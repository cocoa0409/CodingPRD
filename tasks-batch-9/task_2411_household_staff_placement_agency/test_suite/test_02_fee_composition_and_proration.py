"""Three multi-step money formulas: the per-component final fee, the refund
proration, and the regressive poaching penalty.

Each is a fixed sequence of rounding and tier steps in which rearranging any two
steps changes the answer.
"""
from test_helpers import (
    api_client,
    assert_milestone_allocation,
    file_claim,
    file_enforcement_case,
    find_ledger_entries,
    find_milestone,
    invoice_and_pay,
    investigate_case,
    read_client,
    read_ledger,
    read_milestones,
    read_placement,
    resolve_case,
    review_claim,
    set_clock,
    setup_active_placement,
    setup_senior_scenario,
)

# A CHEF search whose four package components each carry a one-quarter-cent
# fraction, so per-component rounding loses a cent against the aggregate.
DUCLOS_OPTIONS = {
    "client": {
        "household_name": "Carrington Farm",
        "primary_contact_email": "ops@carrington.example",
        "region_code": "CA",
    },
    "signatory_name": "J. Carrington",
    "fee_schedules": [
        {
            "role_type": "CHEF",
            "comp_band_floor_cents": 0,
            "comp_band_ceiling_cents": 15_000_000,
            "fee_percent_bps": 2000,
            "guarantee_window_days": 120,
            "effective_from": "2026-01-01",
        },
        {
            "role_type": "CHEF",
            "comp_band_floor_cents": 15_000_000,
            "comp_band_ceiling_cents": 30_000_000,
            "fee_percent_bps": 2233,
            "guarantee_window_days": 120,
            "effective_from": "2026-01-01",
        },
    ],
    "requisition": {
        "role_type": "CHEF",
        "first_year_compensation_cents": 15_000_000,
        "schedule_pattern": "SIX_ONE",
        "live_in_required": False,
    },
    "candidate": {
        "full_name": "P. Duclos",
        "contact_email": "pd@mail.example",
        "primary_role_type": "CHEF",
        "years_experience": 12,
        "live_in_willing": False,
    },
    "references": [
        {
            "principal_employer_name": "Grantham Estate",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2022-01",
            "employment_end_month": "2022-12",
            "contact_email": "grantham@mail.example",
        },
        {
            "principal_employer_name": "Ravensworth Hall",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2023-01",
            "employment_end_month": "2023-12",
            "contact_email": "ravensworth@mail.example",
            "chain_to_previous": True,
        },
    ],
    "background": {
        "provider_reference": "BV-3001",
        "scope_items": ["IDENTITY", "CREDENTIAL"],
    },
    "trial": {
        "day_rate_cents": 60_000,
        "start_at": "2026-08-12T09:00:00Z",
        "end_at": "2026-08-12T17:00:00Z",
    },
    "trial_end_clock": "2026-08-12T17:00:00Z",
    "term": {
        "live_in": False,
        "weekly_hours": 50,
        "days_off_per_week": 1,
        "private_quarters": False,
        "imputed_accommodation_cents": 0,
    },
    "term_responder": "CANDIDATE",
    "placement": {
        "start_date": "2026-09-01",
        "base_salary_cents": 4_002_500,
        "guaranteed_bonus_cents": 3_502_500,
        "accommodation_imputed_cents": 2_502_500,
        "overtime_allowance_cents": 4_992_500,
    },
}


def _round_half_up_bps(amount, bps):
    """PRD §2.7 rounding: half up, away from zero on an exact half."""
    scaled = amount * bps
    whole, remainder = divmod(scaled, 10000)
    return whole + (1 if remainder * 2 >= 10000 else 0)


class TestFinalFeeComposition:
    def test_01_each_component_is_rounded_before_the_sum(self):
        """A wholly different component split still loses exactly one cent.

        PRD §3.6: "Then the **`FINAL` fee** is computed: each of the four
        components is multiplied by the re-resolved `fee_percent_bps`, divided by
        10000 and **rounded half up individually**, in the fixed order
        `base_salary_cents`, then `guaranteed_bonus_cents`, then
        `accommodation_imputed_cents`, then `overtime_allowance_cents`; the four
        rounded results are then summed, and that sum is stored as `fee_cents`
        with `fee_variant` set to `FINAL`."

        Design: Difficulty/combinatorial_formula/final_fee_rounds_each_component_before_summing_mode_b
        """
        scenario = setup_active_placement(**DUCLOS_OPTIONS)
        placement = scenario["placement"]
        assert placement["actual_first_year_compensation_cents"] == 15_000_000
        assert placement["fee_percent_bps"] == 2233
        assert placement["fee_variant"] == "FINAL"
        assert placement["fee_cents"] == 3_349_499

        per_component = [
            _round_half_up_bps(placement[field], 2233)
            for field in (
                "base_salary_cents",
                "guaranteed_bonus_cents",
                "accommodation_imputed_cents",
                "overtime_allowance_cents",
            )
        ]
        assert per_component == [893_758, 782_108, 558_808, 1_114_825]
        assert sum(per_component) == 3_349_499
        assert _round_half_up_bps(15_000_000, 2233) == 3_349_500

    def test_02_the_final_fee_carries_its_own_window_and_milestone_split(self):
        """The re-resolved band supplies the 120 day window and the split.

        PRD §3.6: "Next, `guarantee_expires_on` is recomputed as `start_date`
        plus the re-resolved `guarantee_window_days` days, and the window it
        describes is half-open: it covers `start_date` inclusive up to but
        excluding `guarantee_expires_on`."

        Design: Difficulty/combinatorial_formula/final_fee_rounds_each_component_before_summing_mode_b
        """
        scenario = setup_active_placement(**DUCLOS_OPTIONS)
        placement = scenario["placement"]
        assert placement["guarantee_window_days"] == 120
        assert placement["guarantee_expires_on"] == "2026-12-30"

        milestones = assert_milestone_allocation(
            read_milestones(placement), placement["fee_cents"]
        )
        assert [row["amount_cents"] for row in milestones] == [
            1_004_850,
            1_004_850,
            1_339_799,
        ]


class TestRefundProration:
    def _refunded(self):
        scenario = setup_senior_scenario(stage="placement_active")
        scenario["milestones"][0] = invoice_and_pay(scenario["milestones"][0])
        set_clock("2026-09-29T12:00:00Z")
        claim = file_claim(
            scenario["placement"], scenario["client_headers"], "REFUND", "2026-09-29"
        )
        claim = review_claim(claim, "OPEN_REVIEW")
        scenario["claim"] = review_claim(claim, "APPROVE_REFUND")
        return scenario

    def test_03_the_five_steps_run_in_order_on_the_prorated_gross(self):
        """The retention tier is keyed on the prorated gross, not on the fee.

        PRD §3.8: "Step four: the administrative retention rate is selected by
        tier **keyed on `gross_refund_cents`** — not on `fee_cents` and not on
        the amount invoiced — at 500 basis points when `gross_refund_cents` is
        below 1,000,000, at 750 basis points when it is from 1,000,000 up to but
        excluding 3,000,000, and at 1000 basis points when it is 3,000,000 or
        more; `retained_admin_fee_cents` is `gross_refund_cents` multiplied by
        that rate, divided by 10000, rounded half up."

        Design: Difficulty/combinatorial_formula/refund_proration_pins_gross_then_tier_then_retention_mode_c
        """
        scenario = self._refunded()
        claim = scenario["claim"]
        assert claim["status"] == "APPROVED_REFUND"
        assert claim["elapsed_days"] == 28
        assert claim["unused_days"] == 62
        assert claim["gross_refund_cents"] == 2_307_433
        assert claim["retained_admin_fee_cents"] == 173_057
        assert claim["net_refund_cents"] == 2_134_376
        assert (
            claim["gross_refund_cents"] - claim["retained_admin_fee_cents"]
            == claim["net_refund_cents"]
        )

    def test_04_the_refund_cascade_voids_pending_rows_and_posts_the_net(self):
        """Approval settles the placement, its milestones and the ledger.

        PRD §3.8: "Hop three appends a `LedgerEntry` of `entry_type`
        `REFUND_ISSUED` with `signed_amount_cents` equal to the negative of
        `net_refund_cents` and `related_ref_type` `REPLACEMENT_CLAIM`."

        Design: Difficulty/combinatorial_formula/refund_proration_pins_gross_then_tier_then_retention_mode_c
        """
        scenario = self._refunded()
        placement = read_placement(scenario["placement"])
        assert placement["fee_cents"] == 3_349_499
        assert placement["guarantee_window_days"] == 90
        assert placement["placement_status"] == "TERMINATED_REFUNDED"
        assert placement["billing_status"] == "REFUNDED"

        milestones = read_milestones(placement)
        assert find_milestone(milestones, "ENGAGEMENT")["invoice_status"] == "PAID"
        assert find_milestone(milestones, "ENGAGEMENT")["amount_cents"] == 1_004_850
        assert find_milestone(milestones, "TRIAL_CLEARED")["invoice_status"] == "VOIDED"
        assert find_milestone(milestones, "START_DATE")["invoice_status"] == "VOIDED"

        entries = read_ledger(scenario["client"])
        refunds = find_ledger_entries(entries, "REFUND_ISSUED")
        assert len(refunds) == 1
        assert refunds[0]["signed_amount_cents"] == -2_134_376
        assert refunds[0]["related_ref_type"] == "REPLACEMENT_CLAIM"
        assert entries[-1]["balance_after_cents"] == -2_134_376
        assert read_client(scenario["client"])["outstanding_balance_cents"] == -2_134_376


class TestPoachingPenalty:
    def test_05_the_tier_is_keyed_on_the_source_placement_fee(self):
        """A base of 3,349,499 selects the middle 7500 bps tier.

        PRD §3.9: "Step two: the rate is selected by a deliberately
        **regressive** tier keyed on that base — 10000 basis points, a full 100
        percent, when the base is below 2,000,000; 7500 basis points when the
        base is from 2,000,000 up to but excluding 5,000,000; and 5000 basis
        points when the base is 5,000,000 or more."

        Design: Difficulty/combinatorial_formula/poaching_penalty_tiers_on_base_then_multiplies_mode_a
        """
        scenario = setup_senior_scenario(stage="placement_active")
        set_clock("2026-10-01T00:00:00Z")
        case = file_enforcement_case(
            scenario["client"],
            scenario["candidate"],
            "2026-09-30",
            source_placement=scenario["placement"],
        )
        case = resolve_case(investigate_case(case), "SUBSTANTIATE")
        assert case["status"] == "SUBSTANTIATED"
        assert case["prior_substantiated_count"] == 0
        assert case["penalty_cents"] == 2_512_124
        assert _round_half_up_bps(3_349_499, 7500) == 2_512_124

        client = read_client(scenario["client"])
        assert client["status"] == "SUSPENDED"
        assert client["outstanding_balance_cents"] == 2_512_124

    def test_06_the_repeat_multiplier_doubles_the_second_assessment(self):
        """One frozen prior count is the only difference, and it doubles it.

        PRD §3.9: "Step four: the rated amount is multiplied by one plus
        `prior_substantiated_count`, so a first offence is taken once, a first
        repeat twice, a second repeat three times; this multiplication is exact
        with no rounding."

        Design: Difficulty/combinatorial_formula/poaching_penalty_tiers_on_base_then_multiplies_mode_a
        """
        scenario = setup_senior_scenario(stage="placement_active")
        set_clock("2026-10-01T00:00:00Z")
        first = file_enforcement_case(
            scenario["client"],
            scenario["candidate"],
            "2026-09-30",
            source_placement=scenario["placement"],
        )
        first = resolve_case(investigate_case(first), "SUBSTANTIATE")
        assert first["penalty_cents"] == 2_512_124

        # The frozen count reads only cases substantiated strictly before this
        # case's investigation_opened_at, so the second file is opened later.
        set_clock("2026-10-02T00:00:00Z")
        second = file_enforcement_case(
            scenario["client"],
            scenario["candidate"],
            "2026-10-01",
            source_placement=scenario["placement"],
            allegation_note="A second approach after the first finding.",
        )
        second = resolve_case(investigate_case(second), "SUBSTANTIATE")
        assert second["status"] == "SUBSTANTIATED"
        assert second["prior_substantiated_count"] == 1
        assert second["penalty_cents"] == 5_024_248
        assert second["penalty_cents"] == 2 * first["penalty_cents"]

        entries = read_ledger(scenario["client"])
        assessed = [
            row["signed_amount_cents"]
            for row in find_ledger_entries(entries, "PENALTY_ASSESSED")
        ]
        assert assessed == [2_512_124, 5_024_248]
        client = read_client(scenario["client"])
        assert client["outstanding_balance_cents"] == 7_536_372
        assert client["status"] == "SUSPENDED"

    def test_07_the_clamp_leaves_both_assessments_untouched(self):
        """Both figures sit strictly inside the floor and the cap.

        PRD §3.9: "Step five: the result is clamped, first raised to the floor of
        750,000 cents and then trimmed to the cap of 7,500,000 cents — $75,000 —
        and stored as `penalty_cents`."

        Design: Difficulty/combinatorial_formula/poaching_penalty_tiers_on_base_then_multiplies_mode_a
        """
        scenario = setup_senior_scenario(stage="placement_active")
        set_clock("2026-10-01T00:00:00Z")
        case = file_enforcement_case(
            scenario["client"],
            scenario["candidate"],
            "2026-09-30",
            source_placement=scenario["placement"],
        )
        case = resolve_case(investigate_case(case), "SUBSTANTIATE")
        assert 750_000 < case["penalty_cents"] < 7_500_000
        stored = api_client.get_non_solicitation_case(
            case["id"], scenario["client_headers"]
        )
        assert stored.status_code == 200
        assert stored.json()["data"]["penalty_cents"] == 2_512_124
