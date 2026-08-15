"""Composite setup helpers.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so the database
starts empty). Setup calls use the lenient get_success_data() validator so
failures surface as clear "Setup failed" errors.

Identity threading: after creating a Veterinarian, every AccreditedVet call
uses make_vet_headers(vet["id"]) — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    create_certificate_payload,
    create_entry_requirement_payload,
    create_movement_permit_payload,
    create_movement_record_payload,
    create_none_entry_requirement_payload,
    create_outbreak_zone_payload,
    create_premises_payload,
    create_quarantine_order_payload,
    create_test_record_payload,
    create_veterinarian_payload,
)
from .test_users import TEST_USERS, make_officer_headers, make_vet_headers

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
OFFICER_B = TEST_USERS["officer_b_headers"]
LAB = TEST_USERS["lab_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

# Canonical logical-clock instant used by the standard scenario chains.
STANDARD_CLOCK = "2026-08-10T00:00:00Z"


def _setup_ok(response, what: str):
    try:
        return get_success_data(response)
    except AssertionError as exc:  # pragma: no cover - setup diagnostics
        raise AssertionError(
            f"Setup failed at {what}: {response.status_code} {response.text}"
        ) from exc


# --- single-entity creators -------------------------------------------------

def create_premises(admin_headers=ADMIN, **overrides):
    resp = api_client.create_premises(create_premises_payload(**overrides), admin_headers)
    return _setup_ok(resp, "create_premises")


def create_veterinarian(admin_headers=ADMIN, **overrides):
    resp = api_client.create_veterinarian(
        create_veterinarian_payload(**overrides), admin_headers
    )
    return _setup_ok(resp, "create_veterinarian")


def create_entry_requirement(admin_headers=ADMIN, none_type=False, **overrides):
    factory = create_none_entry_requirement_payload if none_type else create_entry_requirement_payload
    resp = api_client.create_entry_requirement(factory(**overrides), admin_headers)
    return _setup_ok(resp, "create_entry_requirement")


def create_test_record(premises_id, lab_headers=LAB, **overrides):
    payload = create_test_record_payload(premises_id=premises_id, **overrides)
    resp = api_client.create_test_record(payload, lab_headers)
    return _setup_ok(resp, "create_test_record")


def report_result(test_id, result, lab_headers=LAB):
    resp = api_client.report_test_result(test_id, {"result": result}, lab_headers)
    return _setup_ok(resp, f"report_result({result})")


def create_negative_test(premises_id, lab_headers=LAB, **overrides):
    """Create a test record and resolve it NEGATIVE. Returns the record."""
    record = create_test_record(premises_id, lab_headers=lab_headers, **overrides)
    return report_result(record["id"], "NEGATIVE", lab_headers=lab_headers)


def set_clock(to_iso8601, admin_headers=ADMIN):
    resp = api_client.set_clock(to_iso8601, admin_headers)
    return _setup_ok(resp, f"set_clock({to_iso8601})")


def create_outbreak_zone(officer_headers=OFFICER, **overrides):
    resp = api_client.create_outbreak_zone(
        create_outbreak_zone_payload(**overrides), officer_headers
    )
    return _setup_ok(resp, "create_outbreak_zone")


def create_quarantine_order(premises_id, officer_user_id="officer-a", **overrides):
    payload = create_quarantine_order_payload(premises_id=premises_id, **overrides)
    resp = api_client.create_quarantine_order(
        payload, make_officer_headers(officer_user_id)
    )
    return _setup_ok(resp, "create_quarantine_order")


# --- certificate lifecycle (tiers 1 & 3) -------------------------------------

def create_draft_certificate(premises_id, vet_id, **overrides):
    """Create a DRAFT certificate owned by vet_id. Returns the certificate."""
    payload = create_certificate_payload(origin_premises_id=premises_id, **overrides)
    resp = api_client.create_certificate(payload, make_vet_headers(vet_id))
    return _setup_ok(resp, "create_draft_certificate")


def submit_certificate(cert_id, vet_id):
    resp = api_client.submit_certificate(cert_id, make_vet_headers(vet_id))
    return _setup_ok(resp, "submit_certificate")


def issue_certificate(cert_id, officer_headers=OFFICER):
    resp = api_client.issue_certificate(cert_id, officer_headers)
    return _setup_ok(resp, "issue_certificate")


def setup_standard_scenario(
    head_count=30,
    disease_status="MONITORED",
    none_matrix=False,
    clock=STANDARD_CLOCK,
    county=DEFAULTS["COUNTY"],
    species="CATTLE",
    premises_name="Standard Ranch",
):
    """Premises + accredited vet + matrix row (+ NEGATIVE test when the matrix
    demands one) + logical clock advanced. Returns a dict of the pieces."""
    premises = create_premises(
        name=premises_name,
        county=county,
        species_code=species,
        initial_head_count=head_count,
        disease_status=disease_status,
    )
    vet = create_veterinarian()
    if none_matrix:
        requirement = create_entry_requirement(none_type=True, species_code=species)
        test = None
    else:
        requirement = create_entry_requirement(species_code=species)
        test = create_negative_test(premises["id"], species_code=species)
    set_clock(clock)
    return {
        "premises": premises,
        "vet": vet,
        "requirement": requirement,
        "test": test,
    }


def create_submitted_certificate(scenario=None, cert_overrides=None, **scenario_kwargs):
    """Full chain through PENDING_REVIEW. Returns (scenario, certificate)."""
    if scenario is None:
        scenario = setup_standard_scenario(**scenario_kwargs)
    overrides = dict(cert_overrides or {})
    if scenario.get("test") is not None:
        overrides.setdefault("test_record_id", scenario["test"]["id"])
        overrides.setdefault("vaccination_date", DEFAULTS["VACCINATION_DATE"])
    cert = create_draft_certificate(
        scenario["premises"]["id"], scenario["vet"]["id"], **overrides
    )
    cert = submit_certificate(cert["id"], scenario["vet"]["id"])
    return scenario, cert


def create_issued_certificate(scenario=None, cert_overrides=None, **scenario_kwargs):
    """Full chain through ISSUED. Returns (scenario, certificate)."""
    scenario, cert = create_submitted_certificate(
        scenario=scenario, cert_overrides=cert_overrides, **scenario_kwargs
    )
    cert = issue_certificate(cert["id"])
    return scenario, cert


# --- permit / movement tiers --------------------------------------------------

def create_requested_permit(cert_id, vet_id, **overrides):
    payload = create_movement_permit_payload(certificate_id=cert_id, **overrides)
    resp = api_client.create_movement_permit(payload, make_vet_headers(vet_id))
    return _setup_ok(resp, "create_requested_permit")


def issue_permit(permit_id, officer_headers=OFFICER):
    resp = api_client.issue_movement_permit(permit_id, officer_headers)
    return _setup_ok(resp, "issue_permit")


def create_issued_permit(cert_id, vet_id, **overrides):
    """Request + issue a movement permit. Returns the ISSUED permit."""
    permit = create_requested_permit(cert_id, vet_id, **overrides)
    return issue_permit(permit["id"])


def setup_issued_certificate_with_permit(
    allocation=10, cert_head_count=10, none_matrix=True, **scenario_kwargs
):
    """ISSUED certificate + ISSUED permit. Returns (scenario, cert, permit)."""
    cert_overrides = {"head_count": cert_head_count}
    if "species" in scenario_kwargs:
        # The certificate's species must match the premises' species (PRD §3.4).
        cert_overrides["species_code"] = scenario_kwargs["species"]
    scenario, cert = create_issued_certificate(
        none_matrix=none_matrix,
        cert_overrides=cert_overrides,
        **scenario_kwargs,
    )
    permit = create_issued_permit(cert["id"], scenario["vet"]["id"], allocated_head_count=allocation)
    return scenario, cert, permit


def create_scheduled_record(permit_id, vet_id, **overrides):
    payload = create_movement_record_payload(permit_id=permit_id, **overrides)
    resp = api_client.create_movement_record(payload, make_vet_headers(vet_id))
    return _setup_ok(resp, "create_scheduled_record")


def get_premises(premises_id, headers=AUDITOR):
    resp = api_client.get_premises(premises_id, headers)
    return _setup_ok(resp, "get_premises")


def get_certificate(cert_id, headers=AUDITOR):
    resp = api_client.get_certificate(cert_id, headers)
    return _setup_ok(resp, "get_certificate")


def get_permit(permit_id, headers=AUDITOR):
    resp = api_client.get_movement_permit(permit_id, headers)
    return _setup_ok(resp, "get_permit")


# --- outbreak cascade helpers --------------------------------------------------

def create_and_escalate_zone(officer_headers=OFFICER, **overrides):
    """Declare a zone and escalate it to ACTIVE (fires the hold cascade)."""
    zone = create_outbreak_zone(officer_headers=officer_headers, **overrides)
    resp = api_client.escalate_outbreak_zone(zone["id"], officer_headers)
    return _setup_ok(resp, "escalate_outbreak_zone")


def transmit_and_acknowledge(cert_id, officer_headers=OFFICER, channel="XML_GATEWAY"):
    """Transmit a certificate and acknowledge the audit -> certificate TRANSMITTED."""
    audit = _setup_ok(
        api_client.transmit_certificate(cert_id, {"channel": channel}, officer_headers),
        "transmit_certificate",
    )
    _setup_ok(
        api_client.acknowledge_transmission(audit["id"], officer_headers),
        "acknowledge_transmission",
    )
    return audit
