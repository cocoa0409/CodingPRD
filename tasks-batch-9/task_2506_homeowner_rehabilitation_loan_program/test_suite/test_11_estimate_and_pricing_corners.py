"""Money arithmetic at the edges: priority subtotals, the bid band and fee tiers."""

import pytest

from test_helpers import (
    api_client,
    assert_rehab_loan,
    assert_work_write_up,
    assert_write_up_roll_up,
    validate_success,
)
from test_helpers.fixtures import (
    REHAB,
    add_work_item,
    build_contractor,
    build_write_up,
    place_bid,
    refresh_bid,
    refresh_write_up,
    setup_case,
    tabulate,
)

HEALTH_SAFETY_LINE = {
    "description": "Furnace replacement",
    "category": "HVAC",
    "priority_class": "HEALTH_SAFETY",
    "estimated_cost_cents": 1_000_000,
}
CODE_LINE = {
    "description": "Egress window to code",
    "category": "STRUCTURAL",
    "priority_class": "CODE",
    "estimated_cost_cents": 500_000,
}
GENERAL_LINE = {
    "description": "Kitchen cabinet upgrade",
    "category": "ACCESSIBILITY",
    "priority_class": "GENERAL_PROPERTY_IMPROVEMENT",
    "estimated_cost_cents": 800_000,
}
LARGE_HEALTH_SAFETY_LINE = {
    "description": "Whole-house rewiring and service upgrade",
    "category": "ELECTRICAL",
    "priority_class": "HEALTH_SAFETY",
    "estimated_cost_cents": 4_600_000,
}


class TestPrioritySubtotalInputSet:
    """Two aggregates over the same repair lines, with different input sets."""

    @pytest.fixture
    def three_line_write_up(self, inspected_case):
        """A DRAFT scope of one health-and-safety, one code and one general line."""
        write_up = build_write_up(inspected_case["application"]["id"])
        general = add_work_item(write_up["id"], **GENERAL_LINE)
        add_work_item(write_up["id"], **HEALTH_SAFETY_LINE)
        add_work_item(write_up["id"], **CODE_LINE)
        return {"write_up": write_up, "general_line": general}

    def test_the_priority_subtotal_leaves_out_the_general_improvement(
        self, three_line_write_up
    ):
        """The base estimate takes all three lines; the priority subtotal takes two.

        PRD: "`priority_repair_total_cents` is the sum of `line_total_cents`
        restricted to lines whose `priority_class` is `HEALTH_SAFETY` or `CODE`,
        and `work_item_count` is simply the number of lines on the write-up."

        Design: Corner/calculations/priority_repair_total_counts_only_health_safety_and_code_lines
        """
        rolled_up = refresh_write_up(three_line_write_up["write_up"]["id"])

        assert_work_write_up(rolled_up)
        assert rolled_up["work_item_count"] == 3
        assert rolled_up["base_estimate_cents"] == 2_300_000, (
            "1,000,000 plus 500,000 plus 800,000 is the base estimate, got "
            f"{rolled_up['base_estimate_cents']}"
        )
        assert rolled_up["contingency_cents"] == 230_000
        assert rolled_up["total_estimate_cents"] == 2_530_000
        assert rolled_up["priority_repair_total_cents"] == 1_500_000, (
            "Only the health-and-safety and code lines count toward the priority "
            f"subtotal, got {rolled_up['priority_repair_total_cents']}"
        )
        assert_write_up_roll_up(rolled_up)

    def test_dropping_the_general_line_moves_the_base_but_not_the_subtotal(
        self, three_line_write_up
    ):
        """Removing a line outside the priority set leaves that subtotal untouched.

        PRD: "All five figures are recomputed whenever a line is added or removed,
        and again when the write-up is submitted, and each recomputation advances
        the write-up's `version` by one."

        Design: Corner/calculations/priority_repair_total_counts_only_health_safety_and_code_lines
        """
        write_up_id = three_line_write_up["write_up"]["id"]

        response = api_client.delete_work_item(
            three_line_write_up["general_line"]["id"], REHAB
        )

        assert response.status_code == 204, (
            f"Removal answers 204, got {response.status_code}: {response.text}"
        )
        rolled_up = refresh_write_up(write_up_id)
        assert rolled_up["work_item_count"] == 2
        assert rolled_up["base_estimate_cents"] == 1_500_000, (
            "The base estimate loses the 800,000 general line, got "
            f"{rolled_up['base_estimate_cents']}"
        )
        assert rolled_up["contingency_cents"] == 150_000
        assert rolled_up["total_estimate_cents"] == 1_650_000
        assert rolled_up["priority_repair_total_cents"] == 1_500_000, (
            "The priority subtotal never held the general line, so it does not "
            f"move, got {rolled_up['priority_repair_total_cents']}"
        )
        assert_write_up_roll_up(rolled_up)


class TestResponsivenessBandBoundaries:
    """The band brackets the independent cost estimate, and both bounds are inclusive."""

    @pytest.fixture
    def two_bid_case(self):
        """A solicitation on a 2,200,000 estimate awaiting two bids."""
        return setup_case(
            stage="bid_open", solicitation_overrides={"min_bids_required": 2}
        )

    def test_a_bid_exactly_at_the_ceiling_is_responsive_and_one_cent_over_is_not(
        self, two_bid_case
    ):
        """2,420,000 is inside the window; 2,420,001 is one cent outside it.

        PRD: "`responsive_ceiling_cents` is the independent cost estimate
        increased by ten percent — the estimate multiplied by 1.10 — rounded half
        up to whole cents."

        PRD: "Both bounds are inclusive: a bid exactly at the ceiling or exactly
        at the floor is responsive."

        Design: Corner/calculations/responsive_band_constants_admit_a_bid_exactly_at_the_ceiling
        """
        case = two_bid_case
        solicitation = case["solicitation"]
        assert solicitation["independent_cost_estimate_cents"] == 2_200_000
        assert solicitation["responsive_ceiling_cents"] == 2_420_000
        assert solicitation["responsive_floor_cents"] == 1_650_000
        at_ceiling = place_bid(
            solicitation["id"], case["contractor"]["id"], amount_cents=2_420_000
        )
        over_ceiling = place_bid(
            solicitation["id"],
            build_contractor(legal_name="Borough Builders Inc")["id"],
            amount_cents=2_420_001,
            proposed_start_date="2026-09-06",
            proposed_end_date="2026-11-15",
        )

        tabulated = tabulate(solicitation["id"])

        assert tabulated["status"] == "TABULATED"
        assert refresh_bid(at_ceiling["id"])["status"] == "RESPONSIVE", (
            "A bid exactly at the 2,420,000 ceiling is responsive"
        )
        assert refresh_bid(at_ceiling["id"])["rank"] == 1
        rejected = refresh_bid(over_ceiling["id"])
        assert rejected["status"] == "NON_RESPONSIVE", (
            "One cent above the ceiling leaves the window, got "
            f"{rejected['status']}"
        )
        assert rejected["non_responsive_reason"] == "OVER_CEILING"
        assert tabulated["bid_count"] == 2
        assert tabulated["responsive_bid_count"] == 1

    def test_a_bid_exactly_at_the_floor_is_responsive_and_one_cent_under_is_not(
        self, two_bid_case
    ):
        """1,650,000 is inside the window; 1,649,999 is one cent below it.

        PRD: "`responsive_floor_cents` is the independent cost estimate reduced
        by twenty-five percent — the estimate multiplied by 0.75 — rounded half up
        to whole cents."

        PRD: "Otherwise, when `amount_cents` is strictly less than
        `responsive_floor_cents`, the reason is `UNDER_FLOOR`."

        Design: Corner/calculations/responsive_band_constants_admit_a_bid_exactly_at_the_ceiling
        """
        case = two_bid_case
        solicitation = case["solicitation"]
        at_floor = place_bid(
            solicitation["id"], case["contractor"]["id"], amount_cents=1_650_000
        )
        under_floor = place_bid(
            solicitation["id"],
            build_contractor(legal_name="Borough Builders Inc")["id"],
            amount_cents=1_649_999,
            proposed_start_date="2026-09-06",
            proposed_end_date="2026-11-15",
        )

        tabulated = tabulate(solicitation["id"])

        assert tabulated["status"] == "TABULATED"
        assert refresh_bid(at_floor["id"])["status"] == "RESPONSIVE", (
            "A bid exactly at the 1,650,000 floor is responsive"
        )
        rejected = refresh_bid(under_floor["id"])
        assert rejected["status"] == "NON_RESPONSIVE", (
            "The cheaper-looking 1,649,999 bid is out of band, got "
            f"{rejected['status']}"
        )
        assert rejected["non_responsive_reason"] == "UNDER_FLOOR"
        assert rejected.get("rank") in (None, ""), (
            "A non-responsive bid carries no rank"
        )
        assert tabulated["responsive_bid_count"] == 1


class TestTieredRecordingFee:
    """The financed recording fee is a step schedule on the pre-fee project cost."""

    @pytest.mark.parametrize(
        "awarded_amount_cents, expected_fee_cents, expected_principal_cents",
        [
            (5_000_000, 25_000, 5_025_000),
            (5_000_001, 40_000, 5_040_001),
        ],
    )
    def test_one_cent_above_fifty_thousand_dollars_moves_up_a_fee_tier(
        self, awarded_amount_cents, expected_fee_cents, expected_principal_cents
    ):
        """A contract at 5,000,000 draws 25,000; a cent more draws 40,000.

        PRD: "`lien_recording_fee_cents` is chosen once from the pre-fee project
        cost: a project cost at or below twenty thousand dollars — 2,000,000 cents
        — carries a fee of one hundred and fifty dollars, or 15,000 cents; a
        project cost above that and at or below fifty thousand dollars —
        5,000,000 cents — carries a fee of two hundred and fifty dollars, or
        25,000 cents; a project cost above fifty thousand dollars carries a fee of
        four hundred dollars, or 40,000 cents."

        Design: Corner/calculations/recording_fee_tier_flips_one_cent_above_five_million
        """
        case = setup_case(
            stage="structured",
            lines=[dict(LARGE_HEALTH_SAFETY_LINE)],
            bid_amount_cents=awarded_amount_cents,
            loan_overrides={
                "structure_type": "DEFERRED",
                "forgiveness_term_months": 60,
            },
        )

        loan = case["loan"]

        assert_rehab_loan(loan)
        assert loan["awarded_bid_amount_cents"] == awarded_amount_cents
        assert loan["approved_project_cost_cents"] == awarded_amount_cents
        assert loan["lien_recording_fee_cents"] == expected_fee_cents, (
            f"A pre-fee cost of {awarded_amount_cents} draws a "
            f"{expected_fee_cents} fee, got {loan['lien_recording_fee_cents']}"
        )
        assert loan["principal_cents"] == expected_principal_cents
        assert loan["status"] == "STRUCTURED"

    def test_the_fee_is_financed_into_the_principal_and_not_re_derived_from_it(self):
        """The 5,040,001 principal is above the tier line but the fee stays at 40,000.

        PRD: "`principal_cents` is the lesser of two figures: the project cost
        plus the recording fee, and the program year's `max_loan_amount_cents`."

        Design: Corner/calculations/recording_fee_tier_flips_one_cent_above_five_million
        """
        case = setup_case(
            stage="structured",
            lines=[dict(LARGE_HEALTH_SAFETY_LINE)],
            bid_amount_cents=5_000_001,
            loan_overrides={
                "structure_type": "DEFERRED",
                "forgiveness_term_months": 60,
            },
        )

        loan = case["loan"]

        assert loan["principal_cents"] == 5_040_001, (
            "The 40,000 fee rides inside the note, got "
            f"{loan['principal_cents']}"
        )
        assert loan["lien_recording_fee_cents"] == 40_000
        assert loan["monthly_payment_cents"] == 0, (
            "A deferred note carries no amortised payment, got "
            f"{loan['monthly_payment_cents']}"
        )
        assert loan["unforgiven_balance_cents"] == 5_040_001
        assert loan["disbursed_cents"] == 0
        assert case["program_year"]["committed_amount_cents"] == 0, (
            "Structuring commits nothing to the program year"
        )

    def test_a_contract_at_the_twenty_thousand_dollar_line_draws_the_bottom_tier(self):
        """A 2,000,000 contract is at the first tier's boundary, so the fee is 15,000.

        PRD: "That tier is locked at structuring: the fee is never re-chosen after
        it has been added into the principal, is never re-chosen because the
        per-household cap bound the principal, and is never re-chosen when a
        change order later moves the project cost."

        Design: Corner/calculations/recording_fee_tier_flips_one_cent_above_five_million
        """
        case = setup_case(
            stage="structured",
            bid_amount_cents=2_000_000,
            loan_overrides={
                "structure_type": "DEFERRED",
                "forgiveness_term_months": 60,
            },
        )

        loan = case["loan"]

        assert loan["approved_project_cost_cents"] == 2_000_000
        assert loan["lien_recording_fee_cents"] == 15_000, (
            "2,000,000 sits at the top of the bottom tier, got "
            f"{loan['lien_recording_fee_cents']}"
        )
        assert loan["principal_cents"] == 2_015_000
        assert loan["monthly_payment_cents"] == 0
        assert loan["status"] == "STRUCTURED"
