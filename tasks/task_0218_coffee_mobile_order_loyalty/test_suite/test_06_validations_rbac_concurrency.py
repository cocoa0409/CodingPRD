"""Business validations, RBAC enforcement, pagination guards, and OCC version checks.

Queue B (Corner): validations section, rbac section,
                  cross_cutting_complexity_layers (OCC).
"""
from test_helpers import (
    fixtures as fx,
    factories as f,
    validate_success,
    validate_error,
    ApiErrorId,
)

ERR = ApiErrorId


# ─── validations section ──────────────────────────────────────────────────

def test_slot_lead_time_violation_returns_slot_unavailable(api):
    """PRD §3.3: "the slot's `window_start` minus the current time must be at least
    `prep_minutes` minutes; a slot that fails these checks is rejected with
    `ERR_SLOT_UNAVAILABLE`."

    Store prep_minutes 30; clock 17:00; slot starts 17:10 (only 10 min lead) ->
    creating an order on that slot is rejected 409 ERR_SLOT_UNAVAILABLE.

    Design: Corner/validations/slot_lead_time_violation_returns_slot_unavailable
    """
    fx.set_clock("2026-06-01T17:00:00Z")
    store = fx.create_store(slot_capacity=5, prep_minutes=30)
    slot = fx.create_pickup_slot(store["id"], "2026-06-01T17:10:00Z", "2026-06-01T17:25:00Z")
    member = fx.create_member()
    mid = member["id"]
    resp = api.create_order(mid, f.create_order_payload(store["id"], slot["id"]),
                            fx.make_member_headers(mid))
    validate_error(resp, ERR.ERR_SLOT_UNAVAILABLE.value)


def test_birthday_claim_outside_month_rejected(api):
    """PRD §3.9: "The claim is allowed only during the member's birthday month
    (matching the month component of `birth_month_day` against the current month), at
    most once per calendar year ... a claim that violates any of these — already
    claimed this calendar year, made outside the birthday month, or made while an
    `ISSUED` birthday reward already exists — is rejected with
    `ERR_BIRTHDAY_ALREADY_CLAIMED`."

    Member born 03-14 claims in June 2026 -> 409 ERR_BIRTHDAY_ALREADY_CLAIMED.

    Design: Corner/validations/birthday_outside_month_returns_already_claimed
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(birth_month_day="03-14")
    mid = member["id"]
    resp = api.claim_birthday_reward(mid, fx.make_member_headers(mid))
    validate_error(resp, ERR.ERR_BIRTHDAY_ALREADY_CLAIMED.value)


def test_birthday_claim_in_month_succeeds(api):
    """PRD §3.9: "A successful claim mints a `RewardGrant` of kind `BIRTHDAY` in
    `ISSUED` status with a `star_cost` of 0, a `max_discount_cents` of 700, and an
    `expires_at` set 30 days after the grant time, and sets the member's
    `last_birthday_reward_year` to the current year."

    Member born 03-14 claims in March 2026 -> 201, RewardGrant kind BIRTHDAY,
    star_cost 0, last_birthday_reward_year 2026.

    Design: Corner/validations/birthday_reward_granted_in_month
    """
    fx.set_clock("2026-03-10T00:00:00Z")
    member = fx.create_member(birth_month_day="03-14")
    mid = member["id"]
    hdr = fx.make_member_headers(mid)
    reward = validate_success(api.claim_birthday_reward(mid, hdr), 201)
    assert reward["kind"] == "BIRTHDAY", reward
    assert reward["star_cost"] == 0, reward
    member2 = validate_success(api.get_member(mid, hdr))
    assert member2["last_birthday_reward_year"] == 2026, member2


def test_redeem_below_star_cost_returns_insufficient_stars(api):
    """PRD §3.9: "Redemption requires the member's `star_balance` to be at least the
    redemption cost of 150 stars; if it is below that, the request is rejected with
    `ERR_INSUFFICIENT_STARS`."

    A member with 0 stars redeeming -> 409 ERR_INSUFFICIENT_STARS.

    Design: Corner/validations/insufficient_stars_below_redeem_cost
    """
    member = fx.create_member()
    mid = member["id"]
    resp = api.redeem_reward(mid, fx.make_member_headers(mid))
    validate_error(resp, ERR.ERR_INSUFFICIENT_STARS.value)


def test_stored_value_pay_insufficient_balance_no_autoreload(api):
    """PRD §3.5: "After any auto-reload, the card's `balance_cents` must cover
    `total_cents`; if it still falls short the pay is rejected with
    `ERR_INSUFFICIENT_BALANCE` (HTTP 402)."

    Card balance 100 (auto-reload off), total 669, STORED_VALUE pay -> 402
    ERR_INSUFFICIENT_BALANCE.

    Design: Corner/validations/insufficient_balance_stored_value_no_autoreload
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    card = fx.reload_card(mid, 100)
    resp = api.pay_order(
        mid, ctx["order"]["id"],
        f.pay_payload("STORED_VALUE", expected_card_version=card["version"]), hdr)
    validate_error(resp, ERR.ERR_INSUFFICIENT_BALANCE.value)


def test_pagination_limit_over_max_returns_validation(api):
    """PRD §2.3: "A `limit` greater than 100 or below 1, or a negative `offset`, is
    rejected with `ERR_VALIDATION`."

    GET /orders?limit=500 -> 422 ERR_VALIDATION.

    Design: Corner/validations/pagination_limit_over_max_returns_validation
    """
    member = fx.create_member()
    mid = member["id"]
    resp = api.list_orders(fx.make_member_headers(mid),
                           params={"member_id": mid, "limit": 500})
    validate_error(resp, ERR.ERR_VALIDATION.value)


# ─── rbac section ─────────────────────────────────────────────────────────

def test_member_cannot_pay_another_members_order(api):
    """PRD §2.1: "Ownership checks on any resource that references a `Member` compare
    the resource's owning foreign key to `X-User-ID` ... An attempt by a `Member` to
    operate on another member's resources fails the ownership check with
    `ERR_FORBIDDEN`."

    Member B paying Member A's order (X-User-ID mismatch with Order.member_id) -> 403
    ERR_FORBIDDEN.

    Design: Corner/rbac/member_cannot_pay_another_members_order
    """
    fx.set_clock()
    store = fx.create_store()
    item = fx.create_menu_item(store["id"], base_price_cents=615, category="BEVERAGE")
    slot = fx.create_pickup_slot(store["id"], *fx._SLOT_WINDOWS[0])
    mem_a = fx.create_member()
    mem_b = fx.create_member()
    order = fx.create_cart_order(mem_a["id"], store["id"], slot["id"])
    fx.add_line(mem_a["id"], order["id"], item["id"], quantity=1)
    # Member B pays A's order, addressed under A's path but with B's identity.
    resp = api.pay_order(mem_a["id"], order["id"], f.pay_payload("EXTERNAL_CARD"),
                         fx.make_member_headers(mem_b["id"]))
    validate_error(resp, ERR.ERR_FORBIDDEN.value)


def test_store_operator_cannot_create_store(api):
    """PRD §2.1: "When the headers are present and well-formed but the role is not
    permitted to perform the requested operation — or an ownership check fails — the
    request is rejected with `ERR_FORBIDDEN`."
    PRD §3.2: "A `PlatformAdmin` creates a store by providing its display `name`, its
    IANA `timezone` identifier".

    StoreOperator calling POST /stores (a PlatformAdmin-exclusive op) -> 403
    ERR_FORBIDDEN.

    Design: Corner/rbac/storeoperator_cannot_create_store
    """
    resp = api.create_store(f.create_store_payload(name="X"), fx.OPERATOR)
    validate_error(resp, ERR.ERR_FORBIDDEN.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request other than member registration must be authenticated
    through two mandatory HTTP headers: `X-User-ID` ... and `X-User-Role` ... A request
    missing either header (or carrying an unrecognized role) is rejected with
    `ERR_UNAUTHENTICATED`."

    A protected GET with no X-User-ID/X-User-Role -> 401 ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    member = fx.create_member()
    resp = api.get_member(member["id"], headers={})
    validate_error(resp, ERR.ERR_UNAUTHENTICATED.value)


# ─── cross_cutting_complexity_layers: OCC ─────────────────────────────────

def test_occ_stale_card_version_on_pay_rejected(api):
    """PRD §2.8: "A pay request whose `pay_method` is `STORED_VALUE` must carry
    `expected_card_version` equal to the card's current `version`. If another writer
    has advanced the card's `version` since the client last read it ... the pay is
    rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Client captures card version v, a second reload bumps it to v+1, then pays with the
    stale v -> 412 ERR_STALE_VERSION; order stays UNPAID.

    Design: Corner/cross_cutting_complexity_layers/occ_card_stale_version_on_pay
    """
    ctx = fx.setup_base(item_price=615, num_slots=1)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    stale_card = fx.reload_card(mid, 5000)
    stale_v = stale_card["version"]
    fx.reload_card(mid, 1000)  # bumps card version
    order = fx.create_cart_order(mid, store_id, ctx["slots"][0]["id"])
    fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    resp = api.pay_order(
        mid, order["id"],
        f.pay_payload("STORED_VALUE", expected_card_version=stale_v), hdr)
    validate_error(resp, ERR.ERR_STALE_VERSION.value)
    reread = validate_success(api.get_order(order["id"], hdr))
    assert reread["payment_status"] == "UNPAID", reread


def test_occ_stale_slot_version_on_place_rejected(api):
    """PRD §2.8: "A place request must carry `expected_slot_version` equal to the
    slot's current `version`. If another writer has placed or cancelled an order
    against the same slot since the client last read it ... the place is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Two members hold paid orders on one slot; member 2 places (bumping slot to v+1);
    member 1 then places carrying the stale v -> 412 ERR_STALE_VERSION; order 1 stays
    CART.

    Design: Corner/cross_cutting_complexity_layers/occ_slot_stale_version_on_place
    """
    fx.set_clock()
    store = fx.create_store(slot_capacity=5, prep_minutes=0)
    item = fx.create_menu_item(store["id"], base_price_cents=615, category="BEVERAGE")
    slot = fx.create_pickup_slot(store["id"], *fx._SLOT_WINDOWS[0])
    slot_v0 = slot["version"]

    mem1 = fx.create_member()
    o1 = fx.create_cart_order(mem1["id"], store["id"], slot["id"])
    fx.add_line(mem1["id"], o1["id"], item["id"], quantity=1)
    fx.pay(mem1["id"], o1["id"], "EXTERNAL_CARD")

    mem2 = fx.create_member()
    o2 = fx.create_cart_order(mem2["id"], store["id"], slot["id"])
    fx.add_line(mem2["id"], o2["id"], item["id"], quantity=1)
    fx.pay(mem2["id"], o2["id"], "EXTERNAL_CARD")

    # Member 2 places first, bumping the slot version.
    fx.place(mem2["id"], o2["id"], slot_v0)
    # Member 1 places with the now-stale slot_v0.
    resp = api.place_order(mem1["id"], o1["id"], f.place_payload(slot_v0),
                           fx.make_member_headers(mem1["id"]))
    validate_error(resp, ERR.ERR_STALE_VERSION.value)
    reread = validate_success(api.get_order(o1["id"], fx.make_member_headers(mem1["id"])))
    assert reread["fulfillment_status"] == "CART", reread
