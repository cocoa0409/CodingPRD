"""Entity assertions and domain invariant checkers (PRD §2.4, §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_association(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["statutory_response_days"], int) and data["statutory_response_days"] >= 1
    assert data["counting_mode"] in ("CALENDAR", "BUSINESS")
    assert data["fine_mode"] in ("SIMPLE_DAILY", "TIERED_ESCALATION")
    assert isinstance(data["base_fine_cents"], int) and data["base_fine_cents"] >= 0
    assert isinstance(data["daily_fine_cents"], int) and data["daily_fine_cents"] >= 0
    assert isinstance(data["lien_threshold_cents"], int) and data["lien_threshold_cents"] >= 1
    assert isinstance(data["committee_size"], int) and data["committee_size"] >= 1
    assert isinstance(data["quorum_min"], int)
    assert isinstance(data["max_window_days"], int) and data["max_window_days"] >= 1


def assert_owner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert is_valid_uuid(data.get("association_id", ""))


def assert_property(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("association_id", ""))
    assert is_valid_uuid(data.get("primary_owner_id", ""))
    assert isinstance(data["lot_number"], str)
    assert isinstance(data["address"], str)
    assert isinstance(data["outstanding_fine_balance_cents"], int)
    assert data["outstanding_fine_balance_cents"] >= 0
    assert isinstance(data["open_permit_count"], int) and data["open_permit_count"] >= 0
    assert data["compliance_posture"] in ("CLEAR", "FINES_OUTSTANDING", "LIENED")


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("property_id", ""))
    assert is_valid_uuid(data.get("owner_id", ""))
    assert data["project_type"] in ("ADDITION", "FENCE", "PAINT", "ROOF", "SOLAR", "OTHER")
    assert isinstance(data["guideline_section"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["requested_window_start"], str)
    assert isinstance(data["requested_window_end"], str)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED",
        "APPROVED_WITH_CONDITIONS", "DENIED", "DEEMED_APPROVED",
        "UNDER_APPEAL", "APPEAL_DENIED",
    )
    assert data["decision_outcome"] in ("NONE", "APPROVED", "DENIED")
    assert isinstance(data["applicant_hold_days"], int) and data["applicant_hold_days"] >= 0
    assert isinstance(data["conditions"], list)


def assert_attachment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["kind"] in ("DRAWING", "MATERIAL_SAMPLE")
    assert isinstance(data["label"], str)
    assert isinstance(data["uri"], str)


def assert_committee_vote(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["voter_owner_id"], str) and data["voter_owner_id"]
    assert data["ballot"] in ("APPROVE", "DENY", "ABSTAIN")
    assert isinstance(data["recast_count"], int) and data["recast_count"] >= 0


def assert_appeal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["grounds"], str)
    assert data["status"] in ("PENDING", "UPHELD", "OVERRULED")


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["status"] in ("ACTIVE", "COMPLETED", "EXPIRED")


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("permit_id", ""))
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED_REMEDIATION")


def assert_violation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("property_id", ""))
    assert data["kind"] in ("UNAPPROVED_WORK", "CONDITION_BREACH", "INCOMPLETE_CONSTRUCTION")
    assert data["status"] in ("OPEN", "ESCALATED", "REMEDIATED")


def assert_fine(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("violation_id", ""))
    assert data["mode_snapshot"] in ("SIMPLE_DAILY", "TIERED_ESCALATION")
    for field in ("base_cents", "daily_rate_cents", "accrued_cents",
                  "settled_cents", "waived_cents", "outstanding_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["status"] in ("ACCRUING", "STOPPED", "SETTLED")


def assert_lien(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("property_id", ""))
    assert isinstance(data["amount_at_filing_cents"], int)
    assert data["status"] in ("FILED", "SATISFIED")


def assert_variance(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("association_id", ""))
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["guideline_section"], str)
    assert isinstance(data["deviation_description"], str)


def assert_fine_invariant(fine: dict):
    """PRD §2.5: accrued_cents == settled_cents + waived_cents + outstanding_cents."""
    total = fine["settled_cents"] + fine["waived_cents"] + fine["outstanding_cents"]
    assert fine["accrued_cents"] == total, (
        f"fine invariant broken: accrued {fine['accrued_cents']} != "
        f"settled {fine['settled_cents']} + waived {fine['waived_cents']} "
        f"+ outstanding {fine['outstanding_cents']}"
    )


def assert_sweep_report(data: dict):
    """PRD §3.8: the checkpoint reports the five transition counters."""
    for field in ("applications_deemed_approved", "fines_accrued",
                  "violations_escalated", "liens_filed", "permits_expired"):
        assert isinstance(data.get(field), int) and data[field] >= 0, (
            f"sweep report must carry non-negative integer {field}"
        )
