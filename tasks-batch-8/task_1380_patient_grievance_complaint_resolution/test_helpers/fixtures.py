"""Composite setup helpers for the patient-grievance domain.

Every fixture builds its preconditions from scratch through the public API
(each test starts against an empty database and the PRD §2.4 logical clock).
Setup calls use the lenient get_success_data() validator so a broken
precondition surfaces as a clear "Setup failed" error, not an assertion
failure deep inside a test.

All fixtures return a SimpleNamespace carrying every created entity plus the
identity-correct header dicts for entity-backed roles (PRD §2.1).
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_LETTER_SECTIONS, FULL_LETTER_SECTIONS
from .factories import (
    create_case_payload,
    create_letter_payload,
    create_note_payload,
    create_staff_payload,
    create_submit_findings_payload,
    create_unit_payload,
)
from .test_users import (
    TEST_USERS,
    make_advocate_headers,
    make_director_headers,
    make_investigator_headers,
    make_qro_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> None:
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup failed (set_clock): {resp.text}"


def create_unit(name="ED Main", category="EMERGENCY", **overrides) -> dict:
    payload = create_unit_payload(name=name, category=category, **overrides)
    data = get_success_data(api_client.create_unit(payload, ADMIN))
    assert isinstance(data, dict), f"Setup failed (create_unit): {data}"
    return data


def create_staff(full_name, capabilities, **overrides) -> dict:
    payload = create_staff_payload(full_name=full_name, capabilities=capabilities,
                                   **overrides)
    data = get_success_data(api_client.create_staff(payload, ADMIN))
    assert isinstance(data, dict), f"Setup failed (create_staff): {data}"
    return data


def register_holiday(observance_date, name="Holiday") -> dict:
    data = get_success_data(api_client.create_holiday(
        {"observance_date": observance_date, "name": name}, ADMIN))
    assert isinstance(data, dict), f"Setup failed (register_holiday): {data}"
    return data


def create_case(unit_id, **overrides) -> dict:
    payload = create_case_payload(unit_id=unit_id, **overrides)
    data = get_success_data(api_client.create_case(payload, INTAKE))
    assert isinstance(data, dict), f"Setup failed (create_case): {data}"
    return data


def get_case(case_id) -> dict:
    return get_success_data(api_client.get_case(case_id, INTAKE))


def get_staff(staff_id) -> dict:
    return get_success_data(api_client.get_staff(staff_id, ADMIN))


def get_case_version(case_id) -> int:
    return get_case(case_id)["version"]


def get_timeline(case_id, headers=None) -> dict:
    return get_success_data(api_client.get_case_timeline(case_id, headers or INTAKE))


def classify_case(case_id, decision, rationale_code="INITIAL_INTAKE",
                  expected_version=None) -> dict:
    """Record a classification decision under the OCC contract (PRD §2.7)."""
    version = expected_version if expected_version is not None else get_case_version(case_id)
    payload = {"decision": decision, "rationale_code": rationale_code,
               "expected_case_version": version}
    data = get_success_data(api_client.create_classification_decision(
        case_id, payload, INTAKE))
    assert isinstance(data, dict), f"Setup failed (classify_case): {data}"
    return data


def acknowledge_case(case_id) -> dict:
    data = get_success_data(api_client.acknowledge_case(case_id, INTAKE))
    assert isinstance(data, dict), f"Setup failed (acknowledge_case): {data}"
    return data


def assign_investigator(case_id, director_id, investigator_id=None,
                        assignment_role=None) -> dict:
    """Create an assignment (explicit or selector-chosen) as the director."""
    payload = {"expected_case_version": get_case_version(case_id)}
    if investigator_id is not None:
        payload["investigator_id"] = investigator_id
    if assignment_role is not None:
        payload["assignment_role"] = assignment_role
    data = get_success_data(api_client.create_assignment(
        case_id, payload, make_director_headers(director_id)))
    assert isinstance(data, dict), f"Setup failed (assign_investigator): {data}"
    return data


def open_investigation(case_id, investigator_id) -> dict:
    data = get_success_data(api_client.create_investigation(
        case_id, make_investigator_headers(investigator_id)))
    assert isinstance(data, dict), f"Setup failed (open_investigation): {data}"
    return data


def add_note(investigation_id, investigator_id, note_type="INTERVIEW",
             body="Investigation note") -> dict:
    data = get_success_data(api_client.create_note(
        investigation_id, create_note_payload(note_type=note_type, body=body),
        make_investigator_headers(investigator_id)))
    assert isinstance(data, dict), f"Setup failed (add_note): {data}"
    return data


def add_sufficient_notes(investigation_id, investigator_id) -> None:
    """Meet the evidence floor: >= 2 notes total, >= 1 INTERVIEW (PRD §3.3)."""
    add_note(investigation_id, investigator_id, "INTERVIEW", "Interview conducted")
    add_note(investigation_id, investigator_id, "DOCUMENT_REVIEW", "Records reviewed")


def submit_findings(investigation_id, investigator_id, care_concern_flag=False,
                    findings_summary="Findings documented") -> dict:
    data = get_success_data(api_client.submit_findings(
        investigation_id,
        create_submit_findings_payload(care_concern_flag=care_concern_flag,
                                       findings_summary=findings_summary),
        make_investigator_headers(investigator_id)))
    assert isinstance(data, dict), f"Setup failed (submit_findings): {data}"
    return data


def accept_findings(investigation_id, director_id) -> dict:
    data = get_success_data(api_client.accept_findings(
        investigation_id, make_director_headers(director_id)))
    assert isinstance(data, dict), f"Setup failed (accept_findings): {data}"
    return data


def draft_letter(case_id, investigator_id, sections=None, body_summary=None) -> dict:
    payload = create_letter_payload(
        sections=list(sections) if sections is not None else list(BASE_LETTER_SECTIONS),
        **({"body_summary": body_summary} if body_summary else {}))
    data = get_success_data(api_client.create_letter(
        case_id, payload, make_investigator_headers(investigator_id)))
    assert isinstance(data, dict), f"Setup failed (draft_letter): {data}"
    return data


def submit_letter_review(letter_id, investigator_id) -> dict:
    data = get_success_data(api_client.submit_letter_review(
        letter_id, make_investigator_headers(investigator_id)))
    assert isinstance(data, dict), f"Setup failed (submit_letter_review): {data}"
    return data


def approve_letter(letter_id, approver_id, approver_role="DIRECTOR") -> dict:
    headers = (make_qro_headers(approver_id) if approver_role == "QRO"
               else make_director_headers(approver_id))
    data = get_success_data(api_client.approve_letter(letter_id, headers))
    assert isinstance(data, dict), f"Setup failed (approve_letter): {data}"
    return data


def issue_letter(letter_id) -> dict:
    data = get_success_data(api_client.issue_letter(letter_id, INTAKE))
    assert isinstance(data, dict), f"Setup failed (issue_letter): {data}"
    return data


def issue_recovery(case_id, advocate_id, action_type="MEAL_VOUCHER", value_cents=1000,
                   justification="Goodwill gesture for the inconvenience") -> dict:
    payload = {"action_type": action_type, "value_cents": value_cents,
               "justification": justification}
    data = get_success_data(api_client.create_recovery_action(
        case_id, payload, make_advocate_headers(advocate_id)))
    assert isinstance(data, dict), f"Setup failed (issue_recovery): {data}"
    return data


def get_follow_up_for_case(case_id, headers=None) -> dict:
    data, _meta = _list_follow_ups(case_id, headers or INTAKE)
    assert len(data) == 1, f"Setup failed: expected exactly one follow-up, got {data}"
    return data[0]


def _list_follow_ups(case_id, headers):
    resp = api_client.list_follow_ups(headers, params={"case_id": case_id})
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed (list follow-ups): {resp.text}"
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Composite scenario builders (Tier 1–3)
# ---------------------------------------------------------------------------
def make_standard_staff():
    """One investigator + one director with identity-correct headers."""
    inv = create_staff("Ivy Investigator", ["INVESTIGATOR"])
    director = create_staff("Dana Director", ["DIRECTOR"])
    return SimpleNamespace(
        inv=inv, director=director,
        inv_headers=make_investigator_headers(inv["id"]),
        director_headers=make_director_headers(director["id"]),
    )


def setup_classified_case(decision="GRIEVANCE", unit_name="ED Main",
                          unit_category="EMERGENCY", received_at="2026-08-03T09:00:00.000Z",
                          clock="2026-08-03T10:00:00.000Z", acknowledge=False,
                          **case_overrides) -> SimpleNamespace:
    """Unit + case classified to `decision` (case in CLASSIFIED)."""
    set_clock(clock)
    unit = create_unit(unit_name, unit_category)
    case = create_case(unit["id"], received_at=received_at, **case_overrides)
    decision_row = classify_case(case["id"], decision)
    ack = acknowledge_case(case["id"]) if acknowledge else None
    return SimpleNamespace(unit=unit, case=get_case(case["id"]),
                           decision=decision_row, acknowledgment=ack)


def setup_assigned_case(decision="GRIEVANCE", acknowledge=False, **kwargs) -> SimpleNamespace:
    """Classified case + staff + ACTIVE PRIMARY assignment (case ASSIGNED)."""
    base = setup_classified_case(decision=decision, acknowledge=acknowledge, **kwargs)
    staff = make_standard_staff()
    assignment = assign_investigator(base.case["id"], staff.director["id"],
                                     staff.inv["id"])
    return SimpleNamespace(unit=base.unit, case=get_case(base.case["id"]),
                           decision=base.decision, acknowledgment=base.acknowledgment,
                           assignment=assignment, **vars(staff))


def setup_open_investigation(**kwargs) -> SimpleNamespace:
    """Assigned case + OPEN investigation (case UNDER_INVESTIGATION)."""
    base = setup_assigned_case(**kwargs)
    investigation = open_investigation(base.case["id"], base.inv["id"])
    return SimpleNamespace(**{**vars(base), "investigation": investigation,
                              "case": get_case(base.case["id"])})


def setup_findings_submitted(care_concern_flag=False, **kwargs) -> SimpleNamespace:
    """Open investigation + sufficient notes + findings submitted
    (case FINDINGS_REVIEW)."""
    base = setup_open_investigation(**kwargs)
    add_sufficient_notes(base.investigation["id"], base.inv["id"])
    investigation = submit_findings(base.investigation["id"], base.inv["id"],
                                    care_concern_flag=care_concern_flag)
    return SimpleNamespace(**{**vars(base), "investigation": investigation,
                              "case": get_case(base.case["id"])})


def setup_response_drafting(**kwargs) -> SimpleNamespace:
    """Findings accepted (grievance path) — case RESPONSE_DRAFTING."""
    base = setup_findings_submitted(**kwargs)
    investigation = accept_findings(base.investigation["id"], base.director["id"])
    return SimpleNamespace(**{**vars(base), "investigation": investigation,
                              "case": get_case(base.case["id"])})


def setup_complaint_response_drafting(**kwargs) -> SimpleNamespace:
    """Complaint path: classified COMPLAINT + assignment + fast-track
    (case RESPONSE_DRAFTING, no investigation)."""
    base = setup_assigned_case(decision="COMPLAINT", **kwargs)
    resp = api_client.fast_track_case(base.case["id"], INTAKE)
    assert resp.status_code == 200, f"Setup failed (fast_track): {resp.text}"
    return SimpleNamespace(**{**vars(base), "case": get_case(base.case["id"]),
                              "investigation": None})


def setup_letter_in_review(sections=None, **kwargs) -> SimpleNamespace:
    """Letter drafted and submitted for review (case RESPONSE_REVIEW).

    Grievance path by default; pass complaint=True for the fast-track path.
    """
    complaint = kwargs.pop("complaint", False)
    if complaint:
        base = setup_complaint_response_drafting(**kwargs)
    else:
        base = setup_response_drafting(**kwargs)
    letter = draft_letter(base.case["id"], base.inv["id"], sections=sections)
    letter = submit_letter_review(letter["id"], base.inv["id"])
    return SimpleNamespace(**{**vars(base), "letter": letter,
                              "case": get_case(base.case["id"])})


def setup_letter_approved(**kwargs) -> SimpleNamespace:
    """Letter APPROVED (case PENDING_CLOSURE).

    pass severity_tier="CRITICAL" to route approval through a QRO co-signer
    with the full seven-section letter (PRD §3.4).
    """
    critical = kwargs.get("severity_tier") == "CRITICAL"
    if critical:
        kwargs.setdefault("sections", list(FULL_LETTER_SECTIONS))
    base = setup_letter_in_review(**kwargs)
    if critical:
        qro = create_staff("Quinn Risk", ["QRO"])
        letter = approve_letter(base.letter["id"], qro["id"], approver_role="QRO")
        return SimpleNamespace(**{**vars(base), "letter": letter, "qro": qro,
                                  "qro_headers": make_qro_headers(qro["id"]),
                                  "case": get_case(base.case["id"])})
    letter = approve_letter(base.letter["id"], base.director["id"])
    return SimpleNamespace(**{**vars(base), "letter": letter,
                              "case": get_case(base.case["id"])})


def setup_closed_case(issue_at=None, **kwargs) -> SimpleNamespace:
    """Full grievance lifecycle through CLOSED via letter issuance.

    Sets the clock to `issue_at` before issuing when provided.
    Returns the namespace with case/investigation/letter/follow_up/unit refs.
    """
    base = setup_letter_approved(**kwargs)
    if issue_at is not None:
        set_clock(issue_at)
    letter = issue_letter(base.letter["id"])
    case = get_case(base.case["id"])
    follow_up = get_follow_up_for_case(case["id"])
    return SimpleNamespace(**{**vars(base), "letter": letter, "case": case,
                              "follow_up": follow_up})


def setup_closed_complaint(close_note="Resolved at the point of contact",
                           close_at=None, **kwargs) -> SimpleNamespace:
    """Complaint fast-track closure (PRD §3.4) — case CLOSED, follow-up PENDING."""
    base = setup_complaint_response_drafting(**kwargs)
    if close_at is not None:
        set_clock(close_at)
    resp = api_client.close_case(base.case["id"], {"closure_note": close_note}, INTAKE)
    assert resp.status_code == 200, f"Setup failed (close_case): {resp.text}"
    case = get_case(base.case["id"])
    follow_up = get_follow_up_for_case(case["id"])
    return SimpleNamespace(**{**vars(base), "case": case, "follow_up": follow_up})


# ---------------------------------------------------------------------------
# Escalation helpers (PRD §3.6)
# ---------------------------------------------------------------------------
def create_escalation(case_id, qro_id, escalation_type="CARE_CONCERN",
                      review_track="COMPLIANCE") -> dict:
    data = get_success_data(api_client.create_escalation(
        case_id, {"escalation_type": escalation_type, "review_track": review_track},
        make_qro_headers(qro_id)))
    assert isinstance(data, dict), f"Setup failed (create_escalation): {data}"
    return data


def drive_escalation_to_reviews_complete(escalation_id, qro_id, review_track) -> dict:
    """Triage + complete every branch the track requires (fork-join)."""
    get_success_data(api_client.triage_escalation(
        escalation_id, {"review_track": review_track}, make_qro_headers(qro_id)))
    branches = ["COMPLIANCE", "SAFETY"] if review_track == "BOTH" else [review_track]
    data = None
    for branch in branches:
        data = get_success_data(api_client.complete_escalation_review(
            escalation_id, {"review_branch": branch}, make_qro_headers(qro_id)))
    return data


def setup_escalation_at_reviews_complete(case_id, filer_qro_id,
                                         escalation_type="CARE_CONCERN",
                                         review_track="COMPLIANCE") -> dict:
    esc = create_escalation(case_id, filer_qro_id, escalation_type, review_track)
    return drive_escalation_to_reviews_complete(esc["id"], filer_qro_id, review_track)
