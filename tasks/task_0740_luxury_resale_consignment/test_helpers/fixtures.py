"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures.

Identity threading (PRD §2.1): entity-backed Seller / Buyer calls always use
make_seller_headers(seller_id) / make_buyer_headers(buyer_id) with the real record
id so ownership checks (seller_id / buyer_id == X-User-ID) pass. Opaque roles
(OpsAdmin, Authenticator, ConciergeAgent) use the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_seller_payload, create_buyer_payload, create_category_policy_payload,
    create_item_payload, create_authenticate_payload, create_listing_payload,
    create_offer_payload, create_sale_payload, create_dispute_payload,
    create_resolve_payload, create_concierge_payload, create_vehicle_payload,
    create_pickup_payload,
)
from .test_users import (
    TEST_USERS, make_seller_headers, make_buyer_headers,
)

_ADMIN = TEST_USERS["ops_admin_headers"]
_AUTH = TEST_USERS["authenticator_headers"]
_CONCIERGE = TEST_USERS["concierge_agent_headers"]


# ─── Tier 0: Logical clock ──────────────────────────────────────────────────
def set_clock(iso8601: str) -> None:
    """Set the server logical clock (OpsAdmin, PRD §2.10)."""
    api_client.set_clock(iso8601, _ADMIN)


def reset_clock() -> None:
    set_clock(DEFAULT_CLOCK)


# ─── Tier 1: Single-resource creation ───────────────────────────────────────
def create_category_policy(category: str = "HANDBAGS", **overrides) -> dict:
    return get_success_data(api_client.create_category_policy(
        create_category_policy_payload(category=category, **overrides), _ADMIN))


def create_seller(**overrides) -> dict:
    return get_success_data(api_client.create_seller(create_seller_payload(**overrides), _ADMIN))


def create_buyer(**overrides) -> dict:
    return get_success_data(api_client.create_buyer(create_buyer_payload(**overrides), _ADMIN))


def create_concierge(**overrides) -> dict:
    return get_success_data(api_client.create_concierge(create_concierge_payload(**overrides), _ADMIN))


def create_vehicle(**overrides) -> dict:
    return get_success_data(api_client.create_vehicle(create_vehicle_payload(**overrides), _ADMIN))


def create_item(seller_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_item(
        create_item_payload(seller_id, **overrides), make_seller_headers(seller_id)))


def authenticate_item(item_id: str, verdict: str = "AUTHENTIC", condition_grade: str = "A") -> dict:
    return get_success_data(api_client.authenticate_item(
        item_id, create_authenticate_payload(verdict, condition_grade), _AUTH))


def create_listing(item_id: str, list_price_cents: int, seller_id: str) -> dict:
    return get_success_data(api_client.create_listing(
        create_listing_payload(item_id, list_price_cents), make_seller_headers(seller_id)))


def publish_listing(listing_id: str, seller_id: str) -> dict:
    return get_success_data(api_client.publish_listing(listing_id, make_seller_headers(seller_id)))


# ─── Readers ────────────────────────────────────────────────────────────────
def get_listing(listing_id: str) -> dict:
    return get_success_data(api_client.get_listing(listing_id, _ADMIN))


def get_item(item_id: str) -> dict:
    return get_success_data(api_client.get_item(item_id, _ADMIN))


def get_seller(seller_id: str) -> dict:
    return get_success_data(api_client.get_seller(seller_id, _ADMIN))


def get_buyer(buyer_id: str) -> dict:
    return get_success_data(api_client.get_buyer(buyer_id, _ADMIN))


def get_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_offer(offer_id, _ADMIN))


def get_sale(sale_id: str) -> dict:
    return get_success_data(api_client.get_sale(sale_id, _ADMIN))


def get_sale_by_listing(listing_id: str) -> dict:
    data, _meta = _paginate(api_client.list_sales(_ADMIN, params={"listing_id": listing_id}))
    return data[0]


def get_sale_payout(sale_id: str) -> dict:
    data, _meta = _paginate(api_client.list_sale_payouts(sale_id, _ADMIN))
    return data[0]


def _paginate(response):
    body = response.json()
    return body["data"], body.get("meta", {})


# ─── Offer / negotiation helpers ────────────────────────────────────────────
def make_offer(listing_id: str, buyer_id: str, amount_cents: int, expected_listing_version: int) -> dict:
    return get_success_data(api_client.create_offer(
        create_offer_payload(listing_id, buyer_id, amount_cents, expected_listing_version),
        make_buyer_headers(buyer_id)))


# ─── Sale / fulfilment helpers ──────────────────────────────────────────────
def direct_buy(listing_id: str, buyer_id: str) -> dict:
    return get_success_data(api_client.create_sale(
        create_sale_payload(listing_id, buyer_id), make_buyer_headers(buyer_id)))


def capture_payment(sale_id: str, buyer_id: str) -> dict:
    return get_success_data(api_client.capture_payment(sale_id, make_buyer_headers(buyer_id)))


def ship_sale(sale_id: str, seller_id: str) -> dict:
    return get_success_data(api_client.ship_sale(sale_id, make_seller_headers(seller_id)))


def confirm_delivery(sale_id: str, buyer_id: str) -> dict:
    return get_success_data(api_client.confirm_delivery(sale_id, make_buyer_headers(buyer_id)))


def file_dispute(sale_id: str, buyer_id: str, dtype: str, reason: str = "reason") -> dict:
    return get_success_data(api_client.create_dispute(
        create_dispute_payload(sale_id, dtype, reason), make_buyer_headers(buyer_id)))


def resolve_dispute(dispute_id: str, outcome: str) -> dict:
    return get_success_data(api_client.resolve_dispute(
        dispute_id, create_resolve_payload(outcome), _ADMIN))


def release_payout(payout_id: str) -> dict:
    return get_success_data(api_client.release_payout(payout_id, _ADMIN))


# ─── Tier 2: Composite scenarios ────────────────────────────────────────────
def setup_published_listing(list_price_cents: int = 200000, category: str = "HANDBAGS",
                            policy_overrides: dict = None, grade: str = "A") -> dict:
    """policy + seller + authenticated DROP_OFF item (AUTHENTIC/grade) + published ACTIVE listing.

    Returns a ctx dict with policy, seller, seller_id, item, item_id, listing, listing_id,
    and listing_version (the Listing.version after publish)."""
    policy = create_category_policy(category=category, **(policy_overrides or {}))
    seller = create_seller()
    item = create_item(seller["id"], category=category, declared_value_cents=list_price_cents)
    authenticate_item(item["id"], "AUTHENTIC", grade)
    listing = create_listing(item["id"], list_price_cents, seller["id"])
    listing = publish_listing(listing["id"], seller["id"])
    return {
        "policy": policy,
        "seller": seller, "seller_id": seller["id"],
        "item": item, "item_id": item["id"],
        "listing": listing, "listing_id": listing["id"],
        "listing_version": listing["version"],
    }


def setup_draft_listing(list_price_cents: int = 90000, category: str = "HANDBAGS",
                        policy_overrides: dict = None, authenticate: bool = True,
                        grade: str = "A") -> dict:
    """policy + seller + DROP_OFF item (optionally authenticated) + DRAFT listing (NOT published).

    When authenticate=False the item stays RECEIVED; when grade is below the policy
    threshold the item is AUTHENTICATED but not listable. Returns ctx dict."""
    policy = create_category_policy(category=category, **(policy_overrides or {}))
    seller = create_seller()
    item = create_item(seller["id"], category=category, declared_value_cents=list_price_cents)
    if authenticate:
        authenticate_item(item["id"], "AUTHENTIC", grade)
    listing = create_listing(item["id"], list_price_cents, seller["id"])
    return {
        "policy": policy,
        "seller": seller, "seller_id": seller["id"],
        "item": item, "item_id": item["id"],
        "listing": listing, "listing_id": listing["id"],
    }


def setup_direct_sale(list_price_cents: int = 180000, category: str = "HANDBAGS",
                      policy_overrides: dict = None) -> dict:
    """setup_published_listing + buyer + direct-buy Sale (payment PENDING, fulfilment
    AWAITING_SHIPMENT). Returns ctx dict extended with buyer, buyer_id, sale, sale_id."""
    ctx = setup_published_listing(list_price_cents=list_price_cents, category=category,
                                  policy_overrides=policy_overrides)
    buyer = create_buyer()
    sale = direct_buy(ctx["listing_id"], buyer["id"])
    ctx.update({"buyer": buyer, "buyer_id": buyer["id"], "sale": sale, "sale_id": sale["id"]})
    return ctx


def advance_to_delivered(sale_id: str, seller_id: str, buyer_id: str,
                         delivered_clock: str = None) -> dict:
    """capture-payment -> ship -> [set clock to delivered_clock] -> confirm-delivery.
    Returns the DELIVERED sale."""
    capture_payment(sale_id, buyer_id)
    ship_sale(sale_id, seller_id)
    if delivered_clock is not None:
        set_clock(delivered_clock)
    return confirm_delivery(sale_id, buyer_id)


def setup_delivered_sale(list_price_cents: int = 180000, category: str = "HANDBAGS",
                         policy_overrides: dict = None, delivered_clock: str = None) -> dict:
    """Full chain through DELIVERED: setup_direct_sale + capture + ship + confirm-delivery,
    which cascade-creates the seller's SCHEDULED Payout. Returns ctx dict extended with the
    delivered sale plus payout and payout_id."""
    ctx = setup_direct_sale(list_price_cents=list_price_cents, category=category,
                            policy_overrides=policy_overrides)
    sale = advance_to_delivered(ctx["sale_id"], ctx["seller_id"], ctx["buyer_id"],
                                delivered_clock=delivered_clock)
    payout = get_sale_payout(ctx["sale_id"])
    ctx.update({"sale": sale, "payout": payout, "payout_id": payout["id"]})
    return ctx


# ─── Tier 3: White-glove pickup resources ───────────────────────────────────
def setup_pickup_resources(category: str = "HANDBAGS", policy_overrides: dict = None,
                           concierge_names=("C1",), vehicle_plates=("V1",)) -> dict:
    """policy + seller + N concierges + M vehicles (all ACTIVE). Returns ctx dict with
    seller_id, concierges (list), vehicles (list)."""
    policy = create_category_policy(category=category, **(policy_overrides or {}))
    seller = create_seller()
    concierges = [create_concierge(name=n) for n in concierge_names]
    vehicles = [create_vehicle(plate=p) for p in vehicle_plates]
    return {
        "policy": policy,
        "seller": seller, "seller_id": seller["id"],
        "concierges": concierges,
        "vehicles": vehicles,
    }


def create_pickup_item(seller_id: str, declared_value_cents: int = 100000,
                       category: str = "HANDBAGS", **overrides) -> dict:
    """Create a PICKUP-channel item (starts INTAKE_REQUESTED)."""
    return create_item(seller_id, category=category, intake_channel="PICKUP",
                       declared_value_cents=declared_value_cents, **overrides)


def schedule_pickup(item_id: str, concierge_id: str, vehicle_id: str,
                    window_start: str, window_end: str, seller_id: str) -> dict:
    """Schedule a pickup as the owning Seller. Setup-only (expects success)."""
    return get_success_data(api_client.create_pickup(
        create_pickup_payload(item_id, concierge_id, vehicle_id, window_start, window_end),
        make_seller_headers(seller_id)))


# ─── Tier 4: Multiple delivered sales for one buyer (ledger scenarios) ───────
def setup_delivered_sales_for_buyer(count: int = 2, list_price_cents: int = 180000,
                                    category: str = "HANDBAGS", policy_overrides: dict = None) -> dict:
    """One policy + one seller + one buyer + `count` independent delivered direct-buy sales,
    each at list_price_cents and delivered at the current/default clock (each delivery
    cascade-creates a SCHEDULED payout). Returns ctx dict with policy, seller, seller_id,
    buyer, buyer_id, and a `sales` list of the delivered Sale dicts."""
    policy = create_category_policy(category=category, **(policy_overrides or {}))
    seller = create_seller()
    buyer = create_buyer()
    sales = []
    for i in range(count):
        item = create_item(seller["id"], category=category,
                           declared_value_cents=list_price_cents, title=f"Item {i + 1}")
        authenticate_item(item["id"], "AUTHENTIC", "A")
        listing = create_listing(item["id"], list_price_cents, seller["id"])
        listing = publish_listing(listing["id"], seller["id"])
        sale = direct_buy(listing["id"], buyer["id"])
        advance_to_delivered(sale["id"], seller["id"], buyer["id"])
        sales.append(get_sale(sale["id"]))
    return {
        "policy": policy,
        "seller": seller, "seller_id": seller["id"],
        "buyer": buyer, "buyer_id": buyer["id"],
        "sales": sales,
    }
