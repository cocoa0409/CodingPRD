"""Invoice birth state, pinned tiered pricing, and reading-type variants."""
import pytest

from test_helpers import (
    CYCLE_1,
    CYCLE_2,
    api_client,
    assert_invoice,
    bill_cycle_with_readings,
    close_cycle,
    create_area,
    create_rate_schedule_payload,
    get_cycle_invoice,
    get_success_data,
    open_cycle,
    setup_billed_invoice,
    setup_district_with_schedule,
    setup_member_with_installed_tap,
    submit_reading,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    DIRECTOR,
    TREASURER,
    add_member_with_installed_tap,
    adopt_rate_schedule,
    adopt_resolution,
)

# Schedule S1 economics: base 3500 covers 2000 gal; tier2 450/started-kgal up to
# 10000 cumulative; tier3 700/started-kgal beyond. Rounding is per tier, then sum.


def _setup_two_tap_billed_cycle(api, reading_a, reading_b):
    """District with two members/taps billed in one cycle; returns context."""
    district, schedule = setup_district_with_schedule()
    area = create_area(district["id"])
    member_a, tap_a = add_member_with_installed_tap(district["id"], area["id"], "M A")
    member_b, tap_b = add_member_with_installed_tap(district["id"], area["id"], "M B")
    cycle = open_cycle(district["id"], **CYCLE_1)
    bill_cycle_with_readings(
        district["id"], cycle["id"], [(tap_a["id"], reading_a), (tap_b["id"], reading_b)]
    )
    inv_a = get_cycle_invoice(district["id"], cycle["id"], member_a["id"])
    inv_b = get_cycle_invoice(district["id"], cycle["id"], member_b["id"])
    return district, schedule, member_a, member_b, cycle, inv_a, inv_b


class TestInvoiceBirthState:
    def test_invoice_initial_state_and_pinned_schedule(self, api):
        """PRD section 3.4: "Its `billing_status` begins at `ISSUED` and its
        `collection_status` at `CURRENT`" and "`amount_paid_cents` starts at 0 and
        `days_past_due` at 0" and "its `rate_schedule_id` is pinned to the
        district's `active_rate_schedule_id` at the moment of billing —
        version-pinned and never re-pinned afterwards".

        Design: Corner/state_machines/invoice_initial_state_on_bill
        """
        ctx = setup_billed_invoice(usage_gallons=3000)
        invoice = ctx["invoice"]
        assert_invoice(invoice)
        assert invoice["billing_status"] == "ISSUED"
        assert invoice["collection_status"] == "CURRENT"
        assert invoice["amount_paid_cents"] == 0
        assert invoice["days_past_due"] == 0
        assert invoice["rate_schedule_id"] == ctx["schedule"]["id"]
        # usage 3000 -> billable 1000 -> 1 started thousand x 450 -> total 3950
        assert invoice["usage_gallons"] == 3000
        assert invoice["usage_charge_cents"] == 450
        assert invoice["minimum_charge_cents"] == 3500
        assert invoice["total_cents"] == 3950


class TestInclusionBoundary:
    def test_usage_at_exact_inclusion_bills_minimum_only(self, api):
        """PRD section 3.4: "The billable quantity above inclusion is U minus
        `included_gallons`, floored at zero." and "the member always pays the
        monthly minimum plus marginal usage above the inclusion, and the maximum
        is load-bearing for the zero-usage edge". At U == included_gallons the
        billable quantity is zero and the total is the bare minimum.

        Design: Difficulty/boundary_precision_check/tier_inclusion_boundary_2000_vs_2001
        """
        _, _, _, _, _, inv_a, _ = _setup_two_tap_billed_cycle(api, 2000, 2001)
        assert inv_a["usage_gallons"] == 2000
        assert inv_a["usage_charge_cents"] == 0
        assert inv_a["total_cents"] == 3500

    def test_one_gallon_over_inclusion_bills_a_full_started_thousand(self, api):
        """PRD section 3.4: "Each tier's gallons are converted to
        started-thousands by dividing by 1,000 and rounding up to the next whole
        thousand — a single gallon into a tier bills the full thousand". At
        U == 2001 the single gallon over inclusion bills 1 x 450 = 450 cents.

        Design: Difficulty/boundary_precision_check/tier_inclusion_boundary_2000_vs_2001
        """
        _, _, _, _, _, _, inv_b = _setup_two_tap_billed_cycle(api, 2000, 2001)
        assert inv_b["usage_gallons"] == 2001
        assert inv_b["usage_charge_cents"] == 450
        assert inv_b["total_cents"] == 3950


class TestRoundPerTierThenSum:
    def test_usage_12500_rounds_each_tier_before_summing(self, api):
        """PRD section 3.4: "The `usage_charge_cents` is the sum of the two tier
        charges, and the rounding order is pinned: each tier is rounded up before
        the tiers are summed." At U=12500: tier2 = 8 started-thousands x 450 =
        3600, tier3 = ceil(2500/1000)=3 x 700 = 2100, total charge 5700.

        Design: Difficulty/combinatorial_formula/tiered_charge_round_per_tier_then_sum
        """
        ctx = setup_billed_invoice(usage_gallons=12_500)
        invoice = ctx["invoice"]
        assert invoice["usage_gallons"] == 12_500
        assert invoice["usage_charge_cents"] == 5700, (
            f"round-per-tier-then-sum must give 5700, got {invoice['usage_charge_cents']}"
        )
        assert invoice["total_cents"] == 9200

    def test_usage_10501_tier3_remainder_rounds_up_independently(self, api):
        """PRD section 2.5: "The tiered usage charge rounds each tier's
        started-thousand quantity up before summing across tiers — rounding order
        is pinned as round-per-tier-then-sum, and reordering it changes results."
        At U=10501: tier2 = 3600, tier3 = ceil(501/1000)=1 x 700 = 700, charge
        4300, total 7800.

        Design: Difficulty/combinatorial_formula/tiered_charge_round_per_tier_then_sum
        """
        ctx = setup_billed_invoice(usage_gallons=10_501)
        invoice = ctx["invoice"]
        assert invoice["usage_charge_cents"] == 4300
        assert invoice["total_cents"] == 7800


class TestTierCapStraddle:
    def test_tier2_cap_straddle_10000_vs_10001(self, api):
        """PRD section 3.4: "the tier-2 quantity is the portion not exceeding
        `tier2_cap_gallons` minus `included_gallons`; the tier-3 quantity is
        whatever usage lies above `tier2_cap_gallons` (zero if none)." U=10000 is
        entirely tier-2 (3600); U=10001 pushes one gallon into tier-3, billed a
        full started thousand at 700 (4300).

        Design: Corner/calculations/tiered_charge_tier2_cap_straddle
        """
        _, _, _, _, _, inv_a, inv_b = _setup_two_tap_billed_cycle(api, 10_000, 10_001)
        assert inv_a["usage_charge_cents"] == 3600
        assert inv_a["total_cents"] == 7100
        assert inv_b["usage_charge_cents"] == 4300
        assert inv_b["total_cents"] == 7800


class TestEstimatedVsActualReadings:
    def _setup_estimated_then_actual(self, api):
        """C1 billed on an ESTIMATED 5000; C2 read ACTUAL 12000 after close."""
        ctx = setup_billed_invoice(usage_gallons=5000, reading_type="ESTIMATED")
        district = ctx["district"]
        invoice_c1 = ctx["invoice"]
        close_cycle(district["id"], ctx["cycle"]["id"], master_gallons=5000)
        cycle2 = open_cycle(district["id"], **CYCLE_2)
        bill_cycle_with_readings(district["id"], cycle2["id"], [(ctx["tap"]["id"], 12_000)])
        invoice_c2 = get_cycle_invoice(district["id"], cycle2["id"])
        ctx.update({"invoice_c1": invoice_c1, "cycle2": cycle2, "invoice_c2": invoice_c2})
        return ctx

    def test_estimated_reading_bills_on_the_estimate(self, api):
        """PRD section 3.4: "`ESTIMATED` readings bill identically to `ACTUAL`
        ones". An ESTIMATED register of 5000 bills usage 5000: billable 3000,
        3 started-thousands x 450 = 1350, total 4850.

        Design: Difficulty/dual_variant_calc/invoice_estimated_vs_actual_reading_billing
        """
        ctx = self._setup_estimated_then_actual(api)
        invoice_c1 = ctx["invoice_c1"]
        assert invoice_c1["usage_gallons"] == 5000
        assert invoice_c1["usage_charge_cents"] == 1350
        assert invoice_c1["total_cents"] == 4850

    def test_following_actual_reading_does_not_true_up_prior_invoice(self, api):
        """PRD section 3.4: "when the next cycle's `ACTUAL` reading lands, that
        cycle's usage is the actual register minus the previously estimated
        register, which may under- or over-recover against reality and is
        deliberately not trued-up on the prior invoice." Register 12000 minus
        estimate 5000 = 7000 -> billable 5000 -> 5 x 450 = 2250 -> total 5750,
        and the estimated cycle's invoice stays 4850.

        Design: Difficulty/dual_variant_calc/invoice_estimated_vs_actual_reading_billing
        """
        ctx = self._setup_estimated_then_actual(api)
        invoice_c2 = ctx["invoice_c2"]
        assert invoice_c2["usage_gallons"] == 7000
        assert invoice_c2["usage_charge_cents"] == 2250
        assert invoice_c2["total_cents"] == 5750
        reread = get_success_data(
            api.get_invoice(ctx["district"]["id"], ctx["invoice_c1"]["id"], CLERK)
        )
        assert reread["total_cents"] == 4850, "The estimated invoice must not be trued up"


class TestRatePinning:
    def test_invoice_rate_pinning_survives_later_adoption(self, api):
        """PRD section 3.4: "its `rate_schedule_id` is pinned to the district's
        `active_rate_schedule_id` at the moment of billing — version-pinned and
        never re-pinned afterwards, so a later rate adoption does not reach back."
        PRD section 3.1: "when a `RATE_ADOPTION` resolution is adopted, the target
        schedule moves `DRAFT → ADOPTED`, any previously `ADOPTED` schedule
        cascades to `SUPERSEDED`, and the district's `active_rate_schedule_id` is
        repointed".

        Design: Corner/state_machines/invoice_rate_pinning_survives_later_adoption
        """
        ctx = setup_billed_invoice(usage_gallons=1000)  # total 3500 under S1
        district = ctx["district"]
        schedule1 = ctx["schedule"]
        invoice_c1 = ctx["invoice"]

        schedule2 = adopt_rate_schedule(
            district["id"],
            schedule_label="S2",
            base_minimum_cents=4000,
            tier2_rate_cents_per_kgal=500,
            tier3_rate_cents_per_kgal=800,
            tap_fee_schedule={"RESIDENTIAL": 80_000, "COMMERCIAL": 160_000, "AGRICULTURAL": 130_000},
            reconnect_fee_cents=6000,
        )

        close_cycle(district["id"], ctx["cycle"]["id"], master_gallons=1000)
        cycle2 = open_cycle(district["id"], **CYCLE_2)
        bill_cycle_with_readings(district["id"], cycle2["id"], [(ctx["tap"]["id"], 2000)])
        invoice_c2 = get_cycle_invoice(district["id"], cycle2["id"])

        reread_c1 = get_success_data(api.get_invoice(district["id"], invoice_c1["id"], CLERK))
        assert reread_c1["rate_schedule_id"] == schedule1["id"], "Pinned schedule must not move"
        assert reread_c1["total_cents"] == 3500
        assert invoice_c2["rate_schedule_id"] == schedule2["id"]
        # usage 1000 (2000 - 1000) within inclusion -> S2 minimum applies
        assert invoice_c2["total_cents"] == 4000

        s1_after = get_success_data(api.get_rate_schedule(district["id"], schedule1["id"], DIRECTOR))
        s2_after = get_success_data(api.get_rate_schedule(district["id"], schedule2["id"], DIRECTOR))
        assert s1_after["status"] == "SUPERSEDED"
        assert s2_after["status"] == "ADOPTED"
        district_after = get_success_data(api.get_district(district["id"], ADMIN))
        assert district_after["active_rate_schedule_id"] == schedule2["id"]
