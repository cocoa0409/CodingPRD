"""Concurrency and serialization — PRD §2.12.

PRD §2.12 explicitly names the loser error_id for each race, so these
tests assert both the success count AND the specific error_id. They
use the framework's run_race + assert_exactly_one_succeeds helpers.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_exactly_one_succeeds,
    create_dock_slot_payload,
    iso_offset,
    iso_utc,
    make_exhibitor_headers,
    run_race,
    setup_exhibition_in_setup_with_confirmed_allocation,
    setup_open_exhibition_at_occupancy,
    validate_error,
    validate_error_is_one_of,
)
from datetime import datetime, timedelta, timezone


# ===========================================================================
# Two simultaneous scan-ins of the same ticket (PRD §2.12)
# ===========================================================================
class TestScanInRace:

    def test_two_scan_ins_of_same_ticket_exactly_one_succeeds(
        self, api, gate_operator_headers,
    ):
        """PRD §2.12: "Two scan-ins of the same ticket serialize on
        its ISSUED → SCANNED_IN transition: only one increments
        live_occupancy, the loser receives ERR_INVALID_STATE (409)."

        Claim: of two concurrent scan-in calls on the same ticket,
        exactly one succeeds; the loser carries ERR_INVALID_STATE.
        """
        ctx = setup_open_exhibition_at_occupancy(
            capacity_max=10,
            target_live_occupancy=0,
            extra_unscanned_tickets=1,
        )
        ticket = ctx["issued_tickets"][0]
        results = run_race(
            lambda: api.scan_in_ticket(ticket["id"], gate_operator_headers),
            lambda: api.scan_in_ticket(ticket["id"], gate_operator_headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # Loser must carry ERR_INVALID_STATE per PRD §2.12.
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_INVALID_STATE.value],
        )


# ===========================================================================
# Two scan-ins racing at capacity boundary (PRD §2.12)
# ===========================================================================
class TestScanInAtCapacityRace:

    def test_two_scan_ins_at_capacity_minus_one_exactly_one_succeeds(
        self, api, gate_operator_headers,
    ):
        """PRD §2.12: "Two scan-ins racing at the capacity boundary
        (live_occupancy equal to one less than capacity_max) serialize
        on the atomic occupancy increment: exactly one succeeds, the
        loser receives ERR_CAPACITY_EXCEEDED (409)."

        Claim: at live_occupancy == capacity_max - 1, two concurrent
        scan-ins of different tickets — exactly one succeeds; loser
        carries ERR_CAPACITY_EXCEEDED.
        """
        ctx = setup_open_exhibition_at_occupancy(
            capacity_max=5,
            target_live_occupancy=4,
            extra_unscanned_tickets=2,
        )
        t_a, t_b = ctx["issued_tickets"][0], ctx["issued_tickets"][1]
        results = run_race(
            lambda: api.scan_in_ticket(t_a["id"], gate_operator_headers),
            lambda: api.scan_in_ticket(t_b["id"], gate_operator_headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_CAPACITY_EXCEEDED.value],
        )


# ===========================================================================
# Confirm vs revoke racing on the same allocation (PRD §2.12)
# ===========================================================================
class TestConfirmVsRevokeRace:

    def test_confirm_vs_revoke_on_same_published_allocation(
        self, api, venue_admin_headers,
    ):
        """PRD §2.12: "A confirm and a revoke racing on the same
        allocation in PUBLISHED serialize on its outgoing transition:
        exactly one wins, the loser receives ERR_INVALID_STATE (409)."

        Claim: of one confirm-by-owner and one revoke-by-admin
        running concurrently on a PUBLISHED allocation, exactly one
        succeeds; loser carries ERR_INVALID_STATE.
        """
        from test_helpers import (
            revoke_allocation_payload,
            setup_two_standard_booths_with_published_allocation_on_first,
        )
        ctx = setup_two_standard_booths_with_published_allocation_on_first()
        owner = make_exhibitor_headers(ctx["exhibitor_id"])
        results = run_race(
            lambda: api.confirm_allocation(
                ctx["allocation"]["id"], owner,
            ),
            lambda: api.revoke_allocation(
                ctx["allocation"]["id"],
                revoke_allocation_payload(reason="admin-revoke"),
                venue_admin_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_INVALID_STATE.value],
        )


# ===========================================================================
# Two simultaneous dock slots overlapping (PRD §2.12)
# ===========================================================================
class TestDockSlotOverlapRace:

    def test_two_overlapping_dock_slots_loser_overlap(self, api):
        """PRD §2.12: "Two exhibitors attempting to book overlapping
        intervals on the same dock_code serialize on DockSlot row
        creation: at most one succeeds, the loser receives
        ERR_DOCK_SLOT_OVERLAP (409)."

        Claim: two concurrent dock-slot creations whose intervals
        intersect on the same dock_code: exactly one succeeds; loser
        carries ERR_DOCK_SLOT_OVERLAP.
        """
        # Need two confirmed allocations to issue two parallel requests
        # under different exhibitors.
        from test_helpers import (
            advance_clock,
            confirm_allocation_as_owner,
            create_allocation,
            create_booth,
            create_qualified_application,
            open_intake,
            publish_allocation,
            setup_exhibition_with_active_plan,
        )
        from test_helpers import validate_success
        exh, hall, _ = setup_exhibition_with_active_plan(
            theme_code="GEN",
            objection_window_hours=1,
            open_date=iso_offset(days=10),
            close_date=iso_offset(days=17),
        )
        b1 = create_booth(
            hall["id"], cells=[{"row": 1, "col": 1}],
            tier="STANDARD", code="B1",
        )
        b2 = create_booth(
            hall["id"], cells=[{"row": 3, "col": 3}],
            tier="STANDARD", code="B2",
        )
        open_intake(exh["id"])
        app1, eid1 = create_qualified_application(
            exh["id"], theme_tags=["GEN"], requested_tier="STANDARD",
        )
        app2, eid2 = create_qualified_application(
            exh["id"], theme_tags=["GEN"], requested_tier="STANDARD",
        )
        alloc1 = create_allocation(app1["id"], b1["id"])
        alloc2 = create_allocation(app2["id"], b2["id"])
        publish_allocation(exh["id"])
        alloc1 = validate_success(
            api.get_allocation(
                alloc1["id"], TEST_USERS["venue_admin_headers"],
            ),
            expected_status=200,
        )
        alloc2 = validate_success(
            api.get_allocation(
                alloc2["id"], TEST_USERS["venue_admin_headers"],
            ),
            expected_status=200,
        )
        confirm_allocation_as_owner(alloc1["id"], eid1)
        confirm_allocation_as_owner(alloc2["id"], eid2)
        advance_clock(to=iso_offset(hours=2))
        # start-setup.
        api.start_setup(exh["id"], TEST_USERS["venue_admin_headers"])
        # Two concurrent overlapping slots on dock D1.
        h1 = make_exhibitor_headers(eid1)
        h2 = make_exhibitor_headers(eid2)
        base = (
            datetime.now(tz=timezone.utc)
            .replace(hour=10, minute=0, second=0, microsecond=0)
            + timedelta(days=3)
        )
        payload_a = create_dock_slot_payload(
            dock_code="D1", window_kind="MOVE_IN",
            start_at=iso_utc(base),
            end_at=iso_utc(base + timedelta(hours=2)),
            allocation_id=alloc1["id"],
        )
        payload_b = create_dock_slot_payload(
            dock_code="D1", window_kind="MOVE_IN",
            start_at=iso_utc(base + timedelta(minutes=30)),
            end_at=iso_utc(base + timedelta(hours=1, minutes=30)),
            allocation_id=alloc2["id"],
        )
        results = run_race(
            lambda: api.create_dock_slot(exh["id"], payload_a, h1),
            lambda: api.create_dock_slot(exh["id"], payload_b, h2),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_DOCK_SLOT_OVERLAP.value],
        )
