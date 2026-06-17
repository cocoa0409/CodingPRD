"""Booth/attendant selection, overlap-driven unavailability, optimistic concurrency,
priority precedence at confirm, and capacity conservation under cancel.

Tests here use only directly-overlapping event windows (cores overlap regardless of the
SETUP/TEARDOWN/TURNAROUND buffer magnitudes, which the PRD names symbolically without
pinning numeric values). Buffer-edge geometry instances are not asserted — see the
generation summary for the skipped buffer-boundary instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, make_customer_headers, TEST_USERS,
    seed_base_scenario, seed_model_and_package, create_customer, create_booth,
    create_attendant, create_add_on, create_booking, add_add_on_line,
    pay_deposit, confirm_booking, cancel_confirmed_booking,
    create_payment_payload,
)

OPS = TEST_USERS["operations_manager_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Optimistic concurrency (Queue B cross_cutting) ────────────────────

def test_confirm_with_stale_booth_version_rejected(api):
    """PRD §2.7: "That request must carry `expected_booth_version`, which must equal the
    chosen booth's current `version`. If the booth's `version` has advanced since the
    client last read it ... the confirm is rejected as stale with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/confirm_stale_booth_version_conflict
    """
    sc = seed_base_scenario()
    booth = sc["booth"]
    stale_version = booth["version"]  # version captured at creation
    booking = create_booking(
        sc["customer"]["id"], sc["package"]["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=0)
    pay_deposit(booking["id"])
    # Two PATCHes advance the booth version past the stale value.
    api.update_booth(booth["id"], {"status": "MAINTENANCE"}, OPS)
    api.update_booth(booth["id"], {"status": "AVAILABLE"}, OPS)
    res = api.confirm_booking(booking["id"], {"expected_booth_version": stale_version}, OPS)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
    after = get_success_data(api.get_booking(booking["id"], OPS))
    assert after["schedule_status"] == "DRAFT"


def test_finalize_with_stale_eventlog_version_rejected(api):
    """PRD §2.7: "Finalizing an event log requires `expected_eventlog_version`, which
    must equal that event log's current `version`. If the event log's `version` has
    advanced since the client last observed it — because an actuals correction was
    applied in between, bumping the event log's `version` — the finalize is rejected as
    stale with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/finalize_stale_eventlog_version_conflict
    """
    from test_helpers import create_in_service_booking
    built = create_in_service_booking()
    log = built["event_log"]
    stale_version = log["version"]
    # A PATCH correction bumps the event log version.
    api.update_event_log(log["id"], {"actual_print_count": 250}, OPS)
    payload = {
        "actual_setup_start": "2026-09-12T18:00:00Z",
        "actual_coverage_start": "2026-09-12T18:00:00Z",
        "actual_coverage_end": "2026-09-12T22:00:00Z",
        "actual_teardown_end": "2026-09-12T22:30:00Z",
        "actual_print_count": 250,
        "expected_eventlog_version": stale_version,
    }
    res = api.finalize_event_log(log["id"], payload, OPS)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
    after = get_success_data(api.get_event_log(log["id"], OPS))
    assert after["finalized"] is False


# ─── Helpers for two-booking overlap scenarios ─────────────────────────

def _two_overlapping_bookings(api, num_booths=1, with_attendant=False, num_attendants=0):
    """Seed model + package + N booths + (optional) attendants + one customer, then two
    bookings on directly overlapping windows (18:00-22:00 and 19:00-23:00).
    Returns dict with all created entities."""
    api.set_clock({"to_iso8601": "2026-06-14T00:00:00Z"}, ADMIN)
    model, package = seed_model_and_package(package_overrides={"name": "Basic 4hr"})
    booths = [create_booth(model["id"], f"BTH-{i+1:03d}") for i in range(num_booths)]
    attendants = [create_attendant(f"Att {i}") for i in range(num_attendants)]
    att_addon = None
    if with_attendant:
        att_addon = create_add_on(code="ATTENDANT", name="Staff Attendant",
                                  unit_price=200.00, requires_attendant=True)
    customer = create_customer()

    def _booking(start, end):
        bk = create_booking(customer["id"], package["id"],
                            event_start=start, event_end=end, venue_distance_miles=0)
        if with_attendant:
            add_add_on_line(bk["id"], customer["id"], att_addon["id"], 1)
        pay_deposit(bk["id"])
        return get_success_data(api.get_booking(bk["id"], OPS))

    bk1 = _booking("2026-09-12T18:00:00Z", "2026-09-12T22:00:00Z")
    bk2 = _booking("2026-09-12T19:00:00Z", "2026-09-12T23:00:00Z")
    return {"model": model, "package": package, "booths": booths,
            "attendants": attendants, "customer": customer, "bk1": bk1, "bk2": bk2}


# ─── Priority precedence at confirm (Difficulty Rule 5) ────────────────

class TestConfirmPriorityPrecedence:

    def test_temporal_beats_fiscal_no_booth_available(self, api):
        """PRD §3.4: "If no candidate survives, confirmation is rejected with
        `ERR_NO_BOOTH_AVAILABLE`."
        PRD §2.9: "then the temporal and selection checks at confirmation
        (`ERR_BOOTH_INTERVAL_CONFLICT`, `ERR_NO_BOOTH_AVAILABLE`,
        `ERR_ATTENDANT_INTERVAL_CONFLICT`, `ERR_NO_ATTENDANT_AVAILABLE`); and finally the
        fiscal exact-amount checks (`ERR_DEPOSIT_AMOUNT_MISMATCH`,
        `ERR_BALANCE_AMOUNT_MISMATCH`, `ERR_REFUND_AMOUNT_MISMATCH`)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_no_booth_vs_deposit_on_confirm
        """
        s = _two_overlapping_bookings(api, num_booths=1)
        booth = s["booths"][0]
        confirm_booking(s["bk1"]["id"], booth["id"])  # B1 claims the only booth
        booth_v = get_success_data(api.get_booth(booth["id"], OPS))["version"]
        res = api.confirm_booking(s["bk2"]["id"], {"expected_booth_version": booth_v}, OPS)
        validate_error(res, ApiErrorId.ERR_NO_BOOTH_AVAILABLE.value)
        after = get_success_data(api.get_booking(s["bk2"]["id"], OPS))
        assert after["schedule_status"] == "DRAFT"

    def test_first_booking_holds_the_only_booth(self, api):
        """PRD §3.4: "The first booth in that ordering is chosen, its `id` written to the
        booking's `booth_id`, and its interval claimed (which bumps that booth's
        `version`)."
        PRD §3.4: "If no candidate survives, confirmation is rejected with
        `ERR_NO_BOOTH_AVAILABLE`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_no_booth_vs_deposit_on_confirm
        """
        s = _two_overlapping_bookings(api, num_booths=1)
        booth = s["booths"][0]
        bk1_confirmed = confirm_booking(s["bk1"]["id"], booth["id"])
        # The single booth is genuinely held by B1, so the overlapping B2 has no booth.
        assert bk1_confirmed["booth_id"] == booth["id"]
        booth_v = get_success_data(api.get_booth(booth["id"], OPS))["version"]
        res = api.confirm_booking(s["bk2"]["id"], {"expected_booth_version": booth_v}, OPS)
        validate_error(res, ApiErrorId.ERR_NO_BOOTH_AVAILABLE.value)

    def test_state_beats_fiscal_on_balance_payment(self, api):
        """PRD §3.6: "A `BALANCE` payment moves the booking from `DEPOSIT_PAID` to
        `PAID_IN_FULL`. It is allowed only when `payment_status` is `DEPOSIT_PAID`."
        PRD §2.9: "then state-machine preconditions (`ERR_INVALID_STATE`, and the
        draft-lock guard `ERR_BOOKING_LOCKED`); then the optimistic-concurrency version
        check ... and finally the fiscal exact-amount checks
        (`ERR_DEPOSIT_AMOUNT_MISMATCH`, `ERR_BALANCE_AMOUNT_MISMATCH`,
        `ERR_REFUND_AMOUNT_MISMATCH`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_balance_payment
        """
        model, package = seed_model_and_package(package_overrides={"name": "Basic 4hr"})
        customer = create_customer()
        booking = create_booking(
            customer["id"], package["id"],
            event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
            venue_distance_miles=0)
        # DRAFT/UNPAID booking: a BALANCE with a wrong amount must fail on STATE, not fiscal.
        res = api.create_payment(booking["id"], create_payment_payload("BALANCE", 9999.99), FINANCE)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_check_leaves_unpaid_booking_unpaid(self, api):
        """PRD §3.6: "Any payment action attempted against a booking that is not in the
        right payment state for that transition is rejected with `ERR_INVALID_STATE`."
        PRD §3.6: "A `BALANCE` payment moves the booking from `DEPOSIT_PAID` to
        `PAID_IN_FULL`. It is allowed only when `payment_status` is `DEPOSIT_PAID`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_balance_payment
        """
        model, package = seed_model_and_package(package_overrides={"name": "Basic 4hr"})
        customer = create_customer()
        booking = create_booking(
            customer["id"], package["id"],
            event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
            venue_distance_miles=0)
        res = api.create_payment(booking["id"], create_payment_payload("BALANCE", 9999.99), FINANCE)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
        after = get_success_data(api.get_booking(booking["id"], OPS))
        # The fiscal path never ran; payment_status is untouched.
        assert after["payment_status"] == "UNPAID"


# ─── Cancel cascade releases attendant, unblocks overlapping confirm ───

class TestCancelReleasesAttendant:
    """Difficulty Rule 4: cancelling a CONFIRMED attendant-staffed booking releases the
    attendant, lifting the conflict gate that blocked an overlapping booking."""

    def test_cancel_releases_attendant_assignment(self, api):
        """PRD §3.7: "Cancelling a `CONFIRMED` booking releases the held booth — clearing
        its interval claim — and, if one is present, releases the attendant assignment
        (moving its `status` from `ACTIVE` to `RELEASED`)."

        Design: Difficulty/transitive_cascade/cancel_confirmed_cascade_releases_attendant_unblocks_other
        """
        s = _two_overlapping_bookings(api, num_booths=2, with_attendant=True, num_attendants=1)
        confirm_booking(s["bk1"]["id"], s["booths"][0]["id"])
        cancel_confirmed_booking(s["bk1"]["id"], s["customer"]["id"])
        assignments = get_success_data(
            api.list_booking_attendant_assignments(s["bk1"]["id"], OPS))
        assert len(assignments) == 1
        assert assignments[0]["status"] == "RELEASED"

    def test_overlapping_booking_confirms_after_release(self, api):
        """PRD §3.7: "Releasing the attendant frees its interval, which in turn lifts the
        attendant-conflict gate that had been blocking any overlapping `DRAFT` booking
        from confirming on that attendant."

        Design: Difficulty/transitive_cascade/cancel_confirmed_cascade_releases_attendant_unblocks_other
        """
        s = _two_overlapping_bookings(api, num_booths=2, with_attendant=True, num_attendants=1)
        confirm_booking(s["bk1"]["id"], s["booths"][0]["id"])
        cancel_confirmed_booking(s["bk1"]["id"], s["customer"]["id"])
        # The released attendant + the second free booth let B2 confirm.
        booth2_v = get_success_data(api.get_booth(s["booths"][1]["id"], OPS))["version"]
        confirmed = validate_success(
            api.confirm_booking(s["bk2"]["id"], {"expected_booth_version": booth2_v}, OPS), 200)
        assert confirmed["schedule_status"] == "CONFIRMED"


# ─── Booth interval-capacity conservation (Difficulty Rule 9) ──────────

class TestBoothCapacityConservation:
    """Difficulty Rule 9: confirming claims one booth slot; cancelling releases exactly
    that slot so a second overlapping booking can confirm on the same booth."""

    def test_cancel_confirmed_frees_the_slot(self, api):
        """PRD §3.7: "Cancelling a `CONFIRMED` booking releases the held booth — clearing
        its interval claim."

        Design: Difficulty/compensating_invariant/cancel_confirmed_booth_capacity_conservation
        """
        s = _two_overlapping_bookings(api, num_booths=1)
        confirm_booking(s["bk1"]["id"], s["booths"][0]["id"])
        cancelled = cancel_confirmed_booking(s["bk1"]["id"], s["customer"]["id"])
        assert cancelled["schedule_status"] == "CANCELLED"

    def test_second_booking_confirms_on_freed_booth(self, api):
        """PRD §3.4: "The booth selector considers only booths whose `booth_model_id`
        matches the booking's package's model, whose `status` is `AVAILABLE`, and that
        survive the booth-overlap filter against the new booking's booth-occupied
        interval (the half-open interval of §2.6)."
        PRD §3.7: "Cancelling a `CONFIRMED` booking releases the held booth — clearing its
        interval claim."

        Design: Difficulty/compensating_invariant/cancel_confirmed_booth_capacity_conservation
        """
        s = _two_overlapping_bookings(api, num_booths=1)
        bk1_confirmed = confirm_booking(s["bk1"]["id"], s["booths"][0]["id"])
        cancel_confirmed_booking(s["bk1"]["id"], s["customer"]["id"])
        booth_v = get_success_data(api.get_booth(s["booths"][0]["id"], OPS))["version"]
        bk2_confirmed = validate_success(
            api.confirm_booking(s["bk2"]["id"], {"expected_booth_version": booth_v}, OPS), 200)
        assert bk2_confirmed["schedule_status"] == "CONFIRMED"
        assert bk2_confirmed["booth_id"] == bk1_confirmed["booth_id"]
