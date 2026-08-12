"""Validation rules: priority ordering, fiscal gates, referential rules,
temporal rules, uniqueness, and cross-entity sailing gates."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    set_clock, create_principal, create_port_call, create_da_for_call,
    add_manual_line, create_vendor, create_purchase_order, create_crew_change,
    create_husbandry_case, create_cargo_document, create_berth_window,
    create_notification, drive_call_to_alongside, send_da_and_fund,
    make_agency_ops_headers, make_agency_admin_headers, make_agency_finance_headers,
    make_port_authority_headers, make_crewing_agent_headers,
    make_husbandry_officer_headers,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue B: validations / not_found_beats_state
# ---------------------------------------------------------------------------

def test_not_found_beats_state(api):
    """PRD §2.7: "3. **Path existence** — every identifier in the URL path is
    resolved left to right; the first identifier that does not resolve to an
    existing resource yields `ERR_NOT_FOUND` (HTTP 404)." — this stage
    precedes state-machine legality at stage 6.

    Design: Corner/validations/not_found_beats_state
    """
    resp = api_client.confirm_berth_window(NON_EXISTENT_UUID, make_port_authority_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ---------------------------------------------------------------------------
# Queue B: validations / credit_limit_gate_blocks_new_call
# ---------------------------------------------------------------------------

def test_credit_limit_gate_blocks_new_call(api):
    """PRD §3.1: "The principal's forward-looking exposure must remain
    strictly below `credit_limit_cents` — a principal already at or beyond
    its ceiling is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`, and an
    unlimited (zero) ceiling always passes."

    Design: Corner/validations/credit_limit_gate_blocks_new_call
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=10000)
    pc = create_port_call(principal["id"])
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 20000, description="big")  # forward exposure 20500
    resp = api_client.create_port_call(
        {"principal_id": principal["id"], "vessel_name": "SS Owl",
         "imo_number": "9000021", "vessel_gt": 4000, "flag_state": "PA",
         "port_code": "NODUE", "eta": "2026-06-05T10:00:00Z",
         "etd": "2026-06-06T10:00:00Z", "cargo_description": "g"},
        make_agency_ops_headers("ops-1"))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


# ---------------------------------------------------------------------------
# Queue B: validations / send_po_with_suspended_vendor_rejected
# ---------------------------------------------------------------------------

def test_send_po_with_suspended_vendor_rejected(api):
    """PRD §3.4: "suspension never force-cancels purchase orders already in
    flight, but it blocks new purchase-order creation, sending, and
    acknowledgment ... each rejected with `ERR_VENDOR_SUSPENDED`."

    Design: Corner/validations/send_po_with_suspended_vendor_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    vendor = create_vendor(name="ChandlerCo", categories=["PROVISIONS"],
                           contact_email="c@x.example")
    po = create_purchase_order(pc["id"], vendor["id"], estimated_cents=5000)
    get_success_data(api_client.suspend_vendor(vendor["id"], make_agency_admin_headers()))
    resp = api_client.send_purchase_order(po["id"], make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_VENDOR_SUSPENDED)
    po_now = validate_success(api_client.get_purchase_order(po["id"], make_agency_ops_headers()))
    assert po_now["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue B: validations / po_vendor_category_mismatch_rejected
# ---------------------------------------------------------------------------

def test_po_vendor_category_mismatch_rejected(api):
    """PRD §3.4: "The chosen `category` must appear in the vendor's
    `categories`, failing which the creation is rejected with
    `ERR_VENDOR_CATEGORY_MISMATCH`."

    Design: Corner/validations/po_vendor_category_mismatch_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    vendor = create_vendor(name="StoreCo", categories=["STORES"], contact_email="s@x.example")
    resp = api_client.create_purchase_order(
        {"port_call_id": pc["id"], "vendor_id": vendor["id"],
         "category": "BUNKERS", "estimated_cents": 5000,
         "needed_by": "2026-06-01T09:00:00Z"},
        make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_VENDOR_CATEGORY_MISMATCH)


# ---------------------------------------------------------------------------
# Queue B: validations / service_order_vendor_kind_rules
# ---------------------------------------------------------------------------

def test_service_order_vendor_kind_rules(api):
    """PRD §3.5: "a `vendor_id` is required for `TUG`, `LINEBOAT`, and
    `LAUNCH` orders and must be omitted for `PILOT` orders, because pilots
    are port-authority resources; a violation is rejected with
    `ERR_VENDOR_KIND_MISMATCH`."

    Design: Corner/validations/service_order_vendor_kind_rules
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    vendor = create_vendor(name="TugCo", categories=["STORES"], contact_email="t@x.example")
    resp1 = api_client.create_service_order(
        {"port_call_id": pc["id"], "kind": "PILOT", "vendor_id": vendor["id"],
         "resource_unit": "PILOT-BOAT-1", "window_start": "2026-06-01T12:00:00Z",
         "window_end": "2026-06-01T13:00:00Z", "estimated_cents": 8000},
        make_agency_ops_headers())
    validate_error(resp1, ApiErrorId.ERR_VENDOR_KIND_MISMATCH)
    resp2 = api_client.create_service_order(
        {"port_call_id": pc["id"], "kind": "TUG",
         "resource_unit": "TUG-5", "window_start": "2026-06-01T12:00:00Z",
         "window_end": "2026-06-01T13:00:00Z", "estimated_cents": 8000},
        make_agency_ops_headers())
    validate_error(resp2, ApiErrorId.ERR_VENDOR_KIND_MISMATCH)


# ---------------------------------------------------------------------------
# Queue B: validations / pre_arrival_deadline_missed
# ---------------------------------------------------------------------------

def test_pre_arrival_deadline_missed(api):
    """PRD §3.2: "the logical clock must read no later than twenty-four hours
    before the call's `eta` — filing after that deadline fails with
    `ERR_PRE_ARRIVAL_DEADLINE_MISSED`."

    Design: Corner/validations/pre_arrival_deadline_missed
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-10T20:00:00Z",
                          etd="2026-06-13T01:00:00Z")
    for auth_type in ("PORT_STATE_CONTROL", "IMMIGRATION", "CUSTOMS", "HARBOR_MASTER"):
        n = create_notification(pc["id"], auth_type, payload_summary=auth_type[0].lower())
        get_success_data(api_client.submit_notification(n["id"], make_agency_ops_headers()))
    # deadline = eta - 24h = 2026-06-09T20:00:00Z; one second past it
    set_clock("2026-06-09T20:00:01Z")
    resp = api_client.file_pre_arrival(pc["id"], make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_PRE_ARRIVAL_DEADLINE_MISSED)
    pc_now = validate_success(api_client.get_port_call(pc["id"], make_agency_ops_headers()))
    assert pc_now["ops_status"] == "NOMINATED"


# ---------------------------------------------------------------------------
# Queue B: validations / passport_expiry_not_after_etd_rejected
# ---------------------------------------------------------------------------

def test_passport_expiry_not_after_etd_rejected(api):
    """PRD §3.6: "the `passport_expiry` must be strictly later than the
    parent call's `etd`, failing which verification is rejected with
    `ERR_PASSPORT_EXPIRY_INVALID`."

    Design: Corner/validations/passport_expiry_not_after_etd_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-01T10:00:00Z",
                          etd="2026-06-02T10:00:00Z")
    cc = create_crew_change(pc["id"], passport_expiry="2026-06-02T10:00:00Z")
    resp = api_client.verify_docs(cc["id"], make_crewing_agent_headers())
    validate_error(resp, ApiErrorId.ERR_PASSPORT_EXPIRY_INVALID)
    cc_now = validate_success(api_client.get_crew_change(cc["id"], make_crewing_agent_headers()))
    assert cc_now["status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# Queue B: validations / sailing_with_open_crew_change_rejected
# ---------------------------------------------------------------------------

def test_sailing_with_open_crew_change_rejected(api):
    """PRD §3.3: "No crew change of this call may remain in `REQUESTED`,
    `DOCS_VERIFIED`, `VISA_PENDING`, `VISA_GRANTED`, or `PASS_EXPIRED` — a
    movement in `SHORE_PASS_ISSUED` does not block departure
    (`ERR_OPEN_CREW_CHANGES`)."

    Design: Corner/validations/sailing_with_open_crew_change_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-10T20:00:00Z",
                          etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 1000, description="stores")
    pc, bw = drive_call_to_alongside(pc, berth_code="B12")
    send_da_and_fund(da["id"], 820)
    cc = create_crew_change(pc["id"], full_name="J. Cook", nationality="PH",
                            passport_no="P1", requires_visa=False)
    resp = api_client.record_sailing(pc["id"], {"berth_window_id": bw["id"]},
                                     make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_OPEN_CREW_CHANGES)
    pc_now = validate_success(api_client.get_port_call(pc["id"], make_agency_ops_headers()))
    assert pc_now["ops_status"] == "ALONGSIDE"
    cc_now = validate_success(api_client.get_crew_change(cc["id"], make_crewing_agent_headers()))
    assert cc_now["status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# Queue B: validations / sailing_with_doc_on_hold_rejected
# ---------------------------------------------------------------------------

def test_sailing_with_doc_on_hold_rejected(api):
    """PRD §3.3: "No cargo document of this call may be `ON_HOLD`
    (`ERR_CARGO_DOCS_ON_HOLD`)."
    PRD §3.7: "A verified document may be placed `ON_HOLD` and the hold later
    released, cycling back to `VERIFIED`."

    Design: Corner/validations/sailing_with_doc_on_hold_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-10T20:00:00Z",
                          etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 1000, description="stores")
    pc, bw = drive_call_to_alongside(pc, berth_code="B13")
    send_da_and_fund(da["id"], 820)
    doc = create_cargo_document(pc["id"], bl_number="BL-1", freight_paid=True)
    get_success_data(api_client.verify_cargo_document(doc["id"], make_agency_ops_headers()))
    get_success_data(api_client.hold_cargo_document(doc["id"], make_agency_ops_headers()))
    resp = api_client.record_sailing(pc["id"], {"berth_window_id": bw["id"]},
                                     make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_CARGO_DOCS_ON_HOLD)
    pc_now = validate_success(api_client.get_port_call(pc["id"], make_agency_ops_headers()))
    assert pc_now["ops_status"] == "ALONGSIDE"
    get_success_data(api_client.release_hold_cargo_document(doc["id"], make_agency_ops_headers()))
    doc = get_success_data(api_client.release_cargo_document(doc["id"], make_agency_ops_headers()))
    assert doc["status"] == "RELEASED"
    pc = validate_success(api_client.record_sailing(
        pc["id"], {"berth_window_id": bw["id"]}, make_agency_ops_headers()))
    assert pc["ops_status"] == "SAILED"


# ---------------------------------------------------------------------------
# Queue B: validations / bl_release_gates
# ---------------------------------------------------------------------------

def test_bl_release_gates(api):
    """PRD §3.7: "Release is the terminal act, moving a `VERIFIED` document
    to `RELEASED`, and it carries two gates: the parent call must be
    `ALONGSIDE` — an early release is rejected with
    `ERR_BL_RELEASE_TOO_EARLY` — and a `BILL_OF_LADING` may only be released
    when `freight_paid` is true, failing which the release is rejected with
    `ERR_FREIGHT_NOT_PAID`."

    Design: Corner/validations/bl_release_gates
    """
    from test_helpers import drive_call_to_cleared
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-10T20:00:00Z",
                          etd="2026-06-13T01:00:00Z")
    pc, _ = drive_call_to_cleared(pc)
    doc_paid = create_cargo_document(pc["id"], bl_number="BL-PAID", freight_paid=True)
    doc_unpaid = create_cargo_document(pc["id"], bl_number="BL-UNPAID",
                                       consignee_name="DebtorCo", freight_paid=False)
    get_success_data(api_client.verify_cargo_document(doc_paid["id"], make_agency_ops_headers()))
    get_success_data(api_client.verify_cargo_document(doc_unpaid["id"], make_agency_ops_headers()))
    bw = create_berth_window(pc["id"], berth_code="B14",
                             start_at="2026-06-10T18:00:00Z", end_at="2026-06-14T06:00:00Z")
    get_success_data(api_client.confirm_berth_window(bw["id"], make_port_authority_headers()))
    # Early release while CLEARED_TO_ENTER
    resp = api_client.release_cargo_document(doc_paid["id"], make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_BL_RELEASE_TOO_EARLY)
    # Drive to ALONGSIDE
    set_clock("2026-06-10T21:00:00Z")
    get_success_data(api_client.occupy_berth_window(bw["id"], make_agency_ops_headers()))
    pc = get_success_data(api_client.record_arrival(
        pc["id"], {"berth_window_id": bw["id"]}, make_agency_ops_headers()))
    assert pc["ops_status"] == "ALONGSIDE"
    # Unpaid B/L now hits the freight gate
    resp = api_client.release_cargo_document(doc_unpaid["id"], make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_FREIGHT_NOT_PAID)
    # Paid B/L releases cleanly
    doc_paid = validate_success(api_client.release_cargo_document(
        doc_paid["id"], make_agency_ops_headers()))
    assert doc_paid["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Queue B: validations / advance_on_proforma_da_rejected
# ---------------------------------------------------------------------------

def test_advance_on_proforma_da_rejected(api):
    """PRD §3.8: "records an advance with a strictly positive `amount_cents`,
    but only while the account is in `SENT_TO_PRINCIPAL`, `FUNDED`, `FINAL`,
    or `DISPUTED`; against any other account status the creation fails with
    `ERR_INVALID_STATE`."

    Design: Corner/validations/advance_on_proforma_da_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 1000)
    resp = api_client.create_funding_advance(
        da["id"], {"amount_cents": 5000}, make_agency_finance_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    advances, meta = validate_paginated(api_client.list_funding_advances(
        make_agency_finance_headers(), params={"da_id": da["id"]}))
    assert len(advances) == 0, "no FundingAdvance created"


# ---------------------------------------------------------------------------
# Queue B: validations / finalize_before_sailing_rejected
# ---------------------------------------------------------------------------

def test_finalize_before_sailing_rejected(api):
    """PRD §3.9: "the parent call must be in `SAILED` — finalizing earlier is
    rejected with `ERR_PORT_CALL_NOT_SAILED`."

    Design: Corner/validations/finalize_before_sailing_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    da = create_da_for_call(pc)
    get_success_data(api_client.send_disbursement_account(da["id"], make_agency_ops_headers()))
    resp = api_client.finalize_disbursement_account(da["id"], make_agency_finance_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_PORT_CALL_NOT_SAILED)
    da_now = validate_success(api_client.get_disbursement_account(da["id"], make_agency_ops_headers()))
    assert da_now["status"] == "SENT_TO_PRINCIPAL"


# ---------------------------------------------------------------------------
# Queue B: validations / da_finalize_same_user_segregation_rejected
# ---------------------------------------------------------------------------

def test_da_finalize_same_user_segregation_rejected(api):
    """PRD §3.9: "segregation of duties forbids the account's creator from
    finalizing it, so the acting `X-User-ID` must differ from the account's
    `created_by_user_id`, failing which the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`"; "`total_final_cents` as the sum of every
    line's `actual_cents` plus `agency_fee_final_cents` ... and the actor is
    recorded as `finalized_by_user_id`."

    Design: Corner/validations/da_finalize_same_user_segregation_rejected
    """
    from test_helpers import sail_call
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-10T20:00:00Z",
                          etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc, ops_user_id="ops-1")
    add_manual_line(da["id"], 1000, description="stores")
    pc, bw = drive_call_to_alongside(pc, berth_code="B15")
    send_da_and_fund(da["id"], 820)
    sail_call(pc, bw)
    # Finalize as the creator (ops-1) -> segregation violation
    resp = api_client.finalize_disbursement_account(da["id"], make_agency_finance_headers("ops-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    da_now = validate_success(api_client.get_disbursement_account(da["id"], make_agency_ops_headers()))
    # Funded at exactly advance_required (820 == 820): the account auto-toggled to
    # FUNDED per §3.8 ("reaches advance_required_cents ... moves to FUNDED on its
    # own"), and the rejected finalize leaves it there.
    assert da_now["status"] == "FUNDED"
    # A different finance user succeeds
    da = validate_success(api_client.finalize_disbursement_account(
        da["id"], make_agency_finance_headers("fin-1")))
    assert da["status"] == "FINAL"
    assert da["finalized_by_user_id"] == "fin-1"
    assert da["total_final_cents"] == 1025, "1000 + fee 25"


# ---------------------------------------------------------------------------
# Queue B: validations / full_settlement_flow_gates
# ---------------------------------------------------------------------------

def test_full_settlement_flow_gates(api):
    """PRD §3.9: "no advance of the account may still be `RECEIVED` holding
    an unapplied, unrefunded remainder — such an advance must first be
    applied or refunded, failing which settlement is rejected with
    `ERR_UNREFUNDED_ADVANCES` — and `balance_due_cents` must be exactly zero,
    meaning the applied advances equal the final total; a nonzero balance, in
    either direction, is rejected with `ERR_BALANCE_NOT_ZERO`, because exact
    equality, not mere sufficiency, is required."
    PRD §3.3: "an `AgencyFinance` controller closes a `SAILED` call ... only
    when the call's non-`SUPERSEDED` disbursement account has reached
    `SETTLED`; an unsettled account fails with `ERR_DA_NOT_SETTLED`."

    Design: Corner/validations/full_settlement_flow_gates
    """
    from test_helpers import sail_call
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-10T20:00:00Z",
                          etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 10000, description="stores")
    pc, bw = drive_call_to_alongside(pc, berth_code="B16")
    get_success_data(api_client.send_disbursement_account(da["id"], make_agency_ops_headers()))
    adv1 = get_success_data(api_client.create_funding_advance(
        da["id"], {"amount_cents": 8200}, make_agency_finance_headers()))
    pc = sail_call(pc, bw)
    da = validate_success(api_client.finalize_disbursement_account(
        da["id"], make_agency_finance_headers("fin-1")))
    assert da["total_final_cents"] == 10250
    # Close before settlement
    resp = api_client.close_port_call(pc["id"], make_agency_finance_headers())
    validate_error(resp, ApiErrorId.ERR_DA_NOT_SETTLED)
    # Settle with unapplied remainder
    resp = api_client.settle_disbursement_account(da["id"], make_agency_finance_headers())
    validate_error(resp, ApiErrorId.ERR_UNREFUNDED_ADVANCES)
    # Apply 8200; balance 2050 remains
    get_success_data(api_client.apply_funding_advance(
        adv1["id"], {"amount_cents": 8200}, make_agency_finance_headers()))
    resp = api_client.settle_disbursement_account(da["id"], make_agency_finance_headers())
    validate_error(resp, ApiErrorId.ERR_BALANCE_NOT_ZERO)
    # Top up 2050 and apply it: balance hits exactly zero
    adv2 = get_success_data(api_client.create_funding_advance(
        da["id"], {"amount_cents": 2050}, make_agency_finance_headers()))
    get_success_data(api_client.apply_funding_advance(
        adv2["id"], {"amount_cents": 2050}, make_agency_finance_headers()))
    da = validate_success(api_client.settle_disbursement_account(da["id"], make_agency_finance_headers()))
    assert da["status"] == "SETTLED"
    assert da["balance_due_cents"] == 0
    adv1_now = validate_success(api_client.get_funding_advance(adv1["id"], make_agency_finance_headers()))
    adv2_now = validate_success(api_client.get_funding_advance(adv2["id"], make_agency_finance_headers()))
    assert adv1_now["status"] == "APPLIED" and adv2_now["status"] == "APPLIED"
    pc = validate_success(api_client.close_port_call(pc["id"], make_agency_finance_headers()))
    assert pc["ops_status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Queue B: validations / apply_exceeds_remaining_rejected
# ---------------------------------------------------------------------------

def test_apply_exceeds_remaining_rejected(api):
    """PRD §3.8: "the amount must be positive and no greater than the
    advance's remaining unapplied, unrefunded balance
    (`ERR_APPLY_EXCEEDS_REMAINING`). The amount is added to `applied_cents`;
    when the applied portion reaches the full `amount_cents` the advance
    becomes `APPLIED`."

    Design: Corner/validations/apply_exceeds_remaining_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 1000, description="s")
    get_success_data(api_client.send_disbursement_account(da["id"], make_agency_ops_headers()))
    adv = get_success_data(api_client.create_funding_advance(
        da["id"], {"amount_cents": 820}, make_agency_finance_headers()))
    resp = api_client.apply_funding_advance(
        adv["id"], {"amount_cents": 821}, make_agency_finance_headers())
    validate_error(resp, ApiErrorId.ERR_APPLY_EXCEEDS_REMAINING)
    adv = validate_success(api_client.apply_funding_advance(
        adv["id"], {"amount_cents": 820}, make_agency_finance_headers()))
    assert adv["status"] == "APPLIED"
    assert adv["applied_cents"] == 820


# ---------------------------------------------------------------------------
# Queue B: validations / duplicate_notification_type_rejected
# ---------------------------------------------------------------------------

def test_duplicate_notification_type_rejected(api):
    """PRD §3.2: "Each authority type may exist at most once per port call
    among notifications that are not `WITHDRAWN`; a duplicate type is
    rejected with `ERR_DUPLICATE_NOTIFICATION_TYPE`."

    Design: Corner/validations/duplicate_notification_type_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    create_notification(pc["id"], "CUSTOMS", payload_summary="first")
    resp = api_client.create_authority_notification(
        {"port_call_id": pc["id"], "authority_type": "CUSTOMS", "payload_summary": "second"},
        make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_NOTIFICATION_TYPE)


# ---------------------------------------------------------------------------
# Queue B: validations / duplicate_bl_number_rejected
# ---------------------------------------------------------------------------

def test_duplicate_bl_number_rejected(api):
    """PRD §3.7: "The `bl_number` is unique per port call among documents
    that have not reached a terminal state; a duplicate registration is
    rejected with `ERR_DUPLICATE_BL_NUMBER`."

    Design: Corner/validations/duplicate_bl_number_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc1 = create_port_call(principal["id"])
    pc2 = create_port_call(principal["id"], vessel_name="SS Owl", imo_number="9000021",
                           vessel_gt=4000, eta="2026-06-05T10:00:00Z",
                           etd="2026-06-06T10:00:00Z")
    create_cargo_document(pc1["id"], bl_number="BL-77", freight_paid=True)
    resp = api_client.create_cargo_document(
        {"port_call_id": pc1["id"], "doc_type": "BILL_OF_LADING",
         "bl_number": "BL-77", "consignee_name": "OtherCo", "freight_paid": True},
        make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BL_NUMBER)
    resp2 = api_client.create_cargo_document(
        {"port_call_id": pc2["id"], "doc_type": "BILL_OF_LADING",
         "bl_number": "BL-77", "consignee_name": "OtherCo", "freight_paid": True},
        make_agency_ops_headers())
    data = validate_success(resp2, expected_status=201)
    assert data["bl_number"] == "BL-77", "scope is per call"


# ---------------------------------------------------------------------------
# Queue B: validations / repatriate_without_crew_link_rejected
# ---------------------------------------------------------------------------

def test_repatriate_without_crew_link_rejected(api):
    """PRD §3.6: "Repatriation from `OPEN` or `IN_TREATMENT` requires a
    linked crew change — a case without one is rejected with
    `ERR_NO_LINKED_CREW_CHANGE`."

    Design: Corner/validations/repatriate_without_crew_link_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    hc = create_husbandry_case(pc["id"], case_type="MEDICAL", severity="URGENT",
                               summary="sprained ankle")
    resp = api_client.repatriate_husbandry_case(hc["id"], make_husbandry_officer_headers())
    validate_error(resp, ApiErrorId.ERR_NO_LINKED_CREW_CHANGE)
    hc_now = validate_success(api_client.get_husbandry_case(hc["id"], make_husbandry_officer_headers()))
    assert hc_now["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Queue B: validations / principal_suspended_call_rejected
# ---------------------------------------------------------------------------

def test_principal_suspended_call_rejected(api):
    """PRD §3.1: "A suspended principal cannot open new business: port-call
    creation for a principal that is not `ACTIVE` is rejected with
    `ERR_PRINCIPAL_SUSPENDED`."

    Design: Corner/validations/principal_suspended_call_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    get_success_data(api_client.suspend_principal(principal["id"], make_agency_admin_headers()))
    resp = api_client.create_port_call(
        {"principal_id": principal["id"], "vessel_name": "SS Rye",
         "imo_number": "9000020", "vessel_gt": 5000, "flag_state": "PA",
         "port_code": "NODUE", "eta": "2026-06-01T10:00:00Z",
         "etd": "2026-06-02T10:00:00Z", "cargo_description": "g"},
        make_agency_ops_headers("ops-1"))
    validate_error(resp, ApiErrorId.ERR_PRINCIPAL_SUSPENDED)


# ---------------------------------------------------------------------------
# Queue B: validations / dispute_on_proforma_da_rejected
# ---------------------------------------------------------------------------

def test_dispute_on_proforma_da_rejected(api):
    """PRD §3.9: "The account must be in `FINAL` or `DISPUTED` — raising
    against any other status fails with `ERR_INVALID_STATE`."

    Design: Corner/validations/dispute_on_proforma_da_rejected
    """
    from test_helpers import make_principal_rep_headers
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    da = create_da_for_call(pc)
    resp = api_client.create_cost_dispute(
        {"da_id": da["id"], "amount_cents": 100, "reason": "too early"},
        make_principal_rep_headers(principal["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Queue B: validations / occupy_before_window_start_rejected
# ---------------------------------------------------------------------------

def test_occupy_before_window_start_rejected(api):
    """PRD §3.3: "An `AgencyOps` agent marks a `CONFIRMED` window occupied
    once the logical clock has reached its `start_at` — an early attempt
    fails with `ERR_WINDOW_NOT_STARTED`."
    PRD §2.7: temporal rules (stage 8) precede business constraints (stage 9),
    so the temporal error surfaces even when the HARBOR_MASTER
    acknowledgement gate would also fail.

    Design: Corner/validations/occupy_before_window_start_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-02T08:00:00Z",
                          etd="2026-06-03T08:00:00Z")
    bw = create_berth_window(pc["id"], berth_code="B17",
                             start_at="2026-06-02T10:00:00Z", end_at="2026-06-02T20:00:00Z")
    get_success_data(api_client.confirm_berth_window(bw["id"], make_port_authority_headers()))
    # clock still at the 2026-05-01 default; HM never acknowledged either
    resp = api_client.occupy_berth_window(bw["id"], make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_STARTED)


# ---------------------------------------------------------------------------
# Queue B: validations / window_start_not_before_end_rejected
# ---------------------------------------------------------------------------

def test_window_start_not_before_end_rejected(api):
    """PRD §3.3: "the start must be strictly earlier than the end, and an
    inverted window is rejected with `ERR_WINDOW_INVALID`."
    PRD §3.5: "the requested `window_start` and `window_end` with the start
    strictly earlier than the end (`ERR_WINDOW_INVALID`)."

    Design: Corner/validations/window_start_not_before_end_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    vendor = create_vendor(name="TugCo", categories=["STORES"], contact_email="t@x.example")
    resp1 = api_client.create_berth_window(
        {"port_call_id": pc["id"], "berth_code": "B18",
         "start_at": "2026-06-01T12:00:00Z", "end_at": "2026-06-01T12:00:00Z"},
        make_agency_ops_headers())
    validate_error(resp1, ApiErrorId.ERR_WINDOW_INVALID)
    resp2 = api_client.create_service_order(
        {"port_call_id": pc["id"], "kind": "TUG", "vendor_id": vendor["id"],
         "resource_unit": "TUG-2", "window_start": "2026-06-01T12:00:00Z",
         "window_end": "2026-06-01T12:00:00Z", "estimated_cents": 5000},
        make_agency_ops_headers())
    validate_error(resp2, ApiErrorId.ERR_WINDOW_INVALID)
