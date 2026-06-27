"""Corner coverage — calculations (complex band, fee-line materialization,
waterfall shortfall, deny-sets-zero) and validations (duplicate return, capacity,
bank-product gate, EFIN-suspended, amend-target).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_office, create_client, create_return, create_refund_advance,
    create_refund_transfer, setup_return_in_docs_pending, setup_return_in_prep,
    setup_return_prepared, setup_office_with_preparer,
    add_document, set_document_received,
    api_client, TEST_USERS,
)

OM = TEST_USERS["office_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
BO = TEST_USERS["bank_officer_headers"]


# ─── calculations ──────────────────────────────────────────────────────────

def test_prep_fee_complex_band_all_schedules(api):
    """PRD §3.4: "SIMPLE uses 1.00, STANDARD uses 1.20, and COMPLEX uses 1.50."
    PRD §3.4: "the per-schedule fees are 4000 cents for A, 2500 for B, 9000 for
    C, 6000 for D, 7500 for E, and 5000 for EIC ... Each of these lines is
    rounded individually before any summing."

    Design: Corner/calculations/prep_fee_complex_band_all_schedules_correct
    """
    ctx = setup_return_in_docs_pending(
        client_overrides={"full_name": "Cx Cli", "ssn_last4": "4848", "is_returning": False},
        return_overrides={"complexity_band": "COMPLEX", "schedules": ["A", "B", "C", "D"],
                          "state_return_count": 2})
    ret = validate_success(api.transition_return(
        ctx["return"]["id"], {"to": "IN_PREP"}, ctx["prep_headers"]), 200)
    # COMPLEX x1.50: base 22500 + A 6000 + B 3750 + C 13500 + D 9000 + 2*9000 = 72750.
    assert ret["prep_fee_cents"] == 72750, f"expected 72750, got {ret['prep_fee_cents']}"


def test_fee_lines_materialized_with_discount_line(api):
    """PRD §3.4: "Each fee line records the parent tax_return_id, a line_kind of
    BASE_1040, SCHEDULE, STATE_RETURN, or DISCOUNT ... and a signed amount_cents
    (discount lines are negative)."
    PRD §3.4: "it is added as a single negative DISCOUNT line carrying the
    negated discount amount."

    Design: Corner/calculations/fee_lines_materialized_with_discount_line
    """
    ctx = setup_return_in_docs_pending(
        client_overrides={"full_name": "Fl Cli", "ssn_last4": "4949", "is_returning": True},
        return_overrides={"complexity_band": "STANDARD", "schedules": ["EIC"]})
    ret = validate_success(api.transition_return(
        ctx["return"]["id"], {"to": "IN_PREP"}, ctx["prep_headers"]), 200)
    lines, _ = validate_paginated(api.list_fee_lines(ctx["return"]["id"], ctx["prep_headers"]))
    by_kind = {}
    for line in lines:
        by_kind.setdefault(line["line_kind"], []).append(line["amount_cents"])
    # STANDARD x1.20: base 18000, EIC 6000, subtotal 24000, discount 2400 -> -2400.
    assert 18000 in by_kind.get("BASE_1040", []), f"BASE_1040 18000 missing: {by_kind}"
    assert 6000 in by_kind.get("SCHEDULE", []), f"SCHEDULE 6000 missing: {by_kind}"
    assert -2400 in by_kind.get("DISCOUNT", []), f"DISCOUNT -2400 missing: {by_kind}"
    assert ret["prep_fee_cents"] == 21600, f"expected 21600, got {ret['prep_fee_cents']}"


def test_waterfall_shortfall_floors_net_at_zero(api):
    """PRD §3.7: "when the refund falls short the lower-priority buckets are
    partially or not filled, the taxpayer nets zero, and the shortfall is the
    excess of fees over the refund."

    Design: Corner/calculations/waterfall_shortfall_floors_net_at_zero
    """
    # STANDARD [A,C] state=1 → prep 40800; bank fee 3995; total 44795; disburse 40000.
    ctx = setup_return_prepared(
        bank_product_enabled=True,
        client_overrides={"risk_band": "LOW"},
        return_overrides={"complexity_band": "STANDARD", "schedules": ["A", "C"],
                          "state_return_count": 1, "expected_refund_cents": 40000})
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]
    rt = create_refund_transfer(rid)
    rt_v = rt["version"]
    validate_success(api.efile_return(rid, ph), 200)
    validate_success(api.efile_ack_return(rid, {"ack_status": "ACCEPTED"}, ph), 200)
    disbursed = validate_success(api.disburse_refund_transfer(
        rt["id"], {"disbursed_refund_cents": 40000, "expected_refundtransfer_version": rt_v}, BO), 200)
    assert disbursed["net_to_taxpayer_cents"] == 0
    assert disbursed["fee_shortfall_cents"] == 4795, f"expected 4795, got {disbursed['fee_shortfall_cents']}"


def test_advance_deny_sets_approved_zero(api):
    """PRD §3.8: "A denial moves the advance from REQUESTED to DENIED and sets
    approved_cents to zero."

    Design: Corner/calculations/advance_deny_sets_approved_zero
    """
    office = validate_success(api_client.create_office(
        {"name": "Deny Office", "efin": "100021", "state_code": "ME",
         "bank_product_enabled": True}, OM), 201)
    client = create_client(office["id"], full_name="Dn Cli", ssn_last4="5151", risk_band="LOW")
    ret = create_return(office["id"], client["id"], tax_year=2025, expected_refund_cents=500000)
    adv = create_refund_advance(ret["id"], 100000)
    denied = validate_success(api.underwrite_refund_advance(adv["id"], {"decision": "DENY"}, BO), 200)
    assert denied["status"] == "DENIED"
    assert denied["approved_cents"] == 0


# ─── validations ───────────────────────────────────────────────────────────

def test_duplicate_non_amended_return_rejected(api):
    """PRD §3.3: "within one office, no two returns may share the same client_id
    and tax_year unless the new one is an AMENDED_1040X ... A second non-amended
    return for the same office, client, and tax year is rejected with
    ERR_DUPLICATE_RETURN."

    Design: Corner/validations/duplicate_non_amended_return_rejected
    """
    office = create_office()
    client = create_client(office["id"], full_name="Dp Cli", ssn_last4="5252")
    create_return(office["id"], client["id"], tax_year=2025)
    res = api.create_return(
        {"office_id": office["id"], "client_id": client["id"], "tax_year": 2025}, FD)
    validate_error(res, "ERR_DUPLICATE_RETURN", expected_status=409)


def test_preparer_at_capacity_rejects_assignment(api):
    """PRD §3.4: "The assignment is rejected with ERR_PREPARER_AT_CAPACITY when
    it would push the target preparer's assigned_open_returns above that
    preparer's max_open_returns."

    Design: Corner/validations/preparer_at_capacity_rejects_assignment
    """
    office, _, prep, _ = setup_office_with_preparer(
        credential_overrides={"ptin": "P17171717"}, preparer_overrides={"max_open_returns": 1})
    client = create_client(office["id"], full_name="Cp Cli", ssn_last4="5353")
    ret_a = create_return(office["id"], client["id"], tax_year=2025)
    ret_b = create_return(office["id"], client["id"], tax_year=2024, return_kind="PRIOR_YEAR")
    validate_success(api.assign_return(ret_a["id"], {"preparer_id": prep["id"]}, OM), 200)

    res = api.assign_return(ret_b["id"], {"preparer_id": prep["id"]}, OM)
    validate_error(res, "ERR_PREPARER_AT_CAPACITY", expected_status=409)
    prep_after = validate_success(api.get_preparer(prep["id"], OM), 200)
    assert prep_after["assigned_open_returns"] == 1


def test_bank_product_disabled_blocks_refund_transfer(api):
    """PRD §3.7: "Because this is a bank product, the office's
    bank_product_enabled must be true, else ERR_BANK_PRODUCT_DISABLED."

    Design: Corner/validations/bank_product_disabled_blocks_refund_transfer
    """
    office = create_office(bank_product_enabled=False)
    client = create_client(office["id"], full_name="Nb Cli", ssn_last4="5454")
    ret = create_return(office["id"], client["id"], tax_year=2025)
    res = api.create_refund_transfer({"tax_return_id": ret["id"]}, BO)
    validate_error(res, "ERR_BANK_PRODUCT_DISABLED", expected_status=409)


def test_efin_suspended_blocks_efile_from_prepared(api):
    """PRD §3.5: "The office's efin_status must be ACTIVE, else
    ERR_EFIN_SUSPENDED."

    Design: Corner/validations/efin_suspended_blocks_efile_from_prepared
    """
    ctx = setup_return_prepared(return_overrides={"complexity_band": "SIMPLE"})
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]
    validate_success(api.set_efin_status(ctx["office"]["id"], {"efin_status": "SUSPENDED"}, OM), 200)
    res = api.efile_return(rid, ph)
    validate_error(res, "ERR_EFIN_SUSPENDED", expected_status=409)
    after = validate_success(api.get_return(rid, ph), 200)
    assert after["status"] == "PREPARED"


def test_amend_target_not_accepted_blocks_1040x_efile(api):
    """PRD §3.5: "if the return's return_kind is AMENDED_1040X, the return
    referenced by amends_return_id must itself be in EFILED_ACCEPTED, else
    ERR_AMEND_TARGET_NOT_ACCEPTED."

    Design: Corner/validations/amend_target_not_accepted_blocks_1040x_efile
    """
    office, _, prep, ph = setup_office_with_preparer(credential_overrides={"ptin": "P19191919"})
    client = create_client(office["id"], full_name="Ad Cli", ssn_last4="5656")
    # ORIGINAL target left in INTAKE (not accepted).
    orig = create_return(office["id"], client["id"], tax_year=2025, return_kind="ORIGINAL")
    # 1040X PREPARED with ACTIVE credential.
    x = create_return(office["id"], client["id"], headers=ph, tax_year=2025,
                      return_kind="AMENDED_1040X", complexity_band="SIMPLE",
                      amends_return_id=orig["id"])
    doc = add_document(x["id"], ph, doc_type="PRIOR_RETURN", is_required=True)
    set_document_received(doc["id"], ph)
    validate_success(api.assign_return(x["id"], {"preparer_id": prep["id"]}, ph), 200)
    validate_success(api.transition_return(x["id"], {"to": "DOCS_PENDING"}, ph), 200)
    validate_success(api.transition_return(x["id"], {"to": "IN_PREP"}, ph), 200)
    validate_success(api.transition_return(x["id"], {"to": "PREPARED"}, ph), 200)

    res = api.efile_return(x["id"], ph)
    validate_error(res, "ERR_AMEND_TARGET_NOT_ACCEPTED", expected_status=409)
    after = validate_success(api.get_return(x["id"], ph), 200)
    assert after["status"] == "PREPARED"
