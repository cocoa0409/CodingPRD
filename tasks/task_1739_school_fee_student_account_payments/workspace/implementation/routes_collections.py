"""Routes: ledger entries, reconciliation runs, collections cases, write-offs."""
from flask import Blueprint, jsonify, request

from core import (
    db, auth, body, req_int, envelope_obj, paginate, clock_now, fmt_ts,
    new_entity, touch, ApiError, err_invalid_request, err_invalid_state,
    get_or_404, get_scoped, observe_account, recompute_account,
    case_bucket, assessment_outstanding, write_ledger, dept_distributed,
    bump_dirty_departments,
)
from serializers import ser_ledger, ser_run, ser_case

bp = Blueprint("collections", __name__)
BK = ("Bookkeeper",)
Supt = ("Superintendent",)
ANY = ("Bookkeeper", "FamilyMember", "Superintendent")


def ok(payload, code=200):
    resp = jsonify(payload)
    resp.status_code = code
    return resp


# ---------------------------------------------------------------------------
# Ledger entries (account-scoped)
# ---------------------------------------------------------------------------

@bp.get("/student-accounts/<id>/ledger-entries")
def list_account_ledger(id):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    rows = [e for e in db.ledger.values() if e["student_account_id"] == id]
    if "department_id" in request.args:
        rows = [e for e in rows
                if e["department_id"] == request.args["department_id"]]
    if "entry_type" in request.args:
        rows = [e for e in rows if e["entry_type"] == request.args["entry_type"]]
    return ok(paginate(rows, ser_ledger))


# ---------------------------------------------------------------------------
# Reconciliation runs
# ---------------------------------------------------------------------------

@bp.post("/school-years/<id>/reconciliation-runs")
def create_reconciliation(id):
    auth(BK)
    year = get_or_404("years", id, "school year")
    run = new_entity("runs", {
        "school_year_id": id,
        "run_at": fmt_ts(clock_now()),
        "entries_reconciled": 0,
        "drift_detected": False,
        "status": "COMPLETED",
    })
    # stamp every unreconciled ledger entry of the year
    acct_year = {a["id"]: a for a in db.accounts.values()
                 if a["school_year_id"] == id}
    count = 0
    for e in db.ledger.values():
        if e["reconciliation_run_id"] is None and \
                e["student_account_id"] in acct_year:
            e["reconciliation_run_id"] = run["id"]
            count += 1
    run["entries_reconciled"] = count

    # per-department drift check: expected (gross derivations) vs actual (ledger)
    drift = False
    depts = [d for d in db.departments.values() if d["school_year_id"] == id]
    for d in depts:
        did = d["id"]
        alloc = 0
        for al in db.allocations.values():
            pay = db.payments.get(al["payment_id"])
            if pay is None or pay["status"] != "SUCCEEDED":
                continue
            a = db.assessments.get(al["fee_assessment_id"])
            if a is not None and a["department_id"] == did:
                alloc += al["allocated_cents"]
        purch = 0
        for p in db.purchases.values():
            if p["status"] in ("COMPLETED", "REFUNDED"):
                item = db.purchase_items.get(p["item_id"])
                if item is not None and item["department_id"] == did:
                    purch += p["amount_cents"]
        refunds = 0
        for r in db.refunds.values():
            if r["status"] != "EXECUTED":
                continue
            if r.get("fee_assessment_id"):
                a = db.assessments.get(r["fee_assessment_id"])
                if a is not None and a["department_id"] == did:
                    refunds += r["refund_cents"]
            elif r.get("purchase_id"):
                p = db.purchases.get(r["purchase_id"])
                item = db.purchase_items.get(p["item_id"]) if p else None
                if item is not None and item["department_id"] == did:
                    refunds += r["refund_cents"]
        writeoffs = 0
        for e in db.ledger.values():
            if e["department_id"] == did and e["entry_type"] == "WRITE_OFF_DEBIT":
                writeoffs += abs(e["amount_cents"])
        expected = alloc + purch - refunds - writeoffs
        actual = dept_distributed(did)
        if expected != actual:
            drift = True
        if d.get("reconciled_cents", 0) != actual:
            d["reconciled_cents"] = actual
            touch(d)
    run["drift_detected"] = drift
    return ok(envelope_obj(ser_run(run)), 201)


# ---------------------------------------------------------------------------
# Collections cases
# ---------------------------------------------------------------------------

@bp.get("/student-accounts/<id>/collections-cases")
def list_cases(id):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    rows = [c for c in db.cases.values() if c["student_account_id"] == id]
    if "status" in request.args:
        rows = [c for c in rows if c["status"] == request.args["status"]]
    return ok(paginate(rows, ser_case))


@bp.get("/student-accounts/<id>/collections-cases/<caseId>")
def get_case(id, caseId):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    c = get_scoped("cases", caseId, "student_account_id", id,
                   "collections case")
    return ok(envelope_obj(ser_case(c)))


@bp.post("/student-accounts/<id>/collections-cases/<caseId>/promise")
def promise_case(id, caseId):
    auth(BK)
    get_or_404("accounts", id, "student account")
    c = get_scoped("cases", caseId, "student_account_id", id,
                   "collections case")
    if c["status"] != "OPEN":
        raise err_invalid_state("Only an OPEN case can record a payment promise.")
    c["status"] = "PAYMENT_PROMISED"
    c["_promised_at"] = fmt_ts(clock_now())
    touch(c)
    return ok(envelope_obj(ser_case(c)))


@bp.post("/student-accounts/<id>/collections-cases/<caseId>/approve-writeoff")
def approve_writeoff(id, caseId):
    auth(Supt)
    get_or_404("accounts", id, "student account")
    c = get_scoped("cases", caseId, "student_account_id", id,
                   "collections case")
    if c["status"] not in ("OPEN", "PAYMENT_PROMISED"):
        raise err_invalid_state(
            "Only a non-terminal case can receive write-off approval.")
    data = body()
    amount = req_int(data, "approved_writeoff_cents")
    if amount < 0:
        raise err_invalid_request("approved_writeoff_cents must be at least 0.")
    c["approved_writeoff_cents"] = amount
    touch(c)
    return ok(envelope_obj(ser_case(c)))


@bp.post("/student-accounts/<id>/collections-cases/<caseId>/write-off")
def write_off(id, caseId):
    uid, _role = auth(BK)
    account = get_or_404("accounts", id, "student account")
    c = get_scoped("cases", caseId, "student_account_id", id,
                   "collections case")
    if c["status"] not in ("OPEN", "PAYMENT_PROMISED"):
        raise err_invalid_state(
            "Only an OPEN or PAYMENT_PROMISED case can be written off.")
    data = body()
    amount = req_int(data, "amount_cents")
    if amount <= 0:
        raise err_invalid_request("amount_cents must be greater than zero.")
    year = db.years.get(account["school_year_id"])
    # rung 20: aging gate
    if case_bucket(c, year) != "BUCKET_3":
        raise ApiError("ERR_CASE_NOT_AGED", 409,
                       "The case has not aged to BUCKET_3.")
    # rung 21: governance — above the bookkeeper limit requires co-approval
    if amount > year["writeoff_max_cents"] and \
            c["approved_writeoff_cents"] < amount:
        raise ApiError("ERR_WRITEOFF_NEEDS_APPROVAL", 403,
                       "The write-off exceeds the bookkeeper limit without "
                       "Superintendent approval coverage.")
    # rung 22: segregation of duties vs most recent SUCCEEDED payment recorder
    succeeded = [p for p in db.payments.values()
                 if p["student_account_id"] == id and p["status"] == "SUCCEEDED"]
    if succeeded:
        succeeded.sort(key=lambda p: (p["created_at"], p["_seq"]))
        last = succeeded[-1]
        if last.get("_settled_by") is not None and last["_settled_by"] == uid:
            raise ApiError("ERR_WRITEOFF_SOD", 403,
                           "The write-off actor recorded the most recent "
                           "SUCCEEDED payment on the account.")
    # --- execute ---
    c["written_off_cents"] = amount
    c["status"] = "WRITTEN_OFF"
    touch(c)
    # prorate the write-off across departments by share of the account's
    # outstanding; floor per department; leftover cent(s) to the department
    # whose ledger entry for this account has the earliest created_at
    weights = {}
    for a in db.assessments.values():
        if a["student_account_id"] != id:
            continue
        if a["status"] in ("ASSESSED", "PARTIALLY_PAID", "PAYMENT_PLAN",
                           "DELINQUENT"):
            o = assessment_outstanding(a)
            if o > 0:
                weights[a["department_id"]] = \
                    weights.get(a["department_id"], 0) + o
    total_weight = sum(weights.values())
    if total_weight > 0:
        shares = {d: (amount * w) // total_weight for d, w in weights.items()}
        leftover = amount - sum(shares.values())
        if leftover:
            candidates = sorted(
                weights.keys(),
                key=lambda d: _earliest_entry_key(id, d))
            shares[candidates[0]] += leftover
        for d, share in shares.items():
            if share != 0:
                write_ledger(id, d, "WRITE_OFF_DEBIT", -share,
                             source_payment_id=None)
    # assessments still DELINQUENT or ASSESSED under the case -> VOID
    for a in db.assessments.values():
        if a["student_account_id"] == id and \
                a["status"] in ("DELINQUENT", "ASSESSED"):
            a["status"] = "VOID"
            touch(a)
    recompute_account(account)
    bump_dirty_departments()
    return ok(envelope_obj(ser_case(c)))


def _earliest_entry_key(account_id, dept_id):
    """Sort key: earliest ledger entry of (account, dept); departments with no
    entries sort last, by department creation order."""
    entries = [e for e in db.ledger.values()
               if e["student_account_id"] == account_id
               and e["department_id"] == dept_id]
    if entries:
        e = min(entries, key=lambda x: (x["created_at"], x["_seq"]))
        return (0, e["created_at"], e["_seq"])
    dept = db.departments.get(dept_id)
    return (1, dept["created_at"] if dept else "", dept["_seq"] if dept else 0)
