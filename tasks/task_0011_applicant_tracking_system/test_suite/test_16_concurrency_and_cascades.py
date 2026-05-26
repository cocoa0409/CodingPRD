"""Optimistic concurrency and immediate-consistency observability across the cascade chain.

PRD §3.6 allows offer revocation only from APPROVED or EXTENDED, while BackgroundCheck and
ReferralBonus rows are created only at offer ACCEPT — so the BGC-INITIATED-then-revoked
combination is not reachable through any PRD-declared path. The corresponding assertion is
therefore left unwritten rather than weakened.
"""
import pytest
from test_helpers import (
    api_client, validate_error, get_success_data, TEST_USERS,
    set_clock,
    setup_offer_in_state,
    create_department, create_requisition, submit_requisition, approve_requisition,
    create_offer, comp_approve_offer,
    approve_offer_payload, accept_offer,
    cancel_requisition_payload,
    make_headers,
)


# =========================================================================
# Instance: occ_stale_offer_version_on_vp_approve
# =========================================================================

def test_occ_stale_offer_version_on_vp_approve(api,
                                                comp_approver_headers,
                                                vp_headers):
    """PRD §2.7: "A request to approve an offer must carry
    `expected_offer_version` matching the offer's current `version` at the
    moment the server processes the request. If another writer has advanced
    the offer's version since the client last read it — for example, a
    reject call interleaving between the comp-approver step and the VP step,
    or a revoke landing between two approval polls — the approve is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_offer_version_on_vp_approve
    """
    set_clock("2027-12-01T00:00:00Z")
    ctx = setup_offer_in_state(
        "PENDING_APPROVAL",
        req_overrides={"base_salary_max_cents": 15_000_000},
        base_salary_cents=12_000_000,
    )
    offer = ctx["offer"]
    pre_comp_version = offer["version"]
    # Run the comp half — this bumps offer.version.
    comp_approve_offer(offer["id"], pre_comp_version, comp_headers=comp_approver_headers)
    # VP attempts approve carrying the PRE-comp version → stale.
    res = api_client.approve_offer(offer["id"],
                                   approve_offer_payload(pre_comp_version),
                                   vp_headers)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# =========================================================================
# Instance: occ_stale_requisition_version_on_cancel
# =========================================================================

def test_occ_stale_requisition_version_on_cancel(api, hiring_manager_headers):
    """PRD §2.7: "A request to cancel must carry
    `expected_requisition_version` matching the requisition's current
    `version`. If a system auto-transition or any other writer has advanced
    the requisition's version since the client's last read, the cancel is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_requisition_version_on_cancel
    """
    dept = create_department(budget_cents=100_000_000)
    req = create_requisition(dept["id"])
    initial_v = req["version"]
    submit_requisition(req["id"])
    approve_requisition(req["id"], hiring_manager_headers=hiring_manager_headers)
    # cancel with PRE-submit version (now stale — submit and approve have bumped it).
    res = api_client.cancel_requisition(
        req["id"], cancel_requisition_payload(initial_v),
        hiring_manager_headers,
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# =========================================================================
# Instance: immediate_consistency_filled_count_visible_in_same_response
# =========================================================================

def test_immediate_consistency_filled_count_visible_in_same_response(
        api, recruiter_headers):
    """PRD §3.4: "The successful pathway out is via offer acceptance: when
    an offer linked to the application transitions to `ACCEPTED`, the
    application moves to `HIRED` (see §3.6), which itself bubbles into the
    requisition's `filled_count` and may auto-close the requisition."
    PRD §3.2: "A requisition in `APPROVED` reaches `CLOSED` automatically
    when its computed `filled_count` equals its `openings`."

    Design: Corner/consistency_model/immediate_consistency_filled_count_visible_in_same_response
    """
    set_clock("2028-02-01T00:00:00Z")
    ctx = setup_offer_in_state(
        "EXTENDED",
        req_overrides={"openings": 1, "base_salary_max_cents": 15_000_000},
        base_salary_cents=12_000_000,
    )
    cand = ctx["candidate"]
    offer = ctx["offer"]
    accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))
    # Single GET — cascade chain must be visible immediately, no re-read needed.
    req_after = get_success_data(api_client.get_requisition(ctx["req"]["id"], recruiter_headers))
    assert req_after["filled_count"] == 1
    assert req_after["status"] == "CLOSED"
