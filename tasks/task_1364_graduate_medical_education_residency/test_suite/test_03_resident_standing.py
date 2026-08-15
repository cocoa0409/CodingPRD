"""Resident enrollment, the parallel lifecycle/standing dimensions, graduation
terminal lockdown, fiscal-gate precedence, and the remediation/probation
instruments that drive standing (PRD §3.3, §3.8)."""
from test_helpers import (
    PC, PD, ApiClient, ApiErrorId, approx2,
    complete_remediation_plan, create_resident_payload, list_probation_cases,
    make_active_resident, make_active_year, make_complement, make_dio_headers,
    make_pd_headers, make_probation_case, make_program, make_remediation_plan,
    make_resident, make_year, setup_graduated_resident,
    setup_program_with_active_resident, validate_error, validate_paginated,
    validate_success,
)


def _resident(api, res_id):
    return validate_success(api.get_resident(res_id, PD))


class TestParallelDimensions:
    def test_lifecycle_moves_while_standing_holds(self, api: ApiClient):
        """PRD §3.3: "The two evolve independently: a resident can be `ACTIVE`
        and `ON_PROBATION` at once."
        PRD §3.8: "A resident's `standing_status` is never set directly; it is
        re-derived after every creation, completion, cancellation, lifting,
        recommendation, or confirmation touching the resident's remediation
        plans and probation cases."

        Design: Difficulty/non_linear_state_machine/resident_lifecycle_and_standing_parallel_dimensions
        """
        s = setup_program_with_active_resident(approved_positions=4)
        resident = s["resident"]

        make_remediation_plan(resident["id"], goals="Improve sign-out documentation")
        r = _resident(api, resident["id"])
        assert (r["lifecycle_status"], r["standing_status"]) == (
            "ACTIVE", "UNDER_REMEDIATION")

        r = validate_success(api.place_on_leave(resident["id"], PD))
        assert (r["lifecycle_status"], r["standing_status"]) == (
            "ON_LEAVE", "UNDER_REMEDIATION")

        r = validate_success(api.return_from_leave(resident["id"], PD))
        assert (r["lifecycle_status"], r["standing_status"]) == (
            "ACTIVE", "UNDER_REMEDIATION")

    def test_probation_lift_lands_back_on_active_remediation(self, api: ApiClient):
        """PRD §3.8: "The derivation is a strict priority: `ON_PROBATION` when
        any probation case of the resident is `ACTIVE` or
        `DISMISSAL_RECOMMENDED`; otherwise `UNDER_REMEDIATION` when any
        remediation plan of the resident is `ACTIVE`; otherwise
        `GOOD_STANDING`."
        PRD §3.8: "Lifting a case requires `ACTIVE` (otherwise
        `ERR_PROBATION_NOT_ACTIVE`, HTTP 409), moves it to `LIFTED`, and
        recomputes standing — the resident reaches `GOOD_STANDING` only when no
        remediation plan is `ACTIVE` and no other probation case is open."

        Design: Difficulty/non_linear_state_machine/resident_lifecycle_and_standing_parallel_dimensions
        """
        s = setup_program_with_active_resident(approved_positions=4)
        resident = s["resident"]
        plan = make_remediation_plan(resident["id"])
        case = make_probation_case(resident["id"])
        assert _resident(api, resident["id"])["standing_status"] == "ON_PROBATION"

        validate_success(api.lift_probation_case(case["id"], PD))
        r = _resident(api, resident["id"])
        # The still-ACTIVE remediation plan wins the recompute.
        assert r["standing_status"] == "UNDER_REMEDIATION"
        assert r["lifecycle_status"] == "ACTIVE"

        complete_remediation_plan(plan["id"], "SUCCESS")
        r = _resident(api, resident["id"])
        assert (r["lifecycle_status"], r["standing_status"]) == (
            "ACTIVE", "GOOD_STANDING")


class TestActivationPrecedence:
    def _setup(self, api):
        program = make_program()
        year = make_active_year(program["id"])
        make_complement(program["id"], year["id"], approved_positions=2)
        make_active_resident(program["id"], year["id"], full_name="A One")
        res_b = make_active_resident(program["id"], year["id"], full_name="B Two")
        validate_success(api.place_on_leave(res_b["id"], PD))
        return program, year, res_b

    def test_state_error_beats_fiscal_error(self, api: ApiClient):
        """PRD §3.3: "Then — and only after every other validation stage has
        passed, per the pipeline of §2.8 — the two fiscal gates run against the
        matching complement row."
        PRD §3.3: "The resident must be `INCOMING` (otherwise
        `ERR_RESIDENT_NOT_INCOMING`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/activate_state_error_beats_fiscal_error
        """
        program, year, res_b = self._setup(api)
        # B is ON_LEAVE (state violation) AND headcount is full at 2 (fiscal
        # violation): the state error must win.
        resp = api.activate_resident(res_b["id"], PC)
        validate_error(resp, ApiErrorId.ERR_RESIDENT_NOT_INCOMING)
        assert resp.status_code == 409
        r = _resident(api, res_b["id"])
        assert r["lifecycle_status"] == "ON_LEAVE"

    def test_fiscal_gate_reaches_when_state_passes(self, api: ApiClient):
        """PRD §3.3: "The headcount gate: the row's `filled_headcount` plus 1
        must not exceed `approved_positions`; a breach is
        `ERR_COMPLEMENT_EXCEEDED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/activate_state_error_beats_fiscal_error
        """
        program, year, _ = self._setup(api)
        # A fresh INCOMING resident fails purely on the fiscal headcount gate.
        res_c = make_resident(program["id"], year["id"], full_name="C Three")
        resp = api.activate_resident(res_c["id"], PC)
        validate_error(resp, ApiErrorId.ERR_COMPLEMENT_EXCEEDED)
        assert _resident(api, res_c["id"])["lifecycle_status"] == "INCOMING"


class TestEnrollment:
    def test_missing_required_email_rejected(self, api: ApiClient):
        """PRD §2.8: "For endpoints with a request body: all required input
        fields are present, types match, and enum values fall within their
        declared sets (specialty, moonlighting type, case-log role, outcome,
        competency codes, and so on); otherwise `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/resident_create_missing_required_email
        """
        program = make_program()
        year = make_year(program["id"])
        make_complement(program["id"], year["id"])
        payload = create_resident_payload(program["id"], year["id"])
        del payload["email"]
        resp = api.create_resident(payload, PC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400
        _, meta = validate_paginated(
            api.list_residents(PC, params={"program_id": program["id"]}))
        assert meta["total_count"] == 0

    def test_submitted_complement_does_not_satisfy_enrollment(self, api: ApiClient):
        """PRD §3.3: "an `APPROVED` or `LOCKED` complement row must already
        exist for the (program, entry year, PGY level) triple, otherwise
        creation is rejected with `ERR_NO_APPROVED_COMPLEMENT` (HTTP 409)."

        Design: Corner/entities/resident_create_without_approved_complement_rejected
        """
        program = make_program()
        year = make_year(program["id"])
        comp = make_complement(program["id"], year["id"], approve=False)
        validate_success(api.submit_complement(comp["id"], PD))
        resp = api.create_resident(
            create_resident_payload(program["id"], year["id"]), PC)
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_COMPLEMENT)
        assert resp.status_code == 409


class TestGraduatedTerminalLockdown:
    def test_graduated_resident_accepts_no_transitions(self, api: ApiClient):
        """PRD §3.3: "Transfer, also a director action, moves a resident from
        `ACTIVE` or `ON_LEAVE` to `TRANSFERRED` — a resident in any other
        lifecycle state fails with `ERR_RESIDENT_NOT_ACTIVE` — and likewise
        recomputes the fill figures."
        PRD §3.3: "Graduation is the `ProgramDirector`'s certification that
        training is complete, and it is gated on four conditions: the resident
        is `ACTIVE` (`ERR_RESIDENT_NOT_ACTIVE`); their `standing_status` is
        `GOOD_STANDING` (`ERR_STANDING_NOT_CLEAR`, HTTP 409); every case
        requirement of the program evaluates to met for this resident
        (`ERR_CASE_REQUIREMENTS_UNMET`, HTTP 409; the requirement math lives in
        §3.7); and at least one CCC review for the resident has reached
        `FINALIZED` (`ERR_NO_FINALIZED_CCC_REVIEW`, HTTP 409).".

        Design: Corner/state_machines/graduated_resident_terminal_lockdown
        """
        s = setup_graduated_resident()
        resident = s["resident"]
        assert resident["lifecycle_status"] == "GRADUATED"

        resp = api.place_on_leave(resident["id"], PD)
        validate_error(resp, ApiErrorId.ERR_RESIDENT_NOT_ACTIVE)
        resp = api.transfer_resident(resident["id"], PD)
        validate_error(resp, ApiErrorId.ERR_RESIDENT_NOT_ACTIVE)
        resp = api.graduate_resident(resident["id"], PD)
        validate_error(resp, ApiErrorId.ERR_RESIDENT_NOT_ACTIVE)
        assert _resident(api, resident["id"])["lifecycle_status"] == "GRADUATED"


class TestResidentListFilters:
    def test_filters_compose(self, api: ApiClient):
        """PRD §3.3: "The resident list may be filtered by `program_id`,
        `entry_academic_year_id`, `lifecycle_status`, and `standing_status`."

        Design: Corner/endpoints/resident_list_filters_combine
        """
        program = make_program()
        year = make_active_year(program["id"])
        make_complement(program["id"], year["id"], approved_positions=3)
        make_active_resident(program["id"], year["id"], full_name="A One")
        res_b = make_active_resident(program["id"], year["id"], full_name="B Two")
        validate_success(api.place_on_leave(res_b["id"], PD))
        make_remediation_plan(res_b["id"], goals="Chart review")

        data, meta = validate_paginated(api.list_residents(PD, params={
            "program_id": program["id"], "lifecycle_status": "ON_LEAVE",
            "standing_status": "UNDER_REMEDIATION"}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == res_b["id"]

        _, meta = validate_paginated(api.list_residents(PD, params={
            "program_id": program["id"], "lifecycle_status": "ACTIVE"}))
        assert meta["total_count"] == 1

        _, meta = validate_paginated(api.list_residents(PD, params={
            "program_id": program["id"]}))
        assert meta["total_count"] == 2


class TestRemediationProbation:
    def test_failure_escalates_to_probation(self, api: ApiClient):
        """PRD §3.8: "Failure moves the plan to `COMPLETED_FAILURE` and
        escalates: unless a probation case is already open for the resident,
        one is created with the `remediation_plan_id` set, the reason
        "Remediation plan failure", and status `ACTIVE`, driving the standing
        to `ON_PROBATION` and running the moonlighting sweep."

        Design: Corner/state_machines/remediation_failure_escalates_to_probation
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        plan = make_remediation_plan(resident["id"], goals="Improve documentation")

        completed = complete_remediation_plan(plan["id"], "FAILURE")
        assert completed["status"] == "COMPLETED_FAILURE"

        cases, meta = list_probation_cases(
            resident_id=resident["id"], remediation_plan_id=plan["id"])
        assert meta["total_count"] == 1
        assert cases[0]["status"] == "ACTIVE"
        assert cases[0]["reason"] == "Remediation plan failure"
        assert cases[0]["remediation_plan_id"] == plan["id"]
        assert _resident(api, resident["id"])["standing_status"] == "ON_PROBATION"

    def test_probation_lift_is_not_replayable(self, api: ApiClient):
        """PRD §3.8: "Lifting a case requires `ACTIVE` (otherwise
        `ERR_PROBATION_NOT_ACTIVE`, HTTP 409), moves it to `LIFTED`, and
        recomputes standing — the resident reaches `GOOD_STANDING` only when no
        remediation plan is `ACTIVE` and no other probation case is open."

        Design: Corner/state_machines/probation_lift_twice_rejected
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        case = make_probation_case(resident["id"])

        lifted = validate_success(api.lift_probation_case(case["id"], PD))
        assert lifted["status"] == "LIFTED"

        resp = api.lift_probation_case(case["id"], PD)
        validate_error(resp, ApiErrorId.ERR_PROBATION_NOT_ACTIVE)
        assert validate_success(api.get_probation_case(case["id"], PD))[
            "status"] == "LIFTED"
        # The first lift's standing recompute ran exactly once.
        assert _resident(api, resident["id"])["standing_status"] == "GOOD_STANDING"


class TestDismissalSegregationOfDuties:
    def test_recommender_cannot_confirm_own_dismissal(self, api: ApiClient):
        """PRD §3.8: "the confirming `X-User-ID` must differ from the recorded
        `recommended_by`; the same operator attempting to confirm their own
        recommendation is rejected with `ERR_DISMISSAL_CONFIRMATION_CONFLICT`
        (HTTP 403). On confirmation the case moves to its terminal `DISMISSED`
        state, and the cascade lands on the resident: `lifecycle_status` moves
        from `ACTIVE` or `ON_LEAVE` to `DISMISSED`, and the complement fill
        figures are recomputed."

        Design: Corner/rbac/sod_dismissal_recommender_cannot_confirm
        """
        s = setup_program_with_active_resident()
        resident, comp = s["resident"], s["complement"]
        case = make_probation_case(resident["id"],
                                   reason="Patient safety incident",
                                   user_id="pd-1")
        recommended = validate_success(
            api.recommend_dismissal(case["id"], make_pd_headers("pd-1")))
        assert recommended["status"] == "DISMISSAL_RECOMMENDED"
        assert recommended["recommended_by"] == "pd-1"

        # Same operator id (different role) attempts to confirm: conflict.
        resp = api.confirm_dismissal(case["id"], make_dio_headers("pd-1"))
        validate_error(resp, ApiErrorId.ERR_DISMISSAL_CONFIRMATION_CONFLICT)
        assert resp.status_code == 403
        assert validate_success(api.get_probation_case(case["id"], PD))[
            "status"] == "DISMISSAL_RECOMMENDED"

        confirmed = validate_success(
            api.confirm_dismissal(case["id"], make_dio_headers("dio-9")))
        assert confirmed["status"] == "DISMISSED"
        assert _resident(api, resident["id"])["lifecycle_status"] == "DISMISSED"
        row = validate_success(api.get_complement(comp["id"], PD))
        assert row["filled_headcount"] == 0
        assert row["filled_funded_census"] == approx2(0.0)
