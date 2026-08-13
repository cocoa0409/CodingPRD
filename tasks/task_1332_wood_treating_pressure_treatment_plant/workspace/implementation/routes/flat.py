"""Flat retrieval routes, FK reverse-reachability sub-resources, and filtered
list endpoints mounted under /treatment-plants (PRD sections 2.8 and 4)."""

from flask import Blueprint

from db import store, public
from middleware import authenticate, authorize
from response import success
from util import (
    resolve_cylinder, resolve_preservative, resolve_customer, resolve_charge,
    resolve_piece, resolve_cycle, resolve_assay, resolve_inspection,
    resolve_drip_log, resolve_warranty, resolve_slot, paginate, query_filter,
    query_bool, parse_query_ts,
)

bp = Blueprint("flat", __name__)

ROLES_CYL = ["PlantOperator", "LabTechnician", "QualityManager", "QualityAgencyInspector", "ComplianceOfficer"]
ROLES_PRES = ["LabTechnician", "PlantOperator", "QualityManager", "ComplianceOfficer"]
ROLES_CUST = ["AccountsReceivable", "PlantOperator", "QualityManager", "ComplianceOfficer"]
ROLES_CHARGE = ["PlantOperator", "LabTechnician", "QualityManager", "QualityAgencyInspector", "ComplianceOfficer", "AccountsReceivable"]
ROLES_CYCLE = ["PlantOperator", "LabTechnician", "QualityManager", "ComplianceOfficer"]
ROLES_ASSAY = ["LabTechnician", "QualityManager", "QualityAgencyInspector", "ComplianceOfficer", "PlantOperator"]
ROLES_INSP = ["QualityAgencyInspector", "ComplianceOfficer", "QualityManager", "PlantOperator", "LabTechnician"]
ROLES_DRIP = ["PlantOperator", "QualityManager", "QualityAgencyInspector", "ComplianceOfficer", "LabTechnician"]
ROLES_WARRANTY = ["PlantOperator", "QualityManager", "AccountsReceivable", "ComplianceOfficer", "QualityAgencyInspector"]
ROLES_SLOT = ["PlantOperator", "QualityManager", "ComplianceOfficer"]


# --- Flat single-resource GETs ---

@bp.route("/treatment-plants/cylinders/<cylinderId>", methods=["GET"])
def flat_get_cylinder(cylinderId):
    _, role = authenticate()
    authorize(role, ROLES_CYL)
    return success(public(resolve_cylinder(cylinderId)))


@bp.route("/treatment-plants/preservatives/<preservativeId>", methods=["GET"])
def flat_get_preservative(preservativeId):
    _, role = authenticate()
    authorize(role, ROLES_PRES)
    return success(public(resolve_preservative(preservativeId)))


@bp.route("/treatment-plants/customers/<customerId>", methods=["GET"])
def flat_get_customer(customerId):
    _, role = authenticate()
    authorize(role, ROLES_CUST)
    return success(public(resolve_customer(customerId)))


@bp.route("/treatment-plants/charges/<chargeId>", methods=["GET"])
def flat_get_charge(chargeId):
    _, role = authenticate()
    authorize(role, ROLES_CHARGE)
    return success(public(resolve_charge(chargeId)))


@bp.route("/treatment-plants/pieces/<pieceId>", methods=["GET"])
def flat_get_piece(pieceId):
    _, role = authenticate()
    authorize(role, ROLES_CYL)
    return success(public(resolve_piece(pieceId)))


@bp.route("/treatment-plants/cycles/<cycleId>", methods=["GET"])
def flat_get_cycle(cycleId):
    _, role = authenticate()
    authorize(role, ROLES_CYCLE)
    return success(public(resolve_cycle(cycleId)))


@bp.route("/treatment-plants/assays/<assayId>", methods=["GET"])
def flat_get_assay(assayId):
    _, role = authenticate()
    authorize(role, ROLES_ASSAY)
    return success(public(resolve_assay(assayId)))


@bp.route("/treatment-plants/inspections/<inspectionId>", methods=["GET"])
def flat_get_inspection(inspectionId):
    _, role = authenticate()
    authorize(role, ROLES_INSP)
    return success(public(resolve_inspection(inspectionId)))


@bp.route("/treatment-plants/drip-logs/<logId>", methods=["GET"])
def flat_get_drip_log(logId):
    _, role = authenticate()
    authorize(role, ROLES_DRIP)
    return success(public(resolve_drip_log(logId)))


@bp.route("/treatment-plants/warranties/<warrantyId>", methods=["GET"])
def flat_get_warranty(warrantyId):
    _, role = authenticate()
    authorize(role, ROLES_WARRANTY)
    return success(public(resolve_warranty(warrantyId)))


@bp.route("/treatment-plants/slots/<slotId>", methods=["GET"])
def flat_get_slot(slotId):
    _, role = authenticate()
    authorize(role, ROLES_SLOT)
    return success(public(resolve_slot(slotId)))


# --- FK reverse-reachability sub-resources ---

@bp.route("/treatment-plants/customers/<customerId>/charges", methods=["GET"])
def flat_customer_charges(customerId):
    _, role = authenticate()
    authorize(role, ROLES_CUST)
    cust = resolve_customer(customerId)
    items = [c for c in store.charges.values() if c.get("customer_id") == cust["id"]]
    status = query_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/preservatives/<preservativeId>/cycles", methods=["GET"])
def flat_preservative_cycles(preservativeId):
    _, role = authenticate()
    authorize(role, ROLES_PRES)
    pres = resolve_preservative(preservativeId)
    items = [c for c in store.cycles.values() if c["preservative_id"] == pres["id"]]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/cycles/<cycleId>/retention-assays", methods=["GET"])
def flat_cycle_assays(cycleId):
    _, role = authenticate()
    authorize(role, ROLES_ASSAY)
    cycle = resolve_cycle(cycleId)
    items = [a for a in store.assays.values() if a["cycle_id"] == cycle["id"]]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/charges/<chargeId>/slots", methods=["GET"])
def flat_charge_slots(chargeId):
    _, role = authenticate()
    authorize(role, ROLES_SLOT)
    charge = resolve_charge(chargeId)
    items = [s for s in store.slots.values() if s.get("charge_id") == charge["id"]]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/cylinders/<cylinderId>/charges", methods=["GET"])
def flat_cylinder_charges(cylinderId):
    _, role = authenticate()
    authorize(role, ROLES_CYL)
    cyl = resolve_cylinder(cylinderId)
    items = [c for c in store.charges.values() if c["cylinder_id"] == cyl["id"]]
    status = query_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/charges/<chargeId>/pieces", methods=["GET"])
def flat_charge_pieces(chargeId):
    _, role = authenticate()
    authorize(role, ROLES_CYL)
    charge = resolve_charge(chargeId)
    items = [p for p in store.pieces.values() if p["charge_id"] == charge["id"]]
    status = query_filter("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/charges/<chargeId>/cycles", methods=["GET"])
def flat_charge_cycles(chargeId):
    _, role = authenticate()
    authorize(role, ROLES_CYCLE)
    charge = resolve_charge(chargeId)
    items = [c for c in store.cycles.values() if c["charge_id"] == charge["id"]]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/charges/<chargeId>/retention-assays", methods=["GET"])
def flat_charge_assays(chargeId):
    _, role = authenticate()
    authorize(role, ROLES_ASSAY)
    charge = resolve_charge(chargeId)
    items = [a for a in store.assays.values() if a["charge_id"] == charge["id"]]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/charges/<chargeId>/drip-pad-logs", methods=["GET"])
def flat_charge_drip_logs(chargeId):
    _, role = authenticate()
    authorize(role, ROLES_DRIP)
    charge = resolve_charge(chargeId)
    items = [l for l in store.drip_logs.values() if l["charge_id"] == charge["id"]]
    breach = query_bool("containment_breach")
    if breach is not None:
        items = [l for l in items if l["containment_breach"] == breach]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/charges/<chargeId>/warranty-registrations", methods=["GET"])
def flat_charge_warranties(chargeId):
    _, role = authenticate()
    authorize(role, ROLES_WARRANTY)
    charge = resolve_charge(chargeId)
    items = [w for w in store.warranties.values() if w["charge_id"] == charge["id"]]
    status = query_filter("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/cylinders/<cylinderId>/slots", methods=["GET"])
def flat_cylinder_slots(cylinderId):
    _, role = authenticate()
    authorize(role, ROLES_SLOT)
    cyl = resolve_cylinder(cylinderId)
    items = [s for s in store.slots.values() if s["cylinder_id"] == cyl["id"]]
    kind = query_filter("slot_kind")
    if kind is not None:
        items = [s for s in items if s["slot_kind"] == kind]
    from_dt = parse_query_ts(query_filter("from_iso"), "from_iso")
    to_dt = parse_query_ts(query_filter("to_iso"), "to_iso")
    if from_dt is not None:
        items = [s for s in items if s["_start_dt"] >= from_dt]
    if to_dt is not None:
        items = [s for s in items if s["_end_dt"] <= to_dt]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


# --- Filtered-list GETs ---

@bp.route("/treatment-plants/cylinders", methods=["GET"])
def flat_list_cylinders():
    _, role = authenticate()
    authorize(role, ROLES_CYL)
    items = list(store.cylinders.values())
    for param in ("status", "plant_id"):
        value = query_filter(param)
        if value is not None:
            items = [c for c in items if c.get(param) == value]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/preservatives", methods=["GET"])
def flat_list_preservatives():
    _, role = authenticate()
    authorize(role, ROLES_PRES)
    items = list(store.preservatives.values())
    for param in ("status", "plant_id"):
        value = query_filter(param)
        if value is not None:
            items = [p for p in items if p.get(param) == value]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/inspections", methods=["GET"])
def flat_list_inspections():
    _, role = authenticate()
    authorize(role, ROLES_INSP)
    items = list(store.inspections.values())
    for param in ("status", "severity", "plant_id"):
        value = query_filter(param)
        if value is not None:
            items = [i for i in items if i.get(param) == value]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/charges", methods=["GET"])
def flat_list_charges():
    _, role = authenticate()
    authorize(role, ROLES_CHARGE)
    items = list(store.charges.values())
    for param in ("status", "use_category", "customer_id", "cylinder_id"):
        value = query_filter(param)
        if value is not None:
            items = [c for c in items if c.get(param) == value]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/pieces", methods=["GET"])
def flat_list_pieces():
    _, role = authenticate()
    authorize(role, ROLES_CYL)
    items = list(store.pieces.values())
    for param in ("status", "charge_id"):
        value = query_filter(param)
        if value is not None:
            items = [p for p in items if p.get(param) == value]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/cycles", methods=["GET"])
def flat_list_cycles():
    _, role = authenticate()
    authorize(role, ROLES_CYCLE)
    items = list(store.cycles.values())
    for param in ("status", "charge_id", "preservative_id"):
        value = query_filter(param)
        if value is not None:
            items = [c for c in items if c.get(param) == value]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/assays", methods=["GET"])
def flat_list_assays():
    _, role = authenticate()
    authorize(role, ROLES_ASSAY)
    items = list(store.assays.values())
    for param in ("charge_id", "cycle_id"):
        value = query_filter(param)
        if value is not None:
            items = [a for a in items if a.get(param) == value]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/drip-logs", methods=["GET"])
def flat_list_drip_logs():
    _, role = authenticate()
    authorize(role, ROLES_DRIP)
    items = list(store.drip_logs.values())
    charge_id = query_filter("charge_id")
    if charge_id is not None:
        items = [l for l in items if l["charge_id"] == charge_id]
    breach = query_bool("containment_breach")
    if breach is not None:
        items = [l for l in items if l["containment_breach"] == breach]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/warranties", methods=["GET"])
def flat_list_warranties():
    _, role = authenticate()
    authorize(role, ROLES_WARRANTY)
    items = list(store.warranties.values())
    for param in ("status", "charge_id"):
        value = query_filter(param)
        if value is not None:
            items = [w for w in items if w.get(param) == value]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/slots", methods=["GET"])
def flat_list_slots():
    _, role = authenticate()
    authorize(role, ROLES_SLOT)
    items = list(store.slots.values())
    for param in ("slot_kind", "cylinder_id", "charge_id"):
        value = query_filter(param)
        if value is not None:
            items = [s for s in items if s.get(param) == value]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)
