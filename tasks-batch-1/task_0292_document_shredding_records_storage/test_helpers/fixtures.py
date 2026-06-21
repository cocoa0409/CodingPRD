"""Composite setup helpers.

Encapsulates the multi-step API sequences that put the system into a specific
state so tests can focus on assertions. Every fixture builds its preconditions
from scratch (the server starts against an empty database before each test) and
uses get_success_data() so a setup failure surfaces a clear "Setup failed".

Operator identity threading: this PRD's roles use opaque X-User-IDs, but several
workflows record the acting operator (assigned_tech_id pinning, captured_by,
witnessed_by, SoD). Where a flow needs a specific operator id, the fixture
builds headers via make_*_headers(user_id) so the recorded identifier is
controllable and the segregation-of-duties counterparty can be pinned.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_field_technician_headers,
    make_plant_operator_headers,
    make_destruction_witness_headers,
)
from . import factories as f

CO = TEST_USERS["compliance_officer_headers"]
AM = TEST_USERS["account_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]

DEFAULT_TECH_ID = "tech-1"
DEFAULT_WITNESS_ID = "witness-9"
SLOT_START = "2026-07-01T09:00:00Z"
SLOT_END = "2026-07-01T10:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1 / 2: base scaffolding — account + location + active rate card
# ---------------------------------------------------------------------------
def create_account(compliance_regime="STANDARD", business_name="Test Business",
                   billing_email="b@x.com"):
    """Create an ACTIVE service account. Returns the account dict."""
    resp = api_client.create_account(
        f.create_account_payload(business_name=business_name,
                                 compliance_regime=compliance_regime,
                                 billing_email=billing_email),
        CO,
    )
    return get_success_data(resp)


def create_location(account_id, label="HQ", address="1 Main", **overrides):
    resp = api_client.create_location(
        f.create_location_payload(account_id, label=label, address=address, **overrides), AM)
    return get_success_data(resp)


def create_active_rate_card(account_id, **overrides):
    """Create a rate card and activate it. Returns the ACTIVE rate card dict."""
    resp = api_client.create_rate_card(f.create_rate_card_payload(account_id, **overrides), CO)
    card = get_success_data(resp)
    activated = api_client.activate_rate_card(card["id"], CO)
    return get_success_data(activated)


def setup_account_with_rate_card(compliance_regime="STANDARD", rate_overrides=None):
    """ACTIVE account + location + ACTIVE rate card.

    Returns (account, location, rate_card).
    """
    account = create_account(compliance_regime=compliance_regime)
    location = create_location(account["id"])
    rate_card = create_active_rate_card(account["id"], **(rate_overrides or {}))
    return account, location, rate_card


def create_container(account_id, location_id, container_type="CONSOLE",
                     capacity_kg=50, tare_weight_kg=8.0):
    resp = api_client.create_container(
        f.create_container_payload(account_id, location_id,
                                   container_type=container_type,
                                   capacity_kg=capacity_kg,
                                   tare_weight_kg=tare_weight_kg),
        AM,
    )
    return get_success_data(resp)


def create_order(account_id, location_id, container_ids=None, service_mode="ON_SITE",
                 cadence="SCHEDULED", assigned_tech_id=None,
                 scheduled_slot_start=SLOT_START, scheduled_slot_end=SLOT_END,
                 headers=None):
    payload = f.create_order_payload(
        account_id, location_id,
        service_mode=service_mode, cadence=cadence,
        scheduled_slot_start=scheduled_slot_start,
        scheduled_slot_end=scheduled_slot_end,
    )
    if container_ids is not None:
        payload["container_ids"] = container_ids
    if assigned_tech_id is not None:
        payload["assigned_tech_id"] = assigned_tech_id
    resp = api_client.create_order(payload, headers or AM)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: ServiceOrder lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_onsite_order_en_route(tech_id=DEFAULT_TECH_ID, container_specs=None,
                                weigh_in=False, gross_weight_kg=70.0,
                                compliance_regime="STANDARD"):
    """ACTIVE account + rate card; ON_SITE SCHEDULED order over the given
    containers, dispatched to EN_ROUTE (optionally weighed-in).

    container_specs: list of dicts with container_type/capacity_kg/tare_weight_kg.
                     Defaults to one CONSOLE (cap 50, tare 8.0).
    Returns dict with account, location, rate_card, containers, order.
    """
    if container_specs is None:
        container_specs = [{"container_type": "CONSOLE", "capacity_kg": 50, "tare_weight_kg": 8.0}]
    account, location, rate_card = setup_account_with_rate_card(compliance_regime=compliance_regime)
    containers = [create_container(account["id"], location["id"], **spec) for spec in container_specs]
    order = create_order(account["id"], location["id"],
                         container_ids=[c["id"] for c in containers],
                         service_mode="ON_SITE", cadence="SCHEDULED",
                         assigned_tech_id=tech_id)
    tech_headers = make_field_technician_headers(tech_id)
    get_success_data(api_client.dispatch_order(order["id"], tech_headers))
    if weigh_in:
        get_success_data(api_client.weigh_in_order(
            order["id"], f.weigh_in_payload(gross_weight_kg), tech_headers))
    return {
        "account": account, "location": location, "rate_card": rate_card,
        "containers": containers, "order": order, "tech_id": tech_id,
        "tech_headers": tech_headers,
    }


def setup_offsite_order_at_plant(tech_id=DEFAULT_TECH_ID, gross_weight_kg=36.0,
                                 capacity_kg=40, tare_weight_kg=4.0, cadence="ONE_TIME",
                                 compliance_regime="STANDARD"):
    """ACTIVE account + rate card; OFF_SITE_PICKUP order over one BIN driven to
    AT_PLANT (dispatch -> confirm-pickup -> weigh-in -> receive-at-plant).

    Returns dict with account, location, rate_card, container, order, tech_id.
    """
    account, location, rate_card = setup_account_with_rate_card(compliance_regime=compliance_regime)
    container = create_container(account["id"], location["id"],
                                 container_type="BIN", capacity_kg=capacity_kg,
                                 tare_weight_kg=tare_weight_kg)
    order = create_order(account["id"], location["id"],
                         container_ids=[container["id"]],
                         service_mode="OFF_SITE_PICKUP", cadence=cadence,
                         assigned_tech_id=tech_id)
    tech_headers = make_field_technician_headers(tech_id)
    get_success_data(api_client.dispatch_order(order["id"], tech_headers))
    get_success_data(api_client.confirm_pickup(order["id"], tech_headers))
    get_success_data(api_client.weigh_in_order(
        order["id"], f.weigh_in_payload(gross_weight_kg), PO))
    get_success_data(api_client.receive_at_plant(order["id"], PO))
    return {
        "account": account, "location": location, "rate_card": rate_card,
        "container": container, "order": order, "tech_id": tech_id,
        "tech_headers": tech_headers,
    }


def setup_offsite_order_destroyed(tech_id=DEFAULT_TECH_ID, witness_id=DEFAULT_WITNESS_ID,
                                  gross_weight_kg=36.0, capacity_kg=40, tare_weight_kg=4.0,
                                  cadence="ONE_TIME", compliance_regime="STANDARD"):
    """OFF_SITE order driven all the way to terminal DESTROYED with a witness
    distinct from the collector. Returns the same dict plus 'witness_id'.
    """
    state = setup_offsite_order_at_plant(tech_id=tech_id, gross_weight_kg=gross_weight_kg,
                                         capacity_kg=capacity_kg, tare_weight_kg=tare_weight_kg,
                                         cadence=cadence, compliance_regime=compliance_regime)
    witness_headers = make_destruction_witness_headers(witness_id)
    get_success_data(api_client.destroy_order(
        state["order"]["id"], f.destroy_payload(witness_id), witness_headers))
    state["witness_id"] = witness_id
    return state


def setup_onsite_order_shredded(tech_id=DEFAULT_TECH_ID, gross_weight_kg=70.0,
                                capacity_kg=50, tare_weight_kg=8.0,
                                compliance_regime="STANDARD"):
    """ON_SITE order driven to terminal ON_SITE_SHREDDED (certificate issued).

    Returns dict with account, location, rate_card, container, order, tech_id.
    """
    state = setup_onsite_order_en_route(
        tech_id=tech_id,
        container_specs=[{"container_type": "CONSOLE", "capacity_kg": capacity_kg,
                          "tare_weight_kg": tare_weight_kg}],
        weigh_in=True, gross_weight_kg=gross_weight_kg,
        compliance_regime=compliance_regime,
    )
    get_success_data(api_client.shred_on_site(state["order"]["id"], state["tech_headers"]))
    state["container"] = state["containers"][0]
    return state


# ---------------------------------------------------------------------------
# Tier: RetentionBox + RetrievalRequest lifecycles
# ---------------------------------------------------------------------------
def create_box(account_id, location_id, barcode="BX-1", **overrides):
    resp = api_client.create_retention_box(
        f.create_retention_box_payload(account_id, location_id, barcode, **overrides), AM)
    return get_success_data(resp)


def setup_stored_box(barcode="BX-1", free_periods=None, destroy_after_period=None,
                     with_rate_card=True, compliance_regime="STANDARD"):
    """ACTIVE account (+ optional rate card) + location; one box shelved STORED.

    Returns dict with account, location, rate_card (or None), box.
    """
    account = create_account(compliance_regime=compliance_regime)
    location = create_location(account["id"], label="Vault", address="2 Ave")
    rate_card = None
    if with_rate_card:
        rate_card = create_active_rate_card(account["id"])
    box_overrides = {}
    if free_periods is not None:
        box_overrides["free_periods"] = free_periods
    if destroy_after_period is not None:
        box_overrides["destroy_after_period"] = destroy_after_period
    box = create_box(account["id"], location["id"], barcode=barcode, **box_overrides)
    get_success_data(api_client.shelve_box(box["id"], PO))
    return {"account": account, "location": location, "rate_card": rate_card, "box": box}


def setup_ingested_box(barcode="BX-1", with_rate_card=True, compliance_regime="STANDARD"):
    """ACTIVE account (+ optional rate card) + location; one box INGESTED (not shelved)."""
    account = create_account(compliance_regime=compliance_regime)
    location = create_location(account["id"], label="Vault", address="2 Ave")
    rate_card = None
    if with_rate_card:
        rate_card = create_active_rate_card(account["id"])
    box = create_box(account["id"], location["id"], barcode=barcode)
    return {"account": account, "location": location, "rate_card": rate_card, "box": box}


def create_retrieval(box_id, account_id, priority="STANDARD", requested_by="mgr-1"):
    resp = api_client.create_retrieval_request(
        f.create_retrieval_request_payload(box_id, account_id, priority=priority,
                                            requested_by=requested_by), AM)
    return get_success_data(resp)


def setup_pending_retrieval(priority="STANDARD", barcode="BX-1"):
    """ACTIVE account + rate card; box shelved STORED; one PENDING retrieval.

    Returns dict with account, location, rate_card, box, request.
    """
    state = setup_stored_box(barcode=barcode)
    request = create_retrieval(state["box"]["id"], state["account"]["id"], priority=priority)
    state["request"] = request
    return state


def setup_delivered_retrieval(priority="STANDARD", barcode="BX-1"):
    """Retrieval fulfilled (DELIVERED); box OUT_FOR_RETRIEVAL."""
    state = setup_pending_retrieval(priority=priority, barcode=barcode)
    get_success_data(api_client.fulfill_retrieval(state["request"]["id"], PO))
    return state


def setup_return_pending_retrieval(priority="STANDARD", barcode="BX-1"):
    """Retrieval DELIVERED then start-return -> RETURN_PENDING."""
    state = setup_delivered_retrieval(priority=priority, barcode=barcode)
    get_success_data(api_client.start_return(state["request"]["id"], AM))
    return state


# ---------------------------------------------------------------------------
# ComplianceHold helper
# ---------------------------------------------------------------------------
def place_hold(account_id, subject_type, subject_id, reason="LITIGATION_HOLD"):
    resp = api_client.create_compliance_hold(
        f.create_compliance_hold_payload(account_id, subject_type, subject_id, reason=reason), CO)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Period / storage-credit helpers
# ---------------------------------------------------------------------------
def credit_account(account_id, amount_cents):
    resp = api_client.credit_account(account_id, f.credit_payload(amount_cents), CO)
    return get_success_data(resp)


def advance_period(account_id):
    """Close the current period, emit a StorageInvoice, advance the clock.

    Returns the emitted StorageInvoice dict.
    """
    resp = api_client.advance_period(account_id, CO)
    return get_success_data(resp)
