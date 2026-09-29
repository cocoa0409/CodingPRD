"""Undo operations measured against the identities they are supposed to restore.

Neither of these is a soft delete. Each is required to put a conserved quantity back
to the exact figure it held before, while leaving the record that caused it in place.
"""

from typing import Any, Dict

from test_helpers import (
    TEST_USERS,
    approve_disbursement,
    assert_case_money_invariants,
    assert_funding_commitment,
    assert_funding_source_conservation,
    assert_member_organization,
    assert_pledge_capacity_identity,
    assert_version_bumped,
    create_funding_source,
    create_project,
    make_member_org_delegate_headers,
    pay_disbursement,
    permit_project,
    read_case,
    read_funding_source,
    read_member_org,
    read_presentation,
    request_disbursement,
    setup_awarded_case,
    validate_success,
)

ADMIN = TEST_USERS["ltrg_admin_headers"]

UNRESTRICTED_POOL = {
    "label": "General donations 2026",
    "source_type": "INDIVIDUAL_DONATION",
    "restriction_code": "UNRESTRICTED",
    "total_cents": 2_000_000,
    "admin_retention_allowed": True,
}

RESCISSION_REASON = "Board reallocated the fund to a different disaster."
REVERSAL_REASON = "Contractor withdrew before mobilisation; funds returned."


def _setup_award_carried_by_a_capped_organization() -> Dict[str, Any]:
    """A 3000000 need where one organization pledged its entire annual cap.

    The organization is `CAPPED` at award time, and the 15 percent tier bridge adds
    450000 on top of the 1500000 pledge.
    """
    return setup_awarded_case(
        damage=[("STRUCTURE", 3_000_000)],
        orgs=[{"org_name": "Summit Valley Charities", "annual_pledge_cap_cents": 1_500_000}],
        pledges=[(0, 1_500_000, "STRUCTURE_REPAIR")],
        funding_sources=[UNRESTRICTED_POOL],
    )


def test_rescinding_a_confirmed_pledge_restores_the_annual_cap_exactly(api):
    """PRD §2.9: "The conserved identity is that `remaining_pledge_capacity_cents` equals
    `annual_pledge_cap_cents` less the sum of `committed_cents` and `disbursed_cents`."

    Design: Difficulty/compensating_invariant/rescind_restores_member_org_pledge_capacity_to_its_annual_cap_exactly
    """
    scenario = _setup_award_carried_by_a_capped_organization()
    org_id = scenario["member_orgs"][0]["id"]
    before = read_member_org(org_id)
    assert before["committed_cents"] == 1_500_000
    assert before["remaining_pledge_capacity_cents"] == 0
    assert before["status"] == "CAPPED"
    commitment = scenario["commitments"][0]

    rescinded = validate_success(
        api.rescind_funding_commitment(
            commitment["id"],
            {"rescission_reason": RESCISSION_REASON},
            make_member_org_delegate_headers(org_id),
        )
    )

    assert_funding_commitment(rescinded)
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["rescission_reason"] == RESCISSION_REASON
    assert_version_bumped(commitment, rescinded, by=2)
    after = read_member_org(org_id)
    assert_member_organization(after)
    assert after["committed_cents"] == 0
    assert after["disbursed_cents"] == 0
    # Back to the untouched annual cap, to the cent.
    assert after["remaining_pledge_capacity_cents"] == after["annual_pledge_cap_cents"]
    assert after["remaining_pledge_capacity_cents"] == 1_500_000
    assert_pledge_capacity_identity(after)
    assert after["status"] == "ACTIVE"


def test_rescission_recomputes_the_award_downward_and_the_case_ledger_with_it(api):
    """PRD §3.5: "because the organization released capacity, the presentation's
    `awarded_cents` — which is recomputed downward — and `shortfall_cents`, and the
    case's `total_committed_cents`, `residual_unmet_cents` and `funding_status` are all
    recomputed"

    Design: Difficulty/compensating_invariant/rescind_restores_member_org_pledge_capacity_to_its_annual_cap_exactly
    """
    scenario = _setup_award_carried_by_a_capped_organization()
    assert scenario["presentation"]["bridge_tier"] == "TIER_C"
    assert scenario["presentation"]["bridge_authorized_cents"] == 450_000
    assert scenario["presentation"]["awarded_cents"] == 1_950_000

    validate_success(
        api.rescind_funding_commitment(
            scenario["commitments"][0]["id"],
            {"rescission_reason": RESCISSION_REASON},
            make_member_org_delegate_headers(scenario["member_orgs"][0]["id"]),
        )
    )

    presentation = read_presentation(scenario["presentation"]["id"])
    assert presentation["pledged_total_cents"] == 0
    # The bridge was an authorization, so only the pledged part of the award is undone.
    assert presentation["bridge_authorized_cents"] == 450_000
    assert presentation["awarded_cents"] == 450_000
    assert presentation["shortfall_cents"] == 2_550_000
    case = read_case(scenario["case"]["id"])
    assert case["total_committed_cents"] == 450_000
    assert case["residual_unmet_cents"] == 2_550_000
    assert_case_money_invariants(case)
    assert case["funding_status"] == "PARTIALLY_COMMITTED"
    assert case["case_status"] == "ACTIVE_RECOVERY"


def _setup_paid_draw_on_a_single_grant() -> Dict[str, Any]:
    """A paid 1000000 net payment that consumed a grant of exactly 1035000 cents.

    The payment names no commitment, so the only conserved quantity it disturbed is the
    funding source's, and the grant holds precisely the net plus the retention that net
    attracts — it ends up `EXHAUSTED` to the cent.
    """
    scenario = setup_awarded_case(
        damage=[("STRUCTURE", 2_000_000)],
        orgs=[{"org_name": "Ironwood Community Trust", "annual_pledge_cap_cents": 4_000_000}],
        pledges=[(0, 2_000_000, "STRUCTURE_REPAIR")],
    )
    scenario["source"] = create_funding_source(
        label="Rebuild grant, single draw",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=1_035_000,
        expires_on="2026-12-31",
        admin_retention_allowed=True,
    )
    project = create_project(scenario["case"]["id"], required_trade_hours={"FRAMING": 180})
    permit_project(project["id"], "PB-3323")
    scenario["project"] = project
    row = request_disbursement(
        scenario["case"]["id"], "STRUCTURE_REPAIR", 1_000_000, project_id=project["id"]
    )
    approve_disbursement(row["id"], "Approved for rebuild")
    scenario["disbursement"] = pay_disbursement(row["id"], "CHK-3323")
    return scenario


def test_reversal_returns_the_funding_source_to_its_face_value(api):
    """PRD §2.9: "reversal removes them from `disbursed_cents` and
    `admin_retained_cents`, restoring availability."

    Design: Difficulty/compensating_invariant/reverse_restores_funding_source_conservation_identity_exactly
    """
    scenario = _setup_paid_draw_on_a_single_grant()
    before = read_funding_source(scenario["source"]["id"])
    assert before["available_cents"] == 0
    assert before["committed_cents"] == 0
    assert before["disbursed_cents"] == 1_000_000
    assert before["admin_retained_cents"] == 35_000
    assert before["status"] == "EXHAUSTED"
    assert_funding_source_conservation(before)

    reversed_row = validate_success(
        api.reverse_disbursement(
            scenario["disbursement"]["id"], {"reversal_reason": REVERSAL_REASON}, ADMIN
        )
    )

    assert reversed_row["status"] == "REVERSED"
    after = read_funding_source(scenario["source"]["id"])
    assert after["total_cents"] == 1_035_000
    assert after["available_cents"] == 1_035_000
    assert after["committed_cents"] == 0
    assert after["disbursed_cents"] == 0
    assert after["admin_retained_cents"] == 0
    assert after["status"] == "OPEN"
    assert_funding_source_conservation(after)
    # The reversal is compensating, not erasing: the row keeps what it was paid for.
    assert reversed_row["net_cents"] == 1_000_000
    assert reversed_row["admin_retained_cents"] == 35_000
    assert reversed_row["gross_cents"] == 1_035_000


def test_reversal_rewinds_the_money_axis_to_fully_committed(api):
    """PRD §2.5: "Otherwise, if `total_committed_cents` is greater than or equal to
    `reference_unmet_cents`, `funding_status` becomes `FULLY_COMMITTED`."

    Design: Difficulty/compensating_invariant/reverse_restores_funding_source_conservation_identity_exactly
    """
    scenario = _setup_paid_draw_on_a_single_grant()
    before = read_case(scenario["case"]["id"])
    assert before["total_net_disbursed_cents"] == 1_000_000
    assert before["total_committed_cents"] == 2_000_000
    # 1000000 paid against 2000000 committed is short of the committed total.
    assert before["funding_status"] == "DISBURSING"

    validate_success(
        api.reverse_disbursement(
            scenario["disbursement"]["id"], {"reversal_reason": REVERSAL_REASON}, ADMIN
        )
    )

    case = read_case(scenario["case"]["id"])
    assert case["total_net_disbursed_cents"] == 0
    assert case["total_committed_cents"] == 2_000_000
    assert case["residual_unmet_cents"] == 0
    assert_case_money_invariants(case)
    assert case["funding_status"] == "FULLY_COMMITTED"
    assert case["case_status"] == "ACTIVE_RECOVERY"
    # No commitment was named, so no organization figure moved either way.
    org = read_member_org(scenario["member_orgs"][0]["id"])
    assert org["committed_cents"] == 2_000_000
    assert org["disbursed_cents"] == 0
    assert_pledge_capacity_identity(org)
