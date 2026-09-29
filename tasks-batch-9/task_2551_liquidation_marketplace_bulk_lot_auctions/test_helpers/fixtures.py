"""Composite setup helpers.

Every helper builds its state from scratch through PRD endpoints, because the
API under test starts from an empty database for each test. Setup calls use the
lenient success validator so a broken precondition surfaces as a clear setup
failure rather than as a confusing assertion deeper in a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AUCTION_OPENING_BID_CENTS,
    AUCTION_RESERVE_PRICE_CENTS,
    AUCTION_WINDOW_END,
    AUCTION_WINDOW_START,
    CANONICAL_CREDIT_LIMIT_CENTS,
    CANONICAL_LOT_LINES,
    CLOCK_START,
    DEFAULT_BID_INCREMENT_CENTS,
    INSIDE_WINDOW_CLOCK,
    LONG_WINDOW_END,
    SMALL_LOT_LINES,
)
from .factories import (
    auction_listing_payload,
    bid_payload,
    brand_policy_payload,
    carrier_payload,
    claim_decision_payload,
    claim_payload,
    clock_payload,
    completion_payload,
    counter_offer_payload,
    credit_limit_payload,
    fixed_price_listing_payload,
    lot_payload,
    manifest_line_payload,
    manifest_review_payload,
    negotiated_listing_payload,
    negotiation_payload,
    payment_payload,
    pickup_appointment_payload,
    qualification_decision_payload,
    seller_account_payload,
    warehouse_payload,
    buyer_account_payload,
)
from .test_users import (
    TEST_USERS,
    make_buyer_headers,
    make_seller_ops_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["marketplace_ops_reviewer_headers"]
CLOSER = TEST_USERS["marketplace_ops_closer_headers"]
DOCK_OPS = TEST_USERS["marketplace_ops_dock_headers"]
SWEEPER = TEST_USERS["marketplace_ops_sweeper_headers"]
CLAIMS_OPS = TEST_USERS["marketplace_ops_claims_headers"]
TRUST_SAFETY = TEST_USERS["trust_safety_headers"]


# ─── Tier 1: single-entity primitives ─────────────────

def set_clock(current_utc: str, headers=None) -> dict:
    """Move the logical clock. Open to every role; no business row changes."""
    return get_success_data(
        api_client.set_current_utc(clock_payload(current_utc), headers or ADMIN)
    )


def create_seller(**overrides) -> dict:
    return get_success_data(
        api_client.create_seller_account(seller_account_payload(**overrides), ADMIN)
    )


def create_warehouse(**overrides) -> dict:
    return get_success_data(
        api_client.create_warehouse(warehouse_payload(**overrides), ADMIN)
    )


def create_carrier(**overrides) -> dict:
    return get_success_data(api_client.create_carrier(carrier_payload(**overrides), ADMIN))


def create_brand_policy(brand_code="ARCLIGHT", permitted_channels=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_brand_policy(
            brand_policy_payload(brand_code, permitted_channels, **overrides), ADMIN
        )
    )


def create_buyer(*, qualify=True, credit_limit_cents=CANONICAL_CREDIT_LIMIT_CENTS,
                 **overrides) -> dict:
    """Register a buyer, then (by default) qualify it and approve a credit limit."""
    buyer = get_success_data(
        api_client.create_buyer_account(buyer_account_payload(**overrides), ADMIN)
    )
    if qualify:
        buyer = get_success_data(
            api_client.decide_buyer_qualification(
                buyer["id"], qualification_decision_payload("QUALIFY"), TRUST_SAFETY
            )
        )
    if credit_limit_cents is not None:
        buyer = get_success_data(
            api_client.set_buyer_credit_limit(
                buyer["id"], credit_limit_payload(credit_limit_cents), ADMIN
            )
        )
    return buyer


# ─── Tier 2: reference-data bootstrap ─────────────────

def bootstrap_marketplace(*, clock=CLOCK_START, seller_overrides=None,
                          warehouse_overrides=None, carrier_overrides=None,
                          buyer_overrides=None,
                          credit_limit_cents=CANONICAL_CREDIT_LIMIT_CENTS,
                          with_carrier=True, with_buyer=True,
                          qualify_buyer=True) -> dict:
    """Seller + warehouse + carrier + qualified buyer, with the logical clock
    parked where the caller wants it.

    Returns a dict carrying every row plus the ownership-threaded headers:
    seller, seller_headers, warehouse, carrier, buyer, buyer_headers.
    """
    if clock is not None and clock != CLOCK_START:
        set_clock(clock)
    seller = create_seller(**(seller_overrides or {}))
    warehouse = create_warehouse(**(warehouse_overrides or {}))
    env = {
        "seller": seller,
        "seller_headers": make_seller_ops_headers(seller["id"]),
        "warehouse": warehouse,
        "carrier": None,
        "buyer": None,
        "buyer_headers": None,
        "admin_headers": ADMIN,
        "reviewer_headers": REVIEWER,
        "closer_headers": CLOSER,
        "dock_headers": DOCK_OPS,
        "sweeper_headers": SWEEPER,
        "claims_headers": CLAIMS_OPS,
        "trust_safety_headers": TRUST_SAFETY,
    }
    if with_carrier:
        env["carrier"] = create_carrier(**(carrier_overrides or {}))
    if with_buyer:
        buyer = create_buyer(
            qualify=qualify_buyer, credit_limit_cents=credit_limit_cents,
            **(buyer_overrides or {})
        )
        env["buyer"] = buyer
        env["buyer_headers"] = make_buyer_headers(buyer["id"])
    return env


def add_buyer(env, *, tax_id="B-2002", legal_name="Ridge Wholesale Inc",
              state_code="AZ", contact_email="buying@ridgewholesale.example",
              resale_certificate_number="AZ-RC-31",
              resale_certificate_expires_on="2027-01-31",
              qualify=True, credit_limit_cents=CANONICAL_CREDIT_LIMIT_CENTS,
              **overrides) -> dict:
    """Register a second (or third) buyer alongside the bootstrap buyer."""
    buyer = create_buyer(
        qualify=qualify, credit_limit_cents=credit_limit_cents,
        tax_id=tax_id, legal_name=legal_name, state_code=state_code,
        contact_email=contact_email,
        resale_certificate_number=resale_certificate_number,
        resale_certificate_expires_on=resale_certificate_expires_on,
        **overrides,
    )
    env.setdefault("extra_buyers", []).append(buyer)
    return buyer


# ─── Tier 3: lots and manifests ───────────────────────

def create_lot_with_lines(env, lines=None, *, warehouse_id=None, **lot_overrides) -> dict:
    """Create a DRAFT lot and append its manifest lines.

    Returns {"lot": <lot after the last line>, "lines": [<line>, ...]}.
    """
    lines = CANONICAL_LOT_LINES if lines is None else lines
    payload = lot_payload(
        env["seller"]["id"], warehouse_id or env["warehouse"]["id"], **lot_overrides
    )
    lot = get_success_data(api_client.create_lot(payload, env["seller_headers"]))
    created = []
    for line in lines:
        created.append(
            get_success_data(
                api_client.create_manifest_line(
                    lot["id"], manifest_line_payload(**line), env["seller_headers"]
                )
            )
        )
    lot = get_success_data(api_client.get_lot(lot["id"], env["seller_headers"]))
    return {"lot": lot, "lines": created}


def submit_manifest(env, lot_id) -> dict:
    return get_success_data(api_client.submit_manifest(lot_id, {}, env["seller_headers"]))


def review_manifest(env, lot_id, decision="APPROVE", reviewer_headers=None,
                    **overrides) -> dict:
    return get_success_data(
        api_client.review_manifest(
            lot_id, manifest_review_payload(decision, **overrides),
            reviewer_headers or env["reviewer_headers"],
        )
    )


def setup_approved_lot(env, lines=None, *, reviewer_headers=None, **lot_overrides) -> dict:
    """DRAFT lot -> lines -> submission -> MarketplaceOps approval.

    Returns {"lot": <MANIFEST_APPROVED lot>, "lines": [...]}.
    """
    built = create_lot_with_lines(env, lines, **lot_overrides)
    submit_manifest(env, built["lot"]["id"])
    lot = review_manifest(env, built["lot"]["id"], "APPROVE", reviewer_headers)
    return {"lot": lot, "lines": built["lines"]}


# ─── Tier 4: listings ─────────────────────────────────

def create_listing(env, lot_id, payload) -> dict:
    return get_success_data(api_client.create_listing(lot_id, payload, env["seller_headers"]))


def publish_listing(env, listing_id) -> dict:
    return get_success_data(api_client.publish_listing(listing_id, {}, env["seller_headers"]))


def setup_open_auction(env=None, *, lines=None, lot_overrides=None,
                       listing_overrides=None, clock=None) -> dict:
    """Approved lot + published AUCTION listing.

    Defaults to the canonical shape: a 400-unit / 10000000-cent CUSTOMER_RETURNS
    lot under an auction with opening_bid_cents 1000000, reserve_price_cents
    2700000 and bid_increment_cents 100000 over
    [2026-08-05T00:00:00Z, 2026-08-12T00:00:00Z).

    Returns {"env", "lot", "lines", "listing"}.
    """
    env = env or bootstrap_marketplace()
    built = setup_approved_lot(env, lines, **(lot_overrides or {}))
    listing = create_listing(
        env, built["lot"]["id"], auction_listing_payload(**(listing_overrides or {}))
    )
    listing = publish_listing(env, listing["id"])
    if clock:
        set_clock(clock)
    return {"env": env, "lot": built["lot"], "lines": built["lines"], "listing": listing}


def setup_open_fixed_price(env=None, *, ask_price_cents=1_000_000, lines=None,
                           lot_overrides=None, listing_overrides=None,
                           clock=INSIDE_WINDOW_CLOCK) -> dict:
    """Approved lot + published FIXED_PRICE listing, clock inside the window."""
    env = env or bootstrap_marketplace()
    lines = SMALL_LOT_LINES if lines is None else lines
    defaults = {"condition_grade": "NEW_OVERSTOCK"}
    defaults.update(lot_overrides or {})
    built = setup_approved_lot(env, lines, **defaults)
    listing = create_listing(
        env, built["lot"]["id"],
        fixed_price_listing_payload(ask_price_cents, **(listing_overrides or {})),
    )
    listing = publish_listing(env, listing["id"])
    if clock:
        set_clock(clock)
    return {"env": env, "lot": built["lot"], "lines": built["lines"], "listing": listing}


def setup_open_negotiated(env=None, *, min_offer_cents=900_000, lines=None,
                          lot_overrides=None, listing_overrides=None,
                          clock=INSIDE_WINDOW_CLOCK) -> dict:
    """Approved lot + published NEGOTIATED listing, clock inside the window."""
    env = env or bootstrap_marketplace()
    lines = SMALL_LOT_LINES if lines is None else lines
    defaults = {"condition_grade": "NEW_OVERSTOCK"}
    defaults.update(lot_overrides or {})
    built = setup_approved_lot(env, lines, **defaults)
    listing = create_listing(
        env, built["lot"]["id"],
        negotiated_listing_payload(min_offer_cents, **(listing_overrides or {})),
    )
    listing = publish_listing(env, listing["id"])
    if clock:
        set_clock(clock)
    return {"env": env, "lot": built["lot"], "lines": built["lines"], "listing": listing}


# ─── Tier 5: sale orders ──────────────────────────────

def order_for_listing(listing_id, headers) -> dict:
    """The single SaleOrder a closed sale produces, read back through the
    listing_id filter."""
    body = api_client.list_sale_orders(headers, params={"listing_id": listing_id})
    rows = get_success_data(body)
    assert rows, f"expected a SaleOrder for listing {listing_id}, found none"
    return rows[0]


def order_count_for_listing(listing_id, headers) -> int:
    response = api_client.list_sale_orders(headers, params={"listing_id": listing_id})
    get_success_data(response)
    return response.json()["meta"]["total_count"]


def buy_at_ask(env, listing, *, amount_cents=None, buyer=None, buyer_headers=None) -> dict:
    """A fixed-price purchase at exactly the ask. Returns {"bid", "order"}."""
    buyer = buyer or env["buyer"]
    headers = buyer_headers or make_buyer_headers(buyer["id"])
    amount = listing["ask_price_cents"] if amount_cents is None else amount_cents
    bid = get_success_data(
        api_client.place_bid(listing["id"], bid_payload(buyer["id"], amount), headers)
    )
    return {"bid": bid, "order": order_for_listing(listing["id"], headers)}


def setup_fixed_price_order(env=None, *, ask_price_cents=1_000_000, lines=None,
                            lot_overrides=None, listing_overrides=None,
                            clock=INSIDE_WINDOW_CLOCK) -> dict:
    """Full fixed-price sale: approved lot -> OPEN listing -> purchase at the ask.

    Returns {"env", "lot", "lines", "listing", "bid", "order"}.
    """
    built = setup_open_fixed_price(
        env, ask_price_cents=ask_price_cents, lines=lines,
        lot_overrides=lot_overrides, listing_overrides=listing_overrides, clock=clock,
    )
    sold = buy_at_ask(built["env"], built["listing"])
    built.update(sold)
    built["listing"] = get_success_data(
        api_client.get_listing(built["listing"]["id"], built["env"]["buyer_headers"])
    )
    return built


def pay_order(env, order, amount_cents=None, *, buyer_headers=None) -> dict:
    """Pay an order, defaulting to the whole outstanding balance."""
    headers = buyer_headers or env["buyer_headers"]
    amount = order["balance_due_cents"] if amount_cents is None else amount_cents
    return get_success_data(
        api_client.pay_sale_order(order["id"], payment_payload(amount), headers)
    )


def setup_paid_fixed_price_order(env=None, *, ask_price_cents=1_000_000, lines=None,
                                 lot_overrides=None, listing_overrides=None,
                                 clock=INSIDE_WINDOW_CLOCK) -> dict:
    """A fixed-price sale paid in full. Returns the setup_fixed_price_order keys
    with "order" refreshed to its PAID state."""
    built = setup_fixed_price_order(
        env, ask_price_cents=ask_price_cents, lines=lines,
        lot_overrides=lot_overrides, listing_overrides=listing_overrides, clock=clock,
    )
    built["order"] = pay_order(built["env"], built["order"])
    return built


def close_auction(env, listing, *, at=None, closer_headers=None) -> dict:
    """Advance the clock to the effective close and close the auction."""
    set_clock(at or listing["effective_close_at"])
    return get_success_data(
        api_client.close_listing(
            listing["id"], {}, closer_headers or env["closer_headers"]
        )
    )


def setup_auction_sale_order(env=None, *, bid_amount_cents=AUCTION_RESERVE_PRICE_CENTS,
                             lines=None, lot_overrides=None, listing_overrides=None,
                             bid_clock=INSIDE_WINDOW_CLOCK) -> dict:
    """Canonical auction sale: one LIVE bid that meets the reserve, then closure.

    Returns {"env", "lot", "lines", "listing", "bid", "order"}.
    """
    built = setup_open_auction(
        env, lines=lines, lot_overrides=lot_overrides,
        listing_overrides=listing_overrides, clock=bid_clock,
    )
    env = built["env"]
    bid = get_success_data(
        api_client.place_bid(
            built["listing"]["id"],
            bid_payload(env["buyer"]["id"], bid_amount_cents),
            env["buyer_headers"],
        )
    )
    listing = close_auction(env, built["listing"])
    built["listing"] = listing
    built["bid"] = get_success_data(api_client.get_bid(bid["id"], env["buyer_headers"]))
    built["order"] = order_for_listing(listing["id"], env["buyer_headers"])
    return built


def setup_paid_auction_order(env=None, **kwargs) -> dict:
    """Canonical auction sale paid in full at the closing instant."""
    built = setup_auction_sale_order(env, **kwargs)
    built["order"] = pay_order(built["env"], built["order"])
    return built


# ─── Tier 6: freight and pickup ───────────────────────

def book_appointment(env, order, *, window_start_at, window_end_at,
                     warehouse_id=None, carrier_id=None, bol_number="BOL-0001",
                     buyer_headers=None) -> dict:
    return get_success_data(
        api_client.book_pickup_appointment(
            order["id"],
            pickup_appointment_payload(
                warehouse_id or env["warehouse"]["id"],
                carrier_id or env["carrier"]["id"],
                window_start_at, window_end_at, bol_number,
            ),
            buyer_headers or env["buyer_headers"],
        )
    )


def complete_appointment(env, appointment, *, actual_freight_cents,
                         picked_up_unit_count, at=None, dock_headers=None) -> dict:
    """Move the clock to the window start (or the caller's instant) and complete
    the pickup, which switches the order's settlement basis to FINAL."""
    set_clock(at or appointment["window_start_at"])
    return get_success_data(
        api_client.complete_pickup_appointment(
            appointment["id"],
            completion_payload(actual_freight_cents, picked_up_unit_count),
            dock_headers or env["dock_headers"],
        )
    )


def setup_picked_up_order(env=None, *, sale="auction", actual_freight_cents=None,
                          picked_up_unit_count=None,
                          window_start_at="2026-08-18T14:00:00Z",
                          window_end_at="2026-08-18T15:00:00Z", **kwargs) -> dict:
    """A sale carried all the way through pickup completion, so the order is
    PICKED_UP on a FINAL settlement basis with the seller payout frozen.

    Returns the sale keys plus {"appointment"} and a refreshed "order".
    """
    if sale == "auction":
        built = setup_paid_auction_order(env, **kwargs)
    else:
        built = setup_paid_fixed_price_order(env, **kwargs)
    env = built["env"]
    lot = get_success_data(api_client.get_lot(built["lot"]["id"], env["seller_headers"]))
    units = lot["declared_unit_count"]
    freight = (
        built["order"]["estimated_freight_cents"] if actual_freight_cents is None
        else actual_freight_cents
    )
    appointment = book_appointment(
        env, built["order"], window_start_at=window_start_at,
        window_end_at=window_end_at, bol_number="BOL-PICKUP",
    )
    appointment = complete_appointment(
        env, appointment, actual_freight_cents=freight,
        picked_up_unit_count=units if picked_up_unit_count is None else picked_up_unit_count,
    )
    built["appointment"] = appointment
    built["order"] = get_success_data(
        api_client.get_sale_order(built["order"]["id"], env["buyer_headers"])
    )
    built["lot"] = lot
    return built


def setup_two_paid_fixed_price_orders(env=None, *, ask_price_cents=1_000_000,
                                     clock=INSIDE_WINDOW_CLOCK,
                                     warehouse_overrides=None,
                                     carrier_overrides=None) -> dict:
    """Two fixed-price sales to the same buyer out of the same warehouse, both
    paid in full - the precondition for every dock-door and carrier-capacity
    contention scenario.

    Returns {"env", "lot_a", "order_a", "lot_b", "order_b", "listing_a", "listing_b"}.
    """
    env = env or bootstrap_marketplace(
        warehouse_overrides=warehouse_overrides, carrier_overrides=carrier_overrides
    )
    first = setup_paid_fixed_price_order(env, ask_price_cents=ask_price_cents, clock=clock)
    second = setup_paid_fixed_price_order(
        env, ask_price_cents=ask_price_cents, clock=None,
        lot_overrides={"title": "Second overstock lot", "condition_grade": "NEW_OVERSTOCK"},
    )
    return {
        "env": env,
        "lot_a": first["lot"], "listing_a": first["listing"], "order_a": first["order"],
        "lot_b": second["lot"], "listing_b": second["listing"], "order_b": second["order"],
    }


# ─── Tier 7: claims ───────────────────────────────────

DEFAULT_EVIDENCE_URLS = [
    "https://evidence.example/photo-1.jpg",
    "https://evidence.example/photo-2.jpg",
]


def file_claim(env, order, manifest_line_id, *, claim_type="UNIT_SHORTAGE",
               claimed_units=80, evidence_urls=None, buyer_headers=None) -> dict:
    return get_success_data(
        api_client.file_claim(
            order["id"],
            claim_payload(manifest_line_id, claim_type, claimed_units, evidence_urls),
            buyer_headers or env["buyer_headers"],
        )
    )


def setup_claim_under_review(env=None, *, claimed_units=80, line_index=0,
                             claim_type="UNIT_SHORTAGE",
                             evidence_urls=None, filing_clock="2026-08-19T00:00:00Z",
                             **kwargs) -> dict:
    """A picked-up canonical auction sale plus a claim filed with two evidence
    URLs, so the claim is already UNDER_REVIEW.

    Returns the setup_picked_up_order keys plus {"claim", "claim_line"}.
    """
    built = setup_picked_up_order(env, **kwargs)
    env = built["env"]
    set_clock(filing_clock)
    line = built["lines"][line_index]
    claim = file_claim(
        env, built["order"], line["id"], claim_type=claim_type,
        claimed_units=claimed_units,
        evidence_urls=DEFAULT_EVIDENCE_URLS if evidence_urls is None else evidence_urls,
    )
    built["claim"] = claim
    built["claim_line"] = line
    return built


def decide_claim(env, claim, decision, verified_units=None, *, headers=None,
                 **overrides) -> dict:
    return get_success_data(
        api_client.decide_claim(
            claim["id"],
            claim_decision_payload(decision, verified_units, **overrides),
            headers or env["claims_headers"],
        )
    )


def setup_decided_claim(env=None, *, decision="APPROVE", claimed_units=80,
                        verified_units=None, **kwargs) -> dict:
    """A claim carried through to a MarketplaceOps decision by the claims desk
    operator, who is a different user from the manifest reviewer.

    Returns the setup_claim_under_review keys with "claim" refreshed and the
    order re-read after the refund ledger has run.
    """
    built = setup_claim_under_review(env, claimed_units=claimed_units, **kwargs)
    env = built["env"]
    verified = claimed_units if verified_units is None else verified_units
    built["claim"] = decide_claim(env, built["claim"], decision, verified)
    built["order"] = get_success_data(
        api_client.get_sale_order(built["order"]["id"], env["buyer_headers"])
    )
    return built


# ─── Tier 8: negotiations ─────────────────────────────

def open_negotiation(env, listing, amount_cents, *, buyer=None, buyer_headers=None) -> dict:
    buyer = buyer or env["buyer"]
    return get_success_data(
        api_client.open_negotiation(
            listing["id"], negotiation_payload(buyer["id"], amount_cents),
            buyer_headers or make_buyer_headers(buyer["id"]),
        )
    )


def counter_offer(env, negotiation, amount_cents, *, as_seller=False, headers=None) -> dict:
    """Counter the live offer, passing the negotiation's freshly read version."""
    fresh = get_success_data(
        api_client.get_negotiation(negotiation["id"], env["seller_headers"])
    )
    if headers is None:
        headers = env["seller_headers"] if as_seller else env["buyer_headers"]
    return get_success_data(
        api_client.create_counter_offer(
            negotiation["id"],
            counter_offer_payload(amount_cents, fresh["version"]),
            headers,
        )
    )


def setup_negotiation_rounds(env=None, *, min_offer_cents=900_000,
                             amounts=(900_000, 1_500_000, 1_200_000),
                             clock=INSIDE_WINDOW_CLOCK, **kwargs) -> dict:
    """Open a negotiation and walk alternating counter-offers.

    The first amount is the buyer's opening offer (round 1); each subsequent
    amount is a counter-offer from the side whose turn it is, so the sides
    alternate BUYER, SELLER, BUYER, SELLER as round_number climbs.

    Returns {"env", "lot", "lines", "listing", "negotiation"}.
    """
    built = setup_open_negotiated(
        env, min_offer_cents=min_offer_cents, clock=clock, **kwargs
    )
    env = built["env"]
    negotiation = open_negotiation(env, built["listing"], amounts[0])
    for index, amount in enumerate(amounts[1:]):
        negotiation = counter_offer(
            env, negotiation, amount, as_seller=(index % 2 == 0)
        )
    built["negotiation"] = negotiation
    return built


# ─── Read-back helpers ────────────────────────────────
# PlatformAdmin is admitted to every read endpoint, so these helpers keep tests
# free of header plumbing when all they need is the current state of a row.

def total_count(response) -> int:
    """The filtered population size a list response reports before paging."""
    return response.json()["meta"]["total_count"]


def read_seller(env, seller_id=None) -> dict:
    return get_success_data(
        api_client.get_seller_account(seller_id or env["seller"]["id"], ADMIN)
    )


def read_buyer(env, buyer_id=None) -> dict:
    return get_success_data(
        api_client.get_buyer_account(buyer_id or env["buyer"]["id"], ADMIN)
    )


def read_lot(env, lot_id) -> dict:
    return get_success_data(api_client.get_lot(lot_id, ADMIN))


def read_manifest_line(env, manifest_line_id) -> dict:
    return get_success_data(api_client.get_manifest_line(manifest_line_id, ADMIN))


def read_listing(env, listing_id) -> dict:
    return get_success_data(api_client.get_listing(listing_id, ADMIN))


def read_bid(env, bid_id) -> dict:
    return get_success_data(api_client.get_bid(bid_id, ADMIN))


def read_negotiation(env, negotiation_id) -> dict:
    return get_success_data(api_client.get_negotiation(negotiation_id, ADMIN))


def read_order(env, sale_order_id) -> dict:
    return get_success_data(api_client.get_sale_order(sale_order_id, ADMIN))


def read_appointment(env, appointment_id) -> dict:
    return get_success_data(api_client.get_pickup_appointment(appointment_id, ADMIN))


def read_claim(env, claim_id) -> dict:
    return get_success_data(api_client.get_claim(claim_id, ADMIN))


def read_analytics(env, seller_id=None, **params) -> dict:
    query = {"seller_id": seller_id or env["seller"]["id"]}
    query.update(params)
    return get_success_data(api_client.get_recovery_analytics(ADMIN, params=query))
