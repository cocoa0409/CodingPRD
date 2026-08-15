"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. All resources carry the standard four
system-managed fields (id, created_at, updated_at, version).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_provider(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "TERMINATED")


def assert_edit_rule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["edit_code"], str) and data["edit_code"]
    assert data["category"] in ("CLINICAL", "CODING", "POLICY")
    assert data["source"] in ("INTERNAL", "VENDOR")
    assert isinstance(data["active_version_count"], int) and data["active_version_count"] >= 0


def assert_edit_version(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["edit_rule_id"], str)
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert data["severity"] in ("DENY", "SUSPEND", "MONITOR")
    assert isinstance(data["applies_to_claim_types"], list) and data["applies_to_claim_types"]
    assert isinstance(data["logic_expression"], str)
    assert isinstance(data["effective_from"], str)
    assert data["status"] in ("DRAFT", "PENDING_APPROVAL", "ACTIVE", "SUSPENDED", "RETIRED")
    assert isinstance(data["created_by_user_id"], str)
    assert isinstance(data["resolved_hits_count"], int) and data["resolved_hits_count"] >= 0
    assert isinstance(data["fp_hits_count"], int) and data["fp_hits_count"] >= 0
    assert isinstance(data["fp_rate"], (int, float))


def assert_vendor_edit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["vendor_edit_key"], str) and data["vendor_edit_key"]
    assert data["comparison_status"] in ("UNMAPPED", "DUPLICATE", "COMPLEMENTARY")
    assert data["conflict_policy"] == "INTERNAL_FIRST"


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_number"], str) and data["claim_number"]
    assert isinstance(data["provider_id"], str)
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert data["claim_type"] in ("PROFESSIONAL", "INSTITUTIONAL_INPATIENT",
                                  "INSTITUTIONAL_OUTPATIENT")
    assert isinstance(data["total_billed_cents"], int) and data["total_billed_cents"] >= 1
    assert data["status"] in ("RECEIVED", "PENDED", "DETERMINED", "READY_TO_PAY",
                              "DENIED", "PAID")
    for field in ("initial_allowed_cents", "allowed_amount_cents", "denied_amount_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["high_dollar_flag"], bool)
    assert isinstance(data["readmission_flag"], bool)


def assert_claim_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["line_number"], int) and data["line_number"] >= 1
    assert isinstance(data["procedure_code"], str) and data["procedure_code"]
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["billed_cents"], int) and data["billed_cents"] >= 1
    assert isinstance(data["allowed_cents"], int)
    assert isinstance(data["denied_cents"], int)


def assert_edit_hit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["claim_line_id"], str)
    assert isinstance(data["edit_version_id"], str)
    assert data["status"] in ("FIRED", "CONFIRMED", "OVERRIDDEN",
                              "RELEASED_FALSE_POSITIVE", "SUPERSEDED")
    assert isinstance(data["applied"], bool)
    for field in ("expected_savings_cents", "attributed_savings_cents", "released_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_review_task(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["edit_hit_id"], str)
    assert data["status"] in ("PENDING", "IN_REVIEW", "ESCALATED", "DECIDED", "CANCELLED")
    assert isinstance(data["requires_senior"], bool)


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["edit_hit_id"], str)
    assert isinstance(data["provider_id"], str)
    assert isinstance(data["reason"], str)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "AWAITING_PROVIDER_INFO",
                              "DECIDED")
    assert isinstance(data["released_cents"], int)
    assert is_iso8601_timestamp(data.get("submitted_at", ""))


def assert_ibr(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["provider_id"], str)
    assert data["status"] in ("REQUESTED", "DOCUMENTS_RECEIVED", "IN_AUDIT",
                              "COMPLETED", "EXPIRED")
    assert is_iso8601_timestamp(data.get("requested_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))


def assert_inpatient_review(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert data["review_type"] in ("DRG_VALIDATION", "READMISSION")
    assert data["status"] in ("OPEN", "FINDINGS_RECORDED", "DECIDED")
    assert isinstance(data["provider_drg_code"], str)
    assert isinstance(data["payment_delta_cents"], int)


def assert_abrasion_profile(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["provider_id"], str)
    for field in ("confirmed_count", "overridden_count", "fp_count",
                  "superseded_count", "denied_cents_lifetime",
                  "released_cents_lifetime", "open_ibr_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["standard_index"], (int, float))
    assert isinstance(data["regulatory_index"], (int, float))
    assert data["tier"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["monitor_only"], bool)


def assert_savings_period(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period_key"], str)
    assert data["status"] in ("OPEN", "RECONCILING", "FINALIZED")
    for field in ("provisional_savings_cents", "finalized_savings_cents",
                  "pending_pipeline_cents", "reversed_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_claim_ledger_invariant(claim: dict):
    """The PRD claim ledger invariant: allowed + denied == initial_allowed,
    with allowed never driven below zero."""
    assert claim["allowed_amount_cents"] + claim["denied_amount_cents"] == \
        claim["initial_allowed_cents"], (
            f"Claim ledger invariant broken: {claim['allowed_amount_cents']} + "
            f"{claim['denied_amount_cents']} != {claim['initial_allowed_cents']}"
        )
    assert claim["allowed_amount_cents"] >= 0, "allowed_amount_cents below zero"
