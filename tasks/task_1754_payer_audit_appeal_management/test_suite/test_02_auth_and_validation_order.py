"""Auth header enforcement, RBAC entry checks, request validation tiers, and
the fixed validation priority order when several checks fail at once."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    begin_payer_review,
    create_audit_case,
    create_audit_case_payload,
    create_payer,
    create_payer_payload,
    create_issue_code,
    denied_outcome,
    get_case,
    make_auditor_headers,
    make_payer_agent_headers,
    open_appeal,
    setup_cap_in_check,
    setup_cross_payer_offset_scenario,
    setup_determined_case,
    submit_records,
    add_claim_line,
    advance_clock,
    validate_error,
    withdraw_appeal,
    create_remittance,
    manual_offset_payload,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
HIM = TEST_USERS["him_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestAuthHeaders:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request in which either header is missing or malformed
        is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.create_payer(create_payer_payload(name="P1"), {})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_forbidden_role_create_payer(self, api, him_headers):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/validations/forbidden_role_create_payer
        """
        resp = api.create_payer(create_payer_payload(name="P1"), him_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestCaseIntakeValidation:
    def test_case_create_missing_payer_id_rejected(self, api, him_headers):
        """PRD §2.9: "Request-body well-formedness — required fields present,
        enums valid, amounts positive, and `service_end_date` after
        `service_start_date` on claim lines — else `ERR_INVALID_REQUEST`
        (400)."

        Design: Corner/validations/case_create_missing_required_payer_id
        """
        resp = api.create_audit_case(
            {"audit_type": "RAC_COMPLEX", "received_at": "2026-08-01T00:00:00Z"},
            him_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_case_create_unknown_payer_not_found(self, api, him_headers):
        """PRD §3.2: "Intake is guarded in the order of §2.9: the payer must
        exist (`ERR_NOT_FOUND`), the payer must be `ACTIVE` (else
        `ERR_PAYER_SUSPENDED`)"

        Design: Corner/validations/case_create_unknown_payer_not_found
        """
        resp = api.create_audit_case(
            create_audit_case_payload(NON_EXISTENT_UUID), him_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAnalyticsWindow:
    def test_inverted_window_rejected(self, api, reader_headers):
        """PRD §2.9: "Analytics window sanity, evaluated only on the
        success-rate analytics read, immediately after body well-formedness and
        before existence — a window whose `from` is not before its `to` returns
        `ERR_ANALYTICS_WINDOW_INVALID` (422)."

        Design: Corner/validations/analytics_window_inverted_rejected
        """
        resp = api.get_success_rates(reader_headers, params={
            "from": "2026-09-01T00:00:00Z", "to": "2026-08-01T00:00:00Z"})
        validate_error(resp, ApiErrorId.ERR_ANALYTICS_WINDOW_INVALID)


class TestPayerAgentOwnership:
    def test_payer_agent_cannot_intake_audit_case(self, api):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.2: "An audit case begins when a `HIMCoordinator` — or a
        `RevenueCycleAdmin` — intakes a payer's audit request"

        Design: Corner/rbac/payer_agent_cannot_create_case
        """
        payer = create_payer(name="P1")
        resp = api.create_audit_case(
            create_audit_case_payload(payer["id"]),
            make_payer_agent_headers(payer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_payer_agent_matching_payer_drives_review(self, api):
        """PRD §2.1: "a `PayerAgent` caller must be acting on behalf of the
        payer that owns the target: the case's `payer_id` when beginning review
        or posting a determination"

        Design: Corner/rbac/payer_agent_ownership_positive
        """
        payer = create_payer(name="P1")
        case = create_audit_case(payer["id"])
        add_claim_line(case["id"])
        submit_records(case["id"])
        updated = begin_payer_review(case["id"], payer["id"])
        assert updated["status"] == "UNDER_PAYER_REVIEW"

    def test_payer_mismatch_on_determination_rejected(self, api):
        """PRD §2.1: "Any mismatch is rejected with `ERR_PAYER_MISMATCH`
        (HTTP 403)."

        Design: Corner/validations/payer_mismatch_determination_rejected
        """
        payer_a = create_payer(name="PA", payer_type="RAC")
        payer_b = create_payer(name="PB", payer_type="COMMERCIAL")
        case = create_audit_case(payer_a["id"])
        line = add_claim_line(case["id"])
        submit_records(case["id"])
        begin_payer_review(case["id"], payer_a["id"])

        issue = create_issue_code("MED_NEC", "CLINICAL", "Medical necessity")
        resp = api.post_determination(
            case["id"],
            {"outcomes": [denied_outcome(line["id"], 100000, issue["id"],
                                         "CLINICAL")]},
            make_payer_agent_headers(payer_b["id"]))
        validate_error(resp, ApiErrorId.ERR_PAYER_MISMATCH)
        assert get_case(case["id"])["status"] == "UNDER_PAYER_REVIEW"


class TestValidationPriorityOnAppealFile:
    def test_withdrawn_appeal_file_reports_state_error_not_temporal(self, api):
        """PRD §2.9: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the earliest
        failing tier determines the error returned"
        PRD §2.9: "State guards — the target must be in a state that permits
        the requested transition, else `ERR_INVALID_STATE_TRANSITION` (409)"
        PRD §2.9: "Temporal checks — appeal filing deadlines and the
        corrective-plan effectiveness window — else
        `ERR_APPEAL_DEADLINE_PASSED` (409) or `ERR_CAP_WINDOW_NOT_ELAPSED`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_withdrawn_appeal_file
        """
        ctx = setup_determined_case(billed_amounts=(100000,),
                                    issue_code="MED_NEC",
                                    issue_category="CLINICAL",
                                    issue_description="Medical necessity")
        appeal = open_appeal(ctx["lines"][0]["id"])
        withdraw_appeal(appeal["id"])
        advance_clock("2026-09-01T00:00:00Z")
        resp = api.file_appeal(appeal["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_draft_appeal_file_past_deadline_reports_temporal_error(self, api):
        """PRD §3.4: "When the clock has passed `filed_deadline_at`, the filing
        attempt is rejected with `ERR_APPEAL_DEADLINE_PASSED` (HTTP 409) — and
        the attempt itself moves the appeal `DRAFT → EXPIRED`."
        PRD §2.9: "the earliest failing tier determines the error returned"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_withdrawn_appeal_file
        """
        ctx = setup_determined_case(billed_amounts=(100000,),
                                    issue_code="MED_NEC",
                                    issue_category="CLINICAL",
                                    issue_description="Medical necessity")
        appeal = open_appeal(ctx["lines"][0]["id"])
        advance_clock("2026-09-01T00:00:00Z")
        resp = api.file_appeal(appeal["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_APPEAL_DEADLINE_PASSED)


class TestValidationPriorityOnCapVerify:
    def test_proposer_verify_before_window_reports_segregation_error(self, api):
        """PRD §2.9: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the earliest
        failing tier determines the error returned"
        PRD §2.9: "Segregation of duties and director authority — else
        `ERR_SEGREGATION_OF_DUTIES` (409) or `ERR_REQUIRES_DIRECTOR` (403)."
        PRD §3.9: "segregation of duties forbids the plan's proposer from
        verifying it — a verifier whose `X-User-ID` equals the plan's
        `proposed_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_cap_verify
        """
        ctx = setup_cap_in_check(proposer_user_id="co-1")
        resp = api.verify_plan(ctx["cap"]["id"], make_auditor_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_other_verifier_before_window_reports_window_error(self, api):
        """PRD §3.9: "the effectiveness window must have elapsed, meaning the
        logical now must be at least fourteen days past `check_started_at`,
        else `ERR_CAP_WINDOW_NOT_ELAPSED` (HTTP 409)."
        PRD §2.9: "the earliest failing tier determines the error returned"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_cap_verify
        """
        ctx = setup_cap_in_check(proposer_user_id="co-1")
        advance_clock("2026-08-10T00:00:00Z")
        resp = api.verify_plan(ctx["cap"]["id"], make_auditor_headers("ia-1"))
        validate_error(resp, ApiErrorId.ERR_CAP_WINDOW_NOT_ELAPSED)


class TestValidationPriorityOnManualOffset:
    def test_cross_payer_and_over_amount_reports_cross_payer_error(self, api):
        """PRD §2.9: "the earliest failing tier determines the error returned"
        PRD §3.8: "the remittance and the demand must belong to the same payer,
        else `ERR_CROSS_PAYER_ALLOCATION` (HTTP 409)"
        PRD §2.9: "Cross-payer linkage on manual offsets — else
        `ERR_CROSS_PAYER_ALLOCATION` (409)." (tier 10, before money ceilings
        at tier 11)

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_manual_offset
        """
        scn = setup_cross_payer_offset_scenario()
        resp = api.create_manual_offset(
            scn["demand"]["id"],
            manual_offset_payload(scn["remittance_b"]["id"], 200000),
            ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_CROSS_PAYER_ALLOCATION)

    def test_same_payer_over_amount_reports_offset_ceiling_error(self, api):
        """PRD §3.8: "the amount may not exceed the smaller of the remittance's
        `available_cents` and the demand's outstanding principal plus its
        accrued interest, else `ERR_OFFSET_EXCEEDS_OUTSTANDING` (HTTP 409)."
        PRD §2.9: "Money ceilings — demand principal bounds and offset amount
        bounds — else `ERR_DEMAND_EXCEEDS_DENIED` (409) or
        `ERR_OFFSET_EXCEEDS_OUTSTANDING` (409)." (tier 11, reached only when
        cross-payer linkage at tier 10 passes)

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_manual_offset
        """
        scn = setup_cross_payer_offset_scenario()
        payer_a = scn["payer_a"]
        rem_a = create_remittance(payer_a["id"], 200000)
        resp = api.create_manual_offset(
            scn["demand"]["id"],
            manual_offset_payload(rem_a["id"], 200000),
            ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_OFFSET_EXCEEDS_OUTSTANDING)
