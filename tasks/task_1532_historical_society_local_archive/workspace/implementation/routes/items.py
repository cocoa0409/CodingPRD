"""Item routes (PRD §3.2) + nested reverse-reachability views."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_ACCESSION_NOT_ACCESSIONED,
    ERR_FINDING_AID_NOT_PUBLISHED, ERR_ZONE_RESTRICTED,
)
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from services.rollup import recompute_collection
from util import (
    get_json_body, as_str, as_int, as_enum, paginate, public_view,
)

bp = Blueprint("items", __name__)

CONDITION_GRADES = {"EXCELLENT", "GOOD", "FAIR", "POOR", "FRAGILE"}
ITEM_FORMATS = {"MANUSCRIPT", "PHOTOGRAPH", "MAP", "ARTIFACT", "AUDIOVISUAL", "BOUND_VOLUME"}


def serialize_item(item: dict) -> dict:
    return public_view(item)


def get_item(item_id: str) -> dict:
    item = db.items.get(item_id)
    if item is None:
        raise_err(ERR_NOT_FOUND, f"Item not found: {item_id}")
    return item


@bp.route("/items", methods=["POST"])
@require_roles("Archivist")
def create_item(_user_id: str, _role: str):
    body = get_json_body()
    accession_id = as_str(body, "accession_id", required=True)
    collection_id = as_str(body, "collection_id", required=True)
    title = as_str(body, "title", required=True)

    # existence (priority 4), body order
    accession = db.accessions.get(accession_id)
    if accession is None:
        raise_err(ERR_NOT_FOUND, f"Accession not found: {accession_id}")
    collection = db.collections.get(collection_id)
    if collection is None:
        raise_err(ERR_NOT_FOUND, f"Collection not found: {collection_id}")

    # cross-entity state gates (priority 7)
    if accession["status"] != "ACCESSIONED":
        raise_err(ERR_ACCESSION_NOT_ACCESSIONED, "Item creation requires an ACCESSIONED accession")
    if collection["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Item creation requires an ACTIVE collection")

    item = {
        **db.make_common_fields(),
        "accession_id": accession_id,
        "collection_id": collection_id,
        "title": title,
        "description": None,
        "condition_grade": None,
        "appraised_value_cents": None,
        "format": None,
        "status": "PENDING_CATALOG",
        "conservation_priority_score": None,
        "current_assessment_id": None,
    }
    db.items[item["id"]] = item
    recompute_collection(collection)  # item_count += 1; collection touched
    return success_object(serialize_item(item), 201)


@bp.route("/items", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_items(_user_id: str, _role: str):
    accession_id = request.args.get("accession_id")
    collection_id = request.args.get("collection_id")
    status = request.args.get("status")
    items = list(db.items.values())
    if accession_id is not None:
        items = [i for i in items if i["accession_id"] == accession_id]
    if collection_id is not None:
        items = [i for i in items if i["collection_id"] == collection_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_item(i) for i in page], limit, offset, total)


@bp.route("/items/<item_id>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_one_item(item_id: str, _user_id: str, _role: str):
    return success_object(serialize_item(get_item(item_id)))


@bp.route("/items/<item_id>/catalog", methods=["POST"])
@require_roles("Archivist")
def catalog_item(item_id: str, _user_id: str, _role: str):
    body = get_json_body()
    description = as_str(body, "description", required=True)
    condition_grade = as_enum(body, "condition_grade", CONDITION_GRADES, required=True)
    appraised = as_int(body, "appraised_value_cents", required=True, minimum=0)
    fmt = as_enum(body, "format", ITEM_FORMATS, required=True)

    item = get_item(item_id)
    if item["status"] != "PENDING_CATALOG":
        raise_err(ERR_INVALID_STATE, "Only a PENDING_CATALOG item may be cataloged")

    item["description"] = description
    item["condition_grade"] = condition_grade
    item["appraised_value_cents"] = appraised
    item["format"] = fmt
    item["status"] = "CATALOGED"
    db.touch(item)
    return success_object(serialize_item(item))


@bp.route("/items/<item_id>/make-available", methods=["POST"])
@require_roles("Archivist")
def make_available(item_id: str, _user_id: str, _role: str):
    item = get_item(item_id)
    if item["status"] != "CATALOGED":
        raise_err(ERR_INVALID_STATE, "Only a CATALOGED item may be made available")

    collection = db.collections.get(item["collection_id"])
    if collection is None or not collection["published_finding_aid_present"]:
        raise_err(ERR_FINDING_AID_NOT_PUBLISHED, "The collection has no PUBLISHED finding aid")
    accession = db.accessions.get(item["accession_id"])
    if accession is None or accession["status"] != "ACCESSIONED":
        raise_err(ERR_ACCESSION_NOT_ACCESSIONED, "The item's accession is not ACCESSIONED")
    zone = db.zones.get(collection["storage_zone_id"])
    if zone is None or zone["posture"] != "OPEN":
        raise_err(ERR_ZONE_RESTRICTED, "The collection's storage zone is not OPEN")

    item["status"] = "AVAILABLE"
    db.touch(item)
    return success_object(serialize_item(item))


@bp.route("/items/<item_id>/flag-conservation", methods=["POST"])
@require_roles("Archivist")
def flag_conservation(item_id: str, _user_id: str, _role: str):
    item = get_item(item_id)
    if item["status"] != "AVAILABLE":
        raise_err(ERR_INVALID_STATE, "Only an AVAILABLE item may be flagged for conservation")
    item["status"] = "FLAGGED_CONSERVATION"
    db.touch(item)
    return success_object(serialize_item(item))


# --- FK reverse-reachability views -------------------------------------------

@bp.route("/items/<item_id>/research-requests", methods=["GET"])
@require_roles(*ANY_ROLE)
def item_research_requests(item_id: str, _user_id: str, _role: str):
    get_item(item_id)
    reqs = [r for r in db.requests.values() if item_id in r["item_ids"]]
    page, limit, offset, total = paginate(reqs)
    return success_list([public_view(r) for r in page], limit, offset, total)


@bp.route("/items/<item_id>/reproduction-orders", methods=["GET"])
@require_roles(*ANY_ROLE)
def item_reproduction_orders(item_id: str, _user_id: str, _role: str):
    get_item(item_id)
    ords = [o for o in db.orders.values() if item_id in o["item_ids"]]
    page, limit, offset, total = paginate(ords)
    return success_list([public_view(o) for o in page], limit, offset, total)


@bp.route("/items/<item_id>/deaccession-proposals", methods=["GET"])
@require_roles(*ANY_ROLE)
def item_deaccession_proposals(item_id: str, _user_id: str, _role: str):
    get_item(item_id)
    props = [p for p in db.proposals.values() if item_id in p["item_ids"]]
    page, limit, offset, total = paginate(props)
    return success_list([public_view(p) for p in page], limit, offset, total)
