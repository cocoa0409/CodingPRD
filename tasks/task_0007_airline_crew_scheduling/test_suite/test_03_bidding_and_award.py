"""Bid validation: rank–seat compatibility, bid uniqueness.
"""
from test_helpers import (
    validate_error,
    setup_clean_world,
    setup_pairing_in_bid_open,
    create_crew_member,
    create_pairing,
    add_revenue_leg,
    open_bidding,
    submit_bid,
    create_bid_payload,
    make_crew_member_headers,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Duplicate Bid uniqueness on POST /bids
# ---------------------------------------------------------------------

def test_duplicate_bid_rejected_when_prior_still_submitted(api):
    """PRD §3.2: "a given `crew_member_id` may have at most one non-terminal
    Bid (state in `SUBMITTED` or `AWARDED`) against a given `pairing_id`. A
    duplicate is rejected with `ERR_DUPLICATE_BID`."

    Design: Corner/validations/duplicate_bid_rejected
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    cm = create_crew_member(employee_code="AB0400", seniority_number=400)
    pairing = create_pairing(pairing_code="P-2026-400")
    add_revenue_leg(pairing["id"])
    open_bidding(pairing["id"])
    # First bid succeeds via fixture helper.
    submit_bid(pairing["id"], cm, requested_seat="CAPTAIN")
    # Second bid by the same crew on the same pairing — must be rejected.
    res = api.create_bid(
        create_bid_payload(pairing["id"], cm["id"], requested_seat="CAPTAIN"),
        make_crew_member_headers(cm["id"]),
    )
    validate_error(res, "ERR_DUPLICATE_BID", expected_status=409)


# ---------------------------------------------------------------------
# Rank–seat mismatch on POST /bids
# ---------------------------------------------------------------------

def test_first_officer_cannot_bid_for_captain_seat(api):
    """PRD §3.2: "a `CAPTAIN` may only bid for a `CAPTAIN` seat; a `FIRST_OFFICER`
    may only bid for a `FIRST_OFFICER` seat; both `PURSER` and `FLIGHT_ATTENDANT`
    are permitted to bid for either the `PURSER` seat or the `FLIGHT_ATTENDANT`
    seat. Any other combination is rejected with `ERR_RANK_SEAT_MISMATCH`."

    Design: Corner/validations/rank_seat_mismatch_on_bid
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    cm = create_crew_member(
        employee_code="AB0410",
        seniority_number=410,
        rank="FIRST_OFFICER",
    )
    pairing = create_pairing(
        pairing_code="P-2026-410",
        required_captains=1,
        required_first_officers=1,
    )
    add_revenue_leg(pairing["id"])
    open_bidding(pairing["id"])
    res = api.create_bid(
        create_bid_payload(pairing["id"], cm["id"], requested_seat="CAPTAIN"),
        make_crew_member_headers(cm["id"]),
    )
    validate_error(res, "ERR_RANK_SEAT_MISMATCH", expected_status=422)
