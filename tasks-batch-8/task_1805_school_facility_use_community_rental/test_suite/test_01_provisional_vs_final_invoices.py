"""Provisional vs final invoice variants: identical window and policy, money
driven by estimated vs verified custodial hours (PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    validate_success,
    invoice_of_kind,
    assert_invoice_conservation,
    make_renter_headers,
    setup_approved_permit,
    setup_completed_permit,
    TEST_USERS,
    api_client,
)

DIRECTOR = TEST_USERS["director_headers"]

# Sat 2026-09-05 17:00-21:00 site-local (America/Los_Angeles).
EVENT_START = "2026-09-06T00:00:00Z"
EVENT_END = "2026-09-06T04:00:00Z"


class TestProvisionalVsFinalMoneyDelta:
    def test_provisional_invoice_uses_estimated_hours(self, api):
        """PRD §3.6: "The hours figure — `estimated_hours` for a provisional invoice,
        verified `actual_hours` for a final one — is multiplied by the policy's
        `custodial_hourly_cents` and rounded half-up to integer cents."
        PRD §3.6: "`estimated_hours` is that full scheduled span expressed in hours
        to two decimal places, which means the buffers are billable custodial time."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_money_delta
        """
        env, req, permit = setup_approved_permit(
            event_title="Charity Auction", headcount_estimate=200,
            starts_at=EVENT_START, ends_at=EVENT_END,
        )
        assert permit["deposit_required_cents"] == 10000, (
            "deposit = max(floor 10000, round_half_up(20000 * 2000/10000) = 4000)")

        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        prov = invoice_of_kind(invoices, "PROVISIONAL")
        # 4 billable hours x 5000; custodial span 23:30-04:30 = 5.0h x 4000;
        # Saturday evening -> after-hours + weekend flags -> uplift 0.75.
        assert prov["rental_fee_cents"] == 20000
        assert prov["staffing_charge_cents"] == 20000
        assert prov["after_hours_charge_cents"] == 15000
        assert prov["discount_cents"] == 2750       # subtotal 55000 -> 5% tier
        assert prov["total_cents"] == 52250
        assert_invoice_conservation(prov)

    def test_final_invoice_uses_verified_actuals_and_voids_provisional(self, api):
        """PRD §3.6: "Completion voids the `PROVISIONAL` invoice, generates the
        `FINAL` invoice from actuals, and moves the financial dimension to
        `INVOICED` if it is not already there."
        PRD §3.6: "so the money that actually moves is staffing: the provisional
        bills the estimated span while the final bills verified actual hours,
        which almost always differ."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_money_delta
        """
        env, req, permit, work_order = setup_completed_permit(
            deposit_cents=10000, clock_after_end="2026-09-06T12:00:00Z",
            actual_hours=6.5, idempotency_key="dep-a-1",
            event_title="Charity Auction", headcount_estimate=200,
            starts_at=EVENT_START, ends_at=EVENT_END,
        )
        assert work_order is not None and work_order["wo_status"] == "VERIFIED"

        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        prov = invoice_of_kind(invoices, "PROVISIONAL")
        final = invoice_of_kind(invoices, "FINAL")

        assert prov["invoice_status"] == "VOID", "provisional voided at completion"
        assert final["rental_fee_cents"] == 20000      # window unchanged
        assert final["staffing_charge_cents"] == 26000  # 6.5h x 4000
        assert final["after_hours_charge_cents"] == 19500  # 0.75 x 26000
        assert final["discount_cents"] == 3275          # subtotal 65500 -> 5% tier
        assert final["total_cents"] == 62225
        assert_invoice_conservation(final)

        # Identical window and rate policy: the 9975 delta is purely the
        # estimate-vs-actual variant (staffing +6000, after-hours +4500,
        # discount +525).
        assert final["total_cents"] - prov["total_cents"] == 9975
