"""Special orders: dual-variant quote (DISTRIBUTOR vs POD), the QUOTED<->DRAFT
revision cycle and its limit, POD eligibility, receive-creates-stock, and
terminal-state lockdown on cancel."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    create_special_order_payload,
    make_member, make_title,
    setup_special_order, setup_quoted_special_order,
    setup_special_order_revised_n_times, setup_received_special_order,
)

BOOKSELLER = TEST_USERS["bookseller_headers"]


def test_distributor_quote_price_and_eta(api):
    """PRD §3.7: "For a `DISTRIBUTOR` order, `quoted_unit_cents` is the title's
    `list_price_cents` taken at list (multiplied by one), rounded half-up to whole
    cents, and `promised_eta` is the current logical clock plus seven days."
    PRD §3.1: "At startup the clock reads exactly `2026-01-01T00:00:00Z`".

    Design: Difficulty/dual_variant_calc/special_order_quote_distributor_vs_pod_diverge
    """
    member = make_member()
    title = make_title(list_price_cents=2000, pod_eligible=True)
    mh = make_member_headers(member["id"])
    so = validate_success(
        api.create_special_order(
            create_special_order_payload(member["id"], title["id"], 1,
                                         "DISTRIBUTOR"), mh),
        expected_status=201,
    )
    quoted = validate_success(api.quote_special_order(so["id"], BOOKSELLER))
    assert quoted["quoted_unit_cents"] == 2000
    assert quoted["promised_eta"].startswith("2026-01-08"), \
        f"distributor ETA must be clock + 7 days, got {quoted['promised_eta']}"


def test_pod_quote_price_and_eta_diverge_from_distributor(api):
    """PRD §3.7: "For a `POD` order, `quoted_unit_cents` is the title's
    `list_price_cents` multiplied by a print-on-demand markup of one and twenty
    hundredths, rounded half-up to whole cents, and `promised_eta` is the current
    logical clock plus three days."

    Design: Difficulty/dual_variant_calc/special_order_quote_distributor_vs_pod_diverge
    """
    member = make_member()
    title = make_title(list_price_cents=2000, pod_eligible=True)
    mh = make_member_headers(member["id"])
    so = validate_success(
        api.create_special_order(
            create_special_order_payload(member["id"], title["id"], 1, "POD"), mh),
        expected_status=201,
    )
    quoted = validate_success(api.quote_special_order(so["id"], BOOKSELLER))
    # 2000 * 1.20 = 2400; ETA = clock(2026-01-01) + 3 days = 2026-01-04.
    assert quoted["quoted_unit_cents"] == 2400
    assert quoted["promised_eta"].startswith("2026-01-04"), \
        f"POD ETA must be clock + 3 days, got {quoted['promised_eta']}"


def test_revision_cycle_increments_count_and_clears_quote(api):
    """PRD §3.7: "**Revising** a quote is a renegotiation loop performed by the
    owning `Member` or a `StoreAdmin`: it bounces the order from `QUOTED` back to
    `DRAFT`." And: "On a successful revision the system clears `quoted_unit_cents`
    and `promised_eta`, increments `revision_count` by one, and increments
    `version`."

    Design: Difficulty/non_linear_state_machine/special_order_quoted_to_draft_revision_cycle
    """
    member = make_member()
    title = make_title(list_price_cents=2000)
    mh = make_member_headers(member["id"])
    so = validate_success(
        api.create_special_order(
            create_special_order_payload(member["id"], title["id"], 1,
                                         "DISTRIBUTOR"), mh),
        expected_status=201,
    )
    validate_success(api.quote_special_order(so["id"], BOOKSELLER))
    # revise -> quote -> revise: state DRAFT, revision_count 2.
    validate_success(api.revise_special_order(so["id"], mh))
    validate_success(api.quote_special_order(so["id"], BOOKSELLER))
    revised = validate_success(api.revise_special_order(so["id"], mh))
    assert revised["state"] == "DRAFT"
    assert revised["revision_count"] == 2
    assert revised["quoted_unit_cents"] in (None, 0) or "quoted_unit_cents" not in revised, \
        "quoted_unit_cents must be cleared after a revise"


def test_revise_back_to_draft_state(api):
    """PRD §3.7: "it bounces the order from `QUOTED` back to `DRAFT`."

    Design: Difficulty/non_linear_state_machine/special_order_quoted_to_draft_revision_cycle
    """
    ctx = setup_quoted_special_order(list_price_cents=2000,
                                     fulfillment_method="DISTRIBUTOR")
    mh = make_member_headers(ctx["member"]["id"])
    revised = validate_success(
        api.revise_special_order(ctx["special_order"]["id"], mh)
    )
    assert revised["state"] == "DRAFT"
    assert revised["revision_count"] == 1


def test_revision_limit_blocks_fourth_revise(api):
    """PRD §3.7: "A revision is allowed only when the order is `QUOTED` and only
    while its `revision_count` is below three; a revision attempt once the count
    has reached three is rejected with `ERR_REVISION_LIMIT` (HTTP 422)."

    Design: Corner/state_machines/special_order_revision_limit_blocks_fourth_revise
    """
    ctx = setup_special_order_revised_n_times(3, list_price_cents=2000)
    mh = ctx["member_headers"]
    so_id = ctx["special_order"]["id"]
    assert ctx["special_order"]["revision_count"] == 3
    assert ctx["special_order"]["state"] == "QUOTED"
    resp = api.revise_special_order(so_id, mh)
    validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT)


def test_pod_quote_requires_pod_eligible_title(api):
    """PRD §3.7: "when the `fulfillment_method` is `POD`, the title must be
    print-on-demand eligible (its `pod_eligible` is true), failing which the quote
    is rejected with `ERR_TITLE_NOT_POD_ELIGIBLE` (HTTP 422)."

    Design: Corner/calculations/special_order_quote_pod_requires_eligible
    """
    member = make_member()
    title = make_title(list_price_cents=2000, pod_eligible=False)
    mh = make_member_headers(member["id"])
    so = validate_success(
        api.create_special_order(
            create_special_order_payload(member["id"], title["id"], 1, "POD"), mh),
        expected_status=201,
    )
    resp = api.quote_special_order(so["id"], BOOKSELLER)
    validate_error(resp, ApiErrorId.ERR_TITLE_NOT_POD_ELIGIBLE)


def test_receive_creates_available_stock(api):
    """PRD §3.7: "**Receiving** a confirmed order ... creates the order's
    `quantity` of new `StockItem` rows for the title in `AVAILABLE` state with
    `source` `DISTRIBUTOR` and `cost_cents` equal to `quoted_unit_cents`,
    recomputes the title's `on_hand_qty`".

    Design: Corner/state_machines/special_order_receive_creates_available_stock
    """
    ctx = setup_received_special_order(list_price_cents=2000, quantity=2)
    assert ctx["special_order"]["state"] == "RECEIVED"
    title = validate_success(api.get_title(ctx["title"]["id"], BOOKSELLER))
    assert title["on_hand_qty"] == 2


def test_cancel_received_special_order_rejected(api):
    """PRD §3.7: "A special order may instead be **cancelled** from `DRAFT` or
    `QUOTED`, moving it to `CANCELLED`".

    Design: Corner/state_machines/cancel_special_order_from_received_returns_invalid_state
    """
    ctx = setup_received_special_order(list_price_cents=2000, quantity=1)
    mh = ctx["member_headers"]
    resp = api.cancel_special_order(ctx["special_order"]["id"], mh)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
