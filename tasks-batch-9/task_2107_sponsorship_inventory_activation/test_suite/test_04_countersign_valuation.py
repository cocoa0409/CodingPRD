"""Countersignature: clause pricing, the contract rollup and the trade leg."""

from test_helpers import (
    AFTER_TERM_END,
    ApiErrorId,
    TEST_USERS,
    TWO_BREAK_DIGITAL_BOARD_LINE,
    assert_contract,
    assert_contract_money_consistency,
    assert_entitlement,
    close_contract,
    countersign_contract,
    read_contract,
    read_entitlement,
    read_property,
    set_clock,
    setup_category_exclusivity_standoff,
    setup_contract_scenario,
    setup_trade_leg_contract,
    validate_error,
    validate_success,
)

APPROVER = TEST_USERS["approver_headers"]


def _submitted_deal(**kwargs):
    return setup_contract_scenario(stage="SUBMITTED", **kwargs)


# ---------------------------------------------------------------------------
# Clause pricing: tier, seasonality and exclusivity interact on one value
# ---------------------------------------------------------------------------
def test_entitlement_unit_value_combines_tier_seasonality_and_exclusivity(api):
    """PRD §3.5: "The line's `tier_breaks` are then considered in ascending order
    of `min_units`, and each break whose `min_units` is less than or equal to the
    entitlement's `promised_units` replaces the running unit price with its own
    `unit_price_cents`; the boundary is inclusive, so an entitlement promising
    exactly the break's `min_units` earns the break."
    PRD §3.5: "The exclusivity factor is the line's `exclusivity_multiplier` when
    the contract's `exclusivity_scope` is `CATEGORY`, and 1.00 otherwise."
    PRD §3.5: "The entitlement's `unit_value_cents` is then the tiered unit price
    multiplied by the property's `seasonality_index` and by that exclusivity
    factor, rounded half up to a whole cent."
    PRD §3.5: "The rounding order is pinned: the per-unit figure is rounded
    first, and only then is `gross_value_cents` obtained by multiplying
    `unit_value_cents` by `promised_units`, a multiplication that is exact and is
    not rounded again."

    Design: Difficulty/combinatorial_formula/entitlement_unit_value_tier_seasonality_exclusivity_mode_a
    """
    scenario = _submitted_deal(
        line_specs=[TWO_BREAK_DIGITAL_BOARD_LINE],
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )
    contract = countersign_contract(
        scenario["contract"]["id"], scenario["property"]["id"]
    )
    entitlement = read_entitlement(scenario["entitlement"]["id"])

    assert_entitlement(entitlement)
    assert entitlement["unit_value_cents"] == 337_500, (
        "225000 at the 10-unit break, scaled by seasonality 1.20 and the 1.25 "
        f"exclusivity premium, rounds to 337500; got {entitlement['unit_value_cents']}"
    )
    assert entitlement["gross_value_cents"] == 3_375_000

    assert contract["gross_entitlement_value_cents"] == 3_375_000
    assert contract["volume_discount_pct"] == 0.08
    assert contract["cash_value_cents"] == 3_105_000


def test_countersign_rolls_the_priced_clause_into_the_property_position(api):
    """PRD §3.5: "Step five sets `total_recognized_value_cents` to
    `cash_value_cents` plus `in_kind_recognized_value_cents`."
    PRD §3.1: "`committed_gross_value_cents` is the sum of
    `total_recognized_value_cents` across those contracts of the property whose
    `status` is `COUNTERSIGNED` or `ACTIVE`."
    PRD §3.5: "Finally the property's committed position is recomputed, refreshing
    `committed_gross_value_cents` and `sellout_pct` and incrementing the
    property's `version` by 1 — which is exactly what makes any other approver's
    previously captured `expected_property_version` stale."

    Design: Difficulty/combinatorial_formula/entitlement_unit_value_tier_seasonality_exclusivity_mode_a
    """
    scenario = _submitted_deal(
        line_specs=[TWO_BREAK_DIGITAL_BOARD_LINE],
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )
    version_before = read_property(scenario["property"]["id"])["version"]

    contract = countersign_contract(
        scenario["contract"]["id"], scenario["property"]["id"]
    )
    assert_contract(contract)
    assert contract["total_recognized_value_cents"] == 3_105_000
    assert_contract_money_consistency(contract)

    prop = read_property(scenario["property"]["id"])
    assert prop["committed_gross_value_cents"] == 3_105_000
    assert prop["version"] > version_before, (
        "the committed rollup increments the property's version"
    )


# ---------------------------------------------------------------------------
# The volume discount is keyed on the pre-discount, cash-only gross
# ---------------------------------------------------------------------------
def test_volume_discount_is_keyed_on_the_pre_discount_gross(api):
    """PRD §3.5: "Step two selects `volume_discount_pct` from that gross alone —
    never from the headline total, even though the total is the number the deal is
    announced at: a gross of 5,000,000 cents (fifty thousand dollars) or more
    earns 0.12, a gross of at least 2,500,000 cents earns 0.08, a gross of at
    least 1,000,000 cents earns 0.04, and anything below one million cents earns
    0.00; each threshold is inclusive."
    PRD §3.5: "Step three sets `cash_value_cents` to
    `gross_entitlement_value_cents` less the discount amount, where the discount
    amount is `gross_entitlement_value_cents` multiplied by `volume_discount_pct`
    and rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/volume_discount_keyed_on_pre_discount_gross_mode_c
    """
    scenario = _submitted_deal(
        line_specs=[TWO_BREAK_DIGITAL_BOARD_LINE],
        sponsor_spec={
            "name": "Nimbus Motors",
            "category": "AUTOMOTIVE",
            "contact_email": "ops@nimbus.example",
        },
        entitlement_specs=[
            {"asset_index": 0, "clause_ref": "3.1", "promised_units": 8}
        ],
        contract_overrides={
            "exclusivity_scope": "NONE",
            "in_kind_declared_value_cents": 900_000,
            "in_kind_category": "PRODUCT",
        },
    )
    contract = countersign_contract(
        scenario["contract"]["id"], scenario["property"]["id"]
    )

    entitlement = read_entitlement(scenario["entitlement"]["id"])
    assert entitlement["unit_value_cents"] == 300_000, (
        "8 units reach no break and the contract holds no CATEGORY exclusivity, "
        f"so 250000 * 1.20 stands; got {entitlement['unit_value_cents']}"
    )
    assert contract["gross_entitlement_value_cents"] == 2_400_000
    assert contract["volume_discount_pct"] == 0.04, (
        "the tier is keyed on the 2400000 gross, not on the 2880000 headline "
        f"total; got {contract['volume_discount_pct']}"
    )
    assert contract["cash_value_cents"] == 2_304_000


def test_trade_ceiling_is_derived_from_the_discounted_cash_leg(api):
    """PRD §3.5: "The ceiling is `cash_value_cents` multiplied by 0.25 — a
    quarter of the cash leg — rounded half up to a whole cent."
    PRD §3.5: "At countersignature the **conservative** ordering applies:
    `in_kind_declared_value_cents` is multiplied by one minus the haircut rate and
    rounded half up to a whole cent, and `in_kind_recognized_value_cents` is the
    smaller of that haircut figure and the ceiling."
    PRD §3.5: "Step five sets `total_recognized_value_cents` to
    `cash_value_cents` plus `in_kind_recognized_value_cents`."

    Design: Difficulty/combinatorial_formula/volume_discount_keyed_on_pre_discount_gross_mode_c
    """
    scenario = _submitted_deal(
        line_specs=[TWO_BREAK_DIGITAL_BOARD_LINE],
        sponsor_spec={
            "name": "Nimbus Motors",
            "category": "AUTOMOTIVE",
            "contact_email": "ops@nimbus.example",
        },
        entitlement_specs=[
            {"asset_index": 0, "clause_ref": "3.1", "promised_units": 8}
        ],
        contract_overrides={
            "exclusivity_scope": "NONE",
            "in_kind_declared_value_cents": 900_000,
            "in_kind_category": "PRODUCT",
        },
    )
    contract = countersign_contract(
        scenario["contract"]["id"], scenario["property"]["id"]
    )

    assert contract["in_kind_recognized_value_cents"] == 576_000, (
        "the 585000 haircut figure is capped at a quarter of the 2304000 cash "
        f"leg; got {contract['in_kind_recognized_value_cents']}"
    )
    assert contract["total_recognized_value_cents"] == 2_880_000
    assert_contract_money_consistency(contract)


# ---------------------------------------------------------------------------
# The tier boundary is inclusive
# ---------------------------------------------------------------------------
def _two_clause_deal():
    return _submitted_deal(
        entitlement_specs=[
            {"asset_index": 0, "clause_ref": "4.2(a)", "promised_units": 10},
            {"asset_index": 0, "clause_ref": "4.2(b)", "promised_units": 9},
        ],
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )


def test_promised_units_exactly_on_the_break_earn_the_break_price(api):
    """PRD §3.5: "The line's `tier_breaks` are then considered in ascending order
    of `min_units`, and each break whose `min_units` is less than or equal to the
    entitlement's `promised_units` replaces the running unit price with its own
    `unit_price_cents`; the boundary is inclusive, so an entitlement promising
    exactly the break's `min_units` earns the break."

    Design: Difficulty/boundary_precision_check/tier_break_inclusive_at_exactly_min_units
    """
    scenario = _two_clause_deal()
    countersign_contract(scenario["contract"]["id"], scenario["property"]["id"])

    at_break = read_entitlement(scenario["entitlements"][0]["id"])
    assert at_break["promised_units"] == 10
    assert at_break["unit_value_cents"] == 337_500, (
        "10 units sit exactly on the 10-unit break, so 225000 * 1.20 * 1.25 "
        f"applies; got {at_break['unit_value_cents']}"
    )
    assert at_break["gross_value_cents"] == 3_375_000


def test_one_unit_below_the_break_keeps_the_base_price(api):
    """PRD §3.5: "In effect, the highest break the promised volume reaches wins,
    and if the promised volume reaches none of them the base price stands."
    PRD §3.5: "Step two selects `volume_discount_pct` from that gross alone —
    never from the headline total, even though the total is the number the deal is
    announced at: a gross of 5,000,000 cents (fifty thousand dollars) or more
    earns 0.12, a gross of at least 2,500,000 cents earns 0.08, a gross of at
    least 1,000,000 cents earns 0.04, and anything below one million cents earns
    0.00; each threshold is inclusive."

    Design: Difficulty/boundary_precision_check/tier_break_inclusive_at_exactly_min_units
    """
    scenario = _two_clause_deal()
    contract = countersign_contract(
        scenario["contract"]["id"], scenario["property"]["id"]
    )

    below_break = read_entitlement(scenario["entitlements"][1]["id"])
    assert below_break["promised_units"] == 9
    assert below_break["unit_value_cents"] == 375_000, (
        "9 units reach no break, so the 250000 base price is scaled by 1.20 and "
        f"1.25; got {below_break['unit_value_cents']}"
    )
    assert below_break["gross_value_cents"] == 3_375_000

    assert contract["gross_entitlement_value_cents"] == 6_750_000
    assert contract["volume_discount_pct"] == 0.12
    assert contract["cash_value_cents"] == 5_940_000


# ---------------------------------------------------------------------------
# The trade leg is recognized twice, in two different orderings
# ---------------------------------------------------------------------------
def test_trade_leg_is_recognized_conservatively_at_countersignature(api):
    """PRD §3.5: "The haircut rate is fixed by `in_kind_category`: `MEDIA_TRADE`
    is discounted by 0.50, `SERVICES` by 0.40, `PRODUCT` by 0.35 and `TICKETS` by
    0.20."
    PRD §3.5: "At countersignature the **conservative** ordering applies:
    `in_kind_declared_value_cents` is multiplied by one minus the haircut rate and
    rounded half up to a whole cent, and `in_kind_recognized_value_cents` is the
    smaller of that haircut figure and the ceiling."

    Design: Difficulty/dual_variant_calc/in_kind_conservative_versus_audited_recognition
    """
    scenario = setup_trade_leg_contract()
    contract = scenario["contract"]

    assert contract["cash_value_cents"] == 3_105_000
    assert contract["in_kind_recognized_value_cents"] == 776_250, (
        "1200000 haircut to 780000 is then capped at a quarter of the cash leg; "
        f"got {contract['in_kind_recognized_value_cents']}"
    )
    assert contract["total_recognized_value_cents"] == 3_881_250
    assert_contract_money_consistency(contract)


def test_trade_leg_is_revalued_under_the_audited_ordering_at_close(api):
    """PRD §3.9: "First the trade leg is re-valued under the **audited**
    ordering, which reverses the two operations used at signature: the ceiling —
    `cash_value_cents` multiplied by 0.25, rounded half up to a whole cent — is
    applied to the raw `in_kind_declared_value_cents` first, taking whichever of
    the two is smaller, and only then is that capped figure multiplied by one
    minus the category haircut rate and rounded half up to a whole cent."
    PRD §3.9: "The new `in_kind_recognized_value_cents` replaces the old, and
    `total_recognized_value_cents` is set again to `cash_value_cents` plus the new
    in-kind figure; `gross_entitlement_value_cents`, `volume_discount_pct` and
    `cash_value_cents` are not recomputed at close."

    Design: Difficulty/dual_variant_calc/in_kind_conservative_versus_audited_recognition
    """
    scenario = setup_trade_leg_contract()
    assert scenario["contract"]["in_kind_recognized_value_cents"] == 776_250

    set_clock(AFTER_TERM_END)
    closed = close_contract(scenario["contract"]["id"])

    assert closed["status"] == "CLOSED"
    assert closed["in_kind_recognized_value_cents"] == 504_563, (
        "capping 1200000 at 776250 first and only then applying the 0.35 "
        f"haircut yields 504563; got {closed['in_kind_recognized_value_cents']}"
    )
    assert closed["total_recognized_value_cents"] == 3_609_563
    assert closed["cash_value_cents"] == 3_105_000, (
        "cash_value_cents is not recomputed at close"
    )


def test_media_trade_haircut_lands_below_the_ceiling(api):
    """PRD §3.5: "The haircut rate is fixed by `in_kind_category`: `MEDIA_TRADE`
    is discounted by 0.50, `SERVICES` by 0.40, `PRODUCT` by 0.35 and `TICKETS` by
    0.20."
    PRD §3.1: "`sellout_pct` is 0.00 when `inventory_target_value_cents` is 0;
    otherwise it is 100 multiplied by `committed_gross_value_cents`, divided by
    `inventory_target_value_cents`, rounded half up to 2 decimal places."

    Design: Corner/calculations/in_kind_media_trade_haircut_constant_applied
    """
    scenario = _submitted_deal(
        contract_overrides={
            "exclusivity_scope": "CATEGORY",
            "in_kind_declared_value_cents": 1_200_000,
            "in_kind_category": "MEDIA_TRADE",
        }
    )
    contract = countersign_contract(
        scenario["contract"]["id"], scenario["property"]["id"]
    )

    assert contract["cash_value_cents"] == 3_105_000
    assert contract["in_kind_recognized_value_cents"] == 600_000, (
        "the 0.50 MEDIA_TRADE haircut yields 600000, which sits below the "
        f"776250 ceiling; got {contract['in_kind_recognized_value_cents']}"
    )
    assert contract["total_recognized_value_cents"] == 3_705_000

    prop = read_property(scenario["property"]["id"])
    assert prop["committed_gross_value_cents"] == 3_705_000
    assert prop["sellout_pct"] == 7.41


def test_oversell_ceiling_alone_aborts_the_countersign(api):
    """PRD §3.5: "The property's current `committed_gross_value_cents` plus this
    contract's freshly computed `total_recognized_value_cents` must be no greater
    than `inventory_target_value_cents` multiplied by 1.10 and rounded half up to
    a whole cent — a ten percent oversell allowance over the season target.
    Exceeding it aborts the countersign with `ERR_INVENTORY_VALUE_EXCEEDED` and
    leaves every field untouched."

    Design: Corner/validations/oversell_ceiling_alone_returns_inventory_value_exceeded
    """
    scenario = _submitted_deal(
        property_overrides={
            "name": "Harbor Arena",
            "sport_code": "BASKETBALL",
            "inventory_target_value_cents": 3_000_000,
        },
        asset_specs=[
            {
                "name": "Center Hung Board",
                "asset_class": "DIGITAL_BOARD",
                "capacity_units": 12,
                "changeover_buffer_minutes": 0,
            }
        ],
        sponsor_spec={
            "name": "Nimbus Motors",
            "category": "AUTOMOTIVE",
            "contact_email": "ops@nimbus.example",
        },
        entitlement_specs=[
            {"asset_index": 0, "clause_ref": "4.2(a)", "promised_units": 12}
        ],
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )
    property_id = scenario["property"]["id"]
    version_before = read_property(property_id)["version"]

    response = api.countersign_contract(
        scenario["contract"]["id"],
        {"expected_property_version": version_before},
        APPROVER,
    )
    validate_error(response, ApiErrorId.ERR_INVENTORY_VALUE_EXCEEDED.value)
    assert response.status_code == 409

    prop = read_property(property_id)
    assert prop["committed_gross_value_cents"] == 0
    assert prop["version"] == version_before, (
        "an aborted countersign leaves every field untouched"
    )

    contract = read_contract(scenario["contract"]["id"])
    assert contract["status"] == "SUBMITTED"
    assert contract["cash_value_cents"] == 0


def test_countersign_response_already_carries_every_cascaded_value(api):
    """PRD §2.9: "Whenever an event changes a quantity that some other row
    summarises, the summary is recomputed immediately as part of the same request,
    and each such recomputation is a mutation of the row it touches: `updated_at`
    is refreshed and `version` increases by 1."
    PRD §3.5: "An accepted countersignature pins `rate_card_id` to the id of the
    property's published card — pinned once, never re-pinned, and unaffected by
    any later supersession — stamps `countersigned_by_user_id` with the caller's
    `X-User-ID`, writes the entitlement and contract money fields computed above,
    and drives the contract `SUBMITTED → COUNTERSIGNED`."

    Design: Corner/consistency_model/countersign_response_already_carries_every_cascaded_value
    """
    scenario = _submitted_deal(
        contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    property_id = scenario["property"]["id"]
    version_before = read_property(property_id)["version"]

    written = validate_success(
        api.countersign_contract(
            scenario["contract"]["id"],
            {"expected_property_version": version_before},
            APPROVER,
        )
    )
    assert written["gross_entitlement_value_cents"] == 3_375_000
    assert written["cash_value_cents"] == 3_105_000
    assert written["total_recognized_value_cents"] == 3_105_000
    assert written["rate_card_id"] == scenario["rate_card"]["id"]

    reread = read_contract(scenario["contract"]["id"])
    for field in (
        "gross_entitlement_value_cents",
        "cash_value_cents",
        "total_recognized_value_cents",
        "rate_card_id",
    ):
        assert reread[field] == written[field], (
            f"{field} settled immediately: the follow-up read must match the "
            f"write response, got {reread[field]} vs {written[field]}"
        )

    prop = read_property(property_id)
    assert prop["committed_gross_value_cents"] == 3_105_000
    assert prop["version"] > version_before

    entitlement = read_entitlement(scenario["entitlement"]["id"])
    assert entitlement["unit_value_cents"] == 337_500


# ---------------------------------------------------------------------------
# Category exclusivity is decided before the fiscal ceiling
# ---------------------------------------------------------------------------
def test_category_exclusivity_conflict_wins_over_the_oversell_ceiling(api):
    """PRD §3.5: "Then category exclusivity is tested: the countersign is refused
    with `ERR_CATEGORY_EXCLUSIVITY_CONFLICT` when some other contract of the same
    property, whose `status` is `COUNTERSIGNED` or `ACTIVE`, belongs to a sponsor
    of the same `category` as this contract's sponsor and either that other
    contract holds `exclusivity_scope` of `CATEGORY` or the contract now being
    countersigned holds it."
    PRD §3.5: "Only after all of those does the money get computed, and the
    resulting figure is finally tested against the property's oversell ceiling."

    Design: Difficulty/priority_pair_validation_conflict/exclusivity_safety_error_wins_over_oversell_ceiling
    """
    standoff = setup_category_exclusivity_standoff()
    assert standoff["contract_one"]["total_recognized_value_cents"] == 3_881_250
    assert standoff["property"]["committed_gross_value_cents"] == 3_881_250

    response = api.countersign_contract(
        standoff["contract_two"]["id"],
        {"expected_property_version": standoff["property"]["version"]},
        APPROVER,
    )
    validate_error(response, ApiErrorId.ERR_CATEGORY_EXCLUSIVITY_CONFLICT.value)
    assert response.status_code == 409, (
        "the category lock is decided before the fiscal ceiling, even though "
        "3881250 + 3881250 also breaches the 7700000 allowance"
    )


def test_refused_countersign_leaves_the_property_position_untouched(api):
    """PRD §3.5: "An accepted countersignature pins `rate_card_id` to the id of
    the property's published card — pinned once, never re-pinned, and unaffected
    by any later supersession — stamps `countersigned_by_user_id` with the
    caller's `X-User-ID`, writes the entitlement and contract money fields
    computed above, and drives the contract `SUBMITTED → COUNTERSIGNED`."
    PRD §3.1: "`committed_gross_value_cents` is the sum of
    `total_recognized_value_cents` across those contracts of the property whose
    `status` is `COUNTERSIGNED` or `ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/exclusivity_safety_error_wins_over_oversell_ceiling
    """
    standoff = setup_category_exclusivity_standoff()

    refused = api.countersign_contract(
        standoff["contract_two"]["id"],
        {"expected_property_version": standoff["property"]["version"]},
        APPROVER,
    )
    validate_error(refused, ApiErrorId.ERR_CATEGORY_EXCLUSIVITY_CONFLICT.value)

    blocked = read_contract(standoff["contract_two"]["id"])
    assert blocked["status"] == "SUBMITTED"
    assert blocked["rate_card_id"] is None, (
        "a refused countersign pins no rate card"
    )

    prop = read_property(standoff["property"]["id"])
    assert prop["committed_gross_value_cents"] == 3_881_250, (
        "only the first deal contributes to the committed position"
    )
