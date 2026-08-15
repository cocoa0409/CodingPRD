"""Validation rules: authentication, authorization, existence, SoD, temporal,
referential, fiscal, deadline protection, priority ordering.

Covers queue-B corner instances under `validations` and `roles`, plus queue-A
difficulty instances `priority_pair_validation_conflict/*`.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_case,
    create_and_approve_case,
    create_case_payload,
    create_revocation_task,
    create_asset_item,
    create_benefits_notice,
    set_clock,
    make_task_ready,
    execute_task,
    verify_task,
    calculate_statement,
    approve_statement,
    HR_INTAKE,
    HR_APPROVER,
    HR_REVIEWER,
    HR_DIRECTOR,
    PAYROLL_CALC,
    PAYROLL_APPROVER,
    IT_OP,
    IT_VER,
    IT_MGR,
    MGR,
    CLERK,
    BEN_ADMIN,
)


class TestAuthentication:
    def test_unauthenticated_missing_headers_401(self):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers_401
        """
        resp = api_client.list_cases(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_unauthenticated_unknown_role_401(self):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers_401
        """
        resp = api_client.list_cases(headers={"X-User-ID": "u1", "X-User-Role": "NotARole"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestAuthorization:
    def test_role_forbidden_on_exclusive_endpoint_manager_creates_task(self):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." Manager is not in the create-revocation-task role list
        (§4: ITManager only).

        Design: Corner/roles/role_forbidden_on_exclusive_endpoint
        """
        case = create_and_approve_case(employee_ref="E-R5")
        resp = api_client.create_revocation_task(
            {"offboarding_case_id": case["id"], "system_name": "EMAIL", "sequence_rank": 1},
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_role_forbidden_on_clock_endpoint_for_it_operator(self):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." `PlatformAdmin` "drives the logical clock and nothing
        else"; other roles have no clock access.

        Design: Corner/roles/role_forbidden_on_exclusive_endpoint
        """
        resp = api_client.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, IT_OP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


class TestExistencePrecedesState:
    def test_existence_precedes_state_left_to_right(self):
        """PRD §2.10: "Requests that address nested resources resolve path
        identifiers strictly left to right: the case first, then the child
        within that case. The request is rejected with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not resolve, and no later
        validation runs against a resource the path never reached."
        PRD §2.6: "Existence — every path-referenced resource resolves..."

        Design: Corner/validations/existence_precedes_state_left_to_right
        """
        resp = api_client.execute_revocation_task(
            NON_EXISTENT_UUID, {"outcome": "SUCCESS"}, IT_OP
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestTemporalSanity:
    def test_temporal_end_before_start_interview_422(self):
        """PRD §3.5: "an end that does not fall strictly after the start is
        rejected with `ERR_TEMPORAL_INVALID`."

        Design: Corner/validations/temporal_end_before_start_interview_422
        """
        case = create_and_approve_case(employee_ref="E-V1")
        resp = api_client.create_exit_interview(
            {
                "offboarding_case_id": case["id"],
                "interviewer_ref": "hr-int-1",
                "scheduled_start": "2026-08-05T11:00:00Z",
                "scheduled_end": "2026-08-05T10:00:00Z",
            },
            HR_INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_INVALID, expected_status=422)


class TestReferentialIntegrity:
    def test_duplicate_sequence_rank_rejected(self):
        """PRD §2.10: "Within a case, no two revocation tasks may share a
        `sequence_rank`... Violating any of these constraints is rejected with
        `ERR_REFERENTIAL_INTEGRITY`."

        Design: Corner/validations/duplicate_sequence_rank_rejected
        """
        case = create_and_approve_case(employee_ref="E-V2")
        create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        resp = api_client.create_revocation_task(
            {"offboarding_case_id": case["id"], "system_name": "VPN", "sequence_rank": 1},
            IT_MGR,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY, expected_status=422)

    def test_duplicate_asset_tag_rejected(self):
        """PRD §2.10: "no two asset items may share an `asset_tag`. Violating
        any of these constraints is rejected with `ERR_REFERENTIAL_INTEGRITY`."

        Design: Corner/validations/duplicate_asset_tag_rejected
        """
        case = create_and_approve_case(employee_ref="E-V3")
        create_asset_item(
            case["id"], asset_tag="A1", asset_kind="LAPTOP",
            replacement_cost_cents=1000, issued_date="2026-01-01T00:00:00Z",
        )
        resp = api_client.create_asset_item(
            {
                "offboarding_case_id": case["id"],
                "asset_tag": "A1",
                "asset_kind": "PHONE",
                "replacement_cost_cents": 2000,
                "issued_date": "2026-02-01T00:00:00Z",
            },
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY, expected_status=422)


class TestFiscalSanity:
    def test_fiscal_negative_wage_rejected(self):
        """PRD §2.8: "The `hourly_wage_cents` must be greater than zero... A
        violation is rejected with `ERR_FISCAL_INVALID` (HTTP 422)."

        Design: Corner/validations/fiscal_negative_wage_rejected
        """
        resp = api_client.create_case(
            create_case_payload(employee_ref="E-V4", work_state_code="TX",
                                hourly_wage_cents=-1),
            HR_INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_FISCAL_INVALID, expected_status=422)

    def test_fiscal_zero_wage_rejected(self):
        """PRD §2.8: "The `hourly_wage_cents` must be greater than zero... A
        violation is rejected with `ERR_FISCAL_INVALID` (HTTP 422)." Zero fails
        the strictly-greater-than-zero rule.

        Design: Corner/validations/fiscal_negative_wage_rejected
        """
        resp = api_client.create_case(
            create_case_payload(employee_ref="E-V4B", work_state_code="TX",
                                hourly_wage_cents=0),
            HR_INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_FISCAL_INVALID, expected_status=422)


class TestBenefitsDeadlineProtection:
    def test_benefits_send_after_deadline_rejected(self):
        """PRD §3.6: "attempting to send after the deadline is rejected with
        `ERR_DEADLINE_MISSED` (HTTP 422) — the notice must instead be requeued —
        and a notice still `QUEUED` when the clock passes `send_by` is marked
        `FAILED` by the scheduler with its `failure_count` incremented."

        After the clock passes send_by, the scheduler may have already flipped
        the notice to FAILED; in that case send is rejected for state reasons.

        Design: Corner/validations/benefits_send_after_deadline_rejected
        """
        case = create_and_approve_case(employee_ref="E-V5")
        notice = create_benefits_notice(case["id"], notice_kind="COBRA_ELECTION")
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task["id"], outcome="SUCCESS")
        verify_task(task["id"], outcome="VERIFIED")
        # Past send_by = 2026-09-23T17:00:00Z
        set_clock("2026-09-24T00:00:00Z")
        resp = api_client.send_benefits_notice(notice["id"], BEN_ADMIN)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_DEADLINE_MISSED, ApiErrorId.ERR_INVALID_STATE]
        )


class TestCloseRequiresFinalizedReview:
    def test_case_close_requires_finalized_rehire_review(self):
        """PRD §3.7: "An `HRPartner` closes a `READY_TO_CLOSE` case, but only
        when the rehire review is `FINALIZED` — closing without it is rejected
        with `ERR_DEADLINE_MISSED`."

        Design: Corner/validations/case_close_requires_finalized_rehire_review
        """
        # Drive case toward READY_TO_CLOSE but leave the rehire review DRAFT.
        case = create_and_approve_case(employee_ref="E-V6")
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task["id"], outcome="SUCCESS")
        verify_task(task["id"], outcome="VERIFIED")
        stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
        stmt = stmts[0]
        calculate_statement(stmt, regular_wages_cents=100000)
        approve_statement(stmt["id"])
        disb = validate_success(api_client.disburse_statement(stmt["id"], PAYROLL_CALC))
        assert disb["status"] in ("DISBURSED", "LATE")
        plans = get_success_data(api_client.list_case_kt_plans(case["id"], MGR))
        validate_success(api_client.waive_kt_plan(plans[0]["id"], {"waived_reason": "n/a"}, MGR))
        case_after = get_success_data(api_client.get_case(case["id"], HR_INTAKE))

        resp = api_client.close_case(
            case["id"],
            {"expected_offboarding_case_version": case_after["version"]},
            HR_APPROVER,
        )
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_DEADLINE_MISSED, ApiErrorId.ERR_INVALID_STATE]
        )


class TestSegregationOfDuties:
    def test_intake_approver_must_differ_from_recorder(self):
        """PRD §2.7: "SoD-1, intake approval. The HR partner approving a case
        must differ from the `intake_hr_ref` recorded when the case was
        created." A match is rejected with `ERR_SOD_VIOLATION` (HTTP 422).

        Design: Corner/roles/intake_approver_must_differ_from_recorder
        """
        case = create_case(employee_ref="E-R3", work_state_code="TX",
                           requested_last_day="2026-08-14T00:00:00Z")
        resp = api_client.approve_case(case["id"], HR_INTAKE)  # same X-User-ID as recorder
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=422)

    def test_it_operator_cannot_verify_own_execution(self):
        """PRD §2.7: "SoD-3, revocation verification. The verifier confirming
        an executed revocation must differ from the operator who executed it."
        PRD §3.2: "An `ITVerifier` reviews an `EXECUTED` task — never the same
        person who executed it, per SoD-3, with breaches rejected as
        `ERR_SOD_VIOLATION`."

        Design: Corner/roles/it_operator_cannot_verify_own_execution
        """
        case = create_and_approve_case(employee_ref="E-R1")
        task = make_task_ready(case["id"], system_name="EMAIL", sequence_rank=1)
        execute_task(task["id"], outcome="SUCCESS")
        # Verify with X-User-ID identical to executor's id ("it-op-1").
        same_user_as_verifier = {"X-User-ID": "it-op-1", "X-User-Role": "ITVerifier"}
        resp = api_client.verify_revocation_task(
            task["id"], {"outcome": "VERIFIED"}, same_user_as_verifier
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=422)

    def test_statement_approve_by_calculator_rejected(self):
        """PRD §2.7: "SoD-2, statement approval. The payroll specialist
        approving a final pay statement must differ from the `calc_by_ref`
        recorded when the statement was last calculated."
        PRD §3.3: "A `PayrollSpecialist` different from the recorded
        `calc_by_ref` approves a `CALCULATED` statement — SoD-2, with
        self-approval rejected as `ERR_SOD_VIOLATION`."

        Design: Corner/roles/statement_approve_by_calculator_rejected
        """
        case = create_and_approve_case(employee_ref="E-R2")
        stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
        stmt = stmts[0]
        calc = calculate_statement(stmt, regular_wages_cents=100000)
        # Approve with same X-User-ID as the calculator ("payroll-calc-1").
        resp = api_client.approve_statement(stmt["id"], PAYROLL_CALC)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=422)

    def test_statement_approve_by_different_specialist_succeeds(self):
        """PRD §3.3: "A `PayrollSpecialist` different from the recorded
        `calc_by_ref` approves a `CALCULATED` statement."

        Design: Corner/roles/statement_approve_by_calculator_rejected
        """
        case = create_and_approve_case(employee_ref="E-R2B")
        stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
        stmt = stmts[0]
        calculate_statement(stmt, regular_wages_cents=100000)
        approved = validate_success(api_client.approve_statement(stmt["id"], PAYROLL_APPROVER))
        assert approved["status"] == "APPROVED"

    def test_rehire_finalizer_must_differ_from_reviewer(self):
        """PRD §2.7: "SoD-4, rehire finalization. The HR director finalizing a
        rehire review must differ from the `reviewer_hr_ref` recorded on the
        review."

        Design: Corner/roles/rehire_finalizer_must_differ_from_reviewer
        """
        case = create_and_approve_case(employee_ref="E-R4")
        # Drive case to CLEARANCE_IN_PROGRESS so submit is legal.
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task["id"], outcome="SUCCESS")
        verify_task(task["id"], outcome="VERIFIED")
        stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
        stmt = stmts[0]
        calculate_statement(stmt, regular_wages_cents=100000)
        approve_statement(stmt["id"])

        reviews = get_success_data(api_client.list_case_rehire_reviews(case["id"], HR_REVIEWER))
        review = reviews[0]
        validate_success(api_client.submit_rehire_review(
            review["id"],
            {"recommended_code": "ELIGIBLE", "rationale": "ok"},
            HR_REVIEWER,
        ))
        # Finalize with X-User-ID equal to reviewer_hr_ref ("hr-reviewer-1").
        same_user_as_director = {"X-User-ID": "hr-reviewer-1", "X-User-Role": "HRDirector"}
        resp = api_client.finalize_rehire_review(review["id"], same_user_as_director)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=422)


class TestPriorityPairConflict:
    def test_state_vs_sod_on_case_approve(self):
        """PRD §2.6: "When several rules could reject the same request, the
        server evaluates them in a fixed priority order so that the returned
        error is deterministic. The order is: ... 4. State legality ... 5.
        Segregation of duties ...". Approving an already-APPROVED case with the
        same user as the intake recorder violates both; state beats SoD.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_sod_on_case_approve
        """
        case = create_and_approve_case(employee_ref="E-P1", work_state_code="TX",
                                       requested_last_day="2026-08-14T00:00:00Z")
        # Second approve: same user as intake recorder (SoD breach) AND state no
        # longer INTAKE (state breach). Priority 4 (state) wins.
        resp = api_client.approve_case(case["id"], HR_INTAKE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_state_vs_sod_state_fires_for_legitimate_second_attempt(self):
        """PRD §2.6 priority order means that even a *different* HR partner
        re-approving an APPROVED case sees ERR_INVALID_STATE — the state gate
        fires regardless of identity, and is never shadowed by SoD.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_sod_on_case_approve
        """
        case = create_and_approve_case(employee_ref="E-P1B", work_state_code="TX",
                                       requested_last_day="2026-08-14T00:00:00Z")
        # A third HR partner (never the recorder, so SoD would pass in isolation)
        resp = api_client.approve_case(
            case["id"], {"X-User-ID": "hr-third-1", "X-User-Role": "HRPartner"}
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_temporal_vs_fiscal_on_case_create(self):
        """PRD §2.6: "6. Temporal sanity — dates and windows are internally
        coherent; otherwise `ERR_TEMPORAL_INVALID` (HTTP 422). ... 11. Fiscal
        sanity — wage, balance, cost, and wage inputs are in range; otherwise
        `ERR_FISCAL_INVALID` (HTTP 422)." A create that violates both surfaces
        the temporal error.

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_on_case_create
        """
        resp = api_client.create_case(
            create_case_payload(
                employee_ref="E-P2",
                case_type="RESIGNATION",
                work_state_code="TX",
                notice_received_date="2026-08-10T00:00:00Z",
                requested_last_day="2026-08-05T00:00:00Z",  # before notice -> temporal
                hourly_wage_cents=0,                         # -> fiscal
            ),
            HR_INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_INVALID, expected_status=422)

    def test_temporal_alone_on_case_create(self):
        """PRD §3.1: "A requested last day earlier than the notice date is
        rejected with `ERR_TEMPORAL_INVALID` — both at creation and again at
        approval."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_on_case_create
        """
        resp = api_client.create_case(
            create_case_payload(
                employee_ref="E-P2B",
                work_state_code="TX",
                notice_received_date="2026-08-10T00:00:00Z",
                requested_last_day="2026-08-05T00:00:00Z",
                # hourly_wage_cents stays valid
            ),
            HR_INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_INVALID, expected_status=422)


