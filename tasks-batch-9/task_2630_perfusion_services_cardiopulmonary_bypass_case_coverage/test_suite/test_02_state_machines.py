"""Lifecycle machines: initial states, declared edges, one-shot edges and terminal lockdown."""
from test_helpers import (
    add_case,
    add_device,
    adjudicate_ce_activity,
    ADMIN_HEADERS,
    api_client,
    approve_pack,
    assert_case_dimensions,
    assert_ce_hours,
    assert_cents,
    assert_contract_ledger,
    assert_device_state,
    assert_fields_null,
    assert_pack_line,
    assert_version_unchanged,
    assign_perfusionist,
    base_setup,
    build_assignment,
    build_ce_decision,
    build_check_result,
    build_ecmo_handoff,
    build_end_bypass,
    build_incident_close,
    build_pack_configuration,
    build_pack_decision,
    build_pump_checklist,
    build_substitution,
    cancel_case,
    capture_device_event,
    close_case,
    closed_case_setup,
    complete_device_service,
    configure_pack,
    create_device,
    create_ecmo_run,
    create_incident_report,
    decannulate_ecmo_run,
    end_bypass,
    ERR_CASE_NOT_ASSIGNABLE,
    ERR_CASE_NOT_CANCELLABLE,
    ERR_CASE_NOT_OFF_BYPASS,
    ERR_CASE_NOT_ON_BYPASS,
    ERR_CASE_NOT_PACK_CONFIGURED,
    ERR_CASE_NOT_SETUP_VERIFIED,
    ERR_CASE_NOT_STAFFED,
    ERR_CE_ACTIVITY_STATE_INVALID,
    ERR_CHECKLIST_NOT_DRAFT,
    ERR_DEVICE_SERVICE_NOT_PERMITTED,
    ERR_ECMO_RUN_STATE_INVALID,
    ERR_INCIDENT_STATE_INVALID,
    ERR_PACK_APPROVAL_STATE_INVALID,
    INITIAL_CLOCK,
    off_bypass_setup,
    on_bypass_setup,
    open_checklist,
    read_case,
    read_checklist,
    read_contract,
    read_device,
    read_ecmo_run,
    read_incident_report,
    read_pack,
    read_perfusionist,
    read_slot,
    set_clock,
    setup_verified_setup,
    staffed_setup,
    start_bypass,
    submit_incident_report,
    TECH_HEADERS,
    validate_error,
    validate_paginated,
    verify_checklist,
)


def test_start_bypass_moves_case_device_and_slot_in_one_transition():
    """Going on pump advances the case, the primary machine and the covering call slot together.

    PRD 3.6: The case then moves `SETUP_VERIFIED → ON_BYPASS` with `bypass_started_at` set to the logical clock, the primary machine moves `RESERVED → IN_USE`, and the call rotation slot that satisfied the assignment's coverage requirement moves `SCHEDULED → ACTIVE` if it is still `SCHEDULED` — a slot already `ACTIVE` from an earlier case in the same window simply stays as it is.
    PRD 3.3: Primary and backup call slots never set `consumed`; it stays false for their whole life, because one primary call window is expected to cover any number of cases inside it.
    PRD 3.5: That count, `open_reservation_count`, is recomputed from scratch for each touched machine as the number of bypass cases naming that machine as either their primary or their standby whose `bypass_status` is `PACK_CONFIGURED`, `SETUP_VERIFIED` or `ON_BYPASS` — which is why it is a count rather than a flag, and why cases in `SCHEDULED`, `STAFFED`, `OFF_BYPASS`, `CLOSED` or `CANCELLED` never contribute to it.
    PRD 3.6: On success the checklist moves `DRAFT → VERIFIED` with `blood_mgmt_signoff` set true, `verified_by_perfusionist_id` set to the acting perfusionist and `verified_at` set to the logical clock, while the case moves `PACK_CONFIGURED → SETUP_VERIFIED` with `setup_verified_at` set to the same instant.

    Design: Corner/state_machines/start_bypass_moves_case_device_and_slot_in_one_transition
    """
    env = setup_verified_setup()

    case = start_bypass(env["case"]["id"], env["p1"]["id"])

    assert case["bypass_status"] == "ON_BYPASS"
    assert case["bypass_started_at"] == INITIAL_CLOCK
    assert_case_dimensions(case, "ON_BYPASS", "PROVISIONAL_ACCRUED")
    assert_cents(case["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert case["final_fee_cents"] is None

    assert_device_state(read_device(env["d1"]["id"]), status="IN_USE", open_reservation_count=1)
    assert_device_state(read_device(env["d2"]["id"]), status="RESERVED", open_reservation_count=1)

    slot = read_slot(env["slot_p1"]["id"])
    assert slot["status"] == "ACTIVE"
    assert slot["consumed"] is False

    checklist = read_checklist(env["checklist"]["id"])
    assert checklist["status"] == "VERIFIED"
    assert checklist["blood_mgmt_signoff"] is True
    assert checklist["verified_by_perfusionist_id"] == env["p1"]["id"]
    assert checklist["verified_at"] == INITIAL_CLOCK


def test_newly_created_rows_start_in_their_declared_initial_state():
    """Every machine's entry state is what creation returns, independent of any parent's state.

    PRD 3.2: A new cycle begins `ACTIVE`, with `probation_count` at 0, `remediation_credits_required` at 0 and `probation_credits_banked` at 0, and recording it re-derives the holder's credit ledger against the new window.
    PRD 3.2: An accepted claim lands in `SUBMITTED` with `counted_toward_remediation` false, and it immediately raises the holder's pending credit total by its own hours.
    PRD 3.1: A commissioned device begins `AVAILABLE`, with `runtime_hours_since_service` and `alarm_count_since_service` at 0, `open_reservation_count` at 0, and `last_service_completed_at` null until its first service is recorded.
    PRD 3.3: A slot begins in `SCHEDULED` with `consumed` false and moves through a short lifecycle.
    PRD 3.4: Its clinical dimension `bypass_status` starts at `SCHEDULED` and its fiscal dimension `billing_status` starts at `UNBILLED`, independently, as §2.9 requires.
    PRD 3.6: A fresh checklist begins in `DRAFT` with `blood_mgmt_signoff` false, `verified_at` null and `verified_by_perfusionist_id` null.
    PRD 3.6: The server immediately derives `missing_check_codes` against the pinned preference card: it is the array of codes appearing in that card's `required_safety_check_codes` that are either absent from `check_results` altogether or present there with `passed` false, ordered ascending.

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    env = base_setup()

    assert env["cert"]["status"] == "ACTIVE"
    assert env["cert"]["probation_count"] == 0
    assert_ce_hours(env["cert"]["remediation_credits_required"], 0)
    assert_ce_hours(env["cert"]["probation_credits_banked"], 0)

    assert env["ce"]["status"] == "SUBMITTED"
    assert env["ce"]["counted_toward_remediation"] is False

    for key in ("d1", "d2"):
        assert_device_state(
            env[key],
            status="AVAILABLE",
            open_reservation_count=0,
            alarm_count_since_service=0,
            runtime_hours_since_service=0,
        )
        assert env[key]["last_service_completed_at"] is None

    assert env["slot_p1"]["status"] == "SCHEDULED"
    assert env["slot_p1"]["consumed"] is False

    assert_case_dimensions(env["case"], "SCHEDULED", "UNBILLED")

    case = assign_perfusionist(
        env["case"]["id"], env["p1"]["id"], env["case"]["version"], env["chief"]["id"]
    )
    configure_pack(case["id"], env["d1"]["id"], env["p1"]["id"])
    assert read_case(case["id"])["bypass_status"] == "PACK_CONFIGURED"

    checklist = open_checklist(case["id"], env["p1"]["id"])
    assert checklist["status"] == "DRAFT"
    assert checklist["blood_mgmt_signoff"] is False
    assert_fields_null(checklist, ["verified_at", "verified_by_perfusionist_id"])
    assert checklist["missing_check_codes"] == []


def test_end_bypass_applies_every_declared_side_effect_once():
    """Coming off pump writes the clinical record and fans out to both machines and the slot.

    PRD 3.6: The case moves `ON_BYPASS → OFF_BYPASS`, `bypass_ended_at` is set to the logical clock, and all four reported quality figures are stored.
    PRD 3.6: The primary machine's `runtime_hours_since_service` rises by the reported pump minutes divided by 60, kept exact and unrounded — a 95-minute case adds one and five-twelfths hours, not one or two.
    PRD 3.6: If the machine is clean — its `alarm_count_since_service` is 0 **and** its `runtime_hours_since_service`, after the addition just made, is strictly below its `service_interval_hours` — then it moves `IN_USE → AVAILABLE` when its recomputed `open_reservation_count` is 0, or `IN_USE → RESERVED` when that count is 1 or more, because a machine still committed to a future case should not advertise itself as free.
    PRD 3.6: Meanwhile the standby machine moves `RESERVED → AVAILABLE`, and both machines' `open_reservation_count` values are recomputed.
    PRD 3.6: The covering call slot moves `ACTIVE → COMPLETED` when the perfusionist has no other case still on pump.
    PRD 3.6: The fiscal dimension is deliberately untouched: a case that has come off pump still reads `PROVISIONAL_ACCRUED`, because coming off pump is a clinical event and settlement is a fiscal one.

    Design: Corner/state_machines/end_bypass_applies_every_declared_side_effect_once
    """
    env = off_bypass_setup(
        end_bypass_overrides={
            "pump_time_minutes": 120,
            "cross_clamp_minutes": 60,
            "lowest_hematocrit_pct": 24,
            "adverse_event_count": 0,
        }
    )
    case = env["case"]

    assert case["bypass_status"] == "OFF_BYPASS"
    assert case["bypass_ended_at"] == INITIAL_CLOCK
    assert case["pump_time_minutes"] == 120
    assert case["cross_clamp_minutes"] == 60
    assert float(case["lowest_hematocrit_pct"]) == 24
    assert case["adverse_event_count"] == 0

    assert_device_state(
        read_device(env["d1"]["id"]),
        status="AVAILABLE",
        open_reservation_count=0,
        runtime_hours_since_service=2.0,
    )
    assert_device_state(
        read_device(env["d2"]["id"]), status="AVAILABLE", open_reservation_count=0
    )

    assert read_slot(env["slot_p1"]["id"])["status"] == "COMPLETED"

    assert_case_dimensions(case, "OFF_BYPASS", "PROVISIONAL_ACCRUED")
    assert_cents(case["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert case["final_fee_cents"] is None
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)

    _, meta = validate_paginated(
        api_client.list_device_event_logs(
            env["d1"]["id"], TECH_HEADERS, {"event_code": "SELF_TEST_FAIL"}
        )
    )
    assert meta["total_count"] == 0


def test_service_completion_requires_needs_service_and_zero_reservations():
    """Preventive service is admitted only from NEEDS_SERVICE with no live reservation left.

    PRD 3.7: And an `ALARM_CRITICAL` or a `SELF_TEST_FAIL` drives the machine to `NEEDS_SERVICE` from whichever of `AVAILABLE`, `RESERVED` or `IN_USE` it was in — which in turn fires a four-link cascade across the cases that were counting on it.
    PRD 3.7: The second link reaches every bypass case naming that machine as its **primary** whose `bypass_status` is `PACK_CONFIGURED` or `SETUP_VERIFIED`: such a case falls back to `STAFFED`, its `setup_verified_at` is cleared to null, its `readiness_flag` is raised to `DEVICE_FALLBACK_REQUIRED`, both its `primary_device_id` and its `backup_device_id` are cleared to null, and the standby machine it was holding moves `RESERVED → AVAILABLE`.
    PRD 3.7: Cases already `ON_BYPASS` are deliberately **not** unwound: an alarm mid-run is a clinical event handled through the incident pathway of §3.9, not by rewinding a case with a patient on the circuit.
    PRD 3.7: A `BiomedTech` records a service completion, optionally with `detail`, against a machine that is in `NEEDS_SERVICE` and whose `open_reservation_count` is 0; a machine in any other state, or one still carrying a live reservation, is refused with `ERR_DEVICE_SERVICE_NOT_PERMITTED`.
    PRD 3.7: The completion moves the machine `NEEDS_SERVICE → AVAILABLE`, resets both `alarm_count_since_service` and `runtime_hours_since_service` to 0, stamps `last_service_completed_at` with the logical clock, appends an event log carrying `event_code` `SERVICE_COMPLETED`, and advances the machine's `version`.
    PRD 3.7: Recovery from `NEEDS_SERVICE` runs through biomedical engineering.

    Design: Corner/state_machines/service_completion_requires_needs_service_and_zero_reservations
    """
    env = on_bypass_setup()
    add_device(env, "d3", asset_tag="HLM-003")
    case_b = add_case(
        env,
        "case_b",
        scheduled_start="2026-08-02T13:31:00Z",
        scheduled_end="2026-08-02T19:31:00Z",
    )
    case_b = assign_perfusionist(
        case_b["id"], env["p1"]["id"], case_b["version"], env["chief"]["id"]
    )
    configure_pack(
        case_b["id"], env["d2"]["id"], env["p1"]["id"], backup_device_id=env["d3"]["id"]
    )

    assert_device_state(read_device(env["d2"]["id"]), status="RESERVED", open_reservation_count=2)

    reserved_probe = api_client.create_service_completion(env["d2"]["id"], {}, TECH_HEADERS)
    validate_error(reserved_probe, ERR_DEVICE_SERVICE_NOT_PERMITTED, 409)

    capture_device_event(env["d2"]["id"], "ALARM_CRITICAL", detail="inlet pressure alarm")

    assert_device_state(
        read_device(env["d2"]["id"]),
        status="NEEDS_SERVICE",
        open_reservation_count=1,
        alarm_count_since_service=1,
    )
    reverted = read_case(case_b["id"])
    assert_case_dimensions(reverted, "STAFFED", "UNBILLED")
    assert_fields_null(reverted, ["primary_device_id", "backup_device_id", "setup_verified_at"])
    assert reverted["readiness_flag"] == "DEVICE_FALLBACK_REQUIRED"
    assert_cents(reverted["accrued_fee_cents"], 0, "accrued_fee_cents")
    assert_device_state(read_device(env["d3"]["id"]), status="AVAILABLE", open_reservation_count=0)

    running = read_case(env["case"]["id"])
    assert running["bypass_status"] == "ON_BYPASS"
    assert running["backup_device_id"] == env["d2"]["id"]
    assert read_checklist(env["checklist"]["id"])["status"] == "VERIFIED"
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)

    still_reserved = api_client.create_service_completion(env["d2"]["id"], {}, TECH_HEADERS)
    validate_error(still_reserved, ERR_DEVICE_SERVICE_NOT_PERMITTED, 409)

    end_bypass(
        env["case"]["id"],
        env["p1"]["id"],
        pump_time_minutes=120,
        cross_clamp_minutes=60,
        lowest_hematocrit_pct=24,
    )
    assert_device_state(
        read_device(env["d2"]["id"]), status="NEEDS_SERVICE", open_reservation_count=0
    )

    serviced = complete_device_service(env["d2"]["id"], detail="oxygenator sensor replaced")
    assert_device_state(
        serviced,
        status="AVAILABLE",
        open_reservation_count=0,
        alarm_count_since_service=0,
        runtime_hours_since_service=0,
    )
    assert serviced["last_service_completed_at"] == INITIAL_CLOCK

    _, meta = validate_paginated(
        api_client.list_device_event_logs(
            env["d2"]["id"], TECH_HEADERS, {"event_code": "SERVICE_COMPLETED"}
        )
    )
    assert meta["total_count"] == 1


def test_staffed_case_rejects_every_out_of_order_lifecycle_trigger():
    """A STAFFED case admits only the pack and the cancel; the four later triggers all refuse.

    PRD 2.8: In order: (26) the case is `SCHEDULED` or `STAFFED` for an assignment, else `ERR_CASE_NOT_ASSIGNABLE` (409); (27) the case is `STAFFED` for pack configuration, else `ERR_CASE_NOT_STAFFED` (409); (28) the case is `PACK_CONFIGURED` both for opening a pump checklist and for verifying one, else `ERR_CASE_NOT_PACK_CONFIGURED` (409); (29) the checklist itself is `DRAFT` when verified, else `ERR_CHECKLIST_NOT_DRAFT` (409); (30) the case is `SETUP_VERIFIED` to go on pump, else `ERR_CASE_NOT_SETUP_VERIFIED` (409); (31) the case is `ON_BYPASS` both to come off pump and to open an ECMO run, else `ERR_CASE_NOT_ON_BYPASS` (409); (32) the case is `OFF_BYPASS` to be closed, else `ERR_CASE_NOT_OFF_BYPASS` (409); (33) the case is one of `SCHEDULED`, `STAFFED`, `PACK_CONFIGURED` or `SETUP_VERIFIED` to be cancelled, else `ERR_CASE_NOT_CANCELLABLE` (409); (34) at pack configuration both the primary and the resolved backup machine hold a status of `AVAILABLE` or `RESERVED`, else `ERR_DEVICE_NOT_AVAILABLE` (409); (35) a service completion targets a device that is `NEEDS_SERVICE` and whose `open_reservation_count` is 0, else `ERR_DEVICE_SERVICE_NOT_PERMITTED` (409); (36) an incident report is in the origin state of the requested move — `DRAFT` or `RETURNED_FOR_INFO` to submit, `SUBMITTED` to review, `UNDER_REVIEW` to close — else `ERR_INCIDENT_STATE_INVALID` (409); (37) a return-for-information decision is only admitted while the report's `return_count` is below the two-return ceiling, else `ERR_INCIDENT_RETURN_LIMIT` (409); (38) a handoff targets a run in `RELIEF_PENDING` and a decannulation targets a run in `RUNNING` or `RELIEF_PENDING`, else `ERR_ECMO_RUN_STATE_INVALID` (409); (39) a CE claim being verified or rejected is `SUBMITTED`, and one being revoked is `VERIFIED`, else `ERR_CE_ACTIVITY_STATE_INVALID` (409); (40) a pack being adjudicated has `approval_status` of `PENDING`, else `ERR_PACK_APPROVAL_STATE_INVALID` (409).
    PRD 3.6: It is permitted from `SCHEDULED`, `STAFFED`, `PACK_CONFIGURED` or `SETUP_VERIFIED` and refused with `ERR_CASE_NOT_CANCELLABLE` from anywhere else; a case with an extracorporeal run still open may not be cancelled, a combination the clinical pathway makes unreachable because a run can only be opened from a case on pump and a case on pump is no longer cancellable.
    PRD 3.6: If its `billing_status` reads `PROVISIONAL_ACCRUED`, the contract's `accrued_case_fee_cents` falls by the case's `accrued_fee_cents`, the contract's `accrued_case_count` falls by one, the fiscal dimension moves `PROVISIONAL_ACCRUED → UNBILLED` and the case's `accrued_fee_cents` becomes 0 — the cancellation performs this compensation inline and does not route through any other billing rule.

    Design: Corner/state_machines/staffed_case_rejects_every_out_of_order_lifecycle_trigger
    """
    env = staffed_setup()
    case_id = env["case"]["id"]
    staffed_version = env["case"]["version"]

    validate_error(
        api_client.create_pump_checklist(case_id, build_pump_checklist(), env["p1_headers"]),
        ERR_CASE_NOT_PACK_CONFIGURED,
        409,
    )
    validate_error(
        api_client.start_bypass(case_id, env["p1_headers"]),
        ERR_CASE_NOT_SETUP_VERIFIED,
        409,
    )
    validate_error(
        api_client.end_bypass(case_id, build_end_bypass(), env["p1_headers"]),
        ERR_CASE_NOT_ON_BYPASS,
        409,
    )
    validate_error(
        api_client.close_bypass_case(case_id, env["chief_headers"]),
        ERR_CASE_NOT_OFF_BYPASS,
        409,
    )
    assert_version_unchanged(read_case(case_id), staffed_version)

    cancelled = cancel_case(case_id, env["chief"]["id"])
    assert_case_dimensions(cancelled, "CANCELLED", "UNBILLED")
    assert_cents(cancelled["accrued_fee_cents"], 0, "accrued_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 0, 0)

    validate_error(
        api_client.cancel_bypass_case(case_id, env["chief_headers"], {"reason": "too late"}),
        ERR_CASE_NOT_CANCELLABLE,
        409,
    )
    validate_error(
        api_client.configure_disposable_pack(
            case_id, build_pack_configuration(env["d1"]["id"]), env["p1_headers"]
        ),
        ERR_CASE_NOT_STAFFED,
        409,
    )
    assert_device_state(read_device(env["d1"]["id"]), status="AVAILABLE", open_reservation_count=0)


def test_closed_case_is_locked_against_all_seven_case_triggers():
    """A closed case refuses every case-level trigger and its ledger stays where the close left it.

    PRD 2.8: In order: (26) the case is `SCHEDULED` or `STAFFED` for an assignment, else `ERR_CASE_NOT_ASSIGNABLE` (409); (27) the case is `STAFFED` for pack configuration, else `ERR_CASE_NOT_STAFFED` (409); (28) the case is `PACK_CONFIGURED` both for opening a pump checklist and for verifying one, else `ERR_CASE_NOT_PACK_CONFIGURED` (409); (29) the checklist itself is `DRAFT` when verified, else `ERR_CHECKLIST_NOT_DRAFT` (409); (30) the case is `SETUP_VERIFIED` to go on pump, else `ERR_CASE_NOT_SETUP_VERIFIED` (409); (31) the case is `ON_BYPASS` both to come off pump and to open an ECMO run, else `ERR_CASE_NOT_ON_BYPASS` (409); (32) the case is `OFF_BYPASS` to be closed, else `ERR_CASE_NOT_OFF_BYPASS` (409); (33) the case is one of `SCHEDULED`, `STAFFED`, `PACK_CONFIGURED` or `SETUP_VERIFIED` to be cancelled, else `ERR_CASE_NOT_CANCELLABLE` (409); (34) at pack configuration both the primary and the resolved backup machine hold a status of `AVAILABLE` or `RESERVED`, else `ERR_DEVICE_NOT_AVAILABLE` (409); (35) a service completion targets a device that is `NEEDS_SERVICE` and whose `open_reservation_count` is 0, else `ERR_DEVICE_SERVICE_NOT_PERMITTED` (409); (36) an incident report is in the origin state of the requested move — `DRAFT` or `RETURNED_FOR_INFO` to submit, `SUBMITTED` to review, `UNDER_REVIEW` to close — else `ERR_INCIDENT_STATE_INVALID` (409); (37) a return-for-information decision is only admitted while the report's `return_count` is below the two-return ceiling, else `ERR_INCIDENT_RETURN_LIMIT` (409); (38) a handoff targets a run in `RELIEF_PENDING` and a decannulation targets a run in `RUNNING` or `RELIEF_PENDING`, else `ERR_ECMO_RUN_STATE_INVALID` (409); (39) a CE claim being verified or rejected is `SUBMITTED`, and one being revoked is `VERIFIED`, else `ERR_CE_ACTIVITY_STATE_INVALID` (409); (40) a pack being adjudicated has `approval_status` of `PENDING`, else `ERR_PACK_APPROVAL_STATE_INVALID` (409).
    PRD 3.10: Closure moves the clinical dimension `OFF_BYPASS → CLOSED` and settles the fee for real.
    PRD 3.10: The assigned perfusionist's `career_case_count` rises by exactly one, which re-derives their `readiness_score` under the admission variant.

    Design: Corner/state_machines/closed_case_is_locked_against_all_seven_case_triggers
    """
    env = closed_case_setup(
        end_bypass_overrides={
            "pump_time_minutes": 120,
            "cross_clamp_minutes": 60,
            "lowest_hematocrit_pct": 24,
        }
    )
    case = env["case"]
    case_id = case["id"]
    closed_version = case["version"]

    assert_case_dimensions(case, "CLOSED", "FINAL_ACCRUED")
    assert_cents(case["final_fee_cents"], 400000, "final_fee_cents")
    assert_cents(case["accrued_fee_cents"], 400000, "accrued_fee_cents")

    validate_error(
        api_client.assign_perfusionist(
            case_id,
            build_assignment(env["p1"]["id"], closed_version),
            env["chief_headers"],
        ),
        ERR_CASE_NOT_ASSIGNABLE,
        409,
    )
    validate_error(
        api_client.configure_disposable_pack(
            case_id, build_pack_configuration(env["d1"]["id"]), env["p1_headers"]
        ),
        ERR_CASE_NOT_STAFFED,
        409,
    )
    validate_error(
        api_client.create_pump_checklist(
            case_id,
            build_pump_checklist(check_results=[build_check_result("ACT_BASELINE")]),
            env["p1_headers"],
        ),
        ERR_CASE_NOT_PACK_CONFIGURED,
        409,
    )
    validate_error(
        api_client.start_bypass(case_id, env["p1_headers"]),
        ERR_CASE_NOT_SETUP_VERIFIED,
        409,
    )
    validate_error(
        api_client.end_bypass(
            case_id,
            build_end_bypass(
                pump_time_minutes=200, cross_clamp_minutes=90, lowest_hematocrit_pct=21
            ),
            env["p1_headers"],
        ),
        ERR_CASE_NOT_ON_BYPASS,
        409,
    )
    validate_error(
        api_client.close_bypass_case(case_id, env["chief_headers"]),
        ERR_CASE_NOT_OFF_BYPASS,
        409,
    )
    validate_error(
        api_client.cancel_bypass_case(case_id, env["chief_headers"], {"reason": "too late"}),
        ERR_CASE_NOT_CANCELLABLE,
        409,
    )

    locked = read_case(case_id)
    assert locked["pump_time_minutes"] == 120
    assert_version_unchanged(locked, closed_version)
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)
    assert read_perfusionist(env["p1"]["id"])["career_case_count"] == 151


def test_repeating_pack_approval_and_ce_verification_is_rejected():
    """Approval and continuing-education adjudication are one-shot edges, not idempotent writes.

    PRD 2.8: In order: (26) the case is `SCHEDULED` or `STAFFED` for an assignment, else `ERR_CASE_NOT_ASSIGNABLE` (409); (27) the case is `STAFFED` for pack configuration, else `ERR_CASE_NOT_STAFFED` (409); (28) the case is `PACK_CONFIGURED` both for opening a pump checklist and for verifying one, else `ERR_CASE_NOT_PACK_CONFIGURED` (409); (29) the checklist itself is `DRAFT` when verified, else `ERR_CHECKLIST_NOT_DRAFT` (409); (30) the case is `SETUP_VERIFIED` to go on pump, else `ERR_CASE_NOT_SETUP_VERIFIED` (409); (31) the case is `ON_BYPASS` both to come off pump and to open an ECMO run, else `ERR_CASE_NOT_ON_BYPASS` (409); (32) the case is `OFF_BYPASS` to be closed, else `ERR_CASE_NOT_OFF_BYPASS` (409); (33) the case is one of `SCHEDULED`, `STAFFED`, `PACK_CONFIGURED` or `SETUP_VERIFIED` to be cancelled, else `ERR_CASE_NOT_CANCELLABLE` (409); (34) at pack configuration both the primary and the resolved backup machine hold a status of `AVAILABLE` or `RESERVED`, else `ERR_DEVICE_NOT_AVAILABLE` (409); (35) a service completion targets a device that is `NEEDS_SERVICE` and whose `open_reservation_count` is 0, else `ERR_DEVICE_SERVICE_NOT_PERMITTED` (409); (36) an incident report is in the origin state of the requested move — `DRAFT` or `RETURNED_FOR_INFO` to submit, `SUBMITTED` to review, `UNDER_REVIEW` to close — else `ERR_INCIDENT_STATE_INVALID` (409); (37) a return-for-information decision is only admitted while the report's `return_count` is below the two-return ceiling, else `ERR_INCIDENT_RETURN_LIMIT` (409); (38) a handoff targets a run in `RELIEF_PENDING` and a decannulation targets a run in `RUNNING` or `RELIEF_PENDING`, else `ERR_ECMO_RUN_STATE_INVALID` (409); (39) a CE claim being verified or rejected is `SUBMITTED`, and one being revoked is `VERIFIED`, else `ERR_CE_ACTIVITY_STATE_INVALID` (409); (40) a pack being adjudicated has `approval_status` of `PENDING`, else `ERR_PACK_APPROVAL_STATE_INVALID` (409).
    PRD 3.5: A pack whose `substitutions` array is non-empty has `requires_surgeon_approval` set true and `approval_status` set to `PENDING`; a pack with no substitutions has `requires_surgeon_approval` false and `approval_status` `NOT_REQUIRED`, and needs no further human act.
    PRD 3.5: The owning surgeon adjudicates a pending pack with a `decision` of `APPROVED` or `REJECTED` and an optional `note`, moving `approval_status` from `PENDING` to the decided value and advancing the pack's `version`; a pack that is not `PENDING` cannot be adjudicated at all, which is `ERR_PACK_APPROVAL_STATE_INVALID`.
    PRD 3.5: Its `line_items` array is built by walking the selected card's `pack_line_items` in order: for each template, if a substitution names that template's line code, the materialised line takes the substitution's `replacement_code` as its `line_code`, the substitution's `replacement_unit_cost_cents` as its `unit_cost_cents`, and carries `substituted` true; otherwise the line takes the template's own line code and unit cost and carries `substituted` false.
    PRD 3.2: A `VERIFIED` decision moves the claim `SUBMITTED → VERIFIED`, lowers the holder's pending total by the claim's hours and raises the verified total by the same hours.
    PRD 3.2: A `REVOKED` decision applies to a claim already in `VERIFIED`, moves it `VERIFIED → REVOKED`, lowers the verified total by exactly the claim's hours, and — when that claim had been marked `counted_toward_remediation` — withdraws the same hours from the certification's `probation_credits_banked` before clearing `counted_toward_remediation` back to false.

    Design: Corner/state_machines/repeating_pack_approval_and_ce_verification_is_rejected
    """
    env = staffed_setup()
    pack = configure_pack(
        env["case"]["id"],
        env["d1"]["id"],
        env["p1"]["id"],
        substitutions=[
            build_substitution("A_OXYGENATOR", "A_OXYGENATOR_ALT", 1200, "vendor stockout")
        ],
    )
    assert pack["requires_surgeon_approval"] is True
    assert pack["approval_status"] == "PENDING"
    assert_cents(pack["pack_cost_cents"], 3898, "pack_cost_cents")
    assert_pack_line(pack["line_items"][0], "A_OXYGENATOR_ALT", 1, 1200, 1296, True)

    approved = approve_pack(
        pack["id"], env["surgeon"]["id"], "APPROVED", note="alternate oxygenator accepted"
    )
    assert approved["approval_status"] == "APPROVED"
    assert approved["line_items"][0]["substituted"] is True

    validate_error(
        api_client.approve_disposable_pack(
            pack["id"],
            build_pack_decision("REJECTED", note="changed my mind"),
            env["surgeon_headers"],
        ),
        ERR_PACK_APPROVAL_STATE_INVALID,
        409,
    )
    assert read_pack(pack["id"])["approval_status"] == "APPROVED"

    verified = adjudicate_ce_activity(env["ce"]["id"], "VERIFIED", note="transcript on file")
    assert verified["status"] == "VERIFIED"
    holder = read_perfusionist(env["p1"]["id"])
    assert_ce_hours(holder["ce_credits_verified"], 20)
    assert_ce_hours(holder["ce_credits_pending"], 0)

    validate_error(
        api_client.adjudicate_ce_activity(
            env["ce"]["id"], build_ce_decision("VERIFIED", note="filed twice"), ADMIN_HEADERS
        ),
        ERR_CE_ACTIVITY_STATE_INVALID,
        409,
    )
    assert_ce_hours(read_perfusionist(env["p1"]["id"])["ce_credits_verified"], 20)

    revoked = adjudicate_ce_activity(
        env["ce"]["id"], "REVOKED", note="accreditation withdrawn"
    )
    assert revoked["status"] == "REVOKED"
    holder = read_perfusionist(env["p1"]["id"])
    assert_ce_hours(holder["ce_credits_verified"], 0)
    assert_ce_hours(holder["ce_credits_pending"], 0)

    validate_error(
        api_client.adjudicate_ce_activity(
            env["ce"]["id"], build_ce_decision("REVOKED", note="withdrawn again"), ADMIN_HEADERS
        ),
        ERR_CE_ACTIVITY_STATE_INVALID,
        409,
    )
    assert_ce_hours(read_perfusionist(env["p1"]["id"])["ce_credits_verified"], 0)


def test_repeating_decannulation_and_incident_submission_is_rejected():
    """A closed support run and a submitted report both refuse a replay of the edge that moved them.

    PRD 2.8: In order: (26) the case is `SCHEDULED` or `STAFFED` for an assignment, else `ERR_CASE_NOT_ASSIGNABLE` (409); (27) the case is `STAFFED` for pack configuration, else `ERR_CASE_NOT_STAFFED` (409); (28) the case is `PACK_CONFIGURED` both for opening a pump checklist and for verifying one, else `ERR_CASE_NOT_PACK_CONFIGURED` (409); (29) the checklist itself is `DRAFT` when verified, else `ERR_CHECKLIST_NOT_DRAFT` (409); (30) the case is `SETUP_VERIFIED` to go on pump, else `ERR_CASE_NOT_SETUP_VERIFIED` (409); (31) the case is `ON_BYPASS` both to come off pump and to open an ECMO run, else `ERR_CASE_NOT_ON_BYPASS` (409); (32) the case is `OFF_BYPASS` to be closed, else `ERR_CASE_NOT_OFF_BYPASS` (409); (33) the case is one of `SCHEDULED`, `STAFFED`, `PACK_CONFIGURED` or `SETUP_VERIFIED` to be cancelled, else `ERR_CASE_NOT_CANCELLABLE` (409); (34) at pack configuration both the primary and the resolved backup machine hold a status of `AVAILABLE` or `RESERVED`, else `ERR_DEVICE_NOT_AVAILABLE` (409); (35) a service completion targets a device that is `NEEDS_SERVICE` and whose `open_reservation_count` is 0, else `ERR_DEVICE_SERVICE_NOT_PERMITTED` (409); (36) an incident report is in the origin state of the requested move — `DRAFT` or `RETURNED_FOR_INFO` to submit, `SUBMITTED` to review, `UNDER_REVIEW` to close — else `ERR_INCIDENT_STATE_INVALID` (409); (37) a return-for-information decision is only admitted while the report's `return_count` is below the two-return ceiling, else `ERR_INCIDENT_RETURN_LIMIT` (409); (38) a handoff targets a run in `RELIEF_PENDING` and a decannulation targets a run in `RUNNING` or `RELIEF_PENDING`, else `ERR_ECMO_RUN_STATE_INVALID` (409); (39) a CE claim being verified or rejected is `SUBMITTED`, and one being revoked is `VERIFIED`, else `ERR_CE_ACTIVITY_STATE_INVALID` (409); (40) a pack being adjudicated has `approval_status` of `PENDING`, else `ERR_PACK_APPROVAL_STATE_INVALID` (409).
    PRD 3.8: On success `decannulated_at` is set to the logical clock, the run moves to `DECANNULATED`, which is terminal, and the pricing runs.
    PRD 3.8: It is the number of minutes between the later of `last_handoff_at` and `cannulated_at` — `cannulated_at` before the first handoff — and the logical clock while the run is open, or between that same starting instant and `decannulated_at` once the run is closed.
    PRD 3.8: The total minutes between `cannulated_at` and `decannulated_at` are divided by 60 and rounded **up** to the next whole hour to give `billable_hours`: 60 minutes bill as 1 hour, 61 minutes bill as 2, and 1441 minutes bill as 25.
    PRD 3.8: A mode uplift percentage is read from the configuration: 0.00 for `VV`, 0.15 for `VA` and 0.30 for `VAV`.
    PRD 3.8: The run must be in `RELIEF_PENDING`, else `ERR_ECMO_RUN_STATE_INVALID` — a run only 400 minutes into its shift cannot be handed over early.
    PRD 3.3: Only in the relief case is `consumed` set to true, and a consumed relief slot may never be named by a second handoff.
    PRD 3.9: Submission moves the report to `SUBMITTED` and does nothing else but advance its `version`.
    PRD 3.9: Only a chief may close, the report must be `UNDER_REVIEW`, and the closer may be neither the involved perfusionist nor the filer — the same segregation-of-duties test as at review, now with a second purpose, since the closer's identity is recorded in `closed_by_perfusionist_id`.

    Design: Corner/state_machines/repeating_decannulation_and_incident_submission_is_rejected
    """
    env = on_bypass_setup()
    run = create_ecmo_run(env["case"]["id"], env["p1"]["id"], "VA")
    set_clock("2026-08-01T06:30:00Z")

    closed_run = decannulate_ecmo_run(run["id"], env["p1"]["id"])
    assert closed_run["status"] == "DECANNULATED"
    assert closed_run["decannulated_at"] == "2026-08-01T06:30:00Z"
    assert float(closed_run["uninterrupted_minutes"]) == 390
    assert closed_run["billable_hours"] == 7
    assert_cents(closed_run["ecmo_fee_cents"], 724500, "ecmo_fee_cents")

    validate_error(
        api_client.decannulate_ecmo_run(run["id"], env["p1_headers"]),
        ERR_ECMO_RUN_STATE_INVALID,
        409,
    )
    replayed = read_ecmo_run(run["id"])
    assert replayed["billable_hours"] == 7
    assert_cents(replayed["ecmo_fee_cents"], 724500, "ecmo_fee_cents")

    validate_error(
        api_client.handoff_ecmo_run(
            run["id"], build_ecmo_handoff(env["slot_p1"]["id"]), env["chief_headers"]
        ),
        ERR_ECMO_RUN_STATE_INVALID,
        409,
    )
    slot = read_slot(env["slot_p1"]["id"])
    assert slot["consumed"] is False
    assert slot["status"] == "ACTIVE"

    end_bypass(
        env["case"]["id"],
        env["p1"]["id"],
        pump_time_minutes=120,
        cross_clamp_minutes=60,
        lowest_hematocrit_pct=24,
        adverse_event_count=1,
    )
    close_case(env["case"]["id"], env["chief"]["id"])

    report = create_incident_report(
        env["case"]["id"],
        env["p1"]["id"],
        env["p1"]["id"],
        severity="MAJOR",
        category="GAS_EXCHANGE",
        narrative="Oxygenator gas exchange degraded during the VA run.",
    )
    assert report["status"] == "DRAFT"

    submitted = submit_incident_report(report["id"], env["p1"]["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["filed_by_perfusionist_id"] == env["p1"]["id"]
    assert submitted["return_count"] == 0
    submitted_version = submitted["version"]

    validate_error(
        api_client.submit_incident_report(report["id"], env["p1_headers"]),
        ERR_INCIDENT_STATE_INVALID,
        409,
    )
    assert_version_unchanged(read_incident_report(report["id"]), submitted_version)

    validate_error(
        api_client.close_incident_report(
            report["id"], build_incident_close("ISOLATED"), env["chief_headers"]
        ),
        ERR_INCIDENT_STATE_INVALID,
        409,
    )
    still_submitted = read_incident_report(report["id"])
    assert still_submitted["finding"] == "NONE"
    assert still_submitted["corrective_action_required"] is False
    certifications, _ = validate_paginated(
        api_client.list_certifications(env["p1"]["id"], ADMIN_HEADERS)
    )
    assert [row["status"] for row in certifications] == ["ACTIVE"]


def test_checklist_verify_requires_draft_status_and_a_pack_configured_case():
    """Sign-off carries two preconditions, and only re-arming the case exposes the second one.

    PRD 3.6: Opening one is permitted only while the case is `PACK_CONFIGURED`, and both opening and signing off refuse with `ERR_CASE_NOT_PACK_CONFIGURED` when the case is anywhere else.
    PRD 3.6: The checklist must still be `DRAFT`, else `ERR_CHECKLIST_NOT_DRAFT`.
    PRD 3.6: A checklist in `DRAFT` or `VERIFIED` is driven to `INVALIDATED` either by the critical-alarm cascade of §3.7 or by the cancellation of its case, and in both instances `blood_mgmt_signoff` returns to false and `verified_at` returns to null.
    PRD 3.6: An invalidated checklist can never be verified again; the perfusionist opens a new one.
    PRD 3.7: The second link reaches every bypass case naming that machine as its **primary** whose `bypass_status` is `PACK_CONFIGURED` or `SETUP_VERIFIED`: such a case falls back to `STAFFED`, its `setup_verified_at` is cleared to null, its `readiness_flag` is raised to `DEVICE_FALLBACK_REQUIRED`, both its `primary_device_id` and its `backup_device_id` are cleared to null, and the standby machine it was holding moves `RESERVED → AVAILABLE`.
    PRD 3.7: The fourth link unwinds money: each of those same cases whose `billing_status` reads `PROVISIONAL_ACCRUED` moves to `UNBILLED`, its `accrued_fee_cents` drops to 0, and the contract's `accrued_case_fee_cents` falls by exactly that amount while `accrued_case_count` falls by one.
    PRD 3.7: The flag itself is cleared only by a fresh pack configuration, which is available only while the case is `STAFFED`, or by cancelling the case.

    Design: Corner/state_machines/checklist_verify_requires_draft_status_and_a_pack_configured_case
    """
    env = setup_verified_setup()
    assert env["checklist"]["status"] == "VERIFIED"
    assert env["case"]["bypass_status"] == "SETUP_VERIFIED"

    validate_error(
        api_client.verify_pump_checklist(env["checklist"]["id"], env["p1_headers"]),
        ERR_CASE_NOT_PACK_CONFIGURED,
        409,
    )

    capture_device_event(env["d1"]["id"], "ALARM_CRITICAL", detail="console self test alarm")

    reverted = read_case(env["case"]["id"])
    assert_case_dimensions(reverted, "STAFFED", "UNBILLED")
    assert_fields_null(reverted, ["primary_device_id", "backup_device_id", "setup_verified_at"])
    assert reverted["readiness_flag"] == "DEVICE_FALLBACK_REQUIRED"
    invalidated = read_checklist(env["checklist"]["id"])
    assert invalidated["status"] == "INVALIDATED"
    assert invalidated["blood_mgmt_signoff"] is False
    assert invalidated["verified_at"] is None
    assert_contract_ledger(read_contract(env["contract"]["id"]), 0, 0)

    complete_device_service(env["d1"]["id"], detail="console board replaced")
    second_pack = configure_pack(env["case"]["id"], env["d1"]["id"], env["p1"]["id"])
    assert second_pack["id"] != env["pack"]["id"]

    rearmed = read_case(env["case"]["id"])
    assert rearmed["bypass_status"] == "PACK_CONFIGURED"
    assert rearmed["readiness_flag"] == "NONE"
    assert rearmed["primary_device_id"] == env["d1"]["id"]
    assert rearmed["backup_device_id"] == env["d2"]["id"]

    validate_error(
        api_client.verify_pump_checklist(env["checklist"]["id"], env["p1_headers"]),
        ERR_CHECKLIST_NOT_DRAFT,
        409,
    )
    final = read_checklist(env["checklist"]["id"])
    assert final["status"] == "INVALIDATED"
    assert final["verified_at"] is None
    assert final["blood_mgmt_signoff"] is False


def test_end_bypass_service_due_branch_fires_only_when_runtime_reaches_the_interval():
    """Runtime reaching the service interval selects the service-due branch and stays device-local.

    PRD 3.1: `service_interval_hours` is the runtime allowance between preventive services, defaulting to 500 hours and at least 1.
    PRD 3.6: The primary machine's `runtime_hours_since_service` rises by the reported pump minutes divided by 60, kept exact and unrounded — a 95-minute case adds one and five-twelfths hours, not one or two.
    PRD 3.6: If the machine is not clean — its `alarm_count_since_service` is greater than 0 **or** its accumulated runtime has reached its service interval — it moves `IN_USE → NEEDS_SERVICE` and, additionally, the service records an event log against it with `event_code` `SELF_TEST_FAIL` and the `detail` text "service interval reached at end of case".
    PRD 3.6: That extra event log is the observable difference between the service-due branch and the clean ones.
    PRD 3.6: Meanwhile the standby machine moves `RESERVED → AVAILABLE`, and both machines' `open_reservation_count` values are recomputed.
    PRD 3.10: Closure moves the clinical dimension `OFF_BYPASS → CLOSED` and settles the fee for real.
    PRD 3.7: A `BiomedTech` records a service completion, optionally with `detail`, against a machine that is in `NEEDS_SERVICE` and whose `open_reservation_count` is 0; a machine in any other state, or one still carrying a live reservation, is refused with `ERR_DEVICE_SERVICE_NOT_PERMITTED`.

    Design: Corner/state_machines/end_bypass_service_due_branch_fires_only_when_runtime_reaches_the_interval
    """
    env = base_setup(with_devices=False)
    env["d2"] = create_device(env["contract"]["id"], asset_tag="HLM-002")
    env["d1"] = create_device(
        env["contract"]["id"],
        asset_tag="HLM-001",
        backup_device_id=env["d2"]["id"],
        service_interval_hours=2,
    )

    case = assign_perfusionist(
        env["case"]["id"], env["p1"]["id"], env["case"]["version"], env["chief"]["id"]
    )
    configure_pack(case["id"], env["d1"]["id"], env["p1"]["id"])
    checklist = open_checklist(case["id"], env["p1"]["id"])
    verify_checklist(checklist["id"], env["p1"]["id"])
    start_bypass(case["id"], env["p1"]["id"])

    off_pump = end_bypass(
        case["id"],
        env["p1"]["id"],
        pump_time_minutes=120,
        cross_clamp_minutes=60,
        lowest_hematocrit_pct=24,
        adverse_event_count=0,
    )

    assert_device_state(
        read_device(env["d1"]["id"]),
        status="NEEDS_SERVICE",
        open_reservation_count=0,
        runtime_hours_since_service=2.0,
    )
    _, meta = validate_paginated(
        api_client.list_device_event_logs(
            env["d1"]["id"], TECH_HEADERS, {"event_code": "SELF_TEST_FAIL"}
        )
    )
    assert meta["total_count"] == 1
    assert_device_state(
        read_device(env["d2"]["id"]), status="AVAILABLE", open_reservation_count=0
    )

    assert off_pump["bypass_status"] == "OFF_BYPASS"
    assert off_pump["readiness_flag"] == "NONE"
    assert read_checklist(checklist["id"])["status"] == "VERIFIED"

    closed = close_case(case["id"], env["chief"]["id"])
    assert_case_dimensions(closed, "CLOSED", "FINAL_ACCRUED")
    assert_cents(closed["final_fee_cents"], 400000, "final_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)

    serviced = complete_device_service(env["d1"]["id"], detail="preventive service performed")
    assert_device_state(
        serviced, status="AVAILABLE", runtime_hours_since_service=0, alarm_count_since_service=0
    )


def test_rotation_slot_completes_only_when_the_last_on_bypass_case_ends():
    """The slot's completion edge is an aggregate over its holder's cases, not a per-case effect.

    PRD 3.3: `ACTIVE → COMPLETED` happens when a case comes off pump or a run is decannulated, but only once no case of that slot's perfusionist remains on pump and no extracorporeal run tied to that slot remains open.
    PRD 3.6: The covering call slot moves `ACTIVE → COMPLETED` when the perfusionist has no other case still on pump.
    PRD 3.4: The concurrency limit looks only at other cases whose half-open planned interval intersects this case's half-open planned interval.
    PRD 3.4: Among those, fewer than 2 may already be staffed to the incoming perfusionist in `STAFFED`, `PACK_CONFIGURED` or `SETUP_VERIFIED` — so a perfusionist may hold two overlapping prepared cases but not three — and exactly zero of them may be staffed to that perfusionist in `ON_BYPASS`, because nobody runs two pumps at once.
    PRD 3.5: The consequence at the boundary is worth stating plainly: a raw gap of exactly 90 minutes between two cases collides and is refused, while a gap of 91 minutes passes.
    PRD 3.6: The primary machine's `runtime_hours_since_service` rises by the reported pump minutes divided by 60, kept exact and unrounded — a 95-minute case adds one and five-twelfths hours, not one or two.
    PRD 3.6: The fiscal dimension is deliberately untouched: a case that has come off pump still reads `PROVISIONAL_ACCRUED`, because coming off pump is a clinical event and settlement is a fiscal one.

    Design: Corner/state_machines/rotation_slot_completes_only_when_the_last_on_bypass_case_ends
    """
    env = on_bypass_setup()
    add_device(env, "d3", asset_tag="HLM-003")
    add_device(env, "d4", asset_tag="HLM-004")

    case_b = add_case(
        env,
        "case_b",
        scheduled_start="2026-08-02T13:31:00Z",
        scheduled_end="2026-08-02T19:31:00Z",
    )
    case_b = assign_perfusionist(
        case_b["id"], env["p1"]["id"], case_b["version"], env["chief"]["id"]
    )
    configure_pack(
        case_b["id"], env["d3"]["id"], env["p1"]["id"], backup_device_id=env["d4"]["id"]
    )
    checklist_b = open_checklist(case_b["id"], env["p1"]["id"])
    verify_checklist(checklist_b["id"], env["p1"]["id"])
    case_b = start_bypass(case_b["id"], env["p1"]["id"])

    assert read_case(env["case"]["id"])["bypass_status"] == "ON_BYPASS"
    assert case_b["bypass_status"] == "ON_BYPASS"

    first_off = end_bypass(
        env["case"]["id"],
        env["p1"]["id"],
        pump_time_minutes=120,
        cross_clamp_minutes=60,
        lowest_hematocrit_pct=24,
    )
    assert read_slot(env["slot_p1"]["id"])["status"] == "ACTIVE"
    assert first_off["bypass_status"] == "OFF_BYPASS"
    assert_device_state(read_device(env["d1"]["id"]), status="AVAILABLE")
    assert_device_state(read_device(env["d2"]["id"]), status="AVAILABLE")
    assert_device_state(read_device(env["d3"]["id"]), status="IN_USE")

    second_off = end_bypass(
        case_b["id"],
        env["p1"]["id"],
        pump_time_minutes=150,
        cross_clamp_minutes=70,
        lowest_hematocrit_pct=25,
    )
    assert read_slot(env["slot_p1"]["id"])["status"] == "COMPLETED"
    assert second_off["bypass_status"] == "OFF_BYPASS"
    assert_device_state(
        read_device(env["d3"]["id"]), status="AVAILABLE", runtime_hours_since_service=2.5
    )
    assert_device_state(read_device(env["d4"]["id"]), status="AVAILABLE")

    assert_case_dimensions(read_case(env["case"]["id"]), "OFF_BYPASS", "PROVISIONAL_ACCRUED")
    assert_case_dimensions(read_case(case_b["id"]), "OFF_BYPASS", "PROVISIONAL_ACCRUED")
    assert_cents(first_off["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert_cents(second_off["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 800000, 2)
