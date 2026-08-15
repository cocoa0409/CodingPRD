"""Asset sales (prohibited-transaction analysis, confirm cascade) and the
compliance-disclosure board review loop (PRD §3.8, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    analyze_sale,
    assert_asset_sale,
    assert_compliance_disclosure,
    create_analyzed_sale,
    create_asset_holding,
    create_asset_sale,
    create_disclosure,
    create_quarter,
    create_reit,
    make_board_director_headers,
    make_compliance_officer_headers,
    setup_locked_income_test_report,
    setup_reit_with_open_quarter,
    submit_disclosure,
    validate_error,
    validate_success,
)


class TestProhibitedTransactionBranches:
    def test_dealer_gain_under_24_months_taxed_safe_harbor_not(
            self, api, compliance_officer_headers):
        """PRD §3.8: "The `is_prohibited` flag is true when the asset is
        dealer inventory (`is_dealer_inventory` true) and the holding period
        is less than 24 months — the 24-month boundary is a safe harbor, so a
        holding period of 24 months or more is safe. When the sale is
        prohibited and the gain — the excess of `sale_price_cents` over
        `basis_cents` — is positive, the `prohibited_tax_cents` equals that
        gain in full: a 100% tax on net gain. Otherwise the tax is 0."

        Design: Difficulty/combinatorial_formula/prohibited_transaction_three_input_branch
        """
        reit = create_reit(legal_name="PT REIT")
        a1 = create_asset_holding(
            reit["id"], asset_name="Dealer Condo A", asset_class="REAL_ESTATE",
            is_dealer_inventory=True, acquisition_date="2025-01-01",
            value_cents=1_300_000,
        )
        a2 = create_asset_holding(
            reit["id"], asset_name="Dealer Condo B", asset_class="REAL_ESTATE",
            is_dealer_inventory=True, acquisition_date="2025-01-01",
            value_cents=1_300_000,
        )
        s1 = create_asset_sale(reit["id"], a1["id"], sale_price_cents=2_000_000,
                               basis_cents=1_300_000, sale_date="2026-08-01")
        s2 = create_asset_sale(reit["id"], a2["id"], sale_price_cents=2_000_000,
                               basis_cents=1_300_000, sale_date="2027-02-01")

        analyzed_1 = validate_success(
            api.analyze_asset_sale(s1["id"], compliance_officer_headers), 200
        )
        assert_asset_sale(analyzed_1)
        assert analyzed_1["holding_period_months"] == 19
        assert analyzed_1["is_prohibited"] is True
        assert analyzed_1["prohibited_tax_cents"] == 700_000

        analyzed_2 = validate_success(
            api.analyze_asset_sale(s2["id"], compliance_officer_headers), 200
        )
        assert analyzed_2["holding_period_months"] == 25
        assert analyzed_2["is_prohibited"] is False
        assert analyzed_2["prohibited_tax_cents"] == 0

    def test_zero_gain_and_non_dealer_branches_tax_zero(
            self, api, compliance_officer_headers):
        """PRD §3.8: "When the sale is prohibited and the gain — the excess of
        `sale_price_cents` over `basis_cents` — is positive, the
        `prohibited_tax_cents` equals that gain in full: a 100% tax on net
        gain. Otherwise the tax is 0."

        Design: Difficulty/combinatorial_formula/prohibited_transaction_three_input_branch
        """
        reit = create_reit(legal_name="PT REIT 2")
        dealer = create_asset_holding(
            reit["id"], asset_name="Dealer Flat", asset_class="REAL_ESTATE",
            is_dealer_inventory=True, acquisition_date="2025-01-01",
            value_cents=1_300_000,
        )
        non_dealer = create_asset_holding(
            reit["id"], asset_name="Investment Flat", asset_class="REAL_ESTATE",
            is_dealer_inventory=False, acquisition_date="2025-01-01",
            value_cents=1_300_000,
        )
        zero_gain = create_asset_sale(reit["id"], dealer["id"],
                                      sale_price_cents=1_300_000,
                                      basis_cents=1_300_000,
                                      sale_date="2026-08-01")
        non_dealer_gain = create_asset_sale(reit["id"], non_dealer["id"],
                                            sale_price_cents=2_000_000,
                                            basis_cents=1_300_000,
                                            sale_date="2026-08-01")

        analyzed_zero = validate_success(
            api.analyze_asset_sale(zero_gain["id"], compliance_officer_headers),
            200,
        )
        assert analyzed_zero["holding_period_months"] == 19
        assert analyzed_zero["is_prohibited"] is True
        assert analyzed_zero["prohibited_tax_cents"] == 0, (
            "prohibited but zero gain -> no tax"
        )

        analyzed_nd = validate_success(
            api.analyze_asset_sale(non_dealer_gain["id"],
                                   compliance_officer_headers),
            200,
        )
        assert analyzed_nd["is_prohibited"] is False
        assert analyzed_nd["prohibited_tax_cents"] == 0


def test_dealer_sale_at_exactly_24_months_is_safe(
        api, compliance_officer_headers):
    """PRD §3.8: "the system computes `holding_period_months` as the floor of
    the day count between the asset's `acquisition_date` and the `sale_date`
    divided by 30 — a whole-calendar-month figure. The `is_prohibited` flag is
    true when the asset is dealer inventory (`is_dealer_inventory` true) and
    the holding period is less than 24 months — the 24-month boundary is a
    safe harbor, so a holding period of 24 months or more is safe."

    Design: Corner/calculations/prohibited_sale_at_exactly_24_months_is_safe
    """
    reit = create_reit(legal_name="C6 REIT")
    asset = create_asset_holding(
        reit["id"], asset_name="Spec House", asset_class="REAL_ESTATE",
        is_dealer_inventory=True, acquisition_date="2024-06-15",
        value_cents=1_000_000,
    )
    sale = create_asset_sale(reit["id"], asset["id"],
                             sale_price_cents=1_500_000,
                             basis_cents=1_000_000, sale_date="2026-06-09")
    analyzed = validate_success(
        api.analyze_asset_sale(sale["id"], compliance_officer_headers), 200
    )
    assert analyzed["holding_period_months"] == 24
    assert analyzed["is_prohibited"] is False
    assert analyzed["prohibited_tax_cents"] == 0


def test_confirm_sale_flips_holding_to_sold(api, tax_director_headers,
                                            compliance_officer_headers):
    """PRD §3.8: "On confirm the underlying asset flips `HELD → SOLD`
    (removing it from subsequent asset tests), the sale transitions `ANALYZED
    → CONFIRMED`, and both the sale's and the asset's `version` increment by
    one."

    Design: Corner/state_machines/confirm_sale_flips_holding_to_sold
    """
    reit = create_reit(legal_name="SM6 REIT")
    asset = create_asset_holding(
        reit["id"], asset_name="Plaza", asset_class="REAL_ESTATE",
        acquisition_date="2020-01-01", value_cents=5_000_000,
    )
    sale = create_analyzed_sale(reit["id"], asset["id"],
                                sale_price_cents=5_500_000,
                                basis_cents=5_000_000, sale_date="2026-06-01")
    confirmed = validate_success(
        api.confirm_asset_sale(sale["id"], tax_director_headers), 200
    )
    assert confirmed["status"] == "CONFIRMED"
    holding = validate_success(
        api.get_asset_holding(asset["id"], compliance_officer_headers), 200
    )
    assert holding["status"] == "SOLD"


class TestDisclosureRejectRevisionCycle:
    def _setup_submitted_disclosure(self):
        reit, quarter = setup_reit_with_open_quarter()
        report = setup_locked_income_test_report(reit["id"], quarter["id"])
        assert report["status"] == "LOCKED"
        disclosure = create_disclosure(reit["id"], "INCOME_TEST",
                                       report["id"],
                                       title="Q1 income test",
                                       body="75% and 95% results")
        submitted = submit_disclosure(disclosure["id"], officer_id="officer-1")
        return reit, report, submitted

    def test_reject_loops_back_to_draft(self, api, board_director_headers):
        """PRD §3.9: "Approving moves `SUBMITTED → APPROVED`; rejecting marks
        the decision `REJECTED` and returns the disclosure to `DRAFT` for
        revision — the rejection is a revision loop, not a terminal state."
        PRD §3.9: "A rejection additionally increments `revision_count` by
        one, tracking how many times this disclosure has made the round trip
        back to draft."

        Design: Difficulty/non_linear_state_machine/disclosure_reject_revision_cycle
        """
        _reit, _report, submitted = self._setup_submitted_disclosure()
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_officer_id"] == "officer-1"

        rejected = validate_success(
            api.reject_compliance_disclosure(
                submitted["id"], make_board_director_headers("director-9")
            ),
            200,
        )
        assert_compliance_disclosure(rejected)
        assert rejected["status"] == "DRAFT"
        assert rejected["revision_count"] == 1
        assert rejected["decided_by_director_id"] == "director-9"

    def test_resubmit_after_reject_terminates_at_approved(
            self, api, board_director_headers):
        """PRD §3.9: "Once a rejected disclosure has been revised, the officer
        may submit it again and the loop repeats."

        Design: Difficulty/non_linear_state_machine/disclosure_reject_revision_cycle
        """
        _reit, _report, submitted = self._setup_submitted_disclosure()
        validate_success(
            api.reject_compliance_disclosure(
                submitted["id"], make_board_director_headers("director-9")
            ),
            200,
        )
        resubmitted = submit_disclosure(submitted["id"], officer_id="officer-1")
        assert resubmitted["status"] == "SUBMITTED"
        approved = validate_success(
            api.approve_compliance_disclosure(
                submitted["id"], make_board_director_headers("director-9")
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["revision_count"] == 1
        assert approved["decided_by_director_id"] == "director-9"


def test_disclosure_submit_requires_locked_reference(
        api, compliance_officer_headers):
    """PRD §3.9: "Reference integrity is enforced at submit time: the
    `reference_id` must resolve to an existing entity of the type implied by
    `disclosure_type`, and that entity must be in a terminal or locked state —
    `LOCKED` or `BREACHED` for the two test report types, `FINALIZED` for
    snapshots, `POSTED` or `CLOSED` for requirements, `CONFIRMED` for asset
    sales. A reference that is missing yields `ERR_NOT_FOUND`; one that
    resolves but is still in a non-terminal state yields `ERR_INVALID_STATE`."

    Design: Corner/validations/disclosure_submit_requires_locked_reference
    """
    reit = create_reit(legal_name="DSC REIT")
    quarter = create_quarter(reit["id"])
    create_asset_holding(reit["id"], asset_name="Center",
                         asset_class="REAL_ESTATE", value_cents=100_000_000)
    report = validate_success(
        api.create_asset_test_report(
            {"reit_id": reit["id"], "quarter_id": quarter["id"]},
            compliance_officer_headers,
        ),
        201,
    )
    disclosure = create_disclosure(reit["id"], "ASSET_TEST", report["id"],
                                   title="Asset test", body="75% detail")

    early = api.submit_compliance_disclosure(
        disclosure["id"], make_compliance_officer_headers("officer-1")
    )
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)

    validate_success(
        api.lock_asset_test_report(report["id"], compliance_officer_headers),
        200,
    )
    submitted = validate_success(
        api.submit_compliance_disclosure(
            disclosure["id"], make_compliance_officer_headers("officer-1")
        ),
        200,
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_officer_id"] == "officer-1"
