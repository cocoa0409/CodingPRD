"""Operator certification gates, assembly-verification guards, and
ownership-scoped actions (PRD sections 2.10, 3.1, 3.2, 3.3).

Covers design instances:
  Corner/validations/certification_expiry_boundary_today_valid_yesterday_expired
  Corner/cross_cutting_layers/revoked_certification_blocks_checklist_and_double_revoke_fails
  Corner/errors/annual_cert_must_cover_the_season_at_verify
  Corner/errors/verify_assembly_requires_covering_setup_shift
  Corner/errors/verify_assembly_twice_rejected
  Corner/rbac/inspector_cannot_complete_unassigned_appointment_returns_403
  Corner/rbac/crew_member_cannot_confirm_others_shift_returns_403
"""
from test_helpers import (
    ApiErrorId,
    make_crew_headers,
    make_inspector_headers,
    make_manager_headers,
    make_operator_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


class TestCertificationExpiryBoundary:
    def test_expires_today_valid_expired_yesterday_rejected(self, api):
        """PRD section 3.3: "A certification never carries a stored expired
        state: validity is evaluated at enforcement time, and a certification
        is valid exactly when its status is `ACTIVE` and its `expires_on` is on
        or after the current date." PRD section 2.10: "**Safety and compliance
        (redemption creation; checklist creation, submission, and
        countersignature; assembly verification and ride resumption; day
        resumption; permit approval and denial).**" — a caller without "a
        valid operator certification for the ride's class" is rejected with
        `ERR_CERTIFICATION_MISSING`.

        op1's certification expires today (valid); op2's expired yesterday.

        Design: Corner/validations/certification_expiry_boundary_today_valid_yesterday_expired
        """
        ctx = fx.setup_permitted_fair("V8", operator_functions=None)
        sup = ctx["sup"]
        op1 = fx.create_staff_via_manager(sup, "Op One V8", ["OPERATOR"])
        op2 = fx.create_staff_via_manager(sup, "Op Two V8", ["OPERATOR"])
        fx.certify_operator(op1["id"], expires_on="2026-08-03")
        fx.certify_operator(op2["id"], expires_on="2026-08-02")
        fx.begin_day(ctx)
        chk = validate_success(api.create_checklist(
            {"ride_id": ctx["ride"]["id"], "operating_day_id": ctx["day"]["id"],
             "items_total": 5},
            make_operator_headers(op1["id"])), 201)
        assert chk["status"] == "DRAFT"
        resp = api.create_checklist(
            {"ride_id": ctx["ride"]["id"], "operating_day_id": ctx["day"]["id"],
             "items_total": 5},
            make_operator_headers(op2["id"]))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_MISSING, 422)


class TestRevokedCertification:
    def test_revoked_cert_blocks_checklist_and_double_revoke_fails(self, api):
        """PRD section 3.3: "A certification is `ACTIVE` upon issuance and may
        later be moved to `REVOKED` by a `StateProgramAdmin` or a
        `StateInspector`; revoking an already-`REVOKED` certification is
        `ERR_CERT_INVALID_STATE`" and "validity is evaluated at enforcement
        time, and a certification is valid exactly when its status is `ACTIVE`
        and its `expires_on` is on or after the current date."

        Revocation by a StateInspector takes effect immediately: the operator's
        next checklist creation fails the safety-family certification gate.

        Design: Corner/cross_cutting_layers/revoked_certification_blocks_checklist_and_double_revoke_fails
        """
        ctx = fx.setup_permitted_fair("CC5", operator_functions=None)
        sup = ctx["sup"]
        insp1 = ctx["inspectors"][0]
        op = fx.create_staff_via_manager(sup, "Op CC5", ["OPERATOR"])
        cert = fx.certify_operator(op["id"], ride_class="THRILL")
        fx.begin_day(ctx)
        revoked = validate_success(api.revoke_certification(
            cert["id"], {}, make_inspector_headers(insp1["id"])))
        assert revoked["status"] == "REVOKED"
        resp = api.create_checklist(
            {"ride_id": ctx["ride"]["id"], "operating_day_id": ctx["day"]["id"],
             "items_total": 5},
            make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_MISSING, 422)
        resp = api.revoke_certification(cert["id"], {}, make_inspector_headers(insp1["id"]))
        validate_error(resp, ApiErrorId.ERR_CERT_INVALID_STATE, 409)


class TestVerifyAssemblyGuards:
    def test_annual_cert_must_cover_the_season(self, api):
        """PRD section 3.1: "the manufacturer annual certification must cover
        the whole season, meaning `annual_cert_expires_on` falls on or after
        the fair's `closing_date` (`ERR_ANNUAL_CERT_EXPIRED`)".

        The certification expires 2026-08-04, one day short of closing
        2026-08-05; the covering SETUP shift exists, so only the safety gate
        can fire.

        Design: Corner/errors/annual_cert_must_cover_the_season_at_verify
        """
        ctx = fx.setup_fair_with_staff("ER5")
        sup = ctx["sup"]
        crew = fx.create_staff_via_manager(sup, "Crew ER5", ["CREW"])
        ride = fx.create_ride(sup, annual_cert_expires_on="2026-08-04",
                              serial_number="SN-ER5-1")
        fx.book_setup_shift(sup, crew)
        resp = api.verify_assembly(ride["id"], {}, make_crew_headers(crew["id"]))
        validate_error(resp, ApiErrorId.ERR_ANNUAL_CERT_EXPIRED, 422)
        ride_after = fx.get_ride(sup, ride["id"])
        assert ride_after["setup_status"] == "INSTALLED"

    def test_verify_assembly_requires_covering_setup_shift(self, api):
        """PRD section 3.1: "the caller must hold a covering crew shift — a
        `CrewShift` whose `shift_role` is `SETUP`, whose `work_date` equals the
        current date, and whose status is `SCHEDULED` or `CONFIRMED`
        (`ERR_NO_COVERING_SHIFT`)."

        Design: Corner/errors/verify_assembly_requires_covering_setup_shift
        """
        ctx = fx.setup_fair_with_staff("ER9")
        sup = ctx["sup"]
        crew = fx.create_staff_via_manager(sup, "Crew ER9", ["CREW"])
        ride = fx.create_ride(sup, serial_number="SN-ER9-1")
        resp = api.verify_assembly(ride["id"], {}, make_crew_headers(crew["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_COVERING_SHIFT, 422)
        ride_after = fx.get_ride(sup, ride["id"])
        assert ride_after["setup_status"] == "INSTALLED"

    def test_verify_assembly_twice_rejected(self, api):
        """PRD section 3.1: "Four conditions gate the verification, in the
        pipeline order of §2.10: the fair must be `SETUP` or
        `PERMIT_REQUESTED` (`ERR_FAIR_INVALID_STATE`); the ride must still be
        `INSTALLED` (`ERR_RIDE_INVALID_STATE`); ...". An already
        `SETUP_VERIFIED` ride fails the still-INSTALLED precondition — the
        setup dimension moves strictly forward.

        Design: Corner/errors/verify_assembly_twice_rejected
        """
        ctx = fx.setup_verified_ride("ER12")
        crew, ride = ctx["crew"], ctx["ride"]
        assert ride["setup_status"] == "SETUP_VERIFIED"
        resp = api.verify_assembly(ride["id"], {}, make_crew_headers(crew["id"]))
        validate_error(resp, ApiErrorId.ERR_RIDE_INVALID_STATE, 409)


class TestOwnershipScopedActions:
    def test_inspector_cannot_complete_unassigned_appointment(self, api):
        """PRD section 3.2: "Completion belongs to the assigned inspector
        alone. A `StateInspector` completes a `SCHEDULED` appointment by
        recording an `outcome` of PASS or FAIL, with optional free-text
        `findings`; completing from any other status is
        `ERR_APPOINTMENT_INVALID_STATE`, a caller whose `X-User-ID` is not the
        appointment's `inspector_id` is `ERR_FORBIDDEN`, and completing before
        the `scheduled_date` has arrived is `ERR_APPOINTMENT_NOT_DUE`."

        Design: Corner/rbac/inspector_cannot_complete_unassigned_appointment_returns_403
        """
        ctx = fx.setup_permit_requested("RB2")
        sup = ctx["sup"]
        appt = fx.schedule_fair_wide(sup)
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        other = [i for i in ctx["inspectors"] if i["id"] != appt["inspector_id"]][0]
        resp = api.complete_appointment(appt["id"], {"outcome": "PASS"},
                                        make_inspector_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        appt_after = fx.get_success_data(api.get_appointment(
            appt["id"], make_manager_headers(sup["id"])))
        assert appt_after["status"] == "SCHEDULED"

    def test_crew_member_cannot_confirm_others_shift(self, api):
        """PRD section 3.3: "The assigned crew member — and only that worker,
        by `X-User-ID` against the shift's `staff_id` (`ERR_FORBIDDEN`) —
        confirms their own shift, moving it to `CONFIRMED`, provided the
        `work_date` has not already passed (`ERR_SHIFT_OUT_OF_SEASON`)."

        Design: Corner/rbac/crew_member_cannot_confirm_others_shift_returns_403
        """
        ctx = fx.setup_fair_with_staff("RB3")
        sup = ctx["sup"]
        crew1 = fx.create_staff_via_manager(sup, "Crew One", ["CREW"])
        crew2 = fx.create_staff_via_manager(sup, "Crew Two", ["CREW"])
        shift = fx.book_setup_shift(sup, crew1)
        resp = api.confirm_shift(shift["id"], {}, make_crew_headers(crew2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        shift_after = fx.get_shift(sup, shift["id"])
        assert shift_after["status"] == "SCHEDULED"
