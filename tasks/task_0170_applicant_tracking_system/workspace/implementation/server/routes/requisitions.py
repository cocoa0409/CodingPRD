"""Requisition routes — including the branching state machine."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_auth
from ..clock import iso_format, now
from ..common import (
    bump, check_occ, get_json_body, paginate_list, parse_pagination,
    positive_int, require_enum, require_fields, require_str, stamp_new,
)
from ..errors import ApiError
from ..lookups import (
    path_requisition, ref_diversity_goal, ref_hiring_manager, ref_recruiter,
)
from ..response import respond
from ..serializers import serialize_requisition
from ..services import (
    APP_NON_TERMINAL, recompute_goal_for_requisition, system_reject_application,
)
from ..store import store


requisitions_bp = Blueprint("requisitions", __name__)


SENIORITY_LEVELS = {"JUNIOR", "MID", "SENIOR", "STAFF", "PRINCIPAL"}
MAX_OPEN_REQS_PER_RECRUITER = 5


# ---------------- CRUD ----------------

@requisitions_bp.post("/requisitions")
@require_auth("Recruiter")
def create_requisition():
    body = get_json_body()
    require_fields(
        body, "recruiter_id", "hiring_manager_id", "job_title",
        "department_code", "seniority_level", "headcount", "budget_cents",
    )
    recruiter_id = require_str(body["recruiter_id"], "recruiter_id")
    hiring_manager_id = require_str(body["hiring_manager_id"], "hiring_manager_id")
    job_title = require_str(body["job_title"], "job_title")
    department_code = require_str(body["department_code"], "department_code")
    seniority = require_enum(body["seniority_level"], "seniority_level", SENIORITY_LEVELS)
    headcount = positive_int(body["headcount"], "headcount")
    budget_cents = positive_int(body["budget_cents"], "budget_cents", allow_zero=True)
    target_goal_id = body.get("target_diversity_goal_id")

    with store.lock:
        recruiter = ref_recruiter(recruiter_id)
        if not recruiter.get("is_active", True):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Recruiter is not active")
        ref_hiring_manager(hiring_manager_id)
        if target_goal_id is not None:
            ref_diversity_goal(target_goal_id)

        # Owner check: the acting Recruiter must equal recruiter_id.
        if g.user_id != recruiter_id:
            raise ApiError("ERR_FORBIDDEN", "Recruiter may only create requisitions they own")

        req = stamp_new({
            "recruiter_id": recruiter_id,
            "hiring_manager_id": hiring_manager_id,
            "job_title": job_title,
            "department_code": department_code,
            "seniority_level": seniority,
            "headcount": headcount,
            "filled_count": 0,
            "active_offer_count": 0,
            "posted_at": None,
            "closed_at": None,
            "budget_cents": budget_cents,
            "target_diversity_goal_id": target_goal_id,
            "status": "DRAFT",
        })
        store.requisitions[req["id"]] = req
    return respond(serialize_requisition(req), 201)


@requisitions_bp.get("/requisitions")
@require_auth("PlatformAdmin", "Recruiter", "HiringManager")
def list_requisitions():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    recruiter_id = request.args.get("recruiter_id")
    hiring_manager_id = request.args.get("hiring_manager_id")
    department_code = request.args.get("department_code")

    with store.lock:
        all_reqs = sorted(store.requisitions.values(), key=lambda r: r["created_at"])
        filtered = []
        for r in all_reqs:
            if status and r["status"] != status:
                continue
            if recruiter_id and r["recruiter_id"] != recruiter_id:
                continue
            if hiring_manager_id and r["hiring_manager_id"] != hiring_manager_id:
                continue
            if department_code and r["department_code"] != department_code:
                continue
            filtered.append(r)
        page, meta = paginate_list(filtered, limit, offset)
        return respond([serialize_requisition(r) for r in page], list_meta=meta)


@requisitions_bp.get("/requisitions/<rid>")
@require_auth("PlatformAdmin", "Recruiter", "HiringManager")
def get_requisition(rid):
    with store.lock:
        return respond(serialize_requisition(path_requisition(rid)))


@requisitions_bp.patch("/requisitions/<rid>")
@require_auth("Recruiter")
def patch_requisition(rid):
    body = get_json_body()
    with store.lock:
        req = path_requisition(rid)
        if g.user_id != req["recruiter_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the owning recruiter may edit this requisition")
        check_occ(req, body.get("version"))

        if "headcount" in body and body["headcount"] is not None and req["status"] != "DRAFT":
            raise ApiError(
                "ERR_HEADCOUNT_IMMUTABLE",
                "headcount is immutable after the requisition leaves DRAFT",
            )
        # Other fields are recruiter-editable only while DRAFT.
        recruiter_editable = {
            "job_title", "department_code", "seniority_level",
            "headcount", "budget_cents", "target_diversity_goal_id",
        }
        attempted = [k for k in recruiter_editable if k in body and body[k] is not None]
        if attempted and req["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Requisition fields may only be edited while DRAFT")

        # Apply edits.
        if "job_title" in body and body["job_title"] is not None:
            req["job_title"] = require_str(body["job_title"], "job_title")
        if "department_code" in body and body["department_code"] is not None:
            req["department_code"] = require_str(body["department_code"], "department_code")
        if "seniority_level" in body and body["seniority_level"] is not None:
            req["seniority_level"] = require_enum(body["seniority_level"], "seniority_level", SENIORITY_LEVELS)
        if "headcount" in body and body["headcount"] is not None:
            req["headcount"] = positive_int(body["headcount"], "headcount")
        if "budget_cents" in body and body["budget_cents"] is not None:
            req["budget_cents"] = positive_int(body["budget_cents"], "budget_cents", allow_zero=True)
        if "target_diversity_goal_id" in body:
            gid = body["target_diversity_goal_id"]
            if gid is not None:
                ref_diversity_goal(gid)
            req["target_diversity_goal_id"] = gid
        bump(req)
        recompute_goal_for_requisition(req)
        return respond(serialize_requisition(req))


# ---------------- Transitions ----------------

def _require_owner_recruiter(req: dict) -> None:
    if g.user_id != req["recruiter_id"]:
        raise ApiError("ERR_FORBIDDEN", "Only the owning recruiter may perform this action")


@requisitions_bp.post("/requisitions/<rid>/submit")
@require_auth("Recruiter")
def submit_requisition(rid):
    with store.lock:
        req = path_requisition(rid)
        if req["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Requisition is not in DRAFT")
        _require_owner_recruiter(req)
        if req["headcount"] < 1:
            raise ApiError("ERR_VALIDATION", "headcount must be >= 1")
        if req["budget_cents"] < 0:
            raise ApiError("ERR_VALIDATION", "budget_cents must be >= 0")
        req["status"] = "PENDING_APPROVAL"
        bump(req)
        return respond(serialize_requisition(req))


@requisitions_bp.post("/requisitions/<rid>/approve")
@require_auth("HiringManager")
def approve_requisition(rid):
    with store.lock:
        req = path_requisition(rid)
        if req["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_INVALID_STATE", "Requisition is not PENDING_APPROVAL")
        if g.user_id != req["hiring_manager_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the assigned hiring manager may approve")
        manager = store.hiring_managers.get(g.user_id)
        if manager is None or manager["department_code"] != req["department_code"]:
            raise ApiError("ERR_FORBIDDEN", "Hiring manager department_code must match the requisition")

        # Recruiter open-requisition cap check (priority 11).
        currently_open = sum(
            1
            for r in store.requisitions.values()
            if r["recruiter_id"] == req["recruiter_id"]
            and r.get("posted_at") is not None
            and r.get("closed_at") is None
        )
        if currently_open >= MAX_OPEN_REQS_PER_RECRUITER:
            raise ApiError(
                "ERR_RECRUITER_REQUISITION_CAP",
                f"Recruiter already owns {MAX_OPEN_REQS_PER_RECRUITER} open requisitions",
            )

        req["status"] = "OPEN"
        req["posted_at"] = iso_format(now())
        bump(req)
        return respond(serialize_requisition(req))


@requisitions_bp.post("/requisitions/<rid>/reject")
@require_auth("HiringManager")
def reject_requisition(rid):
    with store.lock:
        req = path_requisition(rid)
        if req["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_INVALID_STATE", "Requisition is not PENDING_APPROVAL")
        if g.user_id != req["hiring_manager_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the assigned hiring manager may reject")
        req["status"] = "DRAFT"
        bump(req)
        return respond(serialize_requisition(req))


@requisitions_bp.post("/requisitions/<rid>/hold")
@require_auth("Recruiter")
def hold_requisition(rid):
    with store.lock:
        req = path_requisition(rid)
        if req["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Only OPEN requisitions may be put on hold")
        _require_owner_recruiter(req)
        for app in store.applications.values():
            if app["requisition_id"] == req["id"] and app["stage"] == "OFFER_STAGE":
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "Cannot hold: an application on this requisition is in OFFER_STAGE",
                )
        req["status"] = "ON_HOLD"
        bump(req)
        return respond(serialize_requisition(req))


@requisitions_bp.post("/requisitions/<rid>/resume")
@require_auth("Recruiter")
def resume_requisition(rid):
    with store.lock:
        req = path_requisition(rid)
        if req["status"] != "ON_HOLD":
            raise ApiError("ERR_INVALID_STATE", "Only ON_HOLD requisitions may be resumed")
        _require_owner_recruiter(req)
        req["status"] = "OPEN"
        bump(req)
        return respond(serialize_requisition(req))


@requisitions_bp.post("/requisitions/<rid>/cancel")
@require_auth("Recruiter")
def cancel_requisition(rid):
    with store.lock:
        req = path_requisition(rid)
        if req["status"] not in {"OPEN", "ON_HOLD"}:
            raise ApiError("ERR_INVALID_STATE", "Requisition cannot be cancelled from this state")
        _require_owner_recruiter(req)
        if req.get("filled_count", 0) != 0:
            raise ApiError("ERR_INVALID_STATE", "Cannot cancel: filled_count must be 0")
        if req["status"] == "OPEN":
            for app in store.applications.values():
                if app["requisition_id"] == req["id"] and app["stage"] == "OFFER_STAGE":
                    raise ApiError(
                        "ERR_INVALID_STATE",
                        "Cannot cancel: an application is in OFFER_STAGE",
                    )
        req["status"] = "CANCELLED"
        req["closed_at"] = iso_format(now())
        bump(req)

        # Auto-reject every non-terminal application on this requisition with OTHER.
        for app in list(store.applications.values()):
            if app["requisition_id"] == req["id"] and app["stage"] in APP_NON_TERMINAL:
                system_reject_application(app, reason="OTHER")
        return respond(serialize_requisition(req))
