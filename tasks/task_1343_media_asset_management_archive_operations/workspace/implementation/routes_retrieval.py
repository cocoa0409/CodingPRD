"""RetrievalRequest routes: review, staging, deep-archive recall, delivery."""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, require_roles
from db import STORE, new_id, now, stamp
from envelope import ok, paginate
from errors import raise_err
from serializers import request_out
from validate import DELIVERY_TIERS, PURPOSES, body, opt_enum, req_dt, req_enum, req_str

bp = Blueprint("retrieval", __name__, url_prefix="/archive")

LIVE_STATES = ("SUBMITTED", "UNDER_REVIEW", "RECALLING", "STAGED")


def _get_request(rid):
    rec = STORE.requests.get(rid)
    if rec is None:
        raise_err("ERR_RETRIEVAL_REQUEST_NOT_FOUND", "Retrieval request not found")
    return rec


def _purpose_gate(asset, purpose):
    posture = calc.rights_posture(asset)
    if not calc.purpose_allowed(purpose, posture):
        raise_err(
            "ERR_RIGHTS_EXPIRED_FOR_PURPOSE",
            f"Purpose {purpose} is not permitted under rights posture {posture}",
        )


@bp.post("/retrieval-requests")
def create_request():
    require_roles("Requester")
    j = body()
    asset_id = req_str(j, "asset_id")
    asset = STORE.assets.get(asset_id)
    if asset is None:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    requester_id = req_str(j, "requester_id")
    if requester_id not in STORE.staff:
        raise_err("ERR_STAFF_MEMBER_NOT_FOUND", "Requester staff member not found")
    purpose = req_enum(j, "purpose", PURPOSES)
    delivery_tier = opt_enum(j, "delivery_tier", DELIVERY_TIERS, "STANDARD")
    requested_delivery_by = req_dt(j, "requested_delivery_by")
    # State: retrievable means CATALOGED or ARCHIVED; DISPOSED is special-cased
    if asset["catalog_status"] == "DISPOSED":
        raise_err("ERR_ASSET_DISPOSED", "The asset has been disposed")
    if asset["catalog_status"] not in ("CATALOGED", "ARCHIVED"):
        raise_err(
            "ERR_ASSET_NOT_RETRIEVABLE",
            "Retrieval requires catalog_status CATALOGED or ARCHIVED",
        )
    # Safety gate
    if calc.hold_status(asset) != "CLEAR":
        raise_err("ERR_ASSET_UNDER_LEGAL_HOLD", "Asset is under an active legal hold")
    # Purpose gate against current rights posture
    _purpose_gate(asset, purpose)
    # Deadline must lie strictly in the future
    if requested_delivery_by <= now():
        raise_err("ERR_DELIVERY_DEADLINE_PAST", "requested_delivery_by must be in the future")
    # BROADCAST: deadline strictly before every effective grant's window_end
    if purpose == "BROADCAST":
        for g in calc.effective_grants(asset):
            if requested_delivery_by >= g["window_end"]:
                raise_err(
                    "ERR_DELIVERY_BEYOND_RIGHTS_WINDOW",
                    "requested_delivery_by must fall strictly before every effective "
                    "grant's window_end",
                )
    rec = {
        "id": new_id(),
        "asset_id": asset_id,
        "requester_id": requester_id,
        "purpose": purpose,
        "delivery_tier": delivery_tier,
        "requested_delivery_by": requested_delivery_by,
        "status": "SUBMITTED",
        "quoted_fee_cents": None,
        "return_count": 0,
        "staged_at": None,
        "delivered_at": None,
        "review_note": None,
    }
    stamp(rec)
    STORE.requests[rec["id"]] = rec
    return ok(request_out(rec), 201)


@bp.get("/retrieval-requests")
def list_requests():
    require_roles(*ALL_ROLES)
    recs = list(STORE.requests.values())
    for param, field in (
        ("asset_id", "asset_id"),
        ("requester_id", "requester_id"),
        ("status", "status"),
    ):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    return paginate(recs, request_out)


@bp.get("/retrieval-requests/<rid>")
def get_request(rid):
    require_roles(*ALL_ROLES)
    return ok(request_out(_get_request(rid)))


@bp.post("/retrieval-requests/<rid>/start-review")
def start_review(rid):
    require_roles("AccessOfficer")
    rec = _get_request(rid)
    if rec["status"] != "SUBMITTED":
        raise_err("ERR_REQUEST_NOT_SUBMITTED", "start-review requires SUBMITTED")
    rec["status"] = "UNDER_REVIEW"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(request_out(rec))


@bp.post("/retrieval-requests/<rid>/approve")
def approve_request(rid):
    uid, _ = require_roles("AccessOfficer")
    rec = _get_request(rid)
    if rec["status"] != "UNDER_REVIEW":
        raise_err("ERR_REQUEST_NOT_UNDER_REVIEW", "approve requires UNDER_REVIEW")
    if uid == rec["requester_id"]:
        raise_err(
            "ERR_SOD_RETRIEVAL_SELF_APPROVE",
            "Approver must differ from the requester",
        )
    asset = STORE.assets.get(rec["asset_id"])
    if asset is None:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    if calc.hold_status(asset) != "CLEAR":
        raise_err("ERR_ASSET_UNDER_LEGAL_HOLD", "Asset is under an active legal hold")
    _purpose_gate(asset, rec["purpose"])
    rec["quoted_fee_cents"] = calc.delivery_fee_cents(asset, rec["delivery_tier"])
    if asset["storage_tier"] == "DEEP_ARCHIVE":
        rec["status"] = "RECALLING"
    else:
        rec["status"] = "STAGED"
        rec["staged_at"] = now()
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(request_out(rec))


@bp.post("/retrieval-requests/<rid>/return")
def return_request(rid):
    require_roles("AccessOfficer")
    rec = _get_request(rid)
    if rec["status"] != "UNDER_REVIEW":
        raise_err("ERR_REQUEST_NOT_UNDER_REVIEW", "return requires UNDER_REVIEW")
    j = body()
    note = req_str(j, "note")
    rec["status"] = "SUBMITTED"
    rec["return_count"] += 1
    rec["review_note"] = note
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(request_out(rec))


@bp.post("/retrieval-requests/<rid>/reject")
def reject_request(rid):
    require_roles("AccessOfficer")
    rec = _get_request(rid)
    if rec["status"] != "UNDER_REVIEW":
        raise_err("ERR_REQUEST_NOT_UNDER_REVIEW", "reject requires UNDER_REVIEW")
    j = body()
    note = req_str(j, "note")
    rec["status"] = "REJECTED"
    rec["review_note"] = note
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(request_out(rec))


@bp.post("/retrieval-requests/<rid>/stage-complete")
def stage_complete(rid):
    require_roles("LabTechnician")
    rec = _get_request(rid)
    if rec["status"] != "RECALLING":
        raise_err("ERR_REQUEST_NOT_RECALLING", "stage-complete requires RECALLING")
    rec["status"] = "STAGED"
    rec["staged_at"] = now()
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(request_out(rec))


@bp.post("/retrieval-requests/<rid>/deliver")
def deliver_request(rid):
    require_roles("AccessOfficer")
    rec = _get_request(rid)
    if rec["status"] != "STAGED":
        raise_err("ERR_REQUEST_NOT_STAGED", "deliver requires STAGED")
    rec["status"] = "DELIVERED"
    rec["delivered_at"] = now()
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(request_out(rec))


@bp.post("/retrieval-requests/<rid>/cancel")
def cancel_request(rid):
    uid, role = require_roles("Requester", "AccessOfficer")
    rec = _get_request(rid)
    if role == "Requester" and uid != rec["requester_id"]:
        raise_err(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "A Requester may cancel only their own retrieval requests",
        )
    if rec["status"] not in LIVE_STATES:
        raise_err("ERR_REQUEST_TERMINAL", "cancel requires a non-terminal request")
    rec["status"] = "CANCELLED"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(request_out(rec))
