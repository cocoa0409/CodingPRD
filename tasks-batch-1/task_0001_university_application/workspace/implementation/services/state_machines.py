"""State-machine transitions for Application / RecommendationRequest /
AidPackage / WaitlistEntry. Includes cascade handling.

Validation priority (relevant to action endpoints):
  - state precondition (5) ERR_INVALID_STATE
  - business preconditions (6+) using endpoint-specific error_ids
"""
from __future__ import annotations

from typing import Optional

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_DEADLINE_PASSED,
    ERR_ED_EXCLUSIVITY_VIOLATED,
    ERR_APPLICATION_INCOMPLETE,
    ERR_ED_BINDING_VIOLATION,
    ERR_ENROLLMENT_ALREADY_DECLARED,
    ERR_AID_EXCEEDS_TUITION,
    ERR_YIELD_TARGET_REACHED,
    ERR_STALE_VERSION,
    ERR_FORBIDDEN_OWNER_MISMATCH,
    ERR_INVALID_REQUEST,
)
from services.common import touch
from services import calculations

LIVE_STATUSES = {
    "SUBMITTED", "UNDER_REVIEW", "ADMITTED",
    "WAITLISTED", "DENIED", "ENROLLED", "DECLINED",
}
ED_LIVE_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "ADMITTED", "WAITLISTED", "ENROLLED"}


# ---------------------------------------------------------------- helpers
def _maybe_lock_applicant(applicant: dict):
    if applicant["profile_status"] == "DRAFT":
        applicant["profile_status"] = "LOCKED"
        touch(applicant)


def _bump_school_admitted(school: dict, delta: int):
    school["admitted_count"] += delta
    calculations.recompute_yield_posture(school)
    touch(school)


def _bump_school_enrolled(school: dict, delta: int):
    school["enrolled_count"] += delta
    calculations.recompute_yield_posture(school)
    touch(school)


def _bump_school_simple(school: dict, field: str, delta: int):
    school[field] += delta
    touch(school)


def _recompute_composites_for_applicant(applicant_id: str):
    """Recompute composite_score for any of this applicant's apps in SUBMITTED/UNDER_REVIEW."""
    for app in db.applications.values():
        if app["applicant_id"] == applicant_id and app["status"] in {"SUBMITTED", "UNDER_REVIEW"}:
            calculations.recompute_application_composite(app)


# ---------------------------------------------------------------- Application: submit
def submit_application(app: dict, caller_user_id: str):
    if app["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Application is not in DRAFT state")
    school = db.schools[app["school_id"]]
    # owner check (priority 4) happens at route layer before this.

    # priority 6: deadline
    clock = db.system_clock["current_utc"]
    if clock > school["deadline_iso"]:
        raise APIError(ERR_DEADLINE_PASSED, 409, "Deadline has passed")

    # priority 7: ED exclusivity
    if school["admission_track"] == "EARLY_DECISION":
        for other in db.applications.values():
            if other["id"] == app["id"]:
                continue
            if other["applicant_id"] != app["applicant_id"]:
                continue
            if other.get("admission_track_snapshot") == "EARLY_DECISION" and other["status"] in ED_LIVE_STATUSES:
                raise APIError(ERR_ED_EXCLUSIVITY_VIOLATED, 409,
                               "Another ED application is already live")

    # priority 8: completeness — essays all completed, >=2 SUBMITTED recs for (applicant, school),
    # FinancialAidProfile exists for this applicant
    essays_for_app = [e for e in db.essays.values() if e["application_id"] == app["id"]]
    if not all(e["completed"] for e in essays_for_app):
        raise APIError(ERR_APPLICATION_INCOMPLETE, 422, "Not all essays completed")
    submitted_recs = [
        r for r in db.recommendation_requests.values()
        if r["applicant_id"] == app["applicant_id"]
        and r["school_id"] == app["school_id"]
        and r["status"] == "SUBMITTED"
    ]
    if len(submitted_recs) < 2:
        raise APIError(ERR_APPLICATION_INCOMPLETE, 422,
                       "At least 2 submitted recommendations required")
    has_fap = any(p["applicant_id"] == app["applicant_id"] for p in db.financial_aid_profiles.values())
    if not has_fap:
        raise APIError(ERR_APPLICATION_INCOMPLETE, 422, "FinancialAidProfile required")

    # Side effects
    app["status"] = "SUBMITTED"
    app["admission_track_snapshot"] = school["admission_track"]
    app["submitted_at"] = db.system_clock["current_utc"]
    touch(app)
    # composite score
    calculations.recompute_application_composite(app)
    # applicant counters + lock
    applicant = db.applicants[app["applicant_id"]]
    applicant["submitted_application_count"] += 1
    _maybe_lock_applicant(applicant)


# ---------------------------------------------------------------- Application: withdraw
def withdraw_application(app: dict):
    if app["status"] not in {"DRAFT", "SUBMITTED"}:
        raise APIError(ERR_INVALID_STATE, 409, "Cannot withdraw from this state")
    prev = app["status"]
    app["status"] = "WITHDRAWN"
    touch(app)
    if prev == "SUBMITTED":
        applicant = db.applicants[app["applicant_id"]]
        applicant["submitted_application_count"] -= 1


# ---------------------------------------------------------------- Application: begin-review
def begin_review(app: dict):
    if app["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "Application is not in SUBMITTED state")
    school = db.schools[app["school_id"]]
    if school["admission_track"] != "ROLLING":
        clock = db.system_clock["current_utc"]
        if not (clock > school["deadline_iso"]):
            raise APIError(ERR_INVALID_STATE, 409,
                           "Cannot begin review before deadline for non-rolling schools")
    app["status"] = "UNDER_REVIEW"
    touch(app)


# ---------------------------------------------------------------- Application: admit
def admit_application(app: dict, expected_version):
    # State precondition (priority 5) first
    if app["status"] != "UNDER_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "Application is not in UNDER_REVIEW state")
    # OCC (priority 15)
    if expected_version is None or not isinstance(expected_version, int):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_application_version required")
    if expected_version != app["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "expected_application_version is stale")
    school = db.schools[app["school_id"]]
    app["status"] = "ADMITTED"
    app["decision_at"] = db.system_clock["current_utc"]
    touch(app)
    _bump_school_admitted(school, +1)


# ---------------------------------------------------------------- Application: waitlist
def waitlist_application(app: dict):
    if app["status"] != "UNDER_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "Application is not in UNDER_REVIEW state")
    if app.get("admission_track_snapshot") == "EARLY_DECISION":
        raise APIError(ERR_INVALID_STATE, 409, "ED applications cannot be waitlisted")
    school = db.schools[app["school_id"]]
    app["status"] = "WAITLISTED"
    app["decision_at"] = db.system_clock["current_utc"]
    touch(app)

    # Create WaitlistEntry; rank = next unused per school, ordered by existing PENDING entries
    # We compute rank as (count of PENDING entries for school) + 1 -- but the PRD says rank is
    # determined by (composite_score DESC, submitted_at ASC) "among already PENDING entries".
    # Interpretation: rank is the position this new app would have when sorted by that key.
    # The PRD states "next unused integer", "ranks are stable and never renumbered". So new
    # entries get monotonically increasing ranks (next unused), not interleaved.
    # Reading the scaffold: "rank := next unused rank for the school ordered by
    # (composite_score DESC, submitted_at ASC) among already PENDING entries"
    # The "ordered by" qualifier is ambiguous. Simplest interpretation that satisfies "stable,
    # never renumbered" and "next unused": rank = max(existing rank for school) + 1.
    existing_ranks = [
        we["rank"] for we in db.waitlist_entries.values()
        if db.applications[we["application_id"]]["school_id"] == school["id"]
    ]
    next_rank = (max(existing_ranks) + 1) if existing_ranks else 1
    we = {
        **_we_common(),
        "application_id": app["id"],
        "rank": next_rank,
        "status": "PENDING",
        "promoted_at": None,
    }
    db.waitlist_entries[we["id"]] = we


def _we_common():
    from services.common import new_common_fields
    return new_common_fields()


# ---------------------------------------------------------------- Application: deny
def deny_application(app: dict):
    if app["status"] != "UNDER_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "Application is not in UNDER_REVIEW state")
    school = db.schools[app["school_id"]]
    app["status"] = "DENIED"
    app["decision_at"] = db.system_clock["current_utc"]
    touch(app)
    _bump_school_simple(school, "denied_count", +1)
    # cascade: linked FINALIZED AidPackage → REVOKED
    _cascade_aid_package_revoke(app["id"])


def _cascade_aid_package_revoke(application_id: str):
    for ap in db.aid_packages.values():
        if ap["application_id"] == application_id and ap["status"] == "FINALIZED":
            ap["status"] = "REVOKED"
            touch(ap)


def _cascade_waitlist_release(application_id: str):
    for we in db.waitlist_entries.values():
        if we["application_id"] == application_id and we["status"] == "PENDING":
            we["status"] = "RELEASED"
            touch(we)


# ---------------------------------------------------------------- Application: enroll
def enroll_application(app: dict):
    if app["status"] != "ADMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "Application is not in ADMITTED state")
    # priority 9.5: no other ENROLLED app for this applicant
    for other in db.applications.values():
        if other["id"] == app["id"]:
            continue
        if other["applicant_id"] == app["applicant_id"] and other["status"] == "ENROLLED":
            raise APIError(ERR_ENROLLMENT_ALREADY_DECLARED, 409,
                           "Applicant is already ENROLLED elsewhere")
    # AidPackage must be FINALIZED for this app
    has_finalized_aid = any(
        ap["application_id"] == app["id"] and ap["status"] == "FINALIZED"
        for ap in db.aid_packages.values()
    )
    if not has_finalized_aid:
        raise APIError(ERR_INVALID_STATE, 409, "FINALIZED AidPackage required to enroll")

    school = db.schools[app["school_id"]]
    app["status"] = "ENROLLED"
    app["enrollment_decision_at"] = db.system_clock["current_utc"]
    touch(app)
    # school: -1 admitted, +1 enrolled, recompute posture (recompute_yield_posture inside the helpers)
    school["admitted_count"] -= 1
    school["enrolled_count"] += 1
    calculations.recompute_yield_posture(school)
    touch(school)

    # Cascade: every other ADMITTED / WAITLISTED app of this applicant → DECLINED
    for other in list(db.applications.values()):
        if other["id"] == app["id"]:
            continue
        if other["applicant_id"] != app["applicant_id"]:
            continue
        if other["status"] in {"ADMITTED", "WAITLISTED"}:
            _cascade_decline(other)


def _cascade_decline(other_app: dict):
    """Cascaded decline. Fires full side-effects."""
    src = other_app["status"]
    other_school = db.schools[other_app["school_id"]]
    other_app["status"] = "DECLINED"
    other_app["enrollment_decision_at"] = db.system_clock["current_utc"]
    touch(other_app)
    other_school["declined_count"] += 1
    if src == "ADMITTED":
        other_school["admitted_count"] -= 1
        calculations.recompute_yield_posture(other_school)
    touch(other_school)
    # cascade aid package
    _cascade_aid_package_revoke(other_app["id"])
    # cascade waitlist release if it was WAITLISTED
    if src == "WAITLISTED":
        _cascade_waitlist_release(other_app["id"])


# ---------------------------------------------------------------- Application: decline
def decline_application(app: dict):
    if app["status"] not in {"ADMITTED", "WAITLISTED"}:
        raise APIError(ERR_INVALID_STATE, 409, "Cannot decline from this state")
    # priority 9: ED binding violation when source was ADMITTED
    if app["status"] == "ADMITTED" and app.get("admission_track_snapshot") == "EARLY_DECISION":
        raise APIError(ERR_ED_BINDING_VIOLATION, 409, "ED admit is binding; cannot decline")
    src = app["status"]
    school = db.schools[app["school_id"]]
    app["status"] = "DECLINED"
    app["enrollment_decision_at"] = db.system_clock["current_utc"]
    touch(app)
    school["declined_count"] += 1
    if src == "ADMITTED":
        school["admitted_count"] -= 1
        calculations.recompute_yield_posture(school)
        _cascade_aid_package_revoke(app["id"])
    else:  # WAITLISTED
        _cascade_waitlist_release(app["id"])
    touch(school)


# ---------------------------------------------------------------- Waitlist promote
def waitlist_promote(school: dict):
    # yield_posture must be OPEN (priority 11)
    if school["yield_posture"] != "OPEN":
        raise APIError(ERR_YIELD_TARGET_REACHED, 409,
                       "School yield_posture is not OPEN")
    # Find lowest-rank PENDING entry for the school
    candidate = None
    for we in db.waitlist_entries.values():
        if we["status"] != "PENDING":
            continue
        app = db.applications.get(we["application_id"])
        if not app:
            continue
        if app["school_id"] != school["id"]:
            continue
        if candidate is None or we["rank"] < candidate["rank"]:
            candidate = we
    if candidate is None:
        raise APIError(ERR_INVALID_STATE, 409, "No PENDING waitlist entries for this school")
    app = db.applications[candidate["application_id"]]
    if app["status"] != "WAITLISTED":
        raise APIError(ERR_INVALID_STATE, 409, "Application is not WAITLISTED")
    # Transition
    app["status"] = "ADMITTED"
    app["decision_at"] = db.system_clock["current_utc"]
    touch(app)
    candidate["status"] = "PROMOTED"
    candidate["promoted_at"] = db.system_clock["current_utc"]
    touch(candidate)
    school["admitted_count"] += 1
    calculations.recompute_yield_posture(school)
    touch(school)
    return app


# ---------------------------------------------------------------- RecommendationRequest
def rec_submit(rr: dict, rating):
    if rr["status"] != "INVITED":
        raise APIError(ERR_INVALID_STATE, 409, "Recommendation is not in INVITED state")
    if not isinstance(rating, int) or rating < 1 or rating > 5 or isinstance(rating, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "rating must be integer in [1,5]")
    rr["status"] = "SUBMITTED"
    rr["submitted_at"] = db.system_clock["current_utc"]
    rr["rating"] = rating
    touch(rr)
    # PRD §2.7 / §2.8: a cascaded composite_score recompute is a server-acknowledged
    # mutation of the Application row, so its version is bumped exactly once.
    for app in db.applications.values():
        if (
            app["applicant_id"] == rr["applicant_id"]
            and app["school_id"] == rr["school_id"]
            and app["status"] in {"SUBMITTED", "UNDER_REVIEW"}
        ):
            calculations.recompute_application_composite(app)
            touch(app)


def rec_waive(rr: dict):
    if rr["status"] != "INVITED":
        raise APIError(ERR_INVALID_STATE, 409, "Recommendation is not in INVITED state")
    # cannot waive if matching app in those statuses
    for app in db.applications.values():
        if (
            app["applicant_id"] == rr["applicant_id"]
            and app["school_id"] == rr["school_id"]
            and app["status"] in {"SUBMITTED", "UNDER_REVIEW", "ADMITTED", "WAITLISTED", "ENROLLED"}
        ):
            raise APIError(ERR_INVALID_STATE, 409,
                           "Cannot waive: associated application is live")
    rr["status"] = "WAIVED"
    touch(rr)


# ---------------------------------------------------------------- AidPackage finalize
def aid_finalize(ap: dict):
    if ap["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "AidPackage is not in DRAFT state")
    app = db.applications.get(ap["application_id"])
    if app is None or app["status"] != "ADMITTED":
        raise APIError(ERR_INVALID_STATE, 409,
                       "Linked Application is not in ADMITTED state")
    # FinancialAidProfile must exist
    applicant_id = app["applicant_id"]
    has_fap = any(p["applicant_id"] == applicant_id for p in db.financial_aid_profiles.values())
    if not has_fap:
        raise APIError(ERR_INVALID_STATE, 409,
                       "FinancialAidProfile required for the linked applicant")
    # priority 10: aid <= residency tuition
    school = db.schools[app["school_id"]]
    applicant = db.applicants[applicant_id]
    residency = applicant["residency"]
    if residency == "IN_STATE":
        cap = school["in_state_tuition_cents"]
    elif residency == "OUT_OF_STATE":
        cap = school["out_of_state_tuition_cents"]
    else:
        cap = school["international_tuition_cents"]
    total = ap["grant_cents"] + ap["loan_cents"] + ap["work_study_cents"]
    if total > cap:
        raise APIError(ERR_AID_EXCEEDS_TUITION, 422,
                       "Aid package exceeds residency-appropriate tuition")
    ap["status"] = "FINALIZED"
    ap["net_cost_cents"] = calculations.net_cost_calc(ap)
    touch(ap)
    # recompute composite if app currently ADMITTED
    if app["status"] == "ADMITTED":
        calculations.recompute_application_composite(app)
