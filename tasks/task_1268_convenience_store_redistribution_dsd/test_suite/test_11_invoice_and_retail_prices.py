"""Invoice/payment/memo errors, COD due date, retail price supersede."""
import pytest

from test_helpers import (
    ADMIN,
    CREDIT,
    SALES,
    ApiErrorId,
    api_client,
    create_credit_memo_payload,
    create_retail_price_record_payload,
    get_success_data,
    setup_invoiced_order,
    setup_product,
    setup_retailer,
    validate_error,
    validate_success,
)


def test_payment_exceeds_balance_error(api, credit_manager_headers):
    """PRD §3.7: "the amount may not exceed the invoice's `balance_cents`,
    else `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422)".

    Design: Corner/validations/payment_exceeds_balance_error
    """
    base = setup_invoiced_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
                                fuel_doe=3.00)
    invoice = base["invoice"]
    resp = api_client.apply_payment(
        invoice["id"], {"amount_cents": 60601, "method": "ACH"}, credit_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, expected_status=422)


def test_memo_exceeds_invoice_error(api, credit_manager_headers):
    """PRD §3.7: "Both at creation and at posting time, the amount may not
    exceed the invoice's `balance_cents`, else `ERR_MEMO_EXCEEDS_INVOICE`
    (HTTP 422)".

    Design: Corner/validations/memo_exceeds_invoice_error
    """
    base = setup_invoiced_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
                                fuel_doe=3.00)
    invoice = base["invoice"]
    resp = api_client.create_credit_memo(
        invoice["id"],
        create_credit_memo_payload(origin="MANUAL", amount_cents=60601),
        credit_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_MEMO_EXCEEDS_INVOICE, expected_status=422)


def test_manual_credit_hold_blocks_submit(api, credit_manager_headers):
    """PRD §3.4: "the retailer must be in `GOOD_STANDING`, else
    `ERR_CREDIT_HOLD` (HTTP 422)". PRD §3.1: "The credit desk can also place
    or release a hold directly by passing a `hold` flag".

    Design: Corner/validations/manual_credit_hold_blocks_submit
    """
    from test_helpers import setup_draft_order
    base = setup_draft_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}])
    hold_resp = api_client.set_credit_hold(
        base["retailer"]["id"], {"hold": True}, credit_manager_headers,
    )
    held = validate_success(hold_resp)
    assert held["credit_status"] == "CREDIT_HOLD"
    resp = api_client.submit_order(
        base["order"]["id"],
        {"expected_order_version": base["order_version"]},
        base["sm_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_HOLD, expected_status=422)


def test_tobacco_license_missing_error(api, admin_headers):
    """PRD §3.4: "Draft creation already enforces three rules: ... any line
    referencing a tobacco product requires the retailer to carry a
    `tobacco_license_id`, else `ERR_TOBACCO_LICENSE_MISSING` (HTTP 422)".

    Design: Corner/validations/tobacco_license_missing_error
    """
    from test_helpers import (
        create_purchase_order_payload,
        make_store_manager_headers,
        order_line,
        setup_guide,
    )
    retailer_payload = {
        "store_name": "RN",
        "jurisdiction_code": "CA_NORTH",
        "credit_terms": "NET7",
        "credit_limit_cents": 10_000_000,
        "delivery_day": "MON",
    }
    retailer = get_success_data(api_client.create_retailer(retailer_payload, admin_headers))
    sm = make_store_manager_headers(retailer["id"])
    t1 = setup_product(sku="T1", case_pack_units=60, case_cost_cents=33000,
                       unit_cost_cents=550, split_case_allowed=True, is_tobacco=True,
                       weight_lbs_per_case=15)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": t1["id"], "par_cases": 0}])
    # The retailer carries no tobacco_license_id, so draft creation is rejected.
    resp = api_client.create_purchase_order(
        create_purchase_order_payload(retailer_id=retailer["id"], order_guide_id=guide["id"],
                                      lines=[order_line(t1["id"], cases_qty=1, split_units_qty=0)]),
        sm,
    )
    validate_error(resp, ApiErrorId.ERR_TOBACCO_LICENSE_MISSING, expected_status=422)


def test_order_cutoff_passed_error_alone(api):
    """PRD §3.4: "the logical clock must still be before the cutoff — midnight
    at the start of the delivery day minus the guide's `cutoff_hours_before`
    hours — else `ERR_ORDER_CUTOFF_PASSED` (HTTP 422)".

    Design: Corner/validations/order_cutoff_passed_error_alone
    """
    from test_helpers import setup_draft_order
    base = setup_draft_order(
        [{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
        clock_to="2026-05-24T12:00:00Z",  # past the 24h cutoff for MON 2026-05-25
    )
    resp = api_client.submit_order(
        base["order"]["id"],
        {"expected_order_version": base["order_version"]},
        base["sm_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_CUTOFF_PASSED, expected_status=422)


def test_credit_limit_exceeded_on_submit(api):
    """PRD §3.4: "if that exposure now exceeds the retailer's
    `credit_limit_cents`, the submission is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` instead of proceeding."

    Design: Corner/validations/credit_limit_exceeded_on_submit
    """
    from test_helpers import setup_draft_order
    base = setup_draft_order(
        [{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
        retailer_overrides={"credit_limit_cents": 60000},
    )
    resp = api_client.submit_order(
        base["order"]["id"],
        {"expected_order_version": base["order_version"]},
        base["sm_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, expected_status=422)


def test_cod_due_date_equals_delivery_date(api, route_driver_headers, credit_manager_headers):
    """PRD §3.6: "its `due_date` derives from the retailer's terms — the
    delivery date itself for `COD`, seven days after the delivery date for
    `NET7`, fourteen days after for `NET14`."

    Design: Corner/calculations/cod_due_date_equals_delivery_date
    """
    base = setup_invoiced_order(
        [{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
        fuel_doe=3.00,
        retailer_overrides={"credit_terms": "COD"},
    )
    invoice = base["invoice"]
    assert invoice["due_date"] == "2026-05-25"
    assert invoice["invoiced_total_cents"] == 60600


def test_retail_price_supersede_side_effect(api, sales_rep_headers):
    """PRD §3.2: "Publishing a record for a store-product pair supersedes
    whatever record was previously `ACTIVE` for that pair: the prior record's
    `status` becomes `SUPERSEDED`, and the new record's `supersedes_id` points
    back to it, forming a durable price history."

    Design: Corner/endpoints/retail_price_supersede_side_effect
    """
    retailer, _ = setup_retailer()
    p1 = setup_product(sku="P1")
    rpr1 = get_success_data(api_client.create_retail_price_record(
        create_retail_price_record_payload(
            retailer_id=retailer["id"], product_id=p1["id"],
            shelf_price_cents=199, effective_start="2026-05-01",
        ),
        sales_rep_headers,
    ))
    rpr2 = get_success_data(api_client.create_retail_price_record(
        create_retail_price_record_payload(
            retailer_id=retailer["id"], product_id=p1["id"],
            shelf_price_cents=219, effective_start="2026-06-01",
        ),
        sales_rep_headers,
    ))
    assert rpr2["supersedes_id"] == rpr1["id"]
    assert rpr2["status"] == "ACTIVE"
    superseded = get_success_data(api_client.list_retail_price_records(
        sales_rep_headers,
        params={"retailer_id": retailer["id"], "product_id": p1["id"], "status": "SUPERSEDED"},
    ))
    assert superseded[0]["id"] == rpr1["id"]
