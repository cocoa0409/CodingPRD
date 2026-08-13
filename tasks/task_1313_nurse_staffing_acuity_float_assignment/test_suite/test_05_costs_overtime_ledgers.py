"""Cost economics: provisional vs final variants, rounding order, the 40-hour
overtime boundary, missed-break penalties, and the nurse week ledger."""
import pytest

from test_helpers import (
    accept_assignment,
    ADMIN,
    api_client,
    ApiErrorId,
    cancel_assignment,
    complete_assignment,
    confirm_assignment,
    create_float_nurse,
    create_nurse,
    create_shift,
    get_week_ledger,
    propose_assignment,
    setup_nurse_with_completions,
    setup_unit_with_shift,
    submit_snapshot,
    validate_error,
    validate_success,
    walk_to_accepted,
)


class TestProvisionalVsFinalCost:
    """Difficulty instance: provisional_vs_final_assignment_cost."""

    def _setup_completed_single(self):
        """ICU DAY shift required 4 (census 2/3/2/1); one CORE nurse at 5000
        cents/h completes 10.5h with 1 missed break."""
        sc = setup_unit_with_shift(name="ICU West", census=(2, 3, 2, 1))
        assert sc["shift"]["required_nurses"] == 4
        nurse = create_nurse(full_name="Nora Core", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=5000,
                             home_unit_id=sc["unit"]["id"])
        asg = propose_assignment(sc["shift"]["id"], nurse["id"],
                                 sc["charge_headers"])
        sc.update({"nurse": nurse, "asg": asg})
        return sc

    def test_provisional_cost_straight_time_no_ot(self):
        """PRD section 3.4: "The projected overtime is the smaller of 12.0 and
        the greater of zero and (prior hours plus 12.0 minus the 40-hour weekly
        threshold). The provisional cost is then the straight-time portion —
        12.0 minus the projected overtime hours — multiplied by the nurse's
        `base_hourly_rate_cents` and the assignment's `premium_multiplier`,
        plus the projected overtime hours multiplied by the base rate, the
        premium multiplier, and the one-and-a-half overtime factor, plus any
        `flat_bonus_cents`; the whole total is rounded half-up to whole cents
        in a single rounding step at the end."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_assignment_cost
        """
        sc = self._setup_completed_single()
        asg = sc["asg"]
        # No prior hours -> projected OT 0 -> 12.0 * 5000 * 1.0 = 60000
        assert asg["provisional_cost_cents"] == 60000, \
            f"provisional must be 12h * 5000 with no projected OT, got {asg['provisional_cost_cents']}"
        assert asg["projected_ot_hours"] == 0

    def test_final_cost_replaces_estimate_with_actuals(self):
        """PRD section 3.8: "The recorded `final_cost_cents` is the sum of the
        two rounded components, plus 5,000 cents for each entry in
        `missed_breaks`, plus any `flat_bonus_cents`."
        PRD section 3.8: "The settled cost replaces the estimate with actuals
        and uses chronological, completion-order overtime accounting."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_assignment_cost
        """
        sc = self._setup_completed_single()
        nurse, asg = sc["nurse"], sc["asg"]
        accept_assignment(asg["id"], nurse["id"])
        confirm_assignment(asg["id"], sc["charge_headers"])
        done = complete_assignment(asg["id"], 10.5, 1, sc["charge_headers"])
        # running 0 -> final_ot = min(10.5, max(0, 10.5-40)) = 0
        assert done["final_ot_hours"] == 0
        # round(10.5 * 5000) + 0 + 5000 * 1 = 52500 + 5000
        assert done["final_cost_cents"] == 57500, \
            f"final must be 52500 + 5000 penalty = 57500, got {done['final_cost_cents']}"
        assert done["final_cost_cents"] != asg["provisional_cost_cents"]


class TestFinalCostRoundingOrder:
    """Difficulty instance: final_cost_component_rounding_order."""

    def _setup_rounding_scenario(self):
        """Nurse at 3333 cents/h completes Mon 16.0, Tue 16.0, Wed 6.5
        (running 38.5h), then holds a Thursday assignment."""
        sc = setup_nurse_with_completions(
            [("2026-08-10", 16.0), ("2026-08-11", 16.0), ("2026-08-12", 6.5)],
            rate=3333, name="ICU R")
        submit_snapshot(sc["unit"]["id"], "2026-08-13", "DAY", (4, 0, 0, 0),
                        as_headers=sc["charge_headers"])
        sh4 = create_shift(sc["unit"]["id"], "2026-08-13", "DAY")
        sc["sh4"] = sh4
        return sc

    def test_final_cost_components_rounded_before_summation(self):
        """PRD section 2.8: "Where a cost formula is decomposed into
        components, the rounding order is pinned: each component is rounded
        half-up to whole cents individually *before* the components are added
        together, and summing first and rounding once afterwards is a
        different, non-conformant result".
        PRD section 3.8: "The `final_ot_hours` are the smaller of
        `actual_hours_worked` and the greater of zero and (running hours plus
        `actual_hours_worked` minus the 40-hour weekly threshold)".

        Design: Difficulty/combinatorial_formula/final_cost_component_rounding_order
        """
        sc = self._setup_rounding_scenario()
        nurse = sc["nurse"]
        asg = propose_assignment(sc["sh4"]["id"], nurse["id"],
                                 sc["charge_headers"])
        accept_assignment(asg["id"], nurse["id"])
        confirm_assignment(asg["id"], sc["charge_headers"])
        done = complete_assignment(asg["id"], 2.5, 0, sc["charge_headers"])
        # running 38.5 + 2.5 = 41.0 -> OT = min(2.5, 1.0) = 1.0
        assert done["final_ot_hours"] == 1.0
        # normal: round_half_up(1.5 * 3333) = round(4999.5) = 5000
        # ot:     round_half_up(1.0 * 3333 * 1.5) = round(4999.5) = 5000
        # per-component rounding gives 10000; sum-then-round would give 9999
        assert done["final_cost_cents"] == 10000, \
            f"per-component rounding must yield 10000, got {done['final_cost_cents']}"

    def test_provisional_projection_uses_completed_plus_scheduled(self):
        """PRD section 3.4: "Prior hours are taken as the sum of
        `actual_hours_worked` over the nurse's `COMPLETED` assignments in the
        shift's ISO week plus 12.0 for each of the nurse's `PROPOSED`,
        `ACCEPTED`, and `CONFIRMED` assignments in that week."
        PRD section 2.8: "(the one exception is the provisional cost estimate,
        which is defined as a single rounding applied once at the end of the
        formula)."

        Design: Difficulty/combinatorial_formula/final_cost_component_rounding_order
        """
        sc = self._setup_rounding_scenario()
        asg = propose_assignment(sc["sh4"]["id"], sc["nurse"]["id"],
                                 sc["charge_headers"])
        # prior = 38.5 completed -> projected OT = min(12, 38.5+12-40) = 10.5
        assert asg["projected_ot_hours"] == 10.5
        # single end-rounding: 1.5*3333 + 10.5*3333*1.5 = 57494.25 -> 57494
        assert asg["provisional_cost_cents"] == 57494, \
            f"single-rounding provisional must be 57494, got {asg['provisional_cost_cents']}"


class TestFortyHourOvertimeBoundary:
    """Difficulty instance: exact_40h_no_overtime_then_beyond."""

    def _setup_ot_boundary(self):
        """Nurse at 4000 cents/h completes Mon 16.0 and Tue 12.0 (28.0h);
        Wednesday and Thursday DAY shifts stand ready."""
        sc = setup_nurse_with_completions(
            [("2026-08-10", 16.0), ("2026-08-11", 12.0)],
            rate=4000, name="ICU J")
        for date in ("2026-08-12", "2026-08-13"):
            submit_snapshot(sc["unit"]["id"], date, "DAY", (4, 0, 0, 0),
                            as_headers=sc["charge_headers"])
            sc["shifts"][date] = create_shift(sc["unit"]["id"], date, "DAY")
        return sc

    def _complete(self, sc, date, hours):
        asg = propose_assignment(sc["shifts"][date]["id"], sc["nurse"]["id"],
                                 sc["charge_headers"])
        accept_assignment(asg["id"], sc["nurse"]["id"])
        confirm_assignment(asg["id"], sc["charge_headers"])
        return complete_assignment(asg["id"], hours, 0, sc["charge_headers"])

    def test_exactly_40_hours_no_overtime(self):
        """PRD section 2.9: "hours up to a weekly threshold of 40 are paid at
        the straight rate, and hours beyond 40 attract an overtime multiplier
        of one-and-a-half."

        Design: Difficulty/boundary_precision_check/exact_40h_no_overtime_then_beyond
        """
        sc = self._setup_ot_boundary()
        done = self._complete(sc, "2026-08-12", 12.0)
        # running 28.0 + 12.0 == 40.0 exactly -> no hour is beyond 40
        assert done["final_ot_hours"] == 0, \
            f"exactly 40.0h must attract zero OT, got {done['final_ot_hours']}"
        assert done["final_cost_cents"] == 48000, \
            f"12 * 4000 straight time = 48000, got {done['final_cost_cents']}"

    def test_hours_beyond_40_entirely_overtime(self):
        """PRD section 3.8: "The `final_ot_hours` are the smaller of
        `actual_hours_worked` and the greater of zero and (running hours plus
        `actual_hours_worked` minus the 40-hour weekly threshold)".

        Design: Difficulty/boundary_precision_check/exact_40h_no_overtime_then_beyond
        """
        sc = self._setup_ot_boundary()
        self._complete(sc, "2026-08-12", 12.0)  # running now exactly 40.0
        done = self._complete(sc, "2026-08-13", 4.0)
        # running 40.0 -> OT = min(4.0, 4.0) = 4.0
        assert done["final_ot_hours"] == 4.0
        assert done["final_cost_cents"] == 24000, \
            f"4 * 4000 * 1.5 = 24000, got {done['final_cost_cents']}"


class TestProvisionalWithProjectedOvertime:

    def test_provisional_cost_with_projected_overtime(self):
        """PRD section 3.4: "Prior hours are taken as the sum of
        `actual_hours_worked` over the nurse's `COMPLETED` assignments in the
        shift's ISO week plus 12.0 for each of the nurse's `PROPOSED`,
        `ACCEPTED`, and `CONFIRMED` assignments in that week. The projected
        overtime is the smaller of 12.0 and the greater of zero and (prior
        hours plus 12.0 minus the 40-hour weekly threshold)."

        Design: Corner/calculations/provisional_cost_with_projected_overtime
        """
        sc = setup_unit_with_shift(name="ICU C1", census=(4, 0, 0, 0))
        nurse = create_nurse(full_name="Proj Pete", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=5000,
                             home_unit_id=sc["unit"]["id"])
        # 36.0 projected hours across Mon/Tue/Wed (ACCEPTED counts at 12.0)
        # Reuse the Monday shift setup_unit_with_shift already created
        # (PRD enforces one shift per unit/date/code).
        monday_shift = sc["shift"]
        assert monday_shift["shift_date"] == "2026-08-10"
        walk_to_accepted(monday_shift["id"], nurse, sc["charge_headers"])
        for date in ("2026-08-11", "2026-08-12"):
            submit_snapshot(sc["unit"]["id"], date, "DAY", (4, 0, 0, 0),
                            as_headers=sc["charge_headers"])
            shift = create_shift(sc["unit"]["id"], date, "DAY")
            walk_to_accepted(shift["id"], nurse, sc["charge_headers"])
        submit_snapshot(sc["unit"]["id"], "2026-08-13", "DAY", (4, 0, 0, 0),
                        as_headers=sc["charge_headers"])
        sh4 = create_shift(sc["unit"]["id"], "2026-08-13", "DAY")

        asg = propose_assignment(sh4["id"], nurse["id"], sc["charge_headers"])
        # prior 36.0 -> projected OT = min(12, 36+12-40) = 8.0
        assert asg["projected_ot_hours"] == 8.0
        # (12-8)*5000 + 8*5000*1.5 = 20000 + 60000
        assert asg["provisional_cost_cents"] == 80000, \
            f"expected 80000, got {asg['provisional_cost_cents']}"


class TestMissedBreakPenalty:

    def test_missed_break_penalty_stacking(self):
        """PRD section 3.8: "The recorded `final_cost_cents` is the sum of the
        two rounded components, plus 5,000 cents for each entry in
        `missed_breaks`, plus any `flat_bonus_cents`."

        Design: Corner/calculations/missed_break_penalty_stacking
        """
        sc = setup_unit_with_shift(name="ICU C2", census=(4, 0, 0, 0))
        nurse = create_nurse(full_name="Break Betty", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=6000,
                             home_unit_id=sc["unit"]["id"])
        asg = propose_assignment(sc["shift"]["id"], nurse["id"],
                                 sc["charge_headers"])
        accept_assignment(asg["id"], nurse["id"])
        confirm_assignment(asg["id"], sc["charge_headers"])
        done = complete_assignment(asg["id"], 12.0, 2, sc["charge_headers"])
        # 12 * 6000 = 72000 + 2 * 5000 penalty
        assert done["final_cost_cents"] == 82000, \
            f"expected 82000, got {done['final_cost_cents']}"


class TestWeekLedger:
    """Difficulty instance: nurse_projected_hours_create_cancel_invariant;
    plus the week_start shape rule."""

    def test_week_ledger_non_monday_rejected(self):
        """PRD section 2.5: "Required fields are present, enum values are
        in-domain, numeric ranges are valid, an observation window's `end_at`
        is strictly after its `start_at`, and a week ledger query's
        `week_start` falls on a Monday — any violation yields
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/week_ledger_non_monday_rejected
        """
        nurse = create_float_nurse(full_name="Wendy Week",
                                   competencies=["ICU"])
        resp = api_client.get_week_ledger(
            nurse["id"], ADMIN, params={"week_start": "2026-08-11"})
        # 2026-08-11 is a Tuesday
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_then_cancel_leaves_projected_hours_unchanged(self):
        """PRD section 2.9: "Creating an assignment and then declining or
        cancelling that same assignment leaves `projected_hours` unchanged —
        the twelve hours enter on creation and leave on release."

        Design: Difficulty/compensating_invariant/nurse_projected_hours_create_cancel_invariant
        """
        sc = setup_unit_with_shift(name="ICU P", census=(4, 0, 0, 0))
        nurse = create_nurse(full_name="Pam Projected", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=5000,
                             home_unit_id=sc["unit"]["id"])
        asg = propose_assignment(sc["shift"]["id"], nurse["id"],
                                 sc["charge_headers"])
        mid = get_week_ledger(nurse["id"], "2026-08-10")
        assert mid["projected_hours"] == 12.0, \
            f"create must add 12.0 projected hours, got {mid['projected_hours']}"

        cancel_assignment(asg["id"], sc["charge_headers"])
        ledger = get_week_ledger(nurse["id"], "2026-08-10")
        assert ledger["projected_hours"] == 0.0, \
            f"create+cancel must leave projected_hours unchanged, got {ledger['projected_hours']}"
        assert ledger["completed_hours"] == 0.0, \
            "cancel never touches the completed ledger"

    def test_week_ledger_echoes_week_start(self):
        """PRD section 2.9: "Two ledgers are maintained per nurse per week, and
        are readable through the nurse's week-ledger capability, which takes a
        `week_start` query parameter that must be a Monday and responds with
        the echoed `week_start` plus two figures: `projected_hours`, equal to
        12.0 multiplied by the number of the nurse's assignments in
        `PROPOSED`, `ACCEPTED`, or `CONFIRMED` status whose `shift_date` falls
        inside that week, and `completed_hours`, the sum of
        `actual_hours_worked` over the nurse's `COMPLETED` assignments in that
        week."

        Design: Difficulty/compensating_invariant/nurse_projected_hours_create_cancel_invariant
        """
        sc = setup_unit_with_shift(name="ICU P2", census=(4, 0, 0, 0))
        nurse = create_nurse(full_name="Pam Echo", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=5000,
                             home_unit_id=sc["unit"]["id"])
        propose_assignment(sc["shift"]["id"], nurse["id"],
                           sc["charge_headers"])
        ledger = get_week_ledger(nurse["id"], "2026-08-10")
        assert ledger["week_start"] == "2026-08-10"
        assert ledger["projected_hours"] == 12.0
        assert ledger["completed_hours"] == 0.0
