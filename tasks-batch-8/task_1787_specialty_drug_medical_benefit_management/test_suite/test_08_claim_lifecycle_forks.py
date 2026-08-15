"""Claim adjudication forks, the suspend/reinstate cycle, exhaustion, and expiry
sweeps (PRD §3.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_claim_payload,
    get_auth,
    get_claim,
    get_provider,
    list_claims_for_auth,
    make_mpo_headers,
    pay_claim,
    set_clock,
    setup_approved_scenario,
    submit_claim,
    TEST_USERS,
    validate_error,
    validate_success,
)

MPO = TEST_USERS["mpo_headers"]
ADMIN = TEST_USERS["plan_admin_headers"]


class TestSuspendReinstateCycle:
    def _cycle_scenario(self, j_code="J2500", member_id="MEM-4"):
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": j_code, "drug_name": "CycleDrug"},
            member_id=member_id,
        )
        claim_paid = submit_claim(scenario, billed_units=10)
        pay_claim(claim_paid["id"])
        claim_open = submit_claim(scenario, billed_units=10)
        assert claim_open["status"] == "APPROVED_FOR_PAYMENT"
        return scenario, claim_paid, claim_open

    def test_suspend_pends_only_unpaid_approved_claims(self, api):
        """PRD §3.4: "Suspending requires the authorization to be `APPROVED` — otherwise
        `ERR_AUTH_NOT_APPROVED` — and moves it to `SUSPENDED`; every claim of that
        authorization currently `APPROVED_FOR_PAYMENT` is pended with `pend_reason`
        `AUTH_SUSPENDED`, while `PAID`, `ADJUSTED`, and dose-review-pended claims are
        untouched."

        Design: Difficulty/non_linear_state_machine/auth_suspend_reinstate_cycle
        """
        scenario, claim_paid, claim_open = self._cycle_scenario()
        suspended = validate_success(api.suspend_auth(scenario["auth"]["id"], MPO))
        assert suspended["status"] == "SUSPENDED"

        open_after = get_claim(claim_open["id"])
        assert open_after["status"] == "PENDED"
        assert open_after["pend_reason"] == "AUTH_SUSPENDED"

        paid_after = get_claim(claim_paid["id"])
        assert paid_after["status"] == "PAID", "the paid sibling claim is untouched"

    def test_reinstate_restores_cycle_with_debits_intact(self, api):
        """PRD §3.4: "Reinstating requires `SUSPENDED` — otherwise
        `ERR_AUTH_NOT_SUSPENDED` — and returns the authorization to `APPROVED`; exactly
        those claims pended with `AUTH_SUSPENDED` return to `APPROVED_FOR_PAYMENT`,
        claims pended for dose review stay pended, and `administrations_used` is left
        unchanged."

        Design: Difficulty/non_linear_state_machine/auth_suspend_reinstate_cycle
        """
        scenario, claim_paid, claim_open = self._cycle_scenario("J2501", "MEM-4B")
        auth_id = scenario["auth"]["id"]
        api.suspend_auth(auth_id, MPO)
        reinstated = validate_success(api.reinstate_auth(auth_id, MPO))
        assert reinstated["status"] == "APPROVED"

        assert get_claim(claim_open["id"])["status"] == "APPROVED_FOR_PAYMENT"
        assert get_claim(claim_paid["id"])["status"] == "PAID"
        # Both debits (the paid claim's and the open claim's) survived the cycle.
        assert get_auth(auth_id)["administrations_used"] == 2


class TestUtilizationConservation:
    def test_suspend_reinstate_conserves_administration_count(self, api):
        """PRD §3.4: "`administrations_used` is left unchanged" across reinstatement — the
        suspend + reinstate pair performs no double debit and no release.

        Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_utilization
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J3700", "drug_name": "UtilDrug"},
            member_id="MEM-17",
        )
        claim = submit_claim(scenario, billed_units=10)
        auth_id = scenario["auth"]["id"]
        assert get_auth(auth_id)["administrations_used"] == 1

        api.suspend_auth(auth_id, MPO)
        assert get_auth(auth_id)["administrations_used"] == 1
        api.reinstate_auth(auth_id, MPO)

        auth_after = get_auth(auth_id)
        assert auth_after["status"] == "APPROVED"
        assert auth_after["administrations_used"] == 1, "no debit drift across the cycle"
        claim_after = get_claim(claim["id"])
        assert claim_after["status"] == "APPROVED_FOR_PAYMENT"
        assert claim_after["pend_reason"] is None

    def test_approved_for_payment_count_across_cycle(self, api):
        """PRD §3.4: "every claim of that authorization currently `APPROVED_FOR_PAYMENT`
        is pended with `pend_reason` `AUTH_SUSPENDED`" on suspend, and "exactly those
        claims pended with `AUTH_SUSPENDED` return to `APPROVED_FOR_PAYMENT`" on
        reinstatement.

        Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_utilization
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J3701", "drug_name": "UtilDrug2"},
            member_id="MEM-17B",
        )
        submit_claim(scenario, billed_units=10)
        auth_id = scenario["auth"]["id"]

        def afp_count():
            return len(list_claims_for_auth(auth_id, status="APPROVED_FOR_PAYMENT"))

        assert afp_count() == 1
        api.suspend_auth(auth_id, MPO)
        assert afp_count() == 0
        api.reinstate_auth(auth_id, MPO)
        assert afp_count() == 1


class TestBranchingForkJoin:
    def _branch_scenario(self):
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J2600", "drug_name": "BranchDrug"},
            member_id="MEM-5",
        )
        # Direct branch: 10 units = 100 mg == approved dose.
        direct = submit_claim(scenario, billed_units=10)
        # Pended branch: 11 units = 110 mg, within the inclusive 110% tolerance
        # (110 x 10 == 100 x 11).
        pended = submit_claim(scenario, billed_units=11)
        return scenario, direct, pended

    def test_direct_branch_and_tolerance_pended_branch(self, api):
        """PRD §3.6: "An overage within the inclusive ten-percent tolerance instead pends
        the claim with `pend_reason` `DOSE_REVIEW` — provisional pricing is computed and
        stored, but no administration is debited."
        PRD §3.6: "The override records the acting officer in `override_by` — null on
        claims that approved directly at adjudication".

        Design: Difficulty/non_linear_state_machine/claim_branching_fork_join
        """
        scenario, direct, pended = self._branch_scenario()
        assert direct["status"] == "APPROVED_FOR_PAYMENT"
        assert direct["override_by"] is None, "direct branch never records an override"
        assert pended["status"] == "PENDED"
        assert pended["pend_reason"] == "DOSE_REVIEW"
        # Provisional pricing stored even on the pended branch (11 x 500 x 1.06 = 5830).
        assert pended["allowed_amount_cents"] == 5830
        # Only the direct branch has debited so far.
        assert get_auth(scenario["auth"]["id"])["administrations_used"] == 1

    def test_override_approve_marks_officer_and_debits_once(self, api):
        """PRD §3.6: "The override records the acting officer in `override_by` ... returns
        the claim to `APPROVED_FOR_PAYMENT` at its adjudication-fixed price, since
        override deliberately does not re-price, and performs the same administration
        debit and possible exhaustion as the direct branch."

        Design: Difficulty/non_linear_state_machine/claim_branching_fork_join
        """
        scenario, direct, pended = self._branch_scenario()
        resolved = validate_success(
            api.override_approve_claim(pended["id"], make_mpo_headers("mpo-7"))
        )
        assert resolved["status"] == "APPROVED_FOR_PAYMENT"
        assert resolved["override_by"] == "mpo-7"
        assert resolved["allowed_amount_cents"] == 5830, "override does not re-price"
        # Each branch debited the authorization exactly once.
        assert get_auth(scenario["auth"]["id"])["administrations_used"] == 2


class TestExhaustionCascade:
    def test_claim_approval_debits_and_exhausts_auth(self, api):
        """PRD §3.6: "When `administered_mg` does not exceed `approved_dose_mg`, the claim
        lands `APPROVED_FOR_PAYMENT`: the authorization's `administrations_used` is
        incremented by one, and if that brings it to `max_administrations` the
        authorization immediately becomes `EXHAUSTED` (§3.4)."

        Design: Difficulty/transitive_cascade/claim_approval_exhausts_auth_cascade
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J2700", "drug_name": "ExhaustDrug"},
            member_id="MEM-7",
            max_administrations=1,
        )
        claim = submit_claim(scenario, billed_units=10)
        assert claim["status"] == "APPROVED_FOR_PAYMENT"
        auth = get_auth(scenario["auth"]["id"])
        assert auth["administrations_used"] == 1
        assert auth["status"] == "EXHAUSTED", "debit reaching the cap auto-exhausts"

    def test_exhausted_auth_rejects_further_claims(self, api):
        """PRD §3.4: "the authorization becomes `EXHAUSTED` — terminal, and further claims
        against it fail with `ERR_AUTH_NOT_APPROVED`, just as they would against any
        authorization that is not approved."

        Design: Difficulty/transitive_cascade/claim_approval_exhausts_auth_cascade
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J2701", "drug_name": "ExhaustDrug2"},
            member_id="MEM-7B",
            max_administrations=1,
        )
        submit_claim(scenario, billed_units=10)
        assert get_auth(scenario["auth"]["id"])["status"] == "EXHAUSTED"

        resp = api.create_claim(
            create_claim_payload(
                scenario["auth"]["id"], scenario["drug"]["id"], "J2701"
            ),
            scenario["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_APPROVED, 409)


class TestClaimStateGates:
    def test_override_approve_on_unpended_claim_rejected(self, api):
        """PRD §3.6: "Override approval requires the claim to be `PENDED` (otherwise
        `ERR_CLAIM_NOT_PENDED`)".

        Design: Corner/state_machines/claim_override_approve_not_pended_rejected
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J4600", "drug_name": "OvrDrug"},
            member_id="MEM-T3",
        )
        claim = submit_claim(scenario, billed_units=10)
        assert claim["status"] == "APPROVED_FOR_PAYMENT"

        resp = api.override_approve_claim(claim["id"], MPO)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PENDED, 409)
        assert get_claim(claim["id"])["status"] == "APPROVED_FOR_PAYMENT"
        assert get_auth(scenario["auth"]["id"])["administrations_used"] == 1

    def test_pay_pended_claim_rejected(self, api):
        """PRD §3.6: "Payment is a `PlanAdmin` act on an `APPROVED_FOR_PAYMENT` claim
        (otherwise `ERR_CLAIM_NOT_PAYABLE`)".
        PRD §2.10: ledger fields change only on payment or repricing, so the refused
        payment credits nothing.

        Design: Corner/state_machines/claim_pay_pended_rejected
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J4700", "drug_name": "PayDrug"},
            member_id="MEM-T4",
        )
        pended = submit_claim(scenario, billed_units=11)  # 110 mg: within tolerance
        assert pended["status"] == "PENDED"
        assert pended["pend_reason"] == "DOSE_REVIEW"

        resp = api.pay_claim(pended["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PAYABLE, 409)

        claim_after = get_claim(pended["id"])
        assert claim_after["status"] == "PENDED"
        assert claim_after["pend_reason"] == "DOSE_REVIEW"
        assert get_provider(scenario["provider"]["id"])["cumulative_paid_cents"] == 0


class TestAuthExpirySweep:
    def test_expiry_of_suspended_auth_denies_pended_claim(self, api):
        """PRD §3.4: "expiry from `SUSPENDED` additionally denies every claim still pended
        with `AUTH_SUSPENDED`, stamping `denial_reason` `AUTH_EXPIRED` on each."
        PRD §2.4: "Setting the clock eagerly applies every transition that has come due
        ... authorizations whose validity window has closed expire".

        Design: Corner/state_machines/auth_expiry_sweep_denies_suspended_pended_claim
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J5100", "drug_name": "ExpDrug"},
            member_id="MEM-T9",
        )
        claim = submit_claim(scenario, billed_units=10)
        api.suspend_auth(scenario["auth"]["id"], MPO)
        assert get_claim(claim["id"])["pend_reason"] == "AUTH_SUSPENDED"

        # validity window is [2026-08-01, 2027-01-28]; 2027-02-01 is past its end.
        set_clock("2027-02-01T00:00:00Z")

        auth = get_auth(scenario["auth"]["id"])
        assert auth["status"] == "EXPIRED"
        assert auth["administrations_used"] == 1
        claim_after = get_claim(claim["id"])
        assert claim_after["status"] == "DENIED"
        assert claim_after["denial_reason"] == "AUTH_EXPIRED"
