"""Composite setup helpers for the Coffee Mobile Order & Loyalty API.

Each test runs against a freshly wiped database, so every fixture builds its
preconditions from scratch using only PRD-declared endpoints. Fixtures use the
lenient get_success_data() validator so a broken setup raises a clear
"Setup step failed" rather than a confusing downstream assertion error.

Identity threading: a Member is entity_backed, so every ownership-gated call
uses make_member_headers(member_id) with the real member id. StoreOperator and
PlatformAdmin are opaque.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_store_operator_headers,
    make_platform_admin_headers,
)
from . import factories as f

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["store_operator_headers"]
ANON = TEST_USERS["anonymous_headers"]

# Default clock instant used across deterministic fixtures.
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"

# Default non-overlapping slot windows (16 windows, 1h apart, 15-min each).
_SLOT_WINDOWS = [
    ("2026-06-01T17:00:00Z", "2026-06-01T17:15:00Z"),
    ("2026-06-01T18:00:00Z", "2026-06-01T18:15:00Z"),
    ("2026-06-01T19:00:00Z", "2026-06-01T19:15:00Z"),
    ("2026-06-01T20:00:00Z", "2026-06-01T20:15:00Z"),
    ("2026-06-01T21:00:00Z", "2026-06-01T21:15:00Z"),
    ("2026-06-01T22:00:00Z", "2026-06-01T22:15:00Z"),
]


# ─── Tier 0: primitives ───────────────────────────────────────────────────

def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Pin the server clock (PlatformAdmin only)."""
    get_success_data(api_client.set_clock(f.clock_payload(to_iso8601), ADMIN))


def create_store(**overrides) -> dict:
    return get_success_data(api_client.create_store(f.create_store_payload(**overrides), ADMIN))


def create_menu_item(store_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_menu_item(store_id, f.create_menu_item_payload(**overrides), ADMIN))


def create_modifier(menu_item_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_modifier(menu_item_id, f.create_modifier_payload(**overrides), ADMIN))


def create_pickup_slot(store_id, window_start, window_end, **overrides) -> dict:
    return get_success_data(api_client.create_pickup_slot(
        store_id, f.create_pickup_slot_payload(window_start, window_end, **overrides), ADMIN))


def create_member(**overrides) -> dict:
    return get_success_data(api_client.create_member(f.create_member_payload(**overrides), ANON))


def reload_card(member_id, amount_cents) -> dict:
    """Reload the member's own card; returns the updated card (carries version).

    The reload endpoint creates and returns the new WalletTransaction (PRD §4:
    reloading a card is a standalone-resource create that returns 201). To obtain
    the card's bumped `version` for the OCC pay check, re-read the card afterward.
    """
    get_success_data(api_client.reload_card(
        member_id, f.reload_card_payload(amount_cents), make_member_headers(member_id)))
    return get_card(member_id)


def get_card(member_id) -> dict:
    """Return the member's single StoredValueCard."""
    data = get_success_data(api_client.get_member_card(member_id, make_member_headers(member_id)))
    assert isinstance(data, list) and len(data) == 1, "expected exactly one card"
    return data[0]


# ─── Tier 1: a base catalog + member scenario ─────────────────────────────

def setup_base(clock=DEFAULT_CLOCK, slot_capacity=5, prep_minutes=0,
               item_price=615, item_reward_eligible=True, num_slots=2):
    """Clock + store + one BEVERAGE menu item + N non-overlapping slots + member.

    Returns a context dict with keys:
      store, item, slots (list of slot dicts), member, member_headers.
    """
    set_clock(clock)
    store = create_store(slot_capacity=slot_capacity, prep_minutes=prep_minutes)
    item = create_menu_item(store["id"], base_price_cents=item_price,
                            category="BEVERAGE", reward_eligible=item_reward_eligible)
    slots = []
    for i in range(num_slots):
        ws, we = _SLOT_WINDOWS[i]
        slots.append(create_pickup_slot(store["id"], ws, we))
    member = create_member()
    return {
        "store": store,
        "item": item,
        "slots": slots,
        "member": member,
        "member_headers": make_member_headers(member["id"]),
    }


# ─── Tier 2: orders at various lifecycle stages ───────────────────────────

def create_cart_order(member_id, store_id, slot_id, applied_reward_id=None) -> dict:
    return get_success_data(api_client.create_order(
        member_id,
        f.create_order_payload(store_id, slot_id, applied_reward_id=applied_reward_id),
        make_member_headers(member_id),
    ))


def add_line(member_id, order_id, menu_item_id, quantity=1, modifiers=None) -> dict:
    return get_success_data(api_client.add_order_line(
        member_id, order_id,
        f.add_line_payload(menu_item_id, quantity, modifiers=modifiers),
        make_member_headers(member_id),
    ))


def pay(member_id, order_id, pay_method, expected_card_version=None) -> dict:
    return get_success_data(api_client.pay_order(
        member_id, order_id,
        f.pay_payload(pay_method, expected_card_version=expected_card_version),
        make_member_headers(member_id),
    ))


def place(member_id, order_id, expected_slot_version) -> dict:
    return get_success_data(api_client.place_order(
        member_id, order_id,
        f.place_payload(expected_slot_version),
        make_member_headers(member_id),
    ))


def setup_cart_order_with_line(item_price=615, slot_capacity=5, prep_minutes=0,
                               quantity=1, clock=DEFAULT_CLOCK):
    """Base scenario + a CART order carrying one line of the base item.

    Returns ctx (from setup_base) augmented with: order, line, slot (the order's slot).
    """
    ctx = setup_base(clock=clock, slot_capacity=slot_capacity, prep_minutes=prep_minutes,
                     item_price=item_price)
    slot = ctx["slots"][0]
    order = create_cart_order(ctx["member"]["id"], ctx["store"]["id"], slot["id"])
    line = add_line(ctx["member"]["id"], order["id"], ctx["item"]["id"], quantity=quantity)
    ctx.update({"order": order, "line": line, "slot": slot})
    return ctx


def setup_paid_order(item_price=615, slot_capacity=5, prep_minutes=0,
                     pay_method="EXTERNAL_CARD", clock=DEFAULT_CLOCK,
                     card_balance=None):
    """Base scenario + a PAID (still CART) order with one line.

    If pay_method == STORED_VALUE, the card is reloaded to `card_balance`
    (default 5000) before pay. Returns ctx with: order (paid), line, slot,
    card_version (the card version observed just before pay, only when STORED_VALUE).
    """
    ctx = setup_cart_order_with_line(item_price=item_price, slot_capacity=slot_capacity,
                                     prep_minutes=prep_minutes, clock=clock)
    mid = ctx["member"]["id"]
    card_version = None
    if pay_method == "STORED_VALUE":
        bal = 5000 if card_balance is None else card_balance
        card = reload_card(mid, bal)
        card_version = card["version"]
    paid = pay(mid, ctx["order"]["id"], pay_method, expected_card_version=card_version)
    ctx["order"] = paid
    ctx["card_version"] = card_version
    return ctx


def setup_placed_order(item_price=615, slot_capacity=5, prep_minutes=0,
                       pay_method="EXTERNAL_CARD", clock=DEFAULT_CLOCK,
                       card_balance=None):
    """Base scenario + a PAID then PLACED order with one line.

    Returns ctx with: order (placed), line, slot (current, carries bumped version).
    """
    ctx = setup_paid_order(item_price=item_price, slot_capacity=slot_capacity,
                           prep_minutes=prep_minutes, pay_method=pay_method,
                           clock=clock, card_balance=card_balance)
    mid = ctx["member"]["id"]
    slot_v = ctx["slot"]["version"]
    placed = place(mid, ctx["order"]["id"], slot_v)
    ctx["order"] = placed
    # Re-read slot to capture its bumped version/reserved_count.
    ctx["slot"] = api_client.get_pickup_slot(
        ctx["slot"]["id"], ctx["member_headers"]).json()["data"]
    return ctx


def drive_to_picked_up(ctx):
    """Walk a PLACED order through IN_PREP -> READY -> PICKED_UP (operator)."""
    store_id = ctx["store"]["id"]
    oid = ctx["order"]["id"]
    get_success_data(api_client.start_prep(store_id, oid, OPERATOR))
    get_success_data(api_client.mark_ready(store_id, oid, OPERATOR))
    final = get_success_data(api_client.complete_order(store_id, oid, OPERATOR))
    ctx["order"] = final
    return ctx


# ─── Tier 3: star accumulation + reward minting ───────────────────────────

def earn_lifetime_stars(member_id, store_id, slot_id, dollars,
                        category="FOOD", reward_eligible=False):
    """Drive `dollars` of GREEN+EXTERNAL pre-tax spend so the member earns
    exactly `dollars` lifetime stars (1 star/dollar at GREEN/EXTERNAL).

    Creates a dedicated high-priced item (base = dollars*100 cents, no tax-free
    rounding surprises because we read pre-tax dollars), orders it, pays
    EXTERNAL_CARD and places it. Returns the member dict after re-read.
    """
    item = create_menu_item(store_id, name=f"SeedBox{dollars}",
                            base_price_cents=dollars * 100,
                            category=category, reward_eligible=reward_eligible)
    order = create_cart_order(member_id, store_id, slot_id)
    add_line(member_id, order["id"], item["id"], quantity=1)
    pay(member_id, order["id"], "EXTERNAL_CARD")
    # Re-read slot version to place.
    slot = api_client.get_pickup_slot(slot_id, make_member_headers(member_id)).json()["data"]
    place(member_id, order["id"], slot["version"])
    return get_success_data(api_client.get_member(member_id, make_member_headers(member_id)))


def mint_free_item_reward(member_id):
    """Redeem 150 stars to mint a FREE_ITEM reward. Returns the reward dict.
    The member MUST already hold >= 150 star_balance."""
    return get_success_data(api_client.redeem_reward(member_id, make_member_headers(member_id)))


def setup_member_with_free_item_reward(clock=DEFAULT_CLOCK, num_slots=4):
    """Full scenario: a member who has earned 150 stars and minted a FREE_ITEM
    reward (ISSUED, max_discount 700). The seed order occupies slots[0].

    Returns ctx with: store, item (latte 615, reward_eligible), slots, member,
    member_headers, reward (the minted FREE_ITEM RewardGrant).
    """
    ctx = setup_base(clock=clock, item_price=615, item_reward_eligible=True,
                     num_slots=num_slots)
    mid = ctx["member"]["id"]
    earn_lifetime_stars(mid, ctx["store"]["id"], ctx["slots"][0]["id"], dollars=150)
    reward = mint_free_item_reward(mid)
    ctx["reward"] = reward
    return ctx
