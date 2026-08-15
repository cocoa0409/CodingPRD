"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch against the running API
using only PRD-declared endpoints. All setup calls use ``get_success_data``
so failures surface as clear "Setup step failed" errors.

Logical-clock discipline: the server clock starts at the mandatory default
2026-08-01T00:00:00Z (PRD §2.4); fixtures that need a different "now" call
``set_clock`` explicitly.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client
from .factories import (
    create_member_payload,
    create_provider_payload,
    create_deadline_policy_payload,
    create_case_payload,
    create_notification_payload,
    create_clinical_factors_payload,
    ALL_DECISION_ELEMENTS,
)
from .test_users import (
    TEST_USERS,
    make_intake_specialist_headers,
    make_case_analyst_headers,
    make_medical_director_headers,
    make_member_services_rep_headers,
    make_compliance_officer_headers,
    make_claims_processor_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + reference data
# ---------------------------------------------------------------------------

def _parse_instant(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_instant(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_clock(to_iso8601: str):
    """Drive the logical server clock (PRD §2.4). Returns response data."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_member(member_ref: str, full_name: str = "Test Member",
                  program: str = "MEDICARE") -> dict:
    return get_success_data(
        api_client.create_member(
            create_member_payload(member_ref=member_ref, full_name=full_name,
                                  program=program),
            ADMIN,
        ),
        expected_status=201,
    )


def create_provider(npi: str, legal_name: str = "Test Provider",
                    contract_status: str = "CONTRACTED",
                    w9_on_file: bool = True) -> dict:
    return get_success_data(
        api_client.create_provider(
            create_provider_payload(npi=npi, legal_name=legal_name,
                                    contract_status=contract_status,
                                    w9_on_file=w9_on_file),
            ADMIN,
        ),
        expected_status=201,
    )


def create_policy(program: str, case_kind: str, priority_track: str,
                  resolution_hours: int = 720, extension_hours: int = 0,
                  effectuation_hours: int = 72,
                  business_hours_only: bool = False) -> dict:
    return get_success_data(
        api_client.create_deadline_policy(
            create_deadline_policy_payload(
                program=program, case_kind=case_kind,
                priority_track=priority_track,
                resolution_hours=resolution_hours,
                extension_hours=extension_hours,
                effectuation_hours=effectuation_hours,
                business_hours_only=business_hours_only,
            ),
            ADMIN,
        ),
        expected_status=201,
    )


# ---------------------------------------------------------------------------
# Tier 1: case state progression
# ---------------------------------------------------------------------------

def intake_case(member_id: str, case_kind: str = "GRIEVANCE",
                provider_id: str = None, headers=None, **overrides) -> dict:
    """Intake a case; lands in RECEIVED (PRD §3.2). Returns the case."""
    payload = create_case_payload(member_id=member_id, case_kind=case_kind,
                                  provider_id=provider_id, **overrides)
    return get_success_data(
        api_client.create_case(payload, headers or INTAKE),
        expected_status=201,
    )


def triage_case(case_id: str, headers=None) -> dict:
    """RECEIVED -> TRIAGED (PRD §3.3). Returns the triaged case."""
    return get_success_data(api_client.triage_case(case_id, headers or INTAKE))


def begin_review(case_id: str, headers=None) -> dict:
    """TRIAGED -> IN_REVIEW (PRD §3.3). Returns the case."""
    return get_success_data(api_client.begin_review(case_id, headers or ANALYST))


def create_triaged_case(member_id: str, case_kind: str = "GRIEVANCE",
                        provider_id: str = None, intake_user_id: str = None,
                        **intake_overrides) -> dict:
    """Create + triage. ``intake_user_id`` pins the triager's X-User-ID when a
    downstream segregation-of-duties assertion needs to know it."""
    case = intake_case(member_id, case_kind=case_kind, provider_id=provider_id,
                       **intake_overrides)
    triage_headers = (make_intake_specialist_headers(intake_user_id)
                      if intake_user_id else INTAKE)
    return triage_case(case["id"], headers=triage_headers)


def create_in_review_case(member_id: str, case_kind: str = "GRIEVANCE",
                          provider_id: str = None, intake_user_id: str = None,
                          **intake_overrides) -> dict:
    """Create + triage + begin-review; lands in IN_REVIEW."""
    case = create_triaged_case(member_id, case_kind=case_kind,
                               provider_id=provider_id,
                               intake_user_id=intake_user_id, **intake_overrides)
    return begin_review(case["id"])


# ---------------------------------------------------------------------------
# Tier 2: clinical review ladder (PRD §3.4)
# ---------------------------------------------------------------------------

def request_clinical_review(case_id: str, analyst_user_id: str = None) -> dict:
    """IN_REVIEW -> PENDING_CLINICAL with a REQUESTED ClinicalReview.
    Returns the ClinicalReview."""
    headers = (make_case_analyst_headers(analyst_user_id)
               if analyst_user_id else ANALYST)
    return get_success_data(
        api_client.request_clinical_review(case_id, headers),
        expected_status=201,
    )


def walk_review_to_determined(review_id: str, reviewer_id: str,
                              factors: dict = None,
                              determination: str = "UPHOLD_SERVICE",
                              assigner_id: str = "md-admin") -> dict:
    """REQUESTED -> ASSIGNED -> DETERMINATION_DRAFT -> DETERMINED.
    Draft/finalize are gated on X-User-ID == reviewer_physician_id (PRD §3.4).
    Returns the DETERMINED review."""
    get_success_data(
        api_client.assign_clinical_review(
            review_id, {"reviewer_physician_id": reviewer_id},
            make_medical_director_headers(assigner_id),
        )
    )
    get_success_data(
        api_client.draft_determination(
            review_id, factors or create_clinical_factors_payload(),
            make_medical_director_headers(reviewer_id),
        )
    )
    return get_success_data(
        api_client.finalize_determination(
            review_id, {"determination": determination},
            make_medical_director_headers(reviewer_id),
        )
    )


def setup_case_pending_clinical(member_id: str, case_kind: str = "APPEAL",
                                provider_id: str = None,
                                intake_user_id: str = None,
                                analyst_user_id: str = None,
                                **intake_overrides) -> tuple:
    """Case in PENDING_CLINICAL with a REQUESTED review.
    Returns (case, review)."""
    case = create_in_review_case(member_id, case_kind=case_kind,
                                 provider_id=provider_id,
                                 intake_user_id=intake_user_id,
                                 **intake_overrides)
    review = request_clinical_review(case["id"], analyst_user_id=analyst_user_id)
    return case, review


def setup_case_with_determined_review(member_id: str, case_kind: str = "APPEAL",
                                      provider_id: str = None,
                                      reviewer_id: str = "md-001",
                                      intake_user_id: str = None,
                                      factors: dict = None,
                                      determination: str = "UPHOLD_SERVICE",
                                      **intake_overrides) -> tuple:
    """Case in PENDING_CLINICAL whose ClinicalReview is DETERMINED.
    Returns (case, review)."""
    case, review = setup_case_pending_clinical(
        member_id, case_kind=case_kind, provider_id=provider_id,
        intake_user_id=intake_user_id, **intake_overrides,
    )
    walk_review_to_determined(review["id"], reviewer_id, factors=factors,
                              determination=determination)
    return case, review


# ---------------------------------------------------------------------------
# Tier 3: decision / notification / closure ladder (PRD §3.5, §3.8)
# ---------------------------------------------------------------------------

def decide_grievance_from_in_review(case_id: str,
                                    decision_outcome: str = "UNFAVORABLE",
                                    payment_amount_cents: int = None,
                                    analyst_user_id: str = None) -> dict:
    """Non-clinical door: CaseAnalyst decides a GRIEVANCE from IN_REVIEW."""
    payload = {"decision_outcome": decision_outcome}
    if payment_amount_cents is not None:
        payload["payment_amount_cents"] = payment_amount_cents
    headers = (make_case_analyst_headers(analyst_user_id)
               if analyst_user_id else ANALYST)
    return get_success_data(api_client.decide_case(case_id, payload, headers))


def decide_case_clinical(case_id: str, decision_outcome: str = "UNFAVORABLE",
                         payment_amount_cents: int = None,
                         decider_id: str = "md-decider") -> dict:
    """Clinical door: MedicalDirector decides a PENDING_CLINICAL case."""
    payload = {"decision_outcome": decision_outcome}
    if payment_amount_cents is not None:
        payload["payment_amount_cents"] = payment_amount_cents
    return get_success_data(
        api_client.decide_case(case_id, payload,
                               make_medical_director_headers(decider_id))
    )


def create_and_send_decision_notification(case_id: str,
                                          recipient_kind: str = "MEMBER",
                                          supplied_elements: list = None) -> dict:
    """Create a DECISION notification with a complete content set and mark it
    SENT (PRD §3.5). For recipient_kind=MEMBER this cascades the parent case
    DECIDED -> NOTIFIED. Returns the SENT notification."""
    notif = get_success_data(
        api_client.create_notification(
            case_id,
            create_notification_payload(
                recipient_kind=recipient_kind,
                notification_kind="DECISION",
                supplied_elements=(supplied_elements
                                   if supplied_elements is not None
                                   else list(ALL_DECISION_ELEMENTS)),
            ),
            MSR,
        ),
        expected_status=201,
    )
    return get_success_data(api_client.mark_notification_sent(notif["id"], MSR))


def setup_decided_grievance(member_id: str,
                            decision_outcome: str = "UNFAVORABLE",
                            payment_amount_cents: int = None,
                            provider_id: str = None,
                            **intake_overrides) -> dict:
    """GRIEVANCE case walked RECEIVED -> TRIAGED -> IN_REVIEW -> DECIDED via
    the non-clinical door. Returns the DECIDED case."""
    case = create_in_review_case(member_id, case_kind="GRIEVANCE",
                                 provider_id=provider_id, **intake_overrides)
    return decide_grievance_from_in_review(
        case["id"], decision_outcome=decision_outcome,
        payment_amount_cents=payment_amount_cents,
    )


def setup_notified_case(member_id: str, case_kind: str = "GRIEVANCE",
                        decision_outcome: str = "UNFAVORABLE",
                        payment_amount_cents: int = None,
                        provider_id: str = None,
                        reviewer_id: str = "md-001",
                        intake_user_id: str = None,
                        decider_id: str = "md-decider") -> dict:
    """Case walked all the way to NOTIFIED (DECISION/MEMBER notice SENT).
    Grievances take the non-clinical door; other kinds route through clinical
    review. Returns the NOTIFIED case."""
    if case_kind == "GRIEVANCE":
        case = setup_decided_grievance(
            member_id, decision_outcome=decision_outcome,
            payment_amount_cents=payment_amount_cents,
            provider_id=provider_id,
        )
    else:
        case, _review = setup_case_with_determined_review(
            member_id, case_kind=case_kind, provider_id=provider_id,
            reviewer_id=reviewer_id, intake_user_id=intake_user_id,
        )
        case = decide_case_clinical(
            case["id"], decision_outcome=decision_outcome,
            payment_amount_cents=payment_amount_cents, decider_id=decider_id,
        )
    create_and_send_decision_notification(case["id"])
    return get_success_data(api_client.get_case(case["id"], COMPLIANCE))


def setup_closed_case(member_id: str, case_kind: str = "GRIEVANCE",
                      decision_outcome: str = "UNFAVORABLE",
                      provider_id: str = None,
                      reviewer_id: str = "md-001",
                      intake_user_id: str = None,
                      decider_id: str = "md-decider",
                      close_note: bool = False) -> dict:
    """Case walked to CLOSED. For a non-FULLY_FAVORABLE APPEAL the close path
    requires an IRE referral or a lapsed-window NOTE; ``close_note`` records the
    lapse NOTE (PRD §3.8). Returns the CLOSED case.

    The lapse path only exists once the 72-hour forwarding window has actually
    lapsed (PRD §3.8: "the 72-hour forwarding window lapsed unexercised, the
    lapse documented by a NOTE event"), so ``close_note`` also moves the
    logical clock past ``decided_at`` + 72h before recording the NOTE."""
    case = setup_notified_case(
        member_id, case_kind=case_kind, decision_outcome=decision_outcome,
        provider_id=provider_id, reviewer_id=reviewer_id,
        intake_user_id=intake_user_id, decider_id=decider_id,
    )
    if close_note:
        decided_at = _parse_instant(case["decided_at"])
        set_clock(_fmt_instant(decided_at + timedelta(hours=73)))
        get_success_data(
            api_client.append_case_event(
                case["id"],
                {"event_type": "NOTE",
                 "body": "IRE forwarding window lapsed unexercised"},
                COMPLIANCE,
            ),
            expected_status=201,
        )
    return get_success_data(api_client.close_case(case["id"], COMPLIANCE))


# ---------------------------------------------------------------------------
# Tier 4: effectuation helpers (PRD §3.7)
# ---------------------------------------------------------------------------

def get_case_effectuation(case_id: str, index: int = 0) -> dict:
    """Fetch the Nth effectuation on a case (creation order)."""
    data = get_success_data(
        api_client.list_case_effectuations(case_id, CLAIMS)
    )
    assert len(data) > index, f"Expected effectuation[{index}] on case {case_id}"
    return data[index]


def get_effectuation_fresh(effectuation_id: str) -> dict:
    return get_success_data(api_client.get_effectuation(effectuation_id, CLAIMS))


def start_effectuation(effectuation_id: str) -> dict:
    """PENDING -> IN_PROGRESS."""
    return get_success_data(api_client.start_effectuation(effectuation_id, CLAIMS))


def complete_effectuation(effectuation_id: str) -> dict:
    """Complete with the current version (OCC field, PRD §2.7)."""
    fresh = get_effectuation_fresh(effectuation_id)
    return get_success_data(
        api_client.complete_effectuation(
            effectuation_id,
            {"expected_effectuation_version": fresh["version"]},
            CLAIMS,
        )
    )


# ---------------------------------------------------------------------------
# Tier 4: CTM linkage (PRD §3.9)
# ---------------------------------------------------------------------------

def link_case_to_ctm(case_id: str, body: str = "ctm", headers=None) -> dict:
    return get_success_data(
        api_client.append_case_event(
            case_id, {"event_type": "CTM_LINKED", "body": body},
            headers or INTAKE,
        ),
        expected_status=201,
    )


def unlink_case_from_ctm(case_id: str, body: str = "ctm", headers=None) -> dict:
    return get_success_data(
        api_client.append_case_event(
            case_id, {"event_type": "CTM_UNLINKED", "body": body},
            headers or INTAKE,
        ),
        expected_status=201,
    )


def get_ctm_exposure(member_id: str) -> dict:
    return get_success_data(api_client.get_member_ctm_exposure(member_id, COMPLIANCE))


def get_member_fresh(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, COMPLIANCE))


def setup_member_with_ctm_cases(member_ref: str, n_cases: int,
                                triage: bool = False,
                                program: str = "MEDICARE") -> tuple:
    """Member plus ``n_cases`` GRIEVANCE cases, each CTM-linked. When
    ``triage`` is true the cases are triaged (full weight); otherwise they
    stay RECEIVED (provisional half weight, PRD §3.9).
    Requires the (program, GRIEVANCE, STANDARD) policy when triage=True.
    Returns (member, [cases]).

    The intakes are identical (same member/kind/provider), so each one is
    spaced two hours past the previous to stay outside the duplicate-intake
    guard's prior-one-hour look-back (PRD §3.2)."""
    member = create_member(member_ref)
    cases = []
    for i in range(n_cases):
        if i > 0:
            set_clock(f"2026-08-01T{2 * i:02d}:00:00Z")
        case = intake_case(member["id"], case_kind="GRIEVANCE")
        link_case_to_ctm(case["id"], body=f"ctm-{i}")
        if triage:
            case = triage_case(case["id"])
        cases.append(case)
    return member, cases


# ---------------------------------------------------------------------------
# Tier 5: reopening ladder (PRD §3.8)
# ---------------------------------------------------------------------------

def create_and_review_reopening(case_id: str,
                                request_reason: str = "NEW_EVIDENCE",
                                requester_headers=None) -> dict:
    """Reopening walked REQUESTED -> UNDER_REVIEW. Returns the reopening."""
    reopening = get_success_data(
        api_client.create_reopening(
            {"case_id": case_id, "request_reason": request_reason},
            requester_headers or COMPLIANCE,
        ),
        expected_status=201,
    )
    return get_success_data(
        api_client.begin_reopening_review(reopening["id"], COMPLIANCE)
    )


def setup_closed_case_with_reopening_under_review(
        member_id: str, case_kind: str = "GRIEVANCE",
        request_reason: str = "NEW_EVIDENCE", **kwargs) -> tuple:
    """Closed case plus a Reopening in UNDER_REVIEW against it.
    Returns (closed_case, reopening)."""
    closed = setup_closed_case(member_id, case_kind=case_kind, **kwargs)
    reopening = create_and_review_reopening(closed["id"],
                                            request_reason=request_reason)
    return closed, reopening


# ---------------------------------------------------------------------------
# Composite: full MEDICARE policy set for one program
# ---------------------------------------------------------------------------

def seed_standard_grievance_policy(program: str = "MEDICARE",
                                   resolution_hours: int = 720,
                                   extension_hours: int = 0,
                                   effectuation_hours: int = 72) -> dict:
    return create_policy(program, "GRIEVANCE", "STANDARD",
                         resolution_hours=resolution_hours,
                         extension_hours=extension_hours,
                         effectuation_hours=effectuation_hours)


def seed_standard_appeal_policy(program: str = "MEDICARE",
                                resolution_hours: int = 720,
                                extension_hours: int = 0,
                                effectuation_hours: int = 72) -> dict:
    return create_policy(program, "APPEAL", "STANDARD",
                         resolution_hours=resolution_hours,
                         extension_hours=extension_hours,
                         effectuation_hours=effectuation_hours)
