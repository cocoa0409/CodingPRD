"""Composite setup helpers for the Medical Courier & Specimen Logistics API.

The harness restarts the server (empty database) before every test, so every
helper here builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls use the lenient get_success_data() validator, so a broken
precondition surfaces as a clear "Setup step failed" instead of a confusing
assertion error deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_driver_headers, make_lab_client_headers
from .factories import (
    create_rate_card_payload,
    create_lab_client_payload,
    create_driver_payload,
    create_vehicle_payload,
    create_route_template_payload,
    create_route_payload,
    create_stop_payload,
    create_specimen_payload,
    assign_route_payload,
    scan_payload,
    credential_payload,
    billing_payload,
)
from .constants import CLOCK_DURING_RUN, CLOCK_BEFORE_RUN

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Advance the server's logical clock (PRD §2.9)."""
    return get_success_data(api_client.set_clock(to_iso8601, DISPATCHER))


# ---------------------------------------------------------------------------
# Tier 0 — single-resource creation
# ---------------------------------------------------------------------------
def create_rate_card(**overrides) -> dict:
    return get_success_data(api_client.create_rate_card(create_rate_card_payload(**overrides), DISPATCHER))


def create_lab_client(**overrides) -> dict:
    return get_success_data(api_client.create_lab_client(create_lab_client_payload(**overrides), DISPATCHER))


def create_driver(**overrides) -> dict:
    return get_success_data(api_client.create_driver(create_driver_payload(**overrides), DISPATCHER))


def create_vehicle(**overrides) -> dict:
    return get_success_data(api_client.create_vehicle(create_vehicle_payload(**overrides), DISPATCHER))


def create_route(lab_client_id, rate_card_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_route(create_route_payload(lab_client_id, rate_card_id, **overrides), DISPATCHER)
    )


def add_stop(route_id, **overrides) -> dict:
    return get_success_data(api_client.add_stop(route_id, create_stop_payload(**overrides), DISPATCHER))


def add_specimen(route_id, pickup_stop_id, dropoff_stop_id, **overrides) -> dict:
    return get_success_data(
        api_client.add_specimen(
            route_id, create_specimen_payload(pickup_stop_id, dropoff_stop_id, **overrides), DISPATCHER
        )
    )


def create_route_template(lab_client_id, rate_card_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_route_template(
            create_route_template_payload(lab_client_id, rate_card_id, **overrides), DISPATCHER
        )
    )


def generate_route_from_template(template_id, **payload) -> dict:
    return get_success_data(api_client.generate_route(template_id, payload, DISPATCHER))


# ---------------------------------------------------------------------------
# Tier 1 — lifecycle transitions
# ---------------------------------------------------------------------------
def assign_route(route_id, driver_id, vehicle_id) -> dict:
    return get_success_data(
        api_client.assign_route(route_id, assign_route_payload(driver_id, vehicle_id), DISPATCHER)
    )


def unassign_route(route_id) -> dict:
    return get_success_data(api_client.unassign_route(route_id, DISPATCHER))


def dispatch_route(route_id) -> dict:
    return get_success_data(api_client.dispatch_route(route_id, DISPATCHER))


def complete_route(route_id) -> dict:
    return get_success_data(api_client.complete_route(route_id, DISPATCHER))


def scan(stop_id, specimen_id, scan_type, temp_reading_c, leg_miles, driver_id) -> dict:
    """Record a scan as the route's own assigned driver (ownership-gated, PRD §2.1)."""
    return get_success_data(
        api_client.scan_stop(
            stop_id,
            scan_payload(specimen_id, scan_type, temp_reading_c, leg_miles),
            make_driver_headers(driver_id),
        )
    )


def miss_stop(stop_id) -> dict:
    return get_success_data(api_client.miss_stop(stop_id, DISPATCHER))


def reschedule_stop(stop_id) -> dict:
    return get_success_data(api_client.reschedule_stop(stop_id, DISPATCHER))


def suspend_driver(driver_id) -> dict:
    return get_success_data(
        api_client.driver_credential(driver_id, credential_payload("SUSPEND"), COMPLIANCE)
    )


def create_billing(route_id, expected_route_version) -> dict:
    return get_success_data(
        api_client.create_billing(route_id, billing_payload(expected_route_version), DISPATCHER)
    )


def issue_billing(billing_id) -> dict:
    return get_success_data(api_client.issue_billing(billing_id, DISPATCHER))


def void_billing(billing_id) -> dict:
    return get_success_data(api_client.void_billing(billing_id, DISPATCHER))


# ---------------------------------------------------------------------------
# Reads (setup-time snapshots)
# ---------------------------------------------------------------------------
def get_route(route_id) -> dict:
    return get_success_data(api_client.get_route(route_id, DISPATCHER))


def get_stop(stop_id) -> dict:
    return get_success_data(api_client.get_stop(stop_id, DISPATCHER))


def get_specimen(specimen_id) -> dict:
    return get_success_data(api_client.get_specimen(specimen_id, DISPATCHER))


def get_vehicle(vehicle_id) -> dict:
    return get_success_data(api_client.get_vehicle(vehicle_id, DISPATCHER))


def get_lab_client(lab_client_id) -> dict:
    return get_success_data(api_client.get_lab_client(lab_client_id, DISPATCHER))


def get_billing(billing_id) -> dict:
    return get_success_data(api_client.get_billing(billing_id, DISPATCHER))


def list_exceptions(**params) -> list:
    body = api_client.list_exceptions(DISPATCHER, params=params)
    return get_success_data(body)


# ---------------------------------------------------------------------------
# Tier 2 — the canonical courier scenario
# ---------------------------------------------------------------------------
# The default manifest used by nearly every test: two stops (a PICKUP at
# sequence 1 with a 2.5-mile planned leg, a DROPOFF at sequence 2 with a
# 3.5-mile planned leg) carrying one REFRIGERATED BLOOD specimen whose
# acceptable band is [2, 8] degrees Celsius.
DEFAULT_STOPS = [
    {"sequence": 1, "address": "A", "stop_kind": "PICKUP", "planned_leg_miles": 2.5},
    {"sequence": 2, "address": "B", "stop_kind": "DROPOFF", "planned_leg_miles": 3.5},
]
DEFAULT_SPECIMENS = [
    {
        "pickup_index": 0,
        "dropoff_index": 1,
        "specimen_type": "BLOOD",
        "temp_requirement": "REFRIGERATED",
        "required_temp_min_c": 2,
        "required_temp_max_c": 8,
    }
]


def setup_scenario(
    clock=CLOCK_DURING_RUN,
    rate_card=None,
    lab=None,
    driver=None,
    vehicle=None,
    route=None,
    stops=DEFAULT_STOPS,
    specimens=DEFAULT_SPECIMENS,
    assign=False,
    dispatch=False,
) -> dict:
    """Build the reference network + one route manifest, optionally crewing and
    dispatching it.

    Returns a dict with keys: rate_card, lab, driver, vehicle, route, stops (list),
    specimens (list). Every argument accepts a dict of field overrides so tests can
    control exactly the values their claim depends on.
    """
    rc = create_rate_card(**(rate_card or {}))
    lb = create_lab_client(**(lab or {}))
    drv = create_driver(**(driver or {}))
    veh = create_vehicle(**(vehicle or {}))
    if clock is not None:
        set_clock(clock)

    rt = create_route(lb["id"], rc["id"], **(route or {}))

    stop_rows = [add_stop(rt["id"], **spec) for spec in (stops or [])]

    specimen_rows = []
    for spec in specimens or []:
        spec = dict(spec)
        pickup = stop_rows[spec.pop("pickup_index")]["id"]
        dropoff = stop_rows[spec.pop("dropoff_index")]["id"]
        specimen_rows.append(add_specimen(rt["id"], pickup, dropoff, **spec))

    if assign or dispatch:
        rt = assign_route(rt["id"], drv["id"], veh["id"])
    if dispatch:
        rt = dispatch_route(rt["id"])

    return {
        "rate_card": rc,
        "lab": lb,
        "driver": drv,
        "vehicle": veh,
        "route": rt,
        "stops": stop_rows,
        "specimens": specimen_rows,
    }


def setup_dispatched_route(**kwargs) -> dict:
    """The canonical two-stop, one-specimen route, crewed and DISPATCHED."""
    kwargs.setdefault("assign", True)
    kwargs["dispatch"] = True
    return setup_scenario(**kwargs)


def setup_served_route(pickup_temp=5.0, dropoff_temp=5.0, pickup_miles=2.5,
                       dropoff_miles=3.5, **kwargs) -> dict:
    """Dispatched route whose single specimen has been picked up at stop 1 and
    dropped off at stop 2 (both stops therefore served)."""
    ctx = setup_dispatched_route(**kwargs)
    spec = ctx["specimens"][0]
    scan(ctx["stops"][0]["id"], spec["id"], "PICKUP", pickup_temp, pickup_miles, ctx["driver"]["id"])
    scan(ctx["stops"][1]["id"], spec["id"], "DROPOFF", dropoff_temp, dropoff_miles, ctx["driver"]["id"])
    return ctx


def setup_completed_route(**kwargs) -> dict:
    """Served route driven through to COMPLETED. `route` in the returned dict is
    the completed route (its `version` is the one a billing create must echo)."""
    ctx = setup_served_route(**kwargs)
    ctx["route"] = complete_route(ctx["route"]["id"])
    return ctx


def setup_route_with_draft_billing(**kwargs) -> dict:
    """Completed route with a generated (DRAFT) RunBilling.

    Adds `billing` and `stale_route_version` (the route version the first billing
    create consumed — no longer current afterwards) to the scenario dict.
    """
    ctx = setup_completed_route(**kwargs)
    version_at_completion = ctx["route"]["version"]
    ctx["billing"] = create_billing(ctx["route"]["id"], version_at_completion)
    ctx["stale_route_version"] = version_at_completion
    return ctx


def setup_route_with_issued_billing(**kwargs) -> dict:
    """Completed route whose billing has been generated and ISSUED."""
    ctx = setup_route_with_draft_billing(**kwargs)
    ctx["billing"] = issue_billing(ctx["billing"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — missed stops and exceptions
# ---------------------------------------------------------------------------
def setup_missed_stop(**kwargs) -> dict:
    """Dispatched route whose PICKUP stop (index 0) has been marked missed.

    Adds `missed_stop` and `exceptions` (the exceptions opened for that stop).
    """
    ctx = setup_dispatched_route(**kwargs)
    ctx["missed_stop"] = miss_stop(ctx["stops"][0]["id"])
    ctx["exceptions"] = list_exceptions(stop_id=ctx["stops"][0]["id"])
    return ctx


def setup_two_specimen_route(**kwargs) -> dict:
    """Three-stop manifest (PICKUP, PICKUP, DROPOFF) carrying two AMBIENT
    specimens that share a dropoff stop — used for custody-bucket accounting."""
    kwargs.setdefault(
        "stops",
        [
            {"sequence": 1, "address": "A", "stop_kind": "PICKUP", "planned_leg_miles": 2.0},
            {"sequence": 2, "address": "B", "stop_kind": "PICKUP", "planned_leg_miles": 2.0},
            {"sequence": 3, "address": "C", "stop_kind": "DROPOFF", "planned_leg_miles": 2.0},
        ],
    )
    kwargs.setdefault(
        "specimens",
        [
            {
                "pickup_index": 0, "dropoff_index": 2, "specimen_type": "BLOOD",
                "temp_requirement": "AMBIENT", "required_temp_min_c": 15, "required_temp_max_c": 25,
            },
            {
                "pickup_index": 1, "dropoff_index": 2, "specimen_type": "URINE",
                "temp_requirement": "AMBIENT", "required_temp_min_c": 15, "required_temp_max_c": 25,
            },
        ],
    )
    return setup_dispatched_route(**kwargs)


# ---------------------------------------------------------------------------
# Tier 4 — multi-route resource-contention scenarios
# ---------------------------------------------------------------------------
def setup_vehicle_in_use_on_other_route() -> dict:
    """One vehicle held IN_USE by route 1; route 2 has a NON-overlapping window
    and its own driver, so only the vehicle's availability can block it."""
    rc = create_rate_card()
    lb = create_lab_client()
    d1 = create_driver(name="D1")
    d2 = create_driver(name="D2")
    veh = create_vehicle()
    set_clock("2026-05-01T00:00:00Z")

    rt1 = create_route(lb["id"], rc["id"],
                       scheduled_start="2026-05-05T09:00:00Z",
                       scheduled_end="2026-05-05T11:00:00Z")
    assign_route(rt1["id"], d1["id"], veh["id"])

    rt2 = create_route(lb["id"], rc["id"],
                       scheduled_start="2026-05-06T09:00:00Z",
                       scheduled_end="2026-05-06T11:00:00Z")
    return {"lab": lb, "rate_card": rc, "driver_1": d1, "driver_2": d2,
            "vehicle": veh, "route_1": rt1, "route_2": rt2}


def setup_driver_with_overlapping_route(
    credential_expiry="2026-12-31T00:00:00Z",
    clock_after_setup=None,
    route_2_start="2026-05-05T10:00:00Z",
    route_2_end="2026-05-05T12:00:00Z",
) -> dict:
    """One driver already crewed on route 1 [09:00, 11:00); route 2 defaults to
    [10:00, 12:00) — a true overlap — and has its own AVAILABLE vehicle, so only
    the driver's schedule (or credential) can block it. Pass `route_2_start` /
    `route_2_end` to build a non-overlapping (e.g. adjacent) window instead.

    `clock_after_setup` advances the clock once both routes exist — used to let a
    credential lapse between the two assignments.
    """
    rc = create_rate_card()
    lb = create_lab_client()
    drv = create_driver(credential_expiry=credential_expiry)
    veh1 = create_vehicle(plate="V1")
    veh2 = create_vehicle(plate="V2")
    set_clock("2026-05-01T00:00:00Z")

    rt1 = create_route(lb["id"], rc["id"],
                       scheduled_start="2026-05-05T09:00:00Z",
                       scheduled_end="2026-05-05T11:00:00Z")
    assign_route(rt1["id"], drv["id"], veh1["id"])

    rt2 = create_route(lb["id"], rc["id"],
                       scheduled_start=route_2_start,
                       scheduled_end=route_2_end)

    if clock_after_setup:
        set_clock(clock_after_setup)

    return {"lab": lb, "rate_card": rc, "driver": drv, "vehicle_1": veh1,
            "vehicle_2": veh2, "route_1": rt1, "route_2": rt2}


def setup_released_vehicle(release_clock="2026-05-05T12:00:00Z",
                           next_start="2026-05-05T12:15:00Z",
                           next_end="2026-05-05T14:00:00Z",
                           sanitation_buffer_minutes=30) -> dict:
    """Route 1 runs and completes at `release_clock`, freeing the vehicle and
    stamping its `last_released_at`. Route 2 is created (still PLANNED) with
    `next_start` and a second driver, ready to be assigned the same vehicle.
    """
    rc = create_rate_card()
    lb = create_lab_client()
    d1 = create_driver(name="D1")
    d2 = create_driver(name="D2")
    veh = create_vehicle(sanitation_buffer_minutes=sanitation_buffer_minutes)
    set_clock("2026-05-05T09:00:00Z")

    rt1 = create_route(lb["id"], rc["id"],
                       scheduled_start="2026-05-05T09:00:00Z",
                       scheduled_end="2026-05-05T11:00:00Z")
    s1 = add_stop(rt1["id"], sequence=1, address="A", stop_kind="PICKUP", planned_leg_miles=2.5)
    assign_route(rt1["id"], d1["id"], veh["id"])
    dispatch_route(rt1["id"])
    miss_stop(s1["id"])
    set_clock(release_clock)
    rt1 = complete_route(rt1["id"])

    rt2 = create_route(lb["id"], rc["id"],
                       scheduled_start=next_start, scheduled_end=next_end)
    return {"lab": lb, "rate_card": rc, "driver_1": d1, "driver_2": d2,
            "vehicle": veh, "route_1": rt1, "route_2": rt2}


# ---------------------------------------------------------------------------
# Tier 5 — templates
# ---------------------------------------------------------------------------
def setup_template(**overrides) -> dict:
    """Rate card + lab + a two-stop recurring route template."""
    rc = create_rate_card()
    lb = create_lab_client()
    tmpl = create_route_template(lb["id"], rc["id"], **overrides)
    return {"rate_card": rc, "lab": lb, "template": tmpl}


# ---------------------------------------------------------------------------
# Tier 6 — lab-owned (ownership-scoped) scenarios
# ---------------------------------------------------------------------------
def setup_two_labs_with_route_owned_by_first() -> dict:
    """Two laboratories; a route created by lab A under its own lab_client_id."""
    rc = create_rate_card()
    lab_a = create_lab_client(name="LabA")
    lab_b = create_lab_client(name="LabB")
    set_clock(CLOCK_BEFORE_RUN)
    route = get_success_data(
        api_client.create_route(
            create_route_payload(lab_a["id"], rc["id"]),
            make_lab_client_headers(lab_a["id"]),
        )
    )
    return {"rate_card": rc, "lab_a": lab_a, "lab_b": lab_b, "route": route}
