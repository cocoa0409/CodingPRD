"""Corner coverage — action endpoints, error conditions, RBAC, the OCC
stale-version guard, the cancel→void cascade, and immediate consistency.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_office, create_client, create_return, create_refund_transfer,
    create_approved_advance, create_audit_protection,
    setup_return_prepared, setup_return_accepted, setup_return_in_prep,
    setup_return_in_docs_pending, setup_office_with_preparer,
    build_user_headers, api_client, TEST_USERS,
)

OM = TEST_USERS["office_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
BO = TEST_USERS["bank_officer_headers"]


# ─── endpoints ─────────────────────────────────────────────────────────────

def test_efin_status_reinstate_then_active(api):
    """PRD §3.1: "The manager can later flip efin_status between ACTIVE and
    SUSPENDED by submitting the new efin_status"

    Design: Corner/endpoints/efin_status_reinstate_then_active
    """
    office = create_office()
    validate_success(api.set_efin_status(office["id"], {"efin_status": "SUSPENDED"}, OM), 200)
    reinstated = validate_success(api.set_efin_status(office["id"], {"efin_status": "ACTIVE"}, OM), 200)
    assert reinstated["efin_status"] == "ACTIVE"


def test_get_efile_submissions_after_transmission(api):
    """PRD §3.5: "creates one EfileSubmission in TRANSMITTED status, recording
    the parent tax_return_id, the efin_used copied from the office's EFIN at
    transmission time, and the ptin_used copied from the assigned preparer's
    credential PTIN at transmission time."

    Design: Corner/endpoints/get_efile_submissions_after_transmission
    """
    # Controlled efin/ptin so the snapshot values are known.
    office, cred, prep, ph = setup_office_with_preparer(
        office_overrides={"efin": "100028"}, credential_overrides={"ptin": "P20202021"})
    client = create_client(office["id"], full_name="Sb Cli", ssn_last4="5757")
    ret = create_return(office["id"], client["id"], headers=ph, tax_year=2025, complexity_band="SIMPLE")
    from test_helpers import add_document, set_document_received
    doc = add_document(ret["id"], ph, is_required=True)
    set_document_received(doc["id"], ph)
    validate_success(api.assign_return(ret["id"], {"preparer_id": prep["id"]}, ph), 200)
    validate_success(api.transition_return(ret["id"], {"to": "DOCS_PENDING"}, ph), 200)
    validate_success(api.transition_return(ret["id"], {"to": "IN_PREP"}, ph), 200)
    validate_success(api.transition_return(ret["id"], {"to": "PREPARED"}, ph), 200)
    validate_success(api.efile_return(ret["id"], ph), 200)

    subs, _ = validate_paginated(api.list_efile_submissions(ret["id"], ph))
    assert len(subs) == 1, f"expected exactly one submission, got {len(subs)}"
    sub = subs[0]
    assert sub["ack_status"] == "TRANSMITTED"
    assert sub["efin_used"] == "100028"
    assert sub["ptin_used"] == "P20202021"


def test_refund_transfer_adjust_bumps_version_stays_pending(api):
    """PRD §3.7: "The revision re-stamps estimated_refund_cents to the supplied
    figure and increments the transfer's version by one, leaving the transfer in
    PENDING_FUNDING."

    Design: Corner/endpoints/refund_transfer_adjust_bumps_version_stays_pending
    """
    office = create_office(bank_product_enabled=True)
    client = create_client(office["id"], full_name="Aj Cli", ssn_last4="6464")
    ret = create_return(office["id"], client["id"], tax_year=2025)
    rt = create_refund_transfer(ret["id"])
    base_version = rt["version"]
    adjusted = validate_success(api.adjust_refund_transfer(
        rt["id"], {"estimated_refund_cents": 480000}, BO), 200)
    assert adjusted["estimated_refund_cents"] == 480000
    assert adjusted["status"] == "PENDING_FUNDING"
    assert adjusted["version"] == base_version + 1, \
        f"version should bump by 1 from {base_version}, got {adjusted['version']}"


# ─── errors ────────────────────────────────────────────────────────────────

def test_advance_disburse_no_refund_transfer(api):
    """PRD §3.8: "and requires a RefundTransfer in PENDING_FUNDING to exist for
    the same return, else ERR_NO_REFUND_TRANSFER."

    Design: Corner/errors/error_advance_disburse_no_refund_transfer
    """
    ctx = setup_return_accepted(
        bank_product_enabled=True,
        client_overrides={"risk_band": "LOW"},
        return_overrides={"complexity_band": "SIMPLE", "expected_refund_cents": 500000})
    rid = ctx["return"]["id"]
    adv = create_approved_advance(rid, 60000)
    # No RefundTransfer opened for this return.
    res = api.disburse_refund_advance(adv["id"], BO)
    validate_error(res, "ERR_NO_REFUND_TRANSFER", expected_status=409)
    after = validate_success(api.get_refund_advance(adv["id"], BO), 200)
    assert after["status"] == "APPROVED"


def test_invalid_refund_figure_on_disburse(api):
    """PRD §3.7: "the disbursed_refund_cents must be greater than zero, else
    ERR_INVALID_REFUND_FIGURE"

    Design: Corner/errors/error_invalid_refund_figure_on_disburse
    """
    ctx = setup_return_accepted(
        bank_product_enabled=True,
        client_overrides={"risk_band": "LOW"},
        return_overrides={"complexity_band": "SIMPLE", "expected_refund_cents": 500000})
    rid = ctx["return"]["id"]
    rt = create_refund_transfer(rid)
    res = api.disburse_refund_transfer(
        rt["id"], {"disbursed_refund_cents": 0, "expected_refundtransfer_version": rt["version"]}, BO)
    validate_error(res, "ERR_INVALID_REFUND_FIGURE", expected_status=409)
    after = validate_success(api.get_refund_transfer(rt["id"], BO), 200)
    assert after["status"] == "PENDING_FUNDING"


# ─── rbac ──────────────────────────────────────────────────────────────────

def test_front_desk_cannot_create_office(api):
    """PRD §2.1: "When the headers are present and valid but the named role is
    not permitted to perform the requested operation, the request is rejected
    with ERR_FORBIDDEN (HTTP 403)."
    PRD §4: POST /offices is authorized only for OfficeManager.

    Design: Corner/rbac/front_desk_cannot_create_office
    """
    res = api.create_office({"name": "X Office", "efin": "100031", "state_code": "HI"}, FD)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_front_desk_cannot_efile(api):
    """PRD §2.1: "When the headers are present and valid but the named role is
    not permitted to perform the requested operation, the request is rejected
    with ERR_FORBIDDEN (HTTP 403)."
    PRD §4: POST /returns/{id}/efile is authorized only for TaxPreparer.

    Design: Corner/rbac/front_desk_cannot_efile
    """
    ctx = setup_return_prepared(return_overrides={"complexity_band": "SIMPLE"})
    res = api.efile_return(ctx["return"]["id"], FD)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
    after = validate_success(api.get_return(ctx["return"]["id"], ctx["prep_headers"]), 200)
    assert after["status"] == "PREPARED"


def test_unknown_role_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of
    the recognized role names, the request is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    res = api.create_office({"name": "Auth Office", "efin": "100033", "state_code": "CA"},
                            build_user_headers("stranger-1", "Stranger"))
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── cross_cutting_complexity_layers ───────────────────────────────────────

def test_occ_stale_version_on_refund_transfer_disburse(api):
    """PRD §2.6: "If that value does not equal the transfer's current version,
    the disburse is rejected with ERR_STALE_VERSION (HTTP 412)."
    PRD §2.6: "A disburse request that still carries the version observed before
    a revision will therefore find the transfer in an identical PENDING_FUNDING
    state — every state precondition passes — yet the version it presents is
    stale"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_refund_transfer_disburse
    """
    ctx = setup_return_accepted(
        bank_product_enabled=True,
        client_overrides={"risk_band": "LOW"},
        return_overrides={"complexity_band": "SIMPLE", "expected_refund_cents": 500000})
    rid = ctx["return"]["id"]
    rt = create_refund_transfer(rid)
    stale_version = rt["version"]
    # An /adjust supersedes the transfer, bumping version while keeping PENDING_FUNDING.
    validate_success(api.adjust_refund_transfer(rt["id"], {"estimated_refund_cents": 510000}, BO), 200)
    res = api.disburse_refund_transfer(
        rt["id"], {"disbursed_refund_cents": 500000, "expected_refundtransfer_version": stale_version}, BO)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    after = validate_success(api.get_refund_transfer(rt["id"], BO), 200)
    assert after["status"] == "PENDING_FUNDING", "rejected disburse must not apply"


def test_cancel_cascade_voids_audit_protection(api):
    """PRD §3.5: "Every AuditProtection on the return that is currently ACTIVE
    is moved to VOIDED."

    Design: Corner/cross_cutting_complexity_layers/cancel_cascade_voids_audit_protection
    """
    # Return in IN_PREP at a bank office with an ACTIVE AuditProtection.
    ctx = setup_return_in_prep(
        bank_product_enabled=True,
        client_overrides={"risk_band": "LOW"},
        return_overrides={"complexity_band": "SIMPLE"})
    rid = ctx["return"]["id"]
    ap = create_audit_protection(rid)
    cancelled = validate_success(api.transition_return(rid, {"to": "CANCELLED"}, ctx["prep_headers"]), 200)
    assert cancelled["status"] == "CANCELLED"
    ap_after = validate_success(api.get_audit_protection(ap["id"], BO), 200)
    assert ap_after["status"] == "VOIDED", "ACTIVE audit-protection must cascade to VOIDED (not CANCELLED)"


# ─── consistency_model ─────────────────────────────────────────────────────

def test_prep_fee_visible_in_in_prep_response(api):
    """PRD §3.4: "The move into IN_PREP is also where the preparation fee is
    computed, written to prep_fee_cents, and materialized as FeeLine rows"

    Design: Corner/consistency_model/prep_fee_visible_in_same_response
    """
    ctx = setup_return_in_docs_pending(
        client_overrides={"full_name": "Im Cli", "ssn_last4": "6363", "is_returning": False},
        return_overrides={"complexity_band": "STANDARD", "schedules": ["A", "C"],
                          "state_return_count": 1})
    res = api.transition_return(ctx["return"]["id"], {"to": "IN_PREP"}, ctx["prep_headers"])
    ret = validate_success(res, 200)
    # The transition response itself carries the computed fee (immediate consistency).
    assert ret["prep_fee_cents"] == 40800, f"expected 40800 in the same response, got {ret['prep_fee_cents']}"
