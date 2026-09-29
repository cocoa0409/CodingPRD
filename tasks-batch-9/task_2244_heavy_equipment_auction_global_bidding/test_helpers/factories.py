"""Payload factories — one per resource, request-supplied fields only.

Each factory returns the minimal well-formed body; pass keyword overrides to vary
any field, or pass ``field=None`` and pop it when a test needs the field omitted.
"""
import itertools

_serial_counter = itertools.count(1)


def next_serial_number(prefix: str = "CAT-D8T") -> str:
    """A serial number unique within one test run."""
    return f"{prefix}-{next(_serial_counter):04d}"


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

def create_yard_payload(**overrides) -> dict:
    payload = {
        "code": "YRD-DAL",
        "country_code": "US",
        "teardown_buffer_minutes": 120,
        "loadout_deadline_days": 10,
        "currency_code": "USD",
    }
    payload.update(overrides)
    return payload


def create_loadout_bay_payload(yard_id: str, **overrides) -> dict:
    payload = {
        "yard_id": yard_id,
        "bay_number": 1,
        "crane_capacity_kg": 40_000,
    }
    payload.update(overrides)
    return payload


def update_loadout_bay_payload(**overrides) -> dict:
    payload = {"is_active": False}
    payload.update(overrides)
    return payload


def create_consignor_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Lone Star Fleet",
        "country_code": "US",
        "seller_type": "FLEET_OWNER",
        "unreserved_policy_ack": False,
    }
    payload.update(overrides)
    return payload


def create_bidder_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Permian Iron LLC",
        "country_code": "US",
        "tax_id": "US-74-0000001",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Consignment intake
# ---------------------------------------------------------------------------

def create_consignment_payload(consignor_id: str, **overrides) -> dict:
    payload = {
        "consignor_id": consignor_id,
        "agreement_type": "RESERVE",
        "commission_schedule_code": "RESERVE_STD",
        "refurb_authorization_cap_cents": 500_000,
        "advance_paid_cents": 0,
    }
    payload.update(overrides)
    return payload


def intake_decision_payload(decision: str = "ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_lot_payload(consignment_id: str, **overrides) -> dict:
    payload = {
        "consignment_id": consignment_id,
        "make": "Caterpillar",
        "model": "D8T",
        "model_year": 2019,
        "serial_number": next_serial_number(),
        "hour_meter_reading": 6_200,
        "weight_kg": 36_000,
        "title_required": False,
        "reserve_price_cents": 8_000_000,
    }
    payload.update(overrides)
    return payload


def withdraw_lot_payload(**overrides) -> dict:
    payload = {"withdrawal_reason": "seller retained the machine"}
    payload.update(overrides)
    return payload


def lien_search_payload(**overrides) -> dict:
    payload = {"lien_search_reference": "LS-0001"}
    payload.update(overrides)
    return payload


def lien_result_payload(encumbrance_found: bool = False, **overrides) -> dict:
    payload = {"encumbrance_found": encumbrance_found}
    if encumbrance_found:
        payload["lienholder_name"] = "First Equipment Bank"
    payload.update(overrides)
    return payload


def lien_release_payload(**overrides) -> dict:
    payload = {"release_document_ref": "REL-0001"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Inspection and refurbishment
# ---------------------------------------------------------------------------

def create_condition_report_payload(**overrides) -> dict:
    payload = {
        "structural_score": 90.0,
        "powertrain_score": 90.0,
        "hydraulics_score": 90.0,
        "tires_score": 90.0,
        "observed_hour_meter_reading": 6_200,
        "hour_meter_verified": True,
    }
    payload.update(overrides)
    return payload


def rescore_condition_report_payload(**overrides) -> dict:
    payload = {
        "structural_score": 88.0,
        "powertrain_score": 88.0,
        "hydraulics_score": 88.0,
        "tires_score": 88.0,
    }
    payload.update(overrides)
    return payload


def create_refurbishment_order_payload(lot_id: str, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "scope_note": "replace hydraulic hoses and repaint",
        "estimated_cost_cents": 300_000,
    }
    payload.update(overrides)
    return payload


def refurbishment_transition_payload(action: str, **overrides) -> dict:
    """`action` is one of START, SUBMIT_QA, QA_REWORK or QA_PASS."""
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Auction scheduling and catalogue
# ---------------------------------------------------------------------------

def create_auction_payload(yard_id: str, **overrides) -> dict:
    payload = {
        "yard_id": yard_id,
        "kind": "LIVE_ONSITE",
        "reserve_policy": "RESERVE_ALLOWED",
        "premium_schedule_code": "STANDARD",
        "window_start": "2026-08-10T14:00:00Z",
        "window_end": "2026-08-10T22:00:00Z",
    }
    payload.update(overrides)
    return payload


def reschedule_auction_payload(window_start: str, window_end: str, **overrides) -> dict:
    payload = {"window_start": window_start, "window_end": window_end}
    payload.update(overrides)
    return payload


def lot_assignment_payload(lot_id: str, **overrides) -> dict:
    payload = {"lot_id": lot_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Buyer onboarding and bidding
# ---------------------------------------------------------------------------

def create_deposit_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "reference": "WIRE-US-1"}
    payload.update(overrides)
    return payload


def create_bidder_registration_payload(
    bidder_id: str, auction_id: str, deposit_hold_cents: int, **overrides
) -> dict:
    payload = {
        "bidder_id": bidder_id,
        "auction_id": auction_id,
        "deposit_hold_cents": deposit_hold_cents,
        "financing_requested": False,
    }
    payload.update(overrides)
    return payload


def credit_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    if decision == "APPROVE":
        payload["approved_credit_limit_cents"] = 0
    payload.update(overrides)
    return payload


def create_bid_payload(
    registration_id: str, lot_id: str, amount_cents: int, **overrides
) -> dict:
    payload = {
        "registration_id": registration_id,
        "lot_id": lot_id,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Provisional-sale negotiation
# ---------------------------------------------------------------------------

def counteroffer_payload(counter_price_cents: int, expected_sale_version: int, **overrides) -> dict:
    payload = {
        "counter_price_cents": counter_price_cents,
        "expected_sale_version": expected_sale_version,
    }
    payload.update(overrides)
    return payload


def counter_response_payload(decision: str = "ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def reject_sale_payload(**overrides) -> dict:
    payload = {"reject_reason": "the bid falls short of the seller's floor"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def create_payment_payload(invoice_id: str, amount_cents: int, **overrides) -> dict:
    payload = {
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "method": "WIRE",
        "currency_code": "USD",
    }
    payload.update(overrides)
    return payload


def fee_waiver_payload(waiver_cents: int, **overrides) -> dict:
    payload = {"waiver_cents": waiver_cents, "reason": "goodwill adjustment"}
    payload.update(overrides)
    return payload


def abandon_invoice_payload(**overrides) -> dict:
    payload = {"reason": "the buyer walked away from the machine"}
    payload.update(overrides)
    return payload


def create_consignor_settlement_payload(sale_id: str, **overrides) -> dict:
    payload = {"sale_id": sale_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Export and load-out
# ---------------------------------------------------------------------------

def create_export_packet_payload(
    invoice_id: str, destination_country_code: str, **overrides
) -> dict:
    payload = {
        "invoice_id": invoice_id,
        "destination_country_code": destination_country_code,
    }
    payload.update(overrides)
    return payload


def export_packet_transition_payload(action: str, **overrides) -> dict:
    """`action` is one of ATTACH_TITLE, FILE_CUSTOMS, CLEAR, REJECT or REOPEN."""
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_loadout_slot_payload(
    invoice_id: str,
    bay_id: str,
    expected_invoice_version: int,
    slot_start: str,
    slot_end: str,
    tonnage_kg: int,
    **overrides,
) -> dict:
    payload = {
        "invoice_id": invoice_id,
        "bay_id": bay_id,
        "expected_invoice_version": expected_invoice_version,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "transport_mode": "HOUSE_BROKERED",
        "tonnage_kg": tonnage_kg,
    }
    payload.update(overrides)
    return payload


def check_in_loadout_slot_payload(**overrides) -> dict:
    """Check-in carries no body of its own; arrival is judged from the logical clock."""
    payload: dict = {}
    payload.update(overrides)
    return payload


def complete_loadout_slot_payload(gate_pass_ref: str = "GP-0001", **overrides) -> dict:
    payload = {"gate_pass_ref": gate_pass_ref}
    payload.update(overrides)
    return payload


def cancel_loadout_slot_payload(
    outcome: str = "CANCELLED", cancel_reason: str = "transport rescheduled by the buyer",
    **overrides,
) -> dict:
    payload = {"outcome": outcome, "cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload
