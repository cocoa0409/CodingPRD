"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """All resources share id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_deposit_product(data: dict):
    _assert_common(data)
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["product_class"] in ["SAVINGS", "MONEY_MARKET", "CD", "INTEREST_CHECKING"]
    assert isinstance(data["term_months"], int) and data["term_months"] >= 0
    assert data["tier_application"] in ["MARGINAL", "WHOLE_BALANCE"]
    assert isinstance(data["rate_cap_bp"], int)
    assert isinstance(data["allows_promos"], bool)
    assert isinstance(data["allows_exceptions"], bool)


def assert_rate_sheet(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert isinstance(data["sheet_version"], int) and data["sheet_version"] >= 1
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["disclosure_lead_days"], int)
    assert isinstance(data["margin_floor_bp"], int)
    assert isinstance(data["tiers"], list) and len(data["tiers"]) >= 1
    for row in data["tiers"]:
        assert isinstance(row["tier_index"], int)
        assert isinstance(row["lower_bound_cents"], int)
        assert isinstance(row["upper_bound_cents"], int)
        assert isinstance(row["rate_bp"], int)
        assert isinstance(row["projected_balance_cents"], int)
    assert isinstance(data["total_projected_balance_cents"], int)
    assert data["status"] in ["DRAFT", "COMMITTEE_REVIEW", "APPROVED", "SCHEDULED",
                              "EFFECTIVE", "SUPERSEDED", "RETIRED"]


def assert_competitor_rate_scan(data: dict):
    _assert_common(data)
    assert isinstance(data["market_code"], str)
    assert isinstance(data["scan_date"], str)
    assert isinstance(data["source_name"], str)
    assert isinstance(data["entries"], list)
    assert data["status"] in ["SUBMITTED", "ANALYZED", "ACTIONED"]
    assert data.get("benchmark_weighted_bp") is None or isinstance(data["benchmark_weighted_bp"], int)
    assert data.get("benchmark_simple_bp") is None or isinstance(data["benchmark_simple_bp"], int)


def assert_repricing_cycle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["market_code"], str)
    assert isinstance(data["cadence_days"], int) and data["cadence_days"] > 0
    assert data.get("last_reviewed_at") is None or isinstance(data["last_reviewed_at"], str)
    assert data.get("next_review_due") is None or isinstance(data["next_review_due"], str)
    assert data["status"] in ["CURRENT", "OVERDUE"]


def assert_promotional_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["market_code"], str)
    assert isinstance(data["promo_rate_bp"], int)
    assert isinstance(data["promo_term_days"], int) and data["promo_term_days"] > 0
    assert isinstance(data["enrollment_start"], str)
    assert isinstance(data["enrollment_end"], str)
    assert isinstance(data["min_opening_balance_cents"], int)
    assert data["rollover_treatment"] in ["ROLL_TO_SHEET", "RENEW_THEN_SHEET"]
    assert data["status"] in ["DRAFT", "SCHEDULED", "ACTIVE", "CLOSED", "EXPIRED"]


def assert_exception_pricing_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("sheet_id", ""))
    assert isinstance(data["requested_rate_bp"], int)
    assert isinstance(data["baseline_rate_bp"], int)
    assert isinstance(data["delta_bp"], int)
    assert data["delta_bp"] == data["requested_rate_bp"] - data["baseline_rate_bp"], (
        "delta_bp must equal requested_rate_bp - baseline_rate_bp (PRD §3.6)"
    )
    assert data["authority_tier"] in ["BRANCH", "COMMITTEE"]
    assert isinstance(data["term_days"], int)
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    assert data["status"] in ["UNDER_REVIEW", "RETURNED", "REBASE_REQUIRED", "APPROVED",
                              "APPLIED", "DECLINED", "REVOKED", "EXPIRED"]


def assert_deposit_account(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_ref"], str) and data["customer_ref"]
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("sheet_id", ""))
    assert isinstance(data["balance_cents"], int)
    assert data["channel"] in ["BRANCH", "ONLINE", "MOBILE", "CALL_CENTER"]
    assert data["lifecycle"] in ["OPEN", "FROZEN", "CLOSED"]
    assert data["rate_source"] in ["SHEET", "PROMO", "EXCEPTION", "GRANDFATHERED"]
    assert isinstance(data["base_rate_bp"], int)
    assert isinstance(data["bundle_bonus_bp"], int)
    assert isinstance(data["current_rate_bp"], int)
    assert isinstance(data["unposted_accrual_milli"], int)
    assert isinstance(data["posted_interest_cents"], int)
    assert isinstance(data["last_accrual_date"], str)
    assert isinstance(data["opened_at"], str)


def assert_funding_curve(data: dict):
    _assert_common(data)
    assert isinstance(data["curve_date"], str)
    assert isinstance(data["points"], list) and len(data["points"]) >= 1
    for point in data["points"]:
        assert isinstance(point["tenor_months"], int)
        assert isinstance(point["cost_bp"], int)


def assert_relationship_bundle(data: dict):
    _assert_common(data)
    assert isinstance(data["bundle_code"], str) and data["bundle_code"]
    assert isinstance(data["bonus_bp"], int)
    assert isinstance(data["min_combined_balance_cents"], int)
    assert isinstance(data["required_product_classes"], list)
    assert isinstance(data["eligible_product_classes"], list)


def assert_bundle_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("bundle_id", ""))
    assert isinstance(data["customer_ref"], str)
    assert isinstance(data["qualifying_balance_cents"], int)
    assert data["status"] in ["ENROLLED", "SUSPENDED", "EXITED"]


def assert_disclosure_notice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sheet_id", ""))
    assert data.get("account_id") is None or is_valid_uuid(data["account_id"])
    assert data["channel"] in ["BRANCH", "ONLINE", "MOBILE", "CALL_CENTER"]
    assert data["notice_type"] in ["PRE_CHANGE", "RATE_CHANGE_ADVERSE", "PROMO_EXPIRY"]
    assert isinstance(data["required_by_date"], str)
    assert isinstance(data["is_late"], bool)
    assert data["status"] in ["PENDING", "SENT", "WAIVED"]


def assert_rate_deployment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sheet_id", ""))
    assert data["channel"] in ["BRANCH", "ONLINE", "MOBILE", "CALL_CENTER"]
    assert data["status"] in ["PENDING", "DEPLOYED", "FAILED", "RETIRED"]
    assert data.get("deployed_at") is None or is_iso8601_timestamp(data["deployed_at"])


def assert_migration_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("source_sheet_id", ""))
    assert is_valid_uuid(data.get("target_sheet_id", ""))
    assert isinstance(data["migrated_count"], int)
    assert isinstance(data["skipped_count"], int)
    assert data["status"] in ["PLANNED", "COMPLETED", "ABORTED"]


def assert_rate_quote(data: dict):
    """Rate-quote breakdown shape (PRD §3.5)."""
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["rate_source"] in ["SHEET", "PROMO", "EXCEPTION", "GRANDFATHERED"]
    assert isinstance(data["base_rate_bp"], int)
    assert isinstance(data["bundle_bonus_bp"], int)
    assert data.get("exception_rate_bp") is None or isinstance(data["exception_rate_bp"], int)
    assert isinstance(data["cap_applied"], bool)
    assert isinstance(data["current_rate_bp"], int)
