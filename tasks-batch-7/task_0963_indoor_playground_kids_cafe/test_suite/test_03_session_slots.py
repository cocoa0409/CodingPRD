"""Session slot quota/counters, half-open overlap semantics, capacity-patch
OCC, and list pagination (PRD §2.3, §2.7, §2.9, §3.3)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, assert_session_slot, TEST_DEFAULTS,
    reset_clock, make_staff, staff_headers, create_slot, create_open_slot,
    create_reservation, check_in_visit, set_clock,
    setup_reserved_visit, get_slot_fresh, guardian_headers, add_child,
)
from test_helpers import api_client


class TestReservationQuotaComputation:
    def test_reservation_quota_floored_for_odd_capacity(self, api):
        """PRD §3.3: "A new slot starts `SCHEDULED`, with its
        `reservation_quota` computed as seventy percent of `capacity` rounded
        down".

        Capacity 11 -> floor(7.7) = 7, not 8.

        Design: Corner/calculations/reservation_quota_floored_for_odd_capacity
        """
        mgr = make_staff("MANAGER", "Mgr One")
        slot = create_slot(staff_headers(mgr), capacity=11)
        assert_session_slot(slot)
        assert slot["reservation_quota"] == 7
        assert slot["status"] == "SCHEDULED"
        assert slot["reserved_count"] == 0 and slot["checked_in_count"] == 0


class TestSlotCountersReconciliation:
    def test_slot_counters_reflect_reservation_and_checkin(self, api):
        """PRD §3.5: "A successful check-in stamps `checked_in_at`, records
        the resolved `sock_method`, and moves one unit from `reserved_count`
        to `checked_in_count`."

        Two reservations then one check-in => reserved_count 1,
        checked_in_count 1.

        Design: Corner/entities/slot_counters_reflect_reservation_and_checkin
        """
        ctx = setup_reserved_visit(email="gg@x.com")
        guardian, slot, gh = ctx["guardian"], ctx["slot"], ctx["g_headers"]
        child2 = add_child(guardian, full_name="K2", birth_date="2019-06-15")
        create_reservation(guardian, slot, child2)

        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])
        check_in_visit(ctx["visit"], ctx["fd_headers"])

        fresh = get_slot_fresh(slot["id"], ctx["mgr_headers"])
        assert fresh["reserved_count"] == 1
        assert fresh["checked_in_count"] == 1


class TestSlotPagination:
    def test_session_slots_list_paginates_with_limit(self, api, anonymous_headers):
        """PRD §2.3: "The `limit` parameter caps the number of returned items;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items from the start of the
        result set and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/session_slots_list_paginates_with_limit
        """
        mgr = make_staff("MANAGER", "Mgr One")
        mh = staff_headers(mgr)
        s1 = create_slot(mh, start_at="2026-06-06T14:00:00Z",
                         end_at="2026-06-06T15:30:00Z")
        s2 = create_slot(mh, start_at="2026-06-06T16:00:00Z",
                         end_at="2026-06-06T17:30:00Z")

        page1, meta1 = validate_paginated(api.list_session_slots(
            anonymous_headers, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_session_slots(
            anonymous_headers, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert {page1[0]["id"], page2[0]["id"]} == {s1["id"], s2["id"]}


class TestSlotHalfOpenOverlap:
    def test_overlapping_slot_rejected_but_adjacent_accepted(self, api):
        """PRD §2.9: "A session slot occupies the half-open interval from its
        `start_at` up to but not including its `end_at`; two slots on the same
        `slot_date` may touch — one ending exactly when another begins — but
        may never overlap while both are non-`CLOSED`."
        PRD §3.3: "an overlap is rejected with `ERR_SLOT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/session_slot_half_open_adjacency
        """
        mgr = make_staff("MANAGER", "Mgr One")
        mh = staff_headers(mgr)
        create_slot(mh, start_at="2026-06-06T14:00:00Z",
                    end_at="2026-06-06T15:30:00Z")

        # 15:00 intersects [14:00, 15:30) -> overlap.
        res = api.create_session_slot(
            {"slot_date": "2026-06-06", "start_at": "2026-06-06T15:00:00Z",
             "end_at": "2026-06-06T16:00:00Z", "capacity": 10}, mh)
        validate_error(res, ApiErrorId.ERR_SLOT_OVERLAP, expected_status=409)

        # 15:30 == prior end: half-open adjacency with gap 0 is allowed.
        s3 = validate_success(api.create_session_slot(
            {"slot_date": "2026-06-06", "start_at": "2026-06-06T15:30:00Z",
             "end_at": "2026-06-06T17:00:00Z", "capacity": 10}, mh), 201)
        assert s3["status"] == "SCHEDULED"

    def test_closed_slot_does_not_block_overlapping_creation(self, api):
        """PRD §2.9: "two slots on the same `slot_date` may touch — one ending
        exactly when another begins — but may never overlap while both are
        non-`CLOSED`."

        A CLOSED slot no longer participates in the overlap check, so an
        interval intersecting it is accepted.

        Design: Difficulty/resource_temporal_overlap/session_slot_half_open_adjacency
        """
        reset_clock()
        mgr = make_staff("MANAGER", "Mgr One")
        mh = staff_headers(mgr)
        slot = create_open_slot(mh, start_at="2026-06-06T14:00:00Z",
                                end_at="2026-06-06T15:30:00Z")
        closed = validate_success(api.close_session_slot(
            slot["id"], {"reason": "MANAGER_CLOSE"}, mh), 200)
        assert closed["status"] == "CLOSED"
        assert closed["close_reason"] == "MANAGER_CLOSE"

        s2 = validate_success(api.create_session_slot(
            {"slot_date": "2026-06-06", "start_at": "2026-06-06T15:00:00Z",
             "end_at": "2026-06-06T16:00:00Z", "capacity": 10}, mh), 201)
        assert s2["status"] == "SCHEDULED"


class TestReservationQuotaBoundary:
    def test_reservation_quota_equality_rejected_capacity_4(self, api):
        """PRD §3.4: "Admission is subject to the quota gate: a reservation is
        accepted only while `reserved_count` is strictly below
        `reservation_quota`, otherwise `ERR_RESERVATION_QUOTA_FULL`
        (HTTP 409)."

        Capacity 4 -> quota floor(2.8) = 2; the reservation at exact equality
        (reserved_count == quota) is rejected.

        Design: Difficulty/boundary_precision_check/reservation_quota_equality_rejected
        """
        ctx = setup_reserved_visit(capacity=4, email="gq@x.com")
        guardian, slot, gh = ctx["guardian"], ctx["slot"], ctx["g_headers"]
        assert slot["reservation_quota"] == 2

        c2 = add_child(guardian, full_name="K2", birth_date="2019-06-15")
        create_reservation(guardian, slot, c2)  # reserved_count now 2 == quota

        c3 = add_child(guardian, full_name="K3", birth_date="2018-09-15")
        res = api.create_visit(
            {"session_slot_id": slot["id"], "child_id": c3["id"],
             "guardian_id": guardian["id"], "visit_type": "RESERVATION",
             "booked_duration_minutes": 60}, gh)
        validate_error(res, ApiErrorId.ERR_RESERVATION_QUOTA_FULL,
                       expected_status=409)

    def test_reservation_quota_equality_rejected_capacity_10(self, api):
        """PRD §2.9: "A new reservation is admitted only while the number of
        `RESERVED` visits is strictly below the quota".

        Capacity 10 -> quota 7: seven reservations succeed, the eighth
        (reserved_count == 7 == quota) is rejected.

        Design: Difficulty/boundary_precision_check/reservation_quota_equality_rejected
        """
        ctx = setup_reserved_visit(capacity=10, email="gq2@x.com")
        guardian, slot, gh = ctx["guardian"], ctx["slot"], ctx["g_headers"]
        assert slot["reservation_quota"] == 7

        # ctx already holds reservation #1; add #2..#7.
        for i in range(2, 8):
            child = add_child(guardian, full_name=f"K{i}",
                              birth_date="2019-06-15")
            create_reservation(guardian, slot, child)

        child8 = add_child(guardian, full_name="K8", birth_date="2018-09-15")
        res = api.create_visit(
            {"session_slot_id": slot["id"], "child_id": child8["id"],
             "guardian_id": guardian["id"], "visit_type": "RESERVATION",
             "booked_duration_minutes": 60}, gh)
        validate_error(res, ApiErrorId.ERR_RESERVATION_QUOTA_FULL,
                       expected_status=409)


class TestSlotCapacityPatchOCC:
    def test_slot_patch_with_stale_version_rejected(self, api):
        """PRD §2.7: "Resizing a session slot's `capacity` requires
        `expected_session_slot_version` matching the slot's current `version`.
        A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412): the slot's
        counters may have moved since the client read it, and the
        quota-reduction cascade must never run from a stale view."

        Design: Corner/cross_cutting_layers/slot_patch_with_stale_version_rejected
        """
        mgr = make_staff("MANAGER", "Mgr One")
        mh = staff_headers(mgr)
        slot = create_slot(mh, capacity=10)
        stale_version = slot["version"]

        patched = validate_success(api.patch_session_slot(
            slot["id"], {"capacity": 12,
                         "expected_session_slot_version": stale_version},
            mh), 200)
        assert patched["reservation_quota"] == 8  # floor(12 * 0.7)
        assert patched["version"] == stale_version + 1

        res = api.patch_session_slot(
            slot["id"], {"capacity": 14,
                         "expected_session_slot_version": stale_version}, mh)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
