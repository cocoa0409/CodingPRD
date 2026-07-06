"""Application intake: creation, initial state, the completeness/revision loop, listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    application_payload,
    make_applicant_headers,
    assert_application,
    seed_parcel, seed_applicant, make_application, build_submitted, build_accepted,
    record_completeness,
)
from test_helpers import api_client as api


# --- Creation -------------------------------------------------------------

def test_create_application_returns_draft_201():
    """PRD §3.2: "An Applicant opens a case by creating an entitlement application,
    which begins in DRAFT."
    PRD §4: "Operations that create a new, stand-alone resource return 201 Created."

    Design: Corner/entities/create_application_returns_all_fields_201
    """
    parcel = seed_parcel()
    applicant = seed_applicant()
    headers = make_applicant_headers(applicant["id"])
    resp = api.create_application(
        application_payload(parcel["id"], applicant["id"], application_type="VARIANCE"), headers)
    data = validate_success(resp, 201)
    assert_application(data)
    assert data["status"] == "DRAFT", f"new application must be DRAFT, got {data['status']}"
    assert data["application_type"] == "VARIANCE"
    assert data["parcel_id"] == parcel["id"]
    assert data["applicant_id"] == applicant["id"]
    assert data["revision_count"] == 0


def test_create_application_missing_type_invalid_request():
    """PRD §2.5: "Field-level validity — required fields present, enums valid, acreage
    and lot counts positive, deficiency notes present when required, else
    ERR_INVALID_REQUEST (400)."

    Design: Corner/entities/create_application_missing_field_returns_invalid_request
    """
    parcel = seed_parcel()
    applicant = seed_applicant()
    headers = make_applicant_headers(applicant["id"])
    payload = {"parcel_id": parcel["id"], "applicant_id": applicant["id"], "requested_use": "x"}
    resp = api.create_application(payload, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_application_unknown_parcel_not_found():
    """PRD §2.6: "Each resource type has its own not-found code: ERR_PARCEL_NOT_FOUND
    for a parcel, ERR_FEE_SCHEDULE_NOT_FOUND for a fee schedule, ERR_APPLICANT_NOT_FOUND
    for an applicant, ERR_APPLICATION_NOT_FOUND for an application ... each returned with
    HTTP 404 for the first unresolved identifier in path order."

    Design: Corner/entities/create_application_bad_parcel_returns_not_found
    """
    applicant = seed_applicant()
    headers = make_applicant_headers(applicant["id"])
    payload = application_payload(NON_EXISTENT_UUID, applicant["id"], application_type="VARIANCE")
    resp = api.create_application(payload, headers)
    validate_error(resp, ApiErrorId.ERR_PARCEL_NOT_FOUND)


def test_create_application_unknown_applicant_not_found():
    """PRD §2.5: "Existence — every resource id named in the path or body is resolved
    left to right in path order (parcel, applicant, application, hearing, agenda item,
    appeal, plat, fee assessment, fee schedule), else the matching ERR_..._NOT_FOUND (404)."
    PRD §2.6: "ERR_APPLICANT_NOT_FOUND for an applicant"

    Design: Corner/entities/create_application_bad_applicant_returns_not_found
    """
    parcel = seed_parcel()
    headers = make_applicant_headers(NON_EXISTENT_UUID)
    payload = application_payload(parcel["id"], NON_EXISTENT_UUID, application_type="VARIANCE")
    resp = api.create_application(payload, headers)
    validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_FOUND)


def test_get_unknown_application_not_found(clerk_headers):
    """PRD §2.6: "ERR_APPLICATION_NOT_FOUND for an application ... each returned with
    HTTP 404 for the first unresolved identifier in path order."

    Design: Corner/entities/get_application_missing_returns_not_found
    """
    resp = api.get_application(NON_EXISTENT_UUID, clerk_headers)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)


def test_client_supplied_status_ignored_stays_draft():
    """PRD §3.2: "An Applicant opens a case by creating an entitlement application,
    which begins in DRAFT."

    Design: Corner/entities/create_application_extra_field_ignored
    """
    parcel = seed_parcel()
    applicant = seed_applicant()
    headers = make_applicant_headers(applicant["id"])
    payload = application_payload(parcel["id"], applicant["id"],
                                 application_type="REZONE", status="EFFECTIVE")
    resp = api.create_application(payload, headers)
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT", "client-supplied status must be ignored"


def test_new_application_starts_draft():
    """PRD §3.2: "An Applicant opens a case by creating an entitlement application,
    which begins in DRAFT."
    PRD §3.2: "On the first submit only, the server stamps submitted_at with the current
    clock reading (marking the start of the parcel's active review window)"

    Design: Corner/state_machines/initial_state_is_draft
    """
    parcel = seed_parcel()
    applicant = seed_applicant()
    headers = make_applicant_headers(applicant["id"])
    resp = api.create_application(
        application_payload(parcel["id"], applicant["id"], application_type="CUP"), headers)
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data.get("submitted_at") is None, "submitted_at must be null before the first submit"


# --- Completeness / revision loop -----------------------------------------

def test_incomplete_without_deficiency_notes_rejected():
    """PRD §3.2: "An INCOMPLETE determination requires deficiency_notes describing the
    deficiencies; if they are absent the review is refused with
    ERR_DEFICIENCY_NOTES_REQUIRED, and it drives the application from SUBMITTED to INCOMPLETE."

    Design: Corner/validations/deficiency_notes_required_on_incomplete
    """
    ctx = build_submitted(app_type="VARIANCE", clock=None)
    from test_helpers import make_planner_headers
    resp = api.record_completeness(ctx["app"]["id"], {"determination": "INCOMPLETE"},
                                   make_planner_headers("planner-1"))
    validate_error(resp, ApiErrorId.ERR_DEFICIENCY_NOTES_REQUIRED)


def test_completeness_on_accepted_invalid_state():
    """PRD §3.2: "A Planner screens a SUBMITTED application by recording a completeness
    review, supplying a determination of either COMPLETE or INCOMPLETE."
    PRD §2.5: "the target resource is in a state from which the requested transition is
    legal, else the state error appropriate to the transition (ERR_INVALID_STATE,
    ERR_APPLICATION_NOT_ACCEPTED, ERR_HEARING_NOT_OPEN, ERR_AGENDA_FULL,
    ERR_FEE_NOT_ASSESSED, ERR_APPLICATION_NOT_EFFECTIVE, and the like), each HTTP 409."

    Design: Corner/state_machines/completeness_on_accepted_returns_invalid_state
    """
    from test_helpers import make_planner_headers
    ctx = build_accepted(app_type="VARIANCE", clock=None)
    resp = api.record_completeness(ctx["app"]["id"], {"determination": "COMPLETE"},
                                   make_planner_headers("planner-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_withdraw_terminal_application_invalid_state():
    """PRD §3.2: "At any point before the case terminates, the owning applicant may
    withdraw it, moving it to WITHDRAWN."
    PRD §2.5: "the target resource is in a state from which the requested transition is
    legal, else the state error appropriate to the transition (ERR_INVALID_STATE ...),
    each HTTP 409."

    Design: Corner/state_machines/withdraw_terminal_application_returns_invalid_state
    """
    ctx = build_submitted(app_type="VARIANCE", clock=None)
    app_id, applicant_id = ctx["app"]["id"], ctx["applicant"]["id"]
    headers = make_applicant_headers(applicant_id)
    validate_success(api.withdraw_application(app_id, headers), 200)
    resp = api.withdraw_application(app_id, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_resubmit_after_incomplete_returns_to_submitted(clerk_headers):
    """PRD §3.2: "When the applicant resubmits an INCOMPLETE application, it returns to
    SUBMITTED, revision_count increases by one, and submitted_at is left unchanged; this
    SUBMITTED ↔ INCOMPLETE revision loop may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/application_completeness_revision_loop
    """
    ctx = build_submitted(app_type="VARIANCE", clock=None)
    app_id, applicant_id = ctx["app"]["id"], ctx["applicant"]["id"]
    record_completeness(app_id, "INCOMPLETE", deficiency_notes="Missing site plan")
    resp = api.submit_application(app_id, make_applicant_headers(applicant_id))
    data = validate_success(resp, 200)
    assert data["status"] == "SUBMITTED", f"resubmit must return to SUBMITTED, got {data['status']}"


def test_resubmit_increments_revision_count(clerk_headers):
    """PRD §3.2: "When the applicant resubmits an INCOMPLETE application, it returns to
    SUBMITTED, revision_count increases by one, and submitted_at is left unchanged; this
    SUBMITTED ↔ INCOMPLETE revision loop may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/application_completeness_revision_loop
    """
    ctx = build_submitted(app_type="VARIANCE", clock=None)
    app_id, applicant_id = ctx["app"]["id"], ctx["applicant"]["id"]
    record_completeness(app_id, "INCOMPLETE", deficiency_notes="Missing site plan")
    resp = api.submit_application(app_id, make_applicant_headers(applicant_id))
    data = validate_success(resp, 200)
    assert data["revision_count"] == 1, f"revision_count must be 1 after one resubmit, got {data['revision_count']}"


# --- Listing --------------------------------------------------------------

def test_list_applications_filter_and_pagination(clerk_headers):
    """PRD §2.3: "The meta object of every list response carries limit, offset,
    total_count, and has_more."
    PRD §4: "GET /applications | List applications; filter by applicant_id, parcel_id, status"

    Design: Corner/endpoints/list_applications_pagination_envelope
    """
    p1 = seed_parcel()
    p2 = seed_parcel()
    applicant = seed_applicant()
    make_application(p1["id"], applicant["id"], application_type="VARIANCE")
    make_application(p2["id"], applicant["id"], application_type="CUP")
    resp = api.list_applications(clerk_headers,
                                 params={"applicant_id": applicant["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 2, f"expected 2 applications for applicant filter, got {meta['total_count']}"
    assert meta["has_more"] is False
