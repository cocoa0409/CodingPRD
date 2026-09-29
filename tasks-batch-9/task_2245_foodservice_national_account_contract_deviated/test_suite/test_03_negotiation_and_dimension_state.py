"""Two rows in this service move through non-linear state shapes: the deviation
agreement runs a bounded negotiation cycle, and the order line carries two
status dimensions that advance on unrelated triggers.
"""
from test_helpers import (
    ANALYST_USER_ID,
    AUG_06,
    NOV_START,
    SEP_START,
    TERM_START,
    api_client,
    bootstrap_partners,
    build_deviated_line_world,
    build_signed_contract,
    build_submitted_claim,
    create_deviation,
    create_product,
    create_remittance,
    decide_deviation,
    invoice_order_line,
    reprice_order_line,
    set_clock,
    submit_deviation,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANALYST, NAM

COST_PLUS_300 = {
    "bill_back_basis": "COST_PLUS_PROTECTED",
    "protected_discount_cents": 300,
}


def _build_draft_deviation():
    """A DRAFT cost-plus-protected deviation on a live contract, ready to be
    walked around the negotiation loop."""
    world = bootstrap_partners()
    product = create_product(world["manufacturer_id"])
    signed = build_signed_contract(
        world["operator_id"], world["manufacturer_id"], world["dc_id"]
    )
    world.update(signed)
    world["deviation"] = create_deviation(
        signed["contract_id"],
        product["id"],
        world["manufacturer_id"],
        4500,
        TERM_START,
        NOV_START,
        **COST_PLUS_300,
    )
    world["deviation_id"] = world["deviation"]["id"]
    return world


def _request_revision(deviation_id, manufacturer_id, note):
    return decide_deviation(deviation_id, manufacturer_id, "REQUEST_REVISION", note)


class TestNegotiationCycleIsBounded:
    def test_each_return_trip_through_revision_requested_advances_the_round(self):
        """PRD §3.4: "The two submit paths differ in exactly one respect: the
        `DRAFT → SUBMITTED` path leaves `revision_round` alone, while the
        `REVISION_REQUESTED → SUBMITTED` path increments `revision_round` by 1
        before the agreement is submitted again."

        Design: Difficulty/non_linear_state_machine/deviation_negotiation_cycle_capped_at_three_rounds
        """
        world = _build_draft_deviation()
        deviation_id = world["deviation_id"]
        manufacturer_id = world["manufacturer_id"]

        # Cost 4200 less the 300 protected discount.
        assert world["deviation"]["deviated_price_cents"] == 3900
        assert world["deviation"]["revision_round"] == 0

        first = submit_deviation(deviation_id)
        assert first["status"] == "SUBMITTED"
        assert first["revision_round"] == 0
        assert first["submitted_by_user_id"] == ANALYST_USER_ID

        for expected_round, note in (
            (1, "Net price too aggressive for Q3"),
            (2, "Still short of program funding"),
            (3, "Third pass requested"),
        ):
            handed_back = _request_revision(deviation_id, manufacturer_id, note)
            assert handed_back["status"] == "REVISION_REQUESTED"
            resubmitted = submit_deviation(deviation_id)
            assert resubmitted["status"] == "SUBMITTED"
            assert resubmitted["revision_round"] == expected_round

    def test_a_fourth_resubmission_is_refused_and_leaves_the_round_at_three(self):
        """PRD §3.4: "A fourth submission attempt — one made while
        `revision_round` has already reached three — is rejected with
        `ERR_MAX_REVISION_ROUNDS_EXCEEDED`, which is what bounds the
        `SUBMITTED → REVISION_REQUESTED → SUBMITTED` negotiation loop."

        Design: Difficulty/non_linear_state_machine/deviation_negotiation_cycle_capped_at_three_rounds
        """
        world = _build_draft_deviation()
        deviation_id = world["deviation_id"]
        manufacturer_id = world["manufacturer_id"]

        submit_deviation(deviation_id)
        for note in (
            "Net price too aggressive for Q3",
            "Still short of program funding",
            "Third pass requested",
        ):
            _request_revision(deviation_id, manufacturer_id, note)
            submit_deviation(deviation_id)

        handed_back = _request_revision(
            deviation_id, manufacturer_id, "Fourth pass requested"
        )
        assert handed_back["status"] == "REVISION_REQUESTED"
        assert handed_back["revision_round"] == 3

        refused = api_client.submit_deviation_agreement(deviation_id, ANALYST)
        validate_error(refused, "ERR_MAX_REVISION_ROUNDS_EXCEEDED", 409)

        unchanged = validate_success(
            api_client.get_deviation_agreement(deviation_id, ANALYST)
        )
        assert unchanged["revision_round"] == 3
        assert unchanged["status"] == "REVISION_REQUESTED"


def _build_claimed_line_world():
    """One invoiced 300-case line under an ACTIVE cost-plus-protected deviation,
    swept into a SUBMITTED bill-back claim of 247500 cents."""
    world = build_deviated_line_world(
        deviation_max_operator_price_cents=4500,
        deviation_overrides=dict(COST_PLUS_300),
        deviation_to=NOV_START,
    )
    set_clock(AUG_06)
    world["claim"] = build_submitted_claim(
        world["deviation_id"], TERM_START, SEP_START
    )
    world["claim_id"] = world["claim"]["id"]
    return world


class TestPricingAndBillbackDimensionsAreIndependent:
    def test_recovery_lands_while_the_pricing_dimension_sits_at_repriced(self):
        """PRD §3.5: "Neither dimension constrains the other: the bill-back
        dimension advances on its own triggers, so a line that has reached
        `CREDITED` on the pricing side may still be `CLAIMED` on the bill-back
        side, and a line whose recovery has reached `RECOVERED` may still be
        repriced."

        Design: Difficulty/non_linear_state_machine/order_line_pricing_and_billback_dimensions_advance_independently
        """
        world = _build_claimed_line_world()

        assert world["order_line"]["list_unit_price_cents"] == 4725
        assert world["order_line"]["invoiced_unit_price_cents"] == 3900
        assert world["order_line"]["extended_price_cents"] == 1170000
        assert world["claim"]["claimed_amount_cents"] == 247500

        repriced = reprice_order_line(world["order_line_id"])
        assert repriced["pricing_status"] == "REPRICED"
        assert repriced["billback_status"] == "CLAIMED"

        create_remittance(world["manufacturer_id"], 247500)

        claim = validate_success(
            api_client.get_bill_back_claim(world["claim_id"], NAM)
        )
        assert claim["status"] == "RECOVERED"

        # The row legitimately sits at (REPRICED, RECOVERED).
        line = validate_success(api_client.get_order_line(world["order_line_id"], NAM))
        assert line["billback_status"] == "RECOVERED"
        assert line["pricing_status"] == "REPRICED"

    def test_re_invoicing_closes_the_pricing_cycle_without_touching_recovery(self):
        """PRD §3.5: "Invoicing a repriced line moves it `REPRICED → INVOICED`
        again, so `INVOICED → REPRICED → INVOICED` is a legitimate cycle inside
        the pricing dimension."

        Design: Difficulty/non_linear_state_machine/order_line_pricing_and_billback_dimensions_advance_independently
        """
        world = _build_claimed_line_world()

        reprice_order_line(world["order_line_id"])
        create_remittance(world["manufacturer_id"], 247500)
        final = invoice_order_line(world["order_line_id"])

        assert final["pricing_status"] == "INVOICED"
        assert final["billback_status"] == "RECOVERED"
        # The deviation is still ACTIVE, so neither move changed the price.
        assert final["invoiced_unit_price_cents"] == 3900
        assert final["extended_price_cents"] == 1170000
