"""BadDebtWriteOff endpoints: create (PENDING_APPROVAL), get, list,
list-by-account, approve (OCC + segregation of duties), reverse; plus the
MedicareBadDebtLogEntry read surface (PRD 3.9)."""

from datetime import date

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INSUFFICIENT_STATEMENTS,
    ERR_INVALID_COST_REPORT_YEAR,
    ERR_INVALID_REQUEST,
    ERR_OPEN_DISPUTE_BLOCKS_WRITE_OFF,
    ERR_PARTIAL_WRITE_OFF,
    ERR_PLAN_BLOCKS_WRITE_OFF,
    ERR_REVERSAL_WINDOW_PASSED,
    ERR_SCREENING_NOT_CURRENT,
    ERR_SOD,
    ERR_STALE_VERSION,
    ERR_WRITE_OFF_BEFORE_120,
    invalid_state,
    not_found,
)
from middleware import ROLE_COLLECTOR, ROLE_OFFICER, authenticate
from response import ok_list, ok_object
from services import (
    ELIGIBLE_OUTCOMES,
    REQUIRED_STATEMENTS_BEFORE_WRITEOFF,
    WRITE_OFF_REVERSAL_WINDOW_DAYS,
    active_agency_placement,
    active_payment_plan,
    build_medicare_log_entry,
    open_dispute,
    serialize_log_entry,
    serialize_write_off,
    statements_sent_count,
)
from util import (
    append_only_record,
    base_record,
    get_body,
    now_iso,
    paginate,
    parse_dt,
    req_enum,
    req_int,
    req_str,
    today,
    touch,
)

bp = Blueprint("write_offs", __name__)

_RW_ROLES = [ROLE_COLLECTOR, ROLE_OFFICER]


def get_write_off_or_404(write_off_id):
    wo = db.write_offs.get(write_off_id)
    if wo is None:
        raise not_found("write-off not found")
    return wo


def get_log_entry_or_404(entry_id):
    e = db.medicare_log_entries.get(entry_id)
    if e is None:
        raise not_found("medicare bad-debt log entry not found")
    return e


@bp.post("/self-pay/bad-debt-write-offs")
def create_write_off():
    user_id, _ = authenticate(_RW_ROLES)
    b = get_body()
    account_id = req_str(b, "account_id")
    from routes_accounts import get_account_or_404
    account = get_account_or_404(account_id)

    # payload shape (priority 4): if the client carries amount_cents at all it
    # must at least be an integer
    if "amount_cents" in b and b["amount_cents"] is not None:
        req_int(b, "amount_cents")

    write_off_kind = req_enum(b, "write_off_kind", ("BAD_DEBT", "CHARITY_CARE"))
    screening_id = None
    medicare_cost_report_year = None
    if write_off_kind == "CHARITY_CARE":
        if b.get("screening_id") is None:
            raise ApiError(ERR_INVALID_REQUEST,
                           "screening_id is required for CHARITY_CARE", 400)
        screening_id = req_str(b, "screening_id")
        if screening_id not in db.screenings:
            raise not_found("screening not found")
    else:
        medicare_cost_report_year = req_int(b, "medicare_cost_report_year")

    # full-balance write-offs only (priority 15): the written-off amount is
    # always a snapshot of the entire current balance at approval time, so an
    # explicit amount that differs from that full balance is a partial amount
    # and is rejected (PRD 3.9)
    if ("amount_cents" in b and b["amount_cents"] is not None
            and b["amount_cents"] != account["current_balance_cents"]):
        raise ApiError(
            ERR_PARTIAL_WRITE_OFF,
            "only full-balance write-offs exist; an explicit partial amount "
            "is not supported",
            422,
        )

    # cost report year window (priority 16)
    if write_off_kind == "BAD_DEBT":
        gl_year = date.fromisoformat(account["guarantor_liability_date"]).year
        if (medicare_cost_report_year < gl_year
                or medicare_cost_report_year > today().year):
            raise ApiError(
                ERR_INVALID_COST_REPORT_YEAR,
                "medicare_cost_report_year must be no earlier than the "
                "guarantor_liability_date calendar year and no later than "
                "the logical clock's calendar year",
                422,
            )

    rec = base_record()
    rec.update({
        "account_id": account_id,
        "write_off_kind": write_off_kind,
        "amount_cents": None,  # snapshot taken at approval (posting) time
        "screening_id": screening_id,
        "medicare_cost_report_year": medicare_cost_report_year,
        "posted_at": None,
        "approved_by_user_id": None,
        "status": "PENDING_APPROVAL",
        "_created_by_user_id": user_id,
        "_pre_writeoff_credit_status": None,
    })
    db.write_offs[rec["id"]] = rec
    return ok_object(serialize_write_off(rec), 201)


@bp.get("/self-pay/bad-debt-write-offs/<write_off_id>")
def get_write_off(write_off_id):
    authenticate(_RW_ROLES)
    return ok_object(serialize_write_off(get_write_off_or_404(write_off_id)))


def _write_off_filters(items):
    account_f = request.args.get("account_id")
    kind_f = request.args.get("write_off_kind")
    status_f = request.args.get("status")
    screening_f = request.args.get("screening_id")
    if account_f is not None:
        items = [w for w in items if w["account_id"] == account_f]
    if kind_f is not None:
        items = [w for w in items if w["write_off_kind"] == kind_f]
    if status_f is not None:
        items = [w for w in items if w["status"] == status_f]
    if screening_f is not None:
        items = [w for w in items if w.get("screening_id") == screening_f]
    return items


@bp.get("/self-pay/bad-debt-write-offs")
def list_write_offs():
    authenticate(_RW_ROLES)
    items = _write_off_filters(list(db.write_offs.values()))
    page, meta = paginate(items)
    return ok_list([serialize_write_off(w) for w in page], meta)


@bp.get("/self-pay/accounts/<account_id>/bad-debt-write-offs")
def list_write_offs_for_account(account_id):
    authenticate(_RW_ROLES)
    from routes_accounts import get_account_or_404
    get_account_or_404(account_id)
    items = [w for w in db.write_offs.values() if w["account_id"] == account_id]
    page, meta = paginate(items)
    return ok_list([serialize_write_off(w) for w in page], meta)


@bp.post("/self-pay/bad-debt-write-offs/<write_off_id>/approve")
def approve_write_off(write_off_id):
    user_id, _ = authenticate([ROLE_OFFICER])
    wo = get_write_off_or_404(write_off_id)
    b = get_body()
    expected_account_version = req_int(b, "expected_account_version")
    account = db.accounts.get(wo["account_id"])
    if account is None:
        raise not_found("account not found")

    # OCC (priority 5)
    if expected_account_version != account["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_account_version does not match the account's current "
            "version",
            412,
        )
    # state preconditions (priority 6)
    if wo["status"] != "PENDING_APPROVAL":
        raise invalid_state("only a PENDING_APPROVAL write-off can be approved")
    if wo["write_off_kind"] == "CHARITY_CARE":
        if account["status"] != "OPEN":
            raise invalid_state(
                "a CHARITY_CARE write-off requires account status OPEN")
    else:
        if account["status"] not in ("OPEN", "IN_COLLECTIONS"):
            raise invalid_state(
                "a BAD_DEBT write-off requires account status OPEN or "
                "IN_COLLECTIONS")
    # segregation of duties (priority 7): approver != creator
    if user_id == wo["_created_by_user_id"]:
        raise ApiError(
            ERR_SOD,
            "the approving officer must differ from the write-off creator",
            403,
        )
    # screening currency (priority 8)
    if wo["write_off_kind"] == "CHARITY_CARE":
        scr = db.screenings.get(wo.get("screening_id"))
        if (scr is None
                or scr["account_id"] != account["id"]
                or scr["status"] != "EVALUATED"
                or scr["eligibility_outcome"] not in ELIGIBLE_OUTCOMES):
            raise ApiError(
                ERR_SCREENING_NOT_CURRENT,
                "the referenced screening is not currently EVALUATED with a "
                "charity-eligible outcome",
                409,
            )
    # open-dispute guard (priority 9)
    if open_dispute(account["id"]) is not None:
        raise ApiError(
            ERR_OPEN_DISPUTE_BLOCKS_WRITE_OFF,
            "an OPEN patient dispute blocks write-off approval",
            409,
        )
    if wo["write_off_kind"] == "BAD_DEBT":
        # active payment plan guard (direct-from-OPEN path)
        if account["status"] == "OPEN" \
                and active_payment_plan(account["id"]) is not None:
            raise ApiError(
                ERR_PLAN_BLOCKS_WRITE_OFF,
                "an ACTIVE payment plan blocks bad-debt write-off approval",
                409,
            )
        # aging + statement-cycle prerequisites (priority 11)
        if account["aging_bucket"] != "BUCKET_120_PLUS":
            raise ApiError(
                ERR_WRITE_OFF_BEFORE_120,
                "bad-debt write-off approval requires aging bucket "
                "BUCKET_120_PLUS",
                409,
            )
        if statements_sent_count(account["id"]) < REQUIRED_STATEMENTS_BEFORE_WRITEOFF:
            raise ApiError(
                ERR_INSUFFICIENT_STATEMENTS,
                "statements_sent_count has not reached the write-off minimum",
                409,
            )

    # posting is atomic and fans out widely (PRD 3.9)
    amount = account["current_balance_cents"]
    wo["amount_cents"] = amount
    wo["status"] = "POSTED"
    wo["posted_at"] = now_iso()
    wo["approved_by_user_id"] = user_id
    wo["_pre_writeoff_credit_status"] = account["credit_reporting_status"]
    touch(wo)

    account["current_balance_cents"] = 0
    if wo["write_off_kind"] == "CHARITY_CARE":
        account["charity_writeoff_total_cents"] += amount
        account["status"] = "CLOSED_CHARITY"
        account["status_reason"] = "charity care write-off posted"
        account["credit_reporting_status"] = "SUPPRESSED_BY_CHARITY"
        scr = db.screenings.get(wo.get("screening_id"))
        if scr is not None:
            scr["status"] = "APPLIED"
            touch(scr)
        # charity care is never claimable as Medicare bad debt: no log entry
    else:
        account["bad_debt_writeoff_total_cents"] += amount
        account["status"] = "WRITTEN_OFF"
        # an active agency placement is NOT auto-closed by a write-off
        build_medicare_log_entry(wo, account, append_only_record)
    touch(account)
    return ok_object(serialize_write_off(wo))


@bp.post("/self-pay/bad-debt-write-offs/<write_off_id>/reverse")
def reverse_write_off(write_off_id):
    user_id, _ = authenticate([ROLE_OFFICER])
    wo = get_write_off_or_404(write_off_id)
    if wo["status"] != "POSTED":
        raise invalid_state("only a POSTED write-off can be reversed")
    # segregation of duties on reversal: reverser != approver
    if user_id == wo["approved_by_user_id"]:
        raise ApiError(
            ERR_SOD,
            "the reversing officer must differ from the approving officer",
            403,
        )
    posted_date = parse_dt(wo["posted_at"]).date()
    if (today() - posted_date).days > WRITE_OFF_REVERSAL_WINDOW_DAYS:
        raise ApiError(
            ERR_REVERSAL_WINDOW_PASSED,
            "the write-off reversal window has passed",
            409,
        )

    account = db.accounts.get(wo["account_id"])
    if account is None:
        raise not_found("account not found")
    amount = wo["amount_cents"]
    wo["status"] = "REVERSED"
    touch(wo)

    account["current_balance_cents"] += amount
    if account["status"] == "WRITTEN_OFF":
        account["status"] = (
            "IN_COLLECTIONS"
            if active_agency_placement(account["id"]) is not None
            else "OPEN"
        )
        account["status_reason"] = None
    elif account["status"] == "CLOSED_CHARITY":
        account["status"] = "OPEN"
        account["status_reason"] = None
    if wo["write_off_kind"] == "CHARITY_CARE":
        account["charity_writeoff_total_cents"] -= amount
        scr = db.screenings.get(wo.get("screening_id"))
        if scr is not None and scr["status"] == "APPLIED":
            scr["status"] = "EVALUATED"
            touch(scr)
        account["credit_reporting_status"] = (
            wo["_pre_writeoff_credit_status"] or "NOT_REPORTED"
        )
    else:
        account["bad_debt_writeoff_total_cents"] -= amount
        # the linked log entry is voided in place, never deleted
        for e in db.medicare_log_entries.values():
            if e["write_off_id"] == wo["id"] and e["voided_at"] is None:
                e["voided_at"] = now_iso()
    touch(account)
    return ok_object(serialize_write_off(wo))


# ---------------------------------------------------------------------------
# MedicareBadDebtLogEntry read surface (RevenueIntegrityOfficer only)
# ---------------------------------------------------------------------------

def _log_filters(items):
    year_f = request.args.get("cost_report_year")
    wo_f = request.args.get("write_off_id")
    acct_f = request.args.get("account_id")
    if year_f is not None:
        try:
            year_v = int(year_f)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST,
                           "cost_report_year must be an integer", 400)
        items = [e for e in items if e["cost_report_year"] == year_v]
    if wo_f is not None:
        items = [e for e in items if e["write_off_id"] == wo_f]
    if acct_f is not None:
        items = [e for e in items if e["account_id"] == acct_f]
    return items


@bp.get("/self-pay/medicare-bad-debt-log-entries/<entry_id>")
def get_log_entry(entry_id):
    authenticate([ROLE_OFFICER])
    return ok_object(serialize_log_entry(get_log_entry_or_404(entry_id)))


@bp.get("/self-pay/medicare-bad-debt-log-entries")
def list_log_entries():
    authenticate([ROLE_OFFICER])
    items = _log_filters(list(db.medicare_log_entries.values()))
    page, meta = paginate(items)
    return ok_list([serialize_log_entry(e) for e in page], meta)


@bp.get("/self-pay/accounts/<account_id>/medicare-bad-debt-log-entries")
def list_log_entries_for_account(account_id):
    authenticate([ROLE_OFFICER])
    from routes_accounts import get_account_or_404
    get_account_or_404(account_id)
    items = _log_filters([e for e in db.medicare_log_entries.values()
                          if e["account_id"] == account_id])
    page, meta = paginate(items)
    return ok_list([serialize_log_entry(e) for e in page], meta)


@bp.get("/self-pay/bad-debt-write-offs/<write_off_id>/medicare-bad-debt-log-entries")
def list_log_entries_for_write_off(write_off_id):
    authenticate([ROLE_OFFICER])
    get_write_off_or_404(write_off_id)
    items = [e for e in db.medicare_log_entries.values()
             if e["write_off_id"] == write_off_id]
    page, meta = paginate(items)
    return ok_list([serialize_log_entry(e) for e in page], meta)
