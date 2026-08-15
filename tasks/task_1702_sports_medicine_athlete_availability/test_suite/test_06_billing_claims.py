"""Insurance policies and the claims lifecycle: adjudication, appeals, OCC."""
from test_helpers import (
    ApiErrorId,
    adjudicate_claim,
    appeal_claim,
    appeal_payload,
    claim_line_item,
    claim_submit_payload,
    create_claim,
    get_policy,
    get_success_data,
    setup_policy_scenario,
    submit_claim,
    validate_error,
    validate_success,
)


class TestReadjudicationDivergence:
    def test_readjudication_after_appeal_uses_current_accumulators(self, api, billing_staff_headers):
        """PRD §3.8: "An appealed claim may be re-adjudicated with
        `denial_reason` recorded when `deny` is true; the same calculation
        runs against the current policy accumulators, which may have been
        advanced by other claims between denial and appeal, so identical
        billed amounts can split differently."

        Policy: deductible 25000, coinsurance 90, oop_max 100000.
        Intervening claims advance the accumulators to deductible_met 25000 /
        oop_accrued 40500 before the appealed 200000 claim is re-adjudicated.

        Design: Difficulty/dual_variant_calc/claim_adjudication_initial_vs_readjudication_divergence
        """
        sc = setup_policy_scenario(
            deductible_cents=25000, coinsurance_pct=90, oop_max_cents=100000,
            sport="SOCCER",
        )
        pol_id = sc["policy"]["id"]
        case_id = sc["case"]["id"]

        claim_c = create_claim(case_id, pol_id, 200000, service_date="2026-08-02", cpt_code="X1")
        submit_claim(claim_c["id"], pol_id)
        denied = adjudicate_claim(claim_c["id"], {"deny": True, "denial_reason": "initial denial"})
        assert denied["status"] == "DENIED"

        claim_d = create_claim(case_id, pol_id, 100000, service_date="2026-08-03", cpt_code="X2")
        submit_claim(claim_d["id"], pol_id)
        adj_d = adjudicate_claim(claim_d["id"])
        assert adj_d["payer_paid_cents"] == 67500 and adj_d["patient_resp_cents"] == 32500, (
            "claim D: 25000 deductible + 10% of 75000 = patient 32500, payer 67500"
        )

        claim_e = create_claim(case_id, pol_id, 80000, service_date="2026-08-04", cpt_code="X3")
        submit_claim(claim_e["id"], pol_id)
        adj_e = adjudicate_claim(claim_e["id"])
        assert adj_e["payer_paid_cents"] == 72000 and adj_e["patient_resp_cents"] == 8000, (
            "claim E: deductible met; patient 10% of 80000 = 8000, payer 72000"
        )

        appeal_claim(claim_c["id"], "reconsider")
        adj_c = adjudicate_claim(claim_c["id"])
        assert adj_c["status"] == "PAID"
        assert adj_c["deductible_applied_cents"] == 0, (
            "deductible was fully met by claim D, so nothing remains to apply"
        )
        assert adj_c["patient_resp_cents"] == 20000, (
            "re-adjudication against current accumulators: 10% of 200000 = 20000"
        )
        assert adj_c["payer_paid_cents"] == 180000

    def test_initial_adjudication_on_untouched_accumulators(self, api, billing_staff_headers):
        """PRD §3.8: "The remaining deductible is the greater of zero or
        `deductible_cents` minus `deductible_met_cents`."
        PRD §3.8: "The patient coinsurance is the after-deductible amount
        multiplied by `100` minus `coinsurance_pct`, divided by `100`, rounded
        half-up to zero decimal places; this rounding is applied per claim,
        never per line item."

        The same 200000 billed amount splits 42500/157500 when the
        accumulators have not been advanced by other claims.

        Design: Difficulty/dual_variant_calc/claim_adjudication_initial_vs_readjudication_divergence
        """
        sc = setup_policy_scenario(
            deductible_cents=25000, coinsurance_pct=90, oop_max_cents=100000,
            sport="SOCCER",
        )
        pol_id = sc["policy"]["id"]
        claim = create_claim(sc["case"]["id"], pol_id, 200000,
                             service_date="2026-08-02", cpt_code="X1")
        submit_claim(claim["id"], pol_id)
        adj = adjudicate_claim(claim["id"])
        assert adj["status"] == "PAID"
        assert adj["deductible_applied_cents"] == 25000
        assert adj["patient_resp_cents"] == 42500, (
            "initial adjudication: 25000 deductible + 10% of 175000 = 42500"
        )
        assert adj["payer_paid_cents"] == 157500
        policy = get_policy(pol_id)
        assert policy["deductible_met_cents"] == 25000
        assert policy["oop_accrued_cents"] == 42500


class TestPerClaimRounding:
    def test_coinsurance_rounded_once_per_claim(self, api):
        """PRD §3.8: "The patient coinsurance is the after-deductible amount
        multiplied by `100` minus `coinsurance_pct`, divided by `100`, rounded
        half-up to zero decimal places; this rounding is applied per claim,
        never per line item."

        33333 + 33333 + 33334 = 100000 billed at coinsurance 67:
        patient = round_half_up(100000 * 33 / 100) = 33000, payer = 67000.

        Design: Difficulty/combinatorial_formula/claim_rounding_order_per_claim_not_per_line
        """
        sc = setup_policy_scenario(
            deductible_cents=0, coinsurance_pct=67, oop_max_cents=100000000,
            sport="HOCKEY", surface="ICE", mechanism="OVERUSE",
            dx_code="M70.0", body_region="HIP", position="D",
            season=("2026-08-01", "2027-04-01"),
        )
        items = [
            claim_line_item("A", 33333, "2026-08-02"),
            claim_line_item("B", 33333, "2026-08-02"),
            claim_line_item("C", 33334, "2026-08-02"),
        ]
        claim = create_claim(sc["case"]["id"], sc["policy"]["id"], 100000, line_items=items)
        submit_claim(claim["id"], sc["policy"]["id"])
        adj = adjudicate_claim(claim["id"])
        assert adj["patient_resp_cents"] == 33000
        assert adj["payer_paid_cents"] == 67000
        assert adj["payer_paid_cents"] + adj["patient_resp_cents"] == 100000, (
            "payer + patient must conserve the billed amount"
        )

    def test_per_claim_rounding_not_per_line_sum(self, api):
        """PRD §3.8: "rounded half-up to zero decimal places; this rounding is
        applied per claim, never per line item."

        33335 + 33335 = 66670 billed at coinsurance 67: per-claim patient is
        round_half_up(66670 * 33 / 100) = 22001; summing per-line roundings
        (11001 + 11001) would yield 22002.

        Design: Difficulty/combinatorial_formula/claim_rounding_order_per_claim_not_per_line
        """
        sc = setup_policy_scenario(
            deductible_cents=0, coinsurance_pct=67, oop_max_cents=100000000,
            sport="HOCKEY", surface="ICE", mechanism="OVERUSE",
            dx_code="M70.1", body_region="HIP", position="D",
            season=("2026-08-01", "2027-04-01"),
        )
        items = [
            claim_line_item("A", 33335, "2026-08-02"),
            claim_line_item("B", 33335, "2026-08-02"),
        ]
        claim = create_claim(sc["case"]["id"], sc["policy"]["id"], 66670, line_items=items)
        submit_claim(claim["id"], sc["policy"]["id"])
        adj = adjudicate_claim(claim["id"])
        assert adj["patient_resp_cents"] == 22001, (
            "coinsurance must be rounded once on the aggregate, not per line item"
        )
        assert adj["payer_paid_cents"] == 44669
        assert adj["payer_paid_cents"] + adj["patient_resp_cents"] == 66670


class TestAppealCycle:
    def test_denied_appealed_readjudicated_paid(self, api):
        """PRD §3.8: "A denied claim may be appealed with `appeal_reason`,
        transitioning to `APPEALED` and incrementing `appeals_count`"
        PRD §3.8: "Adjudication may be run against a claim in `SUBMITTED` or
        `APPEALED` (otherwise `ERR_CLAIM_NOT_SUBMITTABLE_STATE`)."

        Design: Difficulty/non_linear_state_machine/claim_appeal_cycle
        """
        sc = setup_policy_scenario(
            deductible_cents=0, coinsurance_pct=80, oop_max_cents=1000000,
            sport="BASEBALL", position="P", dx_code="M75.1",
            body_region="SHOULDER", mechanism="OVERUSE",
            season=("2026-08-01", "2026-11-01"),
        )
        pol_id = sc["policy"]["id"]
        claim = create_claim(sc["case"]["id"], pol_id, 50000,
                             service_date="2026-08-02", cpt_code="S1")
        submit_claim(claim["id"], pol_id)
        denied = adjudicate_claim(claim["id"], {"deny": True, "denial_reason": "not covered"})
        assert denied["status"] == "DENIED"

        appealed = appeal_claim(claim["id"], "additional docs")
        assert appealed["status"] == "APPEALED"
        assert appealed["appeals_count"] == 1

        final = adjudicate_claim(claim["id"])
        assert final["status"] == "PAID", "APPEALED claim must re-enter adjudication"
        assert final["payer_paid_cents"] == 40000
        assert final["patient_resp_cents"] == 10000

    def test_appeal_requires_denied_state(self, api, billing_staff_headers):
        """PRD §3.8: "provided the claim is `DENIED` (otherwise
        `ERR_CLAIM_NOT_DENIED`)".

        Design: Difficulty/non_linear_state_machine/claim_appeal_cycle
        """
        sc = setup_policy_scenario(deductible_cents=0, coinsurance_pct=80,
                                   oop_max_cents=1000000)
        claim = create_claim(sc["case"]["id"], sc["policy"]["id"], 10000,
                             service_date="2026-08-02")
        submit_claim(claim["id"], sc["policy"]["id"])
        resp = api.appeal_claim(claim["id"], appeal_payload("premature"), billing_staff_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_DENIED)


class TestMoneyConservation:
    def test_adjudication_conserves_billed_amount(self, api):
        """PRD §3.8: "The patient responsibility is the smaller of the pre-cap
        amount and the remaining out-of-pocket. The payer paid is the allowed
        amount minus the patient responsibility. The credited deductible is
        the smaller of the deductible applied and the patient responsibility."
        PRD §3.8: "On a non-denial adjudication, `payer_paid_cents`,
        `patient_resp_cents`, and `deductible_applied_cents` are set on the
        claim, `adjudicated_at` is recorded, the policy's
        `deductible_met_cents` increases by the credited deductible amount,
        `oop_accrued_cents` increases by `patient_resp_cents`"

        Billed 120000 against deductible 50000 / coinsurance 80: deductible
        applied 50000, coinsurance 20% of 70000 = 14000, patient 64000, payer
        56000; payer + patient == billed.

        Design: Difficulty/compensating_invariant/claim_money_conservation_across_adjudication
        """
        sc = setup_policy_scenario(
            deductible_cents=50000, coinsurance_pct=80, oop_max_cents=200000,
            sport="SOCCER",
        )
        pol_id = sc["policy"]["id"]
        claim = create_claim(sc["case"]["id"], pol_id, 120000,
                             service_date="2026-08-02", cpt_code="X1")
        submit_claim(claim["id"], pol_id)
        adj = adjudicate_claim(claim["id"])
        assert adj["deductible_applied_cents"] == 50000
        assert adj["patient_resp_cents"] == 64000
        assert adj["payer_paid_cents"] == 56000
        assert adj["payer_paid_cents"] + adj["patient_resp_cents"] == 120000, (
            "money must be conserved across the adjudication split"
        )
        policy = get_policy(pol_id)
        assert policy["deductible_met_cents"] == 50000, (
            "deductible_met must increase by the credited deductible"
        )
        assert policy["oop_accrued_cents"] == 64000, (
            "oop_accrued must increase by patient_resp_cents"
        )

    def test_conservation_holds_at_oop_cap_and_exhausts_policy(self, api):
        """PRD §3.8: "The patient responsibility is the smaller of the pre-cap
        amount and the remaining out-of-pocket."
        PRD §3.8: "if `oop_accrued_cents` reaches or exceeds `oop_max_cents`
        the policy transitions from `ACTIVE` to `EXHAUSTED`."

        Billed 120000 against deductible 50000 / coinsurance 80 / oop_max
        60000: pre-cap patient 64000 is truncated to 60000, payer pays the
        remainder 60000; conservation holds at the cap.

        Design: Difficulty/compensating_invariant/claim_money_conservation_across_adjudication
        """
        sc = setup_policy_scenario(
            deductible_cents=50000, coinsurance_pct=80, oop_max_cents=60000,
            sport="SOCCER",
        )
        pol_id = sc["policy"]["id"]
        claim = create_claim(sc["case"]["id"], pol_id, 120000,
                             service_date="2026-08-02", cpt_code="X1")
        submit_claim(claim["id"], pol_id)
        adj = adjudicate_claim(claim["id"])
        assert adj["patient_resp_cents"] == 60000, "patient responsibility caps at remaining OOP"
        assert adj["payer_paid_cents"] == 60000
        assert adj["payer_paid_cents"] + adj["patient_resp_cents"] == 120000
        policy = get_policy(pol_id)
        assert policy["oop_accrued_cents"] == 60000
        assert policy["status"] == "EXHAUSTED", (
            "reaching oop_max must transition the policy ACTIVE -> EXHAUSTED"
        )


class TestServiceDateWindow:
    def test_service_date_after_policy_year_rejected_end_inclusive(self, api, billing_staff_headers):
        """PRD §3.8: "every `service_date` in `line_items` to lie within the
        inclusive window from `policy_year_start` to `policy_year_end`
        (otherwise `ERR_SERVICE_DATE_OUT_OF_POLICY_YEAR`)".

        A line dated 2027-01-01 (one day past a 2026-12-31 year end) is
        rejected; a line dated exactly 2026-12-31 submits.

        Design: Difficulty/resource_temporal_overlap/claim_service_date_policy_year_window_containment
        """
        sc = setup_policy_scenario(
            deductible_cents=0, coinsurance_pct=80, oop_max_cents=500000,
            sport="HOCKEY", surface="ICE", dx_code="M70.0", body_region="HIP",
            position="D", season=("2026-08-01", "2027-04-01"),
        )
        pol_id = sc["policy"]["id"]
        case_id = sc["case"]["id"]
        claim_out = create_claim(
            case_id, pol_id, 10000,
            line_items=[claim_line_item("A", 10000, "2027-01-01")],
        )
        policy = get_policy(pol_id)
        resp = api.submit_claim(
            claim_out["id"], claim_submit_payload(policy["version"]), billing_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_OUT_OF_POLICY_YEAR)

        claim_edge = create_claim(
            case_id, pol_id, 10000,
            line_items=[claim_line_item("B", 10000, "2026-12-31")],
        )
        submitted = submit_claim(claim_edge["id"], pol_id)
        assert submitted["status"] == "SUBMITTED", (
            "service_date equal to policy_year_end is inside the inclusive window"
        )

    def test_service_date_year_start_boundary_inclusive(self, api, billing_staff_headers):
        """PRD §3.8: "every `service_date` in `line_items` to lie within the
        inclusive window from `policy_year_start` to `policy_year_end`
        (otherwise `ERR_SERVICE_DATE_OUT_OF_POLICY_YEAR`)".

        A line dated exactly policy_year_start (2026-01-01) submits; one day
        earlier (2025-12-31) is rejected.

        Design: Difficulty/resource_temporal_overlap/claim_service_date_policy_year_window_containment
        """
        sc = setup_policy_scenario(deductible_cents=0, coinsurance_pct=80,
                                   oop_max_cents=500000)
        pol_id = sc["policy"]["id"]
        case_id = sc["case"]["id"]
        claim_edge = create_claim(
            case_id, pol_id, 10000,
            line_items=[claim_line_item("A", 10000, "2026-01-01")],
        )
        submitted = submit_claim(claim_edge["id"], pol_id)
        assert submitted["status"] == "SUBMITTED"

        claim_before = create_claim(
            case_id, pol_id, 10000,
            line_items=[claim_line_item("B", 10000, "2025-12-31")],
        )
        policy = get_policy(pol_id)
        resp = api.submit_claim(
            claim_before["id"], claim_submit_payload(policy["version"]), billing_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_OUT_OF_POLICY_YEAR)


class TestSubmitValidationPriority:
    def test_sum_mismatch_precedes_inactive_policy(self, api, billing_staff_headers):
        """PRD §2.5: "... field-level constraints, claim integrity, temporal
        window checks, supersede-target validity, future-date rejection,
        policy activity, appeal budget, and finally uniqueness constraints. A
        higher-priority failure masks all lower-priority failures for the same
        request."
        PRD §3.8: "the sum of `charge_cents` across `line_items` to equal
        `billed_amount_cents` (otherwise `ERR_LINE_ITEM_SUM_MISMATCH`)".

        A claim whose line items sum to 40000 against a billed 50000, on a
        CANCELLED policy, fails claim integrity before policy activity.

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_claim_submit
        """
        sc = setup_policy_scenario(deductible_cents=0, coinsurance_pct=80,
                                   oop_max_cents=500000)
        pol_id = sc["policy"]["id"]
        get_success_data(api.cancel_insurance_policy(pol_id, billing_staff_headers))
        claim = create_claim(
            sc["case"]["id"], pol_id, 50000,
            line_items=[claim_line_item("A", 40000, "2026-08-02")],
        )
        policy = get_policy(pol_id)
        resp = api.submit_claim(
            claim["id"], claim_submit_payload(policy["version"]), billing_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_LINE_ITEM_SUM_MISMATCH)

    def test_sum_mismatch_against_active_policy(self, api, billing_staff_headers):
        """PRD §3.8: "the sum of `charge_cents` across `line_items` to equal
        `billed_amount_cents` (otherwise `ERR_LINE_ITEM_SUM_MISMATCH`)".

        Isolated claim-integrity failure against an ACTIVE policy.

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_claim_submit
        """
        sc = setup_policy_scenario(deductible_cents=0, coinsurance_pct=80,
                                   oop_max_cents=500000)
        claim = create_claim(
            sc["case"]["id"], sc["policy"]["id"], 50000,
            line_items=[claim_line_item("A", 40000, "2026-08-02")],
        )
        policy = get_policy(sc["policy"]["id"])
        resp = api.submit_claim(
            claim["id"], claim_submit_payload(policy["version"]), billing_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_LINE_ITEM_SUM_MISMATCH)

    def test_inactive_policy_with_matching_sum(self, api, billing_staff_headers):
        """PRD §3.8: "Submitting a claim requires it to be `DRAFT` (otherwise
        `ERR_CLAIM_NOT_DRAFT`), the referenced policy to be `ACTIVE`
        (otherwise `ERR_POLICY_NOT_ACTIVE`)".

        Isolated policy-activity failure with a matching line-item sum.

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_claim_submit
        """
        sc = setup_policy_scenario(deductible_cents=0, coinsurance_pct=80,
                                   oop_max_cents=500000)
        pol_id = sc["policy"]["id"]
        get_success_data(api.cancel_insurance_policy(pol_id, billing_staff_headers))
        claim = create_claim(sc["case"]["id"], pol_id, 50000,
                             service_date="2026-08-02")
        policy = get_policy(pol_id)
        resp = api.submit_claim(
            claim["id"], claim_submit_payload(policy["version"]), billing_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE)


class TestPolicyAndAppealConstraints:
    def test_duplicate_policy_number_rejected(self, api, billing_staff_headers):
        """PRD §3.8: "The pair `(athlete_id, policy_number)` must be unique
        among non-`CANCELLED` policies; a duplicate is rejected with
        `ERR_DUPLICATE_POLICY_NUMBER`."

        Design: Corner/validations/duplicate_policy_number_rejected
        """
        sc = setup_policy_scenario(policy_number="PN-1")
        resp = api.create_insurance_policy(
            {
                "athlete_id": sc["athlete"]["id"],
                "payer_name": "Payer2",
                "policy_number": "PN-1",
                "deductible_cents": 0,
                "coinsurance_pct": 70,
                "oop_max_cents": 50000,
                "policy_year_start": "2026-01-01",
                "policy_year_end": "2026-12-31",
            },
            billing_staff_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_POLICY_NUMBER)

    def test_fourth_appeal_rejected(self, api, billing_staff_headers):
        """PRD §3.8: "A denied claim may be appealed with `appeal_reason`,
        transitioning to `APPEALED` and incrementing `appeals_count`, provided
        the claim is `DENIED` (otherwise `ERR_CLAIM_NOT_DENIED`) and
        `appeals_count` is less than `3` (otherwise
        `ERR_MAX_APPEALS_REACHED`)."

        Design: Corner/validations/max_appeals_enforced
        """
        sc = setup_policy_scenario(
            deductible_cents=0, coinsurance_pct=80, oop_max_cents=1000000,
            sport="BASEBALL", position="P", dx_code="M75.1",
            body_region="SHOULDER", mechanism="OVERUSE",
            season=("2026-08-01", "2026-11-01"),
        )
        pol_id = sc["policy"]["id"]
        claim = create_claim(sc["case"]["id"], pol_id, 10000,
                             service_date="2026-08-02", cpt_code="S1")
        submit_claim(claim["id"], pol_id)
        last = None
        for i in range(3):
            denied = adjudicate_claim(claim["id"], {"deny": True, "denial_reason": f"d{i + 1}"})
            assert denied["status"] == "DENIED"
            last = appeal_claim(claim["id"], f"a{i + 1}")
            assert last["status"] == "APPEALED"
        assert last["appeals_count"] == 3
        denied3 = adjudicate_claim(claim["id"], {"deny": True, "denial_reason": "d4"})
        assert denied3["status"] == "DENIED"
        assert denied3["appeals_count"] == 3

        resp = api.appeal_claim(claim["id"], appeal_payload("a4"), billing_staff_headers)
        validate_error(resp, ApiErrorId.ERR_MAX_APPEALS_REACHED)


class TestPolicyOcc:
    def test_submit_with_stale_policy_version_rejected(self, api, billing_staff_headers):
        """PRD §2.6: "A request to submit a claim must carry
        `expected_policy_version` matching the referenced insurance policy's
        current `version`. If the supplied value does not match the parent
        entity's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.8: "On submission, `submitted_at` is set to the current logical
        timestamp and the policy's `version` increments."

        Design: Corner/cross_cutting_layers/stale_policy_version_on_submit_returns_412
        """
        sc = setup_policy_scenario(deductible_cents=0, coinsurance_pct=80,
                                   oop_max_cents=500000)
        pol_id = sc["policy"]["id"]
        stale_version = sc["policy"]["version"]
        case_id = sc["case"]["id"]
        claim1 = create_claim(case_id, pol_id, 10000,
                              line_items=[claim_line_item("A", 10000, "2026-08-02")])
        claim2 = create_claim(case_id, pol_id, 20000,
                              line_items=[claim_line_item("B", 20000, "2026-08-03")])
        submitted = submit_claim(claim1["id"], pol_id)
        assert submitted["status"] == "SUBMITTED"
        # claim1's submission bumped the policy version; claim2's stale
        # expected version must now be rejected.
        resp = api.submit_claim(
            claim2["id"], claim_submit_payload(stale_version), billing_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestImmediateConsistency:
    def test_adjudication_visible_on_claim_and_policy(self, api, billing_staff_headers):
        """PRD §3.8: "On a non-denial adjudication, `payer_paid_cents`,
        `patient_resp_cents`, and `deductible_applied_cents` are set on the
        claim, `adjudicated_at` is recorded, the policy's
        `deductible_met_cents` increases by the credited deductible amount,
        `oop_accrued_cents` increases by `patient_resp_cents`, the policy's
        `version` increments"

        Design: Corner/consistency_model/adjudication_immediately_visible_on_claim_and_policy
        """
        sc = setup_policy_scenario(deductible_cents=0, coinsurance_pct=80,
                                   oop_max_cents=500000)
        pol_id = sc["policy"]["id"]
        claim = create_claim(sc["case"]["id"], pol_id, 10000,
                             line_items=[claim_line_item("A", 10000, "2026-08-02")])
        submit_claim(claim["id"], pol_id)
        resp = api.adjudicate_claim(claim["id"], {}, billing_staff_headers)
        adj = validate_success(resp)
        assert adj["payer_paid_cents"] == 8000, "80% of 10000 paid by payer"
        assert adj["patient_resp_cents"] == 2000
        policy = get_success_data(api.get_insurance_policy(pol_id, billing_staff_headers))
        assert policy["oop_accrued_cents"] == 2000, (
            "the immediately following read must reflect the adjudication update"
        )
        assert policy["deductible_met_cents"] == 0
