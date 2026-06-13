"""Loss-claim adjustment workflow: the segregated, branching, cyclic review loop.

Covers the revision loop (PRD §3.6), the approve-vs-deny branch divergence, immediate
indemnity visibility, the harvest-price-availability gate, adjuster-assignment gate,
and the cross-entity precondition that a unit be reported before a claim is submitted.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_submitted_loss_claim, setup_reported_unit, setup_election_with_unit,
    file_loss_claim, make_lossadjuster_headers, register_adjuster,
)


def test_loss_claim_revision_loop_increments_revision_count(api):
    """PRD §3.6: "The assigned adjuster may return the claim for rework, moving it from
    UNDER_REVIEW back to DRAFT and incrementing its revision_count by one; the claim may
    then be resubmitted, so a claim can cycle through DRAFT → UNDER_REVIEW → DRAFT any
    number of times."

    Design: Difficulty/non_linear_state_machine/nonlinear_lossclaim_revision_loop_cycle
    """
    ctx = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                     publish_harvest=5.20)
    cid = ctx["claim"]["id"]
    # round 1: return -> DRAFT (rc=1), resubmit -> UNDER_REVIEW
    api.return_loss_claim(cid, ctx["adj_headers"])
    api.submit_loss_claim(cid, ctx["sa_headers"])
    # round 2: return -> DRAFT (rc=2), resubmit -> UNDER_REVIEW
    api.return_loss_claim(cid, ctx["adj_headers"])
    final = validate_success(api.submit_loss_claim(cid, ctx["sa_headers"]), 200)
    assert final["revision_count"] == 2, final["revision_count"]
    assert final["status"] == "UNDER_REVIEW", final["status"]


def test_single_return_puts_claim_back_to_draft(api):
    """PRD §3.6: "The assigned adjuster may return the claim for rework, moving it from
    UNDER_REVIEW back to DRAFT and incrementing its revision_count by one"

    Design: Difficulty/non_linear_state_machine/nonlinear_lossclaim_revision_loop_cycle
    """
    ctx = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                     publish_harvest=5.20)
    res = validate_success(api.return_loss_claim(ctx["claim"]["id"], ctx["adj_headers"]), 200)
    assert res["status"] == "DRAFT", res["status"]
    assert res["revision_count"] == 1, res["revision_count"]


def test_approve_and_deny_branches_diverge_on_policy_ledger(api):
    """PRD §3.6: "Approval moves the claim from UNDER_REVIEW to APPROVED, computes and
    sets its indemnity_cents by the methodology of §3.7 ... the approved indemnity_cents
    is added into the policy's total_indemnity_cents"
    PRD §3.6: "Denial moves the claim from UNDER_REVIEW to DENIED, leaving indemnity_cents
    at zero, and likewise settles the unit if no other open claim remains."

    Design: Difficulty/non_linear_state_machine/nonlinear_lossclaim_branch_approve_vs_deny_divergent_effects
    """
    # Approve branch.
    ap = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                    publish_harvest=5.20)
    ap_res = validate_success(api.approve_loss_claim(ap["claim"]["id"], ap["adj_headers"]), 200)
    assert ap_res["status"] == "APPROVED"
    assert ap_res["indemnity_cents"] == 1400000, ap_res["indemnity_cents"]
    ap_policy = get_success_data(api.get_policy(ap["policy"]["id"], ap["sa_headers"]))
    assert ap_policy["total_indemnity_cents"] == 1400000, ap_policy["total_indemnity_cents"]

    # Deny branch (built identically).
    dn = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                    publish_harvest=5.20)
    dn_res = validate_success(api.deny_loss_claim(dn["claim"]["id"], dn["adj_headers"]), 200)
    assert dn_res["status"] == "DENIED"
    assert dn_res["indemnity_cents"] == 0, dn_res["indemnity_cents"]
    dn_policy = get_success_data(api.get_policy(dn["policy"]["id"], dn["sa_headers"]))
    assert dn_policy["total_indemnity_cents"] == 0, dn_policy["total_indemnity_cents"]


def test_approve_vs_deny_diverge_on_claim_indemnity(api):
    """PRD §3.6: "Approval moves the claim from UNDER_REVIEW to APPROVED, computes and sets
    its indemnity_cents by the methodology of §3.7"
    PRD §3.6: "Denial moves the claim from UNDER_REVIEW to DENIED, leaving indemnity_cents
    at zero"

    Design: Difficulty/non_linear_state_machine/nonlinear_lossclaim_branch_approve_vs_deny_divergent_effects
    """
    # Two identically-built claims diverge only by branch; assert claim-level fields.
    ap = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                    publish_harvest=5.20)
    ap_res = validate_success(api.approve_loss_claim(ap["claim"]["id"], ap["adj_headers"]), 200)
    dn = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                    publish_harvest=5.20)
    dn_res = validate_success(api.deny_loss_claim(dn["claim"]["id"], dn["adj_headers"]), 200)
    assert ap_res["status"] == "APPROVED" and ap_res["indemnity_cents"] == 1400000
    assert dn_res["status"] == "DENIED" and dn_res["indemnity_cents"] == 0


def test_approved_indemnity_visible_in_same_response(api):
    """PRD §3.6: "Approval moves the claim from UNDER_REVIEW to APPROVED, computes and
    sets its indemnity_cents by the methodology of §3.7 (which is required to be at least
    zero)"

    Design: Corner/consistency_model/immediate_indemnity_visible_in_same_request
    """
    ctx = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                     publish_harvest=5.20)
    res = validate_success(api.approve_loss_claim(ctx["claim"]["id"], ctx["adj_headers"]), 200)
    assert res["status"] == "APPROVED"
    assert res["indemnity_cents"] == 1400000, res["indemnity_cents"]


def test_loss_submit_requires_unit_reported(api):
    """PRD §3.6: "Submission requires that the unit be REPORTED or ACTIVE; submitting
    against a unit not yet reported is rejected with ERR_UNIT_NOT_REPORTED."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_loss_submit_requires_unit_reported
    """
    # Unit PENDING (no acreage report). File a claim, then attempt submit.
    ctx = setup_election_with_unit(plan_type="YP", acres=100, share=1)
    adj = register_adjuster(license_number="ADJ-CROSS")
    claim = file_loss_claim(ctx["unit"]["id"], adj["id"], ctx["sa_headers"],
                            production_to_count_bu=10000)
    res = api.submit_loss_claim(claim["id"], ctx["sa_headers"])
    validate_error(res, "ERR_UNIT_NOT_REPORTED")
    after = get_success_data(api.get_loss_claim(claim["id"], ctx["sa_headers"]))
    assert after["status"] == "DRAFT", after["status"]


def test_loss_submit_succeeds_when_unit_reported(api):
    """PRD §3.6: "Submission requires that the unit be REPORTED or ACTIVE ... On submission,
    a unit that was REPORTED advances to ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_loss_submit_requires_unit_reported
    """
    # Same cross-entity dependency, positive side: a REPORTED unit lets submit proceed,
    # and the unit advances REPORTED -> ACTIVE.
    ctx = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                     publish_harvest=5.20)
    claim = get_success_data(api.get_loss_claim(ctx["claim"]["id"], ctx["sa_headers"]))
    assert claim["status"] == "UNDER_REVIEW", claim["status"]
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], ctx["sa_headers"]))
    assert unit["status"] == "ACTIVE", unit["status"]


def test_loss_submit_rp_without_harvest_price_rejected(api):
    """PRD §3.6: "For revenue plans — that is, an election whose plan_type is RP or RP_HPE
    — submission additionally requires that the commodity program's harvest price has been
    published; otherwise it is rejected with ERR_HARVEST_PRICE_UNAVAILABLE."

    Design: Corner/validations/loss_submit_rp_without_harvest_price_returns_unavailable
    """
    # RP election, REPORTED unit, harvest NOT published.
    ctx = setup_reported_unit(plan_type="RP", acres=100, share=1, publish_harvest=None)
    adj = register_adjuster(license_number="ADJ-NOHV")
    claim = file_loss_claim(ctx["unit"]["id"], adj["id"], ctx["sa_headers"],
                            production_to_count_bu=10000)
    res = api.submit_loss_claim(claim["id"], ctx["sa_headers"])
    validate_error(res, "ERR_HARVEST_PRICE_UNAVAILABLE")
    after = get_success_data(api.get_loss_claim(claim["id"], ctx["sa_headers"]))
    assert after["status"] == "DRAFT", after["status"]


def test_loss_approve_by_unassigned_adjuster_rejected(api):
    """PRD §3.6: "Both approval and denial enforce two safety rules in turn: the acting
    adjuster must be the claim's assigned_adjuster_id (else ERR_ADJUSTER_NOT_ASSIGNED)"

    Design: Corner/validations/loss_approve_by_unassigned_adjuster_returns_not_assigned
    """
    # Claim assigned to ctx adjuster; a different adjuster (not the selling agent) approves.
    ctx = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                     publish_harvest=5.20)
    other = register_adjuster(license_number="ADJ-OTHER")
    res = api.approve_loss_claim(ctx["claim"]["id"], make_lossadjuster_headers(other["id"]))
    validate_error(res, "ERR_ADJUSTER_NOT_ASSIGNED")
    after = get_success_data(api.get_loss_claim(ctx["claim"]["id"], ctx["sa_headers"]))
    assert after["status"] == "UNDER_REVIEW", after["status"]
