"""Violations, remediation orders, and the enforcement cascade (Cascade B)."""

from flask import Blueprint

from db import base_fields, db, iso, iso_now, now, to_dt, touch
from errors import fail
from middleware import ALL_ROLES, require
from response import list_response, object_response
from services import calc, engine
from validation import (body, fk, lookup, opt_str, pagination, paginate,
                        query_filters, req_dt, req_enum, req_str)

bp = Blueprint("enforcement", __name__)

_VIOLATION_RESOLUTIONS = ("REMEDIATED", "CLOSED_UNRESOLVED")
_ORDER_RESOLUTIONS = ("SATISFIED", "DEFAULTED")


def _community_of_violation(violation):
    prop = db.properties.get(violation["property_id"])
    return db.communities.get(prop["community_id"]) if prop else None


# ----------------------------------------------------------------- Violation


@bp.post("/violations")
def create_violation():
    require("FloodplainAdministrator")
    data = body()
    property_id = fk(data, "property_id", "property")
    violation_type = req_enum(data, "violation_type", calc.VIOLATION_TYPES)
    severity = req_enum(data, "severity", calc.SEVERITIES)
    structure_id = fk(data, "structure_id", "structure", required=False)
    permit_id = fk(data, "permit_id", "permit", required=False)

    prop = lookup("property", property_id)
    structure = lookup("structure", structure_id) if structure_id else None
    if permit_id:
        lookup("permit", permit_id)

    row = base_fields()
    row.update({
        "property_id": property_id,
        "structure_id": structure_id,
        "permit_id": permit_id,
        "violation_type": violation_type,
        "severity": severity,
        "status": "OPEN",
        "sanction_points_contributed": calc.SEVERITY_WEIGHT[severity],
        "opened_at": iso_now(),
        "resolved_at": None,
    })
    db.violations[row["id"]] = row

    community = db.communities.get(prop["community_id"])
    if community is not None:
        engine.apply_sanction(community)

    if violation_type == "ELEVATION_DEFICIENT" and structure is not None:
        if structure["compliance_status"] in ("COMPLIANT", "PENDING_CERTIFICATE"):
            structure["compliance_status"] = "NON_COMPLIANT"
            touch(structure)

    return object_response(row, 201)


@bp.get("/violations/<violation_id>")
def read_violation(violation_id):
    require(*ALL_ROLES)
    return object_response(lookup("violation", violation_id))


@bp.get("/violations")
def list_violations():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.violations.values()), {
        "property_id": ("property_id", None),
        "structure_id": ("structure_id", None),
        "permit_id": ("permit_id", None),
        "status": ("status", None),
        "severity": ("severity", None),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/violations/<violation_id>/resolve")
def resolve_violation(violation_id):
    require("FloodplainAdministrator")
    violation = lookup("violation", violation_id)
    data = body()
    resolution = req_enum(data, "resolution", _VIOLATION_RESOLUTIONS)
    opt_str(data, "resolution_note")

    if violation["status"] not in calc.ACTIVE_VIOLATION_STATUSES:
        fail("ERR_VIOLATION_NOT_ACTIONABLE")

    community = _community_of_violation(violation)
    if resolution == "REMEDIATED":
        engine.remediate_violation(violation, community)
    else:
        violation["status"] = "CLOSED_UNRESOLVED"
        violation["resolved_at"] = iso_now()
        violation["sanction_points_contributed"] = 0
        touch(violation)
        if community is not None:
            engine.apply_sanction(community)
    return object_response(violation)


# ----------------------------------------------------------- RemediationOrder


@bp.post("/remediation-orders")
def create_order():
    require("FloodplainAdministrator")
    data = body()
    violation_id = fk(data, "violation_id", "violation")
    required_action = req_str(data, "required_action")
    deadline_at = req_dt(data, "deadline_at")
    violation = lookup("violation", violation_id)

    # The state gate deliberately admits ORDER_ISSUED (PRD 2.8 step 9).
    if violation["status"] not in ("OPEN", "ORDER_ISSUED"):
        fail("ERR_VIOLATION_NOT_ACTIONABLE")
    if deadline_at <= now():
        fail("ERR_DEADLINE_NOT_IN_FUTURE")
    for existing in engine.orders_of(violation_id):
        if existing["status"] in ("ISSUED", "EXTENDED"):
            fail("ERR_ORDER_ALREADY_ACTIVE")

    row = base_fields()
    row.update({
        "violation_id": violation_id,
        "required_action": required_action,
        "deadline_at": iso(deadline_at),
        "extension_count": 0,
        "status": "ISSUED",
        "resolved_at": None,
    })
    db.orders[row["id"]] = row

    if violation["status"] == "OPEN":
        violation["status"] = "ORDER_ISSUED"
        touch(violation)
    community = _community_of_violation(violation)
    if community is not None:
        engine.apply_sanction(community)
    return object_response(row, 201)


@bp.get("/remediation-orders/<order_id>")
def read_order(order_id):
    require(*ALL_ROLES)
    return object_response(lookup("order", order_id))


@bp.get("/remediation-orders")
def list_orders():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.orders.values()), {
        "violation_id": ("violation_id", None),
        "status": ("status", None),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/remediation-orders/<order_id>/extend")
def extend_order(order_id):
    require("FloodplainAdministrator")
    order = lookup("order", order_id)
    data = body()
    deadline_at = req_dt(data, "deadline_at")

    if order["status"] not in ("ISSUED", "EXTENDED"):
        fail("ERR_ORDER_NOT_ACTIONABLE")
    if order["extension_count"] >= calc.MAX_ORDER_EXTENSIONS:
        fail("ERR_EXTENSION_LIMIT_EXCEEDED")
    if deadline_at <= to_dt(order["deadline_at"]):
        fail("ERR_EXTENSION_LIMIT_EXCEEDED")

    order["status"] = "EXTENDED"
    order["extension_count"] += 1
    order["deadline_at"] = iso(deadline_at)
    touch(order)
    return object_response(order)


@bp.post("/remediation-orders/<order_id>/resolve")
def resolve_order(order_id):
    require("FloodplainAdministrator")
    order = lookup("order", order_id)
    data = body()
    resolution = req_enum(data, "resolution", _ORDER_RESOLUTIONS)

    if order["status"] not in ("ISSUED", "EXTENDED"):
        fail("ERR_ORDER_NOT_ACTIONABLE")
    if resolution == "DEFAULTED" and now() <= to_dt(order["deadline_at"]):
        fail("ERR_ORDER_DEADLINE_NOT_PASSED")

    violation = db.violations.get(order["violation_id"])
    community = _community_of_violation(violation) if violation else None

    if resolution == "SATISFIED":
        order["status"] = "SATISFIED"
        order["resolved_at"] = iso_now()
        touch(order)
        if violation is not None and violation["status"] in ("OPEN", "ORDER_ISSUED"):
            engine.remediate_violation(violation, community)
        elif community is not None:
            engine.apply_sanction(community)
        return object_response(order)

    # Cascade B — hop 1
    order["status"] = "DEFAULTED"
    order["resolved_at"] = iso_now()
    touch(order)

    if violation is not None and violation["status"] == "ORDER_ISSUED":
        # hop 2
        violation["status"] = "ESCALATED"
        touch(violation)
        # hop 3a (and hop 4 inside, when the posture becomes SUSPENDED)
        if community is not None:
            engine.apply_sanction(community)
        # hop 3b
        permit = db.permits.get(violation["permit_id"]) if violation["permit_id"] else None
        if permit is not None and permit["status"] in ("APPROVED", "ISSUED"):
            permit["status"] = "REVOKED"
            touch(permit)
    elif community is not None:
        engine.apply_sanction(community)

    return object_response(order)
