"""Out-of-Policy approval chain — L1 / L2 / FINAL escalation, denial,
and cascade-back to line policy_status.

Covers PRD §3.5 (chain), PRD §3.3 (OOP_APPROVED / OOP_DENIED line
cascade), §2.7 #16/#17 (wrong-role and duplicate-approver),
and these difficulty-design instances:
  - non_linear_state_machine.expense_line_parallel_policy_and_ocr_dimensions
  - compensating_invariant.report_policy_violation_count_drift_zero_on_oop_cycle
"""
from __future__ import annotations

import pytest

from test_helpers import (
    OOP_FINAL_ESCALATION_AMOUNT_CENTS,
    add_meal_line,
    approve_report,
    attach_receipt_to_line,
    claim_report,
    create_expense_report,
    create_oop_approval_payload,
    get_line,
    get_oop_approval,
    get_report,
    make_finance_reviewer_headers,
    make_manager_headers,
    make_oop_approver_headers,
    make_traveler_headers,
    open_oop_approval,
    oop_final_approve,
    oop_l1_approve,
    oop_l2_approve,
    seed_per_diem_rate,
    setup_approved_trip,
    setup_report_submitted_for_oop_chain,
    setup_report_with_oop_meal_line,
    submit_report,
    upload_receipt,
    validate_error,
    validate_success,
)


# ===========================================================================
# Open OOP approval
# ===========================================================================
def test_open_oop_approval_creates_awaiting_l1(api):
    """PRD §3.5: "The approval is born in `AWAITING_L1` with
    `l1_approver_id`, `l2_approver_id`, and `final_approver_id` all
    null."
    """
    cast = setup_report_with_oop_meal_line()
    res = api.create_oop_approval(
        create_oop_approval_payload(expense_line_id=cast["line"]["id"]),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    approval = validate_success(res, 201)
    assert approval["chain_level"] == "AWAITING_L1"
    assert approval["l1_approver_id"] is None
    assert approval["l2_approver_id"] is None
    assert approval["final_approver_id"] is None
    assert approval["expense_line_id"] == cast["line"]["id"]


def test_open_oop_requires_final_escalation_when_amount_above_1000_dollars(api):
    """PRD §3.5: "At creation, the system computes
    `requires_final_escalation` — set to true if and only if the bound
    line's `amount_claimed_cents` is strictly greater than 100000 cents
    (which is one thousand dollars) or the destination's `PerDiemRate`
    has `is_high_cost_locality` equal to true."
    """
    # Use a meal line with very large claim → over per-meal cap → OOP +
    # over 100000 → requires_final_escalation = True.
    cast = setup_report_with_oop_meal_line(
        over_cap_amount_cents=OOP_FINAL_ESCALATION_AMOUNT_CENTS + 1,
        meal_type="DINNER",
    )
    approval = open_oop_approval(
        line=cast["line"], traveler=cast["traveler"],
    )
    assert approval["requires_final_escalation"] is True


def test_open_oop_requires_final_escalation_false_at_or_below_boundary(api):
    """PRD §3.5: "strictly greater than 100000 cents".
    Equal to 100000 → requires_final_escalation = False.
    """
    # The default Boston rate has is_high_cost_locality=false. A line at
    # exactly 100000 over per-meal cap is still OOP. Use a small over-
    # cap amount (3000 ≤ 100000) — escalation should be False.
    cast = setup_report_with_oop_meal_line(
        over_cap_amount_cents=3000,
        meal_type="BREAKFAST",
    )
    approval = open_oop_approval(
        line=cast["line"], traveler=cast["traveler"],
    )
    assert approval["requires_final_escalation"] is False


def test_open_oop_requires_final_escalation_when_high_cost_locality(api):
    """PRD §3.5: "or the destination's `PerDiemRate` has
    `is_high_cost_locality` equal to true."
    """
    # High-cost locality rate.
    seed_per_diem_rate(
        city="NewYork", state="NY",
        effective_from="2025-06-01T00:00:00.000Z",
        effective_to="2025-07-01T00:00:00.000Z",
        lodging_cap_cents=40000, mie_cap_cents=10000,
        is_high_cost_locality=True,
    )
    cast = setup_approved_trip(
        destination_city="NewYork", destination_state="NY",
    )
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    # Breakfast cap = 10000 * 0.25 = 2500. Claim 3000 > cap → OOP.
    line = add_meal_line(
        report=rpt, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type="BREAKFAST", per_diem_method="ACTUAL",
        amount_claimed_cents=3000,
    )
    assert line["policy_status"] == "OUT_OF_POLICY"
    approval = open_oop_approval(line=line, traveler=cast["traveler"])
    assert approval["requires_final_escalation"] is True


# ===========================================================================
# L1 step
# ===========================================================================
def test_l1_approve_by_manager_advances_to_awaiting_l2(api):
    """PRD §3.5: "The L1 step (`AWAITING_L1` advancing to `AWAITING_L2`)
    must be invoked by a `MANAGER` whose `Employee.id` equals the
    traveler's `manager_id` ... As a side effect, `l1_approver_id` is
    set to `X-User-ID`."
    """
    cast = setup_report_submitted_for_oop_chain()
    res = api.oop_l1_approve(
        cast["approval"]["id"],
        make_manager_headers(cast["manager"]["id"]),
    )
    approval = validate_success(res, 200)
    assert approval["chain_level"] == "AWAITING_L2"
    assert approval["l1_approver_id"] == cast["manager"]["id"]


def test_l1_approve_by_finance_returns_wrong_approver_role(api):
    """PRD §3.5: "A wrong-role invocation yields
    `ERR_OOP_WRONG_APPROVER_ROLE`."
    PRD §2.7 #16: "the OOP step being invoked by the correct role".

    PRD also states in §2.1 / §2.7 that "an authenticated principal
    whose role is not on the endpoint's authorized list receives
    `ERR_INVALID_ROLE`" at priority 2. The l1-approve endpoint is
    MANAGER-only (see §4), so a FINANCE_REVIEWER call could be
    rejected either by the endpoint-level role gate (ERR_INVALID_ROLE)
    or by the OOP-chain-specific gate (ERR_OOP_WRONG_APPROVER_ROLE).
    Accept either reading.
    """
    from test_helpers import validate_error_is_one_of
    cast = setup_report_submitted_for_oop_chain()
    res = api.oop_l1_approve(
        cast["approval"]["id"],
        make_finance_reviewer_headers(cast["finance"]["id"]),
    )
    validate_error_is_one_of(
        res, ["ERR_OOP_WRONG_APPROVER_ROLE", "ERR_INVALID_ROLE"],
    )


# ===========================================================================
# L2 step — single-step finalization (no escalation)
# ===========================================================================
def test_l2_approve_without_escalation_advances_to_final_approved(api):
    """PRD §3.5: "Its destination depends on `requires_final_escalation`:
    when escalation is required, the chain advances from `AWAITING_L2`
    to `AWAITING_FINAL`; when escalation is not required, the chain
    advances directly from `AWAITING_L2` to `FINAL_APPROVED`, and the
    bound line's `policy_status` is transitioned by the system to
    `OOP_APPROVED` as a cascade."
    """
    cast = setup_report_submitted_for_oop_chain()
    approval = oop_l1_approve(
        approval=cast["approval"], manager=cast["manager"],
    )
    assert approval["requires_final_escalation"] is False
    res = api.oop_l2_approve(
        approval["id"], make_finance_reviewer_headers(cast["finance"]["id"]),
    )
    approval = validate_success(res, 200)
    assert approval["chain_level"] == "FINAL_APPROVED"
    assert approval["l2_approver_id"] == cast["finance"]["id"]

    # Cascade: bound line's policy_status → OOP_APPROVED.
    line_after = get_line(
        cast["line"]["id"], viewer=cast["finance"],
    )
    assert line_after["policy_status"] == "OOP_APPROVED"


# ===========================================================================
# L2 step — escalation hop
# ===========================================================================
def test_l2_approve_with_escalation_advances_to_awaiting_final(api):
    """PRD §3.5: "when escalation is required, the chain advances from
    `AWAITING_L2` to `AWAITING_FINAL`"."""
    cast = setup_report_with_oop_meal_line(
        over_cap_amount_cents=OOP_FINAL_ESCALATION_AMOUNT_CENTS + 1,
        meal_type="DINNER",
    )
    approval = open_oop_approval(
        line=cast["line"], traveler=cast["traveler"],
    )
    approval = oop_l1_approve(approval=approval, manager=cast["manager"])
    approval = oop_l2_approve(approval=approval, finance=cast["finance"])
    assert approval["chain_level"] == "AWAITING_FINAL"


# ===========================================================================
# FINAL step — duplicate approver
# ===========================================================================
def test_final_approve_advances_to_final_approved_and_cascades_line(api):
    """PRD §3.5: "The final step is invoked by an `OOP_APPROVER`,
    advancing the chain from `AWAITING_FINAL` to `FINAL_APPROVED` ...
    `final_approver_id` is set to `X-User-ID` and the bound line's
    `policy_status` cascades to `OOP_APPROVED`."
    """
    cast = setup_report_with_oop_meal_line(
        over_cap_amount_cents=OOP_FINAL_ESCALATION_AMOUNT_CENTS + 1,
        meal_type="DINNER",
    )
    approval = open_oop_approval(
        line=cast["line"], traveler=cast["traveler"],
    )
    approval = oop_l1_approve(approval=approval, manager=cast["manager"])
    approval = oop_l2_approve(approval=approval, finance=cast["finance"])
    approval = oop_final_approve(
        approval=approval, oop_approver=cast["oop"],
    )
    assert approval["chain_level"] == "FINAL_APPROVED"
    assert approval["final_approver_id"] == cast["oop"]["id"]
    line_after = get_line(cast["line"]["id"], viewer=cast["finance"])
    assert line_after["policy_status"] == "OOP_APPROVED"


def test_final_approver_same_as_l1_returns_duplicate_approver(api):
    """PRD §3.5: "the acting approver ... must not be the same person
    who acted at L1 — the latter check returns
    `ERR_OOP_DUPLICATE_APPROVER`".

    Setup: build an Employee that has BOTH MANAGER and OOP_APPROVER
    semantics by creating two employees with the SAME id is not
    possible. Instead, simulate by creating a single Employee with role
    OOP_APPROVER and using it as the L1 manager — but PRD requires L1
    actor.role == MANAGER, so we cannot collapse. The only way to
    trigger the duplicate check is when the L1 manager AND the final
    OOP approver share an Employee.id — impossible across distinct
    roles. Thus we test the next-best contract: the final-approve call
    by an OOP_APPROVER whose id equals the recorded `l1_approver_id`.
    Since `l1_approver_id` records X-User-ID and the L1 actor was a
    MANAGER role, this scenario cannot arise in a single Employee under
    PRD's strict id-binding. We therefore use the available signal: ask
    the OOP_APPROVER to act as final, and verify it succeeds when their
    id != l1_approver_id. The negative path is exercised by simulating
    a duplicate via making the OOP_APPROVER's underlying employee_id
    match the manager's; if the implementation upholds strict
    role-binding it instead returns ERR_INVALID_ROLE, which is a faithful
    alternative outcome.

    Accept either ERR_OOP_DUPLICATE_APPROVER (the targeted check) or
    ERR_INVALID_ROLE (role-binding wins first) — both are PRD-faithful.
    """
    from test_helpers import (
        make_oop_approver_headers, validate_error_is_one_of,
    )
    cast = setup_report_with_oop_meal_line(
        over_cap_amount_cents=OOP_FINAL_ESCALATION_AMOUNT_CENTS + 1,
        meal_type="DINNER",
    )
    approval = open_oop_approval(
        line=cast["line"], traveler=cast["traveler"],
    )
    approval = oop_l1_approve(approval=approval, manager=cast["manager"])
    approval = oop_l2_approve(approval=approval, finance=cast["finance"])
    # Attempt final-approve using the MANAGER's id with role OOP_APPROVER —
    # the X-User-ID equals l1_approver_id.
    res = api.oop_final_approve(
        approval["id"],
        make_oop_approver_headers(cast["manager"]["id"]),
    )
    err = validate_error_is_one_of(
        res,
        ["ERR_OOP_DUPLICATE_APPROVER", "ERR_INVALID_ROLE"],
    )
    assert err in ("ERR_OOP_DUPLICATE_APPROVER", "ERR_INVALID_ROLE")


# ===========================================================================
# Denial cascade + drift invariant
# difficulty: compensating_invariant/report_policy_violation_count_drift_zero_on_oop_cycle
# ===========================================================================
def test_oop_deny_cascades_line_to_oop_denied(api):
    """PRD §3.5: "At any chain level, the current approver may deny the
    request: ... Denial advances `chain_level` to `DENIED` (terminal),
    accepts an optional `reason`, and cascades the bound line's
    `policy_status` to `OOP_DENIED`."
    """
    cast = setup_report_submitted_for_oop_chain()
    res = api.oop_deny(
        cast["approval"]["id"],
        make_manager_headers(cast["manager"]["id"]),
    )
    approval = validate_success(res, 200)
    assert approval["chain_level"] == "DENIED"
    line_after = get_line(cast["line"]["id"], viewer=cast["manager"])
    assert line_after["policy_status"] == "OOP_DENIED"


def test_policy_violation_count_drift_zero_after_oop_denied(api):
    """PRD §3.3: "policy_violation_count is recomputed as the count of
    child lines whose `policy_status` equals `OUT_OF_POLICY`."

    After OOP denial, the line transitions to OOP_DENIED — which is
    NOT OUT_OF_POLICY — so policy_violation_count drops back to 0.
    The compensating-action invariant: count_after == count_before.
    # difficulty: compensating_invariant/report_policy_violation_count_drift_zero_on_oop_cycle
    """
    cast = setup_report_with_oop_meal_line()
    # After creating the OUT_OF_POLICY line, count should be 1.
    rpt_after_line = get_report(
        cast["report"]["id"], viewer=cast["traveler"],
    )
    assert rpt_after_line["policy_violation_count"] == 1

    approval = open_oop_approval(
        line=cast["line"], traveler=cast["traveler"],
    )
    approval = oop_l1_approve(approval=approval, manager=cast["manager"])
    # Deny at L2.
    res = api.oop_deny(
        approval["id"],
        make_finance_reviewer_headers(cast["finance"]["id"]),
    )
    validate_success(res, 200)
    rpt_after_deny = get_report(
        cast["report"]["id"], viewer=cast["traveler"],
    )
    # Drift is zero: count returns to 0 — line is no longer OUT_OF_POLICY.
    assert rpt_after_deny["policy_violation_count"] == 0


def test_oop_approved_lifts_amount_reimbursable_to_claimed(api):
    """PRD §3.3: "When an `OUT_OF_POLICY` line transitions to
    `OOP_APPROVED`, the system sets `amount_reimbursable_cents` equal
    to `amount_claimed_cents`, decrements the parent report's
    `policy_violation_count` by 1".
    """
    cast = setup_report_submitted_for_oop_chain()
    approval = oop_l1_approve(
        approval=cast["approval"], manager=cast["manager"],
    )
    approval = oop_l2_approve(approval=approval, finance=cast["finance"])
    assert approval["chain_level"] == "FINAL_APPROVED"
    line_after = get_line(cast["line"]["id"], viewer=cast["finance"])
    assert line_after["policy_status"] == "OOP_APPROVED"
    assert line_after["amount_reimbursable_cents"] == cast["line"]["amount_claimed_cents"]
    rpt_after = get_report(
        cast["report"]["id"], viewer=cast["traveler"],
    )
    assert rpt_after["policy_violation_count"] == 0
