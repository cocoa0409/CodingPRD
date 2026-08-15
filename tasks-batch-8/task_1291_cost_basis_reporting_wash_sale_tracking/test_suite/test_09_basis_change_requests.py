"""Basis change requests: review cycle, segregation of duties, OCC guard on
the target lot, and per-kind application effects.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, TEST_USERS,
    make_tax_ops_headers, make_customer_headers, make_customer_service_headers,
    setup_book, make_lot, make_security, make_firm, make_customer, make_account,
    make_basis_request, setup_under_review_request, setup_approved_request,
    create_corporate_action_payload, assert_basis_change_request,
)

TAX_OPS = TEST_USERS["tax_ops_headers"]
CUSTOMER_SERVICE = TEST_USERS["customer_service_headers"]


def _book_with_lot(tin, cusip, ticker):
    s = setup_book(tin=tin, cusip=cusip, ticker=ticker)
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=10, basis=10000)
    return s, lot


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / basis_change_request_reject_resubmit_cycle
# ---------------------------------------------------------------------------

def test_request_cycles_reject_resubmit_then_applied(api):
    """PRD §3.9: "Rejection from `UNDER_REVIEW` moves the request to
    `REJECTED`, from which the owning customer — and only that customer,
    verified by comparing the request's customer to the caller's `X-User-ID` —
    may resubmit it, moving it to `RESUBMITTED`; a resubmitted request
    re-enters review through the same start-review action."
    PRD §3.9: "On success the server records the acting operator as
    `applied_by_user_id`, increments the lot's `version`, and moves the request
    to `APPLIED`, its terminal state."

    Design: Difficulty/non_linear_state_machine/basis_change_request_reject_resubmit_cycle
    """
    s, lot = _book_with_lot("TIN-BC-1", "888888888", "BCX")
    req = make_basis_request(s["firm"]["id"], s["customer"]["id"], lot["id"], proposed_basis_cents=12000)
    validate_success(api.start_review_basis_request(s["firm"]["id"], req["id"], TAX_OPS))
    rejected = validate_success(api.reject_basis_request(s["firm"]["id"], req["id"], TAX_OPS))
    assert rejected["status"] == "REJECTED"
    resubmitted = validate_success(api.resubmit_basis_request(
        s["firm"]["id"], req["id"], make_customer_headers(s["customer"]["id"])
    ))
    assert resubmitted["status"] == "RESUBMITTED", "REJECTED -> RESUBMITTED closes the review cycle"
    back = validate_success(api.start_review_basis_request(s["firm"]["id"], req["id"], TAX_OPS))
    assert back["status"] == "UNDER_REVIEW", "RESUBMITTED re-enters review"
    validate_success(api.approve_basis_request(s["firm"]["id"], req["id"], make_tax_ops_headers("taxops-reviewer-1")))
    applied = validate_success(api.apply_basis_request(
        s["firm"]["id"], req["id"], {"expected_tax_lot_version": lot["version"]},
        make_tax_ops_headers("taxops-applier-2"),
    ))
    assert applied["status"] == "APPLIED"
    lot_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["adjusted_cost_basis_cents"] == 12000


def test_applied_request_records_both_operators(api):
    """PRD §3.9: "Approval ... records the acting operator as
    `approved_by_user_id` while snapshotting the target lot's current `version`
    into `version_applied_to`."
    PRD §3.9: "On success the server records the acting operator as
    `applied_by_user_id`, increments the lot's `version`, and moves the request
    to `APPLIED`, its terminal state."

    Design: Difficulty/non_linear_state_machine/basis_change_request_reject_resubmit_cycle
    """
    s, lot = _book_with_lot("TIN-BC-1", "888888888", "BCX")
    req = make_basis_request(s["firm"]["id"], s["customer"]["id"], lot["id"], proposed_basis_cents=12000)
    validate_success(api.start_review_basis_request(s["firm"]["id"], req["id"], TAX_OPS))
    validate_success(api.reject_basis_request(s["firm"]["id"], req["id"], TAX_OPS))
    validate_success(api.resubmit_basis_request(s["firm"]["id"], req["id"],
                                                make_customer_headers(s["customer"]["id"])))
    validate_success(api.start_review_basis_request(s["firm"]["id"], req["id"], TAX_OPS))
    validate_success(api.approve_basis_request(s["firm"]["id"], req["id"], make_tax_ops_headers("taxops-reviewer-1")))
    applied = validate_success(api.apply_basis_request(
        s["firm"]["id"], req["id"], {"expected_tax_lot_version": lot["version"]},
        make_tax_ops_headers("taxops-applier-2"),
    ))
    assert_basis_change_request(applied)
    assert applied["approved_by_user_id"] == "taxops-reviewer-1"
    assert applied["applied_by_user_id"] == "taxops-applier-2"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / basis_apply_gated_by_taxlot_version
# ---------------------------------------------------------------------------

def _approved_then_superseded():
    """Approved request on L1, then a SPLIT corporate action supersedes L1
    (mutating it, advancing its version)."""
    s, lot = _book_with_lot("TIN-XD-3", "111111121", "XD3")
    req = setup_approved_request(s["firm"]["id"], s["customer"]["id"], lot["id"],
                                 reviewer="taxops-reviewer-1", proposed_basis_cents=12000,
                                 supporting_doc_ref="DOC-9")
    ca = validate_success(api_client.create_corporate_action(
        s["firm"]["id"], s["security"]["id"],
        create_corporate_action_payload(action_type="SPLIT", split_ratio_numerator=2, split_ratio_denominator=1),
        TAX_OPS,
    ), 201)
    validate_success(api_client.apply_corporate_action(s["firm"]["id"], ca["id"], TAX_OPS))
    return s, lot, req


def test_apply_rejected_when_lot_mutated_after_approval(api):
    """PRD §2.8: "Applying an approved basis change —
    `POST /firms/{firmId}/basis_change_requests/{reqId}/apply` — requires
    `expected_tax_lot_version`, matched against the current `version` of the
    target tax lot. A mismatch is rejected with `ERR_STALE_LOT_VERSION`
    (HTTP 412): the lot's basis may already have been mutated since approval,
    for example by a corporate action or a wash-sale taint, so the approval's
    snapshot is stale."

    Design: Difficulty/cross_entity_state_dependency/basis_apply_gated_by_taxlot_version
    """
    s, lot, req = _approved_then_superseded()
    resp = api.apply_basis_request(
        s["firm"]["id"], req["id"], {"expected_tax_lot_version": lot["version"]},
        make_tax_ops_headers("taxops-applier-2"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION)


def test_stale_apply_leaves_request_approved(api):
    """PRD §3.9: "the lot must still sit exactly at the snapshot captured in
    `version_applied_to` — any drift is rejected with `ERR_STALE_LOT_VERSION`
    (HTTP 412)."

    Design: Difficulty/cross_entity_state_dependency/basis_apply_gated_by_taxlot_version
    """
    s, lot, req = _approved_then_superseded()
    validate_error(
        api.apply_basis_request(s["firm"]["id"], req["id"],
                                {"expected_tax_lot_version": lot["version"]},
                                make_tax_ops_headers("taxops-applier-2")),
        ApiErrorId.ERR_STALE_LOT_VERSION,
    )
    req_after = validate_success(api.get_basis_change_request(s["firm"]["id"], req["id"], TAX_OPS))
    assert req_after["status"] == "APPROVED", "rejected apply leaves the request unchanged"


# ---------------------------------------------------------------------------
# Corner: state_machines / approve gate; validations / doc + SOD
# ---------------------------------------------------------------------------

def test_basis_change_approve_requires_under_review(api):
    """PRD §3.9: "Starting review moves a `PENDING` request to `UNDER_REVIEW`."
    and approval is defined on a request under review; per PRD §2.6 "The target
    entity must be in the from-state the requested transition requires, or the
    request fails with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/basis_change_approve_requires_under_review
    """
    s, lot = _book_with_lot("TIN-SM-13", "262626262", "SMD")
    req = make_basis_request(s["firm"]["id"], s["customer"]["id"], lot["id"], proposed_basis_cents=12000)
    resp = api.approve_basis_request(s["firm"]["id"], req["id"], make_tax_ops_headers("taxops-r1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_basis_approve_missing_supporting_doc_rejected(api):
    """PRD §3.9: "Approval requires a non-empty `supporting_doc_ref` —
    approving without one fails with `ERR_MISSING_SUPPORTING_DOC` (HTTP 422)."

    Design: Corner/validations/basis_approve_missing_supporting_doc_rejected
    """
    s, lot = _book_with_lot("TIN-V-5", "484848484", "ND")
    req = make_basis_request(s["firm"]["id"], s["customer"]["id"], lot["id"],
                             proposed_basis_cents=12000, supporting_doc_ref=None)
    validate_success(api.start_review_basis_request(s["firm"]["id"], req["id"], TAX_OPS))
    resp = api.approve_basis_request(s["firm"]["id"], req["id"], make_tax_ops_headers("taxops-r1"))
    validate_error(resp, ApiErrorId.ERR_MISSING_SUPPORTING_DOC)


def test_basis_apply_same_user_sod_violation(api):
    """PRD §3.9: "The operator applying an `APPROVED` request must be a
    different `TaxOps` user than the one recorded in `approved_by_user_id`; the
    same user attempting both steps is refused with `ERR_SOD_VIOLATION`
    (HTTP 403)."

    Design: Corner/validations/basis_apply_same_user_sod_violation
    """
    s, lot = _book_with_lot("TIN-V-6", "494949494", "SOD")
    req = setup_approved_request(s["firm"]["id"], s["customer"]["id"], lot["id"],
                                 reviewer="taxops-solo-1", proposed_basis_cents=12000,
                                 supporting_doc_ref="DOC-SOD")
    resp = api.apply_basis_request(
        s["firm"]["id"], req["id"], {"expected_tax_lot_version": lot["version"]},
        make_tax_ops_headers("taxops-solo-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
    req_after = validate_success(api.get_basis_change_request(s["firm"]["id"], req["id"], TAX_OPS))
    assert req_after["status"] == "APPROVED", "SOD refusal leaves the request unchanged"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / OCC literal sequence
# ---------------------------------------------------------------------------

def test_occ_basis_apply_stale_lot_version_literal_sequence(api):
    """PRD §2.8: "Applying an approved basis change —
    `POST /firms/{firmId}/basis_change_requests/{reqId}/apply` — requires
    `expected_tax_lot_version`, matched against the current `version` of the
    target tax lot. A mismatch is rejected with `ERR_STALE_LOT_VERSION`
    (HTTP 412): the lot's basis may already have been mutated since approval,
    for example by a corporate action or a wash-sale taint, so the approval's
    snapshot is stale."
    PRD §3.9: "A `BASIS_AMOUNT_CORRECTION` replaces the lot's
    `adjusted_cost_basis_cents` with `proposed_basis_cents` while preserving
    `original_cost_basis_cents` for audit."

    Design: Corner/cross_cutting_layers/occ_basis_apply_stale_lot_version_literal_sequence
    """
    s, lot = _book_with_lot("TIN-X-2", "676767676", "OC2")
    lot_v0 = lot["version"]
    req1 = setup_approved_request(s["firm"]["id"], s["customer"]["id"], lot["id"],
                                  reviewer="taxops-rev-1", proposed_basis_cents=12000,
                                  supporting_doc_ref="DOC-A")
    applied1 = validate_success(api.apply_basis_request(
        s["firm"]["id"], req1["id"], {"expected_tax_lot_version": lot_v0},
        make_tax_ops_headers("taxops-app-1"),
    ))
    assert applied1["status"] == "APPLIED", "happy-path apply with the current version succeeds"
    req2 = setup_approved_request(s["firm"]["id"], s["customer"]["id"], lot["id"],
                                  reviewer="taxops-rev-1", proposed_basis_cents=13000,
                                  supporting_doc_ref="DOC-B")
    resp = api.apply_basis_request(
        s["firm"]["id"], req2["id"], {"expected_tax_lot_version": lot_v0},
        make_tax_ops_headers("taxops-app-2"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION)
    req2_after = validate_success(api.get_basis_change_request(s["firm"]["id"], req2["id"], TAX_OPS))
    assert req2_after["status"] == "APPROVED"
    lot_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["adjusted_cost_basis_cents"] == 12000, (
        "REQ1's value stands; the failed REQ2 apply must not overwrite it"
    )


# ---------------------------------------------------------------------------
# Corner: rbac / ownership on resubmit; CustomerService allowed to submit
# ---------------------------------------------------------------------------

def test_customer_cannot_resubmit_other_customers_request(api):
    """PRD §3.9: "Rejection from `UNDER_REVIEW` moves the request to
    `REJECTED`, from which the owning customer — and only that customer,
    verified by comparing the request's customer to the caller's `X-User-ID` —
    may resubmit it, moving it to `RESUBMITTED`."
    PRD §2.1: "a well-identified caller whose role is not admitted to an
    endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_resubmit_other_customers_request
    """
    firm = make_firm("Firm R4")
    cust1 = make_customer(firm["id"], tin="TIN-R-4A", display_name="Owner")
    cust2 = make_customer(firm["id"], tin="TIN-R-4B", display_name="Intruder")
    acct = make_account(firm["id"], cust1["id"])
    sec = make_security(firm["id"], cusip="646464646", ticker="RB4")
    lot = make_lot(firm["id"], acct["id"], sec["id"], quantity=10, basis=10000)
    req = make_basis_request(firm["id"], cust1["id"], lot["id"], proposed_basis_cents=12000,
                             supporting_doc_ref="DOC-OWN")
    validate_success(api.start_review_basis_request(firm["id"], req["id"], TAX_OPS))
    validate_success(api.reject_basis_request(firm["id"], req["id"], TAX_OPS))
    resp = api.resubmit_basis_request(firm["id"], req["id"], make_customer_headers(cust2["id"]))
    # PRD §3.9 pins the ownership gate ("only that customer ... may resubmit")
    # but names no error_id for its violation; ERR_FORBIDDEN_FOR_ROLE (§2.1)
    # and ERR_NOT_FOUND (§2.5 non-disclosure) are both faithful readings.
    validate_error_is_one_of(resp, [ApiErrorId.ERR_FORBIDDEN_FOR_ROLE,
                                    ApiErrorId.ERR_NOT_FOUND])


def test_customer_service_can_submit_basis_request(api):
    """PRD §2.1: "`CustomerService` is a read-heavy support role that can book
    lots and dispositions on a customer's behalf and submit basis change
    requests for them."
    PRD §3.9: "New requests are born `PENDING`, and a customer who is
    `SUSPENDED` or `CLOSED` cannot file one (`ERR_CUSTOMER_SUSPENDED`)."

    Design: Corner/rbac/customer_service_can_submit_basis_request
    """
    s, lot = _book_with_lot("TIN-R-5", "656565656", "RB5")
    resp = api.create_basis_change_request(
        s["firm"]["id"], s["customer"]["id"],
        {"tax_lot_id": lot["id"], "request_kind": "BASIS_AMOUNT_CORRECTION",
         "proposed_basis_cents": 11500, "supporting_doc_ref": "DOC-CS"},
        CUSTOMER_SERVICE,
    )
    req = validate_success(resp, 201)
    assert_basis_change_request(req)
    assert req["status"] == "PENDING"
