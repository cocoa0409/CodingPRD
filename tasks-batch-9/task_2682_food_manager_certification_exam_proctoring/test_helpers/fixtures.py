"""Composite setup helpers.

The harness relaunches the API server before every individual test, so every
fixture here builds its preconditions from scratch through PRD endpoints only.
Ownership-gated calls always thread the acting entity's own id into the
X-User-ID header via the make_*_headers builders.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_candidate_headers,
    make_health_officer_headers,
    make_proctor_headers,
    make_provider_admin_headers,
)

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

# A comfortable default sitting slot: well past the 1,440-minute lead-time floor
# measured from the clock's 2026-08-01T00:00:00Z default.
DEFAULT_SESSION_START = "2026-09-10T09:00:00Z"


def parse_iso(value: str) -> datetime:
    """Accept both the compact Z form and the three-fractional-digit form."""
    cleaned = value.replace("Z", "")
    if "." in cleaned:
        return datetime.strptime(cleaned, "%Y-%m-%dT%H:%M:%S.%f")
    return datetime.strptime(cleaned, "%Y-%m-%dT%H:%M:%S")


def iso(moment: datetime) -> str:
    return moment.strftime(ISO_FMT)


def shift_iso(value: str, days: int = 0, hours: int = 0, minutes: int = 0,
              seconds: int = 0) -> str:
    return iso(parse_iso(value) + timedelta(days=days, hours=hours,
                                            minutes=minutes, seconds=seconds))


def set_clock(to_iso8601: str, headers=None) -> str:
    """Pin the logical clock; answers an object whose single field is current_utc."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    data = get_success_data(api_client.set_clock(to_iso8601, headers))
    return data["current_utc"]


# --- Tier 1: the accreditation landscape ---------------------------------


def setup_landscape(prepay_cents: int = TEST_DEFAULTS["PREPAY_CENTS"],
                    jurisdiction=None, provider=None, exam_form=None,
                    testing_site=None, with_site: bool = True) -> dict:
    """Jurisdiction + provider (optionally prepaid) + exam form + testing site.

    Returns an environment dict reused by every richer fixture below.
    """
    admin = TEST_USERS["platform_admin_headers"]
    jur = get_success_data(api_client.create_jurisdiction(
        f.create_jurisdiction_payload(**(jurisdiction or {})), admin))
    prov = get_success_data(api_client.create_training_provider(
        f.create_training_provider_payload(jur["id"], **(provider or {})), admin))
    if prepay_cents:
        prov = get_success_data(api_client.create_credit_adjustment(
            prov["id"], f.create_credit_adjustment_payload(amount_cents=prepay_cents), admin))
    form = get_success_data(api_client.create_exam_form(
        f.create_exam_form_payload(**(exam_form or {})), admin))
    site = None
    if with_site:
        site = get_success_data(api_client.create_testing_site(
            f.create_testing_site_payload(jur["id"], **(testing_site or {})), admin))
    return {
        "admin_headers": admin,
        "jurisdiction": jur,
        "provider": prov,
        "provider_headers": make_provider_admin_headers(prov["id"]),
        "officer_headers": make_health_officer_headers(jur["id"]),
        "exam_form": form,
        "testing_site": site,
    }


def add_jurisdiction(env: dict, **overrides) -> dict:
    return get_success_data(api_client.create_jurisdiction(
        f.create_jurisdiction_payload(**overrides), env["admin_headers"]))


def add_provider(env: dict, jurisdiction_id: str = None,
                 prepay_cents: int = 0, **overrides) -> dict:
    prov = get_success_data(api_client.create_training_provider(
        f.create_training_provider_payload(
            jurisdiction_id or env["jurisdiction"]["id"], **overrides),
        env["admin_headers"]))
    if prepay_cents:
        prov = get_success_data(api_client.create_credit_adjustment(
            prov["id"], f.create_credit_adjustment_payload(amount_cents=prepay_cents),
            env["admin_headers"]))
    return prov


def add_exam_form(env: dict, **overrides) -> dict:
    return get_success_data(api_client.create_exam_form(
        f.create_exam_form_payload(**overrides), env["admin_headers"]))


def add_testing_site(env: dict, **overrides) -> dict:
    return get_success_data(api_client.create_testing_site(
        f.create_testing_site_payload(env["jurisdiction"]["id"], **overrides),
        env["admin_headers"]))


def add_candidate(env: dict, provider: dict = None, jurisdiction_id: str = None,
                  **overrides) -> dict:
    """Enrolled by the owning ProviderAdmin, so the header carries the provider id."""
    prov = provider or env["provider"]
    payload = f.create_candidate_payload(
        prov["id"], jurisdiction_id or env["jurisdiction"]["id"], **overrides)
    return get_success_data(api_client.create_candidate(
        payload, make_provider_admin_headers(prov["id"])))


def add_proctor(env: dict, provider: dict = None, registered: bool = True,
                **overrides) -> dict:
    """Register a proctor and, by default, have a PlatformAdmin APPROVE it."""
    prov = provider or env["provider"]
    proctor = get_success_data(api_client.create_proctor(
        f.create_proctor_payload(prov["id"], **overrides),
        make_provider_admin_headers(prov["id"])))
    if registered:
        proctor = get_success_data(api_client.decide_proctor_registration(
            proctor["id"], f.create_registration_decision_payload("APPROVE"),
            env["admin_headers"]))
    return proctor


# --- Tier 2: access-code inventory ---------------------------------------


def purchase_batch(env: dict, line_items=None, expires_at: str = "2027-01-01T00:00:00Z",
                   exam_form_id: str = None, provider: dict = None, **overrides) -> dict:
    prov = provider or env["provider"]
    payload = f.create_access_code_batch_payload(
        prov["id"], exam_form_id or env["exam_form"]["id"],
        line_items=line_items, expires_at=expires_at, **overrides)
    return get_success_data(api_client.create_access_code_batch(
        payload, make_provider_admin_headers(prov["id"])))


def read_batch(env: dict, batch_id: str, provider: dict = None) -> dict:
    prov = provider or env["provider"]
    return get_success_data(api_client.get_access_code_batch(
        batch_id, make_provider_admin_headers(prov["id"])))


def assign_code(env: dict, batch: dict, candidate: dict,
                bundle_type: str = "EXAM_ONLY", provider: dict = None,
                expected_batch_version: int = None):
    """Assign one AVAILABLE code of the requested bundle_type to a candidate.

    Returns (code, refreshed_batch) so callers always hold a fresh version for
    the next version-guarded write.
    """
    prov = provider or env["provider"]
    headers = make_provider_admin_headers(prov["id"])
    version = expected_batch_version if expected_batch_version is not None else batch["version"]
    code = get_success_data(api_client.assign_access_code(
        batch["id"], f.create_assignment_payload(candidate["id"], version, bundle_type),
        headers))
    fresh = get_success_data(api_client.get_access_code_batch(batch["id"], headers))
    return code, fresh


def sign_off_course(env: dict, code: dict, instructor: dict, provider: dict = None) -> dict:
    prov = provider or env["provider"]
    return get_success_data(api_client.complete_course(
        code["id"], f.create_course_completion_payload(instructor["id"]),
        make_provider_admin_headers(prov["id"])))


def setup_assigned_code(env: dict = None, bundle_type: str = "EXAM_ONLY",
                        quantity: int = 1, candidate: dict = None,
                        expires_at: str = "2027-01-01T00:00:00Z") -> dict:
    """Landscape + candidate + batch + one ASSIGNED code ready to be redeemed."""
    env = env or setup_landscape()
    cand = candidate or add_candidate(env)
    batch = purchase_batch(
        env, line_items=[{"bundle_type": bundle_type, "quantity": quantity}],
        expires_at=expires_at)
    code, batch = assign_code(env, batch, cand, bundle_type=bundle_type)
    env = dict(env)
    env.update({"candidate": cand, "batch": batch, "access_code": code})
    return env


# --- Tier 3: the sitting lifecycle ---------------------------------------


def schedule_session(env: dict, candidate: dict, code: dict, start_at: str,
                     proctor: dict = None, delivery_mode: str = "IN_PERSON",
                     testing_site: dict = "default", provider: dict = None,
                     **overrides) -> dict:
    prov = provider or env["provider"]
    payload = f.create_exam_session_payload(
        candidate["id"], overrides.pop("exam_form_id", env["exam_form"]["id"]),
        code["id"], start_at, delivery_mode=delivery_mode)
    if delivery_mode == "IN_PERSON":
        site = env["testing_site"] if testing_site == "default" else testing_site
        if site is not None:
            payload["testing_site_id"] = site["id"]
    if proctor is not None:
        payload["proctor_id"] = proctor["id"]
    payload.update(overrides)
    return get_success_data(api_client.create_exam_session(
        payload, make_provider_admin_headers(prov["id"])))


def check_in_session(env: dict, session: dict, proctor: dict,
                     at_clock: str = None, **overrides) -> dict:
    """Pin the clock inside the check-in window, then verify identity."""
    set_clock(at_clock or session["scheduled_start_at"], env["admin_headers"])
    payload = f.create_check_in_payload(**overrides)
    return get_success_data(api_client.check_in_exam_session(
        session["id"], payload, make_proctor_headers(proctor["id"])))


def start_session(env: dict, session: dict, proctor: dict) -> dict:
    return get_success_data(api_client.start_exam_session(
        session["id"], make_proctor_headers(proctor["id"])))


def submit_session(env: dict, session: dict, proctor: dict,
                   scored_correct_count: int = 60, **overrides) -> dict:
    """Answers the freshly minted PROVISIONAL score report."""
    payload = f.create_submission_payload(scored_correct_count, **overrides)
    return get_success_data(api_client.submit_exam_session(
        session["id"], payload, make_proctor_headers(proctor["id"])))


def finalize_report(env: dict, report: dict, admin_headers=None, **overrides) -> dict:
    return get_success_data(api_client.finalize_score_report(
        report["id"], f.create_finalization_payload(**overrides),
        admin_headers or TEST_USERS["scoring_admin_headers"]))


def issue_certificate(env: dict, report: dict, admin_headers=None) -> dict:
    return get_success_data(api_client.create_certificate(
        f.create_certificate_payload(report["id"]),
        admin_headers or env["admin_headers"]))


def file_local_registration(env: dict, certificate: dict, provider: dict = None,
                            **overrides) -> dict:
    prov = provider or env["provider"]
    return get_success_data(api_client.create_local_registration(
        f.create_local_registration_payload(certificate["id"], **overrides),
        make_provider_admin_headers(prov["id"])))


_STAGES = [
    "SCHEDULED", "CHECKED_IN", "IN_PROGRESS", "SUBMITTED",
    "CLOSED", "CERTIFIED", "FILED", "POSTED", "VERIFIED",
]


def setup_sitting(stage: str = "SCHEDULED", env: dict = None,
                  start_at: str = DEFAULT_SESSION_START,
                  delivery_mode: str = "IN_PERSON", bundle_type: str = "EXAM_ONLY",
                  scored_correct_count: int = 60, with_proctor: bool = True,
                  candidate: dict = None, proctor: dict = None,
                  quantity: int = 1, auto_sign_off: bool = True,
                  checkin_overrides: dict = None, finalize_overrides: dict = None,
                  scoring_admin_headers=None, session_overrides: dict = None,
                  expires_at: str = "2027-01-01T00:00:00Z") -> dict:
    """Walk one sitting as far as `stage` and return the whole environment.

    Stages, in order: SCHEDULED, CHECKED_IN, IN_PROGRESS, SUBMITTED, CLOSED,
    CERTIFIED, FILED, POSTED, VERIFIED.
    """
    assert stage in _STAGES, f"unknown stage {stage!r}"
    target = _STAGES.index(stage)

    env = dict(env or setup_landscape())
    cand = candidate or env.get("candidate") or add_candidate(env)
    proc = proctor or env.get("proctor") or add_proctor(env)
    batch = purchase_batch(
        env, line_items=[{"bundle_type": bundle_type, "quantity": quantity}],
        expires_at=expires_at)
    code, batch = assign_code(env, batch, cand, bundle_type=bundle_type)
    if bundle_type == "COURSE_PLUS_EXAM" and auto_sign_off:
        code = sign_off_course(env, code, proc)

    session = schedule_session(
        env, cand, code, start_at,
        proctor=proc if with_proctor else None,
        delivery_mode=delivery_mode,
        testing_site="default" if delivery_mode == "IN_PERSON" else None,
        **(session_overrides or {}))

    env.update({"candidate": cand, "candidate_headers": make_candidate_headers(cand["id"]),
                "proctor": proctor or proc, "proctor_headers": make_proctor_headers(proc["id"]),
                "batch": batch, "access_code": code, "session": session})

    if target >= _STAGES.index("CHECKED_IN"):
        overrides = dict(checkin_overrides or {})
        if delivery_mode == "REMOTE" and "biometric_match_score" not in overrides:
            overrides["biometric_match_score"] = 95
        session = check_in_session(env, session, proc, **overrides)
        env["session"] = session

    if target >= _STAGES.index("IN_PROGRESS"):
        session = start_session(env, session, proc)
        env["session"] = session

    if target >= _STAGES.index("SUBMITTED"):
        report = submit_session(env, session, proc,
                               scored_correct_count=scored_correct_count)
        env["score_report"] = report
        env["session"] = get_success_data(api_client.get_exam_session(
            session["id"], env["admin_headers"]))

    if target >= _STAGES.index("CLOSED"):
        env["score_report"] = finalize_report(
            env, env["score_report"],
            admin_headers=scoring_admin_headers,
            **(finalize_overrides or {}))
        env["session"] = get_success_data(api_client.get_exam_session(
            session["id"], env["admin_headers"]))

    if target >= _STAGES.index("CERTIFIED"):
        env["certificate"] = issue_certificate(env, env["score_report"])

    if target >= _STAGES.index("FILED"):
        env["local_registration"] = file_local_registration(env, env["certificate"])

    if target >= _STAGES.index("POSTED"):
        env["local_registration"] = get_success_data(api_client.confirm_posting(
            env["local_registration"]["id"], f.create_posting_confirmation_payload(),
            env["provider_headers"]))

    if target >= _STAGES.index("VERIFIED"):
        env["local_registration"] = get_success_data(api_client.verify_local_registration(
            env["local_registration"]["id"], f.create_verification_payload("VERIFY"),
            env["officer_headers"]))

    # Redeeming the code at check-in mutates the batch's counters, and PRD 2.2
    # says `version` "increments by exactly 1 on every mutation of that
    # resource", so the copy captured at assignment time is stale by now. Hand
    # callers a freshly read batch so their version-guarded writes carry the
    # batch's real current version.
    env["batch"] = read_batch(env, env["batch"]["id"])
    return env


# --- Tier 4: accumulation and threshold targeting -------------------------


def setup_terminal_sittings(env: dict, proctor: dict, candidate: dict,
                            count: int = 3, first_start: str = "2026-09-10T09:00:00Z",
                            gap_minutes: int = 15, allowed_minutes: int = 120,
                            scored_correct_count: int = 60) -> list:
    """Take `count` back-to-back sittings all the way to SUBMITTED for one proctor.

    Neighbouring intervals are separated by exactly `gap_minutes`, which the
    exclusive occupancy rule permits when the gap is exactly 15 minutes.
    Returns a list of {"session", "score_report"} dicts in chronological order.
    """
    batch = purchase_batch(
        env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": count}])
    step = allowed_minutes + gap_minutes
    sittings = []
    for index in range(count):
        code, batch = assign_code(env, batch, candidate)
        start = shift_iso(first_start, minutes=step * index)
        session = schedule_session(env, candidate, code, start, proctor=proctor)
        sittings.append({"session": session, "access_code": code, "start_at": start})
    for sitting in sittings:
        session = check_in_session(env, sitting["session"], proctor)
        session = start_session(env, session, proctor)
        report = submit_session(env, session, proctor,
                               scored_correct_count=scored_correct_count)
        sitting["session"] = get_success_data(api_client.get_exam_session(
            session["id"], env["admin_headers"]))
        sitting["score_report"] = report
    # Consumption during check-in has since bumped the batch's counters and its
    # `version` (PRD 2.2), so re-read rather than reuse the assignment-time copy.
    env["batch"] = read_batch(env, batch["id"])
    return sittings


def file_incident(env: dict, session: dict, proctor: dict,
                  severity: str = "MAJOR", **overrides) -> dict:
    return get_success_data(api_client.create_security_incident(
        f.create_security_incident_payload(session["id"], proctor["id"],
                                          severity=severity, **overrides),
        make_proctor_headers(proctor["id"])))


def take_incident_into_review(env: dict, incident: dict, admin_headers=None) -> dict:
    return get_success_data(api_client.open_incident_review(
        incident["id"], admin_headers or TEST_USERS["security_admin_headers"]))


def resolve_incident(env: dict, incident: dict, outcome: str = "SUBSTANTIATE",
                     admin_headers=None, **overrides) -> dict:
    return get_success_data(api_client.resolve_security_incident(
        incident["id"], f.create_incident_resolution_payload(outcome, **overrides),
        admin_headers or TEST_USERS["security_admin_headers"]))


# --- Tier 5: incident review and terminal cascades ------------------------


def setup_incident_under_review(stage: str = "CERTIFIED", severity: str = "MAJOR",
                                env: dict = None, **kwargs) -> dict:
    """Walk a sitting to `stage`, file an incident against it and open the review.

    The score report is finalized by admin-scoring-1, so a distinct operator must
    resolve the incident to clear the segregation-of-duties comparison.
    """
    env = setup_sitting(stage=stage, env=env,
                        scoring_admin_headers=TEST_USERS["scoring_admin_headers"],
                        **kwargs)
    incident = file_incident(env, env["session"], env["proctor"], severity=severity)
    env["incident"] = take_incident_into_review(env, incident)
    env["session"] = get_success_data(api_client.get_exam_session(
        env["session"]["id"], env["admin_headers"]))
    return env


def run_compliance(env: dict = None, headers=None) -> dict:
    return get_success_data(api_client.create_compliance_run(
        headers or (env or {}).get("admin_headers") or TEST_USERS["platform_admin_headers"]))
