"""Custodial verification is gated on the owning permit being COMPLETED —
across the aggregate boundary, a work order cannot be verified while its
permit is merely ACTIVE (PRD §3.6, §2.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    invoice_of_kind,
    make_booking_env, make_approved_permit_in_env,
    capture_deposit, set_clock, get_single_work_order,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]

# Sat 2026-09-12 17:00-20:00 site-local; blocked span 23:30-03:30Z (4.0h est).
EVENT_START = "2026-09-13T00:00:00Z"
EVENT_END = "2026-09-13T03:00:00Z"


def _active_permit_with_work_order(api, clock_during_event="2026-09-13T02:00:00Z"):
    """Approved, secured permit driven to ACTIVE (clock mid-event, before
    occupancy_end). Returns (env, permit, work_order)."""
    env = make_booking_env()
    req, permit = make_approved_permit_in_env(
        env, event_title="Auction Night", headcount_estimate=100,
        starts_at=EVENT_START, ends_at=EVENT_END)
    capture_deposit(env, permit["id"], 10000, "dep-i-1")
    set_clock(clock_during_event)
    active = validate_success(api.get_permit(permit["id"], DIRECTOR))
    assert active["lifecycle_status"] == "ACTIVE", "Setup: permit must be ACTIVE"
    return env, active, get_single_work_order(permit["id"])


class TestWorkOrderVerifyGatedOnPermitCompletion:
    def test_verify_while_permit_active_rejected(self, api):
        """PRD §3.6: "Verification — the `CustodialSupervisor` attesting
        `actual_hours`, a field that is null until verification and thereafter
        holds a value greater than zero carried to two decimals — requires the
        permit to be `COMPLETED` and moves the order `IN_PROGRESS` → `VERIFIED`".
        PRD §2.9: "**Lifecycle state legality.** The target resource's current
        state must permit the operation — approval requires `UNDER_REVIEW`,
        permit cancellation requires `ISSUED`, terminal states reject all
        mutations — else `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/work_order_verify_gated_on_permit_completion
        """
        env, permit, order = _active_permit_with_work_order(api)
        assert order["wo_status"] == "IN_PROGRESS"

        res = api.verify_work_order(order["id"], {"actual_hours": 4.0}, SUPERVISOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_work_order(order["id"], SUPERVISOR))
        assert after["wo_status"] == "IN_PROGRESS"
        assert after["actual_hours"] is None, "actual_hours stays null until verification"

    def test_verify_after_completion_succeeds_and_recomputes_final(self, api):
        """PRD §3.6: "Verification — the `CustodialSupervisor` attesting
        `actual_hours`, a field that is null until verification and thereafter
        holds a value greater than zero carried to two decimals — requires the
        permit to be `COMPLETED` and moves the order `IN_PROGRESS` → `VERIFIED`,
        recomputing the `FINAL` invoice's staffing and after-hours components
        from the verified hours."

        Design: Difficulty/cross_entity_state_dependency/work_order_verify_gated_on_permit_completion
        """
        env, permit, order = _active_permit_with_work_order(api)
        # Past occupancy_end: the SiteCoordinator can now mark completion.
        set_clock("2026-09-13T12:00:00Z")
        validate_success(api.complete_permit(permit["id"], COORDINATOR))

        verified = validate_success(api.verify_work_order(
            order["id"], {"actual_hours": 6.5}, SUPERVISOR))
        assert verified["actual_hours"] == 6.5
        # The order has left IN_PROGRESS; whether it is observed at VERIFIED or
        # already BILLED depends on when the FINAL-invoice-issued check fires.
        assert verified["wo_status"] in ("VERIFIED", "BILLED")

        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        final = invoice_of_kind(invoices, "FINAL")
        assert final["staffing_charge_cents"] == 26000   # 6.5h x 4000
        assert final["after_hours_charge_cents"] == 19500  # 0.75 x 26000
