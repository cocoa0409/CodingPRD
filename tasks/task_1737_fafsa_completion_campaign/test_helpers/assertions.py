"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_campaign(data: dict):
    _assert_common_fields(data, "campaign")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["academic_year"], str) and data["academic_year"]
    assert isinstance(data["total_budget_cents"], int)
    assert data["status"] in ["DRAFT", "OPEN", "STATE_GRACE", "CLOSED"]
    assert isinstance(data["committed_budget_cents"], int)
    assert isinstance(data["spent_budget_cents"], int)
    assert isinstance(data["budget_balance_cents"], int)
    for knob in (
        "auto_confirm_threshold",
        "review_floor",
        "min_subgroup_size",
        "max_caseload",
        "no_show_limit",
        "min_recognition_seniors",
    ):
        assert knob in data, f"campaign.{knob} must be present"


def assert_school(data: dict):
    _assert_common_fields(data, "school")
    assert is_valid_uuid(data.get("campaign_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["district_code"], str)
    assert isinstance(data["school_code"], str)
    assert data["status"] in ["INVITED", "ENROLLED", "SUSPENDED"]
    assert data["recognition_tier"] in ["GOLD", "SILVER", "BRONZE", "UNRATED"]


def assert_staff_profile(data: dict):
    _assert_common_fields(data, "staff_profile")
    assert is_valid_uuid(data.get("campaign_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["capabilities"], list)
    assert isinstance(data["languages"], list)
    assert data["background_check_status"] in ["PENDING", "CLEARED", "EXPIRED"]
    assert data["status"] in ["ACTIVE", "OVERLOADED", "SUSPENDED"]
    assert isinstance(data["confirmed_hours_total"], (int, float))
    assert isinstance(data["no_show_count"], int)
    assert isinstance(data["active_case_count"], int)


def assert_senior_record(data: dict):
    """Senior assertions tolerate privacy masking: the aid-status quartet may be
    null on any read when data_visibility is RESTRICTED (PRD §2.6)."""
    _assert_common_fields(data, "senior_record")
    assert is_valid_uuid(data.get("school_id", ""))
    assert isinstance(data["student_ref"], str) and data["student_ref"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["dob"], str) and data["dob"]
    assert isinstance(data["home_language"], str) and data["home_language"]
    assert isinstance(data["subgroup_tags"], list)
    assert data["efc_band"] in ["LOW", "MID", "HIGH"]
    assert data["dependency_status"] in ["DEPENDENT", "INDEPENDENT", "PENDING_REVIEW"]
    assert data["match_status"] in ["UNMATCHED", "SUGGESTED", "MATCHED"]
    assert "fafsa_status" in data
    assert "submitted_at" in data
    assert "deadline_classification" in data
    assert "current_match_link_id" in data
    assert data["data_visibility"] in ["NORMAL", "RESTRICTED"]


def assert_aid_record(data: dict):
    _assert_common_fields(data, "aid_record")
    assert is_valid_uuid(data.get("campaign_id", ""))
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["current_status"] in [
        "STARTED",
        "SUBMITTED",
        "VERIFICATION_SELECTED",
        "COMPLETE",
    ]
    assert isinstance(data["last_effective_date"], str) and data["last_effective_date"]


def assert_aid_status_event(data: dict):
    """Append-only log entry: id + created_at only — updated_at and version
    must be ABSENT (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "event.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "event.created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only event must not expose updated_at"
    assert "version" not in data, "append-only event must not expose version"
    assert is_valid_uuid(data.get("aid_record_id", ""))
    assert data["fafsa_status"] in [
        "STARTED",
        "SUBMITTED",
        "VERIFICATION_SELECTED",
        "COMPLETE",
    ]
    assert isinstance(data["effective_date"], str) and data["effective_date"]


def assert_match_link(data: dict):
    _assert_common_fields(data, "match_link")
    assert is_valid_uuid(data.get("senior_record_id", ""))
    assert is_valid_uuid(data.get("aid_record_id", ""))
    assert isinstance(data["match_score"], (int, float))
    assert 0.0 <= data["match_score"] <= 1.0
    components = data["score_components"]
    for key in ("dob_exact", "name_exact", "school_code_match", "district_match"):
        assert isinstance(components.get(key), bool), f"score_components.{key} boolean"
    assert data["status"] in [
        "SUGGESTED",
        "AUTO_CONFIRMED",
        "CONFIRMED",
        "REJECTED",
        "AUTO_REJECTED",
        "INVALIDATED",
    ]


def assert_consent_record(data: dict):
    _assert_common_fields(data, "consent_record")
    assert is_valid_uuid(data.get("senior_record_id", ""))
    assert isinstance(data["scopes"], list) and len(data["scopes"]) >= 1
    for scope in data["scopes"]:
        assert scope in ["STATUS_DETAIL", "OUTREACH", "DATA_SHARE"]
    assert data["granted_by"] in ["PARENT", "ADULT_STUDENT"]
    assert data["status"] in ["GRANTED", "REVOKED", "EXPIRED"]
    assert "expires_at" in data


def assert_completion_event(data: dict):
    _assert_common_fields(data, "event")
    assert is_valid_uuid(data.get("school_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["cost_estimate_cents"], int)
    assert "actual_cost_cents" in data
    assert isinstance(data["required_expert_count"], int)
    assert isinstance(data["supported_languages"], list)
    assert data["status"] in [
        "DRAFT",
        "PUBLISHED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
    ]


def assert_staff_assignment(data: dict):
    _assert_common_fields(data, "staff_assignment")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("staff_profile_id", ""))
    assert data["assigned_role"] in ["VOLUNTEER", "EXPERT"]
    assert data["status"] in [
        "INVITED",
        "ACCEPTED",
        "CONFIRMED",
        "CHECKED_IN",
        "NO_SHOW",
        "DECLINED",
        "CANCELLED",
    ]
    assert isinstance(data["duration_hours"], (int, float))


def assert_event_registration(data: dict):
    _assert_common_fields(data, "event_registration")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("senior_record_id", ""))
    assert data["status"] in ["REGISTERED", "CANCELLED"]


def assert_document_checklist(data: dict):
    _assert_common_fields(data, "document_checklist")
    assert is_valid_uuid(data.get("senior_record_id", ""))
    assert isinstance(data["language"], str) and data["language"]
    assert data["template_key"] in ["DEPENDENT_STANDARD", "INDEPENDENT_STANDARD"]
    assert data["status"] in ["GENERATED", "IN_PROGRESS", "COMPLETE", "ARCHIVED"]


def assert_checklist_item(data: dict):
    _assert_common_fields(data, "checklist_item")
    assert is_valid_uuid(data.get("checklist_id", ""))
    assert data["doc_type"] in [
        "STUDENT_ID",
        "STUDENT_TAX_RETURN",
        "PARENT_TAX_RETURN",
        "BANK_STATEMENT",
        "DEPENDENCY_OVERRIDE_FORM",
    ]
    assert data["status"] in ["PENDING", "RECEIVED", "VERIFIED", "REJECTED", "WAIVED"]
    assert isinstance(data["waivable"], bool)


def assert_support_case(data: dict):
    _assert_common_fields(data, "support_case")
    assert is_valid_uuid(data.get("senior_record_id", ""))
    assert "assigned_specialist_id" in data
    assert data["case_type"] in ["VERIFICATION_FOLLOWUP", "SPECIAL_CIRCUMSTANCE"]
    assert data["status"] in [
        "OPEN",
        "IN_REVIEW",
        "AWAITING_FAMILY",
        "ESCALATED",
        "PAUSED",
        "RESOLVED",
        "CANCELLED",
    ]
    assert "previous_status" in data
    assert "resolution_outcome" in data
    assert "notes" in data


def assert_completion_report(data: dict):
    _assert_common_fields(data, "completion_report")
    assert is_valid_uuid(data.get("campaign_id", ""))
    assert data["variant"] in ["SUBMISSION_BASED", "PROCESSED_BASED"]
    assert data["status"] in ["GENERATED", "PUBLISHED", "SUPERSEDED"]
    assert isinstance(data["rows"], list)
    assert isinstance(data["eligible_count"], int)
    assert isinstance(data["completed_count"], int)
    assert "overall_rate" in data
    for row in data["rows"]:
        assert row["dimension"] in ["LANGUAGE", "EFC_BAND", "SCHOOL"]
        assert isinstance(row["eligible_count"], int)
        assert isinstance(row["completed_count"], int)
        assert isinstance(row["state_deadline_met_count"], int)
        assert isinstance(row["rate"], (int, float))


# ---------------------------------------------------------------------------
# Domain invariants (PRD §3.1 budget ledger; §3.2 staff counters)
# ---------------------------------------------------------------------------
def assert_budget_invariants(campaign: dict):
    """budget_balance == total - committed - spent (PRD §3.1)."""
    assert (
        campaign["budget_balance_cents"]
        == campaign["total_budget_cents"]
        - campaign["committed_budget_cents"]
        - campaign["spent_budget_cents"]
    ), (
        f"budget ledger broken: balance {campaign['budget_balance_cents']} != "
        f"{campaign['total_budget_cents']} - {campaign['committed_budget_cents']} - "
        f"{campaign['spent_budget_cents']}"
    )


def find_row(report: dict, dimension: str, key: str):
    """Return the report row for (dimension, key), or None if suppressed/absent."""
    for row in report.get("rows", []):
        if row["dimension"] == dimension and row["key"] == key:
            return row
    return None
