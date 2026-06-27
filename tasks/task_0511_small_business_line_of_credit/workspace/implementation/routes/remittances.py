"""Remittance routes (PRD §3.5). Schedule (overlap-checked), settle (FIFO
waterfall, NSF retry cycle, delinquency cascade, cure loop), cancel."""
from datetime import timedelta

from flask import Blueprint, request

import constants as C
import db
import serialize
from common import (parse_body, require_fields, parse_datetime, stamp_create, touch,
                    list_response, now, iso_millis)
from errors import (err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_REMITTANCE_NOT_DUE,
                    ERR_REMITTANCE_OVERLAP)
from lookups import get_credit_line, get_remittance
from middleware import auth_and_role
from response import object_response
from services import calc, ledger

bp = Blueprint("remittances", __name__)

OUTCOMES = {"SUCCESS", "NSF", "ACCOUNT_CLOSED"}
NON_TERMINAL_REM = {"SCHEDULED", "FAILED"}


@bp.post("/credit-lines/<rid>/remittances")
def schedule_remittance(rid):
    auth_and_role(["Servicer"])
    cl = get_credit_line(rid)
    body = parse_body()
    require_fields(body, ["scheduled_for"])
    sched_dt = parse_datetime(body["scheduled_for"])
    if sched_dt is None:
        raise err(ERR_INVALID_REQUEST, "scheduled_for must be a valid ISO8601 instant")

    # priority 14: overlap against other non-terminal remittances under cadence rule.
    cadence = cl["remittance_cadence"]
    if cadence == "DAILY":
        gap = timedelta(days=1)
    else:
        gap = timedelta(days=7)
    for other in db.remittances.values():
        if other["credit_line_id"] != cl["id"]:
            continue
        if other["status"] not in NON_TERMINAL_REM:
            continue
        other_dt = other["_scheduled_for_dt"]
        delta = abs((sched_dt - other_dt).total_seconds())
        if cadence == "DAILY":
            # >= 1 calendar day gap; half-open, exact adjacency (== gap) allowed.
            if delta < gap.total_seconds():
                raise err(ERR_REMITTANCE_OVERLAP, "Remittance window collides (daily cadence)")
        else:
            # >= 7 days gap; closed-interval, adjacency (== gap) rejected.
            if delta <= gap.total_seconds():
                raise err(ERR_REMITTANCE_OVERLAP, "Remittance window collides (weekly cadence)")

    record = {
        "credit_line_id": cl["id"],
        "scheduled_for": body["scheduled_for"],
        "amount_cents": 0,
        "principal_applied_cents": 0,
        "fee_applied_cents": 0,
        "attempt_count": 0,
        "status": "SCHEDULED",
        "failure_reason": None,
        "next_retry_remittance_id": None,
    }
    stamp_create(record)
    record["_scheduled_for_dt"] = sched_dt
    db.remittances[record["id"]] = record
    return object_response(serialize.remittance(record), 201)


@bp.get("/remittances/<rid>")
def fetch_remittance(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    r = get_remittance(rid)
    return object_response(serialize.remittance(r), 200)


@bp.get("/credit-lines/<rid>/remittances")
def list_remittances(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    get_credit_line(rid)
    status = request.args.get("status")
    rems = [r for r in db.remittances.values() if r["credit_line_id"] == rid]
    if status is not None:
        rems = [r for r in rems if r["status"] == status]
    return list_response(rems, serialize.remittance)


@bp.post("/remittances/<rid>/cancel")
def cancel_remittance(rid):
    auth_and_role(["Servicer"])
    r = get_remittance(rid)
    if r["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Remittance is not SCHEDULED")
    r["status"] = "CANCELLED"
    touch(r)
    return object_response(serialize.remittance(r), 200)


@bp.post("/remittances/<rid>/settle")
def settle_remittance(rid):
    auth_and_role(["Servicer"])
    r = get_remittance(rid)
    body = parse_body()
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in OUTCOMES:
        raise err(ERR_INVALID_REQUEST, "outcome must be SUCCESS, NSF, or ACCOUNT_CLOSED")

    cl = db.credit_lines[r["credit_line_id"]]

    # priority 6: state legality — remittance SCHEDULED, parent line ACTIVE/DELINQUENT.
    if r["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Remittance is not SCHEDULED")
    if cl["status"] not in ("ACTIVE", "DELINQUENT"):
        raise err(ERR_INVALID_STATE, "Parent line is not ACTIVE or DELINQUENT")
    # priority 13: due timing.
    if now() < r["_scheduled_for_dt"]:
        raise err(ERR_REMITTANCE_NOT_DUE, "Remittance is not yet due")

    # every settlement increments attempt_count and version.
    r["attempt_count"] += 1

    if outcome == "SUCCESS":
        _settle_success(r, cl)
    else:
        _settle_failure(r, cl, outcome)

    touch(r)
    return object_response(serialize.remittance(r), 200)


def _settle_success(r, cl):
    """FIFO waterfall allocation; fee-before-principal within each draw."""
    outstanding_total = cl["outstanding_principal_cents"] + cl["outstanding_fee_cents"]
    target = calc.remittance_target(outstanding_total=outstanding_total,
                                    cadence=cl["remittance_cadence"])
    amount = min(target, outstanding_total)

    remaining = amount
    principal_applied = 0
    fee_applied = 0
    draws_ordered = ledger.outstanding_draws_fifo(cl["id"])
    touched = []
    for d in draws_ordered:
        if remaining <= 0:
            break
        fee_due = d["fee_cents"] - d["fee_repaid_cents"]
        pay_fee = min(remaining, fee_due)
        if pay_fee > 0:
            d["fee_repaid_cents"] += pay_fee
            remaining -= pay_fee
            fee_applied += pay_fee
        prin_due = d["principal_cents"] - d["principal_repaid_cents"]
        pay_prin = min(remaining, prin_due)
        if pay_prin > 0:
            d["principal_repaid_cents"] += pay_prin
            remaining -= pay_prin
            principal_applied += pay_prin
        if pay_fee > 0 or pay_prin > 0:
            touched.append((d, pay_prin, pay_fee))

    r["principal_applied_cents"] = principal_applied
    r["fee_applied_cents"] = fee_applied
    r["amount_cents"] = principal_applied + fee_applied

    # ledger entries: PRINCIPAL_REPAYMENT and FEE_REPAYMENT.
    balance = ledger.current_principal_balance(cl["id"])
    if principal_applied > 0:
        balance = balance - principal_applied
        ledger.append_entry(
            credit_line_id=cl["id"], draw_id=None, remittance_id=r["id"],
            entry_type="PRINCIPAL_REPAYMENT", amount_cents=-principal_applied,
            balance_after_cents=balance,
        )
    if fee_applied > 0:
        ledger.append_entry(
            credit_line_id=cl["id"], draw_id=None, remittance_id=r["id"],
            entry_type="FEE_REPAYMENT", amount_cents=-fee_applied,
            balance_after_cents=balance,
        )

    # fully-repaid draws auto-transition OUTSTANDING -> REPAID.
    for d, _pp, _pf in touched:
        if (d["status"] == "OUTSTANDING"
                and d["principal_repaid_cents"] == d["principal_cents"]
                and d["fee_repaid_cents"] == d["fee_cents"]):
            d["status"] = "REPAID"
            touch(d)

    r["status"] = "SETTLED"

    # reset strikes; cure DELINQUENT -> ACTIVE.
    cl["nsf_strike_count"] = 0
    if cl["status"] == "DELINQUENT":
        cl["status"] = "ACTIVE"
    ledger.recompute_outstanding(cl)
    touch(cl)


def _settle_failure(r, cl, outcome):
    """NSF or ACCOUNT_CLOSED: bump strike, maybe spawn retry, maybe escalate."""
    r["failure_reason"] = outcome
    r["status"] = "FAILED"
    cl["nsf_strike_count"] += 1

    if outcome == "NSF":
        # spawn one retry if post-increment attempt_count < ceiling.
        if r["attempt_count"] < C.NSF_MAX_RETRIES:
            retry_dt = r["_scheduled_for_dt"] + timedelta(days=C.NSF_RETRY_GAP_DAYS)
            retry = {
                "credit_line_id": cl["id"],
                "scheduled_for": iso_millis(retry_dt),
                "amount_cents": 0,
                "principal_applied_cents": 0,
                "fee_applied_cents": 0,
                "attempt_count": r["attempt_count"],
                "status": "SCHEDULED",
                "failure_reason": None,
                "next_retry_remittance_id": None,
            }
            stamp_create(retry)
            retry["_scheduled_for_dt"] = retry_dt
            db.remittances[retry["id"]] = retry
            r["next_retry_remittance_id"] = retry["id"]
    # ACCOUNT_CLOSED: never spawns a retry; next_retry_remittance_id stays null.

    # escalation: ACTIVE -> DELINQUENT at threshold.
    if cl["nsf_strike_count"] >= C.NSF_DELINQUENCY_THRESHOLD and cl["status"] == "ACTIVE":
        cl["status"] = "DELINQUENT"
    touch(cl)
