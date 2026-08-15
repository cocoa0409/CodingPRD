"""ShipmentRecord endpoints."""

from flask import request

from db import STORE, create_entity, touch, public, sort_default
from errors import (ApiError, ERR_INVALID_STATE, ERR_DUPLICATE_PRO_NUMBER,
                    ERR_NOT_FOUND)
from middleware import (authenticate, require_roles, guard_read_scope,
                        in_read_scope, require_client_active, resolve,
                        READ_ROLES)
from response import success_object, success_list
from validate import get_body, check_shape, parse_pagination

MODES = ["PARCEL", "LTL", "FTL", "AIR", "OCEAN"]


def serialize_shipment(shipment):
    return public(shipment)


def register(app):

    @app.route("/fap/clients/<cid>/shipments", methods=["POST"])
    def create_shipment(cid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        client = resolve(STORE.clients, cid)
        body = get_body(allow_empty=False)
        # Stage 3: body FK — carrier_id must exist and belong to this client.
        carrier_id = body.get("carrier_id")
        if carrier_id is not None:
            carrier = STORE.carriers.get(carrier_id)
            if carrier is None or carrier["client_id"] != cid:
                raise ApiError(ERR_NOT_FOUND, 404,
                               "Referenced carrier_id does not exist")
        require_client_active(client)
        check_shape(body, {
            "carrier_id": {"kind": "string", "required": True},
            "pro_number": {"kind": "string", "required": True},
            "ship_date": {"kind": "date", "required": True},
            "origin_country": {"kind": "string", "required": True},
            "dest_country": {"kind": "string", "required": True},
            "mode": {"kind": "string", "required": True, "enum": MODES},
            "actual_weight_kg": {"kind": "number", "required": True},
            "accessorials_rendered": {"kind": "array", "required": False},
        })
        # Stage 9: PRO number uniqueness per (client, carrier) among non-VOIDED.
        for other in STORE.shipments.values():
            if other["client_id"] == cid and other["carrier_id"] == carrier_id \
                    and other["status"] != "VOIDED" \
                    and other["pro_number"] == body["pro_number"]:
                raise ApiError(ERR_DUPLICATE_PRO_NUMBER, 409,
                               "pro_number already used by a non-VOIDED shipment")
        shipment = create_entity(STORE.shipments, {
            "client_id": cid,
            "carrier_id": carrier_id,
            "pro_number": body["pro_number"],
            "ship_date": body["ship_date"],
            "origin_country": body["origin_country"],
            "dest_country": body["dest_country"],
            "mode": body["mode"],
            "actual_weight_kg": body["actual_weight_kg"],
            "accessorials_rendered": body.get("accessorials_rendered") or [],
            "status": "REGISTERED",
        })
        return success_object(serialize_shipment(shipment), status=201)

    @app.route("/fap/shipments/<sid>", methods=["GET"])
    def get_shipment(sid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        shipment = guard_read_scope(role, uid, "shipment", STORE.shipments.get(sid))
        return success_object(serialize_shipment(shipment))

    @app.route("/fap/shipments", methods=["GET"])
    def list_shipments():
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        limit, offset = parse_pagination()
        rows = [s for s in STORE.shipments.values()
                if in_read_scope(role, uid, "shipment", s)]
        for param in ("client_id", "carrier_id", "status"):
            value = request.args.get(param)
            if value is not None:
                rows = [s for s in rows if str(s.get(param)) == value]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([serialize_shipment(s) for s in page], limit, offset, total)

    @app.route("/fap/shipments/<sid>/void", methods=["POST"])
    def void_shipment(sid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        shipment = resolve(STORE.shipments, sid)
        require_client_active(STORE.clients.get(shipment["client_id"]))
        body = get_body()
        check_shape(body, {})
        if shipment["status"] != "REGISTERED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Shipment cannot be voided from %s" % shipment["status"])
        referenced = any(
            inv.get("shipment_id") == sid and inv["audit_status"] != "VOIDED"
            for inv in STORE.invoices.values()
        )
        if referenced:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Shipment is referenced by a non-VOIDED invoice")
        shipment["status"] = "VOIDED"
        touch(shipment)
        return success_object(serialize_shipment(shipment))
