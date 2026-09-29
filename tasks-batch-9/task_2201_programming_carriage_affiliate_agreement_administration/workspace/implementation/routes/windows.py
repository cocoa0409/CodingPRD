"""Rights windows: the half-open occupancy regime (PRD 3.6)."""
from flask import Blueprint

import constants as K
from auth import enforce_scope, guard
from calc import holdback_days, window_neighbours
from cascades import blackout_conflicts, recompute_title
from common import (
    ALL_READ_ROLES,
    created,
    list_endpoint,
    ok,
    read_endpoint,
    scope_from_body_agreement,
)
from errors import ApiError
from lookup import must, put
from store import db, new_entity, touch
from validation import bad, check_body, field

bp = Blueprint("windows", __name__)
BASE = "/carriage/rights-windows"

WINDOW_ACTIONS = ["CLEAR", "BLOCK", "UNBLOCK"]


@bp.route(BASE, methods=["POST"])
def create_window():
    caller = guard(["RightsAdministrator"])
    scope_from_body_agreement(caller)
    body = check_body(
        {
            "agreement_id": field("id", required=True),
            "content_title_id": field("id", required=True),
            "platform": field("enum", required=True, enum=K.PLATFORMS),
            "territory_code": field("territory", required=True),
            "window_start": field("datetime", required=True),
            "window_end": field("datetime", required=True),
            "exclusivity": field("enum", required=True, enum=K.EXCLUSIVITIES),
        }
    )
    if body["window_end"] <= body["window_start"]:
        bad("window_end must be strictly later than window_start")

    agreement = must("agreement", body["agreement_id"])
    title = must("title", body["content_title_id"])

    record = new_entity()
    record.update(
        {
            "agreement_id": agreement["id"],
            "content_title_id": title["id"],
            "platform": body["platform"],
            "territory_code": body["territory_code"],
            "window_start": body["window_start"],
            "window_end": body["window_end"],
            "exclusivity": body["exclusivity"],
            "windowing_holdback_days": 0,
            "concurrent_licensee_count": 0,
            "status": "PLANNED",
            "block_reason": "NONE",
        }
    )
    # A PLANNED window occupies nothing, so no occupancy check runs here.
    record["windowing_holdback_days"] = holdback_days(record, title)
    put("window", record)
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_windows():
    return list_endpoint(
        "window",
        ALL_READ_ROLES,
        [
            "agreement_id",
            "content_title_id",
            "platform",
            "territory_code",
            "status",
            "exclusivity",
        ],
    )


@bp.route(BASE + "/<window_id>", methods=["GET"])
def read_window(window_id):
    return read_endpoint("window", ALL_READ_ROLES, window_id)


def _check_occupancy(window):
    """Exclusivity then the aggregate cap; returns the neighbour count."""
    neighbours = window_neighbours(window)
    if window["exclusivity"] == "EXCLUSIVE":
        if neighbours:
            raise ApiError(
                "ERR_WINDOW_EXCLUSIVITY_CONFLICT",
                "an exclusive grant tolerates no overlap",
            )
        return 0
    for other in neighbours:
        if other["exclusivity"] == "EXCLUSIVE":
            raise ApiError(
                "ERR_WINDOW_EXCLUSIVITY_CONFLICT",
                "an exclusive neighbour already holds this slot",
            )
    if len(neighbours) + 1 > K.MAX_CONCURRENT_NONEXCLUSIVE:
        raise ApiError(
            "ERR_WINDOW_CONCURRENCY_CAP_EXCEEDED",
            "at most three simultaneous non-exclusive licensees are permitted",
        )
    return len(neighbours)


@bp.route(BASE + "/<window_id>/lifecycle", methods=["POST"])
def window_lifecycle(window_id):
    caller = guard(["RightsAdministrator"])
    body = check_body(
        {
            "action": field("enum", required=True, enum=WINDOW_ACTIONS),
            "block_reason": field("enum", enum=K.BLOCK_REASONS),
        }
    )
    window = must("window", window_id)
    agreement = db.agreements.get(window["agreement_id"])
    enforce_scope(caller, agreement["distributor_id"] if agreement else None)
    title = db.content_titles.get(window["content_title_id"])
    action = body["action"]

    if action == "CLEAR":
        if window["status"] != "PLANNED":
            raise ApiError("ERR_INVALID_WINDOW_STATE", "clearance requires PLANNED")
        if agreement["lifecycle_status"] != "EXECUTED":
            raise ApiError(
                "ERR_AGREEMENT_NOT_EXECUTED",
                "a suspended agreement cannot clear new rights",
            )
        if title["rights_status"] != "OWNED_CLEARED":
            raise ApiError(
                "ERR_TITLE_RIGHTS_NOT_CLEARED", "the title's rights are not cleared"
            )
        # the regulatory obligation outranks the private contractual matter
        if blackout_conflicts(window) is not None:
            raise ApiError(
                "ERR_BLACKOUT_WINDOW_CONFLICT",
                "a blackout rule of this agreement covers the window",
            )
        count = _check_occupancy(window)
        if window["windowing_holdback_days"] < K.PLATFORM_HOLDBACK_DAYS[
            window["platform"]
        ]:
            raise ApiError(
                "ERR_HOLDBACK_NOT_SATISFIED",
                "the platform holdback has not elapsed since the linear premiere",
            )
        if not (
            agreement["term_start_date"] <= window["window_start"]
            and window["window_end"] <= agreement["term_end_date"]
        ):
            raise ApiError(
                "ERR_WINDOW_OUTSIDE_TERM", "the window is not contained in the term"
            )

        window["status"] = "CLEARED"
        window["block_reason"] = "NONE"
        window["concurrent_licensee_count"] = count
        touch(window)
        recompute_title(title)
        return ok(window)

    if action == "BLOCK":
        if window["status"] not in ("CLEARED", "ACTIVE"):
            raise ApiError(
                "ERR_INVALID_WINDOW_STATE", "blocking requires CLEARED or ACTIVE"
            )
        window["status"] = "BLOCKED"
        window["block_reason"] = "MANUAL_BLOCK"
        touch(window)
        recompute_title(title)
        return ok(window)

    # UNBLOCK
    if window["status"] != "BLOCKED":
        raise ApiError("ERR_INVALID_WINDOW_STATE", "unblocking requires BLOCKED")
    if agreement["lifecycle_status"] != "EXECUTED":
        raise ApiError(
            "ERR_AGREEMENT_NOT_EXECUTED", "the granting agreement is not EXECUTED"
        )
    if title["rights_status"] != "OWNED_CLEARED":
        raise ApiError(
            "ERR_TITLE_RIGHTS_NOT_CLEARED", "the title's rights are not cleared"
        )
    if blackout_conflicts(window) is not None:
        raise ApiError(
            "ERR_BLACKOUT_WINDOW_CONFLICT",
            "a blackout rule of this agreement covers the window",
        )
    # The holdback and containment tests belong to the initial clearance only.
    count = _check_occupancy(window)
    window["status"] = "CLEARED"
    window["block_reason"] = "NONE"
    window["concurrent_licensee_count"] = count
    touch(window)
    recompute_title(title)
    return ok(window)
