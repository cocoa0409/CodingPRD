"""AuditableEntity endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_AUDITABLE_ENTITY_INVALID_STATE,
    ERR_ENTITY_HAS_OPEN_ENGAGEMENTS,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one
from services.core import new_record, public, touch
from util import CLOCK
from validate import (
    check_unknown_fields,
    get_body,
    opt_bool,
    opt_nullable_datetime,
    req_str,
    require_path,
)

bp = Blueprint("auditable_entities", __name__)

CREATE_FIELDS = {"name", "business_owner", "regulatory_scrutiny", "last_audit_completed_at"}
OPEN_ENGAGEMENT_STATUSES = ("PLANNED", "SCOPED", "FIELDWORK", "REPORTING")


@bp.post("/audit/auditable-entities")
def create_entity():
    authorized(["AuditAdmin"])
    body = get_body()
    check_unknown_fields(body, CREATE_FIELDS)
    name = req_str(body, "name")
    business_owner = req_str(body, "business_owner")
    regulatory_scrutiny = opt_bool(body, "regulatory_scrutiny", False)
    last_audit_completed_at = opt_nullable_datetime(body, "last_audit_completed_at")
    rec = new_record("auditable_entities", {
        "name": name,
        "business_owner": business_owner,
        "regulatory_scrutiny": regulatory_scrutiny,
        "last_audit_completed_at": last_audit_completed_at,
        "status": "ACTIVE",
        "retired_at": None,
        "current_inherent_risk_score": None,
        "current_risk_tier": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/audit/auditable-entities/<rid>")
def get_entity(rid):
    return get_one("auditable_entities", rid)


@bp.post("/audit/auditable-entities/<rid>/retire")
def retire_entity(rid):
    authorized(["AuditAdmin"])
    entity = require_path("auditable_entities", rid)
    # Stage 7: must be ACTIVE
    if entity["status"] != "ACTIVE":
        raise_error(ERR_AUDITABLE_ENTITY_INVALID_STATE, "entity is not ACTIVE")
    # Stage 9: no open engagements
    for eng in db["engagements"].values():
        if eng["auditable_entity_id"] == entity["id"] and eng["status"] in OPEN_ENGAGEMENT_STATUSES:
            raise_error(ERR_ENTITY_HAS_OPEN_ENGAGEMENTS,
                        "entity has engagements in an open status")
    entity["status"] = "RETIRED"
    entity["retired_at"] = CLOCK.now_iso()
    touch(entity)
    return success_object(public(entity))
