"""Core infrastructure: logical clock, in-memory store, envelope, errors, auth,
and shared domain engine (recompute, waiver stacking, waterfall, proration, aging)."""
import re
import uuid
from datetime import datetime, date, timedelta, timezone

from flask import request

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _clock


def clock_set(dt):
    global _clock
    _clock = dt


def clock_date():
    return _clock.date()


def parse_datetime(s):
    """Parse an ISO-8601 instant; returns aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    try:
        if txt.endswith("Z"):
            dt = datetime.fromisoformat(txt[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s.strip()[:10])
    except ValueError:
        return None


def fmt_ts(dt):
    """ISO-8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    return d.isoformat() if isinstance(d, date) else d


# ---------------------------------------------------------------------------
# In-memory store (dicts keyed by id). Starts EMPTY; nothing is seeded.
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.years = {}
        self.students = {}
        self.accounts = {}
        self.departments = {}
        self.offerings = {}
        self.fee_items = {}
        self.purchase_items = {}
        self.enrollments = {}
        self.assessments = {}
        self.purchases = {}
        self.programs = {}
        self.applications = {}
        self.payments = {}
        self.allocations = {}
        self.plans = {}
        self.installments = {}
        self.refunds = {}
        self.ledger = {}
        self.runs = {}
        self.cases = {}
        self.seq = 0  # global monotonic insertion sequence (stable tiebreak)

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()

COMMON = ("id", "created_at", "updated_at", "version")


def new_entity(kind, fields):
    """Create and register an entity dict with system common fields."""
    now = fmt_ts(clock_now())
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "_created_dt": clock_now(),
    }
    ent.update(fields)
    getattr(db, kind)[ent["id"]] = ent
    return ent


def new_ledger_row(fields):
    """LedgerEntry / PaymentAllocation: only id + created_at (immutable rows)."""
    row = {
        "id": str(uuid.uuid4()),
        "created_at": fmt_ts(clock_now()),
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


def touch(ent):
    """System mutation: refresh updated_at and increment version."""
    ent["updated_at"] = fmt_ts(clock_now())
    ent["version"] += 1


def pub(ent, fields):
    """Serialize entity: whitelisted fields in declared order."""
    return {k: ent.get(k) for k in fields}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err_not_found(what="resource"):
    return ApiError("ERR_NOT_FOUND", 404, f"The requested {what} does not exist.")


def err_ref_not_found(what="referenced resource"):
    return ApiError("ERR_REFERENCED_NOT_FOUND", 404,
                    f"The referenced {what} does not exist in this scope.")


def err_invalid_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Resource is not in the required state for this operation."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def meta_base():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(clock_now()),
    }


def envelope_obj(data):
    return {"meta": meta_base(), "response_type": "object", "data": data}


def envelope_list(items, limit, offset, total):
    meta = meta_base()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    })
    return {"meta": meta, "response_type": "array", "data": items}


def envelope_error(error_id, message):
    return {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


def pagination():
    """Read limit/offset query params with defaults; clamp to spec bounds."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(rows, serializer):
    """rows pre-sorted by (created_at, seq); returns flask-ready envelope."""
    rows = sorted(rows, key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return envelope_list([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Auth (ladder rungs 1-2)
# ---------------------------------------------------------------------------

ROLES = ("Bookkeeper", "FamilyMember", "Superintendent")
ANY_ROLE = ROLES


def auth(allowed):
    """Validate user context headers and endpoint role permission."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip() \
            or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID and X-User-Role headers are missing or malformed.")
    if role not in allowed:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                       "The declared role is not permitted on this endpoint.")
    return uid, role


def body():
    """JSON request body (must be an object); empty body -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object.")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise err_invalid_request(f"Missing required field: {name}")
    return data[name]


def req_int(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field {name} must be an integer.")
    return v


def opt_int(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field {name} must be an integer.")
    return v


def req_enum(data, name, values):
    v = req_field(data, name)
    if v not in values:
        raise err_invalid_request(f"Field {name} must be one of {sorted(values)}.")
    return v


def opt_bool(data, name, default):
    v = data.get(name, default)
    if not isinstance(v, bool):
        raise err_invalid_request(f"Field {name} must be a boolean.")
    return v


# ---------------------------------------------------------------------------
# Lookups with scope checks
# ---------------------------------------------------------------------------

def get_or_404(table, rid, what="resource"):
    ent = db.__dict__[table].get(rid) if isinstance(table, str) else table.get(rid)
    if ent is None:
        raise err_not_found(what)
    return ent


def get_scoped(table, rid, parent_key, parent_id, what="resource"):
    ent = get_or_404(table, rid, what)
    if ent.get(parent_key) != parent_id:
        raise err_not_found(what)
    return ent


def year_of_account(account):
    return db.years.get(account["school_year_id"])


def require_year_open(year):
    if year["status"] != "OPEN":
        raise ApiError("ERR_YEAR_NOT_OPEN", 409,
                       "The school year is not OPEN for this write.")


# ---------------------------------------------------------------------------
# Domain engine
# ---------------------------------------------------------------------------

def observe_offering(off):
    """Lazy SCHEDULED -> IN_SESSION when the logical date reaches start_date."""
    if off["status"] == "SCHEDULED" and clock_date() >= off["_start"]:
        off["status"] = "IN_SESSION"
        touch(off)


def observe_account(account):
    """Lazy flips on account read: SCHEDULED->DUE installments, posture."""
    for plan in db.plans.values():
        if plan["student_account_id"] != account["id"] or plan["status"] != "ACTIVE":
            continue
        for inst in db.installments.values():
            if inst["payment_plan_id"] == plan["id"] and inst["status"] == "SCHEDULED" \
                    and clock_date() >= inst["_due"]:
                inst["status"] = "DUE"
                touch(inst)
    recompute_account(account, bump=False)


def recompute_account(account, bump=True):
    """Recompute aggregates + posture. bump=True records a mutation."""
    acct_id = account["id"]
    assessed = 0
    waived = 0
    for a in db.assessments.values():
        if a["student_account_id"] != acct_id:
            continue
        st = a["status"]
        if st == "VOID":
            continue
        if st in ("ASSESSED", "PARTIALLY_PAID", "PAID", "PAYMENT_PLAN",
                  "DELINQUENT", "WAIVED"):
            assessed += a["assessed_amount_cents"]
        elif st == "REFUNDED":
            assessed += a["allocated_cents"]  # retained portion only
        waived += a["waived_amount_cents"]
    paid = 0
    for p in db.payments.values():
        if p["student_account_id"] == acct_id and p["status"] == "SUCCEEDED":
            paid += p["amount_cents"]
    for r in db.refunds.values():
        if r["student_account_id"] == acct_id and r["status"] == "EXECUTED" \
                and r.get("purchase_id") is None:
            # purchase-sourced refunds never touch fee-ledger balance math
            paid -= r["refund_cents"]
    balance = assessed - waived - paid

    # posture (priority: WRITTEN_OFF > COLLECTIONS > GRADUATION_HOLD > CLEAR)
    posture = "CLEAR"
    has_open_case = False
    has_written_off = False
    for c in db.cases.values():
        if c["student_account_id"] != acct_id:
            continue
        if c["status"] == "WRITTEN_OFF":
            has_written_off = True
        elif c["status"] in ("OPEN", "PAYMENT_PROMISED"):
            has_open_case = True
    if has_written_off:
        posture = "WRITTEN_OFF"
    elif has_open_case:
        posture = "COLLECTIONS"
    else:
        year = year_of_account(account)
        threshold = year["graduation_hold_threshold_cents"] if year else 0
        if balance > 0 and balance > threshold:
            posture = "GRADUATION_HOLD"

    account["assessed_cents"] = assessed
    account["waived_cents"] = waived
    account["paid_cents"] = paid
    account["balance_cents"] = balance
    account["posture"] = posture
    account["last_posture_check_at"] = fmt_ts(clock_now())
    if bump:
        touch(account)


def family_balance(account):
    """Sum of balance_cents over accounts of students sharing family_id whose
    school year is OPEN. Computed live (identical for every sibling)."""
    student = db.students.get(account["student_id"])
    if student is None:
        return account["balance_cents"]
    total = 0
    for other in db.accounts.values():
        o_student = db.students.get(other["student_id"])
        if o_student is None or o_student["family_id"] != student["family_id"]:
            continue
        year = db.years.get(other["school_year_id"])
        if year is None or year["status"] != "OPEN":
            continue
        total += other["balance_cents"]
    return total


def case_bucket(case, year):
    """Live-computed aging bucket: whole-day floor of (clock - opened_at)."""
    age = (clock_now() - case["_opened_dt"]).days
    k = year["aging_interval_days"]
    if age < k:
        return "CURRENT"
    if age < 2 * k:
        return "BUCKET_1"
    if age < 3 * k:
        return "BUCKET_2"
    return "BUCKET_3"


def open_or_advance_case(account):
    """Open a collections case for the account (or advance existing bucket).
    Returns the case and whether it was newly opened."""
    for c in db.cases.values():
        if c["student_account_id"] == account["id"] and c["status"] in ("OPEN", "PAYMENT_PROMISED"):
            return c, False
    recompute_account(account, bump=False)
    case = new_entity("cases", {
        "student_account_id": account["id"],
        "opened_at": fmt_ts(clock_now()),
        "principal_cents": account["balance_cents"],
        "written_off_cents": 0,
        "approved_writeoff_cents": 0,
        "status": "OPEN",
        "_opened_dt": clock_now(),
        "_promised_at": None,
    })
    return case, True


def assessment_outstanding(a):
    return a["assessed_amount_cents"] - a["waived_amount_cents"] - a["allocated_cents"]


# ---------------------------------------------------------------------------
# Waiver stacking (floor-then-cap; per-student cap consumed earliest-created-first)
# ---------------------------------------------------------------------------

def sorted_approved_programs(account):
    progs = {}
    for app in db.applications.values():
        if app["student_account_id"] == account["id"] and app["status"] == "APPROVED":
            progs[app["waiver_program_id"]] = db.programs.get(app["waiver_program_id"])
    result = [p for p in progs.values() if p is not None]
    result.sort(key=lambda p: (p["stacking_priority"], p["created_at"], p["_seq"]))
    return result


def run_stacking(account, only_assessment=None):
    """Recompute waiver application across the account's assessments.

    Visits assessments in created_at order; earlier ones consume each program's
    per-student cap first. Each program's tentative waiver on an assessment is
    floor(remaining_base * pct_bp / 10000) computed BEFORE the cap is applied
    (pinned floor-then-cap order). On final runs (only_assessment=None) every
    program's contribution is recomputed from scratch; on provisional runs only
    the newly created assessment is computed (earlier ones unchanged)."""
    programs = sorted_approved_programs(account)
    assessments = [a for a in db.assessments.values()
                   if a["student_account_id"] == account["id"] and a["status"] != "VOID"]
    assessments.sort(key=lambda a: (a["created_at"], a["_seq"]))

    cap_used = {p["id"]: 0 for p in programs}
    for a in assessments:
        if "_waiver_by_program" not in a:
            a["_waiver_by_program"] = {}
        if only_assessment is not None and a["id"] != only_assessment:
            # frozen row: consumes cap with its recorded per-program amounts
            for pid, cents in a["_waiver_by_program"].items():
                if pid in cap_used:
                    cap_used[pid] += cents
            continue
        if a["status"] not in ("ASSESSED", "PARTIALLY_PAID", "WAIVED"):
            for pid, cents in a["_waiver_by_program"].items():
                if pid in cap_used:
                    cap_used[pid] += cents
            continue
        item = db.fee_items.get(a["fee_item_id"])
        if item is None or not item.get("waiverable", True):
            a["_waiver_by_program"] = {}
            if a["waived_amount_cents"]:
                a["waived_amount_cents"] = 0
                touch(a)
            continue
        base = a["assessed_amount_cents"] - a["allocated_cents"]
        remaining_base = base
        new_breakdown = {}
        for p in programs:
            remaining_cap = p["max_waived_per_student_cents"] - cap_used[p["id"]]
            w = (remaining_base * p["waiver_pct_bp"]) // 10000  # floor FIRST
            w = min(w, remaining_cap, remaining_base)           # cap SECOND
            if w > 0:
                new_breakdown[p["id"]] = w
                cap_used[p["id"]] += w
                remaining_base -= w
        new_waived = base - remaining_base
        if new_waived != a["waived_amount_cents"] or \
                new_breakdown != a["_waiver_by_program"]:
            a["waived_amount_cents"] = new_waived
            a["_waiver_by_program"] = new_breakdown
            # status transitions on coverage change
            if a["status"] in ("ASSESSED", "PARTIALLY_PAID"):
                if a["status"] == "ASSESSED" and a["allocated_cents"] == 0 \
                        and new_waived == a["assessed_amount_cents"] \
                        and new_waived > 0:
                    a["status"] = "WAIVED"
            elif a["status"] == "WAIVED":
                if new_waived < a["assessed_amount_cents"]:
                    a["status"] = "PARTIALLY_PAID" if a["allocated_cents"] > 0 \
                        else "ASSESSED"
            touch(a)


# ---------------------------------------------------------------------------
# Refund proration
# ---------------------------------------------------------------------------

def proration_refund_cents(year, offering, assessment, force_full=False):
    """Compute refund per tier rules. Collected cents only; waived never refunded.
    force_full models a SCHEDULED offering cancellation (days_elapsed := 0)."""
    item = db.fee_items.get(assessment["fee_item_id"])
    collected = assessment["allocated_cents"]
    if item is not None and not item.get("refundable", True):
        return 0
    if force_full:
        days = 0
    else:
        days = (clock_date() - offering["_start"]).days
    if days <= year["refund_full_days"]:
        return collected
    if days <= year["refund_partial_days"]:
        return (collected * year["partial_refund_pct_bp"]) // 10000  # floor
    return 0


def spawn_refund(account, reason, refund_cents, fee_assessment_id=None, purchase_id=None):
    return new_entity("refunds", {
        "student_account_id": account["id"],
        "fee_assessment_id": fee_assessment_id,
        "purchase_id": purchase_id,
        "reason": reason,
        "refund_cents": refund_cents,
        "status": "PENDING",
    })


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------

def write_ledger(account_id, department_id, entry_type, amount_cents,
                 source_payment_id=None):
    row = new_ledger_row({
        "student_account_id": account_id,
        "department_id": department_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "source_payment_id": source_payment_id,
        "reconciliation_run_id": None,
    })
    db.ledger[row["id"]] = row
    dept = db.departments.get(department_id)
    if dept is not None:
        dept["_dirty"] = True  # counter mutation -> version bump at op end
    return row


def dept_distributed(dept_id):
    total = 0
    for e in db.ledger.values():
        if e["department_id"] == dept_id:
            total += e["amount_cents"]
    return total


def bump_dirty_departments():
    for d in db.departments.values():
        if d.pop("_dirty", False):
            touch(d)


# ---------------------------------------------------------------------------
# Allocation waterfall
# ---------------------------------------------------------------------------

def half_up(num, den):
    """Round num/den to nearest integer, halves away from zero (num,den >= 0)."""
    q, r = divmod(num, den)
    if 2 * r >= den:
        q += 1
    return q


def settle_waterfall(account, payment):
    """Run stage-1 (installments) and stage-2 (oldest outstanding) allocation.
    Assumes REJECT pre-check already passed. Returns None."""
    remaining = payment["amount_cents"]

    # ---- Stage 1: installment due ----
    plan = None
    for p in db.plans.values():
        if p["student_account_id"] == account["id"] and p["status"] == "ACTIVE":
            plan = p
            break
    if plan is not None:
        covered = [(db.assessments[cid], w) for cid, w in plan["_covered"]]
        covered = [(a, w) for a, w in covered if a is not None]
        total_weight = sum(w for _, w in covered)
        insts = [i for i in db.installments.values()
                 if i["payment_plan_id"] == plan["id"]]
        insts.sort(key=lambda i: (i["_due"], i["sequence"]))
        for inst in insts:
            if remaining <= 0:
                break
            shortfall = inst["amount_cents"] - inst["paid_cents"]
            if shortfall <= 0:
                continue
            take = min(remaining, shortfall)
            if take > 0 and total_weight > 0 and covered:
                shares = []
                for a, w in covered:
                    shares.append(half_up(take * w, total_weight))
                residual = take - sum(shares)
                if residual != 0:
                    # residual cent(s) to earliest-created covered assessment
                    ear = min(range(len(covered)),
                              key=lambda i: (covered[i][0]["created_at"],
                                             covered[i][0]["_seq"]))
                    shares[ear] += residual
                for (a, _), share in zip(covered, shares):
                    if share <= 0:
                        continue
                    _allocate(account, payment, a, share, "INSTALLMENT_DUE")
            inst["paid_cents"] += take
            if inst["paid_cents"] >= inst["amount_cents"] and \
                    inst["status"] in ("SCHEDULED", "DUE", "PAST_DUE"):
                inst["status"] = "PAID"
            touch(inst)
            remaining -= take
        # plan completion
        if all(i["status"] == "PAID" for i in insts) and plan["status"] == "ACTIVE":
            plan["status"] = "COMPLETED"
            touch(plan)
            for a, _ in covered:
                if a["status"] == "PAYMENT_PLAN":
                    a["status"] = "PAID"
                    a["payment_plan_id"] = None
                    touch(a)

    # ---- Stage 2: oldest outstanding ----
    if remaining > 0:
        eligible = [a for a in db.assessments.values()
                    if a["student_account_id"] == account["id"]
                    and a["status"] in ("ASSESSED", "PARTIALLY_PAID", "DELINQUENT")
                    and assessment_outstanding(a) > 0]
        eligible.sort(key=lambda a: (a["created_at"], -a["assessed_amount_cents"],
                                     a["_seq"]))
        for a in eligible:
            if remaining <= 0:
                break
            take = min(remaining, assessment_outstanding(a))
            if take <= 0:
                continue
            _allocate(account, payment, a, take, "OLDEST_OUTSTANDING")
            remaining -= take

    # ---- Stage 3: overpayment stays unallocated under CREDIT_BALANCE ----
    return remaining


def _allocate(account, payment, assessment, cents, rule):
    row = new_ledger_row({
        "payment_id": payment["id"],
        "fee_assessment_id": assessment["id"],
        "allocated_cents": cents,
        "allocation_rule": rule,
    })
    db.allocations[row["id"]] = row
    payment["allocated_cents"] = payment.get("allocated_cents", 0) + cents
    assessment["allocated_cents"] += cents
    # status transition per coverage
    if assessment["allocated_cents"] + assessment["waived_amount_cents"] >= \
            assessment["assessed_amount_cents"]:
        assessment["status"] = "PAID"
        if assessment.get("payment_plan_id"):
            assessment["payment_plan_id"] = None
    elif assessment["status"] in ("ASSESSED", "DELINQUENT"):
        assessment["status"] = "PARTIALLY_PAID"
    touch(assessment)
    write_ledger(account["id"], assessment["department_id"],
                 "DISTRIBUTION_CREDIT", cents, source_payment_id=payment["id"])


def allocatable_ceiling(account):
    """Stage-1 installment capacity + stage-2 outstanding (REJECT pre-check)."""
    cap = 0
    for p in db.plans.values():
        if p["student_account_id"] == account["id"] and p["status"] == "ACTIVE":
            for i in db.installments.values():
                if i["payment_plan_id"] == p["id"]:
                    shortfall = i["amount_cents"] - i["paid_cents"]
                    if shortfall > 0 and i["status"] in ("SCHEDULED", "DUE", "PAST_DUE"):
                        cap += shortfall
    for a in db.assessments.values():
        if a["student_account_id"] == account["id"] and \
                a["status"] in ("ASSESSED", "PARTIALLY_PAID", "DELINQUENT"):
            o = assessment_outstanding(a)
            if o > 0:
                cap += o
    return cap
