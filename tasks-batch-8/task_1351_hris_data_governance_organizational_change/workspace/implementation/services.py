"""Business machinery: intervals, DQ, hierarchy, apply/void, batches, sweeps."""
import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError
from store import db
from util import clock_date, new_entity

GOVERNABLE_KEYS = {
    "assignment.position_id", "assignment.salary_cents", "assignment.pay_grade",
    "assignment.location_code", "position.parent_position_id", "position.title",
    "position.department",
}
GOV_ATTR = {
    "assignment.position_id": "position_id",
    "assignment.salary_cents": "salary_cents",
    "assignment.pay_grade": "pay_grade",
    "assignment.location_code": "location_code",
}
CHANNELS = {"PAYROLL", "BENEFITS", "IDENTITY"}
SOD_PAIRS = {("HRIS_ANALYST", "CHANGE_APPROVER"), ("DATA_STEWARD", "CHANGE_APPROVER")}
MAX_RETRY = 3
SENSITIVE = ("CONFIDENTIAL", "RESTRICTED")
PCT_RE = re.compile(r"^\+(\d+(?:\.\d+)?)%$")


def bump(e):
    e["updated_at"] = db.clock
    e["version"] += 1


def get_or_404(coll, oid, error_id):
    e = coll.get(oid)
    if e is None:
        raise ApiError(error_id, 404, "Resource not found: %s" % oid)
    return e


# ---------------------------------------------------------------- audit/events
def audit(actor, action, worker_id=None, field_id=None, change_request_id=None,
          batch_id=None, old_value=None, new_value=None):
    a = {"id": None, "_seq": next(db.seq), "created_at": db.clock,
         "actor_id": actor, "action": action, "worker_id": worker_id,
         "field_id": field_id, "change_request_id": change_request_id,
         "batch_id": batch_id, "old_value": old_value, "new_value": new_value}
    from util import new_id
    a["id"] = new_id()
    db.audit_entries[a["id"]] = a
    return a


def emit_event(event_type, channel, worker_id, change_request_id=None, batch_id=None):
    e = new_entity(db.events)
    e.update({"event_type": event_type, "channel": channel, "worker_id": worker_id,
              "change_request_id": change_request_id, "batch_id": batch_id,
              "status": "QUEUED", "retry_count": 0, "resolution_note": None})
    db.events[e["id"]] = e
    return e


# ------------------------------------------------------------- priority score
def compute_priority(exc):
    rule = db.dq_rules.get(exc["rule_id"]) if exc["rule_id"] else None
    if rule is None:
        base = 300  # dead-letter-originated
    else:
        base = 100 if rule["severity"] == "WARNING" else 300
    field = db.data_fields.get(exc["field_id"]) if exc["field_id"] else None
    mult = 1
    if field is not None:
        mult = {"PUBLIC": 1, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3}[field["sensitivity"]]
    age_days = (clock_date() - exc["created_at"].date()).days
    if age_days < 7:
        bonus = 0
    elif age_days < 30:
        bonus = 50
    else:
        bonus = 150
    return min(1000, base * mult + bonus)


def open_exception(rule_id, change_request_id, batch_id, integration_event_id,
                   worker_id, field_id, observed_value):
    x = new_entity(db.exceptions)
    x.update({"rule_id": rule_id, "change_request_id": change_request_id,
              "batch_id": batch_id, "integration_event_id": integration_event_id,
              "worker_id": worker_id, "field_id": field_id,
              "observed_value": observed_value, "status": "OPEN",
              "priority_score": 0, "waiver_expiry_date": None,
              "resolution_note": None})
    x["priority_score"] = compute_priority(x)
    db.exceptions[x["id"]] = x
    return x


# ------------------------------------------------------------------ intervals
def derive_row_status(start, end, cdate):
    if end is not None and cdate >= end:
        return "HISTORY"
    if cdate < start:
        return "FUTURE"
    return "ACTIVE"


def row_covers(row, d):
    """Half-open [start, end); null end counts as +infinity."""
    return row["effective_start_date"] <= d and (
        row["effective_end_date"] is None or d < row["effective_end_date"])


def live_rows(worker_id):
    return [r for r in db.assignments.values()
            if r["worker_id"] == worker_id and r["row_status"] != "VOIDED"]


def make_row(worker_id, change_request_id, position_id, salary_cents, pay_grade,
             location_code, start, end):
    r = new_entity(db.assignments)
    r.update({"worker_id": worker_id, "change_request_id": change_request_id,
              "position_id": position_id, "salary_cents": salary_cents,
              "pay_grade": pay_grade, "location_code": location_code,
              "effective_start_date": start, "effective_end_date": end,
              "row_status": derive_row_status(start, end, clock_date())})
    db.assignments[r["id"]] = r
    return r


def place_row(worker, D):
    """§2.6 effective-interval placement. Returns (baseline, new_end,
    truncated_row, truncated_old_end). Raises overlap / no-baseline errors."""
    rows = live_rows(worker["id"])
    for r in rows:
        if r["effective_start_date"] == D:
            raise ApiError("ERR_EFFECTIVE_PERIOD_OVERLAP", 409,
                           "An existing assignment row starts on the effective date")
    covering = None
    for r in rows:
        if r["effective_start_date"] < D and (
                r["effective_end_date"] is None or D < r["effective_end_date"]):
            covering = r
            break
    if covering is not None:
        old_end = covering["effective_end_date"]
        covering["effective_end_date"] = D
        bump(covering)
        return covering, old_end, covering, old_end
    earlier = [r for r in rows if r["effective_start_date"] < D]
    if not earlier:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "No baseline assignment row before the effective date")
    earlier.sort(key=lambda r: (r["effective_start_date"], r["_seq"]))
    baseline = earlier[-1]
    later = [r["effective_start_date"] for r in rows if r["effective_start_date"] > D]
    return baseline, (min(later) if later else None), None, None


# ------------------------------------------------------------------- DQ rules
def rule_passes(rule, value):
    t = rule["rule_type"]
    if t == "REQUIRED":
        return value is not None and str(value) != ""
    if t == "RANGE":
        try:
            iv = int(str(value).strip())
        except (TypeError, ValueError):
            return False
        if rule["param_min"] is not None and iv < rule["param_min"]:
            return False
        if rule["param_max"] is not None and iv > rule["param_max"]:
            return False
        return True
    if t == "REGEX":
        try:
            return re.search(rule["param_pattern"] or "", str(value)) is not None
        except re.error:
            return True
    return True


def dq_screen(field, value_str):
    """Returns (critical_failed, [warning rules failed]). DISABLED skipped."""
    critical = False
    warnings = []
    rules = [r for r in db.dq_rules.values()
             if r["target_field_id"] == field["id"] and r["status"] == "ACTIVE"]
    rules.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for r in rules:
        if rule_passes(r, value_str):
            continue
        if r["severity"] == "CRITICAL":
            critical = True
        else:
            warnings.append(r)
    return critical, warnings


# ------------------------------------------------------------------ hierarchy
def position_depth(pos):
    """Levels from root; a root has depth 1."""
    d = 1
    p = pos
    seen = set()
    while p["parent_position_id"]:
        if p["id"] in seen:
            break
        seen.add(p["id"])
        parent = db.positions.get(p["parent_position_id"])
        if parent is None:
            break
        p = parent
        d += 1
    return d


def children_map():
    m = {}
    for p in db.positions.values():
        if p["parent_position_id"]:
            m.setdefault(p["parent_position_id"], []).append(p["id"])
    return m


def subtree_ids(position_id):
    cm = children_map()
    out = set()
    stack = [position_id]
    while stack:
        pid = stack.pop()
        if pid in out:
            continue
        out.add(pid)
        stack.extend(cm.get(pid, []))
    return out


def subtree_height(position_id):
    cm = children_map()
    def h(pid):
        kids = cm.get(pid, [])
        if not kids:
            return 1
        return 1 + max(h(k) for k in kids)
    return h(position_id)


def creates_cycle(position, new_parent):
    """new parent may not be the position itself or any of its descendants."""
    if new_parent["id"] == position["id"]:
        return True
    return new_parent["id"] in subtree_ids(position["id"])


def subtree_headcount(position_id, mode):
    ids = subtree_ids(position_id)
    if mode == "FILLED_ONLY":
        workers = set()
        for r in db.assignments.values():
            if r["row_status"] == "ACTIVE" and r["position_id"] in ids:
                workers.add(r["worker_id"])
        return len(workers)
    # BUDGETED_CAPACITY: ACTIVE positions only; CLOSED contribute 0
    return sum(p["headcount_budget"] for p in db.positions.values()
               if p["id"] in ids and p["status"] == "ACTIVE")


# -------------------------------------------------------------- value parsing
def parse_gov_value(field, raw):
    if field["field_key"] == "assignment.salary_cents":
        return int(str(raw).strip())
    return raw


def is_salary_field(field):
    return field["field_key"] == "assignment.salary_cents"


def resolve_salary(new_value, prior):
    m = PCT_RE.match(str(new_value).strip())
    if m:
        pct = Decimal(m.group(1))
        val = Decimal(prior) * (Decimal(1) + pct / Decimal(100))
        return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return int(str(new_value).strip())


def valid_salary_literal(new_value, allow_pct):
    s = str(new_value).strip()
    if allow_pct and PCT_RE.match(s):
        return True
    return re.fullmatch(r"-?\d+", s) is not None
