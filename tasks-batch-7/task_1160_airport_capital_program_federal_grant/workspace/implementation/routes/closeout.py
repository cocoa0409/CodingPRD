"""Audit findings and grant assets (useful life / disposal)."""
from decimal import Decimal

from flask import Blueprint, request

from auth import ALL_ROLES, require
from domain import (ASSET_KINDS, FINDING_CODES, SEVERITIES,
                    asset_credit_recompute, disposal_payback, ser_asset,
                    ser_finding)
from errors import ApiError, err_invalid_state, err_validation
from store import DB
from util import (as_enum, as_int, as_number, as_str, body, get_or_404, need,
                  new_entity, parse_dt, respond, respond_list, touch)

bp = Blueprint("closeout", __name__)


# ---------------------------------------------------------------------------
# Audit findings
# ---------------------------------------------------------------------------

@bp.route("/aip/audit-findings", methods=["POST"])
@require("Auditor")
def create_finding():
    b = body()
    if "grant_id" not in b or b["grant_id"] is None:
        raise err_validation("Missing required field: grant_id")
    grant = get_or_404(DB.grants, b["grant_id"], "Grant")
    if grant["status"] != "UNDER_AUDIT":
        raise err_invalid_state(
            "Findings may only be recorded while the grant is UNDER_AUDIT")
    code = as_enum(need(b, "finding_code"), "finding_code", FINDING_CODES)
    severity = as_enum(need(b, "severity"), "severity", SEVERITIES)
    description = as_str(need(b, "description"), "description")
    f = new_entity(common=False)
    f.update({"grant_id": grant["id"], "finding_code": code,
              "severity": severity, "description": description,
              "status": "OPEN"})
    DB.findings[f["id"]] = f
    return respond(ser_finding(f), 201)


@bp.route("/aip/grants/<grantId>/audit-findings", methods=["GET"])
@require(*ALL_ROLES)
def list_findings(grantId):
    grant = get_or_404(DB.grants, grantId, "Grant")
    items = [f for f in DB.findings.values() if f["grant_id"] == grant["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return respond_list(items, ser_finding)


@bp.route("/aip/audit-findings/<findingId>/resolve", methods=["POST"])
@require("ComplianceOfficer")
def resolve_finding(findingId):
    f = get_or_404(DB.findings, findingId, "AuditFinding")
    if f["status"] != "OPEN":
        raise err_invalid_state("Only an OPEN finding can be resolved")
    grant = DB.grants.get(f["grant_id"])
    if grant is None or grant["status"] != "UNDER_AUDIT":
        raise err_invalid_state(
            "Findings may only be resolved while the grant is UNDER_AUDIT")
    f["status"] = "RESOLVED"
    return respond(ser_finding(f))


# ---------------------------------------------------------------------------
# Grant assets
# ---------------------------------------------------------------------------

@bp.route("/aip/grant-assets", methods=["POST"])
@require("SponsorStaff")
def create_asset():
    b = body()
    if "grant_id" not in b or b["grant_id"] is None:
        raise err_validation("Missing required field: grant_id")
    grant = get_or_404(DB.grants, b["grant_id"], "Grant")
    kind = as_enum(need(b, "asset_kind"), "asset_kind", ASSET_KINDS)
    description = as_str(need(b, "description"), "description")
    acq = as_number(need(b, "acquisition_federal_share"),
                    "acquisition_federal_share")
    if acq <= 0:
        raise err_validation("acquisition_federal_share must be > 0")
    life = as_int(need(b, "useful_life_years"), "useful_life_years")
    if not (1 <= life <= 50):
        raise err_validation("useful_life_years must be within 1..50")
    in_service_raw = as_str(need(b, "in_service_date"), "in_service_date")
    parse_dt(in_service_raw, "in_service_date")  # validate
    a = new_entity()
    a.update({"grant_id": grant["id"], "asset_kind": kind,
              "description": description, "acquisition_federal_share": acq,
              "useful_life_years": life, "in_service_date": in_service_raw,
              "payback_due": Decimal("0"), "status": "IN_SERVICE"})
    asset_credit_recompute(a)
    DB.assets[a["id"]] = a
    return respond(ser_asset(a), 201)


@bp.route("/aip/grants/<grantId>/assets", methods=["GET"])
@require(*ALL_ROLES)
def list_assets(grantId):
    grant = get_or_404(DB.grants, grantId, "Grant")
    items = [a for a in DB.assets.values() if a["grant_id"] == grant["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return respond_list(items, ser_asset)


def _get_asset(aid):
    return get_or_404(DB.assets, aid, "GrantAsset")


@bp.route("/aip/grant-assets/<assetId>/request-disposal", methods=["POST"])
@require("SponsorStaff")
def request_disposal(assetId):
    a = _get_asset(assetId)
    if a["status"] != "IN_SERVICE":
        raise err_invalid_state(
            "Only an IN_SERVICE asset can request disposal")
    asset_credit_recompute(a)
    a["status"] = "DISPOSAL_REQUESTED"
    touch(a)
    return respond(ser_asset(a))


@bp.route("/aip/grant-assets/<assetId>/approve-disposal", methods=["POST"])
@require("FAAManager")
def approve_disposal(assetId):
    a = _get_asset(assetId)
    if a["status"] != "DISPOSAL_REQUESTED":
        raise err_invalid_state(
            "Only a DISPOSAL_REQUESTED asset can be disposed")
    b = body()
    fmv = b.get("fair_market_value")
    if a["asset_kind"] == "LAND" and fmv is None:
        raise ApiError("ERR_FMV_REQUIRED", 422,
                       "LAND disposal approval requires fair_market_value")
    if fmv is not None:
        fmv = as_number(fmv, "fair_market_value")
        if fmv < 0:
            raise err_validation("fair_market_value must be >= 0")
    grant = DB.grants[a["grant_id"]]
    a["payback_due"] = disposal_payback(a, grant, fmv)
    a["remaining_restricted_value"] = Decimal("0")
    a["status"] = "DISPOSED"
    touch(a)
    return respond(ser_asset(a))


@bp.route("/aip/grant-assets/<assetId>/return-to-service", methods=["POST"])
@require("SponsorStaff")
def return_to_service(assetId):
    a = _get_asset(assetId)
    if a["status"] != "DISPOSAL_REQUESTED":
        raise err_invalid_state(
            "Only a DISPOSAL_REQUESTED asset can return to service")
    a["status"] = "IN_SERVICE"
    touch(a)
    return respond(ser_asset(a))
