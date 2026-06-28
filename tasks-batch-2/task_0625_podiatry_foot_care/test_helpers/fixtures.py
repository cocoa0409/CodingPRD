"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing downstream assertions.

The harness restarts the server (empty DB) before every test, so every helper
builds its preconditions from scratch using only PRD-declared endpoints. The
Podiatrist role is entity-backed: ownership-gated calls (complete-exam) thread
the rendering Provider.id through make_podiatrist_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_practice_payload, create_provider_payload, create_modality_payload,
    create_patient_payload, create_prior_authorization_payload,
    create_encounter_payload, create_procedure_payload, create_orthotic_rx_payload,
    create_lab_order_payload, create_dme_dispense_payload,
)
from .test_users import TEST_USERS, make_podiatrist_headers


ADMIN = TEST_USERS["practice_admin_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
FRONTDESK = TEST_USERS["front_desk_headers"]
PAYER = TEST_USERS["payer_agent_headers"]


# ─── Logical clock ─────────────────────────────────────────────────────────
def set_clock(iso8601: str):
    """Move the logical clock to an absolute instant (as PracticeAdmin)."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# ─── Tier 0: Backbone provisioning ─────────────────────────────────────────
def create_practice(**overrides) -> dict:
    return get_success_data(api_client.create_practice(create_practice_payload(**overrides), ADMIN))


def create_provider(practice_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_provider(create_provider_payload(practice_id, **overrides), ADMIN))


def create_modality(practice_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_modality(create_modality_payload(practice_id, **overrides), ADMIN))


def create_patient(practice_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_patient(create_patient_payload(practice_id, **overrides), FRONTDESK))


def create_encounter(patient_id: str, provider_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_encounter(
        create_encounter_payload(patient_id, provider_id, **overrides), FRONTDESK))


def setup_practice_provider_patient(patient_overrides=None, provider_overrides=None):
    """Practice + one provider + one patient. Returns (practice, provider, patient)."""
    practice = create_practice()
    provider = create_provider(practice["id"], **(provider_overrides or {}))
    patient = create_patient(practice["id"], **(patient_overrides or {}))
    return practice, provider, patient


# ─── Tier 1: Prior-authorization state progression ────────────────────────
def create_approved_pa(patient_id: str, **overrides) -> dict:
    """Request + approve a PA. Returns the APPROVED PriorAuthorization."""
    pa = get_success_data(api_client.create_prior_authorization(
        create_prior_authorization_payload(patient_id, **overrides), BILLING))
    return get_success_data(api_client.approve_prior_authorization(pa["id"], PAYER))


def create_requested_pa(patient_id: str, **overrides) -> dict:
    """Request a PA, leaving it in REQUESTED."""
    return get_success_data(api_client.create_prior_authorization(
        create_prior_authorization_payload(patient_id, **overrides), BILLING))


def create_denied_pa(patient_id: str, **overrides) -> dict:
    """Request + deny a PA. Returns the DENIED PriorAuthorization."""
    pa = get_success_data(api_client.create_prior_authorization(
        create_prior_authorization_payload(patient_id, **overrides), BILLING))
    return get_success_data(api_client.deny_prior_authorization(pa["id"], PAYER))


# ─── Tier 2: Encounter lifecycle progression ──────────────────────────────
def add_procedure(encounter_id: str, **overrides) -> dict:
    """Add a procedure line (Podiatrist; not ownership-gated per PRD §3.4)."""
    return get_success_data(api_client.create_procedure(
        create_procedure_payload(encounter_id, **overrides),
        TEST_USERS["podiatrist_headers"]))


def complete_exam(encounter_id: str, provider_id: str) -> dict:
    """Complete the exam as the rendering provider (ownership-gated)."""
    return get_success_data(
        api_client.complete_exam(encounter_id, make_podiatrist_headers(provider_id)))


def code_encounter(encounter_id: str) -> dict:
    return get_success_data(api_client.code_encounter(encounter_id, BILLING))


def submit_encounter(encounter_id: str) -> dict:
    return get_success_data(api_client.submit_encounter(encounter_id, BILLING))


def adjudicate_encounter(encounter_id: str) -> dict:
    return get_success_data(api_client.adjudicate_encounter(encounter_id, PAYER))


def setup_encounter_in_exam_done(patient_id, provider_id, encounter_overrides=None,
                                 procedure_overrides=None):
    """Encounter walked to EXAM_DONE, optionally with one procedure line.

    Returns (encounter, procedure_or_None).
    """
    enc = create_encounter(patient_id, provider_id, **(encounter_overrides or {}))
    proc = None
    if procedure_overrides is not None:
        proc = add_procedure(enc["id"], **procedure_overrides)
    complete_exam(enc["id"], provider_id)
    enc = get_success_data(api_client.get_encounter(enc["id"], FRONTDESK))
    return enc, proc


def setup_coded_encounter(patient_id, provider_id, encounter_overrides=None,
                          procedure_overrides=None):
    """Encounter walked to CODED, optionally with one procedure. Returns (encounter, proc)."""
    enc, proc = setup_encounter_in_exam_done(
        patient_id, provider_id, encounter_overrides, procedure_overrides)
    coded = code_encounter(enc["id"])
    if proc is not None:
        proc = get_success_data(api_client.get_procedure(proc["id"], FRONTDESK))
    return coded, proc


def setup_adjudicated_encounter(patient_id, provider_id, encounter_overrides=None,
                                procedure_overrides=None):
    """Drive an encounter fully to ADJUDICATED. Returns (encounter, proc)."""
    coded, proc = setup_coded_encounter(
        patient_id, provider_id, encounter_overrides, procedure_overrides)
    submit_encounter(coded["id"])
    adj = adjudicate_encounter(coded["id"])
    if proc is not None:
        proc = get_success_data(api_client.get_procedure(proc["id"], FRONTDESK))
    return adj, proc


def establish_last_covered_routine_date(patient_id, provider_id, covered_date,
                                        clock_iso=None):
    """Adjudicate a covered routine encounter so the patient's
    last_covered_routine_care_date advances to `covered_date` (YYYY-MM-DD).

    Patient must already be diabetic with no closer prior covered routine care.
    `clock_iso` (optional) sets the logical clock before scheduling. Returns the
    adjudicated encounter.
    """
    if clock_iso is not None:
        set_clock(clock_iso)
    start = f"{covered_date}T09:00:00Z"
    end = f"{covered_date}T09:30:00Z"
    adj, _ = setup_adjudicated_encounter(
        patient_id, provider_id,
        encounter_overrides={"scheduled_start": start, "scheduled_end": end},
        procedure_overrides={"procedure_kind": "ROUTINE_NAIL_DEBRIDEMENT",
                             "service_date": covered_date,
                             "billed_cents": 8000, "fee_cap_cents": 7000},
    )
    return adj


# ─── Tier 3: Orthotic Rx lifecycle ─────────────────────────────────────────
def create_draft_rx(encounter_id, provider_id, prior_authorization_id, **overrides) -> dict:
    """Create an OrthoticRx in DRAFT (Podiatrist; not ownership-gated per PRD §3.7)."""
    return get_success_data(api_client.create_orthotic_rx(
        create_orthotic_rx_payload(encounter_id, prior_authorization_id, **overrides),
        TEST_USERS["podiatrist_headers"]))


def create_approved_rx(encounter_id, provider_id, prior_authorization_id, **overrides) -> dict:
    """DRAFT -> PENDING_PA -> APPROVED. Linked PA must be ORTHOTIC + APPROVED. Returns Rx."""
    rx = create_draft_rx(encounter_id, provider_id, prior_authorization_id, **overrides)
    get_success_data(api_client.submit_orthotic_rx_to_payer(
        rx["id"], TEST_USERS["podiatrist_headers"]))
    return get_success_data(api_client.orthotic_rx_payer_decision(
        rx["id"], {"decision": "APPROVE"}, PAYER))


def create_pending_pa_rx(encounter_id, provider_id, prior_authorization_id, **overrides) -> dict:
    """DRAFT -> PENDING_PA (submitted to payer, no decision yet). Returns Rx."""
    rx = create_draft_rx(encounter_id, provider_id, prior_authorization_id, **overrides)
    return get_success_data(api_client.submit_orthotic_rx_to_payer(
        rx["id"], TEST_USERS["podiatrist_headers"]))


# ─── Tier 4: Lab order lifecycle ───────────────────────────────────────────
def create_lab_order(orthotic_rx_id, **overrides) -> dict:
    return get_success_data(api_client.create_lab_order(
        create_lab_order_payload(orthotic_rx_id, **overrides), BILLING))


def create_shipped_lab_order(orthotic_rx_id, **overrides) -> dict:
    lab = create_lab_order(orthotic_rx_id, **overrides)
    return get_success_data(api_client.ship_lab_order(lab["id"], BILLING))


def setup_approved_rx_with_shipped_lab(patient_overrides=None, pa_overrides=None,
                                       lab_overrides=None):
    """Full orthotic chain to an APPROVED Rx with a SHIPPED LabOrder.

    Returns (practice, provider, patient, pa, encounter, rx, lab_order).
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides=patient_overrides or {"has_diabetes_mellitus": True})
    pa = create_approved_pa(patient["id"],
                            **(pa_overrides or {"service_category": "ORTHOTIC",
                                                "hcpcs_code": "L3000",
                                                "authorized_units": 3}))
    enc = create_encounter(patient["id"], provider["id"])
    rx = create_approved_rx(enc["id"], provider["id"], pa["id"])
    lab = create_shipped_lab_order(rx["id"], **(lab_overrides or {}))
    return practice, provider, patient, pa, enc, rx, lab


# ─── Tier 5: DME dispense lifecycle and accumulation ───────────────────────
def dispense_dme(prior_authorization_id, encounter_id, pa_version, **overrides) -> dict:
    return get_success_data(api_client.create_dme_dispense(
        create_dme_dispense_payload(prior_authorization_id, encounter_id, pa_version, **overrides),
        FRONTDESK))


def setup_dme_pa_and_encounter(patient_overrides=None, pa_overrides=None,
                               clock_iso="2026-06-01T09:00:00Z"):
    """Approved DME PA + an OPEN encounter on the same patient.

    Returns (practice, provider, patient, pa, encounter).
    """
    set_clock(clock_iso)
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides=patient_overrides or {"has_diabetes_mellitus": True})
    pa = create_approved_pa(patient["id"], **(pa_overrides or {"service_category": "DME",
                                                               "hcpcs_code": "L4360",
                                                               "authorized_units": 2}))
    enc = create_encounter(patient["id"], provider["id"])
    return practice, provider, patient, pa, enc


def setup_rental_accumulated_to_cap_minus_one(monthly_rental=5000, purchase_price=30000,
                                              prior_rental_periods=5):
    """Make N prior RENTAL dispenses for the same hcpcs_code under one DME PA so
    cumulative rental approaches the purchase-price cap.

    With monthly_rental=5000, purchase_price=30000, prior_rental_periods=5, the
    cumulative rental reaches 25000 (one 5000 period short of the 30000 cap).
    Each dispense bumps PA.version; the live version is re-read between draws.

    Returns (pa, encounter, current_pa_version).
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"has_diabetes_mellitus": True})
    # Need at least prior_rental_periods + 1 authorized units for follow-on draws.
    pa = create_approved_pa(patient["id"], service_category="DME", hcpcs_code="L4360",
                            authorized_units=prior_rental_periods + 1,
                            valid_from_date="2026-01-01", valid_through_date="2026-12-31")
    enc = create_encounter(patient["id"], provider["id"])
    pa_version = pa["version"]
    for _ in range(prior_rental_periods):
        dispense_dme(pa["id"], enc["id"], pa_version,
                     hcpcs_code="L4360", acquisition_mode="RENTAL", units=1,
                     purchase_price_cents=purchase_price, monthly_rental_cents=monthly_rental)
        live = get_success_data(api_client.get_prior_authorization(pa["id"], FRONTDESK))
        pa_version = live["version"]
    return pa, enc, pa_version


# ─── Tier 6: Imaging / modality ────────────────────────────────────────────
def setup_modality_with_scheduled_study(study_start, study_end, cleanup_buffer_minutes=15,
                                        clock_iso="2026-06-02T08:00:00Z"):
    """A modality holding one SCHEDULED imaging study.

    Returns (practice, provider, patient, modality, encounter, imaging_order,
    current_modality_version).
    """
    from .factories import create_imaging_order_payload
    set_clock(clock_iso)
    practice, provider, patient = setup_practice_provider_patient()
    modality = create_modality(practice["id"], cleanup_buffer_minutes=cleanup_buffer_minutes)
    enc = create_encounter(
        patient["id"], provider["id"],
        scheduled_start="2026-06-02T08:30:00Z", scheduled_end="2026-06-02T08:55:00Z")
    img = get_success_data(api_client.create_imaging_order(
        create_imaging_order_payload(enc["id"], modality["id"], modality["version"],
                                     study_start=study_start, study_end=study_end),
        make_podiatrist_headers(provider["id"])))
    live = get_success_data(api_client.get_modality(modality["id"], FRONTDESK))
    return practice, provider, patient, modality, enc, img, live["version"]
