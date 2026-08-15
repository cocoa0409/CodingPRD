"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the
server before each test), so these helpers build complete precondition
chains out of PRD-declared endpoints only. Setup steps use the lenient
validator so a broken precondition surfaces as a clear "Setup failed".

Segregation-of-duties threading: safety configurations are created by
"planner-1" and approved by "so-1"; evaluations are certified by "so-2"
(distinct from the config approver, as certification requires).
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_DEFAULT_ISO,
    DEFAULT_AUTH_WINDOW_END,
    DEFAULT_AUTH_WINDOW_START,
    DEFAULT_READING_AT,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    IN_WINDOW_CLOCK,
    PRE_SHOW_EVAL_CLOCK,
)
from .factories import (
    create_authorization_payload,
    create_charge_bay_payload,
    create_charge_session_payload,
    create_drone_payload,
    create_flight_log_payload,
    create_go_no_go_evaluation_payload,
    create_incident_report_payload,
    create_launch_grid_assignment_payload,
    create_safety_configuration_payload,
    create_show_design_payload,
    create_show_event_payload,
    create_simulation_run_payload,
    create_site_payload,
    create_weather_reading_payload,
)
from .test_users import (
    TEST_USERS,
    make_authority_headers,
    make_fleet_manager_headers,
    make_ops_admin_headers,
    make_planner_headers,
    make_safety_officer_headers,
)

PLANNER = TEST_USERS["planner_headers"]
AUTHORITY = TEST_USERS["authority_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
SAFETY_2 = TEST_USERS["safety_officer_2_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]
OPS = TEST_USERS["ops_admin_headers"]

_serial_counter = itertools.count(1)


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and atomic transitions
# ---------------------------------------------------------------------------

def create_site(**overrides) -> dict:
    """Create a venue site. Returns the site."""
    return get_success_data(
        api_client.create_site(create_site_payload(**overrides), PLANNER))


def set_clock(to_iso8601=CLOCK_DEFAULT_ISO) -> dict:
    """Set the server's logical clock. Returns {current_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


def create_show(site_id, **overrides) -> dict:
    """Book a show (PLANNING / DEPOSIT_DUE, pricing computed). Returns the show."""
    return get_success_data(
        api_client.create_show_event(create_show_event_payload(site_id, **overrides),
                                     PLANNER))


def get_show(show_id) -> dict:
    return get_success_data(api_client.get_show_event(show_id, PLANNER))


def create_design(show_id, **overrides) -> dict:
    """Create a design revision (DRAFT). Returns the design."""
    return get_success_data(
        api_client.create_show_design(create_show_design_payload(show_id, **overrides),
                                      PLANNER))


def record_simulation(design_id, **overrides) -> dict:
    """Record a simulation run (verdict computed). Returns the run."""
    return get_success_data(
        api_client.create_simulation_run(
            create_simulation_run_payload(design_id, **overrides), PLANNER))


def lock_design(show_id, design_id) -> dict:
    """Lock a SIMULATED design, threading the show's current version (OCC).
    Returns the lock response (the LOCKED design)."""
    show = get_show(show_id)
    return get_success_data(
        api_client.lock_design(
            design_id, {"expected_show_event_version": show["version"]}, PLANNER))


def create_safety_config(show_id, creator_user_id="planner-1", **overrides) -> dict:
    """Create a safety configuration (DRAFT), threading the show's current
    version (OCC). The creator's user id is recorded as created_by_user_id."""
    show = get_show(show_id)
    payload = create_safety_configuration_payload(show_id, show["version"], **overrides)
    return get_success_data(
        api_client.create_safety_configuration(
            payload, make_planner_headers(creator_user_id)))


def approve_safety_config(config_id, approver_user_id="so-1") -> dict:
    """Approve a DRAFT configuration (SafetyOfficer, segregated from creator)."""
    return get_success_data(
        api_client.approve_safety_configuration(
            config_id, make_safety_officer_headers(approver_user_id)))


def create_authorization(show_id, **overrides) -> dict:
    """File an authorization application (DRAFT). Returns the authorization."""
    return get_success_data(
        api_client.create_authorization(
            create_authorization_payload(show_id, **overrides), PLANNER))


def submit_authorization(authorization_id) -> dict:
    return get_success_data(api_client.submit_authorization(authorization_id, PLANNER))


def decide_authorization(authorization_id, decision="APPROVED",
                         officer_user_id="ao-1") -> dict:
    return get_success_data(
        api_client.decide_authorization(authorization_id, {"decision": decision},
                                        make_authority_headers(officer_user_id)))


def authorize_show(show_id, authorization_id) -> dict:
    return get_success_data(
        api_client.authorize_show(show_id, {"authorization_id": authorization_id},
                                  PLANNER))


def pay_show_in_full(show_id) -> dict:
    """Record DEPOSIT then BALANCE at the exact server-computed amounts.
    Returns the final (PAID_IN_FULL) show."""
    show = get_show(show_id)
    get_success_data(
        api_client.record_payment(
            show_id, {"kind": "DEPOSIT", "amount_cents": show["deposit_cents"]},
            PLANNER))
    return get_success_data(
        api_client.record_payment(
            show_id, {"kind": "BALANCE", "amount_cents": show["balance_cents"]},
            PLANNER))


def register_drone(serial_number=None, **overrides) -> dict:
    """Register a drone (AVAILABLE; charge_pct defaults to 100). Returns it."""
    serial = serial_number or f"SN-AUTO-{next(_serial_counter):04d}"
    return get_success_data(
        api_client.create_drone(create_drone_payload(serial, **overrides), FLEET))


def create_charge_bay(site_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_charge_bay(create_charge_bay_payload(site_id, **overrides),
                                     FLEET))


def start_charge_session(drone_id, charge_bay_id) -> dict:
    return get_success_data(
        api_client.create_charge_session(
            create_charge_session_payload(drone_id, charge_bay_id), FLEET))


def assign_drone(show_id, drone_id, grid_row, grid_col) -> dict:
    """Assign a drone to a grid slot. Returns the assignment."""
    return get_success_data(
        api_client.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(show_id, drone_id, grid_row,
                                                  grid_col),
            FLEET))


def post_weather(site_id, **overrides) -> dict:
    """Record a weather observation (SafetyOfficer). Returns the reading."""
    return get_success_data(
        api_client.create_weather_reading(
            create_weather_reading_payload(site_id, **overrides), SAFETY))


def create_evaluation(show_id, officer_user_id="so-1") -> dict:
    """Compute a go/no-go evaluation (PROVISIONAL). Returns the evaluation."""
    return get_success_data(
        api_client.create_go_no_go_evaluation(
            create_go_no_go_evaluation_payload(show_id),
            make_safety_officer_headers(officer_user_id)))


def certify_evaluation(evaluation_id, officer_user_id="so-2") -> dict:
    """Certify a PROVISIONAL evaluation (segregated from the pinned
    configuration's approver)."""
    return get_success_data(
        api_client.certify_go_no_go_evaluation(
            evaluation_id, make_safety_officer_headers(officer_user_id)))


def certify_show_go(show_id, evaluation_id, officer_user_id="so-2") -> dict:
    return get_success_data(
        api_client.certify_go(show_id, {"evaluation_id": evaluation_id},
                              make_safety_officer_headers(officer_user_id)))


def post_flight_log(show_id, drone_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_flight_log(
            create_flight_log_payload(show_id, drone_id, **overrides), FLEET))


def file_incident(show_id, filer_user_id="so-1", **overrides) -> dict:
    return get_success_data(
        api_client.create_incident_report(
            create_incident_report_payload(show_id, **overrides),
            make_safety_officer_headers(filer_user_id)))


# ---------------------------------------------------------------------------
# Tier 2/3: lifecycle composites
# ---------------------------------------------------------------------------

def setup_show_with_locked_design(site_overrides=None, show_overrides=None,
                                  design_overrides=None, sim_overrides=None) -> dict:
    """Site + show + design + one PASS simulation + lock.

    Returns dict(site, show, design, sim) with the show in DESIGN_LOCKED.
    """
    site = create_site(**(site_overrides or {}))
    set_clock()
    show = create_show(site["id"], **(show_overrides or {}))
    design = create_design(show["id"], **(design_overrides or {}))
    sim = record_simulation(design["id"], **(sim_overrides or {}))
    lock_design(show["id"], design["id"])
    return {"site": site, "show": get_show(show["id"]), "design": design, "sim": sim}


def setup_authorized_show(site_overrides=None, show_overrides=None,
                          design_overrides=None, sim_overrides=None,
                          config_overrides=None, auth_overrides=None) -> dict:
    """Full chain through authorize: locked design + APPROVED safety
    configuration + APPROVED authorization pinned. Show is AUTHORIZED.

    Returns dict(site, show, design, sim, config, auth).
    """
    ctx = setup_show_with_locked_design(site_overrides, show_overrides,
                                        design_overrides, sim_overrides)
    show = ctx["show"]
    config = create_safety_config(show["id"], **(config_overrides or {}))
    approve_safety_config(config["id"])
    auth = create_authorization(show["id"], **(auth_overrides or {}))
    submit_authorization(auth["id"])
    decide_authorization(auth["id"], "APPROVED")
    authorize_show(show["id"], auth["id"])
    ctx.update({"config": config, "auth": auth, "show": get_show(show["id"])})
    return ctx


def setup_ready_show(drone_count=None, site_overrides=None, show_overrides=None,
                     design_overrides=None, sim_overrides=None,
                     config_overrides=None, auth_overrides=None) -> dict:
    """AUTHORIZED show with the launch grid fully populated -> READY.

    The design's drone_count drives the grid size. Returns the authorized
    context plus drones and assignments.
    """
    ctx = setup_authorized_show(site_overrides, show_overrides, design_overrides,
                                sim_overrides, config_overrides, auth_overrides)
    show = ctx["show"]
    design = ctx["design"]
    needed = drone_count if drone_count is not None else design["drone_count"]
    drones = [register_drone() for _ in range(needed)]
    assignments = []
    for i, drone in enumerate(drones):
        assignments.append(
            assign_drone(show["id"], drone["id"], grid_row=i // 10,
                         grid_col=i % 10))
    ctx.update({"drones": drones, "assignments": assignments,
                "show": get_show(show["id"])})
    return ctx


def setup_go_certified_show(weather_overrides=None, eval_clock=PRE_SHOW_EVAL_CLOCK,
                            reading_at=DEFAULT_READING_AT, **kwargs) -> dict:
    """READY show + favorable weather + CERTIFIED GO evaluation + certify-go.

    Returns the ready context plus weather and evaluation. Show is
    GO_CERTIFIED with readiness_posture GO.
    """
    ctx = setup_ready_show(**kwargs)
    site = ctx["site"]
    show = ctx["show"]
    set_clock(eval_clock)
    reading_payload = {"recorded_at": reading_at}
    if weather_overrides:
        reading_payload.update(weather_overrides)
    weather = post_weather(site["id"], **reading_payload)
    evaluation = create_evaluation(show["id"])
    certify_evaluation(evaluation["id"])
    certify_show_go(show["id"], evaluation["id"])
    ctx.update({"weather": weather, "evaluation": evaluation,
                "show": get_show(show["id"])})
    return ctx


def setup_executed_show(with_flight_logs=False, battery_consumed_pct=30,
                        max_altitude_reached_ft=195, max_deviation_m=1.0,
                        execute_clock=IN_WINDOW_CLOCK, **kwargs) -> dict:
    """Full lifecycle through EXECUTED: GO_CERTIFIED + PAID_IN_FULL, then
    execute inside the window. Optionally uploads one flight log per flown
    drone. Returns the go-certified context plus flight_logs.
    """
    ctx = setup_go_certified_show(**kwargs)
    show = ctx["show"]
    pay_show_in_full(show["id"])
    set_clock(execute_clock)
    get_success_data(api_client.execute_show(show["id"], PLANNER))
    flight_logs = []
    if with_flight_logs:
        for drone in ctx["drones"]:
            flight_logs.append(
                post_flight_log(show["id"], drone["id"],
                                battery_consumed_pct=battery_consumed_pct,
                                max_altitude_reached_ft=max_altitude_reached_ft,
                                max_deviation_m=max_deviation_m))
    ctx.update({"flight_logs": flight_logs, "show": get_show(show["id"])})
    return ctx
