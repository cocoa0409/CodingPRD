"""Waitlist creation and the slip-match selector — PRD §3.7.

Append-only WaitlistEntry; ops-sweep selector promotes against the
tightest-fit available slip in ascending sequence_no order.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_waitlist_entry,
    advance_clock_to_iso,
    api_client,
    cancel_waitlist_entry,
    create_active_policy,
    create_boater,
    create_boater_with_vessel,
    create_marina,
    create_slip,
    create_vessel,
    create_waitlist_payload,
    get_waitlist_entry,
    make_boater_headers,
    run_ops,
    setup_marina_with_too_small_slip_and_waitlist,
    validate_error,
)


# ===========================================================================
# Waitlist creation — PRD §3.7
# ===========================================================================
class TestWaitlistCreate:

    def test_new_waitlist_entry_is_queued(self, api, dock_master_headers):
        """PRD §3.7: "The new entry's `status` is `QUEUED`, its
        `promoted_reservation_id` is unset, and it carries only `id` and
        `created_at` from the common-fields set — no `updated_at` and
        no `version`."

        Claim: a fresh waitlist entry has status=QUEUED, no
        promoted_reservation_id, and no updated_at/version on the
        response."""
        scenario = setup_marina_with_too_small_slip_and_waitlist()
        entry = scenario["entry"]
        assert entry["status"] == "QUEUED"
        assert entry.get("promoted_reservation_id") in (None, "")
        # PRD §2.4: WaitlistEntry omits updated_at and version.
        assert "updated_at" not in entry, (
            "WaitlistEntry must not expose 'updated_at' (PRD §2.4)"
        )
        assert "version" not in entry, (
            "WaitlistEntry must not expose 'version' (PRD §2.4)"
        )

    def test_check_out_before_check_in_rejected(
        self, api, dock_master_headers,
    ):
        """PRD §3.7: "The system rejects any waitlist creation where
        `requested_check_out` is not strictly after `requested_check_in`
        with `ERR_INVALID_DATE_RANGE`."

        Claim: requested_check_out == requested_check_in →
        ERR_INVALID_DATE_RANGE."""
        marina = create_marina()
        boater, vessel = create_boater_with_vessel(marina["id"])
        h = make_boater_headers(boater["id"])
        payload = create_waitlist_payload(
            boater_id=boater["id"], vessel_id=vessel["id"],
            requested_check_in="2024-05-01T00:00:00.000Z",
            requested_check_out="2024-05-01T00:00:00.000Z",
        )
        resp = api.create_waitlist_entry(marina["id"], payload, h)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)

    def test_sequence_no_is_monotonic_within_marina(
        self, api, dock_master_headers,
    ):
        """PRD §3.7: "The new entry receives a `sequence_no` assigned
        atomically — a monotonic integer unique within the marina that
        determines queue order."

        Claim: two waitlist entries in the same marina receive distinct
        sequence_nos, with the second strictly greater than the first.
        """
        marina = create_marina()
        boater_a, vessel_a = create_boater_with_vessel(marina["id"])
        boater_b, vessel_b = create_boater_with_vessel(marina["id"])
        entry_a = add_waitlist_entry(
            marina["id"], boater_a, vessel_a,
            requested_check_in="2024-05-01T00:00:00.000Z",
            requested_check_out="2024-05-05T00:00:00.000Z",
        )
        entry_b = add_waitlist_entry(
            marina["id"], boater_b, vessel_b,
            requested_check_in="2024-05-01T00:00:00.000Z",
            requested_check_out="2024-05-05T00:00:00.000Z",
        )
        assert entry_a["sequence_no"] != entry_b["sequence_no"], (
            "Each WaitlistEntry must receive a distinct sequence_no "
            "(PRD §3.7)"
        )
        assert entry_b["sequence_no"] > entry_a["sequence_no"], (
            f"sequence_no must increase monotonically; got A="
            f"{entry_a['sequence_no']}, B={entry_b['sequence_no']}"
        )


# ===========================================================================
# Waitlist cancel — PRD §3.7
# ===========================================================================
class TestWaitlistCancel:

    def test_cancel_queued_entry_transitions_to_cancelled(
        self, api, dock_master_headers,
    ):
        """PRD §3.7: "A `Boater` may cancel their own queued entry at
        any time, transitioning it to `CANCELLED`.\""""
        scenario = setup_marina_with_too_small_slip_and_waitlist()
        cancelled = cancel_waitlist_entry(
            scenario["marina"]["id"], scenario["boater"],
            scenario["entry"]["id"],
        )
        assert cancelled["status"] == "CANCELLED"


# ===========================================================================
# Promotion via ops sweep — PRD §3.7
# ===========================================================================
class TestPromotion:

    def test_no_promotion_when_candidate_set_is_empty(
        self, api, dock_master_headers,
    ):
        """PRD §3.7: "If no candidate exists the entry remains
        `QUEUED`..."

        Claim: ops/run with a too-small slip cannot promote — entry
        stays QUEUED."""
        scenario = setup_marina_with_too_small_slip_and_waitlist()
        run_ops(scenario["marina"]["id"])
        refreshed = get_waitlist_entry(
            scenario["marina"]["id"], scenario["entry"]["id"],
        )
        assert refreshed["status"] == "QUEUED", (
            f"With empty candidate set, entry must remain QUEUED, got "
            f"{refreshed['status']!r}"
        )

    def test_expiry_when_requested_check_out_passed(
        self, api, dock_master_headers,
    ):
        """PRD §3.7: "If the entry's `requested_check_out` has been
        reached or passed by the marina clock at sweep time and no
        promotion was possible, the entry transitions to `EXPIRED` in
        the same sweep."

        Claim: with a too-small slip and clock past
        requested_check_out, ops/run sets entry to EXPIRED."""
        scenario = setup_marina_with_too_small_slip_and_waitlist(
            requested_check_in="2024-05-01T00:00:00.000Z",
            requested_check_out="2024-05-05T00:00:00.000Z",
        )
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-05-06T00:00:00.000Z",
        )
        run_ops(scenario["marina"]["id"])
        refreshed = get_waitlist_entry(
            scenario["marina"]["id"], scenario["entry"]["id"],
        )
        assert refreshed["status"] == "EXPIRED", (
            f"Past requested_check_out, entry must be EXPIRED, got "
            f"{refreshed['status']!r}"
        )
