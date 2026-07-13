"""Transitive cascades and compensating invariants: completion propagating to
partner year-to-date totals, cancellation propagating back to route volume, and
the two conserved quantities (route cubic feet, partner cents) returning to
their pre-mutation values.

Difficulty instances: transitive_cascade/*, compensating_invariant/*.
"""
from test_helpers import (
    api_client as api,
    validate_success,
    setup_scheduled_request, setup_completed_donation,
    make_donor_headers, make_partner_admin_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]

FURN = "FURNITURE"


# ─── Difficulty: complete DONATION -> receipt -> partner ytd ──────────

def test_completion_issues_receipt_with_final_value():
    """PRD §3.6: "for each item, multiply its value by the factor of its
    condition and round that product to whole cents using round-half-up; then
    add the rounded per-item results together."
    PRD §3.5: "the system issues a donation receipt in status ISSUED ... stamping
    its provisional_value_cents and final_value_cents (both computed as in
    Section 3.6)"

    Design: Difficulty/transitive_cascade/complete_donation_request_to_receipt_to_partner_ytd
    """
    ctx = setup_completed_donation(capacity_cf=100)
    assert ctx["receipt"]["final_value_cents"] == 1408


def test_receipt_issuance_recomputes_partner_ytd():
    """PRD §3.8: "A partner's ytd_donation_value_cents is the sum of
    final_value_cents over that partner's donation receipts that are currently
    ISSUED and whose issued_at falls in the same calendar year as the current
    logical clock. It is recomputed when a receipt is issued at donation
    completion and when a receipt is voided"

    Design: Difficulty/transitive_cascade/complete_donation_request_to_receipt_to_partner_ytd
    """
    ctx = setup_completed_donation(capacity_cf=100)
    partner = validate_success(api.get_partner(ctx["partner"]["id"], PLATFORM), 200)
    assert partner["ytd_donation_value_cents"] == 1408


# ─── Difficulty: cancel SCHEDULED -> stop -> route volume ─────────────

def test_cancel_scheduled_cancels_stop_and_request():
    """PRD §3.5: "Cancelling a SCHEDULED request advances it SCHEDULED ->
    CANCELLED and, because it had a stop, cancels that route stop (moving it to
    CANCELLED) and recomputes the route's reserved_volume_cf and
    total_stop_count."

    Design: Difficulty/transitive_cascade/cancel_scheduled_request_to_stop_to_route_volume
    """
    ctx = setup_scheduled_request(partner_categories=[FURN], capacity_cf=200,
                                  disposition="DONATION",
                                  items=[{"category": FURN, "volume_cf": 40}])
    donor_headers = make_donor_headers(ctx["donor"]["id"])
    validate_success(api.cancel_pickup(ctx["request"]["id"], donor_headers), 200)

    stops = validate_success(api.list_request_stops(ctx["request"]["id"], DISPATCHER), 200)
    assert stops[0]["status"] == "CANCELLED"
    request = validate_success(api.get_pickup_request(ctx["request"]["id"], DISPATCHER), 200)
    assert request["status"] == "CANCELLED"


def test_cancel_scheduled_recomputes_route_reserved_volume():
    """PRD §3.5: "recomputes the route's reserved_volume_cf and
    total_stop_count."
    PRD §3.3: "Its reserved_volume_cf is always the sum of the reserved_volume_cf
    snapshots of its stops that are currently RESERVED — stops that have moved to
    SERVICED or CANCELLED no longer contribute."

    Design: Difficulty/transitive_cascade/cancel_scheduled_request_to_stop_to_route_volume
    """
    ctx = setup_scheduled_request(partner_categories=[FURN], capacity_cf=200,
                                  disposition="DONATION",
                                  items=[{"category": FURN, "volume_cf": 40}])
    donor_headers = make_donor_headers(ctx["donor"]["id"])
    validate_success(api.cancel_pickup(ctx["request"]["id"], donor_headers), 200)
    route = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER), 200)
    assert route["reserved_volume_cf"] == 0


# ─── Difficulty: route reserved volume conserved (schedule -> cancel) ─

def test_route_reserved_volume_returns_to_zero():
    """PRD §3.4: "A successful schedule advances the request REQUESTED ->
    SCHEDULED and, as its side effects, creates a route stop joining the route
    and the request, recomputes the route's reserved_volume_cf and
    total_stop_count"
    PRD §3.5: "recomputes the route's reserved_volume_cf and total_stop_count."

    Design: Difficulty/compensating_invariant/route_reserved_volume_conserved_schedule_cancel
    """
    ctx = setup_scheduled_request(partner_categories=[FURN], capacity_cf=200,
                                  disposition="DONATION",
                                  items=[{"category": FURN, "volume_cf": 40}])
    scheduled = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER), 200)
    assert scheduled["reserved_volume_cf"] == 40

    donor_headers = make_donor_headers(ctx["donor"]["id"])
    validate_success(api.cancel_pickup(ctx["request"]["id"], donor_headers), 200)
    after = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER), 200)
    assert after["reserved_volume_cf"] == 0


def test_route_total_stop_count_returns_to_zero():
    """PRD §3.3: "Its total_stop_count is the number of its stops that are either
    RESERVED or SERVICED (cancelled stops are excluded)."

    Design: Difficulty/compensating_invariant/route_reserved_volume_conserved_schedule_cancel
    """
    ctx = setup_scheduled_request(partner_categories=[FURN], capacity_cf=200,
                                  disposition="DONATION",
                                  items=[{"category": FURN, "volume_cf": 40}])
    donor_headers = make_donor_headers(ctx["donor"]["id"])
    validate_success(api.cancel_pickup(ctx["request"]["id"], donor_headers), 200)
    after = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER), 200)
    assert after["total_stop_count"] == 0


# ─── Difficulty: partner ytd conserved (issue -> void) ────────────────

def test_partner_ytd_returns_to_zero_after_void():
    """PRD §3.8: "because a voided receipt leaves the ISSUED set, the
    recomputation naturally removes its contribution, which for a receipt issued
    in the current year debits exactly its final_value_cents."

    Design: Difficulty/compensating_invariant/partner_ytd_value_conserved_issue_void
    """
    ctx = setup_completed_donation(capacity_cf=100)
    before = validate_success(api.get_partner(ctx["partner"]["id"], PLATFORM), 200)
    assert before["ytd_donation_value_cents"] == 1408

    admin_headers = make_partner_admin_headers(ctx["partner"]["id"])
    validate_success(api.void_receipt(ctx["receipt"]["id"], admin_headers), 200)
    after = validate_success(api.get_partner(ctx["partner"]["id"], PLATFORM), 200)
    assert after["ytd_donation_value_cents"] == 0


def test_receipt_status_voided_after_void():
    """PRD §3.6: "A donation receipt may be voided by the partner administrator
    who owns it, advancing it ISSUED -> VOIDED"

    Design: Difficulty/compensating_invariant/partner_ytd_value_conserved_issue_void
    """
    ctx = setup_completed_donation(capacity_cf=100)
    admin_headers = make_partner_admin_headers(ctx["partner"]["id"])
    validate_success(api.void_receipt(ctx["receipt"]["id"], admin_headers), 200)
    receipt = validate_success(api.get_receipt(ctx["receipt"]["id"], admin_headers), 200)
    assert receipt["status"] == "VOIDED"
