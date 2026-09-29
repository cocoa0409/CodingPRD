"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------------------
# Shared property helpers (PRD §2.4)
# --------------------------------------------------------------------------
def assert_versioned_common_fields(data: dict, entity: str = "resource") -> None:
    """id + created_at + updated_at + version, as most resources carry."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_append_only_common_fields(data: dict, entity: str = "record") -> None:
    """Append-only records carry ONLY id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert (
        "updated_at" not in data
    ), f"{entity} is append-only and must not expose updated_at"
    assert "version" not in data, f"{entity} is append-only and must not expose version"


def assert_two_decimal_places(value, field: str) -> None:
    assert value is not None, f"{field} must be present"
    assert round(float(value), 2) == float(
        value
    ), f"{field} must carry at most 2 decimal places, got {value}"


def assert_one_decimal_place(value, field: str) -> None:
    assert value is not None, f"{field} must be present"
    assert round(float(value), 1) == float(
        value
    ), f"{field} must carry at most 1 decimal place, got {value}"


def assert_whole_cents(value, field: str) -> None:
    assert isinstance(
        value, int
    ), f"{field} must be an integer number of whole cents, got {value!r}"


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------
def assert_community(data: dict) -> None:
    assert_versioned_common_fields(data, "community")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["care_levels_offered"], list) and data["care_levels_offered"]
    for level in data["care_levels_offered"]:
        assert level in [
            "INDEPENDENT_LIVING",
            "ASSISTED_LIVING",
            "MEMORY_CARE",
            "SKILLED_NURSING",
        ]
    assert_whole_cents(
        data["guest_meal_sponsor_cap_cents"], "guest_meal_sponsor_cap_cents"
    )
    assert_whole_cents(data["variance_tolerance_cents"], "variance_tolerance_cents")
    assert isinstance(data["pending_dietitian_review_count"], int)
    assert data["pending_dietitian_review_count"] >= 0
    assert data["active_menu_cycle_id"] is None or is_valid_uuid(
        data["active_menu_cycle_id"]
    )


def assert_dining_venue(data: dict) -> None:
    assert_versioned_common_fields(data, "venue")
    assert is_valid_uuid(data["community_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["venue_kind"] in ["MAIN_DINING", "BISTRO", "SATELLITE"]
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["care_levels_served"], list) and data["care_levels_served"]
    assert isinstance(data["seating_turn_minutes"], int)
    assert data["seating_turn_minutes"] >= 15
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert data["turnover_buffer_minutes"] >= 0
    assert data["temp_compliance_posture"] in ["COMPLIANT", "WATCH", "SUSPENDED"]
    assert isinstance(data["consecutive_temp_violation_count"], int)
    assert data["consecutive_temp_violation_count"] >= 0
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_resident(data: dict) -> None:
    assert_versioned_common_fields(data, "resident")
    assert is_valid_uuid(data["community_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["care_level"] in [
        "INDEPENDENT_LIVING",
        "ASSISTED_LIVING",
        "MEMORY_CARE",
        "SKILLED_NURSING",
    ]
    assert_one_decimal_place(data["baseline_weight_kg"], "baseline_weight_kg")
    assert float(data["baseline_weight_kg"]) > 0
    assert isinstance(data["allergens"], list)
    assert isinstance(data["dislikes"], list)
    assert data["preference_strictness"] in ["STRICT", "FLEXIBLE"]
    assert data["dining_status"] in ["ACTIVE", "ON_LEAVE", "DISCHARGED"]
    assert data["tray_card_state"] in ["CLEAR", "HOLD_PENDING_REVIEW", "BLOCKED"]
    assert_one_decimal_place(data["current_weight_kg"], "current_weight_kg")
    assert_whole_cents(
        data["guest_meal_charge_balance_cents"], "guest_meal_charge_balance_cents"
    )
    assert_two_decimal_places(
        data["rolling_30d_weight_change_pct"], "rolling_30d_weight_change_pct"
    )
    assert_two_decimal_places(
        data["baseline_weight_change_pct"], "baseline_weight_change_pct"
    )
    assert_two_decimal_places(data["intake_risk_score"], "intake_risk_score")
    assert 0.00 <= float(data["intake_risk_score"]) <= 100.00
    if data["avg_intake_pct_7d"] is not None:
        assert_two_decimal_places(data["avg_intake_pct_7d"], "avg_intake_pct_7d")


def assert_diet_order(data: dict) -> None:
    assert_versioned_common_fields(data, "diet order")
    assert is_valid_uuid(data["resident_id"])
    assert data["texture_level"] in ["REGULAR", "BITE_SIZED", "MINCED_MOIST", "PUREED"]
    assert data["liquid_consistency"] in [
        "THIN",
        "SLIGHTLY_THICK",
        "MILDLY_THICK",
        "MODERATELY_THICK",
        "EXTREMELY_THICK",
    ]
    assert isinstance(data["therapeutic_codes"], list)
    assert data["clinical_status"] in [
        "PENDING_REVIEW",
        "ACTIVE",
        "SUPERSEDED",
        "DISCONTINUED",
    ]
    assert data["review_status"] in [
        "AWAITING_DIETITIAN",
        "CHANGES_REQUESTED",
        "APPROVED",
        "REREVIEW_REQUIRED",
    ]
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    assert isinstance(data["ordered_by_user_id"], str) and data["ordered_by_user_id"]
    if data.get("activated_at") is not None:
        assert is_iso8601_timestamp(data["activated_at"])


def assert_substitution_rule(data: dict) -> None:
    assert_versioned_common_fields(data, "substitution rule")
    assert is_valid_uuid(data["resident_id"])
    assert data["trigger_type"] in ["ALLERGEN", "TEXTURE", "DISLIKE"]
    assert isinstance(data["match_value"], str) and data["match_value"]
    assert isinstance(data["replacement_item_code"], str)
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_seating_reservation(data: dict) -> None:
    assert_versioned_common_fields(data, "reservation")
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["service_date"], str)
    assert data["meal_period"] in ["BREAKFAST", "LUNCH", "DINNER"]
    assert isinstance(data["seat_start_utc"], str) and data["seat_start_utc"]
    assert isinstance(data["seat_end_utc"], str) and data["seat_end_utc"]
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert data["status"] in [
        "RESERVED",
        "WAITLISTED",
        "SEATED",
        "COMPLETED",
        "RELEASED",
    ]
    assert isinstance(data["suspension_hold"], bool)


def assert_menu_cycle(data: dict) -> None:
    assert_versioned_common_fields(data, "menu cycle")
    assert is_valid_uuid(data["community_id"])
    assert isinstance(data["cycle_number"], int) and data["cycle_number"] >= 1
    assert isinstance(data["week_count"], int) and data["week_count"] >= 1
    assert data["status"] in [
        "DRAFT",
        "PENDING_DIETITIAN_SIGNOFF",
        "PUBLISHED",
        "REFRESH_PENDING",
        "ARCHIVED",
    ]
    assert isinstance(data["refresh_round"], int) and data["refresh_round"] >= 0
    assert_two_decimal_places(data["refresh_index"], "refresh_index")
    assert data["refresh_tier"] in ["QUORUM", "ADVISORY"]


def assert_menu_item(data: dict) -> None:
    assert_versioned_common_fields(data, "menu item")
    assert is_valid_uuid(data["menu_cycle_id"])
    assert isinstance(data["item_code"], str) and data["item_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["day_index"], int) and data["day_index"] >= 1
    assert data["meal_period"] in ["BREAKFAST", "LUNCH", "DINNER"]
    assert data["base_texture"] in ["REGULAR", "BITE_SIZED", "MINCED_MOIST", "PUREED"]
    assert isinstance(data["allergen_tags"], list)
    assert isinstance(data["required_therapeutic_codes"], list)
    assert data["extension_coverage_status"] in [
        "NOT_REQUIRED",
        "INCOMPLETE",
        "COMPLETE",
    ]


def assert_therapeutic_extension(data: dict) -> None:
    assert_versioned_common_fields(data, "therapeutic extension")
    assert is_valid_uuid(data["menu_item_id"])
    assert data["diet_code"] in [
        "CARB_CONTROLLED",
        "RENAL",
        "LOW_SODIUM",
        "HIGH_PROTEIN",
        "GLUTEN_FREE",
    ]
    assert data["review_status"] in [
        "DRAFT",
        "SUBMITTED",
        "CHANGES_REQUESTED",
        "APPROVED",
        "RETIRED",
    ]
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    assert isinstance(data["authored_by_user_id"], str) and data["authored_by_user_id"]


def assert_meal_ticket(data: dict) -> None:
    assert_versioned_common_fields(data, "meal ticket")
    assert is_valid_uuid(data["venue_id"])
    assert data["ticket_type"] in ["RESIDENT", "GUEST", "TAKEOUT"]
    assert data["meal_period"] in ["BREAKFAST", "LUNCH", "DINNER"]
    assert data["status"] in ["ISSUED", "SERVED", "BILLED", "VOIDED"]
    assert_whole_cents(data["billed_amount_cents"], "billed_amount_cents")
    assert_whole_cents(data["voided_amount_cents"], "voided_amount_cents")
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]


def assert_billing_reconciliation(data: dict) -> None:
    assert_versioned_common_fields(data, "reconciliation")
    assert is_valid_uuid(data["community_id"])
    assert data["status"] in ["RECONCILED", "FINALIZED"]
    for field in (
        "ticket_ledger_total_cents",
        "census_projection_total_cents",
        "variance_cents",
        "void_credit_cents",
        "pre_fee_base_cents",
        "administrative_fee_cents",
        "net_billable_total_cents",
    ):
        assert_whole_cents(data[field], field)
    for counts_field in ("ledger_meal_counts", "census_meal_counts"):
        counts = data[counts_field]
        assert isinstance(counts, dict), f"{counts_field} must be an object"
        for key in ("RESIDENT", "GUEST", "TAKEOUT"):
            assert key in counts, f"{counts_field} must always carry the {key} key"
            assert isinstance(counts[key], int)


def assert_plan_of_care_review(data: dict) -> None:
    assert_versioned_common_fields(data, "plan-of-care review")
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["trigger_observation_id"])
    assert data["trigger_reason"] in ["WEIGHT_LOSS_30D", "LOW_INTAKE_AVG", "COMBINED"]
    assert_two_decimal_places(data["risk_score_at_open"], "risk_score_at_open")
    assert data["status"] in ["OPEN", "COMPLETED"]
    assert data["outcome"] in [None, "NO_CHANGE", "DIET_ORDER_REREVIEW", "ESCALATED"]


def assert_intake_observation(data: dict) -> None:
    assert_append_only_common_fields(data, "intake observation")
    assert is_valid_uuid(data["resident_id"])
    assert isinstance(data["observation_date"], str)
    assert data["meal_period"] in ["BREAKFAST", "LUNCH", "DINNER"]
    assert 0 <= float(data["intake_pct"]) <= 100
    if data.get("weight_kg") is not None:
        assert_one_decimal_place(data["weight_kg"], "weight_kg")
        assert float(data["weight_kg"]) > 0
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_temperature_log(data: dict) -> None:
    assert_append_only_common_fields(data, "temperature log")
    assert is_valid_uuid(data["venue_id"])
    assert data["probe_point"] in ["HOT_HOLDING", "COLD_HOLDING", "REHEAT"]
    assert_one_decimal_place(data["temperature_f"], "temperature_f")
    assert isinstance(data["in_range"], bool)
    assert isinstance(data["violation_sequence_index"], int)
    assert is_iso8601_timestamp(data["logged_at_utc"])
    assert isinstance(data["logged_by_user_id"], str) and data["logged_by_user_id"]


def assert_committee_feedback(data: dict) -> None:
    assert_append_only_common_fields(data, "committee ballot")
    assert is_valid_uuid(data["menu_cycle_id"])
    assert is_valid_uuid(data["resident_id"])
    assert isinstance(data["menu_item_code"], str) and data["menu_item_code"]
    assert data["sentiment"] in ["POSITIVE", "NEUTRAL", "NEGATIVE"]
    assert data["vote_weight"] in (1, 2)
    assert data["status"] in ["SUBMITTED", "ACKNOWLEDGED"]


# --------------------------------------------------------------------------
# Computed reads
# --------------------------------------------------------------------------
def assert_tray_card(data: dict) -> None:
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["menu_cycle_id"])
    assert isinstance(data["day_index"], int) and data["day_index"] >= 1
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert isinstance(line["item_code"], str)
        assert isinstance(line["served_item_code"], str)
        assert line["reason"] in [
            "ALLERGEN_UNRESOLVED",
            "EXTENSION_PENDING",
            "NONE",
            "ALLERGEN_SUBSTITUTION",
            "TEXTURE_SUBSTITUTION",
            "DISLIKE_SUBSTITUTION",
        ]
    assert isinstance(data["blocked_item_codes"], list)
    assert data["blocked_item_codes"] == sorted(
        data["blocked_item_codes"]
    ), "blocked_item_codes must be in ascending item-code order"
    assert data["tray_status"] in ["CLEAR", "HOLD_PENDING_REVIEW", "BLOCKED"]
    if data["blocked_item_codes"]:
        assert (
            data["tray_status"] == "BLOCKED"
        ), "tray_status is BLOCKED whenever blocked_item_codes is non-empty"


def assert_seat_availability(data: dict) -> None:
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["seat_capacity"], int)
    assert isinstance(data["committed_seats"], int)
    assert isinstance(data["open_seats"], int)
    assert data["open_seats"] >= 0, "open_seats is floored at 0"
    assert isinstance(data["blocking_reservation_ids"], list)


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_reconciliation_waterfall(data: dict) -> None:
    """The fee waterfall's structural identities, as stated by the PRD."""
    assert (
        data["variance_cents"]
        == data["ticket_ledger_total_cents"] - data["census_projection_total_cents"]
    ), "variance_cents is the ledger total minus the census projection"
    assert data["pre_fee_base_cents"] == max(
        0, data["ticket_ledger_total_cents"] - data["void_credit_cents"]
    ), "pre_fee_base_cents is the gross ledger figure minus the void credit, floored at 0"
    assert (
        data["net_billable_total_cents"]
        == data["pre_fee_base_cents"] + data["administrative_fee_cents"]
    ), "net_billable_total_cents is the pre-fee base plus the administrative fee"


def assert_ticket_conservation(data: dict, original_amount: int) -> None:
    """A void moves the charge into voided_amount_cents and zeroes the live charge."""
    assert (
        data["billed_amount_cents"] + data["voided_amount_cents"] == original_amount
    ), (
        "billed_amount_cents + voided_amount_cents must conserve the amount originally "
        f"charged ({original_amount})"
    )
