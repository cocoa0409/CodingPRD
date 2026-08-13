"""Correction program filings, RBAC denials, segregation of duties, overlap rules."""
from test_helpers import (
    AUDITOR,
    MANAGER,
    NON_EXISTENT_UUID,
    SPONSOR,
    SYSTEM,
    TPA,
    ApiErrorId,
    acknowledge_finding,
    api_client,
    create_correction_program_filing_payload,
    create_engagement,
    create_engagement_payload,
    create_manual_finding,
    create_participant_payload,
    create_schedule_entry_payload,
    create_small_plan_engagement,
    get_success_data,
    make_manager_headers,
    make_tpa_headers,
    propose_approved_action,
    set_clock,
    setup_acknowledged_finding,
    validate_error,
    validate_success,
    execute_action,
)


class TestCorrectionProgramFilings:

    def test_reject_resubmit_approve_cycle(self):
        """PRD §3.10: "An `EngagementManager` submits a `DRAFTED` filing to the
        agency, but only when every finding named in `linked_finding_ids` is in
        `CORRECTED` or `VERIFIED_CLOSED` status; otherwise the submit is rejected
        with `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.10: "A `REJECTED` program filing may be cured and resubmitted: an
        `EngagementManager` resubmits it, provided the linked findings are still
        in `CORRECTED` or `VERIFIED_CLOSED`, returning it from `REJECTED` to
        `SUBMITTED`. The `APPROVED` and `WITHDRAWN` statuses are terminal."

        Design: Corner/state_machines/correction_program_filing_resubmit_cycle
        """
        ctx = setup_acknowledged_finding(
            severity="HIGH", category="NONDISCRIMINATION_FAILURE",
            description="ADP failure")
        action = propose_approved_action(
            ctx["engagement"]["id"], ctx["finding"]["id"],
            action_type="QNEC_CONTRIBUTION", principal_cents=8_000,
            planned_execution_date="2026-03-01",
            participant_id=ctx["participant"]["id"])
        set_clock("2026-03-01T00:00:00Z")
        execute_action(action["id"])
        get_success_data(api_client.verify_corrective_action(action["id"], AUDITOR))
        closed = validate_success(api_client.verify_close_finding(ctx["finding"]["id"], AUDITOR))
        assert closed["status"] == "VERIFIED_CLOSED"
        participant_now = get_success_data(
            api_client.get_participant(ctx["participant"]["id"], SPONSOR))
        assert participant_now["account_balance_cents"] == 8_000
        cpf = get_success_data(api_client.create_correction_program_filing(
            create_correction_program_filing_payload(
                ctx["engagement"]["id"], program="EPCRS_VCP",
                linked_finding_ids=[ctx["finding"]["id"]],
                government_fee_cents=150_000),
            MANAGER))
        assert cpf["status"] == "DRAFTED"
        submitted = get_success_data(api_client.submit_correction_program_filing(cpf["id"], MANAGER))
        assert submitted["status"] == "SUBMITTED"
        rejected = get_success_data(api_client.record_decision(
            cpf["id"], {"outcome": "REJECTED", "notes": "incomplete attachments"}, SYSTEM))
        assert rejected["status"] == "REJECTED"
        resubmitted = get_success_data(
            api_client.submit_correction_program_filing(cpf["id"], MANAGER))
        assert resubmitted["status"] == "SUBMITTED"
        approved = get_success_data(api_client.record_decision(
            cpf["id"], {"outcome": "APPROVED"}, SYSTEM))
        assert approved["status"] == "APPROVED"


class TestAuthAndRoles:

    def test_missing_auth_headers_rejected(self):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, naming the capacity in
        which they act. A request in which either header is missing or malformed is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api_client.create_engagement(create_engagement_payload(), {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       expected_status=400)

    def test_auditor_cannot_create_participants(self):
        """PRD §2.1: "A request whose `X-User-Role` is not in the endpoint's
        allowed role list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "POST | `/plan-audit/participants` | Create one census participant
        | SponsorAdmin".

        Design: Corner/rbac/auditor_cannot_create_participants_forbidden
        """
        eng = create_engagement()
        resp = api_client.create_participant(
            create_participant_payload(eng["id"], "P-001"), AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_sponsor_cannot_verify_close_finding(self):
        """PRD §2.1: "A request whose `X-User-Role` is not in the endpoint's
        allowed role list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "POST | `/plan-audit/findings/{id}/verify_close` | Auditor verifies
        and closes a corrected finding | PlanAuditor".

        Design: Corner/rbac/sponsor_cannot_verify_close_finding_forbidden
        """
        eng = create_engagement()
        finding = create_manual_finding(
            eng["id"], category="FILING_DEFECT", severity="LOW", description="x")
        resp = api_client.verify_close_finding(finding["id"], SPONSOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        finding_now = get_success_data(api_client.get_finding(finding["id"], SPONSOR))
        assert finding_now["status"] == "OPEN"


class TestSegregationOfDuties:

    def test_proposer_cannot_approve_own_action(self):
        """PRD §2.7: "First, a corrective action is proposed by one operator and
        approved by another: the request to approve is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 409) when the approver's `X-User-ID`
        equals the action's recorded `proposed_by_user_id`."

        Design: Corner/rbac/segregation_of_duties_proposer_cannot_approve
        """
        ctx = setup_acknowledged_finding(
            severity="MEDIUM", category="FEE_DISCLOSURE_GAP", description="x")
        action = get_success_data(api_client.create_corrective_action(
            {
                "engagement_id": ctx["engagement"]["id"],
                "finding_id": ctx["finding"]["id"],
                "action_type": "FEE_REDISCLOSURE",
                "principal_cents": 100,
                "planned_execution_date": "2026-04-01",
            },
            SPONSOR,  # proposed by u-sponsor-1
        ))
        assert action["status"] == "PROPOSED"
        # Same operator id, acting in the manager capacity, still loses the SoD check.
        resp = api_client.approve_corrective_action(
            action["id"], make_manager_headers("u-sponsor-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        action_now = get_success_data(api_client.get_corrective_action(action["id"], SPONSOR))
        assert action_now["status"] == "PROPOSED"

    def test_filing_creator_cannot_mark_ready(self):
        """PRD §2.7: "Second, a filing is created by one operator and marked ready
        by another: the readiness step is rejected with `ERR_SEGREGATION_OF_DUTIES`
        when the marker's `X-User-ID` equals the filing's recorded
        `created_by_user_id`."

        Design: Corner/rbac/segregation_of_duties_filing_creator_cannot_mark_ready
        """
        eng, _p = create_small_plan_engagement()
        dual_headers = make_tpa_headers("u-dual-1")
        filing = get_success_data(api_client.create_filing(
            {"engagement_id": eng["id"]}, dual_headers))
        entry = get_success_data(api_client.create_schedule_entry(
            create_schedule_entry_payload(filing["id"], schedule_type="I"), TPA))
        get_success_data(api_client.verify_schedule_entry(entry["id"], AUDITOR))
        get_success_data(api_client.mark_schedules_complete(filing["id"], TPA))
        # The same operator id that created the filing cannot mark it ready.
        resp = api_client.mark_ready(filing["id"], make_manager_headers("u-dual-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["status"] == "SCHEDULES_COMPLETE"


class TestExistenceOrdering:

    def test_unknown_engagement_id_reports_not_found(self):
        """PRD §2.6: "The same `ERR_NOT_FOUND` rejection applies when a
        foreign-key identifier carried in a request body points at a resource that
        does not exist".

        Design: Corner/validations/existence_check_left_to_right
        """
        resp = api_client.create_finding(
            {
                "engagement_id": NON_EXISTENT_UUID,
                "category": "FILING_DEFECT",
                "severity": "LOW",
                "description": "x",
                "contribution_id": "1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e",
            },
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestPlanYearOverlap:

    def test_overlapping_plan_year_rejected(self):
        """PRD §3.1: "Two engagements with the same combination of `sponsor_ein`
        and `plan_number` may not have overlapping plan years; because the
        interval is half-open, an adjacency in which one engagement's
        `plan_year_end` equals another's `plan_year_start` is permitted, but any
        true overlap is rejected with `ERR_PLAN_YEAR_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/engagement_plan_year_half_open_overlap
        """
        create_engagement(plan_number="017", plan_name="Pi 401(k) Plan")
        resp = api_client.create_engagement(
            create_engagement_payload(
                plan_number="017", plan_name="Pi 401(k) Plan mid-year dup",
                plan_year_start="2025-07-01", plan_year_end="2026-07-01"),
            SPONSOR)
        validate_error(resp, ApiErrorId.ERR_PLAN_YEAR_OVERLAP)

    def test_adjacent_plan_year_and_different_plan_number_accepted(self):
        """PRD §3.1: "an adjacency in which one engagement's `plan_year_end`
        equals another's `plan_year_start` is permitted".
        PRD §3.1: "Two engagements with the same combination of `sponsor_ein` and
        `plan_number` may not have overlapping plan years".

        Design: Difficulty/resource_temporal_overlap/engagement_plan_year_half_open_overlap
        """
        first = create_engagement(plan_number="017", plan_name="Pi 401(k) Plan")
        assert first["status"] == "DRAFT"
        # Adjacent half-open interval: [2026-01-01, 2027-01-01) touches but does
        # not overlap [2025-01-01, 2026-01-01).
        adjacent = validate_success(api_client.create_engagement(
            create_engagement_payload(
                plan_number="017", plan_name="Pi 401(k) Plan PY2026",
                plan_year_start="2026-01-01", plan_year_end="2027-01-01"),
            SPONSOR), expected_status=201)
        assert adjacent["status"] == "DRAFT"
        # Overlap is only policed within the same (sponsor_ein, plan_number).
        other_plan = validate_success(api_client.create_engagement(
            create_engagement_payload(plan_number="917", plan_name="Other Plan"),
            SPONSOR), expected_status=201)
        assert other_plan["status"] == "DRAFT"
