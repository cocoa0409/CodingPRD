"""Two different conserved quantities, each put through an action and its
compensating reversal: remitted manufacturer cash, and rebate liability on one
contract.
"""
from test_helpers import (
    AUG_05,
    NOV_START,
    OCT_START,
    SEP_05,
    SEP_START,
    TERM_START,
    api_client,
    assert_manufacturer_cash_conserved,
    assert_pct,
    assert_rebate_liability_conserved,
    assert_rebate_split,
    bootstrap_partners,
    build_active_deviation,
    build_closed_period_world,
    build_signed_contract,
    build_submitted_claim,
    create_invoiced_line,
    create_product,
    create_remittance,
    open_rebate_period,
    reverse_remittance,
    settle_rebate_period,
    validate_success,
)
from test_helpers.fixtures import AUDITOR, NAM


def _build_two_claim_world():
    """One manufacturer owing 412500 cents across two submitted claims on
    disjoint sweep windows: 247500 for August and 165000 for September."""
    world = bootstrap_partners()
    product = create_product(world["manufacturer_id"])
    signed = build_signed_contract(
        world["operator_id"], world["manufacturer_id"], world["dc_id"]
    )
    world.update(signed)
    world["deviation"] = build_active_deviation(
        signed["contract_id"],
        product["id"],
        world["manufacturer_id"],
        4500,
        TERM_START,
        NOV_START,
        requested_net_price_cents=3900,
    )
    world["deviation_id"] = world["deviation"]["id"]

    world["periods"] = [
        open_rebate_period(signed["contract_id"], period_start, period_end)
        for period_start, period_end in ((TERM_START, SEP_START), (SEP_START, OCT_START))
    ]

    # 825 cents of bill-back delta per case: 4725 list against 3900 deviated.
    world["line_august"] = create_invoiced_line(
        signed["contract_id"],
        product["id"],
        world["dc_id"],
        world["operator_id"],
        300,
        order_clock=AUG_05,
    )
    world["line_september"] = create_invoiced_line(
        signed["contract_id"],
        product["id"],
        world["dc_id"],
        world["operator_id"],
        200,
        order_clock=SEP_05,
    )

    world["claim_august"] = build_submitted_claim(
        world["deviation_id"], TERM_START, SEP_START
    )
    world["claim_september"] = build_submitted_claim(
        world["deviation_id"], SEP_START, OCT_START
    )
    return world


def _read_claims(world):
    return [
        validate_success(api_client.get_bill_back_claim(claim["id"], NAM))
        for claim in (world["claim_august"], world["claim_september"])
    ]


def _read_manufacturer(world):
    return validate_success(
        api_client.get_manufacturer(world["manufacturer_id"], NAM)
    )


class TestManufacturerCashConservation:
    def test_surplus_cash_is_parked_rather_than_discarded(self):
        """PRD §2.10: "For any manufacturer, `total_remitted_cents` equals the sum
        of `recovered_amount_cents` across all of that manufacturer's bill-back
        claims regardless of status, plus `unapplied_credit_cents`."

        Design: Difficulty/compensating_invariant/manufacturer_remitted_cash_conserved_across_apply_and_reverse
        """
        world = _build_two_claim_world()

        assert world["claim_august"]["claimed_amount_cents"] == 247500
        assert world["claim_september"]["claimed_amount_cents"] == 165000
        assert _read_manufacturer(world)["open_claim_exposure_cents"] == 412500

        remittance = create_remittance(
            world["manufacturer_id"], 450000, remittance_reference="CPC-WIRE-0007"
        )
        assert remittance["applied_amount_cents"] == 412500
        assert remittance["unapplied_amount_cents"] == 37500

        august, september = _read_claims(world)
        assert august["recovered_amount_cents"] == 247500
        assert august["status"] == "RECOVERED"
        assert september["recovered_amount_cents"] == 165000
        assert september["status"] == "RECOVERED"

        manufacturer = _read_manufacturer(world)
        assert manufacturer["total_remitted_cents"] == 450000
        assert manufacturer["unapplied_credit_cents"] == 37500
        assert manufacturer["open_claim_exposure_cents"] == 0
        # 450000 == 247500 + 165000 + 37500.
        assert_manufacturer_cash_conserved(manufacturer, [august, september])

        for key in ("line_august", "line_september"):
            line = validate_success(
                api_client.get_order_line(world[key]["id"], NAM)
            )
            assert line["billback_status"] == "RECOVERED"

    def test_reversing_the_wire_restores_every_term_to_its_prior_value(self):
        """PRD §2.10: "Applying a remittance and reversing that remittance must
        each leave the equality true, and the reversal must restore every term —
        `total_remitted_cents`, each claim's `recovered_amount_cents`, and
        `unapplied_credit_cents` — to its pre-application value."

        Design: Difficulty/compensating_invariant/manufacturer_remitted_cash_conserved_across_apply_and_reverse
        """
        world = _build_two_claim_world()

        remittance = create_remittance(
            world["manufacturer_id"], 450000, remittance_reference="CPC-WIRE-0007"
        )
        reversed_remittance = reverse_remittance(remittance["id"])
        assert reversed_remittance["status"] == "REVERSED"

        august, september = _read_claims(world)
        assert august["recovered_amount_cents"] == 0
        assert august["status"] == "SUBMITTED"
        assert september["recovered_amount_cents"] == 0
        assert september["status"] == "SUBMITTED"

        manufacturer = _read_manufacturer(world)
        assert manufacturer["total_remitted_cents"] == 0
        assert manufacturer["unapplied_credit_cents"] == 0
        # Exactly the pre-application exposure, with no drift.
        assert manufacturer["open_claim_exposure_cents"] == 412500
        assert_manufacturer_cash_conserved(manufacturer, [august, september])

        for key in ("line_august", "line_september"):
            line = validate_success(
                api_client.get_order_line(world[key]["id"], NAM)
            )
            assert line["billback_status"] == "CLAIMED"


def _build_accrued_period_world():
    """A single 300-case line of 1417500 cents in a CLOSED period, worth 56700
    cents of operator rebate."""
    return build_closed_period_world(contract={"compliance_basis": "DOLLAR_WEIGHTED"})


def _read_contract(world):
    return validate_success(api_client.get_contract(world["contract_id"], NAM))


class TestRebateLiabilityConservation:
    def test_settlement_moves_cents_between_the_two_terms_without_changing_the_sum(
        self,
    ):
        """PRD §2.10: "Settling a period moves cents from `rebate_payable_cents`
        into `rebate_settled_total_cents` and reversing a settlement moves the
        same cents back; neither may change the sum, and after a reversal the
        manufacturer-side mirror `rebate_funding_payable_cents` must equal its
        value from before the settlement."

        Design: Difficulty/compensating_invariant/rebate_liability_conserved_across_settle_and_reversal
        """
        world = _build_accrued_period_world()
        closed = world["rebate_period"]

        assert world["order_line"]["extended_price_cents"] == 1417500
        assert world["order_line"]["is_contracted_item"] is True
        assert_pct(closed["compliance_pct"], 100.00, "compliance_pct")
        assert_pct(closed["rebate_rate_pct"], 4.00, "rebate_rate_pct")
        assert closed["operator_rebate_cents"] == 56700
        assert closed["manufacturer_funded_cents"] == 34020
        assert closed["distributor_funded_cents"] == 22680
        assert_rebate_split(closed)

        after_close = _read_contract(world)
        assert after_close["rebate_payable_cents"] == 56700
        assert after_close["rebate_settled_total_cents"] == 0
        assert_rebate_liability_conserved(after_close, [closed])
        assert (
            validate_success(
                api_client.get_manufacturer(world["manufacturer_id"], NAM)
            )["rebate_funding_payable_cents"]
            == 34020
        )

        settled = settle_rebate_period(world["rebate_period_id"])
        assert settled["status"] == "SETTLED"
        assert settled["settled_amount_cents"] == 56700

        after_settle = _read_contract(world)
        assert after_settle["rebate_payable_cents"] == 0
        assert after_settle["rebate_settled_total_cents"] == 56700
        assert_rebate_liability_conserved(after_settle, [settled])
        assert (
            validate_success(
                api_client.get_manufacturer(world["manufacturer_id"], NAM)
            )["rebate_funding_payable_cents"]
            == 0
        )

    def test_reversing_the_settlement_is_a_clean_compensating_cycle(self):
        """PRD §3.7: "The contract's `rebate_payable_cents` is increased by
        `operator_rebate_cents` and `rebate_settled_total_cents` decreased by the
        same amount, with the contract's `version` incremented by 1; the funding
        manufacturer's `rebate_funding_payable_cents` is increased by
        `manufacturer_funded_cents` with its `version` incremented by 1; the
        period's `version` is incremented by 1; and the same conservation
        equality holds before and after."

        Design: Difficulty/compensating_invariant/rebate_liability_conserved_across_settle_and_reversal
        """
        world = _build_accrued_period_world()

        settle_rebate_period(world["rebate_period_id"])
        reopened = validate_success(
            api_client.reverse_rebate_settlement(
                world["rebate_period_id"],
                {"reason": "Operator remit instructions incorrect"},
                AUDITOR,
            )
        )

        assert reopened["status"] == "CLOSED"
        assert reopened["settled_amount_cents"] == 0
        assert reopened["operator_rebate_cents"] == 56700

        contract = _read_contract(world)
        assert contract["rebate_payable_cents"] == 56700
        assert contract["rebate_settled_total_cents"] == 0
        assert_rebate_liability_conserved(contract, [reopened])

        manufacturer = validate_success(
            api_client.get_manufacturer(world["manufacturer_id"], NAM)
        )
        assert manufacturer["rebate_funding_payable_cents"] == 34020
