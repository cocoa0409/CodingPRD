"""Record lifecycle, serialization, pagination, and cascade helpers."""
from flask import request

from db import db, next_insertion_seq
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_LITIGATION_HOLD,
    ERR_REFERENCED_NOT_FOUND, ERR_CAPACITY_EXCEEDED,
)
from response import success_list
from util import CLOCK, fmt_dt, fmt_dt_ms, new_id
from services import calculations as calc


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------

def new_record():
    """Common fields (PRD §2.4): id, created_at, updated_at (ms precision),
    version starting at 1."""
    now = CLOCK.now()
    return {
        "id": new_id(),
        "created_at": fmt_dt_ms(now),
        "updated_at": fmt_dt_ms(now),
        "version": 1,
        "_created_dt": now,
        "_updated_dt": now,
        "_seq": next_insertion_seq(),
    }


def touch(rec):
    """Every mutation refreshes updated_at and increments version by 1."""
    now = CLOCK.now()
    rec["updated_at"] = fmt_dt_ms(now)
    rec["_updated_dt"] = now
    rec["version"] += 1


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Lookup helpers (validation priorities 4 and 5)
# ---------------------------------------------------------------------------

def require_path(collection, rid):
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"{collection[:-1]} {rid} not found")
    return rec


def require_ref(collection, rid, field):
    """Body-referenced foreign keys must resolve (priority 5)."""
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(ERR_REFERENCED_NOT_FOUND,
                    f"referenced {field} {rid} does not exist")
    return rec


def check_capacity_available(inv):
    """Capacity screen (priority 14): the live count must be strictly below
    max_active_cases at assignment."""
    if not compute_active_case_count(inv["id"]) < inv["max_active_cases"]:
        raise_error(ERR_CAPACITY_EXCEEDED,
                    "investigator is at their active-case capacity")


def check_case_not_held(case):
    """Litigation-hold freeze (PRD §2.7, priority 7)."""
    if case["litigation_hold"]:
        raise_error(ERR_LITIGATION_HOLD,
                    f"case {case['id']} is under litigation hold")


# ---------------------------------------------------------------------------
# Pagination + listing (PRD §2.3)
# ---------------------------------------------------------------------------

def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def get_bool_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    raise_error(ERR_INVALID_REQUEST, f"{name} must be true or false")


def list_response(records, serializer):
    items = sorted(records, key=lambda r: (r["_created_dt"], r["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Serializers (exact scaffold field sets; computed fields resolved here)
# ---------------------------------------------------------------------------

def serialize_employee(e):
    return public(e)


def serialize_investigator(inv):
    out = public(inv)
    # Derived live count (PRD §3.1): cases assigned to this investigator whose
    # status is TRIAGE/ASSIGNED/INVESTIGATING/FINDINGS_DRAFT/CALIBRATION/
    # PENDING_CLOSURE. ON_HOLD, REOPENED, and CLOSED cases do not count.
    out["active_case_count"] = compute_active_case_count(inv["id"])
    return out


ACTIVE_CASE_STATUSES = frozenset({
    "TRIAGE", "ASSIGNED", "INVESTIGATING", "FINDINGS_DRAFT", "CALIBRATION",
    "PENDING_CLOSURE",
})


def compute_active_case_count(investigator_id) -> int:
    return sum(
        1 for c in db["cases"].values()
        if c.get("assigned_investigator_id") == investigator_id
        and c["status"] in ACTIVE_CASE_STATUSES
    )


def serialize_channel(ch):
    return public(ch)


def serialize_holiday(h):
    # HolidayCalendarEntry carries only id and created_at (no updated_at/version).
    return public(h)


def serialize_case(c):
    out = public(c)
    out["overdue_business_days"] = calc.overdue_days_for(c)
    # reopen_count is the case's own stored counter (PRD §3.6: "a case whose
    # reopen_count has already reached two"); it increments by one per reopen
    # of this case.
    return out


def serialize_interview(iv):
    return public(iv)


def serialize_evidence(ev):
    return public(ev)


def serialize_assessment(a):
    return public(a)


def serialize_finding(f):
    return public(f)


def serialize_action(a):
    return public(a)


def serialize_notice(n):
    return public(n)


def serialize_snapshot(s):
    return public(s)


def serialize_package(p):
    return public(p)


# ---------------------------------------------------------------------------
# Collection queries
# ---------------------------------------------------------------------------

def interviews_of(case_id):
    return [iv for iv in db["interviews"].values() if iv["case_id"] == case_id]


def evidence_of(case_id):
    return [ev for ev in db["evidence_items"].values() if ev["case_id"] == case_id]


def assessments_of(case_id):
    return [a for a in db["credibility_assessments"].values()
            if a["case_id"] == case_id]


def findings_of(case_id):
    return calc.findings_of(case_id)


def actions_of(finding_id):
    return calc.actions_of(finding_id)


def notices_of(case_id):
    return [n for n in db["closure_notices"].values() if n["case_id"] == case_id]


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def bump_investigator_count(investigator_id, delta):
    """Kept for call-site compatibility; active_case_count is derived live
    (compute_active_case_count), so no stored counter needs mutation."""
    return


def mark_snapshots_stale_for_case(case):
    """Bubble-up invalidation: any snapshot whose scope matches the case's
    subject (manager chain or location) and whose as_of is not later than the
    event is marked stale (PRD §3.7)."""
    subject = db["employees"].get(case["subject_employee_id"])
    if subject is None:
        return
    now = CLOCK.now()
    for snap in db["trend_snapshots"].values():
        if snap["_as_of_dt"] > now:
            continue
        if calc.employee_in_scope(subject, snap["scope_type"], snap["scope_key"]):
            if not snap["is_stale"]:
                snap["is_stale"] = True
                touch(snap)


def touch_case_manifest(case_id):
    """While a package is ASSEMBLING, package_version increments whenever the
    manifest membership changes (PRD §3.8)."""
    member_ids, _lines = calc.compute_manifest(case_id)
    for pkg in db["litigation_packages"].values():
        if pkg["case_id"] != case_id or pkg["status"] != "ASSEMBLING":
            continue
        if pkg.get("_member_ids") != member_ids:
            pkg["_member_ids"] = member_ids
            pkg["item_count"] = len(member_ids)
            pkg["package_version"] += 1
            touch(pkg)


def recompute_assessment_scores(assessment):
    sc, sr = calc.credibility_scores(assessment["corroboration_count"],
                                     assessment["contradiction_count"],
                                     assessment["account_age_days"])
    assessment["score_corroboration"] = sc
    assessment["score_recency"] = sr
