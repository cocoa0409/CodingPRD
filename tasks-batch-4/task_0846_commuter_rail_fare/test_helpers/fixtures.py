"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is reset before every individual test. Setup calls use the
lenient get_success_data() so setup failures surface as clear "Setup failed" errors.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_passenger_headers
from .factories import (
    create_fare_product_payload, create_agency_payload, create_passenger_payload,
    create_application_payload, create_ticket_payload, create_inspection_payload,
    create_citation_payload, create_refund_request_payload, create_disruption_payload,
    create_service_credit_payload,
)
from .constants import DEFAULT_CLOCK

ADMIN = TEST_USERS["fareadmin_headers"]
CONDUCTOR = TEST_USERS["conductor_headers"]

_email_seq = itertools.count(1)


def _fresh_email(prefix="rider"):
    return f"{prefix}{next(_email_seq)}@example.com"


# --------------------------------------------------------------------------
# Atomic builders
# --------------------------------------------------------------------------

def set_clock(api, iso=DEFAULT_CLOCK):
    return get_success_data(api.set_clock(iso, ADMIN))


def create_fare_product(api, **overrides):
    return get_success_data(api.create_fare_product(create_fare_product_payload(**overrides), ADMIN))


def create_agency(api, code, zones_served):
    return get_success_data(api.create_agency(create_agency_payload(code, zones_served), ADMIN))


def create_agencies_abc(api):
    """Agencies A[1], B[2], C[3] created in that order (creation order is the tie-break)."""
    a = create_agency(api, "A", [1])
    b = create_agency(api, "B", [2])
    c = create_agency(api, "C", [3])
    return a, b, c


def create_passenger(api, dob="1990-01-01", email=None, full_name="Test Rider"):
    payload = create_passenger_payload(
        email=email or _fresh_email(), full_name=full_name, date_of_birth=dob
    )
    return get_success_data(api.create_passenger(payload, ADMIN))


def purchase_ticket(api, passenger_id, fare_product_id, travel_period="PEAK",
                    use_reduced_fare=None, wallet_apply_cents=None):
    payload = create_ticket_payload(
        passenger_id, fare_product_id, travel_period,
        use_reduced_fare=use_reduced_fare, wallet_apply_cents=wallet_apply_cents,
    )
    return get_success_data(api.create_ticket(payload, make_passenger_headers(passenger_id)))


def activate_ticket(api, ticket_id, passenger_id):
    return get_success_data(api.activate_ticket(ticket_id, make_passenger_headers(passenger_id)))


def create_inspection(api, passenger_id, observed_destination_zone, ticket_id=None):
    payload = create_inspection_payload(passenger_id, observed_destination_zone, ticket_id=ticket_id)
    return get_success_data(api.create_inspection(payload, CONDUCTOR))


def issue_citation(api, inspection_id, passenger_id):
    payload = create_citation_payload(inspection_id, passenger_id)
    return get_success_data(api.create_citation(payload, CONDUCTOR))


def submit_application(api, passenger_id, category, expected_passenger_version,
                       proof_expires_at="2027-01-01T00:00:00Z"):
    payload = create_application_payload(
        passenger_id, category, expected_passenger_version, proof_expires_at=proof_expires_at
    )
    return get_success_data(api.create_application(payload, make_passenger_headers(passenger_id)))


def approve_application(api, application_id):
    return get_success_data(api.approve_application(application_id, ADMIN))


def request_refund(api, ticket_id, passenger_id, refund_destination="WALLET", reason="changed plans"):
    payload = create_refund_request_payload(ticket_id, refund_destination=refund_destination, reason=reason)
    return get_success_data(api.create_refund_request(payload, make_passenger_headers(passenger_id)))


def approve_refund(api, refund_id):
    return get_success_data(api.approve_refund(refund_id, ADMIN))


def create_disruption(api, line_code, scheduled_departure, actual_departure, window_start, window_end):
    payload = create_disruption_payload(
        line_code, scheduled_departure, actual_departure, window_start, window_end
    )
    return get_success_data(api.create_disruption(payload, ADMIN))


def issue_service_credit(api, disruption_id, ticket_id):
    payload = create_service_credit_payload(disruption_id, ticket_id)
    return get_success_data(api.create_service_credit(payload, ADMIN))


def get_passenger(api, passenger_id):
    return get_success_data(api.get_passenger(passenger_id, ADMIN))


def get_ticket(api, ticket_id):
    return get_success_data(api.get_ticket(ticket_id, ADMIN))


def get_application(api, application_id):
    return get_success_data(api.get_application(application_id, ADMIN))


def get_citation(api, citation_id):
    return get_success_data(api.get_citation(citation_id, ADMIN))


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------

def setup_reduced_fare_passenger(api, category="STUDENT", dob="2005-01-01"):
    """Register a passenger and drive an approved reduced-fare eligibility.

    Returns (passenger_after_approval, application). Passenger.version has been
    advanced twice (application create + approval).
    """
    set_clock(api)
    pax = create_passenger(api, dob=dob)
    app = submit_application(api, pax["id"], category, pax["version"])
    approve_application(api, app["id"])
    return get_passenger(api, pax["id"]), app


def setup_evasion_citation(api, dob="1990-01-01"):
    """Passenger with one EVASION inspection escalated to one ISSUED citation
    (evasion_count == 1). Returns (passenger_id, inspection, citation)."""
    set_clock(api)
    pax = create_passenger(api, dob=dob)
    insp = create_inspection(api, pax["id"], observed_destination_zone=3)
    cit = issue_citation(api, insp["id"], pax["id"])
    return pax["id"], insp, cit


def setup_purchased_single_ticket(api, base=1000, peak=300, travel_period="PEAK"):
    """Clock + SINGLE (1->3) product + passenger + one PURCHASED ticket.

    Returns (fare_product, passenger, ticket)."""
    set_clock(api)
    fp = create_fare_product(api, base_fare_cents=base, peak_surcharge_cents=peak)
    pax = create_passenger(api)
    tkt = purchase_ticket(api, pax["id"], fp["id"], travel_period)
    return fp, pax, tkt


def setup_service_credit_scenario(api, delay_actual, base=1000, peak=300, line_code="L1"):
    """SINGLE ticket (PEAK, price 1300) + a disruption with the given actual_departure.

    Returns (passenger, ticket, disruption)."""
    set_clock(api)
    fp = create_fare_product(api, base_fare_cents=base, peak_surcharge_cents=peak)
    pax = create_passenger(api)
    tkt = purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    dis = create_disruption(
        api, line_code,
        scheduled_departure="2026-03-01T08:00:00Z",
        actual_departure=delay_actual,
        window_start="2026-03-01T08:00:00Z",
        window_end="2026-03-01T09:00:00Z",
    )
    return pax, tkt, dis
