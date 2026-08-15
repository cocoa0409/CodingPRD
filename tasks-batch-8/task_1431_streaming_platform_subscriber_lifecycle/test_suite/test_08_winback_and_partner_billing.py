"""Win-back campaign eligibility and enrollment guards; partner-billed
reconciliation with its tolerance boundary and override path."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_partner_billing_record,
    cancel_subscription,
    create_active_campaign,
    get_partner_billing_record,
    get_subscription,
    set_clock,
    setup_account_with_subscription,
    setup_partner_billing_record,
    setup_received_partner_record,
    validate_error,
    validate_success,
    winback_enroll_payload,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
PARTNER_OPS = TEST_USERS["partner_billing_ops_headers"]


class TestWinbackEligibilityWindow:

    def test_enroll_within_too_recent_window_rejected(self):
        """PRD section 2.8: "12. **Win-back window** — enrollment requires the
        days-since-cancellation figure to fall within the campaign's inclusive
        window; failures surface `ERR_WINBACK_INELIGIBLE` (422)."
        PRD section 3.8: "The eligibility rules of §2.8 apply on enrollment:
        an account whose window or cancel reason fails every campaign is
        refused with `ERR_WINBACK_INELIGIBLE`."

        Design: Corner/validations/winback_enroll_ineligible_account_returns_error
        """
        plan, account, sub = setup_account_with_subscription()
        cancel_subscription(sub["subscription_id"])
        campaign = create_active_campaign(
            campaign_code="W30", discount_pct=50, duration_months=3,
            min_days_since_cancel=30, max_days_since_cancel=365,
            eligible_cancel_reasons=["USER_REQUESTED"],
        )
        # Only 5 days since the cancellation; the campaign's window starts
        # at 30.
        set_clock("2026-08-06T00:00:00Z")
        sub_now = get_subscription(sub["subscription_id"])
        resp = api_client.winback_enroll(
            account["account_id"],
            winback_enroll_payload(campaign["winback_campaign_id"],
                                   sub_now["version"]),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WINBACK_INELIGIBLE)


class TestPartnerReconcileBoundary:
    """Boundary precision on the auto-reconcile tolerance (PRD section 3.9)."""

    def test_delta_at_exactly_500_reconciles(self):
        """PRD section 3.9: "When the absolute delta is within the
        auto-reconcile tolerance of 500 cents — and exactly 500 counts as
        within — the record moves `RECEIVED → RECONCILED` and a `CHARGE`
        event for the received amount posts to the linked subscription's
        ledger."

        Design: Difficulty/boundary_precision_check/reconcile_delta_at_exactly_500
        """
        _account, record = setup_received_partner_record(
            expected_amount_cents=10000, received_amount_cents=10500
        )
        current = get_partner_billing_record(record["partner_billing_record_id"],
                                             as_headers=PARTNER_OPS)
        resp = api_client.reconcile_partner_record(
            record["partner_billing_record_id"],
            {"expected_partner_billing_record_version": current["version"]},
            PARTNER_OPS,
        )
        data = validate_success(resp, expected_status=200)
        assert_partner_billing_record(data)
        assert data["report_status"] == "RECONCILED", (
            f"a delta of exactly +500 is within tolerance (inclusive "
            f"boundary), got {data['report_status']}"
        )

    def test_delta_at_501_opens_discrepancy(self):
        """PRD section 3.9: "When the absolute delta exceeds the tolerance —
        501 cents is already over — the record instead moves to `DISCREPANCY`
        for human review."

        Design: Difficulty/boundary_precision_check/reconcile_delta_at_exactly_500
        """
        _account, record = setup_received_partner_record(
            expected_amount_cents=10000, received_amount_cents=10501
        )
        current = get_partner_billing_record(record["partner_billing_record_id"],
                                             as_headers=PARTNER_OPS)
        resp = api_client.reconcile_partner_record(
            record["partner_billing_record_id"],
            {"expected_partner_billing_record_version": current["version"]},
            PARTNER_OPS,
        )
        data = validate_success(resp, expected_status=200)
        assert data["report_status"] == "DISCREPANCY", (
            f"a delta of 501 exceeds the tolerance and must open a "
            f"discrepancy, got {data['report_status']}"
        )


class TestReconcileDeltaError:

    def test_over_tolerance_without_override_rejected(self):
        """PRD section 3.9: "When the absolute delta exceeds the tolerance —
        501 cents is already over — the record instead moves to `DISCREPANCY`
        for human review."
        PRD section 3.9: "A `PlatformAdmin` may reconcile it by force: the
        reconcile call on a `DISCREPANCY` record requires `override` set to
        true, and a call without the override is rejected with
        `ERR_RECONCILE_DELTA_EXCEEDS_TOLERANCE`".

        Design: Corner/errors/reconcile_delta_over_tolerance_without_override
        """
        _account, record = setup_received_partner_record(
            expected_amount_cents=10000, received_amount_cents=10600
        )
        current = get_partner_billing_record(record["partner_billing_record_id"],
                                             as_headers=PARTNER_OPS)
        # First reconcile: delta 600 exceeds the 500-cent tolerance, so the
        # record moves to DISCREPANCY.
        first = api_client.reconcile_partner_record(
            record["partner_billing_record_id"],
            {"expected_partner_billing_record_version": current["version"]},
            PARTNER_OPS,
        )
        first_data = validate_success(first, expected_status=200)
        assert first_data["report_status"] == "DISCREPANCY"
        # Second reconcile on the DISCREPANCY record, without override, is
        # rejected.
        resp = api_client.reconcile_partner_record(
            record["partner_billing_record_id"],
            {"expected_partner_billing_record_version": first_data["version"]},
            PARTNER_OPS,
        )
        validate_error(resp, ApiErrorId.ERR_RECONCILE_DELTA_EXCEEDS_TOLERANCE)
