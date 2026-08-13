"""Quote intake validation, customer uniqueness, quote lifecycle edges
(supersede, double-accept, expiry), pagination, and 404 existence (PRD §2.3,
§2.9, §2.10, §3.1, §3.4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_quote,
    assert_money_eq,
    create_config,
    create_customer,
    create_quote,
    create_variety,
    factories,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def _variety(api):
    return create_variety(api)


def _two_pallet_lines(v_id):
    return [factories.quote_line(v_id, "PREMIUM", 2)]


# ---------------------------------------------------------------------------
# Corner: entities / quote_create_missing_required_field_returns_invalid_request
# ---------------------------------------------------------------------------

def test_quote_create_missing_customer_id_returns_invalid_request(api):
    """PRD §2.9: "4. **Request shape** — required fields present, types and ranges valid, windows aligned, uniqueness respected; otherwise `ERR_INVALID_REQUEST`."
    PRD §3.4: "A `SalesRep` prices a prospective order by creating a quote with the `customer_id`, the requested `delivery_date` (which must not be earlier than the clock's current date, else `ERR_DELIVERY_DATE_TOO_SOON`), the `settlement_method` (`CARD` or `CASH_CHECK`), the planned route mix `z1_pallets`, `z2_pallets`, and `z3_pallets` (each zero or more), and the merchandise `lines`."

    Design: Corner/entities/quote_create_missing_required_field_returns_invalid_request
    """
    v = _variety(api)
    payload = {
        "delivery_date": "2026-08-03",
        "settlement_method": "CARD",
        "z1_pallets": 0,
        "z2_pallets": 10,
        "z3_pallets": 0,
        "lines": _two_pallet_lines(v["id"]),
    }
    resp = api.create_quote(payload, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


# ---------------------------------------------------------------------------
# Corner: entities / customer_email_uniqueness_enforced
# ---------------------------------------------------------------------------

def test_customer_email_uniqueness_enforced(api):
    """PRD §3.1: "A `SalesRep` registers each buyer as a `Customer` with `full_name`, a unique `email` (duplicates rejected with `ERR_INVALID_REQUEST`), `phone`, a `freight_zone` of 1, 2, or 3 (any other value is rejected with `ERR_INVALID_REQUEST`), and a delivery `address`."

    Design: Corner/entities/customer_email_uniqueness_enforced
    """
    create_customer(api)
    resp = api.create_customer(
        factories.create_customer_payload(
            full_name="Aria Clone", email="aria@example.com",
            phone="555-9999", freight_zone=1, address="1 Dup St",
        ),
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


# ---------------------------------------------------------------------------
# Corner: state_machines / quote_double_accept_returns_already_terminal
# ---------------------------------------------------------------------------

def test_quote_double_accept_returns_already_terminal(api):
    """PRD §3.4: "A `SalesRep` may accept only a `DRAFT` quote: an accept attempted against a `SUPERSEDED` or `EXPIRED` quote is rejected with `ERR_INVALID_STATE`, while an accept against an already-`ACCEPTED` quote — like any action on a terminal quote — is rejected with `ERR_ALREADY_TERMINAL`."
    PRD §3.4: "The order records the `quote_id` (at most one order ever exists per quote), copies `customer_id`, `price_config_id`, `delivery_date`, `settlement_method`, `capacity_zone`, `turf_sqft`, `freight_amount`, `pre_discount_subtotal`, `volume_tier`, `volume_discount`, `card_fee`, `total_price`, and `total_pallets` from the quote, and takes `freight_zone` from the customer record."

    Design: Corner/state_machines/quote_double_accept_returns_already_terminal
    """
    create_config(api)
    v = _variety(api)
    c = create_customer(api)
    q = create_quote(api, c["id"], _two_pallet_lines(v["id"]), 1, 1, 0)
    order = accept_quote(api, q["id"])

    resp = api.accept_quote(q["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)

    data, meta = validate_paginated(api.list_quote_orders(q["id"], SALES))
    assert len(data) == 1 and data[0]["id"] == order["id"], (
        "at most one order ever exists per quote"
    )


# ---------------------------------------------------------------------------
# Corner: state_machines / new_draft_quote_supersedes_existing_draft
# ---------------------------------------------------------------------------

def test_new_draft_quote_supersedes_existing_draft(api):
    """PRD §3.4: "One draft per customer is the rule. Creating a new quote for a customer who already has a `DRAFT` quote supersedes the older one: its status becomes `SUPERSEDED`, its `superseded_by_id` points at the new quote, and its `version` increments."
    PRD §3.4: "A `SalesRep` may accept only a `DRAFT` quote: an accept attempted against a `SUPERSEDED` or `EXPIRED` quote is rejected with `ERR_INVALID_STATE`, while an accept against an already-`ACCEPTED` quote — like any action on a terminal quote — is rejected with `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/new_draft_quote_supersedes_existing_draft
    """
    create_config(api)
    v = _variety(api)
    c = create_customer(api)
    q1 = create_quote(api, c["id"], _two_pallet_lines(v["id"]), 1, 1, 0)
    q2 = create_quote(
        api, c["id"],
        [factories.quote_line(v["id"], "ECONOMY", 2)],
        2, 0, 0,
        delivery_date="2026-08-04",
        settlement_method="CASH_CHECK",
    )

    q1_after = validate_success(api.get_quote(q1["id"], SALES), 200)
    assert q1_after["status"] == "SUPERSEDED"
    assert q1_after["superseded_by_id"] == q2["id"]
    q2_after = validate_success(api.get_quote(q2["id"], SALES), 200)
    assert q2_after["status"] == "DRAFT"

    # Per PRD §3.4, accepting a SUPERSEDED quote is rejected ERR_INVALID_STATE.
    resp = api.accept_quote(q1["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


# ---------------------------------------------------------------------------
# Corner: state_machines / quote_accept_after_delivery_date_returns_quote_expired
# ---------------------------------------------------------------------------

def test_quote_accept_after_delivery_date_returns_quote_expired(api):
    """PRD §3.4: "If the quote's `delivery_date` has fallen behind the clock's current date, the accept attempt flips the quote to `EXPIRED` and is rejected with `ERR_QUOTE_EXPIRED`."

    Design: Corner/state_machines/quote_accept_after_delivery_date_returns_quote_expired
    """
    create_config(api)
    v = _variety(api)
    c = create_customer(api)
    q = create_quote(api, c["id"], _two_pallet_lines(v["id"]), 1, 1, 0,
                     delivery_date="2026-08-02")

    # Advance the logical clock past the delivery date (PRD §2.5).
    from test_helpers import set_clock
    set_clock(api, "2026-08-03T00:30:00Z")

    resp = api.accept_quote(q["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED, 409)
    q_after = validate_success(api.get_quote(q["id"], SALES), 200)
    assert q_after["status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Corner: validations / quote_delivery_date_in_past_rejected
# ---------------------------------------------------------------------------

def test_quote_delivery_date_in_past_rejected(api):
    """PRD §3.4: "A `SalesRep` prices a prospective order by creating a quote with the `customer_id`, the requested `delivery_date` (which must not be earlier than the clock's current date, else `ERR_DELIVERY_DATE_TOO_SOON`), the `settlement_method` (`CARD` or `CASH_CHECK`), the planned route mix `z1_pallets`, `z2_pallets`, and `z3_pallets` (each zero or more), and the merchandise `lines`."
    PRD §2.5: "Before it has ever been set, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time."

    Design: Corner/validations/quote_delivery_date_in_past_rejected
    """
    create_config(api)
    v = _variety(api)
    c = create_customer(api)
    resp = api.create_quote(
        factories.create_quote_payload(
            c["id"], _two_pallet_lines(v["id"]), 1, 1, 0,
            delivery_date="2026-07-31",
        ),
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_DELIVERY_DATE_TOO_SOON, 422)


# ---------------------------------------------------------------------------
# Corner: validations / zone_split_must_sum_to_total_pallets
# ---------------------------------------------------------------------------

def test_zone_split_must_sum_to_total_pallets(api):
    """PRD §3.4: "The quote's `total_pallets` is the sum of the per-line pallet counts, and the route mix must reconcile with it — if the three zone counts do not sum to `total_pallets`, creation is rejected with `ERR_ZONE_SPLIT_MISMATCH`."

    Design: Corner/validations/zone_split_must_sum_to_total_pallets
    """
    create_config(api)
    v = _variety(api)
    c = create_customer(api)
    resp = api.create_quote(
        factories.create_quote_payload(
            c["id"],
            [factories.quote_line(v["id"], "PREMIUM", 16)],
            5, 5, 0,  # 10 != 16 pallets from the lines
        ),
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_ZONE_SPLIT_MISMATCH, 422)


# ---------------------------------------------------------------------------
# Corner: endpoints / list_pagination_limit_offset
# ---------------------------------------------------------------------------

def test_list_quotes_paginates_with_limit_and_offset(api):
    """PRD §2.3: "List endpoints accept two query parameters. `limit` caps the number of returned items: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The server stamps `created_at` at millisecond precision and guarantees uniqueness per row, so ties cannot occur and the ordering is total."
    PRD §2.3: "List responses include four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_pagination_limit_offset
    """
    create_config(api)
    v = _variety(api)
    c = create_customer(api)
    q1 = create_quote(api, c["id"], _two_pallet_lines(v["id"]), 1, 1, 0,
                      delivery_date="2026-08-03")
    q2 = create_quote(api, c["id"], _two_pallet_lines(v["id"]), 1, 1, 0,
                      delivery_date="2026-08-04")
    q3 = create_quote(api, c["id"], _two_pallet_lines(v["id"]), 1, 1, 0,
                      delivery_date="2026-08-05")

    page1, meta1 = validate_paginated(
        api.list_quotes(SALES, params={"customer_id": c["id"], "limit": 2, "offset": 0})
    )
    assert [row["id"] for row in page1] == [q1["id"], q2["id"]], (
        "page 1 returns the two oldest quotes in created_at ascending order"
    )
    assert meta1["has_more"] is True
    assert meta1["total_count"] == 3
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_quotes(SALES, params={"customer_id": c["id"], "limit": 2, "offset": 2})
    )
    assert [row["id"] for row in page2] == [q3["id"]]
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 3


# ---------------------------------------------------------------------------
# Corner: entities / get_order_not_found_returns_404
# ---------------------------------------------------------------------------

def test_get_order_not_found_returns_404(api):
    """PRD §2.10: "Paths that address a sub-resource are validated left-to-right: the server resolves the first identifier, then the next, and rejects with `ERR_NOT_FOUND` (404) at the first identifier that does not exist, never reaching deeper validations."
    PRD §2.9: "3. **Existence** — path identifiers resolve left-to-right, and body references (`customer_id`, `variety_id`, `field_id`, `crew_id`, and each quote line's `variety_id`) resolve; otherwise `ERR_NOT_FOUND`."

    Design: Corner/entities/get_order_not_found_returns_404
    """
    resp = api.get_order(NON_EXISTENT_UUID, SALES)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
