"""Consumer Claim & Rebate Aggregator — Flask REST API.

Entry point: registers all 38 routes, auth/validation middleware, error handler.
State is in-memory only (see db.py) and starts empty on every process boot.
"""
import os
from datetime import timedelta

from flask import Flask, request

from db import store, new_id, parse_dt
from errors import ApiError, err
from response import ok, ok_list, error_body
import calc

app = Flask(__name__)

RECOGNIZED_ROLES = {
    "Anonymous", "Consumer", "ClaimReviewer",
    "FraudAnalyst", "ProgramManager", "PlatformAdmin",
}

PROGRAM_CATEGORIES = {"PRODUCT_REBATE", "CLASS_ACTION", "WARRANTY", "PRICE_ADJUSTMENT"}
DISTRIBUTION_METHODS = {"FIXED", "PRO_RATA"}
DOC_TYPES = {"RECEIPT", "PROOF_OF_PURCHASE", "ID", "OTHER"}
FRAUD_REASONS = {"DUPLICATE", "IDENTITY_MISMATCH", "SUSPICIOUS_DOCS", "INELIGIBLE_PURCHASE", "OTHER"}


# ---------------------------------------------------------------------------
# Auth / authorization
# ---------------------------------------------------------------------------
def authorize(allowed_roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or role not in RECOGNIZED_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role")
    if role != "Anonymous" and not uid:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID")
    if role != "PlatformAdmin" and role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")
    return uid, role


def authorize_register():
    """POST /consumers — Anonymous self-registration (auth check does not apply)."""
    role = request.headers.get("X-User-Role")
    if role is None:
        role = "Anonymous"
    if role not in {"Anonymous", "PlatformAdmin"}:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")
    return request.headers.get("X-User-ID"), role


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return b


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Missing or invalid field: " + field)
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Invalid field: " + field)
    return v


def req_int(body, field, positive=False, non_negative=False):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Missing or invalid integer: " + field)
    if positive and v <= 0:
        raise err("ERR_INVALID_REQUEST", field + " must be > 0")
    if non_negative and v < 0:
        raise err("ERR_INVALID_REQUEST", field + " must be >= 0")
    return v


def opt_int(body, field, default, positive=False, non_negative=False):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Invalid integer: " + field)
    if positive and v <= 0:
        raise err("ERR_INVALID_REQUEST", field + " must be > 0")
    if non_negative and v < 0:
        raise err("ERR_INVALID_REQUEST", field + " must be >= 0")
    return v


def opt_bool(body, field, default):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Invalid boolean: " + field)
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid enum value for " + field)
    return v


def req_dt(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Missing datetime: " + field)
    try:
        return parse_dt(v)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Invalid datetime: " + field)


def get_pagination():
    def pint(raw):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10 if limit_raw is None else pint(limit_raw)
    offset = 0 if offset_raw is None else pint(offset_raw)
    if limit is None or limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "Invalid limit")
    if offset is None or offset < 0:
        raise err("ERR_INVALID_REQUEST", "Invalid offset")
    return limit, offset


def list_page(records, serialize):
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def base_record(extra):
    now = store.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    rec.update(extra)
    return rec


def ledger_record(extra):
    rec = {
        "id": new_id(),
        "created_at": store.now(),
        "_seq": store.next_seq(),
    }
    rec.update(extra)
    return rec


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = store.now()


def notify(consumer_id, related_claim_id, event_type, body):
    n = ledger_record({
        "consumer_id": consumer_id,
        "related_claim_id": related_claim_id,
        "channel": "EMAIL",
        "event_type": event_type,
        "body": body,
        "read": False,
    })
    store.notifications[n["id"]] = n
    return n


def fund_txn(program, related_claim_id, ttype, amount, reason):
    t = ledger_record({
        "program_id": program["id"],
        "related_claim_id": related_claim_id,
        "type": ttype,
        "amount_cents": amount,
        "reason": reason,
        "balance_after_cents": calc.fund_remaining(program),
    })
    store.fund_transactions[t["id"]] = t
    return t


def lookup(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def ensure_claim_owner(claim, uid, role):
    if role == "Consumer" and claim["consumer_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Consumer does not own this claim")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_body(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_body("ERR_NOT_FOUND", "Resource not found"), 404


@app.errorhandler(405)
def handle_405(e):
    return error_body("ERR_NOT_FOUND", "Method not allowed"), 404


# ===========================================================================
# RebateProgram
# ===========================================================================
@app.post("/rebate-aggregator/programs")
def create_program():
    authorize({"ProgramManager", "PlatformAdmin"})
    body = get_body()
    name = req_str(body, "name")
    settlement_case_id = req_str(body, "settlement_case_id")
    category = req_enum(body, "category", PROGRAM_CATEGORIES)
    distribution_method = req_enum(body, "distribution_method", DISTRIBUTION_METHODS)
    fund_total = req_int(body, "fund_total_cents", positive=True)
    advertised = req_int(body, "advertised_amount_cents", non_negative=True)
    per_claim_cap = req_int(body, "per_claim_cap_cents", positive=True)
    elig_min = opt_int(body, "eligibility_min_purchase_cents", 0, non_negative=True)
    requires_proof = opt_bool(body, "requires_proof", True)
    min_documents = opt_int(body, "min_documents", 1, non_negative=True)
    open_at = req_dt(body, "claim_window_open_at")
    close_at = req_dt(body, "claim_window_close_at")
    if not (open_at < close_at):
        raise err("ERR_INVALID_REQUEST", "claim_window_open_at must precede claim_window_close_at")

    # Window-conflict guard vs same settlement_case_id (closed interval + buffer).
    buffer = timedelta(days=calc.PROGRAM_WINDOW_BUFFER_DAYS)
    for other in store.programs.values():
        if other["settlement_case_id"] != settlement_case_id:
            continue
        disjoint = (open_at >= other["claim_window_close_at"] + buffer) or \
                   (close_at <= other["claim_window_open_at"] - buffer)
        if not disjoint:
            raise err("ERR_PROGRAM_WINDOW_CONFLICT", "Program window conflicts with a same-case program")

    p = base_record({
        "name": name,
        "settlement_case_id": settlement_case_id,
        "category": category,
        "distribution_method": distribution_method,
        "fund_total_cents": fund_total,
        "advertised_amount_cents": advertised,
        "per_claim_cap_cents": per_claim_cap,
        "eligibility_min_purchase_cents": elig_min,
        "requires_proof": requires_proof,
        "min_documents": min_documents,
        "claim_window_open_at": open_at,
        "claim_window_close_at": close_at,
        "status": "DRAFT",
    })
    store.programs[p["id"]] = p
    return ok(calc.ser_program(p), 201)


@app.get("/rebate-aggregator/programs/<pid>")
def get_program(pid):
    authorize({"Consumer", "ClaimReviewer", "FraudAnalyst", "ProgramManager", "PlatformAdmin"})
    p = lookup(store.programs, pid)
    return ok(calc.ser_program(p))


@app.get("/rebate-aggregator/programs")
def list_programs():
    authorize({"Consumer", "ClaimReviewer", "FraudAnalyst", "ProgramManager", "PlatformAdmin"})
    category = request.args.get("category")
    status = request.args.get("status")
    case_id = request.args.get("settlement_case_id")
    recs = list(store.programs.values())
    if category is not None:
        recs = [r for r in recs if r["category"] == category]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    if case_id is not None:
        recs = [r for r in recs if r["settlement_case_id"] == case_id]
    return list_page(recs, calc.ser_program)


@app.get("/rebate-aggregator/programs/<pid>/report")
def program_report(pid):
    authorize({"ProgramManager", "PlatformAdmin"})
    p = lookup(store.programs, pid)
    claims = [c for c in store.claims.values() if c["program_id"] == pid]
    payouts = calc.program_payouts(pid)
    not_reversed = [po for po in payouts if po["status"] != "REVERSED"]
    cleared = [po for po in payouts if po["status"] == "CLEARED"]
    total_cleared = sum(po["net_amount_cents"] for po in cleared)
    avg_net = calc.round_half_up(total_cleared / len(cleared)) if cleared else 0
    report = {
        "program_id": pid,
        "total_claims": len(claims),
        "approved_claims": sum(1 for c in claims if c["status"] == "APPROVED"),
        "rejected_claims": sum(1 for c in claims if c["status"] == "REJECTED"),
        "expired_claims": sum(1 for c in claims if c["status"] == "EXPIRED"),
        "total_committed_cents": sum(po["gross_amount_cents"] for po in not_reversed),
        "total_fees_cents": sum(po["fee_amount_cents"] for po in not_reversed),
        "total_cleared_cents": total_cleared,
        "fund_total_cents": p["fund_total_cents"],
        "fund_remaining_cents": calc.fund_remaining(p),
        "average_net_payout_cents": avg_net,
    }
    return ok(report)


@app.get("/rebate-aggregator/programs/<pid>/fund-transactions")
def program_fund_transactions(pid):
    authorize({"ProgramManager", "PlatformAdmin"})
    lookup(store.programs, pid)
    recs = [t for t in store.fund_transactions.values() if t["program_id"] == pid]
    return list_page(recs, calc.ser_fund_transaction)


@app.post("/rebate-aggregator/programs/<pid>/open")
def open_program(pid):
    authorize({"ProgramManager", "PlatformAdmin"})
    p = lookup(store.programs, pid)
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Program is not DRAFT")
    p["status"] = "OPEN"
    touch(p)
    return ok(calc.ser_program(p))


@app.post("/rebate-aggregator/programs/<pid>/close")
def close_program(pid):
    authorize({"ProgramManager", "PlatformAdmin"})
    p = lookup(store.programs, pid)
    if p["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Program is not OPEN")

    if p["distribution_method"] == "PRO_RATA":
        _pro_rata_settle(p)

    # Expiry sweep: non-terminal claims -> EXPIRED.
    for c in list(store.claims.values()):
        if c["program_id"] == pid and c["status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
            c["status"] = "EXPIRED"
            touch(c)
            notify(c["consumer_id"], c["id"], "CLAIM_EXPIRED", "Your claim has expired.")

    p["status"] = "CLOSED"
    touch(p)
    return ok(calc.ser_program(p))


def _pro_rata_settle(program):
    approved = [c for c in store.claims.values()
                if c["program_id"] == program["id"] and c["status"] == "APPROVED"]
    approved.sort(key=lambda c: (c["created_at"], c["_seq"]))
    if not approved:
        return
    total_claimed = sum(c["claimed_amount_cents"] for c in approved)
    pool = program["fund_total_cents"]
    finals = {}
    if total_claimed <= pool:
        for c in approved:
            finals[c["id"]] = min(c["claimed_amount_cents"], program["per_claim_cap_cents"])
    else:
        for c in approved:
            finals[c["id"]] = calc.floor_share(c["claimed_amount_cents"], total_claimed, pool)
        remainder = pool - sum(finals.values())
        for c in approved:
            if remainder <= 0:
                break
            finals[c["id"]] += 1
            remainder -= 1
    for c in approved:
        final = finals[c["id"]]
        consumer = store.consumers[c["consumer_id"]]
        verified = consumer["identity_status"] == "VERIFIED"
        fee = calc.contingency_fee(final, verified)
        net = final - fee
        c["final_payout_cents"] = final
        c["contingency_fee_cents"] = fee
        c["net_payout_cents"] = net
        touch(c)
        payout = base_record({
            "claim_id": c["id"],
            "gross_amount_cents": final,
            "fee_amount_cents": fee,
            "net_amount_cents": net,
            "attempt_count": 1,
            "status": "INITIATED",
        })
        store.payouts[payout["id"]] = payout
        fund_txn(program, c["id"], "DEBIT", final, "PAYOUT_COMMIT")


# ===========================================================================
# Consumer
# ===========================================================================
@app.post("/rebate-aggregator/consumers")
def create_consumer():
    authorize_register()
    body = get_body()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    for c in store.consumers.values():
        if c["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", "Email already registered")
    c = base_record({
        "email": email,
        "full_name": full_name,
        "identity_status": "UNVERIFIED",
    })
    store.consumers[c["id"]] = c
    return ok(calc.ser_consumer(c), 201)


@app.get("/rebate-aggregator/consumers/<cid>")
def get_consumer(cid):
    uid, role = authorize({"Consumer", "ClaimReviewer", "FraudAnalyst", "ProgramManager", "PlatformAdmin"})
    c = lookup(store.consumers, cid)
    if role == "Consumer" and cid != uid:
        raise err("ERR_UNAUTHORIZED", "Consumer may only read their own record")
    return ok(calc.ser_consumer(c))


@app.post("/rebate-aggregator/consumers/<cid>/verify")
def verify_consumer(cid):
    authorize({"PlatformAdmin"})
    c = lookup(store.consumers, cid)
    if c["identity_status"] != "UNVERIFIED":
        raise err("ERR_INVALID_STATE", "Consumer is not UNVERIFIED")
    c["identity_status"] = "VERIFIED"
    touch(c)
    return ok(calc.ser_consumer(c))


@app.get("/rebate-aggregator/consumers/<cid>/notifications")
def consumer_notifications(cid):
    uid, role = authorize({"Consumer", "ProgramManager", "PlatformAdmin"})
    lookup(store.consumers, cid)
    if role == "Consumer" and cid != uid:
        raise err("ERR_UNAUTHORIZED", "Consumer may only read their own notifications")
    recs = [n for n in store.notifications.values() if n["consumer_id"] == cid]
    read_arg = request.args.get("read")
    if read_arg is not None:
        want = read_arg.lower() == "true"
        recs = [n for n in recs if n["read"] == want]
    return list_page(recs, calc.ser_notification)


# ===========================================================================
# Match
# ===========================================================================
@app.post("/rebate-aggregator/matches")
def create_match():
    authorize({"ProgramManager", "PlatformAdmin"})
    body = get_body()
    consumer_id = req_str(body, "consumer_id")
    program_id = req_str(body, "program_id")
    lookup(store.consumers, consumer_id)
    program = lookup(store.programs, program_id)
    score = 50
    if program["status"] == "OPEN":
        score += 30
    now = store.now()
    if program["claim_window_open_at"] <= now < program["claim_window_close_at"]:
        score += 20
    score = min(100, score)
    m = base_record({
        "consumer_id": consumer_id,
        "program_id": program_id,
        "match_score": score,
        "status": "CANDIDATE",
    })
    store.matches[m["id"]] = m
    return ok(calc.ser_match(m), 201)


@app.get("/rebate-aggregator/matches/<mid>")
def get_match(mid):
    uid, role = authorize({"Consumer", "ProgramManager", "PlatformAdmin"})
    m = lookup(store.matches, mid)
    if role == "Consumer" and m["consumer_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Consumer may only read their own matches")
    return ok(calc.ser_match(m))


@app.get("/rebate-aggregator/matches")
def list_matches():
    uid, role = authorize({"Consumer", "ProgramManager", "PlatformAdmin"})
    recs = list(store.matches.values())
    if role == "Consumer":
        recs = [r for r in recs if r["consumer_id"] == uid]
    consumer_id = request.args.get("consumer_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if consumer_id is not None:
        recs = [r for r in recs if r["consumer_id"] == consumer_id]
    if program_id is not None:
        recs = [r for r in recs if r["program_id"] == program_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return list_page(recs, calc.ser_match)


# ===========================================================================
# Claim
# ===========================================================================
@app.post("/rebate-aggregator/claims")
def create_claim():
    uid, role = authorize({"Consumer", "PlatformAdmin"})
    body = get_body()
    consumer_id = body.get("consumer_id")
    if role == "Consumer" and consumer_id is not None and consumer_id != uid:
        raise err("ERR_UNAUTHORIZED", "Consumer may only file their own claims")
    consumer_id = req_str(body, "consumer_id")
    program_id = req_str(body, "program_id")
    match_id = body.get("match_id")
    lookup(store.consumers, consumer_id)
    lookup(store.programs, program_id)
    match = None
    if match_id is not None:
        if not isinstance(match_id, str):
            raise err("ERR_INVALID_REQUEST", "Invalid match_id")
        match = lookup(store.matches, match_id)
    start = req_dt(body, "benefit_period_start")
    end = req_dt(body, "benefit_period_end")
    if not (start < end):
        raise err("ERR_INVALID_REQUEST", "benefit_period_start must precede benefit_period_end")
    claimed = req_int(body, "claimed_amount_cents", positive=True)

    if match is not None:
        if match["consumer_id"] != consumer_id or match["program_id"] != program_id:
            raise err("ERR_MATCH_MISMATCH", "Match does not belong to this consumer/program")

    c = base_record({
        "consumer_id": consumer_id,
        "program_id": program_id,
        "benefit_period_start": start,
        "benefit_period_end": end,
        "claimed_amount_cents": claimed,
        "provisional_payout_cents": None,
        "final_payout_cents": None,
        "contingency_fee_cents": None,
        "net_payout_cents": None,
        "eligibility_status": "UNASSESSED",
        "needs_info_count": 0,
        "submitted_at": None,
        "status": "DRAFT",
    })
    store.claims[c["id"]] = c
    if match is not None and match["status"] == "CANDIDATE":
        match["status"] = "CONVERTED"
        touch(match)
    return ok(calc.ser_claim(c), 201)


@app.get("/rebate-aggregator/claims/<clid>")
def get_claim(clid):
    uid, role = authorize({"Consumer", "ClaimReviewer", "FraudAnalyst", "ProgramManager", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    ensure_claim_owner(c, uid, role)
    return ok(calc.ser_claim(c))


@app.get("/rebate-aggregator/claims")
def list_claims():
    uid, role = authorize({"Consumer", "ClaimReviewer", "FraudAnalyst", "ProgramManager", "PlatformAdmin"})
    recs = list(store.claims.values())
    if role == "Consumer":
        recs = [r for r in recs if r["consumer_id"] == uid]
    consumer_id = request.args.get("consumer_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if consumer_id is not None:
        recs = [r for r in recs if r["consumer_id"] == consumer_id]
    if program_id is not None:
        recs = [r for r in recs if r["program_id"] == program_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return list_page(recs, calc.ser_claim)


@app.post("/rebate-aggregator/claims/<clid>/documents")
def upload_document(clid):
    uid, role = authorize({"Consumer", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    ensure_claim_owner(c, uid, role)
    body = get_body()
    doc_type = req_enum(body, "doc_type", DOC_TYPES)
    file_ref = req_str(body, "file_ref")
    d = base_record({
        "claim_id": clid,
        "doc_type": doc_type,
        "file_ref": file_ref,
        "status": "PENDING",
        "rejection_reason": None,
    })
    store.documents[d["id"]] = d
    return ok(calc.ser_document(d), 201)


@app.get("/rebate-aggregator/claims/<clid>/documents")
def list_documents(clid):
    uid, role = authorize({"Consumer", "ClaimReviewer", "FraudAnalyst", "ProgramManager", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    ensure_claim_owner(c, uid, role)
    recs = [d for d in store.documents.values() if d["claim_id"] == clid]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return list_page(recs, calc.ser_document)


@app.post("/rebate-aggregator/claims/<clid>/submit")
def submit_claim(clid):
    uid, role = authorize({"Consumer", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    ensure_claim_owner(c, uid, role)
    if c["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Claim is not DRAFT")
    program = store.programs[c["program_id"]]
    # Business rules in fixed order (PRD §3.3).
    if program["status"] != "OPEN":
        raise err("ERR_PROGRAM_NOT_OPEN", "Program is not OPEN")
    now = store.now()
    if not (program["claim_window_open_at"] <= now < program["claim_window_close_at"]):
        raise err("ERR_CLAIM_WINDOW_CLOSED", "Outside the claim window")
    for other in store.claims.values():
        if other["id"] == clid:
            continue
        if other["consumer_id"] != c["consumer_id"] or other["program_id"] != c["program_id"]:
            continue
        if other["status"] in ("REJECTED", "EXPIRED"):
            continue
        if (c["benefit_period_start"] < other["benefit_period_end"] and
                other["benefit_period_start"] < c["benefit_period_end"]):
            raise err("ERR_BENEFIT_PERIOD_OVERLAP", "Benefit period overlaps a live claim")
    if program["requires_proof"] and calc.document_count(clid) < program["min_documents"]:
        raise err("ERR_INSUFFICIENT_DOCUMENTS", "Not enough documents")
    if c["claimed_amount_cents"] < program["eligibility_min_purchase_cents"]:
        raise err("ERR_NOT_ELIGIBLE", "Claimed amount below eligibility floor")

    c["status"] = "SUBMITTED"
    c["submitted_at"] = now
    c["provisional_payout_cents"] = calc.provisional_payout(c, program)
    touch(c)
    notify(c["consumer_id"], clid, "CLAIM_SUBMITTED", "Your claim was submitted.")
    return ok(calc.ser_claim(c))


@app.post("/rebate-aggregator/claims/<clid>/start-review")
def start_review(clid):
    uid, role = authorize({"ClaimReviewer", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim is not SUBMITTED")
    program = store.programs[c["program_id"]]
    _run_assessment(c, program, uid)
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return ok(calc.ser_claim(c))


def _run_assessment(claim, program, uid):
    min_met, docs_ok, eligible, reasons = calc.eligibility(claim, program)
    a = base_record({
        "claim_id": claim["id"],
        "assessed_by_user_id": uid,
        "eligible": eligible,
        "min_purchase_met": min_met,
        "documents_sufficient": docs_ok,
        "reasons": reasons,
        "assessed_at": store.now(),
    })
    store.assessments[a["id"]] = a
    claim["eligibility_status"] = "ELIGIBLE" if eligible else "INELIGIBLE"
    return a


@app.post("/rebate-aggregator/claims/<clid>/request-info")
def request_info(clid):
    authorize({"ClaimReviewer", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    if c["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")
    get_body()  # optional message; not persisted
    c["needs_info_count"] += 1
    c["status"] = "NEEDS_INFO"
    touch(c)
    notify(c["consumer_id"], clid, "NEEDS_INFO", "More information is required.")
    return ok(calc.ser_claim(c))


@app.post("/rebate-aggregator/claims/<clid>/resubmit")
def resubmit_claim(clid):
    uid, role = authorize({"Consumer", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    ensure_claim_owner(c, uid, role)
    if c["status"] != "NEEDS_INFO":
        raise err("ERR_INVALID_STATE", "Claim is not NEEDS_INFO")
    program = store.programs[c["program_id"]]
    min_met, docs_ok, eligible, reasons = calc.eligibility(c, program)
    c["eligibility_status"] = "ELIGIBLE" if eligible else "INELIGIBLE"
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return ok(calc.ser_claim(c))


@app.post("/rebate-aggregator/claims/<clid>/approve")
def approve_claim(clid):
    authorize({"ClaimReviewer", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    body = get_body()
    expected_version = req_int(body, "expected_program_version")
    program = store.programs[c["program_id"]]
    consumer = store.consumers[c["consumer_id"]]
    # Precedence: state, OCC, eligibility, fraud hold, risk, fiscal (PRD §3.5).
    if c["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")
    if expected_version != program["version"]:
        raise err("ERR_STALE_PROGRAM_VERSION", "Stale program version")
    if c["eligibility_status"] != "ELIGIBLE":
        raise err("ERR_NOT_ELIGIBLE", "Claim is not ELIGIBLE")
    if calc.claim_fraud_status(clid) == "CONFIRMED":
        raise err("ERR_FRAUD_HOLD", "Claim is on fraud hold")
    opt, _ = calc.risk_scores(consumer)
    if opt >= calc.RISK_THRESHOLD:
        raise err("ERR_RISK_THRESHOLD_EXCEEDED", "Consumer risk too high")

    if program["distribution_method"] == "FIXED":
        fr = calc.fund_remaining(program)
        final = min(c["provisional_payout_cents"], program["per_claim_cap_cents"], fr)
        if final <= 0:
            raise err("ERR_FUND_EXHAUSTED", "No fund remaining")
        verified = consumer["identity_status"] == "VERIFIED"
        fee = calc.contingency_fee(final, verified)
        net = final - fee
        c["final_payout_cents"] = final
        c["contingency_fee_cents"] = fee
        c["net_payout_cents"] = net
        c["status"] = "APPROVED"
        touch(c)
        payout = base_record({
            "claim_id": clid,
            "gross_amount_cents": final,
            "fee_amount_cents": fee,
            "net_amount_cents": net,
            "attempt_count": 1,
            "status": "INITIATED",
        })
        store.payouts[payout["id"]] = payout
        fund_txn(program, clid, "DEBIT", final, "PAYOUT_COMMIT")
        program["version"] += 1
        program["updated_at"] = store.now()
        notify(c["consumer_id"], clid, "CLAIM_APPROVED", "Your claim was approved.")
        if calc.fund_remaining(program) == 0:
            _exhaust_program(program, clid)
    else:
        c["status"] = "APPROVED"
        touch(c)
        program["version"] += 1
        program["updated_at"] = store.now()
        notify(c["consumer_id"], clid, "CLAIM_APPROVED", "Your claim was approved.")
    return ok(calc.ser_claim(c))


def _exhaust_program(program, exclude_claim_id):
    program["status"] = "EXHAUSTED"
    program["updated_at"] = store.now()
    for c in list(store.claims.values()):
        if c["program_id"] != program["id"] or c["id"] == exclude_claim_id:
            continue
        if c["status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
            c["status"] = "REJECTED"
            touch(c)
            notify(c["consumer_id"], c["id"], "CLAIM_REJECTED", "Your claim was rejected (fund exhausted).")


@app.post("/rebate-aggregator/claims/<clid>/reject")
def reject_claim(clid):
    authorize({"ClaimReviewer", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    if c["status"] not in ("UNDER_REVIEW", "NEEDS_INFO"):
        raise err("ERR_INVALID_STATE", "Claim cannot be rejected from its current state")
    get_body()  # optional reason
    c["status"] = "REJECTED"
    touch(c)
    notify(c["consumer_id"], clid, "CLAIM_REJECTED", "Your claim was rejected.")
    return ok(calc.ser_claim(c))


@app.get("/rebate-aggregator/claims/<clid>/eligibility-assessments")
def list_assessments(clid):
    uid, role = authorize({"Consumer", "ClaimReviewer", "ProgramManager", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    ensure_claim_owner(c, uid, role)
    recs = [a for a in store.assessments.values() if a["claim_id"] == clid]
    return list_page(recs, calc.ser_assessment)


# ===========================================================================
# Documents (review)
# ===========================================================================
@app.post("/rebate-aggregator/documents/<did>/verify")
def verify_document(did):
    authorize({"ClaimReviewer", "PlatformAdmin"})
    d = lookup(store.documents, did)
    if d["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Document is not PENDING")
    d["status"] = "VERIFIED"
    touch(d)
    return ok(calc.ser_document(d))


@app.post("/rebate-aggregator/documents/<did>/reject")
def reject_document(did):
    authorize({"ClaimReviewer", "PlatformAdmin"})
    d = lookup(store.documents, did)
    body = get_body()
    reason = req_str(body, "rejection_reason")
    if d["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Document is not PENDING")
    d["status"] = "REJECTED"
    d["rejection_reason"] = reason
    touch(d)
    claim = store.claims.get(d["claim_id"])
    if claim is not None and claim["status"] in ("SUBMITTED", "UNDER_REVIEW"):
        claim["status"] = "NEEDS_INFO"
        claim["needs_info_count"] += 1
        touch(claim)
        notify(claim["consumer_id"], claim["id"], "NEEDS_INFO", "A document was rejected; more info required.")
    return ok(calc.ser_document(d))


# ===========================================================================
# Fraud
# ===========================================================================
@app.post("/rebate-aggregator/claims/<clid>/fraud-flags")
def raise_fraud_flag(clid):
    uid, role = authorize({"FraudAnalyst", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    body = get_body()
    reason = req_enum(body, "reason", FRAUD_REASONS)
    f = base_record({
        "claim_id": clid,
        "raised_by_user_id": uid,
        "reason": reason,
        "status": "OPEN",
        "cleared_by_user_id": None,
        "resolution_note": None,
    })
    store.fraud_flags[f["id"]] = f
    notify(c["consumer_id"], clid, "FRAUD_FLAGGED", "A fraud flag was raised on your claim.")
    return ok(calc.ser_fraud_flag(f), 201)


@app.get("/rebate-aggregator/claims/<clid>/fraud-flags")
def list_fraud_flags(clid):
    authorize({"FraudAnalyst", "ClaimReviewer", "ProgramManager", "PlatformAdmin"})
    lookup(store.claims, clid)
    recs = [f for f in store.fraud_flags.values() if f["claim_id"] == clid]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return list_page(recs, calc.ser_fraud_flag)


@app.post("/rebate-aggregator/fraud-flags/<fid>/confirm")
def confirm_fraud_flag(fid):
    authorize({"FraudAnalyst", "PlatformAdmin"})
    f = lookup(store.fraud_flags, fid)
    if f["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Fraud flag is not OPEN")
    body = get_body()
    note = opt_str(body, "resolution_note")
    f["status"] = "CONFIRMED"
    if note is not None:
        f["resolution_note"] = note
    touch(f)
    claim = store.claims.get(f["claim_id"])
    if claim is not None:
        consumer = store.consumers.get(claim["consumer_id"])
        if consumer is not None and consumer["identity_status"] in ("UNVERIFIED", "VERIFIED"):
            consumer["identity_status"] = "SUSPENDED"
            touch(consumer)
    return ok(calc.ser_fraud_flag(f))


@app.post("/rebate-aggregator/fraud-flags/<fid>/clear")
def clear_fraud_flag(fid):
    uid, role = authorize({"FraudAnalyst", "PlatformAdmin"})
    f = lookup(store.fraud_flags, fid)
    if f["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Fraud flag is not OPEN")
    if uid == f["raised_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Cannot clear a flag you raised")
    body = get_body()
    note = opt_str(body, "resolution_note")
    f["status"] = "CLEARED"
    f["cleared_by_user_id"] = uid
    if note is not None:
        f["resolution_note"] = note
    touch(f)
    return ok(calc.ser_fraud_flag(f))


# ===========================================================================
# Payout
# ===========================================================================
@app.get("/rebate-aggregator/claims/<clid>/payouts")
def list_payouts(clid):
    uid, role = authorize({"Consumer", "ClaimReviewer", "ProgramManager", "PlatformAdmin"})
    c = lookup(store.claims, clid)
    ensure_claim_owner(c, uid, role)
    recs = [p for p in store.payouts.values() if p["claim_id"] == clid]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return list_page(recs, calc.ser_payout)


@app.post("/rebate-aggregator/payouts/<pid>/clear")
def clear_payout(pid):
    authorize({"PlatformAdmin"})
    p = lookup(store.payouts, pid)
    if p["status"] != "INITIATED":
        raise err("ERR_INVALID_STATE", "Payout is not INITIATED")
    claim = store.claims[p["claim_id"]]
    consumer = store.consumers[claim["consumer_id"]]
    if consumer["identity_status"] != "VERIFIED":
        raise err("ERR_CONSUMER_NOT_VERIFIED", "Consumer is not VERIFIED")
    _, pess = calc.risk_scores(consumer)
    if pess >= calc.RISK_THRESHOLD:
        raise err("ERR_RISK_THRESHOLD_EXCEEDED", "Consumer risk too high")
    p["status"] = "CLEARED"
    touch(p)
    notify(consumer["id"], claim["id"], "PAYOUT_CLEARED", "Your payout was cleared.")
    return ok(calc.ser_payout(p))


@app.post("/rebate-aggregator/payouts/<pid>/fail")
def fail_payout(pid):
    authorize({"PlatformAdmin"})
    p = lookup(store.payouts, pid)
    if p["status"] != "INITIATED":
        raise err("ERR_INVALID_STATE", "Payout is not INITIATED")
    get_body()  # optional reason
    p["status"] = "FAILED"
    touch(p)
    claim = store.claims[p["claim_id"]]
    notify(claim["consumer_id"], claim["id"], "PAYOUT_FAILED", "Your payout failed.")
    return ok(calc.ser_payout(p))


@app.post("/rebate-aggregator/payouts/<pid>/retry")
def retry_payout(pid):
    authorize({"PlatformAdmin"})
    p = lookup(store.payouts, pid)
    if p["status"] != "FAILED":
        raise err("ERR_INVALID_STATE", "Payout is not FAILED")
    p["status"] = "INITIATED"
    p["attempt_count"] += 1
    touch(p)
    return ok(calc.ser_payout(p))


@app.post("/rebate-aggregator/payouts/<pid>/reverse")
def reverse_payout(pid):
    authorize({"PlatformAdmin"})
    p = lookup(store.payouts, pid)
    if p["status"] != "CLEARED":
        raise err("ERR_INVALID_STATE", "Payout is not CLEARED")
    get_body()  # optional reason
    claim = store.claims[p["claim_id"]]
    program = store.programs[claim["program_id"]]
    p["status"] = "REVERSED"
    touch(p)
    fund_txn(program, claim["id"], "CREDIT", p["gross_amount_cents"], "PAYOUT_REVERSAL")
    program["version"] += 1
    program["updated_at"] = store.now()
    return ok(calc.ser_payout(p))


# ===========================================================================
# Logical clock
# ===========================================================================
@app.post("/rebate-aggregator/_clock/set_current_utc")
def set_clock():
    authorize({"PlatformAdmin"})
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise err("ERR_INVALID_REQUEST", "Missing to_iso8601")
    try:
        instant = parse_dt(to_iso)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Invalid to_iso8601")
    store.clock = instant
    from db import fmt_dt
    return ok({"current_utc": fmt_dt(store.clock)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
