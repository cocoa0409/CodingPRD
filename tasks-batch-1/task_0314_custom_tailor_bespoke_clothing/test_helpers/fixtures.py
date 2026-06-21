"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the server (empty DB) before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. All
setup calls use get_success_data() (lenient) so a setup failure surfaces as a
clear "Setup failed" rather than a confusing assertion error.

Default money math used throughout (so tests can hard-code expected values):
  fabric @ 8000 cents/m, meters 7.0, base_labor 40000, lines MONOGRAM+CONTRAST_LINING.
    yardage(7, 8000) = round(3*8000*1.00) + round(3*8000*0.90) + round(1*8000*0.80)
                     = 24000 + 21600 + 6400 = 52000
    options = 1500 + 4000 = 5500
    pre_rush = 40000 + 52000 + 5500 = 97500  (non-rush -> locked = 97500)
    deposit  = ceil(97500 * 0.50) = 48750
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_measurement_profile_payload,
    create_fabric_payload, create_tailor_payload, create_fitting_room_payload,
    create_group_order_payload, create_order_payload, create_option_line_payload,
    create_fitting_payload, create_payment_payload,
)
from .test_users import TEST_USERS, make_customer_headers


SA = TEST_USERS["sales_associate_headers"]
FS = TEST_USERS["fitting_specialist_headers"]
SM = TEST_USERS["shop_manager_headers"]

# Canonical money figures for the default order shape (see module docstring).
DEFAULT_LOCKED_TOTAL_CENTS = 97500
DEFAULT_DEPOSIT_CENTS = 48750
DEFAULT_BALANCE_CENTS = 48750  # locked 97500 - deposit 48750


# A monotonically increasing day counter so fitting windows on the SAME order
# never collide on their own tailor/room. Each call returns a fresh ISO date.
class _DateGen:
    def __init__(self):
        self._day = 1

    def next_window(self, hour_start=9, hour_end=10):
        # Spread fittings across distinct days in 2026-07 to avoid self-overlap.
        day = self._day
        self._day += 1
        d = f"2026-07-{day:02d}"
        return (f"{d}T{hour_start:02d}:00:00.000Z", f"{d}T{hour_end:02d}:00:00.000Z")


# ─── Tier 0: atomic catalog / customer creation ─────────────────────────

def create_customer(**overrides):
    """Create a Customer. Returns the customer dict."""
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), SA))


def create_profile(customer_id, **overrides):
    """Create a MANUAL MeasurementProfile for a customer. Returns the profile."""
    return get_success_data(api_client.create_measurement_profile(
        create_measurement_profile_payload(customer_id, **overrides), SA))


def create_fabric(**overrides):
    """Create a Fabric. Returns the fabric dict."""
    return get_success_data(api_client.create_fabric(create_fabric_payload(**overrides), SM))


def create_master_tailor(**overrides):
    overrides.setdefault("skill_tier", "MASTER")
    overrides.setdefault("display_name", "Master Tailor")
    return get_success_data(api_client.create_tailor(create_tailor_payload(**overrides), SM))


def create_journeyman_tailor(**overrides):
    overrides.setdefault("skill_tier", "JOURNEYMAN")
    overrides.setdefault("display_name", "Journeyman Tailor")
    return get_success_data(api_client.create_tailor(create_tailor_payload(**overrides), SM))


def create_open_room(**overrides):
    overrides.setdefault("cleanup_buffer_minutes", 0)
    return get_success_data(api_client.create_fitting_room(create_fitting_room_payload(**overrides), SM))


def setup_customer_and_profile(**overrides):
    """Create a customer + one MANUAL profile. Returns (customer, profile)."""
    cust = create_customer(**overrides.get("customer_overrides", {}))
    prof = create_profile(cust["id"], **overrides.get("profile_overrides", {}))
    return cust, prof


# ─── Tier 1: draft / confirmed order shortcuts ──────────────────────────

def create_draft_order(option_codes=("MONOGRAM", "CONTRAST_LINING"),
                       fabric=None, base_labor_cents=40000, fabric_meters_required=7.0,
                       price_per_meter_cents=8000, bolt_meters_initial=50,
                       is_rush=False, group_order_id=None, garment_type="SUIT",
                       customer=None, profile=None):
    """Create a customer + profile + fabric + DRAFT order with the given option lines.

    Returns a dict bundle: {customer, profile, fabric, order, lines}.
    """
    if customer is None:
        customer = create_customer()
    if profile is None:
        profile = create_profile(customer["id"])
    if fabric is None:
        fabric = create_fabric(price_per_meter_cents=price_per_meter_cents,
                               bolt_meters_initial=bolt_meters_initial)

    order_kwargs = dict(base_labor_cents=base_labor_cents,
                        fabric_meters_required=fabric_meters_required,
                        is_rush=is_rush, garment_type=garment_type)
    if group_order_id is not None:
        order_kwargs["group_order_id"] = group_order_id
    order = get_success_data(api_client.create_order(
        create_order_payload(customer["id"], profile["id"], **order_kwargs), SA))

    lines = []
    for code in option_codes:
        line = get_success_data(api_client.create_option_line(
            order["id"], create_option_line_payload(fabric["id"], code), SA))
        lines.append(line)

    order = get_success_data(api_client.get_order(order["id"], SA))
    return {"customer": customer, "profile": profile, "fabric": fabric,
            "order": order, "lines": lines}


def create_confirmed_order(**kwargs):
    """create_draft_order(...) then confirm. Bundle gains a refreshed 'order'."""
    bundle = create_draft_order(**kwargs)
    confirmed = get_success_data(api_client.confirm_order(bundle["order"]["id"], SA))
    bundle["order"] = confirmed
    return bundle


def pay_deposit(order_id, amount_cents=DEFAULT_DEPOSIT_CENTS):
    """Capture a DEPOSIT payment. Returns the payment dict."""
    return get_success_data(api_client.create_payment(
        order_id, create_payment_payload("DEPOSIT", amount_cents), SA))


def create_confirmed_order_with_deposit(deposit_cents=DEFAULT_DEPOSIT_CENTS, **kwargs):
    """Confirmed order with the deposit captured. Bundle gains 'deposit_payment'."""
    bundle = create_confirmed_order(**kwargs)
    bundle["deposit_payment"] = pay_deposit(bundle["order"]["id"], deposit_cents)
    bundle["order"] = get_success_data(api_client.get_order(bundle["order"]["id"], SA))
    return bundle


# ─── Tier 2: fitting-room progression ───────────────────────────────────

def _schedule_fitting(order_id, tailor_id, room_id, milestone, expected_order_version, dates):
    start_at, end_at = dates.next_window()
    return get_success_data(api_client.create_fitting(
        order_id,
        create_fitting_payload(tailor_id, room_id, milestone, start_at, end_at, expected_order_version),
        FS))


def create_order_at_scheduled_final(deposit_cents=DEFAULT_DEPOSIT_CENTS, **kwargs):
    """Drive an order to a SCHEDULED FINAL fitting with BASTED+FORWARD already PASSED.

    Uses a MASTER tailor (FINAL requires MASTER) and an open room, scheduling each
    fitting on a distinct day to avoid self-overlap. After this the order is
    IN_FITTING with a SCHEDULED FINAL fitting ready to be recorded.

    Returns a bundle: {customer, profile, fabric, order, lines, tailor, room,
                       fittings: {basted, forward, final}}.
    """
    bundle = create_confirmed_order_with_deposit(deposit_cents=deposit_cents, **kwargs)
    tailor = create_master_tailor()
    room = create_open_room()
    order_id = bundle["order"]["id"]
    dates = _DateGen()

    order = get_success_data(api_client.get_order(order_id, SA))
    basted = _schedule_fitting(order_id, tailor["id"], room["id"], "BASTED", order["version"], dates)
    get_success_data(api_client.record_fitting_outcome(
        order_id, basted["id"], {"result": "PASS"}, FS))

    order = get_success_data(api_client.get_order(order_id, SA))
    forward = _schedule_fitting(order_id, tailor["id"], room["id"], "FORWARD", order["version"], dates)
    get_success_data(api_client.record_fitting_outcome(
        order_id, forward["id"], {"result": "PASS"}, FS))

    order = get_success_data(api_client.get_order(order_id, SA))
    final = _schedule_fitting(order_id, tailor["id"], room["id"], "FINAL", order["version"], dates)

    bundle["tailor"] = tailor
    bundle["room"] = room
    bundle["fittings"] = {"basted": basted, "forward": forward, "final": final}
    bundle["order"] = get_success_data(api_client.get_order(order_id, SA))
    return bundle


def create_ready_order(**kwargs):
    """Drive an order to READY: scheduled FINAL fitting then record PASS on it.

    Returns the same bundle as create_order_at_scheduled_final, with order refreshed
    to READY status.
    """
    bundle = create_order_at_scheduled_final(**kwargs)
    order_id = bundle["order"]["id"]
    get_success_data(api_client.record_fitting_outcome(
        order_id, bundle["fittings"]["final"]["id"], {"result": "PASS"}, FS))
    bundle["order"] = get_success_data(api_client.get_order(order_id, SA))
    return bundle


def create_ready_order_balance_paid(balance_cents=DEFAULT_BALANCE_CENTS, **kwargs):
    """READY order with the balance fully captured (balance_due_cents == 0)."""
    bundle = create_ready_order(**kwargs)
    order_id = bundle["order"]["id"]
    bundle["balance_payment"] = get_success_data(api_client.create_payment(
        order_id, create_payment_payload("BALANCE", balance_cents), SA))
    bundle["order"] = get_success_data(api_client.get_order(order_id, SA))
    return bundle


def create_picked_up_order(**kwargs):
    """Full lifecycle through PICKED_UP. Bundle gains 'pickup'."""
    bundle = create_ready_order_balance_paid(**kwargs)
    order_id = bundle["order"]["id"]
    bundle["pickup"] = get_success_data(api_client.pickup_order(
        order_id, {"released_to_name": "Test Pickup"}, SA))
    bundle["order"] = get_success_data(api_client.get_order(order_id, SA))
    return bundle


def fail_final_into_remake(bundle):
    """Given a bundle at a SCHEDULED FINAL fitting, record FAIL to cascade REMAKE.

    Returns the refreshed order (now REMAKE). Mutates and returns bundle['order'].
    """
    order_id = bundle["order"]["id"]
    get_success_data(api_client.record_fitting_outcome(
        order_id, bundle["fittings"]["final"]["id"], {"result": "FAIL"}, FS))
    bundle["order"] = get_success_data(api_client.get_order(order_id, SA))
    return bundle


# ─── Tier 3: group order assembly ───────────────────────────────────────

def create_group(**overrides):
    """Create a FORMING GroupOrder. Returns the group dict."""
    return get_success_data(api_client.create_group_order(create_group_order_payload(**overrides), SA))


def add_confirmed_member(group_id, base_labor_cents=20000, fabric_meters_required=3.0,
                         price_per_meter_cents=6000, fabric=None, option_codes=("MONOGRAM",)):
    """Create a member order in the group and confirm it. Returns the order bundle.

    With base 20000, meters 3.0 @ 6000, MONOGRAM: yardage(3,6000) = round(3*6000*1.0)=18000,
    options 1500 -> locked = 20000 + 18000 + 1500 = 39500.
    """
    bundle = create_confirmed_order(
        option_codes=option_codes, fabric=fabric,
        base_labor_cents=base_labor_cents, fabric_meters_required=fabric_meters_required,
        price_per_meter_cents=price_per_meter_cents, bolt_meters_initial=200,
        group_order_id=group_id)
    return bundle


def setup_group_with_confirmed_members(num_members=3, shared_fabric=True):
    """Create a FORMING group with `num_members` CONFIRMED member orders.

    Each member order locks at 39500 cents (see add_confirmed_member). Returns
    (group, [member_bundles]). The group is NOT locked.
    """
    group = create_group()
    fabric = create_fabric(price_per_meter_cents=6000, bolt_meters_initial=2000) if shared_fabric else None
    members = []
    for _ in range(num_members):
        members.append(add_confirmed_member(group["id"], fabric=fabric))
    group = get_success_data(api_client.get_group_order(group["id"], SA))
    return group, members


def lock_group(group_id):
    """Lock a forming group, supplying its current version. Returns the locked group."""
    group = get_success_data(api_client.get_group_order(group_id, SA))
    return get_success_data(api_client.lock_group_order(
        group_id, {"expected_group_order_version": group["version"]}, SM))
