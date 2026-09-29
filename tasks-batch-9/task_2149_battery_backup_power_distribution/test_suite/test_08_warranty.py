"""Warranty adjudication and settlement."""
import pytest

from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    create_account, create_battery_model, create_warranty_claim,
    adjudicate_warranty_claim, read_warranty_claim,
)

REP = TEST_USERS["sales_rep_headers"]


def _account_and_flooded_model():
    account = create_account(name="Alamo Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=9)
    model = create_battery_model("IB-31-FLD")
    return account, model


def test_failure_on_the_exact_free_band_anniversary_pays_the_full_list_price():
    """PRD §3.7: "When the service age is **at most** the model's
    `warranty_free_replacement_months`, the claim moves `SUBMITTED →
    APPROVED_FREE`, `coverage_band` becomes `FREE` and `credit_cents` becomes
    the model's full `list_price_cents` with no pro-ration at all. The
    comparison is inclusive, so a claim landing exactly on the free-band
    anniversary month is a full replacement."
    PRD §3.7: "The `months_in_service` is a whole anniversary-month count: take
    the difference in calendar years between the failure date and the
    installation date and multiply it by twelve, add the difference in calendar
    month numbers, and then subtract one if the failure date's day of month is
    earlier than the installation date's day of month — so a unit installed on
    the 15th and failing on the 14th thirteen months later has served twelve
    months, not thirteen."

    Design: Difficulty/boundary_precision_check/warranty_free_band_includes_the_exact_anniversary_month
    """
    account, model = _account_and_flooded_model()
    claim = create_warranty_claim(account["id"], model["id"], "SN-BND-ON",
                                  installed_on="2024-08-15", failed_on="2025-08-15")

    adjudicated = adjudicate_warranty_claim(claim["id"])
    assert adjudicated["months_in_service"] == 12, \
        f"Expected 12 months, got {adjudicated['months_in_service']}"
    assert adjudicated["coverage_band"] == "FREE"
    assert adjudicated["status"] == "APPROVED_FREE"
    assert adjudicated["credit_cents"] == 18500, \
        f"A free replacement pays the whole list price, got {adjudicated['credit_cents']}"


def test_one_month_past_the_free_band_pays_a_pro_rated_credit():
    """PRD §3.7: "When the service age is strictly greater than the free band
    but strictly less than the free band plus the model's
    `warranty_prorata_months`, the claim moves `SUBMITTED → APPROVED_PRORATA`,
    `coverage_band` becomes `PRORATA`, and the credit is pro-rated: count the
    whole months remaining in the pro-rata band as the free band plus the
    pro-rata band minus the service age, multiply the model's
    `list_price_cents` by that remaining count, divide by the
    `warranty_prorata_months` alone — the denominator is the pro-rata band's own
    length, **not** the sum of the two bands — and round half up to whole
    cents."
    PRD §3.7: "At exactly one month past the free band this pays strictly less
    than a free replacement for the same list price; a single month of service
    separates the two bands."

    Design: Difficulty/boundary_precision_check/warranty_free_band_includes_the_exact_anniversary_month
    """
    account, model = _account_and_flooded_model()
    claim = create_warranty_claim(account["id"], model["id"], "SN-BND-OVER",
                                  installed_on="2024-08-15", failed_on="2025-09-15")

    adjudicated = adjudicate_warranty_claim(claim["id"])
    assert adjudicated["months_in_service"] == 13, \
        f"Expected 13 months, got {adjudicated['months_in_service']}"
    assert adjudicated["coverage_band"] == "PRORATA"
    assert adjudicated["status"] == "APPROVED_PRORATA"
    assert adjudicated["credit_cents"] == 17729, \
        f"Expected 17729, got {adjudicated['credit_cents']}"


def test_reusing_a_serial_number_on_a_second_claim_is_refused(api):
    """PRD §3.7: "A serial number may be claimed only once across the whole
    system; a repeat is refused with `ERR_DUPLICATE_SERIAL_NUMBER` (HTTP 409)."
    PRD §3.7: "A new claim opens with `status` at `SUBMITTED`, and its
    `months_in_service` and `credit_cents` stay at 0 until it is adjudicated."

    Design: Corner/entities/duplicate_warranty_serial_number_returns_duplicate_serial_number
    """
    from test_helpers import validate_paginated
    account, model = _account_and_flooded_model()
    first = create_warranty_claim(account["id"], model["id"], "SN-DUP-1",
                                  installed_on="2025-01-10", failed_on="2025-06-10")
    assert first["status"] == "SUBMITTED"
    assert first["credit_cents"] == 0

    resp = api.create_warranty_claim({
        "account_id": account["id"], "battery_model_id": model["id"],
        "serial_number": "SN-DUP-1", "installed_on": "2025-02-10",
        "failed_on": "2025-07-10",
    }, REP)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL_NUMBER.value)

    _rows, meta = validate_paginated(api.list_warranty_claims(
        REP, params={"account_id": account["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, f"The repeat created nothing, got {meta['total_count']}"


def test_settling_as_account_credit_raises_the_warranty_credit_balance(api):
    """PRD §3.7: "Choosing `ACCOUNT_CREDIT` adds the claim's `credit_cents` to
    the account's `warranty_credit_cents`, where it becomes credit-limit
    headroom on the next order submission, and leaves `replacement_order_id`
    null."
    PRD §3.7: "Settlement is available on a claim standing in `APPROVED_FREE` or
    in `APPROVED_PRORATA` — never on one already denied — and the caller chooses
    a `settlement_mode` of either `ACCOUNT_CREDIT` or `REPLACEMENT_ORDER`. The
    two branches are disjoint and both move the claim to `SETTLED`."

    Design: Corner/state_machines/warranty_settle_account_credit_raises_warranty_credit_balance
    """
    from test_helpers import settle_warranty_claim, read_account, validate_paginated
    account, model = _account_and_flooded_model()
    claim = create_warranty_claim(account["id"], model["id"], "SN-CRED-1",
                                  installed_on="2025-01-10", failed_on="2025-06-10")
    adjudicated = adjudicate_warranty_claim(claim["id"])
    assert adjudicated["months_in_service"] == 5
    assert adjudicated["coverage_band"] == "FREE"
    assert adjudicated["credit_cents"] == 18500

    settled = settle_warranty_claim(claim["id"], "ACCOUNT_CREDIT")
    assert settled["status"] == "SETTLED"
    assert settled["replacement_order_id"] is None
    assert read_account(account["id"])["warranty_credit_cents"] == 18500

    _rows, meta = validate_paginated(api.list_orders(
        REP, params={"account_id": account["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, "The credit branch synthesizes no order"


def test_settling_as_a_replacement_order_synthesizes_a_draft_order_and_line(api):
    """PRD §3.7: "Choosing `REPLACEMENT_ORDER` requires a
    `replacement_warehouse_id` in the body naming a real warehouse; the platform
    synthesizes a fresh `DRAFT` order for the claiming account at that warehouse
    with a `requested_ship_date` equal to the current logical-clock date,
    attaches to it exactly one line of `quantity` 1 with `core_expected_count`
    1, and writes the new order's id into the claim's `replacement_order_id`."
    PRD §3.7: "The replacement branch does **not** touch the account's
    `warranty_credit_cents`; a claimant is paid once, either in credit or in
    goods."

    Design: Corner/state_machines/warranty_settle_replacement_order_synthesizes_draft_order_and_line
    """
    from test_helpers import (create_warehouse, settle_warranty_claim, read_account,
                              read_order, validate_paginated)
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account, model = _account_and_flooded_model()
    claim = create_warranty_claim(account["id"], model["id"], "SN-REPL-1",
                                  installed_on="2025-01-10", failed_on="2025-06-10")
    adjudicate_warranty_claim(claim["id"])

    settled = settle_warranty_claim(claim["id"], "REPLACEMENT_ORDER",
                                    replacement_warehouse_id=warehouse["id"])
    assert settled["status"] == "SETTLED"
    assert settled["replacement_order_id"] is not None

    order = read_order(settled["replacement_order_id"])
    assert order["fulfillment_status"] == "DRAFT"
    assert order["credit_status"] == "PENDING"
    assert order["account_id"] == account["id"]
    assert order["warehouse_id"] == warehouse["id"]
    assert order["line_count"] == 1

    lines, _meta = validate_paginated(api.list_order_lines(
        REP, params={"order_id": order["id"], "limit": 10, "offset": 0}))
    assert len(lines) == 1
    assert lines[0]["battery_model_id"] == model["id"]
    assert lines[0]["quantity"] == 1
    assert lines[0]["core_expected_count"] == 1
    assert read_account(account["id"])["warranty_credit_cents"] == 0


def test_a_claim_past_both_bands_is_denied_with_no_credit():
    """PRD §3.7: "When the service age reaches or exceeds the free band plus the
    pro-rata band, the claim moves `SUBMITTED → DENIED`, `coverage_band` becomes
    `EXPIRED` and `credit_cents` becomes 0."
    PRD §3.7: "The three bands are then decided against the model's own warranty
    terms, and each writes `months_in_service`, a `coverage_band` and a
    `credit_cents`."

    Design: Corner/calculations/warranty_claim_past_both_bands_is_denied_with_zero_credit
    """
    from test_helpers import read_account
    account, model = _account_and_flooded_model()
    claim = create_warranty_claim(account["id"], model["id"], "SN-EXP-1",
                                  installed_on="2022-01-10", failed_on="2025-01-10")

    adjudicated = adjudicate_warranty_claim(claim["id"])
    assert adjudicated["months_in_service"] == 36
    assert adjudicated["coverage_band"] == "EXPIRED"
    assert adjudicated["credit_cents"] == 0
    assert adjudicated["status"] == "DENIED"
    assert read_account(account["id"])["warranty_credit_cents"] == 0
