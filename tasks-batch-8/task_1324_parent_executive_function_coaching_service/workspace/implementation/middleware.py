"""Auth header extraction, role checking, validation helpers, serializers."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import errors as E

ROLES = ("PracticeAdmin", "Coach", "FamilyMember", "ExternalContact")


# ---------------------------------------------------------------------------
# Auth (validation priority 1-3)
# ---------------------------------------------------------------------------

def get_auth():
    """Priority 1: both headers present and role in the enumeration."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        E.raise_error(E.ERR_UNAUTHENTICATED,
                      "Missing or unknown X-User-Role / X-User-ID headers")
    return {"role": role, "user_id": user_id}


def require_roles(auth, allowed):
    """Priority 2: role must be listed in the endpoint's roles."""
    if auth["role"] not in allowed:
        E.raise_error(E.ERR_FORBIDDEN_ROLE,
                      "Role %s is not authorized for this endpoint" % auth["role"])


def require_family_scope(auth, family_id):
    if auth["role"] == "FamilyMember" and auth["user_id"] != family_id:
        E.raise_error(E.ERR_FORBIDDEN_SCOPE,
                      "FamilyMember does not own this family resource")


def require_coach_scope(auth, coach_id):
    if auth["role"] == "Coach" and auth["user_id"] != coach_id:
        E.raise_error(E.ERR_FORBIDDEN_SCOPE,
                      "Coach does not own this resource")


# ---------------------------------------------------------------------------
# Body / field validation helpers (priority 5)
# ---------------------------------------------------------------------------

def get_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            E.raise_error(E.ERR_VALIDATION, "Missing required field: %s" % f)


def enum_check(value, allowed, field):
    if value not in allowed:
        E.raise_error(E.ERR_VALIDATION, "Invalid value for %s" % field)


def int_check(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        E.raise_error(E.ERR_VALIDATION, "Field %s must be an integer" % field)
    if minimum is not None and value < minimum:
        E.raise_error(E.ERR_VALIDATION, "Field %s below minimum" % field)
    if maximum is not None and value > maximum:
        E.raise_error(E.ERR_VALIDATION, "Field %s above maximum" % field)


def num_check(value, field, gt=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        E.raise_error(E.ERR_VALIDATION, "Field %s must be a number" % field)
    if gt is not None and not value > gt:
        E.raise_error(E.ERR_VALIDATION, "Field %s must be > %s" % (field, gt))


def parse_dt(value, field):
    """Parse an ISO 8601 datetime; ERR_VALIDATION on malformed input."""
    if not isinstance(value, str):
        E.raise_error(E.ERR_VALIDATION, "Field %s must be an ISO 8601 string" % field)
    s = value
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        E.raise_error(E.ERR_VALIDATION, "Field %s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    if not isinstance(value, str):
        E.raise_error(E.ERR_VALIDATION, "Field %s must be a date string" % field)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        E.raise_error(E.ERR_VALIDATION, "Field %s must be YYYY-MM-DD" % field)
    return value


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------

def rhu(value):
    """Round-half-up a Decimal-compatible value to an integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity access / touch
# ---------------------------------------------------------------------------

_TABLES = {
    "family": lambda: db.families,
    "client": lambda: db.clients,
    "coach": lambda: db.coaches,
    "intake": lambda: db.intakes,
    "plan": lambda: db.plans,
    "goal": lambda: db.goals,
    "package": lambda: db.packages,
    "session": lambda: db.sessions,
    "checkin": lambda: db.checkins,
    "snapshot": lambda: db.snapshots,
    "contact": lambda: db.contacts,
    "consent": lambda: db.consents,
    "note": lambda: db.notes,
    "workshop": lambda: db.workshops,
    "enrollment": lambda: db.enrollments,
    "supervision": lambda: db.supervision_records,
}


def get_entity(kind, entity_id):
    row = _TABLES[kind]().get(entity_id)
    if row is None:
        E.raise_error(E.ERR_NOT_FOUND, "%s not found: %s" % (kind, entity_id))
    return row


def touch(row):
    """Common mutation bookkeeping: version bump + updated_at refresh."""
    row["version"] += 1
    row["updated_at"] = db.now_iso()
    row["updated_dt"] = db.clock


def new_common():
    ts = db.now_iso()
    return {"id": db.new_id(), "created_at": ts, "updated_at": ts,
            "updated_dt": db.clock, "version": 1, "seq": db.next_seq()}


def pagination_params():
    """Read limit/offset with scaffold defaults (10 / 0, min 1, max 100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(rows, serializer, paginate):
    rows = sorted(rows, key=lambda r: (r["created_at"], r["seq"]))
    if paginate:
        limit, offset = pagination_params()
        total = len(rows)
        page = rows[offset:offset + limit]
        from response import success_list
        return success_list([serializer(r) for r in page], limit, offset, total)
    from response import success_list
    return success_list([serializer(r) for r in rows], len(rows), 0, len(rows))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def family_pub(f):
    return {
        "id": f["id"], "created_at": f["created_at"], "updated_at": f["updated_at"],
        "version": f["version"],
        "account_name": f["account_name"], "primary_email": f["primary_email"],
        "status": f["status"],
        "total_charged_cents": f["total_charged_cents"],
        "total_refunded_cents": f["total_refunded_cents"],
        "total_paid_cents": f["total_paid_cents"],
        "outstanding_balance_cents": f["total_charged_cents"] - f["total_refunded_cents"] - f["total_paid_cents"],
        "billing_status": "DELINQUENT" if (f["total_charged_cents"] - f["total_refunded_cents"] - f["total_paid_cents"]) > 20000 else "CURRENT",
    }


def client_pub(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "family_id": c["family_id"], "full_name": c["full_name"],
        "date_of_birth": c["date_of_birth"], "track": c["track"],
        "status": c["status"], "active_plan_id": c["active_plan_id"],
        "checkin_streak": c["checkin_streak"],
        "rolling_progress_index": c["rolling_progress_index"],
        "cumulative_progress_index": c["cumulative_progress_index"],
    }


def coach_pub(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "full_name": c["full_name"], "credential_level": c["credential_level"],
        "status": c["status"], "active_caseload": c["active_caseload"],
        "caseload_cap": c["caseload_cap"],
        "required_supervision_hours": c["required_supervision_hours"],
        "verified_supervision_hours_30d": c["verified_supervision_hours_30d"],
    }


def intake_pub(i):
    return {
        "id": i["id"], "created_at": i["created_at"], "updated_at": i["updated_at"],
        "version": i["version"],
        "client_id": i["client_id"],
        "presenting_concerns": i["presenting_concerns"],
        "baseline_score": i["baseline_score"],
        "review_notes": i["review_notes"], "status": i["status"],
    }


def plan_pub(p):
    # posture is a derived field: reflect current state on every read.
    from services import billing
    posture = billing.compute_plan_posture(p)
    if posture != p["posture"]:
        p["posture"] = posture
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
        "client_id": p["client_id"], "coach_id": p["coach_id"],
        "intake_id": p["intake_id"], "cadence": p["cadence"],
        "revision_number": p["revision_number"], "status": p["status"],
        "posture": p["posture"], "revision_recommended": p["revision_recommended"],
        "activated_at": p["activated_at"],
    }


def goal_pub(g):
    return {
        "id": g["id"], "created_at": g["created_at"], "updated_at": g["updated_at"],
        "version": g["version"],
        "plan_id": g["plan_id"], "title": g["title"],
        "target_date": g["target_date"], "status": g["status"],
        "carried_to_plan_id": g["carried_to_plan_id"], "resolved_at": g["resolved_at"],
    }


def package_pub(p):
    remaining = p["credits_total"] - p["credits_consumed"] - p["credits_forfeited"]
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
        "family_id": p["family_id"], "track": p["track"],
        "credits_total": p["credits_total"],
        "credits_consumed": p["credits_consumed"],
        "credits_forfeited": p["credits_forfeited"],
        "credits_remaining": remaining,
        "reserved_count": p["reserved_count"],
        "price_paid_cents": p["price_paid_cents"],
        "unit_gross_cents": p["unit_gross_cents"],
        "per_credit_value_cents": p["per_credit_value_cents"],
        "provisional_refund_cents": remaining * p["per_credit_value_cents"],
        "purchased_at": p["purchased_at"], "expires_at": p["expires_at"],
        "refund_cents": p["refund_cents"], "status": p["status"],
    }


def session_pub(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
        "plan_id": s["plan_id"], "coach_id": s["coach_id"],
        "package_id": s["package_id"],
        "scheduled_start": s["scheduled_start"], "scheduled_end": s["scheduled_end"],
        "attendance_state": s["attendance_state"], "billing_state": s["billing_state"],
        "cancellation_fee_cents": s["cancellation_fee_cents"],
        "resolved_at": s["resolved_at"],
    }


def checkin_pub(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "plan_id": c["plan_id"], "due_at": c["due_at"],
        "submitted_at": c["submitted_at"], "outcome_note": c["outcome_note"],
        "status": c["status"],
    }


def snapshot_pub(s):
    return {
        "id": s["id"], "created_at": s["created_at"],
        "client_id": s["client_id"],
        "window_start": s["window_start"], "window_end": s["window_end"],
        "goals_considered": s["goals_considered"],
        "goals_achieved": s["goals_achieved"],
        "checkins_considered": s["checkins_considered"],
        "checkins_on_time": s["checkins_on_time"],
        "rolling_index": s["rolling_index"],
        "cumulative_index": s["cumulative_index"],
    }


def contact_pub(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "family_id": c["family_id"], "name": c["name"],
        "organization": c["organization"], "contact_type": c["contact_type"],
        "email": c["email"], "status": c["status"],
    }


def consent_pub(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "family_id": c["family_id"], "contact_id": c["contact_id"],
        "scope": c["scope"], "status": c["status"],
        "signed_at": c["signed_at"], "expires_at": c["expires_at"],
    }


def note_pub(n):
    return {
        "id": n["id"], "created_at": n["created_at"], "updated_at": n["updated_at"],
        "version": n["version"],
        "client_id": n["client_id"], "author_coach_id": n["author_coach_id"],
        "topic": n["topic"], "body": n["body"], "status": n["status"],
        "shared_with_contact_id": n["shared_with_contact_id"],
        "shared_at": n["shared_at"],
    }


def workshop_pub(w):
    return {
        "id": w["id"], "created_at": w["created_at"], "updated_at": w["updated_at"],
        "version": w["version"],
        "title": w["title"], "coach_id": w["coach_id"], "capacity": w["capacity"],
        "window_start": w["window_start"], "window_end": w["window_end"],
        "price_cents": w["price_cents"], "seats_taken": w["seats_taken"],
        "status": w["status"],
    }


def enrollment_pub(e):
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
        "workshop_id": e["workshop_id"], "client_id": e["client_id"],
        "status": e["status"], "waitlist_position": e["waitlist_position"],
        "billing_source": e["billing_source"], "charged_cents": e["charged_cents"],
    }


def supervision_pub(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
        "coach_id": s["coach_id"], "supervisor_coach_id": s["supervisor_coach_id"],
        "scheduled_at": s["scheduled_at"], "hours": s["hours"],
        "status": s["status"], "verified_at": s["verified_at"],
    }
