"""Entity assertions, timestamp canonicalisation and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CONDITION_GRADES = ["A", "B", "C", "D"]

# --- timestamp handling (PRD §2.4) ----------------------------------------


def canonical_instant(value: str) -> str:
    """Reduce an ISO-8601 UTC timestamp to a comparable canonical form.

    PRD §2.4 requires every timestamp to be rendered with exactly three
    fractional-second digits, so ``2026-08-22T00:00:00.000Z`` is the wire form of
    the instant that the PRD's own prose writes as ``2026-08-22T00:00:00Z``.
    This helper strips a zero fractional part so that the two spellings of one
    instant compare equal; a non-zero fractional part is preserved.
    """
    assert isinstance(value, str), f"expected an ISO-8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = frac.rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return f"{text}Z"


def assert_instant(actual: str, expected: str, label: str = "timestamp") -> None:
    """Assert an emitted timestamp denotes exactly the expected instant."""
    assert is_iso8601_timestamp(actual), (
        f"{label} must be an ISO 8601 UTC timestamp, got {actual!r}"
    )
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_millisecond_precision(value: str, label: str = "timestamp") -> None:
    """PRD §2.4: timestamps carry exactly three fractional-second digits."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"{label} must end in 'Z', got {value!r}"
    )
    assert len(value) == 24 and value[19] == "." and value[20:23].isdigit(), (
        f"{label} must carry exactly three fractional-second digits, got {value!r}"
    )


# --- common field shapes (PRD §2.4) ---------------------------------------


def assert_common_fields(data: dict) -> None:
    """PRD §2.4: a UUID ``id`` with no prefix, ``created_at``, ``updated_at`` and
    an integer ``version`` that starts at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict) -> None:
    """PRD §2.4: a ``TrialAbuseSignal`` carries only ``id`` and ``created_at``."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "a TrialAbuseSignal must not carry updated_at"
    assert "version" not in data, "a TrialAbuseSignal must not carry version"


# --- entity assertions ----------------------------------------------------


def assert_mattress_model(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"].strip()
    assert isinstance(data["name"], str)
    assert data["firmness"] in ["SOFT", "MEDIUM", "FIRM"]
    assert data["size"] in ["TWIN", "QUEEN", "KING"]
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["break_in_nights"], int) and data["break_in_nights"] >= 0
    assert isinstance(data["trial_nights"], int)
    assert data["trial_nights"] > data["break_in_nights"], (
        "trial_nights must exceed break_in_nights"
    )
    assert float(data["indentation_warranty_threshold_mm"]) > 0
    assert isinstance(data["warranty_years"], int) and data["warranty_years"] > 0
    assert isinstance(data["donation_eligible"], bool)


def assert_promotion_bundle(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"].strip()
    assert data["unwind_policy"] in ["DEDUCT_RETAIL", "DEDUCT_PRORATED", "FORFEIT_NONE"]
    assert isinstance(data["accessory_retail_cents"], int) and data["accessory_retail_cents"] >= 0
    assert isinstance(data["percent_off_bps"], int) and 0 <= data["percent_off_bps"] <= 5000
    assert isinstance(data["gift_card_cents"], int) and data["gift_card_cents"] >= 0
    assert isinstance(data["requires_accessory_return"], bool)


def assert_retail_partner(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["region_code"], str) and data["region_code"].strip()
    assert isinstance(data["commission_bps"], int) and 0 <= data["commission_bps"] <= 3000
    assert data["price_match_policy"] in [
        "MATCH_TO_LOWEST", "MATCH_TO_ADVERTISED", "NO_MATCH",
    ]
    assert isinstance(data["attribution_window_days"], int) and data["attribution_window_days"] > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_disposition_partner(data: dict) -> None:
    assert_common_fields(data)
    assert data["partner_type"] in ["CHARITY", "RECYCLER"]
    assert isinstance(data["region_code"], str) and data["region_code"].strip()
    assert isinstance(data["daily_intake_capacity_units"], int)
    assert data["daily_intake_capacity_units"] > 0
    grades = data["accepts_condition_grades"]
    assert isinstance(grades, list) and grades
    assert all(g in CONDITION_GRADES for g in grades)
    assert data["soil_policy"] in ["REJECT_SOILED", "ACCEPT_SOILED"]
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1
    assert isinstance(data["recycle_fee_cents_per_unit"], int)
    assert data["recycle_fee_cents_per_unit"] >= 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_customer(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["household_hash"], str) and data["household_hash"].strip()
    assert data["status"] in ["ACTIVE", "TRIAL_RESTRICTED", "BLOCKED"]
    assert isinstance(data["lifetime_trial_count"], int) and data["lifetime_trial_count"] >= 0
    assert isinstance(data["completed_return_count"], int)
    assert 0 <= data["abuse_score_rolling"] <= 100
    assert 0 <= data["abuse_score_lifetime"] <= 100
    assert isinstance(data["signal_count"], int) and data["signal_count"] >= 0


def assert_trial_order(data: dict) -> None:
    assert_common_fields(data)
    assert data["channel"] in ["DTC", "RETAIL_PARTNER"]
    assert data["fulfillment_status"] in [
        "CREATED", "IN_TRANSIT", "DELIVERED", "DAMAGED_REPORTED", "REPLACED", "CLOSED",
    ]
    assert data["trial_status"] in [
        "NOT_STARTED", "BREAK_IN", "TRIAL_ACTIVE", "TRIAL_EXPIRED",
        "RETURN_REQUESTED", "RETURNED", "KEPT", "EXCHANGED",
    ]
    assert isinstance(data["gross_price_cents"], int) and data["gross_price_cents"] > 0
    assert isinstance(data["bundle_discount_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)
    assert isinstance(data["exchange_chain_depth"], int) and data["exchange_chain_depth"] >= 0
    assert_refund_ledger_identity(data)


def assert_return_case(data: dict) -> None:
    assert_common_fields(data)
    assert data["reason_code"] in ["COMFORT", "DAMAGE", "PRICE", "OTHER"]
    assert data["logistics_status"] in [
        "REQUESTED", "PICKUP_SCHEDULED", "PICKED_UP", "INSPECTED",
        "DISPOSITIONED", "CANCELLED",
    ]
    assert data["financial_status"] in ["PENDING", "AUTHORIZED", "RELEASED", "VOID"]
    assert data["disposition"] in ["PENDING", "DONATION", "RECYCLE"]
    assert is_iso8601_timestamp(data["requested_at"])


def assert_pickup_route(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "PUBLISHED"]
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] > 0
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert_route_capacity_identity(data)


def assert_pickup_appointment(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ["BOOKED", "COMPLETED", "MISSED", "CANCELLED"]
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert is_iso8601_timestamp(data["slot_start_at"])
    assert is_iso8601_timestamp(data["slot_end_at"])


def assert_disposition_assignment(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ["ASSIGNED", "DELIVERED", "REJECTED"]
    assert data["disposition_type"] in ["DONATION", "RECYCLE"]
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["fallback_applied"], bool)


def assert_refund_authorization(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ["AUTHORIZED", "RELEASED", "VOIDED"]
    for field in (
        "gross_refundable_cents", "proration_deduction_cents",
        "bundle_unwind_cents", "damage_offset_cents", "net_refund_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"


def assert_comfort_exchange(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ["REQUESTED", "APPROVED", "DECLINED"]
    assert data["settlement_direction"] in ["CHARGE_CUSTOMER", "CREDIT_CUSTOMER", "EVEN"]
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    for field in (
        "raw_price_difference_cents", "exchange_fee_cents",
        "tier_credit_cents", "price_difference_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"


def assert_quality_claim(data: dict) -> None:
    assert_common_fields(data)
    assert data["claim_type"] in [
        "SHIPPING_DAMAGE", "COMPRESSION_RECOVERY", "WARRANTY_INDENTATION",
    ]
    assert data["status"] in [
        "SUBMITTED", "EVIDENCE_REQUESTED", "APPROVED", "DENIED", "SETTLED", "WITHDRAWN",
    ]
    assert data["resolution"] in ["PENDING", "REPLACEMENT", "CREDIT", "DENIED"]
    assert isinstance(data["photo_evidence_count"], int)
    assert isinstance(data["evidence_round_count"], int)


def assert_attribution_claim(data: dict) -> None:
    assert_common_fields(data)
    assert data["claim_type"] in ["SALES_ATTRIBUTION", "PRICE_MATCH"]
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "REJECTED",
    ]
    assert isinstance(data["evidence_url_count"], int)
    assert isinstance(data["revision_round_count"], int)


def assert_trial_abuse_signal(data: dict) -> None:
    assert_append_only_fields(data)
    assert data["signal_type"] in [
        "REPEAT_RETURN", "HOUSEHOLD_MATCH", "SHORT_TRIAL", "MULTI_CHANNEL",
    ]
    assert isinstance(data["weight"], int) and data["weight"] > 0
    assert is_iso8601_timestamp(data["recorded_at"])


# --- conserved-quantity invariants ---------------------------------------


def assert_refund_ledger_identity(order: dict) -> None:
    """PRD §2.9: ``paid_amount_cents`` always equals ``refunded_total_cents`` plus
    ``outstanding_refundable_cents`` plus ``retained_amount_cents``."""
    total = (
        order["refunded_total_cents"]
        + order["outstanding_refundable_cents"]
        + order["retained_amount_cents"]
    )
    assert order["paid_amount_cents"] == total, (
        "refund ledger identity broken: paid_amount_cents "
        f"{order['paid_amount_cents']} != refunded {order['refunded_total_cents']} "
        f"+ outstanding {order['outstanding_refundable_cents']} "
        f"+ retained {order['retained_amount_cents']}"
    )


def assert_route_capacity_identity(route: dict) -> None:
    """PRD §2.10: ``capacity_units`` always equals ``booked_units`` plus
    ``available_units``."""
    total = route["booked_units"] + route["available_units"]
    assert route["capacity_units"] == total, (
        "route capacity identity broken: capacity_units "
        f"{route['capacity_units']} != booked {route['booked_units']} "
        f"+ available {route['available_units']}"
    )


def assert_money_fields_are_integers(data: dict) -> None:
    """PRD §2.6: every monetary amount is an integer count of cents."""
    for key, value in data.items():
        if key.endswith("_cents") and value is not None:
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{key} must be an integer count of cents, got {value!r}"
            )
