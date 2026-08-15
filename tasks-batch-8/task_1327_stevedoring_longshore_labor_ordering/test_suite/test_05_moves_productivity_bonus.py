"""Move records, vessel cargo aggregates, live productivity, and bonus math."""
from test_helpers import (
    ApiErrorId,
    complete_gang,
    enter_submit_approve_timesheet,
    get_gang,
    get_vessel,
    record_moves,
    setup_working_gang,
    setup_completed_gang,
    validate_error,
    validate_success,
    void_move_record,
    make_foreman_headers,
    api_client,
)


class TestVesselCargoAggregates:

    def _setup_working_one_man_gang(self):
        return setup_working_gang(
            vessel_overrides={"vessel_name": "MV Ledger", "voyage_number": "I-502",
                              "planned_moves": 50, "planned_tons": 10,
                              "credit_limit_cents": 500_000_000},
            gang_overrides={"required_headcount": 1})

    def test_move_record_adds_to_vessel_actuals(self, api):
        """PRD §3.5: "Each record is born `RECORDED`, and the vessel's `actual_moves` and `actual_tons` recompute on every record as the sums of `moves_count` and `tons_lifted` over the `RECORDED` records of the gang orders across the vessel's shifts."

        Design: Difficulty/compensating_invariant/move_record_void_restores_vessel_actuals
        """
        ns = self._setup_working_one_man_gang()
        vessel = get_vessel(ns.vessel["id"])
        assert vessel["actual_moves"] == 0
        assert vessel["actual_tons"] == 0

        mr = record_moves(ns.gang["id"], ns.foreman_id,
                          period_start_utc="2026-08-10T08:00:00Z",
                          period_end_utc="2026-08-10T09:00:00Z",
                          moves_count=30, tons_lifted=5, stoppage_minutes=0)
        assert mr["status"] == "RECORDED"
        assert mr["recorded_by_worker_id"] == ns.foreman_id

        vessel = get_vessel(ns.vessel["id"])
        assert vessel["actual_moves"] == 30
        assert vessel["actual_tons"] == 5

    def test_move_record_void_restores_vessel_actuals(self, api):
        """PRD §3.5: "Voiding a record moves it `RECORDED` → `VOIDED` and recomputes those vessel totals with the voided row excluded."

        Design: Difficulty/compensating_invariant/move_record_void_restores_vessel_actuals
        """
        ns = self._setup_working_one_man_gang()
        mr = record_moves(ns.gang["id"], ns.foreman_id,
                          moves_count=30, tons_lifted=5, stoppage_minutes=0)
        vessel = get_vessel(ns.vessel["id"])
        assert (vessel["actual_moves"], vessel["actual_tons"]) == (30, 5)

        voided = void_move_record(mr["id"], ns.foreman_id)
        assert voided["status"] == "VOIDED"

        vessel = get_vessel(ns.vessel["id"])
        assert vessel["actual_moves"] == 0, (
            "record + void conserves the vessel aggregates")
        assert vessel["actual_tons"] == 0


class TestMoveRecordPeriods:

    def test_move_record_period_overlap_rejected_but_adjacency_allowed(self, api):
        """PRD §3.5: "a period that overlaps another `RECORDED` period on the same gang order is rejected with `ERR_MOVE_PERIOD_OVERLAP` (409)"
        PRD §2.8: "Adjacency therefore never counts as overlap — a booking or shift that ends exactly when another begins touches it without conflicting — and this holds uniformly for the worker double-booking check, the move-record period check, and equipment bookings."

        Design: Corner/validations/move_record_period_overlap_rejected_but_adjacency_allowed
        """
        ns = setup_working_gang(
            vessel_overrides={"vessel_name": "MV Periods", "voyage_number": "V-306"},
            gang_overrides={"required_headcount": 1})

        mr1 = record_moves(ns.gang["id"], ns.foreman_id,
                           period_start_utc="2026-08-10T08:00:00Z",
                           period_end_utc="2026-08-10T09:00:00Z",
                           moves_count=10, tons_lifted=5)
        assert mr1["status"] == "RECORDED"
        # Adjacent at the 09:00 seam: allowed under half-open semantics.
        mr2 = record_moves(ns.gang["id"], ns.foreman_id,
                           period_start_utc="2026-08-10T09:00:00Z",
                           period_end_utc="2026-08-10T10:00:00Z",
                           moves_count=12, tons_lifted=6)
        assert mr2["status"] == "RECORDED"

        # Straddling the seam: overlaps the second RECORDED period.
        resp = api_client.create_move_record(
            {"gang_order_id": ns.gang["id"],
             "period_start_utc": "2026-08-10T09:30:00Z",
             "period_end_utc": "2026-08-10T10:30:00Z",
             "moves_count": 5, "tons_lifted": 2, "stoppage_minutes": 0},
            make_foreman_headers(ns.foreman_id))
        validate_error(resp, ApiErrorId.ERR_MOVE_PERIOD_OVERLAP)


class TestProductivityRead:

    def test_productivity_computed_read_reflects_live_records(self, api, superintendent_headers):
        """PRD §3.5: "It returns the `gang_order_id`, the live `total_moves` and `productive_minutes` aggregated from `RECORDED` records, the current `actual_mph` at two-decimal precision, the vessel's contracted target surfaced as `mph_target`, and `bonus_eligible_now` indicating whether the present pace meets that target."
        PRD §3.5: "Moves per hour: take the order's `RECORDED` move records, sum their `moves_count` into a total move count, and compute productive minutes as the sum over those records of each period's length in minutes minus its `stoppage_minutes`."

        Design: Corner/endpoints/productivity_computed_read_reflects_live_records
        """
        ns = setup_working_gang(
            vessel_overrides={"vessel_name": "MV Live", "voyage_number": "E-401",
                              "planned_moves": 50, "planned_tons": 10,
                              "contracted_mph_target": 25.0,
                              "credit_limit_cents": 500_000_000},
            gang_overrides={"required_headcount": 1})
        record_moves(ns.gang["id"], ns.foreman_id,
                     period_start_utc="2026-08-10T08:00:00Z",
                     period_end_utc="2026-08-10T09:00:00Z",
                     moves_count=30, tons_lifted=20, stoppage_minutes=10)
        record_moves(ns.gang["id"], ns.foreman_id,
                     period_start_utc="2026-08-10T09:00:00Z",
                     period_end_utc="2026-08-10T10:00:00Z",
                     moves_count=25, tons_lifted=15, stoppage_minutes=0)

        resp = api.get_gang_order_productivity(ns.gang["id"], superintendent_headers)
        data = validate_success(resp)
        assert data["gang_order_id"] == ns.gang["id"]
        assert data["total_moves"] == 55
        assert data["productive_minutes"] == 110, (
            "stoppage minutes are excluded from the denominator")
        assert data["actual_mph"] == 30.0
        assert data["mph_target"] == 25.0
        assert data["bonus_eligible_now"] is True


class TestBonusAtExactTarget:

    def _setup_exact_target_gang(self):
        """One 60-minute RECORDED period of exactly 25 moves, target 25.0."""
        return setup_working_gang(
            vessel_overrides={"vessel_name": "MV Exact", "voyage_number": "B-202",
                              "planned_moves": 50, "planned_tons": 10,
                              "contracted_mph_target": 25.0,
                              "credit_limit_cents": 500_000_000},
            gang_overrides={"required_headcount": 1},
            move_records=[{"period_start_utc": "2026-08-10T08:00:00Z",
                           "period_end_utc": "2026-08-10T09:00:00Z",
                           "moves_count": 25, "tons_lifted": 20,
                           "stoppage_minutes": 0}])

    def test_bonus_eligible_at_exact_mph_target(self, api):
        """PRD §3.5: "Bonus eligibility follows: `bonus_eligible` is true when `actual_mph` is at least the vessel's `contracted_mph_target` — exact equality qualifies."
        PRD §3.5: "When productive minutes are zero or negative, `actual_mph` is zero; otherwise `actual_mph` is the total moves multiplied by sixty, divided by the productive minutes, rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/bonus_eligible_at_exact_mph_target_with_zero_pool
        """
        ns = self._setup_exact_target_gang()
        gang = complete_gang(ns.gang["id"], ns.foreman_id)
        assert gang["actual_mph"] == 25.0, "25 moves * 60 / 60 productive minutes"
        assert gang["bonus_eligible"] is True, ">= semantics at exact equality"

    def test_exact_target_yields_zero_bonus_pool(self, api):
        """PRD §3.5: "A gang that lands exactly on its target is therefore bonus-eligible but earns a zero pool, because it produced no excess moves."
        PRD §3.5: "When the pool is zero, `bonus_per_worker_cents` is zero; otherwise it is the pool divided by the greater of one and the number of the order's assignments in `COMPLETED` status immediately after the completion cascade, rounded half up to integer cents."

        Design: Difficulty/boundary_precision_check/bonus_eligible_at_exact_mph_target_with_zero_pool
        """
        ns = self._setup_exact_target_gang()
        gang = complete_gang(ns.gang["id"], ns.foreman_id)
        assert gang["bonus_eligible"] is True
        assert gang["bonus_pool_cents"] == 0, (
            "excess_moves = max(0, 25 - ceil(25.0 * 1)) = 0")
        assert gang["bonus_per_worker_cents"] == 0


class TestBonusPoolFrozenAndAttached:

    def test_bonus_pool_frozen_at_completion_and_attached_at_approve(self, api):
        """PRD §3.5: "The bonus pool starts from the target move count, which is the `contracted_mph_target` multiplied by the productive hours (productive minutes divided by sixty, unrounded) and rounded up to the next whole move; excess moves are the amount by which the total moves exceed that target, floored at zero; and `bonus_pool_cents` is the excess multiplied by 1,500 cents — fifteen dollars per excess move."
        PRD §3.8: "Approval also attaches the productivity bonus: `bonus_cents` takes the gang order's frozen `bonus_per_worker_cents`, which is zero whenever the order has not yet completed or earned no bonus."

        Design: Corner/calculations/bonus_pool_frozen_at_completion_and_attached_at_approve
        """
        ns = setup_completed_gang(
            vessel_overrides={"vessel_name": "MV Bonus", "voyage_number": "C-210",
                              "planned_moves": 50, "planned_tons": 10,
                              "contracted_mph_target": 25.0,
                              "credit_limit_cents": 500_000_000},
            gang_overrides={"required_headcount": 2},
            move_records=[{"period_start_utc": "2026-08-10T08:00:00Z",
                           "period_end_utc": "2026-08-10T09:00:00Z",
                           "moves_count": 30, "tons_lifted": 20,
                           "stoppage_minutes": 10},
                          {"period_start_utc": "2026-08-10T09:00:00Z",
                           "period_end_utc": "2026-08-10T10:00:00Z",
                           "moves_count": 25, "tons_lifted": 15,
                           "stoppage_minutes": 0}])
        gang = get_gang(ns.gang["id"])
        # productive minutes = (60-10) + (60-0) = 110; total moves 55.
        assert gang["actual_mph"] == 30.0, "55 * 60 / 110"
        assert gang["bonus_eligible"] is True
        # target_moves = ceil(25.0 * 110/60) = 46; excess = 9; pool = 9 * 1500.
        assert gang["bonus_pool_cents"] == 13_500
        assert gang["bonus_per_worker_cents"] == 6_750, (
            "13500 split across 2 COMPLETED workers, round half up")

        ts = enter_submit_approve_timesheet(ns.gang["id"], ns.workers[0]["id"],
                                            ns.foreman_id, work_minutes=120,
                                            meal_break_taken=True)
        assert ts["bonus_cents"] == 6_750, "frozen share attached verbatim"
        assert ts["gross_pay_cents"] == 8_000, "120 straight minutes at 4000/hour"
