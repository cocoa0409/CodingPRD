"""Cleaning records (PRD 3.10)."""
from flask import Blueprint, request

import domain
from envelope import ok, ok_list
from errors import invalid_state, not_found, validation
from http_util import (
    CLEANING_GRADES, COMMODITIES, get_body, parse_pagination, require_roles,
    v_bool, v_date, v_enum, v_int, v_str,
)
from store import db, new_entity, touch

bp_cleanings = Blueprint("cleanings", __name__)

ROLES = ("SystemAdmin", "LeaseAdmin", "FleetPlanner", "MaintenanceController", "ComplianceOfficer")
STEAM_PRIORS = {"CRUDE_OIL", "GASOLINE", "CHEMICAL_SOLVENT"}


def _load_cleaning(cleaning_id):
    c = db.cleanings.get(cleaning_id)
    if c is None:
        raise not_found("ERR_CLEANING_NOT_FOUND", f"Cleaning record {cleaning_id} not found")
    return c


@bp_cleanings.route("/cleaning-records", methods=["POST"])
@require_roles("MaintenanceController")
def create_cleaning():
    body = get_body()
    railcar_id = v_str(body, "railcar_id")
    prior = v_enum(body, "prior_commodity", COMMODITIES)
    nxt = v_enum(body, "next_commodity", COMMODITIES)
    planned_date = v_date(body, "planned_date")
    attributable = v_bool(body, "attributable_to_lessee", required=False, default=False)

    if railcar_id not in db.railcars:
        raise not_found("ERR_RAILCAR_NOT_FOUND", f"Railcar {railcar_id} not found")

    record = new_entity(
        {
            "railcar_id": railcar_id,
            "prior_commodity": prior,
            "next_commodity": nxt,
            "cleaning_grade_required": "STEAM_CLEAN" if prior in STEAM_PRIORS else "WASH",
            "cleaning_grade_performed": None,
            "planned_date": planned_date,
            "cost_cents": None,
            "attributable_to_lessee": attributable,
            "bill_to": "LESSEE" if attributable else "LESSOR",
            "certificate_ref": None,
            "status": "SCHEDULED",
        }
    )
    db.cleanings[record["id"]] = record
    return ok(domain.serialize_cleaning(record), status=201)


@bp_cleanings.route("/cleaning-records", methods=["GET"])
@require_roles(*ROLES)
def list_cleanings():
    limit, offset = parse_pagination()
    items = sorted(db.cleanings.values(), key=lambda c: (c["created_at"], c["_created_seq"]))
    railcar_id = request.args.get("railcar_id")
    status = request.args.get("status")
    if railcar_id is not None:
        items = [c for c in items if c["railcar_id"] == railcar_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_cleaning(c) for c in page], limit, offset, total)


@bp_cleanings.route("/cleaning-records/<cleaning_id>", methods=["GET"])
@require_roles(*ROLES)
def get_cleaning(cleaning_id):
    return ok(domain.serialize_cleaning(_load_cleaning(cleaning_id)))


@bp_cleanings.route("/cleaning-records/<cleaning_id>/complete", methods=["POST"])
@require_roles("MaintenanceController")
def complete_cleaning(cleaning_id):
    c = _load_cleaning(cleaning_id)
    body = get_body()
    performed = v_enum(body, "cleaning_grade_performed", CLEANING_GRADES)
    cost = v_int(body, "cost_cents", min=0)
    if c["status"] not in ("SCHEDULED", "FAILED"):
        raise invalid_state(f"Cleaning in status {c['status']} cannot be completed")
    # STEAM_CLEAN satisfies both grades; WASH satisfies only WASH
    satisfied = performed == "STEAM_CLEAN" or c["cleaning_grade_required"] == "WASH"
    if not satisfied:
        raise validation(
            "cleaning_grade_performed does not satisfy cleaning_grade_required"
        )
    c["cleaning_grade_performed"] = performed
    c["cost_cents"] = cost
    c["status"] = "COMPLETED"
    touch(c)
    return ok(domain.serialize_cleaning(c))


@bp_cleanings.route("/cleaning-records/<cleaning_id>/certify", methods=["POST"])
@require_roles("ComplianceOfficer")
def certify_cleaning(cleaning_id):
    c = _load_cleaning(cleaning_id)
    body = get_body()
    ref = v_str(body, "certificate_ref")
    if c["status"] != "COMPLETED":
        raise invalid_state(f"Cleaning in status {c['status']} cannot be certified")
    c["certificate_ref"] = ref
    c["status"] = "CERTIFIED"
    touch(c)
    if c["bill_to"] == "LESSEE":
        assignment = domain.most_recent_returned_assignment(c["railcar_id"])
        if assignment is not None:
            lease = db.leases.get(assignment["lease_id"])
            lessee = db.lessees.get(lease["lessee_id"]) if lease else None
            if lessee is not None:
                domain.balance_add(lessee, c["cost_cents"])
    return ok(domain.serialize_cleaning(c))


@bp_cleanings.route("/cleaning-records/<cleaning_id>/fail", methods=["POST"])
@require_roles("ComplianceOfficer")
def fail_cleaning(cleaning_id):
    c = _load_cleaning(cleaning_id)
    body = get_body()
    v_str(body, "reason")
    if c["status"] != "COMPLETED":
        raise invalid_state(f"Cleaning in status {c['status']} cannot be failed")
    c["status"] = "FAILED"
    touch(c)
    return ok(domain.serialize_cleaning(c))
