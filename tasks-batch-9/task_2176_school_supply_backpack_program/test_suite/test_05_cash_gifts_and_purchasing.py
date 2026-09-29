"""Cash gifts and their restrictions, purchase-order costing and the funding waterfall."""

from test_helpers import (
    ApiErrorId,
    assert_cash_conservation,
    assert_cash_donation,
    assert_purchase_order,
    assert_unit_conservation,
    create_backpack,
    create_cash_gift,
    create_collecting_cycle,
    create_pencil,
    create_purchase_order,
    create_school,
    create_supply_item,
    cycle_version,
    move_order,
    read_position,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PD = TEST_USERS["program_director_headers"]
PD_ALT = TEST_USERS["program_director_alt_headers"]
WL = TEST_USERS["warehouse_lead_headers"]
DR = TEST_USERS["donor_relations_headers"]


def _waterfall_scenario():
    """A COLLECTING cycle holding, oldest first, a 30000-cent backpack-restricted gift,
    a 50000-cent unrestricted gift and a 40000-cent school-restricted gift, plus one
    DRAFT purchase order closing a 40-unit backpack gap."""
    school = create_school()
    backpack = create_backpack()
    cycle = create_collecting_cycle()
    item_gift = create_cash_gift(
        cycle["id"],
        donor_name="Backpack Fund",
        amount_cents=30_000,
        restriction_type="ITEM_RESTRICTED",
        restricted_supply_item_id=backpack["id"],
    )
    open_gift = create_cash_gift(
        cycle["id"], donor_name="Acme Corp", amount_cents=50_000, restriction_type="UNRESTRICTED"
    )
    school_gift = create_cash_gift(
        cycle["id"],
        donor_name="Lincoln PTA",
        amount_cents=40_000,
        restriction_type="SCHOOL_RESTRICTED",
        restricted_school_id=school["id"],
    )
    order = create_purchase_order(cycle["id"], backpack["id"], requested_unit_gap=40)
    return {
        "cycle": cycle,
        "backpack": backpack,
        "item_gift": item_gift,
        "open_gift": open_gift,
        "school_gift": school_gift,
        "order": order,
    }


def test_cash_gift_restriction_type_and_foreign_key_must_agree(api):
    """PRD §3.5: "When `restriction_type` is `ITEM_RESTRICTED`,
    `restricted_supply_item_id` is required and `restricted_school_id` must be null."
    PRD §3.5: "Any other combination is refused with `ERR_CASH_RESTRICTION_VIOLATION`."

    Design: Corner/entities/cash_donation_restriction_type_and_fk_must_agree
    """
    cycle = create_collecting_cycle()

    response = api.create_cash_donation(
        {
            "drive_cycle_id": cycle["id"],
            "donor_name": "Backpack Fund",
            "amount_cents": 30_000,
            "restriction_type": "ITEM_RESTRICTED",
        },
        DR,
    )
    validate_error(response, ApiErrorId.ERR_CASH_RESTRICTION_VIOLATION.value, expected_status=422)

    reread = validate_success(api.get_drive_cycle(cycle["id"], PD))
    assert reread["cash_received_cents"] == 0
    rows, _ = validate_paginated(
        api.list_cash_donations(DR, params={"drive_cycle_id": cycle["id"]})
    )
    assert rows == [], "a refused gift must not be persisted"


def test_booking_a_gift_refreshes_every_cash_aggregate_on_the_cycle(api):
    """PRD §3.5: "Booking a gift refreshes four numbers on the cycle:
    `cash_received_cents`, which sums `amount_cents` over every gift of the cycle
    regardless of restriction; `cash_available_cents`, which is `cash_received_cents`
    minus `cash_allocated_cents`; `unrestricted_gross_cents`, which sums `amount_cents`
    over only those gifts whose `restriction_type` is `UNRESTRICTED` and which is taken
    **gross**, never net of what has already been allocated; and
    `supplemental_cap_cents`, described in §3.8."
    PRD §3.8: "Whenever a cash gift is booked, the cycle's `supplemental_cap_cents` is
    recomputed as fifteen percent of its `unrestricted_gross_cents`, **floored** rather
    than rounded to a whole cent."

    Design: Corner/cross_cutting_complexity_layers/cash_aggregates_are_reconciled_on_every_gift
    """
    cycle = create_collecting_cycle()
    backpack = create_backpack()
    create_cash_gift(
        cycle["id"], donor_name="Acme Corp", amount_cents=50_000, restriction_type="UNRESTRICTED"
    )

    second = create_cash_gift(
        cycle["id"],
        donor_name="Backpack Fund",
        amount_cents=30_000,
        restriction_type="ITEM_RESTRICTED",
        restricted_supply_item_id=backpack["id"],
    )
    assert_cash_donation(second)

    reread = validate_success(api.get_drive_cycle(cycle["id"], PD))
    assert reread["cash_received_cents"] == 80_000
    assert reread["cash_allocated_cents"] == 0
    assert reread["cash_available_cents"] == 80_000
    assert reread["unrestricted_gross_cents"] == 50_000, (
        "only the UNRESTRICTED gift feeds the gross figure"
    )
    assert reread["supplemental_cap_cents"] == 7_500, "floor(50000 * 0.15)"
    assert_cash_conservation(reread)

    rows, meta = validate_paginated(
        api.list_cash_donations(DR, params={"drive_cycle_id": cycle["id"]})
    )
    assert meta["total_count"] == 2


def test_purchase_order_pack_rounding_fixes_ordered_quantity_and_subtotal(api):
    """PRD §3.5: "First, the wholesaler only sells whole packs, so the number of packs
    is the `requested_unit_gap` divided by the item's `bulk_pack_size` and rounded
    **up** to a whole number, and `ordered_qty` is that pack count multiplied back by
    `bulk_pack_size`."
    PRD §3.5: "Second, `line_subtotal_cents` is `ordered_qty` multiplied by the item's
    `unit_cost_cents`."

    Design: Difficulty/combinatorial_formula/purchase_admin_fee_rounded_per_pack_then_summed_mode_b
    """
    cycle = create_collecting_cycle()
    glue = create_supply_item(
        sku="GLU-03", name="Glue stick 3-pack", unit_cost_cents=175, bulk_pack_size=3
    )

    order = validate_success(
        api.create_purchase_order(
            {
                "drive_cycle_id": cycle["id"],
                "supply_item_id": glue["id"],
                "requested_unit_gap": 20,
            },
            WL,
        ),
        expected_status=201,
    )
    assert_purchase_order(order)
    assert order["ordered_qty"] == 21, "ceil(20/3) = 7 packs of 3 units"
    assert order["line_subtotal_cents"] == 3675, "21 units at 175 cents"


def test_administration_fee_is_rounded_per_pack_then_summed(api):
    """PRD §3.5: "Fourth, the fee is levied **per pack and rounded per pack**: the cost
    of one pack is `bulk_pack_size` multiplied by `unit_cost_cents`, the fee for one
    pack is that pack cost multiplied by the selected rate and then rounded half up to
    a whole cent, and `admin_fee_cents` is that rounded per-pack fee multiplied by the
    number of packs."
    PRD §3.5: "Finally, `total_cost_cents` is `line_subtotal_cents` plus
    `admin_fee_cents`, and it is the amount the cash waterfall must cover in full."

    Design: Difficulty/combinatorial_formula/purchase_admin_fee_rounded_per_pack_then_summed_mode_b
    """
    cycle = create_collecting_cycle()
    glue = create_supply_item(
        sku="GLU-03", name="Glue stick 3-pack", unit_cost_cents=175, bulk_pack_size=3
    )

    order = create_purchase_order(cycle["id"], glue["id"], requested_unit_gap=20)

    assert order["admin_fee_cents"] == 329, (
        "round_half_up(525 * 0.09) = 47 cents a pack, times 7 packs"
    )
    assert order["total_cost_cents"] == 4004, "3675 + 329"


def test_fee_tier_is_selected_from_the_subtotal_at_its_upper_boundary(api):
    """PRD §3.5: "Third — and this is the step most easily got wrong — the
    administration fee rate is selected from the **subtotal**, never from the total:
    the rate is nine percent when `line_subtotal_cents` is 50,000 cents or less, seven
    percent when `line_subtotal_cents` is above 50,000 cents and at most 200,000 cents,
    and five percent when `line_subtotal_cents` is above 200,000 cents."

    Design: Difficulty/combinatorial_formula/purchase_fee_tier_keyed_on_subtotal_not_total_mode_c
    """
    cycle = create_collecting_cycle()
    marker = create_supply_item(
        sku="MRK-25", name="Marker 25-pack", unit_cost_cents=500, bulk_pack_size=25
    )

    order = create_purchase_order(cycle["id"], marker["id"], requested_unit_gap=100)

    assert order["line_subtotal_cents"] == 50_000, "exactly on the nine-percent boundary"
    assert order["admin_fee_cents"] == 4500, (
        "4 packs at round_half_up(12500 * 0.09) = 1125 cents each"
    )


def test_fee_tier_is_not_re_read_off_the_resulting_total(api):
    """PRD §3.5: "Reading the tier off `total_cost_cents` is circular, because the total
    depends on the fee, which depends on the tier, and it is wrong."
    PRD §3.5: "Finally, `total_cost_cents` is `line_subtotal_cents` plus
    `admin_fee_cents`, and it is the amount the cash waterfall must cover in full."

    Design: Difficulty/combinatorial_formula/purchase_fee_tier_keyed_on_subtotal_not_total_mode_c
    """
    cycle = create_collecting_cycle()
    marker = create_supply_item(
        sku="MRK-25", name="Marker 25-pack", unit_cost_cents=500, bulk_pack_size=25
    )

    order = create_purchase_order(cycle["id"], marker["id"], requested_unit_gap=100)

    assert order["total_cost_cents"] == 54_500, (
        "50000 + 4500; the seven-percent tier of the 54500 total is never consulted"
    )
    assert order["admin_fee_cents"] != 3500, (
        "3500 is the answer produced by keying the tier off the total"
    )
    assert_purchase_order(order)


def test_submission_walks_the_waterfall_item_restricted_bucket_first(api):
    """PRD §3.5: "Bucket one holds the cash gifts of the same drive cycle whose
    `restriction_type` is `ITEM_RESTRICTED`, whose `restricted_supply_item_id` equals
    the order's `supply_item_id`, and whose `available_cents` is greater than 0,
    ordered by `created_at` ascending."
    PRD §3.5: "Gifts marked `SCHOOL_RESTRICTED` are never eligible at all: a purchase
    order is a cycle-level object with no beneficiary school."
    PRD §3.5: "It is `RECEIVED` while `allocated_cents` is 0, `PARTIALLY_ALLOCATED`
    while `allocated_cents` is greater than 0 but strictly less than `amount_cents`,
    and `FULLY_ALLOCATED` once `allocated_cents` equals `amount_cents`."

    Design: Difficulty/compensating_invariant/submit_then_cancel_purchase_order_conserves_donated_cents
    """
    scene = _waterfall_scenario()
    order = scene["order"]
    assert order["ordered_qty"] == 42, "ceil(40/6) = 7 packs of 6 backpacks"
    assert order["line_subtotal_cents"] == 60_900
    assert order["admin_fee_cents"] == 4263, "7 packs at round_half_up(8700 * 0.07) = 609"
    assert order["total_cost_cents"] == 65_163

    submitted = submit_order(order["id"], scene["cycle"]["id"])
    assert submitted["status"] == "SUBMITTED"

    item_gift = validate_success(api.get_cash_donation(scene["item_gift"]["id"], DR))
    assert item_gift["allocated_cents"] == 30_000
    assert item_gift["status"] == "FULLY_ALLOCATED"

    open_gift = validate_success(api.get_cash_donation(scene["open_gift"]["id"], DR))
    assert open_gift["allocated_cents"] == 35_163, "65163 minus the 30000 taken from bucket one"
    assert open_gift["available_cents"] == 14_837
    assert open_gift["status"] == "PARTIALLY_ALLOCATED"

    school_gift = validate_success(api.get_cash_donation(scene["school_gift"]["id"], DR))
    assert school_gift["allocated_cents"] == 0

    cycle = validate_success(api.get_drive_cycle(scene["cycle"]["id"], PD))
    assert cycle["cash_allocated_cents"] == 65_163
    assert cycle["cash_available_cents"] == 54_837
    assert_cash_conservation(cycle)


def test_cancelling_a_submitted_order_returns_every_gift_to_its_prior_allocation(api):
    """PRD §3.5: "From `SUBMITTED` and from `APPROVED` the effects are identical and are
    a true compensation: the `funding_allocations` list is replayed in **reverse**
    order, each entry's gift has its `allocated_cents` decreased by exactly that
    entry's `amount_cents` and its derived `status` recomputed, and the list is then
    emptied."
    PRD §2.9: "Submitting an order and then cancelling it must return every gift to
    the exact `allocated_cents` it held beforehand, gift by gift."

    Design: Difficulty/compensating_invariant/submit_then_cancel_purchase_order_conserves_donated_cents
    """
    scene = _waterfall_scenario()
    submit_order(scene["order"]["id"], scene["cycle"]["id"])

    cancelled = validate_success(
        move_order(scene["order"]["id"], scene["cycle"]["id"], "CANCELLED", headers=PD)
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["funding_allocations"] == []

    for key in ("item_gift", "open_gift", "school_gift"):
        gift = validate_success(api.get_cash_donation(scene[key]["id"], DR))
        assert gift["allocated_cents"] == 0, f"{key} must be restored to its prior allocation"
        assert gift["status"] == "RECEIVED"
        assert_cash_donation(gift)

    cycle = validate_success(api.get_drive_cycle(scene["cycle"]["id"], PD))
    assert cycle["cash_received_cents"] == 120_000
    assert cycle["cash_allocated_cents"] == 0
    assert cycle["cash_available_cents"] == 120_000
    assert_cash_conservation(cycle)


def test_school_restricted_gift_alone_cannot_fund_a_cycle_level_order(api):
    """PRD §3.5: "Gifts marked `SCHOOL_RESTRICTED` are never eligible at all: a
    purchase order is a cycle-level object with no beneficiary school."
    PRD §3.5: "If any amount is still outstanding after both buckets are exhausted, the
    submission is refused with `ERR_INSUFFICIENT_FUNDS` and **nothing at all is
    written** — no partial allocation is left behind."

    Design: Corner/calculations/school_restricted_gift_cannot_fund_a_cycle_level_order
    """
    school = create_school()
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    gift = create_cash_gift(
        cycle["id"],
        donor_name="Lincoln PTA",
        amount_cents=100_000,
        restriction_type="SCHOOL_RESTRICTED",
        restricted_school_id=school["id"],
    )
    order = create_purchase_order(cycle["id"], pencil["id"], requested_unit_gap=24)

    response = move_order(order["id"], cycle["id"], "SUBMITTED")
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value, expected_status=409)

    reread = validate_success(api.get_purchase_order(order["id"], WL))
    assert reread["status"] == "DRAFT"
    assert reread["funding_allocations"] == []

    gift_after = validate_success(api.get_cash_donation(gift["id"], DR))
    assert gift_after["allocated_cents"] == 0
    assert gift_after["status"] == "RECEIVED"
    assert validate_success(api.get_drive_cycle(cycle["id"], PD))["cash_allocated_cents"] == 0


def test_purchase_order_cannot_be_approved_straight_from_draft(api):
    """PRD §3.5: "A purchase-order move that is not declared from the order's current
    `status` is rejected with `ERR_INVALID_ORDER_STATE`."
    PRD §3.5: "Approval belongs to a `ProgramDirector` alone and moves `SUBMITTED` to
    `APPROVED`."

    Design: Corner/state_machines/purchase_order_cannot_be_approved_straight_from_draft
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    create_cash_gift(
        cycle["id"], donor_name="Acme Corp", amount_cents=20_000, restriction_type="UNRESTRICTED"
    )
    order = create_purchase_order(cycle["id"], pencil["id"], requested_unit_gap=24)

    response = api.transition_purchase_order(
        order["id"],
        {
            "target_status": "APPROVED",
            "expected_drive_cycle_version": cycle_version(cycle["id"], PD),
        },
        PD,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ORDER_STATE.value, expected_status=409)

    assert validate_success(api.get_purchase_order(order["id"], WL))["status"] == "DRAFT"
    assert validate_success(api.get_drive_cycle(cycle["id"], PD))["cash_allocated_cents"] == 0


def test_purchase_order_receipt_credits_inventory_and_clears_the_expectation(api):
    """PRD §3.5: "On receipt the goods land: `ordered_qty` is added to the position's
    `on_hand_qty` and to its `purchased_received_qty`, and subtracted from its
    `in_transit_qty`, so what was expectation becomes holding without disturbing the
    conservation identity."

    Design: Corner/state_machines/purchase_order_receipt_credits_inventory_and_clears_in_transit
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    gift = create_cash_gift(
        cycle["id"], donor_name="Acme Corp", amount_cents=20_000, restriction_type="UNRESTRICTED"
    )
    order = create_purchase_order(cycle["id"], pencil["id"], requested_unit_gap=24)
    submit_order(order["id"], cycle["id"])
    validate_success(move_order(order["id"], cycle["id"], "APPROVED", headers=PD))

    received = validate_success(move_order(order["id"], cycle["id"], "RECEIVED", headers=WL))
    assert received["status"] == "RECEIVED"
    assert received["total_cost_cents"] == 6540, "6000 subtotal plus 2 packs at 270 cents"

    position = read_position(cycle["id"], pencil["id"])
    assert position["on_hand_qty"] == 24
    assert position["purchased_received_qty"] == 24
    assert position["in_transit_qty"] == 0
    assert_unit_conservation(position)

    cycle_after = validate_success(api.get_drive_cycle(cycle["id"], PD))
    assert cycle_after["cash_allocated_cents"] == 6540
    assert cycle_after["cash_available_cents"] == 13_460
    gift_after = validate_success(api.get_cash_donation(gift["id"], DR))
    assert gift_after["allocated_cents"] == 6540
    assert gift_after["status"] == "PARTIALLY_ALLOCATED"


def test_stale_drive_cycle_version_blocks_a_second_submission(api):
    """PRD §2.8: "If the supplied value does not equal the cycle's current `version`,
    the request is rejected with `ERR_STALE_CYCLE_VERSION` and HTTP 412, and nothing is
    written — no allocation is made, no compensation is replayed, no inventory is
    credited."

    Design: Corner/cross_cutting_complexity_layers/stale_drive_cycle_version_is_rejected_with_412
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    gift = create_cash_gift(
        cycle["id"], donor_name="Acme Corp", amount_cents=40_000, restriction_type="UNRESTRICTED"
    )
    first = create_purchase_order(cycle["id"], pencil["id"], requested_unit_gap=24)
    second = create_purchase_order(cycle["id"], pencil["id"], requested_unit_gap=24)

    observed = cycle_version(cycle["id"], WL)
    validate_success(
        api.transition_purchase_order(
            first["id"],
            {"target_status": "SUBMITTED", "expected_drive_cycle_version": observed},
            WL,
        )
    )

    response = api.transition_purchase_order(
        second["id"],
        {"target_status": "SUBMITTED", "expected_drive_cycle_version": observed},
        WL,
    )
    validate_error(response, ApiErrorId.ERR_STALE_CYCLE_VERSION.value, expected_status=412)

    reread = validate_success(api.get_purchase_order(second["id"], WL))
    assert reread["status"] == "DRAFT"
    assert reread["funding_allocations"] == []
    assert validate_success(api.get_purchase_order(first["id"], WL))["status"] == "SUBMITTED"
    assert validate_success(api.get_drive_cycle(cycle["id"], PD))["cash_allocated_cents"] == 6540
    assert validate_success(api.get_cash_donation(gift["id"], DR))["allocated_cents"] == 6540


def test_the_operator_who_submitted_an_order_may_not_approve_it(api):
    """PRD §2.1: "Where a purchase order is concerned, the separation is enforced rather
    than merely encouraged: the operator identifier that approves an order must differ
    from the one recorded as having submitted it, and an attempt to self-approve is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/purchase_order_submitter_cannot_approve_their_own_order
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    create_cash_gift(
        cycle["id"], donor_name="Acme Corp", amount_cents=20_000, restriction_type="UNRESTRICTED"
    )
    order = create_purchase_order(cycle["id"], pencil["id"], requested_unit_gap=24)

    submitted = validate_success(
        api.transition_purchase_order(
            order["id"],
            {
                "target_status": "SUBMITTED",
                "expected_drive_cycle_version": cycle_version(cycle["id"], PD),
            },
            PD,
        )
    )
    assert submitted["submitted_by_user_id"] == "pd-1"

    response = api.transition_purchase_order(
        order["id"],
        {
            "target_status": "APPROVED",
            "expected_drive_cycle_version": cycle_version(cycle["id"], PD),
        },
        PD,
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403)

    reread = validate_success(api.get_purchase_order(order["id"], WL))
    assert reread["status"] == "SUBMITTED"
    assert reread["approved_by_user_id"] is None
