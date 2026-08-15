from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import db
import errors
import middleware as mw
from response import success
from services import posture
from services.common import add_months_clamped, parse_dt, stamp_new, touch
from services.pagination import get_pagination, paginate
from services.serialize import option as ser_option
from services.validate import body_json, require_fields, req_int, req_number

bp = Blueprint("extensions", __name__)


@bp.post("/loans/<lid>/extension-options")
def create_option(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    loan = db.loans.get(lid)
    if loan is None:
        raise errors.not_found("Loan not found")
    data = body_json()
    require_fields(data, [
        "option_seq", "exercise_window_start", "exercise_window_end",
        "extension_months", "fee_pct",
    ])
    seq = req_int(data, "option_seq", minimum=1)
    wstart = parse_dt(data.get("exercise_window_start"), "exercise_window_start")
    wend = parse_dt(data.get("exercise_window_end"), "exercise_window_end")
    if wend < wstart:
        raise errors.invalid_request("exercise_window_end must not precede start")
    if wend >= loan["maturity_date_dt"]:
        raise errors.invalid_request("exercise_window_end must be strictly before loan maturity_date")
    months = req_int(data, "extension_months", gt=0)
    fee_pct = req_number(data, "fee_pct", minimum=0)
    existing = [o for o in db.extension_options.values() if o["loan_id"] == lid]
    # Window overlap / duplicate seq (priority 23) before count (priority 24).
    for o in existing:
        if o["option_seq"] == seq:
            raise errors.ApiError(
                errors.ERR_EXTENSION_WINDOW_OVERLAP,
                "option_seq must be unique per loan", 409)
        if wstart <= o["exercise_window_end_dt"] and o["exercise_window_start_dt"] <= wend:
            raise errors.ApiError(
                errors.ERR_EXTENSION_WINDOW_OVERLAP,
                "Exercise windows must not overlap on the same loan", 409)
    if len(existing) >= 2:
        raise errors.ApiError(
            errors.ERR_MAX_OPTIONS_REACHED,
            "A loan carries at most two extension options", 422)
    o = {
        "id": db.new_id(),
        "loan_id": lid,
        "option_seq": seq,
        "exercise_window_start": db.fmt_ts(wstart),
        "exercise_window_start_dt": wstart,
        "exercise_window_end": db.fmt_ts(wend),
        "exercise_window_end_dt": wend,
        "extension_months": months,
        "fee_pct": fee_pct,
        "status": "AVAILABLE",
        "exercised_fee_cents": None,
    }
    stamp_new(o)
    db.extension_options[o["id"]] = o
    return success(ser_option(o), status=201)


@bp.get("/loans/<lid>/extension-options")
def list_options(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    loan = db.loans.get(lid)
    if not mw.read_scope_allows(actor, "loan", loan):
        raise errors.not_found("Loan not found")
    limit, offset = get_pagination()
    items = [o for o in db.extension_options.values() if o["loan_id"] == lid]
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    page, pg = paginate([ser_option(o) for o in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.post("/extension-options/<oid>/exercise")
def exercise_option(oid):
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower"])
    o = db.extension_options.get(oid)
    if o is None:
        raise errors.not_found("ExtensionOption not found")
    mw.require_borrower_ownership(actor, "option", o)
    loan = db.loans.get(o["loan_id"])
    # Pipeline: state (7) -> covenant (9) -> currency (10) -> sequencing (27) -> window (30)
    if o["status"] != "AVAILABLE":
        raise errors.invalid_state("Only an AVAILABLE option can be exercised")
    if posture.loan_open_assessments(loan["id"]):
        raise errors.ApiError(
            errors.ERR_OPEN_COVENANT_BREACH,
            "OPEN covenant assessment blocks exercise", 409)
    if loan["payment_status"] != "CURRENT":
        raise errors.ApiError(
            errors.ERR_LOAN_NOT_CURRENT, "Loan must be CURRENT", 409)
    if o["option_seq"] > 1:
        prev = [
            x for x in db.extension_options.values()
            if x["loan_id"] == loan["id"] and x["option_seq"] == o["option_seq"] - 1
        ]
        if not prev or prev[0]["status"] != "EXERCISED":
            raise errors.ApiError(
                errors.ERR_EXTENSION_SEQUENCE_VIOLATION,
                "The preceding option must be EXERCISED first", 409)
    clock = db.get_clock()
    if not (o["exercise_window_start_dt"] <= clock <= o["exercise_window_end_dt"]):
        raise errors.ApiError(
            errors.ERR_EXTENSION_WINDOW_CLOSED,
            "Exercise must fall inside the inclusive window", 409)
    fee = int(
        (Decimal(loan["current_balance_cents"]) * Decimal(str(o["fee_pct"])))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    o["status"] = "EXERCISED"
    o["exercised_fee_cents"] = fee
    touch(o)
    new_maturity = add_months_clamped(loan["maturity_date_dt"], o["extension_months"])
    loan["maturity_date_dt"] = new_maturity
    loan["maturity_date"] = db.fmt_ts(new_maturity)
    touch(loan)
    return success(ser_option(o))
