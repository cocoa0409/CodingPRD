"""Response projections of PRD 2.11.  The projection is identical for the list
and the detail form of a resource; only the item redaction rules differ by role.
"""

COMMON = ("id", "created_at", "updated_at", "version")
LIGHT = ("id", "created_at")


def _pick(row, fields):
    return {f: row.get(f) for f in fields}


MEMBER_FIELDS = COMMON + ("email", "full_name", "member_role", "household_id")
HOUSEHOLD_FIELDS = COMMON + (
    "name",
    "address_label",
    "write_gate_state",
    "records_freeze_active",
    "item_count",
    "asset_count",
    "asset_bytes_used",
    "frozen_item_count",
    "active_share_count",
    "total_effective_value_cents",
)
SUBSCRIPTION_FIELDS = COMMON + (
    "household_id",
    "tier",
    "status",
    "refresh_state",
    "period_start_at",
    "period_end_at",
    "past_due_since_at",
    "last_attested_at",
    "refresh_due_at",
    "appraisal_credits_remaining",
    "packages_used_this_period",
    "monthly_fee_cents",
    "last_proration_charge_cents",
)
ROOM_FIELDS = COMMON + ("household_id", "name", "floor_label", "item_count")
ITEM_FIELDS = COMMON + (
    "household_id",
    "room_id",
    "name",
    "category",
    "quantity",
    "serial_number",
    "acquired_at",
    "purchase_price_cents",
    "replacement_cost_cents",
    "declared_value_cents",
    "declared_by_member_id",
    "lifecycle_state",
    "evidence_tier",
    "valuation_state",
    "effective_value_cents",
    "effective_value_basis",
    "acv_value_cents",
    "coverage_mode",
    "scheduled_policy_id",
    "scheduled_value_cents",
    "replaces_item_id",
    "serial_chain_intact",
    "allocated_quantity",
    "frozen_by_claim_id",
)
ASSET_FIELDS = LIGHT + ("item_id", "asset_kind", "byte_size", "checksum", "captured_at", "status")
CATEGORY_SCHEDULE_FIELDS = LIGHT + (
    "category",
    "useful_life_months",
    "annual_depreciation_pct",
    "salvage_floor_pct",
    "blanket_sublimit_cents",
    "appraisal_scope",
    "serial_required",
)
APPRAISER_FIELDS = COMMON + (
    "display_name",
    "credential_id",
    "scope_categories",
    "linked_member_id",
    "status",
)
APPRAISAL_FIELDS = COMMON + (
    "item_id",
    "appraiser_id",
    "requested_by_member_id",
    "status",
    "inspection_start_at",
    "inspection_end_at",
    "appraised_value_cents",
    "certified_at",
    "valid_until_at",
    "credit_consumed",
    "void_reason",
)
POLICY_FIELDS = COMMON + (
    "household_id",
    "carrier_name",
    "policy_number",
    "deductible_cents",
    "scheduled_allowance_cents",
    "scheduled_consumed_cents",
    "scheduled_remaining_cents",
    "coverage_gap_cents",
    "total_effective_value_cents",
    "effective_from",
)
PACKAGE_FIELDS = COMMON + (
    "household_id",
    "policy_id",
    "status",
    "recipient_ref",
    "generated_at",
    "delivered_at",
    "expires_at",
    "line_count",
    "snapshot_total_effective_cents",
    "snapshot_total_covered_cents",
    "snapshot_coverage_gap_cents",
    "stale_line_count",
    "superseded_by_package_id",
)
PACKAGE_LINE_FIELDS = LIGHT + (
    "package_id",
    "item_id",
    "snapshot_name",
    "snapshot_category",
    "snapshot_evidence_tier",
    "snapshot_effective_value_cents",
    "snapshot_effective_value_basis",
    "snapshot_covered_cents",
    "snapshot_coverage_mode",
    "stale",
)
CLAIM_FIELDS = COMMON + (
    "household_id",
    "package_id",
    "policy_id",
    "loss_date",
    "peril",
    "settlement_basis",
    "deductible_mode",
    "affected_room_ids",
    "status",
    "submitted_at",
    "frozen_item_count",
    "line_count",
    "approved_line_count",
    "denied_line_count",
    "blocked_line_count",
    "total_settlement_cents",
)
CLAIM_LINE_FIELDS = COMMON + (
    "claim_id",
    "item_id",
    "claimed_quantity",
    "status",
    "gross_value_cents",
    "capped_value_cents",
    "deductible_share_cents",
    "net_settlement_cents",
    "appeal_count",
    "settlement_hold",
    "basis_downgraded",
    "denial_reason",
)
ESTATE_PLAN_FIELDS = COMMON + (
    "household_id",
    "executor_member_id",
    "status",
    "valuation_mode",
    "proposed_at",
    "approved_at",
    "executed_at",
    "approved_by_member_id",
    "heir_count",
    "balance_spread_pct",
    "balanced",
    "unallocated_item_count",
)
ALLOCATION_FIELDS = COMMON + (
    "estate_plan_id",
    "item_id",
    "heir_member_id",
    "disposition",
    "quantity",
    "allocated_value_cents",
    "blocked",
)
SHARE_GRANT_FIELDS = COMMON + (
    "household_id",
    "scope_kind",
    "scope_room_id",
    "scope_package_id",
    "scope_claim_id",
    "recipient_ref",
    "redaction_level",
    "share_token",
    "starts_at",
    "expires_at",
    "access_cap",
    "access_count",
    "status",
    "voided_reason",
)


def member(row):
    return _pick(row, MEMBER_FIELDS)


def household(row):
    return _pick(row, HOUSEHOLD_FIELDS)


def subscription(row):
    return _pick(row, SUBSCRIPTION_FIELDS)


def room(row):
    return _pick(row, ROOM_FIELDS)


def item(row, role=None):
    """PRD 2.11 role-based redaction on item reads."""
    out = _pick(row, ITEM_FIELDS)
    if role in ("HouseholdMember", "Appraiser"):
        if row.get("evidence_tier") != "DOCUMENTED":
            out["serial_number"] = None
    elif role in ("InsuranceAgent", "ClaimsAdjuster"):
        out["declared_by_member_id"] = None
    return out


def asset(row):
    return _pick(row, ASSET_FIELDS)


def category_schedule(row):
    return _pick(row, CATEGORY_SCHEDULE_FIELDS)


def appraiser(row):
    return _pick(row, APPRAISER_FIELDS)


def appraisal(row):
    return _pick(row, APPRAISAL_FIELDS)


def policy(row):
    return _pick(row, POLICY_FIELDS)


def package(row):
    return _pick(row, PACKAGE_FIELDS)


def package_line(row):
    return _pick(row, PACKAGE_LINE_FIELDS)


def claim(row):
    return _pick(row, CLAIM_FIELDS)


def claim_line(row):
    return _pick(row, CLAIM_LINE_FIELDS)


def estate_plan(row):
    return _pick(row, ESTATE_PLAN_FIELDS)


def allocation(row):
    return _pick(row, ALLOCATION_FIELDS)


def share_grant(row):
    return _pick(row, SHARE_GRANT_FIELDS)
