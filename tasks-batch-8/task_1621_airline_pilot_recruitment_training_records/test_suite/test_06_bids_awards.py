"""Equipment bid periods, seniority ranking, and award eligibility."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_applicant,
    get_bid,
    get_success_data,
    make_cleared_applicant,
    make_equipment,
    make_open_bid_period,
    make_pilot_headers,
    run_daily_scan,
    set_clock,
    submit_bid,
    validate_error,
    validate_success,
)

REC = TEST_USERS["recruiter_headers"]
CS = TEST_USERS["crew_scheduler_headers"]


def _setup_two_bidders_one_seat(api):
    """Senior applicant A (cleared first, medical lapsing to DOWNGRADED by
    2026-09-01) and junior applicant B (medical VALID) bid on one seat."""
    eq = make_equipment(code="B744", sim_rate=52000, ioe_hours=12,
                        landings_required=3)
    ap_a = make_cleared_applicant(
        "snr@x.com", "L310", full_name="Snr Ace", hours=9000, age=45,
        medical_issued_at="2026-02-10T00:00:00Z")
    ap_b = make_cleared_applicant(
        "jnr@x.com", "L311", full_name="Jnr Bay", hours=4000, age=33,
        medical_issued_at="2026-07-01T00:00:00Z")
    bp = make_open_bid_period(eq["id"], opens_at="2026-08-02T00:00:00Z",
                              closes_at="2026-08-05T00:00:00Z",
                              seats_available=1,
                              open_clock="2026-08-03T00:00:00Z")
    bid_a = submit_bid(bp["id"], ap_a["id"], preference_rank=1)
    bid_b = submit_bid(bp["id"], ap_b["id"], preference_rank=1)
    get_success_data(api.close_bid_period(bp["id"], CS))
    # Advance past A's first-class validity (through 2026-08-31) and scan so
    # the certificate is DOWNGRADED before the award runs.
    set_clock("2026-09-01T00:00:00Z")
    run_daily_scan()
    return {"equipment": eq, "applicant_a": ap_a, "applicant_b": ap_b,
            "period": bp, "bid_a": bid_a, "bid_b": bid_b}


class TestBidAwardEligibility:
    def test_senior_bidder_with_downgraded_medical_is_ineligible(self, api):
        """PRD §3.7: "Eligibility is pinned first: the bidding applicant must
        be `CLEARED` and must hold a `VALID` first-class medical certificate."
        PRD §3.7: "Eligible bids ranked beyond the seat count move to `DENIED`
        with `denial_reason` `INSUFFICIENT_SENIORITY`; ineligible bids move to
        `DENIED` with `denial_reason` `INELIGIBLE`."
        PRD §3.7: "The first `seats_available` bids in that ranking move
        `SUBMITTED` → `AWARDED` with the bid's `awarded_at` stamped, and each
        winner's `current_equipment_id` is set to the period's fleet,
        incrementing the applicant `version`."

        Design: Difficulty/cross_entity_state_dependency/bid_award_eligibility_requires_valid_medical
        """
        ctx = _setup_two_bidders_one_seat(api)
        validate_success(api.award_bid_period(ctx["period"]["id"], CS))

        bid_a = get_bid(ctx["bid_a"]["id"])
        assert bid_a["status"] == "DENIED"
        assert bid_a["denial_reason"] == "INELIGIBLE", (
            "The senior bidder's DOWNGRADED certificate fails eligibility")
        bid_b = get_bid(ctx["bid_b"]["id"])
        assert bid_b["status"] == "AWARDED", "The seat falls through to junior"
        assert bid_b["awarded_at"] is not None
        winner = get_applicant(ctx["applicant_b"]["id"])
        assert winner["current_equipment_id"] == ctx["equipment"]["id"]

    def test_ranking_uses_seniority_snapshot_and_stamps_period(self, api):
        """PRD §3.1: "A successful clear stamps `cleared_at` with the current
        logical time and runs seniority assignment: `seniority_number` becomes
        one plus the count of applicants who already hold a seniority number,
        producing a gapless sequence that is never renumbered afterwards, and
        the applicant's `version` increments."
        PRD §3.7: "At submission the system captures `seniority_snapshot` from
        the applicant's current `seniority_number`, and all later ranking uses
        the snapshot rather than a live value."
        PRD §3.7: "The period stamps its own `awarded_at` and increments
        `version`."

        Design: Difficulty/cross_entity_state_dependency/bid_award_eligibility_requires_valid_medical
        """
        ctx = _setup_two_bidders_one_seat(api)
        assert get_applicant(ctx["applicant_a"]["id"])["seniority_number"] == 1
        assert get_applicant(ctx["applicant_b"]["id"])["seniority_number"] == 2
        assert ctx["bid_a"]["seniority_snapshot"] == 1
        assert ctx["bid_b"]["seniority_snapshot"] == 2

        awarded = validate_success(api.award_bid_period(ctx["period"]["id"], CS))
        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_at"] is not None
        # Only the junior bid was eligible at award time.
        assert get_bid(ctx["bid_b"]["id"])["status"] == "AWARDED"
        assert get_bid(ctx["bid_a"]["id"])["status"] == "DENIED"


class TestBidRules:
    def test_duplicate_bid_same_period_rejected(self, api):
        """PRD §3.7: "The period must be `OPEN` at submission, and one bid per
        applicant per period is enforced — a second bid is rejected with
        `ERR_DUPLICATE_BID` (409)."

        Design: Corner/validations/duplicate_bid_same_period_rejected
        """
        eq = make_equipment(code="E170", sim_rate=38000, ioe_hours=8)
        ap = make_cleared_applicant("bid@x.com", "L435", full_name="Bid Der")
        bp = make_open_bid_period(eq["id"], seats_available=2)
        submit_bid(bp["id"], ap["id"], preference_rank=1)
        resp = api.create_bid(
            {"bid_period_id": bp["id"], "applicant_id": ap["id"],
             "preference_rank": 2}, CS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BID)

    def test_bid_withdrawal_by_owner_while_open(self, api):
        """PRD §3.7: "A `Pilot` may submit only under their own `applicant_id`
        and may withdraw only their own bids; withdrawal is allowed while the
        bid is `SUBMITTED` and the period is still `OPEN`, and a withdrawal
        against a bid that has already been decided is rejected with
        `ERR_BID_INVALID_STATE` (409)."
        PRD §3.7: "At submission the system captures `seniority_snapshot` from
        the applicant's current `seniority_number`, and all later ranking uses
        the snapshot rather than a live value."

        Design: Corner/endpoints/bid_withdrawal_by_owner_while_open
        """
        eq = make_equipment(code="FK02", sim_rate=38000, ioe_hours=8)
        ap = make_cleared_applicant("wb@x.com", "L454", full_name="Wit Bid")
        bp = make_open_bid_period(eq["id"], seats_available=2)
        pilot = make_pilot_headers(ap["id"])
        bid = validate_success(api.create_bid(
            {"bid_period_id": bp["id"], "applicant_id": ap["id"],
             "preference_rank": 1}, pilot), 201)
        assert bid["seniority_snapshot"] == 1, (
            "The snapshot captures the seniority number at submission")
        withdrawn = validate_success(api.withdraw_bid(bid["id"], pilot))
        assert withdrawn["status"] == "WITHDRAWN"
        reread = get_bid(bid["id"])
        assert reread["status"] == "WITHDRAWN"
        assert reread["seniority_snapshot"] == 1, (
            "The snapshot survives the withdrawal")

    def test_bid_period_auto_close_via_scan(self, api):
        """PRD §3.7: "Closing moves `OPEN` → `CLOSED`, either on explicit
        request or automatically when the daily scan finds the clock past
        `closes_at`."
        PRD §3.7: "Any period action attempted from the wrong state is rejected
        with `ERR_BID_PERIOD_INVALID_STATE`."

        Design: Corner/errors/bid_period_auto_close_via_scan
        """
        eq = make_equipment(code="FK04", sim_rate=38000, ioe_hours=8)
        ap = make_cleared_applicant("clo@x.com", "L457", full_name="Clo Sed")
        bp = make_open_bid_period(eq["id"], opens_at="2026-07-01T00:00:00Z",
                                  closes_at="2026-08-05T00:00:00Z",
                                  seats_available=1)
        set_clock("2026-08-06T00:00:00Z")
        summary = run_daily_scan()
        assert summary["bid_periods_closed"] >= 1, (
            "The scan closed the period whose closes_at passed")
        period = validate_success(api.get_bid_period(bp["id"], CS))
        assert period["status"] == "CLOSED"
        resp = api.create_bid(
            {"bid_period_id": bp["id"], "applicant_id": ap["id"],
             "preference_rank": 1}, CS)
        validate_error(resp, ApiErrorId.ERR_BID_PERIOD_INVALID_STATE)
