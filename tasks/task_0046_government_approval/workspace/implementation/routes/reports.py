"""SLA performance reporting."""

from flask import Blueprint, request

import db
from middleware import require_role
from response import success
from services import calculations

bp = Blueprint("reports", __name__)


@bp.get("/reports/sla-performance")
def sla_performance():
    require_role("PlatformAdmin")
    matter_id = request.args.get("matter_id")
    department_id = request.args.get("department_id")
    since = request.args.get("since")
    until = request.args.get("until")

    apps = db.all_rows("applications")

    matter_version_ids = None
    if matter_id:
        matter_version_ids = {
            v["id"] for v in db.find_many("matter_versions", matter_id=matter_id)
        }
    department_app_ids = None
    if department_id:
        department_app_ids = {
            t["application_id"] for t in db.find_many(
                "review_tasks", department_id=department_id)
        }

    selected = []
    for a in apps:
        if matter_version_ids is not None and a["matter_version_id"] not in matter_version_ids:
            continue
        if department_app_ids is not None and a["id"] not in department_app_ids:
            continue
        if since and (a.get("created_at") or "") < since:
            continue
        if until and (a.get("created_at") or "") > until:
            continue
        selected.append(a)

    total = len(selected)
    on_track = warning = overdue = approved = rejected = 0
    for a in selected:
        version = db.find_by_id("matter_versions", a["matter_version_id"])
        sla = calculations.time_limit_warning(a, version)
        s = sla["status"]
        if s == "ON_TRACK":
            on_track += 1
        elif s == "WARNING":
            warning += 1
        elif s == "OVERDUE":
            overdue += 1
        if a["review_status"] == "APPROVED":
            approved += 1
        elif a["review_status"] == "REJECTED":
            rejected += 1

    return success({
        "total_applications": total,
        "on_track": on_track,
        "warning": warning,
        "overdue": overdue,
        "approved": approved,
        "rejected": rejected,
        "filters": {
            "matter_id": matter_id,
            "department_id": department_id,
            "since": since,
            "until": until,
        },
    }, 200)
