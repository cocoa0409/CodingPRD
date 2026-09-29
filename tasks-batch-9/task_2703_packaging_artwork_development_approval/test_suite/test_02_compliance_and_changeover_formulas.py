"""Two formulas that compose several independent inputs in a contractual order."""

import pytest

from test_helpers import (
    all_elements_passing,
    element_checks_for,
    new_approved_brief,
    new_asset,
    new_version,
    read_asset,
    read_version,
    scrapped_runout,
    verify,
)

EU_BRIEF = {
    "sku_code": "SKU-2044",
    "product_name": "Continental Wafer Selection 250g",
    "regulatory_scheme": "EU_FIC",
    "market_codes": ["DE", "FR"],
    "language_codes": ["de", "fr", "it"],
}

TRILINGUAL_ASSET = {
    "market_code": "DE",
    "language_codes": ["de", "fr", "it"],
}


def _failing_elements():
    """An all-passing payload broken on one CRITICAL and one MAJOR element."""
    return all_elements_passing(
        allergen_statement={"text": "Contains milk and soya.", "allergen_emphasis": False},
        date_code_zone={"zone_mm2": 120, "position": "BASE_PANEL"},
    )


class TestComplianceScoreComposition:
    """Element deductions, the scheme factor and both breadth penalties."""

    def test_scheme_factor_applies_before_the_two_breadth_penalties(self):
        """The scheme-scaled subtotal is rounded before anything else is added.

        PRD §3.4: "Second, that sum is multiplied by the scheme factor for the
        brief's `regulatory_scheme` — 1.00 under `FDA_FOOD`, 1.10 under `EU_FIC`
        and 1.05 under `HEALTH_CANADA` — and the product is rounded half up to two
        decimal places **at this point**, before anything else is added."

        Design: Difficulty/combinatorial_formula/compliance_score_combines_element_scheme_market_and_language_inputs
        """
        brief = new_approved_brief(**EU_BRIEF)
        asset = new_asset(brief["id"], **TRILINGUAL_ASSET)
        version = new_version(asset, mandatory_elements=_failing_elements())

        verified = verify(version["id"])

        # (25 + 10) * 1.10 = 38.50, plus 2.5 for the second market and 1.5 for the
        # third language: 100 - 42.5 = 57.5.
        assert verified["compliance_score"] == pytest.approx(57.5, abs=0.01)
        assert verified["failed_element_count"] == 2
        assert verified["waived_element_count"] == 0
        assert verified["check_run_no"] == 1
        assert verified["state"] == "ELEMENTS_VERIFIED"

        rows = element_checks_for(version["id"])
        assert len(rows) == 7
        assert all(row["check_run_no"] == 1 for row in rows)
        by_code = {row["element_code"]: row for row in rows}
        assert by_code["ALLERGEN_STATEMENT"]["severity"] == "CRITICAL"
        assert by_code["ALLERGEN_STATEMENT"]["result"] == "FAIL"
        assert by_code["ALLERGEN_STATEMENT"]["deduction_points"] == pytest.approx(
            25.0, abs=0.01
        )
        assert by_code["DATE_CODE_ZONE"]["severity"] == "MAJOR"
        assert by_code["DATE_CODE_ZONE"]["result"] == "FAIL"
        assert by_code["DATE_CODE_ZONE"]["deduction_points"] == pytest.approx(
            10.0, abs=0.01
        )
        assert by_code["BARCODE"]["severity"] == "MAJOR"
        assert by_code["BARCODE"]["result"] == "PASS"
        assert by_code["BARCODE"]["deduction_points"] == pytest.approx(0.0, abs=0.01)

    def test_breadth_penalties_hold_a_flawless_pack_below_a_hundred(self):
        """Market and language breadth are charged even with no deductions at all.

        PRD §3.4: "Fourth, a language-breadth penalty of 1.5 points is charged for
        every language beyond the second printed on *this asset* — the asset's own
        `language_codes`, not the brief's wider list — so a bilingual variant is
        penalty-free and a four-language variant is charged 3.0 points."

        Design: Difficulty/combinatorial_formula/compliance_score_combines_element_scheme_market_and_language_inputs
        """
        brief = new_approved_brief(**EU_BRIEF)
        asset = new_asset(brief["id"], **TRILINGUAL_ASSET)
        version = new_version(asset, mandatory_elements=all_elements_passing())

        verified = verify(version["id"])

        # No deductions: 0 * 1.10 = 0.00, plus 2.5 and 1.5 -> 100 - 4.0 = 96.0.
        assert verified["compliance_score"] == pytest.approx(96.0, abs=0.01)
        assert verified["compliance_score"] != pytest.approx(100.0, abs=0.01)
        assert verified["failed_element_count"] == 0
        rows = element_checks_for(version["id"])
        assert all(row["result"] == "PASS" for row in rows)

    def test_two_versions_of_one_asset_score_independently(self):
        """Each version's score reads only the rows of its own verification run.

        PRD §3.4: "First, the `deduction_points` of every row of the run just
        executed are summed; rows from earlier runs have been deleted and can never
        enter the sum."

        Design: Difficulty/combinatorial_formula/compliance_score_combines_element_scheme_market_and_language_inputs
        """
        brief = new_approved_brief(**EU_BRIEF)
        asset = new_asset(brief["id"], **TRILINGUAL_ASSET)
        v1 = new_version(asset, mandatory_elements=_failing_elements())
        v2 = new_version(
            asset["id"],
            mandatory_elements=all_elements_passing(),
            reason_for_change_code="ERROR_CORRECTION",
            change_description="Allergen emphasis restored and date code zone enlarged.",
        )

        verify(v1["id"])
        verify(v2["id"])

        assert read_version(v1["id"])["compliance_score"] == pytest.approx(
            57.5, abs=0.01
        )
        assert read_version(v2["id"])["compliance_score"] == pytest.approx(
            96.0, abs=0.01
        )
        assert read_version(v1["id"])["version_no"] == 1
        assert read_version(v2["id"])["version_no"] == 2


class TestChangeoverTierOnPreSurchargeBase:
    """The changeover write-off ladder and its ledger consequences."""

    def test_expedite_tier_reads_the_base_and_not_the_total(self):
        """The tier is keyed on the pre-surcharge base, never on the total.

        PRD §3.8: "An expedite surcharge is then keyed on `changeover_base_cents` —
        the **pre**-surcharge figure, never on the total, which would make the
        formula circular."

        Design: Difficulty/combinatorial_formula/changeover_writeoff_tier_selected_on_pre_surcharge_base
        """
        _brief, _asset, _v1, _v2, runout = scrapped_runout()

        assert runout["material_writeoff_cents"] == 420000  # 10000 * 42
        assert runout["relabel_cost_cents"] == 60012  # 3334 * 18
        assert runout["changeover_base_cents"] == 480012
        # A base below 500000 attracts 5 percent: 480012 * 0.05 = 24000.6 -> 24001.
        assert runout["changeover_expedite_cents"] == 24001
        assert runout["total_changeover_cost_cents"] == 504013
        assert runout["total_changeover_cost_cents"] != 518413
        assert runout["state"] == "SCRAPPED"
        assert runout["disposition"] == "SCRAP"

    def test_scrap_credits_both_asset_ledgers_and_closes_the_chain(self):
        """The write-off feeds two conserved ledgers and completes obsolescence.

        PRD §3.8: "The asset's `obsolete_units_total` is then credited by
        `units_scrapped` and its `changeover_cost_committed_cents` by
        `total_changeover_cost_cents`."

        Design: Difficulty/combinatorial_formula/changeover_writeoff_tier_selected_on_pre_surcharge_base
        """
        _brief, asset, v1, v2, runout = scrapped_runout()

        assert runout["units_scrapped"] == 10000
        assert runout["units_reworked"] == 3334

        after = read_asset(asset["id"])
        assert after["obsolete_units_total"] == 10000
        assert after["changeover_cost_committed_cents"] == 504013
        assert after["obsolescence_state"] == "SUPERSEDED"
        assert read_version(v1["id"])["state"] == "OBSOLETE"
        assert read_version(v2["id"])["state"] == "APPROVED"
