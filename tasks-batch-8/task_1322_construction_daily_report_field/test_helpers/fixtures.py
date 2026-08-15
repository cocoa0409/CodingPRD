"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so all preconditions are built from scratch here via the
PRD's public endpoints. All helpers use get_success_data (lenient) so a setup
failure surfaces as a clear setup error rather than a confusing assertion.

Tiers:
  Tier 1: single-entity creation (project/area/zone/work item/report)
  Tier 2: child-entry makers (crew/equipment/weather/delay/safety/incident/
          media/delivery/quantity/ticket/distribution)
  Tier 3: report and ticket lifecycle shortcuts (submitted/under-review/
          approved/locked; fully-signed ticket)
  Tier 4: exact-state targeting (classified delay, partial delivery)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_crew_entry_payload,
    create_daily_report_payload,
    create_delay_event_payload,
    create_delivery_payload,
    create_delivery_zone_payload,
    create_distribution_record_payload,
    create_equipment_entry_payload,
    create_incident_payload,
    create_media_attachment_payload,
    create_project_payload,
    create_quantity_entry_payload,
    create_safety_observation_payload,
    create_tm_ticket_payload,
    create_weather_observation_payload,
    create_work_area_payload,
    create_work_item_payload,
)
from .test_users import (
    TEST_USERS,
    make_contractor_rep_headers,
    make_owner_rep_headers,
    make_project_manager_headers,
    make_safety_officer_headers,
    make_superintendent_headers,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_SUPT = TEST_USERS["superintendent_headers"]      # X-User-ID: supt-1
_PM = TEST_USERS["project_manager_headers"]       # X-User-ID: pm-1
_SO = TEST_USERS["safety_officer_headers"]        # X-User-ID: so-1
_CTR = TEST_USERS["contractor_rep_headers"]       # X-User-ID: ctr-1
_OWNER = TEST_USERS["owner_rep_headers"]          # X-User-ID: owner-1


def submit_clock_for(report_date: str) -> str:
    """A logical-clock instant after the workday of `report_date`."""
    return f"{report_date}T17:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, _ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def make_project(**overrides):
    """Create a MOBILIZING project."""
    return get_success_data(api_client.create_project(create_project_payload(**overrides),
                                                      _ADMIN))


def make_active_project(**overrides):
    """Create + activate. Returns the ACTIVE project."""
    project = make_project(**overrides)
    return get_success_data(api_client.activate_project(project["id"], _ADMIN))


def make_work_area(project_id, **overrides):
    return get_success_data(api_client.create_work_area(
        create_work_area_payload(project_id, **overrides), _ADMIN))


def make_delivery_zone(project_id, **overrides):
    return get_success_data(api_client.create_delivery_zone(
        create_delivery_zone_payload(project_id, **overrides), _ADMIN))


def make_work_item(project_id, **overrides):
    return get_success_data(api_client.create_work_item(
        create_work_item_payload(project_id, **overrides), _ADMIN))


def make_report(project_id, user_id="supt-1", **overrides):
    """Create a DRAFT daily report as a Superintendent."""
    return get_success_data(api_client.create_daily_report(
        create_daily_report_payload(project_id, **overrides),
        make_superintendent_headers(user_id)))


# ---------------------------------------------------------------------------
# Tier 2: child-entry makers
# ---------------------------------------------------------------------------

def add_crew_entry(report_id, work_area_id, user_id="supt-1", **overrides):
    return get_success_data(api_client.create_crew_entry(
        create_crew_entry_payload(report_id, work_area_id, **overrides),
        make_superintendent_headers(user_id)))


def add_equipment_entry(report_id, work_area_id, user_id="supt-1", **overrides):
    return get_success_data(api_client.create_equipment_entry(
        create_equipment_entry_payload(report_id, work_area_id, **overrides),
        make_superintendent_headers(user_id)))


def add_weather_observation(report_id, user_id="supt-1", **overrides):
    return get_success_data(api_client.create_weather_observation(
        create_weather_observation_payload(report_id, **overrides),
        make_superintendent_headers(user_id)))


def add_delay_event(report_id, work_area_id, user_id="supt-1", **overrides):
    return get_success_data(api_client.create_delay_event(
        create_delay_event_payload(report_id, work_area_id, **overrides),
        make_superintendent_headers(user_id)))


def add_safety_observation(report_id, work_area_id, user_id="so-1", **overrides):
    return get_success_data(api_client.create_safety_observation(
        create_safety_observation_payload(report_id, work_area_id, **overrides),
        make_safety_officer_headers(user_id)))


def add_incident(report_id, work_area_id, user_id="so-1", **overrides):
    """Create an incident as a SafetyOfficer (report must not be LOCKED)."""
    return get_success_data(api_client.create_incident(
        create_incident_payload(report_id, work_area_id, **overrides),
        make_safety_officer_headers(user_id)))


def add_media(report_id, work_area_id, role="Superintendent", user_id="supt-1",
              **overrides):
    headers = (make_safety_officer_headers(user_id) if role == "SafetyOfficer"
               else make_superintendent_headers(user_id))
    return get_success_data(api_client.create_media_attachment(
        create_media_attachment_payload(report_id, work_area_id, **overrides), headers))


def add_delivery(report_id, delivery_zone_id, user_id="supt-1", **overrides):
    return get_success_data(api_client.create_delivery(
        create_delivery_payload(report_id, delivery_zone_id, **overrides),
        make_superintendent_headers(user_id)))


def add_quantity_entry(report_id, work_item_id, work_area_id, quantity_installed,
                       user_id="supt-1"):
    """Create a QuantityEntry, transparently carrying the report's CURRENT
    version in expected_report_version (PRD section 2.7 OCC guard)."""
    current = get_success_data(api_client.get_daily_report(report_id, _ADMIN))
    return get_success_data(api_client.create_quantity_entry(
        create_quantity_entry_payload(
            report_id, work_item_id, work_area_id,
            expected_report_version=current["version"],
            quantity_installed=quantity_installed),
        make_superintendent_headers(user_id)))


def add_tm_ticket(report_id, work_item_id, user_id="supt-1", **overrides):
    return get_success_data(api_client.create_tm_ticket(
        create_tm_ticket_payload(report_id, work_item_id, **overrides),
        make_superintendent_headers(user_id)))


def add_distribution_record(report_id, user_id="pm-1", **overrides):
    return get_success_data(api_client.create_distribution_record(
        create_distribution_record_payload(report_id, **overrides),
        make_project_manager_headers(user_id)))


# ---------------------------------------------------------------------------
# Tier 2b: readers (thin, lenient)
# ---------------------------------------------------------------------------

def get_report(report_id):
    return get_success_data(api_client.get_daily_report(report_id, _ADMIN))


def get_work_item(work_item_id):
    return get_success_data(api_client.get_work_item(work_item_id, _ADMIN))


def get_project(project_id):
    return get_success_data(api_client.get_project(project_id, _ADMIN))


def get_delivery(delivery_id):
    return get_success_data(api_client.get_delivery(delivery_id, _ADMIN))


def get_incident(incident_id):
    return get_success_data(api_client.get_incident(incident_id, _ADMIN))


def get_distribution_record(record_id):
    return get_success_data(api_client.get_distribution_record(record_id, _ADMIN))


def get_quantity_entry(entry_id):
    return get_success_data(api_client.get_quantity_entry(entry_id, _ADMIN))


def get_safety_observation(observation_id):
    return get_success_data(api_client.get_safety_observation(observation_id, _ADMIN))


def get_delay_event(event_id):
    return get_success_data(api_client.get_delay_event(event_id, _ADMIN))


def get_tm_ticket(ticket_id):
    return get_success_data(api_client.get_tm_ticket(ticket_id, _ADMIN))


def get_progress_summary(project_id):
    return get_success_data(api_client.get_progress_summary(project_id, _ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: report lifecycle shortcuts
# ---------------------------------------------------------------------------

def submit_report(report_id, user_id="supt-1"):
    return get_success_data(api_client.submit_report(
        report_id, make_superintendent_headers(user_id)))


def start_review(report_id, user_id="pm-1"):
    return get_success_data(api_client.start_review_report(
        report_id, make_project_manager_headers(user_id)))


def approve_report(report_id, user_id="pm-1"):
    return get_success_data(api_client.approve_report(
        report_id, make_project_manager_headers(user_id)))


def lock_report(report_id):
    return get_success_data(api_client.lock_report(report_id, _ADMIN))


def make_report_bundle(report_date="2026-08-05", project_overrides=None,
                       with_weather=True, with_crew=True):
    """ACTIVE project + OPEN area + DRAFT report (+ weather + crew entries).

    Returns a dict: {project, area, report}. This is the most common setup for
    report-lifecycle tests.
    """
    project = make_active_project(**(project_overrides or {}))
    area = make_work_area(project["id"])
    report = make_report(project["id"], report_date=report_date)
    if with_weather:
        add_weather_observation(report["id"],
                                observed_at=f"{report_date}T08:00:00Z")
    if with_crew:
        add_crew_entry(report["id"], area["id"])
    return {"project": project, "area": area, "report": get_report(report["id"])}


def make_submitted_report(report_date="2026-08-05", project_overrides=None,
                          submitter="supt-1"):
    """DRAFT (with weather + crew) -> SUBMITTED. Clock is left at end-of-day."""
    ctx = make_report_bundle(report_date=report_date,
                             project_overrides=project_overrides)
    set_clock(submit_clock_for(report_date))
    ctx["report"] = submit_report(ctx["report"]["id"], user_id=submitter)
    return ctx


def make_under_review_report(**kwargs):
    ctx = make_submitted_report(**kwargs)
    ctx["report"] = start_review(ctx["report"]["id"])
    return ctx


def make_approved_report(**kwargs):
    ctx = make_under_review_report(**kwargs)
    ctx["report"] = approve_report(ctx["report"]["id"])
    return ctx


def make_locked_report(**kwargs):
    ctx = make_approved_report(**kwargs)
    ctx["report"] = lock_report(ctx["report"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3b: T&M ticket lifecycle shortcuts
# ---------------------------------------------------------------------------

def make_pending_signature_ticket(report_id, work_item_id, creator="supt-1",
                                  **ticket_overrides):
    """DRAFT ticket -> PENDING_SIGNATURES."""
    ticket = add_tm_ticket(report_id, work_item_id, user_id=creator,
                           **ticket_overrides)
    return get_success_data(api_client.submit_ticket_for_signature(
        ticket["id"], make_superintendent_headers(creator)))


def make_fully_signed_ticket(report_id, work_item_id, creator="supt-1",
                             contractor="ctr-1", owner="owner-1",
                             **ticket_overrides):
    """DRAFT -> PENDING_SIGNATURES -> PARTIALLY_SIGNED -> FULLY_SIGNED."""
    ticket = make_pending_signature_ticket(report_id, work_item_id, creator=creator,
                                           **ticket_overrides)
    get_success_data(api_client.sign_ticket(
        ticket["id"], {"signer_role": "CONTRACTOR"},
        make_contractor_rep_headers(contractor)))
    return get_success_data(api_client.sign_ticket(
        ticket["id"], {"signer_role": "OWNER"},
        make_owner_rep_headers(owner)))


# ---------------------------------------------------------------------------
# Tier 4: exact-state targeting
# ---------------------------------------------------------------------------

def make_classified_delay(report_id, work_area_id, classification,
                          start_at="2026-08-05T09:00:00Z",
                          end_at="2026-08-05T10:00:00Z", cause="OWNER",
                          classifier="pm-1"):
    """RECORDED delay event -> CLASSIFIED with the given classification."""
    event = add_delay_event(report_id, work_area_id, start_at=start_at,
                            end_at=end_at, cause=cause)
    return get_success_data(api_client.classify_delay_event(
        event["id"], {"classification": classification},
        make_project_manager_headers(classifier)))


def make_partial_delivery(report_id, zone_id, delivered_qty=100, accepted=60,
                          rejected=25):
    """Delivery inspected only partially -> PARTIAL with a pending remainder."""
    delivery = add_delivery(report_id, zone_id, delivered_qty=delivered_qty)
    return get_success_data(api_client.inspect_delivery(
        delivery["id"], {"accepted_qty": accepted, "rejected_qty": rejected}, _SUPT))
