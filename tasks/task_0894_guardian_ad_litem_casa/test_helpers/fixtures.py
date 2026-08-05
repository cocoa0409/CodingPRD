"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, because the server (and its DB) is restarted
before every individual test. Setup calls use the lenient get_success_data so a
broken precondition surfaces as a clear "Setup failed" rather than a confusing
assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_supervisor_headers,
    make_volunteer_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# ------------------------------------------------------------------ primitives
def set_clock(api, iso):
    return get_success_data(api.set_clock(iso, ADMIN))


def create_supervisor(api, email="s1@casa.org", full_name="Sup One"):
    return get_success_data(
        api.create_supervisor({"full_name": full_name, "email": email}, ADMIN)
    )


def register_volunteer(api, email="v1@casa.org", home_zip="94601",
                       full_name="Val One", max_caseload=None):
    payload = {"full_name": full_name, "email": email, "home_zip": home_zip}
    if max_caseload is not None:
        payload["max_caseload"] = max_caseload
    return get_success_data(api.create_volunteer(payload, ADMIN))


def create_volunteer_in_training(api, email="v1@casa.org", home_zip="94601",
                                 full_name="Val One", training_hours=30,
                                 completed_at="2026-06-01T00:00:00Z",
                                 check_type="STATE_AND_FEDERAL"):
    """Register -> SCREENING -> (bg cleared, auto TRAINING) -> log training hours.

    Leaves the volunteer in TRAINING with the given training_hours_total.
    """
    vol = register_volunteer(api, email=email, home_zip=home_zip, full_name=full_name)
    vid = vol["id"]
    get_success_data(api.start_screening(vid, ADMIN))
    bg = get_success_data(api.create_background_check(vid, {"check_type": check_type}, ADMIN))
    get_success_data(api.clear_background_check(bg["id"], ADMIN))
    get_success_data(api.create_training_record(
        vid, {"module_name": "CORE", "hours": training_hours, "completed_at": completed_at}, ADMIN))
    return get_success_data(api.get_volunteer(vid, ADMIN))


def onboard_active_volunteer(api, email="v1@casa.org", home_zip="94601",
                             full_name="Val One", max_caseload=None,
                             training_hours=30, completed_at="2026-06-01T00:00:00Z",
                             check_type="STATE_AND_FEDERAL"):
    """Full PROSPECT -> ACTIVE onboarding. Returns the sworn-in Volunteer."""
    vol = register_volunteer(api, email=email, home_zip=home_zip,
                             full_name=full_name, max_caseload=max_caseload)
    vid = vol["id"]
    get_success_data(api.start_screening(vid, ADMIN))
    bg = get_success_data(api.create_background_check(vid, {"check_type": check_type}, ADMIN))
    get_success_data(api.clear_background_check(bg["id"], ADMIN))
    get_success_data(api.create_training_record(
        vid, {"module_name": "CORE", "hours": training_hours, "completed_at": completed_at}, ADMIN))
    get_success_data(api.swear_in(vid, ADMIN))
    return get_success_data(api.get_volunteer(vid, ADMIN))


def create_case(api, supervisor_id, budget=None, child_initials="J.D.",
                child_dob="2018-04-01", jurisdiction="CA-ALAMEDA"):
    payload = {
        "child_initials": child_initials,
        "child_dob": child_dob,
        "jurisdiction": jurisdiction,
        "supervisor_id": supervisor_id,
    }
    if budget is not None:
        payload["reimbursement_budget_cents"] = budget
    return get_success_data(api.create_case(payload, ADMIN))


def assign_volunteer(api, case_id, volunteer_id, supervisor_id, expected_version):
    return get_success_data(api.create_assignment(
        case_id,
        {"volunteer_id": volunteer_id, "expected_case_version": expected_version},
        make_supervisor_headers(supervisor_id),
    ))


# --------------------------------------------------------- workhorse composite
def setup_active_volunteer_assigned_case(api, budget=None, max_caseload=None,
                                         clock=DEFAULT_CLOCK,
                                         volunteer_email="v1@casa.org",
                                         supervisor_email="s1@casa.org"):
    """Clock set + Supervisor + ACTIVE Volunteer + Case with the volunteer
    ASSIGNED. Returns a dict of the built entities, their ids, the case version
    observed after assignment, and ready-to-use ownership headers.
    """
    set_clock(api, clock)
    sup = create_supervisor(api, email=supervisor_email)
    vol = onboard_active_volunteer(api, email=volunteer_email, max_caseload=max_caseload)
    case = create_case(api, sup["id"], budget=budget)
    sup_headers = make_supervisor_headers(sup["id"])
    assignment = get_success_data(api.create_assignment(
        case["id"],
        {"volunteer_id": vol["id"], "expected_case_version": case["version"]},
        sup_headers,
    ))
    case_after = get_success_data(api.get_case(case["id"], sup_headers))
    return {
        "supervisor": sup,
        "volunteer": vol,
        "case": case_after,
        "assignment": assignment,
        "supervisor_id": sup["id"],
        "volunteer_id": vol["id"],
        "case_id": case["id"],
        "assignment_id": assignment["id"],
        "case_version": case_after["version"],
        "supervisor_headers": sup_headers,
        "volunteer_headers": make_volunteer_headers(vol["id"]),
    }


def setup_case_with_hearing(api, scheduled_at="2026-07-20T09:00:00Z",
                            hearing_type="STATUS", budget=None):
    """Active-volunteer-assigned case plus one SCHEDULED hearing."""
    base = setup_active_volunteer_assigned_case(api, budget=budget)
    hearing = get_success_data(api.create_hearing(
        base["case_id"], {"hearing_type": hearing_type, "scheduled_at": scheduled_at},
        base["supervisor_headers"]))
    base["hearing"] = hearing
    base["hearing_id"] = hearing["id"]
    return base


def setup_draft_report(api, scheduled_at="2026-07-20T09:00:00Z"):
    """Case + SCHEDULED hearing + a DRAFT court report authored by the volunteer."""
    base = setup_case_with_hearing(api, scheduled_at=scheduled_at)
    report = get_success_data(api.create_court_report(
        base["case_id"],
        {"hearing_id": base["hearing_id"], "content_summary": "s", "recommendation": "r"},
        base["volunteer_headers"]))
    base["report"] = report
    base["report_id"] = report["id"]
    return base


def setup_submitted_report(api, scheduled_at="2026-07-20T09:00:00Z"):
    """DRAFT report advanced to SUBMITTED (clock stays at DEFAULT_CLOCK, which is
    well before the report_due_date)."""
    base = setup_draft_report(api, scheduled_at=scheduled_at)
    get_success_data(api.submit_report(base["report_id"], base["volunteer_headers"]))
    base["report"] = get_success_data(
        api.get_court_report(base["report_id"], base["supervisor_headers"]))
    return base


def setup_submitted_expense(api, budget=20000, total_miles=120,
                            other_expense_cents=6000, period_month="2026-06"):
    """Case + ACTIVE volunteer + one SUBMITTED expense claim."""
    base = setup_active_volunteer_assigned_case(api, budget=budget)
    claim = get_success_data(api.create_expense_claim(
        {
            "case_id": base["case_id"],
            "period_month": period_month,
            "total_miles": total_miles,
            "other_expense_cents": other_expense_cents,
        },
        base["volunteer_headers"],
    ))
    base["expense_claim"] = claim
    base["expense_claim_id"] = claim["id"]
    return base


def log_standard_compliance_visits(api, base):
    """Log the canonical compliance visit set on the case and advance the clock
    into July: June has 2 IN_PERSON + 1 VIDEO, July has 1 IN_PERSON, all by the
    assigned volunteer and non-overlapping. Clock ends at 2026-07-05.
    """
    cid = base["case_id"]
    vh = base["volunteer_headers"]
    get_success_data(api.create_visit(cid, {
        "contact_type": "IN_PERSON",
        "contact_start": "2026-06-05T10:00:00Z",
        "contact_end": "2026-06-05T11:00:00Z", "miles": 12}, vh))
    get_success_data(api.create_visit(cid, {
        "contact_type": "IN_PERSON",
        "contact_start": "2026-06-12T10:00:00Z",
        "contact_end": "2026-06-12T11:00:00Z", "miles": 12}, vh))
    get_success_data(api.create_visit(cid, {
        "contact_type": "VIDEO",
        "contact_start": "2026-06-20T10:00:00Z",
        "contact_end": "2026-06-20T10:30:00Z", "miles": 0}, vh))
    set_clock(api, "2026-07-05T00:00:00Z")
    get_success_data(api.create_visit(cid, {
        "contact_type": "IN_PERSON",
        "contact_start": "2026-07-03T10:00:00Z",
        "contact_end": "2026-07-03T11:00:00Z", "miles": 12}, vh))
    return base


def setup_compliance_case(api):
    """Active-volunteer-assigned case with the canonical compliance visit set
    logged and the clock advanced to 2026-07-05."""
    base = setup_active_volunteer_assigned_case(api)
    return log_standard_compliance_visits(api, base)


def log_visit(api, base, contact_type="IN_PERSON",
              contact_start="2026-06-05T10:00:00Z",
              contact_end="2026-06-05T11:00:00Z", miles=10):
    """Log a single visit on the base case as the assigned volunteer."""
    return get_success_data(api.create_visit(
        base["case_id"],
        {
            "contact_type": contact_type,
            "contact_start": contact_start,
            "contact_end": contact_end,
            "miles": miles,
        },
        base["volunteer_headers"],
    ))
