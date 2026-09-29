"""Vendor negotiation: when pricing is materialised and what acceptance demands."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_service_event,
    advance_equipment,
    assert_asset,
    assert_cents,
    assert_decimal,
    assert_gpo_contract,
    assert_vendor_quote,
    cast_vote,
    close_intake,
    close_voting,
    create_quote_payload,
    decommission,
    get_success_data,
    live_allocation,
    make_asset,
    make_cycle,
    make_department,
    make_facility,
    make_gpo_contract,
    make_member,
    make_project,
    make_quote,
    make_request,
    open_intake,
    pin_clock,
    refresh_asset,
    refresh_cycle,
    refresh_facility,
    refresh_quote,
    refresh_request,
    run_allocation,
    run_scoring,
    screen,
    setup_quoted_request,
    setup_scored_request,
    submit,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]
_TIER_TABLE = {
    "small_tier_pct": 0.05,
    "mid_tier_pct": 0.12,
    "large_tier_pct": 0.18,
    "tier_mid_floor_cents": 100000000,
    "tier_large_floor_cents": 240000000,
    "multi_unit_addendum_pct": 0.03,
    "trade_in_cap_pct": 0.10,
}


def _scored_request_with_a_sibling_asset():
    """A SCORED request on scanner AC, plus a second scanner AC2 in the same department."""
    ctx = setup_scored_request()
    ctx["sibling_asset"] = make_asset(
        ctx["facility"]["id"], ctx["department"]["id"],
        modality="CT", model_name="Aquilon CT-8B", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=100000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    ctx["expired_contract"] = make_gpo_contract(
        contract_code="GPO-EXP", expires_on=CLOCK, **_TIER_TABLE
    )
    ctx["live_contract"] = make_gpo_contract(
        contract_code="GPO-OK", expires_on="2026-08-01T00:00:01Z", **_TIER_TABLE
    )
    return ctx


def _approved_request_at_the_safety_bar():
    """Asset AS is engineered so its request's safety driver lands on exactly 90.00.

    Life 10 from a 2020-08-02 install gives an age of 6.00 years and a nominal
    40.00; six corrective events, one of them twenty downtime hours, carry a
    28.00 service penalty to an adjusted 12.00, so the driver is
    (100.00 - 12.00) * 0.75 + 4.00 * 6 = 90.00 on the nose.
    """
    pin_clock(CLOCK)
    facility = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-10", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=100000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    for day, hours in (("01", 0.00), ("02", 0.00), ("03", 0.00),
                       ("04", 0.00), ("05", 0.00), ("06", 20.00)):
        add_service_event(
            asset["id"], f"2026-07-{day}T00:00:00Z", "CORRECTIVE", downtime_hours=hours
        )
    cycle = open_intake(make_cycle()["id"])
    request = make_request(
        cycle["id"], department["id"], asset["id"],
        clinical_justification="Repeated correctives; the scanner is unsafe for high-acuity work.",
    )
    submit(request["id"], department["id"])
    screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    cycle = run_allocation(cycle["id"], "RANK_ORDERED", cycle["version"])
    chair = make_member("CHAIR", 3, full_name="Dana Okafor")
    cast_vote(request["id"], chair["id"], "APPROVE")
    close_voting(request["id"], chair["id"])
    contract = make_gpo_contract(contract_code="GPO-OK", **_TIER_TABLE)
    quote = make_quote(request["id"], contract["id"])
    return {
        "facility": facility, "department": department, "asset": asset, "cycle": cycle,
        "request": refresh_request(request["id"]), "chair": chair,
        "contract": contract, "quote": quote,
    }


# ─── The negotiation loop ─────────────────────────────────────────────


def test_a_revise_needs_a_counter_first_and_only_the_counter_counts_the_round(api):
    """PRD §3.8: "Revising a quote requires it to stand in `COUNTERED`, performs
    `COUNTERED → SUBMITTED`, and overwrites `list_price_cents` from the mandatory
    `revised_list_price_cents` plus, when supplied, `trade_in_offer_cents` from
    `revised_trade_in_offer_cents` and `warranty_months` from `revised_warranty_months`."
    PRD §3.8: "A counter increments `negotiation_round` by one and re-runs the whole six-step
    pricing over the new list price, rewriting `gpo_tier`, `gpo_discount_cents`,
    `multi_unit_addendum_cents`, `subtotal_cents`, `trade_in_credit_cents` and
    `net_capital_cents`."
    PRD §3.8: "A revise re-runs the pricing but does **not** increment `negotiation_round`."
    PRD §3.8: "Step one selects `gpo_tier` from the **list** price alone: `LARGE` when
    `list_price_cents` is at or above `tier_large_floor_cents`, otherwise `MID` when it is at or
    above `tier_mid_floor_cents`, otherwise `SMALL`."
    PRD §2.11: "18. The vendor quote not in the state set the operation requires, on counter,
    revise, accept and withdraw — `ERR_QUOTE_INVALID_STATE`, 409."

    Design: Corner/state_machines/revise_before_a_counter_is_a_quote_state_fault_then_the_cycle_reprices
    """
    ctx = setup_quoted_request(base="scored")
    quote_id = ctx["quote"]["id"]
    assert ctx["quote"]["status"] == "SUBMITTED"
    assert ctx["quote"]["gpo_tier"] == "MID"
    assert_cents(ctx["quote"]["net_capital_cents"], 88000000, "net_capital_cents")

    validate_error(
        api.revise_quote(quote_id, {"revised_list_price_cents": 95000000}, _PLANNER),
        ApiErrorId.ERR_QUOTE_INVALID_STATE.value, 409,
    )
    untouched = refresh_quote(quote_id)
    assert untouched["status"] == "SUBMITTED"
    assert_cents(untouched["list_price_cents"], 100000000, "list_price_cents")
    assert_cents(untouched["net_capital_cents"], 88000000, "net_capital_cents")
    assert untouched["negotiation_round"] == 1
    assert untouched["version"] == 1

    countered = validate_success(
        api.counter_quote(
            quote_id,
            {"counter_list_price_cents": 90000000,
             "counter_note": "Below the MID floor, please re-quote."},
            _PLANNER,
        )
    )
    assert_vendor_quote(countered)
    assert countered["status"] == "COUNTERED"
    assert_cents(countered["list_price_cents"], 90000000, "list_price_cents")
    assert countered["gpo_tier"] == "SMALL"
    assert_cents(countered["gpo_discount_cents"], 4500000, "gpo_discount_cents")
    assert_cents(countered["subtotal_cents"], 85500000, "subtotal_cents")
    assert_cents(countered["net_capital_cents"], 85500000, "net_capital_cents")
    assert countered["negotiation_round"] == 2
    assert countered["version"] == 2

    revised = validate_success(
        api.revise_quote(quote_id, {"revised_list_price_cents": 240000000}, _PLANNER)
    )
    assert revised["status"] == "SUBMITTED"
    assert_cents(revised["list_price_cents"], 240000000, "list_price_cents")
    assert revised["gpo_tier"] == "LARGE"
    assert_cents(revised["gpo_discount_cents"], 43200000, "gpo_discount_cents")
    assert_cents(revised["subtotal_cents"], 196800000, "subtotal_cents")
    assert_cents(revised["net_capital_cents"], 196800000, "net_capital_cents")
    assert revised["negotiation_round"] == 2
    assert revised["version"] == 3

    request = refresh_request(ctx["request"]["id"])
    assert_cents(request["budgetary_tco_cents"], 160106313, "budgetary_tco_cents")
    assert request["negotiated_tco_cents"] is None


def test_a_contract_edit_leaves_the_priced_quote_alone_until_its_own_counter(api):
    """PRD §3.8: "A planner may later edit `vendor_name`, all three tier fractions, both floors,
    `multi_unit_addendum_pct`, `trade_in_cap_pct` and `expires_on`; already-priced quotes are
    **not** repriced by a contract edit, and a quote re-prices only on its own counter or
    revise."
    PRD §3.8: "Step two takes the fraction of the selected tier — `large_tier_pct`,
    `mid_tier_pct` or `small_tier_pct` — and sets `gpo_discount_cents` to the list price
    multiplied by that fraction, rounded half up."
    PRD §3.8: "Step four sets `subtotal_cents` to the list price less the group-purchasing
    discount less the multi-unit addendum."
    PRD §3.8: "A new quote is born in `SUBMITTED` with `negotiation_round` 1, and raising it
    changes nothing on the request — the request's cost of ownership and funded amount move only
    when a quote is accepted."

    Design: Corner/endpoints/patching_a_gpo_contract_leaves_priced_quotes_untouched_until_the_next_counter
    """
    ctx = setup_quoted_request(
        base="scored", contract={"contract_code": "GPO-OK", **_TIER_TABLE}
    )
    quote_id = ctx["quote"]["id"]

    repriced_contract = validate_success(
        api.patch_gpo_contract(ctx["contract"]["id"], {"mid_tier_pct": 0.20}, _PLANNER)
    )
    assert_gpo_contract(repriced_contract)
    assert_decimal(repriced_contract["mid_tier_pct"], 0.20, "mid_tier_pct")
    assert_decimal(repriced_contract["small_tier_pct"], 0.05, "small_tier_pct")
    assert_decimal(repriced_contract["large_tier_pct"], 0.18, "large_tier_pct")
    assert_cents(repriced_contract["tier_mid_floor_cents"], 100000000, "tier_mid_floor_cents")
    assert_cents(repriced_contract["tier_large_floor_cents"], 240000000, "tier_large_floor_cents")
    assert repriced_contract["version"] == 2

    stale_price = validate_success(api.get_quote(quote_id, _PLANNER))
    assert stale_price["gpo_tier"] == "MID"
    assert_cents(stale_price["gpo_discount_cents"], 12000000, "gpo_discount_cents")
    assert_cents(stale_price["subtotal_cents"], 88000000, "subtotal_cents")
    assert_cents(stale_price["net_capital_cents"], 88000000, "net_capital_cents")
    assert stale_price["negotiation_round"] == 1
    assert stale_price["version"] == 1

    countered = validate_success(
        api.counter_quote(
            quote_id,
            {"counter_list_price_cents": 100000000,
             "counter_note": "Re-pricing under the renegotiated tier table."},
            _PLANNER,
        )
    )
    assert countered["status"] == "COUNTERED"
    assert countered["negotiation_round"] == 2
    assert_cents(countered["gpo_discount_cents"], 20000000, "gpo_discount_cents")
    assert_cents(countered["subtotal_cents"], 80000000, "subtotal_cents")
    assert_cents(countered["net_capital_cents"], 80000000, "net_capital_cents")

    request = refresh_request(ctx["request"]["id"])
    assert_cents(request["budgetary_tco_cents"], 160106313, "budgetary_tco_cents")
    assert request["negotiated_tco_cents"] is None


# ─── What quote creation checks ───────────────────────────────────────


def test_a_contract_expiring_on_the_clock_is_dead_and_the_trade_in_must_be_the_replaced_machine(api):
    """PRD §3.8: "The contract must still be live: an `expires_on` at or before the logical clock
    is rejected with `ERR_GPO_CONTRACT_EXPIRED`."
    PRD §3.8: "Four inputs are optional: `trade_in_asset_id` naming the machine offered in
    part-exchange, which must equal the request's own `asset_id` and is otherwise rejected with
    `ERR_TRADE_IN_ASSET_MISMATCH`; `trade_in_offer_cents`, the vendor's pre-cap offer, defaulting
    to 0 and never negative; `multi_unit_count` between 1 and 10 inclusive, defaulting to 1; and
    `warranty_months`, which must be exactly 0, 12 or 24 and defaults to 0."
    PRD §3.8: "Step five sets `trade_in_credit_cents`, when a `trade_in_asset_id` is present, to
    the smaller of `trade_in_offer_cents` and the subtotal multiplied by `trade_in_cap_pct`
    rounded half up; with no trade-in asset the credit is 0."
    PRD §3.8: "Step six sets `net_capital_cents` to the subtotal less the trade-in credit."
    PRD §2.11: "26. The group-purchasing contract expired, on quote creation —
    `ERR_GPO_CONTRACT_EXPIRED`, 409."
    PRD §2.11: "28. `trade_in_asset_id` supplied but not equal to the request's `asset_id`, on
    quote creation — `ERR_TRADE_IN_ASSET_MISMATCH`, 422."

    Design: Corner/validations/contract_expiry_and_trade_in_identity_are_checked_at_quote_creation
    """
    ctx = _scored_request_with_a_sibling_asset()
    request_id = ctx["request"]["id"]

    validate_error(
        api.create_quote(
            request_id, create_quote_payload(ctx["expired_contract"]["id"]), _PLANNER
        ),
        ApiErrorId.ERR_GPO_CONTRACT_EXPIRED.value, 409,
    )
    validate_error(
        api.create_quote(
            request_id,
            create_quote_payload(
                ctx["live_contract"]["id"],
                trade_in_asset_id=ctx["sibling_asset"]["id"],
                trade_in_offer_cents=30000000,
            ),
            _PLANNER,
        ),
        ApiErrorId.ERR_TRADE_IN_ASSET_MISMATCH.value, 422,
    )

    quote = validate_success(
        api.create_quote(
            request_id,
            create_quote_payload(
                ctx["live_contract"]["id"],
                trade_in_asset_id=ctx["asset"]["id"],
                trade_in_offer_cents=30000000,
            ),
            _PLANNER,
        ),
        201,
    )
    assert_vendor_quote(quote)
    assert quote["gpo_tier"] == "MID"
    assert_cents(quote["gpo_discount_cents"], 12000000, "gpo_discount_cents")
    assert_cents(quote["multi_unit_addendum_cents"], 0, "multi_unit_addendum_cents")
    assert_cents(quote["subtotal_cents"], 88000000, "subtotal_cents")
    assert_cents(quote["trade_in_credit_cents"], 8800000, "trade_in_credit_cents")
    assert_cents(quote["net_capital_cents"], 79200000, "net_capital_cents")
    assert quote["negotiation_round"] == 1

    rows = get_success_data(api.list_quotes(_PLANNER, params={"request_id": request_id}))
    assert len(rows) == 1
    assert rows[0]["id"] == quote["id"]

    asset = refresh_asset(ctx["asset"]["id"])
    assert asset["disposition_status"] == "NONE"
    assert_cents(asset["trade_in_credit_applied_cents"], 0, "trade_in_credit_applied_cents")


# ─── What acceptance checks ───────────────────────────────────────────


def test_a_quote_lapsing_exactly_on_the_clock_is_still_acceptable(api):
    """PRD §3.8: "Accepting a quote requires it to stand in `SUBMITTED`, requires the owning
    request to stand in `APPROVED` or `FUNDED`, and requires the logical clock to be at or before
    the quote's `valid_until` — validity is evaluated lazily at acceptance and never at creation,
    counter or revise, so a lapsed quote is rejected with `ERR_QUOTE_EXPIRED` only here."
    PRD §3.8: "Because a quote is now accepted, the negotiated cost-of-ownership variant runs and
    rewrites the request's `negotiated_operating_5y_cents`, `negotiated_tco_cents` and
    `baseline_year1_opex_cents`, the funded amount is recomputed into `funded_amount_cents`, and
    the request's `version` is incremented."
    PRD §3.8: "Where the request already stands in `FUNDED`, the change in funded amount is
    applied as a delta to the facility allocation: `committed_cents` moves by the difference,
    `available_cents` is recomputed, `posture` is refreshed and the allocation's `version` is
    incremented; and where that recomputation lifts `available_cents` above zero on a row that
    had been `EXHAUSTED`, the posture returns to `ACTIVE`, the cycle's
    `exhausted_allocation_count` is decremented and the cycle's `version` is incremented."
    PRD §2.11: "27. The quote's validity lapsed, on quote accept — `ERR_QUOTE_EXPIRED`, 409."

    Design: Corner/validations/quote_expiry_bar_is_inclusive_of_the_clock_instant_at_accept
    """
    ctx = setup_quoted_request(
        base="approved", allocation_method="RANK_ORDERED",
        contract={"contract_code": "GPO-OK", **_TIER_TABLE},
        quote={"valid_until": "2026-07-31T00:00:00Z"},
    )
    lapsed = ctx["quote"]
    on_the_clock = make_quote(
        ctx["request"]["id"], ctx["contract"]["id"], valid_until=CLOCK
    )
    assert lapsed["status"] == "SUBMITTED"
    assert on_the_clock["status"] == "SUBMITTED"

    validate_error(
        api.accept_quote(lapsed["id"], _PLANNER),
        ApiErrorId.ERR_QUOTE_EXPIRED.value, 409,
    )
    still_open = refresh_quote(lapsed["id"])
    assert still_open["status"] == "SUBMITTED"
    assert still_open["version"] == 1

    accepted = validate_success(api.accept_quote(on_the_clock["id"], _PLANNER))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["version"] == 2

    request = refresh_request(ctx["request"]["id"])
    assert_cents(request["negotiated_operating_5y_cents"], 59013226,
                 "negotiated_operating_5y_cents")
    assert_cents(request["negotiated_tco_cents"], 147013226, "negotiated_tco_cents")
    assert_cents(request["baseline_year1_opex_cents"], 10850000, "baseline_year1_opex_cents")
    assert_cents(request["funded_amount_cents"], 88000000, "funded_amount_cents")
    assert request["status"] == "APPROVED"

    allocation = live_allocation(ctx["cycle"]["id"], ctx["facility"]["id"])
    assert_cents(allocation["committed_cents"], 0, "committed_cents")
    assert_cents(allocation["available_cents"], 100000000, "available_cents")
    assert allocation["version"] == 1

    asset = refresh_asset(ctx["asset"]["id"])
    assert asset["disposition_status"] == "NONE"
    assert_cents(asset["trade_in_credit_applied_cents"], 0, "trade_in_credit_applied_cents")


def test_a_scrapped_machine_can_no_longer_back_the_trade_in_it_was_offered_for(api):
    """PRD §3.8: "Where a `trade_in_asset_id` is set, that asset must equal the request's
    `asset_id`, must not be `DECOMMISSIONED`, and must have a `disposition_status` of either
    `NONE` or `HELD_FOR_TRADE_IN`; an asset already held for another request's accepted quote is
    rejected with `ERR_TRADE_IN_ASSET_UNAVAILABLE`."
    PRD §3.11: "On success the asset moves `REPLACEMENT_PENDING → DECOMMISSIONED`, its
    `disposition_status` becomes `TRADED_IN` or `SCRAPPED` per the input and its `version` is
    incremented, and the owning facility's `active_asset_count` falls by one with the facility's
    `version` incremented."
    PRD §3.9: "Because a row became exhausted, the cycle's `exhausted_allocation_count` rises by
    one; and where that count then equals the cycle's `allocation_count`, the cycle itself moves
    `ALLOCATED → COMMITTED` with the cycle's `version` incremented."
    PRD §2.11: "29. The trade-in asset unavailable, on quote accept —
    `ERR_TRADE_IN_ASSET_UNAVAILABLE`, 409."
    PRD §2.11: "Nothing later in the order is evaluated, and no side effect is written."

    Design: Corner/validations/trade_in_credit_cannot_be_taken_on_an_already_decommissioned_asset
    """
    ctx = setup_quoted_request(
        base="funded", allocation_method="RANK_ORDERED",
        contract={"contract_code": "GPO-OK", **_TIER_TABLE},
    )
    quote = make_quote(
        ctx["request"]["id"], ctx["contract"]["id"],
        trade_in_asset_id=ctx["asset"]["id"], trade_in_offer_cents=30000000,
    )
    assert_cents(quote["net_capital_cents"], 79200000, "net_capital_cents")

    project = make_project(
        ctx["request"]["id"], ctx["facility"]["id"],
        downtime_start="2026-09-01T00:00:00Z", downtime_end="2026-09-02T00:00:00Z",
    )
    advance_equipment(project["id"], ctx["facility"]["id"], steps=3)
    scrapped = decommission(ctx["asset"]["id"], "SCRAPPED")
    assert scrapped["status"] == "DECOMMISSIONED"

    validate_error(
        api.accept_quote(quote["id"], _PLANNER),
        ApiErrorId.ERR_TRADE_IN_ASSET_UNAVAILABLE.value, 409,
    )

    after_quote = refresh_quote(quote["id"])
    assert after_quote["status"] == "SUBMITTED"
    assert after_quote["version"] == 1
    assert_cents(after_quote["net_capital_cents"], 79200000, "net_capital_cents")

    request = refresh_request(ctx["request"]["id"])
    assert request["status"] == "FUNDED"
    assert_cents(request["funded_amount_cents"], 100000000, "funded_amount_cents")
    assert request["negotiated_tco_cents"] is None

    allocation = live_allocation(ctx["cycle"]["id"], ctx["facility"]["id"])
    assert_cents(allocation["committed_cents"], 100000000, "committed_cents")
    assert_cents(allocation["available_cents"], 0, "available_cents")
    assert allocation["posture"] == "EXHAUSTED"

    cycle = refresh_cycle(ctx["cycle"]["id"])
    assert cycle["status"] == "COMMITTED"
    assert cycle["exhausted_allocation_count"] == 1

    asset = refresh_asset(ctx["asset"]["id"])
    assert_asset(asset)
    assert asset["status"] == "DECOMMISSIONED"
    assert asset["disposition_status"] == "SCRAPPED"
    assert_cents(asset["trade_in_credit_applied_cents"], 0, "trade_in_credit_applied_cents")
    assert refresh_facility(ctx["facility"]["id"])["active_asset_count"] == 0


def test_a_safety_driver_of_exactly_ninety_holds_the_contract_until_it_is_acknowledged(api):
    """PRD §3.8: "A request whose `safety_driver` is at least 90.00 may not be contracted
    silently: acceptance then also requires the optional `safety_review_ack` input to be present
    and true, and its absence or a false value is rejected with `ERR_SAFETY_REVIEW_REQUIRED`."
    PRD §3.5: "The **safety driver** is one hundred less the asset's `adjusted_ruls_score`,
    multiplied by seventy-five hundredths, plus four points for every corrective service event in
    the asset's trailing two-year window, the sum rounded half up to two decimals and then capped
    at 100.00."
    PRD §3.2: "From those, `service_penalty_points` is three points for each corrective event
    plus half a point for each downtime hour, rounded half up to two decimals, and then capped at
    40.00; the cap applies to this penalty term alone and never to the sum of all penalties."
    PRD §3.2: "The **derate gate** sets the asset's `status` to `DERATED` when
    `adjusted_ruls_score` is at most 15.00 or when `unresolved_recall` is true, and to
    `IN_SERVICE` otherwise."
    PRD §2.11: "30. A safety acknowledgement missing on a high-safety-driver request, on quote
    accept — `ERR_SAFETY_REVIEW_REQUIRED`, 422."

    Design: Corner/validations/safety_review_acknowledgement_is_required_at_a_safety_driver_of_exactly_ninety
    """
    ctx = _approved_request_at_the_safety_bar()

    asset = refresh_asset(ctx["asset"]["id"])
    assert_decimal(asset["nominal_ruls_score"], 40.00, "nominal_ruls_score")
    assert_decimal(asset["service_penalty_points"], 28.00, "service_penalty_points")
    assert_decimal(asset["adjusted_ruls_score"], 12.00, "adjusted_ruls_score")
    assert asset["corrective_count_24m"] == 6
    assert_decimal(asset["downtime_hours_24m"], 20.00, "downtime_hours_24m")
    assert asset["status"] == "DERATED"

    request = ctx["request"]
    assert_decimal(request["safety_driver"], 90.00, "safety_driver")
    assert_decimal(request["growth_driver"], 100.00, "growth_driver")
    assert_decimal(request["regulatory_driver"], 0.00, "regulatory_driver")
    assert_decimal(request["eos_driver"], 0.00, "eos_driver")
    assert_decimal(request["composite_score"], 51.50, "composite_score")
    assert request["expedited"] is False

    validate_error(
        api.accept_quote(ctx["quote"]["id"], _PLANNER),
        ApiErrorId.ERR_SAFETY_REVIEW_REQUIRED.value, 422,
    )
    held = refresh_quote(ctx["quote"]["id"])
    assert held["status"] == "SUBMITTED"
    assert held["version"] == 1
    assert refresh_request(ctx["request"]["id"])["negotiated_tco_cents"] is None

    accepted = validate_success(
        api.accept_quote(ctx["quote"]["id"], _PLANNER, {"safety_review_ack": True})
    )
    assert accepted["status"] == "ACCEPTED"

    after = refresh_request(ctx["request"]["id"])
    assert_cents(after["negotiated_operating_5y_cents"], 59013226,
                 "negotiated_operating_5y_cents")
    assert_cents(after["negotiated_tco_cents"], 147013226, "negotiated_tco_cents")
    assert_cents(after["funded_amount_cents"], 88000000, "funded_amount_cents")
