"""Recording lots in the field, entering findings, and stamping the fee."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_animal_lot,
    assert_inspection_order,
    assert_instant_equals,
    create_bill_of_sale,
    create_lot_payload,
    enrol_owner,
    enter_finding,
    make_field_inspector_headers,
    present_lot,
    read_lot,
    read_order,
    read_owner,
    record_brand,
    record_finding_payload,
    setup_order_in_field,
    setup_two_lot_rounding_order,
    setup_zero_and_single_lot_orders,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

BOARD_ADMIN = TEST_USERS["board_admin_headers"]
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


# ─── The administrative surcharge rounding order ──────────────────────────────

def test_administrative_surcharge_is_rounded_per_lot_before_the_lots_are_summed(api):
    """PRD §3.9: "The board charges 110 cents for each of the first 50 head presented
    under the order, 85 cents for each head from the fifty-first through the
    two-hundredth, and 60 cents for every head beyond the two-hundredth."
    PRD §3.9: "Each lot's own base charge is then loaded with an administrative
    surcharge of 12.5 percent of that base, and the point at which the board rounds is
    part of the rule rather than an accident of implementation: the surcharge is rounded
    half up to whole cents **per lot**, and only the already-rounded per-lot amounts are
    summed."
    PRD §3.9: "Qualifying lots are priced in `created_at` ascending order, and a running
    head count carries forward from one lot to the next, so a second lot of 20 head on
    an order that already presented 40 is priced at 110 cents for its first ten head and
    85 cents for its remaining ten."
    PRD §3.9: "`assessed_fee_cents` is the subtotal plus the travel surcharge plus the
    after-hours premium where it applies."

    Design: Difficulty/combinatorial_formula/fee_admin_surcharge_rounded_per_lot_then_summed
    """
    scenario = setup_two_lot_rounding_order()

    completed = validate_success(
        api.complete_order(
            scenario["order"]["id"],
            make_field_inspector_headers(scenario["inspector"]["id"]),
        ),
        200,
    )

    assert_inspection_order(completed)
    assert completed["assessed_fee_cents"] == 10601, (
        "30-head base 3300 with surcharge 413 plus 40-head base 3900 with surcharge 488, "
        f"plus travel 2500, got {completed['assessed_fee_cents']}"
    )
    assert completed["head_count_presented"] == 70
    assert completed["fee_status"] == "ASSESSED"


def test_summing_the_lot_bases_before_rounding_would_give_a_different_fee(api):
    """PRD §3.9: "Summing every lot's base first and rounding the surcharge once at the
    end produces a different answer by whole cents whenever a lot's base lands on a half
    cent, and that is not the answer the board wants."
    PRD §3.9: "In that same request the order's `fee_status` advances
    `UNASSESSED → ASSESSED`, `assessed_fee_cents` is stamped with the computed fee,
    `fee_due_on` is set to the logical clock advanced by 30 days, and the owner's
    `projected_arrears_cents` is recomputed."

    Design: Difficulty/combinatorial_formula/fee_admin_surcharge_rounded_per_lot_then_summed
    """
    scenario = setup_two_lot_rounding_order()

    completed = validate_success(
        api.complete_order(
            scenario["order"]["id"],
            make_field_inspector_headers(scenario["inspector"]["id"]),
        ),
        200,
    )

    assert completed["assessed_fee_cents"] != 10600, (
        "summing the two bases to 7200 and rounding once gives 10600, which is the "
        "reading the board rejects"
    )
    assert completed["assessed_fee_cents"] == 10601
    assert_instant_equals(completed["fee_due_on"], "2026-08-31T00:00:00Z", "fee_due_on")
    assert read_owner(scenario["owner"]["id"])["projected_arrears_cents"] == 10601


# ─── The empty-order boundary ─────────────────────────────────────────────────

def test_order_completed_with_no_lots_carries_only_the_travel_surcharge(api):
    """PRD §3.9: "The district's `travel_surcharge_cents` is always added, which is why
    an order that completes with no qualifying lots at all still carries a fee: its
    subtotal is zero but the travel surcharge stands."
    PRD §3.9: "In that same request the order's `fee_status` advances
    `UNASSESSED → ASSESSED`, `assessed_fee_cents` is stamped with the computed fee,
    `fee_due_on` is set to the logical clock advanced by 30 days, and the owner's
    `projected_arrears_cents` is recomputed."

    Design: Difficulty/boundary_precision_check/complete_order_with_zero_qualifying_lots_assesses_travel_only
    """
    scenario = setup_zero_and_single_lot_orders()

    completed = validate_success(
        api.complete_order(
            scenario["empty_order"]["id"],
            make_field_inspector_headers(scenario["empty_inspector"]["id"]),
        ),
        200,
    )

    assert completed["assessed_fee_cents"] == 2500, (
        f"an empty order carries only the travel surcharge, got {completed['assessed_fee_cents']}"
    )
    assert completed["head_count_presented"] == 0
    assert completed["fee_status"] == "ASSESSED"
    assert_instant_equals(completed["fee_due_on"], "2026-08-31T00:00:00Z", "fee_due_on")


def test_single_head_lot_adds_its_rounded_surcharge_to_the_travel_charge(api):
    """PRD §3.9: "Each lot's own base charge is then loaded with an administrative
    surcharge of 12.5 percent of that base, and the point at which the board rounds is
    part of the rule rather than an accident of implementation: the surcharge is rounded
    half up to whole cents **per lot**, and only the already-rounded per-lot amounts are
    summed."
    PRD §3.9: "`projected_arrears_cents` is the summed `assessed_fee_cents` of that
    owner's orders whose `fee_status` is `ASSESSED` or `DELINQUENT` — everything
    outstanding, whether or not it has come due."

    Design: Difficulty/boundary_precision_check/complete_order_with_zero_qualifying_lots_assesses_travel_only
    """
    scenario = setup_zero_and_single_lot_orders()

    empty = validate_success(
        api.complete_order(
            scenario["empty_order"]["id"],
            make_field_inspector_headers(scenario["empty_inspector"]["id"]),
        ),
        200,
    )
    single = validate_success(
        api.complete_order(
            scenario["single_lot_order"]["id"],
            make_field_inspector_headers(scenario["single_lot_inspector"]["id"]),
        ),
        200,
    )

    assert empty["assessed_fee_cents"] == 2500
    assert single["assessed_fee_cents"] == 2624, (
        "a 1-head base of 110 rounds its 13.75-cent surcharge up to 14, giving "
        f"124 plus travel 2500, got {single['assessed_fee_cents']}"
    )
    assert single["head_count_presented"] == 1
    assert read_owner(scenario["owner"]["id"])["projected_arrears_cents"] == 5124


# ─── Other fee-assessment inputs ──────────────────────────────────────────────

def test_window_starting_before_seven_utc_adds_the_after_hours_premium(api):
    """PRD §3.9: "And an after-hours premium of 4,500 cents is added when the order's
    `scheduled_start_at` falls outside normal board hours in UTC — that is, when its UTC
    hour is strictly before 7 or is 18 or later."
    PRD §3.9: "An order starting at 06:59 UTC and one starting at 18:00 UTC both attract
    the premium; one starting at 07:00 UTC does not."

    Design: Corner/calculations/corner_after_hours_window_adds_flat_surcharge
    """
    scenario = setup_order_in_field(
        territory_code="T-AH",
        travel_surcharge_cents=2500,
        inspection_purpose="SLAUGHTER",
        requested_window_start_at="2026-08-10T04:00:00Z",
        requested_window_end_at="2026-08-10T08:00:00Z",
        scheduled_start_at="2026-08-10T05:00:00Z",
        scheduled_end_at="2026-08-10T07:00:00Z",
        owner_name="After Hours Ranch",
    )
    _, registration = record_brand(
        scenario["owner"]["id"], brand_symbol="AH", position_code="LEFT_RIB"
    )
    lot = present_lot(
        scenario["order"]["id"], scenario["inspector"]["id"], 60,
        brand_registration_id=registration["id"],
    )
    enter_finding(lot["id"], scenario["inspector"]["id"], "MATCH_CONFIRMED")

    completed = validate_success(
        api.complete_order(
            scenario["order"]["id"],
            make_field_inspector_headers(scenario["inspector"]["id"]),
        ),
        200,
    )

    assert completed["assessed_fee_cents"] == 14144, (
        "base 6350 with surcharge 794, plus travel 2500 and the after-hours 4500, "
        f"got {completed['assessed_fee_cents']}"
    )
    assert completed["head_count_presented"] == 60
    assert read_owner(scenario["owner"]["id"])["projected_arrears_cents"] == 14144


def test_two_hundred_ten_head_lot_walks_all_three_marginal_bands(api):
    """PRD §3.9: "The fee is built from marginal per-head bands that are consumed
    cumulatively across the order's lots rather than restarting at each lot."
    PRD §3.9: "The board charges 110 cents for each of the first 50 head presented under
    the order, 85 cents for each head from the fifty-first through the two-hundredth,
    and 60 cents for every head beyond the two-hundredth."

    Design: Corner/calculations/corner_tier_three_band_applies_above_two_hundred_head
    """
    scenario = setup_order_in_field(
        territory_code="T-TIER",
        travel_surcharge_cents=2500,
        impound_capacity_head=300,
        scheduled_end_at="2026-08-10T15:00:00Z",
        owner_name="Big Herd Ranch",
    )
    _, registration = record_brand(
        scenario["owner"]["id"], brand_symbol="BH", position_code="RIGHT_HIP"
    )
    lot = present_lot(
        scenario["order"]["id"], scenario["inspector"]["id"], 210,
        brand_registration_id=registration["id"],
    )
    enter_finding(lot["id"], scenario["inspector"]["id"], "MATCH_CONFIRMED")

    completed = validate_success(
        api.complete_order(
            scenario["order"]["id"],
            make_field_inspector_headers(scenario["inspector"]["id"]),
        ),
        200,
    )

    assert completed["assessed_fee_cents"] == 23706, (
        "50 head at 110, 150 at 85 and 10 at 60 give base 18850 with surcharge 2356, "
        f"plus travel 2500, got {completed['assessed_fee_cents']}"
    )
    assert completed["head_count_presented"] == 210


# ─── Recording lots ───────────────────────────────────────────────────────────

def test_head_count_presented_is_recomputed_as_lots_are_recorded(api):
    """PRD §3.6: "A new lot enters with `lot_status` `PRESENTED`, `match_status`
    `UNCHECKED` and `disposition` `NONE`, and recording it refreshes the parent order's
    `head_count_presented`, which is the summed `head_count` of that order's lots whose
    `lot_status` is `PRESENTED`, `VERIFIED` or `HELD`."

    Design: Corner/entities/corner_head_count_presented_recomputes_on_each_lot
    """
    scenario = setup_order_in_field(territory_code="T-HCP", owner_name="Head Count Ranch")
    assert scenario["order"]["head_count_presented"] == 0

    first = present_lot(scenario["order"]["id"], scenario["inspector"]["id"], 9)
    assert_animal_lot(first)
    assert first["lot_status"] == "PRESENTED"
    assert first["match_status"] == "UNCHECKED"
    assert first["disposition"] == "NONE"
    assert read_order(scenario["order"]["id"])["head_count_presented"] == 9

    present_lot(scenario["order"]["id"], scenario["inspector"]["id"], 12)
    assert read_order(scenario["order"]["id"])["head_count_presented"] == 21


def test_lot_of_zero_head_is_refused(api):
    """PRD §3.6: "A lot declares its `species_class` and its `head_count`, which must be
    at least one animal."
    PRD §2.8: "Any of these failing yields `ERR_INVALID_REQUEST` (HTTP 400 Bad Request)."

    Design: Corner/entities/corner_animal_lot_head_count_zero_rejected
    """
    scenario = setup_order_in_field(territory_code="T-ZH", owner_name="Zero Head Ranch")

    response = api.create_lot(
        scenario["order"]["id"],
        create_lot_payload(0),
        make_field_inspector_headers(scenario["inspector"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(
        api.list_animal_lots(
            BOARD_ADMIN, params={"inspection_order_id": scenario["order"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_order(scenario["order"]["id"])["head_count_presented"] == 0


def test_lot_naming_an_unknown_brand_record_is_refused(api):
    """PRD §2.8: "**Fifth**, body reference resolution: every foreign key supplied in the
    request payload must likewise resolve, which covers `owner_id`, `territory_id`,
    `inspector_id`, `prior_registration_id`, `respondent_registration_id`,
    `contested_application_id`, `brand_registration_id`, `bill_of_sale_id`,
    `seller_owner_id`, `buyer_owner_id` and each element of `covered_order_ids`."
    PRD §2.8: "These failures reuse the same not-found codes at HTTP 404."

    Design: Corner/entities/corner_lot_with_unknown_brand_registration_fk_rejected
    """
    scenario = setup_order_in_field(territory_code="T-FK", owner_name="Dangling FK Ranch")

    response = api.create_lot(
        scenario["order"]["id"],
        create_lot_payload(5, brand_registration_id=UNKNOWN_ID),
        make_field_inspector_headers(scenario["inspector"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_REGISTRATION_NOT_FOUND.value, 404)

    rows, meta = validate_paginated(
        api.list_animal_lots(
            BOARD_ADMIN, params={"inspection_order_id": scenario["order"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_completion_is_refused_while_a_lot_is_still_unchecked(api):
    """PRD §3.6: "Completion is refused while any lot of the order that is not `VOIDED`
    still carries `match_status` `UNCHECKED`; the board will not close a certificate
    with an unexamined lot on it, and the attempt yields `ERR_ORDER_INVALID_STATE`."

    Design: Corner/validations/corner_complete_with_unchecked_lot_rejected
    """
    scenario = setup_order_in_field(territory_code="T-UNCK", owner_name="Unchecked Ranch")
    _, registration = record_brand(
        scenario["owner"]["id"], brand_symbol="UC", position_code="RIGHT_HIP"
    )
    checked = present_lot(
        scenario["order"]["id"], scenario["inspector"]["id"], 10,
        brand_registration_id=registration["id"],
    )
    enter_finding(checked["id"], scenario["inspector"]["id"], "MATCH_CONFIRMED")
    unchecked = present_lot(
        scenario["order"]["id"], scenario["inspector"]["id"], 5,
        brand_registration_id=registration["id"],
    )

    response = api.complete_order(
        scenario["order"]["id"],
        make_field_inspector_headers(scenario["inspector"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)

    order = read_order(scenario["order"]["id"])
    assert order["schedule_status"] == "IN_FIELD"
    assert order["fee_status"] == "UNASSESSED"
    assert order["assessed_fee_cents"] == 0
    assert order["fee_due_on"] is None
    assert read_lot(unchecked["id"])["match_status"] == "UNCHECKED"


def test_tendered_instrument_with_the_wrong_head_count_is_refused(api):
    """PRD §3.6: "When an instrument is tendered with the finding, it must agree with
    what the inspector sees on three points at once — the instrument's `head_count` must
    equal the lot's `head_count`, its `species_class` must equal the lot's
    `species_class`, and its `buyer_owner_id` must equal the `owner_id` of the parent
    order, since the party presenting the head for inspection must be the party the
    paper says bought them. Any of the three disagreeing is refused with
    `ERR_BILL_OF_SALE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/corner_bill_of_sale_head_count_mismatch_rejected
    """
    scenario = setup_order_in_field(territory_code="T-BOS", owner_name="BOS Buyer Ranch")
    seller = enrol_owner("BOS Seller Ranch", contact_email="bossell@example.test")
    instrument = create_bill_of_sale(
        seller["id"], scenario["owner"]["id"],
        document_number="BOS-0025", sale_date="2026-08-01T00:00:00Z",
        head_count=25, species_class="CATTLE", brand_symbol_declared="BO",
    )
    _, registration = record_brand(
        scenario["owner"]["id"], brand_symbol="BO", position_code="LEFT_RIB"
    )
    lot = present_lot(
        scenario["order"]["id"], scenario["inspector"]["id"], 40,
        brand_registration_id=registration["id"],
    )

    response = api.record_finding(
        lot["id"],
        record_finding_payload("MATCH_CONFIRMED", bill_of_sale_id=instrument["id"]),
        make_field_inspector_headers(scenario["inspector"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_BILL_OF_SALE_MISMATCH.value, 422)

    unchanged = read_lot(lot["id"])
    assert unchanged["match_status"] == "UNCHECKED"
    assert unchanged["bill_of_sale_id"] is None

    rows, meta = validate_paginated(
        api.list_animal_lots(BOARD_ADMIN, params={"bill_of_sale_id": instrument["id"]})
    )
    assert meta["total_count"] == 0


def test_lots_filtered_by_parent_order_exclude_sibling_orders(api):
    """PRD §3.6: "Lots may be listed and narrowed by `inspection_order_id`, by
    `brand_registration_id`, by `bill_of_sale_id`, by `match_status` or by `lot_status`."
    PRD §3.6: "Each lot belongs to the order it was recorded under through
    `inspection_order_id`."

    Design: Corner/endpoints/corner_filtered_list_by_fk_returns_only_matching_children
    """
    scenario = setup_order_in_field(territory_code="T-FLT", owner_name="Filter Ranch")
    first = present_lot(scenario["order"]["id"], scenario["inspector"]["id"], 4)
    second = present_lot(scenario["order"]["id"], scenario["inspector"]["id"], 6)

    from test_helpers import add_order_in_field

    sibling_inspector, sibling_order = add_order_in_field(
        scenario,
        inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-08-11T08:00:00Z",
        requested_window_end_at="2026-08-11T17:00:00Z",
        scheduled_start_at="2026-08-11T09:00:00Z",
        scheduled_end_at="2026-08-11T11:00:00Z",
    )
    sibling_lot = present_lot(sibling_order["id"], sibling_inspector["id"], 8)

    rows, meta = validate_paginated(
        api.list_animal_lots(
            BOARD_ADMIN, params={"inspection_order_id": scenario["order"]["id"]}
        )
    )

    assert meta["total_count"] == 2
    returned_ids = {row["id"] for row in rows}
    assert returned_ids == {first["id"], second["id"]}
    assert sibling_lot["id"] not in returned_ids
    assert read_order(scenario["order"]["id"])["head_count_presented"] == 10
    assert read_order(sibling_order["id"])["head_count_presented"] == 8
