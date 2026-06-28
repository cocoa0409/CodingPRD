"""Composite setup helpers for multi-step test prerequisites.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty DB before every test).
All setup calls use get_success_data() (lenient validator) so a broken
precondition surfaces as a clear "Setup step failed" error.

The CampaignAdmin runs the program; the Treasurer reconciles/disburses. A seller
is added before activation because activation requires >= 1 seller (PRD §3.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_campaign_payload, create_prize_tier_payload, create_seller_payload,
    create_product_payload, create_order_payload, order_line,
    create_pledge_payload, create_volunteer_payload, create_shift_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["campaign_admin_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


# ─── Tier 1: Campaign creation / posture progression ──────────────────────

def create_campaign(campaign_type="CATALOG", profit_split_pct=0.50, **overrides):
    """Create a DRAFT campaign. Returns the campaign object."""
    payload = create_campaign_payload(
        campaign_type=campaign_type, profit_split_pct=profit_split_pct, **overrides)
    return get_success_data(api_client.create_campaign(payload, ADMIN))


def add_prize_tier(campaign_id, **overrides):
    return get_success_data(api_client.create_prize_tier(
        create_prize_tier_payload(campaign_id, **overrides), ADMIN))


def add_seller(campaign_id, **overrides):
    return get_success_data(api_client.create_seller(
        create_seller_payload(campaign_id, **overrides), ADMIN))


def add_product(campaign_id, **overrides):
    return get_success_data(api_client.create_product(
        create_product_payload(campaign_id, **overrides), ADMIN))


def create_and_activate_campaign(campaign_type="CATALOG", profit_split_pct=0.50,
                                 with_prize_tier=True, **overrides):
    """Create campaign + 1 seller (+ optional prize tier) + activate.

    Returns (campaign_after_activation, seller). EVENT campaigns need no prize
    tier for activation, so with_prize_tier may be False there.
    """
    camp = create_campaign(campaign_type=campaign_type,
                           profit_split_pct=profit_split_pct, **overrides)
    if with_prize_tier:
        add_prize_tier(camp["id"], label="T1", threshold_cents=5000)
    seller = add_seller(camp["id"])
    activated = get_success_data(api_client.activate_campaign(camp["id"], ADMIN))
    return activated, seller


def setup_active_catalog(profit_split_pct=0.50, stock_qty=100,
                         unit_price_cents=2000, unit_cost_cents=800,
                         prize_threshold_cents=5000):
    """Active CATALOG campaign + 1 seller + 1 prize tier + 1 product.

    Returns (campaign, seller, product).
    """
    camp = create_campaign(campaign_type="CATALOG", profit_split_pct=profit_split_pct)
    add_prize_tier(camp["id"], label="T1", threshold_cents=prize_threshold_cents)
    seller = add_seller(camp["id"])
    product = add_product(camp["id"], sku="WRAP", name="Wrap",
                          unit_price_cents=unit_price_cents,
                          unit_cost_cents=unit_cost_cents, stock_qty=stock_qty)
    activated = get_success_data(api_client.activate_campaign(camp["id"], ADMIN))
    return activated, seller, product


def setup_active_pledge(profit_split_pct=1.0, prize_threshold_cents=1000):
    """Active PLEDGE campaign + 1 seller + 1 prize tier. Returns (campaign, seller)."""
    camp = create_campaign(campaign_type="PLEDGE", profit_split_pct=profit_split_pct,
                           vendor_name="Self")
    add_prize_tier(camp["id"], label="T1", threshold_cents=prize_threshold_cents)
    seller = add_seller(camp["id"])
    activated = get_success_data(api_client.activate_campaign(camp["id"], ADMIN))
    return activated, seller


def setup_active_event(profit_split_pct=1.0):
    """Active EVENT campaign + 1 seller (for activation). EVENT needs no prize
    tier. Returns (campaign, seller)."""
    camp = create_campaign(campaign_type="EVENT", profit_split_pct=profit_split_pct,
                           vendor_name="Self")
    seller = add_seller(camp["id"])
    activated = get_success_data(api_client.activate_campaign(camp["id"], ADMIN))
    return activated, seller


# ─── Tier 2: Orders ───────────────────────────────────────────────────────

def place_order(campaign_id, seller_id, lines, headers=None):
    """Place a catalog order. `lines` is a list of order_line() dicts."""
    return get_success_data(api_client.create_order(
        create_order_payload(campaign_id, seller_id, lines), headers or ADMIN))


def place_simple_order(campaign_id, seller_id, product_id, quantity):
    """Place a one-line order. Returns the order object (PENDING + PLACED)."""
    return place_order(campaign_id, seller_id, [order_line(product_id, quantity)])


def place_and_pay_order(campaign_id, seller_id, product_id, quantity):
    """Place a one-line order and pay it. Returns the paid order object."""
    order = place_simple_order(campaign_id, seller_id, product_id, quantity)
    return get_success_data(api_client.pay_order(order["id"], ADMIN))


# ─── Tier 3: Pledges ──────────────────────────────────────────────────────

def create_pledge(campaign_id, seller_id, per_unit_cents, headers=None, **overrides):
    return get_success_data(api_client.create_pledge(
        create_pledge_payload(campaign_id, seller_id, per_unit_cents, **overrides),
        headers or ADMIN))


def create_recorded_pledge(campaign_id, seller_id, per_unit_cents,
                           units_recorded, **overrides):
    """Create a pledge then record it. Returns the recorded pledge object."""
    pledge = create_pledge(campaign_id, seller_id, per_unit_cents, **overrides)
    return get_success_data(api_client.record_pledge(
        pledge["id"], {"units_recorded": units_recorded}, ADMIN))


def create_collected_pledge(campaign_id, seller_id, per_unit_cents,
                            units_recorded, **overrides):
    """Create -> record -> collect a pledge. Returns the collected pledge object."""
    recorded = create_recorded_pledge(campaign_id, seller_id, per_unit_cents,
                                      units_recorded, **overrides)
    return get_success_data(api_client.collect_pledge(recorded["id"], ADMIN))


# ─── Tier 4: Reconciliation / disbursement lifecycle ──────────────────────

def close_campaign(campaign_id):
    """Close a campaign. Returns the closed campaign (carries post-close version)."""
    return get_success_data(api_client.close_campaign(campaign_id, ADMIN))


def reconcile_campaign(campaign_id, expected_version):
    """Reconcile a CLOSED campaign with the given expected version."""
    return get_success_data(api_client.reconcile_campaign(
        campaign_id, {"expected_campaign_version": expected_version}, TREASURER))


def disburse_campaign(campaign_id, expected_version, memo=None):
    """Disburse a RECONCILED campaign with the given expected version."""
    payload = {"expected_campaign_version": expected_version}
    if memo is not None:
        payload["memo"] = memo
    return get_success_data(api_client.disburse_campaign(campaign_id, payload, TREASURER))


def setup_reconciled_profit_split():
    """Build a CLOSED->RECONCILED campaign with psp 0.60, one PAID 5-unit order
    @ price 2000 / cost 800 (gross 10000, tax 825) and one COLLECTED pledge of
    5000, then reconcile. Yields school_profit 6600 / vendor_payable 8400.

    Returns (reconciled_campaign, post_reconcile_version, post_close_version).
    """
    camp, seller, product = setup_active_catalog(profit_split_pct=0.60)
    place_and_pay_order(camp["id"], seller["id"], product["id"], 5)
    create_collected_pledge(camp["id"], seller["id"], per_unit_cents=0,
                            units_recorded=0, flat_cents=5000)
    closed = close_campaign(camp["id"])
    reconciled = reconcile_campaign(camp["id"], closed["version"])
    return reconciled, reconciled["version"], closed["version"]


def setup_closed_for_reconcile(campaign_type="PLEDGE", profit_split_pct=1.0):
    """Drive a campaign (no settled money) to CLOSED. Returns (campaign, post_close_version)."""
    if campaign_type == "PLEDGE":
        camp, _ = setup_active_pledge(profit_split_pct=profit_split_pct)
    elif campaign_type == "EVENT":
        camp, _ = setup_active_event(profit_split_pct=profit_split_pct)
    else:
        camp, _, _ = setup_active_catalog(profit_split_pct=profit_split_pct)
    closed = close_campaign(camp["id"])
    return closed, closed["version"]


def setup_disbursed_campaign():
    """Drive a campaign all the way through DISBURSED. Returns
    (campaign_after_disburse, post_disburse_version)."""
    closed, v_closed = setup_closed_for_reconcile(campaign_type="PLEDGE")
    reconciled = reconcile_campaign(closed["id"], v_closed)
    disbursed = disburse_campaign(closed["id"], reconciled["version"])
    return disbursed, disbursed["version"]


# ─── Tier 5: Volunteers / shifts ──────────────────────────────────────────

def add_volunteer(campaign_id, **overrides):
    return get_success_data(api_client.create_volunteer(
        create_volunteer_payload(campaign_id, **overrides), ADMIN))


def add_shift(campaign_id, starts_at, ends_at, **overrides):
    return get_success_data(api_client.create_shift(
        create_shift_payload(campaign_id, starts_at, ends_at, **overrides), ADMIN))


def book_shift(shift_id, volunteer_id):
    return get_success_data(api_client.book_shift(
        shift_id, {"volunteer_id": volunteer_id}, ADMIN))


def setup_event_with_booked_shift(shift_a_start="2026-04-10T09:00:00Z",
                                  shift_a_end="2026-04-10T12:00:00Z",
                                  shift_a_buffer=0):
    """Active EVENT campaign + 1 volunteer + one BOOKED shift A.

    Returns (campaign, volunteer, shift_a).
    """
    camp, _ = setup_active_event()
    volunteer = add_volunteer(camp["id"])
    shift_a = add_shift(camp["id"], shift_a_start, shift_a_end,
                        role_label="A", setup_buffer_minutes=shift_a_buffer)
    booked_a = book_shift(shift_a["id"], volunteer["id"])
    return camp, volunteer, booked_a
