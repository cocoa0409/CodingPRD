"""Invoice evaluation order: discount tier keyed on the pre-discount subtotal,
re-keyed between provisional and final (PRD §3.6)."""
import pytest

from test_helpers import (
    validate_success,
    invoice_of_kind,
    assert_invoice_conservation,
    setup_approved_permit,
    setup_completed_permit,
    TEST_USERS,
    api_client,
)

DIRECTOR = TEST_USERS["director_headers"]

FP_PRE_POLICY = {
    "policy_code": "FP-PRE", "rate_class": "FOR_PROFIT", "facility_tier": "PREMIUM",
    "hourly_rate_cents": 15000, "deposit_basis_points": 3000,
    "custodial_hourly_cents": 6000, "effective_from": "2026-01-01T00:00:00Z",
    "deposit_floor_cents": 20000,
}
# Fri 2026-11-06 afternoon/evening site-local; 6 billable hours.
EVENT_START = "2026-11-06T21:00:00Z"
EVENT_END = "2026-11-07T03:00:00Z"


def _kwargs():
    return dict(
        site_code="FHS",
        facility_overrides={"facility_code": "AUD", "facility_tier": "PREMIUM",
                            "capacity": 500},
        policy_overrides=FP_PRE_POLICY,
        org_name="Gala Productions LLC", rate_class="FOR_PROFIT",
        insurance_overrides={"per_occurrence_limit_cents": 200000000,
                             "aggregate_limit_cents": 400000000},
        event_title="Product Launch", headcount_estimate=400,
        starts_at=EVENT_START, ends_at=EVENT_END,
    )


class TestInvoiceTotalTierRekeyEvaluationOrder:
    def test_provisional_discount_tier_ten_percent(self, api):
        """PRD §3.6: "**Fifth, the volume discount**, keyed on that pre-discount
        subtotal with inclusive floors: a subtotal of at least 200000 cents earns
        15 percent; otherwise at least 100000 cents earns 10 percent; otherwise at
        least 50000 cents earns 5 percent; below that, nothing."

        Design: Difficulty/combinatorial_formula/invoice_total_tier_rekey_evaluation_order
        """
        env, req, permit = setup_approved_permit(**_kwargs())
        # 6 billable hours: rental = round_half_up(90000 * 0.90) = 81000
        assert permit["deposit_required_cents"] == 24300

        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        prov = invoice_of_kind(invoices, "PROVISIONAL")
        # Custodial span 20:30Z-03:30Z = 7.0h; weekday evening -> after-hours only.
        assert prov["rental_fee_cents"] == 81000
        assert prov["staffing_charge_cents"] == 42000
        assert prov["after_hours_charge_cents"] == 21000
        assert prov["discount_cents"] == 14400       # subtotal 144000 -> 10% tier
        assert prov["total_cents"] == 129600
        assert_invoice_conservation(prov)

    def test_final_discount_tier_rekeys_to_five_percent(self, api):
        """PRD §3.6: "And because the discount tier re-keys on the final subtotal,
        actuals that push the subtotal across a tier boundary — past 100000 cents,
        say — move the provisional and final totals apart by more than the staffing
        delta alone."
        PRD §3.6: "A minimum-shift floor applies: whenever the hours are greater
        than zero but less than 2.0, exactly 2.0 hours are billed instead, that
        product likewise rounded half-up."

        Design: Difficulty/combinatorial_formula/invoice_total_tier_rekey_evaluation_order
        """
        env, req, permit, work_order = setup_completed_permit(
            deposit_cents=24300, clock_after_end="2026-11-07T12:00:00Z",
            actual_hours=1.5, idempotency_key="dep-c-1", **_kwargs())

        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        prov = invoice_of_kind(invoices, "PROVISIONAL")
        final = invoice_of_kind(invoices, "FINAL")

        # actual 1.5h -> min-shift floor bills 2.0h x 6000 = 12000
        assert final["staffing_charge_cents"] == 12000
        assert final["after_hours_charge_cents"] == 6000   # 0.50 x 12000
        assert final["rental_fee_cents"] == 81000
        # subtotal 99000 < 100000 -> tier re-keys from 10% down to 5%
        assert final["discount_cents"] == 4950
        assert final["total_cents"] == 94050
        assert_invoice_conservation(final)

        # Totals diverge by more than the staffing delta (30000) alone:
        # 35550 = staffing 30000 + after-hours 15000 - discount delta 9450.
        assert prov["total_cents"] - final["total_cents"] == 35550
