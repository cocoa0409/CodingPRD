"""Shared record helpers: creation, mutation stamping, serializers."""

from db import store, next_seq, take_stamp
from errors import ApiError
from util import new_id, fmt_ts, fmt_dt
import calc


def touch(rec):
    rec["version"] = rec.get("version", 0) + 1
    rec["updated_at"] = fmt_ts(take_stamp())


def new_record(coll, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = fmt_ts(take_stamp())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    store[coll][rec["id"]] = rec
    return rec


def get_or_404(coll, rid, err_id, label):
    rec = store[coll].get(rid)
    if rec is None:
        raise ApiError(err_id, 404, f"{label} not found: {rid}")
    return rec


def children(coll, case_id, key="case_id"):
    return [r for r in store[coll].values() if r.get(key) == case_id]


def find_one(coll, case_id, key="case_id"):
    for r in store[coll].values():
        if r.get(key) == case_id:
            return r
    return None


def sort_created(records):
    return sorted(records, key=lambda r: (r["_seq"],))


def sort_indexed(records):
    return sorted(records, key=lambda r: (r["sort_index"], r["_seq"]))


# ---- serializers (declared fields only; internals prefixed with _) ----

def _pick(rec, fields):
    return {k: rec.get(k) for k in fields}


COMMON = ["id", "created_at", "updated_at", "version"]


def ser_profile(p):
    return _pick(p, ["id", "name", "status", "published_version",
                     "preboarding_tasks", "training_modules",
                     "equipment_items", "access_grants", "probation_days",
                     "max_probation_extensions", "extension_days",
                     "buddy_checkin_interval_days", "buddy_checkin_count",
                     "manager_checkin_offsets_days", "provisioning_sla_hours",
                     "created_at", "updated_at", "version"])


def ser_employee(e):
    return _pick(e, ["id", "full_name", "email", "employment_status",
                     "manager_id", "created_at", "updated_at", "version"])


def ser_new_hire(n):
    return _pick(n, ["id", "full_name", "personal_email", "start_date",
                     "department", "status", "created_at", "updated_at",
                     "version"])


def ser_case(c):
    return _pick(c, ["id", "new_hire_id", "role_profile_id",
                     "pinned_profile_version", "manager_id", "buddy_id",
                     "start_date", "base_salary_cents", "signing_bonus_cents",
                     "relocation_stipend_cents", "benefits_tier", "phase",
                     "health", "health_score", "orientation_session_id",
                     "orientation_rsvp", "manager_reassignment_required",
                     "created_at", "updated_at", "version"])


def ser_task(t):
    return _pick(t, ["id", "case_id", "task_kind", "title", "is_required",
                     "status", "document_ref", "note", "review_note",
                     "reject_count", "due_at", "sort_index", "created_at",
                     "updated_at", "version"])


def ser_clearance(c):
    return _pick(c, ["id", "case_id", "status", "background_status",
                     "reference_status", "initiated_by_user_id",
                     "adjudicated_by_user_id", "adjudication_rationale",
                     "override_clear", "created_at", "updated_at", "version"])


def ser_order(o):
    out = _pick(o, ["id", "case_id", "status", "pinned_profile_version",
                    "sla_hours", "submitted_at", "fulfilled_at",
                    "created_at", "updated_at", "version"])
    out.update(calc.sla_fields(o))
    return out


def ser_item(i):
    return _pick(i, ["id", "order_id", "item_kind", "item_name", "quantity",
                     "status", "blocked_reason", "sort_index", "created_at",
                     "updated_at", "version"])


def session_booked_count(session):
    return sum(1 for c in store["cases"].values()
               if c.get("orientation_session_id") == session["id"]
               and c.get("orientation_rsvp") in ("BOOKED", "ATTENDED"))


def ser_session(s):
    out = _pick(s, ["id", "room", "starts_at", "ends_at", "capacity",
                    "status", "created_at", "updated_at", "version"])
    out["booked_count"] = session_booked_count(s)
    return out


def ser_checkin(c):
    return _pick(c, ["id", "case_id", "owner_employee_id", "kind",
                     "scheduled_at", "status", "productivity_rating", "notes",
                     "completed_at", "sort_index", "created_at", "updated_at",
                     "version"])


def ser_training(t):
    return _pick(t, ["id", "case_id", "module_code", "due_at", "status",
                     "score", "completed_at", "completed_late", "sort_index",
                     "created_at", "updated_at", "version"])


def ser_cycle(c):
    return _pick(c, ["id", "case_id", "cycle_index", "evaluation_due_at",
                     "status", "outcome_rating", "notes", "evaluated_at",
                     "created_at", "updated_at", "version"])


def ser_handoff(h):
    return _pick(h, ["id", "case_id", "status", "base_salary_cents",
                     "signing_bonus_cents", "relocation_stipend_cents",
                     "benefits_tier", "start_date", "first_period_start_date",
                     "first_period_end_date", "first_period_gross_cents",
                     "transmitted_at", "acknowledged_at",
                     "benefits_window_end", "benefits_window_breached",
                     "rejection_reason", "created_at", "updated_at",
                     "version"])


def ser_survey(s):
    return _pick(s, ["id", "case_id", "status", "sent_at", "expires_at",
                     "onboarding_experience_rating", "manager_support_rating",
                     "resources_rating", "overall_score", "created_at",
                     "updated_at", "version"])
