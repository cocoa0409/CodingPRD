"""Cross-entity preconditions, validation precedence, and order-progression gates.

Covers queue A: cross_entity_state_dependency, priority_pair_validation_conflict,
plus queue B errors / validations / state_machines corners that assert a single
rejection error.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_agency_and_order,
    setup_order_with_issued_commitment,
    setup_order_clear_to_close,
    create_draft_commitment,
    create_pending_policy,
    add_exception,
    add_title_search,
    add_posted_deposit,
    add_approved_disbursement,
    add_disbursement,
    transition_order,
    complete_title_search,
    get_order,
    file_claim,
    setup_issued_owner_policy,
    make_agency_headers,
    TO,
    UW,
)


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_policy_issue_requires_commitment_issued(api):
    """PRD §3.6: "The commitment must be in `ISSUED` (otherwise
    `ERR_COMMITMENT_NOT_ISSUED`)".
    The commitment is left DRAFT.

    Design: Difficulty/cross_entity_state_dependency/policy_issue_requires_commitment_issued
    """
    agency, order = create_agency_and_order()
    commitment = create_draft_commitment(order, insured_amount_cents=25_000_000)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=25_000_000)
    validate_error(
        api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW),
        ApiErrorId.ERR_COMMITMENT_NOT_ISSUED.value,
    )
    assert validate_success(api.get_policy(policy["id"], UW))["status"] == "PENDING"


def test_policy_issue_succeeds_once_commitment_issued(api):
    """PRD §3.6: "The commitment must be in `ISSUED` (otherwise `ERR_COMMITMENT_NOT_ISSUED`)".
    The positive complement of the cross-entity gate: with the commitment in ISSUED the
    dependent policy issue is allowed.

    Design: Difficulty/cross_entity_state_dependency/policy_issue_requires_commitment_issued
    """
    _agency, order, commitment = setup_order_with_issued_commitment(insured_amount_cents=25_000_000)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=25_000_000)
    data = validate_success(api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW))
    assert data["status"] == "ISSUED", "policy issue must succeed when its commitment is ISSUED"


def test_disbursement_approve_requires_order_disbursable(api):
    """PRD §3.7: "Approval requires the order to be in a disbursable state: for every
    purpose other than `CLAIM_PAYOUT` the order must be in `CLEAR_TO_CLOSE` or `CLOSED`,
    while a `CLAIM_PAYOUT` is allowed only when the order is `CLOSED` (otherwise
    `ERR_ORDER_NOT_DISBURSABLE`)."
    The order is still OPENED.

    Design: Difficulty/cross_entity_state_dependency/disbursement_approve_requires_order_disbursable
    """
    _agency, order = create_agency_and_order()
    disb = add_disbursement(order, amount_cents=1_000, purpose="SELLER_PROCEEDS")
    validate_error(
        api.transition_disbursement(disb["id"], {"to_status": "APPROVED"}, UW),
        ApiErrorId.ERR_ORDER_NOT_DISBURSABLE.value,
    )
    assert validate_success(api.get_disbursement(disb["id"], UW))["status"] == "REQUESTED"


def test_disbursement_approve_succeeds_when_order_clear_to_close(api):
    """PRD §3.7: "Approval requires the order to be in a disbursable state: for every
    purpose other than `CLAIM_PAYOUT` the order must be in `CLEAR_TO_CLOSE` or `CLOSED`,
    while a `CLAIM_PAYOUT` is allowed only when the order is `CLOSED` (otherwise
    `ERR_ORDER_NOT_DISBURSABLE`)."
    The positive complement: a SELLER_PROCEEDS disbursement on a CLEAR_TO_CLOSE order is
    approvable.

    Design: Difficulty/cross_entity_state_dependency/disbursement_approve_requires_order_disbursable
    """
    agency, order, _commitment, _search, _policy = setup_order_clear_to_close()
    add_posted_deposit(order, agency, amount_cents=200_000, source_ref="WIRE-IN-DA")
    disb = add_disbursement(order, amount_cents=200_000, purpose="SELLER_PROCEEDS")
    data = validate_success(api.transition_disbursement(disb["id"], {"to_status": "APPROVED"}, UW))
    assert data["status"] == "APPROVED", "approve must succeed on a CLEAR_TO_CLOSE order"


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_wire_state_error_beats_fiscal_error(api):
    """PRD §2.8: "State validity is sixth: a transition requested from a state the resource
    is not currently in fails with `ERR_INVALID_STATE`".
    PRD §2.8: "Fiscal checks are evaluated last, after every structural and safety check
    has passed, so that a money error never masks a safety or state error."
    A REQUESTED (not APPROVED) disbursement whose amount also exceeds the balance: the
    state error (6th) is reported, not the fiscal error (last).

    Design: Difficulty/priority_pair_validation_conflict/wire_invalid_state_beats_insufficient_escrow
    """
    agency, order = create_agency_and_order()
    add_posted_deposit(order, agency, amount_cents=100, source_ref="WIRE-IN-PP1")
    disb = add_disbursement(order, amount_cents=500_000, purpose="SELLER_PROCEEDS")  # never approved
    validate_error(
        api.transition_disbursement(disb["id"], {"to_status": "WIRED"}, UW),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert validate_success(api.get_disbursement(disb["id"], UW))["status"] == "REQUESTED"


def test_wire_over_balance_alone_reports_insufficient_escrow(api):
    """PRD §3.7: "The `amount_cents` must be less than or equal to the order's current
    `escrow_balance_cents` (otherwise `ERR_INSUFFICIENT_ESCROW`)".
    With the state precondition satisfied (the disbursement is APPROVED) the fiscal check
    alone fires — confirming the loser of the state-vs-fiscal conflict has its own trigger.

    Design: Difficulty/priority_pair_validation_conflict/wire_invalid_state_beats_insufficient_escrow
    """
    agency, order, _commitment, _search, _policy = setup_order_clear_to_close()
    add_posted_deposit(order, agency, amount_cents=100, source_ref="WIRE-IN-PP3")
    disb = add_approved_disbursement(order, amount_cents=500_000, purpose="SELLER_PROCEEDS")
    validate_error(
        api.transition_disbursement(disb["id"], {"to_status": "WIRED"}, UW),
        ApiErrorId.ERR_INSUFFICIENT_ESCROW.value,
    )
    assert validate_success(api.get_disbursement(disb["id"], UW))["status"] == "APPROVED"


def test_policy_issue_referential_error_beats_safety_error(api):
    """PRD §2.8: "Cross-entity referential preconditions are seventh — the prerequisites
    that depend on another entity's state, such as a policy requiring its commitment to be
    in `ISSUED`."
    PRD §2.8: "Title-safety and curative gates are eighth and ninth in the temporal and
    safety bands."
    A policy issue against a DRAFT commitment that ALSO has an open RAISED exception:
    the referential error (7th) is reported, not the safety error (9th).

    Design: Difficulty/priority_pair_validation_conflict/policy_issue_commitment_not_issued_beats_exceptions_open
    """
    agency, order = create_agency_and_order()
    commitment = create_draft_commitment(order, insured_amount_cents=25_000_000)
    add_exception(commitment, exception_type="SPECIAL", description="Undisclosed easement", curative_required=True)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=25_000_000)
    validate_error(
        api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW),
        ApiErrorId.ERR_COMMITMENT_NOT_ISSUED.value,
    )
    assert validate_success(api.get_policy(policy["id"], UW))["status"] == "PENDING"


def test_policy_issue_with_open_exception_alone_reports_exceptions_open(api):
    """PRD §3.6: "the commitment's `open_exception_count` must be 0 (otherwise
    `ERR_EXCEPTIONS_OPEN`)".
    With the referential precondition satisfied (commitment ISSUED) the safety check alone
    fires — confirming the loser of the referential-vs-safety conflict has its own trigger.

    Design: Difficulty/priority_pair_validation_conflict/policy_issue_commitment_not_issued_beats_exceptions_open
    """
    _agency, order, commitment = setup_order_with_issued_commitment(insured_amount_cents=25_000_000)
    add_exception(commitment, exception_type="SPECIAL", description="Open easement", curative_required=True)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=25_000_000)
    validate_error(
        api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW),
        ApiErrorId.ERR_EXCEPTIONS_OPEN.value,
    )
    assert validate_success(api.get_policy(policy["id"], UW))["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Queue B — validations / errors single-rejection corners
# ---------------------------------------------------------------------------
def test_policy_coverage_exceeds_commitment_rejected(api):
    """PRD §3.6: "the policy's `coverage_amount_cents` must not exceed the commitment's
    `insured_amount_cents` (otherwise `ERR_COVERAGE_EXCEEDS_COMMITMENT`)."
    Coverage 30000000 over insured 25000000.

    Design: Corner/validations/policy_issue_coverage_exceeds_commitment_rejected
    """
    _agency, order, commitment = setup_order_with_issued_commitment(insured_amount_cents=25_000_000)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=30_000_000)
    validate_error(
        api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW),
        ApiErrorId.ERR_COVERAGE_EXCEEDS_COMMITMENT.value,
    )
    assert validate_success(api.get_policy(policy["id"], UW))["status"] == "PENDING"


def test_cancel_order_with_nonzero_escrow_rejected(api):
    """PRD §3.2: "In every case the order's `escrow_balance_cents` must be 0 before it can
    be cancelled (otherwise `ERR_ESCROW_NOT_ZERO`), so that no posted trust funds are
    stranded."

    Design: Corner/validations/order_cancel_with_nonzero_escrow_rejected
    """
    agency, order = create_agency_and_order()
    add_posted_deposit(order, agency, amount_cents=100_000, source_ref="WIRE-IN-PP2")
    validate_error(
        api.transition_order(order["id"], {"to_status": "CANCELLED"}, make_agency_headers(agency["id"])),
        ApiErrorId.ERR_ESCROW_NOT_ZERO.value,
    )
    assert get_order(order["id"])["status"] == "OPENED"


def test_clear_to_close_without_issued_policy_rejected(api):
    """PRD §3.2: "the order's `ISSUED` commitment must have an `open_exception_count` of 0
    — every exception waived or cleared — (otherwise `ERR_EXCEPTIONS_OPEN`), and the order
    must have at least one `Policy` in `ISSUED` (otherwise `ERR_NO_ISSUED_POLICY`)."
    Order in COMMITTED with no issued policy.

    Design: Corner/errors/order_clear_to_close_without_issued_policy_rejected
    """
    _agency, order, _commitment = setup_order_with_issued_commitment()
    search = add_title_search(order)
    transition_order(order["id"], "IN_TITLE")
    complete_title_search(search)
    transition_order(order["id"], "COMMITTED")
    validate_error(
        api.transition_order(order["id"], {"to_status": "CLEAR_TO_CLOSE"}, TO),
        ApiErrorId.ERR_NO_ISSUED_POLICY.value,
    )
    assert get_order(order["id"])["status"] == "COMMITTED"


def test_order_in_title_requires_a_search(api):
    """PRD §3.2: "A title officer moves an order from `OPENED` to `IN_TITLE` once at least
    one `TitleSearch` exists for it in `ORDERED` or `IN_EXAM`."
    PRD §2.8: "State validity is sixth: a transition requested from a state the resource is
    not currently in fails with `ERR_INVALID_STATE`".
    A freshly OPENED order with no searches fails the precondition.

    Design: Corner/errors/order_in_title_requires_a_search
    """
    _agency, order = create_agency_and_order()
    validate_error(
        api.transition_order(order["id"], {"to_status": "IN_TITLE"}, TO),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert get_order(order["id"])["status"] == "OPENED"


def test_pay_claim_without_resolved_curative_rejected(api):
    """PRD §3.9: "The move to `PAID` requires that a `CurativeAction` whose `subject_type`
    is `CLAIM` and whose `subject_id` is this claim exists in `RESOLVED` (otherwise
    `ERR_NO_RESOLVED_CURATIVE`), and the request must supply `settled_loss_cents`, the
    final settled loss."
    Claim at CURATIVE with no curative action.

    Design: Corner/errors/claim_pay_without_resolved_curative_rejected
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy()
    claim = file_claim(policy, claim_type="UNDISCLOSED_LIEN", estimated_loss_cents=50_000)
    validate_success(api.transition_claim(claim["id"], {"to_status": "INVESTIGATING"}, UW))
    validate_success(api.transition_claim(claim["id"], {"to_status": "CURATIVE"}, UW))
    validate_error(
        api.transition_claim(claim["id"], {"to_status": "PAID", "settled_loss_cents": 40_000}, UW),
        ApiErrorId.ERR_NO_RESOLVED_CURATIVE.value,
    )
    assert validate_success(api.get_claim(claim["id"], UW))["status"] == "CURATIVE"
