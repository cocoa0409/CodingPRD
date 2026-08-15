"""Husbandry waiver gate, repatriation cascade, and cost-dispute lifecycle."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, create_principal, create_port_call, create_da_for_call,
    add_manual_line, create_crew_change, create_husbandry_case,
    drive_call_to_alongside, send_da_and_fund, sail_call,
    make_agency_ops_headers, make_agency_admin_headers, make_agency_finance_headers,
    make_port_authority_headers, make_principal_rep_headers,
    make_crewing_agent_headers, make_husbandry_officer_headers,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue B: endpoints / sailing_with_waived_critical_case_succeeds
# ---------------------------------------------------------------------------

def test_sailing_with_waived_critical_case_succeeds(api):
    """PRD §3.3: "No husbandry case of this call with `severity` `CRITICAL`
    may sit in `OPEN` or `IN_TREATMENT` without its `departure_waiver_granted`
    flag set (`ERR_OPEN_CRITICAL_HUSBANDRY`)."
    PRD §3.6: "an `AgencyAdmin` holds the escape hatch: granting the one-case
    departure waiver sets `departure_waiver_granted` true, letting
    record-sailing pass despite that case."

    Design: Corner/endpoints/sailing_with_waived_critical_case_succeeds
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-10T20:00:00Z",
                          etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 1000, description="stores")
    pc, bw = drive_call_to_alongside(pc, berth_code="B19")
    send_da_and_fund(da["id"], 820)
    hc = create_husbandry_case(pc["id"], case_type="MEDICAL", severity="CRITICAL",
                               summary="cardiac observation")
    resp = api_client.record_sailing(pc["id"], {"berth_window_id": bw["id"]},
                                     make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_OPEN_CRITICAL_HUSBANDRY)
    get_success_data(api_client.waive_departure_hold(hc["id"], make_agency_admin_headers()))
    pc = validate_success(api_client.record_sailing(
        pc["id"], {"berth_window_id": bw["id"]}, make_agency_ops_headers()))
    assert pc["ops_status"] == "SAILED"
    hc_now = validate_success(api_client.get_husbandry_case(hc["id"], make_husbandry_officer_headers()))
    assert hc_now["departure_waiver_granted"] is True
    assert hc_now["status"] == "OPEN", "waiver does not close the case"


# ---------------------------------------------------------------------------
# Queue B: endpoints / repatriation_cascades_to_crew_change
# ---------------------------------------------------------------------------

def test_repatriation_cascades_to_crew_change(api):
    """PRD §3.6: "Repatriation from `OPEN` or `IN_TREATMENT` requires a
    linked crew change ... and cascades: the linked movement moves to
    `REPATRIATED` from `DOCS_VERIFIED`, `VISA_GRANTED`, or
    `SHORE_PASS_ISSUED`."

    Design: Corner/endpoints/repatriation_cascades_to_crew_change
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    cc = create_crew_change(pc["id"], direction="OFF_SIGNER", requires_visa=False)
    cc = get_success_data(api_client.verify_docs(cc["id"], make_crewing_agent_headers()))
    assert cc["status"] == "DOCS_VERIFIED"
    hc = create_husbandry_case(pc["id"], case_type="REPATRIATION", severity="URGENT",
                               summary="family emergency", crew_change_id=cc["id"])
    hc = validate_success(api_client.repatriate_husbandry_case(
        hc["id"], make_husbandry_officer_headers()))
    assert hc["status"] == "REPATRIATED"
    cc_now = validate_success(api_client.get_crew_change(cc["id"], make_crewing_agent_headers()))
    assert cc_now["status"] == "REPATRIATED", "cascaded in the same request"


# ---------------------------------------------------------------------------
# Queue B: endpoints / da_dispute_uphold_credit_and_refinalize
# ---------------------------------------------------------------------------

def _setup_final_da_with_line_10000():
    """Call SAILED; DA FINAL with one SUNDRY line 10000 (total_final 10250);
    advance 8200 fully applied. Returns dict of artifacts."""
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], eta="2026-06-10T20:00:00Z",
                          etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc)
    ln = add_manual_line(da["id"], 10000, description="stores")
    pc, bw = drive_call_to_alongside(pc, berth_code="B20")
    get_success_data(api_client.send_disbursement_account(da["id"], make_agency_ops_headers()))
    adv = get_success_data(api_client.create_funding_advance(
        da["id"], {"amount_cents": 8200}, make_agency_finance_headers()))
    pc = sail_call(pc, bw)
    da = validate_success(api_client.finalize_disbursement_account(
        da["id"], make_agency_finance_headers("fin-1")))
    get_success_data(api_client.apply_funding_advance(
        adv["id"], {"amount_cents": 8200}, make_agency_finance_headers()))
    return {"pc": pc, "da": da, "ln": ln, "adv": adv, "principal": principal}


def test_da_dispute_uphold_credit_and_refinalize(api):
    """PRD §3.9: "when the dispute references a line, that line's
    `actual_cents` is reduced by the disputed amount but never below zero and
    the line returns to `ACTUALIZED`"; "An `AgencyFinance` controller
    refinalizes an account in `DISPUTED`, returning it to `FINAL` ... with
    any upheld credits already applied to the lines"; "`balance_due_cents` as
    `total_final_cents` minus `advances_applied_cents`."

    Design: Corner/endpoints/da_dispute_uphold_credit_and_refinalize
    """
    s = _setup_final_da_with_line_10000()
    cd = get_success_data(api_client.create_cost_dispute(
        {"da_id": s["da"]["id"], "da_line_id": s["ln"]["id"],
         "amount_cents": 3000, "reason": "double billed stores"},
        make_principal_rep_headers(s["principal"]["id"])))
    get_success_data(api_client.start_review_cost_dispute(cd["id"], make_agency_finance_headers()))
    cd = validate_success(api_client.uphold_cost_dispute(
        cd["id"], {"resolution_note": "credit approved"}, make_agency_finance_headers()))
    assert cd["status"] == "UPHELD"
    lines, _ = validate_paginated(api_client.list_da_lines(s["da"]["id"], make_agency_ops_headers()))
    ln = [l for l in lines if l["id"] == s["ln"]["id"]][0]
    assert ln["actual_cents"] == 7000, "10000 - 3000 credit"
    assert ln["status"] == "ACTUALIZED"
    da = validate_success(api_client.refinalize_disbursement_account(
        s["da"]["id"], make_agency_finance_headers("fin-1")))
    assert da["status"] == "FINAL"
    assert da["total_final_cents"] == 7175, f"7000 + fee 175; got {da['total_final_cents']}"
    assert da["balance_due_cents"] == -1025, f"7175 - 8200; got {da['balance_due_cents']}"


# ---------------------------------------------------------------------------
# Queue B: endpoints / dispute_escalation_resolve_reject
# ---------------------------------------------------------------------------

def test_dispute_escalation_resolve_reject(api):
    """PRD §3.9: "the owning `PrincipalRep` may escalate it (`REJECTED` →
    `ESCALATED`), with ownership enforced as `ERR_NOT_RESOURCE_OWNER`.
    Escalated disputes land with an `AgencyAdmin`, whose resolution carries a
    `decision` and a `resolution_note`: an `ACCEPT` decision resolves the
    dispute as `RESOLVED_ACCEPTED` and applies the same credit mechanics as
    an uphold, while a `REJECT` decision resolves it as `RESOLVED_REJECTED`
    with any linked line returned to `ACTUALIZED` unchanged."

    Design: Corner/endpoints/dispute_escalation_resolve_reject
    """
    s = _setup_final_da_with_line_10000()
    cd = get_success_data(api_client.create_cost_dispute(
        {"da_id": s["da"]["id"], "amount_cents": 1000,
         "reason": "agency fee too high"},
        make_principal_rep_headers(s["principal"]["id"])))
    get_success_data(api_client.start_review_cost_dispute(cd["id"], make_agency_finance_headers()))
    cd = validate_success(api_client.reject_cost_dispute(
        cd["id"], {"resolution_note": "within contract"}, make_agency_finance_headers()))
    assert cd["status"] == "REJECTED"
    cd = validate_success(api_client.escalate_cost_dispute(
        cd["id"], make_principal_rep_headers(s["principal"]["id"])))
    assert cd["status"] == "ESCALATED"
    cd = validate_success(api_client.resolve_cost_dispute(
        cd["id"], {"decision": "REJECT", "resolution_note": "final: rejected"},
        make_agency_admin_headers()))
    assert cd["status"] == "RESOLVED_REJECTED"
    lines, _ = validate_paginated(api_client.list_da_lines(s["da"]["id"], make_agency_ops_headers()))
    assert len(lines) == 1, "no credit line appended on rejection"
    assert lines[0]["actual_cents"] == 10000
    da = validate_success(api_client.refinalize_disbursement_account(
        s["da"]["id"], make_agency_finance_headers("fin-1")))
    assert da["status"] == "FINAL"
    assert da["total_final_cents"] == 10250
