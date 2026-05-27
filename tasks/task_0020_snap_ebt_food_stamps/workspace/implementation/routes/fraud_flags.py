"""Fraud flag routes."""

from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from util import (
    get_json_body, require_nonempty_str, parse_pagination, paginate, new_id,
    get_household_or_parent_404,
)


bp = Blueprint("fraud_flags", __name__)

VALID_TRIGGER_RULES = {
    "VELOCITY_SPIKE", "OUT_OF_STATE", "DUPLICATE_HH_MEMBER", "CARD_REPLACE_ABUSE",
}


def _flag_view(f: dict) -> dict:
    return {
        "id": f["id"],
        "household_id": f["household_id"],
        "trigger_rule": f["trigger_rule"],
        "status": f["status"],
        "investigator_id": f.get("investigator_id"),
        "resolution_note": f.get("resolution_note"),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


@bp.route("/snap/fraud-flags", methods=["POST"])
@require_roles("Caseworker", "FraudInvestigator")
def create_flag(**_):
    body = get_json_body()
    hh_id = require_nonempty_str(body, "household_id")
    get_household_or_parent_404(hh_id)
    trigger_rule = require_nonempty_str(body, "trigger_rule")
    if trigger_rule not in VALID_TRIGGER_RULES:
        raise_api("ERR_INVALID_REQUEST", "trigger_rule not in allowed enum")

    now = db.current_utc_iso()
    f = {
        "id": new_id(),
        "household_id": hh_id,
        "trigger_rule": trigger_rule,
        "status": "OPEN",
        "investigator_id": None,
        "resolution_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.fraud_flags[f["id"]] = f
    return success(_flag_view(f), 201)


@bp.route("/snap/fraud-flags/<flag_id>", methods=["GET"])
@require_roles("FraudInvestigator", "Caseworker")
def get_flag(flag_id, **_):
    f = db.fraud_flags.get(flag_id)
    if f is None:
        raise_api("ERR_NOT_FOUND", "FraudFlag not found")
    return success(_flag_view(f))


@bp.route("/snap/fraud-flags", methods=["GET"])
@require_roles("FraudInvestigator", "Caseworker")
def list_flags(**_):
    limit, offset = parse_pagination()
    hh_filter = request.args.get("household_id")
    status_filter = request.args.get("status")
    rule_filter = request.args.get("trigger_rule")

    rows = list(db.fraud_flags.values())
    if hh_filter is not None:
        rows = [r for r in rows if r["household_id"] == hh_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if rule_filter is not None:
        rows = [r for r in rows if r["trigger_rule"] == rule_filter]

    page, total = paginate(rows, limit, offset)
    return list_success([_flag_view(r) for r in page], limit, offset, total)


@bp.route("/snap/fraud-flags/<flag_id>/claim", methods=["POST"])
@require_roles("FraudInvestigator")
def claim_flag(flag_id, _user_id, _role, **_):
    f = db.fraud_flags.get(flag_id)
    if f is None:
        raise_api("ERR_NOT_FOUND", "FraudFlag not found")
    if f["status"] != "OPEN":
        raise_api("ERR_INVALID_STATE", "FraudFlag must be OPEN to claim")

    f["status"] = "UNDER_REVIEW"
    f["investigator_id"] = _user_id
    f["updated_at"] = db.current_utc_iso()
    f["version"] = int(f.get("version", 1)) + 1
    return success(_flag_view(f))


@bp.route("/snap/fraud-flags/<flag_id>/substantiate", methods=["POST"])
@require_roles("FraudInvestigator")
def substantiate_flag(flag_id, _user_id, _role, **_):
    f = db.fraud_flags.get(flag_id)
    if f is None:
        raise_api("ERR_NOT_FOUND", "FraudFlag not found")

    body = get_json_body()
    if f["status"] != "UNDER_REVIEW":
        raise_api("ERR_INVALID_STATE", "FraudFlag must be UNDER_REVIEW to substantiate")
    # Claiming-investigator check (priority 9 in §2.8)
    if f.get("investigator_id") != _user_id:
        raise_api("ERR_NOT_CLAIMING_INVESTIGATOR",
                  "Only the claiming investigator may resolve")
    resolution_note = require_nonempty_str(body, "resolution_note")
    # OCC: expected_fraudflag_version must match (priority 21)
    expected = body.get("expected_fraudflag_version", None)
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise_api("ERR_INVALID_REQUEST", "expected_fraudflag_version (int) required")
    if expected != f["version"]:
        raise_api("ERR_STALE_FRAUDFLAG_VERSION",
                  f"Expected version {expected}, current {f['version']}")

    f["status"] = "SUBSTANTIATED"
    f["resolution_note"] = resolution_note
    f["updated_at"] = db.current_utc_iso()
    f["version"] = int(f.get("version", 1)) + 1
    return success(_flag_view(f))


@bp.route("/snap/fraud-flags/<flag_id>/dismiss", methods=["POST"])
@require_roles("FraudInvestigator")
def dismiss_flag(flag_id, _user_id, _role, **_):
    f = db.fraud_flags.get(flag_id)
    if f is None:
        raise_api("ERR_NOT_FOUND", "FraudFlag not found")

    body = get_json_body()
    if f["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise_api("ERR_INVALID_STATE", "FraudFlag must be OPEN or UNDER_REVIEW to dismiss")

    # Claiming-investigator check only when UNDER_REVIEW (per priority 9 applies_to)
    if f["status"] == "UNDER_REVIEW" and f.get("investigator_id") != _user_id:
        raise_api("ERR_NOT_CLAIMING_INVESTIGATOR",
                  "Only the claiming investigator may dismiss an UNDER_REVIEW flag")

    resolution_note = require_nonempty_str(body, "resolution_note")
    f["status"] = "DISMISSED"
    f["resolution_note"] = resolution_note
    f["updated_at"] = db.current_utc_iso()
    f["version"] = int(f.get("version", 1)) + 1
    return success(_flag_view(f))
