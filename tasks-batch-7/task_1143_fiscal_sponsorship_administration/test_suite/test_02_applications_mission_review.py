"""Application lifecycle, mission scorecard, and review-role RBAC
(PRD §2.1, §3.1, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    compliance_decision_payload,
    create_active_bundle,
    create_application,
    create_application_payload,
    create_approved_bundle,
    create_exit_plan_payload,
    create_grant_tranche_payload,
    create_risk_incident_payload,
    decide_application,
    make_applicant_headers,
    make_compliance_officer_headers,
    make_donor_headers,
    make_program_officer_headers,
    make_project_lead_headers,
    make_sponsor_admin_headers,
    mission_score_payload,
    open_review,
    pledge_donation,
    propose_engagement,
    score_mission,
    submit_application,
    validate_error,
    validate_success,
)


class TestInitialStates:
    def test_initial_states(self, api):
        """PRD §3.1: "The application is born in `DRAFT`"
        PRD §3.3: "The gift is born `PLEDGED`, with its `fund_account_id` resolved
        from the project."
        PRD §3.5: "The engagement is born `PROPOSED` with `classification_overridden`
        false"
        PRD §3.6: "the review is born `OPEN` with `findings_count` and
        `open_findings_count` at zero"
        PRD §3.6: "the incident is born `REPORTED`"
        PRD §3.8: "The plan is born `PROPOSED` with an empty `signoffs` list"
        PRD §3.2: "A new tranche is born `ISSUED` with `committed_cents` and
        `spent_cents` at zero."

        Design: Corner/state_machines/sm_initial_states
        """
        app = create_application("user_c_is1", project_name="IS1",
                                 requested_model="COMPREHENSIVE", contact_email="is1@x.org")
        assert app["status"] == "DRAFT"

        bundle = create_active_bundle("user_c_is1b", model="COMPREHENSIVE",
                                      project_name="IS1b", contact_email="is1b@x.org")
        pid = bundle["project_id"]

        donation = pledge_donation(pid, 5000)
        assert donation["status"] == "PLEDGED"

        engagement = propose_engagement(pid, "wis@x.org", rate_cents=1000)
        assert engagement["status"] == "PROPOSED"

        review = open_review(pid, review_type="SCHEDULED")
        assert review["status"] == "OPEN"

        incident = validate_success(api.create_risk_incident(
            pid, create_risk_incident_payload(category="LIABILITY", severity="LOW",
                                              description="minor"),
            make_project_lead_headers(pid)), expected_status=201)
        assert incident["status"] == "REPORTED"

        exit_plan = validate_success(api.create_exit_plan(
            pid, create_exit_plan_payload(successor_entity_name="X",
                                          successor_ein="11-1111111", reason="r"),
            make_project_lead_headers(pid)), expected_status=201)
        assert exit_plan["status"] == "PROPOSED"

        grant_bundle = create_active_bundle("user_c_is2", model="PRE_APPROVED_GRANT",
                                            project_name="IS2", contact_email="is2@x.org")
        tranche = validate_success(api.create_grant_tranche(
            grant_bundle["agreement_id"],
            create_grant_tranche_payload(amount_cents=100000, period_start="2026-01-01",
                                         period_end="2026-03-31", purpose="q1"),
            make_sponsor_admin_headers()), expected_status=201)
        assert tranche["status"] == "ISSUED"
        assert tranche["committed_cents"] == 0
        assert tranche["spent_cents"] == 0


class TestApplicationStateGuards:
    def test_mission_score_on_draft_rejected(self, api):
        """PRD §3.1: "Once `SUBMITTED`, the application awaits a mission scorecard from
        a `ProgramOfficer`."
        PRD §2.11: "Seventh, state-machine guards: the target resource must be in a
        from-state of the requested transition, else the per-machine state error"

        Design: Corner/state_machines/sm_mission_score_on_draft_rejected
        """
        app = create_application("user_c_dr", project_name="DR", contact_email="dr@x.org")
        resp = api.score_mission(app["id"], mission_score_payload(action="ADVANCE"),
                                 make_program_officer_headers())
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_ACTIONABLE)
        after = validate_success(api.get_application(app["id"], make_program_officer_headers()))
        assert after["status"] == "DRAFT"

    def test_withdrawn_terminal_lockdown(self, api):
        """PRD §3.1: "Withdrawal is available to the owning applicant from any
        non-terminal state — `DRAFT`, `SUBMITTED`, `RETURNED`, or `COMPLIANCE_REVIEW` —
        and moves the application to `WITHDRAWN`. `APPROVED`, `REJECTED`, and
        `WITHDRAWN` are terminal."

        Design: Corner/state_machines/sm_withdrawn_terminal_lockdown
        """
        app = create_application("user_c_wd", project_name="WD", contact_email="wd@x.org")
        withdrawn = validate_success(api.withdraw_application(
            app["id"], make_applicant_headers("user_c_wd")))
        assert withdrawn["status"] == "WITHDRAWN"

        e1 = api.submit_application(app["id"], make_applicant_headers("user_c_wd"))
        validate_error(e1, ApiErrorId.ERR_APPLICATION_NOT_ACTIONABLE)
        e2 = api.score_mission(app["id"], mission_score_payload(action="ADVANCE"),
                               make_program_officer_headers())
        validate_error(e2, ApiErrorId.ERR_APPLICATION_NOT_ACTIONABLE)


class TestOwnershipAndReviewRbac:
    def test_ownership_submit_by_other_applicant_rejected(self, api):
        """PRD §3.1: "Submitting is the applicant's own act: the caller's `X-User-ID`
        must equal the application's `applicant_user_id`, otherwise
        `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/validations/v_ownership_submit_by_other_applicant_rejected
        """
        app = create_application("user_c_v3", project_name="OW", contact_email="ow@x.org")
        resp = api.submit_application(app["id"], make_applicant_headers("user_c_other"))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        after = validate_success(api.get_application(app["id"], make_program_officer_headers()))
        assert after["status"] == "DRAFT"

    def test_projectlead_cannot_mission_score(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /fsa/applications/{id}/mission-score is authorized for
        ProgramOfficer only.

        Design: Corner/rbac/rbac_projectlead_cannot_mission_score
        """
        app = create_application("user_c_b2", project_name="RB2", contact_email="rb2@x.org")
        submit_application(app["id"], "user_c_b2")
        resp = api.score_mission(app["id"], mission_score_payload(action="ADVANCE"),
                                 make_project_lead_headers("user_c_b2"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_program_officer_cannot_compliance_decision(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /fsa/applications/{id}/compliance-decision is authorized for
        ComplianceOfficer only.

        Design: Corner/rbac/rbac_program_officer_cannot_compliance_decision
        """
        app = create_application("user_c_b5", project_name="RB5", contact_email="rb5@x.org")
        submit_application(app["id"], "user_c_b5")
        score_mission(app["id"], action="ADVANCE")
        resp = api.decide_compliance(
            app["id"], compliance_decision_payload(decision="APPROVE",
                                                   sponsorship_model="COMPREHENSIVE"),
            make_program_officer_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = validate_success(api.get_application(app["id"], make_program_officer_headers()))
        assert after["status"] == "COMPLIANCE_REVIEW"


class TestMissionScoreRoundingPinned:
    def test_mission_score_per_component_rounding_order(self, api):
        """PRD §3.1: "The rounding order is pinned: each component is individually
        rounded half up to two decimal places first, and the score is the sum of the
        four rounded components."
        PRD §3.1: "Summing the raw components and rounding once is a rejected
        alternative — with inputs 73, 63, 61, and 67 the pinned order yields 60.39
        while sum-first would yield 60.37."

        Design: Difficulty/combinatorial_formula/mission_score_rounding_order_pinned
        """
        app = create_application("user_app_f", project_name="Zeta", contact_email="z@x.org")
        submit_application(app["id"], "user_app_f")
        scored = score_mission(app["id"], action="RETURN", purpose_pts=73,
                               benefit_pts=63, capacity_pts=61, risk_pts=67)
        assert scored["mission_score"] == pytest.approx(60.39, abs=0.001), (
            f"pinned per-component rounding must yield 60.39, got {scored['mission_score']}")

    def test_mission_score_return_persists_score_and_status(self, api):
        """PRD §3.1: "a `RETURN` moves it from `SUBMITTED` to `RETURNED`. Either way
        the computed `mission_score` is persisted."

        Design: Difficulty/combinatorial_formula/mission_score_rounding_order_pinned
        """
        app = create_application("user_app_f2", project_name="Zeta2", contact_email="z2@x.org")
        submit_application(app["id"], "user_app_f2")
        scored = score_mission(app["id"], action="RETURN", purpose_pts=73,
                               benefit_pts=63, capacity_pts=61, risk_pts=67)
        assert scored["status"] == "RETURNED"
        reread = validate_success(api.get_application(app["id"], make_program_officer_headers()))
        assert reread["status"] == "RETURNED"
        assert reread["mission_score"] == pytest.approx(60.39, abs=0.001)


class TestMissionScoreBoundary:
    def test_mission_score_exactly_7000_advances(self, api):
        """PRD §3.1: "An `ADVANCE` action succeeds only when the resulting score is at
        least 70.00, the boundary inclusive; a lower score is rejected with
        `ERR_MISSION_SCORE_BELOW_THRESHOLD` (HTTP 422)."
        Scorecard 50/61/95/10 rounds per component to 16.75 + 16.17 + 20.43 + 16.65
        = 70.00 exactly.

        Design: Difficulty/boundary_precision_check/mission_score_exactly_7000_advances
        """
        app = create_application("user_app_n", project_name="Xi", contact_email="x@x.org")
        submit_application(app["id"], "user_app_n")
        scored = score_mission(app["id"], action="ADVANCE", purpose_pts=50,
                               benefit_pts=61, capacity_pts=95, risk_pts=10)
        assert scored["mission_score"] == pytest.approx(70.00, abs=0.001)
        assert scored["status"] == "COMPLIANCE_REVIEW", (
            "score of exactly 70.00 must advance (boundary inclusive)")

    def test_mission_score_6999_rejected_below_threshold(self, api):
        """PRD §3.1: "An `ADVANCE` action succeeds only when the resulting score is at
        least 70.00, the boundary inclusive; a lower score is rejected with
        `ERR_MISSION_SCORE_BELOW_THRESHOLD` (HTTP 422)."
        Scorecard 50/54/95/0 rounds per component to 16.75 + 14.31 + 20.43 + 18.50
        = 69.99.

        Design: Difficulty/boundary_precision_check/mission_score_exactly_7000_advances
        """
        app = create_application("user_app_o", project_name="Omicron", contact_email="o@x.org")
        submit_application(app["id"], "user_app_o")
        resp = api.score_mission(
            app["id"],
            mission_score_payload(action="ADVANCE", purpose_pts=50, benefit_pts=54,
                                  capacity_pts=95, risk_pts=0),
            make_program_officer_headers())
        validate_error(resp, ApiErrorId.ERR_MISSION_SCORE_BELOW_THRESHOLD)
        after = validate_success(api.get_application(app["id"], make_program_officer_headers()))
        assert after["status"] == "SUBMITTED"


class TestApplicationRevisionCycle:
    def test_application_revision_loop_states(self, api):
        """PRD §3.1: "The same submission also serves the revision loop — an
        application in `RETURNED` may be resubmitted to `SUBMITTED` by its owner,
        again incrementing `submit_count`"
        PRD §3.1: "On `REJECT` the application becomes `REJECTED`; on `RETURN` it goes
        back to `RETURNED` for another revision loop."
        PRD §3.1: "a `RETURN` moves it from `SUBMITTED` to `RETURNED`."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle
        """
        app = create_application("user_app_h", project_name="Theta", contact_email="t@x.org")
        submit_application(app["id"], "user_app_h")

        returned1 = score_mission(app["id"], action="RETURN", purpose_pts=40,
                                  benefit_pts=40, capacity_pts=40, risk_pts=90)
        assert returned1["status"] == "RETURNED", "mission-score RETURN from SUBMITTED"

        submit_application(app["id"], "user_app_h")
        advanced = score_mission(app["id"], action="ADVANCE")
        assert advanced["status"] == "COMPLIANCE_REVIEW"

        returned2 = decide_application(app["id"], "RETURN", rationale="budget unclear")
        assert returned2["status"] == "RETURNED", "compliance-decision RETURN loops back"

        submit_application(app["id"], "user_app_h")
        advanced2 = score_mission(app["id"], action="ADVANCE")
        assert advanced2["status"] == "COMPLIANCE_REVIEW"

        approved = decide_application(app["id"], "APPROVE", sponsorship_model="COMPREHENSIVE")
        assert approved["status"] == "APPROVED"

    def test_application_revision_loop_submit_count_and_minted_ids(self, api):
        """PRD §3.1: "Submission from `DRAFT` moves the application to `SUBMITTED` and
        increments `submit_count` by one."
        PRD §3.1: "On `APPROVE`, the application's `decided_model` is set from the
        request's `sponsorship_model` — it may differ from `requested_model` — and a
        single atomic cascade mints three resources"
        PRD §3.1: "The application's `project_id`, `agreement_id`, and `fund_account_id`
        are back-linked to the minted ids."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle
        """
        app = create_application("user_app_h2", project_name="Theta2", contact_email="t2b@x.org")
        submit_application(app["id"], "user_app_h2")                      # submit_count 1
        score_mission(app["id"], action="RETURN", purpose_pts=40, benefit_pts=40,
                      capacity_pts=40, risk_pts=90)
        submit_application(app["id"], "user_app_h2")                      # submit_count 2
        score_mission(app["id"], action="ADVANCE")
        decide_application(app["id"], "RETURN", rationale="budget unclear")
        submit_application(app["id"], "user_app_h2")                      # submit_count 3
        score_mission(app["id"], action="ADVANCE")
        approved = decide_application(app["id"], "APPROVE", sponsorship_model="COMPREHENSIVE")

        assert approved["status"] == "APPROVED"
        assert approved["submit_count"] == 3, (
            f"three submissions through the revision loop, got {approved['submit_count']}")
        assert approved["project_id"], "approval must back-link the minted project id"
        assert approved["agreement_id"], "approval must back-link the minted agreement id"
        assert approved["fund_account_id"], "approval must back-link the minted fund id"
