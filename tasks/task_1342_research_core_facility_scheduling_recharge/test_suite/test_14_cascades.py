"""Transitive cascades: downtime confirm, instrument retire, and user
suspension, each releasing grant encumbrance (PRD §2.10, §3.1, §3.2, §3.11)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, create_downtime_event_payload, create_booking_payload,
    make_researcher_headers,
    setup_canonical_stack, create_booking_request, create_approved_booking,
    set_clock, get_booking, get_grant, get_instrument,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _saturated_stack(api):
    """Canonical stack whose grant totals exactly 18000; one APPROVED 90-minute
    booking (estimate 18000) drives budget_available_cents to exactly 0."""
    stack = setup_canonical_stack(grant_budget=18000)
    b1 = create_approved_booking(stack)
    return stack, b1


class TestDowntimeConfirmCascade:
    def _setup(self, api):
        stack, b1 = _saturated_stack(api)
        dt1 = validate_success(
            api.create_downtime_event(
                create_downtime_event_payload(
                    stack["i1"]["id"], notes="cryogen fault"
                ),
                STAFF,
            ),
            201,
        )
        # The window 08:00-12:00 contains the logical time 08:30.
        set_clock("2026-09-01T08:30:00Z")
        return stack, b1, dt1

    def test_confirm_cancels_booking_and_flips_instrument(self, api):
        """PRD §3.11: "If the event's window contains the current logical time,
        the instrument flips to `DOWN` for `UNSCHEDULED_FAILURE` or to
        `MAINTENANCE` for the other kinds" and "Every booking on the instrument
        whose interval intersects the downtime window under closed-interval
        semantics is resolved: `APPROVED` bookings are `CANCELLED` with
        `cancellation_reason` `DOWNTIME`, penalty waived and zeroed".

        Design: Difficulty/transitive_cascade/downtime_confirm_cancellation_cascade
        """
        stack, b1, dt1 = self._setup(api)
        grant_pre = get_grant(stack["g1"]["id"])
        assert grant_pre["status"] == "EXHAUSTED"
        assert grant_pre["budget_available_cents"] == 0

        confirmed = validate_success(api.confirm_downtime_event(dt1["id"], STAFF), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert get_instrument(stack["i1"]["id"])["status"] == "DOWN"

        booking = get_booking(b1["id"])
        assert booking["status"] == "CANCELLED"
        assert booking["cancellation_reason"] == "DOWNTIME"
        assert booking["penalty_waived"] is True
        assert booking["penalty_cents"] == 0

    def test_booking_cancellation_recovers_exhausted_grant(self, api):
        """PRD §3.11: "each cancelled booking's grant encumbrance is released
        exactly as in the suspension cascade, with the grant's status
        recomputed." PRD §2.10: "When a reversal (a cancellation releasing
        encumbrance, a write-off crediting a charge, or an amendment raising
        the budget) pushes availability back above zero, an `EXHAUSTED` grant
        flips back to `ACTIVE` without any explicit client action."

        Design: Difficulty/transitive_cascade/downtime_confirm_cancellation_cascade
        """
        stack, b1, dt1 = self._setup(api)
        validate_success(api.confirm_downtime_event(dt1["id"], STAFF), 200)
        grant = get_grant(stack["g1"]["id"])
        assert grant["budget_encumbered_cents"] == 0
        assert grant["budget_available_cents"] == 18000
        assert grant["status"] == "ACTIVE", "recovered via the release"
        assert get_booking(b1["id"])["encumbered_cents"] == 0


class TestInstrumentRetireCascade:
    def test_retire_cancels_future_approved_booking(self, api):
        """PRD §3.2: "Retirement is terminal and cascades broadly: every
        `REQUESTED` booking on the instrument is `REJECTED`; every `APPROVED`
        booking with a future `start_at` is `CANCELLED` with
        `cancellation_reason` `INSTRUMENT_RETIRED`, penalty waived, and zero
        penalty".

        Design: Difficulty/transitive_cascade/instrument_retire_cascade
        """
        stack, b1 = _saturated_stack(api)
        retired = validate_success(api.retire_instrument(stack["i1"]["id"], ADMIN), 200)
        assert retired["status"] == "RETIRED"
        booking = get_booking(b1["id"])
        assert booking["status"] == "CANCELLED"
        assert booking["cancellation_reason"] == "INSTRUMENT_RETIRED"
        assert booking["penalty_waived"] is True
        assert booking["penalty_cents"] == 0

    def test_retire_releases_encumbrance_and_recovers_grant(self, api):
        """PRD §3.2: "each cancellation releases its grant encumbrance exactly
        as in the suspension cascade". PRD §2.10: "When a reversal (a
        cancellation releasing encumbrance, a write-off crediting a charge, or
        an amendment raising the budget) pushes availability back above zero,
        an `EXHAUSTED` grant flips back to `ACTIVE` without any explicit client
        action."

        Design: Difficulty/transitive_cascade/instrument_retire_cascade
        """
        stack, b1 = _saturated_stack(api)
        validate_success(api.retire_instrument(stack["i1"]["id"], ADMIN), 200)
        grant = get_grant(stack["g1"]["id"])
        assert grant["budget_encumbered_cents"] == 0
        assert grant["budget_available_cents"] == 18000
        assert grant["status"] == "ACTIVE"


class TestUserSuspensionCascade:
    def test_user_suspend_cascades_to_future_bookings(self, api):
        """PRD §3.1: "When a `FacilityAdmin` suspends a user, every `REQUESTED`
        booking of that user whose `start_at` lies in the future is `REJECTED`,
        and every `APPROVED` booking with a future `start_at` is `CANCELLED`
        with `cancellation_reason` set to `USER_SUSPENDED`, `penalty_waived`
        set to true, and `penalty_cents` set to zero. Each such cancellation
        releases the booking's grant encumbrance: the grant's
        `budget_encumbered_cents` decreases by the booking's
        `encumbered_cents`, the booking's `encumbered_cents` becomes zero, and
        the grant's status is recomputed, so an `EXHAUSTED` grant may recover
        to `ACTIVE`."

        Design: Corner/state_machines/user_suspend_cascades_to_future_bookings
        """
        stack = setup_canonical_stack()
        b1 = create_booking_request(stack)  # REQUESTED 2026-09-01
        b2 = create_approved_booking(
            stack, start_at="2026-09-02T09:00:00Z", end_at="2026-09-02T10:30:00Z"
        )

        suspended = validate_success(api.suspend_user(stack["u1"]["id"], ADMIN), 200)
        assert suspended["status"] == "SUSPENDED"

        assert get_booking(b1["id"])["status"] == "REJECTED"
        booking2 = get_booking(b2["id"])
        assert booking2["status"] == "CANCELLED"
        assert booking2["cancellation_reason"] == "USER_SUSPENDED"
        assert booking2["penalty_waived"] is True
        assert booking2["penalty_cents"] == 0
        assert booking2["encumbered_cents"] == 0
        assert get_grant(stack["g1"]["id"])["budget_encumbered_cents"] == 0
