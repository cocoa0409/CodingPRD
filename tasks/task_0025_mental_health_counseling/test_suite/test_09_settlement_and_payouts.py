"""Settlement ledger breakdowns and payout aggregation (PRD §3.8, §3.9)."""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_charge_breakdown_pay_per_session,
    assert_charge_breakdown_package,
    bring_counselor_to_active,
    confirm_appointment,
    create_appointment_in_hold,
    create_payout_payload,
    create_slot,
    DEFAULT_LIST_PRICE_CENTS,
    DEFAULT_T0,
    disqualify_counselor,
    find_ledger_row,
    list_settlement_ledger_for_appointment,
    make_admin_headers,
    make_client_headers,
    setup_confirmed_appointment,
    setup_counselor_and_completed_client,
    shift,
    validate_error,
    validate_success,
)


class TestPayPerSessionCharge:
    def test_pps_charge_breakdown_default_share(self):
        """PRD §3.8: "For `PAY_PER_SESSION`, `gross_amount_cents` equals the
        appointment's frozen `list_price_cents` (default 12000 cents). The
        tax component `tax_cents` is `gross_amount_cents` multiplied by the
        basis-points tax rate `TAX_BPS` of 875 divided by 10000, rounded
        half up. The counselor's portion `counselor_share_cents` is
        `gross_amount_cents` multiplied by the counselor's
        `revenue_share_bps` divided by 10000, rounded half up. The
        platform's portion `platform_share_cents` is then
        `gross_amount_cents` minus `counselor_share_cents`, with no further
        rounding."
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
            revenue_share_bps=7000,
        )
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        charge = find_ledger_row(rows, confirmed["id"], "CHARGE")
        assert charge is not None
        assert_charge_breakdown_pay_per_session(
            charge, list_price_cents=DEFAULT_LIST_PRICE_CENTS,
            revenue_share_bps=7000, tax_bps=875,
        )

    def test_pps_charge_breakdown_custom_share(self):
        """PRD §2.8: "Counselor revenue share is similarly stored in basis
        points on the counselor's `revenue_share_bps` field, with a default
        of 7000 (70%) and a permitted range from 0 to 10000."

        Verify the breakdown adapts to a non-default share.
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
            revenue_share_bps=6000,
        )
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        charge = find_ledger_row(rows, confirmed["id"], "CHARGE")
        assert charge is not None
        assert_charge_breakdown_pay_per_session(
            charge, list_price_cents=DEFAULT_LIST_PRICE_CENTS,
            revenue_share_bps=6000, tax_bps=875,
        )

    def test_pps_per_component_rounding_pin(self):
        """PRD §2.8: "for the same gross amount, the result of 'round
        counselor share, then platform share = gross minus counselor share'
        can differ by one cent from the result of 'round platform share
        directly from the residual basis points', and the platform requires
        the former."

        Use revenue_share_bps=6667 with default list_price_cents=12000.
        Method A (PRD-pinned): counselor = round_half_up(12000*6667/10000)
                              = round_half_up(8000.4) = 8000;
                              platform = 12000 - 8000 = 4000.
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
            revenue_share_bps=6667,
        )
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        charge = find_ledger_row(rows, confirmed["id"], "CHARGE")
        assert charge is not None
        assert charge["counselor_share_cents"] == 8000
        assert charge["platform_share_cents"] == 4000


class TestPackageCharge:
    def test_package_charge_breakdown(self):
        """PRD §3.8: "For `PACKAGE`, the consumer has already paid for the
        session through the prepaid package, so the ledger's
        `gross_amount_cents` is zero and `tax_cents` is zero. The counselor
        still earns a share, however, computed against an imputed shadow
        rate `SHADOW_PACKAGE_RATE` of 9000 cents per session:
        `counselor_share_cents` equals 9000 multiplied by `revenue_share_bps`
        divided by 10000, rounded half up. Because there is no concurrent
        gross to draw from, the platform absorbs that share from prior
        package revenue, so `platform_share_cents` equals the negative of
        `counselor_share_cents`."
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PACKAGE",
            revenue_share_bps=7000, package_balance_sessions=2,
        )
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        charge = find_ledger_row(rows, confirmed["id"], "CHARGE")
        assert charge is not None
        assert_charge_breakdown_package(
            charge, revenue_share_bps=7000, shadow_rate_cents=9000,
        )


class TestPayoutWindowOverlap:
    def test_overlapping_window_rejected(self, api, admin_headers):
        """PRD §3.9: "the new payout's window must not overlap any existing
        `PENDING` or `PAID` payout for the same counselor, otherwise
        `ERR_PAYOUT_WINDOW_OVERLAP`."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        # Create initial payout.
        api.create_payout(
            create_payout_payload(
                counselor_id=counselor["id"],
                period_start_at="2026-01-01T00:00:00.000Z",
                period_end_at="2026-02-01T00:00:00.000Z",
            ),
            admin_headers,
        )
        # Overlapping payout: start in middle of first window.
        res = api.create_payout(
            create_payout_payload(
                counselor_id=counselor["id"],
                period_start_at="2026-01-15T00:00:00.000Z",
                period_end_at="2026-03-01T00:00:00.000Z",
            ),
            admin_headers,
        )
        validate_error(res, "ERR_PAYOUT_WINDOW_OVERLAP", expected_status=409)


class TestPayoutDisqualified:
    def test_disqualified_counselor_payout_rejected(self, api, admin_headers):
        """PRD §3.9: "A payout creation against a counselor whose `status`
        is `DISQUALIFIED` is rejected with `ERR_COUNSELOR_DISQUALIFIED`."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        disqualify_counselor(counselor)
        res = api.create_payout(
            create_payout_payload(
                counselor_id=counselor["id"],
                period_start_at="2026-01-01T00:00:00.000Z",
                period_end_at="2026-02-01T00:00:00.000Z",
            ),
            admin_headers,
        )
        validate_error(res, "ERR_COUNSELOR_DISQUALIFIED", expected_status=409)


class TestSettlementLedgerImmutability:
    def test_ledger_rows_have_no_updated_at_or_version(self):
        """PRD §2.4: "SettlementLedger (whose rows are append-only — once a
        CHARGE or REFUND row is written it is never updated) ... For these
        three, callers MUST NOT supply a `version` in any request, and the
        server MUST NOT return one."
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
        )
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        for row in rows:
            assert "updated_at" not in row, \
                "PRD §2.4: SettlementLedger rows MUST NOT carry updated_at"
            assert "version" not in row, \
                "PRD §2.4: SettlementLedger rows MUST NOT carry version"
