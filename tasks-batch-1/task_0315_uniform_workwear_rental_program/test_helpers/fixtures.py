"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so a broken setup surfaces
as a clear "setup failed" error rather than a confusing assertion failure.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness re-launches the server (empty database)
before each individual test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_account_payload,
    create_wearer_payload,
    create_garment_type_payload,
    create_wash_station_payload,
    create_garment_payload,
    create_assignment_payload,
    create_route_payload,
    create_route_stop_payload,
    create_service_visit_payload,
    pickup_payload,
    reconcile_payload,
    start_wash_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
DRIVER = TEST_USERS["route_driver_headers"]
TECH = TEST_USERS["cleanroom_tech_headers"]


# ─── Atomic create helpers ────────────────────────────────────────────────

def make_account(**overrides):
    return get_success_data(api_client.create_account(create_account_payload(**overrides), ADMIN))


def make_garment_type(**overrides):
    return get_success_data(api_client.create_garment_type(create_garment_type_payload(**overrides), ADMIN))


def make_wash_station(**overrides):
    return get_success_data(api_client.create_wash_station(create_wash_station_payload(**overrides), ADMIN))


def make_wearer(account_id, **overrides):
    return get_success_data(api_client.create_wearer(account_id, create_wearer_payload(**overrides), MANAGER))


def make_garment(account_id, garment_type_id, **overrides):
    return get_success_data(
        api_client.create_garment(account_id, create_garment_payload(garment_type_id, **overrides), ADMIN)
    )


def make_assignment(garment_id, wearer_id):
    return get_success_data(
        api_client.create_assignment(create_assignment_payload(garment_id, wearer_id), MANAGER)
    )


def make_route(**overrides):
    return get_success_data(api_client.create_route(create_route_payload(**overrides), ADMIN))


def make_route_stop(route_id, account_id, **overrides):
    return get_success_data(
        api_client.create_route_stop(route_id, create_route_stop_payload(account_id, **overrides), ADMIN)
    )


def make_service_visit(route_stop_id, week_index=0):
    return get_success_data(
        api_client.create_service_visit(route_stop_id, create_service_visit_payload(week_index=week_index), ADMIN)
    )


# ─── Tier 1: small composite hierarchies ──────────────────────────────────

def setup_account_with_wearer(grace=None, billing_overrides=None):
    """Create an account (optional grace) and one ACTIVE wearer.

    Returns (account, wearer).
    """
    acct_kwargs = dict(billing_overrides or {})
    if grace is not None:
        acct_kwargs["shortage_grace_units"] = grace
    acct = make_account(**acct_kwargs)
    wearer = make_wearer(acct["id"])
    return acct, wearer


def setup_assigned_garment(grace=None, replacement_cost_cents=8000, weekly_rate_cents=1000,
                           category="SHIRT", emblem_setup_cents=0):
    """Account + ACTIVE wearer + one garment ASSIGNED to that wearer.

    Returns (account, wearer, garment_type, garment, assignment).
    """
    acct, wearer = setup_account_with_wearer(grace=grace)
    gt = make_garment_type(
        category=category,
        weekly_rate_cents=weekly_rate_cents,
        replacement_cost_cents=replacement_cost_cents,
        emblem_setup_cents=emblem_setup_cents,
    )
    g = make_garment(acct["id"], gt["id"])
    asg = make_assignment(g["id"], wearer["id"])
    return acct, wearer, gt, g, asg


def setup_route_stop_for_account(account_id, stop_sequence=1,
                                 window_start_min=480, window_end_min=540, service_day="MON"):
    """Create a route + one stop servicing the account. Returns (route, stop)."""
    route = make_route(service_day=service_day)
    stop = make_route_stop(route["id"], account_id, stop_sequence=stop_sequence,
                           window_start_min=window_start_min, window_end_min=window_end_min)
    return route, stop


# ─── Tier 2: wash-cycle helpers ───────────────────────────────────────────

def wash_garment(garment_id, wash_station_id, slot_start_min=600, slot_end_min=660):
    """Drive a single IN_SOIL garment through start-wash then finish-wash back to AT_PLANT."""
    get_success_data(
        api_client.start_wash(garment_id, start_wash_payload(wash_station_id, slot_start_min, slot_end_min), TECH)
    )
    return get_success_data(api_client.finish_wash(garment_id, TECH))


# ─── Tier 3: full provisional / finalized visit lifecycle ─────────────────

def setup_provisional_finalized_visit(grace=2, weekly_rate_cents=1200, num_garments=3,
                                      num_washed=1, actual_soil_count=1):
    """Build the canonical dual-variant scenario through to DELIVERED.

    Creates an account (given grace), a garment type at `weekly_rate_cents`, a wash
    station, one ACTIVE wearer, `num_garments` garments all ASSIGNED to the wearer,
    a route + stop + scheduled visit. Then runs pickup with `actual_soil_count`,
    washes `num_washed` of the soiled garments back to AT_PLANT, and delivers.

    Returns a dict with keys:
        account, wearer, garment_type, wash_station, garments (list),
        route, stop, visit (the DELIVERED visit), delivered_version.
    """
    acct = make_account(shortage_grace_units=grace)
    gt = make_garment_type(weekly_rate_cents=weekly_rate_cents, replacement_cost_cents=8000)
    ws = make_wash_station(capacity=5)
    wearer = make_wearer(acct["id"])
    garments = [make_garment(acct["id"], gt["id"]) for _ in range(num_garments)]
    for g in garments:
        make_assignment(g["id"], wearer["id"])

    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)

    get_success_data(api_client.pickup_visit(visit["id"], pickup_payload(actual_soil_count), DRIVER))

    # The pickup moved min(actual, expected) oldest garments into IN_SOIL. Wash the
    # requested number of those (oldest first matches assignment/creation order).
    for g in garments[:num_washed]:
        wash_garment(g["id"], ws["id"])

    delivered = get_success_data(api_client.deliver_visit(visit["id"], DRIVER))
    return {
        "account": acct,
        "wearer": wearer,
        "garment_type": gt,
        "wash_station": ws,
        "garments": garments,
        "route": route,
        "stop": stop,
        "visit": delivered,
        "delivered_version": delivered["version"],
    }


def reconcile_with_version(visit_id, expected_version):
    """Reconcile a DELIVERED visit at the given expected version. Returns the visit."""
    return get_success_data(
        api_client.reconcile_visit(visit_id, reconcile_payload(expected_version), ADMIN)
    )


# ─── Tier 4: soil-strike accumulation ─────────────────────────────────────

def setup_garment_with_soil_strikes(target_strikes, replacement_cost_cents=8000):
    """Account + ACTIVE wearer + one ASSIGNED garment driven to `target_strikes`.

    Each weekly visit where the wearer keeps the garment (pickup actual_soil_count=0
    against expected 1) increments the garment's soil_strikes by one. Runs
    `target_strikes` pickup/deliver cycles. The garment is never moved into soil, so
    delivery (which requires no garment IN_SOIL/IN_WASH) succeeds each week.

    Returns (account, wearer, garment_type, garment, assignment, stop).
    """
    acct = make_account(shortage_grace_units=0)
    gt = make_garment_type(replacement_cost_cents=replacement_cost_cents)
    wearer = make_wearer(acct["id"])
    g = make_garment(acct["id"], gt["id"])
    asg = make_assignment(g["id"], wearer["id"])
    route, stop = setup_route_stop_for_account(acct["id"])

    for week in range(target_strikes):
        visit = make_service_visit(stop["id"], week_index=week)
        # actual=0 against expected=1 leaves the garment AT_CUSTOMER and +1 strike.
        get_success_data(api_client.pickup_visit(visit["id"], pickup_payload(0), DRIVER))
        get_success_data(api_client.deliver_visit(visit["id"], DRIVER))

    return acct, wearer, gt, g, asg, stop


# ─── Tier 5: ledger / billing-posture helpers ─────────────────────────────

def setup_account_with_loss_charge(replacement_cost_cents=60000):
    """Account driven to a single LOSS charge of `replacement_cost_cents`.

    Creates account + ACTIVE wearer + one ASSIGNED garment, then declares the
    assignment lost (raising a LOSS ServiceCharge of the full replacement cost).

    Returns (account, wearer, garment_type, garment, assignment).
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(
        grace=0, replacement_cost_cents=replacement_cost_cents, category="COVERALL"
    )
    get_success_data(api_client.declare_loss(asg["id"], DRIVER if False else MANAGER))
    return acct, wearer, gt, g, asg


def setup_account_on_hold(ramp_spare_wearer=False):
    """Account driven ON_HOLD via a 60000 LOSS (-> PAST_DUE) then place-hold.

    Also provisions a spare IN_STOCK garment and a separate ACTIVE wearer so a
    footprint-growing assignment can be attempted against the held account.

    When `ramp_spare_wearer` is True the spare wearer is ramped down BEFORE the
    hold is placed (ramp-down is itself blocked on an ON_HOLD account per PRD
    §3.2), so an assignment to it later violates BOTH the ON_HOLD gate
    (priority 6) and the wearer-active gate (priority 7).

    Returns a dict: account, lost_wearer, spare_wearer, spare_garment,
    spare_garment_type.
    """
    acct = make_account(shortage_grace_units=0)
    gt_cov = make_garment_type(category="COVERALL", replacement_cost_cents=60000)
    gt_shirt = make_garment_type(category="SHIRT", replacement_cost_cents=8000)
    lost_wearer = make_wearer(acct["id"])
    spare_wearer = make_wearer(acct["id"])
    lost_garment = make_garment(acct["id"], gt_cov["id"])
    spare_garment = make_garment(acct["id"], gt_shirt["id"])
    a_lost = make_assignment(lost_garment["id"], lost_wearer["id"])
    get_success_data(api_client.declare_loss(a_lost["id"], MANAGER))
    # Ramp the spare wearer down before the hold, since ramp-down on an ON_HOLD
    # account is rejected with ERR_ACCOUNT_ON_HOLD (PRD §3.2).
    if ramp_spare_wearer:
        get_success_data(api_client.ramp_down_wearer(spare_wearer["id"], MANAGER))
    get_success_data(api_client.place_hold(acct["id"], ADMIN))
    return {
        "account": acct,
        "lost_wearer": lost_wearer,
        "spare_wearer": spare_wearer,
        "spare_garment": spare_garment,
        "spare_garment_type": gt_shirt,
    }


def get_account(account_id):
    return get_success_data(api_client.get_account(account_id, ADMIN))


def get_garment(garment_id):
    return get_success_data(api_client.get_garment(garment_id, ADMIN))


def get_wearer(wearer_id):
    return get_success_data(api_client.get_wearer(wearer_id, ADMIN))


def get_visit(visit_id):
    return get_success_data(api_client.get_service_visit(visit_id, ADMIN))


def list_account_charges(account_id, charge_type=None):
    """Return the list of ServiceCharges for an account, optionally filtered by type."""
    params = {"account_id": account_id}
    if charge_type is not None:
        params["charge_type"] = charge_type
    res = api_client.list_service_charges(ADMIN, params=params)
    body = res.json()
    return body["data"]
