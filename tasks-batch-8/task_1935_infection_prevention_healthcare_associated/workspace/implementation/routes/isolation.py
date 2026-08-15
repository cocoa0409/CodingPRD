"""IsolationOrders and IsolationComplianceAudits."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ERR_AUDIT_ELEMENTS_INVALID,
    ERR_AUDIT_NOT_FOUND,
    ERR_DUPLICATE_ISOLATION_ORDER,
    ERR_INVALID_REQUEST,
    ERR_ISOLATION_ALREADY_DISCONTINUED,
    ERR_ISOLATION_ORDER_NOT_ACTIVE,
    ERR_ISOLATION_ORDER_NOT_FOUND,
    ERR_ISOLATION_ORDER_NOT_STARTABLE,
    ERR_PATIENT_NOT_ADMITTED,
    ERR_PATIENT_NOT_FOUND,
    raise_err,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import new_entity, recompute_posture, round1, touch
from services.serializers import audit_view, isolation_order_view
from util import clock
from validate import body, pagination_args, req_dt, req_enum, req_int

bp = Blueprint("isolation", __name__)

PRECAUTION_TYPES = {"CONTACT", "DROPLET", "AIRBORNE"}
COMPLIANCE_THRESHOLD_PCT = Decimal("90.0")


@bp.post("/api/isolation-orders")
def create_order():
    user_id, _ = require_roles(["InfectionPreventionist"])
    b = body()
    for f in ("patient_id", "precaution_type"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    patient_id = b.get("patient_id")
    if not isinstance(patient_id, str) or not patient_id:
        raise_err(ERR_INVALID_REQUEST, "patient_id must be a string")
    precaution_type = req_enum(b, "precaution_type", PRECAUTION_TYPES)

    patient = db.patients.get(patient_id)
    if patient is None:
        raise_err(ERR_PATIENT_NOT_FOUND, "patient id does not exist")
    if patient["status"] != "ADMITTED":
        raise_err(ERR_PATIENT_NOT_ADMITTED, "patient must be ADMITTED")

    for o in db.isolation_orders.values():
        if (
            o["patient_id"] == patient_id
            and o["precaution_type"] == precaution_type
            and o["status"] in ("ORDERED", "ACTIVE")
        ):
            raise_err(ERR_DUPLICATE_ISOLATION_ORDER, "an open order already exists for (patient_id, precaution_type)")

    order = new_entity({
        "patient_id": patient_id,
        "unit_id": patient["current_unit_id"],
        "precaution_type": precaution_type,
        "ordered_by_user_id": user_id,
        "ordered_at": clock.get(),
        "started_at": None,
        "discontinued_at": None,
        "status": "ORDERED",
        "compliance_status": "NOT_AUDITED",
    })
    db.isolation_orders[order["id"]] = order
    return success_object(isolation_order_view(order), 201)


@bp.get("/api/isolation-orders")
def list_orders():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    patient_id = request.args.get("patient_id")
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")

    def _match(o):
        if patient_id is not None and o["patient_id"] != patient_id:
            return False
        if unit_id is not None and o["unit_id"] != unit_id:
            return False
        if status is not None and o["status"] != status:
            return False
        return True

    items = [o for o in db.isolation_orders.values() if _match(o)]
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([isolation_order_view(o) for o in page], total, limit, offset)


@bp.get("/api/isolation-orders/<oid>")
def get_order(oid):
    require_roles(ALL_ROLES)
    o = db.isolation_orders.get(oid)
    if o is None:
        raise_err(ERR_ISOLATION_ORDER_NOT_FOUND, "isolation order id does not exist")
    return success_object(isolation_order_view(o))


@bp.post("/api/isolation-orders/<oid>/start")
def start_order(oid):
    require_roles(["UnitNurseManager"])
    o = db.isolation_orders.get(oid)
    if o is None:
        raise_err(ERR_ISOLATION_ORDER_NOT_FOUND, "isolation order id does not exist")
    if o["status"] != "ORDERED":
        raise_err(ERR_ISOLATION_ORDER_NOT_STARTABLE, "start requires status ORDERED")
    o["status"] = "ACTIVE"
    o["started_at"] = clock.get()
    touch(o)
    return success_object(isolation_order_view(o))


@bp.post("/api/isolation-orders/<oid>/discontinue")
def discontinue_order(oid):
    require_roles(["UnitNurseManager"])
    o = db.isolation_orders.get(oid)
    if o is None:
        raise_err(ERR_ISOLATION_ORDER_NOT_FOUND, "isolation order id does not exist")
    if o["status"] not in ("ORDERED", "ACTIVE"):
        raise_err(ERR_ISOLATION_ALREADY_DISCONTINUED, "discontinue requires status ORDERED or ACTIVE")
    o["status"] = "DISCONTINUED"
    o["discontinued_at"] = clock.get()
    # compliance_status deliberately untouched — axes are independent.
    touch(o)
    return success_object(isolation_order_view(o))


# ---------------------------------------------------------------------------
# Compliance audits
# ---------------------------------------------------------------------------
@bp.post("/api/isolation-compliance-audits")
def create_audit():
    user_id, _ = require_roles(["UnitNurseManager"])
    b = body()
    for f in ("isolation_order_id", "observed_at", "elements_checked", "elements_passed"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    order_id = b.get("isolation_order_id")
    if not isinstance(order_id, str) or not order_id:
        raise_err(ERR_INVALID_REQUEST, "isolation_order_id must be a string")
    observed_at = req_dt(b, "observed_at")
    # schema ranges first
    elements_checked = req_int(b, "elements_checked", min_v=1)
    elements_passed = req_int(b, "elements_passed", min_v=0)

    order = db.isolation_orders.get(order_id)
    if order is None:
        raise_err(ERR_ISOLATION_ORDER_NOT_FOUND, "isolation order id does not exist")

    if order["status"] != "ACTIVE":
        raise_err(ERR_ISOLATION_ORDER_NOT_ACTIVE, "audit requires the isolation order to be ACTIVE")

    if elements_passed > elements_checked:
        raise_err(ERR_AUDIT_ELEMENTS_INVALID, "elements_passed must be <= elements_checked")

    pct = round1(Decimal(100) * Decimal(elements_passed) / Decimal(elements_checked))
    outcome = "COMPLIANT" if pct >= COMPLIANCE_THRESHOLD_PCT else "NON_COMPLIANT"

    audit = new_entity({
        "isolation_order_id": order_id,
        "auditor_user_id": user_id,
        "observed_at": observed_at,
        "elements_checked": elements_checked,
        "elements_passed": elements_passed,
        "compliance_pct": pct,
        "outcome": outcome,
    })
    db.isolation_compliance_audits[audit["id"]] = audit

    # Last-audit-wins on the order's compliance axis: latest by observed_at, tie by created_at.
    latest = None
    for a in db.isolation_compliance_audits.values():
        if a["isolation_order_id"] == order_id:
            if latest is None or (a["observed_at"], a["created_at"]) >= (latest["observed_at"], latest["created_at"]):
                latest = a
    if latest is not None:
        if order["compliance_status"] != latest["outcome"]:
            order["compliance_status"] = latest["outcome"]
            touch(order)

    # NON_COMPLIANT cascade: every non-compliant audit system-creates an ACTIVE CAP
    # for the order's unit (the trigger is the audit outcome, per scaffold side_effects).
    if outcome == "NON_COMPLIANT":
        cap = new_entity({
            "unit_id": order["unit_id"],
            "source_type": "ISOLATION_AUDIT",
            "source_ref_id": audit["id"],
            "description": "System-generated corrective action plan for non-compliant isolation audit",
            "due_date": observed_at + timedelta(days=14),
            "evidence_notes": None,
            "failure_count": 0,
            "created_by_user_id": "system",
            "verified_by_user_id": None,
            "status": "ACTIVE",
        })
        db.corrective_action_plans[cap["id"]] = cap
        recompute_posture(order["unit_id"])

    return success_object(audit_view(audit), 201)


@bp.get("/api/isolation-compliance-audits")
def list_audits():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    order_id = request.args.get("isolation_order_id")
    items = [a for a in db.isolation_compliance_audits.values() if order_id is None or a["isolation_order_id"] == order_id]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([audit_view(a) for a in page], total, limit, offset)


@bp.get("/api/isolation-compliance-audits/<aid>")
def get_audit(aid):
    require_roles(ALL_ROLES)
    a = db.isolation_compliance_audits.get(aid)
    if a is None:
        raise_err(ERR_AUDIT_NOT_FOUND, "isolation compliance audit id does not exist")
    return success_object(audit_view(a))
