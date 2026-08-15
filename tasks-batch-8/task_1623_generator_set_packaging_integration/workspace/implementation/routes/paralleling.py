"""ParallelingScheme endpoints."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp

bp = Blueprint("paralleling", __name__)

VALID_SYNC_MODES = {"ISOLATED", "PARALLEL_WITH_UTILITY", "MULTI_UNIT"}


@bp.route("/genset-packaging/paralleling-schemes", methods=["POST"])
def create_scheme():
    mw.require_roles("ApplicationEngineer")
    body = mw.get_json_body()

    order_id = mw.require_string(body, "order_id")
    sync_mode = mw.require_enum(body, "sync_mode", VALID_SYNC_MODES)
    max_units = mw.require_int(body, "max_units", minimum=1, maximum=8)

    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Package order not found")

    record = {
        "order_id": order_id,
        "sync_mode": sync_mode,
        "max_units": max_units,
        "positions": [],
        "control_program_version": None,
        "status": "DESIGN",
    }
    db.stamp_new(record)
    db.paralleling_schemes[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/paralleling-schemes/<schemeId>", methods=["GET"])
def get_scheme(schemeId):
    mw.authenticate()
    record = db.paralleling_schemes.get(schemeId)
    if record is None:
        raise errors.not_found("Paralleling scheme not found")
    return resp.success_object(record)


@bp.route("/genset-packaging/paralleling-schemes", methods=["GET"])
def list_schemes():
    mw.authenticate()
    limit, offset = mw.parse_pagination()

    items = list(db.paralleling_schemes.values())
    val = mw.request.args.get("order_id")
    if val:
        items = [s for s in items if s["order_id"] == val]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.success_list(page, limit, offset, total)


@bp.route("/genset-packaging/paralleling-schemes/<schemeId>/positions", methods=["POST"])
def add_position(schemeId):
    mw.require_roles("ApplicationEngineer")
    body = mw.get_json_body()

    scheme = db.paralleling_schemes.get(schemeId)
    if scheme is None:
        raise errors.not_found("Paralleling scheme not found")

    if scheme["status"] != "DESIGN":
        raise errors.ApiError(
            errors.ERR_SCHEME_STATE_INVALID, 409,
            "Positions can only be added while scheme is in DESIGN",
        )

    kw_rating = mw.require_number(body, "kw_rating", minimum=0, exclusive_minimum=True)

    if len(scheme["positions"]) >= scheme["max_units"]:
        raise errors.ApiError(
            errors.ERR_PARALLEL_CAPACITY_EXCEEDED, 409,
            "Adding a position would exceed max_units",
        )

    position_no = len(scheme["positions"]) + 1
    scheme["positions"].append({
        "position_no": position_no,
        "kw_rating": kw_rating,
    })
    db.touch(scheme)
    return resp.success_created(scheme)


@bp.route("/genset-packaging/paralleling-schemes/<schemeId>/program", methods=["POST"])
def program_scheme(schemeId):
    mw.require_roles("ApplicationEngineer")
    body = mw.get_json_body()

    scheme = db.paralleling_schemes.get(schemeId)
    if scheme is None:
        raise errors.not_found("Paralleling scheme not found")

    if scheme["status"] != "DESIGN":
        raise errors.ApiError(
            errors.ERR_SCHEME_STATE_INVALID, 409,
            "Scheme must be DESIGN to program",
        )

    program_version = mw.require_string(body, "program_version")

    pos_count = len(scheme["positions"])
    if pos_count == 0:
        raise errors.invalid_request("Scheme must have at least one position to program")
    if pos_count > scheme["max_units"]:
        raise errors.ApiError(
            errors.ERR_PARALLEL_CAPACITY_EXCEEDED, 409,
            "Position count exceeds max_units",
        )

    scheme["control_program_version"] = program_version
    scheme["status"] = "PROGRAMMED"
    db.touch(scheme)
    return resp.success_object(scheme)


@bp.route("/genset-packaging/paralleling-schemes/<schemeId>/rework", methods=["POST"])
def rework_scheme(schemeId):
    mw.require_roles("ApplicationEngineer")

    scheme = db.paralleling_schemes.get(schemeId)
    if scheme is None:
        raise errors.not_found("Paralleling scheme not found")

    if scheme["status"] != "PROGRAMMED":
        raise errors.ApiError(
            errors.ERR_SCHEME_STATE_INVALID, 409,
            "Scheme must be PROGRAMMED to rework",
        )

    scheme["control_program_version"] = None
    scheme["status"] = "DESIGN"
    db.touch(scheme)
    return resp.success_object(scheme)


@bp.route("/genset-packaging/paralleling-schemes/<schemeId>/verify", methods=["POST"])
def verify_scheme(schemeId):
    mw.require_roles("ApplicationEngineer")

    scheme = db.paralleling_schemes.get(schemeId)
    if scheme is None:
        raise errors.not_found("Paralleling scheme not found")

    if scheme["status"] != "PROGRAMMED":
        raise errors.ApiError(
            errors.ERR_SCHEME_STATE_INVALID, 409,
            "Scheme must be PROGRAMMED to verify",
        )

    order = db.orders.get(scheme["order_id"])
    if order is None:
        raise errors.not_found("Package order not found")

    if order["build_status"] not in ("TESTING", "READY_TO_SHIP", "DELIVERED", "COMMISSIONED"):
        raise errors.ApiError(
            errors.ERR_INVALID_BUILD_STATE, 409,
            "Order build_status must be TESTING, READY_TO_SHIP, DELIVERED, or COMMISSIONED to verify",
        )

    scheme["status"] = "VERIFIED"
    db.touch(scheme)
    return resp.success_object(scheme)
