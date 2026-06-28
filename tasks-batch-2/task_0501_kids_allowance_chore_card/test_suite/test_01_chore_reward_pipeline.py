"""Chore-to-reward pipeline: revision cycle, approval cascade, gating, RBAC.

Covers difficulty queue (non_linear_state_machine, transitive_cascade,
priority_pair_validation_conflict, cross_entity_state_dependency) and corner queue
(state_machines, validations, rbac) instances rooted in PRD Sections 3.3, 2.8, 2.9.
"""
from test_helpers import (
    validate_success, validate_error,
    make_child_headers,
    setup_pending_completion, get_spend_jar_id, get_card,
)


# ─── non_linear_state_machine: ChoreCompletion revision cycle ───────────────
def test_revision_cycle_increments_count_twice(api):
    """PRD 3.3: "The child then resubmits, moving the completion from `NEEDS_REVISION` back to `PENDING_REVIEW`, permitted only while it is `NEEDS_REVISION` and the acting child is the completion's `child_account_id`; each resubmission increments `revision_count` by one."
    PRD 3.3: "The kick-back and resubmit pair can repeat, and `revision_count` grows by one on every loop."

    Design: Difficulty/non_linear_state_machine/chore_completion_revision_cycle_increments_count
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=0, reward_cents=500)
    cid = completion["id"]
    child_h = make_child_headers(child["id"])

    validate_success(api.kick_back_completion(cid, ph), 200)
    validate_success(api.resubmit_completion(cid, child_h), 200)
    validate_success(api.kick_back_completion(cid, ph), 200)
    final = validate_success(api.resubmit_completion(cid, child_h), 200)

    assert final["status"] == "PENDING_REVIEW"
    assert final["revision_count"] == 2, f"expected revision_count 2, got {final['revision_count']}"


def test_first_resubmit_sets_revision_count_one_and_pending(api):
    """PRD 3.3: "The child then resubmits, moving the completion from `NEEDS_REVISION` back to `PENDING_REVIEW`, permitted only while it is `NEEDS_REVISION` and the acting child is the completion's `child_account_id`; each resubmission increments `revision_count` by one."

    Design: Difficulty/non_linear_state_machine/chore_completion_revision_cycle_increments_count
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=0, reward_cents=500)
    cid = completion["id"]
    child_h = make_child_headers(child["id"])

    validate_success(api.kick_back_completion(cid, ph), 200)
    after = validate_success(api.resubmit_completion(cid, child_h), 200)

    assert after["status"] == "PENDING_REVIEW"
    assert after["revision_count"] == 1


# ─── transitive_cascade: approve -> funding -> jar -> card (depth 3) ─────────
def test_approve_cascade_debits_funding_credits_jar_funds_card(api):
    """PRD 3.3: "first the family's `funding_balance_cents` is reduced by `reward_cents_snapshot`; second the child's jar of the snapshot's `payout_jar_type_snapshot` has its `balance_cents` increased by `reward_cents_snapshot`, which is the step that actually mutates the jar; and third that jar credit raises the jar's `lifetime_credited_cents`, and if the credited jar is the `SPEND` jar the balance change recomputes the debit card's `funding_state` and `available_cents`."

    Design: Difficulty/transitive_cascade/chore_approve_cascade_funding_jar_card_depth3
    """
    fam, child, chore, completion, ph = setup_pending_completion(
        deposit_cents=10_000, reward_cents=1500, payout_jar_type="SPEND")
    spend_jar_id = get_spend_jar_id(child["id"], ph)
    card = get_card(child["id"], ph)

    validate_success(api.approve_completion(completion["id"], ph), 200)

    fam_after = validate_success(api.get_family(fam["id"], ph), 200)
    jar_after = validate_success(api.get_jar(spend_jar_id, ph), 200)
    card_after = validate_success(api.get_debit_card(card["id"], ph), 200)

    assert fam_after["funding_balance_cents"] == 8500
    assert jar_after["balance_cents"] == 1500
    assert card_after["funding_state"] == "FUNDED"
    assert card_after["available_cents"] == 1500


def test_approve_marks_completion_paid(api):
    """PRD 3.3: "The completion's `status` becomes `PAID`, and the parent chore bubbles up automatically: a chore in `SUBMITTED` advances to a transient `APPROVED` state that resolves immediately, returning the chore to `AVAILABLE` if it is recurring, or moving it to `ARCHIVED` if it is not."

    Design: Difficulty/transitive_cascade/chore_approve_cascade_funding_jar_card_depth3
    """
    fam, child, chore, completion, ph = setup_pending_completion(
        deposit_cents=10_000, reward_cents=1500, payout_jar_type="SPEND")

    paid = validate_success(api.approve_completion(completion["id"], ph), 200)
    assert paid["status"] == "PAID"

    chore_after = validate_success(api.get_chore(chore["id"], ph), 200)
    assert chore_after["status"] == "ARCHIVED"


# ─── priority_pair: family suspended beats insufficient funding ─────────────
def test_family_suspended_beats_insufficient_funding_on_approve(api):
    """PRD 2.9: "The recurring principle is that a more fundamental failure is never masked by a later check: a suspended family surfaces as `ERR_FAMILY_SUSPENDED` rather than as an insufficient-funds error that a later step might have raised."
    PRD 2.8: "any chore approval, allowance run, interest accrual, or card authorization for a child of a suspended family is rejected with `ERR_FAMILY_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/family_suspended_beats_insufficient_funding
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=0, reward_cents=5000)
    # funding is 0 (insufficient) AND family suspended -> suspension must win.
    validate_success(api.suspend_family(fam["id"], ph), 200)

    res = api.approve_completion(completion["id"], ph)
    validate_error(res, "ERR_FAMILY_SUSPENDED")


def test_child_archived_beats_insufficient_funding_does_not_apply_here(api):
    """PRD 2.9: "The remaining business checks ... funding-wallet sufficiency (`ERR_INSUFFICIENT_FUNDING`) ... are evaluated within the workflow that owns each"
    PRD 3.3: "if the wallet cannot cover the snapshot it fails with `ERR_INSUFFICIENT_FUNDING"

    With an ACTIVE family and ACTIVE child but a wallet of 0, the surviving lower-priority arm
    (insufficient funding) is what surfaces — confirming the pair's loser is reachable in isolation.

    Design: Difficulty/priority_pair_validation_conflict/family_suspended_beats_insufficient_funding
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=0, reward_cents=5000)
    res = api.approve_completion(completion["id"], ph)
    validate_error(res, "ERR_INSUFFICIENT_FUNDING")


# ─── cross_entity_state_dependency: approve requires Family ACTIVE ──────────
def test_approve_blocked_when_family_suspended_funding_sufficient(api):
    """PRD 3.3: "approval additionally requires that the family is `ACTIVE`, that the child account is `ACTIVE`, and that the family's `funding_balance_cents` is at least the completion's `reward_cents_snapshot`. If the family is suspended the approval fails with `ERR_FAMILY_SUSPENDED"

    Design: Difficulty/cross_entity_state_dependency/chore_approve_requires_family_active
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=10_000, reward_cents=1500)
    validate_success(api.suspend_family(fam["id"], ph), 200)

    res = api.approve_completion(completion["id"], ph)
    validate_error(res, "ERR_FAMILY_SUSPENDED")

    comp_after = validate_success(api.get_completion(completion["id"], ph), 200)
    assert comp_after["status"] == "PENDING_REVIEW"
    fam_after = validate_success(api.get_family(fam["id"], ph), 200)
    assert fam_after["funding_balance_cents"] == 10_000


def test_approve_succeeds_after_family_reactivated(api):
    """PRD 3.1: "Suspending it sets `status` to `SUSPENDED` and, per Section 2.8, blocks all downstream money movement; reactivating it returns `status` to `ACTIVE`."
    PRD 3.3: "When approval proceeds it pays the reward in three cascading steps: first the family's `funding_balance_cents` is reduced by `reward_cents_snapshot"

    Design: Difficulty/cross_entity_state_dependency/chore_approve_requires_family_active
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=10_000, reward_cents=1500)
    validate_success(api.suspend_family(fam["id"], ph), 200)
    validate_error(api.approve_completion(completion["id"], ph), "ERR_FAMILY_SUSPENDED")

    validate_success(api.reactivate_family(fam["id"], ph), 200)
    paid = validate_success(api.approve_completion(completion["id"], ph), 200)
    assert paid["status"] == "PAID"
    fam_after = validate_success(api.get_family(fam["id"], ph), 200)
    assert fam_after["funding_balance_cents"] == 8500


# ─── corner: invalid transitions / side effects / validations / rbac ───────
def test_approve_already_paid_completion_returns_invalid_state(api):
    """PRD 3.3: "A parent approves a completion only while it is `PENDING_REVIEW ... and a completion not in `PENDING_REVIEW` fails the state check with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_already_paid_completion_returns_invalid_state
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=10_000, reward_cents=500)
    validate_success(api.approve_completion(completion["id"], ph), 200)  # now PAID, funding 9500

    res = api.approve_completion(completion["id"], ph)
    validate_error(res, "ERR_INVALID_STATE")
    fam_after = validate_success(api.get_family(fam["id"], ph), 200)
    assert fam_after["funding_balance_cents"] == 9500


def test_resubmit_from_pending_review_returns_invalid_state(api):
    """PRD 3.3: "The child then resubmits, moving the completion from `NEEDS_REVISION` back to `PENDING_REVIEW`, permitted only while it is `NEEDS_REVISION` and the acting child is the completion's `child_account_id"

    Design: Corner/state_machines/resubmit_from_pending_review_returns_invalid_state
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=0, reward_cents=300)
    child_h = make_child_headers(child["id"])

    res = api.resubmit_completion(completion["id"], child_h)
    validate_error(res, "ERR_INVALID_STATE")
    comp_after = validate_success(api.get_completion(completion["id"], ph), 200)
    assert comp_after["status"] == "PENDING_REVIEW"
    assert comp_after["revision_count"] == 0


def test_deny_sets_completion_denied_chore_rejected_no_money(api):
    """PRD 3.3: "A parent may instead deny a completion, moving it from `PENDING_REVIEW` to `DENIED`; denial moves no money and additionally transitions the parent chore to `REJECTED`."

    Design: Corner/state_machines/deny_compensation_sets_chore_rejected_no_money
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=10_000, reward_cents=1500)

    denied = validate_success(api.deny_completion(completion["id"], ph), 200)
    assert denied["status"] == "DENIED"
    chore_after = validate_success(api.get_chore(chore["id"], ph), 200)
    assert chore_after["status"] == "REJECTED"
    fam_after = validate_success(api.get_family(fam["id"], ph), 200)
    assert fam_after["funding_balance_cents"] == 10_000


def test_archived_child_cannot_earn_reward(api):
    """PRD 3.3: "if the child is archived it fails with `ERR_CHILD_ARCHIVED"
    PRD 2.8: "an archived child cannot earn rewards, spend, or accrue interest, and any such attempt is rejected with `ERR_CHILD_ARCHIVED`."

    Design: Corner/validations/archived_child_cannot_earn_reward
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=10_000, reward_cents=1500)
    validate_success(api.archive_child_account(child["id"], ph), 200)

    res = api.approve_completion(completion["id"], ph)
    validate_error(res, "ERR_CHILD_ARCHIVED")
    fam_after = validate_success(api.get_family(fam["id"], ph), 200)
    assert fam_after["funding_balance_cents"] == 10_000


def test_insufficient_funding_on_chore_approve(api):
    """PRD 3.3: "if the wallet cannot cover the snapshot it fails with `ERR_INSUFFICIENT_FUNDING"

    Design: Corner/validations/insufficient_funding_on_chore_approve
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=1000, reward_cents=1500)

    res = api.approve_completion(completion["id"], ph)
    validate_error(res, "ERR_INSUFFICIENT_FUNDING")
    comp_after = validate_success(api.get_completion(completion["id"], ph), 200)
    assert comp_after["status"] == "PENDING_REVIEW"


def test_child_cannot_approve_completion(api):
    """PRD 2.1: "When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Approve is a Parent-authorized operation (Section 4 endpoint table lists Parent only); a Child
    caller is not permitted.

    Design: Corner/rbac/child_cannot_approve_completion
    """
    fam, child, chore, completion, ph = setup_pending_completion(deposit_cents=10_000, reward_cents=500)
    child_h = make_child_headers(child["id"])

    res = api.approve_completion(completion["id"], child_h)
    validate_error(res, "ERR_FORBIDDEN_ROLE")
    comp_after = validate_success(api.get_completion(completion["id"], ph), 200)
    assert comp_after["status"] == "PENDING_REVIEW"
