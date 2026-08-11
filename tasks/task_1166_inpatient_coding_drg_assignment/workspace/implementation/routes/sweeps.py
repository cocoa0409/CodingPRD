"""DnfbSweep ops-run checkpoint endpoints (PRD §3.7)."""
from flask import Blueprint

from db import now, store
from errors import ERR_INVALID_REQUEST, fail
from middleware import ALL_ROLES, require_roles
from response import ok_obj
from services.calc import DNFB_DEFAULT_THRESHOLD_DAYS, run_sweep
from services.core import ser_sweep
from validators import body, has, opt_dt, opt_int

bp = Blueprint("sweeps", __name__)


@bp.route("/dnfb-sweeps", methods=["POST"])
def create_sweep():
    require_roles("CodingManager")
    b = body()
    threshold = opt_int(b, "threshold_days")
    if threshold is None:
        threshold = DNFB_DEFAULT_THRESHOLD_DAYS
    as_of = opt_dt(b, "as_of")
    if as_of is None:
        as_of = now()
    sweep = run_sweep(threshold, as_of)
    return ok_obj(ser_sweep(sweep), 201)


@bp.route("/dnfb-sweeps/<id>", methods=["GET"])
def get_sweep(id):
    require_roles(*ALL_ROLES)
    sweep = store.sweeps.get(id)
    if sweep is None:
        fail(404, ERR_INVALID_REQUEST, f"DnfbSweep {id} does not exist")
    return ok_obj(ser_sweep(sweep), 200)
