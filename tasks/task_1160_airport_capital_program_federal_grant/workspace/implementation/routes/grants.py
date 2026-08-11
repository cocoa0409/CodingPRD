"""Grants and grant amendments."""
from flask import Blueprint, request

from auth import ALL_ROLES, require
from domain import (amendment_calc, closeout_settle_and_cascade,
                    funding_split, ser_amendment, ser_grant)
from errors import ApiError, err_invalid_state, err_validation
from store import DB
from util import (as_int, as_number, as_str, body, get_or_404, need,
                  new_entity, respond, respond_list, touch)

bp = Blueprint("grants", __name__)


def _get_grant(gid):
    return get_or_404(DB.grants, gid, "Grant")


@bp.route("/aip/grants", methods=["GET"])
@require(*ALL_ROLES)
def list_grants():
    items = list(DB.grants.values())
    sponsor_id = request.args.get("sponsor_id")
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    if sponsor_id is not None:
        items = [g for g in items if g["sponsor_id"] == sponsor_id]
    if application_id is not None:
        items = [g for g in items if g["application_id"] == application_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    return respond_list(items, ser_grant)


@bp.route("/aip/grants/<grantId>", methods=["GET"])
@require(*ALL_ROLES)
def get_grant(grantId):
    return respond(ser_grant(_get_grant(grantId)))


@bp.route("/aip/grants/<grantId>/request-closeout", methods=["POST"])
@require("SponsorStaff")
def request_closeout(grantId):
    g = _get_grant(grantId)
    if g["status"] != "ACTIVE":
        raise err_invalid_state(
            f"Grant in status {g['status']} cannot request closeout")
    if any(r["grant_id"] == g["id"] and
           r["status"] in ("DRAFT", "CERTIFIED", "SUBMITTED")
           for r in DB.reimbursements.values()):
        raise ApiError("ERR_CLOSEOUT_BLOCKED", 422,
                       "Closeout blocked by pending drawdowns")
    if any(p["grant_id"] == g["id"] and p["status"] in ("PLANNED", "ACTIVE")
           for p in DB.phases.values()):
        raise ApiError("ERR_CLOSEOUT_BLOCKED", 422,
                       "Closeout blocked by open construction phases")
    g["status"] = "CLOSEOUT_REQUESTED"
    touch(g)
    return respond(ser_grant(g))


@bp.route("/aip/grants/<grantId>/begin-audit", methods=["POST"])
@require("Auditor")
def begin_audit(grantId):
    g = _get_grant(grantId)
    if g["status"] != "CLOSEOUT_REQUESTED":
        raise err_invalid_state(
            "Only a CLOSEOUT_REQUESTED grant can begin audit")
    g["status"] = "UNDER_AUDIT"
    touch(g)
    return respond(ser_grant(g))


@bp.route("/aip/grants/<grantId>/approve-closeout", methods=["POST"])
@require("FAAManager")
def approve_closeout(grantId):
    g = _get_grant(grantId)
    if g["status"] != "UNDER_AUDIT":
        raise err_invalid_state(
            "Only an UNDER_AUDIT grant can be approved for closeout")
    if any(f["grant_id"] == g["id"] and f["status"] == "OPEN"
           for f in DB.findings.values()):
        raise ApiError("ERR_CLOSEOUT_BLOCKED", 422,
                       "Closeout blocked by OPEN audit findings")
    if any(a["grant_id"] == g["id"] and a["status"] == "DISPOSAL_REQUESTED"
           for a in DB.assets.values()):
        raise ApiError("ERR_CLOSEOUT_BLOCKED", 422,
                       "Closeout blocked by DISPOSAL_REQUESTED assets")
    closeout_settle_and_cascade(g)
    touch(g)
    return respond(ser_grant(g))


# ---------------------------------------------------------------------------
# Grant amendments
# ---------------------------------------------------------------------------

@bp.route("/aip/grants/<grantId>/amendments", methods=["POST"])
@require("SponsorStaff")
def create_amendment(grantId):
    g = _get_grant(grantId)
    if g["status"] != "ACTIVE":
        raise err_invalid_state(
            "Amendments may only be created against an ACTIVE grant")
    b = body()
    added = as_number(need(b, "added_scope_cost"), "added_scope_cost")
    if added <= 0:
        raise err_validation("added_scope_cost must be > 0")
    reason = as_str(need(b, "reason"), "reason")
    expected = as_int(need(b, "expected_grant_version"),
                      "expected_grant_version")
    # OCC is evaluated last (priority 29).
    if expected != g["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_grant_version does not match the grant's "
                       "current version")
    new_total, contingency, federal_delta = amendment_calc(g, added)
    # Supersede any prior PENDING amendment of this grant.
    for a in DB.amendments.values():
        if a["grant_id"] == g["id"] and a["status"] == "PENDING":
            a["status"] = "SUPERSEDED"
            touch(a)
    a = new_entity()
    a.update({"grant_id": g["id"], "added_scope_cost": added,
              "reason": reason, "contingency_amount": contingency,
              "new_total_budget": new_total, "federal_delta": federal_delta,
              "status": "PENDING"})
    DB.amendments[a["id"]] = a
    touch(g)
    return respond(ser_amendment(a), 201)


@bp.route("/aip/grants/<grantId>/amendments", methods=["GET"])
@require(*ALL_ROLES)
def list_amendments(grantId):
    g = _get_grant(grantId)
    items = [a for a in DB.amendments.values() if a["grant_id"] == g["id"]]
    return respond_list(items, ser_amendment)


def _get_amendment(aid):
    return get_or_404(DB.amendments, aid, "GrantAmendment")


@bp.route("/aip/grant-amendments/<amendmentId>/approve", methods=["POST"])
@require("FAAManager")
def approve_amendment(amendmentId):
    a = _get_amendment(amendmentId)
    if a["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING amendment can be approved")
    g = DB.grants[a["grant_id"]]
    if g["status"] != "ACTIVE":
        raise ApiError("ERR_GRANT_NOT_ACTIVE", 409,
                       "Amendment approval requires an ACTIVE grant")
    sponsor = DB.sponsors[g["sponsor_id"]]
    if a["federal_delta"] > sponsor["npe_entitlement_available"]:
        raise ApiError("ERR_ENTITLEMENT_INSUFFICIENT", 402,
                       "federal_delta exceeds sponsor NPE available")
    g["total_budget"] = a["new_total_budget"]
    g["federal_obligated"] += a["federal_delta"]
    g["entitlement_portion"] += a["federal_delta"]
    sponsor["npe_entitlement_available"] -= a["federal_delta"]
    touch(sponsor)
    _, state_est, local_est = funding_split(g["total_budget"],
                                            g["federal_share_pct_dec"])
    g["state_share_estimated"] = state_est
    g["local_share_estimated"] = local_est
    touch(g)
    a["status"] = "APPROVED"
    touch(a)
    return respond(ser_amendment(a))


@bp.route("/aip/grant-amendments/<amendmentId>/reject", methods=["POST"])
@require("FAAManager")
def reject_amendment(amendmentId):
    a = _get_amendment(amendmentId)
    if a["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING amendment can be rejected")
    a["status"] = "REJECTED"
    touch(a)
    return respond(ser_amendment(a))
