"""Composite setup helpers for multi-step test prerequisites (Vital Records).

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: FacilityFiler and MedicalCertifier are entity_backed roles.
Any ownership-gated call is issued with make_facility_filer_headers(facility_id)
or make_medical_certifier_headers(certifier_id) — never the shared fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_facility_payload,
    create_certifier_payload,
    create_vital_event_payload,
    create_certification_payload,
    create_amendment_payload,
    create_paternity_payload,
    create_copy_request_payload,
    create_apostille_payload,
    create_packet_payload,
    create_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_facility_filer_headers,
    make_medical_certifier_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]
APPLICANT = TEST_USERS["applicant_headers"]


# ─── Clock ──────────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Move the logical clock (StateRegistrar-only, PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, REGISTRAR))


# ─── Single-step building blocks ────────────────────────────────────────
def create_facility(**overrides):
    return get_success_data(
        api_client.create_facility(create_facility_payload(**overrides), REGISTRAR)
    )


def create_certifier(**overrides):
    return get_success_data(
        api_client.create_certifier(create_certifier_payload(**overrides), REGISTRAR)
    )


def create_vital_event(facility_id, **overrides):
    """FacilityFiler owning `facility_id` drafts a vital event."""
    headers = make_facility_filer_headers(facility_id)
    return get_success_data(
        api_client.create_vital_event(
            create_vital_event_payload(facility_id, **overrides), headers
        )
    )


def file_event(event_id, facility_id):
    headers = make_facility_filer_headers(facility_id)
    return get_success_data(api_client.file_vital_event(event_id, headers))


def register_event(event_id):
    return get_success_data(api_client.register_vital_event(event_id, REGISTRAR))


def return_event(event_id):
    return get_success_data(api_client.return_vital_event(event_id, REGISTRAR))


def void_event(event_id):
    return get_success_data(api_client.void_vital_event(event_id, REGISTRAR))


def create_certification(vital_event_id, certifier_id, **overrides):
    headers = make_medical_certifier_headers(certifier_id)
    return get_success_data(
        api_client.create_certification(
            create_certification_payload(vital_event_id, certifier_id, **overrides),
            headers,
        )
    )


def certify(cert_id, certifier_id):
    headers = make_medical_certifier_headers(certifier_id)
    return get_success_data(api_client.certify_certification(cert_id, headers))


def create_amendment(vital_event_id, **overrides):
    return get_success_data(
        api_client.create_amendment(
            create_amendment_payload(vital_event_id, **overrides), REGISTRAR
        )
    )


def submit_amendment(amendment_id):
    return get_success_data(api_client.submit_amendment(amendment_id, REGISTRAR))


def approve_amendment(amendment_id, expected_vital_event_version):
    return get_success_data(
        api_client.approve_amendment(
            amendment_id,
            {"expected_vital_event_version": expected_vital_event_version},
            REGISTRAR,
        )
    )


def reject_amendment(amendment_id):
    return get_success_data(api_client.reject_amendment(amendment_id, REGISTRAR))


def create_paternity(vital_event_id, **overrides):
    return get_success_data(
        api_client.create_paternity(
            create_paternity_payload(vital_event_id, **overrides), APPLICANT
        )
    )


def acknowledge_paternity(pa_id):
    return get_success_data(api_client.acknowledge_paternity(pa_id, REGISTRAR))


def create_copy_request(vital_event_id, **overrides):
    return get_success_data(
        api_client.create_copy_request(
            create_copy_request_payload(vital_event_id, **overrides), APPLICANT
        )
    )


def verify_copy(copy_id):
    return get_success_data(api_client.verify_id_copy_request(copy_id, REGISTRAR))


def issue_copy(copy_id, expected_vital_event_version):
    return get_success_data(
        api_client.issue_copy_request(
            copy_id,
            {"expected_vital_event_version": expected_vital_event_version},
            REGISTRAR,
        )
    )


def create_apostille(certified_copy_request_id, **overrides):
    return get_success_data(
        api_client.create_apostille(
            create_apostille_payload(certified_copy_request_id, **overrides), APPLICANT
        )
    )


def create_packet(vital_event_id, **overrides):
    return get_success_data(
        api_client.create_packet(
            create_packet_payload(vital_event_id, **overrides), REGISTRAR
        )
    )


def accept_packet(packet_id):
    return get_success_data(api_client.accept_packet(packet_id, REGISTRAR))


def event_version(event_id) -> int:
    """Read the vital event's current version (for OCC-guarded writes)."""
    data = get_success_data(api_client.get_vital_event(event_id, REGISTRAR))
    return data["version"]


# ─── Composite lifecycle shortcuts ──────────────────────────────────────
def setup_registered_birth_event(jurisdiction_code="CTY-01",
                                 event_date="2026-02-25T00:00:00Z",
                                 facility_overrides=None, event_overrides=None):
    """Facility + BIRTH event filed and registered (timely). Returns (facility, event).

    The event ends in REGISTERED with a minted state_file_number.
    """
    facility_overrides = facility_overrides or {}
    event_overrides = event_overrides or {}
    facility = create_facility(jurisdiction_code=jurisdiction_code, **facility_overrides)
    event = create_vital_event(
        facility["id"],
        event_type="BIRTH",
        event_date=event_date,
        jurisdiction_code=jurisdiction_code,
        **event_overrides,
    )
    file_event(event["id"], facility["id"])
    event = register_event(event["id"])
    return facility, event


def setup_registered_death_event(jurisdiction_code="CTY-06",
                                 event_date="2026-03-01T00:00:00Z",
                                 cause_of_death="Myocardial infarction",
                                 manner_of_death="NATURAL"):
    """Facility + certifier + DEATH event with a CERTIFIED certification, filed and
    registered (so the certification is LOCKED). Returns (facility, certifier, event, cert)."""
    facility = create_facility(
        jurisdiction_code=jurisdiction_code, facility_type="FUNERAL_HOME"
    )
    certifier = create_certifier(jurisdiction_code=jurisdiction_code)
    event = create_vital_event(
        facility["id"],
        event_type="DEATH",
        event_date=event_date,
        jurisdiction_code=jurisdiction_code,
        sex="MALE",
    )
    cert = create_certification(
        event["id"], certifier["id"],
        cause_of_death=cause_of_death, manner_of_death=manner_of_death,
    )
    certify(cert["id"], certifier["id"])
    file_event(event["id"], facility["id"])
    event = register_event(event["id"])
    return facility, certifier, event, cert


def setup_id_verified_copy(vital_event_id, **copy_overrides):
    """Create a copy request against `vital_event_id` and verify its ID.
    Returns the ID_VERIFIED copy request."""
    copy = create_copy_request(vital_event_id, **copy_overrides)
    return verify_copy(copy["id"])
