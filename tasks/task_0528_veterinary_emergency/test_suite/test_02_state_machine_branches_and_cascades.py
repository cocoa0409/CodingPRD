"""Non-linear state machine and transitive-cascade tests: authorization
revision cycle, visit death branch, discharge report cascade, approve
deposit-credit cascade.

Difficulty queue: non_linear_state_machine, transitive_cascade.
"""
from test_helpers import (
    validate_success,
    make_finance_coordinator_headers,
    make_clinician_dvm_headers,
    make_owner_headers,
    register_and_triage,
    setup_visit_with_active_auth,
    setup_visit_in_treatment,
    admit_hospitalization,
    schedule_procedure,
    perform_procedure,
    finalize_invoice,
    get_invoice,
    get_visit_state,
    api_client,
)


def test_decline_authorization_supersedes_estimate(api):
    """PRD §3.5: "Declining is the owner's rejection of the proposed spend. It
    requires the Authorization to be `PENDING` (`ERR_INVALID_STATE`), moves it
    from `PENDING` to `DECLINED`, and supersedes the referenced estimate —
    moving it from `ISSUED` to `SUPERSEDED`; both versions increment."

    Design: Difficulty/non_linear_state_machine/nlsm_authorization_decline_revision_cycle
    """
    finance = make_finance_coordinator_headers()
    owner = make_owner_headers("owner-4")
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-4",
                                   chief_complaint="lameness")
    from test_helpers import create_and_issue_estimate
    est = create_and_issue_estimate(visit["id"], unit_price_cents=100000)
    auth = validate_success(api.create_authorization(visit["id"], {
        "estimate_id": est["id"], "approved_ceiling_cents": 200000}, finance),
        expected_status=201)
    resp = api.decline_authorization(visit["id"], auth["id"], owner)
    declined = validate_success(resp)
    assert declined["status"] == "DECLINED"
    est_after = validate_success(api.get_estimate(visit["id"], est["id"], finance))
    assert est_after["status"] == "SUPERSEDED"


def test_decline_authorization_marks_authorization_declined(api):
    """PRD §3.5: "It requires the Authorization to be `PENDING`
    (`ERR_INVALID_STATE`), moves it from `PENDING` to `DECLINED`, and supersedes
    the referenced estimate"

    Design: Difficulty/non_linear_state_machine/nlsm_authorization_decline_revision_cycle
    """
    finance = make_finance_coordinator_headers()
    owner = make_owner_headers("owner-4")
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-4")
    from test_helpers import create_and_issue_estimate
    est = create_and_issue_estimate(visit["id"], unit_price_cents=100000)
    auth = validate_success(api.create_authorization(visit["id"], {
        "estimate_id": est["id"], "approved_ceiling_cents": 200000}, finance),
        expected_status=201)
    resp = api.decline_authorization(visit["id"], auth["id"], owner)
    assert validate_success(resp)["status"] == "DECLINED"


def test_mark_deceased_unwinds_hospitalization_and_procedure(api):
    """PRD §3.6: "Recording death unwinds open commitments: every `ACTIVE`
    Hospitalization on the Visit is released — which accrues its board cost and
    posts it to the invoice exactly as a normal release does, then recomputes
    the invoice's subtotal, tax, and balance — and in parallel every `SCHEDULED`
    Procedure on the Visit is cancelled, freeing each one's resource-room slot."
    PRD §3.6: "A `ClinicianDVM` records this from the `IN_TREATMENT` status only
    (`ERR_INVALID_STATE`), moving the Visit to the terminal `DECEASED` status."

    Design: Difficulty/non_linear_state_machine/nlsm_visit_branch_deceased_vs_discharge
    """
    dvm = make_clinician_dvm_headers()
    _, visit, _, _ = setup_visit_in_treatment(triage_level="YELLOW",
                                              unit_price_cents=100000,
                                              approved_ceiling_cents=300000,
                                              owner_user_id="owner-5",
                                              chief_complaint="trauma")
    hosp = admit_hospitalization(visit["id"], ward="ICU", cage_number=1,
                                 admit_at="2026-05-01T08:00:00Z",
                                 planned_discharge_at="2026-05-03T08:00:00Z")
    proc = schedule_procedure(visit["id"], modality="SURGERY", resource_room="OR_1",
                              start_at="2026-05-01T12:00:00Z",
                              end_at="2026-05-01T14:00:00Z", price_cents=50000)
    resp = api.mark_deceased(visit["id"], dvm)
    v = validate_success(resp)
    assert v["status"] == "DECEASED"
    hosp_after = validate_success(api.list_hospitalizations(visit["id"], dvm))
    hosp_row = next(h for h in hosp_after if h["id"] == hosp["id"])
    assert hosp_row["status"] == "RELEASED"
    procs = validate_success(api.list_procedures(visit["id"], dvm))
    proc_row = next(p for p in procs if p["id"] == proc["id"])
    assert proc_row["status"] == "CANCELLED"


def test_mark_deceased_terminal_status(api):
    """PRD §3.6: "A patient may die during treatment. A `ClinicianDVM` records
    this from the `IN_TREATMENT` status only (`ERR_INVALID_STATE`), moving the
    Visit to the terminal `DECEASED` status."

    Design: Difficulty/non_linear_state_machine/nlsm_visit_branch_deceased_vs_discharge
    """
    dvm = make_clinician_dvm_headers()
    _, visit, _, _ = setup_visit_in_treatment(triage_level="YELLOW",
                                              approved_ceiling_cents=300000,
                                              owner_user_id="owner-5b")
    resp = api.mark_deceased(visit["id"], dvm)
    assert validate_success(resp)["status"] == "DECEASED"


def test_discharge_finalizes_invoice_and_generates_report(api):
    """PRD §3.11: "Discharge moves the Visit from `READY_FOR_DISCHARGE` to the
    terminal `DISCHARGED` status and triggers two cascading effects."
    PRD §3.11: "Second, a ReferringVetReport is generated as the discharge
    artifact."
    PRD §3.11: "its `total_billed_cents` is the Visit invoice's `subtotal_cents`
    plus `tax_cents` at generation."

    Design: Difficulty/transitive_cascade/tc_discharge_finalize_report_depth3
    """
    finance = make_finance_coordinator_headers()
    dvm = make_clinician_dvm_headers()
    # Build a YELLOW visit, perform one 20000 CT procedure, finalize, pay in full,
    # ready-for-discharge, then discharge.
    _, visit, _, _ = setup_visit_in_treatment(triage_level="YELLOW",
                                              unit_price_cents=20000,
                                              approved_ceiling_cents=100000,
                                              owner_user_id="owner-6",
                                              chief_complaint="URI")
    proc = schedule_procedure(visit["id"], modality="IMAGING_CT",
                              resource_room="CT_SUITE",
                              start_at="2026-05-01T09:00:00Z",
                              end_at="2026-05-01T09:30:00Z", price_cents=20000)
    perform_procedure(visit["id"], proc["id"])
    invoice = finalize_invoice(visit["id"])
    # Balance after the deposit credit; pay it in full.
    validate_success(api.pay_invoice(visit["id"],
                                     {"amount_cents": invoice["balance_due_cents"]}, finance))
    validate_success(api.ready_for_discharge(visit["id"], dvm))
    resp = api.discharge(visit["id"], dvm)
    v = validate_success(resp)
    assert v["status"] == "DISCHARGED"
    inv_after = get_invoice(visit["id"])
    assert inv_after["status"] == "SETTLED"
    reports = validate_success(api.list_referring_vet_reports(visit["id"], dvm))
    assert len(reports) == 1, f"expected exactly 1 report, got {len(reports)}"
    expected_billed = inv_after["subtotal_cents"] + inv_after["tax_cents"]
    assert reports[0]["total_billed_cents"] == expected_billed, (
        f"expected total_billed_cents {expected_billed}, got {reports[0]['total_billed_cents']}")


def test_discharge_report_snapshots_invoice_total(api):
    """PRD §3.11: "it also snapshots the case at report time — its
    `procedures_performed` is the list of `PERFORMED` procedure ids on the Visit,
    and its `total_billed_cents` is the Visit invoice's `subtotal_cents` plus
    `tax_cents` at generation."

    Design: Difficulty/transitive_cascade/tc_discharge_finalize_report_depth3
    """
    finance = make_finance_coordinator_headers()
    dvm = make_clinician_dvm_headers()
    _, visit, _, _ = setup_visit_in_treatment(triage_level="YELLOW",
                                              unit_price_cents=20000,
                                              approved_ceiling_cents=100000,
                                              owner_user_id="owner-6b")
    proc = schedule_procedure(visit["id"], modality="IMAGING_CT",
                              resource_room="CT_SUITE",
                              start_at="2026-05-01T09:00:00Z",
                              end_at="2026-05-01T09:30:00Z", price_cents=20000)
    perform_procedure(visit["id"], proc["id"])
    invoice = finalize_invoice(visit["id"])
    validate_success(api.pay_invoice(visit["id"],
                                     {"amount_cents": invoice["balance_due_cents"]}, finance))
    validate_success(api.ready_for_discharge(visit["id"], dvm))
    validate_success(api.discharge(visit["id"], dvm))
    inv_after = get_invoice(visit["id"])
    reports = validate_success(api.list_referring_vet_reports(visit["id"], dvm))
    assert reports[0]["total_billed_cents"] == inv_after["subtotal_cents"] + inv_after["tax_cents"]


def test_approve_credits_deposit_and_recomputes_ceiling(api):
    """PRD §3.5: "the referenced estimate moves from `ISSUED` to `CONSUMED`; the
    estimate's `deposit_cents` is copied into the authorization's
    `deposit_paid_cents`; the Visit's `authorized_ceiling_cents` is recomputed as
    the sum of `approved_ceiling_cents` over all active authorizations; and that
    deposit is credited into the Visit's open invoice by increasing its
    `deposit_applied_cents`, after which the invoice's balance is recomputed."

    Design: Difficulty/transitive_cascade/tc_authorization_approve_deposit_balance_depth2
    """
    finance = make_finance_coordinator_headers()
    owner = make_owner_headers("owner-7")
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-7",
                                   chief_complaint="bloat")
    from test_helpers import create_and_issue_estimate
    est = create_and_issue_estimate(visit["id"], unit_price_cents=300000)
    auth = validate_success(api.create_authorization(visit["id"], {
        "estimate_id": est["id"], "approved_ceiling_cents": 386100}, finance),
        expected_status=201)
    resp = api.approve_authorization(visit["id"], auth["id"], owner)
    active = validate_success(resp)
    assert active["status"] == "ACTIVE"
    est_after = validate_success(api.get_estimate(visit["id"], est["id"], finance))
    assert est_after["status"] == "CONSUMED"
    invoice = get_invoice(visit["id"])
    assert invoice["deposit_applied_cents"] == 193050, (
        f"expected deposit_applied 193050, got {invoice['deposit_applied_cents']}")
    v = get_visit_state(visit["id"])
    assert v["authorized_ceiling_cents"] == 386100


def test_approve_consumes_estimate_and_sets_ceiling(api):
    """PRD §3.5: "the referenced estimate moves from `ISSUED` to `CONSUMED`"
    PRD §3.5: "the Visit's `authorized_ceiling_cents` is recomputed as the sum of
    `approved_ceiling_cents` over all active authorizations"

    Design: Difficulty/transitive_cascade/tc_authorization_approve_deposit_balance_depth2
    """
    finance = make_finance_coordinator_headers()
    owner = make_owner_headers("owner-7b")
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-7b")
    from test_helpers import create_and_issue_estimate
    est = create_and_issue_estimate(visit["id"], unit_price_cents=300000)
    auth = validate_success(api.create_authorization(visit["id"], {
        "estimate_id": est["id"], "approved_ceiling_cents": 386100}, finance),
        expected_status=201)
    validate_success(api.approve_authorization(visit["id"], auth["id"], owner))
    est_after = validate_success(api.get_estimate(visit["id"], est["id"], finance))
    assert est_after["status"] == "CONSUMED"
    v = get_visit_state(visit["id"])
    assert v["authorized_ceiling_cents"] == 386100
