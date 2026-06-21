"""Quote lifecycle: drafting/pricing, the cyclic revise loop, per-line rounding
order, expiry, terminal-state lockdown, and the quote-revise OCC guard.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    # fixtures
    create_customer,
    create_part,
    create_quote,
    create_sent_quote,
    add_line,
    set_clock,
)

SM = TEST_USERS["service_manager_headers"]


# ===========================================================================
# Corner / state_machines / initial_state_quote_is_draft
# ===========================================================================
def test_new_quote_is_draft_revision_1(api):
    """PRD §3.3: "A new quote starts at `revision` 1."
    PRD §3.3: "A `ServiceManager` creates a quote in `DRAFT` status for a given
    customer (`customer_id`) with a `quote_type` of either `SERVICE_CALL` or `INSTALL`"

    Design: Corner/state_machines/initial_state_quote_is_draft
    """
    customer = create_customer()
    quote = validate_success(
        api.create_quote({"customer_id": customer["id"], "quote_type": "INSTALL"}, SM), 201
    )
    assert quote["status"] == "DRAFT", f"Expected status DRAFT, got {quote['status']}"
    assert quote["revision"] == 1, f"Expected revision 1, got {quote['revision']}"


# ===========================================================================
# Difficulty / combinatorial_formula / cf_quote_line_round_then_sum_order
# ===========================================================================
def test_estimate_rounds_each_line_before_summing(api):
    """PRD §3.3: "Second, each line's `line_total_cents` is obtained by rounding
    that raw line amount half-up to whole cents — this per-line rounding happens
    first, before any summation."
    PRD §3.3: "Summing the raw line amounts and rounding once at the end is
    incorrect; the rounding must be applied per line first and the rounded line
    totals then summed."

    Design: Difficulty/combinatorial_formula/cf_quote_line_round_then_sum_order
    """
    # Two PART lines, each raw 333*1.35 = 449.55 -> rounds to 450 per line; sum
    # 900. Summing raw first (899.10) then rounding once would give 899.
    customer = create_customer()
    roller = create_part(category="ROLLER", unit_price_cents=333, markup_pct=0.35, on_hand_qty=20)
    quote = create_quote(customer["id"], quote_type="SERVICE_CALL", service_call_fee_cents=0)
    add_line(quote["id"], "PART", item_ref_id=roller["id"], qty=1, unit_price_cents=333)
    add_line(quote["id"], "PART", item_ref_id=roller["id"], qty=1, unit_price_cents=333)
    sent = validate_success(api.send_quote(quote["id"], SM))
    assert sent["estimate_total_cents"] == 900, (
        f"Expected estimate_total_cents 900 (per-line rounding), got {sent['estimate_total_cents']}"
    )


def test_each_part_line_total_rounds_to_450(api):
    """PRD §3.3: "Second, each line's `line_total_cents` is obtained by rounding
    that raw line amount half-up to whole cents — this per-line rounding happens
    first, before any summation."

    Design: Difficulty/combinatorial_formula/cf_quote_line_round_then_sum_order
    """
    # Each PART line raw 333*1.35 = 449.55 rounds half-up to 450 per line.
    customer = create_customer()
    roller = create_part(category="ROLLER", unit_price_cents=333, markup_pct=0.35, on_hand_qty=20)
    quote = create_quote(customer["id"], quote_type="SERVICE_CALL", service_call_fee_cents=0)
    line = add_line(quote["id"], "PART", item_ref_id=roller["id"], qty=1, unit_price_cents=333)
    assert line["line_total_cents"] == 450, (
        f"Expected per-line line_total_cents 450 (round_half_up of 449.55), got {line['line_total_cents']}"
    )


# ===========================================================================
# Difficulty / non_linear_state_machine / nlsm_quote_cyclic_revise_loop
# ===========================================================================
class TestQuoteCyclicReviseLoop:
    def _sent_quote_with_version(self):
        customer = create_customer()
        quote = create_sent_quote(
            customer["id"], [{"item_kind": "LABOR", "qty": 30}],
            quote_type="SERVICE_CALL", service_call_fee_cents=5000,
        )
        return quote

    def test_revise_twice_keeps_sent(self, api):
        """PRD §3.4: "A `SENT` quote may be revised repeatedly before the customer
        decides; revising is a self-loop that keeps the quote in `SENT`."

        Design: Difficulty/non_linear_state_machine/nlsm_quote_cyclic_revise_loop
        """
        quote = self._sent_quote_with_version()
        v1 = quote["version"]
        revised1 = validate_success(api.revise_quote(quote["id"], {"expected_quote_version": v1}, SM))
        v2 = revised1["version"]
        revised2 = validate_success(api.revise_quote(quote["id"], {"expected_quote_version": v2}, SM))
        assert revised2["status"] == "SENT", (
            f"Expected status SENT after two revisions, got {revised2['status']}"
        )

    def test_revise_twice_makes_revision_3(self, api):
        """PRD §3.4: "A successful revise increments `revision` by one, resets
        `expires_at` to the revise instant plus 14 days, recomputes
        `estimate_total_cents` over the current set of quote lines, and advances
        the quote's `version`."

        Design: Difficulty/non_linear_state_machine/nlsm_quote_cyclic_revise_loop
        """
        quote = self._sent_quote_with_version()
        v1 = quote["version"]
        revised1 = validate_success(api.revise_quote(quote["id"], {"expected_quote_version": v1}, SM))
        revised2 = validate_success(
            api.revise_quote(quote["id"], {"expected_quote_version": revised1["version"]}, SM)
        )
        assert revised2["revision"] == 3, (
            f"Expected revision 3 after starting at 1 and revising twice, got {revised2['revision']}"
        )


# ===========================================================================
# Corner / cross_cutting_complexity_layers / occ_quote_revise_stale_quote_version
# ===========================================================================
def test_revise_with_stale_quote_version_rejected(api):
    """PRD §2.6: "If `expected_quote_version` does not equal the quote's current
    `version`, the revision is rejected with `ERR_STALE_VERSION` (HTTP 412), so a
    client carrying a stale quote version cannot overwrite a revision it never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_quote_revise_stale_quote_version
    """
    customer = create_customer()
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    v1 = quote["version"]
    validate_success(api.revise_quote(quote["id"], {"expected_quote_version": v1}, SM))
    # Retry carrying the now-stale v1.
    resp = api.revise_quote(quote["id"], {"expected_quote_version": v1}, SM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


# ===========================================================================
# Corner / state_machines / send_quote_with_no_lines_returns_invalid_state
# ===========================================================================
def test_send_quote_with_no_lines_rejected(api):
    """PRD §3.4: "A quote moves from `DRAFT` to `SENT` when the `ServiceManager`
    sends it, which is permitted only if the quote has at least one quote line."

    Design: Corner/state_machines/send_quote_with_no_lines_returns_invalid_state
    """
    customer = create_customer()
    quote = create_quote(customer["id"], quote_type="SERVICE_CALL", service_call_fee_cents=5000)
    resp = api.send_quote(quote["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Corner / state_machines / decline_already_declined_quote_returns_invalid_state
# ===========================================================================
def test_decline_already_declined_quote_rejected(api):
    """PRD §3.4: "`ACCEPTED` and `DECLINED` are likewise terminal."
    PRD §3.4: "When the `Customer` who owns the quote **declines** it, the quote
    moves from `SENT` to `DECLINED` and no job is created."

    Design: Corner/state_machines/decline_already_declined_quote_returns_invalid_state
    """
    customer = create_customer()
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    cust_h = make_customer_headers(customer["id"])
    get_success_data(api.decline_quote(quote["id"], cust_h))
    resp = api.decline_quote(quote["id"], cust_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Corner / state_machines / accept_expired_quote_returns_quote_expired
# ===========================================================================
def test_accept_expired_quote_returns_quote_expired(api):
    """PRD §3.4: "Once a quote is `EXPIRED`, it is terminal, and any attempt to
    accept, decline, or revise it is rejected with `ERR_QUOTE_EXPIRED`."
    PRD §3.4: "Sending stamps `expires_at` to the instant of sending plus 14 days"

    Design: Corner/state_machines/accept_expired_quote_returns_quote_expired
    """
    set_clock("2026-07-01T12:00:00Z")
    customer = create_customer()
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    # Advance past expires_at (send + 14 days).
    set_clock("2026-07-16T12:00:00Z")
    resp = api.accept_quote(quote["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED.value, 409)
