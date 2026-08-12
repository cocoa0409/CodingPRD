"""State machine transitions: cyclic flows, invalid transitions, auto-transitions."""
import pytest

from test_helpers import (
    ADMIN,
    CREDIT,
    DRIVER,
    SALES,
    ApiErrorId,
    api_client,
    assign_order_to_manifest,
    begin_loading,
    close_manifest,
    create_credit_memo_payload,
    create_delivery_manifest_payload,
    create_new_item_request_payload,
    create_order_guide_payload,
    create_purchase_order_payload,
    create_retail_price_record_payload,
    get_success_data,
    make_store_manager_headers,
    order_line,
    publish_fuel_rate,
    setup_draft_order,
    setup_guide,
    setup_invoiced_order,
    setup_manifest,
    setup_product,
    setup_retailer,
    setup_submitted_order,
    validate_error,
    validate_success,
)


def test_cancel_already_cancelled_order_rejected(api):
    """PRD §3.4: "Once assigned, an order can no longer be cancelled, and a
    cancel attempt against an order that is not `DRAFT` or `SUBMITTED` fails
    with `ERR_INVALID_STATE` (HTTP 409)." A CANCELLED order is neither DRAFT
    nor SUBMITTED.

    Design: Corner/state_machines/cancel_already_cancelled_order_rejected
    """
    base = setup_draft_order([{"sku": "P1", "cases_qty": 1, "split_units_qty": 0}])
    first = get_success_data(api_client.cancel_order(base["order"]["id"], base["sm_headers"]))
    assert first["status"] == "CANCELLED"
    resp = api_client.cancel_order(base["order"]["id"], base["sm_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_void_draft_memo_rejected(api, credit_manager_headers):
    """PRD §3.7: "Voiding a `POSTED` memo is the compensating action". Voiding
    a DRAFT memo is outside the legal from-state and is rejected with
    `ERR_INVALID_STATE`.

    Design: Corner/state_machines/void_draft_memo_rejected
    """
    base = setup_invoiced_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
                                fuel_doe=3.00)
    invoice = base["invoice"]
    memo = get_success_data(api_client.create_credit_memo(
        invoice["id"],
        create_credit_memo_payload(origin="MANUAL", amount_cents=100),
        credit_manager_headers,
    ))
    resp = api_client.void_credit_memo(memo["id"], credit_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_authorize_from_revision_requested_rejected(api, admin_headers, sales_rep_headers):
    """PRD §3.8: "Authorization is the terminal success path: from
    `UNDER_REVIEW` ... the administrator authorizes the request". REVISION_REQUESTED
    is not UNDER_REVIEW, so authorize is rejected with `ERR_INVALID_STATE`.

    Design: Corner/state_machines/authorize_from_revision_requested_rejected
    """
    retailer, _ = setup_retailer()
    px = setup_product(sku="PX", case_pack_units=12, case_cost_cents=900,
                       unit_cost_cents=90, weight_lbs_per_case=6)
    setup_guide(retailer_id=retailer["id"], lines=[])
    nir = get_success_data(api_client.create_new_item_request(
        create_new_item_request_payload(retailer_id=retailer["id"], product_id=px["id"],
                                        proposed_shelf_price_cents=999),
        sales_rep_headers,
    ))
    get_success_data(api_client.start_review(nir["id"], admin_headers))
    get_success_data(api_client.request_revision(nir["id"], {"revision_notes": "reprice"},
                                                 admin_headers))
    resp = api_client.authorize_request(nir["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_past_due_auto_transition_on_clock_advance(api, admin_headers, credit_manager_headers):
    """PRD §3.7: "when the logical clock passes an `OPEN` invoice's `due_date`
    while its `balance_cents` remains positive, the invoice auto-transitions
    `OPEN` to `PAST_DUE` and the retailer's `credit_status` is set to
    `CREDIT_HOLD`".
    PRD §3.6: "the delivery date itself for `COD`, seven days after the
    delivery date for `NET7`".

    Design: Corner/state_machines/past_due_auto_transition_on_clock_advance
    """
    base = setup_invoiced_order(
        [{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
        fuel_doe=3.00,
        retailer_overrides={"credit_terms": "NET7"},
    )
    invoice = base["invoice"]
    # Delivery 2026-05-25 (Mon); NET7 due = 2026-06-01
    assert invoice["due_date"] == "2026-06-01"
    get_success_data(api_client.set_clock({"to_iso8601": "2026-06-05T00:00:00Z"}, admin_headers))
    inv = get_success_data(api_client.get_invoice(invoice["id"], credit_manager_headers))
    assert inv["status"] == "PAST_DUE"
    ret = get_success_data(api_client.get_retailer(base["retailer"]["id"], credit_manager_headers))
    assert ret["credit_status"] == "CREDIT_HOLD"


def test_manifest_auto_completes_when_all_orders_invoiced(api, route_driver_headers, admin_headers):
    """PRD §3.5: "A manifest completes itself: once every non-cancelled order
    in it has reached `DELIVERED` or `INVOICED`, the manifest auto-transitions
    `CLOSED` to `COMPLETED` and increments its `version`."

    Design: Corner/state_machines/manifest_auto_completes_when_all_orders_invoiced
    """
    base = setup_submitted_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}])
    manifest = setup_manifest()
    publish_fuel_rate(doe_index_usd=3.00)
    manifest = assign_order_to_manifest(manifest, base["order"])
    manifest = begin_loading(manifest)
    manifest = close_manifest(manifest)
    get_success_data(api_client.confirm_delivery(base["order"]["id"], route_driver_headers))
    final = get_success_data(api_client.get_delivery_manifest(manifest["id"], admin_headers))
    assert final["status"] == "COMPLETED"


def test_new_item_revision_cycle(api, admin_headers, sales_rep_headers):
    """PRD §3.8: "The administrator may send the request back, moving
    `UNDER_REVIEW` to `REVISION_REQUESTED` and recording the reason in
    `revision_notes`; the sales rep revises and resubmits — optionally
    supplying a new `proposed_shelf_price_cents` — which moves
    `REVISION_REQUESTED` back to `SUBMITTED` and clears `revision_notes`, so
    the cycle can repeat as many times as the negotiation needs."
    PRD §3.8: "a base of 50,000 cents plus 250 cents for each unit in the
    product's `case_pack_units`, capped at 150,000 cents".

    Design: Difficulty/non_linear_state_machine/new_item_revision_cycle
    """
    retailer, _ = setup_retailer()
    p1 = setup_product(sku="P1")
    px = setup_product(sku="PX", case_pack_units=12, case_cost_cents=900,
                       unit_cost_cents=90, weight_lbs_per_case=6)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": p1["id"], "par_cases": 0}])
    nir = get_success_data(api_client.create_new_item_request(
        create_new_item_request_payload(retailer_id=retailer["id"], product_id=px["id"],
                                        proposed_shelf_price_cents=999),
        sales_rep_headers,
    ))
    reviewed = get_success_data(api_client.start_review(nir["id"], admin_headers))
    assert reviewed["slotting_fee_cents"] == 53000  # 50000 + 12*250, under cap
    get_success_data(api_client.request_revision(nir["id"], {"revision_notes": "reprice"},
                                                 admin_headers))
    get_success_data(api_client.resubmit(nir["id"], {"proposed_shelf_price_cents": 949},
                                         sales_rep_headers))
    get_success_data(api_client.start_review(nir["id"], admin_headers))
    resp = api_client.authorize_request(nir["id"], admin_headers)
    data = validate_success(resp)
    assert data["status"] == "AUTHORIZED"
    # Guide line appended
    guide_now = get_success_data(api_client.get_order_guide(guide["id"], sales_rep_headers))
    product_ids = [line["product_id"] for line in guide_now["lines"]]
    assert px["id"] in product_ids
    # Retail price record published at the resubmitted price
    prices = get_success_data(api_client.list_retail_price_records(
        sales_rep_headers,
        params={"retailer_id": retailer["id"], "product_id": px["id"], "status": "ACTIVE"},
    ))
    assert prices[0]["shelf_price_cents"] == 949


def test_new_item_revision_cycle_clears_revision_notes(api, admin_headers, sales_rep_headers):
    """PRD §3.8: "the sales rep revises and resubmits ... which moves
    `REVISION_REQUESTED` back to `SUBMITTED` and clears `revision_notes`".

    Design: Difficulty/non_linear_state_machine/new_item_revision_cycle
    """
    retailer, _ = setup_retailer()
    px = setup_product(sku="PX", case_pack_units=12, case_cost_cents=900,
                       unit_cost_cents=90, weight_lbs_per_case=6)
    setup_guide(retailer_id=retailer["id"], lines=[])
    nir = get_success_data(api_client.create_new_item_request(
        create_new_item_request_payload(retailer_id=retailer["id"], product_id=px["id"],
                                        proposed_shelf_price_cents=999),
        sales_rep_headers,
    ))
    get_success_data(api_client.start_review(nir["id"], admin_headers))
    get_success_data(api_client.request_revision(nir["id"], {"revision_notes": "reprice"},
                                                 admin_headers))
    resubmitted = get_success_data(api_client.resubmit(
        nir["id"], {"proposed_shelf_price_cents": 949}, sales_rep_headers,
    ))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted.get("revision_notes") in (None, "")


def test_invoice_paid_to_open_reversal_cycle(api, credit_manager_headers):
    """PRD §3.7: "Reversing an `APPLIED` payment marks it `REVERSED`, adds its
    amount back to the invoice's `balance_cents` and to the retailer's
    `ar_balance_cents`, and re-evaluates `credit_status`. If the reversed
    payment was the one that closed the invoice, the invoice returns `PAID` to
    `OPEN`".

    Design: Difficulty/non_linear_state_machine/invoice_paid_to_open_reversal_cycle
    """
    base = setup_invoiced_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
                                fuel_doe=3.00)
    invoice = base["invoice"]
    assert invoice["invoiced_total_cents"] == 60600
    pay = get_success_data(api_client.apply_payment(
        invoice["id"], {"amount_cents": 60600, "method": "ACH"}, credit_manager_headers,
    ))
    paid_invoice = get_success_data(api_client.get_invoice(invoice["id"], credit_manager_headers))
    assert paid_invoice["status"] == "PAID"
    resp = api_client.reverse_payment(pay["id"], credit_manager_headers)
    reversed_pay = validate_success(resp)
    assert reversed_pay["status"] == "REVERSED"
    inv = get_success_data(api_client.get_invoice(invoice["id"], credit_manager_headers))
    assert inv["status"] == "OPEN"
    assert inv["balance_cents"] == 60600


def test_invoice_paid_to_open_reversal_restores_balance(api, credit_manager_headers):
    """PRD §3.7: "adds its amount back to the invoice's `balance_cents`".

    Design: Difficulty/non_linear_state_machine/invoice_paid_to_open_reversal_cycle
    """
    base = setup_invoiced_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
                                fuel_doe=3.00)
    invoice = base["invoice"]
    pay = get_success_data(api_client.apply_payment(
        invoice["id"], {"amount_cents": 60600, "method": "ACH"}, credit_manager_headers,
    ))
    get_success_data(api_client.reverse_payment(pay["id"], credit_manager_headers))
    inv = get_success_data(api_client.get_invoice(invoice["id"], credit_manager_headers))
    assert inv["invoiced_total_cents"] == 60600
    assert inv["balance_cents"] == 60600
