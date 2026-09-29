"""Where a request is refused and in what order: tier band collisions and
interchangeability, the order-line rejection ladder, notice windows and
activation timing, period windows and the payable gate, dispute and settlement
gates, claim windows and segregation of duties, inclusive term boundaries, the
ceiling check on a resolved cost-plus price, and a stranded amendment draft.
"""
from test_helpers import (
    AUG_05,
    AUG_10,
    OCT_05,
    OCT_START,
    SEP_05,
    SEP_15,
    SEP_START,
    TERM_END,
    TERM_START,
    add_substitution_rule,
    add_tier,
    acknowledge_notice,
    amendment_payload,
    api_client,
    assert_pct,
    bill_back_claim_payload,
    bootstrap_partners,
    build_active_deviation,
    build_signed_contract,
    build_submitted_claim,
    close_rebate_period,
    contract_tier_payload,
    create_contract_draft,
    create_deviation,
    create_dispute,
    create_distribution_center,
    create_invoiced_line,
    create_notice,
    create_order_line,
    create_product,
    deviation_agreement_payload,
    invoice_order_line,
    open_rebate_period,
    order_line_payload,
    price_change_notice_payload,
    pricing_dispute_payload,
    read_contract_version,
    read_deviation_version,
    rebate_period_payload,
    resolve_dispute,
    settle_rebate_period,
    set_clock,
    start_audit,
    substitution_rule_payload,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_notice,
    ACCOUNTANT_USER_ID,
    make_contract_auditor_headers,
)
from test_helpers.fixtures import ACCOUNTANT, ANALYST, AUDITOR, NAM, add_coverage

AUG_15 = "2026-08-15T00:00:00Z"
AUG_20 = "2026-08-20T00:00:00Z"
OCT_10 = "2026-10-10T00:00:00Z"
OCT_12 = "2026-10-12T00:00:00Z"
JUL_2027_START = "2027-07-01T00:00:00Z"
AUG_2027_START = "2027-08-01T00:00:00Z"
FUTURE_TERM_END = "2027-08-31T23:59:59Z"

# 4000 cents of cost on every basis, so a 25.00 percent markup lists at 5000.
FLAT_COST = {
    "last_cost_cents": 4000,
    "avg_cost_cents": 4000,
    "replacement_cost_cents": 4000,
}
PROTEIN_QUARTER = {
    "product_class_code": "PROTEIN",
    "cost_basis": "LAST_COST",
    "markup_type": "PERCENT_OF_COST",
    "markup_value": 25.00,
    "min_case_volume": 0,
}


def _chicken(manufacturer_id, **overrides):
    return create_product(manufacturer_id, **dict(FLAT_COST, **overrides))


class TestTierBandAndSubstituteGroupChecks:
    def test_an_intersecting_band_is_refused_where_a_touching_one_is_taken(self):
        """PRD §3.2: "Two `ACTIVE` tiers of the same contract and the same product
        class may not have overlapping bands: an attempt to create one whose
        half-open band intersects an existing active band for that class is
        rejected with `ERR_TIER_BAND_OVERLAP`."

        PRD §3.2: "At declaration time the two products must be genuinely
        interchangeable: they must share a non-null `substitution_group_code` and
        the same `product_class_code`, and `primary_product_id` must differ from
        `substitute_product_id`."

        Design: Corner/Validations/tier_band_overlap_and_substitute_group_mismatch_rejected
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"], substitution_group_code="CHKN")
        alternate = _chicken(
            world["manufacturer_id"],
            sku="S1-CHKN",
            description="Chicken Breast Alternate 4/10#",
            substitution_group_code="CHKN",
        )
        napkins = create_product(
            world["manufacturer_id"],
            sku="P-NAP",
            description="Dinner Napkins 6/1000",
            product_class_code="DISPOSABLES",
            pack_size=6,
            substitution_group_code="CHKN",
        )
        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )
        contract_id = contract["id"]

        entry = add_tier(
            contract_id, markup_value=25.00, min_case_volume=0, max_case_volume=500
        )
        assert entry["status"] == "ACTIVE"

        # [400, 600) intersects [0, 500) for the same class on the same contract.
        validate_error(
            api_client.create_contract_tier(
                contract_tier_payload(
                    contract_id,
                    markup_value=9.00,
                    min_case_volume=400,
                    max_case_volume=600,
                ),
                NAM,
            ),
            "ERR_TIER_BAND_OVERLAP",
            409,
        )

        # A band starting exactly where the first one ends only touches it.
        touching = add_tier(contract_id, markup_value=9.00, min_case_volume=500)
        assert touching["min_case_volume"] == 500
        assert touching["max_case_volume"] is None
        assert touching["status"] == "ACTIVE"

        # [0, 500) again, but for a different product class.
        other_class = add_tier(
            contract_id,
            product_class_code="BEVERAGE",
            cost_basis="AVG_COST",
            markup_type="DOLLARS_PER_CASE",
            markup_value=150,
            min_case_volume=0,
            max_case_volume=500,
        )
        assert other_class["status"] == "ACTIVE"

        # A different product class, then the item substituting for itself.
        for substitute_id in (napkins["id"], chicken["id"]):
            validate_error(
                api_client.create_substitution_rule(
                    substitution_rule_payload(
                        contract_id, chicken["id"], substitute_id
                    ),
                    NAM,
                ),
                "ERR_SUBSTITUTE_GROUP_MISMATCH",
                422,
            )

        rule = add_substitution_rule(contract_id, chicken["id"], alternate["id"])
        assert rule["status"] == "ACTIVE"

        tiers, tier_page = validate_paginated(
            api_client.list_contract_tiers(NAM, {"contract_id": contract_id})
        )
        assert tier_page["total_count"] == 3
        assert {tier["id"] for tier in tiers} == {
            entry["id"],
            touching["id"],
            other_class["id"],
        }
        _, rule_page = validate_paginated(
            api_client.list_substitution_rules(NAM, {"contract_id": contract_id})
        )
        assert rule_page["total_count"] == 1


class TestOrderLineRejectionLadder:
    def test_each_broken_rung_answers_in_ladder_order_until_the_line_prices(self):
        """PRD §2.8: "When a single request violates several rules, exactly one
        error is returned, and which one is fully determined by the following
        priority ladder."

        PRD §3.5: "The logical clock at the moment of the request becomes the
        line's `order_date`, which must fall inside the contract's inclusive term
        from `effective_from` to `effective_to`; outside it, the line is refused
        with `ERR_ORDER_DATE_OUTSIDE_CONTRACT_TERM`."

        Design: Corner/Validations/order_line_validation_ladder_returns_the_lowest_numbered_violation
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        milk = create_product(
            world["manufacturer_id"],
            sku="P-MILK",
            description="Whole Milk 4/1gal",
            product_class_code="BEVERAGE",
            **FLAT_COST,
        )
        boise = create_distribution_center(
            dc_code="DC-BOI",
            name="Boise DC",
            in_market_state_codes=["ID"],
            out_of_market_fee_per_case_cents=300,
        )
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
            coverages=[{"coverage_from": SEP_START, "coverage_to": FUTURE_TERM_END}],
            contract_code="HLG-FUTURE",
            effective_from=SEP_START,
            effective_to=FUTURE_TERM_END,
        )
        contract_id = signed["contract_id"]
        september = open_rebate_period(contract_id, SEP_START, OCT_START)

        # Rung 12 (422) outranks the term, coverage and period rungs below it.
        validate_error(
            api_client.create_order_line(
                order_line_payload(contract_id, milk["id"], boise["id"], 10),
                world["buyer"],
            ),
            "ERR_NO_TIER_FOR_PRODUCT_CLASS",
            422,
        )

        # The clock still stands at 2026-08-01, a month before the term opens:
        # rung 23 (422) now outranks coverage and period.
        validate_error(
            api_client.create_order_line(
                order_line_payload(contract_id, chicken["id"], boise["id"], 10),
                world["buyer"],
            ),
            "ERR_ORDER_DATE_OUTSIDE_CONTRACT_TERM",
            422,
        )

        set_clock(SEP_05)
        # Inside the term now, so rung 30 (409) is the lowest one still broken.
        validate_error(
            api_client.create_order_line(
                order_line_payload(contract_id, chicken["id"], boise["id"], 10),
                world["buyer"],
            ),
            "ERR_DC_NOT_COVERED",
            409,
        )

        line = create_order_line(
            contract_id,
            chicken["id"],
            world["dc_id"],
            world["operator_id"],
            10,
        )
        assert line["order_date"].startswith("2026-09-05T00:00:00")
        assert line["list_unit_price_cents"] == 5000
        assert line["invoiced_unit_price_cents"] == 5000
        assert line["extended_price_cents"] == 50000
        assert line["service_fee_cents"] == 0
        assert line["rebate_period_id"] == september["id"]
        assert line["pricing_status"] == "DRAFT_PRICED"

        set_clock(OCT_05)
        # October is covered and inside the term, but no OPEN period holds it.
        validate_error(
            api_client.create_order_line(
                order_line_payload(contract_id, chicken["id"], world["dc_id"], 10),
                world["buyer"],
            ),
            "ERR_NO_OPEN_REBATE_PERIOD",
            409,
        )

        _, page = validate_paginated(
            api_client.list_order_lines(NAM, {"contract_id": contract_id})
        )
        assert page["total_count"] == 1


class TestNoticeWindowAndActivationTiming:
    def test_the_rolling_slot_and_the_effective_instant_both_bind(self):
        """PRD §3.6: "One further guard protects the operator from notice churn on
        the same item: if any other notice on the same product in `PENDING` or
        `ACKNOWLEDGED` status has an `effective_at` whose absolute distance from
        the new notice's `effective_at` is strictly less than thirty days, the new
        notice is refused with `ERR_NOTICE_WINDOW_CONFLICT`."

        PRD §3.6: "Activation belongs to the `PricingAnalyst`, requires the notice
        to be `ACKNOWLEDGED`, requires the contract to be `ACTIVE`, and requires
        the logical clock to have reached or passed `effective_at` — an early
        activation is `ERR_NOTICE_NOT_YET_EFFECTIVE`."

        Design: Corner/Validations/notice_rolling_window_and_activation_timing_enforced
        """
        world = bootstrap_partners()
        product_a = _chicken(world["manufacturer_id"])
        product_b = _chicken(
            world["manufacturer_id"],
            sku="P-B",
            description="Chicken Thigh 4/10#",
        )
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
        )
        contract_id = signed["contract_id"]

        # 4000 -> 4400 is a 10.00 percent move, so the contract's own 30 days
        # apply and the earliest effective instant is 2026-08-31.
        first = create_notice(
            contract_id, product_a["id"], SEP_15, proposed_cost_cents=4400
        )
        assert first["status"] == "PENDING"
        assert first["new_cost_cents"] == 4400
        assert_pct(first["delta_pct"], 10.00, "delta_pct")
        assert first["notice_required_days"] == 30

        # 2026-10-10 sits 25 days from 2026-09-15 on the same product.
        validate_error(
            api_client.create_price_change_notice(
                price_change_notice_payload(
                    contract_id, product_a["id"], OCT_10, proposed_cost_cents=4400
                ),
                ANALYST,
            ),
            "ERR_NOTICE_WINDOW_CONFLICT",
            409,
        )

        # The same instant on a different product occupies its own slot.
        other_item = create_notice(
            contract_id, product_b["id"], OCT_10, proposed_cost_cents=4400
        )
        assert other_item["status"] == "PENDING"
        withdrawn = withdraw_notice(other_item["id"], "Supplier pulled the increase")
        assert withdrawn["status"] == "WITHDRAWN"

        # 2026-10-12 is 2 days from the withdrawn notice, which no longer counts.
        replacement = create_notice(
            contract_id, product_b["id"], OCT_12, proposed_cost_cents=4400
        )
        assert replacement["status"] == "PENDING"

        validate_error(
            api_client.activate_price_change_notice(first["id"], ANALYST),
            "ERR_NOTICE_INVALID_STATE",
            409,
        )
        acknowledged = acknowledge_notice(first["id"], world["operator_id"])
        assert acknowledged["status"] == "ACKNOWLEDGED"

        # The clock still stands at 2026-08-01, well short of 2026-09-15.
        validate_error(
            api_client.activate_price_change_notice(first["id"], ANALYST),
            "ERR_NOTICE_NOT_YET_EFFECTIVE",
            409,
        )

        set_clock(SEP_15)
        effective = validate_success(
            api_client.activate_price_change_notice(first["id"], ANALYST)
        )
        assert effective["status"] == "EFFECTIVE"

        moved = validate_success(api_client.get_product(product_a["id"], ANALYST))
        assert moved["last_cost_cents"] == 4400
        assert moved["cost_effective_at"].startswith("2026-09-15T00:00:00")

        # EFFECTIVE is terminal.
        validate_error(
            api_client.activate_price_change_notice(first["id"], ANALYST),
            "ERR_NOTICE_INVALID_STATE",
            409,
        )
        assert (
            validate_success(api_client.get_product(product_b["id"], ANALYST))[
                "last_cost_cents"
            ]
            == 4000
        )
        assert (
            validate_success(
                api_client.get_price_change_notice(replacement["id"], ANALYST)
            )["status"]
            == "PENDING"
        )


class TestPeriodWindowsAndTerminationGate:
    def test_a_period_closes_only_after_it_ends_and_only_a_paid_contract_ends(self):
        """PRD §3.7: "A new period's half-open window may not intersect any
        existing period of the same contract, whatever that period's status; an
        intersection is `ERR_PERIOD_OVERLAP`."

        PRD §3.7: "It is refused unless the period is `OPEN`, unless the logical
        clock has reached or passed `period_end` (otherwise
        `ERR_PERIOD_NOT_ENDED`), and unless the governing contract is `ACTIVE`,
        `SUSPENDED` or `EXPIRED` — a contract in any other status raises
        `ERR_CONTRACT_INVALID_STATE`, since a period may legitimately be closed
        after the term has run out or while the account is suspended."

        PRD §3.3: "Termination is permitted from `DRAFT`, `PENDING_SIGNATURE`,
        `ACTIVE` or `SUSPENDED`, optionally carrying a `reason`, and is refused
        while the contract still owes money: `rebate_payable_cents` must be
        exactly 0, otherwise `ERR_REBATE_PAYABLE_OUTSTANDING`."

        Design: Corner/Validations/period_window_close_timing_and_payable_gate_on_termination
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
        )
        contract_id = signed["contract_id"]
        august = open_rebate_period(contract_id, TERM_START, SEP_START)
        create_invoiced_line(
            contract_id,
            chicken["id"],
            world["dc_id"],
            world["operator_id"],
            100,
            order_clock=AUG_05,
        )

        # [2026-08-15, 2026-09-15) cuts into August's [2026-08-01, 2026-09-01).
        validate_error(
            api_client.create_rebate_period(
                rebate_period_payload(contract_id, AUG_15, SEP_15), ACCOUNTANT
            ),
            "ERR_PERIOD_OVERLAP",
            409,
        )
        september = open_rebate_period(contract_id, SEP_START, OCT_START)
        assert september["status"] == "OPEN"

        # The clock stands at 2026-08-05, short of the 2026-09-01 period end.
        validate_error(
            api_client.close_rebate_period(august["id"], ACCOUNTANT),
            "ERR_PERIOD_NOT_ENDED",
            409,
        )

        set_clock(SEP_START)
        closed = close_rebate_period(august["id"])
        assert closed["status"] == "CLOSED"
        assert_pct(closed["compliance_pct"], 100.00, "compliance_pct")
        assert_pct(closed["rebate_rate_pct"], 4.00, "rebate_rate_pct")
        assert closed["operator_rebate_cents"] == 20000
        assert closed["manufacturer_funded_cents"] == 12000
        assert closed["distributor_funded_cents"] == 8000

        owing = validate_success(api_client.get_contract(contract_id, NAM))
        assert owing["rebate_payable_cents"] == 20000
        validate_error(
            api_client.terminate_contract(
                contract_id, NAM, {"reason": "Operator sold the group"}
            ),
            "ERR_REBATE_PAYABLE_OUTSTANDING",
            409,
        )
        assert (
            validate_success(api_client.get_contract(contract_id, NAM))["status"]
            == "ACTIVE"
        )

        settled = settle_rebate_period(august["id"], "WIRE-2026-09-01")
        assert settled["status"] == "SETTLED"
        assert settled["settled_amount_cents"] == 20000
        paid = validate_success(api_client.get_contract(contract_id, NAM))
        assert paid["rebate_payable_cents"] == 0
        assert paid["rebate_settled_total_cents"] == 20000

        terminated = validate_success(
            api_client.terminate_contract(
                contract_id, NAM, {"reason": "Operator sold the group"}
            )
        )
        assert terminated["status"] == "TERMINATED"
        assert (
            validate_success(
                api_client.get_contract_tier(signed["tier_ids"][0], NAM)
            )["status"]
            == "SUPERSEDED"
        )
        assert (
            validate_success(
                api_client.get_dc_coverage(signed["coverage_ids"][0], NAM)
            )["status"]
            == "ENDED"
        )
        # Rebate periods are not part of the termination cascade.
        assert (
            validate_success(api_client.get_rebate_period(september["id"], NAM))[
                "status"
            ]
            == "OPEN"
        )


class TestSettlementAndCreditGates:
    def test_an_open_dispute_holds_the_money_and_a_settled_period_refuses_a_credit(
        self,
    ):
        """PRD §3.7: "Settlement is refused while any pricing dispute in `OPEN` or
        `UNDER_AUDIT` status exists on a line assigned to this period —
        `ERR_OPEN_DISPUTES_BLOCK_SETTLEMENT` — and refused while the contract's
        `compliance_posture` is `RESTRICTED` — `ERR_CONTRACT_POSTURE_RESTRICTED`."

        PRD §3.9: "Issuing the credit for an `UPHELD` dispute is the deepest
        cascade in the service, and it is refused outright when the rebate period
        covering the credited line has already reached `SETTLED` — a settled
        period may not be reopened by a credit, and the attempt is
        `ERR_SETTLED_PERIOD_IMMUTABLE`."

        Design: Corner/Validations/open_dispute_blocks_settlement_and_settled_period_blocks_credit
        """
        world = bootstrap_partners()
        product = create_product(
            world["manufacturer_id"],
            last_cost_cents=3000,
            avg_cost_cents=3000,
            replacement_cost_cents=3000,
        )
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[
                {
                    "product_class_code": "PROTEIN",
                    "cost_basis": "LAST_COST",
                    "markup_type": "DOLLARS_PER_CASE",
                    "markup_value": 1000,
                    "min_case_volume": 0,
                    "max_case_volume": 500,
                },
                {
                    "product_class_code": "PROTEIN",
                    "cost_basis": "LAST_COST",
                    "markup_type": "DOLLARS_PER_CASE",
                    "markup_value": 980,
                    "min_case_volume": 500,
                },
            ],
        )
        contract_id = signed["contract_id"]
        august = open_rebate_period(contract_id, TERM_START, SEP_START)

        # Both lines carry the same order_date, so neither counts toward the
        # other's accumulated volume and both price from the entry band.
        big = create_invoiced_line(
            contract_id,
            product["id"],
            world["dc_id"],
            world["operator_id"],
            400,
            order_clock=AUG_05,
        )
        small = create_invoiced_line(
            contract_id, product["id"], world["dc_id"], world["operator_id"], 100
        )
        assert big["invoiced_unit_price_cents"] == 4000
        assert small["invoiced_unit_price_cents"] == 4000

        set_clock(SEP_START)
        closed = close_rebate_period(august["id"])
        # 64000 on 1600000 plus 16000 on 400000, each rounded per line.
        assert closed["operator_rebate_cents"] == 80000

        blocking = create_dispute(big["id"], world["operator_id"], 3980)
        assert blocking["status"] == "OPEN"
        validate_error(
            api_client.settle_rebate_period(
                august["id"], {"settlement_reference": "WIRE-BLOCKED"}, ACCOUNTANT
            ),
            "ERR_OPEN_DISPUTES_BLOCK_SETTLEMENT",
            409,
        )
        assert (
            validate_success(api_client.get_rebate_period(august["id"], NAM))["status"]
            == "CLOSED"
        )

        withdrawn = validate_success(
            api_client.withdraw_pricing_dispute(
                blocking["id"], world["buyer"], {"reason": "Raised in error"}
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        settled = settle_rebate_period(august["id"], "WIRE-2026-09-01")
        assert settled["status"] == "SETTLED"
        assert settled["settled_amount_cents"] == 80000

        # A settled period is final volume, so the audit itself is legal.
        later = create_dispute(small["id"], world["operator_id"], 3980)
        audited = start_audit(later["id"])
        assert audited["status"] == "UNDER_AUDIT"
        # Retroactive volume of 500 cases selects the 980-cent band: 3980.
        assert audited["audited_correct_unit_price_cents"] == 3980
        assert audited["variance_cents_per_case"] == 20
        assert_pct(audited["variance_pct"], 0.50, "variance_pct")

        upheld = resolve_dispute(later["id"], "UPHELD", "Retroactive band applies")
        assert upheld["status"] == "UPHELD"
        validate_error(
            api_client.issue_dispute_credit(later["id"], AUDITOR),
            "ERR_SETTLED_PERIOD_IMMUTABLE",
            409,
        )

        assert (
            validate_success(api_client.get_pricing_dispute(later["id"], AUDITOR))[
                "status"
            ]
            == "UPHELD"
        )
        assert (
            validate_success(api_client.get_order_line(small["id"], NAM))[
                "pricing_status"
            ]
            == "INVOICED"
        )
        final_period = validate_success(
            api_client.get_rebate_period(august["id"], NAM)
        )
        assert final_period["status"] == "SETTLED"
        assert final_period["reopen_count"] == 0


class TestClaimWindowsAndWriteOffDuties:
    def test_an_overlapping_sweep_an_empty_sweep_and_a_self_blessed_write_off(self):
        """PRD §3.8: "The window may not intersect any existing claim on the same
        agreement unless that claim has been written off; an intersection is
        `ERR_CLAIM_PERIOD_OVERLAP`."

        PRD §3.8: "A sweep that gathers no cases at all — `claimed_cases` of zero
        — is rejected with `ERR_NO_QUALIFYING_LINES`."

        PRD §2.11: "The `ContractAuditor` who writes off a bill-back claim must
        not be the `RebateAccountant` who submitted it: the writing-off
        `X-User-ID` is compared against the claim's `submitted_by_user_id`, and
        equality raises the same error."

        Design: Corner/Validations/claim_overlap_qualifying_lines_and_write_off_segregation
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
        )
        contract_id = signed["contract_id"]
        open_rebate_period(contract_id, TERM_START, SEP_START)
        deviation = build_active_deviation(
            contract_id,
            chicken["id"],
            world["manufacturer_id"],
            5000,
            TERM_START,
            OCT_START,
            requested_net_price_cents=4200,
        )
        line = create_invoiced_line(
            contract_id,
            chicken["id"],
            world["dc_id"],
            world["operator_id"],
            10,
            order_clock=AUG_05,
        )
        assert line["invoiced_unit_price_cents"] == 4200
        assert line["billback_status"] == "ACCRUED"

        claim = build_submitted_claim(deviation["id"], TERM_START, SEP_START)
        assert claim["claimed_cases"] == 10
        assert claim["claimed_amount_cents"] == 8000
        assert claim["status"] == "SUBMITTED"
        assert claim["submitted_by_user_id"] == ACCOUNTANT_USER_ID

        # [2026-08-10, 2026-08-20) sits inside the submitted claim's window.
        validate_error(
            api_client.create_bill_back_claim(
                bill_back_claim_payload(
                    deviation["id"],
                    AUG_10,
                    AUG_20,
                    read_deviation_version(deviation["id"]),
                ),
                ACCOUNTANT,
            ),
            "ERR_CLAIM_PERIOD_OVERLAP",
            409,
        )
        # September is disjoint but sweeps no line at all.
        validate_error(
            api_client.create_bill_back_claim(
                bill_back_claim_payload(
                    deviation["id"],
                    SEP_START,
                    OCT_START,
                    read_deviation_version(deviation["id"]),
                ),
                ACCOUNTANT,
            ),
            "ERR_NO_QUALIFYING_LINES",
            422,
        )

        # A ContractAuditor header carrying the submitting accountant's own id.
        validate_error(
            api_client.write_off_bill_back_claim(
                claim["id"],
                {"write_off_reason": "Manufacturer insolvent"},
                make_contract_auditor_headers(ACCOUNTANT_USER_ID),
            ),
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            409,
        )

        written_off = validate_success(
            api_client.write_off_bill_back_claim(
                claim["id"], {"write_off_reason": "Manufacturer insolvent"}, AUDITOR
            )
        )
        assert written_off["status"] == "WRITTEN_OFF"
        assert (
            validate_success(api_client.get_order_line(line["id"], NAM))[
                "billback_status"
            ]
            == "WRITTEN_OFF"
        )
        assert (
            validate_success(
                api_client.get_manufacturer(world["manufacturer_id"], NAM)
            )["open_claim_exposure_cents"]
            == 0
        )

        # The written-off claim no longer blocks the window, but its lines are
        # gone from the sweep, so the same request fails one rung lower now.
        validate_error(
            api_client.create_bill_back_claim(
                bill_back_claim_payload(
                    deviation["id"],
                    AUG_10,
                    AUG_20,
                    read_deviation_version(deviation["id"]),
                ),
                ACCOUNTANT,
            ),
            "ERR_NO_QUALIFYING_LINES",
            422,
        )


class TestDisputeCreationGuards:
    def test_only_an_invoiced_line_may_be_disputed_and_only_once_at_a_time(self):
        """PRD §3.9: "The line must actually have been invoiced — its
        `pricing_status` must be `INVOICED` or `REPRICED`, otherwise
        `ERR_ORDER_LINE_INVALID_STATE` — and no dispute in `OPEN`, `UNDER_AUDIT`
        or `UPHELD` status may already exist for that line, otherwise
        `ERR_DISPUTE_ALREADY_EXISTS_FOR_LINE`."

        PRD §3.9: "The operator may withdraw its own dispute from `OPEN` or
        `UNDER_AUDIT`, optionally supplying a `reason`; the dispute becomes
        `WITHDRAWN`, its `version` is incremented by 1, and the period it was
        blocking becomes settleable again."

        Design: Corner/Validations/dispute_creation_state_gate_and_duplicate_guard
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
        )
        contract_id = signed["contract_id"]
        open_rebate_period(contract_id, TERM_START, SEP_START)
        line = create_order_line(
            contract_id, chicken["id"], world["dc_id"], world["operator_id"], 10
        )
        assert line["pricing_status"] == "DRAFT_PRICED"

        validate_error(
            api_client.create_pricing_dispute(
                pricing_dispute_payload(line["id"], 4900), world["buyer"]
            ),
            "ERR_ORDER_LINE_INVALID_STATE",
            409,
        )

        invoiced = invoice_order_line(line["id"])
        assert invoiced["pricing_status"] == "INVOICED"

        first = create_dispute(line["id"], world["operator_id"], 4900)
        assert first["status"] == "OPEN"
        assert first["contract_id"] == contract_id
        validate_error(
            api_client.create_pricing_dispute(
                pricing_dispute_payload(line["id"], 4800), world["buyer"]
            ),
            "ERR_DISPUTE_ALREADY_EXISTS_FOR_LINE",
            409,
        )

        withdrawn = validate_success(
            api_client.withdraw_pricing_dispute(
                first["id"], world["buyer"], {"reason": "Reason restated"}
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"

        # A withdrawn dispute is not one of the three blocking statuses.
        second = create_dispute(line["id"], world["operator_id"], 4800)
        assert second["status"] == "OPEN"

        validate_error(
            api_client.withdraw_pricing_dispute(
                first["id"], world["buyer"], {"reason": "Again"}
            ),
            "ERR_DISPUTE_INVALID_STATE",
            409,
        )

        _, page = validate_paginated(
            api_client.list_pricing_disputes(NAM, {"order_line_id": line["id"]})
        )
        assert page["total_count"] == 2


class TestInclusiveTermBoundaries:
    def test_orders_at_both_closed_endpoints_of_the_term_are_accepted(self):
        """PRD §2.5: "A `Contract` term `[effective_from, effective_to]` is
        **closed** at both ends: an order dated exactly at `effective_to` is still
        inside the term."

        PRD §3.3: "When a `SystemAdmin` advances the logical clock past a
        contract's `effective_to` while that contract is `ACTIVE` or `SUSPENDED`,
        the contract moves to `EXPIRED`; its deviation agreements in any of the
        six non-terminal states listed above become `TERMINATED`, and its `ACTIVE`
        coverage rows become `ENDED`, but — unlike a termination — its markup
        tiers are left as they are."

        Design: Corner/Validations/inclusive_term_and_coverage_boundary_instants_are_accepted
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
        )
        contract_id = signed["contract_id"]
        august = open_rebate_period(contract_id, TERM_START, SEP_START)
        final_month = open_rebate_period(contract_id, JUL_2027_START, AUG_2027_START)

        # The clock starts at exactly effective_from, the lower closed endpoint.
        opening = create_order_line(
            contract_id, chicken["id"], world["dc_id"], world["operator_id"], 10
        )
        assert opening["order_date"].startswith("2026-08-01T00:00:00")
        assert opening["invoiced_unit_price_cents"] == 5000
        assert opening["rebate_period_id"] == august["id"]

        # Exactly at effective_to the sweep touches nothing.
        swept = set_clock(TERM_END)
        assert swept["expired_contract_ids"] == []
        assert swept["expired_deviation_ids"] == []
        assert (
            validate_success(api_client.get_contract(contract_id, NAM))["status"]
            == "ACTIVE"
        )

        closing = create_order_line(
            contract_id, chicken["id"], world["dc_id"], world["operator_id"], 10
        )
        assert closing["order_date"].startswith("2027-07-31T23:59:59")
        assert closing["invoiced_unit_price_cents"] == 5000
        # The coverage window is closed at its upper end too, so no fee applies.
        assert closing["service_fee_cents"] == 0
        assert closing["rebate_period_id"] == final_month["id"]
        assert closing["rebate_period_id"] != opening["rebate_period_id"]


class TestCeilingAfterPriceResolution:
    def test_the_ceiling_reads_the_resolved_cost_plus_price_not_the_discount(self):
        """PRD §3.4: "Under `COST_PLUS_PROTECTED` the analyst supplies
        `protected_discount_cents`, greater than zero, and must leave
        `requested_net_price_cents` null; `deviated_price_cents` is then the item's
        current cost on the relevant basis minus that protected discount, where
        the cost basis is the one named by the contract's entry-band tier — the
        single `ACTIVE` tier of this contract covering the product's class at case
        volume zero, that is, the tier whose `min_case_volume` is 0."

        PRD §3.4: "Once resolved, the price is tested against the ceiling: a
        `deviated_price_cents` strictly greater than `max_operator_price_cents` at
        creation is rejected with `ERR_DEVIATED_PRICE_ABOVE_CEILING`."

        Design: Corner/Validations/ceiling_check_runs_after_the_deviated_price_is_resolved
        """
        world = bootstrap_partners()
        # avg_cost_cents 4100, which the entry band's AVG_COST basis reads.
        chicken = create_product(world["manufacturer_id"])
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[
                {
                    "product_class_code": "PROTEIN",
                    "cost_basis": "AVG_COST",
                    "markup_type": "PERCENT_OF_COST",
                    "markup_value": 12.50,
                    "min_case_volume": 0,
                }
            ],
        )
        contract_id = signed["contract_id"]
        observed_version = read_contract_version(contract_id)

        # 4100 - 100 resolves to 4000, one cent group above the 3900 ceiling.
        validate_error(
            api_client.create_deviation_agreement(
                deviation_agreement_payload(
                    contract_id,
                    chicken["id"],
                    world["manufacturer_id"],
                    observed_version,
                    3900,
                    TERM_START,
                    SEP_START,
                    bill_back_basis="COST_PLUS_PROTECTED",
                    protected_discount_cents=100,
                ),
                ANALYST,
            ),
            "ERR_DEVIATED_PRICE_ABOVE_CEILING",
            422,
        )
        # A refused create writes nothing, so the parent version has not moved.
        assert read_contract_version(contract_id) == observed_version

        # 4100 - 200 resolves to exactly the ceiling, and the test is strict.
        accepted = create_deviation(
            contract_id,
            chicken["id"],
            world["manufacturer_id"],
            3900,
            TERM_START,
            SEP_START,
            bill_back_basis="COST_PLUS_PROTECTED",
            protected_discount_cents=200,
        )
        assert accepted["deviated_price_cents"] == 3900
        assert accepted["status"] == "DRAFT"
        assert accepted["price_revision_count"] == 0
        assert read_contract_version(contract_id) == observed_version + 1

        rows, page = validate_paginated(
            api_client.list_deviation_agreements(
                ANALYST, {"contract_id": contract_id}
            )
        )
        assert page["total_count"] == 1
        assert rows[0]["id"] == accepted["id"]


class TestStrandedAmendmentDraft:
    def test_suspending_the_parent_strands_the_draft_without_deadlocking_it(self):
        """PRD §3.3: "Signing an amendment draft is refused with
        `ERR_PARENT_CONTRACT_NOT_AMENDING` unless the parent is in `AMENDING` at
        that moment."

        PRD §3.3: "Suspending a parent in mid-amendment deliberately strands the
        outstanding draft: signing it now fails the parent-amending check, because
        the parent is no longer in `AMENDING`."

        PRD §3.3: "Nothing deadlocks — reinstating returns the parent to `ACTIVE`,
        and the stranded draft can still be terminated."

        Design: Corner/Validations/amendment_signature_requires_the_parent_to_still_be_amending
        """
        world = bootstrap_partners()
        parent = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
        )
        parent_id = parent["contract_id"]

        draft = validate_success(
            api_client.open_contract_amendment(
                parent_id,
                NAM,
                amendment_payload(
                    contract_code="HLG-2026-A1",
                    effective_from=SEP_START,
                    effective_to=TERM_END,
                ),
            ),
            201,
        )
        assert draft["status"] == "DRAFT"
        assert draft["amends_contract_id"] == parent_id
        assert (
            validate_success(api_client.get_contract(parent_id, NAM))["status"]
            == "AMENDING"
        )

        add_tier(draft["id"], **PROTEIN_QUARTER)
        add_coverage(
            draft["id"],
            world["dc_id"],
            coverage_from=SEP_START,
            coverage_to=TERM_END,
        )
        pending = validate_success(
            api_client.submit_contract_for_signature(draft["id"], NAM)
        )
        assert pending["status"] == "PENDING_SIGNATURE"

        suspended = validate_success(
            api_client.suspend_contract(
                parent_id, NAM, {"note": "Credit hold on the account"}
            )
        )
        assert suspended["status"] == "SUSPENDED"

        validate_error(
            api_client.sign_contract(draft["id"], world["buyer"]),
            "ERR_PARENT_CONTRACT_NOT_AMENDING",
            409,
        )
        assert (
            validate_success(api_client.get_contract(draft["id"], NAM))["status"]
            == "PENDING_SIGNATURE"
        )

        reinstated = validate_success(api_client.reinstate_contract(parent_id, NAM))
        assert reinstated["status"] == "ACTIVE"
        # ACTIVE is still not AMENDING, so the draft remains unsignable.
        validate_error(
            api_client.sign_contract(draft["id"], world["buyer"]),
            "ERR_PARENT_CONTRACT_NOT_AMENDING",
            409,
        )

        abandoned = validate_success(
            api_client.terminate_contract(
                draft["id"], NAM, {"reason": "Amendment abandoned"}
            )
        )
        assert abandoned["status"] == "TERMINATED"
        # The parent was ACTIVE rather than AMENDING, so nothing hops back.
        assert (
            validate_success(api_client.get_contract(parent_id, NAM))["status"]
            == "ACTIVE"
        )

        # The terminated draft no longer counts as an outstanding amendment.
        second = validate_success(
            api_client.open_contract_amendment(
                parent_id,
                NAM,
                amendment_payload(
                    contract_code="HLG-2026-A2",
                    effective_from=SEP_START,
                    effective_to=TERM_END,
                ),
            ),
            201,
        )
        assert second["status"] == "DRAFT"
        assert second["amends_contract_id"] == parent_id
        assert (
            validate_success(api_client.get_contract(parent_id, NAM))["status"]
            == "AMENDING"
        )
