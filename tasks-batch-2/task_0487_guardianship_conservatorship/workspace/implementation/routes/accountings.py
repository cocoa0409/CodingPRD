"""AccountingReport routes: create, submit, return, resubmit, approve."""

from flask import Blueprint, request

from db import db, stamp_create, stamp_update
from errors import err
from middleware import get_identity, require_role
from response import object_response, array_response
from validators import (
    ALL_ROLES,
    get_json_body,
    require_string,
    require_int,
    optional_int,
    parse_pagination,
    paginate,
)
from services import (
    resolve_path,
    resolve_ref,
    accounts_for_case,
    expenditures_for_case,
    budgets_for_case,
    disbursed_year,
    touch_account,
    touch_case,
    advance_due_iso,
)
from calculations import fiduciary_fee, VARIANCE_TOLERANCE_CENTS

bp = Blueprint("accountings", __name__)


def _appointed_fiduciary_kind(case_id):
    """Kind of the fiduciary on the case's appointment.

    Prefer the ACTIVE appointment; otherwise the most recently created appointment.
    """
    appts = [a for a in db.appointments.values() if a["case_id"] == case_id]
    if not appts:
        return None
    active = [a for a in appts if a["status"] == "ACTIVE"]
    chosen = None
    if active:
        chosen = max(active, key=lambda a: a.get("_seq", 0))
    else:
        chosen = max(appts, key=lambda a: a.get("_seq", 0))
    fid = db.fiduciaries.get(chosen["fiduciary_id"])
    return fid["fiduciary_kind"] if fid else None


def _recompute_derived(report):
    """Recompute ledger / projection / variance / fee (calc accounting_reconciliation,
    projected_disbursed_cents, fiduciary_fee).
    """
    case_id = report["case_id"]
    period_year = report["period_year"]

    # Chronological-actual: sum DISBURSED expenditures whose disbursed-year == period_year.
    ledger = sum(
        e["amount_cents"]
        for e in expenditures_for_case(case_id)
        if e["status"] == "DISBURSED" and disbursed_year(e) == period_year
    )
    report["ledger_disbursed_cents"] = ledger

    # Forward-looking projection: the single APPROVED budget for the period year.
    gov = None
    for b in budgets_for_case(case_id):
        if b["period_year"] == period_year and b["status"] == "APPROVED":
            gov = b
            break
    if gov is None:
        report["projected_disbursed_cents"] = 0
    else:
        report["projected_disbursed_cents"] = (
            gov["care_cap_cents"] + gov["medical_cap_cents"] + gov["admin_cap_cents"]
        )

    report["variance_cents"] = report["reported_disbursed_cents"] - ledger

    kind = _appointed_fiduciary_kind(case_id)
    report["fiduciary_fee_cents"] = fiduciary_fee(
        report["opening_balance_cents"], report["reported_income_cents"], kind
    )


@bp.route("/gc/accountings", methods=["POST"])
def create_accounting():
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    body = get_json_body()
    case_id = require_string(body, "case_id")
    period_year = require_int(body, "period_year")
    opening_balance = require_int(body, "opening_balance_cents", minimum=0)
    reported_income = require_int(body, "reported_income_cents", minimum=0)
    reported_disbursed = require_int(body, "reported_disbursed_cents", minimum=0)
    resolve_ref(db.cases, case_id)

    record = {
        "case_id": case_id,
        "period_year": period_year,
        "opening_balance_cents": opening_balance,
        "reported_income_cents": reported_income,
        "reported_disbursed_cents": reported_disbursed,
        "ledger_disbursed_cents": 0,
        "projected_disbursed_cents": 0,
        "variance_cents": 0,
        "fiduciary_fee_cents": 0,
        "status": "DRAFT",
    }
    stamp_create(record)
    with db.lock:
        db.accountings[record["id"]] = record
    return object_response(record, 201)


@bp.route("/gc/accountings/<aid>", methods=["GET"])
def get_accounting(aid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    return object_response(resolve_path(db.accountings, aid), 200)


@bp.route("/gc/accountings", methods=["GET"])
def list_accountings():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.accountings.values())
    case_id = request.args.get("case_id")
    period_year = request.args.get("period_year")
    if case_id is not None:
        items = [a for a in items if a["case_id"] == case_id]
    if period_year is not None:
        try:
            py = int(period_year)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "period_year must be an integer")
        items = [a for a in items if a["period_year"] == py]
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/gc/accountings/<aid>/submit", methods=["POST"])
def submit_accounting(aid):
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    report = resolve_path(db.accountings, aid)
    if report["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Accounting must be DRAFT")
    case = db.cases.get(report["case_id"])
    if case is None or case["status"] not in ("ACTIVE", "UNDER_REVIEW"):
        raise err("ERR_CASE_NOT_ACTIVE", "Case must be ACTIVE or UNDER_REVIEW")
    report["status"] = "SUBMITTED"
    _recompute_derived(report)
    stamp_update(report)
    return object_response(report, 200)


@bp.route("/gc/accountings/<aid>/return", methods=["POST"])
def return_accounting(aid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    report = resolve_path(db.accountings, aid)
    if report["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Accounting must be SUBMITTED")
    report["status"] = "RETURNED_FOR_CORRECTION"
    stamp_update(report)
    return object_response(report, 200)


@bp.route("/gc/accountings/<aid>/resubmit", methods=["POST"])
def resubmit_accounting(aid):
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    body = get_json_body()
    report = resolve_path(db.accountings, aid)
    if report["status"] != "RETURNED_FOR_CORRECTION":
        raise err("ERR_INVALID_STATE", "Accounting must be RETURNED_FOR_CORRECTION")
    # Apply corrected fields if supplied.
    for field in ("reported_disbursed_cents", "reported_income_cents", "opening_balance_cents"):
        value = optional_int(body, field, minimum=0)
        if value is not None:
            report[field] = value
    report["status"] = "SUBMITTED"
    _recompute_derived(report)
    stamp_update(report)
    return object_response(report, 200)


@bp.route("/gc/accountings/<aid>/approve", methods=["POST"])
def approve_accounting(aid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    report = resolve_path(db.accountings, aid)
    if report["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Accounting must be SUBMITTED")
    if abs(report["variance_cents"]) > VARIANCE_TOLERANCE_CENTS:
        raise err("ERR_ACCOUNTING_VARIANCE", "Variance exceeds the approval tolerance")

    report["status"] = "APPROVED"
    stamp_update(report)
    case = db.cases.get(report["case_id"])
    if case is not None:
        # Advance next_accounting_due_iso by one accounting period.
        if case.get("next_accounting_due_iso"):
            case["next_accounting_due_iso"] = advance_due_iso(case["next_accounting_due_iso"])
        # Credit reported income into the restricted account principal (once).
        accounts = accounts_for_case(case["id"])
        if accounts:
            account = accounts[0]
            account["principal_balance_cents"] += report["reported_income_cents"]
            touch_account(account)
        # Recompute overdue count + posture and bump version.
        touch_case(case)
    return object_response(report, 200)
