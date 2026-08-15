"""Composite setup helpers for the CNG station API (PRD §2.5, §3).

Every helper builds its preconditions from scratch against a fresh server and
uses get_success_data() internally so setup failures surface as clear errors.
Entity-backed roles always thread the real entity id into their headers.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    authorize_session_payload,
    create_backup_arrangement_payload,
    create_calibration_record_payload,
    create_compressor_payload,
    create_dispenser_payload,
    create_fleet_account_payload,
    create_fleet_card_payload,
    create_maintenance_window_payload,
    create_pricing_policy_payload,
    create_safety_inspection_payload,
    create_station_payload,
    create_supply_contract_payload,
    create_tax_credit_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_fleet_account_manager_headers,
    make_fleet_driver_headers,
    make_station_manager_headers,
)

OP = TEST_USERS["network_operator_headers"]
SM = TEST_USERS["station_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Tier 1/2: entity construction and state progression
# ---------------------------------------------------------------------------

def create_station(**overrides) -> dict:
    """Create a station (born SETUP with OUTAGE posture, PRD §3.1)."""
    resp = api_client.create_station(create_station_payload(**overrides), OP)
    return get_success_data(resp)


def add_compressor(station_id: str, **overrides) -> dict:
    resp = api_client.create_compressor(create_compressor_payload(station_id, **overrides), SM)
    return get_success_data(resp)


def add_dispenser(station_id: str, **overrides) -> dict:
    resp = api_client.create_dispenser(create_dispenser_payload(station_id, **overrides), SM)
    return get_success_data(resp)


def activate_station(station_id: str) -> dict:
    return get_success_data(api_client.activate_station(station_id, OP))


def create_active_station(num_compressors: int = 1, num_dispensers: int = 1, **overrides) -> dict:
    """Station + compressor(s) + dispenser(s), activated. Returns a dict with
    the station, and lists of compressors and dispensers."""
    station = create_station(**overrides)
    compressors = [add_compressor(station["id"]) for _ in range(num_compressors)]
    dispensers = [add_dispenser(station["id"]) for _ in range(num_dispensers)]
    station = activate_station(station["id"])
    return {"station": station, "compressors": compressors, "dispensers": dispensers}


def get_station(station_id: str) -> dict:
    return get_success_data(api_client.get_station(station_id, OP))


def get_station_version(station_id: str) -> int:
    return get_station(station_id)["version"]


def get_account(account_id: str) -> dict:
    return get_success_data(api_client.get_fleet_account(account_id, OP))


def get_account_version(account_id: str) -> int:
    return get_account(account_id)["version"]


def get_account_balance(account_id: str) -> int:
    return get_account(account_id)["outstanding_balance_cents"]


def create_pricing_policy(
    station_id: str,
    expected_station_version: Optional[int] = None,
    **overrides,
) -> dict:
    """Create a pricing policy, OCC-guarded on the station version (PRD §2.9)."""
    if expected_station_version is None:
        expected_station_version = get_station_version(station_id)
    resp = api_client.create_pricing_policy(
        create_pricing_policy_payload(
            station_id, expected_station_version, **overrides
        ),
        OP,
    )
    return get_success_data(resp)


def create_fleet_account(**overrides) -> dict:
    resp = api_client.create_fleet_account(create_fleet_account_payload(**overrides), OP)
    return get_success_data(resp)


def create_fleet_card(account_id: str, **overrides) -> dict:
    """Issue a card as the account's own FleetAccountManager (PRD §3.3)."""
    resp = api_client.create_fleet_card(
        create_fleet_card_payload(account_id, **overrides),
        make_fleet_account_manager_headers(account_id),
    )
    return get_success_data(resp)


def create_account_with_card(
    credit_limit_cents: int = TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    daily_gge_limit: float = TEST_DEFAULTS["DAILY_GGE_LIMIT"],
    **account_overrides,
) -> dict:
    account = create_fleet_account(credit_limit_cents=credit_limit_cents, **account_overrides)
    card = create_fleet_card(account["id"], daily_gge_limit=daily_gge_limit)
    return {"account": account, "card": card}


def calibrate(dispenser_id: str, measured_error_pct: float) -> dict:
    resp = api_client.create_calibration_record(
        create_calibration_record_payload(dispenser_id, measured_error_pct=measured_error_pct), SM
    )
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OP))


def create_window(station_id: str, compressor_id: Optional[str] = None, **overrides) -> dict:
    payload = create_maintenance_window_payload(station_id, **overrides)
    if compressor_id is not None:
        payload["compressor_id"] = compressor_id
    return get_success_data(api_client.create_maintenance_window(payload, SM))


def create_backup(station_id: str, **overrides) -> dict:
    resp = api_client.create_backup_arrangement(
        create_backup_arrangement_payload(station_id, **overrides), SM
    )
    return get_success_data(resp)


def create_inspection(station_id: str, **overrides) -> dict:
    resp = api_client.create_safety_inspection(
        create_safety_inspection_payload(station_id, **overrides), SM
    )
    return get_success_data(resp)


def complete_inspection(inspection_id: str, result: str, performer_id: str,
                        findings: Optional[str] = None) -> dict:
    payload = {"result": result}
    if findings is not None:
        payload["findings"] = findings
    resp = api_client.complete_safety_inspection(
        inspection_id, payload, make_station_manager_headers(performer_id)
    )
    return get_success_data(resp)


def approve_inspection(inspection_id: str, approver_id: str) -> dict:
    resp = api_client.approve_safety_inspection(
        inspection_id, make_compliance_officer_headers(approver_id)
    )
    return get_success_data(resp)


def create_contract(account_id: str, station_id: str, **overrides) -> dict:
    resp = api_client.create_supply_contract(
        create_supply_contract_payload(account_id, station_id, **overrides), OP
    )
    return get_success_data(resp)


def create_active_contract(account_id: str, station_id: str, **overrides) -> dict:
    contract = create_contract(account_id, station_id, **overrides)
    return get_success_data(api_client.activate_supply_contract(contract["id"], OP))


def create_claim(station_id: str, **overrides) -> dict:
    resp = api_client.create_tax_credit_claim(
        create_tax_credit_claim_payload(station_id, **overrides), SM
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: fueling session lifecycle
# ---------------------------------------------------------------------------

def authorize_session(
    card_id: str,
    dispenser_id: str,
    client_ref: str,
    estimated_gge: float = 20.0,
    expected_fleet_account_version: Optional[int] = None,
):
    """Authorize a private session as the card-holding FleetDriver. When the
    expected account version is omitted, it is read fresh first (OCC, PRD §2.9).
    Returns the raw Response so callers can assert success or error."""
    account_id = get_success_data(
        api_client.get_fleet_card(card_id, make_fleet_driver_headers(card_id))
    )["fleet_account_id"]
    if expected_fleet_account_version is None:
        expected_fleet_account_version = get_account_version(account_id)
    payload = authorize_session_payload(
        card_id, dispenser_id, client_ref, estimated_gge, expected_fleet_account_version
    )
    return api_client.authorize_session(payload, make_fleet_driver_headers(card_id))


def authorize_session_ok(
    card_id: str, dispenser_id: str, client_ref: str, estimated_gge: float = 20.0
) -> dict:
    from prd_bench_local_runner.testing import validate_success

    resp = authorize_session(card_id, dispenser_id, client_ref, estimated_gge)
    return validate_success(resp, 201)


def complete_session_ok(session_id: str, card_id: str, metered_mass_kg: float) -> dict:
    from prd_bench_local_runner.testing import validate_success

    resp = api_client.complete_session(
        session_id, {"metered_mass_kg": metered_mass_kg}, make_fleet_driver_headers(card_id)
    )
    return validate_success(resp, 200)


def void_session_ok(session_id: str, headers, reason: Optional[str] = None) -> dict:
    from prd_bench_local_runner.testing import validate_success

    payload = {} if reason is None else {"reason": reason}
    resp = api_client.void_session(session_id, payload, headers)
    return validate_success(resp, 200)


def authorize_and_complete(
    card_id: str,
    dispenser_id: str,
    client_ref: str,
    metered_mass_kg: float,
    estimated_gge: float = 20.0,
) -> dict:
    session = authorize_session_ok(card_id, dispenser_id, client_ref, estimated_gge)
    return complete_session_ok(session["id"], card_id, metered_mass_kg)


# ---------------------------------------------------------------------------
# Tier 2/4: standard composite scenarios
# ---------------------------------------------------------------------------

def setup_fueling_station(
    access_mode: str = "DUAL",
    fuel_type: str = "CNG",
    price_per_gge_cents: int = TEST_DEFAULTS["PRICE_PER_GGE_CENTS"],
    calibrate_error_pct: Optional[float] = None,
    **station_overrides,
) -> dict:
    """ACTIVE station + compressor + dispenser + PRIVATE pricing policy.

    When calibrate_error_pct is given, a calibration is recorded on the
    dispenser after activation (0.50 -> PASS, factor 0.995; 0.51 -> FAIL).
    """
    env = create_active_station(access_mode=access_mode, **station_overrides)
    dispenser = env["dispensers"][0]
    if calibrate_error_pct is not None:
        calibrate(dispenser["id"], calibrate_error_pct)
        dispenser = get_success_data(api_client.get_dispenser(dispenser["id"], SM))
    policy = create_pricing_policy(
        env["station"]["id"], fuel_type=fuel_type, price_per_gge_cents=price_per_gge_cents
    )
    return {
        "station": get_station(env["station"]["id"]),
        "compressor": env["compressors"][0],
        "compressors": env["compressors"],
        "dispenser": dispenser,
        "dispensers": [dispenser] + list(env["dispensers"][1:]),
        "policy": policy,
    }


def setup_fueling_ready(
    access_mode: str = "DUAL",
    fuel_type: str = "CNG",
    price_per_gge_cents: int = TEST_DEFAULTS["PRICE_PER_GGE_CENTS"],
    credit_limit_cents: int = TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    daily_gge_limit: float = TEST_DEFAULTS["DAILY_GGE_LIMIT"],
    calibrate_error_pct: Optional[float] = None,
    **station_overrides,
) -> dict:
    """setup_fueling_station + an ACTIVE fleet account and card."""
    env = setup_fueling_station(
        access_mode=access_mode,
        fuel_type=fuel_type,
        price_per_gge_cents=price_per_gge_cents,
        calibrate_error_pct=calibrate_error_pct,
        **station_overrides,
    )
    party = create_account_with_card(
        credit_limit_cents=credit_limit_cents, daily_gge_limit=daily_gge_limit
    )
    env.update(party)
    return env


def setup_settled_session_scenario(
    session_iso: str = "2026-07-15T12:00:00Z",
    after_iso: str = "2026-08-02T00:00:00Z",
    metered_mass_kg: float = 26.0,
    calibrate_error_pct: Optional[float] = 0.50,
    **overrides,
) -> dict:
    """Fueling-ready station with one session completed in a prior month and
    swept to SETTLED by the month-close sweep (PRD §2.5).

    The logical clock is moved to session_iso for the fueling, then advanced
    past month end so the session lands in SETTLED.
    """
    env = setup_fueling_ready(calibrate_error_pct=calibrate_error_pct, **overrides)
    set_clock(session_iso)
    session = authorize_and_complete(
        env["card"]["id"], env["dispenser"]["id"], "CR-SETTLED-1", metered_mass_kg
    )
    set_clock(after_iso)
    session = get_success_data(
        api_client.get_fueling_session(session["id"], make_fleet_driver_headers(env["card"]["id"]))
    )
    env["session"] = session
    return env
