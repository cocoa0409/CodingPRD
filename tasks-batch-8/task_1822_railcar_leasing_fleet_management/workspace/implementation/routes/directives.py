"""Compliance directives (PRD 3.11): announce and promote with cascade."""
from flask import Blueprint, request

import domain
from envelope import ok, ok_list
from errors import ApiError, invalid_state, not_found, validation
from http_util import CAR_TYPES, get_body, parse_pagination, require_roles, v_date, v_int, v_str
from store import db, new_entity, today, touch

bp_directives = Blueprint("directives", __name__)

ROLES = (
    "SystemAdmin", "LeaseAdmin", "FleetPlanner", "MaintenanceController",
    "BillingAnalyst", "ComplianceOfficer",
)


def _load_directive(directive_id):
    d = db.directives.get(directive_id)
    if d is None:
        raise not_found("ERR_DIRECTIVE_NOT_FOUND", f"Compliance directive {directive_id} not found")
    return d


@bp_directives.route("/compliance-directives", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_directive():
    body = get_body()
    code = v_str(body, "directive_code")
    description = v_str(body, "description")
    types = body.get("applies_to_car_types")
    if not isinstance(types, list) or len(types) == 0:
        raise validation("applies_to_car_types must be a non-empty array")
    for t in types:
        if t not in CAR_TYPES:
            raise validation(f"applies_to_car_types contains invalid car type: {t}")
    deadline = v_date(body, "retrofit_deadline")
    grace = v_int(body, "grace_days", required=False, min=0)
    if grace is None:
        grace = 30
    daily = v_int(body, "daily_penalty_cents", min=1)
    cap = v_int(body, "penalty_cap_cents", min=1)

    if any(d["directive_code"] == code for d in db.directives.values()):
        raise ApiError(
            "ERR_DUPLICATE_DIRECTIVE_CODE", 409,
            f"directive_code {code} already exists",
        )

    d = new_entity(
        {
            "directive_code": code,
            "description": description,
            "applies_to_car_types": list(types),
            "retrofit_deadline": deadline,
            "grace_days": grace,
            "daily_penalty_cents": daily,
            "penalty_cap_cents": cap,
            "effective_date": None,
            "status": "ANNOUNCED",
        }
    )
    db.directives[d["id"]] = d
    # announcement side effect: covered cars lacking a CERTIFIED retrofit
    # become RETROFIT_DUE (unless already NON_COMPLIANT)
    for car in db.railcars.values():
        if car["car_type"] in d["applies_to_car_types"]:
            domain.recompute_posture(car)
    return ok(domain.serialize_directive(d), status=201)


@bp_directives.route("/compliance-directives", methods=["GET"])
@require_roles(*ROLES)
def list_directives():
    limit, offset = parse_pagination()
    items = sorted(db.directives.values(), key=lambda d: (d["created_at"], d["_created_seq"]))
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_directive(d) for d in page], limit, offset, total)


@bp_directives.route("/compliance-directives/<directive_id>", methods=["GET"])
@require_roles(*ROLES)
def get_directive(directive_id):
    return ok(domain.serialize_directive(_load_directive(directive_id)))


@bp_directives.route("/compliance-directives/<directive_id>/promote", methods=["POST"])
@require_roles("ComplianceOfficer")
def promote_directive(directive_id):
    d = _load_directive(directive_id)
    if d["status"] != "ANNOUNCED":
        raise invalid_state(f"Directive in status {d['status']} cannot be promoted")
    d["status"] = "EFFECTIVE"
    d["effective_date"] = today()
    touch(d)
    # hop 1: covered cars without a CERTIFIED retrofit -> NON_COMPLIANT
    affected = [
        car
        for car in db.railcars.values()
        if car["car_type"] in d["applies_to_car_types"]
        and not domain._has_certified_retrofit(car["id"], d["id"])
    ]
    for car in affected:
        domain.recompute_posture(car)
    # hop 2: SCHEDULED assignments on those cars -> CANCELLED (DIRECTIVE_EFFECTIVE)
    affected_ids = {car["id"] for car in affected}
    for a in db.assignments.values():
        if a["railcar_id"] in affected_ids and a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            a["cancellation_reason"] = "DIRECTIVE_EFFECTIVE"
            touch(a)
    return ok(domain.serialize_directive(d))
