"""Composite setup helpers for multi-step test prerequisites.

Fixtures use get_success_data() (lenient validator) so setup failures surface
as clear "Setup failed" errors. Volunteer-role calls always thread the acting
volunteer's real id through make_volunteer_headers().
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_WINDOW_END, DEFAULT_WINDOW_START
from .factories import (
    adjudicate_check_payload,
    adjudicate_incident_payload,
    create_background_check_payload,
    create_campus_payload,
    create_check_in_payload,
    create_hour_entry_payload,
    create_incident_report_payload,
    create_lincoln_campus_payload,
    create_opportunity_payload,
    create_placement_payload,
    create_recognition_award_payload,
    create_training_module_payload,
    create_training_record_payload,
    create_volunteer_payload,
)
from .test_users import TEST_USERS, make_volunteer_headers

DC = TEST_USERS["coordinator_headers"]
CA = TEST_USERS["campus_admin_headers"]


# ─── Logical clock ──────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock and run the sweep. Returns the sweep payload."""
    return get_success_data(api_client.set_clock(to_iso8601, DC))


# ─── Configuration: modules and campuses ────────────────────────────────────

def create_orient_module(validity_days=365,
                         required_contact_types=("SUPERVISED", "UNSUPERVISED"),
                         module_code="ORIENT",
                         title="Volunteer Orientation") -> dict:
    payload = create_training_module_payload(
        module_code=module_code, title=title,
        required_contact_types=list(required_contact_types),
        validity_days=validity_days)
    return get_success_data(api_client.create_training_module(payload, DC))


def create_core_module_never_expires(module_code="CORE") -> dict:
    """Module whose completions never expire (validity_days omitted/null)."""
    payload = create_training_module_payload(
        module_code=module_code, title="Core Orientation",
        required_contact_types=["SUPERVISED", "UNSUPERVISED"],
        validity_days=None)
    return get_success_data(api_client.create_training_module(payload, DC))


def create_campus(name="Lincoln Elementary", campus_code=None,
                  badge_prefix=None) -> dict:
    overrides = {"name": name}
    if campus_code is not None:
        overrides["campus_code"] = campus_code
    if badge_prefix is not None:
        overrides["badge_prefix"] = badge_prefix
    return get_success_data(api_client.create_campus(
        create_campus_payload(**overrides), DC))


def create_lincoln_campus() -> dict:
    """The canonical LNC-prefixed campus used by badge-code scenarios."""
    return get_success_data(api_client.create_campus(
        create_lincoln_campus_payload(), DC))


# ─── Volunteer lifecycle ────────────────────────────────────────────────────

def get_volunteer(volunteer_id: str) -> dict:
    return get_success_data(api_client.get_volunteer(volunteer_id, DC))


def create_volunteer_applied(full_name: str, email: str,
                             contact_type: str = "SUPERVISED") -> dict:
    """Intake only — the volunteer lands in APPLIED."""
    return get_success_data(api_client.create_volunteer(
        create_volunteer_payload(full_name=full_name, email=email,
                                 contact_type=contact_type), DC))


def initiate_background_check(volunteer: dict, level: str = None) -> dict:
    """Initiate a check carrying the volunteer's current version (OCC)."""
    level = level or ("BASIC" if volunteer["contact_type"] == "SUPERVISED"
                      else "ENHANCED")
    return get_success_data(api_client.create_background_check(
        create_background_check_payload(volunteer["id"], volunteer["version"],
                                        level=level), DC))


def record_training(volunteer_id: str, module_id: str,
                    completed_at: str = "2026-07-01T00:00:00Z") -> dict:
    return get_success_data(api_client.create_training_record(
        create_training_record_payload(volunteer_id, module_id, completed_at),
        DC))


def adjudicate_check(check_id: str, findings: str = "NONE") -> dict:
    return get_success_data(api_client.adjudicate_background_check(
        check_id, adjudicate_check_payload(findings), DC))


def create_active_volunteer(full_name: str, email: str,
                            contact_type: str = "SUPERVISED", *,
                            level: str = None, findings: str = "NONE",
                            module: dict = None,
                            completed_at: str = "2026-07-01T00:00:00Z") -> dict:
    """Walk a volunteer to ACTIVE: intake -> check -> training -> adjudicate.

    Returns {"volunteer": <refreshed>, "check": <adjudicated>, "module": ...}.
    """
    module = module or create_orient_module()
    volunteer = create_volunteer_applied(full_name, email, contact_type)
    check = initiate_background_check(volunteer, level=level)
    record_training(volunteer["id"], module["id"], completed_at)
    check = adjudicate_check(check["id"], findings)
    return {"volunteer": get_volunteer(volunteer["id"]), "check": check,
            "module": module}


def create_clearance_granted_volunteer(full_name: str, email: str,
                                       contact_type: str = "SUPERVISED", *,
                                       level: str = None,
                                       module: dict = None) -> dict:
    """Adjudicate before any training record: the volunteer parks in
    CLEARANCE_GRANTED with training still owed."""
    module = module or create_orient_module()
    volunteer = create_volunteer_applied(full_name, email, contact_type)
    check = initiate_background_check(volunteer, level=level)
    check = adjudicate_check(check["id"], "NONE")
    return {"volunteer": get_volunteer(volunteer["id"]), "check": check,
            "module": module}


# ─── Opportunities and placements ───────────────────────────────────────────

def create_open_opportunity(campus_id: str, *, title: str = "Library Help",
                            required_contact_type: str = "SUPERVISED",
                            restricted_category: str = "NONE",
                            capacity: int = 2,
                            starts_at: str = DEFAULT_WINDOW_START,
                            ends_at: str = DEFAULT_WINDOW_END) -> dict:
    """Create an opportunity in DRAFT and publish it to OPEN."""
    opp = get_success_data(api_client.create_opportunity(
        create_opportunity_payload(
            campus_id, title=title, required_contact_type=required_contact_type,
            restricted_category=restricted_category, capacity=capacity,
            starts_at=starts_at, ends_at=ends_at), CA))
    return get_success_data(api_client.publish_opportunity(opp["id"], CA))


def request_placement(opportunity_id: str, volunteer_id: str) -> dict:
    """Self-service placement request by the owning volunteer."""
    return get_success_data(api_client.create_placement(
        create_placement_payload(opportunity_id),
        make_volunteer_headers(volunteer_id)))


def confirm_placement(placement_id: str, headers=None) -> dict:
    return get_success_data(api_client.confirm_placement(
        placement_id, headers or CA))


def get_placement(placement_id: str) -> dict:
    return get_success_data(api_client.get_placement(placement_id, DC))


def get_opportunity(opportunity_id: str) -> dict:
    return get_success_data(api_client.get_opportunity(opportunity_id, CA))


def setup_volunteer_with_confirmed_placement(
        full_name="Placed Pat", email=None, contact_type="SUPERVISED", *,
        findings="NONE", level=None,
        opp_overrides: dict = None) -> dict:
    """ACTIVE volunteer + LNC campus + OPEN opportunity + CONFIRMED placement.

    Returns {"volunteer", "check", "module", "campus", "opportunity",
    "placement"}.
    """
    email = email or f"placed-{full_name.split()[-1].lower()}@example.org"
    module = create_orient_module()
    recruited = create_active_volunteer(full_name, email, contact_type,
                                        level=level, findings=findings,
                                        module=module)
    campus = create_lincoln_campus()
    opp = create_open_opportunity(campus["id"], **(opp_overrides or {}))
    placement = request_placement(opp["id"], recruited["volunteer"]["id"])
    placement = confirm_placement(placement["id"])
    return {"volunteer": recruited["volunteer"], "check": recruited["check"],
            "module": module, "campus": campus, "opportunity": opp,
            "placement": placement}


# ─── Hour entries ───────────────────────────────────────────────────────────

def log_hours(placement_id: str, volunteer_id: str, *, worked_date: str,
              hours: float, activity_category: str = "STANDARD") -> dict:
    """Log a PENDING hour entry as the owning volunteer."""
    return get_success_data(api_client.create_hour_entry(
        create_hour_entry_payload(placement_id, worked_date=worked_date,
                                  hours=hours,
                                  activity_category=activity_category),
        make_volunteer_headers(volunteer_id)))


def verify_entry(entry_id: str, headers=None) -> dict:
    return get_success_data(api_client.verify_hour_entry(entry_id,
                                                         headers or CA))


def log_and_verify_hours(placement_id: str, volunteer_id: str, *,
                         worked_date: str, hours: float,
                         activity_category: str = "STANDARD") -> dict:
    entry = log_hours(placement_id, volunteer_id, worked_date=worked_date,
                      hours=hours, activity_category=activity_category)
    return verify_entry(entry["id"])


# ─── Check-ins ──────────────────────────────────────────────────────────────

def check_in_volunteer(campus_id: str, volunteer_id: str,
                       placement_id: str = None) -> dict:
    """Check the volunteer in (self-service). Optional placement link."""
    return get_success_data(api_client.create_check_in(
        create_check_in_payload(campus_id, placement_id=placement_id),
        make_volunteer_headers(volunteer_id)))


def check_out_volunteer(checkin_id: str, volunteer_id: str) -> dict:
    return get_success_data(api_client.check_out(
        checkin_id, make_volunteer_headers(volunteer_id)))


# ─── Incidents ──────────────────────────────────────────────────────────────

def file_incident(volunteer_id: str, *, severity: str, description: str,
                  placement_id: str = None, headers=None) -> dict:
    payload = create_incident_report_payload(
        volunteer_id, severity=severity, description=description)
    if placement_id is not None:
        payload["placement_id"] = placement_id
    return get_success_data(api_client.create_incident_report(payload,
                                                              headers or CA))


def adjudicate_incident(incident_id: str, outcome: str) -> dict:
    return get_success_data(api_client.adjudicate_incident(
        incident_id, adjudicate_incident_payload(outcome), DC))


# ─── Recognition awards ─────────────────────────────────────────────────────

def grant_manual_award(volunteer: dict, tier: str, note: str = "") -> dict:
    """Grant a manual award carrying the volunteer's current version (OCC)."""
    return get_success_data(api_client.create_recognition_award(
        create_recognition_award_payload(volunteer["id"], tier,
                                         volunteer["version"], note=note),
        DC))


def list_awards_for(volunteer_id: str) -> tuple:
    """Return (awards_list, meta) for a volunteer."""
    return validate_paginated(api_client.list_recognition_awards(
        DC, params={"volunteer_id": volunteer_id}))
