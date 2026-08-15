"""Payload factories — one per creatable resource, input fields only (PRD §3)."""


def team_payload(
    name="Test Team",
    sport="SOCCER",
    season_start_date="2026-08-01",
    season_end_date="2026-12-01",
    hipaa_mode=None,
    acwr_variant=None,
) -> dict:
    payload = {
        "name": name,
        "sport": sport,
        "season_start_date": season_start_date,
        "season_end_date": season_end_date,
    }
    if hipaa_mode is not None:
        payload["hipaa_mode"] = hipaa_mode
    if acwr_variant is not None:
        payload["acwr_variant"] = acwr_variant
    return payload


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def diagnosis_code_payload(
    code="S83.5",
    body_region="KNEE",
    severity_class="MINOR",
    is_concussion=False,
) -> dict:
    return {
        "code": code,
        "body_region": body_region,
        "severity_class": severity_class,
        "is_concussion": is_concussion,
    }


def athlete_payload(
    team_id,
    full_name="Test Athlete",
    position="F",
    enrollment_date="2026-08-01",
) -> dict:
    return {
        "team_id": team_id,
        "full_name": full_name,
        "position": position,
        "enrollment_date": enrollment_date,
    }


def injury_case_payload(
    athlete_id,
    diagnosis_code_id,
    occurred_on="2026-08-01",
    surface="GRASS",
    mechanism="CONTACT",
) -> dict:
    return {
        "athlete_id": athlete_id,
        "diagnosis_code_id": diagnosis_code_id,
        "occurred_on": occurred_on,
        "surface": surface,
        "mechanism": mechanism,
    }


def treatment_plan_payload(
    injury_case_id,
    title="Rehab plan",
    planned_sessions_per_week=3,
    estimated_duration_weeks=3,
) -> dict:
    return {
        "injury_case_id": injury_case_id,
        "title": title,
        "planned_sessions_per_week": planned_sessions_per_week,
        "estimated_duration_weeks": estimated_duration_weeks,
    }


def daily_status_entry_payload(
    injury_case_id,
    entry_date,
    designation="OUT",
    symptom_free=False,
    functional_test_score=40,
    notes=None,
    supersedes_entry_id=None,
) -> dict:
    payload = {
        "injury_case_id": injury_case_id,
        "entry_date": entry_date,
        "designation": designation,
        "symptom_free": symptom_free,
        "functional_test_score": functional_test_score,
    }
    if notes is not None:
        payload["notes"] = notes
    if supersedes_entry_id is not None:
        payload["supersedes_entry_id"] = supersedes_entry_id
    return payload


def rtp_protocol_payload(injury_case_id, total_stages=3) -> dict:
    return {"injury_case_id": injury_case_id, "total_stages": total_stages}


def advance_payload(expected_protocol_version) -> dict:
    return {"expected_protocol_version": expected_protocol_version}


def regress_payload(reason="symptom recurrence") -> dict:
    return {"reason": reason}


def clearance_request_payload(expected_protocol_version, request_notes=None) -> dict:
    payload = {"expected_protocol_version": expected_protocol_version}
    if request_notes is not None:
        payload["request_notes"] = request_notes
    return payload


def clearance_decision_payload(decision, decision_notes=None) -> dict:
    payload = {"decision": decision}
    if decision_notes is not None:
        payload["decision_notes"] = decision_notes
    return payload


def workload_session_payload(
    athlete_id,
    session_date,
    session_type="PRACTICE",
    surface="GRASS",
    duration_minutes=60,
    rpe=5,
) -> dict:
    return {
        "athlete_id": athlete_id,
        "session_date": session_date,
        "session_type": session_type,
        "surface": surface,
        "duration_minutes": duration_minutes,
        "rpe": rpe,
    }


def insurance_policy_payload(
    athlete_id,
    payer_name="Payer",
    policy_number="PN-1",
    deductible_cents=0,
    coinsurance_pct=80,
    oop_max_cents=500000,
    policy_year_start="2026-01-01",
    policy_year_end="2026-12-31",
) -> dict:
    return {
        "athlete_id": athlete_id,
        "payer_name": payer_name,
        "policy_number": policy_number,
        "deductible_cents": deductible_cents,
        "coinsurance_pct": coinsurance_pct,
        "oop_max_cents": oop_max_cents,
        "policy_year_start": policy_year_start,
        "policy_year_end": policy_year_end,
    }


def claim_line_item(cpt_code="X1", charge_cents=10000, service_date="2026-08-02") -> dict:
    return {"cpt_code": cpt_code, "charge_cents": charge_cents, "service_date": service_date}


def claim_payload(
    injury_case_id,
    insurance_policy_id,
    billed_amount_cents,
    line_items=None,
    supersedes_claim_id=None,
) -> dict:
    if line_items is None:
        line_items = [claim_line_item(charge_cents=billed_amount_cents)]
    payload = {
        "injury_case_id": injury_case_id,
        "insurance_policy_id": insurance_policy_id,
        "billed_amount_cents": billed_amount_cents,
        "line_items": line_items,
    }
    if supersedes_claim_id is not None:
        payload["supersedes_claim_id"] = supersedes_claim_id
    return payload


def claim_submit_payload(expected_policy_version) -> dict:
    return {"expected_policy_version": expected_policy_version}


def appeal_payload(appeal_reason="additional documentation") -> dict:
    return {"appeal_reason": appeal_reason}


def disclosure_grant_payload(
    athlete_id,
    grantee_role="COACHING",
    scope="GENERAL",
    effective_from="2026-08-01",
    effective_to="2026-12-31",
) -> dict:
    return {
        "athlete_id": athlete_id,
        "grantee_role": grantee_role,
        "scope": scope,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }


def availability_report_payload(team_id, audience="MEDICAL") -> dict:
    return {"team_id": team_id, "audience": audience}
