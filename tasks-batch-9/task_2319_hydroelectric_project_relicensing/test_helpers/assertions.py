"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

MONEY = dict(abs=0.01)
MWH = dict(abs=0.05)
PCT = dict(abs=0.01)

PROJECT_STAGES = [
    "PRE_FILING",
    "PAD_FILED",
    "STUDY_PHASE",
    "APPLICATION_FILED",
    "UNDER_ENVIRONMENTAL_REVIEW",
    "LICENSED",
]
TIMELINE_POSTURES = ["ON_TRACK", "AT_RISK", "DELINQUENT"]
REGULATORY_POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
PROJECT_WQC_STATUSES = [
    "NONE",
    "REQUESTED",
    "CERTIFIED_WITH_CONDITIONS",
    "DENIED",
    "WAIVED",
]
RESOURCE_CATEGORIES = ["FISH_PASSAGE", "WATER_QUALITY", "RECREATION", "CULTURAL"]


def _assert_common(data: dict, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if versioned:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be a positive integer, got {data.get('version')!r}"
        )


def assert_relicensing_project(data: dict):
    _assert_common(data)
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert data["installed_capacity_mw"] > 0
    assert data["base_annual_generation_mwh"] > 0
    assert isinstance(data["license_expiration_date"], str)
    assert data["stage"] in PROJECT_STAGES, f"unexpected stage {data['stage']!r}"
    assert data["timeline_posture"] in TIMELINE_POSTURES
    assert data["regulatory_posture"] in REGULATORY_POSTURES
    assert data["wqc_status"] in PROJECT_WQC_STATUSES
    assert isinstance(data["economically_infeasible"], bool)
    assert_project_ledger_precision(data)
    assert data["unresolved_mandatory_comment_count"] >= 0
    assert data["open_deficiency_count"] >= 0
    assert data["compliance_flag_count"] >= 0


def assert_project_ledger_precision(data: dict):
    """Every ledger money field carries two decimals and never goes negative."""
    for field in (
        "total_pme_annual_cost_usd",
        "administrative_annual_charge_usd",
        "total_annual_burden_usd",
    ):
        assert data[field] >= 0, f"{field} must not be negative, got {data[field]}"
        assert_cost_precision(data[field])
    assert data["total_generation_loss_mwh"] >= 0
    assert data["burden_ratio_pct"] >= 0
    assert_cost_precision(data["burden_ratio_pct"])


def assert_dam(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["dam_code"], str) and data["dam_code"]
    assert data["hazard_class"] in ["HIGH", "SIGNIFICANT", "LOW"]
    assert data["inspection_interval_months"] > 0
    assert isinstance(data["eap_exercise_required"], bool)
    assert data["max_concurrent_field_activities"] >= 1


def assert_study_site(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert data["river_mile"] >= 0
    assert data["min_rest_buffer_days"] >= 0
    assert data["cultural_sensitivity"] in ["NONE", "MODERATE", "HIGH"]


def assert_study_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["plan_title"], str) and data["plan_title"]
    assert data["status"] in [
        "DRAFT",
        "UNDER_AGENCY_REVIEW",
        "REVISION_REQUIRED",
        "APPROVED",
        "SUPERSEDED",
    ]
    assert data["revision_round"] >= 0
    assert data["open_comment_count"] >= 0
    assert data["unresolved_mandatory_comment_count"] >= 0
    assert data["attached_study_count"] >= 0
    assert (
        data["unresolved_mandatory_comment_count"] <= data["open_comment_count"]
    ), "mandatory open comments are a subset of the open comments"


def assert_resource_study(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["study_plan_id"])
    assert is_valid_uuid(data["site_id"])
    assert data["resource_category"] in RESOURCE_CATEGORIES
    assert isinstance(data["study_title"], str) and data["study_title"]
    assert data["fieldwork_window_start"] <= data["fieldwork_window_end"]
    assert data["fieldwork_status"] in ["PLANNED", "IN_PROGRESS", "SUSPENDED", "COMPLETED"]
    assert data["review_status"] in [
        "NOT_SUBMITTED",
        "UNDER_REVIEW",
        "ACCEPTED",
        "ADDITIONAL_REQUIRED",
    ]
    assert data["additional_round_count"] >= 0


def assert_consultation_comment(data: dict):
    """A comment is an append-only record: no `updated_at`, no `version`."""
    _assert_common(data, versioned=False)
    assert is_valid_uuid(data["study_plan_id"])
    assert is_valid_uuid(data["party_id"])
    assert data["resource_category"] in RESOURCE_CATEGORIES
    assert isinstance(data["comment_text"], str) and data["comment_text"]
    assert isinstance(data["is_mandatory_condition"], bool)
    assert data["resolution_status"] in ["OPEN", "RESOLVED"]
    assert data["disposition"] in [None, "ADOPTED", "DEFERRED", "REJECTED"]
    assert data["reopen_count"] >= 0
    assert "updated_at" not in data, "an append-only comment carries no updated_at"
    assert "version" not in data, "an append-only comment carries no version"


def assert_settlement_party(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["party_name"], str) and data["party_name"]
    assert data["party_type"] in ["AGENCY", "TRIBE", "NGO"]
    assert isinstance(data["has_conditioning_authority"], bool)
    assert data["vote_weight"] >= 1


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in [
        "NEGOTIATING",
        "CIRCULATED",
        "EXECUTED",
        "FAILED",
        "WITHDRAWN",
        "SUPERSEDED",
    ]
    assert data["round_number"] >= 1
    assert data["included_measure_count"] >= 0


def assert_settlement_signature(data: dict):
    """A signature is an append-only record: no `updated_at`, no `version`."""
    _assert_common(data, versioned=False)
    assert is_valid_uuid(data["settlement_id"])
    assert is_valid_uuid(data["party_id"])
    assert data["round_number"] >= 1
    assert data["position"] in ["SUPPORT", "OPPOSE", "ABSTAIN"]
    assert "updated_at" not in data, "an append-only signature carries no updated_at"
    assert "version" not in data, "an append-only signature carries no version"


def assert_water_quality_certification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["certifying_agency_name"], str)
    assert data["status"] in [
        "REQUESTED",
        "CERTIFIED_WITH_CONDITIONS",
        "DENIED",
        "WAIVED",
    ]
    assert isinstance(data["statutory_waiver_date"], str) and data["statutory_waiver_date"]
    assert data["condition_count"] >= 0


def assert_pme_measure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert data["resource_category"] in RESOURCE_CATEGORIES
    assert data["source"] in [
        "SETTLEMENT",
        "WQC_CONDITION",
        "AGENCY_PRESCRIPTION",
        "LICENSEE_PROPOSED",
    ]
    assert data["status"] in [
        "PROPOSED",
        "INCLUDED",
        "IMPLEMENTED",
        "WITHDRAWN",
        "SUPERSEDED",
    ]
    assert data["cost_estimate_variant"] in ["PRELIMINARY", "DEFINITIVE"]
    for field in (
        "escalated_capital_usd",
        "annualized_capital_usd",
        "annual_cost_usd",
        "annual_generation_value_usd",
        "annual_burden_usd",
    ):
        assert data[field] >= 0, f"{field} must not be negative"
        assert_cost_precision(data[field])
    assert data["annual_generation_loss_mwh"] >= 0


def assert_license_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert data["application_type"] in ["ORIGINAL_RELICENSE", "AMENDMENT"]
    assert data["filing_status"] in [
        "FILED",
        "UNDER_REVIEW",
        "DEFICIENT",
        "SUSPENDED",
        "LICENSED",
        "SUPERSEDED",
    ]
    assert data["ea_stage"] in ["NOT_STARTED", "SCOPING", "DRAFT_EA", "FINAL_EA"]
    assert data["deficiency_count"] >= 0
    assert isinstance(data["pinned_measure_ids"], list)
    assert_cost_precision(data["pinned_total_annual_burden_usd"])


def assert_license_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["order_number"], str) and data["order_number"]
    assert data["compliance_state"] in ["EFFECTIVE", "COMPLIANCE_FLAGGED", "SUPERSEDED"]
    assert isinstance(data["amendment_pending"], bool)
    assert data["article_count"] >= 0
    assert data["open_violation_count"] >= 0
    assert 0 <= data["compliance_score"] <= 100
    assert_cost_precision(data["compliance_score"])
    assert data["last_report_basis"] in [None, "CALENDAR", "LICENSE_ANNIVERSARY"]


def assert_compliance_obligation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert data["obligation_type"] in [
        "PME_IMPLEMENTATION",
        "DAM_SAFETY_INSPECTION",
        "PUBLIC_SAFETY_SIGNAGE",
        "EAP_EXERCISE",
    ]
    assert isinstance(data["due_date"], str) and data["due_date"]
    assert data["status"] in ["PENDING", "SCHEDULED", "OVERDUE", "CERTIFIED", "WAIVED"]
    if data["activity_window_start"] and data["activity_window_end"]:
        assert data["activity_window_start"] <= data["activity_window_end"]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_ledger_matches(
    project: dict,
    total_pme_annual_cost_usd: float,
    total_generation_loss_mwh: float,
    administrative_annual_charge_usd: float,
    total_annual_burden_usd: float,
    burden_ratio_pct: float,
):
    """Assert all five derived burden-ledger figures of a project at once."""
    assert project["total_pme_annual_cost_usd"] == pytest.approx(
        total_pme_annual_cost_usd, **MONEY
    ), f"total_pme_annual_cost_usd was {project['total_pme_annual_cost_usd']}"
    assert project["total_generation_loss_mwh"] == pytest.approx(
        total_generation_loss_mwh, **MWH
    ), f"total_generation_loss_mwh was {project['total_generation_loss_mwh']}"
    assert project["administrative_annual_charge_usd"] == pytest.approx(
        administrative_annual_charge_usd, **MONEY
    ), f"administrative_annual_charge_usd was {project['administrative_annual_charge_usd']}"
    assert project["total_annual_burden_usd"] == pytest.approx(
        total_annual_burden_usd, **MONEY
    ), f"total_annual_burden_usd was {project['total_annual_burden_usd']}"
    assert project["burden_ratio_pct"] == pytest.approx(
        burden_ratio_pct, **PCT
    ), f"burden_ratio_pct was {project['burden_ratio_pct']}"


def assert_measure_costs(
    measure: dict,
    escalated_capital_usd: float = None,
    annualized_capital_usd: float = None,
    annual_cost_usd: float = None,
    annual_generation_loss_mwh: float = None,
    annual_generation_value_usd: float = None,
    annual_burden_usd: float = None,
):
    """Assert whichever of the six derived measure figures the caller pins."""
    if escalated_capital_usd is not None:
        assert measure["escalated_capital_usd"] == pytest.approx(
            escalated_capital_usd, **MONEY
        ), f"escalated_capital_usd was {measure['escalated_capital_usd']}"
    if annualized_capital_usd is not None:
        assert measure["annualized_capital_usd"] == pytest.approx(
            annualized_capital_usd, **MONEY
        ), f"annualized_capital_usd was {measure['annualized_capital_usd']}"
    if annual_cost_usd is not None:
        assert measure["annual_cost_usd"] == pytest.approx(
            annual_cost_usd, **MONEY
        ), f"annual_cost_usd was {measure['annual_cost_usd']}"
    if annual_generation_loss_mwh is not None:
        assert measure["annual_generation_loss_mwh"] == pytest.approx(
            annual_generation_loss_mwh, **MWH
        ), f"annual_generation_loss_mwh was {measure['annual_generation_loss_mwh']}"
    if annual_generation_value_usd is not None:
        assert measure["annual_generation_value_usd"] == pytest.approx(
            annual_generation_value_usd, **MONEY
        ), f"annual_generation_value_usd was {measure['annual_generation_value_usd']}"
    if annual_burden_usd is not None:
        assert measure["annual_burden_usd"] == pytest.approx(
            annual_burden_usd, **MONEY
        ), f"annual_burden_usd was {measure['annual_burden_usd']}"


def assert_plan_counters(
    plan: dict,
    open_comment_count: int,
    unresolved_mandatory_comment_count: int,
    attached_study_count: int = None,
):
    assert plan["open_comment_count"] == open_comment_count, (
        f"open_comment_count was {plan['open_comment_count']}, "
        f"expected {open_comment_count}"
    )
    assert (
        plan["unresolved_mandatory_comment_count"] == unresolved_mandatory_comment_count
    ), (
        "unresolved_mandatory_comment_count was "
        f"{plan['unresolved_mandatory_comment_count']}, "
        f"expected {unresolved_mandatory_comment_count}"
    )
    if attached_study_count is not None:
        assert plan["attached_study_count"] == attached_study_count, (
            f"attached_study_count was {plan['attached_study_count']}, "
            f"expected {attached_study_count}"
        )


def assert_postures(project: dict, timeline_posture: str = None, regulatory_posture: str = None):
    if timeline_posture is not None:
        assert project["timeline_posture"] == timeline_posture, (
            f"timeline_posture was {project['timeline_posture']}, "
            f"expected {timeline_posture}"
        )
    if regulatory_posture is not None:
        assert project["regulatory_posture"] == regulatory_posture, (
            f"regulatory_posture was {project['regulatory_posture']}, "
            f"expected {regulatory_posture}"
        )
