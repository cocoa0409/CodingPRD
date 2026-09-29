"""Tuition accounts: the two assessment variants, the aid dimension and payments."""

from flask import Blueprint, request

import calc
import services as svc
from auth import ALL_ROLES, acting, endpoint, require_guardian_owns
from envelope import ok, ok_list
from errors import ApiError
from store import db
from validate import Body, pagination

bp = Blueprint("tuition", __name__)

AID_REQUESTABLE = ("NONE", "DENIED", "RESCINDED")


@bp.route("/tuition-accounts", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_accounts():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.tuition_accounts.values())),
                             request.args,
                             ["member_id", "season_id", "billing_status", "aid_status"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.account_json(r) for r in page], limit, offset, len(rows))


@bp.route("/tuition-accounts/<account_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_account(account_id):
    return ok(svc.account_json(svc.account_or_404(account_id)))


def _accepted_placement(account):
    """The member's ACCEPTED placement inside the account's season, if any."""
    for placement in svc.ordered(list(db.placements.values())):
        if placement["member_id"] != account["member_id"]:
            continue
        if placement["status"] != "ACCEPTED":
            continue
        ensemble = db.ensembles.get(placement["ensemble_id"])
        if ensemble is not None and ensemble["season_id"] == account["season_id"]:
            return placement
    return None


@bp.route("/tuition-accounts/<account_id>/finalize-assessment", methods=["POST"])
@endpoint("FinanceOfficer")
def finalize_assessment(account_id):
    account = svc.account_or_404(account_id)
    Body()

    placement = _accepted_placement(account)
    if account["assessment_variant"] != "PRELIMINARY" or placement is None:
        raise ApiError("ERR_ASSESSMENT_ALREADY_FINAL",
                       "The final assessment cannot run on this account.")

    season = db.seasons[account["season_id"]]
    member = db.members[account["member_id"]]
    gross = calc.gross_cents(season["tuition_base_cents"], account["ensemble_tier"])
    sibling = calc.sibling_discount(gross, member["sibling_enrolled"])
    loyalty = calc.loyalty_credit(gross, member["years_in_org"])

    account["assessment_variant"] = "FINAL"
    account["sibling_discount_cents"] = sibling
    account["loyalty_credit_cents"] = loyalty
    account["assessed_cents"] = gross - sibling - loyalty

    cap = calc.aid_cap(account["assessed_cents"], member["household_income_band"])
    effective = min(account["aid_awarded_cents"], cap)
    surplus = account["aid_awarded_cents"] - effective
    account["aid_effective_cents"] = effective
    if surplus:
        season["aid_committed_cents"] -= surplus
        svc.touch(season)

    svc.recompute_balance(account)
    svc.touch(account)
    svc.apply_billing_status(account)
    return ok(svc.account_json(account))


@bp.route("/tuition-accounts/<account_id>/aid-request", methods=["POST"])
@endpoint("Guardian")
def aid_request(account_id):
    account = svc.account_or_404(account_id)
    require_guardian_owns(account["member_id"])
    body = Body()
    requested = body.integer("aid_requested_cents", required=True)

    previous = account["aid_status"]
    if previous not in AID_REQUESTABLE:
        raise ApiError("ERR_AID_REQUEST_NOT_ALLOWED_IN_STATE",
                       "An aid request is not admissible from %s." % previous)

    if previous == "NONE":
        season = db.seasons[account["season_id"]]
        if season["status"] not in ("PLACEMENT", "IN_SEASON"):
            raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                           "A first aid request needs the season in PLACEMENT "
                           "or IN_SEASON.")

    if requested <= 0 or requested > account["assessed_cents"]:
        raise ApiError("ERR_AID_REQUEST_EXCEEDS_ASSESSMENT",
                       "The requested amount must fall in 1..assessed_cents.")

    account["aid_requested_cents"] = requested
    account["aid_status"] = "REQUESTED"
    account["aid_denial_reason"] = "NONE"
    if previous == "RESCINDED":
        account["aid_reviewed_by_user_id"] = None
        account["aid_awarded_by_user_id"] = None
    svc.touch(account)
    return ok(svc.account_json(account))


@bp.route("/tuition-accounts/<account_id>/aid-review", methods=["POST"])
@endpoint("FinanceOfficer")
def aid_review(account_id):
    account = svc.account_or_404(account_id)
    Body()

    if account["aid_status"] != "REQUESTED":
        raise ApiError("ERR_AID_REQUEST_NOT_ALLOWED_IN_STATE",
                       "Only a REQUESTED account may be opened for funding.")

    season = db.seasons[account["season_id"]]
    if season["aid_budget_cents"] <= 0:
        raise ApiError("ERR_NO_AID_BUDGET",
                       "This season has no aid pool to review against.")

    member = db.members[account["member_id"]]
    placement = _accepted_placement(account)
    loan_requested = bool(placement and placement["instrument_loan_requested"])

    user_id, _role = acting()
    account["aid_status"] = "UNDER_REVIEW"
    account["aid_reviewed_by_user_id"] = user_id
    account["aid_need_score"] = calc.aid_need_score(
        member["household_income_band"], member["sibling_enrolled"],
        member["years_in_org"], loan_requested, account["ensemble_tier"])
    svc.touch(account)
    return ok(svc.account_json(account))


@bp.route("/tuition-accounts/<account_id>/aid-rescind", methods=["POST"])
@endpoint("FinanceOfficer")
def aid_rescind(account_id):
    account = svc.account_or_404(account_id)
    Body()

    if account["aid_status"] != "APPROVED" or account["aid_awarded_cents"] <= 0:
        raise ApiError("ERR_AID_REQUEST_NOT_ALLOWED_IN_STATE",
                       "Only an APPROVED award above zero may be rescinded.")

    season = db.seasons[account["season_id"]]
    committed = account["aid_effective_cents"]
    account["aid_awarded_cents"] = 0
    account["aid_effective_cents"] = 0
    account["aid_status"] = "RESCINDED"
    season["aid_committed_cents"] -= committed
    svc.touch(season)

    svc.recompute_balance(account)
    svc.touch(account)
    svc.apply_billing_status(account)
    return ok(svc.account_json(account))


@bp.route("/tuition-accounts/<account_id>/payments", methods=["POST"])
@endpoint("Guardian")
def create_payment(account_id):
    account = svc.account_or_404(account_id)
    require_guardian_owns(account["member_id"])
    body = Body()
    amount = body.integer("amount_cents", required=True)

    if amount < 1 or amount > account["balance_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE",
                       "The payment must fall in 1..balance_cents.")

    account["payments_total_cents"] += amount
    svc.recompute_balance(account)
    svc.touch(account)
    svc.apply_billing_status(account)
    return ok(svc.account_json(account), 201)
