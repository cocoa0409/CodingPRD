"""Refusals on the pricing instruments: discounts, combinations, corrections and
invoice lines.

Every fiscal relation in this module is tested at its exact boundary — the refused value
and the admitted neighbour one cent, or one hundredth of a percent, away.
"""

import pytest

from test_helpers import (
    approve_correction,
    create_combination_sale_payload,
    create_invoice_line_payload,
    create_price_schedule_item_payload,
    create_quantity_discount_tier_payload,
    new_correction,
    new_invoice,
    new_item,
    new_schedule,
    read_invoice,
    read_item,
    read_schedule,
    read_wholesaler,
    regulator_headers,
    setup_certified_schedule,
    setup_draft_schedule,
    setup_licensee_base,
    validate_error,
    validate_paginated,
    validate_success,
)


TWO_ITEM_SPECS = [
    {
        "size_ml": 750, "bottles_per_case": 12,
        "case_price_cents": 120_000, "unit_price_cents": 11_000,
    },
    {
        "size_ml": 375, "bottles_per_case": 6,
        "case_price_cents": 30_000, "unit_price_cents": 5_500,
    },
]


# --------------------------------------------------------------------------
# Instruments the state forbids outright (priority 15)
# --------------------------------------------------------------------------

def test_01_a_program_forbidding_both_instruments_refuses_both(api):
    """PRD §3.5: "If the governing program has `quantity_discount_allowed` set to
    `false`, the tier is refused with `ERR_QUANTITY_DISCOUNT_PROHIBITED`"
    PRD §3.5: "If the governing program has `combination_sale_allowed` set to `false`,
    the declaration is refused with `ERR_COMBINATION_SALE_PROHIBITED`."
    PRD §2.10: "Quantity discount tiers require the governing program's
    `quantity_discount_allowed` to be `true`, otherwise
    `ERR_QUANTITY_DISCOUNT_PROHIBITED` on `POST /quantity-discount-tiers`; combination
    sales require `combination_sale_allowed` to be `true`, otherwise
    `ERR_COMBINATION_SALE_PROHIBITED` on `POST /combination-sales`. Both HTTP 422."

    Design: Corner/validations/a_state_program_forbidding_discounts_and_combinations_refuses_both_instruments
    """
    scene = setup_draft_schedule(
        setup_licensee_base(
            program_overrides={
                "state_code": "NV",
                "program_name": "Nevada Price Posting Program",
                "quantity_discount_allowed": False,
                "combination_sale_allowed": False,
            },
            license_number="W-9001",
            legal_name="Silver State Beverage",
        ),
        item_specs=TWO_ITEM_SPECS,
    )
    item_one, item_two = scene["items"][0], scene["items"][1]

    # A 10 percent tier is well inside the default cap; only the prohibition bites.
    validate_error(
        api.create_quantity_discount_tier(
            create_quantity_discount_tier_payload(item_one["id"], min_cases=5, discount_pct=0.10),
            scene["agent_headers"],
        ),
        "ERR_QUANTITY_DISCOUNT_PROHIBITED",
        422,
    )

    # 140,000 clears the 135,000 floor of a 150,000 combination; only the prohibition bites.
    validate_error(
        api.create_combination_sale(
            create_combination_sale_payload(
                scene["schedule"]["id"], [item_one["id"], item_two["id"]], 140_000
            ),
            scene["agent_headers"],
        ),
        "ERR_COMBINATION_SALE_PROHIBITED",
        422,
    )

    _, tier_meta = validate_paginated(
        api.list_quantity_discount_tiers(regulator_headers(), params={"item_id": item_one["id"]})
    )
    assert tier_meta["total_count"] == 0, (
        f"no tier may exist under a prohibiting program, found {tier_meta['total_count']}"
    )

    _, combo_meta = validate_paginated(
        api.list_combination_sales(
            regulator_headers(), params={"schedule_id": scene["schedule"]["id"]}
        )
    )
    assert combo_meta["total_count"] == 0, (
        f"no combination may exist under a prohibiting program, found "
        f"{combo_meta['total_count']}"
    )

    program = validate_success(api.get_state_program(scene["program"]["id"], regulator_headers()))
    assert program["quantity_discount_allowed"] is False, (
        f"the program still forbids discounts, got {program['quantity_discount_allowed']}"
    )
    assert program["combination_sale_allowed"] is False, (
        f"the program still forbids combinations, got {program['combination_sale_allowed']}"
    )


# --------------------------------------------------------------------------
# Fiscal relations (priority 17)
# --------------------------------------------------------------------------

def test_02_case_price_above_the_bottle_aggregate_is_refused_and_equality_is_admitted(api):
    """PRD §3.3: "The pricing relation the state cares about is that a case must never
    cost more than buying the same bottles individually: `unit_price_cents` multiplied by
    `bottles_per_case` must be at least `case_price_cents`, and a violation is refused
    with `ERR_CASE_PRICE_EXCEEDS_UNIT_AGGREGATE`."
    PRD §3.3: "A new item begins in `DRAFT` with `certified_case_price_cents`,
    `certified_unit_price_cents` and `supersedes_item_id` unset and with
    `amendment_count` and `correction_count` both 0."

    Design: Corner/validations/case_price_above_the_bottle_aggregate_is_refused_and_equality_is_admitted
    """
    scene = setup_licensee_base()
    schedule = new_schedule(
        scene["wholesaler"]["id"], scene["program"]["id"], scene["agent_headers"]
    )

    # 10,000 x 12 = 120,000, so 120,001 is one cent too much and 120,000 is exact.
    validate_error(
        api.create_price_schedule_item(
            create_price_schedule_item_payload(
                schedule["id"], scene["brand"]["id"],
                size_ml=750, bottles_per_case=12,
                case_price_cents=120_001, unit_price_cents=10_000,
            ),
            scene["agent_headers"],
        ),
        "ERR_CASE_PRICE_EXCEEDS_UNIT_AGGREGATE",
        422,
    )
    assert read_schedule(schedule["id"])["item_count"] == 0, (
        "the refused item must not be counted on the schedule"
    )

    admitted = validate_success(
        api.create_price_schedule_item(
            create_price_schedule_item_payload(
                schedule["id"], scene["brand"]["id"],
                size_ml=750, bottles_per_case=12,
                case_price_cents=120_000, unit_price_cents=10_000,
            ),
            scene["agent_headers"],
        ),
        201,
    )
    assert admitted["case_price_cents"] == 120_000, (
        f"equality is admitted, got {admitted['case_price_cents']}"
    )
    assert admitted["status"] == "DRAFT", (
        f"a new item begins in DRAFT, got {admitted['status']}"
    )
    assert admitted["certified_case_price_cents"] is None, (
        f"certified_case_price_cents starts unset, got {admitted['certified_case_price_cents']}"
    )
    assert admitted["certified_unit_price_cents"] is None, (
        f"certified_unit_price_cents starts unset, got {admitted['certified_unit_price_cents']}"
    )
    assert admitted["amendment_count"] == 0, (
        f"amendment_count starts at 0, got {admitted['amendment_count']}"
    )
    assert admitted["correction_count"] == 0, (
        f"correction_count starts at 0, got {admitted['correction_count']}"
    )
    assert read_schedule(schedule["id"])["item_count"] == 1, (
        "exactly one of the two attempts landed"
    )


def test_03_discount_above_the_state_cap_is_refused_and_the_cap_itself_is_admitted(api):
    """PRD §3.5: "if `discount_pct` is strictly greater than the program's
    `max_quantity_discount_pct`, it is refused with `ERR_DISCOUNT_EXCEEDS_STATE_CAP` — a
    `discount_pct` exactly equal to the cap is permitted."
    PRD §3.5: "The tier's own price is derived, never supplied:
    `discounted_case_price_cents` is the item's `case_price_cents` multiplied by the
    quantity one minus `discount_pct`, rounded half up to whole cents."

    Design: Corner/validations/discount_percentage_above_the_state_cap_is_refused_and_the_cap_itself_is_admitted
    """
    scene = setup_draft_schedule(setup_licensee_base())
    item = scene["items"][0]
    cap = validate_success(
        api.get_state_program(scene["program"]["id"], regulator_headers())
    )["max_quantity_discount_pct"]
    assert cap == 0.15, f"the default state cap is 0.15, got {cap}"

    validate_error(
        api.create_quantity_discount_tier(
            create_quantity_discount_tier_payload(item["id"], min_cases=5, discount_pct=0.16),
            scene["agent_headers"],
        ),
        "ERR_DISCOUNT_EXCEEDS_STATE_CAP",
        422,
    )

    admitted = validate_success(
        api.create_quantity_discount_tier(
            create_quantity_discount_tier_payload(item["id"], min_cases=5, discount_pct=0.15),
            scene["agent_headers"],
        ),
        201,
    )
    assert admitted["discount_pct"] == 0.15, (
        f"a discount exactly at the cap is permitted, got {admitted['discount_pct']}"
    )
    assert admitted["discounted_case_price_cents"] == 102_000, (
        f"120,000 times 0.85 is 102,000 cents, got {admitted['discounted_case_price_cents']}"
    )
    assert admitted["status"] == "ACTIVE", (
        f"a new tier is ACTIVE, got {admitted['status']}"
    )

    _, meta = validate_paginated(
        api.list_quantity_discount_tiers(regulator_headers(), params={"item_id": item["id"]})
    )
    assert meta["total_count"] == 1, (
        f"only the admitted tier may exist, found {meta['total_count']}"
    )


def test_04_combination_one_cent_below_the_minimum_is_refused_and_the_minimum_is_admitted(api):
    """PRD §3.5: "A `combined_case_price_cents` strictly below the computed
    `min_allowed_price_cents` is refused with `ERR_COMBINATION_BELOW_FLOOR`; a price
    exactly equal to it is permitted."
    PRD §3.5: "Keying the band on the pre-discount floor is load-bearing: a
    `floor_price_cents` of exactly 150,000 lands in the ten percent band and yields a
    `min_allowed_price_cents` of 135,000; keying the band on the discounted value would
    have selected the five percent band and produced 142,500, which is not the rule."

    Design: Corner/validations/combination_price_one_cent_below_the_minimum_allowed_is_refused_and_the_minimum_is_admitted
    """
    scene = setup_draft_schedule(setup_licensee_base(), item_specs=TWO_ITEM_SPECS)
    schedule_id = scene["schedule"]["id"]
    members = [scene["items"][0]["id"], scene["items"][1]["id"]]

    # 120,000 + 30,000 = a 150,000 floor, the ten percent band, a 135,000 minimum.
    validate_error(
        api.create_combination_sale(
            create_combination_sale_payload(schedule_id, members, 134_999),
            scene["agent_headers"],
        ),
        "ERR_COMBINATION_BELOW_FLOOR",
        422,
    )

    admitted = validate_success(
        api.create_combination_sale(
            create_combination_sale_payload(schedule_id, members, 135_000),
            scene["agent_headers"],
        ),
        201,
    )
    assert admitted["floor_price_cents"] == 150_000, (
        f"the floor is the plain sum of member case prices, got "
        f"{admitted['floor_price_cents']}"
    )
    assert admitted["min_allowed_price_cents"] == 135_000, (
        f"a 150,000 floor lands in the ten percent band, got "
        f"{admitted['min_allowed_price_cents']}"
    )
    assert admitted["combined_case_price_cents"] == 135_000, (
        f"a price exactly at the minimum is permitted, got "
        f"{admitted['combined_case_price_cents']}"
    )
    assert admitted["status"] == "ACTIVE", (
        f"a new combination is ACTIVE, got {admitted['status']}"
    )

    _, meta = validate_paginated(
        api.list_combination_sales(regulator_headers(), params={"schedule_id": schedule_id})
    )
    assert meta["total_count"] == 1, (
        f"only the admitted combination may exist, found {meta['total_count']}"
    )


# --------------------------------------------------------------------------
# Correction quota (priority 18)
# --------------------------------------------------------------------------

def test_05_approving_a_third_correction_on_one_schedule_is_refused(api):
    """PRD §3.6: "It requires the correction to be in `SUBMITTED` (otherwise
    `ERR_INVALID_STATE`) and requires the item's schedule to have strictly fewer approved
    corrections than the program's `max_corrections_per_schedule`; at or above that
    number the approval is refused with `ERR_CORRECTION_LIMIT_EXCEEDED`."
    PRD §3.6: "When the schedule's resulting `correction_count` reaches 2, the program's
    `repeat_correction_penalty_cents` is added to the wholesaler's
    `correction_penalty_accrued_cents`, `penalty_exposure_cents` is recomputed and the
    wholesaler's `version` is advanced by 1 — the first correction on a schedule is free,
    the second costs the wholesaler money."

    Design: Corner/validations/approving_a_third_correction_on_one_schedule_returns_correction_limit_exceeded
    """
    scene = setup_certified_schedule()
    item_id = scene["items"][0]["id"]
    schedule_id = scene["schedule"]["id"]
    program = validate_success(api.get_state_program(scene["program"]["id"], regulator_headers()))
    assert program["max_corrections_per_schedule"] == 2, (
        f"the default quota is two approved corrections, got "
        f"{program['max_corrections_per_schedule']}"
    )

    # First correction: 6,000 off 120,000 is a 0.05 variance, inside the clerical limit.
    first = new_correction(item_id, 114_000, 10_800, scene["agent_headers"])
    assert first["variance_pct"] == pytest.approx(0.05), (
        f"6,000 over 120,000 is a 0.05 variance, got {first['variance_pct']}"
    )
    approve_correction(first["id"])
    assert read_schedule(schedule_id)["correction_count"] == 1, (
        "the first approval lifts the schedule's correction_count to 1"
    )
    assert read_wholesaler(scene["wholesaler"]["id"])["correction_penalty_accrued_cents"] == 0, (
        "the first correction on a schedule is free"
    )

    # Second correction: 4,000 off the new 114,000 prior price.
    second = new_correction(item_id, 110_000, 10_500, scene["agent_headers"])
    assert second["prior_case_price_cents"] == 114_000, (
        f"the prior price is the price the first approval wrote, got "
        f"{second['prior_case_price_cents']}"
    )
    assert second["variance_pct"] == pytest.approx(4_000 / 114_000), (
        f"4,000 over 114,000 is the variance, got {second['variance_pct']}"
    )
    approve_correction(second["id"])
    assert read_schedule(schedule_id)["correction_count"] == 2, (
        "the second approval lifts the schedule's correction_count to 2"
    )
    wholesaler_after_second = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler_after_second["correction_penalty_accrued_cents"] == 100_000, (
        f"reaching a schedule correction_count of 2 accrues the repeat-correction "
        f"penalty, got {wholesaler_after_second['correction_penalty_accrued_cents']}"
    )
    assert wholesaler_after_second["penalty_exposure_cents"] == 100_000, (
        f"exposure is the sum of the buckets, got "
        f"{wholesaler_after_second['penalty_exposure_cents']}"
    )

    # Third correction files fine — the quota bites at approval, not at filing.
    third = new_correction(item_id, 108_000, 10_400, scene["agent_headers"])
    assert third["status"] == "SUBMITTED", (
        f"a third correction may be filed, got {third['status']}"
    )
    assert third["variance_pct"] == pytest.approx(2_000 / 110_000), (
        f"2,000 over 110,000 is the variance, got {third['variance_pct']}"
    )

    validate_error(
        api.approve_error_correction(third["id"], regulator_headers()),
        "ERR_CORRECTION_LIMIT_EXCEEDED",
        409,
    )

    item_after = read_item(item_id)
    assert item_after["case_price_cents"] == 110_000, (
        f"the refused approval must not move the item's case price, got "
        f"{item_after['case_price_cents']}"
    )
    assert item_after["unit_price_cents"] == 10_500, (
        f"the refused approval must not move the item's unit price, got "
        f"{item_after['unit_price_cents']}"
    )
    assert item_after["correction_count"] == 2, (
        f"only two corrections were approved, got {item_after['correction_count']}"
    )
    assert read_schedule(schedule_id)["correction_count"] == 2, (
        "the schedule's correction_count is unchanged by the refusal"
    )
    wholesaler_final = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler_final["correction_penalty_accrued_cents"] == 100_000, (
        f"the repeat penalty accrues exactly once, got "
        f"{wholesaler_final['correction_penalty_accrued_cents']}"
    )


# --------------------------------------------------------------------------
# Cardinality on the pricing instruments (priority 19)
# --------------------------------------------------------------------------

def test_06_an_invoice_line_with_no_cases_and_no_bottles_is_refused(api):
    """PRD §3.8: "A line whose `cases_quantity` and `bottles_quantity` are *both* zero is
    degenerate and is refused with `ERR_ZERO_QUANTITY_LINE`."
    PRD §3.8: "Quantities are optional and both default to 0: `cases_quantity` counts
    full cases and must be at least 0, `bottles_quantity` counts loose bottles and must
    be at least 0."
    PRD §3.8: "Two allowances are optional and default to 0:
    `promotional_allowance_cents` and `depletion_allowance_cents`, each at least 0."

    Design: Corner/validations/an_invoice_line_with_no_cases_and_no_bottles_returns_zero_quantity_line
    """
    scene = setup_draft_schedule(setup_licensee_base())
    item_id = scene["items"][0]["id"]
    invoice = new_invoice(scene["wholesaler"]["id"], "2026-08-15T00:00:00Z", scene["agent_headers"])

    # Both quantities omitted, so both default to 0 and the line has nothing on it.
    validate_error(
        api.create_invoice_line(
            create_invoice_line_payload(invoice["id"], item_id, 120_000, 11_000),
            scene["agent_headers"],
        ),
        "ERR_ZERO_QUANTITY_LINE",
        422,
    )
    assert read_invoice(invoice["id"])["line_count"] == 0, (
        "the refused line must not be counted on the invoice"
    )

    # A single loose bottle is enough to make the line non-degenerate.
    admitted = validate_success(
        api.create_invoice_line(
            create_invoice_line_payload(
                invoice["id"], item_id, 120_000, 11_000, bottles_quantity=1
            ),
            scene["agent_headers"],
        ),
        201,
    )
    assert admitted["cases_quantity"] == 0, (
        f"an omitted cases_quantity defaults to 0, got {admitted['cases_quantity']}"
    )
    assert admitted["bottles_quantity"] == 1, (
        f"the single loose bottle is recorded, got {admitted['bottles_quantity']}"
    )
    assert admitted["promotional_allowance_cents"] == 0, (
        f"an omitted promotional allowance defaults to 0, got "
        f"{admitted['promotional_allowance_cents']}"
    )
    assert admitted["depletion_allowance_cents"] == 0, (
        f"an omitted depletion allowance defaults to 0, got "
        f"{admitted['depletion_allowance_cents']}"
    )

    invoice_after = read_invoice(invoice["id"])
    assert invoice_after["line_count"] == 1, (
        f"exactly one of the two attempts landed, got {invoice_after['line_count']}"
    )
    assert invoice_after["validation_status"] == "DRAFT", (
        f"adding a line does not validate the invoice, got "
        f"{invoice_after['validation_status']}"
    )

    _, meta = validate_paginated(
        api.list_invoice_lines(regulator_headers(), params={"invoice_id": invoice["id"]})
    )
    assert meta["total_count"] == 1, (
        f"only the admitted line may exist, found {meta['total_count']}"
    )


def test_07_combination_members_must_be_two_distinct_items_of_the_declared_schedule(api):
    """PRD §3.5: "The array must name at least two **distinct** item identifiers — fewer
    distinct entries than that is refused with `ERR_COMBINATION_TOO_FEW_MEMBERS` — and
    every named member must belong to the declared schedule, a violation being refused
    with `ERR_ITEM_NOT_ON_SAME_SCHEDULE`."
    PRD §2.10: "a combination sale names at least two distinct member items
    (`ERR_COMBINATION_TOO_FEW_MEMBERS`) and every named member belongs to the declared
    schedule (`ERR_ITEM_NOT_ON_SAME_SCHEDULE`), both on `POST /combination-sales`, the
    member-count test evaluated before the membership test."
    PRD §2.10: "Array-length degeneracy is *not* a shape violation — a `member_item_ids`
    array with fewer than two distinct entries passes this gate and is caught at priority
    19."

    Design: Corner/validations/combination_members_must_be_two_distinct_items_of_the_declared_schedule
    """
    scene = setup_draft_schedule(setup_licensee_base(), item_specs=TWO_ITEM_SPECS)
    schedule_id = scene["schedule"]["id"]
    item_one, item_two = scene["items"][0], scene["items"][1]

    # A second schedule of the same wholesaler, whose item is a stranger to the first.
    other_schedule = new_schedule(
        scene["wholesaler"]["id"], scene["program"]["id"], scene["agent_headers"],
        posting_month="2026-10",
    )
    stranger = new_item(
        other_schedule["id"], scene["brand"]["id"], scene["agent_headers"],
        size_ml=375, bottles_per_case=6,
        case_price_cents=30_000, unit_price_cents=5_500,
    )

    # The same identifier twice is one distinct entry, not two.
    validate_error(
        api.create_combination_sale(
            create_combination_sale_payload(
                schedule_id, [item_one["id"], item_one["id"]], 240_000
            ),
            scene["agent_headers"],
        ),
        "ERR_COMBINATION_TOO_FEW_MEMBERS",
        422,
    )

    # Two distinct members, but one of them lives on the other schedule.
    validate_error(
        api.create_combination_sale(
            create_combination_sale_payload(
                schedule_id, [item_one["id"], stranger["id"]], 140_000
            ),
            scene["agent_headers"],
        ),
        "ERR_ITEM_NOT_ON_SAME_SCHEDULE",
        422,
    )

    admitted = validate_success(
        api.create_combination_sale(
            create_combination_sale_payload(
                schedule_id, [item_one["id"], item_two["id"]], 140_000
            ),
            scene["agent_headers"],
        ),
        201,
    )
    assert sorted(admitted["member_item_ids"]) == sorted([item_one["id"], item_two["id"]]), (
        f"the admitted combination names exactly the two items of the declared schedule, "
        f"got {admitted['member_item_ids']}"
    )
    assert admitted["floor_price_cents"] == 150_000, (
        f"120,000 plus 30,000 is the floor, got {admitted['floor_price_cents']}"
    )
    assert admitted["min_allowed_price_cents"] == 135_000, (
        f"a 150,000 floor permits ten percent, got {admitted['min_allowed_price_cents']}"
    )
    assert admitted["status"] == "ACTIVE", (
        f"a new combination is ACTIVE, got {admitted['status']}"
    )

    _, meta = validate_paginated(
        api.list_combination_sales(regulator_headers(), params={"schedule_id": schedule_id})
    )
    assert meta["total_count"] == 1, (
        f"only the admitted combination may exist, found {meta['total_count']}"
    )
