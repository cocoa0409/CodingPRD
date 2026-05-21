"""Foreign qualification routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, jsonify

from ..auth import current_caller, require_auth
from ..envelope import object_response
from ..errors import (
    APIError,
    err_entity_not_active,
    err_invalid_input,
    err_invalid_state,
    err_not_found,
    err_version_conflict,
)
from ..store import store
from ..timeutil import now as clock_now, parse_iso
from ..util import get_json_body, new_uuid, optional_str, require_state_code, require_str
from ..services import serializers
from ..services.engine import emit_event, touch


bp = Blueprint("foreign_qualifications", __name__, url_prefix="/business-registry")


def _fq_or_404(fq_id):
    row = store.foreign_qualifications.get(fq_id)
    if row is None:
        raise err_not_found(f"Foreign qualification {fq_id!r} not found")
    return row


def _parse_cogs_date(raw) -> "datetime":
    dt = parse_iso(raw)
    if dt is None:
        raise err_invalid_input("certificate_of_good_standing_date must be a valid ISO 8601 datetime")
    return dt


@bp.post("/foreign-qualifications")
@require_auth(["Filer"])
def create_foreign_qualification():
    caller = current_caller()
    body = get_json_body()
    business_entity_id = require_str(body, "business_entity_id")
    foreign_state = require_state_code(body, "foreign_state")
    foreign_registered_agent_id = require_str(body, "foreign_registered_agent_id")
    cogs_raw = body.get("certificate_of_good_standing_date")
    if cogs_raw is None:
        raise err_invalid_input("Missing required field: certificate_of_good_standing_date")
    cogs_date = _parse_cogs_date(cogs_raw)

    with store.lock:
        entity = store.business_entities.get(business_entity_id)
        if entity is None:
            raise err_not_found(f"business_entity_id {business_entity_id!r} not found")
        agent = store.registered_agents.get(foreign_registered_agent_id)
        if agent is None:
            raise err_not_found(f"foreign_registered_agent_id {foreign_registered_agent_id!r} not found")
        if entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != business_entity_id:
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        if foreign_state == entity.get("home_state"):
            raise APIError("ERR_FOREIGN_STATE_IS_HOME",
                           "foreign_state must differ from home_state", 422)
        if agent.get("service_state") != foreign_state:
            raise APIError("ERR_AGENT_STATE_MISMATCH",
                           "foreign agent's service_state must equal foreign_state", 422)
        # Duplicate non-terminal check
        for existing in store.foreign_qualifications.values():
            if existing.get("business_entity_id") != business_entity_id:
                continue
            if existing.get("foreign_state") != foreign_state:
                continue
            if existing.get("status") in ("WITHDRAWN", "REVOKED"):
                continue
            raise APIError("ERR_DUPLICATE_FOREIGN_QUALIFICATION",
                           "A non-terminal ForeignQualification already exists for this (entity, state)", 409)
        now = clock_now()
        row = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "business_entity_id": business_entity_id,
            "foreign_state": foreign_state,
            "foreign_registered_agent_id": foreign_registered_agent_id,
            "certificate_of_good_standing_date": cogs_date,
            "status": "PENDING",
            "qualified_at": None,
            "revoked_at": None,
        }
        store.foreign_qualifications[row["id"]] = row
        return jsonify(object_response(serializers.foreign_qualification(row))), 201


@bp.patch("/foreign-qualifications/<fq_id>")
@require_auth(["Filer"])
def resubmit_foreign_qualification(fq_id):
    caller = current_caller()
    body = get_json_body()
    with store.lock:
        row = _fq_or_404(fq_id)
        if row.get("status") != "REJECTED":
            raise err_invalid_state("Foreign qualification is not in REJECTED")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != row.get("business_entity_id"):
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        if "version" in body and body["version"] is not None:
            supplied = body["version"]
            if not isinstance(supplied, int) or isinstance(supplied, bool):
                raise err_invalid_input("version must be an integer")
            if supplied != int(row.get("version", 0)):
                raise err_version_conflict()
        new_cogs_raw = body.get("certificate_of_good_standing_date")
        new_agent_id = optional_str(body, "foreign_registered_agent_id")
        if new_cogs_raw is not None:
            cogs_date = _parse_cogs_date(new_cogs_raw)
            now = clock_now()
            if (now - cogs_date) > timedelta(days=60) or (cogs_date - now) > timedelta(days=60):
                raise APIError("ERR_STALE_COGS",
                               "certificate_of_good_standing_date must be within 60 days of clock.now()", 422)
            row["certificate_of_good_standing_date"] = cogs_date
        if new_agent_id is not None:
            agent = store.registered_agents.get(new_agent_id)
            if agent is None:
                raise err_not_found(f"foreign_registered_agent_id {new_agent_id!r} not found")
            row["foreign_registered_agent_id"] = new_agent_id
        # Cycle back to PENDING
        row["status"] = "PENDING"
        touch(row)
        return jsonify(object_response(serializers.foreign_qualification(row))), 200


@bp.post("/foreign-qualifications/<fq_id>/approve")
@require_auth(["StateRegistrar"])
def approve_foreign_qualification(fq_id):
    with store.lock:
        row = _fq_or_404(fq_id)
        if row.get("status") != "PENDING":
            raise err_invalid_state("Foreign qualification is not PENDING")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if entity.get("compliance_status") != "GOOD_STANDING":
            raise err_invalid_state("Entity must be in GOOD_STANDING")
        now = clock_now()
        cogs_date = row.get("certificate_of_good_standing_date")
        if cogs_date is None or (now - cogs_date) > timedelta(days=60):
            raise APIError("ERR_STALE_COGS",
                           "certificate_of_good_standing_date is older than 60 days", 422)
        agent = store.registered_agents.get(row.get("foreign_registered_agent_id"))
        if agent is None or agent.get("status") != "ACTIVE":
            raise err_invalid_state("Foreign registered agent is not ACTIVE")
        if agent.get("service_state") != row.get("foreign_state"):
            raise APIError("ERR_AGENT_STATE_MISMATCH",
                           "foreign agent's service_state must equal foreign_state", 422)
        row["status"] = "QUALIFIED"
        row["qualified_at"] = now
        touch(row, ts=now)
        emit_event(row.get("business_entity_id"), "FOREIGN_QUALIFIED",
                   {"foreign_qualification_id": row["id"], "foreign_state": row.get("foreign_state")},
                   occurred_at=now)
        return jsonify(object_response(serializers.foreign_qualification(row))), 200


@bp.post("/foreign-qualifications/<fq_id>/reject")
@require_auth(["StateRegistrar"])
def reject_foreign_qualification(fq_id):
    with store.lock:
        row = _fq_or_404(fq_id)
        if row.get("status") != "PENDING":
            raise err_invalid_state("Foreign qualification is not PENDING")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        row["status"] = "REJECTED"
        touch(row)
        return jsonify(object_response(serializers.foreign_qualification(row))), 200


@bp.post("/foreign-qualifications/<fq_id>/withdraw")
@require_auth(["Filer"])
def withdraw_foreign_qualification(fq_id):
    caller = current_caller()
    with store.lock:
        row = _fq_or_404(fq_id)
        if row.get("status") != "QUALIFIED":
            raise err_invalid_state("Foreign qualification is not QUALIFIED")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != row.get("business_entity_id"):
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        now = clock_now()
        row["status"] = "WITHDRAWN"
        touch(row, ts=now)
        emit_event(row.get("business_entity_id"), "FOREIGN_REVOKED",
                   {"cause": "WITHDRAWN", "foreign_qualification_id": row["id"]}, occurred_at=now)
        return jsonify(object_response(serializers.foreign_qualification(row))), 200
