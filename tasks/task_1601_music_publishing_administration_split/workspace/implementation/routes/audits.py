from flask import Blueprint, request

from db import STORE
from errors import (
    ApiError,
    ERR_AUDIT_PERIOD_OVERLAP,
    ERR_AUDIT_SAMPLE_BASE_INVALID,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_VALIDATION,
)
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import audit_view
from services import get_or_404, new_record, sorted_all, touch
from validators import (
    body_json, opt_int, paginate, pagination_params, req_dt, req_enum,
    req_int, req_str,
)

bp = Blueprint("audits", __name__)

VALUATION_METHODS = ["ACTUAL_SHORTFALL", "EXTRAPOLATED"]


@bp.route("/licensee-audits", methods=["POST"], strict_slashes=False)
def create_audit():
    uid, role = auth_context()
    require_roles(role, ["Auditor"])
    body = body_json()
    licensee_id = body.get("licensee_id")
    if not isinstance(licensee_id, str) or not licensee_id:
        raise ApiError(ERR_VALIDATION, 422, "licensee_id is required")
    get_or_404("licensees", licensee_id, "licensee")
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if period_start > period_end:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "period_end must be on or after period_start")
    valuation_method = req_enum(body, "valuation_method", VALUATION_METHODS)
    # closed-inclusive overlap against this licensee's audits in any status
    for other in STORE["licensee_audits"].values():
        if other["licensee_id"] != licensee_id:
            continue
        if other["period_start"] <= period_end and period_start <= other["period_end"]:
            raise ApiError(ERR_AUDIT_PERIOD_OVERLAP, 409,
                           "audit period overlaps another audit of this licensee")
    a = new_record()
    a.update({
        "licensee_id": licensee_id,
        "period_start": period_start,
        "period_end": period_end,
        "valuation_method": valuation_method,
        "status": "OPEN",
        "actual_shortfall_cents": None,
        "sampled_base_cents": None,
        "reported_base_cents": None,
        "claim_amount_cents": None,
        "settlement_cents": None,
    })
    STORE["licensee_audits"][a["id"]] = a
    return success(audit_view(a), status=201)


@bp.route("/licensee-audits", methods=["GET"], strict_slashes=False)
def list_audits():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("licensee_audits")
    licensee_id = request.args.get("licensee_id")
    status = request.args.get("status")
    if licensee_id is not None:
        items = [a for a in items if a["licensee_id"] == licensee_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items, limit, offset)
    return success([audit_view(a) for a in page],
                   response_type="array", pagination=meta)


@bp.route("/licensee-audits/<aid>", methods=["GET"], strict_slashes=False)
def get_audit(aid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    a = get_or_404("licensee_audits", aid, "licensee audit")
    return success(audit_view(a))


@bp.route("/licensee-audits/<aid>/begin-fieldwork", methods=["POST"], strict_slashes=False)
def begin_fieldwork(aid):
    uid, role = auth_context()
    require_roles(role, ["Auditor"])
    a = get_or_404("licensee_audits", aid, "licensee audit")
    if a["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "begin-fieldwork requires status OPEN")
    a["status"] = "FIELDWORK"
    touch(a)
    return success(audit_view(a))


@bp.route("/licensee-audits/<aid>/issue-findings", methods=["POST"], strict_slashes=False)
def issue_findings(aid):
    uid, role = auth_context()
    require_roles(role, ["Auditor"])
    a = get_or_404("licensee_audits", aid, "licensee audit")
    body = body_json()
    actual = req_int(body, "actual_shortfall_cents", lo=0)
    sampled = opt_int(body, "sampled_base_cents")
    reported = opt_int(body, "reported_base_cents")
    if a["status"] not in ("FIELDWORK", "UNDER_APPEAL"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "issue-findings requires status FIELDWORK or UNDER_APPEAL")
    if a["valuation_method"] == "EXTRAPOLATED":
        if sampled is None or sampled < 1 or reported is None or reported < sampled:
            raise ApiError(
                ERR_AUDIT_SAMPLE_BASE_INVALID, 422,
                "EXTRAPOLATED findings require sampled_base_cents >= 1 and "
                "reported_base_cents >= sampled_base_cents")
        claim = (actual * reported) // sampled
    else:
        claim = actual
    a["actual_shortfall_cents"] = actual
    a["sampled_base_cents"] = sampled
    a["reported_base_cents"] = reported
    a["claim_amount_cents"] = claim
    a["status"] = "FINDINGS_ISSUED"
    touch(a)
    return success(audit_view(a))


@bp.route("/licensee-audits/<aid>/appeal", methods=["POST"], strict_slashes=False)
def appeal_audit(aid):
    uid, role = auth_context()
    require_roles(role, ["Auditor"])
    a = get_or_404("licensee_audits", aid, "licensee audit")
    body = body_json()
    req_str(body, "reason")
    if a["status"] != "FINDINGS_ISSUED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "appeal requires status FINDINGS_ISSUED")
    a["status"] = "UNDER_APPEAL"
    touch(a)
    return success(audit_view(a))


@bp.route("/licensee-audits/<aid>/settle", methods=["POST"], strict_slashes=False)
def settle_audit(aid):
    uid, role = auth_context()
    require_roles(role, ["FinanceManager"])
    a = get_or_404("licensee_audits", aid, "licensee audit")
    body = body_json()
    settlement = req_int(body, "settlement_cents", lo=0)
    if a["status"] != "FINDINGS_ISSUED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "settle requires status FINDINGS_ISSUED")
    a["settlement_cents"] = settlement
    a["status"] = "SETTLED"
    touch(a)
    return success(audit_view(a))


@bp.route("/licensee-audits/<aid>/close", methods=["POST"], strict_slashes=False)
def close_audit(aid):
    uid, role = auth_context()
    require_roles(role, ["Auditor"])
    a = get_or_404("licensee_audits", aid, "licensee audit")
    if a["status"] not in ("OPEN", "FIELDWORK"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "close requires status OPEN or FIELDWORK")
    a["status"] = "CLOSED"
    touch(a)
    return success(audit_view(a))
