"""Entity shape assertions and domain invariant checkers."""

from typing import Any, Dict, Iterable, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ---------------------------------------------------------------------------
# Common envelope fields
# ---------------------------------------------------------------------------


def assert_common_fields(record: Dict[str, Any]) -> None:
    """Every resource carries a server-minted UUID `id` with no type prefix, a
    `created_at`, an `updated_at` that starts equal to it and an integer `version`
    that starts at 1."""
    assert is_valid_uuid(record["id"]), f"id is not a bare UUID: {record.get('id')!r}"
    assert is_iso8601_timestamp(record["created_at"]), record.get("created_at")
    assert is_iso8601_timestamp(record["updated_at"]), record.get("updated_at")
    assert isinstance(record["version"], int) and record["version"] >= 1, record.get("version")


def assert_immutable_record_fields(record: Dict[str, Any]) -> None:
    """The two immutable record types expose neither `updated_at` nor `version`."""
    assert is_valid_uuid(record["id"]), f"id is not a bare UUID: {record.get('id')!r}"
    assert is_iso8601_timestamp(record["created_at"]), record.get("created_at")
    assert "updated_at" not in record, "immutable record must not expose updated_at"
    assert "version" not in record, "immutable record must not expose version"


def assert_fields_absent(record: Dict[str, Any], field_names: Iterable[str]) -> None:
    """A body field the server neither accepts nor manages is never echoed back."""
    for name in field_names:
        assert name not in record, f"field {name!r} must not be echoed back"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------


def assert_product_category(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert isinstance(record["category_code"], str)
    assert isinstance(record["display_name"], str)
    assert isinstance(record["base_royalty_rate_bps"], int)
    assert isinstance(record["tier_schedule"], list) and record["tier_schedule"]
    for band in record["tier_schedule"]:
        assert isinstance(band["from_cents"], int)
        assert band["to_cents"] is None or isinstance(band["to_cents"], int)
        assert isinstance(band["rate_bps"], int)
    assert isinstance(record["closeout_rate_bps"], int)
    assert isinstance(record["closeout_cap_pct_bps"], int)
    assert isinstance(record["closeout_hard_limit_bps"], int)
    assert isinstance(record["deduction_cap_pct_bps"], int)
    assert isinstance(record["deduction_hard_limit_bps"], int)
    assert isinstance(record["exclusivity_allowed"], bool)
    assert isinstance(record["minimum_guarantee_floor_cents"], int)
    assert isinstance(record["advance_floor_bps_of_mg"], int)
    assert record["mark_usage_class"] in (
        "LEAGUE_ONLY",
        "LEAGUE_AND_CLUB",
        "LEAGUE_CLUB_AND_PLAYER",
    )
    assert isinstance(record["central_licensing_default"], bool)


def assert_club(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert isinstance(record["club_code"], str) and len(record["club_code"]) == 3
    assert record["club_code"].isupper()
    assert isinstance(record["market_name"], str)
    assert 1 <= record["revenue_share_units"] <= 100
    assert record["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(record["lifetime_distributed_cents"], int)


def assert_player(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["club_id"])
    assert isinstance(record["full_name"], str)
    assert isinstance(record["group_licensing_opt_in"], bool)
    assert isinstance(record["individual_grant_category_ids"], list)
    assert record["status"] in ("ACTIVE", "RETIRED")


def assert_mark_right(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert isinstance(record["mark_code"], str)
    assert record["owner_type"] in ("LEAGUE", "CLUB", "PLAYER_GROUP", "PLAYER_INDIVIDUAL")
    assert record["usage_class"] in ("PRIMARY", "SECONDARY", "HERITAGE")
    assert isinstance(record["royalty_share_bps"], int)
    assert record["status"] in ("ACTIVE", "RESTRICTED", "WITHDRAWN")


def assert_licensee(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert isinstance(record["legal_name"], str)
    assert isinstance(record["contact_email"], str)
    assert isinstance(record["home_country_code"], str)
    assert isinstance(record["vendor_compliance_certified"], bool)
    assert record["status"] in ("PROSPECT", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(record["compliance_risk_index"], int)
    assert isinstance(record["outstanding_recovery_cents"], int)
    assert isinstance(record["agreement_count"], int)


def assert_agreement(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["licensee_id"])
    assert is_valid_uuid(record["category_id"])
    assert record["exclusivity_mode"] in ("EXCLUSIVE", "NON_EXCLUSIVE")
    assert isinstance(record["minimum_guarantee_cents"], int)
    assert isinstance(record["required_advance_cents"], int)
    assert record["contract_status"] in (
        "DRAFT",
        "PENDING_SIGNATURE",
        "ACTIVE",
        "SUSPENDED",
        "EXPIRED",
        "TERMINATED",
    )
    assert record["compliance_posture"] in ("CLEAR", "WATCH", "PROBATION", "FROZEN")
    assert isinstance(record["central_licensing_flag"], bool)
    for field in (
        "advance_paid_cents",
        "unrecouped_advance_cents",
        "recouped_advance_cents",
        "cumulative_royalty_cents",
        "mg_accrued_shortfall_cents",
        "approved_sku_count",
        "authorized_channel_count",
    ):
        assert isinstance(record[field], int), field
    assert isinstance(record["distribution_ready"], bool)


def assert_territory_grant(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["agreement_id"])
    assert isinstance(record["territory_code"], str)
    assert record["channel_class"] in (
        "DEPARTMENT",
        "SPECIALTY",
        "MASS",
        "ECOMMERCE",
        "OFF_PRICE",
        "ALL",
    )
    assert record["status"] in ("GRANTED", "REVOKED")
    assert record["exclusivity_mode_snapshot"] in ("EXCLUSIVE", "NON_EXCLUSIVE")


def assert_product_submission(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["agreement_id"])
    assert isinstance(record["product_name"], str)
    assert isinstance(record["mark_ids"], list)
    assert isinstance(record["retail_price_cents"], int)
    assert isinstance(record["sample_required"], bool)
    assert record["status"] in (
        "DRAFT",
        "SUBMITTED",
        "IN_REVIEW",
        "REVISION_REQUESTED",
        "SAMPLE_REQUESTED",
        "SAMPLE_PASSED",
        "APPROVED",
        "REJECTED",
        "REVOKED",
    )
    assert isinstance(record["revision_round"], int)
    assert isinstance(record["review_hold"], bool)
    assert isinstance(record["defect_codes"], list)
    assert isinstance(record["approved_mark_snapshot"], list)
    assert isinstance(record["mark_snapshot_stale"], bool)


def assert_sample_review(record: Dict[str, Any]) -> None:
    """A sample review is immutable evidence of one physical inspection."""
    assert_immutable_record_fields(record)
    assert is_valid_uuid(record["submission_id"])
    assert record["verdict"] in ("PASS", "CONDITIONAL_PASS", "FAIL")
    assert isinstance(record["defect_codes"], list)
    assert isinstance(record["sample_round"], int)
    assert isinstance(record["reviewer_user_id"], str) and record["reviewer_user_id"]
    assert_quarter_label(record["occurrence_quarter"])


def assert_retailer_authorization(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["licensee_id"])
    assert isinstance(record["retailer_name"], str)
    assert record["channel_class"] in (
        "DEPARTMENT",
        "SPECIALTY",
        "MASS",
        "ECOMMERCE",
        "OFF_PRICE",
        "ALL",
    )
    assert isinstance(record["sku_classes"], list)
    assert isinstance(record["closeout_allowed"], bool)
    assert record["status"] in ("PENDING", "AUTHORIZED", "SUSPENDED", "REVOKED")


def assert_royalty_report(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["agreement_id"])
    assert_quarter_label(record["period_quarter"])
    assert isinstance(record["channel_lines"], list) and record["channel_lines"]
    assert record["status"] in (
        "DRAFT",
        "FILED",
        "RETURNED",
        "ACCEPTED",
        "UNDER_AUDIT",
        "ADJUSTED",
        "CLOSED",
    )
    for field in (
        "net_regular_total_cents",
        "closeout_eligible_total_cents",
        "applied_tier_rate_bps",
        "royalty_due_cents",
        "recoupment_applied_cents",
        "cash_due_pre_fee_cents",
        "late_days",
        "late_filing_interest_cents",
        "admin_fee_cents",
        "total_payable_cents",
        "return_count",
    ):
        assert isinstance(record[field], int), field


def assert_audit_engagement(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["agreement_id"])
    assert isinstance(record["scope_quarters"], list) and record["scope_quarters"]
    for label in record["scope_quarters"]:
        assert_quarter_label(label)
    assert record["status"] in (
        "OPENED",
        "FIELDWORK",
        "FINDINGS_ISSUED",
        "DISPUTED",
        "SETTLED",
        "CLOSED",
    )
    assert isinstance(record["opened_by_user_id"], str) and record["opened_by_user_id"]
    assert_quarter_label(record["opened_quarter"])
    for field in (
        "recomputed_royalty_cents",
        "reported_royalty_cents",
        "underreported_royalty_cents",
        "underreport_rate_bps",
        "interest_cents",
        "audit_cost_recovery_cents",
        "recovery_assessed_cents",
        "findings_round",
    ):
        assert isinstance(record[field], int), field
    assert isinstance(record["cost_shift_applied"], bool)


def assert_enforcement_action(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert record["venue_type"] in ("EVENT", "ONLINE")
    assert isinstance(record["venue_reference"], str)
    assert isinstance(record["target_name"], str)
    assert isinstance(record["estimated_units"], int)
    assert isinstance(record["estimated_retail_cents"], int)
    assert record["status"] in (
        "REPORTED",
        "INVESTIGATING",
        "SEIZURE_ORDERED",
        "RESOLVED",
        "DISMISSED",
    )
    assert isinstance(record["seized_units"], int)
    assert isinstance(record["recovered_cents"], int)


def assert_distribution_run(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert_quarter_label(record["period_quarter"])
    assert isinstance(record["league_admin_rate_bps"], int)
    assert record["status"] in ("OPEN", "LOCKED", "DISTRIBUTED")
    for field in (
        "projected_pool_cents",
        "pool_gross_cents",
        "league_admin_cents",
        "player_pool_cents",
        "club_pool_cents",
        "report_count",
    ):
        assert isinstance(record[field], int), field


def assert_club_distribution(record: Dict[str, Any]) -> None:
    """A club distribution is immutable evidence of one club's allocation."""
    assert_immutable_record_fields(record)
    assert is_valid_uuid(record["run_id"])
    assert is_valid_uuid(record["club_id"])
    assert isinstance(record["club_code"], str)
    for field in (
        "revenue_share_units_snapshot",
        "equal_component_cents",
        "weighted_component_cents",
        "remainder_cent_applied",
        "amount_cents",
    ):
        assert isinstance(record[field], int), field


def assert_risk_index_projection(record: Dict[str, Any]) -> None:
    """The read-only risk-index projection carries exactly the PRD's seven fields."""
    assert is_valid_uuid(record["licensee_id"])
    assert_quarter_label(record["as_of_quarter"])
    assert record["variant"] in ("ROLLING_MONITOR", "STRICT_ASSESSMENT")
    assert isinstance(record["index"], int)
    assert record["posture_band"] in ("CLEAR", "WATCH", "PROBATION", "FROZEN")
    assert isinstance(record["factor_count"], int)
    assert isinstance(record["raw_weighted_total_milli"], int)


# ---------------------------------------------------------------------------
# Format assertions
# ---------------------------------------------------------------------------


def assert_quarter_label(label: Any) -> None:
    """A quarter label is a four-digit year, the letter Q and the quarter number,
    with no dash and no other separator."""
    assert isinstance(label, str), f"quarter label is not a string: {label!r}"
    assert len(label) == 6, f"quarter label has the wrong length: {label!r}"
    assert label[:4].isdigit(), f"quarter label year is not four digits: {label!r}"
    assert label[4] == "Q", f"quarter label is missing the letter Q: {label!r}"
    assert label[5] in "1234", f"quarter label has an invalid quarter number: {label!r}"


def assert_iso_date(value: Any) -> None:
    assert isinstance(value, str) and len(value) == 10, value
    assert value[4] == "-" and value[7] == "-", value


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_advance_ledger_conserved(agreement: Dict[str, Any]) -> None:
    """`advance_paid_cents` always equals `unrecouped_advance_cents` plus
    `recouped_advance_cents`."""
    assert (
        agreement["advance_paid_cents"]
        == agreement["unrecouped_advance_cents"] + agreement["recouped_advance_cents"]
    ), (
        f"advance ledger drifted: paid={agreement['advance_paid_cents']} "
        f"unrecouped={agreement['unrecouped_advance_cents']} "
        f"recouped={agreement['recouped_advance_cents']}"
    )


def assert_distribution_pool_conserved(
    run: Dict[str, Any], club_distributions: List[Dict[str, Any]]
) -> None:
    """The sum of every club's `amount_cents` plus `player_pool_cents` plus
    `league_admin_cents` equals `pool_gross_cents` exactly."""
    club_total = sum(row["amount_cents"] for row in club_distributions)
    assert (
        club_total + run["player_pool_cents"] + run["league_admin_cents"]
        == run["pool_gross_cents"]
    ), (
        f"pool drifted: clubs={club_total} player={run['player_pool_cents']} "
        f"admin={run['league_admin_cents']} gross={run['pool_gross_cents']}"
    )
    assert club_total == run["club_pool_cents"], (
        f"club rows sum to {club_total} but club_pool_cents is {run['club_pool_cents']}"
    )


def assert_payable_total(report: Dict[str, Any]) -> None:
    """The total payable is the pre-fee cash plus the late-filing interest plus the
    administration fee."""
    assert (
        report["total_payable_cents"]
        == report["cash_due_pre_fee_cents"]
        + report["late_filing_interest_cents"]
        + report["admin_fee_cents"]
    ), report


def assert_club_distribution_components(row: Dict[str, Any]) -> None:
    """Each club row's amount is its equal component plus its weighted component plus
    any remainder cent it received."""
    assert (
        row["amount_cents"]
        == row["equal_component_cents"]
        + row["weighted_component_cents"]
        + row["remainder_cent_applied"]
    ), row
