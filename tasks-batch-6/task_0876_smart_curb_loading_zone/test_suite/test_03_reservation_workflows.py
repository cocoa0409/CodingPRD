"""Reservation workflows: parallel axes, permit/zone gates, capacity, half-open overlap.

Covers difficulty queue A: non_linear_state_machine (parallel booking/payment axes),
cross_entity_state_dependency (confirm requires permit active),
priority_pair_validation_conflict (permit-inactive beats capacity),
resource_temporal_overlap (half-open capacity). Plus corner cases: idempotent confirm,
fulfill without session, cancel-after-start, non-owner confirm, create validations.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_permittee_headers,
    advance_clock,
    make_policy,
    make_zone,
    make_permittee,
    make_permit,
    submit_permit,
    review_permit,
    approve_permit,
    activate_permit,
    make_reservation,
    confirm_reservation,
    make_confirmed_reservation,
    setup_active_permit,
    fetch_ledger_entries,
    ledger_entries_of_type,
    create_reservation_payload,
)


class TestParallelBookingAndPayment:
    """booking_status and payment_status evolve on separate enums on the same row."""

    def test_confirm_sets_confirmed_and_captured(self, api):
        """PRD §3.4: "On success the reservation moves from PENDING to CONFIRMED, an
        estimated price is computed and stamped into estimated_price_cents together with
        the surge_ratio_bps used to derive it, the payment_status moves from UNPAID to
        CAPTURED, a ledger CHARGE entry equal to the positive estimated price ... is
        appended, and the reservation's version increments by one."

        Design: Difficulty/non_linear_state_machine/reservation_parallel_booking_payment
        """
        ctx = setup_active_permit(api)
        res = make_confirmed_reservation(
            api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        assert res["booking_status"] == "CONFIRMED"
        assert res["payment_status"] == "CAPTURED"
        assert res["estimated_price_cents"] == 900

    def test_cancel_moves_booking_and_payment_independently(self, api):
        """PRD §3.5: "A permitted cancellation of a confirmed reservation moves it to
        CANCELLED, moves payment_status from CAPTURED to REFUNDED, and appends a ledger
        REFUND entry equal to the negative of estimated_price_cents, so the reservation's
        ledger contribution nets back to zero."

        Design: Difficulty/non_linear_state_machine/reservation_parallel_booking_payment
        """
        ctx = setup_active_permit(api)  # clock 2026-05-20, before the window start
        res = make_confirmed_reservation(
            api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        cancelled = validate_success(
            api.cancel_reservation(res["id"], make_permittee_headers(ctx["permittee_id"])))
        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "REFUNDED"
        assert cancelled["estimated_price_cents"] == 900, "estimate stamped at confirm, unchanged by cancel"


class TestConfirmRequiresPermitActive:
    """A SUBMITTED (not ACTIVE) permit blocks confirm even when the zone is fine."""

    def _setup_submitted_permit_pending_reservation(self, api):
        advance_clock(api, "2026-05-20T00:00:00Z")
        policy = make_policy(api)
        zone = make_zone(api, policy["id"])
        permittee = make_permittee(api)
        permit = make_permit(api, permittee["id"], [zone["id"]])
        submit_permit(api, permit["id"], permittee["id"])  # SUBMITTED, never approved
        res = make_reservation(
            api, permit["id"], permittee["id"], zone["id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        return permittee["id"], res["id"]

    def test_confirm_rejected_when_permit_not_active(self, api):
        """PRD §3.4: "The acting permittee must own the reservation's authorizing permit;
        that permit must be ACTIVE (otherwise ERR_PERMIT_NOT_ACTIVE)".

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_permit_active
        """
        permittee_id, res_id = self._setup_submitted_permit_pending_reservation(api)
        resp = api.confirm_reservation(res_id, make_permittee_headers(permittee_id))
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

    def test_reservation_stays_pending_after_permit_gate(self, api):
        """PRD §3.4: "A new reservation opens with booking_status of PENDING,
        payment_status of UNPAID, and version 1".

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_permit_active
        """
        permittee_id, res_id = self._setup_submitted_permit_pending_reservation(api)
        api.confirm_reservation(res_id, make_permittee_headers(permittee_id))
        fetched = validate_success(api.get_reservation(res_id, make_permittee_headers(permittee_id)))
        assert fetched["booking_status"] == "PENDING"


class TestPermitInactiveBeatsCapacity:
    """Referential gate (permit not ACTIVE, priority 6) precedes capacity (priority 7)."""

    def _setup_cap1_full_and_submitted_permit_b(self, api):
        advance_clock(api, "2026-05-20T00:00:00Z")
        policy = make_policy(api)
        zone = make_zone(api, policy["id"], name="Z3", block_face="ELM-300",
                         length_meters=6, capacity_slots=1)
        permittee = make_permittee(api)
        # Permit A: ACTIVE, its reservation RA fills the cap-1 zone.
        permit_a = make_permit(api, permittee["id"], [zone["id"]], purpose="A")
        activate_permit(api, permit_a["id"], permittee["id"])
        make_confirmed_reservation(
            api, permit_a["id"], permittee["id"], zone["id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        # Permit B: only SUBMITTED; its reservation RB overlaps RA.
        permit_b = make_permit(api, permittee["id"], [zone["id"]], purpose="B")
        submit_permit(api, permit_b["id"], permittee["id"])
        rb = make_reservation(
            api, permit_b["id"], permittee["id"], zone["id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        return permittee["id"], rb["id"]

    def test_permit_not_active_wins_over_capacity_conflict(self, api):
        """PRD §2.9: "then cross-entity state gates such as zones-active and permit-active
        (ERR_ZONE_NOT_ACTIVE and ERR_PERMIT_NOT_ACTIVE), then temporal-overlap conflicts
        such as zone-capacity and exclusive-window collisions (ERR_ZONE_CAPACITY_CONFLICT
        and ERR_SCHEDULE_WINDOW_CONFLICT)".

        Design: Difficulty/priority_pair_validation_conflict/confirm_permit_inactive_beats_capacity
        """
        permittee_id, rb_id = self._setup_cap1_full_and_submitted_permit_b(api)
        resp = api.confirm_reservation(rb_id, make_permittee_headers(permittee_id))
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

    def test_rb_unchanged_after_referential_gate(self, api):
        """PRD §3.4: "if that count is already at or above the zone's capacity_slots, the
        confirmation is refused with ERR_ZONE_CAPACITY_CONFLICT."

        Design: Difficulty/priority_pair_validation_conflict/confirm_permit_inactive_beats_capacity
        """
        permittee_id, rb_id = self._setup_cap1_full_and_submitted_permit_b(api)
        api.confirm_reservation(rb_id, make_permittee_headers(permittee_id))
        fetched = validate_success(api.get_reservation(rb_id, make_permittee_headers(permittee_id)))
        assert fetched["booking_status"] == "PENDING"


class TestHalfOpenCapacityOverlap:
    """Half-open [start,end): adjacent does not overlap; genuine overlap conflicts."""

    def _setup_cap1_with_ra_and_rc(self, api):
        advance_clock(api, "2026-05-20T00:00:00Z")
        policy = make_policy(api)
        zone = make_zone(api, policy["id"], name="Z3", block_face="ELM-300",
                         length_meters=6, capacity_slots=1)
        permittee = make_permittee(api)
        permit = make_permit(api, permittee["id"], [zone["id"]])
        activate_permit(api, permit["id"], permittee["id"])
        ra = make_confirmed_reservation(
            api, permit["id"], permittee["id"], zone["id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        # RC starts exactly at RA's end -> adjacent, not overlapping.
        rc = make_reservation(
            api, permit["id"], permittee["id"], zone["id"],
            "2026-06-01T08:45:00Z", "2026-06-01T09:15:00Z")
        rc = confirm_reservation(api, rc["id"], permittee["id"])
        # RB genuinely overlaps RA (and RC).
        rb = make_reservation(
            api, permit["id"], permittee["id"], zone["id"],
            "2026-06-01T08:30:00Z", "2026-06-01T09:00:00Z")
        return permittee["id"], rc, rb["id"]

    def test_adjacent_reservation_confirmed_no_overlap(self, api):
        """PRD §3.4: "the window is treated as the half-open interval from start_utc up
        to but not including end_utc". PRD §3.4: "Capacity is judged by counting the
        CONFIRMED reservations on the zone whose half-open window overlaps this one".

        Design: Difficulty/resource_temporal_overlap/reservation_halfopen_capacity_overlap
        """
        _permittee_id, rc, _rb_id = self._setup_cap1_with_ra_and_rc(api)
        assert rc["booking_status"] == "CONFIRMED", "adjacent [08:45,09:15) does not overlap [08:00,08:45)"

    def test_genuine_overlap_rejected_on_cap1_zone(self, api):
        """PRD §3.4: "if that count is already at or above the zone's capacity_slots, the
        confirmation is refused with ERR_ZONE_CAPACITY_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/reservation_halfopen_capacity_overlap
        """
        permittee_id, _rc, rb_id = self._setup_cap1_with_ra_and_rc(api)
        resp = api.confirm_reservation(rb_id, make_permittee_headers(permittee_id))
        validate_error(resp, ApiErrorId.ERR_ZONE_CAPACITY_CONFLICT)


# --- Corner cases --------------------------------------------------------------

def test_confirm_already_confirmed_reservation_rejected(api):
    """PRD §3.5: "any of them attempted from a state where it is not defined yields
    ERR_INVALID_STATE."

    Design: Corner/state_machines/confirm_already_confirmed_idempotency
    """
    ctx = setup_active_permit(api)
    res = make_confirmed_reservation(
        api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
        "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
    resp = api.confirm_reservation(res["id"], make_permittee_headers(ctx["permittee_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    entries = fetch_ledger_entries(api, params={"reservation_id": res["id"]})
    assert len(ledger_entries_of_type(entries, "CHARGE")) == 1, "no second CHARGE from the rejected confirm"


def test_fulfill_without_occupancy_session_rejected(api):
    """PRD §3.5: "Fulfillment requires that a CLOSED occupancy session exists whose
    reservation_id matches this reservation; if none does, it is refused with
    ERR_NO_OCCUPANCY_SESSION."

    Design: Corner/state_machines/fulfill_without_occupancy_session
    """
    ctx = setup_active_permit(api)
    res = make_confirmed_reservation(
        api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
        "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
    resp = api.fulfill_reservation(res["id"], make_permittee_headers(ctx["permittee_id"]))
    validate_error(resp, ApiErrorId.ERR_NO_OCCUPANCY_SESSION)
    fetched = validate_success(api.get_reservation(res["id"], make_permittee_headers(ctx["permittee_id"])))
    assert fetched["booking_status"] == "CONFIRMED"


def test_cancel_confirmed_after_start_rejected(api):
    """PRD §3.5: "Cancelling a CONFIRMED reservation is permitted only while the logical
    clock is still before the reservation's start_utc; a cancellation attempted at or
    after the window has begun is refused with ERR_CANCEL_AFTER_START."

    Design: Corner/state_machines/cancel_confirmed_after_start_rejected
    """
    ctx = setup_active_permit(api)
    res = make_confirmed_reservation(
        api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
        "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
    advance_clock(api, "2026-06-01T08:30:00Z")  # after start
    resp = api.cancel_reservation(res["id"], make_permittee_headers(ctx["permittee_id"]))
    validate_error(resp, ApiErrorId.ERR_CANCEL_AFTER_START)
    fetched = validate_success(api.get_reservation(res["id"], make_permittee_headers(ctx["permittee_id"])))
    assert fetched["booking_status"] == "CONFIRMED"
    assert fetched["payment_status"] == "CAPTURED"


def test_non_owner_permittee_cannot_confirm_reservation(api):
    """PRD §2.1: "ownership checks on any resource that references a Permittee compare
    that resource's owning permittee to X-User-ID. A permittee may create and drive its
    own permits, schedule windows, and reservations ... but may not act on resources
    owned by another permittee."

    Design: Corner/rbac/permittee_cannot_confirm_others_reservation
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    zone = make_zone(api, policy["id"])
    pm_a = make_permittee(api, legal_name="Acme A")
    pm_b = make_permittee(api, legal_name="Beta B", contact_email="b@x.com")
    permit = make_permit(api, pm_a["id"], [zone["id"]])
    activate_permit(api, permit["id"], pm_a["id"])
    res = make_reservation(api, permit["id"], pm_a["id"], zone["id"],
                           "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
    resp = api.confirm_reservation(res["id"], make_permittee_headers(pm_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    fetched = validate_success(api.get_reservation(res["id"], make_permittee_headers(pm_a["id"])))
    assert fetched["booking_status"] == "PENDING"


def test_reservation_create_end_not_after_start_rejected(api):
    """PRD §3.4: "end_utc must be strictly after start_utc". PRD §2.9: "an end instant
    not strictly after a start ... are reported as ERR_VALIDATION (HTTP 422)."

    Design: Corner/endpoints/reservation_create_end_before_start_validation
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    zone = make_zone(api, policy["id"])
    permittee = make_permittee(api)
    permit = make_permit(api, permittee["id"], [zone["id"]])
    resp = api.create_reservation(
        create_reservation_payload(permit["id"], zone["id"],
                                   "2026-06-01T09:00:00Z", "2026-06-01T08:00:00Z"),
        make_permittee_headers(permittee["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_reservation_create_unknown_zone_returns_not_found(api):
    """PRD §2.5: "The server resolves them left to right, path identifier first and then
    body references in the order they appear, and rejects the request with ERR_NOT_FOUND
    (HTTP 404) at the first identifier that does not resolve to an existing resource."

    Design: Corner/entities/reservation_create_unknown_zone_fk
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    zone = make_zone(api, policy["id"])
    permittee = make_permittee(api)
    permit = make_permit(api, permittee["id"], [zone["id"]])
    resp = api.create_reservation(
        create_reservation_payload(permit["id"], "11111111-1111-4111-8111-111111111111",
                                   "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z"),
        make_permittee_headers(permittee["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
