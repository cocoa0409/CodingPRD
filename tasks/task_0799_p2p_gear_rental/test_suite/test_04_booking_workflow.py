"""Approval, cancellation, handoff scheduling, pickup, and the extension cycle."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_handoff_payload, ApiErrorId,
    make_owner_headers, make_renter_headers,
    create_owner, create_verified_renter, create_active_listing,
    create_requested_booking, add_condition_report, setup_active_booking,
)


def _approved_booking(api, owner_email, renter_email, quantity=1):
    owner = create_owner(api, email=owner_email)
    renter = create_verified_renter(api, email=renter_email)
    listing = create_active_listing(api, owner["id"], quantity=quantity)
    booking = create_requested_booking(api, listing["id"], renter["id"],
                                       "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    get_success_data(api.approve_booking(booking["id"], make_owner_headers(owner["id"])))
    return owner, renter, listing, booking


# --- Invalid transitions (Corner/state_machines) -----------------------------

def test_approve_already_approved_booking_invalid(api):
    """PRD §2.7: "State legality — the target resource is in a state from which the
    requested transition is defined, else ERR_INVALID_STATE (409)."
    PRD §3.4: "Approving it transitions the booking REQUESTED → APPROVED ..."

    Design: Corner/state_machines/approve_already_approved_booking_invalid
    """
    owner, renter, listing, booking = _approved_booking(
        api, "owner_dbl_approve@x.com", "renter_dbl_approve@x.com")
    resp = api.approve_booking(booking["id"], make_owner_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_declined_terminal_booking_invalid(api):
    """PRD §3.4: "Declining instead transitions the booking REQUESTED → DECLINED and
    decrements the listing's active_booking_count by 1, releasing the availability unit
    that the request had held."
    PRD §2.7: "State legality — the target resource is in a state from which the
    requested transition is defined, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/cancel_declined_terminal_booking_invalid
    """
    owner = create_owner(api, email="owner_cancel_declined@x.com")
    renter = create_verified_renter(api, email="renter_cancel_declined@x.com")
    listing = create_active_listing(api, owner["id"], quantity=1)
    booking = create_requested_booking(api, listing["id"], renter["id"],
                                       "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    get_success_data(api.decline_booking(booking["id"], make_owner_headers(owner["id"])))
    resp = api.cancel_booking(booking["id"], make_renter_headers(renter["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_pickup_without_completed_handoff_rejected(api):
    """PRD §3.5: "a PICKUP handoff appointment for the booking must already be COMPLETED
    (or ERR_HANDOFF_MISSING), and a PICKUP condition report with at least one photo must
    exist (or ERR_CONDITION_PHOTOS_REQUIRED)."

    Design: Corner/state_machines/pickup_without_completed_handoff_rejected
    """
    owner, renter, listing, booking = _approved_booking(
        api, "owner_pu_nohandoff@x.com", "renter_pu_nohandoff@x.com")
    add_condition_report(api, booking["id"], owner["id"], "PICKUP")
    resp = api.pickup_booking(booking["id"], make_owner_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_HANDOFF_MISSING.value)


def test_cancel_cascades_scheduled_handoff_to_cancelled(api):
    """PRD §3.4: "Whenever a booking is declined or cancelled, any still-SCHEDULED handoff
    appointments for that booking are cascaded to CANCELLED and the owner's calendar slots
    are freed."
    PRD §3.4: "A renter who no longer wants an already-approved booking may cancel it while
    it is APPROVED, transitioning APPROVED → CANCELLED: this decrements the listing's
    active_booking_count by 1 ..."

    Design: Corner/state_machines/cancel_cascades_scheduled_handoff_to_cancelled
    """
    owner, renter, listing, booking = _approved_booking(
        api, "owner_cascade@x.com", "renter_cascade@x.com")
    handoff = get_success_data(api.create_handoff(
        booking["id"], create_handoff_payload("PICKUP", "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z"),
        make_owner_headers(owner["id"])))
    get_success_data(api.cancel_booking(booking["id"], make_renter_headers(renter["id"])))

    handoffs = get_success_data(api.list_booking_handoffs(booking["id"], make_owner_headers(owner["id"])))
    matched = next(h for h in handoffs if h["id"] == handoff["id"])
    assert matched["status"] == "CANCELLED", matched["status"]
    fresh_listing = get_success_data(api.get_listing(listing["id"], make_owner_headers(owner["id"])))
    assert fresh_listing["active_booking_count"] == 0, fresh_listing["active_booking_count"]


# --- Extension window validation (Corner/validations) ------------------------

def test_extension_new_end_not_after_end_rejected(api):
    """PRD §3.5: "The request requires the acting renter to own the booking, the booking
    to be ACTIVE, and the new_end_date to be strictly after the current end_date
    (otherwise ERR_EXTENSION_WINDOW_INVALID)."

    Design: Corner/validations/extension_new_end_not_after_end_rejected
    """
    sc = setup_active_booking(api, base_daily_rate_cents=10000, quantity=1)
    resp = api.request_extension(sc["booking_id"], {"new_end_date": "2026-06-05T00:00:00Z"},
                                 sc["renter_headers"])
    validate_error(resp, ApiErrorId.ERR_EXTENSION_WINDOW_INVALID.value)


# --- Cyclic extension: ACTIVE -> EXTENSION_REQUESTED -> ACTIVE (Difficulty) ---

def _extend_and_approve(api, owner_email, renter_email):
    sc = setup_active_booking(api, base_daily_rate_cents=10000, quantity=1)
    get_success_data(api.request_extension(sc["booking_id"], {"new_end_date": "2026-06-15T00:00:00Z"},
                                           sc["renter_headers"]))
    booking = get_success_data(api.decide_extension(sc["booking_id"], {"decision": "APPROVE"},
                                                    sc["owner_headers"]))
    return booking


def test_extension_approve_returns_booking_to_active(api):
    """PRD §3.5: "On approve, the booking transitions EXTENSION_REQUESTED → ACTIVE: the
    end_date is set to extension_requested_end_date, that field is cleared back to null,
    and billable_days, rental_subtotal_cents, renter_service_fee_cents, and
    provisional_total_cents are recomputed over the new, longer window using the dynamic
    daily pricing and provisional settlement rules."

    Design: Difficulty/non_linear_state_machine/booking_extension_cycle_returns_to_active
    """
    booking = _extend_and_approve(api, "owner_ext_a@x.com", "renter_ext_a@x.com")
    assert booking["status"] == "ACTIVE", booking["status"]
    assert booking["extension_requested_end_date"] is None


def test_extension_approve_reprices_new_window(api):
    """PRD §3.5: "On approve, the booking transitions EXTENSION_REQUESTED → ACTIVE: the
    end_date is set to extension_requested_end_date, that field is cleared back to null,
    and billable_days, rental_subtotal_cents, renter_service_fee_cents, and
    provisional_total_cents are recomputed over the new, longer window using the dynamic
    daily pricing and provisional settlement rules."

    Design: Difficulty/non_linear_state_machine/booking_extension_cycle_returns_to_active
    """
    booking = _extend_and_approve(api, "owner_ext_b@x.com", "renter_ext_b@x.com")
    assert booking["billable_days"] == 14, booking["billable_days"]
    assert booking["rental_subtotal_cents"] == 133200, booking["rental_subtotal_cents"]


# --- Compensating invariant: availability count conserved (Difficulty) -------

def test_cancel_from_approved_restores_availability_count(api):
    """PRD §3.4: "A renter who no longer wants an already-approved booking may cancel it
    while it is APPROVED, transitioning APPROVED → CANCELLED: this decrements the listing's
    active_booking_count by 1 and releases the deposit in full ..."

    Design: Difficulty/compensating_invariant/availability_units_conserved_across_book_and_cancel
    """
    owner, renter, listing, booking = _approved_booking(
        api, "owner_ci_count@x.com", "renter_ci_count@x.com")
    result = get_success_data(api.cancel_booking(booking["id"], make_renter_headers(renter["id"])))
    assert result["status"] == "CANCELLED"
    fresh = get_success_data(api.get_listing(listing["id"], make_owner_headers(owner["id"])))
    assert fresh["active_booking_count"] == 0, fresh["active_booking_count"]


def test_cancel_from_approved_releases_deposit_in_full(api):
    """PRD §3.4: "the held balance moves into released_cents, held_cents becomes 0, and
    the deposit's status becomes RELEASED, preserving the conservation invariant."

    Design: Difficulty/compensating_invariant/availability_units_conserved_across_book_and_cancel
    """
    owner, renter, listing, booking = _approved_booking(
        api, "owner_ci_dep@x.com", "renter_ci_dep@x.com")
    get_success_data(api.cancel_booking(booking["id"], make_renter_headers(renter["id"])))
    deposit = get_success_data(api.get_deposit(booking["id"], make_owner_headers(owner["id"])))[0]
    assert deposit["released_cents"] == 50000, deposit["released_cents"]
    assert deposit["held_cents"] == 0, deposit["held_cents"]


# --- Handoff calendar buffered-overlap (Difficulty) --------------------------

def _two_approved_bookings_with_first_handoff(api, owner_email, renter_email):
    owner = create_owner(api, email=owner_email)
    renter = create_verified_renter(api, email=renter_email)
    listing = create_active_listing(api, owner["id"], quantity=2)
    b1 = create_requested_booking(api, listing["id"], renter["id"],
                                  "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    b2 = create_requested_booking(api, listing["id"], renter["id"],
                                  "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    ohead = make_owner_headers(owner["id"])
    get_success_data(api.approve_booking(b1["id"], ohead))
    get_success_data(api.approve_booking(b2["id"], ohead))
    get_success_data(api.create_handoff(
        b1["id"], create_handoff_payload("PICKUP", "2026-06-01T10:00:00Z", "2026-06-01T10:30:00Z"),
        ohead))
    return owner, b2, ohead


def test_handoff_slot_conflict_within_right_buffer(api):
    """PRD §3.4: "The appointment occupies the interval from slot_start to slot_end
    inclusive, extended by a mandatory buffer of 60 minutes on each side. If that
    buffered, closed interval collides with any other still-SCHEDULED handoff on the same
    owner's calendar, the request is rejected with ERR_HANDOFF_SLOT_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/handoff_slot_buffered_closed_overlap
    """
    owner, b2, ohead = _two_approved_bookings_with_first_handoff(
        api, "owner_hf_a@x.com", "renter_hf_a@x.com")
    resp = api.create_handoff(
        b2["id"], create_handoff_payload("PICKUP", "2026-06-01T11:00:00Z", "2026-06-01T11:30:00Z"),
        ohead)
    validate_error(resp, ApiErrorId.ERR_HANDOFF_SLOT_CONFLICT.value)


def test_handoff_slot_conflict_within_left_buffer(api):
    """PRD §3.4: "The appointment occupies the interval from slot_start to slot_end
    inclusive, extended by a mandatory buffer of 60 minutes on each side. If that
    buffered, closed interval collides with any other still-SCHEDULED handoff on the same
    owner's calendar, the request is rejected with ERR_HANDOFF_SLOT_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/handoff_slot_buffered_closed_overlap
    """
    owner, b2, ohead = _two_approved_bookings_with_first_handoff(
        api, "owner_hf_b@x.com", "renter_hf_b@x.com")
    resp = api.create_handoff(
        b2["id"], create_handoff_payload("PICKUP", "2026-06-01T08:45:00Z", "2026-06-01T09:15:00Z"),
        ohead)
    validate_error(resp, ApiErrorId.ERR_HANDOFF_SLOT_CONFLICT.value)
