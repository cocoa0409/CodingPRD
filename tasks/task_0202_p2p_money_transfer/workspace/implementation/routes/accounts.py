"""Account endpoints: register, fetch, list, freeze, and reverse-lookup listings."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import ledger

bp = Blueprint("accounts", __name__)

DEFAULT_DAILY = 250000
DEFAULT_WEEKLY = 1000000


def _find_account_by_email(email):
    low = email.strip().lower()
    for a in db.accounts.values():
        if a["email"].strip().lower() == low:
            return a
    return None


@bp.route("/accounts", methods=["POST"])
def create_account():
    with db.lock:
        # registration is open to Anonymous or PlatformAdmin; no auth headers required.
        body = validate.get_json_body()
        email = validate.require_str(body, "email")
        display_name = validate.require_str(body, "display_name")
        daily = validate.optional_int(body, "daily_send_limit_cents", DEFAULT_DAILY, minimum=0)
        weekly = validate.optional_int(body, "weekly_send_limit_cents", DEFAULT_WEEKLY, minimum=0)
        if _find_account_by_email(email):
            raise err("ERR_INVALID_REQUEST", "Email already registered.")
        acct = {
            "email": email,
            "display_name": display_name,
            "status": "ACTIVE",
            "available_balance_cents": 0,
            "held_balance_cents": 0,
            "risk_score": 0,
            "risk_tier": "LOW",
            "daily_send_limit_cents": daily,
            "weekly_send_limit_cents": weekly,
            "is_recipient_verified": False,
        }
        models._stamp_create(acct)
        db.accounts[acct["id"]] = acct
        return response.ok(models.serialize(acct), 201)


@bp.route("/accounts/<acct_id>", methods=["GET"])
def get_account(acct_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "ComplianceOfficer", "PlatformAdmin"})
        acct = db.accounts.get(acct_id)
        if not acct:
            raise err("ERR_NOT_FOUND", "Account not found.")
        return response.ok(models.serialize(acct))


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    with db.lock:
        p = authenticate()
        require_roles(p, {"ComplianceOfficer", "PlatformAdmin"})
        limit, offset = parse_pagination()
        items = list(db.accounts.values())
        status = request.args.get("status")
        risk_tier = request.args.get("risk_tier")
        if status is not None:
            items = [a for a in items if a["status"] == status]
        if risk_tier is not None:
            items = [a for a in items if a["risk_tier"] == risk_tier]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/accounts/<acct_id>/freeze", methods=["POST"])
def freeze_account(acct_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"ComplianceOfficer", "PlatformAdmin"})
        acct = db.accounts.get(acct_id)
        if not acct:
            raise err("ERR_NOT_FOUND", "Account not found.")
        if acct["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Account is not ACTIVE.")
        acct["status"] = "FROZEN"
        models.touch(acct)
        return response.ok(models.serialize(acct))


def _owner_scoped_list(acct_id, allowed_roles, collection_filter):
    p = authenticate()
    require_roles(p, allowed_roles)
    acct = db.accounts.get(acct_id)
    if not acct:
        raise err("ERR_NOT_FOUND", "Account not found.")
    if p.role == "AccountHolder" and p.user_id != acct_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this account.")
    limit, offset = parse_pagination()
    items = models.sort_by_created(collection_filter())
    page, meta = paginate(items, limit, offset)
    return page, meta


@bp.route("/accounts/<acct_id>/ledger", methods=["GET"])
def list_ledger(acct_id):
    with db.lock:
        page, meta = _owner_scoped_list(
            acct_id, {"AccountHolder", "ComplianceOfficer", "PlatformAdmin"},
            lambda: [e for e in db.ledger_entries.values() if e["account_id"] == acct_id])
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/accounts/<acct_id>/funding-sources", methods=["GET"])
def list_account_funding_sources(acct_id):
    with db.lock:
        page, meta = _owner_scoped_list(
            acct_id, {"AccountHolder", "PlatformAdmin"},
            lambda: [f for f in db.funding_sources.values() if f["account_id"] == acct_id])
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/accounts/<acct_id>/recipient-verifications", methods=["GET"])
def list_account_recipient_verifications(acct_id):
    with db.lock:
        page, meta = _owner_scoped_list(
            acct_id, {"AccountHolder", "PlatformAdmin"},
            lambda: [r for r in db.recipient_verifications.values()
                     if r["account_id"] == acct_id])
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/accounts/<acct_id>/split-participations", methods=["GET"])
def list_account_split_participations(acct_id):
    with db.lock:
        page, meta = _owner_scoped_list(
            acct_id, {"AccountHolder", "PlatformAdmin"},
            lambda: [sp for sp in db.split_participants.values()
                     if sp["participant_account_id"] == acct_id])
        return response.ok_list(models.serialize_list(page), pagination=meta)
