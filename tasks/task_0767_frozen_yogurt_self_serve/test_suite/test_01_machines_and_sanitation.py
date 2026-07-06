"""Machine lifecycle, the cleaning cycle, and sanitation cadence cascades."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_machine_payload, add_line_payload,
    setup_machine_out_of_service, make_machine, make_flavor, make_ticket,
    set_clock, CLOCK_DEFAULT, CLOCK_FAR_FUTURE,
)

MANAGER = TEST_USERS["manager_headers"]
SHIFTLEAD = TEST_USERS["shiftlead_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def test_create_machine_defaults_mix_to_par(api):
    """PRD §3.1: "An optional `initial_mix_oz` seeds the starting
    `current_mix_level_oz`; when omitted, the machine starts full at `mix_par_oz`."
    PRD §3.1: "On creation the machine's `sanitation_status` is `READY`, its
    `last_cleaned_at` is stamped to the current clock, and `next_maintenance_at`
    is `null` until a maintenance window is scheduled."

    Design: Corner/entities/create_machine_defaults_mix_to_par
    """
    resp = api.create_machine(create_machine_payload(name="Barrel-A", mix_par_oz=800), MANAGER)
    data = validate_success(resp, expected_status=201)
    assert data["current_mix_level_oz"] == 800, \
        f"omitting initial_mix_oz must default current_mix_level_oz to mix_par_oz 800, got {data['current_mix_level_oz']}"
    assert data["sanitation_status"] == "READY"


def test_cleaning_cycle_returns_machine_to_ready(api):
    """PRD §3.1: "Completing a cleaning cycle requires the machine to be
    `CLEANING` (otherwise `ERR_MACHINE_INVALID_STATE`) and drives it back to
    `READY`."

    Design: Difficulty/non_linear_state_machine/machine_cyclic_ready_cleaning_ready
    """
    machine = make_machine(api, mix_par_oz=1000)
    validate_success(api.start_cleaning(machine["id"], SHIFTLEAD))
    data = validate_success(api.complete_cleaning(machine["id"], SHIFTLEAD))
    assert data["sanitation_status"] == "READY", \
        f"machine must cycle back to READY after complete-cleaning, got {data['sanitation_status']}"


def test_cleaning_cycle_appends_exactly_one_sanitation_log(api):
    """PRD §3.1: "Completion has three side effects committed together: a
    `SanitationLog` entry is appended recording `machine_id`, `cleaned_at` set to
    the current clock, and `previous_status` of `CLEANING`; the machine's
    `last_cleaned_at` is set to the current clock; and every flavor on that
    machine currently `SUSPENDED` cascades to `LOADED`."

    Design: Difficulty/non_linear_state_machine/machine_cyclic_ready_cleaning_ready
    """
    machine = make_machine(api, mix_par_oz=1000)
    validate_success(api.start_cleaning(machine["id"], SHIFTLEAD))
    validate_success(api.complete_cleaning(machine["id"], SHIFTLEAD))
    logs, meta = validate_paginated(api.list_sanitation_logs(SHIFTLEAD, params={"machine_id": machine["id"]}))
    assert len(logs) == 1, f"one complete-cleaning must append exactly one SanitationLog, got {len(logs)}"
    assert logs[0]["machine_id"] == machine["id"]
    assert logs[0]["previous_status"] == "CLEANING"


def test_overdue_machine_transitions_to_out_of_service(api):
    """PRD §3.1: "When an overdue machine is still `READY`, the system
    transitions it from `READY` to `OUT_OF_SERVICE` and cascades every `LOADED`
    flavor on it to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/machine_oos_suspends_flavors
    """
    machine, _flavors = setup_machine_out_of_service(api, num_flavors=2)
    assert machine["sanitation_status"] == "OUT_OF_SERVICE", \
        f"an overdue READY machine must flip to OUT_OF_SERVICE, got {machine['sanitation_status']}"


def test_out_of_service_cascade_suspends_all_loaded_flavors(api):
    """PRD §3.1: "When an overdue machine is still `READY`, the system
    transitions it from `READY` to `OUT_OF_SERVICE` and cascades every `LOADED`
    flavor on it to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/machine_oos_suspends_flavors
    """
    machine, flavors = setup_machine_out_of_service(api, num_flavors=2)
    for fl in flavors:
        got = validate_success(api.get_flavor(fl["id"], SHIFTLEAD))
        assert got["status"] == "SUSPENDED", \
            f"every LOADED flavor on the machine must cascade to SUSPENDED, got {got['status']}"


def test_addline_rejected_when_machine_out_of_service(api):
    """PRD §3.4: "the flavor's parent machine is re-evaluated for overdue
    sanitation (potentially flipping it to `OUT_OF_SERVICE` and suspending its
    flavors per §3.1), and the machine must be `READY` to dispense — a machine
    that is `CLEANING` or `OUT_OF_SERVICE` yields `ERR_MACHINE_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/addline_requires_machine_ready
    """
    machine, flavors = setup_machine_out_of_service(api, num_flavors=1)
    ticket = make_ticket(api)
    resp = api.add_line(ticket["id"], add_line_payload(flavors[0]["id"], 5.0), CASHIER)
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_READY.value)


def test_addline_rejected_out_of_service_creates_no_line(api):
    """PRD §3.4: "the flavor's parent machine is re-evaluated for overdue
    sanitation (potentially flipping it to `OUT_OF_SERVICE` and suspending its
    flavors per §3.1), and the machine must be `READY` to dispense — a machine
    that is `CLEANING` or `OUT_OF_SERVICE` yields `ERR_MACHINE_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/addline_requires_machine_ready
    """
    machine, flavors = setup_machine_out_of_service(api, num_flavors=1)
    ticket = make_ticket(api)
    resp = api.add_line(ticket["id"], add_line_payload(flavors[0]["id"], 5.0), CASHIER)
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_READY.value)
    lines, meta = validate_paginated(api.list_lines(ticket["id"], CASHIER))
    assert len(lines) == 0, f"a rejected dispense must not append a line, got {len(lines)}"


def test_complete_cleaning_on_ready_machine_rejected(api):
    """PRD §3.1: "Completing a cleaning cycle requires the machine to be
    `CLEANING` (otherwise `ERR_MACHINE_INVALID_STATE`) and drives it back to
    `READY`."

    Design: Corner/state_machines/complete_cleaning_from_ready_rejected
    """
    machine = make_machine(api, mix_par_oz=1000)
    resp = api.complete_cleaning(machine["id"], SHIFTLEAD)
    validate_error(resp, ApiErrorId.ERR_MACHINE_INVALID_STATE.value)


def test_addline_rejected_when_machine_cleaning(api):
    """PRD §3.4: "the flavor's parent machine is re-evaluated for overdue
    sanitation (potentially flipping it to `OUT_OF_SERVICE` and suspending its
    flavors per §3.1), and the machine must be `READY` to dispense — a machine
    that is `CLEANING` or `OUT_OF_SERVICE` yields `ERR_MACHINE_NOT_READY`."

    Design: Corner/state_machines/addline_machine_cleaning_rejected
    """
    machine = make_machine(api, mix_par_oz=1000, initial_mix_oz=1000)
    flavor = make_flavor(api, machine["id"])
    validate_success(api.start_cleaning(machine["id"], SHIFTLEAD))
    ticket = make_ticket(api)
    resp = api.add_line(ticket["id"], add_line_payload(flavor["id"], 5.0), CASHIER)
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_READY.value)


def test_complete_cleaning_restores_suspended_flavor(api):
    """PRD §3.1: "Completion has three side effects committed together: a
    `SanitationLog` entry is appended recording `machine_id`, `cleaned_at` set to
    the current clock, and `previous_status` of `CLEANING`; the machine's
    `last_cleaned_at` is set to the current clock; and every flavor on that
    machine currently `SUSPENDED` cascades to `LOADED`."

    Design: Corner/state_machines/complete_cleaning_restores_suspended_flavor
    """
    machine, flavors = setup_machine_out_of_service(api, num_flavors=1)
    flavor = flavors[0]
    validate_success(api.start_cleaning(machine["id"], SHIFTLEAD))
    data = validate_success(api.complete_cleaning(machine["id"], SHIFTLEAD))
    assert data["sanitation_status"] == "READY"
    got = validate_success(api.get_flavor(flavor["id"], SHIFTLEAD))
    assert got["status"] == "LOADED", \
        f"a SUSPENDED flavor must cascade back to LOADED on complete-cleaning, got {got['status']}"
