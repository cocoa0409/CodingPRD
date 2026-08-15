"""Season windows: create (with supersession + OCC + gap/overlap), list, get, delete."""

from flask import Blueprint

import clock
import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list, success_no_content
from validate import (
    get_body, require_string, parse_date_strict, require_int,
    parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("season_windows", __name__)


def _view(w):
    return {
        "id": w["id"],
        "site_id": w["site_id"],
        "label": w["label"],
        "planned_open_date": w["planned_open_date"],
        "planned_close_date": w["planned_close_date"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


@bp.route("/season-windows", methods=["POST"])
def create_window():
    require_roles("OperatorAdmin")
    body = get_body()
    site_id = require_string(body, "site_id")
    label = require_string(body, "label")
    open_d = parse_date_strict(body.get("planned_open_date"), "planned_open_date")
    close_d = parse_date_strict(body.get("planned_close_date"), "planned_close_date")
    if "expected_site_version" not in body or body["expected_site_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_site_version is required")
    expected_site_version = body["expected_site_version"]
    if isinstance(expected_site_version, bool) or not isinstance(expected_site_version, int):
        raise err("ERR_INVALID_REQUEST", "expected_site_version must be an integer")
    if close_d < open_d:
        raise err("ERR_INVALID_REQUEST", "planned_close_date must be >= planned_open_date")

    # Existence: body FK site_id.
    site = db.sites.get(site_id)
    if site is None:
        raise err("ERR_SITE_NOT_FOUND")

    # OCC (priority 5, after existence, before business rules).
    if expected_site_version != site["version"]:
        raise err("ERR_STALE_VERSION")

    # Calendar rules (priority 14): overlap first, gap second.
    # Consider windows ACTIVE/COMPLETED plus PLANNED not being superseded.
    existing = [
        w for w in db.season_windows.values()
        if w["site_id"] == site_id and w["status"] in ("ACTIVE", "COMPLETED", "PLANNED")
    ]
    # The PLANNED window being superseded is excluded from consideration.
    superseding = [w for w in existing if w["status"] == "PLANNED"]
    superseded_ids = {w["id"] for w in superseding}
    considered = [w for w in existing if w["id"] not in superseded_ids]

    for w in considered:
        w_open = clock.parse_date(w["planned_open_date"])
        w_close = clock.parse_date(w["planned_close_date"])
        if open_d <= w_close and close_d >= w_open:
            raise err("ERR_SEASON_WINDOW_OVERLAP")

    for w in considered:
        w_open = clock.parse_date(w["planned_open_date"])
        w_close = clock.parse_date(w["planned_close_date"])
        gap_after = (open_d - w_close).days
        gap_before = (w_open - close_d).days
        if 0 < gap_after <= core_gap_days() or 0 < gap_before <= core_gap_days():
            raise err("ERR_SEASON_GAP_TOO_SHORT")

    # Supersede existing PLANNED windows.
    for w in superseding:
        w["status"] = "SUPERSEDED"
        w["updated_at"] = db.now_ts()

    now = db.now_ts()
    window = {
        "id": db.new_id(),
        "site_id": site_id,
        "label": label,
        "planned_open_date": open_d.isoformat(),
        "planned_close_date": close_d.isoformat(),
        "status": "PLANNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.season_windows[window["id"]] = window
    site["version"] += 1
    site["updated_at"] = now
    return success_object(_view(window), status=201)


def core_gap_days():
    from services.core import MAINTENANCE_GAP_DAYS
    return MAINTENANCE_GAP_DAYS


@bp.route("/season-windows", methods=["GET"])
def list_windows():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.season_windows.values())
    site_f = get_filter("site_id")
    status_f = get_filter("status")
    if site_f is not None:
        items = [w for w in items if w["site_id"] == site_f]
    if status_f is not None:
        items = [w for w in items if w["status"] == status_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(w) for w in page], total, limit, offset)


@bp.route("/season-windows/<wid>", methods=["GET"])
def get_window(wid):
    get_auth()
    w = db.season_windows.get(wid)
    if w is None:
        raise err("ERR_NOT_FOUND")
    return success_object(_view(w))


@bp.route("/season-windows/<wid>", methods=["DELETE"])
def delete_window(wid):
    require_roles("OperatorAdmin")
    w = db.season_windows.get(wid)
    if w is None:
        raise err("ERR_NOT_FOUND")
    if w["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Only a PLANNED window can be cancelled")
    w["status"] = "CANCELLED"
    w["updated_at"] = db.now_ts()
    return success_no_content()
