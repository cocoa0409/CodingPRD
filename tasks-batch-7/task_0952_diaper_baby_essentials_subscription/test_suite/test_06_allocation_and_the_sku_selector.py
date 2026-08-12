"""Allocation: the candidate selector, the waterfall, and the four empty-pool diagnoses."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cycle,
    assert_cycle_line,
    cycle_lines,
    make_sku,
    read_cycle,
    set_clock,
    setup_allocated_cycle,
    setup_household,
    unique_code,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import allocate_cycle, generate_cycle

OPS = TEST_USERS["ops_admin_headers"]


def test_an_allocated_cycle_reports_every_declared_money_field(api):
    """PRD §3.5: "It begins by freezing `stage_at_allocation` to the child's current
    `stage` — that frozen value is what the box was built for, whatever the child's stage
    does later, and it stays null while the cycle is still `PLANNED`."
    PRD §3.5: "Each cycle also receives a `sequence_number`, the 1-based ordinal of that
    cycle within its subscription, assigned at generation."
    PRD §3.7: "A pricing preview read returns this whole breakdown without mutating
    anything: `subtotal_cents`, `shipping_cents`, `gift_credit_applied_cents`,
    `referral_credit_applied_cents`, `loyalty_redemption_applied_cents`,
    `loyalty_points_redeemed`, `promo_discount_cents`, `total_due_cents` and
    `points_earn_base_cents`."

    Design: Corner/entities/corner_cycle_retrieval_returns_every_declared_money_field
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="read")
    data = validate_success(api.get_cycle(cycle["id"], ctx["headers"]))
    assert_cycle(data)
    assert data["subtotal_cents"] == 2400
    assert data["shipping_cents"] == 599
    assert data["total_due_cents"] == 2999
    assert data["gift_credit_applied_cents"] == 0
    assert data["referral_credit_applied_cents"] == 0
    assert data["loyalty_redemption_applied_cents"] == 0
    assert data["promo_discount_cents"] == 0
    assert data["stage_at_allocation"] == "S2"
    assert data["sequence_number"] == 1


def test_the_allocation_response_already_carries_the_final_figures(api):
    """PRD §3.5: "With lines in place, each line's `unit_price_cents` is set to the
    effective per-pack price of its SKU and its `line_total_cents` to `quantity_packs`
    multiplied by `unit_price_cents`, computed exactly as integers per line."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/consistency_model/corner_allocation_response_is_already_final
    """
    ctx = setup_household(api, email_prefix="immed")
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    written = validate_success(api.allocate_cycle(cycle["id"], OPS))
    read_back = validate_success(api.get_cycle(cycle["id"], ctx["headers"]))

    assert written["subtotal_cents"] == 2400 and read_back["subtotal_cents"] == 2400
    assert written["shipping_cents"] == 599 and read_back["shipping_cents"] == 599
    assert written["total_due_cents"] == 2999 and read_back["total_due_cents"] == 2999


def test_the_selector_breaks_a_full_tie_on_ascending_created_at(api):
    """PRD §3.5: "Candidates are ranked by ascending `pack_price_cents` first; ties are
    broken by descending `pack_size_units`; remaining ties are broken by ascending
    `created_at`. A SKU's `id` is never used as a sort key anywhere in this system."
    PRD §3.5: "Starting with a remaining requirement equal to the subscription's
    `pack_count`, the server walks the candidates in rank order and takes from each the
    smaller of the remaining requirement and that SKU's `stock_packs`."

    Design: Corner/cross_cutting_layers/corner_allocation_selector_tie_breaks_on_created_at
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    first = make_sku(api, code=unique_code("S2-FIRST"), name="Stage 2 First")
    set_clock(api, "2026-06-01T01:00:00Z")
    second = make_sku(api, code=unique_code("S2-SECOND"), name="Stage 2 Second")

    ctx = setup_household(api, clock="2026-06-01T01:00:00Z", with_sku=False, email_prefix="tie")
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocate_cycle(api, cycle["id"])

    lines = cycle_lines(api, cycle["id"])
    assert len(lines) == 1, f"a single fully stocked SKU covers the requirement, got {len(lines)} lines"
    assert lines[0]["sku_id"] == first["id"], "the earlier-created SKU wins the tie"
    assert validate_success(api.get_sku(first["id"], OPS))["stock_packs"] == 48
    assert validate_success(api.get_sku(second["id"], OPS))["stock_packs"] == 50


def test_an_allergen_blocked_pool_reports_the_allergen_error(api):
    """PRD §3.5: "Diagnosing an empty candidate pool is done by the earliest rung that
    explains it, and the ordering matters because all four errors are plausible at once. If
    at least one SKU at the child's stage was excluded solely by the allergen screen, the
    refusal is `ERR_ALLERGEN_BLOCKED`."
    PRD §3.2: "If the SKU carries any tag the child is severely sensitive to, the SKU is
    ineligible, on either product line."

    Design: Corner/validations/corner_allergen_blocked_beats_no_eligible_sku_at_allocation
    """
    ctx = setup_household(
        api,
        email_prefix="allergy",
        sku_overrides={
            "code": unique_code("S2-FRAG"),
            "name": "Stage 2 Fragranced",
            "allergen_tags": ["FRAGRANCE"],
        },
        activate_subscription=False,
    )
    validate_success(
        api.create_allergen_flag(
            ctx["child"]["id"],
            {"allergen_tag": "FRAGRANCE", "severity": "SEVERE"},
            ctx["headers"],
        ),
        201,
    )
    validate_success(api.activate_subscription(ctx["subscription"]["id"], ctx["headers"]))
    cycle = generate_cycle(api, ctx["subscription"]["id"])

    resp = api.allocate_cycle(cycle["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_BLOCKED.value, 422)

    assert read_cycle(api, cycle["id"])["status"] == "PLANNED"
    _lines, meta = validate_paginated(api.list_cycle_lines(OPS, {"cycle_id": cycle["id"]}))
    assert meta["total_count"] == 0
    assert validate_success(api.get_sku(ctx["sku"]["id"], OPS))["stock_packs"] == 50


def test_a_hypoallergenic_required_child_facing_a_standard_only_catalog(api):
    """PRD §3.5: "If it was excluded solely by the child's `hypoallergenic_required` flag,
    the refusal is `ERR_HYPOALLERGENIC_REQUIRED`."
    PRD §3.2: "A child whose `hypoallergenic_required` is true must never receive a SKU
    whose `line` is `STANDARD`, and an attempt to do so is refused with
    `ERR_HYPOALLERGENIC_REQUIRED` (HTTP 422); that rule guards all three of the same
    operations the allergen screen guards — a cycle allocation, a line substitution and a
    gift claimed as a shipped item."

    Design: Corner/validations/corner_hypoallergenic_required_child_rejects_standard_only_catalog
    """
    ctx = setup_household(
        api,
        email_prefix="needhypo",
        child_overrides={"hypoallergenic_required": True},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    resp = api.allocate_cycle(cycle["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_HYPOALLERGENIC_REQUIRED.value, 422)
    assert read_cycle(api, cycle["id"])["status"] == "PLANNED"


def test_a_plan_forbidding_hypoallergenic_facing_a_hypo_only_catalog(api):
    """PRD §3.5: "If it was excluded solely because the plan sets `allows_hypoallergenic`
    to false, the refusal is `ERR_HYPOALLERGENIC_NOT_ALLOWED`."
    PRD §3.2: "Conversely, a subscription whose plan sets `allows_hypoallergenic` to false
    must never receive a SKU whose `line` is `HYPOALLERGENIC`, and an attempt to do so is
    refused with `ERR_HYPOALLERGENIC_NOT_ALLOWED` (HTTP 422)"

    Design: Corner/validations/corner_plan_forbidding_hypoallergenic_rejects_hypo_only_catalog
    """
    ctx = setup_household(
        api,
        email_prefix="nohypo",
        plan_overrides={"code": unique_code("NOHYPO"), "allows_hypoallergenic": False},
        sku_overrides={
            "code": unique_code("S2-HYPO"),
            "name": "Stage 2 Hypoallergenic",
            "line": "HYPOALLERGENIC",
            "pack_price_cents": 1400,
        },
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    resp = api.allocate_cycle(cycle["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_HYPOALLERGENIC_NOT_ALLOWED.value, 422)
    assert validate_success(api.get_sku(ctx["sku"]["id"], OPS))["stock_packs"] == 50


def test_an_empty_stage_in_the_catalog_reports_no_eligible_sku(api):
    """PRD §3.5: "Only when no `ACTIVE` SKU exists at the child's stage at all does the
    refusal become `ERR_NO_ELIGIBLE_SKU` (HTTP 409)."
    PRD §3.5: "It begins by freezing `stage_at_allocation` to the child's current `stage` —
    that frozen value is what the box was built for, whatever the child's stage does later,
    and it stays null while the cycle is still `PLANNED`."

    Design: Corner/validations/corner_no_eligible_sku_when_catalog_has_no_matching_stage
    """
    ctx = setup_household(
        api,
        email_prefix="nosku",
        sku_overrides={"code": unique_code("S5-STD"), "name": "Stage 5 Standard",
                       "stage": "S5", "pack_price_cents": 1600},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    resp = api.allocate_cycle(cycle["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_SKU.value, 409)
    assert read_cycle(api, cycle["id"])["stage_at_allocation"] is None


def test_insufficient_total_stock_never_persists_a_partial_allocation(api):
    """PRD §3.5: "If the candidates are exhausted while a requirement remains, the entire
    allocation fails with `ERR_SKU_OUT_OF_STOCK` (HTTP 409) and *no* cycle line is
    persisted — a partial allocation is never stored."

    Design: Corner/validations/corner_partial_stock_never_persists_a_partial_allocation
    """
    ctx = setup_household(
        api,
        email_prefix="stockout",
        sku_overrides={"code": unique_code("S2-THIN"), "name": "Stage 2 Thin Stock",
                       "stock_packs": 1},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    resp = api.allocate_cycle(cycle["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_SKU_OUT_OF_STOCK.value, 409)

    assert validate_success(api.get_sku(ctx["sku"]["id"], OPS))["stock_packs"] == 1, (
        "the take that was already computed must be rolled back with the allocation"
    )
    _lines, meta = validate_paginated(api.list_cycle_lines(OPS, {"cycle_id": cycle["id"]}))
    assert meta["total_count"] == 0
    assert read_cycle(api, cycle["id"])["subtotal_cents"] == 0
