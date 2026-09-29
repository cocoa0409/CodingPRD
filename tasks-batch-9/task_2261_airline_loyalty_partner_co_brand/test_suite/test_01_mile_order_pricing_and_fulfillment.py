"""Mile purchase order pricing, the two status dimensions, and the parent-state gate.

Every scenario here builds its own programme, issuer and agreement from the
endpoints, because the service restarts against an empty database for each test.
"""
from test_helpers import (
    CONTRACTS_OFFICER,
    PARTNER_MANAGER,
    REVENUE_ACCOUNTANT,
    active_agreement,
    assert_co_brand_issuer,
    assert_loyalty_program,
    assert_mile_purchase_order,
    assert_mile_sale_agreement,
    create_issuer,
    create_order,
    create_program,
    draft_agreement,
    invoice_order,
    issue_order,
    mile_purchase_order_payload,
    ratify_agreement,
    read_agreement,
    read_program,
    settle_order,
    submit_agreement,
    tier_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)

#: Three volume tiers: 160 centicents from mile 0, 145 from 1000000, 130 from 5000000.
THREE_TIER_SCHEDULE = tier_schedule((0, 160), (1_000_000, 145), (5_000_000, 130))

#: A single flat tier at 200 centicents per mile.
FLAT_TIER_SCHEDULE = tier_schedule((0, 200))


def _agreement_drawn_to_4999990(program_name):
    """Programme, issuer, agreement and first order with drawn_miles at 4999990.

    The agreement is ACTIVE on the three-tier schedule with a committed volume of
    8000000 miles, and one 4999990-mile order has already been issued against it.
    """
    program = create_program(name=program_name, current_period="2026-08")
    issuer = create_issuer(
        program["id"],
        name="Northbank Card Services",
        annual_mile_purchase_cap_miles=20_000_000,
    )
    agreement = active_agreement(
        issuer["id"],
        term_start_date="2026-09-01",
        term_end_date="2027-08-31",
        committed_volume_miles=8_000_000,
        tier_schedule=THREE_TIER_SCHEDULE,
    )
    first_order = create_order(agreement["id"], 4_999_990, agreement["version"])
    issue_order(first_order["id"])
    return program, issuer, agreement, first_order


def _straddling_second_order(agreement_id):
    """Draw 1000015 miles from mile 4999990, straddling the 5000000 threshold."""
    refreshed = read_agreement(agreement_id)
    return create_order(agreement_id, 1_000_015, refreshed["version"])


def _flat_agreement_with_pending_order(program_name):
    """Programme, issuer, ACTIVE flat-tier agreement and one PENDING order."""
    program = create_program(name=program_name, current_period="2026-08")
    issuer = create_issuer(
        program["id"],
        name="Northbank Card Services",
        annual_mile_purchase_cap_miles=5_000_000,
    )
    agreement = active_agreement(
        issuer["id"],
        term_start_date="2026-09-01",
        term_end_date="2027-08-31",
        committed_volume_miles=1_000_000,
        tier_schedule=FLAT_TIER_SCHEDULE,
    )
    order = create_order(agreement["id"], 100_000, agreement["version"])
    return program, issuer, agreement, order


class TestProvisionalVersusFinalOrderPricing:
    """The same draw priced by the two deliberately different order variants."""

    def test_provisional_variant_charges_the_starting_tier_for_the_whole_order(self):
        """PRD §3.3: "At creation the order snapshots the agreement's live `drawn_miles` into `drawn_miles_before`."
        PRD §3.3: "It selects a single tier: the last entry of the agreement's `tier_schedule` whose `threshold_miles` is at or below `drawn_miles_before`."
        PRD §3.3: "That entry's `price_per_mile_centicents` is stamped as `provisional_tier_price_centicents`, and `gross_amount_cents` is the `order_miles` multiplied by that centicent price, divided by 100 to convert centicents to cents, rounded half up."
        PRD §3.3: "One tier price is applied to the whole order, chosen purely by where the order **starts**; under this variant an order never straddles tiers."
        PRD §3.3: "The order lands with `fulfillment_status` at `PENDING` and `settlement_status` at `PENDING`, with `final_amount_cents`, `net_amount_cents`, `posted_period` and `reversal_reason` all null and `volume_true_up_cents` at zero."

        Design: Difficulty/dual_variant_calc/mile_order_provisional_vs_final_tier_pricing
        """
        _, _, agreement, _ = _agreement_drawn_to_4999990("SkyMiles Core")

        order = _straddling_second_order(agreement["id"])

        assert_mile_purchase_order(order)
        assert order["drawn_miles_before"] == 4999990, (
            "the order snapshots the agreement's live drawn_miles of 4999990 into "
            f"drawn_miles_before, got {order['drawn_miles_before']}"
        )
        assert order["provisional_tier_price_centicents"] == 145, (
            "the last tier opening at or below 4999990 miles prices at 145 centicents, "
            f"got {order['provisional_tier_price_centicents']}"
        )
        assert order["gross_amount_cents"] == 1450022, (
            "1000015 miles at a single 145-centicent tier price is 1450022 cents, "
            f"got {order['gross_amount_cents']}"
        )
        assert order["fulfillment_status"] == "PENDING", (
            "a freshly drawn order lands with fulfillment_status PENDING, got "
            f"{order['fulfillment_status']}"
        )
        assert order["volume_true_up_cents"] == 0, (
            "a freshly drawn order carries volume_true_up_cents at zero, got "
            f"{order['volume_true_up_cents']}"
        )

    def test_final_variant_diverges_from_the_provisional_quote_on_the_same_order(self):
        """PRD §3.3: "It moves the settlement dimension `PENDING → INVOICED` and runs the **final** pricing variant, which reprices the same order progressively rather than at a single tier."
        PRD §3.3: "From there, `volume_true_up_cents` is `final_amount_cents` minus `gross_amount_cents` — signed, and negative whenever marginal slicing beat the provisional single-tier quote — and `net_amount_cents` is set equal to `final_amount_cents`."
        PRD §3.3: "Invoicing then adds `volume_true_up_cents` to the programme's `deferred_revenue_cents`, which may therefore reduce it, and stamps `posted_period` from the programme's `current_period`."

        Design: Difficulty/dual_variant_calc/mile_order_provisional_vs_final_tier_pricing
        """
        _, _, agreement, _ = _agreement_drawn_to_4999990("SkyMiles Core")
        order = _straddling_second_order(agreement["id"])
        issue_order(order["id"])

        invoiced = invoice_order(order["id"])

        assert_mile_purchase_order(invoiced)
        assert invoiced["gross_amount_cents"] == 1450022, (
            "the provisional single-tier quote stays on the row at 1450022 cents, got "
            f"{invoiced['gross_amount_cents']}"
        )
        assert invoiced["final_amount_cents"] == 1300022, (
            "per-slice marginal pricing of the same draw is 1300022 cents, got "
            f"{invoiced['final_amount_cents']}"
        )
        assert invoiced["final_amount_cents"] != invoiced["gross_amount_cents"], (
            "the two variants must diverge on an order that straddles a tier boundary"
        )
        assert invoiced["volume_true_up_cents"] == -150000, (
            "the signed true-up is final minus gross, that is -150000 cents, got "
            f"{invoiced['volume_true_up_cents']}"
        )
        assert invoiced["net_amount_cents"] == 1300022, (
            "net_amount_cents is set equal to final_amount_cents, got "
            f"{invoiced['net_amount_cents']}"
        )
        assert invoiced["posted_period"] == "2026-08", (
            "invoicing stamps posted_period from the programme's current_period "
            f"2026-08, got {invoiced['posted_period']}"
        )
        assert invoiced["fulfillment_status"] == "ISSUED", (
            "the delivery dimension reads ISSUED after issuance, got "
            f"{invoiced['fulfillment_status']}"
        )
        assert invoiced["settlement_status"] == "INVOICED", (
            "the cash dimension reads INVOICED after invoicing, got "
            f"{invoiced['settlement_status']}"
        )

    def test_agreement_and_programme_ledgers_absorb_both_variants(self):
        """PRD §3.3: "Its effects reach three rows: the agreement's `drawn_miles` increases by `order_miles`, the agreement's `prepayment_balance_miles` increases by the same `order_miles` (these are miles bought but not yet distributed to members), and the programme's `deferred_revenue_cents` increases by `gross_amount_cents`."
        PRD §3.3: "Invoicing then adds `volume_true_up_cents` to the programme's `deferred_revenue_cents`, which may therefore reduce it, and stamps `posted_period` from the programme's `current_period`."

        Design: Difficulty/dual_variant_calc/mile_order_provisional_vs_final_tier_pricing
        """
        program, _, agreement, _ = _agreement_drawn_to_4999990("SkyMiles Core")
        order = _straddling_second_order(agreement["id"])
        issue_order(order["id"])
        invoice_order(order["id"])

        final_agreement = read_agreement(agreement["id"])
        final_program = read_program(program["id"])

        assert_mile_sale_agreement(final_agreement)
        assert_loyalty_program(final_program)
        assert final_agreement["drawn_miles"] == 6000005, (
            "the two issued draws of 4999990 and 1000015 miles sum to 6000005 drawn "
            f"miles, got {final_agreement['drawn_miles']}"
        )
        assert final_program["deferred_revenue_cents"] == 9300006, (
            "7999984 plus 1450022 credited at issuance, less the 150000-cent true-up "
            f"booked at invoicing, is 9300006 cents, got "
            f"{final_program['deferred_revenue_cents']}"
        )


class TestFinalAmountPerSliceRounding:
    """Where the rounding step sits inside the final pricing variant."""

    def test_each_tier_slice_is_rounded_to_whole_cents_before_the_slices_are_summed(self):
        """PRD §3.3: "That interval is cut at every `threshold_miles` in the schedule, producing one slice for each tier the order actually traverses; each slice has a mile count and takes the `price_per_mile_centicents` of the tier whose threshold opens it, thresholds being inclusive lower bounds so an interval starting exactly on a threshold opens at that tier."
        PRD §3.3: "For each slice, the slice's mile count is multiplied by that slice's centicent price, divided by 100, and **rounded half up to whole cents individually**; `final_amount_cents` is then the sum of those already-rounded slice amounts."
        PRD §3.3: "Summing the exact centicent products first and rounding once at the end is not the rule and can differ by a cent."

        Design: Difficulty/combinatorial_formula/mile_order_final_amount_rounds_per_tier_slice_then_sums
        """
        _, _, agreement, _ = _agreement_drawn_to_4999990("SkyMiles Rounding Lab")
        order = _straddling_second_order(agreement["id"])
        issue_order(order["id"])

        invoiced = invoice_order(order["id"])

        assert invoiced["final_amount_cents"] == 1300022, (
            "rounding the 10-mile slice at 145 centicents and the 1000005-mile slice "
            "at 130 centicents individually before summing gives 1300022 cents, got "
            f"{invoiced['final_amount_cents']}"
        )
        assert invoiced["final_amount_cents"] != 1300021, (
            "1300021 cents is the sum-then-round answer, which is explicitly not the "
            "rule"
        )
        assert invoiced["settlement_status"] == "INVOICED", (
            "the settlement dimension advances PENDING -> INVOICED, got "
            f"{invoiced['settlement_status']}"
        )

    def test_opening_tier_quote_and_the_negative_true_up_it_produces(self):
        """PRD §3.3: "That entry's `price_per_mile_centicents` is stamped as `provisional_tier_price_centicents`, and `gross_amount_cents` is the `order_miles` multiplied by that centicent price, divided by 100 to convert centicents to cents, rounded half up."
        PRD §3.3: "From there, `volume_true_up_cents` is `final_amount_cents` minus `gross_amount_cents` — signed, and negative whenever marginal slicing beat the provisional single-tier quote — and `net_amount_cents` is set equal to `final_amount_cents`."

        Design: Difficulty/combinatorial_formula/mile_order_final_amount_rounds_per_tier_slice_then_sums
        """
        _, _, agreement, first_order = _agreement_drawn_to_4999990(
            "SkyMiles Rounding Lab"
        )

        assert first_order["gross_amount_cents"] == 7999984, (
            "4999990 miles quoted at the opening 160-centicent tier is 7999984 cents, "
            f"got {first_order['gross_amount_cents']}"
        )

        order = _straddling_second_order(agreement["id"])
        issue_order(order["id"])
        invoiced = invoice_order(order["id"])

        assert invoiced["volume_true_up_cents"] == -150000, (
            "per-slice repricing beats the single-tier quote by 150000 cents, so the "
            f"signed true-up is -150000, got {invoiced['volume_true_up_cents']}"
        )


class TestOrderFulfillmentAndSettlementDimensions:
    """The cash axis of an order is gated by its delivery axis."""

    def test_invoicing_a_pending_order_is_refused_and_moves_neither_dimension(self, api):
        """PRD §3.3: "Invoicing is the `RevenueAccountant`'s act, requires `settlement_status` to be `PENDING` and `fulfillment_status` to be `ISSUED`, and is refused while the programme is `LOCKED`."
        PRD §2.9: "The target row is in a state from which the requested transition exists, per the state machines described throughout §3 — otherwise `ERR_INVALID_STATE` (409)."
        PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."

        Design: Difficulty/non_linear_state_machine/mile_purchase_order_parallel_fulfillment_and_settlement_dimensions
        """
        program, _, agreement, order = _flat_agreement_with_pending_order(
            "SkyMiles Order Axes"
        )

        response = api.invoice_order(order["id"], REVENUE_ACCOUNTANT)

        validate_error(response, "ERR_INVALID_STATE", 409)

        unchanged = validate_success(
            api.get_mile_purchase_order(order["id"], PARTNER_MANAGER)
        )
        assert unchanged["settlement_status"] == "PENDING", (
            "a refused invoice leaves the cash dimension at PENDING, got "
            f"{unchanged['settlement_status']}"
        )
        assert unchanged["fulfillment_status"] == "PENDING", (
            "a refused invoice leaves the delivery dimension at PENDING, got "
            f"{unchanged['fulfillment_status']}"
        )
        assert read_program(program["id"])["deferred_revenue_cents"] == 0, (
            "nothing is credited to deferred revenue while the order is undelivered"
        )
        assert read_agreement(agreement["id"])["drawn_miles"] == 0, (
            "a refused invoice draws no miles against the agreement"
        )

    def test_the_two_dimensions_advance_independently_to_issued_and_settled(self):
        """PRD §3.3: "The two status dimensions on an order then evolve independently: `fulfillment_status` tracks mile delivery through `PENDING`, `ISSUED` and `REVERSED`, while `settlement_status` tracks cash through `PENDING`, `INVOICED`, `SETTLED` and `WRITTEN_OFF`."
        PRD §3.3: "Settling is a bookkeeping acknowledgement by a `RevenueAccountant` that the cash arrived: it requires `settlement_status` to be `INVOICED` and moves it `INVOICED → SETTLED`."
        PRD §3.3: "An order that stays entirely inside its starting tier produces exactly one slice, so `final_amount_cents` equals `gross_amount_cents` and `volume_true_up_cents` is zero."

        Design: Difficulty/non_linear_state_machine/mile_purchase_order_parallel_fulfillment_and_settlement_dimensions
        """
        _, _, _, order = _flat_agreement_with_pending_order("SkyMiles Order Axes")

        issue_order(order["id"])
        invoice_order(order["id"])
        settled = settle_order(order["id"])

        assert_mile_purchase_order(settled)
        assert settled["fulfillment_status"] == "ISSUED", (
            "the delivery dimension stays at ISSUED while the cash dimension moves on, "
            f"got {settled['fulfillment_status']}"
        )
        assert settled["settlement_status"] == "SETTLED", (
            "the cash dimension ends at SETTLED, got "
            f"{settled['settlement_status']}"
        )
        assert settled["gross_amount_cents"] == 200000, (
            "100000 miles at 200 centicents is 200000 cents, got "
            f"{settled['gross_amount_cents']}"
        )
        assert settled["final_amount_cents"] == 200000, (
            "an order inside its starting tier reprices to the same 200000 cents, got "
            f"{settled['final_amount_cents']}"
        )
        assert settled["volume_true_up_cents"] == 0, (
            "a single-slice order books no true-up, got "
            f"{settled['volume_true_up_cents']}"
        )
        assert settled["net_amount_cents"] == 200000, (
            "net_amount_cents equals final_amount_cents at 200000 cents, got "
            f"{settled['net_amount_cents']}"
        )

    def test_issuance_moves_the_agreement_and_programme_rows(self):
        """PRD §3.3: "Its effects reach three rows: the agreement's `drawn_miles` increases by `order_miles`, the agreement's `prepayment_balance_miles` increases by the same `order_miles` (these are miles bought but not yet distributed to members), and the programme's `deferred_revenue_cents` increases by `gross_amount_cents`."

        Design: Difficulty/non_linear_state_machine/mile_purchase_order_parallel_fulfillment_and_settlement_dimensions
        """
        program, _, agreement, order = _flat_agreement_with_pending_order(
            "SkyMiles Order Axes"
        )

        issue_order(order["id"])
        invoice_order(order["id"])
        settle_order(order["id"])

        final_agreement = read_agreement(agreement["id"])
        final_program = read_program(program["id"])

        assert final_agreement["drawn_miles"] == 100000, (
            "issuing the 100000-mile order lifts drawn_miles to 100000, got "
            f"{final_agreement['drawn_miles']}"
        )
        assert final_agreement["prepayment_balance_miles"] == 100000, (
            "the same 100000 miles sit in prepayment_balance_miles, got "
            f"{final_agreement['prepayment_balance_miles']}"
        )
        assert final_program["deferred_revenue_cents"] == 200000, (
            "the programme's deferred revenue carries the 200000-cent gross amount, "
            f"got {final_program['deferred_revenue_cents']}"
        )


class TestOrderRequiresAnActiveAgreement:
    """A RATIFIED parent is not yet a drawable parent."""

    def _ratified_but_not_activated(self):
        program = create_program(name="SkyMiles Gate", current_period="2026-08")
        issuer = create_issuer(
            program["id"],
            name="Northbank Card Services",
            annual_mile_purchase_cap_miles=5_000_000,
        )
        agreement = draft_agreement(
            issuer["id"],
            term_start_date="2026-09-01",
            term_end_date="2027-08-31",
            committed_volume_miles=2_000_000,
            tier_schedule=tier_schedule((0, 170)),
        )
        submit_agreement(agreement["id"])
        ratify_agreement(agreement["id"])
        return program, issuer, read_agreement(agreement["id"])

    def test_drawing_against_a_ratified_agreement_is_refused_as_invalid_state(self, api):
        """PRD §2.9: "This rung also carries the parent-state preconditions of create operations: the issuer must be `ACTIVE`, the agreement must be `ACTIVE` before an order may be drawn against it, a referenced campaign must be `LIVE`, a booking must be `HELD` before it is ticketed or cancelled, and a fraud case must be in the status its transition demands."
        PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."

        Design: Difficulty/cross_entity_state_dependency/mile_purchase_order_requires_agreement_active_not_merely_ratified
        """
        program, _, agreement = self._ratified_but_not_activated()

        response = api.create_mile_purchase_order(
            mile_purchase_order_payload(agreement["id"], 100_000, agreement["version"]),
            PARTNER_MANAGER,
        )

        validate_error(response, "ERR_INVALID_STATE", 409)
        assert response.status_code != 412, (
            "the state rung precedes the version rung, so a current version must not "
            "be reported as a precondition failure"
        )
        assert response.json()["data"]["error_id"] != "ERR_STALE_VERSION", (
            "the supplied expected_agreement_version is the agreement's current "
            "version, so ERR_STALE_VERSION is not the answer"
        )

        untouched = read_agreement(agreement["id"])
        assert untouched["status"] == "RATIFIED", (
            "the refused draw leaves the agreement in RATIFIED, got "
            f"{untouched['status']}"
        )
        assert untouched["drawn_miles"] == 0, (
            f"the refused draw moves no miles, got {untouched['drawn_miles']}"
        )
        orders, meta = validate_paginated(
            api.list_mile_purchase_orders(
                PARTNER_MANAGER, params={"agreement_id": agreement["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"no order row may be retained, got total_count {meta['total_count']}"
        )
        assert orders == [], f"no order row may be retained, got {len(orders)}"
        assert read_program(program["id"])["deferred_revenue_cents"] == 0, (
            "the refused draw credits no deferred revenue"
        )

    def test_the_identical_draw_succeeds_once_the_agreement_is_activated(self, api):
        """PRD §3.2: "Activation is the last governed step: a `ContractsOfficer` moves a `RATIFIED` agreement to `ACTIVE`, which is the state in which mile purchase orders become creatable, and this too requires the issuer to be `ACTIVE`."
        PRD §3.3: "That entry's `price_per_mile_centicents` is stamped as `provisional_tier_price_centicents`, and `gross_amount_cents` is the `order_miles` multiplied by that centicent price, divided by 100 to convert centicents to cents, rounded half up."

        Design: Difficulty/cross_entity_state_dependency/mile_purchase_order_requires_agreement_active_not_merely_ratified
        """
        _, issuer, agreement = self._ratified_but_not_activated()
        rejected = api.create_mile_purchase_order(
            mile_purchase_order_payload(agreement["id"], 100_000, agreement["version"]),
            PARTNER_MANAGER,
        )
        validate_error(rejected, "ERR_INVALID_STATE", 409)

        activated = validate_success(
            api.activate_agreement(agreement["id"], CONTRACTS_OFFICER)
        )
        assert activated["status"] == "ACTIVE", (
            f"activation moves the agreement to ACTIVE, got {activated['status']}"
        )

        accepted = api.create_mile_purchase_order(
            mile_purchase_order_payload(agreement["id"], 100_000, activated["version"]),
            PARTNER_MANAGER,
        )

        order = validate_success(accepted, expected_status=201)
        assert_mile_purchase_order(order)
        assert order["gross_amount_cents"] == 170000, (
            "100000 miles at the opening 170-centicent tier is 170000 cents, got "
            f"{order['gross_amount_cents']}"
        )
        assert_co_brand_issuer(
            validate_success(api.get_co_brand_issuer(issuer["id"], PARTNER_MANAGER))
        )
