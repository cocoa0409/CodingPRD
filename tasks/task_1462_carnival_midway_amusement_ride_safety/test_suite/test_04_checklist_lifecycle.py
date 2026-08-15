"""Daily checklist lifecycle: the submit/reject revision loop, license gating,
segregation of duties, per-(ride, day) uniqueness, and the open-gates compound
clearance (PRD section 3.4).

Covers design instances:
  Difficulty/non_linear_state_machine/checklist_rejection_loop_recovers_to_countersigned
  Difficulty/cross_entity_state_dependency/checklist_creation_gated_by_ride_license
  Corner/state_machines/checklist_double_submit_rejected
  Corner/errors/duplicate_checklist_and_incomplete_submit_errors
  Corner/validations/checklist_countersigner_same_as_performer_rejected
  Corner/state_machines/open_gates_compound_gate_requires_every_licensed_ride_countersigned
"""
from test_helpers import (
    ApiErrorId,
    make_manager_headers,
    make_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


class TestChecklistRejectionLoop:
    def test_reject_loops_back_to_draft_and_clears_items(self, api):
        """PRD section 3.4: "a `FairManager` rejects a `SUBMITTED` checklist
        back to `DRAFT`, supplying a `reason`; rejection nulls both
        `items_passed` and `countersigned_by_staff_id`, records the
        `rejection_reason`, advances the `version`, and lets the performer
        correct and resubmit."

        Design: Difficulty/non_linear_state_machine/checklist_rejection_loop_recovers_to_countersigned
        """
        ctx = fx.setup_permitted_fair("G")
        fx.begin_day(ctx)
        op, sup = ctx["op"], ctx["sup"]
        chk = fx.open_checklist(op, ctx["ride"]["id"], ctx["day"]["id"], items_total=5)
        created_version = chk["version"]
        chk = fx.submit_checklist(op, chk["id"], 5)
        assert chk["status"] == "SUBMITTED"
        assert chk["version"] == created_version + 1, (
            "submit must advance the checklist version by exactly one")
        chk = fx.reject_checklist(sup, chk["id"], reason="photo of brake gauge missing")
        assert chk["status"] == "DRAFT"
        assert chk["items_passed"] is None, "rejection must null items_passed"
        assert chk["countersigned_by_staff_id"] is None
        assert chk["rejection_reason"] == "photo of brake gauge missing"
        assert chk["version"] == created_version + 2, (
            "reject must advance the checklist version by exactly one")

    def test_resubmit_after_reject_countersigns_with_fresh_version(self, api):
        """PRD section 3.4: "the `expected_checklist_version` handshake of
        section 2.6 must match (`ERR_STALE_CHECKLIST_VERSION`). The
        countersigner is recorded in `countersigned_by_staff_id`, the checklist
        moves to the terminal `COUNTERSIGNED`, and its `version` advances."

        The loop DRAFT -> SUBMITTED -> DRAFT -> SUBMITTED -> COUNTERSIGNED
        bumps the version on every pass, so the countersign must reference the
        post-resubmission version.

        Design: Difficulty/non_linear_state_machine/checklist_rejection_loop_recovers_to_countersigned
        """
        ctx = fx.setup_permitted_fair("Gb")
        fx.begin_day(ctx)
        op, sup = ctx["op"], ctx["sup"]
        chk = fx.open_checklist(op, ctx["ride"]["id"], ctx["day"]["id"], items_total=5)
        chk = fx.submit_checklist(op, chk["id"], 5)
        chk = fx.reject_checklist(sup, chk["id"], reason="photo of brake gauge missing")
        chk = fx.submit_checklist(op, chk["id"], 5)
        resubmit_version = chk["version"]
        resp = api.countersign_checklist(
            chk["id"], {"expected_checklist_version": resubmit_version},
            make_manager_headers(sup["id"]))
        chk = validate_success(resp)
        assert chk["status"] == "COUNTERSIGNED"
        assert chk["countersigned_by_staff_id"] == sup["id"]
        assert chk["version"] == resubmit_version + 1


class TestChecklistLicenseGate:
    def test_checklist_create_rejected_when_ride_not_licensed(self, api):
        """PRD section 3.4: "One checklist per ride per day is allowed; a
        second is rejected with `ERR_DUPLICATE_CHECKLIST`, and a ride whose
        license is not `LICENSED` cannot be checked in at all
        (`ERR_RIDE_NOT_LICENSED`)."

        The ride was registered after the permit was approved, so it stays
        INSTALLED/PENDING; the day is correctly in CHECKLIST_PHASE, yet the
        ride's own license dimension blocks the checklist.

        Design: Difficulty/cross_entity_state_dependency/checklist_creation_gated_by_ride_license
        """
        ctx = fx.setup_permitted_fair("P")
        sup = ctx["sup"]
        ride2 = fx.create_ride(sup, name="Late Arrival", serial_number="SN-P-2")
        fx.begin_day(ctx)
        resp = api.create_checklist(
            {"ride_id": ride2["id"], "operating_day_id": ctx["day"]["id"],
             "items_total": 5},
            make_operator_headers(ctx["op"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RIDE_NOT_LICENSED, 409)
        ride2_after = fx.get_ride(sup, ride2["id"])
        assert ride2_after["license_status"] == "PENDING"
        assert ride2_after["setup_status"] == "INSTALLED"
        data, meta = validate_paginated(api.list_checklists(
            make_manager_headers(sup["id"]), params={"ride_id": ride2["id"]}))
        assert meta["total_count"] == 0 and data == [], (
            "no checklist may be persisted for an unlicensed ride")

    def test_ride_audit_pass_licenses_late_ride_then_checklist_opens(self, api):
        """PRD section 3.2: "A passed `RIDE_AUDIT` resets the audited ride's
        `cycles_since_inspection` to zero and moves its `license_status` from
        `PENDING` or `SUSPENDED` to `LICENSED`."

        The license gate is a cross-entity dependency: once the audit flips
        the late-registered ride to LICENSED, the same checklist creation that
        was blocked now succeeds.

        Design: Difficulty/cross_entity_state_dependency/checklist_creation_gated_by_ride_license
        """
        ctx = fx.setup_permitted_fair("Pb")
        sup = ctx["sup"]
        ride2 = fx.create_ride(sup, name="Late Arrival", serial_number="SN-Pb-2")
        fx.begin_day(ctx)
        audit = fx.schedule_ride_audit(sup, ride2["id"])
        fx.complete_appointment(audit, outcome="PASS")
        ride2_after = fx.get_ride(sup, ride2["id"])
        assert ride2_after["license_status"] == "LICENSED"
        chk = fx.open_checklist(ctx["op"], ride2["id"], ctx["day"]["id"], items_total=5)
        assert chk["status"] == "DRAFT"
        assert chk["performed_by_staff_id"] == ctx["op"]["id"]


class TestChecklistSubmitRules:
    def test_double_submit_rejected(self, api):
        """PRD section 3.4: "Submission belongs to the performer alone: the
        caller must be the `performed_by_staff_id` (`ERR_FORBIDDEN`), the
        checklist must be `DRAFT` (`ERR_CHECKLIST_INVALID_STATE`), the day must
        still be in `CHECKLIST_PHASE` (`ERR_INVALID_DAY_POSTURE`), and the
        caller must hold a valid certification for the ride's `ride_class`
        (`ERR_CERTIFICATION_MISSING`)." A second submit against a `SUBMITTED`
        checklist is not idempotent.

        Design: Corner/state_machines/checklist_double_submit_rejected
        """
        ctx = fx.setup_permitted_fair("SM4")
        fx.begin_day(ctx)
        op = ctx["op"]
        chk = fx.open_checklist(op, ctx["ride"]["id"], ctx["day"]["id"], items_total=5)
        chk = fx.submit_checklist(op, chk["id"], 5)
        submitted_version = chk["version"]
        resp = api.submit_checklist(chk["id"], {"items_passed": 5},
                                    make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECKLIST_INVALID_STATE, 409)
        after = fx.get_checklist(ctx["sup"], chk["id"])
        assert after["status"] == "SUBMITTED"
        assert after["version"] == submitted_version, (
            "a rejected submit must not advance the version")

    def test_duplicate_checklist_rejected(self, api):
        """PRD section 3.4: "One checklist per ride per day is allowed; a
        second is rejected with `ERR_DUPLICATE_CHECKLIST`".

        Design: Corner/errors/duplicate_checklist_and_incomplete_submit_errors
        """
        ctx = fx.setup_permitted_fair("ER1")
        fx.begin_day(ctx)
        op = ctx["op"]
        fx.open_checklist(op, ctx["ride"]["id"], ctx["day"]["id"], items_total=5)
        resp = api.create_checklist(
            {"ride_id": ctx["ride"]["id"], "operating_day_id": ctx["day"]["id"],
             "items_total": 5},
            make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CHECKLIST, 409)

    def test_incomplete_submit_rejected(self, api):
        """PRD section 3.4: "The performer reports `items_passed`, which must
        equal `items_total` — anything short is rejected with
        `ERR_CHECKLIST_INCOMPLETE`".

        Design: Corner/errors/duplicate_checklist_and_incomplete_submit_errors
        """
        ctx = fx.setup_permitted_fair("ER1b")
        fx.begin_day(ctx)
        op = ctx["op"]
        chk = fx.open_checklist(op, ctx["ride"]["id"], ctx["day"]["id"], items_total=5)
        resp = api.submit_checklist(chk["id"], {"items_passed": 4},
                                    make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECKLIST_INCOMPLETE, 422)
        after = fx.get_checklist(ctx["sup"], chk["id"])
        assert after["status"] == "DRAFT", "failed submit must leave the checklist DRAFT"
        assert after["version"] == chk["version"]


class TestChecklistCountersignSoD:
    def test_countersigner_same_as_performer_rejected(self, api):
        """PRD section 3.4: "the countersigner must not be the performer
        (`ERR_CHECKLIST_COUNTERSIGNER_CONFLICT`)".

        A dual-function staff member (OPERATOR + SUPERVISOR) legitimately
        holds both roles, but the same identity on both sides of the checklist
        still fails the segregation-of-duties check.

        Design: Corner/validations/checklist_countersigner_same_as_performer_rejected
        """
        fx.set_clock(fx.SETUP_DAY_ISO)
        fair = fx.create_fair(name="Midway V6")
        dual = fx.create_dual_role_supervisor(fair["id"], full_name="Dual V6")
        crew = fx.create_staff_via_manager(dual, "Crew V6", ["CREW"])
        fx.create_inspector("LIC-V6-1")
        insp2 = fx.create_inspector("LIC-V6-2")
        ride = fx.create_ride(dual, serial_number="SN-V6-1")
        fx.book_setup_shift(dual, crew)
        fx.verify_ride(crew, ride["id"])
        permit = fx.request_permit(dual)
        appt = fx.schedule_fair_wide(dual)
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        fx.complete_appointment(appt, outcome="PASS")
        fx.approve_permit(insp2, permit["id"], dual["fair_id"], dual)
        fx.certify_operator(dual["id"], ride_class="THRILL")
        ctx = {"sup": dual, "op": dual, "fair": fair}
        fx.begin_day(ctx)
        chk = fx.open_checklist(dual, ride["id"], ctx["day"]["id"], items_total=5)
        chk = fx.submit_checklist(dual, chk["id"], 5)
        resp = api.countersign_checklist(
            chk["id"], {"expected_checklist_version": chk["version"]},
            make_manager_headers(dual["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECKLIST_COUNTERSIGNER_CONFLICT, 422)
        after = fx.get_checklist(dual, chk["id"])
        assert after["status"] == "SUBMITTED", (
            "a rejected countersign must not move the checklist")


class TestOpenGatesCompoundGate:
    def test_open_gates_requires_every_licensed_ride_countersigned(self, api):
        """PRD section 3.4: "Opening is gated by a compound condition: every
        ride of the fair that is both `SETUP_VERIFIED` and `LICENSED` must hold
        a `COUNTERSIGNED` checklist for this day, else the opening is rejected
        with `ERR_RIDES_NOT_CLEARED`. Each such cleared ride's `daily_status`
        moves from `CLOSED` to `OPEN` with the gates."

        Design: Corner/state_machines/open_gates_compound_gate_requires_every_licensed_ride_countersigned
        """
        ctx = fx.setup_two_ride_permitted_fair("SM5", ride2_overrides={
            "name": "Tilt", "min_rider_height_in": 46, "max_rider_height_in": 82,
            "wind_limit_mph": 28, "cycle_inspection_interval": 4})
        sup = ctx["sup"]
        fx.begin_day(ctx)
        fx.clear_ride(ctx, ctx["ride1"]["id"])
        resp = api.open_gates(ctx["day"]["id"], {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_RIDES_NOT_CLEARED, 422)
        fx.clear_ride(ctx, ctx["ride2"]["id"])
        day = fx.open_gates(ctx)
        assert day["posture"] == "OPEN"
        for rid in (ctx["ride1"]["id"], ctx["ride2"]["id"]):
            ride = fx.get_ride(sup, rid)
            assert ride["daily_status"] == "OPEN", (
                f"ride {rid} must open with the gates, got {ride['daily_status']}")
