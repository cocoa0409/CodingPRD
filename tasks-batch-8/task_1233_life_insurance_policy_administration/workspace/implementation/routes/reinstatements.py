"""ReinstatementRequest endpoints (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint

import domain
import errors
from db import store
from middleware import require_auth, json_body, require_int, ALL_ROLES
from response import ok_object
from routes.policies import get_policy_or_404, _paged
from services import calculations as calc
from services import engine
from util import add_months

bp = Blueprint("reinstatements", __name__)


def get_reinstatement_or_404(policy, rid):
    req = store.reinstatement_requests.get(rid)
    if req is None or req["policy_id"] != policy["id"]:
        raise errors.not_found(errors.ERR_REINSTATEMENT_NOT_FOUND, "reinstatement request")
    return req


@bp.route("/policies/<policy_id>/reinstatement-requests", methods=["POST"])
def create_reinstatement(policy_id):
    ctx = require_auth(["Agent"])
    policy = get_policy_or_404(policy_id)
    if policy["form_status"] in domain.POLICY_FORM_TERMINAL:
        raise errors.already_terminal("Policy is in a terminal form state")
    if policy["form_status"] != "IN_FORCE":
        raise errors.invalid_state("Reinstatement requires form_status IN_FORCE")
    if policy["premium_payment_status"] != "LAPSED":
        raise errors.invalid_state("Reinstatement requires premium_payment_status LAPSED")
    # Five-year window from the lapse date (priority 6). PRD §3.9: "The lapse
    # date is the policy's paid_to_date — the last date through which
    # premiums were fully paid."
    lapse_date = policy["paid_to_date"]
    if store.current_date() > lapse_date + timedelta(days=domain.FIVE_YEARS_DAYS):
        raise errors.window_expired("Reinstatement window (5 years from lapse) has passed")
    # No prior open request on this policy
    for r in store.reinstatement_requests.values():
        if r["policy_id"] == policy["id"] and r["status"] in ("PENDING", "EVIDENCE_REQUIRED"):
            raise errors.invalid_state(
                "An open reinstatement request already exists on this policy")

    due, n_periods = calc.back_premium_due(policy)
    req = domain.stamp_new({
        "policy_id": policy["id"],
        "request_date": store.current_date(),
        "back_premium_due_cents": due,
        "back_premium_paid_cents": 0,
        "evidence_of_insurability": False,
        "underwriter_decision": "PENDING",
        "status": "PENDING",
        "_requester_user_id": ctx.user_id,
        "_n_periods_owed": n_periods,
    })
    store.reinstatement_requests[req["id"]] = req
    policy["premium_payment_status"] = "REINSTATED_PENDING"
    domain.touch_policy(policy)
    return ok_object(domain.serialize_reinstatement(req), status=201)


@bp.route("/policies/<policy_id>/reinstatement-requests", methods=["GET"])
def list_policy_reinstatements(policy_id):
    require_auth(ALL_ROLES)
    policy = get_policy_or_404(policy_id)
    return _paged([r for r in store.reinstatement_requests.values()
                   if r["policy_id"] == policy["id"]], domain.serialize_reinstatement)


@bp.route("/policies/<policy_id>/reinstatement-requests/<rid>/payments", methods=["POST"])
def pay_reinstatement(policy_id, rid):
    require_auth(["Agent"])
    policy = get_policy_or_404(policy_id)
    req = get_reinstatement_or_404(policy, rid)
    if req["status"] in domain.REINSTATEMENT_TERMINAL:
        raise errors.already_terminal("Reinstatement request is in a terminal state")
    body = json_body(required=True)
    amount = require_int(body, "amount_cents", minimum=1)
    # Payment must cover the full back premium due (priority 12)
    if amount < req["back_premium_due_cents"]:
        raise errors.insufficient_payment()
    req["back_premium_paid_cents"] += amount
    domain.touch(req)
    return ok_object(domain.serialize_reinstatement(req))


@bp.route("/policies/<policy_id>/reinstatement-requests/<rid>/request-evidence", methods=["POST"])
def reinstatement_request_evidence(policy_id, rid):
    require_auth(["Underwriter"])
    policy = get_policy_or_404(policy_id)
    req = get_reinstatement_or_404(policy, rid)
    if req["status"] in domain.REINSTATEMENT_TERMINAL:
        raise errors.already_terminal("Reinstatement request is in a terminal state")
    if req["status"] != "PENDING":
        raise errors.invalid_state("Request must be PENDING to request evidence")
    req["status"] = "EVIDENCE_REQUIRED"
    domain.touch(req)
    return ok_object(domain.serialize_reinstatement(req))


@bp.route("/policies/<policy_id>/reinstatement-requests/<rid>/submit-evidence", methods=["POST"])
def reinstatement_submit_evidence(policy_id, rid):
    require_auth(["Agent"])
    policy = get_policy_or_404(policy_id)
    req = get_reinstatement_or_404(policy, rid)
    if req["status"] in domain.REINSTATEMENT_TERMINAL:
        raise errors.already_terminal("Reinstatement request is in a terminal state")
    if req["status"] != "EVIDENCE_REQUIRED":
        raise errors.invalid_state("Request must be EVIDENCE_REQUIRED to submit evidence")
    req["status"] = "PENDING"
    req["evidence_of_insurability"] = True
    domain.touch(req)
    return ok_object(domain.serialize_reinstatement(req))


@bp.route("/policies/<policy_id>/reinstatement-requests/<rid>/approve", methods=["POST"])
def approve_reinstatement(policy_id, rid):
    ctx = require_auth(["Underwriter"])
    policy = get_policy_or_404(policy_id)
    req = get_reinstatement_or_404(policy, rid)
    if req["status"] in domain.REINSTATEMENT_TERMINAL:
        raise errors.already_terminal("Reinstatement request is in a terminal state")
    if req["status"] != "PENDING":
        raise errors.invalid_state("Request must be PENDING to approve")
    # Segregation of duties: approver != requesting agent (priority 5)
    if req.get("_requester_user_id") == ctx.user_id:
        raise errors.segregation(
            "Approving underwriter must differ from the requesting agent")
    body = json_body()
    if not req["evidence_of_insurability"]:
        raise errors.invalid_state("Evidence of insurability is required")
    if req["back_premium_paid_cents"] < req["back_premium_due_cents"]:
        raise errors.insufficient_payment()

    req["status"] = "APPROVED"
    req["underwriter_decision"] = "APPROVED"
    domain.touch(req)

    # Policy returns to CURRENT; paid_to_date advances by the paid modal premiums
    months = domain.MODE_MONTHS[policy["premium_mode"]]
    n_periods = req.get("_n_periods_owed", 0)
    policy["premium_payment_status"] = "CURRENT"
    policy["grace_period_end_date"] = policy.get("grace_period_end_date")
    if n_periods > 0:
        policy["paid_to_date"] = add_months(policy["paid_to_date"], n_periods * months)
    builds = domain.policy_builds_cash_value(policy)
    paid = req["back_premium_paid_cents"]
    if paid > 0:
        engine.post_ledger(policy, domain.ENTRY_PREMIUM_CREDIT, paid,
                           change_cents=(paid if builds else 0))

    # Cascade: WAIVER_OF_PREMIUM riders terminated at lapse revert when requested
    if body.get("rider_reinstatement") is True:
        for rider in engine.policy_riders(policy):
            if (rider["rider_type"] == "WAIVER_OF_PREMIUM"
                    and rider["status"] == "TERMINATED"
                    and rider.get("_cascade") == "lapse"):
                rider["status"] = "ACTIVE"
                rider["_cascade"] = None
                domain.touch(rider)
    domain.touch_policy(policy)
    return ok_object(domain.serialize_reinstatement(req))


@bp.route("/policies/<policy_id>/reinstatement-requests/<rid>/decline", methods=["POST"])
def decline_reinstatement(policy_id, rid):
    require_auth(["Underwriter"])
    policy = get_policy_or_404(policy_id)
    req = get_reinstatement_or_404(policy, rid)
    if req["status"] in domain.REINSTATEMENT_TERMINAL:
        raise errors.already_terminal("Reinstatement request is in a terminal state")
    if req["status"] != "PENDING":
        raise errors.invalid_state("Request must be PENDING to decline")
    req["status"] = "DECLINED"
    req["underwriter_decision"] = "DECLINED"
    domain.touch(req)
    # The policy falls back to LAPSED
    if policy["premium_payment_status"] == "REINSTATED_PENDING":
        policy["premium_payment_status"] = "LAPSED"
        domain.touch_policy(policy)
    return ok_object(domain.serialize_reinstatement(req))


# ---------------------------------------------------------------------------
# Flat filtered listings
# ---------------------------------------------------------------------------
@bp.route("/reinstatement-requests", methods=["GET"])
def list_all_reinstatements():
    require_auth(ALL_ROLES)
    from flask import request
    records = list(store.reinstatement_requests.values())
    policy_id = request.args.get("policy_id")
    if policy_id is not None:
        records = [r for r in records if r["policy_id"] == policy_id]
    return _paged(records, domain.serialize_reinstatement)


@bp.route("/reinstatement-requests/<row_id>", methods=["GET"])
def get_reinstatement_flat(row_id):
    require_auth(ALL_ROLES)
    row = store.reinstatement_requests.get(row_id)
    if row is None:
        raise errors.not_found(errors.ERR_REINSTATEMENT_NOT_FOUND, "reinstatement request")
    return ok_object(domain.serialize_reinstatement(row))
