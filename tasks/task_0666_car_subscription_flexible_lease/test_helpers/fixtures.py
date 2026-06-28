"""Composite setup helpers.

Every test runs against a freshly restarted, empty server. These helpers rebuild
the multi-step preambles the design instances share (plan -> fleet -> vehicle ->
applicant -> eligibility -> subscription -> assign -> courier+slot -> activate) so
test bodies focus on assertions.

All setup calls go through get_success_data() (lenient) so a setup failure surfaces
as a clear "Setup failed" rather than a confusing assertion error. Member ownership
is threaded with make_member_headers(applicant_id) wherever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers
from . import factories as f

DEFAULT_CLOCK = "2026-04-01T00:00:00Z"


# --------------------------------------------------------------------------- #
# Atomic builders                                                             #
# --------------------------------------------------------------------------- #
def set_clock(to_iso=DEFAULT_CLOCK):
    get_success_data(api_client.set_clock(to_iso, TEST_USERS["platform_admin_headers"]))


def reset_clock_default():
    set_clock(DEFAULT_CLOCK)


def create_plan(**overrides) -> dict:
    return get_success_data(api_client.create_plan(
        f.create_plan_payload(**overrides), TEST_USERS["platform_admin_headers"]))


def create_premium_plan(**overrides) -> dict:
    return get_success_data(api_client.create_plan(
        f.create_premium_plan_payload(**overrides), TEST_USERS["platform_admin_headers"]))


def create_fleet(**overrides) -> dict:
    return get_success_data(api_client.create_fleet(
        f.create_fleet_payload(**overrides), TEST_USERS["platform_admin_headers"]))


def create_vehicle(fleet_id, plan_id, **overrides) -> dict:
    return get_success_data(api_client.create_vehicle(
        f.create_vehicle_payload(fleet_id, plan_id, **overrides),
        TEST_USERS["fleet_operator_headers"]))


def create_applicant(**overrides) -> dict:
    return get_success_data(api_client.create_applicant(
        f.create_applicant_payload(**overrides), TEST_USERS["member_headers"]))


def decide_eligibility(applicant_id, plan_id) -> dict:
    return get_success_data(api_client.decide_eligibility(
        applicant_id, {"plan_id": plan_id}, TEST_USERS["billing_admin_headers"]))


def create_applicant_eligible(plan_id, **overrides) -> dict:
    """Create an applicant and run the eligibility decision against the plan."""
    appl = create_applicant(**overrides)
    decide_eligibility(appl["id"], plan_id)
    # Return the post-decision applicant so callers see eligibility fields.
    return get_success_data(api_client.get_applicant(
        appl["id"], TEST_USERS["billing_admin_headers"]))


def create_subscription(applicant_id, plan_id) -> dict:
    return get_success_data(api_client.create_subscription(
        f.create_subscription_payload(applicant_id, plan_id),
        make_member_headers(applicant_id)))


def create_courier(fleet_id, **overrides) -> dict:
    return get_success_data(api_client.create_courier(
        f.create_courier_payload(fleet_id, **overrides),
        TEST_USERS["fleet_operator_headers"]))


def create_delivery_slot(courier_id, subscription_id, **overrides) -> dict:
    return get_success_data(api_client.create_delivery_slot(
        f.create_delivery_slot_payload(courier_id, subscription_id, **overrides),
        TEST_USERS["fleet_operator_headers"]))


# --------------------------------------------------------------------------- #
# Tier 1 / 2: bootstrap a plan + fleet                                        #
# --------------------------------------------------------------------------- #
def setup_catalog(plan_overrides=None, set_clock_to=DEFAULT_CLOCK):
    """Clock + one PLUS plan + one fleet. Returns (plan, fleet)."""
    set_clock(set_clock_to)
    plan = create_plan(**(plan_overrides or {}))
    fleet = create_fleet()
    return plan, fleet


# --------------------------------------------------------------------------- #
# Tier 3: subscription lifecycle shortcuts                                    #
# --------------------------------------------------------------------------- #
def setup_draft_subscription(plan_overrides=None, applicant_overrides=None,
                             set_clock_to=DEFAULT_CLOCK):
    """Plan + fleet + one AVAILABLE vehicle + eligible applicant + DRAFT subscription.

    Returns a dict with plan, fleet, vehicle, applicant, subscription.
    The vehicle is freshly created (version 1) and AVAILABLE.
    """
    plan, fleet = setup_catalog(plan_overrides, set_clock_to)
    vehicle = create_vehicle(fleet["id"], plan["id"])
    applicant = create_applicant_eligible(plan["id"], **(applicant_overrides or {}))
    sub = create_subscription(applicant["id"], plan["id"])
    return {
        "plan": plan, "fleet": fleet, "vehicle": vehicle,
        "applicant": applicant, "subscription": sub,
    }


def assign_vehicle(subscription_id, vehicle, expected_version=None) -> dict:
    """FleetOperator reserves `vehicle` for the subscription. Uses the vehicle's
    current version unless an explicit (possibly stale) version is supplied."""
    ev = expected_version if expected_version is not None else vehicle["version"]
    return get_success_data(api_client.assign_vehicle(
        subscription_id,
        {"vehicle_id": vehicle["id"], "expected_vehicle_version": ev},
        TEST_USERS["fleet_operator_headers"]))


def setup_pending_delivery(plan_overrides=None, vehicle_overrides=None,
                           applicant_overrides=None, set_clock_to=DEFAULT_CLOCK):
    """DRAFT subscription advanced to PENDING_DELIVERY (vehicle RESERVED).

    Returns dict with plan, fleet, vehicle (RESERVED, version bumped),
    applicant, subscription, courier.
    """
    plan, fleet = setup_catalog(plan_overrides, set_clock_to)
    vehicle = create_vehicle(fleet["id"], plan["id"], **(vehicle_overrides or {}))
    applicant = create_applicant_eligible(plan["id"], **(applicant_overrides or {}))
    sub = create_subscription(applicant["id"], plan["id"])
    assign_vehicle(sub["id"], vehicle)
    courier = create_courier(fleet["id"])
    return {
        "plan": plan, "fleet": fleet, "vehicle": vehicle,
        "applicant": applicant, "subscription": sub, "courier": courier,
    }


def setup_active_subscription(plan_overrides=None, vehicle_overrides=None,
                              applicant_overrides=None, set_clock_to=DEFAULT_CLOCK,
                              activate_clock=None):
    """Full chain to ACTIVE: assign vehicle, schedule DELIVERY slot, activate.

    Opens BillingCycle #1. Returns dict with plan, fleet, vehicle, applicant,
    subscription, courier, delivery_slot. The returned `subscription` is the
    post-activation snapshot (ACTIVE, term_start set).
    """
    ctx = setup_pending_delivery(plan_overrides, vehicle_overrides,
                                 applicant_overrides, set_clock_to)
    slot = create_delivery_slot(ctx["courier"]["id"], ctx["subscription"]["id"])
    if activate_clock:
        set_clock(activate_clock)
    sub = get_success_data(api_client.activate_subscription(
        ctx["subscription"]["id"], TEST_USERS["fleet_operator_headers"]))
    ctx["delivery_slot"] = slot
    ctx["subscription"] = sub
    return ctx


def open_billing_cycle_id(subscription_id) -> str:
    """Return the id of the subscription's current OPEN billing cycle."""
    data, _meta = _list(api_client.list_subscription_billing_cycles(
        subscription_id, TEST_USERS["billing_admin_headers"], params={"status": "OPEN"}))
    assert data, f"Setup failed: no OPEN billing cycle for subscription {subscription_id}"
    return data[0]["id"]


def get_subscription_version(subscription_id, headers=None) -> int:
    h = headers or TEST_USERS["billing_admin_headers"]
    sub = get_success_data(api_client.get_subscription(subscription_id, h))
    return sub["version"]


def get_vehicle_version(vehicle_id) -> int:
    veh = get_success_data(api_client.get_vehicle(
        vehicle_id, TEST_USERS["fleet_operator_headers"]))
    return veh["version"]


# --------------------------------------------------------------------------- #
# Tier 4: swap lifecycle shortcuts                                            #
# --------------------------------------------------------------------------- #
def request_swap(subscription_id, applicant_id, to_vehicle_id) -> dict:
    return get_success_data(api_client.request_swap(
        subscription_id, {"to_vehicle_id": to_vehicle_id},
        make_member_headers(applicant_id)))


def approve_swap(swap_id, to_vehicle_id) -> dict:
    ev = get_vehicle_version(to_vehicle_id)
    return get_success_data(api_client.approve_swap(
        swap_id, {"expected_vehicle_version": ev},
        TEST_USERS["fleet_operator_headers"]))


def complete_swap(swap_id) -> dict:
    return get_success_data(api_client.complete_swap(
        swap_id, TEST_USERS["fleet_operator_headers"]))


def perform_full_swap(subscription_id, applicant_id, to_vehicle_id) -> dict:
    """Request -> approve -> complete a swap into to_vehicle. Returns COMPLETED swap."""
    sw = request_swap(subscription_id, applicant_id, to_vehicle_id)
    approve_swap(sw["id"], to_vehicle_id)
    return complete_swap(sw["id"])


# --------------------------------------------------------------------------- #
# Tier 5: return / inspection lifecycle shortcuts                             #
# --------------------------------------------------------------------------- #
def initiate_return(subscription_id, applicant_id) -> dict:
    return get_success_data(api_client.initiate_return(
        subscription_id, make_member_headers(applicant_id)))


def open_inspection(subscription_id, vehicle_id, reported_odometer_miles=0) -> dict:
    return get_success_data(api_client.create_return_inspection(
        f.create_return_inspection_payload(
            subscription_id, vehicle_id, reported_odometer_miles=reported_odometer_miles),
        TEST_USERS["fleet_operator_headers"]))


def add_damage(inspection_id, severity, amount_cents, note=None) -> dict:
    payload = f.create_damage_line_item_payload(severity=severity, amount_cents=amount_cents)
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.add_damage_line_item(
        inspection_id, payload, TEST_USERS["fleet_operator_headers"]))


def assess_inspection(inspection_id) -> dict:
    return get_success_data(api_client.assess_inspection(
        inspection_id, TEST_USERS["fleet_operator_headers"]))


def settle_inspection(inspection_id) -> dict:
    return get_success_data(api_client.settle_inspection(
        inspection_id, TEST_USERS["billing_admin_headers"]))


def setup_assessed_inspection(damage_items=None, plan_overrides=None,
                              reported_odometer_miles=0):
    """ACTIVE subscription -> initiate-return -> open inspection -> add damage ->
    assess. Returns dict with the active-subscription context plus `inspection`.

    `damage_items` is a list of (severity, amount_cents) tuples.
    """
    ctx = setup_active_subscription(plan_overrides=plan_overrides)
    initiate_return(ctx["subscription"]["id"], ctx["applicant"]["id"])
    insp = open_inspection(ctx["subscription"]["id"], ctx["vehicle"]["id"],
                           reported_odometer_miles)
    for severity, amount in (damage_items or []):
        add_damage(insp["id"], severity, amount)
    insp = assess_inspection(insp["id"])
    ctx["inspection"] = insp
    return ctx


# --------------------------------------------------------------------------- #
# Internal                                                                    #
# --------------------------------------------------------------------------- #
def _list(response):
    """Return (data_list, meta) from a list response without status assertions."""
    body = response.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    return data, meta
