"""Composite setup helpers — multi-step preambles tests can reuse.

A background-check lifecycle moves through many states before
interesting claims can be tested. The minimum preamble for an
adjudication-decision test is:

  1. Seed a JurisdictionPolicy for the candidate's residence state
     (PlatformAdmin) — PRD §3.1.
  2. Register a Candidate (Recruiter) — PRD §3.1.
  3. Record an ACTIVE ConsentDisclosure (Candidate or Recruiter on
     behalf of) — PRD §3.2.
  4. Open a BackgroundCheckOrder (Recruiter) — PRD §3.3.
  5. Start verification (Recruiter) — PRD §3.4.
  6. Vendor returns each VerificationItem (Verifier) — PRD §3.4.
  7. The system cascades parent into AWAITING_ADJUDICATION and the
     composite_decision is computed — PRD §3.5.

For Pre-Adverse / Final Adverse tests add:

  8. Adjudicator issues Pre-Adverse — PRD §3.6.
  9. Clock advance (PlatformAdmin) by the cooling-off period.
 10. PlatformAdmin runs sweep (PRD §3.10) -> order to AWAITING_FINAL.
 11. Adjudicator issues Final Adverse — PRD §3.8.

IDENTITY THREADING — PRD §2.1:

    "When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the
    acting `Candidate`; ownership checks on any resource that
    references a `Candidate` (consent disclosures, orders, verification
    items, disputes) compare the resource's foreign-key `candidate_id`
    to `X-User-ID`."

Every fixture that opens a dispute, or revokes consent, etc., mints
candidate headers via `make_candidate_headers(candidate_id)` from the
server-minted Candidate.id so the request passes ownership checks.

SEGREGATION OF DUTIES — PRD §2.11:

    "The Adjudicator's `X-User-ID` must differ from the
    `BackgroundCheckOrder.opened_by_user_id` recorded when the order
    was opened."

Lifecycle fixtures default to DISTINCT shared ids for Recruiter
(opening the order) and Adjudicator (issuing Pre-Adverse / Final
Adverse / resolving disputes) so the SoD check is satisfied along the
happy path. Tests that probe SoD failure deliberately collide the
two ids.

CLOCK — PRD §3.10:

    "The clock-advance capability accepts a `seconds` integer and
    pushes the server's current time forward by that many seconds; no
    automatic state transitions fire as a result. The sweep capability
    then promotes every order whose flow has reached the conditions
    for `READY_FOR_FINAL`."

Tests cannot read the server clock directly. Fixtures advance by an
explicit `seconds` value; absolute anchors come from server-stamped
timestamps such as `AdverseActionFlow.pre_adverse_notice_sent_at`.

Setup calls use `get_success_data` (lenient 2xx validator) so setup
failures surface as 'Setup failed' rather than confusing assertion
failures downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BUSINESS_DAYS_PER_WEEK,
    FEDERAL_MIN_BUSINESS_DAYS,
    JURISDICTION_CODES,
    TEST_DEFAULTS,
)
from .factories import (
    add_business_days,
    add_days,
    add_hours,
    add_seconds,
    clock_advance_payload,
    create_candidate_payload,
    create_dispute_payload,
    create_order_payload,
    criminal_raw_finding,
    education_raw_finding,
    iso_utc,
    mvr_raw_finding,
    parse_iso,
    record_consent_payload,
    request_rework_payload,
    resolve_dispute_payload,
    return_item_payload,
    sha256_hex,
    unique_disclosure_hash,
    unique_email,
    unique_full_name,
    upsert_jurisdiction_policy_payload,
)
from .test_users import (
    ADJUDICATOR_SHARED_ID,
    PLATFORM_ADMIN_SHARED_ID,
    RECRUITER_SHARED_ID,
    TEST_USERS,
    make_adjudicator_headers,
    make_candidate_headers,
    make_platform_admin_headers,
    make_recruiter_headers,
    make_verifier_headers,
)


# ===========================================================================
# Jurisdiction policy seeding — PRD §3.1
# ===========================================================================
def upsert_jurisdiction_policy(
    *,
    code: str,
    criminal_lookback_years: int = 7,
    salary_history_ban: bool = False,
    ban_the_box_stage: str = "PRE_OFFER",
    adverse_action_waiting_business_days: int = 5,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Idempotent upsert of a JurisdictionPolicy. Sets safe defaults
    that satisfy PRD §3.1: ban_the_box_stage=PRE_OFFER permits any
    stage_at_order; adverse_action_waiting_business_days >= 5
    (federal floor)."""
    h = admin_headers or TEST_USERS["platform_admin_headers"]
    payload = upsert_jurisdiction_policy_payload(
        criminal_lookback_years=criminal_lookback_years,
        salary_history_ban=salary_history_ban,
        ban_the_box_stage=ban_the_box_stage,
        adverse_action_waiting_business_days=
        adverse_action_waiting_business_days,
    )
    return get_success_data(
        api_client.upsert_jurisdiction_policy(code, payload, h)
    )


def ensure_all_default_policies() -> None:
    """Seed every supported jurisdiction with a permissive default
    policy so tests that don't care about jurisdiction can proceed
    without each one repeating the upsert."""
    for code in JURISDICTION_CODES:
        upsert_jurisdiction_policy(
            code=code,
            criminal_lookback_years=7,
            salary_history_ban=False,
            ban_the_box_stage="PRE_OFFER",
            adverse_action_waiting_business_days=5,
        )


# ===========================================================================
# Clock + sweep helpers — PRD §3.10
# ===========================================================================
def clock_advance_seconds(seconds: int,
                          headers: Optional[Dict[str, str]] = None,
                          ) -> None:
    """Advance the logical clock by `seconds` (must be > 0).

    PRD §3.10: "The clock-advance capability accepts a `seconds`
    integer and pushes the server's current time forward by that many
    seconds".
    """
    if seconds <= 0:
        return
    h = headers or TEST_USERS["platform_admin_headers"]
    get_success_data(
        api_client.clock_advance(
            clock_advance_payload(seconds=seconds), h,
        )
    )


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run the periodic sweep (PRD §3.10).

    Promotes flows whose cooling-off has elapsed and recomputes
    eligibility_posture for candidates whose 365-day LOCKED window has
    expired.
    """
    h = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.run_sweep(h)) or {}


def advance_business_days_and_sweep(business_days: int,
                                    extra_seconds: int = 60,
                                    ) -> None:
    """Advance the clock by at least `business_days` business days.

    Because the test clock advances by seconds, we use a conservative
    calendar-day count: each business day is 1 calendar day, but to
    safely cross weekends we add 7-day chunks for every 5 business
    days. PRD §3.10 separates clock advance from sweep, so this helper
    advances first and then runs the sweep.
    """
    # Cover weekends: ceil(business_days / 5) full weeks plus the
    # remainder as calendar days, then add slack.
    weeks = business_days // BUSINESS_DAYS_PER_WEEK
    remainder = business_days % BUSINESS_DAYS_PER_WEEK
    calendar_days = weeks * 7 + remainder + 2  # +2 days slack for weekend
    seconds = calendar_days * 24 * 3600 + extra_seconds
    clock_advance_seconds(seconds)
    run_sweep()


# ===========================================================================
# Candidate / consent / order — PRD §3.1, §3.2, §3.3
# ===========================================================================
def create_candidate(
    *,
    residence_jurisdiction: str = "CA",
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    date_of_birth: str = "1990-01-15",
    recruiter_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Recruiter creates a candidate. The jurisdiction's policy MUST
    already exist (call `upsert_jurisdiction_policy` first or rely on
    `ensure_all_default_policies`)."""
    h = recruiter_headers or TEST_USERS["recruiter_headers"]
    payload = create_candidate_payload(
        full_name=full_name,
        email=email,
        residence_jurisdiction=residence_jurisdiction,
        date_of_birth=date_of_birth,
    )
    return get_success_data(api_client.create_candidate(payload, h))


def record_consent_as_candidate(
    *,
    candidate_id: str,
    consent_signature: str = "Signed: I, the candidate, consent.",
    disclosure_text_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Candidate self-records a ConsentDisclosure with the candidate's
    own X-User-ID. PRD §3.2 lets either Recruiter or Candidate record
    consent; we route through the Candidate to exercise the entity-
    backed identity threading.
    """
    h = make_candidate_headers(candidate_id)
    payload = record_consent_payload(
        disclosure_text_hash=disclosure_text_hash,
        consent_signature=consent_signature,
    )
    return get_success_data(
        api_client.record_consent(candidate_id, payload, h)
    )


def record_consent_as_recruiter(
    *,
    candidate_id: str,
    consent_signature: str = "Signed on behalf of the candidate.",
    disclosure_text_hash: Optional[str] = None,
    recruiter_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Recruiter records a ConsentDisclosure on behalf of the
    candidate. Used by fixtures whose tests don't need to exercise
    candidate-side identity."""
    h = recruiter_headers or TEST_USERS["recruiter_headers"]
    payload = record_consent_payload(
        disclosure_text_hash=disclosure_text_hash,
        consent_signature=consent_signature,
    )
    return get_success_data(
        api_client.record_consent(candidate_id, payload, h)
    )


def open_order(
    *,
    candidate_id: str,
    consent_disclosure_id: str,
    stage_at_order: str = "POST_OFFER",
    requested_packages: Optional[List[str]] = None,
    recruiter_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Recruiter opens a BackgroundCheckOrder. PRD §3.3."""
    h = recruiter_headers or TEST_USERS["recruiter_headers"]
    payload = create_order_payload(
        candidate_id=candidate_id,
        consent_disclosure_id=consent_disclosure_id,
        stage_at_order=stage_at_order,
        requested_packages=requested_packages or
        ["CRIMINAL", "MVR", "EDUCATION"],
    )
    return get_success_data(api_client.create_order(payload, h))


def start_verification(
    order_id: str,
    recruiter_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Recruiter moves the order INTAKE -> IN_VERIFICATION. PRD §3.4."""
    h = recruiter_headers or TEST_USERS["recruiter_headers"]
    return get_success_data(
        api_client.start_verification(order_id, h)
    )


def get_order(order_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["recruiter_headers"]
    return get_success_data(api_client.get_order(order_id, h))


def get_candidate(candidate_id: str,
                  headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    h = headers or TEST_USERS["recruiter_headers"]
    return get_success_data(api_client.get_candidate(candidate_id, h))


def list_verification_items_for_order(
    order_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Discover the child VerificationItems of an order and GET each.

    The PRD spawns one VerificationItem per requested_packages entry at
    order-open time (§3.3), but no list-by-order endpoint is defined.
    The order-create / order-get response carries a `verification_items`
    summary (id + kind) of the spawned items; we use those ids to GET
    each full VerificationItem row. As a fallback for implementations
    that do not surface this summary, we also walk the audit trail and
    pick up subject_entity == VerificationItem rows (events appear only
    after the item has RETURNED / FAILED / etc.).
    """
    h = headers or TEST_USERS["recruiter_headers"]
    order_resp = api_client.get_order(order_id, h)
    order = get_success_data(order_resp)
    item_ids: List[str] = []
    summaries = (order or {}).get("verification_items") or []
    for s in summaries:
        sid = s.get("id") if isinstance(s, dict) else None
        if sid and sid not in item_ids:
            item_ids.append(sid)
    if not item_ids:
        # Fallback: walk the audit trail for any VerificationItem rows
        # that have already produced events (RETURNED / FAILED / ...).
        audit_resp = api_client.get_audit_trail(order_id, h)
        audit = get_success_data(audit_resp)
        events: List[Dict[str, Any]] = (
            audit if isinstance(audit, list)
            else audit.get("items", [])
        )
        for e in events:
            if e.get("subject_entity") == "VerificationItem":
                sid = e.get("subject_id")
                if sid and sid not in item_ids:
                    item_ids.append(sid)
    items: List[Dict[str, Any]] = []
    for iid in item_ids:
        items.append(
            get_success_data(api_client.get_verification_item(iid, h))
        )
    return items


def return_item(
    *,
    item_id: str,
    raw_finding: Dict[str, Any],
    verifier_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Verifier returns a raw_finding on a VerificationItem. PRD §3.4."""
    h = verifier_headers or TEST_USERS["verifier_headers"]
    payload = return_item_payload(raw_finding=raw_finding)
    return get_success_data(
        api_client.return_verification_item(item_id, payload, h)
    )


# ===========================================================================
# Composite — Tier 1: candidate + consent ready, no order yet
# ===========================================================================
def setup_candidate_with_consent(
    *,
    residence_jurisdiction: str = "CA",
    jurisdiction_kwargs: Optional[Dict[str, Any]] = None,
    recruiter_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Seed the jurisdiction, register a candidate, record consent.

    Returns (candidate, consent). The candidate's
    `eligibility_posture` is `ELIGIBLE` (PRD §3.1 initial value); the
    consent's `status` is `ACTIVE` (PRD §3.2 initial value).
    """
    jk = dict(jurisdiction_kwargs or {})
    upsert_jurisdiction_policy(code=residence_jurisdiction, **jk)
    candidate = create_candidate(
        residence_jurisdiction=residence_jurisdiction,
        recruiter_headers=recruiter_headers,
    )
    consent = record_consent_as_recruiter(
        candidate_id=candidate["id"],
        recruiter_headers=recruiter_headers,
    )
    return candidate, consent


# ===========================================================================
# Composite — Tier 2: order in INTAKE
# ===========================================================================
def setup_order_in_intake(
    *,
    residence_jurisdiction: str = "CA",
    jurisdiction_kwargs: Optional[Dict[str, Any]] = None,
    stage_at_order: str = "POST_OFFER",
    requested_packages: Optional[List[str]] = None,
    recruiter_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """candidate + consent + INTAKE order.

    Returns (candidate, consent, order).
    """
    candidate, consent = setup_candidate_with_consent(
        residence_jurisdiction=residence_jurisdiction,
        jurisdiction_kwargs=jurisdiction_kwargs,
        recruiter_headers=recruiter_headers,
    )
    order = open_order(
        candidate_id=candidate["id"],
        consent_disclosure_id=consent["id"],
        stage_at_order=stage_at_order,
        requested_packages=requested_packages,
        recruiter_headers=recruiter_headers,
    )
    return candidate, consent, order


# ===========================================================================
# Composite — Tier 3: order in IN_VERIFICATION (items IN_PROGRESS)
# ===========================================================================
def setup_order_in_verification(
    *,
    residence_jurisdiction: str = "CA",
    jurisdiction_kwargs: Optional[Dict[str, Any]] = None,
    stage_at_order: str = "POST_OFFER",
    requested_packages: Optional[List[str]] = None,
    recruiter_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           List[Dict[str, Any]]]:
    """candidate + consent + order moved to IN_VERIFICATION.

    Returns (candidate, consent, order, items). `items` are GETs after
    start-verification so their `status` should be IN_PROGRESS.
    """
    candidate, consent, order = setup_order_in_intake(
        residence_jurisdiction=residence_jurisdiction,
        jurisdiction_kwargs=jurisdiction_kwargs,
        stage_at_order=stage_at_order,
        requested_packages=requested_packages,
        recruiter_headers=recruiter_headers,
    )
    order = start_verification(order["id"], recruiter_headers)
    items = list_verification_items_for_order(order["id"], recruiter_headers)
    return candidate, consent, order, items


# ===========================================================================
# Composite — Tier 4: order in AWAITING_ADJUDICATION
# ===========================================================================
def setup_order_in_awaiting_adjudication(
    *,
    residence_jurisdiction: str = "CA",
    jurisdiction_kwargs: Optional[Dict[str, Any]] = None,
    stage_at_order: str = "POST_OFFER",
    requested_packages: Optional[List[str]] = None,
    findings_by_kind: Optional[Dict[str, Dict[str, Any]]] = None,
    recruiter_headers: Optional[Dict[str, str]] = None,
    verifier_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           List[Dict[str, Any]]]:
    """candidate + consent + order moved to AWAITING_ADJUDICATION via
    Verifier returns on each item.

    `findings_by_kind` maps item.kind -> raw_finding dict. Default is
    a clean finding for every kind so composite_decision == CLEAR (and
    in fact the order auto-promotes to COMPLETED_CLEAR; callers that
    need a non-clean adjudication must override).

    Returns (candidate, consent, order_after, items_after).
    """
    candidate, consent, order, items = setup_order_in_verification(
        residence_jurisdiction=residence_jurisdiction,
        jurisdiction_kwargs=jurisdiction_kwargs,
        stage_at_order=stage_at_order,
        requested_packages=requested_packages,
        recruiter_headers=recruiter_headers,
    )
    findings_by_kind = findings_by_kind or {
        "CRIMINAL": criminal_raw_finding(
            conviction_date="2024-01-01",
            severity="INFRACTION",
        ),
        "MVR": mvr_raw_finding(
            violations_3yr=0, license_status="VALID",
        ),
        "EDUCATION": education_raw_finding(
            institution="Test University",
            claim_verified=True,
        ),
    }
    # Return every item with the kind-matched finding.
    for it in items:
        kind = it["kind"]
        if kind in findings_by_kind:
            return_item(
                item_id=it["id"],
                raw_finding=findings_by_kind[kind],
                verifier_headers=verifier_headers,
            )
    order_after = get_order(order["id"], recruiter_headers)
    items_after = list_verification_items_for_order(
        order["id"], recruiter_headers,
    )
    return candidate, consent, order_after, items_after


# ===========================================================================
# Composite — Tier 5: order in PRE_ADVERSE_ISSUED
# ===========================================================================
def setup_order_pre_adverse(
    *,
    residence_jurisdiction: str = "CA",
    jurisdiction_kwargs: Optional[Dict[str, Any]] = None,
    stage_at_order: str = "POST_OFFER",
    requested_packages: Optional[List[str]] = None,
    findings_by_kind: Optional[Dict[str, Dict[str, Any]]] = None,
    recruiter_headers: Optional[Dict[str, str]] = None,
    verifier_headers: Optional[Dict[str, str]] = None,
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           List[Dict[str, Any]], Dict[str, Any]]:
    """Drive a complete order through to PRE_ADVERSE_ISSUED.

    Default findings push composite_decision to INELIGIBLE so the
    Adjudicator can legitimately issue Pre-Adverse: CRIMINAL FELONY
    aged 1 year (severity=70) plus state cut for CA=80 yields
    aggregate=70 -> CONSIDER. To force INELIGIBLE, callers may set
    `findings_by_kind` with multiple FELONY-like items or pick a
    jurisdiction with a lower cut.

    Returns (candidate, consent, order, items, flow). `flow` is the
    AdverseActionFlow row created by Pre-Adverse.
    """
    requested_packages = requested_packages or [
        "CRIMINAL", "MVR", "EDUCATION",
    ]
    # Default = enough to be CONSIDER (>=30 aggregate).
    findings_by_kind = findings_by_kind or {
        "CRIMINAL": criminal_raw_finding(
            conviction_date="2024-01-01",  # roughly 2 years ago in 2026
            severity="FELONY",
        ),
        "MVR": mvr_raw_finding(
            violations_3yr=0, license_status="VALID",
        ),
        "EDUCATION": education_raw_finding(
            institution="Test University",
            claim_verified=True,
        ),
    }
    candidate, consent, order, items = (
        setup_order_in_awaiting_adjudication(
            residence_jurisdiction=residence_jurisdiction,
            jurisdiction_kwargs=jurisdiction_kwargs,
            stage_at_order=stage_at_order,
            requested_packages=requested_packages,
            findings_by_kind=findings_by_kind,
            recruiter_headers=recruiter_headers,
            verifier_headers=verifier_headers,
        )
    )
    # Adjudicator MUST be a DIFFERENT X-User-ID from Recruiter
    # (PRD §2.11 SoD).
    ah = adjudicator_headers or TEST_USERS["adjudicator_headers"]
    flow = get_success_data(
        api_client.issue_pre_adverse(order["id"], ah)
    )
    order_after = get_order(order["id"], recruiter_headers)
    items_after = list_verification_items_for_order(
        order["id"], recruiter_headers,
    )
    return candidate, consent, order_after, items_after, flow


# ===========================================================================
# Composite — Tier 6: order in AWAITING_FINAL (cooling-off elapsed, sweep)
# ===========================================================================
def setup_order_awaiting_final(
    *,
    residence_jurisdiction: str = "CA",
    jurisdiction_kwargs: Optional[Dict[str, Any]] = None,
    stage_at_order: str = "POST_OFFER",
    findings_by_kind: Optional[Dict[str, Dict[str, Any]]] = None,
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           List[Dict[str, Any]], Dict[str, Any]]:
    """Drive an order through Pre-Adverse, advance the clock past the
    cooling-off, and sweep to AWAITING_FINAL.

    Returns (candidate, consent, order_after, items, flow_after).
    """
    candidate, consent, order, items, flow = setup_order_pre_adverse(
        residence_jurisdiction=residence_jurisdiction,
        jurisdiction_kwargs=jurisdiction_kwargs,
        stage_at_order=stage_at_order,
        findings_by_kind=findings_by_kind,
        adjudicator_headers=adjudicator_headers,
    )
    waiting = flow.get("waiting_period_business_days") or \
        FEDERAL_MIN_BUSINESS_DAYS
    # Advance past the cooling-off with slack and sweep.
    advance_business_days_and_sweep(business_days=waiting + 1)
    order_after = get_order(order["id"])
    flow_resp = api_client.get_order(order["id"], TEST_USERS["recruiter_headers"])
    _ = flow_resp  # eligible to drop if not used elsewhere
    items_after = list_verification_items_for_order(order["id"])
    return candidate, consent, order_after, items_after, flow


# ===========================================================================
# Composite — Tier 7: order in TERMINATED_ADVERSE (Final Adverse issued)
# ===========================================================================
def setup_order_terminated_adverse(
    *,
    residence_jurisdiction: str = "CA",
    jurisdiction_kwargs: Optional[Dict[str, Any]] = None,
    stage_at_order: str = "POST_OFFER",
    findings_by_kind: Optional[Dict[str, Dict[str, Any]]] = None,
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           List[Dict[str, Any]], Dict[str, Any]]:
    """Drive to TERMINATED_ADVERSE. Returns (candidate, consent,
    order_after, items, flow)."""
    candidate, consent, order, items, flow = setup_order_awaiting_final(
        residence_jurisdiction=residence_jurisdiction,
        jurisdiction_kwargs=jurisdiction_kwargs,
        stage_at_order=stage_at_order,
        findings_by_kind=findings_by_kind,
        adjudicator_headers=adjudicator_headers,
    )
    ah = adjudicator_headers or TEST_USERS["adjudicator_headers"]
    get_success_data(
        api_client.issue_final_adverse(order["id"], ah)
    )
    order_after = get_order(order["id"])
    items_after = list_verification_items_for_order(order["id"])
    return candidate, consent, order_after, items_after, flow


# ===========================================================================
# Disputes & rework — PRD §3.7
# ===========================================================================
def open_dispute_as_candidate(
    *,
    candidate_id: str,
    verification_item_id: str,
    reason_text: str = "I dispute this finding.",
) -> Dict[str, Any]:
    """Candidate opens a dispute on a verification item.

    Identity threading is mandatory: the candidate's id is the
    X-User-ID per PRD §2.1, so ownership check on the item's order
    succeeds.
    """
    h = make_candidate_headers(candidate_id)
    payload = create_dispute_payload(
        verification_item_id=verification_item_id,
        reason_text=reason_text,
    )
    return get_success_data(api_client.create_dispute(payload, h))


def resolve_dispute_as_adjudicator(
    *,
    dispute_id: str,
    status: str,
    resolution_note: str = "Resolved.",
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Adjudicator resolves a dispute. PRD §3.7."""
    h = adjudicator_headers or TEST_USERS["adjudicator_headers"]
    payload = resolve_dispute_payload(
        status=status, resolution_note=resolution_note,
    )
    return get_success_data(
        api_client.resolve_dispute(dispute_id, payload, h)
    )


def request_rework_on_order(
    *,
    order_id: str,
    target_item_ids: List[str],
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Adjudicator requests rework on a PRE_ADVERSE_ISSUED order."""
    h = adjudicator_headers or TEST_USERS["adjudicator_headers"]
    payload = request_rework_payload(target_item_ids=target_item_ids)
    return get_success_data(
        api_client.request_rework(order_id, payload, h)
    )


# ===========================================================================
# Difficulty-design fixtures (purpose-built composites)
# ===========================================================================
def setup_two_candidates_same_findings_different_states(
    *,
    state_a: str = "CA",
    state_b: str = "TX",
    findings_by_kind: Optional[Dict[str, Dict[str, Any]]] = None,
    jurisdiction_kwargs_a: Optional[Dict[str, Any]] = None,
    jurisdiction_kwargs_b: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """For dual-variant adjudication-decision tests: two candidates in
    different states with IDENTICAL VerificationItem findings.

    The order's `requested_packages` is restricted to exactly the
    kinds present in `findings_by_kind` so every spawned item can be
    returned and the order can reach AWAITING_ADJUDICATION (or
    COMPLETED_CLEAR if findings are clean).

    Returns ({"candidate", "consent", "order", "items"} for each
    state).
    """
    if findings_by_kind:
        requested_packages = list(findings_by_kind.keys())
    else:
        requested_packages = None
    cand_a, cons_a, ord_a, items_a = (
        setup_order_in_awaiting_adjudication(
            residence_jurisdiction=state_a,
            jurisdiction_kwargs=jurisdiction_kwargs_a,
            requested_packages=requested_packages,
            findings_by_kind=findings_by_kind,
        )
    )
    cand_b, cons_b, ord_b, items_b = (
        setup_order_in_awaiting_adjudication(
            residence_jurisdiction=state_b,
            jurisdiction_kwargs=jurisdiction_kwargs_b,
            requested_packages=requested_packages,
            findings_by_kind=findings_by_kind,
        )
    )
    return (
        {"candidate": cand_a, "consent": cons_a,
         "order": ord_a, "items": items_a},
        {"candidate": cand_b, "consent": cons_b,
         "order": ord_b, "items": items_b},
    )


def setup_pre_adverse_with_dispute_open(
    *,
    residence_jurisdiction: str = "CA",
    jurisdiction_kwargs: Optional[Dict[str, Any]] = None,
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    """Order in PRE_ADVERSE_ISSUED + the candidate opens an OPEN
    dispute on one VerificationItem.

    Returns (candidate, consent, order, items, flow, dispute).
    """
    candidate, consent, order, items, flow = setup_order_pre_adverse(
        residence_jurisdiction=residence_jurisdiction,
        jurisdiction_kwargs=jurisdiction_kwargs,
        adjudicator_headers=adjudicator_headers,
    )
    # Pick a non-passed item to dispute. PRD §3.7 says items in
    # RETURNED, FAILED, or REWORK_REQUIRED are disputable; in our
    # default setup the CRIMINAL item is the one that drives the
    # CONSIDER outcome so we dispute that one.
    target = next(
        (it for it in items if it.get("kind") == "CRIMINAL"),
        items[0] if items else None,
    )
    assert target is not None, "setup failed: no item to dispute"
    dispute = open_dispute_as_candidate(
        candidate_id=candidate["id"],
        verification_item_id=target["id"],
    )
    return candidate, consent, order, items, flow, dispute


__all__ = [
    # Jurisdiction
    "upsert_jurisdiction_policy",
    "ensure_all_default_policies",
    # Clock + sweep
    "clock_advance_seconds",
    "run_sweep",
    "advance_business_days_and_sweep",
    # Atomic helpers
    "create_candidate",
    "record_consent_as_candidate",
    "record_consent_as_recruiter",
    "open_order",
    "start_verification",
    "get_order",
    "get_candidate",
    "list_verification_items_for_order",
    "return_item",
    # Tiered fixtures
    "setup_candidate_with_consent",
    "setup_order_in_intake",
    "setup_order_in_verification",
    "setup_order_in_awaiting_adjudication",
    "setup_order_pre_adverse",
    "setup_order_awaiting_final",
    "setup_order_terminated_adverse",
    # Disputes / rework
    "open_dispute_as_candidate",
    "resolve_dispute_as_adjudicator",
    "request_rework_on_order",
    # Difficulty-design composites
    "setup_two_candidates_same_findings_different_states",
    "setup_pre_adverse_with_dispute_open",
]
