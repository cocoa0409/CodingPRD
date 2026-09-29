"""Composite setup helpers.

Every helper here builds its preconditions from scratch through published
endpoints only, because each test starts against an empty database.  Setup
calls use ``get_success_data`` so a broken precondition reports itself as a
setup failure rather than as a confusing assertion further down the test.

Identity threading: the StationOperator's ``X-User-ID`` is the acting station's
own id, so every ownership-gated call below goes through
``make_station_operator_headers(station["id"])``.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CANONICAL_ASSET,
    CANONICAL_CONTRACT,
    CANONICAL_LOT,
    CANONICAL_PURITY,
    DEFAULT_CLOCK_UTC,
    HALF_LIMIT_PURITY,
    SMALL_CONTRACT,
    SMALL_LOT,
    STANDARD_BANK,
)
from .factories import (
    amend_report_payload,
    clear_safety_event_payload,
    clock_payload,
    complete_fill_payload,
    condemn_inspection_payload,
    delivery_reject_payload,
    dispense_session_payload,
    fuel_payload,
    funding_agreement_payload,
    incentive_claim_payload,
    liquid_tanker_delivery_payload,
    pass_inspection_payload,
    power_supply_contract_payload,
    pressure_vessel_payload,
    production_asset_payload,
    production_lot_payload,
    purity_test_payload,
    responder_certification_payload,
    safety_event_payload,
    station_payload,
    tube_trailer_delivery_payload,
    uptime_report_payload,
    void_meter_payload,
)
from .test_users import TEST_USERS, make_station_operator_headers

# ─── Header shorthands ────────────────────────────────────────────────────

ADMIN = TEST_USERS["platform_admin_headers"]
ENGINEER = TEST_USERS["production_engineer_headers"]
ANALYST = TEST_USERS["quality_analyst_headers"]
ANALYST_2 = TEST_USERS["quality_analyst_2_headers"]
OFFICER = TEST_USERS["safety_officer_headers"]
OFFICER_2 = TEST_USERS["safety_officer_2_headers"]
COMPLIANCE = TEST_USERS["compliance_admin_headers"]
COMPLIANCE_2 = TEST_USERS["compliance_admin_2_headers"]
DISPATCHER = TEST_USERS["logistics_dispatcher_headers"]
AUDITOR = TEST_USERS["program_auditor_headers"]
AUDITOR_2 = TEST_USERS["program_auditor_2_headers"]


# ─── Logical clock ────────────────────────────────────────────────────────


def set_clock(to_iso8601: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    """Move the logical clock and return the reported clock object."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


# ─── Tier 1: single-entity creation ───────────────────────────────────────


def create_funding_agreement(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_funding_agreement(funding_agreement_payload(**overrides), ADMIN)
    )


def create_station(funding_agreement_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_station(station_payload(funding_agreement_id, **overrides), ADMIN)
    )


def commission_vessel(station_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pressure_vessel(
            station_id, pressure_vessel_payload(station_id, **overrides), ADMIN
        )
    )


def record_responder_certification(station_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_responder_certification(
            station_id, responder_certification_payload(station_id, **overrides), OFFICER
        )
    )


def create_production_asset(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_production_asset(production_asset_payload(**overrides), ENGINEER)
    )


def create_power_supply_contract(production_asset_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_power_supply_contract(
            production_asset_id,
            power_supply_contract_payload(production_asset_id, **overrides),
            ENGINEER,
        )
    )


def create_production_lot(production_asset_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_production_lot(
            production_lot_payload(production_asset_id, **overrides), ENGINEER
        )
    )


def record_purity_test(
    production_lot_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_purity_test(
            production_lot_id,
            purity_test_payload(production_lot_id, **overrides),
            headers or ANALYST,
        )
    )


def certify_lot_ci(production_lot_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.certify_lot_ci(production_lot_id, COMPLIANCE))


def release_lot(
    production_lot_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.release_production_lot(production_lot_id, headers or COMPLIANCE)
    )


def read_station(station_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_station(station_id, ADMIN))


def read_station_version(station_id: str) -> int:
    """Read the station's live version, as a session create must do first."""
    return read_station(station_id)["version"]


def read_agreement(agreement_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_funding_agreement(agreement_id, ADMIN))


def read_vessel(vessel_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_pressure_vessel(vessel_id, ADMIN))


def read_lot(lot_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_production_lot(lot_id, ADMIN))


def read_delivery(delivery_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_delivery(delivery_id, ADMIN))


def read_session(session_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_dispense_session(session_id, ADMIN))


def read_safety_event(event_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_safety_event(event_id, ADMIN))


def read_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_incentive_claim(claim_id, ADMIN))


def read_report(report_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_uptime_report(report_id, ADMIN))


def read_ledger(station_id: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    response = api_client.list_station_inventory_ledger(
        station_id, ADMIN, params=params or {"limit": 100}
    )
    get_success_data(response)
    return response.json()["data"]


def read_ledger_meta(station_id: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    response = api_client.list_station_inventory_ledger(
        station_id, ADMIN, params=params or {"limit": 100}
    )
    get_success_data(response)
    return response.json()["meta"]


# ─── Tier 2: station scaffolding ──────────────────────────────────────────


def setup_station(
    clock: str = DEFAULT_CLOCK_UTC,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    station_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Logical clock, one funding agreement and one station under it.

    Returns ``{"agreement": ..., "station": ..., "operator": headers}``.
    """
    set_clock(clock)
    agreement = create_funding_agreement(**(agreement_overrides or {}))
    station = create_station(agreement["id"], **(station_overrides or {}))
    return {
        "agreement": agreement,
        "station": station,
        "operator": make_station_operator_headers(station["id"]),
    }


def commission_bank(
    station_id: str,
    bank: Sequence[Dict[str, Any]] = STANDARD_BANK,
    next_inspection_due_date: str = "2027-01-01",
) -> Dict[str, Dict[str, Any]]:
    """Commission the listed vessels in order and return them keyed by tier."""
    vessels: Dict[str, Dict[str, Any]] = {}
    for spec in bank:
        payload = dict(spec)
        payload.setdefault("next_inspection_due_date", next_inspection_due_date)
        vessel = commission_vessel(station_id, **payload)
        vessels[spec["bank_tier"]] = vessel
    return vessels


def add_emergency_responders(
    station_id: str,
    count: int = 2,
    valid_from: str = "2026-01-01",
    expires_on: str = "2027-01-01",
) -> List[Dict[str, Any]]:
    """Record `count` current EMERGENCY_RESPONSE certifications on the station."""
    return [
        record_responder_certification(
            station_id,
            responder_ref=f"RESP-{index}",
            cert_type="EMERGENCY_RESPONSE",
            valid_from=valid_from,
            expires_on=expires_on,
        )
        for index in range(1, count + 1)
    ]


def setup_operational_station(
    clock: str = DEFAULT_CLOCK_UTC,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    station_overrides: Optional[Dict[str, Any]] = None,
    bank: Sequence[Dict[str, Any]] = STANDARD_BANK,
    responders: int = 2,
    vessel_due_date: str = "2027-01-01",
) -> Dict[str, Any]:
    """A station able to dispense and to receive hydrogen.

    Clock, funding agreement, station, the cascade bank and the emergency
    responder certifications the readiness floor requires.
    """
    scenario = setup_station(clock, agreement_overrides, station_overrides)
    scenario["vessels"] = commission_bank(
        scenario["station"]["id"], bank, next_inspection_due_date=vessel_due_date
    )
    scenario["responders"] = add_emergency_responders(
        scenario["station"]["id"], count=responders
    )
    scenario["station"] = read_station(scenario["station"]["id"])
    return scenario


# ─── Tier 3: production lot lifecycle ─────────────────────────────────────


def setup_produced_lot(
    asset_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
    lot_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Production asset, one governing power contract and one PRODUCED lot."""
    asset = create_production_asset(**(asset_overrides or {}))
    contract = create_power_supply_contract(asset["id"], **(contract_overrides or {}))
    lot = create_production_lot(asset["id"], **(lot_overrides or {}))
    return {"asset": asset, "contract": contract, "lot": lot}


def setup_released_lot(
    asset_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
    lot_overrides: Optional[Dict[str, Any]] = None,
    purity_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A lot walked all the way to RELEASED: purity PASS, CI certified, released.

    The purity test is performed by one analyst and the release is taken by a
    ComplianceAdmin, so the segregation rule is satisfied.
    """
    scenario = setup_produced_lot(asset_overrides, contract_overrides, lot_overrides)
    lot_id = scenario["lot"]["id"]
    scenario["purity_test"] = record_purity_test(lot_id, **(purity_overrides or {}))
    scenario["lot"] = certify_lot_ci(lot_id)
    scenario["lot"] = release_lot(lot_id)
    return scenario


def _merged(base: Dict[str, Any], overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(base)
    merged.update(overrides or {})
    return merged


def setup_canonical_produced_lot(
    asset_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
    lot_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The recurring 1000.000 kg electrolysis lot, left in PRODUCED."""
    return setup_produced_lot(
        asset_overrides=_merged(CANONICAL_ASSET, asset_overrides),
        contract_overrides=_merged(CANONICAL_CONTRACT, contract_overrides),
        lot_overrides=_merged(CANONICAL_LOT, lot_overrides),
    )


def setup_canonical_released_lot(
    asset_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
    lot_overrides: Optional[Dict[str, Any]] = None,
    purity_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The recurring 1000.000 kg electrolysis lot walked to RELEASED."""
    return setup_released_lot(
        asset_overrides=_merged(CANONICAL_ASSET, asset_overrides),
        contract_overrides=_merged(CANONICAL_CONTRACT, contract_overrides),
        lot_overrides=_merged(CANONICAL_LOT, lot_overrides),
        purity_overrides=_merged(CANONICAL_PURITY, purity_overrides),
    )


def setup_small_produced_lot(
    asset_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
    lot_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A 300.000 kg lot under a 50.000 % renewable grid, left in PRODUCED."""
    return setup_produced_lot(
        asset_overrides=_merged(CANONICAL_ASSET, asset_overrides),
        contract_overrides=_merged(SMALL_CONTRACT, contract_overrides),
        lot_overrides=_merged(SMALL_LOT, lot_overrides),
    )


def setup_small_released_lot(
    asset_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
    lot_overrides: Optional[Dict[str, Any]] = None,
    purity_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A 300.000 kg lot walked to RELEASED on a half-limit purity sample."""
    return setup_released_lot(
        asset_overrides=_merged(CANONICAL_ASSET, asset_overrides),
        contract_overrides=_merged(SMALL_CONTRACT, contract_overrides),
        lot_overrides=_merged(SMALL_LOT, lot_overrides),
        purity_overrides=_merged(HALF_LIMIT_PURITY, purity_overrides),
    )


# ─── Tier 4: deliveries ───────────────────────────────────────────────────


def book_tube_trailer_delivery(
    station_id: str, production_lot_id: str, receiving_vessel_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_delivery(
            tube_trailer_delivery_payload(
                station_id, production_lot_id, receiving_vessel_id, **overrides
            ),
            DISPATCHER,
        )
    )


def book_liquid_tanker_delivery(
    station_id: str, production_lot_id: str, receiving_vessel_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_delivery(
            liquid_tanker_delivery_payload(
                station_id, production_lot_id, receiving_vessel_id, **overrides
            ),
            DISPATCHER,
        )
    )


def arrive_delivery(delivery_id: str, at_clock: Optional[str] = None) -> Dict[str, Any]:
    """Move the clock inside the booked window if asked, then record arrival."""
    if at_clock is not None:
        set_clock(at_clock)
    return get_success_data(api_client.arrive_delivery(delivery_id, DISPATCHER))


def offload_delivery(delivery_id: str, station_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.offload_delivery(delivery_id, make_station_operator_headers(station_id))
    )


def reject_delivery(delivery_id: str, station_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.reject_delivery(
            delivery_id,
            delivery_reject_payload(**overrides),
            make_station_operator_headers(station_id),
        )
    )


def setup_arrived_tube_trailer(
    station_overrides: Optional[Dict[str, Any]] = None,
    bank: Sequence[Dict[str, Any]] = STANDARD_BANK,
    receiving_tier: str = "HIGH",
    delivery_overrides: Optional[Dict[str, Any]] = None,
    arrive_at: str = "2026-08-02T02:00:00Z",
    release_lot_first: bool = True,
    clock: str = DEFAULT_CLOCK_UTC,
) -> Dict[str, Any]:
    """Operational station plus a lot plus a tube-trailer delivery in ARRIVED."""
    scenario = setup_operational_station(
        clock=clock, station_overrides=station_overrides, bank=bank
    )
    lot_scenario = (
        setup_released_lot() if release_lot_first else setup_produced_lot()
    )
    scenario.update(lot_scenario)
    scenario["delivery"] = book_tube_trailer_delivery(
        scenario["station"]["id"],
        scenario["lot"]["id"],
        scenario["vessels"][receiving_tier]["id"],
        **(delivery_overrides or {}),
    )
    scenario["delivery"] = arrive_delivery(scenario["delivery"]["id"], at_clock=arrive_at)
    scenario["station"] = read_station(scenario["station"]["id"])
    return scenario


# ─── Tier 5: dispensing sessions ──────────────────────────────────────────


def open_session(station_id: str, **overrides: Any):
    """Open a session, reading the station's live version first.

    Returns the raw response so callers can assert on refusals as well as on
    successes.
    """
    version = read_station_version(station_id)
    payload = dispense_session_payload(station_id, version, **overrides)
    return api_client.create_dispense_session(
        payload, make_station_operator_headers(station_id)
    )


def create_session(station_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(open_session(station_id, **overrides))


def fuel_session(
    session_id: str, station_id: str, precool_temp_achieved_c: float
) -> Dict[str, Any]:
    return get_success_data(
        api_client.fuel_dispense_session(
            session_id,
            fuel_payload(precool_temp_achieved_c),
            make_station_operator_headers(station_id),
        )
    )


def complete_session(
    session_id: str,
    station_id: str,
    metered_kg: float,
    avg_dispense_pressure_bar: float = 700.00,
    final_pressure_bar: float = 700.00,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_dispense_session(
            session_id,
            complete_fill_payload(metered_kg, avg_dispense_pressure_bar, final_pressure_bar),
            make_station_operator_headers(station_id),
        )
    )


def settle_session(session_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.settle_dispense_session(session_id, COMPLIANCE))


def void_session_meter(session_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.void_dispense_session_meter(
            session_id, void_meter_payload(**overrides), COMPLIANCE
        )
    )


def run_completed_fill(
    station_id: str,
    planned_kg: float,
    metered_kg: float,
    precool_temp_achieved_c: float,
    avg_dispense_pressure_bar: float = 700.00,
    final_pressure_bar: float = 700.00,
    **session_overrides: Any,
) -> Dict[str, Any]:
    """Create a session, start fuelling and close the fill.  Returns the session."""
    session = create_session(station_id, planned_kg=planned_kg, **session_overrides)
    fuel_session(session["id"], station_id, precool_temp_achieved_c)
    return complete_session(
        session["id"],
        station_id,
        metered_kg,
        avg_dispense_pressure_bar,
        final_pressure_bar,
    )


def run_settled_fill(
    station_id: str,
    planned_kg: float,
    metered_kg: float,
    precool_temp_achieved_c: float,
    avg_dispense_pressure_bar: float = 700.00,
    final_pressure_bar: float = 700.00,
    **session_overrides: Any,
) -> Dict[str, Any]:
    """A fill taken all the way to billing_status METERED."""
    session = run_completed_fill(
        station_id,
        planned_kg,
        metered_kg,
        precool_temp_achieved_c,
        avg_dispense_pressure_bar,
        final_pressure_bar,
        **session_overrides,
    )
    return settle_session(session["id"])


# ─── Tier 6: safety events ────────────────────────────────────────────────


def open_safety_event(station_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open an event as the SafetyOfficer identified by SO-1."""
    return get_success_data(
        api_client.create_safety_event(safety_event_payload(station_id, **overrides), OFFICER)
    )


def acknowledge_safety_event(event_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.acknowledge_safety_event(event_id, headers or OFFICER_2)
    )


def clear_safety_event(
    event_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Clear an event as a different officer than the one who opened it."""
    return get_success_data(
        api_client.clear_safety_event(
            event_id, clear_safety_event_payload(**overrides), headers or OFFICER_2
        )
    )


def open_acknowledge_and_clear_event(
    station_id: str,
    opened_at: str,
    cleared_at: str,
    **event_overrides: Any,
) -> Dict[str, Any]:
    """Accrue one closed outage interval: open at `opened_at`, clear at `cleared_at`.

    ``opened_at`` is the inclusive start of the outage interval and
    ``cleared_at`` its exclusive end, so the accrued length is the span
    between them.
    """
    set_clock(opened_at)
    event = open_safety_event(station_id, **event_overrides)
    acknowledge_safety_event(event["id"])
    set_clock(cleared_at)
    return clear_safety_event(event["id"])


def freeze_station_with_critical_leak(station_id: str, nozzles: int = 4) -> Dict[str, Any]:
    """Open a CRITICAL LEAK_DETECTED event, which drives the station to FROZEN."""
    return open_safety_event(
        station_id,
        kind="LEAK_DETECTED",
        severity="CRITICAL",
        affected_nozzle_count=nozzles,
        detected_by="SENSOR",
    )


def restrict_station_with_compressor_fault(
    station_id: str, nozzles: int = 2
) -> Dict[str, Any]:
    """Open a MAJOR COMPRESSOR_FAULT event, which drives the station to RESTRICTED."""
    return open_safety_event(
        station_id,
        kind="COMPRESSOR_FAULT",
        severity="MAJOR",
        affected_nozzle_count=nozzles,
        detected_by="OPERATOR_ROUND",
    )


# ─── Tier 7: pressure-vessel inspections ──────────────────────────────────


def pass_inspection(vessel_id: str, next_due_date: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_vessel_inspection(
            vessel_id, pass_inspection_payload(next_due_date), OFFICER
        )
    )


def condemn_vessel(vessel_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_vessel_inspection(vessel_id, condemn_inspection_payload(), OFFICER)
    )


# ─── Tier 8: incentive claims ─────────────────────────────────────────────


def submit_claim(station_id: str, production_lot_ids: Sequence[str], **overrides: Any):
    """Submit a claim.  Returns the raw response so refusals can be asserted."""
    return api_client.create_incentive_claim(
        incentive_claim_payload(station_id, production_lot_ids, **overrides), COMPLIANCE
    )


def create_claim(station_id: str, production_lot_ids: Sequence[str], **overrides: Any):
    return get_success_data(submit_claim(station_id, production_lot_ids, **overrides))


def setup_delivered_certified_lot(
    station_id: str,
    receiving_vessel_id: str,
    accepted_at: str = "2026-08-02T02:00:00Z",
    window_start: str = "2026-08-02T00:00:00Z",
    window_end: str = "2026-08-02T06:00:00Z",
    departed_at: str = "2026-08-01T12:00:00Z",
    planned_kg: float = 300.000,
    lot_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A certified lot accepted into the station, so a claim can weight it.

    Books a tube-trailer delivery of the released lot, records arrival inside
    the window and offloads it, which stamps ``accepted_at`` inside the claim
    period a caller will use.
    """
    lot_scenario = setup_released_lot(
        contract_overrides=contract_overrides, lot_overrides=lot_overrides
    )
    delivery = book_tube_trailer_delivery(
        station_id,
        lot_scenario["lot"]["id"],
        receiving_vessel_id,
        planned_kg=planned_kg,
        window_start=window_start,
        window_end=window_end,
        departed_at=departed_at,
    )
    arrive_delivery(delivery["id"], at_clock=accepted_at)
    delivery = offload_delivery(delivery["id"], station_id)
    lot_scenario["delivery"] = delivery
    lot_scenario["lot"] = read_lot(lot_scenario["lot"]["id"])
    return lot_scenario


# ─── Tier 9: uptime reports ───────────────────────────────────────────────


def draft_uptime_report(
    station_id: str, funding_agreement_id: str, **overrides: Any
):
    """Draft a report, reading the agreement's live version first.

    Returns the raw response so stale-token refusals can be asserted too.
    """
    version = read_agreement(funding_agreement_id)["version"]
    payload = uptime_report_payload(station_id, funding_agreement_id, version, **overrides)
    return api_client.create_uptime_report(payload, COMPLIANCE)


def create_uptime_report(station_id: str, funding_agreement_id: str, **overrides: Any):
    return get_success_data(draft_uptime_report(station_id, funding_agreement_id, **overrides))


def finalize_report(report_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.finalize_uptime_report(report_id, COMPLIANCE))


def amend_report(report_id: str, period_start: str, period_end: str, **overrides: Any):
    return get_success_data(
        api_client.amend_uptime_report(
            report_id, amend_report_payload(period_start, period_end, **overrides), COMPLIANCE
        )
    )


# ─── Listing helpers ──────────────────────────────────────────────────────


def list_rows(response) -> List[Dict[str, Any]]:
    get_success_data(response)
    return response.json()["data"]


def list_meta(response) -> Dict[str, Any]:
    get_success_data(response)
    return response.json()["meta"]
