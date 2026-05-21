"""Application routes — pipeline transitions, withdrawal, rejection."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_auth
from ..common import (
    bump, get_json_body, paginate_list, parse_pagination, require_enum,
    require_fields, require_str, stamp_new,
)
from ..errors import ApiError
from ..lookups import path_application, path_requisition, ref_candidate
from ..response import respond
from ..serializers import serialize_application
from ..services import (
    APP_NON_TERMINAL, recompute_goal_for_requisition, system_reject_application,
)
from ..store import store


applications_bp = Blueprint("applications", __name__)


REJECTION_REASONS = {
    "NOT_QUALIFIED", "FAILED_INTERVIEW", "FAILED_BACKGROUND_CHECK",
    "OFFER_DECLINED", "DUPLICATE", "OTHER",
}


# ---------------- create ----------------

@applications_bp.post("/requisitions/<rid>/applications")
@require_auth("Recruiter", "Candidate")
def create_application(rid):
    body = get_json_body()
    require_fields(body, "candidate_id")
    candidate_id = require_str(body["candidate_id"], "candidate_id")

    with store.lock:
        req = path_requisition(rid)
        candidate = ref_candidate(candidate_id)

        # RBAC ownership: a Recruiter must own the requisition; a Candidate must match candidate_id.
        if g.user_role == "Recruiter" and g.user_id != req["recruiter_id"]:
            raise ApiError("ERR_FORBIDDEN", "Recruiter may only create applications on owned requisitions")
        if g.user_role == "Candidate" and g.user_id != candidate_id:
            raise ApiError("ERR_FORBIDDEN", "Candidate may only apply on their own behalf")

        if req["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Requisition is not OPEN")

        # Duplicate-application check (priority 12).
        for a in store.applications.values():
            if (
                a["requisition_id"] == rid
                and a["candidate_id"] == candidate_id
                and a["stage"] not in {"WITHDRAWN", "REJECTED"}
            ):
                raise ApiError(
                    "ERR_DUPLICATE_APPLICATION",
                    "An active application already exists for this candidate on this requisition",
                )

        app = stamp_new({
            "requisition_id": rid,
            "candidate_id": candidate_id,
            "stage": "APPLIED",
            "rejection_reason": None,
            "panel_average_score": None,
            "pinned_eeo_snapshot_version": None,
        })
        store.applications[app["id"]] = app
        # Projected diversity goal recompute fires on creation.
        recompute_goal_for_requisition(req)
    return respond(serialize_application(app), 201)


@applications_bp.get("/applications/<aid>")
@require_auth("Recruiter", "HiringManager", "Candidate", "PlatformAdmin")
def get_application(aid):
    with store.lock:
        app = path_application(aid)
        if g.user_role == "Candidate" and g.user_id != app["candidate_id"]:
            raise ApiError("ERR_FORBIDDEN", "Candidate may only read own applications")
        return respond(serialize_application(app))


@applications_bp.get("/requisitions/<rid>/applications")
@require_auth("Recruiter", "HiringManager", "PlatformAdmin")
def list_applications_for_requisition(rid):
    limit, offset = parse_pagination()
    stage = request.args.get("stage")
    with store.lock:
        path_requisition(rid)
        items = sorted(
            (a for a in store.applications.values() if a["requisition_id"] == rid),
            key=lambda a: a["created_at"],
        )
        if stage:
            items = [a for a in items if a["stage"] == stage]
        page, meta = paginate_list(items, limit, offset)
        return respond([serialize_application(a) for a in page], list_meta=meta)


# ---------------- transitions ----------------

@applications_bp.post("/applications/<aid>/advance")
@require_auth("Recruiter")
def advance_application(aid):
    with store.lock:
        app = path_application(aid)
        req = store.requisitions.get(app["requisition_id"])
        if req is None:
            raise ApiError("ERR_NOT_FOUND", "Parent Requisition not found")
        if g.user_id != req["recruiter_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the owning recruiter may advance the application")
        if req["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Parent Requisition is not OPEN")

        stage = app["stage"]
        if stage == "APPLIED":
            app["stage"] = "SCREENING"
            bump(app)
            return respond(serialize_application(app))

        if stage == "SCREENING":
            has_scheduled = any(
                i["application_id"] == app["id"] and i["status"] == "SCHEDULED"
                for i in store.interviews.values()
            )
            if not has_scheduled:
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "Cannot advance: at least one SCHEDULED Interview is required",
                )
            app["stage"] = "INTERVIEWING"
            bump(app)
            return respond(serialize_application(app))

        if stage == "INTERVIEWING":
            # 1) Find COMPLETED interviews under this application.
            completed_interview_ids = [
                i["id"]
                for i in store.interviews.values()
                if i["application_id"] == app["id"] and i["status"] == "COMPLETED"
            ]
            if not completed_interview_ids:
                # Empty-panel rule (priority 20).
                raise ApiError(
                    "ERR_EMPTY_PANEL",
                    "Cannot advance: at least one COMPLETED Interview is required",
                )
            # 2) At least one feedback HIRE/STRONG_HIRE.
            qualifying_feedbacks = [
                f
                for f in store.interview_feedback.values()
                if f["interview_id"] in completed_interview_ids
                and f["recommendation"] in {"HIRE", "STRONG_HIRE"}
            ]
            if not qualifying_feedbacks:
                raise ApiError(
                    "ERR_NO_QUALIFYING_FEEDBACK",
                    "Cannot advance: at least one HIRE/STRONG_HIRE feedback is required",
                )
            # 3) panel_average_score must not be None.
            if app.get("panel_average_score") is None:
                raise ApiError(
                    "ERR_NO_QUALIFYING_FEEDBACK",
                    "Cannot advance: panel_average_score has not been computed",
                )
            # 4) OFCCP EEO gate (priority 7).
            candidate = store.candidates[app["candidate_id"]]
            if candidate.get("is_in_eeo_protected_class"):
                if candidate["id"] not in store.eeo_by_candidate:
                    raise ApiError(
                        "ERR_EEO_DATA_MISSING",
                        "Candidate flagged is_in_eeo_protected_class requires an EEORecord before OFFER_STAGE",
                    )
            app["stage"] = "OFFER_STAGE"
            app["pinned_eeo_snapshot_version"] = candidate["version"]
            bump(app)
            recompute_goal_for_requisition(req)
            return respond(serialize_application(app))

        raise ApiError("ERR_INVALID_STATE", f"Application cannot advance from stage {stage}")


@applications_bp.post("/applications/<aid>/reject")
@require_auth("Recruiter")
def reject_application(aid):
    body = get_json_body()
    with store.lock:
        app = path_application(aid)
        req = store.requisitions.get(app["requisition_id"])
        if req is None:
            raise ApiError("ERR_NOT_FOUND", "Parent Requisition not found")
        if g.user_id != req["recruiter_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the owning recruiter may reject the application")
        if app["stage"] not in {"APPLIED", "SCREENING", "INTERVIEWING"}:
            raise ApiError("ERR_INVALID_STATE", "Application cannot be rejected from this stage")

        reason = body.get("rejection_reason")
        if reason is None:
            # Default reason for INTERVIEWING per state machine.
            reason = "FAILED_INTERVIEW" if app["stage"] == "INTERVIEWING" else None
        if reason is None:
            raise ApiError("ERR_VALIDATION", "rejection_reason is required")
        require_enum(reason, "rejection_reason", REJECTION_REASONS)

        app["stage"] = "REJECTED"
        app["rejection_reason"] = reason
        bump(app)
        recompute_goal_for_requisition(req)
        return respond(serialize_application(app))


@applications_bp.post("/applications/<aid>/withdraw")
@require_auth("Candidate")
def withdraw_application(aid):
    with store.lock:
        app = path_application(aid)
        if g.user_id != app["candidate_id"]:
            raise ApiError("ERR_FORBIDDEN", "Candidate may only withdraw own applications")
        if app["stage"] not in APP_NON_TERMINAL:
            raise ApiError("ERR_INVALID_STATE", "Application cannot be withdrawn from this stage")

        was_offer_stage = app["stage"] == "OFFER_STAGE"
        app["stage"] = "WITHDRAWN"
        bump(app)

        if was_offer_stage:
            # Cancel any non-terminal offer on this application.
            from ..services import cascade_offer_decline, cascade_offer_rescind
            for o in list(store.offers.values()):
                if o["application_id"] != app["id"]:
                    continue
                if o["status"] in {"APPROVED", "EXTENDED"}:
                    # Treat as RESCINDED (without auto-rejecting parent application — already withdrawn).
                    o["status"] = "RESCINDED"
                    bump(o)
                    req = store.requisitions[o["requisition_id"]]
                    from ..services import recompute_active_offer_count
                    recompute_active_offer_count(req)
                    manager = store.hiring_managers.get(req["hiring_manager_id"])
                    if manager is not None:
                        manager["budget_cents"] = manager.get("budget_cents", 0) + o["total_first_year_comp_cents"]
                        bump(manager)
                elif o["status"] in {"DRAFT", "PENDING_APPROVAL", "NEGOTIATING"}:
                    o["status"] = "DECLINED"
                    bump(o)
                    req = store.requisitions[o["requisition_id"]]
                    from ..services import recompute_active_offer_count
                    recompute_active_offer_count(req)

        req = store.requisitions.get(app["requisition_id"])
        if req:
            recompute_goal_for_requisition(req)
        return respond(serialize_application(app))
