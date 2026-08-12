"""Claims, segregation of duties, the adjudication waterfall, remit and void."""
import pytest

from test_helpers import (
    ApiErrorId,
    make_billing_specialist_headers,
    make_insurance_specialist_headers,
    remit_claim_payload,
    setup_delivered_order,
    setup_delivered_with_claim,
    validate_error,
    validate_success,
)


class TestClaimCreation:
    def test_second_claim_for_same_order_rejected(self, api, insurance_specialist_headers):
        """PRD §3.6: "At most one claim may exist per source order; a second attempt is
        rejected with `ERR_DUPLICATE_CLAIM`."

        Design: Corner/state_machines/duplicate_claim_rejected
        """
        ctx = setup_delivered_order()
        validate_success(
            api.create_claim({"pump_order_id": ctx["order"]["id"]},
                             insurance_specialist_headers), 201
        )
        res = api.create_claim({"pump_order_id": ctx["order"]["id"]},
                               insurance_specialist_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_CLAIM, expected_status=409)

    def test_billing_specialist_cannot_submit_claim(self, api, billing_specialist_headers):
        """PRD §3.6: "Once an order is `DELIVERED`, an `InsuranceSpecialist` files a
        `Claim` against it" — the endpoint's role list contains only InsuranceSpecialist.
        PRD §2.8: "the role appears in the endpoint's role list (`ERR_FORBIDDEN`, 403)" —
        authorization precedes existence in the pipeline, so the role error surfaces even
        for a nonexistent order reference.

        Design: Corner/rbac/billing_specialist_cannot_submit_claim
        """
        res = api.create_claim(
            {"pump_order_id": "00000000-0000-0000-0000-000000000000"},
            make_billing_specialist_headers("bill-9"),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestSegregationOfDuties:
    def test_submitter_cannot_remit_even_with_imbalanced_amounts(
        self, api, care_coordinator_headers
    ):
        """PRD §2.8: "Every request passes through a fixed validation pipeline, evaluated
        in strict priority order. When several violations exist, the earliest category wins
        and determines the error returned" — segregation of duties (category 7) precedes
        the fiscal remittance-balance check (category 10).
        PRD §3.6: "the remitting `X-User-ID` must differ from the claim's
        `submitted_by_user_id` — the person who filed a claim may never post its
        remittance — else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_remittance_imbalance
        """
        ctx = setup_delivered_with_claim(
            submitter_user_id="ins-1",
            policy_overrides={"deductible_cents": 50000, "coinsurance_pct": 0.2},
        )
        # Same user id as the submitter AND an imbalanced remittance; SoD must win.
        res = api.remit_claim(
            ctx["claim"]["id"],
            remit_claim_payload("APPROVED", 25000, 1),
            make_billing_specialist_headers("ins-1"),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=422)

        claim = validate_success(
            api.get_claim(ctx["claim"]["id"],
                          make_insurance_specialist_headers("ins-1")), 200
        )
        assert claim["status"] == "SUBMITTED"

    def test_rejected_remit_leaves_member_balance_untouched(self, api, care_coordinator_headers):
        """PRD §3.6: "Posting an approved remittance moves the claim
        `SUBMITTED → ADJUDICATED` (or `APPEALED → ADJUDICATED`), stamps
        `remitted_by_user_id`, `remitted_at`, and `remittance_reference`, and ripples the
        ledger: the policy's `deductible_met_cents` rises by `deductible_applied_cents`,
        and the member's `oop_accumulated_cents` and `out_of_pocket_balance_cents` both
        rise by `patient_responsibility_cents`." A rejected remit posts nothing, so the
        ledger stays at zero.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_remittance_imbalance
        """
        ctx = setup_delivered_with_claim(
            submitter_user_id="ins-1",
            policy_overrides={"deductible_cents": 50000, "coinsurance_pct": 0.2},
        )
        api.remit_claim(
            ctx["claim"]["id"],
            remit_claim_payload("APPROVED", 25000, 1),
            make_billing_specialist_headers("ins-1"),
        )
        member = validate_success(api.get_member(ctx["member"]["id"],
                                                 care_coordinator_headers), 200)
        assert member["out_of_pocket_balance_cents"] == 0


class TestRemittanceBalance:
    def test_imbalanced_remittance_rejected(self, api):
        """PRD §3.6: "The invariant then binds: `insurance_paid_cents` must exactly equal
        the adjudicated allowed amount minus the computed patient responsibility, or the
        remit is rejected with `ERR_REMITTANCE_IMBALANCE`."

        Design: Corner/validations/remittance_imbalance_rejected
        """
        ctx = setup_delivered_with_claim(
            submitter_user_id="ins-1",
            policy_overrides={"deductible_cents": 50000, "coinsurance_pct": 0.2},
        )
        # allowed 25000 -> ded_applied 25000, patient 25000; paid must be 0, not 1.
        res = api.remit_claim(
            ctx["claim"]["id"],
            remit_claim_payload("APPROVED", 25000, 1),
            make_billing_specialist_headers("bill-1"),
        )
        validate_error(res, ApiErrorId.ERR_REMITTANCE_IMBALANCE, expected_status=422)

        claim = validate_success(
            api.get_claim(ctx["claim"]["id"],
                          make_insurance_specialist_headers("ins-1")), 200
        )
        assert claim["status"] == "SUBMITTED"


class TestProvisionalVsAdjudicated:
    def test_provisional_estimate_differs_from_adjudicated_result(
        self, api, insurance_specialist_headers, care_coordinator_headers
    ):
        """PRD §3.3: "a forward-looking computation that deliberately uses the deductible
        state as it stands at qualify time and treats the payer-allowed amount as the
        pump's full list price."
        PRD §3.6: "it uses the payer's adjudicated allowed amount and the deductible state
        at remit time, so identical order data can yield a different patient responsibility
        than the qualify-time estimate."

        Design: Difficulty/dual_variant_calc/provisional_vs_adjudicated_patient_responsibility
        """
        ctx = setup_delivered_with_claim(
            submitter_user_id="ins-1",
            policy_overrides={"deductible_cents": 50000, "coinsurance_pct": 0.2,
                              "oop_max_cents": 0},
        )
        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        # Provisional variant: list price 30000 all absorbed by the 50000 deductible.
        assert order["provisional_allowed_cents"] == 30000
        assert order["provisional_patient_cents"] == 30000

        claim = validate_success(
            api.remit_claim(ctx["claim"]["id"],
                            remit_claim_payload("APPROVED", 25000, 0,
                                                remittance_reference="REM-1"),
                            make_billing_specialist_headers("bill-1")), 200
        )
        # Adjudicated variant: payer allowed only 25000, all absorbed by deductible.
        assert claim["deductible_applied_cents"] == 25000
        assert claim["patient_responsibility_cents"] == 25000
        assert claim["status"] == "ADJUDICATED"

    def test_adjudicated_remit_ripples_ledger(self, api, care_coordinator_headers):
        """PRD §3.6: "Posting an approved remittance moves the claim
        `SUBMITTED → ADJUDICATED` (or `APPEALED → ADJUDICATED`), stamps
        `remitted_by_user_id`, `remitted_at`, and `remittance_reference`, and ripples the
        ledger: the policy's `deductible_met_cents` rises by `deductible_applied_cents`,
        and the member's `oop_accumulated_cents` and `out_of_pocket_balance_cents` both
        rise by `patient_responsibility_cents`. The source order's billing moves to
        `ADJUDICATED`."

        Design: Difficulty/dual_variant_calc/provisional_vs_adjudicated_patient_responsibility
        """
        ctx = setup_delivered_with_claim(
            submitter_user_id="ins-1",
            policy_overrides={"deductible_cents": 50000, "coinsurance_pct": 0.2,
                              "oop_max_cents": 0},
        )
        validate_success(
            api.remit_claim(ctx["claim"]["id"],
                            remit_claim_payload("APPROVED", 25000, 0,
                                                remittance_reference="REM-1"),
                            make_billing_specialist_headers("bill-1")), 200
        )
        member = validate_success(
            api.get_member(ctx["member"]["id"], care_coordinator_headers), 200
        )
        assert member["out_of_pocket_balance_cents"] == 25000
        policy = validate_success(
            api.get_policy(ctx["policy"]["id"], care_coordinator_headers), 200
        )
        assert policy["deductible_met_cents"] == 25000
        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["billing_status"] == "ADJUDICATED"


class TestAdjudicationWaterfall:
    def test_oop_max_caps_patient_responsibility(self, api):
        """PRD §3.6: "The deductible remaining is the policy's `deductible_cents` minus
        `deductible_met_cents`, floored at zero; `deductible_applied_cents` is the smaller
        of the adjudicated allowed amount and that remainder. The remainder after
        deductible is multiplied by `coinsurance_pct` and rounded half up to get
        coinsurance. The patient responsibility before any cap is the deductible applied
        plus coinsurance. When the policy's `oop_max_cents` is greater than zero, the final
        `patient_responsibility_cents` is the smaller of that pre-cap amount and the
        headroom remaining under the out-of-pocket maximum".

        Design: Difficulty/combinatorial_formula/adjudication_waterfall_nested_min_max
        """
        ctx = setup_delivered_with_claim(
            submitter_user_id="ins-1",
            policy_overrides={"deductible_cents": 50000, "coinsurance_pct": 0.2,
                              "oop_max_cents": 55000},
        )
        # allowed 100000: ded_applied 50000, coins 10000, pre-cap 60000, capped to 55000.
        claim = validate_success(
            api.remit_claim(ctx["claim"]["id"],
                            remit_claim_payload("APPROVED", 100000, 45000),
                            make_billing_specialist_headers("bill-1")), 200
        )
        assert claim["deductible_applied_cents"] == 50000
        assert claim["patient_responsibility_cents"] == 55000
        assert claim["status"] == "ADJUDICATED"

    def test_waterfall_ripples_policy_and_member(self, api, care_coordinator_headers):
        """PRD §3.6: "the policy's `deductible_met_cents` rises by
        `deductible_applied_cents`, and the member's `oop_accumulated_cents` and
        `out_of_pocket_balance_cents` both rise by `patient_responsibility_cents`."

        Design: Difficulty/combinatorial_formula/adjudication_waterfall_nested_min_max
        """
        ctx = setup_delivered_with_claim(
            submitter_user_id="ins-1",
            policy_overrides={"deductible_cents": 50000, "coinsurance_pct": 0.2,
                              "oop_max_cents": 55000},
        )
        validate_success(
            api.remit_claim(ctx["claim"]["id"],
                            remit_claim_payload("APPROVED", 100000, 45000),
                            make_billing_specialist_headers("bill-1")), 200
        )
        policy = validate_success(
            api.get_policy(ctx["policy"]["id"], care_coordinator_headers), 200
        )
        assert policy["deductible_met_cents"] == 50000
        member = validate_success(
            api.get_member(ctx["member"]["id"], care_coordinator_headers), 200
        )
        assert member["oop_accumulated_cents"] == 55000
        assert member["out_of_pocket_balance_cents"] == 55000


class TestRemitVoidConservation:
    def test_approved_remit_accumulates_member_balances(self, api, care_coordinator_headers):
        """PRD §3.6: "the policy's `deductible_met_cents` rises by
        `deductible_applied_cents`, and the member's `oop_accumulated_cents` and
        `out_of_pocket_balance_cents` both rise by `patient_responsibility_cents`."

        Design: Difficulty/compensating_invariant/remit_void_monetary_conservation
        """
        ctx = setup_delivered_with_claim(
            submitter_user_id="ins-1",
            policy_overrides={"deductible_cents": 50000, "coinsurance_pct": 0.2},
        )
        validate_success(
            api.remit_claim(ctx["claim"]["id"],
                            remit_claim_payload("APPROVED", 25000, 0),
                            make_billing_specialist_headers("bill-1")), 200
        )
        member = validate_success(
            api.get_member(ctx["member"]["id"], care_coordinator_headers), 200
        )
        assert member["out_of_pocket_balance_cents"] == 25000
        assert member["oop_accumulated_cents"] == 25000

    def test_void_reverses_ledger_effects_cent_for_cent(self, api, care_coordinator_headers):
        """PRD §3.6: "a `BillingSpecialist` may void an `ADJUDICATED` claim: the claim
        moves to the terminal `VOID`, the compensation reverses the ledger — the policy's
        `deductible_met_cents` falls by `deductible_applied_cents`, and the member's
        `oop_accumulated_cents` and `out_of_pocket_balance_cents` both fall by
        `patient_responsibility_cents` — and the source order's billing returns to
        `CLAIM_FILED`, leaving the order claimable once more."

        Design: Difficulty/compensating_invariant/remit_void_monetary_conservation
        """
        ctx = setup_delivered_with_claim(
            submitter_user_id="ins-1",
            policy_overrides={"deductible_cents": 50000, "coinsurance_pct": 0.2},
        )
        validate_success(
            api.remit_claim(ctx["claim"]["id"],
                            remit_claim_payload("APPROVED", 25000, 0),
                            make_billing_specialist_headers("bill-1")), 200
        )
        claim = validate_success(
            api.void_claim(ctx["claim"]["id"],
                           make_billing_specialist_headers("bill-2")), 200
        )
        assert claim["status"] == "VOID"

        member = validate_success(
            api.get_member(ctx["member"]["id"], care_coordinator_headers), 200
        )
        assert member["out_of_pocket_balance_cents"] == 0
        assert member["oop_accumulated_cents"] == 0
        policy = validate_success(
            api.get_policy(ctx["policy"]["id"], care_coordinator_headers), 200
        )
        assert policy["deductible_met_cents"] == 0
        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["billing_status"] == "CLAIM_FILED"
