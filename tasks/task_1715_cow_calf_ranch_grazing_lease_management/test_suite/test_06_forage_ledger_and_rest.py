"""The forage ledger: animal-unit math, reserve/cancel conservation, shorten
proration, and the pasture rest buffer."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_au4,
    assert_aum,
    assert_date_field,
    assert_pasture_ledger_invariant,
    cancel_assignment,
    complete_assignment,
    create_assignment,
    create_herd_group,
    create_pasture,
    create_ranch,
    get_pasture,
    set_clock,
    validate_error,
)

RANGE_MGR = TEST_USERS["range_manager_headers"]


class TestAnimalUnitDemandInteraction:
    def _setup(self, api):
        ranch = create_ranch(name="AU Ranch", hq_state="CO")
        pasture = create_pasture(ranch["id"], name="Bench", acreage=2000,
                                 base_capacity_aum=1000, min_rest_days=45)
        cows = create_herd_group(ranch["id"], group_name="Cows",
                                 animal_class="MATURE_COW", head_count=120,
                                 avg_weight_lbs=1150)
        growing = create_herd_group(ranch["id"], group_name="Yearlings",
                                    animal_class="GROWING", head_count=120,
                                    avg_weight_lbs=1150)
        return ranch, pasture, cows, growing

    def test_mature_cow_class_weight_interaction(self, api):
        """PRD §3.3: "The base factor is 1.00 for a `MATURE_COW` group, 0.70 for
        a `REPLACEMENT_HEIFER` group, and 0.75 for a `GROWING` group. Weight then
        adjusts the base: take the amount by which the group's `avg_weight_lbs`
        exceeds the 1,000-pound reference weight — zero when the group averages
        at or below it — divide that excess by 1,000, multiply by the weight
        coefficient 0.30, add one, and multiply by the class base. The resulting
        animal-unit factor is rounded half-up to 4 decimal places."
        PRD §3.9: "The `reserved_aum` is then the daily demand multiplied by
        `grazing_days`, rounded half-up to 2 decimal places"

        Design: Difficulty/combinatorial_formula/aum_demand_class_weight_day_interaction
        """
        ranch, pasture, cows, _g = self._setup(api)
        asg = create_assignment(pasture["id"], cows["id"], ranch["id"],
                                start_date="2026-06-01",
                                planned_end_date="2026-07-31")
        assert_au4(asg["au_factor"], 1.045, "1.00 x (1 + 150/1000 x 0.30)")
        assert_aum(asg["reserved_aum"], 250.8, "120 x 1.045 x 60 / 30")

    def test_growing_class_branch_changes_the_compounded_multiplier(self, api):
        """PRD §3.3: "The base factor is 1.00 for a `MATURE_COW` group, 0.70 for
        a `REPLACEMENT_HEIFER` group, and 0.75 for a `GROWING` group. Weight then
        adjusts the base: take the amount by which the group's `avg_weight_lbs`
        exceeds the 1,000-pound reference weight — zero when the group averages
        at or below it — divide that excess by 1,000, multiply by the weight
        coefficient 0.30, add one, and multiply by the class base."
        PRD §2.9: "The pasture's `available_aum` is what remains: the effective
        capacity minus the committed total minus the consumed total."

        Design: Difficulty/combinatorial_formula/aum_demand_class_weight_day_interaction
        """
        ranch, pasture, cows, growing = self._setup(api)
        create_assignment(pasture["id"], cows["id"], ranch["id"],
                          start_date="2026-06-01", planned_end_date="2026-07-31")
        asg = create_assignment(pasture["id"], growing["id"], ranch["id"],
                                start_date="2026-09-15",
                                planned_end_date="2026-11-14")
        assert_au4(asg["au_factor"], 0.7838, "0.75 x 1.045 -> round4")
        assert_aum(asg["reserved_aum"], 188.11, "120 x 0.7838 x 60 / 30")
        after = get_pasture(pasture["id"])
        assert_aum(after["available_aum"], 561.09, "1000 - 250.8 - 188.11")
        assert_pasture_ledger_invariant(after)


class TestReserveCancelConservation:
    def _setup(self, api):
        ranch = create_ranch(name="Conserve Ranch", hq_state="MT")
        pasture = create_pasture(ranch["id"], name="Ledger", acreage=900,
                                 base_capacity_aum=200)
        group = create_herd_group(ranch["id"], group_name="Cows", head_count=20,
                                  avg_weight_lbs=1000)
        set_clock("2026-05-01T00:00:00Z")
        return ranch, pasture, group

    def test_create_then_cancel_restores_available_exactly(self, api):
        """PRD §3.9: "An assignment that has not yet begun may instead be
        cancelled — permitted only while the current date is still earlier than
        its `start_date` — which moves it to `CANCELLED`, releases its full
        reservation from the pasture's `committed_aum`, and records a
        `consumed_aum` of zero."
        PRD §2.9: "The pasture's `available_aum` is what remains: the effective
        capacity minus the committed total minus the consumed total."

        Design: Difficulty/compensating_invariant/aum_reserve_cancel_conservation
        """
        ranch, pasture, group = self._setup(api)
        asg = create_assignment(pasture["id"], group["id"], ranch["id"],
                                start_date="2026-06-01",
                                planned_end_date="2026-07-31")
        after_create = get_pasture(pasture["id"])
        assert_aum(after_create["committed_aum"], 40.0)
        assert_aum(after_create["available_aum"], 160.0)
        assert_pasture_ledger_invariant(after_create)

        cancelled = cancel_assignment(asg["id"])
        assert cancelled["assignment_status"] == "CANCELLED"
        assert_aum(cancelled["consumed_aum"], 0.0)
        after_cancel = get_pasture(pasture["id"])
        assert_aum(after_cancel["committed_aum"], 0.0)
        assert_aum(after_cancel["consumed_total_aum"], 0.0)
        assert_aum(after_cancel["available_aum"], 200.0,
                   "forward + compensating pair restores the conserved total")
        assert_pasture_ledger_invariant(after_cancel)

    def test_shortened_assignment_returns_only_unused_portion(self, api):
        """PRD §3.9: "When the actual end equals the `planned_end_date` the
        assignment closes as `COMPLETED`; an earlier actual end — the early-out
        case, drought-driven or otherwise — closes it as `SHORTENED`. Either way
        the `consumed_aum` is the assignment's `daily_demand_aum` multiplied by
        the actual days grazed from `start_date` up to but not including
        `actual_end_date`, rounded half-up to 2 decimal places; the full
        `reserved_aum` comes off the pasture's `committed_aum`, which on a
        shortened stay returns the ungrazed remainder to `available_aum`; and
        the pasture's `resting_until` is set to the `actual_end_date` plus the
        pasture's `min_rest_days`, putting the ground into `RESTING` until the
        current date catches up."

        Design: Difficulty/compensating_invariant/aum_reserve_cancel_conservation
        """
        ranch, pasture, group = self._setup(api)
        asg = create_assignment(pasture["id"], group["id"], ranch["id"],
                                start_date="2026-06-01",
                                planned_end_date="2026-07-31")
        set_clock("2026-06-15T00:00:00Z")
        done = complete_assignment(asg["id"], "2026-06-15")
        assert done["assignment_status"] == "SHORTENED"
        assert_aum(done["consumed_aum"], 9.33, "20 x 1.0 x 14 / 30")
        after = get_pasture(pasture["id"])
        assert_aum(after["committed_aum"], 0.0)
        assert_aum(after["consumed_total_aum"], 9.33)
        assert_aum(after["available_aum"], 190.67, "only the unused 30.67 returns")
        assert_date_field(after["resting_until"], "2026-07-30",
                          "2026-06-15 + 45 rest days")
        assert_pasture_ledger_invariant(after)


class TestPastureRestBuffer:
    def _setup(self, api):
        """Pasture (base 500, rest 45): A1 grazed 05-01..06-01, A2 ACTIVE
        08-20..09-20."""
        ranch = create_ranch(name="Rest Ranch", hq_state="MT")
        pasture = create_pasture(ranch["id"], name="Rotational 4", acreage=900,
                                 base_capacity_aum=500, min_rest_days=45)
        group = create_herd_group(ranch["id"], group_name="Cows", head_count=10,
                                  avg_weight_lbs=1000)
        a1 = create_assignment(pasture["id"], group["id"], ranch["id"],
                               start_date="2026-05-01",
                               planned_end_date="2026-06-01")
        complete_assignment(a1["id"], "2026-06-01")
        a2 = create_assignment(pasture["id"], group["id"], ranch["id"],
                               start_date="2026-08-20",
                               planned_end_date="2026-09-20")
        return ranch, pasture, group, a1, a2

    def test_half_open_overlap_rejected(self, api):
        """PRD §3.9: "The new half-open window may not intersect the half-open
        window of any existing `ACTIVE` assignment on the same pasture —
        intersection under half-open semantics means the new start falls
        strictly before the existing end and the new end falls strictly after
        the existing start — and a collision is `ERR_PASTURE_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/pasture_assignment_rest_buffer
        """
        ranch, pasture, group, _a1, _a2 = self._setup(api)
        resp = api.create_grazing_assignment(
            {"pasture_id": pasture["id"], "herd_group_id": group["id"],
             "ranch_id": ranch["id"], "start_date": "2026-09-01",
             "planned_end_date": "2026-10-01"}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_PASTURE_WINDOW_OVERLAP,
                       expected_status=409)

    def test_rest_buffer_gap_and_exact_boundary(self, api):
        """PRD §3.9: "Only after overlap is clear does the rest-buffer rule run:
        the gap between the new window and every other non-cancelled assignment
        on the pasture, in either direction, must be at least the pasture's
        `min_rest_days`, where an existing assignment's end is taken as its
        `actual_end_date` when it ended `COMPLETED` or `SHORTENED` and its
        `planned_end_date` while still `ACTIVE`; a tighter gap fails with
        `ERR_PASTURE_REST_VIOLATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/pasture_assignment_rest_buffer
        """
        ranch, pasture, group, _a1, _a2 = self._setup(api)
        # 30 days after A1's 06-01 grazed end (and 41 days before A2's start).
        resp = api.create_grazing_assignment(
            {"pasture_id": pasture["id"], "herd_group_id": group["id"],
             "ranch_id": ranch["id"], "start_date": "2026-07-01",
             "planned_end_date": "2026-07-10"}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_PASTURE_REST_VIOLATION,
                       expected_status=409)

        # Exactly 45 days after A2's 09-20 planned end — the bound is inclusive.
        a3 = create_assignment(pasture["id"], group["id"], ranch["id"],
                               start_date="2026-11-04",
                               planned_end_date="2026-11-14")
        assert a3["assignment_status"] == "ACTIVE"
        after = get_pasture(pasture["id"])
        assert_aum(after["committed_aum"], 13.66, "A2 10.33 + A3 3.33")
        assert_aum(after["consumed_total_aum"], 10.33, "A1's 31 days")
        assert_aum(after["available_aum"], 476.01)
        assert_pasture_ledger_invariant(after)


class TestCompleteSetsRestWindow:
    def test_assignment_complete_sets_rest_window(self, api):
        """PRD §2.9: "When an assignment ends, the pasture's `resting_until` is
        set to the assignment's actual end date plus the pasture's
        `min_rest_days`, and until the current date reaches that day the pasture
        reads as `RESTING`. A pasture's `condition_status` is `CLOSED` when its
        `closed_flag` has been set, otherwise `RESTING` while the current date
        is earlier than `resting_until`, otherwise `GRAZEABLE`."

        Design: Corner/state_machines/assignment_complete_sets_rest_window
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=900,
                                 base_capacity_aum=200, min_rest_days=45)
        group = create_herd_group(ranch["id"], group_name="G", head_count=10,
                                  avg_weight_lbs=1000)
        asg = create_assignment(pasture["id"], group["id"], ranch["id"],
                                start_date="2026-05-01",
                                planned_end_date="2026-06-01")
        done = complete_assignment(asg["id"], "2026-06-01")
        assert done["assignment_status"] == "COMPLETED"
        assert_aum(done["consumed_aum"], 10.33, "10 x 1.0 x 31 / 30")

        after = get_pasture(pasture["id"])
        assert_date_field(after["resting_until"], "2026-07-16",
                          "2026-06-01 + 45 rest days")

        set_clock("2026-07-15T00:00:00Z")
        assert get_pasture(pasture["id"])["condition_status"] == "RESTING", (
            "day 44: still inside the rest window"
        )
        set_clock("2026-07-16T00:00:00Z")
        assert get_pasture(pasture["id"])["condition_status"] == "GRAZEABLE", (
            "day 45: current date has reached resting_until — inclusive boundary"
        )
