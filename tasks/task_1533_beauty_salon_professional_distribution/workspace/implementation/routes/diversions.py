"""DiversionCase endpoints (PRD 3.11)."""

from flask import Blueprint, request

import errors as E
import middleware as M
import response as R
import services as S
from db import store, new_id, stamp_created, touch

bp = Blueprint("diversions", __name__)

FILE_ROLES = {"SalesConsultant", "ComplianceOfficer"}
READ_ROLES = {"DistributionAdmin", "ComplianceOfficer"}
ADJUDICATE_ROLES = {"ComplianceOfficer"}
SEVERITIES = {"MINOR", "MAJOR", "SEVERE"}


@bp.post("/api/diversion-cases")
def create_case():
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"salon_account_id", "product_id", "severity", "evidence_note", "hold_shipments"})
    salon_id = M.req_string(data, "salon_account_id")
    product_id = M.req_string(data, "product_id")
    severity = M.req_enum(data, "severity", SEVERITIES)
    evidence_note = M.req_string(data, "evidence_note")
    hold_shipments = M.opt_bool(data, "hold_shipments", default=False)
    M.require_role(ctx, FILE_ROLES)
    salon = S.get_salon(salon_id)
    product = S.get_product(product_id)
    case = {
        "id": new_id(),
        "salon_account_id": salon["id"],
        "product_id": product["id"],
        "filed_by_consultant_id": ctx.user_id if ctx.role == "SalesConsultant" else None,
        "filed_by_user_id": ctx.user_id,
        "severity": severity,
        "evidence_note": evidence_note,
        "hold_shipments": hold_shipments,
        "status": "OPEN",
        "adjudicated_by_user_id": None,
        "strike_points_awarded": 0,
    }
    stamp_created(case)
    store.diversion_cases[case["id"]] = case
    return R.success_object(S.pub(case), 201)


@bp.get("/api/diversion-cases")
def list_cases():
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    items = list(store.diversion_cases.values())
    salon_id = request.args.get("salon_account_id")
    if salon_id is not None:
        items = [c for c in items if c["salon_account_id"] == salon_id]
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [c for c in items if c["product_id"] == product_id]
    filer = request.args.get("filed_by_consultant_id")
    if filer is not None:
        items = [c for c in items if c["filed_by_consultant_id"] == filer]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/diversion-cases/<cid>")
def get_case(cid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    return R.success_object(S.pub(S.get_case(cid)))


def _check_sod(ctx, case):
    if ctx.user_id == case["filed_by_user_id"]:
        raise E.segregation()


@bp.post("/api/diversion-cases/<cid>/start-review")
def start_review(cid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, ADJUDICATE_ROLES)
    case = S.get_case(cid)
    if case["status"] != "OPEN":
        raise E.invalid_diversion_case_state("Only an OPEN case can move to UNDER_REVIEW")
    case["status"] = "UNDER_REVIEW"
    touch(case)
    return R.success_object(S.pub(case))


@bp.post("/api/diversion-cases/<cid>/request-evidence")
def request_evidence(cid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, ADJUDICATE_ROLES)
    case = S.get_case(cid)
    if case["status"] != "UNDER_REVIEW":
        raise E.invalid_diversion_case_state("Only an UNDER_REVIEW case can return to OPEN")
    case["status"] = "OPEN"
    touch(case)
    return R.success_object(S.pub(case))


@bp.post("/api/diversion-cases/<cid>/substantiate")
def substantiate(cid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, ADJUDICATE_ROLES)
    case = S.get_case(cid)
    _check_sod(ctx, case)
    if case["status"] != "UNDER_REVIEW":
        raise E.invalid_diversion_case_state("Only an UNDER_REVIEW case can be substantiated")
    points = S.SEVERITY_POINTS[case["severity"]]
    case["status"] = "SUBSTANTIATED"
    case["adjudicated_by_user_id"] = ctx.user_id
    case["strike_points_awarded"] = points
    touch(case)
    salon = store.salons.get(case["salon_account_id"])
    if salon is not None:
        salon["diversion_strike_points"] += points
        S.recompute_risk_score(salon)
        touch(salon)
        if salon["diversion_strike_points"] >= 3 and salon["status"] == "ACTIVE":
            S.suspend_salon(salon, "DIVERSION_STRIKES")
    return R.success_object(S.pub(case))


@bp.post("/api/diversion-cases/<cid>/dismiss")
def dismiss(cid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, ADJUDICATE_ROLES)
    case = S.get_case(cid)
    _check_sod(ctx, case)
    if case["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise E.invalid_diversion_case_state("Only an OPEN or UNDER_REVIEW case can be dismissed")
    case["status"] = "DISMISSED"
    case["adjudicated_by_user_id"] = ctx.user_id
    touch(case)
    return R.success_object(S.pub(case))
