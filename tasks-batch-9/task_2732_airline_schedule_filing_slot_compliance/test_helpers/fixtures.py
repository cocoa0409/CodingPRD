"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: the harness empties the database before each test, so nothing
here may assume pre-existing rows. Setup calls use the lenient
`get_success_data` so that a broken precondition surfaces as a setup failure
rather than as a confusing assertion.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SEASON_MONDAYS
from .factories import (
    booking_snapshot_payload,
    create_aircraft_payload,
    create_carrier_payload,
    create_filing_submission_payload,
    create_flight_leg_payload,
    create_notification_obligation_payload,
    create_partner_carrier_payload,
    create_route_authority_payload,
    create_schedule_version_payload,
    create_season_payload,
    create_slot_holding_payload,
    create_slot_transaction_payload,
    create_slot_utilization_record_payload,
    create_station_payload,
)
from .test_users import (
    TEST_USERS,
    make_network_planner_headers,
    make_partner_carrier_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
COORDINATOR = TEST_USERS["slot_coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
AGENT = TEST_USERS["filing_agent_headers"]


# ─── Station catalogue ────────────────────────────────────────────────────
# Five airports are enough to express every operational shape the contract
# describes: a fully coordinated hub, two facilitated German fields, a
# facilitated Portuguese field with a night curfew, and a second coordinated
# German field for station-mismatch probes.

STATION_PRESETS: Dict[str, dict] = {
    "FRA": {
        "iata_code": "FRA",
        "country_code": "DE",
        "coordination_level": "LEVEL_3_COORDINATED",
        "utc_offset_minutes": 120,
        "gate_count": 2,
        "maintenance_capable": True,
    },
    "MUC": {
        "iata_code": "MUC",
        "country_code": "DE",
        "coordination_level": "LEVEL_2_FACILITATED",
        "utc_offset_minutes": 120,
        "gate_count": 3,
        "maintenance_capable": True,
    },
    "TXL": {
        "iata_code": "TXL",
        "country_code": "DE",
        "coordination_level": "LEVEL_2_FACILITATED",
        "utc_offset_minutes": 120,
        "gate_count": 2,
        "curfew_start_local_minutes": 1380,
        "curfew_end_local_minutes": 330,
    },
    "LIS": {
        "iata_code": "LIS",
        "country_code": "PT",
        "coordination_level": "LEVEL_2_FACILITATED",
        "utc_offset_minutes": 0,
        "gate_count": 3,
        "curfew_start_local_minutes": 1380,
        "curfew_end_local_minutes": 330,
    },
    "DUS": {
        "iata_code": "DUS",
        "country_code": "DE",
        "coordination_level": "LEVEL_3_COORDINATED",
        "utc_offset_minutes": 120,
        "gate_count": 3,
    },
}


# ─── Single-entity builders ───────────────────────────────────────────────

def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock and return the reported `{current_utc}`."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or ADMIN))


def create_carrier(**overrides) -> dict:
    return get_success_data(
        api_client.create_carrier(create_carrier_payload(**overrides), ADMIN)
    )


def create_partner_carrier(**overrides) -> dict:
    return get_success_data(
        api_client.create_carrier(create_partner_carrier_payload(**overrides), ADMIN)
    )


def create_station(code: str, **overrides) -> dict:
    """Register one of the catalogue airports, with any field overridden."""
    payload = create_station_payload(**STATION_PRESETS[code])
    payload.update(overrides)
    return get_success_data(api_client.create_station(payload, ADMIN))


def create_draft_season(**overrides) -> dict:
    return get_success_data(
        api_client.create_season(create_season_payload(**overrides), ADMIN)
    )


def create_open_season(**overrides) -> dict:
    """Create the season and advance it one step to `OPEN`, the working
    state."""
    season = create_draft_season(**overrides)
    return get_success_data(
        api_client.transition_season(season["id"], {"to_status": "OPEN"}, ADMIN)
    )


def create_aircraft(carrier_id: str, base_station_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_aircraft(
            create_aircraft_payload(carrier_id, base_station_id, **overrides),
            make_network_planner_headers(carrier_id),
        )
    )


def create_schedule_version(carrier_id: str, season_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_schedule_version(
            create_schedule_version_payload(carrier_id, season_id, **overrides),
            make_network_planner_headers(carrier_id),
        )
    )


def create_slot_holding(
    station_id: str, season_id: str, carrier_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_slot_holding(
            create_slot_holding_payload(station_id, season_id, carrier_id, **overrides),
            COORDINATOR,
        )
    )


def create_route_authority(
    carrier_id: str, origin_country_code: str, dest_country_code: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_route_authority(
            create_route_authority_payload(
                carrier_id, origin_country_code, dest_country_code, **overrides
            ),
            ADMIN,
        )
    )


def create_flight_leg(
    carrier_id: str,
    schedule_version_id: str,
    origin_station_id: str,
    dest_station_id: str,
    dep_utc: str,
    arr_utc: str,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_flight_leg(
            create_flight_leg_payload(
                schedule_version_id,
                origin_station_id,
                dest_station_id,
                dep_utc,
                arr_utc,
                **overrides,
            ),
            make_network_planner_headers(carrier_id),
        )
    )


def assign_aircraft(carrier_id: str, flight_leg_id: str, aircraft_id: str) -> dict:
    return get_success_data(
        api_client.assign_aircraft(
            flight_leg_id,
            {"aircraft_id": aircraft_id},
            make_network_planner_headers(carrier_id),
        )
    )


def attach_slot(
    carrier_id: str,
    flight_leg_id: str,
    slot_holding_id: str,
    movement_type: str = "DEPARTURE",
) -> dict:
    return get_success_data(
        api_client.attach_slot(
            flight_leg_id,
            {"slot_holding_id": slot_holding_id, "movement_type": movement_type},
            make_network_planner_headers(carrier_id),
        )
    )


def snapshot_bookings(
    carrier_id: str,
    flight_leg_id: str,
    booked_first: int = 0,
    booked_business: int = 0,
    booked_economy: int = 0,
) -> dict:
    return get_success_data(
        api_client.booking_snapshot(
            flight_leg_id,
            booking_snapshot_payload(booked_first, booked_business, booked_economy),
            make_network_planner_headers(carrier_id),
        )
    )


def validate_version(schedule_version_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.validate_schedule_version(schedule_version_id, headers or OFFICER)
    )


def queue_submission(
    schedule_version_id: str,
    change_window: str = "STANDARD",
    distribution_system: str = "IATA_SSIM",
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api_client.create_filing_submission(
            create_filing_submission_payload(
                schedule_version_id,
                change_window=change_window,
                distribution_system=distribution_system,
            ),
            headers or AGENT,
        )
    )


def transmit_submission(filing_submission_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.transmit_filing_submission(filing_submission_id, headers or AGENT)
    )


def acknowledge_submission(
    filing_submission_id: str,
    outcome: str = "ACCEPT",
    rejection_reason: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    payload: dict = {"outcome": outcome}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(
        api_client.acknowledge_filing_submission(
            filing_submission_id, payload, headers or AGENT
        )
    )


def file_utilization_record(
    slot_holding_id: str, operation_date: str, outcome: str, headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.create_slot_utilization_record(
            create_slot_utilization_record_payload(
                slot_holding_id, operation_date, outcome
            ),
            headers or COORDINATOR,
        )
    )


def raise_obligation(
    flight_leg_id: str,
    trigger_kind: str = "RETIME",
    change_magnitude_minutes: int = 45,
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api_client.create_notification_obligation(
            create_notification_obligation_payload(
                flight_leg_id, trigger_kind, change_magnitude_minutes
            ),
            headers or OFFICER,
        )
    )


# ─── Read-back helpers ────────────────────────────────────────────────────

def read_carrier(carrier_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_carrier(carrier_id, headers or ADMIN))


def read_station(station_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_station(station_id, headers or ADMIN))


def read_season(season_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_season(season_id, headers or ADMIN))


def read_aircraft(aircraft_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_aircraft(aircraft_id, headers or ADMIN))


def read_rotation(aircraft_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_rotation_feasibility(aircraft_id, headers or ADMIN)
    )


def read_version(schedule_version_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_schedule_version(schedule_version_id, headers or ADMIN)
    )


def read_leg(flight_leg_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_flight_leg(flight_leg_id, headers or ADMIN))


def read_holding(slot_holding_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_slot_holding(slot_holding_id, headers or ADMIN)
    )


def read_transaction(slot_transaction_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_slot_transaction(slot_transaction_id, headers or ADMIN)
    )


def read_submission(filing_submission_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_filing_submission(filing_submission_id, headers or ADMIN)
    )


def read_route_authority(route_authority_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_route_authority(route_authority_id, headers or ADMIN)
    )


def read_obligation(
    notification_obligation_id: str, headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.get_notification_obligation(
            notification_obligation_id, headers or ADMIN
        )
    )


# ─── Tier 1: the reference layer ──────────────────────────────────────────

def setup_reference_data(
    station_codes: tuple = ("FRA", "MUC"),
    with_partner: bool = False,
    season_overrides: Optional[dict] = None,
    open_season: bool = True,
) -> dict:
    """Home carrier, the named airports and the season, ready for planning.

    Returns {"carrier", "partner", "stations": {code: station}, "season",
             "planner"} where `planner` is the home carrier's own headers.
    """
    carrier = create_carrier()
    partner = create_partner_carrier() if with_partner else None
    stations = {code: create_station(code) for code in station_codes}
    season = (
        create_open_season(**(season_overrides or {}))
        if open_season
        else create_draft_season(**(season_overrides or {}))
    )
    return {
        "carrier": carrier,
        "partner": partner,
        "stations": stations,
        "season": season,
        "planner": make_network_planner_headers(carrier["id"]),
    }


# ─── Tier 2/3: the Monday slot series schedule ────────────────────────────

def setup_monday_series_schedule(
    *,
    leg_count: int = 4,
    series_weeks: int = 5,
    attach_count: Optional[int] = None,
    assign: bool = True,
    version_label: str = "W26-R1",
    flight_number: str = "HX101",
    dep_time: str = "08:00",
    arr_time: str = "09:00",
    budget_cents: Optional[int] = None,
    with_partner: bool = False,
    marketing_carrier_ids: Optional[List[str]] = None,
    validate: bool = False,
    submission: Optional[dict] = None,
    transmit: bool = False,
    acknowledge: Optional[str] = None,
    aircraft_overrides: Optional[dict] = None,
    ref: Optional[dict] = None,
) -> dict:
    """A schedule version whose legs are the successive Mondays of one slot
    series at the coordinated hub.

    The hub (`FRA`) is `LEVEL_3_COORDINATED` so every leg needs a departure
    slot; the destination (`MUC`) is facilitated so no arrival slot is
    required. Each leg therefore reaches `SLOT_BACKED` on one attach once it
    has a tail. Every leg sits on its own UTC date, so the rotation walk sees
    one leg per date group.

    Returns {"carrier", "partner", "stations", "season", "planner",
             "aircraft", "version", "holding", "legs", "submission"}.
    """
    ref = ref or setup_reference_data(("FRA", "MUC"), with_partner=with_partner)
    carrier, stations, season = ref["carrier"], ref["stations"], ref["season"]
    planner = ref["planner"]

    aircraft = create_aircraft(
        carrier["id"], stations["FRA"]["id"], **(aircraft_overrides or {})
    )

    version_kwargs = {"version_label": version_label}
    if budget_cents is not None:
        version_kwargs["filing_charge_budget_cents"] = budget_cents
    version = create_schedule_version(carrier["id"], season["id"], **version_kwargs)

    holding = create_slot_holding(
        stations["FRA"]["id"],
        season["id"],
        carrier["id"],
        movement_type="DEPARTURE",
        slot_time_utc=f"{SEASON_MONDAYS[0]}T{dep_time}:00.000Z",
        days_of_week="1",
        series_weeks=series_weeks,
    )

    if attach_count is None:
        attach_count = leg_count

    legs: List[dict] = []
    for index in range(leg_count):
        leg_overrides = {"flight_number": flight_number}
        if marketing_carrier_ids is not None:
            leg_overrides["marketing_carrier_ids"] = marketing_carrier_ids
        leg = create_flight_leg(
            carrier["id"],
            version["id"],
            stations["FRA"]["id"],
            stations["MUC"]["id"],
            f"{SEASON_MONDAYS[index]}T{dep_time}:00.000Z",
            f"{SEASON_MONDAYS[index]}T{arr_time}:00.000Z",
            **leg_overrides,
        )
        if assign:
            leg = assign_aircraft(carrier["id"], leg["id"], aircraft["id"])
        if index < attach_count:
            attach_slot(carrier["id"], leg["id"], holding["id"], "DEPARTURE")
            leg = read_leg(leg["id"], planner)
        legs.append(leg)

    if validate:
        validate_version(version["id"])

    filing = None
    if submission is not None:
        filing = queue_submission(
            version["id"],
            change_window=submission.get("change_window", "STANDARD"),
            distribution_system=submission.get("distribution_system", "IATA_SSIM"),
        )
        if transmit:
            filing = transmit_submission(filing["id"])
            if acknowledge is not None:
                filing = acknowledge_submission(filing["id"], acknowledge)

    return {
        "carrier": carrier,
        "partner": ref["partner"],
        "stations": stations,
        "season": season,
        "planner": planner,
        "aircraft": aircraft,
        "version": read_version(version["id"], planner),
        "holding": read_holding(holding["id"], planner),
        "legs": [read_leg(leg["id"], planner) for leg in legs],
        "submission": read_submission(filing["id"], planner) if filing else None,
    }


# ─── Tier 2: a booked leg, ready for the passenger side ───────────────────

def setup_booked_leg(
    *,
    booked_first: int = 3,
    booked_business: int = 7,
    booked_economy: int = 41,
    version_label: str = "W26-N9",
    dep_utc: str = "2026-11-02T08:00:00.000Z",
    arr_utc: str = "2026-11-02T09:00:00.000Z",
    ref: Optional[dict] = None,
) -> dict:
    """One leg of a draft version carrying a booked-load snapshot.

    The passenger-impact rules read only the three cabin counters, so the leg
    needs neither a tail nor a slot.
    """
    ref = ref or setup_reference_data(("FRA", "MUC"))
    carrier, stations, season = ref["carrier"], ref["stations"], ref["season"]
    version = create_schedule_version(
        carrier["id"], season["id"], version_label=version_label
    )
    leg = create_flight_leg(
        carrier["id"],
        version["id"],
        stations["FRA"]["id"],
        stations["MUC"]["id"],
        dep_utc,
        arr_utc,
    )
    leg = snapshot_bookings(
        carrier["id"], leg["id"], booked_first, booked_business, booked_economy
    )
    return {
        "carrier": carrier,
        "stations": stations,
        "season": season,
        "planner": ref["planner"],
        "version": read_version(version["id"], ref["planner"]),
        "leg": leg,
    }


# ─── Tier 2: rotation bases ───────────────────────────────────────────────

def setup_domestic_rotation_base(
    *,
    station_codes: tuple = ("MUC", "TXL"),
    version_label: str = "W26-T6",
    station_overrides: Optional[Dict[str, dict]] = None,
    aircraft_overrides: Optional[dict] = None,
) -> dict:
    """Two facilitated German airports, one tail and one draft version.

    Neither airport is fully coordinated, so a leg between them needs no slot
    at all and auto-advances to `SLOT_BACKED` the moment it is assigned a tail.
    """
    station_overrides = station_overrides or {}
    carrier = create_carrier()
    stations = {
        code: create_station(code, **station_overrides.get(code, {}))
        for code in station_codes
    }
    season = create_open_season()
    aircraft = create_aircraft(
        carrier["id"], stations[station_codes[0]]["id"], **(aircraft_overrides or {})
    )
    version = create_schedule_version(
        carrier["id"], season["id"], version_label=version_label
    )
    return {
        "carrier": carrier,
        "stations": stations,
        "season": season,
        "planner": make_network_planner_headers(carrier["id"]),
        "aircraft": aircraft,
        "version": version,
    }


def setup_international_rotation_base(
    *,
    version_label: str = "W26-R8",
    weekly_frequency_cap: int = 14,
    aircraft_overrides: Optional[dict] = None,
    station_overrides: Optional[Dict[str, dict]] = None,
) -> dict:
    """`MUC` and `LIS` plus the traffic rights that make the pair flyable.

    The country pair is matched as an unordered pair, and both directions are
    granted so either heading is authorised.
    """
    station_overrides = station_overrides or {}
    carrier = create_carrier()
    stations = {
        code: create_station(code, **station_overrides.get(code, {}))
        for code in ("MUC", "LIS")
    }
    season = create_open_season()
    outbound_authority = create_route_authority(
        carrier["id"], "DE", "PT", weekly_frequency_cap=weekly_frequency_cap
    )
    inbound_authority = create_route_authority(
        carrier["id"], "PT", "DE", weekly_frequency_cap=weekly_frequency_cap
    )
    tail_kwargs = {"registration": "D-AHXI", "fleet_type_code": "A320"}
    tail_kwargs.update(aircraft_overrides or {})
    aircraft = create_aircraft(carrier["id"], stations["MUC"]["id"], **tail_kwargs)
    version = create_schedule_version(
        carrier["id"], season["id"], version_label=version_label
    )
    return {
        "carrier": carrier,
        "stations": stations,
        "season": season,
        "planner": make_network_planner_headers(carrier["id"]),
        "aircraft": aircraft,
        "version": version,
        "outbound_authority": outbound_authority,
        "inbound_authority": inbound_authority,
    }


# ─── Tier 2: gate occupancy base ──────────────────────────────────────────

def setup_gate_occupancy_base(*, version_label: str = "W26-G8") -> dict:
    """The coordinated hub with two gates and a facilitated destination with
    three, plus one draft version and no tails or slots at all.

    Gate concurrency is computed per station per UTC date across every carrier
    and version, so nothing else may exist for the arithmetic to be readable.
    """
    ref = setup_reference_data(("FRA", "MUC"))
    version = create_schedule_version(
        ref["carrier"]["id"], ref["season"]["id"], version_label=version_label
    )
    ref["version"] = version
    return ref


# ─── Tier 4: utilization accumulation, ready for the audit ────────────────

def setup_series_with_utilization(
    *,
    outcomes_by_holding: Optional[List[List[str]]] = None,
    series_weeks: int = 5,
    slot_times: tuple = ("08:00", "09:00"),
    historic_precedence: bool = True,
    ref: Optional[dict] = None,
) -> dict:
    """One or more slot series at the coordinated hub with dated utilization
    records already filed against them.

    `outcomes_by_holding[i]` is the ordered list of outcomes filed against the
    i-th series, one per successive Monday. The as-operated percentage that the
    audit rules on therefore follows directly from the crediting outcomes in
    that list.
    """
    outcomes_by_holding = outcomes_by_holding or [["OPERATED"]]
    ref = ref or setup_reference_data(("FRA", "MUC"))
    carrier, stations, season = ref["carrier"], ref["stations"], ref["season"]

    holdings: List[dict] = []
    for index, outcomes in enumerate(outcomes_by_holding):
        holding = create_slot_holding(
            stations["FRA"]["id"],
            season["id"],
            carrier["id"],
            movement_type="DEPARTURE",
            slot_time_utc=f"{SEASON_MONDAYS[0]}T{slot_times[index]}:00.000Z",
            days_of_week="1",
            series_weeks=series_weeks,
            historic_precedence=historic_precedence,
        )
        for day_index, outcome in enumerate(outcomes):
            file_utilization_record(
                holding["id"], f"{SEASON_MONDAYS[day_index]}T00:00:00.000Z", outcome
            )
        holdings.append(read_holding(holding["id"]))

    return {
        "carrier": carrier,
        "stations": stations,
        "season": season,
        "planner": ref["planner"],
        "holdings": holdings,
    }


def close_season(season_id: str) -> dict:
    """Advance an `OPEN` season one step to `CLOSED`, the audit state."""
    return get_success_data(
        api_client.transition_season(season_id, {"to_status": "CLOSED"}, ADMIN)
    )


def run_slot_audit(season_id: str, audit_reference: str = "AUD-W26-01") -> dict:
    return get_success_data(
        api_client.run_slot_audit(
            season_id, {"audit_reference": audit_reference}, COORDINATOR
        )
    )


# ─── Tier 3: slot transaction negotiations ────────────────────────────────

def setup_transaction_precondition(
    *,
    kind: str = "TRANSFER",
    offered_historic: bool = False,
    with_counter_holding: bool = False,
    series_weeks: int = 2,
    ref: Optional[dict] = None,
) -> dict:
    """Home carrier and counterparty each holding a series at the coordinated
    hub.

    The offered series belongs to the home carrier at 08:00Z; the counter
    series, when asked for, belongs to the counterparty at 10:00Z so the two
    never collide on time-of-day.
    """
    ref = ref or setup_reference_data(("FRA", "MUC"), with_partner=True)
    carrier, partner = ref["carrier"], ref["partner"]
    stations, season = ref["stations"], ref["season"]

    offered = create_slot_holding(
        stations["FRA"]["id"],
        season["id"],
        carrier["id"],
        movement_type="DEPARTURE",
        slot_time_utc=f"{SEASON_MONDAYS[0]}T08:00:00.000Z",
        days_of_week="1",
        series_weeks=series_weeks,
        historic_precedence=offered_historic,
    )
    counter = None
    if with_counter_holding or kind == "EXCHANGE":
        counter = create_slot_holding(
            stations["FRA"]["id"],
            season["id"],
            partner["id"],
            movement_type="DEPARTURE",
            slot_time_utc=f"{SEASON_MONDAYS[0]}T10:00:00.000Z",
            days_of_week="1",
            series_weeks=series_weeks,
        )

    return {
        "carrier": carrier,
        "partner": partner,
        "stations": stations,
        "season": season,
        "planner": ref["planner"],
        "counterparty": make_partner_carrier_headers(partner["id"]),
        "offered": offered,
        "counter": counter,
        "kind": kind,
    }


def propose_transaction(
    *,
    carrier_id: str,
    counterparty_carrier_id: str,
    offered_slot_holding_id: str,
    expected_slot_holding_version: int,
    kind: str = "TRANSFER",
    counter_slot_holding_id: Optional[str] = None,
    response_deadline_utc: str = "2026-09-01T00:00:00.000Z",
) -> dict:
    payload = create_slot_transaction_payload(
        counterparty_carrier_id,
        offered_slot_holding_id,
        expected_slot_holding_version,
        kind=kind,
        response_deadline_utc=response_deadline_utc,
    )
    if counter_slot_holding_id is not None:
        payload["counter_slot_holding_id"] = counter_slot_holding_id
    return get_success_data(
        api_client.create_slot_transaction(
            payload, make_network_planner_headers(carrier_id)
        )
    )


def setup_accepted_transaction(*, kind: str = "TRANSFER", **kwargs) -> dict:
    """Walk the negotiation as far as the first gate's acceptance, which is the
    only status the coordinator may rule on.
    """
    setup = setup_transaction_precondition(kind=kind, **kwargs)
    offered = read_holding(setup["offered"]["id"], setup["planner"])
    transaction = propose_transaction(
        carrier_id=setup["carrier"]["id"],
        counterparty_carrier_id=setup["partner"]["id"],
        offered_slot_holding_id=offered["id"],
        expected_slot_holding_version=offered["version"],
        kind=kind,
        counter_slot_holding_id=(
            setup["counter"]["id"] if setup["counter"] is not None else None
        ),
    )
    transaction = get_success_data(
        api_client.respond_slot_transaction(
            transaction["id"], {"decision": "ACCEPT"}, setup["counterparty"]
        )
    )
    setup["transaction"] = transaction
    return setup


# ─── Version succession ───────────────────────────────────────────────────

def supersede_version(
    carrier_id: str,
    schedule_version_id: str,
    expected_schedule_version_version: int,
    version_label: str = "W26-R2",
) -> dict:
    """Mint a successor from a fresh read of the predecessor's version."""
    return get_success_data(
        api_client.supersede_schedule_version(
            schedule_version_id,
            {
                "version_label": version_label,
                "expected_schedule_version_version": expected_schedule_version_version,
            },
            make_network_planner_headers(carrier_id),
        )
    )


def withdraw_version(
    carrier_id: str, schedule_version_id: str, reason: str = "COMMERCIAL_WITHDRAWAL"
) -> dict:
    return get_success_data(
        api_client.withdraw_schedule_version(
            schedule_version_id,
            {"reason": reason},
            make_network_planner_headers(carrier_id),
        )
    )


def cancel_leg(
    carrier_id: str, flight_leg_id: str, reason: str = "DEMAND_SHORTFALL"
) -> dict:
    return get_success_data(
        api_client.cancel_flight_leg(
            flight_leg_id,
            {"reason": reason},
            make_network_planner_headers(carrier_id),
        )
    )


def retime_leg(carrier_id: str, flight_leg_id: str, dep_utc: str, arr_utc: str) -> dict:
    return get_success_data(
        api_client.patch_flight_leg(
            flight_leg_id,
            {"dep_utc": dep_utc, "arr_utc": arr_utc},
            make_network_planner_headers(carrier_id),
        )
    )


def return_holding(
    slot_holding_id: str,
    reason: str = "SEASONAL_RIGHTSIZING",
    headers=None,
    carrier_id: Optional[str] = None,
) -> dict:
    """Hand a series back. The endpoint belongs to the holder's
    `NetworkPlanner`, so pass the holding carrier's id or explicit headers."""
    if headers is None:
        headers = (
            make_network_planner_headers(carrier_id)
            if carrier_id is not None
            else TEST_USERS["network_planner_headers"]
        )
    return get_success_data(
        api_client.return_slot_holding(slot_holding_id, {"reason": reason}, headers)
    )


def dispatch_obligation(
    notification_obligation_id: str,
    channel: str = "EMAIL",
    regulator_reference: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    payload: dict = {"channel": channel}
    if regulator_reference is not None:
        payload["regulator_reference"] = regulator_reference
    return get_success_data(
        api_client.dispatch_notification_obligation(
            notification_obligation_id, payload, headers or OFFICER
        )
    )
