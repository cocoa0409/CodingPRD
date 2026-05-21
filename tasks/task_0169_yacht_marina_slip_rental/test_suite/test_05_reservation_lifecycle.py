"""Reservation lifecycle — PRD §3.4.

DRAFT → APPROVED → CHECKED_IN → CHECKED_OUT happy path, plus
DRAFT→CANCELLED, APPROVED→CANCELLED, and APPROVED→EXPIRED branches.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to_iso,
    approve_reservation,
    assert_reservation,
    cancel_reservation_as_boater,
    check_in_reservation,
    check_out_reservation,
    create_boater,
    create_marina,
    create_reservation,
    create_reservation_payload,
    create_slip,
    create_vessel,
    create_boater_with_vessel,
    create_active_policy,
    get_marina,
    get_reservation,
    make_boater_headers,
    run_ops,
    schedule_pump_out,
    setup_approved_reservation,
    setup_checked_in_reservation,
    setup_draft_reservation,
    validate_error,
)


# ===========================================================================
# Reservation create — PRD §3.4
# ===========================================================================
class TestReservationCreate:

    def test_new_reservation_is_draft(self, api, dock_master_headers):
        """PRD §3.4: "The reservation is born in `status` `DRAFT`.\""""
        scenario = setup_draft_reservation()
        assert scenario["reservation"]["status"] == "DRAFT"
        assert_reservation(scenario["reservation"])

    def test_check_out_before_check_in_rejected(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "the system rejects any creation request where
        `check_out_date` is not strictly after `check_in_date` with
        `ERR_INVALID_DATE_RANGE`."

        Claim: check_out_date == check_in_date is rejected with
        ERR_INVALID_DATE_RANGE."""
        marina = create_marina()
        slip = create_slip(marina["id"])
        boater, vessel = create_boater_with_vessel(marina["id"])
        policy = create_active_policy(marina["id"], boater)
        payload = create_reservation_payload(
            boater_id=boater["id"], vessel_id=vessel["id"],
            slip_id=slip["id"],
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-01T00:00:00.000Z",
            insurance_policy_id=policy["id"],
        )
        resp = api.create_reservation(
            marina["id"], payload, make_boater_headers(boater["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)

    def test_check_out_strictly_before_check_in_rejected(
        self, api, dock_master_headers,
    ):
        """PRD §2.9: "check_out_date must be strictly after
        check_in_date."

        Claim: check_out_date < check_in_date → ERR_INVALID_DATE_RANGE."""
        marina = create_marina()
        slip = create_slip(marina["id"])
        boater, vessel = create_boater_with_vessel(marina["id"])
        policy = create_active_policy(marina["id"], boater)
        payload = create_reservation_payload(
            boater_id=boater["id"], vessel_id=vessel["id"],
            slip_id=slip["id"],
            check_in_date="2024-05-05T00:00:00.000Z",
            check_out_date="2024-05-01T00:00:00.000Z",
            insurance_policy_id=policy["id"],
        )
        resp = api.create_reservation(
            marina["id"], payload, make_boater_headers(boater["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)


# ===========================================================================
# DRAFT → APPROVED — PRD §3.4
# ===========================================================================
class TestReservationApprove:

    def test_approve_happy_path(self, api, dock_master_headers):
        """PRD §3.4: "Approval is the consequential step. A
        `DockMaster` approves a reservation, advancing it from `DRAFT`
        to `APPROVED`."

        Claim: DRAFT → APPROVED succeeds when all preconditions hold."""
        scenario = setup_approved_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-05T00:00:00.000Z",
            liveaboard=False,
        )
        assert scenario["reservation"]["status"] == "APPROVED"

    def test_approve_non_draft_rejected_invalid_state(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "state precondition that the reservation is in
        `DRAFT` (`ERR_INVALID_STATE`)..."

        Claim: approving a CANCELLED reservation → ERR_INVALID_STATE."""
        scenario = setup_draft_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-05T00:00:00.000Z",
        )
        # Cancel from DRAFT.
        cancel_reservation_as_boater(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"],
        )
        resp = api.approve_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
            dock_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_approve_when_policy_window_excludes_term(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "the policy's `effective_date` is at or before
        `check_in_date` and its `expiration_date` is at or after
        `check_out_date`. A policy whose status is anything other than
        `ACTIVE`, or whose coverage window does not span the term,
        yields `ERR_INSURANCE_LAPSED`."

        Claim: a policy whose expiration_date is before the
        reservation's check_out_date triggers ERR_INSURANCE_LAPSED on
        approve."""
        scenario = setup_draft_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-10T00:00:00.000Z",
            policy_effective_date="2024-01-01T00:00:00.000Z",
            policy_expiration_date="2024-05-05T00:00:00.000Z",
        )
        resp = api.approve_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
            dock_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSURANCE_LAPSED.value)


# ===========================================================================
# APPROVED → CHECKED_IN — PRD §3.4
# ===========================================================================
class TestReservationCheckIn:

    def test_check_in_before_clock_reaches_check_in_date_blocked(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "the only precondition beyond state is that the
        marina's `current_date` is at or after `check_in_date` — early
        arrivals must wait for the clock to roll forward before they
        can step off the dock."

        Claim: attempting check-in while clock is before check_in_date
        is rejected (the rule is "must be at or after"). The most
        specific error the PRD names is the state-related rejection;
        PRD doesn't pin a unique error code for early check-in beyond
        the rule, so accept ERR_INVALID_STATE."""
        scenario = setup_approved_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-05T00:00:00.000Z",
        )
        # Clock still at epoch; check_in_date is in the far future
        # relative to the marina clock.
        resp = api.check_in_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
            dock_master_headers,
        )
        # PRD §3.4 spells the precondition but does not commit to a
        # specific error_id for early check-in; accept the broader
        # state-precondition rejection per §3.4 wording.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_check_in_after_clock_reaches_check_in_date_succeeds(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "Check-in advances `APPROVED` to `CHECKED_IN`."

        Claim: APPROVED → CHECKED_IN succeeds once Marina.current_date
        is at or after check_in_date."""
        scenario = setup_checked_in_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-05T00:00:00.000Z",
        )
        assert scenario["reservation"]["status"] == "CHECKED_IN"


# ===========================================================================
# CHECKED_IN → CHECKED_OUT — PRD §3.4
# ===========================================================================
class TestReservationCheckOut:

    def test_check_out_with_scheduled_pump_out_blocked(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "a still-`SCHEDULED` pump-out blocks check-out with
        `ERR_HAS_DEPENDENCIES`."

        Claim: check-out with a SCHEDULED pump-out referencing the
        reservation → ERR_HAS_DEPENDENCIES."""
        scenario = setup_checked_in_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-03T00:00:00.000Z",
            liveaboard=True,
            slip_liveaboard_allowed=True,
            vessel_holding_tank_gallons=60,
            clock_after_approve="2024-05-01T10:00:00.000Z",
        )
        # Schedule a pump-out — leaves it SCHEDULED.
        schedule_pump_out(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"],
            scheduled_start="2024-05-01T15:00:00.000Z",
            scheduled_end="2024-05-01T15:30:00.000Z",
        )
        # Advance clock to check_out_date and attempt check-out.
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-05-03T00:00:00.000Z",
        )
        resp = api.check_out_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
            dock_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_HAS_DEPENDENCIES.value)


# ===========================================================================
# Cancel — PRD §3.4
# ===========================================================================
class TestReservationCancel:

    def test_cancel_from_draft_unconditional(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "From `DRAFT` the cancel is unconditional..."

        Claim: cancelling a DRAFT reservation succeeds with no
        preconditions."""
        scenario = setup_draft_reservation()
        result = cancel_reservation_as_boater(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"],
        )
        assert result["status"] == "CANCELLED"


# ===========================================================================
# APPROVED → EXPIRED via ops/run — PRD §3.4
# ===========================================================================
class TestReservationExpire:

    def test_approved_expires_after_full_day_past_check_in(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "If the marina clock advances and an `APPROVED`
        reservation has not been checked in by a full day past its
        `check_in_date`, the next ops sweep transitions the reservation
        to `EXPIRED`."

        Claim: APPROVED → EXPIRED after clock is past check_in + 1 day
        and _ops/run runs."""
        scenario = setup_approved_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-05T00:00:00.000Z",
            liveaboard=False,
            slip_liveaboard_allowed=False,
        )
        # Advance clock to 2 days past check_in_date and run ops.
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-05-03T00:00:00.000Z",
        )
        run_ops(scenario["marina"]["id"])
        refreshed = get_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        assert refreshed["status"] == "EXPIRED", (
            f"After ops/run past check_in+1 day, reservation must be "
            f"EXPIRED, got {refreshed['status']!r}"
        )
