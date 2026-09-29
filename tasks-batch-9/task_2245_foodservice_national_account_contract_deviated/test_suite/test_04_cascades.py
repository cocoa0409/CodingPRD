"""Two multi-hop cascades, each with a different origin and a different
terminus: an issued dispute credit that unwinds two ledger counters, and an
activated cost change notice that ends by closing a permission gate.
"""
from test_helpers import (
    AUG_31,
    NOV_START,
    SEP_START,
    TERM_START,
    api_client,
    bootstrap_partners,
    build_active_deviation,
    build_signed_contract,
    build_two_band_pricing_world,
    acknowledge_notice,
    activate_notice,
    create_dispute,
    create_notice,
    create_product,
    issue_credit,
    resolve_dispute,
    set_clock,
    start_audit,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANALYST, NAM


def _build_upheld_dispute_world():
    """A closed rebate period carrying 113400 cents of accrued rebate, with an
    UPHELD dispute on its first line audited down to 4578 per case."""
    world = build_two_band_pricing_world(close_clock=SEP_START)

    dispute = create_dispute(
        world["line_a_id"], world["operator_id"], 4578, "TIER_MISAPPLIED"
    )
    start_audit(dispute["id"])
    world["dispute"] = resolve_dispute(
        dispute["id"], "UPHELD", "Volume band 500+ applied retroactively"
    )
    world["dispute_id"] = dispute["id"]
    return world


class TestDisputeCreditCascade:
    def test_credit_rewrites_the_dispute_and_then_the_invoice_line(self):
        """PRD §3.9: "**Hop two,** caused by hop one: the order line moves
        `pricing_status` from `INVOICED` or `REPRICED` to `CREDITED`, its
        `invoiced_unit_price_cents` is rewritten to
        `audited_correct_unit_price_cents`, `extended_price_cents` and
        `invoice_total_cents` are recomputed from that rewritten price,
        `credited_amount_cents` is increased by `credit_amount_cents`, and the
        line's `version` is incremented by 1."

        Design: Difficulty/transitive_cascade/dispute_credit_cascade_line_period_contract_manufacturer
        """
        world = _build_upheld_dispute_world()

        credited = issue_credit(world["dispute_id"])
        assert credited["status"] == "CREDIT_ISSUED"
        # 147 cents of variance across 300 cases.
        assert credited["credit_amount_cents"] == 44100

        line = validate_success(api_client.get_order_line(world["line_a_id"], NAM))
        assert line["pricing_status"] == "CREDITED"
        assert line["invoiced_unit_price_cents"] == 4578
        assert line["extended_price_cents"] == 1373400
        assert line["credited_amount_cents"] == 44100

    def test_credit_reopens_the_period_and_unwinds_both_rebate_ledgers(self):
        """PRD §3.9: "**Hop four,** caused by hop three: the contract's
        `rebate_payable_cents` is decreased by that period's
        `operator_rebate_cents` and the funding manufacturer's
        `rebate_funding_payable_cents` by that period's
        `manufacturer_funded_cents`, the contract's `compliance_posture` is
        recomputed, and the `version` of both the contract and the manufacturer
        is incremented by 1."

        Design: Difficulty/transitive_cascade/dispute_credit_cascade_line_period_contract_manufacturer
        """
        world = _build_upheld_dispute_world()

        before = world["rebate_period"]
        assert before["operator_rebate_cents"] == 113400
        assert before["manufacturer_funded_cents"] == 68040
        contract_before = validate_success(
            api_client.get_contract(world["contract_id"], NAM)
        )
        assert contract_before["rebate_payable_cents"] == 113400

        issue_credit(world["dispute_id"])

        period = validate_success(
            api_client.get_rebate_period(world["rebate_period_id"], NAM)
        )
        assert period["status"] == "OPEN"
        assert period["reopen_count"] == 1
        assert period["compliance_pct"] is None
        assert period["operator_rebate_cents"] is None

        contract = validate_success(
            api_client.get_contract(world["contract_id"], NAM)
        )
        assert contract["rebate_payable_cents"] == 0
        assert contract["compliance_posture"] == "OPEN"

        manufacturer = validate_success(
            api_client.get_manufacturer(world["manufacturer_id"], NAM)
        )
        assert manufacturer["rebate_funding_payable_cents"] == 0

        # The second line of the same period was not part of the cascade.
        line_b = validate_success(api_client.get_order_line(world["line_b_id"], NAM))
        assert line_b["pricing_status"] == "INVOICED"


def _build_indexed_notice_world():
    """A market-indexed item carrying an ACTIVE cost-plus-protected deviation
    whose ceiling sits only 100 cents above its current net price, an approved
    second deviation waiting to be activated, and an acknowledged notice that
    lifts the published index to 112.00.
    """
    world = bootstrap_partners()
    chicken = create_product(
        world["manufacturer_id"],
        is_market_indexed=True,
        index_baseline_value=100.00,
        index_baseline_cost_cents=4200,
    )
    beef = create_product(
        world["manufacturer_id"],
        sku="P-BEEF",
        description="Beef Chuck 4/10#",
        last_cost_cents=6000,
        avg_cost_cents=5900,
        replacement_cost_cents=6100,
    )
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        notice_period_days=30,
    )
    world.update(signed)

    world["deviation"] = build_active_deviation(
        signed["contract_id"],
        chicken["id"],
        world["manufacturer_id"],
        4000,
        TERM_START,
        NOV_START,
        bill_back_basis="COST_PLUS_PROTECTED",
        protected_discount_cents=300,
    )
    world["deviation_id"] = world["deviation"]["id"]

    world["second_deviation"] = build_active_deviation(
        signed["contract_id"],
        beef["id"],
        world["manufacturer_id"],
        6200,
        TERM_START,
        NOV_START,
        stage="MANUFACTURER_APPROVED",
        requested_net_price_cents=5800,
    )
    world["second_deviation_id"] = world["second_deviation"]["id"]

    notice = create_notice(
        signed["contract_id"],
        chicken["id"],
        AUG_31,
        published_index_value=112.00,
    )
    acknowledge_notice(notice["id"], world["operator_id"])
    set_clock(AUG_31)

    world["chicken"] = chicken
    world["chicken_id"] = chicken["id"]
    world["notice"] = notice
    world["notice_id"] = notice["id"]
    return world


class TestPriceNoticeActivationCascade:
    def test_index_reset_rewrites_the_cost_and_re_derives_the_protected_price(self):
        """PRD §3.6: "**Hop one:** the product's cost field named by `cost_basis`
        is overwritten with `new_cost_cents`, `cost_effective_at` is stamped with
        the logical clock, and the product's `version` is incremented by 1."

        Design: Difficulty/transitive_cascade/price_notice_activation_cascade_cost_deviation_breach_posture
        """
        world = _build_indexed_notice_world()

        # 4200 * 112.00 / 100.00 = 4704, a 12.00 percent major change.
        assert world["notice"]["new_cost_cents"] == 4704
        assert world["notice"]["delta_pct"] == 12.00
        assert world["notice"]["notice_required_days"] == 30
        assert world["notice"]["earliest_effective_at"].startswith("2026-08-31T00:00:00")

        activated = activate_notice(world["notice_id"])
        assert activated["status"] == "EFFECTIVE"

        product = validate_success(api_client.get_product(world["chicken_id"], NAM))
        assert product["last_cost_cents"] == 4704
        assert product["cost_effective_at"].startswith("2026-08-31T00:00:00")

        deviation = validate_success(
            api_client.get_deviation_agreement(world["deviation_id"], ANALYST)
        )
        assert deviation["deviated_price_cents"] == 4404
        assert deviation["price_revision_count"] == 1

    def test_breach_restricts_the_contract_and_blocks_the_next_activation(self):
        """PRD §3.6: "**Hop four,** caused by hop three: once
        `deviation_breach_count` reaches one — a single breach is enough — the
        contract's `compliance_posture` is recomputed to `RESTRICTED`, which from
        that moment blocks activating any further deviation agreement and blocks
        opening any amendment, both with `ERR_CONTRACT_POSTURE_RESTRICTED`."

        Design: Difficulty/transitive_cascade/price_notice_activation_cascade_cost_deviation_breach_posture
        """
        world = _build_indexed_notice_world()

        activate_notice(world["notice_id"])

        breached = validate_success(
            api_client.get_deviation_agreement(world["deviation_id"], ANALYST)
        )
        assert breached["status"] == "PRICE_CEILING_BREACHED"

        contract = validate_success(
            api_client.get_contract(world["contract_id"], NAM)
        )
        assert contract["deviation_breach_count"] == 1
        assert contract["compliance_posture"] == "RESTRICTED"

        refused = api_client.activate_deviation_agreement(
            world["second_deviation_id"], NAM
        )
        validate_error(refused, "ERR_CONTRACT_POSTURE_RESTRICTED", 409)

        # The fixed-net-price agreement was never re-derived by the cascade.
        untouched = validate_success(
            api_client.get_deviation_agreement(world["second_deviation_id"], ANALYST)
        )
        assert untouched["status"] == "MANUFACTURER_APPROVED"
        assert untouched["deviated_price_cents"] == 5800
