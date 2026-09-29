"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def client_contract_payload(**overrides) -> dict:
    """A COST_PLUS contract by default: it carries not_to_exceed_cents and
    leaves management_fee_cents null."""
    payload = {
        "client_name": "Northwind Manufacturing",
        "site_code": "NWM-01",
        "fee_structure": "COST_PLUS",
        "staffing_model": "OPERATOR_EMPLOYED",
        "budgeted_staff_fte": 3.5,
        "participation_target_pct": 35,
        "term_start_on": TEST_DEFAULTS["TERM_START_ON"],
        "term_end_on": TEST_DEFAULTS["TERM_END_ON"],
        "not_to_exceed_cents": TEST_DEFAULTS["NOT_TO_EXCEED_CENTS"],
    }
    payload.update(overrides)
    return payload


def management_fee_contract_payload(**overrides) -> dict:
    """A MANAGEMENT_FEE contract: it carries management_fee_cents and leaves
    not_to_exceed_cents null."""
    payload = {
        "client_name": "Axle Logistics",
        "site_code": "AXL-01",
        "fee_structure": "MANAGEMENT_FEE",
        "staffing_model": "HYBRID",
        "budgeted_staff_fte": 2.0,
        "participation_target_pct": 30,
        "term_start_on": TEST_DEFAULTS["TERM_START_ON"],
        "term_end_on": TEST_DEFAULTS["TERM_END_ON"],
        "management_fee_cents": TEST_DEFAULTS["MANAGEMENT_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def amendment_payload(**overrides) -> dict:
    payload = {
        "fee_structure": "COST_PLUS",
        "staffing_model": "OPERATOR_EMPLOYED",
        "budgeted_staff_fte": 4.0,
        "participation_target_pct": 40,
        "term_start_on": "2027-07-01",
        "term_end_on": "2028-06-30",
        "not_to_exceed_cents": 6_000_000,
    }
    payload.update(overrides)
    return payload


def staff_member_payload(contract_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "full_name": "Ravi Patel",
        "role_type": "GROUP_EX_INSTRUCTOR",
        "employment_type": "OPERATOR_EMPLOYED",
        "hourly_cost_cents": TEST_DEFAULTS["INSTRUCTOR_HOURLY_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def staff_credential_payload(staff_member_id, **overrides) -> dict:
    payload = {
        "staff_member_id": staff_member_id,
        "credential_type": "GROUP_EX_CERT",
        "issuer": "ACE",
        "credential_number": "ACE-4410",
        "expires_on": TEST_DEFAULTS["CREDENTIAL_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def facility_room_payload(contract_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "room_name": "Studio A",
        "room_type": "STUDIO",
        "max_occupancy": 30,
    }
    payload.update(overrides)
    return payload


def inspection_payload(**overrides) -> dict:
    payload = {
        "inspection_on": "2026-08-01",
        "cleanliness_score": 92,
        "deficiency_count": 0,
    }
    payload.update(overrides)
    return payload


def aed_asset_payload(contract_id, room_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "room_id": room_id,
        "asset_type": "AED",
        "asset_tag": "AED-01",
        "pad_expiry_on": TEST_DEFAULTS["AED_PAD_EXPIRY_ON"],
        "battery_expiry_on": TEST_DEFAULTS["AED_BATTERY_EXPIRY_ON"],
        "last_inspection_on": TEST_DEFAULTS["AED_LAST_INSPECTION_ON"],
    }
    payload.update(overrides)
    return payload


def cardio_asset_payload(contract_id, room_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "room_id": room_id,
        "asset_type": "CARDIO",
        "asset_tag": "TRD-07",
        "service_interval_days": 90,
    }
    payload.update(overrides)
    return payload


def program_offering_payload(contract_id, lead_staff_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "lead_staff_id": lead_staff_id,
        "program_type": "GROUP_EXERCISE",
        "title": "Lunch Circuit",
        "participation_target": 4,
        "max_participants_per_session": 6,
        "required_credential_type": "GROUP_EX_CERT",
        "eligible_member_classes": ["EMPLOYEE", "DEPENDENT", "RETIREE"],
    }
    payload.update(overrides)
    return payload


def program_session_payload(offering_id, room_id, **overrides) -> dict:
    payload = {
        "offering_id": offering_id,
        "room_id": room_id,
        "scheduled_start_utc": "2026-08-05T12:00:00Z",
        "scheduled_end_utc": "2026-08-05T12:55:00Z",
        "forecast_attendance": 3,
        "direct_supply_cost_cents": 0,
    }
    payload.update(overrides)
    return payload


def staff_assignment_payload(session_id, staff_member_id, **overrides) -> dict:
    payload = {
        "session_id": session_id,
        "staff_member_id": staff_member_id,
        "role_on_session": "LEAD",
    }
    payload.update(overrides)
    return payload


def member_payload(contract_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "member_class": "EMPLOYEE",
        "full_name": "Ada Kim",
        "employee_number": "E-1001",
        "health_data_consent": False,
    }
    payload.update(overrides)
    return payload


def dependent_payload(contract_id, sponsor_member_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "member_class": "DEPENDENT",
        "full_name": "Nina Kim",
        "sponsor_member_id": sponsor_member_id,
    }
    payload.update(overrides)
    return payload


def waiver_payload(expected_member_version, **overrides) -> dict:
    payload = {
        "waiver_version_code": "WVR-2026A",
        "expires_on": TEST_DEFAULTS["WAIVER_EXPIRES_ON"],
        "acknowledged_health_disclosure": True,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def participation_payload(member_id, session_id, **overrides) -> dict:
    payload = {"member_id": member_id, "session_id": session_id}
    payload.update(overrides)
    return payload


def incident_report_payload(contract_id, reported_by_staff_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "reported_by_staff_id": reported_by_staff_id,
        # At or before the clock's startup instant, since an incident may not be
        # reported as having happened in the future.
        "occurred_at_utc": "2026-07-31T16:05:00Z",
        "severity": "MINOR",
        "cause_category": "OTHER",
        "narrative": "Member reported light-headedness after a class.",
    }
    payload.update(overrides)
    return payload


def invoice_payload(contract_id, expected_contract_version, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "period_month": "2026-08",
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload
