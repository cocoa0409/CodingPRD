"""Reservation booking rules: tee-time turnaround buffer, dining-table seat-
capacity aggregation, the active-membership precondition, golf-allowed gating,
field validity, and reservation reverse-reachability listing.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_member_headers,
    create_club, create_category, create_and_activate_membership,
    create_membership, create_resource, create_reservation, get_resource_version,
    setup_reservation,
)

_MANAGER = TEST_USERS["club_manager_headers"]


# ===========================================================================
# Difficulty: resource_temporal_overlap
# ===========================================================================

def test_tee_time_turnaround_buffer_blocks_close_booking(api):
    """PRD §3.4: "For a TEE_TIME or COURT, occupancy is exclusive: the requested
    interval, extended by the resource's turnaround_minutes buffer, must not
    overlap the interval of any existing CONFIRMED reservation on that resource —
    the buffer must separate the end of one booking from the start of the next, so
    a new booking is rejected if its window, padded by the turnaround on each
    side, touches another confirmed window."
    PRD §3.4: "A booking that violates either rule is refused with
    ERR_RESOURCE_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/tee_time_turnaround_buffer_overlap
    """
    club = create_club(name="Tee Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m1 = create_and_activate_membership(club["id"], cat["id"], holder_name="M1")
    m2 = create_and_activate_membership(club["id"], cat["id"], holder_name="M2")
    res = create_resource(club["id"], kind="TEE_TIME", label="Hole 1", turnaround_minutes=15)
    create_reservation(club["id"], res["id"], m1["id"],
                       "2026-02-01T09:00:00Z", "2026-02-01T09:10:00Z", res["version"])

    res_v1 = get_resource_version(res["id"])
    # 09:20 start is only 10 min after the 09:10 end -> within the 15-min buffer.
    resp = api.create_reservation({
        "club_id": club["id"], "resource_id": res["id"], "membership_id": m2["id"],
        "starts_at": "2026-02-01T09:20:00Z", "ends_at": "2026-02-01T09:40:00Z",
        "expected_resource_version": res_v1,
    }, make_member_headers(m2["id"]))
    validate_error(resp, ApiErrorId.ERR_RESOURCE_CONFLICT.value, 409)


def test_tee_time_booking_beyond_turnaround_buffer_succeeds(api):
    """PRD §3.4: "the requested interval, extended by the resource's
    turnaround_minutes buffer, must not overlap the interval of any existing
    CONFIRMED reservation on that resource — the buffer must separate the end of
    one booking from the start of the next."
    PRD §3.4: "A successful create places the reservation in CONFIRMED, holds the
    window on the resource, and bumps the resource's version."

    Design: Difficulty/resource_temporal_overlap/tee_time_turnaround_buffer_overlap
    """
    club = create_club(name="Tee Club 2")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m1 = create_and_activate_membership(club["id"], cat["id"], holder_name="M1")
    m2 = create_and_activate_membership(club["id"], cat["id"], holder_name="M2")
    res = create_resource(club["id"], kind="TEE_TIME", label="Hole 1", turnaround_minutes=15)
    create_reservation(club["id"], res["id"], m1["id"],
                       "2026-02-01T09:00:00Z", "2026-02-01T09:10:00Z", res["version"])

    res_v1 = get_resource_version(res["id"])
    # 09:25 start is >=15 min after the 09:10 end -> the buffer is satisfied.
    data = validate_success(api.create_reservation({
        "club_id": club["id"], "resource_id": res["id"], "membership_id": m2["id"],
        "starts_at": "2026-02-01T09:25:00Z", "ends_at": "2026-02-01T09:40:00Z",
        "expected_resource_version": res_v1,
    }, make_member_headers(m2["id"])), expected_status=201)
    assert data["status"] == "CONFIRMED", f"got {data['status']}"


def test_dining_table_seat_capacity_aggregate_overlap_rejected(api):
    """PRD §3.4: "For a DINING_TABLE, multiple parties may overlap so long as the
    sum of the party_size values of all CONFIRMED reservations whose intervals
    overlap the requested interval does not exceed the resource's seat_capacity."
    PRD §3.4: "A booking that violates either rule is refused with
    ERR_RESOURCE_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/dining_table_seat_capacity_aggregate_overlap
    """
    club = create_club(name="Dine Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    m1 = create_and_activate_membership(club["id"], cat["id"], holder_name="M1")
    m2 = create_and_activate_membership(club["id"], cat["id"], holder_name="M2")
    m3 = create_and_activate_membership(club["id"], cat["id"], holder_name="M3")
    res = create_resource(club["id"], kind="DINING_TABLE", label="Table 5",
                          turnaround_minutes=0, seat_capacity=4)
    # Two overlapping party_size=2 reservations -> sum 4 == capacity (both succeed).
    create_reservation(club["id"], res["id"], m1["id"],
                       "2026-02-01T19:00:00Z", "2026-02-01T20:00:00Z",
                       get_resource_version(res["id"]), party_size=2)
    create_reservation(club["id"], res["id"], m2["id"],
                       "2026-02-01T19:00:00Z", "2026-02-01T20:00:00Z",
                       get_resource_version(res["id"]), party_size=2)

    res_v2 = get_resource_version(res["id"])
    # A third overlapping party_size=1 pushes the sum to 5 > capacity 4.
    resp = api.create_reservation({
        "club_id": club["id"], "resource_id": res["id"], "membership_id": m3["id"],
        "starts_at": "2026-02-01T19:30:00Z", "ends_at": "2026-02-01T19:45:00Z",
        "party_size": 1, "expected_resource_version": res_v2,
    }, make_member_headers(m3["id"]))
    validate_error(resp, ApiErrorId.ERR_RESOURCE_CONFLICT.value, 409)


def test_dining_table_overlap_within_seat_capacity_succeeds(api):
    """PRD §3.4: "For a DINING_TABLE, multiple parties may overlap so long as the
    sum of the party_size values of all CONFIRMED reservations whose intervals
    overlap the requested interval does not exceed the resource's seat_capacity."

    Design: Difficulty/resource_temporal_overlap/dining_table_seat_capacity_aggregate_overlap
    """
    club = create_club(name="Dine Club 2")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    m1 = create_and_activate_membership(club["id"], cat["id"], holder_name="M1")
    m2 = create_and_activate_membership(club["id"], cat["id"], holder_name="M2")
    res = create_resource(club["id"], kind="DINING_TABLE", label="Table 5",
                          turnaround_minutes=0, seat_capacity=4)
    create_reservation(club["id"], res["id"], m1["id"],
                       "2026-02-01T19:00:00Z", "2026-02-01T20:00:00Z",
                       get_resource_version(res["id"]), party_size=2)
    # Second overlapping party_size=2 keeps the sum at 4 == capacity -> allowed.
    data = validate_success(api.create_reservation({
        "club_id": club["id"], "resource_id": res["id"], "membership_id": m2["id"],
        "starts_at": "2026-02-01T19:00:00Z", "ends_at": "2026-02-01T20:00:00Z",
        "party_size": 2, "expected_resource_version": get_resource_version(res["id"]),
    }, make_member_headers(m2["id"])), expected_status=201)
    assert data["status"] == "CONFIRMED", f"got {data['status']}"


# ===========================================================================
# Difficulty: cross_entity_state_dependency
# ===========================================================================

def test_reservation_create_requires_active_membership(api):
    """PRD §3.4: "The booking membership must be ACTIVE; a suspended or otherwise
    non-active member attempting to book is refused with
    ERR_MEMBERSHIP_NOT_ACTIVE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/reservation_requires_active_membership
    """
    club = create_club(name="Dep1 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    validate_success(api.suspend_membership(m["id"], _MANAGER))  # now SUSPENDED
    res = create_resource(club["id"], kind="COURT", label="Court 1", turnaround_minutes=0)

    resp = api.create_reservation({
        "club_id": club["id"], "resource_id": res["id"], "membership_id": m["id"],
        "starts_at": "2026-02-01T10:00:00Z", "ends_at": "2026-02-01T11:00:00Z",
        "expected_resource_version": res["version"],
    }, make_member_headers(m["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value, 409)

    listing = get_success_data(api.list_reservations(_MANAGER, params={"resource_id": res["id"]}))
    assert listing == [], f"no reservation should be created, got {listing}"


def test_reservation_create_rejected_for_pending_membership(api):
    """PRD §3.4: "The booking membership must be ACTIVE; a suspended or otherwise
    non-active member attempting to book is refused with ERR_MEMBERSHIP_NOT_ACTIVE
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/reservation_requires_active_membership
    """
    club = create_club(name="Dep1b Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    # Membership created but NEVER activated -> still PENDING (non-active).
    m = create_membership(club["id"], cat["id"], holder_name="M")
    res = create_resource(club["id"], kind="COURT", label="Court 1", turnaround_minutes=0)

    resp = api.create_reservation({
        "club_id": club["id"], "resource_id": res["id"], "membership_id": m["id"],
        "starts_at": "2026-02-01T10:00:00Z", "ends_at": "2026-02-01T11:00:00Z",
        "expected_resource_version": res["version"],
    }, make_member_headers(m["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value, 409)


# (The guest_checkin_requires_active_sponsor instance under the same rule is
#  translated in test_04_guests_and_quotas.py alongside the guest-pass flows.)


# ===========================================================================
# Corner: validations (golf / field validity)
# ===========================================================================

def test_social_member_cannot_book_tee_time(api):
    """PRD §3.4: "If the resource is a tee time, the member's category must permit
    golf — allows_golf true — and a tee-time booking from a category whose
    allows_golf is false is refused with ERR_GOLF_NOT_ALLOWED (HTTP 422)."

    Design: Corner/validations/golf_not_allowed_for_social_tee_time
    """
    club = create_club(name="V1 Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    # allows_golf omitted -> defaults false.
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    res = create_resource(club["id"], kind="TEE_TIME", label="Hole 1", turnaround_minutes=0)

    resp = api.create_reservation({
        "club_id": club["id"], "resource_id": res["id"], "membership_id": m["id"],
        "starts_at": "2026-02-01T10:00:00Z", "ends_at": "2026-02-01T11:00:00Z",
        "expected_resource_version": res["version"],
    }, make_member_headers(m["id"]))
    validate_error(resp, ApiErrorId.ERR_GOLF_NOT_ALLOWED.value, 422)


def test_reservation_ends_at_not_after_starts_at_rejected(api):
    """PRD §3.4: "ends_at must be strictly after starts_at; a party_size below 1 or
    an ends_at at or before starts_at is refused with ERR_VALIDATION (HTTP 422)."

    Design: Corner/validations/ends_before_starts_rejected
    """
    club = create_club(name="V2 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    res = create_resource(club["id"], kind="TEE_TIME", label="Hole 1", turnaround_minutes=0)

    resp = api.create_reservation({
        "club_id": club["id"], "resource_id": res["id"], "membership_id": m["id"],
        "starts_at": "2026-02-01T11:00:00Z", "ends_at": "2026-02-01T10:00:00Z",
        "expected_resource_version": res["version"],
    }, make_member_headers(m["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


# ===========================================================================
# Corner: endpoints (reservation reverse-reachability)
# ===========================================================================

def test_list_reservations_by_membership(api):
    """PRD §2.10: "List endpoints support filtering by the foreign keys their
    resources carry — for example listing reservations by resource_id or
    membership_id ... so a caller can reach child records from a parent
    identifier."

    Design: Corner/endpoints/list_reservations_by_membership_reverse_reachability
    """
    club, cat, m, resource, rsv = setup_reservation(kind="COURT", turnaround_minutes=0)
    listing = get_success_data(api.list_reservations(
        make_member_headers(m["id"]), params={"membership_id": m["id"]}))
    ids = [r["id"] for r in listing]
    assert rsv["id"] in ids, f"membership filter should return the member's reservation, got {ids}"
