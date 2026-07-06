"""Composite setup helpers.

Every fixture builds its preconditions from scratch (empty DB) using only
PRD-declared endpoints. Setup calls use get_success_data() (lenient) so a
broken precondition surfaces as a clear "Setup failed" rather than a confusing
assertion error inside a test.

Owner is entity_backed: after a patient is created with owner_user_id=X, any
Owner-gated call on that patient's visit passes make_owner_headers(X).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_triage_nurse_headers,
    make_clinician_dvm_headers,
    make_finance_coordinator_headers,
    make_owner_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: primitive progression helpers
# ---------------------------------------------------------------------------

def register_patient(owner_user_id="owner-1", name="Rex", species="CANINE", weight_kg=30):
    """POST /patients. Returns the patient dict."""
    nurse = make_triage_nurse_headers()
    resp = api_client.create_patient(
        {"name": name, "species": species, "weight_kg": weight_kg,
         "owner_user_id": owner_user_id},
        nurse,
    )
    return get_success_data(resp)


def register_visit(patient_id, chief_complaint="collapse"):
    """POST /visits (creates the OPEN Invoice). Returns the visit dict."""
    nurse = make_triage_nurse_headers()
    resp = api_client.create_visit(
        {"patient_id": patient_id, "chief_complaint": chief_complaint}, nurse
    )
    return get_success_data(resp)


def register_and_triage(triage_level="YELLOW", owner_user_id="owner-1",
                        chief_complaint="collapse", name="Rex",
                        species="CANINE", weight_kg=30):
    """Patient -> visit (OPEN invoice) -> triage. Returns (patient, visit)."""
    nurse = make_triage_nurse_headers()
    patient = register_patient(owner_user_id=owner_user_id, name=name,
                               species=species, weight_kg=weight_kg)
    visit = register_visit(patient["id"], chief_complaint=chief_complaint)
    get_success_data(api_client.triage_visit(visit["id"], {"triage_level": triage_level}, nurse))
    visit = get_success_data(api_client.get_visit(visit["id"], nurse))
    return patient, visit


def _current_visit_version(visit_id):
    finance = make_finance_coordinator_headers()
    v = get_success_data(api_client.get_visit(visit_id, finance))
    return v["version"]


# ---------------------------------------------------------------------------
# Tier 2/3: estimate + authorization lifecycle
# ---------------------------------------------------------------------------

def create_draft_estimate(visit_id, unit_price_cents=100000, qty=1, code="TX",
                          description="care", line_items=None):
    """Create a DRAFT estimate. Returns the estimate dict."""
    finance = make_finance_coordinator_headers()
    if line_items is None:
        line_items = [{"code": code, "description": description, "qty": qty,
                       "unit_price_cents": unit_price_cents}]
    resp = api_client.create_estimate(visit_id, {"line_items": line_items}, finance)
    return get_success_data(resp)


def create_and_issue_estimate(visit_id, unit_price_cents=100000, qty=1,
                              line_items=None):
    """Create a DRAFT estimate then issue it (OCC on the current Visit.version).
    Returns the issued estimate dict."""
    finance = make_finance_coordinator_headers()
    est = create_draft_estimate(visit_id, unit_price_cents=unit_price_cents,
                                qty=qty, line_items=line_items)
    vv = _current_visit_version(visit_id)
    resp = api_client.issue_estimate(visit_id, est["id"],
                                     {"expected_visit_version": vv}, finance)
    return get_success_data(resp)


def create_active_authorization(visit_id, estimate_id, approved_ceiling_cents,
                                owner_user_id="owner-1"):
    """Create a PENDING authorization then Owner-approve it -> ACTIVE.
    Returns the active authorization dict."""
    finance = make_finance_coordinator_headers()
    owner = make_owner_headers(owner_user_id)
    auth = get_success_data(api_client.create_authorization(
        visit_id, {"estimate_id": estimate_id,
                   "approved_ceiling_cents": approved_ceiling_cents}, finance))
    resp = api_client.approve_authorization(visit_id, auth["id"], owner)
    return get_success_data(resp)


def setup_visit_with_active_auth(triage_level="YELLOW", unit_price_cents=100000,
                                 approved_ceiling_cents=300000,
                                 owner_user_id="owner-1", chief_complaint="care",
                                 est_line_items=None):
    """Patient -> visit -> triage -> issued estimate -> ACTIVE authorization.
    Visit remains TRIAGED (treatment not yet begun).
    Returns (patient, visit, estimate, authorization)."""
    patient, visit = register_and_triage(triage_level=triage_level,
                                         owner_user_id=owner_user_id,
                                         chief_complaint=chief_complaint)
    est = create_and_issue_estimate(visit["id"], unit_price_cents=unit_price_cents,
                                    line_items=est_line_items)
    auth = create_active_authorization(visit["id"], est["id"],
                                       approved_ceiling_cents,
                                       owner_user_id=owner_user_id)
    return patient, visit, est, auth


def setup_visit_in_treatment(triage_level="YELLOW", unit_price_cents=100000,
                             approved_ceiling_cents=300000,
                             owner_user_id="owner-1", chief_complaint="care",
                             est_line_items=None):
    """As setup_visit_with_active_auth, then begin-treatment -> IN_TREATMENT.
    Returns (patient, visit, estimate, authorization)."""
    dvm = make_clinician_dvm_headers()
    patient, visit, est, auth = setup_visit_with_active_auth(
        triage_level=triage_level, unit_price_cents=unit_price_cents,
        approved_ceiling_cents=approved_ceiling_cents,
        owner_user_id=owner_user_id, chief_complaint=chief_complaint,
        est_line_items=est_line_items)
    get_success_data(api_client.begin_treatment(visit["id"], dvm))
    finance = make_finance_coordinator_headers()
    visit = get_success_data(api_client.get_visit(visit["id"], finance))
    return patient, visit, est, auth


# ---------------------------------------------------------------------------
# Tier 3/4: procedures + charge accumulation
# ---------------------------------------------------------------------------

def schedule_procedure(visit_id, modality="IMAGING_CT", resource_room="CT_SUITE",
                       start_at="2026-05-01T09:00:00Z", end_at="2026-05-01T09:30:00Z",
                       price_cents=20000):
    """Schedule one procedure. Returns the procedure dict."""
    dvm = make_clinician_dvm_headers()
    resp = api_client.create_procedure(visit_id, {
        "modality": modality, "resource_room": resource_room,
        "start_at": start_at, "end_at": end_at, "price_cents": price_cents,
    }, dvm)
    return get_success_data(resp)


def perform_procedure(visit_id, procedure_id):
    dvm = make_clinician_dvm_headers()
    return get_success_data(api_client.perform_procedure(visit_id, procedure_id, dvm))


# A small pool of non-overlapping (room, start, end) slots so multiple
# procedures on one visit never trip ERR_RESOURCE_DOUBLE_BOOKED.
_PROC_SLOTS = [
    ("IMAGING_CT", "CT_SUITE", "2026-05-01T09:00:00Z", "2026-05-01T09:30:00Z"),
    ("IMAGING_MRI", "MRI_SUITE", "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z"),
    ("SURGERY", "OR_1", "2026-05-01T11:00:00Z", "2026-05-01T11:30:00Z"),
    ("SURGERY", "OR_2", "2026-05-01T12:00:00Z", "2026-05-01T12:30:00Z"),
]


def perform_charges(visit_id, prices):
    """Schedule + perform one procedure per price in `prices`, each on a
    distinct non-overlapping slot. Returns the list of performed procedure dicts."""
    performed = []
    for i, price in enumerate(prices):
        modality, room, start, end = _PROC_SLOTS[i % len(_PROC_SLOTS)]
        proc = schedule_procedure(visit_id, modality=modality, resource_room=room,
                                  start_at=start, end_at=end, price_cents=price)
        performed.append(perform_procedure(visit_id, proc["id"]))
    return performed


def setup_visit_with_performed_charges(prices, triage_level="GREEN",
                                       approved_ceiling_cents=None,
                                       owner_user_id="owner-1"):
    """IN_TREATMENT visit with each price in `prices` performed onto the OPEN
    invoice. Ceiling defaults to sum(prices)+slack. Returns (patient, visit,
    estimate, authorization, [performed procedures])."""
    if approved_ceiling_cents is None:
        approved_ceiling_cents = sum(prices) + 100000
    patient, visit, est, auth = setup_visit_in_treatment(
        triage_level=triage_level, unit_price_cents=20000,
        approved_ceiling_cents=approved_ceiling_cents, owner_user_id=owner_user_id)
    performed = perform_charges(visit["id"], prices)
    return patient, visit, est, auth, performed


# ---------------------------------------------------------------------------
# Tier 4/5: hospitalization
# ---------------------------------------------------------------------------

def admit_hospitalization(visit_id, ward="ICU", cage_number=1,
                          admit_at="2026-05-01T08:00:00Z",
                          planned_discharge_at="2026-05-02T08:00:00Z"):
    """Admit an ACTIVE hospitalization. Returns the hospitalization dict."""
    dvm = make_clinician_dvm_headers()
    resp = api_client.create_hospitalization(visit_id, {
        "ward": ward, "cage_number": cage_number, "admit_at": admit_at,
        "planned_discharge_at": planned_discharge_at,
    }, dvm)
    return get_success_data(resp)


def setup_visit_with_active_hospitalization(triage_level="YELLOW", ward="ICU",
                                            cage_number=1,
                                            admit_at="2026-05-01T08:00:00Z",
                                            planned_discharge_at="2026-05-02T08:00:00Z",
                                            approved_ceiling_cents=300000,
                                            owner_user_id="owner-1"):
    """IN_TREATMENT visit with one ACTIVE hospitalization. Returns
    (patient, visit, estimate, authorization, hospitalization)."""
    patient, visit, est, auth = setup_visit_in_treatment(
        triage_level=triage_level, unit_price_cents=100000,
        approved_ceiling_cents=approved_ceiling_cents, owner_user_id=owner_user_id)
    hosp = admit_hospitalization(visit["id"], ward=ward, cage_number=cage_number,
                                 admit_at=admit_at,
                                 planned_discharge_at=planned_discharge_at)
    return patient, visit, est, auth, hosp


# ---------------------------------------------------------------------------
# Tier 5: finalized invoice / payment plan
# ---------------------------------------------------------------------------

def finalize_invoice(visit_id):
    finance = make_finance_coordinator_headers()
    return get_success_data(api_client.finalize_invoice(visit_id, finance))


def setup_finalized_invoice(surgery_price=300000, triage_level="YELLOW",
                            approved_ceiling_cents=386100, owner_user_id="owner-1"):
    """IN_TREATMENT visit -> one SURGERY procedure performed -> invoice FINALIZED.
    Deposit (from the issued YELLOW estimate) is credited before finalize.
    Returns (patient, visit, estimate, authorization, procedure, invoice)."""
    patient, visit, est, auth = setup_visit_in_treatment(
        triage_level=triage_level, unit_price_cents=surgery_price,
        approved_ceiling_cents=approved_ceiling_cents, owner_user_id=owner_user_id)
    proc = schedule_procedure(visit["id"], modality="SURGERY", resource_room="OR_1",
                              start_at="2026-05-01T09:00:00Z",
                              end_at="2026-05-01T11:00:00Z", price_cents=surgery_price)
    perform_procedure(visit["id"], proc["id"])
    invoice = finalize_invoice(visit["id"])
    return patient, visit, est, auth, proc, invoice


def propose_payment_plan(visit_id, invoice_id, provider="CARECREDIT", term_months=6):
    finance = make_finance_coordinator_headers()
    resp = api_client.create_payment_plan(visit_id, {
        "invoice_id": invoice_id, "provider": provider, "term_months": term_months,
    }, finance)
    return get_success_data(resp)


def activate_payment_plan(visit_id, plan_id):
    finance = make_finance_coordinator_headers()
    vv = _current_visit_version(visit_id)
    resp = api_client.activate_payment_plan(visit_id, plan_id,
                                            {"expected_visit_version": vv}, finance)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Invoice read helper (invoice is returned as a single-element list)
# ---------------------------------------------------------------------------

def get_invoice(visit_id):
    """Fetch the visit's single invoice (returned as a one-element list)."""
    finance = make_finance_coordinator_headers()
    resp = api_client.get_invoice(visit_id, finance)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data[0]
    return data


def get_visit_state(visit_id):
    finance = make_finance_coordinator_headers()
    return get_success_data(api_client.get_visit(visit_id, finance))
