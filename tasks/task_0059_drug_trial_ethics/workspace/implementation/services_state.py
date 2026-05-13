from __future__ import annotations

"""Core business logic: state machines, tally, cascades, audit, sweep.

This module is intentionally one big collection of pure-ish functions over the
in-memory store. The HTTP layer composes these functions inside db.lock to
serialize mutations.
"""

import math
from datetime import timedelta
from typing import Optional

import db
from clock import iso, now, parse_iso


QUORUM_PERCENT = 67
QUORUM_MIN_ABSOLUTE = 5
RECTIFICATION_WINDOW_DAYS = 30
SAFETY_ALERT_THRESHOLD = 3
SAFETY_ALERT_RATE = 0.20
LEAD_STANDARD_HOURS = 168
LEAD_EXPEDITED_HOURS = 24


# -----------------------------------------------------------------------------
# Common entity machinery
# -----------------------------------------------------------------------------
def new_versioned(extra: dict | None = None) -> dict:
    ts = iso()
    base = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    if extra:
        base.update(extra)
    return base


def new_append_only(extra: dict | None = None) -> dict:
    base = {
        "id": db.new_id(),
        "created_at": iso(),
    }
    if extra:
        base.update(extra)
    return base


def bump(entity: dict) -> None:
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = iso()


# -----------------------------------------------------------------------------
# Member helpers
# -----------------------------------------------------------------------------
def compute_member_is_active(m: dict) -> bool:
    """is_active = now in [term_start, term_end) AND status == ACTIVE."""
    if m.get("status") != "ACTIVE":
        return False
    try:
        start = parse_iso(m["term_start"])
        end = parse_iso(m["term_end"])
    except Exception:
        return False
    n = now()
    return (n >= start) and (n < end)


def member_has_active_conflict(member_id: str, application_id: str) -> bool:
    for c in db.conflict_declarations.values():
        if c["member_id"] == member_id and c["application_id"] == application_id:
            return True
    return False


# -----------------------------------------------------------------------------
# Audit
# -----------------------------------------------------------------------------
def write_audit(actor_role: str, actor_id: str, event_type: str,
                subject_entity: str, subject_id: str, payload: dict | None = None) -> dict:
    row = new_append_only({
        "actor_role": actor_role,
        "actor_id": actor_id,
        "event_type": event_type,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "payload": payload or {},
    })
    db.audit_logs[row["id"]] = row
    return row


# -----------------------------------------------------------------------------
# Submission helpers
# -----------------------------------------------------------------------------
def submission_checklist_complete(submission: dict) -> bool:
    keys = ("protocol_doc_uri", "investigator_brochure_uri",
            "informed_consent_uri", "cv_doc_uri")
    for k in keys:
        v = submission.get(k)
        if not isinstance(v, str) or not v.strip():
            return False
    return True


def current_submission(application_id: str) -> Optional[dict]:
    for s in db.submissions.values():
        if s["application_id"] == application_id and s.get("is_current"):
            return s
    return None


def max_version_number(application_id: str) -> int:
    versions = [s["version_number"] for s in db.submissions.values()
                if s["application_id"] == application_id]
    return max(versions) if versions else 0


# -----------------------------------------------------------------------------
# Conflict declaration: auto-detection on member create / application create
# -----------------------------------------------------------------------------
def maybe_auto_declare_conflicts_on_member_create(member: dict) -> None:
    affiliated = set(member.get("affiliated_sponsors") or [])
    if not affiliated:
        return
    for app in list(db.applications.values()):
        if app["sponsor_name"] in affiliated:
            if not _conflict_exists(member["id"], app["id"]):
                cd = new_append_only({
                    "member_id": member["id"],
                    "application_id": app["id"],
                    "conflict_type": "SPONSOR_RELATION",
                    "details": "Auto-detected: sponsor in member's affiliated_sponsors",
                    "auto_detected": True,
                })
                db.conflict_declarations[cd["id"]] = cd
                write_audit(member.get("_creator_role", "system"),
                            member.get("_creator_id", "system"),
                            "MEMBER_RECUSAL", "ConflictDeclaration", cd["id"],
                            {"member_id": member["id"], "application_id": app["id"],
                             "auto_detected": True})


def maybe_auto_declare_conflicts_on_application_create(app: dict, creator_role: str, creator_id: str) -> None:
    for m in list(db.committee_members.values()):
        if app["sponsor_name"] in (m.get("affiliated_sponsors") or []):
            if not _conflict_exists(m["id"], app["id"]):
                cd = new_append_only({
                    "member_id": m["id"],
                    "application_id": app["id"],
                    "conflict_type": "SPONSOR_RELATION",
                    "details": "Auto-detected: sponsor in member's affiliated_sponsors",
                    "auto_detected": True,
                })
                db.conflict_declarations[cd["id"]] = cd
                write_audit(creator_role, creator_id,
                            "MEMBER_RECUSAL", "ConflictDeclaration", cd["id"],
                            {"member_id": m["id"], "application_id": app["id"],
                             "auto_detected": True})


def _conflict_exists(member_id: str, application_id: str) -> bool:
    for c in db.conflict_declarations.values():
        if c["member_id"] == member_id and c["application_id"] == application_id:
            return True
    return False


# -----------------------------------------------------------------------------
# Quorum / publication
# -----------------------------------------------------------------------------
def compute_eligible_voter_count(application_id: str) -> int:
    count = 0
    for m in db.committee_members.values():
        if not compute_member_is_active(m):
            continue
        if member_has_active_conflict(m["id"], application_id):
            continue
        count += 1
    return count


def compute_quorum_required(eligible_count: int) -> int:
    # Multiply percent → ceil → max with absolute floor
    pct = math.ceil(QUORUM_PERCENT / 100.0 * eligible_count)
    return max(QUORUM_MIN_ABSOLUTE, pct)


# -----------------------------------------------------------------------------
# Vote tally
# -----------------------------------------------------------------------------
def tally_outcome(votes: list[dict], quorum_required: int,
                  eligible_voter_count: int) -> tuple[str, dict]:
    counts = {"APPROVE": 0, "APPROVE_WITH_MODIFICATION": 0, "REJECT": 0, "DEFER": 0}
    for v in votes:
        counts[v["vote_mode"]] += 1

    votes_cast = len(votes)
    tally = {
        **counts,
        "total_votes_cast": votes_cast,
        "eligible_voter_count": eligible_voter_count,
        "quorum_required": quorum_required,
    }
    if votes_cast < quorum_required:
        return "NO_QUORUM", tally

    # 1. REJECT majority (strict)
    if counts["REJECT"] * 2 > votes_cast:
        return "REJECT", tally

    # 2. APPROVE supermajority (>= ceil(2/3 * votes_cast))
    approval_count = counts["APPROVE"] + counts["APPROVE_WITH_MODIFICATION"]
    supermajority = math.ceil(2 * votes_cast / 3)
    if approval_count >= supermajority:
        if counts["APPROVE_WITH_MODIFICATION"] > counts["APPROVE"]:
            return "APPROVE_WITH_MODIFICATION", tally
        else:
            # equal or APPROVE > AWM → tie-break to APPROVE_WITH_MODIFICATION on equality
            if counts["APPROVE_WITH_MODIFICATION"] == counts["APPROVE"]:
                return "APPROVE_WITH_MODIFICATION", tally
            return "APPROVE", tally

    # 3. DEFER majority (>= ceil(votes_cast / 2))
    defer_threshold = math.ceil(votes_cast / 2)
    if counts["DEFER"] >= defer_threshold:
        return "DEFER", tally

    # 4. fallback → DEFER
    return "DEFER", tally


# -----------------------------------------------------------------------------
# Safety alert
# -----------------------------------------------------------------------------
def compute_safety_alert_flag(serious: int, total: int, enrollment: int) -> bool:
    if serious >= SAFETY_ALERT_THRESHOLD:
        return True
    if enrollment > 0:
        rate = total / enrollment
        if rate >= SAFETY_ALERT_RATE:
            return True
    return False


# -----------------------------------------------------------------------------
# Application state cascades
# -----------------------------------------------------------------------------
def application_set_status(app: dict, new_status: str) -> None:
    app["status"] = new_status
    bump(app)


def cascade_initial_review(app: dict, agenda_item: dict, resolution: dict,
                           actor_role: str, actor_id: str) -> None:
    outcome = resolution["outcome"]
    if outcome == "APPROVE":
        app["approved_submission_version"] = agenda_item["pinned_submission_version"]
        app["approval_resolution_id"] = resolution["id"]
        application_set_status(app, "APPROVED")
        write_audit(actor_role, actor_id, "REGULATORY_SYNC", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
        write_audit(actor_role, actor_id, "IM_NOTIFICATION", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
    elif outcome == "APPROVE_WITH_MODIFICATION":
        app["approved_submission_version"] = agenda_item["pinned_submission_version"]
        app["approval_resolution_id"] = resolution["id"]
        application_set_status(app, "APPROVED_WITH_MOD")
        _create_rectification(app, resolution)
        write_audit(actor_role, actor_id, "REGULATORY_SYNC", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
        write_audit(actor_role, actor_id, "IM_NOTIFICATION", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
    elif outcome == "REJECT":
        application_set_status(app, "REJECTED")
        write_audit(actor_role, actor_id, "REGULATORY_SYNC", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
        write_audit(actor_role, actor_id, "IM_NOTIFICATION", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
    elif outcome == "DEFER":
        application_set_status(app, "DEFERRED")
        _create_rectification(app, resolution)
        write_audit(actor_role, actor_id, "REGULATORY_SYNC", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
        write_audit(actor_role, actor_id, "IM_NOTIFICATION", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
    elif outcome == "NO_QUORUM":
        application_set_status(app, "DEFERRED")
        # No regulatory/IM events for NO_QUORUM


def cascade_continuing_review(app: dict, agenda_item: dict, resolution: dict,
                              annual_report: dict, actor_role: str, actor_id: str) -> None:
    """ANNUAL/AMENDMENT/FINAL_REPORT review remap."""
    underlying = resolution["outcome"]
    if underlying == "NO_QUORUM":
        application_set_status(app, "DEFERRED")
        annual_report["outcome"] = None
        annual_report["status"] = "RESOLVED"
        bump(annual_report)
        return

    if underlying in ("APPROVE", "APPROVE_WITH_MODIFICATION"):
        mapped = "CONTINUE"
    elif underlying == "REJECT":
        mapped = "TERMINATE"
    else:  # DEFER
        mapped = "SUSPEND"

    annual_report["outcome"] = mapped
    annual_report["status"] = "RESOLVED"
    bump(annual_report)

    review_kind = agenda_item["review_kind"]
    prior_state = app["status"]

    if mapped == "CONTINUE":
        if review_kind == "FINAL_REPORT_REVIEW" and annual_report["report_kind"] == "FINAL_REPORT" and underlying == "APPROVE":
            application_set_status(app, "COMPLETED")
            write_audit(actor_role, actor_id, "REGULATORY_SYNC", "Application", app["id"],
                        {"outcome": "COMPLETED", "resolution_id": resolution["id"]})
            write_audit(actor_role, actor_id, "IM_NOTIFICATION", "Application", app["id"],
                        {"outcome": "COMPLETED", "resolution_id": resolution["id"]})
        elif prior_state == "SUSPENDED":
            application_set_status(app, "APPROVED")
        # else: stay in current APPROVED / APPROVED_WITH_MOD
    elif mapped == "SUSPEND":
        if prior_state in ("APPROVED", "APPROVED_WITH_MOD"):
            application_set_status(app, "SUSPENDED")
            write_audit(actor_role, actor_id, "REGULATORY_SYNC", "Application", app["id"],
                        {"outcome": "SUSPENDED", "resolution_id": resolution["id"]})
            write_audit(actor_role, actor_id, "IM_NOTIFICATION", "Application", app["id"],
                        {"outcome": "SUSPENDED", "resolution_id": resolution["id"]})
    elif mapped == "TERMINATE":
        if prior_state in ("APPROVED", "APPROVED_WITH_MOD"):
            application_set_status(app, "TERMINATED")
            write_audit(actor_role, actor_id, "REGULATORY_SYNC", "Application", app["id"],
                        {"outcome": "TERMINATED", "resolution_id": resolution["id"]})
            write_audit(actor_role, actor_id, "IM_NOTIFICATION", "Application", app["id"],
                        {"outcome": "TERMINATED", "resolution_id": resolution["id"]})


def _create_rectification(app: dict, resolution: dict) -> dict:
    created = parse_iso(resolution["created_at"])
    due = created + timedelta(days=RECTIFICATION_WINDOW_DAYS)
    rec = new_versioned({
        "application_id": app["id"],
        "source_resolution_id": resolution["id"],
        "opinions": ["Committee comments pending"],
        "due_at": iso(due),
        "applicant_response_uri": None,
        "responded_at": None,
        "status": "OPEN",
    })
    db.rectifications[rec["id"]] = rec
    return rec


def cascade_secondary_review(app: dict, agenda_item: dict, resolution: dict,
                             rectification: dict, actor_role: str, actor_id: str) -> None:
    """SECONDARY_REVIEW resolution affects the linked rectification + application."""
    outcome = resolution["outcome"]
    if outcome == "NO_QUORUM":
        application_set_status(app, "DEFERRED")
        return
    if outcome in ("APPROVE", "APPROVE_WITH_MODIFICATION"):
        rectification["status"] = "CLOSED_APPROVED"
        bump(rectification)
        # Find originating source resolution outcome
        source_res = db.resolutions.get(rectification["source_resolution_id"])
        if source_res and source_res["outcome"] == "DEFER":
            # cascade DEFERRED → PENDING_REVIEW
            if app["status"] == "DEFERRED":
                application_set_status(app, "PENDING_REVIEW")
        # else originating from APPROVE_WITH_MOD: app stays in APPROVED_WITH_MOD
        write_audit(actor_role, actor_id, "REGULATORY_SYNC", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
        write_audit(actor_role, actor_id, "IM_NOTIFICATION", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
    elif outcome == "REJECT":
        rectification["status"] = "CLOSED_REJECTED"
        bump(rectification)
        application_set_status(app, "REJECTED")
        write_audit(actor_role, actor_id, "REGULATORY_SYNC", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
        write_audit(actor_role, actor_id, "IM_NOTIFICATION", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
    elif outcome == "DEFER":
        # treat like initial DEFER → keep DEFERRED, create new rectification linked to this resolution
        application_set_status(app, "DEFERRED")
        _create_rectification(app, resolution)
        write_audit(actor_role, actor_id, "REGULATORY_SYNC", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})
        write_audit(actor_role, actor_id, "IM_NOTIFICATION", "Application", app["id"],
                    {"outcome": outcome, "resolution_id": resolution["id"]})


# -----------------------------------------------------------------------------
# Sweep
# -----------------------------------------------------------------------------
def run_expiry_sweep(actor_role: str, actor_id: str) -> int:
    n = now()
    # Iterate in ascending created_at, then id
    candidates = [r for r in db.rectifications.values() if r["status"] == "OPEN"]
    candidates.sort(key=lambda r: (r["created_at"], r["id"]))
    flipped = 0
    for rec in candidates:
        due = parse_iso(rec["due_at"])
        if n >= due:
            rec["status"] = "EXPIRED"
            bump(rec)
            flipped += 1
            # cascade per origin
            source_res = db.resolutions.get(rec["source_resolution_id"])
            app = db.applications.get(rec["application_id"])
            if source_res and app:
                if source_res["outcome"] == "APPROVE_WITH_MODIFICATION":
                    if app["status"] == "APPROVED_WITH_MOD":
                        application_set_status(app, "REJECTED")
                # else: DEFER origin → app stays in DEFERRED
            write_audit(actor_role, actor_id, "REVIEW_DECISION",
                        "Rectification", rec["id"],
                        {"event": "RECTIFICATION_EXPIRED",
                         "application_id": rec["application_id"]})
    return flipped


# -----------------------------------------------------------------------------
# Pagination helper
# -----------------------------------------------------------------------------
def paginate(rows: list, limit: int, offset: int) -> list:
    return rows[offset: offset + limit]
