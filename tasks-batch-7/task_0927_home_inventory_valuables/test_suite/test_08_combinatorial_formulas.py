"""Two calculations whose evaluation order is pinned: per-line rounding before
summation in a documentation package, and clip-then-allocate in the claim
settlement arithmetic."""
from test_helpers import (
    add_cataloged_item,
    add_claim_line,
    add_generated_package,
    add_policy,
    add_room,
    adjudicate,
    bootstrap_household,
    make_claims_adjuster_headers,
    open_claim,
    submit_claim,
    validate_success,
)

ADJUSTER_HEADERS = make_claims_adjuster_headers()

FURNITURE_SCHEDULE = {
    "category": "FURNITURE",
    "useful_life_months": 120,
    "annual_depreciation_pct": 10.0,
    "salvage_floor_pct": 10.0,
    "blanket_sublimit_cents": 400000,
    "appraisal_scope": "GENERAL",
    "serial_required": False,
}

COLLECTIBLE_SCHEDULE = {
    "category": "COLLECTIBLE",
    "useful_life_months": 360,
    "annual_depreciation_pct": 2.0,
    "salvage_floor_pct": 50.0,
    "blanket_sublimit_cents": 500000,
    "appraisal_scope": "COLLECTIBLE",
    "serial_required": False,
}


def _setup_half_cent_package_scenario():
    """Three identical FURNITURE items whose exact ACV at the snapshot instant is
    189990.5 cents each, generated into one documentation package."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[FURNITURE_SCHEDULE])
    room = add_room(ctx, name="Living Room", floor_label="1")
    items = [
        add_cataloged_item(
            ctx,
            room["id"],
            150000,
            photo_bytes=80000,
            name=f"Armchair {index}",
            category="FURNITURE",
            acquired_at="2025-11-01T00:00:00Z",
            quantity=1,
            purchase_price_cents=199990,
        )
        for index in (1, 2, 3)
    ]
    policy = add_policy(
        ctx,
        policy_number="NW-3003",
        deductible_cents=50000,
        scheduled_allowance_cents=0,
    )
    package = add_generated_package(ctx, policy["id"])
    ctx.update({"room": room, "items": items, "policy": policy, "package": package})
    return ctx


def test_each_item_acv_lands_on_the_half_cent_and_rounds_up(api):
    """PRD 3.4: "the result is the larger of the raw amount and the salvage floor,
    rounded half up to whole cents **once**, at the very end. No intermediate is
    rounded."
    PRD 2.6: "Wherever a calculation produces a non-integer intermediate, the
    result is converted to cents with **round half up** — a value ending in exactly
    one half cent rounds away from zero to the larger magnitude."

    Design: Difficulty/combinatorial_formula/package_snapshot_rounds_each_line_before_summing
    """
    ctx = _setup_half_cent_package_scenario()

    for item in ctx["items"]:
        row = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
        assert row["acv_value_cents"] == 189991, (
            "199990 * 0.95 is exactly 189990.5 and must round half up to 189991, "
            f"got {row['acv_value_cents']} for {row['name']}"
        )


def test_package_totals_round_every_line_before_summing_them(api):
    """PRD 3.6: "The rounding order is pinned and is **not** interchangeable: round
    every line first, then sum the rounded lines."
    PRD 3.6: "Summing the exact unrounded values and rounding the total once is
    explicitly forbidden; the two orders can differ by up to half a cent per line.
    Three items each with an exact value of 189,990.5 cents produce 569,973 under
    the pinned order and 569,972 under the forbidden one."

    Design: Difficulty/combinatorial_formula/package_snapshot_rounds_each_line_before_summing
    """
    ctx = _setup_half_cent_package_scenario()

    package = validate_success(api.get_package(ctx["package"]["id"], ctx["owner_headers"]))
    assert package["status"] == "GENERATED"
    assert package["line_count"] == 3
    assert package["snapshot_total_effective_cents"] == 569973, (
        "round-per-line then sum yields 3 x 189991 = 569973; got "
        f"{package['snapshot_total_effective_cents']}"
    )
    assert package["snapshot_total_covered_cents"] == 400000, (
        "the FURNITURE sublimit of 400000 caps the covered total"
    )
    assert package["snapshot_coverage_gap_cents"] == 169973


def _setup_clip_then_deductible_scenario():
    """Two COLLECTIBLE items sharing a 500000-cent sublimit under an RCV claim
    with a 100000-cent PRO_RATA deductible; both lines approved."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[COLLECTIBLE_SCHEDULE])
    room = add_room(ctx, name="Gallery", floor_label="1")
    item_a = add_cataloged_item(
        ctx,
        room["id"],
        300000,
        photo_bytes=70000,
        name="Signed Poster",
        category="COLLECTIBLE",
        acquired_at="2024-05-01T00:00:00Z",
        quantity=1,
        serial_number="CO-A1",
        replacement_cost_cents=400000,
    )
    item_b = add_cataloged_item(
        ctx,
        room["id"],
        250000,
        photo_bytes=70000,
        name="Vintage Card",
        category="COLLECTIBLE",
        acquired_at="2024-06-01T00:00:00Z",
        quantity=1,
        serial_number="CO-B1",
        replacement_cost_cents=300000,
    )
    policy = add_policy(
        ctx,
        policy_number="NW-4004",
        deductible_cents=100000,
        scheduled_allowance_cents=0,
    )
    package = add_generated_package(ctx, policy["id"])
    claim = open_claim(
        ctx,
        package["id"],
        policy["id"],
        [room["id"]],
        loss_date="2026-05-01T00:00:00Z",
        peril="THEFT",
        settlement_basis="RCV",
        deductible_mode="PRO_RATA",
    )
    line_a = add_claim_line(ctx, claim["id"], item_a["id"])
    line_b = add_claim_line(ctx, claim["id"], item_b["id"])
    submit_claim(ctx, claim["id"])
    adjudicate(line_a["id"], "APPROVE")
    adjudicate(line_b["id"], "APPROVE")
    ctx.update(
        {
            "room": room,
            "item_a": item_a,
            "item_b": item_b,
            "policy": policy,
            "package": package,
            "claim": claim,
            "line_a": line_a,
            "line_b": line_b,
        }
    )
    return ctx


def test_every_line_is_capped_against_the_category_pool_before_any_deductible(api):
    """PRD 3.7: "For every other line the cap is whatever remains in its item's
    category pool, and that pool is then reduced by the smaller of the line's
    `gross_value_cents` and the cap. Either way the line's `capped_value_cents` is
    the smaller of its `gross_value_cents` and its cap."
    PRD 3.7: "When the basis is `RCV`, the unit value is the item's
    `replacement_cost_cents` divided by that quantity."

    Design: Difficulty/combinatorial_formula/claim_settlement_clips_every_line_before_allocating_any_deductible
    """
    ctx = _setup_clip_then_deductible_scenario()

    line_a = validate_success(api.get_claim_line(ctx["line_a"]["id"], ctx["owner_headers"]))
    line_b = validate_success(api.get_claim_line(ctx["line_b"]["id"], ctx["owner_headers"]))

    assert line_a["gross_value_cents"] == 400000
    assert line_a["capped_value_cents"] == 400000, (
        "the first line in creation order draws on the full 500000 sublimit"
    )
    assert line_b["gross_value_cents"] == 300000
    assert line_b["capped_value_cents"] == 100000, (
        "only 100000 of the shared COLLECTIBLE sublimit survives the first line; got "
        f"{line_b['capped_value_cents']}"
    )


def test_pro_rata_deductible_is_allocated_over_the_clipped_values(api):
    """PRD 3.7: "The apparent circularity — the sublimit clipping needs the gross
    values, the deductible needs the clipped values, and the reported total needs
    both — is resolved by a **pinned evaluation order**: all of step 1 runs, then
    all of step 2, then all of step 3. No step may look ahead at a later step's
    output."
    PRD 3.7: "Under the `PRO_RATA` mode, every line in scope **except the anchor**
    takes a share of the policy's `deductible_cents` proportional to its capped
    value — the deductible multiplied by that line's `capped_value_cents` divided
    by the base, rounded half up to whole cents."
    PRD 3.7: "Settlement re-runs the deductible allocation of step 3 over the
    approved subset only, writes `total_settlement_cents` as the sum of the
    approved lines' `net_settlement_cents`, moves the claim `UNDER_REVIEW →
    SETTLED`, returns every item this claim froze `FROZEN → CATALOGED` with
    `frozen_by_claim_id` cleared to null, lowers the household's
    `frozen_item_count` by exactly the claim's `frozen_item_count` and recomputes
    `records_freeze_active`."

    Design: Difficulty/combinatorial_formula/claim_settlement_clips_every_line_before_allocating_any_deductible
    """
    ctx = _setup_clip_then_deductible_scenario()

    settled = validate_success(
        api.settle_claim(ctx["claim"]["id"], {}, ADJUSTER_HEADERS)
    )
    assert settled["status"] == "SETTLED"

    line_a = validate_success(api.get_claim_line(ctx["line_a"]["id"], ctx["owner_headers"]))
    line_b = validate_success(api.get_claim_line(ctx["line_b"]["id"], ctx["owner_headers"]))

    assert line_a["deductible_share_cents"] == 80000, (
        "shares are proportional to the CLIPPED values 400000 / 100000, not the "
        f"unclipped 400000 / 300000; got {line_a['deductible_share_cents']}"
    )
    assert line_a["net_settlement_cents"] == 320000
    assert line_b["deductible_share_cents"] == 20000
    assert line_b["net_settlement_cents"] == 80000
    assert settled["total_settlement_cents"] == 400000
