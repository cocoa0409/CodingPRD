"""Request-payload builders.

Each factory produces a valid payload for one write endpoint with sensible
domain defaults, and accepts keyword overrides so a test can vary exactly the
one field it is exercising. Nothing here talks to the API — see ``fixtures.py``
for the precondition builders that do.
"""

from typing import Any, Dict, List, Optional

JsonDict = Dict[str, Any]


def _merge(base: JsonDict, overrides: JsonDict) -> JsonDict:
    """Apply overrides; a value of ``None`` removes the key entirely."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None and key in payload:
            del payload[key]
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------
CARRIER_NAME = "Atlas Bonded Carriage"
CARRIER_IRS_NUMBER = "12-3456789"
SECOND_CARRIER_NAME = "Beacon Drayage"
SECOND_CARRIER_IRS_NUMBER = "98-7654321"


def carrier_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {"name": CARRIER_NAME, "irs_number": CARRIER_IRS_NUMBER},
        overrides,
    )


def second_carrier_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {"name": SECOND_CARRIER_NAME, "irs_number": SECOND_CARRIER_IRS_NUMBER},
        overrides,
    )


def carrier_status_payload(custodial_status: str, reason_code: str) -> JsonDict:
    return {"custodial_status": custodial_status, "reason_code": reason_code}


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
PORT_NY_CODE = "4601"
PORT_CHICAGO_CODE = "3901"
PORT_LA_CODE = "2704"
PORT_DETROIT_CODE = "3801"


def port_ny_payload(**overrides: Any) -> JsonDict:
    """Port of New York: north-east region, a single examination bay."""
    return _merge(
        {
            "port_code": PORT_NY_CODE,
            "name": "Port of New York",
            "region_code": "NE",
            "exam_capacity_slots": 1,
            "go_warehouse_available": True,
        },
        overrides,
    )


def port_chicago_payload(**overrides: Any) -> JsonDict:
    """Port of Chicago: mid-west region, two examination bays."""
    return _merge(
        {
            "port_code": PORT_CHICAGO_CODE,
            "name": "Port of Chicago",
            "region_code": "MW",
            "exam_capacity_slots": 2,
            "go_warehouse_available": True,
        },
        overrides,
    )


def port_la_payload(**overrides: Any) -> JsonDict:
    """Port of Los Angeles: Pacific south-west, no general-order warehouse."""
    return _merge(
        {
            "port_code": PORT_LA_CODE,
            "name": "Port of Los Angeles",
            "region_code": "PSW",
            "exam_capacity_slots": 1,
            "go_warehouse_available": False,
        },
        overrides,
    )


def port_detroit_payload(**overrides: Any) -> JsonDict:
    """Port of Detroit: a second mid-west port, so in-region diversions exist."""
    return _merge(
        {
            "port_code": PORT_DETROIT_CODE,
            "name": "Port of Detroit",
            "region_code": "MW",
            "exam_capacity_slots": 1,
            "go_warehouse_available": True,
        },
        overrides,
    )


def port_payload(
    port_code: str,
    name: str,
    region_code: str,
    exam_capacity_slots: int,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "port_code": port_code,
            "name": name,
            "region_code": region_code,
            "exam_capacity_slots": exam_capacity_slots,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Bonds
# ---------------------------------------------------------------------------
BOND_EFFECTIVE_DATE = "2026-07-01T00:00:00Z"
BOND_EXPIRY_DATE = "2027-06-30T00:00:00Z"
BOND_LIMIT = 50000.00
SURETY_CODE = "SUR-100"


def continuous_bond_payload(carrier_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "carrier_id": carrier_id,
            "bond_type": "CONTINUOUS",
            "limit_amount": BOND_LIMIT,
            "effective_date": BOND_EFFECTIVE_DATE,
            "expiry_date": BOND_EXPIRY_DATE,
            "surety_code": SURETY_CODE,
        },
        overrides,
    )


def single_transaction_bond_payload(carrier_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "carrier_id": carrier_id,
            "bond_type": "SINGLE_TRANSACTION",
            "limit_amount": BOND_LIMIT,
            "effective_date": BOND_EFFECTIVE_DATE,
            "expiry_date": BOND_EXPIRY_DATE,
            "surety_code": SURETY_CODE,
        },
        overrides,
    )


def bond_limit_payload(limit_amount: float) -> JsonDict:
    """A surety re-limiting its own bond."""
    return {"limit_amount": limit_amount}


def bond_status_payload(status: str) -> JsonDict:
    """A surety suspending or reinstating its own bond."""
    return {"status": status}


# ---------------------------------------------------------------------------
# Movements
# ---------------------------------------------------------------------------
#: The reference consignment: 1,234.60 in cargo, 100.28 kg, 3 packages.
CARGO_VALUE = 1234.60
GROSS_WEIGHT_KG = 100.28
PACKAGE_COUNT = 3


def movement_payload(
    carrier_id: str,
    origin_port_id: str,
    destination_port_id: str,
    manifest_reference: str,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "carrier_id": carrier_id,
            "in_bond_type": "IT",
            "origin_port_id": origin_port_id,
            "destination_port_id": destination_port_id,
            "manifest_reference": manifest_reference,
            "cargo_value": CARGO_VALUE,
            "gross_weight_kg": GROSS_WEIGHT_KG,
            "package_count": PACKAGE_COUNT,
        },
        overrides,
    )


def departure_payload(seal_number: str) -> JsonDict:
    return {"seal_number": seal_number}


def cancellation_payload(reason_code: str = "SHIPPER_WITHDREW") -> JsonDict:
    return {"reason_code": reason_code}


def cargo_release_payload(reason_code: str = "ENTRY_FILED") -> JsonDict:
    return {"reason_code": reason_code}


# ---------------------------------------------------------------------------
# Seal events
# ---------------------------------------------------------------------------
def seal_event_payload(
    movement_id: str, event_type: str, seal_number: str, port_code: str
) -> JsonDict:
    return {
        "movement_id": movement_id,
        "event_type": event_type,
        "seal_number": seal_number,
        "port_code": port_code,
    }


# ---------------------------------------------------------------------------
# Examination holds
# ---------------------------------------------------------------------------
def unscheduled_hold_payload(
    movement_id: str,
    port_id: str,
    hold_type: str = "DOCUMENT",
    reason_code: str = "MANIFEST_REVIEW",
) -> JsonDict:
    """A documentary or partner-agency hold: both window fields are omitted."""
    return {
        "movement_id": movement_id,
        "port_id": port_id,
        "hold_type": hold_type,
        "reason_code": reason_code,
    }


def scheduled_hold_payload(
    movement_id: str,
    port_id: str,
    scheduled_start: str,
    scheduled_end: str,
    hold_type: str = "EXAM_PHYSICAL",
    reason_code: str = "TARGETED_EXAM",
) -> JsonDict:
    """A bay-consuming examination hold: both window fields are required."""
    return {
        "movement_id": movement_id,
        "port_id": port_id,
        "hold_type": hold_type,
        "reason_code": reason_code,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }


def hold_release_payload(
    findings_code: str = "CLEAR", discrepancy_pieces: Optional[int] = None
) -> JsonDict:
    payload: JsonDict = {"findings_code": findings_code}
    if discrepancy_pieces is not None:
        payload["discrepancy_pieces"] = discrepancy_pieces
    return payload


# ---------------------------------------------------------------------------
# Amendment requests
# ---------------------------------------------------------------------------
def extension_payload(
    movement_id: str,
    expected_movement_version: int,
    requested_days: int,
    justification_code: str = "PORT_CONGESTION",
) -> JsonDict:
    return {
        "movement_id": movement_id,
        "amendment_type": "EXTENSION",
        "expected_movement_version": expected_movement_version,
        "requested_days": requested_days,
        "justification_code": justification_code,
    }


def diversion_payload(
    movement_id: str,
    expected_movement_version: int,
    requested_destination_port_code: str,
    requested_in_bond_type: str = "IT",
    justification_code: str = "CONSIGNEE_CHANGE",
) -> JsonDict:
    return {
        "movement_id": movement_id,
        "amendment_type": "DIVERSION",
        "expected_movement_version": expected_movement_version,
        "requested_destination_port_code": requested_destination_port_code,
        "requested_in_bond_type": requested_in_bond_type,
        "justification_code": justification_code,
    }


def amendment_approval_payload(
    decision_reason_code: str, granted_days: Optional[int] = None
) -> JsonDict:
    payload: JsonDict = {
        "decision": "APPROVE",
        "decision_reason_code": decision_reason_code,
    }
    if granted_days is not None:
        payload["granted_days"] = granted_days
    return payload


def amendment_denial_payload(decision_reason_code: str = "NOT_JUSTIFIED") -> JsonDict:
    return {"decision": "DENY", "decision_reason_code": decision_reason_code}


# ---------------------------------------------------------------------------
# Movement reports
# ---------------------------------------------------------------------------
def arrival_report_payload(
    movement_id: str, port_id: str, packages_reported: int = PACKAGE_COUNT
) -> JsonDict:
    return {
        "movement_id": movement_id,
        "port_id": port_id,
        "report_type": "ARRIVAL",
        "packages_reported": packages_reported,
    }


def export_report_payload(
    movement_id: str, port_id: str, **overrides: Any
) -> JsonDict:
    return _merge(
        {
            "movement_id": movement_id,
            "port_id": port_id,
            "report_type": "EXPORT",
            "packages_reported": PACKAGE_COUNT,
        },
        overrides,
    )


def export_proof_payload(
    proof_of_export_ref: str = "BOL-88123",
    export_conveyance_ref: str = "VESSEL-ATLANTIC-9",
) -> JsonDict:
    return {
        "proof_of_export_ref": proof_of_export_ref,
        "export_conveyance_ref": export_conveyance_ref,
    }


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
def claim_payload(
    movement_id: str, claim_type: str, reason_code: Optional[str] = None
) -> JsonDict:
    payload: JsonDict = {"movement_id": movement_id, "claim_type": claim_type}
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return payload


def claim_payment_payload(paid_amount: float) -> JsonDict:
    return {"action": "PAY", "paid_amount": paid_amount}


def claim_cancellation_payload(reason_code: str = "CLAIM_ISSUED_IN_ERROR") -> JsonDict:
    return {"action": "CANCEL", "reason_code": reason_code}


# ---------------------------------------------------------------------------
# Petitions
# ---------------------------------------------------------------------------
#: The four-factor petition used throughout: 0.20 + 0.15 skipped, 0.10, 0.25,
#: 0.30 — a raw 0.85 that the round-one cap clamps to 0.50.
FOUR_FACTOR_MITIGATION = [
    "FIRST_VIOLATION",
    "CARGO_SECURED_INTACT",
    "CBP_ADMIN_DELAY",
    "EXTRAORDINARY_CIRCUMSTANCE",
]


def petition_payload(
    claim_id: str,
    expected_claim_version: int,
    mitigation_factors: List[str],
    narrative_reference: str,
) -> JsonDict:
    return {
        "claim_id": claim_id,
        "expected_claim_version": expected_claim_version,
        "mitigation_factors": mitigation_factors,
        "narrative_reference": narrative_reference,
    }


def petition_supplement_payload(
    mitigation_factors: List[str], narrative_reference: str
) -> JsonDict:
    return {
        "mitigation_factors": mitigation_factors,
        "narrative_reference": narrative_reference,
    }


def petition_decision_payload(decision: str, decision_reason_code: str) -> JsonDict:
    return {"decision": decision, "decision_reason_code": decision_reason_code}


# ---------------------------------------------------------------------------
# Compliance sweeps
# ---------------------------------------------------------------------------
def sweep_payload(note: str) -> JsonDict:
    return {"note": note}
