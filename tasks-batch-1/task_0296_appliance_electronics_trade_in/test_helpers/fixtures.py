"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface clearly.

Identity threading: every ownership-gated Customer call uses
make_customer_headers(customer_id) with the actual Customer.id (PRD §2.1).

Because the harness restarts the server before every test, each fixture builds
all of its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_catalog_payload,
    create_device_model_payload,
    create_promotion_campaign_payload,
    create_customer_payload,
    create_trade_in_payload,
    inspect_payload,
    payout_payload,
    data_wipe_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
AGENT = TEST_USERS["grading_agent_headers"]
FINANCE = TEST_USERS["finance_operator_headers"]


# ─── Tier 0: Base config (catalog + model + customer) ─────────────

def create_catalog(**overrides):
    """Create a Catalog. Returns the catalog dict."""
    res = api_client.create_catalog(create_catalog_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_device_model(catalog_id, **overrides):
    """Register a DeviceModel under a catalog. Returns the model dict."""
    res = api_client.create_device_model(catalog_id, create_device_model_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_customer(**overrides):
    """Register a Customer. Returns the customer dict."""
    res = api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    return get_success_data(res)


def setup_catalog_model_customer(catalog_overrides=None, model_overrides=None):
    """Active catalog + one device model + one customer.

    Returns (catalog, model, customer).
    """
    catalog = create_catalog(**(catalog_overrides or {}))
    model = create_device_model(catalog["id"], **(model_overrides or {}))
    customer = create_customer()
    return catalog, model, customer


def create_promotion(catalog_id, **overrides):
    """Create a PromotionCampaign under a catalog. Returns the campaign dict."""
    res = api_client.create_promotion_campaign(catalog_id, create_promotion_campaign_payload(**overrides), ADMIN)
    return get_success_data(res)


def set_clock(to_iso8601):
    """Set the server logical clock (PRD §2.10). Returns the response body data."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: Trade-in lifecycle progression ───────────────────────

def create_draft_trade_in(customer, model, **trade_in_overrides):
    """Create a DRAFT trade-in owned by `customer`. Returns the trade-in dict."""
    res = api_client.create_trade_in(
        create_trade_in_payload(customer["id"], model["id"], **trade_in_overrides),
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def create_quoted_trade_in(customer, model, **trade_in_overrides):
    """Create a trade-in and quote it (DRAFT -> QUOTED). Returns the trade-in dict."""
    ti = create_draft_trade_in(customer, model, **trade_in_overrides)
    res = api_client.quote_trade_in(ti["id"], make_customer_headers(customer["id"]))
    return get_success_data(res)


def create_received_trade_in(customer, model, **trade_in_overrides):
    """Drive a trade-in DRAFT -> QUOTED -> KIT_SENT -> RECEIVED. Returns the trade-in dict."""
    ti = create_quoted_trade_in(customer, model, **trade_in_overrides)
    ch = make_customer_headers(customer["id"])
    get_success_data(api_client.ship_kit(ti["id"], ch))
    return get_success_data(api_client.receive_trade_in(ti["id"], AGENT))


def inspect(trade_in_id, verified_grade, verified_powers_on=True, verified_defects=None):
    """Submit inspection findings (RECEIVED -> INSPECTED -> fork). Returns the trade-in dict."""
    payload = inspect_payload(verified_grade, verified_powers_on)
    if verified_defects is not None:
        payload["verified_defects"] = verified_defects
    return get_success_data(api_client.inspect_trade_in(trade_in_id, payload, AGENT))


def setup_inspected_match(customer, model):
    """FLAWLESS trade-in inspected FLAWLESS -> MATCH auto-accept -> ACCEPTED at 60000.

    Returns the ACCEPTED trade-in dict.
    """
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")
    return inspect(ti["id"], "FLAWLESS", verified_defects=[])


def setup_requoted_trade_in(customer, model):
    """Trade-in driven to REQUOTED at inspected value 16000 (FAIR+WATER_DAMAGE on a 60000 model).

    Returns (trade_in_after_inspect, version) where version is read from the
    inspect response so OCC decisions can carry the fresh value.
    """
    ti = create_received_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    inspected = inspect(ti["id"], "FAIR", verified_defects=["WATER_DAMAGE"])
    return inspected, inspected["version"]


def setup_accepted_trade_in(customer, model, declared_grade="FLAWLESS"):
    """Trade-in driven to ACCEPTED via MATCH (FLAWLESS in & out -> 60000).

    Returns the ACCEPTED trade-in dict.
    """
    ti = create_received_trade_in(customer, model, declared_grade=declared_grade)
    return inspect(ti["id"], declared_grade, verified_defects=[])


def setup_paid_trade_in(customer, model, method="ACH"):
    """Trade-in driven all the way to PAID via MATCH-accept then payout.

    Returns (paid_trade_in, payout). Assumes the model's category is NOT in
    data_wipe_required_categories (caller controls the catalog).
    """
    accepted = setup_accepted_trade_in(customer, model)
    payout = get_success_data(api_client.create_payout(accepted["id"], payout_payload(method=method), FINANCE))
    paid = get_success_data(api_client.get_trade_in(accepted["id"], ADMIN))
    return paid, payout


def record_data_wipe(trade_in_id, method="NIST_PURGE", result="PASS"):
    """Record a data-wipe certificate against a trade-in. Returns the certificate dict."""
    return get_success_data(api_client.create_data_wipe(trade_in_id, data_wipe_payload(method, result), AGENT))


# ─── Tier 2: Read-back helpers ────────────────────────────────────

def get_quotes(trade_in_id, headers=None):
    """List a trade-in's quotes. Returns the list of quote dicts."""
    data, _meta = _paginated(api_client.list_quotes(trade_in_id, headers or ADMIN))
    return data


def get_inspections(trade_in_id, headers=None):
    data, _meta = _paginated(api_client.list_inspections(trade_in_id, headers or ADMIN))
    return data


def get_disposition_records(trade_in_id, headers=None):
    data, _meta = _paginated(api_client.list_disposition_records(trade_in_id, headers or ADMIN))
    return data


def get_payouts(trade_in_id, headers=None):
    data, _meta = _paginated(api_client.list_payouts(trade_in_id, headers or ADMIN))
    return data


def get_shipping_kits(trade_in_id, headers=None):
    data, _meta = _paginated(api_client.list_shipping_kits(trade_in_id, headers or ADMIN))
    return data


def _paginated(response):
    """Lenient list reader for setup: returns (data_list, meta)."""
    body = get_success_data(response)
    # get_success_data returns body["data"]; for list endpoints that is the array.
    if isinstance(body, list):
        meta = response.json().get("meta", {})
        return body, meta
    return body, {}
