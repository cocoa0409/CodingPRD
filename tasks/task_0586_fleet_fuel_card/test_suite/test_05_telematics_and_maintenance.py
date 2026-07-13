"""Telematics faults: buffered maintenance windows and the out-of-service cascade."""
from test_helpers import (
    GATEWAY,
    ApiErrorId,
    assert_instant_equals,
    assert_telematics_fault,
    create_card_assignment_payload,
    create_telematics_fault_payload,
    make_critical_fault,
    make_vehicle,
    read_assignment,
    read_vehicle,
    setup_fueling_scenario,
    validate_error,
    validate_success,
)

CLOCK = "2026-06-01T12:00:00Z"
WINDOW_START = "2026-06-02T08:00:00Z"
WINDOW_END = "2026-06-02T12:00:00Z"


# --------------------------------------------------------------------------- #
# TelematicsFault -> Vehicle -> CardAssignment
# --------------------------------------------------------------------------- #

def test_critical_fault_schedules_maintenance_and_ends_assignments(api):
    """PRD §3.7: "When these hold, the critical fault auto-transitions from `OPEN`
    to `MAINTENANCE_SCHEDULED`, and as the origin of a cascade transitions the
    `Vehicle` from `ACTIVE` to `OUT_OF_SERVICE`, which in turn ends every `ACTIVE`
    card assignment on that vehicle."

    Design: Difficulty/transitive_cascade/critical_fault_cascades_vehicle_assignment_depth2
    """
    scenario = setup_fueling_scenario(
        api, clock=CLOCK,
        account_overrides={"company_name": "Telem Fleet"},
        vehicle_overrides={"expected_mpg_min": 3, "expected_mpg_max": 12},
        card_overrides={"last4": "8888"},
    )
    vehicle_id = scenario["vehicle"]["id"]

    payload = create_telematics_fault_payload(
        vehicle_id, fault_code="P0301", severity="CRITICAL",
        maintenance_window_start=WINDOW_START, maintenance_window_end=WINDOW_END,
    )
    fault = validate_success(api.create_telematics_fault(payload, GATEWAY), 201)

    assert_telematics_fault(fault)
    assert fault["status"] == "MAINTENANCE_SCHEDULED", "link 1: the critical fault schedules maintenance"

    vehicle = read_vehicle(api, scenario["account"]["id"], vehicle_id)
    assert vehicle["status"] == "OUT_OF_SERVICE", "link 2: the vehicle goes out of service"

    assignment = read_assignment(api, scenario["account"]["id"], scenario["assignment"]["id"])
    assert assignment["status"] == "ENDED", "link 3: the vehicle's ACTIVE assignment ends"


def test_cascade_ended_assignment_backfills_effective_to_from_the_clock(api):
    """PRD §3.3: "Assignments also end automatically as a cascade side effect when
    their vehicle goes `OUT_OF_SERVICE` or is retired, or when their card is
    cancelled — the same `ACTIVE → ENDED` transition, with the same
    null-`effective_to` backfill."
    PRD §3.3: "A `FleetManager` may end an `ACTIVE` assignment directly, moving it
    to `ENDED`; if its `effective_to` was null, ending it stamps `effective_to` with
    the current logical-clock value."

    Design: Difficulty/transitive_cascade/critical_fault_cascades_vehicle_assignment_depth2
    """
    scenario = setup_fueling_scenario(
        api, clock=CLOCK,
        account_overrides={"company_name": "Telem Fleet"},
        card_overrides={"last4": "8888"},
    )
    assert scenario["assignment"]["effective_to"] is None, "the assignment is open-ended"

    make_critical_fault(api, scenario["vehicle"]["id"], WINDOW_START, WINDOW_END,
                        fault_code="P0301")

    assignment = read_assignment(api, scenario["account"]["id"], scenario["assignment"]["id"])
    assert assignment["status"] == "ENDED"
    assert assignment["effective_to"] is not None, "the null effective_to is backfilled"
    assert_instant_equals(assignment["effective_to"], CLOCK, "effective_to")


# --------------------------------------------------------------------------- #
# Buffered, closed maintenance-window collision on the same vehicle
# --------------------------------------------------------------------------- #

def test_maintenance_window_within_buffer_collides(api):
    """PRD §3.7: "The window, expanded by the maintenance buffer of 2 hours
    (`MAINTENANCE_BUFFER_HOURS`) on both sides, must not intersect any other
    non-`CLEARED` fault window on the same vehicle; because the comparison is
    buffered and closed, windows that touch within the buffer collide and are
    rejected with `ERR_MAINTENANCE_OVERLAP`."

    The second window starts a full hour after the first one ends, yet the 2-hour
    padding on both sides makes them intersect.

    Design: Difficulty/resource_temporal_overlap/maintenance_window_buffered_overlap
    """
    scenario = setup_fueling_scenario(
        api, clock=CLOCK,
        account_overrides={"company_name": "Maint Fleet"},
        create_assignment=False,
    )
    make_critical_fault(
        api, scenario["vehicle"]["id"], "2026-06-02T08:00:00Z", "2026-06-02T10:00:00Z",
        fault_code="P0420",
    )

    payload = create_telematics_fault_payload(
        scenario["vehicle"]["id"], fault_code="P0300", severity="CRITICAL",
        maintenance_window_start="2026-06-02T11:00:00Z",
        maintenance_window_end="2026-06-02T13:00:00Z",
    )
    resp = api.create_telematics_fault(payload, GATEWAY)

    validate_error(resp, ApiErrorId.ERR_MAINTENANCE_OVERLAP.value)


def test_maintenance_window_collision_is_scoped_to_one_vehicle(api):
    """PRD §3.7: "The window, expanded by the maintenance buffer of 2 hours
    (`MAINTENANCE_BUFFER_HOURS`) on both sides, must not intersect any other
    non-`CLEARED` fault window on the same vehicle; because the comparison is
    buffered and closed, windows that touch within the buffer collide and are
    rejected with `ERR_MAINTENANCE_OVERLAP`."

    The very window that collides on the first vehicle is accepted on a second
    vehicle: the collision check is scoped to the same vehicle.

    Design: Difficulty/resource_temporal_overlap/maintenance_window_buffered_overlap
    """
    scenario = setup_fueling_scenario(
        api, clock=CLOCK,
        account_overrides={"company_name": "Maint Fleet"},
        create_assignment=False,
    )
    other_vehicle = make_vehicle(api, scenario["account"]["id"], plate="VC2")
    make_critical_fault(
        api, scenario["vehicle"]["id"], "2026-06-02T08:00:00Z", "2026-06-02T10:00:00Z",
        fault_code="P0420",
    )

    payload = create_telematics_fault_payload(
        other_vehicle["id"], fault_code="P0300", severity="CRITICAL",
        maintenance_window_start="2026-06-02T11:00:00Z",
        maintenance_window_end="2026-06-02T13:00:00Z",
    )
    fault = validate_success(api.create_telematics_fault(payload, GATEWAY), 201)

    assert_telematics_fault(fault)
    assert fault["status"] == "MAINTENANCE_SCHEDULED"
    assert read_vehicle(api, scenario["account"]["id"], other_vehicle["id"])["status"] == \
        "OUT_OF_SERVICE"


# --------------------------------------------------------------------------- #
# Critical-fault preconditions and the downstream assignment guard
# --------------------------------------------------------------------------- #

def test_critical_fault_without_maintenance_window_rejected(api):
    """PRD §3.7: "It requires both `maintenance_window_start` and
    `maintenance_window_end`, else `ERR_MISSING_MAINTENANCE_WINDOW`."

    Design: Corner/validations/critical_fault_missing_window_rejected
    """
    scenario = setup_fueling_scenario(
        api, clock=None,
        account_overrides={"company_name": "NoWin Co"},
        create_assignment=False,
    )

    payload = create_telematics_fault_payload(
        scenario["vehicle"]["id"], fault_code="P0500", severity="CRITICAL",
    )
    resp = api.create_telematics_fault(payload, GATEWAY)

    validate_error(resp, ApiErrorId.ERR_MISSING_MAINTENANCE_WINDOW.value)


def test_assignment_on_out_of_service_vehicle_rejected(api):
    """PRD §3.3: "The named vehicle must be `ACTIVE`, else
    `ERR_VEHICLE_OUT_OF_SERVICE`."

    Design: Corner/validations/assignment_on_out_of_service_vehicle_rejected
    """
    scenario = setup_fueling_scenario(
        api, clock=CLOCK,
        account_overrides={"company_name": "Oos Co"},
        card_overrides={"last4": "0704", "daily_dollar_limit_cents": 100_000,
                        "per_txn_gallon_limit": 100},
        create_assignment=False,
    )
    make_critical_fault(
        api, scenario["vehicle"]["id"], WINDOW_START, "2026-06-02T10:00:00Z",
        fault_code="P0600",
    )
    assert read_vehicle(api, scenario["account"]["id"],
                        scenario["vehicle"]["id"])["status"] == "OUT_OF_SERVICE"

    payload = create_card_assignment_payload(
        scenario["card"]["id"], scenario["vehicle"]["id"], scenario["driver"]["id"],
        scenario["card"]["version"], effective_from="2026-06-05T00:00:00Z",
    )
    resp = api.create_card_assignment(payload, scenario["fm"])

    validate_error(resp, ApiErrorId.ERR_VEHICLE_OUT_OF_SERVICE.value)
