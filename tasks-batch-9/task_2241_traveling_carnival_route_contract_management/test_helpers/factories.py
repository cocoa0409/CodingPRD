"""Payload factories — one per write operation, request-input fields only.

Every factory supplies only the fields the PRD declares as inputs, with the
required ones always present and the optional ones omitted unless a caller
overrides them, so that PRD-declared defaults stay observable.
"""

from .constants import (
    STOP_CLOSE_DATE,
    STOP_LOAD_IN_START,
    STOP_OPEN_DATE,
    STOP_TEARDOWN_DEADLINE,
    TEST_DEFAULTS,
)


def _merge(defaults: dict, overrides: dict) -> dict:
    payload = dict(defaults)
    payload.update(overrides)
    return payload


# ─── Reference data ───────────────────────────────────────────────────────────

def create_jurisdiction_payload(**overrides) -> dict:
    return _merge(
        {
            "state_code": TEST_DEFAULTS["STATE_CODE"],
            "name": TEST_DEFAULTS["STATE_NAME"],
            "permit_lead_days": TEST_DEFAULTS["PERMIT_LEAD_DAYS"],
            "amusement_tax_pct": TEST_DEFAULTS["AMUSEMENT_TAX_PCT"],
            "permit_fee_cents": TEST_DEFAULTS["PERMIT_FEE_CENTS"],
        },
        overrides,
    )


def create_venue_payload(jurisdiction_id: str, **overrides) -> dict:
    return _merge(
        {
            "jurisdiction_id": jurisdiction_id,
            "name": TEST_DEFAULTS["VENUE_NAME"],
            "city": TEST_DEFAULTS["VENUE_CITY"],
            "lot_area_sqft": TEST_DEFAULTS["LOT_AREA_SQFT"],
            "power_amps_available": TEST_DEFAULTS["POWER_AMPS_AVAILABLE"],
            "expected_attendance": TEST_DEFAULTS["EXPECTED_ATTENDANCE"],
            "lot_surface": "GRAVEL",
        },
        overrides,
    )


def create_ride_payload(**overrides) -> dict:
    return _merge(
        {
            "name": TEST_DEFAULTS["MAJOR_RIDE_NAME"],
            "ride_class": "MAJOR",
            "footprint_sqft": TEST_DEFAULTS["MAJOR_FOOTPRINT_SQFT"],
            "power_amps": TEST_DEFAULTS["MAJOR_POWER_AMPS"],
            "crew_size_setup": 6,
            "setup_hours": 8,
            "axle_count": 4,
        },
        overrides,
    )


def create_worker_payload(**overrides) -> dict:
    return _merge(
        {
            "full_name": TEST_DEFAULTS["WORKER_NAME"],
            "employment_type": "PERMANENT",
            "hourly_rate_cents": TEST_DEFAULTS["HOURLY_RATE_CENTS"],
        },
        overrides,
    )


# ─── The season itinerary ─────────────────────────────────────────────────────

def create_route_payload(**overrides) -> dict:
    return _merge(
        {
            "name": TEST_DEFAULTS["ROUTE_NAME"],
            "season_year": TEST_DEFAULTS["SEASON_YEAR"],
            "home_base_state": TEST_DEFAULTS["HOME_BASE_STATE"],
        },
        overrides,
    )


def create_route_stop_payload(route_id: str, venue_id: str, **overrides) -> dict:
    return _merge(
        {
            "route_id": route_id,
            "venue_id": venue_id,
            "load_in_start": STOP_LOAD_IN_START,
            "open_date": STOP_OPEN_DATE,
            "close_date": STOP_CLOSE_DATE,
            "teardown_deadline": STOP_TEARDOWN_DEADLINE,
        },
        overrides,
    )


# ─── The fair deal ────────────────────────────────────────────────────────────

def create_contract_payload(route_stop_id: str, **overrides) -> dict:
    return _merge(
        {
            "route_stop_id": route_stop_id,
            "counterparty_name": TEST_DEFAULTS["COUNTERPARTY_NAME"],
            "revenue_split_pct_operator": TEST_DEFAULTS["REVENUE_SPLIT_PCT_OPERATOR"],
        },
        overrides,
    )


def counter_contract_payload(**overrides) -> dict:
    """Every term on a counter is optional; the factory carries only overrides."""
    return dict(overrides)


# ─── Rides on the lot ─────────────────────────────────────────────────────────

def create_ride_allocation_payload(
    ride_id: str, route_stop_id: str, expected_route_stop_version: int, **overrides
) -> dict:
    return _merge(
        {
            "ride_id": ride_id,
            "route_stop_id": route_stop_id,
            "expected_route_stop_version": expected_route_stop_version,
        },
        overrides,
    )


# ─── Permits and inspections ──────────────────────────────────────────────────

def create_permit_application_payload(
    route_stop_id: str, permit_type: str, valid_from: str, valid_until: str, **overrides
) -> dict:
    return _merge(
        {
            "route_stop_id": route_stop_id,
            "permit_type": permit_type,
            "valid_from": valid_from,
            "valid_until": valid_until,
        },
        overrides,
    )


def permit_decision_payload(decision: str, **overrides) -> dict:
    return _merge({"decision": decision}, overrides)


def create_inspection_order_payload(
    ride_allocation_id: str, authority: str, scheduled_date: str, **overrides
) -> dict:
    return _merge(
        {
            "ride_allocation_id": ride_allocation_id,
            "authority": authority,
            "scheduled_date": scheduled_date,
        },
        overrides,
    )


def inspection_result_payload(result: str, **overrides) -> dict:
    return _merge({"result": result}, overrides)


# ─── Crew ─────────────────────────────────────────────────────────────────────

def create_crew_assignment_payload(
    route_stop_id: str,
    worker_id: str,
    crew_role: str,
    shift_start: str,
    shift_end: str,
    **overrides,
) -> dict:
    return _merge(
        {
            "route_stop_id": route_stop_id,
            "worker_id": worker_id,
            "crew_role": crew_role,
            "shift_start": shift_start,
            "shift_end": shift_end,
        },
        overrides,
    )


# ─── Money ────────────────────────────────────────────────────────────────────

def create_ticket_sale_payload(
    channel: str, units: int, unit_price_cents: int, business_date: str, **overrides
) -> dict:
    return _merge(
        {
            "channel": channel,
            "units": units,
            "unit_price_cents": unit_price_cents,
            "business_date": business_date,
        },
        overrides,
    )


def create_settlement_payload(
    contract_id: str, expected_contract_version: int, **overrides
) -> dict:
    return _merge(
        {
            "contract_id": contract_id,
            "expected_contract_version": expected_contract_version,
        },
        overrides,
    )


def dispute_settlement_payload(dispute_reason: str, **overrides) -> dict:
    return _merge({"dispute_reason": dispute_reason}, overrides)


# ─── Weather and make-goods ───────────────────────────────────────────────────

def create_weather_closure_payload(
    cause: str, closed_from: str, closed_to: str, **overrides
) -> dict:
    return _merge(
        {"cause": cause, "closed_from": closed_from, "closed_to": closed_to}, overrides
    )


def create_make_good_payload(
    weather_closure_id: str, contract_id: str, kind: str, **overrides
) -> dict:
    return _merge(
        {
            "weather_closure_id": weather_closure_id,
            "contract_id": contract_id,
            "kind": kind,
        },
        overrides,
    )


def make_good_response_payload(response: str, **overrides) -> dict:
    return _merge({"response": response}, overrides)
