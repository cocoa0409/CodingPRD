"""Insertion order booking, fiscal guards, and request-validation pipeline."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_insertion_order, assert_line_item,
    create_insertion_order_payload, create_line_item_payload,
    ApiErrorId, TEST_USERS,
    create_io, create_line_item, transition_io, transition_line_item,
    setup_draft_line_item, setup_trafficked_line_item, setup_live_line_item,
    post_snapshot, add_tagged_creative, get_io, get_line_item, get_creative,
)


class TestOrderBooking:
    def test_io_creation_applies_defaults(self, api, ad_ops_headers):
        """PRD §3.1: "`viewability_threshold_pct`, the minimum acceptable
        viewability rate, defaults to 0.70 when omitted, and
        `ivt_threshold_pct`, the maximum tolerable invalid-traffic rate,
        defaults to 0.02. A new order starts in `DRAFT` with
        `booked_budget_cents` and `total_applied_credit_cents` both at zero."

        Design: Corner/entities/io_creation_applies_defaults
        """
        res = api.create_insertion_order(
            create_insertion_order_payload(
                advertiser_name="Acme", total_budget_cents=100000,
                flight_start="2026-08-01", flight_end="2026-08-31",
                billing_basis="LOWER_OF"),
            ad_ops_headers)
        io = validate_success(res, 201)
        assert_insertion_order(io)
        assert io["status"] == "DRAFT"
        assert io["viewability_threshold_pct"] == pytest.approx(0.70)
        assert io["ivt_threshold_pct"] == pytest.approx(0.02)
        assert io["booked_budget_cents"] == 0
        assert io["total_applied_credit_cents"] == 0

    def test_io_create_missing_required_field_returns_invalid_request(
            self, api, ad_ops_headers):
        """PRD §2.8: "Third, request-body schema: required fields present,
        types correct, enum members valid, and cross-field consistency —
        `viewable_impressions` not exceeding `measured_impressions`,
        `ivt_impressions` not exceeding `measured_impressions`, `clicks` not
        exceeding `impressions`, `end_date` on or after `start_date`,
        `flight_end` on or after `flight_start`, `period_end` strictly after
        `period_start`, `measured_impressions` greater than zero, and
        positive amounts wherever an amount is required
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/io_create_missing_required_field_returns_invalid_request
        """
        payload = {
            "advertiser_name": "Acme",
            "flight_start": "2026-08-01",
            "flight_end": "2026-08-31",
            "billing_basis": "LOWER_OF",
        }
        res = api.create_insertion_order(payload, ad_ops_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_io_create_invalid_enum_rejected(self, api, ad_ops_headers):
        """PRD §2.8: "Third, request-body schema: required fields present,
        types correct, enum members valid, and cross-field consistency —
        `viewable_impressions` not exceeding `measured_impressions`,
        `ivt_impressions` not exceeding `measured_impressions`, `clicks` not
        exceeding `impressions`, `end_date` on or after `start_date`,
        `flight_end` on or after `flight_start`, `period_end` strictly after
        `period_start`, `measured_impressions` greater than zero, and
        positive amounts wherever an amount is required
        (`ERR_INVALID_REQUEST`)."
        PRD §3.1: "The order's `billing_basis` — one of `AGENCY_PLATFORM`,
        `THIRD_PARTY_TAG`, or `LOWER_OF` — is fixed at booking"

        Design: Corner/entities/io_create_invalid_enum_rejected
        """
        res = api.create_insertion_order(
            create_insertion_order_payload(billing_basis="BOGUS"),
            ad_ops_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_line_item_get_not_found_returns_404(self, api, trafficker_headers):
        """PRD §2.8: "Fourth, existence: path identifiers are validated left
        to right, and body foreign-key references — `io_id`, `line_item_id`,
        `verification_report_id` — must resolve to existing resources; the
        first missing identifier yields `ERR_NOT_FOUND`."

        Design: Corner/entities/line_item_get_not_found_returns_404
        """
        res = api.get_line_item(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", trafficker_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, 404)

    def test_forbidden_beats_not_found_for_wrong_role(
            self, api, trafficker_headers):
        """PRD §2.8: "Every request is evaluated against a fixed pipeline, and
        a request that would trip several checks is rejected with the error
        belonging to the earliest one."
        PRD §2.8: "Second, authorization: the role must be permitted for the
        endpoint (`ERR_FORBIDDEN`)."

        Design: Corner/validations/forbidden_beats_not_found_for_wrong_role
        """
        res = api.transition_insertion_order(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", {"action": "APPROVE"},
            trafficker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, 403)


class TestLineItemBookingFiscal:
    def test_line_item_budget_computed_at_creation(self, api,
                                                   trafficker_headers):
        """PRD §3.2: "Its `budget_cents` is derived at creation as
        `goal_impressions` multiplied by `cpm_rate_cents`, divided by 1000,
        and rounded half up to a whole cent."
        PRD §3.1: "`booked_budget_cents` is the running sum of `budget_cents`
        across the order's line items that are not `CANCELLED`; it is
        recomputed whenever a line item is created, edited in flight, or
        cancelled."

        Design: Corner/entities/line_item_budget_computed_and_client_budget_input_ignored
        """
        io = create_io(total_budget_cents=100000)
        li = create_line_item(io["id"], goal_impressions=100000,
                              cpm_rate_cents=500)
        assert_line_item(li)
        assert li["budget_cents"] == 50000, (
            f"Expected budget_cents 50000, got {li['budget_cents']}")
        assert li["status"] == "DRAFT"
        assert li["fraud_posture"] == "CLEAR"
        io_after = get_io(io["id"])
        assert io_after["booked_budget_cents"] == 50000

    def test_line_item_dates_outside_io_flight_rejected(
            self, api, trafficker_headers):
        """PRD §3.2: "Both dates must sit inside the parent order's flight,
        and `end_date` must be on or after `start_date`; a violation is
        rejected with `ERR_FLIGHT_WINDOW_VIOLATION`."

        Design: Corner/entities/line_item_dates_outside_io_flight_rejected
        """
        io = create_io(flight_start="2026-08-01", flight_end="2026-08-31")
        res = api.create_line_item(
            create_line_item_payload(
                io["id"], goal_impressions=1000, start_date="2026-07-30",
                end_date="2026-08-31"),
            trafficker_headers)
        validate_error(res, ApiErrorId.ERR_FLIGHT_WINDOW_VIOLATION.value, 422)

    def test_line_item_budget_exceeds_io_budget_rejected(
            self, api, trafficker_headers):
        """PRD §3.2: "Booking is a fiscal act: the order's
        `booked_budget_cents` is recomputed with the new line item included,
        and if that aggregate would exceed the order's `total_budget_cents`,
        creation fails with `ERR_BUDGET_EXCEEDED`."

        Design: Corner/validations/line_item_budget_exceeds_io_budget_rejected
        """
        io = create_io(total_budget_cents=100000)
        create_line_item(io["id"], name="LI1", goal_impressions=100000,
                         cpm_rate_cents=500)
        res = api.create_line_item(
            create_line_item_payload(io["id"], name="LI2",
                                     goal_impressions=200000,
                                     cpm_rate_cents=500),
            trafficker_headers)
        validate_error(res, ApiErrorId.ERR_BUDGET_EXCEEDED.value, 422)
        io_after = get_io(io["id"])
        assert io_after["booked_budget_cents"] == 50000, (
            "booked_budget_cents must be unchanged after a rejected booking")


class TestOrderCancelCascade:
    def test_cancelled_io_terminal_lockdown(self, api, ad_ops_headers):
        """PRD §3.1: "Cancelling is permitted from `DRAFT`, `APPROVED`, or
        `ACTIVE` and fires the depth-2 cascade of §2.9; from `COMPLETED`,
        `CLOSED`, or `CANCELLED` the action fails the state check with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancelled_io_terminal_lockdown
        """
        ctx = setup_draft_line_item(li_overrides={"goal_impressions": 1000})
        transition_io(ctx["io"]["id"], "CANCEL")
        res = api.transition_insertion_order(
            ctx["io"]["id"], {"action": "APPROVE"}, ad_ops_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)
        io_after = get_io(ctx["io"]["id"])
        assert io_after["status"] == "CANCELLED"

    def test_io_cancel_two_hop_cascade_archives_everything(
            self, api, ad_ops_headers):
        """PRD §2.9: "Cancelling an insertion order cancels every one of its
        line items not already `COMPLETED` or `CANCELLED`, and each of those
        line-item cancellations itself cascades: every creative of such a
        line item not already `ARCHIVED` is archived — a cascade two levels
        deep."

        Design: Difficulty/transitive_cascade/io_cancel_two_hop_cascade
        """
        ctx = setup_live_line_item(
            io_overrides={"flight_end": "2026-08-31"},
            li_overrides={"name": "LI1", "goal_impressions": 100000,
                          "cpm_rate_cents": 500})
        io_id = ctx["io"]["id"]
        li1 = ctx["line_item"]
        cr1 = ctx["creative"]
        # Second line item stays DRAFT with a TAGGED creative (never launched).
        li2 = create_line_item(io_id, name="LI2", goal_impressions=50000,
                               cpm_rate_cents=400, pacing_mode="ASAP")
        cr2 = add_tagged_creative(li2["id"], name="CR2")
        transition_io(io_id, "ACTIVATE")

        transition_io(io_id, "CANCEL")

        assert get_io(io_id)["status"] == "CANCELLED"
        assert get_line_item(li1["id"])["status"] == "CANCELLED"
        assert get_line_item(li2["id"])["status"] == "CANCELLED"
        assert get_creative(cr1["id"])["status"] == "ARCHIVED"
        assert get_creative(cr2["id"])["status"] == "ARCHIVED"
        assert get_io(io_id)["booked_budget_cents"] == 0, (
            "All line items cancelled → booked_budget_cents must drop to 0")

    def test_io_cancel_leaves_completed_line_item_untouched(
            self, api, ad_ops_headers):
        """PRD §2.9: "Cancelling an insertion order cancels every one of its
        line items not already `COMPLETED` or `CANCELLED`"
        PRD §3.1: "`booked_budget_cents` is the running sum of `budget_cents`
        across the order's line items that are not `CANCELLED`"

        Design: Difficulty/transitive_cascade/io_cancel_two_hop_cascade
        """
        ctx = setup_live_line_item(
            io_overrides={"flight_end": "2026-08-31"},
            li_overrides={"name": "LI1", "goal_impressions": 100000,
                          "cpm_rate_cents": 500})
        io_id = ctx["io"]["id"]
        li1 = ctx["line_item"]
        cr1 = ctx["creative"]
        li2 = create_line_item(io_id, name="LI2", goal_impressions=1000,
                               cpm_rate_cents=500)
        cr2 = add_tagged_creative(li2["id"], name="CR2")
        transition_line_item(li2["id"], "TRAFFIC")
        transition_line_item(li2["id"], "LAUNCH")
        transition_io(io_id, "ACTIVATE")
        # Auto-complete LI1 by reaching its goal exactly.
        post_snapshot(li1["id"], "2026-08-02", 100000, 500)
        assert get_line_item(li1["id"])["status"] == "COMPLETED"
        assert get_creative(cr1["id"])["status"] == "ARCHIVED"

        transition_io(io_id, "CANCEL")

        assert get_io(io_id)["status"] == "CANCELLED"
        assert get_line_item(li1["id"])["status"] == "COMPLETED", (
            "COMPLETED line item must survive the order-level cancel")
        assert get_line_item(li2["id"])["status"] == "CANCELLED"
        assert get_creative(cr2["id"])["status"] == "ARCHIVED"
        assert get_io(io_id)["booked_budget_cents"] == 50000, (
            "The COMPLETED (non-CANCELLED) line item still counts toward "
            "booked_budget_cents")
