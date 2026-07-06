"""Structural validations, endpoint conditional errors, error catalogue triggers,
RBAC denials, and optimistic-concurrency corner cases.

Corner queue: validations, endpoints, errors, rbac,
cross_cutting_complexity_layers sections.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    build_user_headers,
    make_triage_nurse_headers,
    make_clinician_dvm_headers,
    make_finance_coordinator_headers,
    make_owner_headers,
    register_patient,
    register_visit,
    register_and_triage,
    create_and_issue_estimate,
    create_draft_estimate,
    create_active_authorization,
    setup_visit_in_treatment,
    setup_finalized_invoice,
    propose_payment_plan,
    activate_payment_plan,
    get_invoice,
    get_visit_state,
    api_client,
)


# ---- validations ----

def test_modality_room_mismatch_returns_422(api):
    """PRD §3.8: "The modality must match the room family: `IMAGING_CT` must book
    `CT_SUITE`, `IMAGING_MRI` must book `MRI_SUITE`, and `SURGERY` must book
    `OR_1` or `OR_2`; a mismatch is rejected with `ERR_MODALITY_ROOM_MISMATCH`."

    Design: Corner/validations/modality_room_mismatch_returns_422
    """
    dvm = make_clinician_dvm_headers()
    _, visit, est, auth = setup_visit_in_treatment(
        triage_level="YELLOW", unit_price_cents=100000,
        approved_ceiling_cents=300000, owner_user_id="owner-1")
    resp = api.create_procedure(visit["id"], {
        "modality": "SURGERY", "resource_room": "CT_SUITE",
        "start_at": "2026-05-01T09:00:00Z", "end_at": "2026-05-01T10:00:00Z",
        "price_cents": 50000}, dvm)
    validate_error(resp, ApiErrorId.ERR_MODALITY_ROOM_MISMATCH, expected_status=422)


def test_cage_out_of_range_returns_422(api):
    """PRD §3.7: "For the ICU ward, the `cage_number` must fall within 1 through
    the ICU capacity inclusive; a value outside that range is rejected with
    `ERR_CAGE_OUT_OF_RANGE`."

    Design: Corner/validations/cage_out_of_range_returns_422
    """
    dvm = make_clinician_dvm_headers()
    _, visit, est, auth = setup_visit_in_treatment(
        triage_level="YELLOW", unit_price_cents=100000,
        approved_ceiling_cents=300000, owner_user_id="owner-1")
    resp = api.create_hospitalization(visit["id"], {
        "ward": "ICU", "cage_number": 999, "admit_at": "2026-05-01T08:00:00Z",
        "planned_discharge_at": "2026-05-02T08:00:00Z"}, dvm)
    validate_error(resp, ApiErrorId.ERR_CAGE_OUT_OF_RANGE, expected_status=422)


def test_release_before_admit_invalid_request(api):
    """PRD §3.7: "A `ClinicianDVM` releases an `ACTIVE` hospitalization
    (`ERR_INVALID_STATE`) by supplying a `released_at` instant that must be
    strictly later than the hospitalization's `admit_at` (otherwise
    `ERR_INVALID_REQUEST`)."

    Design: Corner/validations/hospitalization_release_before_admit_returns_invalid_request
    """
    dvm = make_clinician_dvm_headers()
    from test_helpers import setup_visit_with_active_hospitalization
    _, visit, est, auth, hosp = setup_visit_with_active_hospitalization(
        triage_level="YELLOW", ward="ICU", cage_number=1,
        admit_at="2026-05-02T08:00:00Z",
        planned_discharge_at="2026-05-04T08:00:00Z",
        approved_ceiling_cents=300000, owner_user_id="owner-1")
    resp = api.release_hospitalization(visit["id"], hosp["id"],
                                       {"released_at": "2026-05-01T08:00:00Z"}, dvm)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


# ---- endpoints ----

def test_pay_insufficient_returns_402(api):
    """PRD §3.9: "the payment settles the invoice only if `amount_cents` is at
    least the `balance_due_cents`, and an amount below the balance is rejected
    with `ERR_PAYMENT_INSUFFICIENT`."

    Design: Corner/endpoints/invoice_pay_insufficient_returns_402
    """
    finance = make_finance_coordinator_headers()
    # GREEN visit, one 20000 procedure performed, no deposit -> balance = 20000 + tax.
    _, visit, est, auth = setup_visit_in_treatment(
        triage_level="GREEN", unit_price_cents=20000,
        approved_ceiling_cents=100000, owner_user_id="owner-1")
    from test_helpers import schedule_procedure, perform_procedure, finalize_invoice
    proc = schedule_procedure(visit["id"], modality="IMAGING_CT",
                              resource_room="CT_SUITE",
                              start_at="2026-05-01T09:00:00Z",
                              end_at="2026-05-01T09:30:00Z", price_cents=20000)
    perform_procedure(visit["id"], proc["id"])
    invoice = finalize_invoice(visit["id"])
    resp = api.pay_invoice(visit["id"], {"amount_cents": 100}, finance)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_INSUFFICIENT, expected_status=402)
    inv_after = get_invoice(visit["id"])
    assert inv_after["status"] == "FINALIZED", "insufficient pay leaves invoice FINALIZED"


# ---- errors ----

def test_second_plan_activate_already_active_returns_error(api):
    """PRD §3.10: "no other `ACTIVE` payment plan already linking the same invoice
    (otherwise `ERR_PLAN_ALREADY_ACTIVE`)."

    Design: Corner/errors/plan_already_active_returns_error
    """
    finance = make_finance_coordinator_headers()
    _, visit, _, _, _, invoice = setup_finalized_invoice(
        surgery_price=300000, triage_level="YELLOW",
        approved_ceiling_cents=386100, owner_user_id="owner-3")
    plan1 = propose_payment_plan(visit["id"], invoice["id"],
                                 provider="CARECREDIT", term_months=6)
    activate_payment_plan(visit["id"], plan1["id"])  # invoice now SETTLED, plan1 ACTIVE
    plan2 = propose_payment_plan(visit["id"], invoice["id"],
                                 provider="IN_HOUSE", term_months=12)
    vv = get_visit_state(visit["id"])["version"]
    resp = api.activate_payment_plan(visit["id"], plan2["id"],
                                     {"expected_visit_version": vv}, finance)
    validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_ACTIVE, expected_status=409)


def test_mark_lwbs_with_active_auth_returns_error(api):
    """PRD §3.2: "A `TriageNurse` may record a triaged patient as having left
    without being seen ... This is permitted only when the Visit is in `TRIAGED`
    status (`ERR_INVALID_STATE`) and only when no `ACTIVE` Authorization exists on
    the Visit — if one does, the departure is rejected with
    `ERR_VISIT_HAS_ACTIVE_AUTH`"

    Design: Corner/errors/mark_lwbs_with_active_auth_returns_error
    """
    finance = make_finance_coordinator_headers()
    nurse = make_triage_nurse_headers()
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-1")
    est = create_and_issue_estimate(visit["id"], unit_price_cents=100000)
    create_active_authorization(visit["id"], est["id"], 200000,
                                owner_user_id="owner-1")
    # Visit is still TRIAGED (treatment never begun) but has an ACTIVE auth.
    resp = api.mark_lwbs(visit["id"], nurse)
    validate_error(resp, ApiErrorId.ERR_VISIT_HAS_ACTIVE_AUTH, expected_status=409)


# ---- rbac ----

def test_triage_by_clinician_forbidden(api):
    """PRD §2.1: "When both headers are present but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."
    PRD §3.2: "a `TriageNurse` assigns urgency by triaging it"

    Design: Corner/rbac/triage_by_clinician_forbidden
    """
    nurse = make_triage_nurse_headers()
    dvm = make_clinician_dvm_headers()
    patient = register_patient(owner_user_id="owner-1")
    visit = register_visit(patient["id"])
    resp = api.triage_visit(visit["id"], {"triage_level": "YELLOW"}, dvm)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_approve_by_non_owner_forbidden(api):
    """PRD §2.1: "ownership checks on any resource that references a `Patient`
    (through the Visit's `patient_id`) compare that patient's `owner_user_id` to
    `X-User-ID`. An `Owner` who attempts to read or act on a case whose patient
    they do not own is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/approve_by_non_owner_forbidden
    """
    finance = make_finance_coordinator_headers()
    wrong_owner = make_owner_headers("owner-999")
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-1")
    est = create_and_issue_estimate(visit["id"], unit_price_cents=100000)
    auth = validate_success(api.create_authorization(visit["id"], {
        "estimate_id": est["id"], "approved_ceiling_cents": 200000}, finance),
        expected_status=201)
    resp = api.approve_authorization(visit["id"], auth["id"], wrong_owner)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_unauthenticated_returns_401(api):
    """PRD §2.1: "Every request to the API must be authenticated with two
    mandatory HTTP headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, declaring the capacity in which they act. A request missing
    either header is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_returns_401
    """
    resp = api.create_patient({
        "name": "Rex", "species": "CANINE", "weight_kg": 30,
        "owner_user_id": "owner-1"}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


# ---- cross_cutting_complexity_layers (OCC) ----

def test_estimate_issue_stale_visit_version_rejected(api):
    """PRD §2.10: "if `expected_visit_version` does not equal the Visit's current
    `version` — because another writer has advanced it since the client last read
    the Visit — the issue is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.4: "the request must carry `expected_visit_version` matching the
    Visit's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`"

    Design: Corner/cross_cutting_complexity_layers/occ_estimate_issue_stale_visit_version
    """
    finance = make_finance_coordinator_headers()
    owner = make_owner_headers("owner-1")
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-1")
    # Capture a stale version, then advance Visit.version via an approve cascade.
    vv_stale = get_visit_state(visit["id"])["version"]
    est1 = create_draft_estimate(visit["id"], unit_price_cents=100000)
    vv_ok = get_visit_state(visit["id"])["version"]
    validate_success(api.issue_estimate(visit["id"], est1["id"],
                                        {"expected_visit_version": vv_ok}, finance))
    auth = validate_success(api.create_authorization(visit["id"], {
        "estimate_id": est1["id"], "approved_ceiling_cents": 200000}, finance),
        expected_status=201)
    validate_success(api.approve_authorization(visit["id"], auth["id"], owner))
    # Now a second draft; issuing with the stale version must be rejected.
    est2 = create_draft_estimate(visit["id"], unit_price_cents=50000, code="TX2")
    resp = api.issue_estimate(visit["id"], est2["id"],
                              {"expected_visit_version": vv_stale}, finance)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_estimate_issue_correct_version_succeeds(api):
    """PRD §2.10: "Issuing an estimate requires the request to carry
    `expected_visit_version`, the Visit `version` the client last observed."
    PRD §3.4: "On issue, the estimate moves from `DRAFT` to `ISSUED`"

    Design: Corner/cross_cutting_complexity_layers/occ_estimate_issue_correct_version_succeeds
    """
    finance = make_finance_coordinator_headers()
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-1")
    est = create_draft_estimate(visit["id"], unit_price_cents=100000)
    vv_ok = get_visit_state(visit["id"])["version"]
    resp = api.issue_estimate(visit["id"], est["id"],
                              {"expected_visit_version": vv_ok}, finance)
    issued = validate_success(resp)
    assert issued["status"] == "ISSUED"
