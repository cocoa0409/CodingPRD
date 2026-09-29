"""
Request payload factories.

Every factory returns a valid payload for its endpoint and accepts **overrides
so a test can vary exactly one field. Passing None for a field removes it,
which is how the missing-required-field probes are built.
"""

from typing import Any, Dict

from .constants import (
    BASE_BIN_CAPACITY_BUSHELS,
    BASE_BIN_CODE,
    BASE_BOND_AMOUNT_CENTS,
    BASE_DECLARED_VALUE_CENTS_PER_BUSHEL,
    BASE_FILL_END_AT,
    BASE_FILL_START_AT,
    BASE_FREE_STORAGE_DAYS,
    BASE_LENDER_CREDIT_LINE_CENTS,
    BASE_LICENSE_EFFECTIVE_DATE,
    BASE_LICENSE_EXPIRY_DATE,
    BASE_LICENSED_CAPACITY_BUSHELS,
    BASE_LOADOUT_CHARGE_CENTS_PER_BUSHEL,
    BASE_LOADOUT_LANE_COUNT,
    BASE_MAX_MOISTURE_PCT,
    BASE_NET_WORTH_CENTS,
    BASE_OPERATOR_NAME,
    BASE_RECEIPT_NUMBER,
    BASE_RECEIVING_CHARGE_CENTS_PER_BUSHEL,
    BASE_STATE_CODE,
    BASE_STORAGE_RATE_MILLICENTS,
    BASE_TICKET_GROSS_BUSHELS,
    BASE_WAREHOUSE_NAME,
    CLOCK_BASE_UTC,
)


def _clean(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override value is None."""
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def clock_payload(current_utc: str = CLOCK_BASE_UTC, **overrides) -> Dict[str, Any]:
    return _clean({"current_utc": current_utc}, overrides)


# ---------------------------------------------------------------------------
# Warehouse
# ---------------------------------------------------------------------------
def warehouse_payload(**overrides) -> Dict[str, Any]:
    """A STATE warehouse that exactly satisfies the STATE licensing minimums."""
    return _clean(
        {
            "name": BASE_WAREHOUSE_NAME,
            "operator_name": BASE_OPERATOR_NAME,
            "state_code": BASE_STATE_CODE,
            "license_program": "STATE",
            "licensed_capacity_bushels": BASE_LICENSED_CAPACITY_BUSHELS,
            "bond_amount_cents": BASE_BOND_AMOUNT_CENTS,
            "net_worth_cents": BASE_NET_WORTH_CENTS,
            "loadout_lane_count": BASE_LOADOUT_LANE_COUNT,
            "registry_participant": True,
        },
        overrides,
    )


def license_issue_payload(**overrides) -> Dict[str, Any]:
    return _clean(
        {
            "decision": "ISSUE",
            "license_effective_date": BASE_LICENSE_EFFECTIVE_DATE,
            "license_expiry_date": BASE_LICENSE_EXPIRY_DATE,
        },
        overrides,
    )


def license_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _clean({"decision": decision}, overrides)


def insolvency_payload(action: str, **overrides) -> Dict[str, Any]:
    return _clean({"action": action}, overrides)


def financials_payload(**overrides) -> Dict[str, Any]:
    return _clean({}, overrides)


# ---------------------------------------------------------------------------
# Party
# ---------------------------------------------------------------------------
def producer_payload(**overrides) -> Dict[str, Any]:
    return _clean(
        {
            "name": "Ada Farms",
            "party_kind": "PRODUCER_DEPOSITOR",
            "state_code": BASE_STATE_CODE,
        },
        overrides,
    )


def commercial_depositor_payload(**overrides) -> Dict[str, Any]:
    return _clean(
        {
            "name": "Midwest Milling LLC",
            "party_kind": "COMMERCIAL_DEPOSITOR",
            "state_code": BASE_STATE_CODE,
        },
        overrides,
    )


def lender_payload(**overrides) -> Dict[str, Any]:
    return _clean(
        {
            "name": "AgCredit Bank",
            "party_kind": "LENDER",
            "state_code": BASE_STATE_CODE,
            "credit_line_cents": BASE_LENDER_CREDIT_LINE_CENTS,
        },
        overrides,
    )


def credit_line_payload(credit_line_cents: int, **overrides) -> Dict[str, Any]:
    return _clean({"credit_line_cents": credit_line_cents}, overrides)


# ---------------------------------------------------------------------------
# StorageAgreement
# ---------------------------------------------------------------------------
def storage_agreement_payload(
    warehouse_id: str, depositor_party_id: str, **overrides
) -> Dict[str, Any]:
    return _clean(
        {
            "warehouse_id": warehouse_id,
            "depositor_party_id": depositor_party_id,
            "commodity": "CORN",
            "storage_kind": "COMMINGLED",
            "min_grade": "US_NO_3",
            "max_moisture_pct": BASE_MAX_MOISTURE_PCT,
            "storage_rate_millicents_per_bushel_day": BASE_STORAGE_RATE_MILLICENTS,
            "receiving_charge_cents_per_bushel": BASE_RECEIVING_CHARGE_CENTS_PER_BUSHEL,
            "loadout_charge_cents_per_bushel": BASE_LOADOUT_CHARGE_CENTS_PER_BUSHEL,
            "free_storage_days": BASE_FREE_STORAGE_DAYS,
            "declared_value_cents_per_bushel": BASE_DECLARED_VALUE_CENTS_PER_BUSHEL,
        },
        overrides,
    )


def terminate_agreement_payload(**overrides) -> Dict[str, Any]:
    return _clean({"termination_reason": "depositor relocated"}, overrides)


# ---------------------------------------------------------------------------
# Bin
# ---------------------------------------------------------------------------
def bin_payload(warehouse_id: str, **overrides) -> Dict[str, Any]:
    return _clean(
        {
            "warehouse_id": warehouse_id,
            "bin_code": BASE_BIN_CODE,
            "capacity_bushels": BASE_BIN_CAPACITY_BUSHELS,
            "commodity": "CORN",
            "commingling_allowed": True,
        },
        overrides,
    )


def condition_assessment_payload(
    moisture_pct: float, temperature_f: float, **overrides
) -> Dict[str, Any]:
    return _clean(
        {"moisture_pct": moisture_pct, "temperature_f": temperature_f}, overrides
    )


# ---------------------------------------------------------------------------
# DepositTicket
# ---------------------------------------------------------------------------
def deposit_ticket_payload(
    storage_agreement_id: str, bin_id: str, **overrides
) -> Dict[str, Any]:
    """
    The base load: gross 1005 bushels at 4.5 percent dockage and 15.0 percent
    moisture, grading US_NO_1, netting 949 bushels.
    """
    return _clean(
        {
            "storage_agreement_id": storage_agreement_id,
            "bin_id": bin_id,
            "gross_bushels": BASE_TICKET_GROSS_BUSHELS,
            "test_weight_lbs": 56.5,
            "moisture_pct": 15.0,
            "damage_pct": 2.0,
            "foreign_material_pct": 1.0,
            "dockage_pct": 4.5,
            "fill_start_at": BASE_FILL_START_AT,
            "fill_end_at": BASE_FILL_END_AT,
        },
        overrides,
    )


def accept_ticket_payload(expected_bin_version: Any, **overrides) -> Dict[str, Any]:
    return _clean({"expected_bin_version": expected_bin_version}, overrides)


def reject_ticket_payload(**overrides) -> Dict[str, Any]:
    return _clean({"rejection_reason": "OPERATOR_REJECTED"}, overrides)


# ---------------------------------------------------------------------------
# WarehouseReceipt
# ---------------------------------------------------------------------------
def receipt_payload(
    deposit_ticket_id: str,
    holder_party_id: str,
    expected_warehouse_version: Any,
    **overrides,
) -> Dict[str, Any]:
    return _clean(
        {
            "deposit_ticket_id": deposit_ticket_id,
            "holder_party_id": holder_party_id,
            "receipt_number": BASE_RECEIPT_NUMBER,
            "form": "NEGOTIABLE",
            "medium": "ELECTRONIC",
            "expected_warehouse_version": expected_warehouse_version,
        },
        overrides,
    )


def transfer_payload(to_party_id: str, transfer_channel: str, **overrides) -> Dict[str, Any]:
    return _clean(
        {"to_party_id": to_party_id, "transfer_channel": transfer_channel}, overrides
    )


def void_payload(**overrides) -> Dict[str, Any]:
    return _clean({"void_reason": "wrong holder recorded"}, overrides)


# ---------------------------------------------------------------------------
# CollateralLien
# ---------------------------------------------------------------------------
def collateral_lien_payload(
    receipt_id: str, lender_party_id: str, **overrides
) -> Dict[str, Any]:
    return _clean(
        {
            "receipt_id": receipt_id,
            "lender_party_id": lender_party_id,
            "principal_cents": 250000,
            "valuation_basis": "MARK_TO_MARKET",
            "mark_price_cents_per_bushel": 450,
            "perfection_method": "ELECTRONIC_CONTROL",
        },
        overrides,
    )


def perfect_payload(**overrides) -> Dict[str, Any]:
    return _clean({"attestation_note": "registry control taken"}, overrides)


def release_payload(payoff_received_cents: int = 250000, **overrides) -> Dict[str, Any]:
    return _clean({"payoff_received_cents": payoff_received_cents}, overrides)


def revalue_payload(mark_price_cents_per_bushel: int, **overrides) -> Dict[str, Any]:
    return _clean(
        {"mark_price_cents_per_bushel": mark_price_cents_per_bushel}, overrides
    )


# ---------------------------------------------------------------------------
# PositionReport
# ---------------------------------------------------------------------------
def position_report_payload(warehouse_id: str, **overrides) -> Dict[str, Any]:
    return _clean(
        {
            "warehouse_id": warehouse_id,
            "period_start_date": "2026-08-01",
            "period_end_date": "2026-08-31",
            "as_of_date": "2026-08-05",
        },
        overrides,
    )


def submit_report_payload(
    reported_physical_bushels: int, reported_obligation_bushels: int, **overrides
) -> Dict[str, Any]:
    return _clean(
        {
            "reported_physical_bushels": reported_physical_bushels,
            "reported_obligation_bushels": reported_obligation_bushels,
        },
        overrides,
    )


def examine_report_payload(result: str, **overrides) -> Dict[str, Any]:
    return _clean({"result": result}, overrides)


# ---------------------------------------------------------------------------
# DeliveryOrder
# ---------------------------------------------------------------------------
def delivery_order_payload(
    receipt_id: str,
    requested_bushels: int,
    appointment_start_at: str,
    appointment_end_at: str,
    **overrides,
) -> Dict[str, Any]:
    return _clean(
        {
            "receipt_id": receipt_id,
            "requested_bushels": requested_bushels,
            "appointment_start_at": appointment_start_at,
            "appointment_end_at": appointment_end_at,
        },
        overrides,
    )


def load_payload(delivered_bushels: int, **overrides) -> Dict[str, Any]:
    """Loadout readings that grade US_NO_1 unless overridden."""
    return _clean(
        {
            "delivered_bushels": delivered_bushels,
            "delivered_test_weight_lbs": 56.5,
            "delivered_moisture_pct": 13.0,
            "delivered_damage_pct": 2.0,
            "delivered_foreign_material_pct": 1.0,
        },
        overrides,
    )


def settle_payload(settlement_price_cents_per_bushel: int, **overrides) -> Dict[str, Any]:
    return _clean(
        {"settlement_price_cents_per_bushel": settlement_price_cents_per_bushel},
        overrides,
    )


def cancel_delivery_payload(**overrides) -> Dict[str, Any]:
    return _clean({"cancellation_reason": "truck unavailable"}, overrides)


# ---------------------------------------------------------------------------
# IndemnityClaim
# ---------------------------------------------------------------------------
def indemnity_claim_payload(
    warehouse_id: str, receipt_id: str, claimant_party_id: str, claimed_cents: int, **overrides
) -> Dict[str, Any]:
    return _clean(
        {
            "warehouse_id": warehouse_id,
            "receipt_id": receipt_id,
            "claimant_party_id": claimant_party_id,
            "claimed_cents": claimed_cents,
        },
        overrides,
    )


def adjudicate_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _clean({"decision": decision}, overrides)
