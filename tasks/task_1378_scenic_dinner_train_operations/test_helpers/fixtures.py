"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims need the railroad in a specific operating state that
takes 10-20 API calls to reach (agreement -> activate -> slot -> roster stock ->
excursion -> consist -> roster crew -> assign crew -> publish -> bookings).
These helpers encapsulate those chains so tests focus on assertions.

All helpers use get_success_data() so a setup failure surfaces as a clear
"Setup step failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_agreement_payload,
    create_booking_payload,
    create_car_assignment_payload,
    create_crew_assignment_payload,
    create_crew_member_payload,
    create_excursion_payload,
    create_rolling_stock_payload,
    create_slot_payload,
    create_work_order_payload,
)
from .test_users import TEST_USERS

SCHED = TEST_USERS["scheduler_headers"]
MECH = TEST_USERS["mechanic_headers"]
AGENT = TEST_USERS["station_agent_headers"]
CREW = TEST_USERS["crew_manager_headers"]
CATER = TEST_USERS["catering_manager_headers"]
OPS = TEST_USERS["operations_manager_headers"]

# Canonical consists: (unit_code, stock_type, seat_capacity, table_count, class_code)
LOCO_SPEC = ("LOC-1", "LOCOMOTIVE", 0, 0, "LOCO")
COACH_SPEC = ("COACH-1", "COACH_CAR", 40, 0, "COACH")
DINING_SPEC = ("DIN-1", "DINING_CAR", 16, 4, "DINING")
FIRST_CLASS_SPEC = ("FC-1", "FIRST_CLASS_CAR", 20, 0, "FIRST_CLASS")

BASE_CAR_SPECS = [LOCO_SPEC, COACH_SPEC]
DINING_CAR_SPECS = [LOCO_SPEC, DINING_SPEC]

# Canonical rosters: (name, role, is_volunteer, cert_expires_on)
BASE_CREW_SPECS = [
    ("Ed Eng", "ENGINEER", False, TEST_DEFAULTS["CERT_EXPIRES_ON"]),
    ("Con Ida", "CONDUCTOR", False, TEST_DEFAULTS["CERT_EXPIRES_ON"]),
    ("Hal Host", "CAR_HOST", True, None),
]
DINING_CREW_SPECS = [
    ("Chef Ana", "CHEF", False, None),
    ("Svr One", "SERVER", False, None),
    ("Svr Two", "SERVER", False, None),
]


# ─── Tier 1: single-resource state progression ──────────────────────────────

def create_active_agreement(**overrides) -> dict:
    """Create a track rights agreement (DRAFT) and ACTIVATE it. Returns ACTIVE agreement."""
    agr = get_success_data(api_client.create_agreement(create_agreement_payload(**overrides), SCHED))
    return get_success_data(api_client.agreement_event(agr["id"], {"event_type": "ACTIVATE"}, SCHED))


def create_open_slot(agreement_id: str, **overrides) -> dict:
    """Create an operating slot (OPEN) under an ACTIVE agreement."""
    return get_success_data(api_client.create_slot(create_slot_payload(agreement_id, **overrides), SCHED))


def roster_stock(unit_code: str, stock_type: str, seat_capacity: int, table_count: int) -> dict:
    """Roster one unit of rolling stock (AVAILABLE)."""
    return get_success_data(api_client.create_rolling_stock(
        create_rolling_stock_payload(
            unit_code=unit_code, stock_type=stock_type,
            seat_capacity=seat_capacity, table_count=table_count),
        MECH))


def create_draft_excursion(slot_id: str, **overrides) -> dict:
    """Create an excursion (DRAFT) on an OPEN slot; reserves the slot and auto-creates the manifest."""
    return get_success_data(api_client.create_excursion(create_excursion_payload(slot_id, **overrides), SCHED))


def roster_crew_member(name: str, role: str, is_volunteer: bool = False, cert_expires_on=None) -> dict:
    """Roster one crew member or volunteer (ACTIVE)."""
    return get_success_data(api_client.create_crew_member(
        create_crew_member_payload(name, role, is_volunteer, cert_expires_on), CREW))


def publish_excursion(excursion_id: str) -> dict:
    """Publish an excursion, carrying the current version under the OCC rule (PRD §2.8)."""
    current = get_success_data(api_client.get_excursion(excursion_id, SCHED))
    return get_success_data(api_client.excursion_event(
        excursion_id,
        {"event_type": "PUBLISH", "expected_excursion_version": current["version"]},
        SCHED))


def get_manifest(excursion_id: str) -> dict:
    """Fetch the excursion's single provisioning manifest (array of 0-1, PRD §3.7)."""
    data = get_success_data(api_client.get_excursion_manifests(excursion_id, CATER))
    assert isinstance(data, list) and len(data) == 1, "exactly one manifest per excursion"
    return data[0]


def lock_manifest(manifest_id: str) -> dict:
    """Lock a manifest, carrying the current version under the OCC rule (PRD §2.8)."""
    current = get_success_data(api_client.get_manifest(manifest_id, CATER))
    return get_success_data(api_client.manifest_event(
        manifest_id,
        {"event_type": "LOCK", "expected_manifest_version": current["version"]},
        CATER))


def set_clock(to_iso8601: str) -> dict:
    """Advance the test-driving logical clock (OperationsManager only, PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


# ─── Tier 2: consist / crew assembly ────────────────────────────────────────

def assign_car(excursion_id: str, stock_id: str, class_code: str, position: int) -> dict:
    """Add one car or locomotive to a DRAFT excursion's consist."""
    return get_success_data(api_client.create_car_assignment(
        create_car_assignment_payload(excursion_id, stock_id, class_code, position), SCHED))


def assign_crew(excursion_id: str, crew_member_id: str, position: str) -> dict:
    """Assign an ACTIVE crew member to an excursion."""
    return get_success_data(api_client.create_crew_assignment(
        create_crew_assignment_payload(excursion_id, crew_member_id, position), CREW))


def _roster_and_assign_crew(excursion_id: str, crew_specs) -> list:
    members = []
    for name, role, is_volunteer, cert in crew_specs:
        member = roster_crew_member(name, role, is_volunteer, cert)
        members.append(member)
        assign_crew(excursion_id, member["id"], role)
    return members


def setup_draft_excursion(*, service_date=TEST_DEFAULTS["SERVICE_DATE"],
                          start_minute=TEST_DEFAULTS["SLOT_START_MINUTE"],
                          end_minute=TEST_DEFAULTS["SLOT_END_MINUTE"],
                          event_type="REGULAR", surge_multiplier_bp=None,
                          title="Test Run", car_specs=None, crew_specs=None,
                          with_crew=True) -> dict:
    """ACTIVE agreement + OPEN slot + rostered stock + DRAFT excursion + consist + crew.

    car_specs entries: (unit_code, stock_type, seat_capacity, table_count, class_code).
    When any car is a DINING car and with_crew is true, the galley crew
    (CHEF + two SERVERs) is rostered and assigned too (PRD §3.4 coverage rule).
    """
    if car_specs is None:
        car_specs = BASE_CAR_SPECS
    if surge_multiplier_bp is None:
        surge_multiplier_bp = 10000 if event_type == "REGULAR" else 12000

    agreement = create_active_agreement()
    slot = create_open_slot(agreement["id"], service_date=service_date,
                            start_minute=start_minute, end_minute=end_minute)
    excursion = create_draft_excursion(slot["id"], title=title, event_type=event_type,
                                       surge_multiplier_bp=surge_multiplier_bp)

    cars = {}
    for position, (unit_code, stock_type, seat_capacity, table_count, class_code) in enumerate(car_specs, start=1):
        stock = roster_stock(unit_code, stock_type, seat_capacity, table_count)
        assignment = assign_car(excursion["id"], stock["id"], class_code, position)
        cars[unit_code] = {"stock": stock, "assignment": assignment}

    crew = []
    if with_crew:
        specs = list(crew_specs) if crew_specs is not None else list(BASE_CREW_SPECS)
        if any(spec[4] == "DINING" for spec in car_specs):
            specs = specs + [s for s in DINING_CREW_SPECS if s[0] not in {c[0] for c in specs}]
        crew = _roster_and_assign_crew(excursion["id"], specs)

    return {
        "agreement": agreement,
        "slot": slot,
        "excursion": excursion,
        "cars": cars,
        "crew": crew,
        "manifest": get_manifest(excursion["id"]),
    }


def setup_published_excursion(**kwargs) -> dict:
    """Full planning pipeline through PUBLISHED. Returns the scenario dict."""
    scenario = setup_draft_excursion(**kwargs)
    ex_id = scenario["excursion"]["id"]
    scenario["excursion"] = publish_excursion(ex_id)
    scenario["manifest"] = get_manifest(ex_id)
    return scenario


# ─── Tier 3: booking lifecycle shortcuts ────────────────────────────────────

def create_held_booking(excursion_id: str, customer_email: str, class_code: str,
                        party_size: int, dining_service=None) -> dict:
    """Create a booking (HELD, expires_at = created_at + 45 minutes)."""
    return get_success_data(api_client.create_booking(
        create_booking_payload(excursion_id, customer_email, class_code, party_size, dining_service),
        AGENT))


def confirm_booking(booking_id: str, redeemed_rain_check_id=None) -> dict:
    """CONFIRM a HELD booking (fare quote, optional rain-check redemption, dining selector)."""
    payload = {"event_type": "CONFIRM"}
    if redeemed_rain_check_id is not None:
        payload["redeemed_rain_check_id"] = redeemed_rain_check_id
    return get_success_data(api_client.booking_event(booking_id, payload, AGENT))


def create_confirmed_booking(excursion_id: str, customer_email: str, class_code: str,
                             party_size: int, dining_service=None, redeemed_rain_check_id=None) -> dict:
    """Create + CONFIRM. Returns the CONFIRMED booking."""
    held = create_held_booking(excursion_id, customer_email, class_code, party_size, dining_service)
    return confirm_booking(held["id"], redeemed_rain_check_id)


def cancel_excursion(excursion_id: str, cancel_reason: str = "WEATHER") -> dict:
    """OperationsManager cancels an excursion with the given reason."""
    return get_success_data(api_client.excursion_event(
        excursion_id, {"event_type": "CANCEL", "cancel_reason": cancel_reason}, OPS))


def list_rain_checks_for_booking(booking_id: str) -> list:
    """List rain-checks whose source booking is the given booking."""
    data = get_success_data(api_client.list_rain_checks(AGENT, params={"booking_id": booking_id}))
    assert isinstance(data, list)
    return data


def get_booking(booking_id: str) -> dict:
    return get_success_data(api_client.get_booking(booking_id, AGENT))


def get_excursion(excursion_id: str) -> dict:
    return get_success_data(api_client.get_excursion(excursion_id, SCHED))


def get_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_slot(slot_id, SCHED))


# ─── Tier 4: two-excursion and rain-check scenarios ─────────────────────────

def setup_published_pair(*, date_a="2026-10-15", date_b="2026-10-16",
                         car_specs=None, event_types=("REGULAR", "REGULAR"),
                         surges=(10000, 10000), titles=("Run A", "Run B")) -> dict:
    """Two published excursions on different service dates sharing one agreement,
    one set of stock, and one crew roster (different dates, so no same-date
    crew/stock conflicts arise). Returns {"agreement", "stocks", "crew", "a", "b"}.
    """
    if car_specs is None:
        car_specs = BASE_CAR_SPECS
    agreement = create_active_agreement()
    slot_a = create_open_slot(agreement["id"], service_date=date_a)
    slot_b = create_open_slot(agreement["id"], service_date=date_b)

    stocks = {}
    for unit_code, stock_type, seat_capacity, table_count, _ in car_specs:
        stocks[unit_code] = roster_stock(unit_code, stock_type, seat_capacity, table_count)

    crew_specs = list(BASE_CREW_SPECS)
    if any(spec[4] == "DINING" for spec in car_specs):
        crew_specs += DINING_CREW_SPECS
    crew = [roster_crew_member(name, role, vol, cert) for name, role, vol, cert in crew_specs]

    legs = {}
    for key, slot, event_type, surge, title in (
            ("a", slot_a, event_types[0], surges[0], titles[0]),
            ("b", slot_b, event_types[1], surges[1], titles[1])):
        excursion = create_draft_excursion(slot["id"], title=title, event_type=event_type,
                                           surge_multiplier_bp=surge)
        assignments = {}
        for position, (unit_code, _, _, _, class_code) in enumerate(car_specs, start=1):
            assignments[unit_code] = assign_car(excursion["id"], stocks[unit_code]["id"],
                                                class_code, position)
        for member in crew:
            assign_crew(excursion["id"], member["id"], member["role"])
        excursion = publish_excursion(excursion["id"])
        legs[key] = {"slot": slot, "excursion": excursion, "assignments": assignments,
                     "manifest": get_manifest(excursion["id"])}

    return {"agreement": agreement, "stocks": stocks, "crew": crew,
            "a": legs["a"], "b": legs["b"]}


def setup_issued_rain_check_and_second_excursion(*, source_party_size: int = 1,
                                                 customer_email: str = "sam@x.com") -> dict:
    """Excursion A published; one COACH booking confirmed; excursion A weather-cancelled
    so a rain-check (ISSUED) is minted for the source booking; excursion B (next day)
    published and bookable. Returns {"pair", "source_booking", "rain_check"}.
    """
    pair = setup_published_pair()
    source = create_confirmed_booking(pair["a"]["excursion"]["id"], customer_email,
                                      "COACH", source_party_size)
    cancel_excursion(pair["a"]["excursion"]["id"], "WEATHER")
    rain_checks = list_rain_checks_for_booking(source["id"])
    assert len(rain_checks) == 1, "one rain-check per rain-checked booking"
    return {"pair": pair, "source_booking": source, "rain_check": rain_checks[0]}


# ─── Tier 5: maintenance / retirement scenarios ──────────────────────────────

def create_scheduled_work_order(stock_id: str, **overrides) -> dict:
    """Schedule a maintenance window (SCHEDULED)."""
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(stock_id, **overrides), MECH))


def start_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.work_order_event(work_order_id, {"event_type": "START"}, MECH))


def complete_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.work_order_event(work_order_id, {"event_type": "COMPLETE"}, MECH))


def retire_stock(stock_id: str) -> dict:
    return get_success_data(api_client.rolling_stock_event(stock_id, {"event_type": "RETIRE"}, MECH))
