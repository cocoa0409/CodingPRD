"""StoragePlacement charges, segment capacity boundary, aggregate overlap
semantics, count conservation, and the safety-vs-capacity priority pair
(PRD §2.10, §3.6).
"""
from test_helpers import (
    SHIPPER,
    ApiErrorId,
    assert_segment_storage_invariants,
    assert_storage_placement,
    create_storage_placement_payload,
    get_segment,
    get_storage_placement,
    make_inspection,
    make_installed_device,
    make_storage_placement,
    record_inspection_result,
    release_storage_placement,
    set_clock,
    setup_agreement_with_segment,
    validate_error,
)


class TestPerCarRoundingOrder:
    def test_per_car_charge_uses_pinned_rounding(self, api):
        """PRD §3.6: "The daily rate is the agreement's
        `storage_rate_per_car_month_cents` divided by 30, rounded half-up to
        two decimal places."
        PRD §3.6: "The days charged are the whole days from `placed_date` to
        the effective release date, with a floor of one day — even a same-day
        release bills one day."
        PRD §3.6: "The per-car charge is the daily rate multiplied by the days
        charged, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/storage_per_car_rounding_order_pinned
        """
        ctx = setup_agreement_with_segment(capacity=5)
        placement = make_storage_placement(ctx["segment"]["id"], car_mark="STGX301")
        released = release_storage_placement(placement["id"], "2026-08-04")
        # daily = round_half_up(10012 / 30, 2) = 333.73; 3 days -> 1001.19 -> 1001
        assert released["days_charged"] == 3
        assert released["final_storage_charge_cents"] == 1001

    def test_segment_aggregate_sums_rounded_per_car_charges(self, api):
        """PRD §3.6: "A segment's `accrued_storage_cents` is then the plain
        integer sum of the per-car final charges over that segment's placements
        in `RELEASED` or `FORCE_RELEASED` status"
        PRD §3.6: "The alternative order — summing unrounded amounts and
        rounding once — is not permitted: at a monthly rate of 10012 cents with
        3 days charged and 5 cars, the pinned order yields 5005 cents where
        sum-then-round would yield 5006."

        Design: Difficulty/combinatorial_formula/storage_per_car_rounding_order_pinned
        """
        ctx = setup_agreement_with_segment(capacity=5)
        marks = ["STGX301", "STGX302", "STGX303", "STGX304", "STGX305"]
        for mark in marks:
            placement = make_storage_placement(ctx["segment"]["id"], car_mark=mark)
            release_storage_placement(placement["id"], "2026-08-04")
        segment = get_segment(ctx["segment"]["id"])
        # 5 x round_half_up(333.73 * 3, 0) = 5 x 1001 = 5005 (pinned order).
        assert segment["accrued_storage_cents"] == 5005
        assert segment["stored_car_count"] == 0
        assert_segment_storage_invariants(segment)


class TestCapacityBoundary:
    def test_placements_up_to_capacity_accepted(self, api):
        """PRD §3.6: "Capacity is enforced against live inventory: if the
        number of `STORED` placements on the segment already equals its
        `storage_capacity_cars`, the placement is rejected with
        `ERR_STORAGE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/storage_capacity_exact_boundary
        """
        ctx = setup_agreement_with_segment(capacity=3)
        seg_id = ctx["segment"]["id"]
        for mark in ("STGX701", "STGX702", "STGX703"):
            placement = make_storage_placement(seg_id, car_mark=mark)
            assert placement["status"] == "STORED"
        # The third placement reached exactly capacity (count 2 < 3 at check).
        assert get_segment(seg_id)["stored_car_count"] == 3

    def test_placement_beyond_capacity_rejected(self, api):
        """PRD §3.6: "Capacity is enforced against live inventory: if the
        number of `STORED` placements on the segment already equals its
        `storage_capacity_cars`, the placement is rejected with
        `ERR_STORAGE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/storage_capacity_exact_boundary
        """
        ctx = setup_agreement_with_segment(capacity=3)
        seg_id = ctx["segment"]["id"]
        for mark in ("STGX701", "STGX702", "STGX703"):
            make_storage_placement(seg_id, car_mark=mark)
        # Count now equals capacity (3 >= 3): the fourth is rejected.
        res = api.create_storage_placement(
            create_storage_placement_payload(seg_id, car_mark="STGX704"),
            SHIPPER,
        )
        validate_error(res, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED, 409)
        assert get_segment(seg_id)["stored_car_count"] == 3


class TestAggregateOverlapSemantics:
    def test_overlapping_storage_placements_are_legal(self, api):
        """PRD §3.6: "Cars parked on private track for storage are tracked as
        `StoragePlacement` rows."
        PRD §3.6: "Capacity is enforced against live inventory: if the number
        of `STORED` placements on the segment already equals its
        `storage_capacity_cars`, the placement is rejected with
        `ERR_STORAGE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/storage_aggregate_capacity_overlap
        """
        ctx = setup_agreement_with_segment(capacity=3)
        seg_id = ctx["segment"]["id"]
        # Three mutually time-overlapping placements: overlap itself is not a
        # conflict under the aggregate-capacity rule.
        for mark in ("STGX801", "STGX802", "STGX803"):
            placement = make_storage_placement(
                seg_id, car_mark=mark, placed_date="2026-08-01"
            )
            assert placement["status"] == "STORED"
            assert_storage_placement(placement)

    def test_fourth_concurrent_placement_rejected(self, api):
        """PRD §3.6: "Capacity is enforced against live inventory: if the
        number of `STORED` placements on the segment already equals its
        `storage_capacity_cars`, the placement is rejected with
        `ERR_STORAGE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/storage_aggregate_capacity_overlap
        """
        ctx = setup_agreement_with_segment(capacity=3)
        seg_id = ctx["segment"]["id"]
        for mark in ("STGX801", "STGX802", "STGX803"):
            make_storage_placement(seg_id, car_mark=mark)
        res = api.create_storage_placement(
            create_storage_placement_payload(seg_id, car_mark="STGX804"),
            SHIPPER,
        )
        validate_error(res, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED, 409)


class TestStoredCarCountInvariant:
    def test_place_increments_stored_car_count(self, api):
        """PRD §3.6: "A successful placement starts `STORED`, and the segment's
        `stored_car_count` increments by 1."
        PRD §3.4: "Segments are born `IN_SERVICE` with `stored_car_count` 0,
        `accrued_storage_cents` 0, and `safety_suspended` false."

        Design: Difficulty/compensating_invariant/storage_place_release_count_invariant
        """
        ctx = setup_agreement_with_segment(capacity=3)
        seg_id = ctx["segment"]["id"]
        assert get_segment(seg_id)["stored_car_count"] == 0
        make_storage_placement(seg_id, car_mark="STGX901")
        segment = get_segment(seg_id)
        assert segment["stored_car_count"] == 1
        assert_segment_storage_invariants(segment)

    def test_release_decrements_count_to_prior_value(self, api):
        """PRD §3.6: "Release computes the days and final charge as above,
        moves the placement to `RELEASED`, decrements the segment's
        `stored_car_count` by 1 — restoring the invariant that the count
        equals the number of `STORED` placements — and recomputes the
        segment's `accrued_storage_cents` as the sum described above."

        Design: Difficulty/compensating_invariant/storage_place_release_count_invariant
        """
        ctx = setup_agreement_with_segment(capacity=3)
        seg_id = ctx["segment"]["id"]
        placement = make_storage_placement(seg_id, car_mark="STGX901")
        assert get_segment(seg_id)["stored_car_count"] == 1
        release_storage_placement(placement["id"], "2026-08-10")
        segment = get_segment(seg_id)
        assert segment["stored_car_count"] == 0, (
            "the place/release pair must conserve the count with no drift"
        )
        assert_segment_storage_invariants(segment)


def _setup_full_and_suspended_segment():
    """Segment at capacity 1 with one STORED car, then safety-suspended.

    PRD-consistent construction order: the placement is created while the
    segment is IN_SERVICE and clear (the §3.6 gates pass), and the §3.4 FAIL
    cascade suspends the segment afterwards. The FAIL cascade flips only cited
    devices and safety_suspended; per §3.6 the abandonment cascade of §3.8 is
    the only non-shipper exit from STORED, so the stored car survives the
    suspension and the segment ends up both at capacity and suspended.
    """
    ctx = setup_agreement_with_segment(capacity=1)
    placement = make_storage_placement(ctx["segment"]["id"], car_mark="STGX601")
    device = make_installed_device(ctx["segment"]["id"])
    inspection = make_inspection(ctx["agreement"]["id"], ctx["segment"]["id"])
    record_inspection_result(
        inspection["id"], "FAIL", "2026-08-01", cited_device_ids=[device["id"]]
    )
    return {
        "agreement": ctx["agreement"],
        "segment": ctx["segment"],
        "device": device,
        "inspection": inspection,
        "placement": placement,
    }


class TestSafetyBeatsCapacity:
    def test_safety_suspension_error_precedes_capacity_error(self, api):
        """PRD §2.10: "When several validation rules could reject the same
        request, the order in which they fire is part of the contract — the
        first matching failure determines the error returned."
        PRD §2.10: "eighth, segment safety gates, with the in-service
        requirement checked before the suspension requirement
        (`ERR_SEGMENT_OUT_OF_SERVICE`, then `ERR_SEGMENT_SAFETY_SUSPENDED`)"
        PRD §2.10: "tenth, uniqueness, overlap, and frequency rules
        (`ERR_CAR_ALREADY_SPOTTED`, `ERR_POSSESSION_OVERLAP`,
        `ERR_POSSESSION_BUFFER_CONFLICT`, `ERR_SWITCH_LIMIT_EXCEEDED`,
        `ERR_STORAGE_CAPACITY_EXCEEDED`)"

        Design: Difficulty/priority_pair_validation_conflict/storage_safety_error_beats_capacity_error
        """
        # capacity 1 filled by one placement AND safety-suspended: both the
        # suspension gate (eighth) and the capacity rule (tenth) could fire.
        ctx = _setup_full_and_suspended_segment()
        res = api.create_storage_placement(
            create_storage_placement_payload(
                ctx["segment"]["id"], car_mark="STGX602", placed_date="2026-08-02"
            ),
            SHIPPER,
        )
        validate_error(res, ApiErrorId.ERR_SEGMENT_SAFETY_SUSPENDED, 409)
        assert get_segment(ctx["segment"]["id"])["stored_car_count"] == 1

    def test_capacity_error_surfaces_once_suspension_cleared(self, api):
        """PRD §3.4: "A `PASS` restores compliance: every cited device currently
        `NON_COMPLIANT` returns to `INSTALLED`, and if no device on that
        segment remains `NON_COMPLIANT`, the segment's `safety_suspended`
        clears to false."
        PRD §3.6: "Capacity is enforced against live inventory: if the number
        of `STORED` placements on the segment already equals its
        `storage_capacity_cars`, the placement is rejected with
        `ERR_STORAGE_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/storage_safety_error_beats_capacity_error
        """
        ctx = _setup_full_and_suspended_segment()
        # Restore compliance: a PASS inspection citing the same device.
        followup = make_inspection(
            ctx["agreement"]["id"], ctx["segment"]["id"], scheduled_date="2026-08-04"
        )
        record_inspection_result(
            followup["id"], "PASS", "2026-08-04",
            cited_device_ids=[ctx["device"]["id"]],
        )
        assert get_segment(ctx["segment"]["id"])["safety_suspended"] is False
        # With the higher-priority gate clear, the capacity rule now fires.
        res = api.create_storage_placement(
            create_storage_placement_payload(
                ctx["segment"]["id"], car_mark="STGX602", placed_date="2026-08-04"
            ),
            SHIPPER,
        )
        validate_error(res, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED, 409)


class TestProvisionalAccrual:
    def test_provisional_accrual_tracks_logical_clock(self, api):
        """PRD §3.6: "While a placement is `STORED`, reads recompute its
        `accrued_storage_charge_cents` provisionally as of the current logical
        date; `days_charged` and `final_storage_charge_cents` stay unset until
        release."
        PRD §3.6: "The daily rate is the agreement's
        `storage_rate_per_car_month_cents` divided by 30, rounded half-up to
        two decimal places."

        Design: Corner/cross_cutting_layers/storage_provisional_accrual_on_read
        """
        ctx = setup_agreement_with_segment()
        placement = make_storage_placement(
            ctx["segment"]["id"], car_mark="STGX9801", placed_date="2026-08-01"
        )
        set_clock("2026-08-04T00:00:00Z")
        read = get_storage_placement(placement["id"])
        # 3 days at daily 333.73 -> round_half_up(1001.19, 0) = 1001.
        assert read["accrued_storage_charge_cents"] == 1001
        released = release_storage_placement(placement["id"], "2026-08-04")
        assert released["final_storage_charge_cents"] == 1001
