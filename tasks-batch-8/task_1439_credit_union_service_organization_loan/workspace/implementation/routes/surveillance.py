"""Surveillance reporting with OCC on the servicing agreement (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint, request

import db
import serialize as ser
from errors import not_found, raise_err, ERR_NOT_OWNER, ERR_STALE_VERSION, ERR_INVALID_REQUEST
from middleware import (
    auth_context, require_role, body, req_dt, opt_enum, touch, paginate, ALL_ROLES,
)
from response import success
from services import calc
from services.cascade import certificates_of_agreement

bp = Blueprint("surveillance", __name__)

WEIGHTING_BASES = {"OUTSTANDING", "COMMITTED"}
POOL_STATUSES = {"ACTIVE", "EXCEPTION"}


def _get_report(rid):
    r = db.reports.get(rid)
    if r is None:
        not_found("SurveillanceReport")
    return r


@bp.post("/network/surveillance-reports")
def create_report():
    uid, role = auth_context()
    require_role(role, {"CUSOOfficer"})
    b = body()
    aid = b.get("servicing_agreement_id")
    if aid is not None and aid not in db.agreements:
        not_found("ServicingAgreement")
    agreement = db.agreements.get(aid) if aid is not None else None
    if agreement is not None and agreement["cuso_id"] != uid:
        raise_err(ERR_NOT_OWNER, "CUSOOfficer must own the servicing agreement")
    if aid is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: servicing_agreement_id")
    period_start = req_dt(b, "period_start")
    period_end = req_dt(b, "period_end")
    if period_end < period_start:
        raise_err(ERR_INVALID_REQUEST, "period_end must not be earlier than period_start")
    basis = opt_enum(b, "weighting_basis", WEIGHTING_BASES, "OUTSTANDING")
    # expected_servicing_agreement_version is a non-optional field
    if "expected_servicing_agreement_version" not in b or b["expected_servicing_agreement_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: expected_servicing_agreement_version")
    expected = b["expected_servicing_agreement_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_servicing_agreement_version must be an integer")
    # OCC (priority 6)
    if expected != agreement["version"]:
        raise_err(ERR_STALE_VERSION, "expected_servicing_agreement_version is stale")
    # aggregates over the pool: certificates in ACTIVE or EXCEPTION
    pool = [c for c in certificates_of_agreement(aid) if c["status"] in POOL_STATUSES]
    total_outstanding = sum(c["outstanding_principal_cents"] for c in pool)
    delinquent_count = sum(
        1
        for r in db.remittances.values()
        if r["status"] == "LATE_UNPAID" and r["certificate_id"] in {c["id"] for c in pool}
    )
    if pool:
        def weight(c):
            if basis == "OUTSTANDING":
                return c["outstanding_principal_cents"]
            return c["committed_amount_cents"]
        wsum = sum(weight(c) for c in pool)
        if wsum > 0:
            num = sum(
                Decimal(weight(c)) * Decimal(db.offerings[c["offering_id"]]["yield_rate_bps"])
                for c in pool
            )
            wac = calc.round_half_up(num / Decimal(wsum))
        else:
            wac = 0
    else:
        wac = 0
    # supersede the prior CURRENT report for this agreement
    for r in db.reports.values():
        if r["servicing_agreement_id"] == aid and r["status"] == "CURRENT":
            r["status"] = "SUPERSEDED"
            touch("report", r)
    rep = db.insert("report", {
        "servicing_agreement_id": aid,
        "period_start": period_start,
        "period_end": period_end,
        "weighting_basis": basis,
        "status": "CURRENT",
        "total_outstanding_principal_cents": total_outstanding,
        "active_certificate_count": len(pool),
        "weighted_avg_yield_bps": wac,
        "delinquent_remittance_count": delinquent_count,
    })
    # publication increments the agreement's version by one
    touch("agreement", agreement)
    return success(ser.report(rep), 201)


@bp.get("/network/surveillance-reports/<rid>")
def get_report(rid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    return success(ser.report(_get_report(rid)))


@bp.get("/network/surveillance-reports")
def list_reports():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = list(db.reports.values())
    aid = request.args.get("servicing_agreement_id")
    if aid is not None:
        items = [r for r in items if r["servicing_agreement_id"] == aid]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, meta = paginate(items, ser.report)
    return success(page, 200, meta)
