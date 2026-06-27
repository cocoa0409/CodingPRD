"""Reward-claim lifecycle: maturation, expiry, online attribution window, the
disabled-merchant guard, and immediate derived-balance visibility.

Translates difficulty `resource_temporal_overlap` (attribution-window inclusive
edge) and corner `state_machines` / `validations` / `cross_cutting` /
`consistency_model` instances.
"""
from test_helpers import (
    validate_success, validate_error, api_client, TEST_USERS, make_member_headers,
    ApiErrorId,
    create_merchant, create_offer, create_member,
    create_online_click_and_claim, set_clock, get_member,
)

_PA = TEST_USERS["platform_admin_headers"]
_FA = TEST_USERS["finance_admin_headers"]


def test_online_attribution_inclusive_window_edge_accepts(api):
    """PRD §3.3: "a click-through must exist for that member and merchant whose
    `clicked_at` falls within the merchant's `attribution_window_hours` before the
    claim; if no such qualifying click exists within the window, the claim is
    rejected with `ERR_ATTRIBUTION_WINDOW_EXPIRED` (HTTP 409)."

    A click exactly attribution_window_hours before the claim is still in-window.

    Design: Difficulty/resource_temporal_overlap/online_attribution_window_inclusive_boundary
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200,
                               attribution_window_hours=168, maturity_hold_days=30)
    member = create_member("mo@x.com")
    hdr = make_member_headers(member["id"])
    set_clock("2026-01-01T00:00:00Z")
    click = validate_success(api.create_clickthrough(
        {"member_id": member["id"], "merchant_id": merchant["id"]}, hdr), 201)
    set_clock("2026-01-08T00:00:00Z")  # exactly 168h after the click
    claim = validate_success(api.create_reward_claim(
        {"member_id": member["id"], "merchant_id": merchant["id"],
         "click_through_id": click["id"], "purchase_amount_cents": 10000}, hdr), 201)
    assert claim["status"] == "PENDING"
    assert claim["amount_cents"] == 1000, \
        f"10000 @ 1000bps must be 1000, got {claim['amount_cents']}"


def test_online_claim_well_inside_attribution_window_accepts(api):
    """PRD §3.3: "a click-through must exist for that member and merchant whose
    `clicked_at` falls within the merchant's `attribution_window_hours` before the
    claim; if no such qualifying click exists within the window, the claim is
    rejected with `ERR_ATTRIBUTION_WINDOW_EXPIRED` (HTTP 409)."

    A click comfortably inside the window (100h < 168h) attributes the claim,
    confirming the trailing-window semantics below the inclusive edge.

    Design: Difficulty/resource_temporal_overlap/online_attribution_window_inclusive_boundary
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200,
                               attribution_window_hours=168, maturity_hold_days=30)
    member = create_member("moin@x.com")
    hdr = make_member_headers(member["id"])
    set_clock("2026-01-01T00:00:00Z")
    click = validate_success(api.create_clickthrough(
        {"member_id": member["id"], "merchant_id": merchant["id"]}, hdr), 201)
    set_clock("2026-01-05T04:00:00Z")  # 100h after the click, within 168h
    claim = validate_success(api.create_reward_claim(
        {"member_id": member["id"], "merchant_id": merchant["id"],
         "click_through_id": click["id"], "purchase_amount_cents": 10000}, hdr), 201)
    assert claim["status"] == "PENDING"
    assert claim["attribution"] == "ONLINE"


def test_online_claim_past_attribution_window_rejected(api):
    """PRD §3.3: "if no such qualifying click exists within the window, the claim is
    rejected with `ERR_ATTRIBUTION_WINDOW_EXPIRED` (HTTP 409)."

    Design: Corner/validations/online_claim_no_click_attribution_window_expired
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200,
                               attribution_window_hours=168)
    member = create_member("aw@x.com")
    hdr = make_member_headers(member["id"])
    set_clock("2026-01-01T00:00:00Z")
    click = validate_success(api.create_clickthrough(
        {"member_id": member["id"], "merchant_id": merchant["id"]}, hdr), 201)
    set_clock("2026-01-08T00:00:01Z")  # one second past 168h
    resp = api.create_reward_claim(
        {"member_id": member["id"], "merchant_id": merchant["id"],
         "click_through_id": click["id"], "purchase_amount_cents": 10000}, hdr)
    validate_error(resp, ApiErrorId.ERR_ATTRIBUTION_WINDOW_EXPIRED)


def test_clock_advance_matures_pending_claim(api):
    """PRD §3.5: "Once the logical clock reaches the claim's `matures_at`, the claim
    matures to `AVAILABLE`."
    PRD §3.5: "Maturation emits a `CLAIM_MATURED` ledger entry carrying the positive
    `amount_cents`, shifts the value from the member's pending balance into the
    available balance".

    Design: Corner/state_machines/clock_advance_matures_pending_claim
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200, maturity_hold_days=30)
    member = create_member("sv@x.com")
    _, claim = create_online_click_and_claim(member["id"], merchant["id"], 10000)
    set_clock("2026-02-15T00:00:00Z")
    matured = validate_success(api.get_reward_claim(claim["id"], _FA))
    assert matured["status"] == "AVAILABLE"
    member_now = get_member(member["id"])
    assert member_now["pending_balance_cents"] == 0
    assert member_now["available_balance_cents"] == 1000


def test_available_claim_expires_after_expiry_window(api):
    """PRD §3.5: "when the clock reaches its `expires_at` and the claim is still
    `AVAILABLE` (unreserved), it transitions to `EXPIRED`, a terminal state,
    emitting a `CLAIM_EXPIRED` ledger entry for the negative `amount_cents` and
    reducing the member's available balance by `amount_cents`."

    Design: Corner/state_machines/available_claim_expires_after_expiry_window
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200, maturity_hold_days=30)
    member = create_member("sx@x.com")
    _, claim = create_online_click_and_claim(member["id"], merchant["id"], 10000)
    set_clock("2026-02-15T00:00:00Z")  # mature
    set_clock("2027-06-01T00:00:00Z")  # far past expires_at
    expired = validate_success(api.get_reward_claim(claim["id"], _FA))
    assert expired["status"] == "EXPIRED"
    member_now = get_member(member["id"])
    assert member_now["available_balance_cents"] == 0


def test_claim_for_disabled_merchant_rejected(api):
    """PRD §3.1: "A `PlatformAdmin` may later disable a merchant, moving its
    `status` to `DISABLED`; a disabled merchant rejects new claims, receipts, and
    clicks with `ERR_MERCHANT_DISABLED` (HTTP 409)."

    Design: Corner/validations/claim_for_disabled_merchant_rejected
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200)
    member = create_member("dm@x.com")
    hdr = make_member_headers(member["id"])
    click = validate_success(api.create_clickthrough(
        {"member_id": member["id"], "merchant_id": merchant["id"]}, hdr), 201)
    validate_success(api.disable_merchant(merchant["id"], _PA))
    resp = api.create_reward_claim(
        {"member_id": member["id"], "merchant_id": merchant["id"],
         "click_through_id": click["id"], "purchase_amount_cents": 10000}, hdr)
    validate_error(resp, ApiErrorId.ERR_MERCHANT_DISABLED)


def test_ledger_entry_recorded_on_claim_create(api):
    """PRD §3.3: "Creating an online claim emits a ledger entry of type
    `CLAIM_PENDING`".
    PRD §2.6: "`pending_balance_cents` is the sum of `amount_cents` over the
    member's claims in `PENDING`".

    Design: Corner/cross_cutting_complexity_layers/ledger_entry_recorded_on_claim_create
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200)
    member = create_member("le@x.com")
    hdr = make_member_headers(member["id"])
    create_online_click_and_claim(member["id"], merchant["id"], 10000)
    member_now = get_member(member["id"])
    assert member_now["pending_balance_cents"] == 1000
    entries = validate_success(api.list_member_ledger_entries(member["id"], hdr))
    if isinstance(entries, dict):
        entries = [entries]
    assert any(e["entry_type"] == "CLAIM_PENDING" for e in entries), \
        "creating an online claim must emit a CLAIM_PENDING ledger entry"


def test_immediate_balance_visible_in_same_response(api):
    """PRD §2.7: "The wallet balances described in Section 2.6 are recomputed
    implicitly from the claim rows after any cascade, so they always reflect the
    current claim states."
    PRD §2.6: "`pending_balance_cents` is the sum of `amount_cents` over the
    member's claims in `PENDING`; `available_balance_cents` is the sum of
    `amount_cents` over claims in `AVAILABLE` only".

    Design: Corner/consistency_model/immediate_balance_visible_in_same_response
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200)
    member = create_member("im@x.com")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)
    member_now = get_member(member["id"])
    assert member_now["pending_balance_cents"] == 1000
    assert member_now["available_balance_cents"] == 0
