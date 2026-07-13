"""Design-proof revision cycle, terminal/superseded guards, deposit gate on approval,
and optimistic-concurrency on proof creation."""
import test_helpers as th


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / design_proof_revision_cycle
# ---------------------------------------------------------------------------
def test_resubmit_returns_proof_to_submitted(api):
    """PRD §3.3: "The designer then re-submits, carrying the proof from `CHANGES_REQUESTED` back
    to `SUBMITTED` and incrementing its `revision_round` by one — this is the cycle that lets a
    proof iterate."

    Design: Difficulty/non_linear_state_machine/design_proof_revision_cycle
    """
    ctx = th.setup_changes_requested_proof(
        proof_lines=[12, 18], cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    proof = th.validate_success(api.submit_design_proof(ctx["proof"]["id"], th.TEST_USERS["designer_headers"]))
    assert proof["status"] == "SUBMITTED", proof


def test_resubmit_increments_revision_round_to_two(api):
    """PRD §3.3: "The designer then re-submits, carrying the proof from `CHANGES_REQUESTED` back
    to `SUBMITTED` and incrementing its `revision_round` by one — this is the cycle that lets a
    proof iterate."

    Design: Difficulty/non_linear_state_machine/design_proof_revision_cycle
    """
    ctx = th.setup_changes_requested_proof(
        proof_lines=[12, 18], cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    proof = th.validate_success(api.submit_design_proof(ctx["proof"]["id"], th.TEST_USERS["designer_headers"]))
    assert proof["revision_round"] == 2, proof


# ---------------------------------------------------------------------------
# Corner: state_machines / submit_approved_proof_returns_not_draft
# ---------------------------------------------------------------------------
def test_submit_approved_proof_returns_not_draft(api):
    """PRD §3.3: "a submit attempted on a proof that is neither `DRAFT` nor `CHANGES_REQUESTED` is
    rejected with `ERR_PROOF_NOT_DRAFT`."

    Design: Corner/state_machines/submit_approved_proof_returns_not_draft
    """
    ctx = th.setup_approved_proof(deposit_cents=33880, proof_lines=[21, 31])
    resp = api.submit_design_proof(ctx["proof"]["id"], th.TEST_USERS["designer_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_PROOF_NOT_DRAFT.value)


# ---------------------------------------------------------------------------
# Corner: validations / deposit_unpaid_on_approve_returns_deposit_not_paid
# ---------------------------------------------------------------------------
def test_approve_submitted_proof_while_unpaid_returns_deposit_not_paid(api):
    """PRD §3.3: "and when the deposit has already been paid — the order's `payment_status` is not
    `UNPAID` (otherwise `ERR_DEPOSIT_NOT_PAID`)."

    Design: Corner/validations/deposit_unpaid_on_approve_returns_deposit_not_paid
    """
    ctx = th.setup_submitted_proof(proof_lines=[21, 31])
    resp = api.approve_design_proof(ctx["proof"]["id"], ctx["customer_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_DEPOSIT_NOT_PAID.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / proof_create_stale_order_version_returns_conflict
# ---------------------------------------------------------------------------
def test_second_proof_with_stale_order_version_returns_conflict(api):
    """PRD §2.8: "A create-proof request must include `expected_order_version`, carrying the
    `version` of the target `MonumentOrder` that the client last observed. If that value does not
    equal the order's current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/proof_create_stale_order_version_returns_conflict
    """
    ctx = th.setup_one_proof_order(
        proof_lines=[21, 31], cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    # Reuse the version the client observed BEFORE the first proof advanced the order.
    payload = th.create_design_proof_payload(
        ctx["order"]["id"], ctx["observed_version"], engraving_text="Draft Two",
        line_char_counts=[21, 31],
    )
    resp = api.create_design_proof(payload, th.TEST_USERS["designer_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_STALE_ORDER_VERSION.value)
