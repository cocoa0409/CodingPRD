"""Role-based access control: role denial, ownership denial, self-service grants."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS, ANONYMOUS_HEADERS, make_passenger_headers, NON_EXISTENT_UUID,
    add_passenger, add_flight, add_event, add_booking,
    event_to_assessing, event_to_recovery,
    cancel_flight_under_event, get_case_for_booking,
    offer_case, commit_option, get_booking,
    create_flight_payload, cancel_flight_payload, generate_options_payload,
    commit_payload,
)

AGENT = TEST_USERS["agent_headers"]
OPS = TEST_USERS["ops_controller_headers"]
DUTY = TEST_USERS["duty_manager_headers"]
FIN = TEST_USERS["finance_headers"]


def test_finance_processor_cannot_cancel_flight(api):
    """PRD §2.1: "Each endpoint admits a fixed set of roles (enumerated in §4);
    a caller whose role is not admitted is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: "Cancel a flight under a disruption event; OCC-guarded; depth-4
    cascade" — authorized role(s): OpsController. FinanceProcessor is not
    admitted.

    Design: Corner/rbac/finance_cannot_cancel_flight
    """
    flight = add_flight(flight_number="OC70",
                        sched_dep_utc="2026-08-10T09:00:00Z",
                        sched_arr_utc="2026-08-10T10:00:00Z",
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    event = add_event(event_code="MECH-C18", cost_cap_cents=100000)
    event_to_assessing(event["id"])
    res = api_client.cancel_flight(
        flight["id"], cancel_flight_payload(event["id"], flight["version"]), FIN)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
    after = validate_success(api_client.get_flight(flight["id"], OPS))
    assert after["flight_status"] == "SCHEDULED", "rejected cancel must not mutate the flight"


def test_passenger_cannot_read_another_travelers_booking(api):
    """PRD §2.1: "When `X-User-Role` is `Passenger`, `X-User-ID` is the `id` of
    the acting `Passenger` entity, and ownership checks apply: a passenger may
    only read or act on resources whose booking chain's `passenger_id` equals
    their `X-User-ID`. A passenger touching another traveler's booking, case,
    option, voucher, or election is rejected with `ERR_FORBIDDEN_OWNERSHIP`
    (HTTP 403)."

    Design: Corner/rbac/passenger_cannot_read_others_booking
    """
    pa = add_passenger(full_name="Ann Own", contact_email="a@x.com")
    pb = add_passenger(full_name="Bob Own", contact_email="b@x.com")
    flight = add_flight(flight_number="OC71",
                        sched_dep_utc="2026-08-10T09:00:00Z",
                        sched_arr_utc="2026-08-10T10:00:00Z",
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    booking = add_booking(pb["id"], flight["id"])

    res = api_client.get_booking(booking["id"], make_passenger_headers(pa["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    own = validate_success(api_client.get_booking(
        booking["id"], make_passenger_headers(pb["id"])))
    assert own["id"] == booking["id"]


def test_passenger_self_service_option_generation_and_commit(api):
    """PRD §3.5: "Committing is the act of accepting one proposed option, by an
    agent or by the passenger whose booking it is, and it is the most heavily
    guarded write in the system."
    PRD §4: "Run the recovery-option selector; materializes up to 3 ranked
    options" and "Accept a proposed option; OCC-guarded on
    `expected_case_version`; moves seats and rebooks segments" — both admit the
    Passenger role.

    Design: Corner/rbac/passenger_self_service_commit
    """
    from test_helpers import set_clock
    set_clock("2026-08-10T06:00:00Z")
    pax = add_passenger(full_name="Self S", contact_email="self@x.com")
    pax_headers = make_passenger_headers(pax["id"])
    flight = add_flight(flight_number="OC72",
                        sched_dep_utc="2026-08-10T09:00:00Z",
                        sched_arr_utc="2026-08-10T10:00:00Z")
    add_flight(flight_number="OC73",
               sched_dep_utc="2026-08-10T14:00:00Z",
               sched_arr_utc="2026-08-10T15:00:00Z")
    event = add_event(event_code="MECH-C19", cost_cap_cents=1_000_000)
    event_to_assessing(event["id"])
    booking = add_booking(pax["id"], flight["id"], headers=pax_headers)
    cancel_flight_under_event(flight["id"], event["id"],
                              expected_version=flight["version"])
    event_to_recovery(event["id"])

    cases = validate_success(api_client.list_reaccommodation_cases(
        pax_headers, params={"booking_id": booking["id"]}))
    case = cases[0]

    offered = validate_success(api_client.generate_options(
        case["id"], generate_options_payload(False), pax_headers))
    options = validate_success(api_client.list_case_options(case["id"], pax_headers))
    assert len(options) >= 1

    committed = validate_success(api_client.commit_case(
        case["id"], commit_payload(options[0]["id"], offered["version"]), pax_headers))
    assert committed["case_status"] == "COMMITTED"
    booking_after = get_booking(booking["id"], headers=pax_headers)
    assert booking_after["booking_status"] == "REBOOKED"


def test_missing_auth_headers_rejected_401(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the operational
    capacity in which they act. A request with either header missing or
    malformed is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    res = api_client.get_booking(NON_EXISTENT_UUID, ANONYMOUS_HEADERS)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_agent_cannot_run_process_due_batch(api):
    """PRD §2.1: "Each endpoint admits a fixed set of roles (enumerated in §4);
    a caller whose role is not admitted is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: "Run the due-work batch: expire options and vouchers, default
    elections, send due notifications, emit reminders" — authorized role(s):
    OpsAdmin. ReaccommodationAgent is not admitted.

    Design: Corner/rbac/agent_cannot_run_comms_batch
    """
    res = api_client.process_due(AGENT)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
