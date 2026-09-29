"""Study plans, resource studies and consultation comments."""
from flask import Blueprint, g

import auth
import clock
import constants as C
import listing
import payload
import response
import serializers as S
import services as SV
from db import db, sorted_rows
from errors import ApiError

bp = Blueprint("study", __name__)


# ---------------------------------------------------------------------------
# study plans
# ---------------------------------------------------------------------------


@bp.post("/relicensing/study-plans")
def create_plan():
    auth.authenticate(["Licensee"])
    data = payload.body()

    project_id = payload.req_string(data, "project_id")
    project = SV.fetch("projects", project_id)
    plan_title = payload.req_string(data, "plan_title")

    SV.require_not_frozen(project)
    SV.require_stage(
        project,
        ["PAD_FILED", "STUDY_PHASE", "APPLICATION_FILED", "UNDER_ENVIRONMENTAL_REVIEW", "LICENSED"],
    )

    existing = sorted_rows(db.study_plans, lambda p: p["project_id"] == project_id)
    is_first = len(existing) == 0

    for prior in existing:
        if prior["status"] in C.PLAN_OPEN_STATUSES:
            prior["status"] = "SUPERSEDED"
            SV.touch(prior)

    plan = SV.base_row()
    plan.update(
        {
            "project_id": project_id,
            "plan_title": plan_title,
            "status": "DRAFT",
            "revision_round": 0,
            "submitted_at": None,
            "approved_at": None,
            "open_comment_count": 0,
            "unresolved_mandatory_comment_count": 0,
            "attached_study_count": 0,
        }
    )
    db.study_plans[plan["id"]] = plan

    if is_first and project["stage"] == "PAD_FILED":
        project["stage"] = "STUDY_PHASE"
        SV.finalize_project(project)
        SV.touch(project)
    else:
        SV.finalize_project(project)

    return response.object_response(S.plan(plan), 201)


@bp.get("/relicensing/study-plans")
def list_plans():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(sorted_rows(db.study_plans), S.plan, ("project_id", "status"))


@bp.get("/relicensing/study-plans/<study_plan_id>")
def get_plan(study_plan_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.plan(SV.fetch("study_plans", study_plan_id)))


@bp.post("/relicensing/study-plans/<study_plan_id>/submit")
def submit_plan(study_plan_id):
    auth.authenticate(["Licensee"])
    plan = SV.fetch("study_plans", study_plan_id)
    data = payload.body()
    payload.opt_string(data, "submission_note")

    project = SV.project_of_plan(plan)
    SV.require_not_frozen(project)

    if plan["status"] not in ("DRAFT", "REVISION_REQUIRED"):
        raise ApiError(
            "ERR_STUDY_PLAN_STATE_INVALID",
            "A plan in %s cannot be submitted." % plan["status"],
        )
    if plan["attached_study_count"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", "A study plan with no attached studies cannot be submitted.")

    plan["status"] = "UNDER_AGENCY_REVIEW"
    plan["submitted_at"] = clock.now_iso()
    SV.touch(plan)

    SV.finalize_project(project)
    return response.object_response(S.plan(plan))


@bp.post("/relicensing/study-plans/<study_plan_id>/determination")
def plan_determination(study_plan_id):
    auth.authenticate(["AgencyReviewer"])
    plan = SV.fetch("study_plans", study_plan_id)
    auth.require_project_scope(plan["project_id"])

    party = auth.acting_party()
    if not party["has_conditioning_authority"]:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "The acting party does not hold mandatory conditioning authority.",
        )

    data = payload.body()
    determination = payload.req_enum(data, "determination", C.DETERMINATIONS)
    reopen = payload.opt_bool(data, "reopen_deferred_comments", False)
    payload.opt_string(data, "determination_note")

    project = SV.project_of_plan(plan)
    SV.require_not_frozen(project)

    if plan["status"] != "UNDER_AGENCY_REVIEW":
        raise ApiError(
            "ERR_STUDY_PLAN_STATE_INVALID",
            "A determination requires the plan to be UNDER_AGENCY_REVIEW.",
        )

    if determination == "APPROVE":
        if plan["unresolved_mandatory_comment_count"] > 0:
            raise ApiError(
                "ERR_UNRESOLVED_MANDATORY_COMMENTS",
                "The plan still carries unresolved mandatory comments.",
            )
        plan["status"] = "APPROVED"
        plan["approved_at"] = clock.now_iso()
    else:
        plan["status"] = "REVISION_REQUIRED"
        plan["revision_round"] = plan["revision_round"] + 1
        if reopen:
            for comment in sorted_rows(db.comments, lambda c: c["study_plan_id"] == plan["id"]):
                if comment["resolution_status"] == "RESOLVED" and comment["disposition"] == "DEFERRED":
                    comment["resolution_status"] = "OPEN"
                    comment["disposition"] = None
                    comment["reopen_count"] = comment["reopen_count"] + 1
            SV.refresh_plan_counters(plan)

    SV.touch(plan)
    SV.finalize_project(project)
    return response.object_response(S.plan(plan))


# ---------------------------------------------------------------------------
# resource studies
# ---------------------------------------------------------------------------


def _buffered_end(end_date, buffer_days):
    from datetime import timedelta

    return end_date + timedelta(days=int(buffer_days))


@bp.post("/relicensing/studies")
def create_study():
    auth.authenticate(["Licensee"])
    data = payload.body()

    study_plan_id = payload.req_string(data, "study_plan_id")
    plan = SV.fetch("study_plans", study_plan_id)
    site_id = payload.req_string(data, "site_id")
    site = SV.fetch("sites", site_id)

    if plan["project_id"] != site["project_id"]:
        raise ApiError(
            "ERR_CROSS_PROJECT_REFERENCE",
            "The study plan and the study site belong to different projects.",
        )

    resource_category = payload.req_enum(data, "resource_category", C.RESOURCE_CATEGORIES)
    study_title = payload.req_string(data, "study_title")
    window_start = payload.req_date(data, "fieldwork_window_start")
    window_end = payload.req_date(data, "fieldwork_window_end")
    clearance = payload.opt_string(data, "cultural_clearance_reference")

    if not window_start < window_end:
        payload.bad("fieldwork_window_end", "must be strictly later than fieldwork_window_start")

    project = SV.project_of_plan(plan)
    SV.require_not_frozen(project)

    buffer_days = int(site["min_rest_buffer_days"])
    new_end = _buffered_end(window_end, buffer_days)
    for other in sorted_rows(db.studies, lambda s: s["site_id"] == site_id):
        if other["fieldwork_status"] == "COMPLETED":
            continue
        other_start = clock.parse_iso_date(other["fieldwork_window_start"])
        other_end = _buffered_end(clock.parse_iso_date(other["fieldwork_window_end"]), buffer_days)
        if window_start < other_end and other_start < new_end:
            raise ApiError(
                "ERR_SITE_WINDOW_CONFLICT",
                "The buffered fieldwork window overlaps another active study at this site.",
            )

    if site["cultural_sensitivity"] == "HIGH" and not (clearance or "").strip():
        raise ApiError(
            "ERR_CULTURAL_CLEARANCE_MISSING",
            "A study at a HIGH cultural-sensitivity site requires a cultural_clearance_reference.",
        )

    study = SV.base_row()
    study.update(
        {
            "study_plan_id": study_plan_id,
            "site_id": site_id,
            "resource_category": resource_category,
            "study_title": study_title,
            "fieldwork_window_start": clock.fmt_date(window_start),
            "fieldwork_window_end": clock.fmt_date(window_end),
            "cultural_clearance_reference": clearance,
            "fieldwork_status": "PLANNED",
            "review_status": "NOT_SUBMITTED",
            "additional_round_count": 0,
            "report_submitted_at": None,
            "report_submitted_by_user_id": None,
        }
    )
    db.studies[study["id"]] = study

    plan["attached_study_count"] = plan["attached_study_count"] + 1
    SV.touch(plan)

    SV.finalize_project(project)
    return response.object_response(S.study(study), 201)


@bp.get("/relicensing/studies")
def list_studies():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(
        sorted_rows(db.studies),
        S.study,
        ("study_plan_id", "site_id", "resource_category", "fieldwork_status", "review_status"),
    )


@bp.get("/relicensing/studies/<study_id>")
def get_study(study_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.study(SV.fetch("studies", study_id)))


_FIELDWORK_TRANSITIONS = {
    "START": ("PLANNED", "IN_PROGRESS"),
    "SUSPEND": ("IN_PROGRESS", "SUSPENDED"),
    "RESUME": ("SUSPENDED", "IN_PROGRESS"),
    "COMPLETE": ("IN_PROGRESS", "COMPLETED"),
}


@bp.post("/relicensing/studies/<study_id>/fieldwork")
def study_fieldwork(study_id):
    auth.authenticate(["Licensee"])
    study = SV.fetch("studies", study_id)
    data = payload.body()
    action = payload.req_enum(data, "action", C.FIELDWORK_ACTIONS)
    payload.opt_string(data, "fieldwork_note")

    plan = db.study_plans[study["study_plan_id"]]
    project = SV.project_of_plan(plan)
    SV.require_not_frozen(project)

    required, target = _FIELDWORK_TRANSITIONS[action]
    if study["fieldwork_status"] != required:
        raise ApiError(
            "ERR_STUDY_STATE_INVALID",
            "Action %s requires fieldwork_status %s." % (action, required),
        )

    if action == "START" and plan["status"] not in (
        "UNDER_AGENCY_REVIEW",
        "REVISION_REQUIRED",
        "APPROVED",
    ):
        raise ApiError(
            "ERR_STUDY_PLAN_STATE_INVALID",
            "Fieldwork may start only once the plan has been submitted.",
        )

    study["fieldwork_status"] = target
    SV.touch(study)

    SV.finalize_project(project)
    return response.object_response(S.study(study))


@bp.post("/relicensing/studies/<study_id>/report")
def study_report(study_id):
    auth.authenticate(["Licensee"])
    study = SV.fetch("studies", study_id)
    data = payload.body()
    payload.opt_string(data, "report_note")

    project = SV.project_of_study(study)
    SV.require_not_frozen(project)

    if study["review_status"] not in ("NOT_SUBMITTED", "ADDITIONAL_REQUIRED"):
        raise ApiError(
            "ERR_STUDY_STATE_INVALID",
            "A report cannot be submitted while review_status is %s." % study["review_status"],
        )
    if study["fieldwork_status"] != "COMPLETED":
        raise ApiError(
            "ERR_STUDY_STATE_INVALID",
            "A report requires fieldwork_status COMPLETED.",
        )

    study["review_status"] = "UNDER_REVIEW"
    study["report_submitted_at"] = clock.now_iso()
    study["report_submitted_by_user_id"] = g.user_id
    SV.touch(study)

    SV.finalize_project(project)
    return response.object_response(S.study(study))


@bp.post("/relicensing/studies/<study_id>/review-decision")
def study_review_decision(study_id):
    auth.authenticate(["AgencyReviewer"])
    study = SV.fetch("studies", study_id)
    plan = db.study_plans[study["study_plan_id"]]
    auth.require_project_scope(plan["project_id"])

    data = payload.body()
    decision = payload.req_enum(data, "decision", C.REVIEW_DECISIONS)
    payload.opt_string(data, "review_note")

    project = SV.project_of_plan(plan)
    SV.require_not_frozen(project)

    if study["review_status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_STUDY_STATE_INVALID",
            "A review decision requires review_status UNDER_REVIEW.",
        )

    if decision == "ACCEPT":
        study["review_status"] = "ACCEPTED"
    else:
        if study["additional_round_count"] >= C.MAX_ADDITIONAL_ROUNDS:
            raise ApiError(
                "ERR_STUDY_STATE_INVALID",
                "The additional-study loop is capped at %d rounds." % C.MAX_ADDITIONAL_ROUNDS,
            )
        study["review_status"] = "ADDITIONAL_REQUIRED"
        study["additional_round_count"] = study["additional_round_count"] + 1
        if study["fieldwork_status"] == "COMPLETED":
            study["fieldwork_status"] = "IN_PROGRESS"

    SV.touch(study)
    SV.finalize_project(project)
    return response.object_response(S.study(study))


# ---------------------------------------------------------------------------
# consultation comments
# ---------------------------------------------------------------------------


@bp.post("/relicensing/comments")
def create_comment():
    auth.authenticate(["AgencyReviewer", "Stakeholder"])
    data = payload.body()

    study_plan_id = payload.req_string(data, "study_plan_id")
    plan = SV.fetch("study_plans", study_plan_id)
    auth.require_project_scope(plan["project_id"])

    party_id = payload.req_string(data, "party_id")
    party = SV.fetch("parties", party_id)

    acting = auth.acting_party()
    if party["id"] != acting["id"] and party_id != g.user_id:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "A comment must be filed by the authoring party itself.",
        )

    if plan["project_id"] != party["project_id"]:
        raise ApiError(
            "ERR_CROSS_PROJECT_REFERENCE",
            "The study plan and the authoring party belong to different projects.",
        )

    resource_category = payload.req_enum(data, "resource_category", C.RESOURCE_CATEGORIES)
    comment_text = payload.req_string(data, "comment_text")
    payload.opt_bool(data, "is_mandatory_condition")

    project = SV.project_of_plan(plan)
    SV.require_not_frozen(project)

    comment = SV.base_row(versioned=False)
    comment.update(
        {
            "study_plan_id": study_plan_id,
            "party_id": party["id"],
            "resource_category": resource_category,
            "comment_text": comment_text,
            "is_mandatory_condition": bool(party["has_conditioning_authority"]),
            "resolution_status": "OPEN",
            "disposition": None,
            "resolved_at": None,
            "reopen_count": 0,
        }
    )
    db.comments[comment["id"]] = comment

    SV.refresh_plan_counters(plan)
    SV.touch(plan)

    SV.finalize_project(project)
    return response.object_response(S.comment(comment), 201)


@bp.get("/relicensing/comments")
def list_comments():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(
        sorted_rows(db.comments),
        S.comment,
        ("study_plan_id", "party_id", "resolution_status", "is_mandatory_condition"),
    )


@bp.get("/relicensing/comments/<comment_id>")
def get_comment(comment_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.comment(SV.fetch("comments", comment_id)))


@bp.post("/relicensing/comments/<comment_id>/resolve")
def resolve_comment(comment_id):
    auth.authenticate(["Licensee"])
    comment = SV.fetch("comments", comment_id)
    data = payload.body()
    disposition = payload.req_enum(data, "disposition", C.DISPOSITIONS)
    payload.opt_string(data, "resolution_note")

    plan = db.study_plans[comment["study_plan_id"]]
    project = SV.project_of_plan(plan)
    SV.require_not_frozen(project)

    if plan["status"] not in C.PLAN_OPEN_STATUSES:
        raise ApiError(
            "ERR_STUDY_PLAN_STATE_INVALID",
            "Comments may be resolved only while the plan is open.",
        )
    if comment["resolution_status"] != "OPEN":
        raise ApiError("ERR_COMMENT_ALREADY_RESOLVED", "The comment is already resolved.")

    comment["resolution_status"] = "RESOLVED"
    comment["disposition"] = disposition
    comment["resolved_at"] = clock.now_iso()

    SV.refresh_plan_counters(plan)
    SV.touch(plan)

    SV.finalize_project(project)
    return response.object_response(S.comment(comment))
