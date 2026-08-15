from flask import Blueprint, request

from db import STORE
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_DISTRIBUTION_RUN,
    ERR_VALIDATION,
)
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import distribution_run_view
from services import (
    MIN_PAYOUT_CENTS,
    get_or_404,
    new_record,
    recompute_work_rollup,
    recompute_writer_rollups,
    sorted_all,
    statement_lines_of,
    touch,
)
from validators import body_json, paginate, pagination_params, req_str

bp = Blueprint("distributions", __name__)


@bp.route("/distribution-runs", methods=["POST"], strict_slashes=False)
def create_run():
    uid, role = auth_context()
    require_roles(role, ["RoyaltyAnalyst"])
    body = body_json()
    period_label = req_str(body, "period_label")
    for existing in STORE["distribution_runs"].values():
        if existing["period_label"] == period_label:
            raise ApiError(ERR_VALIDATION, 422,
                           "period_label must be unique across runs")
    r = new_record()
    r.update({
        "period_label": period_label,
        "status": "OPEN",
        "calculated_by_user_id": None,
        "approved_by_user_id": None,
        "writer_payouts": [],
        "included_statement_ids": [],
        "total_payable_cents": 0,
    })
    STORE["distribution_runs"][r["id"]] = r
    return success(distribution_run_view(r), status=201)


@bp.route("/distribution-runs", methods=["GET"], strict_slashes=False)
def list_runs():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("distribution_runs")
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items, limit, offset)
    return success([distribution_run_view(r) for r in page],
                   response_type="array", pagination=meta)


@bp.route("/distribution-runs/<rid>", methods=["GET"], strict_slashes=False)
def get_run(rid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    r = get_or_404("distribution_runs", rid, "distribution run")
    return success(distribution_run_view(r))


@bp.route("/distribution-runs/<rid>/calculate", methods=["POST"], strict_slashes=False)
def calculate_run(rid):
    uid, role = auth_context()
    require_roles(role, ["RoyaltyAnalyst"])
    r = get_or_404("distribution_runs", rid, "distribution run")
    if r["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "calculate requires status OPEN")
    eligible = [w for w in sorted_all("writers")
                if w["payable_balance_cents"] >= MIN_PAYOUT_CENTS]
    r["writer_payouts"] = [
        {"writer_id": w["id"], "amount_cents": w["payable_balance_cents"]}
        for w in eligible
    ]
    r["included_statement_ids"] = [
        s["id"] for s in sorted_all("royalty_statements")
        if s["status"] == "FINALIZED"
    ]
    r["total_payable_cents"] = sum(p["amount_cents"] for p in r["writer_payouts"])
    r["calculated_by_user_id"] = uid
    r["status"] = "CALCULATED"
    touch(r)
    return success(distribution_run_view(r))


@bp.route("/distribution-runs/<rid>/approve", methods=["POST"], strict_slashes=False)
def approve_run(rid):
    uid, role = auth_context()
    require_roles(role, ["FinanceManager"])
    r = get_or_404("distribution_runs", rid, "distribution run")
    if r["status"] != "CALCULATED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "approve requires status CALCULATED")
    if uid == r["calculated_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "the approver must differ from the user who calculated the run")
    included = set(r["included_statement_ids"])
    for s in STORE["royalty_statements"].values():
        if s["status"] == "FINALIZED" and s["id"] not in included:
            raise ApiError(ERR_STALE_DISTRIBUTION_RUN, 409,
                           "a FINALIZED statement exists outside the run snapshot")
    r["approved_by_user_id"] = uid
    r["status"] = "APPROVED"
    touch(r)
    return success(distribution_run_view(r))


@bp.route("/distribution-runs/<rid>/pay", methods=["POST"], strict_slashes=False)
def pay_run(rid):
    uid, role = auth_context()
    require_roles(role, ["FinanceManager"])
    r = get_or_404("distribution_runs", rid, "distribution run")
    if r["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "pay requires status APPROVED")
    for entry in r["writer_payouts"]:
        writer = STORE["writers"].get(entry["writer_id"])
        if writer is None:
            continue
        writer["payable_balance_cents"] -= entry["amount_cents"]
        recompute_writer_rollups(writer)
    affected_works = set()
    for sid in r["included_statement_ids"]:
        st = STORE["royalty_statements"].get(sid)
        if st is None or st["status"] != "FINALIZED":
            continue
        st["status"] = "DISTRIBUTED"
        touch(st)
        for line in statement_lines_of(st["id"]):
            if line["work_id"] is not None:
                affected_works.add(line["work_id"])
    for wid in affected_works:
        work = STORE["works"].get(wid)
        if work is not None:
            recompute_work_rollup(work)
    r["status"] = "PAID"
    touch(r)
    return success(distribution_run_view(r))


@bp.route("/distribution-runs/<rid>/reopen", methods=["POST"], strict_slashes=False)
def reopen_run(rid):
    uid, role = auth_context()
    require_roles(role, ["RoyaltyAnalyst"])
    r = get_or_404("distribution_runs", rid, "distribution run")
    if r["status"] != "CALCULATED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "reopen requires status CALCULATED")
    r["writer_payouts"] = []
    r["included_statement_ids"] = []
    r["total_payable_cents"] = 0
    r["calculated_by_user_id"] = None
    r["status"] = "OPEN"
    touch(r)
    return success(distribution_run_view(r))
