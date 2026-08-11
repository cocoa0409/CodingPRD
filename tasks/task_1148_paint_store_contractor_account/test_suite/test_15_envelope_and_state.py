"""Response envelope contracts (PRD §2.2), order creation defaults and
immediate consistency (PRD §3.6), and computed account balances (PRD §3.1)."""
from test_helpers import (
    TEST_USERS,
    assert_order,
    create_order_payload,
    get_account_version,
    is_iso8601_timestamp,
    place_and_pay_order,
    place_order,
    setup_account_job_product,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]


def test_order_create_response_envelope(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body: ... The
    `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`. The `api_request_timestamp` is a server-generated
    ISO 8601 UTC timestamp with three fractional digits. The `response_type`
    is either "object" for a single resource or "array" for a list of
    resources. The `data` field contains the resource object or an array of
    resource objects. ... Unless otherwise noted, operations that create or
    modify a resource will return the created or updated resource object in
    the data field."

    Design: Corner/endpoints/order_create_response_envelope
    """
    account, _, job, product = setup_account_job_product(
        company_name="Env Co", credit_limit_cents=1_000_000,
        jurisdiction_code="AL-OPEN", jurisdiction_name="Alabama",
        sku="P-ENV", list_price_cents=5000)
    resp = api.create_order(
        create_order_payload(account["id"], job["id"],
                             get_account_version(account["id"]),
                             [{"product_id": product["id"], "quantity": 1}]),
        ASSOCIATE)
    body = resp.json()
    assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
    assert "meta" in body, "envelope must carry meta"
    assert isinstance(body["meta"].get("api_request_id"), str), \
        "meta.api_request_id must be present"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']}")
    assert is_iso8601_timestamp(body["meta"].get("api_request_timestamp", "")), \
        "meta.api_request_timestamp must be ISO 8601"
    assert body["response_type"] == "object", (
        f"a single-resource create is response_type object, "
        f"got {body['response_type']}")
    order = body["data"]
    assert_order(order)
    assert order["subtotal_cents"] == 5000
    assert order["tax_cents"] == 413, (
        f"round_half_up(5000 * 825 / 10000) = 413, got {order['tax_cents']}")
    assert order["total_cents"] == 5413


def test_order_initial_state_is_unpaid_pending(api):
    """PRD §3.6: "A created order starts `UNPAID` and `PENDING` with
    `refunded_cents` zero and `paid_at` null; its creation recomputes the
    account's `outstanding_balance_cents` and increments the account's
    `version`." PRD §3.6: "Each line snapshots the product's current
    `list_price_cents` into `unit_list_price_cents`, and the account's tier at
    that moment is frozen into the order's `tier_snapshot` — later tier
    changes never reprice an existing order, and the loyalty multiplier of
    §3.7 also keys off this snapshot."

    Design: Corner/state_machines/order_initial_state_is_unpaid_pending
    """
    account, _, job, product = setup_account_job_product(
        company_name="Init Co", credit_limit_cents=1_000_000,
        jurisdiction_code="AK-OPEN", jurisdiction_name="Alaska",
        sku="P-INIT", list_price_cents=5000)
    order = place_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 1}])
    assert_order(order)
    assert order["payment_status"] == "UNPAID"
    assert order["fulfillment_status"] == "PENDING"
    assert order["refunded_cents"] == 0
    assert order["paid_at"] is None
    assert order["tier_snapshot"] == "STANDARD", (
        "the fresh account's STANDARD tier is frozen into the snapshot")


def _setup_unpaid_order(api):
    """Account with one unpaid order (total 5413)."""
    account, _, job, product = setup_account_job_product(
        company_name="Out Co", credit_limit_cents=1_000_000,
        jurisdiction_code="GA-OPEN", jurisdiction_name="Georgia",
        sku="P-OUT", list_price_cents=5000)
    order = place_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 1}])
    return account, order


def test_outstanding_balance_reflects_unpaid_order(api):
    """PRD §3.1: "Reading an account returns these derived figures alongside
    the inputs: `outstanding_balance_cents`, the sum of `total_cents` over the
    account's orders whose `payment_status` is `UNPAID`; ...".

    Design: Corner/endpoints/account_read_reflects_outstanding
    """
    account, order = _setup_unpaid_order(api)
    view = validate_success(api.get_contractor_account(account["id"], ADMIN))
    assert view["outstanding_balance_cents"] == 5413, (
        f"the unpaid order's full total counts, "
        f"got {view['outstanding_balance_cents']}")


def test_outstanding_balance_drops_after_pay(api):
    """PRD §3.6: "Payment stamps `paid_at` from the logical clock and fires
    the loyalty earn cascade of §3.7, recomputes the account's
    `outstanding_balance_cents` (the order leaves the unpaid set) and the
    job's `spent_cents`, and increments both the order's and the account's
    `version`."

    Design: Corner/endpoints/account_read_reflects_outstanding
    """
    account, order = _setup_unpaid_order(api)
    validate_success(api.pay_order(order["id"], ASSOCIATE))
    view = validate_success(api.get_contractor_account(account["id"], ADMIN))
    assert view["outstanding_balance_cents"] == 0, (
        f"the paid order leaves the unpaid set, "
        f"got {view['outstanding_balance_cents']}")


def test_create_response_carries_computed_totals(api):
    """PRD §2.9: "Fields described as "recomputed" or "computed" — balances,
    spent totals, pull-through percentages, order totals — are derived from
    underlying rows and are kept in sync immediately whenever a contributing
    event lands; they are never stale snapshots and never client-writable."
    PRD §3.6: "Order totals derive from the lines in a pinned evaluation order
    — lines, then subtotal, then tax, then total. `subtotal_cents` is the sum
    of `line_total_cents` over all lines. ... `tax_cents` is 8.25 percent of
    the discounted `subtotal_cents`, rounded half up, computed exactly once at
    order level and never per line. `total_cents` is `subtotal_cents` plus
    `tax_cents`."

    The 201 create response itself already carries the fully computed totals
    for two units at 5000: subtotal 10000, tax 825, total 10825 — no re-fetch
    is needed.

    Design: Corner/consistency_model/create_response_carries_computed_totals
    """
    account, _, job, product = setup_account_job_product(
        company_name="Imm Co", credit_limit_cents=1_000_000,
        jurisdiction_code="WI-OPEN", jurisdiction_name="Wisconsin",
        sku="P-IMM", list_price_cents=5000)
    resp = api.create_order(
        create_order_payload(account["id"], job["id"],
                             get_account_version(account["id"]),
                             [{"product_id": product["id"], "quantity": 2}]),
        ASSOCIATE)
    order = validate_success(resp, expected_status=201)
    assert order["subtotal_cents"] == 10_000
    assert order["tax_cents"] == 825, (
        f"round_half_up(10000 * 825 / 10000) = 825, got {order['tax_cents']}")
    assert order["total_cents"] == 10_825
