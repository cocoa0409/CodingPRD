"""Entity assertions and domain invariant checkers for the royalty API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

HOLDER_TYPES = ["LABEL", "DISTRIBUTOR", "PUBLISHER", "COLLECTIVE"]
WORK_TYPES = ["RECORDING", "COMPOSITION"]
RIGHTS_STATES = ["UNMATCHED", "PROVISIONAL", "REGISTERED", "DISPUTED"]
PERIOD_STATUSES = ["OPEN", "USAGE_SEALED", "DISTRIBUTED", "CLOSED", "REOPENED"]
BATCH_STATUSES = ["OPEN", "SEALED", "MATCHED", "PARTIALLY_MATCHED", "RECONCILED"]
SUBSCRIPTION_TIERS = ["FREE_AD_SUPPORTED", "INDIVIDUAL", "FAMILY", "STUDENT"]
MATCH_STATUSES = ["UNMATCHED", "AUTO_MATCHED", "CLAIM_MATCHED", "DISPUTED"]
RIGHT_TYPES = ["MASTER", "MECHANICAL", "PERFORMANCE"]
ROUTINGS = ["DIRECT", "COLLECTIVE"]
REGISTRATION_STATUSES = [
    "SUBMITTED",
    "UNDER_REVIEW",
    "NEEDS_EVIDENCE",
    "APPROVED",
    "REJECTED",
    "DISPUTED",
    "SUPERSEDED",
]
DENOMINATOR_BASES = ["ALL_USAGE", "MATCHED_ONLY"]
ALLOCATION_BASES = ["REVENUE_SHARE", "PER_SUBSCRIBER_MINIMUM", "STATUTORY_FLOOR"]
POOL_STATUSES = ["DRAFT", "CALCULATED", "FINALIZED", "REOPENED_FOR_ADJUSTMENT"]
STATEMENT_STATUSES = ["DRAFT", "ISSUED", "SUPERSEDED"]
LINE_TYPES = ["USAGE", "HOLDING_RELEASE", "RESIDUAL", "ADJUSTMENT"]
PRODUCTION_STATUSES = ["PENDING", "PARTIAL", "COMPLETE"]
FINDING_STATUSES = ["NONE", "ASSERTED", "SETTLED", "WITHDRAWN"]
RATE_SCHEDULE_STATUSES = ["PROPOSED", "EFFECTIVE", "SUPERSEDED"]


# ─── Shared shape helpers ─────────────────────────────

def assert_versioned_entity(data: dict) -> None:
    """Every entity except the append-only statement line carries these four."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


# ─── Per-entity assertions ────────────────────────────

def assert_rights_holder(data: dict) -> None:
    assert_versioned_entity(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["holder_type"] in HOLDER_TYPES
    assert isinstance(data["home_territory_code"], str) and data["home_territory_code"]
    rate = data["direct_deal_rate_bps"]
    assert rate is None or (isinstance(rate, int) and 0 <= rate <= 5000)
    assert isinstance(data["receivable_balance_cents"], int)
    assert isinstance(data["issued_statement_count"], int)
    assert data["issued_statement_count"] >= 0


def assert_work(data: dict) -> None:
    assert_versioned_entity(data)
    assert data["work_type"] in WORK_TYPES
    assert isinstance(data["identifier"], str) and data["identifier"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["normalized_title"], str)
    assert data["rights_state"] in RIGHTS_STATES
    assert isinstance(data["approved_master_share_bps"], int)
    assert 0 <= data["approved_master_share_bps"] <= 10000
    if data["work_type"] == "RECORDING":
        assert data["artist_credit"], "a recording carries an artist_credit"
    else:
        assert data["artist_credit"] is None, "a composition carries no artist_credit"


def assert_accounting_period(data: dict) -> None:
    assert_versioned_entity(data)
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["usage_start"], str)
    assert isinstance(data["usage_end"], str)
    assert is_iso8601_timestamp(data["claim_window_closes_at"])
    assert data["status"] in PERIOD_STATUSES
    assert isinstance(data["total_holding_cents"], int)


def assert_usage_batch(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["period_id"])
    assert isinstance(data["source_label"], str) and data["source_label"]
    assert data["status"] in BATCH_STATUSES
    for field in (
        "line_count",
        "total_play_count",
        "matched_play_count",
        "unmatched_play_count",
        "disputed_play_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, field


def assert_usage_line(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["batch_id"])
    assert data["work_id"] is None or is_valid_uuid(data["work_id"])
    assert isinstance(data["reported_title"], str) and data["reported_title"]
    assert isinstance(data["territory_code"], str) and len(data["territory_code"]) == 2
    assert data["subscription_tier"] in SUBSCRIPTION_TIERS
    assert isinstance(data["play_count"], int) and data["play_count"] >= 1
    assert data["match_status"] in MATCH_STATUSES
    assert isinstance(data["match_confidence_bps"], int)
    assert 0 <= data["match_confidence_bps"] <= 10000
    assert isinstance(data["attributed_revenue_cents"], int)


def assert_rights_registration(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["work_id"])
    assert is_valid_uuid(data["claimant_id"])
    assert data["collective_id"] is None or is_valid_uuid(data["collective_id"])
    assert data["right_type"] in RIGHT_TYPES
    assert data["routing"] in ROUTINGS
    assert isinstance(data["share_bps"], int) and 1 <= data["share_bps"] <= 10000
    assert isinstance(data["territory_set"], list) and data["territory_set"]
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert isinstance(data["supersede_overlapping"], bool)
    assert is_valid_uuid(data["payee_holder_id"])
    assert data["status"] in REGISTRATION_STATUSES
    assert isinstance(data["evidence_round"], int) and data["evidence_round"] >= 0
    if data["routing"] == "COLLECTIVE":
        assert data["collective_id"] is not None
        assert data["payee_holder_id"] == data["collective_id"]
    else:
        assert data["collective_id"] is None
        assert data["payee_holder_id"] == data["claimant_id"]


def assert_royalty_pool(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["period_id"])
    assert isinstance(data["territory_code"], str) and len(data["territory_code"]) == 2
    assert data["subscription_tier"] in SUBSCRIPTION_TIERS
    assert isinstance(data["subscriber_count"], int) and data["subscriber_count"] >= 0
    assert isinstance(data["gross_revenue_cents"], int)
    assert data["applied_rate_schedule_id"] is None or is_valid_uuid(
        data["applied_rate_schedule_id"]
    )
    for field in (
        "revenue_share_pool_cents",
        "minimum_pool_cents",
        "statutory_floor_cents",
        "total_play_count",
        "denominator_play_count",
        "distributable_cents",
        "matched_attributed_cents",
        "holding_cents",
        "rounding_residual_cents",
    ):
        assert isinstance(data[field], int), field
    assert data["denominator_basis"] is None or data["denominator_basis"] in DENOMINATOR_BASES
    assert data["allocation_basis"] is None or data["allocation_basis"] in ALLOCATION_BASES
    assert data["residual_payee_holder_id"] is None or is_valid_uuid(
        data["residual_payee_holder_id"]
    )
    assert data["status"] in POOL_STATUSES


def assert_royalty_statement(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["rights_holder_id"])
    assert is_valid_uuid(data["period_id"])
    assert data["status"] in STATEMENT_STATUSES
    for field in ("gross_cents", "admin_fee_cents", "net_payable_cents", "line_count"):
        assert isinstance(data[field], int), field
    if data["status"] == "DRAFT":
        assert data["issued_at"] is None
    else:
        assert is_iso8601_timestamp(data["issued_at"])


def assert_statement_line(data: dict) -> None:
    """A statement line is immutable, so it carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "an immutable line has no updated_at field"
    assert "version" not in data, "an immutable line has no version field"
    assert is_valid_uuid(data["statement_id"])
    assert is_valid_uuid(data["payee_holder_id"])
    assert data["line_type"] in LINE_TYPES
    assert data["right_type"] is None or data["right_type"] in RIGHT_TYPES
    assert data["routing"] is None or data["routing"] in ROUTINGS
    for field in ("play_count", "share_bps", "gross_cents", "admin_fee_cents", "net_cents"):
        assert isinstance(data[field], int), field
    assert data["gross_cents"] - data["admin_fee_cents"] == data["net_cents"], (
        "net_cents must be gross_cents minus admin_fee_cents"
    )


def assert_audit_engagement(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["rights_holder_id"])
    assert is_valid_uuid(data["statement_id"])
    assert isinstance(data["requested_scope_start"], str)
    assert isinstance(data["requested_scope_end"], str)
    assert is_iso8601_timestamp(data["production_deadline_at"])
    assert isinstance(data["required_line_count"], int)
    assert isinstance(data["produced_line_count"], int)
    assert data["produced_line_count"] <= data["required_line_count"]
    assert data["production_status"] in PRODUCTION_STATUSES
    assert data["finding_status"] in FINDING_STATUSES
    for field in ("asserted_underpayment_cents", "settled_amount_cents", "interest_cents"):
        assert isinstance(data[field], int), field


def assert_rate_schedule(data: dict) -> None:
    assert_versioned_entity(data)
    assert isinstance(data["proceeding_ref"], str) and data["proceeding_ref"]
    assert isinstance(data["territory_code"], str)
    assert data["subscription_tier"] in SUBSCRIPTION_TIERS
    for field in (
        "revenue_share_bps",
        "per_subscriber_minimum_cents",
        "mechanical_share_bps",
        "performance_share_bps",
        "statutory_floor_per_play_millicents",
    ):
        assert isinstance(data[field], int), field
    assert data["mechanical_share_bps"] + data["performance_share_bps"] == 10000
    assert isinstance(data["retroactive"], bool)
    assert data["status"] in RATE_SCHEDULE_STATUSES
    if data["status"] == "PROPOSED":
        assert data["promulgated_at"] is None
    else:
        assert is_iso8601_timestamp(data["promulgated_at"])


# ─── Domain invariants (PRD §2.9) ─────────────────────

def assert_pool_value_conservation(pool: dict) -> None:
    """matched_attributed_cents + holding_cents + rounding_residual_cents
    must equal distributable_cents."""
    total = (
        pool["matched_attributed_cents"]
        + pool["holding_cents"]
        + pool["rounding_residual_cents"]
    )
    assert total == pool["distributable_cents"], (
        f"pool value conservation broken: {pool['matched_attributed_cents']} + "
        f"{pool['holding_cents']} + {pool['rounding_residual_cents']} != "
        f"{pool['distributable_cents']}"
    )


def assert_play_count_conservation(batch: dict) -> None:
    """matched + unmatched + disputed play counts must equal total_play_count."""
    total = (
        batch["matched_play_count"]
        + batch["unmatched_play_count"]
        + batch["disputed_play_count"]
    )
    assert total == batch["total_play_count"], (
        f"play count conservation broken: {batch['matched_play_count']} + "
        f"{batch['unmatched_play_count']} + {batch['disputed_play_count']} != "
        f"{batch['total_play_count']}"
    )


def assert_statement_totals(statement: dict, lines: list) -> None:
    """The statement header must aggregate exactly its own lines."""
    assert statement["line_count"] == len(lines)
    assert statement["gross_cents"] == sum(line["gross_cents"] for line in lines)
    assert statement["admin_fee_cents"] == sum(line["admin_fee_cents"] for line in lines)
    assert statement["net_payable_cents"] == sum(line["net_cents"] for line in lines)
