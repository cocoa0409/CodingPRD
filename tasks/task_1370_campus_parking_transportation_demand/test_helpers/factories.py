"""Payload factories — one per entity, input fields only (PRD §3)."""

from .constants import TERM_END, TERM_START

DEFAULTS = {
    "PATRON_NAME": "Test Patron",
    "CAMPUS_ROLE": "STUDENT",
    "RESIDENCY": "OFF_CAMPUS",
    "COMMUTE_MODE": "DRIVE_ALONE",
    "LOT_CODE": "LOT_1",
    "LOT_NAME": "Test Lot",
    "ZONE": "CORE",
    "CAPACITY_TOTAL": 50,
    "PERMIT_CODE": "GEN",
    "ELIGIBLE_ROLES": ["STUDENT", "STAFF", "FACULTY"],
    "RESIDENCY_RULE": "ANY",
    "BASE_FEE_CENTS": 80000,
    "PRORATION_POLICY": "PRORATED_WEEKLY",
    "QUOTA": 5,
    "PLATE_NUMBER": "AAA111",
    "VIOLATION_TYPE": "NO_VALID_PERMIT",
    "APPEAL_REASON": "Contest the citation",
    "CLOSURE_REASON": "EVENT",
    "EVENT_NAME": "GameDay",
    "RESERVED_SPACES": 10,
    "CLOSURE_STARTS_AT": "2026-08-10T00:00:00Z",
    "CLOSURE_ENDS_AT": "2026-08-20T00:00:00Z",
    "FUND_CODE": "PTS_OPERATING",
    "ROUTE_CODE": "BLUE_LOOP",
    "FLEET_GROUP": "FLEET_A",
    "WINDOW_START": 480,
    "WINDOW_END": 960,
    "HEADWAY_MINUTES": 30,
    "VEHICLE_CAPACITY": 25,
    "PROJECTED_RIDERSHIP": 300,
    "ANNUAL_COST_CENTS": 10000,
    "LOG_DATE": "2026-08-03",
    "BOARDINGS": 100,
}


def create_patron_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PATRON_NAME"],
        "campus_role": DEFAULTS["CAMPUS_ROLE"],
        "residency": DEFAULTS["RESIDENCY"],
        "primary_commute_mode": DEFAULTS["COMMUTE_MODE"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_code": DEFAULTS["LOT_CODE"],
        "name": DEFAULTS["LOT_NAME"],
        "zone": DEFAULTS["ZONE"],
        "capacity_total": DEFAULTS["CAPACITY_TOTAL"],
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(lot_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "permit_code": DEFAULTS["PERMIT_CODE"],
        "eligible_roles": list(DEFAULTS["ELIGIBLE_ROLES"]),
        "residency_rule": DEFAULTS["RESIDENCY_RULE"],
        "base_fee_cents": DEFAULTS["BASE_FEE_CENTS"],
        "proration_policy": DEFAULTS["PRORATION_POLICY"],
        "term_start": TERM_START,
        "term_end": TERM_END,
        "quota": DEFAULTS["QUOTA"],
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(patron_id: str, allocation_id: str, **overrides) -> dict:
    defaults = {"patron_id": patron_id, "allocation_id": allocation_id}
    defaults.update(overrides)
    return defaults


def create_claim_payload(expected_allocation_version: int, **overrides) -> dict:
    defaults = {"expected_allocation_version": expected_allocation_version}
    defaults.update(overrides)
    return defaults


def create_permit_payload(
    patron_id: str,
    allocation_id: str,
    plate_number: str,
    expected_allocation_version: int,
    **overrides,
) -> dict:
    defaults = {
        "patron_id": patron_id,
        "allocation_id": allocation_id,
        "plate_number": plate_number,
        "expected_allocation_version": expected_allocation_version,
    }
    defaults.update(overrides)
    return defaults


def create_citation_payload(lot_id: str, plate_number: str, violation_type: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "plate_number": plate_number,
        "violation_type": violation_type,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(reason: str = None, **overrides) -> dict:
    defaults = {"reason": reason or DEFAULTS["APPEAL_REASON"]}
    defaults.update(overrides)
    return defaults


def create_decision_payload(outcome: str, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_closure_payload(lot_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "reason": DEFAULTS["CLOSURE_REASON"],
        "event_name": DEFAULTS["EVENT_NAME"],
        "reserved_spaces": DEFAULTS["RESERVED_SPACES"],
        "starts_at": DEFAULTS["CLOSURE_STARTS_AT"],
        "ends_at": DEFAULTS["CLOSURE_ENDS_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_shuttle_route_payload(fund_id: str, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "route_code": DEFAULTS["ROUTE_CODE"],
        "fleet_group": DEFAULTS["FLEET_GROUP"],
        "service_window_start_minutes": DEFAULTS["WINDOW_START"],
        "service_window_end_minutes": DEFAULTS["WINDOW_END"],
        "headway_minutes": DEFAULTS["HEADWAY_MINUTES"],
        "vehicle_capacity": DEFAULTS["VEHICLE_CAPACITY"],
        "projected_daily_ridership": DEFAULTS["PROJECTED_RIDERSHIP"],
        "annual_operating_cost_cents": DEFAULTS["ANNUAL_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_ridership_log_payload(**overrides) -> dict:
    defaults = {"log_date": DEFAULTS["LOG_DATE"], "boardings": DEFAULTS["BOARDINGS"]}
    defaults.update(overrides)
    return defaults


def create_incentive_account_payload(patron_id: str, **overrides) -> dict:
    defaults = {"patron_id": patron_id}
    defaults.update(overrides)
    return defaults


def create_accrual_payload(days_commuted: int, **overrides) -> dict:
    defaults = {"days_commuted": days_commuted}
    defaults.update(overrides)
    return defaults


def create_redeem_payload(blocks: int, **overrides) -> dict:
    defaults = {"blocks": blocks}
    defaults.update(overrides)
    return defaults


def create_fund_payload(**overrides) -> dict:
    defaults = {"fund_code": DEFAULTS["FUND_CODE"]}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
