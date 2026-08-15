"""Routes: billing claims and stipend ledger entries."""
from flask import Blueprint, request

from store import db
from errors import ApiError, err_invalid_request
from envelope import ok, ok_list
from validate import auth, get_body, check_body, sort_and_page, apply_filters, valid_month_str
import calc
import services
import serializers as ser

bp = Blueprint("billing", __name__, url_prefix="/anesthesia-ops")

BILLER = ["BillingSpecialist"]
ALL = ["GroupAdministrator", "Scheduler", "AttendingAnesthesiologist", "CRNA",
       "BillingSpecialist", "ComplianceAuditor"]
LEDGER_READERS = ["GroupAdministrator", "Scheduler", "BillingSpecialist"]


def _get_claim(claim_id):
    rec = db.claims.get(claim_id)
    if rec is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "Claim not found")
    return rec


# ------------------------------------------------------------------ claims ----
@bp.post("/claims")
def create_claim_manual():
    auth(BILLER)
    body = get_body()
    check_body(body, {
        "case_id": {"kind": "str", "req": True},
        "provider_id": {"kind": "str", "req": True},
    })
    case = db.cases.get(body["case_id"])
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "Case not found")
    provider = db.providers.get(body["provider_id"])
    if provider is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "Provider not found")
    target = None
    primary = None
    directing = None
    if case["status"] == "COMPLETED":
        for a in db.assignments.values():
            if a["case_id"] != case["id"] or a["status"] != "COMPLETED":
                continue
            if a["provider_id"] == provider["id"]:
                target = a
            if a["assignment_role"] == "CASE_PRIMARY":
                primary = a
            elif a["assignment_role"] == "CASE_DIRECTING":
                directing = a
    if target is None:
        raise ApiError("ERR_NO_COMPLETED_ASSIGNMENT", 409,
                       "Case is not COMPLETED or provider has no COMPLETED assignment on it")
    rec = services.create_claim(case, target, primary, directing)
    return ok(ser.claim(rec), 201)


@bp.get("/claims")
def list_claims():
    auth(ALL)
    items = apply_filters(db.claims.values(), request.args,
                          ["case_id", "provider_id", "status", "modifier_code"])
    page, limit, offset, total = sort_and_page(items, request.args)
    return ok_list([ser.claim(r) for r in page], limit, offset, total)


@bp.get("/claims/<claim_id>")
def get_claim(claim_id):
    auth(ALL)
    return ok(ser.claim(_get_claim(claim_id)))


@bp.post("/claims/<claim_id>/mark-ready")
def mark_ready(claim_id):
    auth(BILLER)
    get_body()
    rec = _get_claim(claim_id)
    if rec["status"] not in ("DRAFT", "DENIED"):
        raise ApiError("ERR_CLAIM_NOT_READYABLE", 409,
                       "mark-ready requires status DRAFT or DENIED")
    # referential duplicate check deliberately precedes the fiscal check
    for c in db.claims.values():
        if c["id"] != rec["id"] and c["case_id"] == rec["case_id"] \
                and c["provider_id"] == rec["provider_id"] \
                and c["status"] in ("READY", "SUBMITTED", "PAID"):
            raise ApiError("ERR_DUPLICATE_CLAIM", 409,
                           "Another claim for this case and provider is READY/SUBMITTED/PAID")
    case = db.cases[rec["case_id"]]
    fee = calc.fee_by_code(case["procedure_code"])
    if fee is not None and rec["charge_cents"] > fee["contracted_max_cents"]:
        raise ApiError("ERR_CHARGE_EXCEEDS_MAX", 402,
                       "charge_cents exceeds the contracted maximum")
    if rec["status"] == "DENIED":
        rec["resubmission_count"] += 1
        rec["denial_reason"] = None
    rec["status"] = "READY"
    db.bump(rec)
    return ok(ser.claim(rec))


@bp.post("/claims/<claim_id>/submit")
def submit_claim(claim_id):
    auth(BILLER)
    get_body()
    rec = _get_claim(claim_id)
    case = db.cases[rec["case_id"]]
    roster = db.rosters[case["roster_id"]]
    if roster["lifecycle"] != "LOCKED":
        raise ApiError("ERR_ROSTER_NOT_LOCKED", 409,
                       "Claim submit requires the case's roster to be LOCKED")
    if rec["status"] != "READY":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTABLE", 409, "Claim is not READY")
    rec["status"] = "SUBMITTED"
    db.bump(rec)
    return ok(ser.claim(rec))


@bp.post("/claims/<claim_id>/record-payment")
def record_payment(claim_id):
    auth(BILLER)
    body = get_body()
    check_body(body, {"paid_amount_cents": {"kind": "int", "req": True}})
    rec = _get_claim(claim_id)
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SETTLABLE", 409, "Claim is not SUBMITTED")
    rec["status"] = "PAID"
    rec["paid_amount_cents"] = body["paid_amount_cents"]
    db.bump(rec)
    return ok(ser.claim(rec))


@bp.post("/claims/<claim_id>/record-denial")
def record_denial(claim_id):
    auth(BILLER)
    body = get_body()
    check_body(body, {"denial_reason": {"kind": "str", "req": True}})
    rec = _get_claim(claim_id)
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SETTLABLE", 409, "Claim is not SUBMITTED")
    rec["status"] = "DENIED"
    rec["denial_reason"] = body["denial_reason"]
    db.bump(rec)
    return ok(ser.claim(rec))


@bp.post("/claims/<claim_id>/write-off")
def write_off(claim_id):
    auth(BILLER)
    get_body()
    rec = _get_claim(claim_id)
    if rec["status"] not in ("SUBMITTED", "DENIED"):
        raise ApiError("ERR_CLAIM_NOT_SETTLABLE", 409,
                       "write-off requires status SUBMITTED or DENIED")
    rec["status"] = "WRITTEN_OFF"
    db.bump(rec)
    return ok(ser.claim(rec))


# --------------------------------------------------------- stipend entries ----
@bp.get("/stipend-entries/summary")
def stipend_summary():
    auth(LEDGER_READERS)
    provider_id = request.args.get("provider_id")
    month = request.args.get("month")
    if provider_id is None or month is None:
        raise err_invalid_request("provider_id and month query parameters are required")
    if not valid_month_str(month):
        raise err_invalid_request("month must be in YYYY-MM form")
    if db.providers.get(provider_id) is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "Provider not found")
    entries = [e for e in db.stipend_entries.values()
               if e["provider_id"] == provider_id and e["status"] != "VOIDED"
               and e["occurred_date"][:7] == month]
    gross = sum(e["amount_cents"] for e in entries)
    entries.sort(key=lambda e: (e["occurred_date"], e["created_at"], e["_seq"]))
    running = 0
    for e in entries:
        running += min(e["applied_amount_cents"],
                       max(0, calc.MONTHLY_STIPEND_CAP_CENTS - running))
    return ok({
        "provider_id": provider_id,
        "month": month,
        "gross_cents": gross,
        "applied_cents": running,
        "capped_cents": gross - running,
        "entry_count": len(entries),
    })


@bp.get("/stipend-entries")
def list_stipend_entries():
    auth(LEDGER_READERS)
    items = apply_filters(db.stipend_entries.values(), request.args,
                          ["provider_id", "roster_id", "entry_type", "status"])
    page, limit, offset, total = sort_and_page(items, request.args)
    return ok_list([ser.stipend_entry(r) for r in page], limit, offset, total)


@bp.get("/stipend-entries/<entry_id>")
def get_stipend_entry(entry_id):
    auth(LEDGER_READERS)
    rec = db.stipend_entries.get(entry_id)
    if rec is None:
        raise ApiError("ERR_STIPEND_ENTRY_NOT_FOUND", 404, "Stipend entry not found")
    return ok(ser.stipend_entry(rec))


@bp.post("/stipend-entries/<entry_id>/void")
def void_stipend_entry(entry_id):
    auth(["GroupAdministrator"])
    get_body()
    rec = db.stipend_entries.get(entry_id)
    if rec is None:
        raise ApiError("ERR_STIPEND_ENTRY_NOT_FOUND", 404, "Stipend entry not found")
    if rec["status"] != "ACCRUED":
        raise ApiError("ERR_ENTRY_NOT_VOIDABLE", 409, "Entry is not ACCRUED")
    rec["status"] = "VOIDED"
    db.bump(rec)
    calc.run_daily_waterfall(rec["provider_id"], rec["occurred_date"])
    return ok(ser.stipend_entry(rec))
