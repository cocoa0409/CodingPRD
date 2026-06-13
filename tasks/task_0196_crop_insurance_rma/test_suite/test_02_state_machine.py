"""Lifecycle state machines: initial states, invalid transitions, preconditions.

Covers the loss-claim initial state, invalid/terminal transition rejections, the
program-close / policy-activate / policy-cancel precondition gates, and the
election bubble-up when all units report (PRD §3.1-§3.6).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_reported_unit, setup_policy_with_election, setup_election_with_unit,
    setup_submitted_loss_claim, setup_program_and_parties,
    file_loss_claim, register_adjuster, create_policy, add_unit, file_acreage_report,
    make_lossadjuster_headers, TEST_USERS,
)


def test_new_loss_claim_starts_in_draft(api):
    """PRD §3.6: "A new claim begins in DRAFT with indemnity_cents at zero and
    revision_count at zero."

    Design: Corner/state_machines/new_loss_claim_starts_in_draft
    """
    ctx = setup_reported_unit(plan_type="YP", acres=100, share=1,
                              clock="2026-06-01T00:00:00Z")
    adj = register_adjuster(license_number="ADJ-INIT")
    claim = file_loss_claim(ctx["unit"]["id"], adj["id"], ctx["sa_headers"],
                            production_to_count_bu=9000)
    assert claim["status"] == "DRAFT", claim["status"]
    assert claim["indemnity_cents"] == 0, claim["indemnity_cents"]
    assert claim["revision_count"] == 0, claim["revision_count"]


def test_approve_loss_claim_from_draft_rejected(api):
    """PRD §2.9: "the state-machine check that the target resource is in a state from which
    the requested transition is defined (ERR_INVALID_STATE)."
    PRD §3.6: "From UNDER_REVIEW the adjuster may instead approve or deny the claim."

    Design: Corner/state_machines/approve_loss_claim_from_draft_returns_invalid_state
    """
    # DRAFT (unsubmitted) claim, distinct assigned adjuster (not the selling agent).
    ctx = setup_reported_unit(plan_type="YP", acres=100, share=1, publish_harvest=5.20,
                              clock="2026-06-01T00:00:00Z")
    adj = register_adjuster(license_number="ADJ-DRAFT")
    claim = file_loss_claim(ctx["unit"]["id"], adj["id"], ctx["sa_headers"],
                            production_to_count_bu=9000)
    res = api.approve_loss_claim(claim["id"], make_lossadjuster_headers(adj["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_loss_claim(claim["id"], ctx["sa_headers"]))
    assert after["status"] == "DRAFT", after["status"]


def test_pay_paid_claim_again_rejected(api):
    """PRD §3.6: "Finally, an RmaAdmin pays an approved claim, moving it from APPROVED to
    PAID, which marks the indemnity disbursed. DENIED and PAID are the claim's terminal
    states."

    Design: Corner/state_machines/pay_terminal_paid_claim_again_returns_invalid_state
    """
    ctx = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                     publish_harvest=5.20)
    validate_success(api.approve_loss_claim(ctx["claim"]["id"], ctx["adj_headers"]), 200)
    rma = TEST_USERS["rma_admin_headers"]
    validate_success(api.pay_loss_claim(ctx["claim"]["id"], rma), 200)
    res = api.pay_loss_claim(ctx["claim"]["id"], rma)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_loss_claim(ctx["claim"]["id"], ctx["sa_headers"]))
    assert after["status"] == "PAID", after["status"]


def test_close_program_with_open_election_rejected(api):
    """PRD §3.1: "A program cannot be closed while any coverage election that references it
    is still in ELECTED status — that attempt is rejected with
    ERR_PROGRAM_HAS_OPEN_ELECTIONS."

    Design: Corner/state_machines/close_program_with_open_election_returns_has_open_elections
    """
    ctx = setup_policy_with_election(plan_type="YP", aph_yield=180, coverage_level=0.75)
    rma = TEST_USERS["rma_admin_headers"]
    res = api.close_commodity_program(ctx["program"]["id"], rma)
    validate_error(res, "ERR_PROGRAM_HAS_OPEN_ELECTIONS")
    prog = get_success_data(api.get_commodity_program(ctx["program"]["id"], rma))
    assert prog["status"] == "OPEN", prog["status"]


def test_activate_policy_without_elections_rejected(api):
    """PRD §3.2: "Activation is permitted only when at least one coverage election under
    the policy is in ELECTED status; otherwise it is rejected with
    ERR_POLICY_HAS_NO_ELECTIONS."

    Design: Corner/state_machines/activate_policy_without_elections_returns_no_elections
    """
    ctx = setup_program_and_parties()
    policy = create_policy(ctx["producer"]["id"], ctx["sa"]["id"], ctx["sa_headers"])
    res = api.activate_policy(policy["id"], ctx["sa_headers"])
    validate_error(res, "ERR_POLICY_HAS_NO_ELECTIONS")
    after = get_success_data(api.get_policy(policy["id"], ctx["sa_headers"]))
    assert after["status"] == "DRAFT", after["status"]


def test_cancel_policy_with_approved_claim_rejected(api):
    """PRD §3.2: "A policy may not be cancelled while any loss claim or prevented-planting
    claim beneath it is in UNDER_REVIEW or APPROVED; that attempt is rejected with
    ERR_POLICY_HAS_OPEN_CLAIMS."

    Design: Corner/state_machines/cancel_policy_with_approved_claim_returns_has_open_claims
    """
    # Build to an APPROVED (not yet paid) loss claim under an ACTIVE policy.
    # Activate the policy BEFORE the unit is reported: activation requires an ELECTED
    # election (PRD §3.2), and accepting an acreage report bubbles the sole-unit election
    # from ELECTED to REPORTED (PRD §3.5), which would then leave the policy with no
    # ELECTED election to activate. Activating first leaves the election ELECTED, after
    # which the report and the claim flow proceed.
    ctx = setup_election_with_unit(plan_type="YP", acres=100, share=1, publish_harvest=5.20,
                                   clock="2026-06-01T00:00:00Z")
    validate_success(api.activate_policy(ctx["policy"]["id"], ctx["sa_headers"]), 200)
    file_acreage_report(ctx["unit"]["id"], ctx["sa_headers"], ctx["unit"]["version"],
                        planted_acres=100, prevented_acres=0)
    adj = register_adjuster(license_number="ADJ-OPEN")
    claim = file_loss_claim(ctx["unit"]["id"], adj["id"], ctx["sa_headers"],
                            production_to_count_bu=10000)
    api.submit_loss_claim(claim["id"], ctx["sa_headers"])
    validate_success(api.approve_loss_claim(claim["id"], make_lossadjuster_headers(adj["id"])), 200)
    res = api.cancel_policy(ctx["policy"]["id"], ctx["sa_headers"])
    validate_error(res, "ERR_POLICY_HAS_OPEN_CLAIMS")
    after = get_success_data(api.get_policy(ctx["policy"]["id"], ctx["sa_headers"]))
    assert after["status"] == "ACTIVE", after["status"]


def test_election_bubbles_to_reported_only_when_all_units_reported(api):
    """PRD §3.5: "If accepting this report means every sibling unit under the election is
    now REPORTED, the election bubbles up from ELECTED to REPORTED, signaling it is
    eligible for loss adjustment."

    Design: Corner/state_machines/election_to_reported_bubbles_up_when_all_units_reported
    """
    ctx = setup_policy_with_election(plan_type="YP", aph_yield=180, coverage_level=0.75,
                                     clock="2026-06-01T00:00:00Z")
    unit1 = add_unit(ctx["election"]["id"], ctx["sa_headers"], unit_number="0001-0001",
                     acres=60, share=1)
    unit2 = add_unit(ctx["election"]["id"], ctx["sa_headers"], unit_number="0001-0002",
                     acres=40, share=1)
    file_acreage_report(unit1["id"], ctx["sa_headers"], unit1["version"],
                        planted_acres=60, prevented_acres=0)
    mid = get_success_data(api.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    assert mid["status"] == "ELECTED", mid["status"]
    file_acreage_report(unit2["id"], ctx["sa_headers"], unit2["version"],
                        planted_acres=40, prevented_acres=0)
    final = get_success_data(api.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    assert final["status"] == "REPORTED", final["status"]
