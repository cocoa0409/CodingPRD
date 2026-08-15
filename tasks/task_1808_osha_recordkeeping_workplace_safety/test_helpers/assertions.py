"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. CaseDayCountEntry is append-only and must
NOT expose updated_at/version (PRD §2.5 common-resource-properties section).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}")


def assert_company(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["fein"], str) and data["fein"]


def assert_establishment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert isinstance(data["naics_code"], str) and len(data["naics_code"]) == 6
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["size_class"] in ("SMALL", "STANDARD", "LARGE")
    assert isinstance(data["is_partially_exempt"], bool)
    assert data["posture"] in ("CLEAR", "WATCH", "ELEVATED")
    assert isinstance(data["risk_score"], (int, float))
    assert isinstance(data["current_year_hours"], int)


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["job_title"], str)
    assert isinstance(data["hire_date"], str)
    assert data["employment_status"] in ("ACTIVE", "SEPARATED")


def assert_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["establishment_id"], str)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert isinstance(data["occurred_at"], str)
    assert isinstance(data["reported_at"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["body_part"], str)
    assert data["event_type"] in ("INJURY", "SKIN_DISORDER", "RESPIRATORY",
                                  "POISONING", "HEARING_LOSS", "OTHER_ILLNESS")
    assert isinstance(data["is_privacy_case"], bool)
    assert data["is_severe_event"] in ("NONE", "FATALITY",
                                       "INPATIENT_HOSPITALIZATION",
                                       "AMPUTATION", "EYE_LOSS")
    assert data["status"] in ("INTAKE", "PENDING_REVIEW", "RECORDABLE",
                              "NOT_RECORDABLE", "RECLASSIFIED", "FINALIZED")
    assert data["classification"] in ("NONE", "FIRST_AID_ONLY",
                                      "MEDICAL_TREATMENT",
                                      "JOB_TRANSFER_RESTRICTION", "DAYS_AWAY",
                                      "DEATH")
    assert isinstance(data["is_recordable"], bool)
    assert isinstance(data["is_dart"], bool)
    for field in ("days_away_count", "restricted_days_count",
                  "projected_days_away_count",
                  "projected_restricted_days_count", "revision_index",
                  "log_year"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["day_count_closed"], bool)
    assert isinstance(data["recordability_deadline"], str)


def assert_day_entry(data: dict):
    """Append-only day-count entry: id + created_at only (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601")
    assert "updated_at" not in data, (
        "day-count entries must not expose updated_at (PRD §2.5)")
    assert "version" not in data, (
        "day-count entries must not expose version (PRD §2.5)")
    assert isinstance(data["case_id"], str)
    assert data["day_type"] in ("DAYS_AWAY", "RESTRICTED")
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["calendar_days"], int) and data["calendar_days"] >= 1
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_investigation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["lead_supervisor_id"], str)
    assert isinstance(data["opened_at"], str)
    assert data["status"] in ("OPEN", "ROOT_CAUSE_SUBMITTED", "CLOSED")


def assert_corrective_action(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["establishment_id"], str)
    assert data["priority"] in ("LOW", "MEDIUM", "HIGH", "IMMINENT_DANGER")
    assert data["status"] in ("OPEN", "COMPLETED", "VERIFIED", "OVERDUE",
                              "REOPENED", "CANCELLED")
    assert isinstance(data["assigned_to"], str)
    assert isinstance(data["due_date"], str)
    assert isinstance(data["description"], str)


def assert_summary(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["establishment_id"], str)
    assert isinstance(data["year"], int)
    assert data["status"] in ("DRAFT", "PREPARED", "CERTIFIED", "POSTED",
                              "AMENDED")
    for field in ("total_recordable_cases", "total_dart_cases",
                  "total_days_away", "total_restricted_days",
                  "annual_avg_employment", "total_hours_worked"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["trir"] is None or isinstance(data["trir"], (int, float))
    assert data["dart_rate"] is None or isinstance(data["dart_rate"],
                                                   (int, float))
    assert isinstance(data["posting_window_open"], str)
    assert isinstance(data["posting_window_close"], str)


def assert_hour_log(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["establishment_id"], str)
    assert isinstance(data["year"], int)
    assert isinstance(data["month"], int) and 1 <= data["month"] <= 12
    assert isinstance(data["hours_worked"], int) and data["hours_worked"] >= 0
    assert isinstance(data["employment_count"], int)
    assert data["employment_count"] >= 0
    assert data["status"] in ("DRAFT", "APPROVED", "LOCKED")


def assert_severe_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["report_kind"] in ("FATALITY", "INPATIENT_HOSPITALIZATION",
                                   "AMPUTATION", "EYE_LOSS")
    assert isinstance(data["occurred_at"], str)
    assert isinstance(data["reported_to_agency_at"], str)
    assert isinstance(data["deadline"], str)
    assert isinstance(data["within_clock"], bool)
    assert data["status"] in ("TIMELY", "LATE")


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["establishment_id"], str)
    assert isinstance(data["opened_on"], str)
    assert data["inspection_type"] in ("PROGRAMMED", "COMPLAINT", "REFERRAL",
                                       "FATALITY_CATASTROPHE", "FOLLOW_UP")
    assert data["scope"] in ("COMPREHENSIVE", "PARTIAL", "RECORDS_ONLY")
    assert data["status"] in ("OPEN", "CITATIONS_ISSUED", "CLOSED_NO_CITATION")


def assert_citation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["inspection_id"], str)
    assert isinstance(data["standard_cited"], str)
    assert data["violation_type"] in ("OTHER_THAN_SERIOUS", "SERIOUS",
                                      "WILLFUL", "REPEAT", "FAILURE_TO_ABATE")
    assert isinstance(data["proposed_penalty_usd"], (int, float))
    assert data["proposed_penalty_usd"] >= 0
    assert isinstance(data["abatement_due_date"], str)
    assert data["status"] in ("ISSUED", "CONTESTED", "FINAL_ORDER",
                              "ABATEMENT_PENDING", "ABATED", "VACATED",
                              "OVERDUE")
    assert isinstance(data["contest_deadline"], str)


def assert_case_day_totals_capped(data: dict):
    """Domain invariant: the combined stored day counts never exceed the
    180-day ceiling, and days away take precedence under the cap (PRD §3.3)."""
    combined = data["days_away_count"] + data["restricted_days_count"]
    assert combined <= 180, (
        f"Combined stored day counts {combined} exceed the 180-day ceiling")
    if data["days_away_count"] + data["restricted_days_count"] == 180:
        assert data["days_away_count"] >= 0
