"""Two figures from one dataset: valuation variants and coverage bases.

PRD §3.6 makes a single valuation record carry both a pre-accrual disclosure
figure and the official transaction price, and PRD §3.7 makes a single
declaration disclose coverage on a GAAP basis and on a cash-flow basis at once.
The tests below pin both members of each pair on the same row, because a
service that computes only one of them and reuses it for the other is
indistinguishable from a correct one until the two figures are forced apart.
"""

from __future__ import annotations

from test_helpers import (
    SPONSOR,
    ApiClient,
    ClassCode,
    DeclarationStatus,
    NavRecordStatus,
    assert_created,
    assert_fields,
    declaration_payload,
    nav_record_payload,
)
from test_helpers.fixtures import ReitWorld

# The two stockholders of the Cornerstone scenario and the three of Harborline.
_CORNERSTONE_HOLDERS = (
    ("Avery Nolan", "avery.nolan@example.com", "SUIT-A-2026-08"),
    ("Blake Ortiz", "blake.ortiz@example.com", "SUIT-B-2026-08"),
)

_HARBORLINE_HOLDERS = (
    ("Avery Nolan", "avery.nolan@example.com", "SUIT-A-2026-08"),
    ("Blake Ortiz", "blake.ortiz@example.com", "SUIT-B-2026-08"),
    ("Casey Rivera", "casey.rivera@example.com", "SUIT-C-2026-08"),
)


def _cornerstone_with_unpaid_declaration(world: ReitWorld) -> dict:
    """Class T holding 193,000,000 e4 plus one still-DECLARED distribution.

    Two 10,000,000-cent tickets into a 300 + 50 bps class at the 1000-cent
    initial price each buy 96,500,000 e4, and the August declaration of 5 cents
    a share is left unpaid so that it sits in the accrual of any valuation
    record prepared afterwards (PRD §3.6, §3.7).
    """
    offering = world.offering(
        name="Cornerstone Income REIT",
        minimum_offering_amount_cents=20000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        rescission_window_days=5,
    )
    share_class = world.share_class(
        offering["id"],
        class_code=ClassCode.T,
        upfront_selling_commission_bps=300,
        dealer_manager_fee_bps=50,
        annual_distribution_fee_bps=850,
        distribution_fee_cap_bps=875,
        converts_to_class_code=ClassCode.I,
    )
    firm = world.broker_dealer(
        firm_name="Meridian Securities LLC", crd_number="CRD-100001"
    )
    agreement = world.selling_agreement(
        offering["id"],
        firm["id"],
        max_commission_bps=500,
        suitability_documentation_required=True,
    )
    world.declare_effective(offering["id"])
    world.activate_agreement(agreement["id"])

    holders = []
    for legal_name, email, reference in _CORNERSTONE_HOLDERS:
        holder = world.investor(
            legal_name=legal_name,
            email=email,
            state_code="TX",
            net_worth_cents=500000000,
            annual_income_cents=100000000,
        )
        world.document_suitability(holder["id"], reference)
        holders.append(holder)

    for holder in holders:
        subscription = world.subscription(
            offering["id"],
            share_class["id"],
            holder["id"],
            agreement["id"],
            10000000,
        )
        world.escrow_subscription(subscription["id"])

    world.break_escrow(offering["id"])
    world.set_clock("2026-09-02T00:00:00Z", SPONSOR)

    declaration = world.declaration(
        offering["id"],
        record_date="2026-08-31",
        payment_date="2026-09-15",
        declared_per_share_cents=5,
        gaap_net_income_cents=60000,
        adjusted_cash_flow_cents=96500,
        board_uncovered_acknowledgement=False,
    )
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "declaration": declaration,
    }


def _prepare_august_valuation(world: ReitWorld, api: ApiClient, share_class_id: str) -> dict:
    """Prepare the August record over a 20,000,000-cent appraisal, 1,000,000 of liabilities."""
    response = api.create_nav_record(
        nav_record_payload(
            share_class_id,
            world.share_class_version(share_class_id),
            period_start_date="2026-08-01",
            period_end_date="2026-08-31",
            gross_asset_value_cents=20000000,
            other_liabilities_cents=1000000,
        ),
        SPONSOR,
    )
    return assert_created(response)


def _harborline_priced_offering(world: ReitWorld) -> dict:
    """Class I holding 300,000,000 e4 with a PUBLISHED August valuation of 1000 cents."""
    offering = world.offering(
        name="Harborline Diversified REIT",
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        rescission_window_days=5,
    )
    share_class = world.share_class(
        offering["id"],
        class_code=ClassCode.I,
        upfront_selling_commission_bps=0,
        dealer_manager_fee_bps=0,
        annual_distribution_fee_bps=0,
        distribution_fee_cap_bps=0,
    )
    firm = world.broker_dealer(
        firm_name="Keystone Advisory Group", crd_number="CRD-200001"
    )
    agreement = world.selling_agreement(
        offering["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    world.declare_effective(offering["id"])
    world.activate_agreement(agreement["id"])

    holders = []
    for legal_name, email, reference in _HARBORLINE_HOLDERS:
        holder = world.investor(
            legal_name=legal_name,
            email=email,
            state_code="TX",
            net_worth_cents=2000000000,
            annual_income_cents=400000000,
        )
        world.document_suitability(holder["id"], reference)
        holders.append(holder)

    for holder in holders:
        subscription = world.subscription(
            offering["id"],
            share_class["id"],
            holder["id"],
            agreement["id"],
            10000000,
        )
        world.escrow_subscription(subscription["id"])

    world.break_escrow(offering["id"])
    world.set_clock("2026-09-02T00:00:00Z", SPONSOR)
    nav_record = world.published_nav(
        share_class["id"], "2026-08-01", "2026-08-31", 30900000, 900000, "IVA-2026-08-I"
    )
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "nav_record": nav_record,
    }


def _declare(api: ApiClient, world: ReitWorld, offering_id: str, **overrides) -> dict:
    """Author an August-record-date declaration of 5 cents a share."""
    payload = declaration_payload(
        offering_id,
        world.offering_version(offering_id),
        record_date="2026-08-31",
        payment_date="2026-09-15",
        declared_per_share_cents=5,
    )
    payload.update(overrides)
    return assert_created(api.create_distribution_declaration(payload, SPONSOR))


class TestValuationPreAccrualAndOfficialVariants:
    """One valuation row must carry both per-share figures, not one reused twice."""

    def test_accrual_of_unpaid_declaration_is_snapshotted_alongside_the_share_count(
        self, api: ApiClient, world: ReitWorld
    ):
        """The record snapshots the class's outstanding shares and sums the unpaid declarations.

        PRD §3.6: "The record snapshots `shares_outstanding_e4_snapshot` from the class's `shares_outstanding_e4` at the instant of creation, and computes `accrued_distribution_payable_cents` as the sum of `total_declared_cents` across every declaration of the class's offering that is currently `DECLARED` and whose `record_date` falls on or before this record's `period_end_date`."

        PRD §3.7: "The declared total is built class by class: `total_declared_cents` is the sum, over every share class of the offering, of the `declared_per_share_cents` multiplied by that class's `shares_outstanding_e4`, divided by 10,000 and rounded half up to a whole cent — again each class's contribution rounded independently before summation."

        Design: Difficulty/dual_variant_calc/nav_pre_accrual_vs_official_transaction_price
        """
        scene = _cornerstone_with_unpaid_declaration(world)

        assert_fields(scene["declaration"], total_declared_cents=96500)

        record = _prepare_august_valuation(world, api, scene["share_class_id"])
        assert_fields(
            record,
            shares_outstanding_e4_snapshot=193000000,
            accrued_distribution_payable_cents=96500,
        )

    def test_disclosure_variant_ignores_the_accrual_that_the_official_variant_subtracts(
        self, api: ApiClient, world: ReitWorld
    ):
        """Both per-share figures come off one appraisal and differ by the accrual per share.

        PRD §3.6: "Net assets before the distribution accrual are the gross asset value less the other liabilities; net assets after it are that same figure less the accrued distribution payable."

        PRD §3.6: "Otherwise `nav_per_share_pre_accrual_cents` is the pre-accrual net assets multiplied by 10,000, divided by the snapshotted share count and rounded half up to a whole cent, while `nav_per_share_cents` is the post-accrual net assets multiplied by 10,000, divided by the same snapshotted share count and rounded half up."

        Design: Difficulty/dual_variant_calc/nav_pre_accrual_vs_official_transaction_price
        """
        scene = _cornerstone_with_unpaid_declaration(world)

        record = _prepare_august_valuation(world, api, scene["share_class_id"])

        assert_fields(
            record,
            nav_per_share_pre_accrual_cents=984,
            nav_per_share_cents=979,
        )
        gap = record["nav_per_share_pre_accrual_cents"] - record["nav_per_share_cents"]
        assert gap == 5, (
            "the 96,500-cent accrual over 193,000,000 e4 must separate the two "
            f"variants by exactly 5 cents, got {gap}"
        )

    def test_first_valuation_of_a_class_opens_in_draft_with_zero_variance(
        self, api: ApiClient, world: ReitWorld
    ):
        """With no prior published record the variance is zero and the row is untouched by review.

        PRD §3.6: "When no prior published record exists, `variance_bps` is zero."

        PRD §3.6: "New records open in `DRAFT` with a null `advisor_opinion_reference` and a null `rejection_reason`."

        Design: Difficulty/dual_variant_calc/nav_pre_accrual_vs_official_transaction_price
        """
        scene = _cornerstone_with_unpaid_declaration(world)

        record = _prepare_august_valuation(world, api, scene["share_class_id"])

        assert_fields(
            record,
            variance_bps=0,
            status=NavRecordStatus.DRAFT,
            advisor_opinion_reference=None,
            rejection_reason=None,
        )


class TestDistributionCoverageOnBothAccountingBases:
    """One declared total measured against two numerators, with only cash flow gating."""

    def test_one_declared_total_yields_a_gaap_ratio_and_a_cash_flow_ratio(
        self, api: ApiClient, world: ReitWorld
    ):
        """The same 150,000-cent total produces 6000 bps of GAAP coverage and 9000 bps of cash coverage.

        PRD §3.7: "The declared total is built class by class: `total_declared_cents` is the sum, over every share class of the offering, of the `declared_per_share_cents` multiplied by that class's `shares_outstanding_e4`, divided by 10,000 and rounded half up to a whole cent — again each class's contribution rounded independently before summation."

        PRD §3.7: "`coverage_ratio_gaap_bps` is `gaap_net_income_cents` multiplied by 10,000, divided by `total_declared_cents` and floored to whole basis points."

        PRD §3.7: "`coverage_ratio_cash_bps` is `adjusted_cash_flow_cents` multiplied by 10,000, divided by the same total and floored."

        Design: Difficulty/dual_variant_calc/distribution_coverage_gaap_basis_vs_cash_flow_basis
        """
        scene = _harborline_priced_offering(world)
        assert_fields(
            world.read_share_class(scene["share_class_id"]),
            shares_outstanding_e4=300000000,
        )

        declaration = _declare(
            api,
            world,
            scene["offering_id"],
            gaap_net_income_cents=90000,
            adjusted_cash_flow_cents=135000,
            board_uncovered_acknowledgement=True,
        )

        assert_fields(
            declaration,
            total_declared_cents=150000,
            coverage_ratio_gaap_bps=6000,
            coverage_ratio_cash_bps=9000,
        )

    def test_return_of_capital_is_disclosed_separately_on_each_basis(
        self, api: ApiClient, world: ReitWorld
    ):
        """Each shortfall from full coverage is disclosed on its own basis, and neither substitutes.

        PRD §3.7: "Full coverage is 10,000 basis points, so the disclosed return of capital on each basis is what the coverage falls short of full: `return_of_capital_bps` is the greater of zero and 10,000 less `coverage_ratio_cash_bps`, while `gaap_return_of_capital_bps` is the greater of zero and 10,000 less `coverage_ratio_gaap_bps`."

        PRD §3.7: "A new declaration opens `DECLARED` with `total_distribution_fee_accrued_cents` at zero."

        Design: Difficulty/dual_variant_calc/distribution_coverage_gaap_basis_vs_cash_flow_basis
        """
        scene = _harborline_priced_offering(world)

        declaration = _declare(
            api,
            world,
            scene["offering_id"],
            gaap_net_income_cents=90000,
            adjusted_cash_flow_cents=135000,
            board_uncovered_acknowledgement=True,
        )

        assert_fields(
            declaration,
            return_of_capital_bps=1000,
            gaap_return_of_capital_bps=4000,
            status=DeclarationStatus.DECLARED,
            total_distribution_fee_accrued_cents=0,
        )
        assert (
            declaration["gaap_return_of_capital_bps"]
            != declaration["return_of_capital_bps"]
        ), (
            "the GAAP and cash-flow return-of-capital disclosures must be reported "
            "as two distinct figures on the same declaration"
        )

    def test_exact_cash_coverage_needs_no_acknowledgement_even_with_a_weak_gaap_ratio(
        self, api: ApiClient, world: ReitWorld
    ):
        """Cash flow equal to the declared total clears the gate while GAAP still shows 4000 bps of return of capital.

        PRD §3.7: "A coverage ratio landing on exactly 10,000 basis points is fully covered, produces a `return_of_capital_bps` of zero, and needs no acknowledgement."

        PRD §3.7: "A weak GAAP ratio, on its own, never blocks a declaration."

        Design: Difficulty/dual_variant_calc/distribution_coverage_gaap_basis_vs_cash_flow_basis
        """
        scene = _harborline_priced_offering(world)

        declaration = _declare(
            api,
            world,
            scene["offering_id"],
            gaap_net_income_cents=90000,
            adjusted_cash_flow_cents=150000,
            board_uncovered_acknowledgement=False,
        )

        assert_fields(
            declaration,
            total_declared_cents=150000,
            coverage_ratio_cash_bps=10000,
            return_of_capital_bps=0,
            coverage_ratio_gaap_bps=6000,
            gaap_return_of_capital_bps=4000,
            status=DeclarationStatus.DECLARED,
        )
