"""Two cross-entity state dependencies and three flavours of resource overlap."""
from test_helpers import (
    add_case,
    add_perfusionist,
    add_slot,
    ADMIN_HEADERS,
    api_client,
    assert_case_dimensions,
    assert_cents,
    assert_contract_ledger,
    assert_created_at_ascending,
    assert_device_state,
    assert_error_envelope,
    assert_readiness_score,
    assign_perfusionist,
    base_setup,
    build_assignment,
    build_call_rotation_slot,
    build_ecmo_handoff,
    build_pack_configuration,
    capture_device_event,
    complete_device_service,
    configure_pack,
    create_ce_activity,
    create_certification,
    create_contract,
    create_ecmo_run,
    create_perfusionist,
    create_slot,
    handoff_ecmo_run,
    INITIAL_CLOCK,
    on_bypass_setup,
    read_case,
    read_contract,
    read_device,
    read_ecmo_run,
    read_perfusionist,
    read_slot,
    set_clock,
    staffed_setup,
    validate_error,
    validate_paginated,
    validate_success,
)

RELIEF_WINDOW_END = "2026-08-02T00:00:00Z"
FIRST_RELIEF_INSTANT = "2026-08-01T10:00:00Z"
SECOND_RELIEF_INSTANT = "2026-08-01T20:00:00Z"


def _relief_pending_run():
    """Drive one case on pump, open a VA run, and let the clock ask for relief.

    p2 holds an `ECMO_RELIEF` window rather than backup call, so the contract's
    posture is THIN while the run's relief pool holds exactly one slot.
    """
    env = on_bypass_setup()
    add_perfusionist(env, "p2", full_name="Ines Kowalczyk", employee_code="EMP-1006")
    add_slot(
        env,
        env["p2"]["id"],
        key="slot_relief",
        slot_type="ECMO_RELIEF",
        window_start=INITIAL_CLOCK,
        window_end=RELIEF_WINDOW_END,
    )
    env["run"] = create_ecmo_run(env["case"]["id"], env["p1"]["id"], "VA")
    env["clock_report"] = set_clock(FIRST_RELIEF_INSTANT)
    return env


def test_a_handoff_is_refused_when_the_named_slot_is_not_a_scheduled_relief_row():
    """The run is in the right state both times; only the foreign slot row decides.

    PRD 3.8: At 600 minutes of uninterrupted staffing a run in `RUNNING` moves `RUNNING → RELIEF_PENDING` — the system is asking for a relief perfusionist, and the transition is performed by the clock advance itself, not by any operator.
    PRD 3.8: Both figures are recomputed for every open run on every clock advance, and the count of runs that have entered `RELIEF_PENDING` is reported back in the clock response as `relief_pending_run_count`.
    PRD 3.8: The chief names a `relief_slot_id`, and that slot must satisfy every one of five conditions or the request is refused with `ERR_RELIEF_SLOT_INVALID`: its `slot_type` must be `ECMO_RELIEF`, its `consumed` must still be false, its `contract_id` must equal the contract of the run's parent case, the logical clock must fall inside the half-open interval from its `window_start` to its `window_end`, and its `perfusionist_id` must differ from the run's current `primary_perfusionist_id` — a perfusionist cannot relieve themselves.
    PRD 3.3: Slots in `COMPLETED` or `RELEASED`, and every `ECMO_RELIEF` slot regardless of status, are excluded from the whole computation, and a slot that started before the clock contributes only its remaining minutes.

    Design: Difficulty/cross_entity_state_dependency/ecmo_handoff_requires_relief_slot_in_scheduled_ecmo_relief_state
    """
    env = _relief_pending_run()
    run_id = env["run"]["id"]
    assert env["clock_report"]["relief_pending_run_count"] == 1, (
        "the clock advance itself performs the transition and counts it back"
    )
    assert read_contract(env["contract"]["id"])["coverage_posture"] == "THIN", (
        "an ECMO_RELIEF window is excluded from the coverage arithmetic entirely"
    )

    pending = read_ecmo_run(run_id)
    assert pending["status"] == "RELIEF_PENDING"
    assert abs(float(pending["uninterrupted_minutes"]) - 600) < 1e-9
    assert pending["staffing_breach"] is False
    assert pending["relief_slot_id"] is None
    assert pending["last_handoff_at"] is None

    wrong_row = api_client.handoff_ecmo_run(
        run_id,
        build_ecmo_handoff(env["slot_p1"]["id"]),
        env["chief_headers"],
    )
    validate_error(wrong_row, "ERR_RELIEF_SLOT_INVALID", 422)
    assert_error_envelope(wrong_row, "ERR_RELIEF_SLOT_INVALID")

    unmoved = read_ecmo_run(run_id)
    assert unmoved["status"] == "RELIEF_PENDING", "the run's own state was never the problem"
    assert unmoved["primary_perfusionist_id"] == env["p1"]["id"]
    assert unmoved["relief_slot_id"] is None
    assert unmoved["version"] == pending["version"]

    untouched = read_slot(env["slot_p1"]["id"])
    assert untouched["consumed"] is False, "a refused handoff consumes nothing"
    assert read_slot(env["slot_relief"]["id"])["status"] == "SCHEDULED"


def test_the_relief_slot_serves_exactly_one_handoff_and_is_then_out_of_the_pool():
    """A `SCHEDULED` relief row hands the console over; the same row, now consumed, cannot.

    PRD 3.8: The chief names a `relief_slot_id`, and that slot must satisfy every one of five conditions or the request is refused with `ERR_RELIEF_SLOT_INVALID`: its `slot_type` must be `ECMO_RELIEF`, its `consumed` must still be false, its `contract_id` must equal the contract of the run's parent case, the logical clock must fall inside the half-open interval from its `window_start` to its `window_end`, and its `perfusionist_id` must differ from the run's current `primary_perfusionist_id` — a perfusionist cannot relieve themselves.
    PRD 3.8: The handoff moves the run `RELIEF_PENDING → RUNNING`, sets `primary_perfusionist_id` to the relief slot's `perfusionist_id`, stores the slot's identifier in the run's `relief_slot_id`, stamps `last_handoff_at` with the logical clock, resets `uninterrupted_minutes` to 0 and re-derives `staffing_breach` as false.
    PRD 3.8: The named slot moves `SCHEDULED → ACTIVE` with `consumed` set true, which both removes it from the pool of slots available to satisfy another handoff and keeps it out of a bypass case's coverage arithmetic.
    PRD 3.8: It is the number of minutes between the later of `last_handoff_at` and `cannulated_at` — `cannulated_at` before the first handoff — and the logical clock while the run is open, or between that same starting instant and `decannulated_at` once the run is closed.
    PRD 3.8: At 600 minutes of uninterrupted staffing a run in `RUNNING` moves `RUNNING → RELIEF_PENDING` — the system is asking for a relief perfusionist, and the transition is performed by the clock advance itself, not by any operator.

    Design: Difficulty/cross_entity_state_dependency/ecmo_handoff_requires_relief_slot_in_scheduled_ecmo_relief_state
    """
    env = _relief_pending_run()
    run_id = env["run"]["id"]
    slot_before = env["slot_relief"]

    handed = handoff_ecmo_run(run_id, slot_before["id"], env["chief"]["id"])
    assert handed["status"] == "RUNNING"
    assert handed["primary_perfusionist_id"] == env["p2"]["id"]
    assert handed["relief_slot_id"] == slot_before["id"]
    assert handed["last_handoff_at"] == FIRST_RELIEF_INSTANT
    assert abs(float(handed["uninterrupted_minutes"]) - 0) < 1e-9
    assert handed["staffing_breach"] is False

    consumed = read_slot(slot_before["id"])
    assert consumed["status"] == "ACTIVE"
    assert consumed["consumed"] is True
    assert consumed["version"] == slot_before["version"] + 1

    second_cycle = set_clock(SECOND_RELIEF_INSTANT)
    assert second_cycle["relief_pending_run_count"] == 1
    again = read_ecmo_run(run_id)
    assert again["status"] == "RELIEF_PENDING", (
        "600 minutes of uninterrupted staffing counts from the handoff, not from cannulation"
    )
    assert abs(float(again["uninterrupted_minutes"]) - 600) < 1e-9

    reuse = api_client.handoff_ecmo_run(
        run_id, build_ecmo_handoff(slot_before["id"]), env["chief_headers"]
    )
    validate_error(reuse, "ERR_RELIEF_SLOT_INVALID", 422)
    still_running_p2 = read_ecmo_run(run_id)
    assert still_running_p2["status"] == "RELIEF_PENDING"
    assert still_running_p2["primary_perfusionist_id"] == env["p2"]["id"]
    assert still_running_p2["relief_slot_id"] == slot_before["id"]


def test_a_failed_self_test_on_an_idle_pump_blocks_the_pack_configuration():
    """The case is perfectly staffed; the machine's own row is what refuses the request.

    PRD 3.7: An `ALARM_CRITICAL`, an `ALARM_ADVISORY` or a `SELF_TEST_FAIL` raises the machine's `alarm_count_since_service` by one.
    PRD 3.7: And an `ALARM_CRITICAL` or a `SELF_TEST_FAIL` drives the machine to `NEEDS_SERVICE` from whichever of `AVAILABLE`, `RESERVED` or `IN_USE` it was in — which in turn fires a four-link cascade across the cases that were counting on it.
    PRD 3.7: The second link reaches every bypass case naming that machine as its **primary** whose `bypass_status` is `PACK_CONFIGURED` or `SETUP_VERIFIED`: such a case falls back to `STAFFED`, its `setup_verified_at` is cleared to null, its `readiness_flag` is raised to `DEVICE_FALLBACK_REQUIRED`, both its `primary_device_id` and its `backup_device_id` are cleared to null, and the standby machine it was holding moves `RESERVED → AVAILABLE`.
    PRD 3.5: Its `status` must be `AVAILABLE` or `RESERVED` — a machine already reserved for a non-colliding case window is perfectly usable, whereas a machine that is `IN_USE` or `NEEDS_SERVICE` is refused with `ERR_DEVICE_NOT_AVAILABLE`.

    Design: Difficulty/cross_entity_state_dependency/pack_config_requires_primary_device_available
    """
    env = staffed_setup()
    case_id = env["case"]["id"]
    assert_device_state(read_device(env["d1"]["id"]), "AVAILABLE", open_reservation_count=0)
    assert_device_state(read_device(env["d2"]["id"]), "AVAILABLE", open_reservation_count=0)

    capture_device_event(
        env["d1"]["id"], "SELF_TEST_FAIL", detail="oxygenator pressure transducer failed self test"
    )
    failed = read_device(env["d1"]["id"])
    assert_device_state(failed, "NEEDS_SERVICE", alarm_count_since_service=1)

    held_nothing = read_case(case_id)
    assert held_nothing["bypass_status"] == "STAFFED", (
        "no case held the machine as its primary in a reserved state, so nothing was unwound"
    )
    assert held_nothing["readiness_flag"] == "NONE"

    refused = api_client.configure_disposable_pack(
        case_id, build_pack_configuration(env["d1"]["id"]), env["p1_headers"]
    )
    validate_error(refused, "ERR_DEVICE_NOT_AVAILABLE", 409)
    assert_error_envelope(refused, "ERR_DEVICE_NOT_AVAILABLE")

    _, meta = validate_paginated(
        api_client.list_disposable_packs(ADMIN_HEADERS, params={"case_id": case_id})
    )
    assert meta["total_count"] == 0, "the refused configuration materialised no pack"
    assert_device_state(read_device(env["d2"]["id"]), "AVAILABLE", open_reservation_count=0)
    assert read_case(case_id)["primary_device_id"] is None


def test_a_service_completion_restores_the_pump_and_the_identical_request_then_succeeds():
    """Only the foreign row changed between the refusal and the acceptance.

    PRD 3.7: The completion moves the machine `NEEDS_SERVICE → AVAILABLE`, resets both `alarm_count_since_service` and `runtime_hours_since_service` to 0, stamps `last_service_completed_at` with the logical clock, appends an event log carrying `event_code` `SERVICE_COMPLETED`, and advances the machine's `version`.
    PRD 3.7: Event logs are immutable and carry no `version`; they may be listed for one device filtered by `event_code`.
    PRD 3.5: Its `status` must be `AVAILABLE` or `RESERVED` — a machine already reserved for a non-colliding case window is perfectly usable, whereas a machine that is `IN_USE` or `NEEDS_SERVICE` is refused with `ERR_DEVICE_NOT_AVAILABLE`.
    PRD 3.5: Both machines end at `RESERVED`: a machine that was `AVAILABLE` moves `AVAILABLE → RESERVED`, and a machine already `RESERVED` for another non-colliding case simply stays `RESERVED` with a higher reservation count.
    PRD 3.5: For each materialised line, the gross value is its `quantity` multiplied by its `unit_cost_cents`; the discounted value is that gross multiplied by one minus the contract's `disposable_discount_pct`; the marked-up value is the discounted value multiplied by one plus the contract's `disposable_markup_pct`; and the line's `line_total_cents` is that marked-up value rounded half up to a whole number of cents.
    PRD 3.5: The pack's `pack_cost_cents` is the exact sum of those already-rounded line totals — never the rounding of an unrounded sum, as §2.6 insists.

    Design: Difficulty/cross_entity_state_dependency/pack_config_requires_primary_device_available
    """
    env = staffed_setup()
    case_id = env["case"]["id"]
    capture_device_event(
        env["d1"]["id"], "SELF_TEST_FAIL", detail="oxygenator pressure transducer failed self test"
    )
    validate_error(
        api_client.configure_disposable_pack(
            case_id, build_pack_configuration(env["d1"]["id"]), env["p1_headers"]
        ),
        "ERR_DEVICE_NOT_AVAILABLE",
        409,
    )

    serviced = complete_device_service(env["d1"]["id"], detail="transducer replaced and retested")
    assert_device_state(
        serviced,
        "AVAILABLE",
        alarm_count_since_service=0,
        runtime_hours_since_service=0,
    )
    assert serviced["last_service_completed_at"] == INITIAL_CLOCK

    logs, log_meta = validate_paginated(
        api_client.list_device_event_logs(env["d1"]["id"], env["tech_headers"])
    )
    assert log_meta["total_count"] == 2
    assert [row["event_code"] for row in logs] == ["SELF_TEST_FAIL", "SERVICE_COMPLETED"], (
        "the completion appends its own immutable row after the failure it answers"
    )
    assert_created_at_ascending(logs)

    pack = validate_success(
        api_client.configure_disposable_pack(
            case_id, build_pack_configuration(env["d1"]["id"]), env["p1_headers"]
        ),
        201,
    )
    assert_cents(pack["pack_cost_cents"], 3741, "pack_cost_cents")
    reserved = read_case(case_id)
    assert_case_dimensions(reserved, "PACK_CONFIGURED", "PROVISIONAL_ACCRUED")
    assert reserved["primary_device_id"] == env["d1"]["id"]
    assert reserved["backup_device_id"] == env["d2"]["id"]
    assert_device_state(read_device(env["d1"]["id"]), "RESERVED", open_reservation_count=1)
    assert_device_state(read_device(env["d2"]["id"]), "RESERVED", open_reservation_count=1)


HORIZON_END = "2026-08-04T00:00:00Z"


def _two_hospitals_one_holder():
    """Two unrelated hospitals, two perfusionists, and one primary-call window.

    p1's window on the first hospital spans the whole 72-hour horizon, so every
    later attempt to put p1 on call somewhere else meets that incumbent row.
    """
    env = {}
    env["c1"] = create_contract()
    env["c2"] = create_contract(
        hospital_name="Brackenridge Heart Institute",
        staffing_model="PER_CASE",
        per_case_fee_cents=380000,
        ecmo_hourly_fee_cents=85000,
        monthly_case_cap=4,
        monthly_coverage_fee_cents=None,
        prolonged_surcharge_pct=None,
        prolonged_pump_threshold_minutes=None,
        disposable_markup_pct=None,
        disposable_discount_pct=None,
    )
    env["p1"] = create_perfusionist()
    env["p2"] = create_perfusionist(
        full_name="Tom Vasquez", employee_code="EMP-1003", career_case_count=90
    )
    env["slot_p1"] = create_slot(
        env["c1"]["id"],
        env["p1"]["id"],
        window_start=INITIAL_CLOCK,
        window_end=HORIZON_END,
    )
    return env


def test_one_overlapping_minute_is_refused_while_bare_adjacency_is_admitted():
    """A different hospital and a different role do not exempt a single shared minute.

    PRD 3.3: Nobody can be on call twice at once.
    PRD 3.3: A new slot's half-open interval must not intersect the interval of any other slot held by the same perfusionist whose `status` is `SCHEDULED` or `ACTIVE` — and that test ignores both the hospital and the rotation role, so a person cannot hold primary call at one hospital while holding backup call at another across the same minutes.
    PRD 3.3: A collision is refused with `ERR_ROTATION_SLOT_OVERLAP`.
    PRD 3.3: Because the intervals are half-open, a slot that ends at exactly the instant the next one begins is not a collision and is admitted.

    Design: Difficulty/resource_temporal_overlap/rotation_slot_half_open_adjacency_allowed_overlap_rejected
    """
    env = _two_hospitals_one_holder()

    collision = api_client.create_call_rotation_slot(
        build_call_rotation_slot(
            env["c2"]["id"],
            env["p1"]["id"],
            slot_type="BACKUP_CALL",
            window_start="2026-08-03T23:59:00Z",
            window_end="2026-08-05T00:00:00Z",
        ),
        ADMIN_HEADERS,
    )
    validate_error(collision, "ERR_ROTATION_SLOT_OVERLAP", 409)
    assert_error_envelope(collision, "ERR_ROTATION_SLOT_OVERLAP")

    _, meta = validate_paginated(
        api_client.list_call_rotation_slots(
            ADMIN_HEADERS, params={"perfusionist_id": env["p1"]["id"]}
        )
    )
    assert meta["total_count"] == 1, "the refusal wrote no partial row"

    adjacent = validate_success(
        api_client.create_call_rotation_slot(
            build_call_rotation_slot(
                env["c2"]["id"],
                env["p1"]["id"],
                slot_type="BACKUP_CALL",
                window_start=HORIZON_END,
                window_end="2026-08-05T00:00:00Z",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert adjacent["status"] == "SCHEDULED"
    assert adjacent["window_start"] == HORIZON_END, (
        "starting at the exact instant the incumbent ends is adjacency, not intersection"
    )
    assert adjacent["consumed"] is False
    _, after = validate_paginated(
        api_client.list_call_rotation_slots(
            ADMIN_HEADERS, params={"perfusionist_id": env["p1"]["id"]}
        )
    )
    assert after["total_count"] == 2


def test_a_nested_window_for_a_second_holder_merges_into_one_covered_stretch():
    """The overlap rule is scoped to one person, and merging does not double-count minutes.

    PRD 3.3: A new slot's half-open interval must not intersect the interval of any other slot held by the same perfusionist whose `status` is `SCHEDULED` or `ACTIVE` — and that test ignores both the hospital and the rotation role, so a person cannot hold primary call at one hospital while holding backup call at another across the same minutes.
    PRD 3.3: For each of the two staffing roles `PRIMARY_CALL` and `BACKUP_CALL`, the service collects that contract's slots of that role whose `status` is `SCHEDULED` or `ACTIVE`, intersects each slot's window with the horizon and discards any slot whose intersection is empty, then sorts the surviving intersections by start instant ascending with ties broken by end instant ascending, and merges them: an interval whose start lies strictly after the running interval's end begins a new merged interval, while an interval whose start is at or before the running interval's end extends the running interval to the later of the two end instants.
    PRD 3.3: The contract is `COVERED` when primary-call coverage fills the horizon completely — all 4320 minutes, with no gap anywhere — and backup-call coverage reaches at least half the horizon, meaning at least 2160 minutes.
    PRD 3.3: Failing that, the contract is `THIN` when primary-call coverage reaches at least half the horizon, again 2160 minutes or more.
    PRD 3.3: Failing both, the contract is `UNCOVERED`.

    Design: Difficulty/resource_temporal_overlap/rotation_slot_half_open_adjacency_allowed_overlap_rejected
    """
    env = _two_hospitals_one_holder()
    assert read_contract(env["c1"]["id"])["coverage_posture"] == "THIN"

    nested = create_slot(
        env["c1"]["id"],
        env["p2"]["id"],
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )
    assert nested["status"] == "SCHEDULED", (
        "a window wholly inside another holder's window is a different person's calendar"
    )

    merged = read_contract(env["c1"]["id"])
    assert merged["coverage_posture"] == "THIN", (
        "the two primary windows merge to the horizon's 4320 minutes, and backup cover is 0"
    )

    beyond = create_slot(
        env["c2"]["id"],
        env["p1"]["id"],
        slot_type="BACKUP_CALL",
        window_start=HORIZON_END,
        window_end="2026-08-05T00:00:00Z",
    )
    assert beyond["window_start"] == HORIZON_END
    assert read_contract(env["c2"]["id"])["coverage_posture"] == "UNCOVERED", (
        "a window lying wholly beyond the horizon has an empty intersection and is discarded"
    )


CASE_B_WINDOW = ("2026-08-02T13:30:00Z", "2026-08-02T19:30:00Z")
CASE_C_WINDOW = ("2026-08-02T13:31:00Z", "2026-08-02T19:31:00Z")


def _fleet_with_three_case_windows():
    """One machine pair, one holder, and three non-intersecting case windows.

    Case A runs 06:00-12:00 and holds the pair; case B opens exactly 90 minutes
    after A ends and case C one minute later than B.
    """
    env = base_setup()
    add_perfusionist(env, "p2")
    add_slot(
        env,
        env["p2"]["id"],
        key="slot_p2",
        slot_type="BACKUP_CALL",
        window_start=INITIAL_CLOCK,
        window_end="2026-08-03T00:00:00Z",
    )
    env["case"] = assign_perfusionist(
        env["case"]["id"], env["p1"]["id"], env["case"]["version"], env["chief"]["id"]
    )
    env["pack_a"] = configure_pack(env["case"]["id"], env["d1"]["id"], env["p1"]["id"])
    for key, (start, end) in (("case_b", CASE_B_WINDOW), ("case_c", CASE_C_WINDOW)):
        scheduled = add_case(env, key, scheduled_start=start, scheduled_end=end)
        env[key] = assign_perfusionist(
            scheduled["id"], env["p1"]["id"], scheduled["version"], env["chief"]["id"]
        )
    return env


def test_a_raw_gap_of_exactly_ninety_minutes_collides_on_the_turnaround_buffer():
    """The machines are merely reserved, so it is the buffer row and not availability that answers.

    PRD 3.5: A machine needs 90 minutes of turnaround between cases — an hour and a half to be broken down, cleaned and rebuilt — and the test therefore compares the incoming case against each case already holding that machine in `PACK_CONFIGURED`, `SETUP_VERIFIED` or `ON_BYPASS`, adding the 90-minute buffer once to the incumbent side of each comparison and using non-strict comparisons on both sides.
    PRD 3.5: A collision exists exactly when the incoming case's `scheduled_start` is at or before the incumbent's `scheduled_end` plus 90 minutes, **and** the incumbent's `scheduled_start` is at or before the incoming case's `scheduled_end` plus 90 minutes.
    PRD 3.5: The consequence at the boundary is worth stating plainly: a raw gap of exactly 90 minutes between two cases collides and is refused, while a gap of 91 minutes passes.
    PRD 3.5: Its `status` must be `AVAILABLE` or `RESERVED` — a machine already reserved for a non-colliding case window is perfectly usable, whereas a machine that is `IN_USE` or `NEEDS_SERVICE` is refused with `ERR_DEVICE_NOT_AVAILABLE`.

    Design: Difficulty/resource_temporal_overlap/device_turnaround_buffer_rejects_gap_of_exactly_ninety_minutes
    """
    env = _fleet_with_three_case_windows()
    case_b_id = env["case_b"]["id"]
    assert_device_state(read_device(env["d1"]["id"]), "RESERVED", open_reservation_count=1)
    assert_device_state(read_device(env["d2"]["id"]), "RESERVED", open_reservation_count=1)
    assert env["case_b"]["bypass_status"] == "STAFFED"

    collision = api_client.configure_disposable_pack(
        case_b_id, build_pack_configuration(env["d1"]["id"]), env["p1_headers"]
    )
    validate_error(collision, "ERR_DEVICE_TURNAROUND_CONFLICT", 409)
    assert_error_envelope(collision, "ERR_DEVICE_TURNAROUND_CONFLICT")
    assert collision.json()["data"]["error_id"] != "ERR_DEVICE_NOT_AVAILABLE", (
        "a machine reserved for another case window is perfectly usable; only the buffer refuses"
    )

    untouched = read_case(case_b_id)
    assert untouched["bypass_status"] == "STAFFED"
    assert untouched["primary_device_id"] is None
    assert untouched["backup_device_id"] is None
    _, meta = validate_paginated(
        api_client.list_disposable_packs(ADMIN_HEADERS, params={"case_id": case_b_id})
    )
    assert meta["total_count"] == 0
    assert_device_state(read_device(env["d1"]["id"]), "RESERVED", open_reservation_count=1)
    assert_device_state(read_device(env["d2"]["id"]), "RESERVED", open_reservation_count=1)


def test_one_extra_minute_clears_the_buffer_and_the_pair_carries_two_reservations():
    """A 91-minute gap passes, and the reservation figure proves it counts rather than locks.

    PRD 3.5: A collision exists exactly when the incoming case's `scheduled_start` is at or before the incumbent's `scheduled_end` plus 90 minutes, **and** the incumbent's `scheduled_start` is at or before the incoming case's `scheduled_end` plus 90 minutes.
    PRD 3.5: The consequence at the boundary is worth stating plainly: a raw gap of exactly 90 minutes between two cases collides and is refused, while a gap of 91 minutes passes.
    PRD 3.5: Both machines end at `RESERVED`: a machine that was `AVAILABLE` moves `AVAILABLE → RESERVED`, and a machine already `RESERVED` for another non-colliding case simply stays `RESERVED` with a higher reservation count.
    PRD 3.5: That count, `open_reservation_count`, is recomputed from scratch for each touched machine as the number of bypass cases naming that machine as either their primary or their standby whose `bypass_status` is `PACK_CONFIGURED`, `SETUP_VERIFIED` or `ON_BYPASS` — which is why it is a count rather than a flag, and why cases in `SCHEDULED`, `STAFFED`, `OFF_BYPASS`, `CLOSED` or `CANCELLED` never contribute to it.
    PRD 3.5: For each materialised line, the gross value is its `quantity` multiplied by its `unit_cost_cents`; the discounted value is that gross multiplied by one minus the contract's `disposable_discount_pct`; the marked-up value is the discounted value multiplied by one plus the contract's `disposable_markup_pct`; and the line's `line_total_cents` is that marked-up value rounded half up to a whole number of cents.
    PRD 3.5: The pack's `pack_cost_cents` is the exact sum of those already-rounded line totals — never the rounding of an unrounded sum, as §2.6 insists.

    Design: Difficulty/resource_temporal_overlap/device_turnaround_buffer_rejects_gap_of_exactly_ninety_minutes
    """
    env = _fleet_with_three_case_windows()
    validate_error(
        api_client.configure_disposable_pack(
            env["case_b"]["id"], build_pack_configuration(env["d1"]["id"]), env["p1_headers"]
        ),
        "ERR_DEVICE_TURNAROUND_CONFLICT",
        409,
    )

    pack_c = validate_success(
        api_client.configure_disposable_pack(
            env["case_c"]["id"], build_pack_configuration(env["d1"]["id"]), env["p1_headers"]
        ),
        201,
    )
    assert_cents(pack_c["pack_cost_cents"], 3741, "pack_cost_cents")

    accepted = read_case(env["case_c"]["id"])
    assert accepted["bypass_status"] == "PACK_CONFIGURED"
    assert accepted["primary_device_id"] == env["d1"]["id"]
    assert accepted["backup_device_id"] == env["d2"]["id"]

    assert_device_state(read_device(env["d1"]["id"]), "RESERVED", open_reservation_count=2)
    assert_device_state(read_device(env["d2"]["id"]), "RESERVED", open_reservation_count=2)
    assert read_case(env["case"]["id"])["bypass_status"] == "PACK_CONFIGURED", (
        "the incumbent case keeps its own reservation alongside the new one"
    )


OVERLAPPING_WINDOWS = (
    ("case_1", "2026-08-02T06:00:00Z", "2026-08-02T12:00:00Z"),
    ("case_2", "2026-08-02T08:00:00Z", "2026-08-02T14:00:00Z"),
    ("case_3", "2026-08-02T10:00:00Z", "2026-08-02T16:00:00Z"),
)


def _three_intersecting_case_windows():
    """Three unstaffed cases whose windows all intersect, and two credentialed holders.

    No pack is configured anywhere, so no machine is involved and no case has
    gone on pump: every fatigue counter therefore reads 0 throughout.
    """
    env = base_setup(with_case=False)
    add_perfusionist(env, "p2")
    create_certification(env["p2"]["id"])
    # A single claim may carry at most 20 credit hours, so the 30 pending hours
    # this holder needs are claimed as two in-cycle activities.
    create_ce_activity(env["p2"]["id"], credit_hours=15, activity_date="2026-03-05T00:00:00Z")
    create_ce_activity(env["p2"]["id"], credit_hours=15, activity_date="2026-03-06T00:00:00Z")
    add_slot(
        env,
        env["p2"]["id"],
        key="slot_p2",
        slot_type="BACKUP_CALL",
        window_start=INITIAL_CLOCK,
        window_end="2026-08-03T00:00:00Z",
    )
    for key, start, end in OVERLAPPING_WINDOWS:
        add_case(env, key, scheduled_start=start, scheduled_end=end)
    return env


def test_one_holder_may_carry_two_intersecting_prepared_cases():
    """Each pair of windows on its own is a legal double-booking.

    PRD 3.4: The concurrency limit looks only at other cases whose half-open planned interval intersects this case's half-open planned interval.
    PRD 3.4: Among those, fewer than 2 may already be staffed to the incoming perfusionist in `STAFFED`, `PACK_CONFIGURED` or `SETUP_VERIFIED` — so a perfusionist may hold two overlapping prepared cases but not three — and exactly zero of them may be staffed to that perfusionist in `ON_BYPASS`, because nobody runs two pumps at once.
    PRD 3.4: On success from `SCHEDULED`, the case moves `SCHEDULED → STAFFED`: `assigned_perfusionist_id` is set to the named perfusionist, the provisional fee is computed and written to `provisional_fee_cents`, the fiscal dimension moves `UNBILLED → PROVISIONAL_ACCRUED`, `accrued_fee_cents` is set to the provisional amount, and the contract absorbs it — `accrued_case_fee_cents` rises by that amount, `accrued_case_count` rises by one, and the contract's `updated_at` and `version` advance.

    Design: Difficulty/resource_temporal_overlap/perfusionist_aggregate_concurrent_case_capacity_rejects_third_overlap
    """
    env = _three_intersecting_case_windows()

    first = assign_perfusionist(
        env["case_1"]["id"], env["p1"]["id"], env["case_1"]["version"], env["chief"]["id"]
    )
    assert_case_dimensions(first, "STAFFED", "PROVISIONAL_ACCRUED")
    assert first["assigned_perfusionist_id"] == env["p1"]["id"]
    assert_cents(first["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)

    second = assign_perfusionist(
        env["case_2"]["id"], env["p1"]["id"], env["case_2"]["version"], env["chief"]["id"]
    )
    assert_case_dimensions(second, "STAFFED", "PROVISIONAL_ACCRUED")
    assert second["assigned_perfusionist_id"] == env["p1"]["id"], (
        "exactly one other intersecting case is already staffed to this holder"
    )
    assert_cents(second["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 800000, 2)


def test_the_third_intersecting_case_is_refused_and_a_second_holder_takes_it_at_once():
    """It is the collective count of intersecting staffed cases that breaks, not any pair.

    PRD 3.4: Among those, fewer than 2 may already be staffed to the incoming perfusionist in `STAFFED`, `PACK_CONFIGURED` or `SETUP_VERIFIED` — so a perfusionist may hold two overlapping prepared cases but not three — and exactly zero of them may be staffed to that perfusionist in `ON_BYPASS`, because nobody runs two pumps at once.
    PRD 3.4: Either violation is `ERR_PERFUSIONIST_CONCURRENT_CASE_LIMIT`.
    PRD 3.4: On success from `SCHEDULED`, the case moves `SCHEDULED → STAFFED`: `assigned_perfusionist_id` is set to the named perfusionist, the provisional fee is computed and written to `provisional_fee_cents`, the fiscal dimension moves `UNBILLED → PROVISIONAL_ACCRUED`, `accrued_fee_cents` is set to the provisional amount, and the contract absorbs it — `accrued_case_fee_cents` rises by that amount, `accrued_case_count` rises by one, and the contract's `updated_at` and `version` advance.
    PRD 3.4: The admission score just computed is stored on the perfusionist.
    PRD 3.2: The **admission** variant counts the holder's verified credits plus their pending credits — the group is willing to admit a perfusionist on the strength of education they have claimed but the back office has not yet adjudicated.
    PRD 3.2: Everything else is identical: a credit ratio, being the smaller of 1.0 and the counted credits divided by the certification's `cycle_credit_requirement`; an experience ratio, being the smaller of 1.0 and the holder's `career_case_count` divided by a career target of 150 completed cases; and a fatigue penalty, being eight hundredths for each case counted in `consecutive_case_count_24h` plus two hundredths for each hour counted in `ecmo_hours_rolling_7d`.
    PRD 3.2: The raw score is fifty-five hundredths of the credit ratio plus forty-five hundredths of the experience ratio, minus the fatigue penalty.
    PRD 3.2: That raw value is then clamped into the closed interval from 0 to 1 — negative results become 0 and results above 1 become 1 — and only then rounded half up to three decimal places.
    PRD 3.2: The perfusionist's `readiness_score` always holds the most recently computed value, and `readiness_variant_last` records which of the two variants produced it: it is set to `ADMISSION` when the value came from an assignment-time admission computation and to `AUDIT` when the value came from a quality-review audit computation.

    Design: Difficulty/resource_temporal_overlap/perfusionist_aggregate_concurrent_case_capacity_rejects_third_overlap
    """
    env = _three_intersecting_case_windows()
    assign_perfusionist(
        env["case_1"]["id"], env["p1"]["id"], env["case_1"]["version"], env["chief"]["id"]
    )
    assign_perfusionist(
        env["case_2"]["id"], env["p1"]["id"], env["case_2"]["version"], env["chief"]["id"]
    )
    case_3 = env["case_3"]

    third = api_client.assign_perfusionist(
        case_3["id"],
        build_assignment(env["p1"]["id"], case_3["version"]),
        env["chief_headers"],
    )
    validate_error(third, "ERR_PERFUSIONIST_CONCURRENT_CASE_LIMIT", 409)
    assert_error_envelope(third, "ERR_PERFUSIONIST_CONCURRENT_CASE_LIMIT")

    untouched = read_case(case_3["id"])
    assert_case_dimensions(untouched, "SCHEDULED", "UNBILLED")
    assert untouched["assigned_perfusionist_id"] is None
    assert_cents(untouched["accrued_fee_cents"], 0, "accrued_fee_cents")
    assert untouched["version"] == case_3["version"], "a refused assignment mutates nothing"
    assert_contract_ledger(read_contract(env["contract"]["id"]), 800000, 2)

    handed_over = assign_perfusionist(
        case_3["id"], env["p2"]["id"], case_3["version"], env["chief"]["id"]
    )
    assert handed_over["assigned_perfusionist_id"] == env["p2"]["id"], (
        "the second holder carries no intersecting staffed case at all"
    )
    assert_case_dimensions(handed_over, "STAFFED", "PROVISIONAL_ACCRUED")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 1200000, 3)

    admitted = read_perfusionist(env["p2"]["id"])
    assert_readiness_score(admitted["readiness_score"], 0.637)
    assert admitted["readiness_variant_last"] == "ADMISSION"
