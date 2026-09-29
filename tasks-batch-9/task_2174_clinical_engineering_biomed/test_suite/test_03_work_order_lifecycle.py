"""Work-order intake, assignment, the two repair cycles and cancellation."""

from test_helpers import (
    ApiErrorId,
    assert_timestamp_equals,
    assert_work_order,
    bootstrap_monitor_campus,
    bootstrap_pump_campus,
    cancel_work_order,
    complete_repair,
    create_device,
    create_scale_model,
    create_vendor,
    department_version,
    intake_work_order,
    read_department,
    read_device,
    read_loaner_assignment,
    read_work_order,
    set_clock,
    set_posture,
    setup_locked_down_campus_with_intake,
    setup_pump_repair_complete_day_shift,
    setup_work_order_with_deployed_pool_loaner,
    validate_error,
    validate_paginated,
    validate_success,
    verify_work_order,
    assign_work_order,
)
from test_helpers.factories import SCALE_UNIT


def test_intake_creates_the_order_in_intake_with_zeroed_counters(api, biomed_tech_headers):
    """PRD §3.4: "The order is created with `status` at `INTAKE`, `reported_at` read from the
    logical clock, `loaner_status` at `NONE`, and every cost, timing and counter field at its
    zero value: `active_repair_seconds` at 0, `active_repair_hours` at 0.00,
    `turnaround_hours` at 0.00, `labor_minutes` at 0, `parts_cost_cents` at 0,
    `estimated_cost_cents` at 0, `final_cost_cents` at 0, `department_charge_cents` at 0,
    `verify_fail_count` at 0, `sla_met` at `false`, `shift_multiplier_applied` at 1.0, and
    `vendor_id`, `service_contract_id`, `service_mode`, `assigned_user_id`,
    `repaired_by_user_id`, `verified_by_user_id`, `repair_started_at`, `repair_completed_at`
    and `closed_at` all null."
    PRD §3.4: "Intake takes the unit `DOWN`."

    Design: Corner/state_machines/work_order_initial_state_is_intake
    """
    scene = bootstrap_pump_campus()

    response = api.create_work_order(
        {"device_id": scene["device"]["id"], "reported_severity": "ROUTINE",
         "problem_summary": "Occlusion alarm"},
        biomed_tech_headers,
    )
    data = validate_success(response, 201)
    assert_work_order(data)

    assert data["status"] == "INTAKE"
    assert data["service_mode"] is None
    assert data["repair_started_at"] is None
    assert data["loaner_status"] == "NONE"
    assert_timestamp_equals(data["reported_at"], "2026-08-01T00:00:00Z", "reported_at")
    assert read_device(scene["device"]["id"])["operational_state"] == "DOWN"


def test_intake_on_a_critical_unit_derives_p1_and_a_four_hour_sla(api, biomed_tech_headers):
    """PRD §3.4: "An order becomes `P1` when its `reported_severity` is `PATIENT_HARM` or the
    device's frozen `risk_class` is `CRITICAL`; failing that, it becomes `P2` when its
    `reported_severity` is `CLINICAL_IMPACT` or the device's `risk_class` is `HIGH`; otherwise
    it is `P3`."
    PRD §3.4: "The `sla_hours` allowance follows directly from the band: 4 hours for `P1`,
    24 hours for `P2`, 72 hours for `P3` — a `P3` order is given three full days of active
    repair time, a `P1` order barely half a shift."

    Design: Corner/state_machines/work_order_initial_state_is_intake
    """
    scene = bootstrap_pump_campus()
    assert scene["device"]["risk_class"] == "CRITICAL"

    data = validate_success(
        api.create_work_order({"device_id": scene["device"]["id"],
                               "reported_severity": "ROUTINE",
                               "problem_summary": "Occlusion alarm"},
                              biomed_tech_headers),
        201,
    )
    assert data["priority"] == "P1", "A CRITICAL device forces P1 even on a ROUTINE report"
    assert data["sla_hours"] == 4


def test_priority_takes_the_higher_of_severity_and_risk_band(api, biomed_tech_headers):
    """PRD §3.4: "An order becomes `P1` when its `reported_severity` is `PATIENT_HARM` or the
    device's frozen `risk_class` is `CRITICAL`; failing that, it becomes `P2` when its
    `reported_severity` is `CLINICAL_IMPACT` or the device's `risk_class` is `HIGH`; otherwise
    it is `P3`."
    PRD §3.4: "The `sla_hours` allowance follows directly from the band: 4 hours for `P1`,
    24 hours for `P2`, 72 hours for `P3` — a `P3` order is given three full days of active
    repair time, a `P1` order barely half a shift."

    Design: Corner/calculations/work_order_priority_from_severity_overrides_low_risk_class
    """
    scene = bootstrap_monitor_campus()
    model = create_scale_model()
    device = create_device(scene["facility"]["id"], scene["department"]["id"], model["id"],
                           SCALE_UNIT)
    assert device["risk_class"] == "LOW"

    routine = validate_success(
        api.create_work_order({"device_id": device["id"], "reported_severity": "ROUTINE",
                               "problem_summary": "Reads 0.2 kg high"}, biomed_tech_headers),
        201,
    )
    harm = validate_success(
        api.create_work_order({"device_id": device["id"],
                               "reported_severity": "PATIENT_HARM",
                               "problem_summary": "Dosing error traced to scale"},
                              biomed_tech_headers),
        201,
    )

    assert routine["priority"] == "P3" and routine["sla_hours"] == 72
    assert harm["priority"] == "P1" and harm["sla_hours"] == 4


def test_close_from_intake_is_rejected_and_posts_nothing(api, ce_manager_headers):
    """PRD §3.5: "Only a `CEManager` closes a work order, and only from `VERIFIED`."
    PRD §2.11: "State legality — whether the target resource is in a state from which the
    requested transition is declared: `ERR_INVALID_WORK_ORDER_STATE`,
    `ERR_INVALID_PM_TASK_STATE`, `ERR_INVALID_RECALL_STATE`, `ERR_INVALID_LOANER_STATE`,
    `ERR_INVALID_SECURITY_STATE` or `ERR_INVALID_RECALL_MATCH_STATE`, each HTTP 409."

    Design: Corner/state_machines/work_order_close_from_intake_returns_invalid_work_order_state
    """
    scene = bootstrap_pump_campus()
    order = intake_work_order(scene["device"]["id"], problem_summary="Alarm volume low")
    version = department_version(scene["department"]["id"])

    response = api.close_work_order(order["id"],
                                    {"expected_department_version": version},
                                    ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_WORK_ORDER_STATE.value, 409)

    assert read_work_order(order["id"])["status"] == "INTAKE"
    assert read_department(scene["department"]["id"])["downtime_spend_cents"] == 0


def test_second_cancel_on_a_cancelled_order_is_rejected(api, ce_manager_headers):
    """PRD §3.4: "An order already `CLOSED` or `CANCELLED`, or one in `REPAIR_COMPLETE` or
    `VERIFIED`, cannot be cancelled and reports `ERR_INVALID_WORK_ORDER_STATE`."

    Design: Corner/state_machines/work_order_cancel_from_cancelled_returns_invalid_work_order_state
    """
    scene = bootstrap_pump_campus()
    order = intake_work_order(scene["device"]["id"], problem_summary="Reported in error")
    cancel_work_order(order["id"], reason="Reported in error")

    response = api.cancel_work_order(order["id"], {"reason": "Cancelling again"},
                                     ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_WORK_ORDER_STATE.value, 409)

    assert read_work_order(order["id"])["status"] == "CANCELLED"
    assert read_device(scene["device"]["id"])["operational_state"] == "IN_SERVICE"


def test_device_stays_down_until_the_last_open_order_is_gone(api, ce_manager_headers):
    """PRD §2.10: "Whenever a work-order close, a work-order cancellation, a recall
    disposition or a security resolution would return a unit from `DOWN` to `IN_SERVICE`, the
    restoration happens only when all three of the following hold: no other work order on that
    device is in `INTAKE`, `IN_REPAIR`, `AWAITING_PARTS`, `REPAIR_COMPLETE` or `VERIFIED`; the
    device's `recall_hold` is `false`; and the device's `security_state` is not `QUARANTINED`."

    Design: Corner/state_machines/device_stays_down_when_a_second_work_order_is_still_open
    """
    scene = bootstrap_monitor_campus()
    device_id = scene["device"]["id"]
    order_one = intake_work_order(device_id, problem_summary="Fault A")
    order_two = intake_work_order(device_id, problem_summary="Fault B")

    first = validate_success(
        api.cancel_work_order(order_one["id"],
                              {"reason": "Fault A is a duplicate of Fault B"},
                              ce_manager_headers),
        200,
    )
    assert first["status"] == "CANCELLED"
    assert read_device(device_id)["operational_state"] == "DOWN", (
        "The second open order must keep the unit DOWN"
    )

    second = validate_success(
        api.cancel_work_order(order_two["id"],
                              {"reason": "Both faults resolved by firmware reset"},
                              ce_manager_headers),
        200,
    )
    assert second["status"] == "CANCELLED"
    assert read_device(device_id)["operational_state"] == "IN_SERVICE"
    assert read_department(scene["department"]["id"])["downtime_spend_cents"] == 0


def test_a_technician_may_not_verify_their_own_repair(api, biomed_tech_headers,
                                                      biomed_tech_peer_headers):
    """PRD §3.4: "The verifier's `X-User-ID` must differ from the order's
    `repaired_by_user_id`; if they match, the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`, because the technician who performed a repair may not sign
    it off."
    PRD §3.4: "A `PASS` moves the order `REPAIR_COMPLETE` → `VERIFIED` and records
    `verified_by_user_id` from `X-User-ID`."

    Design: Corner/validations/verifier_cannot_be_the_technician_who_repaired
    """
    scene = bootstrap_pump_campus()
    order = intake_work_order(scene["device"]["id"], problem_summary="Keypad replacement")
    assign_work_order(order["id"])
    complete_repair(order["id"], 60, 0)

    response = api.verify_work_order(order["id"], {"result": "PASS"}, biomed_tech_headers)
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    held = read_work_order(order["id"])
    assert held["status"] == "REPAIR_COMPLETE"
    assert held["verified_by_user_id"] is None

    passed = validate_success(
        api.verify_work_order(order["id"], {"result": "PASS"}, biomed_tech_peer_headers), 200
    )
    assert passed["status"] == "VERIFIED"
    assert passed["verified_by_user_id"] == biomed_tech_peer_headers["X-User-ID"]


def test_assignment_to_an_unapproved_vendor_is_rejected(api, ce_manager_headers):
    """PRD §3.4: "Three preconditions guard the move `INTAKE` → `IN_REPAIR`: the device's
    campus must not be in `LOCKDOWN` posture (`ERR_FACILITY_LOCKDOWN`), the device must not be
    `RETIRED`, and vendor-mode assignment must name an existing vendor whose `is_approved` is
    `true` (`ERR_VENDOR_NOT_APPROVED`)."

    Design: Corner/validations/unapproved_vendor_cannot_be_assigned
    """
    scene = bootstrap_pump_campus()
    vendor = create_vendor(name="Unvetted Repairs LLC", vendor_code="UNV",
                           hourly_rate_cents=12000, travel_flat_cents=9000,
                           is_approved=False)
    order = intake_work_order(scene["device"]["id"],
                              problem_summary="Needs vendor service")

    response = api.assign_work_order(order["id"],
                                     {"service_mode": "VENDOR", "vendor_id": vendor["id"]},
                                     ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_VENDOR_NOT_APPROVED.value, 422)

    after = read_work_order(order["id"])
    assert after["status"] == "INTAKE"
    assert after["service_mode"] is None
    assert after["vendor_id"] is None
    assert after["repair_started_at"] is None


def test_work_order_listing_filters_by_status(api, ce_manager_headers):
    """PRD §3.4: "Work orders can be read individually and listed with filters on `device_id`,
    `vendor_id`, `service_contract_id`, `origin_security_finding_id`, `status` and `priority`."

    Design: Corner/endpoints/work_orders_list_filters_by_status
    """
    scene = bootstrap_monitor_campus()
    device_id = scene["device"]["id"]
    intake_work_order(device_id, problem_summary="Order one")
    second = intake_work_order(device_id, problem_summary="Order two")
    assign_work_order(second["id"])

    data, meta = validate_paginated(
        api.list_work_orders(ce_manager_headers,
                             params={"device_id": device_id, "status": "IN_REPAIR"})
    )
    assert len(data) == 1, f"Expected exactly 1 IN_REPAIR order, got {len(data)}"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert data[0]["id"] == second["id"]


def test_logical_clock_starts_at_the_declared_instant_and_moves_on_demand(api, ce_manager_headers):
    """PRD §2.5: "At server start the clock reads `2026-08-01T00:00:00Z`, and it must not fall
    back to real wall-clock time before it has been explicitly set."
    PRD §2.5: "A `CEManager` may advance or rewind it by supplying a `to_iso8601` instant; the
    endpoint answers with the resulting `current_utc`."

    Design: Corner/endpoints/logical_clock_defaults_to_fixed_instant_before_any_set
    """
    scene = bootstrap_monitor_campus()
    order = intake_work_order(scene["device"]["id"],
                              problem_summary="Default clock probe")
    assert_timestamp_equals(order["reported_at"], "2026-08-01T00:00:00Z", "reported_at")

    data = validate_success(
        api.set_clock({"to_iso8601": "2026-09-15T06:30:00Z"}, ce_manager_headers), 200
    )
    assert_timestamp_equals(data["current_utc"], "2026-09-15T06:30:00Z", "current_utc")

    cancelled = validate_success(
        api.cancel_work_order(order["id"], {"reason": "Probe complete"}, ce_manager_headers),
        200,
    )
    assert_timestamp_equals(cancelled["closed_at"], "2026-09-15T06:30:00Z", "closed_at")


def test_failed_verification_returns_the_order_to_in_repair(api, biomed_tech_peer_headers):
    """PRD §3.4: "A `FAIL` sends the order back: `REPAIR_COMPLETE` → `IN_REPAIR`,
    `verify_fail_count` increases by 1, a new active-repair segment opens at the logical
    clock, and — as stated above — `shift_multiplier_applied` is *not* recomputed even though
    repair is resuming at a new hour of day."

    Design: Difficulty/non_linear_state_machine/work_order_verify_fail_returns_order_to_in_repair_cycle
    """
    scene = setup_pump_repair_complete_day_shift(labor_minutes=60)
    order_id = scene["work_order"]["id"]

    data = validate_success(
        api.verify_work_order(order_id,
                              {"result": "FAIL", "note": "Fault reproduces on soak test"},
                              biomed_tech_peer_headers),
        200,
    )
    assert data["status"] == "IN_REPAIR"
    assert data["verify_fail_count"] == 1
    assert float(data["shift_multiplier_applied"]) == 1.0


def test_second_repair_pass_accumulates_labour_and_recosts_the_order(api, biomed_tech_headers,
                                                                     biomed_tech_peer_headers):
    """PRD §3.4: "These figures **accumulate**: each call adds its `labor_minutes` to the
    order's running total and its `parts_cost_cents` to the running parts spend, rather than
    replacing them."
    PRD §3.4: "The labour term is computed in a pinned order: multiply the cumulative
    `labor_minutes` by that rate, multiply the product by `shift_multiplier_applied`, **then**
    divide by 60, **then** round half up to whole cents — exactly one rounding, applied at the
    end."

    Design: Difficulty/non_linear_state_machine/work_order_verify_fail_returns_order_to_in_repair_cycle
    """
    scene = setup_pump_repair_complete_day_shift(labor_minutes=60)
    order_id = scene["work_order"]["id"]
    verify_work_order(order_id, "FAIL", note="Fault reproduces on soak test")
    set_clock("2026-08-02T13:00:00Z")

    data = validate_success(
        api.complete_repair(order_id, {"labor_minutes": 40, "parts_cost_cents": 0},
                            biomed_tech_headers),
        200,
    )
    assert data["labor_minutes"] == 100, "60 + 40 minutes must accumulate on the order"
    assert data["estimated_cost_cents"] == 15000, (
        f"100 minutes at 9000 cents/hour with multiplier 1.0 is 15000, "
        f"got {data['estimated_cost_cents']}"
    )
    assert float(data["shift_multiplier_applied"]) == 1.0


def test_the_repair_cycle_closes_on_a_passing_second_verification(api, biomed_tech_peer_headers):
    """PRD §3.4: "A `PASS` moves the order `REPAIR_COMPLETE` → `VERIFIED` and records
    `verified_by_user_id` from `X-User-ID`."
    PRD §3.4: "The multiplier is pinned once, at the first assignment, and is never recomputed
    afterwards, no matter how many parts holds, resumptions or failed verifications the order
    goes through."

    Design: Difficulty/non_linear_state_machine/work_order_verify_fail_returns_order_to_in_repair_cycle
    """
    scene = setup_pump_repair_complete_day_shift(labor_minutes=60)
    order_id = scene["work_order"]["id"]
    verify_work_order(order_id, "FAIL", note="Fault reproduces on soak test")
    set_clock("2026-08-02T13:00:00Z")
    complete_repair(order_id, 40, 0)

    data = validate_success(
        api.verify_work_order(order_id, {"result": "PASS"}, biomed_tech_peer_headers), 200
    )
    assert data["status"] == "VERIFIED"
    assert data["verify_fail_count"] == 1, "The earlier failure stays on the record"
    assert float(data["shift_multiplier_applied"]) == 1.0


def test_assignment_is_blocked_while_the_campus_is_locked_down(api, biomed_tech_headers):
    """PRD §2.9: "While a facility is in `LOCKDOWN`, no work order on any of its devices may
    be assigned for repair; the attempt is rejected with `ERR_FACILITY_LOCKDOWN` (HTTP 409)."
    PRD §3.4: "Intake takes the unit `DOWN`."

    Design: Difficulty/cross_entity_state_dependency/work_order_assign_gated_by_facility_posture
    """
    scene = setup_locked_down_campus_with_intake()
    order_id = scene["work_order"]["id"]

    # Intake itself is unaffected by posture, so the unit is already DOWN.
    assert read_device(scene["device"]["id"])["operational_state"] == "DOWN"

    response = api.assign_work_order(order_id, {"service_mode": "IN_HOUSE"},
                                     biomed_tech_headers)
    validate_error(response, ApiErrorId.ERR_FACILITY_LOCKDOWN.value, 409)

    after = read_work_order(order_id)
    assert after["status"] == "INTAKE"
    assert after["repair_started_at"] is None


def test_restoring_normal_posture_lets_the_same_assignment_succeed(api, biomed_tech_headers):
    """PRD §2.9: "The system escalates a `NORMAL` posture to `HEIGHTENED` automatically in
    three circumstances described in §3, but it never sets `LOCKDOWN` on its own — `LOCKDOWN`
    is reachable only through the explicit posture-setting capability, where a `CEManager`
    supplies `to_posture` and an optional `note`."
    PRD §3.4: "On success the system sets `repair_started_at` from the logical clock, records
    `assigned_user_id` from `X-User-ID` as an opaque identifier, stores the `service_mode` and
    `vendor_id`, opens the first active-repair segment at that instant, and increments the
    order's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/work_order_assign_gated_by_facility_posture
    """
    scene = setup_locked_down_campus_with_intake()
    order_id = scene["work_order"]["id"]
    api.assign_work_order(order_id, {"service_mode": "IN_HOUSE"}, biomed_tech_headers)

    set_posture(scene["facility"]["id"], "NORMAL")

    data = validate_success(
        api.assign_work_order(order_id, {"service_mode": "IN_HOUSE"}, biomed_tech_headers),
        200,
    )
    assert data["status"] == "IN_REPAIR"
    assert data["service_mode"] == "IN_HOUSE"
    assert data["repair_started_at"] is not None


def test_cancelling_a_covered_order_moves_no_money(api, ce_manager_headers):
    """PRD §3.4: "No money moves: `final_cost_cents` and `department_charge_cents` stay 0, and
    the department's `downtime_spend_cents` is not touched at all — a compensating invariant
    that keeps the fiscal ledger consistent with the work actually performed."
    PRD §3.5: "The device's `lifetime_maintenance_cost_cents` grows by this order's
    `final_cost_cents`, and its `replacement_priority_score` is recomputed on the new burden."

    Design: Difficulty/compensating_invariant/work_order_cancel_conserves_department_downtime_spend
    """
    scene = setup_work_order_with_deployed_pool_loaner()
    set_clock("2026-08-04T00:00:00Z")

    data = validate_success(
        api.cancel_work_order(scene["work_order"]["id"],
                              {"reason": "Duplicate of an already-resolved report"},
                              ce_manager_headers),
        200,
    )
    assert data["status"] == "CANCELLED"
    assert data["final_cost_cents"] == 0
    assert data["department_charge_cents"] == 0

    department = read_department(scene["department"]["id"])
    assert department["downtime_spend_cents"] == 0
    assert department["budget_state"] == "OPEN"
    assert read_device(scene["device"]["id"])["lifetime_maintenance_cost_cents"] == 0


def test_cancelling_releases_the_deployed_pool_loaner_without_billing_it(api, ce_manager_headers):
    """PRD §3.4: "Every loaner assignment on the cancelled order that is still `DEPLOYED`
    moves to `CANCELLED` with `billable_days` 0 and `rental_cost_cents` 0, releasing any pool
    unit from `ON_LOAN` back to `IN_SERVICE`."

    Design: Difficulty/compensating_invariant/work_order_cancel_conserves_department_downtime_spend
    """
    scene = setup_work_order_with_deployed_pool_loaner()
    assert read_device(scene["pool_device"]["id"])["operational_state"] == "ON_LOAN"
    set_clock("2026-08-04T00:00:00Z")

    cancel_work_order(scene["work_order"]["id"],
                      reason="Duplicate of an already-resolved report")

    loaner = read_loaner_assignment(scene["loaner"]["id"])
    assert loaner["status"] == "CANCELLED"
    assert loaner["billable_days"] == 0
    assert loaner["rental_cost_cents"] == 0
    assert read_device(scene["pool_device"]["id"])["operational_state"] == "IN_SERVICE"


def test_cancelling_restores_the_downed_unit_to_service(api, ce_manager_headers):
    """PRD §3.4: "`closed_at` is set from the logical clock, and the downed unit returns from
    `DOWN` to `IN_SERVICE` subject to the three conditional-restoration preconditions of §2.10."

    Design: Difficulty/compensating_invariant/work_order_cancel_conserves_department_downtime_spend
    """
    scene = setup_work_order_with_deployed_pool_loaner()
    assert read_device(scene["device"]["id"])["operational_state"] == "DOWN"
    set_clock("2026-08-04T00:00:00Z")

    cancel_work_order(scene["work_order"]["id"],
                      reason="Duplicate of an already-resolved report")

    assert read_device(scene["device"]["id"])["operational_state"] == "IN_SERVICE"
