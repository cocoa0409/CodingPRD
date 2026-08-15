"""Cross-cutting error matrices: auth envelope guard, rotation retire guards,
assignment/log/CCC invalid-from transitions, remediation/probation state
errors, and the uniqueness family (PRD §2.8, §3)."""
from test_helpers import (
    DIO, PC, PD, ApiClient, ApiErrorId, anonymous_headers,
    close_survey_payload, complete_remediation_plan,
    create_assignment_payload, create_case_requirement_payload,
    create_ccc_review_payload, create_survey_payload, finalize_ccc_payload,
    get_block, make_assignment, make_attested_log, make_ccc_chair_headers,
    make_ccc_review, make_probation_case, make_program, make_remediation_plan,
    make_rotation, make_survey, resident_headers,
    setup_program_with_active_resident, validate_error, validate_success,
)


class TestAuthEnvelopeGuard:
    def test_missing_headers_rejected_400(self, api: ApiClient):
        """PRD §2.1: "A request missing either header, or presenting an
        `X-User-Role` value outside this declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.8: "Every request is validated against an ordered pipeline, and
        the first failure wins" — user context is stage 1 and "applies to all
        endpoints".

        Design: Corner/errors/missing_auth_header_returns_400
        """
        program = make_program()
        resp = api.get_program(program["id"], anonymous_headers())
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400


class TestRotationRetireGuards:
    def test_retire_guards_and_survey_rate_bounds(self, api: ApiClient):
        """PRD §3.4: "Retiring a rotation likewise requires `ACTIVE` (same
        error) and is additionally barred while any assignment referencing the
        rotation is `PLANNED` or `CONFIRMED`, surfacing
        `ERR_ROTATION_HAS_OPEN_ASSIGNMENTS` (HTTP 409); retirement moves the
        rotation to its terminal `RETIRED` state."
        PRD §3.4: "The rotation must be `ACTIVE` (`ERR_ROTATION_NOT_ACTIVE`)."
        PRD §3.9: "any value outside its range is rejected with
        `ERR_INVALID_SURVEY_RATE` (HTTP 422)".

        Design: Corner/errors/rotation_retire_guards_and_survey_enum_errors
        """
        s = setup_program_with_active_resident()
        program, year, resident = s["program"], s["year"], s["resident"]
        rotation = make_rotation(program["id"], name="Wards")
        block = get_block(year["id"], 1)
        asg = make_assignment(resident["id"], block["id"], rotation["id"])
        survey = make_survey(program["id"], year["id"])

        resp = api.retire_rotation(rotation["id"], PC)
        validate_error(resp, ApiErrorId.ERR_ROTATION_HAS_OPEN_ASSIGNMENTS)

        validate_success(api.cancel_assignment(asg["id"], PC))
        retired = validate_success(api.retire_rotation(rotation["id"], PC))
        assert retired["status"] == "RETIRED"

        resp = api.retire_rotation(rotation["id"], PC)
        validate_error(resp, ApiErrorId.ERR_ROTATION_NOT_ACTIVE)
        resp = api.create_assignment(
            create_assignment_payload(resident["id"], block["id"],
                                      rotation["id"]), PC)
        validate_error(resp, ApiErrorId.ERR_ROTATION_NOT_ACTIVE)

        resp = api.close_survey(
            survey["id"],
            close_survey_payload(resident_response_rate=100.01,
                                 faculty_response_rate=90.00, area_results=[]),
            DIO)
        validate_error(resp, ApiErrorId.ERR_INVALID_SURVEY_RATE)
        assert resp.status_code == 422
        assert validate_success(api.get_survey(survey["id"], DIO))[
            "status"] == "OPEN"


class TestAssignmentLogCccInvalidTransitions:
    def test_invalid_from_matrix(self, api: ApiClient):
        """PRD §3.4: "Confirming requires `PLANNED` (otherwise
        `ERR_ASSIGNMENT_NOT_PLANNED`, HTTP 409)"; "Completing requires
        `CONFIRMED` (otherwise `ERR_ASSIGNMENT_NOT_CONFIRMED`, HTTP 409)";
        "Cancelling is permitted from either `PLANNED` or `CONFIRMED`
        (otherwise `ERR_ASSIGNMENT_NOT_CANCELLABLE`, HTTP 409)".
        PRD §3.5: "Attesting requires the log to be `SUBMITTED` (otherwise
        `ERR_LOG_NOT_SUBMITTED`, HTTP 409)".
        PRD §3.7: "Beginning deliberation requires `OPEN` (otherwise
        `ERR_CCC_NOT_OPEN`, HTTP 409)"; "Finalization requires
        `IN_DELIBERATION` (same `ERR_CCC_NOT_IN_DELIBERATION`)".

        Design: Corner/errors/assignment_and_log_invalid_transition_errors
        """
        s = setup_program_with_active_resident()
        resident, year = s["resident"], s["year"]
        rotation = make_rotation(s["program"]["id"], name="Wards")
        block = get_block(year["id"], 1)
        asg = make_assignment(resident["id"], block["id"], rotation["id"])
        log = make_attested_log(resident, "2026-08-03T00:00:00Z",
                                "2026-08-03T08:00:00Z")
        review = make_ccc_review(resident, year, chair_id="chair-1")
        chair = make_ccc_chair_headers("chair-1")

        resp = api.complete_assignment(asg["id"], PC)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_CONFIRMED)
        validate_success(api.confirm_assignment(asg["id"], PC))
        resp = api.confirm_assignment(asg["id"], PC)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_PLANNED)
        completed = validate_success(api.complete_assignment(asg["id"], PC))
        assert completed["status"] == "COMPLETED"
        resp = api.cancel_assignment(asg["id"], PC)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE)

        resp = api.attest_duty_log(log["id"], resident_headers(resident))
        validate_error(resp, ApiErrorId.ERR_LOG_NOT_SUBMITTED)

        # finalize from OPEN: the state gate fires before any quorum check.
        resp = api.finalize_ccc_review(
            review["id"], finalize_ccc_payload("SATISFACTORY"), chair)
        validate_error(resp, ApiErrorId.ERR_CCC_NOT_IN_DELIBERATION)
        validate_success(api.begin_deliberation(review["id"], chair))
        resp = api.begin_deliberation(review["id"], chair)
        validate_error(resp, ApiErrorId.ERR_CCC_NOT_OPEN)

        # Each error left state untouched.
        assert validate_success(api.get_assignment(asg["id"], PC))[
            "status"] == "COMPLETED"
        assert validate_success(api.get_duty_log(log["id"], PD))[
            "status"] == "ATTESTED"
        assert validate_success(api.get_ccc_review(review["id"], PD))[
            "status"] == "IN_DELIBERATION"


class TestRemediationProbationStateErrors:
    def test_terminal_and_missing_state_errors(self, api: ApiClient):
        """PRD §3.8: "Completing a plan requires it to be `ACTIVE` (otherwise
        `ERR_REMEDIATION_NOT_ACTIVE`, HTTP 409)" and "Cancelling a plan —
        again requiring `ACTIVE` (`ERR_REMEDIATION_NOT_ACTIVE`)".
        PRD §3.8: "The `DesignatedInstitutionalOfficial` confirms dismissal on
        a case in `DISMISSAL_RECOMMENDED` (otherwise
        `ERR_PROBATION_NOT_RECOMMENDED`, HTTP 409)".

        Design: Corner/errors/remediation_probation_and_outcome_enum_errors
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        plan = make_remediation_plan(resident["id"], goals="Chart review")
        complete_remediation_plan(plan["id"], "SUCCESS")
        case = make_probation_case(resident["id"], reason="Later incident")

        resp = api.complete_remediation_plan(plan["id"], {"outcome": "SUCCESS"},
                                             PD)
        validate_error(resp, ApiErrorId.ERR_REMEDIATION_NOT_ACTIVE)
        resp = api.confirm_dismissal(case["id"], DIO)
        validate_error(resp, ApiErrorId.ERR_PROBATION_NOT_RECOMMENDED)
        resp = api.cancel_remediation_plan(plan["id"],
                                           {"cancel_reason": "moot"}, PD)
        validate_error(resp, ApiErrorId.ERR_REMEDIATION_NOT_ACTIVE)

        assert validate_success(api.get_probation_case(case["id"], PD))[
            "status"] == "ACTIVE"
        assert validate_success(api.get_resident(resident["id"], PD))[
            "standing_status"] == "ON_PROBATION"


class TestUniquenessConstraints:
    def test_uniqueness_family(self, api: ApiClient):
        """PRD §3.7: "a non-`FINALIZED` review already existing for the triple
        is rejected with `ERR_CCC_REVIEW_EXISTS` (HTTP 409)".
        PRD §3.7: "a case requirement names the `program_id` and
        `procedure_category` — unique per program, with a duplicate rejected as
        `ERR_REQUIREMENT_EXISTS` (HTTP 409)".
        PRD §3.9: "one survey per program per year, with a duplicate rejected
        as `ERR_SURVEY_EXISTS` (HTTP 409)".
        PRD §3.2: "no other complement row for the same (program, academic
        year, PGY level) triple may already be `APPROVED` or `LOCKED`,
        otherwise `ERR_COMPLEMENT_ALREADY_APPROVED` (HTTP 409)".
        PRD §3.8: "only one open case — one in `ACTIVE` or
        `DISMISSAL_RECOMMENDED` — may exist per resident, with a second attempt
        rejected as `ERR_OPEN_PROBATION_EXISTS` (HTTP 409)."

        Design: Corner/validations/uniqueness_constraint_violations
        """
        s = setup_program_with_active_resident()
        program, year, resident = s["program"], s["year"], s["resident"]
        make_ccc_review(resident, year, chair_id="chair-1")
        validate_success(api.create_case_requirement(
            create_case_requirement_payload(program["id"]), PD),
            expected_status=201)
        make_survey(program["id"], year["id"])
        comp2 = validate_success(api.create_complement(
            {"program_id": program["id"], "academic_year_id": year["id"],
             "pgy_level": 1, "approved_positions": 5,
             "annual_funding_budget_cents": 100000000,
             "blended_stipend_cents": 6000000}, PD), expected_status=201)
        validate_success(api.submit_complement(comp2["id"], PD))
        make_probation_case(resident["id"], reason="Unprofessional conduct")

        # Second open CCC review for the same (resident, year, period).
        resp = api.create_ccc_review(
            create_ccc_review_payload(resident["id"], year["id"]),
            make_ccc_chair_headers("chair-1"))
        validate_error(resp, ApiErrorId.ERR_CCC_REVIEW_EXISTS)

        # Second MAJOR_SURGERY requirement for the same program.
        resp = api.create_case_requirement(
            create_case_requirement_payload(program["id"], required_count=5,
                                            required_primary_count=3), PD)
        validate_error(resp, ApiErrorId.ERR_REQUIREMENT_EXISTS)

        # Second survey for the same (program, year).
        resp = api.create_survey(create_survey_payload(program["id"],
                                                       year["id"]), PC)
        validate_error(resp, ApiErrorId.ERR_SURVEY_EXISTS)

        # Approving the second row while the first is APPROVED for the triple.
        resp = api.approve_complement(comp2["id"], DIO)
        validate_error(resp, ApiErrorId.ERR_COMPLEMENT_ALREADY_APPROVED)

        # Second open probation case for the same resident.
        resp = api.create_probation_case(
            {"resident_id": resident["id"], "reason": "Second case"}, PD)
        validate_error(resp, ApiErrorId.ERR_OPEN_PROBATION_EXISTS)
