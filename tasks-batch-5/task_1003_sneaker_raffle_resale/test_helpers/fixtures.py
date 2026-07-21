"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.
All helpers use get_success_data() (lenient) so a setup failure surfaces as a
clear "Setup failed" rather than a confusing assertion error downstream.

Identity threading: after creating an Account (Buyer/Seller) or Authenticator,
any ownership-gated call uses the per-instance header builder with that entity's
real id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_buyer_headers,
    make_seller_headers,
    make_authenticator_headers,
)
from .factories import (
    create_account_payload,
    create_sku_payload,
    create_authenticator_payload,
    create_release_payload,
    create_listing_payload,
    create_bid_payload,
    create_consignment_item_payload,
    create_dispute_payload,
)
from .constants import (
    DEFAULT_ENTRY_OPENS,
    DEFAULT_ENTRY_CLOSES,
    DEFAULT_PURCHASE_OPENS,
    DEFAULT_PURCHASE_CLOSES,
)

ADMIN = TEST_USERS["admin_headers"]
CS = TEST_USERS["cs_headers"]


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def advance_clock(api, to_iso8601: str):
    """Set the logical clock (PlatformAdmin only)."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# --------------------------------------------------------------------------- #
# Primitive entity builders
# --------------------------------------------------------------------------- #
def create_account(api, verified: bool = True, **overrides) -> dict:
    acct = get_success_data(api.create_account(create_account_payload(**overrides), ADMIN))
    if verified:
        acct = get_success_data(api.verify_account(acct["id"], ADMIN))
    return acct


def create_sku(api, **overrides) -> dict:
    return get_success_data(api.create_sku(create_sku_payload(**overrides), ADMIN))


def create_authenticator(api, **overrides) -> dict:
    return get_success_data(
        api.create_authenticator(create_authenticator_payload(**overrides), ADMIN)
    )


def create_listing(api, sku_id, seller_id, **overrides) -> dict:
    payload = create_listing_payload(sku_id=sku_id, seller_account_id=seller_id, **overrides)
    return get_success_data(api.create_listing(payload, make_seller_headers(seller_id)))


def create_bid(api, sku_id, buyer_id, **overrides) -> dict:
    payload = create_bid_payload(sku_id=sku_id, buyer_account_id=buyer_id, **overrides)
    return get_success_data(api.create_bid(payload, make_buyer_headers(buyer_id)))


def buy_listing(api, listing_id, buyer_id) -> dict:
    return get_success_data(api.buy_listing(listing_id, make_buyer_headers(buyer_id)))


# --------------------------------------------------------------------------- #
# Resale order tiers
# --------------------------------------------------------------------------- #
def setup_fixed_order(
    api,
    ask_price_cents: int = 30000,
    listed_condition: str = "DEADSTOCK",
    size: str = "10",
    pricing_mode: str = "FIXED",
) -> dict:
    """Verified seller + verified buyer + one listing + a FIXED buy Order.

    Returns {sku, seller, buyer, listing, order}. The order is fresh
    (AWAITING_SHIPMENT / AUTHORIZED) with provisional fees computed.
    """
    sku = create_sku(api)
    seller = create_account(api, full_name="Seller")
    buyer = create_account(api, full_name="Buyer")
    listing = create_listing(
        api, sku["id"], seller["id"],
        ask_price_cents=ask_price_cents, size=size,
        condition=listed_condition, pricing_mode=pricing_mode,
    )
    order = buy_listing(api, listing["id"], buyer["id"])
    return {"sku": sku, "seller": seller, "buyer": buyer, "listing": listing, "order": order}


def create_consignment(api, order_id, seller_id, sku_id,
                       declared_condition="DEADSTOCK",
                       declared_box="PERFECT",
                       declared_acc=True) -> dict:
    payload = create_consignment_item_payload(
        order_id=order_id, seller_account_id=seller_id, sku_id=sku_id,
        declared_condition_grade=declared_condition,
        declared_box_grade=declared_box,
        declared_accessories_complete=declared_acc,
    )
    return get_success_data(api.create_consignment_item(payload, make_seller_headers(seller_id)))


def receive_item(api, ci_id, auth_id) -> dict:
    return get_success_data(api.receive_consignment_item(ci_id, make_authenticator_headers(auth_id)))


def schedule_item(api, ci_id, auth_id,
                  window_start="2026-07-01T09:00:00Z",
                  window_end="2026-07-01T09:30:00Z") -> dict:
    payload = {
        "authenticator_id": auth_id,
        "inspection_window_start": window_start,
        "inspection_window_end": window_end,
    }
    return get_success_data(api.schedule_inspection(ci_id, payload, make_authenticator_headers(auth_id)))


def complete_pass(api, ci_id, auth_id,
                  condition="DEADSTOCK", box="PERFECT", accessories=True) -> dict:
    payload = {
        "inspection_result": "PASS",
        "authenticated_condition_grade": condition,
        "authenticated_box_grade": box,
        "authenticated_accessories_complete": accessories,
    }
    return get_success_data(api.complete_inspection(ci_id, payload, make_authenticator_headers(auth_id)))


def complete_fail(api, ci_id, auth_id) -> dict:
    return get_success_data(
        api.complete_inspection(ci_id, {"inspection_result": "FAIL"}, make_authenticator_headers(auth_id))
    )


def setup_order_through_authentication(
    api,
    ask_price_cents: int = 30000,
    listed_condition: str = "DEADSTOCK",
    declared_box: str = "PERFECT",
    declared_acc: bool = True,
    auth_condition: str = "DEADSTOCK",
    auth_box: str = "PERFECT",
    auth_acc: bool = True,
    size: str = "10",
    window_start: str = "2026-07-01T09:00:00Z",
    window_end: str = "2026-07-01T09:30:00Z",
) -> dict:
    """FIXED order driven through receive -> schedule -> PASS inspection.

    Order fulfillment ends at AUTHENTICATED. Returns the setup_fixed_order
    dict extended with {authenticator, consignment}.
    """
    ctx = setup_fixed_order(api, ask_price_cents, listed_condition, size)
    auth = create_authenticator(api)
    ci = create_consignment(
        api, ctx["order"]["id"], ctx["seller"]["id"], ctx["sku"]["id"],
        declared_condition=listed_condition, declared_box=declared_box, declared_acc=declared_acc,
    )
    receive_item(api, ci["id"], auth["id"])
    schedule_item(api, ci["id"], auth["id"], window_start, window_end)
    ci = complete_pass(api, ci["id"], auth["id"], auth_condition, auth_box, auth_acc)
    ctx["authenticator"] = auth
    ctx["consignment"] = ci
    return ctx


def setup_shipped_order(api, **kwargs) -> dict:
    """Resale order shipped to buyer (fulfillment SHIPPED_TO_BUYER)."""
    ctx = setup_order_through_authentication(api, **kwargs)
    ctx["order"] = get_success_data(api.ship_order(ctx["order"]["id"], ADMIN))
    return ctx


def setup_verified_order(api, **kwargs) -> dict:
    """Resale order verified by the buyer (payment CAPTURED, payout settled)."""
    ctx = setup_shipped_order(api, **kwargs)
    ctx["order"] = get_success_data(api.verify_order(ctx["order"]["id"], make_buyer_headers(ctx["buyer"]["id"])))
    return ctx


def file_dispute(api, order_id, buyer_id, reason="INAUTHENTIC") -> dict:
    payload = create_dispute_payload(order_id=order_id, filed_by_account_id=buyer_id, reason=reason)
    return get_success_data(api.create_dispute(payload, make_buyer_headers(buyer_id)))


def setup_verified_order_with_open_dispute(api, reason="INAUTHENTIC", **kwargs) -> dict:
    """Verified resale order with an OPEN dispute filed by the buyer within the window."""
    ctx = setup_verified_order(api, **kwargs)
    ctx["dispute"] = file_dispute(api, ctx["order"]["id"], ctx["buyer"]["id"], reason)
    return ctx


# --------------------------------------------------------------------------- #
# Raffle tiers
# --------------------------------------------------------------------------- #
def setup_open_release(
    api,
    allocated_quantity: int = 1,
    release_price_cents: int = 20000,
    num_accounts: int = 0,
    entry_opens: str = DEFAULT_ENTRY_OPENS,
    entry_closes: str = DEFAULT_ENTRY_CLOSES,
    purchase_opens: str = DEFAULT_PURCHASE_OPENS,
    purchase_closes: str = DEFAULT_PURCHASE_CLOSES,
) -> dict:
    """A LIMITED SKU with an OPEN release plus `num_accounts` verified accounts.

    Accounts are created BEFORE the clock advances to `entry_opens`, so at entry
    time their tenure (days between created_at and the clock) clears the
    minimum-age bot heuristic. Returns {sku, release, accounts}.
    """
    sku = create_sku(api, release_category="LIMITED")
    accounts = [create_account(api, full_name=f"Entrant {i}") for i in range(num_accounts)]
    release = get_success_data(api.create_release(create_release_payload(
        sku_id=sku["id"], allocated_quantity=allocated_quantity,
        release_price_cents=release_price_cents,
        entry_opens_at=entry_opens, entry_closes_at=entry_closes,
        purchase_opens_at=purchase_opens, purchase_closes_at=purchase_closes,
    ), ADMIN))
    advance_clock(api, entry_opens)
    release = get_success_data(api.open_release(release["id"], ADMIN))
    return {"sku": sku, "release": release, "accounts": accounts}


def enter_raffle(api, release_id, account_id) -> dict:
    return get_success_data(api.enter_release(release_id, make_buyer_headers(account_id)))


def run_draw(api, release_id, clock: str = None) -> dict:
    """Draw a release. Reads the release's live version first so the required
    expected_release_version always matches the current version regardless of
    how many entries preceded the draw."""
    if clock is not None:
        advance_clock(api, clock)
    rel = get_success_data(api.get_release(release_id, ADMIN))
    return get_success_data(
        api.draw_release(release_id, {"expected_release_version": rel["version"]}, ADMIN)
    )


def run_settle(api, release_id, clock: str = None) -> dict:
    if clock is not None:
        advance_clock(api, clock)
    return get_success_data(api.settle_release(release_id, ADMIN))


def raffle_claim(api, entry_id, account_id) -> dict:
    return get_success_data(api.claim_entry(entry_id, make_buyer_headers(account_id)))


def setup_drawn_single_winner(api) -> dict:
    """One-allocation LIMITED release with a single verified entrant, drawn.

    After the draw the sole entry is WON. Clock ends at entry_closes; callers
    advance into (or past) the purchase window as their scenario requires.
    Returns {sku, release, accounts, entry}.
    """
    ctx = setup_open_release(api, allocated_quantity=1, num_accounts=1)
    ctx["entry"] = enter_raffle(api, ctx["release"]["id"], ctx["accounts"][0]["id"])
    run_draw(api, ctx["release"]["id"], clock=DEFAULT_ENTRY_CLOSES)
    return ctx
