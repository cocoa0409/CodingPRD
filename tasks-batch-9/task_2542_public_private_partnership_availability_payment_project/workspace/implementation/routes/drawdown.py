"""Drawdown milestones: request, certify, refuse, disburse (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint

import calc
from db import db, insert, public, setf, touch
from errors import fail
from middleware import (ROLE_CONCESSIONAIRE, ROLE_INDEPENDENT_CERTIFIER,
                        ROLE_LENDER_AGENT, body, concession_of, get_concession,
                        get_milestone, owner_guard, req_int, req_str, require_auth)
from response import created, ok

bp = Blueprint("drawdown", __name__)

DRAWDOWN_STATES = ("FINANCIAL_CLOSE", "CONSTRUCTION")


@bp.post("/ppp/concessions/<row_id>/drawdown-milestones")
def create_milestone(row_id):
    require_auth(ROLE_CONCESSIONAIRE)
    concession = get_concession(row_id)
    owner_guard(concession)
    data = body()
    milestone_name = req_str(data, "milestone_name", max_len=200)
    requested = req_int(data, "requested_amount_cents", minimum=1)
    expected = req_int(data, "expected_concession_version", minimum=0)
    if expected != concession["version"]:
        fail("ERR_STALE_CONCESSION_VERSION")
    if concession["status"] not in DRAWDOWN_STATES:
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    calc.enforcement_freeze_guard(concession)

    existing = [m for m in db.all("milestones") if m["concession_id"] == concession["id"]]
    seq = (max(m["sequence_no"] for m in existing) + 1) if existing else 1
    row = insert("milestones", {
        "concession_id": concession["id"],
        "sequence_no": seq,
        "milestone_name": milestone_name,
        "requested_amount_cents": requested,
        "certified_cost_cents": 0,
        "status": "REQUESTED",
        "equity_portion_cents": None,
        "debt_portion_cents": None,
        "rejection_reason": None,
        "approved_at": None,
        "disbursed_at": None,
    })
    touch(concession)
    return created(public(row))


@bp.post("/ppp/drawdown-milestones/<row_id>/approve")
def approve_milestone(row_id):
    require_auth(ROLE_INDEPENDENT_CERTIFIER)
    milestone = get_milestone(row_id)
    concession = concession_of(milestone)
    data = body()
    certified = req_int(data, "certified_cost_cents", minimum=0)
    if milestone["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if concession["status"] not in DRAWDOWN_STATES:
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    equity_portion, debt_portion = calc.drawdown_split(concession, certified)
    calc.commitment_guard(concession, equity_portion, debt_portion)

    setf(milestone, "certified_cost_cents", certified)
    setf(milestone, "equity_portion_cents", equity_portion)
    setf(milestone, "debt_portion_cents", debt_portion)
    setf(milestone, "approved_at", db.now_str())
    setf(milestone, "status", "APPROVED")
    return ok(public(milestone))


@bp.post("/ppp/drawdown-milestones/<row_id>/reject")
def reject_milestone(row_id):
    require_auth(ROLE_INDEPENDENT_CERTIFIER)
    milestone = get_milestone(row_id)
    data = body()
    reason = req_str(data, "rejection_reason", max_len=2000)
    if milestone["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    setf(milestone, "rejection_reason", reason)
    setf(milestone, "equity_portion_cents", None)
    setf(milestone, "debt_portion_cents", None)
    setf(milestone, "approved_at", None)
    setf(milestone, "disbursed_at", None)
    setf(milestone, "status", "REJECTED")
    return ok(public(milestone))


@bp.post("/ppp/drawdown-milestones/<row_id>/disburse")
def disburse_milestone(row_id):
    require_auth(ROLE_LENDER_AGENT)
    milestone = get_milestone(row_id)
    concession = concession_of(milestone)
    if milestone["status"] != "APPROVED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if concession["status"] not in DRAWDOWN_STATES:
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    calc.enforcement_freeze_guard(concession)

    setf(milestone, "disbursed_at", db.now_str())
    setf(milestone, "status", "DISBURSED")

    setf(concession, "equity_drawn_cents",
         concession["equity_drawn_cents"] + (milestone["equity_portion_cents"] or 0))
    setf(concession, "senior_debt_drawn_cents",
         concession["senior_debt_drawn_cents"] + (milestone["debt_portion_cents"] or 0))
    ratio = calc.cumulative_drawn(concession)
    setf(concession, "cumulative_drawn_pct", float(ratio))
    if concession["status"] == "FINANCIAL_CLOSE" and ratio >= calc.CONSTRUCTION_START_PCT:
        setf(concession, "status", "CONSTRUCTION")
        seed = calc.rhu(Decimal(concession["total_project_cost_cents"])
                        * calc.CONSTRUCTION_SEED_PCT)
        calc.append_ledger(concession, "CONTRIBUTION", seed, "CONSTRUCTION_SEED", "SYSTEM")
    return ok(public(milestone))
