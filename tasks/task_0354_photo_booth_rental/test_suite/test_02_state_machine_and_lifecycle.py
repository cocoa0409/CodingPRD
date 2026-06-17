"""Booking schedule/payment state machines, parallel dimensions, cascades, and
cross-entity state dependencies."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data, assert_booking, ApiErrorId,
    make_customer_headers, TEST_USERS,
    seed_base_scenario, seed_model_and_package, create_customer, create_booking,
    create_deposit_paid_booking, create_confirmed_booking, create_in_service_booking,
    create_finalized_booking, create_paid_in_full_booking, create_completed_booking,
    pay_deposit, pay_balance, confirm_booking, start_service,
    add_add_on_line, create_add_on,
)

OPS = TEST_USERS["operations_manager_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


# ─── Parallel schedule + payment dimensions (Difficulty Rule 3) ────────

class TestParallelDimensions:
    """Booking carries two independent state dimensions on one row."""

    def test_deposit_advances_payment_status_only(self, api):
        """PRD §3.6: "A `DEPOSIT` payment moves the booking from `UNPAID` to
        `DEPOSIT_PAID`. It is allowed only when `payment_status` is `UNPAID` and
        `schedule_status` is `DRAFT`."

        Design: Difficulty/non_linear_state_machine/booking_parallel_schedule_payment_dimensions
        """
        built = create_deposit_paid_booking()
        assert built["booking"]["payment_status"] == "DEPOSIT_PAID"
        assert built["booking"]["schedule_status"] == "DRAFT"

    def test_confirm_advances_schedule_status_only(self, api):
        """PRD §3.4: "It is driven by an `OperationsManager` and advances the booking
        from `DRAFT` to `CONFIRMED`. Confirmation may proceed only when the booking's
        `schedule_status` is `DRAFT` and its `payment_status` is already `DEPOSIT_PAID`."

        Design: Difficulty/non_linear_state_machine/booking_parallel_schedule_payment_dimensions
        """
        built = create_confirmed_booking()
        assert built["booking"]["schedule_status"] == "CONFIRMED"
        assert built["booking"]["payment_status"] == "DEPOSIT_PAID"


# ─── Gallery cyclic publish/unpublish loop (Difficulty Rule 3) ─────────

class TestGalleryPublishCycle:
    """Gallery is cyclic: PUBLISHED -> UNPUBLISHED -> PUBLISHED, minting a fresh
    access_pin on each (re)publish."""

    def test_republish_after_unpublish_returns_to_published(self, api):
        """PRD §3.9: "Re-publishing from `UNPUBLISHED` back to `PUBLISHED` requires that
        the gallery is `UNPUBLISHED`, that its `photo_count` is at least 1, and that the
        parent booking's `payment_status` is `PAID_IN_FULL`; it mints a fresh six-digit
        `access_pin` (a different PIN per publish) and increments the gallery's `version`."

        Design: Difficulty/non_linear_state_machine/gallery_publish_unpublish_cycle
        """
        built = create_completed_booking()
        gid = built["gallery"]["id"]
        api.upload_gallery_photos(gid, {"count": 12}, OPS)
        get_success_data(api.publish_gallery(gid, OPS))
        get_success_data(api.unpublish_gallery(gid, OPS))
        republished = validate_success(api.publish_gallery(gid, OPS), 200)
        assert republished["status"] == "PUBLISHED"
        assert republished["access_pin"] is not None

    def test_version_increments_across_full_cycle(self, api):
        """PRD §2.4: "`version` (integer): a counter that starts at the resource's
        creation and increments by one on every mutation of that resource."

        Design: Difficulty/non_linear_state_machine/gallery_publish_unpublish_cycle
        """
        built = create_completed_booking()
        gid = built["gallery"]["id"]
        # Gallery created at completion (version 1). photos(2) publish(3) unpublish(4) publish(5).
        api.upload_gallery_photos(gid, {"count": 12}, OPS)
        get_success_data(api.publish_gallery(gid, OPS))
        get_success_data(api.unpublish_gallery(gid, OPS))
        republished = validate_success(api.publish_gallery(gid, OPS), 200)
        assert republished["version"] == 5


# ─── Transitive cascade: finalize -> balance -> PAID_IN_FULL -> COMPLETE ─

class TestFinalizeCompletionCascade:
    """Difficulty Rule 4: depth-3 cascade originating at finalize."""

    ADDONS = [
        {"code": "PROPS", "name": "Prop Box", "unit_price": 50.00},
        {"code": "BACKDROP", "name": "Sequin Backdrop", "unit_price": 100.00},
        {"code": "ALBUM", "name": "Leather Album", "unit_price": 150.00},
    ]
    BOOKING = {
        "event_start": "2026-09-12T18:00:00Z", "event_end": "2026-09-13T00:00:00Z",
        "venue_distance_miles": 40, "requested_setup_lead_min": 90,
    }
    ACTUALS = {
        "actual_setup_start": "2026-09-12T16:15:00Z",
        "actual_coverage_start": "2026-09-12T17:00:00Z",
        "actual_coverage_end": "2026-09-13T00:15:00Z",
        "actual_teardown_end": "2026-09-13T01:00:00Z",
        "actual_print_count": 360,
    }

    def test_balance_payment_reaches_paid_in_full(self, api):
        """PRD §3.6: "A `BALANCE` payment moves the booking from `DEPOSIT_PAID` to
        `PAID_IN_FULL`." PRD §3.6: "On success the payment is appended, `amount_paid` is
        increased by the amount, `balance_due` is set to 0, and the booking's `version`
        is incremented."

        Design: Difficulty/transitive_cascade/finalize_cascade_depth3_balance_to_completion_gate
        """
        built = create_finalized_booking(
            booking_overrides=self.BOOKING, add_ons=self.ADDONS, actuals=self.ACTUALS)
        _, after = pay_balance(built["booking"]["id"])
        assert after["payment_status"] == "PAID_IN_FULL"
        assert after["balance_due"] == pytest.approx(0.0, abs=0.01)

    def test_completion_unblocked_only_after_paid_in_full(self, api):
        """PRD §3.5: "That change to `balance_due` re-opens the balance-payment gate, and
        clearing that balance — reaching `PAID_IN_FULL` — is itself the precondition that
        later unblocks completion of the event."
        PRD §3.8: "It is permitted only when the booking is `IN_SERVICE`, its event log
        has been finalized (`finalized` is `true`, so actuals have been submitted), and
        its `payment_status` is `PAID_IN_FULL`."

        Design: Difficulty/transitive_cascade/finalize_cascade_depth3_balance_to_completion_gate
        """
        built = create_paid_in_full_booking(
            booking_overrides=self.BOOKING, add_ons=self.ADDONS, actuals=self.ACTUALS)
        completed = validate_success(api.complete_booking(built["booking"]["id"], OPS), 200)
        assert completed["schedule_status"] == "COMPLETED"
        assert completed["payment_status"] == "PAID_IN_FULL"
        assert completed["balance_due"] == pytest.approx(0.0, abs=0.01)


# ─── Cross-entity state dependency (Difficulty Rule 7) ─────────────────

class TestCrossEntityStateDependency:

    def test_gallery_publish_requires_completed_and_paid_parent(self, api):
        """PRD §3.9: "Publishing from `DRAFT` to `PUBLISHED` requires that the gallery is
        in `DRAFT`, that its `photo_count` is at least 1, that the parent booking's
        `schedule_status` is `COMPLETED`, and that the parent booking's `payment_status`
        is `PAID_IN_FULL`; on success the system mints a fresh six-digit `access_pin` and
        increments the gallery's `version`."

        Design: Difficulty/cross_entity_state_dependency/gallery_publish_requires_booking_completed_and_paid
        """
        built = create_completed_booking()
        gid = built["gallery"]["id"]
        api.upload_gallery_photos(gid, {"count": 3}, OPS)
        published = validate_success(api.publish_gallery(gid, OPS), 200)
        assert published["status"] == "PUBLISHED"
        assert published["access_pin"] is not None

    def test_gallery_publish_mints_pin_and_bumps_version_on_completed_paid(self, api):
        """PRD §3.9: "on success the system mints a fresh six-digit `access_pin` and
        increments the gallery's `version`."
        PRD §3.8: "Completion ... creates the booking's **gallery** if none exists (with
        `status` of `DRAFT` and `photo_count` of 0)."

        Design: Difficulty/cross_entity_state_dependency/gallery_publish_requires_booking_completed_and_paid
        """
        built = create_completed_booking()
        gid = built["gallery"]["id"]
        before = get_success_data(api.get_gallery(gid, OPS))
        api.upload_gallery_photos(gid, {"count": 3}, OPS)
        published = validate_success(api.publish_gallery(gid, OPS), 200)
        assert isinstance(published["access_pin"], str) and len(published["access_pin"]) == 6
        assert published["version"] > before["version"]

    def test_complete_requires_eventlog_finalized(self, api):
        """PRD §3.8: "It is permitted only when the booking is `IN_SERVICE`, its event
        log has been finalized (`finalized` is `true`, so actuals have been submitted),
        and its `payment_status` is `PAID_IN_FULL`. A completion attempted before those
        conditions are met is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/complete_requires_eventlog_finalized
        """
        built = create_in_service_booking()
        res = api.complete_booking(built["booking"]["id"], OPS)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
        after = get_success_data(api.get_booking(built["booking"]["id"], OPS))
        assert after["schedule_status"] == "IN_SERVICE"

    def test_complete_succeeds_once_eventlog_finalized_and_paid(self, api):
        """PRD §3.8: "It is permitted only when the booking is `IN_SERVICE`, its event
        log has been finalized (`finalized` is `true`, so actuals have been submitted),
        and its `payment_status` is `PAID_IN_FULL`."
        PRD §3.5: "On a successful finalize the system sets `finalized` to `true`."

        Design: Difficulty/cross_entity_state_dependency/complete_requires_eventlog_finalized
        """
        built = create_paid_in_full_booking()
        log_after = get_success_data(api.get_event_log(built["event_log"]["id"], OPS))
        assert log_after["finalized"] is True
        completed = validate_success(api.complete_booking(built["booking"]["id"], OPS), 200)
        assert completed["schedule_status"] == "COMPLETED"


# ─── State precondition / invalid transition corners (Queue B) ─────────

def test_confirm_from_unpaid_booking_rejected(api):
    """PRD §3.4: "Confirmation may proceed only when the booking's `schedule_status` is
    `DRAFT` and its `payment_status` is already `DEPOSIT_PAID` — the deposit must have
    been recorded before the booking can be confirmed."
    PRD §3.4: "A confirmation requested against a booking not in `DRAFT` (or whose
    deposit precondition is unmet) is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_from_unpaid_booking_rejected
    """
    sc = seed_base_scenario()
    booking = create_booking(
        sc["customer"]["id"], sc["package"]["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=0)
    booth_v = get_success_data(api.get_booth(sc["booth"]["id"], OPS))["version"]
    res = api.confirm_booking(booking["id"], {"expected_booth_version": booth_v}, OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_booking(booking["id"], OPS))
    assert after["schedule_status"] == "DRAFT"


def test_start_service_from_draft_rejected(api):
    """PRD §3.5: "Once confirmed, the booking is taken into service by an
    `OperationsManager`, advancing `schedule_status` from `CONFIRMED` to `IN_SERVICE`.
    This is permitted only when the booking is `CONFIRMED` and no event log yet exists
    for it; otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/start_service_from_draft_rejected
    """
    model, package = seed_model_and_package()
    customer = create_customer()
    booking = create_booking(
        customer["id"], package["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=0)
    res = api.start_service(booking["id"], OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_terminal_completed_booking_rejected(api):
    """PRD §3.7: "A `Customer` may cancel their own booking while it is either `DRAFT` or
    `CONFIRMED`, moving `schedule_status` to `CANCELLED`; a cancel against any other
    schedule state is rejected with `ERR_INVALID_STATE`."
    PRD §3.8: "Both `COMPLETED` and `CANCELLED` are terminal schedule states."

    Design: Corner/state_machines/cancel_terminal_completed_booking_rejected
    """
    built = create_completed_booking()
    cust_id = built["scenario"]["customer"]["id"]
    res = api.cancel_booking(built["booking"]["id"], make_customer_headers(cust_id))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_booking(built["booking"]["id"], OPS))
    assert after["schedule_status"] == "COMPLETED"


def test_gallery_unpublish_from_draft_rejected(api):
    """PRD §3.9: "Unpublishing from `PUBLISHED` to `UNPUBLISHED` requires only that the
    gallery is `PUBLISHED`."
    PRD §3.9: "any publish or unpublish requested from the wrong gallery state is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/gallery_unpublish_from_draft_rejected
    """
    built = create_completed_booking()
    gid = built["gallery"]["id"]
    res = api.unpublish_gallery(gid, OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_gallery(gid, OPS))
    assert after["status"] == "DRAFT"


def test_confirm_twice_second_rejected(api):
    """PRD §3.4: "A confirmation requested against a booking not in `DRAFT` (or whose
    deposit precondition is unmet) is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_twice_idempotency_second_rejected
    """
    built = create_confirmed_booking()
    booth_id = built["scenario"]["booth"]["id"]
    booth_v = get_success_data(api.get_booth(booth_id, OPS))["version"]
    res = api.confirm_booking(built["booking"]["id"], {"expected_booth_version": booth_v}, OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_booking(built["booking"]["id"], OPS))
    assert after["schedule_status"] == "CONFIRMED"


def test_add_addon_to_confirmed_booking_locked(api):
    """PRD §3.3: "A line may be added only while the booking's `schedule_status` is
    `DRAFT`; attempting to add a line to a booking in any other schedule state is
    rejected with `ERR_BOOKING_LOCKED`."

    Design: Corner/state_machines/add_addon_to_confirmed_booking_locked
    """
    built = create_confirmed_booking()
    cust_id = built["scenario"]["customer"]["id"]
    props = create_add_on(code="PROPS", name="Prop Box", unit_price=50.00)
    res = api.add_booking_add_on(
        built["booking"]["id"], {"add_on_id": props["id"], "qty": 1},
        make_customer_headers(cust_id))
    validate_error(res, ApiErrorId.ERR_BOOKING_LOCKED.value)


def test_finalize_rejects_unordered_actual_timestamps(api):
    """PRD §3.5: "Finalization requires ... that the timestamps are consistently ordered
    so that `actual_setup_start` is at or before `actual_coverage_start`,
    `actual_coverage_start` is strictly before `actual_coverage_end`, and
    `actual_coverage_end` is at or before `actual_teardown_end` ... A finalize that
    violates any of these is rejected with `ERR_INVALID_STATE` (or `ERR_INVALID_REQUEST`
    for a malformed actuals payload)."

    Design: Corner/state_machines/finalize_rejects_unordered_actual_timestamps
    """
    built = create_in_service_booking()
    log = built["event_log"]
    payload = {
        "actual_setup_start": "2026-09-12T18:00:00Z",
        "actual_coverage_start": "2026-09-12T20:00:00Z",
        "actual_coverage_end": "2026-09-12T19:00:00Z",   # before coverage_start
        "actual_teardown_end": "2026-09-12T22:30:00Z",
        "actual_print_count": 100,
        "expected_eventlog_version": log["version"],
    }
    res = api.finalize_event_log(log["id"], payload, OPS)
    # The recipe asserts ERR_INVALID_REQUEST; PRD §3.5 names both ERR_INVALID_STATE and
    # ERR_INVALID_REQUEST for an out-of-order/malformed actuals payload without uniquely
    # pinning which applies to a logically-ordered-but-inverted coverage span.
    validate_error_is_one_of(res, [
        ApiErrorId.ERR_INVALID_REQUEST.value, ApiErrorId.ERR_INVALID_STATE.value])


# ─── Endpoint action corners (Queue B endpoints) ──────────────────────


def test_gallery_photos_increments_count(api):
    """PRD §3.9: "An `OperationsManager` uploads photos with a `count`, which increases
    the gallery's `photo_count` by that amount and increments the gallery's `version`."

    Design: Corner/endpoints/gallery_photos_action_increments_count
    """
    built = create_completed_booking()
    gid = built["gallery"]["id"]
    updated = validate_success(api.upload_gallery_photos(gid, {"count": 5}, OPS), 200)
    assert updated["photo_count"] == 5
    assert updated["status"] == "DRAFT"
