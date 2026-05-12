"""Progress updates."""

from flask import Blueprint, g

from clock import CLOCK
from db import DB, LOCK, new_id
from errors import forbidden, not_found, validation_error
from middleware import require_roles
from response import success_array, success_object
from services.audit import append_audit
from services.common import (
    bump_version,
    get_json_body,
    paginate,
    parse_pagination,
    require_str,
    stamp_create_appendonly,
)
from services.serializers import progress_update_view


bp = Blueprint("progress", __name__)


VALID_VISIBILITY = {"PUBLIC", "BACKERS_ONLY"}


@bp.route("/projects/<project_id>/progress-updates", methods=["POST"])
@require_roles("Initiator")
def create_progress(project_id):
    body = get_json_body()
    title = require_str(body, "title")
    body_md = require_str(body, "body_md")
    visibility = body.get("visibility")
    if visibility not in VALID_VISIBILITY:
        raise validation_error("visibility must be PUBLIC or BACKERS_ONLY")
    milestone_label = body.get("milestone_label")
    if milestone_label is not None and not isinstance(milestone_label, str):
        raise validation_error("milestone_label must be a string")
    is_delay_notice = body.get("is_delay_notice", False)
    if is_delay_notice is None:
        is_delay_notice = False
    if not isinstance(is_delay_notice, bool):
        raise validation_error("is_delay_notice must be a boolean")

    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()
        if project["initiator_id"] != g.user_id:
            raise forbidden()
        rec = stamp_create_appendonly({
            "id": new_id(),
            "project_id": project_id,
            "title": title,
            "body_md": body_md,
            "visibility": visibility,
            "milestone_label": milestone_label,
            "is_delay_notice": is_delay_notice,
        })
        DB.progress_updates[rec["id"]] = rec
        project["last_update_published_at"] = CLOCK.now()
        bump_version(project)
        append_audit(
            subject_type="PROJECT",
            subject_id=project["id"],
            event_type="STATUS_CHANGE",
            payload={"event": "progress_update_published", "progress_update_id": rec["id"]},
            actor_role=g.role,
            actor_id=g.user_id,
        )
    return success_object(progress_update_view(rec), status=201)


@bp.route("/projects/<project_id>/progress-updates", methods=["GET"])
@require_roles("Backer", "Initiator", "PlatformAdmin")
def list_progress(project_id):
    limit, offset = parse_pagination()
    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()
        items = [p for p in DB.progress_updates.values() if p["project_id"] == project_id]

        # Filter BACKERS_ONLY for non-privileged callers who aren't backers of this project
        privileged = g.role in ("PlatformAdmin", "Initiator")
        if privileged and g.role == "Initiator" and project["initiator_id"] != g.user_id:
            privileged = False
        if not privileged:
            backer_ids = {o["backer_id"] for o in DB.orders.values() if o["project_id"] == project_id}
            is_backer = (g.role == "Backer" and g.user_id in backer_ids)
            if not is_backer:
                items = [p for p in items if p["visibility"] == "PUBLIC"]
        items.sort(key=lambda r: r["created_at"])
        page, total, has_more = paginate(items, limit, offset)
        return success_array([progress_update_view(p) for p in page], limit=limit, offset=offset,
                             total_count=total, has_more=has_more)
