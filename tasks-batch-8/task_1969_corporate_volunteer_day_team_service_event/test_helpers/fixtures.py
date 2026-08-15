"""Composite setup helpers: multi-step scenarios built only from PRD-declared endpoints.

Every helper uses get_success_data() so a setup failure raises a clear
"Setup step failed" AssertionError naming the step, rather than a confusing
assertion failure inside the test body.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ADULT_DOB,
    EVENT_END,
    EVENT_START,
    GLOVES_LINES,
    LEAD_DOB,
    MINOR_DOB,
)
from .test_users import (
    TEST_USERS,
    make_employee_volunteer_headers,
    make_nonprofit_coordinator_headers,
    make_staff_lead_headers,
)

CEM = TEST_USERS["cem_headers"]
PO = TEST_USERS["procurement_officer_headers"]
LC = TEST_USERS["logistics_headers"]
FC = TEST_USERS["finance_headers"]
PA = TEST_USERS["platform_admin_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------

def create_partner(name: str = "River Guild", contact_email: str = "ops@river.org") -> dict:
    resp = api_client.create_nonprofit_partner(
        {"name": name, "contact_email": contact_email}, CEM
    )
    return get_success_data(resp, 201)


def create_event(
    name: str = "Volunteer Day",
    budget_cents: int = 1_000_000,
    event_start_at: str = EVENT_START,
    event_end_at: str = EVENT_END,
    waiver_document_version: Optional[int] = None,
) -> dict:
    payload = {
        "name": name,
        "event_start_at": event_start_at,
        "event_end_at": event_end_at,
        "budget_cents": budget_cents,
    }
    if waiver_document_version is not None:
        payload["waiver_document_version"] = waiver_document_version
    resp = api_client.create_service_event(payload, CEM)
    return get_success_data(resp, 201)


def create_project(
    partner_id: str,
    title: str = "Trail Repair",
    min_volunteers: int = 1,
    max_volunteers: int = 10,
) -> dict:
    payload = {
        "nonprofit_id": partner_id,
        "title": title,
        "min_volunteers": min_volunteers,
        "max_volunteers": max_volunteers,
    }
    resp = api_client.create_service_project(
        payload, make_nonprofit_coordinator_headers(partner_id)
    )
    return get_success_data(resp, 201)


def create_volunteer(
    full_name: str,
    email: str,
    date_of_birth: str = ADULT_DOB,
    is_staff_lead: bool = False,
    dietary_tags: Optional[list] = None,
    department: str = "Eng",
) -> dict:
    payload = {
        "full_name": full_name,
        "email": email,
        "department": department,
        "date_of_birth": date_of_birth,
    }
    if is_staff_lead:
        payload["is_staff_lead"] = True
    if dietary_tags is not None:
        payload["dietary_tags"] = dietary_tags
    resp = api_client.create_employee_volunteer(payload, CEM)
    return get_success_data(resp, 201)


def create_vehicle(name: str = "Bus-7", seat_capacity: int = 40) -> dict:
    resp = api_client.create_vehicle({"name": name, "seat_capacity": seat_capacity}, LC)
    return get_success_data(resp, 201)


def create_manifest(
    event_id: str,
    vehicle_id: str,
    depart_at: str = "2026-08-20T08:00:00Z",
    return_at: str = "2026-08-20T10:00:00Z",
    cost_cents: int = 5000,
) -> dict:
    payload = {
        "event_id": event_id,
        "vehicle_id": vehicle_id,
        "depart_at": depart_at,
        "return_at": return_at,
        "cost_cents": cost_cents,
    }
    resp = api_client.create_transport_manifest(payload, LC)
    return get_success_data(resp, 201)


def create_sponsorship(
    event_id: str,
    sponsor_name: str = "CorpCo",
    match_type: str = "FLAT",
    rate_cents: int = 5000,
    pledge_cap_cents: int = 9000,
) -> dict:
    payload = {
        "event_id": event_id,
        "sponsor_name": sponsor_name,
        "match_type": match_type,
        "rate_cents": rate_cents,
        "pledge_cap_cents": pledge_cap_cents,
    }
    resp = api_client.create_sponsorship(payload, FC)
    return get_success_data(resp, 201)


def create_meal_plan(
    event_id: str,
    vendor_name: str = "FreshCo",
    per_person_cost_cents: int = 1000,
    dietary_surcharge_cents: Optional[int] = None,
) -> dict:
    """Create a meal plan carrying the event's freshly-read version (PRD §2.9 OCC)."""
    event = get_event(event_id)
    payload = {
        "vendor_name": vendor_name,
        "per_person_cost_cents": per_person_cost_cents,
        "expected_event_version": event["version"],
    }
    if dietary_surcharge_cents is not None:
        payload["dietary_surcharge_cents"] = dietary_surcharge_cents
    resp = api_client.create_meal_plan(event_id, payload, LC)
    return get_success_data(resp, 201)


def create_impact_record(
    registration_id: str,
    project_id: str,
    nonprofit_id: str,
    hours_attended: float,
    photo_count: Optional[int] = None,
    story_text: Optional[str] = None,
) -> dict:
    payload = {
        "registration_id": registration_id,
        "project_id": project_id,
        "hours_attended": hours_attended,
    }
    if photo_count is not None:
        payload["photo_count"] = photo_count
    if story_text is not None:
        payload["story_text"] = story_text
    resp = api_client.create_impact_record(
        payload, make_nonprofit_coordinator_headers(nonprofit_id)
    )
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Tier 1b: GET passthroughs (return the data payload)
# ---------------------------------------------------------------------------

def get_event(event_id: str) -> dict:
    return get_success_data(api_client.get_service_event(event_id, ANY), 200)


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_service_project(project_id, ANY), 200)


def get_registration(registration_id: str) -> dict:
    return get_success_data(api_client.get_registration(registration_id, ANY), 200)


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_procurement_order(order_id, ANY), 200)


def get_manifest(manifest_id: str) -> dict:
    return get_success_data(api_client.get_transport_manifest(manifest_id, ANY), 200)


def get_meal_plan(meal_plan_id: str) -> dict:
    return get_success_data(api_client.get_meal_plan(meal_plan_id, ANY), 200)


def get_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_supervision_assignment(assignment_id, ANY), 200)


def get_sponsorship(sponsorship_id: str) -> dict:
    return get_success_data(api_client.get_sponsorship(sponsorship_id, ANY), 200)


def get_partner(partner_id: str) -> dict:
    return get_success_data(api_client.get_nonprofit_partner(partner_id, ANY), 200)


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, PA), 200
    )


# ---------------------------------------------------------------------------
# Tier 2: lifecycle transitions
# ---------------------------------------------------------------------------

def vet_project(project_id: str) -> dict:
    return get_success_data(api_client.vet_project(project_id, CEM), 200)


def match_project(project_id: str, event_id: str) -> dict:
    return get_success_data(
        api_client.match_project(project_id, {"event_id": event_id}, CEM), 200
    )


def lock_project(project_id: str) -> dict:
    return get_success_data(api_client.lock_project(project_id, CEM), 200)


def open_event_registration(event_id: str) -> dict:
    return get_success_data(api_client.open_registration(event_id, CEM), 200)


def lock_event_registration(event_id: str) -> dict:
    return get_success_data(api_client.lock_registration(event_id, CEM), 200)


def begin_event(event_id: str) -> dict:
    return get_success_data(api_client.begin_event(event_id, CEM), 200)


def complete_event(event_id: str) -> dict:
    return get_success_data(api_client.complete_event(event_id, CEM), 200)


def register_volunteer(
    volunteer: dict,
    event_id: str,
    project_id: str,
    wants_meal: Optional[bool] = None,
    wants_transport: Optional[bool] = None,
) -> dict:
    """Volunteer self-registers; volunteer_id comes from X-User-ID."""
    payload = {"event_id": event_id, "project_id": project_id}
    if wants_meal is not None:
        payload["wants_meal"] = wants_meal
    if wants_transport is not None:
        payload["wants_transport"] = wants_transport
    resp = api_client.create_registration(
        payload, make_employee_volunteer_headers(volunteer["id"])
    )
    return get_success_data(resp, 201)


def sign_waiver_self(registration_id: str, volunteer: dict, media_consent: bool = False) -> dict:
    payload = {
        "signer_name": volunteer["full_name"],
        "signer_relation": "SELF",
        "media_consent": media_consent,
    }
    resp = api_client.sign_waiver(
        registration_id, payload, make_employee_volunteer_headers(volunteer["id"])
    )
    return get_success_data(resp, 200)


def sign_waiver_guardian(
    registration_id: str, volunteer: dict, guardian_name: str, media_consent: bool = False
) -> dict:
    payload = {
        "signer_name": guardian_name,
        "signer_relation": "GUARDIAN",
        "media_consent": media_consent,
        "guardian_name": guardian_name,
    }
    resp = api_client.sign_waiver(
        registration_id, payload, make_employee_volunteer_headers(volunteer["id"])
    )
    return get_success_data(resp, 200)


def verify_waiver(registration_id: str) -> dict:
    return get_success_data(api_client.verify_waiver(registration_id, CEM), 200)


def verify_impact_record(record_id: str) -> dict:
    return get_success_data(api_client.verify_impact_record(record_id, CEM), 200)


def confirm_registration(registration_id: str) -> dict:
    return get_success_data(api_client.confirm_registration(registration_id, CEM), 200)


def cancel_registration(registration_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.cancel_registration(registration_id, headers or CEM), 200
    )


def check_in_registration(registration_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.check_in_registration(registration_id, headers or CEM), 200
    )


def assign_lead(project_id: str, lead: dict) -> dict:
    payload = {"project_id": project_id, "lead_volunteer_id": lead["id"]}
    resp = api_client.create_supervision_assignment(payload, CEM)
    return get_success_data(resp, 201)


def withdraw_assignment(assignment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.withdraw_supervision_assignment(assignment_id, headers or CEM), 200
    )


def create_order(event_id: str, project_id: str, lines: Optional[list] = None) -> dict:
    """Create a DRAFT order as the canonical creator handle (cem-1)."""
    payload = {
        "event_id": event_id,
        "project_id": project_id,
        "lines": lines or GLOVES_LINES,
    }
    resp = api_client.create_procurement_order(payload, CEM)
    return get_success_data(resp, 201)


def submit_order(order_id: str) -> dict:
    return get_success_data(api_client.submit_order(order_id, CEM), 200)


def approve_order(order_id: str) -> dict:
    return get_success_data(api_client.approve_order(order_id, PO), 200)


def receive_order(order_id: str) -> dict:
    return get_success_data(api_client.receive_order(order_id, CEM), 200)


def create_received_order(event_id: str, project_id: str, lines: Optional[list] = None) -> dict:
    """Create -> submit -> approve -> receive. Returns the RECEIVED order."""
    order = create_order(event_id, project_id, lines)
    submit_order(order["id"])
    approve_order(order["id"])
    return receive_order(order["id"])


def create_submitted_order(event_id: str, project_id: str, lines: Optional[list] = None) -> dict:
    order = create_order(event_id, project_id, lines)
    return submit_order(order["id"])


def order_meal_plan(meal_plan_id: str) -> dict:
    return get_success_data(api_client.order_meal_plan(meal_plan_id, LC), 200)


def commit_sponsorship(sponsorship_id: str) -> dict:
    return get_success_data(api_client.commit_sponsorship(sponsorship_id, FC), 200)


def settle_sponsorship(sponsorship_id: str) -> dict:
    return get_success_data(api_client.settle_sponsorship(sponsorship_id, FC), 200)


def submit_survey(registration_id: str, volunteer: dict, rating: int, would_repeat: bool = True) -> dict:
    payload = {
        "registration_id": registration_id,
        "rating": rating,
        "would_repeat": would_repeat,
    }
    resp = api_client.create_feedback_survey(
        payload, make_employee_volunteer_headers(volunteer["id"])
    )
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Tier 3: scenario composites
# ---------------------------------------------------------------------------

def setup_matched_scenario(
    event_name: str = "Volunteer Day",
    budget_cents: int = 1_000_000,
    min_volunteers: int = 1,
    max_volunteers: int = 10,
    project_title: str = "Trail Repair",
    event_start_at: str = EVENT_START,
    event_end_at: str = EVENT_END,
    open_registration: bool = True,
) -> dict:
    """Partner + project vetted + matched to a fresh event; registration opened by default."""
    partner = create_partner()
    project = create_project(partner["id"], project_title, min_volunteers, max_volunteers)
    event = create_event(event_name, budget_cents, event_start_at, event_end_at)
    vet_project(project["id"])
    match_project(project["id"], event["id"])
    if open_registration:
        event = open_event_registration(event["id"])
    return {"partner": partner, "project": get_project(project["id"]), "event": event}


def add_signed_registration(
    event_id: str,
    project_id: str,
    volunteer: dict,
    wants_meal: Optional[bool] = False,
    wants_transport: Optional[bool] = None,
    verify: bool = False,
    confirm: bool = False,
    media_consent: bool = False,
) -> dict:
    """Register + sign (SELF); optionally verify and/or confirm."""
    reg = register_volunteer(
        volunteer, event_id, project_id, wants_meal=wants_meal, wants_transport=wants_transport
    )
    sign_waiver_self(reg["id"], volunteer, media_consent=media_consent)
    if verify:
        verify_waiver(reg["id"])
    if confirm:
        confirm_registration(reg["id"])
    return get_registration(reg["id"])


def setup_ready_event(
    event_name: str = "Volunteer Day",
    budget_cents: int = 1_000_000,
    num_adults: int = 1,
    min_volunteers: int = 1,
    max_volunteers: int = 10,
    wants_meal: bool = False,
    verify_waivers: bool = True,
    order_lines: Optional[list] = None,
    project_title: str = "Trail Repair",
    event_start_at: str = EVENT_START,
    event_end_at: str = EVENT_END,
) -> dict:
    """Full chain to a READY-posture event: matched project, N confirmed adults,
    one ACTIVE staff lead, one RECEIVED order, project LOCKED."""
    sc = setup_matched_scenario(
        event_name=event_name,
        budget_cents=budget_cents,
        min_volunteers=min_volunteers,
        max_volunteers=max_volunteers,
        project_title=project_title,
        event_start_at=event_start_at,
        event_end_at=event_end_at,
        open_registration=True,
    )
    partner, project, event = sc["partner"], sc["project"], sc["event"]
    volunteers, registrations = [], []
    for i in range(num_adults):
        vol = create_volunteer(f"Vol {i + 1}", f"vol{i + 1}@corp.com")
        reg = add_signed_registration(
            event["id"],
            project["id"],
            vol,
            wants_meal=wants_meal,
            wants_transport=False,
            verify=verify_waivers,
            confirm=True,
        )
        volunteers.append(vol)
        registrations.append(reg)
    lead = create_volunteer("Lead One", "lead1@corp.com", date_of_birth=LEAD_DOB, is_staff_lead=True)
    assignment = assign_lead(project["id"], lead)
    order = create_received_order(event["id"], project["id"], lines=order_lines)
    project = lock_project(project["id"])
    return {
        "partner": partner,
        "project": project,
        "event": get_event(event["id"]),
        "volunteers": volunteers,
        "registrations": registrations,
        "lead": lead,
        "assignment": assignment,
        "order": order,
    }


def begin_ready_event(event_id: str) -> dict:
    """REGISTRATION_OPEN -> REGISTRATION_LOCKED -> IN_PROGRESS."""
    lock_event_registration(event_id)
    return begin_event(event_id)


def setup_in_progress_event(**kwargs) -> dict:
    """READY event driven through lock-registration + begin."""
    sc = setup_ready_event(**kwargs)
    sc["event"] = begin_ready_event(sc["event"]["id"])
    return sc


def setup_completed_event(**kwargs) -> dict:
    """IN_PROGRESS event with every confirmed registration checked in, then completed."""
    sc = setup_in_progress_event(**kwargs)
    for reg in sc["registrations"]:
        check_in_registration(reg["id"])
    sc["registrations"] = [get_registration(r["id"]) for r in sc["registrations"]]
    sc["event"] = complete_event(sc["event"]["id"])
    return sc
