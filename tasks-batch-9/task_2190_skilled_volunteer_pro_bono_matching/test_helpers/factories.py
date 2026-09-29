"""Payload factories — one per resource, input fields only."""
import itertools

_seq = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_seq):05d}"


def partner_org_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "name": f"Riverside Literacy Trust {suffix}",
        "contact_email": f"ops+{suffix}@riverside.example",
        "sector": "EDUCATION",
        "annual_budget_usd": 3000000.00,
    }
    payload.update(overrides)
    return payload


def program_cycle_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "cycle_code": f"2026-Q4-{suffix}",
        "starts_at": "2026-08-01T00:00:00Z",
        "ends_at": "2026-12-01T00:00:00Z",
        "capacity_slot_total": 10,
    }
    payload.update(overrides)
    return payload


def project_request_payload(partner_org_id: str, cycle_id: str, **overrides) -> dict:
    payload = {
        "partner_org_id": partner_org_id,
        "cycle_id": cycle_id,
        "title": "Annual audit readiness",
        "discipline": "ACCOUNTING",
        "required_skill_code": "TAX_LAW",
        "min_proficiency": 3,
        "requested_hours": 40.00,
        "urgency": "ROUTINE",
    }
    payload.update(overrides)
    return payload


def scope_definition_payload(expected_project_request_version: int, **overrides) -> dict:
    payload = {
        "expected_project_request_version": expected_project_request_version,
        "estimated_hours": 40.00,
        "complexity_factor": 1.00,
        "confidentiality_tier": "STANDARD",
        "ip_disposition": "ASSIGN_TO_PARTNER",
    }
    payload.update(overrides)
    return payload


def deliverable_payload(**overrides) -> dict:
    payload = {
        "title": "Findings memo",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "Board-ready memo with cited findings.",
    }
    payload.update(overrides)
    return payload


def volunteer_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "full_name": f"Dana Okafor {suffix}",
        "email": f"dana+{suffix}@volunteers.example",
        "professional_rate_usd_per_hour": 150.00,
        "seniority": "SENIOR",
        "weekly_hours_cap": 40,
    }
    payload.update(overrides)
    return payload


def skill_profile_payload(**overrides) -> dict:
    payload = {"skill_code": "TAX_LAW", "proficiency": 4, "years_experience": 10.0}
    payload.update(overrides)
    return payload


def availability_window_payload(**overrides) -> dict:
    payload = {
        "starts_at": "2026-08-01T00:00:00Z",
        "ends_at": "2026-11-01T00:00:00Z",
        "window_kind": "HARD",
        "hours_offered": 300.00,
    }
    payload.update(overrides)
    return payload


def agreement_payload(expected_engagement_version: int, **overrides) -> dict:
    payload = {
        "expected_engagement_version": expected_engagement_version,
        "ip_disposition": "ASSIGN_TO_PARTNER",
        "confidentiality_tier": "STANDARD",
        "indemnity_cap_usd": 10000.00,
    }
    payload.update(overrides)
    return payload


def counter_payload(**overrides) -> dict:
    payload = {
        "ip_disposition": "ASSIGN_TO_PARTNER",
        "confidentiality_tier": "STANDARD",
        "indemnity_cap_usd": 5000.00,
    }
    payload.update(overrides)
    return payload


def time_log_payload(**overrides) -> dict:
    payload = {
        "work_date": "2026-08-12T00:00:00Z",
        "hours": 4.00,
        "activity_class": "DELIVERY",
    }
    payload.update(overrides)
    return payload


def milestone_payload(**overrides) -> dict:
    payload = {"due_at": "2026-08-20T00:00:00Z"}
    payload.update(overrides)
    return payload


def scope_change_request_payload(**overrides) -> dict:
    payload = {
        "additional_hours": 4.00,
        "additional_deliverable_count": 0,
        "justification": "Additional lease schedules surfaced during review.",
    }
    payload.update(overrides)
    return payload


def handoff_payload(**overrides) -> dict:
    payload = {"confidentiality_attested": True, "handoff_artifact_count": 3}
    payload.update(overrides)
    return payload


def valuation_payload(expected_engagement_version: int, **overrides) -> dict:
    payload = {
        "expected_engagement_version": expected_engagement_version,
        "method": "INDEPENDENT_SECTOR",
    }
    payload.update(overrides)
    return payload


def satisfaction_survey_payload(**overrides) -> dict:
    payload = {
        "score_expertise": 5,
        "score_responsiveness": 4,
        "score_deliverable_fit": 5,
        "would_recommend": True,
    }
    payload.update(overrides)
    return payload


def deliverable_scores_payload(scores: dict) -> dict:
    """`scores` maps deliverable_id -> review_score."""
    return {
        "deliverable_scores": [
            {"deliverable_id": did, "review_score": score}
            for did, score in scores.items()
        ]
    }
