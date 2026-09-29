"""Segregation-hold reads and the explicit release of held funds (PRD 3.8)."""
from flask import Blueprint

import auth
import enums
import errors
import services
import validation as v
from auth import endpoint
from envelope import object_response, paginate
from store import db, order_by, public, public_list

bp = Blueprint("holds", __name__)


def find_hold(hold_id):
    hold = db.segregation_holds.get(hold_id)
    if hold is None:
        errors.fail(errors.ERR_SEGREGATION_HOLD_NOT_FOUND, "No segregation hold with that id.")
    return hold


@bp.route("/segregation-holds/<id>", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant")
def read_hold(caller, id):
    hold = find_hold(id)
    account = db.plan_accounts.get(hold["plan_account_id"])
    if account is not None:
        auth.own_plan_account(caller, account)
    return object_response(public(hold))


@bp.route("/segregation-holds", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant")
def list_holds(caller):
    account_id = v.query_string("plan_account_id")
    case_id = v.query_string("qdro_case_id")
    status = v.query_enum("status", enums.HOLD_STATUSES)
    rows = order_by(list(db.segregation_holds.values()), "placed_at")
    if account_id is not None:
        rows = [r for r in rows if r["plan_account_id"] == account_id]
    if case_id is not None:
        rows = [r for r in rows if r["qdro_case_id"] == case_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if caller.is_participant:
        owned = {a["id"] for a in db.plan_accounts.values()
                 if a["participant_id"] == caller.user_id}
        rows = [r for r in rows if r["plan_account_id"] in owned]
    return paginate(public_list(rows))


@bp.route("/segregation-holds/<id>/release", methods=["POST"])
@endpoint("PlanAdministrator")
def release_hold(caller, id):
    hold = find_hold(id)
    case = db.qdro_cases[hold["qdro_case_id"]]
    if hold["status"] != "HELD":
        errors.fail(errors.ERR_HOLD_NOT_HELD, "The segregation hold is not HELD.")
    if case["review_status"] != "DENIED":
        errors.fail(errors.ERR_CASE_NOT_DENIED,
                    "The hold's case has not reached a DENIED review status.")
    if not services.drafts_of_case(case["id"]):
        errors.fail(errors.ERR_NO_ACTIVE_DRAFT_ORDER,
                    "The case has no draft order to release funds against.")
    hold["status"] = "RELEASED"
    db.touch(hold)
    account = db.plan_accounts.get(hold["plan_account_id"])
    if account is not None:
        services.recompute_plan_account(account, force=True)
    case["segregation_status"] = "RELEASED_TO_PARTICIPANT"
    services.append_party_pair(case, "RELEASE_NOTICE", "LIMITED")
    db.touch(case)
    return object_response(public(hold))
