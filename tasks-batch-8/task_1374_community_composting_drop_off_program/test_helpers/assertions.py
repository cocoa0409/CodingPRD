"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_program(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["name"], str)
    assert isinstance(data["fiscal_year"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["posture_contam_threshold"], int)
    assert isinstance(data["posture_complaint_threshold"], int)
    assert isinstance(data["ops_run_index"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_site(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ONBOARDING", "OPERATIONAL", "DECOMMISSIONED"]
    assert data["posture"] in ["OPEN", "WATCH", "SUSPENDED", "CLOSED"]
    assert isinstance(data["capacity_kg"], int)
    assert isinstance(data["stored_kg"], (int, float))
    assert isinstance(data["pending_pickup_kg"], (int, float))
    assert isinstance(data["archived"], bool)
    assert isinstance(data["version"], int)


def assert_host_agreement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["DRAFT", "ACTIVE", "BREACH_NOTICED",
                              "TERMINATED", "EXPIRED"]
    assert isinstance(data["site_id"], str)
    assert isinstance(data["host_name"], str)
    assert isinstance(data["version"], int)


def assert_material(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["code"], str)
    assert data["contamination_sensitivity"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(data["active"], bool)


def assert_participant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["PENDING_VERIFY", "ACTIVE", "SUSPENDED",
                              "DEACTIVATED"]
    assert isinstance(data["household_size"], int)
    assert isinstance(data["bucket_credit_balance"], int)
    assert isinstance(data["bucket_credits_granted_total"], int)
    assert isinstance(data["bucket_credits_redeemed_total"], int)
    assert isinstance(data["bucket_credits_expired_total"], int)
    assert isinstance(data["suspension_count"], int)


def assert_access_grant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "REVOKED", "EXPIRED"]
    assert isinstance(data["access_code"], str) and len(data["access_code"]) == 8
    assert isinstance(data["bucket_quota"], int)
    assert isinstance(data["buckets_checked_out"], int)


def assert_drop_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["verification_state"] in ["PENDING_AUDIT", "ACCEPTED",
                                          "FLAGGED_CONTAMINATED", "REJECTED"]
    assert data["credit_state"] in ["UNCREDITED", "PROVISIONALLY_CREDITED",
                                    "FINALLY_CREDITED", "REVOKED"]
    assert isinstance(data["gross_weight_kg"], (int, float))
    assert isinstance(data["contamination_kg"], (int, float))
    assert isinstance(data["provisional_net_kg"], (int, float))


def assert_contamination_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "FEEDBACK_SENT", "RESOLVED", "DISMISSED"]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]


def assert_route(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["PLANNED", "DISPATCHED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["assigned_load_kg"], (int, float))
    assert isinstance(data["version"], int)


def assert_partner(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["active"], bool)
    assert isinstance(data["yield_ratio"], (int, float))


def assert_stop(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["SCHEDULED", "COLLECTED", "SKIPPED", "CANCELLED"]
    assert isinstance(data["planned_pickup_kg"], int)


def assert_batch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "CLOSED_ACCEPTED", "CLOSED_REJECTED"]
    assert isinstance(data["input_gross_kg"], (int, float))


def assert_distribution(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "CLOSED", "CANCELLED"]
    assert isinstance(data["total_pool_kg"], (int, float))
    assert isinstance(data["allocated_kg"], (int, float))
    assert isinstance(data["version"], int)


def assert_allocation(data: dict):
    """Append-only entity per PRD §2.4: carries id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["REQUESTED", "DISTRIBUTED", "CANCELLED"]
    assert isinstance(data["requested_kg"], (int, float))
    assert isinstance(data["credits_redeemed"], int)
    assert "version" not in data, "DistributionAllocation carries no version"
    assert "updated_at" not in data, "DistributionAllocation carries no updated_at"


def assert_complaint(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "ACKNOWLEDGED", "RESOLVED", "REOPENED",
                              "CLOSED"]
    assert data["kind"] in ["ODOR", "VECTOR", "OTHER"]
    assert isinstance(data["reopen_count"], int)
    assert isinstance(data["sla_breached"], bool)


def assert_diversion_report(data: dict):
    """Append-only entity per PRD §2.4: carries id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["DRAFT", "CERTIFIED", "SUPERSEDED"]
    assert data["method"] in ["PROVISIONAL_NET", "FINAL_NET"]
    assert isinstance(data["gross_diverted_kg"], (int, float))
    assert isinstance(data["net_diverted_kg"], (int, float))
    assert isinstance(data["contamination_kg"], (int, float))
    assert isinstance(data["diversion_rate_pct"], (int, float))
    assert "version" not in data, "DiversionReport carries no version"
    assert "updated_at" not in data, "DiversionReport carries no updated_at"


def assert_credit_ledger_conserved(participant: dict):
    """PRD §2.8: balance == granted − redeemed − expired at all times."""
    balance = participant["bucket_credit_balance"]
    granted = participant["bucket_credits_granted_total"]
    redeemed = participant["bucket_credits_redeemed_total"]
    expired = participant["bucket_credits_expired_total"]
    assert balance == granted - redeemed - expired, (
        f"Credit ledger not conserved: balance={balance}, "
        f"granted={granted}, redeemed={redeemed}, expired={expired}")
