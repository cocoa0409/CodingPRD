"""Client endpoints & onboarding state machine (PRD §3.1)."""

from datetime import date

from flask import Blueprint, request

from db import db
from errors import err
from middleware import authenticate, authorize
from response import created, ok, list_ok
from services.common import stamp_new, touch
from services.lookup import get_or_404, ref_or_422
from util import (body, require_str, require_score, require_iso_date,
                  require_str as _rs, pagination, paginate, require_enum, parse_iso_date)

bp = Blueprint("clients", __name__)

READ_ROLES = {"Advisor", "ComplianceOfficer", "BillingAdmin"}
ACTIONS = {"VERIFY_KYC", "SIGN_IPS", "ACTIVATE", "DISENGAGE"}


def serialize(c):
    return {
        "id": c["id"],
        "household_id": c["household_id"],
        "full_name": c["full_name"],
        "date_of_birth": c["date_of_birth"],
        "risk_capacity_score": c["risk_capacity_score"],
        "risk_tolerance_score": c["risk_tolerance_score"],
        "suitability_band": c["suitability_band"],
        "onboarding_status": c["onboarding_status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _suitability_band(capacity, tolerance):
    """Conservative of the two scores selects the band (PRD §3.1).
    Low -> CONSERVATIVE, middle -> MODERATE, high -> AGGRESSIVE."""
    s = min(capacity, tolerance)
    if s < 34:
        return "CONSERVATIVE"
    if s < 67:
        return "MODERATE"
    return "AGGRESSIVE"


@bp.route("/clients", methods=["POST"])
def create():
    _, role = authenticate()
    authorize(role, {"Advisor"})
    data = body()
    household_id = require_str(data, "household_id")
    full_name = require_str(data, "full_name")
    dob = require_iso_date(data, "date_of_birth")
    capacity = require_score(data, "risk_capacity_score")
    tolerance = require_score(data, "risk_tolerance_score")
    ref_or_422(db.households, household_id, "household_id")
    c = {
        "household_id": household_id,
        "full_name": full_name,
        "date_of_birth": dob,
        "risk_capacity_score": capacity,
        "risk_tolerance_score": tolerance,
        "suitability_band": "MODERATE",
        "onboarding_status": "PROSPECT",
    }
    stamp_new(c)
    db.clients[c["id"]] = c
    return created(serialize(c))


@bp.route("/clients/<cid>", methods=["GET"])
def read(cid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    c = get_or_404(db.clients, cid)
    return ok(serialize(c))


@bp.route("/clients", methods=["GET"])
def list_():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    household_id = request.args.get("household_id")
    items = list(db.clients.values())
    if household_id is not None:
        items = [c for c in items if c["household_id"] == household_id]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize(x) for x in page], limit, offset, len(items))


@bp.route("/clients/<cid>/state", methods=["POST"])
def state(cid):
    _, role = authenticate()
    authorize(role, {"Advisor"})
    c = get_or_404(db.clients, cid)
    data = body()
    action = require_enum(data, "action", ACTIONS)

    status = c["onboarding_status"]

    if action == "VERIFY_KYC":
        if status != "PROSPECT":
            raise err("ERR_INVALID_STATE", "VERIFY_KYC requires PROSPECT")
        # date_of_birth present and parses to a valid past date
        dob = parse_iso_date(c["date_of_birth"], "date_of_birth")
        if dob >= db.clock_date():
            raise err("ERR_INVALID_REQUEST", "date_of_birth must be a past date")
        c["suitability_band"] = _suitability_band(
            c["risk_capacity_score"], c["risk_tolerance_score"])
        c["onboarding_status"] = "KYC_VERIFIED"

    elif action == "SIGN_IPS":
        if status != "KYC_VERIFIED":
            raise err("ERR_INVALID_STATE", "SIGN_IPS requires KYC_VERIFIED")
        approved = any(
            i["client_id"] == cid and i["status"] == "APPROVED"
            for i in db.investment_policy_statements.values()
        )
        if not approved:
            raise err("ERR_INVALID_STATE", "An APPROVED IPS is required to sign")
        c["onboarding_status"] = "IPS_SIGNED"

    elif action == "ACTIVATE":
        if status != "IPS_SIGNED":
            raise err("ERR_INVALID_STATE", "ACTIVATE requires IPS_SIGNED")
        has_account = any(
            a["client_id"] == cid and a["status"] in {"PENDING", "ACTIVE"}
            for a in db.accounts.values()
        )
        if not has_account:
            raise err("ERR_INVALID_STATE", "At least one PENDING/ACTIVE account is required")
        c["onboarding_status"] = "ACTIVE"

    elif action == "DISENGAGE":
        if status not in {"PROSPECT", "KYC_VERIFIED"}:
            raise err("ERR_INVALID_STATE", "DISENGAGE requires PROSPECT or KYC_VERIFIED")
        c["onboarding_status"] = "DISENGAGED"

    touch(c)
    return ok(serialize(c))
