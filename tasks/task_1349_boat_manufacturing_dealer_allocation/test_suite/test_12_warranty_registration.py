"""Warranty registration: the 45-day sale window, 36-month coverage, one
registration per hull, selling-dealer match, and the allocation recount
(PRD §3.8, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_warranty_registration,
    book_order_no_options,
    cancel_order,
    certify_hull,
    confirm_order,
    create_dealer,
    create_hull,
    create_model,
    create_run,
    create_slot,
    create_warranty_registration_payload,
    deliver_hull,
    get_dealer,
    get_order,
    make_dealer_principal_headers,
    set_clock,
    setup_bookable_world,
    setup_delivered_hull,
    setup_registered_hull,
    validate_error,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


class TestCoverageEnd:
    def test_coverage_end_date_36_months_computed(self, api):
        """PRD §3.8: "Registration stamps `registered_at` from the clock,
        computes `coverage_end_date` as the sale date plus 36 months, and sets
        a permanent `ACTIVE` status — lapse is enforced purely temporally
        through the coverage end, never through a status change."

        Sale on 2026-08-02 -> coverage through 2029-08-02.

        Design: Corner/calculations/coverage_end_date_36_months_computed
        """
        world = setup_registered_hull(api, sale_date="2026-08-02")
        reg = world["registration"]
        assert_warranty_registration(reg)
        assert reg["coverage_end_date"] == "2029-08-02", (
            f"sale date + 36 months: got {reg['coverage_end_date']}"
        )
        assert reg["status"] == "ACTIVE"


class TestRegistrationWindow:
    def test_sale_46_days_old_rejected_45_days_allowed(self, api):
        """PRD §3.8: "The sale date must not be in the future and must not be
        more than 45 days before the clock date — a sale exactly 45 days old
        still qualifies; anything older or later-dated is rejected with
        `ERR_REGISTRATION_WINDOW_EXPIRED`."

        At clock 2026-08-15 a 2026-06-30 sale is 46 days old and rejects; at
        clock 2026-09-16 the 2026-08-02 sale is exactly 45 days old and is
        accepted.

        Design: Corner/validations/registration_window_45_days_boundary
        """
        # 46 days before the clock -> rejected.
        world = setup_delivered_hull(api, with_options=False)
        set_clock(api, "2026-08-15T00:00:00Z")
        resp = api.create_warranty_registration(
            create_warranty_registration_payload(
                world["hull"]["id"], world["dealer"]["id"], "2026-06-30"
            ),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_WINDOW_EXPIRED)

        # Exactly 45 days before the clock -> still qualifies.
        world2 = setup_delivered_hull(api, with_options=False)
        set_clock(api, "2026-09-16T00:00:00Z")
        reg = validate_success(
            api.create_warranty_registration(
                create_warranty_registration_payload(
                    world2["hull"]["id"], world2["dealer"]["id"], "2026-08-02"
                ),
                make_dealer_principal_headers(world2["dealer"]["id"]),
            ),
            201,
        )
        assert_warranty_registration(reg)

    def test_future_sale_rejected(self, api):
        """PRD §3.8: "The sale date must not be in the future and must not be
        more than 45 days before the clock date — a sale exactly 45 days old
        still qualifies; anything older or later-dated is rejected with
        `ERR_REGISTRATION_WINDOW_EXPIRED`."

        Design: Corner/validations/registration_window_future_sale_rejected
        """
        world = setup_delivered_hull(api, with_options=False)
        set_clock(api, "2026-08-15T00:00:00Z")
        resp = api.create_warranty_registration(
            create_warranty_registration_payload(
                world["hull"]["id"], world["dealer"]["id"], "2026-08-16"
            ),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_WINDOW_EXPIRED)


class TestRegistrationConstraints:
    def test_duplicate_registration_rejected(self, api):
        """PRD §3.8: "A hull accepts exactly one registration, a second attempt
        failing with `ERR_DUPLICATE_REGISTRATION`."

        Design: Corner/validations/duplicate_registration_rejected
        """
        world = setup_registered_hull(api, sale_date="2026-08-02")
        resp = api.create_warranty_registration(
            create_warranty_registration_payload(
                world["hull"]["id"], world["dealer"]["id"], "2026-08-02"
            ),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION)

    def test_selling_dealer_mismatch_rejected(self, api):
        """PRD §3.8: "The `dealer_id` must equal the caller's `X-User-ID` and
        must match the dealer on the delivered order — a different dealer is
        refused with `ERR_SELLING_DEALER_MISMATCH`."

        Design: Corner/validations/selling_dealer_mismatch_rejected
        """
        world = setup_delivered_hull(api, with_options=False)
        other = create_dealer(api, dealer_code="D-B")
        resp = api.create_warranty_registration(
            create_warranty_registration_payload(
                world["hull"]["id"], other["id"], "2026-08-02"
            ),
            make_dealer_principal_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SELLING_DEALER_MISMATCH)


class TestAllocationRecount:
    def test_allocation_used_decreases_after_retail(self, api):
        """PRD §3.8: "Registration also closes the commercial pipeline: the
        order transitions `DELIVERED` → `RETAILED` with a version increment,
        and because `RETAILED` exits the pipeline while `DELIVERED` still
        counted, the dealer's `allocation_used` is recounted down by one with
        a dealer version increment."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_allocation_used_after_retail
        """
        world = setup_delivered_hull(api, with_options=False)
        assert get_dealer(api, world["dealer"]["id"])["allocation_used"] == 1, (
            "DELIVERED still counts toward the pipeline"
        )
        resp = api.create_warranty_registration(
            create_warranty_registration_payload(
                world["hull"]["id"], world["dealer"]["id"], "2026-08-02"
            ),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_success(resp, 201)
        assert get_dealer(api, world["dealer"]["id"])["allocation_used"] == 0, (
            "RETAILED exits the pipeline"
        )
        assert get_order(api, world["order"]["id"])["status"] == "RETAILED"

    def test_allocation_count_excludes_waitlisted_retailed_cancelled(self, api):
        """PRD §3.4: "When no slot fits, the order lands in `WAITLISTED` with
        `slot_id` null — the quota gate does not apply to waitlisted entries,
        which by definition hold no committed production."
        PRD §3.8: "because `RETAILED` exits the pipeline while `DELIVERED`
        still counted, the dealer's `allocation_used` is recounted down by one"
        PRD §3.5: "the dealer's `allocation_used` is recounted down by one
        with the dealer's `version` incremented" (on cancellation).

        The counter is traced across the lifecycle: WAITLISTED contributes 0,
        ALLOCATED and DELIVERED contribute 1, RETAILED and CANCELLED return to
        0.

        Design: Corner/calculations/allocation_usage_count_excludes_waitlisted_retailed_cancelled
        """
        dealer = create_dealer(api, annual_allocation_quota=5)
        m_big = create_model(api, model_code="XL300", production_hours=250,
                             base_price_cents=1000000)
        # A 250-hour order can never fit the 200-hour slots below: it waits.
        o_wait = book_order_no_options(api, dealer, m_big, deposit_paid_cents=103000)
        assert o_wait["status"] == "WAITLISTED"
        assert get_dealer(api, dealer["id"])["allocation_used"] == 0, (
            "WAITLISTED holds no committed production"
        )
        # Open capacity and book an ALLOCATED order on it.
        model = create_model(api, model_code="SP190")
        run = create_run(api)
        slot = create_slot(api, run["id"], slot_code="S1", capacity_hours=200)
        o2 = book_order_no_options(api, dealer, model, slot_id=slot["id"])
        assert o2["status"] == "ALLOCATED"
        assert get_dealer(api, dealer["id"])["allocation_used"] == 1
        # Drive it to DELIVERED: still in the pipeline.
        o2 = confirm_order(api, o2, dealer)
        hull = create_hull(api, o2["id"])
        certify_hull(api, hull["id"])
        set_clock(api, "2026-08-02T00:00:00Z")
        deliver_hull(api, hull["id"])
        assert get_dealer(api, dealer["id"])["allocation_used"] == 1, (
            "DELIVERED still counts"
        )
        # Retail it: the pipeline exits.
        resp = api.create_warranty_registration(
            create_warranty_registration_payload(hull["id"], dealer["id"], "2026-08-02"),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_success(resp, 201)
        assert get_dealer(api, dealer["id"])["allocation_used"] == 0, (
            "RETAILED is excluded"
        )
        # Book and cancel a third order: CANCELLED is excluded too. The big
        # waitlisted order cannot be promoted (250h > 200h free).
        o3 = book_order_no_options(api, dealer, model, slot_id=slot["id"])
        assert o3["status"] == "ALLOCATED"
        assert get_dealer(api, dealer["id"])["allocation_used"] == 1
        cancel_order(api, o3, dealer)
        assert get_dealer(api, dealer["id"])["allocation_used"] == 0, (
            "CANCELLED is excluded"
        )
        assert get_order(api, o_wait["id"])["status"] == "WAITLISTED", (
            "the oversized waiter cannot fit the freed slot and is not promoted"
        )
