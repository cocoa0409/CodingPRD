"""Business-rule validation tests: cross-entity preconditions on confirm and production,
priority-ordered conflicts, run-completion bounds, reorder-source validity, and the
billing-axis error paths.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_shop_catalog,
    setup_confirmed_order,
    setup_started_run,
    setup_invoiced_order,
    create_draft_order,
    add_line,
    create_proof,
    submit_proof,
    create_press,
    create_production_run_payload,
    get_order,
    api_client,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
ART = TEST_USERS["art_staff_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# cross_entity_state_dependency — confirm requires approved proof
# ═══════════════════════════════════════════════════════════════════════════

def test_confirm_requires_approved_proof(api):
    """PRD §3.4: "The order's `ArtProof` must be `APPROVED`, else
    `ERR_PROOF_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_depends_on_artproof_approved
    """
    cat = setup_shop_catalog(stock_qty=100)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    add_line(order["id"], cat["style"]["id"], cat["method"]["id"], {"L": 30})
    proof = create_proof(order["id"])
    submit_proof(order["id"], proof["id"])  # SUBMITTED, not APPROVED

    res = api.confirm_order(order["id"], SM)
    validate_error(res, "ERR_PROOF_NOT_APPROVED", expected_status=409)
    assert get_order(order["id"])["fulfillment_status"] == "DRAFT"


def test_confirm_succeeds_once_proof_approved(api):
    """PRD §3.4: "When those hold, the server computes the order's **ESTIMATE** `Quote`".
    PRD §3.4: "advances the order's `fulfillment_status` from `DRAFT` to `CONFIRMED`".

    Design: Difficulty/cross_entity_state_dependency/order_confirm_depends_on_artproof_approved
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_confirmed_order(cat, size_run={"L": 30})
    assert parts["order"]["fulfillment_status"] == "CONFIRMED"


# ═══════════════════════════════════════════════════════════════════════════
# cross_entity_state_dependency — production run requires confirmed order
# ═══════════════════════════════════════════════════════════════════════════

def test_production_run_requires_confirmed_order(api):
    """PRD §3.7: "Scheduling is permitted only while the order's `fulfillment_status` is
    `CONFIRMED` or `IN_PRODUCTION`; otherwise the request is rejected with
    `ERR_ORDER_NOT_CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/production_run_depends_on_order_confirmed
    """
    cat = setup_shop_catalog(with_sku=False)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])  # DRAFT, never confirmed
    press_id = create_press(cat["shop"]["id"])["id"]
    res = api.create_production_run(
        order["id"],
        create_production_run_payload(
            "2026-06-02T10:00:00.000Z", "2026-06-02T12:00:00.000Z", press_id=press_id
        ), SM,
    )
    validate_error(res, "ERR_ORDER_NOT_CONFIRMED", expected_status=409)


def test_first_production_run_advances_confirmed_order_to_in_production(api):
    """PRD §3.7: "A new run begins in `SCHEDULED` status; if the order was `CONFIRMED`,
    creating its first run advances `fulfillment_status` from `CONFIRMED` to
    `IN_PRODUCTION`."

    Design: Difficulty/cross_entity_state_dependency/production_run_depends_on_order_confirmed
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_confirmed_order(cat, size_run={"L": 30})
    order_id = parts["order"]["id"]
    press_id = create_press(cat["shop"]["id"])["id"]
    run = validate_success(
        api.create_production_run(
            order_id,
            create_production_run_payload(
                "2026-06-02T10:00:00.000Z", "2026-06-02T12:00:00.000Z", press_id=press_id
            ), SM,
        ), 201
    )
    assert run["status"] == "SCHEDULED"
    assert get_order(order_id)["fulfillment_status"] == "IN_PRODUCTION"


# ═══════════════════════════════════════════════════════════════════════════
# priority_pair_validation_conflict — confirm: proof (P7) vs blanks (P9)
# ═══════════════════════════════════════════════════════════════════════════

def test_confirm_reports_proof_error_before_blank_error(api):
    """PRD §3.4: "The order's `ArtProof` must be `APPROVED`, else
    `ERR_PROOF_NOT_APPROVED`. And for every line, the `BlankSku` ... must have
    `on_hand_qty` of at least the ordered quantity plus its misprint allowance ... else
    `ERR_BLANK_INSUFFICIENT`."
    PRD §3.4: "Several preconditions guard it, each with its own error. The order must
    hold at least one `OrderLine`, else `ERR_ORDER_EMPTY`. The order's `ArtProof` must
    be `APPROVED`, else `ERR_PROOF_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_proof_vs_blank_state_vs_fiscal
    """
    # Line {L:50} needs 53 blanks; stock only 10 (insufficient); proof only SUBMITTED.
    cat = setup_shop_catalog(stock_qty=10)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    add_line(order["id"], cat["style"]["id"], cat["method"]["id"], {"L": 50})
    proof = create_proof(order["id"])
    submit_proof(order["id"], proof["id"])

    res = api.confirm_order(order["id"], SM)
    # ERR_PROOF_NOT_APPROVED is listed before ERR_BLANK_INSUFFICIENT in §3.4's guard order.
    validate_error(res, "ERR_PROOF_NOT_APPROVED", expected_status=409)


def test_confirm_reports_blank_error_when_only_blanks_violated(api):
    """PRD §3.4: "for every line, the `BlankSku` matching that line's style, `color`, and
    size must have `on_hand_qty` of at least the ordered quantity plus its misprint
    allowance ... else `ERR_BLANK_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_proof_vs_blank_state_vs_fiscal
    """
    # Proof APPROVED (proof check passes), but stock 10 < 53 needed -> only blanks fail.
    cat = setup_shop_catalog(stock_qty=10)
    res = setup_order_approved_then_confirm_attempt(api, cat, {"L": 50})
    validate_error(res, "ERR_BLANK_INSUFFICIENT", expected_status=409)


# ═══════════════════════════════════════════════════════════════════════════
# priority_pair_validation_conflict — run create: state (P10) vs temporal (P11)
# ═══════════════════════════════════════════════════════════════════════════

def test_production_run_reports_state_error_before_window_conflict(api):
    """PRD §3.7: "Scheduling is permitted only while the order's `fulfillment_status` is
    `CONFIRMED` or `IN_PRODUCTION`; otherwise the request is rejected with
    `ERR_ORDER_NOT_CONFIRMED`. The window is checked for machine availability per §3.2".
    PRD §2.10: "the target resource must be in a state from which the requested
    transition is allowed, else `ERR_INVALID_STATE`. Beyond these five universal tiers,
    individual workflows layer their own business preconditions".

    Design: Difficulty/priority_pair_validation_conflict/production_run_state_vs_temporal_conflict
    """
    cat = setup_shop_catalog(stock_qty=100)
    press_id = create_press(cat["shop"]["id"])["id"]
    # Order #1 CONFIRMED with a run on the press [10:00,12:00).
    parts1 = setup_confirmed_order(cat, size_run={"L": 30})
    validate_success(
        api.create_production_run(
            parts1["order"]["id"],
            create_production_run_payload(
                "2026-06-02T10:00:00.000Z", "2026-06-02T12:00:00.000Z", press_id=press_id
            ), SM,
        ), 201
    )
    # Order #2 DRAFT, attempts overlapping run [11:00,13:00) on the same press.
    order2 = create_draft_order(
        cat["shop"]["id"], cat["customer"]["id"],
        requested_ship_date="2026-06-22T00:00:00.000Z",
    )
    res = api.create_production_run(
        order2["id"],
        create_production_run_payload(
            "2026-06-02T11:00:00.000Z", "2026-06-02T13:00:00.000Z", press_id=press_id
        ), SM,
    )
    # State precondition is checked before the window conflict.
    validate_error(res, "ERR_ORDER_NOT_CONFIRMED", expected_status=409)


def test_production_run_reports_window_conflict_when_only_temporal_violated(api):
    """PRD §3.7: "The window is checked for machine availability per §3.2, raising
    `ERR_PRESS_WINDOW_CONFLICT` on a press or `ERR_STATION_OVERSUBSCRIBED` on a station
    as appropriate."

    Design: Difficulty/priority_pair_validation_conflict/production_run_state_vs_temporal_conflict
    """
    cat = setup_shop_catalog(stock_qty=100)
    press_id = create_press(cat["shop"]["id"])["id"]
    # Both orders CONFIRMED (state OK) so only the window conflict can fire.
    parts1 = setup_confirmed_order(cat, size_run={"L": 30})
    validate_success(
        api.create_production_run(
            parts1["order"]["id"],
            create_production_run_payload(
                "2026-06-02T10:00:00.000Z", "2026-06-02T12:00:00.000Z", press_id=press_id
            ), SM,
        ), 201
    )
    parts2 = setup_confirmed_order(cat, size_run={"L": 30})
    res = api.create_production_run(
        parts2["order"]["id"],
        create_production_run_payload(
            "2026-06-02T11:00:00.000Z", "2026-06-02T13:00:00.000Z", press_id=press_id
        ), SM,
    )
    validate_error(res, "ERR_PRESS_WINDOW_CONFLICT", expected_status=409)


# ═══════════════════════════════════════════════════════════════════════════
# validations (corner) — single-failure isolations
# ═══════════════════════════════════════════════════════════════════════════

def test_confirm_insufficient_blanks_alone(api):
    """PRD §3.4: "for every line, the `BlankSku` matching that line's style, `color`, and
    size must have `on_hand_qty` of at least the ordered quantity plus its misprint
    allowance ... else `ERR_BLANK_INSUFFICIENT`."

    Design: Corner/validations/confirm_blank_insufficient_alone
    """
    # Approved proof, non-empty order, but stock 10 < 53 needed.
    cat = setup_shop_catalog(stock_qty=10)
    parts = setup_order_approved_then_confirm_attempt(api, cat, {"L": 50})
    validate_error(parts, "ERR_BLANK_INSUFFICIENT", expected_status=409)


def test_confirm_empty_order_rejected(api):
    """PRD §3.4: "The order must hold at least one `OrderLine`, else `ERR_ORDER_EMPTY`."

    Design: Corner/validations/confirm_empty_order_returns_order_empty
    """
    cat = setup_shop_catalog(with_sku=False)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    order_v = order["version"]
    proof = create_proof(order["id"])
    submit_proof(order["id"], proof["id"])
    from test_helpers import approve_proof
    approve_proof(order["id"], proof["id"], cat["customer"]["id"], order_v)
    res = api.confirm_order(order["id"], SM)
    validate_error(res, "ERR_ORDER_EMPTY", expected_status=409)


def test_complete_good_units_exceed_pulled_rejected(api):
    """PRD §3.7: "Completion first validates that `good_units` is at least 0,
    `spoiled_units` is at least 0, and their sum does not exceed `blanks_pulled`; a
    violation raises `ERR_INVALID_GOOD_UNITS`."

    Design: Corner/validations/run_complete_good_units_exceed_pulled
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_started_run(cat, size_run={"L": 50})  # blanks_pulled 53
    res = api.complete_run(
        parts["order"]["id"], parts["run"]["id"], {"good_units": 60, "spoiled_units": 0}, SM
    )
    validate_error(res, "ERR_INVALID_GOOD_UNITS", expected_status=400)


def test_complete_short_run_rejected_and_stays_in_production(api):
    """PRD §3.7: "Completion can only fulfill the order if `good_units` reaches the total
    `ordered_qty` summed across the order's reservations; when `good_units` falls short
    of that total, the run does not change the order's state and the request is rejected
    with `ERR_RUN_SHORT`."

    Design: Corner/validations/run_complete_short_returns_run_short
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_started_run(cat, size_run={"L": 50})  # ordered 50, blanks_pulled 53
    res = api.complete_run(
        parts["order"]["id"], parts["run"]["id"], {"good_units": 40, "spoiled_units": 5}, SM
    )
    validate_error(res, "ERR_RUN_SHORT", expected_status=409)
    assert get_order(parts["order"]["id"])["fulfillment_status"] == "IN_PRODUCTION"


def test_reorder_of_non_fulfilled_order_rejected(api):
    """PRD §3.6: "a supplied `reorder_of_order_id` must reference a `FULFILLED` order
    belonging to the *same* customer, else creation is rejected with
    `ERR_INVALID_REORDER_SOURCE`."

    Design: Corner/validations/invalid_reorder_source_not_fulfilled
    """
    cat = setup_shop_catalog(with_sku=False)
    o1 = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])  # left DRAFT
    res = api.create_order(
        {"shop_id": cat["shop"]["id"], "customer_id": cat["customer"]["id"],
         "requested_ship_date": "2026-06-25T00:00:00.000Z", "reorder_of_order_id": o1["id"]},
        SM,
    )
    validate_error(res, "ERR_INVALID_REORDER_SOURCE", expected_status=409)


# ═══════════════════════════════════════════════════════════════════════════
# errors (corner) — billing-axis error paths
# ═══════════════════════════════════════════════════════════════════════════

def test_pay_unbilled_order_rejected(api):
    """PRD §3.9: "Payment requires the order's `billing_status` to be `INVOICED`
    (`ERR_NOT_INVOICED`)".

    Design: Corner/errors/pay_not_invoiced_returns_not_invoiced
    """
    cat = setup_shop_catalog(with_sku=False)
    from test_helpers import make_customer_headers
    cust_headers = make_customer_headers(cat["customer"]["id"])
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"], actor=cust_headers)
    res = api.pay_order(order["id"], cust_headers)
    validate_error(res, "ERR_NOT_INVOICED", expected_status=409)


def test_double_invoice_rejected(api):
    """PRD §3.9: "invoicing an order whose `billing_status` is not `UNBILLED` is rejected
    with `ERR_ALREADY_INVOICED`."

    Design: Corner/errors/double_invoice_returns_already_invoiced
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_invoiced_order(cat, size_run={"L": 30}, good_units=30, spoiled_units=0)
    res = api.invoice_order(parts["order"]["id"], SM)
    validate_error(res, "ERR_ALREADY_INVOICED", expected_status=409)


# ─── helpers local to this file ──────────────────────────────────────────────

def setup_order_approved_then_confirm_attempt(api, cat, size_run):
    """Build an order with an APPROVED proof, then return the confirm Response
    (not validated) so the caller can assert the specific error."""
    from test_helpers import approve_proof
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    order_v = order["version"]
    add_line(order["id"], cat["style"]["id"], cat["method"]["id"], size_run)
    proof = create_proof(order["id"])
    submit_proof(order["id"], proof["id"])
    approve_proof(order["id"], proof["id"], cat["customer"]["id"], order_v)
    return api.confirm_order(order["id"], SM)
