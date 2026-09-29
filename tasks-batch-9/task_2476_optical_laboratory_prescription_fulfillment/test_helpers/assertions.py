"""Entity-shape assertions and the three conservation checks."""

from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_KEYS = ("id", "created_at", "updated_at", "version")
EVENT_ROW_KEYS = ("id", "created_at")


# --------------------------------------------------------------------------
# Shared shape helpers
# --------------------------------------------------------------------------


def assert_common_fields(row: dict) -> None:
    """Most rows carry id, created_at, updated_at and version."""
    for key in COMMON_KEYS:
        assert key in row, f"missing common field {key}"
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']}"
    assert is_iso8601_timestamp(row["created_at"])
    assert is_iso8601_timestamp(row["updated_at"])
    assert isinstance(row["version"], int) and row["version"] >= 1


def assert_event_row_fields(row: dict) -> None:
    """Append-only event rows carry only id and created_at."""
    for key in EVENT_ROW_KEYS:
        assert key in row, f"missing event-row field {key}"
    assert is_valid_uuid(row["id"])
    assert is_iso8601_timestamp(row["created_at"])
    assert "updated_at" not in row, "event rows have no updated_at"
    assert "version" not in row, "event rows have no version"


def assert_timestamp_millis(value: str) -> None:
    """Timestamps are rendered with exactly three fractional digits."""
    assert is_iso8601_timestamp(value), f"not an ISO 8601 instant: {value}"
    assert value.endswith("Z"), f"not a UTC instant: {value}"
    assert len(value) == len("2026-08-01T00:00:00.000Z"), (
        f"expected exactly three fractional digits: {value}"
    )


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------


def assert_prescriber(row: dict) -> None:
    assert_common_fields(row)
    assert row["status"] in {"ACTIVE", "SUSPENDED", "RETIRED"}
    assert isinstance(row["npi"], str) and len(row["npi"]) == 10
    assert len(row["license_state"]) == 2 and row["license_state"].isupper()
    assert 1 <= row["max_rx_validity_months"] <= 36
    assert isinstance(row["verified_rx_count"], int)


def assert_insurance_plan(row: dict) -> None:
    assert_common_fields(row)
    for field in (
        "frame_allowance_cents",
        "lens_base_allowance_cents",
        "coating_allowance_cents",
        "progressive_copay_cents",
        "annual_benefit_cap_cents",
    ):
        assert isinstance(row[field], int) and row[field] >= 0
    assert 0.0 <= row["coinsurance_pct"] <= 1.0
    assert isinstance(row["expedite_covered"], bool)
    assert isinstance(row["specialty_requires_prior_auth"], bool)


def assert_patient(row: dict) -> None:
    assert_common_fields(row)
    assert row["status"] in {"ACTIVE", "INACTIVE"}
    assert isinstance(row["benefit_used_cents"], int)
    if row.get("insurance_plan_id") is None:
        assert row.get("member_number") is None, "a self-pay patient has no member number"


def assert_lens_design(row: dict) -> None:
    assert_common_fields(row)
    assert row["design_type"] in {"SINGLE_VISION", "PROGRESSIVE", "SPECIALTY"}
    assert row["material"] in {"CR39", "POLYCARBONATE", "TRIVEX", "HIGH_INDEX_167"}
    assert row["product_tier"] in {"ECONOMY", "STANDARD", "PREMIUM"}
    assert isinstance(row["allowed_coatings"], list) and row["allowed_coatings"]
    assert row["retail_price_cents"] > 0
    assert 8.0 <= row["min_fitting_height_mm"] <= 30.0
    assert 50.0 <= row["min_blank_diameter_mm"] <= 85.0


def assert_tolerance_standard(row: dict) -> None:
    assert_common_fields(row)
    assert row["power_band_max_abs"] > row["power_band_min_abs"]
    for field in (
        "sphere_tolerance_diopters",
        "cylinder_tolerance_diopters",
        "axis_tolerance_degrees",
        "prism_tolerance_pd",
    ):
        assert row[field] > 0
    assert isinstance(row["allowed_cosmetic_defect_codes"], list)


def assert_lens_blank_lot(row: dict) -> None:
    assert_common_fields(row)
    assert row["status"] in {"AVAILABLE", "DEPLETED"}
    assert 50.0 <= row["diameter_mm"] <= 85.0
    assert_blank_ledger_conserved(row)


def assert_lab_machine(row: dict) -> None:
    assert_common_fields(row)
    assert row["machine_type"] in {"GENERATOR", "POLISHER"}
    assert row["status"] in {"AVAILABLE", "CALIBRATION_HOLD", "DOWN"}
    assert 0 <= row["calibration_buffer_minutes"] <= 120


def assert_finishing_bay(row: dict) -> None:
    assert_common_fields(row)
    assert row["status"] in {"OPEN", "CLOSED"}
    assert 1 <= row["concurrent_capacity"] <= 4


def assert_prescription(row: dict) -> None:
    assert_common_fields(row)
    assert row["verification_status"] in {"UNVERIFIED", "VERIFIED", "REJECTED"}
    assert isinstance(row["requires_multifocal"], bool)
    assert isinstance(row["resubmit_count"], int)
    assert_timestamp_millis(row["expires_at"])
    assert row["prism_diopter_od"] is not None
    assert row["prism_diopter_os"] is not None


def assert_rx_order(row: dict) -> None:
    assert_common_fields(row)
    assert row["fulfillment_status"] in {
        "DRAFT",
        "LAYOUT_READY",
        "IN_LAB",
        "LAB_COMPLETE",
        "REMAKE_PENDING",
        "DISPENSED",
        "CANCELLED",
    }
    assert row["billing_status"] in {
        "PROVISIONAL_QUOTED",
        "BENEFIT_APPLIED",
        "BENEFIT_VOIDED",
        "SELF_PAY_FINAL",
        "PATIENT_SETTLED",
        "REFUND_DUE",
        "CANCELLED_NO_CHARGE",
    }
    assert row["tat_commitment_status"] in {"ON_TRACK", "AT_RISK", "BREACHED"}
    assert row["quote_variant"] in {"PROVISIONAL", "FINAL"}
    for field in (
        "gross_charge_cents",
        "estimated_benefit_cents",
        "insurance_benefit_cents",
        "patient_portion_cents",
        "lab_writeoff_cents",
        "patient_paid_cents",
        "patient_balance_due_cents",
        "expedite_fee_cents",
    ):
        assert isinstance(row[field], int), f"{field} must be integer cents"
    assert_money_identity(row)
    assert_balance_definition(row)


def assert_frame_layout(row: dict) -> None:
    assert_common_fields(row)
    assert row["layout_status"] in {"COMPUTED", "SUPERSEDED", "BLANK_TOO_SMALL"}
    assert row["trace_source"] in {"DIGITAL_TRACER", "MANUAL_CALIPER", "CATALOG"}
    assert row["required_blank_diameter_mm"] > 0


def assert_lab_job(row: dict) -> None:
    assert_common_fields(row)
    assert row["route"] in {"STOCK_EDGE_ONLY", "SURFACE_AND_EDGE"}
    assert row["status"] in {
        "QUEUED",
        "SURFACING",
        "SURFACED",
        "EDGING",
        "EDGED",
        "REWORK_QUEUED",
        "BLANK_BACKORDER",
        "PASSED",
        "RELEASED",
        "SCRAPPED",
    }
    assert 0 <= row["rework_cycle_count"] <= 2
    assert row["breakage_count"] >= 0
    if row["route"] == "STOCK_EDGE_ONLY":
        assert row["blank_lot_id"] is None, "a stock-edging job consumes no blank lot"


def assert_lab_operation(row: dict) -> None:
    assert_common_fields(row)
    assert row["operation_type"] in {"SURFACING", "EDGING"}
    assert row["status"] in {
        "SCHEDULED",
        "RUNNING",
        "COMPLETED",
        "BROKEN",
        "CANCELLED",
    }
    if row["operation_type"] == "EDGING":
        assert row.get("machine_id") is None
        assert row.get("bay_id") is not None
    else:
        assert row.get("bay_id") is None
        assert row.get("machine_id") is not None


def assert_quality_inspection(row: dict) -> None:
    assert_event_row_fields(row)
    assert row["eye"] in {"OD", "OS"}
    assert row["verdict"] in {"PASS", "FAIL"}
    assert isinstance(row["failed_metrics"], list)
    assert (row["verdict"] == "FAIL") == bool(row["failed_metrics"])
    assert_failed_metric_order(row["failed_metrics"])
    assert isinstance(row["axis_delta"], int)
    assert row["cycle_index"] >= 0


def assert_remake_case(row: dict) -> None:
    assert_common_fields(row)
    assert row["status"] in {"SUBMITTED", "ADJUDICATED", "CLOSED"}
    assert row["responsibility"] in {"UNASSIGNED", "STORE", "LAB", "SPLIT"}
    assert isinstance(row["warranty_covered"], bool)
    assert isinstance(row["lab_chargeback_cents"], int)
    if row["adjudication_method"] is not None:
        assert row["adjudication_method"] in {"PROCESS_AUDIT", "TOLERANCE_DELTA"}


def assert_settlement_entry(row: dict) -> None:
    assert_event_row_fields(row)
    assert row["entry_type"] in {
        "ORDER_CHARGE",
        "INSURANCE_BENEFIT",
        "BENEFIT_REVERSAL",
        "LAB_WRITEOFF",
        "PATIENT_PAYMENT",
    }
    assert isinstance(row["amount_cents"], int)
    assert_settlement_sign(row)
    assert_timestamp_millis(row["effective_at"])


def assert_charge_summary(row: dict) -> None:
    for field in (
        "gross_charge_cents",
        "estimated_benefit_cents",
        "insurance_benefit_cents",
        "patient_portion_cents",
        "lab_writeoff_cents",
        "patient_paid_cents",
        "patient_balance_due_cents",
        "expedite_fee_cents",
        "quote_variant",
        "invariant_holds",
    ):
        assert field in row, f"charge summary is missing {field}"
    assert isinstance(row["invariant_holds"], bool)


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------


def assert_money_identity(order: dict) -> None:
    """The gross charge equals benefit plus patient portion plus write-off."""
    assert order["gross_charge_cents"] == (
        order["insurance_benefit_cents"]
        + order["patient_portion_cents"]
        + order["lab_writeoff_cents"]
    ), (
        "money identity violated: "
        f"gross={order['gross_charge_cents']} "
        f"benefit={order['insurance_benefit_cents']} "
        f"patient={order['patient_portion_cents']} "
        f"writeoff={order['lab_writeoff_cents']}"
    )


def assert_balance_definition(order: dict) -> None:
    """The balance due is always the patient portion less what has been paid."""
    assert (
        order["patient_balance_due_cents"]
        == order["patient_portion_cents"] - order["patient_paid_cents"]
    )


def assert_blank_ledger_conserved(lot: dict) -> None:
    """The four quantity counters together account for received_qty."""
    total = (
        lot["on_hand_qty"]
        + lot["allocated_qty"]
        + lot["consumed_qty"]
        + lot["scrapped_qty"]
    )
    assert total == lot["received_qty"], (
        "blank ledger not conserved: "
        f"received={lot['received_qty']} on_hand={lot['on_hand_qty']} "
        f"allocated={lot['allocated_qty']} consumed={lot['consumed_qty']} "
        f"scrapped={lot['scrapped_qty']}"
    )


def assert_lot_quantities(
    lot: dict,
    on_hand: int,
    allocated: int,
    consumed: int,
    scrapped: int,
    status: Optional[str] = None,
) -> None:
    assert lot["on_hand_qty"] == on_hand, f"on_hand_qty {lot['on_hand_qty']} != {on_hand}"
    assert lot["allocated_qty"] == allocated
    assert lot["consumed_qty"] == consumed
    assert lot["scrapped_qty"] == scrapped
    if status is not None:
        assert lot["status"] == status
    assert_blank_ledger_conserved(lot)


def assert_failed_metric_order(failed_metrics: list) -> None:
    """failed_metrics is assembled in the fixed SPHERE, CYLINDER, AXIS, PRISM,
    COSMETIC order."""
    canonical = ["SPHERE", "CYLINDER", "AXIS", "PRISM", "COSMETIC"]
    positions = [canonical.index(metric) for metric in failed_metrics]
    assert positions == sorted(positions), (
        f"failed_metrics out of the fixed order: {failed_metrics}"
    )


def assert_settlement_sign(entry: dict) -> None:
    """ORDER_CHARGE and BENEFIT_REVERSAL are positive; the other three are
    negative."""
    positive_types = {"ORDER_CHARGE", "BENEFIT_REVERSAL"}
    if entry["entry_type"] in positive_types:
        assert entry["amount_cents"] > 0, (
            f"{entry['entry_type']} must be positive, got {entry['amount_cents']}"
        )
    else:
        assert entry["amount_cents"] < 0, (
            f"{entry['entry_type']} must be negative, got {entry['amount_cents']}"
        )


def assert_ledger_types_in_order(entries: list, expected_types: list) -> None:
    """The ledger read returns entries in effective_at order, oldest first."""
    actual = [entry["entry_type"] for entry in entries]
    assert actual == expected_types, f"ledger sequence {actual} != {expected_types}"


def assert_no_version_or_updated_at(row: dict) -> None:
    assert "version" not in row
    assert "updated_at" not in row
