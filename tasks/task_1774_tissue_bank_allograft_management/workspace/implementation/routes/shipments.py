"""Shipments: receipt, acceptance, rejection (PRD §3.2)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_SUPPLIER_NOT_FOUND,
    ERR_FREEZER_NOT_FOUND,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_DUPLICATE_VALUE,
    ERR_SUPPLIER_NOT_QUALIFIED,
    ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED,
    ERR_INVENTORY_VALUE_CAP_EXCEEDED,
    ERR_FREEZER_CAPACITY_EXCEEDED,
    ERR_SHIPMENT_NOT_RECEIVED,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from services import domain
from util import fmt_dt
from validate import get_body, req_str, MISSING

bp = Blueprint("shipments", __name__)

ANY = ALL_ROLES


def _get_shipment(shipment_id: str) -> dict:
    shipment = db["shipments"].get(shipment_id)
    if shipment is None:
        raise_error(ERR_SHIPMENT_NOT_FOUND, f"shipment {shipment_id} does not exist")
    return shipment


def _validate_manifest(items_raw):
    """Request-shape validation of the manifest; returns normalized item dicts."""
    if not isinstance(items_raw, list) or len(items_raw) < 1:
        raise_error(ERR_INVALID_REQUEST, "items must be a non-empty array")
    items = []
    for i, line in enumerate(items_raw):
        if not isinstance(line, dict):
            raise_error(ERR_INVALID_REQUEST, f"items[{i}] must be an object")
        tissue_type = line.get("tissue_type", MISSING)
        if not isinstance(tissue_type, str) or tissue_type not in domain.TISSUE_TYPES:
            raise_error(ERR_INVALID_REQUEST, f"items[{i}].tissue_type must be one of {sorted(domain.TISSUE_TYPES)}")
        lot_number = line.get("lot_number", MISSING)
        if not isinstance(lot_number, str) or not lot_number:
            raise_error(ERR_INVALID_REQUEST, f"items[{i}].lot_number must be a non-empty string")
        serial_number = line.get("serial_number", MISSING)
        if not isinstance(serial_number, str) or not serial_number:
            raise_error(ERR_INVALID_REQUEST, f"items[{i}].serial_number must be a non-empty string")
        unit_cost_cents = line.get("unit_cost_cents", MISSING)
        if isinstance(unit_cost_cents, bool) or not isinstance(unit_cost_cents, int) or unit_cost_cents < 0:
            raise_error(ERR_INVALID_REQUEST, f"items[{i}].unit_cost_cents must be an integer >= 0")
        expiration_raw = line.get("expiration_at", MISSING)
        try:
            from util import parse_dt
            expiration_dt = parse_dt(expiration_raw)
        except (ValueError, TypeError):
            raise_error(ERR_INVALID_REQUEST, f"items[{i}].expiration_at must be an ISO 8601 datetime string")
        criticality_tier = line.get("criticality_tier", MISSING)
        if not isinstance(criticality_tier, str) or criticality_tier not in domain.CRITICALITY_TIERS:
            raise_error(ERR_INVALID_REQUEST, f"items[{i}].criticality_tier must be one of {sorted(domain.CRITICALITY_TIERS)}")
        # System-managed keys smuggled into the manifest (id, status, ...) are ignored.
        items.append({
            "tissue_type": tissue_type,
            "lot_number": lot_number,
            "serial_number": serial_number,
            "unit_cost_cents": unit_cost_cents,
            "expiration_at": fmt_dt(expiration_dt),
            "criticality_tier": criticality_tier,
            "_expiration_dt": expiration_dt,
        })
    return items


@bp.route("/tissue-bank/shipments", methods=["POST"])
def create_shipment():
    require_roles({"TissueBankCoordinator"})
    body = get_body()
    # request shape first (rung 3.4)
    supplier_id = req_str(body, "supplier_id")
    freezer_id = req_str(body, "freezer_id")
    items = _validate_manifest(body.get("items", MISSING))
    # body-reference existence (§2.6 vocabulary)
    supplier = db["suppliers"].get(supplier_id)
    if supplier is None:
        raise_error(ERR_SUPPLIER_NOT_FOUND, f"supplier {supplier_id} does not exist")
    freezer = db["freezers"].get(freezer_id)
    if freezer is None:
        raise_error(ERR_FREEZER_NOT_FOUND, f"freezer {freezer_id} does not exist")
    # compliance gate: supplier must be QUALIFIED at receipt time
    if supplier["status"] != "QUALIFIED":
        raise_error(ERR_SUPPLIER_NOT_QUALIFIED, f"supplier status is {supplier['status']}, not QUALIFIED")
    # structural: serial_number unique within the manifest
    serials = [it["serial_number"] for it in items]
    if len(set(serials)) != len(serials):
        raise_error(ERR_DUPLICATE_VALUE, "serial_number must be unique within the shipment manifest")
    # structural: freezer admits the full manifest under effective_capacity
    if not domain.freezer_admits(freezer, len(items)):
        raise_error(
            ERR_FREEZER_CAPACITY_EXCEEDED,
            f"freezer {freezer['name']} cannot admit {len(items)} additional unit(s)",
        )
    now = domain.CLOCK.now()
    shipment = {
        "supplier_id": supplier["id"],
        "freezer_id": freezer["id"],
        "items": items,
        "status": "RECEIVED",
        "received_at": fmt_dt(now),
        "total_declared_value_cents": sum(it["unit_cost_cents"] for it in items),
        "unit_count": len(items),
        "accepted_at": None,
        "rejection_reason": None,
        "_received_dt": now,
    }
    domain.stamp_new(shipment)
    db["shipments"][shipment["id"]] = shipment
    # mint one QUARANTINED TissueUnit per manifest line
    for it in items:
        unit = {
            "shipment_id": shipment["id"],
            "supplier_id": supplier["id"],
            "freezer_id": freezer["id"],
            "tissue_type": it["tissue_type"],
            "lot_number": it["lot_number"],
            "serial_number": it["serial_number"],
            "unit_cost_cents": it["unit_cost_cents"],
            "criticality_tier": it["criticality_tier"],
            "expiration_at": it["expiration_at"],
            "received_at": shipment["received_at"],
            "status": "QUARANTINED",
            "hold_reason": "NONE",
            "recall_flag": False,
            "implanted_case_id": None,
            "implanted_at": None,
            "_expiration_dt": it["_expiration_dt"],
            "_received_dt": now,
            "_issued_via_case_id": None,
        }
        domain.stamp_new(unit)
        db["units"][unit["id"]] = unit
    return success_object(domain.shipment_json(shipment), status=201)


@bp.route("/tissue-bank/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    require_roles(ANY)
    return success_object(domain.shipment_json(_get_shipment(shipment_id)))


@bp.route("/tissue-bank/shipments/<shipment_id>/accept", methods=["POST"])
def accept_shipment(shipment_id):
    require_roles({"TissueBankCoordinator"})
    shipment = _get_shipment(shipment_id)
    # state rung
    if shipment["status"] != "RECEIVED":
        raise_error(ERR_SHIPMENT_NOT_RECEIVED, f"shipment status is {shipment['status']}, not RECEIVED")
    # compliance rung: re-verified at accept time
    supplier = db["suppliers"][shipment["supplier_id"]]
    if supplier["status"] != "QUALIFIED":
        raise_error(ERR_SUPPLIER_NOT_QUALIFIED, f"supplier status is {supplier['status']}, not QUALIFIED")
    if not domain.has_required_doc_coverage(supplier["id"]):
        raise_error(
            ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED,
            "supplier no longer holds VERIFIED AATB_ACCREDITATION and FDA_REGISTRATION documents",
        )
    # fiscal rung (evaluated last): projected WEIGHTED_AVERAGE valuation per
    # tissue_type in this shipment that has an ACTIVE par-level policy
    units_of_shipment = [u for u in db["units"].values() if u["shipment_id"] == shipment["id"]]
    shipment_types = {u["tissue_type"] for u in units_of_shipment}
    for tissue_type in sorted(shipment_types):
        policy = next(
            (p for p in db["policies"].values()
             if p["tissue_type"] == tissue_type and p["status"] == "ACTIVE"),
            None,
        )
        if policy is None:
            continue  # tissue types without an ACTIVE policy are uncapped
        incoming = [u for u in units_of_shipment if u["tissue_type"] == tissue_type]
        projected = domain.projected_wa_total_with(tissue_type, incoming)
        if projected > policy["max_inventory_value_cents"]:
            raise_error(
                ERR_INVENTORY_VALUE_CAP_EXCEEDED,
                f"projected valuation {projected} for {tissue_type} exceeds policy cap {policy['max_inventory_value_cents']}",
            )
    shipment["status"] = "ACCEPTED"
    shipment["accepted_at"] = fmt_dt(domain.CLOCK.now())
    domain.touch(shipment)
    return success_object(domain.shipment_json(shipment))


@bp.route("/tissue-bank/shipments/<shipment_id>/reject", methods=["POST"])
def reject_shipment(shipment_id):
    caller = require_roles({"TissueBankCoordinator"})
    shipment = _get_shipment(shipment_id)
    # request shape is pinned BEFORE the state precondition (rung 3.4 before 4)
    body = get_body()
    rejection_reason = req_str(body, "rejection_reason", min_len=10)
    if shipment["status"] != "RECEIVED":
        raise_error(ERR_SHIPMENT_NOT_RECEIVED, f"shipment status is {shipment['status']}, not RECEIVED")
    shipment["status"] = "REJECTED"
    shipment["rejection_reason"] = rejection_reason
    domain.touch(shipment)
    units = sorted(
        (u for u in db["units"].values() if u["shipment_id"] == shipment["id"]),
        key=lambda u: u["_seq"],
    )
    for u in units:
        u["status"] = "RETURNED_TO_SUPPLIER"
        u["hold_reason"] = "NONE"
        domain.touch(u)
        domain.create_disposition(u, "RETURNED_TO_SUPPLIER", rejection_reason, caller.user_id)
    return success_object(domain.shipment_json(shipment))
