"""Cancellation refund waterfall: days-before tier vs administrative class
(PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    sum_txns, txns_of_kind,
    make_renter_headers,
    setup_secured_permit,
    set_clock,
    api_client,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]
ADMIN = TEST_USERS["admin_headers"]

FP_PRE_POLICY = {
    "policy_code": "FP-PRE", "rate_class": "FOR_PROFIT", "facility_tier": "PREMIUM",
    "hourly_rate_cents": 15000, "deposit_basis_points": 3000,
    "custodial_hourly_cents": 6000, "effective_from": "2026-01-01T00:00:00Z",
    "deposit_floor_cents": 20000,
}


def _secured_fp_permit(api, starts_at, ends_at, title, dep_key):
    """FOR_PROFIT renter on a PREMIUM facility; 6h event -> rental 81000 ->
    deposit max(20000, round(81000 * 0.30)) = 24300, captured."""
    env, req, permit = setup_secured_permit(
        24300, idempotency_key=dep_key,
        site_code="FHS",
        facility_overrides={"facility_code": "AUD", "facility_tier": "PREMIUM",
                            "capacity": 500},
        policy_overrides=FP_PRE_POLICY,
        org_name="Gala Productions LLC", rate_class="FOR_PROFIT",
        insurance_overrides={"per_occurrence_limit_cents": 200000000,
                             "aggregate_limit_cents": 400000000},
        event_title=title, headcount_estimate=400,
        starts_at=starts_at, ends_at=ends_at,
    )
    return env, req, permit


class TestCancellationRefundTierVsAdministrativeVariant:
    def test_renter_cancel_seven_days_before_half_refund_minus_fee(self, api):
        """PRD §3.7: "At least seven but fewer than fourteen days before, half of
        what was paid is refundable, less a processing fee of 2500 cents."
        PRD §3.7: "whatever part of the held deposit is not refunded posts as
        `DEPOSIT_FORFEIT` to the district."

        Design: Difficulty/dual_variant_calc/cancellation_refund_tier_vs_administrative_variant
        """
        env, req, permit = _secured_fp_permit(
            api, "2026-10-14T22:00:00Z", "2026-10-15T04:00:00Z", "Gala Night A", "dep-b-1")
        # Clock 2026-10-07T12:00Z -> site-local Oct 7; occupancy starts Oct 14
        # site-local: exactly 7 whole days before.
        set_clock("2026-10-07T12:00:00Z")
        org_id = env["org"]["id"]
        cancelled = validate_success(api.cancel_permit(
            permit["id"], {"cancellation_reason": "renter changed plans"},
            make_renter_headers(org_id)))
        assert cancelled["lifecycle_status"] == "CANCELLED"
        assert cancelled["financial_status"] == "REFUNDED"

        payments = validate_success(api.list_permit_payments(permit["id"], DIRECTOR))
        # gross paid 24300 -> round_half_up(24300 * 0.5) - 2500 = 12150 - 2500
        assert sum_txns(payments, "DEPOSIT_REFUND") == 9650
        assert sum_txns(payments, "DEPOSIT_FORFEIT") == 14650

    def test_tier0_supersession_administrative_full_refund(self, api):
        """PRD §3.7: "An administrative cancellation — supersession by a tier-0
        calendar event, the renter being barred, or the site closing — refunds
        one hundred percent of what was paid and charges no fee."
        PRD §3.1: "Creating a tier-0 event whose window overlaps the blocked
        interval of an already-`ISSUED` community permit preempts that permit to
        `SUPERSEDED` with a full administrative refund (§3.7)".

        Design: Difficulty/dual_variant_calc/cancellation_refund_tier_vs_administrative_variant
        """
        env, req, permit = _secured_fp_permit(
            api, "2026-10-21T22:00:00Z", "2026-10-22T04:00:00Z", "Gala Night B", "dep-b-2")
        set_clock("2026-10-19T12:00:00Z")
        validate_success(api.create_calendar_event(
            env["site"]["id"],
            {"facility_id": env["facility"]["id"], "title": "State Playoff Game",
             "starts_at": "2026-10-21T20:00:00Z", "ends_at": "2026-10-22T05:00:00Z",
             "event_priority_tier": 0},
            ADMIN), 201)

        superseded = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert superseded["lifecycle_status"] == "SUPERSEDED"
        assert superseded["financial_status"] == "REFUNDED"

        payments = validate_success(api.list_permit_payments(permit["id"], DIRECTOR))
        # Same gross paid 24300 as the tiered cancel, but administrative class
        # refunds everything and forfeits nothing.
        assert sum_txns(payments, "DEPOSIT_REFUND") == 24300
        assert txns_of_kind(payments, "DEPOSIT_FORFEIT") == []
