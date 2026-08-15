"""Pricing, tax, and additive-injection calculation claims: the four-level
tax stack, California branded uplift, per-line round-then-sum discipline,
latest-start-wins rule overlap, and provisional-vs-final repricing."""
from test_helpers import (
    ADMIN,
    OPER,
    ApiErrorId,
    adjust_inventory,
    assert_lifting_ticket,
    create_active_contract,
    create_customer,
    create_lifting_right,
    create_posted_ticket,
    create_product,
    create_published_schedule,
    create_tax_rule,
    create_terminal,
    get_customer,
    post_bol,
    reserve_ticket,
    set_clock,
    setup_liftable_right,
    validate_error,
    validate_success,
)

CA_TAXES = [
    ("FEDERAL", "US", "GASOLINE", 18),
    ("STATE", "CA", "GASOLINE", 50),
    ("COUNTY", "06037", "GASOLINE", 10),
    ("CITY", "LAX", "GASOLINE", 5),
]
TX_DIESEL_TAXES = [
    ("FEDERAL", "US", "DIESEL", 24),
    ("STATE", "TX", "DIESEL", 20),
]


class TestMultiLevelTaxStack:
    """CA terminal, GASOLINE brandable, RACK_MINUS_2, branded PKG_A, 1000 gal:
    unit 300 + 20 - 2 = 318; additive 750 + 100 = 850; tax
    1000 * (18 + 50 + 2 uplift + 10 + 5) = 85000; gross 403850."""

    def _setup_and_post(self, api):
        env = setup_liftable_right(
            state_code="CA", county_code="06037", city_code="LAX",
            terminal_code="LAX-02",
            product_family="GASOLINE", product_code="PREM93",
            is_brandable=True, pricing_tier="RACK_MINUS_2",
            inventory_gallons=100000, tax_rules=CA_TAXES,
            posted_rack_cents_per_gal=300, branded_premium_cents_per_gal=20,
        )
        ticket = reserve_ticket(
            env["right"]["id"], 1000, branded=True,
            additive_package_code="PKG_A",
        )
        return env, post_bol(ticket["id"])

    def test_unit_price_and_additive_lines(self, api):
        """PRD §3.3: "The per-gallon `unit_price_cents_per_gal` starts from
        the schedule's `posted_rack_cents_per_gal`, adds the
        `branded_premium_cents_per_gal` if the load is branded, then
        subtracts the contract tier discount — zero cents per gallon for
        `RACK`, one cent for `RACK_MINUS_1`, two cents for `RACK_MINUS_2` —
        with the result floored at zero so the unit price never goes
        negative."
        PRD §3.6: "`PKG_A` blends two lines, one at 250 millicents per gallon
        with a 500-cent flat fee and one at 100 millicents per gallon with no
        flat fee".

        Design: Difficulty/combinatorial_formula/tax_jurisdiction_multi_level_stacked_aggregate_mode_a
        """
        _env, posted = self._setup_and_post(api)
        assert_lifting_ticket(posted)
        assert posted["unit_price_cents_per_gal"] == 318, (
            f"300 posted + 20 branded - 2 tier = 318, got "
            f"{posted['unit_price_cents_per_gal']}"
        )
        # round_half_up(1000*250/1000) + 500 = 750; round_half_up(1000*100/1000) = 100
        assert posted["additive_cost_cents"] == 850, (
            f"PKG_A lines 750 + 100 = 850, got {posted['additive_cost_cents']}"
        )

    def test_four_level_tax_with_ca_uplift_and_gross(self, api):
        """PRD §3.6: "The `tax_cents` then stacks up to four levels of
        motor-fuel excise — `FEDERAL` matched on jurisdiction code `US`,
        `STATE` matched on the terminal's `state_code`, `COUNTY` on its
        `county_code`, and `CITY` on its `city_code`."
        PRD §3.6: "a branded load at a California terminal — one whose
        `state_code` is `CA` — carries an additional 2 cents per gallon of
        branded-blend uplift at the `STATE` level, added before the levels
        are summed."
        PRD §3.6: "The ticket's `gross_cents` is then the
        `requested_gallons` multiplied by the `unit_price_cents_per_gal`,
        plus the `additive_cost_cents`, plus the `tax_cents`".

        Design: Difficulty/combinatorial_formula/tax_jurisdiction_multi_level_stacked_aggregate_mode_a
        """
        _env, posted = self._setup_and_post(api)
        # 1000 * (18 FED + 50 STATE + 2 CA branded uplift + 10 COUNTY + 5 CITY)
        assert posted["tax_cents"] == 85000, (
            f"expected 85000, got {posted['tax_cents']}"
        )
        assert posted["gross_cents"] == 403850, (
            f"1000*318 + 850 + 85000 = 403850, got {posted['gross_cents']}"
        )


class TestAdditiveRoundThenSum:
    """TX terminal, DIESEL brandable, RACK, branded PKG_C, 1001 gal:
    per-line round_half_up gives 333 + 417 + 100 = 850 (sum-then-round would
    give 851); unit 280 + 15 = 295; tax 1001 * 44 = 44044."""

    def _setup_and_post(self, api):
        env = setup_liftable_right(
            terminal_code="HOU-01",
            product_family="DIESEL", product_code="ULSD-B",
            is_brandable=True,
            inventory_gallons=100000, tax_rules=TX_DIESEL_TAXES,
            posted_rack_cents_per_gal=280, branded_premium_cents_per_gal=15,
        )
        ticket = reserve_ticket(
            env["right"]["id"], 1001, branded=True,
            additive_package_code="PKG_C",
        )
        return env, post_bol(ticket["id"])

    def test_per_line_rounding_before_summation(self, api):
        """PRD §2.6: "each additive recipe line is converted from millicents
        to cents and rounded half up to a whole cent *before* the lines are
        summed — the ticket's additive cost is a sum of rounded lines, never
        a rounding of the sum, and on a multi-line recipe the two orders can
        differ by real cents."
        PRD §3.6: "`PKG_C` stacks three lines at 333 millicents per gallon
        with no flat fee, 167 millicents per gallon with a 250-cent flat fee,
        and 100 millicents per gallon with no flat fee."

        Design: Difficulty/combinatorial_formula/additive_injection_per_line_round_then_sum_mode_b
        """
        _env, posted = self._setup_and_post(api)
        # round(1001*333/1000)=333; round(1001*167/1000)+250=167+250=417;
        # round(1001*100/1000)=100 -> 850. Sum-then-round would yield 851.
        assert posted["additive_cost_cents"] == 850, (
            f"per-line round-then-sum must give 850, got "
            f"{posted['additive_cost_cents']}"
        )
        assert posted["unit_price_cents_per_gal"] == 295

    def test_gross_composition_with_rounded_additive(self, api):
        """PRD §3.6: "The ticket's `gross_cents` is then the
        `requested_gallons` multiplied by the `unit_price_cents_per_gal`,
        plus the `additive_cost_cents`, plus the `tax_cents`".
        PRD §2.6: "Motor-fuel excise is computed as whole gallons times a
        whole-cents-per-gallon rate, so no rounding ever arises in the tax
        stack."

        Design: Difficulty/combinatorial_formula/additive_injection_per_line_round_then_sum_mode_b
        """
        _env, posted = self._setup_and_post(api)
        assert posted["tax_cents"] == 44044, f"1001 * (24+20) = 44044"
        assert posted["gross_cents"] == 340189, (
            f"1001*295 + 850 + 44044 = 340189, got {posted['gross_cents']}"
        )


class TestLatestStartWinsOnOverlap:
    """Two ACTIVE STATE/TX/DIESEL rules both cover 2026-08-01: rate 20
    (start 2026-01-01) and rate 22 (start 2026-07-01)."""

    def _setup(self, api):
        env = setup_liftable_right(
            inventory_gallons=100000,
            tax_rules=[("FEDERAL", "US", "DIESEL", 24)],
            posted_rack_cents_per_gal=280,
        )
        rule_a = api.create_tax_rule(
            {
                "jurisdiction_level": "STATE",
                "jurisdiction_code": "TX",
                "product_family": "DIESEL",
                "rate_cents_per_gal": 20,
                "effective_start_date": "2026-01-01",
                "effective_end_date": "2026-12-31",
            },
            ADMIN,
        )
        rule_b = api.create_tax_rule(
            {
                "jurisdiction_level": "STATE",
                "jurisdiction_code": "TX",
                "product_family": "DIESEL",
                "rate_cents_per_gal": 22,
                "effective_start_date": "2026-07-01",
                "effective_end_date": "2026-12-31",
            },
            ADMIN,
        )
        env["rule_a"] = validate_success(rule_a, 201)
        validate_success(rule_b, 201)
        return env

    def test_later_start_rule_wins(self, api):
        """PRD §3.6: "At each level the system selects the `ACTIVE` tax rule
        matching that level, jurisdiction code, and the product's
        `product_family` whose effective window contains the logical date; if
        several active rules match one level, the one with the latest
        `effective_start_date` wins, with earlier `created_at` breaking a
        tie."

        Design: Difficulty/resource_temporal_overlap/tax_rule_window_latest_start_wins_on_overlap
        """
        env = self._setup(api)
        ticket = create_posted_ticket(env["right"]["id"], 1000)
        assert ticket["tax_cents"] == 46000, (
            f"1000 * (24 FED + 22 latest-start STATE) = 46000, got "
            f"{ticket['tax_cents']}"
        )

    def test_shadowed_rule_stays_active(self, api):
        """PRD §3.1: "A rule's `status` is `ACTIVE` while the rate is in
        force and `RETIRED` once withdrawn; the rule list filters by
        `jurisdiction_level`, `jurisdiction_code`, `product_family`, or
        `status`."
        PRD §3.6: "if several active rules match one level, the one with the
        latest `effective_start_date` wins, with earlier `created_at`
        breaking a tie."

        Design: Difficulty/resource_temporal_overlap/tax_rule_window_latest_start_wins_on_overlap
        """
        env = self._setup(api)
        create_posted_ticket(env["right"]["id"], 1000)

        rule_a = validate_success(
            api.get_tax_rule(env["rule_a"]["id"], ADMIN)
        )
        assert rule_a["status"] == "ACTIVE", (
            "overlap resolution selects at read time; the shadowed rule is "
            "not retired"
        )


class TestProvisionalVsFinalPriceDivergence:
    """CA terminal, GASOLINE, RACK, taxes 18/50/10/5; schedule at 300
    published, then a 302 schedule publishes between reservation and post."""

    def _setup_reserved(self, api):
        env = setup_liftable_right(
            state_code="CA", county_code="06037", city_code="LAX",
            terminal_code="LAX-01",
            product_family="GASOLINE", product_code="REG87",
            is_brandable=True, credit_limit_cents=100000000,
            inventory_gallons=100000, tax_rules=CA_TAXES,
            posted_rack_cents_per_gal=300,
        )
        ticket = reserve_ticket(env["right"]["id"], 1000)
        return env, ticket

    def test_final_price_rereads_schedule_at_post(self, api):
        """PRD §3.3: "Timing matters as much as arithmetic: a reservation
        prices provisionally against the schedule in effect on the
        reservation's logical date, while the final price re-reads the
        schedule in effect on the posting date — so if a new schedule
        publishes between reservation and posting, the new price wins and the
        provisional figure is discarded."

        Design: Difficulty/dual_variant_calc/rack_price_provisional_vs_final_diverge_on_midday_republish
        """
        env, ticket = self._setup_reserved(api)
        create_published_schedule(
            env["terminal"]["id"], env["product"]["id"],
            posted_rack_cents_per_gal=302, effective_date="2026-08-01",
        )

        posted = post_bol(ticket["id"])
        assert posted["unit_price_cents_per_gal"] == 302, (
            f"final price must come from the newer PUBLISHED schedule, got "
            f"{posted['unit_price_cents_per_gal']}"
        )
        assert posted["tax_cents"] == 83000, f"1000 * (18+50+10+5) = 83000"
        assert posted["gross_cents"] == 385000, (
            f"1000*302 + 0 + 83000 = 385000, got {posted['gross_cents']}"
        )

    def test_provisional_gross_captured_then_discarded(self, api):
        """PRD §3.6: "a provisional `gross_cents` is computed from the price
        schedule in effect on the reservation's logical date and added to the
        customer's `open_lifting_exposure_cents`".
        PRD §3.3: "Timing matters as much as arithmetic: a reservation prices
        provisionally against the schedule in effect on the reservation's
        logical date, while the final price re-reads the schedule in effect
        on the posting date — so if a new schedule publishes between
        reservation and posting, the new price wins and the provisional
        figure is discarded."

        Design: Difficulty/dual_variant_calc/rack_price_provisional_vs_final_diverge_on_midday_republish
        """
        env, ticket = self._setup_reserved(api)
        # Provisional: 1000 * 300 + 1000 * (18+50+10+5) = 383000.
        assert ticket["gross_cents"] == 383000, (
            f"provisional gross at reservation = 383000, got "
            f"{ticket['gross_cents']}"
        )
        assert (
            get_customer(env["customer"]["id"])["open_lifting_exposure_cents"]
            == 383000
        )

        create_published_schedule(
            env["terminal"]["id"], env["product"]["id"],
            posted_rack_cents_per_gal=302, effective_date="2026-08-01",
        )
        posted = post_bol(ticket["id"])
        assert posted["gross_cents"] != 383000, (
            "the provisional figure must be discarded, not carried forward"
        )
        assert posted["gross_cents"] == 385000


def test_no_matching_county_or_city_rules_contribute_zero(api):
    """PRD §3.6: "At each level the system selects the `ACTIVE` tax rule
    matching that level, jurisdiction code, and the product's
    `product_family` whose effective window contains the logical date; if
    several active rules match one level, the one with the latest
    `effective_start_date` wins, with earlier `created_at` breaking a tie.
    Each selected level contributes the `requested_gallons` multiplied by its
    `rate_cents_per_gal`".

    With no COUNTY or CITY rule matching the terminal's codes, those levels
    contribute nothing: tax = 1000 * (24 + 20) = 44000.

    Design: Corner/calculations/tax_jurisdiction_no_matching_county_or_city_rules
    """
    env = setup_liftable_right(
        inventory_gallons=50000, tax_rules=TX_DIESEL_TAXES,
        posted_rack_cents_per_gal=280,
    )
    ticket = create_posted_ticket(env["right"]["id"], 1000)
    assert ticket["tax_cents"] == 44000


def test_branded_uplift_only_in_california(api):
    """PRD §3.6: "Each selected level contributes the `requested_gallons`
    multiplied by its `rate_cents_per_gal`, and a branded load at a
    California terminal — one whose `state_code` is `CA` — carries an
    additional 2 cents per gallon of branded-blend uplift at the `STATE`
    level, added before the levels are summed."

    Identical branded PKG_B liftings: CA taxes 1000 * (18+50+2) = 70000; TX
    taxes 1000 * (18+20) = 38000.

    Design: Corner/calculations/branded_uplift_applies_only_in_california
    """
    set_clock()
    t_ca = create_terminal(
        terminal_code="CA-T", state_code="CA", county_code="06037",
        city_code="LAX",
    )
    t_tx = create_terminal(
        terminal_code="TX-T", state_code="TX", county_code="48201",
        city_code="HOU",
    )
    product = create_product(
        product_code="REG87", product_family="GASOLINE", is_brandable=True,
    )
    customer = create_customer()
    contract = create_active_contract(
        customer["id"], volume_commitment_gallons=1000000,
    )
    right_ca = create_lifting_right(
        customer["id"], t_ca["id"], product["id"], contract["id"],
    )
    right_tx = create_lifting_right(
        customer["id"], t_tx["id"], product["id"], contract["id"],
    )
    create_tax_rule("FEDERAL", "US", "GASOLINE", 18)
    create_tax_rule("STATE", "CA", "GASOLINE", 50)
    create_tax_rule("STATE", "TX", "GASOLINE", 20)
    adjust_inventory(t_ca["id"], 100000)
    adjust_inventory(t_tx["id"], 100000)
    create_published_schedule(
        t_ca["id"], product["id"], 300, branded_premium_cents_per_gal=20,
    )
    create_published_schedule(
        t_tx["id"], product["id"], 300, branded_premium_cents_per_gal=20,
    )

    ticket_ca = reserve_ticket(
        right_ca["id"], 1000, branded=True, additive_package_code="PKG_B",
    )
    ticket_tx = reserve_ticket(
        right_tx["id"], 1000, branded=True, additive_package_code="PKG_B",
    )
    posted_ca = post_bol(ticket_ca["id"])
    posted_tx = post_bol(ticket_tx["id"])

    assert posted_ca["tax_cents"] == 70000, (
        f"CA branded: 1000 * (18+50+2 uplift) = 70000, got "
        f"{posted_ca['tax_cents']}"
    )
    assert posted_tx["tax_cents"] == 38000, (
        f"TX branded: 1000 * (18+20) = 38000 (no uplift), got "
        f"{posted_tx['tax_cents']}"
    )


def test_unknown_additive_package_rejected(api):
    """PRD §3.6: "Third, a branded request requires the product's
    `is_brandable` to be true and the `additive_package_code` to name a known
    recipe, else `ERR_INVALID_ADDITIVE_PACKAGE` (HTTP 422)."

    Design: Corner/validations/ticket_create_with_invalid_additive_package_returns_error
    """
    env = setup_liftable_right(
        product_family="GASOLINE", product_code="REG87", is_brandable=True,
    )
    resp = api.create_lifting_ticket(
        {
            "lifting_right_id": env["right"]["id"],
            "requested_gallons": 100,
            "branded": True,
            "additive_package_code": "NOPE",
        },
        OPER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ADDITIVE_PACKAGE, 422)


def test_branded_on_non_brandable_product_rejected(api):
    """PRD §3.6: "Third, a branded request requires the product's
    `is_brandable` to be true and the `additive_package_code` to name a known
    recipe, else `ERR_INVALID_ADDITIVE_PACKAGE` (HTTP 422)."
    PRD §3.1: "an optional `is_brandable` flag that defaults to false and
    governs whether branded additive injection may be sold against the
    product."

    Design: Corner/validations/ticket_create_branded_on_non_brandable_product_returns_error
    """
    env = setup_liftable_right(is_brandable=False)
    resp = api.create_lifting_ticket(
        {
            "lifting_right_id": env["right"]["id"],
            "requested_gallons": 100,
            "branded": True,
            "additive_package_code": "PKG_A",
        },
        OPER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ADDITIVE_PACKAGE, 422)
