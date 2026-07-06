"""Event cancellation cascades, the safety-over-fiscal book precedence, cancellation
fees, the COI clock sweep, and event-completion gates.

Covers queue A transitive_cascade (depth-3 event cancel) and priority_pair (COI
beats budget) plus queue B cancellation-fee / clock-sweep / completion corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    PLANNER,
    create_event,
    create_contract,
    create_vendor,
    create_verified_vendor,
    create_pending_vendor,
    create_booking,
    book_booking,
    setup_event_in_booking,
    list_booking_payments,
    get_event,
    set_clock,
)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------
def _setup_booking_for_cascade():
    """Event in BOOKING (budget 10M) with a BOOKED booking (2M) and its two SCHEDULED
    payments. Returns (event, contract, booking)."""
    event, contract = setup_event_in_booking(total_budget_cents=10_000_000)
    vendor, _coi = create_verified_vendor(category="PHOTO")
    booking = create_booking(event["id"], vendor["id"], estimated_cost_cents=1_800_000)
    booking = book_booking(booking["id"], 2_000_000)
    return event, contract, booking


def _setup_coi_and_budget_conflict():
    """Event in BOOKING with only a 1,000,000 budget; a vendor whose COI is still
    PENDING; one PROPOSED booking. Returns (event, booking)."""
    event, _contract = setup_event_in_booking(total_budget_cents=1_000_000)
    vendor, _coi = create_pending_vendor()
    booking = create_booking(event["id"], vendor["id"], estimated_cost_cents=500_000)
    return event, booking


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade: event cancel -> booking cancel -> payment void
# ---------------------------------------------------------------------------
def test_event_cancel_cascades_booking_to_cancelled(api):
    """PRD §3.8: "Third, every vendor booking of the event that is still `PROPOSED` or
    `BOOKED` is cancelled as a cascade, and each such booking cancellation itself voids
    that booking's scheduled payments and restores the budget exactly as a direct booking
    cancellation would."

    Design: Difficulty/transitive_cascade/event_cancel_cascade_booking_payment_depth3
    """
    event, _contract, booking = _setup_booking_for_cascade()
    data = validate_success(api.cancel_event(event["id"], PLANNER))
    assert data["status"] == "CANCELLED"
    booking_after = validate_success(api.get_vendor_booking(booking["id"], PLANNER))
    assert booking_after["status"] == "CANCELLED"


def test_event_cancel_voids_payments_and_restores_budget(api):
    """PRD §3.8: "Third, every vendor booking of the event that is still `PROPOSED` or
    `BOOKED` is cancelled as a cascade, and each such booking cancellation itself voids
    that booking's scheduled payments and restores the budget exactly as a direct booking
    cancellation would."
    PRD §3.8: "Second, if the event has an active contract that is not already `VOID`,
    that contract is transitioned to `VOID`."

    Depth-3: the booking's SCHEDULED payments are VOIDed (caused by the booking
    cancellation, not directly by the event), committed spend is restored, and the active
    contract is voided.

    Design: Difficulty/transitive_cascade/event_cancel_cascade_booking_payment_depth3
    """
    event, contract, booking = _setup_booking_for_cascade()
    validate_success(api.cancel_event(event["id"], PLANNER))
    payments = list_booking_payments(booking["id"])
    assert len(payments) == 2
    assert all(p["status"] == "VOID" for p in payments), "both scheduled payments must be VOIDed"
    contract_after = validate_success(api.get_contract(contract["id"], PLANNER))
    assert contract_after["status"] == "VOID"
    assert get_event(event["id"])["committed_spend_cents"] == 0


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict: COI safety beats budget fiscal
# ---------------------------------------------------------------------------
def test_book_unverified_and_over_budget_returns_coi_not_verified(api):
    """PRD §3.3: "Booking is guarded by several conditions evaluated in a fixed order:
    the booking must be in `PROPOSED` (otherwise `ERR_BOOKING_NOT_PROPOSED`) and its
    parent event must be in `BOOKING` (otherwise `ERR_EVENT_NOT_BOOKING`); then the
    referenced vendor must have a `VERIFIED` COI whose `coverage_expiry_date` is on or
    after the event's `event_date` (otherwise `ERR_COI_NOT_VERIFIED`); and finally,
    checked last, the fiscal guard must hold — the event's `committed_spend_cents` plus
    the new `contracted_cost_cents` must not exceed `total_budget_cents`, otherwise the
    booking is rejected with `ERR_BUDGET_EXCEEDED`."

    Booking 5,000,000 against a 1,000,000 budget with an unverified COI: the COI check
    (earlier) wins over the fiscal check (checked last).

    Design: Difficulty/priority_pair_validation_conflict/book_coi_not_verified_beats_budget
    """
    event, booking = _setup_coi_and_budget_conflict()
    validate_error(
        api.book_vendor_booking(booking["id"], {"contracted_cost_cents": 5_000_000}, PLANNER),
        ApiErrorId.ERR_COI_NOT_VERIFIED.value,
    )


def test_coi_check_precedes_budget_check(api):
    """PRD §3.3: "Booking is guarded by several conditions evaluated in a fixed order:
    the booking must be in `PROPOSED` (otherwise `ERR_BOOKING_NOT_PROPOSED`) and its
    parent event must be in `BOOKING` (otherwise `ERR_EVENT_NOT_BOOKING`); then the
    referenced vendor must have a `VERIFIED` COI whose `coverage_expiry_date` is on or
    after the event's `event_date` (otherwise `ERR_COI_NOT_VERIFIED`); and finally,
    checked last, the fiscal guard must hold — the event's `committed_spend_cents` plus
    the new `contracted_cost_cents` must not exceed `total_budget_cents`, otherwise the
    booking is rejected with `ERR_BUDGET_EXCEEDED`."

    The rejection is the 403 ERR_COI_NOT_VERIFIED (safety), not ERR_BUDGET_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/book_coi_not_verified_beats_budget
    """
    event, booking = _setup_coi_and_budget_conflict()
    resp = api.book_vendor_booking(booking["id"], {"contracted_cost_cents": 5_000_000}, PLANNER)
    err = validate_error(resp, ApiErrorId.ERR_COI_NOT_VERIFIED.value)
    assert resp.status_code == 403
    assert err["error_id"] == "ERR_COI_NOT_VERIFIED"


# ---------------------------------------------------------------------------
# Queue B — cancellation-fee tiers
# ---------------------------------------------------------------------------
def test_cancellation_fee_far_tier_25pct(api):
    """PRD §3.8: "If at least 90 days remain, the rate is 25 percent; if fewer than 90
    but at least 30 days remain, the rate is 50 percent; if fewer than 30 days remain, the
    rate is 100 percent. The `cancellation_fee_cents` is that rate applied to the active
    contract's `planner_fee_cents`, rounded half up to whole cents."

    Clock 2026-03-01 to event 2026-09-15 is 198 days (>= 90 -> 25%): 0.25 * 2,300,000 =
    575,000.

    Design: Corner/calculations/cancellation_fee_far_tier_25pct
    """
    event = create_event(package_type="FULL", total_budget_cents=10_000_000, guest_count_estimate=100)
    contract = create_contract(event["id"], event["version"])
    data = validate_success(api.cancel_event(event["id"], PLANNER))
    assert data["cancellation_fee_cents"] == 575_000
    assert data["status"] == "CANCELLED"
    contract_after = validate_success(api.get_contract(contract["id"], PLANNER))
    assert contract_after["status"] == "VOID"


def test_cancellation_fee_imminent_tier_100pct(api):
    """PRD §3.8: "If at least 90 days remain, the rate is 25 percent; if fewer than 90
    but at least 30 days remain, the rate is 50 percent; if fewer than 30 days remain, the
    rate is 100 percent. The `cancellation_fee_cents` is that rate applied to the active
    contract's `planner_fee_cents`, rounded half up to whole cents."

    Clock advanced to 2026-09-01 leaves 14 days (< 30 -> 100%): the fee equals the full
    planner fee 2,300,000.

    Design: Corner/calculations/cancellation_fee_imminent_tier_100pct
    """
    event = create_event(package_type="FULL", total_budget_cents=10_000_000, guest_count_estimate=100)
    create_contract(event["id"], event["version"])
    set_clock("2026-09-01T00:00:00Z")
    data = validate_success(api.cancel_event(event["id"], PLANNER))
    assert data["cancellation_fee_cents"] == 2_300_000


# ---------------------------------------------------------------------------
# Queue B — COI clock sweep
# ---------------------------------------------------------------------------
def test_coi_clock_sweep_expires_verified_coi(api):
    """PRD §2.6: "Any COI whose `coverage_expiry_date` is at or before the new clock
    value transitions to `EXPIRED`, regardless of whether it was previously `PENDING` or
    `VERIFIED`."

    Design: Corner/cross_cutting_complexity_layers/coi_clock_sweep_expires_verified_coi
    """
    _vendor, coi = create_verified_vendor(coverage_expiry_date="2026-06-01T00:00:00Z", category="RENTAL")
    set_clock("2026-07-01T00:00:00Z")
    coi_after = validate_success(api.get_coi(coi["id"], PLANNER))
    assert coi_after["status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Queue B — event completion / cancellation gates
# ---------------------------------------------------------------------------
def test_complete_event_not_booking_rejected(api):
    """PRD §3.8: "Completion requires the event to be in `BOOKING` (otherwise
    `ERR_EVENT_NOT_BOOKING`), requires the current logical clock to have reached or passed
    the `event_date` (otherwise `ERR_EVENT_DATE_NOT_REACHED`), and requires that no vendor
    booking for the event is still `PROPOSED` — every engagement must be resolved to booked
    or cancelled first, otherwise the completion is rejected with `ERR_UNRESOLVED_BOOKINGS`."

    A fresh DRAFT event is not in BOOKING.

    Design: Corner/state_machines/complete_event_not_booking_returns_conflict
    """
    event = create_event(package_type="FULL", total_budget_cents=8_000_000)
    validate_error(api.complete_event(event["id"], PLANNER), ApiErrorId.ERR_EVENT_NOT_BOOKING.value)


def test_complete_before_event_date_rejected(api):
    """PRD §3.8: "Completion requires the event to be in `BOOKING` (otherwise
    `ERR_EVENT_NOT_BOOKING`), requires the current logical clock to have reached or passed
    the `event_date` (otherwise `ERR_EVENT_DATE_NOT_REACHED`), and requires that no vendor
    booking for the event is still `PROPOSED` — every engagement must be resolved to booked
    or cancelled first, otherwise the completion is rejected with `ERR_UNRESOLVED_BOOKINGS`."

    The clock is left at the startup default 2026-03-01, before the 2026-09-15 event date.

    Design: Corner/state_machines/complete_before_event_date_returns_conflict
    """
    event, _contract = setup_event_in_booking(total_budget_cents=8_000_000)
    validate_error(api.complete_event(event["id"], PLANNER), ApiErrorId.ERR_EVENT_DATE_NOT_REACHED.value)


def test_complete_with_proposed_booking_rejected(api):
    """PRD §3.8: "Completion requires the event to be in `BOOKING` (otherwise
    `ERR_EVENT_NOT_BOOKING`), requires the current logical clock to have reached or passed
    the `event_date` (otherwise `ERR_EVENT_DATE_NOT_REACHED`), and requires that no vendor
    booking for the event is still `PROPOSED` — every engagement must be resolved to booked
    or cancelled first, otherwise the completion is rejected with `ERR_UNRESOLVED_BOOKINGS`."

    The clock is advanced past the event date, but one booking is still PROPOSED.

    Design: Corner/state_machines/complete_with_proposed_booking_returns_unresolved
    """
    event, _contract = setup_event_in_booking(total_budget_cents=8_000_000)
    vendor = create_vendor(category="OTHER")
    create_booking(event["id"], vendor["id"], estimated_cost_cents=500_000)  # stays PROPOSED
    set_clock("2026-09-16T00:00:00Z")
    validate_error(api.complete_event(event["id"], PLANNER), ApiErrorId.ERR_UNRESOLVED_BOOKINGS.value)


def test_cancel_already_cancelled_event_rejected(api):
    """PRD §3.8: "The `Planner` may cancel an event that is in `DRAFT` or `BOOKING`; any
    other state yields `ERR_EVENT_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_already_cancelled_event_returns_not_cancellable
    """
    event = create_event(package_type="DAY_OF", total_budget_cents=2_000_000)
    validate_success(api.cancel_event(event["id"], PLANNER))
    validate_error(api.cancel_event(event["id"], PLANNER), ApiErrorId.ERR_EVENT_NOT_CANCELLABLE.value)
