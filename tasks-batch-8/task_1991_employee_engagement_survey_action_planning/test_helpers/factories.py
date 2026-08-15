"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_CLOSES_AT,
    DEFAULT_ITEM_TARGET_AT,
    DEFAULT_OPENS_AT,
    DEFAULT_PLAN_DUE_AT,
    HIRED_LONG_AGO,
    TEST_DEFAULTS,
)


def create_item_bank_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "name": "Test Bank",
        "framework": TEST_DEFAULTS["BANK_FRAMEWORK"],
    }
    defaults.update(overrides)
    return defaults


def create_survey_item_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "item_code": "ITEM-01",
        "dimension": TEST_DEFAULTS["ITEM_DIMENSION"],
        "weight": TEST_DEFAULTS["ITEM_WEIGHT"],
    }
    defaults.update(overrides)
    return defaults


def create_org_unit_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "name": "Test Unit",
        "manager_user_id": "mgr-test",
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "external_ref": "EMP-001",
        "unit_id": "",
        "employment_status": "ACTIVE",
        "hired_at": HIRED_LONG_AGO,
    }
    defaults.update(overrides)
    return defaults


def create_survey_cycle_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "label": "Test Cycle",
        "cycle_kind": "CENSUS",
        "bank_id": "",
        "opens_at": DEFAULT_OPENS_AT,
        "closes_at": DEFAULT_CLOSES_AT,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_item_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "item_id": "",
        "pinned_weight": TEST_DEFAULTS["ITEM_WEIGHT"],
        "display_order": 1,
    }
    defaults.update(overrides)
    return defaults


def create_benchmark_set_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "name": "Benchmark 2026",
        "dimension_scores": [40.0, 50.0, 60.0, 70.0, 80.0],
    }
    defaults.update(overrides)
    return defaults


def create_action_plan_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "cycle_id": "",
        "unit_id": "",
        "title": "Improvement plan",
        "focus_dimension": "PURPOSE",
        "due_at": DEFAULT_PLAN_DUE_AT,
    }
    defaults.update(overrides)
    return defaults


def create_action_item_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "description": "Milestone one",
        "owner_user_id": "mgr-test",
        "target_at": DEFAULT_ITEM_TARGET_AT,
    }
    defaults.update(overrides)
    return defaults


def create_outcome_linkage_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "cycle_id": "",
        "outcome_kind": "ATTRITION",
        "outcome_value": "VOLUNTARY",
    }
    defaults.update(overrides)
    return defaults


def build_answers(cycle_item_ids: List[str], scores: List[int],
                  comments: Optional[List[Optional[str]]] = None) -> List[dict]:
    """One answer per pinned cycle item: {cycle_item_id, score, comment?} (§3.4)."""
    answers = []
    for idx, cycle_item_id in enumerate(cycle_item_ids):
        entry: Dict[str, Any] = {
            "cycle_item_id": cycle_item_id,
            "score": scores[idx],
        }
        if comments and idx < len(comments) and comments[idx] is not None:
            entry["comment"] = comments[idx]
        answers.append(entry)
    return answers
