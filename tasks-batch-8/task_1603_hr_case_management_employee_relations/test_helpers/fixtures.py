"""Composite setup helpers — multi-step preconditions built from PRD-declared endpoints."""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_employee_payload,
    create_investigator_payload,
    create_intake_channel_payload,
    create_case_payload,
    create_interview_payload,
    create_evidence_payload,
    create_credibility_assessment_payload,
    create_finding_payload,
    create_action_payload,
    create_closure_notice_payload,
)
from .test_users import (
    TEST_USERS,
    make_investigator_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: basic entities
# ---------------------------------------------------------------------------

def setup_employee(**overrides):
    """Create one Employee. Returns the employee dict."""
    resp = api_client.create_employee(
        create_employee_payload(**overrides), TEST_USERS["er_manager_headers"]
    )
    return get_success_data(resp)


def setup_investigator(certification_level="LEVEL_3", max_active_cases=10,
                       conflicted_employee_ids=None, **employee_overrides):
    """Create an Employee + an Investigator bound to it. Returns (employee, investigator)."""
    emp = setup_employee(**employee_overrides)
    payload = create_investigator_payload(
        emp["id"],
        certification_level=certification_level,
        max_active_cases=max_active_cases,
    )
    if conflicted_employee_ids is not None:
        payload["conflicted_employee_ids"] = conflicted_employee_ids
    resp = api_client.create_investigator(payload, TEST_USERS["er_manager_headers"])
    return emp, get_success_data(resp)


def setup_intake_channel(**overrides):
    """Create one IntakeChannelConfig."""
    resp = api_client.create_intake_channel(
        create_intake_channel_payload(**overrides), TEST_USERS["er_manager_headers"]
    )
    return get_success_data(resp)


def setup_holiday(holiday_date: str, label: str = "Holiday"):
    resp = api_client.create_holiday(
        {"holiday_date": holiday_date, "label": label},
        TEST_USERS["er_manager_headers"],
    )
    return get_success_data(resp)


def set_clock(to_iso8601: str):
    resp = api_client.set_clock(
        {"to_iso8601": to_iso8601}, TEST_USERS["er_manager_headers"]
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: case scaffolding
# ---------------------------------------------------------------------------

def setup_case(channel_id: str, subject_employee_id: str,
               reporter_employee_id=None, category="HARASSMENT",
               severity="MEDIUM", **overrides):
    """Create a case in TRIAGE. Returns the case dict."""
    payload = create_case_payload(
        channel_id, subject_employee_id, category=category, severity=severity, **overrides
    )
    if reporter_employee_id is not None:
        payload["reporter_employee_id"] = reporter_employee_id
    resp = api_client.create_case(payload, TEST_USERS["er_manager_headers"])
    return get_success_data(resp)


def assign_case_to(case_id: str, investigator_id: str, expected_case_version: int):
    """POST /er/cases/{id}/assign as ERManager."""
    resp = api_client.assign_case(
        case_id,
        {"investigator_id": investigator_id, "expected_case_version": expected_case_version},
        TEST_USERS["er_manager_headers"],
    )
    return get_success_data(resp)


def setup_assigned_case(channel_id, subject_employee_id, investigator_id,
                        reporter_employee_id=None, category="HARASSMENT",
                        severity="MEDIUM", **overrides):
    """Create a case and assign to the given investigator. Returns case in ASSIGNED."""
    case = setup_case(channel_id, subject_employee_id,
                      reporter_employee_id=reporter_employee_id,
                      category=category, severity=severity, **overrides)
    return assign_case_to(case["id"], investigator_id, case["version"])


def begin_investigation(case_id: str, investigator_id: str):
    """POST /er/cases/{id}/begin-investigation as the assigned investigator."""
    resp = api_client.begin_investigation(
        case_id, make_investigator_headers(investigator_id)
    )
    return get_success_data(resp)


def setup_investigating_case(channel_id, subject_employee_id, investigator_id,
                             reporter_employee_id=None, category="HARASSMENT",
                             severity="MEDIUM", **overrides):
    """Create a case in INVESTIGATING. Returns the case dict."""
    case = setup_assigned_case(
        channel_id, subject_employee_id, investigator_id,
        reporter_employee_id=reporter_employee_id,
        category=category, severity=severity, **overrides
    )
    return begin_investigation(case["id"], investigator_id)


# ---------------------------------------------------------------------------
# Tier 3: interviews & evidence on an investigating case
# ---------------------------------------------------------------------------

def schedule_interview(case_id: str, investigator_id: str,
                       interviewee_employee_id: str,
                       scheduled_start="2026-07-27T09:00:00Z",
                       scheduled_end="2026-07-27T10:00:00Z"):
    resp = api_client.create_interview(
        case_id,
        create_interview_payload(
            interviewee_employee_id,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        ),
        make_investigator_headers(investigator_id),
    )
    return get_success_data(resp)


def complete_interview(interview_id: str, investigator_id: str,
                       documentation_text: str = None):
    if documentation_text is None:
        documentation_text = (
            "Completed interview documentation capturing the full account "
            "of events with sufficient detail for the record."
        )
    resp = api_client.complete_interview(
        interview_id,
        {"documentation_text": documentation_text},
        make_investigator_headers(investigator_id),
    )
    return get_success_data(resp)


def log_evidence(case_id: str, investigator_id: str, submitted_by_employee_id: str,
                 evidence_type="DOCUMENT", description="Evidence item."):
    resp = api_client.create_evidence_item(
        case_id,
        create_evidence_payload(
            submitted_by_employee_id,
            evidence_type=evidence_type,
            description=description,
        ),
        make_investigator_headers(investigator_id),
    )
    return get_success_data(resp)


def admit_evidence(evidence_id: str, investigator_id: str, weight: float = 0.8):
    """begin-review + admit by the same investigator."""
    begin = api_client.begin_review(evidence_id, make_investigator_headers(investigator_id))
    get_success_data(begin)
    admit = api_client.admit_evidence(
        evidence_id, {"weight": weight}, make_investigator_headers(investigator_id)
    )
    return get_success_data(admit)


def exclude_evidence(evidence_id: str, investigator_id: str,
                     exclusion_reason: str = "Excluded because the item is privileged or unauthenticated."):
    begin = api_client.begin_review(evidence_id, make_investigator_headers(investigator_id))
    get_success_data(begin)
    excl = api_client.exclude_evidence(
        evidence_id, {"exclusion_reason": exclusion_reason},
        make_investigator_headers(investigator_id),
    )
    return get_success_data(excl)


def create_assessment(case_id: str, investigator_id: str, subject_employee_id: str,
                      corroboration_count=3, contradiction_count=0, account_age_days=5):
    resp = api_client.create_credibility_assessment(
        case_id,
        create_credibility_assessment_payload(
            subject_employee_id,
            corroboration_count=corroboration_count,
            contradiction_count=contradiction_count,
            account_age_days=account_age_days,
        ),
        make_investigator_headers(investigator_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: findings pipeline
# ---------------------------------------------------------------------------

def create_draft_finding(case_id: str, investigator_id: str, rationale_text: str = None):
    """Create the finding draft (requires case INVESTIGATING with 1 completed interview + 1 admitted evidence)."""
    if rationale_text is None:
        rationale_text = (
            "Finding rationale: the admitted evidence and the completed interviews "
            "together establish the conclusion on the balance of probabilities here."
        )
    resp = api_client.create_finding(
        case_id,
        create_finding_payload(rationale_text=rationale_text),
        make_investigator_headers(investigator_id),
    )
    return get_success_data(resp)


def substantiate_finding(finding_id: str, investigator_id: str, outcome: str = "SUBSTANTIATED"):
    resp = api_client.substantiate_finding(
        finding_id, {"outcome": outcome}, make_investigator_headers(investigator_id)
    )
    return get_success_data(resp)


def propose_action(finding_id: str, investigator_id: str,
                   action_type="COACHING", severity_points=20,
                   justification="This action is proportionate to the finding reached."):
    resp = api_client.create_recommended_action(
        finding_id,
        create_action_payload(
            action_type=action_type,
            severity_points=severity_points,
            justification=justification,
        ),
        make_investigator_headers(investigator_id),
    )
    return get_success_data(resp)


def submit_for_calibration(finding_id: str, investigator_id: str):
    resp = api_client.submit_for_calibration(
        finding_id, make_investigator_headers(investigator_id)
    )
    return get_success_data(resp)


def approve_finding_as(finding_id: str, voter_investigator_id: str):
    resp = api_client.approve_finding(
        finding_id, make_investigator_headers(voter_investigator_id)
    )
    return get_success_data(resp)


def reject_finding_as(finding_id: str, voter_investigator_id: str,
                      rejection_reason: str = "Rejection rationale requires revision by the author."):
    resp = api_client.reject_finding(
        finding_id, {"rejection_reason": rejection_reason},
        make_investigator_headers(voter_investigator_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: full pipeline to CLOSED
# ---------------------------------------------------------------------------

def run_case_to_closed(channel_id, subject_employee_id, inv_author, inv_peer1, inv_peer2,
                       reporter_employee_id=None, category="HARASSMENT", severity="MEDIUM",
                       action_type="POLICY_CHANGE", severity_points=30,
                       substantiation_outcome="SUBSTANTIATED",
                       assessment_kwargs=None,
                       interview_start="2026-07-27T09:00:00Z",
                       interview_end="2026-07-27T10:00:00Z",
                       **case_overrides):
    """
    Drive a case from intake all the way to CLOSED.
    inv_author: Investigator dict (assigned investigator & finding author).
    inv_peer1, inv_peer2: Investigator dicts who cast the two calibration votes.
    Returns (case_after_close, finding, action, subject_notice, reporter_notice_or_None).

    When substantiation_outcome is SUBSTANTIATED and assessment_kwargs is None, a
    default high-scoring assessment is recorded so the PRD's credibility gate
    ("when every credibility assessment on the case has its active score below
    0.50, the outcome may not be SUBSTANTIATED") is unambiguously satisfied.

    interview_start / interview_end set the interview window; per PRD §3.3 the
    logical clock must have reached at least scheduled_start at completion time,
    so callers running the pipeline at a clock earlier than the default window
    must pass an earlier window.
    """
    case = setup_investigating_case(
        channel_id, subject_employee_id, inv_author["id"],
        reporter_employee_id=reporter_employee_id,
        category=category, severity=severity, **case_overrides
    )
    iv = schedule_interview(case["id"], inv_author["id"], subject_employee_id,
                            scheduled_start=interview_start,
                            scheduled_end=interview_end)
    complete_interview(iv["id"], inv_author["id"])
    ev = log_evidence(case["id"], inv_author["id"],
                      reporter_employee_id or subject_employee_id)
    admit_evidence(ev["id"], inv_author["id"])
    if assessment_kwargs is None and substantiation_outcome == "SUBSTANTIATED":
        assessment_kwargs = {"corroboration_count": 4, "contradiction_count": 0,
                              "account_age_days": 2}
    if assessment_kwargs is not None:
        create_assessment(case["id"], inv_author["id"], subject_employee_id,
                          **assessment_kwargs)
    finding = create_draft_finding(case["id"], inv_author["id"])
    substantiate_finding(finding["id"], inv_author["id"], outcome=substantiation_outcome)
    action = propose_action(finding["id"], inv_author["id"],
                            action_type=action_type, severity_points=severity_points)
    submit_for_calibration(finding["id"], inv_author["id"])
    approve_finding_as(finding["id"], inv_peer1["id"])
    approve_finding_as(finding["id"], inv_peer2["id"])

    # notices
    subject_notice_resp = api_client.create_closure_notice(
        case["id"],
        create_closure_notice_payload(
            subject_employee_id,
            recipient_role="SUBJECT",
            confidentiality_tier="TIER_2_LIMITED",
        ),
        TEST_USERS["er_manager_headers"],
    )
    subject_notice = get_success_data(subject_notice_resp)
    api_client.send_notice(subject_notice["id"], TEST_USERS["er_manager_headers"])

    reporter_notice = None
    if reporter_employee_id is not None:
        reporter_notice_resp = api_client.create_closure_notice(
            case["id"],
            create_closure_notice_payload(
                reporter_employee_id,
                recipient_role="REPORTER",
                confidentiality_tier="TIER_1_SUMMARY",
                body_text="Thank you for your report. The investigation has concluded.",
            ),
            TEST_USERS["er_manager_headers"],
        )
        reporter_notice = get_success_data(reporter_notice_resp)
        api_client.send_notice(reporter_notice["id"], TEST_USERS["er_manager_headers"])

    final_case = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
    closed = api_client.close_case(
        case["id"],
        {"expected_case_version": final_case["version"]},
        TEST_USERS["er_manager_headers"],
    )
    return get_success_data(closed), finding, action, subject_notice, reporter_notice


# ---------------------------------------------------------------------------
# Tier 5b: standard cast — three investigators + reporter + subject + channel
# ---------------------------------------------------------------------------

def setup_standard_cast(channel_kwargs=None, reporter_kwargs=None, subject_kwargs=None):
    """
    Create channel + reporter + subject + three LEVEL_3 investigators.
    Returns dict with keys: channel, reporter, subject, inv_author, inv_peer1, inv_peer2.
    """
    channel = setup_intake_channel(**(channel_kwargs or {}))
    reporter = setup_employee(**(reporter_kwargs or {}))
    subject = setup_employee(**(subject_kwargs or {}))
    _, inv_author = setup_investigator()
    _, inv_peer1 = setup_investigator()
    _, inv_peer2 = setup_investigator()
    return {
        "channel": channel,
        "reporter": reporter,
        "subject": subject,
        "inv_author": inv_author,
        "inv_peer1": inv_peer1,
        "inv_peer2": inv_peer2,
    }
