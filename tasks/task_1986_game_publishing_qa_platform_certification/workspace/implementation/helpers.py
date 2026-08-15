"""Shared helpers: ids, timestamps, pagination, computed fields."""

import uuid
from datetime import datetime, timezone, timedelta, date, time

from db import db
from errors import ApiError


def new_id():
    return str(uuid.uuid4())


def clock_now():
    return db.clock


def clock_iso():
    ts = db.clock
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def touch(entity):
    entity["updated_at"] = clock_iso()
    entity["version"] += 1


def init_common(entity):
    entity["id"] = new_id()
    ts = clock_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_created"] = db.clock  # internal datetime mirror of created_at


def public(entity):
    """Strip internal underscore-prefixed fields for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def parse_iso_dt(value, field):
    """Parse an ISO 8601 datetime to an aware datetime (UTC assumed on naive)."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string.", 400)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 datetime.", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 date string.", 400)
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 date.", 400)


def monday_of_current_week():
    today = db.clock.date()
    return today - timedelta(days=today.weekday())


def week_monday_of(dt):
    d = dt.date()
    return d - timedelta(days=d.weekday())


def get_pagination(args):
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.", 400)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit out of range.", 400)
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.", 400)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset out of range.", 400)
    return limit, offset


# ---------- computed fields ----------

def open_blocker_count(title_id):
    n = 0
    for b in db.bugs.values():
        if b["title_id"] == title_id and b["severity"] == "BLOCKER" and \
                b["status"] in ("OPEN", "TRIAGED", "IN_PROGRESS", "REOPENED"):
            n += 1
    return n


def escrow_cents(title_id):
    total = 0
    for p in db.packages.values():
        if p["title_id"] == title_id and p["status"] in ("SUBMITTED", "IN_REVIEW") and \
                p["fee_cents"] is not None:
            total += p["fee_cents"]
    return total


def spent_cents(title_id):
    total = 0
    for p in db.packages.values():
        if p["title_id"] == title_id and p["status"] in ("APPROVED", "REJECTED") and \
                p["fee_cents"] is not None:
            total += p["fee_cents"]
    for f in db.filings.values():
        if f["title_id"] == title_id and f["fee_cents"] is not None:
            total += f["fee_cents"]
    for w in db.windows.values():
        if w["title_id"] == title_id and w["fee_cents"] is not None:
            total += w["fee_cents"]
    for h in db.hotfixes.values():
        if h["title_id"] == title_id and h["fee_cents"] is not None:
            total += h["fee_cents"]
    return total


def title_view(t):
    escrow = escrow_cents(t["id"])
    spent = spent_cents(t["id"])
    available = t["cert_budget_total_cents"] - escrow - spent
    out = public(t)
    out["cert_budget_escrow_cents"] = escrow
    out["cert_budget_spent_cents"] = spent
    out["cert_budget_available_cents"] = available
    out["open_blocker_count"] = open_blocker_count(t["id"])
    return out


def vendor_committed_current_week(vendor_id):
    monday = monday_of_current_week().isoformat()
    total = 0
    for a in db.assignments.values():
        if a["vendor_id"] == vendor_id and a["week_start_date"] == monday and \
                a["status"] in ("SCHEDULED", "IN_PROGRESS"):
            total += a["reserved_hours"]
    return total


def vendor_escapes(vendor_id):
    n = 0
    for b in db.bugs.values():
        if b.get("found_by_vendor_id") == vendor_id and b.get("found_post_launch") and \
                b["status"] not in ("DUPLICATE", "WONT_FIX"):
            n += 1
    return n


def vendor_view(v):
    committed = vendor_committed_current_week(v["id"])
    out = public(v)
    out["committed_hours_current_week"] = committed
    out["available_hours_current_week"] = v["weekly_capacity_hours"] - committed
    out["escapes_count"] = vendor_escapes(v["id"])
    return out


def entry_assigned_hours(plan_id, feature_area):
    total = 0
    for a in db.assignments.values():
        if a["plan_id"] == plan_id and a["feature_area"] == feature_area and \
                a["status"] in ("SCHEDULED", "IN_PROGRESS", "DONE"):
            total += a["reserved_hours"]
    return total


def plan_view(p):
    entries = []
    covered_required = 0
    required_total = 0
    for e in p["entries"]:
        assigned = entry_assigned_hours(p["id"], e["feature_area"])
        if assigned >= e["required_coverage_hours"]:
            cov = "COVERED"
        elif assigned > 0:
            cov = "PARTIAL"
        else:
            cov = "UNCOVERED"
        entry = dict(e)
        entry["assigned_hours"] = assigned
        entry["coverage_status"] = cov
        entries.append(entry)
        if e["is_cert_blocker"]:
            required_total += 1
            if cov == "COVERED":
                covered_required += 1
    out = public(p)
    out["entries"] = entries
    out["required_entries_total"] = required_total
    out["covered_required_count"] = covered_required
    return out


def checklist_counters(c):
    items = c["items"]
    passed = sum(1 for i in items if i["status"] == "PASSED")
    waived = sum(1 for i in items if i["status"] == "WAIVED")
    na = sum(1 for i in items if i["status"] == "NA")
    failed = sum(1 for i in items if i["status"] == "FAILED")
    unverified = sum(1 for i in items if i["status"] == "UNVERIFIED")
    return {
        "total_items": len(items),
        "passed_count": passed,
        "waived_count": waived,
        "na_count": na,
        "failed_count": failed,
        "unverified_count": unverified,
    }


def checklist_view(c):
    out = public(c)
    out.update(checklist_counters(c))
    return out


def round_half_up_2dp(numerator, denominator):
    from decimal import Decimal, ROUND_HALF_UP
    if denominator == 0:
        return Decimal("100.00")
    val = (Decimal(100) * Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return val


def readiness(c):
    """Return (optimistic_pct, strict_pct) as floats with 2dp."""
    items = c["items"]
    total = len(items)
    strict_num = sum(1 for i in items if i["status"] in ("PASSED", "WAIVED", "NA"))
    opt_num = sum(1 for i in items if i["status"] in ("PASSED", "WAIVED", "NA") or
                  (i["status"] == "UNVERIFIED" and i["auto_verifiable"]))
    strict = round_half_up_2dp(strict_num, total)
    opt = round_half_up_2dp(opt_num, total)
    return float(opt), float(strict)


def refresh_package_readiness(package_id):
    p = db.packages.get(package_id)
    if p is None:
        return
    c = db.checklists.get(p["checklist_id"])
    if c is None:
        return
    opt, strict = readiness(c)
    p["readiness_optimistic_pct"] = opt
    p["readiness_strict_pct"] = strict


def pack_view(pk):
    out = public(pk)
    out["text_coverage_pct"] = float(round_half_up_2dp(
        pk["translated_text_assets"], pk["text_asset_total"])) \
        if pk["text_asset_total"] else 100.00
    out["audio_coverage_pct"] = float(round_half_up_2dp(
        pk["translated_audio_assets"], pk["audio_asset_total"])) \
        if pk["audio_asset_total"] else 100.00
    return out


def find_plan_unlock_candidates(plan_id):
    """Check if plan can unlock LOCKED -> APPROVED: every referencing package terminal."""
    terminal = ("APPROVED", "WITHDRAWN", "SUPERSEDED", "CLOSED")
    for p in db.packages.values():
        if p["test_plan_id"] == plan_id and p["status"] not in terminal:
            return False
    return True


def maybe_unlock_plan(plan_id):
    plan = db.test_plans.get(plan_id)
    if plan is None or plan["status"] != "LOCKED":
        return
    if find_plan_unlock_candidates(plan_id):
        plan["status"] = "APPROVED"
        touch(plan)


def cancel_assignment_cascade(assignment):
    """Cancel SCHEDULED/IN_PROGRESS assignment; demote APPROVED plan on coverage loss."""
    if assignment["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        return
    assignment["status"] = "CANCELLED"
    touch(assignment)
    plan = db.test_plans.get(assignment["plan_id"])
    if plan is None:
        return
    if plan["status"] == "APPROVED":
        view = plan_view(plan)
        for e in view["entries"]:
            if e["is_cert_blocker"] and e["coverage_status"] != "COVERED":
                plan["status"] = "DRAFT"
                touch(plan)
                break
