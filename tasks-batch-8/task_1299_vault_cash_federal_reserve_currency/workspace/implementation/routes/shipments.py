"""CashShipment endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import DB, new_id, clock_date_str
from errors import ApiError
from middleware import (
    auth, ALL_ROLES, SITE_SCOPED_STAFF_ROLES, require_site_scope,
    require_carrier_ownership,
)
from response import ok, ok_list
from services import stamp_new, touch, public, append_ledger, site_mutation
from util import (
    body, required, as_int, as_str, as_iso_dt, parse_dt, pagination_args,
)

bp = Blueprint("shipments", __name__)

TURNAROUND_MINUTES = 45
DOCK_WINDOW_MINUTES = 30


def _get_shipment_or_404(shipment_id):
    shipment = DB["cash_shipments"].get(shipment_id)
    if shipment is None:
        raise ApiError("ERR_SHIPMENT_NOT_FOUND", 404, "Shipment not found")
    return shipment


def _site_or_404(site_id):
    site = DB["vault_sites"].get(site_id)
    if site is None:
        raise ApiError("ERR_VAULT_SITE_NOT_FOUND", 404, "Vault site not found")
    return site


@bp.post("/vault-cash/cash-shipments")
def create_shipment():
    principal = auth(["FedCoordinator"])
    data = body()
    carrier_id = as_str(required(data, "carrier_id"), "carrier_id")
    carrier = DB["carriers"].get(carrier_id)
    if carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND", 404, "Carrier not found")
    departure = as_iso_dt(
        required(data, "scheduled_departure_at"), "scheduled_departure_at"
    )
    arrival = as_iso_dt(
        required(data, "scheduled_arrival_at"), "scheduled_arrival_at"
    )
    if not parse_dt(arrival) > parse_dt(departure):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "scheduled_arrival_at must be after scheduled_departure_at",
        )

    fed_order_id = data.get("fed_order_id")
    order = None
    if fed_order_id is not None:
        fed_order_id = as_str(fed_order_id, "fed_order_id")
        order = DB["fed_orders"].get(fed_order_id)
        if order is None:
            raise ApiError("ERR_FED_ORDER_NOT_FOUND", 404, "Fed order not found")

    if order is not None:
        # Fed-linked: origin/destination derived from the linked order.
        if order["direction"] == "ORDER":
            origin_site_id = None
            destination_site_id = order["site_id"]
        else:
            origin_site_id = order["site_id"]
            destination_site_id = None
        declared = order["face_total_cents"]
        require_site_scope(principal, order["site_id"])
        # Linked order must be SUBMITTED or ACKNOWLEDGED at scheduling time.
        if order["status"] not in ("SUBMITTED", "ACKNOWLEDGED"):
            raise ApiError(
                "ERR_LINKED_ORDER_NOT_ACKNOWLEDGED",
                409,
                "Linked Fed order must be SUBMITTED or ACKNOWLEDGED",
            )
    else:
        origin_site_id = data.get("origin_site_id")
        destination_site_id = data.get("destination_site_id")
        if origin_site_id is not None:
            origin_site_id = as_str(origin_site_id, "origin_site_id")
            _site_or_404(origin_site_id)
        if destination_site_id is not None:
            destination_site_id = as_str(destination_site_id, "destination_site_id")
            _site_or_404(destination_site_id)
        declared = as_int(
            required(data, "declared_value_cents"), "declared_value_cents"
        )
        # Site scope: coordinator must be scoped to a site involved.
        scope_site = origin_site_id if origin_site_id is not None else destination_site_id
        require_site_scope(principal, scope_site)

    # Cross-entity state guard (priority 8): carrier must be ACTIVE.
    if carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED", 409, "Carrier is not ACTIVE")

    inbound = destination_site_id is not None
    # Insurance headroom guard (priority 10, business_safety) — evaluated before
    # the temporal and fiscal rules below; candidate excluded from committed.
    if inbound:
        dest = _site_or_404(destination_site_id)
        committed = (
            dest["on_hand_total_cents"]
            + dest.get("in_transit_inbound_cents", 0)
            + dest.get("pending_inbound_order_cents", 0)
        )
        headroom = dest["insurance_coverage_cents"] - committed
        if declared > headroom:
            raise ApiError(
                "ERR_INSURANCE_HEADROOM_EXCEEDED",
                402,
                "Inbound declared value exceeds insurance headroom",
            )

    # Turnaround (priority 12): the new shipment's [dep, arr] window, expanded by
    # 45 min on both ends, must not overlap any non-cancelled same-carrier
    # shipment's expanded window. Windows are half-open: a gap of exactly 45 min
    # is permitted, so boundary-touching is not a conflict. Equivalent form:
    # conflict iff new_dep < s_arr + 45m AND s_dep < new_arr + 45m.
    new_dep = parse_dt(departure)
    new_arr = parse_dt(arrival)
    for s in DB["cash_shipments"].values():
        if s["carrier_id"] != carrier_id or s["status"] == "CANCELLED":
            continue
        s_dep = parse_dt(s["scheduled_departure_at"])
        s_arr = parse_dt(s["scheduled_arrival_at"])
        if (
            new_dep < s_arr + timedelta(minutes=TURNAROUND_MINUTES)
            and s_dep < new_arr + timedelta(minutes=TURNAROUND_MINUTES)
        ):
            raise ApiError(
                "ERR_CARRIER_TURNAROUND_CONFLICT",
                409,
                "Shipment window conflicts with the carrier turnaround buffer",
            )

    if inbound:
        # Dock capacity (priority 13): arrivals within +/-30 min of the new one.
        count = 0
        for s in DB["cash_shipments"].values():
            if s.get("destination_site_id") != destination_site_id:
                continue
            if s["status"] not in ("SCHEDULED", "LOADED", "IN_TRANSIT"):
                continue
            s_arr = parse_dt(s["scheduled_arrival_at"])
            if abs((s_arr - new_arr).total_seconds()) <= DOCK_WINDOW_MINUTES * 60:
                count += 1
        if count >= dest["dock_capacity"]:
            raise ApiError(
                "ERR_DOCK_CAPACITY_EXCEEDED",
                409,
                "Destination dock capacity exceeded at the arrival instant",
            )

    # Carrier liability (priority 18, business_fiscal): declared <= per-truck cap.
    if declared > carrier["liability_cap_per_truck_cents"]:
        raise ApiError(
            "ERR_CARRIER_LIABILITY_EXCEEDED",
            402,
            "Declared value exceeds carrier per-truck liability cap",
        )

    shipment = stamp_new({
        "id": new_id(),
        "fed_order_id": fed_order_id,
        "carrier_id": carrier_id,
        "origin_site_id": origin_site_id,
        "destination_site_id": destination_site_id,
        "declared_value_cents": declared,
        "counted_value_cents": None,
        "scheduled_departure_at": departure,
        "scheduled_arrival_at": arrival,
        "status": "SCHEDULED",
    })
    DB["cash_shipments"][shipment["id"]] = shipment

    # Outbound schedule immediately reserves value at origin.
    if origin_site_id is not None:
        origin = _site_or_404(origin_site_id)
        origin["reserved_out_cents"] = origin.get("reserved_out_cents", 0) + declared
        site_mutation(origin)
    return ok(public(shipment), status=201)


@bp.get("/vault-cash/cash-shipments")
def list_shipments():
    principal = auth(ALL_ROLES)
    limit, offset = pagination_args()
    carrier_id = request.args.get("carrier_id")
    origin_site_id = request.args.get("origin_site_id")
    destination_site_id = request.args.get("destination_site_id")
    fed_order_id = request.args.get("fed_order_id")
    status = request.args.get("status")
    rows = list(DB["cash_shipments"].values())
    if carrier_id is not None:
        rows = [s for s in rows if s["carrier_id"] == carrier_id]
    if origin_site_id is not None:
        rows = [s for s in rows if s.get("origin_site_id") == origin_site_id]
    if destination_site_id is not None:
        rows = [s for s in rows if s.get("destination_site_id") == destination_site_id]
    if fed_order_id is not None:
        rows = [s for s in rows if s.get("fed_order_id") == fed_order_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        hs = principal.home_site_id
        rows = [
            s for s in rows
            if s.get("origin_site_id") == hs or s.get("destination_site_id") == hs
        ]
    rows.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(rows)
    return ok_list([public(s) for s in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/vault-cash/cash-shipments/<shipmentId>")
def get_shipment(shipmentId):
    principal = auth(ALL_ROLES)
    shipment = _get_shipment_or_404(shipmentId)
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        hs = principal.home_site_id
        if shipment.get("origin_site_id") != hs and shipment.get("destination_site_id") != hs:
            raise ApiError(
                "ERR_SITE_SCOPE_VIOLATION", 403, "Shipment belongs to another site"
            )
    return ok(public(shipment))


@bp.post("/vault-cash/cash-shipments/<shipmentId>/load")
def load_shipment(shipmentId):
    principal = auth(["FedCoordinator"])
    shipment = _get_shipment_or_404(shipmentId)
    scope_site = shipment.get("origin_site_id") or shipment.get("destination_site_id")
    require_site_scope(principal, scope_site)

    if shipment["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_SHIPMENT_INVALID_STATE", 409, "Only SCHEDULED shipments may load"
        )
    carrier = DB["carriers"].get(shipment["carrier_id"])
    if carrier is None or carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED", 409, "Carrier is not ACTIVE")
    order = None
    if shipment.get("fed_order_id"):
        order = DB["fed_orders"].get(shipment["fed_order_id"])
        if order is None or order["status"] != "ACKNOWLEDGED":
            raise ApiError(
                "ERR_LINKED_ORDER_NOT_ACKNOWLEDGED",
                409,
                "Linked Fed order must be ACKNOWLEDGED at load",
            )

    declared = shipment["declared_value_cents"]
    if shipment.get("origin_site_id") is not None:
        origin = _site_or_404(shipment["origin_site_id"])
        if origin["posture"] == "FROZEN":
            raise ApiError("ERR_VAULT_FROZEN", 409, "Origin site posture is FROZEN")
        # Outbound physical debit, pinned to the FIT bucket.
        origin["reserved_out_cents"] = origin.get("reserved_out_cents", 0) - declared
        entry_type = "SHIPMENT_OUT"
        if order is not None and order["direction"] == "DEPOSIT":
            entry_type = "FED_DEPOSIT"
        append_ledger(
            origin["id"], clock_date_str(), entry_type, -declared, "FIT",
            note=f"Shipment {shipment['id']} load",
        )
    else:
        # Inbound: declared value enters in-transit exposure at destination.
        dest = _site_or_404(shipment["destination_site_id"])
        dest["in_transit_inbound_cents"] = (
            dest.get("in_transit_inbound_cents", 0) + declared
        )
        site_mutation(dest)

    shipment["status"] = "LOADED"
    touch(shipment)
    return ok(public(shipment))


@bp.post("/vault-cash/cash-shipments/<shipmentId>/depart")
def depart_shipment(shipmentId):
    principal = auth(["CarrierDispatcher"])
    shipment = _get_shipment_or_404(shipmentId)
    require_carrier_ownership(principal, shipment)
    if shipment["status"] != "LOADED":
        raise ApiError(
            "ERR_SHIPMENT_INVALID_STATE", 409, "Only LOADED shipments may depart"
        )
    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    if shipment.get("fed_order_id"):
        order = DB["fed_orders"].get(shipment["fed_order_id"])
        if order is not None and order["status"] == "ACKNOWLEDGED":
            order["status"] = "IN_TRANSIT"
            touch(order)
    return ok(public(shipment))


@bp.post("/vault-cash/cash-shipments/<shipmentId>/verify")
def verify_shipment(shipmentId):
    principal = auth(["CarrierDispatcher"])
    shipment = _get_shipment_or_404(shipmentId)
    require_carrier_ownership(principal, shipment)
    data = body()
    counted = as_int(required(data, "counted_value_cents"), "counted_value_cents")
    accept_variance = data.get("accept_variance", False)
    if accept_variance is None:
        accept_variance = False
    if not isinstance(accept_variance, bool):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "accept_variance must be a boolean"
        )

    declared = shipment["declared_value_cents"]
    status = shipment["status"]
    if status == "IN_TRANSIT":
        shipment["counted_value_cents"] = counted
        if counted == declared:
            _finalize_verify(shipment, counted)
        else:
            shipment["status"] = "EXCEPTION"
            touch(shipment)
    elif status == "EXCEPTION":
        if not accept_variance:
            raise ApiError(
                "ERR_SHIPMENT_INVALID_STATE",
                409,
                "EXCEPTION shipments require accept_variance to verify",
            )
        _finalize_verify(shipment, shipment["counted_value_cents"])
    else:
        raise ApiError(
            "ERR_SHIPMENT_INVALID_STATE",
            409,
            "Only IN_TRANSIT or EXCEPTION shipments may verify",
        )
    return ok(public(shipment))


def _finalize_verify(shipment, counted):
    """Matched verify or exception-accept: move cash, set basis, RECEIVED cascade."""
    declared = shipment["declared_value_cents"]
    order = DB["fed_orders"].get(shipment.get("fed_order_id")) if shipment.get("fed_order_id") else None
    business_date = clock_date_str()

    if shipment.get("destination_site_id") is not None:
        # Inbound: credit destination with counted; release full declared from transit.
        dest = _site_or_404(shipment["destination_site_id"])
        dest["in_transit_inbound_cents"] = (
            dest.get("in_transit_inbound_cents", 0) - declared
        )
        site_mutation(dest)
        entry_type = "SHIPMENT_IN"
        if order is not None and order["direction"] == "ORDER":
            entry_type = "FED_RECEIPT"
        append_ledger(
            dest["id"], business_date, entry_type, counted, "FIT",
            note=f"Shipment {shipment['id']} verify",
        )
        if order is not None:
            # Matched verify books declared; exception-accept books counted.
            order["settled_basis_cents"] = counted if shipment["status"] == "EXCEPTION" else declared
    else:
        # Outbound exception-accept: return undelivered value to origin fit.
        if shipment["status"] == "EXCEPTION":
            origin = _site_or_404(shipment["origin_site_id"])
            append_ledger(
                origin["id"], business_date, "ADJUSTMENT", declared - counted, "FIT",
                note=f"Shipment {shipment['id']} exception accept",
            )
        if order is not None:
            order["settled_basis_cents"] = counted

    shipment["status"] = "VERIFIED"
    touch(shipment)
    if order is not None and order["status"] == "IN_TRANSIT":
        order["status"] = "RECEIVED"
        touch(order)
        # IN_TRANSIT -> RECEIVED side effect: pending inbound exposure releases.
        if order["direction"] == "ORDER":
            order_site = _site_or_404(order["site_id"])
            order_site["pending_inbound_order_cents"] = (
                order_site.get("pending_inbound_order_cents", 0)
                - order["face_total_cents"]
            )
            site_mutation(order_site)


@bp.post("/vault-cash/cash-shipments/<shipmentId>/cancel")
def cancel_shipment(shipmentId):
    principal = auth(["FedCoordinator"])
    shipment = _get_shipment_or_404(shipmentId)
    scope_site = shipment.get("origin_site_id") or shipment.get("destination_site_id")
    require_site_scope(principal, scope_site)
    if shipment["status"] not in ("SCHEDULED", "LOADED"):
        raise ApiError(
            "ERR_SHIPMENT_INVALID_STATE",
            409,
            "Only SCHEDULED or LOADED shipments may be cancelled",
        )
    declared = shipment["declared_value_cents"]
    was_loaded = shipment["status"] == "LOADED"
    shipment["status"] = "CANCELLED"
    touch(shipment)

    if shipment.get("origin_site_id") is not None:
        origin = _site_or_404(shipment["origin_site_id"])
        if was_loaded:
            # Load already consumed the reservation (reserved_out -> 0 at load);
            # cancellation from LOADED returns the value to origin fit via a
            # SHIPMENT_IN reversal ledger entry. reserved_out is untouched here.
            append_ledger(
                origin["id"], clock_date_str(), "SHIPMENT_IN", declared, "FIT",
                note=f"Shipment {shipment['id']} cancel reversal",
            )
        else:
            # Compensation: cancelling from SCHEDULED releases the reservation.
            origin["reserved_out_cents"] = origin.get("reserved_out_cents", 0) - declared
            site_mutation(origin)
    elif was_loaded and shipment.get("destination_site_id") is not None:
        # Inbound cancel from LOADED: release in-transit exposure.
        dest = _site_or_404(shipment["destination_site_id"])
        dest["in_transit_inbound_cents"] = (
            dest.get("in_transit_inbound_cents", 0) - declared
        )
        site_mutation(dest)
    return ok(public(shipment))
