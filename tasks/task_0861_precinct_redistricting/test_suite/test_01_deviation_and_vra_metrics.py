"""Population-deviation standards, rounding order, compliance gate, VRA boundaries.

Difficulty queue A: dual_variant_calc/plan_deviation_range_vs_maxabs,
combinatorial_formula/plan_compliance_gate_contiguity_flips,
combinatorial_formula/deviation_range_rounding_order,
boundary_precision_check/deviation_exactly_5pct_is_compliant,
boundary_precision_check/minority_exactly_50pct_not_majority_minority.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    setup_f1, create_jurisdiction, add_block, create_plan, create_district, assign_block,
    TEST_USERS,
)

CART = TEST_USERS["cartographer_headers"]
DEMO = TEST_USERS["demographer_headers"]


def _plan(api, pid, headers=DEMO):
    return validate_success(api.get_plan(pid, headers))


def _districts(api, pid, headers=DEMO):
    return validate_success(api.list_districts(pid, headers))


# ---------------------------------------------- dual_variant: max-abs vs range
def test_max_abs_deviation_symmetric_pair(api):
    """PRD §2.6: "A plan whose most over-populated district is +4.9% and whose
    most under-populated district is -4.9% scores 4.90 under this standard."

    Design: Difficulty/dual_variant_calc/plan_deviation_range_vs_maxabs
    """
    ctx = setup_f1(api, jname="J1max")
    plan = _plan(api, ctx["pid"])
    assert plan["max_abs_deviation_pct"] == 4.90, f"expected 4.90, got {plan['max_abs_deviation_pct']}"


def test_overall_range_deviation_symmetric_pair(api):
    """PRD §2.6: "That same +4.9%/-4.9% plan scores 9.80 under this standard: a
    different number from identical inputs."

    Design: Difficulty/dual_variant_calc/plan_deviation_range_vs_maxabs
    """
    ctx = setup_f1(api, jname="J1rng")
    plan = _plan(api, ctx["pid"])
    assert plan["overall_deviation_range_pct"] == 9.80, \
        f"expected 9.80, got {plan['overall_deviation_range_pct']}"


# ------------------------------------ combinatorial: contiguity flips compliance
def test_contiguity_false_makes_plan_noncompliant(api):
    """PRD §3.3: "A plan's overall is_compliant gate is true only when all four of
    the following hold together: the max_abs_deviation_pct is at most 5.00% ... ;
    every district in the plan has is_contiguous true; and the plan forms a
    complete partition ... If any of the four fails, the plan is not compliant."

    Design: Difficulty/combinatorial_formula/plan_compliance_gate_contiguity_flips
    """
    j = create_jurisdiction(api, name="Jc", target_district_count=2, required_mm=0)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1049, voting_age_population=800, minority_vap=500, registered_voters=700)
    blkB = add_block(api, jid, geoid="B", population=951, voting_age_population=700, minority_vap=200, registered_voters=600)
    plan = create_plan(api, jid, name="Pc")
    pid = plan["id"]
    d1 = create_district(api, pid, 1, is_contiguous=True)
    d2 = create_district(api, pid, 2, is_contiguous=False)
    assign_block(api, pid, d1["id"], blkA["id"])
    assign_block(api, pid, d2["id"], blkB["id"])
    got = _plan(api, pid, CART)
    assert got["is_compliant"] is False, "one non-contiguous district must flip is_compliant to false"


def test_contiguity_flip_keeps_deviation_passing(api):
    """PRD §3.3: "the max_abs_deviation_pct is at most 5.00% (the boundary is
    inclusive - exactly 5.00% still passes)".

    The deviation limb still passes (4.90 <= 5.00); only the contiguity limb fails,
    proving one boolean overrides two passing conditions.

    Design: Difficulty/combinatorial_formula/plan_compliance_gate_contiguity_flips
    """
    j = create_jurisdiction(api, name="Jc2", target_district_count=2, required_mm=0)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1049, voting_age_population=800, minority_vap=500, registered_voters=700)
    blkB = add_block(api, jid, geoid="B", population=951, voting_age_population=700, minority_vap=200, registered_voters=600)
    plan = create_plan(api, jid, name="Pc2")
    pid = plan["id"]
    d1 = create_district(api, pid, 1, is_contiguous=True)
    d2 = create_district(api, pid, 2, is_contiguous=False)
    assign_block(api, pid, d1["id"], blkA["id"])
    assign_block(api, pid, d2["id"], blkB["id"])
    got = _plan(api, pid, CART)
    assert got["max_abs_deviation_pct"] == 4.90, "deviation limb still passes at 4.90"
    assert got["is_compliant"] is False, "yet plan is non-compliant due to contiguity"


# ------------------------------------ combinatorial: rounding order (round then range)
def test_deviation_range_rounds_per_district_first(api):
    """PRD §3.3: "each district's deviation_pct is rounded to 2 decimal places
    first, and only then are the maximum, minimum, and range taken over those
    already-rounded values."

    Raw +2.125% -> 2.13 and -3.125% -> -3.13; range over rounded = 5.26.

    Design: Difficulty/combinatorial_formula/deviation_range_rounding_order
    """
    j = create_jurisdiction(api, name="Jr", target_district_count=2, required_mm=0)
    jid = j["id"]
    a2 = add_block(api, jid, geoid="A2", population=817, voting_age_population=600, minority_vap=100, registered_voters=500)
    b2 = add_block(api, jid, geoid="B2", population=775, voting_age_population=500, minority_vap=100, registered_voters=400)
    add_block(api, jid, geoid="C2", population=8, voting_age_population=6, minority_vap=1, registered_voters=5)
    plan = create_plan(api, jid, name="Pr")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    d2 = create_district(api, pid, 2)
    assign_block(api, pid, d1["id"], a2["id"])
    assign_block(api, pid, d2["id"], b2["id"])
    got = _plan(api, pid, CART)
    assert got["overall_deviation_range_pct"] == 5.26, \
        f"round-then-range must yield 5.26, got {got['overall_deviation_range_pct']}"


def test_max_abs_deviation_over_rounded_district_pcts(api):
    """PRD §3.3: "The plan's max_abs_deviation_pct is the maximum of the absolute
    values of the districts' rounded deviation percentages".

    With rounded 2.13 and -3.13, max-abs is 3.13.

    Design: Difficulty/combinatorial_formula/deviation_range_rounding_order
    """
    j = create_jurisdiction(api, name="Jr2", target_district_count=2, required_mm=0)
    jid = j["id"]
    a2 = add_block(api, jid, geoid="A2", population=817, voting_age_population=600, minority_vap=100, registered_voters=500)
    b2 = add_block(api, jid, geoid="B2", population=775, voting_age_population=500, minority_vap=100, registered_voters=400)
    add_block(api, jid, geoid="C2", population=8, voting_age_population=6, minority_vap=1, registered_voters=5)
    plan = create_plan(api, jid, name="Pr2")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    d2 = create_district(api, pid, 2)
    assign_block(api, pid, d1["id"], a2["id"])
    assign_block(api, pid, d2["id"], b2["id"])
    got = _plan(api, pid, CART)
    assert got["max_abs_deviation_pct"] == 3.13, \
        f"max-abs over rounded pcts must be 3.13, got {got['max_abs_deviation_pct']}"


# ------------------------------------ boundary: deviation exactly 5.00% compliant
def test_deviation_exactly_5pct_max_abs_value(api):
    """PRD §2.6: "Each district's `deviation_pct` measures how far that district's
    assigned population strays from the ideal, and is reported to 2 decimal places
    using round-half-up." Blocks 1050/950 vs ideal 1000 give +5.00%/-5.00%.

    Design: Difficulty/boundary_precision_check/deviation_exactly_5pct_is_compliant
    """
    j = create_jurisdiction(api, name="Jb", target_district_count=2, required_mm=0)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1050, voting_age_population=800, minority_vap=500, registered_voters=700)
    blkB = add_block(api, jid, geoid="B", population=950, voting_age_population=700, minority_vap=200, registered_voters=600)
    plan = create_plan(api, jid, name="Pb")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    d2 = create_district(api, pid, 2)
    assign_block(api, pid, d1["id"], blkA["id"])
    assign_block(api, pid, d2["id"], blkB["id"])
    got = _plan(api, pid)
    assert got["max_abs_deviation_pct"] == 5.00, f"expected 5.00, got {got['max_abs_deviation_pct']}"


def test_deviation_exactly_5pct_is_compliant(api):
    """PRD §3.3: "the max_abs_deviation_pct is at most 5.00% (the boundary is
    inclusive - exactly 5.00% still passes)".

    Design: Difficulty/boundary_precision_check/deviation_exactly_5pct_is_compliant
    """
    j = create_jurisdiction(api, name="Jb2", target_district_count=2, required_mm=0)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1050, voting_age_population=800, minority_vap=500, registered_voters=700)
    blkB = add_block(api, jid, geoid="B", population=950, voting_age_population=700, minority_vap=200, registered_voters=600)
    plan = create_plan(api, jid, name="Pb2")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    d2 = create_district(api, pid, 2)
    assign_block(api, pid, d1["id"], blkA["id"])
    assign_block(api, pid, d2["id"], blkB["id"])
    got = _plan(api, pid)
    assert got["is_compliant"] is True, "5.00% deviation is inclusive and must be compliant"


# ------------------------------------ boundary: minority exactly 50% not majority
def test_minority_vap_pct_exactly_fifty(api):
    """PRD §3.3: "Its minority_vap_pct is the sum of minority_vap divided by the
    sum of voting_age_population, taken over the district's active block
    assignments, multiplied by 100 and rounded to 2 decimal places". 400/800*100=50.00.

    Design: Difficulty/boundary_precision_check/minority_exactly_50pct_not_majority_minority
    """
    j = create_jurisdiction(api, name="Jv", target_district_count=1)
    jid = j["id"]
    blkM = add_block(api, jid, geoid="M", population=1000, voting_age_population=800, minority_vap=400, registered_voters=600)
    plan = create_plan(api, jid, name="Pv")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    assign_block(api, pid, d1["id"], blkM["id"])
    districts = _districts(api, pid)
    d = next(x for x in districts if x["id"] == d1["id"])
    assert d["minority_vap_pct"] == 50.00, f"expected 50.00, got {d['minority_vap_pct']}"


def test_minority_exactly_fifty_not_majority_minority(api):
    """PRD §3.3: "A district is flagged is_majority_minority when its
    minority_vap_pct is strictly greater than 50.0 - a district sitting at exactly
    50.00 is not majority-minority."

    Design: Difficulty/boundary_precision_check/minority_exactly_50pct_not_majority_minority
    """
    j = create_jurisdiction(api, name="Jv2", target_district_count=1)
    jid = j["id"]
    blkM = add_block(api, jid, geoid="M", population=1000, voting_age_population=800, minority_vap=400, registered_voters=600)
    plan = create_plan(api, jid, name="Pv2")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    assign_block(api, pid, d1["id"], blkM["id"])
    districts = _districts(api, pid)
    d = next(x for x in districts if x["id"] == d1["id"])
    assert d["is_majority_minority"] is False, "exactly 50.00% is NOT majority-minority (strict >)"
