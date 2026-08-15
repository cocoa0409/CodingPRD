"""DossierItem endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CASE_NOT_FOUND,
    ERR_DOSSIER_ITEM_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_CASE_STAGE_FORBIDDEN,
    ERR_STALE_VERSION,
    ERR_INVALID_ITEM_STATE,
    ERR_SUPERSEDE_TARGET_INVALID,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import new_record, touch
from validate import (
    get_body, req_str, req_enum, req_int, opt_bool, opt_nullable_str,
    require_path, raw_str, raw_int,
)

bp = Blueprint("dossier_items", __name__)

CATEGORIES = {"TEACHING", "RESEARCH", "SERVICE"}


def _own_item_case_or_403(caller, item):
    case = db["cases"].get(item["case_id"])
    if case is None or caller.user_id != case["candidate_id"]:
        raise_error(ERR_OWNERSHIP_MISMATCH, "acting user does not own this item's case")
    return case


def _require_assembly(case):
    if case["stage"] != "DOSSIER_ASSEMBLY":
        raise_error(ERR_CASE_STAGE_FORBIDDEN,
                    "dossier item mutations require the case to be in DOSSIER_ASSEMBLY")


@bp.post("/dossier-items")
def create_item():
    caller = authorized(["Candidate"])
    body = get_body()
    # Priority 4: body FK existence (case_id, supersedes_item_id).
    case = None
    case_id_raw = raw_str(body, "case_id")
    if case_id_raw is not None:
        case = db["cases"].get(case_id_raw)
        if case is None:
            raise_error(ERR_CASE_NOT_FOUND, "case_id does not resolve")
    supersedes_raw = raw_str(body, "supersedes_item_id")
    if supersedes_raw is not None and db["dossier_items"].get(supersedes_raw) is None:
        raise_error(ERR_DOSSIER_ITEM_NOT_FOUND, "supersedes_item_id does not resolve")
    # Priority 5: ownership of the referenced case.
    if case is not None and caller.user_id != case["candidate_id"]:
        raise_error(ERR_OWNERSHIP_MISMATCH, "acting user does not own this case")
    # Priority 6: stage gate, then OCC on the parent case version.
    if case is not None and case["stage"] != "DOSSIER_ASSEMBLY":
        raise_error(ERR_CASE_STAGE_FORBIDDEN,
                    "dossier item mutations require the case to be in DOSSIER_ASSEMBLY")
    expected = raw_int(body, "expected_case_version")
    if case is not None and expected is not None and expected != case["version"]:
        raise_error(ERR_STALE_VERSION, "expected_case_version does not match the case version")
    # Priority 9: shape.
    case_id = req_str(body, "case_id")
    category = req_enum(body, "category", CATEGORIES)
    title = req_str(body, "title")
    page_count = req_int(body, "page_count", minimum=1)
    is_peer_reviewed = opt_bool(body, "is_peer_reviewed", False)
    supersedes_item_id = opt_nullable_str(body, "supersedes_item_id", None)
    req_int(body, "expected_case_version")  # non-optional OCC field (PRD §2.11)
    rec = new_record("dossier_items", {
        "case_id": case_id,
        "category": category,
        "title": title,
        "page_count": page_count,
        "is_peer_reviewed": is_peer_reviewed,
        "supersedes_item_id": supersedes_item_id,
        "status": "DRAFT",
    })
    touch(case)  # item creation increments TenureCase.version by 1 (PRD §2.6)
    return success_object(public(rec), status=201)


@bp.get("/dossier-items")
def list_items():
    return list_response("dossier_items", {
        "case_id": request.args.get("case_id"),
        "supersedes_item_id": request.args.get("supersedes_item_id"),
        "status": request.args.get("status"),
        "category": request.args.get("category"),
    })


@bp.get("/dossier-items/<rid>")
def get_item(rid):
    return get_one("dossier_items", rid, ERR_DOSSIER_ITEM_NOT_FOUND)


@bp.post("/dossier-items/<rid>/submit")
def submit_item(rid):
    caller = authorized(["Candidate"])
    item = require_path("dossier_items", rid, ERR_DOSSIER_ITEM_NOT_FOUND)
    case = _own_item_case_or_403(caller, item)
    _require_assembly(case)
    if item["status"] not in ("DRAFT", "RETURNED"):
        raise_error(ERR_INVALID_ITEM_STATE,
                    f"cannot submit an item in status {item['status']}")
    # Priority 9: supersede target must be a SUBMITTED item of same case+category.
    target = None
    if item.get("supersedes_item_id"):
        target = db["dossier_items"].get(item["supersedes_item_id"])
        if (
            target is None
            or target["case_id"] != item["case_id"]
            or target["category"] != item["category"]
            or target["status"] != "SUBMITTED"
        ):
            raise_error(ERR_SUPERSEDE_TARGET_INVALID,
                        "supersede target must be a SUBMITTED item of the same case and category")
    if target is not None:
        target["status"] = "SUPERSEDED"
        touch(target)
    item["status"] = "SUBMITTED"
    touch(item)
    return success_object(public(item))


@bp.post("/dossier-items/<rid>/return")
def return_item(rid):
    authorized(["ProvostOfficer"])
    item = require_path("dossier_items", rid, ERR_DOSSIER_ITEM_NOT_FOUND)
    case = db["cases"].get(item["case_id"])
    if case is not None:
        _require_assembly(case)
    if item["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_ITEM_STATE,
                    f"cannot return an item in status {item['status']}")
    item["status"] = "RETURNED"
    touch(item)
    return success_object(public(item))


@bp.post("/dossier-items/<rid>/withdraw")
def withdraw_item(rid):
    caller = authorized(["Candidate"])
    item = require_path("dossier_items", rid, ERR_DOSSIER_ITEM_NOT_FOUND)
    case = _own_item_case_or_403(caller, item)
    _require_assembly(case)
    if item["status"] not in ("DRAFT", "RETURNED"):
        raise_error(ERR_INVALID_ITEM_STATE,
                    f"cannot withdraw an item in status {item['status']}")
    item["status"] = "WITHDRAWN"
    touch(item)
    return success_object(public(item))
