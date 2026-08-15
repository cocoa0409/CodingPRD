"""Background-check risk scoring, background-gated application transitions,
and emergency-permit interval rules."""
from test_helpers import (
    EVALUATOR,
    INVESTIGATOR,
    LEGAL,
    ApiErrorId,
    add_and_verify_transcript,
    advance_application,
    api_client,
    create_application,
    issue_emergency_permit,
    num,
    open_and_submit_background_check,
    open_background_check,
    post_plan_evidence,
    register_applicant,
    report_and_verify_score,
    setup_deficiency_pending_application,
    setup_reciprocity_full_in_evaluation,
    submit_prints,
    validate_error,
    validate_success,
)


class TestRiskScoreComputation:

    def test_auto_clear_with_zero_risk(self):
        """PRD section 3.6: "a `CONVICTION` contributes its full decayed
        weight, a `PENDING` finding contributes half of its decayed weight,
        and a `DISMISSED` finding contributes nothing."
        PRD section 3.6: "A check whose `risk_score` is below 40 and carries
        no forced flag clears automatically; anything else lands in
        `FLAGGED`."

        Design: Corner/state_machines/background_check_auto_clears_with_zero_risk
        """
        applicant = register_applicant(full_name="Yol Yo", email="yol@x.com")
        app = create_application(applicant["id"], pathway="RECIPROCITY",
                                 subject_area="MATHEMATICS", grade_band="G7_12")
        check = open_background_check(
            app["id"],
            adverse_findings=[{
                "offense_category": "MISDEMEANOR_OTHER",
                "offense_date": "2020-01-01T00:00:00Z",
                "disposition": "DISMISSED"}])
        resolved = submit_prints(check["id"])
        assert num(resolved["risk_score"]) == 0
        assert resolved["status"] == "CLEARED", (
            "PRINTS_SUBMITTED is transient and must land in CLEARED here")

    def test_old_violent_felony_decays_below_threshold_and_clears(self):
        """PRD section 3.6: "findings aged at most 3 years count at full
        weight, findings older than 3 years and at most 7 years count at half
        weight, and findings older than 7 years count at one quarter."
        PRD section 3.6: "Separately, a forced-flag disqualifier applies
        whenever any finding is a `FELONY_VIOLENT` `CONVICTION` aged at most
        10 years."

        Design: Corner/calculations/risk_score_decay_band_old_felony_clears
        """
        applicant = register_applicant(full_name="Gus Gu", email="gus@x.com")
        app = create_application(applicant["id"], pathway="RECIPROCITY",
                                 subject_area="MATHEMATICS", grade_band="G7_12")
        check = open_background_check(
            app["id"],
            adverse_findings=[{
                "offense_category": "FELONY_VIOLENT",
                "offense_date": "2014-08-01T00:00:00Z",
                "disposition": "CONVICTION"}])
        resolved = submit_prints(check["id"])
        # 100 * 0.25 = 25 (< 40); aged ~12 years, outside the 10-year
        # forced-flag lookback.
        assert num(resolved["risk_score"]) == 25
        assert resolved["status"] == "CLEARED"

    def test_forced_flag_violent_conviction_within_lookback(self):
        """PRD section 3.6: "Separately, a forced-flag disqualifier applies
        whenever any finding is a `FELONY_VIOLENT` `CONVICTION` aged at most
        10 years. A check whose `risk_score` is below 40 and carries no forced
        flag clears automatically; anything else lands in `FLAGGED`."

        Design: Corner/calculations/forced_flag_violent_conviction_within_lookback
        """
        applicant = register_applicant(full_name="Han Ha", email="han@x.com")
        app = create_application(applicant["id"], pathway="RECIPROCITY",
                                 subject_area="MATHEMATICS", grade_band="G7_12")
        check = open_background_check(
            app["id"],
            adverse_findings=[{
                "offense_category": "FELONY_VIOLENT",
                "offense_date": "2018-08-01T00:00:00Z",
                "disposition": "CONVICTION"}])
        resolved = submit_prints(check["id"])
        # 100 * 0.25 = 25 (< 40) but aged ~8 years -> forced flag.
        assert num(resolved["risk_score"]) == 25
        assert resolved["status"] == "FLAGGED"


class TestBackgroundCheckUniqueness:

    def test_second_open_background_check_rejected(self):
        """PRD section 3.6: "The check opens in `INITIATED`, and only one
        non-terminal check may exist per application — opening a second while
        the first is still in flight is rejected with
        `ERR_BACKGROUND_CHECK_OPEN`."

        Design: Corner/validations/second_open_background_check_rejected
        """
        applicant = register_applicant(full_name="Ron Ro", email="ron@x.com")
        app = create_application(applicant["id"], pathway="RECIPROCITY",
                                 subject_area="MATHEMATICS", grade_band="G7_12")
        open_background_check(app["id"], adverse_findings=[])
        resp = api_client.create_background_check(
            app["id"], {"adverse_findings": []}, INVESTIGATOR)
        validate_error(resp, ApiErrorId.ERR_BACKGROUND_CHECK_OPEN)


class TestBackgroundGateOnDecision:

    def _setup_flagged_application_in_background_review(self, full_name, email):
        """RECIPROCITY FULL application in BACKGROUND_REVIEW whose check is
        FLAGGED (MISDEMEANOR_DRUG conviction ~2 years old: 40 x 1.0 = 40,
        which is not below 40)."""
        applicant = register_applicant(full_name=full_name, email=email)
        app = setup_reciprocity_full_in_evaluation(applicant)
        check = open_and_submit_background_check(
            app["id"],
            adverse_findings=[{
                "offense_category": "MISDEMEANOR_DRUG",
                "offense_date": "2024-08-01T00:00:00Z",
                "disposition": "CONVICTION"}])
        assert check["status"] == "FLAGGED"
        app = advance_application(app["id"], "BACKGROUND_REVIEW", EVALUATOR)
        return applicant, app, check

    def test_pending_decision_blocked_until_background_cleared(self):
        """PRD section 3.6: "the investigator's advance from
        `BACKGROUND_REVIEW` to `PENDING_DECISION` requires the check to be
        fully `CLEARED` (else `ERR_BACKGROUND_NOT_CLEARED`)."
        PRD section 3.6: "A `LegalOfficer` adjudicates flagged checks, moving
        them `FLAGGED` → `ADJUDICATION` and then to a final `CLEARED` or
        `DENIED`."

        Design: Difficulty/cross_entity_state_dependency/application_blocked_until_background_cleared
        """
        _, app, check = self._setup_flagged_application_in_background_review(
            "Ned Ne", "ned@x.com")
        resp = api_client.transition_application(
            app["id"], {"to_status": "PENDING_DECISION"}, INVESTIGATOR)
        validate_error(resp, ApiErrorId.ERR_BACKGROUND_NOT_CLEARED)
        for target in ("ADJUDICATION", "CLEARED"):
            resp = api_client.transition_background_check(
                check["id"], {"to_status": target}, LEGAL)
            validate_success(resp)
        advanced = advance_application(app["id"], "PENDING_DECISION", INVESTIGATOR)
        assert advanced["status"] == "PENDING_DECISION"
        fetched_check = validate_success(
            api_client.get_background_check(check["id"], EVALUATOR))
        assert num(fetched_check["risk_score"]) == 40

    def test_pending_decision_blocked_while_check_in_adjudication(self):
        """PRD section 3.6: "the investigator's advance from
        `BACKGROUND_REVIEW` to `PENDING_DECISION` requires the check to be
        fully `CLEARED` (else `ERR_BACKGROUND_NOT_CLEARED`)."

        Design: Difficulty/cross_entity_state_dependency/application_blocked_until_background_cleared
        """
        _, app, check = self._setup_flagged_application_in_background_review(
            "Ned Nf", email="nedf@x.com")
        resp = api_client.transition_background_check(
            check["id"], {"to_status": "ADJUDICATION"}, LEGAL)
        validate_success(resp)
        resp = api_client.transition_application(
            app["id"], {"to_status": "PENDING_DECISION"}, INVESTIGATOR)
        validate_error(resp, ApiErrorId.ERR_BACKGROUND_NOT_CLEARED)
        resp = api_client.transition_background_check(
            check["id"], {"to_status": "CLEARED"}, LEGAL)
        validate_success(resp)
        advanced = advance_application(app["id"], "PENDING_DECISION", INVESTIGATOR)
        assert advanced["status"] == "PENDING_DECISION"


class TestBackgroundDenialCascade:

    def test_background_denial_cascades_application_and_permit(self):
        """PRD section 3.6: "Denial cascades twice: the linked application, if
        sitting in `BACKGROUND_REVIEW`, transitions to `DENIED`, and that
        denial in turn revokes every emergency permit of the application still
        `ISSUED` or `ACTIVE`."

        Design: Difficulty/transitive_cascade/background_denial_cascades_application_and_permit
        """
        ctx = setup_deficiency_pending_application(
            accept_plan=True, full_name="Ida Id", email="ida@x.com")
        applicant, app, plan = (
            ctx["applicant"], ctx["application"], ctx["plan"])
        permit = issue_emergency_permit(
            app["id"], district_code="D02",
            valid_from="2026-09-01T00:00:00Z",
            valid_until="2027-03-01T00:00:00Z")
        post_plan_evidence(plan["id"], 30)
        app = advance_application(app["id"], "EVALUATION", EVALUATOR)
        add_and_verify_transcript(app["id"], applicant["id"],
                                  subject_relevant_hours=18,
                                  institution_name="Night School",
                                  total_semester_hours=90,
                                  courses=[{"course_code": "BIO101",
                                            "credit_hours": 4,
                                            "letter_grade": "B"}])
        report_and_verify_score(app["id"], applicant["id"], "PRAXIS_SUBJECT",
                                60, tested_on="2026-07-01T00:00:00Z")
        report_and_verify_score(app["id"], applicant["id"], "PEDAGOGY", 30,
                                tested_on="2026-07-02T00:00:00Z")
        check = open_and_submit_background_check(
            app["id"],
            adverse_findings=[{
                "offense_category": "FELONY_OTHER",
                "offense_date": "2024-08-01T00:00:00Z",
                "disposition": "CONVICTION"}])
        assert check["status"] == "FLAGGED"
        advance_application(app["id"], "BACKGROUND_REVIEW", EVALUATOR)
        resp = api_client.transition_background_check(
            check["id"], {"to_status": "ADJUDICATION"}, LEGAL)
        validate_success(resp)
        resp = api_client.transition_background_check(
            check["id"], {"to_status": "DENIED"}, LEGAL)
        denied_check = validate_success(resp)
        assert denied_check["status"] == "DENIED"
        fetched_app = validate_success(
            api_client.get_application(app["id"], EVALUATOR))
        assert fetched_app["status"] == "DENIED"
        fetched_permit = validate_success(
            api_client.get_emergency_permit(permit["id"], EVALUATOR))
        assert fetched_permit["status"] == "REVOKED"
        fetched_plan = validate_success(
            api_client.get_deficiency_plan(plan["id"], EVALUATOR))
        assert fetched_plan["status"] == "COMPLETED"

    def test_background_denial_outside_background_review_does_not_cascade(self):
        """PRD section 3.6: "Denial cascades twice: the linked application, if
        sitting in `BACKGROUND_REVIEW`, transitions to `DENIED`, and that
        denial in turn revokes every emergency permit of the application still
        `ISSUED` or `ACTIVE`."

        Design: Difficulty/transitive_cascade/background_denial_cascades_application_and_permit
        """
        applicant = register_applicant(full_name="Ida Ie", email="idae@x.com")
        app = setup_reciprocity_full_in_evaluation(applicant)
        check = open_and_submit_background_check(
            app["id"],
            adverse_findings=[{
                "offense_category": "FELONY_OTHER",
                "offense_date": "2024-08-01T00:00:00Z",
                "disposition": "CONVICTION"}])
        assert check["status"] == "FLAGGED"
        for target in ("ADJUDICATION", "DENIED"):
            resp = api_client.transition_background_check(
                check["id"], {"to_status": target}, LEGAL)
            validate_success(resp)
        fetched_app = validate_success(
            api_client.get_application(app["id"], EVALUATOR))
        assert fetched_app["status"] == "EVALUATION", (
            "the denial cascade applies only when the application sits in "
            "BACKGROUND_REVIEW")


class TestEmergencyPermitSafetyAndOverlap:

    def _setup_permit_context(self, full_name, email, district="D01"):
        ctx = setup_deficiency_pending_application(
            accept_plan=True, full_name=full_name, email=email)
        permit = issue_emergency_permit(
            ctx["application"]["id"], district_code=district,
            valid_from="2026-09-01T00:00:00Z",
            valid_until="2027-03-01T00:00:00Z")
        return ctx, permit

    def _flag_applicant_background(self, application_id):
        check = open_and_submit_background_check(
            application_id,
            adverse_findings=[{
                "offense_category": "FELONY_OTHER",
                "offense_date": "2024-08-01T00:00:00Z",
                "disposition": "CONVICTION"}])
        assert check["status"] == "FLAGGED"
        return check

    def test_safety_gate_beats_overlap_constraint(self):
        """PRD section 3.7: "no background check of the applicant may be
        `FLAGGED` or in `ADJUDICATION` (else `ERR_BACKGROUND_HOLD`)"
        PRD section 2.5: "Incoming requests are validated against an ordered
        pipeline; a failure at an earlier stage masks all later checks, and
        the error returned is always the first one that fires."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_permit_creation
        """
        ctx, _ = self._setup_permit_context("Kim Ki", "kim@x.com")
        check = self._flag_applicant_background(ctx["application"]["id"])
        resp = api_client.create_emergency_permit(
            ctx["application"]["id"],
            {"district_code": "D01",
             "valid_from": "2026-12-01T00:00:00Z",
             "valid_until": "2027-06-01T00:00:00Z"},
            EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_BACKGROUND_HOLD)
        fetched = validate_success(
            api_client.get_background_check(check["id"], EVALUATOR))
        assert fetched["status"] == "FLAGGED"
        assert num(fetched["risk_score"]) == 60

    def test_background_hold_applies_without_any_overlap(self):
        """PRD section 3.7: "no background check of the applicant may be
        `FLAGGED` or in `ADJUDICATION` (else `ERR_BACKGROUND_HOLD`)"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_permit_creation
        """
        ctx, _ = self._setup_permit_context("Kim Kj", "kimj@x.com")
        self._flag_applicant_background(ctx["application"]["id"])
        resp = api_client.create_emergency_permit(
            ctx["application"]["id"],
            {"district_code": "D02",
             "valid_from": "2026-12-01T00:00:00Z",
             "valid_until": "2027-06-01T00:00:00Z"},
            EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_BACKGROUND_HOLD)

    def test_permit_half_open_adjacency_allowed(self):
        """PRD section 3.7: "the half-open interval from `valid_from` up to
        but not including `valid_until` must not collide with any `ISSUED` or
        `ACTIVE` permit held by the same applicant in the same district —
        touching endpoints, where the new `valid_from` equals a prior permit's
        `valid_until`, do not collide and are allowed, while any genuine
        overlap is rejected with `ERR_PERMIT_INTERVAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/permit_half_open_adjacency_allowed
        """
        ctx, permit1 = self._setup_permit_context("Pat Pa", "pat@x.com",
                                                  district="D07")
        app_id = ctx["application"]["id"]
        resp = api_client.create_emergency_permit(
            app_id,
            {"district_code": "D07",
             "valid_from": "2027-02-28T00:00:00Z",
             "valid_until": "2027-08-28T00:00:00Z"},
            EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_PERMIT_INTERVAL_OVERLAP)
        adjacent = issue_emergency_permit(
            app_id, district_code="D07",
            valid_from="2027-03-01T00:00:00Z",
            valid_until="2027-09-01T00:00:00Z")
        assert adjacent["status"] == "ISSUED"

    def test_permit_overlap_in_other_district_allowed(self):
        """PRD section 3.7: "the half-open interval from `valid_from` up to
        but not including `valid_until` must not collide with any `ISSUED` or
        `ACTIVE` permit held by the same applicant in the same district"

        Design: Difficulty/resource_temporal_overlap/permit_half_open_adjacency_allowed
        """
        ctx, _ = self._setup_permit_context("Pat Pb", "patb@x.com",
                                            district="D07")
        other_district = issue_emergency_permit(
            ctx["application"]["id"], district_code="D08",
            valid_from="2026-12-01T00:00:00Z",
            valid_until="2027-06-01T00:00:00Z")
        assert other_district["status"] == "ISSUED"

    def test_permit_duration_over_365_days_rejected(self):
        """PRD section 3.7: "the window length may not exceed 365 days (else
        `ERR_PERMIT_DURATION_EXCEEDED`)"

        Design: Corner/validations/permit_duration_over_365_days_rejected
        """
        ctx = setup_deficiency_pending_application(
            accept_plan=True, full_name="Ola Ol", email="ola@x.com")
        resp = api_client.create_emergency_permit(
            ctx["application"]["id"],
            {"district_code": "D11",
             "valid_from": "2026-09-01T00:00:00Z",
             "valid_until": "2027-09-02T00:00:00Z"},
            EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_PERMIT_DURATION_EXCEEDED)
