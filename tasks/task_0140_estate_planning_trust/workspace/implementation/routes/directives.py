"""EndOfLifeDirective endpoints (SCAFFOLD §1.5 directives)."""
from __future__ import annotations

from flask import Blueprint, request

from config import DIRECTIVE_INSTRUCTIONS_MAX, DIRECTIVE_TYPES, DIRECTIVE_STATUSES, HIPAA_SCOPES
from db import store
from errors import ApiError
from middleware import require_auth
from response import success
from services.common import (
    bump,
    check_version,
    get_json_body,
    require_child,
    require_estate,
)
from services.serializers import serialize_directive
from utils import new_uuid


bp = Blueprint("directives", __name__)


def _scope_covers(active_scope: str, required: str) -> bool:
    if active_scope == "ALL":
        return True
    return active_scope == required


@bp.post("/estates/<estate_id>/directives")
@require_auth(["Executor"])
def create_directive(estate_id: str):
    body = get_json_body(request)
    with store.lock:
        require_estate(estate_id)
        directive_type = body.get("directive_type")
        if directive_type not in DIRECTIVE_TYPES:
            raise ApiError("ERR_BAD_REQUEST", 400,
                           "directive_type must be one of the enum literals.")
        instructions = body.get("instructions")
        if not isinstance(instructions, str):
            raise ApiError("ERR_BAD_REQUEST", 400, "instructions is required.")
        if len(instructions) > DIRECTIVE_INSTRUCTIONS_MAX:
            raise ApiError("ERR_BAD_REQUEST", 400,
                           f"instructions exceeds {DIRECTIVE_INSTRUCTIONS_MAX} characters.")
        req_hipaa = body.get("requires_hipaa_scope")
        if req_hipaa not in HIPAA_SCOPES:
            raise ApiError("ERR_BAD_REQUEST", 400,
                           "requires_hipaa_scope must be a HIPAA scope literal.")
        supersedes_id = body.get("supersedes_directive_id")
        prior = None
        if supersedes_id is not None:
            if not isinstance(supersedes_id, str) or not supersedes_id:
                raise ApiError("ERR_BAD_REQUEST", 400,
                               "supersedes_directive_id must be a string id.")
            prior = store.directives.get(supersedes_id)
            if not prior or prior["estate_id"] != estate_id:
                raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                               "supersedes_directive_id does not reference a directive in this estate.")
            if prior["status"] not in ("DRAFT", "EXECUTED"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Can only supersede a directive in DRAFT or EXECUTED status.")

        did = new_uuid()
        now = store.now()
        d = {
            "id": did,
            "estate_id": estate_id,
            "directive_type": directive_type,
            "instructions": instructions,
            "requires_hipaa_scope": req_hipaa,
            "status": "DRAFT",
            "supersedes_directive_id": supersedes_id,
            "executed_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.directives[did] = d

        if prior is not None:
            prior["status"] = "SUPERSEDED"
            bump(prior)
    return success(serialize_directive(d), 201)


@bp.get("/estates/<estate_id>/directives/<directive_id>")
@require_auth(["Executor", "CourtClerk"])
def get_directive(estate_id: str, directive_id: str):
    with store.lock:
        require_estate(estate_id)
        d = require_child(store.directives, estate_id, directive_id)
    return success(serialize_directive(d), 200)


@bp.post("/estates/<estate_id>/directives/<directive_id>/state")
@require_auth(["Executor"])
def transition_directive_state(estate_id: str, directive_id: str):
    body = get_json_body(request)
    to_status = body.get("to_status")
    if to_status not in DIRECTIVE_STATUSES:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Unknown target status for directive transition.")
    with store.lock:
        estate = require_estate(estate_id)
        d = require_child(store.directives, estate_id, directive_id)
        check_version(d, body)
        current = d["status"]

        if current == "DRAFT" and to_status == "EXECUTED":
            # Priority 6 (state reachability) — we are reachable.
            # Priority 7 (HIPAA scope coverage) — required.
            # Check estate phase precondition first, then HIPAA scope.
            # Per validation priority: state-machine (6) before HIPAA (7).
            if estate["admin_phase"] not in ("IN_PROBATE", "INVENTORIED"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Directive may only be EXECUTED while estate is IN_PROBATE or INVENTORIED.")
            req = d["requires_hipaa_scope"]
            covered = False
            for h in store.hipaa_auths.values():
                if h["estate_id"] != estate_id:
                    continue
                if h["status"] != "ACTIVE":
                    continue
                if _scope_covers(h["scope"], req):
                    covered = True
                    break
            if not covered:
                raise ApiError("ERR_HIPAA_SCOPE_INSUFFICIENT", 403,
                               "No ACTIVE HIPAA authorization covers the directive's required scope.")
            d["status"] = "EXECUTED"
            d["executed_at"] = store.now()
            bump(d)
            return success(serialize_directive(d), 200)

        if current == "DRAFT" and to_status == "REVOKED":
            d["status"] = "REVOKED"
            bump(d)
            return success(serialize_directive(d), 200)

        if current == "SUPERSEDED" and to_status == "DRAFT":
            if estate["admin_phase"] == "SETTLED":
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Cannot revise a directive on a SETTLED estate.")
            d["status"] = "DRAFT"
            d["executed_at"] = None
            bump(d)
            return success(serialize_directive(d), 200)

        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Cannot transition directive from {current} to {to_status}.")
