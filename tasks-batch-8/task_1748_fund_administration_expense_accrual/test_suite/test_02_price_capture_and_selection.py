"""Price capture rules, the valuation-hierarchy selector, and override lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_money,
    assert_nav_record,
    assert_price_observation,
    assert_rate,
    create_fund,
    create_security,
    create_share_class,
    open_position,
    set_logical_clock,
    submit_price,
    approve_price,
    subscribe_shares,
    is_valid_uuid,
    validate_error,
    validate_success,
)

CTRL = TEST_USERS["fund_controller_headers"]
ACCT = TEST_USERS["fund_accountant_headers"]
PC = TEST_USERS["pricing_committee_headers"]


def _kit_with_two_prices():
    """Fund/class (10000 shares) + position qty 1000 + two observations on
    2026-08-04: EXCHANGE_CLOSE LEVEL_1 100.00 left SUBMITTED, and
    PRICING_SERVICE LEVEL_2 99.00 APPROVED."""
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund(
        adviser_fee_tiers=[
            {"up_to_net_assets": 100000000, "rate_bps": 50},
            {"up_to_net_assets": None, "rate_bps": 40},
        ]
    )
    share_class = create_share_class(fund["id"])
    subscribe_shares(share_class["id"], 10000)
    security = create_security()
    position = open_position(share_class["id"], security["id"], quantity=1000)
    submit_price(security["id"], price=100.00, source="EXCHANGE_CLOSE",
                 pricing_level="LEVEL_1")
    px2 = submit_price(security["id"], price=99.00, source="PRICING_SERVICE",
                       pricing_level="LEVEL_2")
    approve_price(px2["id"])
    return fund, share_class, security, position


def test_provisional_variant_selects_submitted_level1(api):
    """PRD §3.3: "The two variants differ only in eligibility: the
    `PROVISIONAL` variant — used while a record is `ESTIMATED` and for the
    `provisional_nav_per_share` preview — admits both `SUBMITTED` and
    `APPROVED` observations, so unapproved quotes are admissible"
    PRD §3.3: "among what remains, the lower pricing level wins — `LEVEL_1`
    beats `LEVEL_2`, which beats `LEVEL_3`"

    Design: Difficulty/dual_variant_calc/nav_provisional_vs_final_pricing_variant
    """
    _, share_class, _, _ = _kit_with_two_prices()
    resp = api.create_nav_record(
        {"share_class_id": share_class["id"], "accounting_date": "2026-08-04"},
        ACCT,
    )
    nav = validate_success(resp, 201)
    assert_nav_record(nav)
    # PROVISIONAL admits the SUBMITTED LEVEL_1 100.00: GAV 1000 x 100.00.
    assert_money(nav["gross_asset_value"], 100000.00, "gross_asset_value")
    assert_rate(nav["nav_per_share"], 10.0000, "nav_per_share")
    assert_rate(nav["provisional_nav_per_share"], 10.0000,
                "provisional_nav_per_share")


def test_final_priced_variant_preview_excludes_submitted(api):
    """PRD §3.3: "the `FINAL_PRICED` variant — used once a record is `FINAL` or
    `REOPENED`, and for the `final_nav_per_share` preview — admits `APPROVED`
    observations only, so identical positions can price differently once
    merely-submitted rows drop out."
    PRD §3.4: "The record's `pricing_variant_used` reads `PROVISIONAL` while
    the record is `ESTIMATED` and `FINAL_PRICED` once it has reached `FINAL`
    or `REOPENED`."

    Design: Difficulty/dual_variant_calc/nav_provisional_vs_final_pricing_variant
    """
    _, share_class, _, _ = _kit_with_two_prices()
    resp = api.create_nav_record(
        {"share_class_id": share_class["id"], "accounting_date": "2026-08-04"},
        ACCT,
    )
    nav = validate_success(resp, 201)
    assert nav["pricing_variant_used"] == "PROVISIONAL"
    # FINAL_PRICED admits only the APPROVED LEVEL_2 99.00: GAV 99000.00,
    # TNA 98999.73 after the 0.27 accrual.
    assert_rate(nav["final_nav_per_share"], 9.9000, "final_nav_per_share")
    assert_money(nav["expense_accrual_total"], 0.27, "expense_accrual_total")


def test_price_selection_latest_created_at_wins_tie(api):
    """PRD §3.3: "and within an identical level, the most recently created
    observation wins. An observation's `id` is never consulted in selection,
    ranking, or tie-breaking."

    Design: Corner/calculations/price_selection_latest_created_at_wins_tie
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    subscribe_shares(share_class["id"], 10000)
    security = create_security()
    open_position(share_class["id"], security["id"], quantity=1000)
    px_a = submit_price(security["id"], price=100.00, source="EXCHANGE_CLOSE",
                        pricing_level="LEVEL_1")
    approve_price(px_a["id"])
    set_logical_clock("2026-08-04T00:01:00Z")
    px_b = submit_price(security["id"], price=101.00, source="PRICING_SERVICE",
                        pricing_level="LEVEL_1")
    approve_price(px_b["id"])

    resp = api.create_nav_record(
        {"share_class_id": share_class["id"], "accounting_date": "2026-08-04"},
        ACCT,
    )
    nav = validate_success(resp, 201)
    # Both APPROVED LEVEL_1; the later-created 101.00 observation wins.
    assert_money(nav["gross_asset_value"], 101000.00, "gross_asset_value")
    assert_rate(nav["nav_per_share"], 10.1000, "nav_per_share")


def test_price_future_date_rejected(api):
    """PRD §3.2: "The `price_date` must not lie after the logical clock date —
    a future-dated price is rejected with `ERR_PRICE_DATE_FUTURE` (HTTP 422)."

    Design: Corner/validations/price_future_date_rejected
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    security = create_security()
    future = api.create_price_observation(
        {"security_id": security["id"], "price_date": "2026-08-05",
         "price": 100.00, "source": "EXCHANGE_CLOSE", "pricing_level": "LEVEL_1"},
        ACCT,
    )
    validate_error(future, ApiErrorId.ERR_PRICE_DATE_FUTURE, 422)

    same_day = api.create_price_observation(
        {"security_id": security["id"], "price_date": "2026-08-04",
         "price": 100.00, "source": "EXCHANGE_CLOSE", "pricing_level": "LEVEL_1"},
        ACCT,
    )
    obs = validate_success(same_day, 201)
    assert_price_observation(obs)
    assert is_valid_uuid(obs["id"])


def test_duplicate_price_source_rejected(api):
    """PRD §3.2: "At most one observation that has not been `OVERRIDDEN` may
    exist for a given security, date, and source; a second live observation for
    the same triple is rejected with `ERR_DUPLICATE_PRICE_SOURCE` (HTTP 409)."

    Design: Corner/validations/duplicate_price_source_rejected
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    security = create_security()
    submit_price(security["id"], price=100.00, source="EXCHANGE_CLOSE")

    dup = api.create_price_observation(
        {"security_id": security["id"], "price_date": "2026-08-04",
         "price": 100.50, "source": "EXCHANGE_CLOSE", "pricing_level": "LEVEL_1"},
        ACCT,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_PRICE_SOURCE, 409)

    other_source = api.create_price_observation(
        {"security_id": security["id"], "price_date": "2026-08-04",
         "price": 100.50, "source": "BROKER_QUOTE", "pricing_level": "LEVEL_2"},
        ACCT,
    )
    obs = validate_success(other_source, 201)
    assert is_valid_uuid(obs["id"])


def test_override_source_reserved_rejected(api):
    """PRD §3.2: "the `FAIR_VALUE_COMMITTEE` source is reserved to the
    fair-value override flow, and a manual create naming it is rejected with
    `ERR_OVERRIDE_SOURCE_RESERVED` (HTTP 422)."

    Design: Corner/validations/override_source_reserved_rejected
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    security = create_security()
    resp = api.create_price_observation(
        {"security_id": security["id"], "price_date": "2026-08-04",
         "price": 100.00, "source": "FAIR_VALUE_COMMITTEE",
         "pricing_level": "LEVEL_3"},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_OVERRIDE_SOURCE_RESERVED, 422)


def test_price_override_terminal_lockdown(api):
    """PRD §3.3: "The fair-value override is the committee's heavier instrument
    and may be applied to an observation in either `SUBMITTED` or `APPROVED`
    status."
    PRD §2.9: "State eligibility of the target resource for the requested
    transition — `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/price_override_terminal_lockdown
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    security = create_security()
    obs = submit_price(security["id"], price=100.00)
    first = api.override_price_observation(
        obs["id"], {"override_price": 101.00, "pricing_level": "LEVEL_3"}, PC
    )
    replacement = validate_success(first, 201)
    assert replacement["source"] == "FAIR_VALUE_COMMITTEE"

    second = api.override_price_observation(
        obs["id"], {"override_price": 102.00, "pricing_level": "LEVEL_3"}, PC
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE, 409)
