"""Deposits (capacity, deadline, amount), melt-risk scoring and its
threshold side effect, advisor intervention scheduling, and the melt sweep."""
from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_aid_offer,
    advance_cycle,
    advance_cycle_to_decisions_released,
    assert_seat_ledger_conserved,
    create_admitted_application,
    create_aid_offer,
    create_deposited_application,
    create_intervention_payload,
    create_waitlisted_application,
    list_interventions_for,
    make_applicant_headers,
    pay_deposit,
    refresh_application,
    refresh_program,
    schedule_intervention,
    set_clock,
    setup_open_cycle_with_program,
    transition_application,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["enrollment_manager_headers"]
OFFICER = TEST_USERS["admissions_officer_headers"]


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestDepositCapacityBoundary:
    def test_deposits_accepted_below_capacity(self, api):
        """PRD 3.6: "a deposit made when the program's `deposited_count`
        plus `enrolled_count` has already reached `capacity_seats` is
        rejected with `ERR_CAPACITY_FULL`, while one made when the sum is
        exactly one below capacity is accepted."

        Design: Difficulty/boundary_precision_check/deposit_capacity_exactly_full_boundary
        """
        setup = setup_open_cycle_with_program(name="MUS", capacity_seats=2,
                                              target_enrollment=2)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair_a = create_admitted_application(cycle_id, program_id,
                                             academic_score=80)
        pair_b = create_admitted_application(cycle_id, program_id,
                                             academic_score=81)
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")

        dep_a = pay_deposit(pair_a["application"], pair_a["applicant"])
        assert dep_a["status"] == "PAID", "First deposit lands at count 0 < 2"
        dep_b = pay_deposit(pair_b["application"], pair_b["applicant"])
        assert dep_b["status"] == "PAID", \
            "Second deposit lands at count 1 == capacity-1 and is accepted"

    def test_deposit_rejected_at_exactly_capacity(self, api):
        """PRD 3.6: "a deposit made when the program's `deposited_count`
        plus `enrolled_count` has already reached `capacity_seats` is
        rejected with `ERR_CAPACITY_FULL`, while one made when the sum is
        exactly one below capacity is accepted."
        PRD 2.6: "The posture flips to `PAUSED` the moment the
        deposited-plus-enrolled sum reaches or exceeds the target."

        Design: Difficulty/boundary_precision_check/deposit_capacity_exactly_full_boundary
        """
        setup = setup_open_cycle_with_program(name="MUS", capacity_seats=2,
                                              target_enrollment=2)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pairs = [create_admitted_application(cycle_id, program_id,
                                             academic_score=s)
                 for s in (80, 81, 82)]
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(pairs[0]["application"], pairs[0]["applicant"])
        pay_deposit(pairs[1]["application"], pairs[1]["applicant"])

        resp = api.create_deposit(
            {"application_id": pairs[2]["application"]["id"],
             "amount_cents": 50_000},
            make_applicant_headers(pairs[2]["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_FULL)

        program = refresh_program(program_id)
        assert program["deposited_count"] == 2
        assert program["seats_open"] == 0
        assert program["intake_posture"] == "PAUSED", \
            "The sum reaching target_enrollment flips posture to PAUSED"
        assert_seat_ledger_conserved(program)


class TestDepositGuards:
    def test_deposit_deadline_boundary_inclusive(self, api):
        """PRD 3.6: "the logical clock must not have passed the cycle's
        `deposit_deadline_at` — the deadline boundary is inclusive, so a
        deposit landing exactly at the deadline is accepted and anything
        strictly later is rejected with `ERR_DEPOSIT_DEADLINE_PASSED`"

        Design: Corner/state_machines/deposit_deadline_boundary_inclusive
        """
        setup = setup_open_cycle_with_program(name="DDL", capacity_seats=3,
                                              target_enrollment=2)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair_a = create_admitted_application(cycle_id, program_id,
                                             academic_score=80)
        pair_b = create_admitted_application(cycle_id, program_id,
                                             academic_score=81)
        advance_cycle_to_decisions_released(cycle_id)

        set_clock("2027-05-01T00:00:00Z")  # exactly deposit_deadline_at
        dep_a = pay_deposit(pair_a["application"], pair_a["applicant"])
        assert dep_a["status"] == "PAID", \
            "A deposit landing exactly at the deadline is accepted"

        set_clock("2027-05-01T00:00:01Z")  # one second past
        resp = api.create_deposit(
            {"application_id": pair_b["application"]["id"],
             "amount_cents": 50_000},
            make_applicant_headers(pair_b["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_DEADLINE_PASSED)

    def test_deposit_amount_mismatch_rejected(self, api):
        """PRD 3.6: "the `amount_cents` must equal the program's
        `deposit_amount_cents` exactly, with any mismatch rejected as
        `ERR_DEPOSIT_AMOUNT_MISMATCH`"

        Design: Corner/validations/deposit_amount_mismatch_rejected
        """
        setup = setup_open_cycle_with_program(name="AMT", capacity_seats=4,
                                              target_enrollment=2)
        cycle_id = setup["cycle"]["id"]
        pair = create_admitted_application(cycle_id, setup["program"]["id"],
                                           academic_score=80)
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")

        wrong = api.create_deposit(
            {"application_id": pair["application"]["id"],
             "amount_cents": 40_000},
            make_applicant_headers(pair["applicant"]["id"]))
        validate_error(wrong, ApiErrorId.ERR_DEPOSIT_AMOUNT_MISMATCH)

        exact = pay_deposit(pair["application"], pair["applicant"])
        assert exact["status"] == "PAID", \
            "The exact deposit_amount_cents succeeds"


class TestValidationOrderingDeposit:
    def test_state_error_beats_capacity_error(self, api):
        """PRD 2.9: "Because fiscal checks run last, a seat-capacity failure
        can never mask an earlier state or clock failure; the inverse is
        always what the caller observes."
        PRD 3.6: "the application must currently be `ADMITTED`, with any
        other status rejected as `ERR_INVALID_STATE`"

        Design: Difficulty/priority_pair_validation_conflict/deposit_state_error_beats_capacity_fiscal_error
        """
        setup = setup_open_cycle_with_program(name="ART", capacity_seats=1,
                                              target_enrollment=1)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair_a = create_admitted_application(cycle_id, program_id,
                                             academic_score=80)
        pair_b = create_admitted_application(cycle_id, program_id,
                                             academic_score=81)
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(pair_a["application"], pair_a["applicant"])  # fills 1/1
        transition_application(pair_b["application"]["id"], "WITHDRAWN")

        resp = api.create_deposit(
            {"application_id": pair_b["application"]["id"],
             "amount_cents": 50_000},
            make_applicant_headers(pair_b["applicant"]["id"]))
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert error["error_id"] != "ERR_CAPACITY_FULL", \
            "The state failure (WITHDRAWN) outranks the fiscal failure"

    def test_rejected_deposit_persists_no_row(self, api):
        """PRD 2.9: "Because fiscal checks run last, a seat-capacity failure
        can never mask an earlier state or clock failure; the inverse is
        always what the caller observes."
        PRD 3.6: "The deposit listing can be filtered by `application_id`
        and `status`."

        Design: Difficulty/priority_pair_validation_conflict/deposit_state_error_beats_capacity_fiscal_error
        """
        setup = setup_open_cycle_with_program(name="ART", capacity_seats=1,
                                              target_enrollment=1)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair_a = create_admitted_application(cycle_id, program_id,
                                             academic_score=80)
        pair_b = create_admitted_application(cycle_id, program_id,
                                             academic_score=81)
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(pair_a["application"], pair_a["applicant"])
        transition_application(pair_b["application"]["id"], "WITHDRAWN")

        resp = api.create_deposit(
            {"application_id": pair_b["application"]["id"],
             "amount_cents": 50_000},
            make_applicant_headers(pair_b["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        _rows, meta = validate_paginated(api.list_deposits(
            MANAGER, params={"application_id": pair_b["application"]["id"]}))
        assert meta["total_count"] == 0, \
            "The rejected deposit persists no row"


class TestSeatLedgerRoundTrip:
    def test_deposit_moves_seat_counters(self, api):
        """PRD 2.6: "The seat ledger is expressed through `seats_open`,
        defined as `capacity_seats` minus the program's `deposited_count`
        minus its `enrolled_count`; it never drifts from that identity."
        PRD 3.6: "That transition shifts the program's counters —
        `admitted_count` down by one, `deposited_count` up by one —
        recomputes `seats_open` and `intake_posture`"

        Design: Difficulty/compensating_invariant/seat_ledger_deposit_refund_round_trip
        """
        setup = setup_open_cycle_with_program(name="PHI", capacity_seats=2,
                                              target_enrollment=2)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair = create_admitted_application(cycle_id, program_id,
                                           academic_score=80)
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-15T00:00:00Z")

        before = refresh_program(program_id)
        assert before["deposited_count"] == 0
        assert before["enrolled_count"] == 0
        assert before["seats_open"] == 2
        assert_seat_ledger_conserved(before)

        pay_deposit(pair["application"], pair["applicant"])
        mid = refresh_program(program_id)
        assert mid["deposited_count"] == 1
        assert mid["seats_open"] == 1
        assert_seat_ledger_conserved(mid), "Identity holds mid-flight"

    def test_pre_deadline_withdraw_restores_seat_and_refunds(self, api):
        """PRD 3.6: "when the logical clock is on or before the cycle's
        `deposit_deadline_at` the deposit moves from `PAID` to `REFUNDED` and
        its `refund_amount_cents` is set to the full `amount_cents`"
        PRD 3.6: "The program's `deposited_count` decrements, `seats_open`
        and `intake_posture` recompute"

        Design: Difficulty/compensating_invariant/seat_ledger_deposit_refund_round_trip
        """
        setup = setup_open_cycle_with_program(name="PHI", capacity_seats=2,
                                              target_enrollment=2)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair = create_admitted_application(cycle_id, program_id,
                                           academic_score=80)
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-15T00:00:00Z")
        deposit = pay_deposit(pair["application"], pair["applicant"])
        before = refresh_program(program_id)

        transition_application(
            pair["application"]["id"], "WITHDRAWN",
            make_applicant_headers(pair["applicant"]["id"]))

        after = refresh_program(program_id)
        assert after["deposited_count"] == 0
        assert after["seats_open"] == 2, \
            "The compensating withdrawal restores the seat exactly"
        assert_seat_ledger_conserved(after)

        deposit_after = validate_success(
            api.get_deposit(deposit["id"], MANAGER))
        assert deposit_after["status"] == "REFUNDED"
        assert deposit_after["refund_amount_cents"] == 50_000, \
            "Withdrawal at 2027-04-15 (<= deadline 2027-05-01) refunds in full"


class TestWithdrawForfeiture:
    def test_withdraw_after_deadline_forfeits_deposit(self, api):
        """PRD 3.6: "when the clock is past the deadline the deposit moves
        from `PAID` to `FORFEITED` and `refund_amount_cents` becomes 0."
        PRD 3.6: "The program's `deposited_count` decrements, `seats_open`
        and `intake_posture` recompute"

        Design: Corner/state_machines/withdraw_after_deadline_forfeits_deposit
        """
        setup = setup_open_cycle_with_program(name="FOR", capacity_seats=2,
                                              target_enrollment=2)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair = create_admitted_application(cycle_id, program_id,
                                           academic_score=80)
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-15T00:00:00Z")
        deposit = pay_deposit(pair["application"], pair["applicant"])

        set_clock("2027-05-02T00:00:00Z")  # past the 2027-05-01 deadline
        app = transition_application(
            pair["application"]["id"], "WITHDRAWN",
            make_applicant_headers(pair["applicant"]["id"]))
        assert app["status"] == "WITHDRAWN"

        deposit_after = validate_success(
            api.get_deposit(deposit["id"], MANAGER))
        assert deposit_after["status"] == "FORFEITED"
        assert deposit_after["refund_amount_cents"] == 0

        program = refresh_program(program_id)
        assert program["deposited_count"] == 0
        assert program["seats_open"] == 2, \
            "Seat counters restore exactly despite the forfeit"
        assert_seat_ledger_conserved(program)


class TestMeltRiskVariants:
    def _deposited_local_no_aid(self, api):
        setup = setup_open_cycle_with_program(name="BIO", capacity_seats=3,
                                              target_enrollment=2,
                                              scholarship_budget_cents=0)
        pair = create_admitted_application(
            setup["cycle"]["id"], setup["program"]["id"], academic_score=85,
            distance_band="LOCAL")
        advance_cycle_to_decisions_released(setup["cycle"]["id"])
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(pair["application"], pair["applicant"])
        return setup, pair

    def test_standard_variant_before_deadline(self, api):
        """PRD 3.7: "While the clock is on or before the deadline, the
        standard variant applies: the risk is 0.40 times the aid-gap factor
        plus 0.25 times the distance factor plus 0.20 times the engagement
        factor plus 0.15 times the time factor."
        PRD 3.7: "Every recompute carries a threshold side effect: if the
        application is currently `DEPOSITED`, the fresh score is at least
        0.70, and no melt intervention of the application is presently in
        `SCHEDULED`, the system automatically schedules one"

        Design: Difficulty/dual_variant_calc/melt_risk_summer_window_variant_diverges
        """
        setup, pair = self._deposited_local_no_aid(api)
        app = refresh_application(pair["application"]["id"])
        assert app["melt_risk_score"] == pytest.approx(0.60, abs=1e-6), (
            "0.40*1.0 (full aid gap) + 0.25*0.0 (LOCAL) + 0.20*1.0 "
            "(engagement) + 0.15*0.0 (same-day deposit) = 0.6000")
        assert list_interventions_for(app["id"]) == [], \
            "0.6000 < 0.70: no automatic intervention is scheduled"

    def test_summer_window_variant_after_deadline(self, api):
        """PRD 3.7: "Once the clock passes the deadline, the summer-window
        variant applies: the distance factor drops out entirely and the
        weights rebalance to 0.50 times the aid-gap factor plus 0.30 times
        the engagement factor plus 0.20 times the time factor."
        PRD 2.4: "Setting the clock is not a passive read of time: as a side
        effect it recomputes the `melt_risk_score` of every application
        currently in `DEPOSITED`, including the threshold-triggered automatic
        interventions described in §3.7."

        Design: Difficulty/dual_variant_calc/melt_risk_summer_window_variant_diverges
        """
        setup, pair = self._deposited_local_no_aid(api)
        app_id = pair["application"]["id"]
        before = refresh_application(app_id)
        assert before["melt_risk_score"] == pytest.approx(0.60, abs=1e-6)

        set_clock("2027-05-16T00:00:00Z")  # past the 2027-05-01 deadline
        after = refresh_application(app_id)
        assert after["melt_risk_score"] == pytest.approx(1.0, abs=1e-6), (
            "summer window: 0.50*1.0 + 0.30*1.0 + 0.20*1.0 (45 days "
            "caps the time factor) = 1.0000")
        assert after["melt_risk_score"] != before["melt_risk_score"], \
            "Same fields, different variant, different score"

        interventions = list_interventions_for(app_id)
        assert len(interventions) == 1, \
            "1.0000 >= 0.70 triggers exactly one automatic intervention"
        auto = interventions[0]
        assert auto["trigger_source"] == "AUTO_THRESHOLD"
        assert auto["intervention_type"] == "EMAIL_CAMPAIGN"
        assert auto["advisor_id"] == "AUTO_QUEUE"
        assert auto["status"] == "SCHEDULED"
        span = _iso(auto["window_end_at"]) - _iso(auto["window_start_at"])
        assert span.days == 7, \
            "The automatic window runs from the clock instant to 7 days later"


class TestMeltThresholdBoundary:
    def test_melt_threshold_exact_boundary(self, api):
        """PRD 3.7: "Every recompute carries a threshold side effect: if the
        application is currently `DEPOSITED`, the fresh score is at least
        0.70, and no melt intervention of the application is presently in
        `SCHEDULED`, the system automatically schedules one"
        PRD 3.7: "The score blends four factors. The aid-gap factor is the
        application's `aid_gap_cents` divided by its program's
        `tuition_cents`, capped at 1 and rounded half-up to four decimals"

        Design: Corner/cross_cutting_layers/melt_threshold_exact_boundary
        """
        setup = setup_open_cycle_with_program(name="THR", capacity_seats=4,
                                              target_enrollment=3,
                                              scholarship_budget_cents=5_000_000)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair_x = create_admitted_application(
            cycle_id, program_id, academic_score=85, efc_cents=4_375_000,
            distance_band="NATIONAL")
        offer_x = create_aid_offer(pair_x["application"], "NEED_BASED")
        assert offer_x["amount_cents"] == 625_000, \
            "min(625000 need, 3000000 rate cap, 3000000 fund cap)"
        accept_aid_offer(offer_x["id"], pair_x["applicant"]["id"])

        pair_y = create_admitted_application(
            cycle_id, program_id, academic_score=85, efc_cents=3_124_000,
            distance_band="INTERNATIONAL")
        offer_y = create_aid_offer(pair_y["application"], "NEED_BASED")
        assert offer_y["amount_cents"] == 1_876_000
        accept_aid_offer(offer_y["id"], pair_y["applicant"]["id"])

        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(pair_x["application"], pair_x["applicant"])
        pay_deposit(pair_y["application"], pair_y["applicant"])

        app_x = refresh_application(pair_x["application"]["id"])
        assert app_x["melt_risk_score"] == pytest.approx(0.70, abs=1e-6), (
            "aid gap 4375000/5000000 = 0.875: 0.40*0.875 + 0.25*0.6 "
            "+ 0.20*1.0 + 0.15*0.0 = 0.7000")
        x_interventions = list_interventions_for(app_x["id"])
        assert len(x_interventions) == 1
        assert x_interventions[0]["trigger_source"] == "AUTO_THRESHOLD"
        assert x_interventions[0]["status"] == "SCHEDULED"

        app_y = refresh_application(pair_y["application"]["id"])
        assert app_y["melt_risk_score"] == pytest.approx(0.6999, abs=1e-6), (
            "aid gap 3124000/5000000 = 0.6248: 0.40*0.6248 rounds to 0.2499 "
            "+ 0.25*1.0 + 0.20*1.0 + 0.15*0.0 = 0.6999")
        assert list_interventions_for(app_y["id"]) == [], \
            "0.6999 < 0.70: no automatic intervention for Y"


class TestEnrollmentCascade:
    def test_enrollment_cancels_scheduled_intervention(self, api):
        """PRD 3.6: "The transition moves `deposited_count` down by one and
        `enrolled_count` up by one, recomputes `seats_open` and
        `intake_posture`, and cancels every melt intervention of the
        application still in `SCHEDULED`, moving each to `CANCELLED`."

        Design: Corner/state_machines/enrollment_cancels_scheduled_intervention
        """
        setup = setup_open_cycle_with_program(name="ENR", capacity_seats=4,
                                              target_enrollment=2)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair = create_admitted_application(cycle_id, program_id,
                                           academic_score=80)
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(pair["application"], pair["applicant"])
        intervention = schedule_intervention(
            pair["application"]["id"], advisor_id="advisor-Z")

        app = transition_application(pair["application"]["id"], "ENROLLED",
                                     MANAGER)
        assert app["status"] == "ENROLLED"

        iv = validate_success(api.get_intervention(intervention["id"],
                                                   MANAGER))
        assert iv["status"] == "CANCELLED", \
            "Enrollment cancels the still-SCHEDULED intervention"

        program = refresh_program(program_id)
        assert program["deposited_count"] == 0
        assert program["enrolled_count"] == 1
        assert program["seats_open"] == 3
        assert_seat_ledger_conserved(program)


class TestAdvisorBuffer:
    def _deposited_with_first_call(self, api):
        setup = setup_open_cycle_with_program(name="NUR", capacity_seats=4,
                                              target_enrollment=3)
        pair = create_admitted_application(
            setup["cycle"]["id"], setup["program"]["id"], academic_score=80)
        advance_cycle_to_decisions_released(setup["cycle"]["id"])
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(pair["application"], pair["applicant"])
        schedule_intervention(pair["application"]["id"],
                              advisor_id="advisor-M",
                              window_start_at="2027-04-10T09:00:00Z",
                              window_end_at="2027-04-10T09:30:00Z")
        return pair

    def test_start_inside_post_buffer_rejected(self, api):
        """PRD 3.7: "the new intervention conflicts when another `SCHEDULED`
        intervention of either of those two types exists for the same
        `advisor_id` whose exclusion span — running from its window start to
        fifteen minutes past its window end — overlaps the new window, and a
        conflict is rejected with `ERR_INTERVENTION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/advisor_intervention_buffer_gap
        """
        pair = self._deposited_with_first_call(api)
        resp = api.create_intervention(
            create_intervention_payload(
                pair["application"]["id"], "advisor-M", "OUTREACH_CALL",
                "2027-04-10T09:30:00Z", "2027-04-10T10:00:00Z"),
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_INTERVENTION_WINDOW_CONFLICT)

    def test_start_exactly_at_buffer_end_accepted(self, api):
        """PRD 3.7: "the new intervention conflicts when another `SCHEDULED`
        intervention of either of those two types exists for the same
        `advisor_id` whose exclusion span — running from its window start to
        fifteen minutes past its window end — overlaps the new window, and a
        conflict is rejected with `ERR_INTERVENTION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/advisor_intervention_buffer_gap
        """
        pair = self._deposited_with_first_call(api)
        created = validate_success(api.create_intervention(
            create_intervention_payload(
                pair["application"]["id"], "advisor-M", "OUTREACH_CALL",
                "2027-04-10T09:45:00Z", "2027-04-10T10:15:00Z"),
            MANAGER), 201)
        assert created["status"] == "SCHEDULED", \
            "Starting exactly at window_end + 15 minutes satisfies the buffer"

        _rows, meta = validate_paginated(api.list_interventions(
            MANAGER, params={"advisor_id": "advisor-M",
                             "status": "SCHEDULED"}))
        assert meta["total_count"] == 2, \
            "advisor-M holds exactly the two non-conflicting calls"


class TestMeltSweepCascade:
    def _melt_sweep_setup(self, api):
        """M (70) admitted+deposited, K (80) admitted+deposited+enrolled,
        W (60) waitlisted; auto_waitlist_activation on; ENROLLMENT_TRACKING."""
        setup = setup_open_cycle_with_program(
            name="CHE", capacity_seats=3, target_enrollment=2,
            auto_waitlist_activation=True)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        melt = create_admitted_application(cycle_id, program_id,
                                           academic_score=70)
        keep = create_admitted_application(cycle_id, program_id,
                                           academic_score=80)
        waited = create_waitlisted_application(cycle_id, program_id,
                                               academic_score=60)
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(melt["application"], melt["applicant"])
        pay_deposit(keep["application"], keep["applicant"])
        transition_application(keep["application"]["id"], "ENROLLED", MANAGER)
        set_clock("2027-05-02T00:00:00Z")
        advance_cycle(cycle_id, "ENROLLMENT_TRACKING")
        return setup, melt, keep, waited

    def test_sweep_melts_deposited_and_forfeits(self, api):
        """PRD 3.7: "it moves every application of the cycle still in
        `DEPOSITED` to `MELTED` and runs the full melt cascade on each: the
        application's deposit moves from `PAID` to `FORFEITED` with
        `refund_amount_cents` set to 0; the program's `deposited_count`
        decrements, `seats_open` rises by one, and `intake_posture`
        re-derives"
        PRD 3.7: "The sweep answers with `melted_count`, the list of
        `melted_application_ids`, and the list of `activated_entry_ids`
        produced by those conditional activations."

        Design: Difficulty/transitive_cascade/melt_sweep_cascade_to_waitlist_activation
        """
        setup, melt, keep, waited = self._melt_sweep_setup(api)
        result = validate_success(
            api.melt_sweep_cycle(setup["cycle"]["id"], MANAGER))
        assert result["melted_count"] == 1, "K is ENROLLED, not swept"
        assert result["melted_application_ids"] == [melt["application"]["id"]]

        melted_app = refresh_application(melt["application"]["id"])
        assert melted_app["status"] == "MELTED"
        rows, meta = validate_paginated(api.list_deposits(
            MANAGER, params={"application_id": melt["application"]["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "FORFEITED"
        assert rows[0]["refund_amount_cents"] == 0

        program = refresh_program(setup["program"]["id"])
        assert program["deposited_count"] == 0
        assert program["enrolled_count"] == 1
        assert program["seats_open"] == 2
        assert program["intake_posture"] == "OPEN", \
            "The freed seat reopens the posture"
        assert_seat_ledger_conserved(program)

    def test_sweep_freed_seat_auto_activates_top_waitlist_entry(self, api):
        """PRD 3.8: "Seats freed by melt or by a post-deposit withdrawal run
        the same selection automatically, but only when two conditions both
        hold: the program's `auto_waitlist_activation` flag is true, and the
        posture recomputed after the seat frees is `OPEN`. When both hold,
        the same pinned selector — `rank_score` descending, `submitted_at`
        ascending as the tie-break — picks the top-ranked `ACTIVE` entry of
        that program, moves it to `ACTIVATED`, moves its application from
        `WAITLISTED` to `ADMITTED`, and increments `admitted_count`"

        Design: Difficulty/transitive_cascade/melt_sweep_cascade_to_waitlist_activation
        """
        setup, melt, keep, waited = self._melt_sweep_setup(api)
        entry_before = waited["entry"]
        assert entry_before["rank_score"] == pytest.approx(76.0, abs=1e-6), \
            "0.6*60 + 0.4*100 (two ADMIT reads) = 76.0"

        result = validate_success(
            api.melt_sweep_cycle(setup["cycle"]["id"], MANAGER))
        assert result["activated_entry_ids"] == [entry_before["id"]]

        entry_after = validate_success(
            api.get_waitlist_entry(entry_before["id"], MANAGER))
        assert entry_after["status"] == "ACTIVATED", \
            "Auto-activation fired after the posture flip"

        waited_app = refresh_application(waited["application"]["id"])
        assert waited_app["status"] == "ADMITTED"

        program = refresh_program(setup["program"]["id"])
        assert program["admitted_count"] == 1
