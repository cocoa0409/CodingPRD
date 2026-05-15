"""Business logic engine: state machines, cascades, score updates."""
from __future__ import annotations

from decimal import Decimal

from core.clock import clock
from core.errors import raise_error
from core.store import store
from services import calculations as calc
from services.time_utils import add_days, parse_iso, whole_days_between


# ---------------------------------------------------------------------------
# Lookup helpers (raise the correct error on miss)
# ---------------------------------------------------------------------------
def get_applicant(applicant_id: str) -> dict:
    rec = store.applicants.get(applicant_id)
    if rec is None:
        raise_error("ERR_APPLICANT_NOT_FOUND")
    return rec


def get_university(university_id: str) -> dict:
    rec = store.universities.get(university_id)
    if rec is None:
        raise_error("ERR_UNIVERSITY_NOT_FOUND")
    return rec


def get_program(program_id: str) -> dict:
    rec = store.programs.get(program_id)
    if rec is None:
        raise_error("ERR_PROGRAM_NOT_FOUND")
    return rec


def get_application(application_id: str) -> dict:
    rec = store.applications.get(application_id)
    if rec is None:
        raise_error("ERR_APPLICATION_NOT_FOUND")
    return rec


def get_essay(essay_id: str) -> dict:
    rec = store.essays.get(essay_id)
    if rec is None:
        raise_error("ERR_RESOURCE_NOT_FOUND")
    return rec


def get_recommendation(rec_id: str) -> dict:
    rec = store.recommendations.get(rec_id)
    if rec is None:
        raise_error("ERR_RESOURCE_NOT_FOUND")
    return rec


def get_aid(aid_id: str) -> dict:
    rec = store.aid_packages.get(aid_id)
    if rec is None:
        raise_error("ERR_RESOURCE_NOT_FOUND")
    return rec


def get_waitlist(wl_id: str) -> dict:
    rec = store.waitlist_entries.get(wl_id)
    if rec is None:
        raise_error("ERR_RESOURCE_NOT_FOUND")
    return rec


# ---------------------------------------------------------------------------
# OCC helper
# ---------------------------------------------------------------------------
def check_version(record: dict, supplied_version) -> None:
    if supplied_version is None:
        return
    if not isinstance(supplied_version, int) or isinstance(supplied_version, bool):
        raise_error("ERR_VALIDATION", "version must be an integer.")
    if int(supplied_version) != int(record["version"]):
        raise_error("ERR_VERSION_CONFLICT")


# ---------------------------------------------------------------------------
# Essay scoring helpers
# ---------------------------------------------------------------------------
def _variant_for_application(app: dict) -> str:
    status = app["status"]
    if status == "DRAFT":
        return "draft"
    if status in {"SUBMITTED", "UNDER_REVIEW", "ADMITTED", "WAITLISTED"}:
        return "final"
    # WITHDRAWN/REJECTED/ENROLLED — leave as-is (no recomputation)
    return ""


def recompute_essay_score(essay: dict) -> None:
    """Recompute the linked essay's customization_score for the current application status."""
    app = store.applications.get(essay["application_id"])
    if app is None:
        return
    variant = _variant_for_application(app)
    if not variant:
        return  # excluded statuses: WITHDRAWN, REJECTED, ENROLLED
    program = store.programs.get(app["program_id"])
    if program is None:
        return
    university = store.universities.get(program["university_id"])
    if university is None:
        return
    score = calc.compute_customization_score(
        body=essay.get("body", ""),
        prompt_code=essay.get("prompt_code", ""),
        university_name=university.get("name", ""),
        program_name=program.get("name", ""),
        university_id=university["id"],
        variant=variant,
    )
    essay["customization_score"] = score
    essay["word_count"] = len(calc.whitespace_tokens(essay.get("body", "")))


def refresh_application_essay(app: dict) -> None:
    """If the application has an essay, recompute its score for the new application status."""
    essay_id = app.get("essay_id")
    if not essay_id:
        return
    essay = store.essays.get(essay_id)
    if essay is None:
        return
    recompute_essay_score(essay)


# ---------------------------------------------------------------------------
# Waitlist rank
# ---------------------------------------------------------------------------
def _demonstrated_interest(applicant_id: str, university_id: str) -> int:
    counted_statuses = {"SUBMITTED", "UNDER_REVIEW", "ADMITTED", "WAITLISTED", "ENROLLED"}
    distinct_apps = 0
    for app in store.applications.values():
        if app["applicant_id"] != applicant_id:
            continue
        if app["status"] not in counted_statuses:
            continue
        program = store.programs.get(app["program_id"])
        if program is None or program["university_id"] != university_id:
            continue
        distinct_apps += 1
    return distinct_apps


def recompute_rank_score(entry: dict) -> None:
    app = store.applications.get(entry["application_id"])
    if app is None:
        return
    program = store.programs.get(entry["program_id"])
    if program is None:
        return
    applicant = store.applicants.get(app["applicant_id"])
    if applicant is None:
        return
    essay = store.essays.get(app.get("essay_id")) if app.get("essay_id") else None
    cs = essay.get("customization_score") if essay else Decimal("0")
    if cs is None:
        cs = Decimal("0")
    gpa = applicant.get("high_school_gpa", 0)
    days = whole_days_between(clock.iso(), entry["created_at"])
    interest = _demonstrated_interest(app["applicant_id"], program["university_id"])
    entry["rank_score"] = calc.compute_rank_score(gpa, cs, days, interest)


# ---------------------------------------------------------------------------
# Aid package cascades
# ---------------------------------------------------------------------------
def cascade_revoke_aid_for_application(application_id: str) -> None:
    for pkg in store.aid_packages.values():
        if pkg["application_id"] != application_id:
            continue
        if pkg["status"] in {"REQUESTED", "OFFERED"}:
            pkg["status"] = "REVOKED"
            store.bump(pkg)


def cascade_release_waitlist_for_application(application_id: str) -> None:
    for entry in store.waitlist_entries.values():
        if entry["application_id"] != application_id:
            continue
        if entry["status"] in {"ACTIVE", "OFFERED"}:
            # If OFFERED, revert the provisional admitted_count reservation.
            if entry["status"] == "OFFERED":
                program = store.programs.get(entry["program_id"])
                if program is not None and program.get("admitted_count", 0) > 0:
                    program["admitted_count"] = program["admitted_count"] - 1
                    store.bump(program)
            entry["status"] = "RELEASED"
            entry["offered_at"] = None
            entry["offer_expires_at"] = None
            store.bump(entry)


# ---------------------------------------------------------------------------
# Application state transitions
# ---------------------------------------------------------------------------
def _enrollment_deadline_for(app: dict, decision_iso: str) -> str:
    days = 14 if app["round"] == "EARLY_DECISION" else 30
    return add_days(decision_iso, days)


def app_transition_to_admitted(app: dict, system: bool = False) -> None:
    """Apply the side effects of moving an application into ADMITTED (used by decide+waitlist accept)."""
    now = clock.iso()
    app["status"] = "ADMITTED"
    app["admission_decision_at"] = now
    app["enrollment_deadline"] = _enrollment_deadline_for(app, now)
    program = get_program(app["program_id"])
    program["admitted_count"] = program.get("admitted_count", 0) + 1
    store.bump(program)
    store.bump(app)


def cascade_ed_admit_other_applications(applicant_id: str, except_id: str) -> None:
    """When this applicant has an ED admit, withdraw all their other in-flight applications."""
    for other in list(store.applications.values()):
        if other["id"] == except_id:
            continue
        if other["applicant_id"] != applicant_id:
            continue
        if other["status"] in {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "WAITLISTED", "ADMITTED"}:
            _withdraw_application(other, clear_ed_for_self=False)


def _withdraw_application(app: dict, clear_ed_for_self: bool) -> None:
    """Move an application to WITHDRAWN and run cascades; idempotent on terminal states."""
    if app["status"] in {"WITHDRAWN", "REJECTED", "ENROLLED"}:
        return
    prior_status = app["status"]
    if prior_status in {"ADMITTED"}:
        program = store.programs.get(app["program_id"])
        if program is not None and program.get("admitted_count", 0) > 0:
            program["admitted_count"] = program["admitted_count"] - 1
            store.bump(program)
    app["status"] = "WITHDRAWN"
    store.bump(app)
    # If this app was an ED commitment for its applicant, optionally clear it.
    if clear_ed_for_self and app["round"] == "EARLY_DECISION":
        applicant = store.applicants.get(app["applicant_id"])
        if applicant is not None and applicant.get("ed_commitment_application_id") == app["id"]:
            applicant["ed_commitment_application_id"] = None
            store.bump(applicant)
    # Cascade hop 2/3
    cascade_release_waitlist_for_application(app["id"])
    cascade_revoke_aid_for_application(app["id"])


# ---------------------------------------------------------------------------
# Recommendation expiry sweep — invoked opportunistically on reads/mutations.
# Spec describes auto-expiry but no explicit endpoint; we evaluate on touch.
# ---------------------------------------------------------------------------
def auto_expire_recommendations() -> None:
    now = clock.iso()
    for rec in store.recommendations.values():
        if rec["status"] in {"REQUESTED", "ACCEPTED"}:
            exp = rec.get("invitation_expires_at")
            if exp and parse_iso(now) > parse_iso(exp):
                rec["status"] = "EXPIRED"
                store.bump(rec)
