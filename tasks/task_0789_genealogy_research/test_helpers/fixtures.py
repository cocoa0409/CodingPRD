"""Composite setup helpers for the Genealogy Research API.

Each test runs against a freshly-reset, empty database, so every helper builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls
use get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion later.

Identity threading: the Client and Researcher roles are entity-backed. Whenever a
call is ownership-gated (deliverable accept/request-revision) or identity-stamped
(record searches, time entries), the acting header carries the real entity id via
make_client_headers()/make_researcher_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_client_headers, make_researcher_headers
from .factories import (
    create_client_payload, create_researcher_payload, create_repository_payload,
    create_project_payload, create_record_search_payload, create_citation_payload,
    create_person_payload, create_dna_payload, create_document_request_payload,
    create_heirloom_payload, create_deliverable_payload, create_milestone_payload,
    create_time_entry_payload, create_appointment_payload,
)

PM = TEST_USERS["project_manager_headers"]


# --------------------------------------------------------------------------
# Tier 1: primitive provisioning
# --------------------------------------------------------------------------
def provision_client(tier=None, email=None, name="Test Client"):
    resp = api_client.create_client(
        create_client_payload(name=name, email=email, tier=tier), PM)
    return get_success_data(resp)


def provision_researcher(email=None, name="Test Researcher", hourly_rate_cents=9000):
    resp = api_client.create_researcher(
        create_researcher_payload(name=name, email=email,
                                  hourly_rate_cents=hourly_rate_cents), PM)
    return get_success_data(resp)


def provision_repository(concurrent_capacity=None, name="Test Repository", location="London"):
    resp = api_client.create_repository(
        create_repository_payload(name=name, location=location,
                                  concurrent_capacity=concurrent_capacity), PM)
    return get_success_data(resp)


def create_draft_project(client_id, researcher_id, **overrides):
    resp = api_client.create_project(
        create_project_payload(client_id=client_id, lead_researcher_id=researcher_id,
                               **overrides), PM)
    return get_success_data(resp)


def create_active_project(client_tier=None, **project_overrides):
    """Provision a client + researcher, open a project, and activate it.

    Returns (client, researcher, project) with the project in ACTIVE.
    """
    client = provision_client(tier=client_tier)
    researcher = provision_researcher()
    project = create_draft_project(client["id"], researcher["id"], **project_overrides)
    activated = get_success_data(api_client.activate_project(project["id"], PM))
    return client, researcher, activated


# --------------------------------------------------------------------------
# Tier 2: research substrate (searches, persons, citations)
# --------------------------------------------------------------------------
def create_completed_search(project_id, researcher_id, estimated_hours=1,
                            repository_name="Archive", search_terms="query",
                            result_summary=None):
    """Create a record search on an ACTIVE project and drive it to COMPLETED."""
    rh = make_researcher_headers(researcher_id)
    search = get_success_data(api_client.create_record_search(
        create_record_search_payload(project_id=project_id, estimated_hours=estimated_hours,
                                     repository_name=repository_name,
                                     search_terms=search_terms), rh))
    payload = {"outcome": "COMPLETED"}
    if result_summary is not None:
        payload["result_summary"] = result_summary
    get_success_data(api_client.complete_record_search(search["id"], payload, rh))
    return search


def create_person(project_id, researcher_id, full_name="Test Person", **overrides):
    rh = make_researcher_headers(researcher_id)
    resp = api_client.create_person(
        create_person_payload(project_id=project_id, full_name=full_name, **overrides), rh)
    return get_success_data(resp)


def add_citation(search_id, person_id, researcher_id, quality="PRIMARY",
                 source_type="VITAL_RECORD", citation_text="Citation", verify=False):
    """Attach a citation to a person from a completed search; optionally verify it."""
    rh = make_researcher_headers(researcher_id)
    citation = get_success_data(api_client.create_citation(
        create_citation_payload(record_search_id=search_id, person_id=person_id,
                               citation_text=citation_text, source_type=source_type,
                               quality=quality), rh))
    if verify:
        get_success_data(api_client.verify_citation(citation["id"], rh))
    return citation


def setup_person_under_review(project_id, researcher_id, full_name="Under Review Person"):
    """Create a person and submit it for review (DRAFT -> UNDER_REVIEW)."""
    person = create_person(project_id, researcher_id, full_name=full_name)
    rh = make_researcher_headers(researcher_id)
    get_success_data(api_client.submit_review_person(person["id"], rh))
    return person


def setup_verified_person(project_id, researcher_id, full_name="Verified Person"):
    """Drive a person to VERIFIED via two PRIMARY citations (auto-verifies on the
    second citation-verify: 2 verified citations, confidence 1.00 >= 0.75).

    Returns the person as read back after verification.
    """
    person = setup_person_under_review(project_id, researcher_id, full_name=full_name)
    search = create_completed_search(project_id, researcher_id, search_terms="verify-src")
    add_citation(search["id"], person["id"], researcher_id, quality="PRIMARY",
                 source_type="VITAL_RECORD", citation_text="Birth", verify=True)
    add_citation(search["id"], person["id"], researcher_id, quality="PRIMARY",
                 source_type="CHURCH", citation_text="Baptism", verify=True)
    rh = make_researcher_headers(researcher_id)
    return get_success_data(api_client.get_person(person["id"], rh))


# --------------------------------------------------------------------------
# Tier 3: time entries
# --------------------------------------------------------------------------
def log_time(project_id, researcher_id, hours, activity_type="RESEARCH", billable=True):
    """Log a time entry; returns the raw Response so callers can assert success or error."""
    rh = make_researcher_headers(researcher_id)
    return api_client.create_time_entry(
        create_time_entry_payload(project_id=project_id, hours=hours,
                                  activity_type=activity_type, billable=billable), rh)


def log_time_data(project_id, researcher_id, hours, activity_type="RESEARCH", billable=True):
    """Like log_time but asserts success and returns the created entity."""
    return get_success_data(log_time(project_id, researcher_id, hours,
                                     activity_type=activity_type, billable=billable))


# --------------------------------------------------------------------------
# Tier 4: deliverables + milestone billing
# --------------------------------------------------------------------------
def create_submitted_deliverable(project_id, researcher_id, deliverable_type="RESEARCH_REPORT",
                                 milestone_id=None):
    """Create a deliverable and submit it (DRAFT -> SUBMITTED)."""
    rh = make_researcher_headers(researcher_id)
    deliverable = get_success_data(api_client.create_deliverable(
        create_deliverable_payload(project_id=project_id, deliverable_type=deliverable_type,
                                   milestone_id=milestone_id), rh))
    get_success_data(api_client.submit_deliverable(deliverable["id"], rh))
    return deliverable


def create_milestone(project_id, amount_cents=40000, sequence_no=1, title="Milestone"):
    resp = api_client.create_milestone(
        create_milestone_payload(project_id=project_id, title=title,
                                 amount_cents=amount_cents, sequence_no=sequence_no), PM)
    return get_success_data(resp)


def setup_ready_milestone(project_id, researcher_id, client_id, amount_cents=40000,
                          sequence_no=1, deliverable_type="RESEARCH_REPORT"):
    """Milestone driven to READY via an accepted deliverable that links it.

    Returns (milestone, deliverable) both freshly read back.
    """
    milestone = create_milestone(project_id, amount_cents=amount_cents,
                                 sequence_no=sequence_no)
    deliverable = create_submitted_deliverable(project_id, researcher_id,
                                               deliverable_type=deliverable_type,
                                               milestone_id=milestone["id"])
    get_success_data(api_client.accept_deliverable(
        deliverable["id"], make_client_headers(client_id)))
    milestone = get_success_data(api_client.get_milestone(milestone["id"], PM))
    return milestone, deliverable


def setup_invoiced_milestone(project_id, researcher_id, client_id, amount_cents=40000,
                             sequence_no=1, deliverable_type="RESEARCH_REPORT"):
    """Milestone driven all the way to INVOICED. Returns the invoiced milestone."""
    milestone, _ = setup_ready_milestone(project_id, researcher_id, client_id,
                                         amount_cents=amount_cents, sequence_no=sequence_no,
                                         deliverable_type=deliverable_type)
    return get_success_data(api_client.invoice_milestone(milestone["id"], PM))


# --------------------------------------------------------------------------
# Tier 5: repository appointments
# --------------------------------------------------------------------------
def book_appointment(project_id, researcher_id, repository_id,
                     start_utc="2026-04-01T09:00:00Z", end_utc="2026-04-01T10:00:00Z"):
    """Book an appointment; returns the raw Response (may be success or error)."""
    return api_client.create_appointment(
        create_appointment_payload(repository_id=repository_id, project_id=project_id,
                                   researcher_id=researcher_id, start_utc=start_utc,
                                   end_utc=end_utc), make_researcher_headers(researcher_id))


def setup_project_with_booked_appointment(concurrent_capacity=5,
                                          start_utc="2026-04-01T09:00:00Z",
                                          end_utc="2026-04-01T10:00:00Z"):
    """Active project + repository + one BOOKED appointment for the lead researcher.

    Returns (client, researcher, project, repository, appointment).
    """
    client, researcher, project = create_active_project()
    repo = provision_repository(concurrent_capacity=concurrent_capacity)
    appt = get_success_data(book_appointment(project["id"], researcher["id"], repo["id"],
                                             start_utc=start_utc, end_utc=end_utc))
    return client, researcher, project, repo, appt


def setup_repo_capacity_scenario(concurrent_capacity=1,
                                 start_utc="2026-04-01T09:00:00Z",
                                 end_utc="2026-04-01T10:00:00Z"):
    """Repository at concurrent_capacity with one BOOKED appointment by researcher1,
    plus a second distinct researcher available to attempt an overlapping booking.

    Returns (client, researcher1, researcher2, project, repository, appointment1).
    """
    client = provision_client()
    researcher1 = provision_researcher(name="Researcher One")
    researcher2 = provision_researcher(name="Researcher Two")
    project = create_draft_project(client["id"], researcher1["id"])
    project = get_success_data(api_client.activate_project(project["id"], PM))
    repo = provision_repository(concurrent_capacity=concurrent_capacity)
    appt1 = get_success_data(book_appointment(project["id"], researcher1["id"], repo["id"],
                                              start_utc=start_utc, end_utc=end_utc))
    return client, researcher1, researcher2, project, repo, appt1
