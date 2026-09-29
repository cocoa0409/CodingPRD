"""Ports, meeting points and the per-port revenue report."""

from flask import Blueprint

from db import db
from errors import fail
from middleware import FINANCE, MANAGER, endpoint
from response import list_response, object_response
from routes import API_PREFIX
from serializers import meeting_point_json, port_json
from services.revenue import build_report
from validation import (f, paginate, pagination, port_or_404, meeting_point_or_404,
                        query_values, validate_body)

bp = Blueprint("ports", __name__)

DOCKING_MODES = ("ALONGSIDE", "TENDER")
ZONES = ("PIER_APRON", "TENDER_PONTOON", "TERMINAL_HALL")

PORT_CREATE = [
    f("port_code", "string", required=True, regex=r"^[A-Z]{3,5}$"),
    f("name", "string", required=True),
    f("country_code", "string", required=True, regex=r"^[A-Z]{2}$"),
    f("docking_mode", "enum", required=True, enum=DOCKING_MODES),
    f("risk_buffer_minutes", "int", lo=0, hi=240),
    f("tender_egress_minutes", "int", lo=0, hi=180),
]

MEETING_POINT_CREATE = [
    f("name", "string", required=True),
    f("zone", "enum", required=True, enum=ZONES),
    f("max_concurrent_groups", "int", required=True, lo=1, hi=12),
    f("slot_buffer_minutes", "int", lo=0, hi=60),
]


@bp.post(API_PREFIX + "/ports")
@endpoint(MANAGER)
def create_port(caller):
    body = validate_body(PORT_CREATE)
    for existing in db.ports.values():
        if existing["port_code"] == body["port_code"]:
            fail("ERR_DUPLICATE_PORT_CODE", "port_code is already registered")
    row = db.insert("ports", {
        "port_code": body["port_code"],
        "name": body["name"],
        "country_code": body["country_code"],
        "docking_mode": body["docking_mode"],
        "risk_buffer_minutes": body.get("risk_buffer_minutes", 30),
        "tender_egress_minutes": body.get("tender_egress_minutes", 25),
    })
    return object_response(port_json(row), 201)


@bp.get(API_PREFIX + "/ports/<port_id>")
@endpoint()
def read_port(caller, port_id):
    return object_response(port_json(port_or_404(port_id)))


@bp.get(API_PREFIX + "/ports")
@endpoint()
def list_ports(caller):
    limit, offset = pagination()
    filters = query_values([
        f("country_code", "string"),
        f("docking_mode", "enum", enum=DOCKING_MODES),
    ])
    rows = db.ordered("ports")
    if "country_code" in filters:
        rows = [r for r in rows if r["country_code"] == filters["country_code"]]
    if "docking_mode" in filters:
        rows = [r for r in rows if r["docking_mode"] == filters["docking_mode"]]
    page, total = paginate(rows, limit, offset)
    return list_response([port_json(r) for r in page], limit, offset, total)


@bp.get(API_PREFIX + "/ports/<port_id>/revenue-report")
@endpoint(FINANCE, MANAGER)
def revenue_report(caller, port_id):
    filters = query_values([f("voyage_code", "string")])
    port = port_or_404(port_id)
    return object_response(build_report(port, filters.get("voyage_code")))


@bp.post(API_PREFIX + "/ports/<port_id>/meeting-points")
@endpoint(MANAGER)
def create_meeting_point(caller, port_id):
    body = validate_body(MEETING_POINT_CREATE)
    port = port_or_404(port_id)
    row = db.insert("meeting_points", {
        "port_id": port["id"],
        "name": body["name"],
        "zone": body["zone"],
        "max_concurrent_groups": body["max_concurrent_groups"],
        "slot_buffer_minutes": body.get("slot_buffer_minutes", 10),
    })
    return object_response(meeting_point_json(row), 201)


@bp.get(API_PREFIX + "/meeting-points/<meeting_point_id>")
@endpoint()
def read_meeting_point(caller, meeting_point_id):
    return object_response(meeting_point_json(meeting_point_or_404(meeting_point_id)))


@bp.get(API_PREFIX + "/meeting-points")
@endpoint()
def list_meeting_points(caller):
    limit, offset = pagination()
    filters = query_values([
        f("port_id", "string"),
        f("zone", "enum", enum=ZONES),
    ])
    rows = db.ordered("meeting_points")
    if "port_id" in filters:
        rows = [r for r in rows if r["port_id"] == filters["port_id"]]
    if "zone" in filters:
        rows = [r for r in rows if r["zone"] == filters["zone"]]
    page, total = paginate(rows, limit, offset)
    return list_response([meeting_point_json(r) for r in page], limit, offset, total)
