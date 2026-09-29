"""Entity assertions and domain invariant checkers for the LTL API."""

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import CLASS_CODES

# --------------------------------------------------------------------------
# Shared structural helpers
# --------------------------------------------------------------------------


def assert_identity_fields(data: dict) -> None:
    """Every resource is addressed by a server-minted UUID with no type prefix
    and carries an ISO 8601 UTC `created_at` with three fractional digits."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert "_" not in str(data.get("id", "")), "id must carry no type prefix"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_mutable_resource_fields(data: dict) -> None:
    """Resources that are mutated over their life also carry `updated_at` and an
    integer `version`."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_append_only_resource_fields(data: dict) -> None:
    """Append-only records carry only `id` and `created_at`; both `updated_at`
    and `version` are absent from the response entirely."""
    assert_identity_fields(data)
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"


def assert_recognized_class_code(value) -> None:
    assert value in CLASS_CODES, f"{value} is not one of the eighteen recognized codes"


def assert_two_decimal_places(value, label: str = "value") -> None:
    assert value == pytest.approx(round(float(value), 2)), (
        f"{label} must be rounded to two decimal places, got {value}"
    )


def assert_four_decimal_places(value, label: str = "value") -> None:
    assert value == pytest.approx(round(float(value), 4)), (
        f"{label} must carry four decimal places, got {value}"
    )


def assert_integer_cents(value, label: str = "amount") -> None:
    assert isinstance(value, int), f"{label} must be an integer number of cents, got {value!r}"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------


def assert_terminal(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert isinstance(data["code"], str) and 3 <= len(data["code"]) <= 10
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["calibration_interval_captures"], int)
    assert data["calibration_interval_captures"] >= 1
    assert isinstance(data["captures_since_calibration"], int)
    assert data["dimensioner_status"] in ("CALIBRATED", "OUT_OF_CALIBRATION")
    if data["captures_since_calibration"] < data["calibration_interval_captures"]:
        assert data["dimensioner_status"] == "CALIBRATED"
    else:
        assert data["dimensioner_status"] == "OUT_OF_CALIBRATION"


def assert_customer(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert isinstance(data["account_code"], str) and len(data["account_code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["billing_posture"] in ("OPEN", "CREDIT_HOLD", "CLOSED")
    assert data["education_status"] in ("NONE", "REQUIRED", "COMPLETED")
    assert isinstance(data["education_strike_interval"], int)
    assert data["education_strike_interval"] >= 1
    assert isinstance(data["education_threshold_strikes"], int)
    assert isinstance(data["offender_strike_count"], int)
    assert data["offender_strike_count"] >= 0
    assert_two_decimal_places(data["liability_index_rolling"], "liability_index_rolling")
    assert_two_decimal_places(data["liability_index_lifetime"], "liability_index_lifetime")
    assert data["offender_tier"] in ("TIER_0", "TIER_1", "TIER_2", "TIER_3")
    assert data["dispute_window_days"] in (30, 25, 20, 15)
    assert data["active_program_type"] in (None, "CLASS_BASED", "DENSITY_BASED", "FAK")


def assert_customer_offender_record(data: dict) -> None:
    """The tier reads the already-rounded rolling index alone, and the window is
    30 days less 5 days per tier step above zero."""
    rolling = data["liability_index_rolling"]
    if rolling >= 6.00:
        expected_tier = "TIER_3"
    elif rolling >= 3.00:
        expected_tier = "TIER_2"
    elif rolling >= 1.00:
        expected_tier = "TIER_1"
    else:
        expected_tier = "TIER_0"
    assert data["offender_tier"] == expected_tier, (
        f"rolling index {rolling} implies {expected_tier}, got {data['offender_tier']}"
    )
    expected_window = {"TIER_0": 30, "TIER_1": 25, "TIER_2": 20, "TIER_3": 15}[expected_tier]
    assert data["dispute_window_days"] == expected_window


def assert_tariff_version(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert is_iso8601_timestamp(data["effective_at"])
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    breaks = data["density_breaks"]
    assert isinstance(breaks, list) and len(breaks) >= 1
    previous = None
    for row in breaks:
        assert_recognized_class_code(row["class_code"])
        if previous is not None:
            assert row["min_density_pcf"] < previous, "density_breaks must be strictly descending"
        previous = row["min_density_pcf"]
    assert breaks[-1]["min_density_pcf"] == 0, "density_breaks must terminate at exactly 0"
    if data["status"] == "DRAFT":
        assert data["published_at"] is None
        assert data["superseded_by_tariff_version_id"] is None


def assert_commodity_profile(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert data["classification_basis"] in ("DENSITY_BASED", "FIXED_CLASS")
    assert data["handling_code"] in ("STANDARD", "FRAGILE", "HAZMAT", "OVERLENGTH")
    assert data["stowability_code"] in ("STACKABLE", "NON_STACKABLE", "HAZ_SEGREGATED")
    assert data["liability_code"] in ("LOW", "MEDIUM", "HIGH")
    if data["classification_basis"] == "FIXED_CLASS":
        assert_recognized_class_code(data["fixed_class_code"])
    else:
        assert data["fixed_class_code"] is None


def assert_rate_program(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert data["program_type"] in ("CLASS_BASED", "DENSITY_BASED", "FAK")
    assert data["status"] in ("MODELING", "APPROVED", "ACTIVE", "RETIRED")
    assert isinstance(data["base_rate_per_cwt_cents"], int)
    assert data["base_rate_per_cwt_cents"] >= 1
    assert 0 <= data["discount_pct"] <= 0.75
    assert_four_decimal_places(data["discount_pct"], "discount_pct")
    assert_integer_cents(data["min_charge_cents"], "min_charge_cents")
    assert_integer_cents(data["baseline_revenue_cents"], "baseline_revenue_cents")
    assert_integer_cents(
        data["modeled_annual_revenue_cents"], "modeled_annual_revenue_cents"
    )
    assert_four_decimal_places(data["modeled_delta_pct"], "modeled_delta_pct")
    assert data["migration_recommendation"] in (
        None, "MIGRATE_DENSITY_BASED", "HOLD_CLASS_BASED", "NEGOTIATE_FAK",
    )
    if data["program_type"] == "FAK":
        assert_recognized_class_code(data["fak_class_code"])
    else:
        assert data["fak_class_code"] is None


def assert_exception_agreement(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert data["agreement_type"] in ("EXCEPTION_CLASS", "FAK")
    assert_recognized_class_code(data["agreed_class_code"])
    assert data["status"] in ("PENDING", "ACTIVE", "EXPIRED")
    assert data["effective_to"] > data["effective_from"], (
        "effective_to must be strictly after effective_from"
    )
    if data["status"] == "PENDING":
        assert data["approved_by_user_id"] is None
        assert data["approved_at"] is None


def assert_shipment(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert data["class_status"] in (
        "DECLARED", "CAPTURED", "UNDER_INSPECTION",
        "RECLASS_PENDING", "RECLASSED", "CLASS_CONFIRMED",
    )
    assert data["billing_status"] in (
        "UNBILLED", "BILLED", "REBILLED", "CREDITED", "CLOSED",
    )
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    assert isinstance(data["declared_total_weight_lb"], int)
    assert isinstance(data["reweigh_required"], bool)
    assert isinstance(data["declared_vs_found_class_delta_count"], int)
    assert_integer_cents(data["original_charge_cents"], "original_charge_cents")
    assert_integer_cents(data["assessed_total_cents"], "assessed_total_cents")
    assert isinstance(data["open_notice_count"], int) and data["open_notice_count"] >= 0
    if data["weight_variance_pct"] is not None:
        assert_two_decimal_places(data["weight_variance_pct"], "weight_variance_pct")
    if data["billing_status"] == "UNBILLED":
        assert data["billed_at"] is None


def assert_shipment_line(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert isinstance(data["line_no"], int) and data["line_no"] >= 1
    assert_recognized_class_code(data["declared_class_code"])
    assert isinstance(data["declared_weight_lb"], int) and data["declared_weight_lb"] >= 1
    assert isinstance(data["pieces"], int) and data["pieces"] >= 1
    assert_two_decimal_places(data["declared_cubic_ft"], "declared_cubic_ft")
    assert_two_decimal_places(data["declared_density_pcf"], "declared_density_pcf")
    assert_recognized_class_code(data["effective_class_code"])
    assert data["classification_source"] in (
        "BOL_DECLARED", "FIXED_CLASS", "DIMENSIONER",
        "INSPECTION", "EXCEPTION_AGREEMENT", "FAK",
    )
    assert isinstance(data["class_floor_applied"], bool)
    assert_integer_cents(data["line_charge_cents"], "line_charge_cents")
    if data["found_class_code"] is not None:
        assert_recognized_class_code(data["found_class_code"])
        assert data["effective_class_code"] >= data["found_class_code"]
    if data["measured_cubic_ft"] is not None:
        assert_two_decimal_places(data["measured_cubic_ft"], "measured_cubic_ft")
    if data["measured_density_pcf"] is not None:
        assert_two_decimal_places(data["measured_density_pcf"], "measured_density_pcf")


def assert_capture_event(data: dict) -> None:
    assert_append_only_resource_fields(data)
    assert data["device_type"] in ("DIMENSIONER", "SCALE", "COMBINED")
    assert isinstance(data["measured_total_weight_lb"], int)
    assert data["measured_total_weight_lb"] >= 1
    assert isinstance(data["capture_sequence"], int) and data["capture_sequence"] >= 1
    assert_two_decimal_places(data["variance_pct"], "variance_pct")
    assert isinstance(data["triggered_reweigh"], bool)
    assert isinstance(data["triggered_reclass"], bool)
    assert isinstance(data["reclassed_line_count"], int)
    assert is_iso8601_timestamp(data["captured_at"])
    assert data["terminal_id"] == data["captured_by_user_id"], (
        "terminal_id and captured_by_user_id are both taken from the operator's X-User-ID"
    )


def assert_inspection_finding(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert data["finding_basis"] in (
        "DENSITY", "STOWABILITY", "HANDLING", "LIABILITY", "COMMODITY_MISMATCH",
    )
    assert_recognized_class_code(data["found_class_code"])
    assert isinstance(data["evidence_photo_count"], int)
    assert data["evidence_photo_count"] >= 0
    assert data["status"] in ("RECORDED", "ACCEPTED", "SUPERSEDED")
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]
    if data["finding_basis"] == "COMMODITY_MISMATCH":
        assert data["found_commodity_profile_id"] is not None
    else:
        assert data["found_commodity_profile_id"] is None
    if data["status"] == "RECORDED":
        assert data["accepted_by_user_id"] is None
        assert data["accepted_at"] is None


def assert_correction_notice(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert data["notice_type"] in ("REWEIGH", "RECLASS", "BOTH")
    assert data["origin"] in ("AUTOMATED_CAPTURE", "AUDITOR_MANUAL")
    assert data["status"] in (
        "DRAFT", "ISSUED", "DISPUTED", "EVIDENCE_REQUESTED",
        "UPHELD", "PARTIALLY_OVERTURNED", "OVERTURNED", "VOID",
    )
    assert_integer_cents(data["provisional_delta_cents"], "provisional_delta_cents")
    assert_integer_cents(data["final_delta_cents"], "final_delta_cents")
    assert_integer_cents(data["applied_delta_cents"], "applied_delta_cents")
    assert_integer_cents(data["inspection_fee_cents"], "inspection_fee_cents")
    assert isinstance(data["evidence_bundle_count"], int)
    assert isinstance(data["uses_inspection_findings"], bool)
    assert isinstance(data["dispute_round_count"], int)
    assert isinstance(data["supplement_request_count"], int)
    assert data["supplement_request_count"] <= 2
    assert data["dispute_round_count"] <= 3
    if data["status"] in ("DRAFT", "VOID"):
        assert data["issued_at"] is None, "issued_at is null while a notice is DRAFT or VOID"
        assert data["dispute_deadline_at"] is None, (
            "dispute_deadline_at is null while a notice is DRAFT or VOID"
        )
        assert data["applied_delta_cents"] == 0
        assert data["inspection_fee_cents"] == 0


def assert_dispute(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert data["claim_basis"] in (
        "DENSITY_RECOMPUTE", "EXCEPTION_AGREEMENT",
        "DEVICE_CALIBRATION", "EVIDENCE_INSUFFICIENT",
    )
    assert isinstance(data["evidence_doc_count"], int) and data["evidence_doc_count"] >= 1
    assert data["status"] in ("OPEN", "SUPPLEMENT_REQUESTED", "SUPPLEMENTED", "RESOLVED")
    assert isinstance(data["round_no"], int) and data["round_no"] >= 1
    assert data["outcome"] in (None, "UPHELD_CARRIER", "PARTIAL", "OVERTURNED")
    assert is_iso8601_timestamp(data["filed_at"])
    if data["status"] != "RESOLVED":
        assert data["outcome"] is None
        assert data["resolved_at"] is None
    if data["claimed_class_code"] is not None:
        assert_recognized_class_code(data["claimed_class_code"])


def assert_credit_memo(data: dict) -> None:
    assert_append_only_resource_fields(data)
    assert data["reason"] in ("FULL_OVERTURN", "PARTIAL_OVERTURN")
    assert_integer_cents(data["freight_credit_cents"], "freight_credit_cents")
    assert_integer_cents(data["fee_credit_cents"], "fee_credit_cents")
    assert_integer_cents(data["interest_credit_cents"], "interest_credit_cents")
    assert_integer_cents(data["amount_cents"], "amount_cents")
    assert data["interest_credit_cents"] <= 250, "interest is capped at $2.50"
    assert data["amount_cents"] == (
        data["freight_credit_cents"]
        + data["fee_credit_cents"]
        + data["interest_credit_cents"]
    ), "amount_cents is the three buckets added together"
    assert is_iso8601_timestamp(data["issued_at"])


def assert_repricing_run(data: dict) -> None:
    assert_mutable_resource_fields(data)
    assert data["scope"] in ("ALL_CLASS_BASED", "ALL_DENSITY_BASED", "ALL_ACTIVE")
    assert data["status"] in ("DRAFT", "MODELED", "COMMITTED")
    assert isinstance(data["impacted_customer_count"], int)
    assert_integer_cents(data["aggregate_delta_cents"], "aggregate_delta_cents")
    assert data["sample_window_end_at"] > data["sample_window_start_at"]
    if data["status"] == "DRAFT":
        assert data["modeled_at"] is None
        assert data["committed_at"] is None


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------

LEDGER_CONTRIBUTING_STATUSES = (
    "ISSUED", "DISPUTED", "EVIDENCE_REQUESTED",
    "UPHELD", "PARTIALLY_OVERTURNED", "OVERTURNED",
)

STRIKE_CONTRIBUTING_STATUSES = (
    "ISSUED", "DISPUTED", "EVIDENCE_REQUESTED", "UPHELD", "PARTIALLY_OVERTURNED",
)


def assert_shipment_ledger_identity(shipment: dict, notices: list, memos: list) -> None:
    """`assessed_total_cents` equals `original_charge_cents` plus the frozen
    amounts of the contributing notices minus the freight and fee buckets of
    their credit memos.  `interest_credit_cents` is excluded on purpose."""
    contributing_ids = {
        n["id"] for n in notices if n["status"] in LEDGER_CONTRIBUTING_STATUSES
    }
    notice_sum = sum(
        n["applied_delta_cents"] + n["inspection_fee_cents"]
        for n in notices
        if n["id"] in contributing_ids
    )
    memo_sum = sum(
        m["freight_credit_cents"] + m["fee_credit_cents"]
        for m in memos
        if m["correction_notice_id"] in contributing_ids
    )
    expected = shipment["original_charge_cents"] + notice_sum - memo_sum
    assert shipment["assessed_total_cents"] == expected, (
        f"ledger identity broken: original {shipment['original_charge_cents']} "
        f"+ notices {notice_sum} - credits {memo_sum} = {expected}, "
        f"but assessed_total_cents is {shipment['assessed_total_cents']}"
    )


def assert_strike_count_conserved(customer: dict, notices: list) -> None:
    """`offender_strike_count` always equals the number of correction notices
    against that shipper's shipments in a strike-contributing status."""
    expected = len(
        [n for n in notices if n["status"] in STRIKE_CONTRIBUTING_STATUSES]
    )
    assert customer["offender_strike_count"] == expected, (
        f"expected offender_strike_count {expected} from the notice population, "
        f"got {customer['offender_strike_count']}"
    )


def assert_status_dimensions_independent(
    shipment: dict, expected_class_status: str, expected_billing_status: str
) -> None:
    assert shipment["class_status"] == expected_class_status, (
        f"expected class_status {expected_class_status}, got {shipment['class_status']}"
    )
    assert shipment["billing_status"] == expected_billing_status, (
        f"expected billing_status {expected_billing_status}, "
        f"got {shipment['billing_status']}"
    )
