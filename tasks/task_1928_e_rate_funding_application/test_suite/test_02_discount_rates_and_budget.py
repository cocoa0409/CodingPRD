"""Discount-rate variants, matrix band edges, and the Category Two budget pool
(PRD §3.2)."""
import pytest

from test_helpers import (
    budget_summary,
    new_applicant,
    new_cycle,
    new_snapshot,
    setup_applicant_base,
)


class TestDirectVsCepVariant:
    """Queue A: dual_variant_calc/discount_rate_direct_vs_cep."""

    def test_direct_snapshot_share_and_rate(self):
        """PRD §3.2: "When `cep_participating` is false, the share is 100 times
        `free_lunch_eligible_students` divided by `total_students`, rounded half
        up to two decimal places."
        PRD §3.2 matrix: "| at least 20, less than 35 | 50 | 60 | 50 | 60 |".
        PRD §3.2: "A computed budget-summary read on an applicant, given a
        `funding_cycle_id`, returns all of this live — `c2_cap_cents`,
        `c2_committed_cents`, and `c2_available_cents` from the budget pool, plus
        `discount_rate_c1_pct`, `discount_rate_c2_pct`, and `nslp_share_pct` from
        a fresh run of the discount lookup against the latest snapshot."

        Design: Difficulty/dual_variant_calc/discount_rate_direct_vs_cep
        """
        ctx = setup_applicant_base(
            applicant_overrides={"student_count": 1000},
            snapshot_overrides={"total_students": 1000,
                                "free_lunch_eligible_students": 300,
                                "cep_participating": False},
        )
        summary = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert summary["nslp_share_pct"] == pytest.approx(30.0, abs=1e-9), (
            f"direct share 100*300/1000 must be 30.00, got {summary['nslp_share_pct']}"
        )
        assert summary["discount_rate_c1_pct"] == 50, (
            f"share 30.00 lands in band [20,35) -> C1 URBAN 50, "
            f"got {summary['discount_rate_c1_pct']}"
        )

    def test_cep_snapshot_supersedes_direct_and_changes_rate(self):
        """PRD §3.2: "When `cep_participating` is true, the share is
        `cep_identified_student_pct` multiplied by 1.6, capped at 100.00 — so an
        identified percentage of 62.50 or higher saturates the cap."
        PRD §3.2: "The effective snapshot for any applicant-and-cycle pair is the
        latest one by `created_at`; because timestamps carry millisecond precision
        and snapshots are recorded sequentially, ties cannot occur."
        PRD §3.2: "Both variants then feed the same discount matrix, yet identical
        cohorts can yield different shares — and therefore different rates —
        depending on the variant."

        Design: Difficulty/dual_variant_calc/discount_rate_direct_vs_cep
        """
        ctx = setup_applicant_base(
            applicant_overrides={"student_count": 1000},
            snapshot_overrides={"total_students": 1000,
                                "free_lunch_eligible_students": 300,
                                "cep_participating": False},
        )
        direct = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert direct["discount_rate_c1_pct"] == 50

        # A later CEP snapshot supersedes the direct one by recency.
        new_snapshot(
            ctx["applicant"]["id"], ctx["cycle"]["id"],
            total_students=1000, free_lunch_eligible_students=300,
            cep_participating=True, cep_identified_student_pct=30.00,
        )
        cep = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert cep["nslp_share_pct"] == pytest.approx(48.0, abs=1e-9), (
            f"CEP share min(30.00*1.6, 100.00) must be 48.00, got {cep['nslp_share_pct']}"
        )
        assert cep["discount_rate_c1_pct"] == 60, (
            f"share 48.00 lands in band [35,50) -> C1 URBAN 60, "
            f"got {cep['discount_rate_c1_pct']}"
        )
        assert cep["discount_rate_c1_pct"] != direct["discount_rate_c1_pct"], (
            "same cohort under two variants must yield different rates"
        )


class TestDiscountBandEdge35Pct:
    """Queue A: boundary_precision_check/discount_band_edge_35_pct."""

    def test_share_349_of_1000_stays_in_third_band(self):
        """PRD §3.2: "Boundary behavior is exact: a share of exactly 35.00 enters
        the fourth band and yields a Category One urban rate of 60, while 34.99 —
        one centile below — stays in the third band at 50."
        PRD §3.2 matrix: "| at least 20, less than 35 | 50 | 60 | 50 | 60 |".

        Design: Difficulty/boundary_precision_check/discount_band_edge_35_pct
        """
        cycle = new_cycle()
        applicant = new_applicant(name="Lowshare Elementary District",
                                  entity_type="SCHOOL", urban_rural="URBAN",
                                  student_count=1000)
        new_snapshot(applicant["id"], cycle["id"], total_students=1000,
                     free_lunch_eligible_students=349, cep_participating=False)
        summary = budget_summary(applicant["id"], cycle["id"])
        assert summary["nslp_share_pct"] == pytest.approx(34.9, abs=1e-9)
        assert summary["discount_rate_c1_pct"] == 50, (
            f"34.90 < 35 stays in band [20,35) at rate 50, "
            f"got {summary['discount_rate_c1_pct']}"
        )

    def test_share_350_of_1000_enters_fourth_band(self):
        """PRD §3.2: "Boundary behavior is exact: a share of exactly 35.00 enters
        the fourth band and yields a Category One urban rate of 60, while 34.99 —
        one centile below — stays in the third band at 50."
        PRD §3.2: "The share falls into the first band whose lower bound it meets
        or exceeds and whose upper bound it falls short of; the top band is closed
        at 100"

        Design: Difficulty/boundary_precision_check/discount_band_edge_35_pct
        """
        cycle = new_cycle()
        applicant = new_applicant(name="Edgeline High District",
                                  entity_type="SCHOOL", urban_rural="URBAN",
                                  student_count=1000)
        new_snapshot(applicant["id"], cycle["id"], total_students=1000,
                     free_lunch_eligible_students=350, cep_participating=False)
        summary = budget_summary(applicant["id"], cycle["id"])
        assert summary["nslp_share_pct"] == pytest.approx(35.0, abs=1e-9)
        assert summary["discount_rate_c1_pct"] == 60, (
            f"35.00 >= 35 enters band [35,50) at rate 60, "
            f"got {summary['discount_rate_c1_pct']}"
        )


class TestCepShareCap:
    def test_cep_share_capped_at_100(self):
        """PRD §3.2: "When `cep_participating` is true, the share is
        `cep_identified_student_pct` multiplied by 1.6, capped at 100.00 — so an
        identified percentage of 62.50 or higher saturates the cap."
        PRD §3.2 matrix: "| at least 75, at most 100 | 90 | 90 | 85 | 85 |".

        Design: Corner/calculations/cep_share_capped_at_100
        """
        cycle = new_cycle()
        applicant = new_applicant(entity_type="SCHOOL", urban_rural="URBAN",
                                  student_count=1000)
        new_snapshot(applicant["id"], cycle["id"], total_students=1000,
                     free_lunch_eligible_students=0, cep_participating=True,
                     cep_identified_student_pct=70.00)
        summary = budget_summary(applicant["id"], cycle["id"])
        assert summary["nslp_share_pct"] == pytest.approx(100.0, abs=1e-9), (
            f"min(70.00*1.6, 100.00) must saturate the cap at 100.00, "
            f"got {summary['nslp_share_pct']} (not 112.00)"
        )
        assert summary["discount_rate_c1_pct"] == 90
        assert summary["discount_rate_c2_pct"] == 85, (
            "top band: Category Two urban caps at 85, below Category One's 90"
        )


class TestLibraryBudgetFloor:
    def test_library_budget_floor_variant(self):
        """PRD §3.2: "For a `LIBRARY`, the cap is the greater of 450 cents ($4.50)
        per square foot times `square_feet`, or the same 2,500,000-cent floor.
        Consider a 3,000-square-foot library: its computed 1,350,000 cents lands
        on the floor at 2,500,000, while a 1,000-student school's 16,700,000
        cents comfortably exceeds it."

        Design: Corner/calculations/library_budget_floor_variant
        """
        cycle = new_cycle()
        library = new_applicant(name="Carnegie Public Library",
                                entity_type="LIBRARY", urban_rural="URBAN",
                                square_feet=3000)
        new_snapshot(library["id"], cycle["id"], total_students=1000,
                     free_lunch_eligible_students=300, cep_participating=False)
        summary = budget_summary(library["id"], cycle["id"])
        assert summary["c2_cap_cents"] == 2500000, (
            f"floor must bind over 450*3000=1,350,000, got {summary['c2_cap_cents']}"
        )
        assert summary["c2_committed_cents"] == 0
        assert summary["c2_available_cents"] == 2500000
        assert summary["discount_rate_c2_pct"] == 50, (
            f"share 30.00 lands in band [20,35) -> C2 URBAN 50, "
            f"got {summary['discount_rate_c2_pct']}"
        )
