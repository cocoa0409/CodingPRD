"""The eleven pinned adjudication edits (PRD §3.4) plus edit-ordering/priority claims."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    NON_EXISTENT_UUID,
    make_plan, make_drug, make_formulary_entry, make_pharmacy, make_member,
    make_adjudication_scenario, activate_plan, make_step_therapy_scenario,
    submit_claim, get_only_rejected_claim,
    make_pharmacist_headers,
)


class TestMemberEligibilityWindow:
    def test_fill_before_eligibility_start_rejected(self, api):
        """PRD §3.4: "First, member eligibility: the member must be `ACTIVE` and the
        `fill_date` must fall within the inclusive window from `eligibility_start_date`
        to `eligibility_end_date`, else `ERR_MEMBER_INELIGIBLE`."

        Design: Corner/validations/member_eligibility_window_bounds
        """
        scenario = make_adjudication_scenario(
            drug_overrides={"ndc": "00000-9028", "name": "Eligex", "unit_cost_cents": 100,
                            "max_daily_dose_units": 10},
        )
        res = submit_claim(
            scenario["member"]["id"], scenario["drug"]["id"],
            scenario["pharmacy"]["id"], fill_date="2025-12-31",
        )
        validate_error(res, "ERR_MEMBER_INELIGIBLE", expected_status=422)
        claim = get_only_rejected_claim(scenario["member"]["id"])
        assert claim["reject_reasons"] == ["ERR_MEMBER_INELIGIBLE"]

    def test_fill_on_eligibility_end_date_pays(self, api):
        """PRD §3.4: "First, member eligibility: the member must be `ACTIVE` and the
        `fill_date` must fall within the inclusive window from `eligibility_start_date`
        to `eligibility_end_date`, else `ERR_MEMBER_INELIGIBLE`."

        Design: Corner/validations/member_eligibility_window_bounds
        """
        scenario = make_adjudication_scenario(
            drug_overrides={"ndc": "00000-9028", "name": "Eligex", "unit_cost_cents": 100,
                            "max_daily_dose_units": 10},
        )
        claim = validate_success(
            submit_claim(
                scenario["member"]["id"], scenario["drug"]["id"],
                scenario["pharmacy"]["id"], fill_date="2026-12-31",
            ),
            201,
        )
        assert claim["status"] == "PAID", "Fill exactly on eligibility_end_date is in-window"


def test_claim_plan_not_active_edit(api):
    """PRD §3.4: "Second, plan status: the member's plan must be `ACTIVE`, else
    `ERR_PLAN_NOT_ACTIVE`."

    Design: Corner/validations/claim_plan_not_active_edit
    """
    plan = make_plan(name="P-DRAFT")
    drug = make_drug(ndc="00000-9042", name="Draftex", unit_cost_cents=100,
                     max_daily_dose_units=10)
    make_formulary_entry(plan["id"], drug["id"], tier=1, quantity_limit_per_fill=30,
                         max_days_supply=30, copay_type="FLAT", copay_flat_cents=100)
    # Deliberately never activated: the plan stays DRAFT.
    pharmacy = make_pharmacy(ncpdp_id="NCPDP-DFT")
    member = make_member(plan["id"], external_ref="M-DFT", full_name="Pat Draft")

    res = submit_claim(member["id"], drug["id"], pharmacy["id"], fill_date="2026-03-01")
    validate_error(res, "ERR_PLAN_NOT_ACTIVE", expected_status=422)
    claim = get_only_rejected_claim(member["id"])
    assert claim["status"] == "REJECTED"
    assert claim["reject_reasons"] == ["ERR_PLAN_NOT_ACTIVE"]


def test_drug_not_on_formulary_edit(api):
    """PRD §3.4: "Third, coverage: an `ACTIVE` formulary entry must exist pairing the
    member's plan with the claim's drug, else `ERR_DRUG_NOT_ON_FORMULARY`."

    Design: Corner/validations/drug_not_on_formulary_edit
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9026", "name": "Covered", "unit_cost_cents": 100,
                        "max_daily_dose_units": 10},
    )
    other_drug = make_drug(ndc="00000-9027", name="Notcovered", unit_cost_cents=100,
                           max_daily_dose_units=10)
    res = submit_claim(
        scenario["member"]["id"], other_drug["id"], scenario["pharmacy"]["id"],
        fill_date="2026-03-01",
    )
    validate_error(res, "ERR_DRUG_NOT_ON_FORMULARY", expected_status=422)
    claim = get_only_rejected_claim(scenario["member"]["id"])
    assert claim["reject_reasons"] == ["ERR_DRUG_NOT_ON_FORMULARY"]


class TestSpecialtyChannel:
    def _specialty_scenario(self):
        scenario = make_adjudication_scenario(
            plan_overrides={"oop_max_cents": 1000000},
            drug_overrides={"ndc": "00000-9025", "name": "Specialtin",
                            "therapeutic_class": "BIOLOGIC", "unit_cost_cents": 50000,
                            "max_daily_dose_units": 100, "is_specialty": True},
            entry_overrides={"tier": 4, "copay_type": "PERCENTAGE", "copay_percentage": 25},
        )
        specialty = make_pharmacy(ncpdp_id="NCPDP-SPS", name="Rx Specialty",
                                  channel="SPECIALTY", auto_suspend_threshold_cents=5000)
        return scenario, specialty

    def test_specialty_drug_rejected_at_retail(self, api):
        """PRD §3.4: "Fourth, channel: if the drug's `is_specialty` flag is true, the
        dispensing pharmacy's `channel` must be `SPECIALTY`, else
        `ERR_SPECIALTY_CHANNEL_REQUIRED`."

        Design: Corner/validations/specialty_channel_enforced
        """
        scenario, _specialty = self._specialty_scenario()
        res = submit_claim(
            scenario["member"]["id"], scenario["drug"]["id"],
            scenario["pharmacy"]["id"], fill_date="2026-03-01",
        )
        validate_error(res, "ERR_SPECIALTY_CHANNEL_REQUIRED", expected_status=422)
        claim = get_only_rejected_claim(scenario["member"]["id"])
        assert claim["reject_reasons"] == ["ERR_SPECIALTY_CHANNEL_REQUIRED"]

    def test_specialty_drug_pays_at_specialty_channel(self, api):
        """PRD §3.4: "Fourth, channel: if the drug's `is_specialty` flag is true, the
        dispensing pharmacy's `channel` must be `SPECIALTY`, else
        `ERR_SPECIALTY_CHANNEL_REQUIRED`."

        Design: Corner/validations/specialty_channel_enforced
        """
        scenario, specialty = self._specialty_scenario()
        claim = validate_success(
            submit_claim(
                scenario["member"]["id"], scenario["drug"]["id"], specialty["id"],
                fill_date="2026-03-01",
            ),
            201,
        )
        assert claim["status"] == "PAID"
        assert claim["allowed_cents"] == 500000
        assert claim["copay_base_cents"] == 125000, "25% of 500000"
        assert claim["plan_paid_cents"] == 375000


class TestQuantityLimitBoundary:
    def _quantity_scenario(self):
        return make_adjudication_scenario(
            drug_overrides={"ndc": "88888-0001", "name": "Quantol",
                            "therapeutic_class": "ANTICOAGULANT", "unit_cost_cents": 1000,
                            "max_daily_dose_units": 3},
            entry_overrides={"quantity_limit_per_fill": 90, "max_days_supply": 90,
                             "copay_flat_cents": 100},
        )

    def test_quantity_equal_to_limit_passes(self, api):
        """PRD §3.4: "Ninth, quantity ceiling: the `quantity` must not exceed the
        entry's `quantity_limit_per_fill`, with a quantity exactly equal to the limit
        passing, else `ERR_QUANTITY_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/quantity_limit_equality_boundary
        """
        scenario = self._quantity_scenario()
        claim = validate_success(
            submit_claim(
                scenario["member"]["id"], scenario["drug"]["id"],
                scenario["pharmacy"]["id"], fill_date="2026-03-01",
                quantity=90, days_supply=30,
            ),
            201,
        )
        assert claim["status"] == "PAID", "quantity == limit (90) passes"
        assert claim["allowed_cents"] == 90000
        assert claim["member_pays_cents"] == 100
        assert claim["plan_paid_cents"] == 89900

    def test_quantity_one_above_limit_rejected(self, api):
        """PRD §3.4: "Ninth, quantity ceiling: the `quantity` must not exceed the
        entry's `quantity_limit_per_fill`, with a quantity exactly equal to the limit
        passing, else `ERR_QUANTITY_LIMIT_EXCEEDED`."
        PRD §3.4: "the claim's `reject_reasons` array records every failed edit's error
        identifier, in that same pinned order."

        Design: Difficulty/boundary_precision_check/quantity_limit_equality_boundary
        """
        scenario = self._quantity_scenario()
        member_id = scenario["member"]["id"]
        validate_success(
            submit_claim(member_id, scenario["drug"]["id"], scenario["pharmacy"]["id"],
                         fill_date="2026-03-01", quantity=90, days_supply=30),
            201,
        )
        res = submit_claim(member_id, scenario["drug"]["id"], scenario["pharmacy"]["id"],
                           fill_date="2026-05-01", quantity=91, days_supply=30)
        validate_error(res, "ERR_QUANTITY_LIMIT_EXCEEDED", expected_status=422)
        claim = get_only_rejected_claim(member_id)
        assert claim["status"] == "REJECTED"
        assert claim["reject_reasons"] == ["ERR_QUANTITY_LIMIT_EXCEEDED"]
        assert claim["plan_paid_cents"] == 0


def test_claim_rejection_persists_ordered_reasons(api):
    """PRD §3.4: "When any edit fails, the claim is still persisted — now with `status`
    `REJECTED` — and the response is HTTP 422 whose `error_id` is the first failed edit
    in the pinned order; the claim's `reject_reasons` array records every failed edit's
    error identifier, in that same pinned order."
    PRD §3.4: "A rejected claim's financial fields — `allowed_cents`, `copay_base_cents`,
    `deductible_applied_cents`, `card_applied_cents`, `member_pays_cents`, and
    `plan_paid_cents` — are all 0, and its `rebate_tag` is `REBATE_INELIGIBLE`."

    Design: Corner/state_machines/claim_rejection_persists_ordered_reasons
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9011", "name": "Orderex", "unit_cost_cents": 100,
                        "max_daily_dose_units": 1000},
        entry_overrides={"quantity_limit_per_fill": 90, "max_days_supply": 90,
                         "copay_flat_cents": 100},
    )
    member_id = scenario["member"]["id"]
    # Fails edit 9 (qty 91 > 90) AND edit 10 (days 99 > 90).
    res = submit_claim(member_id, scenario["drug"]["id"], scenario["pharmacy"]["id"],
                       fill_date="2026-03-01", quantity=91, days_supply=99)
    validate_error(res, "ERR_QUANTITY_LIMIT_EXCEEDED", expected_status=422)
    claim = get_only_rejected_claim(member_id)
    assert claim["status"] == "REJECTED"
    assert claim["reject_reasons"] == [
        "ERR_QUANTITY_LIMIT_EXCEEDED", "ERR_DAYS_SUPPLY_EXCEEDED",
    ], "reject_reasons must carry every failed edit in the pinned edit order"
    assert claim["allowed_cents"] == 0
    assert claim["plan_paid_cents"] == 0
    assert claim["rebate_tag"] == "REBATE_INELIGIBLE"


class TestExistenceBeatsRequestShape:
    def _priority_scenario(self):
        return make_adjudication_scenario(
            drug_overrides={"ndc": "77777-0001", "name": "Existin",
                            "therapeutic_class": "ANTIFUNGAL", "unit_cost_cents": 1000,
                            "max_daily_dose_units": 100},
            entry_overrides={"copay_flat_cents": 0},
        )

    def test_unknown_drug_beats_malformed_quantity(self, api):
        """PRD §2.6: "Every request is screened against a fixed pipeline, and a request
        failing at any stage is rejected with that stage's error — later stages are
        never consulted for that request."
        PRD §2.7: "an unknown drug (whether referenced as `drug_id`, `step_drug_id`, or
        `card_drug_id`) yields `ERR_DRUG_NOT_FOUND`" (stage 4 existence precedes stage 7
        request shape).

        Design: Difficulty/priority_pair_validation_conflict/unknown_drug_vs_malformed_quantity_conflict
        """
        scenario = self._priority_scenario()
        res = submit_claim(
            scenario["member"]["id"], NON_EXISTENT_UUID, scenario["pharmacy"]["id"],
            fill_date="2026-06-01", quantity=0, days_supply=10,
        )
        validate_error(res, "ERR_DRUG_NOT_FOUND", expected_status=404)

    def test_unknown_drug_beats_missing_quantity(self, api):
        """PRD §2.6: "Every request is screened against a fixed pipeline, and a request
        failing at any stage is rejected with that stage's error — later stages are
        never consulted for that request."
        PRD §2.7: "an unknown drug (whether referenced as `drug_id`, `step_drug_id`, or
        `card_drug_id`) yields `ERR_DRUG_NOT_FOUND`" (stage 4 existence precedes stage 7
        request shape).

        Design: Difficulty/priority_pair_validation_conflict/unknown_drug_vs_malformed_quantity_conflict
        """
        scenario = self._priority_scenario()
        payload = {
            "member_id": scenario["member"]["id"],
            "drug_id": NON_EXISTENT_UUID,
            "prescription_number": "RX-K9B",
            "fill_date": "2026-06-01",
            "days_supply": 10,
        }
        res = api.create_claim(
            payload, make_pharmacist_headers(scenario["pharmacy"]["id"])
        )
        validate_error(res, "ERR_DRUG_NOT_FOUND", expected_status=404)


class TestStepTherapyLookback:
    def test_step_fill_exactly_lookback_days_before_satisfies(self, api):
        """PRD §3.4: "Eighth, step therapy: if the entry's `step_therapy_required` is
        true, there must exist a `PAID` claim of the same member for the entry's
        `step_drug_id` whose fill date lies within the inclusive lookback window ending
        on the new claim's `fill_date` and beginning `step_therapy_lookback_days`
        earlier — else `ERR_STEP_THERAPY_NOT_MET`; a step-drug fill exactly
        `step_therapy_lookback_days` before the new fill date satisfies the edit, and
        `REVERSED` or `REJECTED` claims never satisfy it."

        Design: Corner/calculations/step_therapy_lookback_inclusive_boundary
        """
        scenario = make_step_therapy_scenario(lookback_days=180)
        # Step-drug history: PAID fill on 2026-01-01.
        validate_success(
            submit_claim(scenario["member"]["id"], scenario["step_drug"]["id"],
                         scenario["pharmacy"]["id"], fill_date="2026-01-01",
                         quantity=30, days_supply=30),
            201,
        )
        # 2026-01-01 is exactly 180 days before 2026-06-30.
        claim = validate_success(
            submit_claim(scenario["member"]["id"], scenario["drug"]["id"],
                         scenario["pharmacy"]["id"], fill_date="2026-06-30",
                         quantity=30, days_supply=30),
            201,
        )
        assert claim["status"] == "PAID", "Inclusive lower lookback bound satisfies the edit"

    def test_step_fill_one_day_beyond_lookback_fails(self, api):
        """PRD §3.4: "Eighth, step therapy: if the entry's `step_therapy_required` is
        true, there must exist a `PAID` claim of the same member for the entry's
        `step_drug_id` whose fill date lies within the inclusive lookback window ending
        on the new claim's `fill_date` and beginning `step_therapy_lookback_days`
        earlier — else `ERR_STEP_THERAPY_NOT_MET`; a step-drug fill exactly
        `step_therapy_lookback_days` before the new fill date satisfies the edit, and
        `REVERSED` or `REJECTED` claims never satisfy it."

        Design: Corner/calculations/step_therapy_lookback_inclusive_boundary
        """
        scenario = make_step_therapy_scenario(lookback_days=180)
        member_id = scenario["member"]["id"]
        validate_success(
            submit_claim(member_id, scenario["step_drug"]["id"],
                         scenario["pharmacy"]["id"], fill_date="2026-01-01",
                         quantity=30, days_supply=30),
            201,
        )
        # 2026-07-01 is 181 days after 2026-01-01 — outside the 180-day lookback.
        res = submit_claim(member_id, scenario["drug"]["id"], scenario["pharmacy"]["id"],
                           fill_date="2026-07-01", quantity=30, days_supply=30)
        validate_error(res, "ERR_STEP_THERAPY_NOT_MET", expected_status=422)
        claim = get_only_rejected_claim(member_id)
        assert claim["reject_reasons"] == ["ERR_STEP_THERAPY_NOT_MET"]
