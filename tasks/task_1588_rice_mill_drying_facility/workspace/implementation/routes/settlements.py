"""Settlement endpoints (PRD §3.8)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_GROWER_NOT_FOUND, ERR_SETTLEMENT_PERIOD_EMPTY,
    ERR_SETTLEMENT_INVALID_STATE, ERR_INVALID_SEASON_STATE,
    ERR_SEASON_NOT_SETTLEMENT_REVIEW, ERR_SOD_APPROVER_IS_CREATOR,
)
from middleware import authorized, check_grower_scope
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import new_id, next_seq, parse_date
from validate import get_body, req_str, req_date

bp = Blueprint("settlements", __name__)


@bp.route("/mill/settlements", methods=["POST"])
def create_settlement():
    caller = authorized(["SettlementClerk"])
    body = get_body()
    season_id = req_str(body, "season_id")
    grower_id = req_str(body, "grower_id")
    period_start = req_date(body, "period_start_date")
    period_end = req_date(body, "period_end_date")
    require_resource("seasons", season_id)
    grower = db["growers"].get(grower_id)
    if grower is None or grower["season_id"] != season_id:
        raise_error(ERR_GROWER_NOT_FOUND, "grower not found in this season")
    start = parse_date(period_start)
    end = parse_date(period_end)
    eligible = []
    for lot in db["lots"].values():
        if (lot["season_id"] == season_id and lot["grower_id"] == grower_id
                and lot["status"] == "BINNED" and lot.get("settlement_id") is None
                and lot.get("graded_date") is not None
                and start <= parse_date(lot["graded_date"]) <= end):
            eligible.append(lot)
    eligible.sort(key=lambda r: r["_seq"])
    if not eligible:
        raise_error(ERR_SETTLEMENT_PERIOD_EMPTY,
                    "no eligible BINNED unsettled lots for this grower in the period")
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "season_id": season_id,
        "grower_id": grower_id,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "lot_ids": [l["id"] for l in eligible],
        "created_by_user_id": caller.user_id,
        "provisional_gross_cents": None,
        "provisional_drying_cents": None,
        "provisional_checkoff_cents": None,
        "provisional_advance_repay_cents": None,
        "provisional_net_cents": None,
        "final_gross_cents": None,
        "final_drying_cents": None,
        "final_checkoff_cents": None,
        "final_advance_repay_cents": None,
        "final_net_cents": None,
        "dispute_reason": None,
        "status": "DRAFT",
    }
    core.touch_new(rec)
    db["settlements"][rec["id"]] = rec
    for lot in eligible:
        lot["settlement_id"] = rec["id"]
        core.bump(lot)
    core.compute_provisional(rec)
    return success_object(public(rec), 201)


@bp.route("/mill/settlements", methods=["GET"])
def list_settlements():
    return list_endpoint("settlements", ["season_id", "grower_id", "status"])


@bp.route("/mill/settlements/<rid>", methods=["GET"])
def get_settlement(rid):
    return get_endpoint("settlements", rid)


@bp.route("/mill/settlements/<rid>/issue-provisional", methods=["POST"])
def issue_provisional(rid):
    authorized(["SettlementClerk"])
    st = require_resource("settlements", rid)
    if st["status"] != "DRAFT":
        raise_error(ERR_SETTLEMENT_INVALID_STATE,
                    f"issue-provisional requires DRAFT; settlement is {st['status']}")
    season = db["seasons"][st["season_id"]]
    if season["status"] not in ("INTAKE_CLOSED", "SETTLEMENT_REVIEW"):
        raise_error(ERR_INVALID_SEASON_STATE,
                    "issue-provisional requires the season INTAKE_CLOSED or SETTLEMENT_REVIEW")
    st["status"] = "PROVISIONAL_ISSUED"
    core.bump(st)
    return success_object(public(st))


@bp.route("/mill/settlements/<rid>/approve", methods=["POST"])
def approve_settlement(rid):
    caller = authorized(["SettlementClerk"])
    st = require_resource("settlements", rid)
    # Segregation of duties (identity priority 3): approver must differ from creator.
    if caller.user_id == st["created_by_user_id"]:
        raise_error(ERR_SOD_APPROVER_IS_CREATOR,
                    "the approving clerk must differ from the settlement creator")
    if st["status"] != "PROVISIONAL_ISSUED":
        raise_error(ERR_SETTLEMENT_INVALID_STATE,
                    f"approve requires PROVISIONAL_ISSUED; settlement is {st['status']}")
    season = db["seasons"][st["season_id"]]
    if season["status"] != "SETTLEMENT_REVIEW":
        raise_error(ERR_SEASON_NOT_SETTLEMENT_REVIEW,
                    "approve requires the season in SETTLEMENT_REVIEW")
    core.compute_final(st)
    for lid in st["lot_ids"]:
        lot = db["lots"].get(lid)
        if lot is not None and lot["status"] == "BINNED":
            lot["status"] = "SETTLED"
            core.bump(lot)
    st["status"] = "APPROVED"
    core.bump(st)
    return success_object(public(st))


@bp.route("/mill/settlements/<rid>/pay", methods=["POST"])
def pay_settlement(rid):
    authorized(["SettlementClerk"])
    st = require_resource("settlements", rid)
    if st["status"] != "APPROVED":
        raise_error(ERR_SETTLEMENT_INVALID_STATE,
                    f"pay requires APPROVED; settlement is {st['status']}")
    grower = db["growers"].get(st["grower_id"])
    if grower is not None:
        grower["advance_outstanding_cents"] = int(grower["advance_outstanding_cents"]) - int(st["final_advance_repay_cents"])
        grower["cumulative_paid_cents"] = int(grower["cumulative_paid_cents"]) + int(st["final_net_cents"])
        core.bump(grower)
    st["status"] = "PAID"
    core.bump(st)
    return success_object(public(st))


@bp.route("/mill/settlements/<rid>/dispute", methods=["POST"])
def dispute_settlement(rid):
    caller = authorized(["SettlementClerk", "GrowerRep"])
    st = db["settlements"].get(rid)
    if st is not None:
        # Identity scoping for GrowerRep once the target is known (priority 3).
        check_grower_scope(caller, st["grower_id"])
    body = get_body()
    reason = req_str(body, "dispute_reason")
    if st is None:
        st = require_resource("settlements", rid)
    if st["status"] not in ("PROVISIONAL_ISSUED", "APPROVED"):
        raise_error(ERR_SETTLEMENT_INVALID_STATE,
                    f"dispute requires PROVISIONAL_ISSUED or APPROVED; settlement is {st['status']}")
    was_approved = st["status"] == "APPROVED"
    st["status"] = "DISPUTED"
    st["dispute_reason"] = reason
    core.bump(st)
    if was_approved:
        for lid in st["lot_ids"]:
            lot = db["lots"].get(lid)
            if lot is not None and lot["status"] == "SETTLED":
                lot["status"] = "BINNED"
                core.bump(lot)
    core.season_revert_on_dispute(st["season_id"])
    return success_object(public(st))


@bp.route("/mill/settlements/<rid>/revise", methods=["POST"])
def revise_settlement(rid):
    authorized(["SettlementClerk"])
    st = require_resource("settlements", rid)
    if st["status"] != "DISPUTED":
        raise_error(ERR_SETTLEMENT_INVALID_STATE,
                    f"revise requires DISPUTED; settlement is {st['status']}")
    core.compute_provisional(st)
    st["status"] = "DRAFT"
    core.bump(st)
    return success_object(public(st))
