"""Change-in-control event endpoints."""
from flask import Blueprint, request

import db
from errors import (
    ERR_PLAN_NOT_ACTIVE,
    ERR_CIC_STATE_INVALID,
    ERR_CIC_THRESHOLD_NOT_MET,
    raise_err,
)
from middleware import user_context, require_role
from response import ok_object
from routes.plans import _list_response
from routes.distribution_requests import make_request
from services.core import (
    body,
    req_date,
    req_int,
    req_enum,
    get_or_404,
    stamp_new,
    touch,
    recompute_account_balances,
    recompute_trust,
)
from util import CLOCK, fmt_date

bp = Blueprint("cic", __name__)

EVENT_TYPES = {"OWNERSHIP_CHANGE", "EFFECTIVE_CONTROL_CHANGE", "ASSET_CHANGE"}
THRESHOLDS = {
    "OWNERSHIP_CHANGE": 5000,
    "EFFECTIVE_CONTROL_CHANGE": 3500,
    "ASSET_CHANGE": 4000,
}


def cic_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "plan_id": c["plan_id"],
        "event_type": c["event_type"],
        "effective_date": c["effective_date"],
        "stake_change_bp": c["stake_change_bp"],
        "status": c["status"],
        "verified_by_user_id": c["verified_by_user_id"],
    }


@bp.post("/api/change-in-control-events")
def create_cic():
    data = body()
    from errors import ERR_INVALID_REQUEST

    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise_err(ERR_INVALID_REQUEST, "plan_id is required and must be a string")
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    effective = req_date(data, "effective_date")
    stake = req_int(data, "stake_change_bp", 0, 10000)

    user_id, role = user_context()
    require_role(role, {"PlanSponsor"})
    plan = get_or_404(db.plans, plan_id, "Plan")
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to report a change in control")

    cic = stamp_new(
        {
            "plan_id": plan_id,
            "event_type": event_type,
            "effective_date": fmt_date(effective),
            "stake_change_bp": stake,
            "status": "REPORTED",
            "verified_by_user_id": None,
        }
    )
    db.change_in_control_events[cic["id"]] = cic
    return ok_object(cic_view(cic), 201)


@bp.get("/api/change-in-control-events")
def list_cics():
    user_context()
    items = list(db.change_in_control_events.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [c for c in items if c["plan_id"] == plan_id]
    return _list_response([cic_view(c) for c in items], request.args)


@bp.get("/api/change-in-control-events/<cicId>")
def get_cic(cicId):
    user_context()
    c = get_or_404(db.change_in_control_events, cicId, "ChangeInControlEvent")
    return ok_object(cic_view(c))


@bp.post("/api/change-in-control-events/<cicId>/adjudicate")
def adjudicate_cic(cicId):
    data = body()
    outcome = req_enum(data, "outcome", {"VERIFIED", "REJECTED"})

    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    cic = get_or_404(db.change_in_control_events, cicId, "ChangeInControlEvent")

    if cic["status"] != "REPORTED":
        raise_err(ERR_CIC_STATE_INVALID, "Adjudicate requires REPORTED")

    if outcome == "VERIFIED":
        if cic["stake_change_bp"] < THRESHOLDS[cic["event_type"]]:
            raise_err(ERR_CIC_THRESHOLD_NOT_MET, "stake_change_bp is below the threshold for the event type")

    cic["status"] = outcome
    cic["verified_by_user_id"] = user_id

    if outcome == "VERIFIED":
        plan = db.plans[cic["plan_id"]]
        # Cascade 1: trust escalates to 125% funding requirement
        for trust in db.rabbi_trusts.values():
            if trust["plan_id"] == cic["plan_id"]:
                trust["cic_funding_required"] = True
                recompute_trust(trust)
                touch(trust)
        # Cascade 2: acceleration distribution requests
        if plan["accelerate_on_cic"]:
            accounts = [
                a
                for a in db.accounts.values()
                if a["plan_id"] == cic["plan_id"] and a["status"] in ("ACTIVE", "FLAGGED_FOR_INCLUSION")
            ]
            accounts.sort(key=lambda a: a["created_at"])
            for account in accounts:
                recompute_account_balances(account)
                if account["vested_balance_cents"] > 0:
                    make_request(
                        account_id=account["id"],
                        participant_id=account["participant_id"],
                        event_type="CHANGE_IN_CONTROL",
                        requested=None,
                        fixed_date=None,
                        emergency_need=None,
                        case_id=None,
                        cic_id=cic["id"],
                        status="EVENT_VERIFIED",
                        verified_at=fmt_date(CLOCK.date()),
                    )

    touch(cic)
    return ok_object(cic_view(cic))
