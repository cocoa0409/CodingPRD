"""Client endpoints."""
from flask import Blueprint, g, request

import db
from errors import err
from middleware import require_auth, get_pagination
from response import success
from services.validation import (
    get_body, require_str, require_int, require_field, optional_str,
    check_version, validate_email, validate_e164,
)
from services.risk import recompute_for_client, get_score_for_client
from services.calculations import round_half_to_even
from services.calculations import risk_flag_for_score


bp = Blueprint("clients", __name__)


def _client_public(c: dict) -> dict:
    return db.public(c)


@bp.route("/counseling/clients", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def create_client():
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    timezone = require_str(body, "timezone")
    emergency_contact_name = require_str(body, "emergency_contact_name")
    emergency_contact_phone = require_str(body, "emergency_contact_phone")

    validate_email(email)
    validate_e164(emergency_contact_phone)
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(timezone)
    except Exception:
        raise err("ERR_VALIDATION", "timezone must be a valid IANA timezone")

    for cli in db.clients.values():
        if cli["email"] == email:
            raise err("ERR_VALIDATION", "email already in use")

    client = {
        "full_name": full_name,
        "email": email,
        "timezone": timezone,
        "emergency_contact_name": emergency_contact_name,
        "emergency_contact_phone": emergency_contact_phone,
        "assessment_status": "PENDING",
        "package_balance_sessions": 0,
        "risk_flag": "NONE",
    }
    db.stamp_create(client, common_fields=True)
    db.clients[client["id"]] = client
    return success(_client_public(client), 201)


@bp.route("/counseling/clients/<id>", methods=["GET"])
@require_auth(roles={"Client", "Counselor", "CrisisResponder", "PlatformAdmin"})
def get_client(id):
    cli = db.clients.get(id)
    if cli is None:
        raise err("ERR_NOT_FOUND", f"Client {id} not found")
    if g.user_role == "Client" and g.user_id != id:
        raise err("ERR_FORBIDDEN", "Client may only see own profile")
    return success(_client_public(cli))


@bp.route("/counseling/clients/<id>", methods=["PATCH"])
@require_auth(roles={"Client", "PlatformAdmin"})
def patch_client(id):
    cli = db.clients.get(id)
    if cli is None:
        raise err("ERR_NOT_FOUND", f"Client {id} not found")
    if g.user_role == "Client" and g.user_id != id:
        raise err("ERR_FORBIDDEN", "Client may only edit own profile")

    body = get_body()
    check_version(cli, body)

    if "emergency_contact_name" in body and body["emergency_contact_name"] is not None:
        if not isinstance(body["emergency_contact_name"], str):
            raise err("ERR_VALIDATION", "emergency_contact_name must be a string")
        cli["emergency_contact_name"] = body["emergency_contact_name"]
    if "emergency_contact_phone" in body and body["emergency_contact_phone"] is not None:
        validate_e164(body["emergency_contact_phone"])
        cli["emergency_contact_phone"] = body["emergency_contact_phone"]
    if "timezone" in body and body["timezone"] is not None:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(body["timezone"])
        except Exception:
            raise err("ERR_VALIDATION", "timezone must be a valid IANA timezone")
        cli["timezone"] = body["timezone"]

    db.stamp_update(cli)
    return success(_client_public(cli))


@bp.route("/counseling/clients/<id>/credit-package", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def credit_package(id):
    cli = db.clients.get(id)
    if cli is None:
        raise err("ERR_NOT_FOUND", f"Client {id} not found")
    body = get_body()
    sessions = require_int(body, "sessions")
    check_version(cli, body)
    if sessions <= 0:
        raise err("ERR_VALIDATION", "sessions must be positive")
    cli["package_balance_sessions"] = cli.get("package_balance_sessions", 0) + sessions
    db.stamp_update(cli)
    return success(_client_public(cli))


@bp.route("/counseling/clients/<id>/risk-summary", methods=["GET"])
@require_auth(roles={"Client", "Counselor", "CrisisResponder", "PlatformAdmin"})
def risk_summary(id):
    cli = db.clients.get(id)
    if cli is None:
        raise err("ERR_NOT_FOUND", f"Client {id} not found")
    if g.user_role == "Client" and g.user_id != id:
        raise err("ERR_FORBIDDEN", "Client may only see own risk summary")

    raw_score = get_score_for_client(id)
    flag = risk_flag_for_score(raw_score)
    if g.user_role == "Counselor":
        displayed_score = round_half_to_even(raw_score)
    else:
        displayed_score = raw_score
    return success({
        "client_id": id,
        "score": displayed_score,
        "risk_flag": flag,
    })
