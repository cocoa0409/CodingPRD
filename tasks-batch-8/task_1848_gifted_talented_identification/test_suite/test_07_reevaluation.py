"""Annual re-evaluations: scheduling, activation sweep, exit bands, cascades."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_placement,
    api_client,
    assert_re_evaluation,
    conclude_re_evaluation,
    create_re_eval_conclusion_payload,
    create_re_evaluation_payload,
    create_student,
    create_transfer_honor_case,
    get_placement,
    get_re_evaluation_list,
    get_site,
    get_student,
    offer_placement,
    schedule_re_evaluation,
    set_clock,
    setup_active_placement,
    setup_active_placement_with_reeval,
    setup_full_site_with_waitlist,
    validate_error,
    validate_success,
)

GC = TEST_USERS["gifted_coordinator_headers"]


class TestReEvaluationLifecycle:
    def test_reevaluation_created_scheduled(self, api):
        """PRD §3.7: "The record starts `SCHEDULED`, and when the logical
        clock is set to a date on or after `due_on`, the clock-set sweep moves
        it `SCHEDULED` → `IN_REVIEW` automatically."

        Design: Corner/entities/reevaluation_created_scheduled
        """
        ctx = setup_active_placement()
        resp = api.create_re_evaluation(
            ctx["placement"]["id"],
            create_re_evaluation_payload(due_on="2027-05-01"),
            GC)
        re_eval = validate_success(resp, 201)
        assert_re_evaluation(re_eval)
        assert re_eval["status"] == "SCHEDULED"
        assert re_eval["outcome"] is None
        assert re_eval["exit_score"] is None

    def test_reevaluation_auto_activates_on_due_date(self, api):
        """PRD §3.7: "The record starts `SCHEDULED`, and when the logical
        clock is set to a date on or after `due_on`, the clock-set sweep moves
        it `SCHEDULED` → `IN_REVIEW` automatically."

        Design: Corner/cross_cutting_layers/reevaluation_auto_activates_on_due_date
        """
        ctx = setup_active_placement_with_reeval(due_on="2027-01-15",
                                                 activate=False)
        re_id = ctx["re_evaluation"]["id"]

        set_clock("2027-01-14T00:00:00Z")
        rows = get_re_evaluation_list(ctx["placement"]["id"])
        assert rows[0]["status"] == "SCHEDULED", (
            "one day before due_on the record must still be SCHEDULED")

        set_clock("2027-01-15T00:00:00Z")
        rows = get_re_evaluation_list(ctx["placement"]["id"])
        assert rows[0]["status"] == "IN_REVIEW", (
            "on due_on itself (inclusive) the sweep moves the record to "
            "IN_REVIEW")
        assert rows[0]["id"] == re_id


class TestConcludeGates:
    def test_reeval_conclude_before_due_rejected(self, api):
        """PRD §3.7: "Concluding is a coordinator act requiring the record in
        `IN_REVIEW` — otherwise `ERR_REEVAL_NOT_IN_REVIEW`."

        Design: Corner/validations/reeval_conclude_before_due_rejected
        """
        ctx = setup_active_placement_with_reeval(due_on="2027-05-01",
                                                 activate=False)
        resp = api.conclude_re_evaluation(
            ctx["re_evaluation"]["id"],
            create_re_eval_conclusion_payload(
                growth_percentile=80, service_rating=4, teacher_rating=5,
                outcome="RETAINED"),
            GC)
        validate_error(resp, ApiErrorId.ERR_REEVAL_NOT_IN_REVIEW.value)
        rows = get_re_evaluation_list(ctx["placement"]["id"])
        assert rows[0]["status"] == "SCHEDULED"

    def test_reeval_outcome_mismatch_rejected(self, api):
        """PRD §3.7: "The submitted `outcome` must equal the computed
        effective outcome exactly; a disagreement is rejected with
        `ERR_REEVAL_OUTCOME_MISMATCH` (HTTP 422), and nothing is written."

        Design: Corner/validations/reeval_outcome_mismatch_rejected
        """
        ctx = setup_active_placement_with_reeval(due_on="2027-01-15",
                                                 activate=True)
        # 0.5*60 + 7.5*3 + 4.0*4 = 30 + 22.5 + 16 = 68.5 -> PROBATION band.
        resp = api.conclude_re_evaluation(
            ctx["re_evaluation"]["id"],
            create_re_eval_conclusion_payload(
                growth_percentile=60, service_rating=3, teacher_rating=4,
                outcome="RETAINED"),
            GC)
        validate_error(resp, ApiErrorId.ERR_REEVAL_OUTCOME_MISMATCH.value)
        rows = get_re_evaluation_list(ctx["placement"]["id"])
        assert rows[0]["status"] == "IN_REVIEW"
        assert rows[0]["outcome"] is None
        placement = get_placement(ctx["placement"]["id"])
        assert placement["status"] == "ACTIVE"
        assert placement["is_on_probation"] is False

    def test_second_open_reeval_rejected(self, api):
        """PRD §3.7: "at most one non-`CONCLUDED` re-evaluation may exist per
        placement — a second open one is refused with
        `ERR_REEVAL_ALREADY_OPEN`."

        Design: Corner/validations/second_open_reeval_rejected
        """
        ctx = setup_active_placement_with_reeval(due_on="2027-05-01",
                                                 activate=False)
        resp = api.create_re_evaluation(
            ctx["placement"]["id"],
            create_re_evaluation_payload(due_on="2027-06-01"),
            GC)
        validate_error(resp, ApiErrorId.ERR_REEVAL_ALREADY_OPEN.value)


class TestExitScoreBands:
    def test_exit_score_band_boundaries(self, api):
        """PRD §3.7: "The band is then: an exit score of 70.0 or higher means
        `RETAINED`; an exit score of 50.0 or higher but below 70.0 means
        `PROBATION` — exactly 50.0 is `PROBATION`; below 50.0 means
        `EXITED`."
        PRD §3.7: "The server computes the **exit score** as follows:
        multiply `growth_percentile` by 0.5, multiply `service_rating` by
        7.5, multiply `teacher_rating` by 4.0, sum the three products, and
        round half-up to one decimal place".

        Design: Corner/calculations/exit_score_band_boundaries
        """
        ctx_x = setup_active_placement_with_reeval(
            due_on="2027-01-15", activate=False,
            student_overrides={"student_number": "ST-X", "legal_name": "Stu X",
                               "primary_guardian_user_id": "guard-x"})
        # Second placement for student Y on the CLUSTER model of the same site
        # (PULL_OUT capacity 5 leaves room; using a different model keeps the
        # occupancy domains independent).
        ctx_y = {}
        site = ctx_x["site"]
        cycle = ctx_x["cycle"]
        stu_y = create_student(site["id"], student_number="ST-Y",
                               legal_name="Stu Y", grade_level=3,
                               demographic_group="BLACK",
                               primary_guardian_user_id="guard-y")
        case_y = create_transfer_honor_case(stu_y["id"], cycle["id"])
        plc_y = offer_placement(case_y["id"], site["id"], "CLUSTER")
        accept_placement(plc_y["id"], "guard-y")
        re_y = schedule_re_evaluation(plc_y["id"], "2027-01-15")

        set_clock("2027-01-15T00:00:00Z")
        # 0.5*54 + 7.5*2 + 4.0*2 = 27 + 15 + 8 = 50.0 -> PROBATION (inclusive).
        rx = conclude_re_evaluation(ctx_x["re_evaluation"]["id"],
                                    54, 2, 2, "PROBATION")
        assert float(rx["exit_score"]) == 50.0
        assert rx["outcome"] == "PROBATION"
        assert rx["status"] == "CONCLUDED"
        plc_x_after = get_placement(ctx_x["placement"]["id"])
        assert plc_x_after["status"] == "ACTIVE"
        assert plc_x_after["is_on_probation"] is True

        # 0.5*48 + 7.5*4 + 4.0*4 = 24 + 30 + 16 = 70.0 -> RETAINED (inclusive).
        ry = conclude_re_evaluation(re_y["id"], 48, 4, 4, "RETAINED")
        assert float(ry["exit_score"]) == 70.0
        assert ry["outcome"] == "RETAINED"
        plc_y_after = get_placement(plc_y["id"])
        assert plc_y_after["status"] == "ACTIVE"
        assert plc_y_after["is_on_probation"] is False


class TestProbationRepeat:
    def test_first_probation_flags_placement_but_keeps_active(self, api):
        """PRD §3.7: "`PROBATION` sets the placement's `is_on_probation` to
        true while it stays `ACTIVE`."

        Design: Difficulty/combinatorial_formula/exit_score_probation_repeat_forces_exit
        """
        ctx = setup_active_placement_with_reeval(due_on="2027-01-15",
                                                 activate=True)
        re1 = conclude_re_evaluation(ctx["re_evaluation"]["id"],
                                     60, 3, 4, "PROBATION")
        # 0.5*60 + 7.5*3 + 4.0*4 = 30 + 22.5 + 16 = 68.5 -> PROBATION band.
        assert float(re1["exit_score"]) == 68.5
        assert re1["outcome"] == "PROBATION"
        assert re1["status"] == "CONCLUDED"
        placement = get_placement(ctx["placement"]["id"])
        assert placement["is_on_probation"] is True
        assert placement["status"] == "ACTIVE"

    def test_second_consecutive_probation_forces_exit(self, api):
        """PRD §3.7: "One state-dependent override applies: if the banded
        outcome is `PROBATION` but the placement's `is_on_probation` flag is
        already true — a second consecutive probation — the effective outcome
        is `EXITED` instead."
        PRD §3.7: "`EXITED` runs the full exit cascade of §3.6 in the same
        request: the placement moves `ACTIVE` → `EXITED` with `end_on` set to
        today, the student's `gifted_status` becomes `EXITED`".

        Design: Difficulty/combinatorial_formula/exit_score_probation_repeat_forces_exit
        """
        ctx = setup_active_placement_with_reeval(due_on="2027-01-15",
                                                 activate=True)
        conclude_re_evaluation(ctx["re_evaluation"]["id"], 60, 3, 4,
                               "PROBATION")
        re2 = schedule_re_evaluation(ctx["placement"]["id"], "2027-06-01")
        set_clock("2027-06-01T00:00:00Z")
        # 0.5*45 + 7.5*3 + 4.0*3 = 22.5 + 22.5 + 12 = 57.0 -> PROBATION band,
        # overridden to EXITED because the placement is already on probation.
        concluded = conclude_re_evaluation(re2["id"], 45, 3, 3, "EXITED")
        assert float(concluded["exit_score"]) == 57.0
        assert concluded["outcome"] == "EXITED"
        placement = get_placement(ctx["placement"]["id"])
        assert placement["status"] == "EXITED"
        assert placement["end_on"] == "2027-06-01"
        assert get_student(ctx["student"]["id"])["gifted_status"] == "EXITED"


class TestExitCascade:
    def test_reeval_exit_cascades_seat_release(self, api):
        """PRD §3.7: "`EXITED` runs the full exit cascade of §3.6 in the same
        request: the placement moves `ACTIVE` → `EXITED` with `end_on` set to
        today, the student's `gifted_status` becomes `EXITED`, the site's
        occupied counter for the model decrements by one, and waitlist
        promotion runs for the site-and-model pair."

        Design: Difficulty/transitive_cascade/reeval_exit_cascades_seat_release_and_promotion
        """
        ctx = setup_full_site_with_waitlist(capacity=1)
        re1 = schedule_re_evaluation(ctx["pa"]["id"], "2027-01-15")
        set_clock("2027-01-15T00:00:00Z")
        # 0.5*30 + 7.5*2 + 4.0*3 = 15 + 15 + 12 = 42.0 -> below 50 -> EXITED.
        concluded = conclude_re_evaluation(re1["id"], 30, 2, 3, "EXITED")
        assert float(concluded["exit_score"]) == 42.0
        assert concluded["outcome"] == "EXITED"
        assert concluded["status"] == "CONCLUDED"

        pa = get_placement(ctx["pa"]["id"])
        assert pa["status"] == "EXITED"
        assert pa["end_on"] == "2027-01-15"
        assert get_student(ctx["stu_a"]["id"])["gifted_status"] == "EXITED"
        assert get_site(ctx["site"]["id"])["pull_out_occupied"] == 0

    def test_reeval_exit_promotes_waitlist_head(self, api):
        """PRD §3.7: "`EXITED` runs the full exit cascade of §3.6 in the same
        request ... and waitlist promotion runs for the site-and-model pair."
        PRD §3.6: "it re-enters `OFFERED` with `offered_on` set to today, a
        fresh `accept_by` of today plus 30 days, and `waitlisted_at` nulled."

        Design: Difficulty/transitive_cascade/reeval_exit_cascades_seat_release_and_promotion
        """
        ctx = setup_full_site_with_waitlist(capacity=1)
        re1 = schedule_re_evaluation(ctx["pa"]["id"], "2027-01-15")
        set_clock("2027-01-15T00:00:00Z")
        conclude_re_evaluation(re1["id"], 30, 2, 3, "EXITED")
        pb = get_placement(ctx["pb"]["id"])
        assert pb["status"] == "OFFERED", (
            "the seat released by the exit promotes the waitlist head")
        assert pb["offered_on"] == "2027-01-15"
        assert pb["accept_by"] == "2027-02-14"
        assert pb["waitlisted_at"] is None
