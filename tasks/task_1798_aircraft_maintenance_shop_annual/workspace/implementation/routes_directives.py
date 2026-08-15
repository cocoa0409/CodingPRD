"""Airworthiness directives and service bulletins (PRD 3.4)."""

from flask import Blueprint

import db
import envelope
import ops
from middleware import require_roles
from validate import (
    apply_filters,
    body,
    get_row,
    paginate,
    req_enum,
    req_str,
)

bp = Blueprint("directives", __name__)


@bp.post("/api/directives")
@require_roles("ShopManager")
def create_directive():
    b = body()
    aircraft_id = req_str(b, "aircraft_id")
    directive_type = req_enum(b, "directive_type", ("AD", "SB"))
    reference_number = req_str(b, "reference_number")
    description = req_str(b, "description")
    aircraft = get_row(db.AIRCRAFT, aircraft_id)
    directive = {
        "aircraft_id": aircraft_id,
        "directive_type": directive_type,
        "reference_number": reference_number,
        "description": description,
        "compliance_status": "PENDING_EVALUATION",
        "evaluated_by_mechanic_id": None,
    }
    db.stamp_new(directive)
    db.DIRECTIVES[directive["id"]] = directive
    # PENDING_EVALUATION does not itself ground, but registration is a
    # posture-relevant event.
    ops.recompute_posture(aircraft)
    return envelope.created(ops.pub(directive, ops.DIRECTIVE_F))


@bp.post("/api/directives/<rid>/evaluate")
@require_roles("Mechanic")
def evaluate_directive(rid):
    directive = get_row(db.DIRECTIVES, rid)
    b = body()
    compliance_status = req_enum(
        b, "compliance_status", ("APPLICABLE_OPEN", "COMPLIED", "NOT_APPLICABLE")
    )
    evaluated_by = req_str(b, "evaluated_by_mechanic_id")
    get_row(db.MECHANICS, evaluated_by)
    directive["compliance_status"] = compliance_status
    directive["evaluated_by_mechanic_id"] = evaluated_by
    db.touch(directive)
    ops.recompute_posture_for(directive["aircraft_id"])
    return envelope.ok(ops.pub(directive, ops.DIRECTIVE_F))


@bp.get("/api/directives")
@require_roles("ShopManager", "Mechanic", "Owner")
def list_directives():
    rows = apply_filters(
        list(db.DIRECTIVES.values()),
        {
            "aircraft_id": "aircraft_id",
            "compliance_status": "compliance_status",
            "evaluated_by_mechanic_id": "evaluated_by_mechanic_id",
        },
    )
    return paginate(rows, ops.DIRECTIVE_F)


@bp.get("/api/directives/<rid>")
@require_roles("ShopManager", "Mechanic", "Owner")
def get_directive(rid):
    directive = get_row(db.DIRECTIVES, rid)
    return envelope.ok(ops.pub(directive, ops.DIRECTIVE_F))
