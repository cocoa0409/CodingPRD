"""Construction draws and the negative-arbitrage series (PRD 3.6)."""

from flask import Blueprint

import calc
import domain
import serialize
import validation as v
from auth import guard, own_project
from envelope import object_response
from errors import fail
from store import db, new_row, parse_iso, touch

bp = Blueprint("draws", __name__)

BLOCKING_DRAW_STATUSES = ("SUBMITTED", "APPROVED", "FUNDED")


def _require_issue_open(issue):
    if issue.get("status") != "ISSUED":
        fail("ERR_BOND_ISSUE_STATE_INVALID",
             "The bond issue is %s, not ISSUED." % issue.get("status"))


@bp.post("/draw-requests")
def create_draw():
    caller = guard("POST /draw-requests")
    body = v.body()
    issue = domain.soft_get(db.bond_issues, body.get("bond_issue_id"))
    own_project(caller, domain.project_of_row(issue))

    bond_issue_id = v.req_id(body, "bond_issue_id")
    draw_number = v.req_int(body, "draw_number", minimum=1)
    start_raw, start_dt = v.req_dt(body, "period_start")
    end_raw, end_dt = v.req_dt(body, "period_end")
    requested_amount_cents = v.req_int(body, "requested_amount_cents", minimum=1)
    expected_version = v.req_int(body, "expected_bond_issue_version")
    if end_dt <= start_dt:
        fail("ERR_INVALID_REQUEST", "period_end must be strictly after period_start.")

    issue = domain.get_or_404(db.bond_issues, bond_issue_id, "ERR_BOND_ISSUE_NOT_FOUND")
    project = domain.project_of_row(issue)
    own_project(caller, project)

    if expected_version != issue.get("version"):
        fail("ERR_STALE_BOND_ISSUE_VERSION",
             "expected_bond_issue_version %s does not match the issue's current version %s."
             % (expected_version, issue.get("version")))

    domain.require_developer_active(project)
    _require_issue_open(issue)

    for other in calc.issue_draws(bond_issue_id):
        if other.get("status") not in BLOCKING_DRAW_STATUSES:
            continue
        other_start = parse_iso(other.get("period_start"))
        other_end = parse_iso(other.get("period_end"))
        if other_start is None or other_end is None:
            continue
        if start_dt < other_end and other_start < end_dt:
            fail("ERR_DRAW_PERIOD_OVERLAP",
                 "The funding period overlaps draw %s." % other.get("draw_number"))

    undrawn = calc.issue_ledger(issue)["undrawn_cents"]
    if requested_amount_cents > undrawn:
        fail("ERR_DRAW_EXCEEDS_UNDRAWN",
             "The requested amount exceeds the undrawn proceeds of %d cents." % undrawn)

    row = new_row(db.draws, {
        "bond_issue_id": bond_issue_id,
        "draw_number": draw_number,
        "period_start": start_raw,
        "period_end": end_raw,
        "requested_amount_cents": requested_amount_cents,
        "approved_amount_cents": None,
        "status": "SUBMITTED",
        "funding_date": None,
        "rejection_reason": None,
        "void_reason": None,
        "negative_arbitrage_accrual_cents": 0,
    })
    touch(issue)
    return object_response(serialize.draw(row), 201)


@bp.post("/draw-requests/<row_id>/decision")
def decide_draw(row_id):
    guard("POST /draw-requests/{id}/decision")
    body = v.body()
    decision = v.req_enum(body, "decision", ("APPROVE", "REJECT"))
    approved_amount_cents = None
    rejection_reason = None
    if decision == "APPROVE":
        approved_amount_cents = v.req_int(body, "approved_amount_cents", minimum=0)
    else:
        rejection_reason = v.req_str(body, "rejection_reason", allow_empty=False)

    draw = domain.get_or_404(db.draws, row_id, "ERR_DRAW_REQUEST_NOT_FOUND")
    issue = domain.get_or_404(db.bond_issues, draw.get("bond_issue_id"),
                              "ERR_BOND_ISSUE_NOT_FOUND")

    if draw.get("status") != "SUBMITTED":
        fail("ERR_DRAW_STATE_INVALID",
             "A draw in %s cannot be decided." % draw.get("status"))
    _require_issue_open(issue)

    if decision == "APPROVE":
        if approved_amount_cents > (draw.get("requested_amount_cents") or 0):
            fail("ERR_DRAW_EXCEEDS_UNDRAWN",
                 "The approved amount exceeds the amount requested.")
        undrawn = calc.issue_ledger(issue)["undrawn_cents"]
        if approved_amount_cents > undrawn:
            fail("ERR_DRAW_EXCEEDS_UNDRAWN",
                 "The approved amount exceeds the undrawn proceeds of %d cents." % undrawn)
        draw["status"] = "APPROVED"
        draw["approved_amount_cents"] = approved_amount_cents
    else:
        draw["status"] = "REJECTED"
        draw["rejection_reason"] = rejection_reason
    touch(draw)
    return object_response(serialize.draw(draw))


@bp.post("/draw-requests/<row_id>/fund")
def fund_draw(row_id):
    guard("POST /draw-requests/{id}/fund")
    body = v.body()
    funding_raw, _funding_dt = v.req_dt(body, "funding_date")

    draw = domain.get_or_404(db.draws, row_id, "ERR_DRAW_REQUEST_NOT_FOUND")
    issue = domain.get_or_404(db.bond_issues, draw.get("bond_issue_id"),
                              "ERR_BOND_ISSUE_NOT_FOUND")

    if draw.get("status") != "APPROVED":
        fail("ERR_DRAW_STATE_INVALID",
             "Only an APPROVED draw may be funded.")
    _require_issue_open(issue)

    ledger = calc.issue_ledger(issue)
    approved = draw.get("approved_amount_cents") or 0
    if approved > ledger["undrawn_cents"]:
        fail("ERR_DRAW_EXCEEDS_UNDRAWN",
             "The approved amount exceeds the undrawn proceeds of %d cents."
             % ledger["undrawn_cents"])

    projected, _accruals = calc.negative_arbitrage_series(issue, extra_draw=draw)
    allowance = issue.get("negative_arbitrage_allowance_cents") or 0
    if projected > allowance:
        fail("ERR_NEGATIVE_ARBITRAGE_ALLOWANCE_EXCEEDED",
             "Projected negative arbitrage of %d cents exceeds the allowance of %d cents."
             % (projected, allowance))

    first_funding = ledger["cumulative_funded_cents"] == 0

    draw["status"] = "FUNDED"
    draw["funding_date"] = funding_raw
    touch(draw)

    domain.recompute_negative_arbitrage(issue)
    touch(issue)

    project = domain.project_of_row(issue)
    if first_funding and project is not None:
        if project.get("development_status") == "FINANCED":
            project["development_status"] = "UNDER_CONSTRUCTION"
            touch(project)

    return object_response(serialize.draw(draw))


@bp.post("/draw-requests/<row_id>/void")
def void_draw(row_id):
    guard("POST /draw-requests/{id}/void")
    body = v.body()
    void_reason = v.req_str(body, "void_reason", allow_empty=False)

    draw = domain.get_or_404(db.draws, row_id, "ERR_DRAW_REQUEST_NOT_FOUND")
    issue = domain.get_or_404(db.bond_issues, draw.get("bond_issue_id"),
                              "ERR_BOND_ISSUE_NOT_FOUND")

    if draw.get("status") != "FUNDED":
        fail("ERR_DRAW_STATE_INVALID", "Only a FUNDED draw may be voided.")
    _require_issue_open(issue)

    draw["status"] = "VOIDED"
    draw["void_reason"] = void_reason
    draw["funding_date"] = None
    draw["negative_arbitrage_accrual_cents"] = 0
    touch(draw)

    domain.recompute_negative_arbitrage(issue)
    touch(issue)
    return object_response(serialize.draw(draw))
