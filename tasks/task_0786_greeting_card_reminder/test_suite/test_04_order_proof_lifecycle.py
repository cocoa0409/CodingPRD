"""Order and proof lifecycle: the cyclic revision loop, the two parallel order
dimensions, the proof-approval cascade gate, the verified-contact submit gate,
and invalid-state guards on schedule/cancel/approve.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    build_pipeline, holder, TEST_USERS,
    new_account, new_subscription, new_contact, new_card, new_order, account_version,
)

STUDIO = TEST_USERS["studio_operator_headers"]


# --------------------------------------------------------------------------
# Cyclic proof revision loop
# --------------------------------------------------------------------------
def test_proof_revision_cycle_loops_twice_then_approves(api):
    """PRD §3.5: "This request-changes/revise cycle may repeat any number of
    rounds before the proof is finally approved."
    PRD §3.5: "the account holder may approve it, moving the proof from `PENDING`
    to `APPROVED`; this cascade advances the owning order from `PENDING_PROOF` to
    `PROOF_APPROVED`."

    Design: Difficulty/non_linear_state_machine/proof_revision_cycle_loops_twice
    """
    ctx = build_pipeline("submitted", tier="PRO")
    ah = holder(ctx["account_id"])
    proof_id, order_id = ctx["proof_id"], ctx["order_id"]

    validate_success(api.request_changes(proof_id, {"reviewer_notes": "fix name"}, ah), 200)
    validate_success(api.revise_proof(proof_id, {"proof_image_ref": "img-2"}, STUDIO), 200)
    validate_success(api.request_changes(proof_id, {"reviewer_notes": "fix date"}, ah), 200)
    validate_success(api.revise_proof(proof_id, {"proof_image_ref": "img-3"}, STUDIO), 200)
    proof = validate_success(api.approve_proof(proof_id, ah), 200)

    assert proof["revision_count"] == 2, "two request-changes rounds occurred"
    assert proof["status"] == "APPROVED"
    order = validate_success(api.get_order(order_id, ah), 200)
    assert order["status"] == "PROOF_APPROVED"


def test_request_changes_increments_revision_then_revise_returns_pending(api):
    """PRD §3.5: "the account holder may request changes, moving the proof from
    `PENDING` to `CHANGES_REQUESTED`; this stores the supplied `reviewer_notes`
    and increments `revision_count` by one."
    PRD §3.5: "A `StudioOperator` then revises the proof, moving it back from
    `CHANGES_REQUESTED` to `PENDING` and refreshing the `proof_image_ref`."

    Design: Difficulty/non_linear_state_machine/proof_revision_cycle_loops_twice
    """
    ctx = build_pipeline("submitted", tier="PRO")
    ah = holder(ctx["account_id"])
    proof_id = ctx["proof_id"]

    changed = validate_success(api.request_changes(proof_id, {"reviewer_notes": "fix"}, ah), 200)
    assert changed["status"] == "CHANGES_REQUESTED"
    assert changed["revision_count"] == 1
    revised = validate_success(api.revise_proof(proof_id, {"proof_image_ref": "img-2"}, STUDIO), 200)
    assert revised["status"] == "PENDING"
    assert revised["revision_count"] == 1, "revising does not reset the round counter"


# --------------------------------------------------------------------------
# Two parallel order dimensions
# --------------------------------------------------------------------------
def test_submit_sets_pending_proof_and_held(api):
    """PRD §3.4: "Submitting a draft is the account holder's commitment, and it
    advances the order from `DRAFT` to `PENDING_PROOF` while moving its credit
    dimension from `NONE` to `HELD`."

    Design: Difficulty/non_linear_state_machine/order_status_and_credit_status_evolve_independently
    """
    ctx = build_pipeline("submitted", tier="PRO")
    order = validate_success(api.get_order(ctx["order_id"], holder(ctx["account_id"])), 200)
    assert order["status"] == "PENDING_PROOF"
    assert order["credit_status"] == "HELD"


def test_cancel_sets_cancelled_and_refunded(api):
    """PRD §2.10: "Its `status` follows the fulfillment pipeline — `DRAFT`,
    `PENDING_PROOF`, `PROOF_APPROVED`, `SCHEDULED`, `IN_PRODUCTION`, `MAILED`,
    `DELIVERED`, and the terminal `CANCELLED` — while its `credit_status` follows
    the accounting lifecycle — `NONE`, `HELD`, `SETTLED`, and the terminal
    `REFUNDED`."

    Design: Difficulty/non_linear_state_machine/order_status_and_credit_status_evolve_independently
    """
    ctx = build_pipeline("submitted", tier="PRO")
    ah = holder(ctx["account_id"])
    validate_success(api.cancel_order(ctx["order_id"], ah), 200)
    order = validate_success(api.get_order(ctx["order_id"], ah), 200)
    assert order["status"] == "CANCELLED"
    assert order["credit_status"] == "REFUNDED"


# --------------------------------------------------------------------------
# Proof-approval cascade gate
# --------------------------------------------------------------------------
def test_proof_approval_cascades_order_to_proof_approved(api):
    """PRD §3.5: "the account holder may approve it, moving the proof from
    `PENDING` to `APPROVED`; this cascade advances the owning order from
    `PENDING_PROOF` to `PROOF_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/order_proof_approved_gates_order_advance
    """
    ctx = build_pipeline("submitted", tier="PRO")
    ah = holder(ctx["account_id"])
    proof = validate_success(api.approve_proof(ctx["proof_id"], ah), 200)
    assert proof["status"] == "APPROVED"
    order = validate_success(api.get_order(ctx["order_id"], ah), 200)
    assert order["status"] == "PROOF_APPROVED"


def test_order_stays_pending_proof_while_proof_pending(api):
    """PRD §3.5: "From `PENDING`, the account holder may approve it, moving the
    proof from `PENDING` to `APPROVED`; this cascade advances the owning order
    from `PENDING_PROOF` to `PROOF_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/order_proof_approved_gates_order_advance
    """
    ctx = build_pipeline("submitted", tier="PRO")
    ah = holder(ctx["account_id"])
    proofs = validate_success(api.list_order_proofs(ctx["order_id"], ah), 200)
    assert proofs[0]["status"] == "PENDING"
    order = validate_success(api.get_order(ctx["order_id"], ah), 200)
    assert order["status"] == "PENDING_PROOF", "the order does not advance before the proof is approved"


# --------------------------------------------------------------------------
# Verified-contact submit gate
# --------------------------------------------------------------------------
def test_submit_rejected_when_contact_unverified(api):
    """PRD §3.4: "the recipient contact's address must be `VERIFIED`, or the
    submit fails with `ERR_ADDRESS_NOT_VERIFIED`".

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_verified_contact
    """
    account = new_account()
    new_subscription(account["id"], "PRO")
    contact = new_contact(account["id"])  # left UNVERIFIED
    card = new_card()
    order = new_order(account["id"], contact["id"], card["id"])
    ah = holder(account["id"])
    version = account_version(account["id"])
    validate_error(
        api.submit_order(order["id"], {"expected_account_version": version}, ah),
        ApiErrorId.ERR_ADDRESS_NOT_VERIFIED.value,
    )


def test_submit_succeeds_once_contact_verified(api):
    """PRD §3.4: "Submitting a draft is the account holder's commitment, and it
    advances the order from `DRAFT` to `PENDING_PROOF` while moving its credit
    dimension from `NONE` to `HELD`."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_verified_contact
    """
    account = new_account()
    new_subscription(account["id"], "PRO")
    contact = new_contact(account["id"], verified=True)
    card = new_card()
    order = new_order(account["id"], contact["id"], card["id"])
    ah = holder(account["id"])
    version = account_version(account["id"])
    submitted = validate_success(api.submit_order(order["id"], {"expected_account_version": version}, ah), 200)
    assert submitted["status"] == "PENDING_PROOF"
    assert submitted["credit_status"] == "HELD"


# --------------------------------------------------------------------------
# Invalid-state guards (queue B)
# --------------------------------------------------------------------------
def test_schedule_in_pending_proof_returns_invalid_state(api):
    """PRD §3.6: "Confirming the schedule advances the order from
    `PROOF_APPROVED` to `SCHEDULED`".
    PRD §2.9: "an illegal transition yields `ERR_INVALID_STATE`, and this state
    check takes precedence over every business rule that follows it."

    Design: Corner/state_machines/schedule_order_in_pending_proof_returns_invalid_state
    """
    ctx = build_pipeline("submitted", tier="PRO")  # still PENDING_PROOF (proof not approved)
    validate_error(api.schedule_order(ctx["order_id"], STUDIO), ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_already_cancelled_returns_invalid_state(api):
    """PRD §3.8: "An order may be cancelled from any pre-delivery pipeline state,
    always ending in the terminal `CANCELLED`".
    PRD §2.9: "an illegal transition yields `ERR_INVALID_STATE`".

    Design: Corner/state_machines/cancel_already_cancelled_order_returns_invalid_state
    """
    ctx = build_pipeline("draft", tier=None, verify=False)
    ah = holder(ctx["account_id"])
    validate_success(api.cancel_order(ctx["order_id"], ah), 200)
    validate_error(api.cancel_order(ctx["order_id"], ah), ApiErrorId.ERR_INVALID_STATE.value)


def test_approve_already_approved_proof_returns_invalid_state(api):
    """PRD §3.5: "From `PENDING`, the account holder may approve it, moving the
    proof from `PENDING` to `APPROVED`".
    PRD §2.9: "an illegal transition yields `ERR_INVALID_STATE`".

    Design: Corner/state_machines/approve_proof_twice_returns_invalid_state
    """
    ctx = build_pipeline("approved", tier="PRO")  # proof already APPROVED
    validate_error(api.approve_proof(ctx["proof_id"], holder(ctx["account_id"])), ApiErrorId.ERR_INVALID_STATE.value)
