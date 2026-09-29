"""Pinned evaluation orders: parts rounding, audit extrapolation, labor-rate ceilings."""
import pytest

from test_helpers import (
    approve_claim,
    assert_date_equals,
    assert_instant_equals,
    assert_ratio_four_decimals,
    assert_whole_cents,
    create_dealer,
    create_rate_request,
    create_state_law_profile,
    get_claim,
    get_dealer,
    get_finding,
    issue_findings,
    list_ledger_entries,
    set_clock,
    setup_audit_with_findings,
    setup_claim,
)

CA_PROFILE = {
    "state_code": "CA",
    "markup_cap_pct": 0.30,
    "labor_rate_method": "RETAIL_SAMPLE",
    "min_sample_repair_orders": 5,
    "max_labor_rate_cents": 19500,
    "deemed_approved_days": 30,
    "appeal_window_days": 30,
}

TX_PROFILE = {
    "state_code": "TX",
    "markup_cap_pct": 0.25,
    "labor_rate_method": "TIME_AND_PRICE",
    "min_sample_repair_orders": 0,
    "max_labor_rate_cents": 16000,
    "deemed_approved_days": 15,
    "appeal_window_days": 20,
}

BRAKE_OPERATION = {
    "op_code": "A1234-56",
    "description": "Front brake pad replacement",
    "standard_time_hours": 1.5,
    "max_time_hours": 2.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "BRAKE_FRONT",
    "overlap_group": "BRAKE_FRONT",
}

BRAKE_PART = {
    "part_number": "BRK-PAD-9931",
    "description": "Front brake pad set",
    "dealer_net_cents": 24799,
    "failure_group": "BRAKE_FRONT",
    "return_required": True,
    "retention_days": 30,
}

COVERED_TERMS = {
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

BRAKE_CLAIM = {
    "repair_order_number": "RO-1001",
    "repair_date": "2026-04-10",
    "odometer_at_repair": 20000,
    "claimed_labor_hours": 1.5,
    "claimed_parts_qty": 3,
    "complaint_text": "Customer reports brake squeal at low speed.",
    "cause_text": "Front brake pads worn beyond specification.",
    "correction_text": "Replaced front brake pads and verified normal braking.",
}

ELEC_OPERATION = {
    "op_code": "AUD-100",
    "description": "Electrical harness repair",
    "standard_time_hours": 2.0,
    "max_time_hours": 3.0,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "ELEC",
    "overlap_group": "ELEC",
}

ELEC_PART = {
    "part_number": "AUD-P1",
    "description": "Electrical harness",
    "dealer_net_cents": 24000,
    "failure_group": "ELEC",
    "return_required": False,
    "retention_days": 0,
}

ELEC_NARRATIVE = {
    "complaint_text": "Customer reports intermittent electrical fault.",
    "cause_text": "Harness chafed through insulation layer.",
    "correction_text": "Replaced the electrical harness assembly.",
}


def build_penny_fork_claim():
    """CA dealer at rate 13750 / markup 0.40 with a 24,799-cent part at quantity three."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides={
            "dealer_code": "D1",
            "name": "Dealer One",
            "vehicles_in_operation": 100,
            "initial_labor_rate_cents": 13750,
            "initial_parts_markup_pct": 0.40,
        },
        vehicle_overrides=COVERED_TERMS,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
        claim_overrides=BRAKE_CLAIM,
    )
    assert world["claim"]["status"] == "SUBMITTED"
    return world


def build_extrapolation_audit():
    """Three paid 50,000-cent claims, two of them sampled and carrying 40,000 of findings."""
    set_clock("2026-05-01T00:00:00Z")
    specs = [
        {
            "claim": dict(
                ELEC_NARRATIVE,
                repair_order_number="RO-A1",
                repair_date="2026-01-05",
                odometer_at_repair=11000,
                claimed_labor_hours=2.0,
                claimed_parts_qty=1,
            ),
            "approve": {"approved_labor_hours": 2.0, "approved_parts_qty": 1},
            "pay": True,
        },
        {
            "claim": dict(
                ELEC_NARRATIVE,
                repair_order_number="RO-A2",
                repair_date="2026-02-10",
                odometer_at_repair=13000,
                claimed_labor_hours=2.0,
                claimed_parts_qty=1,
            ),
            "approve": {"approved_labor_hours": 2.0, "approved_parts_qty": 1},
            "pay": True,
        },
        {
            "claim": dict(
                ELEC_NARRATIVE,
                repair_order_number="RO-A3",
                repair_date="2026-03-20",
                odometer_at_repair=15000,
                claimed_labor_hours=2.0,
                claimed_parts_qty=1,
            ),
            "approve": {"approved_labor_hours": 2.0, "approved_parts_qty": 1},
            "pay": True,
        },
    ]
    world = setup_audit_with_findings(
        specs,
        [
            {
                "claim_index": 0,
                "unsupported_amount_cents": 30000,
                "finding_code": "NO_REPAIR_ORDER",
                "evidence_note": "No repair order on file for this claim.",
            },
            {
                "claim_index": 1,
                "unsupported_amount_cents": 10000,
                "finding_code": "TIME_NOT_DOCUMENTED",
                "evidence_note": "Technician time is not documented on the order.",
            },
        ],
        audit_overrides={
            "period_start": "2026-01-01",
            "period_end": "2026-07-01",
            "sample_size": 2,
            "lead_auditor_user_id": "auditor-lead-1",
        },
        profile_overrides=CA_PROFILE,
        dealer_overrides={
            "dealer_code": "D-AUD",
            "name": "Audit Dealer",
            "vehicles_in_operation": 100,
            "initial_labor_rate_cents": 10000,
            "initial_parts_markup_pct": 0.25,
        },
        operation_overrides=ELEC_OPERATION,
        part_overrides=ELEC_PART,
        vehicle_overrides=COVERED_TERMS,
    )
    for claim in world["claims"]:
        assert claim["approved_total_cents"] == 50000
        assert claim["payment_status"] == "PAID"
    return world


class TestPartsRoundingOrder:
    def test_01_provisional_parts_round_the_unit_price_before_multiplying_by_quantity(self):
        """PRD §3.4: "Parts are priced with a **pinned rounding order** that must be implemented exactly as stated, because the alternative order produces a different number of cents."
        PRD §3.4: "First, take the catalog part's `dealer_net_cents`, multiply it by one plus the markup fraction, and round that *unit* price half up to a whole cent."
        PRD §3.4: "Rounding after the multiplication instead of before it is forbidden: with a dealer net price of 24,799 cents, a markup of 0.40 and a quantity of three, the pinned order gives a unit price of 34,719 cents and a parts amount of 104,157 cents, whereas rounding the whole product would give 104,156 cents — a cent low."

        Design: Difficulty/combinatorial_formula/parts_amount_rounding_before_quantity_multiply_order
        """
        world = build_penny_fork_claim()
        claim = world["claim"]

        assert_whole_cents(
            claim["provisional_parts_amount_cents"], "provisional_parts_amount_cents"
        )
        assert claim["provisional_parts_amount_cents"] == 104157, (
            "the pinned order rounds 24799 * 1.40 to a 34719-cent unit price and only then "
            "multiplies by three; rounding the whole product gives 104156, a cent low"
        )
        assert claim["provisional_parts_amount_cents"] != 104156
        # Unit-first rounding leaves the parts amount an exact multiple of the quantity.
        assert claim["provisional_parts_amount_cents"] % 3 == 0
        assert claim["provisional_parts_amount_cents"] // 3 == 34719
        assert claim["provisional_labor_amount_cents"] == 20625
        assert claim["provisional_total_cents"] == 124782

    def test_02_the_same_penny_fork_repeats_on_the_capped_markup_branch(self):
        """PRD §3.4: "Then multiply the rounded unit price by the quantity as an exact integer multiplication, with no further rounding."
        PRD §3.6: "The markup is the lesser of the dealer's `approved_parts_markup_pct` and the governing statute's `markup_cap_pct`, so a grandfathered markup is finally trimmed to what state law allows."
        PRD §3.6: "Labor is multiplied and rounded half up once to give `approved_labor_amount_cents`; the marked-up unit price is rounded half up once and then multiplied by the quantity to give `approved_parts_amount_cents`, which is 0 when the claim names no causal part; and their sum is the unadjusted total, with no further rounding."

        Design: Difficulty/combinatorial_formula/parts_amount_rounding_before_quantity_multiply_order
        """
        world = build_penny_fork_claim()

        approved = approve_claim(
            world["claim"]["id"], approved_labor_hours=1.5, approved_parts_qty=3
        )

        assert approved["status"] == "APPROVED"
        assert_whole_cents(
            approved["approved_parts_amount_cents"], "approved_parts_amount_cents"
        )
        # 24799 * 1.30 = 32238.7 -> 32239 per unit -> 96717 for three units.
        assert approved["approved_parts_amount_cents"] == 96717, (
            "the capped 0.30 branch forks the same way: rounding the whole product gives "
            "96716 instead of the pinned 96717"
        )
        assert approved["approved_parts_amount_cents"] != 96716
        assert approved["approved_parts_amount_cents"] % 3 == 0
        assert approved["approved_parts_amount_cents"] // 3 == 32239
        assert approved["approved_labor_amount_cents"] == 20625
        assert approved["approved_total_cents"] == 117342


class TestAuditExtrapolationOrder:
    def test_03_both_denominators_are_pinned_before_the_sampled_claims_are_debited(self):
        """PRD §3.8: "`sample_paid_snapshot_cents` is the sum of `approved_total_cents` over every claim that is named by one of this audit's findings, belongs to the audited dealer, is in `APPROVED`, has `payment_status` `PAID` at this instant — before any chargeback has touched it — and has a `repair_date` inside the half-open period."
        PRD §3.8: "The second step pins the unsampled remainder: the same sum is taken over every claim of the dealer in `APPROVED` with `payment_status` `PAID` and a `repair_date` inside the period regardless of whether a finding names it, and `population_paid_snapshot_cents` is that figure less `sample_paid_snapshot_cents`."
        PRD §3.8: "The fourth step derives `error_rate`: when the pinned sampled denominator is zero the rate is zero, and otherwise it is `sample_chargeback_cents` divided by `sample_paid_snapshot_cents`, rounded half up to four decimal places."
        PRD §3.8: "The sixth step multiplies `population_paid_snapshot_cents` by `error_rate` and then by `extrapolation_factor`, rounds that product half up to whole cents as `extrapolated_chargeback_cents`, and sets `total_chargeback_cents` to `sample_chargeback_cents` plus `extrapolated_chargeback_cents`."

        Design: Difficulty/combinatorial_formula/audit_extrapolation_pinned_six_step_evaluation_order
        """
        world = build_extrapolation_audit()

        audit = issue_findings(world["audit"]["id"])

        assert audit["sample_paid_snapshot_cents"] == 100000, (
            "the sampled denominator is captured while both sampled claims are still PAID"
        )
        assert audit["population_paid_snapshot_cents"] == 50000, (
            "the unsampled remainder is the 150000 in-period paid total less the 100000 "
            "sample, not the whole population"
        )
        assert audit["sample_chargeback_cents"] == 40000
        assert_ratio_four_decimals(audit["error_rate"], "error_rate")
        assert audit["error_rate"] == 0.4000
        assert audit["extrapolation_factor"] == 1.00
        assert audit["extrapolated_chargeback_cents"] == 20000
        assert audit["total_chargeback_cents"] == 60000
        assert audit["status"] == "FINDINGS_ISSUED"
        assert_instant_equals(
            audit["findings_issued_at"], "2026-05-01T00:00:00Z", "findings_issued_at"
        )
        assert_date_equals(audit["appeal_deadline"], "2026-05-31", "appeal_deadline")

    def test_04_the_pinned_totals_drive_the_findings_claims_and_ledger_rows(self):
        """PRD §3.8: "`sample_chargeback_cents` is the sum of `unsupported_amount_cents` over this audit's findings whose `status` is `OPEN`, `CHARGED_BACK` or `UPHELD`; findings in `OVERTURNED` are excluded."
        PRD §3.8: "One ledger row with `source_type` `AUDIT_CHARGEBACK_SAMPLE` is appended per charged-back finding, each carrying that finding's `claim_id` and its positive `unsupported_amount_cents`, so the sampled rows sum to `sample_chargeback_cents`."
        PRD §3.8: "Then, and only when `extrapolated_chargeback_cents` is greater than zero, a single further row with `source_type` `AUDIT_CHARGEBACK_EXTRAPOLATION` is appended for that positive amount with its `claim_id` left null, because extrapolated money is by construction not attributable to any one claim."

        Design: Difficulty/combinatorial_formula/audit_extrapolation_pinned_six_step_evaluation_order
        """
        world = build_extrapolation_audit()

        issue_findings(world["audit"]["id"])

        assert get_finding(world["findings"][0]["id"])["status"] == "CHARGED_BACK"
        assert get_finding(world["findings"][1]["id"])["status"] == "CHARGED_BACK"

        sampled_one = get_claim(world["claims"][0]["id"])
        sampled_two = get_claim(world["claims"][1]["id"])
        untouched = get_claim(world["claims"][2]["id"])
        assert sampled_one["payment_status"] == "DEBITED"
        assert sampled_one["debited_amount_cents"] == 30000
        assert sampled_two["payment_status"] == "DEBITED"
        assert sampled_two["debited_amount_cents"] == 10000
        assert untouched["payment_status"] == "PAID"
        assert untouched["debited_amount_cents"] == 0

        entries = list_ledger_entries(world["dealer"]["id"])
        sample_rows = [
            row for row in entries if row["source_type"] == "AUDIT_CHARGEBACK_SAMPLE"
        ]
        extrapolation_rows = [
            row
            for row in entries
            if row["source_type"] == "AUDIT_CHARGEBACK_EXTRAPOLATION"
        ]
        assert len(sample_rows) == 2
        assert sum(row["amount_cents"] for row in sample_rows) == 40000
        assert {row["claim_id"] for row in sample_rows} == {
            world["claims"][0]["id"],
            world["claims"][1]["id"],
        }
        assert len(extrapolation_rows) == 1
        assert extrapolation_rows[0]["amount_cents"] == 20000
        assert extrapolation_rows[0]["claim_id"] is None

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 60000
        assert dealer["status"] == "ACTIVE"


class TestLaborRateCeilingNestedBinding:
    def test_05_each_of_the_three_retail_sample_terms_binds_at_a_different_dealer_rate(self):
        """PRD §3.2: "Under the retail-sample method the server first works out a step-up floor by taking the dealer's currently approved hourly rate, increasing it by twenty-five percent, and rounding the product half up to whole cents; it then takes the greater of the cited sample median and that step-up floor; and it finally takes the lesser of that result and the statute's absolute `max_labor_rate_cents`."
        PRD §3.2: "The ceiling itself is written into `statutory_ceiling_cents` at creation and never recomputed thereafter."

        Design: Difficulty/combinatorial_formula/labor_rate_ceiling_nested_min_max_three_way_binding
        """
        set_clock("2026-05-01T00:00:00Z")
        profile = create_state_law_profile(**CA_PROFILE)
        median_bound = create_dealer(
            profile["id"],
            dealer_code="D-CEIL1",
            name="Ceiling Dealer One",
            vehicles_in_operation=50,
            initial_labor_rate_cents=13750,
            initial_parts_markup_pct=0.30,
        )
        step_up_bound = create_dealer(
            profile["id"],
            dealer_code="D-CEIL2",
            name="Ceiling Dealer Two",
            vehicles_in_operation=50,
            initial_labor_rate_cents=15000,
            initial_parts_markup_pct=0.30,
        )
        cap_bound = create_dealer(
            profile["id"],
            dealer_code="D-CEIL3",
            name="Ceiling Dealer Three",
            vehicles_in_operation=50,
            initial_labor_rate_cents=16000,
            initial_parts_markup_pct=0.30,
        )

        first = create_rate_request(
            median_bound,
            requested_labor_rate_cents=17600,
            requested_parts_markup_pct=0.30,
            sample_repair_order_count=5,
            sample_median_rate_cents=17600,
            effective_date="2026-06-01",
        )
        second = create_rate_request(
            step_up_bound,
            requested_labor_rate_cents=18750,
            requested_parts_markup_pct=0.30,
            sample_repair_order_count=5,
            sample_median_rate_cents=17600,
            effective_date="2026-06-01",
        )
        third = create_rate_request(
            cap_bound,
            requested_labor_rate_cents=19500,
            requested_parts_markup_pct=0.30,
            sample_repair_order_count=5,
            sample_median_rate_cents=17600,
            effective_date="2026-06-01",
        )

        # 13750 * 1.25 = 17187.5 -> 17188 step-up floor, so the 17600 median is the greater.
        assert first["statutory_ceiling_cents"] == 17600
        # 15000 * 1.25 = 18750 step-up floor now beats the same 17600 median.
        assert second["statutory_ceiling_cents"] == 18750
        # 16000 * 1.25 = 20000 step-up floor is clipped by max_labor_rate_cents 19500.
        assert third["statutory_ceiling_cents"] == 19500
        for request in (first, second, third):
            assert_whole_cents(
                request["statutory_ceiling_cents"], "statutory_ceiling_cents"
            )

    def test_06_the_time_and_price_branch_applies_a_ten_percent_step_and_ignores_the_median(self):
        """PRD §3.2: "Under the time-and-price method there is no sample to consider: the server increases the dealer's currently approved hourly rate by ten percent, rounds the product half up to whole cents, and takes the lesser of that figure and the statute's absolute maximum."
        PRD §3.2: "The request opens in `SUBMITTED` with `deemed_approved` false, and the petitioning dealer's `version` advances by 1."

        Design: Difficulty/combinatorial_formula/labor_rate_ceiling_nested_min_max_three_way_binding
        """
        set_clock("2026-05-01T00:00:00Z")
        profile = create_state_law_profile(**TX_PROFILE)
        dealer = create_dealer(
            profile["id"],
            dealer_code="D-TX",
            name="Texas Dealer",
            vehicles_in_operation=50,
            initial_labor_rate_cents=10000,
            initial_parts_markup_pct=0.25,
        )

        request = create_rate_request(
            dealer,
            requested_labor_rate_cents=11000,
            requested_parts_markup_pct=0.25,
            sample_repair_order_count=5,
            sample_median_rate_cents=17600,
            effective_date="2026-06-01",
        )

        # 10000 * 1.10 = 11000, below the 16000 statutory maximum; the cited 17600 median
        # is never consulted on this branch.
        assert request["statutory_ceiling_cents"] == 11000
        assert request["status"] == "SUBMITTED"
        assert request["deemed_approved"] is False
        assert get_dealer(dealer["id"])["version"] == dealer["version"] + 1
