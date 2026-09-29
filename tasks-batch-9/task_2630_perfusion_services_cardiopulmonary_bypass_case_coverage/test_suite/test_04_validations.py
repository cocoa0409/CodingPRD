"""Field, cross-entity, temporal and aggregate guards, and the order they fire in."""
from test_helpers import (
    ADMIN_HEADERS,
    ERR_BLOOD_PROTOCOL_MISMATCH,
    ERR_CASE_START_IN_PAST,
    ERR_CLOCK_NOT_MONOTONIC,
    ERR_CROSS_CLAMP_EXCEEDS_PUMP_TIME,
    ERR_DEVICE_SERVICE_OVERDUE,
    ERR_ECMO_PRIVILEGE_REQUIRED,
    ERR_ECMO_STAFFING_BREACH,
    ERR_HEMATOCRIT_BELOW_MINIMUM,
    ERR_INCIDENT_CASE_NOT_COMPLETE,
    ERR_INVALID_SUBSTITUTION_LINE,
    ERR_INVALID_TIME_WINDOW,
    ERR_NO_ACTIVE_PREFERENCE_CARD,
    ERR_PACK_APPROVAL_PENDING,
    ERR_PERFUSIONIST_NOT_ACTIVE,
    ERR_PROCEDURE_SPECIALTY_MISMATCH,
    ERR_SAFETY_CHECKS_INCOMPLETE,
    ERR_SURGEON_NOT_ACTIVE,
    INITIAL_CLOCK,
    add_device,
    api_client,
    approve_pack,
    assert_case_dimensions,
    assert_cents,
    assert_created_at_ascending,
    assert_device_state,
    assert_fields_null,
    assign_perfusionist,
    base_setup,
    build_bypass_case,
    build_call_rotation_slot,
    build_certification,
    build_check_result,
    build_clock,
    build_end_bypass,
    build_pack_configuration,
    build_substitution,
    capture_device_event,
    complete_device_service,
    configure_pack,
    create_case,
    create_contract,
    create_ecmo_run,
    create_incident_report,
    create_perfusionist,
    create_slot,
    create_surgeon,
    end_bypass,
    make_perfusionist_headers,
    on_bypass_setup,
    open_checklist,
    pack_configured_setup,
    read_case,
    read_checklist,
    read_device,
    read_ecmo_run,
    read_incident_report,
    read_pack,
    read_contract,
    set_clock,
    staffed_setup,
    submit_incident_report,
    validate_error,
    validate_paginated,
    validate_success,
    verify_checklist,
)

CLEAN_CHECKS = [
    build_check_result("ACT_BASELINE"),
    build_check_result("CIRCUIT_INTEGRITY"),
    build_check_result("GAS_LINE"),
]


def test_checklist_verify_ladder_returns_the_highest_priority_violation_first():
    """Four checklists relax one gate each, so verify answers the safety, protocol and hematocrit rules in order.

    PRD 3.6: The server immediately derives `missing_check_codes` against the pinned preference card: it is the array of codes appearing in that card's `required_safety_check_codes` that are either absent from `check_results` altogether or present there with `passed` false, ordered ascending.
    PRD 3.6: Then four clinical conditions are checked in the order §2.8 fixes: `missing_check_codes` must be the empty array, else `ERR_SAFETY_CHECKS_INCOMPLETE`; the checklist's `blood_management_protocol` must equal the applied card's `blood_management_protocol` exactly, else `ERR_BLOOD_PROTOCOL_MISMATCH` — a bloodless-protocol case set up on a standard protocol is a serious event, not a formatting difference; the checklist's `hematocrit_pct` must be at or above the applied card's `min_hematocrit_pct`, else `ERR_HEMATOCRIT_BELOW_MINIMUM`; and the case's pack must not be awaiting or refused surgeon approval, else `ERR_PACK_APPROVAL_PENDING`.
    PRD 3.6: On success the checklist moves `DRAFT → VERIFIED` with `blood_mgmt_signoff` set true, `verified_by_perfusionist_id` set to the acting perfusionist and `verified_at` set to the logical clock, while the case moves `PACK_CONFIGURED → SETUP_VERIFIED` with `setup_verified_at` set to the same instant.
    PRD 3.6: A fresh checklist begins in `DRAFT` with `blood_mgmt_signoff` false, `verified_at` null and `verified_by_perfusionist_id` null.

    Design: Corner/validations/checklist_verify_ladder_returns_the_highest_priority_violation_first
    """
    env = pack_configured_setup()
    case_id = env["case"]["id"]
    p1_id = env["p1"]["id"]
    assert_case_dimensions(env["case"], "PACK_CONFIGURED", "PROVISIONAL_ACCRUED")
    assert read_pack(env["pack"]["id"])["approval_status"] == "NOT_REQUIRED"

    failing_checks = [
        build_check_result("ACT_BASELINE"),
        build_check_result("CIRCUIT_INTEGRITY"),
        build_check_result("GAS_LINE", passed=False, note="blender fault"),
    ]
    chk_a = open_checklist(
        case_id,
        p1_id,
        check_results=failing_checks,
        blood_management_protocol="ANTIFIBRINOLYTIC",
        hematocrit_pct=18,
    )
    chk_b = open_checklist(
        case_id,
        p1_id,
        check_results=[dict(item) for item in CLEAN_CHECKS],
        blood_management_protocol="ANTIFIBRINOLYTIC",
        hematocrit_pct=18,
    )
    chk_c = open_checklist(
        case_id,
        p1_id,
        check_results=[dict(item) for item in CLEAN_CHECKS],
        hematocrit_pct=21,
    )
    chk_d = open_checklist(
        case_id,
        p1_id,
        check_results=[dict(item) for item in CLEAN_CHECKS],
        hematocrit_pct=22,
    )
    assert chk_a["missing_check_codes"] == ["GAS_LINE"]
    assert chk_b["missing_check_codes"] == []

    validate_error(
        api_client.verify_pump_checklist(chk_a["id"], env["p1_headers"]),
        ERR_SAFETY_CHECKS_INCOMPLETE,
        422,
    )
    validate_error(
        api_client.verify_pump_checklist(chk_b["id"], env["p1_headers"]),
        ERR_BLOOD_PROTOCOL_MISMATCH,
        422,
    )
    validate_error(
        api_client.verify_pump_checklist(chk_c["id"], env["p1_headers"]),
        ERR_HEMATOCRIT_BELOW_MINIMUM,
        422,
    )
    for refused in (chk_a, chk_b, chk_c):
        current = read_checklist(refused["id"])
        assert current["status"] == "DRAFT"
        assert current["blood_mgmt_signoff"] is False
        assert_fields_null(current, ["verified_at", "verified_by_perfusionist_id"])

    verified = verify_checklist(chk_d["id"], p1_id)
    assert verified["status"] == "VERIFIED"
    assert verified["blood_mgmt_signoff"] is True
    assert verified["verified_by_perfusionist_id"] == p1_id
    assert verified["verified_at"] == INITIAL_CLOCK
    case = read_case(case_id)
    assert_case_dimensions(case, "SETUP_VERIFIED", "PROVISIONAL_ACCRUED")
    assert case["setup_verified_at"] == INITIAL_CLOCK


def test_pack_substitution_gate_applies_only_when_the_pack_requested_one():
    """The approval gate is a function of the pack's approval_status, not of the checklist.

    PRD 3.5: Substitutions require the surgeon's blessing.
    PRD 3.5: A pack whose `substitutions` array is non-empty has `requires_surgeon_approval` set true and `approval_status` set to `PENDING`; a pack with no substitutions has `requires_surgeon_approval` false and `approval_status` `NOT_REQUIRED`, and needs no further human act.
    PRD 3.5: The owning surgeon adjudicates a pending pack with a `decision` of `APPROVED` or `REJECTED` and an optional `note`, moving `approval_status` from `PENDING` to the decided value and advancing the pack's `version`; a pack that is not `PENDING` cannot be adjudicated at all, which is `ERR_PACK_APPROVAL_STATE_INVALID`.
    PRD 3.5: A `REJECTED` pack does not unwind the case — the case stays in `PACK_CONFIGURED` — but it does keep blocking: both checklist verification and case closure refuse with `ERR_PACK_APPROVAL_PENDING` until the case's pack reads `NOT_REQUIRED` or `APPROVED`.
    PRD 3.5: The pack's `pack_cost_cents` is the exact sum of those already-rounded line totals — never the rounding of an unrounded sum, as §2.6 insists.

    Design: Corner/validations/pack_substitution_gate_applies_only_when_the_pack_requested_one
    """
    env = staffed_setup()
    case_id = env["case"]["id"]
    p1_id = env["p1"]["id"]
    pack = configure_pack(
        case_id,
        env["d1"]["id"],
        p1_id,
        substitutions=[build_substitution("A_OXYGENATOR", "A_OXYGENATOR_ALT", 1200, "recall")],
    )
    assert pack["requires_surgeon_approval"] is True
    assert pack["approval_status"] == "PENDING"
    assert_cents(pack["pack_cost_cents"], 3898, "pack_cost_cents")

    checklist = open_checklist(
        case_id, p1_id, check_results=[dict(item) for item in CLEAN_CHECKS], hematocrit_pct=26
    )
    validate_error(
        api_client.verify_pump_checklist(checklist["id"], env["p1_headers"]),
        ERR_PACK_APPROVAL_PENDING,
        409,
    )
    assert read_checklist(checklist["id"])["status"] == "DRAFT"
    assert read_case(case_id)["bypass_status"] == "PACK_CONFIGURED"

    approved = approve_pack(pack["id"], env["surgeon"]["id"], note="alt oxygenator accepted")
    assert approved["approval_status"] == "APPROVED"
    assert_cents(approved["pack_cost_cents"], 3898, "pack_cost_cents")

    verified = verify_checklist(checklist["id"], p1_id)
    assert verified["status"] == "VERIFIED"
    assert read_case(case_id)["bypass_status"] == "SETUP_VERIFIED"


def test_pack_config_rejects_a_substitution_line_absent_from_the_selected_card():
    """A substitution naming a line the selected card does not carry writes no pack at all.

    PRD 3.5: The `line_code` values must be unique within the array, and every one of them must exist among the selected card's `pack_line_items`; a substitution naming a line the card does not contain is `ERR_INVALID_SUBSTITUTION_LINE`.
    PRD 3.5: The candidate set is every preference card whose `surgeon_id` is the case's surgeon, whose `procedure_type` is the case's procedure, and whose `status` is `ACTIVE`.

    Design: Corner/validations/pack_config_rejects_a_substitution_line_absent_from_the_selected_card
    """
    env = staffed_setup()
    case_id = env["case"]["id"]
    validate_error(
        api_client.configure_disposable_pack(
            case_id,
            build_pack_configuration(
                env["d1"]["id"],
                substitutions=[
                    build_substitution("D_HEATER_HOSE", "D_HEATER_HOSE_ALT", 900, "not stocked")
                ],
            ),
            env["p1_headers"],
        ),
        ERR_INVALID_SUBSTITUTION_LINE,
        422,
    )
    case = read_case(case_id)
    assert_case_dimensions(case, "STAFFED", "PROVISIONAL_ACCRUED")
    assert_fields_null(case, ["primary_device_id", "backup_device_id"])
    assert_device_state(read_device(env["d1"]["id"]), "AVAILABLE", 0)
    assert_device_state(read_device(env["d2"]["id"]), "AVAILABLE", 0)
    packs, meta = validate_paginated(api_client.list_disposable_packs(ADMIN_HEADERS))
    assert meta["total_count"] == 0
    assert packs == []


def test_case_creation_and_pack_config_read_the_surgeon_and_card_side():
    """Specialty, surgeon status and the card selector are all guards on rows the request only names.

    PRD 3.4: The procedure must be within the named surgeon's competence: an `ADULT_CARDIAC` surgeon may take `CABG`, `VALVE`, `AORTIC_ARCH` and `VAD_IMPLANT`; a `PEDIATRIC_CARDIAC` surgeon may take `PEDIATRIC_SWITCH` and `VALVE`; a `TRANSPLANT` surgeon may take `TRANSPLANT` and `VAD_IMPLANT`; anything else is `ERR_PROCEDURE_SPECIALTY_MISMATCH`.
    PRD 3.4: The surgeon's own `status` must be `ACTIVE`, or the request is `ERR_SURGEON_NOT_ACTIVE`.
    PRD 3.5: The candidate set is every preference card whose `surgeon_id` is the case's surgeon, whose `procedure_type` is the case's procedure, and whose `status` is `ACTIVE`.
    PRD 3.5: An empty candidate set is refused with `ERR_NO_ACTIVE_PREFERENCE_CARD`.

    Design: Corner/validations/case_creation_and_pack_config_read_the_surgeon_and_card_side
    """
    env = base_setup(with_case=False)
    contract_id = env["contract"]["id"]
    pediatric = create_surgeon(
        full_name="Dr Petra Lindqvist", npi_code="NPI-3300220", specialty="PEDIATRIC_CARDIAC"
    )
    retired = create_surgeon(
        full_name="Dr Owen Achebe", npi_code="NPI-3300330", status="INACTIVE"
    )
    cardless = create_surgeon(full_name="Dr Halima Rossi", npi_code="NPI-3300440")

    validate_error(
        api_client.create_bypass_case(
            build_bypass_case(contract_id, pediatric["id"]), env["chief_headers"]
        ),
        ERR_PROCEDURE_SPECIALTY_MISMATCH,
        422,
    )
    validate_error(
        api_client.create_bypass_case(
            build_bypass_case(contract_id, retired["id"]), env["chief_headers"]
        ),
        ERR_SURGEON_NOT_ACTIVE,
        422,
    )

    case = create_case(contract_id, cardless["id"], chief_id=env["chief"]["id"])
    assert_case_dimensions(case, "SCHEDULED", "UNBILLED")
    staffed = assign_perfusionist(
        case["id"], env["p1"]["id"], case["version"], env["chief"]["id"]
    )
    assert_case_dimensions(staffed, "STAFFED", "PROVISIONAL_ACCRUED")

    validate_error(
        api_client.configure_disposable_pack(
            case["id"], build_pack_configuration(env["d1"]["id"]), env["p1_headers"]
        ),
        ERR_NO_ACTIVE_PREFERENCE_CARD,
        422,
    )
    still_staffed = read_case(case["id"])
    assert still_staffed["bypass_status"] == "STAFFED"
    assert_fields_null(still_staffed, ["primary_device_id"])
    assert_device_state(read_device(env["d1"]["id"]), "AVAILABLE", 0)
    _, meta = validate_paginated(api_client.list_bypass_cases(ADMIN_HEADERS))
    assert meta["total_count"] == 1


def test_temporal_guards_reject_inverted_windows_past_starts_and_a_backward_clock():
    """Inverted windows, past starts and a backward clock are all measured against the logical clock.

    PRD 2.8: Rungs 62 through 71 are temporal constraints, with one fiscal constraint interleaved: (62) every declared interval ends strictly later than it starts — a case's `scheduled_end` after its `scheduled_start`, a slot's `window_end` after its `window_start`, a certification's `expires_on` after its `issued_on` — else `ERR_INVALID_TIME_WINDOW` (422); (63) a scheduled case does not start in the past relative to the logical clock, else `ERR_CASE_START_IN_PAST` (422); (64) the clock never moves backwards, else `ERR_CLOCK_NOT_MONOTONIC` (422); (65) a claimed CE activity falls inside the holder's current certification cycle, else `ERR_CE_ACTIVITY_OUTSIDE_CYCLE` (422); (66) a new call slot does not overlap another live slot of the same perfusionist, else `ERR_ROTATION_SLOT_OVERLAP` (409); (67) a covering call slot exists for the assignment being made, else `ERR_NO_COVERING_CALL_SLOT` (422); (68) neither machine is held by a colliding case under the turnaround rule at pack configuration, else `ERR_DEVICE_TURNAROUND_CONFLICT` (409); (69) the incoming perfusionist is within concurrency limits for the case window at assignment, else `ERR_PERFUSIONIST_CONCURRENT_CASE_LIMIT` (409); (70) the contract's coverage posture admits a newly scheduled case, else `ERR_CONTRACT_COVERAGE_INSUFFICIENT` (409); (71) a settlement period is well-formed, not in the future and strictly later than the last settled period, else `ERR_SETTLEMENT_PERIOD_INVALID` (422).
    PRD 3.4: The planned window must be well-formed, with `scheduled_end` strictly after `scheduled_start`, and it must not begin in the past: `scheduled_start` must be at or after the logical clock as it reads when the case is created, or the request is `ERR_CASE_START_IN_PAST`.
    PRD 2.5: Before that capability has ever been called, the clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to the host's real time.
    PRD 2.5: The clock never runs backwards: a requested instant earlier than the current reading is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), while a request that names the current reading exactly is accepted and is a no-op with respect to the clock value itself.

    Design: Corner/validations/temporal_guards_reject_inverted_windows_past_starts_and_a_backward_clock
    """
    env = base_setup(with_case=False)
    contract_id = env["contract"]["id"]

    validate_error(
        api_client.create_bypass_case(
            build_bypass_case(
                contract_id,
                env["surgeon"]["id"],
                scheduled_start="2026-07-31T12:00:00Z",
                scheduled_end="2026-07-31T12:00:00Z",
            ),
            env["chief_headers"],
        ),
        ERR_INVALID_TIME_WINDOW,
        422,
    )
    validate_error(
        api_client.create_bypass_case(
            build_bypass_case(
                contract_id,
                env["surgeon"]["id"],
                scheduled_start="2026-07-31T23:00:00Z",
                scheduled_end="2026-08-01T05:00:00Z",
            ),
            env["chief_headers"],
        ),
        ERR_CASE_START_IN_PAST,
        422,
    )
    validate_error(
        api_client.create_certification(
            env["p1"]["id"],
            build_certification(
                cert_code="CES_A",
                issued_on="2026-02-01T00:00:00Z",
                expires_on="2026-02-01T00:00:00Z",
                cycle_credit_requirement=30,
            ),
            ADMIN_HEADERS,
        ),
        ERR_INVALID_TIME_WINDOW,
        422,
    )

    validate_success(api_client.set_clock(build_clock(INITIAL_CLOCK), ADMIN_HEADERS), 200)
    validate_error(
        api_client.set_clock(build_clock("2026-07-31T23:59:59Z"), ADMIN_HEADERS),
        ERR_CLOCK_NOT_MONOTONIC,
        422,
    )

    edge = create_case(
        contract_id,
        env["surgeon"]["id"],
        chief_id=env["chief"]["id"],
        scheduled_start=INITIAL_CLOCK,
        scheduled_end="2026-08-01T06:00:00Z",
    )
    assert edge["scheduled_start"] == INITIAL_CLOCK
    assert_case_dimensions(edge, "SCHEDULED", "UNBILLED")
    _, meta = validate_paginated(api_client.list_certifications(env["p1"]["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 1


def test_rotation_slot_creation_gates_on_employment_and_only_ecmo_slots_on_privilege():
    """Employment is checked for every slot, while the privilege rule applies only to ECMO_RELIEF.

    PRD 3.3: A window whose `window_end` is not strictly after its `window_start` is refused with `ERR_INVALID_TIME_WINDOW`; a slot whose named perfusionist is not in `ACTIVE` employment is refused with `ERR_PERFUSIONIST_NOT_ACTIVE`; and an `ECMO_RELIEF` slot whose holder does not carry `ecmo_privileged` is refused with `ERR_ECMO_PRIVILEGE_REQUIRED`, because a relief slot that cannot legally take a handoff is worse than no slot at all.
    PRD 3.3: The three rotation roles are `PRIMARY_CALL`, `BACKUP_CALL` and `ECMO_RELIEF`.
    PRD 3.3: Failing that, the contract is `THIN` when primary-call coverage reaches at least half the horizon, again 2160 minutes or more.
    PRD 3.1: Perfusionists are onboarded with `full_name` under the same 120-character limit, a group `employee_code` unique across every perfusionist, and four optional attributes: `employment_status`, one of `ACTIVE`, `LEAVE` or `TERMINATED` and defaulting to `ACTIVE`; `is_chief`, defaulting to false, which is what permits that person to act in the chief capacity; `ecmo_privileged`, defaulting to false, which is what permits them to staff extracorporeal support; and `career_case_count`, defaulting to 0 and never negative, seeded at onboarding from the HR record because a perfusionist joining the group with years of experience should not be treated as a novice by the readiness score.

    Design: Corner/validations/rotation_slot_creation_gates_on_employment_and_only_ecmo_slots_on_privilege
    """
    contract = create_contract()
    on_leave = create_perfusionist(
        full_name="Nell Okoro",
        employee_code="EMP-1011",
        employment_status="LEAVE",
        career_case_count=90,
    )
    plain = create_perfusionist(
        full_name="Tomas Aleksy",
        employee_code="EMP-1012",
        ecmo_privileged=None,
        career_case_count=90,
    )
    privileged = create_perfusionist(
        full_name="Suri Vanterpool", employee_code="EMP-1013", career_case_count=90
    )
    assert plain["ecmo_privileged"] is False
    assert privileged["ecmo_privileged"] is True

    validate_error(
        api_client.create_call_rotation_slot(
            build_call_rotation_slot(contract["id"], on_leave["id"]), ADMIN_HEADERS
        ),
        ERR_PERFUSIONIST_NOT_ACTIVE,
        422,
    )
    validate_error(
        api_client.create_call_rotation_slot(
            build_call_rotation_slot(contract["id"], plain["id"], slot_type="ECMO_RELIEF"),
            ADMIN_HEADERS,
        ),
        ERR_ECMO_PRIVILEGE_REQUIRED,
        422,
    )

    primary = create_slot(contract["id"], plain["id"])
    assert primary["status"] == "SCHEDULED"
    assert primary["slot_type"] == "PRIMARY_CALL"
    assert primary["consumed"] is False
    assert read_contract(contract["id"])["coverage_posture"] == "THIN"

    relief = create_slot(contract["id"], privileged["id"], slot_type="ECMO_RELIEF")
    assert relief["slot_type"] == "ECMO_RELIEF"
    assert relief["status"] == "SCHEDULED"
    assert relief["consumed"] is False
    _, meta = validate_paginated(api_client.list_call_rotation_slots(ADMIN_HEADERS))
    assert meta["total_count"] == 2


def test_a_breached_ecmo_run_blocks_the_same_perfusionist_from_staffing_another():
    """The staffing-breach guard is an aggregate over the actor's other open runs.

    PRD 3.8: That perfusionist must additionally hold `ecmo_privileged` true, else `ERR_ECMO_PRIVILEGE_REQUIRED`, and must not already be staffing another run that has gone into staffing breach: if any other run whose `status` is `RUNNING` or `RELIEF_PENDING` and whose `staffing_breach` reads true names them, the new run is refused with `ERR_ECMO_STAFFING_BREACH`.
    PRD 3.8: `uninterrupted_minutes` measures how long the perfusionist currently at the console has been there without relief, not how long the run has been open.
    PRD 3.8: At 600 minutes of uninterrupted staffing a run in `RUNNING` moves `RUNNING → RELIEF_PENDING` — the system is asking for a relief perfusionist, and the transition is performed by the clock advance itself, not by any operator.
    PRD 3.8: At 720 minutes `staffing_breach` becomes true, which is the flag that blocks the perfusionist from taking on further runs.
    PRD 3.8: Everything else is derived: `status` initialises to `RUNNING`, `primary_perfusionist_id` to the case's `assigned_perfusionist_id`, `cannulated_at` to the logical clock, `last_handoff_at` to null, `relief_slot_id` to null, `uninterrupted_minutes` to 0, `staffing_breach` to false, `billable_hours` to 0 and `ecmo_fee_cents` to 0.

    Design: Corner/validations/a_breached_ecmo_run_blocks_the_same_perfusionist_from_staffing_another
    """
    env = on_bypass_setup()
    case_id = env["case"]["id"]
    p1_id = env["p1"]["id"]
    run = create_ecmo_run(case_id, p1_id, "VA")
    assert run["status"] == "RUNNING"
    assert run["staffing_breach"] is False
    assert run["cannulated_at"] == INITIAL_CLOCK

    set_clock("2026-08-01T12:00:00Z")
    breached = read_ecmo_run(run["id"])
    assert breached["status"] == "RELIEF_PENDING"
    assert abs(float(breached["uninterrupted_minutes"]) - 720) < 1e-9
    assert breached["staffing_breach"] is True

    validate_error(
        api_client.create_ecmo_run(case_id, {"mode": "VV"}, env["p1_headers"]),
        ERR_ECMO_STAFFING_BREACH,
        409,
    )
    runs, meta = validate_paginated(api_client.list_ecmo_runs(ADMIN_HEADERS))
    assert meta["total_count"] == 1
    assert len(runs) == 1
    only = read_ecmo_run(run["id"])
    assert only["primary_perfusionist_id"] == p1_id
    assert_fields_null(only, ["relief_slot_id", "decannulated_at"])
    assert_cents(only["ecmo_fee_cents"], 0, "ecmo_fee_cents")
    assert read_case(case_id)["bypass_status"] == "ON_BYPASS"


def test_pack_config_rejects_a_service_overdue_primary_machine_until_serviced():
    """The service guard reads the runtime counter against the machine's own interval, not its status.

    PRD 3.5: Its service posture must be current: `runtime_hours_since_service` strictly below `service_interval_hours`, else `ERR_DEVICE_SERVICE_OVERDUE`.
    PRD 3.7: A `RUNTIME_TICK` adds its `runtime_hours_delta` to the machine's `runtime_hours_since_service`; for every other code the delta is ignored even when supplied.
    PRD 3.7: An `ALARM_CRITICAL`, an `ALARM_ADVISORY` or a `SELF_TEST_FAIL` raises the machine's `alarm_count_since_service` by one.
    PRD 3.7: And an `ALARM_CRITICAL` or a `SELF_TEST_FAIL` drives the machine to `NEEDS_SERVICE` from whichever of `AVAILABLE`, `RESERVED` or `IN_USE` it was in — which in turn fires a four-link cascade across the cases that were counting on it.
    PRD 3.7: The completion moves the machine `NEEDS_SERVICE → AVAILABLE`, resets both `alarm_count_since_service` and `runtime_hours_since_service` to 0, stamps `last_service_completed_at` with the logical clock, appends an event log carrying `event_code` `SERVICE_COMPLETED`, and advances the machine's `version`.
    PRD 3.5: The pack's `pack_cost_cents` is the exact sum of those already-rounded line totals — never the rounding of an unrounded sum, as §2.6 insists.

    Design: Corner/validations/pack_config_rejects_a_service_overdue_primary_machine_until_serviced
    """
    env = staffed_setup()
    case_id = env["case"]["id"]
    loaner = add_device(
        env,
        "d5",
        asset_tag="HLM-005",
        backup_device_id=env["d2"]["id"],
        service_interval_hours=2,
    )
    capture_device_event(
        loaner["id"],
        "RUNTIME_TICK",
        runtime_hours_delta=3,
        detail="loaner returned with 3 hours on the pump",
    )
    assert_device_state(read_device(loaner["id"]), "AVAILABLE", 0, 0, 3)

    validate_error(
        api_client.configure_disposable_pack(
            case_id, build_pack_configuration(loaner["id"]), env["p1_headers"]
        ),
        ERR_DEVICE_SERVICE_OVERDUE,
        422,
    )
    assert read_case(case_id)["bypass_status"] == "STAFFED"
    assert_device_state(read_device(loaner["id"]), "AVAILABLE", 0)

    capture_device_event(loaner["id"], "SELF_TEST_FAIL", detail="pulled for preventive service")
    assert_device_state(read_device(loaner["id"]), "NEEDS_SERVICE", 0, 1)

    serviced = complete_device_service(loaner["id"], detail="500-hour service completed")
    assert_device_state(serviced, "AVAILABLE", 0, 0, 0)
    assert serviced["last_service_completed_at"] == INITIAL_CLOCK
    logs, meta = validate_paginated(
        api_client.list_device_event_logs(loaner["id"], env["tech_headers"])
    )
    assert meta["total_count"] == 3
    assert_created_at_ascending(logs)
    assert [log["event_code"] for log in logs] == [
        "RUNTIME_TICK",
        "SELF_TEST_FAIL",
        "SERVICE_COMPLETED",
    ]

    pack = configure_pack(case_id, loaner["id"], env["p1"]["id"])
    assert_cents(pack["pack_cost_cents"], 3741, "pack_cost_cents")
    assert pack["approval_status"] == "NOT_REQUIRED"
    case = read_case(case_id)
    assert case["bypass_status"] == "PACK_CONFIGURED"
    assert case["primary_device_id"] == loaner["id"]
    assert case["backup_device_id"] == env["d2"]["id"]
    assert_device_state(read_device(loaner["id"]), "RESERVED", 1)
    assert_device_state(read_device(env["d2"]["id"]), "RESERVED", 1)


def test_incident_submission_waits_for_the_case_and_end_bypass_checks_its_own_inputs():
    """Both guards are shown failing and then passing on the same fixture, with nothing left mutated.

    PRD 3.9: The referenced case must have come off the pump: its `bypass_status` must be `OFF_BYPASS` or `CLOSED`, else `ERR_INCIDENT_CASE_NOT_COMPLETE`.
    PRD 3.9: Submission moves the report to `SUBMITTED` and does nothing else but advance its `version`.
    PRD 3.9: The report opens in `DRAFT` with `filed_by_perfusionist_id` taken from the acting header, `return_count` 0, `finding` `NONE`, `corrective_action_required` false, `reviewed_readiness_score` null and `closed_by_perfusionist_id` null.
    PRD 3.6: The assigned perfusionist reports `pump_time_minutes`, the actual minutes on pump, which must be between 0 and 2880 inclusive — no single run may be recorded as longer than 48 hours; `cross_clamp_minutes`, the actual aortic cross-clamp minutes, which must be between 0 and the reported pump time inclusive, a longer cross-clamp than pump time being refused with `ERR_CROSS_CLAMP_EXCEEDS_PUMP_TIME`; `lowest_hematocrit_pct`, the lowest on-pump hematocrit percentage, again within 5 to 45; and optionally `adverse_event_count`, which defaults to 0 and is never negative.
    PRD 3.6: The case moves `ON_BYPASS → OFF_BYPASS`, `bypass_ended_at` is set to the logical clock, and all four reported quality figures are stored.
    PRD 3.6: The fiscal dimension is deliberately untouched: a case that has come off pump still reads `PROVISIONAL_ACCRUED`, because coming off pump is a clinical event and settlement is a fiscal one.

    Design: Corner/validations/incident_submission_waits_for_the_case_and_end_bypass_checks_its_own_inputs
    """
    env = on_bypass_setup()
    case_id = env["case"]["id"]
    p1_id = env["p1"]["id"]
    report = create_incident_report(
        case_id,
        p1_id,
        p1_id,
        category="GAS_EXCHANGE",
        narrative="sweep gas line kinked for two minutes",
    )
    assert report["status"] == "DRAFT"

    validate_error(
        api_client.submit_incident_report(report["id"], make_perfusionist_headers(p1_id)),
        ERR_INCIDENT_CASE_NOT_COMPLETE,
        409,
    )
    still_draft = read_incident_report(report["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["filed_by_perfusionist_id"] == p1_id
    assert_fields_null(still_draft, ["reviewed_readiness_score"])

    validate_error(
        api_client.end_bypass(
            case_id,
            build_end_bypass(pump_time_minutes=150, cross_clamp_minutes=200),
            env["p1_headers"],
        ),
        ERR_CROSS_CLAMP_EXCEEDS_PUMP_TIME,
        422,
    )
    on_pump = read_case(case_id)
    assert_case_dimensions(on_pump, "ON_BYPASS", "PROVISIONAL_ACCRUED")
    assert_fields_null(on_pump, ["pump_time_minutes"])

    off_pump = end_bypass(case_id, p1_id, pump_time_minutes=150, cross_clamp_minutes=90)
    assert_case_dimensions(off_pump, "OFF_BYPASS", "PROVISIONAL_ACCRUED")
    assert off_pump["pump_time_minutes"] == 150
    assert off_pump["cross_clamp_minutes"] == 90
    assert off_pump["bypass_ended_at"] == INITIAL_CLOCK
    assert_cents(off_pump["provisional_fee_cents"], 400000, "provisional_fee_cents")
    assert_fields_null(off_pump, ["final_fee_cents"])

    submitted = submit_incident_report(report["id"], p1_id)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["return_count"] == 0
