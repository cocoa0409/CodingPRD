"""
Per-entity shape assertions plus the domain invariant checkers.

The system fields are shared: "`id` is a server-generated UUID string with no
prefix", "`created_at` and `updated_at` are ISO 8601 UTC timestamps with exactly
three fractional-second digits", "`version` starts at 1 on creation and is
incremented by exactly one on every mutation".  The lone exception is the lead
scan, which "carries only `id` and `created_at`".
"""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import LEAD_SCAN_ABSENT_FIELDS


# ── Shared system fields ────────────────────────────────────────────────────
def assert_system_fields(row: Dict[str, Any]) -> None:
    """id / created_at / updated_at / version, as §2.4 declares them."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row["created_at"]), row.get("created_at")
    assert is_iso8601_timestamp(row["updated_at"]), row.get("updated_at")
    assert isinstance(row["version"], int) and row["version"] >= 1, row.get("version")


def assert_has_fields(row: Dict[str, Any], fields: Iterable[str]) -> None:
    missing = [f for f in fields if f not in row]
    assert not missing, f"missing fields {missing} in {sorted(row)}"


def assert_absent_fields(row: Dict[str, Any], fields: Iterable[str]) -> None:
    present = [f for f in fields if f in row]
    assert not present, f"fields {present} must not be present in {sorted(row)}"


# ── VenueContract ───────────────────────────────────────────────────────────
def assert_venue_contract(row: Dict[str, Any],
                          status: Optional[str] = None) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "venue_code", "hall_code", "hall_gross_sqft", "min_aisle_ratio_pct",
        "max_booth_height_ft", "contract_year_start", "contract_year_count",
        "committed_net_sqft_per_year", "attrition_allowance_pct",
        "advance_order_discount_pct", "labor_rate_cents_per_hour",
        "electrical_rate_cents_per_amp", "material_handling_rate_cents_per_cwt",
        "cancellation_fee_schedule", "status", "show_count",
    ])
    assert isinstance(row["cancellation_fee_schedule"], list)
    for bucket in row["cancellation_fee_schedule"]:
        assert "min_days_out" in bucket and "pct" in bucket, bucket
    if status is not None:
        assert row["status"] == status, f"status {row['status']} != {status}"


# ── Show ────────────────────────────────────────────────────────────────────
def assert_show(row: Dict[str, Any], status: Optional[str] = None,
                floor_posture: Optional[str] = None) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "venue_contract_id", "name", "edition_year", "move_in_start",
        "event_start", "event_end", "move_out_end", "gross_sqft",
        "aisle_ratio_pct", "base_rate_cents_per_sqft", "selection_desk_capacity",
        "status", "selection_round", "floor_posture", "sellable_booth_sqft",
        "held_net_sqft", "assigned_net_sqft", "available_net_sqft",
        "committed_ratio_pct", "upheld_violation_count",
    ])
    if status is not None:
        assert row["status"] == status, f"status {row['status']} != {status}"
    if floor_posture is not None:
        assert row["floor_posture"] == floor_posture, (
            f"floor_posture {row['floor_posture']} != {floor_posture}"
        )


def assert_show_area_ledger(show: Dict[str, Any], sellable: int, held: int,
                            assigned: int, available: int,
                            committed_ratio_pct: int) -> None:
    """
    "`available_net_sqft` is always `sellable_booth_sqft` minus `held_net_sqft`
    minus `assigned_net_sqft`" and the four figures partition the floor.
    """
    assert show["sellable_booth_sqft"] == sellable, show["sellable_booth_sqft"]
    assert show["held_net_sqft"] == held, show["held_net_sqft"]
    assert show["assigned_net_sqft"] == assigned, show["assigned_net_sqft"]
    assert show["available_net_sqft"] == available, show["available_net_sqft"]
    assert show["committed_ratio_pct"] == committed_ratio_pct, (
        show["committed_ratio_pct"]
    )
    assert_floor_area_partition(show)


def assert_floor_area_partition(show: Dict[str, Any]) -> None:
    """
    "at every instant `sellable_booth_sqft` equals `available_net_sqft` plus
    `held_net_sqft` plus `assigned_net_sqft`".
    """
    assert (
        show["sellable_booth_sqft"]
        == show["available_net_sqft"] + show["held_net_sqft"]
        + show["assigned_net_sqft"]
    ), (
        f"floor area partition broken: sellable={show['sellable_booth_sqft']} "
        f"available={show['available_net_sqft']} held={show['held_net_sqft']} "
        f"assigned={show['assigned_net_sqft']}"
    )


# ── Booth ───────────────────────────────────────────────────────────────────
def assert_booth(row: Dict[str, Any], status: Optional[str] = None,
                 area_sqft: Optional[int] = None) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "show_id", "booth_number", "width_ft", "depth_ft", "area_sqft",
        "location_class", "premium_zone", "max_height_ft", "status",
    ])
    if status is not None:
        assert row["status"] == status, f"status {row['status']} != {status}"
    if area_sqft is not None:
        assert row["area_sqft"] == area_sqft, row["area_sqft"]


# ── Exhibitor ───────────────────────────────────────────────────────────────
def assert_exhibitor(row: Dict[str, Any], status: Optional[str] = None,
                     priority_tier: Optional[str] = None) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "legal_name", "contact_email", "consecutive_years", "status",
        "ledger_points", "space_points_provisional", "space_points_certified",
        "sponsorship_fulfillment_points", "penalty_points",
        "provisional_priority_points", "certified_priority_points",
        "priority_tier",
    ])
    if status is not None:
        assert row["status"] == status, f"status {row['status']} != {status}"
    if priority_tier is not None:
        assert row["priority_tier"] == priority_tier, row["priority_tier"]


def assert_point_ledger_identity(exhibitor: Dict[str, Any]) -> None:
    """
    "An exhibitor's `provisional_priority_points` must always equal its
    `ledger_points` plus `space_points_provisional` plus
    `sponsorship_fulfillment_points` less `penalty_points`, clamped at zero".

    Call this only where the exhibitor carries no sponsorship spend, so that the
    published `space_points_provisional` is the whole space term.
    """
    expected = max(
        0,
        exhibitor["ledger_points"] + exhibitor["space_points_provisional"]
        + exhibitor["sponsorship_fulfillment_points"]
        - exhibitor["penalty_points"],
    )
    assert exhibitor["provisional_priority_points"] == expected, (
        f"provisional {exhibitor['provisional_priority_points']} != {expected}"
    )


def assert_penalty_points_never_clamped(exhibitor: Dict[str, Any],
                                        expected_penalty_points: int) -> None:
    """
    "`penalty_points` is purely additive": the clamp lands on the published
    standing, never on the penalty accumulator itself.
    """
    assert exhibitor["penalty_points"] == expected_penalty_points, (
        f"penalty_points {exhibitor['penalty_points']} != "
        f"{expected_penalty_points}"
    )


# ── SelectionAppointment ────────────────────────────────────────────────────
def assert_selection_appointment(row: Dict[str, Any],
                                 state: Optional[str] = None) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "show_id", "exhibitor_id", "round_index", "window_start", "window_end",
        "state",
    ])
    if state is not None:
        assert row["state"] == state, f"state {row['state']} != {state}"


# ── SpaceContract ───────────────────────────────────────────────────────────
def assert_space_contract(row: Dict[str, Any], status: Optional[str] = None) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "show_id", "exhibitor_id", "status", "offered_booth_ids",
        "offered_net_sqft", "premium_placement_requested", "requested_sqft",
        "negotiation_round", "volume_tier_pct", "space_fee_cents",
        "sponsorship_attached_cents", "bundle_discount_pct",
        "bundle_discount_cents", "invoice_total_cents", "min_deposit_cents",
        "deposit_paid_cents", "cancellation_fee_cents",
        "fee_applied_to_deposit_cents", "refund_cents", "balance_due_cents",
        "points_awarded",
    ])
    assert isinstance(row["offered_booth_ids"], list)
    if status is not None:
        assert row["status"] == status, f"status {row['status']} != {status}"


def assert_deposit_conservation(contract: Dict[str, Any]) -> None:
    """
    "`deposit_paid_cents` always equals `refund_cents` plus
    `fee_applied_to_deposit_cents`", "`cancellation_fee_cents` always equals
    `fee_applied_to_deposit_cents` plus `balance_due_cents`", and "at most one of
    `refund_cents` and `balance_due_cents` is non-zero".
    """
    assert (
        contract["deposit_paid_cents"]
        == contract["refund_cents"] + contract["fee_applied_to_deposit_cents"]
    ), (
        f"deposit {contract['deposit_paid_cents']} != refund "
        f"{contract['refund_cents']} + applied "
        f"{contract['fee_applied_to_deposit_cents']}"
    )
    assert (
        contract["cancellation_fee_cents"]
        == contract["fee_applied_to_deposit_cents"] + contract["balance_due_cents"]
    ), (
        f"fee {contract['cancellation_fee_cents']} != applied "
        f"{contract['fee_applied_to_deposit_cents']} + balance "
        f"{contract['balance_due_cents']}"
    )
    assert contract["refund_cents"] == 0 or contract["balance_due_cents"] == 0, (
        f"both refund {contract['refund_cents']} and balance "
        f"{contract['balance_due_cents']} are non-zero"
    )


def assert_cancellation_ledger_untouched(contract: Dict[str, Any]) -> None:
    """
    "While a contract is not cancelled all three of `cancellation_fee_cents`,
    `refund_cents` and `balance_due_cents` are zero."
    """
    assert contract["cancellation_fee_cents"] == 0, contract["cancellation_fee_cents"]
    assert contract["refund_cents"] == 0, contract["refund_cents"]
    assert contract["balance_due_cents"] == 0, contract["balance_due_cents"]


# ── ServiceOrder ────────────────────────────────────────────────────────────
def assert_service_order(row: Dict[str, Any], status: Optional[str] = None,
                         rate_variant: Optional[str] = None) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "space_contract_id", "service_type", "quantity", "billable_quantity",
        "unit_rate_cents", "rate_variant", "line_total_cents", "ordered_at",
        "status",
    ])
    if status is not None:
        assert row["status"] == status, f"status {row['status']} != {status}"
    if rate_variant is not None:
        assert row["rate_variant"] == rate_variant, row["rate_variant"]


# ── SponsorshipPackage / SponsorshipDeal / FulfillmentObligation ────────────
def assert_sponsorship_package(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "show_id", "package_code", "list_price_cents", "price_floor_cents",
        "inventory_total", "inventory_committed", "inventory_available",
        "exclusivity_category", "obligation_codes", "priority_point_value",
    ])
    assert_sponsorship_inventory_conservation(row)


def assert_sponsorship_inventory_conservation(package: Dict[str, Any]) -> None:
    """
    "`inventory_total` always equals `inventory_committed` plus
    `inventory_available`."
    """
    assert (
        package["inventory_total"]
        == package["inventory_committed"] + package["inventory_available"]
    ), (
        f"inventory_total {package['inventory_total']} != committed "
        f"{package['inventory_committed']} + available "
        f"{package['inventory_available']}"
    )


def assert_sponsorship_deal(row: Dict[str, Any], deal_status: Optional[str] = None,
                            fulfillment_status: Optional[str] = None) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "sponsorship_package_id", "exhibitor_id", "negotiated_price_cents",
        "deal_status", "fulfillment_status", "obligation_count",
        "resolved_obligation_count", "fulfillment_credited",
        "proposed_by_user_id",
    ])
    if deal_status is not None:
        assert row["deal_status"] == deal_status, row["deal_status"]
    if fulfillment_status is not None:
        assert row["fulfillment_status"] == fulfillment_status, (
            row["fulfillment_status"]
        )


def assert_obligation(row: Dict[str, Any], status: Optional[str] = None) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "sponsorship_deal_id", "obligation_code", "status", "due_date",
    ])
    if status is not None:
        assert row["status"] == status, f"status {row['status']} != {status}"


# ── Registration / RuleViolation / LeadScan ─────────────────────────────────
def assert_registration(row: Dict[str, Any],
                        qualification_status: Optional[str] = None,
                        qualification_score: Optional[int] = None) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "show_id", "category", "company_name", "job_title",
        "purchasing_authority", "annual_spend_band", "email",
        "qualification_score", "qualification_status", "lead_scan_count",
    ])
    if qualification_status is not None:
        assert row["qualification_status"] == qualification_status, (
            row["qualification_status"]
        )
    if qualification_score is not None:
        assert row["qualification_score"] == qualification_score, (
            row["qualification_score"]
        )


def assert_rule_violation(row: Dict[str, Any], status: Optional[str] = None,
                          penalty_points: Optional[int] = None) -> None:
    assert_system_fields(row)
    assert_has_fields(row, [
        "space_contract_id", "violation_type", "status", "penalty_points",
        "reported_by_user_id",
    ])
    if status is not None:
        assert row["status"] == status, f"status {row['status']} != {status}"
    if penalty_points is not None:
        assert row["penalty_points"] == penalty_points, row["penalty_points"]


def assert_lead_scan(row: Dict[str, Any]) -> None:
    """A lead scan "carries only `id` and `created_at`" of the shared fields."""
    assert is_valid_uuid(row["id"]), row.get("id")
    assert is_iso8601_timestamp(row["created_at"]), row.get("created_at")
    assert_has_fields(row, ["space_contract_id", "registration_id", "scanned_at"])
    assert_absent_fields(row, LEAD_SCAN_ABSENT_FIELDS)


# ── Version helpers ─────────────────────────────────────────────────────────
def assert_version_bumped(new_row: Dict[str, Any], old_version: int,
                          by: int = 1) -> None:
    assert new_row["version"] == old_version + by, (
        f"version {new_row['version']} != {old_version} + {by}"
    )


def assert_version_unchanged(new_row: Dict[str, Any], old_version: int) -> None:
    assert new_row["version"] == old_version, (
        f"version moved: {new_row['version']} != {old_version}"
    )
