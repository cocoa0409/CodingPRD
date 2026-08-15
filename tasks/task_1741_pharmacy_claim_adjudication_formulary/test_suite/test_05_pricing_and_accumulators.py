"""Pricing pipeline, copay-assistance variants, accumulator posting and compensation."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_claim, assert_member_accumulator_invariants,
    make_plan, make_drug, make_formulary_entry, make_adjudication_scenario,
    make_dual_assistance_scenario, make_member,
    submit_claim, create_paid_claim, get_claim, get_member,
)


def test_claim_computed_amounts_on_creation(api, pbm_admin_headers):
    """PRD §3.5: "The claim's `allowed_cents` is the drug's `unit_cost_cents` multiplied
    by the `quantity`, plus the plan's `dispensing_fee_cents`."
    PRD §3.4: "Claims carry a `resubmit_count`, initially 0, an `audit_status` that
    begins `UNAUDITED`, and a `pa_id` that is null unless an authorization was consumed."

    Design: Corner/entities/claim_computed_amounts_on_creation
    """
    scenario = make_adjudication_scenario(
        plan_overrides={"dispensing_fee_cents": 200},
        drug_overrides={"ndc": "00000-9003", "name": "Computin", "unit_cost_cents": 10000,
                        "max_daily_dose_units": 10},
        entry_overrides={"copay_flat_cents": 200, "rebate_eligible": False},
    )
    claim = validate_success(
        submit_claim(
            scenario["member"]["id"], scenario["drug"]["id"],
            scenario["pharmacy"]["id"], fill_date="2026-03-01", quantity=3, days_supply=3,
        ),
        201,
    )
    assert_claim(claim)
    assert claim["allowed_cents"] == 30200, "10000 x 3 + 200 fee"
    assert claim["copay_base_cents"] == 200
    assert claim["deductible_applied_cents"] == 0
    assert claim["card_applied_cents"] == 0
    assert claim["member_pays_cents"] == 200
    assert claim["plan_paid_cents"] == 30000
    assert claim["status"] == "PAID"
    assert claim["reject_reasons"] == []
    assert claim["resubmit_count"] == 0
    assert claim["audit_status"] == "UNAUDITED"
    assert claim["rebate_tag"] == "REBATE_INELIGIBLE"
    assert claim["pa_id"] is None
    assert claim["version"] == 1


def test_percentage_coinsurance_rounding(api):
    """PRD §3.5: "or — under `PERCENTAGE` — the `allowed_cents` multiplied by
    `copay_percentage` and divided by 100, rounded half-up to whole cents at this single
    rounding point."
    PRD §2.5: "Rounding is permitted at exactly two places, and both use round-half-up
    to whole cents."

    Design: Corner/calculations/percentage_coinsurance_rounding
    """
    scenario = make_adjudication_scenario(
        plan_overrides={"dispensing_fee_cents": 1, "oop_max_cents": 1000000},
        drug_overrides={"ndc": "00000-9021", "name": "Percentil", "unit_cost_cents": 101,
                        "max_daily_dose_units": 1000},
        entry_overrides={"tier": 2, "quantity_limit_per_fill": 200,
                         "copay_type": "PERCENTAGE", "copay_percentage": 20},
    )
    claim = validate_success(
        submit_claim(
            scenario["member"]["id"], scenario["drug"]["id"],
            scenario["pharmacy"]["id"], fill_date="2026-03-01",
            quantity=100, days_supply=30,
        ),
        201,
    )
    assert claim["allowed_cents"] == 10101, "101 x 100 + 1 fee"
    assert claim["copay_base_cents"] == 2021, "round-half-up of 2020.2 at the single rounding point"
    assert claim["member_pays_cents"] == 2021
    assert claim["plan_paid_cents"] == 8080


class TestDeductibleCrossing:
    def _crossing_scenario(self):
        return make_adjudication_scenario(
            plan_overrides={"deductible_cents": 15000, "oop_max_cents": 1000000,
                            "dispensing_fee_cents": 0},
            drug_overrides={"ndc": "33333-0001", "name": "Pressoril",
                            "therapeutic_class": "ANTIHYPERTENSIVE",
                            "unit_cost_cents": 10000, "max_daily_dose_units": 100},
            entry_overrides={"tier": 2, "copay_flat_cents": 3000},
        )

    def test_claim_crossing_remaining_deductible_financials(self, api):
        """PRD §3.5: "The member's remaining deductible is the plan's `deductible_cents`
        minus the member's `deductible_paid_cents`, floored at zero, and
        `deductible_applied_cents` is the smaller of `allowed_cents` and that remaining
        deductible; the post-deductible remainder is `allowed_cents` minus
        `deductible_applied_cents`."
        PRD §3.5: "The copay actually owed is the smaller of `copay_base_cents` and the
        post-deductible remainder."

        Design: Difficulty/combinatorial_formula/pricing_nested_min_max_deductible_crossing
        """
        scenario = self._crossing_scenario()
        member_id, drug_id, pharmacy_id = (
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
        )
        first = create_paid_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-01",
                                  quantity=1, days_supply=1)
        assert first["allowed_cents"] == 10000
        assert first["deductible_applied_cents"] == 10000, "all of claim 1 absorbed by deductible"
        assert first["copay_base_cents"] == 3000
        assert first["member_pays_cents"] == 10000
        assert first["plan_paid_cents"] == 0

        second = validate_success(
            submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-04-01",
                         quantity=30, days_supply=30),
            201,
        )
        assert second["allowed_cents"] == 300000
        assert second["deductible_applied_cents"] == 5000, "only 5000 of deductible remains"
        assert second["copay_base_cents"] == 3000
        assert second["member_pays_cents"] == 8000, "5000 deductible + 3000 copay"
        assert second["plan_paid_cents"] == 292000

    def test_claim_crossing_deductible_member_accumulators(self, api, pbm_admin_headers):
        """PRD §3.5: "The deductible credit is the smaller of `member_pays_cents` and
        `deductible_applied_cents`, and it is added to the member's
        `deductible_paid_cents`; the full `member_pays_cents` is added to
        `oop_paid_cents`; and `oop_max_reached` is then recomputed as true exactly when
        `oop_paid_cents` is greater than or equal to the plan's `oop_max_cents` — the
        equality boundary counts as reached."

        Design: Difficulty/combinatorial_formula/pricing_nested_min_max_deductible_crossing
        """
        scenario = self._crossing_scenario()
        member_id, drug_id, pharmacy_id = (
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
        )
        create_paid_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-01",
                          quantity=1, days_supply=1)
        validate_success(
            submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-04-01",
                         quantity=30, days_supply=30),
            201,
        )
        member = get_member(member_id, pbm_admin_headers)
        assert member["deductible_paid_cents"] == 15000, "deductible exactly met"
        assert member["oop_paid_cents"] == 18000
        assert member["oop_max_reached"] is False
        assert_member_accumulator_invariants(member, scenario["plan"])


class TestDualVariantCopayAssistance:
    def test_accumulator_model_card_split(self, api, pbm_admin_headers):
        """PRD §3.5: "Under the `ACCUMULATOR` model, the card may cover patient
        responsibility only down to the plan's `member_min_pay_cents` floor:
        `card_applied_cents` is the smaller of the card balance and the amount by which
        patient responsibility exceeds `member_min_pay_cents` (floored at zero), so the
        member always pays at least that floor per fill unless the card balance runs
        short."
        PRD §3.5: "The same inputs therefore produce different `member_pays_cents` and
        different accumulator growth under the two models."

        Design: Difficulty/dual_variant_calc/copay_card_accumulator_vs_maximizer
        """
        s = make_dual_assistance_scenario()
        claim = validate_success(
            submit_claim(s["m_acc"]["id"], s["drug"]["id"], s["pharmacy"]["id"],
                         fill_date="2026-03-01", quantity=10, days_supply=10),
            201,
        )
        assert claim["status"] == "PAID"
        assert claim["allowed_cents"] == 100200, "10000 x 10 + 200 fee"
        assert claim["card_applied_cents"] == 2500, "min(5000 balance, 3000 resp - 500 floor)"
        assert claim["member_pays_cents"] == 500, "member always pays the 500 floor"
        assert claim["plan_paid_cents"] == 97200
        member = get_member(s["m_acc"]["id"], pbm_admin_headers)
        assert member["oop_paid_cents"] == 500, "only member money accumulates"
        assert member["card_balance_cents"] == 2500, "card debited by card_applied_cents"

    def test_maximizer_model_card_split(self, api, pbm_admin_headers):
        """PRD §3.5: "Under the `MAXIMIZER` model there is no member floor: the card
        pays the smallest of the card balance, the full patient responsibility, and the
        plan's `card_fill_cap_cents` — with a cap of 0 meaning uncapped, so the cap term
        drops out and the card covers up to the balance or the full responsibility."
        PRD §3.5: "The same inputs therefore produce different `member_pays_cents` and
        different accumulator growth under the two models."

        Design: Difficulty/dual_variant_calc/copay_card_accumulator_vs_maximizer
        """
        s = make_dual_assistance_scenario()
        claim = validate_success(
            submit_claim(s["m_max"]["id"], s["drug"]["id"], s["pharmacy"]["id"],
                         fill_date="2026-03-01", quantity=10, days_supply=10),
            201,
        )
        assert claim["status"] == "PAID"
        assert claim["allowed_cents"] == 100200
        assert claim["card_applied_cents"] == 800, "min(5000 balance, 3000 resp, 800 cap)"
        assert claim["member_pays_cents"] == 2200, "no member floor under MAXIMIZER"
        assert claim["plan_paid_cents"] == 97200
        member = get_member(s["m_max"]["id"], pbm_admin_headers)
        assert member["oop_paid_cents"] == 2200
        assert member["card_balance_cents"] == 4200


def test_derived_oop_max_reached_flag_and_cap(api, pbm_admin_headers):
    """PRD §3.5: "and `oop_max_reached` is then recomputed as true exactly when
    `oop_paid_cents` is greater than or equal to the plan's `oop_max_cents` — the
    equality boundary counts as reached."
    PRD §3.5: "the member's remaining out-of-pocket room is the plan's `oop_max_cents`
    minus `oop_paid_cents`, floored at zero; and final patient responsibility is the
    smaller of the pre-cap responsibility and that remaining room."

    Design: Corner/cross_cutting_layers/derived_oop_max_reached_flag_and_cap
    """
    scenario = make_adjudication_scenario(
        plan_overrides={"oop_max_cents": 5000},
        drug_overrides={"ndc": "00000-9040", "name": "Oopmax", "unit_cost_cents": 10000,
                        "max_daily_dose_units": 100},
        entry_overrides={"tier": 2, "copay_flat_cents": 5000},
    )
    member_id, drug_id, pharmacy_id = (
        scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
    )
    first = create_paid_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-01")
    assert first["member_pays_cents"] == 5000
    assert first["plan_paid_cents"] == 95000
    member = get_member(member_id, pbm_admin_headers)
    assert member["oop_paid_cents"] == 5000
    assert member["oop_max_reached"] is True, "oop_paid == oop_max counts as reached (>=)"

    second = validate_success(
        submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-05-01"),
        201,
    )
    assert second["member_pays_cents"] == 0, "OOP room exhausted caps responsibility at 0"
    assert second["plan_paid_cents"] == 100000


def test_rebate_tag_ineligible_for_non_eligible_entry(api):
    """PRD §3.5: "When a claim enters `PAID`, its `rebate_tag` is set to
    `REBATE_ELIGIBLE` if the governing formulary entry's `rebate_eligible` flag is true,
    and `REBATE_INELIGIBLE` otherwise."

    Design: Corner/calculations/rebate_tag_ineligible_for_non_eligible_entry
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9014", "name": "Norebate", "unit_cost_cents": 500},
        entry_overrides={"rebate_eligible": False},
    )
    claim = create_paid_claim(
        scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
    )
    assert claim["status"] == "PAID"
    assert claim["rebate_tag"] == "REBATE_INELIGIBLE"


class TestAccumulatorRestorationOnReversal:
    def _invariant_scenario(self):
        return make_adjudication_scenario(
            plan_overrides={"assistance_model": "ACCUMULATOR", "member_min_pay_cents": 500,
                            "dispensing_fee_cents": 200, "oop_max_cents": 1000000},
            drug_overrides={"ndc": "11111-0002", "name": "Brandstatin-B",
                            "therapeutic_class": "STATIN", "unit_cost_cents": 10000,
                            "max_daily_dose_units": 3},
            entry_overrides={"tier": 2, "copay_flat_cents": 3000, "rebate_eligible": True},
            member_overrides={"full_name": "Pat Inv"},
        )

    def _scenario_with_card(self):
        scenario = self._invariant_scenario()
        # Enroll the card-carrying member directly so card_drug_id matches the drug.
        member = make_member(
            scenario["plan"]["id"], external_ref="M-INV", full_name="Pat Inv",
            card_drug_id=scenario["drug"]["id"], card_balance_cents=5000,
        )
        scenario["member"] = member
        return scenario

    def test_payment_posts_accumulators_and_debits_card(self, api, pbm_admin_headers):
        """PRD §3.5: "The deductible credit is the smaller of `member_pays_cents` and
        `deductible_applied_cents`, and it is added to the member's
        `deductible_paid_cents`; the full `member_pays_cents` is added to
        `oop_paid_cents`"
        PRD §3.5: "When `card_applied_cents` is positive, the card is debited by
        subtracting it from `card_balance_cents`."

        Design: Difficulty/compensating_invariant/member_accumulators_restored_on_reversal
        """
        scenario = self._scenario_with_card()
        claim = create_paid_claim(
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
            fill_date="2026-03-01", quantity=10, days_supply=10,
        )
        assert claim["card_applied_cents"] == 2500, "min(5000, 3000 - 500)"
        assert claim["member_pays_cents"] == 500
        assert claim["rebate_tag"] == "REBATE_ELIGIBLE"
        member = get_member(scenario["member"]["id"], pbm_admin_headers)
        assert member["oop_paid_cents"] == 500
        assert member["deductible_paid_cents"] == 0
        assert member["card_balance_cents"] == 2500

    def test_reversal_restores_accumulators_and_card_exactly(self, api, pbm_admin_headers):
        """PRD §3.7: "Reversal is exact compensation against the claim's stored
        financial fields, so accumulators and ledgers return to their pre-claim values:
        the smaller of `member_pays_cents` and `deductible_applied_cents` is subtracted
        from `deductible_paid_cents`; the full `member_pays_cents` is subtracted from
        `oop_paid_cents`; `oop_max_reached` is recomputed on the same
        greater-than-or-equal boundary; any `card_applied_cents` is credited back to
        `card_balance_cents`"
        PRD §3.5: "When a previously eligible claim is reversed or clawed back by audit,
        its tag moves from `REBATE_ELIGIBLE` to `REBATE_VOID`; a tag of
        `REBATE_INELIGIBLE` is unchanged by those events."

        Design: Difficulty/compensating_invariant/member_accumulators_restored_on_reversal
        """
        scenario = self._scenario_with_card()
        claim = create_paid_claim(
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
            fill_date="2026-03-01", quantity=10, days_supply=10,
        )
        reversed_claim = validate_success(
            api.reverse_claim(
                claim["id"], {"reversal_reason": "patient returned medication"},
                scenario["pharmacist_headers"],
            ),
            200,
        )
        assert reversed_claim["status"] == "REVERSED"
        assert reversed_claim["rebate_tag"] == "REBATE_VOID"
        member = get_member(scenario["member"]["id"], pbm_admin_headers)
        assert member["oop_paid_cents"] == 0, "exact pre-claim value"
        assert member["deductible_paid_cents"] == 0, "exact pre-claim value"
        assert member["card_balance_cents"] == 5000, "card ledger reconciles exactly"
