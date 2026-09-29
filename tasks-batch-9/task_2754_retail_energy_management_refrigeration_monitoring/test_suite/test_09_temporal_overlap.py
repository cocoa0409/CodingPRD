"""Three overlap resources with three different interval semantics."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error
from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_store_manager_headers

RT1_STORE = {
    "code": "STR-RT1",
    "floor_area_sqft": 120000,
    "override_budget_kwh_month": 500.0,
}


def _store_with_two_adjacent_sales_floor_windows(api):
    """SALES_FLOOR holds 00:00-08:00 and then 08:00-16:00 of the same day."""
    ctx = fx.setup_commissioned_store(api, **RT1_STORE)
    ctx["override_a"] = fx.create_override(
        api, ctx["store_id"], zone="SALES_FLOOR", override_type="SCHEDULE_EXTEND",
        start_iso="2026-08-10T00:00:00Z", end_iso="2026-08-10T08:00:00Z",
        zone_load_kw=37.5, requested_reason="night crew A",
    )
    ctx["override_b"] = fx.create_override(
        api, ctx["store_id"], zone="SALES_FLOOR", override_type="SCHEDULE_EXTEND",
        start_iso="2026-08-10T08:00:00Z", end_iso="2026-08-10T16:00:00Z",
        zone_load_kw=12.5, requested_reason="day crew adjacency",
    )
    return ctx


STRADDLING_WINDOW = {
    "override_type": "SCHEDULE_EXTEND",
    "start_iso": "2026-08-10T07:00:00Z",
    "end_iso": "2026-08-10T09:00:00Z",
    "zone_load_kw": 10.0,
}


class TestOverrideHalfOpenWindowAdjacency:
    def test_a_window_starting_exactly_when_another_ends_is_admitted(self, api):
        """Half-open windows make touching endpoints legal.

        The PRD states: "Windows are half-open, so a request whose `start_iso`
        equals an existing override's `end_iso` for the same zone is admitted, while
        any genuine intersection is refused with `ERR_OVERRIDE_WINDOW_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/override_half_open_window_adjacency_admitted_overlap_rejected
        """
        ctx = _store_with_two_adjacent_sales_floor_windows(api)

        assert ctx["override_a"]["projected_kwh"] == pytest.approx(300.00, abs=0.01)
        assert ctx["override_b"]["projected_kwh"] == pytest.approx(100.00, abs=0.01)
        assert ctx["override_b"]["state"] == "SCHEDULED"
        assert ctx["override_b"]["zone"] == "SALES_FLOOR"

    def test_a_window_straddling_that_instant_is_refused(self, api):
        """The rejection is temporal, not fiscal — 20.00 kWh would have fit.

        The PRD states: "Overlap is judged per store and zone, and only against
        overrides in `SCHEDULED` or `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/override_half_open_window_adjacency_admitted_overlap_rejected
        """
        ctx = _store_with_two_adjacent_sales_floor_windows(api)

        response = api.create_lighting_override(
            ctx["store_id"],
            f.create_lighting_override_payload(
                zone="SALES_FLOOR", requested_reason="straddles the boundary",
                **STRADDLING_WINDOW,
            ),
            make_store_manager_headers(ctx["store_id"]),
        )

        validate_error(response, ApiErrorId.ERR_OVERRIDE_WINDOW_CONFLICT.value, 409)
        assert fx.read_store(api, ctx["store_id"])[
            "override_kwh_used_month"
        ] == pytest.approx(400.00, abs=0.01)

    def test_the_same_straddling_window_on_another_zone_is_admitted(self, api):
        """The zone is part of the resource key.

        The PRD states: "The same zone may hold overrides of different types at
        different times, and two different zones of one store never conflict with
        each other."

        Design: Difficulty/resource_temporal_overlap/override_half_open_window_adjacency_admitted_overlap_rejected
        """
        ctx = _store_with_two_adjacent_sales_floor_windows(api)
        api.create_lighting_override(
            ctx["store_id"],
            f.create_lighting_override_payload(
                zone="SALES_FLOOR", requested_reason="straddles the boundary",
                **STRADDLING_WINDOW,
            ),
            make_store_manager_headers(ctx["store_id"]),
        )

        parking = fx.create_override(
            api, ctx["store_id"], zone="PARKING",
            requested_reason="different zone, same window", **STRADDLING_WINDOW,
        )
        rows, meta = fx.list_overrides(api, ctx["store_id"])

        assert parking["zone"] == "PARKING"
        assert parking["projected_kwh"] == pytest.approx(20.00, abs=0.01)
        assert fx.read_store(api, ctx["store_id"])[
            "override_kwh_used_month"
        ] == pytest.approx(420.00, abs=0.01)
        assert meta["total_count"] == 3
        assert len(rows) == 3


def _account_with_one_scheduled_event(api):
    """A COLD / EXPRESS store whose single account holds a SCHEDULED 14:00-15:00 event."""
    ctx = fx.setup_commissioned_store(
        api, code="STR-RT2", climate_zone="COLD", store_format="EXPRESS",
        floor_area_sqft=14000,
    )
    account = fx.create_account(
        api, ctx["store_id"], utility_name="Northern Grid",
        rate_schedule_code="TOU-GS1", rate_family="TOU_DEMAND",
        demand_charge_per_kw=12.00, rate_on_peak=0.1400, rate_off_peak=0.0790,
    )
    ctx["account_id"] = account["id"]
    ctx["event_a"] = fx.create_event(
        api, account["id"], program_code="CPP-2026",
        curtailment_start_iso="2026-08-05T14:00:00Z",
        curtailment_end_iso="2026-08-05T15:00:00Z", target_reduction_kw=200.0,
    )
    return ctx


class TestDrEventClosedWindowWithRecoveryGap:
    def test_touching_curtailment_endpoints_already_collide(self, api):
        """A window opening exactly when another closes is a conflict here.

        The PRD states: "Crowding is judged generously in the utility's favour:
        event windows are treated as closed intervals inclusive of both endpoints, so
        touching endpoints already collide".

        Design: Difficulty/resource_temporal_overlap/dr_event_closed_window_with_recovery_gap_rejected
        """
        ctx = _account_with_one_scheduled_event(api)
        assert ctx["event_a"]["event_state"] == "SCHEDULED"

        response = api.create_demand_response_event(
            ctx["account_id"],
            f.create_demand_response_event_payload(
                program_code="CPP-2026",
                curtailment_start_iso="2026-08-05T15:00:00Z",
                curtailment_end_iso="2026-08-05T16:00:00Z",
                target_reduction_kw=150.0,
            ),
            fx.MANAGER,
        )

        validate_error(response, ApiErrorId.ERR_DR_WINDOW_CONFLICT.value, 409)

    def test_a_gap_one_minute_short_of_the_recovery_separation_is_refused(self, api):
        """239 minutes of separation is not enough.

        The PRD states: "beyond that a mandatory recovery separation of four hours
        applies, measured forward from the earlier event's `curtailment_end_iso` — a
        new event whose `curtailment_start_iso` falls less than 240 minutes after an
        existing event ends is refused even though the windows themselves do not
        overlap."

        Design: Difficulty/resource_temporal_overlap/dr_event_closed_window_with_recovery_gap_rejected
        """
        ctx = _account_with_one_scheduled_event(api)

        response = api.create_demand_response_event(
            ctx["account_id"],
            f.create_demand_response_event_payload(
                program_code="CPP-2026",
                curtailment_start_iso="2026-08-05T18:59:00Z",
                curtailment_end_iso="2026-08-05T19:59:00Z",
                target_reduction_kw=150.0,
            ),
            fx.MANAGER,
        )

        validate_error(response, ApiErrorId.ERR_DR_WINDOW_CONFLICT.value, 409)

    def test_a_start_exactly_four_hours_after_the_earlier_end_is_admitted(self, api):
        """240 minutes exactly clears the separation.

        The PRD states: "It is also refused with `ERR_DR_WINDOW_CONFLICT` (HTTP 409)
        when it would crowd another event of the same account whose `event_state` is
        `SCHEDULED`, `NOTIFIED` or `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/dr_event_closed_window_with_recovery_gap_rejected
        """
        ctx = _account_with_one_scheduled_event(api)
        for start, end in [
            ("2026-08-05T15:00:00Z", "2026-08-05T16:00:00Z"),
            ("2026-08-05T18:59:00Z", "2026-08-05T19:59:00Z"),
        ]:
            api.create_demand_response_event(
                ctx["account_id"],
                f.create_demand_response_event_payload(
                    program_code="CPP-2026", curtailment_start_iso=start,
                    curtailment_end_iso=end, target_reduction_kw=150.0,
                ),
                fx.MANAGER,
            )

        admitted = fx.create_event(
            api, ctx["account_id"], program_code="CPP-2026",
            curtailment_start_iso="2026-08-05T19:00:00Z",
            curtailment_end_iso="2026-08-05T20:00:00Z", target_reduction_kw=150.0,
        )
        rows, meta = fx.list_events(api, ctx["account_id"])

        assert admitted["event_state"] == "SCHEDULED"
        assert admitted["curtailment_start_iso"].startswith("2026-08-05T19:00:00")
        assert meta["total_count"] == 2
        assert len(rows) == 2


HVAC_FAULT = {
    "equipment_class": "HVAC",
    "fault_code": "ECON_DAMPER_STUCK",
    "severity": "MAJOR",
    "occurrence_count": 3,
    "affected_load_kw": 30.0,
}


def _store_with_three_routine_hvac_orders(api):
    """Three HVAC faults on distinct equipment, each triaged into a ROUTINE order."""
    ctx = fx.setup_commissioned_store(
        api, code="STR-RT3", climate_zone="HOT_HUMID", floor_area_sqft=130000,
    )
    ctx["faults"] = []
    ctx["triages"] = []
    for equipment_ref in ["RTU-1", "RTU-2", "RTU-3"]:
        ctx["faults"].append(
            fx.create_fault(api, ctx["store_id"], equipment_ref=equipment_ref, **HVAC_FAULT)
        )
    for fault in ctx["faults"]:
        ctx["triages"].append(fx.triage_fault(api, fault["id"]))
    ctx["work_order_ids"] = [triage["work_order_id"] for triage in ctx["triages"]]
    return ctx


class TestWorkOrderAggregateCapacity:
    def test_two_mutually_overlapping_orders_of_one_store_are_legal(self, api):
        """Crew capacity tolerates exactly two concurrent windows.

        The PRD states: "The second is per-store crew capacity: at most two work
        orders of the same store may occupy mutually overlapping windows".

        Design: Difficulty/resource_temporal_overlap/work_order_aggregate_capacity_exceeded_at_third_overlap
        """
        ctx = _store_with_three_routine_hvac_orders(api)
        assert ctx["faults"][0]["fault_score"] == pytest.approx(62.1, abs=0.05)
        assert ctx["triages"][0]["work_order_priority"] == "ROUTINE"
        assert ctx["triages"][0]["store_bms_status"] == "ACTIVE"
        assert ctx["triages"][2]["urgent_work_order_count"] == 0

        first = fx.schedule_work_order(
            api, ctx["work_order_ids"][0], "2026-08-20T08:00:00Z", "2026-08-20T12:00:00Z"
        )
        second = fx.schedule_work_order(
            api, ctx["work_order_ids"][1], "2026-08-20T09:00:00Z", "2026-08-20T13:00:00Z"
        )

        assert first["state"] == "SCHEDULED"
        assert second["state"] == "SCHEDULED"

    def test_the_third_mutual_overlap_exceeds_crew_capacity(self, api):
        """The refusal ignores equipment_ref, so it is the capacity rule that fires.

        The PRD states: "so a request is refused with
        `ERR_WORK_ORDER_CAPACITY_EXCEEDED` (HTTP 422) when two or more *other*
        `SCHEDULED` work orders of that store already overlap the requested window —
        and this rule ignores `equipment_ref` entirely, because the constraint is
        technicians, not machines."

        Design: Difficulty/resource_temporal_overlap/work_order_aggregate_capacity_exceeded_at_third_overlap
        """
        ctx = _store_with_three_routine_hvac_orders(api)
        fx.schedule_work_order(
            api, ctx["work_order_ids"][0], "2026-08-20T08:00:00Z", "2026-08-20T12:00:00Z"
        )
        fx.schedule_work_order(
            api, ctx["work_order_ids"][1], "2026-08-20T09:00:00Z", "2026-08-20T13:00:00Z"
        )

        response = api.schedule_work_order(
            ctx["work_order_ids"][2],
            f.schedule_work_order_payload("2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z"),
            fx.TECH,
        )

        validate_error(response, ApiErrorId.ERR_WORK_ORDER_CAPACITY_EXCEEDED.value, 422)

    def test_the_refused_order_schedules_onto_a_disjoint_day(self, api):
        """Moving off the crowded day clears the aggregate rule.

        The PRD states: "Scheduling a work order supplies `scheduled_start_iso` and
        `scheduled_end_iso` and is legal from `OPEN`, which advances the order
        `OPEN → SCHEDULED`".

        Design: Difficulty/resource_temporal_overlap/work_order_aggregate_capacity_exceeded_at_third_overlap
        """
        ctx = _store_with_three_routine_hvac_orders(api)
        fx.schedule_work_order(
            api, ctx["work_order_ids"][0], "2026-08-20T08:00:00Z", "2026-08-20T12:00:00Z"
        )
        fx.schedule_work_order(
            api, ctx["work_order_ids"][1], "2026-08-20T09:00:00Z", "2026-08-20T13:00:00Z"
        )
        api.schedule_work_order(
            ctx["work_order_ids"][2],
            f.schedule_work_order_payload("2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z"),
            fx.TECH,
        )

        rescheduled = fx.schedule_work_order(
            api, ctx["work_order_ids"][2], "2026-08-21T08:00:00Z", "2026-08-21T10:00:00Z"
        )
        store = fx.read_store(api, ctx["store_id"])

        assert rescheduled["state"] == "SCHEDULED"
        assert rescheduled["scheduled_start_iso"].startswith("2026-08-21T08:00:00")
        assert store["energy_posture"] == "NORMAL"
        assert store["bms_status"] == "ACTIVE"
