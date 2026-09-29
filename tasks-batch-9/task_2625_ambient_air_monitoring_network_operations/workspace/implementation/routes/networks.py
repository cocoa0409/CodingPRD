"""Monitoring networks and their child listings."""
from flask import Blueprint

import constants as C
import response
import validate as V
from auth import ALL_ROLES, require
from db import new_record, sorted_by_created, store
from routes.common import get_network
from services import compute as K
from services import serialize as S

bp = Blueprint("networks", __name__)


@bp.post("/monitoring-networks")
@require("NetworkAdmin")
def create_network():
    data = V.body()
    name = V.req_string(data, "name", min_len=1)
    agency_code = V.req_string(data, "agency_code", min_len=1)
    metropolitan_population = V.req_int(data, "metropolitan_population", lo=0)
    for existing in store.networks.values():
        if existing["agency_code"] == agency_code:
            V.bad("A network with agency_code '%s' already exists." % agency_code)
    rec = new_record()
    rec.update({
        "name": name,
        "agency_code": agency_code,
        "metropolitan_population": metropolitan_population,
        "network_status": "ACTIVE",
        "current_assessment_year": None,
    })
    # Every census counter and the delinquency counter initialise to 0.
    rec.update(K.network_census(rec["id"]))
    store.networks[rec["id"]] = rec
    return response.object_response(S.network(rec), 201)


@bp.get("/monitoring-networks/<network_id>")
@require(*ALL_ROLES)
def read_network(network_id):
    return response.object_response(S.network(get_network(network_id)))


@bp.get("/monitoring-networks/<network_id>/assessments")
@require(*ALL_ROLES)
def list_network_assessments(network_id):
    limit, offset = V.pagination()
    status = V.q_enum("status", C.ASSESSMENT_STATUSES)
    cycle_year = V.q_int("cycle_year")
    get_network(network_id)
    rows = [a for a in store.assessments.values() if a["network_id"] == network_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    if cycle_year is not None:
        rows = [a for a in rows if a["cycle_year"] == cycle_year]
    rows = sorted_by_created(rows)
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.assessment(a) for a in page], pagination=meta)


@bp.get("/monitoring-networks/<network_id>/certification-packages")
@require(*ALL_ROLES)
def list_network_packages(network_id):
    limit, offset = V.pagination()
    year = V.q_int("year")
    status = V.q_enum("status", C.PACKAGE_STATUSES)
    get_network(network_id)
    rows = [p for p in store.packages.values() if p["network_id"] == network_id]
    if year is not None:
        rows = [p for p in rows if p["year"] == year]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows = sorted_by_created(rows)
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.package(p) for p in page], pagination=meta)
