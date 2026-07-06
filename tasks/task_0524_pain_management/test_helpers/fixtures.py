"""Composite setup helpers.

Every test runs against a freshly-restarted, empty server, so each helper builds all
of its preconditions from scratch using only PRD-declared endpoints. Fixtures use the
lenient get_success_data() validator so setup failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Identity threading: after creating a Provider that acts as Prescriber / ComplianceOfficer,
every ownership-gated call uses make_prescriber_headers(id) / make_compliance_officer_headers(id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_clinic_payload,
    create_provider_payload,
    create_patient_payload,
    create_opioid_agreement_payload,
    create_pdmp_check_payload,
    create_treatment_plan_payload,
    create_fluoroscopy_suite_payload,
    create_prior_authorization_payload,
    create_procedure_payload,
    create_prescription_payload,
    create_urine_drug_screen_payload,
    create_pill_count_audit_payload,
)
from .test_users import (
    TEST_USERS,
    make_prescriber_headers,
    make_compliance_officer_headers,
    make_clinic_admin_headers,
    make_intake_coordinator_headers,
    make_prior_auth_clerk_headers,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
PA_CLERK = TEST_USERS["prior_auth_clerk_headers"]


# ---------------------------------------------------------------------------
# Clock helper
# ---------------------------------------------------------------------------
def set_clock(clinic_id: str, to_iso8601: str):
    return get_success_data(
        api_client.set_current_utc({"clinic_id": clinic_id, "to_iso8601": to_iso8601}, ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: base entities
# ---------------------------------------------------------------------------
def create_clinic(clock_utc: str = None, **overrides):
    """Create a clinic; optionally advance its logical clock to clock_utc."""
    clinic = get_success_data(api_client.create_clinic(create_clinic_payload(**overrides), ADMIN))
    if clock_utc is not None:
        set_clock(clinic["id"], clock_utc)
        clinic = get_success_data(api_client.get_clinic(clinic["id"], ADMIN))
    return clinic


def create_prescriber(clinic_id: str, **overrides):
    """Create a PRESCRIBER provider. Returns the provider dict."""
    overrides.setdefault("role_kind", "PRESCRIBER")
    payload = create_provider_payload(**overrides)
    return get_success_data(api_client.create_provider(clinic_id, payload, ADMIN))


def create_compliance_officer(clinic_id: str, **overrides):
    """Create a COMPLIANCE_OFFICER provider. Returns the provider dict."""
    overrides.setdefault("full_name", "CO One")
    overrides.setdefault("dea_number", "AC7654321")
    overrides.setdefault("role_kind", "COMPLIANCE_OFFICER")
    payload = create_provider_payload(**overrides)
    return get_success_data(api_client.create_provider(clinic_id, payload, ADMIN))


def create_suite(clinic_id: str, **overrides):
    return get_success_data(
        api_client.create_fluoroscopy_suite(clinic_id, create_fluoroscopy_suite_payload(**overrides), ADMIN)
    )


def register_patient(clinic_id: str, **overrides):
    """Register a referral (patient in REFERRED). Returns the patient dict."""
    return get_success_data(
        api_client.create_patient(clinic_id, create_patient_payload(**overrides), INTAKE)
    )


# ---------------------------------------------------------------------------
# Tier 1: patient state progression
# ---------------------------------------------------------------------------
def advance_patient_to_active(clinic_id: str, patient_id: str, intake_utc: str = "2026-05-01T00:00:00Z"):
    """Walk REFERRED -> INTAKE_SCHEDULED -> INTAKE_COMPLETE -> ACTIVE.

    Requires at least one plan already routed (PROCEDURE_PATH/MEDICATION_PATH or ACTIVE)
    for the activate step to satisfy ERR_NO_ACTIVE_PLAN.
    """
    get_success_data(api_client.schedule_intake(clinic_id, patient_id, {"intake_utc": intake_utc}, INTAKE))
    get_success_data(api_client.complete_intake(clinic_id, patient_id, INTAKE))
    return get_success_data(api_client.activate_patient(clinic_id, patient_id, INTAKE))


def create_routed_plan(clinic_id: str, patient_id: str, prescriber_id: str, modality: str):
    """Create -> approve -> route a treatment plan. Returns the routed plan dict."""
    pres_h = make_prescriber_headers(prescriber_id)
    plan = get_success_data(
        api_client.create_treatment_plan(clinic_id, patient_id, create_treatment_plan_payload(modality=modality), pres_h)
    )
    get_success_data(api_client.approve_treatment_plan(clinic_id, patient_id, plan["id"], pres_h))
    return get_success_data(api_client.route_treatment_plan(clinic_id, patient_id, plan["id"], pres_h))


# ---------------------------------------------------------------------------
# Tier 2/3: active patient on a routed medication plan (the most common base)
# ---------------------------------------------------------------------------
def setup_active_medication_patient(clock_utc: str = None, intake_utc: str = "2026-05-01T00:00:00Z"):
    """Active patient with a routed MEDICATION plan, plus a prescriber and a compliance officer.

    Returns dict: clinic, prescriber, compliance_officer, patient, plan.
    """
    clinic = create_clinic(clock_utc=clock_utc)
    prescriber = create_prescriber(clinic["id"])
    co = create_compliance_officer(clinic["id"])
    patient = register_patient(clinic["id"])
    plan = create_routed_plan(clinic["id"], patient["id"], prescriber["id"], "MEDICATION")
    advance_patient_to_active(clinic["id"], patient["id"], intake_utc=intake_utc)
    return {
        "clinic": clinic,
        "prescriber": prescriber,
        "compliance_officer": co,
        "patient": patient,
        "plan": plan,
    }


def setup_active_procedure_patient(clock_utc: str = None, intake_utc: str = "2026-05-01T00:00:00Z", modality="INJECTION"):
    """Active patient with a routed PROCEDURE-path plan, a prescriber, and a suite.

    Returns dict: clinic, prescriber, patient, plan, suite.
    """
    clinic = create_clinic(clock_utc=clock_utc)
    prescriber = create_prescriber(clinic["id"])
    suite = create_suite(clinic["id"])
    patient = register_patient(clinic["id"])
    plan = create_routed_plan(clinic["id"], patient["id"], prescriber["id"], modality)
    advance_patient_to_active(clinic["id"], patient["id"], intake_utc=intake_utc)
    return {
        "clinic": clinic,
        "prescriber": prescriber,
        "patient": patient,
        "plan": plan,
        "suite": suite,
    }


# ---------------------------------------------------------------------------
# Prescription helpers
# ---------------------------------------------------------------------------
def propose_prescription(clinic_id: str, patient_id: str, prescriber_id: str, **overrides):
    """Propose a prescription. Returns the PROPOSED prescription dict."""
    pres_h = make_prescriber_headers(prescriber_id)
    payload = create_prescription_payload(prescriber_id, **overrides)
    return get_success_data(api_client.create_prescription(clinic_id, patient_id, payload, pres_h))


def activate_prescription(clinic_id: str, patient_id: str, prescriber_id: str, rx_id: str):
    pres_h = make_prescriber_headers(prescriber_id)
    return get_success_data(api_client.activate_prescription(clinic_id, patient_id, rx_id, pres_h))


def create_active_below_threshold_rx(ctx, **overrides):
    """Given a setup_active_medication_patient ctx, propose + activate a below-threshold Rx.

    Default provisional MED = 5 * 4 * 1.0 = 20.00. Returns the ACTIVE prescription dict.
    """
    defaults = dict(
        drug_name="tramadol", dose_mg=5, units_per_day=4, conversion_factor=1.0,
        day_supply=30, pills_dispensed=120,
    )
    defaults.update(overrides)
    rx = propose_prescription(ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"], **defaults)
    return activate_prescription(ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"], rx["id"])


def get_prescription(clinic_id, patient_id, prescriber_id, rx_id):
    lst = get_success_data(
        api_client.list_prescriptions(clinic_id, patient_id, make_prescriber_headers(prescriber_id))
    )
    for rx in lst:
        if rx["id"] == rx_id:
            return rx
    return None


# ---------------------------------------------------------------------------
# Opioid agreement + PDMP + prior-auth (the full above-threshold gate package)
# ---------------------------------------------------------------------------
def create_active_agreement(clinic_id: str, patient_id: str, prescriber_id: str):
    """Draft + counter-sign an opioid agreement. Returns ACTIVE agreement dict."""
    pres_h = make_prescriber_headers(prescriber_id)
    ag = get_success_data(
        api_client.create_opioid_agreement(
            clinic_id, create_opioid_agreement_payload(patient_id, prescriber_id), pres_h
        )
    )
    return get_success_data(api_client.counter_sign_agreement(clinic_id, ag["id"], pres_h))


def create_draft_agreement(clinic_id: str, patient_id: str, prescriber_id: str):
    pres_h = make_prescriber_headers(prescriber_id)
    return get_success_data(
        api_client.create_opioid_agreement(
            clinic_id, create_opioid_agreement_payload(patient_id, prescriber_id), pres_h
        )
    )


def create_pdmp_check(clinic_id: str, patient_id: str, prescriber_id: str, **overrides):
    pres_h = make_prescriber_headers(prescriber_id)
    return get_success_data(
        api_client.create_pdmp_check(
            clinic_id, create_pdmp_check_payload(patient_id, prescriber_id, **overrides), pres_h
        )
    )


def create_approved_prescription_pa(clinic_id: str, patient_id: str, authorized_units: int = 30):
    """Submit + approve a PRESCRIPTION-target prior authorization. Returns APPROVED PA dict."""
    pa = get_success_data(
        api_client.create_prior_authorization(
            clinic_id, patient_id,
            create_prior_authorization_payload(target_kind="PRESCRIPTION", authorized_units=authorized_units),
            PA_CLERK,
        )
    )
    return get_success_data(
        api_client.decide_prior_authorization(clinic_id, patient_id, pa["id"], {"decision": "APPROVED"}, PA_CLERK)
    )


def submit_prescription_pa(clinic_id: str, patient_id: str, authorized_units: int = 30):
    """Submit (but do NOT decide) a PRESCRIPTION-target prior authorization. Returns SUBMITTED PA."""
    return get_success_data(
        api_client.create_prior_authorization(
            clinic_id, patient_id,
            create_prior_authorization_payload(target_kind="PRESCRIPTION", authorized_units=authorized_units),
            PA_CLERK,
        )
    )


def create_approved_procedure_pa(clinic_id: str, patient_id: str, authorized_units: int = 1):
    pa = get_success_data(
        api_client.create_prior_authorization(
            clinic_id, patient_id,
            create_prior_authorization_payload(target_kind="PROCEDURE", authorized_units=authorized_units),
            PA_CLERK,
        )
    )
    return get_success_data(
        api_client.decide_prior_authorization(clinic_id, patient_id, pa["id"], {"decision": "APPROVED"}, PA_CLERK)
    )


def submit_procedure_pa(clinic_id: str, patient_id: str, authorized_units: int = 1):
    """Submit (but do NOT decide) a PROCEDURE-target prior authorization. Returns SUBMITTED PA."""
    return get_success_data(
        api_client.create_prior_authorization(
            clinic_id, patient_id,
            create_prior_authorization_payload(target_kind="PROCEDURE", authorized_units=authorized_units),
            PA_CLERK,
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: scheduled procedure (OCC-aware)
# ---------------------------------------------------------------------------
def request_procedure(clinic_id, patient_id, plan_id, suite_id, pa_id, **overrides):
    return get_success_data(
        api_client.create_procedure(
            clinic_id, patient_id, create_procedure_payload(plan_id, suite_id, pa_id, **overrides), INTAKE
        )
    )


def schedule_procedure_with_current_version(clinic_id, patient_id, procedure_id):
    """Read the clinic version, then schedule the procedure with it. Returns scheduled procedure."""
    clinic = get_success_data(api_client.get_clinic(clinic_id, ADMIN))
    return get_success_data(
        api_client.schedule_procedure(
            clinic_id, patient_id, procedure_id, {"expected_clinic_version": clinic["version"]}, INTAKE
        )
    )


def setup_scheduled_procedure(clock_utc: str = "2026-06-01T00:00:00Z", duration_minutes: int = 30,
                              start_utc: str = "2026-06-10T10:00:00Z"):
    """Active procedure-path patient with one SCHEDULED procedure in a suite.

    Build the patient/procedure at the clinic's startup default clock (so intake
    scheduling satisfies `intake_utc >= current_utc`), then advance the clinic's
    logical clock to ``clock_utc`` as a final step. This lets callers request a
    ``clock_utc`` at or after ``start_utc`` (needed to complete the procedure)
    without tripping ERR_INTAKE_IN_PAST during setup.

    Returns dict: clinic, prescriber, patient, plan, suite, procedure, pa.
    """
    ctx = setup_active_procedure_patient(clock_utc=None, intake_utc="2026-05-01T00:00:00Z")
    pa = create_approved_procedure_pa(ctx["clinic"]["id"], ctx["patient"]["id"])
    proc = request_procedure(
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["plan"]["id"], ctx["suite"]["id"], pa["id"],
        start_utc=start_utc, duration_minutes=duration_minutes,
    )
    scheduled = schedule_procedure_with_current_version(ctx["clinic"]["id"], ctx["patient"]["id"], proc["id"])
    if clock_utc is not None:
        set_clock(ctx["clinic"]["id"], clock_utc)
        ctx["clinic"] = get_success_data(api_client.get_clinic(ctx["clinic"]["id"], ADMIN))
    ctx["procedure"] = scheduled
    ctx["pa"] = pa
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: urine drug screen progression
# ---------------------------------------------------------------------------
def schedule_uds(clinic_id, patient_id, co_id, **overrides):
    co_h = make_compliance_officer_headers(co_id)
    return get_success_data(
        api_client.create_urine_drug_screen(clinic_id, patient_id, create_urine_drug_screen_payload(**overrides), co_h)
    )


def collect_uds(clinic_id, patient_id, uds_id):
    return get_success_data(api_client.collect_urine_drug_screen(clinic_id, patient_id, uds_id, INTAKE))


def setup_collected_uds(expected_substances, clock_utc="2026-06-01T00:00:00Z", due_utc="2026-06-01T00:00:00Z"):
    """Active patient with one COLLECTED urine drug screen.

    Returns dict: clinic, prescriber, compliance_officer, patient, plan, uds.
    """
    ctx = setup_active_medication_patient(clock_utc=clock_utc, intake_utc="2026-06-01T00:00:00Z")
    uds = schedule_uds(
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["compliance_officer"]["id"],
        due_utc=due_utc, expected_substances=expected_substances,
    )
    collect_uds(ctx["clinic"]["id"], ctx["patient"]["id"], uds["id"])
    ctx["uds"] = uds
    return ctx
