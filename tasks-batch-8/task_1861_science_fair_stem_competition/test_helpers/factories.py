"""Payload factories — one per entity, input fields only (PRD §3-§4)."""
import uuid

from .constants import (
    DEFAULT_ADVANCEMENT_SLOTS,
    DEFAULT_MAX_JUDGES_PER_PROJECT,
    DEFAULT_MIN_QUORUM_RATIO_PCT,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)


def _unique_email(prefix: str = "mentor") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def fair_edition_payload(
    name="Test Edition",
    normalization_algorithm="Z_SCORE",
    max_judges_per_project=DEFAULT_MAX_JUDGES_PER_PROJECT,
    min_quorum_ratio_pct=DEFAULT_MIN_QUORUM_RATIO_PCT,
    **overrides,
) -> dict:
    defaults = {
        "name": name,
        "normalization_algorithm": normalization_algorithm,
        "max_judges_per_project": max_judges_per_project,
        "min_quorum_ratio_pct": min_quorum_ratio_pct,
    }
    defaults.update(overrides)
    return defaults


def category_payload(
    fair_edition_id,
    code="PHYS",
    name="Physics & Astronomy",
    grade_band="SENIOR",
    advancement_slots=DEFAULT_ADVANCEMENT_SLOTS,
    **overrides,
) -> dict:
    defaults = {
        "fair_edition_id": fair_edition_id,
        "code": code,
        "name": name,
        "grade_band": grade_band,
        "advancement_slots": advancement_slots,
    }
    defaults.update(overrides)
    return defaults


def mentor_payload(full_name="Test Mentor", email=None, **overrides) -> dict:
    defaults = {
        "full_name": full_name,
        "email": email or _unique_email(),
    }
    defaults.update(overrides)
    return defaults


def project_payload(
    fair_edition_id,
    category_id,
    title="Test Project",
    team_size=1,
    involves_human_subjects=False,
    involves_animal_subjects=False,
    **overrides,
) -> dict:
    defaults = {
        "fair_edition_id": fair_edition_id,
        "category_id": category_id,
        "title": title,
        "team_size": team_size,
        "involves_human_subjects": involves_human_subjects,
        "involves_animal_subjects": involves_animal_subjects,
    }
    defaults.update(overrides)
    return defaults


def research_plan_payload(
    project_id,
    plan_text="Research plan narrative",
    risk_level="LOW",
    **overrides,
) -> dict:
    defaults = {
        "project_id": project_id,
        "plan_text": plan_text,
        "risk_level": risk_level,
    }
    defaults.update(overrides)
    return defaults


def ethics_decision_payload(reviewer_mentor_id, decision="APPROVE", rationale=None, **overrides) -> dict:
    payload = {
        "reviewer_mentor_id": reviewer_mentor_id,
        "decision": decision,
    }
    if rationale is not None:
        payload["rationale"] = rationale
    payload.update(overrides)
    return payload


def judge_payload(
    fair_edition_id,
    full_name="Test Judge",
    max_assignments=9,
    expertise_category_ids=None,
    **overrides,
) -> dict:
    payload = {
        "fair_edition_id": fair_edition_id,
        "full_name": full_name,
        "max_assignments": max_assignments,
    }
    if expertise_category_ids is not None:
        payload["expertise_category_ids"] = expertise_category_ids
    payload.update(overrides)
    return payload


def conflict_payload(project_id, reason="mentor at same school", **overrides) -> dict:
    defaults = {"project_id": project_id, "reason": reason}
    defaults.update(overrides)
    return defaults


def score_sheet_payload(raw_score, **overrides) -> dict:
    defaults = {"raw_score": raw_score}
    defaults.update(overrides)
    return defaults


def booth_payload(
    hall="A",
    booth_number=1,
    inspection_window_start=DEFAULT_WINDOW_START,
    inspection_window_end=DEFAULT_WINDOW_END,
    **overrides,
) -> dict:
    defaults = {
        "hall": hall,
        "booth_number": booth_number,
        "inspection_window_start": inspection_window_start,
        "inspection_window_end": inspection_window_end,
    }
    defaults.update(overrides)
    return defaults


def inspection_result_payload(result="PASS", **overrides) -> dict:
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults


def award_payload(fair_edition_id, project_id, award_type="CATEGORY_FIRST", **overrides) -> dict:
    defaults = {
        "fair_edition_id": fair_edition_id,
        "project_id": project_id,
        "award_type": award_type,
    }
    defaults.update(overrides)
    return defaults


def scholarship_pool_payload(fair_edition_id, total_cents, **overrides) -> dict:
    defaults = {"fair_edition_id": fair_edition_id, "total_cents": total_cents}
    defaults.update(overrides)
    return defaults
