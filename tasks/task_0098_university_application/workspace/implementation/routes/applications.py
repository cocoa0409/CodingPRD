"""Application routes."""
from __future__ import annotations

from flask import Blueprint, g, request

from core.auth import require_roles
from core.clock import clock
from core.errors import raise_error
from core.pagination import page, parse_pagination
from core.response import success_array, success_object
from core.store import store
from services.engine import (
    _withdraw_application,
    app_transition_to_admitted,
    auto_expire_recommendations,
    cascade_ed_admit_other_applications,
    cascade_release_waitlist_for_application,
    cascade_revoke_aid_for_application,
    check_version,
    get_applicant,
    get_application,
    get_program,
    get_university,
    recompute_essay_score,
    recompute_rank_score,
    refresh_application_essay,
)
from services.serializers import application_out
from services.time_utils import parse_iso

bp = Blueprint("applications", __name__)

VALID_ROUNDS = {"EARLY_DECISION", "REGULAR_DECISION", "ROLLING"}


@bp.post("/applications")
@require_roles("Applicant")
def create_application():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    applicant_id = body.get("applicant_id")
    program_id = body.get("program_id")
    rnd = body.get("round")
    if not isinstance(applicant_id, str) or not applicant_id:
        raise_error("ERR_VALIDATION", "applicant_id is required.")
    if not isinstance(program_id, str) or not program_id:
        raise_error("ERR_VALIDATION", "program_id is required.")
    if rnd not in VALID_ROUNDS:
        raise_error("ERR_VALIDATION", "round must be one of EARLY_DECISION, REGULAR_DECISION, ROLLING.")
    rrc = body.get("required_recommendation_count", 2)
    if rrc is None:
        rrc = 2
    if not isinstance(rrc, int) or isinstance(rrc, bool) or rrc not in (2, 3):
        raise_error("ERR_VALIDATION", "required_recommendation_count must be 2 or 3.")

    # Existence after body validation? Spec orders existence before body shape, but path-only.
    # For body-referenced entities, we check after shape per typical interpretation.
    get_applicant(applicant_id)
    get_program(program_id)

    rec = store.stamp_create()
    rec.update(
        {
            "applicant_id": applicant_id,
            "program_id": program_id,
            "round": rnd,
            "status": "DRAFT",
            "essay_id": None,
            "required_recommendation_count": rrc,
            "submitted_at": None,
            "admission_decision_at": None,
            "enrollment_deadline": None,
        }
    )
    store.applications[rec["id"]] = rec
    return success_object(application_out(rec), 201)


@bp.get("/applications/<application_id>")
@require_roles("Applicant", "AdmissionsOfficer", "PlatformAdmin")
def read_application(application_id: str):
    rec = get_application(application_id)
    return success_object(application_out(rec), 200)


@bp.get("/applications")
@require_roles("Applicant", "AdmissionsOfficer", "PlatformAdmin")
def list_applications():
    limit, offset = parse_pagination()
    applicant_id = request.args.get("applicant_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    rnd = request.args.get("round")
    items = list(store.applications.values())
    if applicant_id:
        items = [a for a in items if a["applicant_id"] == applicant_id]
    if program_id:
        items = [a for a in items if a["program_id"] == program_id]
    if status:
        items = [a for a in items if a["status"] == status]
    if rnd:
        items = [a for a in items if a["round"] == rnd]
    items.sort(key=lambda a: a["created_at"])
    page_items, total = page(items, limit, offset)
    return success_array([application_out(a) for a in page_items], limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------
def _qualifying_letters_count(application_id: str) -> int:
    count = 0
    for rec in store.recommendations.values():
        if rec["application_id"] != application_id:
            continue
        if rec["status"] != "SUBMITTED":
            continue
        wc = rec.get("letter_word_count") or 0
        if wc >= 200:
            count += 1
    return count


@bp.post("/applications/<application_id>/submit")
@require_roles("Applicant")
def submit_application(application_id: str):
    app = get_application(application_id)
    body = request.get_json(silent=True) or {}
    if app["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE")
    check_version(app, body.get("version") if isinstance(body, dict) else None)

    applicant = store.applicants.get(app["applicant_id"])
    program = store.programs.get(app["program_id"])
    if applicant is None or program is None:
        raise_error("ERR_INVALID_STATE")
    university = store.universities.get(program["university_id"])
    if university is None:
        raise_error("ERR_INVALID_STATE")

    # Refresh recommendation expiry first
    auto_expire_recommendations()

    # --- Business safety / fairness gates (priority 40, 41) ---
    if app["round"] == "EARLY_DECISION":
        ed_commit = applicant.get("ed_commitment_application_id")
        if ed_commit is not None and ed_commit != app["id"]:
            raise_error("ERR_ED_ALREADY_BOUND")
        # ED deadline
        if parse_iso(clock.iso()) > parse_iso(university["early_decision_deadline"]):
            raise_error("ERR_ED_DEADLINE_PASSED")

    # --- Business referential gates (priority 50, 51) ---
    essay_id = app.get("essay_id")
    if not essay_id:
        raise_error("ERR_ESSAY_NOT_CUSTOMIZED")
    essay = store.essays.get(essay_id)
    if essay is None:
        raise_error("ERR_ESSAY_NOT_CUSTOMIZED")
    cs = essay.get("customization_score")
    from decimal import Decimal
    if cs is None or Decimal(str(cs)) < Decimal("0.30"):
        raise_error("ERR_ESSAY_NOT_CUSTOMIZED")

    qualifying = _qualifying_letters_count(application_id)
    if qualifying != app["required_recommendation_count"]:
        raise_error("ERR_INSUFFICIENT_RECOMMENDATIONS")

    # --- Round-dependent submission deadline (priority 63) ---
    if app["round"] == "REGULAR_DECISION":
        if parse_iso(clock.iso()) > parse_iso(university["regular_decision_deadline"]):
            raise_error("ERR_DEADLINE_PASSED")
    elif app["round"] == "ROLLING":
        if not university.get("rolling_admission_enabled", False):
            raise_error("ERR_DEADLINE_PASSED")

    # --- Apply transition ---
    now = clock.iso()
    app["status"] = "SUBMITTED"
    app["submitted_at"] = now
    store.bump(app)
    if app["round"] == "EARLY_DECISION":
        applicant["ed_commitment_application_id"] = app["id"]
        store.bump(applicant)
    # Essay variant flips to 'final'
    refresh_application_essay(app)
    return success_object(application_out(app), 200)


@bp.post("/applications/<application_id>/withdraw-submission")
@require_roles("Applicant")
def withdraw_submission(application_id: str):
    app = get_application(application_id)
    body = request.get_json(silent=True) or {}
    if app["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_STATE")
    check_version(app, body.get("version") if isinstance(body, dict) else None)
    # ED window check
    if app["round"] == "EARLY_DECISION":
        program = store.programs.get(app["program_id"])
        university = store.universities.get(program["university_id"]) if program else None
        if university and parse_iso(clock.iso()) > parse_iso(university["early_decision_deadline"]):
            raise_error("ERR_ED_DEADLINE_PASSED")
    app["status"] = "DRAFT"
    app["submitted_at"] = None
    if app["round"] == "EARLY_DECISION":
        applicant = store.applicants.get(app["applicant_id"])
        if applicant is not None and applicant.get("ed_commitment_application_id") == app["id"]:
            applicant["ed_commitment_application_id"] = None
            store.bump(applicant)
    store.bump(app)
    refresh_application_essay(app)
    return success_object(application_out(app), 200)


@bp.post("/applications/<application_id>/withdraw")
@require_roles("Applicant")
def withdraw_application(application_id: str):
    app = get_application(application_id)
    body = request.get_json(silent=True) or {}
    if app["status"] not in {"DRAFT", "SUBMITTED"}:
        raise_error("ERR_INVALID_STATE")
    check_version(app, body.get("version") if isinstance(body, dict) else None)
    _withdraw_application(app, clear_ed_for_self=True)
    return success_object(application_out(app), 200)


@bp.post("/applications/<application_id>/begin-review")
@require_roles("AdmissionsOfficer")
def begin_review(application_id: str):
    app = get_application(application_id)
    if app["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_STATE")
    # Officer-university scope: identify officer's university via header X-University-Id when present;
    # if not provided, accept any AdmissionsOfficer (the PRD says the check is referential — we apply
    # via X-University-Id which the officer must supply for scope enforcement).
    officer_uni = request.headers.get("X-University-Id")
    program = store.programs.get(app["program_id"])
    if program is None:
        raise_error("ERR_INVALID_STATE")
    if officer_uni and officer_uni != program["university_id"]:
        raise_error("ERR_FORBIDDEN")
    app["status"] = "UNDER_REVIEW"
    store.bump(app)
    refresh_application_essay(app)
    return success_object(application_out(app), 200)


VALID_DECISIONS = {"ADMIT", "REJECT", "WAITLIST"}


@bp.post("/applications/<application_id>/decide")
@require_roles("AdmissionsOfficer")
def decide_application(application_id: str):
    app = get_application(application_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    decision = body.get("decision")
    if decision not in VALID_DECISIONS:
        raise_error("ERR_VALIDATION", "decision must be one of ADMIT, REJECT, WAITLIST.")
    if app["status"] != "UNDER_REVIEW":
        raise_error("ERR_INVALID_STATE")

    program = store.programs.get(app["program_id"])
    if program is None:
        raise_error("ERR_INVALID_STATE")

    # Officer-university scope check (priority 42) before capacity (priority 60)
    officer_uni = request.headers.get("X-University-Id")
    if officer_uni and officer_uni != program["university_id"]:
        raise_error("ERR_FORBIDDEN")

    now = clock.iso()

    if decision == "ADMIT":
        if program.get("admitted_count", 0) + 1 > program["capacity"]:
            raise_error("ERR_PROGRAM_AT_CAPACITY")
        app_transition_to_admitted(app)
        if app["round"] == "EARLY_DECISION":
            cascade_ed_admit_other_applications(app["applicant_id"], app["id"])
    elif decision == "WAITLIST":
        app["status"] = "WAITLISTED"
        app["admission_decision_at"] = now
        store.bump(app)
        # Create the WaitlistEntry
        entry = store.stamp_create()
        entry.update(
            {
                "application_id": app["id"],
                "program_id": program["id"],
                "status": "ACTIVE",
                "rank_score": None,
                "offered_at": None,
                "offer_expires_at": None,
            }
        )
        store.waitlist_entries[entry["id"]] = entry
        refresh_application_essay(app)
        recompute_rank_score(entry)
    else:  # REJECT
        app["status"] = "REJECTED"
        app["admission_decision_at"] = now
        store.bump(app)
        # If ED binding, clear it
        if app["round"] == "EARLY_DECISION":
            applicant = store.applicants.get(app["applicant_id"])
            if applicant is not None and applicant.get("ed_commitment_application_id") == app["id"]:
                applicant["ed_commitment_application_id"] = None
                store.bump(applicant)
        # Cascade: revoke aid, release waitlist
        cascade_revoke_aid_for_application(app["id"])
        cascade_release_waitlist_for_application(app["id"])

    return success_object(application_out(app), 200)


@bp.post("/applications/<application_id>/enroll")
@require_roles("Applicant")
def enroll_application(application_id: str):
    app = get_application(application_id)
    body = request.get_json(silent=True) or {}
    if app["status"] != "ADMITTED":
        raise_error("ERR_INVALID_STATE")
    check_version(app, body.get("version") if isinstance(body, dict) else None)

    # Sweep-in-progress check
    program = store.programs.get(app["program_id"])
    if program is None:
        raise_error("ERR_INVALID_STATE")
    university_id = program["university_id"]
    sweep_lock = store.get_sweep_lock(university_id)
    if not sweep_lock.acquire(blocking=False):
        raise_error("ERR_SWEEP_IN_PROGRESS")
    try:
        # Temporal check
        if parse_iso(clock.iso()) > parse_iso(app["enrollment_deadline"]):
            raise_error("ERR_ENROLLMENT_DEADLINE_PASSED")

        # Aid package status gate
        aid = next(
            (
                p
                for p in store.aid_packages.values()
                if p["application_id"] == app["id"]
            ),
            None,
        )
        if aid is not None and aid["status"] not in {"ACCEPTED", "DECLINED"}:
            raise_error("ERR_INVALID_STATE")

        # Single-enrollment rule
        applicant_id = app["applicant_id"]
        for other in store.applications.values():
            if other["id"] == app["id"]:
                continue
            if other["applicant_id"] == applicant_id and other["status"] == "ENROLLED":
                raise_error("ERR_ALREADY_ENROLLED_ELSEWHERE")

        # Apply
        app["status"] = "ENROLLED"
        store.bump(app)
        university = store.universities.get(university_id)
        if university is not None:
            university["enrolled_count"] = university.get("enrolled_count", 0) + 1
            store.bump(university)
        # Clear ED binding if this was an ED commitment
        applicant = store.applicants.get(applicant_id)
        if applicant is not None and applicant.get("ed_commitment_application_id") == app["id"]:
            applicant["ed_commitment_application_id"] = None
            store.bump(applicant)

        # Cascade: withdraw sibling applications and release/revoke their children.
        for other in list(store.applications.values()):
            if other["id"] == app["id"]:
                continue
            if other["applicant_id"] != applicant_id:
                continue
            if other["status"] in {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "ADMITTED", "WAITLISTED"}:
                _withdraw_application(other, clear_ed_for_self=True)
    finally:
        sweep_lock.release()
    return success_object(application_out(app), 200)
