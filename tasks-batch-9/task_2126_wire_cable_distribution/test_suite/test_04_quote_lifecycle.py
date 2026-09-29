"""The quote lifecycle: draft, issue, reprice, convert and expiry.

Also the stale-version guard on line-add, the segregation-of-duties control
and the two credit gates on conversion.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    PRODUCT_P1,
    PRODUCT_P3,
    PRODUCT_P4,
    add_line,
    build_quote,
    create_branch,
    create_customer,
    create_product,
    create_quote_line_payload,
    create_quote_payload,
    issue_quote,
    list_orders,
    list_quote_lines,
    make_sales_rep_headers,
    open_quote,
    publish_index,
    read_customer,
    read_quote,
    read_quote_line,
    set_clock,
    validate_error,
    validate_success,
)

REP_1 = make_sales_rep_headers("rep-1")
REP_2 = make_sales_rep_headers("rep-2")


def test_new_quote_is_draft_with_nothing_pinned(api):
    """PRD §3.3: "A new quote is born in `DRAFT` status with
    `created_by_user_id` set to the acting operator's identifier,
    `copper_index_entry_id` null, `issued_at`, `valid_until`,
    `issued_by_user_id` and `void_reason` all null, and every money field —
    `line_subtotal_cents`, `physical_reel_count`, `gross_freight_cents`,
    `rebate_pct`, `rebate_cents`, `freight_cents`, `quoted_total_cents` and
    `deposit_quoted_cents` — at 0."

    Design: Corner/state_machines/quote_initial_state_is_draft_with_no_pinned_index
    """
    branch = create_branch()
    customer = create_customer()

    response = api.create_quote(
        create_quote_payload(customer["id"], branch["id"]), REP_1
    )
    quote = validate_success(response, 201)

    assert quote["status"] == "DRAFT"
    assert quote["copper_index_entry_id"] is None
    assert quote["issued_at"] is None
    assert quote["valid_until"] is None
    assert quote["issued_by_user_id"] is None
    assert quote["void_reason"] is None
    assert quote["created_by_user_id"] == "rep-1"
    assert quote["line_subtotal_cents"] == 0
    assert quote["quoted_total_cents"] == 0


def test_issuing_an_already_issued_quote_is_rejected(api):
    """PRD §3.4: "It moves the quote `DRAFT → ISSUED` and is available only
    while the quote is `DRAFT`; an attempt against any other status is
    rejected with `ERR_QUOTE_NOT_DRAFT`."

    Design: Corner/state_machines/issue_on_already_issued_quote_returns_quote_not_draft
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    index = publish_index("2026-07-30", 450)
    quote, _ = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 300}],
    )
    issue_quote(quote["id"], issuer="rep-2")

    response = api.issue_quote(quote["id"], REP_2)

    validate_error(response, ApiErrorId.ERR_QUOTE_NOT_DRAFT.value)
    refreshed = read_quote(quote["id"])
    assert refreshed["status"] == "ISSUED"
    assert refreshed["copper_index_entry_id"] == index["id"]
    assert refreshed["quoted_total_cents"] == 21588


def test_repricing_a_draft_quote_is_rejected(api):
    """PRD §3.5: "A `SalesRep` facing a customer who took a week to decide
    reopens the offer by repricing it, which moves the quote `ISSUED → DRAFT`
    and is available only from `ISSUED`; from any other status it is refused
    with `ERR_QUOTE_NOT_ISSUED`."

    Design: Corner/state_machines/reprice_on_draft_quote_returns_quote_not_issued
    """
    branch = create_branch()
    customer = create_customer()
    quote = open_quote(customer["id"], branch["id"])

    response = api.reprice_quote(quote["id"], REP_1)

    validate_error(response, ApiErrorId.ERR_QUOTE_NOT_ISSUED.value)
    assert read_quote(quote["id"])["status"] == "DRAFT"


def test_issuing_a_quote_with_no_lines_is_rejected(api):
    """PRD §3.4: "A quote with zero lines cannot be issued and is rejected
    with `ERR_QUOTE_HAS_NO_LINES`."

    Design: Corner/state_machines/issue_quote_with_zero_lines_returns_quote_has_no_lines
    """
    branch = create_branch()
    customer = create_customer()
    publish_index("2026-07-30", 450)
    quote = open_quote(customer["id"], branch["id"])

    response = api.issue_quote(quote["id"], REP_2)

    validate_error(response, ApiErrorId.ERR_QUOTE_HAS_NO_LINES.value)
    refreshed = read_quote(quote["id"])
    assert refreshed["status"] == "DRAFT"
    assert refreshed["copper_index_entry_id"] is None


def test_issuing_without_a_current_settlement_is_rejected(api):
    """PRD §3.4: "Issue also requires a market to price against: if no copper
    index entry exists whose `effective_date` is on or before the current
    logical date, the request fails with `ERR_NO_COPPER_INDEX`."
    PRD §2.5: "Before any call to the clock-setting capability, the logical
    clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to real
    wall-clock time."

    Design: Corner/state_machines/issue_without_any_published_index_returns_no_copper_index
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-09-01", 450)
    quote, _ = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 300}],
    )

    response = api.issue_quote(quote["id"], REP_2)

    validate_error(response, ApiErrorId.ERR_NO_COPPER_INDEX.value)
    assert read_quote(quote["id"])["status"] == "DRAFT"


def test_conversion_at_valid_until_succeeds_and_one_second_later_expires(api):
    """PRD §3.5: "The current logical instant must be at or before
    `valid_until` — the upper bound is inclusive, so a conversion at exactly
    the expiry instant still succeeds."
    PRD §3.5: "When a conversion arrives after `valid_until` has passed, the
    same request moves the quote `ISSUED → EXPIRED` and then fails with
    `ERR_QUOTE_EXPIRED`; no sales order is created, and the quote's `version`
    still advances because the quote itself changed."
    PRD §3.4: "A successful issue stamps `issued_at` with the current logical
    instant, sets `valid_until` to twenty-four hours after `issued_at`,
    records the acting operator in `issued_by_user_id`, and advances the
    quote's `version`."

    Design: Corner/state_machines/convert_at_valid_until_succeeds_and_one_second_later_expires_the_quote
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    line_spec = [{"put_up": "CUT", "requested_length_ft": 300}]
    quote_a, _ = build_quote(
        customer["id"], branch["id"], product["id"], line_spec
    )
    issue_quote(quote_a["id"], issuer="rep-2")
    quote_b, _ = build_quote(
        customer["id"], branch["id"], product["id"], line_spec
    )
    issue_quote(quote_b["id"], issuer="rep-2")

    assert_same_instant(
        read_quote(quote_a["id"])["valid_until"], "2026-08-02T00:00:00Z",
        "Quote.valid_until",
    )

    set_clock("2026-08-02T00:00:00Z")
    on_time = api.convert_quote(quote_a["id"], REP_2)
    order = validate_success(on_time, 201)
    assert read_quote(quote_a["id"])["status"] == "CONVERTED"
    assert order["fulfillment_status"] == "PENDING_ALLOCATION"

    set_clock("2026-08-02T00:00:01Z")
    late = api.convert_quote(quote_b["id"], REP_2)

    validate_error(late, ApiErrorId.ERR_QUOTE_EXPIRED.value)
    assert read_quote(quote_b["id"])["status"] == "EXPIRED"
    assert list_orders(quote_id=quote_b["id"]) == []


def test_reprice_cycle_repins_the_index_that_is_current_at_reissue(api):
    """PRD §3.5: "Repricing takes no request body and is a deliberate erasure:
    `copper_index_entry_id`, `issued_at`, `valid_until` and
    `issued_by_user_id` are all cleared back to null, and
    `line_subtotal_cents`, `gross_freight_cents`, `rebate_pct`,
    `rebate_cents`, `freight_cents`, `quoted_total_cents` and
    `deposit_quoted_cents` are all zeroed, as is every money field on every
    one of the quote's lines."
    PRD §3.4: "Given a market, the quote pins one entry into
    `copper_index_entry_id`: the entry with the greatest `effective_date` that
    is on or before the current logical date."

    Design: Corner/state_machines/reprice_cycle_clears_pinned_index_then_reissue_pins_the_current_one
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    quote, lines = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 300}],
    )
    issue_quote(quote["id"], issuer="rep-2")
    newer_index = publish_index("2026-08-03", 460)
    set_clock("2026-08-04T00:00:00Z")

    validate_success(api.reprice_quote(quote["id"], REP_1), 200)
    drafted = read_quote(quote["id"])
    assert drafted["status"] == "DRAFT"
    assert drafted["copper_index_entry_id"] is None
    assert drafted["quoted_total_cents"] == 0

    validate_success(api.issue_quote(quote["id"], REP_2), 200)

    reissued = read_quote(quote["id"])
    line = read_quote_line(lines[0]["id"])
    assert reissued["status"] == "ISSUED"
    assert reissued["copper_index_entry_id"] == newer_index["id"]
    assert_same_instant(
        reissued["valid_until"], "2026-08-05T00:00:00Z", "Quote.valid_until"
    )
    assert line["copper_adder_cents_per_ft"] == pytest.approx(5.7500, abs=5e-5)
    assert line["metal_cents"] == 1725
    assert line["quoted_extended_cents"] == 10625
    assert reissued["quoted_total_cents"] == 21625


def test_segregation_of_duties_blocks_self_issue_at_exactly_the_threshold(api):
    """PRD §2.9: "When that freshly computed subtotal reaches 250,000 cents
    (2,500 dollars) or more, the issuing operator's `X-User-ID` must differ
    from the quote's `created_by_user_id`; below that threshold a rep may
    issue their own quote."
    PRD §3.4: "When that computed subtotal is at or above 250,000 cents, the
    acting `X-User-ID` must differ from `created_by_user_id`, otherwise the
    issue is refused with `ERR_SEGREGATION_OF_DUTIES` and nothing is written."

    Design: Corner/validations/segregation_of_duties_blocks_self_issue_at_exactly_the_threshold
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P3)
    publish_index("2026-07-30", 450)
    quote, _ = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 2500}],
        creator="rep-1",
    )

    self_issue = api.issue_quote(quote["id"], REP_1)
    validate_error(self_issue, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    validate_success(api.issue_quote(quote["id"], REP_2), 200)

    refreshed = read_quote(quote["id"])
    assert refreshed["status"] == "ISSUED"
    assert refreshed["line_subtotal_cents"] == 250000
    assert refreshed["rebate_cents"] == 3750
    assert refreshed["quoted_total_cents"] == 257250
    assert refreshed["created_by_user_id"] == "rep-1"
    assert refreshed["issued_by_user_id"] == "rep-2"


def test_conversion_beyond_available_credit_is_rejected(api):
    """PRD §3.5: "And the customer's `available_credit_cents` must be at least
    the quote's `quoted_total_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`."
    PRD §3.1: "and `available_credit_cents` is always the credit limit less
    the open balance, a figure that is explicitly permitted to go negative."

    Design: Corner/validations/credit_limit_exceeded_blocks_conversion
    """
    branch = create_branch()
    customer = create_customer(name="Thin Credit LLC", credit_limit_cents=10_000)
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    quote, _ = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 300}],
    )
    issue_quote(quote["id"], issuer="rep-2")

    response = api.convert_quote(quote["id"], REP_2)

    validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)
    account = read_customer(customer["id"])
    assert account["credit_status"] == "ACTIVE"
    assert account["available_credit_cents"] == 10000
    assert read_quote(quote["id"])["status"] == "ISSUED"
    assert list_orders(quote_id=quote["id"]) == []


def test_put_up_outside_the_parts_allowed_list_is_rejected(api):
    """PRD §3.3: "A line whose requested `put_up` is not a member of the
    part's `allowed_put_ups` is rejected with `ERR_PUT_UP_NOT_ALLOWED`, and a
    `CUT` line asking for fewer than 25 feet per conductor is rejected with
    `ERR_BELOW_ABSOLUTE_MIN_CUT` — below that length a run cannot be safely
    terminated."

    Design: Corner/validations/put_up_not_in_product_catalog_is_rejected
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(
        PRODUCT_P1, part_number="CU-CUTONLY", allowed_put_ups=["CUT"]
    )
    publish_index("2026-07-30", 450)
    quote = open_quote(customer["id"], branch["id"])

    response = api.create_quote_line(
        quote["id"],
        create_quote_line_payload(
            product["id"], quote["version"],
            put_up="MASTER_REEL", requested_length_ft=2500,
        ),
        REP_1,
    )

    validate_error(response, ApiErrorId.ERR_PUT_UP_NOT_ALLOWED.value)
    assert list_quote_lines(quote_id=quote["id"]) == []


def test_stale_expected_quote_version_on_line_add_is_rejected(api):
    """PRD §2.8: "Adding a line to a quote requires `expected_quote_version`
    as a non-optional field of the request body, carrying the client's last
    observed `version` of the target `Quote`. If that value does not equal the
    quote's current `version`, the request is rejected with
    `ERR_STALE_QUOTE_VERSION` (HTTP 412) and no line is created."
    PRD §3.3: "Each line receives a `line_number` assigned as one more than
    the count of lines already on the quote, so numbering is 1-based and
    follows creation order; that number is what fixes allocation processing
    order later."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_quote_version_on_line_add_returns_412
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    quote = open_quote(customer["id"], branch["id"])
    stale_version = quote["version"]
    add_line(
        quote["id"], product["id"], put_up="CUT", requested_length_ft=300,
        expected_quote_version=stale_version,
    )

    stale = api.create_quote_line(
        quote["id"],
        create_quote_line_payload(
            product["id"], stale_version, put_up="CUT", requested_length_ft=400
        ),
        REP_1,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_QUOTE_VERSION.value)

    current_version = read_quote(quote["id"])["version"]
    retry = api.create_quote_line(
        quote["id"],
        create_quote_line_payload(
            product["id"], current_version, put_up="CUT", requested_length_ft=400
        ),
        REP_1,
    )
    second_line = validate_success(retry, 201)

    assert second_line["line_number"] == 2
    assert len(list_quote_lines(quote_id=quote["id"])) == 2


def test_cut_line_of_exactly_twenty_five_feet_is_accepted(api):
    """PRD §3.3: "A line whose requested `put_up` is not a member of the
    part's `allowed_put_ups` is rejected with `ERR_PUT_UP_NOT_ALLOWED`, and a
    `CUT` line asking for fewer than 25 feet per conductor is rejected with
    `ERR_BELOW_ABSOLUTE_MIN_CUT` — below that length a run cannot be safely
    terminated."
    PRD §3.3: "For a `CUT` line, `billable_length_ft` is the greater of
    `requested_length_ft` and the part's `min_cut_length_ft` — a customer
    asking for less than the billing minimum is billed at the minimum — and
    `reel_count` is exactly 1, representing the single disposable shipping
    reel the cut travels on."

    Design: Difficulty/boundary_precision_check/absolute_min_cut_ft_boundary_at_exactly_25
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P4)
    publish_index("2026-07-30", 450)
    quote = open_quote(customer["id"], branch["id"])

    response = api.create_quote_line(
        quote["id"],
        create_quote_line_payload(
            product["id"], quote["version"], put_up="CUT", requested_length_ft=25
        ),
        REP_1,
    )
    line = validate_success(response, 201)

    assert line["billable_length_ft"] == 25
    assert line["reel_count"] == 1
    assert line["cut_charge_cents_total"] == 3000


def test_cut_line_of_twenty_four_feet_is_rejected(api):
    """PRD §2.7: "A `CUT` line requests at least 25 feet per conductor —
    otherwise `ERR_BELOW_ABSOLUTE_MIN_CUT` (422), on the quote line-add
    endpoint."
    PRD §3.3: "A line whose requested `put_up` is not a member of the part's
    `allowed_put_ups` is rejected with `ERR_PUT_UP_NOT_ALLOWED`, and a `CUT`
    line asking for fewer than 25 feet per conductor is rejected with
    `ERR_BELOW_ABSOLUTE_MIN_CUT` — below that length a run cannot be safely
    terminated."

    Design: Difficulty/boundary_precision_check/absolute_min_cut_ft_boundary_at_exactly_25
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P4)
    publish_index("2026-07-30", 450)
    quote = open_quote(customer["id"], branch["id"])
    add_line(
        quote["id"], product["id"], put_up="CUT", requested_length_ft=25,
        expected_quote_version=quote["version"],
    )
    current_version = read_quote(quote["id"])["version"]

    response = api.create_quote_line(
        quote["id"],
        create_quote_line_payload(
            product["id"], current_version, put_up="CUT", requested_length_ft=24
        ),
        REP_1,
    )

    validate_error(response, ApiErrorId.ERR_BELOW_ABSOLUTE_MIN_CUT.value)
    assert len(list_quote_lines(quote_id=quote["id"])) == 1, (
        "the sub-minimum line is not persisted"
    )
