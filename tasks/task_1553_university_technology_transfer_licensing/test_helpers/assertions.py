"""Entity assertions and domain invariant checkers.

Each assert_* verifies the server-minted common fields (bare-UUID id,
ISO 8601 created_at/updated_at, integer version) plus the entity-specific
fields the PRD enumerates. Optional/nullable fields are checked only when
present so serializers that omit unset optional fields remain compliant.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (trailing Z or +00:00) to an aware
    datetime, so instants compare by value rather than by string form."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_same_instant(actual: str, expected: str):
    assert parse_instant(actual) == parse_instant(expected), \
        f"expected instant {expected}, got {actual}"


def _assert_common(data: dict, what: str):
    assert is_valid_uuid(data.get("id", "")), f"{what}: id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{what}: created_at must be ISO 8601"
    assert "updated_at" in data, f"{what}: updated_at must be present"
    assert isinstance(data.get("version"), int), f"{what}: version must be an integer"


def assert_department(data: dict):
    _assert_common(data, "Department")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["college_name"], str) and data["college_name"]
    assert isinstance(data["distribution_pool_cents"], int)


def assert_inventor(data: dict):
    _assert_common(data, "Inventor")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["department_id"], str)
    assert data["appointment_type"] in ("FACULTY", "STAFF", "STUDENT")


def assert_disclosure(data: dict):
    _assert_common(data, "InventionDisclosure")
    assert isinstance(data["title"], str) and data["title"]
    assert data["funding_source"] in ("FEDERAL", "NON_FEDERAL", "MIXED")
    assert data["status"] in (
        "INVENTORSHIP_REVIEW", "INVENTORSHIP_DISPUTED", "INVENTORSHIP_CONFIRMED",
        "UNDER_ASSESSMENT", "PATENT_PURSUED", "WAIVED_TO_INVENTORS", "SHELVED",
    )
    assert isinstance(data["unreimbursed_cost_cents"], int)
    assert isinstance(data["written_off_cost_cents"], int)
    assert isinstance(data["cost_writeoff_review_required"], bool)
    assert isinstance(data.get("submitter_inventor_id"), str)


def assert_roster_entry(data: dict):
    _assert_common(data, "DisclosureInventor")
    assert isinstance(data["disclosure_id"], str)
    assert isinstance(data["inventor_id"], str)
    assert isinstance(data["share_bp"], int) and 1 <= data["share_bp"] <= 10000
    assert data["confirmation_status"] in ("PENDING", "CONFIRMED", "DISPUTED")


def assert_dispute(data: dict):
    _assert_common(data, "InventorshipDispute")
    assert isinstance(data["disclosure_id"], str)
    assert isinstance(data["entry_id"], str)
    assert isinstance(data["raised_by_inventor_id"], str)
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_patent_application(data: dict):
    _assert_common(data, "PatentApplication")
    assert isinstance(data["disclosure_id"], str)
    assert isinstance(data["docket_number"], str) and data["docket_number"]
    assert data["application_type"] in ("PROVISIONAL", "NON_PROVISIONAL", "PCT")
    assert data["status"] in (
        "FILED", "OFFICE_ACTION_RECEIVED", "RESPONSE_FILED", "GRANTED", "ABANDONED",
    )
    assert isinstance(data["total_cost_cents"], int)
    assert isinstance(data["unreimbursed_cost_cents"], int)


def assert_patent_cost(data: dict):
    _assert_common(data, "PatentCost")
    assert isinstance(data["patent_application_id"], str)
    assert data["cost_type"] in (
        "FILING_FEE", "ATTORNEY_FEE", "MAINTENANCE_FEE", "TRANSLATION_FEE",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["reimbursed_amount_cents"], int)
    assert 0 <= data["reimbursed_amount_cents"] <= data["amount_cents"]
    assert data["reimbursement_status"] in (
        "UNREIMBURSED", "REIMBURSED", "WRITTEN_OFF",
    )


def assert_startup(data: dict):
    _assert_common(data, "Startup")
    assert isinstance(data["disclosure_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert data["equity_model"] in ("FIXED", "ANTI_DILUTION")
    assert isinstance(data["equity_issued"], bool)
    assert data["status"] in ("INCORPORATION", "EQUITY_ISSUED", "DISSOLVED")


def assert_coi_plan(data: dict):
    _assert_common(data, "ConflictOfInterestPlan")
    assert isinstance(data["startup_id"], str)
    assert isinstance(data["inventor_id"], str)
    assert isinstance(data["management_plan_text"], str)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "TERMINATED")


def assert_license(data: dict):
    _assert_common(data, "LicenseAgreement")
    assert isinstance(data["disclosure_id"], str)
    assert isinstance(data["licensee_name"], str) and data["licensee_name"]
    assert data["exclusivity"] in ("EXCLUSIVE", "NON_EXCLUSIVE")
    assert isinstance(data["royalty_rate_bp"], int)
    assert 100 <= data["royalty_rate_bp"] <= 2000
    assert isinstance(data["minimum_annual_royalty_cents"], int)
    assert isinstance(data["upfront_fee_cents"], int)
    assert isinstance(data["cumulative_sales_cents"], int)
    assert isinstance(data["cumulative_royalty_cents"], int)
    assert data["status"] in (
        "IN_NEGOTIATION", "COUNTERED", "EXECUTED", "ACTIVE",
        "DEFAULT_NOTICE", "TERMINATED", "EXPIRED",
    )


def assert_milestone(data: dict):
    _assert_common(data, "LicenseMilestone")
    assert isinstance(data["license_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "ACHIEVED", "WAIVED", "CANCELLED")


def assert_royalty_report(data: dict):
    _assert_common(data, "RoyaltyReport")
    assert isinstance(data["license_id"], str)
    assert isinstance(data["reported_sales_cents"], int)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "PAID", "VOIDED")


def assert_distribution(data: dict):
    _assert_common(data, "RoyaltyDistribution")
    assert isinstance(data["royalty_report_id"], str)
    for field in ("gross_cents", "cost_offset_cents", "net_cents", "admin_fee_cents",
                  "inventor_pool_cents", "department_pool_cents",
                  "university_pool_cents"):
        assert isinstance(data[field], int), f"RoyaltyDistribution: {field} must be int"
    assert isinstance(data["inventor_shares"], list)
    assert isinstance(data["department_shares"], list)
    assert isinstance(data["cost_applications"], list)
    assert isinstance(data["prepared_by_user_id"], str)
    assert data["status"] in ("CALCULATED", "APPROVED", "PAID", "CANCELLED")


def assert_compliance_report(data: dict):
    _assert_common(data, "FederalComplianceReport")
    assert isinstance(data["disclosure_id"], str)
    assert data["report_type"] in (
        "INITIAL_DISCLOSURE", "ELECTION_OF_TITLE",
        "UTILIZATION_REPORT", "EXTENSION_REQUEST",
    )
    assert isinstance(data["prepared_by_user_id"], str)
    assert data["status"] in (
        "DRAFT", "PENDING_CERTIFICATION", "SUBMITTED", "AGENCY_ACCEPTED",
    )


def assert_distribution_conservation(data: dict):
    """Waterfall conservation identity from the PRD: the gross equals the sum of
    the cost offset, admin fee, inventor pool, and department pool, equivalently
    the university, inventor, and department pools."""
    gross = data["gross_cents"]
    assert data["cost_offset_cents"] + data["admin_fee_cents"] \
        + data["inventor_pool_cents"] + data["department_pool_cents"] == gross, \
        "gross must equal cost_offset + admin_fee + inventor_pool + department_pool"
    assert data["university_pool_cents"] + data["inventor_pool_cents"] \
        + data["department_pool_cents"] == gross, \
        "gross must equal university_pool + inventor_pool + department_pool"
    assert data["university_pool_cents"] == \
        data["cost_offset_cents"] + data["admin_fee_cents"], \
        "university_pool must equal cost_offset + admin_fee"


def assert_share_sums(data: dict):
    """The inventor shares and department shares each sum exactly to their pool."""
    assert sum(s["amount_cents"] for s in data["inventor_shares"]) == \
        data["inventor_pool_cents"], "inventor shares must sum to the inventor pool"
    assert sum(s["amount_cents"] for s in data["department_shares"]) == \
        data["department_pool_cents"], \
        "department shares must sum to the department pool"
