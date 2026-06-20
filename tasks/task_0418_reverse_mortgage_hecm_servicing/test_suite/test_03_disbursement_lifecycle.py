"""The disbursement draw lifecycle: disburse side effects, reject, the void
compensating reversal, the available-line boundary, draw-type matching, the
invalid-state guard, and optimistic concurrency on Loan.version.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_principal_capacity_conserved,
    setup_originated_loc_base_loan,
    setup_disbursed_draw,
    setup_originated_loan,
    setup_loan_with_delinquent_cert,
    request_disbursement,
    loan_version,
)

_SO = TEST_USERS["servicer_ops_headers"]


# ---------------------------------------------------------------------------
# endpoints / disburse_approved_draw_debits_line_credits_balance_side_effect
# ---------------------------------------------------------------------------
def test_disburse_debits_line_credits_balance(api):
    """PRD §3.5: "Disbursing adds the `approved_amount_cents` to the loan's
    `principal_balance_cents` (posted as an `ADVANCE` ledger entry) and
    subtracts the same `approved_amount_cents` from the loan's
    `available_line_of_credit_cents`, so that balance and remaining line stay
    conserved against each other."

    Design: Corner/endpoints/disburse_approved_draw_debits_line_credits_balance_side_effect
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    v = loan["version"]
    disb = request_disbursement(loan["id"], requested_amount_cents=100000)
    validate_success(api.approve_disbursement(disb["id"], {"expected_loan_version": v}, _SO))
    out = validate_success(api.disburse_disbursement(disb["id"], _SO))
    assert out["status"] == "DISBURSED"
    reread = validate_success(api.get_loan(loan["id"], _SO))
    assert reread["principal_balance_cents"] == 1100000
    assert reread["available_line_of_credit_cents"] == 14590000


# ---------------------------------------------------------------------------
# endpoints / reject_disbursement_action_sets_rejected_and_zero_approved
# ---------------------------------------------------------------------------
def test_reject_disbursement_sets_rejected_zero_approved(api):
    """PRD §3.5: "A `ServicerOps` operator may reject it, which moves it to `REJECTED` and
    leaves `approved_amount_cents` at 0."

    Design: Corner/endpoints/reject_disbursement_action_sets_rejected_and_zero_approved
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    disb = request_disbursement(loan["id"], requested_amount_cents=100000)
    out = validate_success(api.reject_disbursement(disb["id"], _SO))
    assert out["status"] == "REJECTED"
    assert out["approved_amount_cents"] == 0


# ---------------------------------------------------------------------------
# state_machines / approve_disbursement_from_rejected_state_returns_invalid_state
# ---------------------------------------------------------------------------
def test_approve_from_rejected_returns_invalid_state(api):
    """PRD §2.10: "and fifth, that the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)."
    PRD §3.5: "A `ServicerOps` operator may reject it, which moves it to `REJECTED` and
    leaves `approved_amount_cents` at 0."

    Design: Corner/state_machines/approve_disbursement_from_rejected_state_returns_invalid_state
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    v = loan["version"]
    disb = request_disbursement(loan["id"], requested_amount_cents=100000)
    validate_success(api.reject_disbursement(disb["id"], _SO))
    validate_error(
        api.approve_disbursement(disb["id"], {"expected_loan_version": v}, _SO),
        ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_disbursement(disb["id"], _SO))
    assert reread["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# compensating_invariant / disbursement_void_restores_principal_capacity
# ---------------------------------------------------------------------------
def test_void_restores_principal_capacity(api):
    """PRD §3.5: "A void is a compensating reversal: the `approved_amount_cents` is subtracted
    back out of the `principal_balance_cents` (posted as a `REVERSAL` ledger
    entry) and added back to the `available_line_of_credit_cents`, restoring
    the conserved principal-capacity invariant to where it stood before the
    disbursement."

    Design: Difficulty/compensating_invariant/disbursement_void_restores_principal_capacity
    """
    lender, borrower, loan, disb = setup_disbursed_draw(amount_cents=5000000)
    before = validate_success(api.get_loan(loan["id"], _SO))
    assert before["principal_balance_cents"] == 6000000
    assert before["available_line_of_credit_cents"] == 9690000
    assert_principal_capacity_conserved(before, 15690000)

    out = validate_success(api.void_disbursement(disb["id"], _SO))
    assert out["status"] == "VOIDED"
    after = validate_success(api.get_loan(loan["id"], _SO))
    assert after["principal_balance_cents"] == 1000000
    assert after["available_line_of_credit_cents"] == 14690000
    assert_principal_capacity_conserved(after, 15690000)


def test_void_posts_reversal_and_zero_drift(api):
    """PRD §3.5: "A void is a compensating reversal: the `approved_amount_cents` is subtracted
    back out of the `principal_balance_cents` (posted as a `REVERSAL` ledger
    entry) and added back to the `available_line_of_credit_cents`, restoring
    the conserved principal-capacity invariant to where it stood before the
    disbursement."

    Design: Difficulty/compensating_invariant/disbursement_void_restores_principal_capacity
    """
    lender, borrower, loan, disb = setup_disbursed_draw(amount_cents=5000000)
    validate_success(api.void_disbursement(disb["id"], _SO))
    after = validate_success(api.get_loan(loan["id"], _SO))
    total = after["principal_balance_cents"] + after["available_line_of_credit_cents"]
    assert total == 15690000


# ---------------------------------------------------------------------------
# boundary_precision_check / disbursement_request_equal_to_line_allowed_over_rejected
# ---------------------------------------------------------------------------
def test_disbursement_request_equal_to_line_approved(api):
    """PRD §3.5: "the `requested_amount_cents` must be less than or equal to the loan's
    `available_line_of_credit_cents` — drawing exactly the full available line
    is allowed, and only a request strictly greater than the line is rejected,
    with `ERR_INSUFFICIENT_LINE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/disbursement_request_equal_to_line_allowed_over_rejected
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    v = loan["version"]
    equal_disb = request_disbursement(loan["id"], requested_amount_cents=14690000)
    out = validate_success(api.approve_disbursement(
        equal_disb["id"], {"expected_loan_version": v}, _SO))
    assert out["status"] == "APPROVED"
    assert out["approved_amount_cents"] == 14690000


def test_disbursement_request_one_cent_over_line_rejected(api):
    """PRD §3.5: "the `requested_amount_cents` must be less than or equal to the loan's
    `available_line_of_credit_cents` — drawing exactly the full available line
    is allowed, and only a request strictly greater than the line is rejected,
    with `ERR_INSUFFICIENT_LINE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/disbursement_request_equal_to_line_allowed_over_rejected
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    v = loan["version"]
    over_disb = request_disbursement(loan["id"], requested_amount_cents=14690001)
    validate_error(
        api.approve_disbursement(over_disb["id"], {"expected_loan_version": v}, _SO),
        ApiErrorId.ERR_INSUFFICIENT_LINE.value)


# ---------------------------------------------------------------------------
# validations / line_draw_on_lump_sum_loan_returns_draw_type_mismatch
# ---------------------------------------------------------------------------
def test_line_draw_on_lump_sum_loan_returns_draw_type_mismatch(api):
    """PRD §3.5: "a draw whose `kind` is `LINE_DRAW` requires the loan's `draw_type` to be
    `LINE_OF_CREDIT`; otherwise the request fails with
    `ERR_DRAW_TYPE_MISMATCH` (HTTP 409)."

    Design: Corner/validations/line_draw_on_lump_sum_loan_returns_draw_type_mismatch
    """
    lender, borrower, loan = setup_originated_loan(loan_overrides={"draw_type": "LUMP_SUM"})
    v = loan["version"]
    disb = request_disbursement(loan["id"], requested_amount_cents=100000)
    validate_error(
        api.approve_disbursement(disb["id"], {"expected_loan_version": v}, _SO),
        ApiErrorId.ERR_DRAW_TYPE_MISMATCH.value)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / disbursement_approve_requires_loan_active_current
# ---------------------------------------------------------------------------
def test_approve_requires_loan_active_and_current(api):
    """PRD §3.5: "First, the loan must be drawable — `disposition_status` `ACTIVE` and
    `servicing_status` `CURRENT` at the same time — or the approval is
    rejected with `ERR_LOAN_NOT_DRAWABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/disbursement_approve_requires_loan_active_current
    """
    # Build loan, capture version, request draw, THEN make cert delinquent.
    # The year-1 cert's due_date is the origination anniversary (2025-01-01).
    # Per PRD §3.7 a certification only lapses once the clock is strictly later
    # than its due_date; advancing the clock past it runs the §3.1 occupancy
    # sweep, which moves the PENDING cert to DELINQUENT and cascades the loan's
    # servicing axis to DELINQUENT_OCCUPANCY (disposition axis untouched).
    lender, borrower, loan = setup_originated_loc_base_loan()
    v = loan["version"]
    disb = request_disbursement(loan["id"], requested_amount_cents=100000)
    validate_success(api.create_occupancy_certification(
        {"loan_id": loan["id"], "certification_year": 1}, _SO), expected_status=201)
    validate_success(api.set_clock(
        {"lender_id": lender["id"], "to_iso8601": "2025-02-01T00:00:00.000Z"}, _SO))

    validate_error(
        api.approve_disbursement(disb["id"], {"expected_loan_version": v}, _SO),
        ApiErrorId.ERR_LOAN_NOT_DRAWABLE.value)
    reread_loan = validate_success(api.get_loan(loan["id"], _SO))
    assert reread_loan["servicing_status"] == "DELINQUENT_OCCUPANCY"
    assert reread_loan["disposition_status"] == "ACTIVE"
    reread_disb = validate_success(api.get_disbursement(disb["id"], _SO))
    assert reread_disb["status"] == "REQUESTED"


def test_approve_blocked_when_servicing_delinquent_via_clock_sweep(api):
    """PRD §3.5: "First, the loan must be drawable — `disposition_status` `ACTIVE` and
    `servicing_status` `CURRENT` at the same time — or the approval is
    rejected with `ERR_LOAN_NOT_DRAWABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/disbursement_approve_requires_loan_active_current
    """
    # Reach servicing_status=DELINQUENT_OCCUPANCY via the clock-advance sweep (a
    # different trigger than mark-delinquent); disposition_status stays ACTIVE.
    lender, borrower, loan = setup_originated_loc_base_loan()
    v = loan["version"]
    disb = request_disbursement(loan["id"], requested_amount_cents=100000)
    cert = validate_success(api.create_occupancy_certification(
        {"loan_id": loan["id"], "certification_year": 1}, _SO), expected_status=201)
    # cert due_date is the year-1 anniversary (2025-01-01); advance the clock past it.
    validate_success(api.set_clock(
        {"lender_id": lender["id"], "to_iso8601": "2025-02-01T00:00:00.000Z"}, _SO))
    drawable = validate_success(api.get_loan(loan["id"], _SO))
    assert drawable["servicing_status"] == "DELINQUENT_OCCUPANCY"
    assert drawable["disposition_status"] == "ACTIVE"
    validate_error(
        api.approve_disbursement(disb["id"], {"expected_loan_version": v}, _SO),
        ApiErrorId.ERR_LOAN_NOT_DRAWABLE.value)


# ---------------------------------------------------------------------------
# cross_cutting / approve_with_stale_expected_loan_version_returns_412
# ---------------------------------------------------------------------------
def test_approve_with_stale_version_returns_stale_version(api):
    """PRD §2.9: "If `expected_loan_version` does not equal the loan's current `version` — for
    example because a prior approve against the same loan has already debited
    the available line and advanced the loan's `version` since the client last
    read it — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412),
    and the client must re-read the loan and retry."

    Design: Corner/cross_cutting/approve_with_stale_expected_loan_version_returns_412
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    v0 = loan["version"]
    disb1 = request_disbursement(loan["id"], requested_amount_cents=100000)
    disb2 = request_disbursement(loan["id"], requested_amount_cents=100000)
    # First approve uses v0, succeeds, and bumps Loan.version.
    validate_success(api.approve_disbursement(disb1["id"], {"expected_loan_version": v0}, _SO))
    # Second reuses the now-stale v0.
    validate_error(
        api.approve_disbursement(disb2["id"], {"expected_loan_version": v0}, _SO),
        ApiErrorId.ERR_STALE_VERSION.value)
    reread = validate_success(api.get_disbursement(disb2["id"], _SO))
    assert reread["status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# cross_cutting / approve_with_current_version_succeeds_and_bumps_loan_version
# ---------------------------------------------------------------------------
def test_approve_with_current_version_bumps_loan_version(api):
    """PRD §2.9: "A successful approve increments the loan's `version` by 1."
    PRD §3.5: "On a successful approve, `approved_amount_cents` is set equal to
    `requested_amount_cents` and the loan's `version` is incremented by 1."

    Design: Corner/cross_cutting/approve_with_current_version_succeeds_and_bumps_loan_version
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    v = loan["version"]
    disb = request_disbursement(loan["id"], requested_amount_cents=100000)
    out = validate_success(api.approve_disbursement(disb["id"], {"expected_loan_version": v}, _SO))
    assert out["status"] == "APPROVED"
    assert out["approved_amount_cents"] == 100000
    v_after = loan_version(loan["id"])
    assert v_after == v + 1
