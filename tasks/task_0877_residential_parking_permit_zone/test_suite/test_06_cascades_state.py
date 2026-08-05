"""Zone-suspend cascade, invalid-state lockdowns, and waitlist ordering.

Translates the Difficulty transitive_cascade zone-suspend instance and Corner
state_machine / calculation instances.
"""
from test_helpers import (
    validate_success, validate_error,
    approve_payload, deny_payload,
)
from test_helpers.fixtures import (
    set_clock, create_zone, register_household, add_vehicle,
    setup_verified_household_with_vehicle,
    create_application, review_application, approve_application, deny_application,
    issue_permit, issue_visitor_pass, waitlist_application, zone_version, SUP, CLERK,
)


# --------------------------------------------------------------------------
# transitive_cascade / zone_suspend_cascades_permits_then_passes
# --------------------------------------------------------------------------
def _zone_with_permit_and_pass(api):
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"], plate="TC2-A")
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])
    vp = issue_visitor_pass(api, hh["id"], permit["id"],
                            "2026-05-02T08:00:00.000Z", "2026-05-04T08:00:00.000Z",
                            pass_type="TEMPORARY", guest_plate="GTC2")
    return zone, hh, permit, vp


def test_zone_suspend_suspends_permit(api):
    """PRD §3.1: "Suspending an `ACTIVE` zone drives it `ACTIVE → SUSPENDED` and fires a
    two-link cascade: first, every permit in the zone whose status is `ACTIVE` or
    `RENEWAL_PENDING` is moved to `SUSPENDED`; second, for each permit just suspended,
    every visitor pass issued under it whose status is `ACTIVE` is moved to `CANCELLED`."

    Design: Difficulty/transitive_cascade/zone_suspend_cascades_permits_then_passes
    """
    zone, hh, permit, vp = _zone_with_permit_and_pass(api)
    suspended = validate_success(api.suspend_zone(zone["id"], SUP), 200)
    assert suspended["status"] == "SUSPENDED"
    permit_after = validate_success(api.get_permit(permit["id"], SUP), 200)
    assert permit_after["status"] == "SUSPENDED"


def test_zone_suspend_cancels_visitor_pass(api):
    """PRD §3.1: "second, for each permit just suspended, every visitor pass issued
    under it whose status is `ACTIVE` is moved to `CANCELLED`."

    Design: Difficulty/transitive_cascade/zone_suspend_cascades_permits_then_passes
    """
    zone, hh, permit, vp = _zone_with_permit_and_pass(api)
    validate_success(api.suspend_zone(zone["id"], SUP), 200)
    pass_after = validate_success(api.get_visitor_pass(vp["id"], SUP), 200)
    assert pass_after["status"] == "CANCELLED"


# --------------------------------------------------------------------------
# Corner/state_machines/suspend_already_suspended_zone_returns_invalid_state
# --------------------------------------------------------------------------
def test_suspend_already_suspended_zone_rejected(api):
    """PRD §3.1: "Attempting to suspend a zone that is not `ACTIVE`, or reactivate one
    that is not `SUSPENDED`, fails as an invalid state."

    Design: Corner/state_machines/suspend_already_suspended_zone_returns_invalid_state
    """
    zone = create_zone(api)
    validate_success(api.suspend_zone(zone["id"], SUP), 200)
    resp = api.suspend_zone(zone["id"], SUP)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


# --------------------------------------------------------------------------
# Corner/state_machines/approve_denied_application_returns_invalid_state
# --------------------------------------------------------------------------
def test_approve_denied_application_rejected(api):
    """PRD §3.4: "Any of these actions on an application not in the required state fails
    as an invalid state."

    Design: Corner/state_machines/approve_denied_application_returns_invalid_state
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    app = create_application(api, zone["id"], hh["id"], veh["id"])
    review_application(api, app["id"])
    deny_application(api, app["id"], denial_reason="ineligible")
    v = zone_version(api, zone["id"])
    resp = api.approve_permit_application(app["id"], approve_payload(v), SUP)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


# --------------------------------------------------------------------------
# Corner/calculations/waitlist_positions_ordered_by_created_at
# --------------------------------------------------------------------------
def test_waitlist_positions_ordered_by_created_at(api):
    """PRD §3.6: "The `position` is the 1-based rank of the entry among the zone's
    `WAITING` entries ordered by `created_at` ascending (ties broken by `created_at`
    ascending); the entry's own `id` is never used for ordering."

    Design: Corner/calculations/waitlist_positions_ordered_by_created_at
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=1)
    # Fill the single slot.
    h0, v0 = setup_verified_household_with_vehicle(api, zone["id"], plate="W0-A")
    issue_permit(api, zone["id"], h0["id"], v0["id"])
    # Two later applications, waitlisted in order.
    h1, v1 = setup_verified_household_with_vehicle(api, zone["id"], plate="W1-A")
    a1 = create_application(api, zone["id"], h1["id"], v1["id"])
    review_application(api, a1["id"])
    entry1 = waitlist_application(api, a1["id"])
    h2, v2 = setup_verified_household_with_vehicle(api, zone["id"], plate="W2-A")
    a2 = create_application(api, zone["id"], h2["id"], v2["id"])
    review_application(api, a2["id"])
    entry2 = waitlist_application(api, a2["id"])

    first = validate_success(api.get_waitlist_entry(entry1["id"], SUP), 200)
    second = validate_success(api.get_waitlist_entry(entry2["id"], SUP), 200)
    assert first["position"] == 1
    assert second["position"] == 2
    zone_after = validate_success(api.get_zone(zone["id"], SUP), 200)
    assert zone_after["waitlist_count"] == 2
