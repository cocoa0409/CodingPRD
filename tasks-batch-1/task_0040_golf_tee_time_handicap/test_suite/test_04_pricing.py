"""Green-fee pricing: peak/off-peak tier selection at window boundaries, member
discount rounding order, and immediate consistency of the booking response."""
import pytest
from test_helpers import (
    validate_success, create_booking_payload, make_golfer_headers,
    create_course, create_golfer, create_tee_time, book_as_golfer, set_clock,
)


class TestPeakWindowBoundaries:
    def test_peak_start_hour_inclusive(self, api):
        """PRD §2.8: "A tee time whose local hour is at least the peak start hour and
        strictly less than the peak end hour is priced at the PEAK tier; any other hour is
        OFF_PEAK."

        Design: Corner/calculations/peak_start_hour_inclusive_boundary
        """
        set_clock()
        course = create_course(name="StartEdge", peak_fee_cents=8000, offpeak_fee_cents=5000,
                               peak_start_hour=7, peak_end_hour=15)
        golfer = create_golfer(full_name="Pub7", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-28T07:00:00Z", 7, "FOURSOME")
        bk = book_as_golfer(tt["id"], golfer["id"], tt["version"])
        assert bk["pricing_tier"] == "PEAK"
        assert bk["green_fee_cents"] == 8000

    def test_peak_end_hour_exclusive(self, api):
        """PRD §2.8: "the peak_end_hour is the local hour, exclusive, at which peak pricing
        ends and defaults to 15. A tee time whose local hour is at least the peak start hour
        and strictly less than the peak end hour is priced at the PEAK tier; any other hour
        is OFF_PEAK."

        Design: Difficulty/boundary_precision_check/peak_window_end_hour_exclusive_boundary
        """
        set_clock()
        course = create_course(name="EdgeCourse", peak_fee_cents=8000, offpeak_fee_cents=5000,
                               peak_start_hour=7, peak_end_hour=15)
        golfer = create_golfer(full_name="Edge Golfer", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-09T15:00:00Z", 15, "FOURSOME")
        bk = book_as_golfer(tt["id"], golfer["id"], tt["version"])
        assert bk["pricing_tier"] == "OFF_PEAK"
        assert bk["green_fee_cents"] == 5000


class TestMemberDiscountRoundingOrder:
    def test_offpeak_member_discount_rounds_then_subtracts(self, api):
        """PRD §2.8: "If the holding golfer's membership_tier is MEMBER, multiply the base by
        the course's member_discount_pct, round that discount amount half-up to whole cents,
        and then subtract the rounded discount from the base; the order is pinned — round the
        discount first, subtract second."

        Design: Difficulty/dual_variant_calc/green_fee_member_discount_rounding_order_divergence
        """
        set_clock()
        course = create_course(name="RoundEdge", course_rating=71.0, slope_rating=120,
                               peak_fee_cents=9000, offpeak_fee_cents=5005,
                               peak_start_hour=7, peak_end_hour=15, member_discount_pct=0.10)
        member = create_golfer(full_name="Member One", membership_tier="MEMBER")
        tt = create_tee_time(course["id"], "2026-06-02T18:00:00Z", 18, "FOURSOME")
        bk = book_as_golfer(tt["id"], member["id"], tt["version"])
        # round(5005*0.10)=501; 5005-501 = 4504 (NOT 4505).
        assert bk["pricing_tier"] == "OFF_PEAK"
        assert bk["green_fee_cents"] == 4504
        assert bk["status"] == "CONFIRMED"

    def test_offpeak_member_discount_round_then_subtract_pinned(self, api):
        """PRD §2.8: "Computing the fee as the base times one-minus-the-percentage and
        rounding the product is not equivalent and is not permitted, because it can differ by
        a cent."

        Design: Difficulty/combinatorial_formula/green_fee_rounding_order_pinned_round_then_subtract
        """
        set_clock()
        course = create_course(name="RoundEdge2", course_rating=71.0, slope_rating=120,
                               peak_fee_cents=9000, offpeak_fee_cents=5005, member_discount_pct=0.10)
        member = create_golfer(full_name="Member Two", membership_tier="MEMBER")
        tt = create_tee_time(course["id"], "2026-06-03T20:00:00Z", 20, "TWOSOME")
        bk = book_as_golfer(tt["id"], member["id"], tt["version"])
        assert bk["green_fee_cents"] == 4504
        assert bk["pricing_tier"] == "OFF_PEAK"


class TestFullFare:
    def test_public_golfer_pays_full_peak_fare(self, api):
        """PRD §2.8: "If the golfer's membership_tier is PUBLIC, there is no discount and the
        fee equals the base."

        Design: Corner/calculations/public_golfer_pays_full_peak_fare
        """
        set_clock()
        course = create_course(name="PubCrs", peak_fee_cents=8000, offpeak_fee_cents=5000,
                               peak_start_hour=7, peak_end_hour=15)
        golfer = create_golfer(full_name="Pub", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-27T10:00:00Z", 10, "FOURSOME")
        bk = book_as_golfer(tt["id"], golfer["id"], tt["version"])
        assert bk["pricing_tier"] == "PEAK"
        assert bk["green_fee_cents"] == 8000


class TestImmediateConsistency:
    def test_booking_response_carries_computed_fields(self, api):
        """PRD §2.8: "If the holding golfer's membership_tier is MEMBER, multiply the base by
        the course's member_discount_pct, round that discount amount half-up to whole cents,
        and then subtract the rounded discount from the base."
        PRD §3.6: "the booking is created CONFIRMED: the system freezes its pricing_tier from
        the slot's local_hour against the course's peak window, computes its green_fee_cents
        per §2.8."

        Design: Corner/consistency_model/booking_create_reflects_all_changes_in_same_response
        """
        set_clock()
        course = create_course(name="ImmCrs", peak_fee_cents=8000, offpeak_fee_cents=5000,
                               peak_start_hour=7, peak_end_hour=15, member_discount_pct=0.20)
        member = create_golfer(full_name="Mem", membership_tier="MEMBER")
        tt = create_tee_time(course["id"], "2026-07-08T09:00:00Z", 9, "FOURSOME")
        resp = api.create_booking(
            tt["id"], create_booking_payload(member["id"], tt["version"]),
            make_golfer_headers(member["id"]),
        )
        bk = validate_success(resp, 201)
        # round(8000*0.20)=1600; 8000-1600 = 6400.
        assert bk["pricing_tier"] == "PEAK"
        assert bk["green_fee_cents"] == 6400
