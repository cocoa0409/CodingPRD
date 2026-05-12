"""StoreOrder lifecycle: drafting, line append, submit, cancel,
modification, cutoff and ordering window enforcement.

PRD §3.2 references throughout. Validates DRAFT → SUBMITTED transition
preconditions, cancellation rules, OrderLine immutability and quantity
range.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    MAX_ORDER_UNITS,
    MIN_ORDER_UNITS,
    advance_clock,
    append_line,
    append_order_line_payload,
    assert_order_line,
    assert_store_order,
    cancel_order,
    create_draft_order,
    create_recipe,
    create_store,
    make_storemanager_headers,
    patch_store_admin,
    patch_store_order_payload,
    setup_store_with_recipe,
    setup_submitted_order,
    submit_order,
    validate_error,
    validate_success,
    api_client,
)


# ===========================================================================
# Draft creation
# ===========================================================================
class TestDraftCreation:
    def test_new_order_starts_draft(self):
        """PRD §3.2: 'the new order is created with status of DRAFT, with
        store_id populated from X-User-ID.'

        Claim: a new StoreOrder has status == DRAFT and store_id == acting Store.id.
        """
        store, _ = setup_store_with_recipe()
        order = create_draft_order(
            store_id=store["id"],
            target_delivery_date="2026-06-01",
        )
        assert_store_order(order)
        assert order["status"] == "DRAFT"
        assert order["store_id"] == store["id"]


# ===========================================================================
# Line append + quantity range
# ===========================================================================
class TestOrderLines:
    @pytest.mark.parametrize("quantity", [MIN_ORDER_UNITS, MAX_ORDER_UNITS])
    def test_quantity_at_inclusive_bounds_accepted(self, quantity):
        """PRD §3.2: 'Quantity must be at least 1 and at most 10,000;
        outside that band, the line is rejected with
        ERR_QUANTITY_OUT_OF_RANGE.'

        Claim: quantity == 1 and quantity == 10000 are accepted (boundary
        precision: PRD specifies '1' and '10,000' as inclusive bounds via
        'at least' and 'at most').
        """
        store, recipe = setup_store_with_recipe()
        order = create_draft_order(
            store_id=store["id"], target_delivery_date="2026-06-01"
        )
        line = append_line(
            order_id=order["id"],
            store_id=store["id"],
            recipe_id=recipe["id"],
            quantity=quantity,
        )
        assert_order_line(line)
        assert line["quantity"] == quantity

    @pytest.mark.parametrize("quantity", [0, MAX_ORDER_UNITS + 1, -1])
    def test_quantity_out_of_range_rejected(self, api, quantity):
        """PRD §3.2: 'Quantity must be at least 1 and at most 10,000;
        outside that band, the line is rejected with
        ERR_QUANTITY_OUT_OF_RANGE.'

        Claim: quantity 0, 10001, and -1 → ERR_QUANTITY_OUT_OF_RANGE.
        """
        store, recipe = setup_store_with_recipe()
        order = create_draft_order(
            store_id=store["id"], target_delivery_date="2026-06-01"
        )
        headers = make_storemanager_headers(store["id"])
        res = api.append_order_line(
            order["id"],
            append_order_line_payload(
                recipe_id=recipe["id"], quantity=quantity
            ),
            headers,
        )
        validate_error(res, "ERR_QUANTITY_OUT_OF_RANGE")

    def test_order_line_is_immutable_id_and_created_at_only(self):
        """PRD §2.4: 'The OrderLine is similarly immutable once recorded
        — it is appended via the order-line action, never updated, and
        likewise carries only id and created_at.'

        Claim: a returned OrderLine has neither updated_at nor version.
        """
        store, recipe = setup_store_with_recipe()
        order = create_draft_order(
            store_id=store["id"], target_delivery_date="2026-06-01"
        )
        line = append_line(
            order_id=order["id"],
            store_id=store["id"],
            recipe_id=recipe["id"],
            quantity=2,
        )
        assert "updated_at" not in line or line.get("updated_at") is None
        assert "version" not in line or line.get("version") is None


# ===========================================================================
# Submission preconditions
# ===========================================================================
class TestSubmit:
    def test_submit_with_no_lines_rejected(self, api):
        """PRD §3.2: 'Five preconditions must hold at submit time: ...
        the order must have at least one line ...'.

        Claim: submit on a DRAFT order with zero lines → ERR_INVALID_STATE
        (the submit precondition is not met). HTTP 409 per §5.
        """
        store, _ = setup_store_with_recipe()
        order = create_draft_order(
            store_id=store["id"], target_delivery_date="2026-06-01"
        )
        headers = make_storemanager_headers(store["id"])
        res = api.submit_store_order(order["id"], headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_submit_outside_window_rejected(self, api, platform_admin_headers):
        """PRD §3.2: 'the current instant must lie inside the store's daily
        ordering window (between order_window_open_minute inclusive and
        order_window_close_minute exclusive, evaluated as UTC
        minute-of-day; otherwise ERR_ORDER_WINDOW_CLOSED)'.

        Claim: when now() is outside the window, submit → ERR_ORDER_WINDOW_CLOSED.
        """
        from test_helpers import (
            advance_clock_relative, current_clock_minute_of_day,
        )
        # Step the clock forward by 1 minute so we land somewhere inside
        # a fresh minute-of-day, then build the store window to EXCLUDE
        # that minute.
        advance_clock_relative(minutes=1)
        cur_min = current_clock_minute_of_day()
        # Window starts 60 minutes after now and lasts 4 hours; current
        # minute lies BEFORE the open boundary → outside the window.
        open_min = (cur_min + 60) % 1440
        close_min = (cur_min + 60 + 240) % 1440
        # Wrap protection: only build a window that doesn't wrap through
        # midnight; if it would wrap, advance the clock to the start of
        # the day so a clean window (e.g., 13:00–17:00) excludes us at
        # 12:xx (1 minute earlier).
        if close_min <= open_min:
            advance_clock_relative(minutes=10)
            cur_min = current_clock_minute_of_day()
            open_min = max(0, min(1380, cur_min + 60))
            close_min = open_min + 60
        recipe = create_recipe()
        store = create_store(
            catalog_permission=[recipe["id"]],
            order_window_open_minute=open_min,
            order_window_close_minute=close_min,
        )
        order = create_draft_order(
            store_id=store["id"], target_delivery_date="2026-06-01"
        )
        append_line(
            order_id=order["id"],
            store_id=store["id"],
            recipe_id=recipe["id"],
            quantity=1,
        )
        headers = make_storemanager_headers(store["id"])
        res = api.submit_store_order(order["id"], headers)
        validate_error(res, "ERR_ORDER_WINDOW_CLOSED")

    def test_submit_with_recipe_outside_catalog_rejected(self, api):
        """PRD §3.2: 'every line's recipe_id must appear in the store's
        catalog_permission (otherwise ERR_CATALOG_PERMISSION_DENIED)'.

        Claim: a SUBMIT where one OrderLine.recipe is not in the store's
        catalog_permission → ERR_CATALOG_PERMISSION_DENIED.
        """
        # Use a maximally-open window so window check would pass.
        advance_clock("2026-05-11T12:00:00.000Z")
        allowed = create_recipe()
        forbidden = create_recipe()
        store = create_store(
            catalog_permission=[allowed["id"]],
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        order = create_draft_order(
            store_id=store["id"], target_delivery_date="2026-06-01"
        )
        # Append the forbidden line directly.
        headers = make_storemanager_headers(store["id"])
        res = api.append_order_line(
            order["id"],
            append_order_line_payload(
                recipe_id=forbidden["id"], quantity=1
            ),
            headers,
        )
        # PRD validations[priority=11] applies_to lines and submit.
        # Either the line-append or the submit must surface the error;
        # we assert at submit time when both are at issue.
        if res.status_code >= 400:
            validate_error(res, "ERR_CATALOG_PERMISSION_DENIED")
            return
        # Otherwise line was accepted; submit should fail.
        res = api.submit_store_order(order["id"], headers)
        validate_error(res, "ERR_CATALOG_PERMISSION_DENIED")

    def test_submit_locks_line_value_and_totals(self):
        """PRD §3.2: 'On success, each OrderLine.line_value_cents is locked
        at quantity multiplied by Recipe.unit_price_cents, the order's
        total_units is recomputed as the sum of all quantity values, and
        total_value_cents is recomputed as the sum of all line_value_cents.'

        Claim: after SUBMIT, total_units == 5 and total_value_cents ==
        5 × unit_price_cents for a single line(quantity=5).
        """
        advance_clock("2026-05-11T12:00:00.000Z")
        recipe = create_recipe(unit_price_cents=750)
        store = create_store(
            catalog_permission=[recipe["id"]],
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        order = setup_submitted_order(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-06-01",
            quantity=5,
        )
        assert order["status"] == "SUBMITTED"
        assert order["total_units"] == 5
        assert order["total_value_cents"] == 5 * 750

    def test_submit_already_submitted_rejected(self, api):
        """PRD §3.2: 'Submitting a StoreOrder that is already past DRAFT
        is rejected with ERR_INVALID_STATE; this is also the rejection
        that surfaces when two double-clicks race and the second loses
        (only the first transition wins).'

        Claim: a second submit on an already-SUBMITTED order →
        ERR_INVALID_STATE (HTTP 409).
        """
        advance_clock("2026-05-11T12:00:00.000Z")
        recipe = create_recipe()
        store = create_store(
            catalog_permission=[recipe["id"]],
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        order = setup_submitted_order(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-06-01",
            quantity=1,
        )
        headers = make_storemanager_headers(store["id"])
        res = api.submit_store_order(order["id"], headers)
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Cancellation & cutoff
# ===========================================================================
class TestCancellation:
    def test_cancel_within_cutoff_rejected(self, api):
        """PRD §3.2: 'Both transitions require that the current instant
        be at least cutoff_minutes_before_close before
        order_window_close_minute; closer to close than that, the request
        is rejected with ERR_ORDER_CUTOFF_PASSED.'

        Claim: cancel within cutoff → ERR_ORDER_CUTOFF_PASSED.
        """
        from test_helpers import (
            advance_clock_relative, current_clock_minute_of_day,
        )
        # Step the clock forward 1 minute, then build a window whose
        # close is 30 minutes ahead with a 60-minute cutoff: now() lies
        # within 30 minutes of close → cutoff is passed.
        advance_clock_relative(minutes=1)
        cur_min = current_clock_minute_of_day()
        open_min = max(0, cur_min - 60)
        close_min = cur_min + 30
        # Avoid wrap-around past midnight.
        if close_min >= 1440:
            advance_clock_relative(hours=24)
            advance_clock_relative(minutes=1)
            cur_min = current_clock_minute_of_day()
            open_min = max(0, cur_min - 60)
            close_min = cur_min + 30
        recipe = create_recipe()
        store = create_store(
            catalog_permission=[recipe["id"]],
            order_window_open_minute=open_min,
            order_window_close_minute=close_min,
            cutoff_minutes_before_close=60,
        )
        order = create_draft_order(
            store_id=store["id"], target_delivery_date="2026-06-01"
        )
        headers = make_storemanager_headers(store["id"])
        res = api.cancel_store_order(order["id"], headers)
        validate_error(res, "ERR_ORDER_CUTOFF_PASSED")

    def test_patch_target_date_within_cutoff_rejected(self, api):
        """PRD §3.2: 'Header-level modification of a DRAFT order — the
        only permitted field at present is target_delivery_date — is also
        subject to the cutoff rule and yields ERR_ORDER_CUTOFF_PASSED if
        attempted within the lockout window.'

        Claim: PATCH within cutoff → ERR_ORDER_CUTOFF_PASSED.
        """
        from test_helpers import (
            advance_clock_relative, current_clock_minute_of_day,
        )
        advance_clock_relative(minutes=1)
        cur_min = current_clock_minute_of_day()
        open_min = max(0, cur_min - 60)
        close_min = cur_min + 30
        if close_min >= 1440:
            advance_clock_relative(hours=24)
            advance_clock_relative(minutes=1)
            cur_min = current_clock_minute_of_day()
            open_min = max(0, cur_min - 60)
            close_min = cur_min + 30
        recipe = create_recipe()
        store = create_store(
            catalog_permission=[recipe["id"]],
            order_window_open_minute=open_min,
            order_window_close_minute=close_min,
            cutoff_minutes_before_close=60,
        )
        order = create_draft_order(
            store_id=store["id"], target_delivery_date="2026-06-01"
        )
        headers = make_storemanager_headers(store["id"])
        res = api.patch_store_order(
            order["id"],
            patch_store_order_payload(target_delivery_date="2026-06-02"),
            headers,
        )
        validate_error(res, "ERR_ORDER_CUTOFF_PASSED")
