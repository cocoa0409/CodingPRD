"""Proof approval loop: cyclic revision rounds and invalid-transition guards (queues A + B)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_proof,
    make_customer_headers,
    make_staff_headers,
    fixtures,
    factories,
)

STAFF = make_staff_headers()


def test_proof_cyclic_revision_loop_increments_round(api):
    """PRD §3.3: "Staff then revise the changed proof, advancing it `CHANGES_REQUESTED →
    DRAFT`; revision increments `revision_round` by 1, clears `sent_at`, clears
    `approved_text_snapshot`, and may carry a new `content_ref`."
    PRD §3.3: "From `DRAFT` the proof can be sent again, so the loop `SENT →
    CHANGES_REQUESTED → DRAFT → SENT` repeats until the customer approves."

    Design: Difficulty/non_linear_state_machine/proof_cyclic_revision_loop_increments_round
    """
    base = fixtures.setup_foundation(
        product_overrides={"base_price_cents": 800, "standard_lead_days": 2,
                           "product_type": "MEDAL"},
        on_hand_qty=10,
    )
    order = fixtures.create_order(base["customer"])
    line = fixtures.add_line(order, base["customer"], base["product"]["id"],
                             quantity=1, engraving_text="FIRST")
    cust = make_customer_headers(base["customer"]["id"])
    proof = validate_success(
        api.create_proof(line["id"], factories.create_proof_payload(content_ref="FIRST"), STAFF),
        201,
    )
    validate_success(api.send_proof(line["id"], proof["id"], STAFF))
    # SENT -> CHANGES_REQUESTED
    validate_success(api.request_changes_proof(line["id"], proof["id"], cust))
    # CHANGES_REQUESTED -> DRAFT (revision_round increments to 2)
    revised = validate_success(api.revise_proof(line["id"], proof["id"], {"content_ref": "SECOND"}, STAFF))
    assert revised["revision_round"] == 2
    # DRAFT -> SENT again
    sent = validate_success(api.send_proof(line["id"], proof["id"], STAFF))
    assert sent["revision_round"] == 2
    assert sent["proof_status"] == "SENT"


def test_proof_revise_returns_to_draft_state(api):
    """PRD §3.3: "Staff then revise the changed proof, advancing it `CHANGES_REQUESTED →
    DRAFT`; revision increments `revision_round` by 1, clears `sent_at`, clears
    `approved_text_snapshot`, and may carry a new `content_ref`."

    Design: Difficulty/non_linear_state_machine/proof_cyclic_revision_loop_increments_round
    """
    base = fixtures.setup_foundation(
        product_overrides={"base_price_cents": 800, "standard_lead_days": 2,
                           "product_type": "MEDAL"},
        on_hand_qty=10,
    )
    order = fixtures.create_order(base["customer"])
    line = fixtures.add_line(order, base["customer"], base["product"]["id"],
                             quantity=1, engraving_text="FIRST")
    cust = make_customer_headers(base["customer"]["id"])
    proof = fixtures.add_sent_proof(line, content_ref="FIRST")
    validate_success(api.request_changes_proof(line["id"], proof["id"], cust))
    revised = validate_success(api.revise_proof(line["id"], proof["id"], {"content_ref": "SECOND"}, STAFF))
    # Cyclic: the proof has returned to DRAFT — a linear pipeline could never re-reach DRAFT.
    assert revised["proof_status"] == "DRAFT"
    assert revised["revision_round"] == 2


def test_approve_proof_from_draft_returns_invalid_state(api):
    """PRD §3.3: "Approving a sent proof advances it `SENT → APPROVED`, a terminal state,
    and captures `approved_text_snapshot` from the proof's `content_ref`."
    PRD §2.7: "Only after all four of those pass does the system evaluate whether the target
    resource is in a valid state for the requested transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/approve_proof_from_draft_returns_invalid_state
    """
    base = fixtures.setup_foundation(on_hand_qty=10)
    order = fixtures.create_order(base["customer"])
    line = fixtures.add_line(order, base["customer"], base["product"]["id"], quantity=1)
    cust = make_customer_headers(base["customer"]["id"])
    proof = validate_success(
        api.create_proof(line["id"], factories.create_proof_payload(), STAFF), 201
    )
    # Proof is DRAFT (never SENT) — approve must be rejected.
    resp = api.approve_proof(line["id"], proof["id"], cust)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_proof(proof["id"], cust))
    assert reread["proof_status"] == "DRAFT"


def test_revise_proof_from_sent_returns_invalid_state(api):
    """PRD §3.3: "Staff then revise the changed proof, advancing it `CHANGES_REQUESTED →
    DRAFT`; revision increments `revision_round` by 1, clears `sent_at`, clears
    `approved_text_snapshot`, and may carry a new `content_ref`."
    PRD §2.7: "Only after all four of those pass does the system evaluate whether the target
    resource is in a valid state for the requested transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/revise_proof_from_sent_returns_invalid_state
    """
    base = fixtures.setup_foundation(on_hand_qty=10)
    order = fixtures.create_order(base["customer"])
    line = fixtures.add_line(order, base["customer"], base["product"]["id"], quantity=1)
    cust = make_customer_headers(base["customer"]["id"])
    proof = fixtures.add_sent_proof(line)
    # Proof is SENT, not CHANGES_REQUESTED — revise must be rejected.
    resp = api.revise_proof(line["id"], proof["id"], {}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_proof(proof["id"], cust))
    assert reread["proof_status"] == "SENT"
