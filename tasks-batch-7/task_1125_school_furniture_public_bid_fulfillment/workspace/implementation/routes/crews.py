"""Crew endpoints."""
from flask import Blueprint

from db import new_record, public, store
from middleware import ALL_ROLES, authenticate, require_roles
from response import success
from validation import body, get_or_404, req_str

bp = Blueprint("crews", __name__)


@bp.route("/v1/crews", methods=["POST"])
def create_crew():
    caller = authenticate()
    require_roles(caller, ["ContractorAdmin"])
    data = body()
    name = req_str(data, "name")
    rec = new_record({
        "name": name,
        "booked_days": 0,
    })
    store.crews[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.route("/v1/crews/<rid>", methods=["GET"])
def get_crew(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.crews, rid, "crew")
    return success(public(rec), code=200)
