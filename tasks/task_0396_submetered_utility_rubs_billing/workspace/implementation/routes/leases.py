"""Lease lifecycle (PRD §3.3)."""

from flask import Blueprint, request, g

import db
from errors import ApiError
from middleware import require_roles
from response import success, list_success
from services.common import (
    get_json_body, require_fields, serialize, parse_iso, parse_date_field,
    pagination_params, paginate, sort_by_creation,
)

leases_bp = Blueprint("leases", __name__)


@leases_bp.route("/leases", methods=["POST"])
@require_roles("PropertyManager")
def create_lease():
    body = get_json_body()
    require_fields(body, "unit_id", "property_id", "tenant_user_id", "occupant_count", "move_in_date")

    unit_id = body["unit_id"]
    if unit_id not in db.units:
        raise ApiError("ERR_NOT_FOUND", "Unit not found")
    property_id = body["property_id"]
    if property_id not in db.properties:
        raise ApiError("ERR_NOT_FOUND", "Property not found")

    tenant_user_id = body["tenant_user_id"]
    if not isinstance(tenant_user_id, str) or not tenant_user_id.strip():
        raise ApiError("ERR_INVALID_REQUEST", "tenant_user_id must be a non-empty string")

    occupant_count = body["occupant_count"]
    if (not isinstance(occupant_count, int) or isinstance(occupant_count, bool)
            or occupant_count < 1):
        raise ApiError("ERR_INVALID_REQUEST", "occupant_count must be >= 1")

    # Validate move_in_date is a parseable date.
    parse_iso(body["move_in_date"], "move_in_date")

    record = {
        "unit_id": unit_id,
        "property_id": property_id,
        "tenant_user_id": tenant_user_id,
        "occupant_count": occupant_count,
        "move_in_date": body["move_in_date"],
        "notice_date": None,
        "move_out_date": None,
        "status": "PENDING",
    }
    db.stamp_create(record)
    db.leases[record["id"]] = record
    return success(serialize(record), status=201)


@leases_bp.route("/leases/<lease_id>", methods=["GET"])
@require_roles("PropertyManager", "Tenant", "Auditor")
def get_lease(lease_id):
    record = db.leases.get(lease_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", "Lease not found")
    return success(serialize(record), status=200)


@leases_bp.route("/leases", methods=["GET"])
@require_roles("PropertyManager", "Tenant", "Auditor")
def list_leases():
    unit_id = request.args.get("unit_id")
    property_id = request.args.get("property_id")
    tenant_user_id = request.args.get("tenant_user_id")
    status = request.args.get("status")
    items = list(db.leases.values())
    if unit_id is not None:
        items = [l for l in items if l["unit_id"] == unit_id]
    if property_id is not None:
        items = [l for l in items if l["property_id"] == property_id]
    if tenant_user_id is not None:
        items = [l for l in items if l["tenant_user_id"] == tenant_user_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items = sort_by_creation(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return list_success([serialize(l) for l in page], limit, offset, total)


@leases_bp.route("/leases/<lease_id>/activate", methods=["POST"])
@require_roles("PropertyManager")
def activate_lease(lease_id):
    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError("ERR_NOT_FOUND", "Lease not found")
    if lease["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Lease is not PENDING")

    unit = db.units.get(lease["unit_id"])
    if unit is None or unit["status"] == "ARCHIVED":
        raise ApiError("ERR_UNIT_NOT_FOUND", "Unit not found or archived")

    move_in = parse_date_field(lease["move_in_date"], "move_in_date")
    # Overlap vs other ACTIVE/NOTICE_GIVEN leases of the same unit whose
    # occupancy interval [move_in, move_out] (inclusive; null=open) overlaps
    # this lease's move_in_date.
    for other in db.leases.values():
        if other["id"] == lease_id:
            continue
        if other["unit_id"] != lease["unit_id"]:
            continue
        if other["status"] not in ("ACTIVE", "NOTICE_GIVEN"):
            continue
        o_in = parse_date_field(other["move_in_date"], "move_in_date")
        o_out = parse_date_field(other["move_out_date"], "move_out_date") if other["move_out_date"] else None
        # Does move_in fall within [o_in, o_out]? (o_out inclusive; null=open)
        if move_in >= o_in and (o_out is None or move_in <= o_out):
            raise ApiError("ERR_LEASE_OCCUPANCY_OVERLAP", "Lease occupancy overlaps")

    lease["status"] = "ACTIVE"
    db.touch(lease)
    unit["status"] = "OCCUPIED"
    db.touch(unit)
    return success(serialize(lease), status=200)


@leases_bp.route("/leases/<lease_id>/give-notice", methods=["POST"])
@require_roles("PropertyManager", "Tenant")
def give_notice(lease_id):
    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError("ERR_NOT_FOUND", "Lease not found")

    # Tenant ownership (priority 4, before body validation / state).
    if g.user_role == "Tenant" and lease["tenant_user_id"] != g.user_id:
        raise ApiError("ERR_NOT_STATEMENT_OWNER", "Tenant does not own this lease")

    body = get_json_body()
    require_fields(body, "move_out_date")
    move_out = parse_date_field(body["move_out_date"], "move_out_date")

    if lease["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Lease is not ACTIVE")

    move_in = parse_date_field(lease["move_in_date"], "move_in_date")
    if move_out < move_in:
        raise ApiError("ERR_INVALID_MOVE_OUT_DATE", "move_out_date earlier than move_in_date")

    lease["notice_date"] = db.now_iso()
    lease["move_out_date"] = body["move_out_date"]
    lease["status"] = "NOTICE_GIVEN"
    db.touch(lease)
    return success(serialize(lease), status=200)


@leases_bp.route("/leases/<lease_id>/move-out", methods=["POST"])
@require_roles("PropertyManager")
def move_out(lease_id):
    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError("ERR_NOT_FOUND", "Lease not found")
    if lease["status"] != "NOTICE_GIVEN":
        raise ApiError("ERR_INVALID_STATE", "Lease is not NOTICE_GIVEN")

    clock_date = db.get_clock().date()
    move_out_date = parse_date_field(lease["move_out_date"], "move_out_date")
    if not (clock_date > move_out_date):
        raise ApiError("ERR_MOVE_OUT_NOT_DUE", "Move-out date not yet passed")

    lease["status"] = "MOVED_OUT"
    db.touch(lease)
    unit = db.units.get(lease["unit_id"])
    if unit is not None:
        unit["status"] = "VACANT"
        db.touch(unit)
    return success(serialize(lease), status=200)


@leases_bp.route("/leases/<lease_id>/close", methods=["POST"])
@require_roles("PropertyManager")
def close_lease(lease_id):
    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError("ERR_NOT_FOUND", "Lease not found")
    if lease["status"] != "MOVED_OUT":
        raise ApiError("ERR_INVALID_STATE", "Lease is not MOVED_OUT")

    open_statuses = {"UNPAID", "PARTIALLY_PAID", "DELINQUENT", "IN_COLLECTIONS"}
    for stmt in db.tenant_statements.values():
        if stmt["lease_id"] == lease_id and stmt["payment_status"] in open_statuses:
            raise ApiError("ERR_LEASE_HAS_OPEN_BALANCE", "Lease has statements still owing")

    lease["status"] = "CLOSED"
    db.touch(lease)
    return success(serialize(lease), status=200)
