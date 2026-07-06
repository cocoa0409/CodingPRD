"""Special-order revision cycle and OCC on customer-approve."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, get_success_data,
    set_clock, register_customer, TEST_USERS, make_customer_headers,
)


# -----------------------------------------------------------------------------
# Difficulty Rule 3 (instance 2): SpecialOrder cyclic QUOTED ↔ RE_QUOTED
# -----------------------------------------------------------------------------

class TestSpecialOrderRevisionCycle:

    def test_quote_then_requote_advances_revision_count_once(self, api):
        """PRD §3.8: "the manager can re-quote through the special-order-re-quote
        action from a QUOTED origin: the special order moves to RE_QUOTED,
        SpecialOrder.quoted_price_cents is overwritten with the new value,
        SpecialOrder.revision_count is incremented by one, and version bumps."

        Design: Difficulty/non_linear_state_machine/special_order_cyclic_quoted_re_quoted
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="fay1@example.com", delivery_zone="ZONE_A")
        so = get_success_data(api.create_special_order(
            {"customer_id": customer["id"], "service_type": "PROCUREMENT", "sku_description": "rare pothos"},
            make_customer_headers(customer["id"]),
        ))
        q = get_success_data(api.quote_special_order(
            so["id"], {"quoted_price_cents": 12000}, TEST_USERS["manager_headers"]
        ))
        assert q["status"] == "QUOTED"
        assert q["revision_count"] == 0
        rq = get_success_data(api.requote_special_order(
            so["id"], {"quoted_price_cents": 15000}, TEST_USERS["manager_headers"]
        ))
        assert rq["status"] == "RE_QUOTED"
        assert rq["revision_count"] == 1

    def test_full_cycle_ends_in_quoted_with_revision_count_one(self, api):
        """PRD §3.8: "A RE_QUOTED special order returns to QUOTED when the manager
        issues a fresh quote through the special-order-quote action; this
        back-and-forth is a strict cycle — a single re-quote turnaround (out
        through the re-quote and back through the quote) increments
        revision_count exactly once."

        Design: Difficulty/non_linear_state_machine/special_order_cyclic_quoted_re_quoted
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="fay2@example.com", delivery_zone="ZONE_A")
        so = get_success_data(api.create_special_order(
            {"customer_id": customer["id"], "service_type": "PROCUREMENT", "sku_description": "rare cactus"},
            make_customer_headers(customer["id"]),
        ))
        get_success_data(api.quote_special_order(
            so["id"], {"quoted_price_cents": 12000}, TEST_USERS["manager_headers"]
        ))
        get_success_data(api.requote_special_order(
            so["id"], {"quoted_price_cents": 15000}, TEST_USERS["manager_headers"]
        ))
        # Return leg: RE_QUOTED → QUOTED via /quote.
        end = get_success_data(api.quote_special_order(
            so["id"], {"quoted_price_cents": 13000}, TEST_USERS["manager_headers"]
        ))
        assert end["status"] == "QUOTED"
        assert end["revision_count"] == 1
        assert end["quoted_price_cents"] == 13000


# -----------------------------------------------------------------------------
# Difficulty Rule 5 (instance 1): SpecialOrder re-quote from REQUESTED → state error
# -----------------------------------------------------------------------------

class TestSpecialOrderStateVsFiscalPriority:

    def test_requote_from_requested_returns_state_error(self, api):
        """PRD §3.8: "the manager can re-quote through the special-order-re-quote
        action from a QUOTED origin".
        PRD §2.8: "State preconditions. The target resource must be in a valid
        FROM state for the requested transition per the state machines described
        in §3. A precondition failure yields ERR_INVALID_STATE, applicable to
        every mutating action endpoint."
        PRD §3.8: "The same error identifier is used when quote, re-quote, or
        customer-approve is attempted from an invalid FROM state."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_special_order_re_quote_from_re_quoted
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="kim@example.com", delivery_zone="ZONE_A")
        so = get_success_data(api.create_special_order(
            {"customer_id": customer["id"], "service_type": "PROCUREMENT", "sku_description": "test"},
            make_customer_headers(customer["id"]),
        ))
        # Re-quote from REQUESTED state — invalid FROM state.
        # PRD names two identifiers for this shape: ERR_INVALID_STATE (§2.8) and
        # ERR_SPECIAL_ORDER_INVALID_STATE (§3.8). Accept either as PRD-faithful.
        r = api.requote_special_order(
            so["id"], {"quoted_price_cents": 10000}, TEST_USERS["manager_headers"]
        )
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            r,
            [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_SPECIAL_ORDER_INVALID_STATE.value],
        )


# -----------------------------------------------------------------------------
# Corner: errors — SpecialOrder OCC stale-version on customer-approve
# -----------------------------------------------------------------------------

class TestSpecialOrderCustomerApproveOCC:

    def test_customer_approve_with_stale_version_returns_stale_version(self, api):
        """PRD §2.7: "Special-order customer approval. The customer-approve action
        (driven by POST /special-orders/{id}/customer-approve) requires the
        client to send a non-optional expected_special_order_version matching
        the target SpecialOrder's current version. If a manager has issued a
        re-quote in the interval between the customer reading the quoted price
        and submitting approval, the special order's version will have advanced
        and the approval is rejected with ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/errors/err_stale_version_on_special_order_customer_approve
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c16@x.com", delivery_zone="ZONE_A")
        so = get_success_data(api.create_special_order(
            {"customer_id": customer["id"], "service_type": "PROCUREMENT", "sku_description": "rare cactus"},
            make_customer_headers(customer["id"]),
        ))
        quoted = get_success_data(api.quote_special_order(
            so["id"], {"quoted_price_cents": 10000}, TEST_USERS["manager_headers"]
        ))
        v_at_quoted = quoted["version"]
        # Manager re-quotes → version bumps → customer's captured version is stale.
        get_success_data(api.requote_special_order(
            so["id"], {"quoted_price_cents": 12000}, TEST_USERS["manager_headers"]
        ))
        r = api.customer_approve_special_order(
            so["id"], {"expected_special_order_version": v_at_quoted},
            make_customer_headers(customer["id"]),
        )
        validate_error(r, ApiErrorId.ERR_STALE_VERSION.value)
