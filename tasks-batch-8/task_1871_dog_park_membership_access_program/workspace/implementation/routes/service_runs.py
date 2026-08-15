"""Nightly service-run epoch endpoint."""
from flask import Blueprint

from middleware import require_auth
from response import ok
from services import domain

bp = Blueprint("service_runs", __name__)


@bp.route("/dog-park/service-runs/nightly", methods=["POST"])
def run_nightly():
    require_auth(["ParkAdmin"])
    tallies = domain.nightly_run()
    return ok(tallies, 201)
