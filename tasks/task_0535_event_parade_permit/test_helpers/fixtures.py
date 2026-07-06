"""Composite setup helpers for the Event Parade Permit API.

Each test runs against a fresh, empty database (the harness restarts the server
before every test). Every fixture builds its preconditions from scratch using
only PRD-declared endpoints, and uses get_success_data() so setup failures
surface as clear "Setup failed" errors.

Identity threading: the Applicant role is entity_backed. After creating an
Applicant we thread its id through make_applicant_headers(applicant_id) for
every ownership-gated call. DepartmentReviewer / PermitOfficer are opaque.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_applicant_headers, make_reviewer_headers, officer_headers,
)
from . import factories as F

# Canonical MEDIUM staffing plan reused across setups.
# Lines (round per line): 4*8*50=1600, 2*6*60=720, 1*8*45=360, 3*4*40=480
#   subtotal 3160 * 1.15 = 3634.00  (cost_recovery_estimate for planned_hours)
STAFFING = {
    "POLICE": {"planned_personnel": 4, "planned_hours": 8, "hourly_rate": 50},
    "FIRE": {"planned_personnel": 2, "planned_hours": 6, "hourly_rate": 60},
    "EMS": {"planned_personnel": 1, "planned_hours": 8, "hourly_rate": 45},
    "PUBLIC_WORKS": {"planned_personnel": 3, "planned_hours": 4, "hourly_rate": 40},
}
DEPT_ORDER = ["POLICE", "FIRE", "EMS", "PUBLIC_WORKS"]


# --------------------------------------------------------------------------
# Base building blocks
# --------------------------------------------------------------------------
def set_clock(to_iso8601="2026-05-15T00:00:00Z"):
    return get_success_data(api_client.set_clock(to_iso8601, officer_headers()))


def create_venue(**overrides):
    """Create a venue. Returns the Venue dict."""
    return get_success_data(
        api_client.create_venue(F.create_venue_payload(**overrides), officer_headers())
    )


def create_closure_schedule(**overrides):
    return get_success_data(
        api_client.create_closure_schedule(
            F.create_closure_schedule_payload(**overrides), officer_headers())
    )


def create_applicant(**overrides):
    """Register an applicant (officer acts on their behalf). Returns Applicant dict."""
    return get_success_data(
        api_client.create_applicant(F.create_applicant_payload(**overrides), officer_headers())
    )


def create_application(venue_id, applicant_id, **overrides):
    """Create a DRAFT application owned by applicant_id. Returns PermitApplication dict."""
    hdrs = make_applicant_headers(applicant_id)
    return get_success_data(
        api_client.create_application(
            F.create_application_payload(venue_id, **overrides), hdrs)
    )


def add_segment(app_id, applicant_id, closure_schedule_id, **overrides):
    hdrs = make_applicant_headers(applicant_id)
    return get_success_data(
        api_client.add_route_segment(
            app_id, F.create_route_segment_payload(closure_schedule_id, **overrides), hdrs)
    )


def get_venue_version(venue_id):
    v = get_success_data(api_client.get_venue(venue_id, officer_headers()))
    return v["version"]


def get_reviews_by_department(app_id):
    """Return {POLICE: id, FIRE: id, EMS: id, PUBLIC_WORKS: id} for the app's reviews."""
    data = get_success_data(api_client.list_reviews(app_id, officer_headers()))
    mapping = {}
    for r in data:
        mapping[r["department"]] = r["id"]
    return mapping


# --------------------------------------------------------------------------
# Tier 1 / Tier 2: reach UNDER_REVIEW with a route plan
# --------------------------------------------------------------------------
def setup_draft_with_segment(attendance=3000, buffer=60, max_capacity=6000,
                             venue_type="PARK", event_kind="FESTIVAL",
                             occupy_start="2026-06-01T10:00:00Z",
                             occupy_end="2026-06-01T14:00:00Z",
                             closure_start="2026-06-01T09:00:00Z",
                             closure_end="2026-06-01T15:00:00Z",
                             set_clock_first=False):
    """DRAFT application with exactly one PLANNED route segment.

    Returns dict with keys: venue, schedule, applicant, application, venue_v0.
    """
    if set_clock_first:
        set_clock()
    venue = create_venue(max_capacity=max_capacity, setup_buffer_minutes=buffer,
                         venue_type=venue_type)
    schedule = create_closure_schedule()
    applicant = create_applicant()
    app = create_application(venue["id"], applicant["id"], event_kind=event_kind,
                            expected_attendance=attendance,
                            occupy_start=occupy_start, occupy_end=occupy_end)
    add_segment(app["id"], applicant["id"], schedule["id"],
                closure_start=closure_start, closure_end=closure_end)
    return {
        "venue": venue, "schedule": schedule, "applicant": applicant,
        "application": app, "venue_v0": venue["version"],
    }


def setup_under_review(**overrides):
    """Submit a DRAFT-with-segment for review -> UNDER_REVIEW with four PENDING reviews.

    Returns dict adding: reviews (dept->id map), venue_v_after_submit.
    """
    ctx = setup_draft_with_segment(**overrides)
    hdrs = make_applicant_headers(ctx["applicant"]["id"])
    get_success_data(api_client.submit_for_review(
        ctx["application"]["id"],
        {"expected_venue_version": ctx["venue_v0"]},
        hdrs))
    ctx["reviews"] = get_reviews_by_department(ctx["application"]["id"])
    ctx["venue_v_after_submit"] = get_venue_version(ctx["venue"]["id"])
    return ctx


def approve_all_reviews(app_id, reviews, staffing=None):
    """Approve all four department reviews with the canonical staffing plan.
    The fourth approval fires quorum -> CONDITIONALLY_APPROVED + Invoice (ESTIMATE)."""
    staffing = staffing or STAFFING
    for dept in DEPT_ORDER:
        get_success_data(api_client.approve_review(
            app_id, reviews[dept], staffing[dept], make_reviewer_headers(dept)))


# --------------------------------------------------------------------------
# Tier 3: reach CONDITIONALLY_APPROVED / ISSUED
# --------------------------------------------------------------------------
def setup_conditionally_approved(**overrides):
    """Full path to CONDITIONALLY_APPROVED (all four reviews APPROVED, Invoice created).

    Returns dict from setup_under_review plus nothing new (application status advanced).
    """
    ctx = setup_under_review(**overrides)
    approve_all_reviews(ctx["application"]["id"], ctx["reviews"])
    return ctx


def submit_and_accept_coi(app_id, applicant_id, coverage_amount=1_200_000,
                          expires_at="2027-01-01T00:00:00Z"):
    """Submit a COI and have the officer accept it. Returns the COI dict (post-accept read)."""
    coi = get_success_data(api_client.submit_coi(
        app_id, F.create_coi_payload(coverage_amount=coverage_amount, expires_at=expires_at),
        make_applicant_headers(applicant_id)))
    get_success_data(api_client.accept_coi(app_id, coi["id"], officer_headers()))
    return coi


def pay_deposit(app_id, applicant_id, amount=500):
    return get_success_data(api_client.pay_deposit(
        app_id, F.create_deposit_payload(amount), make_applicant_headers(applicant_id)))


def setup_issued(deposit_amount=500, coverage_amount=1_200_000,
                 coi_expires_at="2027-01-01T00:00:00Z", **overrides):
    """Full lifecycle to ISSUED: conditionally-approved + COI accepted + deposit held + issue.

    Returns dict from setup_conditionally_approved plus: coi, deposit.
    """
    overrides.setdefault("set_clock_first", True)
    ctx = setup_conditionally_approved(**overrides)
    app_id = ctx["application"]["id"]
    applicant_id = ctx["applicant"]["id"]
    ctx["coi"] = submit_and_accept_coi(app_id, applicant_id,
                                       coverage_amount=coverage_amount,
                                       expires_at=coi_expires_at)
    ctx["deposit"] = pay_deposit(app_id, applicant_id, deposit_amount)
    get_success_data(api_client.issue_application(app_id, officer_headers()))
    return ctx


# --------------------------------------------------------------------------
# Tier 5: debrief / terminal
# --------------------------------------------------------------------------
def setup_debrief_open(cleanup_charges=0, actual_attendance=3000,
                       incident_count=0, deposit_amount=500, **overrides):
    """ISSUED application with an OPEN debrief. Returns setup_issued ctx plus: debrief."""
    ctx = setup_issued(deposit_amount=deposit_amount, **overrides)
    app_id = ctx["application"]["id"]
    ctx["debrief"] = get_success_data(api_client.open_debrief(
        app_id,
        F.open_debrief_payload(actual_attendance, cleanup_charges=cleanup_charges,
                               incident_count=incident_count),
        officer_headers()))
    return ctx


def log_all_actuals(app_id, reviews, actual_hours_map):
    """Log per-department actual_hours (dept -> hours) while ISSUED."""
    for dept, hours in actual_hours_map.items():
        get_success_data(api_client.log_actuals(
            app_id, reviews[dept], {"actual_hours": hours}, make_reviewer_headers(dept)))
