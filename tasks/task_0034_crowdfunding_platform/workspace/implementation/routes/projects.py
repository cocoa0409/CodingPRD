"""Project lifecycle: CRUD, submit, review, cancel."""

from datetime import timedelta

from flask import Blueprint, g, request

from clock import CLOCK, parse_iso
from db import DB, LOCK, new_id  # noqa: F401
from errors import (
    deadline_too_soon,
    forbidden,
    invalid_amount,
    invalid_state,
    kyc_required,
    no_rewards,
    not_found,
    segregation_violation,
    validation_error,
)
from middleware import require_roles
from response import success_array, success_object
from services.audit import append_audit
from services.common import (
    bump_version,
    check_occ,
    get_json_body,
    paginate,
    parse_pagination,
    require_positive_int,
    require_str,
    stamp_create,
)
from services.projects import _do_cancel, transition_project_status
from services.serializers import project_view


bp = Blueprint("projects", __name__)


VALID_CATEGORIES = {"TECH", "ART", "COMMUNITY"}
VALID_FUNDING_MODELS = {"ALL_OR_NOTHING", "KEEP_IT_ALL"}
VALID_DECISIONS = {"APPROVE", "REQUEST_CHANGES", "REJECT"}


def _validate_title(title):
    if not isinstance(title, str):
        raise validation_error("title must be a string")
    if not (4 <= len(title) <= 120):
        raise validation_error("title must be 4..120 characters")
    return title


def _validate_media_uris(uris):
    if not isinstance(uris, list):
        raise validation_error("media_uris must be a list")
    if not (1 <= len(uris) <= 10):
        raise validation_error("media_uris must contain 1..10 entries")
    for u in uris:
        if not isinstance(u, str) or not u:
            raise validation_error("each media_uri must be a non-empty string")
    return list(uris)


@bp.route("/projects", methods=["POST"])
@require_roles("Initiator")
def create_project():
    body = get_json_body()
    title = _validate_title(body.get("title"))
    category = body.get("category")
    if category not in VALID_CATEGORIES:
        raise validation_error("category must be one of TECH, ART, COMMUNITY")
    description_md = require_str(body, "description_md")
    media_uris = _validate_media_uris(body.get("media_uris"))
    risk_disclosure = require_str(body, "risk_disclosure")
    funding_model = body.get("funding_model")
    if funding_model not in VALID_FUNDING_MODELS:
        raise validation_error("funding_model must be ALL_OR_NOTHING or KEEP_IT_ALL")
    funding_target_cents = require_positive_int(body, "funding_target_cents")
    deadline_raw = body.get("deadline")
    if not deadline_raw:
        raise validation_error("deadline is required")
    try:
        deadline = parse_iso(deadline_raw)
    except ValueError as e:
        raise validation_error(str(e))

    now = CLOCK.now()
    if deadline <= now + timedelta(hours=24):
        raise deadline_too_soon()

    with LOCK:
        rec = stamp_create({
            "id": new_id(),
            "initiator_id": g.user_id,
            "title": title,
            "category": category,
            "description_md": description_md,
            "media_uris": media_uris,
            "risk_disclosure": risk_disclosure,
            "funding_model": funding_model,
            "funding_target_cents": funding_target_cents,
            "deadline": deadline,
            "status": "DRAFT",
            "provisional_raised_cents": 0,
            "final_raised_cents": 0,
            "rejection_reason": None,
            "last_update_published_at": None,
        })
        DB.projects[rec["id"]] = rec
        DB.review_decisions[rec["id"]] = {"content": None, "legal": None, "financial": None}
    return success_object(project_view(rec), status=201)


@bp.route("/projects/<id>", methods=["GET"])
@require_roles("Initiator", "Backer", "ContentReviewer", "LegalReviewer", "FinancialReviewer", "PlatformAdmin")
def get_project(id):
    with LOCK:
        rec = DB.projects.get(id)
        if rec is None:
            raise not_found()
        return success_object(project_view(rec))


@bp.route("/projects", methods=["GET"])
@require_roles("Initiator", "Backer", "ContentReviewer", "LegalReviewer", "FinancialReviewer", "PlatformAdmin")
def list_projects():
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    category_filter = request.args.get("category")
    with LOCK:
        items = list(DB.projects.values())
        if status_filter:
            items = [p for p in items if p["status"] == status_filter]
        if category_filter:
            items = [p for p in items if p["category"] == category_filter]
        items.sort(key=lambda p: p["created_at"])
        page, total, has_more = paginate(items, limit, offset)
        return success_array([project_view(p) for p in page], limit=limit, offset=offset,
                             total_count=total, has_more=has_more)


@bp.route("/projects/<id>", methods=["PATCH"])
@require_roles("Initiator")
def patch_project(id):
    body = get_json_body()
    with LOCK:
        rec = DB.projects.get(id)
        if rec is None:
            raise not_found()
        if rec["initiator_id"] != g.user_id:
            raise forbidden("Initiator does not own this project")
        if rec["status"] != "DRAFT":
            raise invalid_state("Project not in DRAFT")
        check_occ(rec, body)
        if "title" in body:
            rec["title"] = _validate_title(body["title"])
        if "description_md" in body:
            rec["description_md"] = require_str(body, "description_md")
        if "media_uris" in body:
            rec["media_uris"] = _validate_media_uris(body["media_uris"])
        if "risk_disclosure" in body:
            rec["risk_disclosure"] = require_str(body, "risk_disclosure")
        if "funding_model" in body:
            fm = body["funding_model"]
            if fm not in VALID_FUNDING_MODELS:
                raise validation_error("funding_model invalid")
            rec["funding_model"] = fm
        if "funding_target_cents" in body:
            rec["funding_target_cents"] = require_positive_int(body, "funding_target_cents")
        if "deadline" in body:
            try:
                rec["deadline"] = parse_iso(body["deadline"])
            except ValueError as e:
                raise validation_error(str(e))
        bump_version(rec)
        return success_object(project_view(rec))


@bp.route("/projects/<id>/submit", methods=["POST"])
@require_roles("Initiator")
def submit_project(id):
    with LOCK:
        rec = DB.projects.get(id)
        if rec is None:
            raise not_found()
        if rec["initiator_id"] != g.user_id:
            raise forbidden("Initiator does not own this project")
        if rec["status"] != "DRAFT":
            raise invalid_state("Project not in DRAFT")

        initiator = DB.initiators.get(rec["initiator_id"])
        if initiator is None or initiator.get("kyc_status") != "VERIFIED":
            raise kyc_required()

        # Field-presence preconditions
        title = rec.get("title")
        if not title or not str(title).strip():
            raise validation_error("title required for submission")
        desc = rec.get("description_md")
        if not desc or not str(desc).strip():
            raise validation_error("description_md required for submission")
        risk = rec.get("risk_disclosure")
        if not risk or not str(risk).strip():
            raise validation_error("risk_disclosure required for submission")
        media = rec.get("media_uris") or []
        if len(media) < 1:
            raise validation_error("at least one media_uri required")

        # Deadline check at submit time
        now = CLOCK.now()
        if int(rec.get("funding_target_cents", 0)) <= 0:
            raise invalid_amount("funding_target_cents must be > 0")
        if rec.get("deadline") is None or rec["deadline"] <= now + timedelta(hours=24):
            raise deadline_too_soon()

        # At least one reward defined
        rewards = [r for r in DB.rewards.values() if r["project_id"] == rec["id"]]
        if len(rewards) < 1:
            raise no_rewards()

        transition_project_status(rec, "CONTENT_REVIEW", actor_role=g.role, actor_id=g.user_id)
        return success_object(project_view(rec))


def _record_review_decision(project, stage, reviewer_id):
    DB.review_decisions.setdefault(project["id"], {"content": None, "legal": None, "financial": None})
    DB.review_decisions[project["id"]][stage] = reviewer_id


def _check_segregation(project_id, stage, reviewer_id):
    record = DB.review_decisions.get(project_id) or {"content": None, "legal": None, "financial": None}
    other_stages = [s for s in ("content", "legal", "financial") if s != stage]
    for s in other_stages:
        prior = record.get(s)
        if prior is not None and prior == reviewer_id:
            raise segregation_violation()


def _do_review(project_id, stage, expected_status, advance_to):
    body = get_json_body()
    decision = body.get("decision")
    if decision not in VALID_DECISIONS:
        raise validation_error("decision must be APPROVE, REQUEST_CHANGES, or REJECT")
    message = body.get("message")
    if message is not None and not isinstance(message, str):
        raise validation_error("message must be a string")
    with LOCK:
        rec = DB.projects.get(project_id)
        if rec is None:
            raise not_found()
        if rec["status"] != expected_status:
            raise invalid_state(f"Project not in {expected_status}")

        if decision == "APPROVE":
            _check_segregation(rec["id"], stage, g.user_id)
            _record_review_decision(rec, stage, g.user_id)
            transition_project_status(rec, advance_to, actor_role=g.role, actor_id=g.user_id,
                                      payload={"decision": "APPROVE", "stage": stage})
            # Use REVIEW_DECISION event_type instead of generic STATUS_CHANGE in audit?
            # The scaffold says reviewer transitions append REVIEW_DECISION; we add an extra audit.
            append_audit(
                subject_type="PROJECT",
                subject_id=rec["id"],
                event_type="REVIEW_DECISION",
                payload={"stage": stage, "decision": "APPROVE", "message": message},
                actor_role=g.role,
                actor_id=g.user_id,
            )
        elif decision == "REQUEST_CHANGES":
            rec["rejection_reason"] = message
            transition_project_status(rec, "DRAFT", actor_role=g.role, actor_id=g.user_id,
                                      payload={"decision": "REQUEST_CHANGES", "stage": stage})
            append_audit(
                subject_type="PROJECT",
                subject_id=rec["id"],
                event_type="REVIEW_DECISION",
                payload={"stage": stage, "decision": "REQUEST_CHANGES", "message": message},
                actor_role=g.role,
                actor_id=g.user_id,
            )
        else:  # REJECT
            rec["rejection_reason"] = message
            transition_project_status(rec, "REJECTED", actor_role=g.role, actor_id=g.user_id,
                                      payload={"decision": "REJECT", "stage": stage})
            append_audit(
                subject_type="PROJECT",
                subject_id=rec["id"],
                event_type="REVIEW_DECISION",
                payload={"stage": stage, "decision": "REJECT", "message": message},
                actor_role=g.role,
                actor_id=g.user_id,
            )
        return success_object(project_view(rec))


@bp.route("/projects/<id>/review-content", methods=["POST"])
@require_roles("ContentReviewer")
def review_content(id):
    return _do_review(id, "content", expected_status="CONTENT_REVIEW", advance_to="LEGAL_REVIEW")


@bp.route("/projects/<id>/review-legal", methods=["POST"])
@require_roles("LegalReviewer")
def review_legal(id):
    return _do_review(id, "legal", expected_status="LEGAL_REVIEW", advance_to="FINANCIAL_REVIEW")


@bp.route("/projects/<id>/review-financial", methods=["POST"])
@require_roles("FinancialReviewer")
def review_financial(id):
    return _do_review(id, "financial", expected_status="FINANCIAL_REVIEW", advance_to="LIVE")


@bp.route("/projects/<id>/cancel", methods=["POST"])
@require_roles("Initiator")
def cancel_project(id):
    body = get_json_body()
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise validation_error("reason must be a string")
    with LOCK:
        rec = DB.projects.get(id)
        if rec is None:
            raise not_found()
        if rec["initiator_id"] != g.user_id:
            raise forbidden("Initiator does not own this project")
        # Must be LIVE and before deadline
        if rec["status"] != "LIVE":
            raise invalid_state("Project not in LIVE")
        now = CLOCK.now()
        if rec.get("deadline") is not None and now >= rec["deadline"]:
            raise invalid_state("Project deadline has passed; cannot cancel")
        _do_cancel(rec, reason)
        return success_object(project_view(rec))
