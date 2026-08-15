"""Route booking: sequencing, OCC, venue overlap, refurbishment gap (PRD §2.7, §3.2)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_and_open_booking,
    create_venue,
    current_tour_version,
    create_stop_payload,
)

TM = TEST_USERS["tour_manager_headers"]


class TestRouteSequence:
    def test_seq_assigned_by_install_start_not_creation_order(self, api):
        """PRD §3.2: "The `seq` assignment is purely chronological: the new stop's
        position is one plus the number of existing stops of the same tour — of
        any status whatsoever, live or cancelled — that sort strictly earlier,
        where "earlier" means an earlier `install_start`, or an identical
        `install_start` paired with an earlier `created_at`."

        Design: Corner/calculations/route_sequence_assigned_by_install_start_then_created_at
        """
        tour, _ = create_and_open_booking()
        va = create_venue(name="VA")
        vb = create_venue(name="VB")
        vc = create_venue(name="VC")

        # Book December first, then September, then October.
        s_dec = validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(
                    vc["id"],
                    current_tour_version(tour["id"]),
                    install_start="2026-12-01T00:00:00Z",
                    open_date="2026-12-03T00:00:00Z",
                    close_date="2026-12-20T00:00:00Z",
                    teardown_end="2026-12-23T00:00:00Z",
                ),
                TM,
            ),
            201,
        )
        s_sep = validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(
                    va["id"],
                    current_tour_version(tour["id"]),
                    install_start="2026-09-01T00:00:00Z",
                    open_date="2026-09-03T00:00:00Z",
                    close_date="2026-09-20T00:00:00Z",
                    teardown_end="2026-09-23T00:00:00Z",
                ),
                TM,
            ),
            201,
        )
        s_oct = validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(
                    vb["id"],
                    current_tour_version(tour["id"]),
                    install_start="2026-10-01T00:00:00Z",
                    open_date="2026-10-03T00:00:00Z",
                    close_date="2026-10-20T00:00:00Z",
                    teardown_end="2026-10-23T00:00:00Z",
                ),
                TM,
            ),
            201,
        )

        # Re-read after all bookings: each stop's seq is its position in the
        # chronological route order, which out-of-order bookings renumber.
        final = {
            s["id"]: s["seq"]
            for s in validate_success(api.list_stops(tour["id"], TM), 200)
        }
        assert final[s_sep["id"]] == 1, (
            f"September stop should be seq 1, got {final[s_sep['id']]}"
        )
        assert final[s_oct["id"]] == 2, (
            f"October stop should be seq 2, got {final[s_oct['id']]}"
        )
        assert final[s_dec["id"]] == 3, (
            f"December stop should be seq 3, got {final[s_dec['id']]}"
        )

    def test_seq_visible_on_list_read(self, api):
        """PRD §3.2: "The `seq` assignment is purely chronological: the new stop's
        position is one plus the number of existing stops of the same tour — of
        any status whatsoever, live or cancelled — that sort strictly earlier,
        where "earlier" means an earlier `install_start`, or an identical
        `install_start` paired with an earlier `created_at`."

        Design: Corner/calculations/route_sequence_assigned_by_install_start_then_created_at
        """
        tour, _ = create_and_open_booking()
        va = create_venue(name="VA")
        vb = create_venue(name="VB")
        # Book October then September: the later-created September stop gets seq 1.
        s_oct = validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(
                    vb["id"],
                    current_tour_version(tour["id"]),
                    install_start="2026-10-01T00:00:00Z",
                    open_date="2026-10-03T00:00:00Z",
                    close_date="2026-10-20T00:00:00Z",
                    teardown_end="2026-10-23T00:00:00Z",
                ),
                TM,
            ),
            201,
        )
        s_sep = validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(
                    va["id"],
                    current_tour_version(tour["id"]),
                    install_start="2026-09-01T00:00:00Z",
                    open_date="2026-09-03T00:00:00Z",
                    close_date="2026-09-20T00:00:00Z",
                    teardown_end="2026-09-23T00:00:00Z",
                ),
                TM,
            ),
            201,
        )
        # The final route positions are visible on a fresh list read.
        final = {
            s["id"]: s["seq"]
            for s in validate_success(api.list_stops(tour["id"], TM), 200)
        }
        assert final[s_oct["id"]] == 2
        assert final[s_sep["id"]] == 1


class TestOccVersionIncrement:
    def test_successful_booking_increments_tour_version_by_one(self, api):
        """PRD §2.7: "A successful booking itself increments the tour's `version`
        by one, meaning each appended stop invalidates the snapshot the next
        writer may be holding."

        Design: Corner/cross_cutting_layers/occ_correct_version_succeeds_then_version_increments
        """
        tour, _ = create_and_open_booking()
        venue = create_venue()
        tv_pre = current_tour_version(tour["id"])
        res = api.create_stop(tour["id"], create_stop_payload(venue["id"], tv_pre), TM)
        stop = validate_success(res, 201)
        assert stop["status"] == "TENTATIVE"
        tv_post = current_tour_version(tour["id"])
        assert tv_post == tv_pre + 1, (
            f"Expected tour.version {tv_pre + 1} after booking, got {tv_post}"
        )

    def test_second_booking_with_fresh_version_succeeds(self, api):
        """PRD §2.7: "A successful booking itself increments the tour's `version`
        by one, meaning each appended stop invalidates the snapshot the next
        writer may be holding."

        Design: Corner/cross_cutting_layers/occ_correct_version_succeeds_then_version_increments
        """
        tour, _ = create_and_open_booking()
        v1 = create_venue(name="V1")
        v2 = create_venue(name="V2")
        s1 = validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(v1["id"], current_tour_version(tour["id"])),
                TM,
            ),
            201,
        )
        s2 = validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(
                    v2["id"],
                    current_tour_version(tour["id"]),
                    install_start="2026-11-01T00:00:00Z",
                    open_date="2026-11-03T00:00:00Z",
                    close_date="2026-12-03T00:00:00Z",
                    teardown_end="2026-12-06T00:00:00Z",
                ),
                TM,
            ),
            201,
        )
        assert s1["seq"] == 1 and s2["seq"] == 2


class TestVenueHalfOpenWindow:
    def test_adjacent_booking_at_teardown_end_allowed(self, api):
        """PRD §3.2: "overlap is measured on the half-open interval that includes
        `install_start` and excludes `teardown_end`, so a stop whose install
        begins exactly when another's teardown ends does not conflict."

        Design: Difficulty/resource_temporal_overlap/venue_half_open_window_overlap_rejected
        """
        tour, _ = create_and_open_booking(refurbishment_gap_days=0)
        venue = create_venue(name="Crystal Hall")
        validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(
                    venue["id"],
                    current_tour_version(tour["id"]),
                    install_start="2026-09-01T00:00:00Z",
                    open_date="2026-09-05T00:00:00Z",
                    close_date="2026-10-01T00:00:00Z",
                    teardown_end="2026-10-07T00:00:00Z",
                ),
                TM,
            ),
            201,
        )
        # install_start == prior teardown_end: adjacent, half-open => allowed.
        res = api.create_stop(
            tour["id"],
            create_stop_payload(
                venue["id"],
                current_tour_version(tour["id"]),
                install_start="2026-10-07T00:00:00Z",
                open_date="2026-10-10T00:00:00Z",
                close_date="2026-11-10T00:00:00Z",
                teardown_end="2026-11-15T00:00:00Z",
            ),
            TM,
        )
        stop2 = validate_success(res, 201)
        assert stop2["seq"] == 2

    def test_overlapping_booking_one_day_earlier_rejected(self, api):
        """PRD §3.2: "Second, venue double-booking: if any other stop at the same
        venue — considering only stops in `TENTATIVE`, `CONTRACTED`,
        `INSTALLING`, `OPEN`, or `TEARDOWN` — holds a window overlapping the new
        one, the booking fails with `ERR_VENUE_DOUBLE_BOOKED`; overlap is
        measured on the half-open interval that includes `install_start` and
        excludes `teardown_end`."

        Design: Difficulty/resource_temporal_overlap/venue_half_open_window_overlap_rejected
        """
        tour, _ = create_and_open_booking(refurbishment_gap_days=0)
        venue = create_venue(name="Crystal Hall")
        validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(
                    venue["id"],
                    current_tour_version(tour["id"]),
                    install_start="2026-09-01T00:00:00Z",
                    open_date="2026-09-05T00:00:00Z",
                    close_date="2026-10-01T00:00:00Z",
                    teardown_end="2026-10-07T00:00:00Z",
                ),
                TM,
            ),
            201,
        )
        # Starts one day before the first stop's teardown_end: overlaps.
        res = api.create_stop(
            tour["id"],
            create_stop_payload(
                venue["id"],
                current_tour_version(tour["id"]),
                install_start="2026-10-06T00:00:00Z",
                open_date="2026-10-10T00:00:00Z",
                close_date="2026-11-10T00:00:00Z",
                teardown_end="2026-11-20T00:00:00Z",
            ),
            TM,
        )
        validate_error(res, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED)


class TestRefurbishmentGap:
    def test_gap_exactly_at_requirement_accepted(self, api):
        """PRD §3.2: "Third, the refurbishment gap: consecutive stops of the same
        tour must leave at least `refurbishment_gap_days` between the previous
        stop's `teardown_end` and the next stop's `install_start`, or the
        booking fails with `ERR_REFURBISHMENT_GAP_VIOLATED`."

        Design: Difficulty/resource_temporal_overlap/consecutive_stop_refurbishment_gap_enforced
        """
        tour, _ = create_and_open_booking(refurbishment_gap_days=5)
        v1 = create_venue(name="V1")
        v2 = create_venue(name="V2")
        validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(
                    v1["id"],
                    current_tour_version(tour["id"]),
                    install_start="2026-09-01T00:00:00Z",
                    open_date="2026-09-05T00:00:00Z",
                    close_date="2026-10-01T00:00:00Z",
                    teardown_end="2026-10-07T00:00:00Z",
                ),
                TM,
            ),
            201,
        )
        # Gap of exactly 5 days (2026-10-07 -> 2026-10-12): "at least" => accepted.
        res = api.create_stop(
            tour["id"],
            create_stop_payload(
                v2["id"],
                current_tour_version(tour["id"]),
                install_start="2026-10-12T00:00:00Z",
                open_date="2026-10-15T00:00:00Z",
                close_date="2026-11-15T00:00:00Z",
                teardown_end="2026-11-20T00:00:00Z",
            ),
            TM,
        )
        stop2 = validate_success(res, 201)
        assert stop2["seq"] == 2

    def test_gap_below_requirement_rejected(self, api):
        """PRD §3.2: "Third, the refurbishment gap: consecutive stops of the same
        tour must leave at least `refurbishment_gap_days` between the previous
        stop's `teardown_end` and the next stop's `install_start`, or the
        booking fails with `ERR_REFURBISHMENT_GAP_VIOLATED`."

        Design: Difficulty/resource_temporal_overlap/consecutive_stop_refurbishment_gap_enforced
        """
        tour, _ = create_and_open_booking(refurbishment_gap_days=5)
        v1 = create_venue(name="V1")
        v2 = create_venue(name="V2")
        validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(
                    v1["id"],
                    current_tour_version(tour["id"]),
                    install_start="2026-09-01T00:00:00Z",
                    open_date="2026-09-05T00:00:00Z",
                    close_date="2026-10-01T00:00:00Z",
                    teardown_end="2026-10-07T00:00:00Z",
                ),
                TM,
            ),
            201,
        )
        # Gap of only 2 days (2026-10-07 -> 2026-10-09): rejected.
        res = api.create_stop(
            tour["id"],
            create_stop_payload(
                v2["id"],
                current_tour_version(tour["id"]),
                install_start="2026-10-09T00:00:00Z",
                open_date="2026-10-15T00:00:00Z",
                close_date="2026-11-15T00:00:00Z",
                teardown_end="2026-11-20T00:00:00Z",
            ),
            TM,
        )
        validate_error(res, ApiErrorId.ERR_REFURBISHMENT_GAP_VIOLATED)


class TestStaleVersionBeatsBusinessRule:
    def test_stale_version_preempts_venue_double_booking(self, api):
        """PRD §3.2: "First comes the stale-version check: a mismatched
        `expected_tour_version` fails with `ERR_STALE_VERSION` before any
        business rule is consulted."
        PRD §2.7: "If that value does not match the tour's current `version` —
        because another booking or mutation has advanced the tour since the
        client read it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_stop_booking
        """
        tour, _ = create_and_open_booking(refurbishment_gap_days=0)
        venue = create_venue(name="Castle Hall")
        tv = current_tour_version(tour["id"])
        validate_success(
            api.create_stop(
                tour["id"],
                create_stop_payload(
                    venue["id"],
                    tv,
                    install_start="2026-09-01T00:00:00Z",
                    open_date="2026-09-05T00:00:00Z",
                    close_date="2026-10-01T00:00:00Z",
                    teardown_end="2026-10-07T00:00:00Z",
                ),
                TM,
            ),
            201,
        )
        # tv is now stale (booking bumped version); the new window also overlaps.
        res = api.create_stop(
            tour["id"],
            create_stop_payload(
                venue["id"],
                tv,
                install_start="2026-09-15T00:00:00Z",
                open_date="2026-09-20T00:00:00Z",
                close_date="2026-10-20T00:00:00Z",
                teardown_end="2026-10-25T00:00:00Z",
            ),
            TM,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_version_rejected_even_without_other_violations(self, api):
        """PRD §2.7: "If that value does not match the tour's current `version` —
        because another booking or mutation has advanced the tour since the
        client read it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), so route-sequencing decisions are never taken against a
        superseded route snapshot."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_stop_booking
        """
        tour, _ = create_and_open_booking()
        v1 = create_venue(name="V1")
        v2 = create_venue(name="V2")
        tv = current_tour_version(tour["id"])
        validate_success(
            api.create_stop(tour["id"], create_stop_payload(v1["id"], tv), TM),
            201,
        )
        # Reuse the same (now stale) version against a fresh, valid window.
        res = api.create_stop(
            tour["id"],
            create_stop_payload(
                v2["id"],
                tv,
                install_start="2026-11-01T00:00:00Z",
                open_date="2026-11-03T00:00:00Z",
                close_date="2026-12-03T00:00:00Z",
                teardown_end="2026-12-06T00:00:00Z",
            ),
            TM,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
