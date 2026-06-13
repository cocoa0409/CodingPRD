"""Capacity routing, the waitlist lifecycle, promotion cascades, and OCC.

Covers difficulty rules boundary_precision_check, non_linear_state_machine
(waitlist fork), transitive_cascade (registration-cancel promotion), and corner
instances under sections state_machines, endpoints, and
cross_cutting_complexity_layers.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_participant_headers,
)
from test_helpers import fixtures as fx
from test_helpers.factories import registration_payload

RD = TEST_USERS["race_director_headers"]


# ---------------------------------------------------------------------------
# Initial state / invalid-state on re-confirm (corner: state_machines)
# ---------------------------------------------------------------------------
def test_new_registration_starts_in_pending_payment(api):
    """PRD §3.2: "A new registration begins in `PENDING_PAYMENT`."

    Design: Corner/state_machines/new_registration_starts_in_pending_payment
    """
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    reg = fx.create_registration(event, distance, wave, participant)
    assert reg["status"] == "PENDING_PAYMENT", \
        f"expected PENDING_PAYMENT, got {reg['status']}"


def test_confirm_payment_from_confirmed_returns_invalid_state(api):
    """PRD §3.3: "Confirmation is only valid from `PENDING_PAYMENT`; attempting it
    from any other status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_payment_from_confirmed_returns_invalid_state
    """
    event, distance, wave, participant, reg = fx.setup_confirmed_registration(capacity_total=5)
    headers = make_participant_headers(participant["id"])
    dv = fx.distance_version(distance["id"], headers)
    resp = api.confirm_payment(reg["id"], {"expected_distance_version": dv}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Capacity boundary: full distance routes to WAITLISTED
# (difficulty: boundary_precision_check)
# ---------------------------------------------------------------------------
def test_full_distance_confirm_routes_to_waitlist(api):
    """PRD §3.3: "If instead the distance is full — `confirmed_count` is greater than
    or equal to `capacity_total` ... the registration is routed to `WAITLISTED`
    rather than erroring, no charge is captured, `amount_paid_cents` stays 0, and the
    system creates a `WaitlistEntry` for this registration on the distance in the
    `QUEUED` state."

    Design: Difficulty/boundary_precision_check/distance_capacity_boundary_full_routes_to_waitlist
    """
    # Capacity 1: P1 confirmed (confirmed_count == 1 == capacity), P2 -> WAITLISTED.
    event, distance, wave = fx.setup_open_event(capacity_total=1)
    p1 = fx.create_participant()
    reg1 = fx.create_registration(event, distance, wave, p1)
    reg1 = fx.confirm_registration(reg1, distance, p1)
    assert reg1["status"] == "CONFIRMED"

    p2 = fx.create_participant()
    reg2 = fx.create_registration(event, distance, wave, p2)
    h2 = make_participant_headers(p2["id"])
    dv = fx.distance_version(distance["id"], h2)
    resp = api.confirm_payment(reg2["id"], {"expected_distance_version": dv}, h2)
    routed = validate_success(resp)
    assert routed["status"] == "WAITLISTED", \
        f"full distance must route to WAITLISTED, got {routed['status']}"
    dist = fx.get_distance_data(distance["id"])
    assert dist["confirmed_count"] == 1, \
        f"confirmed_count must stay at capacity 1, got {dist['confirmed_count']}"


def test_room_available_confirm_routes_to_confirmed(api):
    """PRD §3.3: "If the distance has room — its `confirmed_count` is below
    `capacity_total` ... the registration advances from `PENDING_PAYMENT` to
    `CONFIRMED`."

    Design: Difficulty/boundary_precision_check/distance_capacity_boundary_full_routes_to_waitlist
    """
    # Capacity 2, only one confirmed: a second confirm still has room (1 < 2).
    event, distance, wave = fx.setup_open_event(capacity_total=2)
    p1 = fx.create_participant()
    reg1 = fx.create_registration(event, distance, wave, p1)
    fx.confirm_registration(reg1, distance, p1)

    p2 = fx.create_participant()
    reg2 = fx.create_registration(event, distance, wave, p2)
    h2 = make_participant_headers(p2["id"])
    dv = fx.distance_version(distance["id"], h2)
    resp = api.confirm_payment(reg2["id"], {"expected_distance_version": dv}, h2)
    confirmed = validate_success(resp)
    assert confirmed["status"] == "CONFIRMED", \
        f"room available must route to CONFIRMED, got {confirmed['status']}"


# ---------------------------------------------------------------------------
# Distance version increment / OCC stale version
# (corner: cross_cutting_complexity_layers, endpoints)
# ---------------------------------------------------------------------------
def test_distance_version_increments_on_confirm(api):
    """PRD §3.3: "Confirmation increments the distance's `confirmed_count` (and
    `charity_confirmed_count` for a charity entry) and bumps `Distance.version`."

    Design: Corner/cross_cutting_complexity_layers/distance_version_increments_on_confirm
    """
    event, distance, wave = fx.setup_open_event(capacity_total=5)
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    reg = fx.create_registration(event, distance, wave, participant)
    dv_before = fx.distance_version(distance["id"], headers)
    resp = api.confirm_payment(reg["id"], {"expected_distance_version": dv_before}, headers)
    validate_success(resp)
    dist = fx.get_distance_data(distance["id"])
    assert dist["version"] == dv_before + 1, \
        f"Distance.version must advance by 1, was {dv_before}, now {dist['version']}"
    assert dist["confirmed_count"] == 1


def test_confirm_with_stale_distance_version_returns_412(api):
    """PRD §2.5: "If the submitted `expected_distance_version` does not match the
    distance's current `version`, the confirmation is rejected with
    `ERR_STALE_DISTANCE_VERSION` (HTTP 412), forcing the client to re-read the
    distance before retrying."

    Design: Corner/endpoints/confirm_payment_with_stale_distance_version_returns_412
    """
    # Capacity 5: P1 and P2 both read the same version; P1 confirms (version bumps);
    # P2 confirms with the now-stale version.
    event, distance, wave = fx.setup_open_event(capacity_total=5)
    p1 = fx.create_participant()
    p2 = fx.create_participant()
    h1 = make_participant_headers(p1["id"])
    h2 = make_participant_headers(p2["id"])
    reg1 = fx.create_registration(event, distance, wave, p1)
    reg2 = fx.create_registration(event, distance, wave, p2)
    shared_version = fx.distance_version(distance["id"], h2)
    validate_success(api.confirm_payment(reg1["id"], {"expected_distance_version": shared_version}, h1))
    resp = api.confirm_payment(reg2["id"], {"expected_distance_version": shared_version}, h2)
    validate_error(resp, ApiErrorId.ERR_STALE_DISTANCE_VERSION.value)
    after = fx.get_registration_data(reg2["id"])
    assert after["status"] == "PENDING_PAYMENT", \
        f"rejected confirm must leave P2 PENDING_PAYMENT, got {after['status']}"


def test_claim_with_stale_distance_version_returns_412(api):
    """PRD §2.5: "The same rule guards waitlist claims: claiming an offered slot must
    carry `expected_distance_version` matching the distance's current `version`. If
    another writer has advanced the version since the claimant last read it ... the
    claim is rejected with `ERR_STALE_DISTANCE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/claim_stale_distance_version_returns_412
    """
    # P2 captures the distance version while WAITLISTED, then P1 cancels (version
    # bumps, P2 promoted to OFFERED). P2 claims with the stale pre-cancel version.
    event, distance, wave, p1, reg1, resolved = fx.setup_capacity_one_with_waitlist(num_waitlisted=1)
    p2, reg2, wl2 = resolved[0]
    h2 = make_participant_headers(p2["id"])
    stale_version = fx.distance_version(distance["id"], h2)
    fx.api_cancel(reg1, p1)  # frees slot -> bumps version, promotes P2 to OFFERED
    resp = api.claim_waitlist_entry(wl2["id"], {"expected_distance_version": stale_version}, h2)
    validate_error(resp, ApiErrorId.ERR_STALE_DISTANCE_VERSION.value)
    entry = fx.get_waitlist_entry_data(wl2["id"])
    assert entry["status"] == "OFFERED", \
        f"rejected claim must leave the entry OFFERED, got {entry['status']}"


# ---------------------------------------------------------------------------
# Waitlist branch: OFFERED -> DECLINED (difficulty: non_linear_state_machine)
# ---------------------------------------------------------------------------
def test_offered_waitlist_decline_cancels_registration(api):
    """PRD §3.3: "Alternatively the offered participant may decline, moving the entry
    from `OFFERED` to `DECLINED`, which cancels the linked registration and promotes
    the next queued entry to `OFFERED`."

    Design: Difficulty/non_linear_state_machine/waitlist_offer_branches_to_three_terminals
    """
    event, distance, wave, p1, reg1, p2, reg2, wl2 = fx.setup_offered_waitlist_entry()
    h2 = make_participant_headers(p2["id"])
    resp = api.decline_waitlist_entry(wl2["id"], h2)
    declined = validate_success(resp)
    assert declined["status"] == "DECLINED", f"expected DECLINED, got {declined['status']}"
    reg2_after = fx.get_registration_data(reg2["id"])
    assert reg2_after["status"] == "CANCELLED", \
        f"declining must cancel the linked registration, got {reg2_after['status']}"


def test_offered_waitlist_claim_confirms_registration(api):
    """PRD §3.3: "A successful claim moves the entry from `OFFERED` to `CLAIMED`,
    transitions the linked registration from `WAITLISTED` to `CONFIRMED` capturing the
    charge through the same final pricing computation, increments the distance's
    `confirmed_count`, and bumps `Distance.version`."

    Design: Difficulty/non_linear_state_machine/waitlist_offer_branches_to_three_terminals
    """
    event, distance, wave, p1, reg1, p2, reg2, wl2 = fx.setup_offered_waitlist_entry()
    h2 = make_participant_headers(p2["id"])
    dv = fx.distance_version(distance["id"], h2)
    resp = api.claim_waitlist_entry(wl2["id"], {"expected_distance_version": dv}, h2)
    claimed = validate_success(resp)
    assert claimed["status"] == "CLAIMED", f"expected CLAIMED, got {claimed['status']}"
    reg2_after = fx.get_registration_data(reg2["id"])
    assert reg2_after["status"] == "CONFIRMED", \
        f"claiming must confirm the linked registration, got {reg2_after['status']}"


# ---------------------------------------------------------------------------
# Registration cancel releases capacity then promotes waitlist
# (difficulty: transitive_cascade)
# ---------------------------------------------------------------------------
def test_registration_cancel_promotes_head_waitlist_entry(api):
    """PRD §3.4: "Because cancelling a confirmed registration frees a slot, the head
    queued waitlist entry on that distance is promoted to `OFFERED` and its `version`
    bumped, exactly as in §3.3."
    PRD §3.3: "Promotion stamps `offer_expires_utc` to the current clock plus the
    offer time-to-live of 24 hours and bumps that entry's `version`."

    Design: Difficulty/transitive_cascade/registration_cancel_releases_capacity_then_promotes_waitlist
    """
    event, distance, wave, p1, reg1, resolved = fx.setup_capacity_one_with_waitlist(num_waitlisted=1)
    p2, reg2, wl2 = resolved[0]
    fx.api_cancel(reg1, p1)
    dist = fx.get_distance_data(distance["id"])
    assert dist["confirmed_count"] == 0, \
        f"cancelling the confirmed slot must drop confirmed_count to 0, got {dist['confirmed_count']}"
    entry = fx.get_waitlist_entry_data(wl2["id"])
    assert entry["status"] == "OFFERED", \
        f"head queued entry must be promoted to OFFERED, got {entry['status']}"
    assert entry["offer_expires_utc"] is not None, \
        "promotion must stamp offer_expires_utc"


def test_promoted_offer_can_be_claimed_into_freed_slot(api):
    """PRD §3.4: "Because cancelling a confirmed registration frees a slot, the head
    queued waitlist entry on that distance is promoted to `OFFERED` and its `version`
    bumped, exactly as in §3.3."
    PRD §3.3: "A successful claim moves the entry from `OFFERED` to `CLAIMED`,
    transitions the linked registration from `WAITLISTED` to `CONFIRMED` capturing the
    charge ... increments the distance's `confirmed_count`".

    Design: Difficulty/transitive_cascade/registration_cancel_releases_capacity_then_promotes_waitlist
    """
    # After the cancel frees the slot and promotes P2, P2 can claim into the freed
    # slot, restoring confirmed_count to 1 — the cascade's released capacity is real.
    event, distance, wave, p1, reg1, resolved = fx.setup_capacity_one_with_waitlist(num_waitlisted=1)
    p2, reg2, wl2 = resolved[0]
    fx.api_cancel(reg1, p1)
    h2 = make_participant_headers(p2["id"])
    dv = fx.distance_version(distance["id"], h2)
    claimed = validate_success(api.claim_waitlist_entry(wl2["id"], {"expected_distance_version": dv}, h2))
    assert claimed["status"] == "CLAIMED"
    dist = fx.get_distance_data(distance["id"])
    assert dist["confirmed_count"] == 1, \
        f"claiming the promoted offer must refill the freed slot, got {dist['confirmed_count']}"
    assert fx.get_registration_data(reg2["id"])["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Offer expiry promotes next queued
# (corner: cross_cutting_complexity_layers)
# ---------------------------------------------------------------------------
def test_offer_expiry_promotes_next_queued_entry(api):
    """PRD §3.3: "an offered entry whose window has elapsed is swept by the race
    director's expiry check: when the current clock is at or after `offer_expires_utc`,
    the entry moves from `OFFERED` to `EXPIRED`, and the next queued entry on the
    distance (lowest `created_at`) is promoted to `OFFERED` with its own
    `offer_expires_utc` stamped."

    Design: Corner/cross_cutting_complexity_layers/waitlist_offer_expires_promotes_next_queued
    """
    # Capacity 1: P1 CONFIRMED; P2, P3 WAITLISTED. P1 cancels -> P2 OFFERED.
    event, distance, wave, p1, reg1, resolved = fx.setup_capacity_one_with_waitlist(num_waitlisted=2)
    p2, reg2, wl2 = resolved[0]
    p3, reg3, wl3 = resolved[1]
    fx.api_cancel(reg1, p1)  # P2 -> OFFERED
    # Advance the clock ~49h past P2's 24h offer window, then sweep.
    fx.set_clock("2026-06-11T01:00:00Z")
    resp = api.expire_check_waitlist_entry(wl2["id"], TEST_USERS["race_director_headers"])
    expired = validate_success(resp)
    assert expired["status"] == "EXPIRED", f"expected EXPIRED, got {expired['status']}"
    wl3_after = fx.get_waitlist_entry_data(wl3["id"])
    assert wl3_after["status"] == "OFFERED", \
        f"next queued entry must be promoted to OFFERED, got {wl3_after['status']}"
