"""Conditional, temporal and aggregate validation rules of the pro desk API."""

import pytest

from test_helpers import (
    CREDIT_MANAGER,
    FABRICATED_ID,
    PRO_DESK_ASSOCIATE,
    SKU_MORTAR_BAG,
    SKU_SHINGLE_BUNDLE,
    STORE_OPERATIONS,
    ApiErrorId,
    api_client,
    counter_offer_line_price,
    create_delivery_appointment_payload,
    create_delivery_truck,
    create_draft_order,
    create_draft_quote,
    create_pro_account,
    create_store,
    create_store_stock,
    create_will_call_staging_payload,
    get_success_data,
    make_contractor_admin_headers,
    read_pro_order,
    request_return,
    reserve_order,
    set_clock,
    setup_fulfilled_will_call_order,
    setup_reserved_order,
    submit_order,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
)


def _stocked_store(**overrides):
    store = create_store(**overrides)
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    return store


# --------------------------------------------------------------------------- #
# Account-conditional order coding                                             #
# --------------------------------------------------------------------------- #


def test_order_coding_requirements_follow_the_accounts_own_switches():
    """PRD §3.2: "Two coding switches are pinned at this moment: `po_required`, which when true forces every order submission for this account to carry a non-empty `po_number`, and `job_name_required`, which when true forces every order submission to carry a non-empty `job_name`."
    PRD §2.11: "When a single request could fail several checks, the server must report the failure that comes first in the following ladder."
    PRD §2.11: "31. **Purchase order coding** — `po_number` is present and non-empty when the account's `po_required` is true, otherwise `ERR_PO_NUMBER_REQUIRED`. Applies to submitting an order."
    PRD §2.11: "32. **Job-name coding** — `job_name` is present and non-empty when the account's `job_name_required` is true, otherwise `ERR_JOB_NAME_REQUIRED`. Applies to submitting an order."
    PRD §3.6: "When `tax_exempt_applied` is true, `tax_cents` is 0; otherwise `tax_cents` is the tax base multiplied by the fulfillment store's `tax_rate_pct`, rounded half up to a whole cent in a single rounding on the summed base, never per line."
    PRD §3.6: "Finally, `total_cents` is the sum of `subtotal_cents`, `freight_surcharge_cents`, `lift_gate_fee_cents` and `tax_cents`."

    Design: Corner/validations/po_and_job_name_requirements_apply_only_when_the_account_demands_them
    """
    store = _stocked_store(tax_rate_pct=0.0825)
    strict = create_pro_account(
        store["id"],
        business_name="Strict Coding GC",
        po_required=True,
        job_name_required=True,
    )
    relaxed = create_pro_account(
        store["id"],
        business_name="Relaxed Handyman",
        po_required=False,
        job_name_required=False,
    )
    strict_headers = make_contractor_admin_headers(strict["id"])
    relaxed_headers = make_contractor_admin_headers(relaxed["id"])

    bare_order, _ = create_draft_order(
        strict["id"], store["id"], lines=[(SKU_SHINGLE_BUNDLE, 10)]
    )
    po_only_order, _ = create_draft_order(
        strict["id"], store["id"], lines=[(SKU_SHINGLE_BUNDLE, 10)], po_number="PO-1"
    )
    full_order, _ = create_draft_order(
        strict["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        po_number="PO-1",
        job_name="KITCHEN-REMODEL",
    )
    relaxed_order, _ = create_draft_order(
        relaxed["id"], store["id"], lines=[(SKU_SHINGLE_BUNDLE, 10)]
    )

    validate_error(
        api_client.submit_pro_order(bare_order["id"], strict_headers),
        ApiErrorId.ERR_PO_NUMBER_REQUIRED.value,
        expected_status=422,
    )
    assert (
        read_pro_order(bare_order["id"], strict["id"])["fulfillment_status"] == "DRAFT"
    )

    validate_error(
        api_client.submit_pro_order(po_only_order["id"], strict_headers),
        ApiErrorId.ERR_JOB_NAME_REQUIRED.value,
        expected_status=422,
    )
    assert (
        read_pro_order(po_only_order["id"], strict["id"])["fulfillment_status"]
        == "DRAFT"
    )

    submitted_full = validate_success(
        api_client.submit_pro_order(full_order["id"], strict_headers),
        expected_status=200,
    )
    assert submitted_full["fulfillment_status"] == "SUBMITTED"
    assert submitted_full["po_number"] == "PO-1"
    assert submitted_full["job_name"] == "KITCHEN-REMODEL"
    assert submitted_full["total_cents"] == 21639

    submitted_relaxed = validate_success(
        api_client.submit_pro_order(relaxed_order["id"], relaxed_headers),
        expected_status=200,
    )
    assert submitted_relaxed["fulfillment_status"] == "SUBMITTED"
    assert submitted_relaxed["po_number"] is None
    assert submitted_relaxed["job_name"] is None


# --------------------------------------------------------------------------- #
# Return guards                                                                #
# --------------------------------------------------------------------------- #


def test_return_window_admits_day_ninety_and_closes_on_day_ninety_one():
    """PRD §3.9: "Approval first checks the return window: the whole number of days elapsed since the order's `fulfilled_at`, computed by taking the floor of the elapsed time in whole days, must be no greater than 90, otherwise `ERR_RETURN_WINDOW_CLOSED`."
    PRD §2.11: "45. **Return window open** — the whole days elapsed since the order's `fulfilled_at` are no more than 90, otherwise `ERR_RETURN_WINDOW_CLOSED`. Applies to approving a return request."
    PRD §3.9: "The age policy charges nothing when the elapsed whole days since `fulfilled_at` are within 30, and 10 percent beyond that."
    PRD §3.9: "`restocking_fee_cents` is then that percentage applied to `gross_refund_cents` and rounded half up to a whole cent — **one single rounding, on the summed gross, never per line**, which is the deliberate opposite of the per-unit rounding used when order lines were priced."
    PRD §3.9: "`tax_refund_cents` is 0 when the original order's `tax_exempt_applied` was true, and otherwise that net goods figure multiplied by the fulfillment store's `tax_rate_pct`, rounded half up to a whole cent — note that the refunded tax is computed on the goods net of the restocking fee, not on the gross."
    PRD §3.9: "Finally, `refund_total_cents` is the net goods figure plus `tax_refund_cents`."
    PRD §3.9: "The request opens at `status` `REQUESTED` with `valuation_mode`, every refund figure, `approved_by_user_id`, `denied_reason_code` and `credited_at` all null."

    Design: Corner/validations/return_window_closes_after_ninety_whole_days
    """
    store = _stocked_store(tax_rate_pct=0.0825, will_call_bay_slots=2)
    account = create_pro_account(store["id"], business_name="Late Return Roofing")

    on_time_bundle = setup_fulfilled_will_call_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 1)],
        stage_start="2026-08-01T09:00:00Z",
        stage_hours=24,
        payment_method="CARD",
    )
    on_time_request = request_return(
        on_time_bundle["order"]["id"],
        account["id"],
        [(on_time_bundle["order_lines"][0]["id"], 1)],
        reason_code="DAMAGED",
    )

    late_bundle = setup_fulfilled_will_call_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 1)],
        stage_start="2026-08-01T09:00:00Z",
        stage_hours=24,
        payment_method="CARD",
    )
    late_request = request_return(
        late_bundle["order"]["id"],
        account["id"],
        [(late_bundle["order_lines"][0]["id"], 1)],
        reason_code="DAMAGED",
    )

    assert on_time_bundle["order"]["total_cents"] == 2164
    assert late_request["gross_refund_cents"] is None

    # Exactly 90 whole days after fulfilment.
    set_clock("2026-10-30T00:00:00Z")
    approved = validate_success(
        api_client.approve_return_request(on_time_request["id"], PRO_DESK_ASSOCIATE),
        expected_status=200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["valuation_mode"] == "CURRENT_LIST"
    assert approved["gross_refund_cents"] == 1999
    assert approved["restocking_fee_pct"] == pytest.approx(0.10)
    assert approved["restocking_fee_cents"] == 200
    assert approved["tax_refund_cents"] == 148
    assert approved["refund_total_cents"] == 1947

    # One day later the same approval is 91 whole days out.
    set_clock("2026-10-31T00:00:00Z")
    validate_error(
        api_client.approve_return_request(late_request["id"], PRO_DESK_ASSOCIATE),
        ApiErrorId.ERR_RETURN_WINDOW_CLOSED.value,
        expected_status=422,
    )
    still_open = get_success_data(
        api_client.get_return_request(
            late_request["id"], make_contractor_admin_headers(account["id"])
        )
    )
    assert still_open["status"] == "REQUESTED"
    assert still_open["gross_refund_cents"] is None


def test_return_quantity_is_capped_by_units_not_yet_returned():
    """PRD §3.9: "and each requested `qty_units` must be no greater than that line's `fulfilled_units` less its `returned_units`, otherwise `ERR_RETURN_QTY_EXCEEDS_FULFILLED`, which is what stops the same units from being returned twice."
    PRD §2.11: "46. **Return quantity available** — each requested return quantity is no greater than that order line's `fulfilled_units` less its `returned_units`, otherwise `ERR_RETURN_QTY_EXCEEDS_FULFILLED`. Applies to creating a return request."
    PRD §3.9: "The credit stamps `credited_at` with the current clock, adds each returned `qty_units` to its order line's `returned_units`, increments the request's `version`, and then fires the deepest cascade in the system, all four hops of which must be applied."
    PRD §3.9: "Hop one recomputes the order's `credited_refund_cents`, `credited_gross_refund_cents` and `net_volume_cents`."
    PRD §3.9: "The age policy charges nothing when the elapsed whole days since `fulfilled_at` are within 30, and 10 percent beyond that."
    PRD §3.2: "`trailing_volume_cents` is then the account's `baseline_volume_cents` plus the sum of `net_volume_cents` across the account's in-window orders, where an order's `net_volume_cents` is its `subtotal_cents` less its `credited_gross_refund_cents` — returns net out at their gross refund value, before any restocking fee."

    Design: Corner/validations/cumulative_return_quantity_cannot_exceed_fulfilled_units
    """
    store = _stocked_store(tax_rate_pct=0.0825)
    account = create_pro_account(store["id"], business_name="Partial Return Painting")
    headers = make_contractor_admin_headers(account["id"])

    bundle = setup_fulfilled_will_call_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        stage_start="2026-08-01T09:00:00Z",
        stage_hours=24,
        payment_method="CARD",
    )
    order = bundle["order"]
    order_line = bundle["order_lines"][0]
    assert order["total_cents"] == 21639

    first_request = request_return(
        order["id"], account["id"], [(order_line["id"], 6)], reason_code="OVER_ORDERED"
    )
    get_success_data(
        api_client.approve_return_request(first_request["id"], PRO_DESK_ASSOCIATE)
    )
    credited = validate_success(
        api_client.credit_return_request(first_request["id"], CREDIT_MANAGER),
        expected_status=200,
    )
    assert credited["status"] == "CREDITED"
    assert credited["gross_refund_cents"] == 11994
    assert credited["refund_total_cents"] == 12984

    line_after_credit = get_success_data(
        api_client.get_order_line(order_line["id"], headers)
    )
    assert line_after_credit["fulfilled_units"] == 10
    assert line_after_credit["returned_units"] == 6

    order_after_credit = read_pro_order(order["id"], account["id"])
    assert order_after_credit["credited_refund_cents"] == 12984
    assert order_after_credit["credited_gross_refund_cents"] == 11994
    assert order_after_credit["net_volume_cents"] == 7996

    # Only four units remain returnable, so a request for five is refused outright.
    validate_error(
        api_client.create_return_request(
            {
                "pro_order_id": order["id"],
                "reason_code": "OVER_ORDERED",
                "lines": [{"order_line_id": order_line["id"], "qty_units": 5}],
            },
            headers,
        ),
        ApiErrorId.ERR_RETURN_QTY_EXCEEDS_FULFILLED.value,
        expected_status=422,
    )

    second_request = validate_success(
        api_client.create_return_request(
            {
                "pro_order_id": order["id"],
                "reason_code": "OVER_ORDERED",
                "lines": [{"order_line_id": order_line["id"], "qty_units": 4}],
            },
            headers,
        ),
        expected_status=201,
    )
    assert second_request["status"] == "REQUESTED"

    rows, meta = validate_paginated(
        api_client.list_return_requests(headers, params={"pro_order_id": order["id"]})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


# --------------------------------------------------------------------------- #
# Quote negotiation guards                                                     #
# --------------------------------------------------------------------------- #


def test_revision_is_refused_once_three_rounds_have_been_written():
    """PRD §3.5: "The quote's `round_count` must be strictly below three, otherwise `ERR_QUOTE_ROUND_LIMIT` — three counter-offers is the whole negotiation budget."
    PRD §2.11: "37. **Negotiation round budget** — the quote's `round_count` is strictly below three before a further counter-offer or revision, otherwise `ERR_QUOTE_ROUND_LIMIT`. Applies to writing a counter-offer and to revising a quote."
    PRD §3.5: "The contractor's answer to a round is either acceptance further down the chain or a **revision**, which is the cycle edge that closes the loop: a revision takes the quote from `COUNTERED` back to `SUBMITTED`, carries a `revision_note` explaining what the contractor wants changed, increases `revision_count` by one, and increments the quote's `version`."
    PRD §3.5: "It is subject to the same three-round budget (`ERR_QUOTE_ROUND_LIMIT`) and the same account-hold bar (`ERR_ACCOUNT_ON_HOLD`)."
    PRD §3.5: "The quote's `negotiated_total_cents` becomes the sum of those line figures, and its `discount_depth_pct` is recomputed as the amount given away divided by the list value — that is, `list_subtotal_cents` less `negotiated_total_cents`, divided by `list_subtotal_cents` — rounded half up to four decimal places."
    PRD §3.5: "A `CreditManager` moves the quote from `COUNTERED` to `APPROVED`, which stamps `approved_by_user_id` and increments the quote's `version`."

    Design: Corner/validations/negotiation_loop_terminates_at_max_quote_rounds
    """
    store = _stocked_store()
    account = create_pro_account(store["id"], business_name="Haggling Homes")
    headers = make_contractor_admin_headers(account["id"])

    quote, quote_lines = create_draft_quote(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 8)],
        job_name="ROOF-B",
        requested_term_days=15,
    )
    line_prices = [counter_offer_line_price(quote_lines[0]["id"], 1500)]

    version = submit_quote(quote["id"], account["id"])["version"]
    countered = validate_success(
        api_client.counter_offer_job_quote(
            quote["id"], line_prices, 15, version, PRO_DESK_ASSOCIATE
        ),
        expected_status=200,
    )
    for note in ("trim the ridge cap", "still too high"):
        version = get_success_data(
            api_client.revise_job_quote(quote["id"], note, headers)
        )["version"]
        countered = validate_success(
            api_client.counter_offer_job_quote(
                quote["id"], line_prices, 15, version, PRO_DESK_ASSOCIATE
            ),
            expected_status=200,
        )

    assert countered["round_count"] == 3
    version_after_third_round = countered["version"]

    validate_error(
        api_client.revise_job_quote(quote["id"], "one more look please", headers),
        ApiErrorId.ERR_QUOTE_ROUND_LIMIT.value,
        expected_status=409,
    )

    unchanged = get_success_data(api_client.get_job_quote(quote["id"], headers))
    assert unchanged["status"] == "COUNTERED"
    assert unchanged["round_count"] == 3
    assert unchanged["revision_count"] == 2
    assert unchanged["version"] == version_after_third_round
    assert unchanged["negotiated_total_cents"] == 12000
    assert unchanged["discount_depth_pct"] == pytest.approx(0.2496)

    held_line = get_success_data(
        api_client.get_quote_line(quote_lines[0]["id"], headers)
    )
    assert held_line["negotiated_unit_price_cents"] == 1500

    approved = validate_success(
        api_client.approve_job_quote(quote["id"], CREDIT_MANAGER), expected_status=200
    )
    assert approved["status"] == "APPROVED"


def test_approval_is_refused_above_the_thirty_percent_discount_depth():
    """PRD §3.5: "Three conditions guard it: the acting manager's `X-User-ID` must differ from the quote's `authored_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; the quote's `discount_depth_pct` must be no greater than 30 percent, otherwise `ERR_DISCOUNT_DEPTH_EXCEEDED`, because a discount deeper than that needs an authority this API does not model; and the account must not be on hold, otherwise `ERR_ACCOUNT_ON_HOLD`."
    PRD §2.11: "41. **Approvable discount depth** — the quote's `discount_depth_pct` is no greater than 30 percent, otherwise `ERR_DISCOUNT_DEPTH_EXCEEDED`. Applies to approving a job quote."
    PRD §3.5: "The quote's `negotiated_total_cents` becomes the sum of those line figures, and its `discount_depth_pct` is recomputed as the amount given away divided by the list value — that is, `list_subtotal_cents` less `negotiated_total_cents`, divided by `list_subtotal_cents` — rounded half up to four decimal places."
    PRD §3.5: "A `CreditManager` moves the quote from `COUNTERED` to `APPROVED`, which stamps `approved_by_user_id` and increments the quote's `version`."
    PRD §3.5: "The contractor's answer to a round is either acceptance further down the chain or a **revision**, which is the cycle edge that closes the loop: a revision takes the quote from `COUNTERED` back to `SUBMITTED`, carries a `revision_note` explaining what the contractor wants changed, increases `revision_count` by one, and increments the quote's `version`."

    Design: Corner/validations/approving_a_round_deeper_than_the_ceiling_returns_discount_depth_exceeded
    """
    store = _stocked_store()
    account = create_pro_account(store["id"], business_name="Deep Discount Decks")
    headers = make_contractor_admin_headers(account["id"])

    quote, quote_lines = create_draft_quote(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 8)],
        job_name="DECK-A",
        requested_term_days=15,
    )
    version = submit_quote(quote["id"], account["id"])["version"]
    deep_round = validate_success(
        api_client.counter_offer_job_quote(
            quote["id"],
            [counter_offer_line_price(quote_lines[0]["id"], 1300)],
            15,
            version,
            PRO_DESK_ASSOCIATE,
        ),
        expected_status=200,
    )
    assert deep_round["negotiated_total_cents"] == 10400

    validate_error(
        api_client.approve_job_quote(quote["id"], CREDIT_MANAGER),
        ApiErrorId.ERR_DISCOUNT_DEPTH_EXCEEDED.value,
        expected_status=422,
    )
    blocked = get_success_data(api_client.get_job_quote(quote["id"], headers))
    assert blocked["status"] == "COUNTERED"
    assert blocked["discount_depth_pct"] == pytest.approx(0.3497)
    assert blocked["approved_by_user_id"] is None

    version = get_success_data(
        api_client.revise_job_quote(
            quote["id"], "pro desk to re-price at 1500", headers
        )
    )["version"]
    shallow_round = validate_success(
        api_client.counter_offer_job_quote(
            quote["id"],
            [counter_offer_line_price(quote_lines[0]["id"], 1500)],
            15,
            version,
            PRO_DESK_ASSOCIATE,
        ),
        expected_status=200,
    )
    assert shallow_round["discount_depth_pct"] == pytest.approx(0.2496)

    approved = validate_success(
        api_client.approve_job_quote(quote["id"], CREDIT_MANAGER), expected_status=200
    )
    assert approved["status"] == "APPROVED"
    assert approved["negotiated_total_cents"] == 12000
    assert approved["round_count"] == 2
    assert approved["approved_by_user_id"] == CREDIT_MANAGER["X-User-ID"]


def test_counter_offer_rejects_unknown_lines_partial_rounds_and_markups():
    """PRD §3.5: "Every `quote_line_id` named must belong to this quote, otherwise `ERR_QUOTE_LINE_NOT_FOUND`."
    PRD §3.5: "The array must name **every** line of the quote, because partial rounds are not a thing the desk may do; an omission is rejected with `ERR_INCOMPLETE_COUNTER_OFFER`."
    PRD §3.5: "And every `negotiated_unit_price_cents` must be at least 1 cent and no greater than that line's snapshotted `list_unit_price_cents`, otherwise `ERR_INVALID_NEGOTIATED_PRICE` — the desk may discount, never mark up."
    PRD §3.5: "On success, every line's `list_unit_price_cents` is copied from the originating store's stock position for that SKU, every line's `line_list_subtotal_cents` is set to that unit price multiplied by the line's `qty_units`, the quote's `list_subtotal_cents` is set to the sum of those line figures, and the quote's `version` increments."
    PRD §3.5: "Each named line's `negotiated_unit_price_cents` is overwritten and its `line_negotiated_subtotal_cents` is set to that price multiplied by the line's `qty_units`."
    PRD §3.5: "The quote also records the round's proposed `term_days` as the candidate term, stamps `authored_by_user_id` with the acting associate's `X-User-ID`, increases `round_count` by one, and increments its `version`."

    Design: Corner/validations/counter_offer_payload_guards_rejects_partial_rounds_and_out_of_band_prices
    """
    store = create_store()
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    create_store_stock(
        store["id"], SKU_MORTAR_BAG, on_hand_units=400, list_unit_price_cents=2000
    )
    account = create_pro_account(store["id"], business_name="Two Line Masonry")
    headers = make_contractor_admin_headers(account["id"])

    quote, quote_lines = create_draft_quote(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 8), (SKU_MORTAR_BAG, 5)],
        job_name="WALL-A",
        requested_term_days=15,
    )
    shingle_line, mortar_line = quote_lines
    version = submit_quote(quote["id"], account["id"])["version"]

    validate_error(
        api_client.counter_offer_job_quote(
            quote["id"],
            [
                counter_offer_line_price(FABRICATED_ID, 1500),
                counter_offer_line_price(mortar_line["id"], 1800),
            ],
            15,
            version,
            PRO_DESK_ASSOCIATE,
        ),
        ApiErrorId.ERR_QUOTE_LINE_NOT_FOUND.value,
        expected_status=404,
    )

    validate_error(
        api_client.counter_offer_job_quote(
            quote["id"],
            [counter_offer_line_price(shingle_line["id"], 1500)],
            15,
            version,
            PRO_DESK_ASSOCIATE,
        ),
        ApiErrorId.ERR_INCOMPLETE_COUNTER_OFFER.value,
        expected_status=422,
    )

    validate_error(
        api_client.counter_offer_job_quote(
            quote["id"],
            [
                counter_offer_line_price(shingle_line["id"], 2500),
                counter_offer_line_price(mortar_line["id"], 1800),
            ],
            15,
            version,
            PRO_DESK_ASSOCIATE,
        ),
        ApiErrorId.ERR_INVALID_NEGOTIATED_PRICE.value,
        expected_status=422,
    )

    countered = validate_success(
        api_client.counter_offer_job_quote(
            quote["id"],
            [
                counter_offer_line_price(shingle_line["id"], 1500),
                counter_offer_line_price(mortar_line["id"], 1800),
            ],
            15,
            version,
            PRO_DESK_ASSOCIATE,
        ),
        expected_status=200,
    )

    assert countered["list_subtotal_cents"] == 25992
    assert countered["negotiated_total_cents"] == 21000
    assert countered["round_count"] == 1
    assert countered["status"] == "COUNTERED"

    assert (
        get_success_data(api_client.get_quote_line(shingle_line["id"], headers))[
            "negotiated_unit_price_cents"
        ]
        == 1500
    )
    assert (
        get_success_data(api_client.get_quote_line(mortar_line["id"], headers))[
            "line_negotiated_subtotal_cents"
        ]
        == 9000
    )


def test_quote_bound_order_submits_on_the_last_term_day_but_not_after():
    """PRD §3.5: "The term the contractor actually gets is the **lesser** of what was asked and what the tier permits: `term_days` is set to the smaller of `requested_term_days` and the `max_quote_term_days` of the tier persisted on the account at the acceptance instant — 15 days at `MEMBER`, 30 at `GOLD`, 60 at `PLATINUM`, 90 at `DIAMOND`."
    PRD §3.5: "`term_start` is set to the current clock instant and `term_end` to `term_start` advanced by `term_days` days."
    PRD §2.11: "30. **Quote accepted** — the referenced quote's `status` is `ACCEPTED`, otherwise `ERR_QUOTE_NOT_ACCEPTED`. Applies to submitting an order."
    PRD §2.11: "34. **Quote term open** — a quote-bound order is submitted only while the clock is at or after `term_start` and at or before `term_end`, otherwise `ERR_QUOTE_TERM_EXPIRED`. Applies to submitting an order."
    PRD §3.6: "It is `QUOTED` when the order names a `job_quote_id`, that quote has a quote line for the same `sku`, that quote line's `negotiated_unit_price_cents` is not null, and the pricing instant falls at or after the quote's `term_start` and at or before its `term_end`; in that case `effective_unit_price_cents` is exactly the negotiated unit price."
    PRD §3.6: "The order's `subtotal_cents` is the sum of the lines' `line_subtotal_cents`; its `list_subtotal_cents` is the sum over lines of `list_unit_price_cents` multiplied by `qty_units`; and its `discount_cents` is `list_subtotal_cents` less `subtotal_cents`."
    PRD §3.6: "When `tax_exempt_applied` is true, `tax_cents` is 0; otherwise `tax_cents` is the tax base multiplied by the fulfillment store's `tax_rate_pct`, rounded half up to a whole cent in a single rounding on the summed base, never per line."
    PRD §3.6: "On success the server writes `tier_code_applied`, every order-line price field and every order money field, stamps `priced_at` with the current clock instant, recomputes the credit line's `exposure_cents` and `available_cents`, and increments the order's `version`."

    Design: Corner/validations/quote_bound_order_term_gate_is_inclusive_and_requires_acceptance
    """
    store = _stocked_store(tax_rate_pct=0.0825)
    account = create_pro_account(store["id"], business_name="Term Bound Builders")
    headers = make_contractor_admin_headers(account["id"])

    accepted_quote, accepted_lines = create_draft_quote(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 8)],
        job_name="TERM-A",
        requested_term_days=30,
    )
    version = submit_quote(accepted_quote["id"], account["id"])["version"]
    get_success_data(
        api_client.counter_offer_job_quote(
            accepted_quote["id"],
            [counter_offer_line_price(accepted_lines[0]["id"], 1500)],
            30,
            version,
            PRO_DESK_ASSOCIATE,
        )
    )
    get_success_data(api_client.approve_job_quote(accepted_quote["id"], CREDIT_MANAGER))
    accepted = validate_success(
        api_client.accept_job_quote(accepted_quote["id"], headers), expected_status=200
    )
    assert accepted["term_days"] == 15
    assert accepted["term_start"].startswith("2026-08-01T00:00:00")
    assert accepted["term_end"].startswith("2026-08-16T00:00:00")

    unaccepted_quote, _ = create_draft_quote(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 8)],
        job_name="TERM-B",
        requested_term_days=15,
    )
    submit_quote(unaccepted_quote["id"], account["id"])

    edge_order, edge_lines = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 8)],
        job_quote_id=accepted_quote["id"],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    late_order, _ = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 8)],
        job_quote_id=accepted_quote["id"],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    unaccepted_order, _ = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 8)],
        job_quote_id=unaccepted_quote["id"],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )

    validate_error(
        api_client.submit_pro_order(unaccepted_order["id"], headers),
        ApiErrorId.ERR_QUOTE_NOT_ACCEPTED.value,
        expected_status=422,
    )
    assert (
        read_pro_order(unaccepted_order["id"], account["id"])["fulfillment_status"]
        == "DRAFT"
    )

    set_clock("2026-08-16T00:00:00Z")
    priced = validate_success(
        api_client.submit_pro_order(edge_order["id"], headers), expected_status=200
    )
    assert priced["subtotal_cents"] == 12000
    assert priced["discount_cents"] == 3992
    assert priced["tax_cents"] == 990
    assert priced["total_cents"] == 12990
    assert priced["priced_at"].startswith("2026-08-16T00:00:00")

    quoted_line = get_success_data(
        api_client.get_order_line(edge_lines[0]["id"], headers)
    )
    assert quoted_line["price_source"] == "QUOTED"
    assert quoted_line["effective_unit_price_cents"] == 1500
    assert quoted_line["list_unit_price_cents"] == 1999

    set_clock("2026-08-17T00:00:00Z")
    validate_error(
        api_client.submit_pro_order(late_order["id"], headers),
        ApiErrorId.ERR_QUOTE_TERM_EXPIRED.value,
        expected_status=422,
    )
    stranded = read_pro_order(late_order["id"], account["id"])
    assert stranded["fulfillment_status"] == "DRAFT"
    assert stranded["total_cents"] is None


def test_accepted_quote_expires_only_once_the_clock_passes_the_term_end():
    """PRD §3.5: "Once the clock is strictly past `term_end`, a `ProDeskAssociate` retires the quote by moving it from `ACCEPTED` to `EXPIRED`, incrementing its `version`; attempting this while the clock is still inside the term is rejected with `ERR_QUOTE_TERM_ACTIVE`."
    PRD §2.11: "35. **Quote term closed** — a quote is expired only once the clock is strictly past `term_end`, otherwise `ERR_QUOTE_TERM_ACTIVE`. Applies to expiring a job quote."
    PRD §3.5: "`term_start` is set to the current clock instant and `term_end` to `term_start` advanced by `term_days` days."
    PRD §3.5: "The quote's `negotiated_total_cents` becomes the sum of those line figures, and its `discount_depth_pct` is recomputed as the amount given away divided by the list value — that is, `list_subtotal_cents` less `negotiated_total_cents`, divided by `list_subtotal_cents` — rounded half up to four decimal places."

    Design: Corner/validations/expiring_an_accepted_quote_inside_its_term_returns_quote_term_active
    """
    store = _stocked_store()
    account = create_pro_account(store["id"], business_name="Expiry Exteriors")
    headers = make_contractor_admin_headers(account["id"])

    quote, quote_lines = create_draft_quote(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 8)],
        job_name="EXP-A",
        requested_term_days=15,
    )
    version = submit_quote(quote["id"], account["id"])["version"]
    get_success_data(
        api_client.counter_offer_job_quote(
            quote["id"],
            [counter_offer_line_price(quote_lines[0]["id"], 1500)],
            15,
            version,
            PRO_DESK_ASSOCIATE,
        )
    )
    get_success_data(api_client.approve_job_quote(quote["id"], CREDIT_MANAGER))
    accepted = get_success_data(api_client.accept_job_quote(quote["id"], headers))
    assert accepted["term_end"].startswith("2026-08-16T00:00:00")

    validate_error(
        api_client.expire_job_quote(quote["id"], PRO_DESK_ASSOCIATE),
        ApiErrorId.ERR_QUOTE_TERM_ACTIVE.value,
        expected_status=409,
    )
    assert (
        get_success_data(api_client.get_job_quote(quote["id"], headers))["status"]
        == "ACCEPTED"
    )

    set_clock("2026-08-17T00:00:00Z")
    expired = validate_success(
        api_client.expire_job_quote(quote["id"], PRO_DESK_ASSOCIATE),
        expected_status=200,
    )
    assert expired["status"] == "EXPIRED"
    assert expired["term_end"].startswith("2026-08-16T00:00:00")
    assert expired["negotiated_total_cents"] == 12000


# --------------------------------------------------------------------------- #
# Scheduling guards                                                            #
# --------------------------------------------------------------------------- #


def test_appointment_booking_guards_on_truck_access_and_window():
    """PRD §3.8: "The assigned truck must be `AVAILABLE`, otherwise `ERR_TRUCK_OUT_OF_SERVICE`."
    PRD §3.8: "The requested `jobsite_access_type` must be a member of the truck's `access_types_supported`, otherwise `ERR_JOBSITE_ACCESS_UNSUPPORTED`."
    PRD §3.8: "The `window_end` must be strictly after the `window_start`, so a zero-length or inverted window is refused with `ERR_INVALID_DELIVERY_WINDOW`."
    PRD §3.8: "A new appointment starts at `status` `SCHEDULED` with `delivered_at` and `cancel_reason_code` null, and immediately occupies the buffered window against later bookings."
    PRD §3.1: "Taking a truck out of service is a mechanical hold recorded with a `reason_code`; it flips `status` to `OUT_OF_SERVICE` and increments the truck's `version`, but it deliberately leaves the truck's existing appointments in place, still occupying their windows, so that a dispatcher rescheduling around a breakdown does not silently double-book the replacement vehicle."

    Design: Corner/validations/appointment_guards_reject_dead_trucks_bad_access_and_empty_windows
    """
    store = _stocked_store(tax_rate_pct=0.0825, lift_gate_available=True)
    live_truck = create_delivery_truck(
        store["id"],
        truck_code="T-1",
        lift_gate_equipped=True,
        access_types_supported=["CURBSIDE"],
        turnaround_buffer_minutes=30,
    )
    dead_truck = create_delivery_truck(
        store["id"],
        truck_code="T-2",
        lift_gate_equipped=True,
        access_types_supported=["CURBSIDE"],
        turnaround_buffer_minutes=30,
    )
    grounded = get_success_data(
        api_client.take_truck_out_of_service(
            dead_truck["id"], "MAINTENANCE", STORE_OPERATIONS
        )
    )
    assert grounded["status"] == "OUT_OF_SERVICE"

    account = create_pro_account(store["id"], business_name="Jobsite Access Co")
    order, _ = setup_reserved_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="DELIVERY",
        lift_gate_required=False,
    )[:2]

    validate_error(
        api_client.create_delivery_appointment(
            create_delivery_appointment_payload(
                order["id"],
                dead_truck["id"],
                window_start="2026-08-05T09:00:00Z",
                window_end="2026-08-05T11:00:00Z",
                jobsite_access_type="CURBSIDE",
            ),
            STORE_OPERATIONS,
        ),
        ApiErrorId.ERR_TRUCK_OUT_OF_SERVICE.value,
        expected_status=409,
    )

    validate_error(
        api_client.create_delivery_appointment(
            create_delivery_appointment_payload(
                order["id"],
                live_truck["id"],
                window_start="2026-08-05T09:00:00Z",
                window_end="2026-08-05T11:00:00Z",
                jobsite_access_type="DRIVEWAY",
            ),
            STORE_OPERATIONS,
        ),
        ApiErrorId.ERR_JOBSITE_ACCESS_UNSUPPORTED.value,
        expected_status=422,
    )

    validate_error(
        api_client.create_delivery_appointment(
            create_delivery_appointment_payload(
                order["id"],
                live_truck["id"],
                window_start="2026-08-05T09:00:00Z",
                window_end="2026-08-05T09:00:00Z",
                jobsite_access_type="CURBSIDE",
            ),
            STORE_OPERATIONS,
        ),
        ApiErrorId.ERR_INVALID_DELIVERY_WINDOW.value,
        expected_status=422,
    )

    appointment = validate_success(
        api_client.create_delivery_appointment(
            create_delivery_appointment_payload(
                order["id"],
                live_truck["id"],
                window_start="2026-08-05T09:00:00Z",
                window_end="2026-08-05T11:00:00Z",
                jobsite_access_type="CURBSIDE",
            ),
            STORE_OPERATIONS,
        ),
        expected_status=201,
    )
    assert appointment["status"] == "SCHEDULED"
    assert appointment["jobsite_access_type"] == "CURBSIDE"

    rows, meta = validate_paginated(
        api_client.list_delivery_appointments(
            STORE_OPERATIONS, params={"pro_order_id": order["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_staging_accepts_the_store_ceiling_and_refuses_the_wrong_channel():
    """PRD §3.8: "The requested `stage_hours` may not exceed the store's `max_stage_hours`, otherwise `ERR_STAGE_WINDOW_TOO_LONG`."
    PRD §3.8: "The two channels are strictly separated: a `WILL_CALL` order may not take a delivery appointment and a `DELIVERY` order may not take a will-call staging, and either mismatch is refused with `ERR_DELIVERY_MODE_MISMATCH`."
    PRD §3.8: "The server computes `expires_at` as `stage_start` advanced by `stage_hours` hours."
    PRD §3.8: "A new staging starts at `status` `SCHEDULED` with `picked_up_by` and `picked_up_at` null."

    Design: Corner/validations/staging_window_ceiling_is_inclusive_and_mode_mismatch_is_enforced_both_ways
    """
    store = _stocked_store(max_stage_hours=48, will_call_bay_slots=2)
    truck = create_delivery_truck(
        store["id"],
        truck_code="T-1",
        lift_gate_equipped=True,
        access_types_supported=["CURBSIDE"],
        turnaround_buffer_minutes=30,
    )
    account = create_pro_account(store["id"], business_name="Mode Mixup Millwork")

    will_call_order, _ = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    submit_order(will_call_order["id"], account["id"])
    reserve_order(will_call_order["id"])

    delivery_order, _ = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="DELIVERY",
        lift_gate_required=False,
    )
    submit_order(delivery_order["id"], account["id"])
    reserve_order(delivery_order["id"])

    validate_error(
        api_client.create_will_call_staging(
            create_will_call_staging_payload(
                will_call_order["id"],
                store["id"],
                stage_start="2026-08-01T09:00:00Z",
                stage_hours=49,
            ),
            STORE_OPERATIONS,
        ),
        ApiErrorId.ERR_STAGE_WINDOW_TOO_LONG.value,
        expected_status=422,
    )

    validate_error(
        api_client.create_delivery_appointment(
            create_delivery_appointment_payload(
                will_call_order["id"],
                truck["id"],
                window_start="2026-08-05T09:00:00Z",
                window_end="2026-08-05T11:00:00Z",
                jobsite_access_type="CURBSIDE",
            ),
            STORE_OPERATIONS,
        ),
        ApiErrorId.ERR_DELIVERY_MODE_MISMATCH.value,
        expected_status=422,
    )

    validate_error(
        api_client.create_will_call_staging(
            create_will_call_staging_payload(
                delivery_order["id"],
                store["id"],
                stage_start="2026-08-01T09:00:00Z",
                stage_hours=24,
            ),
            STORE_OPERATIONS,
        ),
        ApiErrorId.ERR_DELIVERY_MODE_MISMATCH.value,
        expected_status=422,
    )

    staging = validate_success(
        api_client.create_will_call_staging(
            create_will_call_staging_payload(
                will_call_order["id"],
                store["id"],
                stage_start="2026-08-01T09:00:00Z",
                stage_hours=48,
            ),
            STORE_OPERATIONS,
        ),
        expected_status=201,
    )
    assert staging["stage_hours"] == 48
    assert staging["expires_at"].startswith("2026-08-03T09:00:00")
    assert staging["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api_client.list_will_call_stagings(
            STORE_OPERATIONS, params={"pro_order_id": delivery_order["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []
