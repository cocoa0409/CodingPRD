"""Incident lifecycle: cyclic reopen, terminal lockdown, the lost-child
check-out gate, and the reunion requirement (PRD §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_DEFAULTS,
    set_clock, setup_staff_trio, create_incident,
    setup_checked_in_visit, get_visit_fresh,
)
from test_helpers import api_client


class TestIncidentLifecycle:
    def test_closed_incident_cannot_be_reopened(self, api):
        """PRD §3.8: "If new information emerges, a manager can reopen a
        `RESOLVED` incident back to `TRIAGED`" — reopen is declared only from
        RESOLVED.
        PRD §2.8: "the target resource must be in a valid from-state for the
        requested transition, yielding `ERR_INVALID_STATE` (HTTP 409)".

        CLOSED is terminal: reopen from CLOSED is rejected.

        Design: Corner/state_machines/closed_incident_cannot_be_reopened
        """
        staff = setup_staff_trio()
        incident = create_incident(staff["fd_headers"], kind="INJURY",
                                   severity="LOW", description="scraped knee")
        validate_success(api_client.triage_incident(incident["id"],
                                                    staff["mgr_headers"]), 200)
        validate_success(api_client.resolve_incident(
            incident["id"], {"resolution_note": "band-aid applied"},
            staff["mgr_headers"]), 200)
        validate_success(api_client.close_incident(incident["id"],
                                                   staff["mgr_headers"]), 200)

        res = api_client.reopen_incident(incident["id"], staff["mgr_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        fresh = get_success_data(
            api_client.get_incident(incident["id"], staff["mgr_headers"]))
        assert fresh["status"] == "CLOSED"

    def test_incident_resolved_can_reopen_to_triaged(self, api):
        """PRD §3.8: "If new information emerges, a manager can reopen a
        `RESOLVED` incident back to `TRIAGED`, which clears `resolved_at` and
        re-engages the lost-child check-out gate."

        Design: Corner/state_machines/incident_resolved_can_reopen_to_triaged
        """
        staff = setup_staff_trio()
        incident = create_incident(staff["fd_headers"], kind="BEHAVIOR",
                                   severity="MEDIUM",
                                   description="sandpit dispute")
        validate_success(api_client.triage_incident(incident["id"],
                                                    staff["mgr_headers"]), 200)
        resolved = validate_success(api_client.resolve_incident(
            incident["id"], {"resolution_note": "parents spoken to"},
            staff["mgr_headers"]), 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_at"] is not None

        reopened = validate_success(api_client.reopen_incident(
            incident["id"], staff["mgr_headers"]), 200)
        assert reopened["status"] == "TRIAGED"
        assert reopened["resolved_at"] is None


class TestLostChildGate:
    def test_lost_child_checkout_blocked_returns_lost_child_unresolved(self, api):
        """PRD §3.8: "from that moment a `LOST_CHILD` incident gates its
        linked visit: while the incident stands in `OPEN` or `TRIAGED`, the
        visit cannot be checked out, and the attempt fails with
        `ERR_LOST_CHILD_UNRESOLVED`."

        Design: Corner/validations_incidents/lost_child_checkout_blocked_returns_lost_child_unresolved
        """
        ctx = setup_checked_in_visit(email="gag@x.com")
        create_incident(ctx["fd_headers"], kind="LOST_CHILD",
                        severity="CRITICAL",
                        description="child separated at gate",
                        visit_id=ctx["visit"]["id"])
        set_clock(TEST_DEFAULTS["CHECKOUT_TIME"])
        res = api_client.check_out_visit(ctx["visit"]["id"], ctx["fd_headers"])
        validate_error(res, ApiErrorId.ERR_LOST_CHILD_UNRESOLVED,
                       expected_status=409)
        fresh = get_visit_fresh(ctx["visit"]["id"], ctx["mgr_headers"])
        assert fresh["admission_status"] == "CHECKED_IN"

    def test_lost_child_resolve_without_reunion_rejected(self, api):
        """PRD §3.8: "resolves a `TRIAGED` incident to `RESOLVED`, stamping
        `resolved_at` and lifting the lost-child gate — but for a `LOST_CHILD`
        incident only when `child_reunited` is submitted true, otherwise
        `ERR_CHILD_NOT_REUNITED` (HTTP 422)".

        Design: Corner/validations_incidents/lost_child_resolve_without_reunion_rejected
        """
        ctx = setup_checked_in_visit(email="gag2@x.com")
        incident = create_incident(ctx["fd_headers"], kind="LOST_CHILD",
                                   severity="CRITICAL",
                                   description="child missing near slide",
                                   visit_id=ctx["visit"]["id"])
        validate_success(api_client.triage_incident(incident["id"],
                                                    ctx["mgr_headers"]), 200)

        res = api_client.resolve_incident(
            incident["id"], {"resolution_note": "area swept"},
            ctx["mgr_headers"])
        validate_error(res, ApiErrorId.ERR_CHILD_NOT_REUNITED,
                       expected_status=422)
        fresh = get_success_data(
            api_client.get_incident(incident["id"], ctx["mgr_headers"]))
        assert fresh["status"] == "TRIAGED"
