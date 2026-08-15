"""Registration and read endpoints: schemes, clients, auditors, decision
makers, witness audits, the public directory, and the logical clock."""

from flask import Blueprint, request

import db
from db import get_now, set_now
from errors import (
    ApiError,
    ERR_CLIENT_NOT_FOUND,
    ERR_SCHEME_NOT_FOUND,
    ERR_AUDITOR_NOT_FOUND,
    ERR_DECISION_MAKER_NOT_FOUND,
)
from middleware import (
    get_auth,
    require_role,
    forbid_ownership,
    invalid_request,
    get_body,
    req_string,
    req_int,
    req_number,
    req_enum,
)
from response import success_object, success_list, parse_pagination, paginate
from services.core import (
    refresh_auditor,
    serialize_auditor,
    run_sweeps,
)

bp = Blueprint("registration", __name__)

ALL_ROLES = ("SchemeAdmin", "ClientAdmin", "Auditor", "DecisionMaker")

_SCHEME_INT_FIELDS = (
    "critical_nc_days",
    "major_nc_days",
    "minor_nc_days",
    "pass_score",
    "unannounced_every_n",
    "unannounced_min_window_days",
    "announced_max_window_days",
    "min_audit_gap_days",
    "cert_validity_days",
    "witness_validity_days",
    "appeal_window_days",
    "max_cap_rejections",
    "rotation_limit",
)
_SCHEME_NUM_FIELDS = (
    "base_fee",
    "per_category_fee",
    "day_rate",
    "unannounced_uplift_pct",
    "high_risk_multiplier",
)


# ---------------------------------------------------------------------------
# Schemes
# ---------------------------------------------------------------------------


@bp.post("/schemes")
def create_scheme():
    _, role = get_auth()
    require_role(role, ("SchemeAdmin",))
    body = get_body()

    code = req_enum(body, "code", ("SQF", "BRC"))
    name = req_string(body, "name")
    supported = body.get("supported_category_codes")
    if (
        not isinstance(supported, list)
        or len(supported) == 0
        or any(not isinstance(c, str) or not c for c in supported)
    ):
        invalid_request(
            "supported_category_codes must be a non-empty array of strings"
        )

    scheme = {
        "id": db.new_id(),
        "code": code,
        "name": name,
        "supported_category_codes": list(supported),
    }
    for field in _SCHEME_INT_FIELDS:
        scheme[field] = req_int(body, field)
    for field in _SCHEME_NUM_FIELDS:
        scheme[field] = req_number(body, field)

    now = get_now()
    scheme["created_at"] = now
    scheme["updated_at"] = now
    scheme["version"] = 1
    db.schemes[scheme["id"]] = scheme
    return success_object(db.serialize(scheme, "schemes"), status=201)


@bp.get("/schemes")
def list_schemes():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    # created_at ASC (PRD §3.1); stable sort keeps creation order on ties.
    items = sorted(db.schemes.values(), key=lambda s: s["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(
        [db.serialize(s, "schemes") for s in page], total, limit, offset
    )


@bp.get("/schemes/<scheme_id>")
def get_scheme(scheme_id):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    scheme = db.schemes.get(scheme_id)
    if not scheme:
        raise ApiError(ERR_SCHEME_NOT_FOUND, "Scheme path id does not exist", 404)
    return success_object(db.serialize(scheme, "schemes"))


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


@bp.post("/clients")
def create_client():
    _, role = get_auth()
    require_role(role, ("SchemeAdmin",))
    body = get_body()
    name = req_string(body, "name")
    contact_email = req_string(body, "contact_email")
    country = req_string(body, "country")
    now = get_now()
    client = {
        "id": db.new_id(),
        "name": name,
        "contact_email": contact_email,
        "country": country,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.clients[client["id"]] = client
    return success_object(db.serialize(client, "clients"), status=201)


@bp.get("/clients/<client_id>")
def get_client(client_id):
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin"))
    if role == "ClientAdmin" and user_id != client_id:
        forbid_ownership("ClientAdmin may read only its own record")
    client = db.clients.get(client_id)
    if not client:
        raise ApiError(ERR_CLIENT_NOT_FOUND, "Client path id does not exist", 404)
    return success_object(db.serialize(client, "clients"))


# ---------------------------------------------------------------------------
# Auditors
# ---------------------------------------------------------------------------


@bp.post("/auditors")
def create_auditor():
    _, role = get_auth()
    require_role(role, ("SchemeAdmin",))
    body = get_body()
    name = req_string(body, "name")
    competency = body.get("competency_categories")
    if not isinstance(competency, list) or any(
        not isinstance(c, str) for c in competency
    ):
        invalid_request("competency_categories must be an array of strings")
    conflicted = body.get("conflicted_client_ids", [])
    if not isinstance(conflicted, list) or any(
        not isinstance(c, str) for c in conflicted
    ):
        invalid_request("conflicted_client_ids must be an array of strings")
    now = get_now()
    auditor = {
        "id": db.new_id(),
        "name": name,
        "competency_categories": list(competency),
        "conflicted_client_ids": list(conflicted),
        "active_audit_count": 0,
        "calibration_status": "LAPSED",
        "last_witnessed_on": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.auditors[auditor["id"]] = auditor
    return success_object(db.serialize(auditor, "auditors"), status=201)


@bp.get("/auditors/<auditor_id>")
def get_auditor(auditor_id):
    _, role = get_auth()
    require_role(role, ("SchemeAdmin", "Auditor", "DecisionMaker"))
    auditor = db.auditors.get(auditor_id)
    if not auditor:
        raise ApiError(ERR_AUDITOR_NOT_FOUND, "Auditor path id does not exist", 404)
    return success_object(serialize_auditor(auditor))


@bp.get("/auditors/<auditor_id>/audits")
def list_auditor_audits(auditor_id):
    _, role = get_auth()
    require_role(role, ("SchemeAdmin", "Auditor", "DecisionMaker"))
    auditor = db.auditors.get(auditor_id)
    if not auditor:
        raise ApiError(ERR_AUDITOR_NOT_FOUND, "Auditor path id does not exist", 404)
    limit, offset = parse_pagination()
    items = [a for a in db.audits.values() if a.get("auditor_id") == auditor_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    # sequence_number ASC (PRD §3.4); a cross-chain tie breaks by created_at,
    # and a full tie keeps creation order (stable sort).
    items.sort(key=lambda a: (a["sequence_number"], a["created_at"]))
    page, total = paginate(items, limit, offset)
    return success_list([db.serialize(a, "audits") for a in page], total, limit, offset)


@bp.post("/auditors/<auditor_id>/witness-audits")
def create_witness_audit(auditor_id):
    _, role = get_auth()
    require_role(role, ("SchemeAdmin",))
    auditor = db.auditors.get(auditor_id)
    if not auditor:
        raise ApiError(ERR_AUDITOR_NOT_FOUND, "Auditor path id does not exist", 404)
    body = get_body()
    witnessed_on = db.parse_iso(req_string(body, "witnessed_on"))
    if witnessed_on is None:
        invalid_request("witnessed_on must be a valid ISO 8601 UTC timestamp")
    result = req_enum(body, "result", ("PASS", "FAIL"))
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        invalid_request("notes must be a string")
    now = get_now()
    witness = {
        "id": db.new_id(),
        "auditor_id": auditor_id,
        "witnessed_on": witnessed_on,
        "result": result,
        "notes": notes,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.witness_audits[witness["id"]] = witness
    # Recording a witness audit refreshes the auditor's computed fields
    # (calibration_status / last_witnessed_on are recomputed on every read).
    refresh_auditor(auditor)
    return success_object(db.serialize(witness, "witness_audits"), status=201)


@bp.get("/auditors/<auditor_id>/witness-audits")
def list_witness_audits(auditor_id):
    _, role = get_auth()
    require_role(role, ("SchemeAdmin", "Auditor"))
    auditor = db.auditors.get(auditor_id)
    if not auditor:
        raise ApiError(ERR_AUDITOR_NOT_FOUND, "Auditor path id does not exist", 404)
    limit, offset = parse_pagination()
    items = [w for w in db.witness_audits.values() if w["auditor_id"] == auditor_id]
    # witnessed_on DESC, ties broken by created_at ASC.
    items.sort(key=lambda w: w["created_at"])
    items.sort(key=lambda w: w["witnessed_on"], reverse=True)
    page, total = paginate(items, limit, offset)
    return success_list(
        [db.serialize(w, "witness_audits") for w in page], total, limit, offset
    )


# ---------------------------------------------------------------------------
# Decision makers
# ---------------------------------------------------------------------------


@bp.post("/decision-makers")
def create_decision_maker():
    _, role = get_auth()
    require_role(role, ("SchemeAdmin",))
    body = get_body()
    name = req_string(body, "name")
    linked_auditor_id = body.get("linked_auditor_id")
    if linked_auditor_id is not None and not isinstance(linked_auditor_id, str):
        invalid_request("linked_auditor_id must be a string or null")
    now = get_now()
    dm = {
        "id": db.new_id(),
        "name": name,
        "linked_auditor_id": linked_auditor_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.decision_makers[dm["id"]] = dm
    return success_object(db.serialize(dm, "decision_makers"), status=201)


@bp.get("/decision-makers")
def list_decision_makers():
    _, role = get_auth()
    require_role(role, ("SchemeAdmin", "DecisionMaker"))
    limit, offset = parse_pagination()
    items = list(db.decision_makers.values())
    if "linked_auditor_id" in request.args:
        linked = request.args.get("linked_auditor_id")
        items = [d for d in items if d.get("linked_auditor_id") == linked]
    items.sort(key=lambda d: d["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(
        [db.serialize(d, "decision_makers") for d in page], total, limit, offset
    )


@bp.get("/decision-makers/<dm_id>")
def get_decision_maker(dm_id):
    _, role = get_auth()
    require_role(role, ("SchemeAdmin", "DecisionMaker"))
    dm = db.decision_makers.get(dm_id)
    if not dm:
        raise ApiError(
            ERR_DECISION_MAKER_NOT_FOUND, "DecisionMaker path id does not exist", 404
        )
    return success_object(db.serialize(dm, "decision_makers"))


@bp.get("/decision-makers/<dm_id>/audits")
def list_decision_maker_audits(dm_id):
    _, role = get_auth()
    require_role(role, ("SchemeAdmin", "DecisionMaker"))
    dm = db.decision_makers.get(dm_id)
    if not dm:
        raise ApiError(
            ERR_DECISION_MAKER_NOT_FOUND, "DecisionMaker path id does not exist", 404
        )
    limit, offset = parse_pagination()
    items = [a for a in db.audits.values() if a.get("decision_maker_id") == dm_id]
    items.sort(key=lambda a: (a["sequence_number"], a["created_at"]))
    page, total = paginate(items, limit, offset)
    return success_list([db.serialize(a, "audits") for a in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Public directory — the single unauthenticated read surface
# ---------------------------------------------------------------------------


@bp.get("/directory")
def list_directory():
    get_auth(allow_anonymous=True)
    limit, offset = parse_pagination()
    items = list(db.directory_listings.values())
    scheme_code = request.args.get("scheme_code")
    if scheme_code is not None:
        items = [l for l in items if l["scheme_code"] == scheme_code]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [l for l in items if l["status"] == status_filter]
    items.sort(key=lambda l: l["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(
        [db.serialize(l, "directory_listings") for l in page], total, limit, offset
    )


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_auth()
    require_role(role, ("SchemeAdmin",))
    body = get_body()
    raw = body.get("to_iso8601")
    target = db.parse_iso(raw)
    if target is None:
        invalid_request("to_iso8601 must be a valid ISO 8601 UTC timestamp")
    set_now(target)
    # Advancing the clock fires the overdue-NC and certificate-expiry sweeps.
    run_sweeps()
    return success_object({"current_utc": db.format_dt(get_now())})
