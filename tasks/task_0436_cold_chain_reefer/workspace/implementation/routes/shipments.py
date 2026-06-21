"""Shipment endpoints and lifecycle transitions (PRD §3.2–§3.8).

Lifecycle: TENDERED -> ACCEPTED -> PRECOOLED -> IN_TRANSIT -> DELIVERED;
plus TENDERED -> REJECTED and ACCEPTED|PRECOOLED -> CANCELLED.
"""

from flask import Blueprint, request

from constants import CARGO_CLASSES, SHIPMENT_STATUSES
from db import store
from errors import err
from helpers import (
    get_shipment_or_404,
    pagination_params,
    paginate,
)
from middleware import authenticate, require_role
from models import serialize, stamp_create, touch
from response import array_response, object_response
from services import (
    compartment_has_inband_precool,
    finalize_on_deliver,
    integrity_report,
    live_posture,
    shipment_view,
)
from validators import as_enum, as_int, as_string, get_body, require

bp = Blueprint("shipments", __name__)


def _compartments_of(shipment_id):
    return [c for c in store.compartments.values() if c["shipment_id"] == shipment_id]


def _lane_regulated_any(shipment_id):
    for c in _compartments_of(shipment_id):
        lane = store.temp_lanes.get(c["temp_lane_id"])
        if lane is not None and lane["regulated"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Create / read / list
# ---------------------------------------------------------------------------
@bp.route("/shipments", methods=["POST"])
def create_shipment():
    uid, role = authenticate()
    require_role(role, {"Shipper", "PlatformAdmin"})

    body = get_body(request)
    carrier_id = as_string(require(body, "carrier_id"), "carrier_id")
    cargo_class = as_enum(require(body, "cargo_class"), "cargo_class", CARGO_CLASSES)

    if carrier_id not in store.carriers:
        raise err("ERR_FK_NOT_FOUND", "carrier_id does not resolve to a carrier")

    rec = {
        "shipper_user_id": uid,                 # stamped from X-User-ID (PRD §3.2)
        "carrier_id": carrier_id,
        "reefer_unit_id": None,
        "cargo_class": cargo_class,
        "status": "TENDERED",
        "load_integrity_posture": "INTACT",
        "precool_verified": False,
        "total_detention_fee_cents": 0,
        "total_lumper_fee_cents": 0,
        "_in_transit_anchor": None,
    }
    stamp_create(rec)
    store.shipments[rec["id"]] = rec
    return object_response(shipment_view(rec), 201)


@bp.route("/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "Driver", "ComplianceOfficer", "PlatformAdmin"})
    rec = get_shipment_or_404(sid)
    return object_response(shipment_view(rec), 200)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "ComplianceOfficer", "PlatformAdmin"})
    limit, offset = pagination_params()

    carrier_id = request.args.get("carrier_id")
    reefer_unit_id = request.args.get("reefer_unit_id")
    shipper_user_id = request.args.get("shipper_user_id")
    status = request.args.get("status")
    if status is not None and status not in SHIPMENT_STATUSES:
        raise err("ERR_INVALID_REQUEST", "Invalid status filter")

    records = list(store.shipments.values())
    if carrier_id is not None:
        records = [r for r in records if r["carrier_id"] == carrier_id]
    if reefer_unit_id is not None:
        records = [r for r in records if r["reefer_unit_id"] == reefer_unit_id]
    if shipper_user_id is not None:
        records = [r for r in records if r["shipper_user_id"] == shipper_user_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]

    # paginate with the live posture surfaced per record
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return array_response([shipment_view(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# accept (TENDERED -> ACCEPTED) — OCC, FK, sizing gates
# ---------------------------------------------------------------------------
@bp.route("/shipments/<sid>/accept", methods=["POST"])
def accept_shipment(sid):
    _uid, role = authenticate()
    require_role(role, {"Carrier"})
    shipment = get_shipment_or_404(sid)

    body = get_body(request)
    reefer_unit_id = as_string(require(body, "reefer_unit_id"), "reefer_unit_id")
    expected_version = as_int(
        require(body, "expected_shipment_version"), "expected_shipment_version"
    )

    # FK existence (priority 4)
    unit = store.reefer_units.get(reefer_unit_id)
    if unit is None:
        raise err("ERR_FK_NOT_FOUND", "reefer_unit_id does not resolve to a reefer unit")

    # state legality (priority 5)
    if shipment["status"] != "TENDERED":
        raise err("ERR_INVALID_STATE", "Shipment is not TENDERED")

    # business: must have >= 1 compartment, unit availability/ownership/sizing
    comps = _compartments_of(sid)
    if len(comps) < 1:
        raise err("ERR_INVALID_STATE", "Shipment has no compartments")

    # unit must belong to the shipment's carrier and be AVAILABLE
    if unit["carrier_id"] != shipment["carrier_id"]:
        raise err("ERR_FK_NOT_FOUND", "reefer unit does not belong to the shipment carrier")
    if unit["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Named reefer unit is not AVAILABLE")

    # unit sizing gate (priority 10)
    if unit["compartment_count"] < len(comps):
        raise err("ERR_UNIT_TOO_SMALL", "Reefer unit has fewer compartments than the shipment requires")

    # OCC — final gate (priority 19)
    if expected_version != shipment["version"]:
        raise err("ERR_STALE_VERSION", "expected_shipment_version does not match current version")

    # commit
    shipment["status"] = "ACCEPTED"
    shipment["reefer_unit_id"] = unit["id"]
    unit["status"] = "ASSIGNED"
    touch(unit)
    touch(shipment)  # version increments by 1 on accept
    return object_response(shipment_view(shipment), 200)


# ---------------------------------------------------------------------------
# reject (TENDERED -> REJECTED)
# ---------------------------------------------------------------------------
@bp.route("/shipments/<sid>/reject", methods=["POST"])
def reject_shipment(sid):
    _uid, role = authenticate()
    require_role(role, {"Carrier"})
    shipment = get_shipment_or_404(sid)
    if shipment["status"] != "TENDERED":
        raise err("ERR_INVALID_STATE", "Shipment is not TENDERED")
    shipment["status"] = "REJECTED"
    touch(shipment)
    return object_response(shipment_view(shipment), 200)


# ---------------------------------------------------------------------------
# precool-verify (ACCEPTED -> PRECOOLED)
# ---------------------------------------------------------------------------
@bp.route("/shipments/<sid>/precool-verify", methods=["POST"])
def precool_verify(sid):
    _uid, role = authenticate()
    require_role(role, {"Carrier"})
    shipment = get_shipment_or_404(sid)
    if shipment["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Shipment is not ACCEPTED")

    comps = _compartments_of(sid)
    for comp in comps:
        if not compartment_has_inband_precool(comp):
            raise err(
                "ERR_PRECOOL_INCOMPLETE",
                "A compartment lacks an in-band PRECOOL reading",
            )

    shipment["precool_verified"] = True
    shipment["status"] = "PRECOOLED"
    touch(shipment)
    return object_response(shipment_view(shipment), 200)


# ---------------------------------------------------------------------------
# dispatch (PRECOOLED -> IN_TRANSIT) — FSMA / sanitary / sanitation gates
# ---------------------------------------------------------------------------
@bp.route("/shipments/<sid>/dispatch", methods=["POST"])
def dispatch_shipment(sid):
    _uid, role = authenticate()
    require_role(role, {"Carrier"})
    shipment = get_shipment_or_404(sid)
    if shipment["status"] != "PRECOOLED":
        raise err("ERR_INVALID_STATE", "Shipment is not PRECOOLED")
    if not shipment["precool_verified"]:
        raise err("ERR_INVALID_STATE", "Shipment is not precool-verified")

    carrier = store.carriers.get(shipment["carrier_id"])

    # gate 1: regulated lane requires FSMA registration (priority 6)
    if _lane_regulated_any(sid) and not (carrier and carrier["fsma_registered"]):
        raise err("ERR_FSMA_NOT_REGISTERED", "Carrier is not FSMA-registered for a regulated lane")

    # gate 2: FOOD/PHARMA cargo requires current sanitary training (priority 7)
    if shipment["cargo_class"] in ("FOOD", "PHARMA") and not (
        carrier and carrier["sanitary_training_current"]
    ):
        raise err("ERR_SANITARY_TRAINING_LAPSED", "Carrier sanitary training is not current")

    # gate 3: assigned unit must have a documented washout (priority 8)
    unit = store.reefer_units.get(shipment["reefer_unit_id"])
    if unit is None or unit.get("last_sanitation_at") is None:
        raise err("ERR_SANITATION_UNDOCUMENTED", "Assigned reefer unit has no documented sanitation")

    # commit
    shipment["status"] = "IN_TRANSIT"
    shipment["_in_transit_anchor"] = store.now()  # offset_min = 0 anchor
    unit["status"] = "IN_TRANSIT"
    touch(unit)
    touch(shipment)
    return object_response(shipment_view(shipment), 200)


# ---------------------------------------------------------------------------
# deliver (IN_TRANSIT -> DELIVERED) — driver
# ---------------------------------------------------------------------------
@bp.route("/shipments/<sid>/deliver", methods=["POST"])
def deliver_shipment(sid):
    _uid, role = authenticate()
    require_role(role, {"Driver"})
    shipment = get_shipment_or_404(sid)
    if shipment["status"] != "IN_TRANSIT":
        raise err("ERR_INVALID_STATE", "Shipment is not IN_TRANSIT")

    # every DELIVERY stop must be CLOSED
    for s in store.stop_events.values():
        if s["shipment_id"] == sid and s["kind"] == "DELIVERY" and s["status"] != "CLOSED":
            raise err("ERR_INVALID_STATE", "A DELIVERY stop is not CLOSED")

    # finalize degree-minutes, impairment, posture
    finalize_on_deliver(shipment)
    shipment["status"] = "DELIVERED"

    # release the reefer unit
    unit = store.reefer_units.get(shipment["reefer_unit_id"])
    if unit is not None and unit["status"] == "IN_TRANSIT":
        unit["status"] = "AVAILABLE"
        touch(unit)

    touch(shipment)
    return object_response(shipment_view(shipment), 200)


# ---------------------------------------------------------------------------
# cancel (ACCEPTED|PRECOOLED -> CANCELLED) — shipper, ownership enforced
# ---------------------------------------------------------------------------
@bp.route("/shipments/<sid>/cancel", methods=["POST"])
def cancel_shipment(sid):
    uid, role = authenticate()
    require_role(role, {"Shipper"})
    shipment = get_shipment_or_404(sid)

    if shipment["status"] not in ("ACCEPTED", "PRECOOLED"):
        raise err("ERR_INVALID_STATE", "Shipment cannot be cancelled from its current state")

    # ownership: caller's X-User-ID must match shipper_user_id
    if uid != shipment["shipper_user_id"]:
        raise err("ERR_FORBIDDEN_ROLE", "Caller does not own this shipment")

    # release reefer unit
    unit = store.reefer_units.get(shipment["reefer_unit_id"])
    if unit is not None and unit["status"] == "ASSIGNED":
        unit["status"] = "AVAILABLE"
        touch(unit)

    shipment["status"] = "CANCELLED"
    shipment["reefer_unit_id"] = None
    touch(shipment)
    return object_response(shipment_view(shipment), 200)


# ---------------------------------------------------------------------------
# integrity-report (computed read)
# ---------------------------------------------------------------------------
@bp.route("/shipments/<sid>/integrity-report", methods=["GET"])
def get_integrity_report(sid):
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "ComplianceOfficer", "PlatformAdmin"})
    shipment = get_shipment_or_404(sid)
    return object_response(integrity_report(shipment), 200)
