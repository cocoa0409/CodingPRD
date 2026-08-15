"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Per-entity structural assertions
# ---------------------------------------------------------------------------

def assert_category(data: dict):
    assert is_valid_uuid(data.get("id", "")), "category id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("name"), str) and data["name"], "name must be non-empty"
    assert "parent_category_id" in data, "parent_category_id must be present (may be null)"
    if data["parent_category_id"] is not None:
        assert is_valid_uuid(data["parent_category_id"]), \
            "parent_category_id must be UUID when set"
    assert isinstance(data.get("weight_factor"), (int, float)), \
        "weight_factor must be numeric"
    assert "current_tolerance_score" in data, \
        "current_tolerance_score must be present (may be null)"
    if data["current_tolerance_score"] is not None:
        assert isinstance(data["current_tolerance_score"], int)


def assert_risk(data: dict):
    assert is_valid_uuid(data.get("id", "")), "risk id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("category_id"), str) and data["category_id"]
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("owner_user_id"), str) and data["owner_user_id"]
    assert isinstance(data.get("treatment_budget_cents"), int)
    assert data["treatment_budget_cents"] >= 0
    assert data.get("status") in (
        "DRAFT", "IDENTIFIED", "ASSESSED", "TREATMENT",
        "MONITORING", "REASSESSMENT", "CLOSED",
    )
    # score fields may be null until first INHERENT / first residual computation
    assert "likelihood" in data
    assert "impact" in data
    assert "inherent_score" in data
    assert "inherent_band" in data
    assert "residual_score" in data
    assert "residual_band" in data
    if data["inherent_score"] is not None:
        assert isinstance(data["inherent_score"], int)
        assert 1 <= data["inherent_score"] <= 25
    if data["inherent_band"] is not None:
        assert data["inherent_band"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    if data["residual_score"] is not None:
        assert isinstance(data["residual_score"], int)
        assert 1 <= data["residual_score"] <= 25
    if data["residual_band"] is not None:
        assert data["residual_band"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(data.get("reserved_treatment_cents"), int)
    assert data["reserved_treatment_cents"] >= 0
    assert isinstance(data.get("available_treatment_cents"), int)
    assert isinstance(data.get("kri_alert"), bool)


def assert_assessment(data: dict):
    """Append-only: id + created_at only from common fields; NO version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "assessment id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "RiskAssessment must not expose version"
    assert "updated_at" not in data, "RiskAssessment must not expose updated_at"
    assert isinstance(data.get("risk_id"), str) and data["risk_id"]
    assert data.get("kind") in ("INHERENT", "RESIDUAL")
    assert "inherent_score" in data
    if data["inherent_score"] is not None:
        assert isinstance(data["inherent_score"], int)
    assert "breach_created" in data
    assert isinstance(data["breach_created"], bool)


def assert_control(data: dict):
    assert is_valid_uuid(data.get("id", "")), "control id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("effectiveness_pct"), (int, float))
    assert 0 < data["effectiveness_pct"] <= 1.0
    assert isinstance(data.get("max_mapped_risks"), int)
    assert data["max_mapped_risks"] >= 1
    assert isinstance(data.get("mapped_active_count"), int)
    assert data["mapped_active_count"] >= 0
    assert data.get("status") in ("PROPOSED", "ACTIVE", "UNDER_REVIEW", "RETIRED")


def assert_mapping(data: dict):
    assert is_valid_uuid(data.get("id", "")), "mapping id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("risk_id"), str) and data["risk_id"]
    assert isinstance(data.get("control_id"), str) and data["control_id"]
    assert isinstance(data.get("coverage_weight"), (int, float))
    assert 0 < data["coverage_weight"] <= 1.0
    assert data.get("status") in ("PROPOSED", "ACTIVE", "RETIRED")


def assert_appetite(data: dict):
    assert is_valid_uuid(data.get("id", "")), "appetite id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("category_id"), str) and data["category_id"]
    assert isinstance(data.get("tolerance_score"), int)
    assert 1 <= data["tolerance_score"] <= 25
    assert isinstance(data.get("acceptance_cap_score"), int)
    assert 1 <= data["acceptance_cap_score"] <= 25
    assert data["acceptance_cap_score"] >= data["tolerance_score"]
    assert isinstance(data.get("effective_from"), str)
    assert isinstance(data.get("effective_to"), str)
    assert data.get("status") in ("DRAFT", "APPROVED", "RETIRED")
    assert isinstance(data.get("created_by"), str) and data["created_by"]


def assert_breach(data: dict):
    assert is_valid_uuid(data.get("id", "")), "breach id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("risk_id"), str) and data["risk_id"]
    assert isinstance(data.get("appetite_statement_id"), str) and data["appetite_statement_id"]
    assert isinstance(data.get("residual_at_breach"), int)
    assert data.get("status") in ("OPEN", "ACKNOWLEDGED", "RESOLVED", "ACCEPTED")


def assert_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "plan id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("risk_id"), str) and data["risk_id"]
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("budget_cents"), int)
    assert data["budget_cents"] > 0
    assert isinstance(data.get("due_date"), str)
    assert isinstance(data.get("owner_user_id"), str) and data["owner_user_id"]
    assert isinstance(data.get("proposer_user_id"), str) and data["proposer_user_id"]
    assert data.get("status") in (
        "PROPOSED", "APPROVED", "IN_PROGRESS", "OVERDUE",
        "COMPLETED", "REJECTED", "CANCELLED",
    )
    assert data.get("priority") in ("STANDARD", "URGENT")
    assert isinstance(data.get("extension_count"), int)
    assert data["extension_count"] >= 0
    assert isinstance(data.get("progress_pct"), (int, float))
    assert 0 <= data["progress_pct"] <= 100


def assert_action(data: dict):
    assert is_valid_uuid(data.get("id", "")), "action id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("plan_id"), str) and data["plan_id"]
    assert isinstance(data.get("title"), str) and data["title"]
    assert data.get("status") in ("PENDING", "DONE")


def assert_kri(data: dict):
    assert is_valid_uuid(data.get("id", "")), "kri id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("category_id"), str) and data["category_id"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("direction") in ("ABOVE", "BELOW")
    assert isinstance(data.get("amber_threshold"), (int, float))
    assert isinstance(data.get("red_threshold"), (int, float))
    assert isinstance(data.get("min_observation_interval_days"), int)
    assert data["min_observation_interval_days"] >= 0
    assert data.get("status") in ("DRAFT", "ACTIVE", "RETIRED")
    assert data.get("current_breach_status") in ("NORMAL", "AMBER_BREACH", "RED_BREACH")
    assert "last_observation_at" in data


def assert_observation(data: dict):
    """Append-only: id + created_at only; NO version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "observation id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "KRIObservation must not expose version"
    assert "updated_at" not in data, "KRIObservation must not expose updated_at"
    assert isinstance(data.get("kri_id"), str) and data["kri_id"]
    assert isinstance(data.get("observed_value"), (int, float))
    assert isinstance(data.get("observed_at"), str)
    assert data.get("resulting_breach_status") in (
        "NORMAL", "AMBER_BREACH", "RED_BREACH",
    )


def assert_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "report id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("period_start"), str)
    assert isinstance(data.get("period_end"), str)
    assert data.get("variant") in ("PROVISIONAL", "FINAL")
    assert data.get("status") in ("DRAFT", "FINALIZED", "CANCELLED")
    assert isinstance(data.get("heat_score_total"), (int, float))
    assert isinstance(data.get("category_breakdown"), list)
    assert isinstance(data.get("band_counts"), dict)


def assert_emerging_risk(data: dict):
    assert is_valid_uuid(data.get("id", "")), "emerging id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("category_id"), str) and data["category_id"]
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("scenario_severity"), int)
    assert 1 <= data["scenario_severity"] <= 5
    assert isinstance(data.get("scenario_probability"), int)
    assert 1 <= data["scenario_probability"] <= 5
    assert isinstance(data.get("stress_factor"), (int, float))
    assert 0.5 <= data["stress_factor"] <= 3.0
    assert isinstance(data.get("scenario_score"), int)
    assert data.get("status") in ("DRAFT", "VALIDATED", "PROMOTED", "DISMISSED")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_risk_budget_invariant(risk: dict):
    """PRD §3.5: available == budget - reserved."""
    assert risk["available_treatment_cents"] == (
        risk["treatment_budget_cents"] - risk["reserved_treatment_cents"]
    ), (
        f"Budget invariant broken: available={risk['available_treatment_cents']} "
        f"budget={risk['treatment_budget_cents']} "
        f"reserved={risk['reserved_treatment_cents']}"
    )
