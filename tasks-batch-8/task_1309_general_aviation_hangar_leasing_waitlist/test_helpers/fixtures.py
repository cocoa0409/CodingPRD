"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these fixtures build preconditions from scratch using
only PRD-declared endpoints. They use the lenient `get_success_data`
validator so setup failures surface as clear "Setup failed" messages.

Identity threading (PRD §2.1): after creating an application or lease, any
ownership-gated call uses `make_applicant_headers(application["id"])` or
`make_tenant_headers(lease["id"])`, never the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    accept_offer_payload,
    create_airport_payload,
    create_application_payload,
    create_hangar_payload,
    create_offer_payload,
    create_rate_schedule_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_applicant_headers

MANAGER = TEST_USERS["manager_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
APPLICANT_FALLBACK = TEST_USERS["applicant_headers"]


def _setup_failed(step: str, resp):
    raise AssertionError(f"Setup failed at {step}: {resp.status_code} {resp.text}")


def create_airport(**overrides):
    """Create an airport (returns ACTIVE airport dict)."""
    resp = api_client.create_airport(create_airport_payload(**overrides), MANAGER)
    if resp.status_code >= 400:
        _setup_failed("create_airport", resp)
    return get_success_data(resp)


def add_rate_schedule(airport_id, **overrides):
    resp = api_client.create_rate_schedule(
        create_rate_schedule_payload(airport_id=airport_id, **overrides), MANAGER
    )
    if resp.status_code >= 400:
        _setup_failed("add_rate_schedule", resp)
    return get_success_data(resp)


def add_hangar(airport_id, **overrides):
    resp = api_client.create_hangar(create_hangar_payload(airport_id=airport_id, **overrides), MANAGER)
    if resp.status_code >= 400:
        _setup_failed("add_hangar", resp)
    return get_success_data(resp)


def submit_application(airport_id, **overrides):
    """Submit a waitlist application as an Applicant. No application exists
    yet, so the shared fallback applicant headers are used (creation is not
    ownership-gated)."""
    resp = api_client.create_application(
        create_application_payload(airport_id=airport_id, **overrides), APPLICANT_FALLBACK
    )
    if resp.status_code >= 400:
        _setup_failed("submit_application", resp)
    return get_success_data(resp)


def extend_offer(airport_id, hangar_id, application_id, override_next_in_queue=False):
    payload = create_offer_payload(
        airport_id=airport_id, hangar_id=hangar_id, application_id=application_id
    )
    if override_next_in_queue:
        payload["override_next_in_queue"] = True
    resp = api_client.create_offer(payload, MANAGER)
    if resp.status_code >= 400:
        _setup_failed("extend_offer", resp)
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(set_clock_payload(to_iso8601=to_iso8601), MANAGER)
    if resp.status_code >= 400:
        _setup_failed("set_clock", resp)
    return get_success_data(resp)


def accept_offer(offer, hangar, application, **overrides):
    """Accept an OPEN offer as the applicant; returns the created Lease.

    `expected_hangar_version` defaults to the hangar's version as captured in
    the passed hangar dict; the caller is responsible for re-reading the
    hangar if it may have mutated since.
    """
    overrides.setdefault("expected_hangar_version", hangar["version"])
    overrides.setdefault("aircraft_n_number", application["aircraft_n_number"])
    resp = api_client.accept_offer(
        offer["id"], accept_offer_payload(**overrides), make_applicant_headers(application["id"])
    )
    if resp.status_code >= 400:
        _setup_failed("accept_offer", resp)
    return get_success_data(resp)


def setup_offer(airport_overrides=None, size_class="T_HANGAR", rate=90000,
                hangar_code="T-1", start_clock=None, applicant_name="Test Applicant",
                aircraft_n_number=None, is_based_tenant_transfer=False,
                override_next_in_queue=False, schedule_overrides=None):
    """Airport + rate schedule + hangar + application + OPEN offer.

    `start_clock` moves the logical clock BEFORE the offer is created, so the
    offer's acceptance window stays open for a later acceptance (PRD §3.3:
    the sweep expires an OPEN offer strictly after its deadline).
    Returns dict(airport, schedule, hangar, application, offer).
    """
    airport = create_airport(**(airport_overrides or {}))
    schedule = add_rate_schedule(
        airport["id"], size_class=size_class, monthly_rate_cents=rate,
        **(schedule_overrides or {}),
    )
    hangar = add_hangar(airport["id"], hangar_code=hangar_code, size_class=size_class)
    app_kwargs = dict(
        applicant_name=applicant_name, size_class_requested=size_class,
        is_based_tenant_transfer=is_based_tenant_transfer,
    )
    if aircraft_n_number is not None:
        app_kwargs["aircraft_n_number"] = aircraft_n_number
    application = submit_application(airport["id"], **app_kwargs)
    if start_clock is not None:
        set_clock(start_clock)
    offer = extend_offer(airport["id"], hangar["id"], application["id"],
                         override_next_in_queue=override_next_in_queue)
    return {
        "airport": airport, "schedule": schedule, "hangar": hangar,
        "application": application, "offer": offer,
    }


def setup_lease(airport_overrides=None, size_class="T_HANGAR", rate=90000,
                hangar_code="T-1", start_clock=None, sublease_allowed=False,
                insurance_coverage=None, insurance_effective_from=None,
                insurance_effective_to=None, applicant_name="Test Applicant",
                aircraft_n_number=None, aircraft_make_model="Cessna 172",
                is_based_tenant_transfer=False, override_next_in_queue=False,
                schedule_overrides=None):
    """Full chain through lease activation: airport + schedule + hangar +
    application + offer + accept. Returns dict(airport, schedule, hangar,
    application, offer, lease)."""
    ctx = setup_offer(
        airport_overrides=airport_overrides, size_class=size_class, rate=rate,
        hangar_code=hangar_code, start_clock=start_clock, applicant_name=applicant_name,
        aircraft_n_number=aircraft_n_number,
        is_based_tenant_transfer=is_based_tenant_transfer,
        override_next_in_queue=override_next_in_queue,
        schedule_overrides=schedule_overrides,
    )
    accept_kwargs = {"sublease_allowed": sublease_allowed, "aircraft_make_model": aircraft_make_model}
    if insurance_coverage is not None:
        accept_kwargs["insurance_liability_coverage_cents"] = insurance_coverage
    if insurance_effective_from is not None:
        accept_kwargs["insurance_effective_from"] = insurance_effective_from
    if insurance_effective_to is not None:
        accept_kwargs["insurance_effective_to"] = insurance_effective_to
    ctx["lease"] = accept_offer(ctx["offer"], ctx["hangar"], ctx["application"], **accept_kwargs)
    return ctx


def get_lease(lease_id):
    resp = api_client.get_lease(lease_id, MANAGER)
    if resp.status_code >= 400:
        _setup_failed("get_lease", resp)
    return get_success_data(resp)


def get_hangar(hangar_id):
    resp = api_client.get_hangar(hangar_id, MANAGER)
    if resp.status_code >= 400:
        _setup_failed("get_hangar", resp)
    return get_success_data(resp)


def get_application(application_id):
    resp = api_client.get_application(application_id, MANAGER)
    if resp.status_code >= 400:
        _setup_failed("get_application", resp)
    return get_success_data(resp)


def get_offer(offer_id):
    resp = api_client.get_offer(offer_id, MANAGER)
    if resp.status_code >= 400:
        _setup_failed("get_offer", resp)
    return get_success_data(resp)


def get_eviction_case(case_id):
    resp = api_client.get_eviction_case(case_id, MANAGER)
    if resp.status_code >= 400:
        _setup_failed("get_eviction_case", resp)
    return get_success_data(resp)


def list_rent_charges(lease_id):
    """All rent charges of a lease, in the list endpoint's created_at
    ascending order (PRD §2.3)."""
    resp = api_client.list_rent_charges(lease_id, MANAGER, params={"limit": 100})
    if resp.status_code >= 400:
        _setup_failed("list_rent_charges", resp)
    return get_success_data(resp)


def list_audit_findings(lease_id, params=None):
    resp = api_client.list_audit_findings(lease_id, MANAGER, params=params or {"limit": 100})
    if resp.status_code >= 400:
        _setup_failed("list_audit_findings", resp)
    return get_success_data(resp)


def list_lease_eviction_cases(lease_id):
    resp = api_client.list_lease_eviction_cases(lease_id, MANAGER, params={"limit": 100})
    if resp.status_code >= 400:
        _setup_failed("list_lease_eviction_cases", resp)
    return get_success_data(resp)


def file_finding(lease_id, finding_type="NON_AERONAUTICAL_USE"):
    """ComplianceOfficer files a use-audit finding; returns the OPEN finding."""
    resp = api_client.file_audit_finding(lease_id, {"finding_type": finding_type}, COMPLIANCE)
    if resp.status_code >= 400:
        _setup_failed("file_finding", resp)
    return get_success_data(resp)
