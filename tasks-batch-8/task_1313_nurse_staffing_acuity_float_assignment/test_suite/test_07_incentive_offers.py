"""Premium incentive offers: posture gate, budget gate, claim/settle/withdraw
lifecycle, the auto-offer cascade, and the budget conservation invariant."""
import pytest

from test_helpers import (
    ADMIN,
    api_client,
    ApiErrorId,
    assert_unit_budget_invariants,
    cancel_assignment,
    complete_assignment,
    confirm_assignment,
    create_nurse,
    create_offer,
    get_shift,
    get_unit,
    setup_claimed_offer,
    setup_staffed_shift,
    setup_unit_with_shift,
    staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOfferCreationGates:

    def test_offer_on_adequate_shift_rejected(self):
        """PRD section 3.6: "Offers are only lawful while the shift is short:
        creating one while the shift's posture is `ADEQUATE` is rejected with
        `ERR_SHIFT_ADEQUATELY_STAFFED` — only `UNDERSTAFFED` or `CRITICAL`
        postures qualify."

        Design: Corner/entities/offer_on_adequate_shift_rejected
        """
        sc = setup_staffed_shift(num_accepted=2, charge_first=True,
                                 name="ICU W", census=(4, 0, 0, 0))
        assert get_shift(sc["shift"]["id"])["staffing_posture"] == "ADEQUATE"
        resp = api_client.create_incentive_offer(
            {"shift_id": sc["shift"]["id"], "premium_multiplier": 1.25},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHIFT_ADEQUATELY_STAFFED)

    def test_offer_create_over_budget_rejected(self):
        """PRD section 2.10: "the reserve the new offer would take, added to
        the current `incentive_reserved_cents`, must not exceed
        `incentive_budget_cents`, or creation fails with
        `ERR_INCENTIVE_BUDGET_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/offer_create_over_budget_rejected
        """
        sc = setup_unit_with_shift(name="ICU V4", census=(4, 0, 0, 0),
                                   budget=30000)
        # Posture is CRITICAL (0 of 2), so offers are allowed; the reserve for
        # mult 1.5 is 0 + round(12 * 6000 * 0.5) = 36000 > 30000 budget.
        resp = api_client.create_incentive_offer(
            {"shift_id": sc["shift"]["id"], "premium_multiplier": 1.5},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INCENTIVE_BUDGET_EXCEEDED)

    def test_offer_duplicate_active_rejected(self):
        """PRD section 3.6: "At most one offer per shift may be open at a time;
        a second creation while an `OFFERED` offer exists fails with
        `ERR_OFFER_ALREADY_ACTIVE`."

        Design: Corner/validations/offer_duplicate_active_rejected
        """
        sc = setup_unit_with_shift(name="ICU V5", census=(4, 0, 0, 0))
        create_offer(sc["shift"]["id"], premium_multiplier=1.25)
        resp = api_client.create_incentive_offer(
            {"shift_id": sc["shift"]["id"], "premium_multiplier": 1.5},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_OFFER_ALREADY_ACTIVE)


class TestSafetyBeatsFiscal:
    """Difficulty instance: safety_beats_fiscal_on_offer_create."""

    def _setup_adequate_low_budget(self):
        """ADEQUATE shift (2 accepted, one charge) on a unit whose 30000-cent
        budget cannot fit the 36000-cent reserve of a 1.5x offer."""
        return setup_staffed_shift(num_accepted=2, charge_first=True,
                                   name="ICU H", census=(4, 0, 0, 0),
                                   budget=30000)

    def test_adequate_and_over_budget_reports_safety_error(self):
        """PRD section 2.5: "The pipeline below is evaluated in this exact
        order, and an earlier failure masks all later ones" — business safety
        rules (item 7) run ahead of fiscal gates (item 10): "The incentive
        budget check on offer creation (`ERR_INCENTIVE_BUDGET_EXCEEDED`) runs
        last, after every other rule has passed."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_offer_create
        """
        sc = self._setup_adequate_low_budget()
        resp = api_client.create_incentive_offer(
            {"shift_id": sc["shift"]["id"], "premium_multiplier": 1.5},
            ADMIN)
        # Both rules are violated; the safety error must surface.
        validate_error(resp, ApiErrorId.ERR_SHIFT_ADEQUATELY_STAFFED)
        assert resp.status_code == 409

    def test_adequate_rejects_even_affordable_offer(self):
        """PRD section 3.6: "Offers are only lawful while the shift is short:
        creating one while the shift's posture is `ADEQUATE` is rejected with
        `ERR_SHIFT_ADEQUATELY_STAFFED` — only `UNDERSTAFFED` or `CRITICAL`
        postures qualify."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_offer_create
        """
        sc = self._setup_adequate_low_budget()
        # reserve of a 1.01x offer is round(12*6000*0.01) = 720 <= 30000, so
        # only the adequately-staffed gate can fire.
        resp = api_client.create_incentive_offer(
            {"shift_id": sc["shift"]["id"], "premium_multiplier": 1.01},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHIFT_ADEQUATELY_STAFFED)


class TestOfferClaim:

    def test_offer_claim_creates_accepted_incentive_assignment(self):
        """PRD section 3.6: "Claiming creates an assignment that enters
        directly in `ACCEPTED` status with `source` `INCENTIVE`, its
        `premium_multiplier` and `flat_bonus_cents` copied from the offer; the
        offer moves to `CLAIMED` with `claimed_nurse_id` and
        `claimed_assignment_id` recorded".

        Design: Corner/state_machines/offer_claim_creates_accepted_incentive_assignment
        """
        sc = setup_unit_with_shift(name="ICU B3", census=(2, 3, 2, 1))
        offer = create_offer(sc["shift"]["id"], premium_multiplier=1.5,
                             flat_bonus_cents=2000)
        nurse = create_nurse(full_name="Claim Clara", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=5000,
                             home_unit_id=sc["unit"]["id"])
        data = validate_success(
            api_client.claim_incentive_offer(offer["id"],
                                             staff_headers(nurse)),
            expected_status=200)
        assert data["status"] == "CLAIMED"
        assert data["claimed_nurse_id"] == nurse["id"]

        asg = validate_success(
            api_client.get_assignment(data["claimed_assignment_id"], ADMIN),
            expected_status=200)
        assert asg["status"] == "ACCEPTED"
        assert asg["source"] == "INCENTIVE"
        assert asg["premium_multiplier"] == 1.5
        assert asg["flat_bonus_cents"] == 2000


class TestOfferSettlement:

    def test_complete_incentive_assignment_settles_offer(self):
        """PRD section 3.6: "completion of the claimed assignment settles the
        offer to `SETTLED`, moving the reserve from reserved to spent on the
        unit's ledger".
        PRD section 3.8: "The recorded `final_cost_cents` is the sum of the two
        rounded components, plus 5,000 cents for each entry in `missed_breaks`,
        plus any `flat_bonus_cents`."

        Design: Corner/state_machines/complete_incentive_assignment_settles_offer
        """
        sc = setup_claimed_offer(name="ICU B4", rate=5000,
                                 premium_multiplier=1.5, flat_bonus_cents=2000)
        asg = confirm_assignment(sc["assignment"]["id"], sc["charge_headers"])
        done = complete_assignment(asg["id"], 12.0, 0, sc["charge_headers"])
        # round(12 * 5000 * 1.5) = 90000 + 0 penalty + 2000 flat bonus
        assert done["final_cost_cents"] == 92000, \
            f"expected 92000, got {done['final_cost_cents']}"

        offer = validate_success(
            api_client.get_incentive_offer(sc["offer"]["id"], ADMIN),
            expected_status=200)
        assert offer["status"] == "SETTLED"

        unit = get_unit(sc["unit"]["id"])
        # reserve was 2000 + round(12*6000*0.5) = 38000
        assert unit["incentive_reserved_cents"] == 0
        assert unit["incentive_spent_cents"] == 38000
        assert_unit_budget_invariants(unit)

    def test_cancel_incentive_assignment_withdraws_offer(self):
        """PRD section 3.4: "an incentive-funded assignment (source
        `INCENTIVE`) whose offer is `CLAIMED` withdraws that offer with its
        reserve released."
        PRD section 2.10: "Withdrawal and expiry subtract the reserve from
        `incentive_reserved_cents`".

        Design: Corner/state_machines/cancel_incentive_assignment_withdraws_offer
        """
        sc = setup_claimed_offer(name="ICU B5", rate=5000,
                                 premium_multiplier=1.5, flat_bonus_cents=2000)
        cancel_assignment(sc["assignment"]["id"], sc["charge_headers"])

        offer = validate_success(
            api_client.get_incentive_offer(sc["offer"]["id"], ADMIN),
            expected_status=200)
        assert offer["status"] == "WITHDRAWN"

        unit = get_unit(sc["unit"]["id"])
        assert unit["incentive_reserved_cents"] == 0
        assert unit["incentive_spent_cents"] == 0


class TestAutoOfferCascade:
    """Difficulty instance: cancel_triggers_auto_incentive_offer."""

    def _setup_adequate_auto_unit(self):
        return setup_staffed_shift(num_accepted=2, charge_first=True,
                                   name="ICU F", census=(4, 0, 0, 0),
                                   auto_mult=1.5)

    def test_cancel_flips_posture_and_fires_auto_offer(self):
        """PRD section 3.6: "When a unit has `auto_incentive_multiplier` set
        and a confirmed-staff cancellation flips a shift's posture from
        `ADEQUATE` to `UNDERSTAFFED` or `CRITICAL`, an offer with `origin`
        `AUTO` is created using that multiplier and a zero flat bonus — but
        only if no `OFFERED` offer already exists for the shift and only if
        the reserve fits within the unit's remaining budget".

        Design: Difficulty/transitive_cascade/cancel_triggers_auto_incentive_offer
        """
        sc = self._setup_adequate_auto_unit()
        assert get_shift(sc["shift"]["id"])["staffing_posture"] == "ADEQUATE"

        cancel_assignment(sc["assignments"][1]["id"], sc["charge_headers"])

        shift = get_shift(sc["shift"]["id"])
        assert shift["staffing_posture"] == "UNDERSTAFFED", \
            f"counted 2 -> 1 of required 2 must be UNDERSTAFFED, got {shift['staffing_posture']}"
        assert shift["status"] == "OPEN"
        assert shift["counted_assignments"] == 1

        data, _meta = validate_paginated(api_client.list_incentive_offers(
            ADMIN, params={"shift_id": sc["shift"]["id"]}))
        assert len(data) == 1, f"exactly one auto offer, got {len(data)}"
        offer = data[0]
        assert offer["status"] == "OFFERED"
        assert offer["origin"] == "AUTO"
        assert offer["premium_multiplier"] == 1.5

    def test_auto_offer_reserves_against_unit_budget(self):
        """PRD section 3.6: "Every offer takes a budget reserve at creation,
        computed as the `flat_bonus_cents` plus the premium portion of a
        twelve-hour shift at a reference rate of 6,000 cents per hour — that
        is, twelve times 6,000 multiplied by the amount by which the
        `premium_multiplier` exceeds 1.0, rounded half-up to whole cents. This
        `premium_reserve_cents` is added to the unit's
        `incentive_reserved_cents` at creation".

        Design: Difficulty/transitive_cascade/cancel_triggers_auto_incentive_offer
        """
        sc = self._setup_adequate_auto_unit()
        cancel_assignment(sc["assignments"][1]["id"], sc["charge_headers"])

        data, _meta = validate_paginated(api_client.list_incentive_offers(
            ADMIN, params={"shift_id": sc["shift"]["id"]}))
        assert len(data) == 1
        offer = data[0]
        # 0 flat + round_half_up(12 * 6000 * (1.5 - 1.0)) = 36000
        assert offer["premium_reserve_cents"] == 36000, \
            f"expected reserve 36000, got {offer['premium_reserve_cents']}"
        assert offer["flat_bonus_cents"] == 0

        unit = get_unit(sc["unit"]["id"])
        assert unit["incentive_reserved_cents"] == 36000
        assert_unit_budget_invariants(unit)


class TestReserveReleaseInvariant:
    """Difficulty instance: incentive_budget_reserve_release_invariant."""

    def _setup_critical_shift(self):
        return setup_unit_with_shift(name="ICU O", census=(2, 3, 2, 1))

    def test_offer_create_reserves_exact_amount(self):
        """PRD section 3.6: "Every offer takes a budget reserve at creation,
        computed as the `flat_bonus_cents` plus the premium portion of a
        twelve-hour shift at a reference rate of 6,000 cents per hour — that
        is, twelve times 6,000 multiplied by the amount by which the
        `premium_multiplier` exceeds 1.0, rounded half-up to whole cents. This
        `premium_reserve_cents` is added to the unit's
        `incentive_reserved_cents` at creation".

        Design: Difficulty/compensating_invariant/incentive_budget_reserve_release_invariant
        """
        sc = self._setup_critical_shift()
        offer = create_offer(sc["shift"]["id"], premium_multiplier=1.5,
                             flat_bonus_cents=5000)
        # 5000 + round_half_up(12 * 6000 * 0.5) = 5000 + 36000
        assert offer["premium_reserve_cents"] == 41000, \
            f"expected 41000, got {offer['premium_reserve_cents']}"
        unit = get_unit(sc["unit"]["id"])
        assert unit["incentive_reserved_cents"] == 41000
        assert unit["incentive_spent_cents"] == 0

    def test_create_then_withdraw_conserves_budget_ledger(self):
        """PRD section 2.10: "A create-then-withdraw pair and a
        create-then-expire pair each leave both accounts exactly where they
        started, because the reservation taken at creation is released in
        full."
        PRD section 3.6: "withdrawal requires `OFFERED` (else
        `ERR_OFFER_INVALID_STATE`) and moves the offer to `WITHDRAWN` with its
        reserve subtracted from the unit's `incentive_reserved_cents`."

        Design: Difficulty/compensating_invariant/incentive_budget_reserve_release_invariant
        """
        sc = self._setup_critical_shift()
        offer = create_offer(sc["shift"]["id"], premium_multiplier=1.5,
                             flat_bonus_cents=5000)
        withdrawn = validate_success(
            api_client.withdraw_incentive_offer(offer["id"], ADMIN),
            expected_status=200)
        assert withdrawn["status"] == "WITHDRAWN"

        unit = get_unit(sc["unit"]["id"])
        assert unit["incentive_reserved_cents"] == 0, \
            f"withdraw must release the full reserve, got {unit['incentive_reserved_cents']}"
        assert unit["incentive_spent_cents"] == 0
        assert_unit_budget_invariants(unit)
