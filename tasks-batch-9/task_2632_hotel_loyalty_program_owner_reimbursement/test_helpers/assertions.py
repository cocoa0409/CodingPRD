"""Domain-specific assertion helpers.

Every helper here reads a response body or an entity dict and asserts a rule the
PRD states directly. Nothing here silently recomputes a figure a test is meant to
pin literally.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import (
    BENEFIT_ENTITLEMENT,
    DENIAL_COUNTED_STATUSES,
    FEE_LEDGER_STAY_STATUSES,
    RATE_CATEGORY_TABLE,
    THRESHOLDS,
)


# ----------------------------------------------------------------------
# Common-field shape
# ----------------------------------------------------------------------
def assert_versioned_entity_shape(entity: dict) -> None:
    """A mutable entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1


def assert_append_only_entity_shape(entity: dict) -> None:
    """An append-only record carries only id and created_at: no updated_at and no
    version, because the row is never revised after it is written."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "append-only row must not carry updated_at"
    assert "version" not in entity, "append-only row must not carry version"


def assert_created_and_updated_match(entity: dict) -> None:
    """On the first write of an entity the two stamps agree."""
    assert entity["created_at"] == entity["updated_at"], (
        f"created_at {entity['created_at']} != updated_at {entity['updated_at']}"
    )


# ----------------------------------------------------------------------
# Properties
# ----------------------------------------------------------------------
def assert_hotel_counters_zero(hotel: dict) -> None:
    """A freshly enrolled property starts every running counter at zero."""
    for field in (
        "fee_ledger_balance_cents",
        "reimbursement_owed_cents",
        "benefit_recovery_owed_cents",
        "benefit_denial_count",
        "blackout_days_used_current_year",
    ):
        assert hotel[field] == 0, f"{field} should start at 0, got {hotel[field]}"


def assert_hotel(
    hotel: dict,
    *,
    status: str = None,
    fee_ledger_cents: int = None,
    reimbursement_owed_cents: int = None,
    benefit_recovery_owed_cents: int = None,
    benefit_denial_count: int = None,
    blackout_days_used: int = None,
    version: int = None,
    termination_reason: str = None,
) -> None:
    checks = {
        "status": status,
        "fee_ledger_balance_cents": fee_ledger_cents,
        "reimbursement_owed_cents": reimbursement_owed_cents,
        "benefit_recovery_owed_cents": benefit_recovery_owed_cents,
        "benefit_denial_count": benefit_denial_count,
        "blackout_days_used_current_year": blackout_days_used,
        "version": version,
        "termination_reason": termination_reason,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert hotel[field] == expected, (
                f"hotel {field} is {hotel[field]}, expected {expected}"
            )


def assert_rate_plan_derivation(rate_plan: dict) -> None:
    """The four rate-plan flags follow from rate_category alone."""
    expected = RATE_CATEGORY_TABLE[rate_plan["rate_category"]]
    for field, value in expected.items():
        assert rate_plan[field] == value, (
            f"{rate_plan['rate_category']}.{field} is {rate_plan[field]}, expected {value}"
        )


def assert_fee_delinquency_posture(hotel: dict) -> None:
    """A property is delinquent only when its fee ledger is strictly above the
    threshold; a balance exactly at the threshold leaves it active."""
    over = hotel["fee_ledger_balance_cents"] > THRESHOLDS["FEE_DELINQUENCY_CENTS"]
    if over:
        assert hotel["status"] == "FEE_DELINQUENT", hotel["status"]
    elif hotel["status"] in ("ACTIVE", "FEE_DELINQUENT"):
        assert hotel["status"] == "ACTIVE", (
            f"ledger {hotel['fee_ledger_balance_cents']} is not above the threshold "
            f"yet status is {hotel['status']}"
        )


# ----------------------------------------------------------------------
# Members and the point ledger
# ----------------------------------------------------------------------
def assert_member_tier(member: dict, expected: str) -> None:
    assert member["elite_tier"] == expected, (
        f"elite_tier {member['elite_tier']} != expected {expected}"
    )


def assert_member(
    member: dict,
    *,
    elite_tier: str = None,
    qualifying_nights: int = None,
    qualifying_revenue_cents: int = None,
    point_balance: int = None,
    lifetime_points_earned: int = None,
    points_purchased_current_year: int = None,
    version: int = None,
) -> None:
    checks = {
        "elite_tier": elite_tier,
        "qualifying_nights_ytd": qualifying_nights,
        "qualifying_revenue_cents_ytd": qualifying_revenue_cents,
        "point_balance": point_balance,
        "lifetime_points_earned": lifetime_points_earned,
        "points_purchased_current_year": points_purchased_current_year,
        "version": version,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert member[field] == expected, (
                f"member {field} is {member[field]}, expected {expected}"
            )


def assert_member_counters_zero(member: dict) -> None:
    """A new member starts at BASE with every counter at zero."""
    assert member["elite_tier"] == "BASE", member["elite_tier"]
    for field in (
        "qualifying_nights_ytd",
        "qualifying_revenue_cents_ytd",
        "point_balance",
        "lifetime_points_earned",
        "points_purchased_current_year",
    ):
        assert member[field] == 0, f"{field} should start at 0, got {member[field]}"


def assert_ledger_entry(
    entry: dict,
    *,
    entry_type: str = None,
    points: int = None,
    member_id: str = None,
    reversal_of_entry_id: str = None,
    source_stay_id: str = None,
    source_redemption_id: str = None,
    source_purchase_id: str = None,
    adjustment_reason: str = None,
    liability_unit_cost: int = None,
) -> None:
    assert_append_only_entity_shape(entry)
    checks = {
        "entry_type": entry_type,
        "points": points,
        "member_id": member_id,
        "reversal_of_entry_id": reversal_of_entry_id,
        "source_stay_id": source_stay_id,
        "source_redemption_id": source_redemption_id,
        "source_purchase_id": source_purchase_id,
        "adjustment_reason": adjustment_reason,
        "liability_unit_cost_cents_per_1000": liability_unit_cost,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert entry[field] == expected, (
                f"ledger entry {field} is {entry[field]}, expected {expected}"
            )


def assert_scoped_ledger_sum_is_zero(entries: list) -> None:
    """A reversal cancels the entry it points at, so a fully compensated scope
    sums to zero."""
    total = sum(entry["points"] for entry in entries)
    assert total == 0, f"scoped ledger sum is {total}, expected 0"


def assert_ledger_sum_equals(entries: list, expected: int) -> None:
    total = sum(entry["points"] for entry in entries)
    assert total == expected, f"scoped ledger sum is {total}, expected {expected}"


def assert_no_entry_of_type(entries: list, entry_type: str) -> None:
    offenders = [e for e in entries if e["entry_type"] == entry_type]
    assert not offenders, f"unexpected {entry_type} rows: {offenders}"


def entries_of_type(entries: list, entry_type: str) -> list:
    return [e for e in entries if e["entry_type"] == entry_type]


def count_entries_of_type(entries: list, entry_type: str) -> int:
    return len(entries_of_type(entries, entry_type))


def assert_balance_equals_ledger_sum(member: dict, entries: list) -> None:
    """A member's balance equals the signed sum of that member's ledger entries,
    exactly and with no rounding in the comparison."""
    total = sum(entry["points"] for entry in entries)
    assert member["point_balance"] == total, (
        f"point_balance {member['point_balance']} != ledger sum {total}"
    )


# ----------------------------------------------------------------------
# Stays and benefit obligations
# ----------------------------------------------------------------------
def assert_stay(
    stay: dict,
    *,
    status: str = None,
    base_points: int = None,
    bonus_points: int = None,
    fee_cents: int = None,
    tier_at_checkin: str = None,
    nights: int = None,
    bonus_multiplier: float = None,
    room_revenue_cents: int = None,
    version: int = None,
) -> None:
    checks = {
        "status": status,
        "base_points_awarded": base_points,
        "bonus_points_awarded": bonus_points,
        "program_fee_assessed_cents": fee_cents,
        "tier_at_checkin": tier_at_checkin,
        "nights": nights,
        "room_revenue_cents": room_revenue_cents,
        "version": version,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert stay[field] == expected, (
                f"stay {field} is {stay[field]}, expected {expected}"
            )
    if bonus_multiplier is not None:
        assert abs(stay["bonus_multiplier_applied"] - bonus_multiplier) < 1e-9, (
            f"bonus_multiplier_applied is {stay['bonus_multiplier_applied']}, "
            f"expected {bonus_multiplier}"
        )


def assert_non_qualifying_stay_is_inert(stay: dict) -> None:
    """A non-qualifying rate plan earns nothing and owes no programme fee."""
    assert stay["status"] == "POSTED_NON_QUALIFYING", stay["status"]
    assert stay["base_points_awarded"] == 0, stay["base_points_awarded"]
    assert stay["bonus_points_awarded"] == 0, stay["bonus_points_awarded"]
    assert stay["program_fee_assessed_cents"] == 0, stay["program_fee_assessed_cents"]
    assert abs(stay["bonus_multiplier_applied"] - 0.0) < 1e-9, (
        stay["bonus_multiplier_applied"]
    )


def assert_benefit_types(deliveries: list, expected_types) -> None:
    """The obligations a posting wrote, compared as an unordered set."""
    actual = sorted(d["benefit_type"] for d in deliveries)
    assert actual == sorted(expected_types), (
        f"benefit types {actual} != expected {sorted(expected_types)}"
    )


def assert_entitlement_for_tier(deliveries: list, tier: str) -> None:
    assert_benefit_types(deliveries, BENEFIT_ENTITLEMENT[tier])


def assert_all_deliveries_status(deliveries: list, expected: str) -> None:
    assert deliveries, "no obligations to check"
    for delivery in deliveries:
        assert delivery["status"] == expected, (
            f"obligation {delivery['id']} is {delivery['status']}, expected {expected}"
        )


def assert_delivery(
    delivery: dict,
    *,
    status: str = None,
    benefit_type: str = None,
    cost_recovery_cents: int = None,
    denial_reason: str = None,
) -> None:
    checks = {
        "status": status,
        "benefit_type": benefit_type,
        "cost_recovery_cents": cost_recovery_cents,
        "denial_reason": denial_reason,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert delivery[field] == expected, (
                f"obligation {field} is {delivery[field]}, expected {expected}"
            )


def assert_denial_count_matches_obligations(hotel: dict, deliveries: list) -> None:
    """benefit_denial_count counts the property's obligations left in a refused
    reading."""
    counted = len([d for d in deliveries if d["status"] in DENIAL_COUNTED_STATUSES])
    assert hotel["benefit_denial_count"] == counted, (
        f"benefit_denial_count {hotel['benefit_denial_count']} != counted {counted}"
    )


def assert_fee_ledger_reconciles(hotel: dict, stays: list) -> None:
    """The property's fee ledger equals the sum of the programme fees on its own
    stays that are still in a fee-bearing reading."""
    expected = sum(
        stay["program_fee_assessed_cents"]
        for stay in stays
        if stay["status"] in FEE_LEDGER_STAY_STATUSES
    )
    assert hotel["fee_ledger_balance_cents"] == expected, (
        f"fee ledger {hotel['fee_ledger_balance_cents']} != summed fees {expected}"
    )


# ----------------------------------------------------------------------
# Award bookings and batches
# ----------------------------------------------------------------------
def assert_redemption(
    redemption: dict,
    *,
    fulfillment_status: str = None,
    reimbursement_status: str = None,
    points_charged: int = None,
    estimated_cents: int = None,
    settled_cents: int = None,
    season: str = None,
    points_per_night: int = None,
    award_allotment: int = None,
    cash_copay_cents: int = None,
    nights: int = None,
    cancel_reason: str = None,
) -> None:
    checks = {
        "fulfillment_status": fulfillment_status,
        "reimbursement_status": reimbursement_status,
        "points_charged": points_charged,
        "estimated_reimbursement_cents": estimated_cents,
        "settled_reimbursement_cents": settled_cents,
        "season": season,
        "points_per_night_applied": points_per_night,
        "award_allotment_applied": award_allotment,
        "cash_copay_cents": cash_copay_cents,
        "nights": nights,
        "cancel_reason": cancel_reason,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert redemption[field] == expected, (
                f"award booking {field} is {redemption[field]}, expected {expected}"
            )


def assert_redemption_unbatched(redemption: dict) -> None:
    assert redemption["batch_id"] is None, (
        f"batch_id should be null, got {redemption['batch_id']}"
    )


def assert_batch(
    batch: dict,
    *,
    status: str = None,
    item_count: int = None,
    gross_cents: int = None,
    fee_offset_base_cents: int = None,
    surcharge_cents: int = None,
    total_fee_offset_cents: int = None,
    net_payable_cents: int = None,
    rejection_reason: str = None,
    occupancy_at_release: float = None,
    adr_at_release: int = None,
    released_by: str = None,
    approved_by: str = None,
) -> None:
    checks = {
        "status": status,
        "item_count": item_count,
        "gross_reimbursement_cents": gross_cents,
        "fee_offset_base_cents": fee_offset_base_cents,
        "delinquency_surcharge_cents": surcharge_cents,
        "total_fee_offset_cents": total_fee_offset_cents,
        "net_payable_cents": net_payable_cents,
        "rejection_reason": rejection_reason,
        "adr_cents_at_release": adr_at_release,
        "released_by_user_id": released_by,
        "approved_by_user_id": approved_by,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert batch[field] == expected, (
                f"batch {field} is {batch[field]}, expected {expected}"
            )
    if occupancy_at_release is not None:
        assert abs(batch["occupancy_pct_at_release"] - occupancy_at_release) < 1e-9, (
            f"occupancy_pct_at_release is {batch['occupancy_pct_at_release']}, "
            f"expected {occupancy_at_release}"
        )


def assert_batch_money_fields_zeroed(batch: dict) -> None:
    """A rejected batch abandons its working figures."""
    for field in (
        "item_count",
        "gross_reimbursement_cents",
        "fee_offset_base_cents",
        "delinquency_surcharge_cents",
        "total_fee_offset_cents",
        "net_payable_cents",
    ):
        assert batch[field] == 0, f"{field} should be reset to 0, got {batch[field]}"


def assert_release_and_approval_distinct(batch: dict) -> None:
    """The release and approval stamps must name two different operators."""
    released = batch["released_by_user_id"]
    approved = batch["approved_by_user_id"]
    assert released, "released_by_user_id is missing"
    assert approved, "approved_by_user_id is missing"
    assert released != approved, (
        f"release and approval were both performed by {released}"
    )


# ----------------------------------------------------------------------
# Programme fund
# ----------------------------------------------------------------------
def assert_fund(
    fund: dict,
    *,
    cash_cents: int = None,
    outstanding_points: int = None,
    liability_cents: int = None,
    solvency_ratio: float = None,
    status: str = None,
    breakage_rate_pct: float = None,
    last_revalued_at: str = None,
) -> None:
    checks = {
        "cash_balance_cents": cash_cents,
        "outstanding_points": outstanding_points,
        "point_liability_cents": liability_cents,
        "status": status,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert fund[field] == expected, (
                f"fund {field} is {fund[field]}, expected {expected}"
            )
    if solvency_ratio is not None:
        assert abs(fund["solvency_ratio"] - solvency_ratio) < 1e-9, (
            f"solvency_ratio {fund['solvency_ratio']} != expected {solvency_ratio}"
        )
    if breakage_rate_pct is not None:
        assert abs(fund["breakage_rate_pct"] - breakage_rate_pct) < 1e-9, (
            f"breakage_rate_pct {fund['breakage_rate_pct']} != expected {breakage_rate_pct}"
        )
    if last_revalued_at is not None:
        assert fund["last_revalued_at"] == last_revalued_at, fund["last_revalued_at"]


def assert_fund_posture_matches_ratio(fund: dict) -> None:
    """The three postures partition the solvency ratio."""
    ratio = fund["solvency_ratio"]
    if ratio >= THRESHOLDS["SOLVENCY_HEALTHY"]:
        expected = "HEALTHY"
    elif ratio >= THRESHOLDS["SOLVENCY_WATCH"]:
        expected = "WATCH"
    else:
        expected = "IMPAIRED"
    assert fund["status"] == expected, (
        f"ratio {ratio} implies {expected} but status is {fund['status']}"
    )


def assert_outstanding_points_equal_member_balances(fund: dict, members: list) -> None:
    """Outstanding points equal the sum of every member balance."""
    expected = sum(member["point_balance"] for member in members)
    assert fund["outstanding_points"] == expected, (
        f"outstanding_points {fund['outstanding_points']} != summed balances {expected}"
    )


def assert_cash_matches_settled_purchases_less_paid_batches(
    fund: dict, purchases: list, batches: list
) -> None:
    """Programme cash equals settled purchase proceeds less paid batch net."""
    settled = sum(
        p["cash_due_cents"] for p in purchases if p["status"] == "SETTLED"
    )
    paid = sum(b["net_payable_cents"] for b in batches if b["status"] == "PAID")
    assert fund["cash_balance_cents"] == settled - paid, (
        f"cash {fund['cash_balance_cents']} != settled {settled} less paid {paid}"
    )


# ----------------------------------------------------------------------
# Purchases and partners
# ----------------------------------------------------------------------
def assert_purchase(
    purchase: dict,
    *,
    status: str = None,
    cash_due_cents: int = None,
    bonus_points: int = None,
    volume_discount_pct: float = None,
    channel: str = None,
    points_quantity: int = None,
    refund_reason: str = None,
) -> None:
    checks = {
        "status": status,
        "cash_due_cents": cash_due_cents,
        "bonus_points": bonus_points,
        "channel": channel,
        "points_quantity": points_quantity,
        "refund_reason": refund_reason,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert purchase[field] == expected, (
                f"purchase {field} is {purchase[field]}, expected {expected}"
            )
    if volume_discount_pct is not None:
        assert abs(purchase["volume_discount_pct"] - volume_discount_pct) < 1e-9, (
            f"volume_discount_pct is {purchase['volume_discount_pct']}, "
            f"expected {volume_discount_pct}"
        )


def assert_partner(partner: dict, *, purchased_points_mtd: int = None) -> None:
    if purchased_points_mtd is not None:
        assert partner["purchased_points_mtd"] == purchased_points_mtd, (
            f"purchased_points_mtd is {partner['purchased_points_mtd']}, "
            f"expected {purchased_points_mtd}"
        )


# ----------------------------------------------------------------------
# Blackout windows
# ----------------------------------------------------------------------
def assert_blackout_window(
    window: dict,
    *,
    status: str = None,
    day_count: int = None,
    scope: str = None,
    revoke_reason: str = None,
    version: int = None,
) -> None:
    checks = {
        "status": status,
        "day_count": day_count,
        "scope": scope,
        "revoke_reason": revoke_reason,
        "version": version,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert window[field] == expected, (
                f"blackout window {field} is {window[field]}, expected {expected}"
            )


# ----------------------------------------------------------------------
# Complaints
# ----------------------------------------------------------------------
def assert_complaint(
    complaint: dict,
    *,
    status: str = None,
    info_request_count: int = None,
    goodwill_points_granted: int = None,
    adjudication_outcome: str = None,
    subject_type: str = None,
    related_delivery_id: str = None,
    resolution: str = None,
) -> None:
    checks = {
        "status": status,
        "info_request_count": info_request_count,
        "goodwill_points_granted": goodwill_points_granted,
        "adjudication_outcome": adjudication_outcome,
        "subject_type": subject_type,
        "related_delivery_id": related_delivery_id,
        "resolution": resolution,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert complaint[field] == expected, (
                f"complaint {field} is {complaint[field]}, expected {expected}"
            )


# ----------------------------------------------------------------------
# Listing helpers
# ----------------------------------------------------------------------
def collect_all(list_call, headers, **filters) -> list:
    """Drain a paginated collection endpoint into one list."""
    rows = []
    offset = 0
    while True:
        params = {"limit": 100, "offset": offset}
        params.update(filters)
        response = list_call(headers, params=params)
        page, meta = validate_paginated(response)
        rows.extend(page)
        if not meta["has_more"] or not page:
            break
        offset += len(page)
    return rows


def assert_ids_present(rows: list, expected_ids) -> None:
    actual = {row["id"] for row in rows}
    for expected in expected_ids:
        assert expected in actual, f"id {expected} missing from the listing"


def assert_ids_absent(rows: list, unexpected_ids) -> None:
    actual = {row["id"] for row in rows}
    for unexpected in unexpected_ids:
        assert unexpected not in actual, f"id {unexpected} should not be listed"


def assert_single_row(rows: list, expected_id: str) -> dict:
    assert len(rows) == 1, f"expected exactly one row, got {len(rows)}"
    assert rows[0]["id"] == expected_id, rows[0]["id"]
    return rows[0]


def read_entity(get_call, entity_id: str, headers) -> dict:
    """Fetch one row and unwrap the success envelope."""
    return validate_success(get_call(entity_id, headers))
