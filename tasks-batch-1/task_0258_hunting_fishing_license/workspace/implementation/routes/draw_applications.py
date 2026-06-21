"""DrawApplication endpoints (PRD §3.6)."""
from flask import Blueprint, request

import serialize
from db import store, parse_dt
from errors import (
    err, ERR_INVALID_STATE, ERR_ENTRY_CLOSED, ERR_DUPLICATE_ENTRY,
)
from middleware import require_roles
from response import success, success_list
from validation import (
    get_json_body, as_nonempty_str, parse_pagination, paginate,
)
from services.core import (
    get_applicant_or_404, get_draw_pool_or_404, get_draw_application_or_404,
)

bp = Blueprint("draw_applications", __name__)


@bp.route("/draw-applications", methods=["POST"])
@require_roles("Applicant", "DrawOfficer")
def create_draw_application():
    body = get_json_body()
    draw_pool_id = as_nonempty_str(body, "draw_pool_id", required=True)
    applicant_id = as_nonempty_str(body, "applicant_id", required=True)

    # FK existence in body order (PRD §2.5): draw_pool_id then applicant_id.
    pool = get_draw_pool_or_404(draw_pool_id)
    applicant = get_applicant_or_404(applicant_id)

    # Entry-window gate (ERR_ENTRY_CLOSED) before duplicate-entry gate (PRD §3.6).
    now = store.now()
    if pool["status"] != "ACCEPTING" or now >= parse_dt(pool["entry_deadline"]):
        raise err(ERR_ENTRY_CLOSED, "Pool entry is closed")

    # At most one non-WITHDRAWN application per pool per applicant (PRD §3.6).
    for a in store.draw_applications.values():
        if (
            a["draw_pool_id"] == draw_pool_id
            and a["applicant_id"] == applicant_id
            and a["status"] != "WITHDRAWN"
        ):
            raise err(ERR_DUPLICATE_ENTRY, "Applicant already entered this pool")

    record = {
        "draw_pool_id": draw_pool_id,
        "applicant_id": applicant_id,
        # Freeze snapshots of preference/bonus points (PRD §3.6).
        "points_at_entry": applicant["preference_points"],
        "bonus_at_entry": applicant["bonus_points"],
        "priority_score": 0,
        "status": "SUBMITTED",
        "issued_license_id": None,
    }
    store.stamp_new(record)
    store.draw_applications[record["id"]] = record
    return success(serialize.draw_application(record), status=201, response_type="object")


@bp.route("/draw-applications/<id>", methods=["GET"])
@require_roles("DrawOfficer", "Applicant")
def get_draw_application(id):
    record = get_draw_application_or_404(id)
    return success(serialize.draw_application(record), status=200, response_type="object")


@bp.route("/draw-applications", methods=["GET"])
@require_roles("DrawOfficer", "Applicant")
def list_draw_applications():
    limit, offset = parse_pagination()
    items = list(store.draw_applications.values())
    pool_id = request.args.get("draw_pool_id")
    if pool_id is not None:
        items = [r for r in items if r["draw_pool_id"] == pool_id]
    applicant_id = request.args.get("applicant_id")
    if applicant_id is not None:
        items = [r for r in items if r["applicant_id"] == applicant_id]
    issued_license_id = request.args.get("issued_license_id")
    if issued_license_id is not None:
        items = [r for r in items if r["issued_license_id"] == issued_license_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize.draw_application(r) for r in page], limit, offset, total
    )


@bp.route("/draw-applications/<id>/withdraw", methods=["POST"])
@require_roles("Applicant", "DrawOfficer")
def withdraw_draw_application(id):
    record = get_draw_application_or_404(id)
    # Permitted only while SUBMITTED and pool still ACCEPTING (PRD §3.6).
    if record["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Application is not SUBMITTED")
    pool = store.draw_pools.get(record["draw_pool_id"])
    if pool is None or pool["status"] != "ACCEPTING":
        raise err(ERR_INVALID_STATE, "Pool is no longer ACCEPTING")
    record["status"] = "WITHDRAWN"
    store.touch(record)
    return success(serialize.draw_application(record), status=200, response_type="object")
