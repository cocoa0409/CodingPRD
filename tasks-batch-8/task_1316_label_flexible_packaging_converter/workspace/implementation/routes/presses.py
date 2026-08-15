"""Press endpoints (PRD 3.1)."""
from flask import Blueprint

from db import DB, new_id, now_iso
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import get_press, sorted_created
from util import as_int, as_str, body, pagination_args, reject_unknown, required

bp = Blueprint("presses", __name__)

_PRESS_FIELDS = {
    "press_code",
    "station_count",
    "setup_waste_ft",
    "run_waste_pct_numerator",
}


@bp.post("/label-jobs/presses")
def create_press():
    auth(["Estimator"])
    data = body()
    reject_unknown(data, _PRESS_FIELDS)
    press_code = as_str(required(data, "press_code"), "press_code")
    station_count = as_int(required(data, "station_count"), "station_count")
    setup_waste_ft = as_int(required(data, "setup_waste_ft"), "setup_waste_ft")
    run_waste_pct_numerator = as_int(
        required(data, "run_waste_pct_numerator"), "run_waste_pct_numerator"
    )
    ts = now_iso()
    press = {
        "id": new_id(),
        "press_code": press_code,
        "station_count": station_count,
        "setup_waste_ft": setup_waste_ft,
        "run_waste_pct_numerator": run_waste_pct_numerator,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["presses"][press["id"]] = press
    return ok(press, 201)


@bp.get("/label-jobs/presses")
def list_presses():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    items = sorted_created(DB["presses"].values())
    return ok_list(items[offset : offset + limit], len(items), limit, offset)


@bp.get("/label-jobs/presses/<press_id>")
def get_one_press(press_id):
    auth(ALL_ROLES)
    return ok(get_press(press_id))
