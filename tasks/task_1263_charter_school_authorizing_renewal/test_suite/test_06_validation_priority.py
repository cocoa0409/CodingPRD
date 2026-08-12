"""Validation-layer ordering conflicts (PRD §2.9) and existence checks."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    NON_EXISTENT_UUID, CLOCK,
    create_application_under_review, post_full_rubric, create_score_payload,
    create_interview_payload, setup_renewal_ready_school, create_renewal_decision,
    file_school_appeal, schedule_appeal_hearing, rule_appeal, set_clock,
    make_staff_headers, make_board_headers, make_reviewer_headers,
    make_school_operator_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


def _reverted_decision_context():
    """Renewal decision DECIDED DENIED then REVERTED via an overturned appeal;
    clock moved past the original appeal window."""
    ctx = setup_renewal_ready_school(school_name="PP Appeal Academy",
                                     applicant_id="applicant_pp1")
    decision = create_renewal_decision(ctx["school"]["id"], ctx["contract"]["id"])
    validate_success(api_client.decide_renewal(
        decision["id"], {"outcome": "DENIED"}, make_board_headers("board_1")), 200)
    appeal = file_school_appeal(ctx["school"]["id"], "RENEWAL_DENIAL",
                                decision["id"], grounds="Procedural defect")
    schedule_appeal_hearing(appeal["id"], "officer_pp1")
    rule_appeal(appeal["id"], "officer_pp1", "OVERTURNED")
    set_clock("2032-03-01T00:00:00Z")
    return ctx, decision, appeal


class TestAppealStateBeatsTemporal:
    def test_reverted_target_and_expired_window_yield_not_appealable(self, api):
        """PRD §2.9: "Incoming requests are checked against a fixed sequence of
        validation layers, and the first failing layer determines the error
        returned."
        PRD §3.9: "The target must exist, match the declared type, and sit in
        an appealable state — the application must be `DENIED`, the renewal
        decision `DECIDED`, the contract `REVOKED`, and the invoice `FINALIZED`
        or `DISPUTED` — otherwise `ERR_TARGET_NOT_APPEALABLE`."

        Design: Difficulty/priority_pair_validation_conflict/appeal_state_beats_temporal
        """
        ctx, decision, _appeal = _reverted_decision_context()
        current = validate_success(api.get_renewal_decision(decision["id"], STAFF), 200)
        assert current["status"] == "REVERTED"
        # Clock is also past decided_at + 30 days: the state-layer error must win.
        res = api.file_appeal(
            {"target_type": "RENEWAL_DENIAL", "target_id": decision["id"],
             "grounds": "Second appeal too late and target reverted",
             "school_id": ctx["school"]["id"]},
            make_school_operator_headers(ctx["school"]["id"]))
        validate_error(res, ApiErrorId.ERR_TARGET_NOT_APPEALABLE, expected_status=409)

    def test_rejected_second_appeal_leaves_decision_and_appeal_count_untouched(self, api):
        """PRD §2.9: "then state preconditions (the various invalid-state
        conflicts, plus `ERR_TARGET_NOT_APPEALABLE` and `ERR_SCHOOL_NOT_OPEN`),
        then segregation-of-duties and panel-integrity rules, then
        temporal-window rules, then constraint and aggregate rules, and finally
        the fiscal guards."

        Design: Difficulty/priority_pair_validation_conflict/appeal_state_beats_temporal
        """
        ctx, decision, first_appeal = _reverted_decision_context()
        res = api.file_appeal(
            {"target_type": "RENEWAL_DENIAL", "target_id": decision["id"],
             "grounds": "Second appeal too late and target reverted",
             "school_id": ctx["school"]["id"]},
            make_school_operator_headers(ctx["school"]["id"]))
        assert res.status_code == 409  # not the 422 of ERR_APPEAL_WINDOW_EXPIRED
        appeals = validate_success(
            api.list_appeals(STAFF, params={"school_id": ctx["school"]["id"]}), 200)
        assert len(appeals) == 1 and appeals[0]["id"] == first_appeal["id"]
        current = validate_success(api.get_renewal_decision(decision["id"], STAFF), 200)
        assert current["status"] == "REVERTED"


class TestInterviewSodBeatsOverlap:
    def _conflict_context(self):
        app_a = create_application_under_review(school_name="PP SOD Academy A",
                                                applicant_id="applicant_pp2")
        get_success_data(api_client.post_application_score(
            app_a["id"], create_score_payload(criterion="ACADEMIC_PLAN", score=80),
            make_reviewer_headers("rev_sod")))
        app_b = create_application_under_review(school_name="PP SOD Academy B",
                                                applicant_id="applicant_pp2")
        get_success_data(api_client.schedule_interview(
            app_b["id"],
            create_interview_payload(scheduled_start="2026-06-01T10:00:00Z",
                                     scheduled_end="2026-06-01T11:00:00Z",
                                     panelist_user_ids=["rev_busy"]),
            STAFF))
        return app_a, app_b

    def test_panelist_scorer_conflict_wins_over_time_overlap(self, api):
        """PRD §2.8: "No one who scored an application's rubric may sit on its
        capacity-interview panel: at scheduling time, none of the
        `panelist_user_ids` may appear as a `reviewer_user_id` in the
        application's `review_scores`. A conflict is rejected with
        `ERR_SOD_REVIEWER_PANEL_CONFLICT` (HTTP 403)."
        PRD §2.9: "then segregation-of-duties and panel-integrity rules, then
        temporal-window rules"

        Design: Difficulty/priority_pair_validation_conflict/interview_sod_beats_overlap
        """
        app_a, _app_b = self._conflict_context()
        # rev_sod scored app A (SOD conflict); rev_busy overlaps (temporal).
        res = api.schedule_interview(
            app_a["id"],
            {"scheduled_start": "2026-06-01T10:30:00Z",
             "scheduled_end": "2026-06-01T11:30:00Z",
             "panelist_user_ids": ["rev_sod", "rev_busy"]},
            STAFF)
        validate_error(res, ApiErrorId.ERR_SOD_REVIEWER_PANEL_CONFLICT,
                       expected_status=403)

    def test_rejected_schedule_creates_no_interview(self, api):
        """PRD §2.9: "Incoming requests are checked against a fixed sequence of
        validation layers, and the first failing layer determines the error
        returned."
        PRD §3.1: "Scheduling the capacity interview is a staff action
        providing `scheduled_start`, `scheduled_end`, and the
        `panelist_user_ids` who will sit the panel; the new interview records
        its `application_id` and begins life `SCHEDULED` with `panel_score`
        null."

        Design: Difficulty/priority_pair_validation_conflict/interview_sod_beats_overlap
        """
        app_a, _app_b = self._conflict_context()
        res = api.schedule_interview(
            app_a["id"],
            {"scheduled_start": "2026-06-01T10:30:00Z",
             "scheduled_end": "2026-06-01T11:30:00Z",
             "panelist_user_ids": ["rev_sod", "rev_busy"]},
            STAFF)
        assert res.status_code == 403  # not the 409 of ERR_PANEL_TIME_OVERLAP
        interviews = validate_success(api.list_interviews(app_a["id"], STAFF), 200)
        assert interviews == []


class TestExistenceBeatsState:
    def test_decide_on_nonexistent_application_returns_not_found(self, api):
        """PRD §2.9: "then existence of every resource named in the path —
        validated left to right, so the first missing id yields `ERR_NOT_FOUND`
        (HTTP 404) — then `SchoolOperator` ownership, then
        optimistic-concurrency version checks, then state preconditions"

        Design: Corner/validations/val_existence_beats_state_on_decide
        """
        res = api.decide_application(NON_EXISTENT_UUID, {"outcome": "APPROVED"},
                                     make_board_headers("board_1"))
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
