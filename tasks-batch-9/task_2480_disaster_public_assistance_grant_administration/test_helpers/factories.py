"""Payload factories — one per resource, client-supplied fields only."""
from .constants import TEST_DEFAULTS


def disaster_payload(**overrides) -> dict:
    payload = {
        "declaration_number": TEST_DEFAULTS["DECLARATION_NUMBER"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "incident_type": TEST_DEFAULTS["INCIDENT_TYPE"],
        "incident_start_at": TEST_DEFAULTS["INCIDENT_START_AT"],
        "incident_end_at": TEST_DEFAULTS["INCIDENT_END_AT"],
        "population": TEST_DEFAULTS["POPULATION"],
    }
    payload.update(overrides)
    return payload


def applicant_payload(disaster_id: str, **overrides) -> dict:
    payload = {
        "disaster_id": disaster_id,
        "name": TEST_DEFAULTS["APPLICANT_NAME"],
        "applicant_type": TEST_DEFAULTS["APPLICANT_TYPE"],
        "population_served": TEST_DEFAULTS["POPULATION_SERVED"],
    }
    payload.update(overrides)
    return payload


def facility_payload(applicant_id: str, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "name": TEST_DEFAULTS["FACILITY_NAME"],
        "facility_type": TEST_DEFAULTS["FACILITY_TYPE"],
        "ownership": TEST_DEFAULTS["OWNERSHIP"],
    }
    payload.update(overrides)
    return payload


def damage_site_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "category": TEST_DEFAULTS["PROJECT_CATEGORY"],
        "reported_loss_cents": 1_200_000,
        "damage_observed_at": "2026-06-12T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def labor_resource_payload(applicant_id: str, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "resource_kind": "LABOR",
        "label": "Maintenance Crew Lead",
        "employee_type": "PERMANENT",
        "base_hourly_rate_cents": 4_237,
        "fringe_benefit_pct": 0.30,
    }
    payload.update(overrides)
    return payload


def equipment_resource_payload(applicant_id: str, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "resource_kind": "EQUIPMENT",
        "label": "Backhoe Loader",
        "equipment_code": "8010",
        "published_hourly_rate_cents": 6_000,
        "schedule_hourly_rate_cents": 5_500,
    }
    payload.update(overrides)
    return payload


def contract_payload(applicant_id: str, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "vendor_name": "Harbor Civil Works LLC",
        "contract_type": "SEALED_BID",
        "award_amount_cents": 3_000_000,
        "awarded_at": "2026-06-15T00:00:00Z",
        "bids_received": 3,
        "advertised": True,
        "debarment_check_completed": True,
    }
    payload.update(overrides)
    return payload


def insurance_policy_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "insurer_name": "Gulf Mutual Insurance",
        "policy_type": "FLOOD",
        "coverage_limit_cents": 2_000_000,
        "effective_start_at": "2026-01-01T00:00:00Z",
        "effective_end_at": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def project_payload(applicant_id: str, facility_id: str, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "facility_id": facility_id,
        "category": TEST_DEFAULTS["PROJECT_CATEGORY"],
        "title": TEST_DEFAULTS["PROJECT_TITLE"],
        "scope_of_work": TEST_DEFAULTS["SCOPE_OF_WORK"],
        "estimated_repair_cost_cents": TEST_DEFAULTS["ESTIMATED_REPAIR_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def cost_line_item_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "cost_type": "MATERIALS",
        "claimed_cents": 1_000_000,
        "work_start_at": TEST_DEFAULTS["WORK_START_AT"],
        "work_end_at": TEST_DEFAULTS["WORK_END_AT"],
    }
    payload.update(overrides)
    return payload


def drawdown_payload(
    applicant_id: str, project_id: str, requested_cents: int, expected_applicant_version: int
) -> dict:
    return {
        "applicant_id": applicant_id,
        "project_id": project_id,
        "requested_cents": requested_cents,
        "expected_applicant_version": expected_applicant_version,
    }


def progress_report_payload(applicant_id: str, quarter_label: str, **overrides) -> dict:
    payload = {"applicant_id": applicant_id, "quarter_label": quarter_label}
    payload.update(overrides)
    return payload


def deobligation_payload(
    project_id: str, amount_cents: int, expected_project_version: int, reason: str = "SCOPE_REDUCTION"
) -> dict:
    return {
        "project_id": project_id,
        "reason": reason,
        "amount_cents": amount_cents,
        "expected_project_version": expected_project_version,
    }


def appeal_payload(
    deobligation_id: str,
    relief_requested_cents: int,
    grounds: str = "The reduction misreads the documented scope of work.",
    prior_appeal_id: str = None,
) -> dict:
    payload = {
        "deobligation_id": deobligation_id,
        "grounds": grounds,
        "relief_requested_cents": relief_requested_cents,
    }
    if prior_appeal_id is not None:
        payload["prior_appeal_id"] = prior_appeal_id
    return payload
