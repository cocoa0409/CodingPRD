"""Audit log retrieval and chain verification (PRD §2.11)."""

from flask import Blueprint, request

from db import store
from errors import ERR_AUDIT_CHAIN_BROKEN, fail
from middleware import (
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_MANAGER,
    authorize,
    pagination,
    public,
)
from response import list_response
from routes.employers import get_employer_or_404
from services import audit as audit_service

bp = Blueprint("audit", __name__)


def _truthy(value):
    return isinstance(value, str) and value.lower() in ("true", "1", "yes")


@bp.get("/employers/<employerId>/audit-log")
def list_employer_audit_log(employerId):
    # The employer-scoped listing excludes payroll_specialist (PRD §2.1).
    authorize(ROLE_ADMIN, ROLE_MANAGER, ROLE_AUDITOR)
    get_employer_or_404(employerId)
    limit, offset = pagination()

    if _truthy(request.args.get("verify")):
        if not audit_service.verify_chain(employerId):
            fail(ERR_AUDIT_CHAIN_BROKEN, 409,
                 "Audit chain recomputation mismatch for employer '%s'."
                 % employerId)

    items = audit_service.employer_chain(employerId)
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    if entity_type is not None:
        items = [e for e in items if e["entity_type"] == entity_type]
    if entity_id is not None:
        items = [e for e in items if e["entity_id"] == entity_id]

    page = items[offset:offset + limit]
    extra = {"chain_valid": True} if _truthy(request.args.get("verify")) else None
    return list_response([public(e) for e in page], len(items), limit, offset,
                         extra_meta=extra)
