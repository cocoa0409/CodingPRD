"""Shared business logic: time, validation helpers, lookups, calculations,
and the case-resolution cascade (PRD sections 2.4-2.8, 3.5, 3.7, 3.8)."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import store, new_id
from errors import ApiError

SPECIALTIES = (
    "INTERNAL_MEDICINE", "SURGERY", "CARDIOLOGY", "PEDIATRICS",
    "EMERGENCY_MEDICINE", "ANESTHESIOLOGY", "OBSTETRICS", "PSYCHIATRY",
)
REFERRAL_SOURCES = ("INCIDENT_REPORT", "PATIENT_COMPLAINT", "STAFF_REFERRAL", "INSURER_INQUIRY", "OTHER")
SCREEN_OUT_REASONS = ("DUPLICATE", "FRIVOLOUS", "OUT_OF_SCOPE", "OTHER")
CONFLICT_TYPES = ("PRIOR_TREATING", "FAMILY", "FINANCIAL", "SUPERVISORY", "OTHER")
NOTE_TYPES = ("GENERAL", "DELIBERATION")
MEMBER_ROLES = ("MEMBER", "CHAIR")
CASE_TERMINAL = ("SCREENED_OUT", "CLOSED", "EXTERNAL_REVIEW")
NOTE_ALLOWED_STATES = ("ASSIGNED", "IN_REVIEW", "DELIBERATION", "NOTIFIED", "RESPONDED", "COMMITTEE_REVIEW")

RESPONSE_WINDOW = timedelta(days=14)
REFERRAL_COOLDOWN = timedelta(days=30)
TREND_WINDOW = timedelta(days=365)


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------

def iso(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_iso():
    return iso(store.clock)


def parse_dt(value, field):
    """Parse an ISO 8601 datetime; second-precision comparisons per PRD 2.5."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_VALIDATION", 400, field + " must be an ISO 8601 UTC datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, field + " is not a well-formed ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------------------
# record plumbing
# ---------------------------------------------------------------------------

def make_versioned():
    """Primary resources carry id/created_at/updated_at/version (PRD 2.4)."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(store.seq),
    }


def make_ledger():
    """Ledger records carry only id/created_at (PRD 2.4)."""
    return {"id": new_id(), "created_at": now_iso(), "_seq": next(store.seq)}


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = now_iso()


def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_created(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# request body / field helpers
# ---------------------------------------------------------------------------

def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 400, "request body must be a JSON object")
    return b


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_VALIDATION", 400, field + " is required and must be a non-empty string")
    return v


def opt_str(b, field):
    v = b.get(field)
    if v is not None and not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, field + " must be a string")
    return v


def req_enum(b, field, allowed):
    v = b.get(field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, field + " must be one of: " + ", ".join(allowed))
    return v


def req_body_id(b, field):
    v = b.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_VALIDATION", 400, field + " is required")
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check_score_range(v, field):
    if not is_int(v) or v < 1 or v > 5:
        raise ApiError("ERR_SCORE_OUT_OF_RANGE", 422, field + " must be an integer in 1..5")
    return v


# ---------------------------------------------------------------------------
# existence lookups (PRD 2.8 stage 3)
# ---------------------------------------------------------------------------

def get_provider(pid):
    rec = store.providers.get(pid)
    if rec is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "provider not found")
    return rec


def get_member(mid):
    rec = store.members.get(mid)
    if rec is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "committee member not found")
    return rec


def get_case(cid):
    rec = store.cases.get(cid)
    if rec is None:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "case not found")
    return rec


def get_assignment(aid):
    rec = store.assignments.get(aid)
    if rec is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "assignment not found")
    return rec


def get_conflict(cid):
    rec = store.conflicts.get(cid)
    if rec is None:
        raise ApiError("ERR_CONFLICT_NOT_FOUND", 404, "conflict declaration not found")
    return rec


def get_focused_review(fid):
    rec = store.focused_reviews.get(fid)
    if rec is None:
        raise ApiError("ERR_FOCUSED_REVIEW_NOT_FOUND", 404, "focused review not found")
    return rec


def get_focus_group(gid):
    rec = store.focus_groups.get(gid)
    if rec is None:
        raise ApiError("ERR_FOCUS_GROUP_NOT_FOUND", 404, "focus group not found")
    return rec


# ---------------------------------------------------------------------------
# state / scope guards
# ---------------------------------------------------------------------------

def guard_case_state(case, allowed):
    if case["status"] in CASE_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "case is in a terminal state")
    if case["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE", 409, "case state does not allow this action")


def require_chair(actor):
    m = store.members.get(actor.id)
    if m is None or m["member_role"] != "CHAIR":
        raise ApiError("ERR_CHAIR_REQUIRED", 403, "acting committee member must have member_role CHAIR")
    return m


# ---------------------------------------------------------------------------
# domain helpers
# ---------------------------------------------------------------------------

def deliberation_for(case_id):
    for d in store.deliberations.values():
        if d["case_id"] == case_id:
            return d
    return None


def notification_for(case_id):
    for n in store.notifications.values():
        if n["case_id"] == case_id:
            return n
    return None


def response_for(case_id):
    for r in store.responses.values():
        if r["case_id"] == case_id:
            return r
    return None


def referral_for(case_id):
    for r in store.external_referrals.values():
        if r["case_id"] == case_id:
            return r
    return None


def submitted_assignments(case_id):
    return [a for a in store.assignments.values()
            if a["case_id"] == case_id and a["status"] == "SUBMITTED"]


def case_assignments(case_id):
    return [a for a in store.assignments.values() if a["case_id"] == case_id]


def active_focused_review(provider_id):
    cands = [f for f in store.focused_reviews.values()
             if f["provider_id"] == provider_id and f["status"] == "ACTIVE"]
    if not cands:
        return None
    return sort_created(cands)[0]


def compute_rating(subs):
    """Severity-precedence aggregation (PRD 3.5); first matching band wins."""
    care = [a["care_appropriateness_score"] for a in subs]
    ofi = [a["ofi_score"] for a in subs if a["ofi_score"] is not None]
    if any(c == 1 for c in care):
        return "UNACCEPTABLE"
    if sum(1 for c in care if c <= 2) >= 2 or sum(1 for o in ofi if o >= 4) >= 2:
        return "MAJOR_OFI"
    if sum(1 for c in care if c <= 2) == 1 or sum(1 for o in ofi if o >= 4) == 1 or len(ofi) >= 1:
        return "MINOR_OFI"
    return "APPROPRIATE"


def compute_trend(provider_id):
    """provider_trend_metrics (PRD 3.8): per-case means rounded half-up to
    2dp first, then averaged and rounded again."""
    now = store.clock
    window_start = now - TREND_WINDOW
    rated = []
    for case in store.cases.values():
        if case["subject_provider_id"] != provider_id:
            continue
        if case["status"] not in ("CLOSED", "EXTERNAL_REVIEW"):
            continue
        d = deliberation_for(case["id"])
        if d is None or d["status"] != "FINALIZED" or d["rating"] is None:
            continue
        fdt = d["_finalized_dt"]
        if fdt is None or not (window_start < fdt <= now):
            continue
        rated.append((case, d))
    per_case = []
    for case, _d in rated:
        subs = submitted_assignments(case["id"])
        scores = [a["care_appropriateness_score"] for a in subs]
        mean = sum(Decimal(s) for s in scores) / Decimal(len(scores))
        per_case.append(mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    count = len(rated)
    avg = None
    if count:
        avg = (sum(per_case) / Decimal(count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "window_start": window_start,
        "window_end": now,
        "rated_case_count": count,
        "avg": avg,
        "major_ofi_case_count": sum(1 for _, d in rated if d["rating"] == "MAJOR_OFI"),
        "unacceptable_case_count": sum(1 for _, d in rated if d["rating"] == "UNACCEPTABLE"),
    }


def trigger_fires(t):
    """focused_review_trigger_evaluation (PRD 3.8): OR semantics."""
    if t["rated_case_count"] >= 3:
        return True
    if t["rated_case_count"] > 0 and t["avg"] is not None and t["avg"] < Decimal("3.0"):
        return True
    if t["major_ofi_case_count"] >= 1:
        return True
    if t["unacceptable_case_count"] >= 1:
        return True
    return False


def trend_snapshot(t):
    return {
        "window_start": iso(t["window_start"]),
        "window_end": iso(t["window_end"]),
        "rated_case_count": t["rated_case_count"],
        "avg_care_appropriateness": float(t["avg"]) if t["avg"] is not None else None,
        "major_ofi_case_count": t["major_ofi_case_count"],
        "unacceptable_case_count": t["unacceptable_case_count"],
    }


def run_resolution_cascade(case):
    """PRD 3.7: fires on every transition into CLOSED or EXTERNAL_REVIEW.
    Link 1: trend recompute (computed on demand; nothing persisted).
    Link 2: focused-review trigger evaluation.
    Link 3: AUTO_CASE_RESOLVED conflict declarations for SUBMITTED reviewers.
    Link 4: focus_group_id stamping."""
    pid = case["subject_provider_id"]

    # Link 2: trigger evaluation against freshly computed metrics
    t = compute_trend(pid)
    if trigger_fires(t) and active_focused_review(pid) is None:
        rec = make_versioned()
        rec.update({
            "provider_id": pid,
            "trigger_type": "AUTOMATIC",
            "basis": None,
            "trigger_snapshot": trend_snapshot(t),
            "status": "ACTIVE",
            "opened_at": now_iso(),
            "closed_at": None,
            "resolution_note": None,
        })
        store.focused_reviews[rec["id"]] = rec

    # Link 3: auto conflict declarations
    for a in submitted_assignments(case["id"]):
        dup = any(c for c in store.conflicts.values()
                  if c["member_id"] == a["reviewer_id"] and c["provider_id"] == pid)
        if not dup:
            rec = make_ledger()
            rec.update({
                "member_id": a["reviewer_id"],
                "provider_id": pid,
                "conflict_type": "OTHER",
                "source": "AUTO_CASE_RESOLVED",
            })
            store.conflicts[rec["id"]] = rec

    # Link 4: focus group stamping
    fr = active_focused_review(pid)
    if fr is not None:
        groups = sort_created([g for g in store.focus_groups.values() if g["focus_id"] == fr["id"]])
        if groups:
            def attached(g):
                return sum(1 for c in store.cases.values() if c["focus_group_id"] == g["id"])
            best = min(groups, key=lambda g: (attached(g), g["created_at"], g["_seq"]))
            case["focus_group_id"] = best["id"]
