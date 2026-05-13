"""Review stage routes: start-aggregation, publish."""
from flask import Blueprint

from clock import get_now, parse_iso
from common import check_version, get_json_body, stamp_update
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.audit import emit_audit
from services.calculations import stage_aggregate, to_decimal


bp = Blueprint("review_stages", __name__)


def _stage_kind_order(kind):
    return {"PRELIMINARY": 1, "SEMIFINAL": 2, "FINAL": 3}.get(kind, 0)


def _project_stage(project_id, kind):
    for s in db.review_stages.values():
        if s.get("project_id") == project_id and s.get("stage_kind") == kind:
            return s
    return None


def _stage_submissions(stage):
    """The submissions in scope of this stage at the time of aggregation."""
    project_id = stage["project_id"]
    kind = stage["stage_kind"]
    if kind == "PRELIMINARY":
        return [s for s in db.submissions.values()
                if s.get("project_id") == project_id and s.get("status") in {"ACCEPTED", "ADVANCING_SEMIFINAL", "ELIMINATED"}]
    if kind == "SEMIFINAL":
        return [s for s in db.submissions.values()
                if s.get("project_id") == project_id and s.get("status") in {"ADVANCING_SEMIFINAL", "ADVANCING_FINAL", "ELIMINATED"}
                and "SEMIFINAL" in (s.get("aggregate_score_by_stage") or {}) or s.get("status") == "ADVANCING_SEMIFINAL"]
    if kind == "FINAL":
        return [s for s in db.submissions.values()
                if s.get("project_id") == project_id and s.get("status") in {"ADVANCING_FINAL", "WINNER", "RUNNER_UP", "ELIMINATED"}]
    return []


def _in_stage_submissions_for_publish(stage):
    """Submissions considered "in stage" for publish quorum check, before cascade."""
    project_id = stage["project_id"]
    kind = stage["stage_kind"]
    if kind == "PRELIMINARY":
        return [s for s in db.submissions.values()
                if s.get("project_id") == project_id and s.get("status") == "ACCEPTED"]
    if kind == "SEMIFINAL":
        return [s for s in db.submissions.values()
                if s.get("project_id") == project_id and s.get("status") == "ADVANCING_SEMIFINAL"]
    if kind == "FINAL":
        return [s for s in db.submissions.values()
                if s.get("project_id") == project_id and s.get("status") == "ADVANCING_FINAL"]
    return []


@bp.route("/review-stages/<review_stage_id>/start-aggregation", methods=["POST"])
def start_aggregation(review_stage_id):
    require_roles({"PlatformOps"})
    stage = db.review_stages.get(review_stage_id)
    if not stage:
        raise api_error("ERR_NOT_FOUND", "review stage not found")
    if stage.get("status") != "OPEN":
        raise api_error("ERR_INVALID_STATE", "stage must be OPEN to start aggregation")
    body = get_json_body()
    check_version(stage, body)
    if get_now() < parse_iso(stage["ends_at"]):
        raise api_error("ERR_INVALID_STATE", "stage cannot start aggregation before ends_at")

    project = db.projects.get(stage["project_id"])
    stage["status"] = "AGGREGATING"
    stamp_update(stage)

    # Compute per-submission aggregate
    in_scope = _in_stage_submissions_for_publish(stage)
    recompute_stage_aggregates(stage, in_scope, project)
    return success(stage)


def recompute_stage_aggregates(stage, in_scope_submissions, project):
    """For each in-scope submission, compute the aggregate from SUBMITTED assignments."""
    for sub in in_scope_submissions:
        scores = []
        client_id = project.get("client_id") if project else None
        for asn in db.review_assignments.values():
            if (asn.get("review_stage_id") == stage["id"]
                    and asn.get("submission_id") == sub["id"]
                    and asn.get("status") == "SUBMITTED"):
                scores.append({
                    "id": asn["id"],
                    "score": asn.get("aggregated_score", 0),
                    "is_client": asn.get("reviewer_id") == client_id,
                })
        if len(scores) >= stage["reviewer_quorum"]:
            agg = stage_aggregate(
                scores, stage["stage_kind"],
                project.get("client_participates_final", False) if project else False,
            )
            if agg is not None:
                m = dict(sub.get("aggregate_score_by_stage") or {})
                m[stage["stage_kind"]] = agg
                sub["aggregate_score_by_stage"] = m
                stamp_update(sub)


@bp.route("/review-stages/<review_stage_id>/publish", methods=["POST"])
def publish_stage(review_stage_id):
    user_id, _ = require_roles({"PlatformOps"})
    stage = db.review_stages.get(review_stage_id)
    if not stage:
        raise api_error("ERR_NOT_FOUND", "review stage not found")
    if stage.get("status") == "PUBLISHED":
        raise api_error("ERR_STAGE_ALREADY_PUBLISHED", "stage already published")
    if stage.get("status") != "AGGREGATING":
        raise api_error("ERR_INVALID_STATE", "stage must be AGGREGATING to publish")
    body = get_json_body()
    check_version(stage, body)

    project = db.projects.get(stage["project_id"])

    # Quorum check
    in_scope = _in_stage_submissions_for_publish(stage)
    for sub in in_scope:
        submitted_count = sum(
            1 for asn in db.review_assignments.values()
            if asn.get("review_stage_id") == stage["id"]
            and asn.get("submission_id") == sub["id"]
            and asn.get("status") == "SUBMITTED"
        )
        disputed_count = sum(
            1 for asn in db.review_assignments.values()
            if asn.get("review_stage_id") == stage["id"]
            and asn.get("submission_id") == sub["id"]
            and asn.get("status") == "DISPUTED"
        )
        if submitted_count < stage["reviewer_quorum"] or disputed_count > 0:
            raise api_error(
                "ERR_QUORUM_NOT_MET",
                f"submission {sub['id']} fails quorum or has DISPUTED assignment",
            )

    # Compute advancing_submission_ids and cascade.
    threshold = to_decimal(stage["passing_threshold"])
    kind = stage["stage_kind"]
    advancing = []
    for sub in in_scope:
        agg_map = sub.get("aggregate_score_by_stage") or {}
        agg = to_decimal(agg_map.get(kind, 0))
        if kind == "PRELIMINARY":
            if agg >= threshold:
                sub["status"] = "ADVANCING_SEMIFINAL"
                advancing.append(sub["id"])
            else:
                sub["status"] = "ELIMINATED"
            stamp_update(sub)
        elif kind == "SEMIFINAL":
            if agg >= threshold:
                sub["status"] = "ADVANCING_FINAL"
                advancing.append(sub["id"])
            else:
                sub["status"] = "ELIMINATED"
            stamp_update(sub)
        # For FINAL, do not cascade here; the award call handles it.

    stage["status"] = "PUBLISHED"
    stage["advancing_submission_ids"] = advancing
    stamp_update(stage)

    # Project-level transition
    if kind == "PRELIMINARY":
        if project and project.get("status") == "IN_PRELIMINARY":
            project["status"] = "IN_SEMIFINAL"
            stamp_update(project)
        semi = _project_stage(stage["project_id"], "SEMIFINAL")
        if semi and semi.get("status") in {"PENDING"}:
            semi["status"] = "OPEN"
            stamp_update(semi)
    elif kind == "SEMIFINAL":
        if project and project.get("status") == "IN_SEMIFINAL":
            project["status"] = "IN_FINAL"
            stamp_update(project)
        final = _project_stage(stage["project_id"], "FINAL")
        if final and final.get("status") in {"PENDING"}:
            final["status"] = "OPEN"
            stamp_update(final)

    emit_audit(
        "STAGE_PUBLISHED",
        "PLATFORM",
        user_id,
        "REVIEW_STAGE",
        stage["id"],
        {"stage_kind": kind, "advancing_submission_ids": advancing},
    )

    return success(stage)
