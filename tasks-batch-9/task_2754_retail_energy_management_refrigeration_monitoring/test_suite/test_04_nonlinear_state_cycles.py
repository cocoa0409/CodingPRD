"""Cyclic and parallel state dimensions: excursions, events and the gateway."""
import pytest

from prd_bench_local_runner.testing import get_success_data
from test_helpers import factories as f, fixtures as fx
from test_helpers.test_users import (
    make_energy_manager_headers,
    make_store_manager_headers,
)

CASE = {
    "case_code": "CASE-NL1-01",
    "case_type": "MEDIUM_TEMP",
    "product_class": "DAIRY",
    "alarm_high_f": 41.0,
    "alarm_low_f": 28.0,
    "product_value_usd": 6400.00,
}


def _case_with_open_excursion(api):
    """A COLD / NEIGHBORHOOD store whose dairy case has an OPEN excursion after
    two breaching readings fifteen minutes apart."""
    ctx = fx.setup_commissioned_store(
        api, clock="2026-08-01T12:00:00Z", code="STR-NL1",
        climate_zone="COLD", store_format="NEIGHBORHOOD", floor_area_sqft=42000,
    )
    case = fx.create_case(api, ctx["store_id"], **CASE)
    ctx["case_id"] = case["id"]
    ctx["r1"] = fx.post_reading(api, case["id"], ctx["store_id"], 42.0, "2026-08-01T04:00:00Z")
    ctx["r2"] = fx.post_reading(api, case["id"], ctx["store_id"], 42.5, "2026-08-01T04:15:00Z")
    ctx["excursion_id"] = ctx["r2"]["excursion_id"]
    return ctx


class TestExcursionAcknowledgeRebreachCycle:
    def test_a_further_breach_reverts_an_acknowledged_excursion_to_open(self, api):
        """ACKNOWLEDGED is left and re-entered on the same excursion row.

        The PRD states: "Otherwise the excursion is `OPEN`, and an excursion that
        a store manager had already acknowledged reverts `ACKNOWLEDGED → OPEN`,
        which is the cyclic behaviour that keeps a re-breaching case from looking
        handled."

        Design: Difficulty/non_linear_state_machine/excursion_acknowledge_rebreach_cycle
        """
        ctx = _case_with_open_excursion(api)
        manager = make_store_manager_headers(ctx["store_id"])

        first_ack = get_success_data(api.acknowledge_excursion(ctx["excursion_id"], manager))
        assert first_ack["state"] == "ACKNOWLEDGED"
        assert first_ack["acknowledged_by_user_id"] == ctx["store_id"]

        rebreach = fx.post_reading(
            api, ctx["case_id"], ctx["store_id"], 41.5, "2026-08-01T04:30:00Z"
        )
        assert rebreach["excursion_state"] == "OPEN"

        second_ack = get_success_data(api.acknowledge_excursion(ctx["excursion_id"], manager))
        assert second_ack["state"] == "ACKNOWLEDGED"

    def test_exposure_and_peak_advance_monotonically_across_the_cycle(self, api):
        """Exposure climbs 15 -> 30 and the peak stays the furthest deviation.

        The PRD states: "It sets `last_breach_iso` to the new reading instant and
        re-evaluates `peak_temp_f`, which records the actual `temp_f` of whichever
        breaching reading so far has deviated furthest from the nearer of the two
        alarm bounds; when two readings tie on deviation, the earlier reading
        instant wins."

        Design: Difficulty/non_linear_state_machine/excursion_acknowledge_rebreach_cycle
        """
        ctx = _case_with_open_excursion(api)
        assert ctx["r1"]["monitoring_state"] == "ARMED"
        assert ctx["r1"]["consecutive_breach_count"] == 1
        assert ctx["r2"]["excursion_state"] == "OPEN"
        assert ctx["r2"]["exposure_minutes"] == 15

        get_success_data(
            api.acknowledge_excursion(
                ctx["excursion_id"], make_store_manager_headers(ctx["store_id"])
            )
        )
        rebreach = fx.post_reading(
            api, ctx["case_id"], ctx["store_id"], 41.5, "2026-08-01T04:30:00Z"
        )

        assert rebreach["exposure_minutes"] == 30
        assert rebreach["peak_temp_f"] == pytest.approx(42.5, abs=0.05)
        assert rebreach["consecutive_breach_count"] == 3
        assert rebreach["mandatory_disposition"] == "NONE"

    def test_the_case_and_store_stay_alarmed_through_the_cycle(self, api):
        """The case remains in ALARM and the store in CONSTRAINED.

        The PRD states: "Opening an excursion moves the case `ARMED → ALARM` and
        increments the store's `alarm_case_count`, and the store immediately
        recomputes its posture, raising `NORMAL → CONSTRAINED`."

        Design: Difficulty/non_linear_state_machine/excursion_acknowledge_rebreach_cycle
        """
        ctx = _case_with_open_excursion(api)
        get_success_data(
            api.acknowledge_excursion(
                ctx["excursion_id"], make_store_manager_headers(ctx["store_id"])
            )
        )
        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 41.5, "2026-08-01T04:30:00Z")

        case = get_success_data(api.get_refrigeration_case(ctx["case_id"], fx.MANAGER))
        excursion = fx.read_excursion(api, ctx["excursion_id"])
        store = fx.read_store(api, ctx["store_id"])

        assert case["monitoring_state"] == "ALARM"
        assert excursion["first_breach_iso"].startswith("2026-08-01T04:00:00")
        assert excursion["last_breach_iso"].startswith("2026-08-01T04:30:00")
        assert store["energy_posture"] == "CONSTRAINED"


TOU_RATES = {
    "utility_name": "Midland Power",
    "rate_schedule_code": "TOU-GS3",
    "rate_family": "TOU_DEMAND",
    "demand_charge_per_kw": 14.50,
    "rate_on_peak": 0.1450,
    "rate_off_peak": 0.0800,
}

SHORTFALL_INTERVALS = [
    f.demand_interval("2026-08-04T14:00:00Z", 1290.5, True),
    f.demand_interval("2026-08-04T15:00:00Z", 1275.0, True),
    f.demand_interval("2026-08-04T16:00:00Z", 1245.0, True),
    f.demand_interval("2026-08-05T14:00:00Z", 1250.0, True, is_dr_event_day=True),
    f.demand_interval("2026-08-05T14:15:00Z", 1255.5, True, is_dr_event_day=True),
    f.demand_interval("2026-08-05T14:30:00Z", 1240.0, True, is_dr_event_day=True),
    f.demand_interval("2026-08-05T14:45:00Z", 1259.5, True, is_dr_event_day=True),
]

SHORTFALL_EVENT = {
    "program_code": "CPP-2026",
    "curtailment_start_iso": "2026-08-05T14:00:00Z",
    "curtailment_end_iso": "2026-08-05T15:00:00Z",
    "target_reduction_kw": 200.0,
}


def _completed_shortfall_event(api):
    """An event carried to COMPLETED by the sweep over an under-performing run."""
    ctx = fx.setup_commissioned_store(api, code="STR-NL2")
    account = fx.create_account(api, ctx["store_id"], **TOU_RATES)
    fx.ingest_intervals(api, account["id"], SHORTFALL_INTERVALS)
    event = fx.create_event(api, account["id"], **SHORTFALL_EVENT)
    ctx["account_id"] = account["id"]
    ctx["event_id"] = event["id"]
    ctx["event_created"] = event
    ctx["notified"] = fx.notify_event(api, event["id"])
    fx.set_clock(api, SHORTFALL_EVENT["curtailment_start_iso"])
    ctx["activated"] = fx.activate_event(api, event["id"])
    ctx["sweep"] = fx.set_clock(api, SHORTFALL_EVENT["curtailment_end_iso"])
    return ctx


class TestEventStateAndSettlementStateAreIndependent:
    def test_the_participation_dimension_advances_while_settlement_stays_pending(self, api):
        """SCHEDULED -> NOTIFIED -> ACTIVE -> COMPLETED leaves settlement PENDING.

        The PRD states: "during the sweep, every event whose `event_state` is
        `ACTIVE` and whose `curtailment_end_iso` is at or before the new clock
        value advances `ACTIVE → COMPLETED`, its settlement dimension untouched,
        after which the store's posture is recomputed and falls out of `CURTAILED`
        if no other event of the account remains `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/dr_event_parallel_state_dimensions
        """
        ctx = _completed_shortfall_event(api)

        assert ctx["event_created"]["settlement_state"] == "PENDING"
        assert ctx["notified"]["event_state"] == "NOTIFIED"
        assert ctx["activated"]["event_state"] == "ACTIVE"
        assert ctx["activated"]["settlement_state"] == "PENDING"
        assert ctx["sweep"]["dr_events_completed"] == 1
        assert fx.read_store(api, ctx["store_id"])["energy_posture"] == "NORMAL"

    def test_settlement_moves_twice_without_perturbing_the_participation_state(self, api):
        """PENDING -> SETTLED -> REVERSED all happen beneath COMPLETED.

        The PRD states: "The participation dimension stays at `COMPLETED`
        throughout."

        Design: Difficulty/non_linear_state_machine/dr_event_parallel_state_dimensions
        """
        ctx = _completed_shortfall_event(api)

        settled = fx.settle_event(api, ctx["event_id"])
        assert settled["event_state"] == "COMPLETED"
        assert settled["settlement_state"] == "SETTLED"

        reversed_event = get_success_data(
            api.reverse_demand_response_settlement(
                ctx["event_id"],
                f.reversal_payload("meter data corrected by utility"),
                make_energy_manager_headers("u_manager_nl2"),
            )
        )

        assert reversed_event["event_state"] == "COMPLETED"
        assert reversed_event["settlement_state"] == "REVERSED"
        assert reversed_event["reversal_reason"] == "meter data corrected by utility"

    def test_a_shortfall_run_prices_a_penalty_and_keeps_it_after_reversal(self, api):
        """Performance below the floor pays a penalty, retained as evidence.

        The PRD states: "When performance falls below that floor the position
        reverses: `incentive_usd` is 0.00 and `penalty_usd` is the shortfall — the
        obligation minus the delivered total — multiplied by 0.18 dollars per
        kilowatt-hour, rounded half up to two decimal places."

        Design: Difficulty/non_linear_state_machine/dr_event_parallel_state_dimensions
        """
        ctx = _completed_shortfall_event(api)
        assert ctx["notified"]["baseline_kw"] == pytest.approx(1270.17, abs=0.01)

        settled = fx.settle_event(api, ctx["event_id"])
        assert settled["total_reduction_kwh"] == pytest.approx(18.92, abs=0.001)
        assert settled["performance_pct"] == pytest.approx(9.5, abs=0.05)
        assert settled["incentive_usd"] == pytest.approx(0.00, abs=0.01)
        assert settled["penalty_usd"] == pytest.approx(32.59, abs=0.01)

        reversed_event = get_success_data(
            api.reverse_demand_response_settlement(
                ctx["event_id"],
                f.reversal_payload("meter data corrected by utility"),
                make_energy_manager_headers("u_manager_nl2"),
            )
        )
        assert reversed_event["performance_pct"] == pytest.approx(9.5, abs=0.05)
        assert reversed_event["penalty_usd"] == pytest.approx(32.59, abs=0.01)


URGENT_REFRIGERATION_FAULT = {
    "equipment_ref": "RACK-B2",
    "equipment_class": "REFRIGERATION",
    "fault_code": "SUCTION_PRESSURE_HIGH",
    "severity": "MAJOR",
    "occurrence_count": 6,
    "affected_load_kw": 20.0,
}


def _degraded_store_with_urgent_work_order(api):
    """A HOT_DRY store degraded by the triage of an urgent refrigeration fault."""
    ctx = fx.setup_commissioned_store(
        api, code="STR-NL3", climate_zone="HOT_DRY", floor_area_sqft=110000,
    )
    fault = fx.create_fault(api, ctx["store_id"], **URGENT_REFRIGERATION_FAULT)
    ctx["fault_id"] = fault["id"]
    ctx["fault_score"] = fault["fault_score"]
    ctx["triage"] = fx.triage_fault(api, fault["id"])
    ctx["work_order_id"] = ctx["triage"]["work_order_id"]
    return ctx


class TestBmsStatusDegradeAndRecommissionCycle:
    def test_active_is_re_entered_only_through_an_explicit_recommission(self, api):
        """DEGRADED -> COMMISSIONING -> ACTIVE closes the cycle.

        The PRD states: "Recovery from `DEGRADED` is deliberately manual —
        completing the offending work order clears the *posture* input but leaves
        `bms_status` at `DEGRADED` until an engineer explicitly re-commissions and
        re-activates."

        Design: Difficulty/non_linear_state_machine/store_bms_status_degrade_recommission_cycle
        """
        ctx = _degraded_store_with_urgent_work_order(api)
        assert ctx["fault_score"] == pytest.approx(89.3, abs=0.05)
        assert ctx["triage"]["work_order_priority"] == "URGENT"
        assert ctx["triage"]["store_bms_status"] == "DEGRADED"
        assert ctx["triage"]["store_energy_posture"] == "CONSTRAINED"

        after_cascade = fx.read_store(api, ctx["store_id"])
        recommissioned = fx.commission_store(
            api, ctx["store_id"], ctx["standard_id"], after_cascade["version"]
        )
        assert recommissioned["bms_status"] == "COMMISSIONING"

        reactivated = fx.activate_store_bms(api, ctx["store_id"])
        assert reactivated["bms_status"] == "ACTIVE"
        assert reactivated["energy_posture"] == "CONSTRAINED"
        assert reactivated["urgent_work_order_count"] == 1
        assert reactivated["active_standard_id"] == ctx["standard_id"]

    def test_the_recommission_needs_the_version_the_cascade_left_behind(self, api):
        """The fault cascade bumps the store version, so a fresh read is required.

        The PRD states: "A store leaves `ACTIVE` for `DEGRADED` in exactly two
        circumstances, and in both the store's `version` increments and the posture
        is recomputed immediately afterward, raising `NORMAL → CONSTRAINED`."

        Design: Difficulty/non_linear_state_machine/store_bms_status_degrade_recommission_cycle
        """
        ctx = _degraded_store_with_urgent_work_order(api)

        after_cascade = fx.read_store(api, ctx["store_id"])

        assert after_cascade["bms_status"] == "DEGRADED"
        assert after_cascade["version"] > ctx["version_at_commissioning"]
        recommissioned = fx.commission_store(
            api, ctx["store_id"], ctx["standard_id"], after_cascade["version"]
        )
        assert recommissioned["version"] == after_cascade["version"] + 1

    def test_completing_the_work_order_clears_the_posture_but_not_the_status(self, api):
        """Completion resolves the fault and frees the posture only.

        The PRD states: "Because that fault is no longer triaged, the store's
        `urgent_work_order_count` decrements when the completed order was `URGENT`.
        Because that count changed, the store recomputes its posture, falling
        `CONSTRAINED → NORMAL` when no other constraining input holds."

        Design: Difficulty/non_linear_state_machine/store_bms_status_degrade_recommission_cycle
        """
        ctx = _degraded_store_with_urgent_work_order(api)
        after_cascade = fx.read_store(api, ctx["store_id"])
        fx.commission_store(api, ctx["store_id"], ctx["standard_id"], after_cascade["version"])
        fx.activate_store_bms(api, ctx["store_id"])

        work_order = fx.complete_work_order(
            api, ctx["work_order_id"], "compressor rack B2 valve replaced"
        )
        fault = get_success_data(api.get_fault_diagnostic(ctx["fault_id"], fx.TECH))
        store = fx.read_store(api, ctx["store_id"])

        assert work_order["state"] == "COMPLETED"
        assert fault["state"] == "RESOLVED"
        assert store["urgent_work_order_count"] == 0
        assert store["energy_posture"] == "NORMAL"
        assert store["bms_status"] == "ACTIVE"
