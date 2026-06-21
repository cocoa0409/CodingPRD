"""EndOfLifeDirective routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body,
    optional_string,
    pagination_params,
    require_enum,
    require_string,
    stamp_common_fields,
    touch,
)
from errors import (
    APIError,
    ERR_HIPAA_RECIPIENTS_REQUIRED,
    ERR_INVALID_REQUEST,
    ERR_SEGREGATION_OF_DUTIES_VIOLATED,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import created, list_response, success
from views import view_directive


bp = Blueprint("directives", __name__)

DIRECTIVE_TYPES = {"LIVING_WILL", "DNR", "HEALTHCARE_POA", "HIPAA_AUTHORIZATION"}


@bp.post("/directives")
@require_roles("EstatePlanner")
def create_directive():
    body = get_body()
    decedent_id = require_string(body, "decedent_id")
    if decedent_id not in db.decedents:
        raise not_found("Decedent")
    directive_type = require_enum(body, "directive_type", DIRECTIVE_TYPES)
    physician = optional_string(body, "physician_attester_user_id")
    recipients = body.get("hipaa_authorized_recipients")
    if recipients is None:
        recipients = []
    if not isinstance(recipients, list) or not all(isinstance(r, str) for r in recipients):
        raise APIError(ERR_INVALID_REQUEST, "hipaa_authorized_recipients must be an array of strings.", 400)

    now = db.now_utc()
    d = {
        "decedent_id": decedent_id,
        "directive_type": directive_type,
        "status": "DRAFT",
        "physician_attester_user_id": physician,
        "hipaa_authorized_recipients": list(recipients),
    }
    stamp_common_fields(d, now)
    db.directives[d["id"]] = d
    return created(view_directive(d))


@bp.get("/directives/<did>")
@require_roles("EstatePlanner", "Executor")
def get_directive(did: str):
    d = db.directives.get(did)
    if d is None:
        raise not_found("Directive")
    return success(view_directive(d))


@bp.get("/directives")
@require_roles("EstatePlanner", "Executor")
def list_directives():
    limit, offset = pagination_params()
    decedent_id = request.args.get("decedent_id")
    directive_type = request.args.get("directive_type")
    status = request.args.get("status")

    items = list(db.directives.values())
    if decedent_id is not None:
        items = [d for d in items if d["decedent_id"] == decedent_id]
    if directive_type is not None:
        items = [d for d in items if d["directive_type"] == directive_type]
    if status is not None:
        items = [d for d in items if d["status"] == status]

    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    page = [view_directive(d) for d in items[offset:offset + limit]]
    return list_response(page, limit=limit, offset=offset, total_count=total)


def _decedent_alive(directive: dict) -> bool:
    d = db.decedents.get(directive["decedent_id"])
    return d is not None and d.get("date_of_death") is None


@bp.post("/directives/<did>/witness")
@require_roles("EstatePlanner")
def witness_directive(did: str):
    d = db.directives.get(did)
    if d is None:
        raise not_found("Directive")
    if d["status"] != "DRAFT":
        raise invalid_state("Directive must be DRAFT to witness.")
    if not _decedent_alive(d):
        raise invalid_state("Cannot witness a directive after decedent's death.")
    now = db.now_utc()
    d["status"] = "WITNESSED"
    touch(d, now)
    return success(view_directive(d))


@bp.post("/directives/<did>/notarize")
@require_roles("EstatePlanner")
def notarize_directive(did: str):
    d = db.directives.get(did)
    if d is None:
        raise not_found("Directive")
    if d["status"] != "WITNESSED":
        raise invalid_state("Directive must be WITNESSED to notarize.")
    if d["directive_type"] not in ("DNR", "LIVING_WILL", "HEALTHCARE_POA"):
        raise invalid_state("This directive_type does not require notarization.")
    now = db.now_utc()
    d["status"] = "NOTARIZED"
    touch(d, now)
    return success(view_directive(d))


def _executor_ids_for_decedent(decedent_id: str) -> set[str]:
    """Set of Estate.executor_user_id values across estates of this decedent."""
    result = set()
    for e in db.estates.values():
        if e["decedent_id"] != decedent_id:
            continue
        if e.get("executor_user_id"):
            result.add(e["executor_user_id"])
    return result


@bp.post("/directives/<did>/activate")
@require_roles("EstatePlanner")
def activate_directive(did: str):
    d = db.directives.get(did)
    if d is None:
        raise not_found("Directive")

    dt = d["directive_type"]
    cur = d["status"]
    # Per PRD: HIPAA_AUTH may activate from WITNESSED; others require NOTARIZED.
    if dt == "HIPAA_AUTHORIZATION":
        if cur not in ("WITNESSED",):
            raise invalid_state("HIPAA_AUTHORIZATION must be WITNESSED to activate.")
    elif dt == "DNR":
        if cur != "NOTARIZED":
            raise invalid_state("DNR must be NOTARIZED to activate.")
    elif dt == "LIVING_WILL":
        if cur != "NOTARIZED":
            raise invalid_state("LIVING_WILL must be NOTARIZED to activate.")
    elif dt == "HEALTHCARE_POA":
        if cur != "NOTARIZED":
            raise invalid_state("HEALTHCARE_POA must be NOTARIZED to activate.")
    else:
        raise invalid_state("Unknown directive_type.")

    # Segregation of duties (priority 5).
    if d.get("physician_attester_user_id") is not None:
        executor_ids = _executor_ids_for_decedent(d["decedent_id"])
        if d["physician_attester_user_id"] in executor_ids:
            raise APIError(
                ERR_SEGREGATION_OF_DUTIES_VIOLATED,
                "physician_attester_user_id must not equal any Estate.executor_user_id for this decedent.",
                422,
            )

    # DNR additionally requires physician_attester_user_id
    if dt == "DNR" and not d.get("physician_attester_user_id"):
        raise invalid_state("DNR activation requires physician_attester_user_id.")

    # HIPAA requires non-empty recipients
    if dt == "HIPAA_AUTHORIZATION":
        recipients = d.get("hipaa_authorized_recipients") or []
        if not recipients:
            raise APIError(
                ERR_HIPAA_RECIPIENTS_REQUIRED,
                "HIPAA_AUTHORIZATION activation requires non-empty hipaa_authorized_recipients.",
                422,
            )

    now = db.now_utc()
    d["status"] = "ACTIVE"
    touch(d, now)
    return success(view_directive(d))


@bp.post("/directives/<did>/revoke")
@require_roles("EstatePlanner")
def revoke_directive(did: str):
    d = db.directives.get(did)
    if d is None:
        raise not_found("Directive")
    if d["status"] != "ACTIVE":
        raise invalid_state("Directive must be ACTIVE to revoke.")
    if not _decedent_alive(d):
        raise invalid_state("Cannot revoke a directive after decedent's death.")
    now = db.now_utc()
    d["status"] = "REVOKED"
    touch(d, now)
    return success(view_directive(d))
