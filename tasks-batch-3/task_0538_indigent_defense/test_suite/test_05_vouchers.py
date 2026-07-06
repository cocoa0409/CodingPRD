"""Panel/service voucher billing: approval amount (min/cap branch), the
reject-revise-resubmit cycle, budget-restrict and void cascades on the office
ledger, the disposed-case submit gate, and voucher RBAC/ownership."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import make_attorney_headers

COORD = TEST_USERS["assignment_coordinator_headers"]
SUPER = TEST_USERS["supervising_attorney_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]


# ===========================================================================
# Difficulty: approved amount = min(gross, remaining fee cap)
# ===========================================================================

def test_panel_voucher_approved_amount_clamped_to_case_fee_cap(api):
    """PRD 3.7: "The server first computes a gross figure by rounding, half up to
    whole cents, the product of `claimed_hours` and the applicable hourly rate."
    PRD 3.7: "For a `PANEL_FEE` voucher the rate is the attorney's
    `hourly_rate_cents`, and the payable amount is capped by the case fee cap for
    the charge class net of prior panel approvals: take the case fee cap —
    $7,500 (750,000 cents) for `FELONY_A`, $5,000 (500,000 cents) for
    `FELONY_B`, $2,000 (200,000 cents) for `MISDEMEANOR`, $3,000 (300,000 cents)
    for `JUVENILE`, and $6,000 (600,000 cents) for `APPEAL` — subtract the sum of
    `approved_amount_cents` across this case's `PANEL_FEE` vouchers already in
    `APPROVED` status, floor that remaining cap at zero, and set
    `approved_amount_cents` to the lesser of the gross and the remaining cap."

    Design: Difficulty/combinatorial_formula/voucher_approved_amount_min_cap_branch
    """
    # MISDEMEANOR disposed case; PANEL attorney rate 15000; claimed 20h.
    # gross = 20 * 15000 = 300000; cap MISDEMEANOR = 200000; approved = 200000.
    ctx = fx.setup_submitted_panel_voucher(claimed_hours=20)
    approved = validate_success(api.approve_voucher(ctx["voucher"]["id"], SUPER), 200)
    assert approved["approved_amount_cents"] == 200_000


def test_panel_voucher_approved_status_after_clamped_approval(api):
    """PRD 3.7: "A `SupervisingAttorney` approves a submitted voucher (requiring
    `SUBMITTED`, else `ERR_VOUCHER_INVALID_STATE`) or rejects it to `REJECTED`
    (same state requirement)."

    Design: Difficulty/combinatorial_formula/voucher_approved_amount_min_cap_branch
    """
    ctx = fx.setup_submitted_panel_voucher(claimed_hours=20)
    approved = validate_success(api.approve_voucher(ctx["voucher"]["id"], SUPER), 200)
    assert approved["status"] == "APPROVED"


# ===========================================================================
# Difficulty: reject -> revise -> resubmit -> approve cycle
# ===========================================================================

def test_voucher_reject_revise_resubmit_approve_cycle(api):
    """PRD 3.7: "A `SupervisingAttorney` approves a submitted voucher (requiring
    `SUBMITTED`, else `ERR_VOUCHER_INVALID_STATE`) or rejects it to `REJECTED`
    (same state requirement)."
    PRD 3.7: "An `Attorney` may revise a rejected voucher, returning it from
    `REJECTED` to `DRAFT` (else `ERR_VOUCHER_INVALID_STATE`), which resets
    `approved_amount_cents` to 0 and allows `claimed_hours` to be re-edited
    before the next submission; this REJECTED-to-DRAFT-to-SUBMITTED path may
    cycle."

    Design: Difficulty/non_linear_state_machine/voucher_reject_revise_resubmit_cycle
    """
    ctx = fx.setup_submitted_panel_voucher(claimed_hours=5)
    vid = ctx["voucher"]["id"]
    att_headers = make_attorney_headers(ctx["attorney"]["id"])

    rejected = validate_success(api.reject_voucher(vid, SUPER), 200)
    assert rejected["status"] == "REJECTED"

    revised = validate_success(api.revise_voucher(vid, att_headers), 200)
    assert revised["status"] == "DRAFT"

    resubmitted = validate_success(api.submit_voucher(vid, att_headers), 200)
    assert resubmitted["status"] == "SUBMITTED"

    approved = validate_success(api.approve_voucher(vid, SUPER), 200)
    assert approved["status"] == "APPROVED"


def test_voucher_revise_resets_approved_amount_to_zero(api):
    """PRD 3.7: "An `Attorney` may revise a rejected voucher, returning it from
    `REJECTED` to `DRAFT` (else `ERR_VOUCHER_INVALID_STATE`), which resets
    `approved_amount_cents` to 0 and allows `claimed_hours` to be re-edited
    before the next submission; this REJECTED-to-DRAFT-to-SUBMITTED path may
    cycle."

    Design: Difficulty/non_linear_state_machine/voucher_reject_revise_resubmit_cycle
    """
    ctx = fx.setup_submitted_panel_voucher(claimed_hours=5)
    vid = ctx["voucher"]["id"]
    att_headers = make_attorney_headers(ctx["attorney"]["id"])
    validate_success(api.reject_voucher(vid, SUPER), 200)
    revised = validate_success(api.revise_voucher(vid, att_headers), 200)
    assert revised["status"] == "DRAFT"
    assert revised["approved_amount_cents"] == 0


# ===========================================================================
# Difficulty: approve cascade -> office spend rises -> budget RESTRICTED (depth 2)
# ===========================================================================

def test_voucher_approval_debits_office_and_computes_amount(api):
    """PRD 3.7: "Approving a voucher debits the office ledger: the office's
    `voucher_spent_cents` increases by the voucher's `approved_amount_cents`, and
    because spending rose, if `voucher_spent_cents` now exceeds ninety percent of
    the office's `annual_voucher_budget_cents` the office's `budget_status` flips
    to `RESTRICTED`."

    Design: Difficulty/transitive_cascade/voucher_approve_cascade_budget_restricted_depth2
    """
    # Office budget 200000; claimed 12.5h @ 15000 = 187500 (< MISDEMEANOR cap).
    ctx = fx.setup_submitted_panel_voucher(
        claimed_hours=12.5, office_overrides={"annual_voucher_budget_cents": 200_000})
    approved = validate_success(api.approve_voucher(ctx["voucher"]["id"], SUPER), 200)
    assert approved["approved_amount_cents"] == 187_500
    office = validate_success(api.get_defender_office(ctx["office"]["id"], CLERK), 200)
    assert office["voucher_spent_cents"] == 187_500


def test_voucher_approval_flips_office_to_restricted(api):
    """PRD 2.10: "The office flips to `RESTRICTED` the moment its
    `voucher_spent_cents` exceeds ninety percent of its
    `annual_voucher_budget_cents`."
    PRD 3.7: "if `voucher_spent_cents` now exceeds ninety percent of the office's
    `annual_voucher_budget_cents` the office's `budget_status` flips to
    `RESTRICTED`."

    Design: Difficulty/transitive_cascade/voucher_approve_cascade_budget_restricted_depth2
    """
    # 187500 > 0.90 * 200000 = 180000, so the office must flip to RESTRICTED.
    ctx = fx.setup_submitted_panel_voucher(
        claimed_hours=12.5, office_overrides={"annual_voucher_budget_cents": 200_000})
    validate_success(api.approve_voucher(ctx["voucher"]["id"], SUPER), 200)
    office = validate_success(api.get_defender_office(ctx["office"]["id"], CLERK), 200)
    assert office["budget_status"] == "RESTRICTED"


# ===========================================================================
# Difficulty: office budget conserved on void (compensation)
# ===========================================================================

def test_void_returns_office_spend_to_pre_approval_value(api):
    """PRD 3.7: "Voiding an approved voucher compensates that debit: the office's
    `voucher_spent_cents` decreases by the same `approved_amount_cents`, and if
    the result is at or below ninety percent of the budget the office returns to
    `OPEN`."
    PRD 3.7: "Finally, a `SupervisingAttorney` may void an approved voucher,
    moving it from `APPROVED` to the terminal `VOIDED` (else
    `ERR_VOUCHER_INVALID_STATE`)."

    Design: Difficulty/compensating_invariant/office_budget_conserved_on_void
    """
    # 5h @ 15000 = 75000 approved against a large-budget office.
    ctx = fx.setup_approved_panel_voucher(claimed_hours=5)
    before = validate_success(api.get_defender_office(ctx["office"]["id"], CLERK), 200)
    assert before["voucher_spent_cents"] == 75_000
    voided = validate_success(api.void_voucher(ctx["voucher"]["id"], SUPER), 200)
    assert voided["status"] == "VOIDED"
    after = validate_success(api.get_defender_office(ctx["office"]["id"], CLERK), 200)
    assert after["voucher_spent_cents"] == 0


def test_void_excludes_voided_voucher_from_office_spend_sum(api):
    """PRD 2.5: "A `DefenderOffice`'s `voucher_spent_cents` always equals the sum
    of `approved_amount_cents` across that office's vouchers currently in
    `APPROVED` status (vouchers that have been `VOIDED` are excluded); it starts
    at 0."

    Design: Difficulty/compensating_invariant/office_budget_conserved_on_void
    """
    ctx = fx.setup_approved_panel_voucher(claimed_hours=5)
    validate_success(api.void_voucher(ctx["voucher"]["id"], SUPER), 200)
    office = validate_success(api.get_defender_office(ctx["office"]["id"], CLERK), 200)
    # The single voucher is now VOIDED, so the sum over APPROVED vouchers is 0.
    assert office["voucher_spent_cents"] == 0


# ===========================================================================
# Difficulty: PANEL_FEE submit requires the case to be DISPOSED
# ===========================================================================

def test_panel_voucher_submit_blocked_while_case_assigned(api):
    """PRD 3.7: "Submission has a type-dependent precondition: a `PANEL_FEE`
    voucher may be submitted only once its parent case is `DISPOSED` (else
    `ERR_CASE_NOT_DISPOSED`), while a `SERVICE` voucher may be submitted only
    once its linked `ServiceRequest` is `COMPLETED` (else
    `ERR_SERVICE_REQUEST_NOT_COMPLETED`)."

    Design: Difficulty/cross_entity_state_dependency/panel_voucher_submit_requires_case_disposed
    """
    ctx = fx.setup_assigned_case(attorney_overrides={"attorney_type": "PANEL"},
                                 screening_overrides={"household_income_cents": 800_000})
    att_id = ctx["attorney"]["id"]
    voucher = validate_success(api.create_voucher(
        {"case_id": ctx["case"]["id"], "attorney_id": att_id,
         "voucher_type": "PANEL_FEE", "claimed_hours": 5}, make_attorney_headers(att_id)), 201)
    resp = api.submit_voucher(voucher["id"], make_attorney_headers(att_id))
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_DISPOSED.value)


def test_panel_voucher_stays_draft_when_submit_blocked(api):
    """PRD 3.7: "a `PANEL_FEE` voucher may be submitted only once its parent case
    is `DISPOSED` (else `ERR_CASE_NOT_DISPOSED`)"

    Design: Difficulty/cross_entity_state_dependency/panel_voucher_submit_requires_case_disposed
    """
    ctx = fx.setup_assigned_case(attorney_overrides={"attorney_type": "PANEL"},
                                 screening_overrides={"household_income_cents": 800_000})
    att_id = ctx["attorney"]["id"]
    voucher = validate_success(api.create_voucher(
        {"case_id": ctx["case"]["id"], "attorney_id": att_id,
         "voucher_type": "PANEL_FEE", "claimed_hours": 5}, make_attorney_headers(att_id)), 201)
    api.submit_voucher(voucher["id"], make_attorney_headers(att_id))
    still = validate_success(api.get_voucher(voucher["id"], CLERK), 200)
    assert still["status"] == "DRAFT"


# ===========================================================================
# Corner: RBAC — Attorney cannot approve a voucher
# ===========================================================================

def test_attorney_cannot_approve_voucher(api):
    """PRD 2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."
    PRD 2.1: "A `SupervisingAttorney` administers offices, attorneys, and
    courtrooms, suspends and reactivates attorneys, approves service requests,
    approves/rejects/voids vouchers, and collects or waives recoupment. An
    `Attorney` authors and submits their own vouchers."

    Design: Corner/rbac/attorney_cannot_approve_voucher
    """
    ctx = fx.setup_submitted_panel_voucher(claimed_hours=5)
    att_id = ctx["attorney"]["id"]
    resp = api.approve_voucher(ctx["voucher"]["id"], make_attorney_headers(att_id))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
    still = validate_success(api.get_voucher(ctx["voucher"]["id"], CLERK), 200)
    assert still["status"] == "SUBMITTED"


# ===========================================================================
# Corner: ownership — Attorney cannot create a voucher for another attorney
# ===========================================================================

def test_attorney_cannot_create_voucher_for_other_attorney(api):
    """PRD 2.1: "Concretely, when an `Attorney` creates, submits, or revises a
    `Voucher`, that voucher's `attorney_id` must equal `X-User-ID`, and a
    mismatch is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/attorney_cannot_create_voucher_for_other_attorney
    """
    ctx = fx.setup_disposed_case(attorney_overrides={"attorney_type": "PANEL", "name": "AttA",
                                                     "bar_number": "R3A"})
    att_a = ctx["attorney"]["id"]
    att_b = fx.create_attorney(ctx["office"]["id"], attorney_type="PANEL",
                               name="AttB", bar_number="R3B")["id"]
    # Caller acts as attorney A (X-User-ID == att_a) but claims attorney B's id.
    resp = api.create_voucher(
        {"case_id": ctx["case"]["id"], "attorney_id": att_b,
         "voucher_type": "PANEL_FEE", "claimed_hours": 5}, make_attorney_headers(att_a))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
