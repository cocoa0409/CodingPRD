"""Composite setup helpers for the Special-Event Alcohol Permit API.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty database before each
test). Setup calls use the lenient get_success_data() validator so that a broken
precondition surfaces as a clear "Setup failed" error.

Identity model (PRD §2.1):
  - Applicant / PermitClerk / AgencyReviewer: opaque X-User-ID.
  - Inspector: X-User-ID is the acting Inspector entity's id.
Agency reviews are recorded by user id ``rev-1`` and the approving clerk uses
``clerk-1`` so the segregation-of-duties gate is satisfied on the happy path.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_venue_payload,
    create_inspector_payload,
    create_application_payload,
    create_server_payload,
    create_insurance_payload,
    create_security_plan_payload,
    create_inspection_payload,
    create_report_payload,
    create_payment_payload,
    decide_payload,
)
from .test_users import (
    TEST_USERS,
    make_clerk_headers,
    make_reviewer_headers,
    make_inspector_headers,
)
from .constants import STANDARD_BALANCE_DUE_CENTS, CLOCK_DEFAULT

DEFAULT_REVIEWER_ID = "rev-1"
DEFAULT_CLERK_ID = "clerk-1"

_APPLICANT = TEST_USERS["applicant_headers"]
_CLERK = TEST_USERS["clerk_headers"]


def _data(resp):
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(api, iso8601):
    return _data(api.set_clock(iso8601, _APPLICANT))


def reset_clock(api):
    return set_clock(api, CLOCK_DEFAULT)


# ---------------------------------------------------------------------------
# Reference registries + reads
# ---------------------------------------------------------------------------
def create_venue(api, **overrides):
    return _data(api.create_venue(create_venue_payload(**overrides), _CLERK))


def create_inspector(api, **overrides):
    return _data(api.create_inspector(create_inspector_payload(**overrides), _CLERK))


def get_application(api, application_id):
    return _data(api.get_application(application_id, _APPLICANT))


def get_app_version(api, application_id):
    return get_application(api, application_id)["version"]


def list_ledger_entries(api, application_id):
    resp = api.list_ledger_entries(_CLERK, params={"application_id": application_id, "limit": 100})
    return _data(resp)


# ---------------------------------------------------------------------------
# Draft application + supporting documents
# ---------------------------------------------------------------------------
def create_application(api, venue_id=None, venue_overrides=None, **app_overrides):
    """Create a DRAFT application (creating a venue first if none is supplied)."""
    if venue_id is None:
        venue = create_venue(api, **(venue_overrides or {}))
        venue_id = venue["id"]
    app = _data(api.create_application(create_application_payload(venue_id, **app_overrides), _APPLICANT))
    return app


def add_server(api, application_id, **overrides):
    return _data(api.create_server(create_server_payload(application_id, **overrides), _APPLICANT))


def add_insurance(api, application_id, **overrides):
    return _data(api.create_insurance_policy(create_insurance_payload(application_id, **overrides), _APPLICANT))


def add_security_plan(api, application_id, **overrides):
    return _data(api.create_security_plan(create_security_plan_payload(application_id, **overrides), _APPLICANT))


def create_draft_with_documents(api, venue_id=None, app_overrides=None,
                                server_overrides=None, insurance_overrides=None,
                                security_overrides=None):
    """DRAFT application with the three mandatory documents attached.

    Returns a dict with keys: venue_id, application, server, insurance, security_plan.
    """
    if venue_id is None:
        venue_id = create_venue(api)["id"]
    app = create_application(api, venue_id=venue_id, **(app_overrides or {}))
    server = add_server(api, app["id"], **(server_overrides or {}))
    insurance = add_insurance(api, app["id"], **(insurance_overrides or {}))
    plan = add_security_plan(api, app["id"], **(security_overrides or {}))
    return {
        "venue_id": venue_id,
        "application": app,
        "server": server,
        "insurance": insurance,
        "security_plan": plan,
    }


def create_submitted_application(api, **kwargs):
    """DRAFT-with-documents driven through submit -> SUBMITTED."""
    ctx = create_draft_with_documents(api, **kwargs)
    _data(api.submit_application(ctx["application"]["id"], _APPLICANT))
    ctx["application"] = get_application(api, ctx["application"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Review workflow
# ---------------------------------------------------------------------------
def open_review(api, application_id):
    """Open multi-agency review; return the list of created AgencyReview rows."""
    _data(api.open_review(application_id, _CLERK))
    reviews = _data(api.list_agency_reviews(_CLERK, params={"application_id": application_id, "limit": 100}))
    return reviews


def create_under_review_application(api, **kwargs):
    """SUBMITTED application driven through open-review; adds 'reviews' to ctx."""
    ctx = create_submitted_application(api, **kwargs)
    ctx["reviews"] = open_review(api, ctx["application"]["id"])
    ctx["application"] = get_application(api, ctx["application"]["id"])
    return ctx


def decide_review(api, review_id, application_id, decision, reviewer_user_id=DEFAULT_REVIEWER_ID, conditions=None):
    """Record one agency decision, threading the current application version."""
    version = get_app_version(api, application_id)
    payload = decide_payload(decision, version, conditions=conditions)
    return _data(api.decide_agency_review(review_id, payload, make_reviewer_headers(reviewer_user_id)))


def decide_all_reviews(api, application_id, reviews, decisions, reviewer_user_id=DEFAULT_REVIEWER_ID):
    """Apply a decision to each review in order, re-fetching version each time."""
    for review, decision in zip(reviews, decisions):
        conditions = "Standard conditions" if decision == "APPROVE_WITH_CONDITIONS" else None
        decide_review(api, review["id"], application_id, decision,
                      reviewer_user_id=reviewer_user_id, conditions=conditions)


def clear_document_gates(api, ctx):
    """Verify the server, accept insurance, approve the security plan."""
    app_id = ctx["application"]["id"]
    _data(api.verify_server(ctx["server"]["id"], _CLERK))
    _data(api.accept_insurance_policy(ctx["insurance"]["id"], _CLERK))
    _data(api.approve_security_plan(ctx["security_plan"]["id"], _CLERK))


def drive_to_approved(api, reviewer_user_id=DEFAULT_REVIEWER_ID, clerk_user_id=DEFAULT_CLERK_ID, **kwargs):
    """Full happy-path chain: DRAFT -> ... -> APPROVED.

    All three reviews are APPROVED (recorded by reviewer_user_id); documents are
    verified/accepted/approved; approval is performed by clerk_user_id (distinct
    from the reviewer, satisfying segregation of duties).
    """
    ctx = create_under_review_application(api, **kwargs)
    app_id = ctx["application"]["id"]
    decide_all_reviews(api, app_id, ctx["reviews"], ["APPROVE", "APPROVE", "APPROVE"],
                       reviewer_user_id=reviewer_user_id)
    clear_document_gates(api, ctx)
    _data(api.approve_application(app_id, make_clerk_headers(clerk_user_id)))
    ctx["application"] = get_application(api, app_id)
    return ctx


def drive_to_ready_for_approval(api, reviewer_user_id=DEFAULT_REVIEWER_ID, review_decisions=None, **kwargs):
    """UNDER_REVIEW application with every approval gate satisfied but NOT yet
    approved. All reviews decided (default all APPROVE), documents cleared.

    Leaves the application in UNDER_REVIEW so the caller can invoke /approve with a
    chosen clerk identity (e.g. to exercise segregation of duties).
    """
    ctx = create_under_review_application(api, **kwargs)
    reviews = ctx["reviews"]
    decisions = review_decisions or ["APPROVE"] * len(reviews)
    decide_all_reviews(api, ctx["application"]["id"], reviews, decisions,
                       reviewer_user_id=reviewer_user_id)
    clear_document_gates(api, ctx)
    ctx["application"] = get_application(api, ctx["application"]["id"])
    return ctx


def pay_balance(api, application_id, amount_cents):
    """Record a payment for amount_cents against the current version."""
    version = get_app_version(api, application_id)
    return _data(api.create_payment(application_id,
                                     create_payment_payload(amount_cents, version), _APPLICANT))


def schedule_inspection(api, application_id, inspector_id=None, **overrides):
    """Create an inspector (if needed) and schedule a SCHEDULED inspection."""
    if inspector_id is None:
        inspector_id = create_inspector(api)["id"]
    inspection = _data(api.create_inspection(
        create_inspection_payload(application_id, inspector_id, **overrides), _CLERK))
    return {"inspector_id": inspector_id, "inspection": inspection}


def record_inspection(api, inspection_id, inspector_id, result):
    return _data(api.record_inspection_result(
        inspection_id, {"result": result}, make_inspector_headers(inspector_id)))


def drive_to_approved_with_inspection(api, **kwargs):
    """APPROVED application plus a SCHEDULED inspection (adds inspector_id/inspection)."""
    ctx = drive_to_approved(api, **kwargs)
    insp = schedule_inspection(api, ctx["application"]["id"])
    ctx["inspector_id"] = insp["inspector_id"]
    ctx["inspection"] = insp["inspection"]
    ctx["application"] = get_application(api, ctx["application"]["id"])
    return ctx


def drive_to_permit_issued(api, **kwargs):
    """Full chain to PERMIT_ISSUED: APPROVED -> pay balance -> PASSED inspection -> issue."""
    ctx = drive_to_approved_with_inspection(api, **kwargs)
    app_id = ctx["application"]["id"]
    balance = get_application(api, app_id)["balance_due_cents"]
    if balance > 0:
        pay_balance(api, app_id, balance)
    record_inspection(api, ctx["inspection"]["id"], ctx["inspector_id"], "PASSED")
    _data(api.issue_permit(app_id, _CLERK))
    ctx["application"] = get_application(api, app_id)
    return ctx


def drive_to_event_complete(api, report_overrides=None, event_end_clock="2026-06-16T00:00:00Z", **kwargs):
    """Full chain to EVENT_COMPLETE: PERMIT_ISSUED -> advance clock -> file report."""
    ctx = drive_to_permit_issued(api, **kwargs)
    app_id = ctx["application"]["id"]
    set_clock(api, event_end_clock)
    report = _data(api.create_report(
        create_report_payload(app_id, **(report_overrides or {})), _APPLICANT))
    ctx["report"] = report
    ctx["application"] = get_application(api, app_id)
    return ctx


# Sanity reference: the standard fixture leaves an unpaid balance of 33789.
STANDARD_BALANCE = STANDARD_BALANCE_DUE_CENTS
