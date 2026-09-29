"""Check runs and check disbursements (PRD 3.8, 3.9)."""
from flask import Blueprint, request

import auth
import calc
import cascade
import clock
import db
import derive
import response
import validation as v
from errors import ApiError

bp = Blueprint("batches", __name__)

ALIVE_BATCH_STATES = ("OPEN", "LOCKED", "ISSUED")


def _starting_check_number(data):
    if "starting_check_number" not in data or data["starting_check_number"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'starting_check_number' is required.")
    value = data["starting_check_number"]
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'starting_check_number' must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ApiError("ERR_INVALID_REQUEST", "Field 'starting_check_number' must be an integer.")


@bp.post("/refund-batches")
@auth.require(auth.DISBURSEMENT_OFFICER)
def create_batch():
    data = v.body()
    # rank 6 - body shape
    batch_number = v.req_str(data, "batch_number")
    bank_account_code = v.req_enum(data, "bank_account_code", v.BANK_ACCOUNT_CODES)
    cutoff_at = v.req_dt(data, "cutoff_at")
    scheduled_run_at = v.req_dt(data, "scheduled_run_at")
    # rank 26 - window ordering
    if not cutoff_at < scheduled_run_at:
        raise ApiError("ERR_INVALID_BATCH_WINDOW")
    # rank 27 - half-open non-overlap on the same channel; touching is allowed
    for other in db.refund_batches.values():
        if other["bank_account_code"] != bank_account_code:
            continue
        if other["state"] not in ALIVE_BATCH_STATES:
            continue
        if cutoff_at < other["scheduled_run_at"] and other["cutoff_at"] < scheduled_run_at:
            raise ApiError("ERR_BATCH_WINDOW_OVERLAP")
    # rank 31 - batch_number uniqueness
    for other in db.refund_batches.values():
        if other["batch_number"] == batch_number:
            raise ApiError("ERR_DUPLICATE_BATCH_NUMBER")

    row = db.base_row()
    row.update({
        "batch_number": batch_number,
        "bank_account_code": bank_account_code,
        "cutoff_at": cutoff_at,
        "scheduled_run_at": scheduled_run_at,
        "state": "OPEN",
    })
    db.refund_batches[row["id"]] = row
    return response.ok(derive.refund_batch(row), 201)


@bp.get("/refund-batches")
@auth.require(*auth.ALL_ROLES)
def list_batches():
    rows = db.ordered(list(db.refund_batches.values()))
    state = request.args.get("state")
    if state:
        rows = [r for r in rows if r["state"] == state]
    bank_account_code = request.args.get("bank_account_code")
    if bank_account_code:
        rows = [r for r in rows if r["bank_account_code"] == bank_account_code]
    return response.page(rows, derive.refund_batch)


@bp.get("/refund-batches/<batch_id>")
@auth.require(*auth.ALL_ROLES)
def read_batch(batch_id):
    return response.ok(derive.refund_batch(v.must_exist("refund_batch", batch_id)))


@bp.post("/refund-batches/<batch_id>/items")
@auth.require(auth.DISBURSEMENT_OFFICER)
def add_batch_item(batch_id):
    batch = v.must_exist("refund_batch", batch_id)                     # rank 3
    data = v.body()
    v.fk_exists("refund_request", data, "refund_request_id")           # rank 4
    refund_request_id = v.req_str(data, "refund_request_id")           # rank 6
    req = db.refund_requests[refund_request_id]
    if req["approval_state"] != "APPROVED" or \
            req["disbursement_state"] not in ("NOT_SCHEDULED", "REISSUE_PENDING"):  # rank 9
        raise ApiError("ERR_REFUND_REQUEST_INVALID_STATE")
    if batch["state"] != "OPEN":                                       # rank 10
        raise ApiError("ERR_BATCH_INVALID_STATE")

    gross = derive.rr_approved_amount_cents(req)
    fee, net = calc.net_disbursement(gross)                            # rank 42

    chk = _mint_check(req, batch, gross, fee, net, reissue_of=None)
    req["disbursement_state"] = "BATCHED"
    db.touch(req)
    db.touch(batch)
    return response.ok(derive.check_disbursement(chk), 201)


def _mint_check(req, batch, gross, fee, net, reissue_of):
    chk = db.base_row()
    chk.update({
        "refund_request_id": req["id"],
        "refund_batch_id": batch["id"],
        "reissue_of_disbursement_id": reissue_of,
        "check_number": None,
        "gross_amount_cents": gross,
        "processing_fee_cents": fee,
        "net_check_amount_cents": net,
        "payee_state_code": req["payee_state_code"],
        "issued_at": None,
        "cleared_at": None,
        "stale_at": None,
        "void_reason": None,
        "state": "PENDING",
    })
    db.check_disbursements[chk["id"]] = chk
    return chk


@bp.post("/refund-batches/<batch_id>/lock")
@auth.require(auth.DISBURSEMENT_OFFICER)
def lock_batch(batch_id):
    batch = v.must_exist("refund_batch", batch_id)                        # rank 3
    data = v.body()
    expected = v.req_int(data, "expected_refund_batch_version")           # rank 6
    if batch["state"] != "OPEN":                                          # rank 10
        raise ApiError("ERR_BATCH_INVALID_STATE")
    if expected != batch["version"]:                                      # rank 17
        raise ApiError("ERR_STALE_VERSION")
    if derive.batch_totals(batch["id"])["item_count"] < 1:                # rank 43
        raise ApiError("ERR_BATCH_EMPTY")

    batch["state"] = "LOCKED"
    db.touch(batch)
    return response.ok(derive.refund_batch(batch))


@bp.post("/refund-batches/<batch_id>/unlock")
@auth.require(auth.DISBURSEMENT_OFFICER)
def unlock_batch(batch_id):
    batch = v.must_exist("refund_batch", batch_id)   # rank 3
    if batch["state"] != "LOCKED":                   # rank 10
        raise ApiError("ERR_BATCH_INVALID_STATE")
    batch["state"] = "OPEN"
    db.touch(batch)
    return response.ok(derive.refund_batch(batch))


@bp.post("/refund-batches/<batch_id>/issue")
@auth.require(auth.DISBURSEMENT_OFFICER)
def issue_batch(batch_id):
    batch = v.must_exist("refund_batch", batch_id)          # rank 3
    data = v.body()
    starting = _starting_check_number(data)                 # rank 6
    if batch["state"] != "LOCKED":                          # rank 10
        raise ApiError("ERR_BATCH_INVALID_STATE")
    if derive.batch_totals(batch["id"])["item_count"] < 1:  # rank 43
        raise ApiError("ERR_BATCH_EMPTY")

    cascade.issue_batch(batch, starting)
    return response.ok(derive.refund_batch(batch))


@bp.get("/check-disbursements")
@auth.require(*auth.ALL_ROLES)
def list_checks():
    rows = db.ordered(list(db.check_disbursements.values()))
    refund_request_id = request.args.get("refund_request_id")
    if refund_request_id:
        rows = [r for r in rows if r["refund_request_id"] == refund_request_id]
    refund_batch_id = request.args.get("refund_batch_id")
    if refund_batch_id:
        rows = [r for r in rows if r["refund_batch_id"] == refund_batch_id]
    reissue_of = request.args.get("reissue_of_disbursement_id")
    if reissue_of:
        rows = [r for r in rows if r["reissue_of_disbursement_id"] == reissue_of]
    state = request.args.get("state")
    if state:
        rows = [r for r in rows if r["state"] == state]
    return response.page(rows, derive.check_disbursement)


@bp.get("/check-disbursements/<check_id>")
@auth.require(*auth.ALL_ROLES)
def read_check(check_id):
    return response.ok(derive.check_disbursement(v.must_exist("check", check_id)))


@bp.post("/check-disbursements/<check_id>/clear")
@auth.require(auth.DISBURSEMENT_OFFICER)
def clear_check(check_id):
    chk = v.must_exist("check", check_id)    # rank 3
    if chk["state"] != "ISSUED":             # rank 11
        raise ApiError("ERR_CHECK_INVALID_STATE")
    chk["state"] = "CLEARED"
    chk["cleared_at"] = clock.now()
    db.touch(chk)
    req = db.refund_requests.get(chk["refund_request_id"])
    if req is not None and req["disbursement_state"] == "ISSUED":
        req["disbursement_state"] = "CLEARED"
        db.touch(req)
    return response.ok(derive.check_disbursement(chk))


@bp.post("/check-disbursements/<check_id>/void")
@auth.require(auth.DISBURSEMENT_OFFICER)
def void_check(check_id):
    chk = v.must_exist("check", check_id)                          # rank 3
    data = v.body()
    void_reason = v.req_enum(data, "void_reason", v.VOID_REASONS)  # rank 6
    if chk["state"] not in ("ISSUED", "STALE"):                    # rank 11
        raise ApiError("ERR_CHECK_INVALID_STATE")
    cascade.void_check(chk, void_reason)
    return response.ok(derive.check_disbursement(chk))


@bp.post("/check-disbursements/<check_id>/reissue")
@auth.require(auth.DISBURSEMENT_OFFICER)
def reissue_check(check_id):
    chk = v.must_exist("check", check_id)                       # rank 3
    data = v.body()
    v.fk_exists("refund_batch", data, "refund_batch_id")        # rank 4
    refund_batch_id = v.req_str(data, "refund_batch_id")        # rank 6
    batch = db.refund_batches[refund_batch_id]
    if batch["state"] != "OPEN":                                # rank 10
        raise ApiError("ERR_BATCH_INVALID_STATE")
    req = db.refund_requests.get(chk["refund_request_id"])
    eligible = chk["state"] == "STALE" or (
        chk["state"] == "VOIDED" and req is not None
        and req["disbursement_state"] == "REISSUE_PENDING")
    if not eligible:                                            # rank 11
        raise ApiError("ERR_CHECK_INVALID_STATE")

    gross = derive.rr_approved_amount_cents(req)
    fee, net = calc.net_disbursement(gross)                     # rank 42

    successor = _mint_check(req, batch, gross, fee, net, reissue_of=chk["id"])
    if chk["state"] == "STALE":
        chk["state"] = "REISSUED"
        db.touch(chk)
    req["disbursement_state"] = "BATCHED"
    db.touch(req)
    db.touch(batch)

    rec = db.escheatment_for_check(chk["id"])
    if rec is not None and rec["state"] == "DUE_DILIGENCE_SENT":
        rec["state"] = "CLAIMED"
        rec["claimed_at"] = clock.now()
        db.touch(rec)
    return response.ok(derive.check_disbursement(successor), 201)
