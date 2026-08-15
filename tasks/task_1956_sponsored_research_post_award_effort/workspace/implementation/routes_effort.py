"""Routes: effort cycles (fan-out, close gates, fringe true-up) and statements."""
from decimal import Decimal
from flask import Blueprint, request

import serializers as sz
from db import STORES, new_id, now_clock, stamp_new, touch
from errors import err
from middleware import (Shape, auth, body, get_or_404, list_page, require_role,
                        sh_dt, sh_int, sh_pct, sh_str)
from response import ok, ok_created, ok_list
from services import charged_pct, fringe_trueup, KEY_FLOOR, VARIANCE_TOLERANCE
from util import D, rhu2

bp = Blueprint("effort", __name__)

CYCLE_STATUSES = {"SCHEDULED", "CERTIFYING", "CLOSED"}
STMT_STATUSES = {"PENDING", "CERTIFIED", "REOPENED", "RECERTIFIED"}
STMT_KINDS = {"AWARD", "NON_SPONSORED"}


# ---------------------------------------------------------------------------
# effort cycles
# ---------------------------------------------------------------------------

@bp.post("/api/effort-cycles")
def create_cycle():
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    b = body()
    sh = Shape()
    code = sh_str(b, "cycle_code", sh)
    start = sh_dt(b, "period_start", sh)
    end = sh_dt(b, "period_end", sh)
    months = sh_int(b, "cycle_months", sh, min_v=1, max_v=12)
    if start is not None and end is not None and not (end > start):
        sh.bad = True
    # structural (10): half-open window overlap; adjacency allowed
    if start is not None and end is not None:
        for c in STORES["cycles"].values():
            if start < c["period_end"] and end > c["period_start"]:
                raise err("ERR_CYCLE_PERIOD_OVERLAP", "Cycle window overlaps an existing cycle")
    if code is not None and any(c["cycle_code"] == code for c in STORES["cycles"].values()):
        raise err("ERR_DUPLICATE_CYCLE_CODE", "cycle_code already exists")
    sh.raise_if_bad()
    c = stamp_new({
        "id": new_id(), "cycle_code": code, "period_start": start, "period_end": end,
        "cycle_months": months, "actual_fringe_rate_bps": None, "status": "SCHEDULED",
    })
    STORES["cycles"][c["id"]] = c
    return ok_created(sz.cycle(c))


@bp.get("/api/effort-cycles")
def list_cycles():
    auth()
    filters = {lambda c: c["status"]: request.args.get("status")}
    items, total, limit, offset = list_page("cycles", sz.cycle, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/effort-cycles/<cid>")
def get_cycle(cid):
    auth()
    return ok(sz.cycle(get_or_404("cycles", cid, "ERR_CYCLE_NOT_FOUND")))


def _overlaps_window(a, c):
    """Award period of performance [start, end] (closed) vs cycle window [start, end) (half-open)."""
    return a["project_start_date"] < c["period_end"] and a["current_end_date"] >= c["period_start"]


@bp.post("/api/effort-cycles/<cid>/open")
def open_cycle(cid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    c = get_or_404("cycles", cid, "ERR_CYCLE_NOT_FOUND")
    if c["status"] != "SCHEDULED":
        raise err("ERR_CYCLE_NOT_CERTIFYING", "Open requires cycle status SCHEDULED")
    # temporal (9)
    if now_clock() < c["period_start"]:
        raise err("ERR_CYCLE_NOT_YET_OPENABLE", "Logical clock has not reached period_start")
    # structural (10): at most one CERTIFYING cycle
    if any(o["status"] == "CERTIFYING" for o in STORES["cycles"].values()):
        raise err("ERR_CYCLE_ALREADY_CERTIFYING", "Another EffortCycle is already CERTIFYING")
    # fan-out: one AWARD statement per commitment on overlapping awards,
    # plus exactly one NON_SPONSORED statement per person
    persons = {}
    for cm in STORES["commitments"].values():
        a = STORES["awards"].get(cm["award_id"])
        p = STORES["persons"].get(cm["person_id"])
        if a is None or p is None or not _overlaps_window(a, c):
            continue
        s = stamp_new({
            "id": new_id(), "cycle_id": c["id"], "person_id": cm["person_id"],
            "award_id": cm["award_id"], "statement_kind": "AWARD",
            "committed_effort_pct": cm["committed_effort_pct"],  # snapshot, version-pinned
            "charged_effort_pct": float(charged_pct(p, cm["award_id"], c)),
            "certified_effort_pct": None, "variance_pp": None,
            "payroll_adjustment_note": None, "key_reduction_flag": False,
            "status": "PENDING",
        })
        STORES["statements"][s["id"]] = s
        persons[cm["person_id"]] = True
    for pid in persons:
        s = stamp_new({
            "id": new_id(), "cycle_id": c["id"], "person_id": pid, "award_id": None,
            "statement_kind": "NON_SPONSORED", "committed_effort_pct": 0.0,
            "charged_effort_pct": 0.0, "certified_effort_pct": None, "variance_pp": None,
            "payroll_adjustment_note": None, "key_reduction_flag": False, "status": "PENDING",
        })
        STORES["statements"][s["id"]] = s
    c["status"] = "CERTIFYING"
    touch(c)
    return ok(sz.cycle(c))


@bp.post("/api/effort-cycles/<cid>/close")
def close_cycle(cid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    c = get_or_404("cycles", cid, "ERR_CYCLE_NOT_FOUND")
    if c["status"] != "CERTIFYING":
        raise err("ERR_CYCLE_NOT_CERTIFYING", "Close requires cycle status CERTIFYING")
    stmts = [s for s in STORES["statements"].values() if s["cycle_id"] == cid]
    # structural (10): all certified first, then per-person 100.00 totals
    if any(s["status"] not in ("CERTIFIED", "RECERTIFIED") for s in stmts):
        raise err("ERR_CYCLE_HAS_UNCERTIFIED_STATEMENTS",
                  "Every generated statement must be CERTIFIED or RECERTIFIED")
    per_person = {}
    for s in stmts:
        per_person[s["person_id"]] = per_person.get(s["person_id"], Decimal("0.00")) + D(s["certified_effort_pct"])
    for pid, total in per_person.items():
        if total != Decimal("100.00"):
            raise err("ERR_EFFORT_TOTAL_NOT_100",
                      "Certified effort for a person must total exactly 100.00 across all statements")
    b = body()
    sh = Shape()
    actual = sh_int(b, "actual_fringe_rate_bps", sh)
    sh.raise_if_bad()
    c["actual_fringe_rate_bps"] = actual
    c["status"] = "CLOSED"
    touch(c)
    fringe_trueup(c)
    return ok(sz.cycle(c))


# ---------------------------------------------------------------------------
# effort statements
# ---------------------------------------------------------------------------

@bp.get("/api/effort-statements")
def list_statements():
    auth()
    filters = {
        lambda s: s["cycle_id"]: request.args.get("cycle_id"),
        lambda s: s["person_id"]: request.args.get("person_id"),
        lambda s: s.get("award_id"): request.args.get("award_id"),
        lambda s: s["status"]: request.args.get("status"),
        lambda s: s["statement_kind"]: request.args.get("statement_kind"),
    }
    items, total, limit, offset = list_page("statements", sz.statement, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/effort-statements/<sid>")
def get_statement(sid):
    auth()
    return ok(sz.statement(get_or_404("statements", sid, "ERR_STATEMENT_NOT_FOUND")))


@bp.post("/api/effort-statements/<sid>/certify")
def certify_statement(sid):
    uid, role = auth()
    require_role(role, ["PrincipalInvestigator", "ResearchStaff"])
    s = get_or_404("statements", sid, "ERR_STATEMENT_NOT_FOUND")
    # ownership (3): entity-backed roles act only on their own statements
    if uid != s["person_id"]:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "A certifier may only certify their own statement")
    b = body()
    sh = Shape()
    certified = sh_pct(b, "certified_effort_pct", sh, lo_exclusive=None, hi_inclusive=100,
                       required=True)
    if certified is not None and certified < 0:
        sh.bad = True
        certified = None
    expected = b.get("expected_effort_statement_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        sh.bad = True
        expected = None
    note = sh_str(b, "payroll_adjustment_note", sh, required=False)
    # OCC (5): statement version match
    if expected is not None and expected != s["version"]:
        raise err("ERR_STALE_STATEMENT_VERSION",
                  "expected_effort_statement_version does not match the statement's current version")
    # state (6): certifiable only while cycle CERTIFYING from PENDING/REOPENED
    cycle = STORES["cycles"].get(s["cycle_id"])
    if cycle is None or cycle["status"] != "CERTIFYING" or s["status"] not in ("PENDING", "REOPENED"):
        raise err("ERR_STATEMENT_NOT_CERTIFIABLE",
                  "Certify requires statement PENDING/REOPENED with cycle CERTIFYING")
    # structural (10): variance note when |certified - charged| > 5.00
    if certified is not None:
        variance = rhu2(certified - D(s["charged_effort_pct"]))
        if abs(variance) > VARIANCE_TOLERANCE and (note is None or len(note) < 20):
            raise err("ERR_VARIANCE_NOTE_REQUIRED",
                      "|certified - charged| > 5.00 requires payroll_adjustment_note >= 20 chars")
    sh.raise_if_bad()
    # effects: variance, key-personnel floor, status, version bump
    s["certified_effort_pct"] = float(rhu2(certified))
    s["variance_pp"] = float(rhu2(certified - D(s["charged_effort_pct"])))
    flag = False
    if s["statement_kind"] == "AWARD":
        cm = next((c for c in STORES["commitments"].values()
                   if c["award_id"] == s["award_id"] and c["person_id"] == s["person_id"]), None)
        if cm is not None and cm.get("is_key_personnel"):
            flag = certified < KEY_FLOOR * D(cm["committed_effort_pct"])
    s["key_reduction_flag"] = bool(flag)
    s["payroll_adjustment_note"] = note
    s["status"] = "CERTIFIED" if s["status"] == "PENDING" else "RECERTIFIED"
    touch(s)
    return ok(sz.statement(s))


@bp.post("/api/effort-statements/<sid>/reopen")
def reopen_statement(sid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    s = get_or_404("statements", sid, "ERR_STATEMENT_NOT_FOUND")
    cycle = STORES["cycles"].get(s["cycle_id"])
    if s["status"] != "CERTIFIED" or cycle is None or cycle["status"] != "CERTIFYING":
        raise err("ERR_STATEMENT_NOT_CERTIFIABLE",
                  "Reopen requires a CERTIFIED statement with cycle CERTIFYING")
    b = body()
    sh = Shape()
    sh_str(b, "reason", sh)
    sh.raise_if_bad()
    person = STORES["persons"].get(s["person_id"])
    if s["statement_kind"] == "AWARD" and person is not None:
        s["charged_effort_pct"] = float(charged_pct(person, s["award_id"], cycle))
    s["certified_effort_pct"] = None
    s["variance_pp"] = None
    s["payroll_adjustment_note"] = None
    s["key_reduction_flag"] = False
    s["status"] = "REOPENED"
    touch(s)
    return ok(sz.statement(s))
