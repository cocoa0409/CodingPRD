"""ReserveRun endpoints."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_NO_SELECTED_PATTERN,
    ERR_NOT_FOUND,
    ERR_RUN_ALREADY_EXISTS,
    ERR_TRIANGLE_STALE,
)
from middleware import authorized
from response import success_object, success_list
from routes.helpers import new_common_record, sorted_by_creation
from services.calculations import (
    bornhuetter_ferguson_ultimate,
    chain_ladder_ultimate,
    reserve_range,
)
from services.serializers import run_view
from util import dec
from validate import (
    get_body,
    parse_pagination,
    reject_server_managed,
    req_enum,
    req_int,
    req_number,
    req_quarter,
    req_str,
    require_body_fk,
    require_path_resource,
)

bp = Blueprint("reserve_runs", __name__)

RUN_COMPUTED = [
    "development_pattern_id", "ultimate_cents", "ibnr_cents",
    "range_low_cents", "range_high_cents", "ultimate_by_accident_quarter",
    "is_stale",
]


@bp.post("/actuarial/reserve-runs")
def create_run():
    authorized(["ActuarialAnalyst"])
    body = get_body()
    reject_server_managed(body, RUN_COMPUTED)
    segment_id = req_str(body, "segment_id")
    valuation_quarter = req_quarter(body, "valuation_quarter")
    method = req_enum(body, "method", ["CHAIN_LADDER", "BORNHUETTER_FERGUSON"])
    basis = req_enum(body, "basis", ["PAID", "INCURRED"])

    earned_exposure_cents = None
    a_priori_loss_ratio = None
    if method == "BORNHUETTER_FERGUSON":
        earned_exposure_cents = req_int(body, "earned_exposure_cents")
        a_priori_loss_ratio = req_number(body, "a_priori_loss_ratio")
    else:
        # Ignored for CHAIN_LADDER; capture but don't require.
        if "earned_exposure_cents" in body and body.get("earned_exposure_cents") is not None:
            v = body.get("earned_exposure_cents")
            if isinstance(v, bool) or not isinstance(v, int):
                raise_error(ERR_INVALID_REQUEST, "earned_exposure_cents must be an integer")
            earned_exposure_cents = v
        if "a_priori_loss_ratio" in body and body.get("a_priori_loss_ratio") is not None:
            v = body.get("a_priori_loss_ratio")
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise_error(ERR_INVALID_REQUEST, "a_priori_loss_ratio must be a number")
            a_priori_loss_ratio = v

    require_body_fk("segments", segment_id, "segment_id")

    # Covering SELECTED pattern of (segment, basis) whose window covers valuation_quarter.
    pattern = None
    for p in db["development_patterns"].values():
        if p["segment_id"] != segment_id:
            continue
        if p["basis"] != basis:
            continue
        if p["status"] != "SELECTED":
            continue
        if p["effective_from_quarter"] <= valuation_quarter < p["effective_to_quarter"]:
            pattern = p
            break
    if pattern is None:
        raise_error(ERR_NO_SELECTED_PATTERN,
                    "no SELECTED pattern covers (segment, basis, valuation_quarter)")

    # Triangle for (segment, basis, valuation_quarter) must exist and be non-stale.
    triangle = None
    for t in db["triangles"].values():
        if (t["segment_id"] == segment_id and t["basis"] == basis
                and t["valuation_quarter"] == valuation_quarter):
            triangle = t
            break
    if triangle is None:
        raise_error(ERR_NOT_FOUND, "triangle not found for (segment, basis, valuation_quarter)")
    if triangle["is_stale"]:
        raise_error(ERR_TRIANGLE_STALE, "triangle is stale; re-aggregate first")

    # Uniqueness: at most one non-stale run per (segment, valuation_quarter, method, basis).
    for r in db["reserve_runs"].values():
        if (r["segment_id"] == segment_id
                and r["valuation_quarter"] == valuation_quarter
                and r["method"] == method
                and r["basis"] == basis
                and not r["is_stale"]):
            raise_error(ERR_RUN_ALREADY_EXISTS,
                        "a non-stale run already exists for (segment, valuation_quarter, method, basis)")

    factors = [dec(f) for f in pattern["selected_factors"]]
    tail = dec(pattern["tail_factor"])

    if method == "CHAIN_LADDER":
        ultimate, ibnr, per_aq = chain_ladder_ultimate(
            triangle["cells"], triangle["large_loss_cells"],
            valuation_quarter, factors, tail,
        )
    else:
        ultimate, ibnr, per_aq = bornhuetter_ferguson_ultimate(
            triangle["cells"], triangle["large_loss_cells"],
            valuation_quarter, factors, tail,
            earned_exposure_cents, a_priori_loss_ratio,
        )

    range_low, range_high = reserve_range(ibnr)

    rec = new_common_record({
        "segment_id": segment_id,
        "development_pattern_id": pattern["id"],
        "valuation_quarter": valuation_quarter,
        "method": method,
        "basis": basis,
        "earned_exposure_cents": earned_exposure_cents,
        "a_priori_loss_ratio": a_priori_loss_ratio,
        "ultimate_cents": ultimate,
        "ibnr_cents": ibnr,
        "range_low_cents": range_low,
        "range_high_cents": range_high,
        "ultimate_by_accident_quarter": per_aq,
        "is_stale": False,
    })
    db["reserve_runs"][rec["id"]] = rec
    return success_object(run_view(rec), status=201)


@bp.get("/actuarial/reserve-runs/<rid>")
def get_run(rid):
    authorized(["ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    rec = require_path_resource("reserve_runs", rid)
    return success_object(run_view(rec))


@bp.get("/actuarial/reserve-runs")
def list_runs():
    authorized(["ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    limit, offset = parse_pagination()
    segment_id = request.args.get("segment_id")
    pattern_id = request.args.get("development_pattern_id")
    vq = request.args.get("valuation_quarter")
    method = request.args.get("method")
    basis = request.args.get("basis")
    items = list(db["reserve_runs"].values())
    if segment_id is not None:
        items = [r for r in items if r["segment_id"] == segment_id]
    if pattern_id is not None:
        items = [r for r in items if r.get("development_pattern_id") == pattern_id]
    if vq is not None:
        items = [r for r in items if r["valuation_quarter"] == vq]
    if method is not None:
        items = [r for r in items if r["method"] == method]
    if basis is not None:
        items = [r for r in items if r["basis"] == basis]
    items = sorted_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([run_view(r) for r in page], total, limit, offset)
