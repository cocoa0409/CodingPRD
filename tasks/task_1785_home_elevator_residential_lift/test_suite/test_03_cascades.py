"""Transitive cascades and cross-entity state gates (PRD §3.5, §3.6, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_application,
    create_dispatched_call,
    create_grant_application_payload,
    create_grant_program,
    create_install_complete_project,
    create_quoted_project,
    create_registered_project,
    create_service_call,
    create_technician,
    create_unit_with_contract,
    factories,
    get_success_data,
    make_homeowner_headers,
    make_inspector_headers,
    validate_error,
    validate_paginated,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["dealer_admin_headers"]
REGULATOR = TEST_USERS["regulator_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]


def _schedule_annual(api, ctx, start="2026-09-02T09:00:00Z", end="2026-09-02T10:00:00Z"):
    return get_success_data(api.create_inspection(
        factories.create_inspection_payload(
            ctx["unit"]["id"], ctx["inspector"]["id"], inspection_type="ANNUAL",
            scheduled_start=start, scheduled_end=end), COORD))


# ===========================================================================
# Queue A — transitive_cascade / annual_fail_cascade_depth4
# ===========================================================================

class TestAnnualFailCascadeDepth4:
    def _setup(self, api):
        """Unit IN_SERVICE/REGISTERED, ACTIVE certificate, DISPATCHED repair call,
        SCHEDULED annual inspection with the clock inside its window."""
        ctx = create_unit_with_contract(tier="STANDARD")
        get_success_data(api.set_clock({"to_iso8601": "2026-09-01T09:00:00Z"}, ADMIN))
        call = create_dispatched_call(ctx, call_type="REPAIR", description="Door operator noisy")
        annual = _schedule_annual(api, ctx)
        get_success_data(api.set_clock({"to_iso8601": "2026-09-02T09:05:00Z"}, ADMIN))
        return ctx, call, annual

    def test_failed_annual_revokes_certificate_and_suspends_unit(self, api):
        """PRD §3.6: "a failing one fires a four-hop cascade: first the unit's
        certificate in `ACTIVE` or `RENEWAL_DUE` is `REVOKED`; second the unit's
        `registration_status` moves from `REGISTERED` to `SUSPENDED`; third its
        `equipment_status` moves from `IN_SERVICE` to `OUT_OF_SERVICE`".

        Design: Difficulty/transitive_cascade/annual_fail_cascade_depth4
        """
        ctx, _call, annual = self._setup(api)
        get_success_data(api.record_inspection_result(
            annual["id"], {"result": "FAILED", "deficiency_codes": ["DOOR_INTERLOCK"]},
            make_inspector_headers(ctx["inspector"]["id"])))
        cert = get_success_data(api.get_certificate(ctx["certificate"]["id"], COORD))
        assert cert["status"] == "REVOKED"
        unit = get_success_data(api.get_unit(ctx["unit"]["id"], COORD))
        assert unit["registration_status"] == "SUSPENDED"
        assert unit["equipment_status"] == "OUT_OF_SERVICE"

    def test_failed_annual_cancels_dispatched_service_calls(self, api):
        """PRD §3.6: "fourth the unit's `OPEN` or `DISPATCHED` service calls are
        cancelled with consumed visits restored."

        Design: Difficulty/transitive_cascade/annual_fail_cascade_depth4
        """
        ctx, call, annual = self._setup(api)
        insp = get_success_data(api.record_inspection_result(
            annual["id"], {"result": "FAILED", "deficiency_codes": ["DOOR_INTERLOCK"]},
            make_inspector_headers(ctx["inspector"]["id"])))
        assert insp["status"] == "FAILED"
        call = get_success_data(api.get_service_call(call["id"], COORD))
        assert call["status"] == "CANCELLED"


# ===========================================================================
# Queue A — transitive_cascade / project_cancel_grant_clawback_cascade
# ===========================================================================

class TestProjectCancelGrantClawbackCascade:
    def _setup(self, api):
        ctx = create_quoted_project()
        program = create_grant_program()
        app = create_approved_application(ctx, program)
        return ctx, program, app

    def test_cancel_withdraws_approved_application(self, api):
        """PRD §3.8: "Cancellation cascades outward in hops: first, the project's
        non-terminal permit applications and structural work orders move to `CANCELLED`,
        its `SUBMITTED` grant applications move to `WITHDRAWN`, and its `SCHEDULED`
        inspections move to `CANCELLED`; second, its `APPROVED` grant applications move
        to `WITHDRAWN` with the `final_award` credited back to the program pool".

        Design: Difficulty/transitive_cascade/project_cancel_grant_clawback_cascade
        """
        ctx, _program, app = self._setup(api)
        project = get_success_data(api.cancel_project(ctx["project"]["id"], COORD))
        assert project["status"] == "CANCELLED"
        app = get_success_data(api.get_grant_application(app["id"], OFFICER))
        assert app["status"] == "WITHDRAWN"

    def test_pool_credit_caused_by_withdrawal_restores_program(self, api):
        """PRD §3.8: "second, its `APPROVED` grant applications move to `WITHDRAWN` with
        the `final_award` credited back to the program pool; third, a pool credit that
        lifts an `EXHAUSTED` program above zero reopens it to `OPEN`."

        Design: Difficulty/transitive_cascade/project_cancel_grant_clawback_cascade
        """
        ctx, program, _app = self._setup(api)
        program = get_success_data(api.get_grant_program(program["id"], OFFICER))
        assert program["remaining_pool"] == 40000.00  # after the 10000.00 approval
        get_success_data(api.cancel_project(ctx["project"]["id"], COORD))
        program = get_success_data(api.get_grant_program(program["id"], OFFICER))
        assert program["remaining_pool"] == 50000.00
        assert program["status"] == "OPEN"


# ===========================================================================
# Queue A — transitive_cascade / grant_approve_pool_exhaustion_cascade
# ===========================================================================

class TestGrantApprovePoolExhaustionCascade:
    def _setup(self, api):
        ctx1 = create_quoted_project(prop_overrides={"address_line": "1 Pine St"})
        ctx2 = create_quoted_project(prop_overrides={"address_line": "2 Oak Ave"})
        program = create_grant_program(program_name="SmallPool", funder_name="County Fund",
                                       max_award=10000.00, coverage_percent=0.50,
                                       total_pool=15000.00)
        app1 = create_approved_application(ctx1, program)
        app2 = get_success_data(api.create_grant_application(
            create_grant_application_payload(ctx2["project"]["id"], program["id"]),
            make_homeowner_headers(ctx2["prop"]["owner_user_id"])))
        return program, app1, app2

    def test_second_approval_clamps_to_remaining_pool(self, api):
        """PRD §3.8: "then takes the smallest of three caps: that coverage amount, the
        program's `max_award`, and the program's `remaining_pool`. The award is debited
        from the pool immediately".

        Design: Difficulty/transitive_cascade/grant_approve_pool_exhaustion_cascade
        """
        _program, _app1, app2 = self._setup(api)
        approved = get_success_data(api.approve_grant_application(
            app2["id"], {"verified_income": 42000.00}, OFFICER))
        # coverage 0.50 x 33000 = 16500, max 10000, pool remaining 5000 -> 5000
        assert approved["final_award"] == 5000.00

    def test_pool_reaching_zero_flips_program_to_exhausted(self, api):
        """PRD §3.8: "a debit that drains the pool to exactly zero flips the program
        from `OPEN` to `EXHAUSTED`."

        Design: Difficulty/transitive_cascade/grant_approve_pool_exhaustion_cascade
        """
        program, _app1, app2 = self._setup(api)
        get_success_data(api.approve_grant_application(
            app2["id"], {"verified_income": 42000.00}, OFFICER))
        program = get_success_data(api.get_grant_program(program["id"], OFFICER))
        assert program["remaining_pool"] == 0.00
        assert program["status"] == "EXHAUSTED"


# ===========================================================================
# Queue A — cross_entity_state_dependency / annual_inspection_requires_unit_in_service
# ===========================================================================

class TestAnnualInspectionRequiresUnitInService:
    def test_annual_rejected_on_installed_unit(self, api):
        """PRD §3.6: "An `ANNUAL` inspection may be scheduled only against a unit whose
        equipment is `IN_SERVICE`".

        Design: Difficulty/cross_entity_state_dependency/annual_inspection_requires_unit_in_service
        """
        ctx = create_install_complete_project()
        inspector = create_technician(name="Quinn Inspector", certification="QEI")
        resp = api.create_inspection(
            factories.create_inspection_payload(
                ctx["unit"]["id"], inspector["id"], inspection_type="ANNUAL",
                scheduled_start="2026-08-13T09:00:00Z", scheduled_end="2026-08-13T10:00:00Z"),
            COORD)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_IN_SERVICE)
        unit = get_success_data(api.get_unit(ctx["unit"]["id"], COORD))
        assert unit["equipment_status"] == "INSTALLED"

    def test_annual_rejection_creates_no_inspection(self, api):
        """PRD §3.6: "An `ANNUAL` inspection may be scheduled only against a unit whose
        equipment is `IN_SERVICE`; a `REINSPECTION` may be scheduled only when the
        unit's latest terminal inspection was `FAILED`".

        Design: Difficulty/cross_entity_state_dependency/annual_inspection_requires_unit_in_service
        """
        ctx = create_install_complete_project()
        inspector = create_technician(name="Quinn Inspector", certification="QEI")
        resp = api.create_inspection(
            factories.create_inspection_payload(
                ctx["unit"]["id"], inspector["id"], inspection_type="ANNUAL",
                scheduled_start="2026-08-13T09:00:00Z", scheduled_end="2026-08-13T10:00:00Z"),
            COORD)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_IN_SERVICE)
        inspections, meta = validate_paginated(
            api.list_inspections(COORD, params={"unit_id": ctx["unit"]["id"]}))
        assert inspections == []


# ===========================================================================
# Queue A — cross_entity_state_dependency / certificate_application_requires_acceptance_passed
# ===========================================================================

class TestCertificateApplicationRequiresAcceptancePassed:
    def test_certificate_rejected_while_acceptance_only_scheduled(self, api):
        """PRD §3.6: "Application requires the unit's latest `ACCEPTANCE` or
        `MODERNIZATION_ACCEPTANCE` inspection to be `PASSED`
        (`ERR_ACCEPTANCE_NOT_PASSED`)".

        Design: Difficulty/cross_entity_state_dependency/certificate_application_requires_acceptance_passed
        """
        ctx = create_install_complete_project()
        inspector = create_technician(name="Quinn Inspector", certification="QEI")
        get_success_data(api.create_inspection(
            factories.create_inspection_payload(
                ctx["unit"]["id"], inspector["id"],
                scheduled_start="2026-08-13T10:00:00Z", scheduled_end="2026-08-13T11:00:00Z",
                project_id=ctx["project"]["id"]), COORD))
        resp = api.create_certificate(
            factories.create_certificate_payload(ctx["unit"]["id"]), COORD)
        validate_error(resp, ApiErrorId.ERR_ACCEPTANCE_NOT_PASSED)

    def test_certificate_rejection_creates_no_certificate(self, api):
        """PRD §3.6: "Application requires the unit's latest `ACCEPTANCE` or
        `MODERNIZATION_ACCEPTANCE` inspection to be `PASSED`
        (`ERR_ACCEPTANCE_NOT_PASSED`) and creates a certificate in `PENDING_ISSUANCE`."

        Design: Difficulty/cross_entity_state_dependency/certificate_application_requires_acceptance_passed
        """
        ctx = create_install_complete_project()
        inspector = create_technician(name="Quinn Inspector", certification="QEI")
        get_success_data(api.create_inspection(
            factories.create_inspection_payload(
                ctx["unit"]["id"], inspector["id"],
                scheduled_start="2026-08-13T10:00:00Z", scheduled_end="2026-08-13T11:00:00Z",
                project_id=ctx["project"]["id"]), COORD))
        resp = api.create_certificate(
            factories.create_certificate_payload(ctx["unit"]["id"]), COORD)
        validate_error(resp, ApiErrorId.ERR_ACCEPTANCE_NOT_PASSED)
        certs, _meta = validate_paginated(
            api.list_certificates(COORD, params={"unit_id": ctx["unit"]["id"]}))
        assert certs == []


# ===========================================================================
# Queue A — cross_entity_state_dependency / install_schedule_requires_unexpired_permit
# ===========================================================================

class TestInstallScheduleRequiresUnexpiredPermit:
    def _setup_expired_permit(self, api):
        ctx = create_quoted_project()
        permit = get_success_data(api.create_permit(
            factories.create_permit_payload(ctx["project"]["id"]), COORD))
        permit = get_success_data(api.approve_permit(permit["id"], REGULATOR))
        # Permit approved at the default clock: valid_through 2027-01-28.
        get_success_data(api.set_clock({"to_iso8601": "2027-02-02T00:00:00Z"}, ADMIN))
        return ctx, permit

    def test_clock_sweep_expires_permit_but_leaves_project(self, api):
        """PRD §3.3: "Time works against an approved permit: when the clock sweep finds
        the clock past `valid_through` while installation is incomplete, the application
        moves from `APPROVED` to `EXPIRED`. Expiry does not move the project".

        Design: Difficulty/cross_entity_state_dependency/install_schedule_requires_unexpired_permit
        """
        ctx, permit = self._setup_expired_permit(api)
        permit = get_success_data(api.get_permit(permit["id"], COORD))
        assert permit["status"] == "EXPIRED"
        project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
        assert project["status"] == "READY_FOR_INSTALL"

    def test_scheduling_against_expired_permit_rejected(self, api):
        """PRD §3.3: "Expiry does not move the project, but scheduling an installation
        against an expired permit fails with `ERR_PERMIT_EXPIRED_FOR_INSTALL`".

        Design: Difficulty/cross_entity_state_dependency/install_schedule_requires_unexpired_permit
        """
        ctx, _permit = self._setup_expired_permit(api)
        resp = api.schedule_installation(ctx["project"]["id"], {
            "install_start_date": "2027-02-10T08:00:00Z",
            "install_end_date": "2027-02-15T17:00:00Z",
        }, COORD)
        validate_error(resp, ApiErrorId.ERR_PERMIT_EXPIRED_FOR_INSTALL)
