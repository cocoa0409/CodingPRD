"""Shape assertions per entity plus the invariant and formula checkers.

The computation helpers re-implement the PRD's pinned rounding orders so a test
can state an expectation once and check it against the derived value.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import THRESHOLDS

# --- Rounding --------------------------------------------------------------


def round_half_up(value, places: int):
    """Round half up to ``places`` decimals, the only rounding mode in use."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def round_cents(value) -> int:
    """Round half up to whole cents; there are no fractional cents anywhere."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --- Common audit fields ---------------------------------------------------


def assert_common_fields(data: dict, *, versioned: bool = True) -> None:
    assert is_valid_uuid(data["id"]), f"id is not a uuid: {data['id']}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    if versioned:
        assert is_iso8601_timestamp(data["updated_at"]), data["updated_at"]
        assert isinstance(data["version"], int) and data["version"] >= 1, data["version"]


def assert_enrollment(data: dict) -> None:
    assert_common_fields(data)
    assert data["program_type"] in ("PRIVATE_FAMILY", "PUBLIC_DONATION")
    assert isinstance(data["primary_parent_name"], str) and data["primary_parent_name"]
    assert isinstance(data["expected_delivery_date"], str)
    assert isinstance(data["collection_site_code"], str)
    assert isinstance(data["research_use_authorized"], bool)
    assert isinstance(data["hla_typing_consent"], bool)
    assert data["lifecycle_status"] in (
        "CONSENT_PENDING",
        "ACTIVE",
        "KIT_DISPATCHED",
        "COLLECTED",
        "CLOSED",
        "WITHDRAWN",
    )
    assert data["consent_status"] in ("PENDING", "CONSENTED", "AMENDMENT_PENDING", "REVOKED")
    assert isinstance(data["consent_version"], int)
    assert isinstance(data["consent_amendment_count"], int)
    assert "consent_signed_at" in data
    assert "withdrawal_reason_code" in data


def assert_storage_account(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert isinstance(data["billing_contact_email"], str)
    assert data["plan_term_years"] in THRESHOLDS["PLAN_TERM_YEARS_ALLOWED"]
    assert isinstance(data["prepaid_through_date"], str)
    assert isinstance(data["paid_through_date"], str)
    assert data["status"] in (
        "ACTIVE",
        "PAST_DUE",
        "DELINQUENT",
        "ABANDONMENT_NOTICE",
        "ABANDONED",
        "CLOSED",
    )
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["lifetime_paid_cents"], int)
    assert "last_settlement_total_cents" in data
    assert "delinquency_stage_entered_at" in data


def assert_collection_kit(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert isinstance(data["kit_lot_code"], str)
    assert isinstance(data["courier_tracking_code"], str)
    assert is_iso8601_timestamp(data["dispatched_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("DISPATCHED", "HELD", "USED", "EXPIRED", "RETURNED")
    assert "hold_reason_code" in data


def assert_collection(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["kit_id"])
    assert is_iso8601_timestamp(data["collected_at"])
    assert isinstance(data["collection_volume_ml"], (int, float))
    assert isinstance(data["anticoagulant_volume_ml"], (int, float))
    assert data["delivery_mode"] in ("VAGINAL", "CESAREAN")
    assert isinstance(data["net_volume_ml"], (int, float))
    assert "transport_temp_c" in data
    assert "received_at" in data
    assert "hours_to_receipt" in data
    assert data["status"] in (
        "COLLECTED",
        "RECEIVED",
        "REJECTED_LATE",
        "REJECTED_TEMP",
        "REJECTED_VOLUME",
        "DISCARDED",
    )
    assert "rejection_reason_code" in data


def assert_cord_blood_unit(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["collection_id"])
    assert isinstance(data["unit_registry_code"], str)
    assert data["unit_registry_code"].startswith("CBU-"), data["unit_registry_code"]
    assert data["program_type"] in ("PRIVATE_FAMILY", "PUBLIC_DONATION")
    assert data["processing_status"] in (
        "RECEIVED",
        "PROCESSING",
        "VOLUME_REDUCED",
        "CRYOPRESERVED",
        "DISCARDED",
    )
    assert data["availability_status"] in (
        "UNAVAILABLE",
        "PRIVATE_STORED",
        "LISTED",
        "RESERVED",
        "QUARANTINED",
        "PENDING_ABANDONMENT",
        "RELEASED",
        "DISPOSED",
    )
    assert data["eligibility_status"] in ("PENDING", "ELIGIBLE", "INELIGIBLE", "INDETERMINATE")
    for optional in (
        "tank_id",
        "storage_account_id",
        "eligibility_reason_code",
        "eligibility_determined_by_user_id",
        "post_processing_volume_ml",
        "post_processing_tnc_millions",
        "post_processing_cd34_thousands",
        "post_processing_viability_pct",
        "quality_acceptance_score",
        "slot_code",
        "cryopreserved_at",
        "quarantine_reason_code",
        "disposition_reason",
        "disposed_at",
    ):
        assert optional in data, f"unit is missing {optional}"


def assert_processing_run(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert data["method"] in ("HES_SEDIMENTATION", "AUTOMATED_SEPARATION")
    assert isinstance(data["pre_tnc_millions"], int)
    assert isinstance(data["pre_volume_ml"], (int, float))
    assert is_iso8601_timestamp(data["started_at"])
    assert isinstance(data["operator_user_id"], str)
    assert data["status"] in ("IN_PROGRESS", "COMPLETED", "FAILED")
    for optional in (
        "post_volume_ml",
        "post_tnc_millions",
        "tnc_recovery_pct",
        "volume_reduction_pct",
        "completed_at",
    ):
        assert optional in data, f"run is missing {optional}"


def assert_quality_test(data: dict) -> None:
    """A test record is immutable once written, so it carries no version axis."""
    assert_common_fields(data, versioned=False)
    assert "updated_at" not in data, "an immutable test record must expose no updated_at"
    assert "version" not in data, "an immutable test record must expose no version"
    assert is_valid_uuid(data["unit_id"])
    assert data["test_kind"] in ("POST_PROCESSING", "CONFIRMATORY")
    assert isinstance(data["tnc_millions"], int)
    assert isinstance(data["cd34_thousands"], int)
    assert isinstance(data["viability_pct"], (int, float))
    assert isinstance(data["volume_ml"], (int, float))
    assert data["sterility_result"] in ("NEGATIVE", "POSITIVE", "PENDING")
    assert is_iso8601_timestamp(data["performed_at"])
    assert isinstance(data["performed_by_user_id"], str)
    assert data["outcome"] in ("PASS", "FAIL")
    assert isinstance(data["failure_reason_codes"], list)


def assert_maternal_screening(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_iso8601_timestamp(data["collected_at"])
    for marker in ("hiv_result", "hbv_result", "hcv_result", "htlv_result", "syphilis_result"):
        assert data[marker] in ("NON_REACTIVE", "REACTIVE", "INDETERMINATE", "PENDING")
    assert "cmv_result" in data
    assert isinstance(data["nat_confirmed"], bool)
    assert "overall_result" in data
    assert isinstance(data["reactive_marker_codes"], list)
    assert is_iso8601_timestamp(data["valid_until"])
    assert data["status"] in ("PENDING", "COMPLETED", "INVALID", "EXPIRED")


def assert_storage_tank(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["tank_code"], str)
    assert data["tank_class"] in ("STANDARD", "PREMIUM")
    assert isinstance(data["capacity_slots"], int) and data["capacity_slots"] >= 1
    assert isinstance(data["occupied_slots"], int) and data["occupied_slots"] >= 0
    assert data["status"] in ("ONLINE", "ALARM", "MAINTENANCE", "OFFLINE")
    assert isinstance(data["cumulative_excursion_minutes_30d"], int)
    for optional in (
        "maintenance_window_start",
        "maintenance_window_end",
        "last_temperature_c",
        "last_reading_at",
    ):
        assert optional in data, f"tank is missing {optional}"


def assert_temperature_excursion(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["tank_id"])
    assert is_iso8601_timestamp(data["detected_at"])
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "ESCALATED", "RESOLVED", "CLOSED_LOSS")
    for optional in (
        "peak_temperature_c",
        "acknowledged_at",
        "acknowledged_by_user_id",
        "resolved_at",
        "duration_minutes",
        "disposition",
    ):
        assert optional in data, f"excursion is missing {optional}"


def assert_registry_listing(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert isinstance(data["registry_code"], str)
    for locus in ("hla_a", "hla_b", "hla_drb1"):
        assert isinstance(data[locus], str) and data[locus]
    assert is_iso8601_timestamp(data["listed_at"])
    assert data["potency_grade"] in ("A", "B", "C")
    assert data["listing_status"] in ("ACTIVE", "SUSPENDED", "MATCHED", "WITHDRAWN")
    assert "suspension_reason_code" in data


def assert_storage_invoice(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["billing_period_start"], str)
    assert isinstance(data["billing_period_end"], str)
    assert isinstance(data["prorated_days"], int)
    assert isinstance(data["due_date"], str)
    for money in (
        "base_line_cents",
        "surcharge_line_cents",
        "admin_line_cents",
        "late_fee_line_cents",
        "amount_due_cents",
        "amount_paid_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be integer cents"
    assert "stage_advanced_at" in data
    assert data["status"] in (
        "ISSUED",
        "PAST_DUE",
        "DELINQUENT",
        "PAID",
        "VOID",
        "WRITTEN_OFF",
    )


def assert_reservation(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert isinstance(data["requesting_center_user_id"], str)
    assert isinstance(data["requesting_center_name"], str)
    assert isinstance(data["patient_weight_kg"], (int, float))
    assert isinstance(data["patient_hla_match_count"], int)
    assert is_iso8601_timestamp(data["hold_from"])
    assert is_iso8601_timestamp(data["hold_until"])
    assert data["status"] in (
        "PENDING_CONFIRMATORY",
        "CONFIRMED",
        "DECLINED",
        "CANCELLED",
        "EXPIRED",
        "RELEASED",
    )
    for optional in (
        "superseded_by_reservation_id",
        "confirmatory_test_id",
        "intended_transplant_date",
        "pre_cryo_dose_x1e7_per_kg",
        "post_thaw_dose_x1e7_per_kg",
        "dose_variant_applied",
        "settlement_total_cents",
        "released_at",
        "cancellation_reason_code",
    ):
        assert optional in data, f"reservation is missing {optional}"


# --- Formula checkers ------------------------------------------------------

SCORE_TIERS = {
    "PUBLIC_DONATION": {
        "tnc_target": 1500,
        "cd34_target": 3000,
        "viability_floor": 85.0,
        "volume_min": 24.0,
        "volume_max": 26.0,
    },
    "PRIVATE_FAMILY": {
        "tnc_target": 900,
        "cd34_target": 1500,
        "viability_floor": 75.0,
        "volume_min": 20.0,
        "volume_max": 30.0,
    },
}


def expected_quality_acceptance_score(
    program_type: str,
    tnc_millions: int,
    cd34_thousands: int,
    viability_pct: float,
    volume_ml: float,
    sterility_result: str = "NEGATIVE",
) -> float:
    """The score, composed in the pinned order and rounded exactly once."""
    tier = SCORE_TIERS[program_type]
    cell = min(1.0, tnc_millions / tier["tnc_target"])
    cd34 = min(1.0, cd34_thousands / tier["cd34_target"])
    floor = tier["viability_floor"]
    viability = max(0.0, (viability_pct - floor) / (100.0 - floor))
    penalty = 0.10 if (volume_ml < tier["volume_min"] or volume_ml > tier["volume_max"]) else 0.0
    gate = 1.0 if sterility_result == "NEGATIVE" else 0.0
    weighted = 0.45 * cell + 0.35 * cd34 + 0.20 * viability
    return round_half_up(gate * max(0.0, weighted - penalty) * 100, 2)


def expected_pre_cryo_dose(post_processing_tnc_millions: int, patient_weight_kg: float) -> float:
    """The pre-freeze variant: the stored count over ten times the patient weight."""
    return round_half_up(post_processing_tnc_millions / (10 * patient_weight_kg), 2)


def expected_confirmatory_recovery_pct(
    confirmatory_tnc_millions: int, post_processing_tnc_millions: int
) -> float:
    return round_half_up(confirmatory_tnc_millions / post_processing_tnc_millions * 100, 2)


def expected_post_thaw_dose(
    post_processing_tnc_millions: int,
    confirmatory_tnc_millions: int,
    confirmatory_viability_pct: float,
    patient_weight_kg: float,
) -> float:
    """The post-thaw variant, in exactly three rounded steps in exactly this order."""
    recovery = expected_confirmatory_recovery_pct(
        confirmatory_tnc_millions, post_processing_tnc_millions
    )
    effective = round_half_up(
        post_processing_tnc_millions * (confirmatory_viability_pct / 100) * (recovery / 100), 2
    )
    return round_half_up(effective / (10 * patient_weight_kg), 2)


def expected_invoice_lines(prorated_days: int, premium_tank: bool) -> dict:
    """Each line is rounded to whole cents before it joins the total."""
    base = round_cents(
        Decimal(THRESHOLDS["ANNUAL_STORAGE_FEE_CENTS"])
        * Decimal(prorated_days)
        / Decimal(THRESHOLDS["DAYS_PER_YEAR"])
    )
    surcharge = round_cents(Decimal(base) * Decimal(str(THRESHOLDS["PREMIUM_SURCHARGE_RATE"]))) if premium_tank else 0
    admin = round_cents(
        Decimal(THRESHOLDS["ANNUAL_STORAGE_FEE_CENTS"]) * Decimal(str(THRESHOLDS["ADMIN_RATE"]))
    )
    return {
        "base_line_cents": base,
        "surcharge_line_cents": surcharge,
        "admin_line_cents": admin,
        "late_fee_line_cents": 0,
        "amount_due_cents": base + surcharge + admin,
    }


def expected_late_fee(residual_cents: int) -> int:
    """A stage advance adds the residual at that moment times the late-fee rate."""
    return round_cents(Decimal(residual_cents) * Decimal(str(THRESHOLDS["LATE_FEE_RATE"])))


def expected_disposition_fee(pre_fee_subtotal_cents: int) -> int:
    """The fee tier is keyed on the pre-fee subtotal, never on the final total."""
    if pre_fee_subtotal_cents <= 0:
        return THRESHOLDS["DISPOSITION_FEE_SUBTOTAL_NONPOSITIVE_CENTS"]
    if pre_fee_subtotal_cents < THRESHOLDS["DISPOSITION_FEE_HIGH_TIER_FLOOR_CENTS"]:
        return THRESHOLDS["DISPOSITION_FEE_SUBTOTAL_LOW_CENTS"]
    return THRESHOLDS["DISPOSITION_FEE_SUBTOTAL_HIGH_CENTS"]


def expected_potency_grade(tnc_millions: int, cd34_thousands: int) -> str:
    if tnc_millions >= 1500 and cd34_thousands >= 3000:
        return "A"
    if tnc_millions >= 1200 and cd34_thousands >= 2000:
        return "B"
    return "C"


# --- Invariant checkers ----------------------------------------------------

OCCUPYING_AVAILABILITY = (
    "UNAVAILABLE",
    "PRIVATE_STORED",
    "LISTED",
    "RESERVED",
    "QUARANTINED",
    "PENDING_ABANDONMENT",
)


def assert_occupied_slots_matches_inventory(tank: dict, units: list) -> None:
    """``occupied_slots`` is always the count of the tank's units that still hold a slot.

    A unit that has been released or disposed no longer occupies its slot; a
    quarantined or pending-abandonment unit still does.
    """
    live = [
        u
        for u in units
        if u.get("tank_id") == tank["id"] and u["availability_status"] not in ("RELEASED", "DISPOSED")
    ]
    assert tank["occupied_slots"] == len(live), (
        f"occupied_slots {tank['occupied_slots']} does not match "
        f"{len(live)} units still holding a slot"
    )


def assert_unit_axes(
    unit: dict,
    processing_status: Optional[str] = None,
    availability_status: Optional[str] = None,
    eligibility_status: Optional[str] = None,
) -> None:
    """Check the unit's three independent axes, naming whichever ones matter."""
    if processing_status is not None:
        assert unit["processing_status"] == processing_status, (
            f"processing_status {unit['processing_status']} != {processing_status}"
        )
    if availability_status is not None:
        assert unit["availability_status"] == availability_status, (
            f"availability_status {unit['availability_status']} != {availability_status}"
        )
    if eligibility_status is not None:
        assert unit["eligibility_status"] == eligibility_status, (
            f"eligibility_status {unit['eligibility_status']} != {eligibility_status}"
        )


def assert_balance_equals_unpaid_residual(account: dict, invoices: list) -> None:
    """The balance is the sum of the residuals of the account's outstanding invoices."""
    residual = sum(
        inv["amount_due_cents"] - inv["amount_paid_cents"]
        for inv in invoices
        if inv["status"] in ("ISSUED", "PAST_DUE", "DELINQUENT")
    )
    assert account["balance_cents"] == residual, (
        f"balance_cents {account['balance_cents']} != unpaid residual {residual}"
    )


def assert_created_at_ascending(rows: list) -> None:
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), f"rows are not ordered by created_at ascending: {stamps}"


def assert_registry_code_sequence(unit: dict, sequence_number: int) -> None:
    """The label is the literal prefix ``CBU-`` plus the sequence zero-padded to six digits."""
    expected = f"CBU-{sequence_number:06d}"
    assert unit["unit_registry_code"] == expected, (
        f"unit_registry_code {unit['unit_registry_code']} != {expected}"
    )
