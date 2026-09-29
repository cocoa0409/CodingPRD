"""Payload factories — one per create/transition endpoint, input fields only.

Money is always a plain integer count of whole cents (PRD §2.5); percentages are
plain floats expressed as decimal fractions; labor hours are floats carried to one
decimal place.
"""
import itertools

from .constants import OPERATORS, TEST_DEFAULTS

_seq = itertools.count(1)


def next_suffix() -> int:
    """Monotonic counter so uniqueness-constrained codes never collide in a test."""
    return next(_seq)


_STATE_CODES = [
    "OH", "MI", "TX", "CA", "NY", "GA", "FL", "PA", "IL", "NC",
    "VA", "WA", "AZ", "CO", "OR", "MN", "MO", "TN", "IN", "WI",
]


def create_state_law_profile_payload(**overrides) -> dict:
    n = next_suffix()
    defaults = {
        "state_code": _STATE_CODES[(n - 1) % len(_STATE_CODES)],
        "markup_cap_pct": TEST_DEFAULTS["MARKUP_CAP_PCT"],
        "labor_rate_method": "RETAIL_SAMPLE",
        "min_sample_repair_orders": TEST_DEFAULTS["MIN_SAMPLE_REPAIR_ORDERS"],
        "max_labor_rate_cents": TEST_DEFAULTS["MAX_LABOR_RATE_CENTS"],
        "deemed_approved_days": TEST_DEFAULTS["DEEMED_APPROVED_DAYS"],
        "appeal_window_days": TEST_DEFAULTS["APPEAL_WINDOW_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_dealer_payload(state_law_profile_id=None, **overrides) -> dict:
    n = next_suffix()
    defaults = {
        "dealer_code": f"DLR-{n:04d}",
        "name": f"Test Dealership {n}",
        "state_law_profile_id": state_law_profile_id,
        "vehicles_in_operation": TEST_DEFAULTS["VEHICLES_IN_OPERATION"],
        "initial_labor_rate_cents": TEST_DEFAULTS["DEALER_LABOR_RATE_CENTS"],
        "initial_parts_markup_pct": TEST_DEFAULTS["DEALER_MARKUP_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    n = next_suffix()
    defaults = {
        "vin": f"1TESTVIN{n:09d}"[:17],
        "model_year": 2024,
        "warranty_start_date": "2024-01-15",
        "in_service_odometer": 10,
        "basic_months": 36,
        "basic_miles": 36000,
        "powertrain_months": 60,
        "powertrain_miles": 60000,
    }
    defaults.update(overrides)
    if len(defaults["vin"]) != 17:
        defaults["vin"] = (defaults["vin"] + "0" * 17)[:17]
    return defaults


def create_labor_operation_payload(**overrides) -> dict:
    n = next_suffix()
    defaults = {
        "op_code": f"OP-{n:04d}",
        "description": f"Test labor operation {n}",
        "standard_time_hours": TEST_DEFAULTS["STANDARD_TIME_HOURS"],
        "max_time_hours": TEST_DEFAULTS["MAX_TIME_HOURS"],
        "category": "BASIC",
        "requires_causal_part": True,
        "causal_failure_group": "BRAKE_HYDRAULIC",
        "overlap_group": f"GROUP-{n:04d}",
    }
    defaults.update(overrides)
    # PRD §3.1: "when that flag is true the operation must name a non-empty
    # `causal_failure_group` ... and when it is false `causal_failure_group` must be
    # null." A caller that flips requires_causal_part to false without also clearing
    # the group would otherwise build a payload the PRD forbids.
    if defaults.get("requires_causal_part") is False and "causal_failure_group" not in overrides:
        defaults["causal_failure_group"] = None
    return defaults


def create_part_payload(**overrides) -> dict:
    n = next_suffix()
    defaults = {
        "part_number": f"PN-{n:05d}",
        "description": f"Test catalog part {n}",
        "dealer_net_cents": TEST_DEFAULTS["PART_DEALER_NET_CENTS"],
        "failure_group": "BRAKE_HYDRAULIC",
        "return_required": False,
        "retention_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_labor_rate_request_payload(dealer_id=None, expected_dealer_version=1, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "requested_labor_rate_cents": 10000,
        "requested_parts_markup_pct": TEST_DEFAULTS["MARKUP_CAP_PCT"],
        "sample_repair_order_count": TEST_DEFAULTS["MIN_SAMPLE_REPAIR_ORDERS"],
        "sample_median_rate_cents": 10000,
        "effective_date": "2026-09-01",
        "expected_dealer_version": expected_dealer_version,
    }
    defaults.update(overrides)
    return defaults


def review_labor_rate_request_payload(action="START_REVIEW", **overrides) -> dict:
    defaults = {"action": action, "note": "Pulled into review for sample verification."}
    defaults.update(overrides)
    return defaults


def decide_labor_rate_request_payload(action="APPROVE", **overrides) -> dict:
    defaults = {"action": action}
    if action == "APPROVE":
        defaults["approved_labor_rate_cents"] = 10000
        defaults["approved_parts_markup_pct"] = TEST_DEFAULTS["MARKUP_CAP_PCT"]
    else:
        defaults["denial_reason"] = "Sample repair orders were not customer-pay."
    defaults.update(overrides)
    return defaults


def create_claim_payload(
    dealer_id=None,
    vehicle_id=None,
    labor_operation_id=None,
    causal_part_id=None,
    **overrides,
) -> dict:
    n = next_suffix()
    defaults = {
        "dealer_id": dealer_id,
        "vehicle_id": vehicle_id,
        "labor_operation_id": labor_operation_id,
        "repair_order_number": f"RO-{n:05d}",
        "repair_date": "2026-03-10",
        "odometer_at_repair": 20000,
        "claimed_labor_hours": TEST_DEFAULTS["STANDARD_TIME_HOURS"],
        "claimed_parts_qty": 3,
        "complaint_text": "Customer reported a soft brake pedal on the highway.",
        "cause_text": "Technician found the master cylinder leaking internally.",
        "correction_text": "Replaced the master cylinder and bled the brake system.",
    }
    if causal_part_id is not None:
        defaults["causal_part_id"] = causal_part_id
    else:
        defaults["claimed_parts_qty"] = 0
    defaults.update(overrides)
    return defaults


def resubmit_claim_payload(**overrides) -> dict:
    defaults = {
        "claimed_labor_hours": TEST_DEFAULTS["STANDARD_TIME_HOURS"],
        "claimed_parts_qty": 3,
        "complaint_text": "Customer reported a soft brake pedal on the highway.",
        "cause_text": "Technician found the master cylinder leaking internally.",
        "correction_text": "Replaced the master cylinder and bled the brake system.",
    }
    defaults.update(overrides)
    return defaults


def adjudicate_claim_payload(decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    if decision == "APPROVE":
        defaults["approved_labor_hours"] = TEST_DEFAULTS["STANDARD_TIME_HOURS"]
        defaults["approved_parts_qty"] = 3
    else:
        defaults["denial_reason"] = "Repair was not supported by the documentation."
    defaults.update(overrides)
    return defaults


def void_claim_payload(**overrides) -> dict:
    defaults = {"void_reason": "Claim was filed against the wrong vehicle."}
    defaults.update(overrides)
    return defaults


def create_goodwill_authorization_payload(expected_claim_version=1, **overrides) -> dict:
    defaults = {
        "requested_amount_cents": 40000,
        "policy_adjustment_pct": 0.10,
        "justification": "Component failed just past the mileage limit; retention case.",
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults


def decide_goodwill_authorization_payload(action="APPROVE", **overrides) -> dict:
    defaults = {"action": action}
    if action == "APPROVE":
        defaults["approved_amount_cents"] = 40000
    else:
        defaults["denial_reason"] = "Goodwill is not warranted for this repair."
    defaults.update(overrides)
    return defaults


def receive_parts_return_payload(received_date="2026-04-01", **overrides) -> dict:
    defaults = {"received_date": received_date}
    defaults.update(overrides)
    return defaults


def analyze_parts_return_payload(analysis_result="DEFECT_CONFIRMED", **overrides) -> dict:
    defaults = {
        "analysis_result": analysis_result,
        "analysis_note": "Bench test reproduced the reported failure mode.",
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(dealer_id=None, expected_dealer_version=1, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "period_start": "2026-01-01",
        "period_end": "2026-07-01",
        "sample_size": 3,
        "lead_auditor_user_id": OPERATORS["AUDITOR_LEAD"],
        "expected_dealer_version": expected_dealer_version,
    }
    defaults.update(overrides)
    return defaults


def create_audit_finding_payload(claim_id=None, unsupported_amount_cents=10000, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "finding_code": "NO_TECHNICIAN_SIGNATURE",
        "unsupported_amount_cents": unsupported_amount_cents,
        "evidence_note": "Repair order carries no technician signature.",
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(contested_finding_ids=None, expected_audit_version=1, **overrides) -> dict:
    defaults = {
        "grounds": "The cited repair orders were signed and are on file at the store.",
        "contested_finding_ids": list(contested_finding_ids or []),
        "expected_audit_version": expected_audit_version,
    }
    defaults.update(overrides)
    return defaults


def decide_appeal_payload(action="DENY", **overrides) -> dict:
    defaults = {"action": action, "decision_note": "Reviewed the dealer's evidence file."}
    defaults.update(overrides)
    return defaults


def set_clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
