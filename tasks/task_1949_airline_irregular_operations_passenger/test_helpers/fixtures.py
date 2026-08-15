"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against a fresh server
(the harness restarts the API before each test) using only PRD-declared
endpoints. Setup calls use the lenient get_success_data() validator so
failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_passenger_payload, create_flight_payload,
    create_disruption_event_payload, create_booking_payload,
    delay_flight_payload, cancel_flight_payload, depart_payload,
    record_actuals_payload, generate_options_payload, commit_payload,
    create_interline_agreement_payload, issue_voucher_payload,
    redeem_payload, create_crew_assignment_payload,
    create_refund_election_payload, set_clock_payload,
)
from .test_users import TEST_USERS, make_passenger_headers

AGENT = TEST_USERS["agent_headers"]
OPS = TEST_USERS["ops_controller_headers"]
DUTY = TEST_USERS["duty_manager_headers"]
CREW = TEST_USERS["crew_scheduler_headers"]
FIN = TEST_USERS["finance_headers"]
ADMIN = TEST_USERS["ops_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: atomic resource helpers
# ---------------------------------------------------------------------------

def set_clock(iso="2026-08-10T06:00:00Z"):
    """Advance the logical clock (PRD §2.5). Returns {current_utc}."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso), ADMIN))


def add_passenger(headers=None, **overrides):
    res = api_client.create_passenger(create_passenger_payload(**overrides), headers or AGENT)
    return get_success_data(res, 201)


def add_flight(headers=None, **overrides):
    res = api_client.create_flight(create_flight_payload(**overrides), headers or OPS)
    return get_success_data(res, 201)


def add_event(headers=None, **overrides):
    res = api_client.create_disruption_event(
        create_disruption_event_payload(**overrides), headers or DUTY)
    return get_success_data(res, 201)


def add_booking(passenger_id, flight_id=None, headers=None, **overrides):
    payload = create_booking_payload(passenger_id, flight_id, **overrides)
    res = api_client.create_booking(payload, headers or AGENT)
    return get_success_data(res, 201)


def add_crew_assignment(flight_id, headers=None, **overrides):
    res = api_client.create_crew_assignment(
        flight_id, create_crew_assignment_payload(**overrides), headers or CREW)
    return get_success_data(res, 201)


def add_agreement(headers=None, **overrides):
    res = api_client.create_interline_agreement(
        create_interline_agreement_payload(**overrides), headers or ADMIN)
    return get_success_data(res, 201)


def get_booking(booking_id, headers=None):
    return get_success_data(api_client.get_booking(booking_id, headers or AGENT))


def get_case(case_id, headers=None):
    return get_success_data(api_client.get_reaccommodation_case(case_id, headers or AGENT))


def get_option(option_id, headers=None):
    return get_success_data(api_client.get_reaccommodation_option(option_id, headers or AGENT))


def get_event(event_id, headers=None):
    return get_success_data(api_client.get_disruption_event(event_id, headers or DUTY))


def get_flight(flight_id, headers=None):
    return get_success_data(api_client.get_flight(flight_id, headers or OPS))


def fresh_flight_version(flight_id):
    return get_flight(flight_id)["version"]


def cabin_inventory(flight_id, cabin="ECONOMY", headers=None):
    rows = get_success_data(api_client.list_cabin_inventories(flight_id, headers or OPS))
    for row in rows:
        if row["cabin"] == cabin:
            return row
    raise AssertionError(f"no {cabin} cabin inventory on flight {flight_id}")


def segments_for_booking(booking_id, headers=None):
    return get_success_data(api_client.list_booking_segments(
        headers or AGENT, params={"booking_id": booking_id}))


def segments_for_flight(flight_id, headers=None):
    return get_success_data(api_client.list_booking_segments(
        headers or AGENT, params={"flight_id": flight_id}))


def cost_summary(event_id, headers=None):
    return get_success_data(api_client.get_cost_summary(event_id, headers or FIN))


def cost_entries(event_id, headers=None):
    return get_success_data(api_client.list_cost_entries(event_id, headers or FIN))


def comm_logs(params, headers=None):
    return get_success_data(api_client.list_communication_logs(headers or DUTY, params=params))


# ---------------------------------------------------------------------------
# Tier 1: state progression (event staircase, flight ops, vouchers, elections)
# ---------------------------------------------------------------------------

def event_to_assessing(event_id, headers=None):
    return get_success_data(api_client.assess_event(event_id, headers or DUTY))


def event_to_recovery(event_id, headers=None):
    return get_success_data(api_client.declare_recovery(event_id, headers or DUTY))


def cancel_flight_under_event(flight_id, event_id, expected_version=None, headers=None):
    v = expected_version if expected_version is not None else fresh_flight_version(flight_id)
    res = api_client.cancel_flight(
        flight_id, cancel_flight_payload(event_id, v), headers or OPS)
    return get_success_data(res)


def delay_flight_to(flight_id, new_dep, new_arr, event_id=None,
                    expected_version=None, headers=None):
    v = expected_version if expected_version is not None else fresh_flight_version(flight_id)
    payload = delay_flight_payload(new_dep, new_arr, v)
    if event_id:
        payload["disruption_event_id"] = event_id
    return get_success_data(api_client.delay_flight(flight_id, payload, headers or OPS))


def fly_flight(flight_id, act_dep_utc, act_arr_utc, headers=None):
    """Depart then record actual arrival; returns the ARRIVED flight."""
    h = headers or OPS
    get_success_data(api_client.depart_flight(flight_id, depart_payload(act_dep_utc), h))
    return get_success_data(api_client.record_actuals(
        flight_id, record_actuals_payload(act_arr_utc), h))


def issue_voucher(booking_id, voucher_type, check_in_date=None, headers=None):
    res = api_client.issue_voucher(
        booking_id, issue_voucher_payload(voucher_type, check_in_date), headers or AGENT)
    return get_success_data(res, 201)


def elect(booking_id, election, headers=None):
    res = api_client.create_refund_election(
        booking_id, create_refund_election_payload(election), headers or AGENT)
    return get_success_data(res, 201)


def process_election(election_id, headers=None):
    return get_success_data(api_client.process_refund_election(election_id, headers or FIN))


# ---------------------------------------------------------------------------
# Tier 2: reaccommodation case helpers
# ---------------------------------------------------------------------------

def get_case_for_booking(booking_id, headers=None):
    data = get_success_data(api_client.list_reaccommodation_cases(
        headers or AGENT, params={"booking_id": booking_id}))
    assert isinstance(data, list) and len(data) >= 1, (
        f"expected at least one reaccommodation case for booking {booking_id}")
    return data[0]


def list_cases(params, headers=None):
    return get_success_data(api_client.list_reaccommodation_cases(headers or AGENT, params=params))


def offer_case(case_id, include_interline=False, headers=None):
    """Run the selector; returns (OFFERED case, ranked PROPOSED options)."""
    h = headers or AGENT
    case = get_success_data(api_client.generate_options(
        case_id, generate_options_payload(include_interline), h))
    options = get_success_data(api_client.list_case_options(case_id, h))
    return case, options


def commit_option(case_id, option_id, expected_case_version, headers=None):
    res = api_client.commit_case(
        case_id, commit_payload(option_id, expected_case_version), headers or AGENT)
    return get_success_data(res)


def offer_and_commit(case_id, option_index=0, include_interline=False, headers=None):
    """generate-options -> commit options[option_index]. Returns (case, option)."""
    case, options = offer_case(case_id, include_interline=include_interline, headers=headers)
    assert len(options) > option_index, (
        f"expected at least {option_index + 1} option(s), got {len(options)}")
    option = options[option_index]
    committed = commit_option(case_id, option["id"], case["version"], headers=headers)
    return committed, option


# ---------------------------------------------------------------------------
# Tier 3: full disruption scenarios (the shared preamble of most tests)
# ---------------------------------------------------------------------------

def setup_disrupted_booking(clock="2026-08-10T06:00:00Z",
                            classification="MECHANICAL",
                            cost_cap_cents=1_000_000,
                            event_code="MECH-FX",
                            event_state="ASSESSING",
                            flight_overrides=None,
                            booking_overrides=None,
                            passenger_overrides=None,
                            extra_flights=None):
    """Clock -> passenger -> flight (+ extra flights) -> event -> ASSESSING ->
    booking -> cancel the flight under the event. When event_state is
    "RECOVERY", recovery is declared after the cancellation cascade.

    Returns ctx: {passenger, flight, event, booking, case, extra_flights}.
    """
    set_clock(clock)
    pax = add_passenger(**(passenger_overrides or {}))
    flight = add_flight(**(flight_overrides or {}))
    extras = [add_flight(**f) for f in (extra_flights or [])]
    event = add_event(event_code=event_code, classification=classification,
                      cost_cap_cents=cost_cap_cents)
    event_to_assessing(event["id"])
    booking = add_booking(pax["id"], flight["id"], **(booking_overrides or {}))
    cancel_flight_under_event(flight["id"], event["id"],
                              expected_version=flight["version"])
    if event_state == "RECOVERY":
        event_to_recovery(event["id"])
    case = get_case_for_booking(booking["id"])
    return {
        "passenger": pax, "flight": flight, "event": event,
        "booking": booking, "case": case, "extra_flights": extras,
    }


def setup_offered_case(include_interline=False, **kwargs):
    """setup_disrupted_booking + generate-options. Adds case (OFFERED) and options."""
    ctx = setup_disrupted_booking(**kwargs)
    case, options = offer_case(ctx["case"]["id"], include_interline=include_interline)
    ctx["case"] = case
    ctx["options"] = options
    return ctx


def setup_committed_case(option_index=0, include_interline=False, **kwargs):
    """Full chain through commit: booking ends REBOOKED. Adds option + refreshed booking."""
    ctx = setup_offered_case(include_interline=include_interline, **kwargs)
    assert len(ctx["options"]) > option_index, (
        f"expected at least {option_index + 1} option(s), got {len(ctx['options'])}")
    option = ctx["options"][option_index]
    case = commit_option(ctx["case"]["id"], option["id"], ctx["case"]["version"])
    ctx["case"] = case
    ctx["option"] = option
    ctx["booking"] = get_booking(ctx["booking"]["id"])
    return ctx


def setup_multi_booking_disruption(booking_specs=None, booking_count=2,
                                   clock="2026-08-10T06:00:00Z",
                                   classification="MECHANICAL",
                                   cost_cap_cents=1_000_000,
                                   event_code="MECH-MB",
                                   event_state="ASSESSING",
                                   flight_overrides=None,
                                   extra_flights=None):
    """One flight carrying N bookings, cancelled under one event.

    Each spec in booking_specs may carry:
      passenger_id        — reuse an existing passenger (shared-passenger cases)
      passenger_overrides — kwargs for add_passenger when creating one
      booking_overrides   — kwargs for add_booking (fare_cents, party_size, cabin)

    Returns ctx: {flight, event, extra_flights, passengers, bookings, cases}.
    """
    set_clock(clock)
    flight = add_flight(**(flight_overrides or {}))
    extras = [add_flight(**f) for f in (extra_flights or [])]
    event = add_event(event_code=event_code, classification=classification,
                      cost_cap_cents=cost_cap_cents)
    event_to_assessing(event["id"])
    specs = booking_specs if booking_specs is not None else [{}] * booking_count
    passengers, bookings = [], []
    for spec in specs:
        pid = spec.get("passenger_id")
        pax = None
        if pid is None:
            pax = add_passenger(**spec.get("passenger_overrides", {}))
            pid = pax["id"]
        booking = add_booking(pid, flight["id"], **spec.get("booking_overrides", {}))
        passengers.append(pax)
        bookings.append(booking)
    cancel_flight_under_event(flight["id"], event["id"],
                              expected_version=flight["version"])
    if event_state == "RECOVERY":
        event_to_recovery(event["id"])
    cases = [get_case_for_booking(b["id"]) for b in bookings]
    return {
        "flight": flight, "event": event, "extra_flights": extras,
        "passengers": passengers, "bookings": bookings, "cases": cases,
    }


def commit_cases(ctx, option_indexes, include_interline=False):
    """Commit each case in ctx["cases"] to options[idx]; returns [(case, option)]."""
    results = []
    for case, idx in zip(ctx["cases"], option_indexes):
        results.append(offer_and_commit(case["id"], option_index=idx,
                                        include_interline=include_interline))
    return results
