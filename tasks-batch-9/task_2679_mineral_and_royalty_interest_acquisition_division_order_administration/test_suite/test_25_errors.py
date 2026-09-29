"""Triggerability of the not-found sweep, the cap/floor rejections and the state errors."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_acreage, assert_burden, assert_money
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    MANAGER_ALT_HEADERS,
    MANAGER_HEADERS,
    OPERATOR_HEADERS,
    make_royalty_owner_headers,
)

ORRI_ONE = {
    "instrument_type": "ASSIGNMENT",
    "instrument_date": "2009-04-02",
    "conveyed_fraction": 0.2,
    "county_book_page": "700/11",
    "grantor_name": "A Patentee",
    "grantee_name": "ORRI One",
}


def test_every_unknown_path_id_names_its_own_resource_kind(api):
    """Ten reads against an empty database return ten distinct 404 codes.

    PRD: "5. Every resource named by a path parameter exists, checked left to right
    — otherwise the matching not-found code (404)."

    Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found_error
    """
    sweep = [
        (api.get_royalty_owner(NON_EXISTENT_UUID, ADMIN_HEADERS), "ERR_ROYALTY_OWNER_NOT_FOUND"),
        (api.get_valuation(NON_EXISTENT_UUID, MANAGER_HEADERS), "ERR_VALUATION_NOT_FOUND"),
        (api.get_offer_letter(NON_EXISTENT_UUID, MANAGER_HEADERS), "ERR_OFFER_LETTER_NOT_FOUND"),
        (api.get_psa(NON_EXISTENT_UUID, MANAGER_HEADERS), "ERR_PSA_NOT_FOUND"),
        (api.get_title_defect(NON_EXISTENT_UUID, ANALYST_HEADERS), "ERR_TITLE_DEFECT_NOT_FOUND"),
        (api.get_unit(NON_EXISTENT_UUID, OPERATOR_HEADERS), "ERR_UNIT_NOT_FOUND"),
        (api.get_allocation(NON_EXISTENT_UUID, OPERATOR_HEADERS), "ERR_ALLOCATION_NOT_FOUND"),
        (api.get_division_order(NON_EXISTENT_UUID, ADMIN_HEADERS), "ERR_DIVISION_ORDER_NOT_FOUND"),
        (
            api.get_revenue_check_detail(NON_EXISTENT_UUID, ADMIN_HEADERS),
            "ERR_REVENUE_DETAIL_NOT_FOUND",
        ),
        (
            api.get_suspense_account(NON_EXISTENT_UUID, ADMIN_HEADERS),
            "ERR_SUSPENSE_ACCOUNT_NOT_FOUND",
        ),
    ]

    for response, expected in sweep:
        body = validate_error(response, expected, 404)
        assert body["error_id"] == expected
        assert body["message"].strip()


def test_an_overriding_royalty_burden_above_a_quarter_blocks_certification(api):
    """0.2000 plus 0.1000 is 0.3000 of the royalty stream and will not certify.

    PRD: "If that sum is strictly greater than 0.2500 — a quarter of the royalty
    stream, the most the firm will underwrite — the certification is rejected with
    `ERR_BURDEN_CAP_EXCEEDED`; a sum of exactly 0.2500 is accepted."

    Design: Corner/errors/assignments_summing_above_the_burden_cap_are_rejected_at_certification
    """
    tract = fx.create_tract(api)
    fx.add_chain_entry(api, tract["id"], f.patent_entry_payload())
    fx.add_chain_entry(api, tract["id"], f.assignment_entry_payload(**ORRI_ONE))
    fx.add_chain_entry(
        api,
        tract["id"],
        f.assignment_entry_payload(
            instrument_date="2011-01-05",
            conveyed_fraction=0.1,
            county_book_page="780/301",
            grantor_name="A Patentee",
            grantee_name="ORRI Two",
        ),
    )

    response = api.certify_title(tract["id"], ANALYST_HEADERS)

    validate_error(response, "ERR_BURDEN_CAP_EXCEEDED", 422)
    still_research = validate_success(api.get_tract(tract["id"], ANALYST_HEADERS), 200)
    assert still_research["title_status"] == "RESEARCH"
    assert still_research["net_mineral_acres_certified"] is None
    assert still_research["existing_burden_fraction"] is None


def test_a_burden_of_exactly_a_quarter_certifies(api):
    """0.2000 plus 0.0500 sits on the inclusive edge and the acreage is untouched.

    PRD: "An `ASSIGNMENT` entry leaves the running figure exactly as it was, because
    it carves an overriding royalty out of the revenue stream rather than acreage out
    of the tract."

    Design: Corner/errors/assignments_summing_above_the_burden_cap_are_rejected_at_certification
    """
    tract = fx.create_tract(api)
    fx.add_chain_entry(api, tract["id"], f.patent_entry_payload())
    fx.add_chain_entry(api, tract["id"], f.assignment_entry_payload(**ORRI_ONE))
    fx.add_chain_entry(
        api,
        tract["id"],
        f.assignment_entry_payload(
            instrument_date="2011-01-05",
            conveyed_fraction=0.05,
            county_book_page="780/302",
            grantor_name="A Patentee",
            grantee_name="ORRI Three",
        ),
    )

    certified = fx.certify_tract(api, tract["id"])

    assert certified["title_status"] == "CERTIFIED"
    assert_burden(certified["existing_burden_fraction"], "0.2500", "existing_burden_fraction")
    assert_acreage(
        certified["net_mineral_acres_certified"], "640.0000", "net_mineral_acres_certified"
    )


def test_one_cent_below_the_walk_away_floor_is_refused(api):
    """37115.33 against a 37115.34 floor is not an offer the firm will send.

    PRD: "And the money must sit inside the band: an `offer_amount` strictly below
    the valuation's `bid_floor` is `ERR_OFFER_BELOW_BID_FLOOR`, an `offer_amount`
    strictly above the valuation's `max_bid` is `ERR_OFFER_ABOVE_MAX_BID`, and an
    amount equal to either edge is accepted."

    Design: Corner/errors/offer_below_the_walk_away_floor_is_rejected_at_the_floor_boundary
    """
    world = fx.valuation_ready(api)
    assert_money(world["valuation"]["pdp_pv"], "39589.70", "pdp_pv")
    assert_money(world["valuation"]["undeveloped_pv"], "19440.00", "undeveloped_pv")
    assert_money(world["valuation"]["bid_floor"], "37115.34", "bid_floor")
    assert_money(world["valuation"]["max_bid"], "55340.34", "max_bid")

    response = api.create_offer_letter(
        world["interest"]["id"], f.offer_letter_payload(offer_amount=37115.33), MANAGER_ALT_HEADERS
    )

    validate_error(response, "ERR_OFFER_BELOW_BID_FLOOR", 422)
    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "PROSPECT"


def test_an_offer_exactly_at_the_floor_is_sent(api):
    """37115.34 is the inclusive edge and the letter goes out at that amount.

    PRD: "Issuing an offer letter drives the interest from `PROSPECT` to `OFFERED`,
    and it is the single most heavily guarded write on the buy side."

    Design: Corner/errors/offer_below_the_walk_away_floor_is_rejected_at_the_floor_boundary
    """
    world = fx.valuation_ready(api)

    offer = fx.create_offer(api, world["interest"]["id"], offer_amount=37115.34)

    assert offer["offer_status"] == "SENT"
    assert_money(offer["current_amount"], "37115.34", "current_amount")
    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "OFFERED"


def test_the_deed_recording_closes_the_agreement_and_acquires_the_interest(api):
    """One recording drives the PSA CLOSED and the interest ACQUIRED at 915/210.

    PRD: "The first hop writes `recording_county`, `recorded_book_page` and
    `recording_date` onto the agreement and sets `psa_status` to `CLOSED`."

    Design: Corner/errors/recording_a_deed_twice_returns_deed_already_recorded
    """
    world = fx.psa_ready(api)
    fx.close_curative(api, world["psa"]["id"])
    fx.fund_psa(api, world["psa"]["id"])

    recorded = fx.record_deed(api, world["psa"]["id"])

    assert recorded["psa_status"] == "CLOSED"
    assert recorded["recorded_book_page"] == "915/210"
    interest = fx.read_interest(api, world["interest"]["id"])
    assert interest["interest_status"] == "ACQUIRED"
    assert interest["acquiring_deed_book_page"] == "915/210"


def test_a_second_deed_recording_is_refused_and_changes_nothing(api):
    """The already-recorded gate keeps the first clerk citation in place.

    PRD: "The agreement's `recorded_book_page` must still be null, or the request is
    `ERR_DEED_ALREADY_RECORDED`."

    Design: Corner/errors/recording_a_deed_twice_returns_deed_already_recorded
    """
    world = fx.psa_ready(api)
    fx.close_curative(api, world["psa"]["id"])
    fx.fund_psa(api, world["psa"]["id"])
    fx.record_deed(api, world["psa"]["id"])

    second = api.record_deed(
        world["psa"]["id"],
        f.record_deed_payload(recorded_book_page="916/211", recording_date="2026-08-16"),
        ANALYST_HEADERS,
    )

    validate_error(second, "ERR_DEED_ALREADY_RECORDED", 409)
    psa = fx.read_psa(api, world["psa"]["id"])
    assert psa["recorded_book_page"] == "915/210"
    assert psa["recording_date"] == "2026-08-10"


def test_a_waived_defect_is_outside_the_cure_from_set(api):
    """WAIVED is terminal, so the seller's curative instrument has nowhere to land.

    PRD: "Submission is permitted only from `RAISED` or `CURE_REJECTED` (anything
    else is `ERR_DEFECT_STATE_INVALID`), only while the agreement's curative
    dimension is `CURATIVE_OPEN`, only while the logical clock's date is on or before
    the agreement's `curative_deadline` — a later attempt is
    `ERR_CURATIVE_DEADLINE_PASSED` — and only when `X-User-ID` equals the interest's
    `seller_owner_id`."

    Design: Corner/errors/writes_against_the_wrong_lifecycle_state_return_their_own_state_errors
    """
    world = fx.psa_with_defects_ready(api, [{}])
    defect = world["defects"][0]
    validate_success(
        api.waive_defect(
            defect["id"], MANAGER_ALT_HEADERS, {"waiver_note": "Immaterial to the acquisition"}
        ),
        200,
    )

    response = api.submit_cure(
        defect["id"],
        f.submit_cure_payload(cure_instrument_book_page="310/7"),
        make_royalty_owner_headers(world["owner"]["id"]),
    )

    validate_error(response, "ERR_DEFECT_STATE_INVALID", 409)
    assert fx.read_defect(api, defect["id"])["defect_status"] == "WAIVED"


def test_a_closed_curative_period_refuses_a_late_defect(api):
    """The waived defect never entered the uncured set, so the price stays 48000.00.

    PRD: "Any defect activity attempted once the curative dimension has left
    `CURATIVE_OPEN` is `ERR_CURATIVE_PERIOD_CLOSED`."

    Design: Corner/errors/writes_against_the_wrong_lifecycle_state_return_their_own_state_errors
    """
    world = fx.psa_with_defects_ready(api, [{}])
    api.waive_defect(
        world["defects"][0]["id"],
        MANAGER_ALT_HEADERS,
        {"waiver_note": "Immaterial to the acquisition"},
    )

    closed = fx.close_curative(api, world["psa"]["id"])

    assert closed["curative_status"] == "CURATIVE_CLOSED"
    assert_money(closed["defect_adjustment_amount"], "0.00", "defect_adjustment_amount")
    assert_money(closed["adjusted_purchase_price"], "48000.00", "adjusted_purchase_price")

    late = api.create_title_defect(
        world["psa"]["id"],
        f.title_defect_payload(
            defect_type="UNRELEASED_LEASE",
            affected_nma=5.0000,
            description="Late-discovered unreleased lease",
        ),
        ANALYST_HEADERS,
    )
    validate_error(late, "ERR_CURATIVE_PERIOD_CLOSED", 409)


def test_an_interest_under_agreement_takes_no_further_offers(api):
    """The interest is UNDER_PSA and the accepted letter is terminal.

    PRD: "The interest must be sitting in `PROSPECT` — an interest already `OFFERED`,
    `UNDER_PSA`, `ACQUIRED` or `RELEASED` yields `ERR_INTEREST_STATE_INVALID`."

    Design: Corner/errors/writes_against_the_wrong_lifecycle_state_return_their_own_state_errors
    """
    world = fx.psa_ready(api)

    second_letter = api.create_offer_letter(
        world["interest"]["id"],
        f.offer_letter_payload(expires_on="2026-10-01"),
        MANAGER_ALT_HEADERS,
    )
    second_accept = api.accept_offer_letter(
        world["offer"]["id"], make_royalty_owner_headers(world["owner"]["id"])
    )

    validate_error(second_letter, "ERR_INTEREST_STATE_INVALID", 409)
    validate_error(second_accept, "ERR_OFFER_STATE_INVALID", 409)
    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "UNDER_PSA"
    assert fx.read_offer(api, world["offer"]["id"])["offer_status"] == "ACCEPTED"


def test_revenue_cannot_be_reported_against_a_merely_sent_order(api):
    """The operator has not answered yet, so the revenue channel is shut.

    PRD: "Reporting is permitted only against an order whose `do_status` is
    `EXECUTED`; a `SENT`, `DISPUTED` or `SUSPENDED` order yields
    `ERR_DIVISION_ORDER_STATE_INVALID`."

    Design: Corner/errors/allocation_and_division_order_writes_outside_their_from_sets_are_rejected
    """
    world = fx.division_order_ready(api)
    assert world["order"]["do_status"] == "SENT"

    response = api.create_revenue_check_detail(
        world["order"]["id"],
        f.revenue_check_detail_payload(operator_decimal_used=0.00195313),
        OPERATOR_HEADERS,
    )

    validate_error(response, "ERR_DIVISION_ORDER_STATE_INVALID", 409)
    assert fx.read_division_order(api, world["order"]["id"])["do_status"] == "SENT"


def test_an_order_over_a_tract_the_unit_never_pooled_is_a_mismatch(api):
    """The second tract has no allocation row in any posture, so no decimal exists.

    PRD: "if no allocation row exists for that unit-and-tract pairing in any posture
    and over any interval, the request is `ERR_TRACT_UNIT_MISMATCH`"

    Design: Corner/errors/allocation_and_division_order_writes_outside_their_from_sets_are_rejected
    """
    world = fx.division_order_ready(api)
    other_tract = fx.create_tract(
        api, county="Loving", gross_acres=320.0000, operator_activity_tier="MODERATE"
    )
    fx.add_chain_entry(
        api,
        other_tract["id"],
        f.patent_entry_payload(
            instrument_date="1905-06-01", county_book_page="310/7", grantee_name="D Patentee"
        ),
    )
    fx.certify_tract(api, other_tract["id"])
    unpooled = fx.create_interest(
        api, other_tract["id"], world["owner"]["id"], undeveloped_net_acres=10.0000
    )

    response = api.create_division_order(
        f.division_order_payload(
            unpooled["id"], world["unit"]["id"], fx.unit_version(api, world["unit"]["id"])
        ),
        ADMIN_HEADERS,
    )

    validate_error(response, "ERR_TRACT_UNIT_MISMATCH", 422)


def test_an_allocation_is_terminated_once_and_its_acreage_goes_home_once(api):
    """The unit is whole again at 1280.0000 and the repeat termination is refused.

    PRD: "An `Operator` supplies a `termination_reason`, and the allocation moves to
    `TERMINATED` from either `ACTIVE` or `PUGH_RELEASED` — attempting it on an already
    `TERMINATED` allocation is `ERR_ALLOCATION_STATE_INVALID`."

    Design: Corner/errors/allocation_and_division_order_writes_outside_their_from_sets_are_rejected
    """
    world = fx.unit_with_allocation_ready(api)

    terminated = fx.terminate_allocation(api, world["allocation"]["id"])
    assert terminated["allocation_status"] == "TERMINATED"
    whole = fx.read_unit(api, world["unit"]["id"])
    assert_acreage(whole["unallocated_acres"], "1280.0000", "unallocated_acres")
    assert whole["active_allocation_count"] == 0

    repeat = api.terminate_allocation(
        world["allocation"]["id"],
        f.terminate_allocation_payload(termination_reason="Duplicate termination"),
        OPERATOR_HEADERS,
    )

    validate_error(repeat, "ERR_ALLOCATION_STATE_INVALID", 409)
    assert_acreage(
        fx.read_unit(api, world["unit"]["id"])["unallocated_acres"],
        "1280.0000",
        "unallocated_acres",
    )


def test_a_cure_after_the_curative_deadline_is_refused(api):
    """45 days from 2026-08-01 is 2026-09-15, and 2026-09-16 is one day too late.

    PRD: "31. (Priority 61) The curative window is still open in time — otherwise
    `ERR_CURATIVE_DEADLINE_PASSED` (409). Guards submitting a cure and waiving a
    defect."

    Design: Corner/errors/cure_submitted_after_the_curative_deadline_is_rejected
    """
    world = fx.psa_with_defects_ready(api, [{}])
    assert world["psa"]["curative_deadline"] == "2026-09-15"
    fx.set_clock(api, "2026-09-16T00:00:00Z")

    response = api.submit_cure(
        world["defects"][0]["id"],
        f.submit_cure_payload(cure_instrument_book_page="310/7"),
        make_royalty_owner_headers(world["owner"]["id"]),
    )

    validate_error(response, "ERR_CURATIVE_DEADLINE_PASSED", 409)
    defect = fx.read_defect(api, world["defects"][0]["id"])
    assert defect["defect_status"] == "RAISED"
    assert defect["cure_instrument_book_page"] is None
    assert fx.read_psa(api, world["psa"]["id"])["curative_status"] == "CURATIVE_OPEN"


def test_a_cure_on_the_deadline_day_itself_is_accepted(api):
    """The window boundary is inclusive, so 2026-09-15 still cures.

    PRD: "It records the supplied `cure_instrument_book_page`, increments
    `cure_round_count` by 1, and sets `defect_status` to `CURE_SUBMITTED`."

    Design: Corner/errors/cure_submitted_after_the_curative_deadline_is_rejected
    """
    world = fx.psa_with_defects_ready(api, [{}])
    fx.set_clock(api, "2026-09-15T00:00:00Z")

    submitted = validate_success(
        api.submit_cure(
            world["defects"][0]["id"],
            f.submit_cure_payload(cure_instrument_book_page="310/7"),
            make_royalty_owner_headers(world["owner"]["id"]),
        ),
        200,
    )

    assert submitted["defect_status"] == "CURE_SUBMITTED"
    assert submitted["cure_instrument_book_page"] == "310/7"
    assert submitted["cure_round_count"] == 1
