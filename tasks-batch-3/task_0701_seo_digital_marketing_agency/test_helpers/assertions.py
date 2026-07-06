"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version (full common-field entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_append_only_fields(data: dict):
    """id + created_at only; no version/updated_at (append-only entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must not carry a version field"
    assert "updated_at" not in data, \
        "append-only entity must not carry an updated_at field"


def assert_reseller(data: dict):
    assert_common_fields(data)
    assert isinstance(data["brand_name"], str) and len(data["brand_name"]) > 0
    assert 0.0 <= data["markup_pct"] <= 1.0
    assert 0.0 <= data["ppc_management_pct"] <= 0.5
    assert data["status"] == "ACTIVE"


def assert_client(data: dict):
    assert_common_fields(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["primary_domain"], str) and len(data["primary_domain"]) > 0
    assert data["status"] in [
        "PROSPECT", "AUDITED", "ACTIVE", "PAUSED", "CHURNED",
    ]
    assert 0 <= data["health_score"] <= 100
    assert data["open_dispute_count"] >= 0


def assert_site_audit(data: dict):
    assert_append_only_fields(data)
    assert 0 <= data["technical_score"] <= 100
    assert 0 <= data["content_score"] <= 100
    assert 0 <= data["backlink_score"] <= 100
    assert 0 <= data["composite_score"] <= 100


def assert_keyword_target(data: dict):
    assert_common_fields(data)
    assert isinstance(data["phrase"], str) and len(data["phrase"]) > 0
    assert data["search_volume"] >= 0
    assert 0 <= data["difficulty"] <= 100
    assert data["status"] in ["PLANNED", "TRACKING", "DROPPED"]
    assert data["current_rank"] >= 0
    assert data["best_rank"] >= 0


def assert_rank_snapshot(data: dict):
    assert_append_only_fields(data)
    assert 0 <= data["position"] <= 100
    assert data["organic_traffic"] >= 0
    assert is_iso8601_timestamp(data.get("observed_at", ""))


def assert_retainer(data: dict):
    assert_common_fields(data)
    assert data["tier"] in ["STARTER", "GROWTH", "DOMINATE"]
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "CLOSED"]
    assert data["monthly_credits"] >= 0
    assert data["wholesale_price_cents"] >= 0
    assert_credit_ledger_reconciles(data)


def assert_credit_ledger_reconciles(data: dict):
    """PRD §2.9: credits_available == granted - committed - consumed; all whole ints."""
    for field in (
        "credits_granted", "credits_committed", "credits_consumed",
        "credits_available",
    ):
        assert isinstance(data[field], int), f"{field} must be a whole integer"
    expected_available = (
        data["credits_granted"] - data["credits_committed"] - data["credits_consumed"]
    )
    assert data["credits_available"] == expected_available, (
        f"credits_available must equal granted - committed - consumed; "
        f"got {data['credits_available']} != {expected_available}"
    )


def assert_contract(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "PENDING", "SIGNED", "ACTIVE", "RENEWED", "EXPIRED", "TERMINATED",
    ]
    assert data["term_cycles"] >= 1
    assert data["cycles_elapsed"] >= 0
    assert data["early_termination_fee_cents"] >= 0


def assert_sprint(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PLANNING", "ACTIVE", "CLOSED"]
    assert data["capacity_credits"] >= 0
    assert data["committed_credits"] >= 0


def assert_deliverable(data: dict):
    assert_common_fields(data)
    assert data["kind"] in ["CONTENT", "BACKLINK", "TECHNICAL"]
    assert data["complexity"] in ["STANDARD", "COMPLEX"]
    assert data["status"] in [
        "DRAFT", "ASSIGNED", "IN_PROGRESS", "IN_REVIEW",
        "APPROVED", "REJECTED", "CANCELLED",
    ]
    assert data["credit_cost"] >= 0
    assert data["revision_count"] >= 0


def assert_ad_campaign(data: dict):
    assert_common_fields(data)
    assert data["channel"] in ["GOOGLE_ADS", "META", "BING"]
    assert data["lifecycle_status"] in ["DRAFT", "LIVE", "PAUSED", "ENDED"]
    assert data["billing_status"] in ["UNBILLED", "INVOICED", "SETTLED"]
    assert data["budget_cents"] >= 0
    assert data["spent_cents"] >= 0
    assert data["management_fee_cents"] >= 0


def assert_ad_spend_dispute(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "OPEN", "UNDER_REVIEW", "UPHELD", "DENIED", "WITHDRAWN",
    ]
    assert data["disputed_cents"] >= 1
    assert data["credited_cents"] >= 0


def assert_gbp_listing(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["UNVERIFIED", "VERIFIED", "OPTIMIZED", "SUSPENDED"]
    assert 0 <= data["optimization_score"] <= 100


def assert_report(data: dict):
    assert_append_only_fields(data)
    assert data["total_traffic"] >= 0
    assert data["avg_rank"] >= 0.0
