"""Training advancement dual-variant divergence and cyclic state machines
(PRD §3.1, §3.6, §3.8)."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_applicant_with_accepted_assessment,
    create_approved_raiser,
    create_certified_trainer,
    create_cleared_dog,
    create_dog_in_advanced_training,
    create_eligible_entry,
    create_match_ready_dog,
    make_applicant_headers,
    propose_and_accept_match,
    record_milestone,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
COORD_B = TEST_USERS["coordinator_b_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
TD = TEST_USERS["training_director_headers"]


class TestRollingVsCumulativeDivergence:
    """Difficulty/dual_variant_calc/training_advancement_rolling_vs_cumulative_divergence."""

    def _dog_with_five_history(self):
        """95 TW, 90 TW, 88 PM, 85 OB, 82 SOC already recorded."""
        dog, _raiser, trainer, _pl = create_dog_in_advanced_training()
        for category, score, task in [
            ("TASK_WORK", 95, "RETRIEVE_ITEMS"),
            ("TASK_WORK", 90, "OPEN_DOORS"),
            ("PUBLIC_MANNERS", 88, None),
            ("OBEDIENCE", 85, None),
            ("SOCIALIZATION", 82, None),
        ]:
            record_milestone(dog["id"], trainer["id"], category, score, task)
        return dog, trainer

    def test_sixth_milestone_rolling_window_blocks_advancement(self, api):
        """PRD §3.6: "`rolling_avg_3` is the mean of the latest three milestone
        scores in chronological order — fewer when the dog has fewer than three
        — rounded half-up to 1 decimal place; this is the progress readout
        surfaced on each milestone response, and because it looks only at the
        recent window, a strong early history cannot rescue a recent dip."
        PRD §3.6: "A dog in `IN_ADVANCED_TRAINING` moves to `MATCH_READY` when
        all five gates hold: at least 6 milestones recorded;
        `cumulative_gate_score` at least 80.0; `rolling_avg_3` at least 70.0;
        no score below 40 among the latest three milestones; and at most one
        recorded milestone in total with a score below 50."

        Sixth score 41 -> rolling (85+82+41)/3 = 69.3 < 70 -> no advancement.

        Design: Difficulty/dual_variant_calc/training_advancement_rolling_vs_cumulative_divergence
        """
        dog, trainer = self._dog_with_five_history()
        sixth = record_milestone(
            dog["id"], trainer["id"], "TASK_WORK", 41, "RETRIEVE_ITEMS"
        )
        assert sixth["rolling_avg_3"] == pytest.approx(69.3, abs=0.01), (
            f"(85+82+41)/3 rounds to 69.3, got {sixth['rolling_avg_3']}"
        )
        dog_now = validate_success(api.get_dog(dog["id"], TD))
        assert dog_now["status"] == "IN_ADVANCED_TRAINING"

    def test_sixth_milestone_cumulative_gate_would_pass(self, api):
        """PRD §3.6: "`cumulative_gate_score` is a category-weighted mean over
        all of the dog's milestones: half the weight on the mean of all
        `TASK_WORK` scores, three-tenths on the mean of all `PUBLIC_MANNERS`
        scores, and two-tenths on the mean of all `OBEDIENCE` and
        `SOCIALIZATION` scores combined."
        PRD §3.6: "Separately, every `TASK_WORK` milestone scoring at least 80
        adds its `task_code` to the dog's `certified_tasks` set — this set is
        what match proposals check task coverage against."

        0.5*(226/3) + 0.3*88 + 0.2*83.5 = 80.7667 -> 80.8 >= 80: cumulative
        gate satisfied while rolling fails; certified tasks hold the >= 80
        TASK_WORK codes.

        Design: Difficulty/dual_variant_calc/training_advancement_rolling_vs_cumulative_divergence
        """
        dog, trainer = self._dog_with_five_history()
        sixth = record_milestone(
            dog["id"], trainer["id"], "TASK_WORK", 41, "RETRIEVE_ITEMS"
        )
        assert sixth["cumulative_gate_score"] == pytest.approx(80.8, abs=0.01), (
            f"weighted mean rounds to 80.8, got {sixth['cumulative_gate_score']}"
        )
        dog_now = validate_success(api.get_dog(dog["id"], TD))
        assert "RETRIEVE_ITEMS" in dog_now["certified_tasks"]
        assert "OPEN_DOORS" in dog_now["certified_tasks"]


class TestApplicantInfoRequestCycle:
    """Difficulty/non_linear_state_machine/applicant_info_request_cycle."""

    def test_needs_info_resubmit_cycle_runs_twice(self, api):
        """PRD §3.1: "If the file is incomplete, the coordinator requests more
        information — supplying an `info_request_note` — moving the applicant
        from `IN_REVIEW` to `NEEDS_INFO`. The applicant themselves then
        resubmits, which returns the application from `NEEDS_INFO` to
        `IN_REVIEW`; a resubmission by anyone other than that applicant is
        rejected with `ERR_OWNERSHIP_SCOPE`."

        The loop executes twice with no loop counter.

        Design: Difficulty/non_linear_state_machine/applicant_info_request_cycle
        """
        applicant, _a = create_applicant_with_accepted_assessment()
        applicant_h = make_applicant_headers(applicant["id"])
        r1 = validate_success(
            api.request_info(applicant["id"], {"info_request_note": "need medical letter"}, COORD)
        )
        assert r1["application_status"] == "NEEDS_INFO"
        r2 = validate_success(api.resubmit_applicant(applicant["id"], applicant_h))
        assert r2["application_status"] == "IN_REVIEW"
        r3 = validate_success(
            api.request_info(applicant["id"], {"info_request_note": "need landlord OK"}, COORD)
        )
        assert r3["application_status"] == "NEEDS_INFO"
        r4 = validate_success(api.resubmit_applicant(applicant["id"], applicant_h))
        assert r4["application_status"] == "IN_REVIEW"

    def test_approve_after_cycle_creates_pending_entry(self, api):
        """PRD §3.1: "Approval stamps `approved_by_user_id` with the acting
        operator id, moves the applicant to `WAITLISTED`, and creates the
        waitlist entry described in §3.2."
        PRD §3.2: "Approval creates a `WaitlistEntry` with `status` `PENDING`,
        `listed_at` set to the logical-clock timestamp, `raised_cents` 0."

        Design: Difficulty/non_linear_state_machine/applicant_info_request_cycle
        """
        applicant, _a = create_applicant_with_accepted_assessment()
        applicant_h = make_applicant_headers(applicant["id"])
        validate_success(
            api.request_info(applicant["id"], {"info_request_note": "x"}, COORD)
        )
        validate_success(api.resubmit_applicant(applicant["id"], applicant_h))
        approved = validate_success(api.approve_applicant(applicant["id"], COORD))
        assert approved["application_status"] == "WAITLISTED"
        entries = validate_success(
            api.list_applicant_waitlist_entries(applicant["id"], COORD)
        )
        assert isinstance(entries, list) and len(entries) == 1
        assert entries[0]["status"] == "PENDING"


class TestDogRaiserRecallCycle:
    """Difficulty/non_linear_state_machine/dog_raiser_recall_cycle_and_match_revert."""

    def test_recall_then_replace_cycles_dog_and_raiser_count(self, api):
        """PRD §3.6: "Early return — available to a `TrainingDirector` ... —
        moves the placement to `EARLY_RETURN` and recalls the dog from
        `RAISER_PLACED` to `RECALLED`, with the same raiser count and timestamp
        effects. A recalled dog can be placed again through the same creation
        flow."

        RAISER_PLACED -> RECALLED -> RAISER_PLACED cycle; raiser count returns
        to 0 after completion.

        Design: Difficulty/non_linear_state_machine/dog_raiser_recall_cycle_and_match_revert
        """
        dog = create_cleared_dog()
        raiser = create_approved_raiser(foster_capacity=2)
        trainer = create_certified_trainer()
        pl1 = validate_success(
            api.create_raiser_placement(
                dog["id"], {"puppy_raiser_id": raiser["id"]}, TD
            ),
            expected_status=201,
        )
        returned = validate_success(api.early_return_raiser_placement(pl1["id"], TD))
        assert returned["status"] == "EARLY_RETURN"
        dog_now = validate_success(api.get_dog(dog["id"], TD))
        assert dog_now["status"] == "RECALLED"
        pl2 = validate_success(
            api.create_raiser_placement(
                dog["id"], {"puppy_raiser_id": raiser["id"]}, TD
            ),
            expected_status=201,
        )
        assert pl2["status"] == "ACTIVE"
        dog_now = validate_success(api.get_dog(dog["id"], TD))
        assert dog_now["status"] == "RAISER_PLACED"
        validate_success(
            api.complete_raiser_placement(
                pl2["id"], {"primary_trainer_id": trainer["id"]}, TD
            )
        )
        raiser_now = validate_success(api.get_puppy_raiser(raiser["id"], ADMIN))
        assert raiser_now["current_dog_count"] == 0

    def test_match_dissolve_reverts_dog_to_match_ready(self, api):
        """PRD §3.7: "Dissolving an `ACCEPTED` match — by an `IntakeCoordinator`
        directly, or by the career-change, withdrawal, enrollment-withdrawal,
        and PAT-fail cascades — reverts the dog from `MATCHED` to
        `MATCH_READY` ..., reverts the entry from `MATCHED` to `ELIGIBLE` while
        incrementing `dissolved_match_count` and recomputing `rank_score`, and
        moves the applicant from `MATCHED` to `MATCH_ELIGIBLE`."

        Design: Difficulty/non_linear_state_machine/dog_raiser_recall_cycle_and_match_revert
        """
        dog, _raiser, _trainer = create_match_ready_dog()
        assert dog["status"] == "MATCH_READY"
        applicant, entry, _c = create_eligible_entry()
        match = propose_and_accept_match(dog, entry)
        dog_now = validate_success(api.get_dog(dog["id"], TD))
        assert dog_now["status"] == "MATCHED"
        dissolved = validate_success(api.dissolve_match(match["id"], COORD))
        assert dissolved["status"] == "DISSOLVED"
        dog_now = validate_success(api.get_dog(dog["id"], TD))
        assert dog_now["status"] == "MATCH_READY"
        entry_now = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert entry_now["status"] == "ELIGIBLE"
        assert entry_now["dissolved_match_count"] == 1


class TestPartnershipRecertCycle:
    """Difficulty/non_linear_state_machine/partnership_recert_cycle."""

    def _graduated(self):
        from test_helpers import setup_graduated_partnership
        return setup_graduated_partnership()

    def test_clock_sweep_moves_partnership_to_recert_due(self, api):
        """PRD §2.8: "Two transitions fire during the sweep: a `FollowUp`
        still `SCHEDULED` whose current logical date is more than 7 days past
        its `due_on` becomes `MISSED`; and a `Partnership` in `ACTIVE` whose
        current logical date is later than its `recert_due_at` with no
        `COMPLETED_PASS` recertification recorded since activation becomes
        `RECERT_DUE`."

        Graduated 2026-10-16 -> recert due 2027-10-16; sweep at 2027-10-17.

        Design: Difficulty/non_linear_state_machine/partnership_recert_cycle
        """
        ctx = self._graduated()
        partnership = ctx["partnership"]
        validate_success(
            api.set_clock({"to_iso8601": "2027-10-17T00:00:00Z"}, ADMIN)
        )
        now = validate_success(api.get_partnership(partnership["id"], TD))
        assert now["status"] == "RECERT_DUE"

    def test_recert_pass_closes_cycle_and_reschedules(self, api):
        """PRD §3.8: "A `PASS` from `SCHEDULED` or `REMEDIATION` moves the
        recertification to the terminal `COMPLETED_PASS`, stamps `completed_on`
        with the logical date, moves the partnership from `RECERT_DUE` back to
        `ACTIVE` (or keeps an `ACTIVE` partnership active), resets
        `recert_due_at` to `completed_on` plus 365 days, and records the
        completion timestamp as `last_recert_passed_at`."

        completed_on 2027-10-20 + 365 days = 2028-10-19 (leap year).

        Design: Difficulty/non_linear_state_machine/partnership_recert_cycle
        """
        from test_helpers import assert_date_prefix, make_evaluator_headers
        ctx = self._graduated()
        partnership = ctx["partnership"]
        evaluator = ctx["evaluator"]
        validate_success(
            api.set_clock({"to_iso8601": "2027-10-17T00:00:00Z"}, ADMIN)
        )
        current = validate_success(api.get_partnership(partnership["id"], TD))
        recert = validate_success(
            api.create_recertification(
                partnership["id"],
                {
                    "scheduled_on": "2027-10-20",
                    "evaluator_id": evaluator["id"],
                    "expected_partnership_version": current["version"],
                },
                TD,
            ),
            expected_status=201,
        )
        validate_success(
            api.set_clock({"to_iso8601": "2027-10-20T00:00:00Z"}, ADMIN)
        )
        done = validate_success(
            api.record_recert_result(
                recert["id"],
                {"outcome": "PASS"},
                make_evaluator_headers(evaluator["id"]),
            )
        )
        assert done["status"] == "COMPLETED_PASS"
        after = validate_success(api.get_partnership(partnership["id"], TD))
        assert after["status"] == "ACTIVE"
        assert_date_prefix(after["recert_due_at"], "2028-10-19", "recert_due_at")
        assert after["last_recert_passed_at"] is not None
