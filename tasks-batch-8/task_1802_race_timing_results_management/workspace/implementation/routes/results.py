from flask import Blueprint, request

import db
from middleware import endpoint, ALL_ROLES
from response import ok
from serializers import ser_result
from validators import get_or_404, list_page

bp = Blueprint("results", __name__)


@bp.get("/race-timing/results/<result_id>")
@endpoint(*ALL_ROLES)
def get_result(result_id):
    return ok(ser_result(get_or_404(db.results, result_id)))


@bp.get("/race-timing/results")
@endpoint(*ALL_ROLES)
def list_results():
    items = list(db.results.values())
    for param in ("race_id", "registration_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    return list_page(items, ser_result)
