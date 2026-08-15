"""StorageChamber registry (PRD §3.3)."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from flask import Blueprint
from response import respond, respond_list
from services import ser_chamber
from util import body, paginate, req_int, req_num, req_str, sort_created

bp = Blueprint("chambers", __name__)


def get_chamber(chamber_id):
    c = db.store["chambers"].get(chamber_id)
    if c is None:
        raise_err(ERR_NOT_FOUND, f"StorageChamber {chamber_id} not found")
    return c


@bp.route("/chambers", methods=["POST"])
@require_roles("LabDirector")
def create_chamber():
    b = body()
    chamber_code = req_str(b, "chamber_code")
    temp_c = req_num(b, "temp_c")
    capacity_units = req_int(b, "capacity_units", min_value=1)
    for c in db.store["chambers"].values():
        if c["chamber_code"] == chamber_code:
            raise_err(ERR_INVALID_REQUEST,
                      f"chamber_code {chamber_code} is already registered")
    now = clock.now()
    chamber = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "chamber_code": chamber_code,
        "temp_c": temp_c,
        "capacity_units": capacity_units,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["chambers"][chamber["id"]] = chamber
    return respond(ser_chamber(chamber), 201)


@bp.route("/chambers", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_chambers():
    items = sort_created(db.store["chambers"].values())
    page, pagination = paginate(items)
    return respond_list([ser_chamber(c) for c in page], pagination)


@bp.route("/chambers/<chamber_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_chamber(chamber_id):
    return respond(ser_chamber(get_chamber(chamber_id)), 200)
