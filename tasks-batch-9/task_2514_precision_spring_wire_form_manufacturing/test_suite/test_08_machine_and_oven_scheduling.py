"""
Two temporal resources with deliberately opposite interval semantics.

A coiler is single-occupancy: its setup windows are half-open and each is
widened by the machine's own changeover buffer, so a gap exactly equal to the
buffer is legal on either side while one minute less is a clash. A stress-relief
oven is multi-occupancy: its windows are closed, so touching endpoints already
collide, and overlap alone is never the offence — only the summed basket mass
over the colliding set is capped, and a cancelled batch stops counting.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_OVEN_CAPACITY_EXCEEDED,
    ERR_SETUP_WINDOW_CONFLICT,
)
from test_helpers.test_users import PROCESS_TECHNICIAN_HEADERS

# The three windows the buffered-conflict instance probes, on one 30-minute coiler.
S1_START = "2026-08-05T08:00:00Z"
S1_END = "2026-08-05T10:00:00Z"
LATE_CLASH_START = "2026-08-05T10:29:00Z"
LATE_LEGAL_START = "2026-08-05T10:30:00Z"
LATE_END = "2026-08-05T12:00:00Z"
EARLY_START = "2026-08-05T06:00:00Z"
EARLY_CLASH_END = "2026-08-05T07:31:00Z"
EARLY_LEGAL_END = "2026-08-05T07:30:00Z"


def _coiler_with_three_designs(api: ApiClient):
    """One 30-minute-buffer coiler, three released designs, each with its own tool.

    Giving every setup its own design keeps the supersession sweep out of the
    picture, so the only thing that can refuse a booking is the window
    arithmetic. The logical clock is left at its initial reading, so every
    window below is in the future.
    """
    world = X.build_world(
        api,
        "tooling",
        program={
            "program_code": "PGM-IND-9",
            "customer_name": "Bramble Industrial Supply",
            "committed_pieces": 100_000,
        },
        design={"part_number": "DA-WIN"},
        tooling={"tool_code": "TL-DA", "original_cost_cents": 1_200_000},
    )
    others = []
    for part_number, tool_code in (("DB-WIN", "TL-DB"), ("DC-WIN", "TL-DC")):
        design = X.draft_design(
            api, world.program_id, world.material_id, part_number=part_number
        )
        X.add_characteristic(api, design["id"])
        design = X.release_prototype(api, design["id"])
        tool = X.capitalise_tooling(
            api, design["id"], tool_code=tool_code, original_cost_cents=1_200_000
        )
        others.append((design, tool))
    machine = X.commission_machine(
        api, machine_code="COIL-10", changeover_buffer_minutes=30
    )
    return world, machine, others


def test_setup_booking_refused_one_minute_inside_the_changeover_buffer(api):
    """PRD §3.6: "Setup windows are treated as half-open intervals that include their
    start and exclude their end, and each is widened at the far end by the machine's own
    changeover buffer expressed as a duration in minutes."

    PRD §3.6: "Two windows conflict when the new window's start is strictly earlier than
    the existing window's end plus the buffer **and** the existing window's start is
    strictly earlier than the new window's end plus the buffer."

    PRD §3.6: "If any such conflicting setup exists, the booking is rejected with
    `ERR_SETUP_WINDOW_CONFLICT` (HTTP 409)."

    PRD §3.6: "A gap exactly equal to `changeover_buffer_minutes` between two windows is
    permitted — the comparison is strict on both sides, so touching the buffer boundary
    is legal."

    Design: Difficulty/resource_temporal_overlap/coiling_machine_half_open_windows_with_symmetric_changeover_buffer
    """
    world, machine, others = _coiler_with_three_designs(api)
    (db_design, db_tool), _ = others

    s1 = X.book_setup(
        api,
        machine,
        world.design_id,
        world.tooling_id,
        window_start=S1_START,
        window_end=S1_END,
    )
    machine = X.refresh_machine(api, machine["id"])
    version_after_first = machine["version"]

    clash = api.create_setup(
        F.setup_payload(
            machine["id"],
            db_design["id"],
            db_tool["id"],
            version_after_first,
            window_start=LATE_CLASH_START,
            window_end=LATE_END,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(clash, ERR_SETUP_WINDOW_CONFLICT)

    admitted = validate_success(
        api.create_setup(
            F.setup_payload(
                machine["id"],
                db_design["id"],
                db_tool["id"],
                version_after_first,
                window_start=LATE_LEGAL_START,
                window_end=LATE_END,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        expected_status=201,
    )
    assert admitted["setup_status"] == C.SETUP_SCHEDULED, (
        "10:30Z is exactly the existing window's end plus the 30-minute buffer, which "
        f"the strict comparison permits, got {admitted['setup_status']}"
    )
    assert admitted["window_start"] == LATE_LEGAL_START, (
        f"the booked window is stored as sent, got {admitted['window_start']}"
    )

    after = X.refresh_machine(api, machine["id"])
    assert after["version"] == version_after_first + 1, (
        "only the admitted booking advances the coiler, so the rejected one left the "
        f"counter at {version_after_first}, got {after['version']}"
    )
    assert after["machine_state"] == C.MACHINE_IDLE, (
        f"no setup was activated, so the coiler is still IDLE, got {after['machine_state']}"
    )
    assert after["active_setup_id"] is None, (
        f"nothing occupies the coiler, got {after['active_setup_id']}"
    )

    first = X.refresh_setup(api, s1["id"])
    assert first["setup_status"] == C.SETUP_SCHEDULED, (
        "the incumbent window is untouched by either attempt, got "
        f"{first['setup_status']}"
    )


def test_setup_booking_buffer_bites_symmetrically_on_the_earlier_side(api):
    """PRD §3.6: "Two windows conflict when the new window's start is strictly earlier
    than the existing window's end plus the buffer **and** the existing window's start is
    strictly earlier than the new window's end plus the buffer."

    PRD §3.6: "If any such conflicting setup exists, the booking is rejected with
    `ERR_SETUP_WINDOW_CONFLICT` (HTTP 409)."

    PRD §3.6: "A gap exactly equal to `changeover_buffer_minutes` between two windows is
    permitted — the comparison is strict on both sides, so touching the buffer boundary
    is legal."

    Design: Difficulty/resource_temporal_overlap/coiling_machine_half_open_windows_with_symmetric_changeover_buffer
    """
    world, machine, others = _coiler_with_three_designs(api)
    _, (dc_design, dc_tool) = others

    s1 = X.book_setup(
        api,
        machine,
        world.design_id,
        world.tooling_id,
        window_start=S1_START,
        window_end=S1_END,
    )
    machine = X.refresh_machine(api, machine["id"])
    version_after_first = machine["version"]

    clash = api.create_setup(
        F.setup_payload(
            machine["id"],
            dc_design["id"],
            dc_tool["id"],
            version_after_first,
            window_start=EARLY_START,
            window_end=EARLY_CLASH_END,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(clash, ERR_SETUP_WINDOW_CONFLICT)

    admitted = validate_success(
        api.create_setup(
            F.setup_payload(
                machine["id"],
                dc_design["id"],
                dc_tool["id"],
                version_after_first,
                window_start=EARLY_START,
                window_end=EARLY_LEGAL_END,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        expected_status=201,
    )
    assert admitted["setup_status"] == C.SETUP_SCHEDULED, (
        "07:30Z plus the 30-minute buffer lands exactly on the incumbent's 08:00Z "
        f"start, which the strict comparison permits, got {admitted['setup_status']}"
    )
    assert admitted["window_end"] == EARLY_LEGAL_END, (
        f"the booked window is stored as sent, got {admitted['window_end']}"
    )

    after = X.refresh_machine(api, machine["id"])
    assert after["version"] == version_after_first + 1, (
        "the earlier-side rejection never advanced the coiler, got "
        f"{after['version']} against {version_after_first + 1}"
    )
    assert after["machine_state"] == C.MACHINE_IDLE, (
        f"no setup was activated, got {after['machine_state']}"
    )

    first = X.refresh_setup(api, s1["id"])
    assert first["setup_status"] == C.SETUP_SCHEDULED, (
        f"the incumbent window is untouched, got {first['setup_status']}"
    )


def test_bookings_for_distinct_designs_never_supersede_one_another(api):
    """PRD §3.6: "It also performs a supersession sweep: every **other** setup on the
    same machine for the same design whose `setup_status` is `SCHEDULED` transitions
    `SCHEDULED → SUPERSEDED`, and each superseded row's `superseded_by_setup_id` is set
    to the id of the setup that has just been created."

    PRD §2.10: "`MachineSetup.superseded_by_setup_id` is likewise a denormalised pointer
    to the setup whose creation superseded this one, and is null unless the row's
    `setup_status` is `SUPERSEDED`."

    PRD §3.6: "A successful booking stamps `set_by_user_id` from the technician's
    `X-User-ID`, opens the setup in `setup_status` `SCHEDULED`, and increases the
    coiler's `version` by 1."

    PRD §3.6: "Setups may be listed filtered by `machine_id`, `design_id`,
    `tooling_asset_id` and `setup_status`."

    Design: Difficulty/resource_temporal_overlap/coiling_machine_half_open_windows_with_symmetric_changeover_buffer
    """
    world, machine, others = _coiler_with_three_designs(api)
    (db_design, db_tool), (dc_design, dc_tool) = others

    s1 = X.book_setup(
        api,
        machine,
        world.design_id,
        world.tooling_id,
        window_start=S1_START,
        window_end=S1_END,
    )
    machine = X.refresh_machine(api, machine["id"])
    version_after_first = machine["version"]

    validate_error(
        api.create_setup(
            F.setup_payload(
                machine["id"],
                db_design["id"],
                db_tool["id"],
                version_after_first,
                window_start=LATE_CLASH_START,
                window_end=LATE_END,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        ERR_SETUP_WINDOW_CONFLICT,
    )
    second = validate_success(
        api.create_setup(
            F.setup_payload(
                machine["id"],
                db_design["id"],
                db_tool["id"],
                version_after_first,
                window_start=LATE_LEGAL_START,
                window_end=LATE_END,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        expected_status=201,
    )
    version_after_second = X.refresh_machine(api, machine["id"])["version"]

    validate_error(
        api.create_setup(
            F.setup_payload(
                machine["id"],
                dc_design["id"],
                dc_tool["id"],
                version_after_second,
                window_start=EARLY_START,
                window_end=EARLY_CLASH_END,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        ERR_SETUP_WINDOW_CONFLICT,
    )
    third = validate_success(
        api.create_setup(
            F.setup_payload(
                machine["id"],
                dc_design["id"],
                dc_tool["id"],
                version_after_second,
                window_start=EARLY_START,
                window_end=EARLY_LEGAL_END,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        expected_status=201,
    )

    first = X.refresh_setup(api, s1["id"])
    assert first["setup_status"] == C.SETUP_SCHEDULED, (
        "the two later bookings name different designs, so the sweep never touches the "
        f"incumbent, got {first['setup_status']}"
    )
    assert first["superseded_by_setup_id"] is None, (
        "the pointer is null unless the row is SUPERSEDED, got "
        f"{first['superseded_by_setup_id']}"
    )
    for label, setup in (("the 10:30Z booking", second), ("the 06:00Z booking", third)):
        live = X.refresh_setup(api, setup["id"])
        assert live["setup_status"] == C.SETUP_SCHEDULED, (
            f"{label} stands on its own window, got {live['setup_status']}"
        )
        assert live["superseded_by_setup_id"] is None, (
            f"{label} was superseded by nothing, got {live['superseded_by_setup_id']}"
        )

    after = X.refresh_machine(api, machine["id"])
    assert after["version"] == version_after_second + 1, (
        "the third admitted booking is the only advance since the second, got "
        f"{after['version']} against {version_after_second + 1}"
    )
    assert after["machine_state"] == C.MACHINE_IDLE, (
        f"no setup was activated, got {after['machine_state']}"
    )

    _, meta = validate_paginated(
        api.list_setups(PROCESS_TECHNICIAN_HEADERS, {"machine_id": machine["id"]})
    )
    assert meta["total_count"] == 3, (
        "three bookings were admitted and two were refused, so the coiler carries "
        f"three setup rows, got {meta['total_count']}"
    )


# The oven windows the aggregate-capacity instance probes, on a 100.0 kg oven.
BATCH_A_START = "2026-08-05T06:00:00Z"
BATCH_A_END = "2026-08-05T10:00:00Z"
TOUCHING_START = "2026-08-05T10:00:00Z"
CLEAR_START = "2026-08-05T10:01:00Z"
LATE_BATCH_END = "2026-08-05T12:00:00Z"
STRADDLE_START = "2026-08-05T09:00:00Z"
STRADDLE_END = "2026-08-05T11:00:00Z"


def _oven_with_one_scheduled_batch(api: ApiClient):
    """A 100.0 kg oven already carrying a 60.0 kg batch on [06:00Z, 10:00Z].

    The run behind the baskets is a RUNNING 1 000-piece run of an unpeened
    stainless extension spring, coiled on COIL-11 out of a 50.0 kg heat, with
    the logical clock pinned at 04:30Z so every oven window below is still in
    the future.
    """
    world = X.build_world(
        api,
        "running",
        program={
            "program_code": "PGM-IND-10",
            "customer_name": "Halcyon Instruments",
            "committed_pieces": 100_000,
        },
        material={
            "spec_code": "MS-SS302-1",
            "wire_material": C.WIRE_STAINLESS_302,
            "tensile_grade_mpa": 1650,
            "shear_modulus_gpa": 69.0,
            "elastic_modulus_gpa": 193.0,
            "density_kg_per_m3": 7900,
            "coating": C.COATING_PASSIVATED,
            "salt_spray_hours": 240,
            "biocompatible": True,
            "cost_per_kg_cents": 2200,
        },
        design={
            "part_number": "D2-OVEN",
            "form_type": C.FORM_EXTENSION,
            "end_type": C.END_HOOK_EXTENSION,
            "wire_diameter_mm": 1.2,
            "outer_diameter_mm": 10.0,
            "free_length_mm": 24.0,
            "active_coils": 6,
            "max_working_load_n": 25,
            "min_working_load_n": 8,
            "cycle_seconds_per_piece": 2.4,
            "shot_peening_required": False,
        },
        characteristics=[
            {
                "char_code": C.CHAR_HOOK_POSITION,
                "nominal_value": 24.0,
                "lsl": 23.7,
                "usl": 24.3,
                "is_safety_critical": False,
                "cpk_floor": 1.0,
            }
        ],
        tooling={"tool_code": "TL-D2-OV", "original_cost_cents": 900_000},
        machine={"machine_code": "COIL-11"},
        setup={
            "window_start": "2026-08-05T04:00:00Z",
            "window_end": "2026-08-05T06:00:00Z",
        },
        activation_clock="2026-08-05T04:30:00Z",
        wire_lot={"heat_number": "HT-050", "received_kg": 50.0},
        run={"planned_pieces": 1_000},
    )
    oven = X.commission_oven(
        api, oven_code="OV-6", capacity_kg=100.0, max_temp_c=450.0
    )
    batch_a = X.schedule_batch(
        api,
        oven["id"],
        world.run_id,
        window_start=BATCH_A_START,
        window_end=BATCH_A_END,
        load_kg=60.0,
        target_temp_c=425.0,
        peening_requested=False,
    )
    return world, oven, batch_a


def test_oven_batch_refused_when_closed_windows_touch_at_a_single_endpoint(api):
    """PRD §3.9: "Oven windows are **closed** intervals, so two windows collide even
    when they merely touch at a single endpoint: they collide when the first window's
    start is at or before the second window's end **and** the second window's start is at
    or before the first window's end."

    PRD §3.9: "Sum `load_kg` over every batch on the same oven whose `batch_status` is
    `SCHEDULED` or `RUNNING` and whose window collides with the new one; batches that are
    `CANCELLED` or `COMPLETE` are excluded even when their windows collide, because their
    mass has left the oven."

    PRD §3.9: "Add the new batch's `load_kg` to that occupied total, round the sum half
    up to three decimal places, and compare it against the oven's `capacity_kg`: the
    comparison is strict, so a total that exceeds capacity is rejected with
    `ERR_OVEN_CAPACITY_EXCEEDED` (HTTP 409) while a total exactly equal to capacity is
    accepted."

    PRD §3.9: "A successful booking opens the batch in `batch_status` `SCHEDULED` and
    adds its `load_kg` to the oven's `scheduled_load_kg`."

    Design: Difficulty/resource_temporal_overlap/stress_relief_oven_closed_intervals_with_aggregate_multi_batch_capacity
    """
    world, oven, batch_a = _oven_with_one_scheduled_batch(api)
    assert batch_a["batch_status"] == C.BATCH_SCHEDULED, (
        f"the incumbent basket is scheduled, got {batch_a['batch_status']}"
    )
    assert X.refresh_oven(api, oven["id"])["scheduled_load_kg"] == 60.000, (
        "the oven carries the incumbent's 60.0 kg, got "
        f"{X.refresh_oven(api, oven['id'])['scheduled_load_kg']}"
    )

    touching = api.create_batch(
        F.batch_payload(
            oven["id"],
            world.run_id,
            window_start=TOUCHING_START,
            window_end=LATE_BATCH_END,
            load_kg=50.0,
            target_temp_c=425.0,
            peening_requested=False,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(touching, ERR_OVEN_CAPACITY_EXCEEDED)
    assert X.refresh_oven(api, oven["id"])["scheduled_load_kg"] == 60.000, (
        "a refused booking adds nothing to the oven, got "
        f"{X.refresh_oven(api, oven['id'])['scheduled_load_kg']}"
    )

    clear = validate_success(
        api.create_batch(
            F.batch_payload(
                oven["id"],
                world.run_id,
                window_start=CLEAR_START,
                window_end=LATE_BATCH_END,
                load_kg=50.0,
                target_temp_c=425.0,
                peening_requested=False,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        expected_status=201,
    )
    assert clear["batch_status"] == C.BATCH_SCHEDULED, (
        "starting one minute after the incumbent's inclusive end misses it entirely, so "
        f"the occupied load for that window is 0.000, got {clear['batch_status']}"
    )

    after = X.refresh_oven(api, oven["id"])
    assert after["scheduled_load_kg"] == 110.000, (
        "scheduled_load_kg is the plain sum over SCHEDULED and RUNNING batches, "
        f"60.0 plus 50.0, got {after['scheduled_load_kg']}"
    )


def test_oven_capacity_aggregates_only_the_batches_still_holding_mass(api):
    """PRD §3.9: "Sum `load_kg` over every batch on the same oven whose `batch_status` is
    `SCHEDULED` or `RUNNING` and whose window collides with the new one; batches that are
    `CANCELLED` or `COMPLETE` are excluded even when their windows collide, because their
    mass has left the oven."

    PRD §3.9: "Add the new batch's `load_kg` to that occupied total, round the sum half
    up to three decimal places, and compare it against the oven's `capacity_kg`: the
    comparison is strict, so a total that exceeds capacity is rejected with
    `ERR_OVEN_CAPACITY_EXCEEDED` (HTTP 409) while a total exactly equal to capacity is
    accepted."

    PRD §3.9: "The batch moves to `CANCELLED` and its `load_kg` is removed from the
    oven's `scheduled_load_kg`, so the interval it occupied stops counting toward capacity
    for every later batch booking."

    PRD §3.9: "Oven windows are **closed** intervals, so two windows collide even when
    they merely touch at a single endpoint: they collide when the first window's start is
    at or before the second window's end **and** the second window's start is at or before
    the first window's end."

    Design: Difficulty/resource_temporal_overlap/stress_relief_oven_closed_intervals_with_aggregate_multi_batch_capacity
    """
    world, oven, batch_a = _oven_with_one_scheduled_batch(api)
    batch_b = X.schedule_batch(
        api,
        oven["id"],
        world.run_id,
        window_start=CLEAR_START,
        window_end=LATE_BATCH_END,
        load_kg=50.0,
        target_temp_c=425.0,
        peening_requested=False,
    )

    straddling = api.create_batch(
        F.batch_payload(
            oven["id"],
            world.run_id,
            window_start=STRADDLE_START,
            window_end=STRADDLE_END,
            load_kg=50.0,
            target_temp_c=425.0,
            peening_requested=False,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(straddling, ERR_OVEN_CAPACITY_EXCEEDED)

    cancelled = validate_success(
        api.cancel_batch(batch_b["id"], PROCESS_TECHNICIAN_HEADERS)
    )
    assert cancelled["batch_status"] == C.BATCH_CANCELLED, (
        f"the second basket is withdrawn, got {cancelled['batch_status']}"
    )
    freed = X.refresh_oven(api, oven["id"])
    assert freed["scheduled_load_kg"] == 60.000, (
        "the cancelled basket's 50.0 kg leaves the oven, got "
        f"{freed['scheduled_load_kg']}"
    )

    admitted = validate_success(
        api.create_batch(
            F.batch_payload(
                oven["id"],
                world.run_id,
                window_start=STRADDLE_START,
                window_end=STRADDLE_END,
                load_kg=40.0,
                target_temp_c=425.0,
                peening_requested=False,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        expected_status=201,
    )
    assert admitted["batch_status"] == C.BATCH_SCHEDULED, (
        "with the second basket cancelled the straddling window meets only the "
        f"incumbent, so 60.000 plus 40.000 sits exactly at capacity, got "
        f"{admitted['batch_status']}"
    )

    after = X.refresh_oven(api, oven["id"])
    assert after["scheduled_load_kg"] == 100.000, (
        "the oven now holds the incumbent's 60.0 kg and the new 40.0 kg, got "
        f"{after['scheduled_load_kg']}"
    )
    assert X.refresh_batch(api, batch_a["id"])["batch_status"] == C.BATCH_SCHEDULED, (
        "overlap alone is never the offence, so the incumbent stays scheduled while "
        "sharing [09:00Z, 10:00Z] with the new basket"
    )
    assert X.refresh_batch(api, admitted["id"])["batch_status"] == C.BATCH_SCHEDULED, (
        "the new basket co-resides with the incumbent rather than displacing it"
    )
