"""Working-member hours threshold, promotion-window overlap (half-open adjacency),
and shift rest-buffer spacing."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_approved_vendor, create_product,
    create_member_payload, create_working_shift_payload, create_promotion_payload,
    TEST_USERS,
)

INVENTORY = TEST_USERS["inventory_manager_headers"]
COOP = TEST_USERS["coop_admin_headers"]


class TestWorkingHoursThreshold:
    """is_working_member flips at exactly 12 hours (>=) (PRD §3.4)."""

    def _member_with_shift(self, api, start_at, end_at):
        member = get_success_data(api.create_member(
            create_member_payload(full_name="Ivy H", email="ivy@x.com"), COOP))
        shift = get_success_data(api.create_working_shift(
            create_working_shift_payload(member["id"], start_at=start_at, end_at=end_at), COOP))
        api.complete_working_shift(shift["id"], INVENTORY)
        return validate_success(api.get_member(member["id"], COOP), 200)

    def test_exactly_twelve_hours_qualifies(self, api):
        """PRD §3.4: "A member is a working member exactly when their
        `working_hours_balance` is at least the qualifying threshold of 12 hours; a
        member sitting exactly at the threshold qualifies."

        Design: Difficulty/boundary_precision_check/bpc_working_hours_at_threshold_via_shift_complete
        """
        member = self._member_with_shift(api, "2026-07-02T08:00:00Z", "2026-07-02T20:00:00Z")
        assert member["working_hours_balance"] == 12
        assert member["is_working_member"] is True

    def test_eleven_hours_does_not_qualify(self, api):
        """PRD §3.4: "A member is a working member exactly when their
        `working_hours_balance` is at least the qualifying threshold of 12 hours".
        An 11-hour balance is below the threshold and does not qualify.

        Design: Difficulty/boundary_precision_check/bpc_working_hours_at_threshold_via_shift_complete
        """
        member = self._member_with_shift(api, "2026-07-02T08:00:00Z", "2026-07-02T19:00:00Z")
        assert member["working_hours_balance"] == 11
        assert member["is_working_member"] is False


class TestPromotionWindowOverlap:
    """Half-open windows: true overlap rejected, abutting allowed (PRD §2.6, §3.4)."""

    def _product_with_promo(self, api, start_date, end_date):
        vendor = get_success_data(api.create_vendor({"name": "V"}, INVENTORY))
        product = create_product(vendor["id"], sku="JAM", name="Berry Jam",
                                 base_price_cents=650, reorder_point=0, reorder_qty=10)
        get_success_data(api.create_promotion(
            create_promotion_payload(product["id"], deal_type="AD", promo_price_cents=500,
                                     start_date=start_date, end_date=end_date), INVENTORY))
        return product

    def test_overlapping_window_rejected(self, api):
        """PRD §3.4: "A new promotion may not overlap an existing promotion on the same
        product; because windows are half-open (active from `start_date` inclusive to
        `end_date` exclusive), two windows that merely abut at an instant do not overlap,
        but any true overlap is rejected with `ERR_PROMO_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rto_promotion_window_overlap_on_product
        """
        product = self._product_with_promo(api, "2026-07-05T00:00:00Z", "2026-07-12T00:00:00Z")
        res = api.create_promotion(
            create_promotion_payload(product["id"], deal_type="AD", promo_price_cents=450,
                                     start_date="2026-07-10T00:00:00Z",
                                     end_date="2026-07-15T00:00:00Z"), INVENTORY)
        validate_error(res, "ERR_PROMO_WINDOW_OVERLAP", expected_status=409)

    def test_abutting_window_allowed(self, api):
        """PRD §3.4: "two windows that merely abut at an instant do not overlap". A
        window starting exactly where the prior ends is accepted.

        Design: Difficulty/resource_temporal_overlap/rto_promotion_window_overlap_on_product
        """
        product = self._product_with_promo(api, "2026-07-05T00:00:00Z", "2026-07-12T00:00:00Z")
        res = api.create_promotion(
            create_promotion_payload(product["id"], deal_type="AD", promo_price_cents=450,
                                     start_date="2026-07-12T00:00:00Z",
                                     end_date="2026-07-15T00:00:00Z"), INVENTORY)
        validate_success(res, 201)


class TestShiftRestBuffer:
    """A member's shifts must respect a 60-minute rest buffer (PRD §3.4)."""

    def _member_with_shift(self, api, start_at="2026-07-05T08:00:00Z",
                           end_at="2026-07-05T12:00:00Z"):
        member = get_success_data(api.create_member(
            create_member_payload(full_name="Bo K", email="bo@x.com"), COOP))
        get_success_data(api.create_working_shift(
            create_working_shift_payload(member["id"], department="CAFE_DELI",
                                         start_at=start_at, end_at=end_at), COOP))
        return member

    def test_shift_within_rest_buffer_rejected(self, api):
        """PRD §3.4: "if the gap to any other shift is smaller than the mandated rest
        buffer of 60 minutes, the request is rejected with `ERR_SHIFT_OVERLAP`".
        A shift starting 30 minutes after the first ends is too close.

        Design: Difficulty/resource_temporal_overlap/rto_shift_rest_buffer_on_member
        """
        member = self._member_with_shift(api)
        res = api.create_working_shift(
            create_working_shift_payload(member["id"], department="CAFE_DELI",
                                         start_at="2026-07-05T12:30:00Z",
                                         end_at="2026-07-05T14:00:00Z"), COOP)
        validate_error(res, "ERR_SHIFT_OVERLAP", expected_status=409)

    def test_shift_exactly_sixty_minutes_apart_accepted(self, api):
        """PRD §3.4: "shifts exactly 60 minutes apart are acceptable". A second shift
        starting exactly 60 minutes after the first ends is allowed.

        Design: Difficulty/resource_temporal_overlap/rto_shift_rest_buffer_on_member
        """
        member = self._member_with_shift(api)
        res = api.create_working_shift(
            create_working_shift_payload(member["id"], department="CAFE_DELI",
                                         start_at="2026-07-05T13:00:00Z",
                                         end_at="2026-07-05T14:00:00Z"), COOP)
        validate_success(res, 201)
