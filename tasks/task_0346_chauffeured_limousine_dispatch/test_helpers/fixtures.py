"""Composite setup helpers for multi-step test prerequisites.

Each test runs against a freshly-restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) so setup failures surface as clear "Setup failed".

Identity threading: the entity-backed roles are CorporateBooker (CorporateAccount),
AffiliatePartner (Affiliate), and Chauffeur (Chauffeur). Whenever a fixture performs
an ownership-gated call as one of these roles, it threads the actual entity id
through make_<role>_headers(entity_id). Provisioning runs as DispatchAdmin; trip
operations run as Dispatcher unless the chauffeur is the actor.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_chauffeur_headers,
    make_corporate_booker_headers,
    make_affiliate_partner_headers,
)
from .factories import (
    create_corporate_account_payload,
    create_affiliate_payload,
    create_vehicle_class_payload,
    create_vehicle_payload,
    create_chauffeur_payload,
    create_reservation_payload,
    create_flight_tracking_payload,
    create_assignment_payload,
    create_farm_out_order_payload,
    wait_event_payload,
    trip_event_payload,
    billing_event_payload,
    decision_event_payload,
    duty_event_payload,
    flight_update_payload,
)

ADMIN = TEST_USERS["dispatch_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Tier 0: primitives
# ===========================================================================
def set_clock(to_iso8601: str):
    """Set the deterministic server clock. Returns the ClockState."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_account(**overrides):
    """Create a corporate account (DispatchAdmin). Returns the account dict."""
    return get_success_data(
        api_client.create_corporate_account(create_corporate_account_payload(**overrides), ADMIN)
    )


def create_affiliate(**overrides):
    """Create an affiliate operator (DispatchAdmin). Returns the affiliate dict."""
    return get_success_data(
        api_client.create_affiliate(create_affiliate_payload(**overrides), ADMIN)
    )


def create_vehicle_class(**overrides):
    """Create a vehicle class (DispatchAdmin). Returns the class dict."""
    return get_success_data(
        api_client.create_vehicle_class(create_vehicle_class_payload(**overrides), ADMIN)
    )


def create_vehicle(vehicle_class_id, **overrides):
    """Create a vehicle (DispatchAdmin). Returns the vehicle dict."""
    return get_success_data(
        api_client.create_vehicle(create_vehicle_payload(vehicle_class_id, **overrides), ADMIN)
    )


def create_chauffeur(**overrides):
    """Create a chauffeur (DispatchAdmin). Begins OFF_DUTY. Returns the chauffeur dict."""
    return get_success_data(
        api_client.create_chauffeur(create_chauffeur_payload(**overrides), ADMIN)
    )


def create_reservation(account_id, vehicle_class_id, **overrides):
    """Create a DRAFT reservation (Dispatcher). Returns the reservation dict."""
    return get_success_data(
        api_client.create_reservation(
            create_reservation_payload(account_id, vehicle_class_id, **overrides), DISPATCHER
        )
    )


def suspend_account(account_id):
    return get_success_data(api_client.suspend_corporate_account(account_id, ADMIN))


def suspend_affiliate(affiliate_id):
    return get_success_data(api_client.suspend_affiliate(affiliate_id, ADMIN))


def suspend_chauffeur(chauffeur_id):
    """Move an OFF_DUTY chauffeur to SUSPENDED via a duty-event (DispatchAdmin)."""
    return get_success_data(
        api_client.create_duty_event(chauffeur_id, duty_event_payload("SUSPEND"), ADMIN)
    )


# ===========================================================================
# Tier 1: provisioning bundles
# ===========================================================================
def provision_basic(account_overrides=None, class_overrides=None):
    """Provision an account + a SEDAN vehicle class. Returns (account, vclass)."""
    account = create_account(**(account_overrides or {}))
    vclass = create_vehicle_class(**(class_overrides or {}))
    return account, vclass


def provision_with_resources(account_overrides=None, class_overrides=None,
                             vehicle_overrides=None, chauffeur_overrides=None):
    """Provision account + class + one chauffeur + one vehicle.
    Returns (account, vclass, chauffeur, vehicle)."""
    account, vclass = provision_basic(account_overrides, class_overrides)
    chauffeur = create_chauffeur(**(chauffeur_overrides or {}))
    vehicle = create_vehicle(vclass["id"], **(vehicle_overrides or {}))
    return account, vclass, chauffeur, vehicle


# ===========================================================================
# Tier 2: reservation state progression
# ===========================================================================
def quote_reservation(reservation_id, headers=None):
    """DRAFT -> QUOTED. Returns the reservation dict (with quote_estimate_total_cents)."""
    return get_success_data(
        api_client.create_trip_event(reservation_id, trip_event_payload("QUOTE"), headers or DISPATCHER)
    )


def confirm_reservation(reservation_id, headers=None):
    """QUOTED -> CONFIRMED. Returns the reservation dict (capture its version for OCC)."""
    return get_success_data(
        api_client.create_trip_event(reservation_id, trip_event_payload("CONFIRM"), headers or DISPATCHER)
    )


def create_quoted_reservation(account_id, vehicle_class_id, **res_overrides):
    """Create + QUOTE. Returns the QUOTED reservation dict."""
    res = create_reservation(account_id, vehicle_class_id, **res_overrides)
    return quote_reservation(res["id"])


def create_confirmed_reservation(account_id, vehicle_class_id, **res_overrides):
    """Create + QUOTE + CONFIRM. Returns the CONFIRMED reservation dict
    (its version is the value to pass as expected_reservation_version)."""
    res = create_reservation(account_id, vehicle_class_id, **res_overrides)
    quote_reservation(res["id"])
    return confirm_reservation(res["id"])


def assign_in_house(reservation_id, chauffeur_id, vehicle_id, expected_version):
    """CONFIRMED -> ASSIGNED via POST /assignments (Dispatcher, OCC-guarded).
    Returns the Assignment dict."""
    return get_success_data(
        api_client.create_assignment(
            create_assignment_payload(reservation_id, chauffeur_id, vehicle_id, expected_version),
            DISPATCHER,
        )
    )


def dispatch_trip(reservation_id, chauffeur_id=None):
    """ASSIGNED -> EN_ROUTE. Runs as the assigned Chauffeur when chauffeur_id is
    given (ownership-gated), else as Dispatcher. Returns the reservation dict."""
    headers = make_chauffeur_headers(chauffeur_id) if chauffeur_id else DISPATCHER
    return get_success_data(
        api_client.create_trip_event(reservation_id, trip_event_payload("DISPATCH"), headers)
    )


def post_wait_event(reservation_id, kind, occurred_at, chauffeur_id):
    """Append a wait event as the assigned Chauffeur. Returns the WaitEvent dict."""
    return get_success_data(
        api_client.create_wait_event(
            reservation_id, wait_event_payload(kind, occurred_at),
            make_chauffeur_headers(chauffeur_id),
        )
    )


def complete_trip(reservation_id, chauffeur_id=None):
    """PASSENGER_ABOARD -> COMPLETED. Runs as the assigned Chauffeur when given,
    else Dispatcher. Returns the reservation dict (with final_total_cents)."""
    headers = make_chauffeur_headers(chauffeur_id) if chauffeur_id else DISPATCHER
    return get_success_data(
        api_client.create_trip_event(reservation_id, trip_event_payload("COMPLETE"), headers)
    )


# ===========================================================================
# Tier 3: full in-house lifecycle shortcuts
# ===========================================================================
def setup_assigned_reservation(account_overrides=None, class_overrides=None,
                               vehicle_overrides=None, chauffeur_overrides=None,
                               res_overrides=None):
    """Provision + create + quote + confirm + assign in-house.
    Returns dict: account, vclass, chauffeur, vehicle, reservation (CONFIRMED snapshot),
    assignment, reservation_id, chauffeur_id, vehicle_id."""
    account, vclass, chauffeur, vehicle = provision_with_resources(
        account_overrides, class_overrides, vehicle_overrides, chauffeur_overrides
    )
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], **(res_overrides or {}))
    assignment = assign_in_house(
        confirmed["id"], chauffeur["id"], vehicle["id"], confirmed["version"]
    )
    return {
        "account": account,
        "vclass": vclass,
        "chauffeur": chauffeur,
        "vehicle": vehicle,
        "reservation": confirmed,
        "assignment": assignment,
        "reservation_id": confirmed["id"],
        "chauffeur_id": chauffeur["id"],
        "vehicle_id": vehicle["id"],
        "account_id": account["id"],
    }


def setup_en_route_reservation(**overrides):
    """Assigned reservation then DISPATCH -> EN_ROUTE (by the assigned chauffeur).
    Returns the same dict as setup_assigned_reservation."""
    ctx = setup_assigned_reservation(**overrides)
    dispatch_trip(ctx["reservation_id"], ctx["chauffeur_id"])
    return ctx


def setup_on_location_reservation(arrived_at, **overrides):
    """EN_ROUTE then CHAUFFEUR_ARRIVED -> ON_LOCATION. Returns the context dict."""
    ctx = setup_en_route_reservation(**overrides)
    post_wait_event(ctx["reservation_id"], "CHAUFFEUR_ARRIVED", arrived_at, ctx["chauffeur_id"])
    return ctx


def setup_completed_reservation(arrived_at, boarded_at, **overrides):
    """Walk all the way to COMPLETED, posting both wait events. Returns the context
    dict with the post-completion reservation snapshot under key 'reservation_final'."""
    ctx = setup_on_location_reservation(arrived_at, **overrides)
    post_wait_event(ctx["reservation_id"], "PASSENGER_BOARDED", boarded_at, ctx["chauffeur_id"])
    ctx["reservation_final"] = complete_trip(ctx["reservation_id"], ctx["chauffeur_id"])
    return ctx


# ===========================================================================
# Tier 4: farm-out lifecycle
# ===========================================================================
def setup_offered_farmout(account_overrides=None, class_overrides=None,
                          affiliate_overrides=None, res_overrides=None):
    """Provision account + class + affiliate; create + quote + confirm a reservation;
    offer it to the affiliate. Returns dict: account, vclass, affiliate, reservation
    (CONFIRMED snapshot), farm_out_order, reservation_id, affiliate_id, account_id."""
    account, vclass = provision_basic(account_overrides, class_overrides)
    affiliate = create_affiliate(**(affiliate_overrides or {}))
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], **(res_overrides or {}))
    order = get_success_data(
        api_client.create_farm_out_order(
            create_farm_out_order_payload(confirmed["id"], affiliate["id"], confirmed["version"]),
            DISPATCHER,
        )
    )
    return {
        "account": account,
        "vclass": vclass,
        "affiliate": affiliate,
        "reservation": confirmed,
        "farm_out_order": order,
        "reservation_id": confirmed["id"],
        "affiliate_id": affiliate["id"],
        "account_id": account["id"],
    }


def accept_farmout(order_id, affiliate_id):
    """OFFERED -> ACCEPTED as the owning AffiliatePartner. Returns the order dict."""
    return get_success_data(
        api_client.create_decision_event(
            order_id, decision_event_payload("ACCEPT"),
            make_affiliate_partner_headers(affiliate_id),
        )
    )


def reject_farmout(order_id, affiliate_id, decline_reason=None):
    """OFFERED -> REJECTED as the owning AffiliatePartner. Returns the order dict."""
    payload = decision_event_payload("REJECT")
    if decline_reason is not None:
        payload["decline_reason"] = decline_reason
    return get_success_data(
        api_client.create_decision_event(
            order_id, payload, make_affiliate_partner_headers(affiliate_id)
        )
    )


# ===========================================================================
# Tier 5: airport / flight tracking
# ===========================================================================
def attach_flight_tracking(reservation_id, **overrides):
    """Attach a flight tracking record to an AIRPORT reservation (Dispatcher).
    Returns the FlightTracking dict (starts ON_TIME)."""
    return get_success_data(
        api_client.create_flight_tracking(
            create_flight_tracking_payload(reservation_id, **overrides), DISPATCHER
        )
    )


def push_flight_update(flight_tracking_id, **payload):
    """Push a flight update (DispatchAdmin). Returns the FlightTracking dict."""
    return get_success_data(
        api_client.create_flight_update(flight_tracking_id, flight_update_payload(**payload), ADMIN)
    )


def setup_assigned_airport_reservation(scheduled_arrival_at, pickup_at, planned_drop_at,
                                       meet_and_greet=True, class_overrides=None):
    """AIRPORT reservation with flight tracking attached, assigned in-house.
    Returns dict: account, vclass, chauffeur, vehicle, reservation, flight_tracking,
    assignment, reservation_id, flight_tracking_id, assignment_id, chauffeur_id."""
    account, vclass = provision_basic(None, class_overrides or {"code": "SUV", "base_fare_cents": 7000,
                                                                "per_mile_cents": 300, "hourly_rate_cents": 15000,
                                                                "wait_per_minute_cents": 250})
    chauffeur = create_chauffeur()
    vehicle = create_vehicle(vclass["id"], plate="BLK-AIR")
    res = create_reservation(
        account["id"], vclass["id"], trip_type="AIRPORT",
        pickup_at=pickup_at, planned_drop_at=planned_drop_at, estimated_miles=18,
    )
    flight = attach_flight_tracking(
        res["id"], flight_number="UA1234",
        scheduled_arrival_at=scheduled_arrival_at, meet_and_greet=meet_and_greet,
    )
    quote_reservation(res["id"])
    confirmed = confirm_reservation(res["id"])
    assignment = assign_in_house(res["id"], chauffeur["id"], vehicle["id"], confirmed["version"])
    return {
        "account": account,
        "vclass": vclass,
        "chauffeur": chauffeur,
        "vehicle": vehicle,
        "reservation": confirmed,
        "flight_tracking": flight,
        "assignment": assignment,
        "reservation_id": res["id"],
        "flight_tracking_id": flight["id"],
        "assignment_id": assignment["id"],
        "chauffeur_id": chauffeur["id"],
        "account_id": account["id"],
    }


# ===========================================================================
# Tier 6: billing helpers
# ===========================================================================
def invoice_reservation(reservation_id):
    """UNBILLED -> INVOICED (Dispatcher). Returns the reservation dict."""
    return get_success_data(
        api_client.create_billing_event(reservation_id, billing_event_payload("INVOICE"), DISPATCHER)
    )


def settle_reservation(reservation_id):
    """INVOICED -> SETTLED (Dispatcher). Returns the reservation dict."""
    return get_success_data(
        api_client.create_billing_event(reservation_id, billing_event_payload("SETTLE"), DISPATCHER)
    )
