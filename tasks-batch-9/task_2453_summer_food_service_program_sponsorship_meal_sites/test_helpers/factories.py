"""Payload factories — one per writable resource, carrying only client-supplied fields."""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS

DEFAULTS = {
    "SPONSOR_LEGAL_NAME": "Riverbend Community Alliance",
    "SECOND_SPONSOR_LEGAL_NAME": "Hilltop Youth Services",
    "AREA_CODE": "CT-0031",
    "SITE_NAME": "Riverbend Park",
    "SECOND_SITE_NAME": "Hilltop Center",
    "MONITOR_USER_ID": "mon_1",
    "SECOND_MONITOR_USER_ID": "mon_2",
}


def create_sponsor_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "legal_name": DEFAULTS["SPONSOR_LEGAL_NAME"],
        "sponsor_type": "NONPROFIT",
        "experience_status": "EXPERIENCED",
        "program_year": TEST_DEFAULTS["PROGRAM_YEAR"],
        "advance_eligible": True,
    }
    payload.update(overrides)
    return payload


def create_area_eligibility_record_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "area_code": DEFAULTS["AREA_CODE"],
        "data_source": "SCHOOL_DATA",
        "free_reduced_pct": 62.50,
        "determination_date": "2026-03-15",
        "valid_through_date": "2031-06-30",
    }
    payload.update(overrides)
    return payload


def create_sponsor_budget_payload(sponsor_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "sponsor_id": sponsor_id,
        "program_year": TEST_DEFAULTS["PROGRAM_YEAR"],
        "operating_cost_budget_cents": TEST_DEFAULTS["OPERATING_COST_BUDGET_CENTS"],
        "admin_cost_budget_cents": TEST_DEFAULTS["ADMIN_COST_BUDGET_CENTS"],
        "projected_total_meals": TEST_DEFAULTS["PROJECTED_TOTAL_MEALS"],
    }
    payload.update(overrides)
    return payload


def budget_decision_payload(decision: str = "APPROVED", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "APPROVED":
        payload["approved_operating_cost_cents"] = TEST_DEFAULTS["APPROVED_OPERATING_COST_CENTS"]
        payload["approved_admin_cost_cents"] = TEST_DEFAULTS["APPROVED_ADMIN_COST_CENTS"]
    payload.update(overrides)
    return payload


def create_advance_payment_payload(sponsor_id: str, expected_sponsor_version: int,
                                   **overrides) -> Dict[str, Any]:
    payload = {
        "sponsor_id": sponsor_id,
        "request_month": "2026-06",
        "requested_amount_cents": 30_000,
        "expected_sponsor_version": expected_sponsor_version,
    }
    payload.update(overrides)
    return payload


def create_site_payload(sponsor_id: str, area_eligibility_record_id: Optional[str] = None,
                        **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sponsor_id": sponsor_id,
        "name": DEFAULTS["SITE_NAME"],
        "site_type": "OPEN",
        "production_mode": "SELF_PREP",
        "approved_meal_types": ["LUNCH"],
        "approved_max_attendance": TEST_DEFAULTS["APPROVED_MAX_ATTENDANCE"],
        "operating_start_date": TEST_DEFAULTS["SEASON_START_DATE"],
        "operating_end_date": TEST_DEFAULTS["SEASON_END_DATE"],
        "is_open_air": False,
        "is_rural": True,
    }
    if area_eligibility_record_id is not None:
        payload["area_eligibility_record_id"] = area_eligibility_record_id
    payload.update(overrides)
    return payload


def meal_service(meal_type: str = "LUNCH", planned_meals: int = 150,
                 service_start: str = "11:30", service_end: str = "12:30") -> Dict[str, Any]:
    return {
        "meal_type": meal_type,
        "planned_meals": planned_meals,
        "service_start": service_start,
        "service_end": service_end,
    }


def create_meal_service_day_payload(site_id: str, service_date: str = "2026-06-08",
                                    meal_services: Optional[List[Dict[str, Any]]] = None,
                                    **overrides) -> Dict[str, Any]:
    payload = {
        "site_id": site_id,
        "service_date": service_date,
        "meal_services": meal_services if meal_services is not None else [meal_service()],
    }
    payload.update(overrides)
    return payload


def open_day_payload(production_counts: Optional[Dict[str, int]] = None,
                     food_received_at: str = "2026-06-08T10:30:00Z",
                     **overrides) -> Dict[str, Any]:
    payload = {
        "production_counts": production_counts if production_counts is not None
        else {"LUNCH": TEST_DEFAULTS["PLANNED_MEALS"]},
        "food_received_at": food_received_at,
    }
    payload.update(overrides)
    return payload


def create_meal_count_payload(meal_type: str = "LUNCH", first_meals: int = 47,
                              second_meals: int = 0, adult_meals: int = 0,
                              **overrides) -> Dict[str, Any]:
    payload = {
        "meal_type": meal_type,
        "first_meals": first_meals,
        "second_meals": second_meals,
        "adult_meals": adult_meals,
    }
    payload.update(overrides)
    return payload


def create_holding_log_payload(meal_type: str = "LUNCH", temperature_class: str = "HOT",
                               temperature_f: float = 140.0,
                               measured_at: str = "2026-06-08T11:45:00Z",
                               **overrides) -> Dict[str, Any]:
    payload = {
        "meal_type": meal_type,
        "temperature_class": temperature_class,
        "temperature_f": temperature_f,
        "measured_at": measured_at,
    }
    payload.update(overrides)
    return payload


def create_monitoring_visit_payload(site_id: str, monitor_user_id: Optional[str] = None,
                                    visit_type: str = "FIRST_WEEK",
                                    scheduled_date: str = "2026-06-10",
                                    window_start: str = "09:00",
                                    window_end: str = "11:00", **overrides) -> Dict[str, Any]:
    payload = {
        "site_id": site_id,
        "monitor_user_id": monitor_user_id or DEFAULTS["MONITOR_USER_ID"],
        "visit_type": visit_type,
        "scheduled_date": scheduled_date,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def visit_report_payload(findings: Optional[List[Dict[str, Any]]] = None,
                         **overrides) -> Dict[str, Any]:
    payload = {"findings": findings if findings is not None else []}
    payload.update(overrides)
    return payload


def finding(finding_code: str = "MEALS_SERVED_OFFSITE", severity: str = "CRITICAL",
            **overrides) -> Dict[str, Any]:
    payload = {"finding_code": finding_code, "severity": severity}
    payload.update(overrides)
    return payload


def create_meal_claim_payload(sponsor_id: str, expected_sponsor_version: int,
                              claim_month: str = "2026-06", **overrides) -> Dict[str, Any]:
    payload = {
        "sponsor_id": sponsor_id,
        "claim_month": claim_month,
        "expected_sponsor_version": expected_sponsor_version,
    }
    payload.update(overrides)
    return payload


def submit_claim_payload(claimed_operating_cost_cents: int = 20_000,
                         claimed_admin_cost_cents: int = 1_000, **overrides) -> Dict[str, Any]:
    payload = {
        "claimed_operating_cost_cents": claimed_operating_cost_cents,
        "claimed_admin_cost_cents": claimed_admin_cost_cents,
    }
    payload.update(overrides)
    return payload
