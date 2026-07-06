"""Composite setup helpers.

Every fixture builds its preconditions from scratch (the server DB is empty at
the start of every test). Fixtures use get_success_data() (lenient) internally
so setup failures surface as clear "Setup failed" errors.

Identity threading: WoundClinician / HyperbaricTech calls that record or consult
clinician provenance pass the actual Clinician.id via make_*_headers(id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_wound_clinician_headers,
    make_hyperbaric_tech_headers,
    make_attending_physician_headers,
)
from . import factories


# --- header shortcuts ---
INTAKE = TEST_USERS["intake_coordinator_headers"]
PAYER = TEST_USERS["payer_liaison_headers"]
ATTENDING = TEST_USERS["attending_physician_headers"]


# =============================================================================
# Primitive creators (return the created data dict)
# =============================================================================

def create_center(name="Test Center"):
    resp = api_client.create_center(factories.create_center_payload(name=name), INTAKE)
    return get_success_data(resp)


def create_clinician(center_id, role_kind="WOUND", name="Dr Wound", active=None):
    payload = factories.create_clinician_payload(center_id, role_kind=role_kind, name=name)
    if active is not None:
        payload["active"] = active
    resp = api_client.create_clinician(payload, INTAKE)
    return get_success_data(resp)


def create_chamber(center_id, label="CH1", turnover_buffer_minutes=None):
    kwargs = {}
    if turnover_buffer_minutes is not None:
        kwargs["turnover_buffer_minutes"] = turnover_buffer_minutes
    resp = api_client.create_chamber(
        factories.create_chamber_payload(center_id, label=label, **kwargs), INTAKE)
    return get_success_data(resp)


def create_payer_policy(center_id, **overrides):
    resp = api_client.create_payer_policy(
        factories.create_payer_policy_payload(center_id, **overrides), PAYER)
    return get_success_data(resp)


def create_patient(center_id, payer_policy_id, mrn="MRN-1", full_name="Test Patient"):
    resp = api_client.create_patient(
        factories.create_patient_payload(center_id, payer_policy_id, mrn=mrn,
                                         full_name=full_name), INTAKE)
    return get_success_data(resp)


def set_clock(center_id, to_iso8601, wc_id):
    resp = api_client.set_clock(center_id, to_iso8601, make_wound_clinician_headers(wc_id))
    return get_success_data(resp)


def record_assessment(patient_id, wc_id, **overrides):
    resp = api_client.create_wound_assessment(
        factories.create_wound_assessment_payload(patient_id, **overrides),
        make_wound_clinician_headers(wc_id))
    return get_success_data(resp)


def get_plan_version(plan_id, headers):
    resp = api_client.get_treatment_plan(plan_id, headers)
    return get_success_data(resp)["version"]


# =============================================================================
# Tier 1/2: Base setup — center + wound clinician + policy + patient
# =============================================================================

def setup_center_staff_patient(mrn="M", full_name="P", with_hyperbaric=False,
                               policy_overrides=None):
    """Center + WOUND clinician + (optional HYPERBARIC clinician) + payer policy
    + patient (still INTAKE). Returns a dict of ids and entities.
    """
    center = create_center()
    wc = create_clinician(center["id"], role_kind="WOUND", name="Dr W")
    ht = None
    if with_hyperbaric:
        ht = create_clinician(center["id"], role_kind="HYPERBARIC", name="Tech H")
    policy = create_payer_policy(center["id"], **(policy_overrides or {}))
    patient = create_patient(center["id"], policy["id"], mrn=mrn, full_name=full_name)
    return {
        "center": center,
        "center_id": center["id"],
        "wc": wc,
        "wc_id": wc["id"],
        "ht": ht,
        "ht_id": ht["id"] if ht else None,
        "policy": policy,
        "policy_id": policy["id"],
        "patient": patient,
        "patient_id": patient["id"],
    }


def accept_patient_into_care(patient_id, wc_id):
    """Record a baseline assessment, create + accept a referral so the patient
    advances INTAKE -> IN_CARE. Returns the baseline assessment id."""
    asm = record_assessment(patient_id, wc_id)
    ref = get_success_data(api_client.create_referral(
        factories.create_referral_payload(patient_id), INTAKE))
    get_success_data(api_client.accept_referral(ref["id"], INTAKE))
    return asm["id"]


# =============================================================================
# Tier 1/3: Treatment plan progression
# =============================================================================

def create_draft_plan(patient_id, wc_id, baseline_assessment_id, budget_cents=500000):
    resp = api_client.create_treatment_plan(
        factories.create_treatment_plan_payload(
            patient_id, baseline_assessment_id,
            debridement_supply_budget_cents=budget_cents),
        make_wound_clinician_headers(wc_id))
    return get_success_data(resp)


def activate_plan(plan_id, wc_id):
    resp = api_client.activate_treatment_plan(plan_id, make_wound_clinician_headers(wc_id))
    return get_success_data(resp)


def approve_coverage(plan_id, requested_hbo_sessions=4):
    """Submit + approve a prior authorization -> plan coverage COVERED.
    Returns the auth data."""
    auth = get_success_data(api_client.create_prior_authorization(
        factories.create_prior_authorization_payload(
            plan_id, requested_hbo_sessions=requested_hbo_sessions), PAYER))
    get_success_data(api_client.approve_prior_authorization(auth["id"], PAYER))
    return auth


def setup_active_plan(budget_cents=500000, mrn="M", with_hyperbaric=False,
                      covered=False, policy_overrides=None):
    """Center/staff/patient -> IN_CARE -> DRAFT plan -> (optional coverage) ->
    ACTIVE plan. Returns the base dict extended with plan/baseline ids.
    """
    base = setup_center_staff_patient(
        mrn=mrn, with_hyperbaric=with_hyperbaric, policy_overrides=policy_overrides)
    baseline_id = accept_patient_into_care(base["patient_id"], base["wc_id"])
    plan = create_draft_plan(base["patient_id"], base["wc_id"], baseline_id,
                             budget_cents=budget_cents)
    if covered:
        approve_coverage(plan["id"])
    plan = activate_plan(plan["id"], base["wc_id"])
    base["baseline_assessment_id"] = baseline_id
    base["plan"] = plan
    base["plan_id"] = plan["id"]
    return base


def setup_draft_plan(budget_cents=500000, mrn="M", accept_into_care=True):
    """Center/staff/patient with a DRAFT plan (optionally patient IN_CARE).
    Returns base dict extended with plan/baseline ids.
    """
    base = setup_center_staff_patient(mrn=mrn)
    if accept_into_care:
        baseline_id = accept_patient_into_care(base["patient_id"], base["wc_id"])
    else:
        # baseline assessment still required to open a plan, but skip referral accept
        asm = record_assessment(base["patient_id"], base["wc_id"])
        baseline_id = asm["id"]
    plan = create_draft_plan(base["patient_id"], base["wc_id"], baseline_id,
                             budget_cents=budget_cents)
    base["baseline_assessment_id"] = baseline_id
    base["plan"] = plan
    base["plan_id"] = plan["id"]
    return base


# =============================================================================
# Tier 3/4: HBO session helpers
# =============================================================================

def setup_active_covered_plan_with_chamber(budget_cents=500000, mrn="M",
                                           turnover_buffer_minutes=30,
                                           policy_overrides=None):
    """Full: center + WOUND + HYPERBARIC clinicians + chamber + patient IN_CARE
    + plan ACTIVE + COVERED. Returns base dict with chamber added.
    """
    base = setup_active_plan(
        budget_cents=budget_cents, mrn=mrn, with_hyperbaric=True, covered=True,
        policy_overrides=policy_overrides)
    chamber = create_chamber(base["center_id"], turnover_buffer_minutes=turnover_buffer_minutes)
    base["chamber"] = chamber
    base["chamber_id"] = chamber["id"]
    return base


def schedule_hbo_session(plan_id, chamber_id, ht_id, window_start="2026-05-02T09:00:00Z",
                         window_end="2026-05-02T10:00:00Z", expected_plan_version=None):
    """Schedule an HBO session. Reads the plan version fresh unless supplied."""
    ht_headers = make_hyperbaric_tech_headers(ht_id)
    if expected_plan_version is None:
        expected_plan_version = get_plan_version(plan_id, ht_headers)
    resp = api_client.create_hbo_session(
        factories.create_hbo_session_payload(
            plan_id, chamber_id, expected_plan_version,
            window_start=window_start, window_end=window_end),
        ht_headers)
    return get_success_data(resp)


def complete_hbo_session(session_id, ht_id, dive_log_entries=None):
    if dive_log_entries is None:
        dive_log_entries = [{"minute": 0, "spo2": 98, "hr": 72}]
    resp = api_client.complete_hbo_session(
        session_id, {"dive_log_entries": dive_log_entries},
        make_hyperbaric_tech_headers(ht_id))
    return get_success_data(resp)


# =============================================================================
# Tier 3: Debridement helpers
# =============================================================================

def schedule_debridement(plan_id, clinician_id, wc_id,
                         window_start="2026-05-02T09:00:00Z",
                         window_end="2026-05-02T10:00:00Z"):
    resp = api_client.create_debridement_procedure(
        factories.create_debridement_procedure_payload(
            plan_id, clinician_id, window_start=window_start, window_end=window_end),
        make_wound_clinician_headers(wc_id))
    return get_success_data(resp)


# =============================================================================
# Tier 3: Supply order helper
# =============================================================================

def submit_supply_order(plan_id, wc_id, line_items=None, supply_kind="ADVANCED_DRESSING",
                        expected_plan_version=None):
    wc_headers = make_wound_clinician_headers(wc_id)
    if expected_plan_version is None:
        expected_plan_version = get_plan_version(plan_id, wc_headers)
    if line_items is None:
        line_items = factories.THREE_LINES_153
    resp = api_client.create_supply_order(
        factories.create_supply_order_payload(
            plan_id, expected_plan_version, supply_kind=supply_kind,
            line_items=line_items),
        wc_headers)
    return get_success_data(resp)


# =============================================================================
# Tier 3: Acute transfer helper
# =============================================================================

def initiate_transfer(patient_id, attending_user_id=None):
    """Initiate an acute transfer. If attending_user_id supplied, threads it as
    X-User-ID (for the segregation-of-duties scenario); otherwise uses the
    shared opaque attending header."""
    if attending_user_id is not None:
        headers = make_attending_physician_headers(attending_user_id)
    else:
        headers = ATTENDING
    resp = api_client.create_acute_transfer(
        factories.create_acute_transfer_payload(patient_id), headers)
    return get_success_data(resp)
