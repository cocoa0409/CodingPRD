"""Certificate endpoints (PRD §3.8)."""

from flask import Blueprint, request

import errors
import serializers as ser
from db import db
from middleware import authenticate, require_roles, ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER
from response import object_response, array_response
from services.common import (
    touch, get_or_404, parse_pagination, paginate, report_set,
)
from services import calculations as calc

bp = Blueprint("certificates", __name__)


def _scope_filter(principal, items):
    if principal.is_admin:
        return items
    if principal.is_manager:
        scope = report_set(principal.user_id)
        return [c for c in items if c["employee_id"] in scope]
    if principal.is_learner:
        return [c for c in items if c["employee_id"] == principal.user_id]
    return []


@bp.route("/certificates", methods=["GET"])
def list_certificates():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    limit, offset = parse_pagination()
    items = list(db.certificates.values())
    for field in ("employee_id", "course_id", "enrollment_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    items = _scope_filter(p, items)
    page, total = paginate(items, limit, offset)
    return array_response([ser.certificate(c) for c in page], limit, offset, total)


@bp.route("/certificates/<rid>", methods=["GET"])
def get_certificate(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    rec = get_or_404(db.certificates, rid)
    if p.is_learner and rec["employee_id"] != p.user_id:
        raise errors.unauthorized("Out of scope")
    if p.is_manager and rec["employee_id"] not in report_set(p.user_id):
        raise errors.unauthorized("Out of scope")
    return object_response(ser.certificate(rec))


@bp.route("/certificates/<rid>/revoke", methods=["POST"])
def revoke_certificate(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    rec = get_or_404(db.certificates, rid)
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("Certificate not ACTIVE")
    rec["status"] = "REVOKED"
    touch(rec)
    # compensate conserved quantities + recompute score
    emp = db.employees.get(rec["employee_id"])
    if emp is not None:
        calc.recompute_employee_invariants(emp)
        calc.recompute_employee_compliance_score(emp)
    return object_response(ser.certificate(rec))
