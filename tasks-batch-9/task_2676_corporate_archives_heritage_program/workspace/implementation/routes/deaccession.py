"""Deaccession proposals (fork-join clearance) and the logical clock endpoint."""

from flask import Blueprint, g

from core import clock, register, sorted_rows, store, touch
from errors import ApiError
from middleware import endpoint
from response import apply_filters, collection_response, empty_response, object_response
from services import calc
from services.lookup import (
    fetch,
    finding_aids_of_accession,
    recompute_accession_counters,
    series_of_item,
)
from validation import DEACCESSION_ROUTES, body, venum, vid, vinstant, vint, vstr

bp = Blueprint("deaccession", __name__)

PROPOSAL_READERS = ("ArchivesDirector", "Archivist", "LegalCounsel")
PRE_APPROVAL_STATUSES = ("SUBMITTED", "LEGAL_CLEARED", "HERITAGE_CLEARED", "DUALLY_CLEARED")


def _guard_recipient(route, recipient_repository):
    if route == "DONATION" and (
        recipient_repository is None or str(recipient_repository).strip() == ""
    ):
        raise ApiError("ERR_RECIPIENT_REPOSITORY_REQUIRED")


@bp.post("/deaccession-proposals")
@endpoint(("Archivist",))
def create_deaccession_proposal():
    payload = body()
    archival_item_id = vid(payload, "archival_item_id")
    rationale = vstr(payload, "rationale", 1, 500)
    route = venum(payload, "route", DEACCESSION_ROUTES)
    units = vint(payload, "units", 1, None)
    recipient_repository = payload.get("recipient_repository")
    if recipient_repository is not None and not isinstance(recipient_repository, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'recipient_repository' must be a string.")
    item = fetch("archival_items", archival_item_id)
    _guard_recipient(route, recipient_repository)
    row = register(
        store.deaccession_proposals,
        {
            "archival_item_id": item["id"],
            "rationale": rationale,
            "route": route,
            "units": units,
            "recipient_repository": recipient_repository,
            "status": "SUBMITTED",
            "legal_cleared_by": None,
            "heritage_cleared_by": None,
            "approved_by": None,
            "clearance_note": None,
            "transfer_reference": None,
            "stale_finding_aid_count": 0,
            "revalidated_request_count": 0,
        },
    )
    return object_response(row, 201)


@bp.get("/deaccession-proposals")
@endpoint(PROPOSAL_READERS)
def list_deaccession_proposals():
    rows = apply_filters(
        sorted_rows(store.deaccession_proposals),
        {"archival_item_id": "archival_item_id", "status": "status", "route": "route"},
    )
    return collection_response(rows)


@bp.get("/deaccession-proposals/<resource_id>")
@endpoint(PROPOSAL_READERS)
def get_deaccession_proposal(resource_id):
    return object_response(fetch("deaccession_proposals", resource_id))


@bp.post("/deaccession-proposals/<resource_id>/legal-clearance")
@endpoint(("LegalCounsel",))
def legal_clearance(resource_id):
    payload = body()
    clearance_note = vstr(payload, "clearance_note", 1, None, required=False, default=None)
    proposal = fetch("deaccession_proposals", resource_id)
    if proposal["status"] not in ("SUBMITTED", "HERITAGE_CLEARED"):
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")
    series = series_of_item(store.archival_items[proposal["archival_item_id"]])
    # rung 15 then rung 16
    if series["legal_hold_active"] or series["disposition_state"] == "SUSPENDED":
        raise ApiError("ERR_SERIES_DISPOSITION_SUSPENDED")
    if series["disposition_state"] == "PERMANENT":
        raise ApiError("ERR_SERIES_PERMANENT")
    proposal["legal_cleared_by"] = g.user_id
    if clearance_note is not None:
        proposal["clearance_note"] = clearance_note
    proposal["status"] = (
        "DUALLY_CLEARED" if proposal["status"] == "HERITAGE_CLEARED" else "LEGAL_CLEARED"
    )
    touch(proposal)
    return object_response(proposal)


@bp.post("/deaccession-proposals/<resource_id>/heritage-clearance")
@endpoint(("ArchivesDirector",))
def heritage_clearance(resource_id):
    payload = body()
    clearance_note = vstr(payload, "clearance_note", 1, None, required=False, default=None)
    proposal = fetch("deaccession_proposals", resource_id)
    if proposal["status"] not in ("SUBMITTED", "LEGAL_CLEARED"):
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")
    series = series_of_item(store.archival_items[proposal["archival_item_id"]])
    if series["disposition_state"] == "PERMANENT":
        raise ApiError("ERR_SERIES_PERMANENT")
    proposal["heritage_cleared_by"] = g.user_id
    if clearance_note is not None:
        proposal["clearance_note"] = clearance_note
    proposal["status"] = (
        "DUALLY_CLEARED" if proposal["status"] == "LEGAL_CLEARED" else "HERITAGE_CLEARED"
    )
    touch(proposal)
    return object_response(proposal)


@bp.post("/deaccession-proposals/<resource_id>/approve")
@endpoint(("ArchivesDirector",))
def approve_deaccession_proposal(resource_id):
    proposal = fetch("deaccession_proposals", resource_id)
    # rungs 8 and 9 sit deliberately ahead of the state guard
    if proposal["legal_cleared_by"] is None:
        raise ApiError("ERR_LEGAL_CLEARANCE_MISSING")
    if proposal["heritage_cleared_by"] is None:
        raise ApiError("ERR_HERITAGE_CLEARANCE_MISSING")
    if proposal["status"] != "DUALLY_CLEARED":
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")
    # rung 14
    if g.user_id == proposal["legal_cleared_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # rung 27
    _guard_recipient(proposal["route"], proposal["recipient_repository"])
    # rung 29
    item = store.archival_items[proposal["archival_item_id"]]
    if calc.item_has_occupying_loan(item["id"]) is not None:
        raise ApiError("ERR_ITEM_HAS_ACTIVE_LOAN")
    if item["status"] != "ACCESSIONED":
        raise ApiError("ERR_ITEM_STATE_INVALID")
    proposal["approved_by"] = g.user_id
    proposal["status"] = "APPROVED"
    # hop one
    item["status"] = "PENDING_DISPOSITION"
    touch(item)
    # hop two
    moved_aids = []
    for aid in sorted_rows(store.finding_aids):
        if aid["accession_id"] != item["accession_id"] or aid["status"] != "PUBLISHED":
            continue
        aid["status"] = "NEEDS_REVISION"
        aid["stale_item_count"] += 1
        touch(aid)
        moved_aids.append(aid["id"])
    proposal["stale_finding_aid_count"] = len(moved_aids)
    # hop three
    revalidated = 0
    for request_row in sorted_rows(store.access_requests):
        if request_row["finding_aid_id"] not in moved_aids:
            continue
        if request_row["status"] not in ("APPROVED", "PARTIALLY_APPROVED"):
            continue
        request_row["status"] = "REVALIDATION_REQUIRED"
        touch(request_row)
        revalidated += 1
    proposal["revalidated_request_count"] = revalidated
    touch(proposal)
    return object_response(proposal)


@bp.post("/deaccession-proposals/<resource_id>/execute")
@endpoint(("Archivist",))
def execute_deaccession_proposal(resource_id):
    payload = body()
    transfer_reference = vstr(payload, "transfer_reference", 1, None)
    proposal = fetch("deaccession_proposals", resource_id)
    if proposal["status"] != "APPROVED":
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")
    item = store.archival_items[proposal["archival_item_id"]]
    if item["status"] != "PENDING_DISPOSITION":
        raise ApiError("ERR_ITEM_STATE_INVALID")
    # rung 30
    if proposal["units"] > item["units_on_shelf"]:
        raise ApiError("ERR_INSUFFICIENT_SHELF_UNITS")
    proposal["transfer_reference"] = transfer_reference
    item["units_on_shelf"] -= proposal["units"]
    item["units_deaccessioned"] += proposal["units"]
    if proposal["route"] == "DONATION":
        item["_recipient_repository"] = proposal["recipient_repository"]
    item["status"] = "DEACCESSIONED" if item["units_on_shelf"] == 0 else "ACCESSIONED"
    touch(item)
    recompute_accession_counters(store.accessions[item["accession_id"]])
    proposal["status"] = "EXECUTED"
    touch(proposal)
    return object_response(proposal)


@bp.post("/deaccession-proposals/<resource_id>/reject")
@endpoint(("ArchivesDirector",))
def reject_deaccession_proposal(resource_id):
    payload = body()
    clearance_note = vstr(payload, "clearance_note", 1, None, required=False, default=None)
    proposal = fetch("deaccession_proposals", resource_id)
    if proposal["status"] not in PRE_APPROVAL_STATUSES:
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")
    if clearance_note is not None:
        proposal["clearance_note"] = clearance_note
    proposal["status"] = "REJECTED"
    touch(proposal)
    return object_response(proposal)


# --- logical clock ---------------------------------------------------------


@bp.post("/_clock/set_current_utc")
@endpoint(("SystemOperator",))
def set_current_utc():
    payload = body()
    instant = vinstant(payload, "current_utc")
    clock.set(instant)
    return empty_response(200)
