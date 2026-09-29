"""Logical clock, Personnel and Bridge endpoints."""

from decimal import Decimal

from flask import Blueprint

import calc
import db
import params
import response
import serializers
import services
from db import db as store
from errors import ApiError
from middleware import (
    BRIDGE_INSPECTOR,
    DISTRICT_ENGINEER,
    PROGRAM_ADMIN,
    RATING_ENGINEER,
    authenticate,
    authenticate_read,
)

bp = Blueprint("core", __name__)

STRUCTURE_TYPES = ("GIRDER", "TRUSS", "ARCH", "SUSPENSION", "CULVERT")
SERVICE_POSTURES = ("OPEN", "POSTED", "RESTRICTED", "CLOSED")
SCOUR_STATUSES = ("NOT_EVALUATED", "LOW_RISK", "SCOUR_CRITICAL", "STABILIZED")


# --------------------------------------------------------------------------- #
# logical clock
# --------------------------------------------------------------------------- #
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(PROGRAM_ADMIN)
    body = params.json_body()
    raw, instant = params.get_instant(body, "to_iso8601", required=True)
    db.set_clock(instant)
    return response.object_response({"current_utc": db.fmt_dt(instant)})


# --------------------------------------------------------------------------- #
# personnel
# --------------------------------------------------------------------------- #
@bp.post("/personnel")
def create_personnel():
    authenticate(PROGRAM_ADMIN)
    body = params.json_body()
    full_name = params.get_string(body, "full_name", required=True)
    agency = params.get_string(body, "agency", required=True)
    raw_expiry, expiry = params.get_instant(body, "nbis_refresher_expiry_date", required=True)
    record = db.new_record(
        {
            "full_name": full_name,
            "agency": agency,
            "nbis_refresher_expiry_date": raw_expiry,
            "_expiry_date": expiry.date(),
            "team_leader_certified": params.get_bool(body, "team_leader_certified", default=False),
            "underwater_diver_certified": params.get_bool(
                body, "underwater_diver_certified", default=False
            ),
            "fracture_critical_certified": params.get_bool(
                body, "fracture_critical_certified", default=False
            ),
            "load_rating_engineer_licensed": params.get_bool(
                body, "load_rating_engineer_licensed", default=False
            ),
            "pe_license_number": params.get_string(body, "pe_license_number"),
        }
    )
    store.personnel[record["id"]] = record
    return response.object_response(serializers.personnel(record), 201)


@bp.get("/personnel/<person_id>")
def read_personnel(person_id):
    authenticate_read()
    record = services.get_personnel(person_id)
    return response.object_response(serializers.personnel(record))


@bp.get("/personnel")
def list_personnel():
    authenticate_read()
    limit, offset = params.query_pagination()
    agency = params.query_string("agency")
    team_leader = params.query_bool("team_leader_certified")
    licensed = params.query_bool("load_rating_engineer_licensed")
    status = params.query_enum("qualification_status", ("CURRENT", "EXPIRED"))
    items = []
    for record in services.rows("personnel"):
        if agency is not None and record["agency"] != agency:
            continue
        if team_leader is not None and bool(record["team_leader_certified"]) != team_leader:
            continue
        if licensed is not None and bool(record["load_rating_engineer_licensed"]) != licensed:
            continue
        data = serializers.personnel(record)
        if status is not None and data["qualification_status"] != status:
            continue
        items.append(data)
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


# --------------------------------------------------------------------------- #
# bridges
# --------------------------------------------------------------------------- #
@bp.post("/bridges")
def create_bridge():
    authenticate(PROGRAM_ADMIN)
    body = params.json_body()
    structure_number = params.get_string(
        body, "nbi_structure_number", required=True, min_length=1, max_length=15
    )
    name = params.get_string(body, "name", required=True)
    owner_agency = params.get_string(body, "owner_agency", required=True)
    structure_type = params.get_enum(body, "structure_type", STRUCTURE_TYPES, required=True)
    deck_area = params.get_number(body, "deck_area_sqm", required=True, exclusive_minimum=0)
    year_built = params.get_int(body, "year_built", required=True, minimum=1850, maximum=2026)
    adt = params.get_int(body, "adt", required=True, minimum=0)
    detour = params.get_number(body, "detour_length_km", required=True, minimum=0)
    spans_water = params.get_bool(body, "spans_water", default=False)
    underwater = params.get_bool(body, "underwater_elements", default=False)
    fracture = params.get_bool(body, "fracture_critical", default=False)
    initial_deck = params.get_int(body, "initial_deck_rating", default=7, minimum=0, maximum=9)
    initial_super = params.get_int(
        body, "initial_superstructure_rating", default=7, minimum=0, maximum=9
    )
    initial_sub = params.get_int(
        body, "initial_substructure_rating", default=7, minimum=0, maximum=9
    )

    for existing in store.bridges.values():
        if existing["nbi_structure_number"] == structure_number:
            raise ApiError("ERR_DUPLICATE_STRUCTURE_NUMBER")

    record = db.new_record(
        {
            "nbi_structure_number": structure_number,
            "name": name,
            "owner_agency": owner_agency,
            "structure_type": structure_type,
            "deck_area_sqm": deck_area,
            "year_built": year_built,
            "adt": adt,
            "detour_length_km": detour,
            "spans_water": spans_water,
            "underwater_elements": underwater,
            "fracture_critical": fracture,
            "initial_deck_rating": initial_deck,
            "initial_superstructure_rating": initial_super,
            "initial_substructure_rating": initial_sub,
            "deck_rating": initial_deck,
            "superstructure_rating": initial_super,
            "substructure_rating": initial_sub,
            "bridge_health_index": None,
            "inventoried_quantity_total": Decimal("0"),
            "deficiency_pct": Decimal("0.00"),
            "service_posture": "OPEN",
            "scour_status": "NOT_EVALUATED",
            "poa_compliant": True,
            "last_routine_inspection_date": None,
            "last_underwater_inspection_date": None,
            "posting_required": False,
            "posted_limit_tons": None,
            "operating_rating_tons": None,
            "inventory_rating_tons": None,
            "governing_load_rating_id": None,
            "open_critical_finding_count": 0,
        }
    )
    services.settle_bridge(record)
    store.bridges[record["id"]] = record
    return response.object_response(serializers.bridge(record), 201)


@bp.get("/bridges/<bridge_id>")
def read_bridge(bridge_id):
    authenticate_read()
    record = services.get_bridge(bridge_id)
    return response.object_response(serializers.bridge(record))


@bp.get("/bridges")
def list_bridges():
    authenticate_read()
    limit, offset = params.query_pagination()
    owner_agency = params.query_string("owner_agency")
    structure_type = params.query_enum("structure_type", STRUCTURE_TYPES)
    posture = params.query_enum("service_posture", SERVICE_POSTURES)
    scour_status = params.query_enum("scour_status", SCOUR_STATUSES)
    governing_id = params.query_string("governing_load_rating_id")
    posting_required = params.query_bool("posting_required")
    poa_compliant = params.query_bool("poa_compliant")
    fracture_critical = params.query_bool("fracture_critical")
    underwater_elements = params.query_bool("underwater_elements")
    items = []
    for record in services.rows("bridges"):
        if owner_agency is not None and record["owner_agency"] != owner_agency:
            continue
        if structure_type is not None and record["structure_type"] != structure_type:
            continue
        if posture is not None and record["service_posture"] != posture:
            continue
        if scour_status is not None and record["scour_status"] != scour_status:
            continue
        if governing_id is not None and record["governing_load_rating_id"] != governing_id:
            continue
        if posting_required is not None and bool(record["posting_required"]) != posting_required:
            continue
        if poa_compliant is not None and bool(record["poa_compliant"]) != poa_compliant:
            continue
        if fracture_critical is not None and bool(record["fracture_critical"]) != fracture_critical:
            continue
        if (
            underwater_elements is not None
            and bool(record["underwater_elements"]) != underwater_elements
        ):
            continue
        items.append(serializers.bridge(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.patch("/bridges/<bridge_id>")
def update_bridge(bridge_id):
    authenticate(PROGRAM_ADMIN)
    body = params.json_body()
    name = params.get_string(body, "name")
    adt = params.get_int(body, "adt", minimum=0)
    detour = params.get_number(body, "detour_length_km", minimum=0)
    fracture = params.get_bool(body, "fracture_critical")
    underwater = params.get_bool(body, "underwater_elements")
    spans_water = params.get_bool(body, "spans_water")
    record = services.get_bridge(bridge_id)
    if name is not None:
        record["name"] = name
    if adt is not None:
        record["adt"] = adt
    if detour is not None:
        record["detour_length_km"] = detour
    if fracture is not None:
        record["fracture_critical"] = fracture
    if underwater is not None:
        record["underwater_elements"] = underwater
    if spans_water is not None:
        record["spans_water"] = spans_water
    services.settle_and_touch(record)
    return response.object_response(serializers.bridge(record))


@bp.get("/bridges/<bridge_id>/compliance-summary")
def bridge_compliance_summary(bridge_id):
    authenticate_read()
    record = services.get_bridge(bridge_id)
    today = db.now().date()
    routine_due = record.get("next_inspection_due_date")
    underwater_due = record.get("next_underwater_due_date")
    data = {
        "bridge_id": record["id"],
        "inspection_interval_months": record["inspection_interval_months"],
        "next_inspection_due_date": db.fmt_date(routine_due),
        "next_underwater_due_date": db.fmt_date(underwater_due),
        "routine_overdue": bool(routine_due is not None and routine_due < today),
        "underwater_overdue": bool(underwater_due is not None and underwater_due < today),
        "poa_compliant": bool(record["poa_compliant"]),
        "open_critical_finding_count": record["open_critical_finding_count"],
        "service_posture": record["service_posture"],
        "min_nbi_rating": record["min_nbi_rating"],
        "bridge_health_index": record["bridge_health_index"],
    }
    return response.object_response(data)
