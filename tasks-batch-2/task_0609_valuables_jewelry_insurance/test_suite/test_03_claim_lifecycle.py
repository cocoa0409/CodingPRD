"""Claim adjudication: the bounded cyclic review loop, invalid transitions, the
partial-vs-total settle gate, total-loss settle side effects, and terminal lockdown.

Design queue A: non_linear_state_machine (claim cycle).
Design queue B: state_machines (claim invalid transitions, side effects, terminal lockdown).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_risk_zone,
    setup_claim_under_review,
    setup_approved_claim,
    make_policyholder_headers,
)

_UW = TEST_USERS["underwriter_headers"]
_CA = TEST_USERS["claims_adjuster_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Queue A: non_linear_state_machine — cyclic review loop bounded
# ─────────────────────────────────────────────────────────────────────────

def test_claim_review_cycle_bounded_at_max_info_requests(api):
    """PRD §3.11: "From UNDER_REVIEW the adjuster may request more information, moving the
    claim to INFO_REQUESTED and incrementing info_request_count by one; this is permitted
    only while info_request_count is below the limit of two, and a third request is rejected
    with ERR_INFO_REQUEST_LIMIT."

    Design: Difficulty/non_linear_state_machine/claim_cyclic_review_loop_bounded
    """
    ctx = setup_claim_under_review()
    pol, claim, ph = ctx["policy"], ctx["claim"], ctx["policyholder"]
    ph_headers = make_policyholder_headers(ph["id"])

    # Cycle 1: request -> provide.
    validate_success(api.request_info_claim(pol["id"], claim["id"], _CA), 200)
    validate_success(api.provide_info_claim(pol["id"], claim["id"], ph_headers), 200)
    # Cycle 2: request -> provide. Now info_request_count == 2.
    validate_success(api.request_info_claim(pol["id"], claim["id"], _CA), 200)
    validate_success(api.provide_info_claim(pol["id"], claim["id"], ph_headers), 200)

    # Third request_info is rejected.
    res = api.request_info_claim(pol["id"], claim["id"], _CA)
    validate_error(res, ApiErrorId.ERR_INFO_REQUEST_LIMIT, 409)


def test_claim_info_request_count_reaches_two(api):
    """PRD §3.11: "From UNDER_REVIEW the adjuster may request more information, moving the
    claim to INFO_REQUESTED and incrementing info_request_count by one"
    PRD §3.11: "The owning Policyholder answers by providing information, moving the claim
    from INFO_REQUESTED back to UNDER_REVIEW."

    Design: Difficulty/non_linear_state_machine/claim_cyclic_review_loop_bounded
    """
    ctx = setup_claim_under_review()
    pol, claim, ph = ctx["policy"], ctx["claim"], ctx["policyholder"]
    ph_headers = make_policyholder_headers(ph["id"])

    validate_success(api.request_info_claim(pol["id"], claim["id"], _CA), 200)
    validate_success(api.provide_info_claim(pol["id"], claim["id"], ph_headers), 200)
    validate_success(api.request_info_claim(pol["id"], claim["id"], _CA), 200)
    after = validate_success(api.provide_info_claim(pol["id"], claim["id"], ph_headers), 200)

    assert after["info_request_count"] == 2
    assert after["status"] == "UNDER_REVIEW"


# ─────────────────────────────────────────────────────────────────────────
# Queue B: state_machines — invalid transitions & side effects
# ─────────────────────────────────────────────────────────────────────────

def test_provide_info_from_under_review_rejected(api):
    """PRD §3.11: "The owning Policyholder answers by providing information, moving the claim
    from INFO_REQUESTED back to UNDER_REVIEW."
    PRD §2.10: "Only after these four global gates pass does the system evaluate state
    legality (ERR_INVALID_STATE, HTTP 409)"

    Design: Corner/state_machines/provide_info_from_under_review_returns_invalid_state
    """
    ctx = setup_claim_under_review()
    pol, claim, ph = ctx["policy"], ctx["claim"], ctx["policyholder"]
    ph_headers = make_policyholder_headers(ph["id"])
    # Claim is UNDER_REVIEW, not INFO_REQUESTED.
    res = api.provide_info_claim(pol["id"], claim["id"], ph_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)


def test_direct_settle_on_partial_damage_rejected(api):
    """PRD §3.13: "this direct settle is available only when loss_type is TOTAL_LOSS, and
    attempting it on a partial-damage claim is rejected with ERR_PARTIAL_REQUIRES_REPAIR
    because partial losses settle through repair-order closure."

    Design: Corner/state_machines/settle_partial_damage_returns_partial_requires_repair
    """
    ctx = setup_approved_claim(claim_overrides={
        "peril": "ACCIDENTAL_DAMAGE",
        "loss_type": "PARTIAL_DAMAGE",
        "claimed_amount_cents": 300000,
    })
    res = api.settle_claim(ctx["policy"]["id"], ctx["claim"]["id"], _CA)
    validate_error(res, ApiErrorId.ERR_PARTIAL_REQUIRES_REPAIR, 409)


def test_total_loss_settle_removes_item_and_recomputes_insured_value(api):
    """PRD §3.13: "On a total-loss settle the referenced scheduled item transitions from
    SUSPENDED to REMOVED, and the policy's total_insured_value_cents and annual_premium_cents
    are recomputed against the reduced item set."
    PRD §3.4: "items that are PENDING or REMOVED are excluded."

    Design: Corner/state_machines/total_loss_settle_removes_item_bubbles_premium
    """
    ctx = setup_approved_claim(claim_overrides={
        "peril": "THEFT", "loss_type": "TOTAL_LOSS", "claimed_amount_cents": 1000000,
    })
    settled = validate_success(
        api.settle_claim(ctx["policy"]["id"], ctx["claim"]["id"], _CA), 200)
    assert settled["settlement_cents"] == 950000  # cv 1,000,000 - STANDARD 50,000

    item = validate_success(api.get_scheduled_item(ctx["item"]["id"], _UW), 200)
    assert item["item_status"] == "REMOVED"

    policy = validate_success(api.get_policy(ctx["policy"]["id"], _UW), 200)
    assert policy["total_insured_value_cents"] == 0


def test_approve_on_closed_claim_rejected_with_invalid_state(api):
    """PRD §3.13: "Once a claim reaches SETTLED, the adjuster closes it, moving it from
    SETTLED to the terminal CLOSED status."
    PRD §2.10: "Only after these four global gates pass does the system evaluate state
    legality (ERR_INVALID_STATE, HTTP 409) and then the operation-specific business rules
    described in §3. Where an operation carries an OCC field, the stale-version check
    (ERR_STALE_VERSION) is the concurrency guard layered over that operation as described
    in §2.9."

    Design: Corner/state_machines/terminal_claim_close_then_reapprove_rejected
    """
    ctx = setup_approved_claim(claim_overrides={
        "peril": "THEFT", "loss_type": "TOTAL_LOSS", "claimed_amount_cents": 1000000,
    })
    pol, claim = ctx["policy"], ctx["claim"]
    claim_v = claim["version"]
    validate_success(api.settle_claim(pol["id"], claim["id"], _CA), 200)
    validate_success(api.close_claim(pol["id"], claim["id"], _CA), 200)

    # CLOSED is terminal; the state check (priority 5) fires before the OCC check (priority 21).
    res = api.approve_claim(pol["id"], claim["id"], {"expected_claim_version": claim_v}, _CA)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
