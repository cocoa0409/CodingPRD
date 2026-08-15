"""Retrofit orders (PRD 3.11)."""
from flask import Blueprint, request

import domain
from envelope import ok, ok_list
from errors import ApiError, invalid_state, not_found
from http_util import get_body, parse_pagination, require_roles, v_date, v_str
from store import db, new_entity, today, touch

bp_retrofits = Blueprint("retrofits", __name__)

ROLES = ("SystemAdmin", "FleetPlanner", "MaintenanceController", "ComplianceOfficer")


def _load_retrofit(retrofit_id):
    r = db.retrofits.get(retrofit_id)
    if r is None:
        raise not_found("ERR_RETROFIT_NOT_FOUND", f"Retrofit order {retrofit_id} not found")
    return r


@bp_retrofits.route("/retrofit-orders", methods=["POST"])
@require_roles("MaintenanceController")
def create_retrofit():
    body = get_body()
    railcar_id = v_str(body, "railcar_id")
    directive_id = v_str(body, "directive_id")
    scheduled = v_date(body, "scheduled_date")
    if railcar_id not in db.railcars:
        raise not_found("ERR_RAILCAR_NOT_FOUND", f"Railcar {railcar_id} not found")
    directive = db.directives.get(directive_id)
    if directive is None:
        raise not_found("ERR_DIRECTIVE_NOT_FOUND", f"Compliance directive {directive_id} not found")
    if scheduled > directive["retrofit_deadline"]:
        raise ApiError(
            "ERR_RETROFIT_DEADLINE_PASSED", 422,
            "scheduled_date must be on or before the directive's retrofit_deadline",
        )
    r = new_entity(
        {
            "railcar_id": railcar_id,
            "directive_id": directive_id,
            "scheduled_date": scheduled,
            "completed_date": None,
            "certification_ref": None,
            "deferral_count": 0,
            "status": "SCHEDULED",
        }
    )
    db.retrofits[r["id"]] = r
    return ok(domain.serialize_retrofit(r), status=201)


@bp_retrofits.route("/retrofit-orders", methods=["GET"])
@require_roles(*ROLES)
def list_retrofits():
    limit, offset = parse_pagination()
    items = sorted(db.retrofits.values(), key=lambda r: (r["created_at"], r["_created_seq"]))
    railcar_id = request.args.get("railcar_id")
    directive_id = request.args.get("directive_id")
    status = request.args.get("status")
    if railcar_id is not None:
        items = [r for r in items if r["railcar_id"] == railcar_id]
    if directive_id is not None:
        items = [r for r in items if r["directive_id"] == directive_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_retrofit(r) for r in page], limit, offset, total)


@bp_retrofits.route("/retrofit-orders/<retrofit_id>", methods=["GET"])
@require_roles(*ROLES)
def get_retrofit(retrofit_id):
    return ok(domain.serialize_retrofit(_load_retrofit(retrofit_id)))


@bp_retrofits.route("/retrofit-orders/<retrofit_id>/defer", methods=["POST"])
@require_roles("MaintenanceController")
def defer_retrofit(retrofit_id):
    r = _load_retrofit(retrofit_id)
    body = get_body()
    v_str(body, "reason")
    if r["status"] != "SCHEDULED":
        raise invalid_state(f"Retrofit in status {r['status']} cannot be deferred")
    r["status"] = "DEFERRED"
    r["deferral_count"] += 1
    touch(r)
    return ok(domain.serialize_retrofit(r))


@bp_retrofits.route("/retrofit-orders/<retrofit_id>/reschedule", methods=["POST"])
@require_roles("MaintenanceController")
def reschedule_retrofit(retrofit_id):
    r = _load_retrofit(retrofit_id)
    body = get_body()
    scheduled = v_date(body, "scheduled_date")
    if r["status"] != "DEFERRED":
        raise invalid_state(f"Retrofit in status {r['status']} cannot be rescheduled")
    directive = db.directives.get(r["directive_id"])
    if directive is not None and scheduled > directive["retrofit_deadline"]:
        raise ApiError(
            "ERR_RETROFIT_DEADLINE_PASSED", 422,
            "scheduled_date must be on or before the directive's retrofit_deadline",
        )
    r["scheduled_date"] = scheduled
    r["status"] = "SCHEDULED"
    touch(r)
    return ok(domain.serialize_retrofit(r))


@bp_retrofits.route("/retrofit-orders/<retrofit_id>/start", methods=["POST"])
@require_roles("MaintenanceController")
def start_retrofit(retrofit_id):
    r = _load_retrofit(retrofit_id)
    if r["status"] != "SCHEDULED":
        raise invalid_state(f"Retrofit in status {r['status']} cannot be started")
    r["status"] = "IN_PROGRESS"
    touch(r)
    return ok(domain.serialize_retrofit(r))


@bp_retrofits.route("/retrofit-orders/<retrofit_id>/complete", methods=["POST"])
@require_roles("MaintenanceController")
def complete_retrofit(retrofit_id):
    r = _load_retrofit(retrofit_id)
    if r["status"] != "IN_PROGRESS":
        raise invalid_state(f"Retrofit in status {r['status']} cannot be completed")
    r["status"] = "COMPLETED"
    r["completed_date"] = today()
    touch(r)
    return ok(domain.serialize_retrofit(r))


@bp_retrofits.route("/retrofit-orders/<retrofit_id>/certify", methods=["POST"])
@require_roles("ComplianceOfficer")
def certify_retrofit(retrofit_id):
    r = _load_retrofit(retrofit_id)
    body = get_body()
    ref = v_str(body, "certification_ref")
    if r["status"] != "COMPLETED":
        raise invalid_state(f"Retrofit in status {r['status']} cannot be certified")
    r["status"] = "CERTIFIED"
    r["certification_ref"] = ref
    touch(r)
    car = db.railcars.get(r["railcar_id"])
    if car is not None:
        domain.recompute_posture(car)
    return ok(domain.serialize_retrofit(r))


@bp_retrofits.route("/retrofit-orders/<retrofit_id>/cancel", methods=["POST"])
@require_roles("MaintenanceController")
def cancel_retrofit(retrofit_id):
    r = _load_retrofit(retrofit_id)
    if r["status"] not in ("SCHEDULED", "DEFERRED"):
        raise invalid_state(f"Retrofit in status {r['status']} cannot be cancelled")
    r["status"] = "CANCELLED"
    touch(r)
    return ok(domain.serialize_retrofit(r))
