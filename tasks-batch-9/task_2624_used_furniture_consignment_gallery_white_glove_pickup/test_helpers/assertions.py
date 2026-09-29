"""Shape and invariant assertions for the consignment gallery API."""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CLEARANCE_PRICE_THRESHOLD_CENTS,
    SPLIT_PCT_CEILING,
    SPLIT_PCT_FLOOR,
    UTILIZATION_BANDS,
)

# Every mutable row carries these four. PriceScheduleStep and PayoutLedgerEntry
# are the two rows that do not: they are append-only and carry id + created_at
# alone, with neither updated_at nor version.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
IMMUTABLE_ROW_FIELDS = ("id", "created_at")


def assert_fields_present(entity: Dict[str, Any], fields: Iterable[str]) -> None:
    missing = [f for f in fields if f not in entity]
    assert not missing, f"missing fields {missing} in {sorted(entity)}"


def assert_common_fields(entity: Dict[str, Any]) -> None:
    assert_fields_present(entity, COMMON_FIELDS)
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1, entity[
        "version"
    ]


def assert_append_only_row(entity: Dict[str, Any]) -> None:
    """A row that carries id + created_at and neither updated_at nor version."""
    assert_fields_present(entity, IMMUTABLE_ROW_FIELDS)
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "append-only row must not carry updated_at"
    assert "version" not in entity, "append-only row must not carry version"


def assert_null_columns(entity: Dict[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        assert field in entity, f"expected column {field} to be present"
        assert entity[field] is None, f"expected {field} to be null, got {entity[field]}"


# --- Per-entity shapes ------------------------------------------------------

def assert_consignor(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(
        entity,
        (
            "display_name",
            "email",
            "address_line",
            "floor_number",
            "has_elevator",
            "payout_method",
            "status",
            "unclaimed_balance_cents",
            "lifetime_credits_cents",
            "last_activity_at",
            "escheat_state",
        ),
    )
    assert entity["status"] in ("ACTIVE", "SUSPENDED"), entity["status"]
    assert entity["escheat_state"] in ("NONE", "DORMANT", "ESCHEATED"), entity[
        "escheat_state"
    ]
    assert entity["payout_method"] in ("ACH", "CHECK", "STORE_CREDIT"), entity[
        "payout_method"
    ]
    assert isinstance(entity["unclaimed_balance_cents"], int)
    assert isinstance(entity["lifetime_credits_cents"], int)
    assert entity["lifetime_credits_cents"] >= 0


def assert_buyer(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(
        entity,
        (
            "display_name",
            "email",
            "address_line",
            "floor_number",
            "has_elevator",
            "status",
        ),
    )
    assert entity["status"] in ("ACTIVE", "BLOCKED"), entity["status"]


def assert_price_schedule(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(
        entity,
        ("name", "unsold_trigger_day", "election_window_days", "step_count", "status"),
    )
    assert entity["status"] in ("ACTIVE", "RETIRED"), entity["status"]
    assert isinstance(entity["step_count"], int) and entity["step_count"] >= 0


def assert_price_schedule_step(entity: Dict[str, Any]) -> None:
    assert_append_only_row(entity)
    assert_fields_present(
        entity,
        (
            "schedule_id",
            "sequence",
            "start_day_offset",
            "markdown_pct",
            "min_price_cents",
        ),
    )
    assert entity["sequence"] >= 1
    assert entity["start_day_offset"] >= 0
    assert 0.0 <= float(entity["markdown_pct"]) <= 0.90
    assert entity["min_price_cents"] >= 0


def assert_agreement(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(
        entity,
        (
            "consignor_id",
            "price_schedule_id",
            "term_days",
            "status",
            "effective_at",
            "expires_at",
            "approved_by_user_id",
            "item_count",
        ),
    )
    assert entity["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"), entity[
        "status"
    ]
    assert is_valid_uuid(entity["consignor_id"])
    assert is_valid_uuid(entity["price_schedule_id"])


def assert_consignment_item(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(
        entity,
        (
            "consignor_id",
            "agreement_id",
            "parent_lot_item_id",
            "pickup_job_id",
            "placement_zone_id",
            "title",
            "category",
            "declared_value_cents",
            "photo_count",
            "volume_cuft",
            "footprint_sqft",
            "photo_surface_score",
            "photo_structure_score",
            "photo_completeness_score",
            "photo_score",
            "provisional_condition_grade",
            "provisional_list_price_cents",
            "condition_grade",
            "list_price_cents",
            "current_price_cents",
            "markdown_sequence",
            "lifecycle_state",
            "inventory_state",
            "tag_code",
            "listed_at",
            "days_on_floor",
            "election_round",
            "election_deadline_at",
            "disposition_election",
            "unsold_trigger_day_effective",
            "clearance_relocation_pending",
            "lot_component_count",
            "lot_ready",
            "screened_by_user_id",
            "received_by_user_id",
        ),
    )
    assert entity["category"] in (
        "SOFA",
        "DINING",
        "CASEGOOD",
        "RUG",
        "ART",
        "OUTDOOR",
    ), entity["category"]
    assert entity["inventory_state"] in (
        "PENDING_CUSTODY",
        "IN_CUSTODY",
        "SHRINKAGE_MISSING",
        "WRITTEN_OFF_INV",
        "RELEASED",
    ), entity["inventory_state"]
    assert entity["disposition_election"] in (
        "NONE",
        "DONATE",
        "RETURN",
        "DISCOUNT",
    ), entity["disposition_election"]


def assert_truck(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, ("name", "capacity_volume_cuft", "status"))
    assert entity["status"] in ("AVAILABLE", "MAINTENANCE"), entity["status"]


def assert_crew(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, ("name", "max_concurrent_jobs", "status"))
    assert entity["status"] in ("AVAILABLE", "OFF_DUTY"), entity["status"]


def assert_floor_zone(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(
        entity,
        (
            "name",
            "zone_type",
            "capacity_sqft",
            "occupied_sqft",
            "utilization_state",
            "status",
        ),
    )
    assert entity["zone_type"] in (
        "SHOWROOM_FRONT",
        "SHOWROOM_REAR",
        "WAREHOUSE",
        "CLEARANCE",
    ), entity["zone_type"]
    assert entity["status"] in ("OPEN", "CLOSED"), entity["status"]
    assert_utilization_band(entity)


def assert_pickup_job(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(
        entity,
        (
            "consignor_id",
            "truck_id",
            "window_start",
            "window_end",
            "crew_size",
            "item_count",
            "total_volume_cuft",
            "declared_stair_flights",
            "declared_elevator",
            "quoted_surcharge_cents",
            "actual_stair_flights",
            "actual_elevator_used",
            "actual_crew_size",
            "final_surcharge_cents",
            "surcharge_variance_cents",
            "status",
            "scheduled_by_user_id",
        ),
    )
    assert entity["status"] in (
        "SCHEDULED",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    ), entity["status"]


def assert_sale(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(
        entity,
        (
            "item_id",
            "buyer_id",
            "sale_price_cents",
            "markdown_sequence_at_sale",
            "split_pct_applied",
            "consignor_share_cents",
            "gallery_share_cents",
            "refund_cents",
            "status",
            "sold_at",
            "reversed_at",
            "sold_by_user_id",
        ),
    )
    assert entity["status"] in ("COMPLETED", "SETTLED", "REVERSED"), entity["status"]
    assert_split_shares_readd(entity)


def assert_delivery_order(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(
        entity,
        (
            "sale_id",
            "crew_id",
            "window_start",
            "window_end",
            "stair_flights",
            "elevator_used",
            "delivery_fee_cents",
            "status",
            "outcome_recorded_at",
            "claim_window_ends_at",
            "scheduled_by_user_id",
        ),
    )
    assert entity["status"] in (
        "SCHEDULED",
        "DELIVERED",
        "REFUSED",
        "CANCELLED",
    ), entity["status"]


def assert_damage_claim(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(
        entity,
        (
            "delivery_order_id",
            "claim_amount_cents",
            "description",
            "status",
            "resubmission_count",
            "fault_party",
            "adjudicated_amount_cents",
            "gallery_absorbed_cents",
            "consignor_debited_cents",
            "info_request_note",
            "adjudicated_by_user_id",
        ),
    )
    assert entity["status"] in (
        "SUBMITTED",
        "INFO_REQUESTED",
        "APPROVED",
        "DENIED",
        "WITHDRAWN",
    ), entity["status"]


def assert_shrinkage_audit(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    assert_fields_present(
        entity,
        (
            "floor_zone_id",
            "counted_item_ids",
            "expected_item_count",
            "counted_item_count",
            "variance_count",
            "missing_item_ids",
            "write_off_total_cents",
            "status",
            "counted_by_user_id",
            "approved_by_user_id",
        ),
    )
    assert entity["status"] in ("COUNTED", "RECONCILED", "ABANDONED"), entity["status"]
    assert isinstance(entity["counted_item_ids"], list)
    assert isinstance(entity["missing_item_ids"], list)
    assert (
        entity["expected_item_count"] - entity["counted_item_count"]
        == entity["variance_count"]
    ), "variance_count must be expected minus counted"


def assert_ledger_entry(entity: Dict[str, Any]) -> None:
    assert_append_only_row(entity)
    assert_fields_present(
        entity,
        (
            "consignor_id",
            "item_id",
            "entry_type",
            "amount_cents",
            "withholding_cents",
            "processing_fee_cents",
            "net_payout_cents",
            "balance_after_cents",
            "memo",
            "effective_at",
        ),
    )
    assert entity["entry_type"] in (
        "SALE_CREDIT",
        "SALE_REVERSAL_DEBIT",
        "SHRINKAGE_CREDIT",
        "SHRINKAGE_RECOVERY_DEBIT",
        "PICKUP_SURCHARGE_DEBIT",
        "DAMAGE_ALLOCATION_DEBIT",
        "DISPOSAL_FEE_DEBIT",
        "PAYOUT_DISBURSEMENT_DEBIT",
        "ESCHEATMENT_DEBIT",
    ), entity["entry_type"]
    assert is_iso8601_timestamp(entity["effective_at"]), entity["effective_at"]
    if entity["entry_type"] != "PAYOUT_DISBURSEMENT_DEBIT":
        assert_null_columns(
            entity, ("withholding_cents", "processing_fee_cents", "net_payout_cents")
        )


# --- Invariants -------------------------------------------------------------

def assert_split_shares_readd(sale: Dict[str, Any]) -> None:
    """The gallery's cut is the exact remainder, so the two shares re-add."""
    assert (
        sale["consignor_share_cents"] + sale["gallery_share_cents"]
        == sale["sale_price_cents"]
    ), (
        f"{sale['consignor_share_cents']} + {sale['gallery_share_cents']} "
        f"!= {sale['sale_price_cents']}"
    )
    assert (
        SPLIT_PCT_FLOOR <= float(sale["split_pct_applied"]) <= SPLIT_PCT_CEILING
    ), sale["split_pct_applied"]


def assert_utilization_band(zone: Dict[str, Any]) -> None:
    """utilization_state must agree with occupied_sqft / capacity_sqft."""
    ratio = zone["occupied_sqft"] / zone["capacity_sqft"]
    if ratio >= UTILIZATION_BANDS["FULL_AT_OR_ABOVE"]:
        expected = "FULL"
    elif ratio >= UTILIZATION_BANDS["TIGHT_AT_OR_ABOVE"]:
        expected = "TIGHT"
    else:
        expected = "NORMAL"
    assert zone["utilization_state"] == expected, (
        f"{zone['occupied_sqft']}/{zone['capacity_sqft']} implies {expected}, "
        f"got {zone['utilization_state']}"
    )


def assert_zone_occupancy(zone: Dict[str, Any], expected_sqft: int) -> None:
    assert zone["occupied_sqft"] == expected_sqft, (
        f"expected occupied_sqft {expected_sqft}, got {zone['occupied_sqft']}"
    )
    assert_utilization_band(zone)


def assert_ledger_balance_chain(entries: List[Dict[str, Any]]) -> None:
    """balance_after_cents on each entry is the running sum of amount_cents."""
    running = 0
    for entry in entries:
        running += entry["amount_cents"]
        assert entry["balance_after_cents"] == running, (
            f"entry {entry['entry_type']} claims balance {entry['balance_after_cents']} "
            f"but running sum is {running}"
        )


def assert_entry_types(entries: List[Dict[str, Any]], expected: List[str]) -> None:
    actual = [e["entry_type"] for e in entries]
    assert actual == expected, f"expected entry types {expected}, got {actual}"


def assert_payout_entry(
    entry: Dict[str, Any],
    amount_cents: int,
    withholding_cents: int,
    processing_fee_cents: int,
    net_payout_cents: int,
) -> None:
    assert entry["entry_type"] == "PAYOUT_DISBURSEMENT_DEBIT", entry["entry_type"]
    assert entry["amount_cents"] == amount_cents, entry["amount_cents"]
    assert entry["withholding_cents"] == withholding_cents, entry["withholding_cents"]
    assert entry["processing_fee_cents"] == processing_fee_cents, entry[
        "processing_fee_cents"
    ]
    assert entry["net_payout_cents"] == net_payout_cents, entry["net_payout_cents"]


def assert_item_dimensions(
    item: Dict[str, Any], lifecycle_state: str, inventory_state: str
) -> None:
    """The merchandising and custody dimensions are asserted independently."""
    assert item["lifecycle_state"] == lifecycle_state, (
        f"expected lifecycle_state {lifecycle_state}, got {item['lifecycle_state']}"
    )
    assert item["inventory_state"] == inventory_state, (
        f"expected inventory_state {inventory_state}, got {item['inventory_state']}"
    )


def assert_prices(
    item: Dict[str, Any],
    list_price_cents: Optional[int] = None,
    current_price_cents: Optional[int] = None,
    condition_grade: Optional[str] = None,
    photo_score: Optional[float] = None,
) -> None:
    if condition_grade is not None:
        assert item["condition_grade"] == condition_grade, item["condition_grade"]
    if photo_score is not None:
        assert float(item["photo_score"]) == photo_score, item["photo_score"]
    if list_price_cents is not None:
        assert item["list_price_cents"] == list_price_cents, item["list_price_cents"]
    if current_price_cents is not None:
        assert item["current_price_cents"] == current_price_cents, item[
            "current_price_cents"
        ]


def assert_clearance_candidate(item: Dict[str, Any]) -> None:
    """A piece priced under the clearance threshold is a relocation candidate."""
    assert item["current_price_cents"] < CLEARANCE_PRICE_THRESHOLD_CENTS, item[
        "current_price_cents"
    ]


def assert_ordered_by(rows: List[Dict[str, Any]], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), f"{field} not ascending: {values}"
