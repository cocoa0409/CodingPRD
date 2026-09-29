"""Payload factories — one per PRD write endpoint, input fields only.

Every factory returns a plain dict and accepts ``**overrides`` so a test can pin the
one value it cares about while the rest stay at conforming defaults. Values default to
a single self-consistent scenario: lessee ``MCG`` on the B738 airframe ``G-ACMI`` under a
2026-09-01..2026-12-31 term.
"""

from .constants import TEST_DEFAULTS


def create_lessee_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["LESSEE_NAME"],
        "icao_code": TEST_DEFAULTS["LESSEE_ICAO"],
        "home_base_icao": TEST_DEFAULTS["HOME_BASE_ICAO"],
        "credit_limit_usd_cents": TEST_DEFAULTS["CREDIT_LIMIT_USD_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_aircraft_payload(**overrides) -> dict:
    payload = {
        "tail_number": TEST_DEFAULTS["TAIL_NUMBER"],
        "type_designator": TEST_DEFAULTS["TYPE_DESIGNATOR"],
        "type_family": TEST_DEFAULTS["TYPE_FAMILY"],
        "seat_count": TEST_DEFAULTS["SEAT_COUNT"],
        "mtow_kg": TEST_DEFAULTS["MTOW_KG"],
        "maintenance_program_ref": TEST_DEFAULTS["MAINTENANCE_PROGRAM_REF"],
        "airframe_hours_total": 24000.00,
        "hours_since_last_check": 120.00,
        "cycles_since_last_check": 40,
    }
    payload.update(overrides)
    return payload


def create_crew_member_payload(**overrides) -> dict:
    payload = {
        "full_name": "A Hallam",
        "employee_no": "EMP-1001",
        "crew_role": "CAPTAIN",
        "type_ratings": [TEST_DEFAULTS["TYPE_DESIGNATOR"]],
    }
    payload.update(overrides)
    return payload


def create_captain_payload(**overrides) -> dict:
    return create_crew_member_payload(
        **{
            "full_name": "A Hallam",
            "employee_no": "EMP-1001",
            "crew_role": "CAPTAIN",
            **overrides,
        }
    )


def create_first_officer_payload(**overrides) -> dict:
    return create_crew_member_payload(
        **{
            "full_name": "B Okonjo",
            "employee_no": "EMP-1002",
            "crew_role": "FIRST_OFFICER",
            **overrides,
        }
    )


def create_lease_payload(lessee_id: str, primary_aircraft_id: str, **overrides) -> dict:
    payload = {
        "lessee_id": lessee_id,
        "primary_aircraft_id": primary_aircraft_id,
        "term_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "term_end_date": TEST_DEFAULTS["TERM_END_DATE"],
        "block_hour_rate_usd_cents": TEST_DEFAULTS["BLOCK_HOUR_RATE_USD_CENTS"],
        "min_guaranteed_block_hours_per_month": TEST_DEFAULTS[
            "MIN_GUARANTEED_BLOCK_HOURS_PER_MONTH"
        ],
        "shortfall_credit_pct": TEST_DEFAULTS["SHORTFALL_CREDIT_PCT"],
        "crew_provided_by": "LESSOR",
        "maintenance_provided_by": "LESSOR",
        "insurance_provided_by": "LESSOR",
        "operational_control": "LESSOR",
        "substitution_rights": "LESSOR_UNILATERAL",
        "reliability_basis": "DEPARTURE",
        "required_maintenance_program_ref": TEST_DEFAULTS["MAINTENANCE_PROGRAM_REF"],
        "return_hours_since_check_max": 300.00,
        "return_cycles_since_check_max": 120,
        "return_fuel_kg_required": 4000,
        "return_liability_cap_cents": TEST_DEFAULTS["RETURN_LIABILITY_CAP_CENTS"],
        "return_deposit_cents": TEST_DEFAULTS["RETURN_DEPOSIT_CENTS"],
        "redelivery_icao": TEST_DEFAULTS["HOME_BASE_ICAO"],
    }
    payload.update(overrides)
    return payload


def submit_for_approval_payload(**overrides) -> dict:
    payload = {"authority_docket_no": TEST_DEFAULTS["AUTHORITY_DOCKET_NO"]}
    payload.update(overrides)
    return payload


def determination_payload(determination: str = "APPROVED", **overrides) -> dict:
    payload = {"determination": determination}
    payload.update(overrides)
    return payload


def create_insurance_certificate_payload(lease_id: str, **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "certificate_no": TEST_DEFAULTS["CERTIFICATE_NO"],
        "hull_limit_usd_cents": TEST_DEFAULTS["HULL_LIMIT_USD_CENTS"],
        "liability_limit_usd_cents": TEST_DEFAULTS["LIABILITY_LIMIT_USD_CENTS"],
        "breach_of_warranty_endorsed": True,
        "additional_insured_lessee": True,
        "effective_from": "2026-08-15T00:00:00Z",
        "expires_at": "2027-01-31T23:59:59Z",
    }
    payload.update(overrides)
    return payload


def create_crew_qualification_payload(
    crew_member_id: str, lease_id: str, **overrides
) -> dict:
    payload = {"crew_member_id": crew_member_id, "lease_id": lease_id}
    payload.update(overrides)
    return payload


def complete_checkride_payload(**overrides) -> dict:
    payload = {
        "differences_training_completed_on": "2026-08-20",
        "checkride_valid_until": "2027-08-31",
    }
    payload.update(overrides)
    return payload


def create_flight_leg_payload(
    lease_id: str,
    aircraft_id: str,
    captain_id: str,
    first_officer_id: str,
    scheduled_out: str = "2026-09-05T08:00:00Z",
    scheduled_in: str = "2026-09-05T10:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "lease_id": lease_id,
        "aircraft_id": aircraft_id,
        "captain_id": captain_id,
        "first_officer_id": first_officer_id,
        "origin_icao": "EGSS",
        "dest_icao": "LEPA",
        "leg_class": "REVENUE",
        "scheduled_out": scheduled_out,
        "scheduled_in": scheduled_in,
    }
    payload.update(overrides)
    return payload


def dispatch_payload(actual_out: str, **overrides) -> dict:
    payload = {"actual_out": actual_out}
    payload.update(overrides)
    return payload


def complete_leg_payload(actual_in: str, **overrides) -> dict:
    payload = {"actual_in": actual_in}
    payload.update(overrides)
    return payload


def cancel_leg_payload(
    cancelling_party: str = "LESSEE", cancel_reason: str = "COMMERCIAL", **overrides
) -> dict:
    payload = {"cancelling_party": cancelling_party, "cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload


def create_substitution_payload(
    lease_id: str,
    original_aircraft_id: str,
    expected_lease_version: int,
    reason: str = "SCHEDULED_MAINTENANCE",
    effective_from: str = "2026-09-10T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "lease_id": lease_id,
        "original_aircraft_id": original_aircraft_id,
        "reason": reason,
        "effective_from": effective_from,
        "expected_lease_version": expected_lease_version,
    }
    payload.update(overrides)
    return payload


def consent_payload(decision: str = "GRANT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_settlement_invoice_payload(
    period_id: str,
    expected_period_version: int,
    due_on: str = "2026-10-31",
    **overrides,
) -> dict:
    payload = {
        "period_id": period_id,
        "expected_period_version": expected_period_version,
        "due_on": due_on,
    }
    payload.update(overrides)
    return payload


def void_invoice_payload(void_reason: str = "Re-issued after correction", **overrides) -> dict:
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


def create_reliability_report_payload(
    lease_id: str, aircraft_id: str, period_month: str = "2026-09", **overrides
) -> dict:
    payload = {
        "lease_id": lease_id,
        "aircraft_id": aircraft_id,
        "period_month": period_month,
    }
    payload.update(overrides)
    return payload


def review_report_payload(decision: str = "ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def dispute_payload(
    dispute_reason: str = "Credited hours understated", disputed_amount_cents: int = 1000, **overrides
) -> dict:
    payload = {
        "dispute_reason": dispute_reason,
        "disputed_amount_cents": disputed_amount_cents,
    }
    payload.update(overrides)
    return payload


def resolve_dispute_payload(resolution: str = "UPHOLD_SETTLEMENT", **overrides) -> dict:
    payload = {"resolution": resolution}
    payload.update(overrides)
    return payload


def maintenance_event_payload(event_type: str, **overrides) -> dict:
    payload = {"event_type": event_type}
    payload.update(overrides)
    return payload


def inspect_return_payload(
    hours_since_check_at_return: float,
    cycles_since_check_at_return: int,
    fuel_on_board_kg: int,
    discrepancy_codes=None,
    **overrides,
) -> dict:
    payload = {
        "hours_since_check_at_return": hours_since_check_at_return,
        "cycles_since_check_at_return": cycles_since_check_at_return,
        "fuel_on_board_kg": fuel_on_board_kg,
        "discrepancy_codes": discrepancy_codes if discrepancy_codes is not None else [],
    }
    payload.update(overrides)
    return payload


def terminate_lease_payload(termination_reason: str = "Term expiry", **overrides) -> dict:
    payload = {"termination_reason": termination_reason}
    payload.update(overrides)
    return payload


def withdraw_lease_payload(withdrawal_reason: str = "Commercial withdrawal", **overrides) -> dict:
    payload = {"withdrawal_reason": withdrawal_reason}
    payload.update(overrides)
    return payload


def revoke_payload(revocation_reason: str = "Cover withdrawn by underwriter", **overrides) -> dict:
    payload = {"revocation_reason": revocation_reason}
    payload.update(overrides)
    return payload


def clear_conditions_payload(cleared_condition_codes, **overrides) -> dict:
    payload = {"cleared_condition_codes": cleared_condition_codes}
    payload.update(overrides)
    return payload


def close_return_payload(repositioning_leg_id: str, **overrides) -> dict:
    payload = {"repositioning_leg_id": repositioning_leg_id}
    payload.update(overrides)
    return payload
