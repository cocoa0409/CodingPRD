"""Endpoint behaviour: the forward-only rate update, the event-log action, the handoff link and computed reads."""
from test_helpers import (
    ADMIN_HEADERS,
    INITIAL_CLOCK,
    add_perfusionist,
    add_slot,
    api_client,
    add_case,
    assert_case_dimensions,
    assert_cents,
    assert_contract_ledger,
    assert_device_state,
    assert_event_log_fields,
    assert_fields_null,
    assert_line_codes_ascending,
    assert_pack_line,
    assert_pagination_meta,
    assign_perfusionist,
    build_contract_update,
    capture_device_event,
    create_contract,
    create_device,
    create_ecmo_run,
    handoff_ecmo_run,
    make_biomed_tech_headers,
    make_perfusionist_headers,
    on_bypass_setup,
    pack_configured_setup,
    read_case,
    read_contract,
    read_device,
    read_ecmo_run,
    read_pack,
    read_slot,
    set_clock,
    staffed_setup,
    validate_paginated,
    validate_success,
)


def test_contract_rate_update_applies_forward_only_and_never_reprices_accruals():
    """A rate change writes the new terms and prices the next case, leaving the existing accrual alone.

    PRD 3.1: Commercial terms change over the life of a contract, and the update operation accepts any subset of the ten terms above alongside the mandatory `expected_contract_version` described in §2.7.
    PRD 3.1: It never retro-prices work already done: `accrued_case_fee_cents` is untouched by a rate change, and every case that already carries an accrual keeps the amount computed under the rates in force when it accrued.
    PRD 3.1: And it advances the contract's `version` by one, which means a second client holding the pre-update version can no longer update — nor can it assign a perfusionist against a case whose accrual cascade has since moved that version.
    PRD 3.4: On success from `SCHEDULED`, the case moves `SCHEDULED → STAFFED`: `assigned_perfusionist_id` is set to the named perfusionist, the provisional fee is computed and written to `provisional_fee_cents`, the fiscal dimension moves `UNBILLED → PROVISIONAL_ACCRUED`, `accrued_fee_cents` is set to the provisional amount, and the contract absorbs it — `accrued_case_fee_cents` rises by that amount, `accrued_case_count` rises by one, and the contract's `updated_at` and `version` advance.

    Design: Corner/endpoints/contract_rate_update_applies_forward_only_and_never_reprices_accruals
    """
    env = staffed_setup()
    contract_id = env["contract"]["id"]
    assert_cents(env["case"]["provisional_fee_cents"], 400000, "provisional_fee_cents")
    before = read_contract(contract_id)
    assert_contract_ledger(before, 400000, 1)

    updated = validate_success(
        api_client.update_hospital_contract(
            contract_id,
            build_contract_update(
                before["version"],
                per_case_fee_cents=500000,
                prolonged_pump_threshold_minutes=120,
                monthly_case_cap=6,
            ),
            ADMIN_HEADERS,
        ),
        200,
    )
    assert_cents(updated["per_case_fee_cents"], 500000, "per_case_fee_cents")
    assert updated["prolonged_pump_threshold_minutes"] == 120
    assert updated["monthly_case_cap"] == 6
    assert updated["hospital_name"] == "St Aldate Cardiac Center"
    assert updated["version"] == before["version"] + 1
    assert_contract_ledger(updated, 400000, 1)
    assert_cents(
        read_case(env["case"]["id"])["provisional_fee_cents"], 400000, "provisional_fee_cents"
    )

    later = add_case(
        env,
        "case_b",
        scheduled_start="2026-08-02T13:31:00Z",
        scheduled_end="2026-08-02T19:31:00Z",
    )
    later = assign_perfusionist(
        later["id"], env["p1"]["id"], later["version"], env["chief"]["id"]
    )
    assert_case_dimensions(later, "STAFFED", "PROVISIONAL_ACCRUED")
    # The provisional variant takes its minutes from the card's 150
    # standard_pump_minutes, which now sits above the updated 120-minute
    # threshold: FLOOR((150 - 120) / 30) + 1 is 2 units, so the fee is
    # 500000 * (1 + 2 * 0.15) = 650000.
    assert_cents(later["provisional_fee_cents"], 650000, "provisional_fee_cents")
    assert_cents(later["accrued_fee_cents"], 650000, "accrued_fee_cents")
    assert_contract_ledger(read_contract(contract_id), 1050000, 2)


def test_device_event_log_action_ticks_runtime_and_counts_only_alarm_codes():
    """The runtime delta is honoured only for a tick, and only three codes raise the alarm counter.

    PRD 3.7: An event names its `event_code` — one of `ALARM_CRITICAL`, `ALARM_ADVISORY`, `RUNTIME_TICK`, `SELF_TEST_PASS`, `SELF_TEST_FAIL` or `SERVICE_COMPLETED` — and may carry `runtime_hours_delta`, a figure between 0 and 24 inclusive defaulting to 0, and `detail`, a free-text note of at most 400 characters.
    PRD 3.7: The server stores the event against its `device_id` and records the acting header value verbatim as `recorded_by_user_id`, without resolving it against any table, precisely because both opaque and entity-backed roles may capture events.
    PRD 3.7: A `RUNTIME_TICK` adds its `runtime_hours_delta` to the machine's `runtime_hours_since_service`; for every other code the delta is ignored even when supplied.
    PRD 3.7: An `ALARM_CRITICAL`, an `ALARM_ADVISORY` or a `SELF_TEST_FAIL` raises the machine's `alarm_count_since_service` by one.
    PRD 3.7: And an `ALARM_CRITICAL` or a `SELF_TEST_FAIL` drives the machine to `NEEDS_SERVICE` from whichever of `AVAILABLE`, `RESERVED` or `IN_USE` it was in — which in turn fires a four-link cascade across the cases that were counting on it.

    Design: Corner/endpoints/device_event_log_action_ticks_runtime_and_counts_only_alarm_codes
    """
    contract = create_contract()
    standby = create_device(contract["id"], asset_tag="HLM-002")
    machine = create_device(
        contract["id"], asset_tag="HLM-001", backup_device_id=standby["id"]
    )
    assert_device_state(machine, "AVAILABLE", 0, 0, 0)

    tick = capture_device_event(
        machine["id"], "RUNTIME_TICK", runtime_hours_delta=4, detail="post-case runtime"
    )
    self_test = capture_device_event(
        machine["id"],
        "SELF_TEST_PASS",
        headers=make_biomed_tech_headers("tech-audit-7"),
        detail="morning self test",
    )
    advisory = capture_device_event(
        machine["id"], "ALARM_ADVISORY", runtime_hours_delta=5, detail="gas blender advisory"
    )
    assert tick["event_code"] == "RUNTIME_TICK"
    assert self_test["event_code"] == "SELF_TEST_PASS"
    assert advisory["event_code"] == "ALARM_ADVISORY"
    for event in (tick, self_test, advisory):
        assert_event_log_fields(event)
        assert event["device_id"] == machine["id"]
    assert self_test["recorded_by_user_id"] == "tech-audit-7"

    assert_device_state(read_device(machine["id"]), "AVAILABLE", 0, 1, 4)

    logs, meta = validate_paginated(
        api_client.list_device_event_logs(machine["id"], make_biomed_tech_headers())
    )
    assert_pagination_meta(meta, total_count=3, has_more=False)
    assert [log["event_code"] for log in logs] == [
        "RUNTIME_TICK",
        "SELF_TEST_PASS",
        "ALARM_ADVISORY",
    ]


def test_ecmo_handoff_links_the_run_to_a_relief_slot_and_swaps_the_staffing():
    """The handoff writes both sides of the run-to-slot association and restarts the relief clock.

    PRD 3.8: A relief handoff is a chief's act and it closes the staffing cycle.
    PRD 3.8: The run must be in `RELIEF_PENDING`, else `ERR_ECMO_RUN_STATE_INVALID` — a run only 400 minutes into its shift cannot be handed over early.
    PRD 3.8: The handoff moves the run `RELIEF_PENDING → RUNNING`, sets `primary_perfusionist_id` to the relief slot's `perfusionist_id`, stores the slot's identifier in the run's `relief_slot_id`, stamps `last_handoff_at` with the logical clock, resets `uninterrupted_minutes` to 0 and re-derives `staffing_breach` as false.
    PRD 3.8: The named slot moves `SCHEDULED → ACTIVE` with `consumed` set true, which both removes it from the pool of slots available to satisfy another handoff and keeps it out of a bypass case's coverage arithmetic.
    PRD 3.8: Both the run's and the slot's `version` advance.
    PRD 3.8: At 600 minutes of uninterrupted staffing a run in `RUNNING` moves `RUNNING → RELIEF_PENDING` — the system is asking for a relief perfusionist, and the transition is performed by the clock advance itself, not by any operator.

    Design: Corner/endpoints/ecmo_handoff_links_the_run_to_a_relief_slot_and_swaps_the_staffing
    """
    env = on_bypass_setup()
    case_id = env["case"]["id"]
    relief_holder = add_perfusionist(
        env, "p6", full_name="Ines Kowalczyk", employee_code="EMP-1006", career_case_count=120
    )
    relief_slot = add_slot(
        env,
        relief_holder["id"],
        key="slot6",
        slot_type="ECMO_RELIEF",
        window_start=INITIAL_CLOCK,
        window_end="2026-08-02T00:00:00Z",
    )
    run = create_ecmo_run(case_id, env["p1"]["id"], "VA")
    set_clock("2026-08-01T10:00:00Z")

    pending = read_ecmo_run(run["id"])
    assert pending["status"] == "RELIEF_PENDING"
    assert abs(float(pending["uninterrupted_minutes"]) - 600) < 1e-9
    assert pending["staffing_breach"] is False
    assert pending["primary_perfusionist_id"] == env["p1"]["id"]

    handed = handoff_ecmo_run(run["id"], relief_slot["id"], env["chief"]["id"])
    assert handed["status"] == "RUNNING"
    assert handed["primary_perfusionist_id"] == relief_holder["id"]
    assert handed["relief_slot_id"] == relief_slot["id"]
    assert handed["last_handoff_at"] == "2026-08-01T10:00:00Z"
    assert abs(float(handed["uninterrupted_minutes"]) - 0) < 1e-9
    assert handed["staffing_breach"] is False
    assert handed["cannulated_at"] == INITIAL_CLOCK

    consumed = read_slot(relief_slot["id"])
    assert consumed["status"] == "ACTIVE"
    assert consumed["consumed"] is True
    assert consumed["version"] == relief_slot["version"] + 1
    assert read_slot(env["slot_p1"]["id"])["status"] == "ACTIVE"
    assert read_case(case_id)["bypass_status"] == "ON_BYPASS"


def test_pack_read_returns_materialised_lines_and_the_case_read_returns_its_fees():
    """The pack read exposes each already-rounded line in code order, and the case read its fees.

    PRD 3.5: It records `case_id`, pins the selected card as `applied_preference_card_id`, and copies the card's `prime_volume_ml` verbatim onto itself.
    PRD 3.5: The materialised lines are then ordered by `line_code` ascending, which for a substituted line means ordering by the replacement code.
    PRD 3.5: For each materialised line, the gross value is its `quantity` multiplied by its `unit_cost_cents`; the discounted value is that gross multiplied by one minus the contract's `disposable_discount_pct`; the marked-up value is the discounted value multiplied by one plus the contract's `disposable_markup_pct`; and the line's `line_total_cents` is that marked-up value rounded half up to a whole number of cents.
    PRD 3.5: The pack's `pack_cost_cents` is the exact sum of those already-rounded line totals — never the rounding of an unrounded sum, as §2.6 insists.
    PRD 3.5: A pack whose `substitutions` array is non-empty has `requires_surgeon_approval` set true and `approval_status` set to `PENDING`; a pack with no substitutions has `requires_surgeon_approval` false and `approval_status` `NOT_REQUIRED`, and needs no further human act.

    Design: Corner/endpoints/pack_read_returns_materialised_lines_and_the_case_read_returns_its_fees
    """
    env = pack_configured_setup()
    actor = make_perfusionist_headers(env["p1"]["id"])
    pack = read_pack(env["pack"]["id"], actor)
    assert pack["case_id"] == env["case"]["id"]
    assert pack["applied_preference_card_id"] == env["card"]["id"]
    assert pack["prime_volume_ml"] == 1500

    lines = pack["line_items"]
    assert len(lines) == 3
    assert_line_codes_ascending(lines)
    assert_pack_line(lines[0], "A_OXYGENATOR", 1, 1055, 1139, False)
    assert_pack_line(lines[1], "B_TUBING_PACK", 1, 1155, 1247, False)
    assert_pack_line(lines[2], "C_CANNULA_SET", 1, 1255, 1355, False)
    assert_cents(pack["pack_cost_cents"], 1139 + 1247 + 1355, "pack_cost_cents")
    assert_cents(pack["pack_cost_cents"], 3741, "pack_cost_cents")
    assert pack["approval_status"] == "NOT_REQUIRED"
    assert pack["requires_surgeon_approval"] is False

    case = read_case(env["case"]["id"], actor)
    assert_case_dimensions(case, "PACK_CONFIGURED", "PROVISIONAL_ACCRUED")
    assert_cents(case["provisional_fee_cents"], 400000, "provisional_fee_cents")
    assert_cents(case["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert_fields_null(case, ["final_fee_cents"])
    assert case["readiness_flag"] == "NONE"
    assert case["primary_device_id"] == env["d1"]["id"]
    assert case["backup_device_id"] == env["d2"]["id"]
