"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.
All setup runs as Manager, the superset operator that can perform every
Barista and Customer operation (PRD 2.1), so ownership/roster checks never
interfere with setup. Helpers use get_success_data() (lenient) so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion later.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_customer_headers
from . import factories as F

MGR = TEST_USERS["manager_headers"]


# --------------------------------------------------------------------------
# Low-level single-entity helpers
# --------------------------------------------------------------------------
def new_member(api, headers=MGR, **overrides) -> dict:
    return get_success_data(api.create_member(F.create_member_payload(**overrides), headers))


def set_member_points(api, member_id, lifetime_delta=0, balance_delta=0, headers=MGR) -> dict:
    return get_success_data(api.adjust_member_points(
        member_id,
        {"lifetime_points_delta": lifetime_delta, "points_balance_delta": balance_delta},
        headers,
    ))


def member_with_lifetime(api, lifetime_points, balance=0, headers=MGR, **overrides) -> dict:
    """Register a member and raise lifetime_points (and optionally balance) to a
    target via a manual point-adjustment. Returns the member after adjustment."""
    m = new_member(api, headers=headers, **overrides)
    return set_member_points(api, m["id"], lifetime_delta=lifetime_points,
                             balance_delta=balance, headers=headers)


def new_equipment(api, name="esp1", equipment_type="ESPRESSO", headers=MGR) -> dict:
    return get_success_data(api.create_equipment(
        F.create_equipment_payload(name=name, equipment_type=equipment_type), headers))


def new_barista(api, headers=MGR, **overrides) -> dict:
    return get_success_data(api.create_barista(F.create_barista_payload(**overrides), headers))


def new_bean_lot(api, headers=MGR, **overrides) -> dict:
    return get_success_data(api.create_bean_lot(F.create_bean_lot_payload(**overrides), headers))


def activate_lot(api, lot_id, headers=MGR) -> dict:
    return get_success_data(api.activate_bean_lot(lot_id, headers))


def new_active_lot(api, headers=MGR, **overrides) -> dict:
    """Create a RESERVE lot and activate it. Returns the activated lot."""
    lot = new_bean_lot(api, headers=headers, **overrides)
    return activate_lot(api, lot["id"], headers=headers)


def new_modifier(api, headers=MGR, **overrides) -> dict:
    return get_success_data(api.create_modifier(F.create_modifier_payload(**overrides), headers))


def new_menu_item(api, headers=MGR, **overrides) -> dict:
    return get_success_data(api.create_menu_item(F.create_menu_item_payload(**overrides), headers))


def new_order(api, headers=MGR, **overrides) -> dict:
    return get_success_data(api.create_order(F.create_order_payload(**overrides), headers))


def new_catering_event(api, headers=MGR, **overrides) -> dict:
    return get_success_data(api.create_catering_event(
        F.create_catering_event_payload(**overrides), headers))


def new_reconciliation(api, headers=MGR, **overrides) -> dict:
    return get_success_data(api.create_reconciliation(
        F.create_reconciliation_payload(**overrides), headers))


# --------------------------------------------------------------------------
# Composite shop scaffolds
# --------------------------------------------------------------------------
def setup_latte_shop(api, headers=MGR, lot_grams=1000, par_grams=200):
    """Espresso + batch-brew machines OPERATIONAL, an ACTIVE ETHIOPIA lot, an
    Extra Shot modifier, and two origin-required beverages (Latte LG, Drip MD).

    Returns a dict of ids: esp_id, brew_id, lot_id, shot_id, latte_id, drip_id.
    """
    esp = new_equipment(api, name="esp1", equipment_type="ESPRESSO", headers=headers)
    brew = new_equipment(api, name="brew1", equipment_type="BATCH_BREW", headers=headers)
    lot = new_active_lot(api, origin="ETHIOPIA", roast_level="MEDIUM",
                         received_grams=lot_grams, par_grams=par_grams,
                         price_per_gram_cents=5, headers=headers)
    shot = new_modifier(api, name="Extra Shot", modifier_group="SHOT",
                        surcharge_cents=90, extra_bean_grams=9, headers=headers)
    latte = new_menu_item(api, name="Latte LG", category="BEVERAGE", base_price_cents=450,
                          required_equipment_type="ESPRESSO", size="LARGE", bean_grams=18,
                          origin_required=True, bean_origin="ETHIOPIA", headers=headers)
    drip = new_menu_item(api, name="Drip MD", category="BEVERAGE", base_price_cents=300,
                         required_equipment_type="BATCH_BREW", size="MEDIUM", bean_grams=20,
                         origin_required=True, bean_origin="ETHIOPIA", headers=headers)
    return {
        "esp_id": esp["id"], "brew_id": brew["id"], "lot_id": lot["id"],
        "shot_id": shot["id"], "latte_id": latte["id"], "drip_id": drip["id"],
    }


def two_line_order(api, shop, member_id=None, points_redeemed=0, headers=MGR):
    """The canonical two-line order: Latte LG x2 with Extra Shot + Drip MD x1.
    subtotal = 1530 + 375 = 1905 grams drawn = 54 + 20 = 74."""
    payload = {
        "lines": [
            {"menu_item_id": shop["latte_id"], "quantity": 2, "modifier_ids": [shop["shot_id"]]},
            {"menu_item_id": shop["drip_id"], "quantity": 1, "modifier_ids": []},
        ],
    }
    if member_id is not None:
        payload["member_id"] = member_id
    if points_redeemed:
        payload["points_redeemed"] = points_redeemed
    return get_success_data(api.create_order(payload, headers))


def latte_only_order(api, shop, member_id=None, quantity=2, with_shot=True,
                     points_redeemed=0, headers=MGR):
    """Single-line Latte LG order (optionally with the Extra Shot modifier)."""
    line = {"menu_item_id": shop["latte_id"], "quantity": quantity,
            "modifier_ids": [shop["shot_id"]] if with_shot else []}
    payload = {"lines": [line]}
    if member_id is not None:
        payload["member_id"] = member_id
    if points_redeemed:
        payload["points_redeemed"] = points_redeemed
    return get_success_data(api.create_order(payload, headers))


# --------------------------------------------------------------------------
# Catering scaffolds
# --------------------------------------------------------------------------
def setup_confirmed_catering(api, headers=MGR,
                             start="2026-03-02T14:00:00Z", end="2026-03-02T15:00:00Z",
                             equipment_type="ESPRESSO", headcount=30):
    """ACTIVE barista + OPERATIONAL equipment + a CONFIRMED catering event on both.
    Returns dict: bar_id, eq_id, evt_id."""
    bar = new_barista(api, name="B1", station_role="CATERING", headers=headers)
    eq = new_equipment(api, name="esp1", equipment_type=equipment_type, headers=headers)
    evt = new_catering_event(api, client_name="Acme", assigned_equipment_id=eq["id"],
                             assigned_barista_id=bar["id"], scheduled_start=start,
                             scheduled_end=end, headcount=headcount, headers=headers)
    get_success_data(api.confirm_catering_event(evt["id"], headers))
    return {"bar_id": bar["id"], "eq_id": eq["id"], "evt_id": evt["id"]}


# --------------------------------------------------------------------------
# Reconciliation scaffolds
# --------------------------------------------------------------------------
def open_reconciliation(api, lot_id, business_date, headers=MGR) -> dict:
    """Open a reconciliation against a lot. Returns the reconciliation (carries
    its version for the OCC submit-count call)."""
    return new_reconciliation(api, business_date=business_date, bean_lot_id=lot_id, headers=headers)


def submit_recon_count(api, recon_id, counted_revenue_cents, counted_bean_on_hand_grams,
                       expected_version, headers=MGR) -> dict:
    return get_success_data(api.submit_count(
        recon_id,
        {"counted_revenue_cents": counted_revenue_cents,
         "counted_bean_on_hand_grams": counted_bean_on_hand_grams,
         "expected_reconciliation_version": expected_version},
        headers,
    ))


# --------------------------------------------------------------------------
# Subscription scaffolds
# --------------------------------------------------------------------------
def create_subscription(api, member_id, expected_member_version, headers=MGR, **overrides) -> dict:
    payload = F.create_subscription_payload(
        member_id=member_id, expected_member_version=expected_member_version, **overrides)
    return get_success_data(api.create_subscription(payload, headers))


# --------------------------------------------------------------------------
# Customer identity helper
# --------------------------------------------------------------------------
def customer_headers_for(member_id: str) -> dict:
    """Entity-backed Customer headers bound to a real Member.id (ownership calls)."""
    return make_customer_headers(member_id)
