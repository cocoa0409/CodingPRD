"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------------------
# Shared shape helpers
# --------------------------------------------------------------------------
def assert_mutable_resource_shape(data: dict):
    """Every mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_shape(data: dict):
    """Append-only records carry id and created_at but no updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_distributor(data: dict):
    assert_mutable_resource_shape(data)
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 200
    assert data["distributor_type"] in ["CABLE_MSO", "DBS", "TELCO", "VMVPD"]
    assert data["rate_card_class"] in ["CLASS_A", "CLASS_B", "CLASS_C"]
    assert isinstance(data["total_subscribers"], int) and data["total_subscribers"] >= 1
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["receivable_balance_cents"], int)
    assert isinstance(data["audit_recovery_balance_cents"], int)
    assert isinstance(data["executed_agreement_count"], int)
    assert data["status"] in ["ACTIVE", "CREDIT_HOLD", "SUSPENDED", "TERMINATED"]
    assert data["credit_hold_reason"] in [
        "NONE",
        "RECEIVABLE_LIMIT_BREACH",
        "AUDIT_RECOVERY_UNPAID",
        "MANUAL_REVIEW",
    ]


def assert_agreement(data: dict):
    assert_mutable_resource_shape(data)
    assert is_valid_uuid(data["distributor_id"])
    assert isinstance(data["contract_code"], str) and len(data["contract_code"]) > 0
    assert is_iso8601_timestamp(data["term_start_date"])
    assert is_iso8601_timestamp(data["term_end_date"])
    assert data["base_license_fee_cents_per_sub"] > 0
    assert 0 <= data["escalator_pct"] <= 0.15
    assert 0 < data["penetration_floor_pct"] <= 1
    assert data["committed_tier"] in ["BASIC", "EXPANDED_BASIC", "DIGITAL_TIER", "PREMIUM"]
    assert data["lifecycle_status"] in [
        "DRAFT",
        "NEGOTIATING",
        "EXECUTED",
        "SUSPENDED",
        "EXPIRED",
        "TERMINATED",
    ]
    assert data["renewal_status"] in [
        "NOT_DUE",
        "RENEWAL_ANALYSIS",
        "RENEWAL_OFFERED",
        "RENEWED",
        "LAPSED",
    ]
    assert data["penetration_compliance_status"] in ["UNKNOWN", "COMPLIANT", "BREACH"]
    assert data["suspension_reason"] in [
        "NONE",
        "PENETRATION_BREACH",
        "DISTRIBUTOR_CREDIT_HOLD",
        "MANUAL_SUSPENSION",
    ]
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 0
    assert isinstance(data["penetration_breach_count"], int)
    assert isinstance(data["consecutive_compliant_periods"], int)
    assert isinstance(data["recognized_revenue_cents"], int)
    assert isinstance(data["mfn_capped"], bool)


def assert_rate_card_entry(data: dict):
    """A published card row is addressable by id alone (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert "created_at" not in data, "a published rate-card row carries no created_at"
    assert "updated_at" not in data, "a published rate-card row carries no updated_at"
    assert "version" not in data, "a published rate-card row carries no version"
    assert data["rate_card_class"] in ["CLASS_A", "CLASS_B", "CLASS_C"]
    assert data["tier"] in ["BASIC", "EXPANDED_BASIC", "DIGITAL_TIER", "PREMIUM"]
    assert data["published_rate_cents_per_sub"] > 0
    assert isinstance(data["min_subscribers"], int) and data["min_subscribers"] >= 0
    assert is_iso8601_timestamp(data["effective_from"])


def assert_mfn_clause(data: dict):
    assert_mutable_resource_shape(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["mfn_scope"] in ["DOMESTIC", "GLOBAL"]
    assert isinstance(data["min_peer_subscribers"], int) and data["min_peer_subscribers"] >= 0
    assert data["rate_floor_cents"] >= 0
    assert data["benchmark_status"] in ["NOT_EVALUATED", "BENCHMARKED", "NO_COMPARABLE"]
    assert data["status"] in ["ACTIVE", "WAIVED"]


def assert_subscriber_report(data: dict):
    assert_mutable_resource_shape(data)
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert isinstance(data["reported_subscribers"], int) and data["reported_subscribers"] >= 0
    assert data["reported_tier"] in ["BASIC", "EXPANDED_BASIC", "DIGITAL_TIER", "PREMIUM"]
    assert data["status"] in [
        "SUBMITTED",
        "DISPUTED",
        "RESTATED",
        "ACCEPTED",
        "AUDIT_ADJUSTED",
        "SUPERSEDED",
    ]
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["license_fee_due_cents"], int)
    assert isinstance(data["audit_adjustment_cents"], int)
    assert isinstance(data["tier_placement_breach"], bool)


def assert_audit_engagement(data: dict):
    assert_mutable_resource_shape(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["rate_basis"] in ["PERIOD_RATE", "CLOSING_RATE"]
    assert data["status"] in [
        "OPENED",
        "FIELDWORK",
        "FINDINGS_ISSUED",
        "RECOVERY_INVOICED",
        "COLLECTED",
        "CLOSED_NO_FINDING",
    ]
    for field in [
        "total_variance_subscribers",
        "total_reported_subscribers",
        "base_recovery_cents",
        "interest_cents",
        "audit_cost_shift_cents",
        "recovery_amount_cents",
    ]:
        assert isinstance(data[field], int), f"{field} must be an integer of whole cents/subscribers"


def assert_audit_finding(data: dict):
    assert_append_only_shape(data)
    assert is_valid_uuid(data["engagement_id"])
    assert is_valid_uuid(data["subscriber_report_id"])
    assert isinstance(data["audited_subscribers"], int) and data["audited_subscribers"] >= 0
    assert isinstance(data["reported_subscribers"], int)
    assert isinstance(data["variance_subscribers"], int) and data["variance_subscribers"] >= 0


def assert_content_title(data: dict):
    assert_mutable_resource_shape(data)
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 200
    assert len(data["home_territory_code"]) == 2 and data["home_territory_code"].isupper()
    assert is_iso8601_timestamp(data["linear_premiere_at"])
    assert data["rights_status"] in [
        "PENDING_CLEARANCE",
        "OWNED_CLEARED",
        "THIRD_PARTY_LICENSED",
        "EXPIRED_RIGHTS",
    ]
    assert isinstance(data["cleared_window_count"], int) and data["cleared_window_count"] >= 0
    assert data["distribution_coverage_status"] in [
        "UNDISTRIBUTED",
        "LINEAR_ONLY",
        "MULTIPLATFORM",
        "EXCLUSIVE_UNCLEARED",
    ]


def assert_rights_window(data: dict):
    assert_mutable_resource_shape(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["content_title_id"])
    assert data["platform"] in ["LINEAR", "VOD", "STREAMING", "INTERNATIONAL"]
    assert len(data["territory_code"]) == 2 and data["territory_code"].isupper()
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["exclusivity"] in ["EXCLUSIVE", "NON_EXCLUSIVE"]
    assert data["status"] in ["PLANNED", "CLEARED", "ACTIVE", "BLOCKED", "EXPIRED"]
    assert data["block_reason"] in [
        "NONE",
        "AGREEMENT_SUSPENDED",
        "BLACKOUT_CONFLICT",
        "RIGHTS_LAPSED",
        "MANUAL_BLOCK",
    ]
    assert isinstance(data["windowing_holdback_days"], int)
    assert isinstance(data["concurrent_licensee_count"], int)


def assert_blackout_rule(data: dict):
    assert_mutable_resource_shape(data)
    assert is_valid_uuid(data["agreement_id"])
    assert len(data["territory_code"]) == 2 and data["territory_code"].isupper()
    assert is_iso8601_timestamp(data["blackout_start"])
    assert is_iso8601_timestamp(data["blackout_end"])
    assert isinstance(data["substitution_required"], bool)
    assert data["status"] in ["SCHEDULED", "ENFORCED", "WAIVED", "EXPIRED"]
    assert data["blackout_hours"] > 0


def assert_marketing_commitment(data: dict):
    assert_mutable_resource_shape(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["commitment_type"] in ["LAUNCH_FEE", "COOP_ADVERTISING", "MARKETING_SUPPORT"]
    assert isinstance(data["committed_cents"], int) and data["committed_cents"] > 0
    assert is_iso8601_timestamp(data["performance_deadline"])
    assert data["status"] in ["OPEN", "PARTIALLY_EARNED", "EARNED", "FORFEITED", "SETTLED"]
    assert_commitment_ledger_identities(data)


def assert_invoice(data: dict):
    assert_mutable_resource_shape(data)
    assert is_valid_uuid(data["distributor_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert data["invoice_kind"] in ["LICENSE_FEE", "AUDIT_RECOVERY"]
    assert data["status"] in [
        "DRAFT",
        "ISSUED",
        "PARTIALLY_PAID",
        "PAID",
        "WRITTEN_OFF",
        "VOID",
    ]
    for field in [
        "gross_license_fee_cents",
        "coop_offset_cents",
        "launch_fee_offset_cents",
        "recovery_adjustment_cents",
        "net_due_cents",
        "carryforward_cents",
        "paid_cents",
    ]:
        assert isinstance(data[field], int), f"{field} must be an integer of whole cents"
    assert data["net_due_cents"] >= 0, "net_due_cents is floored at zero"
    assert data["carryforward_cents"] >= 0


def assert_renewal_analysis(data: dict):
    assert_append_only_shape(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["variant"] in ["BASE_CASE", "DOWNSIDE"]
    assert 0 <= data["leverage_score"] <= 100
    assert 0 <= data["payment_score"] <= 1
    assert 0 <= data["compliance_score"] <= 1
    assert isinstance(data["distribution_loss_subscribers"], int)
    assert isinstance(data["annualized_revenue_at_risk_cents"], int)


def assert_logical_clock(data: dict):
    assert is_iso8601_timestamp(data["current_utc"])
    assert isinstance(data["set_count"], int) and data["set_count"] >= 0
    assert "version" not in data, "the logical clock is not a versioned resource"


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_commitment_ledger_identities(data: dict):
    """PRD §3.8: committed == earned + remaining + forfeited, and
    earned_unbilled == earned - billed, after every mutation."""
    assert (
        data["committed_cents"]
        == data["earned_cents"] + data["remaining_cents"] + data["forfeited_cents"]
    ), (
        "committed_cents must equal earned + remaining + forfeited, got "
        f"{data['committed_cents']} vs {data['earned_cents']} + {data['remaining_cents']} + "
        f"{data['forfeited_cents']}"
    )
    assert data["earned_unbilled_cents"] == data["earned_cents"] - data["billed_cents"], (
        "earned_unbilled_cents must equal earned_cents less billed_cents, got "
        f"{data['earned_unbilled_cents']} vs {data['earned_cents']} - {data['billed_cents']}"
    )


def assert_rate_precision(value: float, places: int = 4):
    """Rates are carried to four decimal places of a cent (PRD §2.6)."""
    scaled = round(float(value) * (10 ** places))
    assert abs(float(value) * (10 ** places) - scaled) < 1e-6, (
        f"{value} must be expressible at {places} decimal places of a cent"
    )


def assert_whole_cents(value):
    """Monetary amounts are integers of whole cents (PRD §2.6)."""
    assert isinstance(value, int), f"monetary amount must be an integer of whole cents, got {value!r}"


def assert_settlement_summary(data: dict, agreement_id: str):
    assert data["agreement_id"] == agreement_id
    for field in [
        "recognized_revenue_cents",
        "accepted_report_fee_total_cents",
        "invoiced_gross_total_cents",
        "open_receivable_cents",
        "marketing_committed_cents",
        "marketing_earned_cents",
        "marketing_remaining_cents",
        "marketing_forfeited_cents",
    ]:
        assert isinstance(data[field], int), f"{field} must be an integer of whole cents"
    assert isinstance(data["marketing_conserved_identity_holds"], bool)
    assert isinstance(data["revenue_identity_holds"], bool)
