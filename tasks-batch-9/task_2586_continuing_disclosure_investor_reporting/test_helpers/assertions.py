"""Entity assertions and domain invariant checkers.

Field names are exactly the PRD's field names.  `ContentRequirement` is checked
without `updated_at` / `version` because the PRD states it carries neither.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------------------- #
# Shared housekeeping properties (PRD §2.4)
# --------------------------------------------------------------------------- #

def assert_common_fields(data: dict, entity_label: str = "resource"):
    """id + created_at + updated_at + version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a bare UUID"
    assert "_" not in str(data.get("id", "")), f"{entity_label}.id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer starting at 1"
    )


def assert_id_and_created_at_only(data: dict, entity_label: str = "resource"):
    """For the immutable ContentRequirement: id + created_at, no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{entity_label} must have no updated_at field"
    assert "version" not in data, f"{entity_label} must have no version field"


# --------------------------------------------------------------------------- #
# Per-entity assertions
# --------------------------------------------------------------------------- #

def assert_bond_issue(data: dict):
    assert_common_fields(data, "BondIssue")
    assert isinstance(data["issuer_program_code"], str) and 1 <= len(data["issuer_program_code"]) <= 32
    assert isinstance(data["series_designation"], str) and 1 <= len(data["series_designation"]) <= 16
    assert data["security_type"] in ("GENERAL_OBLIGATION", "REVENUE", "SPECIAL_ASSESSMENT")
    assert isinstance(data["dated_date"], str)
    assert isinstance(data["final_maturity_date"], str)
    assert data["final_maturity_date"] > data["dated_date"], (
        "final_maturity_date must fall strictly after dated_date"
    )
    assert isinstance(data["original_par_amount_cents"], int) and data["original_par_amount_cents"] >= 1
    assert isinstance(data["outstanding_par_amount_cents"], int)
    assert data["status"] in ("OUTSTANDING", "DEFEASED", "MATURED")
    assert data["current_rating_agency"] in (None, "MOODYS", "SP", "FITCH", "KBRA")
    assert data["defeasance_type"] in (None, "LEGAL", "ECONOMIC")
    assert isinstance(data["escrow_deposit_cents"], int) and data["escrow_deposit_cents"] >= 0
    assert isinstance(data["open_material_event_count"], int) and data["open_material_event_count"] >= 0


def assert_undertaking(data: dict):
    assert_common_fields(data, "Undertaking")
    assert is_valid_uuid(data["issue_id"])
    assert isinstance(data["fiscal_year_end_month_day"], str)
    assert 1 <= data["filing_window_days"] <= 365
    assert data["timeliness_basis"] in ("SUBMISSION_BASIS", "CONFIRMATION_BASIS")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["termination_cause"] in (None, "DEFEASANCE", "MATURITY")
    assert data["compliance_posture"] in ("COMPLIANT", "WATCH", "IMPAIRED", "DELINQUENT")
    assert data["remediation_tier"] in ("TIER_0", "TIER_1", "TIER_2", "TIER_3")
    assert_two_decimals(data["disclosure_risk_score"], "disclosure_risk_score")
    assert 0.0 <= float(data["disclosure_risk_score"]) <= 100.00, (
        "disclosure_risk_score is capped at 100.00"
    )
    for counter in (
        "late_filing_count",
        "missed_event_count",
        "delinquent_cycle_count",
        "open_obligation_count",
        "content_weight_bp_total",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, f"{counter} must be a non-negative integer"


def assert_content_requirement(data: dict):
    assert_id_and_created_at_only(data, "ContentRequirement")
    assert is_valid_uuid(data["undertaking_id"])
    assert data["kind"] in (
        "AUDITED_FINANCIALS",
        "OPERATING_DATA_TABLE",
        "BUDGET_SUMMARY",
        "DEBT_SERVICE_SCHEDULE",
        "ENTERPRISE_STATISTICS",
    )
    assert isinstance(data["label"], str) and 1 <= len(data["label"]) <= 120
    assert isinstance(data["weight_bp"], int) and 1 <= data["weight_bp"] <= 10000
    assert isinstance(data["waivable"], bool)
    assert isinstance(data["requires_audit_opinion"], bool)
    assert data["requires_audit_opinion"] == (data["kind"] == "AUDITED_FINANCIALS"), (
        "requires_audit_opinion is true if and only if kind is AUDITED_FINANCIALS"
    )


def assert_annual_report_cycle(data: dict):
    assert_common_fields(data, "AnnualReportCycle")
    assert is_valid_uuid(data["undertaking_id"])
    assert isinstance(data["fiscal_year_label"], str) and 1 <= len(data["fiscal_year_label"]) <= 16
    assert data["period_end_date"] > data["period_start_date"], (
        "period_end_date must fall strictly after period_start_date"
    )
    assert isinstance(data["due_date"], str) and len(data["due_date"]) == 10
    assert data["status"] in (
        "DRAFTING",
        "READY_TO_FILE",
        "FILING_IN_PROGRESS",
        "FILED_TIMELY",
        "FILED_LATE",
        "DELINQUENT",
        "WITHDRAWN",
        "CLOSED_NOT_REQUIRED",
    )
    assert_two_decimals(data["completeness_score_pct"], "completeness_score_pct")
    assert 0.0 <= float(data["completeness_score_pct"]) <= 100.00
    assert data["timeliness_basis_applied"] in (None, "SUBMISSION_BASIS", "CONFIRMATION_BASIS")
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0


def assert_cycle_content_item(data: dict):
    assert_common_fields(data, "CycleContentItem")
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["content_requirement_id"])
    assert data["status"] in ("NOT_STARTED", "DRAFT", "READY", "WAIVED", "VOID")
    assert isinstance(data["weight_bp_snapshot"], int) and 1 <= data["weight_bp_snapshot"] <= 10000
    assert data["audit_opinion_type"] in (None, "UNMODIFIED", "QUALIFIED", "UNAUDITED_INTERIM")
    assert float(data["readiness_factor"]) in (0.0, 0.5, 1.0), (
        "readiness_factor is 1.0 for READY/WAIVED, 0.5 for DRAFT, 0.0 for NOT_STARTED and VOID"
    )
    assert_readiness_matches_status(data)


def assert_readiness_matches_status(item: dict):
    """PRD §3.3 pins readiness_factor to the item's own status."""
    expected = {
        "READY": 1.0,
        "WAIVED": 1.0,
        "DRAFT": 0.5,
        "NOT_STARTED": 0.0,
        "VOID": 0.0,
    }[item["status"]]
    assert float(item["readiness_factor"]) == expected, (
        f"Expected readiness_factor {expected} for status {item['status']}, "
        f"got {item['readiness_factor']}"
    )


def assert_material_event_notice(data: dict):
    assert_common_fields(data, "MaterialEventNotice")
    assert is_valid_uuid(data["issue_id"])
    assert data["event_type"] in (
        "PRINCIPAL_PAYMENT_DELINQUENCY",
        "RATING_CHANGE",
        "DEFEASANCE",
        "BOND_CALL",
        "UNSCHEDULED_DRAW_ON_RESERVE",
        "TRUSTEE_SUBSTITUTION",
        "FINANCIAL_OBLIGATION_INCURRENCE",
        "MERGER_OR_SALE",
    )
    assert isinstance(data["per_se_material"], bool)
    assert data["per_se_material"] == (
        data["event_type"]
        in ("PRINCIPAL_PAYMENT_DELINQUENCY", "RATING_CHANGE", "DEFEASANCE", "BOND_CALL")
    ), "per_se_material is true if and only if the event type is one of the four per-se events"
    assert isinstance(data["filing_deadline_date"], str) and len(data["filing_deadline_date"]) == 10
    assert data["filing_deadline_date"] > data["occurrence_date"], (
        "the deadline is the tenth business day strictly after the occurrence date"
    )
    assert data["status"] in (
        "DETERMINATION_PENDING",
        "MATERIAL",
        "NOT_MATERIAL",
        "FILING_IN_PROGRESS",
        "FILED_TIMELY",
        "FILED_LATE",
        "MISSED",
        "VOID",
    )
    assert data["rating_agency"] in (None, "MOODYS", "SP", "FITCH", "KBRA")
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0


def assert_filing(data: dict):
    assert_common_fields(data, "Filing")
    assert is_valid_uuid(data["issue_id"])
    assert data["filing_type"] in (
        "ANNUAL_REPORT",
        "MATERIAL_EVENT_NOTICE",
        "FAILURE_TO_FILE_NOTICE",
        "VOLUNTARY_FINANCIAL_OBLIGATION",
    )
    assert data["status"] in ("DRAFT", "SUBMITTED", "CONFIRMED", "REJECTED", "SUPERSEDED")
    assert isinstance(data["submission_attempt_count"], int) and data["submission_attempt_count"] >= 0
    subjects = [data.get("cycle_id"), data.get("material_event_id"), data.get("direct_placement_id")]
    assert sum(1 for s in subjects if s) == 1, "a filing carries exactly one subject"


def assert_failure_to_file_event(data: dict):
    assert_common_fields(data, "FailureToFileEvent")
    assert is_valid_uuid(data["undertaking_id"])
    assert data["kind"] in ("ANNUAL_REPORT_LATE", "ANNUAL_REPORT_MISSED", "MATERIAL_EVENT_MISSED")
    assert isinstance(data["occurred_at"], str)
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0
    assert data["severity"] in ("MINOR", "MAJOR")
    assert data["status"] in ("OPEN", "REMEDIATION_PENDING", "REMEDIATED")
    assert isinstance(data["disclosed_in_official_statement_ids"], list)
    assert_severity_matches_kind_and_days_late(data)


def assert_severity_matches_kind_and_days_late(event: dict):
    """PRD §3.8: MAJOR for both MISSED kinds, or when days_late >= 30; MINOR otherwise."""
    expected = (
        "MAJOR"
        if event["kind"] in ("ANNUAL_REPORT_MISSED", "MATERIAL_EVENT_MISSED")
        or event["days_late"] >= 30
        else "MINOR"
    )
    assert event["severity"] == expected, (
        f"Expected severity {expected} for kind {event['kind']} with days_late "
        f"{event['days_late']}, got {event['severity']}"
    )


def assert_direct_placement(data: dict):
    assert_common_fields(data, "DirectPlacement")
    assert is_valid_uuid(data["issue_id"])
    assert isinstance(data["lender_name"], str) and 1 <= len(data["lender_name"]) <= 120
    assert isinstance(data["principal_amount_cents"], int) and data["principal_amount_cents"] >= 1
    assert data["review_window_end_date"] >= data["review_window_start_date"]
    assert data["disclosure_practice"] in ("MANDATORY_MATERIAL_EVENT", "VOLUNTARY", "NOT_DISCLOSED")
    assert isinstance(data["materiality_ratio_bp"], int)
    assert data["status"] in ("RECEIVED", "DISCLOSURE_REQUIRED", "DISCLOSED", "DISCLOSURE_WAIVED")


def assert_official_statement(data: dict):
    assert_common_fields(data, "OfficialStatement")
    assert is_valid_uuid(data["issue_id"])
    assert isinstance(data["dated_date"], str)
    assert data["lookback_policy"] in ("STRICT_FIVE_YEAR", "REMEDIATED_EXCLUDED")
    assert data["status"] in ("DRAFT", "COMPLIANCE_REVIEW", "POSTED")
    assert isinstance(data["disclosed_event_ids"], list)
    assert isinstance(data["required_disclosure_event_ids"], list)
    assert data["required_disclosure_event_count"] == len(data["required_disclosure_event_ids"]), (
        "required_disclosure_event_count is the length of required_disclosure_event_ids"
    )
    assert data["disclosure_adequacy"] in ("UNKNOWN", "ADEQUATE", "INCOMPLETE")


def assert_dissemination_engagement(data: dict):
    assert_common_fields(data, "DisseminationEngagement")
    assert is_valid_uuid(data["undertaking_id"])
    assert isinstance(data["agent_name"], str) and 1 <= len(data["agent_name"]) <= 120
    assert data["expiration_date"] >= data["effective_date"]
    assert isinstance(data["retainer_cents"], int) and data["retainer_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["monitoring_lapse_days"], int) and data["monitoring_lapse_days"] >= 0
    assert isinstance(data["billable_filing_count"], int) and data["billable_filing_count"] >= 0
    assert isinstance(data["invoice_total_cents"], int) and data["invoice_total_cents"] >= 0
    assert data["termination_reason"] in (
        None,
        "SUPERSEDED",
        "UNDERTAKING_TERMINATED",
        "ISSUER_TERMINATED",
    )


# --------------------------------------------------------------------------- #
# Numeric precision helpers (PRD §2.7)
# --------------------------------------------------------------------------- #

def assert_two_decimals(value, label: str = "value"):
    """A quantity held to 2 decimal places must not carry more precision than that."""
    assert value is not None, f"{label} must not be null"
    quantized = round(float(value) + 1e-12, 2)
    assert abs(float(value) - quantized) < 1e-9, (
        f"{label} must be held to 2 decimal places, got {value}"
    )


def assert_score(actual, expected, label: str = "score"):
    """Compare a 2-decimal score against its literal expected value."""
    assert abs(float(actual) - float(expected)) < 0.005, (
        f"Expected {label} {expected}, got {actual}"
    )


# --------------------------------------------------------------------------- #
# Domain invariants
# --------------------------------------------------------------------------- #

def assert_undertaking_posture_consistent(undertaking: dict):
    """PRD §3.8 step 6: a delinquent cycle dominates the score bands outright."""
    score = float(undertaking["disclosure_risk_score"])
    if undertaking["delinquent_cycle_count"] >= 1:
        expected = "DELINQUENT"
    elif score >= 50.00:
        expected = "IMPAIRED"
    elif score >= 25.00:
        expected = "WATCH"
    else:
        expected = "COMPLIANT"
    assert undertaking["compliance_posture"] == expected, (
        f"Expected compliance_posture {expected} for score {score} and "
        f"delinquent_cycle_count {undertaking['delinquent_cycle_count']}, "
        f"got {undertaking['compliance_posture']}"
    )


def assert_tier_matches_score(undertaking: dict):
    """PRD §3.8 step 4 bands, applied to the score currently persisted on the row."""
    score = float(undertaking["disclosure_risk_score"])
    if score >= 75.00:
        expected = "TIER_3"
    elif score >= 50.00:
        expected = "TIER_2"
    elif score >= 25.00:
        expected = "TIER_1"
    else:
        expected = "TIER_0"
    assert undertaking["remediation_tier"] == expected, (
        f"Expected remediation_tier {expected} for disclosure_risk_score {score}, "
        f"got {undertaking['remediation_tier']}"
    )
