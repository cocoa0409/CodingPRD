"""Corner queue B: business-rule violations, RBAC, OCC stale-version, presale
code, mobile-entry, resale cap, and immediate consistency.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_event_with_tier,
    setup_held_ticket,
    setup_open_listing,
    register_fan,
    register_and_verify_fan,
    create_event,
    create_tier,
    open_to_phase,
    create_pending_order,
    create_paid_order,
    join_queue,
    advance,
    make_fan_headers,
)
from test_helpers.fixtures import PROMOTER, SCANNER
from test_helpers.factories import create_resale_listing_payload


# ─── validations ──────────────────────────────────────────────────────────

def test_resale_over_cap_rejected(api):
    """PRD §3.7: "The listing is accepted only when list_price_cents is at most
    that cap; a higher asking price is rejected with ERR_RESALE_CAP_EXCEEDED."

    Cap = round(10000 * 210 / 100) = 21000; listing at 21001 is rejected.

    Design: Corner/validations/resale_over_cap_rejected
    """
    event, tier, fan, order, ticket = setup_held_ticket(
        phase="GENERAL", resale_cap_pct=110, face_value_cents=10000
    )
    res = api.create_resale_listing(
        create_resale_listing_payload(ticket["id"], fan["id"], 21001),
        make_fan_headers(fan["id"]),
    )
    validate_error(res, "ERR_RESALE_CAP_EXCEEDED")
    t_after = validate_success(api.get_ticket(ticket["id"], make_fan_headers(fan["id"])), 200)
    assert t_after["holding_status"] == "HELD", t_after


def test_resale_cap_exact_boundary_passes(api):
    """PRD §3.7: "The listing is accepted only when list_price_cents is at most
    that cap". PRD §3.7: "the resale price cap in cents is the event's
    face_value_cents multiplied by the sum of 100 and the event's resale_cap_pct,
    divided by 100, rounded half up."

    Listing exactly at the cap (21000) is accepted (inclusive upper bound).

    Design: Corner/calculations/resale_cap_exact_boundary_passes
    """
    event, tier, fan, order, ticket = setup_held_ticket(
        phase="GENERAL", resale_cap_pct=110, face_value_cents=10000
    )
    listing = validate_success(api.create_resale_listing(
        create_resale_listing_payload(ticket["id"], fan["id"], 21000),
        make_fan_headers(fan["id"]),
    ), 201)
    assert listing["status"] == "OPEN", listing
    assert listing["list_price_cents"] == 21000, listing


def test_refund_blocked_after_scan(api):
    """PRD §3.4: "Refund is barred if any of the order's tickets is already
    SCANNED, in which case the request is rejected with
    ERR_TICKET_ALREADY_SCANNED".

    Design: Corner/validations/refund_blocked_after_scan
    """
    event, tier, fan, order, ticket = setup_held_ticket(phase="GENERAL")
    validate_success(api.scan_ticket(ticket["id"], {"device_channel": "MOBILE"}, SCANNER), 200)
    res = api.refund_order(
        order["id"], {"expected_order_version": order["version"]},
        make_fan_headers(fan["id"]),
    )
    validate_error(res, "ERR_TICKET_ALREADY_SCANNED")
    o_after = validate_success(api.get_order(order["id"], make_fan_headers(fan["id"])), 200)
    assert o_after["status"] == "PAID", o_after


def test_order_qty_mismatch_rejected(api):
    """PRD §3.4: "The quantity must equal the redeemed entry's requested_qty and
    lie within 1 to 6; a violation is rejected with ERR_QTY_MISMATCH."

    Design: Corner/validations/order_qty_mismatch_rejected
    """
    event, tier = setup_event_with_tier(phase="PRESALE")
    fan = register_and_verify_fan("qm@x.com", device="dev-qm")
    qe = join_queue(event, tier, fan, requested_qty=1, presale_code_used="S")
    advance(event["id"], tier_id=tier["id"], max_offers=5)
    res = api.create_order(
        {"queue_entry_id": qe["id"], "fan_id": fan["id"], "tier_id": tier["id"], "quantity": 2},
        make_fan_headers(fan["id"]),
    )
    validate_error(res, "ERR_QTY_MISMATCH")


def test_self_dealing_resale_buy_rejected(api):
    """PRD §3.7: "the buyer to differ from the seller — a buyer equal to the
    seller is rejected with ERR_SELF_DEALING."

    Design: Corner/validations/self_dealing_resale_buy_rejected
    """
    event, tier, seller, ticket, listing = setup_open_listing(list_price_cents=11000)
    res = api.buy_resale_listing(
        listing["id"],
        {"buyer_fan_id": seller["id"], "expected_resalelisting_version": listing["version"]},
        make_fan_headers(seller["id"]),
    )
    validate_error(res, "ERR_SELF_DEALING")
    l_after = validate_success(api.get_resale_listing(listing["id"], make_fan_headers(seller["id"])), 200)
    assert l_after["status"] == "OPEN", l_after


def test_invalid_presale_code_rejected(api):
    """PRD §3.3: "During PRESALE, the submitted presale_code_used must equal the
    event's presale_code, and a mismatch is rejected with
    ERR_INVALID_PRESALE_CODE; during GENERAL the code is not enforced."

    Design: Corner/validations/invalid_presale_code_rejected_stub
    """
    event = create_event(venue_capacity=100, presale_code="SUMMER", face_value_cents=10000)
    tier = create_tier(event["id"], allocation=50)
    open_to_phase(event, "PRESALE")
    fan = register_and_verify_fan("pc@x.com", device="dev-pc")
    res = api.create_queue_entry(
        {"event_id": event["id"], "fan_id": fan["id"], "tier_id": tier["id"],
         "presale_code_used": "WRONG", "requested_qty": 1},
        make_fan_headers(fan["id"]),
    )
    validate_error(res, "ERR_INVALID_PRESALE_CODE")


# ─── endpoints ──────────────────────────────────────────────────────────--

def test_scan_non_mobile_channel_rejected(api):
    """PRD §3.5: "Mobile-only entry is strict: a scan whose device_channel is
    anything other than MOBILE is rejected with ERR_NON_MOBILE_ENTRY."

    Design: Corner/endpoints/scan_non_mobile_channel_rejected
    """
    event, tier, fan, order, ticket = setup_held_ticket(phase="GENERAL")
    res = api.scan_ticket(ticket["id"], {"device_channel": "WEB"}, SCANNER)
    validate_error(res, "ERR_NON_MOBILE_ENTRY")
    t_after = validate_success(api.get_ticket(ticket["id"], make_fan_headers(fan["id"])), 200)
    assert t_after["entry_status"] == "VALID", t_after


# ─── errors / OCC ─────────────────────────────────────────────────────────

def test_stale_version_on_pay(api):
    """PRD §2.7: "Paying an order requires an expected_order_version field
    carrying the client's last observed version of the target Order; if that
    value does not equal the order's current version, the payment is rejected
    with ERR_STALE_VERSION (HTTP 412)".

    Design: Corner/errors/stale_version_on_pay
    """
    event, tier = setup_event_with_tier(phase="PRESALE")
    fan = register_and_verify_fan("sv@x.com", device="dev-sv")
    _qe, order = create_pending_order(event, tier, fan, requested_qty=1, presale_code_used="S")
    res = api.pay_order(
        order["id"], {"expected_order_version": order["version"] - 1},
        make_fan_headers(fan["id"]),
    )
    validate_error(res, "ERR_STALE_VERSION")


def test_version_increments_on_event_transition(api):
    """PRD §3.2: "the transition sets sales_status to PRESALE and increments the
    event's version."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_event_transition

    NOTE: the second assertion (re-opening with a stale version → ERR_STALE_VERSION)
    was removed. After a successful open_presale the event is in PRESALE, so a
    re-open is *both* an invalid-state transition (open_presale is DRAFT→PRESALE
    only) and a stale-version mismatch. PRD §2.5's precedence sentence orders the
    structural ERR_INVALID_STATE gate ahead of the business rules and mentions the
    optimistic-concurrency ERR_STALE_VERSION only in a trailing clause, without
    pinning STALE_VERSION ahead of INVALID_STATE. A faithful PRD-only implementer
    could reasonably report either error here, so the outcome is not uniquely
    derivable (ERROR PRECEDENCE SILENCE). Only the version-increment assertion,
    which §3.2 uniquely determines, is retained.
    """
    event = create_event(venue_capacity=100, presale_code="S", face_value_cents=10000)
    create_tier(event["id"], allocation=50)
    opened = validate_success(
        api.open_presale(event["id"], {"expected_event_version": event["version"]}, PROMOTER), 200
    )
    assert opened["version"] == 2, opened


# ─── rbac ─────────────────────────────────────────────────────────────────

def test_fan_cannot_create_event(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted to
    perform the targeted operation is rejected with ERR_FORBIDDEN_ROLE."
    PRD §4 (endpoint table): "POST /events | Create an event in DRAFT |
    PromoterAdmin".

    Design: Corner/rbac/fan_cannot_create_event
    """
    fan = register_and_verify_fan("fr@x.com", device="dev-fr")
    res = api.create_event(
        {"title": "E", "venue_capacity": 100, "presale_code": "S", "face_value_cents": 10000},
        make_fan_headers(fan["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_non_owner_fan_cannot_refund_others_order(api):
    """PRD §2.8: "the system check that the acting Fan owns the resource being
    mutated; an attempt by a fan to act on another fan's order, ticket, listing,
    or transfer is rejected with ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/non_owner_fan_cannot_refund_others_order
    """
    event, tier = setup_event_with_tier(phase="PRESALE")
    fan_a = register_and_verify_fan("oa@x.com", device="dev-oa")
    fan_b = register_and_verify_fan("ob@x.com", device="dev-ob")
    _qe, paid = create_paid_order(event, tier, fan_a, requested_qty=1, presale_code_used="S")
    res = api.refund_order(
        paid["id"], {"expected_order_version": paid["version"]},
        make_fan_headers(fan_b["id"]),
    )
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")
    o_after = validate_success(api.get_order(paid["id"], make_fan_headers(fan_a["id"])), 200)
    assert o_after["status"] == "PAID", o_after


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request that omits either header, or that names a role outside
    this set, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    res = api.create_queue_entry(
        {"event_id": "00000000-0000-4000-8000-000000000000",
         "fan_id": "00000000-0000-4000-8000-000000000001",
         "tier_id": "00000000-0000-4000-8000-000000000002",
         "presale_code_used": "S", "requested_qty": 1},
        headers={},
    )
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── consistency ─────────────────────────────────────────────────────────-

def test_pay_side_effects_visible_immediately(api):
    """PRD §1 (intro): "every mutation is immediately visible".
    PRD §3.4: "the event's tickets_sold_count is increased by quantity".

    A follow-up GET reflects the incremented counter in the same request cycle.

    Design: Corner/consistency_model/pay_side_effects_visible_immediately
    """
    event, tier = setup_event_with_tier(phase="GENERAL")
    fan = register_and_verify_fan("im@x.com", device="dev-im")
    _qe, paid = create_paid_order(event, tier, fan, requested_qty=1)
    assert paid["status"] == "PAID", paid
    ev_after = validate_success(api.get_event(event["id"], PROMOTER), 200)
    assert ev_after["tickets_sold_count"] == 1, ev_after
