"""Quote drafting, the seven pricing steps, the deposit branches and the quote lifecycle."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_quote,
    assert_same_instant,
    draft_quote,
    instrument_version,
    issue_quote,
    make_client_headers,
    read_instrument,
    set_clock,
    set_condition,
    setup_client_with_instrument,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]


def test_dealer_tune_quote_rounds_each_line_before_summing(api):
    """PRD 3.5: "*Step three*: **each line** is multiplied by one minus that percentage
    and rounded half up to whole cents **individually**, and only then are the rounded
    line amounts summed; `line_discount_cents` is `base_price_cents` less that sum.
    Summing the lines first and rounding the discounted total once is wrong and can
    differ by a cent."
    PRD 3.5: "*Step two*: the discount percentage is read off the client. A `DEALER`
    client sets `pricing_variant` to `DEALER_NET` at 18 percent off; an `INSTITUTION`
    client sets it to `INSTITUTIONAL` at 8 percent off; anyone else sets it to `RETAIL`
    at 0 percent off, so a retail line's net equals its base and `line_discount_cents`
    comes out at 0."
    PRD 3.5: "*Step four*: a zone surcharge is read from the zone of the instrument's
    current location — 0 cents in `ZONE_A`, 4500 cents in `ZONE_B`, 11000 cents in
    `ZONE_C` — and stored as `zone_surcharge_cents`. *Step five*: `subtotal_cents` is
    the sum of the net line amounts plus the zone surcharge."

    Design: Difficulty/combinatorial_formula/quote_per_line_rounding_before_sum
    """
    base = setup_client_with_instrument(
        client_type="DEALER", zone_code="ZONE_B", instrument_class="GRAND",
        usage_tier="STUDIO", deviation=-20.0,
    )
    quote = draft_quote(base["instrument"]["id"], "TUNE")

    assert_quote(quote)
    assert quote["pricing_variant"] == "DEALER_NET"
    assert quote["base_price_cents"] == 39150, "26325 for the tune plus 12825 for the raise"
    assert quote["line_discount_cents"] == 7046, (
        "21587 + 10517 = 32104 net; 39150 - 32104 = 7046, not the 7047 that "
        "rounding the discounted total once would give"
    )
    assert quote["zone_surcharge_cents"] == 4500
    assert quote["subtotal_cents"] == 36604
    assert quote["subtotal_cents"] != 36603, "36603 is the sum-then-round answer"
    assert quote["loyalty_discount_cents"] == 0
    assert quote["total_cents"] == 36604


def test_dealer_tune_quote_at_tier_two_acquires_the_pitch_raise_line(api):
    """PRD 3.5: "There is one exception: a `TUNE` quote for an instrument whose
    **effective** `pitch_raise_tier` is `TIER_1`, `TIER_2` or `TIER_3` automatically
    acquires a second line for a pitch raise, and `line_count` becomes 2."
    PRD 3.3: "Above 15.0 and up to and including 35.0 is `TIER_2`."
    PRD 3.5: "*Step one*: each line's undiscounted base is the service's list price
    multiplied by the class multiplier, rounded half up to whole cents. The list prices
    are 19500 cents for a `TUNE`, 9500 for a `PITCH_RAISE`, 85000 for a `REGULATE`,
    42000 for a `VOICE`, and 1450000 for a `REBUILD`. The class multipliers are 1.00 for
    an `UPRIGHT`, 1.05 for a `CONSOLE`, 1.20 for a `BABY_GRAND`, 1.35 for a `GRAND` and
    1.75 for a `CONCERT_GRAND`. The sum of the line bases is `base_price_cents`."

    Design: Difficulty/combinatorial_formula/quote_per_line_rounding_before_sum
    """
    base = setup_client_with_instrument(
        client_type="DEALER", zone_code="ZONE_B", instrument_class="GRAND",
        usage_tier="STUDIO", deviation=-20.0,
    )
    instrument = read_instrument(base["instrument"]["id"])
    assert instrument["raw_pitch_tier"] == "TIER_2"
    assert instrument["pitch_raise_tier"] == "TIER_2", "no recall exists, so no bump"

    quote = draft_quote(instrument["id"], "TUNE")

    assert quote["line_count"] == 2
    assert quote["base_price_cents"] == 39150


def test_loyalty_discount_is_keyed_on_the_subtotal_at_the_boundary(api):
    """PRD 3.5: "The **loyalty discount** is keyed on `subtotal_cents` and never on
    `total_cents`; keying it on the total would be circular, since the total depends on
    the discount. A subtotal of at least 1450000 cents earns 6 percent; a subtotal of at
    least 119250 cents but below 1450000 earns 3 percent; anything below 119250 earns
    nothing. The percentage is applied to `subtotal_cents` and rounded half up to whole
    cents."
    PRD 3.5: "*Step seven*: `total_cents` is `subtotal_cents` less
    `loyalty_discount_cents`."

    Design: Difficulty/combinatorial_formula/loyalty_tier_keyed_on_subtotal_not_on_total
    """
    base = setup_client_with_instrument(
        zone_code="ZONE_B", instrument_class="GRAND", usage_tier="STUDIO",
        climate_controlled=True, deviation=1.5,
    )
    set_condition(base["instrument"]["id"], "SERVICEABLE", "assessed and playable")

    quote = draft_quote(base["instrument"]["id"], "REGULATE")

    assert quote["line_count"] == 1
    assert quote["base_price_cents"] == 114750
    assert quote["line_discount_cents"] == 0, "a retail line's net equals its base"
    assert quote["zone_surcharge_cents"] == 4500
    assert quote["subtotal_cents"] == 119250, "exactly the 3 percent boundary"
    assert quote["loyalty_discount_cents"] == 3578, "3 percent of 119250 rounded half up"
    assert quote["total_cents"] == 115672
    assert quote["deposit_variant"] == "PERCENT_OF_CONTRACT"
    assert quote["deposit_required_cents"] == 28918


def test_the_same_regulate_quote_in_zone_a_earns_no_loyalty_discount(api):
    """PRD 3.5: "The **loyalty discount** is keyed on `subtotal_cents` and never on
    `total_cents`; keying it on the total would be circular, since the total depends on
    the discount. A subtotal of at least 1450000 cents earns 6 percent; a subtotal of at
    least 119250 cents but below 1450000 earns 3 percent; anything below 119250 earns
    nothing. The percentage is applied to `subtotal_cents` and rounded half up to whole
    cents."
    PRD 3.5: "*Step four*: a zone surcharge is read from the zone of the instrument's
    current location — 0 cents in `ZONE_A`, 4500 cents in `ZONE_B`, 11000 cents in
    `ZONE_C` — and stored as `zone_surcharge_cents`."

    Design: Difficulty/combinatorial_formula/loyalty_tier_keyed_on_subtotal_not_on_total
    """
    base = setup_client_with_instrument(
        zone_code="ZONE_A", instrument_class="GRAND", usage_tier="STUDIO",
        climate_controlled=True, deviation=1.5,
    )
    set_condition(base["instrument"]["id"], "SERVICEABLE", "assessed and playable")

    quote = draft_quote(base["instrument"]["id"], "REGULATE")

    assert quote["base_price_cents"] == 114750
    assert quote["zone_surcharge_cents"] == 0
    assert quote["subtotal_cents"] == 114750, "one surcharge short of the boundary"
    assert quote["loyalty_discount_cents"] == 0
    assert quote["total_cents"] == 114750


def test_institution_client_takes_the_net_terms_deposit_branch(api):
    """PRD 3.5: "Otherwise, an `INSTITUTION` client takes the `NET_TERMS` branch: the
    deposit is 10 percent of `total_cents`, rounded half up, with no floor of any kind."
    PRD 3.5: "The deposit percentage for the service class is 0.00 for a `TUNE`, 0.00
    for a `PITCH_RAISE`, 0.25 for a `REGULATE`, 0.25 for a `VOICE` and 0.40 for a
    `REBUILD`."
    PRD 3.5: "*Step two*: the discount percentage is read off the client. A `DEALER`
    client sets `pricing_variant` to `DEALER_NET` at 18 percent off; an `INSTITUTION`
    client sets it to `INSTITUTIONAL` at 8 percent off; anyone else sets it to `RETAIL`
    at 0 percent off, so a retail line's net equals its base and `line_discount_cents`
    comes out at 0."

    Design: Corner/calculations/deposit_net_terms_variant_for_an_institution_client
    """
    base = setup_client_with_instrument(
        client_type="INSTITUTION", instrument_class="UPRIGHT",
        usage_tier="INSTITUTIONAL", deviation=1.0,
    )
    set_condition(base["instrument"]["id"], "SERVICEABLE")

    quote = draft_quote(base["instrument"]["id"], "REGULATE")

    assert quote["pricing_variant"] == "INSTITUTIONAL"
    assert quote["base_price_cents"] == 85000
    assert quote["line_discount_cents"] == 6800
    assert quote["subtotal_cents"] == 78200
    assert quote["total_cents"] == 78200
    assert quote["deposit_variant"] == "NET_TERMS"
    assert quote["deposit_required_cents"] == 7820, "10 percent, with no flat floor"


def test_small_voice_contract_takes_the_flat_minimum_deposit_branch(api):
    """PRD 3.5: "Every other client takes the percentage of `total_cents`, rounded half
    up; if that figure reaches 25000 cents the variant is `PERCENT_OF_CONTRACT` and the
    figure stands, and if it falls short the variant is `FLAT_MINIMUM` and the deposit
    is pinned at 25000 cents regardless of how small the contract is."
    PRD 3.5: "The deposit percentage for the service class is 0.00 for a `TUNE`, 0.00
    for a `PITCH_RAISE`, 0.25 for a `REGULATE`, 0.25 for a `VOICE` and 0.40 for a
    `REBUILD`."

    Design: Corner/calculations/deposit_flat_minimum_variant_on_a_small_voice_contract
    """
    base = setup_client_with_instrument(deviation=1.0)
    set_condition(base["instrument"]["id"], "SERVICEABLE")

    quote = draft_quote(base["instrument"]["id"], "VOICE")

    assert quote["total_cents"] == 42000
    assert quote["deposit_variant"] == "FLAT_MINIMUM"
    assert quote["deposit_required_cents"] == 25000, (
        "25 percent of 42000 is 10500, short of the flat minimum"
    )


def test_voice_quote_on_an_unassessed_instrument_is_refused(api):
    """PRD 3.5: "A `VOICE` quote requires the instrument's `condition_status` to be
    `SERVICEABLE`, `NEEDS_VOICING` or `RESTORED`."
    PRD 3.5: "A `TUNE` or `PITCH_RAISE` quote is permitted from any condition **except**
    `REBUILD_REQUIRED`."
    PRD 3.5: "A violation is refused with `ERR_SERVICE_PREREQUISITE_NOT_MET`."

    Design: Corner/validations/voice_quote_on_an_unassessed_instrument_is_rejected
    """
    base = setup_client_with_instrument(deviation=2.0)
    instrument = base["instrument"]

    response = api.create_quote(
        {
            "instrument_id": instrument["id"],
            "service_type": "VOICE",
            "expected_instrument_version": instrument_version(instrument["id"]),
        },
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_PREREQUISITE_NOT_MET.value)

    tune = draft_quote(instrument["id"], "TUNE")
    assert tune["status"] == "DRAFT", "TUNE is only barred at REBUILD_REQUIRED"


def test_second_issued_quote_for_the_same_service_type_is_refused(api):
    """PRD 3.5: "issuing is refused with `ERR_DUPLICATE_ACTIVE_QUOTE` when another quote
    for the same instrument and the same `service_type` already holds status `ISSUED`."
    PRD 2.8: "**One issued quote.** At most one quote per instrument-and-service-type
    pair may hold status `ISSUED`. Otherwise `ERR_DUPLICATE_ACTIVE_QUOTE` (409). Applies
    to `POST /quotes/{id}/issue`."

    Design: Corner/validations/second_issued_quote_for_the_same_service_type_is_rejected
    """
    base = setup_client_with_instrument(deviation=2.0)
    instrument = base["instrument"]
    first = draft_quote(instrument["id"], "TUNE")
    issue_quote(first["id"])
    second = draft_quote(instrument["id"], "TUNE")

    response = api.issue_quote(second["id"], MANAGER)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_QUOTE.value)

    second_now = validate_success(api.get_quote(second["id"], MANAGER))
    assert second_now["status"] == "DRAFT"
    assert second_now["expires_at"] is None
    first_now = validate_success(api.get_quote(first["id"], MANAGER))
    assert first_now["status"] == "ISSUED"


def test_reissue_supersedes_the_original_and_mints_a_new_draft(api):
    """PRD 3.5: "Instead, a `ShopManager` **re-issues** it: the named quote moves to
    `SUPERSEDED` with its own `version` bumped by 1, and a brand-new quote row is minted
    in status `DRAFT` carrying `version_number` one higher than the old row,
    `supersedes_quote_id` pointing back at it, and freshly recomputed prices reflecting
    whatever has changed about the instrument, its location and its owner in the
    meantime."
    PRD 3.5: "Re-issue carries `expected_instrument_version` and bumps the instrument's
    `version` by 1, exactly as an original draft does."

    Design: Corner/state_machines/quote_reissue_mints_a_new_row_and_supersedes_the_original
    """
    base = setup_client_with_instrument(deviation=2.0)
    instrument = base["instrument"]
    original = draft_quote(instrument["id"], "TUNE")
    issue_quote(original["id"])

    replacement = validate_success(
        api.reissue_quote(
            original["id"],
            {"expected_instrument_version": instrument_version(instrument["id"])},
            MANAGER,
        ),
        201,
    )

    original_now = validate_success(api.get_quote(original["id"], MANAGER))
    assert original_now["status"] == "SUPERSEDED"
    assert replacement["status"] == "DRAFT"
    assert replacement["version_number"] == 2
    assert replacement["supersedes_quote_id"] == original["id"]
    assert replacement["total_cents"] == 19500

    rows, _ = validate_paginated(
        api.list_quotes(MANAGER, params={"supersedes_quote_id": original["id"]})
    )
    assert [r["id"] for r in rows] == [replacement["id"]]


def test_declining_an_already_declined_quote_is_already_terminal(api):
    """PRD 3.5: "or declines it with an optional `reason`, moving it `ISSUED → DECLINED`."
    PRD 3.5: "Quotes progress through a lifecycle with four terminal states."
    PRD 2.8: "**Not already terminal.** The target resource must not already sit in a
    terminal state of its own machine. Otherwise `ERR_ALREADY_TERMINAL` (409). Applies
    to every action operation that drives a state machine."

    Design: Corner/state_machines/quote_decline_twice_returns_already_terminal
    """
    base = setup_client_with_instrument(deviation=2.0)
    client, instrument = base["client"], base["instrument"]
    quote = draft_quote(instrument["id"], "TUNE")
    issue_quote(quote["id"])
    validate_success(
        api.decline_quote(
            quote["id"], make_client_headers(client["id"]), {"reason": "too expensive"}
        )
    )

    response = api.decline_quote(
        quote["id"], make_client_headers(client["id"]), {"reason": "again"}
    )
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value)

    assert validate_success(api.get_quote(quote["id"], MANAGER))["status"] == "DECLINED"


def test_daily_sweep_expires_an_issued_quote_past_its_window(api):
    """PRD 3.4: "**Step 2** moves every `ISSUED` quote whose `expires_at` the clock has
    reached or passed to `EXPIRED`, reporting `expired_quote_count`."
    PRD 3.5: "A `ShopManager` issues a `DRAFT` quote, which stamps `issued_at` from the
    logical clock, sets `expires_at` to 30 days after that instant, and bumps the
    quote's `version` by 1"
    PRD 2.5: "Before any administrator sets it, the clock reads exactly
    `2026-05-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/state_machines/daily_sweep_expires_an_issued_quote_past_its_window
    """
    base = setup_client_with_instrument(deviation=2.0)
    client, instrument = base["client"], base["instrument"]
    quote = draft_quote(instrument["id"], "TUNE")
    issued = issue_quote(quote["id"])
    assert_same_instant(issued["expires_at"], "2026-05-31T00:00:00Z", "Quote.expires_at")

    set_clock("2026-06-05T00:00:00Z")
    report = validate_success(api.run_daily_sweep(TEST_USERS["platform_admin_headers"]))
    assert report["expired_quote_count"] == 1

    expired = validate_success(api.get_quote(quote["id"], MANAGER))
    assert expired["status"] == "EXPIRED"

    response = api.approve_quote(quote["id"], make_client_headers(client["id"]))
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value)


def test_approving_a_quote_after_its_window_is_refused_as_expired(api):
    """PRD 2.8: "**Quote validity.** The logical clock must be strictly before the
    quote's `expires_at`. Otherwise `ERR_QUOTE_EXPIRED` (409). Applies to
    `POST /quotes/{id}/approve` and `POST /service-orders`."
    PRD 3.5: "The owning client then either approves the quote — permitted only while
    the clock is strictly before `expires_at` and while the client is `ACTIVE`, moving
    it `ISSUED → APPROVED`"

    Design: Corner/validations/quote_approval_after_expiry_window_is_rejected
    """
    base = setup_client_with_instrument(deviation=2.0)
    client, instrument = base["client"], base["instrument"]
    quote = draft_quote(instrument["id"], "TUNE")
    issue_quote(quote["id"])
    set_clock("2026-06-05T00:00:00Z")

    response = api.approve_quote(quote["id"], make_client_headers(client["id"]))
    validate_error(response, ApiErrorId.ERR_QUOTE_EXPIRED.value)

    assert validate_success(api.get_quote(quote["id"], MANAGER))["status"] == "ISSUED", (
        "the sweep has not run, so the quote is still ISSUED"
    )
