"""Composite setup helpers — multi-step preambles that tests reuse.

The clinical-trial workflow is long: create Trial (DRAFT) -> add arms ->
publish ConsentVersion v1 -> submit-for-irb (IRB_PENDING) -> IRB approves
(APPROVED) -> open-enrollment (OPEN_FOR_ENROLLMENT) -> create participants
-> evaluate -> request-consent -> sign-consent (ENROLLED) -> schedule
visits -> advance clock -> complete visits -> complete participant
(FINAL payments). Most interesting test claims need the system in a
late-pipeline state.

IDENTITY THREADING — PRD §2.1:

- PrincipalInvestigator, IRBReviewer, and StudyCoordinator are OPAQUE.
  Shared TEST_USERS headers are canonical. The default PI and the
  default IRBReviewer have DISTINCT ids so the SoD check of PRD §2.5
  succeeds by default. When a test wants to PROVOKE the SoD failure,
  it explicitly mints reviewer headers from the PI's id via
  make_irb_reviewer_headers(PRINCIPAL_INVESTIGATOR_ID).

- Participant_self is ENTITY-BACKED. Every Participant_self-driven call
  (sign-consent, withdraw, GET own participant, GET own visits, GET own
  payments) MUST mint headers via
  make_participant_self_headers(participant["id"]) — never via the
  shared PARTICIPANT_SELF_FALLBACK_ID constant. The fixtures here
  remember the acting Participant.id and pass it through to ownership-
  gated calls.

Setup helpers use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BASE_VISIT_CENTS,
    ON_TIME_BONUS_CENTS,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    complete_visit_payload,
    create_adverse_event_payload,
    create_arm_payload,
    create_consent_version_payload,
    create_irb_review_payload,
    create_participant_payload,
    create_trial_payload,
    create_visit_payload,
    iso_anchor_offset,
    iso_utc,
    parse_anchor,
    parse_iso,
    resolve_adverse_event_payload,
    sign_consent_payload,
    terminate_trial_payload,
    withdraw_participant_payload,
)
from .test_users import (
    PRINCIPAL_INVESTIGATOR_ID,
    TEST_USERS,
    make_participant_self_headers,
    make_pi_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.12.
# ===========================================================================
def advance_clock_to(iso_timestamp: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance — PRD §2.12.

    PRD §2.12: "an admin-only test-driving capability advances the
    logical clock to a supplied to_iso8601 instant. The submitted
    timestamp must be greater than or equal to the current clock; the
    clock is monotonic and may not be moved backwards."

    The scaffold authorizes PI, StudyCoordinator, and IRBReviewer for
    /_clock/advance; the default PI headers suffice.
    """
    headers = headers or TEST_USERS["pi_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to_iso8601=iso_timestamp), headers,
    )
    return get_success_data(resp)


def anchor_clock() -> None:
    """Pin the server clock to the deterministic test anchor so all
    time-sensitive setups are reproducible."""
    advance_clock_to(TEST_DEFAULTS["CLOCK_ANCHOR"])


# ===========================================================================
# Trial creation / arms / consent / IRB approval.
# ===========================================================================
def create_trial_in_draft(
    *,
    pi_headers: Optional[Dict[str, str]] = None,
    **trial_overrides: Any,
) -> Dict[str, Any]:
    """POST /trials. PRD §3.1: "A freshly created trial begins life in
    DRAFT status"."""
    headers = pi_headers or TEST_USERS["pi_headers"]
    resp = api_client.create_trial(
        create_trial_payload(**trial_overrides), headers,
    )
    return get_success_data(resp)


def add_arm(trial_id: str, *,
            code: Optional[str] = None,
            label: Optional[str] = None,
            weight: int = 1,
            pi_headers: Optional[Dict[str, str]] = None,
            ) -> Dict[str, Any]:
    """POST /trials/{trial_id}/arms. PRD §3.1: arms are attached while
    the trial is still in DRAFT."""
    headers = pi_headers or TEST_USERS["pi_headers"]
    resp = api_client.create_arm(
        trial_id,
        create_arm_payload(code=code, label=label, weight=weight),
        headers,
    )
    return get_success_data(resp)


def publish_consent_version(trial_id: str, *,
                            change_summary: Optional[str] = None,
                            requires_re_consent: Optional[bool] = None,
                            pi_headers: Optional[Dict[str, str]] = None,
                            ) -> Dict[str, Any]:
    """POST /trials/{trial_id}/consent-versions. PRD §2.10: "The first
    publish sets active_consent_version from null to 1; subsequent
    publishes set it to the new server-minted version." """
    headers = pi_headers or TEST_USERS["pi_headers"]
    resp = api_client.create_consent_version(
        trial_id,
        create_consent_version_payload(
            change_summary=change_summary,
            requires_re_consent=requires_re_consent,
        ),
        headers,
    )
    return get_success_data(resp)


def submit_trial_for_irb(trial_id: str, *,
                         pi_headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    """POST /trials/{trial_id}/submit-for-irb. PRD §3.1: transitions
    DRAFT -> IRB_PENDING."""
    headers = pi_headers or TEST_USERS["pi_headers"]
    resp = api_client.submit_for_irb(trial_id, headers)
    return get_success_data(resp)


def submit_irb_review(trial_id: str, *,
                      decision: str = "APPROVED",
                      notes: str = "Approved by reviewer.",
                      reviewer_headers: Optional[Dict[str, str]] = None,
                      ) -> Dict[str, Any]:
    """POST /trials/{trial_id}/irb-reviews. PRD §3.2 SoD: the reviewer's
    X-User-ID must not equal the trial's created_by_user_id.

    By default we use TEST_USERS["irb_reviewer_headers"], whose id
    (IRB_REVIEWER_ID) is distinct from the default
    PRINCIPAL_INVESTIGATOR_ID — so the SoD check passes by default."""
    headers = reviewer_headers or TEST_USERS["irb_reviewer_headers"]
    resp = api_client.create_irb_review(
        trial_id,
        create_irb_review_payload(decision=decision, notes=notes),
        headers,
    )
    return get_success_data(resp)


def open_trial_for_enrollment(trial_id: str, *,
                              pi_headers: Optional[Dict[str, str]] = None,
                              ) -> Dict[str, Any]:
    """POST /trials/{trial_id}/open-enrollment. PRD §3.3."""
    headers = pi_headers or TEST_USERS["pi_headers"]
    resp = api_client.open_enrollment(trial_id, headers)
    return get_success_data(resp)


def re_get_trial(trial_id: str, *,
                 headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    """GET /trials/{trial_id}. Used to re-read a trial after cascade
    effects."""
    headers = headers or TEST_USERS["pi_headers"]
    resp = api_client.get_trial(trial_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 2: a trial ready for enrollment.
# ===========================================================================
def setup_trial_open_for_enrollment(
    *,
    randomization_scheme: str = "SIMPLE_BERNOULLI",
    block_size: Optional[int] = None,
    stratification_field: Optional[str] = None,
    target_enrollment: int = 10,
    blood_draw_window_days: int = 7,
    inclusion_criteria: Optional[List[Dict[str, Any]]] = None,
    exclusion_criteria: Optional[List[Dict[str, Any]]] = None,
    arm_weights: Optional[List[int]] = None,
    pi_headers: Optional[Dict[str, str]] = None,
    reviewer_headers: Optional[Dict[str, str]] = None,
    requires_re_consent_v1: bool = False,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Compose: trial DRAFT -> 2 arms -> publish v1 consent -> submit
    -> IRB approve -> open enrollment. Returns (trial, arms, v1).

    PRD §3.1 / §3.2 / §3.3 sequence; trial ends in OPEN_FOR_ENROLLMENT.
    """
    anchor_clock()
    if arm_weights is None:
        arm_weights = [1, 1]
    trial = create_trial_in_draft(
        randomization_scheme=randomization_scheme,
        block_size=block_size,
        stratification_field=stratification_field,
        target_enrollment=target_enrollment,
        blood_draw_window_days=blood_draw_window_days,
        inclusion_criteria=inclusion_criteria,
        exclusion_criteria=exclusion_criteria,
        pi_headers=pi_headers,
    )
    arms: List[Dict[str, Any]] = []
    for i, w in enumerate(arm_weights):
        arms.append(add_arm(
            trial["id"], code=f"A{i + 1}",
            label=f"Arm {i + 1}", weight=w,
            pi_headers=pi_headers,
        ))
    v1 = publish_consent_version(
        trial["id"], requires_re_consent=requires_re_consent_v1,
        pi_headers=pi_headers,
    )
    submit_trial_for_irb(trial["id"], pi_headers=pi_headers)
    submit_irb_review(
        trial["id"], decision="APPROVED",
        notes="Approved for enrollment.",
        reviewer_headers=reviewer_headers,
    )
    trial = open_trial_for_enrollment(
        trial["id"], pi_headers=pi_headers,
    )
    return trial, arms, v1


# ===========================================================================
# Participant creation / evaluate / consent / sign / enroll.
# ===========================================================================
def create_participant(trial_id: str, *,
                       profile: Optional[Dict[str, Any]] = None,
                       coord_headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    """POST /participants. PRD §3.4: StudyCoordinator only."""
    headers = coord_headers or TEST_USERS["study_coordinator_headers"]
    resp = api_client.create_participant(
        create_participant_payload(trial_id=trial_id, profile=profile),
        headers,
    )
    return get_success_data(resp)


def evaluate_participant(participant_id: str, *,
                         coord_headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    """POST /participants/{participant_id}/evaluate. PRD §3.4."""
    headers = coord_headers or TEST_USERS["study_coordinator_headers"]
    resp = api_client.evaluate_participant(participant_id, headers)
    return get_success_data(resp)


def request_consent(participant_id: str, *,
                    coord_headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    """POST /participants/{participant_id}/request-consent. PRD §3.5."""
    headers = coord_headers or TEST_USERS["study_coordinator_headers"]
    resp = api_client.request_consent(participant_id, headers)
    return get_success_data(resp)


def sign_consent(participant_id: str, *,
                 consent_version: int,
                 acting_headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    """POST /participants/{participant_id}/sign-consent.

    PRD §3.5: shared between Participant_self and StudyCoordinator. The
    default is to act AS THE PARTICIPANT THEMSELVES — we mint headers
    via make_participant_self_headers(participant_id) so the ownership
    check (PRD §2.1: "Participant_self may sign consent … only when
    participant_id == X-User-ID") passes when Participant_self is the
    acting role. Callers that prefer the StudyCoordinator pathway can
    supply acting_headers explicitly."""
    headers = acting_headers or make_participant_self_headers(
        participant_id,
    )
    resp = api_client.sign_consent(
        participant_id,
        sign_consent_payload(consent_version=consent_version),
        headers,
    )
    return get_success_data(resp)


def enroll_participant(trial_id: str, *,
                       active_consent_version: int,
                       profile: Optional[Dict[str, Any]] = None,
                       coord_headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    """SCREENING -> ELIGIBLE -> CONSENT_PENDING -> ENROLLED.

    This is the single helper most tests use to walk a brand-new
    participant all the way to ENROLLED. Sign-consent is performed by
    the Participant_self role using the participant's own id (PRD §2.1)
    to keep the ownership-gated path exercised in every test.
    """
    p = create_participant(
        trial_id, profile=profile, coord_headers=coord_headers,
    )
    p = evaluate_participant(p["id"], coord_headers=coord_headers)
    p = request_consent(p["id"], coord_headers=coord_headers)
    p = sign_consent(p["id"], consent_version=active_consent_version)
    return p


def re_get_participant(participant_id: str, *,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    """GET /participants/{participant_id}. By default uses the
    Participant_self headers so the read goes through the ownership
    path; a custom headers value (e.g., StudyCoordinator) can be passed
    for cross-role inspection."""
    headers = headers or make_participant_self_headers(participant_id)
    resp = api_client.get_participant(participant_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Visits.
# ===========================================================================
def schedule_visit(participant_id: str, *,
                   sequence_no: int,
                   target_date: str,
                   coord_headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    """POST /participants/{participant_id}/visits. PRD §3.6."""
    headers = coord_headers or TEST_USERS["study_coordinator_headers"]
    resp = api_client.create_visit(
        participant_id,
        create_visit_payload(
            sequence_no=sequence_no, target_date=target_date,
        ),
        headers,
    )
    return get_success_data(resp)


def complete_visit(visit_id: str, *,
                   actual_draw_at: str,
                   coord_headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    """POST /visits/{visit_id}/complete. PRD §3.6."""
    headers = coord_headers or TEST_USERS["study_coordinator_headers"]
    resp = api_client.complete_visit(
        visit_id,
        complete_visit_payload(actual_draw_at=actual_draw_at),
        headers,
    )
    return get_success_data(resp)


def list_payments(participant_id: str, *,
                  kind: Optional[str] = None,
                  headers: Optional[Dict[str, str]] = None,
                  ) -> List[Dict[str, Any]]:
    """GET /participants/{participant_id}/payments. By default reads as
    Participant_self for ownership exercise; tests can pass other
    headers."""
    headers = headers or make_participant_self_headers(participant_id)
    params = {}
    if kind is not None:
        params["kind"] = kind
    resp = api_client.list_payments(
        participant_id, headers,
        params=params if params else None,
    )
    data = get_success_data(resp)
    # PRD §2.2: list endpoints return data as the resource array.
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Some implementations return {"data": [...]} or similar; the
        # framework already extracts data, but defensively handle both.
        return list(data.get("payments", []))
    return []


# ===========================================================================
# Adverse events.
# ===========================================================================
def report_adverse_event(participant_id: str, *,
                         severity: str = "MILD",
                         narrative: Optional[str] = None,
                         caused_visit_id: Optional[str] = None,
                         coord_headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    """POST /participants/{participant_id}/adverse-events. PRD §3.7
    shares this endpoint between StudyCoordinator and
    PrincipalInvestigator."""
    headers = coord_headers or TEST_USERS["study_coordinator_headers"]
    resp = api_client.create_adverse_event(
        participant_id,
        create_adverse_event_payload(
            severity=severity, narrative=narrative,
            caused_visit_id=caused_visit_id,
        ),
        headers,
    )
    return get_success_data(resp)


def start_review_ae(participant_id: str, ae_id: str, *,
                    pi_headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    """POST AE start-review. PRD §3.7: PrincipalInvestigator only."""
    headers = pi_headers or TEST_USERS["pi_headers"]
    resp = api_client.start_review_adverse_event(
        participant_id, ae_id, headers,
    )
    return get_success_data(resp)


def resolve_ae(participant_id: str, ae_id: str, *,
               resolution_note: str = "Resolved.",
               pi_headers: Optional[Dict[str, str]] = None,
               ) -> Dict[str, Any]:
    """POST AE resolve. PRD §3.7: PrincipalInvestigator only."""
    headers = pi_headers or TEST_USERS["pi_headers"]
    resp = api_client.resolve_adverse_event(
        participant_id, ae_id,
        resolve_adverse_event_payload(resolution_note=resolution_note),
        headers,
    )
    return get_success_data(resp)


def withdraw_participant(participant_id: str, *,
                         reason: Optional[str] = None,
                         acting_headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    """POST /participants/{participant_id}/withdraw.

    PRD §3.7 / §2.1: shared between Participant_self and
    StudyCoordinator. The default acts via Participant_self with the
    participant's own id so the ownership check passes."""
    headers = acting_headers or make_participant_self_headers(
        participant_id,
    )
    resp = api_client.withdraw_participant(
        participant_id,
        withdraw_participant_payload(reason=reason),
        headers,
    )
    return get_success_data(resp)


def complete_participant(participant_id: str, *,
                         coord_headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    """POST /participants/{participant_id}/complete. PRD §3.8: triggers
    finalization."""
    headers = coord_headers or TEST_USERS["study_coordinator_headers"]
    resp = api_client.complete_participant(participant_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 3 — Pre-built scenarios used by multiple tests.
# ===========================================================================
def setup_enrolled_participant(
    *,
    blood_draw_window_days: int = 7,
    target_enrollment: int = 10,
    profile: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Compose: OPEN_FOR_ENROLLMENT trial + one ENROLLED participant.
    Returns (trial, participant, arms).

    Used by tests that need an enrolled participant but do not care
    about the consent / arm-assignment details.
    """
    trial, arms, v1 = setup_trial_open_for_enrollment(
        blood_draw_window_days=blood_draw_window_days,
        target_enrollment=target_enrollment,
    )
    p = enroll_participant(
        trial["id"],
        active_consent_version=v1["version"],
        profile=profile,
    )
    return trial, p, arms


def setup_participant_with_re_consent(
    *,
    blood_draw_window_days: int = 7,
    target_enrollment: int = 10,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Compose: OPEN_FOR_ENROLLMENT trial with both v1 and v2 published
    (v2 with requires_re_consent=true) + participant enrolled on v2.
    Returns (trial, participant, v1, v2).

    Per PRD §3.8 the re-consent bonus condition is characterised purely
    as: "the participant's signed_consent_version equals the trial's
    active_consent_version and at least one ConsentVersion row with
    version of 2 or higher exists on the trial — that is, the
    participant re-consented at least once during their enrollment".
    PRD declares no API for re-signing on an ENROLLED participant
    (sign-consent is only the CONSENT_PENDING -> ENROLLED transition
    per PRD §3.5), so the only PRD-faithful way to reach
    `signed_consent_version == active_consent_version >= 2` is to
    enroll on v2 directly while v2 is the active version.

    Used by difficulty-design instance
    `payment_provisional_vs_final_on_completed_participant` and the
    pinned-order finalization test.
    """
    trial, _arms, v1 = setup_trial_open_for_enrollment(
        blood_draw_window_days=blood_draw_window_days,
        target_enrollment=target_enrollment,
    )
    # Publish v2 BEFORE the participant signs, so the new active version
    # is 2 by the time enrollment closes.
    v2 = publish_consent_version(
        trial["id"], change_summary="Updated risk language for v2.",
        requires_re_consent=True,
    )
    p = enroll_participant(
        trial["id"], active_consent_version=v2["version"],
    )
    return trial, p, v1, v2


def schedule_three_visits_on_anchor_calendar(
    participant: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Schedule three visits whose target_dates are anchor+10d,
    anchor+17d, anchor+24d (spaced one week apart). Returns the visit
    list in order."""
    return [
        schedule_visit(
            participant["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        ),
        schedule_visit(
            participant["id"], sequence_no=2,
            target_date=iso_anchor_offset(days=17),
        ),
        schedule_visit(
            participant["id"], sequence_no=3,
            target_date=iso_anchor_offset(days=24),
        ),
    ]


def setup_participant_with_three_on_time_visits_after_reconsent(
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Compose the canonical scenario used by the dual_variant_calc and
    combinatorial_formula difficulty-design instances:

      Trial OPEN_FOR_ENROLLMENT (window=7, target=10) ->
      Participant enrolled on v1 -> v2 published (requires_re_consent)
      -> participant re-signs v2 -> three visits scheduled on
      anchor+10, anchor+17, anchor+24 -> clock advanced to each
      target_date and visit completed (d=0).

    Returns (trial, participant, completed_visits).

    After this setup:
      - Each visit has PROVISIONAL Payment with amount_cents == 6000
        (BASE 5000 + ON_TIME 1000).
      - signed_consent_version == 2 == active_consent_version.
      - A ConsentVersion with version >= 2 exists.
      - Participant is still ENROLLED — ready for participant-complete.
    """
    trial, participant, _v1, _v2 = setup_participant_with_re_consent(
        blood_draw_window_days=7,
    )
    visits = schedule_three_visits_on_anchor_calendar(participant)
    completed: List[Dict[str, Any]] = []
    for v in visits:
        # Advance to target_date (date-only; PRD §2.9 normalizes to
        # date) and submit actual_draw_at == target_date.
        target_iso = v["target_date"]
        # Strip any time-of-day; complete at 12:00 UTC on target_date.
        target_day = parse_iso(target_iso).date()
        anchor = parse_anchor()
        days_offset = (target_day - anchor.date()).days
        clock_to = iso_anchor_offset(days=days_offset, hours=12)
        advance_clock_to(clock_to)
        completed.append(complete_visit(
            v["id"], actual_draw_at=clock_to,
        ))
    return trial, participant, completed


# ===========================================================================
# Boundary-precision targeting helpers.
# ===========================================================================
def setup_trial_with_target_enrollment(
    target_enrollment: int, *,
    blood_draw_window_days: int = 7,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Open a trial with the SPECIFIED target_enrollment. Used by the
    target_enrollment boundary test (target_enrollment=2 lets the test
    enroll Pa, Pb successfully and then attempt Pc which must fail with
    ERR_TRIAL_FULL).

    PRD §3.5: "the trial's enrolled_count is strictly less than
    target_enrollment (otherwise ERR_TRIAL_FULL)".
    """
    return setup_trial_open_for_enrollment(
        target_enrollment=target_enrollment,
        blood_draw_window_days=blood_draw_window_days,
    )


def fill_consent_pending_for_n_participants(
    trial: Dict[str, Any], n: int,
) -> List[Dict[str, Any]]:
    """Create N participants and walk them to CONSENT_PENDING but stop
    short of sign-consent. Returns the participants in creation order.
    """
    parked: List[Dict[str, Any]] = []
    for _ in range(n):
        p = create_participant(trial["id"])
        p = evaluate_participant(p["id"])
        p = request_consent(p["id"])
        parked.append(p)
    return parked


# ===========================================================================
# Cross-entity / cascade-targeting fixtures.
# ===========================================================================
def setup_enrolled_with_one_completed_visit(
    *,
    blood_draw_window_days: int = 7,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Compose: OPEN_FOR_ENROLLMENT trial -> P1 ENROLLED -> schedule
    V1 (anchor+10) -> advance clock to anchor+10 -> complete V1
    on-time. Returns (trial, participant, v1_visit, v1_payment).

    Used by withdraw-cascade and AE-escalate-cascade tests. The
    PROVISIONAL Payment row written at completion is captured for the
    money-conservation invariant test.
    """
    trial, _arms, v1 = setup_trial_open_for_enrollment(
        blood_draw_window_days=blood_draw_window_days,
    )
    p = enroll_participant(
        trial["id"], active_consent_version=v1["version"],
    )
    visit = schedule_visit(
        p["id"], sequence_no=1,
        target_date=iso_anchor_offset(days=10),
    )
    advance_clock_to(iso_anchor_offset(days=10, hours=12))
    visit = complete_visit(
        visit["id"],
        actual_draw_at=iso_anchor_offset(days=10, hours=12),
    )
    payments = list_payments(p["id"], kind="PROVISIONAL")
    assert payments, "setup expected PROVISIONAL payment after complete"
    return trial, p, visit, payments[-1]


def setup_two_arms_irb_pending() -> Tuple[
    Dict[str, Any], List[Dict[str, Any]], Dict[str, Any],
]:
    """Compose: trial DRAFT -> 2 arms -> publish v1 -> submit-for-irb.
    Trial ends in IRB_PENDING. Returns (trial, arms, v1).

    Used by the trial_branching_irb_revisions_loop difficulty test.
    """
    anchor_clock()
    trial = create_trial_in_draft()
    arms = [
        add_arm(trial["id"], code="A1", label="Arm 1", weight=1),
        add_arm(trial["id"], code="A2", label="Arm 2", weight=1),
    ]
    v1 = publish_consent_version(trial["id"])
    trial = submit_trial_for_irb(trial["id"])
    return trial, arms, v1


def setup_approved_irb_trial() -> Tuple[
    Dict[str, Any], List[Dict[str, Any]], Dict[str, Any],
]:
    """Compose: trial DRAFT -> 2 arms -> publish v1 -> submit-for-irb
    -> IRB approves. Trial ends in APPROVED with
    irb_approval_expires_at set. Returns (trial, arms, v1)."""
    trial, arms, v1 = setup_two_arms_irb_pending()
    submit_irb_review(trial["id"], decision="APPROVED",
                      notes="Approved.")
    trial = re_get_trial(trial["id"])
    return trial, arms, v1


# ===========================================================================
# SoD-violating setup — explicitly mints a reviewer header whose
# X-User-ID equals the trial creator's id, to provoke ERR_SOD_VIOLATION.
# ===========================================================================
def setup_irb_pending_for_sod_violation() -> Tuple[
    Dict[str, Any], Dict[str, str],
]:
    """Compose: PI creates trial; trial reaches IRB_PENDING. Returns
    (trial, reviewer_headers_that_match_pi_id).

    The returned reviewer_headers deliberately carry X-User-ID equal
    to the creating PI's X-User-ID so any irb-reviews call with these
    headers fires ERR_SOD_VIOLATION per PRD §2.5.
    """
    anchor_clock()
    pi_headers = make_pi_headers(PRINCIPAL_INVESTIGATOR_ID)
    trial = create_trial_in_draft(pi_headers=pi_headers)
    add_arm(trial["id"], code="A1", label="Arm 1", weight=1,
            pi_headers=pi_headers)
    add_arm(trial["id"], code="A2", label="Arm 2", weight=1,
            pi_headers=pi_headers)
    publish_consent_version(trial["id"], pi_headers=pi_headers)
    trial = submit_trial_for_irb(trial["id"], pi_headers=pi_headers)
    # Mint reviewer headers whose X-User-ID == PRINCIPAL_INVESTIGATOR_ID.
    from .test_users import make_irb_reviewer_headers  # local import.
    bad_reviewer_headers = make_irb_reviewer_headers(
        PRINCIPAL_INVESTIGATOR_ID,
    )
    return trial, bad_reviewer_headers


# ===========================================================================
# Convenience getters used in the cascade / invariant tests.
# ===========================================================================
def re_get_visit(visit_id: str, *,
                 headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    """Re-read a Visit by listing all visits on its participant.

    PRD §4 does not declare a singleton GET /visits/{id} endpoint, so
    this helper fetches via the listing path. The caller passes the
    participant_id implicitly through the visit row already in hand.
    """
    raise NotImplementedError(
        "GET /visits/{id} is not declared in PRD §4. Tests should "
        "re-read visits via list_visits_for_participant.",
    )


def list_visits_for_participant(
    participant_id: str, *,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """GET /participants/{participant_id}/visits. By default reads via
    StudyCoordinator (PRD §4 authorizes PrincipalInvestigator,
    StudyCoordinator, and Participant_self self-only)."""
    headers = headers or TEST_USERS["study_coordinator_headers"]
    resp = api_client.list_visits(participant_id, headers)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return []


def find_visit_in_list(visits: List[Dict[str, Any]],
                       visit_id: str) -> Dict[str, Any]:
    """Locate a visit by id within a list response. Raises assertion if
    missing."""
    for v in visits:
        if v.get("id") == visit_id:
            return v
    raise AssertionError(
        f"visit {visit_id} not found among {len(visits)} listed visits",
    )


def list_irb_reviews(trial_id: str, *,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> List[Dict[str, Any]]:
    """GET /trials/{trial_id}/irb-reviews. PRD §4 authorizes PI and
    IRBReviewer."""
    headers = headers or TEST_USERS["pi_headers"]
    resp = api_client.list_irb_reviews(trial_id, headers)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return []


def list_aes(participant_id: str, *,
             status: Optional[str] = None,
             headers: Optional[Dict[str, str]] = None,
             ) -> List[Dict[str, Any]]:
    """GET /participants/{participant_id}/adverse-events."""
    headers = headers or TEST_USERS["study_coordinator_headers"]
    params: Dict[str, Any] = {}
    if status is not None:
        params["status"] = status
    resp = api_client.list_adverse_events(
        participant_id, headers,
        params=params if params else None,
    )
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return []


__all__ = [
    # clock
    "advance_clock_to",
    "anchor_clock",
    # raw setup primitives
    "create_trial_in_draft",
    "add_arm",
    "publish_consent_version",
    "submit_trial_for_irb",
    "submit_irb_review",
    "open_trial_for_enrollment",
    "re_get_trial",
    "create_participant",
    "evaluate_participant",
    "request_consent",
    "sign_consent",
    "enroll_participant",
    "re_get_participant",
    "schedule_visit",
    "complete_visit",
    "list_payments",
    "report_adverse_event",
    "start_review_ae",
    "resolve_ae",
    "withdraw_participant",
    "complete_participant",
    # composite scenarios
    "setup_trial_open_for_enrollment",
    "setup_enrolled_participant",
    "setup_participant_with_re_consent",
    "setup_participant_with_three_on_time_visits_after_reconsent",
    "schedule_three_visits_on_anchor_calendar",
    "setup_trial_with_target_enrollment",
    "fill_consent_pending_for_n_participants",
    "setup_enrolled_with_one_completed_visit",
    "setup_two_arms_irb_pending",
    "setup_approved_irb_trial",
    "setup_irb_pending_for_sod_violation",
    # listing helpers
    "list_visits_for_participant",
    "find_visit_in_list",
    "list_irb_reviews",
    "list_aes",
]
