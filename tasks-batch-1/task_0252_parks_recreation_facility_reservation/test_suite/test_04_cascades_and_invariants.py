"""Transitive cascades and compensating invariants.

Covers difficulty instances transitive_cascade (league cancel -> child permit ->
refund; no-show -> standing -> barred block) and compensating_invariant (deny
voids the captured payment; complete releases the deposit and restores count).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    set_clock, create_facility, create_patron, apply_permit, capture_payment,
    facility_version, grant_permit, setup_granted_permit,
    setup_league_with_children, get_first_refund, make_patron_headers, TEST_USERS,
)

COORD = TEST_USERS["rec_coordinator_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


def test_league_cancel_cascades_to_granted_child_refund(api):
    """PRD §3.8: "Cancelling rolls the series to CANCELLED and cascades down: every
    child permit that is not already in a terminal state is cancelled through the
    permit cancel path."
    PRD §3.8: "a child currently GRANTED follows the GRANTED → CANCELLED path —
    running the tiered cancellation refund, creating its own Refund, decrementing
    the facility's granted_permit_count, and bumping the facility's version — so a
    single league cancellation can transitively spawn many refunds and many facility
    mutations."
    PRD §3.7: "If the lead is at least 168 hours — a full seven days — the entire
    usage fee is refunded."

    League with 2 occurrences; one child GRANTED (fee 20000, deposit 5000). Cancel
    the league at a lead well over 168h → child CANCELLED, full refund 25000,
    facility count back to 0.

    Design: Difficulty/transitive_cascade/tc_league_cancel_to_permit_to_refund_depth3
    """
    ctx = setup_league_with_children(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={
            "name": "League Field", "facility_type": "FIELD", "hourly_rate_cents": 10000,
            "resident_discount_pct": 0.0, "prime_multiplier": 1.5,
            "prime_start_hour": 18, "prime_end_hour": 22, "deposit_cents": 5000,
            "buffer_minutes": 0,
        },
        occurrences=2, weekday=1, start_hour=10, duration_minutes=120,
        first_date="2026-08-04T00:00:00Z",
    )
    facility, patron, league, children = (
        ctx["facility"], ctx["patron"], ctx["league"], ctx["children"])
    child0 = children[0]

    capture_payment(child0["id"], 20000, 5000)
    v = facility_version(facility["id"])
    grant_permit(facility["id"], child0["id"], v)

    cancelled = validate_success(api.cancel_league(
        league["id"], {"refund_destination": "ORIGINAL"},
        make_patron_headers(patron["id"])), 200)
    assert cancelled["status"] == "CANCELLED"

    child_after = validate_success(api.get_permit(child0["id"], COORD), 200)
    assert child_after["status"] == "CANCELLED"

    refund = get_first_refund(child0["id"])
    assert refund is not None, "GRANTED child cancellation creates a Refund"
    assert refund["total_refund_cents"] == 25000, "full fee 20000 + deposit 5000 at lead > 168h"

    fac_after = validate_success(api.get_facility(facility["id"], COORD), 200)
    assert fac_after["granted_permit_count"] == 0, "transitive decrement of facility count"


def test_no_show_drives_standing_to_barred_and_blocks_apply(api):
    """PRD §3.7: "Marking a no-show moves the permit GRANTED → NO_SHOW, forfeits
    deposit_held_cents entirely with no refund created, increments the patron's
    no_show_strikes by one and recomputes the patron's standing from the new count,
    decrements the facility's granted_permit_count by one, and increments the
    facility's version by one."
    PRD §3.1: "if no_show_strikes is at least 4 the standing is BARRED; otherwise if
    no_show_strikes is at least 2 the standing is PROBATION; otherwise the standing
    is GOOD."
    PRD §3.3: "A patron whose standing is BARRED cannot apply; such an application
    is rejected with ERR_PATRON_BARRED (HTTP 403)."

    Patron pre-seeded with 3 strikes (PROBATION); no-show a 4th granted permit →
    strikes 4 → BARRED → next apply blocked.

    Design: Difficulty/transitive_cascade/tc_no_show_to_standing_to_barred_block_depth2
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="NS Court", facility_type="COURT", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=1000, buffer_minutes=0,
    )
    patron = create_patron(residency="NON_RESIDENT")
    validate_success(api.inject_no_show_strikes(patron["id"], 3, COORD), 200)

    permit = apply_permit(facility["id"], patron["id"],
                          "2026-07-05T10:00:00Z", "2026-07-05T12:00:00Z")
    capture_payment(permit["id"], 20000, 1000)
    v = facility_version(facility["id"])
    grant_permit(facility["id"], permit["id"], v)

    set_clock("2026-07-05T13:00:00Z")
    ns = validate_success(api.no_show_permit(facility["id"], permit["id"], COORD), 200)
    assert ns["status"] == "NO_SHOW"

    patron_after = validate_success(api.get_patron(patron["id"], COORD), 200)
    assert patron_after["no_show_strikes"] == 4
    assert patron_after["standing"] == "BARRED"

    res = api.apply_permit(
        facility["id"],
        {"patron_id": patron["id"], "start_at": "2026-08-10T10:00:00Z",
         "end_at": "2026-08-10T12:00:00Z"},
        make_patron_headers(patron["id"]))
    validate_error(res, "ERR_PATRON_BARRED")


def test_deny_voids_captured_payment_no_money_retained(api):
    """PRD §3.5: "If a CAPTURED payment exists for the permit it is VOIDED and fully
    reversed as a compensation, with no cancellation fee taken."
    PRD §3.5: "Denying moves the permit APPLIED -> DENIED."

    APPLIED permit with CAPTURED payment (fee 20000 + deposit 1000); deny -> permit
    DENIED, payment VOIDED, refunded_cents stays 0 (deny is not a late cancel).

    Design: Difficulty/compensating_invariant/ci_deny_voids_payment_money_conserved
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="Deny Court", facility_type="COURT", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=1000,
    )
    patron = create_patron(residency="NON_RESIDENT")
    permit = apply_permit(facility["id"], patron["id"],
                          "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z")
    payment = capture_payment(permit["id"], 20000, 1000)

    denied = validate_success(api.deny_permit(facility["id"], permit["id"], COORD), 200)
    assert denied["status"] == "DENIED"

    pay_after = validate_success(api.get_payment(payment["id"], FINANCE), 200)
    assert pay_after["status"] == "VOIDED"

    permit_after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert permit_after["refunded_cents"] == 0, "no fee captured nor charged on deny"


def test_complete_releases_deposit_and_restores_count(api):
    """PRD §3.7: "Completing moves the permit GRANTED -> COMPLETED, releases the
    deposit in full by creating a Refund whose deposit_refund_cents equals
    deposit_held_cents and whose fee_refund_cents is 0, decrements the facility's
    granted_permit_count by one, and increments the facility's version by one."

    Grant (count 0 -> 1), complete after end_at -> count back to 0, deposit 5000
    released in full.

    Design: Difficulty/compensating_invariant/ci_complete_releases_deposit_count_conserved
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={
            "name": "Comp Pool", "facility_type": "POOL", "hourly_rate_cents": 10000,
            "resident_discount_pct": 0.0, "prime_multiplier": 1.5,
            "prime_start_hour": 18, "prime_end_hour": 22, "deposit_cents": 5000,
        },
        start_at="2026-07-03T10:00:00Z", end_at="2026-07-03T12:00:00Z",
        fee_component_cents=20000, deposit_component_cents=5000,
    )
    facility, permit = ctx["facility"], ctx["permit"]
    fac_granted = validate_success(api.get_facility(facility["id"], COORD), 200)
    assert fac_granted["granted_permit_count"] == 1

    set_clock("2026-07-03T13:00:00Z")
    completed = validate_success(api.complete_permit(facility["id"], permit["id"], COORD), 200)
    assert completed["status"] == "COMPLETED"

    fac_after = validate_success(api.get_facility(facility["id"], COORD), 200)
    assert fac_after["granted_permit_count"] == 0, "count back to pre-grant value"

    refund = get_first_refund(permit["id"])
    assert refund is not None, "completion creates a deposit-release Refund"
    assert refund["deposit_refund_cents"] == 5000
    assert refund["fee_refund_cents"] == 0
