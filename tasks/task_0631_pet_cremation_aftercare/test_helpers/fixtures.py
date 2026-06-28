"""Composite setup helpers for the Pet Cremation & Aftercare API.

Most testable claims require the system to be driven through a multi-step custody and
firing lifecycle before the rule under test is reachable. These helpers encapsulate
those preambles so test bodies focus on the trigger + assertions.

The runner kills and relaunches the server before every test, so every helper builds
all of its preconditions from scratch using only PRD-declared endpoints. Setup calls
use the lenient get_success_data() validator so a broken precondition surfaces as a
clear "Setup failed" rather than a confusing assertion deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_clinic_payload, create_petowner_payload, create_cooler_payload,
    create_retort_payload, create_batch_payload, create_case_payload,
    create_transport_leg_payload, create_ready_return_payload,
)
from .test_users import TEST_USERS, make_pet_owner_headers

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# --------------------------------------------------------------------------- #
# Tier 0: clock + standing resources
# --------------------------------------------------------------------------- #
def set_clock(iso8601: str):
    """Advance the admin-only logical clock to a known instant."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


def create_clinic(credit_limit_cents=None, **overrides):
    payload = create_clinic_payload(**overrides)
    if credit_limit_cents is not None:
        payload["credit_limit_cents"] = credit_limit_cents
    return get_success_data(api_client.create_clinic(payload, ADMIN))


def create_owner(**overrides):
    return get_success_data(api_client.create_petowner(
        create_petowner_payload(**overrides), OPERATOR))


def create_cooler(total_capacity=3, **overrides):
    return get_success_data(api_client.create_cooler(
        create_cooler_payload(total_capacity=total_capacity, **overrides), ADMIN))


def create_retort(max_load_lbs=400, **overrides):
    return get_success_data(api_client.create_retort(
        create_retort_payload(max_load_lbs=max_load_lbs, **overrides), ADMIN))


def create_batch(retort_id, service_type="PRIVATE",
                 scheduled_start="2026-03-01T08:00:00Z",
                 scheduled_end="2026-03-01T10:00:00Z"):
    return get_success_data(api_client.create_batch(
        create_batch_payload(retort_id, service_type=service_type,
                             scheduled_start=scheduled_start,
                             scheduled_end=scheduled_end), OPERATOR))


# --------------------------------------------------------------------------- #
# Tier 1: case state progression
# --------------------------------------------------------------------------- #
def create_case(owner_id, clinic_id=None, **overrides):
    """Create an intake case (custody INTAKE_PENDING)."""
    payload = create_case_payload(owner_id, **overrides)
    if clinic_id is not None:
        payload["clinic_id"] = clinic_id
    return get_success_data(api_client.create_case(payload, OPERATOR))


def drive_case_to_received(case_id, origin_kind="HOME", origin_label="1 Test St",
                           driver_name="Driver T"):
    """Create transport leg, advance EN_ROUTE -> ARRIVED, receive the body.

    Leaves the case in custody RECEIVED, billing BILLABLE. Returns the leg id.
    """
    leg = get_success_data(api_client.create_transport_leg(
        case_id, create_transport_leg_payload(
            origin_kind=origin_kind, origin_label=origin_label,
            driver_name=driver_name), OPERATOR))
    get_success_data(api_client.patch_transport_leg(leg["id"], "EN_ROUTE", OPERATOR))
    get_success_data(api_client.patch_transport_leg(leg["id"], "ARRIVED", OPERATOR))
    get_success_data(api_client.receive_case(case_id, OPERATOR))
    return leg["id"]


def create_received_case(owner_id, clinic_id=None, **case_overrides):
    """Create a case and drive it to RECEIVED. Returns the case dict (re-fetched)."""
    case = create_case(owner_id, clinic_id=clinic_id, **case_overrides)
    drive_case_to_received(case["id"])
    return get_success_data(api_client.get_case(case["id"], ADMIN))


# --------------------------------------------------------------------------- #
# Tier 2: full crematory setup for a single private case
# --------------------------------------------------------------------------- #
def setup_private_case_received(clock="2026-03-01T00:00:00Z", clinic_id=None,
                               weight_lbs=50, expedited=False, bill_to="OWNER",
                               max_load_lbs=300, **case_overrides):
    """Clock + retort + owner + one PRIVATE case driven to RECEIVED.

    Returns dict: retort, owner, case (RECEIVED), clinic_id.
    """
    set_clock(clock)
    retort = create_retort(max_load_lbs=max_load_lbs)
    owner = create_owner()
    case = create_case(owner["id"], clinic_id=clinic_id, service_type="PRIVATE",
                       weight_lbs=weight_lbs, expedited=expedited, bill_to=bill_to,
                       pickup_kind=("CLINIC" if clinic_id else "HOME"),
                       **case_overrides)
    drive_case_to_received(case["id"])
    return {
        "retort": retort,
        "owner": owner,
        "case": get_success_data(api_client.get_case(case["id"], ADMIN)),
        "clinic_id": clinic_id,
    }


def stage_load_fire_private(case_id, retort_id,
                            scheduled_start="2026-03-01T08:00:00Z",
                            scheduled_end="2026-03-01T10:00:00Z"):
    """Create a PRIVATE batch, assign the case, load and fire. Returns the batch id.

    Leaves the batch FIRING and the case STAGED with its cremation_charge_cents set.
    """
    batch = create_batch(retort_id, "PRIVATE", scheduled_start, scheduled_end)
    get_success_data(api_client.assign_case(batch["id"], case_id, OPERATOR))
    get_success_data(api_client.load_batch(batch["id"], OPERATOR))
    get_success_data(api_client.fire_batch(batch["id"], OPERATOR))
    return batch["id"]


def setup_private_case_cremated(clock="2026-03-01T00:00:00Z", clinic_id=None,
                                weight_lbs=50, expedited=False, bill_to="OWNER",
                                scheduled_start="2026-03-01T08:00:00Z",
                                scheduled_end="2026-03-01T10:00:00Z",
                                credit_limit_cents=None):
    """Full lifecycle: a single PRIVATE case driven to custody CREMATED (batch COMPLETED).

    If bill_to is CLINIC_ACCOUNT and no clinic_id is given, a clinic is created.
    Returns dict: retort, owner, case (CREMATED), batch_id, clinic_id.
    """
    set_clock(clock)
    if bill_to == "CLINIC_ACCOUNT" and clinic_id is None:
        clinic = create_clinic(credit_limit_cents=credit_limit_cents)
        clinic_id = clinic["id"]
    retort = create_retort(max_load_lbs=400)
    owner = create_owner()
    case = create_case(owner["id"], clinic_id=clinic_id, service_type="PRIVATE",
                       weight_lbs=weight_lbs, expedited=expedited, bill_to=bill_to,
                       pickup_kind=("CLINIC" if clinic_id else "HOME"))
    drive_case_to_received(case["id"])
    batch_id = stage_load_fire_private(case["id"], retort["id"],
                                       scheduled_start, scheduled_end)
    get_success_data(api_client.complete_batch(batch_id, OPERATOR))
    return {
        "retort": retort,
        "owner": owner,
        "case": get_success_data(api_client.get_case(case["id"], ADMIN)),
        "batch_id": batch_id,
        "clinic_id": clinic_id,
    }


def setup_private_case_invoiced(clock="2026-03-01T00:00:00Z", clinic_id=None,
                                weight_lbs=50, bill_to="OWNER",
                                credit_limit_cents=None):
    """Full lifecycle through to an ISSUED invoice on a CREMATED private case.

    Returns dict: retort, owner, case (after invoicing), batch_id, clinic_id,
    invoice (ISSUED), case_version_at_issue.
    """
    ctx = setup_private_case_cremated(clock=clock, clinic_id=clinic_id,
                                      weight_lbs=weight_lbs, bill_to=bill_to,
                                      credit_limit_cents=credit_limit_cents)
    case_id = ctx["case"]["id"]
    case = get_success_data(api_client.get_case(case_id, ADMIN))
    version = case["version"]
    invoice = get_success_data(api_client.create_invoice(case_id, version, ADMIN))
    ctx["invoice"] = invoice
    ctx["case_version_at_issue"] = version
    ctx["case"] = get_success_data(api_client.get_case(case_id, ADMIN))
    return ctx


# --------------------------------------------------------------------------- #
# Tier 3: communal batch with multiple members
# --------------------------------------------------------------------------- #
def setup_communal_batch_loaded(clock, weights, max_load_lbs=400,
                                scheduled_start="2026-03-06T08:00:00Z",
                                scheduled_end="2026-03-06T10:00:00Z"):
    """Create N COMMUNAL cases (in the given weight order), drive each to RECEIVED,
    assign all to one COMMUNAL batch, then load it.

    Returns dict: retort, owner, case_ids (creation order), batch_id (LOADED, not fired).
    """
    set_clock(clock)
    retort = create_retort(max_load_lbs=max_load_lbs)
    owner = create_owner()
    case_ids = []
    for i, w in enumerate(weights):
        case = create_case(owner["id"], service_type="COMMUNAL", weight_lbs=w,
                           bill_to="OWNER", pickup_kind="CLINIC", pet_name=f"K{i+1}",
                           species=("CAT" if w < 25 else "DOG"))
        drive_case_to_received(case["id"], origin_kind="CLINIC",
                               origin_label="VetCo", driver_name="D")
        case_ids.append(case["id"])
    batch = create_batch(retort["id"], "COMMUNAL", scheduled_start, scheduled_end)
    for cid in case_ids:
        get_success_data(api_client.assign_case(batch["id"], cid, OPERATOR))
    get_success_data(api_client.load_batch(batch["id"], OPERATOR))
    return {
        "retort": retort,
        "owner": owner,
        "case_ids": case_ids,
        "batch_id": batch["id"],
    }


def setup_communal_batch_fired(clock, weights, **kwargs):
    """As setup_communal_batch_loaded, then fire the batch (charges allocated)."""
    ctx = setup_communal_batch_loaded(clock, weights, **kwargs)
    get_success_data(api_client.fire_batch(ctx["batch_id"], OPERATOR))
    return ctx


# --------------------------------------------------------------------------- #
# Tier 4: cooler storage
# --------------------------------------------------------------------------- #
def setup_received_case_with_cooler(clock="2026-03-09T00:00:00Z", capacity=1,
                                    max_load_lbs=300):
    """Clock + cooler + retort + owner + one PRIVATE case driven to RECEIVED.

    Returns dict: cooler, retort, owner, case (RECEIVED).
    """
    set_clock(clock)
    cooler = create_cooler(total_capacity=capacity)
    retort = create_retort(max_load_lbs=max_load_lbs)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=10,
                       bill_to="OWNER", pickup_kind="CLINIC")
    drive_case_to_received(case["id"], origin_kind="CLINIC",
                           origin_label="V", driver_name="T")
    return {
        "cooler": get_success_data(api_client.get_cooler(cooler["id"], ADMIN)),
        "retort": retort,
        "owner": owner,
        "case": get_success_data(api_client.get_case(case["id"], ADMIN)),
    }


def store_case(case_id, cooler_id):
    return get_success_data(api_client.store_case(case_id, cooler_id, OPERATOR))


# --------------------------------------------------------------------------- #
# Tier 5: return-of-ashes lifecycle
# --------------------------------------------------------------------------- #
def setup_case_ready_for_return(clock="2026-03-15T00:00:00Z",
                                return_method="COURIER_TO_HOME",
                                destination_label="4 St"):
    """Drive a PRIVATE case to READY_FOR_RETURN with a PLANNED ReturnRoute.

    Returns dict: case (READY_FOR_RETURN), route (PLANNED), batch_id, owner, retort.
    """
    ctx = setup_private_case_cremated(clock=clock,
                                      scheduled_start="2026-03-15T08:00:00Z",
                                      scheduled_end="2026-03-15T10:00:00Z")
    case_id = ctx["case"]["id"]
    get_success_data(api_client.ready_return(
        case_id, create_ready_return_payload(return_method=return_method,
                                             destination_label=destination_label),
        OPERATOR))
    routes, _ = _list(api_client.list_return_routes(case_id, OPERATOR))
    ctx["case"] = get_success_data(api_client.get_case(case_id, ADMIN))
    ctx["route"] = routes[0]
    return ctx


def setup_case_returned(clock="2026-05-01T00:00:00Z"):
    """Drive a PRIVATE case all the way to RETURNED (terminal custody).

    Returns dict: case (RETURNED), route (DELIVERED), batch_id, owner, retort.
    """
    ctx = setup_case_ready_for_return(clock=clock, return_method="PICKUP_AT_FACILITY",
                                      destination_label="Front desk")
    case_id = ctx["case"]["id"]
    get_success_data(api_client.dispatch_return_route(ctx["route"]["id"], OPERATOR))
    get_success_data(api_client.finalize_return(case_id, OPERATOR))
    ctx["case"] = get_success_data(api_client.get_case(case_id, ADMIN))
    return ctx


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _list(response):
    """Lenient extraction of (data_list, meta) from a list response in fixtures."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def get_case(case_id, headers=ADMIN):
    return get_success_data(api_client.get_case(case_id, headers))


def get_case_version(case_id):
    return get_success_data(api_client.get_case(case_id, ADMIN))["version"]
