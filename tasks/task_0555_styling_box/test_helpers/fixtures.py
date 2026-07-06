"""Composite setup helpers.

Every test runs against a fresh, empty database (the server is restarted before
each test), so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. Setup calls use get_success_data (lenient) so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing assert.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_client_payload,
    create_style_profile_payload,
    create_product_payload,
    create_stylist_payload,
    create_purchase_payload,
)
from .test_users import TEST_USERS, make_client_headers, make_stylist_headers

OPS = TEST_USERS["ops_headers"]
ANON = TEST_USERS["anonymous_headers"]


def _data(resp) -> dict:
    return get_success_data(resp)


# ------------------------------------------------------------- Primitive builders
def create_product(price_cents=3000, category="TOP", size=8, total_stock=5, **over) -> dict:
    payload = create_product_payload(
        price_cents=price_cents, category=category, size=size, total_stock=total_stock, **over
    )
    return _data(api_client.create_product(payload, headers=OPS))


def create_stylist(max_concurrent_fixes=None, **over) -> dict:
    payload = create_stylist_payload(**over)
    if max_concurrent_fixes is not None:
        payload["max_concurrent_fixes"] = max_concurrent_fixes
    return _data(api_client.create_stylist(payload, headers=OPS))


def register_client(region_code="CA", cadence=None, **over) -> dict:
    """Register a client (status PROSPECT). No profile yet."""
    payload = create_client_payload(region_code=region_code, **over)
    if cadence is not None:
        payload["cadence"] = cadence
    return _data(api_client.create_client(payload, headers=ANON))


def complete_profile(client_id, quiz_top_size=8, quiz_bottom_size=8, quiz_shoe_size=9,
                     price_tier="MID", **over) -> dict:
    payload = create_style_profile_payload(
        quiz_top_size=quiz_top_size, quiz_bottom_size=quiz_bottom_size,
        quiz_shoe_size=quiz_shoe_size, price_tier=price_tier, **over
    )
    return _data(api_client.complete_style_profile(
        client_id, payload, headers=make_client_headers(client_id)))


def create_active_client(region_code="CA", cadence=None, quiz_top_size=8,
                         quiz_bottom_size=8, quiz_shoe_size=9, price_tier="MID") -> dict:
    """Register + complete profile → client in ACTIVE status. Returns fresh client."""
    c = register_client(region_code=region_code, cadence=cadence)
    complete_profile(c["id"], quiz_top_size=quiz_top_size, quiz_bottom_size=quiz_bottom_size,
                     quiz_shoe_size=quiz_shoe_size, price_tier=price_tier)
    return _data(api_client.get_client(c["id"], headers=OPS))


def client_version(client_id) -> int:
    return _data(api_client.get_client(client_id, headers=OPS))["version"]


def get_client(client_id) -> dict:
    return _data(api_client.get_client(client_id, headers=OPS))


def get_fix(fix_id) -> dict:
    return _data(api_client.get_fix(fix_id, headers=OPS))


def get_product(product_id) -> dict:
    return _data(api_client.get_product(product_id, headers=OPS))


def get_style_profile(client_id) -> dict:
    """Reverse lookup returns an array of 0..1 profiles; return the single profile."""
    arr = _data(api_client.get_style_profile(client_id, headers=OPS))
    assert isinstance(arr, list) and arr, f"expected one style profile for {client_id}"
    return arr[0]


def schedule_fix(client_id) -> dict:
    """Read current version and schedule a fix (OCC create)."""
    v = client_version(client_id)
    return _data(api_client.schedule_fix(
        client_id, {"expected_client_version": v}, headers=make_client_headers(client_id)))


def assign_fix(fix_id, stylist_id) -> dict:
    return _data(api_client.assign_fix(fix_id, {"stylist_id": stylist_id}, headers=OPS))


def add_item(fix_id, product_id, stylist_id) -> dict:
    return _data(api_client.add_fix_item(
        fix_id, {"product_id": product_id}, headers=make_stylist_headers(stylist_id)))


# ------------------------------------------------------------- Composite scenarios
_DEFAULT_CATEGORIES = ["TOP", "BOTTOM", "SHOE", "TOP", "BOTTOM"]


def _spec_lists(prices, categories, sizes):
    n = len(prices)
    cats = categories if categories is not None else [_DEFAULT_CATEGORIES[i % 5] for i in range(n)]
    szs = sizes if sizes is not None else [8] * n
    return cats, szs


def setup_styling_fix(prices=(3000, 3000, 3000), region_code="CA", categories=None,
                      sizes=None, stylist_max=None, cadence=None) -> dict:
    """Active client + stylist + a fix in STYLING with one SELECTED item per price.

    Returns a context dict: client, client_id, stylist, stylist_id, fix, fix_id,
    products, product_ids, items, item_ids.
    """
    prices = list(prices)
    cats, szs = _spec_lists(prices, categories, sizes)
    products = [
        create_product(price_cents=prices[i], category=cats[i], size=szs[i], total_stock=5)
        for i in range(len(prices))
    ]
    stylist = create_stylist(max_concurrent_fixes=stylist_max)
    client = create_active_client(region_code=region_code, cadence=cadence)
    fix = schedule_fix(client["id"])
    assign_fix(fix["id"], stylist["id"])
    items = [add_item(fix["id"], p["id"], stylist["id"]) for p in products]
    return {
        "client": client, "client_id": client["id"],
        "stylist": stylist, "stylist_id": stylist["id"],
        "fix": get_fix(fix["id"]), "fix_id": fix["id"],
        "products": products, "product_ids": [p["id"] for p in products],
        "items": items, "item_ids": [it["id"] for it in items],
    }


def setup_preview_fix(prices=(3000, 3000, 3000), region_code="CA", categories=None,
                      sizes=None) -> dict:
    """Fix walked through to PREVIEW (STYLING → submit-preview)."""
    ctx = setup_styling_fix(prices=prices, region_code=region_code,
                            categories=categories, sizes=sizes)
    _data(api_client.submit_preview(ctx["fix_id"], headers=make_stylist_headers(ctx["stylist_id"])))
    ctx["fix"] = get_fix(ctx["fix_id"])
    return ctx


def setup_delivered_fix(prices=(3000, 3000, 3000), region_code="CA", categories=None,
                        sizes=None) -> dict:
    """Fix walked through to DELIVERED (PREVIEW → ship → mark-delivered).

    After this, estimated_charge_cents and checkout_deadline are populated on
    ctx['fix']. Checkout itself is left to the caller (it is the trigger).
    """
    ctx = setup_preview_fix(prices=prices, region_code=region_code,
                            categories=categories, sizes=sizes)
    _data(api_client.ship_fix(ctx["fix_id"], headers=OPS))
    _data(api_client.mark_delivered(ctx["fix_id"], headers=OPS))
    ctx["fix"] = get_fix(ctx["fix_id"])
    return ctx


def checkout(fix_id, client_id, kept_item_ids, item_feedback=None) -> dict:
    payload = {"kept_item_ids": kept_item_ids}
    if item_feedback is not None:
        payload["item_feedback"] = item_feedback
    return _data(api_client.checkout_fix(
        fix_id, payload, headers=make_client_headers(client_id)))


def setup_checked_out_fix_with_returns(prices=(3000, 3000, 3000), region_code="CA") -> dict:
    """Delivered fix, then checkout keeping only the first item → a ReturnShipment
    (LABEL_ISSUED) covers the remaining items. Returns ctx plus 'return_id'."""
    ctx = setup_delivered_fix(prices=prices, region_code=region_code)
    checkout(ctx["fix_id"], ctx["client_id"], kept_item_ids=[ctx["item_ids"][0]])
    returns = _data(api_client.list_fix_returns(ctx["fix_id"], headers=OPS))
    ctx["return_id"] = returns[0]["id"]
    ctx["fix"] = get_fix(ctx["fix_id"])
    return ctx


def setup_placed_purchase(price_cents=3000, total_stock=5, quantity=2, region_code="CA") -> dict:
    """Active client + product + a PLACED direct-buy purchase. Returns ctx with
    client_id, product_id, purchase, purchase_id."""
    product = create_product(price_cents=price_cents, total_stock=total_stock)
    client = create_active_client(region_code=region_code)
    purchase = _data(api_client.create_purchase(
        client["id"], create_purchase_payload(product["id"], quantity),
        headers=make_client_headers(client["id"])))
    return {
        "client": client, "client_id": client["id"],
        "product": product, "product_id": product["id"],
        "purchase": purchase, "purchase_id": purchase["id"],
    }


def setup_client_with_hold(start_date, end_date, region_code="CA") -> dict:
    """Active client with one existing Hold over [start_date, end_date)."""
    client = create_active_client(region_code=region_code)
    hold = _data(api_client.create_hold(
        client["id"], {"start_date": start_date, "end_date": end_date},
        headers=make_client_headers(client["id"])))
    return {"client": client, "client_id": client["id"], "hold": hold}


def setup_learned_sizing_two_tops() -> dict:
    """Two sequential delivered/checked-out TOP fixes for one client, spaced on the
    logical clock so feedback ordering is total:
      fix#1 at clock 2026-05-01: TOP size 12 kept + PERFECT feedback
      fix#2 at clock 2026-05-15: TOP size 8 kept + TOO_SMALL feedback
    Returns ctx with client_id and the second fix's kept item feedback already
    applied. quiz sizes seed top=6.
    """
    p_top12 = create_product(price_cents=3000, category="TOP", size=12, total_stock=5)
    p_top8 = create_product(price_cents=3000, category="TOP", size=8, total_stock=5)
    filler = create_product(price_cents=1000, category="ACCESSORY", size=1, total_stock=20)
    stylist = create_stylist()
    client = create_active_client(region_code="CA", quiz_top_size=6,
                                  quiz_bottom_size=8, quiz_shoe_size=9)
    cid = client["id"]

    # --- fix #1 ---
    f1 = schedule_fix(cid)
    assign_fix(f1["id"], stylist["id"])
    i1a = add_item(f1["id"], p_top12["id"], stylist["id"])
    add_item(f1["id"], filler["id"], stylist["id"])
    add_item(f1["id"], filler["id"], stylist["id"])
    _data(api_client.submit_preview(f1["id"], headers=make_stylist_headers(stylist["id"])))
    _data(api_client.ship_fix(f1["id"], headers=OPS))
    _data(api_client.mark_delivered(f1["id"], headers=OPS))
    checkout(f1["id"], cid, kept_item_ids=[i1a["id"]],
             item_feedback=[{"fix_item_id": i1a["id"], "rating": "PERFECT"}])

    # --- advance clock, fix #2 ---
    _data(api_client.set_clock({"to_iso8601": "2026-05-15T00:00:00Z"}, headers=OPS))
    f2 = schedule_fix(cid)
    assign_fix(f2["id"], stylist["id"])
    i2b = add_item(f2["id"], p_top8["id"], stylist["id"])
    add_item(f2["id"], filler["id"], stylist["id"])
    add_item(f2["id"], filler["id"], stylist["id"])
    _data(api_client.submit_preview(f2["id"], headers=make_stylist_headers(stylist["id"])))
    _data(api_client.ship_fix(f2["id"], headers=OPS))
    _data(api_client.mark_delivered(f2["id"], headers=OPS))
    return {
        "client_id": cid,
        "stylist_id": stylist["id"],
        "fix2_id": f2["id"],
        "fix2_kept_item_id": i2b["id"],
    }


def set_clock(to_iso8601: str):
    return _data(api_client.set_clock({"to_iso8601": to_iso8601}, headers=OPS))
