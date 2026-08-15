"""Composite setup helpers.

Most claims in this PRD require the system to be in a specific posture: a
license inside its renewal window with an exact CE tally, a just-in-time
appointment awaiting filing, a producer suspended by an overdue inquiry, a
confirmed regulatory action mid-cascade. These helpers encapsulate the
multi-step setup chains so tests stay focused on assertions.

All helpers hit the live API through the shared client and use the lenient
setup validator, so a broken precondition surfaces as a clear "Setup step
failed" error naming the failing call. Every helper builds its preconditions
from scratch against the freshly restarted server (empty database, logical
clock at the PRD 2.5 startup value).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agency_payload,
    create_application_payload,
    create_appointment_payload,
    create_ce_credit_payload,
    create_inquiry_payload,
    create_license_payload,
    create_producer_payload,
    create_regulatory_action_payload,
)
from .test_users import TEST_USERS

LC = TEST_USERS["licensing_coordinator_headers"]
OFFICER_A = TEST_USERS["compliance_officer_a_headers"]
OFFICER_B = TEST_USERS["compliance_officer_b_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]
ADMIN = TEST_USERS["carrier_admin_headers"]


# --- Logical clock ---------------------------------------------------------

def advance_clock(to_iso8601: str) -> dict:
    """CarrierAdmin advances the logical clock, running the compliance sweep."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# --- Tier 1: single-entity creators ----------------------------------------

def create_agency(name="Test Agency", resident_state_code="CA", **overrides) -> dict:
    return get_success_data(
        api_client.create_agency(
            create_agency_payload(name=name, resident_state_code=resident_state_code, **overrides),
            LC,
        )
    )


def create_producer(npn="NPN-0001", full_name="Test Producer",
                    resident_state_code="CA", agency_id=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_producer(
            create_producer_payload(
                npn=npn, full_name=full_name,
                resident_state_code=resident_state_code, agency_id=agency_id, **overrides,
            ),
            LC,
        )
    )


def create_license(producer_id=None, agency_id=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_license(
            create_license_payload(producer_id=producer_id, agency_id=agency_id, **overrides),
            LC,
        )
    )


def report_ce_credit(license_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_ce_credit(create_ce_credit_payload(license_id, **overrides), LC)
    )


def review_ce_credit(credit_id, decision) -> dict:
    return get_success_data(api_client.review_ce_credit(credit_id, {"decision": decision}, LC))


def report_and_accept_ce_credit(license_id, **overrides) -> dict:
    """Report a CE credit and have the coordinator accept it."""
    credit = report_ce_credit(license_id, **overrides)
    return review_ce_credit(credit["id"], "ACCEPT")


def create_appointment(producer_id=None, agency_id=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_appointment(
            create_appointment_payload(producer_id=producer_id, agency_id=agency_id, **overrides),
            LC,
        )
    )


def file_appointment(appointment_id) -> dict:
    return get_success_data(api_client.file_appointment(appointment_id, LC))


def create_and_file_appointment(producer_id=None, agency_id=None, **overrides) -> dict:
    """Request a STANDARD appointment and file it to ACTIVE."""
    appointment = create_appointment(producer_id=producer_id, agency_id=agency_id, **overrides)
    return file_appointment(appointment["id"])


def submit_application(producer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_application(create_application_payload(producer_id, **overrides), LC)
    )


def decide_application(application_id, decision) -> dict:
    return get_success_data(api_client.decide_application(application_id, {"decision": decision}, LC))


def issue_application(application_id) -> dict:
    return get_success_data(api_client.issue_application(application_id, LC))


def get_entry_for_application(application_id) -> dict:
    """Return the application's single commission entry (created at submission)."""
    entries = get_success_data(
        api_client.list_commission_entries(LC, params={"application_id": application_id})
    )
    assert isinstance(entries, list) and len(entries) == 1, (
        f"expected exactly one commission entry for application {application_id}, "
        f"got {entries!r}"
    )
    return entries[0]


def get_license(license_id) -> dict:
    return get_success_data(api_client.get_license(license_id, LC))


def get_producer(producer_id) -> dict:
    return get_success_data(api_client.get_producer(producer_id, LC))


def get_appointment(appointment_id) -> dict:
    return get_success_data(api_client.get_appointment(appointment_id, LC))


def get_application(application_id) -> dict:
    return get_success_data(api_client.get_application(application_id, LC))


def get_inquiry(inquiry_id) -> dict:
    return get_success_data(api_client.get_inquiry(inquiry_id, OFFICER_A))


# --- Tier 2: entity hierarchy ----------------------------------------------

def setup_producer_with_license(
    npn="NPN-1001",
    state_code="CA",
    lines_of_authority=("LIFE",),
    license_class="RESIDENT",
    issue_date="2026-01-01T00:00:00Z",
    expiration_date="2028-01-01T00:00:00Z",
    ce_required_hours=24,
    ce_ethics_required_hours=3,
    resident_state_code="CA",
    agency_id=None,
) -> dict:
    """Producer plus an ACTIVE license in `state_code`. Returns {"producer", "license"}."""
    producer = create_producer(
        npn=npn, resident_state_code=resident_state_code, agency_id=agency_id
    )
    license_ = create_license(
        producer_id=producer["id"],
        state_code=state_code,
        license_class=license_class,
        lines_of_authority=list(lines_of_authority),
        issue_date=issue_date,
        expiration_date=expiration_date,
        ce_required_hours=ce_required_hours,
        ce_ethics_required_hours=ce_ethics_required_hours,
    )
    return {"producer": producer, "license": license_}


def setup_producer_with_active_appointment(
    npn="NPN-1002",
    state_code="CA",
    lines_of_authority=("LIFE",),
    license_class="RESIDENT",
    issue_date="2026-01-01T00:00:00Z",
    expiration_date="2028-01-01T00:00:00Z",
    ce_required_hours=24,
    ce_ethics_required_hours=3,
    effective_date="2026-01-15T00:00:00Z",
    agency_id=None,
) -> dict:
    """Producer plus ACTIVE license plus a filed (ACTIVE) STANDARD appointment.
    Returns {"producer", "license", "appointment"}."""
    base = setup_producer_with_license(
        npn=npn,
        state_code=state_code,
        lines_of_authority=lines_of_authority,
        license_class=license_class,
        issue_date=issue_date,
        expiration_date=expiration_date,
        ce_required_hours=ce_required_hours,
        ce_ethics_required_hours=ce_ethics_required_hours,
        agency_id=agency_id,
    )
    appointment = create_and_file_appointment(
        producer_id=base["producer"]["id"],
        state_code=state_code,
        lines_of_authority=list(lines_of_authority),
        effective_date=effective_date,
    )
    return {**base, "appointment": appointment}


# --- Tier 3: application lifecycle shortcuts --------------------------------

def setup_approved_application(
    npn="NPN-1003",
    state_code="CA",
    line_of_authority="LIFE",
    premium_cents=1_000_000,
    applicant_name="Applicant",
    **license_overrides,
) -> dict:
    """Producer with ACTIVE license + appointment and one APPROVED application.
    Returns {"producer", "license", "appointment", "application", "entry"}."""
    base = setup_producer_with_active_appointment(
        npn=npn, state_code=state_code, lines_of_authority=(line_of_authority,),
        **license_overrides,
    )
    application = submit_application(
        base["producer"]["id"],
        state_code=state_code,
        line_of_authority=line_of_authority,
        applicant_name=applicant_name,
        premium_cents=premium_cents,
    )
    decide_application(application["id"], "APPROVE")
    approved = get_application(application["id"])
    entry = get_entry_for_application(application["id"])
    return {**base, "application": approved, "entry": entry}


def setup_issued_application(
    npn="NPN-1004",
    state_code="CA",
    line_of_authority="LIFE",
    premium_cents=1_000_000,
    applicant_name="Applicant",
    **license_overrides,
) -> dict:
    """Full lifecycle through ISSUED. The commission entry is PAYABLE.
    Returns {"producer", "license", "appointment", "application", "entry"}."""
    base = setup_approved_application(
        npn=npn,
        state_code=state_code,
        line_of_authority=line_of_authority,
        premium_cents=premium_cents,
        applicant_name=applicant_name,
        **license_overrides,
    )
    issued = issue_application(base["application"]["id"])
    entry = get_entry_for_application(issued["id"])
    return {**base, "application": issued, "entry": entry}


def setup_jit_scenario(
    npn="NPN-1005",
    state_code="CA",
    line_of_authority="LIFE",
    premium_cents=5_000_000,
    applicant_name="JIT Applicant",
    **license_overrides,
) -> dict:
    """Producer with an ACTIVE license but NO appointment: submission evaluates
    to APPOINTMENT_GAP, so the platform creates a JIT_PENDING appointment and
    the commission entry starts HELD with hold_reason APPOINTMENT_PENDING.
    Returns {"producer", "license", "application", "jit_appointment", "entry"}."""
    base = setup_producer_with_license(
        npn=npn, state_code=state_code, lines_of_authority=(line_of_authority,),
        **license_overrides,
    )
    application = submit_application(
        base["producer"]["id"],
        state_code=state_code,
        line_of_authority=line_of_authority,
        applicant_name=applicant_name,
        premium_cents=premium_cents,
    )
    assert application.get("jit_appointment_id"), (
        f"expected a JIT appointment link on the application, got {application!r}"
    )
    jit_appointment = get_appointment(application["jit_appointment_id"])
    entry = get_entry_for_application(application["id"])
    return {
        **base,
        "application": application,
        "jit_appointment": jit_appointment,
        "entry": entry,
    }


# --- Tier 4: regulatory actions and inquiries --------------------------------

def create_regulatory_action(producer_id=None, agency_id=None, **overrides) -> dict:
    """Report a regulatory action as officer A (the maker)."""
    return get_success_data(
        api_client.create_regulatory_action(
            create_regulatory_action_payload(
                producer_id=producer_id, agency_id=agency_id, **overrides
            ),
            OFFICER_A,
        )
    )


def confirm_regulatory_action(action_id) -> dict:
    """Confirm a REPORTED action as officer B (the checker)."""
    return get_success_data(api_client.confirm_regulatory_action(action_id, OFFICER_B))


def dismiss_regulatory_action(action_id) -> dict:
    """Dismiss a REPORTED action as officer B (the checker)."""
    return get_success_data(api_client.dismiss_regulatory_action(action_id, OFFICER_B))


def create_inquiry(producer_id=None, agency_id=None, state_code="TX",
                   reference_number="INQ-0001", **overrides) -> dict:
    return get_success_data(
        api_client.create_inquiry(
            create_inquiry_payload(
                producer_id=producer_id, agency_id=agency_id,
                state_code=state_code, reference_number=reference_number, **overrides,
            ),
            OFFICER_A,
        )
    )


def setup_suspended_producer(
    npn="NPN-1006",
    resident_state_code="TX",
    state_code="TX",
    reference_number="INQ-1006",
    sweep_to="2026-09-01T00:00:00Z",
) -> dict:
    """Producer suspended by the inquiry-overdue cascade: an OPEN inquiry is
    created at the default clock (response_due_at = received_at + 30 days) and
    the clock is then swept past the due instant. Returns {"producer", "inquiry"}
    with the producer record re-read after the sweep."""
    producer = create_producer(npn=npn, resident_state_code=resident_state_code)
    inquiry = create_inquiry(
        producer_id=producer["id"], state_code=state_code,
        reference_number=reference_number,
    )
    advance_clock(sweep_to)
    return {"producer": get_producer(producer["id"]), "inquiry": inquiry}


def setup_confirmed_license_action(
    npn="NPN-1007",
    action_type="SUSPENSION",
    state_code="CA",
    lines_of_authority=("LIFE",),
    effective_date="2026-08-01T00:00:00Z",
    **license_overrides,
) -> dict:
    """Producer with license (and ACTIVE appointment) plus a CONFIRMED
    SUSPENSION/REVOCATION action: the license cascade has already run.
    Returns {"producer", "license", "appointment", "action"}."""
    base = setup_producer_with_active_appointment(
        npn=npn, state_code=state_code, lines_of_authority=lines_of_authority,
        **license_overrides,
    )
    action = create_regulatory_action(
        producer_id=base["producer"]["id"],
        state_code=state_code,
        action_type=action_type,
        effective_date=effective_date,
    )
    confirmed = confirm_regulatory_action(action["id"])
    return {**base, "action": confirmed}


def setup_held_commission_via_suspension(
    npn="NPN-1008",
    state_code="CA",
    line_of_authority="PROPERTY",
    premium_cents=10_000_000,
) -> dict:
    """One ISSUED application whose PAYABLE commission has been re-held by a
    confirmed SUSPENSION cascade (REGULATORY_HOLD). Returns the issued bundle
    plus "action" and the re-read "license"."""
    bundle = setup_issued_application(
        npn=npn, state_code=state_code, line_of_authority=line_of_authority,
        premium_cents=premium_cents,
    )
    action = create_regulatory_action(
        producer_id=bundle["producer"]["id"],
        state_code=state_code,
        action_type="SUSPENSION",
        effective_date="2026-08-01T00:00:00Z",
    )
    confirmed = confirm_regulatory_action(action["id"])
    return {
        **bundle,
        "action": confirmed,
        "license": get_license(bundle["license"]["id"]),
        "appointment": get_appointment(bundle["appointment"]["id"]),
        "entry": get_entry_for_application(bundle["application"]["id"]),
    }
