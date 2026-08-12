"""Transitive cascades: compliance-expiry three-hop chain from the ops cycle,
and the client-suspension two-hop chain from a coordinator PATCH."""
from test_helpers import (
    TEST_USERS,
    create_booked_ride,
    create_compliant_driver,
    dispatch_and_accept,
    get_success_data,
    make_driver_headers,
    set_clock,
    setup_standard_dispatch_env,
    suspend_client,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def _setup_expiry_cascade():
    """Driver ACTIVE with BONDING valid only [2026-01-01, 2026-06-30);
    ride ASSIGNED to that driver; clock advanced to 2026-06-30.
    Returns (driver, docs, ride, assignment)."""
    client, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-06-01T09:00:00Z")
    driver, docs = create_compliant_driver(
        doc_validity={"BONDING": ("2026-01-01", "2026-06-30")})
    ride = create_booked_ride(
        client["id"], kind="APPOINTMENT",
        scheduled_pickup_at="2026-06-10T10:00:00Z")
    _, assignment = dispatch_and_accept(ride["id"], driver["id"])
    set_clock("2026-06-30T00:00:00Z")
    return driver, docs, ride, assignment


def test_run_cycle_expires_doc_and_suspends_driver(api):
    """PRD §3.10: "First, document expiry: every `APPROVED` compliance document
    whose `valid_until` has arrived — the half-open window has ended at the
    logical today — moves to `EXPIRED`, and when the owning driver is `ACTIVE`
    and no other approved document of the same type covers today, the posture
    has collapsed and the driver is auto-suspended with the full release
    cascade of §3.2."

    Design: Difficulty/transitive_cascade/compliance_expiry_three_hop_cascade
    """
    driver, docs, _, _ = _setup_expiry_cascade()
    cycle = get_success_data(api_client.run_cycle(ADMIN))
    assert docs["BONDING"]["id"] in cycle["expired_compliance_doc_ids"]
    doc = validate_success(api_client.get_compliance_doc(docs["BONDING"]["id"], OFFICER))
    assert doc["status"] == "EXPIRED", (
        "half-open window [2026-01-01, 2026-06-30) closed at 2026-06-30")
    driver_after = validate_success(api_client.get_driver(driver["id"], COORD))
    assert driver_after["status"] == "SUSPENDED", (
        "posture collapsed: no APPROVED BONDING covers today")


def test_suspension_cascade_releases_assignment_and_rematches_ride(api):
    """PRD §3.2: "When an `ACTIVE` driver is suspended — manually by a
    coordinator, or automatically when the ops cycle finds the posture newly
    incomplete — every `ACCEPTED` assignment of that driver whose ride still
    sits in `ASSIGNED` is released with `release_reason` of `DRIVER_SUSPENDED`,
    and each such ride returns to `DISPATCHING` with `assigned_driver_id`
    cleared, `dispatch_round` incremented by one, and the suspended driver
    appended to the ride's `excluded_driver_ids`."

    Design: Difficulty/transitive_cascade/compliance_expiry_three_hop_cascade
    """
    driver, _, ride, assignment = _setup_expiry_cascade()
    get_success_data(api_client.run_cycle(ADMIN))
    asg = validate_success(api_client.get_assignment(assignment["id"], COORD))
    assert asg["status"] == "RELEASED"
    assert asg["release_reason"] == "DRIVER_SUSPENDED"
    ride_after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert ride_after["status"] == "DISPATCHING"
    assert ride_after["dispatch_round"] == 2
    assert ride_after["assigned_driver_id"] is None
    assert driver["id"] in ride_after["excluded_driver_ids"]


def _setup_client_suspension_cascade():
    """Client with a DISPATCHING ride holding a live OFFERED assignment.
    Returns (client, ride, offer)."""
    client, driver = setup_standard_dispatch_env()
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    offer = get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    return client, ride, offer


def test_client_suspension_cancels_dispatching_ride_fee_free(api):
    """PRD §3.1: "Suspending a client (`ACTIVE` → `SUSPENDED`) fires a cascade:
    every ride of that client still in `SCHEDULED` or `DISPATCHING` is
    cancelled fee-free with `cancel_reason` recorded as `CLIENT_SUSPENDED` and
    `cancelled_by_role` recorded as the system, any live `OFFERED` assignments
    on a dispatching ride are expired with `release_reason` of `RIDE_CANCELLED`,
    and the client's `version` increments."

    Design: Difficulty/transitive_cascade/client_suspension_two_hop_cascade
    """
    client, ride, _ = _setup_client_suspension_cascade()
    suspended = suspend_client(client["id"], client["version"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == client["version"] + 1
    ride_after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert ride_after["status"] == "CANCELLED"
    assert ride_after["cancellation_fee_cents"] == 0
    assert ride_after["cancel_reason"] == "CLIENT_SUSPENDED"
    assert ride_after["cancelled_by_role"] == "system"


def test_client_suspension_expires_live_offer(api):
    """PRD §3.1: "any live `OFFERED` assignments on a dispatching ride are
    expired with `release_reason` of `RIDE_CANCELLED`"
    PRD §3.7: "Cancelling a `DISPATCHING` ride expires its live `OFFERED`
    assignments with `release_reason` of `RIDE_CANCELLED`."

    Design: Difficulty/transitive_cascade/client_suspension_two_hop_cascade
    """
    client, _, offer = _setup_client_suspension_cascade()
    suspend_client(client["id"], client["version"])
    asg = validate_success(api_client.get_assignment(offer["id"], COORD))
    assert asg["status"] == "EXPIRED", (
        f"hop 2: the ride's cancellation expires the live offer; got {asg['status']}")
    assert asg["release_reason"] == "RIDE_CANCELLED"
