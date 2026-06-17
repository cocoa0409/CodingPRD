"""Role-based access control, the lottery allocation, waitlist scoring,
duplicate-waitlist guarding, and banned-attendee blocking.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_convention,
    create_attendee,
    create_waitlist_entry,
    setup_convention_with_ticket_type,
    setup_paid_order_with_badge,
    create_submitted_order,
    convention_version,
    make_attendee_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── RBAC ────────────────────────────────────────────────────────────────────

def test_attendee_cannot_create_convention(api):
    """PRD §4: "POST /conventions | Create a convention | ConventionAdmin".
    PRD §2.1: "When a request carries a valid role that is nonetheless not permitted for the requested operation, the response is `ERR_FORBIDDEN`."

    Design: Corner/rbac/attendee_cannot_create_convention
    """
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    res = api.create_convention(
        {"name": "Illegal Con", "event_start_utc": "2026-09-01T00:00:00Z",
         "event_end_utc": "2026-09-03T23:59:59Z", "total_badge_capacity": 50,
         "lottery_open_utc": "2026-06-01T00:00:00Z"}, headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_attendee_cannot_pickup_badge_agent_only(api):
    """PRD §4: "POST /badges/{id}/pickup | On-site pickup; encode RFID |
    RegistrationAgent".
    PRD §2.1: "When a request carries a valid role that is nonetheless not permitted for the requested operation, the response is `ERR_FORBIDDEN`."

    Design: Corner/rbac/attendee_cannot_pickup_badge_agent_only
    """
    ctx = setup_paid_order_with_badge(clock="2026-07-01T00:00:00Z")
    badge_id = ctx["badge"]["id"]
    headers = make_attendee_headers(ctx["attendee"]["id"])
    set_clock("2026-08-31T00:00:00Z")
    res = api.pickup_badge(badge_id, headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_attendee_cannot_pay_other_attendees_order(api):
    """PRD §2.1: "ownership checks on any resource that references an attendee
    compare that resource's attendee foreign key (for orders, the
    purchaser_attendee_id; ...) to X-User-ID, and an attendee acting on a resource
    it does not own is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/attendee_cannot_pay_other_attendees_order
    """
    conv, tt = setup_convention_with_ticket_type()
    att_a = create_attendee()
    att_b = create_attendee()
    set_clock("2026-07-01T00:00:00Z")
    order = create_submitted_order(conv["id"], att_a["id"], [(tt["id"], 1)])
    conv_v = convention_version(conv["id"])
    res = api.pay_order(order["id"], {"expected_convention_version": conv_v},
                        make_attendee_headers(att_b["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
    after = validate_success(api.get_order(order["id"], make_attendee_headers(att_a["id"])), 200)
    assert after["status"] == "PENDING_PAYMENT"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request other than the two self-registration endpoints must be authenticated by two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. When either header is missing, or when `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    conv = create_convention()
    res = api.create_ticket_type(
        conv["id"], {"tier": "GENERAL", "base_price_cents": 9900, "tier_capacity": 50},
        {"Content-Type": "application/json"})  # no X-User-ID / X-User-Role
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── Lottery & waitlist scoring ──────────────────────────────────────────────

def test_waitlist_priority_weighted_score_with_group_cap(api):
    """PRD §3.8: "The third is a group-size factor equal to the entry's `group_size` multiplied by 5 points per head, capped at 60 points."
    PRD §3.8: "The second is an early-bird bonus of 50 points, granted only when the entry's `created_at` is at or after the convention's `lottery_open_utc` and at the same time no later than 24 hours after that instant".

    Design: Difficulty/combinatorial_formula/waitlist_priority_weighted_score_with_group_cap
    """
    conv = create_convention(lottery_open_utc="2026-06-01T00:00:00Z")
    att = create_attendee(loyalty_tier="SILVER")
    set_clock("2026-06-01T06:00:00Z")  # inside the 24h early window
    entry = create_waitlist_entry(conv["id"], att["id"], requested_quantity=20, group_size=20)
    # SILVER(100) + early(50) + min(20*5=100, 60)=60 = 210
    assert entry["priority_score"] == 210
    assert entry["status"] == "ENTERED"


def test_run_lottery_waterfall_winners_and_losers(api):
    """PRD §3.8: "each entry is granted on an all-or-nothing basis: if the entry's `requested_quantity` is no greater than the remaining capacity, the entry transitions to `WON` and its `requested_quantity` is subtracted from the remaining capacity; otherwise the entry transitions to `LOST` and the walk continues to later, smaller entries, which may still win."

    Design: Corner/state_machines/lottery_run_marks_winners_and_losers_waterfall
    """
    conv = create_convention(total_badge_capacity=10, lottery_open_utc="2026-06-01T00:00:00Z")
    att_p = create_attendee(loyalty_tier="PLATINUM")
    att_g = create_attendee(loyalty_tier="GOLD")
    att_s = create_attendee(loyalty_tier="SILVER")

    # E1: PLATINUM(300) + late(0) + min(2*5=10,60)=10 = 310, req 4
    set_clock("2026-06-05T00:00:00Z")
    e1 = create_waitlist_entry(conv["id"], att_p["id"], requested_quantity=4, group_size=2)
    # E2: GOLD(200) + early(50) + min(4*5=20,60)=20 = 270, req 8
    set_clock("2026-06-01T06:00:00Z")
    e2 = create_waitlist_entry(conv["id"], att_g["id"], requested_quantity=8, group_size=4)
    # E3: SILVER(100) + early(50) + min(20*5=100,60)=60 = 210, req 3
    e3 = create_waitlist_entry(conv["id"], att_s["id"], requested_quantity=3, group_size=20)

    conv_v = convention_version(conv["id"])
    validate_success(api.run_lottery(conv["id"], {"expected_convention_version": conv_v}, ADMIN), 200)

    # E1 WON (rem 10->6); E2 LOST (req 8 > 6); E3 WON (req 3 <= 6).
    assert validate_success(api.get_waitlist_entry(e1["id"], ADMIN), 200)["status"] == "WON"
    assert validate_success(api.get_waitlist_entry(e2["id"], ADMIN), 200)["status"] == "LOST"
    assert validate_success(api.get_waitlist_entry(e3["id"], ADMIN), 200)["status"] == "WON"


def test_duplicate_waitlist_entry_rejected(api):
    """PRD §3.8: "At most one `ENTERED` waitlist entry may exist for any given convention-and-attendee pair; a second such entry is rejected with `ERR_DUPLICATE_WAITLIST`."

    Design: Corner/validations/duplicate_waitlist_entry_rejected
    """
    conv = create_convention(lottery_open_utc="2026-06-01T00:00:00Z")
    att = create_attendee()
    set_clock("2026-06-05T00:00:00Z")
    create_waitlist_entry(conv["id"], att["id"], requested_quantity=2, group_size=2)
    headers = make_attendee_headers(att["id"])
    res = api.create_waitlist_entry(
        conv["id"], {"attendee_id": att["id"], "requested_quantity": 1, "group_size": 1}, headers)
    validate_error(res, "ERR_DUPLICATE_WAITLIST", expected_status=409)


# ─── Banning ─────────────────────────────────────────────────────────────────

def test_banned_attendee_blocked_from_order_create(api):
    """PRD §3.2: "Once an attendee (or, analogously, an exhibitor) is `BANNED`, every create or transition operation they attempt is blocked with `ERR_ATTENDEE_BANNED`."

    Design: Corner/validations/banned_attendee_blocked_from_order_create
    """
    conv, tt = setup_convention_with_ticket_type()
    att = create_attendee()
    validate_success(api.ban_attendee(att["id"], {"expected_attendee_version": att["version"]}, ADMIN), 200)
    headers = make_attendee_headers(att["id"])
    res = api.create_order(
        {"convention_id": conv["id"], "purchaser_attendee_id": att["id"],
         "line_items": [{"ticket_type_id": tt["id"], "quantity": 1}]}, headers)
    validate_error(res, "ERR_ATTENDEE_BANNED", expected_status=403)
