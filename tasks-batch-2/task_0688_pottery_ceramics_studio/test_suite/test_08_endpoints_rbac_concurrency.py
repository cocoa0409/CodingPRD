"""Endpoint, RBAC, OCC concurrency, reconciliation, and immediate-consistency
corners.

Queue B (Corner): sections endpoints, rbac, cross_cutting_complexity_layers,
consistency_model (non-stub instances).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    validate_paginated, get_success_data,
    create_member, create_open_visit, add_piece, create_batch, create_series,
    create_booking, create_member_with_lifetime, load_piece, fire_piece_to_ready,
    make_member_headers, NON_EXISTENT_UUID, TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
MANAGER = TEST_USERS["manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── endpoints ──────────────────────────────────────────────────────────────

def test_pay_deposit_confirms_booking(api):
    """PRD §3.6: "Paying the deposit moves it from DEPOSIT_PENDING to CONFIRMED: the
    payment supplies an amount_cents that must exactly equal the booking's
    deposit_due_cents... on success the deposit_paid_cents is set to the paid amount
    and the booking is CONFIRMED."

    Design: Corner/endpoints/pay_deposit_confirms_booking
    """
    member = create_member()
    booking = create_booking(member["id"], package_tier="DELUXE", guest_count=10,
                             scheduled_for="2026-09-15T18:00:00Z")  # deposit_due 20000
    confirmed = validate_success(
        api.pay_deposit(booking["id"], {"amount_cents": 20000}, STAFF), 200)
    assert confirmed["status"] == "CONFIRMED", confirmed["status"]
    assert confirmed["deposit_paid_cents"] == 20000, confirmed["deposit_paid_cents"]


def test_list_visits_paginated_envelope(api):
    """PRD §2.3: "The limit parameter caps the number of items returned." PRD §2.2:
    "Pagination-related fields in meta (limit, offset, total_count, has_more) are
    included for list endpoints." PRD §2.2: "response_type is either 'object' for a
    single resource or 'array' for a list of resources."

    Design: Corner/endpoints/list_visits_paginated_envelope
    """
    create_open_visit(party_size=1)
    create_open_visit(party_size=2)
    data, meta = validate_paginated(api.list_visits(STAFF, params={"limit": 1, "offset": 0}))
    assert len(data) == 1, len(data)
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]


def test_notification_payload_for_ready_piece(api):
    """PRD §3.3: "A pickup-notification payload is available for any piece that is
    READY or PICKED_UP, exposing the piece's ready_at together with the owning
    member's contact details." PRD §3.5: each readied piece is "stamped with a
    ready_at equal to the current logical-clock instant."

    Design: Corner/endpoints/notification_payload_for_ready_piece
    """
    member = create_member()
    visit = create_open_visit(member_id=member["id"])
    piece, _batch = fire_piece_to_ready(visit["id"], bisque_price_cents=3000)
    notif = validate_success(api.get_piece_notification(piece["id"], STAFF), 200)
    assert notif["status"] == "READY", notif["status"]
    assert notif["ready_at"] is not None and notif["ready_at"].startswith("2026-04-01T00:00:00")


# ─── rbac ───────────────────────────────────────────────────────────────────

def test_staff_cannot_void_visit(api):
    """PRD §2.1: "StudioManager... additionally owns the privileged levers: inventory
    management, voids, comps..." PRD §2.1: "a role attempting an operation outside
    its grant is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/staff_cannot_void_visit
    """
    visit = create_open_visit()
    res = api.void_visit(visit["id"], STAFF)
    validate_error(res, "ERR_FORBIDDEN_ROLE")
    after = validate_success(api.get_visit(visit["id"], STAFF), 200)
    assert after["status"] == "OPEN", after["status"]


def test_member_cannot_read_other_members_ledger(api):
    """PRD §2.1: "A LoyaltyMember who reads or acts on a resource whose owning
    member_id is not their own X-User-ID is rejected with ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/member_cannot_read_other_members_ledger
    """
    a = create_member()
    b = create_member()
    res = api.get_member_ledger(b["id"], make_member_headers(a["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_protected_endpoint_unauthenticated_rejected(api):
    """PRD §2.1: "There are two deliberate exceptions to the requirement that a
    recognized role be present: self-registration of a new loyalty member, and the
    opening of an anonymous walk-in visit." PRD §3.7: "A manager adds an item" —
    Anonymous may not manage inventory, so it is rejected with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/protected_endpoint_unauthenticated_rejected
    """
    res = api.create_paint_bar_item(
        {"sku": "GLZ-Z", "name": "Glaze Z", "category": "GLAZE",
         "unit_price_cents": 500, "reorder_threshold": 5}, ANON)
    validate_error_is_one_of(res, ["ERR_UNAUTHENTICATED", "ERR_FORBIDDEN_ROLE"])


# ─── cross_cutting_complexity_layers (OCC + reconciliation) ─────────────────

def test_occ_correct_version_load_succeeds(api):
    """PRD §2.9: "The server compares that supplied value against the batch's current
    version." PRD §3.4: "When these hold, the piece's kiln_batch_id is set to the
    batch, the piece advances from PAINTED to LOADED, the batch's occupied_slots is
    incremented by one, and the batch's version is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_load_succeeds
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=3000, sku="MUG-12OZ", name="Mug")
    batch = create_batch(capacity_slots=4)  # version 1
    res = api.load_piece(
        batch["id"],
        {"bisque_piece_id": piece["id"], "expected_kiln_batch_version": batch["version"]},
        STAFF)
    loaded = validate_success(res, 200)
    assert loaded["status"] == "LOADED", loaded["status"]
    batch_after = validate_success(api.get_batch(batch["id"], STAFF), 200)
    assert batch_after["occupied_slots"] == 1, batch_after["occupied_slots"]
    assert batch_after["version"] == 2, batch_after["version"]


def test_occ_stale_version_load_rejected(api):
    """PRD §2.9: "If they do not match — because some other load or un-load has
    already advanced the batch's version and shifted its occupied count since the
    client last read it — the load is rejected with ERR_STALE_BATCH_VERSION (HTTP
    412) on the stale-version check, before any slot is consumed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_load_rejected
    """
    visit = create_open_visit()
    p1 = add_piece(visit["id"], bisque_price_cents=2000, sku="S1", name="S1")
    p2 = add_piece(visit["id"], bisque_price_cents=2000, sku="S2", name="S2")
    batch = create_batch(capacity_slots=4)  # version 1
    bv0 = batch["version"]
    api.load_piece(
        batch["id"], {"bisque_piece_id": p1["id"], "expected_kiln_batch_version": bv0}, STAFF)
    # version now advanced past bv0; second load carrying bv0 is stale
    res = api.load_piece(
        batch["id"], {"bisque_piece_id": p2["id"], "expected_kiln_batch_version": bv0}, STAFF)
    validate_error(res, "ERR_STALE_BATCH_VERSION")
    batch_after = validate_success(api.get_batch(batch["id"], STAFF), 200)
    assert batch_after["occupied_slots"] == 1, batch_after["occupied_slots"]


def test_enrollment_withdraw_reconciles_balance(api):
    """PRD §3.11: "Withdrawing reverses the loyalty that the enrollment earned: the
    member's point_balance is decreased by the enrollment's points_earned, the
    member's lifetime_points_earned is decreased by the same amount." PRD §3.11: "The
    series' enrolled_count is decremented by one."

    Design: Corner/cross_cutting_complexity_layers/enrollment_withdraw_reconciles_member_balance
    """
    member, series, enr = create_member_with_lifetime(price_cents=12000, session_count=4)
    assert member["point_balance"] == 120  # floor(12000/100)
    withdrawn = validate_success(api.withdraw_enrollment(enr["id"], STAFF), 200)
    assert withdrawn["status"] == "WITHDRAWN", withdrawn["status"]
    member_after = validate_success(api.get_member(member["id"], MANAGER), 200)
    assert member_after["point_balance"] == 0, member_after["point_balance"]
    assert member_after["lifetime_points_earned"] == 0, member_after["lifetime_points_earned"]
    series_after = validate_success(api.get_series(series["id"], MANAGER), 200)
    assert series_after["enrolled_count"] == 0, series_after["enrolled_count"]


# ─── consistency_model ──────────────────────────────────────────────────────

def test_checkout_effects_visible_immediately(api):
    """PRD §3.8: "The resulting points_earned is pinned on the visit, the member's
    point_balance is increased by that amount, and the member's lifetime_points_earned
    is increased by the same amount." PRD §3.8: "The visit moves from OPEN to
    SETTLED, which is terminal."

    Design: Corner/consistency_model/checkout_all_effects_visible_same_response
    """
    member = create_member()  # BRONZE, no discount
    visit = create_open_visit(member_id=member["id"])
    # one piece 4000, fired; settled = 1000 fee + 4000 = 5000; earn floor(5000/100)=50
    fire_piece_to_ready(visit["id"], bisque_price_cents=4000)
    settled = validate_success(api.checkout_visit(visit["id"], {"points_redeemed": 0}, STAFF), 200)
    assert settled["settled_total_cents"] == 5000, settled["settled_total_cents"]
    assert settled["points_earned"] == 50, settled["points_earned"]
    assert settled["status"] == "SETTLED", settled["status"]
    member_after = validate_success(api.get_member(member["id"], MANAGER), 200)
    assert member_after["point_balance"] == 50, member_after["point_balance"]
    assert member_after["lifetime_points_earned"] == 50, member_after["lifetime_points_earned"]
