"""Contractor permits: approval guards, session binding, and the automatic
close on release of the bound session."""
from test_helpers import (
    ApiErrorId,
    assert_contractor_permit,
    bootstrap_manager,
    create_approved_permit,
    create_contractor_permit_payload,
    create_lockout_session_payload,
    create_machine,
    get_machine,
    get_permit,
    make_authorized_employee_headers,
    make_ehs_manager_headers,
    register_employee,
    register_qualified_employee,
    run_session_to_released,
    setup_bound_active_permit,
    setup_machine_with_active_procedure,
    setup_session_locked,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPermitApprovalGuards:
    def test_expired_insurance_rejected_at_approval(self, api):
        """PRD §3.9: "Approval carries three guards, applied consistently with
        the precedence pipeline of §2.8: the payload's `coordination_meeting_at`
        — recording when the host/contractor coordination meeting happened —
        must be present and not later than the clock (`ERR_VALIDATION`); the
        machine must be `IN_SERVICE` (`ERR_MACHINE_NOT_IN_SERVICE`); and the
        contractor's insurance must still be valid, meaning
        `insurance_valid_until` is strictly later than the clock
        (`ERR_INSURANCE_EXPIRED`)."
        PRD §2.4: "Before the clock has been explicitly set, it reads exactly
        2026-08-01T00:00:00Z; the server must never fall back to wall-clock time."

        Design: Corner/validations/insurance_expired_on_permit_approve_rejected
        """
        mgr = bootstrap_manager("E-MGR-IN", "Mgr IN")
        coordinator = register_employee(mgr, "E-W1-IN", "W1 IN")
        machine = create_machine(mgr, asset_tag="A-IN-1", name="Oven",
                                 area="Bay 26")
        coordinator_headers = make_authorized_employee_headers(coordinator["id"])
        expired = validate_success(api.create_contractor_permit(
            create_contractor_permit_payload(
                machine["id"], company_name="Old Insurance Co",
                insurance_valid_until="2026-07-01T00:00:00Z"),
            coordinator_headers), expected_status=201)
        fresh = validate_success(api.create_contractor_permit(
            create_contractor_permit_payload(
                machine["id"], company_name="Fresh Insurance Co",
                insurance_valid_until="2027-01-01T00:00:00Z"),
            coordinator_headers), expected_status=201)

        resp = api.approve_contractor_permit(
            expired["id"], {"coordination_meeting_at": "2026-07-15T00:00:00Z"},
            make_ehs_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_INSURANCE_EXPIRED)
        assert get_permit(mgr, expired["id"])["status"] == "REQUESTED"

        approved = validate_success(api.approve_contractor_permit(
            fresh["id"], {"coordination_meeting_at": "2026-07-15T00:00:00Z"},
            make_ehs_manager_headers(mgr["id"])))
        assert approved["status"] == "APPROVED"


class TestContractorSessionGuards:
    def test_contractor_session_without_permit_rejected(self, api):
        """PRD §3.5: "Creation is guarded, and the guards run in this order: the
        machine must be `IN_SERVICE` (`ERR_MACHINE_NOT_IN_SERVICE`); the
        procedure must be `ACTIVE` (`ERR_PROCEDURE_NOT_ACTIVE`); the procedure's
        audit must not be overdue, with the clock exactly equal to `audit_due_at`
        still passing (`ERR_AUDIT_OVERDUE`); the creator must be currently
        qualified (`ERR_TRAINING_NOT_CURRENT`); no other session may be occupying
        the machine — occupation is the half-open interval from a session's
        creation to its release, so any session in `SETUP`, `LOCKED`, or
        `CLEARED` conflicts, while a predecessor released at exactly the current
        instant does not (`ERR_MACHINE_SESSION_CONFLICT`); and, for a
        `CONTRACTOR` session, an `APPROVED` contractor permit must exist for the
        machine (`ERR_PERMIT_REQUIRED`)."

        Design: Corner/validations/contractor_session_without_permit_rejected
        """
        ctx_mgr = bootstrap_manager("E-MGR-PR", "Mgr PR")
        primary = register_qualified_employee(ctx_mgr, "E-W1-PR", "W1 PR")
        machine, survey, procedure = setup_machine_with_active_procedure(
            ctx_mgr, primary, asset_tag="A-PR-1", name="Oven", area="Bay 27")

        resp = api.create_lockout_session(
            create_lockout_session_payload(machine["id"], procedure["id"],
                                           session_type="CONTRACTOR"),
            make_authorized_employee_headers(primary["id"]))
        validate_error(resp, ApiErrorId.ERR_PERMIT_REQUIRED)
        _sessions, meta = validate_paginated(api.list_lockout_sessions(
            make_ehs_manager_headers(ctx_mgr["id"]),
            params={"machine_id": machine["id"]}))
        assert meta["total_count"] == 0


class TestPermitActivation:
    def test_activate_with_individual_session_rejected(self, api):
        """PRD §3.9: "The referenced session must be `LOCKED`, of `session_type`
        `CONTRACTOR`, on the permit's own machine, and led by the coordinator as
        its `primary_employee_id`; any mismatch is rejected with
        `ERR_PERMIT_SESSION_MISMATCH`."

        Design: Corner/validations/permit_activate_with_mismatched_session_rejected
        """
        ctx = setup_session_locked(asset_tag="A-PM-1", lock_no="L-PM-1",
                                   tag_no="T-PM-1")
        permit = create_approved_permit(ctx["mgr"], ctx["primary"],
                                        ctx["machine"]["id"])
        assert permit["status"] == "APPROVED"

        resp = api.activate_contractor_permit(
            permit["id"], {"session_id": ctx["session"]["id"]},
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PERMIT_SESSION_MISMATCH)
        assert get_permit(ctx["mgr"], permit["id"])["status"] == "APPROVED", \
            "the permit is unchanged by the rejected activation"


class TestPermitLifecycle:
    def test_release_of_bound_session_closes_permit(self, api):
        """PRD §3.9: "The permit then sits in `ACTIVE` until the bound session is
        released, at which point the permit closes automatically, moving to the
        terminal `CLOSED` state."
        PRD §3.5: "Releasing then moves the session from `CLEARED` to the
        terminal `RELEASED` state: `ended_at` is stamped with the clock, the
        machine's `open_session_count` is recomputed, and any contractor permit
        bound to this session in `ACTIVE` status is automatically closed."

        Design: Corner/state_machines/permit_closes_on_bound_session_release
        """
        ctx = setup_bound_active_permit(asset_tag="A-PC2-1")
        assert ctx["permit"]["status"] == "ACTIVE"
        assert ctx["session"]["status"] == "LOCKED"

        released = run_session_to_released(
            ctx["coordinator"], ctx["session"]["id"], ctx["lock"]["id"])
        assert released["status"] == "RELEASED"

        permit = get_permit(ctx["mgr"], ctx["permit"]["id"])
        assert_contractor_permit(permit)
        assert permit["status"] == "CLOSED", \
            "releasing the bound session auto-closes the permit"
        assert get_machine(ctx["mgr"], ctx["machine"]["id"])["open_session_count"] == 0
