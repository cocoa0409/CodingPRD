"""Complaint SLA boundary, lifecycle lockdown, and linked-work-order gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_complaint,
    create_work_order,
    set_clock,
    setup_active_tenancy,
    validate_error,
    validate_success,
    verify_work_order,
    walk_work_order_to_completed,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["site_manager_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


class TestComplaintSlaBoundary:
    """Difficulty instance: acknowledgement at exactly filed_at + 72h is
    compliant (strict >); one minute later breaches."""

    def _setup_two_complaints(self, api):
        ctx = setup_active_tenancy(site_name="Site SLA",
                                   household_name="Fam SLA")
        set_clock("2026-08-01T10:00:00Z")
        c1 = create_complaint(ctx["tenancy"]["id"], "HABITABILITY", "C1")
        c2 = create_complaint(ctx["tenancy"]["id"], "UTILITY", "C2")
        return ctx, c1, c2

    def test_acknowledgement_at_exactly_72h_compliant(self, api,
                                                      site_manager_headers):
        """PRD §3.7: "`sla_breached` becomes true only when the
        acknowledgement lands strictly later than seventy-two hours after
        `filed_at`; acknowledgement at exactly the seventy-two-hour mark is
        compliant."

        Design: Difficulty/boundary_precision_check/complaint_sla_exactly_72h_compliant
        """
        _, c1, _ = self._setup_two_complaints(api)
        set_clock("2026-08-04T10:00:00Z")
        acked = validate_success(api.update_complaint(
            c1["id"], {"status": "ACKNOWLEDGED"}, site_manager_headers))
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["sla_breached"] is False, (
            "Filed 2026-08-01T10:00:00Z, acknowledged exactly at the "
            "seventy-two-hour mark")

    def test_acknowledgement_one_minute_late_breaches(
            self, api, site_manager_headers):
        """PRD §3.7: "`sla_breached` becomes true only when the
        acknowledgement lands strictly later than seventy-two hours after
        `filed_at`; acknowledgement at exactly the seventy-two-hour mark is
        compliant."

        Design: Difficulty/boundary_precision_check/complaint_sla_exactly_72h_compliant
        """
        _, _, c2 = self._setup_two_complaints(api)
        set_clock("2026-08-04T10:01:00Z")
        acked = validate_success(api.update_complaint(
            c2["id"], {"status": "ACKNOWLEDGED"}, site_manager_headers))
        assert acked["sla_breached"] is True, (
            "One minute past the deadline breaches")


class TestComplaintLifecycle:
    def test_complaint_closed_terminal_lockdown(self, api,
                                                site_manager_headers):
        """PRD §3.7: "A resolved complaint is finally closed — `RESOLVED →
        CLOSED` — with a posture recompute; `CLOSED` is terminal."

        Design: Corner/state_machines/complaint_closed_terminal_lockdown
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam CL")
        complaint = create_complaint(ctx["tenancy"]["id"], "OTHER", "d")
        validate_success(api.update_complaint(
            complaint["id"], {"status": "ACKNOWLEDGED"}, MANAGER))
        validate_success(api.update_complaint(
            complaint["id"], {"status": "INVESTIGATING"}, MANAGER))
        validate_success(api.update_complaint(
            complaint["id"], {"status": "RESOLVED",
                              "resolution_note": "fixed"}, MANAGER))
        closed = validate_success(api.update_complaint(
            complaint["id"], {"status": "CLOSED"}, MANAGER))
        assert closed["status"] == "CLOSED"

        resp = api.update_complaint(complaint["id"],
                                    {"status": "INVESTIGATING"},
                                    site_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_err_linked_work_orders_open_on_resolve(
            self, api, site_manager_headers):
        """PRD §3.7: "Resolution — `INVESTIGATING → RESOLVED` — requires a
        `resolution_note` (`ERR_INVALID_REQUEST` when absent) and requires
        every work order linked through `complaint_id` to stand in `VERIFIED`,
        `CLOSED`, or `CANCELLED` (`ERR_LINKED_WORK_ORDERS_OPEN`), recomputing
        the posture on success."

        Design: Corner/errors/err_linked_work_orders_open_on_resolve
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam LW")
        complaint = create_complaint(ctx["tenancy"]["id"], "HABITABILITY",
                                     "heater broken")
        validate_success(api.update_complaint(
            complaint["id"], {"status": "ACKNOWLEDGED"}, MANAGER))
        validate_success(api.update_complaint(
            complaint["id"], {"status": "INVESTIGATING"}, MANAGER))
        wo = create_work_order(ctx["unit"]["id"], "APPLIANCE", "MAJOR",
                               "replace heater",
                               complaint_id=complaint["id"])

        blocked = api.update_complaint(
            complaint["id"], {"status": "RESOLVED",
                              "resolution_note": "done"},
            site_manager_headers)
        validate_error(blocked, ApiErrorId.ERR_LINKED_WORK_ORDERS_OPEN)

        walk_work_order_to_completed(wo["id"], completed_by="ml-1")
        verify_work_order(wo["id"], verified_by="sm-1")
        resolved = validate_success(api.update_complaint(
            complaint["id"], {"status": "RESOLVED",
                              "resolution_note": "done"},
            site_manager_headers))
        assert resolved["status"] == "RESOLVED"
