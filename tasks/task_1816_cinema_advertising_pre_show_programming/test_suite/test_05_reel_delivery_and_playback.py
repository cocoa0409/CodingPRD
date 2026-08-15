"""Reel lifecycle: lock preconditions, dispatch/delivery retry loop,
acknowledgment deadline, playback gating, and reconciliation."""
from test_helpers import (
    ApiErrorId, constants, make_network_ops_headers, make_sales_manager_headers,
    make_theater_ops_headers, setup_bookable_slot, setup_confirmed_slot,
    setup_showtime_with_reel, validate_error, validate_success,
)
from test_helpers.factories import acknowledge_delivery_payload, create_playlog_payload
from test_helpers.fixtures import (
    SM_CREATOR, dispatch_and_deliver, set_clock,
)


class TestReelLockPreconditions:
    def test_reel_lock_empty_reel_rejected(self, api):
        """PRD §3.4: "it requires at least one slot still in `RESERVED`; locking
        a reel that has left `ASSEMBLING`, or one holding zero `RESERVED` slots,
        is rejected with `ERR_REEL_NOT_LOCKABLE`."

        Design: Corner/state_machines/reel_lock_empty_reel_rejected
        """
        _, _, _, _, reel = setup_showtime_with_reel()
        resp = api.lock_reel(reel["id"], {"expected_reel_version": reel["version"]},
                             make_network_ops_headers())
        validate_error(resp, ApiErrorId.ERR_REEL_NOT_LOCKABLE)
        resp = api.get_reel(reel["id"], make_network_ops_headers())
        after = validate_success(resp)
        assert after["reel_status"] == "ASSEMBLING"
        assert after["version"] == reel["version"]


class TestSlotCancelAfterLock:
    def test_slot_cancel_after_lock_rejected(self, api):
        """PRD §3.3: "locked slots cannot be canceled, and an attempt against a
        reel past that point is rejected with `ERR_REEL_NOT_ASSEMBLING`."

        Design: Corner/state_machines/slot_cancel_after_lock_rejected
        """
        ctx = setup_confirmed_slot()
        resp = api.cancel_slot(ctx["slot"]["id"], make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_REEL_NOT_ASSEMBLING)
        resp = api.get_slot(ctx["slot"]["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["slot_status"] == "CONFIRMED"


class TestDeliveryRetryCycle:
    def test_reel_delivery_failure_retry_cycle(self, api):
        """PRD §3.4: "A failed delivery is not terminal: dispatching again from
        `DELIVERY_FAILED` returns the reel to `IN_TRANSIT` for another attempt."

        Design: Corner/state_machines/reel_delivery_failure_retry_cycle
        """
        ctx = setup_confirmed_slot()
        reel_id = ctx["reel"]["id"]
        theater_id = ctx["theater"]["id"]
        api.dispatch_reel(reel_id, make_network_ops_headers())
        resp = api.acknowledge_delivery(reel_id, acknowledge_delivery_payload(outcome="FAILED"),
                                        make_theater_ops_headers(theater_id))
        assert validate_success(resp)["reel_status"] == "DELIVERY_FAILED"
        resp = api.dispatch_reel(reel_id, make_network_ops_headers())
        assert validate_success(resp)["reel_status"] == "IN_TRANSIT"
        resp = api.acknowledge_delivery(reel_id, acknowledge_delivery_payload(outcome="DELIVERED"),
                                        make_theater_ops_headers(theater_id))
        assert validate_success(resp)["reel_status"] == "DELIVERED"


class TestDeliveryDeadline:
    def test_delivery_ack_at_showtime_start_is_late(self, api):
        """PRD §3.4: "Acknowledging with `DELIVERED` succeeds only while the
        logical clock is still strictly before the showtime's `starts_at` — an
        acknowledgment at or after the feature's start is rejected with
        `ERR_DELIVERY_LATE` (HTTP 422)"

        Design: Corner/errors/delivery_ack_at_showtime_start_is_late
        """
        ctx = setup_confirmed_slot()
        reel_id = ctx["reel"]["id"]
        api.dispatch_reel(reel_id, make_network_ops_headers())
        # Clock at exactly the showtime's starts_at is already late.
        set_clock(constants.OPENING_EVENING_START)
        resp = api.acknowledge_delivery(reel_id, acknowledge_delivery_payload(outcome="DELIVERED"),
                                        make_theater_ops_headers(ctx["theater"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DELIVERY_LATE)
        resp = api.get_reel(reel_id, make_network_ops_headers())
        assert validate_success(resp)["reel_status"] == "IN_TRANSIT"


class TestPlaylogGating:
    def test_playlog_on_reserved_slot_rejected(self, api):
        """PRD §3.4: "only otherwise does a slot not in `CONFIRMED` yield
        `ERR_PLAYLOG_SLOT_NOT_CONFIRMED`."

        Design: Corner/state_machines/playlog_on_reserved_slot_rejected
        """
        ctx = setup_bookable_slot()
        set_clock(constants.AFTER_SHOW_CLOCK)
        resp = api.create_playlog(ctx["slot"]["id"], create_playlog_payload(),
                                  make_theater_ops_headers(ctx["theater"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAYLOG_SLOT_NOT_CONFIRMED)
        resp = api.get_slot(ctx["slot"]["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["slot_status"] == "RESERVED"

    def test_duplicate_playlog_rejected_after_first(self, api):
        """PRD §3.4: "an existing PlayLog for the slot yields
        `ERR_PLAYLOG_ALREADY_RECORDED`"

        Design: Corner/state_machines/duplicate_playlog_rejected_after_first
        """
        ctx = setup_confirmed_slot()
        set_clock(constants.AFTER_SHOW_CLOCK)
        resp = api.create_playlog(ctx["slot"]["id"], create_playlog_payload(outcome="VERIFIED"),
                                  make_theater_ops_headers(ctx["theater"]["id"]))
        validate_success(resp, expected_status=201)
        resp = api.create_playlog(ctx["slot"]["id"], create_playlog_payload(outcome="FAILED"),
                                  make_theater_ops_headers(ctx["theater"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAYLOG_ALREADY_RECORDED)
        resp = api.get_slot(ctx["slot"]["id"], make_sales_manager_headers(SM_CREATOR))
        slot = validate_success(resp)
        assert slot["slot_status"] == "PLAYED"
        assert slot["play_factor"] == 1.0

    def test_playlog_before_showtime_rejected(self, api):
        """PRD §3.4: "the logical clock must be at or after the showtime's
        `starts_at`, or the record is rejected with
        `ERR_PLAYLOG_BEFORE_SHOWTIME` (HTTP 422)."

        Design: Corner/errors/playlog_before_showtime_rejected
        """
        ctx = setup_confirmed_slot()
        # Clock two hours before the 19:00 start.
        set_clock("2026-08-14T17:00:00Z")
        resp = api.create_playlog(ctx["slot"]["id"], create_playlog_payload(),
                                  make_theater_ops_headers(ctx["theater"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAYLOG_BEFORE_SHOWTIME)
        resp = api.get_slot(ctx["slot"]["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["slot_status"] == "CONFIRMED"


class TestReconcile:
    def test_reconcile_with_unlogged_slot_rejected(self, api):
        """PRD §3.4: "Reconciliation is defined only from `DELIVERED`, and only
        once every `CONFIRMED` slot has received its playback record — that is,
        no `CONFIRMED` slot may remain — or the request is rejected with
        `ERR_REEL_NOT_RECONCILABLE`."

        Design: Corner/state_machines/reconcile_with_unlogged_slot_rejected
        """
        ctx = setup_confirmed_slot()
        reel_id = ctx["reel"]["id"]
        dispatch_and_deliver(reel_id, ctx["theater"]["id"])
        resp = api.reconcile_reel(reel_id, make_network_ops_headers())
        validate_error(resp, ApiErrorId.ERR_REEL_NOT_RECONCILABLE)
        resp = api.get_reel(reel_id, make_network_ops_headers())
        assert validate_success(resp)["reel_status"] == "DELIVERED"

    def test_reconcile_succeeds_after_playlog(self, api):
        """PRD §3.4: "A successful reconciliation moves the reel `DELIVERED →
        RECONCILED`, which is terminal."

        Design: Corner/state_machines/reconcile_with_unlogged_slot_rejected
        """
        ctx = setup_confirmed_slot()
        reel_id = ctx["reel"]["id"]
        dispatch_and_deliver(reel_id, ctx["theater"]["id"])
        set_clock(constants.AFTER_SHOW_CLOCK)
        api.create_playlog(ctx["slot"]["id"], create_playlog_payload(),
                           make_theater_ops_headers(ctx["theater"]["id"]))
        resp = api.reconcile_reel(reel_id, make_network_ops_headers())
        assert validate_success(resp)["reel_status"] == "RECONCILED"
