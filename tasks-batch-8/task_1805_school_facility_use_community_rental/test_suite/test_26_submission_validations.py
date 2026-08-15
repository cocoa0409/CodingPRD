"""Submission-gate validations: capacity, window shape, past-dating, and renter
standing (PRD §2.9, §3.3, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_renter_headers,
    make_booking_env, add_renter_with_insurance,
    make_draft_request, submit_request,
    make_approved_permit_in_env,
    capture_deposit, set_clock,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


class TestCapacityGate:
    def test_capacity_exceeded_on_submit(self, api):
        """PRD §3.4: "the `headcount_estimate` must not exceed the facility's
        `capacity` (else `ERR_CAPACITY_EXCEEDED`)".
        PRD §2.9: "**Safety gates: capacity and insurance.** The estimated
        headcount must fit the facility, and the renter's insurance must be
        valid, cover the full event window, and meet the headcount tier — else
        `ERR_CAPACITY_EXCEEDED` or `ERR_INSURANCE_INSUFFICIENT` (HTTP 422)."

        Design: Corner/validations/capacity_exceeded_on_submit
        """
        env = make_booking_env(insurance_overrides={
            "per_occurrence_limit_cents": 500000000,
            "aggregate_limit_cents": 1000000000})
        too_big = make_draft_request(env, event_title="Too Big", headcount_estimate=301,
                                     starts_at="2026-12-01T01:00:00Z",
                                     ends_at="2026-12-01T03:00:00Z")
        just_right = make_draft_request(env, event_title="Just Right",
                                        headcount_estimate=300,
                                        starts_at="2026-12-02T01:00:00Z",
                                        ends_at="2026-12-02T03:00:00Z")

        res = api.submit_request(env["org"]["id"], too_big["id"],
                                 make_renter_headers(env["org"]["id"]))
        validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED)
        stayed = validate_success(api.get_request(too_big["id"], DIRECTOR))
        assert stayed["request_status"] == "DRAFT"

        # headcount == capacity passes: the "must not exceed" bound is inclusive.
        ok = submit_request(env, just_right["id"])
        assert ok["request_status"] == "SUBMITTED"


class TestTimeWindowGate:
    def test_invalid_time_window_variants(self, api):
        """PRD §2.9: "**Temporal sanity.** Window shape rules — end strictly
        after start, duration at most twelve hours, submission start in the
        future, seasonal span within its limit, buffers in whole quarter-hours —
        else `ERR_INVALID_TIME_WINDOW` (HTTP 422). Applies to request creation,
        submission, and resubmission, to seasonal series creation, and to
        calendar event creation."
        PRD §3.4: "the `starts_at` must lie strictly after the logical clock's
        current instant — no past-dated submissions; and the window must satisfy
        the temporal rules, `ends_at` strictly after `starts_at` and the total
        duration at most twelve hours (else `ERR_INVALID_TIME_WINDOW`)."

        Design: Corner/validations/invalid_time_window_variants
        """
        env = make_booking_env()
        set_clock("2026-08-10T00:00:00Z")

        # Inverted window: end strictly after start is violated.
        inverted = api.create_request(
            env["org"]["id"],
            {"facility_id": env["facility"]["id"], "event_title": "Inverted",
             "headcount_estimate": 50, "starts_at": "2026-12-01T03:00:00Z",
             "ends_at": "2026-12-01T01:00:00Z"},
            make_renter_headers(env["org"]["id"]))
        validate_error(inverted, ApiErrorId.ERR_INVALID_TIME_WINDOW)

        # Thirteen-hour duration exceeds the twelve-hour cap.
        too_long = api.create_request(
            env["org"]["id"],
            {"facility_id": env["facility"]["id"], "event_title": "Too Long",
             "headcount_estimate": 50, "starts_at": "2026-12-02T01:00:00Z",
             "ends_at": "2026-12-02T14:00:00Z"},
            make_renter_headers(env["org"]["id"]))
        validate_error(too_long, ApiErrorId.ERR_INVALID_TIME_WINDOW)

        # Drafted while future-dated; the clock then moves past its start, so
        # the no-past-dated-submissions rule fires at submission.
        past = make_draft_request(env, event_title="Past Dated", headcount_estimate=50,
                                  starts_at="2026-08-12T01:00:00Z",
                                  ends_at="2026-08-12T03:00:00Z")
        set_clock("2026-08-13T00:00:00Z")
        res = api.submit_request(env["org"]["id"], past["id"],
                                 make_renter_headers(env["org"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_TIME_WINDOW)
        stayed = validate_success(api.get_request(past["id"], DIRECTOR))
        assert stayed["request_status"] == "DRAFT"


class TestStandingGate:
    def test_suspended_renter_blocked_and_barred_cascade(self, api):
        """PRD §3.3: "When `outstanding_balance_cents` stays above zero
        continuously for thirty or more days — evaluated as the logical clock
        advances — or when `forfeiture_count` reaches three, the organization
        slides from `GOOD_STANDING` to `SUSPENDED`. Suspension blocks new request
        submissions and permit activations: attempts in that window are rejected
        with `ERR_RENTER_NOT_IN_GOOD_STANDING`."
        PRD §3.3: "Barring is the terminal sanction: a `FacilitiesDirector` bars
        an organization with a `reason`, moving it from `GOOD_STANDING` or
        `SUSPENDED` to `BARRED`, withdrawing every non-terminal request the
        organization holds, and cancelling every `ISSUED` permit it holds under
        the administrative cancellation class — a full refund with no fee."

        Design: Corner/validations/suspended_renter_blocked_from_submit_and_approve
        """
        env = make_booking_env(org_name="Slow Payer")
        # An August event completes and its FINAL invoice goes unpaid.
        req_old, p_old = make_approved_permit_in_env(
            env, event_title="August Event", headcount_estimate=50,
            starts_at="2026-08-04T00:00:00Z", ends_at="2026-08-04T02:00:00Z")
        capture_deposit(env, p_old["id"], 10000, "dep-sp-1")
        set_clock("2026-08-05T00:00:00Z")
        validate_success(api.complete_permit(p_old["id"], COORDINATOR))
        # outstanding_balance_cents > 0 from 2026-08-05 onward.

        # A second organization with a pending request.
        doomed, _ = add_renter_with_insurance("Doomed Org")
        env_doomed = {**env, "org": doomed}
        req_doomed = make_draft_request(env_doomed, event_title="Pending Event",
                                        headcount_estimate=50,
                                        starts_at="2026-12-01T01:00:00Z",
                                        ends_at="2026-12-01T03:00:00Z")
        submit_request(env_doomed, req_doomed["id"])

        # 2026-08-05 -> 2026-09-10 is 36 days: the thirty-day arrears rule fires.
        set_clock("2026-09-10T00:00:00Z")
        slow = validate_success(api.get_renter(env["org"]["id"], DIRECTOR))
        assert slow["org_standing"] == "SUSPENDED"

        new_req = make_draft_request(env, event_title="New Attempt",
                                     headcount_estimate=50,
                                     starts_at="2026-12-05T01:00:00Z",
                                     ends_at="2026-12-05T03:00:00Z")
        res = api.submit_request(env["org"]["id"], new_req["id"],
                                 make_renter_headers(env["org"]["id"]))
        validate_error(res, ApiErrorId.ERR_RENTER_NOT_IN_GOOD_STANDING)

        # Barring withdraws every non-terminal request the organization holds.
        barred = validate_success(api.bar_renter(
            doomed["id"], {"reason": "Repeated rule violations"}, DIRECTOR))
        assert barred["org_standing"] == "BARRED"
        withdrawn = validate_success(api.get_request(req_doomed["id"], DIRECTOR))
        assert withdrawn["request_status"] == "WITHDRAWN"
