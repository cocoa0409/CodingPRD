"""Defect reports: filing validation, triage/deferral windows, epoch reopen,
manual-resolve guard, road-call dispatch gate, and link exclusivity."""
from test_helpers import (
    ApiErrorId,
    assert_defect_report,
    assign_mechanic,
    bus_version,
    confirm_assignment,
    create_work_order_payload,
    defect_event,
    file_defect,
    file_safety_defect,
    get_success_data,
    grant_cert,
    new_bus,
    new_mechanic,
    new_published_shift,
    new_work_order,
    run_epoch,
    schedule_wo,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_defect_create_invalid_severity_enum_returns_invalid_request(api):
    """PRD §3.8: "An `Operator` files a **DefectReport** against a bus with a
    `severity` of `SAFETY_CRITICAL`, `MAJOR`, or `MINOR`, a `defect_code` of
    `ENGINE`, `TRANSMISSION`, `BRAKES`, `ELECTRICAL`, `HVAC`, `FUEL_SYSTEM`,
    `TIRE`, or `OTHER`, a free-text `description`, and the operator-observed
    `odometer_at_report`."
    PRD §2.10: "In practical terms this means, for example, that a missing
    header (`ERR_UNAUTHENTICATED`) is reported before an unknown path id
    (`ERR_NOT_FOUND`), which in turn is reported before a malformed enum
    (`ERR_VALIDATION`), which is reported before an illegal state transition
    (`ERR_INVALID_STATE`)"

    Design: Corner/entities/defect_create_invalid_severity_enum_returns_invalid_request
    """
    bus = new_bus(fleet_number="D2", vin="VIND2", initial_odometer_miles=100)
    res = api.create_defect_report(
        {
            "bus_id": bus["id"],
            "severity": "CATASTROPHIC",
            "defect_code": "ENGINE",
            "description": "bad enum",
            "odometer_at_report": 100,
        },
        fx.OP,
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION)
    defects = get_success_data(api.list_bus_defect_reports(bus["id"], fx.FM))
    assert defects == [], "no defect may be persisted for a malformed enum"


def test_defect_deferral_epoch_reopen_cycle(api):
    """PRD §3.8: "The epoch sweep reopens a `DEFERRED` defect back to `OPEN`
    once its `defer_until_date` has passed, clearing `disposition`."
    PRD §3.8: "For a `MAJOR` defect, `defer_until_date` must be no more than 7
    days after the clock date."
    PRD §3.8: "A deferral requires a `defer_justification`, increments
    `defer_count`, and — for a `SAFETY_CRITICAL` defect — keeps the `SAFETY`
    hold in place even while deferred."

    Design: Corner/state_machines/defect_deferral_epoch_reopen_cycle
    """
    bus = new_bus(fleet_number="T6", vin="VINT6", initial_odometer_miles=100)
    defect = file_defect(bus["id"], severity="MAJOR", defect_code="ENGINE",
                         description="oil leak", odometer_at_report=100)

    deferred = validate_success(
        defect_event(defect["id"], "TRIAGE", disposition="DEFER",
                     defer_until_date="2026-08-05",
                     defer_justification="parts on order")
    )
    assert deferred["status"] == "DEFERRED"
    assert deferred["defer_count"] == 1

    set_clock("2026-08-06T00:00:00Z")
    summary = run_epoch()
    assert summary["defects_reopened"] == 1, (
        f"the lapsed deferral must reopen exactly one defect; summary: {summary}"
    )
    after = get_success_data(api.get_defect_report(defect["id"], fx.SUP))
    assert after["status"] == "OPEN", "deferral-lapse cycle returns to OPEN"
    assert after["disposition"] is None, "reopen clears disposition"


def test_major_defer_beyond_seven_days_rejected(api):
    """PRD §3.8: "For a `MAJOR` defect, `defer_until_date` must be no more than
    7 days after the clock date. For a `MINOR` defect, it must be no more than
    90 days after. In all cases `defer_until_date` must not be before the clock
    date; violations are rejected with `ERR_DEFER_DATE_INVALID`."

    Design: Corner/validations/major_defer_beyond_seven_days_rejected
    """
    bus = new_bus(fleet_number="Y22", vin="VINY22", model_year=2021)
    defect = file_defect(bus["id"], severity="MAJOR", defect_code="HVAC",
                         description="ac weak")

    res = defect_event(defect["id"], "TRIAGE", disposition="DEFER",
                       defer_until_date="2026-08-20",
                       defer_justification="too far out")
    validate_error(res, ApiErrorId.ERR_DEFER_DATE_INVALID)
    after = get_success_data(api.get_defect_report(defect["id"], fx.SUP))
    assert after["status"] == "OPEN"


def test_safety_deferral_rule_beats_temporal_window(api):
    """PRD §3.8: "For a `SAFETY_CRITICAL` defect, `defer_until_date` must equal
    the clock date — deferring past today is rejected with
    `ERR_DEFECT_NOT_DEFERRABLE`."

    A SAFETY_CRITICAL deferral to clock+1 day fails the safety-specific rule;
    the generic MAJOR/MINOR windows do not cover SAFETY_CRITICAL.

    Design: Corner/validations/safety_deferral_rule_beats_temporal_window
    """
    bus = new_bus(fleet_number="Y8", vin="VINY8", model_year=2021)
    defect = file_safety_defect(bus["id"], description="fade")

    res = defect_event(defect["id"], "TRIAGE", disposition="DEFER",
                       defer_until_date="2026-08-02",
                       defer_justification="overnight only")
    validate_error(res, ApiErrorId.ERR_DEFECT_NOT_DEFERRABLE)
    after = get_success_data(api.get_defect_report(defect["id"], fx.SUP))
    assert after["status"] == "OPEN"
    bus_after = get_success_data(api.get_bus(bus["id"], fx.FM))
    assert "SAFETY" in bus_after["hold_reasons"], "the SAFETY hold persists"


def test_safety_defect_manual_resolve_rejected(api):
    """PRD §3.8: "A supervisor may also manually resolve a defect from `OPEN`,
    `TRIAGED`, `SHOP_QUEUED`, or `DEFERRED`, but only when `severity` is not
    `SAFETY_CRITICAL` (otherwise `ERR_SAFETY_DEFECT_NEEDS_WORK_ORDER` — safety
    defects must be resolved via a closed work order)"

    Design: Corner/validations/safety_defect_manual_resolve_rejected
    """
    bus = new_bus(fleet_number="Y23", vin="VINY23", model_year=2021)
    defect = file_safety_defect(bus["id"], description="fade")

    res = defect_event(defect["id"], "RESOLVE", resolution="MANUAL")
    validate_error(res, ApiErrorId.ERR_SAFETY_DEFECT_NEEDS_WORK_ORDER)
    after = get_success_data(api.get_defect_report(defect["id"], fx.SUP))
    assert after["status"] == "OPEN"
    bus_after = get_success_data(api.get_bus(bus["id"], fx.FM))
    assert "SAFETY" in bus_after["hold_reasons"]


def test_mechanic_not_on_shift_blocks_road_call_dispatch(api):
    """PRD §3.8: "The mechanic must also have a `CONFIRMED` shift assignment on
    a `PUBLISHED` shift covering the clock date (otherwise
    `ERR_MECHANIC_NOT_ON_SHIFT`)."
    PRD §3.8: "On dispatch, `road_call_mechanic_id` is set and the bus is
    placed in `HELD` with `ROAD_CALL` added to `hold_reasons`; the fleet
    posture is recomputed."
    PRD §3.12: "Confirmation moves it to `CONFIRMED` and is permitted either by
    a supervisor or by the mechanic themselves (with `X-User-ID` equal to the
    assignment's `mechanic_id`)"

    Design: Corner/validations/mechanic_not_on_shift_blocks_road_call_dispatch
    """
    bus = new_bus(fleet_number="Y21", vin="VINY21", model_year=2021)
    mech = new_mechanic(name="Road Tech", employee_ref="Y21A")
    grant_cert(mech["id"], "ENGINE")
    defect = file_defect(bus["id"], severity="MAJOR", defect_code="ENGINE",
                         description="stalled at 5th & Main")
    validate_success(defect_event(defect["id"], "TRIAGE", disposition="ROAD_CALL"))

    res = defect_event(defect["id"], "DISPATCH_ROAD_CALL", mechanic_id=mech["id"])
    validate_error(res, ApiErrorId.ERR_MECHANIC_NOT_ON_SHIFT)

    shift = new_published_shift(shift_date="2026-08-01", shift_type="AM")
    assignment = assign_mechanic(shift["id"], mech["id"])
    confirm_assignment(assignment["id"], mech["id"])

    dispatched = validate_success(
        defect_event(defect["id"], "DISPATCH_ROAD_CALL", mechanic_id=mech["id"])
    )
    assert_defect_report(dispatched)
    assert dispatched["status"] == "ROAD_CALL_DISPATCHED"
    assert dispatched["road_call_mechanic_id"] == mech["id"]
    bus_after = get_success_data(api.get_bus(bus["id"], fx.FM))
    assert bus_after["availability_status"] == "HELD"
    assert "ROAD_CALL" in bus_after["hold_reasons"]


def test_defect_double_link_rejected(api):
    """PRD §3.3: "If `defect_report_id` is supplied, that defect must not
    already be linked to another non-terminal work order
    (`ERR_DEFECT_ALREADY_LINKED`)."

    Design: Corner/validations/defect_double_link_rejected
    """
    bus = new_bus(fleet_number="Y33", vin="VINY33", model_year=2021)
    defect = file_defect(bus["id"], severity="MINOR", defect_code="HVAC",
                         description="rattle")
    validate_success(defect_event(defect["id"], "TRIAGE", disposition="SHOP"))
    wo1 = new_work_order(bus["id"], defect_report_id=defect["id"],
                         planned_start_date="2026-08-10",
                         planned_end_date="2026-08-11")
    schedule_wo(wo1["id"])
    linked = get_success_data(api.get_defect_report(defect["id"], fx.SUP))
    assert linked["status"] == "WO_LINKED"
    assert linked["linked_work_order_id"] == wo1["id"]

    res = api.create_work_order(
        create_work_order_payload(
            bus["id"], bus_version(bus["id"]), wo_type="PM_A",
            defect_report_id=defect["id"], planned_start_date="2026-08-13",
            planned_end_date="2026-08-14", estimated_labor_hours=2,
            estimated_cost_cents=13_000,
        ),
        fx.SUP,
    )
    validate_error(res, ApiErrorId.ERR_DEFECT_ALREADY_LINKED)

    after = get_success_data(api.get_defect_report(defect["id"], fx.SUP))
    assert after["status"] == "WO_LINKED"
    assert after["linked_work_order_id"] == wo1["id"], (
        "the defect must stay linked to the first work order"
    )
