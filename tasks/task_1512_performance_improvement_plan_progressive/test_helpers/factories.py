"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "OU_NAME": "OU1",
    "MANAGER_NAME": "Boss M1",
    "HRBP_NAME": "HRBP H1",
    "DIRECTOR_NAME": "Director D1",
    "COUNSEL_NAME": "Counsel L1",
    "EMPLOYEE_NAME": "E1 Subject",
    "CONCERN_SUMMARY": "Quality below bar for level",
    "TEMPLATE_NAME": "Eng L5 quality PIP",
    "DURATION_DAYS": 30,
    "CADENCE_DAYS": 10,
    "START_DATE": "2026-08-01T00:00:00Z",
    "CHECKIN_AT": "2026-08-11T00:00:00Z",
    "NOTES": "Reviewed current trajectory against goals in depth.",
    "RATIONALE": "Outcome rationale meeting the forty character floor.",
    "REBUTTAL_BODY": (
        "I dispute the attainment computation and request an independent "
        "re-tabulation of the goal evidence used at decision time."
    ),
}

# Narratives must be >= 40 chars (PRD §3.2).
NARRATIVE_A = (
    "Defect rate above team norm for two sprints; reviewed expectations and "
    "paired on RCA for the last three incidents."
)
NARRATIVE_B = (
    "Story-point throughput below target for sprint 12; agreed on daily "
    "standup check-ins and scope trimming tactics."
)


def create_org_unit_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["OU_NAME"]}
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["EMPLOYEE_NAME"],
        "email": "employee@x.com",
        "job_family": "ENGINEERING",
        "job_level": 5,
    }
    defaults.update(overrides)
    return defaults


def create_coaching_entry_payload(**overrides) -> dict:
    defaults = {
        "occurred_at": "2026-07-01T10:00:00Z",
        "category": "QUALITY",
        "severity": "DOCUMENTED",
        "narrative": NARRATIVE_A,
    }
    defaults.update(overrides)
    return defaults


def create_concern_payload(coaching_log_entry_ids, **overrides) -> dict:
    defaults = {
        "category": "QUALITY",
        "summary": DEFAULTS["CONCERN_SUMMARY"],
        "coaching_log_entry_ids": list(coaching_log_entry_ids),
    }
    defaults.update(overrides)
    return defaults


def create_pip_template_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TEMPLATE_NAME"],
        "category": "QUALITY",
        "goal_blueprints": [
            {"metric_key": "defects", "target_value": 2, "unit": "count", "weight": 100}
        ],
        "duration_days": DEFAULTS["DURATION_DAYS"],
        "check_in_cadence_days": DEFAULTS["CADENCE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_pip_payload(concern_id, template_id, **overrides) -> dict:
    defaults = {
        "concern_id": concern_id,
        "template_id": template_id,
        "start_date": DEFAULTS["START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_check_in_payload(**overrides) -> dict:
    defaults = {"scheduled_for": DEFAULTS["CHECKIN_AT"]}
    defaults.update(overrides)
    return defaults


def create_mark_held_payload(**overrides) -> dict:
    defaults = {
        "manager_attended": True,
        "hrbp_attended": True,
        "notes": DEFAULTS["NOTES"],
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(pip_goal_id, **overrides) -> dict:
    defaults = {
        "pip_goal_id": pip_goal_id,
        "observed_value": 1,
        "source": "SYSTEM_REPORT",
    }
    defaults.update(overrides)
    return defaults


def create_legal_review_payload(assigned_counsel_id, **overrides) -> dict:
    defaults = {"assigned_counsel_id": assigned_counsel_id}
    defaults.update(overrides)
    return defaults


def submit_legal_review_payload(**overrides) -> dict:
    defaults = {
        "risk_factors": [],
        "recommendation": "PROCEED",
        "rationale": "Documentation complete; no legal risk factors identified.",
    }
    defaults.update(overrides)
    return defaults


def create_outcome_decision_payload(**overrides) -> dict:
    defaults = {
        "proposed_outcome": "SUCCESS",
        "rationale": DEFAULTS["RATIONALE"],
    }
    defaults.update(overrides)
    return defaults


def create_rebuttal_payload(outcome_decision_id, **overrides) -> dict:
    defaults = {
        "outcome_decision_id": outcome_decision_id,
        "body": DEFAULTS["REBUTTAL_BODY"],
    }
    defaults.update(overrides)
    return defaults


def create_rating_cycle_payload(**overrides) -> dict:
    defaults = {
        "label": "2026-H2",
        "window_start": "2026-07-01T00:00:00Z",
        "window_end": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_consistency_review_payload(target_pip_id, **overrides) -> dict:
    defaults = {"target_pip_id": target_pip_id}
    defaults.update(overrides)
    return defaults
