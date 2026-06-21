"""Optimistic concurrency (OCC) and immediate-consistency ledger checks.

Queue B (Corner) — cross_cutting and consistency_model sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_comp_plan_payload,
    TEST_USERS,
    setup_calibrated_review_in_comp_planning,
    setup_comp_planning_with_n_calibrated_reviews,
    create_comp_plan_for, approve_plan,
    make_manager_headers, make_comp_approver_headers,
)

HR = TEST_USERS["hr_admin_headers"]


def test_occ_stale_cycle_on_second_approve(api):
    """PRD §2.6: "If another approval has advanced those ledgers since the client
    last read the cycle, the approve is rejected with `ERR_STALE_CYCLE_VERSION`
    (HTTP 412)".

    Design: Corner/cross_cutting/occ_stale_cycle_on_second_approve
    """
    ctx = setup_comp_planning_with_n_calibrated_reviews(
        n=2, band_label="MEETS", band_merit_pct=0.04,
        merit_budget_pct=0.5, equity_refresh_pool=100000)
    cyc_id = ctx["cycle"]["id"]
    appr_id = ctx["approver"]["id"]
    appr_hdr = make_comp_approver_headers(appr_id)

    plan0 = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
    plan1 = create_comp_plan_for(cyc_id, ctx["reviews"][1]["id"], ctx["reviewers"][1]["id"])
    validate_success(api.propose_comp_plan(plan0["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
    validate_success(api.propose_comp_plan(plan1["id"], make_manager_headers(ctx["reviewers"][1]["id"])), 200)

    cyc = get_success_data(api.get_cycle(cyc_id, appr_hdr))
    stale_version = cyc["version"]
    # First approve advances the cycle version.
    validate_success(api.approve_comp_plan(
        plan0["id"], {"expected_cycle_version": stale_version}, appr_hdr), 200)
    # Second approve carries the pre-advance (stale) version.
    res = api.approve_comp_plan(
        plan1["id"], {"expected_cycle_version": stale_version}, appr_hdr)
    validate_error(res, "ERR_STALE_CYCLE_VERSION")


def test_occ_stale_review_on_comp_plan_create(api):
    """PRD §2.6: "A create request must carry `expected_review_version` equal to
    the target `Review`'s current `version`. If the review's version has advanced
    since the client last observed it ... the create is rejected with
    `ERR_STALE_REVIEW_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting/occ_stale_review_on_comp_plan_create
    """
    ctx = setup_calibrated_review_in_comp_planning(band_label="MEETS", band_merit_pct=0.04)
    mgr_hdr = make_manager_headers(ctx["manager"]["id"])
    rev = get_success_data(api.get_review(ctx["review"]["id"], mgr_hdr))
    payload = create_comp_plan_payload(
        ctx["cycle"]["id"], ctx["review"]["id"], rev["version"] - 1, plan_type="MERIT_ONLY")
    res = api.create_comp_plan(payload, mgr_hdr)
    validate_error(res, "ERR_STALE_REVIEW_VERSION")


def test_ledger_reflects_approve_immediately(api):
    """PRD §2.7: "`merit_committed_total`, the sum of `merit_amount` across all of
    the cycle's compensation plans that are in the `APPROVED` state". PRD §3.8:
    "approval adds the plan's `merit_amount` to the cycle's `merit_committed_total`".

    MEETS band 0.04, base_salary 120000 -> merit_amount 4800.00; after approve
    GET /cycles shows merit_committed_total 4800.00.

    Design: Corner/consistency_model/ledger_reflects_approve_immediately
    """
    ctx = setup_comp_planning_with_n_calibrated_reviews(
        n=1, band_label="MEETS", band_merit_pct=0.04,
        merit_budget_pct=0.5, equity_refresh_pool=100000,
        base_salaries=[120000])
    cyc_id = ctx["cycle"]["id"]
    plan = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
    assert plan["merit_amount"] == 4800.00
    validate_success(api.propose_comp_plan(plan["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
    validate_success(approve_plan(plan["id"], cyc_id, ctx["approver"]["id"]), 200)
    cyc = validate_success(api.get_cycle(cyc_id, HR), 200)
    assert cyc["merit_committed_total"] == 4800.00
