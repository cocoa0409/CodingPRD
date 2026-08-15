"""Delivery loads: provisional vs final freight, storage fees, dispatch gates."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_customer,
    make_job,
    make_load,
    set_clock,
    setup_confirmed_job,
    setup_mega_chain_delivered,
    setup_two_loads_delivered,
    setup_load_loading,
    load_fresh,
    job_fresh,
)

PM = TEST_USERS["plant_manager_headers"]
SC = TEST_USERS["shipping_coordinator_headers"]


class TestFreightProvisionalVsFinalDivergence:
    def test_final_freight_diverges_from_provisional(self, api):
        """PRD §3.7: "`provisional_freight_cents` is a flat base of 50000 cents, plus
        the `planned_weight_est_lbs` multiplied by 12 cents per pound rounded half-up
        to whole cents, plus a flat 25000 cents when the job's
        `crane_required_at_jobsite` is true." and "Fifth, `final_freight_cents` is the
        50000-cent base, plus `actual_total_weight_lbs` multiplied by 12 cents per
        pound rounded half-up, plus the surcharge, plus the crane cost, plus the
        storage fee — all integer cents."

        Design: Difficulty/dual_variant_calc/freight_provisional_vs_final_divergence
        """
        ns = setup_mega_chain_delivered()
        closed = validate_success(api.transition_load(
            ns.load1["id"], {"to_state": "CLOSED", "crane_hours_actual": 2.5}, SC))
        assert closed["status"] == "CLOSED"
        assert closed["provisional_freight_cents"] == 170000, \
            "planning variant: 50000 + 10000 x 12, estimate only"
        assert closed["actual_total_weight_lbs"] == pytest.approx(12000), \
            "SUPERSEDED bundle b2 is excluded from the measured base"
        assert closed["storage_fee_cents"] == 60000
        assert closed["final_freight_cents"] == 304000, \
            "settlement variant: 50000 + 12000 x 12 + 0 surcharge + 2.5 h x 20000 + 60000 storage"
        assert closed["final_freight_cents"] != closed["provisional_freight_cents"]

    def test_close_recomputes_invoiced_and_completes_job(self, api):
        """PRD §3.2: "`invoiced_cents`, initially 0, is the `contracted_value_cents`
        plus the sum of `final_freight_cents` over the job's `CLOSED` loads." and "The
        job reaches `COMPLETED` automatically once every delivery load of the job is
        `CLOSED` or `CANCELLED`, every production batch is `LOADED` or `CANCELLED`, no
        damage claim on any of the job's loads remains open in `FILED`, `TRIAGED`,
        `APPROVED_REBUILD`, `APPROVED_CREDIT`, or `REBUILD_IN_PROGRESS`, and at least
        one delivery load exists".

        Design: Difficulty/dual_variant_calc/freight_provisional_vs_final_divergence
        """
        ns = setup_mega_chain_delivered()
        validate_success(api.transition_load(
            ns.load1["id"], {"to_state": "CLOSED", "crane_hours_actual": 2.5}, SC))
        job = job_fresh(ns.job["id"])
        assert job["invoiced_cents"] == 5304000, "5000000 contract + 304000 final freight"
        assert job["status"] == "COMPLETED", \
            "only load CLOSED; bat1 LOADED and bat2 CANCELLED; no claims open"


class TestFreightFinalEvaluationOrder:
    def test_surcharge_keys_on_post_supersede_measured_weight(self, api):
        """PRD §3.7: "First, `actual_total_weight_lbs` is the sum of `weight_lbs` over
        the load's bundles in `PACKED`, `LOADED`, `DELIVERED`, `RETURNED`, or
        `DAMAGED` — `SUPERSEDED` bundles are excluded, so a change-order apply between
        staging and close changes this base." and "Third, the overweight surcharge
        applies only to the excess above 20000 pounds: the amount by which
        `actual_total_weight_lbs` strictly exceeds 20000, multiplied by 18 cents per
        pound — a load at exactly 20000 pounds pays nothing."

        Design: Difficulty/combinatorial_formula/freight_final_evaluation_order
        """
        ns = setup_mega_chain_delivered()
        closed = validate_success(api.transition_load(
            ns.load1["id"], {"to_state": "CLOSED", "crane_hours_actual": 2.5}, SC))
        assert closed["actual_total_weight_lbs"] == pytest.approx(12000)
        # Post-supersede base 12000 <= 20000 -> surcharge tier contributes 0 (the
        # pre-supersede 20160 snapshot would have wrongly added 2880).
        assert closed["final_freight_cents"] == 50000 + 144000 + 0 + 50000 + 60000

    def test_storage_anchors_at_restaging_and_crane_from_load_pick(self, api):
        """PRD §3.7: "Staging requires at least one bundle of the load in `PACKED` and
        stamps `staged_at` with the current logical clock — the storage anchor, null
        until this transition." and "the crane is the one on the load's
        earliest-`start_at` `BOOKED` or `COMPLETED` `LOAD_PICK` slot, ties broken by
        slot `created_at` ascending, and `crane_hours_actual` multiplied by that
        crane's `hourly_rate_cents`, rounded half-up to whole cents, gives the crane
        cost."

        Design: Difficulty/combinatorial_formula/freight_final_evaluation_order
        """
        ns = setup_mega_chain_delivered()
        closed = validate_success(api.transition_load(
            ns.load1["id"], {"to_state": "CLOSED", "crane_hours_actual": 2.5}, SC))
        # Re-staged 2026-08-15, dispatched 2026-08-21: 6 days - 2 free = 4 x 15000.
        assert closed["storage_fee_cents"] == 60000, \
            "storage is anchored at the re-staging, not the first 2026-08-10 staging"
        crane_cost = closed["final_freight_cents"] - 50000 - 144000 - 0 - 60000
        assert crane_cost == 50000, "2.5 h x 20000 cents/h on the LOAD_PICK crane"


class TestStorageFeeFreeDayBoundary:
    def test_exactly_free_days_bills_nothing(self, api):
        """PRD §3.7: "Billable days are the days stored minus the customer's
        `storage_free_days`, floored at zero — a load stored exactly
        `storage_free_days` days bills nothing, and one day beyond bills exactly one
        daily fee."

        Design: Difficulty/boundary_precision_check/storage_fee_free_day_boundary
        """
        ns = setup_two_loads_delivered()
        closed = validate_success(api.transition_load(
            ns.loadx["id"], {"to_state": "CLOSED", "crane_hours_actual": 1.0}, SC))
        # Staged 2026-08-19, dispatched 2026-08-21: exactly 2 days == free days.
        assert closed["storage_fee_cents"] == 0
        assert closed["final_freight_cents"] == 50000 + 36000 + 0 + 20000 + 0

    def test_one_day_over_bills_one_daily_fee(self, api):
        """PRD §3.7: "`storage_fee_cents`, null until close, is then the billable days
        multiplied by the customer's `storage_daily_fee_cents`, capped at the
        customer's `storage_fee_cap_cents` — the smaller of the two applies." PRD
        §3.2: "`invoiced_cents`, initially 0, is the `contracted_value_cents` plus the
        sum of `final_freight_cents` over the job's `CLOSED` loads."

        Design: Difficulty/boundary_precision_check/storage_fee_free_day_boundary
        """
        ns = setup_two_loads_delivered()
        closed_y = validate_success(api.transition_load(
            ns.loady["id"], {"to_state": "CLOSED", "crane_hours_actual": 1.0}, SC))
        # Staged 2026-08-18, dispatched 2026-08-21: 3 days - 2 free = 1 billable day.
        assert closed_y["storage_fee_cents"] == 15000
        assert closed_y["final_freight_cents"] == 50000 + 36000 + 0 + 20000 + 15000
        validate_success(api.transition_load(
            ns.loadx["id"], {"to_state": "CLOSED", "crane_hours_actual": 1.0}, SC))
        job = job_fresh(ns.job["id"])
        assert job["invoiced_cents"] == 1000000 + 106000 + 121000


class TestProvisionalFreightConstants:
    def test_provisional_freight_constants_applied(self, api):
        """PRD §3.7: "`provisional_freight_cents` is a flat base of 50000 cents, plus
        the `planned_weight_est_lbs` multiplied by 12 cents per pound rounded half-up
        to whole cents, plus a flat 25000 cents when the job's
        `crane_required_at_jobsite` is true."

        Design: Corner/calculations/provisional_freight_constants_applied
        """
        cust = make_customer()
        job_crane = make_job(cust, job_name="Crane Job", contracted_value_cents=100000,
                             crane_required_at_jobsite=True)
        job_plain = make_job(cust, job_name="No Crane Job", contracted_value_cents=100000)
        load_a = make_load(job_crane["id"], planned_weight_est_lbs=5000)
        load_b = make_load(job_plain["id"], planned_weight_est_lbs=5000)
        assert load_a["provisional_freight_cents"] == 135000, "50000 + 5000 x 12 + 25000 flat"
        assert load_b["provisional_freight_cents"] == 110000, "flag false drops the 25000 flat"


class TestJobsiteDailyDropCapacity:
    def _confirmed_job(self):
        cust = make_customer(max_drops_per_day=2)
        job = make_job(cust, confirm=True, job_name="Drops Job", contracted_value_cents=500000)
        return job

    def test_third_load_on_same_date_rejected(self, api):
        """PRD §3.7: "the aggregate drops-per-day capacity must admit one more load,
        meaning the count of the job's loads sharing that `scheduled_date` with any
        status other than `CANCELLED` must be strictly less than the customer's
        `max_drops_per_day` before this load is added, else
        `ERR_DROPS_PER_DAY_EXCEEDED` (HTTP 422)".

        Design: Difficulty/resource_temporal_overlap/jobsite_daily_drop_capacity
        """
        job = self._confirmed_job()
        l1 = make_load(job["id"], planned_weight_est_lbs=5000)
        l2 = make_load(job["id"], planned_weight_est_lbs=5000)
        assert l1["status"] == "PLANNED" and l2["status"] == "PLANNED", \
            "two loads may share one scheduled date (aggregate capacity 2)"
        resp = api.create_load(job["id"],
                               {"scheduled_date": "2026-08-21T00:00:00Z",
                                "planned_weight_est_lbs": 5000}, SC)
        validate_error(resp, ApiErrorId.ERR_DROPS_PER_DAY_EXCEEDED)

    def test_capacity_is_per_date_and_window_end_inclusive(self, api):
        """PRD §3.7: "the `scheduled_date` must fall inside the job's closed delivery
        window — on or after `delivery_window_start` and on or before
        `delivery_window_end` — else `ERR_OUTSIDE_DELIVERY_WINDOW` (HTTP 422)".

        Design: Difficulty/resource_temporal_overlap/jobsite_daily_drop_capacity
        """
        job = self._confirmed_job()
        l3 = make_load(job["id"], scheduled_date="2026-08-22T00:00:00Z",
                       planned_weight_est_lbs=5000)
        assert l3["status"] == "PLANNED", "capacity is per-date, another day is free"
        l4 = make_load(job["id"], scheduled_date="2026-08-27T00:00:00Z",
                       planned_weight_est_lbs=5000)
        assert l4["status"] == "PLANNED", "the closed window includes its end date"
        resp = api.create_load(job["id"],
                               {"scheduled_date": "2026-08-28T00:00:00Z",
                                "planned_weight_est_lbs": 5000}, SC)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_DELIVERY_WINDOW)


class TestDispatchFiscalGates:
    def test_credit_limit_exceeded_at_load_create(self, api):
        """PRD §3.7: "the customer's `credit_used_cents` plus this load's provisional
        freight must not exceed `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`
        (HTTP 402)".

        Design: Corner/validations/credit_limit_exceeded_at_load_create
        """
        cust = make_customer(credit_limit_cents=100000)
        job = make_job(cust, confirm=True, job_name="Credit Job", contracted_value_cents=100000)
        resp = api.create_load(job["id"],
                               {"scheduled_date": "2026-08-21T00:00:00Z",
                                "planned_weight_est_lbs": 10000}, SC)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)  # 0 + 170000 > 100000
        ok = make_load(job["id"], planned_weight_est_lbs=4000)
        assert ok["provisional_freight_cents"] == 98000, "0 + 98000 <= 100000 passes"

    def test_credit_hold_blocks_dispatch_directly(self, api):
        """PRD §3.7: "the customer's `credit_hold` must be false, else
        `ERR_CREDIT_HOLD` (HTTP 402) — a check deliberately performed after the
        temporal gates".

        Design: Corner/errors/credit_hold_blocks_dispatch_directly
        """
        ns = setup_load_loading(job_name="Hold Job")
        set_clock("2026-08-20T00:00:00Z")  # inside the delivery window
        validate_success(api.update_customer_account(ns.customer["id"], {"credit_hold": True}, PM))
        resp = api.transition_load(ns.load["id"], {"to_state": "DISPATCHED"}, SC)
        validate_error(resp, ApiErrorId.ERR_CREDIT_HOLD)
        assert load_fresh(ns.load["id"])["status"] == "LOADING"


class TestDispatchTemporalBeatsFiscal:
    def test_past_window_with_credit_hold_reports_temporal(self, api):
        """PRD §3.7: "Dispatch is guarded temporally first, then fiscally. The
        `scheduled_date` must lie inside the job's closed delivery window and the
        current logical clock must be on or before `delivery_window_end`, else
        `ERR_OUTSIDE_DELIVERY_WINDOW`; the customer's `credit_hold` must be false,
        else `ERR_CREDIT_HOLD` (HTTP 402) — a check deliberately performed after the
        temporal gates".

        Design: Difficulty/priority_pair_validation_conflict/dispatch_temporal_beats_fiscal
        """
        ns = setup_load_loading(job_name="Late Job")
        set_clock("2026-08-28T00:00:00Z")  # past delivery_window_end 2026-08-27
        validate_success(api.update_customer_account(ns.customer["id"], {"credit_hold": True}, PM))
        assert job_fresh(ns.job["id"])["posture"] == "BLOCKED", \
            "the credit hold derivation is observed before the trigger"
        # Both a temporal fault and a fiscal hold exist; temporal is reported.
        resp = api.transition_load(ns.load["id"], {"to_state": "DISPATCHED"}, SC)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_DELIVERY_WINDOW)
        assert load_fresh(ns.load["id"])["status"] == "LOADING"

    def test_past_window_with_limit_breach_reports_temporal(self, api):
        """PRD §3.7: "Dispatch is guarded temporally first, then fiscally." and "the
        current logical clock must be on or before `delivery_window_end`, else
        `ERR_OUTSIDE_DELIVERY_WINDOW`".

        Design: Difficulty/priority_pair_validation_conflict/dispatch_temporal_beats_fiscal
        """
        ns = setup_load_loading(job_name="Late Job 2")
        set_clock("2026-08-28T00:00:00Z")
        validate_success(api.update_customer_account(ns.customer["id"],
                                                     {"credit_limit_cents": 1}, PM))
        # Temporal fault plus a credit-limit breach; the temporal gate still reports.
        resp = api.transition_load(ns.load["id"], {"to_state": "DISPATCHED"}, SC)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_DELIVERY_WINDOW)
        assert load_fresh(ns.load["id"])["status"] == "LOADING"
