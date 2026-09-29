"""Entity assertions and domain invariant checkers for the season API."""

from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    CapabilityGap,
    CreditRating,
    EducationProgramStatus,
    EngagementType,
    EquipmentCategory,
    FinancialClearance,
    LaborCallStatus,
    LifecycleStatus,
    NegotiationStatus,
    PriceTierStatus,
    ProgramType,
    RentalLineStatus,
    ReserveEntryType,
    RiderReviewStatus,
    RiskTier,
    SalesChannel,
    SettlementStatus,
    SpaceStatus,
    TicketSaleStatus,
    TicketingStatus,
    UnionDepartmentName,
)

_ENUM_VALUES = lambda enum_cls: [member.value for member in enum_cls]  # noqa: E731


# ─── Shared resource properties ───────────────────────

def assert_identity_fields(data: dict, entity_label: str = "resource") -> None:
    """Every resource carries a server-minted id formatted as a UUID with no
    type prefix and an ISO 8601 UTC created_at with three fractional digits."""
    entity_id = data.get("id")
    assert isinstance(entity_id, str), f"{entity_label}.id must be a string"
    assert is_valid_uuid(entity_id), (
        f"{entity_label}.id must be a UUID with no type prefix, got {entity_id!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 UTC instant, "
        f"got {data.get('created_at')!r}"
    )


def assert_mutation_tracking_fields(data: dict, entity_label: str = "resource") -> None:
    """updated_at is an ISO 8601 UTC timestamp and version is an integer that
    starts at 1 on creation."""
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 UTC instant, "
        f"got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{entity_label}.version must be an integer, got {version!r}"
    )
    assert version >= 1, f"{entity_label}.version must start at 1, got {version}"


def assert_common_fields(data: dict, entity_label: str = "resource") -> None:
    assert_identity_fields(data, entity_label)
    assert_mutation_tracking_fields(data, entity_label)


def assert_no_mutation_tracking_fields(data: dict,
                                       entity_label: str = "resource") -> None:
    """For the append-only reserve ledger, which carries neither field."""
    assert "updated_at" not in data, (
        f"{entity_label} is append-only and must carry no updated_at field, "
        f"got {data.get('updated_at')!r}"
    )
    assert "version" not in data, (
        f"{entity_label} is append-only and must carry no version field, "
        f"got {data.get('version')!r}"
    )


def assert_cents(value, field_label: str, allow_negative: bool = False) -> None:
    """Monetary quantities are integer counts of cents, never strings and never
    decimal fractions."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_label} must be an integer number of cents, got {value!r}"
    )
    if not allow_negative:
        assert value >= 0, f"{field_label} must not be negative, got {value}"


# ─── Per-entity assertions ────────────────────────────

def assert_performance_space(data: dict) -> None:
    assert_common_fields(data, "PerformanceSpace")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert_cents(data["base_facility_fee_cents"], "base_facility_fee_cents")
    assert_cents(data["load_in_day_fee_cents"], "load_in_day_fee_cents")
    assert isinstance(data["changeover_buffer_minutes"], int)
    assert data["changeover_buffer_minutes"] >= 0
    assert isinstance(data["rigging_capacity_kg"], int)
    assert data["rigging_capacity_kg"] >= 0
    assert isinstance(data["house_power_amps"], int) and data["house_power_amps"] >= 0
    assert isinstance(data["dmx_universes"], int) and data["dmx_universes"] >= 0
    assert data["status"] in _ENUM_VALUES(SpaceStatus)


def assert_artist(data: dict) -> None:
    assert_common_fields(data, "Artist")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert_cents(data["guarantee_floor_cents"], "guarantee_floor_cents")
    assert 0 <= float(data["historical_sell_through_pct"]) <= 1
    assert is_iso8601_timestamp(data["routing_window_start_utc"])
    assert is_iso8601_timestamp(data["routing_window_end_utc"])
    assert isinstance(data["min_days_between_engagements"], int)
    assert data["min_days_between_engagements"] >= 0
    assert_cents(data["lifetime_guarantee_paid_cents"], "lifetime_guarantee_paid_cents")


def assert_rental_client(data: dict) -> None:
    assert_common_fields(data, "RentalClient")
    assert isinstance(data["org_name"], str) and data["org_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["credit_rating"] in _ENUM_VALUES(CreditRating)
    assert isinstance(data["is_nonprofit"], bool)
    assert_cents(data["outstanding_balance_cents"], "outstanding_balance_cents",
                 allow_negative=True)


def assert_union_department(data: dict) -> None:
    assert_common_fields(data, "UnionDepartment")
    assert data["department"] in _ENUM_VALUES(UnionDepartmentName)
    assert isinstance(data["roster_size"], int) and data["roster_size"] >= 1
    assert_cents(data["straight_hourly_rate_cents"], "straight_hourly_rate_cents")
    assert data["straight_hourly_rate_cents"] >= 1
    assert float(data["overtime_multiplier"]) > 0
    assert float(data["doubletime_multiplier"]) > 0
    assert float(data["call_minimum_hours"]) >= 0
    assert_cents(data["meal_penalty_cents"], "meal_penalty_cents")


def assert_equipment_item(data: dict) -> None:
    assert_common_fields(data, "EquipmentItem")
    assert data["category"] in _ENUM_VALUES(EquipmentCategory)
    assert isinstance(data["model_name"], str) and data["model_name"]
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert_cents(data["daily_rate_cents"], "daily_rate_cents")
    assert_cents(data["replacement_value_cents"], "replacement_value_cents")
    assert isinstance(data["reserve_funded"], bool)
    assert data["reserved_qty"] <= data["on_hand_qty"], (
        "reserved_qty may never exceed on_hand_qty"
    )


def assert_engagement(data: dict) -> None:
    assert_common_fields(data, "Engagement")
    assert data["engagement_type"] in _ENUM_VALUES(EngagementType)
    assert is_valid_uuid(data["space_id"])
    assert isinstance(data["title"], str) and data["title"]
    for field in ("load_in_start_utc", "performance_start_utc",
                  "performance_end_utc", "load_out_end_utc"):
        assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601"
    assert isinstance(data["performance_day_count"], int)
    assert data["performance_day_count"] >= 1
    assert isinstance(data["load_in_day_count"], int)
    assert data["load_in_day_count"] >= 0
    assert_engagement_dimensions(data)
    assert_cents(data["negotiated_fee_cents"], "negotiated_fee_cents")
    assert 0 <= float(data["artist_share_pct"]) <= 1
    assert_cents(data["facility_fee_cents"], "facility_fee_cents")
    assert_cents(data["labor_estimate_total_cents"], "labor_estimate_total_cents")
    assert_cents(data["additional_equipment_cost_cents"],
                 "additional_equipment_cost_cents")
    assert_cents(data["deposit_required_cents"], "deposit_required_cents")
    assert_cents(data["deposit_paid_cents"], "deposit_paid_cents")
    if data["risk_score"] is not None:
        assert isinstance(data["risk_score"], int)
        assert 0 <= data["risk_score"] <= 100, "risk_score is always between 0 and 100"
    assert data["risk_tier"] in _ENUM_VALUES(RiskTier)
    assert_cents(data["projected_gross_cents"], "projected_gross_cents")
    assert_cents(data["projected_margin_cents"], "projected_margin_cents",
                 allow_negative=True)
    assert_cents(data["realized_gross_cents"], "realized_gross_cents")
    assert_cents(data["realized_margin_cents"], "realized_margin_cents",
                 allow_negative=True)
    assert isinstance(data["negotiation_round_count"], int)
    assert data["negotiation_round_count"] >= 0
    assert_cents(data["cancellation_fee_cents"], "cancellation_fee_cents")


def assert_engagement_dimensions(data: dict) -> None:
    """An engagement carries three separate status dimensions rather than one."""
    assert data["lifecycle_status"] in _ENUM_VALUES(LifecycleStatus), (
        f"unknown lifecycle_status {data.get('lifecycle_status')!r}"
    )
    assert data["financial_clearance"] in _ENUM_VALUES(FinancialClearance), (
        f"unknown financial_clearance {data.get('financial_clearance')!r}"
    )
    assert data["ticketing_status"] in _ENUM_VALUES(TicketingStatus), (
        f"unknown ticketing_status {data.get('ticketing_status')!r}"
    )


def assert_engagement_counterparty_exclusivity(data: dict) -> None:
    """artist_id is required for PRESENTED and must be omitted otherwise;
    rental_client_id is required for RENTAL and must be omitted otherwise."""
    if data["engagement_type"] == EngagementType.PRESENTED.value:
        assert is_valid_uuid(data.get("artist_id") or ""), (
            "a presented engagement must carry its artist_id"
        )
        assert data.get("rental_client_id") in (None, ""), (
            "a presented engagement must not carry a rental_client_id"
        )
    else:
        assert is_valid_uuid(data.get("rental_client_id") or ""), (
            "a rental engagement must carry its rental_client_id"
        )
        assert data.get("artist_id") in (None, ""), (
            "a rental engagement must not carry an artist_id"
        )


def assert_fee_negotiation(data: dict) -> None:
    assert_common_fields(data, "FeeNegotiation")
    assert is_valid_uuid(data["engagement_id"])
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert data["status"] in _ENUM_VALUES(NegotiationStatus)
    assert_cents(data["offered_fee_cents"], "offered_fee_cents")
    assert 0 <= float(data["offered_artist_share_pct"]) <= 1
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]


def assert_tech_rider(data: dict) -> None:
    assert_common_fields(data, "TechRider")
    assert is_valid_uuid(data["engagement_id"])
    assert isinstance(data["submitted_rigging_kg"], int)
    assert data["submitted_rigging_kg"] >= 0
    assert isinstance(data["requested_power_amps"], int)
    assert data["requested_power_amps"] >= 0
    assert isinstance(data["requested_dmx_universes"], int)
    assert data["requested_dmx_universes"] >= 0
    assert isinstance(data["requires_orchestra_pit"], bool)
    assert data["review_status"] in _ENUM_VALUES(RiderReviewStatus)
    assert isinstance(data["capability_gaps"], list)
    for gap in data["capability_gaps"]:
        assert gap in _ENUM_VALUES(CapabilityGap), f"unknown capability gap {gap!r}"
    assert_cents(data["additional_equipment_cost_cents"],
                 "additional_equipment_cost_cents")


def assert_equipment_rental_line(data: dict) -> None:
    assert_common_fields(data, "EquipmentRentalLine")
    assert is_valid_uuid(data["tech_rider_id"])
    assert is_valid_uuid(data["equipment_item_id"])
    assert data["covers_gap"] in ("RIGGING_NEAR_LIMIT", "POWER_SHORTFALL",
                                  "DMX_SHORTFALL", "NONE")
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["rental_days"], int) and data["rental_days"] >= 1
    assert_cents(data["line_cost_cents"], "line_cost_cents")
    assert data["status"] in _ENUM_VALUES(RentalLineStatus)


def assert_labor_call(data: dict) -> None:
    assert_common_fields(data, "LaborCall")
    assert is_valid_uuid(data["engagement_id"])
    assert is_valid_uuid(data["union_department_id"])
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert is_iso8601_timestamp(data["call_start_utc"])
    assert is_iso8601_timestamp(data["call_end_utc"])
    assert data["call_end_utc"] > data["call_start_utc"], (
        "call_end_utc must fall strictly after call_start_utc"
    )
    assert float(data["scheduled_hours"]) > 0
    assert_cents(data["estimated_cost_cents"], "estimated_cost_cents")
    assert_cents(data["actual_cost_cents"], "actual_cost_cents")
    assert data["status"] in _ENUM_VALUES(LaborCallStatus)


def assert_price_tier(data: dict) -> None:
    assert_common_fields(data, "PriceTier")
    assert is_valid_uuid(data["engagement_id"])
    assert isinstance(data["tier_name"], str) and data["tier_name"]
    assert isinstance(data["seats_allocated"], int) and data["seats_allocated"] >= 1
    assert_cents(data["base_price_cents"], "base_price_cents")
    assert_cents(data["price_ceiling_cents"], "price_ceiling_cents")
    assert data["price_ceiling_cents"] >= data["base_price_cents"], (
        "price_ceiling_cents may not be lower than base_price_cents"
    )
    assert isinstance(data["dynamic_pricing_enabled"], bool)
    assert isinstance(data["subscription_eligible"], bool)
    assert isinstance(data["sold_qty"], int) and data["sold_qty"] >= 0
    assert isinstance(data["subscription_held_qty"], int)
    assert data["subscription_held_qty"] >= 0
    assert isinstance(data["available_qty"], int)
    assert_cents(data["gross_cents"], "gross_cents")
    assert_cents(data["subscription_revenue_cents"], "subscription_revenue_cents")
    assert data["status"] in _ENUM_VALUES(PriceTierStatus)
    assert_tier_seat_identity(data)


def assert_tier_seat_identity(tier: dict) -> None:
    """At every instant seats_allocated equals available_qty plus sold_qty plus
    subscription_held_qty for every tier."""
    total = (tier["available_qty"] + tier["sold_qty"]
             + tier["subscription_held_qty"])
    assert tier["seats_allocated"] == total, (
        f"seat identity broken on tier {tier.get('tier_name')!r}: "
        f"seats_allocated={tier['seats_allocated']} but available_qty="
        f"{tier['available_qty']} + sold_qty={tier['sold_qty']} + "
        f"subscription_held_qty={tier['subscription_held_qty']} = {total}"
    )


def assert_ticket_sale(data: dict) -> None:
    assert_common_fields(data, "TicketSale")
    assert is_valid_uuid(data["price_tier_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["channel"] in _ENUM_VALUES(SalesChannel)
    assert 0 <= float(data["sell_through_pct_at_sale"]) <= 1
    assert float(data["dynamic_multiplier_applied"]) > 0
    assert_cents(data["unit_price_cents"], "unit_price_cents")
    assert_cents(data["gross_cents"], "gross_cents")
    assert_cents(data["restoration_fee_cents"], "restoration_fee_cents")
    assert data["status"] in _ENUM_VALUES(TicketSaleStatus)
    assert data["gross_cents"] == data["unit_price_cents"] * data["qty"], (
        "gross_cents is unit_price_cents multiplied by qty"
    )


def assert_subscription_package(data: dict) -> None:
    assert_common_fields(data, "SubscriptionPackage")
    assert isinstance(data["name"], str) and data["name"]
    assert_cents(data["package_price_cents"], "package_price_cents")
    assert data["package_price_cents"] >= 1
    assert isinstance(data["included_engagement_ids"], list)
    assert len(data["included_engagement_ids"]) >= 2
    assert isinstance(data["subscription_tier_name"], str)
    assert isinstance(data["seats_per_order"], int) and data["seats_per_order"] >= 1
    assert isinstance(data["sold_count"], int) and data["sold_count"] >= 0
    assert isinstance(data["allocation_map"], dict)


def assert_settlement(data: dict) -> None:
    assert_common_fields(data, "Settlement")
    assert is_valid_uuid(data["engagement_id"])
    assert data["status"] in _ENUM_VALUES(SettlementStatus)
    assert_cents(data["box_office_gross_cents"], "box_office_gross_cents")
    assert_cents(data["restoration_fees_cents"], "restoration_fees_cents")
    assert_cents(data["adjusted_gross_cents"], "adjusted_gross_cents",
                 allow_negative=True)
    assert_cents(data["guarantee_cents"], "guarantee_cents")
    assert_cents(data["actual_labor_cents"], "actual_labor_cents")
    assert_cents(data["actual_equipment_cents"], "actual_equipment_cents")
    assert_cents(data["actual_marketing_cents"], "actual_marketing_cents")
    assert_cents(data["reimbursable_expense_cap_cents"],
                 "reimbursable_expense_cap_cents")
    assert_cents(data["reimbursable_expenses_cents"], "reimbursable_expenses_cents")
    assert_cents(data["artist_share_cents"], "artist_share_cents")
    assert_cents(data["net_to_center_cents"], "net_to_center_cents",
                 allow_negative=True)
    assert_cents(data["reserve_contribution_cents"], "reserve_contribution_cents")
    assert_cents(data["amount_payable_to_artist_cents"],
                 "amount_payable_to_artist_cents")
    assert_cents(data["balance_due_from_client_cents"],
                 "balance_due_from_client_cents", allow_negative=True)
    assert data["adjusted_gross_cents"] == (data["box_office_gross_cents"]
                                            - data["restoration_fees_cents"]), (
        "adjusted_gross_cents is box_office_gross_cents less restoration_fees_cents"
    )


def assert_education_program(data: dict) -> None:
    assert_common_fields(data, "EducationProgram")
    assert is_valid_uuid(data["engagement_id"])
    assert data["program_type"] in _ENUM_VALUES(ProgramType)
    assert isinstance(data["participant_capacity"], int)
    assert data["participant_capacity"] >= 1
    assert_cents(data["subsidy_requested_cents"], "subsidy_requested_cents")
    assert_cents(data["subsidy_approved_cents"], "subsidy_approved_cents")
    assert data["subsidy_approved_cents"] <= data["subsidy_requested_cents"], (
        "subsidy_approved_cents is the smaller of the request and the allowance"
    )
    assert data["status"] in _ENUM_VALUES(EducationProgramStatus)


def assert_reserve_ledger_entry(data: dict) -> None:
    """A reserve ledger entry is append-only: id and created_at only."""
    assert_identity_fields(data, "ReserveLedgerEntry")
    assert_no_mutation_tracking_fields(data, "ReserveLedgerEntry")
    assert data["entry_type"] in _ENUM_VALUES(ReserveEntryType)
    assert_cents(data["amount_cents"], "amount_cents", allow_negative=True)
    assert isinstance(data["memo"], str)
    assert_cents(data["balance_after_cents"], "balance_after_cents",
                 allow_negative=True)


def assert_box_office_statement(data: dict) -> None:
    assert is_valid_uuid(data["engagement_id"])
    for field in ("tier_count", "seats_allocated_total", "sold_qty_total",
                  "subscription_held_qty_total"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer"
        )
    for field in ("single_ticket_gross_cents", "subscription_revenue_cents",
                  "restoration_fees_cents", "box_office_gross_cents"):
        assert_cents(data[field], field)
    assert_cents(data["adjusted_gross_cents"], "adjusted_gross_cents",
                 allow_negative=True)
    assert data["box_office_gross_cents"] == (data["single_ticket_gross_cents"]
                                              + data["subscription_revenue_cents"]), (
        "box_office_gross_cents is the two revenue figures added together"
    )
    assert data["adjusted_gross_cents"] == (data["box_office_gross_cents"]
                                           - data["restoration_fees_cents"]), (
        "adjusted_gross_cents is box_office_gross_cents less restoration_fees_cents"
    )


# ─── Cross-resource invariant checkers ────────────────

def assert_ledger_running_balance(entries: list) -> None:
    """balance_after_cents is the running total of amount_cents across every
    entry, accumulated in created_at ascending order."""
    running = 0
    ordered = sorted(entries, key=lambda entry: entry["created_at"])
    for entry in ordered:
        running += entry["amount_cents"]
        assert entry["balance_after_cents"] == running, (
            f"ledger entry {entry['id']} reports balance_after_cents="
            f"{entry['balance_after_cents']} but the running total is {running}"
        )


def assert_dimension_triple(engagement: dict, lifecycle_status: str,
                            financial_clearance: str,
                            ticketing_status: str) -> None:
    """Assert all three independent dimensions at once."""
    assert engagement["lifecycle_status"] == lifecycle_status, (
        f"expected lifecycle_status {lifecycle_status}, "
        f"got {engagement['lifecycle_status']}"
    )
    assert engagement["financial_clearance"] == financial_clearance, (
        f"expected financial_clearance {financial_clearance}, "
        f"got {engagement['financial_clearance']}"
    )
    assert engagement["ticketing_status"] == ticketing_status, (
        f"expected ticketing_status {ticketing_status}, "
        f"got {engagement['ticketing_status']}"
    )


def assert_version_unchanged(data: dict, expected_version: int,
                             entity_label: str = "resource") -> None:
    assert data["version"] == expected_version, (
        f"{entity_label}.version should still be {expected_version}, "
        f"got {data['version']}"
    )


def assert_statement_matches_tiers(statement: dict, tiers: list,
                                   restoration_fees_cents: Optional[int] = None
                                   ) -> None:
    """The statement is computed live from the tiers' current counters."""
    assert statement["tier_count"] == len(tiers)
    assert statement["seats_allocated_total"] == sum(
        tier["seats_allocated"] for tier in tiers)
    assert statement["sold_qty_total"] == sum(tier["sold_qty"] for tier in tiers)
    assert statement["subscription_held_qty_total"] == sum(
        tier["subscription_held_qty"] for tier in tiers)
    assert statement["single_ticket_gross_cents"] == sum(
        tier["gross_cents"] for tier in tiers)
    assert statement["subscription_revenue_cents"] == sum(
        tier["subscription_revenue_cents"] for tier in tiers)
    if restoration_fees_cents is not None:
        assert statement["restoration_fees_cents"] == restoration_fees_cents


__all__ = [
    "assert_identity_fields",
    "assert_mutation_tracking_fields",
    "assert_common_fields",
    "assert_no_mutation_tracking_fields",
    "assert_cents",
    "assert_performance_space",
    "assert_artist",
    "assert_rental_client",
    "assert_union_department",
    "assert_equipment_item",
    "assert_engagement",
    "assert_engagement_dimensions",
    "assert_engagement_counterparty_exclusivity",
    "assert_fee_negotiation",
    "assert_tech_rider",
    "assert_equipment_rental_line",
    "assert_labor_call",
    "assert_price_tier",
    "assert_tier_seat_identity",
    "assert_ticket_sale",
    "assert_subscription_package",
    "assert_settlement",
    "assert_education_program",
    "assert_reserve_ledger_entry",
    "assert_box_office_statement",
    "assert_ledger_running_balance",
    "assert_dimension_triple",
    "assert_version_unchanged",
    "assert_statement_matches_tiers",
]
