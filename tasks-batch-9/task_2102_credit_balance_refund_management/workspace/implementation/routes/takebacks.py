"""Take-back notices, the offset waterfall and disputes (PRD 3.10)."""
from flask import Blueprint, g, request

import auth
import calc
import cascade
import clock
import db
import derive
import response
import validation as v
from errors import ApiError

bp = Blueprint("takebacks", __name__)


@bp.post("/take-back-notices")
@auth.require(auth.PAYER_LIAISON)
def create_notice():
    data = v.body()
    v.fk_exists("payer", data, "payer_id")                       # rank 4
    # rank 5 - payer scoping for a PayerLiaison
    if isinstance(data.get("payer_id"), str) and data["payer_id"] != g.user_id:
        raise ApiError("ERR_PAYER_SCOPE_VIOLATION")
    # rank 6 - body shape
    payer_id = v.req_str(data, "payer_id")
    notice_number = v.req_str(data, "notice_number")
    total_recoup_cents = v.req_int(data, "total_recoup_cents", minimum=0)
    admin_fee_cents = v.opt_int(data, "admin_fee_cents", 0, minimum=0)
    # rank 32 - notice_number unique within payer
    for other in db.take_back_notices.values():
        if other["payer_id"] == payer_id and other["notice_number"] == notice_number:
            raise ApiError("ERR_DUPLICATE_NOTICE_NUMBER")
    # rank 36 - the payer may file take-backs at all
    payer = db.payers[payer_id]
    if not payer["take_back_allowed"]:
        raise ApiError("ERR_TAKE_BACK_NOT_PERMITTED")

    now = clock.now()
    row = db.base_row()
    row.update({
        "payer_id": payer_id,
        "notice_number": notice_number,
        "total_recoup_cents": total_recoup_cents,
        "admin_fee_cents": admin_fee_cents,
        "received_at": now,
        "dispute_deadline_at": clock.add_days(now, calc.DISPUTE_WINDOW_DAYS),
        "state": "RECEIVED",
    })
    db.take_back_notices[row["id"]] = row
    return response.ok(derive.take_back_notice(row), 201)


@bp.get("/take-back-notices")
@auth.require(*auth.ALL_ROLES)
def list_notices():
    rows = db.ordered(list(db.take_back_notices.values()))
    payer_id = request.args.get("payer_id")
    if payer_id:
        rows = [r for r in rows if r["payer_id"] == payer_id]
    state = request.args.get("state")
    if state:
        rows = [r for r in rows if r["state"] == state]
    return response.page(rows, derive.take_back_notice)


@bp.get("/take-back-notices/<notice_id>")
@auth.require(*auth.ALL_ROLES)
def read_notice(notice_id):
    return response.ok(derive.take_back_notice(v.must_exist("notice", notice_id)))


@bp.post("/take-back-notices/<notice_id>/offset-applications")
@auth.require(auth.CREDIT_ANALYST)
def apply_offsets(notice_id):
    notice = v.must_exist("notice", notice_id)                       # rank 3
    data = v.body()
    # rank 4 - every target account must resolve
    raw_targets = data.get("target_account_ids")
    if isinstance(raw_targets, list):
        for member in raw_targets:
            if isinstance(member, str) and member not in db.patient_accounts:
                raise ApiError("ERR_ACCOUNT_NOT_FOUND")
    # rank 6 - body shape
    target_account_ids = v.req_str_array(data, "target_account_ids")
    expected = v.req_int(data, "expected_take_back_notice_version")
    if notice["state"] not in ("RECEIVED", "PARTIALLY_APPLIED"):     # rank 12
        raise ApiError("ERR_NOTICE_INVALID_STATE")
    if expected != notice["version"]:                                # rank 17
        raise ApiError("ERR_STALE_VERSION")

    lines = calc.offset_waterfall(notice, set(target_account_ids))   # rank 44
    highest = 0
    for existing in db.offsets_for_notice(notice["id"]):
        highest = max(highest, int(existing["sequence"]))

    created = []
    touched = []
    now = clock.now()
    for index, line in enumerate(lines):
        cb = line["credit_balance"]
        # hop 1 - the ledger posting
        txn = cascade.post_transaction(
            account_id=cb["account_id"],
            txn_type="TAKE_BACK_OFFSET",
            amount_cents=line["applied_cents"],
            source="PAYER",
            payer_id=notice["payer_id"],
            remark="Take-back offset for notice %s" % notice["notice_number"],
        )
        row = db.base_row()
        row.update({
            "take_back_notice_id": notice["id"],
            "account_id": cb["account_id"],
            "credit_balance_id": cb["id"],
            "posted_transaction_id": txn["id"],
            "applied_cents": line["applied_cents"],
            "admin_fee_share_cents": line["admin_fee_share_cents"],
            "sequence": highest + 1 + index,
            "applied_at": now,
            "reversed_at": None,
            "state": "APPLIED",
        })
        db.offset_applications[row["id"]] = row
        created.append(row)
        touched.append(cb)

    # hops 2 / 3 / 4 - credit balance recompute, status and obligation
    for cb in touched:
        if cb["status"] == "ATTRIBUTED" and derive.cb_outstanding_cents(cb) == 0:
            cb["status"] = "RESOLVED_BY_OFFSET"
            db.touch(cb)
            cascade.settle_obligations_by_offset(cb)

    remaining = derive.notice_remaining_cents(notice)
    notice["state"] = "FULLY_APPLIED" if remaining == 0 else "PARTIALLY_APPLIED"
    db.touch(notice)

    return response.ok_array([derive.offset_application(r) for r in created], 201)


@bp.post("/take-back-notices/<notice_id>/dispute")
@auth.require(auth.PAYER_LIAISON)
def dispute_notice(notice_id):
    notice = v.must_exist("notice", notice_id)                    # rank 3
    if notice["payer_id"] != g.user_id:                           # rank 5
        raise ApiError("ERR_PAYER_SCOPE_VIOLATION")
    data = v.body()
    v.req_str(data, "dispute_reason")                             # rank 6
    if notice["state"] not in ("RECEIVED", "PARTIALLY_APPLIED"):  # rank 12
        raise ApiError("ERR_NOTICE_INVALID_STATE")
    if clock.now() > notice["dispute_deadline_at"]:               # rank 24
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED")

    notice["state"] = "DISPUTED"
    db.touch(notice)
    return response.ok(derive.take_back_notice(notice))


@bp.post("/take-back-notices/<notice_id>/withdraw-dispute")
@auth.require(auth.PAYER_LIAISON)
def withdraw_dispute(notice_id):
    notice = v.must_exist("notice", notice_id)   # rank 3
    if notice["payer_id"] != g.user_id:          # rank 5
        raise ApiError("ERR_PAYER_SCOPE_VIOLATION")
    if notice["state"] != "DISPUTED":            # rank 12
        raise ApiError("ERR_NOTICE_INVALID_STATE")

    applied = derive.notice_applied_cents(notice)
    notice["state"] = "PARTIALLY_APPLIED" if applied > 0 else "RECEIVED"
    db.touch(notice)
    return response.ok(derive.take_back_notice(notice))


@bp.get("/offset-applications")
@auth.require(*auth.ALL_ROLES)
def list_offsets():
    rows = db.ordered(list(db.offset_applications.values()))
    for name in ("take_back_notice_id", "account_id", "credit_balance_id",
                 "posted_transaction_id", "state"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    return response.page(rows, derive.offset_application)


@bp.get("/offset-applications/<offset_id>")
@auth.require(*auth.ALL_ROLES)
def read_offset(offset_id):
    return response.ok(derive.offset_application(v.must_exist("offset", offset_id)))


@bp.post("/offset-applications/<offset_id>/reverse")
@auth.require(auth.CREDIT_ANALYST)
def reverse_offset(offset_id):
    offset = v.must_exist("offset", offset_id)   # rank 3
    data = v.body()
    reason = v.opt_str(data, "reason")           # rank 6
    if offset["state"] != "APPLIED":
        raise ApiError("ERR_NOTICE_INVALID_STATE",
                       "The offset application is not in state APPLIED.")
    cascade.reverse_offset(offset, remark=reason)
    return response.ok(derive.offset_application(offset))
