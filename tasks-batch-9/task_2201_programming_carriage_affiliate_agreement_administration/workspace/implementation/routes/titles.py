"""Content titles and their derived distribution coverage (PRD section 3.6)."""
from flask import Blueprint

import constants as K
from auth import guard
from cascades import block_window, recompute_title, title_windows, window_order
from common import ALL_READ_ROLES, created, list_endpoint, ok, read_endpoint
from lookup import must, put
from store import new_entity, touch
from validation import check_body, field

bp = Blueprint("titles", __name__)
BASE = "/carriage/content-titles"


@bp.route(BASE, methods=["POST"])
def create_title():
    guard(["RightsAdministrator"])
    body = check_body(
        {
            "title": field("string", required=True, min_len=1, max_len=200),
            "home_territory_code": field("territory", required=True),
            "linear_premiere_at": field("datetime", required=True),
        }
    )
    record = new_entity()
    record.update(
        {
            "title": body["title"],
            "home_territory_code": body["home_territory_code"],
            "linear_premiere_at": body["linear_premiere_at"],
            "rights_status": "PENDING_CLEARANCE",
            "cleared_window_count": 0,
            "distribution_coverage_status": "UNDISTRIBUTED",
        }
    )
    put("title", record)
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_titles():
    return list_endpoint(
        "title",
        ALL_READ_ROLES,
        ["rights_status", "distribution_coverage_status", "home_territory_code"],
    )


@bp.route(BASE + "/<title_id>", methods=["GET"])
def read_title(title_id):
    return read_endpoint("title", ALL_READ_ROLES, title_id)


@bp.route(BASE + "/<title_id>/rights-status", methods=["POST"])
def set_rights_status(title_id):
    guard(["RightsAdministrator"])
    body = check_body(
        {"rights_status": field("enum", required=True, enum=K.RIGHTS_STATUSES)}
    )
    title = must("title", title_id)
    target = body["rights_status"]

    title["rights_status"] = target

    if target == "EXPIRED_RIGHTS":
        # Destructive: every occupying window of this title loses its slot.
        for window in window_order(title_windows(title["id"])):
            if window["status"] in ("CLEARED", "ACTIVE"):
                block_window(window, "RIGHTS_LAPSED")
        # recompute_title performs the single version bump for this change
        recompute_title(title)
    else:
        touch(title)

    return ok(title)
