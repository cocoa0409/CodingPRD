"""Access control, ownership, segregation of duties, and parcel review overlap
(PRD §2.1, §2.9, §3.2)."""
from test_helpers import (
    validate_error, ApiErrorId,
    build_user_headers, make_applicant_headers, make_commissioner_headers,
    decide_payload,
    seed_parcel, seed_applicant, make_application, submit,
    build_submitted, build_scheduled,
)
from test_helpers import api_client as api


# --- Role authorization ---------------------------------------------------

def test_applicant_cannot_record_completeness():
    """PRD §2.1: "If the headers are well-formed but the acting role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §2.1: "A Planner records completeness determinations."

    Design: Corner/rbac/applicant_cannot_record_completeness
    """
    ctx = build_submitted(app_type="VARIANCE", clock=None)
    headers = make_applicant_headers(ctx["applicant"]["id"])
    resp = api.record_completeness(ctx["app"]["id"], {"determination": "COMPLETE"}, headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_unknown_role_rejected():
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the recognized
    roles, the request is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_context_error
    """
    headers = build_user_headers("somebody", "Nobody")
    resp = api.list_applications(headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


# --- Ownership ------------------------------------------------------------

def test_non_owner_cannot_submit():
    """PRD §3.2: "Only the owning applicant may submit — the acting X-User-ID must equal the
    application's applicant_id, else ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/non_owner_applicant_cannot_submit
    """
    parcel = seed_parcel()
    owner = seed_applicant(email="owner@example.com")
    other = seed_applicant(email="other@example.com")
    app = make_application(parcel["id"], owner["id"], application_type="VARIANCE")
    resp = api.submit_application(app["id"], make_applicant_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


# --- Segregation of duties ------------------------------------------------

def test_commissioner_equals_planner_segregation():
    """PRD §2.9: "Later, when a Commissioner records the hearing decision, the acting
    commissioner's X-User-ID is compared against that stored assigned_planner_user_id; if
    they are equal, the decision is refused with ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

    Design: Corner/rbac/commissioner_equals_planner_returns_segregation
    """
    ctx = build_scheduled(app_type="VARIANCE", planner_id="shared-1")
    resp = api.decide_agenda_item(
        ctx["item"]["id"], decide_payload(decision="APPROVE"), make_commissioner_headers("shared-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


# --- Parcel review-window overlap -----------------------------------------

def test_overlapping_second_submit_rejected():
    """PRD §3.2: "That first submit also enforces the parcel-overlap rule: the new
    application's active review interval, which runs from submitted_at (inclusive) up to its
    review_window_closed_at (exclusive), must not overlap the active review interval of any
    other application on the same parcel; an overlap is rejected with ERR_PARCEL_REVIEW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/parcel_review_window_overlap
    """
    from test_helpers import set_clock
    set_clock("2026-06-01T00:00:00Z")
    parcel = seed_parcel()
    applicant = seed_applicant()
    app1 = make_application(parcel["id"], applicant["id"], application_type="VARIANCE",
                           requested_use="first request")
    submit(app1["id"], applicant["id"])
    app2 = make_application(parcel["id"], applicant["id"], application_type="VARIANCE",
                           requested_use="second request")
    resp = api.submit_application(app2["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_PARCEL_REVIEW_CONFLICT)


def test_first_application_remains_active_after_conflict(clerk_headers):
    """PRD §3.2: "An application's interval is active for as long as its
    review_window_closed_at is null."

    Design: Difficulty/resource_temporal_overlap/parcel_review_window_overlap
    """
    from test_helpers import set_clock
    set_clock("2026-06-01T00:00:00Z")
    parcel = seed_parcel()
    applicant = seed_applicant()
    app1 = make_application(parcel["id"], applicant["id"], application_type="VARIANCE",
                           requested_use="first request")
    submit(app1["id"], applicant["id"])
    app2 = make_application(parcel["id"], applicant["id"], application_type="VARIANCE",
                           requested_use="second request")
    api.submit_application(app2["id"], make_applicant_headers(applicant["id"]))
    a1 = api.get_application(app1["id"], clerk_headers).json()["data"]
    a2 = api.get_application(app2["id"], clerk_headers).json()["data"]
    assert a1["status"] == "SUBMITTED", f"first application must remain SUBMITTED, got {a1['status']}"
    assert a2["status"] == "DRAFT", f"conflicting second application must stay DRAFT, got {a2['status']}"
