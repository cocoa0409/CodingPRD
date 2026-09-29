"""Requesters, access requests, confidentiality screenings and service fees."""

from flask import Blueprint, g

from core import clock, register, sorted_rows, store, touch
from errors import ApiError
from middleware import endpoint
from response import apply_filters, collection_response, object_response
from services import calc
from services.lookup import (
    fetch,
    refresh_current_screening_pointer,
    screenings_of_request,
)
from validation import (
    APPROVAL_SCOPES,
    REQUESTER_CLASSES,
    SCREENING_DECISIONS,
    body,
    vbool,
    venum,
    vid,
    vid_list,
    vint,
    vstr,
)

bp = Blueprint("access", __name__)

REQUESTER_READERS = ("ArchivesDirector", "AccessServicesOfficer")
REQUEST_READERS = ("ArchivesDirector", "AccessServicesOfficer", "LegalCounsel", "Requester")
SCREENING_READERS = ("ArchivesDirector", "AccessServicesOfficer", "LegalCounsel")


# --- requesters ------------------------------------------------------------


@bp.post("/requesters")
@endpoint(("AccessServicesOfficer",))
def create_requester():
    payload = body()
    display_name = vstr(payload, "display_name", 1, 120)
    requester_class = venum(payload, "requester_class", REQUESTER_CLASSES)
    affiliation = vstr(payload, "affiliation", 1, 160)
    nda_on_file = vbool(payload, "nda_on_file", required=False, default=False)
    row = register(
        store.requesters,
        {
            "display_name": display_name,
            "requester_class": requester_class,
            "affiliation": affiliation,
            "nda_on_file": nda_on_file,
            "status": "ACTIVE",
            "suspend_reason": None,
        },
    )
    return object_response(row, 201)


@bp.get("/requesters")
@endpoint(REQUESTER_READERS)
def list_requesters():
    rows = apply_filters(
        sorted_rows(store.requesters), {"requester_class": "requester_class", "status": "status"}
    )
    return collection_response(rows)


@bp.get("/requesters/<resource_id>")
@endpoint(("ArchivesDirector", "AccessServicesOfficer", "Requester"))
def get_requester(resource_id):
    return object_response(fetch("requesters", resource_id))


@bp.post("/requesters/<resource_id>/suspend")
@endpoint(("AccessServicesOfficer",))
def suspend_requester(resource_id):
    payload = body()
    suspend_reason = vstr(payload, "suspend_reason", 1, None)
    requester = fetch("requesters", resource_id)
    if requester["status"] != "ACTIVE":
        raise ApiError("ERR_REQUESTER_STATE_INVALID")
    requester["suspend_reason"] = suspend_reason
    requester["status"] = "SUSPENDED"
    touch(requester)
    return object_response(requester)


# --- access requests -------------------------------------------------------


def _guard_items_in_series(item_ids, record_series_id):
    for item_id in item_ids:
        item = store.archival_items[item_id]
        accession = store.accessions[item["accession_id"]]
        if accession["record_series_id"] != record_series_id:
            raise ApiError("ERR_ITEM_NOT_IN_SERIES")


@bp.post("/access-requests")
@endpoint(("Requester", "AccessServicesOfficer"))
def create_access_request():
    payload = body()
    requester_id = vid(payload, "requester_id")
    record_series_id = vid(payload, "record_series_id")
    purpose = vstr(payload, "purpose", 1, 500)
    requested_item_ids = vid_list(payload, "requested_item_ids", 50)
    finding_aid_id = vid(payload, "finding_aid_id", required=False, default=None)
    # rung 5: strictly left to right in the order the endpoint declares them.
    requester = fetch("requesters", requester_id)
    series = fetch("record_series", record_series_id)
    for item_id in requested_item_ids:
        fetch("archival_items", item_id)
    if finding_aid_id is not None:
        fetch("finding_aids", finding_aid_id)
    # rung 7
    if g.user_role == "Requester" and g.user_id != requester["id"]:
        raise ApiError("ERR_NOT_REQUEST_OWNER")
    # rung 21
    if not requested_item_ids:
        raise ApiError("ERR_NO_ITEMS_REQUESTED")
    # rung 22
    _guard_items_in_series(requested_item_ids, series["id"])
    row = register(
        store.access_requests,
        {
            "requester_id": requester["id"],
            "record_series_id": series["id"],
            "purpose": purpose,
            "requested_item_ids": list(requested_item_ids),
            "finding_aid_id": finding_aid_id,
            "status": "SUBMITTED",
            "legal_hold_blocked": False,
            "revision_round": 0,
            "current_screening_id": None,
            "requested_page_count": calc.requested_page_count(requested_item_ids),
            "prelim_risk_score": calc.prelim_risk_score(requester, series),
            "post_screen_risk_score": None,
            "service_fee_cents": None,
            "decided_by": None,
            "approval_scope": None,
            "deny_reason": None,
        },
    )
    return object_response(row, 201)


@bp.get("/access-requests")
@endpoint(REQUEST_READERS)
def list_access_requests():
    rows = apply_filters(
        sorted_rows(store.access_requests),
        {
            "requester_id": "requester_id",
            "record_series_id": "record_series_id",
            "finding_aid_id": "finding_aid_id",
            "status": "status",
        },
    )
    return collection_response(rows)


@bp.get("/access-requests/<resource_id>")
@endpoint(REQUEST_READERS)
def get_access_request(resource_id):
    return object_response(fetch("access_requests", resource_id))


@bp.post("/access-requests/<resource_id>/begin-screening")
@endpoint(("AccessServicesOfficer",))
def begin_screening(resource_id):
    request_row = fetch("access_requests", resource_id)
    origin = request_row["status"]
    if origin not in ("SUBMITTED", "REVALIDATION_REQUIRED"):
        raise ApiError("ERR_REQUEST_STATE_INVALID")
    series = store.record_series[request_row["record_series_id"]]
    if series["disposition_state"] == "SUSPENDED" or series["legal_hold_active"]:
        raise ApiError("ERR_SERIES_DISPOSITION_SUSPENDED")
    requester = store.requesters[request_row["requester_id"]]
    if requester["status"] != "ACTIVE":
        raise ApiError("ERR_REQUESTER_SUSPENDED")
    if origin == "REVALIDATION_REQUIRED":
        request_row["service_fee_cents"] = None
        request_row["post_screen_risk_score"] = None
    request_row["status"] = "SCREENING"
    touch(request_row)
    return object_response(request_row)


@bp.post("/access-requests/<resource_id>/revise")
@endpoint(("Requester",))
def revise_access_request(resource_id):
    payload = body()
    requested_item_ids = vid_list(payload, "requested_item_ids", 50)
    purpose = vstr(payload, "purpose", 1, 500, required=False, default=None)
    request_row = fetch("access_requests", resource_id)
    # rung 7
    if g.user_id != request_row["requester_id"]:
        raise ApiError("ERR_NOT_REQUEST_OWNER")
    # rung 12
    if request_row["status"] != "CHANGES_REQUESTED":
        raise ApiError("ERR_REQUEST_STATE_INVALID")
    # rung 21
    if not requested_item_ids:
        raise ApiError("ERR_NO_ITEMS_REQUESTED")
    for item_id in requested_item_ids:
        fetch("archival_items", item_id)
    # rung 22
    _guard_items_in_series(requested_item_ids, request_row["record_series_id"])
    requester = store.requesters[request_row["requester_id"]]
    series = store.record_series[request_row["record_series_id"]]
    request_row["requested_item_ids"] = list(requested_item_ids)
    if purpose is not None:
        request_row["purpose"] = purpose
    request_row["status"] = "SCREENING"
    request_row["revision_round"] += 1
    request_row["requested_page_count"] = calc.requested_page_count(requested_item_ids)
    request_row["prelim_risk_score"] = calc.prelim_risk_score(requester, series)
    for screening in screenings_of_request(request_row["id"]):
        if screening["status"] in ("OPEN", "COMPLETED"):
            screening["status"] = "SUPERSEDED"
            screening["superseded_reason"] = "REQUESTER_REVISION"
            touch(screening)
    refresh_current_screening_pointer(request_row)
    touch(request_row)
    return object_response(request_row)


ALLOWED_DECISIONS_FOR_SCOPE = {
    "FULL": ("GRANT_FULL",),
    "REDACTED": ("GRANT_FULL", "GRANT_REDACTED"),
}
RISK_REDACTION_THRESHOLD = 75


@bp.post("/access-requests/<resource_id>/approve")
@endpoint(("AccessServicesOfficer",))
def approve_access_request(resource_id):
    payload = body()
    approval_scope = venum(payload, "approval_scope", APPROVAL_SCOPES)
    request_row = fetch("access_requests", resource_id)
    if request_row["status"] != "SCREENING":
        raise ApiError("ERR_REQUEST_STATE_INVALID")
    screening_id = request_row["current_screening_id"]
    screening = store.screenings.get(screening_id) if screening_id else None
    # rung 14
    if screening is not None and g.user_id == screening["screened_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # rung 15
    series = store.record_series[request_row["record_series_id"]]
    if (
        series["disposition_state"] in ("SUSPENDED", "DISPOSED")
        or series["legal_hold_active"]
    ):
        raise ApiError("ERR_SERIES_DISPOSITION_SUSPENDED")
    # rung 23
    if request_row["finding_aid_id"] is not None:
        aid = store.finding_aids.get(request_row["finding_aid_id"])
        if aid is None or aid["status"] != "PUBLISHED":
            raise ApiError("ERR_FINDING_AID_NOT_PUBLISHED")
    # rung 25
    requester = store.requesters[request_row["requester_id"]]
    if requester["status"] != "ACTIVE":
        raise ApiError("ERR_REQUESTER_SUSPENDED")
    # rung 26
    if (
        screening is None
        or screening["status"] != "COMPLETED"
        or screening["decision"] not in ALLOWED_DECISIONS_FOR_SCOPE[approval_scope]
    ):
        raise ApiError("ERR_SCREENING_DECISION_MISSING")
    # rung 35
    if approval_scope == "FULL":
        score = request_row["post_screen_risk_score"]
        if score is None or score >= RISK_REDACTION_THRESHOLD:
            raise ApiError("ERR_RISK_THRESHOLD_REQUIRES_REDACTION")
    request_row["decided_by"] = g.user_id
    request_row["approval_scope"] = approval_scope
    request_row["service_fee_cents"] = calc.access_service_fee(
        requester, request_row["requested_item_ids"]
    )
    request_row["status"] = "APPROVED" if approval_scope == "FULL" else "PARTIALLY_APPROVED"
    touch(request_row)
    return object_response(request_row)


@bp.post("/access-requests/<resource_id>/deny")
@endpoint(("AccessServicesOfficer",))
def deny_access_request(resource_id):
    payload = body()
    deny_reason = vstr(payload, "deny_reason", 1, None)
    request_row = fetch("access_requests", resource_id)
    if request_row["status"] != "SCREENING":
        raise ApiError("ERR_REQUEST_STATE_INVALID")
    screening_id = request_row["current_screening_id"]
    screening = store.screenings.get(screening_id) if screening_id else None
    if screening is not None and g.user_id == screening["screened_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if screening is None or screening["status"] != "COMPLETED":
        raise ApiError("ERR_SCREENING_DECISION_MISSING")
    request_row["deny_reason"] = deny_reason
    request_row["decided_by"] = g.user_id
    request_row["status"] = "DENIED"
    touch(request_row)
    return object_response(request_row)


@bp.post("/access-requests/<resource_id>/close")
@endpoint(("AccessServicesOfficer",))
def close_access_request(resource_id):
    request_row = fetch("access_requests", resource_id)
    if request_row["status"] not in ("APPROVED", "PARTIALLY_APPROVED", "DENIED"):
        raise ApiError("ERR_REQUEST_STATE_INVALID")
    request_row["status"] = "CLOSED"
    touch(request_row)
    return object_response(request_row)


# --- confidentiality screenings -------------------------------------------


@bp.post("/confidentiality-screenings")
@endpoint(("AccessServicesOfficer",))
def create_screening():
    payload = body()
    access_request_id = vid(payload, "access_request_id")
    expected_version = vint(payload, "expected_access_request_version", None, None)
    request_row = fetch("access_requests", access_request_id)
    # rung 10
    if expected_version != request_row["version"]:
        raise ApiError("ERR_STALE_ACCESS_REQUEST_VERSION")
    # rung 12
    if request_row["status"] != "SCREENING":
        raise ApiError("ERR_REQUEST_STATE_INVALID")
    row = register(
        store.screenings,
        {
            "access_request_id": request_row["id"],
            "status": "OPEN",
            "screened_by": g.user_id,
            "max_item_sensitivity": calc.max_item_sensitivity(
                request_row["requested_item_ids"]
            ),
            "redaction_required": False,
            "decision": None,
            "screening_note": None,
            "superseded_reason": None,
            "completed_at": None,
        },
    )
    for other in screenings_of_request(request_row["id"]):
        if other["id"] == row["id"]:
            continue
        if other["status"] in ("OPEN", "COMPLETED"):
            other["status"] = "SUPERSEDED"
            other["superseded_reason"] = "NEW_SCREENING"
            touch(other)
    request_row["current_screening_id"] = row["id"]
    touch(request_row)
    return object_response(row, 201)


@bp.get("/confidentiality-screenings")
@endpoint(SCREENING_READERS)
def list_screenings():
    rows = apply_filters(
        sorted_rows(store.screenings),
        {"access_request_id": "access_request_id", "status": "status"},
    )
    return collection_response(rows)


@bp.get("/confidentiality-screenings/<resource_id>")
@endpoint(SCREENING_READERS)
def get_screening(resource_id):
    return object_response(fetch("screenings", resource_id))


@bp.post("/confidentiality-screenings/<resource_id>/complete")
@endpoint(("AccessServicesOfficer",))
def complete_screening(resource_id):
    payload = body()
    decision = venum(payload, "decision", SCREENING_DECISIONS)
    redaction_required = vbool(payload, "redaction_required", required=False, default=False)
    screening_note = vstr(payload, "screening_note", 1, None, required=False, default=None)
    screening = fetch("screenings", resource_id)
    if screening["status"] != "OPEN":
        raise ApiError("ERR_SCREENING_STATE_INVALID")
    request_row = store.access_requests[screening["access_request_id"]]
    if request_row["status"] != "SCREENING":
        raise ApiError(
            "ERR_SCREENING_STATE_INVALID", "The parent access request is not under screening."
        )
    screening["decision"] = decision
    screening["redaction_required"] = redaction_required
    screening["screening_note"] = screening_note
    screening["completed_at"] = clock.now()
    screening["status"] = "COMPLETED"
    touch(screening)
    requester = store.requesters[request_row["requester_id"]]
    series = store.record_series[request_row["record_series_id"]]
    request_row["post_screen_risk_score"] = calc.post_screen_risk_score(
        requester, series, request_row["requested_item_ids"], redaction_required
    )
    if decision == "CHANGES_REQUESTED":
        request_row["status"] = "CHANGES_REQUESTED"
    touch(request_row)
    return object_response(screening)
