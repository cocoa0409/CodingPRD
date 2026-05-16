"""Composite setup helpers — multi-step preambles tests can reuse.

The tutoring pipeline is long: tutor create -> credential submit ->
verifier approve (x2 critical types) -> tutor VERIFIED -> subject tag
propose -> verifier approve -> subject APPROVED -> session book ->
tutor confirm -> clock advance to start_at -> IN_PROGRESS -> tutor
complete -> COMPLETED -> clock advance + 72h -> SETTLED -> payout
request/mark-paid. Many test claims need the system in a late-pipeline
state.

IDENTITY THREADING — PRD §2.1:

- Tutor is ENTITY-BACKED. Every Tutor call (confirm, complete, respond,
  counter, cancel-as-tutor, submit credential, propose subject, etc.)
  MUST mint headers via make_tutor_headers(tutor["id"]) — never via the
  shared TUTOR_FALLBACK_ID constant.

- Student is ENTITY-BACKED. Every Student call (book as ADULT, cancel,
  open dispute, accept/reopen/escalate/withdraw dispute) MUST mint
  headers via make_student_headers(student["id"]).

- Parent is ENTITY-BACKED. Every Parent call (approve/revoke link, book
  for MINOR child, cancel for MINOR child, open dispute for MINOR
  child) MUST mint headers via make_parent_headers(parent["id"]).

- CredentialVerifier, PlatformArbiter, PlatformAdmin are OPAQUE — the
  shared admin_headers / verifier_headers / arbiter_headers constants
  are canonical. PRD §3.6 (payout segregation) requires a *different*
  admin id for mark-paid vs request; use admin_headers_alt.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    SETTLEMENT_HOLD_HOURS,
    TEST_DEFAULTS,
)
from .factories import (
    arbitrate_dispute_payload,
    book_session_payload,
    clock_advance_payload,
    complete_session_payload,
    counter_dispute_payload,
    create_parent_payload,
    create_payout_payload,
    create_student_payload,
    create_tutor_payload,
    iso_offset,
    iso_utc,
    open_dispute_payload,
    parse_iso,
    propose_subject_payload,
    random_email,
    random_suffix,
    submit_credential_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_arbiter_headers,
    make_parent_headers,
    make_student_headers,
    make_tutor_headers,
    make_verifier_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.9 (PlatformAdmin only for advance; clock read open)
# ===========================================================================
def advance_clock_to(to_iso8601: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /tutoring/_clock/advance.
    PRD §3.9: PlatformAdmin only.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to_iso8601=to_iso8601), headers,
    )
    return get_success_data(resp)


def server_now_iso(headers: Optional[Dict[str, str]] = None) -> str:
    """Return the server's current virtual-clock instant as ISO 8601.

    PRD §3.9: "A read of the current virtual clock is available to
    every role." The response body's data carries the virtual clock;
    we also fall back to api_request_timestamp in meta as a sanity
    backup if data is structured unexpectedly.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.read_clock(headers)
    body = resp.json()
    data = body.get("data", {})
    # The PRD does not pin the exact field name in data — try common
    # spellings, then fall back to api_request_timestamp which the PRD
    # guarantees is server-clock-derived.
    for key in ("now", "to_iso8601", "iso8601", "current",
                "current_iso8601", "clock", "value"):
        if isinstance(data.get(key), str):
            return data[key]
    return body["meta"]["api_request_timestamp"]


def server_now_dt(headers: Optional[Dict[str, str]] = None) -> datetime:
    return parse_iso(server_now_iso(headers))


def advance_clock_by(*, hours: int = 0, days: int = 0,
                     minutes: int = 0,
                     base: Optional[datetime] = None) -> str:
    """Advance the server clock by the given amount relative to `base`
    (or the current server clock if None). Returns the new instant.
    """
    base = base or server_now_dt()
    new_dt = base + timedelta(days=days, hours=hours, minutes=minutes)
    advance_clock_to(iso_utc(new_dt))
    return iso_utc(new_dt)


def advance_clock_past_session_end(session: Dict[str, Any]) -> None:
    """Advance the virtual clock so that the given session is past its
    end_at AND has transitioned through IN_PROGRESS.

    PRD §3.5: "Every Session in CONFIRMED whose start_at is at or
    before the new clock and whose end_at is strictly later transitions
    CONFIRMED → IN_PROGRESS." A single advance straight from before
    start_at to past end_at would skip the IN_PROGRESS window, so we
    advance twice — first to a moment inside [start_at, end_at) so the
    sweep fires CONFIRMED → IN_PROGRESS, then to end_at + 1 minute so
    the tutor's complete action precondition ("current clock has
    reached end_at") holds.
    """
    start_dt = parse_iso(session["start_at"])
    end_dt = parse_iso(session["end_at"])
    now = server_now_dt()
    # Step 1: cross start_at while end_at is still strictly later, only
    # if we have not already crossed start_at.
    if now < start_dt:
        advance_clock_to(iso_utc(start_dt + timedelta(minutes=1)))
    # Step 2: cross end_at.
    advance_clock_to(iso_utc(end_dt + timedelta(minutes=1)))


# ===========================================================================
# Tier 1: Tutor + credentials + verification
# ===========================================================================
def create_tutor(
    *,
    hourly_rate_cents: int = TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    trial_rate_cents: int = TEST_DEFAULTS["TRIAL_RATE_CENTS"],
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/tutors. Returns UNVERIFIED tutor.

    PRD §4: roles PlatformAdmin or Tutor. Defaults to PlatformAdmin
    (opaque) which is always permitted.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_tutor(
        create_tutor_payload(
            display_name=display_name,
            email=email or random_email("tutor"),
            hourly_rate_cents=hourly_rate_cents,
            trial_rate_cents=trial_rate_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def submit_credential(
    *,
    tutor: Dict[str, Any],
    credential_type: str = "GOVERNMENT_ID",
    expires_at: Optional[str] = None,
    document_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /tutoring/tutors/{id}/credentials — Tutor only per PRD §4.

    Identity threading: per PRD §2.1 Tutor is entity-backed, so the
    acting tutor's id IS X-User-ID. We mint per-instance headers from
    the tutor entity.
    """
    headers = make_tutor_headers(tutor["id"])
    resp = api_client.submit_credential(
        tutor["id"],
        submit_credential_payload(
            credential_type=credential_type,
            document_ref=document_ref,
            expires_at=expires_at,
        ),
        headers,
    )
    return get_success_data(resp)


def approve_credential(
    *,
    tutor: Dict[str, Any],
    credential: Dict[str, Any],
    verifier_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/tutors/{id}/credentials/{cid}/approve —
    CredentialVerifier only per PRD §4.

    PRD §2.11: "A CredentialVerifier may not approve or reject a
    credential whose tutor_id equals their X-User-ID". The shared
    CREDENTIAL_VERIFIER_ID constant is a literal string that will
    never collide with a server-minted UUID, so it is safe here.
    """
    headers = verifier_headers or TEST_USERS["verifier_headers"]
    resp = api_client.approve_credential(
        tutor["id"], credential["id"], headers,
    )
    return get_success_data(resp)


def reject_credential(
    *,
    tutor: Dict[str, Any],
    credential: Dict[str, Any],
    verifier_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/tutors/{id}/credentials/{cid}/reject —
    CredentialVerifier only per PRD §4."""
    headers = verifier_headers or TEST_USERS["verifier_headers"]
    resp = api_client.reject_credential(
        tutor["id"], credential["id"], headers,
    )
    return get_success_data(resp)


def make_tutor_verified(
    *,
    hourly_rate_cents: int = TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    trial_rate_cents: int = TEST_DEFAULTS["TRIAL_RATE_CENTS"],
    gov_id_expires_at: Optional[str] = None,
    bg_check_expires_at: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Compose a fresh tutor through to VERIFIED.

    Submits GOVERNMENT_ID and BACKGROUND_CHECK credentials (PRD §3.1:
    "The two critical credential types for verification are
    GOVERNMENT_ID and BACKGROUND_CHECK") and has the verifier approve
    both. Returns (tutor, gov_id_credential, bg_check_credential)
    re-fetched after the final approval.

    The optional expires_at parameters let cascade tests pin the
    expiration instant.
    """
    tutor = create_tutor(
        hourly_rate_cents=hourly_rate_cents,
        trial_rate_cents=trial_rate_cents,
    )
    gov_cred = submit_credential(
        tutor=tutor, credential_type="GOVERNMENT_ID",
        expires_at=gov_id_expires_at,
    )
    bg_cred = submit_credential(
        tutor=tutor, credential_type="BACKGROUND_CHECK",
        expires_at=bg_check_expires_at,
    )
    gov_approved = approve_credential(tutor=tutor, credential=gov_cred)
    bg_approved = approve_credential(tutor=tutor, credential=bg_cred)
    # Re-fetch tutor to pick up VERIFIED status.
    refreshed = get_success_data(
        api_client.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
    )
    return refreshed, gov_approved, bg_approved


# ===========================================================================
# Tier 2: SubjectTag
# ===========================================================================
def propose_subject(
    *,
    tutor: Dict[str, Any],
    subject_code: str = TEST_DEFAULTS["DEFAULT_SUBJECT"],
    proficiency_level: str = TEST_DEFAULTS["DEFAULT_PROFICIENCY"],
) -> Dict[str, Any]:
    """POST /tutoring/tutors/{id}/subjects — Tutor only per PRD §4."""
    headers = make_tutor_headers(tutor["id"])
    resp = api_client.propose_subject(
        tutor["id"],
        propose_subject_payload(
            subject_code=subject_code,
            proficiency_level=proficiency_level,
        ),
        headers,
    )
    return get_success_data(resp)


def approve_subject(
    *,
    tutor: Dict[str, Any],
    subject: Dict[str, Any],
    verifier_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/tutors/{id}/subjects/{sid}/approve —
    CredentialVerifier only per PRD §4."""
    headers = verifier_headers or TEST_USERS["verifier_headers"]
    resp = api_client.approve_subject(
        tutor["id"], subject["id"], headers,
    )
    return get_success_data(resp)


def add_approved_subject(
    *,
    tutor: Dict[str, Any],
    subject_code: str = TEST_DEFAULTS["DEFAULT_SUBJECT"],
    proficiency_level: str = TEST_DEFAULTS["DEFAULT_PROFICIENCY"],
) -> Dict[str, Any]:
    """Compose: propose + verifier approve. Returns APPROVED SubjectTag."""
    proposed = propose_subject(
        tutor=tutor, subject_code=subject_code,
        proficiency_level=proficiency_level,
    )
    return approve_subject(tutor=tutor, subject=proposed)


# ===========================================================================
# Tier 3: Student + Parent + child link
# ===========================================================================
def create_adult_student(
    *,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/students with account_type=ADULT.
    PRD §4: roles Student, Parent, or PlatformAdmin. Defaults to admin.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_student(
        create_student_payload(
            display_name=display_name,
            email=email or random_email("student"),
            account_type="ADULT",
            parent_id=None,
        ),
        headers,
    )
    return get_success_data(resp)


def create_parent(
    *,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/parents.
    PRD §4: roles Parent or PlatformAdmin. Defaults to admin.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_parent(
        create_parent_payload(
            display_name=display_name,
            email=email or random_email("parent"),
        ),
        headers,
    )
    return get_success_data(resp)


def create_minor_student(
    *,
    parent: Dict[str, Any],
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """POST /tutoring/students with account_type=MINOR. PRD §3.3 auto-
    creates a ParentChildLink in PENDING_PARENT_APPROVAL.

    Returns (student, link). The link is found by listing parent links
    in PENDING_PARENT_APPROVAL for the parent.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_student(
        create_student_payload(
            display_name=display_name,
            email=email or random_email("minor"),
            account_type="MINOR",
            parent_id=parent["id"],
        ),
        headers,
    )
    student = get_success_data(resp)
    # Find the auto-created link.
    link_resp = api_client.list_parent_links(
        parent["id"], make_parent_headers(parent["id"]),
        params={"link_status": "PENDING_PARENT_APPROVAL"},
    )
    link_body = link_resp.json()
    links = link_body.get("data", [])
    matching = [
        ln for ln in links if ln.get("student_id") == student["id"]
    ]
    if not matching:
        # Try admin-scoped listing in case Parent filter pickier.
        link_resp = api_client.list_parent_links(
            parent["id"], TEST_USERS["admin_headers"],
            params={"link_status": "PENDING_PARENT_APPROVAL"},
        )
        link_body = link_resp.json()
        links = link_body.get("data", [])
        matching = [
            ln for ln in links if ln.get("student_id") == student["id"]
        ]
    if not matching:
        raise AssertionError(
            f"Setup failed: no PENDING_PARENT_APPROVAL link found for "
            f"parent {parent['id']} / student {student['id']}"
        )
    return student, matching[0]


def approve_link(
    *,
    parent: Dict[str, Any],
    link: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/parents/{id}/links/{lid}/approve — Parent only
    per PRD §4.

    Identity threading: PRD §2.1 — Parent is entity-backed; we mint
    per-instance headers via make_parent_headers(parent["id"]).
    """
    headers = headers or make_parent_headers(parent["id"])
    resp = api_client.approve_link(parent["id"], link["id"], headers)
    return get_success_data(resp)


def setup_active_parent_child() -> Tuple[Dict[str, Any], Dict[str, Any],
                                          Dict[str, Any]]:
    """Compose: create parent + create MINOR student + parent approves
    link. Returns (parent, student, link_after_active).
    """
    parent = create_parent()
    student, link = create_minor_student(parent=parent)
    active_link = approve_link(parent=parent, link=link)
    return parent, student, active_link


def revoke_link(
    *,
    parent: Dict[str, Any],
    link: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> None:
    """DELETE /tutoring/parents/{id}/links/{lid} — Parent or
    PlatformAdmin per PRD §4. 204 No Content per PRD §4."""
    headers = headers or make_parent_headers(parent["id"])
    resp = api_client.revoke_link(parent["id"], link["id"], headers)
    # 204 No Content; do not parse a body.
    if resp.status_code >= 300:
        raise AssertionError(
            f"Setup failed: revoke_link returned {resp.status_code}: "
            f"{resp.text}"
        )


# ===========================================================================
# Tier 4: Session booking and lifecycle
# ===========================================================================
def book_session(
    *,
    tutor: Dict[str, Any],
    student: Dict[str, Any],
    subject_code: str = TEST_DEFAULTS["DEFAULT_SUBJECT"],
    duration_minutes: int = 60,
    start_offset_hours: float = 2.0,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
    is_trial: bool = False,
    apply_credits: bool = False,
    booker_headers: Optional[Dict[str, str]] = None,
    parent: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/sessions.

    Identity threading:
    - When `parent` is provided, the acting role is Parent on behalf of
      a MINOR child — header is minted from parent.id.
    - Otherwise (ADULT self-booking), the acting role is Student —
      header is minted from student.id.

    Tests can override `booker_headers` for unauthorized-actor tests.
    """
    if booker_headers is None:
        if parent is not None:
            booker_headers = make_parent_headers(parent["id"])
        else:
            booker_headers = make_student_headers(student["id"])
    # Use server clock so booking respects the virtual time the harness
    # is driving.
    now = server_now_dt()
    if start_at is None:
        start_dt = now + timedelta(
            hours=int(start_offset_hours),
            minutes=int((start_offset_hours % 1) * 60),
        )
        start_at = iso_utc(start_dt)
    if end_at is None:
        end_dt = parse_iso(start_at) + timedelta(minutes=duration_minutes)
        end_at = iso_utc(end_dt)
    resp = api_client.book_session(
        book_session_payload(
            tutor_id=tutor["id"],
            student_id=student["id"],
            subject_code=subject_code,
            start_at=start_at,
            end_at=end_at,
            is_trial=is_trial,
            apply_credits=apply_credits,
        ),
        booker_headers,
    )
    return get_success_data(resp)


def confirm_session(
    *,
    session: Dict[str, Any],
    tutor: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/sessions/{id}/confirm — Tutor only per PRD §4.

    Identity threading: PRD §3.5: "Confirmation requires the acting
    tutor's X-User-ID to equal the session's tutor_id".
    """
    headers = headers or make_tutor_headers(tutor["id"])
    resp = api_client.confirm_session(session["id"], headers)
    return get_success_data(resp)


def complete_session(
    *,
    session: Dict[str, Any],
    tutor: Dict[str, Any],
    adjusted_minutes: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/sessions/{id}/complete — Tutor only per PRD §4.

    Identity threading: PRD §3.5: "The complete action requires the
    acting tutor's X-User-ID to equal the session's tutor_id".
    """
    headers = headers or make_tutor_headers(tutor["id"])
    payload = complete_session_payload(adjusted_minutes=adjusted_minutes)
    resp = api_client.complete_session(session["id"], payload, headers)
    return get_success_data(resp)


def cancel_session(
    *,
    session: Dict[str, Any],
    actor_headers: Dict[str, str],
) -> Dict[str, Any]:
    """POST /tutoring/sessions/{id}/cancel — Student/Parent/Tutor per
    PRD §4. Caller passes the actor's headers explicitly because the
    cancel transition's target state depends on who cancelled (PRD
    §3.8).
    """
    resp = api_client.cancel_session(session["id"], actor_headers)
    return get_success_data(resp)


def setup_verified_tutor_with_subject(
    *,
    hourly_rate_cents: int = TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    trial_rate_cents: int = TEST_DEFAULTS["TRIAL_RATE_CENTS"],
    subject_code: str = TEST_DEFAULTS["DEFAULT_SUBJECT"],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Compose: VERIFIED tutor + one APPROVED subject tag.
    Returns (tutor, subject_tag).
    """
    tutor, _gov, _bg = make_tutor_verified(
        hourly_rate_cents=hourly_rate_cents,
        trial_rate_cents=trial_rate_cents,
    )
    subject = add_approved_subject(tutor=tutor, subject_code=subject_code)
    # Re-fetch tutor so subject_tags cache reflects approval.
    refreshed = get_success_data(
        api_client.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
    )
    return refreshed, subject


def setup_basic_booking_scenario(
    *,
    hourly_rate_cents: int = TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    trial_rate_cents: int = TEST_DEFAULTS["TRIAL_RATE_CENTS"],
    subject_code: str = TEST_DEFAULTS["DEFAULT_SUBJECT"],
    duration_minutes: int = 60,
    start_offset_hours: float = 2.0,
    is_trial: bool = False,
    apply_credits: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Compose: VERIFIED tutor + APPROVED subject + ADULT student +
    REQUESTED Session. Returns (tutor, student, session).

    Most common starting point for session-state tests.
    """
    tutor, _subject = setup_verified_tutor_with_subject(
        hourly_rate_cents=hourly_rate_cents,
        trial_rate_cents=trial_rate_cents,
        subject_code=subject_code,
    )
    student = create_adult_student()
    session = book_session(
        tutor=tutor, student=student, subject_code=subject_code,
        duration_minutes=duration_minutes,
        start_offset_hours=start_offset_hours,
        is_trial=is_trial, apply_credits=apply_credits,
    )
    return tutor, student, session


def setup_confirmed_session(**kwargs) -> Tuple[Dict[str, Any], Dict[str, Any],
                                               Dict[str, Any]]:
    """Compose: basic scenario + tutor confirms. Returns (tutor,
    student, CONFIRMED session)."""
    tutor, student, session = setup_basic_booking_scenario(**kwargs)
    confirmed = confirm_session(session=session, tutor=tutor)
    return tutor, student, confirmed


def setup_completed_session(
    *,
    hourly_rate_cents: int = TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    trial_rate_cents: int = TEST_DEFAULTS["TRIAL_RATE_CENTS"],
    subject_code: str = TEST_DEFAULTS["DEFAULT_SUBJECT"],
    duration_minutes: int = 60,
    adjusted_minutes: Optional[int] = None,
    start_offset_hours: float = 2.0,
    is_trial: bool = False,
    apply_credits: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Compose: book + confirm + advance clock to end_at + complete.
    Returns (tutor, student, COMPLETED session).

    PRD §3.5: entry to IN_PROGRESS is purely a clock function, then the
    tutor calls complete (which requires clock >= end_at OR
    adjusted_minutes >= scheduled - 10).
    """
    tutor, student, session = setup_basic_booking_scenario(
        hourly_rate_cents=hourly_rate_cents,
        trial_rate_cents=trial_rate_cents,
        subject_code=subject_code,
        duration_minutes=duration_minutes,
        start_offset_hours=start_offset_hours,
        is_trial=is_trial,
        apply_credits=apply_credits,
    )
    confirmed = confirm_session(session=session, tutor=tutor)
    # PRD §3.5: "Every Session in CONFIRMED whose start_at is at or
    # before the new clock and whose end_at is strictly later
    # transitions CONFIRMED → IN_PROGRESS." So we must first cross
    # start_at while still inside [start_at, end_at) to trigger the
    # CONFIRMED→IN_PROGRESS sweep, then cross end_at so the complete
    # action's "current clock has reached end_at" precondition holds.
    start_dt = parse_iso(confirmed["start_at"])
    end_dt = parse_iso(confirmed["end_at"])
    advance_clock_to(iso_utc(start_dt + timedelta(minutes=1)))
    advance_clock_to(iso_utc(end_dt + timedelta(minutes=1)))
    completed = complete_session(
        session=confirmed, tutor=tutor,
        adjusted_minutes=adjusted_minutes,
    )
    return tutor, student, completed


def setup_settled_session(
    *,
    hourly_rate_cents: int = TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    trial_rate_cents: int = TEST_DEFAULTS["TRIAL_RATE_CENTS"],
    subject_code: str = TEST_DEFAULTS["DEFAULT_SUBJECT"],
    duration_minutes: int = 60,
    adjusted_minutes: Optional[int] = None,
    start_offset_hours: float = 2.0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Compose: completed session + advance clock by 72h + sweep ->
    SETTLED. Returns (tutor, student, SETTLED session).

    PRD §3.6: "When both are met, the session transitions
    COMPLETED -> SETTLED, and the tutor's payout_balance_cents is
    increased by the session's pinned tutor_payout_cents."
    """
    tutor, student, completed = setup_completed_session(
        hourly_rate_cents=hourly_rate_cents,
        trial_rate_cents=trial_rate_cents,
        subject_code=subject_code,
        duration_minutes=duration_minutes,
        adjusted_minutes=adjusted_minutes,
        start_offset_hours=start_offset_hours,
    )
    # Advance past the 72h hold window.
    end_dt = parse_iso(completed["end_at"])
    advance_clock_to(
        iso_utc(end_dt + timedelta(hours=SETTLEMENT_HOLD_HOURS, minutes=1)),
    )
    # Re-fetch to pick up SETTLED.
    refreshed = get_success_data(
        api_client.get_session(
            completed["id"], make_tutor_headers(tutor["id"]),
        ),
    )
    return tutor, student, refreshed


# ===========================================================================
# Tier 5: Refund dispute lifecycle
# ===========================================================================
def open_dispute(
    *,
    session: Dict[str, Any],
    opener_headers: Dict[str, str],
    requested_amount_cents: int,
    reason_code: str = "QUALITY_ISSUE",
) -> Dict[str, Any]:
    """POST /tutoring/disputes — Student or Parent.

    Identity threading: caller supplies the actual opener headers
    (minted from student.id for ADULT or parent.id for MINOR).
    """
    resp = api_client.open_dispute(
        open_dispute_payload(
            session_id=session["id"],
            reason_code=reason_code,
            requested_amount_cents=requested_amount_cents,
        ),
        opener_headers,
    )
    return get_success_data(resp)


def respond_dispute(
    *,
    dispute: Dict[str, Any],
    tutor: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /tutoring/disputes/{id}/respond — Tutor only per PRD §4."""
    resp = api_client.respond_dispute(
        dispute["id"], make_tutor_headers(tutor["id"]),
    )
    return get_success_data(resp)


def counter_dispute(
    *,
    dispute: Dict[str, Any],
    tutor: Dict[str, Any],
    counter_amount_cents: int,
) -> Dict[str, Any]:
    """POST /tutoring/disputes/{id}/counter — Tutor only per PRD §4."""
    resp = api_client.counter_dispute(
        dispute["id"],
        counter_dispute_payload(counter_amount_cents=counter_amount_cents),
        make_tutor_headers(tutor["id"]),
    )
    return get_success_data(resp)


def accept_dispute(
    *,
    dispute: Dict[str, Any],
    opener_headers: Dict[str, str],
) -> Dict[str, Any]:
    """POST /tutoring/disputes/{id}/accept — Student or Parent."""
    resp = api_client.accept_dispute(dispute["id"], opener_headers)
    return get_success_data(resp)


def reopen_dispute(
    *,
    dispute: Dict[str, Any],
    opener_headers: Dict[str, str],
) -> Dict[str, Any]:
    """POST /tutoring/disputes/{id}/reopen — Student or Parent."""
    resp = api_client.reopen_dispute(dispute["id"], opener_headers)
    return get_success_data(resp)


def escalate_dispute(
    *,
    dispute: Dict[str, Any],
    actor_headers: Dict[str, str],
) -> Dict[str, Any]:
    """POST /tutoring/disputes/{id}/escalate — Student, Parent, or
    PlatformAdmin."""
    resp = api_client.escalate_dispute(dispute["id"], actor_headers)
    return get_success_data(resp)


def arbitrate_dispute(
    *,
    dispute: Dict[str, Any],
    decision: str,
    refund_amount_cents: Optional[int] = None,
    arbiter_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/disputes/{id}/arbitrate — PlatformArbiter only.

    PRD §3.7: "The arbiter's X-User-ID must not equal the session's
    tutor_id, must not equal the session's student_id, and must not
    equal the linked Parent's id for MINOR students". The shared
    PLATFORM_ARBITER_ID constant is a literal string that will never
    collide with a server-minted UUID, so it is safe here.
    """
    headers = arbiter_headers or TEST_USERS["arbiter_headers"]
    resp = api_client.arbitrate_dispute(
        dispute["id"],
        arbitrate_dispute_payload(
            decision=decision,
            refund_amount_cents=refund_amount_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def withdraw_dispute(
    *,
    dispute: Dict[str, Any],
    opener_headers: Dict[str, str],
) -> Dict[str, Any]:
    """POST /tutoring/disputes/{id}/withdraw — Student or Parent."""
    resp = api_client.withdraw_dispute(dispute["id"], opener_headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 6: Payout batch lifecycle
# ===========================================================================
def create_payout(
    *,
    tutor: Dict[str, Any],
    requester_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/payouts — PlatformAdmin only per PRD §4."""
    headers = requester_headers or TEST_USERS["admin_headers"]
    resp = api_client.create_payout(
        create_payout_payload(tutor_id=tutor["id"]), headers,
    )
    return get_success_data(resp)


def mark_payout_paid(
    *,
    payout: Dict[str, Any],
    payer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/payouts/{id}/mark-paid — PlatformAdmin only.

    PRD §3.6: "A different PlatformAdmin (whose X-User-ID differs from
    requested_by ...) marks the batch paid". Defaults to admin_headers_alt
    which is a distinct opaque admin id from admin_headers used for
    request.
    """
    headers = payer_headers or TEST_USERS["admin_headers_alt"]
    resp = api_client.mark_payout_paid(payout["id"], headers)
    return get_success_data(resp)


def reverse_payout(
    *,
    payout: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tutoring/payouts/{id}/reverse — PlatformAdmin only per
    PRD §4."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.reverse_payout(payout["id"], headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 7: Targeted state-builder helpers for difficulty-design tests
# ===========================================================================
def raise_tutor_to_completed_count(
    *,
    tutor: Dict[str, Any],
    target_count: int,
    helper_subject: str = TEST_DEFAULTS["DEFAULT_SUBJECT"],
) -> Dict[str, Any]:
    """Drive tutor.lifetime_completed_sessions up to target_count by
    completing fresh sessions with a fresh ADULT student per session.

    PRD §3.5: "The tutor's lifetime_completed_sessions is incremented
    by 1" on every COMPLETED transition. PRD §3.4: trial uniqueness is
    per (tutor, student) pair, so using a fresh student each iteration
    keeps every iteration eligible.

    Each completed session uses a 60-minute non-trial slot, starting
    in turn so that overlap rules are not violated.
    """
    current = tutor["lifetime_completed_sessions"]
    needed = target_count - current
    if needed <= 0:
        return get_success_data(
            api_client.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
    # Each iteration: pick a fresh start_at offset so consecutive
    # 60-min sessions do not overlap on the tutor's calendar.
    # PRD §3.4 requires start_at >= now + 60 minutes; we step by 2h.
    for i in range(needed):
        student = create_adult_student()
        # Use a unique start instant per iteration; advance the clock
        # between iterations to keep the next start_at >= now+60min.
        offset_hours = 2 + i * 3  # 2h, 5h, 8h, ... well-separated slots
        session = book_session(
            tutor=tutor, student=student,
            subject_code=helper_subject,
            duration_minutes=60,
            start_offset_hours=float(offset_hours),
        )
        confirm_session(session=session, tutor=tutor)
        # Cross start_at first to enter IN_PROGRESS, then cross end_at.
        start_dt = parse_iso(session["start_at"])
        end_dt = parse_iso(session["end_at"])
        advance_clock_to(iso_utc(start_dt + timedelta(minutes=1)))
        advance_clock_to(iso_utc(end_dt + timedelta(minutes=1)))
        complete_session(session=session, tutor=tutor)
    return get_success_data(
        api_client.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
    )


def setup_completed_session_with_short_delivery(
    *,
    hourly_rate_cents: int,
    duration_minutes: int,
    adjusted_minutes: int,
    initial_credit_cents: int = 0,
    apply_credits: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Book + confirm + clock-advance + complete with adjusted_minutes
    less than scheduled so short_delivery_refund > 0.

    Optionally seeds the student's credit_balance_cents to a target value
    by first completing prior sessions (cancelled or refund-credited).
    For the difficulty test (compensating_invariant) we just want a
    fresh ADULT student so we set initial_credit=0 by default; seeding
    is handled separately when needed.
    """
    tutor, student, session = setup_basic_booking_scenario(
        hourly_rate_cents=hourly_rate_cents,
        duration_minutes=duration_minutes,
        apply_credits=apply_credits,
    )
    confirmed = confirm_session(session=session, tutor=tutor)
    start_dt = parse_iso(confirmed["start_at"])
    end_dt = parse_iso(confirmed["end_at"])
    advance_clock_to(iso_utc(start_dt + timedelta(minutes=1)))
    advance_clock_to(iso_utc(end_dt + timedelta(minutes=1)))
    completed = complete_session(
        session=confirmed, tutor=tutor,
        adjusted_minutes=adjusted_minutes,
    )
    return tutor, student, completed


def seed_student_credit(
    *,
    student: Dict[str, Any],
    target_credit_cents: int,
    helper_tutor: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Drive student.credit_balance_cents up to target_credit_cents by
    booking + cancelling sessions (free cancel ≥24h notice grants full
    refund per PRD §3.8).

    Each booked session is on a fresh ADULT student-side cancellation
    with the helper tutor; the cancel's refund equals
    charged_amount_cents which is fully credited to the student.

    Uses a single helper tutor (created if not supplied) with a high
    hourly rate to keep iterations small.
    """
    if target_credit_cents <= 0:
        return student
    refreshed_student = student
    helper = helper_tutor
    if helper is None:
        helper, _subj = setup_verified_tutor_with_subject(
            hourly_rate_cents=50_000,  # max — $500/hr
        )
    # Each 60-min session at hourly_rate_cents=50000 grosses 50000 cents
    # = $500, credited on free cancel.
    per_session = helper["hourly_rate_cents"]  # 60-min session
    needed = target_credit_cents
    iteration = 0
    while needed > 0:
        amt = min(per_session, needed)
        # The gross is rounded; ensure we book a session that yields
        # exactly amt. Easiest path: book per_session and only iterate
        # as many times as needed to land on the target. If amt <
        # per_session we book a shorter session (amt cents implies
        # ceil(amt/per_min) minutes).
        # Use a sufficiently distant start so we can free-cancel >=24h.
        start_offset = 48 + iteration * 24  # 48h, 72h, 96h, ...
        if amt == per_session:
            session = book_session(
                tutor=helper, student=refreshed_student,
                duration_minutes=60,
                start_offset_hours=float(start_offset),
            )
        else:
            # Compute minutes needed to gross approximately amt cents.
            # gross = round(hourly/60 * minutes). Choose minutes = amt /
            # (hourly/60) rounded to the nearest whole minute, then book.
            per_min = helper["hourly_rate_cents"] / 60.0
            mins = max(1, int(round(amt / per_min)))
            if mins < 60 and mins > 0:
                session = book_session(
                    tutor=helper, student=refreshed_student,
                    duration_minutes=mins,
                    start_offset_hours=float(start_offset),
                )
            else:
                session = book_session(
                    tutor=helper, student=refreshed_student,
                    duration_minutes=60,
                    start_offset_hours=float(start_offset),
                )
        cancelled = cancel_session(
            session=session,
            actor_headers=make_student_headers(refreshed_student["id"]),
        )
        # The actual refund is the cancelled session's
        # refund_to_student_cents (free cancel because >=24h notice).
        needed -= cancelled["refund_to_student_cents"]
        iteration += 1
        if iteration > 200:
            break
    # Re-fetch student.
    refreshed_student = get_success_data(
        api_client.get_student(
            student["id"], make_student_headers(student["id"]),
        ),
    )
    return refreshed_student


__all__ = [
    "advance_clock_to",
    "server_now_iso",
    "server_now_dt",
    "advance_clock_by",
    "advance_clock_past_session_end",
    "create_tutor",
    "submit_credential",
    "approve_credential",
    "reject_credential",
    "make_tutor_verified",
    "propose_subject",
    "approve_subject",
    "add_approved_subject",
    "create_adult_student",
    "create_parent",
    "create_minor_student",
    "approve_link",
    "setup_active_parent_child",
    "revoke_link",
    "book_session",
    "confirm_session",
    "complete_session",
    "cancel_session",
    "setup_verified_tutor_with_subject",
    "setup_basic_booking_scenario",
    "setup_confirmed_session",
    "setup_completed_session",
    "setup_settled_session",
    "open_dispute",
    "respond_dispute",
    "counter_dispute",
    "accept_dispute",
    "reopen_dispute",
    "escalate_dispute",
    "arbitrate_dispute",
    "withdraw_dispute",
    "create_payout",
    "mark_payout_paid",
    "reverse_payout",
    "raise_tutor_to_completed_count",
    "setup_completed_session_with_short_delivery",
    "seed_student_credit",
]
