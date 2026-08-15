from flask import Blueprint

from db import store
from errors import ApiError
from helpers import (
    add_trace,
    base_fields,
    get_customer_or_404,
    get_part_or_404,
    get_unit_or_404,
    list_response,
    pub,
)
from middleware import ALL_ROLES, get_json_body, require_roles, validate_body
from response import ok, ok_list

bp = Blueprint("units", __name__, url_prefix="/mro")

UNIT_SPEC = {
    "part_id": ("str", True),
    "serial_number": ("str", True),
    "ownership": ("enum", True, ["SHOP", "CUSTOMER"]),
    "owner_customer_id": ("str", False),
    "condition_status": ("enum", True, ["SERVICEABLE", "UNSERVICEABLE", "SCRAPPED"]),
    "custody_status": (
        "enum",
        True,
        ["OFF_SITE", "IN_SHOP", "AWAITING_SHIPMENT", "SHIPPED", "IN_POOL", "ON_LEASE"],
    ),
    "total_cycles": ("int", True),
    "cycles_since_overhaul": ("int", True),
    "manufactured_at": ("date", True),
}


@bp.route("/units", methods=["POST"])
@require_roles("CustomerServiceRep")
def register_unit():
    body = validate_body(get_json_body(), UNIT_SPEC)
    part = get_part_or_404(body["part_id"])
    if body["owner_customer_id"] is not None:
        get_customer_or_404(body["owner_customer_id"])
    # Ownership/custody combination rules
    if body["ownership"] == "CUSTOMER":
        if body["owner_customer_id"] is None or body["custody_status"] != "OFF_SITE":
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "CUSTOMER-owned unit requires owner_customer_id and custody OFF_SITE",
            )
    else:  # SHOP
        if body["owner_customer_id"] is not None or body["custody_status"] not in (
            "IN_POOL",
            "IN_SHOP",
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "SHOP-owned unit requires no owner and custody IN_POOL or IN_SHOP",
            )
    if any(u["serial_number"] == body["serial_number"] for u in store.units.values()):
        raise ApiError("ERR_DUPLICATE_SERIAL", 409, "serial_number already registered")
    u = dict(base_fields())
    u.update(
        {
            "part_id": part["id"],
            "serial_number": body["serial_number"],
            "ownership": body["ownership"],
            "owner_customer_id": body["owner_customer_id"],
            "condition_status": body["condition_status"],
            "custody_status": body["custody_status"],
            "total_cycles": body["total_cycles"],
            "cycles_since_overhaul": body["cycles_since_overhaul"],
            "manufactured_at": body["manufactured_at"],
        }
    )
    store.units[u["id"]] = u
    add_trace(u["id"], "BIRTH")
    return ok(pub(u), 201)


@bp.route("/units/<unitId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_unit(unitId):
    return ok(pub(get_unit_or_404(unitId)))


@bp.route("/units", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_units():
    return list_response(
        store.units.values(),
        filters={
            "part_id": "part_id",
            "owner_customer_id": "owner_customer_id",
            "ownership": "ownership",
            "custody_status": "custody_status",
            "condition_status": "condition_status",
        },
    )


@bp.route("/customers/<customerId>/units", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_customer_units(customerId):
    cust = get_customer_or_404(customerId)
    return list_response(
        [u for u in store.units.values() if u["owner_customer_id"] == cust["id"]]
    )


@bp.route("/units/<unitId>/traceability", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_unit_traceability(unitId):
    unit = get_unit_or_404(unitId)
    recs = [t for t in store.traces.values() if t["unit_id"] == unit["id"]]
    # Chronological ascending by event_at, ties broken by created_at.
    recs.sort(key=lambda t: (t["event_at"], t["created_at"], t["_seq"]))
    from middleware import pagination_params

    limit, offset = pagination_params()
    page = recs[offset : offset + limit]
    return ok_list([pub(t) for t in page], limit, offset, len(recs))
