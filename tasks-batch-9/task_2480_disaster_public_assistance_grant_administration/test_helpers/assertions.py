"""Resource-shape assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_resource_fields(data: dict):
    """Every resource carries an opaque UUID id, ISO-8601 create/update stamps
    and an integer version starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_disaster(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["declaration_number"], str) and data["declaration_number"]
    assert len(data["state_code"]) == 2 and data["state_code"].isupper()
    assert data["incident_type"] in [
        "SEVERE_STORM",
        "FLOOD",
        "WILDFIRE",
        "HURRICANE",
        "EARTHQUAKE",
    ]
    assert data["status"] in ["DECLARED", "OBLIGATION_CLOSED"]
    assert data["population"] >= 1
    assert data["federal_cost_share_pct"] in [0.75, 0.90, 1.00]
    assert data["small_project_threshold_cents"] >= 1
    for field in (
        "total_validated_loss_cents",
        "per_capita_impact_cents",
        "total_obligated_cents",
        "total_drawn_cents",
        "enhanced_monitoring_applicant_count",
        "suspended_applicant_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must never go negative, got {data[field]}"
    assert isinstance(data["indicator_met"], bool)


def assert_applicant(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["applicant_type"] in [
        "LOCAL_GOVERNMENT",
        "TRIBE",
        "STATE_AGENCY",
        "PRIVATE_NONPROFIT",
    ]
    assert data["eligibility_status"] in ["PENDING", "ELIGIBLE", "INELIGIBLE"]
    assert data["monitoring_status"] in ["STANDARD", "ENHANCED"]
    assert data["drawdown_status"] in ["ACTIVE", "SUSPENDED"]
    assert data["audit_requirement"] in ["NONE", "SINGLE_AUDIT"]
    assert data["risk_tier"] in ["LOW", "MEDIUM", "HIGH"]
    assert data["population_served"] >= 0
    assert_applicant_ledger_invariants(data)


def assert_applicant_ledger_invariants(data: dict):
    """The applicant grant ledger identities the PRD defines."""
    assert data["cash_on_hand_cents"] == data["total_drawn_cents"] - data["total_refunded_cents"], (
        "cash_on_hand_cents must equal total_drawn_cents less total_refunded_cents, got "
        f"{data['cash_on_hand_cents']} vs {data['total_drawn_cents']} - {data['total_refunded_cents']}"
    )
    assert (
        data["available_drawdown_cents"]
        == data["total_obligated_cents"] - data["cash_on_hand_cents"]
    ), (
        "available_drawdown_cents must equal total_obligated_cents less cash_on_hand_cents, got "
        f"{data['available_drawdown_cents']}"
    )
    for field in (
        "total_obligated_cents",
        "total_drawn_cents",
        "total_refunded_cents",
        "pending_deobligation_cents",
        "delinquent_report_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must never go negative, got {data[field]}"


def assert_facility(data: dict):
    assert_common_resource_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["facility_type"] in [
        "ROAD_BRIDGE",
        "WATER_CONTROL",
        "BUILDING_EQUIPMENT",
        "UTILITY",
        "PARK_RECREATION",
        "EMERGENCY_PROTECTIVE",
    ]
    assert data["ownership"] in ["PUBLIC", "PNP_OWNED", "LEASED"]
    assert data["eligibility_status"] in ["PENDING", "ELIGIBLE", "INELIGIBLE"]
    for flag in (
        "in_active_use",
        "legal_responsibility_documented",
        "flood_zone",
        "prior_disaster_flood_damage",
    ):
        assert isinstance(data[flag], bool), f"{flag} must be a boolean"


def assert_damage_site(data: dict):
    assert_common_resource_fields(data)
    assert data["category"] in list("ABCDEFG")
    assert data["validation_status"] in ["REPORTED", "VALIDATED", "REJECTED"]
    assert data["reported_loss_cents"] >= 0
    assert data["validated_loss_cents"] >= 0
    assert 0 <= data["work_completed_pct"] <= 100


def assert_project(data: dict):
    assert_common_resource_fields(data)
    assert data["category"] in list("ABCDEFG")
    assert data["status"] in [
        "DRAFT",
        "UNDER_REVIEW",
        "RFI_ISSUED",
        "VALIDATED",
        "OBLIGATED",
        "CLOSEOUT_REQUESTED",
        "CLOSED",
        "DENIED",
    ]
    assert data["size_class"] in [None, "SMALL", "LARGE"]
    assert data["work_type"] in [None, "EMERGENCY", "PERMANENT"]
    assert data["estimated_repair_cost_cents"] >= 0
    assert data["mitigation_requested_cents"] >= 0
    assert data["rfi_round_count"] >= 0
    for field in (
        "repair_eligible_cents",
        "anticipated_insurance_cents",
        "settlement_allocated_cents",
        "insurance_reduction_cents",
        "mitigation_approved_cents",
        "eligible_cost_provisional_cents",
        "federal_share_obligated_cents",
        "deobligated_cents",
        "pending_deobligation_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"
        assert data[field] >= 0, f"{field} must never go negative, got {data[field]}"


def assert_cost_line_item(data: dict):
    assert_common_resource_fields(data)
    assert data["cost_type"] in [
        "FORCE_ACCOUNT_LABOR",
        "FORCE_ACCOUNT_EQUIPMENT",
        "MATERIALS",
        "CONTRACT",
    ]
    assert data["review_status"] in ["SUBMITTED", "ALLOWED", "PARTIALLY_ALLOWED", "DISALLOWED"]
    assert data["claimed_cents"] >= 0
    assert isinstance(data["eligible_cents"], int) and data["eligible_cents"] >= 0
    assert data["eligible_cents"] <= data["claimed_cents"], (
        "eligible_cents can never exceed the claim, got "
        f"{data['eligible_cents']} > {data['claimed_cents']}"
    )


def assert_force_account_resource(data: dict):
    assert_common_resource_fields(data)
    assert data["resource_kind"] in ["LABOR", "EQUIPMENT"]
    assert isinstance(data["label"], str) and data["label"]
    assert data["employee_type"] in [None, "PERMANENT", "TEMPORARY"]
    assert 0 <= data["fringe_benefit_pct"] <= 1
    assert data["charged_hours_total"] >= 0


def assert_contract(data: dict):
    assert_common_resource_fields(data)
    assert data["contract_type"] in [
        "SEALED_BID",
        "COMPETITIVE_PROPOSAL",
        "NONCOMPETITIVE",
        "SMALL_PURCHASE",
        "TIME_AND_MATERIALS",
        "COST_PLUS_PERCENTAGE_OF_COST",
    ]
    assert data["procurement_status"] in ["PENDING_REVIEW", "COMPLIANT", "NONCOMPLIANT"]
    assert data["award_amount_cents"] >= 0
    assert data["allowed_cost_total_cents"] >= 0


def assert_insurance_policy(data: dict):
    assert_common_resource_fields(data)
    assert data["policy_type"] in ["FLOOD", "PROPERTY"]
    assert data["coverage_limit_cents"] >= 0
    assert data["deductible_cents"] >= 0
    assert data["settlement_amount_cents"] >= 0
    assert data["allocated_cents"] + data["unallocated_cents"] == data["settlement_amount_cents"] or (
        data["settlement_amount_cents"] == 0
    ), "allocated plus unallocated proceeds must conserve the settlement amount"


def assert_drawdown(data: dict):
    assert_common_resource_fields(data)
    assert data["status"] in ["REQUESTED", "PAID", "REJECTED", "REFUNDED"]
    assert data["requested_cents"] >= 1
    assert data["approved_cents"] >= 0
    assert data["refunded_cents"] >= 0
    assert data["refunded_cents"] <= max(data["approved_cents"], 0), (
        "refunded_cents can never exceed approved_cents, got "
        f"{data['refunded_cents']} > {data['approved_cents']}"
    )


def assert_progress_report(data: dict):
    assert_common_resource_fields(data)
    assert data["status"] in ["DUE", "SUBMITTED", "LATE", "DELINQUENT"]
    assert is_iso8601_timestamp(data["period_start_at"])
    assert is_iso8601_timestamp(data["period_end_at"])
    assert is_iso8601_timestamp(data["due_at"])
    assert 0 <= data["pct_complete"] <= 100
    assert data["expenditures_to_date_cents"] >= 0


def assert_deobligation(data: dict):
    assert_common_resource_fields(data)
    assert data["status"] in ["PROPOSED", "FINAL", "REVERSED"]
    assert data["reason"] in [
        "CLOSEOUT_UNDERRUN",
        "INSURANCE_DOB",
        "DISALLOWED_COST",
        "PROCUREMENT_NONCOMPLIANCE",
        "SCOPE_REDUCTION",
    ]
    assert data["amount_cents"] >= 1
    assert 0 <= data["reversed_cents"] <= data["amount_cents"]


def assert_appeal(data: dict):
    assert_common_resource_fields(data)
    assert data["level"] in ["FIRST", "SECOND"]
    assert data["status"] in [
        "SUBMITTED",
        "GRANTED",
        "PARTIALLY_GRANTED",
        "DENIED",
        "REMANDED",
    ]
    assert data["relief_requested_cents"] >= 1
    assert 0 <= data["relief_granted_cents"] <= data["relief_requested_cents"]


def assert_error_envelope(response, expected_status: int):
    """The uniform failure envelope: a meta block carrying only api_request_id and
    api_request_timestamp, response_type "error", and a data slot carrying
    error_id and message."""
    assert response.status_code == expected_status, (
        f"Expected HTTP {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == "error", (
        f'response_type must be "error" on failure, got {body.get("response_type")!r}'
    )
    meta = body.get("meta")
    assert isinstance(meta, dict), "meta must be an object"
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith(
        "req_"
    ), f"api_request_id must start with req_, got {meta.get('api_request_id')!r}"
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        f"api_request_timestamp must be ISO 8601, got {meta.get('api_request_timestamp')!r}"
    )
    assert set(meta) == {"api_request_id", "api_request_timestamp"}, (
        f"Error meta must carry only api_request_id and api_request_timestamp, got {sorted(meta)}"
    )
    data = body.get("data")
    assert isinstance(data, dict), "data must be an object on failure"
    assert isinstance(data.get("error_id"), str) and data["error_id"]
    assert isinstance(data.get("message"), str) and data["message"]
    return data


def assert_success_envelope(response, expected_status: int = 200, response_type: str = "object"):
    """The uniform success envelope: a meta block, a response_type of "object" or
    "array", and a populated data slot."""
    assert response.status_code == expected_status, (
        f"Expected HTTP {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == response_type, (
        f"Expected response_type {response_type!r}, got {body.get('response_type')!r}"
    )
    meta = body.get("meta")
    assert isinstance(meta, dict), "meta must be an object"
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith(
        "req_"
    ), f"api_request_id must start with req_, got {meta.get('api_request_id')!r}"
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        f"api_request_timestamp must be ISO 8601, got {meta.get('api_request_timestamp')!r}"
    )
    assert body.get("data") is not None, "data must be populated on success"
    return body["data"]


def assert_pagination_meta(meta: dict, total_count: int, limit: int, offset: int, has_more: bool):
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']}"
    )
