"""Renewal, overdue accrual, and sweep-driven transitions (PRD §3.3, §3.5)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    drive_rental_to_overdue,
    iso_utc,
    make_renter_headers,
    renew_rental_payload,
    return_rental_payload,
    run_sweep,
    setup_basic_rental,
    setup_overdue_rental,
    validate_error,
    validate_success,
)


# ===========================================================================
# Renewal — happy path (PRD §3.3)
# ===========================================================================
class TestRenewalHappyPath:

    def test_renewal_extends_current_expires_at(self, api):
        """PRD §3.3: "A renewal extends current_expires_at by
        renewal_billing_units multiplied by the unit-duration for the
        rental's mode."

        Claim: renewing a HOURLY rental by 2 units extends
        current_expires_at by 2 hours and leaves original_expires_at
        untouched.
        """
        ctx = setup_basic_rental(rental_mode="HOURLY", billing_units=1)
        rental = ctx["rental"]
        original_expires = datetime.fromisoformat(
            rental["original_expires_at"].replace("Z", "+00:00"),
        )
        current_expires = datetime.fromisoformat(
            rental["current_expires_at"].replace("Z", "+00:00"),
        )

        resp = api.renew_rental(
            rental["id"], renew_rental_payload(renewal_billing_units=2),
            make_renter_headers(ctx["renter_id"]),
        )
        renewed = validate_success(resp)
        new_current = datetime.fromisoformat(
            renewed["current_expires_at"].replace("Z", "+00:00"),
        )
        # +2 hours
        assert new_current == current_expires + timedelta(hours=2), (
            f"current_expires_at not extended by 2h: "
            f"was {current_expires.isoformat()}, now {new_current.isoformat()}"
        )
        # PRD §3.2: "original_expires_at is never mutated thereafter."
        assert renewed["original_expires_at"] == rental["original_expires_at"]

    def test_renewal_adds_rental_fee_and_increments_count(self, api):
        """PRD §3.3: "adds renewal_billing_units multiplied by
        unit_price_cents_snapshot to rental_fee_cents, increments
        renewal_count by one."

        Claim: rental_fee_cents grows by renewal_billing_units*unit_price
        and renewal_count moves from 0 to 1.
        """
        ctx = setup_basic_rental(rental_mode="HOURLY", billing_units=1)
        rental = ctx["rental"]
        unit_price = rental["unit_price_cents_snapshot"]
        prev_fee = rental["rental_fee_cents"]
        prev_count = rental["renewal_count"]

        resp = api.renew_rental(
            rental["id"], renew_rental_payload(renewal_billing_units=3),
            make_renter_headers(ctx["renter_id"]),
        )
        renewed = validate_success(resp)
        assert renewed["rental_fee_cents"] == prev_fee + 3 * unit_price
        assert renewed["renewal_count"] == prev_count + 1

    def test_renewal_emits_rental_fee_revenue_record(self, api,
                                                    operator_headers):
        """PRD §3.3: "and emits a RevenueRecord row of revenue_kind =
        RENTAL_FEE for the renewal increment."

        Claim: after one renewal, at least two RENTAL_FEE rows exist
        for the rental (the initial creation row plus the renewal row).
        """
        ctx = setup_basic_rental(rental_mode="HOURLY", billing_units=1)
        api.renew_rental(
            ctx["rental"]["id"],
            renew_rental_payload(renewal_billing_units=1),
            make_renter_headers(ctx["renter_id"]),
        )
        resp = api.list_revenue_records(operator_headers, params={
            "cabinet_id": ctx["cabinet"]["id"],
            "revenue_kind": "RENTAL_FEE",
        })
        rows = [
            r for r in resp.json()["data"]
            if r["rental_id"] == ctx["rental"]["id"]
        ]
        assert len(rows) >= 2, (
            f"Expected ≥2 RENTAL_FEE rows after renewal, got {len(rows)}"
        )


# ===========================================================================
# Renewal — denials (PRD §3.3, §2.9)
# ===========================================================================
class TestRenewalDenials:

    def test_overdue_rental_cannot_be_renewed(self, api):
        """PRD §3.3: "if the rental is already OVERDUE or terminal, the
        renewal is rejected with ERR_RENEWAL_NOT_PERMITTED."

        Claim: renewing an OVERDUE rental → ERR_RENEWAL_NOT_PERMITTED.
        """
        ctx = setup_overdue_rental(renter_id="renter-overdue-renew")
        assert ctx["rental"]["status"] == "OVERDUE"
        resp = api.renew_rental(
            ctx["rental"]["id"],
            renew_rental_payload(renewal_billing_units=1),
            make_renter_headers(ctx["renter_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_PERMITTED.value)

    def test_stale_version_returns_version_conflict(self, api):
        """PRD §2.5: "When version is present, the server compares it to
        the persisted resource's version: if they differ the write is
        rejected with ERR_VERSION_CONFLICT."

        Claim: renewing with version=current+5 → ERR_VERSION_CONFLICT.
        """
        ctx = setup_basic_rental()
        resp = api.renew_rental(
            ctx["rental"]["id"],
            renew_rental_payload(renewal_billing_units=1,
                                 version=ctx["rental"]["version"] + 5),
            make_renter_headers(ctx["renter_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


# ===========================================================================
# EXPIRING_SOON sweep (PRD §3.3)
# ===========================================================================
class TestExpiringSoonSweep:

    def test_expiring_soon_transition_sets_reminder(self, api,
                                                   operator_headers):
        """PRD §3.3: "When the sweep observes that the logical clock has
        reached at least thirty minutes before a rental's current_expires_at
        while still less than that timestamp, the rental transitions from
        ACTIVE to EXPIRING_SOON, reminder_sent_at is set to the sweep's
        run-time."

        Claim: at T0 + 35m on a HOURLY 1-unit rental, sweep moves
        rental to EXPIRING_SOON and sets reminder_sent_at.
        """
        ctx = setup_basic_rental(rental_mode="HOURLY", billing_units=1)
        rental = ctx["rental"]
        started_at = datetime.fromisoformat(
            rental["started_at"].replace("Z", "+00:00"),
        )
        # current_expires_at = started_at + 1h. We want clock in
        # [current_expires_at - 30m, current_expires_at), e.g., +35m.
        advance_clock_to(started_at + timedelta(minutes=35))
        run_sweep()
        refreshed = validate_success(api.get_rental(
            rental["id"], make_renter_headers(ctx["renter_id"]),
        ))
        assert refreshed["status"] == "EXPIRING_SOON", (
            f"Expected EXPIRING_SOON, got {refreshed['status']!r}"
        )
        assert refreshed["reminder_sent_at"] is not None


# ===========================================================================
# OVERDUE sweep (PRD §3.3, §2.11)
# ===========================================================================
class TestOverdueSweep:

    def test_sweep_at_grace_boundary_inclusive_no_overdue(self, api):
        """PRD §3.3: "If the inspection time is at or before the
        grace-end instant the overdue fee is zero."

        Claim: at exactly grace_end (overdue_seconds=0) the rental's
        overdue_fee_cents == 0 (boundary check on the fee formula).

        NOTE: PRD also says "When the sweep observes that the clock has
        reached or passed current_expires_at plus grace_minutes_snapshot
        minutes, an ACTIVE or EXPIRING_SOON rental transitions to
        OVERDUE." That "reached or passed" wording is inclusive at the
        boundary, so a PRD-faithful implementation may flip status to
        OVERDUE at exactly grace_end. We therefore only assert the part
        PRD uniquely determines: the fee is zero at the boundary.
        """
        ctx = setup_basic_rental(rental_mode="HOURLY", billing_units=1,
                                 pricing_overrides={"grace_minutes": 15})
        rental = ctx["rental"]
        started_at = datetime.fromisoformat(
            rental["started_at"].replace("Z", "+00:00"),
        )
        # current_expires_at = +1h. grace_end = +1h15m. Land exactly there.
        advance_clock_to(started_at + timedelta(hours=1, minutes=15))
        run_sweep()
        refreshed = validate_success(api.get_rental(
            rental["id"], make_renter_headers(ctx["renter_id"]),
        ))
        assert refreshed["overdue_fee_cents"] == 0

    def test_sweep_one_second_past_grace_makes_overdue(self, api):
        """PRD §3.3: "Otherwise the overdue elapsed time is the number of
        seconds from the grace-end instant to the inspection time; that
        elapsed time, divided by 3600, is rounded up to the next whole
        hour (any started hour counts as a full hour), and the resulting
        number of hours is multiplied by overdue_rate_snapshot to yield
        overdue_fee_cents."

        Claim: 1 second past grace_end → status=OVERDUE and live-estimate
        overdue_fee_cents == 200 (ceil(1/3600)=1 * 200).
        """
        ctx = setup_basic_rental(
            rental_mode="HOURLY", billing_units=1,
            pricing_overrides={"grace_minutes": 15,
                               "overdue_rate_cents_per_hour": 200},
        )
        rental = ctx["rental"]
        started_at = datetime.fromisoformat(
            rental["started_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(started_at
                         + timedelta(hours=1, minutes=15, seconds=1))
        run_sweep()
        refreshed = validate_success(api.get_rental(
            rental["id"], make_renter_headers(ctx["renter_id"]),
        ))
        assert refreshed["status"] == "OVERDUE", (
            f"Expected OVERDUE, got {refreshed['status']!r}"
        )
        assert refreshed["overdue_fee_cents"] == 200

    def test_compartment_cascades_to_overdue(self, api, operator_headers):
        """PRD §3.3: "an ACTIVE or EXPIRING_SOON rental transitions to
        OVERDUE and the housing compartment's occupancy_status cascades
        to OVERDUE in the same operation."

        Claim: when the rental flips OVERDUE the housing compartment's
        occupancy_status is OVERDUE.
        """
        ctx = setup_overdue_rental(renter_id="renter-cascade-od")
        comp = validate_success(api.get_compartment(
            ctx["cabinet"]["id"], ctx["compartment"]["id"], operator_headers,
        ))
        assert comp["occupancy_status"] == "OVERDUE"


# ===========================================================================
# Sweep idempotency for /_clock/advance alone (PRD §2.11)
# ===========================================================================
class TestClockOnlyDoesNotFire:

    def test_clock_advance_without_sweep_does_not_transition(self, api):
        """PRD §2.11: "Advancing the clock alone fires no transitions;
        only invoking the sweep does."

        Claim: advancing clock past grace WITHOUT running the sweep
        leaves rental ACTIVE.
        """
        ctx = setup_basic_rental(rental_mode="HOURLY", billing_units=1)
        rental = ctx["rental"]
        started_at = datetime.fromisoformat(
            rental["started_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(started_at + timedelta(hours=2))
        # No sweep!
        refreshed = validate_success(api.get_rental(
            rental["id"], make_renter_headers(ctx["renter_id"]),
        ))
        # Without sweep, status hasn't flipped from ACTIVE/EXPIRING_SOON to OVERDUE.
        assert refreshed["status"] != "OVERDUE", (
            f"Clock advance alone must not flip status to OVERDUE; "
            f"got {refreshed['status']!r}"
        )
