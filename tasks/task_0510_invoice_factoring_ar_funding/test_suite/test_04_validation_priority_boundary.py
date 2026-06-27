"""Validation-priority conflicts (state vs fiscal, safety vs constraint) and
numeric boundary precision (concentration ratio equality, aging dpd edge).

Difficulty queue A: priority_pair_validation_conflict, boundary_precision_check.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, setup_funding_ready, setup_funded_invoice,
    submit_and_verify_invoice, create_batch_payload, fund_batch_payload,
    advance_clock, create_relationship,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]
FO = TEST_USERS["funding_headers"]
CO = TEST_USERS["collections_headers"]


def _client_version(api, client_id):
    return validate_success(api.get_client(client_id, FO), 200)["version"]


def test_refund_funded_batch_returns_invalid_state_over_credit_limit(api):
    """PRD §2.6: "State validity — the target resource is in a state from which
    the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409)." and
    "The remaining business checks (... credit limit ...) are evaluated within
    the workflow they guard, after the foregoing structural and state checks
    have passed."

    Re-funding an already-FUNDED batch (whose re-fund would also blow the tiny
    credit limit) returns ERR_INVALID_STATE — state (p10) wins over fiscal (p17).

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_fiscal_credit_limit
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               credit_limit_cents=90000, concentration_pct=0.90,
                               invoice_overrides={"invoice_number": "INV-PP"})
    batch_id = ctx["batch"]["id"]
    cv = _client_version(api, ctx["client"]["id"])
    res = api.fund_batch(batch_id, fund_batch_payload(cv), FO)
    validate_error(res, "ERR_INVALID_STATE")


def test_refund_funded_batch_leaves_batch_funded(api):
    """PRD §3.5: "If every listed invoice clears, the batch moves `DRAFT →
    FUNDED`". PRD §2.6: "State validity — the target resource is in a state from
    which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409)."

    A rejected re-fund (ERR_INVALID_STATE) does not alter the already-FUNDED
    batch — it stays FUNDED, never moves to FAILED.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_fiscal_credit_limit
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               credit_limit_cents=90000, concentration_pct=0.90,
                               invoice_overrides={"invoice_number": "INV-PP"})
    batch_id = ctx["batch"]["id"]
    cv = _client_version(api, ctx["client"]["id"])
    api.fund_batch(batch_id, fund_batch_payload(cv), FO)
    after = validate_success(api.get_batch(batch_id, FO), 200)
    assert after["status"] == "FUNDED", (
        f"already-FUNDED batch stays FUNDED after a rejected re-fund, "
        f"got {after['status']}")


def test_fund_suspended_relationship_returns_funding_blocked_over_concentration(api):
    """PRD §3.5: "The invoice is `VERIFIED`, the client is `APPROVED`, and the
    program is `ACTIVE`; if the client is not approved, the program is suspended,
    or (as below) the relationship is not noticed, funding is blocked with
    `ERR_FUNDING_BLOCKED`." ... "The governing relationship's `notice_status` is
    `NOTICED`; otherwise funding is blocked, also with `ERR_FUNDING_BLOCKED`."
    ... "The debtor-concentration check of Section 2.10 passes; otherwise the
    invoice is rejected with `ERR_CONCENTRATION_EXCEEDED`."

    A SUSPENDED relationship (notice != NOTICED) whose invoice also breaches the
    tiny concentration limit returns ERR_FUNDING_BLOCKED — the funding-blocked
    check precedes the concentration check.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_before_constraint_on_fund
    """
    parties = setup_funding_ready(
        client_approve_overrides={"approved_advance_rate_pct": 0.85,
                                  "credit_limit_cents": 100_000_000,
                                  "default_concentration_limit_pct": 0.01},
        debtor_approve_overrides={"approved_credit_ceiling_cents": 100_000_000,
                                  "verification_required": False},
        relationship_overrides={"recourse_type": "RECOURSE"},
        noticed=True)
    client = parties["client"]
    debtor = parties["debtor"]
    rel = parties["relationship"]
    invoice = submit_and_verify_invoice(client["id"], debtor["id"],
                                        invoice_number="INV-PP2",
                                        face_amount_cents=100000)
    validate_success(api.suspend_relationship(rel["id"], FO), 200)
    batch = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [invoice["id"]], batch_reference="B-PP2"), FO))
    cv = _client_version(api, client["id"])
    res = api.fund_batch(batch["id"], fund_batch_payload(cv), FO)
    validate_error(res, "ERR_FUNDING_BLOCKED")


def test_fund_suspended_relationship_batch_fails_with_funding_blocked_error_id(api):
    """PRD §3.5: "If any invoice fails a funding precondition when it is reached
    in array order, no invoice in the batch is funded and no client or debtor
    balance change persists; the batch moves `DRAFT → FAILED`, its
    `failure_error_id` is set to the `error_id` of the first invoice that
    failed".

    The SUSPENDED-relationship fund (where concentration would also breach)
    records failure_error_id == ERR_FUNDING_BLOCKED (the safety check, not the
    concentration constraint).

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_before_constraint_on_fund
    """
    parties = setup_funding_ready(
        client_approve_overrides={"approved_advance_rate_pct": 0.85,
                                  "credit_limit_cents": 100_000_000,
                                  "default_concentration_limit_pct": 0.01},
        debtor_approve_overrides={"approved_credit_ceiling_cents": 100_000_000,
                                  "verification_required": False},
        relationship_overrides={"recourse_type": "RECOURSE"},
        noticed=True)
    client, debtor, rel = parties["client"], parties["debtor"], parties["relationship"]
    invoice = submit_and_verify_invoice(client["id"], debtor["id"],
                                        invoice_number="INV-PP2", face_amount_cents=100000)
    validate_success(api.suspend_relationship(rel["id"], FO), 200)
    batch = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [invoice["id"]], batch_reference="B-PP2"), FO))
    cv = _client_version(api, client["id"])
    api.fund_batch(batch["id"], fund_batch_payload(cv), FO)
    batch_after = validate_success(api.get_batch(batch["id"], FO), 200)
    assert batch_after["status"] == "FAILED"
    assert batch_after["failure_error_id"] == "ERR_FUNDING_BLOCKED", (
        f"failure_error_id is the safety error ERR_FUNDING_BLOCKED, "
        f"got {batch_after['failure_error_id']}")


def test_concentration_ratio_exact_equal_is_allowed(api):
    """PRD §2.10: "Funding is rejected only when the prospective debtor exposure
    is strictly greater than the ceiling times the prospective portfolio; the
    boundary case where the two are exactly equal is allowed."

    DebtorX 150000 + DebtorY 350000 funded; candidate DebtorX 200000 ->
    de_after=350000, pf_after=700000, exactly 0.50 -> funding ALLOWED.

    Design: Difficulty/boundary_precision_check/bpc_concentration_ratio_exact_equal_allowed
    """
    program = get_success_data(api.create_program({"name": "F-BPC"}, ADMIN))
    from test_helpers import create_approved_client, create_approved_debtor
    client = create_approved_client(
        program["id"],
        approve_overrides={"approved_advance_rate_pct": 0.50,
                           "credit_limit_cents": 100_000_000,
                           "default_concentration_limit_pct": 0.50},
        client_overrides={"requested_advance_rate_pct": 0.50})
    debtor_x = create_approved_debtor(program["id"],
                                      debtor_overrides={"legal_name": "DebtorX"})
    debtor_y = create_approved_debtor(program["id"],
                                      debtor_overrides={"legal_name": "DebtorY"})
    rel_x = create_relationship(client["id"], debtor_x["id"], noticed=True,
                                recourse_type="RECOURSE", concentration_limit_pct=0.50)
    create_relationship(client["id"], debtor_y["id"], noticed=True,
                        recourse_type="RECOURSE", concentration_limit_pct=1.0)

    x_pre = submit_and_verify_invoice(client["id"], debtor_x["id"],
                                      invoice_number="X-PRE", face_amount_cents=150000)
    y_pre = submit_and_verify_invoice(client["id"], debtor_y["id"],
                                      invoice_number="Y-PRE", face_amount_cents=350000)
    pre_batch = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [y_pre["id"], x_pre["id"]],
                             batch_reference="B-PRE"), FO))
    cv0 = _client_version(api, client["id"])
    validate_success(api.fund_batch(pre_batch["id"], fund_batch_payload(cv0), FO), 200)

    x_cand = submit_and_verify_invoice(client["id"], debtor_x["id"],
                                       invoice_number="X-CAND", face_amount_cents=200000)
    cand_batch = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [x_cand["id"]], batch_reference="B-CAND"), FO))
    cv1 = _client_version(api, client["id"])
    funded = validate_success(api.fund_batch(cand_batch["id"], fund_batch_payload(cv1), FO), 200)
    assert funded["status"] == "FUNDED", (
        f"exact ratio 0.50 is allowed, batch should be FUNDED, got {funded['status']}")
    cand_invoice = validate_success(api.get_invoice(x_cand["id"], FO), 200)
    assert cand_invoice["status"] == "FUNDED", (
        f"de_after 350000 == 0.50*pf_after 700000, '==' allowed, "
        f"got {cand_invoice['status']}")


def test_concentration_exact_equal_debtor_face_includes_candidate(api):
    """PRD §2.10: "the debtor's prospective exposure (the debtor's
    `outstanding_face_cents` plus the candidate's `face_amount_cents`) is
    compared against the ceiling multiplied by the prospective portfolio ...
    Funding is rejected only when the prospective debtor exposure is strictly
    greater than the ceiling times the prospective portfolio; the boundary case
    where the two are exactly equal is allowed."

    After the allowed exact-ratio fund, DebtorX exposure includes the candidate:
    150000 + 200000 = 350000.

    Design: Difficulty/boundary_precision_check/bpc_concentration_ratio_exact_equal_allowed
    """
    program = get_success_data(api.create_program({"name": "F-BPC2"}, ADMIN))
    from test_helpers import create_approved_client, create_approved_debtor
    client = create_approved_client(
        program["id"],
        approve_overrides={"approved_advance_rate_pct": 0.50,
                           "credit_limit_cents": 100_000_000,
                           "default_concentration_limit_pct": 0.50},
        client_overrides={"requested_advance_rate_pct": 0.50})
    debtor_x = create_approved_debtor(program["id"],
                                      debtor_overrides={"legal_name": "DebtorX"})
    debtor_y = create_approved_debtor(program["id"],
                                      debtor_overrides={"legal_name": "DebtorY"})
    rel_x = create_relationship(client["id"], debtor_x["id"], noticed=True,
                                recourse_type="RECOURSE", concentration_limit_pct=0.50)
    create_relationship(client["id"], debtor_y["id"], noticed=True,
                        recourse_type="RECOURSE", concentration_limit_pct=1.0)
    x_pre = submit_and_verify_invoice(client["id"], debtor_x["id"],
                                      invoice_number="X-PRE", face_amount_cents=150000)
    y_pre = submit_and_verify_invoice(client["id"], debtor_y["id"],
                                      invoice_number="Y-PRE", face_amount_cents=350000)
    pre_batch = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [y_pre["id"], x_pre["id"]],
                             batch_reference="B-PRE"), FO))
    validate_success(api.fund_batch(pre_batch["id"],
                                    fund_batch_payload(_client_version(api, client["id"])), FO), 200)
    x_cand = submit_and_verify_invoice(client["id"], debtor_x["id"],
                                       invoice_number="X-CAND", face_amount_cents=200000)
    cand_batch = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [x_cand["id"]], batch_reference="B-CAND"), FO))
    validate_success(api.fund_batch(cand_batch["id"],
                                    fund_batch_payload(_client_version(api, client["id"])), FO), 200)
    debtor_x_after = validate_success(api.get_debtor(debtor_x["id"], FO), 200)
    assert debtor_x_after["outstanding_face_cents"] == 350000, (
        f"DebtorX exposure 150000+200000=350000 after the allowed fund, "
        f"got {debtor_x_after['outstanding_face_cents']}")


def test_aging_bucket_crosses_to_dpd_31_60_at_dpd_31(api):
    """PRD §2.10: "`DPD_31_60` when at least 31 and at most 60 ... The upper edge
    of each band is inclusive: 30 days past due is `DPD_1_30`, 31 is
    `DPD_31_60`". PRD §3.6: "the system automatically moves the invoice from
    `FUNDED` to `OUTSTANDING`".

    due_date 2026-05-31, clock 2026-07-01 (dpd 31) -> aging_bucket DPD_31_60,
    status OUTSTANDING, no collections.

    Design: Difficulty/boundary_precision_check/bpc_aging_bucket_empty_collection_vs_dpd_31_edge
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               invoice_overrides={"invoice_number": "INV-AGE"})
    advance_clock("2026-07-01T00:00:00Z")  # dpd 31
    invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], CO), 200)
    assert invoice["status"] == "OUTSTANDING", (
        f"auto FUNDED->OUTSTANDING fires past due, got {invoice['status']}")
    assert invoice["aging_bucket"] == "DPD_31_60", (
        f"dpd 31 crosses to DPD_31_60, got {invoice['aging_bucket']}")
    assert invoice["amount_collected_cents"] == 0, (
        f"empty posting set, got {invoice['amount_collected_cents']}")


def test_funded_invoice_auto_outstanding_on_clock_advance_empty_collection(api):
    """PRD §3.6: "As the logical clock advances past an invoice's `due_date`
    while it has not been fully collected — that is, while its
    `amount_collected_cents` is still below `face_amount_cents` minus
    `dilution_cents` — the system automatically moves the invoice from `FUNDED`
    to `OUTSTANDING`".

    With no collections at all, advancing the clock past due fires the automatic
    FUNDED->OUTSTANDING crossing.

    Design: Difficulty/boundary_precision_check/bpc_aging_bucket_empty_collection_vs_dpd_31_edge
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               invoice_overrides={"invoice_number": "INV-AGE"})
    before = validate_success(api.get_invoice(ctx["invoice"]["id"], CO), 200)
    assert before["status"] == "FUNDED"
    advance_clock("2026-07-01T00:00:00Z")
    after = validate_success(api.get_invoice(ctx["invoice"]["id"], CO), 200)
    assert after["status"] == "OUTSTANDING", (
        f"empty collection + clock past due -> OUTSTANDING, got {after['status']}")
