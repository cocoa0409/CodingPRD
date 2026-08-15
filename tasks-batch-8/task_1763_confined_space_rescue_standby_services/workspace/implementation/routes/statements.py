"""Billing statements: generation sweep, finalize, dispute, void, pay (PRD 3.8)."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ERR_INVALID_REQUEST, ERR_INVALID_TIME_RANGE, ERR_PARTIAL_PAYMENT,
    ERR_PERMITS_STILL_OPEN, ERR_STATEMENT_INVALID_STATE,
    ERR_STATEMENT_NOT_FOUND, ERR_STATEMENT_PERIOD_OVERLAP, raise_error,
)
from helpers import (
    body, iso_z, list_response, now_dt, parse_dt, pub_num, reject_unknown,
    req_datetime, req_int, req_string, round_cents, dec, stamp_append_only,
    stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from routes.accounts import get_account
from services import (
    CANCELLATION_FEE_RATIO, adjust_balance, chargeable_hours,
)

bp = Blueprint("statements", __name__)


def get_statement(statement_id):
    stmt = db.billing_statements.get(statement_id)
    if stmt is None:
        raise_error(ERR_STATEMENT_NOT_FOUND, "Billing statement not found")
    return stmt


def _lines_of(statement_id):
    return sorted(
        (l for l in db.statement_lines.values() if l["statement_id"] == statement_id),
        key=lambda l: (l["created_at"], l["_seq"]))


def _recompute_totals(stmt):
    # Pinned rounding order: each line rounds first (amounts are integer cents
    # by construction), then the statement sums.
    lines = _lines_of(stmt["id"])
    stmt["total_cents"] = sum(l["amount_cents"] for l in lines)
    stmt["line_count"] = len(lines)
    touch(stmt)


def _append_line(stmt, kind, permit_id, assignment_id, quantity, unit_rate, amount, description):
    line = {
        "statement_id": stmt["id"],
        "line_kind": kind,
        "reference_permit_id": permit_id,
        "reference_assignment_id": assignment_id,
        "quantity": quantity,
        "unit_rate_cents": unit_rate,
        "amount_cents": amount,
        "description": description,
    }
    stamp_append_only(line)
    db.statement_lines[line["id"]] = line
    return line


def _sweep(stmt, account, period_start, period_end):
    """Append newly billable items per the account's billing_mode."""
    permits = sorted(
        (p for p in db.entry_permits.values() if p["client_account_id"] == account["id"]),
        key=lambda p: (p["created_at"], p["_seq"]))
    assignments = sorted(
        (a for a in db.standby_assignments.values()
         if a["permit_id"] in {p["id"] for p in permits}),
        key=lambda a: (a["created_at"], a["_seq"]))

    def in_period(iso):
        return iso is not None and period_start <= parse_dt(iso) < period_end

    if account["billing_mode"] == "EVENT":
        for p in permits:
            if in_period(p["actual_entry_at"]) and not p["event_base_billed"]:
                _append_line(stmt, "EVENT_BASE", p["id"], None, 1,
                             account["event_base_fee_cents"],
                             account["event_base_fee_cents"],
                             f"Event base fee for permit {p['id']}")
                p["event_base_billed"] = True
                touch(p)
    for a in assignments:
        if a["status"] != "RELEASED" or a["billed"] or not in_period(a["checked_out_at"]):
            continue
        if account["billing_mode"] == "HOURLY_STANDBY":
            qty = chargeable_hours(a, account)
            _append_line(stmt, "STANDBY_HOURLY", a["permit_id"], a["id"],
                         qty, account["hourly_standby_rate_cents"],
                         a["line_amount_cents"],
                         f"Hourly standby charge for assignment {a['id']}")
        else:  # EVENT
            _append_line(stmt, "EVENT_RESCUER", a["permit_id"], a["id"], 1,
                         account["event_per_rescuer_cents"],
                         account["event_per_rescuer_cents"],
                         f"Event rescuer fee for assignment {a['id']}")
        if a["deployed_at"] is not None:
            _append_line(stmt, "DEPLOYMENT_SURCHARGE", a["permit_id"], a["id"], 1,
                         account["deployment_surcharge_cents"],
                         account["deployment_surcharge_cents"],
                         f"Deployment surcharge for assignment {a['id']}")
        a["billed"] = True
        touch(a)
    # Cancellation fees apply in both billing modes.
    for p in permits:
        if (p["status"] == "CANCELLED" and p["actual_entry_at"] is not None
                and in_period(p["closed_at"]) and not p["cancellation_fee_billed"]):
            fee = round_cents(dec(account["event_base_fee_cents"]) * CANCELLATION_FEE_RATIO)
            _append_line(stmt, "CANCELLATION_FEE", p["id"], None, 1, fee, fee,
                         f"Cancellation fee for permit {p['id']}")
            p["cancellation_fee_billed"] = True
            touch(p)


@bp.route("/rescue-ops/client-accounts/<account_id>/statements/generate", methods=["POST"])
def generate_statement(account_id):
    require_auth(("BillingClerk",))
    account = get_account(account_id)
    data = body()
    reject_unknown(data, {"period_start", "period_end"})
    period_start = req_datetime(data, "period_start")
    period_end = req_datetime(data, "period_end")
    if not period_end > period_start:
        raise_error(ERR_INVALID_TIME_RANGE, "period_end must be strictly after period_start")
    # Identical-period OPEN statement: return and top up instead of duplicating.
    for existing in db.billing_statements.values():
        if existing["client_account_id"] != account["id"]:
            continue
        same_period = (parse_dt(existing["period_start"]) == period_start
                       and parse_dt(existing["period_end"]) == period_end)
        if existing["status"] == "OPEN" and same_period:
            _sweep(existing, account, period_start, period_end)
            _recompute_totals(existing)
            return success_object(serializers.billing_statement(existing), 201)
    # Overlap with a FINALIZED | DISPUTED | PAID statement is rejected.
    for existing in db.billing_statements.values():
        if existing["client_account_id"] != account["id"] \
                or existing["status"] not in ("FINALIZED", "DISPUTED", "PAID"):
            continue
        if (period_start < parse_dt(existing["period_end"])
                and parse_dt(existing["period_start"]) < period_end):
            raise_error(ERR_STATEMENT_PERIOD_OVERLAP,
                        "Period intersects an existing FINALIZED, DISPUTED, or PAID statement")
    stmt = {
        "client_account_id": account["id"],
        "period_start": iso_z(period_start),
        "period_end": iso_z(period_end),
        "status": "OPEN",
        "total_cents": 0,
        "line_count": 0,
        "finalized_at": None,
        "billed_balance_contribution_cents": 0,
    }
    stamp_new(stmt)
    db.billing_statements[stmt["id"]] = stmt
    _sweep(stmt, account, period_start, period_end)
    _recompute_totals(stmt)
    return success_object(serializers.billing_statement(stmt), 201)


@bp.route("/rescue-ops/statements", methods=["GET"])
def list_statements():
    require_auth(ALL_ROLES)
    return list_response(list(db.billing_statements.values()),
                         serializers.billing_statement, {
                             "client_account_id": request.args.get("client_account_id"),
                             "status": request.args.get("status"),
                         })


@bp.route("/rescue-ops/statements/<statement_id>", methods=["GET"])
def get_one_statement(statement_id):
    require_auth(ALL_ROLES)
    return success_object(serializers.billing_statement(get_statement(statement_id)))


@bp.route("/rescue-ops/statements/<statement_id>/finalize", methods=["POST"])
def finalize_statement(statement_id):
    require_auth(("BillingClerk",))
    stmt = get_statement(statement_id)
    body()
    if stmt["status"] not in ("OPEN", "DISPUTED"):
        raise_error(ERR_STATEMENT_INVALID_STATE,
                    "Only an OPEN or DISPUTED statement can be finalized")
    # Blocked while in-period permits are still ACTIVE | SUSPENDED.
    period_start = parse_dt(stmt["period_start"])
    period_end = parse_dt(stmt["period_end"])
    for p in db.entry_permits.values():
        if p["client_account_id"] != stmt["client_account_id"] \
                or p["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if p["actual_entry_at"] is not None \
                and period_start <= parse_dt(p["actual_entry_at"]) < period_end:
            raise_error(ERR_PERMITS_STILL_OPEN,
                        "In-period permits are still ACTIVE or SUSPENDED")
    _recompute_totals(stmt)
    account = get_account(stmt["client_account_id"])
    delta = stmt["total_cents"] - stmt["billed_balance_contribution_cents"]
    stmt["billed_balance_contribution_cents"] = stmt["total_cents"]
    stmt["finalized_at"] = iso_z(now_dt())
    stmt["status"] = "FINALIZED"
    touch(stmt)
    adjust_balance(account, delta)
    return success_object(serializers.billing_statement(stmt))


@bp.route("/rescue-ops/statements/<statement_id>/dispute", methods=["POST"])
def dispute_statement(statement_id):
    require_auth(("BillingClerk",))
    stmt = get_statement(statement_id)
    data = body()
    reject_unknown(data, {"reason"})
    req_string(data, "reason")
    if stmt["status"] != "FINALIZED":
        raise_error(ERR_STATEMENT_INVALID_STATE, "Only a FINALIZED statement can be disputed")
    stmt["status"] = "DISPUTED"
    touch(stmt)
    return success_object(serializers.billing_statement(stmt))


@bp.route("/rescue-ops/statements/<statement_id>/adjustments", methods=["POST"])
def add_adjustment(statement_id):
    require_auth(("BillingClerk",))
    stmt = get_statement(statement_id)
    data = body()
    reject_unknown(data, {"credit_amount_cents", "reason"})
    credit = req_int(data, "credit_amount_cents")
    if credit < 0:
        raise_error(ERR_INVALID_REQUEST, "credit_amount_cents must be non-negative")
    reason = req_string(data, "reason")
    if stmt["status"] != "DISPUTED":
        raise_error(ERR_STATEMENT_INVALID_STATE,
                    "Credit adjustments may be appended only to a DISPUTED statement")
    line = _append_line(stmt, "CREDIT_ADJUSTMENT", None, None, 1, -credit, -credit,
                        f"Credit adjustment: {reason}")
    _recompute_totals(stmt)
    return success_object(serializers.statement_line(line), 201)


@bp.route("/rescue-ops/statements/<statement_id>/void", methods=["POST"])
def void_statement(statement_id):
    require_auth(("BillingClerk",))
    stmt = get_statement(statement_id)
    body()
    if stmt["status"] not in ("FINALIZED", "DISPUTED"):
        raise_error(ERR_STATEMENT_INVALID_STATE,
                    "Only a FINALIZED or DISPUTED statement can be voided")
    account = get_account(stmt["client_account_id"])
    contribution = stmt["billed_balance_contribution_cents"]
    stmt["status"] = "VOID"
    stmt["billed_balance_contribution_cents"] = 0
    touch(stmt)
    adjust_balance(account, -contribution)
    return success_object(serializers.billing_statement(stmt))


@bp.route("/rescue-ops/statements/<statement_id>/pay", methods=["POST"])
def pay_statement(statement_id):
    require_auth(("BillingClerk",))
    stmt = get_statement(statement_id)
    data = body()
    reject_unknown(data, {"payment_cents"})
    payment = req_int(data, "payment_cents")
    if stmt["status"] != "FINALIZED":
        raise_error(ERR_STATEMENT_INVALID_STATE, "Only a FINALIZED statement can be paid")
    if payment != stmt["total_cents"]:
        raise_error(ERR_PARTIAL_PAYMENT, "payment_cents must equal total_cents exactly")
    account = get_account(stmt["client_account_id"])
    stmt["status"] = "PAID"
    stmt["billed_balance_contribution_cents"] = 0
    touch(stmt)
    adjust_balance(account, -payment)
    return success_object(serializers.billing_statement(stmt))


@bp.route("/rescue-ops/statements/<statement_id>/lines", methods=["GET"])
def list_lines(statement_id):
    require_auth(ALL_ROLES)
    stmt = get_statement(statement_id)
    return list_response(_lines_of(stmt["id"]), serializers.statement_line, {})
