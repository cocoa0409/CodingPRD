"""Principals, TerritoryAgreements, RateSchedules."""
from datetime import timedelta
from flask import Blueprint, request

import db
from db import now, touch
from errors import err, not_found, invalid_request
from middleware import api, body, ctx, ALL_ROLES
from response import success_object, success_list
import services

bp = Blueprint("principals", __name__)


# ---------------------------------------------------------------------------
# Principals
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/principals", methods=["POST"])
@api(["AgencyAdmin"])
def create_principal():
    data = body()
    name = data.get("name")
    quota = data.get("annual_quota_cents")
    if not isinstance(name, str) or not name:
        raise invalid_request("name is required")
    if not db.is_int(quota) or quota <= 0:
        raise invalid_request("annual_quota_cents must be a positive integer")
    notice = data.get("notice_period_days", 90)
    if not db.is_int(notice) or notice < 0:
        raise invalid_request("notice_period_days must be a non-negative integer")
    p = {
        "name": name,
        "annual_quota_cents": quota,
        "notice_period_days": notice,
        "status": "ACTIVE",
        "termination_notice_issued_at": None,
        "termination_effective_at": None,
        "credited_ytd_sales_cents": 0,
        "ytd_year": now().year,
    }
    db.stamp_new(p)
    db.principals[p["id"]] = p
    return success_object(p, 201)


@bp.route("/rep-agency/principals", methods=["GET"])
@api(ALL_ROLES)
def list_principals():
    items = list(db.principals.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return success_list(items)


@bp.route("/rep-agency/principals/<pid>", methods=["GET"])
@api(ALL_ROLES)
def get_principal(pid):
    p = db.principals.get(pid)
    if p is None:
        raise not_found("Principal")
    return success_object(p)


def _principal_owned(pid):
    """Existence (404) then PrincipalOps ownership (403)."""
    p = db.principals.get(pid)
    if p is None:
        raise not_found("Principal")
    if ctx()["user_id"] != p["id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER",
                  "PrincipalOps may only act on its own principal")
    return p


@bp.route("/rep-agency/principals/<pid>/issue_termination_notice", methods=["POST"])
@api(["PrincipalOps"])
def issue_termination_notice(pid):
    p = _principal_owned(pid)
    if p["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Termination notice requires an ACTIVE principal")
    p["status"] = "NOTICE_PENDING"
    p["termination_notice_issued_at"] = now()
    p["termination_effective_at"] = now() + timedelta(days=p["notice_period_days"])
    touch(p)
    return success_object(p)


@bp.route("/rep-agency/principals/<pid>/rescind_termination_notice", methods=["POST"])
@api(["PrincipalOps"])
def rescind_termination_notice(pid):
    p = _principal_owned(pid)
    if p["status"] != "NOTICE_PENDING":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Rescission requires a NOTICE_PENDING principal")
    if now() >= p["termination_effective_at"]:
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Termination is already effective")
    p["status"] = "ACTIVE"
    p["termination_notice_issued_at"] = None
    p["termination_effective_at"] = None
    touch(p)
    return success_object(p)


# ---------------------------------------------------------------------------
# Territory agreements
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/principals/<pid>/agreements", methods=["POST"])
@api(["AgencyAdmin"])
def create_agreement(pid):
    p = db.principals.get(pid)
    if p is None:
        raise not_found("Principal")
    data = body()
    codes = data.get("territory_codes")
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise invalid_request("territory_codes must be an array of strings")
    eff_start = db.parse_ts(data.get("effective_start"))
    if eff_start is None:
        raise invalid_request("effective_start must be a valid ISO-8601 timestamp")
    exclusive = data.get("exclusive", True)
    if not isinstance(exclusive, bool):
        raise invalid_request("exclusive must be a boolean")
    ssb = data.get("specify_share_bp", 6000)
    if not db.is_int(ssb) or ssb < 0 or ssb > 10000:
        raise invalid_request("specify_share_bp must be an integer in [0, 10000]")
    rpsb = data.get("registered_protection_share_bp", 10000)
    if not db.is_int(rpsb) or rpsb < 0 or rpsb > 10000:
        raise invalid_request("registered_protection_share_bp must be an integer in [0, 10000]")
    eff_end = data.get("effective_end")
    if eff_end is not None:
        eff_end = db.parse_ts(eff_end)
        if eff_end is None:
            raise invalid_request("effective_end must be a valid ISO-8601 timestamp")
    tail = data.get("tail_period_days", 180)
    if not db.is_int(tail) or tail < 0:
        raise invalid_request("tail_period_days must be a non-negative integer")
    ag = {
        "principal_id": p["id"],
        "territory_codes": list(codes),
        "exclusive": exclusive,
        "specify_share_bp": ssb,
        "registered_protection_share_bp": rpsb,
        "effective_start": eff_start,
        "effective_end": eff_end,
        "tail_period_days": tail,
        "status": "DRAFT",
    }
    db.stamp_new(ag)
    db.agreements[ag["id"]] = ag
    return success_object(ag, 201)


@bp.route("/rep-agency/principals/<pid>/agreements", methods=["GET"])
@api(ALL_ROLES)
def list_agreements(pid):
    if pid not in db.principals:
        raise not_found("Principal")
    items = [a for a in db.agreements.values() if a["principal_id"] == pid]
    return success_list(items)


@bp.route("/rep-agency/agreements/<agid>", methods=["GET"])
@api(ALL_ROLES)
def get_agreement(agid):
    ag = db.agreements.get(agid)
    if ag is None:
        raise not_found("TerritoryAgreement")
    return success_object(ag)


@bp.route("/rep-agency/agreements/<agid>/activate", methods=["POST"])
@api(["AgencyAdmin"])
def activate_agreement(agid):
    ag = db.agreements.get(agid)
    if ag is None:
        raise not_found("TerritoryAgreement")
    if ag["status"] not in ("DRAFT", "SUSPENDED"):
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only DRAFT or SUSPENDED agreements can be activated")
    p = db.principals.get(ag["principal_id"])
    if p is not None and p["status"] == "TERMINATED":
        raise err("ERR_LINE_TERMINATED", "Principal is TERMINATED")
    for other in db.agreements.values():
        if (other["id"] != ag["id"] and other["principal_id"] == ag["principal_id"]
                and other["status"] == "ACTIVE"):
            raise err("ERR_AGREEMENT_CONFLICT",
                      "Another ACTIVE agreement already exists for this principal")
    ag["status"] = "ACTIVE"
    touch(ag)
    return success_object(ag)


@bp.route("/rep-agency/agreements/<agid>/suspend", methods=["POST"])
@api(["AgencyAdmin"])
def suspend_agreement(agid):
    ag = db.agreements.get(agid)
    if ag is None:
        raise not_found("TerritoryAgreement")
    if ag["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only an ACTIVE agreement can be suspended")
    ag["status"] = "SUSPENDED"
    touch(ag)
    return success_object(ag)


# ---------------------------------------------------------------------------
# Rate schedules
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/principals/<pid>/rate-schedules", methods=["POST"])
@api(["AgencyAdmin"])
def create_rate_schedule(pid):
    p = db.principals.get(pid)
    if p is None:
        raise not_found("Principal")
    data = body()
    # OCC (priority 6) precedes payload shape checks (priority 9)
    epv = data.get("expected_principal_version")
    if epv is not None:
        if not db.is_int(epv):
            raise invalid_request("expected_principal_version must be an integer")
        if epv != p["version"]:
            raise err("ERR_STALE_PRINCIPAL_VERSION",
                      "expected_principal_version does not match the principal's version")
    else:
        raise invalid_request("expected_principal_version is required")
    family_rates = data.get("family_rates")
    if (not isinstance(family_rates, list) or not family_rates
            or any(not isinstance(fr, dict)
                   or not isinstance(fr.get("family_code"), str)
                   or not db.is_int(fr.get("base_rate_bp"))
                   for fr in family_rates)):
        raise invalid_request("family_rates must be an array of {family_code, base_rate_bp}")
    tiers = data.get("attainment_tiers")
    if (not isinstance(tiers, list) or not tiers
            or any(not isinstance(t, dict)
                   or not db.is_int(t.get("min_attainment_bp"))
                   or not db.is_int(t.get("multiplier_bp"))
                   for t in tiers)):
        raise invalid_request("attainment_tiers must be an array of {min_attainment_bp, multiplier_bp}")
    bonus = data.get("registration_bonus_bp", 200)
    if not db.is_int(bonus) or bonus < 0:
        raise invalid_request("registration_bonus_bp must be a non-negative integer")
    # supersede the currently ACTIVE schedule atomically
    prior = services.active_schedule(pid)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    rs = {
        "principal_id": pid,
        "family_rates": [{"family_code": fr["family_code"],
                          "base_rate_bp": fr["base_rate_bp"]} for fr in family_rates],
        "attainment_tiers": [{"min_attainment_bp": t["min_attainment_bp"],
                              "multiplier_bp": t["multiplier_bp"]} for t in tiers],
        "registration_bonus_bp": bonus,
        "status": "ACTIVE",
        "effective_from": now(),
    }
    db.stamp_new(rs)
    db.rate_schedules[rs["id"]] = rs
    touch(p)
    return success_object(rs, 201)


@bp.route("/rep-agency/principals/<pid>/rate-schedules", methods=["GET"])
@api(ALL_ROLES)
def list_rate_schedules(pid):
    if pid not in db.principals:
        raise not_found("Principal")
    items = [r for r in db.rate_schedules.values() if r["principal_id"] == pid]
    return success_list(items)


@bp.route("/rep-agency/rate-schedules/<rsid>", methods=["GET"])
@api(ALL_ROLES)
def get_rate_schedule(rsid):
    rs = db.rate_schedules.get(rsid)
    if rs is None:
        raise not_found("RateSchedule")
    return success_object(rs)
