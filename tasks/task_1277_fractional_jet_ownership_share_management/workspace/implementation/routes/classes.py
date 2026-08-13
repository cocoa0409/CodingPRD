"""AircraftClass endpoints."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services.core import class_view, new_common
from util import as_int, as_str, body, paginate_sorted, required

bp = Blueprint("classes", __name__)


def _get_class(cid):
    c = db.aircraft_classes.get(cid)
    if not c:
        raise ApiError("ERR_NOT_FOUND", 404, "Aircraft class not found")
    return c


@bp.route("/aircraft-classes", methods=["POST"])
def create_class():
    require_roles("ProgramAdmin")
    data = body()
    program_id = as_str(required(data, "program_id"), "program_id")
    program = db.programs.get(program_id)
    if not program:
        raise ApiError("ERR_NOT_FOUND", 404, "Program not found")
    class_code = as_str(required(data, "class_code"), "class_code")
    hourly_rate = as_int(required(data, "hourly_rate_cents"), "hourly_rate_cents")
    mult_bp = as_int(
        required(data, "interchange_upgrade_multiplier_bp"),
        "interchange_upgrade_multiplier_bp",
    )
    monthly_fee = as_int(
        required(data, "monthly_fee_base_cents"), "monthly_fee_base_cents"
    )
    seats = as_int(required(data, "seats"), "seats")
    if hourly_rate <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "hourly_rate_cents must be > 0")
    if mult_bp < 10000:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "interchange_upgrade_multiplier_bp must be >= 10000",
        )
    if monthly_fee <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "monthly_fee_base_cents must be > 0")
    if seats <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "seats must be > 0")
    for c in db.aircraft_classes.values():
        if c["program_id"] == program_id and c["class_code"] == class_code:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                "class_code must be unique within program",
            )

    rec = new_common()
    rec.update({
        "class_code": class_code,
        "program_id": program_id,
        "hourly_rate_cents": hourly_rate,
        "interchange_upgrade_multiplier_bp": mult_bp,
        "monthly_fee_base_cents": monthly_fee,
        "seats": seats,
    })
    db.aircraft_classes[rec["id"]] = rec
    return ok(class_view(rec), status=201)


@bp.route("/aircraft-classes/<cid>", methods=["GET"])
def get_class(cid):
    require_roles(*ALL_ROLES)
    return ok(class_view(_get_class(cid)))


@bp.route("/aircraft-classes", methods=["GET"])
def list_classes():
    require_roles(*ALL_ROLES)
    program_id = request.args.get("program_id")
    items = list(db.aircraft_classes.values())
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([class_view(c) for c in page], total, limit, offset)
