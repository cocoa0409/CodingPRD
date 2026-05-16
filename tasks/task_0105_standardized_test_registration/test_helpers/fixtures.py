"""Composite fixtures for multi-step setup of standardized-test-registration tests.

Most testable claims live behind multi-call preambles:

  - Tiered-refund tests must first create a TestEvent + capacity, register
    a candidate (force-confirmed), advance the clock to the desired
    days_before_test, then call cancel.
  - Standby-promotion tests must drive the capacity to a known seat
    state (regular pool full, accommodation pool full / empty) and
    submit several STANDBY registrations in known order.
  - Super-score tests must advance the clock past test_date +
    TEST_SESSION_HOURS for each prior sitting, run the sweep, then
    advance past score_release_date so ScoreReport posting becomes
    legal.
  - Accommodation review-cycle tests must wire the SUBMITTED → UR →
    NEEDS_MORE_INFO → SUBMITTED → UR cycle across two actors.

Identity threading (mandatory, PRD §2.1): after a fixture creates a
Candidate, every ownership-gated call MUST use
make_candidate_headers(candidate["id"]) — never the
CANDIDATE_FALLBACK_ID constant. Failing to thread identity is the
canonical bug that breaks every ownership check in the implementation.

All setup calls use get_success_data() (lenient envelope check) so
setup failures surface a clear "setup failed" error rather than a
confusing assertion mismatch later in the test body.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, THRESHOLDS
from .factories import (
    cancel_payload,
    clear_id_payload,
    create_accommodation_request_payload,
    create_candidate_payload,
    create_capacity_payload,
    create_registration_payload,
    create_score_report_payload,
    create_test_center_payload,
    create_test_event_payload,
    extend_deadline_payload,
    reject_id_payload,
    resubmit_accommodation_payload,
    submit_id_payload,
    unique_form_code,
)
from .test_users import (
    ACCOMMODATIONS_OFFICER_ID,
    TEST_USERS,
    make_accommodations_officer_headers,
    make_candidate_headers,
    make_credits_officer_headers,
    make_proctor_headers,
    make_registrar_headers,
)


# ===========================================================================
# Clock helpers (PRD §2.10)
# ===========================================================================
def parse_iso(stamp: str) -> datetime:
    """Parse an ISO 8601 string (Z or offset) into a tz-aware datetime."""
    if stamp.endswith("Z"):
        stamp = stamp[:-1] + "+00:00"
    return datetime.fromisoformat(stamp)


def fmt_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    ms = f"{int(dt_utc.microsecond / 1000):03d}"
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms}Z"


def advance_clock_to(iso_stamp: str) -> str:
    """Advance the logical clock to the supplied instant (PRD §2.10)."""
    res = api_client.advance_clock(
        iso_stamp, TEST_USERS["registrar_headers"],
    )
    data = get_success_data(res)
    return data.get("now", iso_stamp)


def advance_clock_by(delta: timedelta, from_stamp: str) -> str:
    """Advance the clock to from_stamp + delta. Returns new ISO."""
    target = parse_iso(from_stamp) + delta
    target_iso = fmt_iso(target)
    return advance_clock_to(target_iso)


def reset_clock_to(iso_stamp: Optional[str] = None) -> str:
    """Set the simulation clock to the provided ISO time.

    PRD §2.10: "the server exposes an admin-only logical clock that
    can be advanced to any supplied future instant via a `to` field
    in the request body."
    """
    target = iso_stamp or TEST_DEFAULTS["INITIAL_CLOCK"]
    return advance_clock_to(target)


def run_sweep(test_event_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /_sweep/no-show-and-promote for the given event."""
    res = api_client.sweep_no_show_and_promote(
        test_event_id, headers or TEST_USERS["registrar_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 1: state-progression primitives
# ===========================================================================
def create_candidate(legal_name: Optional[str] = None,
                     home_state_code: str = "CA",
                     has_iep_or_504: bool = False,
                     **overrides) -> Dict[str, Any]:
    """Create a Candidate via the Registrar role (PRD §3.3).

    A Registrar may create candidates on a candidate's behalf, which
    avoids the chicken-and-egg of needing a Candidate.id before any
    Candidate-role header exists.
    """
    payload = create_candidate_payload(
        home_state_code=home_state_code,
        has_iep_or_504=has_iep_or_504,
        **overrides,
    )
    if legal_name is not None:
        payload["legal_name"] = legal_name
    res = api_client.create_candidate(
        payload, TEST_USERS["registrar_headers"],
    )
    return get_success_data(res)


def create_test_center(**overrides) -> Dict[str, Any]:
    """Create a TestCenter via Registrar (PRD §3.2)."""
    res = api_client.create_test_center(
        create_test_center_payload(**overrides),
        TEST_USERS["registrar_headers"],
    )
    return get_success_data(res)


def create_test_event(test_type: str = "SAT",
                      subject: Optional[str] = None,
                      test_date: str = "2026-06-08T09:00:00.000Z",
                      registration_deadline: str = "2026-05-25T00:00:00.000Z",
                      late_registration_deadline: str = "2026-06-04T00:00:00.000Z",
                      score_release_date: str = "2026-06-15T00:00:00.000Z",
                      base_fee_cents: int = TEST_DEFAULTS["DEFAULT_BASE_FEE_CENTS"],
                      late_fee_cents: int = TEST_DEFAULTS["DEFAULT_LATE_FEE_CENTS"],
                      form_code: Optional[str] = None,
                      **overrides) -> Dict[str, Any]:
    """Create a TestEvent in REGISTRATION_OPEN (PRD §3.1)."""
    payload = create_test_event_payload(
        test_type=test_type,
        subject=subject,
        test_date=test_date,
        registration_deadline=registration_deadline,
        late_registration_deadline=late_registration_deadline,
        score_release_date=score_release_date,
        base_fee_cents=base_fee_cents,
        late_fee_cents=late_fee_cents,
        form_code=form_code or unique_form_code(test_type),
        **overrides,
    )
    res = api_client.create_test_event(
        payload, TEST_USERS["registrar_headers"],
    )
    return get_success_data(res)


def create_capacity(test_event_id: str, test_center_id: str,
                    total_capacity: int = 10,
                    accommodation_capacity: int = 2,
                    **overrides) -> Dict[str, Any]:
    """Allocate seats at a TestCenter for a TestEvent (PRD §3.2)."""
    res = api_client.create_test_center_capacity(
        test_event_id,
        create_capacity_payload(
            test_center_id=test_center_id,
            total_capacity=total_capacity,
            accommodation_capacity=accommodation_capacity,
            **overrides,
        ),
        TEST_USERS["registrar_headers"],
    )
    return get_success_data(res)


def create_event_with_capacity(test_type: str = "SAT",
                               total_capacity: int = 10,
                               accommodation_capacity: int = 2,
                               **event_overrides) -> Tuple[Dict[str, Any],
                                                            Dict[str, Any],
                                                            Dict[str, Any]]:
    """Common preamble: TestEvent + TestCenter + TestCenterCapacity.

    Returns (event, center, capacity).
    """
    event = create_test_event(test_type=test_type, **event_overrides)
    center = create_test_center()
    capacity = create_capacity(
        event["id"], center["id"],
        total_capacity=total_capacity,
        accommodation_capacity=accommodation_capacity,
    )
    return event, center, capacity


def create_registration_as_candidate(test_event_id: str,
                                     candidate: Dict[str, Any],
                                     test_center_id: str,
                                     force_confirmed: bool = False,
                                     use_registrar: bool = False,
                                     **overrides) -> Dict[str, Any]:
    """POST /test-events/{id}/registrations.

    PRD §2.1 identity threading: ownership-gated Candidate calls must
    use the real Candidate.id, so make_candidate_headers(candidate.id)
    is the only correct header source. Tests that prefer Registrar
    (the second permitted role per PRD §3.4) can flip use_registrar.
    """
    payload = create_registration_payload(
        candidate_id=candidate["id"],
        test_center_id=test_center_id,
        **overrides,
    )
    if force_confirmed:
        payload["force_confirmed"] = True
    headers = (TEST_USERS["registrar_headers"] if use_registrar
               else make_candidate_headers(candidate["id"]))
    res = api_client.create_registration(test_event_id, payload, headers)
    return get_success_data(res)


def force_confirmed_registration(test_event_id: str,
                                 candidate: Dict[str, Any],
                                 test_center_id: str,
                                 **overrides) -> Dict[str, Any]:
    """Shortcut: Registrar creates a force_confirmed Registration.

    Used by every fixture that needs a candidate to be CONFIRMED
    before another action runs (cancel, refund, check-in, etc.).
    Registrar role is appropriate because PRD §3.4 lets a Registrar
    act on any candidate's behalf.
    """
    return create_registration_as_candidate(
        test_event_id, candidate, test_center_id,
        force_confirmed=True, use_registrar=True, **overrides,
    )


# ===========================================================================
# Tier 2: ID verification
# ===========================================================================
def submit_id_verification(test_event_id: str,
                           registration_id: str,
                           candidate: Dict[str, Any],
                           id_document_type: str = "DRIVERS_LICENSE",
                           issuing_state_code: Optional[str] = "CA",
                           id_expires_on: str = "2030-01-01",
                           **overrides) -> Dict[str, Any]:
    """Candidate submits ID documents (PRD §3.5)."""
    payload = submit_id_payload(
        id_document_type=id_document_type,
        issuing_state_code=issuing_state_code,
        id_expires_on=id_expires_on,
        **overrides,
    )
    res = api_client.submit_id_verification(
        test_event_id, registration_id, payload,
        make_candidate_headers(candidate["id"]),
    )
    return get_success_data(res)


def clear_id_verification(test_event_id: str, registration_id: str,
                          allow_cross_state_override: bool = False) -> Dict[str, Any]:
    """Registrar clears the ID (PRD §3.5)."""
    payload = clear_id_payload(
        allow_cross_state_override=allow_cross_state_override,
    ) if allow_cross_state_override else clear_id_payload()
    res = api_client.clear_id_verification(
        test_event_id, registration_id,
        TEST_USERS["registrar_headers"],
        payload,
    )
    return get_success_data(res)


def reject_id_verification(test_event_id: str, registration_id: str,
                           rejection_reason: str = "blurry") -> Dict[str, Any]:
    """Registrar rejects the ID submission (PRD §3.5)."""
    res = api_client.reject_id_verification(
        test_event_id, registration_id,
        reject_id_payload(rejection_reason=rejection_reason),
        TEST_USERS["registrar_headers"],
    )
    return get_success_data(res)


def submit_and_clear_id(test_event_id: str,
                        registration_id: str,
                        candidate: Dict[str, Any],
                        id_document_type: str = "DRIVERS_LICENSE",
                        id_expires_on: str = "2030-01-01") -> Dict[str, Any]:
    """Combined preamble: submit + clear so the IDVerification reaches CLEARED."""
    submit_id_verification(
        test_event_id, registration_id, candidate,
        id_document_type=id_document_type,
        issuing_state_code=candidate["home_state_code"],
        id_expires_on=id_expires_on,
    )
    return clear_id_verification(test_event_id, registration_id)


# ===========================================================================
# Tier 3: Accommodation request review
# ===========================================================================
def submit_accommodation_request(candidate: Dict[str, Any],
                                 test_event_id: str,
                                 requested: Optional[List[str]] = None,
                                 docs: Optional[List[str]] = None,
                                 **overrides) -> Dict[str, Any]:
    """Candidate submits an AccommodationRequest (PRD §3.6)."""
    res = api_client.create_accommodation_request(
        create_accommodation_request_payload(
            candidate_id=candidate["id"],
            test_event_id=test_event_id,
            requested_accommodations=requested,
            supporting_documents=docs,
            **overrides,
        ),
        make_candidate_headers(candidate["id"]),
    )
    return get_success_data(res)


def start_review(accommodation_request_id: str,
                 officer_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """AccommodationsOfficer pulls a SUBMITTED request into UNDER_REVIEW."""
    res = api_client.start_review_accommodation(
        accommodation_request_id,
        officer_headers or TEST_USERS["accommodations_officer_headers"],
    )
    return get_success_data(res)


def approve_accommodation(accommodation_request_id: str,
                          officer_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """AccommodationsOfficer approves (PRD §3.6)."""
    res = api_client.approve_accommodation(
        accommodation_request_id,
        officer_headers or TEST_USERS["accommodations_officer_headers"],
    )
    return get_success_data(res)


def deny_accommodation(accommodation_request_id: str,
                       officer_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.deny_accommodation(
        accommodation_request_id,
        officer_headers or TEST_USERS["accommodations_officer_headers"],
    )
    return get_success_data(res)


def request_more_info(accommodation_request_id: str,
                      officer_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.request_info_accommodation(
        accommodation_request_id,
        officer_headers or TEST_USERS["accommodations_officer_headers"],
    )
    return get_success_data(res)


def resubmit_accommodation(accommodation_request_id: str,
                           candidate: Dict[str, Any],
                           supporting_documents: List[str]) -> Dict[str, Any]:
    """Candidate appends new supporting documents (PRD §3.6)."""
    res = api_client.resubmit_accommodation(
        accommodation_request_id,
        resubmit_accommodation_payload(supporting_documents=supporting_documents),
        make_candidate_headers(candidate["id"]),
    )
    return get_success_data(res)


def submit_and_approve_accommodation(candidate: Dict[str, Any],
                                     test_event_id: str,
                                     officer_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Combined preamble: submit -> start-review -> approve."""
    req = submit_accommodation_request(candidate, test_event_id)
    start_review(req["id"], officer_headers=officer_headers)
    return approve_accommodation(req["id"], officer_headers=officer_headers)


# ===========================================================================
# Tier 4: Cancellation
# ===========================================================================
def self_cancel(test_event_id: str, registration: Dict[str, Any],
                candidate: Dict[str, Any],
                version: Optional[int] = None) -> Dict[str, Any]:
    """Candidate self-cancels their own Registration (PRD §3.8).

    Identity threading: must use make_candidate_headers(candidate.id)
    so the ownership check (candidate_id == X-User-ID) passes."""
    payload = cancel_payload(version=version) if version is not None else cancel_payload()
    res = api_client.self_cancel_registration(
        test_event_id, registration["id"],
        make_candidate_headers(candidate["id"]),
        payload,
    )
    return get_success_data(res)


def admin_cancel(test_event_id: str, registration_id: str,
                 version: Optional[int] = None) -> Dict[str, Any]:
    """Registrar admin-cancels a registration (PRD §3.8)."""
    payload = cancel_payload(version=version) if version is not None else cancel_payload()
    res = api_client.admin_cancel_registration(
        test_event_id, registration_id,
        TEST_USERS["registrar_headers"],
        payload,
    )
    return get_success_data(res)


# ===========================================================================
# Tier 5: Check-in window helpers
# ===========================================================================
def advance_clock_to_check_in_window(test_date_iso: str,
                                     hours_before_test: float = 1.5) -> str:
    """Advance clock to inside the check-in window.

    PRD §3.7: "the window from `test_date - 2 hours` to
    `test_date + 1 hour`" — by default we land at -1.5h, comfortably
    inside the window.
    """
    target = parse_iso(test_date_iso) - timedelta(hours=hours_before_test)
    return advance_clock_to(fmt_iso(target))


def check_in(test_event_id: str, registration_id: str) -> Dict[str, Any]:
    """Proctor checks in a Candidate (PRD §3.7)."""
    res = api_client.check_in_registration(
        test_event_id, registration_id,
        TEST_USERS["proctor_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 6: Full event lifecycle — drive event through to COMPLETED
# ===========================================================================
def drive_event_to_completed(test_event_id: str,
                             test_date_iso: str,
                             score_release_iso: str) -> Dict[str, Any]:
    """Advance clock past test_date + TEST_SESSION_HOURS, run sweep, then
    past score_release_date.

    PRD §3.1: "when the logical clock crosses `test_date` plus the
    test-session duration (a fixed four hours), at which point a
    `REGISTRATION_CLOSED` event moves to `SCORES_PENDING`. This
    transition has a precondition that the no-show-and-promote sweep
    has been called for the event at least once after `test_date`,
    ensuring no still-promotable standby slots are forgotten. ...
    Finally, when the clock crosses `score_release_date`, the event
    moves from `SCORES_PENDING` to `COMPLETED`".
    """
    end_of_session = parse_iso(test_date_iso) + timedelta(
        hours=THRESHOLDS["TEST_SESSION_HOURS"], minutes=5,
    )
    advance_clock_to(fmt_iso(end_of_session))
    run_sweep(test_event_id)
    advance_clock_to(fmt_iso(parse_iso(score_release_iso) + timedelta(minutes=5)))
    return get_success_data(
        api_client.get_test_event(test_event_id, TEST_USERS["registrar_headers"])
    )


def complete_registration_lifecycle(candidate: Dict[str, Any],
                                    test_type: str = "SAT",
                                    test_date_iso: str = "2026-06-08T09:00:00.000Z",
                                    registration_deadline: str = "2026-05-25T00:00:00.000Z",
                                    late_registration_deadline: str = "2026-06-04T00:00:00.000Z",
                                    score_release_date: str = "2026-06-15T00:00:00.000Z",
                                    subject: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Full preamble: event + center + capacity + registration + ID
    cleared + check-in + sweep + score-release advance.

    Returns (event_after_completion, registration_after_completion)."""
    event, center, _ = create_event_with_capacity(
        test_type=test_type,
        subject=subject,
        test_date=test_date_iso,
        registration_deadline=registration_deadline,
        late_registration_deadline=late_registration_deadline,
        score_release_date=score_release_date,
    )
    registration = force_confirmed_registration(event["id"], candidate, center["id"])
    submit_and_clear_id(event["id"], registration["id"], candidate)
    advance_clock_to_check_in_window(test_date_iso)
    check_in(event["id"], registration["id"])
    drive_event_to_completed(event["id"], test_date_iso, score_release_date)
    final_reg = get_success_data(
        api_client.get_registration(event["id"], registration["id"],
                                    TEST_USERS["registrar_headers"])
    )
    final_event = get_success_data(
        api_client.get_test_event(event["id"],
                                  TEST_USERS["registrar_headers"])
    )
    return final_event, final_reg


def post_score_report(test_event_id: str, registration_id: str,
                      section_scores: Dict[str, int], total_score: int,
                      report_type: str = "OFFICIAL") -> Dict[str, Any]:
    """Registrar posts a ScoreReport (PRD §3.9)."""
    res = api_client.create_score_report(
        test_event_id, registration_id,
        create_score_report_payload(section_scores=section_scores,
                                    total_score=total_score,
                                    report_type=report_type),
        TEST_USERS["registrar_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 7: Capacity-saturation / Standby preconditions
# ===========================================================================
def saturate_general_pool(event_id: str, center_id: str,
                          how_many: int) -> List[Dict[str, Any]]:
    """Create `how_many` Registrar-confirmed registrations to fill the
    general (non-accommodation) pool. Returns the list of registrations.

    Each candidate is created via Registrar (PRD §3.3 allows operator
    creation) with has_iep_or_504=false so they consume general seats.
    """
    rows: List[Dict[str, Any]] = []
    for _ in range(how_many):
        cand = create_candidate(has_iep_or_504=False)
        reg = force_confirmed_registration(event_id, cand, center_id)
        rows.append(reg)
    return rows


def saturate_accommodation_pool(event_id: str, center_id: str,
                                how_many: int,
                                officer_headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Fill `how_many` accommodation seats by approving each candidate's
    AccommodationRequest after Registrar-confirming them.

    Returns the list of resulting Registrations (post-approval).
    """
    rows: List[Dict[str, Any]] = []
    for _ in range(how_many):
        cand = create_candidate(has_iep_or_504=True)
        reg = force_confirmed_registration(event_id, cand, center_id)
        submit_and_approve_accommodation(
            cand, event_id, officer_headers=officer_headers,
        )
        # Refresh registration after cascade.
        fresh = get_success_data(
            api_client.get_registration(
                event_id, reg["id"], TEST_USERS["registrar_headers"],
            )
        )
        rows.append(fresh)
    return rows


# ===========================================================================
# Tier 8: Boundary timing for the refund tier
# ===========================================================================
def setup_refund_boundary_event(test_date_iso: str,
                                base_fee_cents: int = TEST_DEFAULTS["DEFAULT_BASE_FEE_CENTS"],
                                late_fee_cents: int = 0,
                                registration_deadline_iso: Optional[str] = None,
                                late_registration_deadline_iso: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create an event whose test_date is fixed at `test_date_iso`,
    with reg deadlines two weeks before. Returns (event, center).

    Used by tier-boundary tests that need to control days_before_test
    independently of any earlier setup work.
    """
    if registration_deadline_iso is None:
        registration_deadline_iso = fmt_iso(
            parse_iso(test_date_iso) - timedelta(days=14),
        )
    if late_registration_deadline_iso is None:
        late_registration_deadline_iso = fmt_iso(
            parse_iso(test_date_iso) - timedelta(days=4),
        )
    score_release_iso = fmt_iso(
        parse_iso(test_date_iso) + timedelta(days=7),
    )
    event = create_test_event(
        test_date=test_date_iso,
        registration_deadline=registration_deadline_iso,
        late_registration_deadline=late_registration_deadline_iso,
        score_release_date=score_release_iso,
        base_fee_cents=base_fee_cents,
        late_fee_cents=late_fee_cents,
    )
    center = create_test_center()
    create_capacity(event["id"], center["id"], total_capacity=10, accommodation_capacity=2)
    return event, center


def setup_registration_at_clock(test_date_iso: str,
                                base_fee_cents: int,
                                late_fee_cents: int,
                                clock_at_creation_iso: str,
                                **event_overrides) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build event + center + capacity, set clock to clock_at_creation_iso,
    then force-confirm one Candidate's Registration.

    Returns (event, center, candidate, registration). Useful for refund
    tests that need a known fee snapshot (base + late) at a known clock
    instant before the refund computation runs.
    """
    reset_clock_to(clock_at_creation_iso)
    event, center = setup_refund_boundary_event(
        test_date_iso=test_date_iso,
        base_fee_cents=base_fee_cents,
        late_fee_cents=late_fee_cents,
        **event_overrides,
    )
    candidate = create_candidate(has_iep_or_504=False)
    registration = force_confirmed_registration(
        event["id"], candidate, center["id"],
    )
    return event, center, candidate, registration


__all__ = [
    "parse_iso",
    "fmt_iso",
    "advance_clock_to",
    "advance_clock_by",
    "reset_clock_to",
    "run_sweep",
    "create_candidate",
    "create_test_center",
    "create_test_event",
    "create_capacity",
    "create_event_with_capacity",
    "create_registration_as_candidate",
    "force_confirmed_registration",
    "submit_id_verification",
    "clear_id_verification",
    "reject_id_verification",
    "submit_and_clear_id",
    "submit_accommodation_request",
    "start_review",
    "approve_accommodation",
    "deny_accommodation",
    "request_more_info",
    "resubmit_accommodation",
    "submit_and_approve_accommodation",
    "self_cancel",
    "admin_cancel",
    "advance_clock_to_check_in_window",
    "check_in",
    "drive_event_to_completed",
    "complete_registration_lifecycle",
    "post_score_report",
    "saturate_general_pool",
    "saturate_accommodation_pool",
    "setup_refund_boundary_event",
    "setup_registration_at_clock",
]
