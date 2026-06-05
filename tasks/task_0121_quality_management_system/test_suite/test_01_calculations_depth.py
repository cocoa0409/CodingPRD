"""Depth tests for the quality calculations (queue A — Difficulty).

Covers CAPA effectiveness (dual variant), AQL sampling (dual variant), supplier
quality rating (combinatorial three-factor), and cost of quality (round-per-line
then sum).
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
)
from test_helpers import fixtures as fx


# ==========================================================================
# Difficulty/dual_variant_calc/capa_effectiveness_provisional_vs_final
# ==========================================================================
def test_capa_provisional_vs_final_effectiveness_diverge(api):
    """PRD 3.4: "The projected (provisional) effectiveness, recorded in
    provisional_effectiveness and clamped to the range 0.00 through 1.00, is the
    total of the containment_count values across all D4 and D5 steps divided by
    the parent report's defect_qty (treating the divisor as 1 if defect_qty were
    ever zero), capped at 1.00 and rounded half-up to two decimal places."
    PRD 3.4: "The final effectiveness is one minus the recurred_defects on the
    D8 step divided by the parent report's defect_qty (again treating the divisor
    as 1 if it were zero), rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/capa_effectiveness_provisional_vs_final
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    # defect_qty=5, containment=3 -> provisional 0.60; recurred=0 -> final 1.00
    ncr, capa = fx.capa_to_effectiveness_check(
        eng["id"], mgr["id"], sup["id"], containment_count=3, recurred_defects=0, defect_qty=5,
        severity="MAJOR", part_number="P-DV1",
    )
    assert capa["provisional_effectiveness"] == 0.60, capa

    closed = validate_success(api.transition_capa(capa["id"], {"action": "CLOSE_EFFECTIVE"}, fx.make_manager_headers(mgr["id"])))
    assert closed["status"] == "CLOSED_EFFECTIVE"
    assert closed["final_effectiveness"] == 1.00
    assert closed["provisional_effectiveness"] != closed["final_effectiveness"]


def test_capa_provisional_effectiveness_computed_on_verification_entry(api):
    """PRD 3.4: "The projected (provisional) effectiveness, recorded in
    provisional_effectiveness and clamped to the range 0.00 through 1.00, is the
    total of the containment_count values across all D4 and D5 steps divided by
    the parent report's defect_qty (treating the divisor as 1 if defect_qty were
    ever zero), capped at 1.00 and rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/capa_effectiveness_provisional_vs_final
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    # containment=3 / defect_qty=5 = 0.60
    ncr, capa = fx.capa_to_verification(
        eng["id"], mgr["id"], sup["id"], containment_count=3, defect_qty=5,
        severity="MAJOR", part_number="P-DV2",
    )
    assert capa["status"] == "VERIFICATION"
    assert capa["provisional_effectiveness"] == 0.60


# ==========================================================================
# Difficulty/dual_variant_calc/aql_sampling_normal_vs_tightened
# ==========================================================================
def test_aql_tightened_column_flips_accept_to_reject(api):
    """PRD 3.6: "In TIGHTENED mode the column is stepped one position tighter
    than the plan's aql_pct, where the ordered columns from tightest to loosest
    are 1.0, then 2.5, then 4.0: stepping tighter takes 4.0 to 2.5 and 2.5 to
    1.0, while 1.0 stays at 1.0 because there is no tighter column."
    PRD 3.6: "Tightening keeps the same code letter — and therefore the same
    sample size — but the tighter column yields an acceptance number that is the
    same or smaller, so a lot that would have been accepted in normal mode can
    flip to rejected in tightened mode."

    Design: Difficulty/dual_variant_calc/aql_sampling_normal_vs_tightened
    """
    # lot_size=120 -> code letter F; aql_pct=4.0. Push 2 rejects -> TIGHTENED.
    inspector, supplier, cp, ip = fx.setup_plan_with_n_rejected_lots(
        2, lot_size=120, aql_pct=4.0, inspection_level="GII", reject_defects=3
    )
    # Third lot now reads TIGHTENED column (F,2.5) -> Ac=1; defects_found=2 rejects.
    lot3 = fx.create_in_inspection_lot(inspector["id"], ip["id"], supplier["id"], actual_lot_size=120)
    assert lot3["severity_mode_used"] == "TIGHTENED"
    assert lot3["acceptance_number"] == 1
    assert lot3["sample_size"] == 20

    disp = validate_success(api.transition_inspection_lot(
        lot3["id"], {"action": "DISPOSITION", "defects_found": 2}, fx.make_inspector_headers(inspector["id"])))
    assert disp["status"] == "REJECTED"


def test_aql_normal_mode_accepts_same_defects_that_tightened_rejects(api):
    """PRD 3.6: "The table holds, for each code letter D through H and each AQL
    column of 1.0, 2.5, or 4.0, a sample size and an acceptance number: ... at
    code letter F the sample size is 20 with acceptance numbers 0, 1, and 2 ..."
    PRD 3.6: "If defects_found is at most the acceptance_number — equality at the
    acceptance number still accepts — the lot is ACCEPTED ..."

    Design: Difficulty/dual_variant_calc/aql_sampling_normal_vs_tightened
    """
    # Fresh NORMAL plan, letter F aql 4.0 -> Ac=2; defects_found=2 accepts.
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII")
    lot = fx.create_in_inspection_lot(inspector["id"], ip["id"], supplier["id"], actual_lot_size=120)
    assert lot["severity_mode_used"] == "NORMAL"
    assert lot["acceptance_number"] == 2
    disp = validate_success(api.transition_inspection_lot(
        lot["id"], {"action": "DISPOSITION", "defects_found": 2}, fx.make_inspector_headers(inspector["id"])))
    assert disp["status"] == "ACCEPTED"


# ==========================================================================
# Difficulty/combinatorial_formula/supplier_quality_rating_three_factor_min_max
# ==========================================================================
def test_supplier_rating_three_factor_combination(api):
    """PRD 3.7: "The lot factor rewards a clean acceptance history: if
    lots_inspected is zero it is 1.0, otherwise it is one minus the ratio of
    lots_rejected to lots_inspected, with the result floored at 0.0."
    PRD 3.7: "The nonconformance factor penalises attributed defects: it is one
    minus the ncrs_attributed multiplied by a per-NCR penalty of 0.10, floored
    at 0.0."
    PRD 3.7: "An open-SCAR penalty caps outstanding accountability: it is the
    open_scar_count multiplied by a per-SCAR step of 0.05, but never more than a
    ceiling of 0.20."
    PRD 3.7: "The base score weights the lot factor at 0.6 and the nonconformance
    factor at 0.4 (the two weights sum to 1.0), then the open-SCAR penalty is
    subtracted, with the result floored at 0.0. That figure is multiplied by 100
    and rounded half-up to two decimal places to produce the stored
    quality_rating."

    Design: Difficulty/combinatorial_formula/supplier_quality_rating_three_factor_min_max
    """
    inspector = fx.create_inspector()
    eng = fx.create_engineer()
    sup = fx.create_supplier()
    cp = fx.create_control_plan()
    ip = get_success_data(api.create_inspection_plan(
        {"name": "IP G", "control_plan_id": cp["id"], "part_number": "P-G",
         "lot_size": 120, "aql_pct": 4.0, "inspection_level": "GII"},
        fx.TEST_USERS["manager_headers"]))
    # one REJECTED + one ACCEPTED lot -> lots_inspected=2, lots_rejected=1
    fx.run_lot(inspector["id"], ip["id"], sup["id"], defects_found=3)
    fx.run_lot(inspector["id"], ip["id"], sup["id"], defects_found=0)
    # two SUPPLIER-source NCRs opened -> ncrs_attributed=2
    fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=1,
                       unit_cost_cents=100, part_number="P-G")
    fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=1,
                       unit_cost_cents=100, part_number="P-G")
    # one SCAR open -> open_scar_count=1
    draft = fx.create_draft_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR",
                                defect_qty=1, unit_cost_cents=100, part_number="P-G")
    mgr = fx.create_manager()
    fx.open_scar(mgr["id"], draft["id"], sup["id"])

    s = validate_success(api.get_supplier(sup["id"], fx.TEST_USERS["manager_headers"]))
    assert s["lots_inspected"] == 2
    assert s["lots_rejected"] == 1
    assert s["ncrs_attributed"] == 2
    assert s["open_scar_count"] == 1
    # lot_factor=0.5, ncr_factor=0.8, scar_penalty=0.05:
    # base = 0.6*0.5 + 0.4*0.8 = 0.62; raw = 0.62 - 0.05 = 0.57 -> 57.00
    assert s["quality_rating"] == pytest.approx(57.00, abs=0.001)
    assert s["approval_status"] == "PROBATION"


def test_supplier_rating_open_scar_penalty_pulls_into_probation(api):
    """PRD 3.7: "An open-SCAR penalty caps outstanding accountability: it is the
    open_scar_count multiplied by a per-SCAR step of 0.05, but never more than a
    ceiling of 0.20."
    PRD 3.7: "a rating below 70.00 but at least 50.00 yields PROBATION; and a
    rating below 50.00 yields DISQUALIFIED. Both thresholds are inclusive at
    their lower bound."

    Design: Difficulty/combinatorial_formula/supplier_quality_rating_three_factor_min_max
    """
    inspector = fx.create_inspector()
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    cp = fx.create_control_plan()
    ip = get_success_data(api.create_inspection_plan(
        {"name": "IP G2", "control_plan_id": cp["id"], "part_number": "P-G2",
         "lot_size": 120, "aql_pct": 4.0, "inspection_level": "GII"},
        fx.TEST_USERS["manager_headers"]))
    fx.run_lot(inspector["id"], ip["id"], sup["id"], defects_found=3)
    fx.run_lot(inspector["id"], ip["id"], sup["id"], defects_found=0)
    fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=1,
                       unit_cost_cents=100, part_number="P-G2")
    fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=1,
                       unit_cost_cents=100, part_number="P-G2")
    draft = fx.create_draft_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR",
                                defect_qty=1, unit_cost_cents=100, part_number="P-G2")
    fx.open_scar(mgr["id"], draft["id"], sup["id"])
    s = validate_success(api.get_supplier(sup["id"], fx.TEST_USERS["manager_headers"]))
    assert s["quality_rating"] == pytest.approx(57.00, abs=0.001)
    assert s["approval_status"] == "PROBATION"


# ==========================================================================
# Difficulty/combinatorial_formula/ncr_cost_of_quality_round_per_line_then_sum
# ==========================================================================
def test_cost_of_quality_round_per_line_then_sum_rework(api):
    """PRD 3.3: "First, a per-unit labour figure is computed as the rework_hours
    multiplied by a labour rate of 6,000 cents per hour (that is, 60 dollars per
    hour), rounded half-up to whole cents."
    PRD 3.3: "Each per-unit base component is then multiplied by a severity
    multiplier — 1.5 when severity is CRITICAL, 1.0 when MAJOR, and 0.5 when
    MINOR — and that product is rounded half-up to whole cents to form the
    per-unit line."
    PRD 3.3: "Finally the per-unit line is summed across all defect_qty units;
    because the units are identical, the total equals the defect_qty times the
    per-unit rounded line. Rounding is applied per line and only then summed,
    never the reverse."

    Design: Difficulty/combinatorial_formula/ncr_cost_of_quality_round_per_line_then_sum
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    # MINOR, defect_qty=3, unit_cost_cents=999, rework_hours=0.5
    # labour=round_half_up(0.5*6000)=3000; per-line=round_half_up(3000*0.5)=1500; sum*3=4500
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=3,
                             unit_cost_cents=999, part_number="P-R", rework_hours=0.5)
    disp = validate_success(api.disposition_ncr(ncr["id"], {"disposition": "REWORK"}, fx.make_manager_headers(mgr["id"])))
    assert disp["disposition"] == "REWORK"
    assert disp["cost_of_quality_cents"] == 4500
    assert disp["budget_reserved_cents"] == 4500


def test_cost_of_quality_rounds_each_line_not_the_sum(api):
    """PRD 2.5: "Where the cost-of-quality calculation accumulates a per-unit
    figure across many units, the rounding is applied to each per-unit line first
    and the rounded lines are then summed — the system never sums raw figures and
    rounds once at the end."
    PRD 3.3: "for REWORK, the base component is that rounded labour figure alone,
    since the unit is salvaged and no material value is lost"

    Design: Difficulty/combinatorial_formula/ncr_cost_of_quality_round_per_line_then_sum
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    # Same pinned inputs; assert the per-line-then-sum total of 4500.
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=3,
                             unit_cost_cents=999, part_number="P-R2", rework_hours=0.5)
    disp = validate_success(api.disposition_ncr(ncr["id"], {"disposition": "REWORK"}, fx.make_manager_headers(mgr["id"])))
    assert disp["cost_of_quality_cents"] == 4500
