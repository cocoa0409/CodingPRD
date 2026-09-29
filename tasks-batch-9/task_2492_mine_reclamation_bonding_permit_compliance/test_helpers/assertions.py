"""Entity assertions and domain invariant checkers for the bonding API."""
import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

MONEY = 0.01


def assert_common_fields(data: dict):
    """Every stored resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_operator(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    for field in (
        "tangible_net_worth", "fixed_assets_in_state", "total_liabilities",
        "net_income_prior_year", "self_bond_capacity_amount",
        "self_bond_exposure_amount", "outstanding_penalty_balance",
        "refund_due_amount",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert data["elected_financial_test"] in ("NET_WORTH_TEST", "FIXED_ASSET_TEST")
    assert data["registry_status"] in ("ACTIVE", "DISQUALIFIED")
    assert data["self_bond_status"] in ("UNTESTED", "QUALIFIED", "FAILED", "DISQUALIFIED")
    assert isinstance(data["violation_points_total"], int)
    assert isinstance(data["forfeiture_count"], int)


def assert_mine_site(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["county"], str) and data["county"]
    assert data["total_acres"] > 0
    assert data["site_class"] in ("ACTIVE_PERMITTED", "ABANDONED_LEGACY")
    assert data["hazard_class"] in ("H1_EXTREME", "H2_HIGH", "H3_MODERATE")
    assert 0 <= data["public_safety_score"] <= 100
    assert 0 <= data["water_quality_score"] <= 100
    assert data["acres_affected"] >= 0
    assert data["funding_status"] in ("NOT_APPLICABLE", "NOMINATED", "FUNDED")
    assert_cost_precision(data["legacy_priority_score"])


def assert_inspector_profile(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["certification_level"] in ("CERT_I", "CERT_II", "CERT_III")
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["scheduled_inspection_count"], int)
    assert data["scheduled_inspection_count"] >= 0


def assert_permit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["mine_site_id"])
    assert is_valid_uuid(data["operator_id"])
    assert data["mining_plan_acres"] > 0
    assert data["post_mining_land_use"] in (
        "CROPLAND", "FORESTLAND", "RANGELAND", "INDUSTRIAL",
        "WATER_IMPOUNDMENT", "WILDLIFE_HABITAT",
    )
    assert data["status"] in (
        "APPLICATION_SUBMITTED", "ISSUED", "DENIED",
        "RECLAMATION_PHASE", "TERMINATED", "FORFEITED",
    )
    assert data["compliance_posture"] in (
        "COMPLIANT", "NOTICE_ACTIVE", "BOND_DEFICIENT", "CESSATION", "FORFEITURE_PENDING",
    )
    assert data["bond_basis"] in ("FULL_PLAN", "INCREMENTAL")
    assert_permit_ledger_invariants(data)


def assert_permit_ledger_invariants(data: dict):
    """The four-field bond ledger relationship the PRD declares invariant."""
    for field in (
        "bond_required_amount", "bond_held_amount",
        "bond_released_to_date", "bond_deficiency_amount",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
        assert_cost_precision(data[field])
    assert data["bond_deficiency_amount"] >= 0, "deficiency is floored at zero"
    expected_deficiency = max(
        round(data["bond_required_amount"] - data["bond_held_amount"], 2), 0.0
    )
    assert data["bond_deficiency_amount"] == pytest.approx(expected_deficiency, abs=MONEY), (
        f"bond_deficiency_amount {data['bond_deficiency_amount']} should be "
        f"max(required - held, 0) = {expected_deficiency}"
    )
    for field in (
        "disturbed_acres", "reclaimed_acres_credited",
        "phase1_released_acres", "phase2_released_acres", "phase3_released_acres",
    ):
        assert data[field] >= 0, f"{field} must not be negative"


def assert_estimate(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["permit_id"])
    assert isinstance(data["estimator_firm"], str) and data["estimator_firm"]
    assert isinstance(data["estimator_license_no"], str) and data["estimator_license_no"]
    assert data["direct_cost_per_acre"] > 0
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "SUPERSEDED")


def assert_bond_instrument(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["permit_id"])
    assert data["instrument_type"] in ("SURETY", "CASH", "COLLATERAL", "SELF_BOND")
    assert data["face_amount"] > 0
    assert data["status"] in (
        "PROPOSED", "ACCEPTED", "REPLACED", "RELEASED", "FORFEITED", "SUBSTITUTION_REQUIRED",
    )
    assert_cost_precision(data["credited_amount"])
    assert data["credited_amount"] >= 0


def assert_release_application(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["permit_id"])
    assert data["phase"] in ("PHASE_I", "PHASE_II", "PHASE_III")
    assert data["acres_requested"] > 0
    assert data["status"] in (
        "SUBMITTED", "PUBLIC_NOTICE", "SUSPENDED", "APPROVED", "DENIED", "RESCINDED",
    )
    assert_cost_precision(data["requested_amount"])
    assert_cost_precision(data["approved_amount"])
    assert isinstance(data["comment_count"], int) and data["comment_count"] >= 0
    assert isinstance(data["objection_count"], int) and data["objection_count"] >= 0
    assert isinstance(data["objections_resolved"], bool)
    assert data["objection_count"] <= data["comment_count"]


def assert_inspection(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["permit_id"])
    assert is_valid_uuid(data["inspector_id"])
    assert data["inspection_type"] in ("ROUTINE", "RELEASE", "COMPLAINT", "ABATEMENT_FOLLOWUP")
    assert data["duration_hours"] > 0
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert data["result"] in (None, "PASS", "VIOLATIONS_FOUND")


def assert_violation_notice(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["inspection_id"])
    assert is_valid_uuid(data["permit_id"])
    assert data["violation_class"] in ("NON_COMPLIANCE", "IMMINENT_HARM", "PERMIT_DEFECT")
    assert 0 <= data["severity_points"] <= 40
    assert 0 <= data["negligence_points"] <= 30
    assert 0 <= data["duration_points"] <= 25
    assert 0 <= data["history_points"] <= 10
    assert data["abatement_days"] >= 1
    assert data["notice_status"] in ("ISSUED", "CESSATION_ORDERED", "ABATED", "VACATED")
    assert data["penalty_status"] in ("NONE", "ASSESSED", "PAID", "VACATED")
    assert_violation_point_invariants(data)


def assert_violation_point_invariants(data: dict):
    """Point arithmetic is integer arithmetic capped at 100."""
    for field in (
        "severity_points", "negligence_points", "duration_points",
        "history_points", "total_points",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    raw = (
        data["severity_points"] + data["negligence_points"]
        + data["duration_points"] + data["history_points"]
    )
    assert data["total_points"] == min(raw, 100), (
        f"total_points {data['total_points']} should be min({raw}, 100)"
    )


def assert_permit_revision(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["permit_id"])
    assert data["revision_type"] in ("EXPANSION", "SEQUENCE_CHANGE", "PMLU_CHANGE")
    assert data["status"] in ("SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED")
    assert isinstance(data["round_count"], int) and data["round_count"] >= 1


def assert_forfeiture_proceeding(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["permit_id"])
    assert data["initiation_reason"] in (
        "UNABATED_CESSATION", "BOND_DEFICIENCY_UNCURED", "OPERATOR_DISQUALIFIED",
    )
    assert data["status"] in ("INITIATED", "CONTESTED", "FINAL", "COMPLETED")
    for field in (
        "forfeited_bond_amount", "state_reclamation_cost_estimate",
        "actual_cost_incurred", "deficiency_amount", "surplus_amount",
    ):
        assert_cost_precision(data[field])
        assert data[field] >= 0
    assert 0 <= data["completion_pct"] <= 100
    assert data["deficiency_amount"] == 0 or data["surplus_amount"] == 0, (
        "deficiency_amount and surplus_amount are mutually exclusive"
    )


def assert_money(actual, expected, label=""):
    assert actual == pytest.approx(expected, abs=MONEY), (
        f"Expected {label or 'amount'} {expected}, got {actual}"
    )


def assert_envelope_meta(body: dict):
    """The success envelope's request identifier and timestamp."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
