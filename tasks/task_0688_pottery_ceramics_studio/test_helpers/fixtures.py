"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors, not confusing assertion failures.

Identity threading: a LoyaltyMember is identity-backed. When a fixture needs an
ownership-gated call it uses make_member_headers(member["id"]); operational
StudioStaff / StudioManager calls use the shared opaque headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_member_payload, create_paint_bar_item_payload, create_visit_payload,
    create_piece_payload, create_batch_payload, create_booking_payload,
    create_series_payload, create_load_payload, create_consume_payload,
)
from .test_users import TEST_USERS, make_member_headers

STAFF = TEST_USERS["staff_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Tier 0: Single-entity creators ────────────────────────────────────────

def create_member(**overrides):
    """Register a fresh ACTIVE BRONZE member. Returns member dict."""
    res = api_client.create_member(create_member_payload(**overrides), MANAGER)
    return get_success_data(res)


def create_item(unit_price_cents=500, on_hand=50, **overrides):
    """Create a paint-bar item and restock to `on_hand`. Returns item dict."""
    item = get_success_data(api_client.create_paint_bar_item(
        create_paint_bar_item_payload(unit_price_cents=unit_price_cents, **overrides), MANAGER))
    if on_hand > 0:
        item = get_success_data(api_client.restock_paint_bar_item(
            item["id"], {"qty": on_hand}, MANAGER))
    return item


def create_series(**overrides):
    """Create an OPEN class series. Returns series dict."""
    return get_success_data(api_client.create_series(create_series_payload(**overrides), MANAGER))


def create_open_visit(member_id=None, party_size=1, visit_type="WALK_IN", **overrides):
    """Open a walk-in visit. Returns visit dict."""
    payload = create_visit_payload(party_size=party_size, visit_type=visit_type, **overrides)
    if member_id is not None:
        payload["member_id"] = member_id
    return get_success_data(api_client.create_visit(payload, STAFF))


def add_piece(visit_id, bisque_price_cents=3000, firing_temp="CONE_06", **overrides):
    """Add one PAINTED piece to an OPEN visit. Returns piece dict."""
    payload = create_piece_payload(
        bisque_price_cents=bisque_price_cents, firing_temp=firing_temp, **overrides)
    return get_success_data(api_client.add_piece(visit_id, payload, STAFF))


def create_batch(firing_temp="CONE_06", capacity_slots=4, turnaround_hours=48, **overrides):
    """Create a LOADING kiln batch (version 1). Returns batch dict."""
    return get_success_data(api_client.create_batch(
        create_batch_payload(firing_temp=firing_temp, capacity_slots=capacity_slots,
                             turnaround_hours=turnaround_hours, **overrides), STAFF))


def create_booking(member_id, package_tier="BASIC", guest_count=6,
                   scheduled_for="2026-09-01T18:00:00Z", **overrides):
    """Create a DEPOSIT_PENDING party booking. Returns booking dict."""
    return get_success_data(api_client.create_booking(
        create_booking_payload(member_id, package_tier=package_tier, guest_count=guest_count,
                               scheduled_for=scheduled_for, **overrides), STAFF))


# ─── Tier 1: Loyalty-state progression ─────────────────────────────────────

def create_member_with_lifetime(price_cents, session_count=8, seat_capacity=5,
                                starts_at="2026-07-01T18:00:00Z", **member_overrides):
    """Create a member, enroll them in one series, returning the member AFTER the
    enrollment EARN has credited their balance/lifetime.

    Returns (member_dict_after_enroll, series_dict, enrollment_dict).
    The member's lifetime/tier reflect the enrollment's points_earned.
    """
    member = create_member(**member_overrides)
    series = create_series(session_count=session_count, seat_capacity=seat_capacity,
                           price_cents=price_cents, starts_at=starts_at)
    enr = get_success_data(api_client.enroll(series["id"], {"member_id": member["id"]}, STAFF))
    member_after = get_success_data(api_client.get_member(member["id"], MANAGER))
    return member_after, series, enr


def create_silver_member():
    """A SILVER member with lifetime_points_earned == 550, via one enrollment in a
    50000-cent / 8-session series (500 base + 50 long-series bonus = 550).
    Returns the member dict (post-enrollment)."""
    member_after, _series, _enr = create_member_with_lifetime(price_cents=50000, session_count=8)
    return member_after


# ─── Tier 2: Kiln load / fire shortcuts ────────────────────────────────────

def load_piece(batch, piece_id):
    """Load a PAINTED piece into a LOADING batch using the batch's CURRENT version
    (read fresh to avoid stale OCC). Returns the loaded piece dict."""
    fresh = get_success_data(api_client.get_batch(batch["id"], STAFF))
    res = api_client.load_piece(
        batch["id"], create_load_payload(piece_id, fresh["version"]), STAFF)
    return get_success_data(res)


def fire_piece_to_ready(visit_id, bisque_price_cents=3000, firing_temp="CONE_06",
                        capacity_slots=4, turnaround_hours=48):
    """On an OPEN visit, add one piece, load it into a fresh batch, start firing and
    complete firing so the piece reaches READY. Returns (piece_dict_ready, batch_dict).
    The piece's owning visit remains OPEN.
    """
    piece = add_piece(visit_id, bisque_price_cents=bisque_price_cents, firing_temp=firing_temp)
    batch = create_batch(firing_temp=firing_temp, capacity_slots=capacity_slots,
                         turnaround_hours=turnaround_hours)
    load_piece(batch, piece["id"])
    get_success_data(api_client.start_firing(batch["id"], STAFF))
    batch_after = get_success_data(api_client.complete_firing(batch["id"], STAFF))
    piece_after = get_success_data(api_client.get_piece(piece["id"], STAFF))
    return piece_after, batch_after


def fire_pieces_to_ready(visit_id, bisque_prices, firing_temp="CONE_06",
                         turnaround_hours=48):
    """On an OPEN visit, add one piece per entry in `bisque_prices`, load them all
    into a single fresh batch sized to hold them, then start and complete firing so
    every piece reaches READY. PRD §3.8 requires every piece on a visit to be in
    READY/PICKED_UP/VOIDED before checkout, so settlement tests must fire pieces
    first. Returns the list of READY piece dicts in creation order.
    """
    pieces = []
    for idx, price in enumerate(bisque_prices):
        pieces.append(add_piece(
            visit_id, bisque_price_cents=price, firing_temp=firing_temp,
            sku=f"FIRE-{idx}", name=f"FirePiece{idx}"))
    batch = create_batch(firing_temp=firing_temp, capacity_slots=max(len(pieces), 1),
                         turnaround_hours=turnaround_hours)
    for piece in pieces:
        load_piece(batch, piece["id"])
    get_success_data(api_client.start_firing(batch["id"], STAFF))
    get_success_data(api_client.complete_firing(batch["id"], STAFF))
    return [get_success_data(api_client.get_piece(p["id"], STAFF)) for p in pieces]


def setup_loaded_piece(bisque_price_cents=5000, firing_temp="CONE_06", capacity_slots=4):
    """An OPEN walk-in visit with one piece LOADED into a LOADING batch (occupied 1).
    Returns (visit_dict, piece_dict_loaded, batch_dict_after_load).
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=bisque_price_cents, firing_temp=firing_temp)
    batch = create_batch(firing_temp=firing_temp, capacity_slots=capacity_slots)
    load_piece(batch, piece["id"])
    batch_after = get_success_data(api_client.get_batch(batch["id"], STAFF))
    return visit, piece, batch_after


def setup_full_capacity_batch(capacity_slots=1, firing_temp="CONE_06"):
    """A LOADING batch at full capacity (occupied == capacity), plus a spare PAINTED
    piece available to attempt an overflow load.

    Returns (visit, batch_after, loaded_piece, spare_piece).
    """
    visit = create_open_visit()
    loaded = add_piece(visit["id"], bisque_price_cents=2000, sku="CAP-1", name="Cap1",
                       firing_temp=firing_temp)
    spare = add_piece(visit["id"], bisque_price_cents=2000, sku="CAP-2", name="Cap2",
                      firing_temp=firing_temp)
    batch = create_batch(firing_temp=firing_temp, capacity_slots=capacity_slots)
    load_piece(batch, loaded["id"])
    batch_after = get_success_data(api_client.get_batch(batch["id"], STAFF))
    return visit, batch_after, loaded, spare


# ─── Tier 3: Visit lifecycle shortcuts ─────────────────────────────────────

def setup_settled_visit(member_id=None, bisque_price_cents=3000, points_redeemed=0):
    """Open a visit, fire its single piece to READY, then checkout to SETTLED.
    Returns (visit_dict_settled, piece_dict).
    """
    visit = create_open_visit(member_id=member_id)
    piece, _batch = fire_piece_to_ready(visit["id"], bisque_price_cents=bisque_price_cents)
    settled = get_success_data(api_client.checkout_visit(
        visit["id"], {"points_redeemed": points_redeemed}, STAFF))
    return settled, piece


# ─── Tier 4: Party-booking shortcuts ───────────────────────────────────────

def setup_cancelled_booking(member_id=None, package_tier="BASIC", guest_count=6):
    """A booking moved to terminal CANCELLED. Returns booking dict (after cancel)."""
    if member_id is None:
        member_id = create_member()["id"]
    booking = create_booking(member_id, package_tier=package_tier, guest_count=guest_count)
    cancelled = get_success_data(api_client.cancel_booking(booking["id"], MANAGER))
    return cancelled


# ─── Tier 5: Class series / enrollment shortcuts ───────────────────────────

def setup_enrolled_member(price_cents=12000, session_count=4, seat_capacity=5,
                          starts_at="2026-07-01T18:00:00Z"):
    """A member with one ENROLLED row in an OPEN series.
    Returns (member_after, series, enrollment)."""
    return create_member_with_lifetime(
        price_cents=price_cents, session_count=session_count,
        seat_capacity=seat_capacity, starts_at=starts_at)


def setup_full_series(price_cents=12000, session_count=4, starts_at="2026-08-05T18:00:00Z"):
    """A seat_capacity=1 series filled to FULL by one enrollment, plus a second
    ACTIVE member ready to attempt an overflow enroll.

    Returns (series_after, first_member, second_member).
    """
    m1 = create_member()
    m2 = create_member()
    series = create_series(session_count=session_count, seat_capacity=1,
                           price_cents=price_cents, starts_at=starts_at)
    get_success_data(api_client.enroll(series["id"], {"member_id": m1["id"]}, STAFF))
    series_after = get_success_data(api_client.get_series(series["id"], MANAGER))
    return series_after, m1, m2
