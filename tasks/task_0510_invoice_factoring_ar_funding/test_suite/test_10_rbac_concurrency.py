"""RBAC breadth (unauthenticated, unauthorized exclusives, segregation of
duties), OCC stale-version on fund and posting, dilution recompute, and
immediate consistency of funding balances.

Corner queue B: rbac, cross_cutting_complexity_layers, consistency_model.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_funding_ready, setup_funded_invoice, submit_and_verify_invoice,
    create_pending_client, create_relationship,
    create_approved_client, create_approved_debtor,
    create_batch_payload, fund_batch_payload, approve_client_payload,
    make_funding_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]
UW2 = TEST_USERS["underwriter2_headers"]
FO = TEST_USERS["funding_headers"]
CO = TEST_USERS["collections_headers"]


def _cv(api, client_id):
    return validate_success(api.get_client(client_id, FO), 200)["version"]


# ─── rbac ────────────────────────────────────────────────────────────────────

def test_unauthenticated_missing_role_header(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    the recognized role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/rbac_unauthenticated_missing_role_header
    """
    res = api.list_programs(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_collections_cannot_fund_batch(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4: fund is authorized for FundingOfficer
    only.

    CollectionsOfficer funding a batch -> ERR_UNAUTHORIZED; batch stays DRAFT.

    Design: Corner/rbac/rbac_collections_cannot_fund_batch
    """
    parties = setup_funding_ready(
        debtor_approve_overrides={"approved_credit_ceiling_cents": 100_000_000,
                                  "verification_required": False})
    client, debtor = parties["client"], parties["debtor"]
    invoice = submit_and_verify_invoice(client["id"], debtor["id"],
                                        invoice_number="INV-RB", face_amount_cents=100000)
    batch = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [invoice["id"]], batch_reference="B-RB"), FO))
    cv = _cv(api, client["id"])
    res = api.fund_batch(batch["id"], fund_batch_payload(cv), CO)
    validate_error(res, "ERR_UNAUTHORIZED")
    batch_after = validate_success(api.get_batch(batch["id"], FO), 200)
    assert batch_after["status"] == "DRAFT"


def test_funding_cannot_make_credit_decision(api):
    """PRD §2.1: "the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: client credit-decision is authorized for UnderwritingOfficer only.

    FundingOfficer calling client credit-decision -> ERR_UNAUTHORIZED; client
    stays PENDING.

    Design: Corner/rbac/rbac_funding_cannot_make_credit_decision
    """
    program = get_success_data(api.create_program({"name": "P-RB2"}, ADMIN))
    client = create_pending_client(program["id"])
    res = api.client_credit_decision(client["id"], approve_client_payload(), FO)
    validate_error(res, "ERR_UNAUTHORIZED")
    after = validate_success(api.get_client(client["id"], FO), 200)
    assert after["status"] == "PENDING"


def test_segregation_of_duties_funder_equals_credit_decision_user(api):
    """PRD §3.5: "the funding officer's `X-User-ID` must differ from the
    `credit_decision_user_id` recorded on both the client and the debtor of
    every invoice in the batch; if the funding officer is the same person who
    underwrote either party, the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Client approved by uw_1; funding as X-User-ID uw_1 -> ERR_SEGREGATION_OF_DUTIES;
    batch stays DRAFT.

    Design: Corner/rbac/rbac_segregation_dedicated
    """
    program = get_success_data(api.create_program({"name": "P-SOD"}, ADMIN))
    # Client approved by uw_1, debtor approved by uw_2 (so only the client's
    # credit-decision user collides with the funder).
    client = create_approved_client(program["id"], uw_user_id="uw_1")
    debtor = create_approved_debtor(program["id"], uw_user_id="uw_2",
                                    approve_overrides={"approved_credit_ceiling_cents": 100_000_000,
                                                       "verification_required": False})
    create_relationship(client["id"], debtor["id"], noticed=True)
    invoice = submit_and_verify_invoice(client["id"], debtor["id"],
                                        invoice_number="INV-SOD", face_amount_cents=100000)
    batch = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [invoice["id"]], batch_reference="B-SOD"), FO))
    cv = _cv(api, client["id"])
    res = api.fund_batch(batch["id"], fund_batch_payload(cv), make_funding_headers("uw_1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
    batch_after = validate_success(api.get_batch(batch["id"], FO), 200)
    assert batch_after["status"] == "DRAFT"


# ─── cross_cutting: OCC and derived-field reconciliation ─────────────────────

def test_fund_stale_client_version_rejected(api):
    """PRD §2.4: "When funding a purchase batch, the request must carry
    `expected_client_version` matching the funding client's current `version`.
    If another funding has advanced principal against this client since the
    caller last read it ... the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412) before any invoice is funded."

    Two batches; fund A advances Client.version; fund B with the pre-advance
    version -> ERR_STALE_VERSION; batch_b stays DRAFT.

    Design: Corner/cross_cutting_complexity_layers/occ_fund_stale_client_version_412
    """
    parties = setup_funding_ready(
        debtor_approve_overrides={"approved_credit_ceiling_cents": 100_000_000,
                                  "verification_required": False})
    client, debtor = parties["client"], parties["debtor"]
    inv_a = submit_and_verify_invoice(client["id"], debtor["id"],
                                      invoice_number="INV-OCC-A", face_amount_cents=100000)
    inv_b = submit_and_verify_invoice(client["id"], debtor["id"],
                                      invoice_number="INV-OCC-B", face_amount_cents=100000)
    batch_a = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [inv_a["id"]], batch_reference="B-OCC-A"), FO))
    batch_b = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [inv_b["id"]], batch_reference="B-OCC-B"), FO))
    stale_cv = _cv(api, client["id"])
    validate_success(api.fund_batch(batch_a["id"], fund_batch_payload(stale_cv), FO), 200)
    res = api.fund_batch(batch_b["id"], fund_batch_payload(stale_cv), FO)
    validate_error(res, "ERR_STALE_VERSION")
    batch_b_after = validate_success(api.get_batch(batch_b["id"], FO), 200)
    assert batch_b_after["status"] == "DRAFT"


def test_posting_stale_client_version_rejected(api):
    """PRD §2.4: "When posting a collection against an invoice, the request must
    likewise carry `expected_client_version` matching the owning client's current
    `version`. If a prior settlement or buyback has already moved the client's
    reserve balance since the caller's last read ... it is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    First posting advances Client.version; second posting reusing the stale
    version -> ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_posting_stale_version
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005,
                               invoice_overrides={"invoice_number": "INV-OCC2"})
    inv_id = ctx["invoice"]["id"]
    client_id = ctx["client"]["id"]
    stale_cv = validate_success(api.get_client(client_id, CO), 200)["version"]
    validate_success(api.create_posting(
        inv_id, {"amount_cents": 30000, "received_at": "2026-05-10T00:00:00Z",
                 "payer": "DEBTOR", "expected_client_version": stale_cv}, CO), 201)
    res = api.create_posting(
        inv_id, {"amount_cents": 20000, "received_at": "2026-05-11T00:00:00Z",
                 "payer": "DEBTOR", "expected_client_version": stale_cv}, CO)
    validate_error(res, "ERR_STALE_VERSION")


def test_dilution_recompute_on_adjustment(api):
    """PRD §3.8: "The invoice's `dilution_cents` — which reduces the collectible
    face used throughout collection and settlement — is recomputed as the sum of
    `amount_cents` over adjustments whose `type` is `DILUTION` or `CREDIT_MEMO`."

    A 20000 DILUTION adjustment sets dilution_cents == 20000.

    Design: Corner/cross_cutting_complexity_layers/ddr_dilution_recompute_on_adjustment
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005,
                               invoice_overrides={"invoice_number": "INV-DIL"})
    inv_id = ctx["invoice"]["id"]
    validate_success(api.create_adjustment(
        inv_id, {"type": "DILUTION", "amount_cents": 20000, "reason": "short ship"}, CO), 201)
    invoice = validate_success(api.get_invoice(inv_id, CO), 200)
    assert invoice["dilution_cents"] == 20000, (
        f"DILUTION 20000 -> dilution_cents 20000, got {invoice['dilution_cents']}")
    from test_helpers import validate_paginated
    data, _ = validate_paginated(api.list_adjustments(FO, params={"invoice_id": inv_id}))
    assert len(data) == 1


# ─── consistency_model ───────────────────────────────────────────────────────

def test_immediate_funding_balances_visible_same_read(api):
    """PRD §2.8: "On each client, `reserve_balance_cents` is the sum of
    `reserve_held_cents` across that client's invoices whose status is `FUNDED`,
    `OUTSTANDING`, or `SHORT_PAID` ... and `funded_advance_outstanding_cents` is
    the sum of `advance_outstanding_cents` across that same set of invoices."

    Immediately after funding (face 100000 @ 0.85): reserve 15000, outstanding
    advance 85000.

    Design: Corner/consistency_model/cm_immediate_funding_balances_visible_same_request
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               invoice_overrides={"invoice_number": "INV-IMM"})
    client = validate_success(api.get_client(ctx["client"]["id"], FO), 200)
    assert client["reserve_balance_cents"] == 15000
    assert client["funded_advance_outstanding_cents"] == 85000
