"""DevelopmentPattern endpoints."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_INVALID_PATTERN_WINDOW,
    ERR_NOT_FOUND,
    ERR_PATTERN_IN_USE,
    ERR_PATTERN_PERIOD_OVERLAP,
    ERR_TRIANGLE_STALE,
)
from middleware import authorized
from response import success_object, success_list
from routes.helpers import new_common_record, touch, sorted_by_creation
from services.calculations import select_factors, estimate_tail
from services.cascade import pattern_withdrawn_staleness
from services.serializers import pattern_view
from util import dec
from validate import (
    get_body,
    parse_pagination,
    reject_server_managed,
    req_enum,
    req_quarter,
    req_str,
    require_body_fk,
    require_path_resource,
)

bp = Blueprint("development_patterns", __name__)

PATTERN_COMPUTED = ["selected_factors", "tail_factor", "status"]


def _window_covers(pattern, vq):
    return pattern["effective_from_quarter"] <= vq < pattern["effective_to_quarter"]


def _windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [a_from, a_to) intersects [b_from, b_to) iff a_from < b_to AND b_from < a_to."""
    return a_from < b_to and b_from < a_to


@bp.post("/actuarial/development-patterns")
def create_pattern():
    authorized(["ActuarialAnalyst"])
    body = get_body()
    reject_server_managed(body, PATTERN_COMPUTED)
    segment_id = req_str(body, "segment_id")
    basis = req_enum(body, "basis", ["PAID", "INCURRED"])
    valuation_quarter = req_quarter(body, "valuation_quarter")
    eff_from = req_quarter(body, "effective_from_quarter")
    eff_to = req_quarter(body, "effective_to_quarter")

    require_body_fk("segments", segment_id, "segment_id")

    # Triangle must exist and be non-stale.
    triangle = None
    for t in db["triangles"].values():
        if (t["segment_id"] == segment_id and t["basis"] == basis
                and t["valuation_quarter"] == valuation_quarter):
            triangle = t
            break
    if triangle is None:
        raise_error(ERR_NOT_FOUND, "triangle not found for (segment, basis, valuation_quarter)")
    if triangle["is_stale"]:
        raise_error(ERR_TRIANGLE_STALE, "source triangle is stale")

    # Window validity: from < to (tier 10 temporal; ERR_INVALID_PATTERN_WINDOW at 422)
    if not (eff_from < eff_to):
        raise_error(ERR_INVALID_PATTERN_WINDOW,
                    "effective_from_quarter must be < effective_to_quarter")

    factors = select_factors(triangle["cells"])
    tail = estimate_tail(factors)

    rec = new_common_record({
        "segment_id": segment_id,
        "basis": basis,
        "valuation_quarter": valuation_quarter,
        "effective_from_quarter": eff_from,
        "effective_to_quarter": eff_to,
        "selected_factors": factors,  # Decimals
        "tail_factor": tail,
        "status": "DRAFT",
    })
    db["development_patterns"][rec["id"]] = rec
    return success_object(pattern_view(rec), status=201)


@bp.get("/actuarial/development-patterns/<pid>")
def get_pattern(pid):
    authorized(["ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    rec = require_path_resource("development_patterns", pid)
    return success_object(pattern_view(rec))


@bp.get("/actuarial/development-patterns")
def list_patterns():
    authorized(["ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    limit, offset = parse_pagination()
    segment_id = request.args.get("segment_id")
    basis = request.args.get("basis")
    status = request.args.get("status")
    items = list(db["development_patterns"].values())
    if segment_id is not None:
        items = [p for p in items if p["segment_id"] == segment_id]
    if basis is not None:
        items = [p for p in items if p["basis"] == basis]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sorted_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pattern_view(p) for p in page], total, limit, offset)


@bp.post("/actuarial/development-patterns/<pid>/select")
def select_pattern(pid):
    authorized(["ActuarialAnalyst"])
    rec = require_path_resource("development_patterns", pid)
    if rec["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only DRAFT patterns can be selected")

    # Half-open window overlap check against other SELECTED patterns of same (segment, basis).
    for other in db["development_patterns"].values():
        if other["id"] == rec["id"]:
            continue
        if other["segment_id"] != rec["segment_id"]:
            continue
        if other["basis"] != rec["basis"]:
            continue
        if other["status"] != "SELECTED":
            continue
        if _windows_overlap(
            rec["effective_from_quarter"], rec["effective_to_quarter"],
            other["effective_from_quarter"], other["effective_to_quarter"],
        ):
            raise_error(ERR_PATTERN_PERIOD_OVERLAP,
                        "pattern window overlaps an existing SELECTED pattern of the same segment/basis")

    rec["status"] = "SELECTED"
    touch(rec)
    return success_object(pattern_view(rec))


@bp.post("/actuarial/development-patterns/<pid>/withdraw")
def withdraw_pattern(pid):
    authorized(["ActuarialAnalyst"])
    rec = require_path_resource("development_patterns", pid)
    if rec["status"] not in ("DRAFT", "SELECTED"):
        raise_error(ERR_INVALID_STATE, "only DRAFT or SELECTED patterns can be withdrawn")

    if rec["status"] == "SELECTED":
        # Blocked when any APPROVED or LOCKED study of the segment has valuation_quarter
        # inside this pattern's window.
        for s in db["studies"].values():
            if s["segment_id"] != rec["segment_id"]:
                continue
            if s["status"] not in ("APPROVED", "LOCKED"):
                continue
            if _window_covers(rec, s["valuation_quarter"]):
                raise_error(ERR_PATTERN_IN_USE,
                            "pattern is in use by an APPROVED/LOCKED study in its window")

    rec["status"] = "WITHDRAWN"
    touch(rec)

    # Cascade: runs built on this pattern with valuation_quarter in window go stale,
    # then IN_REVIEW studies whose matched run turned stale revert to DRAFT.
    pattern_withdrawn_staleness(rec)

    return success_object(pattern_view(rec))
