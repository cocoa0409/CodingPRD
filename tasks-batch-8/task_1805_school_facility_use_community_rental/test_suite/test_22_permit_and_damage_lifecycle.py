"""Permit lifecycle corners: cancel legality, clock-driven lapse of unsecured
permits and stale requests, the zero-award damage path, and supersession
stickiness (PRD §3.1, §3.4, §3.5, §3.7, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    sum_txns,
    make_renter_headers,
    make_booking_env, make_facility, make_policy,
    make_under_review_request, make_approved_permit_in_env,
    make_draft_request, submit_request,
    capture_deposit, set_clock, get_single_work_order,
    make_damage_assessment,
    invoice_of_kind,
    setup_secured_permit,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]

EVENT_START = "2026-09-13T00:00:00Z"
EVENT_END = "2026-09-13T03:00:00Z"
AFTER_EVENT = "2026-09-13T12:00:00Z"


class TestCancelLegality:
    def test_cancel_completed_permit_rejected(self, api):
        """PRD §3.7: "Cancellation is only possible from `ISSUED` — once a permit
        has activated, post-event disputes travel through the damage process
        instead, and a cancel attempt against a permit in any other status is
        rejected with `ERR_PERMIT_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cancel_completed_permit_rejected
        """
        env, req, permit = setup_secured_permit(
            10000, idempotency_key="dep-cc-1",
            event_title="Auction", headcount_estimate=100,
            starts_at=EVENT_START, ends_at=EVENT_END)
        set_clock(AFTER_EVENT)
        validate_success(api.complete_permit(permit["id"], COORDINATOR))

        res = api.cancel_permit(permit["id"], {"cancellation_reason": "too late"},
                                make_renter_headers(env["org"]["id"]))
        validate_error(res, ApiErrorId.ERR_PERMIT_NOT_CANCELLABLE)
        after = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert after["lifecycle_status"] == "COMPLETED"


class TestClockDrivenExpiry:
    def test_clock_expiry_of_unsecured_permit_and_stale_request(self, api):
        """PRD §3.5: "If the clock passes `occupancy_start` while the deposit is
        still `DEPOSIT_PENDING` — the deposit was never secured — the permit
        lapses to `EXPIRED`: its `PROVISIONAL` invoice is voided, its work order
        is cancelled, and the freed interval triggers a waitlist promotion sweep."
        PRD §3.4: "And if the logical clock passes a request's `starts_at` while
        it still sits in `SUBMITTED` or `WAITLISTED` without approval, the system
        moves it to the terminal `EXPIRED`."

        Design: Corner/state_machines/clock_expiry_of_unsecured_permit_and_stale_request
        """
        env = make_booking_env()
        aud = make_facility(env["site"]["id"], facility_code="AUD",
                            facility_tier="PREMIUM", capacity=500)
        make_policy(policy_code="NP-PRE", facility_tier="PREMIUM",
                    hourly_rate_cents=9000, custodial_hourly_cents=4500,
                    deposit_floor_cents=15000)
        # Approved but never secured (deposit stays DEPOSIT_PENDING).
        req1, permit = make_approved_permit_in_env(
            env, event_title="Unsecured Night", headcount_estimate=100,
            starts_at=EVENT_START, ends_at=EVENT_END)
        # Merely submitted, never approved, on the other facility.
        env2 = {**env, "facility": aud}
        req2 = make_draft_request(env2, event_title="Never Reviewed",
                                  headcount_estimate=100,
                                  starts_at=EVENT_START, ends_at=EVENT_END)
        submit_request(env, req2["id"])

        set_clock("2026-09-14T00:00:00Z")  # past both starts_at/occupancy_start

        lapsed = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert lapsed["lifecycle_status"] == "EXPIRED"
        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        assert invoice_of_kind(invoices, "PROVISIONAL")["invoice_status"] == "VOID"
        assert get_single_work_order(permit["id"])["wo_status"] == "CANCELLED"

        stale = validate_success(api.get_request(req2["id"], DIRECTOR))
        assert stale["request_status"] == "EXPIRED"


class TestDamageZeroAward:
    def test_damage_assessment_full_loop_accept_path(self, api):
        """PRD §3.8: "Acceptance — or the window elapsing with no appeal — moves
        the assessment `ADJUDICATED` → `FINAL`."
        PRD §3.8: "A finalization with an adjudicated amount of exactly zero
        moves the permit `FORFEIT_PENDING` → `SETTLED` instead, releasing the
        full held deposit as a `DEPOSIT_REFUND`."

        Design: Corner/state_machines/damage_assessment_full_loop_accept_path
        """
        env, req, permit = setup_secured_permit(
            10000, idempotency_key="dep-da-1",
            event_title="Clean Event", headcount_estimate=100,
            starts_at=EVENT_START, ends_at=EVENT_END)
        set_clock(AFTER_EVENT)
        validate_success(api.complete_permit(permit["id"], COORDINATOR))
        assessment = make_damage_assessment(permit["id"], [
            {"description": "Pre-existing scuff noted", "repair_cost_cents": 8000}])
        validate_success(api.adjudicate_damage_assessment(
            assessment["id"], {"adjudicated_amount_cents": 0}, DIRECTOR))
        final = validate_success(api.accept_damage_assessment(
            assessment["id"], make_renter_headers(env["org"]["id"])))
        assert final["assessment_status"] == "FINAL"
        assert final["adjudicated_amount_cents"] == 0

        settled = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert settled["financial_status"] == "SETTLED"
        payments = validate_success(api.list_permit_payments(permit["id"], DIRECTOR))
        assert sum_txns(payments, "DEPOSIT_REFUND") == 10000
        assert sum_txns(payments, "DEPOSIT_FORFEIT") == 0
        org = validate_success(api.get_renter(env["org"]["id"], DIRECTOR))
        assert org["forfeiture_count"] == 0


class TestSupersessionStickiness:
    def test_supersession_is_sticky_after_calendar_cancel(self, api):
        """PRD §3.1: "Cancelling an event (`SCHEDULED` → `CANCELLED`) never
        un-supersedes a permit it preempted — supersession is sticky — but the
        freed window does trigger a waitlist promotion sweep."
        PRD §3.7: "Supersession is sticky: cancelling the preempting calendar
        event later does not reinstate the superseded permit, though the freed
        window does trigger a waitlist sweep."
        PRD §3.7: "When a tier-0 SchoolCalendarEvent is created over the blocked
        interval of an `ISSUED` permit, the system moves the permit `ISSUED` →
        `SUPERSEDED`: no replacement permit is minted, `superseded_by_permit_id`
        stays null, the refund waterfall runs under the administrative class —
        deposit and any fees returned in full, no cancellation fee — the
        financial dimension moves to `REFUND_PENDING`, and the work order is
        cancelled."

        Design: Corner/state_machines/supersession_is_sticky_after_calendar_cancel
        """
        env, req, permit = setup_secured_permit(
            10000, idempotency_key="dep-ss-1",
            event_title="Auction", headcount_estimate=100,
            starts_at="2026-12-01T01:00:00Z", ends_at="2026-12-01T03:00:00Z")
        event = validate_success(api.create_calendar_event(
            env["site"]["id"],
            {"facility_id": env["facility"]["id"], "title": "Playoff",
             "starts_at": "2026-12-01T00:00:00Z", "ends_at": "2026-12-01T05:00:00Z",
             "event_priority_tier": 0},
            ADMIN), 201)
        preempted = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert preempted["lifecycle_status"] == "SUPERSEDED"
        assert preempted["financial_status"] == "REFUNDED"

        cancelled_event = validate_success(api.cancel_calendar_event(event["id"], ADMIN))
        assert cancelled_event["event_status"] == "CANCELLED"

        after = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert after["lifecycle_status"] == "SUPERSEDED", (
            "cancelling the preempting event does not resurrect the permit")
        assert after["financial_status"] == "REFUNDED", (
            "the administrative refund already posted and stays posted")
