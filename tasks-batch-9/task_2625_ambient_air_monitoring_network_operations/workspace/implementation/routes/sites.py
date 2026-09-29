"""Monitoring sites: proposal, siting approval, commencement and reinstatement."""
from flask import Blueprint

import clock
import constants as C
import response
import validate as V
from auth import ALL_ROLES, require
from db import new_record, sorted_by_created, store, touch
from errors import ApiError
from routes.common import (ensure_from_state, ensure_not_terminal, get_network,
                           get_site, network_of)
from services import cascade
from services import compute as K
from services import serialize as S

bp = Blueprint("sites", __name__)


@bp.post("/monitoring-sites")
@require("NetworkAdmin")
def propose_site():
    data = V.body()
    network_id = V.req_id(data, "network_id")
    site_code = V.req_string(data, "site_code", min_len=1, max_len=20)
    site_type = V.req_enum(data, "site_type", C.SITE_TYPES)
    latitude = V.req_number(data, "latitude", lo=-90, hi=90)
    longitude = V.req_number(data, "longitude", lo=-180, hi=180)
    population_served = V.req_int(data, "population_served", lo=0)
    probe_height_m = V.req_number(data, "probe_height_m", exclusive_lo=0)
    distance_to_roadway_m = V.req_number(data, "distance_to_roadway_m", lo=0)
    distance_to_obstruction_m = V.req_number(data, "distance_to_obstruction_m", lo=0)
    obstruction_height_m = V.req_number(data, "obstruction_height_m", lo=0)
    distance_to_source_m = V.opt_number(data, "distance_to_source_m", default=0.0, lo=0)
    network = get_network(network_id)
    # site_code is unique within the network across sites in ANY status
    for existing in store.sites.values():
        if existing["network_id"] == network_id and existing["site_code"] == site_code:
            raise ApiError("ERR_DUPLICATE_SITE_CODE",
                           "Site code '%s' is already used in this network." % site_code)
    rec = new_record()
    rec.update({
        "network_id": network_id,
        "replaces_site_id": None,
        "site_code": site_code,
        "site_type": site_type,
        "latitude": latitude,
        "longitude": longitude,
        "population_served": population_served,
        "probe_height_m": probe_height_m,
        "distance_to_roadway_m": distance_to_roadway_m,
        "distance_to_obstruction_m": distance_to_obstruction_m,
        "obstruction_height_m": obstruction_height_m,
        "distance_to_source_m": distance_to_source_m,
        "status": "PROPOSED",
        "siting_waiver_granted": False,
        "operations_start_at": None,
        "suspended_at": None,
        "operating_monitor_count": 0,
        "current_attainment_status": "UNDETERMINED",
    })
    # Siting criteria are evaluated the instant the site is proposed.
    K.refresh_siting(rec)
    store.sites[rec["id"]] = rec
    network.update(K.network_census(network_id))
    return response.object_response(S.site(rec), 201)


@bp.post("/monitoring-sites/<site_id>/siting-approval")
@require("EpaRegionalReviewer")
def approve_siting(site_id):
    data = V.body()
    waiver_granted = V.opt_bool(data, "waiver_granted", default=False)
    V.opt_string(data, "approval_note")
    site = get_site(site_id)
    ensure_not_terminal(site["status"], C.SITE_TERMINAL_STATUSES, "monitoring site")
    ensure_from_state(site["status"], ("PROPOSED",), "monitoring site")
    # The criteria are re-evaluated from the site's current geometry.
    K.refresh_siting(site)
    if site["siting_waiver_required"] and not waiver_granted:
        raise ApiError("ERR_SITING_CRITERIA_NOT_MET",
                       "The site fails a siting criterion and no waiver was granted.")
    site["status"] = "SITING_APPROVED"
    site["siting_waiver_granted"] = bool(waiver_granted)
    touch(site)
    network = network_of(site)
    if network is not None:
        network.update(K.network_census(network["id"]))
        touch(network)
    return response.object_response(S.site(site))


@bp.post("/monitoring-sites/<site_id>/commence-operations")
@require("ProgramManager")
def commence_operations(site_id):
    data = V.body()
    V.opt_string(data, "operations_note")
    site = get_site(site_id)
    ensure_not_terminal(site["status"], C.SITE_TERMINAL_STATUSES, "monitoring site")
    ensure_from_state(site["status"], ("SITING_APPROVED",), "monitoring site")
    site["status"] = "OPERATING"
    site["operations_start_at"] = clock.now()
    touch(site)
    network = network_of(site)
    if network is not None:
        network.update(K.network_census(network["id"]))
        touch(network)
    return response.object_response(S.site(site))


@bp.post("/monitoring-sites/<site_id>/reinstate")
@require("ProgramManager")
def reinstate_site(site_id):
    data = V.body()
    V.opt_string(data, "reinstatement_note")
    site = get_site(site_id)
    ensure_not_terminal(site["status"], C.SITE_TERMINAL_STATUSES, "monitoring site")
    ensure_from_state(site["status"], ("SUSPENDED",), "monitoring site")
    cascade.reinstatement(site, network_of(site))
    return response.object_response(S.site(site))


@bp.get("/monitoring-sites/<site_id>")
@require(*ALL_ROLES)
def read_site(site_id):
    return response.object_response(S.site(get_site(site_id)))


@bp.get("/monitoring-sites")
@require(*ALL_ROLES)
def list_sites():
    limit, offset = V.pagination()
    network_id = V.q_string("network_id")
    replaces_site_id = V.q_string("replaces_site_id")
    site_type = V.q_enum("site_type", C.SITE_TYPES)
    status = V.q_enum("status", C.SITE_STATUSES)
    siting_waiver_required = V.q_bool("siting_waiver_required")
    rows = list(store.sites.values())
    for row in rows:
        K.refresh_siting(row)
    if network_id is not None:
        rows = [s for s in rows if s["network_id"] == network_id]
    if replaces_site_id is not None:
        rows = [s for s in rows if s["replaces_site_id"] == replaces_site_id]
    if site_type is not None:
        rows = [s for s in rows if s["site_type"] == site_type]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    if siting_waiver_required is not None:
        rows = [s for s in rows if s["siting_waiver_required"] == siting_waiver_required]
    rows = sorted_by_created(rows)
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.site(s) for s in page], pagination=meta)
