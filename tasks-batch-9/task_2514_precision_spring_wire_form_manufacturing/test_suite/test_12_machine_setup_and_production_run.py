"""
The coiler's occupancy cycle and the production run's two independent axes.

A coiling machine is a single-occupancy resource driven entirely by other
entities' triggers: activating a setup takes it out of rest, opening a run puts
it into production, and closing or abandoning that run hands it back. Its
`active_setup_id` is never written directly — it is a pointer to whichever setup
row is currently `ACTIVE`, so every edge that changes occupancy must move both
the setup and the pointer together.

The run itself carries two status axes that do not gate each other. The process
axis walks the first article through to completion; the quality axis holds and
releases on statistical evidence, and only an out-of-control subgroup on a
safety-critical characteristic can drive it. Where the two axes do meet, they
meet by an explicit rule: completion refuses a held run, and a scrap verdict
cancels the process axis only when that axis is still live.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_INCOMPLETE_FAI_COVERAGE,
    ERR_MACHINE_NOT_IDLE,
    ERR_OUTSIDE_SETUP_WINDOW,
    ERR_RUN_INVALID_STATE,
    ERR_RUN_NOT_ON_HOLD,
    ERR_RUN_ON_SPC_HOLD,
    ERR_SELF_DISPOSITION_FORBIDDEN,
    ERR_SETUP_INVALID_STATE,
    ERR_SETUP_NOT_ACTIVE,
)
from test_helpers.test_users import (
    PROCESS_TECHNICIAN_HEADERS,
    QUALITY_INSPECTOR_ALT_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    QUALITY_INSPECTOR_THIRD_HEADERS,
)

# Two windows on one 45-minute-buffer coiler: the second opens a full hour after
# the first closes, so both bookings stand and only occupancy can refuse the
# second activation.
MORNING_START = "2026-08-05T08:00:00Z"
MORNING_END = "2026-08-05T10:00:00Z"
MIDDAY_START = "2026-08-05T11:00:00Z"
MIDDAY_END = "2026-08-05T13:00:00Z"
CLOCK_INSIDE_MIDDAY_WINDOW = "2026-08-05T11:30:00Z"

# The subgroup that holds the run: 59.4 sits below the 59.5 lower limit and the
# Bessel-corrected sigma of 0.6 puts the index at 0.278, far under the 1.333 floor.
HOLDING_SUBGROUP = [59.4, 60.0, 60.6]
HOLDING_SUBGROUP_CPK = 0.278

# A second characteristic on the print, so first-article coverage needs two records.
DIAMETER_PLAN = {
    "char_code": C.CHAR_OUTER_DIAMETER,
    "nominal_value": 20.0,
    "lsl": 19.8,
    "usl": 20.2,
    "is_safety_critical": True,
    "cpk_floor": 1.333,
}

# The same print limits declared as not safety critical, with a subgroup that
# breaks both of them: sigma 0.300000 and an index of 0.222.
NON_SAFETY_DIAMETER_PLAN = dict(DIAMETER_PLAN, is_safety_critical=False)
WIDE_DIAMETER_SUBGROUP = [19.7, 20.0, 20.3]
WIDE_DIAMETER_CPK = 0.222
WIDE_DIAMETER_SIGMA = 0.300000

# The canonical 26 000-piece run against an 800.000 kg heat, closed at 25 500 good
# and 500 scrapped.
RESERVED_KG = 567.334
CONSUMED_KG = 550.810
ON_HAND_AFTER_COMPLETION_KG = 249.190
RECEIVED_KG = 800.000


def test_machine_cycle_walks_idle_setup_production_and_back_to_idle(api):
    """PRD §3.6: "The machine cycles `IDLE → SETUP → PRODUCTION → IDLE` with an early
    exit back to `IDLE` when a setup is aborted, and the three values `IDLE`, `SETUP`
    and `PRODUCTION` are the only ones it takes."

    PRD §3.6: "On success the coiler transitions `IDLE → SETUP`, its `active_setup_id`
    is set to this setup's id, and its `version` increases by 1."

    PRD §3.7: "Its coiler transitions `SETUP → PRODUCTION` and the machine's `version`
    increases by 1."

    PRD §3.7: "On success both counts are recorded and `process_status` becomes
    `COMPLETE`."

    PRD §3.7: "The run's setup transitions `ACTIVE → RELEASED`, and the coiler returns
    `PRODUCTION → IDLE` with `active_setup_id` cleared and `version` increased by 1."

    PRD §2.10: "`CoilingMachine.active_setup_id` is a denormalised pointer resolved as
    the single machine setup row on that machine whose `setup_status` is `ACTIVE`, and
    is null when no such row exists; it is never accepted as an input."

    Design: Corner/state_machines/machine_cycles_idle_setup_production_idle_across_one_run
    """
    world = X.build_world(api, "certified_wire")

    assert world.machine["machine_state"] == C.MACHINE_SETUP, (
        "activating the setup is the first edge of the cycle, so the coiler reads "
        f"SETUP, got {world.machine['machine_state']}"
    )
    assert world.machine["active_setup_id"] == world.setup_id, (
        "the pointer resolves to the one ACTIVE setup row, got "
        f"{world.machine['active_setup_id']}"
    )
    version_in_setup = world.machine["version"]

    run = X.open_run(api, world.setup_id, world.wire_lot_id, world.design_id)
    in_production = X.refresh_machine(api, world.machine_id)
    assert in_production["machine_state"] == C.MACHINE_PRODUCTION, (
        "opening the run is the second edge, driven from the run rather than the "
        f"setup, got {in_production['machine_state']}"
    )
    assert in_production["active_setup_id"] == world.setup_id, (
        "the setup is still ACTIVE while the run coils, so the pointer holds, got "
        f"{in_production['active_setup_id']}"
    )
    assert in_production["version"] == version_in_setup + 1, (
        "opening a run changes the coiler's occupancy and so advances its version "
        f"by 1, got {in_production['version']} from {version_in_setup}"
    )

    X.record_fai_subgroup(api, run["id"], world.characteristics[0])
    X.accept_first_article(api, run["id"])
    for _ in range(2):
        X.record_spc_subgroup(api, run["id"], world.characteristics[0])

    closed = validate_success(
        api.complete_run(
            run["id"], F.completion_payload(25_500, 500), PROCESS_TECHNICIAN_HEADERS
        )
    )
    assert closed["process_status"] == C.PROCESS_COMPLETE, (
        f"the completed run closes its process axis, got {closed['process_status']}"
    )

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_RELEASED, (
        "completion is the system-driven edge that releases the setup, got "
        f"{setup['setup_status']}"
    )
    at_rest = X.refresh_machine(api, world.machine_id)
    assert at_rest["machine_state"] == C.MACHINE_IDLE, (
        "the third edge returns the coiler to rest, got "
        f"{at_rest['machine_state']}"
    )
    assert at_rest["active_setup_id"] is None, (
        "no setup row is ACTIVE any more, so the pointer resolves to null, got "
        f"{at_rest['active_setup_id']}"
    )
    assert at_rest["version"] == in_production["version"] + 1, (
        "completing the run advances the coiler's version by 1, got "
        f"{at_rest['version']} from {in_production['version']}"
    )


def test_aborting_an_active_setup_returns_the_coiler_to_idle(api):
    """PRD §3.6: "Aborting is the escape hatch and accepts a setup in either
    `SCHEDULED` or `ACTIVE`; anything else answers `ERR_SETUP_INVALID_STATE`."

    PRD §3.6: "The setup transitions to `ABORTED`."

    PRD §3.6: "If it had been `ACTIVE`, the coiler returns to `machine_state` `IDLE`
    with `active_setup_id` cleared to null and its `version` increased by 1; a setup
    aborted straight out of `SCHEDULED` was never occupying the machine and leaves it
    alone."

    PRD §2.10: "`CoilingMachine.active_setup_id` is a denormalised pointer resolved as
    the single machine setup row on that machine whose `setup_status` is `ACTIVE`, and
    is null when no such row exists; it is never accepted as an input."

    Design: Corner/state_machines/setup_abort_from_active_returns_the_machine_to_idle
    """
    world = X.active_setup_world(api)
    assert world.machine["machine_state"] == C.MACHINE_SETUP, (
        "the abort has to start from an occupied coiler, got "
        f"{world.machine['machine_state']}"
    )
    version_in_setup = world.machine["version"]

    aborted = validate_success(
        api.abort_setup(world.setup_id, PROCESS_TECHNICIAN_HEADERS)
    )
    assert aborted["setup_status"] == C.SETUP_ABORTED, (
        f"the aborted setup ends on ABORTED, got {aborted['setup_status']}"
    )

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_IDLE, (
        "aborting an ACTIVE setup is the early exit straight back to rest, got "
        f"{machine['machine_state']}"
    )
    assert machine["active_setup_id"] is None, (
        "no setup row is ACTIVE after the abort, so the pointer is null, got "
        f"{machine['active_setup_id']}"
    )
    assert machine["version"] == version_in_setup + 1, (
        "aborting a setup that was ACTIVE advances the coiler's version by 1, got "
        f"{machine['version']} from {version_in_setup}"
    )


def _second_design_with_its_own_tool(api: ApiClient, world: X.World):
    """A second released design on the same program, carrying its own tool set.

    Two different designs keep the supersession sweep out of the picture, so the
    only thing that can refuse the second activation is the coiler's occupancy.
    """
    design = X.draft_design(api, world.program_id, world.material_id, part_number="D2")
    X.add_characteristic(api, design["id"])
    design = X.release_prototype(api, design["id"])
    tool = X.capitalise_tooling(api, design["id"], tool_code="TL-2")
    return design, tool


def test_activating_a_second_setup_while_the_coiler_is_occupied_is_refused(api):
    """PRD §3.6: "Activating a setup takes it `SCHEDULED → ACTIVE`."

    PRD §3.6: "The coiler must be at rest: if its `machine_state` is anything but
    `IDLE`, the activation answers `ERR_MACHINE_NOT_IDLE` (HTTP 409)."

    PRD §2.10: "`CoilingMachine.active_setup_id` is a denormalised pointer resolved as
    the single machine setup row on that machine whose `setup_status` is `ACTIVE`, and
    is null when no such row exists; it is never accepted as an input."

    Design: Corner/state_machines/setup_activate_when_the_machine_is_not_idle_rejected
    """
    world = X.build_world(api, "machine")
    morning = X.book_setup(
        api,
        world.machine,
        world.design_id,
        world.tooling_id,
        window_start=MORNING_START,
        window_end=MORNING_END,
    )
    world.machine = X.refresh_machine(api, world.machine_id)
    second_design, second_tool = _second_design_with_its_own_tool(api, world)
    midday = X.book_setup(
        api,
        world.machine,
        second_design["id"],
        second_tool["id"],
        window_start=MIDDAY_START,
        window_end=MIDDAY_END,
    )
    assert midday["setup_status"] == C.SETUP_SCHEDULED, (
        "the hour between the two windows clears the 45-minute buffer, so the second "
        f"booking stands, got {midday['setup_status']}"
    )

    X.pin_clock(api, C.CLOCK_INSIDE_SETUP_WINDOW)
    X.activate_setup(api, morning["id"])
    X.pin_clock(api, CLOCK_INSIDE_MIDDAY_WINDOW)

    validate_error(
        api.activate_setup(midday["id"], PROCESS_TECHNICIAN_HEADERS),
        ERR_MACHINE_NOT_IDLE,
        expected_status=409,
    )

    refused = X.refresh_setup(api, midday["id"])
    assert refused["setup_status"] == C.SETUP_SCHEDULED, (
        "the refused activation left its setup on the state it started from, got "
        f"{refused['setup_status']}"
    )
    incumbent = X.refresh_setup(api, morning["id"])
    assert incumbent["setup_status"] == C.SETUP_ACTIVE, (
        "the setup holding the coiler is untouched by the refusal, got "
        f"{incumbent['setup_status']}"
    )
    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_SETUP, (
        "the coiler is still occupied by the morning setup, got "
        f"{machine['machine_state']}"
    )
    assert machine["active_setup_id"] == morning["id"], (
        "the pointer still resolves to the one ACTIVE row, got "
        f"{machine['active_setup_id']}"
    )


def test_activating_at_the_exclusive_window_end_is_outside_the_window(api):
    """PRD §3.6: "Activating a setup takes it `SCHEDULED → ACTIVE`."

    PRD §3.6: "And the logical clock must be inside the booked window, at or after
    `window_start` and strictly before `window_end`; outside that span the answer is
    `ERR_OUTSIDE_SETUP_WINDOW` (HTTP 409)."

    PRD §3.6: "A new coiler opens in `machine_state` `IDLE` with `active_setup_id`
    null."

    Design: Corner/state_machines/setup_activate_at_the_exclusive_window_end_rejected
    """
    world = X.scheduled_setup_world(api)
    assert world.setup["window_end"] == C.CLOCK_SETUP_WINDOW_END, (
        "the clock is about to be pinned on the booked window's own end, got "
        f"{world.setup['window_end']}"
    )
    version_before = world.machine["version"]

    X.pin_clock(api, C.CLOCK_SETUP_WINDOW_END)
    validate_error(
        api.activate_setup(world.setup_id, PROCESS_TECHNICIAN_HEADERS),
        ERR_OUTSIDE_SETUP_WINDOW,
        expected_status=409,
    )

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_SCHEDULED, (
        "the window's end is excluded, so the setup never took the edge to ACTIVE, "
        f"got {setup['setup_status']}"
    )
    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_IDLE, (
        f"the coiler was never occupied, got {machine['machine_state']}"
    )
    assert machine["active_setup_id"] is None, (
        f"no setup row is ACTIVE, so the pointer is null, got "
        f"{machine['active_setup_id']}"
    )
    assert machine["version"] == version_before, (
        "a refused activation changes no occupancy and so no version, got "
        f"{machine['version']} from {version_before}"
    )


def test_a_newer_setup_for_the_same_machine_and_design_supersedes_the_older_one(api):
    """PRD §3.6: "A successful booking stamps `set_by_user_id` from the technician's
    `X-User-ID`, opens the setup in `setup_status` `SCHEDULED`, and increases the
    coiler's `version` by 1."

    PRD §3.6: "It also performs a supersession sweep: every **other** setup on the same
    machine for the same design whose `setup_status` is `SCHEDULED` transitions
    `SCHEDULED → SUPERSEDED`, and each superseded row's `superseded_by_setup_id` is set
    to the id of the setup that has just been created."

    PRD §2.10: "`MachineSetup.superseded_by_setup_id` is likewise a denormalised pointer
    to the setup whose creation superseded this one, and is null unless the row's
    `setup_status` is `SUPERSEDED`."

    PRD §3.6: "A new coiler opens in `machine_state` `IDLE` with `active_setup_id`
    null."

    Design: Corner/state_machines/setup_superseded_by_a_newer_setup_for_the_same_machine_and_design
    """
    world = X.build_world(api, "machine")
    first = X.book_setup(
        api,
        world.machine,
        world.design_id,
        world.tooling_id,
        window_start=MORNING_START,
        window_end=MORNING_END,
    )
    assert first["superseded_by_setup_id"] is None, (
        "the pointer is null while the row is still SCHEDULED, got "
        f"{first['superseded_by_setup_id']}"
    )
    after_first = X.refresh_machine(api, world.machine_id)

    second = validate_success(
        api.create_setup(
            F.setup_payload(
                world.machine_id,
                world.design_id,
                world.tooling_id,
                after_first["version"],
                window_start=MIDDAY_START,
                window_end=MIDDAY_END,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        expected_status=201,
    )
    assert second["setup_status"] == C.SETUP_SCHEDULED, (
        f"the newer booking opens on SCHEDULED, got {second['setup_status']}"
    )

    superseded = X.refresh_setup(api, first["id"])
    assert superseded["setup_status"] == C.SETUP_SUPERSEDED, (
        "the older setup on the same machine for the same design is swept aside, got "
        f"{superseded['setup_status']}"
    )
    assert superseded["superseded_by_setup_id"] == second["id"], (
        "the swept row points at the booking that displaced it, got "
        f"{superseded['superseded_by_setup_id']}"
    )

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_IDLE, (
        "booking occupies nothing, so the coiler is still at rest, got "
        f"{machine['machine_state']}"
    )
    assert machine["active_setup_id"] is None, (
        f"no setup row is ACTIVE, so the pointer is null, got "
        f"{machine['active_setup_id']}"
    )
    assert machine["version"] == after_first["version"] + 1, (
        "the second booking advances the coiler's version by 1 again, got "
        f"{machine['version']} from {after_first['version']}"
    )


def test_activating_an_aborted_setup_is_refused(api):
    """PRD §3.6: "The setup must be `SCHEDULED` — a setup that is already `ACTIVE`, or
    that is `RELEASED`, `SUPERSEDED` or `ABORTED`, answers `ERR_SETUP_INVALID_STATE`
    (HTTP 409)."

    PRD §3.6: "Aborting is the escape hatch and accepts a setup in either `SCHEDULED`
    or `ACTIVE`; anything else answers `ERR_SETUP_INVALID_STATE`."

    PRD §3.6: "If it had been `ACTIVE`, the coiler returns to `machine_state` `IDLE`
    with `active_setup_id` cleared to null and its `version` increased by 1; a setup
    aborted straight out of `SCHEDULED` was never occupying the machine and leaves it
    alone."

    Design: Corner/state_machines/setup_activate_on_an_aborted_setup_rejected
    """
    world = X.scheduled_setup_world(api)
    version_before = world.machine["version"]

    aborted = validate_success(
        api.abort_setup(world.setup_id, PROCESS_TECHNICIAN_HEADERS)
    )
    assert aborted["setup_status"] == C.SETUP_ABORTED, (
        "the abort is taken straight out of SCHEDULED, got "
        f"{aborted['setup_status']}"
    )

    X.pin_clock(api, C.CLOCK_INSIDE_SETUP_WINDOW)
    validate_error(
        api.activate_setup(world.setup_id, PROCESS_TECHNICIAN_HEADERS),
        ERR_SETUP_INVALID_STATE,
        expected_status=409,
    )

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_ABORTED, (
        "the clock is inside the booked window, but an aborted setup has no edge back "
        f"to ACTIVE, got {setup['setup_status']}"
    )
    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_IDLE, (
        "a setup aborted out of SCHEDULED never occupied the coiler, got "
        f"{machine['machine_state']}"
    )
    assert machine["active_setup_id"] is None, (
        f"no setup row is ACTIVE, so the pointer is null, got "
        f"{machine['active_setup_id']}"
    )
    assert machine["version"] == version_before, (
        "neither the abort out of SCHEDULED nor the refused activation touches the "
        f"coiler, got version {machine['version']} from {version_before}"
    )


def test_opening_a_run_against_a_setup_that_was_never_activated_is_refused(api):
    """PRD §3.7: "The setup must currently be `ACTIVE`; a `SCHEDULED`, `RELEASED`,
    `SUPERSEDED` or `ABORTED` setup answers `ERR_SETUP_NOT_ACTIVE` (HTTP 409)."

    PRD §3.7: "On success the reservation moves mass without creating any:
    `wire_reserved_kg` is subtracted from the heat's `on_hand_kg` and added to its
    `reserved_kg`, leaving `received_kg` untouched."

    Design: Corner/state_machines/run_creation_against_a_scheduled_setup_rejected
    """
    world = X.build_world(api, "setup")
    lot = X.certified_wire(api, world.material_id)
    assert world.setup["setup_status"] == C.SETUP_SCHEDULED, (
        "the setup is booked but never activated, got "
        f"{world.setup['setup_status']}"
    )

    validate_error(
        api.create_run(
            F.run_payload(world.setup_id, lot["id"], world.design_id),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        ERR_SETUP_NOT_ACTIVE,
        expected_status=409,
    )

    heat = X.refresh_wire_lot(api, lot["id"])
    assert heat["on_hand_kg"] == RECEIVED_KG, (
        "the refusal lands before the reservation, so the whole heat is still on "
        f"hand, got {heat['on_hand_kg']}"
    )
    assert heat["reserved_kg"] == 0.000, (
        f"no mass was moved into the reserved bucket, got {heat['reserved_kg']}"
    )
    assert heat["consumed_kg"] == 0.000, (
        f"nothing has been consumed either, got {heat['consumed_kg']}"
    )
    A.assert_wire_ledger_conserved(heat)

    runs, meta = validate_paginated(api.list_runs(PROCESS_TECHNICIAN_HEADERS))
    assert meta["total_count"] == 0, (
        f"the rejected request created no run row, got {meta['total_count']}"
    )
    assert runs == [], f"the run list is empty, got {runs}"


def test_the_inspector_who_measured_the_first_article_may_not_dispose_it(api):
    """PRD §3.7: "Both branches enforce exactly the same five gates, in this order: the
    run's `process_status` must be `FAI_PENDING`, otherwise `ERR_RUN_INVALID_STATE`;
    `fai_disposition` must still be `PENDING`, otherwise
    `ERR_FAI_ALREADY_DISPOSITIONED` (HTTP 409); the acting `X-User-ID` must not match
    the `inspected_by_user_id` of any first-article record on this run, otherwise
    `ERR_SELF_DISPOSITION_FORBIDDEN` (HTTP 409) — whoever measured may not judge; the
    run's design must have at least one critical characteristic, otherwise
    `ERR_CHARACTERISTIC_SET_EMPTY` (HTTP 422); and every critical characteristic of
    that design must have at least one first-article record on this run, otherwise
    `ERR_INCOMPLETE_FAI_COVERAGE` (HTTP 422)."

    PRD §3.7: "`ACCEPT` sets `fai_disposition` to `ACCEPTED` and advances the run
    `FAI_PENDING → RUNNING`, and nothing else moves."

    Design: Corner/state_machines/run_fai_disposition_by_the_measuring_inspector_is_forbidden
    """
    world = X.measured_run_world(api)
    measurer = QUALITY_INSPECTOR_HEADERS["X-User-ID"]
    assert world.fai_records[0]["inspected_by_user_id"] == measurer, (
        "the record carries the identity of whoever measured it, got "
        f"{world.fai_records[0]['inspected_by_user_id']}"
    )

    validate_error(
        api.dispose_fai(
            world.run_id, {"decision": C.DECISION_ACCEPT}, QUALITY_INSPECTOR_HEADERS
        ),
        ERR_SELF_DISPOSITION_FORBIDDEN,
        expected_status=409,
    )

    run = X.refresh_run(api, world.run_id)
    assert run["fai_disposition"] == C.FAI_PENDING, (
        "the verdict never landed, so the first article is still undecided, got "
        f"{run['fai_disposition']}"
    )
    assert run["process_status"] == C.PROCESS_FAI_PENDING, (
        "only an accepted first article advances the process axis, got "
        f"{run['process_status']}"
    )


def test_first_article_verdict_without_coverage_of_every_characteristic_is_refused(api):
    """PRD §3.7: "Both branches enforce exactly the same five gates, in this order: the
    run's `process_status` must be `FAI_PENDING`, otherwise `ERR_RUN_INVALID_STATE`;
    `fai_disposition` must still be `PENDING`, otherwise
    `ERR_FAI_ALREADY_DISPOSITIONED` (HTTP 409); the acting `X-User-ID` must not match
    the `inspected_by_user_id` of any first-article record on this run, otherwise
    `ERR_SELF_DISPOSITION_FORBIDDEN` (HTTP 409) — whoever measured may not judge; the
    run's design must have at least one critical characteristic, otherwise
    `ERR_CHARACTERISTIC_SET_EMPTY` (HTTP 422); and every critical characteristic of
    that design must have at least one first-article record on this run, otherwise
    `ERR_INCOMPLETE_FAI_COVERAGE` (HTTP 422)."

    PRD §3.7: "Coverage is about characteristics, not counts: one subgroup per
    characteristic suffices, and a sixth subgroup on an already-covered characteristic
    does nothing for the missing one."

    PRD §3.3: "Adding a characteristic to a design that has left `DRAFT` is rejected
    with `ERR_DESIGN_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/run_fai_disposition_without_full_characteristic_coverage_rejected
    """
    world = X.build_world(api, "run", characteristics=[{}, DIAMETER_PLAN])
    assert len(world.characteristics) == 2, (
        "both characteristics have to join the plan while the design is still DRAFT, "
        f"got {len(world.characteristics)}"
    )

    X.record_fai_subgroup(api, world.run_id, world.characteristics[0])

    validate_error(
        api.dispose_fai(
            world.run_id,
            {"decision": C.DECISION_ACCEPT},
            QUALITY_INSPECTOR_ALT_HEADERS,
        ),
        ERR_INCOMPLETE_FAI_COVERAGE,
        expected_status=422,
    )

    run = X.refresh_run(api, world.run_id)
    assert run["fai_disposition"] == C.FAI_PENDING, (
        "the second characteristic has no first-article record, so the verdict is "
        f"refused and the run stays undecided, got {run['fai_disposition']}"
    )
    assert run["process_status"] == C.PROCESS_FAI_PENDING, (
        "the process axis is still waiting on the first article, got "
        f"{run['process_status']}"
    )


def test_first_article_measurement_on_a_cancelled_run_is_refused(api):
    """PRD §3.7: "Abandoning a run is available from `FAI_PENDING` or `RUNNING`; any
    other `process_status` answers `ERR_RUN_INVALID_STATE`."

    PRD §3.7: "The run moves to `CANCELLED`, the whole reservation comes back using the
    stored `wire_reserved_kg` verbatim — subtracted from `reserved_kg`, added to
    `on_hand_kg`, with `consumed_kg` untouched — the setup transitions
    `ACTIVE → ABORTED`, and the coiler returns to `IDLE` with `active_setup_id` null and
    `version` increased by 1."

    PRD §3.7: "The run must be `FAI_PENDING`, otherwise `ERR_RUN_INVALID_STATE` (HTTP
    409)."

    Design: Corner/state_machines/run_fai_measurement_on_a_cancelled_run_rejected
    """
    world = X.run_world(api)
    assert world.wire_lot["reserved_kg"] == RESERVED_KG, (
        "the open run holds its reservation before the cancellation, got "
        f"{world.wire_lot['reserved_kg']}"
    )

    cancelled = validate_success(
        api.cancel_run(world.run_id, PROCESS_TECHNICIAN_HEADERS)
    )
    assert cancelled["process_status"] == C.PROCESS_CANCELLED, (
        f"the abandoned run ends on CANCELLED, got {cancelled['process_status']}"
    )

    validate_error(
        api.record_fai(
            world.run_id,
            F.measurement_payload(world.characteristic_id),
            QUALITY_INSPECTOR_HEADERS,
        ),
        ERR_RUN_INVALID_STATE,
        expected_status=409,
    )

    records, meta = validate_paginated(
        api.list_inspection_records(
            QUALITY_INSPECTOR_HEADERS, {"run_id": world.run_id}
        )
    )
    assert meta["total_count"] == 0, (
        "a cancelled run takes no first-article record at all, got "
        f"{meta['total_count']}"
    )
    assert records == [], f"no inspection row was written, got {records}"

    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    assert heat["on_hand_kg"] == RECEIVED_KG, (
        "the cancellation gave the whole reservation back, and the refused "
        f"measurement moved nothing, got {heat['on_hand_kg']}"
    )
    assert heat["reserved_kg"] == 0.000, (
        f"the reserved bucket was emptied by the cancellation, got "
        f"{heat['reserved_kg']}"
    )
    assert heat["consumed_kg"] == 0.000, (
        f"a cancellation leaves `consumed_kg` untouched, got {heat['consumed_kg']}"
    )
    A.assert_wire_ledger_conserved(heat)


def test_a_second_first_article_verdict_is_refused(api):
    """PRD §3.7: "Both branches enforce exactly the same five gates, in this order: the
    run's `process_status` must be `FAI_PENDING`, otherwise `ERR_RUN_INVALID_STATE`;
    `fai_disposition` must still be `PENDING`, otherwise
    `ERR_FAI_ALREADY_DISPOSITIONED` (HTTP 409); the acting `X-User-ID` must not match
    the `inspected_by_user_id` of any first-article record on this run, otherwise
    `ERR_SELF_DISPOSITION_FORBIDDEN` (HTTP 409) — whoever measured may not judge; the
    run's design must have at least one critical characteristic, otherwise
    `ERR_CHARACTERISTIC_SET_EMPTY` (HTTP 422); and every critical characteristic of
    that design must have at least one first-article record on this run, otherwise
    `ERR_INCOMPLETE_FAI_COVERAGE` (HTTP 422)."

    PRD §3.7: "`ACCEPT` sets `fai_disposition` to `ACCEPTED` and advances the run
    `FAI_PENDING → RUNNING`, and nothing else moves."

    Design: Corner/state_machines/run_second_fai_disposition_rejected
    """
    world = X.running_run_world(api)
    assert world.run["fai_disposition"] == C.FAI_ACCEPTED, (
        "the first verdict landed and is written once, got "
        f"{world.run['fai_disposition']}"
    )
    assert world.run["process_status"] == C.PROCESS_RUNNING, (
        f"the accepted first article advanced the run, got "
        f"{world.run['process_status']}"
    )

    validate_error(
        api.dispose_fai(
            world.run_id,
            {"decision": C.DECISION_ACCEPT},
            QUALITY_INSPECTOR_THIRD_HEADERS,
        ),
        ERR_RUN_INVALID_STATE,
        expected_status=409,
    )

    run = X.refresh_run(api, world.run_id)
    assert run["fai_disposition"] == C.FAI_ACCEPTED, (
        "a third inspector cannot overwrite a settled verdict, got "
        f"{run['fai_disposition']}"
    )
    assert run["process_status"] == C.PROCESS_RUNNING, (
        "the first of the five gates is the process-status gate, so the refusal "
        "lands there and never re-fires the edge out of FAI_PENDING, got "
        f"{run['process_status']}"
    )


def test_completing_a_run_settles_the_heat_against_its_stored_reservation(api):
    """PRD §3.7: "On success both counts are recorded and `process_status` becomes
    `COMPLETE`."

    PRD §3.7: "Consumption is then computed as the design's stored six-decimal
    `wire_mass_per_piece_kg` multiplied by the sum of `produced_pieces` and
    `scrapped_pieces` — scrap burns wire exactly like good product does — rounded half
    up to three decimal places, and written to `wire_consumed_kg`."

    PRD §3.7: "Three ledger postings follow in this exact order, each rounded half up to
    three decimal places: the run's stored `wire_reserved_kg` is subtracted from the
    heat's `reserved_kg`; `wire_consumed_kg` is added to the heat's `consumed_kg`; and
    the difference between the stored `wire_reserved_kg` and `wire_consumed_kg` is added
    back to the heat's `on_hand_kg`, returning whatever the scrap allowance
    over-reserved."

    PRD §3.7: "`received_kg` is conserved throughout."

    Design: Corner/state_machines/run_complete_syncs_the_wire_ledger_with_the_stored_reservation
    """
    world = X.spc_run_world(api)
    X.record_spc_subgroup(api, world.run_id, world.characteristics[0])
    assert world.run["wire_reserved_kg"] == RESERVED_KG, (
        "the run holds the reservation the completion posting has to reverse, got "
        f"{world.run['wire_reserved_kg']}"
    )

    closed = validate_success(
        api.complete_run(
            world.run_id,
            F.completion_payload(25_500, 500),
            PROCESS_TECHNICIAN_HEADERS,
        )
    )
    assert closed["process_status"] == C.PROCESS_COMPLETE, (
        f"the closed run ends on COMPLETE, got {closed['process_status']}"
    )
    assert closed["produced_pieces"] == 25_500, (
        f"the good count is recorded as sent, got {closed['produced_pieces']}"
    )
    assert closed["scrapped_pieces"] == 500, (
        f"the scrap count is recorded as sent, got {closed['scrapped_pieces']}"
    )
    assert closed["wire_consumed_kg"] == CONSUMED_KG, (
        "26 000 pieces of stored per-piece mass over 25 500 good plus 500 scrapped "
        f"burns {CONSUMED_KG} kg, got {closed['wire_consumed_kg']}"
    )

    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    assert heat["reserved_kg"] == 0.000, (
        "the stored reservation comes off the reserved bucket in full, got "
        f"{heat['reserved_kg']}"
    )
    assert heat["consumed_kg"] == CONSUMED_KG, (
        f"the consumed bucket takes exactly what the run burned, got "
        f"{heat['consumed_kg']}"
    )
    assert heat["on_hand_kg"] == ON_HAND_AFTER_COMPLETION_KG, (
        "the scrap allowance the run over-reserved flows back on hand, got "
        f"{heat['on_hand_kg']}"
    )
    assert heat["received_kg"] == RECEIVED_KG, (
        f"the heat's received mass is never touched, got {heat['received_kg']}"
    )
    A.assert_wire_ledger_conserved(heat)


def test_completing_a_run_held_by_an_out_of_control_subgroup_is_refused(api):
    """PRD §3.7: "`control_state` is `OUT_OF_CONTROL` when the **rounded** `cpk_value`
    is below the characteristic's `cpk_floor`, or when any single measurement in the
    subgroup lies above `usl` or below `lsl`; it is `IN_CONTROL` otherwise."

    PRD §3.8: "Hop two: the run's `quality_status` transitions `OPEN → SPC_HOLD`."

    PRD §3.7: "The run must not be on `SPC_HOLD` — a held run cannot be closed and
    answers `ERR_RUN_ON_SPC_HOLD` (HTTP 409) — and its `process_status` must be
    `RUNNING`, otherwise `ERR_RUN_INVALID_STATE`."

    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest
    `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is
    refreshed to the lowest `ppk_value` across only those of the run's records whose
    `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."

    Design: Corner/state_machines/run_complete_while_on_spc_hold_rejected
    """
    world = X.running_run_world(api)
    held = X.record_spc_subgroup(
        api, world.run_id, world.characteristics[0], HOLDING_SUBGROUP
    )
    assert held["cpk_value"] == HOLDING_SUBGROUP_CPK, (
        f"the widened subgroup indexes at {HOLDING_SUBGROUP_CPK}, got "
        f"{held['cpk_value']}"
    )
    assert held["control_state"] == C.CONTROL_OUT_OF_CONTROL, (
        "the index is under the floor and one reading is below the lower limit, got "
        f"{held['control_state']}"
    )
    on_hold = X.refresh_run(api, world.run_id)
    assert on_hold["quality_status"] == C.QUALITY_SPC_HOLD, (
        "the characteristic is safety critical, so the run is escalated onto a hold, "
        f"got {on_hold['quality_status']}"
    )

    validate_error(
        api.complete_run(
            world.run_id,
            F.completion_payload(25_500, 500),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        ERR_RUN_ON_SPC_HOLD,
        expected_status=409,
    )

    run = X.refresh_run(api, world.run_id)
    assert run["process_status"] == C.PROCESS_RUNNING, (
        "completion reads the quality axis and refuses, leaving the process axis "
        f"where it was, got {run['process_status']}"
    )
    assert run["quality_status"] == C.QUALITY_SPC_HOLD, (
        f"the hold is still in force, got {run['quality_status']}"
    )
    assert run["min_cpk_observed"] == HOLDING_SUBGROUP_CPK, (
        "the run carries the lowest index any of its records reported, got "
        f"{run['min_cpk_observed']}"
    )


def test_an_out_of_control_subgroup_on_a_non_safety_characteristic_leaves_the_run_open(api):
    """PRD §3.7: "`sigma_value` is the Bessel-corrected sample standard deviation: take
    each measurement's deviation from the **unrounded** mean, square it, sum the squares,
    divide by one less than the subgroup size, take the square root, and round half up to
    six decimal places."

    PRD §3.7: "`control_state` is `OUT_OF_CONTROL` when the **rounded** `cpk_value` is
    below the characteristic's `cpk_floor`, or when any single measurement in the
    subgroup lies above `usl` or below `lsl`; it is `IN_CONTROL` otherwise."

    PRD §3.8: "An out-of-control record on a characteristic whose `is_safety_critical` is
    false records its control state and nothing more — the quality axis is untouched, no
    lot is quarantined, and no counter moves."

    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest
    `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is
    refreshed to the lowest `ppk_value` across only those of the run's records whose
    `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."

    Design: Corner/state_machines/non_safety_critical_out_of_control_subgroup_does_not_hold_the_run
    """
    world = X.build_world(api, "running", characteristics=[NON_SAFETY_DIAMETER_PLAN])
    characteristic = world.characteristics[0]
    assert characteristic["is_safety_critical"] is False, (
        "the design's only characteristic carries no safety weight, got "
        f"{characteristic['is_safety_critical']}"
    )

    recorded = validate_success(
        api.record_inspection(
            world.run_id,
            F.measurement_payload(characteristic["id"], WIDE_DIAMETER_SUBGROUP),
            QUALITY_INSPECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert recorded["sigma_value"] == WIDE_DIAMETER_SIGMA, (
        f"the subgroup's Bessel sigma is {WIDE_DIAMETER_SIGMA}, got "
        f"{recorded['sigma_value']}"
    )
    assert recorded["cpk_value"] == WIDE_DIAMETER_CPK, (
        f"the binding distance over three sigma indexes at {WIDE_DIAMETER_CPK}, got "
        f"{recorded['cpk_value']}"
    )
    assert recorded["control_state"] == C.CONTROL_OUT_OF_CONTROL, (
        "the index is under the floor and both outer readings are out of spec, got "
        f"{recorded['control_state']}"
    )

    run = X.refresh_run(api, world.run_id)
    assert run["quality_status"] == C.QUALITY_OPEN, (
        "the escalation is guarded on safety weight, so the quality axis never moves, "
        f"got {run['quality_status']}"
    )
    assert run["min_cpk_observed"] == WIDE_DIAMETER_CPK, (
        "the failing index is still the lowest the run has seen, got "
        f"{run['min_cpk_observed']}"
    )
    assert run["min_ppk_observed"] is None, (
        "the pooled figure only pools safety-critical in-process records, of which "
        f"this run has none, got {run['min_ppk_observed']}"
    )


def test_releasing_a_hold_returns_the_quality_axis_to_open(api):
    """PRD §3.8: "All three require the run's `quality_status` to be `SPC_HOLD`; a run
    that is `OPEN`, `DISPOSITIONED_ACCEPT` or `SCRAPPED` answers `ERR_RUN_NOT_ON_HOLD`
    (HTTP 409)."

    PRD §3.8: "`RELEASE` returns the run `SPC_HOLD → OPEN` and is the cyclic edge on the
    quality axis — a run can be held and released repeatedly over its life."

    PRD §3.8: "It requires evidence that the process has come back: for **every**
    safety-critical characteristic of the run's design, the newest inspection record by
    `created_at` must have a `control_state` of `IN_CONTROL`."

    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest
    `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is
    refreshed to the lowest `ppk_value` across only those of the run's records whose
    `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."

    Design: Corner/state_machines/spc_hold_release_returns_the_quality_axis_to_open
    """
    world = X.running_run_world(api)
    failing = X.record_spc_subgroup(
        api, world.run_id, world.characteristics[0], HOLDING_SUBGROUP
    )
    assert failing["control_state"] == C.CONTROL_OUT_OF_CONTROL, (
        f"the widened subgroup fails its floor, got {failing['control_state']}"
    )
    X.record_spc_subgroup(
        api, world.run_id, world.characteristics[0], C.IN_CONTROL_SUBGROUP
    )
    on_hold = X.refresh_run(api, world.run_id)
    assert on_hold["quality_status"] == C.QUALITY_SPC_HOLD, (
        "a later good subgroup does not lift the hold by itself, got "
        f"{on_hold['quality_status']}"
    )

    released = validate_success(
        api.quality_disposition(
            world.run_id, {"decision": C.DECISION_RELEASE}, QUALITY_INSPECTOR_HEADERS
        )
    )
    assert released["quality_status"] == C.QUALITY_OPEN, (
        "the newest record on the one safety-critical characteristic is back in "
        f"control, so the cyclic edge fires, got {released['quality_status']}"
    )
    assert released["process_status"] == C.PROCESS_RUNNING, (
        f"the process axis is untouched by a quality verdict, got "
        f"{released['process_status']}"
    )
    assert released["min_cpk_observed"] == HOLDING_SUBGROUP_CPK, (
        "the release does not rewrite the run's capability history, got "
        f"{released['min_cpk_observed']}"
    )

    history = validate_success(
        api.get_inspection_record(failing["id"], QUALITY_INSPECTOR_HEADERS)
    )
    assert history["control_state"] == C.CONTROL_OUT_OF_CONTROL, (
        "the record that caused the hold still reports what it measured, got "
        f"{history['control_state']}"
    )


def test_accept_as_is_closes_the_quality_axis_to_further_dispositions(api):
    """PRD §3.8: "`ACCEPT_AS_IS` records a concession instead and moves the run
    `SPC_HOLD → DISPOSITIONED_ACCEPT`, which is terminal on the quality axis; it carries
    the mirror-image requirement, namely that no safety-critical characteristic of the
    design has an `OUT_OF_CONTROL` newest record by `created_at`, and the same refusal
    when one does."

    PRD §3.8: "All three require the run's `quality_status` to be `SPC_HOLD`; a run that
    is `OPEN`, `DISPOSITIONED_ACCEPT` or `SCRAPPED` answers `ERR_RUN_NOT_ON_HOLD` (HTTP
    409)."

    Design: Corner/state_machines/spc_hold_accept_as_is_is_terminal_on_the_quality_axis
    """
    world = X.running_run_world(api)
    X.record_spc_subgroup(
        api, world.run_id, world.characteristics[0], HOLDING_SUBGROUP
    )
    X.record_spc_subgroup(
        api, world.run_id, world.characteristics[0], C.IN_CONTROL_SUBGROUP
    )

    conceded = validate_success(
        api.quality_disposition(
            world.run_id,
            {"decision": C.DECISION_ACCEPT_AS_IS},
            QUALITY_INSPECTOR_HEADERS,
        )
    )
    assert conceded["quality_status"] == C.QUALITY_DISPOSITIONED_ACCEPT, (
        "the concession takes the quality axis to its terminal accepted state, got "
        f"{conceded['quality_status']}"
    )

    validate_error(
        api.quality_disposition(
            world.run_id, {"decision": C.DECISION_RELEASE}, QUALITY_INSPECTOR_HEADERS
        ),
        ERR_RUN_NOT_ON_HOLD,
        expected_status=409,
    )

    run = X.refresh_run(api, world.run_id)
    assert run["quality_status"] == C.QUALITY_DISPOSITIONED_ACCEPT, (
        "there is no edge back out of the accepted state, got "
        f"{run['quality_status']}"
    )


def test_scrapping_a_complete_run_leaves_the_process_axis_and_the_ledger_alone(api):
    """PRD §3.8: "`SCRAP` is the write-off verdict and carries no evidence requirement at
    all — a run can always be scrapped."

    PRD §3.8: "It moves the run's `quality_status` to `SCRAPPED`."

    PRD §3.8: "If the run's `process_status` is still `FAI_PENDING` or `RUNNING`, that
    axis is driven to `CANCELLED` as well, which releases the wire reservation using the
    stored `wire_reserved_kg` verbatim and aborts the machine setup exactly as an
    ordinary run cancellation does, freeing the coiler back to `IDLE`."

    PRD §3.8: "Every shipment lot of the run still in `ALLOCATED` or `PACKED` transitions
    to `QUARANTINED` with `quarantine_reason` `SPC_HOLD_CASCADE`, and for each of those
    lots the owning program's `quarantined_lot_count` increases by 1, `allocated_pieces`
    decreases by the lot's `piece_count`, and `open_commitment_pieces` increases by that
    same `piece_count`, after which `delivery_posture` is re-derived."

    PRD §3.7: "The run's setup transitions `ACTIVE → RELEASED`, and the coiler returns
    `PRODUCTION → IDLE` with `active_setup_id` cleared and `version` increased by 1."

    PRD §3.1: "Otherwise, if `quarantined_lot_count` is at least 1 **or** such a held run
    exists, the posture is `AT_RISK`."

    Design: Corner/state_machines/scrap_disposition_on_a_complete_run_skips_the_cancel_branch
    """
    world = X.allocated_world(api)
    assert world.run["process_status"] == C.PROCESS_COMPLETE, (
        "the run was closed out before the lot was allocated, got "
        f"{world.run['process_status']}"
    )
    assert world.lot["lot_status"] == C.LOT_ALLOCATED, (
        f"one lot is on the books against this run, got {world.lot['lot_status']}"
    )

    X.record_spc_subgroup(
        api, world.run_id, world.characteristics[0], HOLDING_SUBGROUP
    )
    on_hold = X.refresh_run(api, world.run_id)
    assert on_hold["quality_status"] == C.QUALITY_SPC_HOLD, (
        "a post-completion in-process subgroup can still escalate the quality axis, "
        f"got {on_hold['quality_status']}"
    )
    cascaded = X.refresh_lot(api, world.lot_id)
    assert cascaded["lot_status"] == C.LOT_QUARANTINED, (
        f"the escalation quarantined the allocated lot, got {cascaded['lot_status']}"
    )

    scrapped = validate_success(
        api.quality_disposition(
            world.run_id, {"decision": C.DECISION_SCRAP}, QUALITY_INSPECTOR_HEADERS
        )
    )
    assert scrapped["quality_status"] == C.QUALITY_SCRAPPED, (
        f"the write-off verdict always lands, got {scrapped['quality_status']}"
    )
    assert scrapped["process_status"] == C.PROCESS_COMPLETE, (
        "the process axis is already past RUNNING, so the cancellation branch is "
        f"skipped, got {scrapped['process_status']}"
    )

    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    assert heat["consumed_kg"] == CONSUMED_KG, (
        "no reservation was released a second time, so the heat keeps what the "
        f"completion consumed, got {heat['consumed_kg']}"
    )
    assert heat["reserved_kg"] == 0.000, (
        f"the reserved bucket was emptied at completion, got {heat['reserved_kg']}"
    )
    assert heat["on_hand_kg"] == ON_HAND_AFTER_COMPLETION_KG, (
        "the on-hand figure the completion left is untouched by the scrap verdict, "
        f"got {heat['on_hand_kg']}"
    )
    A.assert_wire_ledger_conserved(heat)

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_RELEASED, (
        "the setup was released by the completion and is not aborted again, got "
        f"{setup['setup_status']}"
    )
    lot = X.refresh_lot(api, world.lot_id)
    assert lot["lot_status"] == C.LOT_QUARANTINED, (
        "the lot was already out of ALLOCATED when the verdict ran, got "
        f"{lot['lot_status']}"
    )
    program = X.refresh_program(api, world.program_id)
    assert program["quarantined_lot_count"] == 1, (
        "the one lot was counted once, by the escalation rather than by the verdict, "
        f"got {program['quarantined_lot_count']}"
    )
    assert program["delivery_posture"] == C.POSTURE_AT_RISK, (
        "a positive quarantine count keeps the program at risk, got "
        f"{program['delivery_posture']}"
    )
