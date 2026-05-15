"""Dock slots, safety gating, overnight permits, and resource conflicts
— PRD §3.5, §3.1, §2.10.

Covers:
- safety-inspection gate on open-doors (PRE_OPEN PASS required)
- DockSlot creation requires the BoothAllocation to be CONFIRMED
- half-open [start_at, end_at) overlap on the same dock_code
- pointwise crane/forklift collisions on shared start_at across the
  exhibition
- overnight permit validation for 22:00-crossing windows (priority 7)
  ahead of business-temporal overlap (priority 12) — error-precedence
  test
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    confirm_allocation_as_owner,
    create_dock_slot_payload,
    create_safety_inspection_payload,
    iso_offset,
    iso_utc,
    make_exhibitor_headers,
    setup_exhibition_in_setup_with_confirmed_allocation,
    setup_exhibition_with_published_allocation,
    validate_error,
    validate_success,
)
from datetime import datetime, timedelta, timezone


# ===========================================================================
# Open-doors requires PRE_OPEN PASS (PRD §3.1, §3.5)
# ===========================================================================
class TestOpenDoorsRequiresSafetyInspection:
    # difficulty: cross_entity_state_dependency/open_doors_requires_safety_inspection

    def test_open_doors_without_pre_open_inspection_rejected(
        self, api, venue_admin_headers,
    ):
        """PRD §3.1: "Opening the doors then requires a PRE_OPEN
        SafetyInspection with a PASS result on the exhibition, and
        the current clock to be at or beyond open_date."
        PRD §3.1: "an attempt to open the doors without a PRE_OPEN
        PASS surfaces as ERR_SAFETY_INSPECTION_MISSING."

        Claim: open-doors before a PRE_OPEN PASS exists →
        ERR_SAFETY_INSPECTION_MISSING.
        """
        ctx = setup_exhibition_in_setup_with_confirmed_allocation(
            open_date=iso_offset(hours=-1),
            close_date=iso_offset(days=2),
        )
        res = api.open_doors(
            ctx["exhibition"]["id"], venue_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_SAFETY_INSPECTION_MISSING.value)

    def test_open_doors_succeeds_after_pre_open_pass(
        self, api, venue_admin_headers, venue_ops_headers,
    ):
        """PRD §3.1: "on success, the exhibition moves to OPEN and
        posture flips to OPEN."

        Claim: after recording a PRE_OPEN PASS inspection and being
        past open_date, open-doors → status=OPEN, posture=OPEN.
        """
        ctx = setup_exhibition_in_setup_with_confirmed_allocation(
            open_date=iso_offset(hours=-1),
            close_date=iso_offset(days=2),
        )
        api.create_safety_inspection(
            ctx["exhibition"]["id"],
            create_safety_inspection_payload(
                kind="PRE_OPEN", result="PASS",
            ),
            venue_ops_headers,
        )
        res = api.open_doors(
            ctx["exhibition"]["id"], venue_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "OPEN"
        assert data["posture"] == "OPEN"


# ===========================================================================
# DockSlot requires CONFIRMED allocation (PRD §3.5)
# ===========================================================================
class TestDockSlotRequiresConfirmedAllocation:
    # difficulty: cross_entity_state_dependency/dock_slot_book_requires_allocation_confirmed

    def test_dock_slot_creation_blocked_when_allocation_published_not_confirmed(
        self, api,
    ):
        """PRD §3.5: "The system requires that the acting exhibitor's
        X-User-ID equals the allocation's exhibitor_id, that the
        allocation is in CONFIRMED."

        Claim: POST /exhibitions/{id}/dock-slots when allocation is
        still PUBLISHED (not CONFIRMED) → ERR_INVALID_STATE.
        """
        ctx = setup_exhibition_with_published_allocation()
        headers = make_exhibitor_headers(ctx["exhibitor_id"])
        payload = create_dock_slot_payload(
            dock_code="D1",
            window_kind="MOVE_IN",
            start_at=iso_offset(hours=24),
            end_at=iso_offset(hours=26),
            allocation_id=ctx["allocation"]["id"],
        )
        res = api.create_dock_slot(
            ctx["exhibition"]["id"], payload, headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_dock_slot_creation_succeeds_after_confirm_and_setup(
        self, api,
    ):
        """PRD §3.5: "a MOVE_IN slot is booked only while the
        exhibition is in SETUP."
        PRD §3.5: "A new slot enters BOOKED directly on creation."

        Claim: after confirm + start-setup, a MOVE_IN dock slot in
        SETUP succeeds with status=BOOKED.
        """
        ctx = setup_exhibition_in_setup_with_confirmed_allocation()
        headers = make_exhibitor_headers(ctx["exhibitor_id"])
        # Pick times comfortably inside daytime (10–11 UTC).
        base = datetime.now(tz=timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0,
        ) + timedelta(days=1)
        payload = create_dock_slot_payload(
            dock_code="D1",
            window_kind="MOVE_IN",
            start_at=iso_utc(base),
            end_at=iso_utc(base + timedelta(hours=1)),
            allocation_id=ctx["allocation"]["id"],
        )
        res = api.create_dock_slot(
            ctx["exhibition"]["id"], payload, headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "BOOKED"


# ===========================================================================
# Half-open dock-slot overlap (PRD §3.5)
# ===========================================================================
class TestDockSlotHalfOpenOverlap:
    # difficulty: resource_temporal_overlap/dock_half_open_interval_overlap

    def _setup_ctx_with_two_exhibitors_confirmed(self, api):
        """Build an exhibition in SETUP with two CONFIRMED allocations
        on STANDARD booths (one per exhibitor). PRD §3.5: dock-slot
        creation requires a CONFIRMED allocation.
        """
        from test_helpers import (
            create_allocation,
            create_booth,
            create_qualified_application,
            open_intake,
            publish_allocation,
            setup_exhibition_with_active_plan,
        )
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
        # Refresh.
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
        exh = validate_success(
            api.start_setup(
                exh["id"], TEST_USERS["venue_admin_headers"],
            ),
            expected_status=200,
        )
        # Refresh allocations.
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
        return {
            "exhibition": exh,
            "alloc1": alloc1, "exhibitor_id_1": eid1,
            "alloc2": alloc2, "exhibitor_id_2": eid2,
        }

    def test_adjacent_dock_slots_on_same_dock_succeed(self, api):
        """PRD §3.5: "the [start_at, end_at) half-open interval must
        not overlap any other BOOKED slot on the same dock_code."
        PRD §3.5 (interval semantics): the inclusive-start /
        exclusive-end convention means adjacency at one instant is not
        an overlap.

        Claim: two slots on dock D1 with intervals [10:00,11:00) and
        [11:00,12:00) both succeed.
        """
        ctx = self._setup_ctx_with_two_exhibitors_confirmed(api)
        base = (
            datetime.now(tz=timezone.utc)
            .replace(hour=10, minute=0, second=0, microsecond=0)
            + timedelta(days=2)
        )
        h1 = make_exhibitor_headers(ctx["exhibitor_id_1"])
        h2 = make_exhibitor_headers(ctx["exhibitor_id_2"])
        # First slot 10–11.
        r1 = api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D1", window_kind="MOVE_IN",
                start_at=iso_utc(base),
                end_at=iso_utc(base + timedelta(hours=1)),
                allocation_id=ctx["alloc1"]["id"],
            ),
            h1,
        )
        validate_success(r1, expected_status=201)
        # Adjacent slot 11–12.
        r2 = api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D1", window_kind="MOVE_IN",
                start_at=iso_utc(base + timedelta(hours=1)),
                end_at=iso_utc(base + timedelta(hours=2)),
                allocation_id=ctx["alloc2"]["id"],
            ),
            h2,
        )
        data2 = validate_success(r2, expected_status=201)
        assert data2["status"] == "BOOKED"

    def test_overlapping_dock_slots_on_same_dock_rejected(self, api):
        """PRD §3.5: "the [start_at, end_at) half-open interval must
        not overlap any other BOOKED slot on the same dock_code;
        overlap is rejected with ERR_DOCK_SLOT_OVERLAP."

        Claim: a second slot on D1 whose [start, end) intersects an
        existing BOOKED slot → ERR_DOCK_SLOT_OVERLAP.
        """
        ctx = self._setup_ctx_with_two_exhibitors_confirmed(api)
        base = (
            datetime.now(tz=timezone.utc)
            .replace(hour=10, minute=0, second=0, microsecond=0)
            + timedelta(days=2)
        )
        h1 = make_exhibitor_headers(ctx["exhibitor_id_1"])
        h2 = make_exhibitor_headers(ctx["exhibitor_id_2"])
        # First slot 10–11.
        api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D1", window_kind="MOVE_IN",
                start_at=iso_utc(base),
                end_at=iso_utc(base + timedelta(hours=1)),
                allocation_id=ctx["alloc1"]["id"],
            ),
            h1,
        )
        # Second slot 10:30–11:30 overlaps.
        r2 = api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D1", window_kind="MOVE_IN",
                start_at=iso_utc(base + timedelta(minutes=30)),
                end_at=iso_utc(base + timedelta(hours=1, minutes=30)),
                allocation_id=ctx["alloc2"]["id"],
            ),
            h2,
        )
        validate_error(r2, ApiErrorId.ERR_DOCK_SLOT_OVERLAP.value)


# ===========================================================================
# Crane/forklift pointwise contention (PRD §3.5)
# ===========================================================================
class TestCraneForkliftPointwiseContention:
    # difficulty: resource_temporal_overlap/crane_resource_pointwise_overlap

    def test_crane_collision_across_docks_at_same_start_at_rejected(
        self, api,
    ):
        """PRD §3.5: "crane and forklift contention are checked
        exhibition-wide and per-resource: at most one BOOKED slot
        anywhere on the exhibition may have crane_required true at the
        same start_at, and the same rule applies independently to
        forklift_required — a conflict surfaces as
        ERR_RESOURCE_CONFLICT."

        Claim: two crane-required slots at the same start_at, on
        different dock_codes, conflict → ERR_RESOURCE_CONFLICT.
        """
        ctx = TestDockSlotHalfOpenOverlap()._setup_ctx_with_two_exhibitors_confirmed(api)
        base = (
            datetime.now(tz=timezone.utc)
            .replace(hour=9, minute=0, second=0, microsecond=0)
            + timedelta(days=2)
        )
        h1 = make_exhibitor_headers(ctx["exhibitor_id_1"])
        h2 = make_exhibitor_headers(ctx["exhibitor_id_2"])
        # First slot dock D1 with crane.
        api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D1", window_kind="MOVE_IN",
                start_at=iso_utc(base),
                end_at=iso_utc(base + timedelta(hours=2)),
                allocation_id=ctx["alloc1"]["id"],
                crane_required=True,
            ),
            h1,
        )
        # Second slot DIFFERENT dock D2 at same start_at, crane required.
        res = api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D2", window_kind="MOVE_IN",
                start_at=iso_utc(base),
                end_at=iso_utc(base + timedelta(hours=1)),
                allocation_id=ctx["alloc2"]["id"],
                crane_required=True,
            ),
            h2,
        )
        validate_error(res, ApiErrorId.ERR_RESOURCE_CONFLICT.value)

    def test_forklift_collision_at_same_start_at_rejected(self, api):
        """PRD §3.5: "the same rule applies independently to
        forklift_required."

        Claim: two forklift-required slots at the same start_at
        conflict → ERR_RESOURCE_CONFLICT.
        """
        ctx = TestDockSlotHalfOpenOverlap()._setup_ctx_with_two_exhibitors_confirmed(api)
        base = (
            datetime.now(tz=timezone.utc)
            .replace(hour=9, minute=0, second=0, microsecond=0)
            + timedelta(days=2)
        )
        h1 = make_exhibitor_headers(ctx["exhibitor_id_1"])
        h2 = make_exhibitor_headers(ctx["exhibitor_id_2"])
        api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D1", window_kind="MOVE_IN",
                start_at=iso_utc(base),
                end_at=iso_utc(base + timedelta(hours=2)),
                allocation_id=ctx["alloc1"]["id"],
                forklift_required=True,
            ),
            h1,
        )
        res = api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D2", window_kind="MOVE_IN",
                start_at=iso_utc(base),
                end_at=iso_utc(base + timedelta(hours=1)),
                allocation_id=ctx["alloc2"]["id"],
                forklift_required=True,
            ),
            h2,
        )
        validate_error(res, ApiErrorId.ERR_RESOURCE_CONFLICT.value)


# ===========================================================================
# Overnight permit validation (PRD §3.5)
# ===========================================================================
class TestOvernightPermit:
    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_dock_slot

    def test_overnight_window_without_permit_rejected(self, api):
        """PRD §3.5: "Any slot whose [start_at, end_at) crosses 22:00
        local must be created with overnight_permit set to true;
        missing the permit surfaces as ERR_OVERNIGHT_PERMIT_REQUIRED."

        Claim: a dock-slot whose window crosses 22:00 local without
        overnight_permit=true → ERR_OVERNIGHT_PERMIT_REQUIRED.
        """
        ctx = TestDockSlotHalfOpenOverlap()._setup_ctx_with_two_exhibitors_confirmed(api)
        # Build a window crossing 22:00 UTC.
        base_day = (
            datetime.now(tz=timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=2)
        )
        start = base_day.replace(hour=21, minute=30)
        end = base_day.replace(hour=23, minute=0)
        h1 = make_exhibitor_headers(ctx["exhibitor_id_1"])
        res = api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D1", window_kind="MOVE_IN",
                start_at=iso_utc(start),
                end_at=iso_utc(end),
                allocation_id=ctx["alloc1"]["id"],
            ),
            h1,
        )
        validate_error(res, ApiErrorId.ERR_OVERNIGHT_PERMIT_REQUIRED.value)

    def test_overnight_window_with_permit_succeeds(self, api):
        """PRD §3.5: "Any slot whose [start_at, end_at) crosses 22:00
        local must be created with overnight_permit set to true."

        Claim: same window with overnight_permit=true → BOOKED.
        """
        ctx = TestDockSlotHalfOpenOverlap()._setup_ctx_with_two_exhibitors_confirmed(api)
        base_day = (
            datetime.now(tz=timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=2)
        )
        start = base_day.replace(hour=21, minute=30)
        end = base_day.replace(hour=23, minute=0)
        h1 = make_exhibitor_headers(ctx["exhibitor_id_1"])
        res = api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D1", window_kind="MOVE_IN",
                start_at=iso_utc(start),
                end_at=iso_utc(end),
                allocation_id=ctx["alloc1"]["id"],
                overnight_permit=True,
            ),
            h1,
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "BOOKED"

    def test_overnight_permit_required_takes_precedence_over_dock_overlap(
        self, api,
    ):
        """PRD §2.10: "then domain-safety gates such as posture,
        safety-inspection presence, and overnight-permit requirement,
        then business constraints (fire-safety cells, utility load,
        theme intersection, capacity, group, relocation tier,
        work-order line shape, dispute resolution band, floor-plan
        lock)."
        PRD §3.5: "Any slot whose [start_at, end_at) crosses 22:00
        local must be created with overnight_permit set to true;
        missing the permit surfaces as ERR_OVERNIGHT_PERMIT_REQUIRED."

        Claim: when a request would fail BOTH the overnight-permit
        gate (safety, higher priority) AND the dock-slot-overlap
        gate (business_temporal, lower priority), the server returns
        ERR_OVERNIGHT_PERMIT_REQUIRED — the higher-priority error
        wins. (Distinguishes priority 7 vs priority 12 in the same
        request.)
        """
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_dock_slot
        ctx = TestDockSlotHalfOpenOverlap()._setup_ctx_with_two_exhibitors_confirmed(api)
        base_day = (
            datetime.now(tz=timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=2)
        )
        # First slot 21:00–23:30 with permit=true → BOOKED.
        first_start = base_day.replace(hour=21, minute=0)
        first_end = base_day.replace(hour=23, minute=30)
        h1 = make_exhibitor_headers(ctx["exhibitor_id_1"])
        h2 = make_exhibitor_headers(ctx["exhibitor_id_2"])
        api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D1", window_kind="MOVE_IN",
                start_at=iso_utc(first_start),
                end_at=iso_utc(first_end),
                allocation_id=ctx["alloc1"]["id"],
                overnight_permit=True,
            ),
            h1,
        )
        # Second slot 21:30–22:30 (contains 22:00 → crosses; overlaps the first).
        second_start = base_day.replace(hour=21, minute=30)
        second_end = base_day.replace(hour=22, minute=30)
        res = api.create_dock_slot(
            ctx["exhibition"]["id"],
            create_dock_slot_payload(
                dock_code="D1", window_kind="MOVE_IN",
                start_at=iso_utc(second_start),
                end_at=iso_utc(second_end),
                allocation_id=ctx["alloc2"]["id"],
                overnight_permit=False,  # MISSING permit → priority 7 fires first
            ),
            h2,
        )
        validate_error(res, ApiErrorId.ERR_OVERNIGHT_PERMIT_REQUIRED.value)
