"""Queue B — rbac section corner tests."""
from test_helpers import (
    api_client, validate_error, get_success_data,
    create_active_program, create_program, create_charter_payload,
    create_contract, create_closeout_item, submit_closeout_item,
    verify_closeout_item, create_owner_report, submit_owner_report,
    accept_owner_report,
    create_and_execute_contract, create_change_order, submit_change_order,
    recommend_change_order,
    pm_headers, exec_headers, owner_headers,
    make_pm_headers, make_exec_headers, make_owner_headers,
    ApiErrorId,
)


def test_owner_cannot_create_contract_unauthorized(api):
    """PRD §4 endpoint table: POST /contracts authorized role is OwnerRepPM
    only. PRD §2.5 priority 2: "The role must be authorized for the endpoint
    per the access matrix; failures surface ERR_UNAUTHORIZED_ROLE (403)."

    Design: Corner/rbac/owner_cannot_create_contract_unauthorized
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-R1",
    )
    pid = prog["id"]
    resp = api_client.create_contract(
        {"program_id": pid, "vendor_name": "VX", "contract_type": "CONTRACTOR",
         "solicitation_estimate_cents": 100_000},
        owner_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_executive_cannot_decide_charter_unauthorized(api):
    """PRD §4 endpoint table: POST /charters/{id}/decide authorized role is
    Owner only. PRD §2.5 priority 2 surfaces ERR_UNAUTHORIZED_ROLE before any
    state or OCC check.

    Design: Corner/rbac/executive_cannot_decide_charter_unauthorized
    """
    prog = create_program(name="P-R2")
    pid = prog["id"]
    ch = get_success_data(api_client.create_charter(
        create_charter_payload(pid), pm_headers()))
    api_client.submit_charter(ch["id"], pm_headers())
    pv = get_success_data(api_client.get_program(pid, pm_headers()))["version"]
    resp = api_client.decide_charter(
        ch["id"], {"decision": "APPROVE", "expected_program_version": pv},
        exec_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_pm_cannot_accept_report_unauthorized(api):
    """PRD §4 endpoint table: POST /owner-reports/{id}/accept authorized role
    is Owner only. PRD §2.5 priority 2 role check precedes the SoD user-id
    check (priority 6).

    Design: Corner/rbac/pm_cannot_accept_report_unauthorized
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-R3",
    )
    pid = prog["id"]
    rep = create_owner_report(pid, period="2026-08")
    submit_owner_report(rep["id"], pm_id="pm-1")
    # PM role (even with a different user id) can never accept
    resp = api_client.accept_owner_report(rep["id"], make_pm_headers("pm-2"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_closeout_verify_sod_same_user_rejected(api):
    """PRD §2.9: "Submitter vs. verifier. The OwnerRepExecutive who verifies
    a closeout item must not be the operator recorded as that item's
    submitted_by_user_id." And §2.9: "The comparison is always between the
    X-User-ID of the incoming request and the recorded actor field on the
    resource."

    Design: Corner/rbac/closeout_verify_sod_same_user_rejected
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-R4",
    )
    pid = prog["id"]
    ci = create_closeout_item(pid, item_type="WARRANTY", title="warranty pack")
    submit_closeout_item(ci["id"], pm_id="pm-1")
    # Same X-User-ID as submitter (even with the correct exec role) -> SoD
    resp = api_client.verify_closeout_item(ci["id"], make_exec_headers("pm-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # Distinct exec id verifies
    ok = verify_closeout_item(ci["id"], exec_id="exec-1")
    assert ok["status"] == "VERIFIED"


def test_report_accept_sod_same_user_rejected(api):
    """PRD §2.9: "Submitter vs. accepter. The Owner who accepts an owner
    report must not be the operator recorded as that report's
    submitted_by_user_id."

    Design: Corner/rbac/report_accept_sod_same_user_rejected
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-R5",
    )
    pid = prog["id"]
    rep = create_owner_report(pid, period="2026-08")
    submit_owner_report(rep["id"], pm_id="pm-1")
    # Owner role presenting the submitter's user id -> SoD
    resp = api_client.accept_owner_report(rep["id"], make_owner_headers("pm-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # Distinct owner id accepts
    ok = accept_owner_report(rep["id"], owner_id="owner-1")
    assert ok["status"] == "ACCEPTED"


def test_co_decide_sod_same_user_rejected(api):
    """PRD §2.9: "Recommender vs. decider. The Owner who decides a change
    order must not be the operator recorded as that change order's
    recommended_by_user_id."

    Design: Corner/rbac/co_decide_sod_same_user_rejected
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-R6",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 400_000, solicitation_estimate_cents=400_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    co = create_change_order(ct1["id"], amount_cents=50_000, title="CO", reason="r")
    submit_change_order(co["id"])
    recommend_change_order(co["id"], recommendation="APPROVE", analysis_note="ok",
                            pm_id="pm-1")
    # Owner role presenting the recommender's user id -> SoD
    resp = api_client.decide_change_order(
        co["id"], {"decision": "APPROVE"}, make_owner_headers("pm-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # Distinct owner id decides
    ok = get_success_data(api_client.decide_change_order(
        co["id"], {"decision": "APPROVE"}, owner_headers()))
    assert ok["status"] == "APPROVED"
