"""Multi-step money formulas whose intermediate rounding and ordering are pinned.

Both scenarios chain four or five inputs into one figure, so a single reordered
step or a single rounding taken over a total rather than a part changes the answer.
"""

from typing import Any, Dict

from test_helpers import (
    TEST_USERS,
    assert_allocation_lines,
    assert_case_money_invariants,
    assert_disbursement,
    assert_funding_source_conservation,
    assert_pledge_capacity_identity,
    approve_disbursement,
    create_funding_source,
    create_project,
    permit_project,
    read_case,
    read_funding_source,
    read_member_org,
    request_disbursement,
    setup_awarded_case,
    validate_success,
)

UNRESTRICTED_POOL = {
    "label": "General donations 2026",
    "source_type": "INDIVIDUAL_DONATION",
    "restriction_code": "UNRESTRICTED",
    "total_cents": 2_000_000,
    "admin_retention_allowed": True,
}


def _setup_two_line_structure_draw() -> Dict[str, Any]:
    """An approved 3000000 net structure payment drawn across two restricted grants.

    The first grant holds 1552604 cents, which is exactly one net of 1500100 plus its
    own rounded retention, so the walk is forced to spill the remaining 1499900 onto
    the second grant — and the two nets round to retentions that do not agree with a
    single rounding over their sum.
    """
    scenario = setup_awarded_case(
        damage=[("STRUCTURE", 12_000_000)],
        orgs=[{"org_name": "First Methodist Recovery", "annual_pledge_cap_cents": 5_000_000}],
        pledges=[(0, 3_000_000, "STRUCTURE_REPAIR")],
        funding_sources=[UNRESTRICTED_POOL],
    )
    scenario["near_source"] = create_funding_source(
        label="Structure grant expiring October",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=1_552_604,
        expires_on="2026-10-31",
        admin_retention_allowed=True,
    )
    scenario["far_source"] = create_funding_source(
        label="Structure grant expiring November",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=3_000_000,
        expires_on="2026-11-30",
        admin_retention_allowed=True,
    )
    project = create_project(
        scenario["case"]["id"], required_trade_hours={"FRAMING": 200, "GENERAL_LABOR": 200}
    )
    permit_project(project["id"], "PB-3304")
    scenario["project"] = project
    scenario["requested"] = request_disbursement(
        scenario["case"]["id"],
        "STRUCTURE_REPAIR",
        3_000_000,
        project_id=project["id"],
        commitment_id=scenario["commitments"][0]["id"],
    )
    return scenario


def test_retention_is_rounded_on_each_allocation_line_and_the_lines_are_then_summed(api):
    """PRD §2.8: "**Administrative retention is rounded per allocation line, and the
    rounded line values are then summed.** Summing the net amounts first and rounding
    the retention once over the total produces a different figure and is incorrect.
    For example, two lines of 1500100 and 1499900 cents yield per-line retentions of
    52504 and 52497 cents, totalling 105001 cents, whereas rounding three and one-half
    percent of 3000000 cents once would yield 105000 cents."

    Design: Difficulty/combinatorial_formula/waterfall_retention_rounded_per_line_yields_105001_not_105000
    """
    scenario = _setup_two_line_structure_draw()

    approved = validate_success(
        api.approve_disbursement(
            scenario["requested"]["id"],
            {"approval_note": "Two-source draw approved"},
            TEST_USERS["ltrg_admin_headers"],
        )
    )

    assert_disbursement(approved)
    assert approved["status"] == "APPROVED"
    lines = approved["allocation_lines"]
    assert len(lines) == 2
    assert lines[0]["net_cents"] == 1_500_100
    assert lines[0]["retention_cents"] == 52_504
    assert lines[0]["gross_cents"] == 1_552_604
    assert lines[1]["net_cents"] == 1_499_900
    assert lines[1]["retention_cents"] == 52_497
    assert lines[1]["gross_cents"] == 1_552_397
    assert_allocation_lines(lines, 3_000_000, retention_allowed=True)
    assert approved["net_cents"] == 3_000_000
    # 52504 + 52497, not one rounding over 3000000 net.
    assert approved["admin_retained_cents"] == 105_001
    assert approved["gross_cents"] == 3_105_001


def test_waterfall_spends_restricted_money_first_and_nearest_expiry_first(api):
    """PRD §3.6: "The pool is then ordered by `restriction_specificity` descending, so
    restricted money is spent before unrestricted money and the flexible unrestricted
    balance is preserved for the cases that need it most; then by `expires_on`
    ascending with sources having no expiry ordered last, so money nearest to lapsing
    is used first; then by `created_at` ascending as the tie-break."

    Design: Difficulty/combinatorial_formula/waterfall_retention_rounded_per_line_yields_105001_not_105000
    """
    scenario = _setup_two_line_structure_draw()

    approved = approve_disbursement(scenario["requested"]["id"], "Two-source draw approved")

    line_sources = [line["funding_source_id"] for line in approved["allocation_lines"]]
    assert line_sources == [scenario["near_source"]["id"], scenario["far_source"]["id"]]
    unrestricted = read_funding_source(scenario["funding_sources"][0]["id"])
    assert unrestricted["committed_cents"] == 0
    assert unrestricted["available_cents"] == 2_000_000
    assert unrestricted["status"] == "OPEN"
    assert_funding_source_conservation(unrestricted)


def test_a_drawn_source_whose_availability_reaches_zero_moves_to_exhausted(api):
    """PRD §3.6: "For every drawn line the corresponding funding source's
    `committed_cents` increases by that line's gross and its `available_cents` is
    recomputed; any drawn source whose `available_cents` has reached 0 moves `OPEN →
    EXHAUSTED`."

    Design: Difficulty/combinatorial_formula/waterfall_retention_rounded_per_line_yields_105001_not_105000
    """
    scenario = _setup_two_line_structure_draw()

    approve_disbursement(scenario["requested"]["id"], "Two-source draw approved")

    near = read_funding_source(scenario["near_source"]["id"])
    assert near["committed_cents"] == 1_552_604
    assert near["available_cents"] == 0
    assert near["status"] == "EXHAUSTED"
    assert_funding_source_conservation(near)
    far = read_funding_source(scenario["far_source"]["id"])
    assert far["committed_cents"] == 1_552_397
    assert far["available_cents"] == 1_447_603
    assert far["status"] == "OPEN"
    assert_funding_source_conservation(far)


def _setup_capped_pledge_with_bridge() -> Dict[str, Any]:
    """A determined need of 3000000 with only 1500000 pledged against it.

    The organization's annual cap is what limits the pledge, so the gap is 1500000 —
    far more than the tier percentage of the determined need — which forces the bridge
    onto its own cap.
    """
    return setup_awarded_case(
        damage=[("STRUCTURE", 3_000_000)],
        orgs=[{"org_name": "Valley Interfaith Alliance", "annual_pledge_cap_cents": 1_500_000}],
        pledges=[(0, 1_500_000, "STRUCTURE_REPAIR")],
        funding_sources=[UNRESTRICTED_POOL],
    )


def test_bridge_tier_is_keyed_on_the_pinned_determined_need_not_on_the_award(api):
    """PRD §3.5: "The tier key is taken from the *pinned snapshot's*
    `unmet_need_total_cents`, never from `awarded_cents` — this is what resolves the
    apparent circularity in which the award depends on the bridge, the bridge on the
    tier, and the tier seemingly on the award."

    Design: Difficulty/combinatorial_formula/bridge_tier_keyed_on_pinned_unmet_not_on_awarded_total
    """
    scenario = _setup_capped_pledge_with_bridge()

    presentation = scenario["presentation"]

    assert scenario["assessment"]["unmet_need_total_cents"] == 3_000_000
    # 3000000 is not below the 2500000 TIER_B ceiling, so the key is TIER_C.
    assert presentation["bridge_tier"] == "TIER_C"
    # Keyed on awarded_cents instead, 1950000 would have selected TIER_B.
    assert presentation["awarded_cents"] == 1_950_000


def test_bridge_authorization_is_the_smallest_of_the_gap_the_cap_and_the_pool(api):
    """PRD §3.5: "`bridge_authorized_cents` is then the smallest of three quantities:
    the gap, the bridge cap and the bridge pool."

    Design: Difficulty/combinatorial_formula/bridge_tier_keyed_on_pinned_unmet_not_on_awarded_total
    """
    scenario = _setup_capped_pledge_with_bridge()

    presentation = scenario["presentation"]

    assert presentation["pledged_total_cents"] == 1_500_000
    # gap 1500000, cap 15 percent of 3000000 = 450000, pool 2000000.
    assert presentation["bridge_authorized_cents"] == 450_000
    assert presentation["awarded_cents"] == 1_950_000
    assert presentation["shortfall_cents"] == 1_050_000


def test_the_bridge_is_an_authorization_that_touches_no_funding_source(api):
    """PRD §3.5: "The bridge is an *authorization only*. No funding source field is
    touched at award time; unrestricted money is actually drawn later, at disbursement
    approval."

    Design: Difficulty/combinatorial_formula/bridge_tier_keyed_on_pinned_unmet_not_on_awarded_total
    """
    scenario = _setup_capped_pledge_with_bridge()

    source = read_funding_source(scenario["funding_sources"][0]["id"])
    assert source["available_cents"] == 2_000_000
    assert source["committed_cents"] == 0
    assert source["disbursed_cents"] == 0
    assert source["admin_retained_cents"] == 0
    assert source["status"] == "OPEN"
    assert_funding_source_conservation(source)

    org = read_member_org(scenario["member_orgs"][0]["id"])
    assert org["committed_cents"] == 1_500_000
    assert org["remaining_pledge_capacity_cents"] == 0
    assert org["status"] == "CAPPED"
    assert_pledge_capacity_identity(org)

    case = read_case(scenario["case"]["id"])
    assert case["total_committed_cents"] == 1_950_000
    assert case["reference_unmet_cents"] == 3_000_000
    assert case["residual_unmet_cents"] == 1_050_000
    assert_case_money_invariants(case)
