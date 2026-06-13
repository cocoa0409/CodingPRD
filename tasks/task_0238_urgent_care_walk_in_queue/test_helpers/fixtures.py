"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures. Every
helper builds its preconditions from scratch (the server starts each test against
an empty database).

Provider is an entity-backed role: ownership-gated Provider calls (rooming,
charting, charges, transfer, occ start/result) thread make_provider_headers
with the acting Provider's id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_clinic_payload, create_exam_room_payload, create_provider_payload,
    create_queue_entry_payload, triage_payload, create_patient_payload,
    create_coverage_payload, create_visit_payload, create_charge_payload,
    verify_payload, set_clock_payload, seed_queue_depth_payload,
)
from .test_users import TEST_USERS, make_provider_headers


# ─── Header shortcuts ─────────────────────────────────────────────────
_ANON = TEST_USERS["anonymous_headers"]
_MGR = TEST_USERS["clinic_manager_headers"]
_CLERK = TEST_USERS["front_desk_headers"]
_NURSE = TEST_USERS["triage_nurse_headers"]


def set_clock(to_iso8601):
    """Pin the server clock to a fixed instant."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), _ANON))


# ─── Tier 1: primitive creates ────────────────────────────────────────

def create_clinic(**overrides):
    """Create a clinic. Returns the clinic object (posture OPEN, depth 0)."""
    res = api_client.create_clinic(create_clinic_payload(**overrides), _ANON)
    return get_success_data(res)


def create_exam_room(clinic_id, **overrides):
    res = api_client.create_exam_room(clinic_id, create_exam_room_payload(**overrides), _MGR)
    return get_success_data(res)


def create_provider(clinic_id, **overrides):
    res = api_client.create_provider(clinic_id, create_provider_payload(**overrides), _MGR)
    return get_success_data(res)


def create_walk_in(clinic_id, chief_complaint="walk-in", headers=None):
    """Create a WALK_IN queue entry (born WAITING)."""
    res = api_client.create_queue_entry(
        clinic_id,
        create_queue_entry_payload(arrival_channel="WALK_IN", chief_complaint=chief_complaint),
        headers or _CLERK,
    )
    return get_success_data(res)


def create_online_reservation(clinic_id, chief_complaint="save-spot"):
    """Create an ONLINE queue entry (born RESERVED) as the Patient self-service role."""
    res = api_client.create_queue_entry(
        clinic_id,
        create_queue_entry_payload(arrival_channel="ONLINE", chief_complaint=chief_complaint),
        TEST_USERS["patient_headers"],
    )
    return get_success_data(res)


def triage(clinic_id, queue_entry_id, esi_level=3, **overrides):
    res = api_client.triage_queue_entry(
        clinic_id, queue_entry_id, triage_payload(esi_level=esi_level, **overrides), _NURSE)
    return get_success_data(res)


def get_clinic_version(clinic_id, headers=None):
    """Read the clinic's current version (for the rooming OCC echo)."""
    clinic = get_success_data(api_client.get_clinic(clinic_id, headers or _MGR))
    return clinic["version"]


# ─── Tier 2: registration progression ─────────────────────────────────

def create_triaged_entry(clinic_id, esi_level=3, chief_complaint="visit", **triage_overrides):
    """Walk-in -> triaged. Returns the queue entry in TRIAGED."""
    qe = create_walk_in(clinic_id, chief_complaint=chief_complaint)
    return triage(clinic_id, qe["id"], esi_level=esi_level, **triage_overrides)


def register_patient(queue_entry_id, legal_name="Test Patient",
                     date_of_birth="1990-01-01", consent_signed=True, **overrides):
    """Register a patient against a TRIAGED queue entry (-> IN_REGISTRATION)."""
    res = api_client.create_patient(
        create_patient_payload(
            queue_entry_id, legal_name=legal_name, date_of_birth=date_of_birth,
            consent_signed=consent_signed, **overrides),
        _CLERK,
    )
    return get_success_data(res)


def attach_coverage(patient_id, coverage_type="SELF_PAY", **overrides):
    res = api_client.create_coverage(
        create_coverage_payload(patient_id, coverage_type=coverage_type, **overrides), _CLERK)
    return get_success_data(res)


def verify_coverage(coverage_id, outcome="ELIGIBLE"):
    res = api_client.verify_coverage(coverage_id, verify_payload(outcome=outcome), _CLERK)
    return get_success_data(res)


def mark_ready(clinic_id, queue_entry_id):
    res = api_client.mark_ready_queue_entry(clinic_id, queue_entry_id, _CLERK)
    return get_success_data(res)


def setup_ready_entry(clinic_id, esi_level=3, coverage_type="SELF_PAY",
                      coverage_overrides=None, verify_outcome=None,
                      patient_overrides=None, triage_overrides=None):
    """Create a fully-registered READY_FOR_PROVIDER queue entry under an existing clinic.

    Sequence: walk-in -> triage -> register patient (consent) -> attach coverage
    -> (optional verify) -> mark-ready. Returns dict with queue_entry, patient,
    coverage.
    """
    qe = create_triaged_entry(clinic_id, esi_level=esi_level, **(triage_overrides or {}))
    patient = register_patient(qe["id"], **(patient_overrides or {}))
    coverage = attach_coverage(patient["id"], coverage_type=coverage_type,
                               **(coverage_overrides or {}))
    if verify_outcome is not None:
        coverage = verify_coverage(coverage["id"], outcome=verify_outcome)
    mark_ready(clinic_id, qe["id"])
    return {"queue_entry": qe, "patient": patient, "coverage": coverage}


# ─── Tier 3: rooming / visit lifecycle ────────────────────────────────

def room_visit(clinic_id, queue_entry_id, provider_id, exam_room_id, **overrides):
    """Room a READY_FOR_PROVIDER entry, creating the Visit (clinical IN_EXAM,
    billing OPEN). Reads the live clinic version for the OCC echo."""
    cv = get_clinic_version(clinic_id, make_provider_headers(provider_id))
    res = api_client.create_visit(
        create_visit_payload(queue_entry_id, provider_id, exam_room_id, cv, **overrides),
        make_provider_headers(provider_id),
    )
    return get_success_data(res)


def setup_roomed_visit(esi_level=3, coverage_type="SELF_PAY", coverage_overrides=None,
                       verify_outcome=None, room_overrides=None, provider_overrides=None,
                       clinic_overrides=None, patient_overrides=None, triage_overrides=None):
    """Full path to a roomed Visit (clinical IN_EXAM, billing OPEN).

    Builds: clinic -> exam room -> provider -> triaged walk-in -> registered
    patient + coverage (+ optional verify) -> mark-ready -> room.

    Returns dict: clinic, room, provider, queue_entry, patient, coverage, visit.
    """
    clinic = create_clinic(**(clinic_overrides or {}))
    room = create_exam_room(clinic["id"], **(room_overrides or {}))
    provider = create_provider(clinic["id"], **(provider_overrides or {}))
    ready = setup_ready_entry(
        clinic["id"], esi_level=esi_level, coverage_type=coverage_type,
        coverage_overrides=coverage_overrides, verify_outcome=verify_outcome,
        patient_overrides=patient_overrides, triage_overrides=triage_overrides)
    visit = room_visit(clinic["id"], ready["queue_entry"]["id"], provider["id"], room["id"])
    return {
        "clinic": clinic,
        "room": room,
        "provider": provider,
        "queue_entry": ready["queue_entry"],
        "patient": ready["patient"],
        "coverage": ready["coverage"],
        "visit": visit,
    }


def add_charge(visit_id, provider_id, cpt_code="99213", amount_cents=10000, **overrides):
    res = api_client.create_charge(
        visit_id, create_charge_payload(cpt_code=cpt_code, amount_cents=amount_cents, **overrides),
        make_provider_headers(provider_id))
    return get_success_data(res)


def setup_visit_with_charges(amounts, source_types=None, esi_level=3,
                             coverage_type="SELF_PAY", coverage_overrides=None,
                             verify_outcome=None, clinic_overrides=None):
    """Roomed Visit (billing OPEN) with one charge per entry in `amounts`.

    `source_types` (optional) is a parallel list of "VISIT"/"OCC_HEALTH" labels.
    Returns the setup_roomed_visit dict plus a "charges" list.
    """
    setup = setup_roomed_visit(
        esi_level=esi_level, coverage_type=coverage_type,
        coverage_overrides=coverage_overrides, verify_outcome=verify_outcome,
        clinic_overrides=clinic_overrides)
    charges = []
    for i, amt in enumerate(amounts):
        extra = {}
        if source_types is not None:
            extra["source_type"] = source_types[i]
        charges.append(add_charge(setup["visit"]["id"], setup["provider"]["id"],
                                  cpt_code=f"C{i}", amount_cents=amt, **extra))
    setup["charges"] = charges
    return setup


def post_charges(visit_id, provider_id):
    res = api_client.post_charges(visit_id, make_provider_headers(provider_id))
    return get_success_data(res)


def invoice_visit(visit_id):
    res = api_client.invoice_visit(visit_id, _CLERK)
    return get_success_data(res)


def setup_invoiced_visit(amount_cents=9000, coverage_type="SELF_PAY",
                         coverage_overrides=None, verify_outcome=None):
    """Roomed Visit driven to billing INVOICED. Returns setup dict plus the
    invoiced visit object (so the caller has the frozen version for settle)."""
    setup = setup_visit_with_charges(
        [amount_cents], coverage_type=coverage_type,
        coverage_overrides=coverage_overrides, verify_outcome=verify_outcome)
    post_charges(setup["visit"]["id"], setup["provider"]["id"])
    invoiced = invoice_visit(setup["visit"]["id"])
    setup["invoiced_visit"] = invoiced
    return setup
