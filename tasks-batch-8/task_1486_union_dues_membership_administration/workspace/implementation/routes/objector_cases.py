"""ObjectorCase endpoints: list/get, rebate-projection computed read,
set-rate, issue-rebate, appeal, close."""
from flask import Blueprint, request

import db
import errors
import serializers
import utils
from middleware import require_roles, check_member_ownership, ALL_ROLES
from response import ok, ok_list
from services import ledger as ledger_svc
from services import rebate as rebate_svc

bp = Blueprint("objector_cases", __name__, url_prefix="/api/objector-cases")

TERMINAL_MEMBER_STATES = ("WITHDRAWN", "EXPELLED")


def get_case_or_404(case_id):
    case = db.store.objector_cases.get(case_id)
    if case is None:
        raise errors.objector_case_not_found()
    return case


@bp.route("", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_cases(user_id, role):
    rows = list(db.store.objector_cases.values())
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if member_id is not None:
        rows = [c for c in rows if c["member_id"] == member_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows.sort(key=lambda c: c["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.objector_case(c) for c in page], meta)


@bp.route("/<case_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_case(user_id, role, case_id):
    return ok(serializers.objector_case(get_case_or_404(case_id)), 200)


@bp.route("/<case_id>/rebate-projection", methods=["GET"])
@require_roles(*ALL_ROLES)
def rebate_projection(user_id, role, case_id):
    case = get_case_or_404(case_id)
    member = db.store.members[case["member_id"]]
    actual, projected = rebate_svc.projection(member, case)
    return ok({
        "actual_rebate_to_date_cents": actual,
        "projected_year_rebate_cents": projected,
    }, 200)


@bp.route("/<case_id>/set-rate", methods=["POST"])
@require_roles("LocalAdmin")
def set_rate(user_id, role, case_id):
    case = get_case_or_404(case_id)
    if case["status"] not in ("FILED", "APPEALED"):
        raise errors.objector_case_state_forbidden()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    pct = utils.require_int(body, "chargeable_share_pct")
    if pct < 0 or pct > 100:
        raise errors.pct_out_of_range()
    case["chargeable_share_pct"] = pct
    case["rate_set_at"] = db.fmt_ts(db.now())
    case["status"] = "RATE_SET"
    db.touch(case)
    return ok(serializers.objector_case(case), 200)


@bp.route("/<case_id>/issue-rebate", methods=["POST"])
@require_roles("SecretaryTreasurer")
def issue_rebate(user_id, role, case_id):
    case = get_case_or_404(case_id)
    if case["status"] != "RATE_SET":
        raise errors.objector_case_state_forbidden()
    member = db.store.members[case["member_id"]]
    if member["status"] in TERMINAL_MEMBER_STATES:
        raise errors.member_terminal_state()
    if member["status"] == "SUSPENDED":
        raise errors.member_state_forbidden()

    rebate, periods = rebate_svc.actual_rebate(
        member, case, rebate_svc.issue_rebate_filter(case))
    if rebate != 0:
        ledger_svc.post_entry(
            member["id"], "REBATE_CREDIT", -rebate, db.current_period(),
            memo="objector rebate for case %s" % case["id"])
    case["cumulative_rebate_cents"] += rebate
    if periods:
        case["last_rebated_period"] = max(periods)
    case["status"] = "REBATE_ISSUED"
    db.touch(case)
    ledger_svc.auto_cure(member)
    db.touch(member)
    return ok(serializers.objector_case(case), 200)


@bp.route("/<case_id>/appeal", methods=["POST"])
@require_roles("Member")
def appeal(user_id, role, case_id):
    case = get_case_or_404(case_id)
    check_member_ownership(user_id, role, case["member_id"])
    if case["status"] != "REBATE_ISSUED":
        raise errors.objector_case_state_forbidden()
    case["status"] = "APPEALED"
    db.touch(case)
    return ok(serializers.objector_case(case), 200)


@bp.route("/<case_id>/close", methods=["POST"])
@require_roles("LocalAdmin")
def close_case(user_id, role, case_id):
    case = get_case_or_404(case_id)
    if case["status"] not in ("FILED", "REBATE_ISSUED"):
        raise errors.objector_case_state_forbidden()
    case["status"] = "CLOSED"
    db.touch(case)
    return ok(serializers.objector_case(case), 200)
