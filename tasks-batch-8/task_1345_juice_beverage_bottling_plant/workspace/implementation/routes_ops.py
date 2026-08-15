"""OpsRun housekeeping epoch endpoint."""
from flask import Blueprint

from domain import ser_ops_run
from services import run_ops_epoch
from util import ok, require_roles

bp = Blueprint("ops", __name__)


@bp.post("/v1/ops-runs")
def create_ops_run():
    require_roles("PlantManager")
    record = run_ops_epoch()
    return ok(ser_ops_run(record), 201)
