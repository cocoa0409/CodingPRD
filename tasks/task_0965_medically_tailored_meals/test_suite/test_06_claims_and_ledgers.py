"""Claims, remittance, ledger reconciliation, and billing error paths
(PRD §3.7, §2.10)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_delivery_payload,
    create_reauthorization, get_reauthorization, get_member,
    setup_draft_claim, setup_submitted_claim, setup_scheduled_delivery,
)

W145 = {"full_name": "M Claimant", "payer_member_id": "W-X45",
        "income_fpl_percent": 145, "household_size": 3}
TWO_LINES = (("rice_bowl", 1), ("broth_soup", 1))


def _submitted_claim_1758(member_name, payer_member_id, driver_id):
    """Waiver member at fpl 145 (5% tier) with a SUBMITTED claim for a
    two-line cycle: gross 1850, share 92, plan liability 1758."""
    return setup_submitted_claim(
        member_overrides={"full_name": member_name,
                          "payer_member_id": payer_member_id,
                          "income_fpl_percent": 145, "household_size": 3},
        item_specs=TWO_LINES,
        week_start_date="2026-04-13",
        route_overrides={"driver_id": driver_id, "route_date": "2026-04-15"},
        submitted_by="bill-1")


class TestClaimProvisionalVsFinalVariant:
    def test_provisional_rate_card_vs_final_adjudicated_remit(
            self, api, payer_reviewer_headers):
        """PRD §3.7: "The per-meal rate is 925 cents when `payer_type_snapshot`
        is `MEDICAID_WAIVER` and 1180 cents for `MEDICARE_ADVANTAGE`."
        PRD §3.7: "These figures are the claim's provisional variant; the final
        variant is the adjudicated `remitted_amount_cents` recorded at
        remittance, and a fully paid claim remits exactly `plan_liability_cents`,
        which differs from `provisional_gross_cents` whenever the cost share is
        non-zero."

        Design: Difficulty/dual_variant_calc/claim_amount_provisional_vs_final_remit
        """
        ctx = _submitted_claim_1758("M One", "W-100", "drv-1")
        claim = ctx["claim"]
        assert claim["provisional_gross_cents"] == 1850, "2 units x 925 rate card"
        assert claim["member_cost_share_cents"] == 92
        assert claim["plan_liability_cents"] == 1758
        remitted = validate_success(api.remit_claim(
            claim["id"], "PAID", payer_reviewer_headers,
            remitted_amount_cents=1758))
        assert remitted["remitted_amount_cents"] == 1758
        assert remitted["remitted_amount_cents"] != \
            remitted["provisional_gross_cents"], \
            "final variant differs from the provisional rate-card variant"
        assert remitted["status"] == "PAID"

    def test_paid_remit_moves_money_onto_ledgers(self, api,
                                                 payer_reviewer_headers):
        """PRD §3.7: "A paid or partially paid remittance moves money onto the
        ledgers: the member's `oop_accumulator_cents` increases by the claim's
        `member_cost_share_cents`, and the authorization's
        `consumed_amount_cents` increases by `remitted_amount_cents` with a
        `version` bump."

        Design: Difficulty/dual_variant_calc/claim_amount_provisional_vs_final_remit
        """
        ctx = _submitted_claim_1758("M One", "W-100", "drv-1")
        validate_success(api.remit_claim(ctx["claim"]["id"], "PAID",
                                         payer_reviewer_headers,
                                         remitted_amount_cents=1758))
        member = get_member(ctx["member"]["id"])
        assert member["oop_accumulator_cents"] == 92
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["consumed_amount_cents"] == 1758


class TestCostSharePerLineRoundingOrder:
    def test_two_lines_round_per_line_then_sum(self, api):
        """PRD §3.7: "Each line's share is that tier percentage of the line
        gross, rounded half-up to whole cents per line first, and
        `member_cost_share_cents` is the sum of those per-line amounts —
        rounding after summing is forbidden because it yields different cents
        (two 925-cent lines at the five-percent tier give 46 plus 46, that is 92
        cents per-line, versus 93 cents if the sum were rounded once)."

        Design: Difficulty/combinatorial_formula/cost_share_per_line_rounding_order
        """
        ctx = setup_draft_claim(
            member_overrides={"full_name": "M Three",
                              "payer_member_id": "W-300",
                              "income_fpl_percent": 145, "household_size": 4},
            item_specs=TWO_LINES,
            week_start_date="2026-04-13",
            route_overrides={"driver_id": "drv-2", "route_date": "2026-04-15"})
        claim = ctx["claim"]
        assert claim["provisional_gross_cents"] == 1850
        assert claim["member_cost_share_cents"] == 92, \
            "per-line round_half_up of 46.25 gives 46 + 46 = 92"
        assert claim["member_cost_share_cents"] != 93, \
            "93 would be the forbidden sum-then-round of 92.5"
        assert claim["plan_liability_cents"] == 1758
        assert claim["units_delivered"] == 2

    def test_single_line_of_two_units_rounds_once_to_93(self, api):
        """PRD §3.7: "Each line's share is that tier percentage of the line
        gross, rounded half-up to whole cents per line first, and
        `member_cost_share_cents` is the sum of those per-line amounts —
        rounding after summing is forbidden because it yields different cents
        (two 925-cent lines at the five-percent tier give 46 plus 46, that is 92
        cents per-line, versus 93 cents if the sum were rounded once)."

        One line of quantity 2 (gross 1850) rounds once: round_half_up(92.5)
        is 93 — proving the rounding boundary is the line, not the claim.

        Design: Difficulty/combinatorial_formula/cost_share_per_line_rounding_order
        """
        ctx = setup_draft_claim(
            member_overrides={"full_name": "M Three",
                              "payer_member_id": "W-300",
                              "income_fpl_percent": 145, "household_size": 4},
            item_specs=(("rice_bowl", 2),),
            week_start_date="2026-04-13",
            route_overrides={"driver_id": "drv-2", "route_date": "2026-04-15"})
        claim = ctx["claim"]
        assert claim["provisional_gross_cents"] == 1850
        assert claim["member_cost_share_cents"] == 93
        assert claim["plan_liability_cents"] == 1757
        assert claim["units_delivered"] == 2


class TestClaimSubmitOrdering:
    def _setup_cancelled_cycle_claim(self):
        """DRAFT claim whose cycle was FROZEN at creation (one DELIVERED, one
        open delivery), then CANCELLED; authorization max_amount 1000 is below
        the 1850 gross, so both a state rule and a fiscal rule are violated."""
        ctx = setup_draft_claim(
            member_overrides={"full_name": "M Nine", "payer_member_id": "W-900",
                              "income_fpl_percent": 145, "household_size": 3},
            item_specs=TWO_LINES,
            week_start_date="2026-04-13",
            auth_overrides={"max_amount_cents": 1000},
            route_overrides={"driver_id": "drv-6", "route_date": "2026-04-15"},
            extra_open_deliveries=1)
        return ctx

    def test_state_error_beats_fiscal_error(self, api, dietitian_headers,
                                            billing_specialist_headers):
        """PRD §3.7: "The cycle's state is checked first — it must be `FROZEN`
        or `FULFILLED`, else `ERR_MENU_CYCLE_NOT_FROZEN` — then the
        authorization must be `APPROVED` (otherwise
        `ERR_AUTHORIZATION_NOT_APPROVED`), and only then the fiscal headroom"

        Design: Difficulty/priority_pair_validation_conflict/claim_submit_state_beats_fiscal
        """
        ctx = self._setup_cancelled_cycle_claim()
        validate_success(api.cancel_cycle(ctx["cycle"]["id"], dietitian_headers))
        resp = api.submit_claim(ctx["claim"]["id"], billing_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_MENU_CYCLE_NOT_FROZEN)

    def test_rejected_submit_leaves_claim_draft(self, api, dietitian_headers,
                                                billing_specialist_headers):
        """PRD §3.7: "A `BillingSpecialist` submits a `DRAFT` claim (any other
        status draws `ERR_CLAIM_NOT_DRAFT`). The cycle's state is checked first
        — it must be `FROZEN` or `FULFILLED`, else `ERR_MENU_CYCLE_NOT_FROZEN`"

        Design: Difficulty/priority_pair_validation_conflict/claim_submit_state_beats_fiscal
        """
        ctx = self._setup_cancelled_cycle_claim()
        validate_success(api.cancel_cycle(ctx["cycle"]["id"], dietitian_headers))
        validate_error(api.submit_claim(ctx["claim"]["id"],
                                        billing_specialist_headers),
                       ApiErrorId.ERR_MENU_CYCLE_NOT_FROZEN)
        claim = validate_success(api.get_claim(ctx["claim"]["id"],
                                               billing_specialist_headers))
        assert claim["status"] == "DRAFT", "a rejected submit must not mutate"


class TestClaimSubmitRequiresApprovedAuthorization:
    def _setup_expiring_authorization_claim(self):
        """DRAFT claim against an APPROVED authorization whose end_date is
        2026-04-30; the logical clock then advances past it."""
        return setup_draft_claim(
            member_overrides={"full_name": "M Fourteen",
                              "payer_member_id": "W-410"},
            item_specs=(("rice_bowl", 5),),
            week_start_date="2026-04-13",
            auth_overrides={"end_date": "2026-04-30",
                            "assessed_at": "2026-03-01"},
            route_overrides={"driver_id": "drv-10", "route_date": "2026-04-15"})

    def test_expired_authorization_blocks_submit(self, api,
                                                 program_admin_headers,
                                                 billing_specialist_headers):
        """PRD §2.4: "Any reauthorization in `APPROVED` status whose `end_date`
        has been passed transitions automatically to `EXPIRED`."
        PRD §3.7: "then the authorization must be `APPROVED` (otherwise
        `ERR_AUTHORIZATION_NOT_APPROVED`)"

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_authorization_approved
        """
        ctx = self._setup_expiring_authorization_claim()
        validate_success(api.set_clock("2026-05-02T00:00:00Z",
                                       program_admin_headers))
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["status"] == "EXPIRED"
        resp = api.submit_claim(ctx["claim"]["id"], billing_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_APPROVED)

    def test_rejected_submit_leaves_claim_and_authorization_unchanged(
            self, api, program_admin_headers, billing_specialist_headers):
        """PRD §2.4: "Any reauthorization in `APPROVED` status whose `end_date`
        has been passed transitions automatically to `EXPIRED`. Both are
        terminal."
        PRD §3.7: "then the authorization must be `APPROVED` (otherwise
        `ERR_AUTHORIZATION_NOT_APPROVED`)"

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_authorization_approved
        """
        ctx = self._setup_expiring_authorization_claim()
        validate_success(api.set_clock("2026-05-02T00:00:00Z",
                                       program_admin_headers))
        validate_error(api.submit_claim(ctx["claim"]["id"],
                                        billing_specialist_headers),
                       ApiErrorId.ERR_AUTHORIZATION_NOT_APPROVED)
        claim = validate_success(api.get_claim(ctx["claim"]["id"],
                                               billing_specialist_headers))
        assert claim["status"] == "DRAFT"
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["status"] == "EXPIRED"


class TestVoidReversalInvariant:
    def test_paid_remit_sets_ledgers(self, api, payer_reviewer_headers):
        """PRD §3.7: "A paid or partially paid remittance moves money onto the
        ledgers: the member's `oop_accumulator_cents` increases by the claim's
        `member_cost_share_cents`, and the authorization's
        `consumed_amount_cents` increases by `remitted_amount_cents` with a
        `version` bump."

        Design: Difficulty/compensating_invariant/member_oop_void_reversal_invariant
        """
        ctx = _submitted_claim_1758("M Seventeen", "W-710", "drv-12")
        validate_success(api.remit_claim(ctx["claim"]["id"], "PAID",
                                         payer_reviewer_headers,
                                         remitted_amount_cents=1758))
        assert get_member(ctx["member"]["id"])["oop_accumulator_cents"] == 92
        assert get_reauthorization(
            ctx["authorization"]["id"])["consumed_amount_cents"] == 1758

    def test_void_by_different_operator_restores_ledgers_bit_identical(
            self, api, payer_reviewer_headers):
        """PRD §2.10: "A remittance followed by its void must leave both
        accumulators bit-identical to their pre-remittance values."
        PRD §3.7: "A successful void performs the compensating reversal — the
        member's `oop_accumulator_cents` decreases by the claim's
        `member_cost_share_cents`, and the authorization's
        `consumed_amount_cents` decreases by `remitted_amount_cents` with a
        `version` bump"

        Design: Difficulty/compensating_invariant/member_oop_void_reversal_invariant
        """
        from test_helpers import make_billing_specialist_headers
        ctx = _submitted_claim_1758("M Seventeen", "W-710", "drv-12")
        validate_success(api.remit_claim(ctx["claim"]["id"], "PAID",
                                         payer_reviewer_headers,
                                         remitted_amount_cents=1758))
        voided = validate_success(api.void_claim(
            ctx["claim"]["id"], make_billing_specialist_headers("bill-2")))
        assert voided["status"] == "VOIDED", \
            "bill-2 is segregated from the submitter bill-1 and may void"
        member = get_member(ctx["member"]["id"])
        assert member["oop_accumulator_cents"] == 0, \
            "void must reverse the cost share exactly"
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["consumed_amount_cents"] == 0, \
            "void must reverse the consumed amount exactly"


class TestClaimResubmissionCycle:
    def test_claim_denied_correct_resubmit_cycle(
            self, api, payer_reviewer_headers, billing_specialist_headers):
        """PRD §3.7: "A denied claim is not dead: a `BillingSpecialist` may
        correct a `DENIED` claim back to `DRAFT` (otherwise
        `ERR_CLAIM_NOT_DENIED`), and the draft-submitted-denied-draft loop may
        repeat."
        PRD §3.7: "`DENIED` requires the amount to be omitted or zero."

        Design: Corner/state_machines/claim_denied_correct_resubmit_cycle
        """
        ctx = setup_submitted_claim(
            member_overrides={"full_name": "S Four", "payer_member_id": "W-S4"},
            item_specs=(("rice_bowl", 5),),
            week_start_date="2026-04-13",
            route_overrides={"driver_id": "drv-s4", "route_date": "2026-04-15"},
            submitted_by="bill-1")
        claim_id = ctx["claim"]["id"]
        denied = validate_success(api.remit_claim(claim_id, "DENIED",
                                                  payer_reviewer_headers))
        assert denied["status"] == "DENIED"
        assert get_member(ctx["member"]["id"])["oop_accumulator_cents"] == 0, \
            "a denial moves no money"
        corrected = validate_success(api.correct_claim(claim_id,
                                                       billing_specialist_headers))
        assert corrected["status"] == "DRAFT"
        resubmitted = validate_success(api.submit_claim(
            claim_id, billing_specialist_headers))
        assert resubmitted["status"] == "SUBMITTED"


class TestRemitAmountRules:
    def test_remit_paid_with_wrong_amount_rejected(
            self, api, payer_reviewer_headers, billing_specialist_headers):
        """PRD §3.7: "An outcome of `PAID` requires `remitted_amount_cents` to
        equal `plan_liability_cents` exactly"
        PRD §3.7: "Any other combination is rejected with
        `ERR_REMIT_AMOUNT_MISMATCH`."

        Design: Corner/validations/remit_paid_with_wrong_amount_rejected
        """
        ctx = setup_submitted_claim(
            member_overrides={"full_name": "V Three", "payer_member_id": "W-V3"},
            item_specs=(("rice_bowl", 5),),
            week_start_date="2026-04-13",
            route_overrides={"driver_id": "drv-v3", "route_date": "2026-04-15"},
            submitted_by="bill-1")
        assert ctx["claim"]["plan_liability_cents"] == 4625, \
            "5 x 925 at the zero-percent tier (fpl 130)"
        resp = api.remit_claim(ctx["claim"]["id"], "PAID",
                               payer_reviewer_headers, remitted_amount_cents=1000)
        validate_error(resp, ApiErrorId.ERR_REMIT_AMOUNT_MISMATCH)
        claim = validate_success(api.get_claim(ctx["claim"]["id"],
                                               billing_specialist_headers))
        assert claim["status"] == "SUBMITTED"


class TestSegregationOfDuties:
    def test_error_segregation_of_duties_on_void(
            self, api, payer_reviewer_headers, billing_specialist_headers):
        """PRD §3.7: "the operator voiding must not be the operator who
        submitted: if the caller's `X-User-ID` equals the claim's
        `submitted_by_user_id`, the void is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/errors/error_segregation_of_duties_on_void
        """
        ctx = _submitted_claim_1758("N Five", "W-N5", "drv-n5")
        claim_id = ctx["claim"]["id"]
        validate_success(api.remit_claim(claim_id, "PAID", payer_reviewer_headers,
                                         remitted_amount_cents=1758))
        resp = api.void_claim(claim_id, billing_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        claim = validate_success(api.get_claim(claim_id,
                                               billing_specialist_headers))
        assert claim["status"] == "PAID", "a rejected void must not reverse"
        assert get_member(ctx["member"]["id"])["oop_accumulator_cents"] == 92


class TestAuthorizationExhaustedOnSchedule:
    def test_error_authorization_exhausted_on_schedule(
            self, api, logistics_coordinator_headers):
        """PRD §3.5: "if covering authorizations exist but every one is out of
        available units, the rejection is the fiscal `ERR_AUTHORIZATION_EXHAUSTED`
        (HTTP 402)."

        Design: Corner/errors/error_authorization_exhausted_on_schedule
        """
        ctx = setup_scheduled_delivery(
            member_overrides={"full_name": "N Six", "payer_member_id": "W-N6"},
            auth_overrides={"authorized_units": 1},
            route_overrides={"driver_id": "drv-n6"})
        resp = api.create_delivery(
            create_delivery_payload(ctx["member"]["id"], ctx["cycle"]["id"],
                                    ctx["route"]["id"], service_date="2026-05-06"),
            logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_EXHAUSTED)
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["reserved_units"] == 1, "no partial reservation on rejection"


class TestMedicareAdvantageCostShare:
    def test_ma_flat_copay_cost_share(self, api):
        """PRD §3.7: "Under Medicare Advantage, the cost share is a flat copay
        of 500 cents capped by annual out-of-pocket headroom:
        `member_cost_share_cents` is the lesser of 500 and the member's
        remaining headroom, where headroom is 34000 cents minus the member's
        current `oop_accumulator_cents`, floored at zero."
        PRD §3.7: "The per-meal rate is 925 cents when `payer_type_snapshot` is
        `MEDICAID_WAIVER` and 1180 cents for `MEDICARE_ADVANTAGE`."

        Design: Corner/calculations/ma_flat_copay_cost_share
        """
        ctx = setup_draft_claim(
            member_overrides={"full_name": "K Two",
                              "payer_type": "MEDICARE_ADVANTAGE",
                              "payer_member_id": "MA-K2",
                              "income_fpl_percent": 200, "household_size": 1},
            prescription_overrides={
                "diet_type": "DIABETIC", "daily_sodium_mg_max": 2300,
                "daily_potassium_mg_max": 3000, "daily_phosphorus_mg_max": 1200,
                "daily_carbs_g_max": 200, "daily_protein_g_min": 10},
            item_specs=(("chicken_plate", 2),),
            week_start_date="2026-04-13",
            route_overrides={"driver_id": "drv-k2", "route_date": "2026-04-15"})
        claim = ctx["claim"]
        assert claim["payer_type_snapshot"] == "MEDICARE_ADVANTAGE"
        assert claim["provisional_gross_cents"] == 2360, "2 x 1180 rate card"
        assert claim["member_cost_share_cents"] == 500, \
            "flat MA copay; headroom 34000 - 0"
        assert claim["plan_liability_cents"] == 1860
