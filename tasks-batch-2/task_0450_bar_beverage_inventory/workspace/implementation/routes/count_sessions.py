"""Count session endpoints (PRD §3.7, §2.6 OCC)."""
from flask import Blueprint

import serialize
from db import db, stamp_create, touch
from errors import (ApiError, invalid_state, stale_version, ERR_DUPLICATE_COUNT_LINE,
                    ERR_WEIGHT_BELOW_TARE, ERR_COUNT_WINDOW_OVERLAP)
from middleware import require_roles
from money import D
from response import object_response, array_response
from routes.lookup import get_count_session, get_product
from services.finalize import compute_finalize
from validate import (get_json_body, require, as_str, as_enum, as_number, as_int,
                      parse_pagination, paginate)
from timeutil import parse_iso

bp = Blueprint("count_sessions", __name__)

COUNT_METHODS = {"UNITS", "WEIGHT"}


@bp.route("/count-sessions", methods=["POST"])
@require_roles("InventoryManager")
def create_count_session():
    body = get_json_body()
    label = as_str(require(body, "label"), "label")
    counted_at_raw = require(body, "counted_at")
    counted_at_dt = parse_iso(counted_at_raw, "counted_at")
    record = {
        "label": label,
        "counted_at": counted_at_raw,
        "_counted_at_dt": counted_at_dt,
        "status": "OPEN",
        "total_variance_cost_cents": 0,
    }
    stamp_create(record)
    db.count_sessions[record["id"]] = record
    return object_response(serialize.count_session(record), 201)


@bp.route("/count-sessions/<sid>", methods=["GET"])
@require_roles("InventoryManager")
def read_count_session(sid):
    s = get_count_session(sid)
    return object_response(serialize.count_session(s))


@bp.route("/count-sessions/<sid>/count-lines", methods=["POST"])
@require_roles("InventoryManager")
def add_count_line(sid):
    session = get_count_session(sid)
    body = get_json_body()
    product_id = require(body, "product_id")
    count_method = as_enum(require(body, "count_method"), "count_method", COUNT_METHODS)
    expected_version = as_int(require(body, "expected_count_session_version"),
                              "expected_count_session_version", ge=0)
    counted_units = as_number(body.get("counted_units", 0), "counted_units", ge=0) \
        if body.get("counted_units") is not None else 0
    gross_weight_g = as_number(body.get("gross_weight_g", 0), "gross_weight_g", ge=0) \
        if body.get("gross_weight_g") is not None else 0

    # body FK existence (404) — path resolved already
    product = get_product(product_id)

    # state (409): session must be OPEN
    if session["status"] != "OPEN":
        raise invalid_state("Count lines may only be added to an OPEN session.")

    # OCC (412)
    if expected_version != session["version"]:
        raise stale_version()

    # duplicate count line per product (409)
    for cl in db.count_lines.values():
        if cl["count_session_id"] == sid and cl["product_id"] == product_id:
            raise ApiError(ERR_DUPLICATE_COUNT_LINE, 409,
                           "This product already has a count line in the session.")

    # WEIGHT tare check (422) — enforced at add and at finalize
    if count_method == "WEIGHT":
        if not (D(gross_weight_g) > D(product["empty_container_weight_g"])):
            raise ApiError(ERR_WEIGHT_BELOW_TARE, 422,
                           "gross_weight_g must exceed the product's empty_container_weight_g.")

    record = {
        "count_session_id": sid,
        "product_id": product_id,
        "count_method": count_method,
        "counted_units": counted_units,
        "gross_weight_g": gross_weight_g,
        "closing_units": 0,
        "theoretical_units": 0,
        "variance_units": 0,
        "variance_cost_cents": 0,
    }
    stamp_create(record)
    db.count_lines[record["id"]] = record
    # increment CountSession.version by 1
    touch(session)
    return object_response(serialize.count_line(record), 201)


@bp.route("/count-sessions/<sid>/count-lines", methods=["GET"])
@require_roles("InventoryManager")
def list_count_lines(sid):
    get_count_session(sid)
    limit, offset = parse_pagination()
    items = [cl for cl in db.count_lines.values() if cl["count_session_id"] == sid]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.count_line(cl) for cl in page], limit, offset, total)


def _windows_conflict(session):
    """counted_at must be strictly later than the counted_at of the most recent
    FINALIZED session sharing any product (PRD §3.7). Returns True on conflict."""
    this_dt = session["_counted_at_dt"]
    my_products = {cl["product_id"] for cl in db.count_lines.values()
                   if cl["count_session_id"] == session["id"]}
    for cs in db.count_sessions.values():
        if cs["id"] == session["id"]:
            continue
        if cs["status"] != "FINALIZED":
            continue
        other_products = {cl["product_id"] for cl in db.count_lines.values()
                          if cl["count_session_id"] == cs["id"]}
        if my_products & other_products:
            if not (this_dt > cs["_counted_at_dt"]):
                return True
    return False


@bp.route("/count-sessions/<sid>/finalize", methods=["POST"])
@require_roles("InventoryManager")
def finalize_count_session(sid):
    session = get_count_session(sid)
    body = get_json_body()
    expected_version = as_int(require(body, "expected_count_session_version"),
                              "expected_count_session_version", ge=0)

    # state (409): must be OPEN
    if session["status"] != "OPEN":
        raise invalid_state("Only an OPEN count session can be finalized.")

    # OCC (412)
    if expected_version != session["version"]:
        raise stale_version()

    lines = [cl for cl in db.count_lines.values() if cl["count_session_id"] == sid]
    # >= 1 line
    if len(lines) < 1:
        raise invalid_state("A count session must have at least one line to finalize.")
    # every product distinct (enforced on add, but re-check)
    seen = set()
    for cl in lines:
        if cl["product_id"] in seen:
            raise invalid_state("Count lines must each measure a distinct product.")
        seen.add(cl["product_id"])

    # temporal: counted_at strictly after prior finalized sharing a product (422)
    if _windows_conflict(session):
        raise ApiError(ERR_COUNT_WINDOW_OVERLAP, 422,
                       "counted_at must be strictly after the most recent FINALIZED session sharing a product.")

    # compute everything (may raise ERR_WEIGHT_BELOW_TARE for WEIGHT lines)
    compute_finalize(session)

    session["status"] = "FINALIZED"
    touch(session)
    return object_response(serialize.count_session(session))


@bp.route("/count-sessions/<sid>/void", methods=["POST"])
@require_roles("InventoryManager")
def void_count_session(sid):
    session = get_count_session(sid)
    body = get_json_body()
    expected_version = as_int(require(body, "expected_count_session_version"),
                              "expected_count_session_version", ge=0)
    # state (409): must be OPEN
    if session["status"] != "OPEN":
        raise invalid_state("Only an OPEN count session can be voided.")
    # OCC (412): same guard
    if expected_version != session["version"]:
        raise stale_version()
    session["status"] = "VOID"
    touch(session)
    return object_response(serialize.count_session(session))
