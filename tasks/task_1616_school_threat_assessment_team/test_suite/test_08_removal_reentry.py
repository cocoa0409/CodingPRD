"""Subject removal, re-entry proposals, adjudication, and re-entry completion."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_reentry_plan_payload,
    get_case,
    list_case_checkins,
    make_team_lead_headers,
    make_threat_assessor_headers,
    propose_reentry_plan,
    remove_case,
    setup_case_removed,
    setup_case_under_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)

TA1 = make_threat_assessor_headers("ta_1")
TL1 = TEST_USERS["team_lead_headers"]
TL2 = make_team_lead_headers("tl_2")


class TestReentryGatingByCaseState:
    def test_reentry_plan_creation_rejected_before_removal(self, api):
        """PRD: "A `ThreatAssessor` proposes a re-entry plan for a `REMOVED`
        case (`ERR_CASE_NOT_REMOVED` otherwise), provided no other re-entry
        plan for the case is still open in `PROPOSED` or `APPROVED`
        (`ERR_OPEN_REENTRY_PLAN_EXISTS`)."

        Design: Difficulty/cross_entity_state_dependency/reentry_plan_creation_gated_by_case_removed
        """
        case = setup_case_under_assessment()
        resp = api.create_reentry_plan(
            create_reentry_plan_payload(
                case["id"], conditions=["risk re-assessment completed"]),
            TA1,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_REMOVED)

        plans, meta = validate_paginated(api.list_case_reentry_plans(
            case["id"], TL1))
        assert meta["total_count"] == 0

    def test_reentry_plan_creation_succeeds_after_removal(self, api):
        """PRD: "A `ThreatAssessor` proposes a re-entry plan for a `REMOVED`
        case (`ERR_CASE_NOT_REMOVED` otherwise), provided no other re-entry
        plan for the case is still open in `PROPOSED` or `APPROVED`
        (`ERR_OPEN_REENTRY_PLAN_EXISTS`)."
        PRD: "The proposal carries `case_id` and a non-empty `conditions`
        array; the server stores each condition as an object with its
        `description`, a `status` initially `UNMET`, and an `evidence_note`
        initially null."

        Design: Difficulty/cross_entity_state_dependency/reentry_plan_creation_gated_by_case_removed
        """
        case = setup_case_under_assessment()
        removed = remove_case(case["id"],
                              removal_type="DISCIPLINARY_EXCLUSION",
                              reason="suspension pending assessment")
        assert removed["status"] == "REMOVED"
        assert removed["removal_type"] == "DISCIPLINARY_EXCLUSION"

        plan = validate_success(
            api.create_reentry_plan(
                create_reentry_plan_payload(
                    case["id"], conditions=["risk re-assessment completed"]),
                TA1),
            201,
        )
        assert plan["status"] == "PROPOSED"
        assert plan["created_by_user_id"] == "ta_1"
        assert plan["conditions"][0]["status"] == "UNMET"
        assert plan["conditions"][0]["evidence_note"] is None
        assert plan["conditions"][0]["description"] == "risk re-assessment completed"


class TestReentrySegregationOfDuties:
    def test_approve_by_proposer_rejected(self, api):
        """PRD: "A `TeamLead` then adjudicates: approval requires the plan to
        be `PROPOSED` (`ERR_REENTRY_NOT_PROPOSED`), requires the case to be
        `REMOVED` (`ERR_CASE_NOT_REMOVED`), and enforces segregation of duties
        — an approver whose `X-User-ID` equals the plan's
        `created_by_user_id` is rejected with `ERR_SOD_SELF_APPROVAL` — before
        moving the plan to `APPROVED` and writing `REENTRY_APPROVED`."

        Design: Corner/validations/sod_reentry_approve_by_proposer_rejected
        """
        case, _plan = setup_case_removed()
        plan = propose_reentry_plan(case["id"], conditions=["counseling intake"])

        resp = api.approve_reentry_plan(plan["id"], make_team_lead_headers("ta_1"))
        validate_error(resp, ApiErrorId.ERR_SOD_SELF_APPROVAL)

        after = validate_paginated(api.list_case_reentry_plans(
            case["id"], TL1, params={"status": "PROPOSED"}))[1]
        assert after["total_count"] == 1, "the rejected approval changes nothing"

    def test_state_error_beats_sod_when_approving_denied_plan(self, api):
        """PRD: "When a request fails several rules at once, the error it
        receives is deterministic because validation proceeds in a fixed
        order."
        PRD: "Only then are state preconditions evaluated — the resource being
        acted upon and the case referenced in the body must each be in a state
        that permits the operation — and only after those come the
        business-safety rules (segregation of duties, interview gating,
        referral prerequisites, closure blockers, re-entry condition
        completeness), then uniqueness and quota constraints, then
        cadence-length limits, and finally temporal rules such as interval
        overlap and past-dated deadlines."
        PRD: "A `TeamLead` then adjudicates: approval requires the plan to be
        `PROPOSED` (`ERR_REENTRY_NOT_PROPOSED`), requires the case to be
        `REMOVED` (`ERR_CASE_NOT_REMOVED`), and enforces segregation of duties
        — an approver whose `X-User-ID` equals the plan's
        `created_by_user_id` is rejected with `ERR_SOD_SELF_APPROVAL` — before
        moving the plan to `APPROVED` and writing `REENTRY_APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/reentry_approve_state_error_beats_sod
        """
        case, _plan = setup_case_removed()
        plan = propose_reentry_plan(case["id"],
                                    conditions=["counseling intake completed"])
        denied = validate_success(
            api.deny_reentry_plan(plan["id"],
                                  {"denial_reason": "conditions insufficient"},
                                  TL1),
            200,
        )
        assert denied["status"] == "DENIED"

        # The caller carries the proposer's operator id, so the SoD rule is
        # also violated; the state precondition is evaluated first.
        resp = api.approve_reentry_plan(plan["id"], make_team_lead_headers("ta_1"))
        validate_error(resp, ApiErrorId.ERR_REENTRY_NOT_PROPOSED)

    def test_state_error_also_fires_for_unrelated_approver(self, api):
        """PRD: "A `TeamLead` then adjudicates: approval requires the plan to
        be `PROPOSED` (`ERR_REENTRY_NOT_PROPOSED`), requires the case to be
        `REMOVED` (`ERR_CASE_NOT_REMOVED`), and enforces segregation of duties
        — an approver whose `X-User-ID` equals the plan's
        `created_by_user_id` is rejected with `ERR_SOD_SELF_APPROVAL` — before
        moving the plan to `APPROVED` and writing `REENTRY_APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/reentry_approve_state_error_beats_sod
        """
        case, _plan = setup_case_removed()
        plan = propose_reentry_plan(case["id"], conditions=["counseling intake"])
        validate_success(
            api.deny_reentry_plan(plan["id"], {"denial_reason": "insufficient"},
                                  TL1),
            200,
        )

        resp = api.approve_reentry_plan(plan["id"], TL2)
        validate_error(resp, ApiErrorId.ERR_REENTRY_NOT_PROPOSED)


class TestReentryConditionVerification:
    def test_verify_condition_with_out_of_range_index_returns_404(self, api):
        """PRD: "While the plan is `PROPOSED` or `APPROVED`, a
        `ThreatAssessor` may verify individual conditions by zero-based
        `conditionIndex`, attaching an `evidence_note`; the referenced
        condition's `status` becomes `MET`, and an index outside the array is
        `ERR_CONDITION_NOT_FOUND`."

        Design: Corner/endpoints/verify_condition_with_out_of_range_index_returns_404
        """
        case, _plan = setup_case_removed()
        plan = propose_reentry_plan(case["id"], conditions=["only one condition"])

        resp = api.verify_reentry_condition(
            plan["id"], 5, {"evidence_note": "no such index"}, TA1)
        validate_error(resp, ApiErrorId.ERR_CONDITION_NOT_FOUND)


class TestReentryCompletion:
    def test_full_flow_returns_case_to_plan_active(self, api):
        """PRD: "On success the plan becomes `REENTERED`,
        `REENTRY_COMPLETED` is audited, and the case reopens: its
        `removal_type` is cleared to null, `CASE_REOPENED` is written, and it
        returns to `PLAN_ACTIVE` when an `ACTIVE` management plan exists for
        it, otherwise to `UNDER_ASSESSMENT`."
        PRD: "When the return is to `PLAN_ACTIVE`, a re-entry monitoring
        check-in is auto-created with `auto_created` true, due the current
        calendar date plus 30 days."
        PRD: "Removal is deliberately not an unwind: open check-ins and
        referrals are not cancelled, monitoring continues during removal, and
        an `ACTIVE` management plan remains `ACTIVE`."

        Design: Corner/state_machines/reentry_full_flow_returns_case_to_plan_active
        """
        case, _plan = setup_case_removed(
            with_active_plan=True, cadence_mode="FROM_COMPLETION",
            cadence_days=7)
        reentry = propose_reentry_plan(
            case["id"],
            conditions=["counseling intake completed", "parent meeting held"])

        approved = validate_success(
            api.approve_reentry_plan(reentry["id"], TL2), 200)
        assert approved["status"] == "APPROVED"

        for index, note in ((0, "intake session 2026-08-01"),
                            (1, "meeting held")):
            updated = validate_success(
                api.verify_reentry_condition(reentry["id"], index,
                                             {"evidence_note": note}, TA1),
                200,
            )
            assert updated["conditions"][index]["status"] == "MET"

        completed = validate_success(
            api.complete_reentry(reentry["id"], TL2), 200)
        assert completed["status"] == "REENTERED"

        case_after = get_case(case["id"])
        assert case_after["status"] == "PLAN_ACTIVE"
        assert case_after["removal_type"] is None

        scheduled, meta = list_case_checkins(case["id"], status="SCHEDULED")
        assert meta["total_count"] == 2
        assert sorted(c["due_date"] for c in scheduled) == [
            "2026-08-08", "2026-08-31"], (
            "the surviving cadence check-in plus the re-entry check-in due "
            "the current calendar date plus 30 days"
        )

    def test_reentry_without_active_plan_returns_to_under_assessment(self, api):
        """PRD: "On success the plan becomes `REENTERED`,
        `REENTRY_COMPLETED` is audited, and the case reopens: its
        `removal_type` is cleared to null, `CASE_REOPENED` is written, and it
        returns to `PLAN_ACTIVE` when an `ACTIVE` management plan exists for
        it, otherwise to `UNDER_ASSESSMENT`."
        PRD: "When the return is to `PLAN_ACTIVE`, a re-entry monitoring
        check-in is auto-created with `auto_created` true, due the current
        calendar date plus 30 days."

        Design: Corner/state_machines/reentry_without_active_plan_returns_to_under_assessment
        """
        case, no_plan = setup_case_removed()
        assert no_plan is None
        reentry = propose_reentry_plan(
            case["id"], conditions=["risk re-assessment scheduled"])
        validate_success(api.approve_reentry_plan(reentry["id"], TL2), 200)
        validate_success(
            api.verify_reentry_condition(reentry["id"], 0,
                                         {"evidence_note": "scheduled 2026-08-05"},
                                         TA1),
            200,
        )

        completed = validate_success(
            api.complete_reentry(reentry["id"], TL2), 200)
        assert completed["status"] == "REENTERED"

        case_after = get_case(case["id"])
        assert case_after["status"] == "UNDER_ASSESSMENT", (
            "with no ACTIVE management plan the case returns to "
            "UNDER_ASSESSMENT"
        )
        assert case_after["removal_type"] is None

        _checkins, meta = list_case_checkins(case["id"])
        assert meta["total_count"] == 0, (
            "no re-entry check-in is created on the UNDER_ASSESSMENT branch"
        )
