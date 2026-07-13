"""Booking request creation: state, availability, trust gate, listing-active gate, OCC, RBAC."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_booking_payload, ApiErrorId,
    make_owner_headers, make_renter_headers, platform_headers as _platform_headers,
    create_owner, create_verified_renter, create_active_listing, create_draft_listing,
    create_requested_booking, current_listing_version, setup_active_booking,
)


def test_booking_initial_state_is_requested(api):
    """PRD §3.3: "When all conditions pass, the booking is created in REQUESTED status
    and priced immediately."
    PRD §3.3: "Creating the booking also increments the listing's active_booking_count
    by 1 and increments the listing's version by 1 ..."

    Design: Corner/state_machines/booking_initial_state_is_requested
    """
    owner = create_owner(api, email="owner_init_state@x.com")
    renter = create_verified_renter(api, email="renter_init_state@x.com")
    listing = create_active_listing(api, owner["id"], quantity=1)
    booking = create_requested_booking(api, listing["id"], renter["id"],
                                       "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    assert booking["status"] == "REQUESTED"
    fresh = get_success_data(api.get_listing(listing["id"], make_owner_headers(owner["id"])))
    assert fresh["active_booking_count"] == 1, fresh["active_booking_count"]


def test_owner_cannot_approve_booking_on_nonowned_listing_forbidden(api):
    """PRD §2.1: "Ownership checks compare the owning foreign key of the target resource
    to X-User-ID — for a listing, its owner_id; for a booking-scoped owner action, the
    owner_id of the listing the booking references ..."

    Design: Corner/rbac/owner_cannot_approve_booking_on_nonowned_listing_forbidden
    """
    owner_a = create_owner(api, email="ownerA_approve@x.com")
    owner_b = create_owner(api, email="ownerB_approve@x.com")
    renter = create_verified_renter(api, email="renter_approve_rbac@x.com")
    listing = create_active_listing(api, owner_a["id"], quantity=1)
    booking = create_requested_booking(api, listing["id"], renter["id"],
                                       "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    resp = api.approve_booking(booking["id"], make_owner_headers(owner_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_occ_stale_listing_version_on_booking_rejected(api):
    """PRD §2.6: "If the owner has since re-priced, changed the demand multiplier,
    adjusted quantity, or a prior booking has advanced the listing, the listing's
    version will no longer equal the submitted expected_listing_version; the create is
    then rejected with ERR_STALE_LISTING_VERSION (HTTP 412) ..."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_listing_version_on_booking_rejected
    """
    owner = create_owner(api, email="owner_occ_listing@x.com")
    renter = create_verified_renter(api, email="renter_occ_listing@x.com")
    listing = create_active_listing(api, owner["id"], quantity=1)
    stale_version = listing["version"] - 1
    payload = create_booking_payload(listing["id"], renter["id"],
                                     "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", stale_version)
    resp = api.create_booking(payload, make_renter_headers(renter["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_LISTING_VERSION.value)


# --- Cross-entity: booking create depends on Listing.ACTIVE ------------------

def test_booking_create_rejected_when_listing_suspended(api):
    """PRD §3.3: "The listing must exist and be ACTIVE, or the request is rejected with
    ERR_LISTING_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/booking_create_depends_on_listing_active
    """
    owner = create_owner(api, email="owner_ce_susp@x.com")
    renter = create_verified_renter(api, email="renter_ce_susp@x.com")
    listing = create_active_listing(api, owner["id"], quantity=1)
    get_success_data(api.suspend_listing(listing["id"], make_owner_headers(owner["id"])))
    version = current_listing_version(api, listing["id"], make_renter_headers(renter["id"]))
    payload = create_booking_payload(listing["id"], renter["id"],
                                     "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", version)
    resp = api.create_booking(payload, make_renter_headers(renter["id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE.value)


def test_booking_create_rejected_when_listing_draft(api):
    """PRD §3.3: "The listing must exist and be ACTIVE, or the request is rejected with
    ERR_LISTING_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/booking_create_depends_on_listing_active
    """
    owner = create_owner(api, email="owner_ce_draft@x.com")
    renter = create_verified_renter(api, email="renter_ce_draft@x.com")
    listing = create_draft_listing(api, owner["id"], quantity=1)
    payload = create_booking_payload(listing["id"], renter["id"],
                                     "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z",
                                     listing["version"])
    resp = api.create_booking(payload, make_renter_headers(renter["id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE.value)


# --- Half-open window capacity semantics --------------------------------------

def test_adjacent_booking_window_is_accepted(api):
    """PRD §3.3: "Because the interval is half-open, a booking that ends exactly when
    another begins does not overlap — adjacency is allowed."

    Design: Difficulty/resource_temporal_overlap/booking_window_halfopen_capacity_overlap
    """
    owner = create_owner(api, email="owner_adj@x.com")
    renter = create_verified_renter(api, email="renter_adj@x.com")
    listing = create_active_listing(api, owner["id"], quantity=1)
    create_requested_booking(api, listing["id"], renter["id"],
                             "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    adjacent = create_requested_booking(api, listing["id"], renter["id"],
                                        "2026-06-08T00:00:00Z", "2026-06-15T00:00:00Z")
    assert adjacent["status"] == "REQUESTED"


def test_overlapping_booking_window_rejected_at_capacity(api):
    """PRD §3.3: "counting the listing's other bookings that overlap the requested
    interval and sit in an availability-consuming state (REQUESTED, APPROVED, ACTIVE,
    EXTENSION_REQUESTED, or LATE), that count must be strictly less than the listing's
    quantity, otherwise the request is rejected with ERR_LISTING_UNAVAILABLE."

    Design: Difficulty/resource_temporal_overlap/booking_window_halfopen_capacity_overlap
    """
    owner = create_owner(api, email="owner_ov@x.com")
    renter = create_verified_renter(api, email="renter_ov@x.com")
    listing = create_active_listing(api, owner["id"], quantity=1)
    create_requested_booking(api, listing["id"], renter["id"],
                             "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    version = current_listing_version(api, listing["id"], make_renter_headers(renter["id"]))
    payload = create_booking_payload(listing["id"], renter["id"],
                                     "2026-06-05T00:00:00Z", "2026-06-10T00:00:00Z", version)
    resp = api.create_booking(payload, make_renter_headers(renter["id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_UNAVAILABLE.value)


# --- Trust gate (Corner/validations) -----------------------------------------

def test_trust_too_low_blocks_high_value_booking(api):
    """PRD §3.3: "If the listing's declared_value_cents is greater than 100000 cents,
    the renter's trust_score must be at least 300; a renter below that threshold is
    rejected with ERR_TRUST_TOO_LOW."
    PRD §3.6: "increments the renter's late_return_count by 1, and recomputes the
    renter's trust_score."

    Design: Corner/validations/trust_too_low_blocks_high_value_booking
    """
    sc = setup_active_booking(api, base_daily_rate_cents=10000, deposit_cents=50000,
                              declared_value_cents=90000, quantity=1)
    # Push the booking overdue so the renter takes a late-return trust penalty.
    api.set_clock({"to_iso8601": "2026-06-10T00:00:00Z"}, _platform_headers())
    api.detect_late_returns(_platform_headers())
    renter_id = sc["renter_id"]
    profile = get_success_data(api.get_user(renter_id, _platform_headers()))
    assert profile["trust_score"] == 275, profile["trust_score"]

    high_value = create_active_listing(api, sc["owner_id"], declared_value_cents=200000,
                                       base_daily_rate_cents=10000, deposit_cents=100000, quantity=1)
    version = current_listing_version(api, high_value["id"], make_renter_headers(renter_id))
    payload = create_booking_payload(high_value["id"], renter_id,
                                     "2026-07-01T00:00:00Z", "2026-07-05T00:00:00Z", version)
    resp = api.create_booking(payload, make_renter_headers(renter_id))
    validate_error(resp, ApiErrorId.ERR_TRUST_TOO_LOW.value)


# --- Validation precedence: referential (5) beats temporal (8) ----------------

def _suspended_full_listing(api, owner_email, renter_email):
    owner = create_owner(api, email=owner_email)
    renter = create_verified_renter(api, email=renter_email)
    listing = create_active_listing(api, owner["id"], quantity=1)
    create_requested_booking(api, listing["id"], renter["id"],
                             "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    get_success_data(api.suspend_listing(listing["id"], make_owner_headers(owner["id"])))
    version = current_listing_version(api, listing["id"], make_renter_headers(renter["id"]))
    return owner, renter, listing, version


def test_referential_beats_temporal_partial_overlap(api):
    """PRD §2.7: "Referenced-entity state — a required sibling entity is in its required
    state; for example a booking create or approve requires the listing to be ACTIVE,
    else ERR_LISTING_NOT_ACTIVE (409)."
    PRD §2.7: "Availability — the requested rental or extension window does not collide
    with too many overlapping bookings, else ERR_LISTING_UNAVAILABLE (409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_booking_create
    """
    owner, renter, listing, version = _suspended_full_listing(
        api, "owner_pc_a@x.com", "renter_pc_a@x.com")
    payload = create_booking_payload(listing["id"], renter["id"],
                                     "2026-06-03T00:00:00Z", "2026-06-06T00:00:00Z", version)
    resp = api.create_booking(payload, make_renter_headers(renter["id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE.value)


def test_referential_beats_temporal_full_overlap(api):
    """PRD §2.7: "Referenced-entity state — a required sibling entity is in its required
    state; for example a booking create or approve requires the listing to be ACTIVE,
    else ERR_LISTING_NOT_ACTIVE (409)."
    PRD §2.7: "Availability — the requested rental or extension window does not collide
    with too many overlapping bookings, else ERR_LISTING_UNAVAILABLE (409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_booking_create
    """
    owner, renter, listing, version = _suspended_full_listing(
        api, "owner_pc_b@x.com", "renter_pc_b@x.com")
    payload = create_booking_payload(listing["id"], renter["id"],
                                     "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", version)
    resp = api.create_booking(payload, make_renter_headers(renter["id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE.value)
