"""Requests that violate two checks at once resolve to the higher-ranked one."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error
from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    make_energy_analyst_headers,
    make_energy_manager_headers,
    make_store_manager_headers,
)


def _store_with_one_scheduled_override(api):
    """A store whose 500.0 kWh allowance already carries a 300.00 kWh override."""
    ctx = fx.setup_commissioned_store(
        api, code="STR-PP1", override_budget_kwh_month=500.0,
    )
    ctx["override_a"] = fx.create_override(
        api, ctx["store_id"], zone="SALES_FLOOR", override_type="SCHEDULE_EXTEND",
        start_iso="2026-08-10T00:00:00Z", end_iso="2026-08-10T08:00:00Z",
        zone_load_kw=37.5, requested_reason="overnight resets",
    )
    return ctx


class TestOverrideConflictOutranksBudget:
    def test_a_request_violating_both_reports_the_window_conflict(self, api):
        """Overlap is ranked above the fiscal allowance.

        The PRD states: "11. Uniqueness, overlap and data-sufficiency constraints
        — `ERR_DUPLICATE_STANDARD_SCOPE`, then `ERR_OVERRIDE_WINDOW_CONFLICT`, then
        `ERR_DR_WINDOW_CONFLICT`, then `ERR_WORK_ORDER_WINDOW_CONFLICT`, then
        `ERR_BASELINE_DATA_INSUFFICIENT`, then `ERR_DEMAND_DATA_MISSING`."

        Design: Difficulty/priority_pair_validation_conflict/override_window_conflict_outranks_budget_exceeded
        """
        ctx = _store_with_one_scheduled_override(api)
        assert ctx["override_a"]["state"] == "SCHEDULED"
        assert ctx["override_a"]["projected_kwh"] == pytest.approx(300.00, abs=0.01)

        response = api.create_lighting_override(
            ctx["store_id"],
            f.create_lighting_override_payload(
                zone="SALES_FLOOR", override_type="SCHEDULE_EXTEND",
                start_iso="2026-08-10T07:00:00Z", end_iso="2026-08-10T09:00:00Z",
                zone_load_kw=120.0, requested_reason="both rules violated at once",
            ),
            make_store_manager_headers(ctx["store_id"]),
        )

        validate_error(response, ApiErrorId.ERR_OVERRIDE_WINDOW_CONFLICT.value, 409)

    def test_the_same_request_on_an_adjacent_window_reports_the_budget(self, api):
        """Removing the overlap exposes the fiscal gate alone.

        The PRD states: "A creation request is admitted only when the store's
        current `override_kwh_used_month` plus the new `projected_kwh`, rounded half
        up to two decimal places, is less than or equal to
        `override_budget_kwh_month`; equality is admitted. Exceeding the allowance
        is refused with `ERR_OVERRIDE_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/override_window_conflict_outranks_budget_exceeded
        """
        ctx = _store_with_one_scheduled_override(api)

        response = api.create_lighting_override(
            ctx["store_id"],
            f.create_lighting_override_payload(
                zone="SALES_FLOOR", override_type="SCHEDULE_EXTEND",
                start_iso="2026-08-10T08:00:00Z", end_iso="2026-08-10T10:00:00Z",
                zone_load_kw=120.0, requested_reason="budget only",
            ),
            make_store_manager_headers(ctx["store_id"]),
        )

        validate_error(response, ApiErrorId.ERR_OVERRIDE_BUDGET_EXCEEDED.value, 422)

    def test_neither_refused_request_charges_the_allowance(self, api):
        """Only the admitted override is stored and charged.

        The PRD states: "A store's `override_kwh_used_month` is the sum of
        `projected_kwh` across that store's overrides whose `state` is `SCHEDULED`,
        `ACTIVE` or `EXPIRED` and whose `start_iso` falls inside the calendar month,
        in UTC, of the current logical clock."

        Design: Difficulty/priority_pair_validation_conflict/override_window_conflict_outranks_budget_exceeded
        """
        ctx = _store_with_one_scheduled_override(api)
        manager = make_store_manager_headers(ctx["store_id"])

        api.create_lighting_override(
            ctx["store_id"],
            f.create_lighting_override_payload(
                zone="SALES_FLOOR", start_iso="2026-08-10T07:00:00Z",
                end_iso="2026-08-10T09:00:00Z", zone_load_kw=120.0,
                requested_reason="both rules violated at once",
            ),
            manager,
        )
        api.create_lighting_override(
            ctx["store_id"],
            f.create_lighting_override_payload(
                zone="SALES_FLOOR", start_iso="2026-08-10T08:00:00Z",
                end_iso="2026-08-10T10:00:00Z", zone_load_kw=120.0,
                requested_reason="budget only",
            ),
            manager,
        )

        store = fx.read_store(api, ctx["store_id"])
        rows, meta = fx.list_overrides(api, ctx["store_id"])

        assert store["override_kwh_used_month"] == pytest.approx(300.00, abs=0.01)
        assert meta["total_count"] == 1
        assert len(rows) == 1


FROZEN_CASE = {
    "case_code": "CASE-PP2-01",
    "case_type": "LOW_TEMP",
    "product_class": "FROZEN",
    "alarm_high_f": 5.0,
    "alarm_low_f": -20.0,
    "product_value_usd": 21000.00,
}

NORTHERN_RATES = {
    "utility_name": "Northern Grid",
    "rate_family": "TOU_DEMAND",
    "demand_charge_per_kw": 14.50,
    "rate_on_peak": 0.1450,
    "rate_off_peak": 0.0800,
}

PP2_BASELINE = [
    f.demand_interval("2026-07-31T14:00:00Z", 1290.5, True),
    f.demand_interval("2026-07-31T15:00:00Z", 1275.0, True),
    f.demand_interval("2026-07-31T16:00:00Z", 1245.0, True),
]


def _locked_store_with_a_scheduled_and_a_notified_event(api):
    """A LOCKED store holding one event still SCHEDULED and one already NOTIFIED."""
    ctx = fx.setup_commissioned_store(
        api, clock="2026-08-01T07:00:00Z", code="STR-PP2", climate_zone="COLD",
        floor_area_sqft=118000,
    )
    account_1 = fx.create_account(
        api, ctx["store_id"], rate_schedule_code="TOU-A", **NORTHERN_RATES
    )
    event_a = fx.create_event(
        api, account_1["id"], program_code="CPP-2026",
        curtailment_start_iso="2026-08-01T05:00:00Z",
        curtailment_end_iso="2026-08-01T06:00:00Z", target_reduction_kw=150.0,
    )
    ctx["event_a"] = event_a
    case = fx.create_case(api, ctx["store_id"], **FROZEN_CASE)
    fx.post_reading(api, case["id"], ctx["store_id"], 8.0, "2026-08-01T04:00:00Z")
    second = fx.post_reading(api, case["id"], ctx["store_id"], 9.5, "2026-08-01T04:15:00Z")
    ctx["excursion_id"] = second["excursion_id"]
    ctx["locking_reading"] = fx.post_reading(
        api, case["id"], ctx["store_id"], 11.0, "2026-08-01T06:00:00Z"
    )
    # The second event is notified only after the lock, so the escalation cascade
    # cannot opt it out and it genuinely sits NOTIFIED on a locked store.
    account_2 = fx.create_account(
        api, ctx["store_id"], rate_schedule_code="TOU-B", **NORTHERN_RATES
    )
    fx.ingest_intervals(api, account_2["id"], PP2_BASELINE)
    event_b = fx.create_event(
        api, account_2["id"], program_code="CPP-2026",
        curtailment_start_iso="2026-08-01T06:30:00Z",
        curtailment_end_iso="2026-08-01T07:30:00Z", target_reduction_kw=150.0,
    )
    ctx["event_b_id"] = event_b["id"]
    ctx["event_b"] = fx.notify_event(api, event_b["id"])
    ctx["account_1_id"] = account_1["id"]
    ctx["account_2_id"] = account_2["id"]
    return ctx


class TestEventStateOutranksFoodSafetyHold:
    def test_activating_a_scheduled_event_on_a_locked_store_reports_the_state(self, api):
        """State admissibility is ranked above the business-safety gate.

        The PRD states: "7. State admissibility of the target resource — one of
        `ERR_BMS_STATE_INVALID`, `ERR_STANDARD_STATE_INVALID`,
        `ERR_BILL_STATE_INVALID`, `ERR_DR_EVENT_STATE_INVALID`,
        `ERR_SETTLEMENT_STATE_INVALID`, `ERR_CASE_STATE_INVALID`,
        `ERR_EXCURSION_STATE_INVALID`, `ERR_OVERRIDE_STATE_INVALID`,
        `ERR_FAULT_STATE_INVALID`, `ERR_WORK_ORDER_STATE_INVALID` or
        `ERR_RETROFIT_STATE_INVALID`, in that relative order when more than one
        could apply." — and the business-safety gate `ERR_FOOD_SAFETY_HOLD` is
        only level 9.

        Design: Difficulty/priority_pair_validation_conflict/dr_state_invalid_outranks_food_safety_hold
        """
        ctx = _locked_store_with_a_scheduled_and_a_notified_event(api)
        assert ctx["event_a"]["event_state"] == "SCHEDULED"
        assert ctx["locking_reading"]["excursion_state"] == "ESCALATED"
        assert ctx["locking_reading"]["store_energy_posture"] == "LOCKED"

        response = api.activate_demand_response_event(ctx["event_a"]["id"], fx.MANAGER)

        validate_error(response, ApiErrorId.ERR_DR_EVENT_STATE_INVALID.value, 409)

    def test_activating_a_notified_event_on_the_same_store_reports_the_hold(self, api):
        """With the state rule satisfied only the food-safety gate remains.

        The PRD states: "An `EnergyManager` activating an event requires
        `event_state` to be `NOTIFIED`, requires the owning account's store to be
        in `NORMAL` or `CONSTRAINED` — a store in `CURTAILED` or `LOCKED` is
        refused with `ERR_FOOD_SAFETY_HOLD`".

        Design: Difficulty/priority_pair_validation_conflict/dr_state_invalid_outranks_food_safety_hold
        """
        ctx = _locked_store_with_a_scheduled_and_a_notified_event(api)
        assert ctx["event_b"]["event_state"] == "NOTIFIED"
        assert ctx["event_b"]["baseline_kw"] == pytest.approx(1270.17, abs=0.01)

        response = api.activate_demand_response_event(ctx["event_b_id"], fx.MANAGER)

        validate_error(response, ApiErrorId.ERR_FOOD_SAFETY_HOLD.value, 409)

    def test_neither_refusal_advances_an_event_or_releases_the_lock(self, api):
        """Both events keep the state they held and the store stays LOCKED.

        The PRD states: "Checks are therefore evaluated in a single global order,
        and the **first** violated check determines the response; later checks are
        never reached and never reported."

        Design: Difficulty/priority_pair_validation_conflict/dr_state_invalid_outranks_food_safety_hold
        """
        ctx = _locked_store_with_a_scheduled_and_a_notified_event(api)

        api.activate_demand_response_event(ctx["event_a"]["id"], fx.MANAGER)
        api.activate_demand_response_event(ctx["event_b_id"], fx.MANAGER)

        events_1, _ = fx.list_events(api, ctx["account_1_id"])
        events_2, _ = fx.list_events(api, ctx["account_2_id"])
        store = fx.read_store(api, ctx["store_id"])

        assert fx.find_row(events_1, ctx["event_a"]["id"])["event_state"] == "SCHEDULED"
        assert fx.find_row(events_2, ctx["event_b_id"])["event_state"] == "NOTIFIED"
        assert store["energy_posture"] == "LOCKED"


PP3_RATES = {
    "utility_name": "Midland Power",
    "rate_schedule_code": "TOU-GS3",
    "rate_family": "TOU_DEMAND",
    "demand_charge_per_kw": 14.50,
    "rate_on_peak": 0.1450,
    "rate_off_peak": 0.0800,
    "ratchet_peak_kw": 1500.0,
}

PP3_BILL = {
    "period_start_iso": "2026-06-01T00:00:00Z",
    "period_end_iso": "2026-07-01T00:00:00Z",
    "on_peak_kwh": 240000,
    "off_peak_kwh": 518000,
    "billed_kwh": 758000,
    "billed_peak_kw": 1402.0,
    "billed_amount_usd": 102500.00,
}

ADJUSTMENT = {"adjusted_amount_usd": 99996.04}


def _flagged_bill_recomputed_by_the_dual_role_operator(api):
    """A VARIANCE_FLAGGED bill whose recompute is stamped with u_dual_1."""
    ctx = fx.setup_commissioned_store(api, code="STR-PP3")
    account = fx.create_account(api, ctx["store_id"], **PP3_RATES)
    fx.ingest_intervals(
        api, account["id"], [f.demand_interval("2026-06-10T18:00:00Z", 1310.5, True)]
    )
    bill = fx.create_bill(api, account["id"], **PP3_BILL)
    ctx["account_id"] = account["id"]
    ctx["bill_id"] = bill["id"]
    ctx["flagged"] = fx.recompute_bill(
        api, bill["id"], make_energy_analyst_headers("u_dual_1")
    )
    return ctx


class TestSegregationOfDutiesOutranksBillState:
    def test_the_recomputer_authorising_a_flagged_bill_is_refused_on_duty(self, api):
        """Duty separation answers first even though the bill is not disputed.

        The PRD states: "Duty separation outranks state admissibility: when the
        operator who recomputed a bill tries to authorise the adjustment of a bill
        that is not even in a disputed condition, the answer is
        `ERR_SEGREGATION_OF_DUTIES`, not `ERR_BILL_STATE_INVALID`".

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_bill_state_invalid
        """
        ctx = _flagged_bill_recomputed_by_the_dual_role_operator(api)
        assert ctx["flagged"]["validation_state"] == "VARIANCE_FLAGGED"
        assert ctx["flagged"]["variance_pct"] == pytest.approx(2.50, abs=0.01)
        assert ctx["flagged"]["recomputed_by_user_id"] == "u_dual_1"

        response = api.adjust_utility_bill(
            ctx["bill_id"], ADJUSTMENT, make_energy_manager_headers("u_dual_1")
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    def test_a_different_manager_on_the_same_bill_is_refused_on_state(self, api):
        """With the duty rule satisfied the state rule reports instead.

        The PRD states: "the bill must actually be `DISPUTED`, or the answer is
        `ERR_BILL_STATE_INVALID`".

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_bill_state_invalid
        """
        ctx = _flagged_bill_recomputed_by_the_dual_role_operator(api)

        response = api.adjust_utility_bill(
            ctx["bill_id"], ADJUSTMENT, make_energy_manager_headers("u_manager_2")
        )

        validate_error(response, ApiErrorId.ERR_BILL_STATE_INVALID.value, 409)

    def test_the_duty_refusal_survives_the_bill_reaching_disputed(self, api):
        """Satisfying the state rule does not unlock the recomputer.

        The PRD states: "Three gates guard it, in this order: the authorising
        operator must differ from the one recorded in `recomputed_by_user_id`, or
        the request is refused with `ERR_SEGREGATION_OF_DUTIES`; the bill must
        actually be `DISPUTED`, or the answer is `ERR_BILL_STATE_INVALID`".

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_bill_state_invalid
        """
        ctx = _flagged_bill_recomputed_by_the_dual_role_operator(api)

        disputed = get_success_data(
            api.dispute_utility_bill(
                ctx["bill_id"],
                f.dispute_payload("demand ratchet applied to the wrong month"),
                make_energy_analyst_headers("u_analyst_3"),
            )
        )
        response = api.adjust_utility_bill(
            ctx["bill_id"], ADJUSTMENT, make_energy_manager_headers("u_dual_1")
        )

        assert disputed["validation_state"] == "DISPUTED"
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    def test_a_second_manager_settles_the_dispute_once_both_gates_pass(self, api):
        """The adjustment lands only for an operator who did not recompute.

        The PRD states: "Settling that dispute is an `EnergyManager` action that
        moves the bill `DISPUTED → ADJUSTED`, storing the negotiated
        `adjusted_amount_usd` and recording the authorising operator in
        `adjusted_by_user_id`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_bill_state_invalid
        """
        ctx = _flagged_bill_recomputed_by_the_dual_role_operator(api)
        get_success_data(
            api.dispute_utility_bill(
                ctx["bill_id"],
                f.dispute_payload("demand ratchet applied to the wrong month"),
                make_energy_analyst_headers("u_analyst_3"),
            )
        )

        adjusted = get_success_data(
            api.adjust_utility_bill(
                ctx["bill_id"], ADJUSTMENT, make_energy_manager_headers("u_manager_2")
            )
        )

        assert adjusted["validation_state"] == "ADJUSTED"
        assert adjusted["adjusted_by_user_id"] == "u_manager_2"
        assert adjusted["adjusted_amount_usd"] == pytest.approx(99996.04, abs=0.01)
