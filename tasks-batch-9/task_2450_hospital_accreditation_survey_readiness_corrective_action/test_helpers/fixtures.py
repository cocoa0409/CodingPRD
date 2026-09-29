"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test starts against an empty database with the logical
clock at its fixed starting instant. Setup calls use the lenient validator so a
broken precondition surfaces as a setup failure rather than as a confusing
assertion.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    DIRECTOR_USER_ID,
    EXTERNAL_SURVEYOR_USER_ID,
    OWNER_USER_ID,
    SAFETY_USER_ID,
    SURVEYOR_USER_ID,
    VALIDATOR_USER_ID,
    make_director_headers,
    make_evidence_validator_headers,
    make_external_surveyor_headers,
    make_safety_officer_headers,
    make_standard_owner_headers,
    make_tracer_surveyor_headers,
)

DIRECTOR = make_director_headers()
OWNER = make_standard_owner_headers()
VALIDATOR = make_evidence_validator_headers()
SURVEYOR = make_tracer_surveyor_headers()
SAFETY = make_safety_officer_headers()
EXTERNAL = make_external_surveyor_headers()


# ===========================================================================
# Primitives — one thin wrapper per write, returning the created resource
# ===========================================================================

def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock and return current_utc plus the sweep counts."""
    return get_success_data(api_client.set_clock(to_iso8601, DIRECTOR))


def create_chapter(
    code: str = "EC",
    name: str = "Environment of Care",
    weight_pct: float = 100,
    evidence_min_count: Optional[int] = 1,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"code": code, "name": name, "weight_pct": weight_pct}
    if evidence_min_count is not None:
        payload["evidence_min_count"] = evidence_min_count
    payload.update(overrides)
    return get_success_data(api_client.create_chapter(payload, DIRECTOR))


def create_standard(
    chapter_id: str,
    standard_code: str = "EC.02.06.01",
    title: str = "Safe environment",
    risk_tier: str = "DIRECT_IMPACT",
) -> Dict[str, Any]:
    payload = {"standard_code": standard_code, "title": title, "risk_tier": risk_tier}
    return get_success_data(api_client.create_standard(chapter_id, payload, DIRECTOR))


def assign_owner(
    standard_id: str,
    owner_user_id: str = OWNER_USER_ID,
    designation: str = "PRIMARY",
) -> Dict[str, Any]:
    payload = {"owner_user_id": owner_user_id, "designation": designation}
    return get_success_data(api_client.create_owner_assignment(standard_id, payload, DIRECTOR))


def revoke_owner_assignment(assignment_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(api_client.revoke_owner_assignment(assignment_id, payload, DIRECTOR))


def file_evidence(
    standard_id: str,
    title: str = "Fire drill log",
    doc_type: str = "LOG",
    effective_date: str = "2026-07-01T00:00:00Z",
    expires_at: Optional[str] = None,
    owner_user_id: str = OWNER_USER_ID,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title": title,
        "doc_type": doc_type,
        "effective_date": effective_date,
    }
    if expires_at is not None:
        payload["expires_at"] = expires_at
    return get_success_data(
        api_client.create_evidence_item(
            standard_id, payload, make_standard_owner_headers(owner_user_id)
        )
    )


def evidence_action(
    evidence_id: str,
    action: str,
    headers: Optional[Dict[str, str]] = None,
    review_note: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if review_note is not None:
        payload["review_note"] = review_note
    if headers is None:
        headers = OWNER if action == "SUBMIT" else VALIDATOR
    return get_success_data(api_client.transition_evidence_item(evidence_id, payload, headers))


def create_unit(
    name: str = "ICU-1",
    unit_type: str = "ICU",
    bed_count: int = 12,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": name, "unit_type": unit_type, "bed_count": bed_count}
    payload.update(overrides)
    return get_success_data(api_client.create_unit(payload, DIRECTOR))


def read_unit(unit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_unit(unit_id, DIRECTOR))


def unit_version(unit_id: str) -> int:
    return read_unit(unit_id)["version"]


def read_readiness(unit_id: str, mode: Optional[str] = None) -> Dict[str, Any]:
    params = {"mode": mode} if mode is not None else None
    return get_success_data(api_client.get_unit_readiness(unit_id, DIRECTOR, params))


def read_chapter(chapter_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_chapter(chapter_id, DIRECTOR))


def read_standard(standard_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_standard(standard_id, DIRECTOR))


def schedule_tracer(
    unit_id: str,
    chapter_id: str,
    window_start: str = "2026-08-10T08:00:00Z",
    window_end: str = "2026-08-10T12:00:00Z",
    tracer_type: str = "PATIENT",
    expected_unit_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if expected_unit_version is None:
        expected_unit_version = unit_version(unit_id)
    payload = {
        "unit_id": unit_id,
        "chapter_id": chapter_id,
        "tracer_type": tracer_type,
        "window_start": window_start,
        "window_end": window_end,
        "expected_unit_version": expected_unit_version,
    }
    return get_success_data(api_client.create_mock_tracer(payload, headers or SURVEYOR))


def tracer_action(
    tracer_id: str, action: str, abort_reason: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if abort_reason is not None:
        payload["abort_reason"] = abort_reason
    return get_success_data(api_client.transition_mock_tracer(tracer_id, payload, SURVEYOR))


def record_observation(
    tracer_id: str,
    standard_id: str,
    result: str,
    weight: Optional[float] = None,
    note: Optional[str] = None,
    surveyor_user_id: str = SURVEYOR_USER_ID,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"standard_id": standard_id, "result": result}
    if weight is not None:
        payload["weight"] = weight
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.create_tracer_observation(
            tracer_id, payload, make_tracer_surveyor_headers(surveyor_user_id)
        )
    )


def open_rounding_session(
    unit_id: str,
    round_type: str = "ENVIRONMENT_OF_CARE",
    window_start: str = "2026-08-01T08:00:00Z",
    window_end: str = "2026-08-01T12:00:00Z",
) -> Dict[str, Any]:
    payload = {
        "unit_id": unit_id,
        "round_type": round_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    return get_success_data(api_client.create_rounding_session(payload, SAFETY))


def raise_deficiency(
    session_id: str,
    standard_id: str,
    severity: str = "MODERATE",
    description: str = "Blocked egress corridor",
) -> Dict[str, Any]:
    payload = {
        "standard_id": standard_id,
        "description": description,
        "severity": severity,
    }
    return get_success_data(api_client.create_deficiency(session_id, payload, SAFETY))


def close_rounding_session(session_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.close_rounding_session(session_id, {}, SAFETY))


def ticket_action(
    ticket_id: str,
    action: str,
    headers: Optional[Dict[str, str]] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.transition_deficiency_ticket(ticket_id, payload, headers or SAFETY)
    )


def create_survey_window(
    cycle_label: str = "CYCLE-2026",
    prior_survey_end_date: str = "2025-03-15T00:00:00Z",
) -> Dict[str, Any]:
    payload = {"cycle_label": cycle_label, "prior_survey_end_date": prior_survey_end_date}
    return get_success_data(api_client.create_survey_window(payload, DIRECTOR))


def window_action(window_id: str, action: str, note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.transition_survey_window(window_id, payload, DIRECTOR))


def create_finding(
    window_id: str,
    standard_id: str,
    unit_id: str,
    sampled_count: int,
    observed_noncompliance_count: int,
    patient_harm_observed: Optional[bool] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "standard_id": standard_id,
        "unit_id": unit_id,
        "sampled_count": sampled_count,
        "observed_noncompliance_count": observed_noncompliance_count,
    }
    if patient_harm_observed is not None:
        payload["patient_harm_observed"] = patient_harm_observed
    return get_success_data(api_client.create_finding(window_id, payload, EXTERNAL))


def read_finding(finding_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_finding(finding_id, DIRECTOR))


def escalate_finding(
    finding_id: str, rationale: str = "Immediate jeopardy to patients"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.escalate_finding(finding_id, {"rationale": rationale}, EXTERNAL)
    )


def submit_esc(
    finding_id: str,
    expected_finding_version: Optional[int] = None,
    leadership_signoff: bool = True,
    owner_user_id: str = OWNER_USER_ID,
    corrective_action_summary: str = "Retrained staff and revised the oversight policy",
    measure_of_success: str = "Ninety percent compliance across three monthly audits",
) -> Dict[str, Any]:
    if expected_finding_version is None:
        expected_finding_version = read_finding(finding_id)["version"]
    payload = {
        "corrective_action_summary": corrective_action_summary,
        "measure_of_success": measure_of_success,
        "leadership_signoff": leadership_signoff,
        "expected_finding_version": expected_finding_version,
    }
    return get_success_data(
        api_client.create_esc_submission(
            finding_id, payload, make_standard_owner_headers(owner_user_id)
        )
    )


def review_esc(
    finding_id: str, decision: str, decision_note: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return get_success_data(api_client.esc_review(finding_id, payload, EXTERNAL))


def file_ppr(
    chapter_id: str, period_label: str, self_ratings: Sequence[Dict[str, str]]
) -> Dict[str, Any]:
    payload = {"period_label": period_label, "self_ratings": list(self_ratings)}
    return get_success_data(api_client.create_ppr_self_assessment(chapter_id, payload, DIRECTOR))


def revise_ppr(ppr_id: str, self_ratings: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    payload = {"self_ratings": list(self_ratings)}
    return get_success_data(api_client.revise_ppr_self_assessment(ppr_id, payload, DIRECTOR))


def attest_ppr(
    ppr_id: str, attestation_note: Optional[str] = None, director_user_id: str = DIRECTOR_USER_ID
) -> Dict[str, Any]:
    payload = {"attestation_note": attestation_note} if attestation_note is not None else {}
    return get_success_data(
        api_client.attest_ppr_self_assessment(
            ppr_id, payload, make_director_headers(director_user_id)
        )
    )


# ===========================================================================
# Tier 1 / 2 — mapped accountability and simple hierarchies
# ===========================================================================

def setup_mapped_chapter(
    code: str = "EC",
    name: str = "Environment of Care",
    weight_pct: float = 100,
    evidence_min_count: Optional[int] = 1,
    standard_code: str = "EC.02.06.01",
    title: str = "Safe environment",
    risk_tier: str = "DIRECT_IMPACT",
    owner_user_id: str = OWNER_USER_ID,
    designation: str = "PRIMARY",
) -> Dict[str, Any]:
    """One chapter, one standard, one ACTIVE owner assignment (chapter MAPPED)."""
    chapter = create_chapter(code, name, weight_pct, evidence_min_count)
    standard = create_standard(chapter["id"], standard_code, title, risk_tier)
    assignment = assign_owner(standard["id"], owner_user_id, designation)
    return {"chapter": chapter, "standard": standard, "assignment": assignment}


def setup_unit_and_mapped_chapter(
    unit_name: str = "ICU-1",
    unit_type: str = "ICU",
    bed_count: int = 12,
    **chapter_kwargs,
) -> Dict[str, Any]:
    """Mapped chapter plus one hospital unit."""
    built = setup_mapped_chapter(**chapter_kwargs)
    built["unit"] = create_unit(unit_name, unit_type, bed_count)
    return built


# ===========================================================================
# Tier 3 — tracer lifecycle shortcuts
# ===========================================================================

def run_tracer(
    unit_id: str,
    chapter_id: str,
    observations: Sequence[Dict[str, Any]],
    window_start: str = "2026-08-10T08:00:00Z",
    window_end: str = "2026-08-10T12:00:00Z",
    start_clock: Optional[str] = "2026-08-10T09:00:00Z",
    tracer_type: str = "PATIENT",
    complete: bool = True,
) -> Dict[str, Any]:
    """Schedule a tracer, advance the clock into its window, start it, record
    every observation and (by default) complete it. `observations` entries are
    dicts of standard_id / result / optional weight."""
    tracer = schedule_tracer(
        unit_id, chapter_id, window_start, window_end, tracer_type=tracer_type
    )
    if start_clock is not None:
        set_clock(start_clock)
    tracer = tracer_action(tracer["id"], "START")
    for observation in observations:
        record_observation(
            tracer["id"],
            observation["standard_id"],
            observation["result"],
            observation.get("weight"),
            observation.get("note"),
        )
    if complete:
        tracer = tracer_action(tracer["id"], "COMPLETE")
    return tracer


def setup_unit_scored_78(
    unit_name: str = "ICU-1",
    unit_type: str = "ICU",
    bed_count: int = 12,
    clock: str = "2026-08-10T09:00:00Z",
    chapter_code: str = "EC",
    chapter_name: str = "Environment of Care",
    weight_pct: float = 100,
    evidence_min_count: Optional[int] = 1,
) -> Dict[str, Any]:
    """A single-chapter unit whose one completed tracer froze at 78.00.

    Chapter EC carries the whole weight; standard one is observed COMPLIANT at
    weight 39 and standard two NON_COMPLIANT at weight 11, so the chapter rate
    is 0.7800 and the unit's base score is 78.00 (band CONDITIONAL).
    """
    built = setup_mapped_chapter(
        code=chapter_code,
        name=chapter_name,
        weight_pct=weight_pct,
        evidence_min_count=evidence_min_count,
        standard_code=f"{chapter_code}.02.06.01",
        title="Safe environment",
        risk_tier="DIRECT_IMPACT",
    )
    second = create_standard(
        built["chapter"]["id"],
        f"{chapter_code}.02.05.01",
        "Utility systems maintained",
        "INDIRECT_IMPACT",
    )
    unit = create_unit(unit_name, unit_type, bed_count)
    tracer = run_tracer(
        unit["id"],
        built["chapter"]["id"],
        [
            {"standard_id": built["standard"]["id"], "result": "COMPLIANT", "weight": 39},
            {"standard_id": second["id"], "result": "NON_COMPLIANT", "weight": 11},
        ],
        window_start="2026-08-10T08:00:00Z",
        window_end="2026-08-10T12:00:00Z",
        start_clock=clock,
    )
    built.update({"second_standard": second, "unit": unit, "tracer": tracer})
    return built


def setup_unit_with_completed_tracer(
    results: Sequence[Dict[str, Any]],
    unit_name: str = "ICU-1",
    unit_type: str = "ICU",
    bed_count: int = 12,
    chapter_code: str = "EC",
    weight_pct: float = 100,
    clock: str = "2026-08-05T09:00:00Z",
    window_start: str = "2026-08-05T08:00:00Z",
    window_end: str = "2026-08-05T12:00:00Z",
    standard_count: int = 1,
    evidence_min_count: Optional[int] = 1,
    complete: bool = True,
) -> Dict[str, Any]:
    """Mapped chapter with `standard_count` standards, a unit, and one tracer
    walked through the supplied observation results. `results` entries are dicts
    of standard_index / result / optional weight."""
    built = setup_mapped_chapter(
        code=chapter_code,
        weight_pct=weight_pct,
        evidence_min_count=evidence_min_count,
        standard_code=f"{chapter_code}.02.06.01",
    )
    standards = [built["standard"]]
    for index in range(1, standard_count):
        standards.append(
            create_standard(
                built["chapter"]["id"],
                f"{chapter_code}.02.0{index}.01",
                f"Standard {index + 1}",
                "INDIRECT_IMPACT",
            )
        )
    unit = create_unit(unit_name, unit_type, bed_count)
    observations = [
        {
            "standard_id": standards[entry.get("standard_index", 0)]["id"],
            "result": entry["result"],
            "weight": entry.get("weight"),
        }
        for entry in results
    ]
    tracer = run_tracer(
        unit["id"],
        built["chapter"]["id"],
        observations,
        window_start=window_start,
        window_end=window_end,
        start_clock=clock,
        complete=complete,
    )
    built.update({"standards": standards, "unit": unit, "tracer": tracer})
    return built


# ===========================================================================
# Tier 4 — rounding, ticketing and penalty accumulation
# ===========================================================================

def setup_unit_with_ticket(
    severity: str = "MODERATE",
    round_type: str = "ENVIRONMENT_OF_CARE",
    unit_name: str = "ICU-14",
    unit_type: str = "ICU",
    bed_count: int = 12,
    window_start: str = "2026-08-01T08:00:00Z",
    window_end: str = "2026-08-01T12:00:00Z",
    close_session: bool = False,
    chapter_code: str = "EC",
    chapter_weight_pct: float = 100,
) -> Dict[str, Any]:
    """Mapped chapter + unit + one OPEN rounding session carrying one ticket."""
    built = setup_mapped_chapter(
        code=chapter_code,
        weight_pct=chapter_weight_pct,
        standard_code=f"{chapter_code}.02.06.01",
    )
    unit = create_unit(unit_name, unit_type, bed_count)
    session = open_rounding_session(unit["id"], round_type, window_start, window_end)
    ticket = raise_deficiency(session["id"], built["standard"]["id"], severity)
    if close_session:
        session = close_rounding_session(session["id"])
    built.update({"unit": unit, "session": session, "ticket": ticket})
    return built


def raise_tickets(
    session_id: str, standard_id: str, severities: Sequence[str]
) -> List[Dict[str, Any]]:
    """Raise one ticket per severity in order, returning them in creation order."""
    return [raise_deficiency(session_id, standard_id, severity) for severity in severities]


def setup_unit_at_penalty_points(
    severities: Sequence[str] = ("HIGH", "HIGH", "HIGH"),
    unit_name: str = "ICU-6",
    unit_type: str = "ICU",
    bed_count: int = 12,
    round_type: str = "ENVIRONMENT_OF_CARE",
    window_start: str = "2026-08-01T08:00:00Z",
    window_end: str = "2026-08-01T12:00:00Z",
) -> Dict[str, Any]:
    """Accumulate a chosen penalty total on one unit through successive tickets."""
    built = setup_unit_with_ticket(
        severity=severities[0],
        round_type=round_type,
        unit_name=unit_name,
        unit_type=unit_type,
        bed_count=bed_count,
        window_start=window_start,
        window_end=window_end,
    )
    tickets = [built["ticket"]]
    for severity in severities[1:]:
        tickets.append(
            raise_deficiency(built["session"]["id"], built["standard"]["id"], severity)
        )
    built["tickets"] = tickets
    built["unit"] = read_unit(built["unit"]["id"])
    return built


def setup_immediate_threat_ticket(
    unit_name: str = "ICU-11",
    bed_count: int = 12,
    window_start: str = "2026-08-01T08:00:00Z",
    window_end: str = "2026-08-01T12:00:00Z",
) -> Dict[str, Any]:
    """A LIFE_SAFETY ticket escalated to IMMEDIATE_THREAT, which restricts its
    unit and freezes tracer scheduling hospital-wide."""
    built = setup_unit_with_ticket(
        severity="HIGH",
        round_type="LIFE_SAFETY",
        unit_name=unit_name,
        unit_type="ICU",
        bed_count=bed_count,
        window_start=window_start,
        window_end=window_end,
    )
    built["ticket"] = ticket_action(built["ticket"]["id"], "ESCALATE")
    built["unit"] = read_unit(built["unit"]["id"])
    return built


# ===========================================================================
# Tier 4 — evidence repository states
# ===========================================================================

def setup_evidence_item(
    validation_state: str = "DRAFT",
    expires_at: Optional[str] = None,
    evidence_min_count: Optional[int] = 1,
    owner_user_id: str = OWNER_USER_ID,
    validator_user_id: str = VALIDATOR_USER_ID,
    chapter_code: str = "EC",
    with_owner: bool = True,
) -> Dict[str, Any]:
    """Mapped standard plus one evidence item walked to the requested state."""
    chapter = create_chapter(chapter_code, "Environment of Care", 100, evidence_min_count)
    standard = create_standard(chapter["id"], f"{chapter_code}.02.06.01", "Safe environment")
    assignment = assign_owner(standard["id"], owner_user_id) if with_owner else None
    evidence = file_evidence(standard["id"], expires_at=expires_at, owner_user_id=owner_user_id)
    if validation_state in ("SUBMITTED", "VALIDATED", "REJECTED"):
        evidence = evidence_action(
            evidence["id"], "SUBMIT", make_standard_owner_headers(owner_user_id)
        )
    if validation_state in ("VALIDATED", "REJECTED"):
        evidence = evidence_action(
            evidence["id"], "VALIDATE", make_evidence_validator_headers(validator_user_id)
        )
    if validation_state == "REJECTED":
        evidence = evidence_action(
            evidence["id"], "REJECT", make_evidence_validator_headers(validator_user_id)
        )
    return {
        "chapter": chapter,
        "standard": standard,
        "assignment": assignment,
        "evidence": evidence,
    }


# ===========================================================================
# Tier 5 — survey windows, findings and the response cycle
# ===========================================================================

def setup_eligible_window(
    cycle_label: str = "CYCLE-2026",
    prior_survey_end_date: str = "2025-03-15T00:00:00Z",
    clock: str = "2026-09-20T00:00:00Z",
    activate_command_center: bool = True,
) -> Dict[str, Any]:
    """A survey window swept to ELIGIBLE by a clock advance, with the command
    center activated by default."""
    window = create_survey_window(cycle_label, prior_survey_end_date)
    clock_result = set_clock(clock)
    if activate_command_center:
        window = window_action(window["id"], "ACTIVATE_COMMAND_CENTER")
    else:
        window = get_success_data(api_client.get_survey_window(window["id"], DIRECTOR))
    return {"window": window, "clock": clock_result}


def setup_active_survey(
    cycle_label: str = "CYCLE-2026",
    prior_survey_end_date: str = "2025-03-15T00:00:00Z",
    clock: str = "2026-09-20T00:00:00Z",
) -> Dict[str, Any]:
    """A window driven all the way to ACTIVE_SURVEY."""
    built = setup_eligible_window(cycle_label, prior_survey_end_date, clock, True)
    built["window"] = window_action(built["window"]["id"], "OPEN_SURVEY")
    return built


def setup_survey_finding(
    chapter_code: str = "LD",
    chapter_name: str = "Leadership",
    weight_pct: float = 100,
    evidence_min_count: Optional[int] = 1,
    standard_code: str = "LD.04.01.05",
    standard_title: str = "Contracted services oversight",
    risk_tier: str = "SITUATIONAL_DECISION_RULE",
    owner_user_id: str = OWNER_USER_ID,
    unit_name: str = "MED-12",
    unit_type: str = "MED_SURG",
    bed_count: int = 26,
    cycle_label: str = "CYCLE-2026",
    prior_survey_end_date: str = "2025-03-15T00:00:00Z",
    open_clock: str = "2026-09-20T00:00:00Z",
    sampled_count: int = 10,
    observed_noncompliance_count: int = 2,
    patient_harm_observed: bool = False,
    close_clock: Optional[str] = "2026-09-25T00:00:00Z",
    escalate: bool = False,
) -> Dict[str, Any]:
    """Mapped chapter + unit + active survey + one finding, optionally escalated
    and optionally carried through survey close (which moves the finding to
    RESPONSE_PENDING and sets its response deadlines)."""
    built = setup_mapped_chapter(
        code=chapter_code,
        name=chapter_name,
        weight_pct=weight_pct,
        evidence_min_count=evidence_min_count,
        standard_code=standard_code,
        title=standard_title,
        risk_tier=risk_tier,
        owner_user_id=owner_user_id,
    )
    unit = create_unit(unit_name, unit_type, bed_count)
    survey = setup_active_survey(cycle_label, prior_survey_end_date, open_clock)
    finding = create_finding(
        survey["window"]["id"],
        built["standard"]["id"],
        unit["id"],
        sampled_count,
        observed_noncompliance_count,
        patient_harm_observed,
    )
    if close_clock is not None:
        set_clock(close_clock)
        survey["window"] = window_action(survey["window"]["id"], "CLOSE_SURVEY")
        finding = read_finding(finding["id"])
    if escalate:
        finding = escalate_finding(finding["id"])
        survey["window"] = get_success_data(
            api_client.get_survey_window(survey["window"]["id"], DIRECTOR)
        )
    built.update({"unit": unit, "window": survey["window"], "finding": finding})
    return built


def setup_closed_survey_ld_finding(**overrides) -> Dict[str, Any]:
    """The leadership-chapter finding used by the response-cycle scenarios: two
    of ten sampled elements non-compliant on a situational-decision-rule
    standard, so the finding is LOW risk, not condition level, and gets sixty
    days from survey close."""
    defaults: Dict[str, Any] = {}
    defaults.update(overrides)
    return setup_survey_finding(**defaults)


def setup_closed_survey_condition_level_finding(**overrides) -> Dict[str, Any]:
    """A life-safety finding on a direct-impact standard, eight of ten sampled
    elements non-compliant: WIDESPREAD, condition level, IMMEDIATE_THREAT."""
    defaults: Dict[str, Any] = {
        "chapter_code": "LS",
        "chapter_name": "Life Safety",
        "standard_code": "LS.01.01.01",
        "standard_title": "Egress protection",
        "risk_tier": "DIRECT_IMPACT",
        "sampled_count": 10,
        "observed_noncompliance_count": 8,
        "patient_harm_observed": False,
    }
    defaults.update(overrides)
    return setup_survey_finding(**defaults)


def setup_response_pending_finding_ready_to_submit(**overrides) -> Dict[str, Any]:
    """A closed-survey finding awaiting the hospital's corrective-action plan."""
    return setup_closed_survey_ld_finding(**overrides)


# ===========================================================================
# Tier 5 — periodic performance review states
# ===========================================================================

def setup_chapter_with_flagged_ppr(
    chapter_code: str = "PC",
    chapter_name: str = "Provision of Care",
    weight_pct: float = 100,
    evidence_min_count: Optional[int] = 1,
    standard_code: str = "PC.01.02.03",
    period_label: str = "2026-H1",
    rating: str = "COMPLIANT",
) -> Dict[str, Any]:
    """One mapped standard rated COMPLIANT with no validated evidence, so the
    self-reported and evidence-verified variants diverge by fifty points and the
    assessment is flagged for overstatement."""
    built = setup_mapped_chapter(
        code=chapter_code,
        name=chapter_name,
        weight_pct=weight_pct,
        evidence_min_count=evidence_min_count,
        standard_code=standard_code,
        title="Care planning",
        risk_tier="DIRECT_IMPACT",
    )
    built["ppr"] = file_ppr(
        built["chapter"]["id"],
        period_label,
        [{"standard_id": built["standard"]["id"], "rating": rating}],
    )
    return built


def setup_chapter_with_two_flagged_pprs(
    chapter_code: str = "PC",
    first_period: str = "2026-H1",
    second_period: str = "2026-H2",
) -> Dict[str, Any]:
    """Two flagged assessments drive `ppr_escalation_count` to two, which flips
    the chapter to AT_RISK and returns both assessments for reassessment."""
    built = setup_chapter_with_flagged_ppr(chapter_code=chapter_code, period_label=first_period)
    built["second_ppr"] = file_ppr(
        built["chapter"]["id"],
        second_period,
        [{"standard_id": built["standard"]["id"], "rating": "COMPLIANT"}],
    )
    built["chapter"] = read_chapter(built["chapter"]["id"])
    built["ppr"] = get_success_data(
        api_client.list_ppr_self_assessments(built["chapter"]["id"], DIRECTOR)
    )[0]
    return built
