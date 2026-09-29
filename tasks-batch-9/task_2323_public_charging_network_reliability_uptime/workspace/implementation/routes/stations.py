"""Stations: creation, lifecycle moves, the commissioning gate ladder and the
teardown cascade (PRD §3.2, §3.3)."""
from flask import Blueprint

import calc
import cascades
import clock
import db
import lookup
import serialize
import validation
from errors import err
from middleware import endpoint, require_role_for_leg
from response import array_response, object_response, paginate

bp = Blueprint("stations", __name__)

POWER_CLASSES = ("L2_19", "DCFC_150", "DCFC_350")
TARGET_STATUSES = ("DRAFT", "COMMISSIONING", "OPERATIONAL", "SUSPENDED", "DECOMMISSIONED")


@bp.post("/stations")
@endpoint("NetworkOperator")
def create_station():
    body = validation.json_body()
    host_site_id = validation.as_string(body, "host_site_id")
    site = lookup.host_site(host_site_id)

    station_code = validation.as_string(body, "station_code")
    power_class = validation.as_enum(body, "power_class", POWER_CLASSES)
    declared_port_count = validation.as_int(body, "declared_port_count", minimum=1)
    corridor_designated = validation.as_bool(body, "corridor_designated",
                                             required=False, default=False)

    for existing in db.stations.values():
        if existing["station_code"] == station_code:
            raise err("ERR_STATION_CODE_DUPLICATE", "station_code is already in use.")

    row = db.base_record()
    row.update({
        "host_site_id": site["id"],
        "station_code": station_code,
        "power_class": power_class,
        "declared_port_count": declared_port_count,
        "corridor_designated": corridor_designated,
        "status": "DRAFT",
        "suspension_source": "NONE",
        "commissioned_at": None,
    })
    db.stations[row["id"]] = row
    db.mark_fresh(row)
    return object_response(serialize.station(row), 201)


@bp.get("/stations/<station_id>")
@endpoint()
def get_station(station_id):
    return object_response(serialize.station(lookup.station(station_id)))


@bp.get("/stations/<station_id>/charging-ports")
@endpoint()
def list_ports_of_station(station_id):
    station = lookup.station(station_id)
    limit, offset = validation.pagination()
    rows = db.ports_of_station(station["id"])
    rows = validation.apply_filters(
        rows, validation.filters("service_state", "maintenance_state"))
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.charging_port(r) for r in page], limit, offset, total)


@bp.get("/stations/<station_id>/uptime-reports")
@endpoint()
def list_reports_of_station(station_id):
    station = lookup.station(station_id)
    limit, offset = validation.pagination()
    rows = db.reports_of_station(station["id"])
    rows = validation.apply_filters(rows, validation.filters("state"))
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.uptime_report(r) for r in page], limit, offset, total)


@bp.post("/stations/<station_id>/status-transitions")
@endpoint("NetworkOperator", "ComplianceAuditor")
def station_status_transition(station_id):
    station = lookup.station(station_id)
    body = validation.json_body()
    target = validation.as_enum(body, "target_status", TARGET_STATUSES)

    # Leg-restricted roles: the DRAFT revert is the auditor's audit-failure leg;
    # every other lifecycle move belongs to the operator.
    require_role_for_leg("ComplianceAuditor" if target == "DRAFT" else "NetworkOperator")

    if station["status"] == "DECOMMISSIONED":
        raise err("ERR_ALREADY_TERMINAL", "The station is already DECOMMISSIONED.")

    if target == "COMMISSIONING":
        if station["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Only a DRAFT station may enter COMMISSIONING.")
        if calc.commissioned_port_count(station["id"]) < 1:
            raise err("ERR_INVALID_STATE",
                      "A station with no non-retired dispenser may not enter COMMISSIONING.")
        station["status"] = "COMMISSIONING"
    elif target == "DRAFT":
        if station["status"] != "COMMISSIONING":
            raise err("ERR_INVALID_STATE",
                      "Only a COMMISSIONING station may be reverted to DRAFT.")
        station["status"] = "DRAFT"
    elif target == "SUSPENDED":
        if station["status"] != "OPERATIONAL":
            raise err("ERR_INVALID_STATE", "Only an OPERATIONAL station may be suspended.")
        station["status"] = "SUSPENDED"
        station["suspension_source"] = "MANUAL"
    elif target == "OPERATIONAL":
        if station["status"] != "SUSPENDED":
            raise err("ERR_INVALID_STATE", "Only a SUSPENDED station may be resumed.")
        if calc.out_of_service_port_count(station["id"]) != 0:
            raise err("ERR_INVALID_STATE",
                      "A station with out-of-service dispensers may not be resumed.")
        station["status"] = "OPERATIONAL"
        station["suspension_source"] = "NONE"
    else:  # DECOMMISSIONED
        cascades.teardown_station(station)
        return object_response(serialize.station(station))

    db.touch(station)
    return object_response(serialize.station(station))


@bp.post("/stations/<station_id>/commission")
@endpoint("NetworkOperator")
def commission_station(station_id):
    station = lookup.station(station_id)
    if station["status"] != "COMMISSIONING":
        raise err("ERR_INVALID_STATE",
                  "Only a COMMISSIONING station may be commissioned into service.")

    site = db.host_sites.get(station["host_site_id"])

    if site["agreement_status"] != "EXECUTED":
        raise err("ERR_HOST_AGREEMENT_NOT_EXECUTED",
                  "The host site agreement is not EXECUTED.")
    if site["power_upgrade_status"] not in ("NOT_REQUIRED", "ENERGIZED"):
        raise err("ERR_POWER_UPGRADE_NOT_ENERGIZED",
                  "The host site's power upgrade is not energized.")
    if site["parking_enforcement_mode"] not in ("SIGNAGE_ONLY", "TOWING_ENFORCED"):
        raise err("ERR_PARKING_ENFORCEMENT_REQUIRED",
                  "The host site has no contracted parking enforcement.")
    if calc.commissioned_port_count(station["id"]) < station["declared_port_count"]:
        raise err("ERR_PORT_COUNT_BELOW_DECLARED",
                  "The station has fewer non-retired dispensers than declared.")
    if calc.installed_power_kw(station["id"]) > site["committed_service_capacity_kw"]:
        raise err("ERR_SITE_CAPACITY_EXCEEDED",
                  "Installed power exceeds the host site's committed service capacity.")
    if calc.payment_interoperability_score(station["id"]) < calc.COMMISSION_MIN_SCORE:
        raise err("ERR_INTEROP_SCORE_BELOW_THRESHOLD",
                  "The station's payment interoperability score is below 90.00.")

    station["status"] = "OPERATIONAL"
    if station["commissioned_at"] is None:
        station["commissioned_at"] = clock.now()
    station["suspension_source"] = "NONE"
    db.touch(station)
    return object_response(serialize.station(station))
