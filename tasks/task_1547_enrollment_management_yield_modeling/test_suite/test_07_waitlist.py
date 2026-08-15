"""Waitlist entry creation, ranked activation, tie-breaking, empty pool,
withdrawal cascades, and the intake-pause admission gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_cycle,
    advance_cycle_to_decisions_released,
    assign_and_submit_review,
    assign_review,
    create_admitted_application,
    create_application_for_new_applicant,
    create_waitlisted_application,
    get_waitlist_entry_for_application,
    make_applicant_headers,
    pay_deposit,
    refresh_application,
    refresh_program,
    set_clock,
    setup_open_cycle_with_program,
    transition_application,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["enrollment_manager_headers"]
OFFICER = TEST_USERS["admissions_officer_headers"]


class TestWaitlistEntryCreation:
    def test_waitlist_entry_created_by_waitlist_decision(self, api):
        """PRD 3.8: "A waitlist entry is born only from the waitlist decision
        of §3.4: the entry records the `application_id`, denormalizes the
        `program_id` from the application at creation, and computes its
        `rank_score` once, at entry creation."
        PRD 3.8: "The rank score is six-tenths of the application's
        `academic_score` plus four-tenths of its recommendation strength,
        where recommendation strength is one hundred times the share of the
        application's submitted reads carrying an `ADMIT` recommendation"
        PRD 3.8: "The entry begins in `ACTIVE`"

        Design: Corner/state_machines/waitlist_entry_created_by_waitlist_decision
        """
        setup = setup_open_cycle_with_program(name="WLE", capacity_seats=4,
                                              target_enrollment=2)
        pair = create_waitlisted_application(setup["cycle"]["id"],
                                             setup["program"]["id"],
                                             academic_score=80)
        entry = pair["entry"]
        assert entry["status"] == "ACTIVE"
        assert entry["application_id"] == pair["application"]["id"]
        assert entry["program_id"] == setup["program"]["id"], \
            "program_id is denormalized from the application at creation"
        assert entry["rank_score"] == pytest.approx(88.0, abs=1e-6), \
            "0.6*80 + 0.4*100 (two ADMIT reads of two) = 88.0"


class TestRankScore:
    def test_waitlist_rank_mixed_recommendations(self, api):
        """PRD 3.8: "The rank score is six-tenths of the application's
        `academic_score` plus four-tenths of its recommendation strength,
        where recommendation strength is one hundred times the share of the
        application's submitted reads carrying an `ADMIT` recommendation —
        that is, the count of `SUBMITTED` reviews whose `recommendation` is
        `ADMIT` divided by the total count of `SUBMITTED` reviews, multiplied
        by one hundred, and defined as 0 when the application has no
        submitted reads."

        Design: Corner/calculations/waitlist_rank_mixed_recommendations
        """
        setup = setup_open_cycle_with_program(name="MIX", capacity_seats=5,
                                              target_enrollment=3)
        pair = create_waitlisted_application(
            setup["cycle"]["id"], setup["program"]["id"], academic_score=80,
            recommendations=("ADMIT", "DENY"))
        assert pair["entry"]["rank_score"] == pytest.approx(68.0, abs=1e-6), \
            "0.6*80 + 0.4*(100*1/2) = 68.0 — only SUBMITTED reads count"


class TestManualActivation:
    def test_waitlist_activation_empty_pool_rejected(self, api):
        """PRD 3.8: "The selector ranks the pool by `rank_score` descending,
        breaking ties by the underlying application's `submitted_at`
        ascending — earlier filers win — and an empty pool is rejected with
        `ERR_WAITLIST_EMPTY`."

        Design: Corner/state_machines/waitlist_activation_empty_pool_rejected
        """
        setup = setup_open_cycle_with_program(name="EMP", capacity_seats=4,
                                              target_enrollment=2)
        advance_cycle_to_decisions_released(setup["cycle"]["id"])
        resp = api.activate_waitlist(setup["program"]["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_WAITLIST_EMPTY)

    def test_manual_waitlist_activation_rank_order(self, api):
        """PRD 3.8: "The selector ranks the pool by `rank_score` descending,
        breaking ties by the underlying application's `submitted_at`
        ascending — earlier filers win"
        PRD 3.8: "Activation moves the selected entry from `ACTIVE` to
        `ACTIVATED`, moves its application from `WAITLISTED` to `ADMITTED`,
        increments the program's `admitted_count` by one, and re-derives
        posture."

        Design: Corner/state_machines/manual_waitlist_activation_rank_order
        """
        setup = setup_open_cycle_with_program(name="RANK", capacity_seats=5,
                                              target_enrollment=3)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        first = create_waitlisted_application(cycle_id, program_id,
                                              academic_score=80)  # 88.0
        second = create_waitlisted_application(cycle_id, program_id,
                                               academic_score=75)  # 85.0
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")

        top = validate_success(api.activate_waitlist(program_id, MANAGER))
        assert top["id"] == first["entry"]["id"], \
            "Rank 88.0 activates before rank 85.0"
        assert top["status"] == "ACTIVATED"
        first_app = refresh_application(first["application"]["id"])
        assert first_app["status"] == "ADMITTED"

        second_activation = validate_success(
            api.activate_waitlist(program_id, MANAGER))
        assert second_activation["id"] == second["entry"]["id"], \
            "The second activation takes the remaining pool head"

        program = refresh_program(program_id)
        assert program["admitted_count"] == 2

    def test_waitlist_tie_break_earliest_submitted(self, api):
        """PRD 3.8: "The selector ranks the pool by `rank_score` descending,
        breaking ties by the underlying application's `submitted_at`
        ascending — earlier filers win"
        PRD 2.4: "Creation timestamps stamped by the system — an
        application's `submitted_at`, a deposit's `paid_at`, a review's
        `submitted_at` — are all taken from this logical clock."

        Design: Corner/state_machines/waitlist_tie_break_earliest_submitted
        """
        set_clock("2026-08-01T00:00:00Z")
        setup = setup_open_cycle_with_program(name="TIE", capacity_seats=5,
                                              target_enrollment=3)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]

        early = create_waitlisted_application(cycle_id, program_id,
                                              academic_score=80)
        set_clock("2026-08-02T00:00:00Z")
        late = create_waitlisted_application(cycle_id, program_id,
                                             academic_score=80)

        assert early["entry"]["rank_score"] == pytest.approx(88.0, abs=1e-6)
        assert late["entry"]["rank_score"] == pytest.approx(88.0, abs=1e-6)
        assert early["application"]["submitted_at"] < \
            late["application"]["submitted_at"], \
            "The two filings carry distinct logical-clock submission instants"

        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")
        top = validate_success(api.activate_waitlist(program_id, MANAGER))
        assert top["application_id"] == early["application"]["id"], \
            "Equal rank: the earlier submission wins the tie"
        early_app = refresh_application(early["application"]["id"])
        assert early_app["status"] == "ADMITTED"
        late_app = refresh_application(late["application"]["id"])
        assert late_app["status"] == "WAITLISTED"
        late_entry = get_waitlist_entry_for_application(
            late["application"]["id"])
        assert late_entry["status"] == "ACTIVE"


class TestIntakePauseGate:
    def test_intake_paused_blocks_admission(self, api):
        """PRD 3.4: "Admitting requires two cross-entity gates: the program's
        `intake_posture` must be `OPEN` (a `PAUSED` or `CLOSED` posture
        yields `ERR_INTAKE_PAUSED`)"
        PRD 2.6: "The posture flips to `PAUSED` the moment the
        deposited-plus-enrolled sum reaches or exceeds the target."

        Design: Corner/state_machines/intake_paused_blocks_admission
        """
        setup = setup_open_cycle_with_program(name="PAU", capacity_seats=1,
                                              target_enrollment=1)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair_a = create_admitted_application(cycle_id, program_id,
                                             academic_score=80)
        pair_b = create_application_for_new_applicant(
            cycle_id, program_id, academic_score=81)
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(pair_a["application"], pair_a["applicant"])

        # Drive B to DECISION_PENDING after the pause takes effect.
        transition_application(pair_b["application"]["id"], "IN_REVIEW")
        assign_and_submit_review(pair_b["application"]["id"], "reader-1",
                                 score=81)
        assign_and_submit_review(pair_b["application"]["id"], "reader-2",
                                 score=81)
        transition_application(pair_b["application"]["id"], "DECISION_PENDING")

        resp = api.transition_application(pair_b["application"]["id"],
                                          "ADMITTED", OFFICER)
        validate_error(resp, ApiErrorId.ERR_INTAKE_PAUSED)
        app_b = refresh_application(pair_b["application"]["id"])
        assert app_b["status"] == "DECISION_PENDING"
        program = refresh_program(program_id)
        assert program["intake_posture"] == "PAUSED"


class TestWithdrawCascades:
    def test_application_withdraw_cascades(self, api):
        """PRD 3.4: "Withdrawing from `COMMITTEE_REVIEW` or
        `DECISION_PENDING` also cancels every still-`ASSIGNED` review on the
        application."
        PRD 3.8: "a manual move from `WAITLISTED` to `DENIED` moves its
        `ACTIVE` entry to `REMOVED`, as does the applicant's own withdrawal
        from `WAITLISTED`"

        Design: Corner/state_machines/application_withdraw_cascades
        """
        setup = setup_open_cycle_with_program(name="WDC", capacity_seats=5,
                                              target_enrollment=3)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]

        in_committee = create_application_for_new_applicant(
            cycle_id, program_id, academic_score=80)
        transition_application(in_committee["application"]["id"], "IN_REVIEW")
        # Distinct reader id: PRD 3.4 forbids overlapping ASSIGNED windows for
        # the same reader, and create_waitlisted_application below drives its
        # own reads through reader-1/reader-2 with the default window.
        review = assign_review(in_committee["application"]["id"],
                               "reader-committee")

        waitlisted = create_waitlisted_application(cycle_id, program_id,
                                                   academic_score=75)

        withdrawn_one = transition_application(
            in_committee["application"]["id"], "WITHDRAWN")
        assert withdrawn_one["status"] == "WITHDRAWN"
        review_after = validate_success(api.get_review(review["id"], OFFICER))
        assert review_after["status"] == "CANCELLED", \
            "Withdrawing from COMMITTEE_REVIEW cancels its ASSIGNED reads"

        withdrawn_two = transition_application(
            waitlisted["application"]["id"], "WITHDRAWN",
            make_applicant_headers(waitlisted["applicant"]["id"]))
        assert withdrawn_two["status"] == "WITHDRAWN"
        entry = get_waitlist_entry_for_application(
            waitlisted["application"]["id"])
        assert entry["status"] == "REMOVED", \
            "The applicant's withdrawal removes the ACTIVE waitlist entry"
