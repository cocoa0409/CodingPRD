"""Composite setup helpers.

Every test starts against a fresh, empty database (the runner restarts the
server before each test), so these helpers build all preconditions from scratch
using only PRD-declared endpoints. Setup calls use the lenient get_success_data
validator so a broken precondition surfaces as a clear "Setup step failed".

Identity threading (PRD §2.1): AccountManager is entity_backed:CorporateAccount.
Every ownership-gated AccountManager call in these fixtures uses per-instance
headers built via make_account_manager_headers(account["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_account_manager_headers,
)
from . import factories as f

ADMIN = TEST_USERS["platform_admin_headers"]
FIN = TEST_USERS["finance_approver_headers"]
PROOF = TEST_USERS["proof_approver_headers"]
WH = TEST_USERS["warehouse_ops_headers"]
SHIP = TEST_USERS["shipping_ops_headers"]


# ─── Tier 0: granular creators ─────────────────────────────────────────────

def create_account(api=api_client, *, monthly_budget_cents=1_000_000,
                   approval_threshold_cents=100_000, name=None,
                   billing_email=None):
    payload = f.create_account_payload(name=name, billing_email=billing_email,
                                       monthly_budget_cents=monthly_budget_cents,
                                       approval_threshold_cents=approval_threshold_cents)
    return get_success_data(api.create_account(payload, ADMIN))


def create_sku(api=api_client, *, name="SKU", unit_cost_cents=500,
               is_perishable=False, shelf_life_days=None, on_hand_qty=100):
    payload = f.create_sku_payload(name=name, unit_cost_cents=unit_cost_cents,
                                   is_perishable=is_perishable,
                                   shelf_life_days=shelf_life_days,
                                   on_hand_qty=on_hand_qty)
    return get_success_data(api.create_sku(payload, ADMIN))


def create_template(api=api_client, *, name="Basket", category="CORPORATE_WELCOME",
                    base_price_cents=4000, is_perishable=False,
                    shelf_life_days=None, sku_id=None, quantity_per_basket=1,
                    components=None, active=True):
    if components is None:
        assert sku_id is not None, "provide sku_id or explicit components"
        components = [{"sku_id": sku_id, "quantity": quantity_per_basket}]
    payload = f.create_template_payload(name=name, category=category,
                                        base_price_cents=base_price_cents,
                                        is_perishable=is_perishable,
                                        shelf_life_days=shelf_life_days,
                                        components=components, active=active)
    return get_success_data(api.create_template(payload, ADMIN))


def create_station(api=api_client, *, name="Station", daily_capacity=1000):
    payload = f.create_station_payload(name=name, daily_capacity=daily_capacity)
    return get_success_data(api.create_assembly_station(payload, ADMIN))


def create_shipping_zone(api=api_client, **overrides):
    payload = f.create_shipping_zone_payload(**overrides)
    return get_success_data(api.create_shipping_zone(payload, ADMIN))


def create_branding_profile(api=api_client, *, account, name="Kit",
                            logo_url="https://cdn.example/logo.png",
                            accent_color="#112233", card_stock="MATTE"):
    payload = f.create_branding_profile_payload(
        name=name, logo_url=logo_url, accent_color=accent_color,
        card_stock=card_stock,
        expected_corporate_account_version=account["version"])
    hdrs = make_account_manager_headers(account["id"])
    return get_success_data(api.create_branding_profile(account["id"], payload, hdrs))


def approve_branding_profile(api=api_client, *, profile_id):
    return get_success_data(api.approve_branding_profile(profile_id, ADMIN))


def get_account(api=api_client, *, account_id):
    """Re-fetch to observe current version (bumped by branding/order create/PATCH)."""
    return get_success_data(api.get_account(account_id, ADMIN))


def create_order(api=api_client, *, account, template_id, occasion="ONBOARDING",
                 branding_profile_id=None, scheduled_send_date=None):
    payload = f.create_order_payload(
        template_id=template_id, occasion=occasion,
        branding_profile_id=branding_profile_id,
        scheduled_send_date=scheduled_send_date,
        expected_corporate_account_version=account["version"])
    hdrs = make_account_manager_headers(account["id"])
    return get_success_data(api.create_order(account["id"], payload, hdrs))


def import_recipients(api=api_client, *, account_id, order_id, rows):
    hdrs = make_account_manager_headers(account_id)
    return get_success_data(
        api.import_recipients(order_id, {"rows": rows}, hdrs))


def submit_for_approval(api=api_client, *, account_id, order_id,
                        requested_by_user_id="emp-req-1",
                        station_id=None, scheduled_date=None):
    payload = f.submit_for_approval_payload(
        requested_by_user_id=requested_by_user_id,
        station_id=station_id, scheduled_date=scheduled_date)
    hdrs = make_account_manager_headers(account_id)
    return get_success_data(api.submit_for_approval(order_id, payload, hdrs))


def budget_decision(api=api_client, *, order_id, decision,
                    approver_user_id="fin-appr-1", decision_reason=None,
                    station_id=None, scheduled_date=None):
    payload = f.budget_decision_payload(
        decision=decision, approver_user_id=approver_user_id,
        decision_reason=decision_reason,
        station_id=station_id, scheduled_date=scheduled_date)
    return get_success_data(api.budget_decision(order_id, payload, FIN))


def submit_message_proof(api=api_client, *, account_id, recipient_id,
                         message_text="Hello!", submitted_by_user_id="emp-msg-1"):
    payload = f.message_proof_payload(
        message_text=message_text, submitted_by_user_id=submitted_by_user_id)
    hdrs = make_account_manager_headers(account_id)
    return get_success_data(api.submit_message_proof(recipient_id, payload, hdrs))


def decide_message_proof(api=api_client, *, proof_id, decision,
                         decided_by_user_id="proof-appr-1"):
    payload = f.proof_decision_payload(
        decision=decision, decided_by_user_id=decided_by_user_id)
    return get_success_data(api.decide_message_proof(proof_id, payload, PROOF))


def create_shipment(api=api_client, *, recipient_id, zone_id, ship_date):
    payload = f.create_shipment_payload(zone_id=zone_id, ship_date=ship_date)
    return get_success_data(api.create_shipment(recipient_id, payload, SHIP))


def advance_shipment(api=api_client, *, shipment_id, target_status):
    return get_success_data(
        api.advance_shipment(shipment_id, {"target_status": target_status}, SHIP))


def advance_assembly_task(api=api_client, *, task_id, target_status):
    return get_success_data(
        api.advance_assembly_task(task_id, {"target_status": target_status}, WH))


def find_task_for_recipient(api=api_client, *, recipient_id):
    data = get_success_data(api.list_assembly_tasks(WH, params={"recipient_id": recipient_id}))
    return data[0] if data else None


def find_reservation_for_recipient(api=api_client, *, recipient_id):
    data = get_success_data(
        api.list_inventory_reservations(WH, params={"recipient_id": recipient_id}))
    return data[0] if data else None


def set_clock(api=api_client, *, to_iso8601):
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ─── Tier 1: catalog + account baseline ────────────────────────────────────

def setup_catalog(api=api_client, *, monthly_budget_cents=1_000_000,
                  approval_threshold_cents=100_000,
                  sku_kwargs=None, template_kwargs=None,
                  station_capacity=1000):
    """One account + one SKU + one template + one assembly station.
    Returns dict(account, sku, template, station)."""
    account = create_account(api,
                             monthly_budget_cents=monthly_budget_cents,
                             approval_threshold_cents=approval_threshold_cents)
    sku = create_sku(api, **(sku_kwargs or {}))
    tmpl_kwargs = dict(sku_id=sku["id"])
    tmpl_kwargs.update(template_kwargs or {})
    template = create_template(api, **tmpl_kwargs)
    station = create_station(api, daily_capacity=station_capacity)
    return {"account": account, "sku": sku, "template": template, "station": station}


# ─── Tier 2: order + recipient(s) imported ─────────────────────────────────

def setup_order_with_recipients(api=api_client, *, account, template_id,
                                rows, occasion="ONBOARDING",
                                branding_profile_id=None,
                                scheduled_send_date=None):
    """Create a DRAFT order and import the given rows. Returns
    (order, imported_recipients_list)."""
    order = create_order(api, account=account, template_id=template_id,
                         occasion=occasion,
                         branding_profile_id=branding_profile_id,
                         scheduled_send_date=scheduled_send_date)
    recipients = import_recipients(api, account_id=account["id"],
                                   order_id=order["id"], rows=rows)
    return order, recipients


# ─── Tier 3: order submitted, PENDING_APPROVAL awaiting human decision ─────

def setup_pending_approval_order(api=api_client, *, base, rows=None,
                                 requested_by_user_id="emp-req-1",
                                 occasion="ONBOARDING",
                                 branding_profile_id=None,
                                 scheduled_send_date=None):
    """Full setup: catalog → order → recipients → submit-for-approval.
    Requires that the account's approval_threshold_cents forces a human decision
    (i.e., the order does not auto-approve). Returns dict(order, recipients).
    `base` is a dict as returned by setup_catalog (account/sku/template/station).
    """
    if rows is None:
        rows = [f.recipient_row(quantity=5)]
    order, recipients = setup_order_with_recipients(
        api, account=base["account"], template_id=base["template"]["id"],
        rows=rows, occasion=occasion,
        branding_profile_id=branding_profile_id,
        scheduled_send_date=scheduled_send_date)
    submit_for_approval(api, account_id=base["account"]["id"],
                        order_id=order["id"],
                        requested_by_user_id=requested_by_user_id)
    return {"order": order, "recipients": recipients}


# ─── Tier 4: fully approved order (Cascade A already fired) ────────────────

def setup_approved_order(api=api_client, *, base, rows=None,
                         requested_by_user_id="emp-req-1",
                         approver_user_id="fin-appr-9",
                         scheduled_date="2026-03-04T00:00:00Z",
                         branding_profile_id=None,
                         scheduled_send_date=None,
                         occasion="ONBOARDING"):
    """Full setup through APPROVED (production_status=ASSEMBLING).
    Returns dict(order, recipients)."""
    p = setup_pending_approval_order(
        api, base=base, rows=rows,
        requested_by_user_id=requested_by_user_id,
        occasion=occasion,
        branding_profile_id=branding_profile_id,
        scheduled_send_date=scheduled_send_date)
    budget_decision(api, order_id=p["order"]["id"], decision="APPROVE",
                    approver_user_id=approver_user_id,
                    station_id=base["station"]["id"],
                    scheduled_date=scheduled_date)
    return p


# ─── Tier 5: recipient with LOCKED message proof (Shipment gate cleared) ────

def lock_message_proof_for_recipient(api=api_client, *, account_id, recipient_id,
                                     message_text="Hello!",
                                     submitted_by="emp-msg-lock",
                                     decided_by="proof-appr-lock"):
    """Submit and APPROVE a proof for one recipient; auto-advances SUBMITTED →
    APPROVED → LOCKED. Returns the proof dict (after decision)."""
    proof = submit_message_proof(api, account_id=account_id,
                                 recipient_id=recipient_id,
                                 message_text=message_text,
                                 submitted_by_user_id=submitted_by)
    return decide_message_proof(api, proof_id=proof["id"], decision="APPROVE",
                                decided_by_user_id=decided_by)
