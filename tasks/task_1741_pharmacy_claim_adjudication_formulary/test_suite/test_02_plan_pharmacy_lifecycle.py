"""Plan lifecycle (activate/retire cascade) and pharmacy ledger/suspension lifecycle."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_plan, make_drug, make_formulary_entry, make_pharmacy, make_member,
    activate_plan, make_adjudication_scenario, make_pending_pa, get_pa,
    create_paid_claim, submit_claim, get_claim, get_pharmacy, get_member,
    make_suspended_pharmacy_scenario, make_pharmacist_headers, make_member_headers,
    api_client,
)


class TestPlanActivation:
    def test_plan_activate_twice_rejected(self, api, pbm_admin_headers):
        """PRD §3.1: "Activation moves it to `ACTIVE` and is permitted only from `DRAFT`
        — otherwise `ERR_PLAN_INVALID_STATE` — and only when at least one formulary
        entry already exists for the plan, otherwise `ERR_PLAN_NO_FORMULARY_ENTRIES`."

        Design: Corner/state_machines/plan_activate_twice_rejected
        """
        plan = make_plan(name="P-TWICE")
        drug = make_drug(ndc="00000-9010", name="Twicen", unit_cost_cents=100,
                         max_daily_dose_units=10)
        make_formulary_entry(plan["id"], drug["id"], tier=1, quantity_limit_per_fill=30,
                             max_days_supply=30, copay_type="FLAT", copay_flat_cents=100)
        activate_plan(plan["id"])

        res = api.activate_plan(plan["id"], pbm_admin_headers)
        validate_error(res, "ERR_PLAN_INVALID_STATE", expected_status=409)
        after = get_success_data(api.get_plan(plan["id"], pbm_admin_headers))
        assert after["status"] == "ACTIVE"
        assert after["version"] == 2, (
            f"Exactly one successful activation increments version once: {after['version']}"
        )

    def test_plan_activate_without_entries_rejected(self, api, pbm_admin_headers):
        """PRD §3.1: "Activation moves it to `ACTIVE` and is permitted only from `DRAFT`
        — otherwise `ERR_PLAN_INVALID_STATE` — and only when at least one formulary
        entry already exists for the plan, otherwise `ERR_PLAN_NO_FORMULARY_ENTRIES`."

        Design: Corner/state_machines/plan_activate_without_entries_rejected
        """
        plan = make_plan(name="P-EMPTY", assistance_model="MAXIMIZER",
                         card_fill_cap_cents=1000)
        res = api.activate_plan(plan["id"], pbm_admin_headers)
        validate_error(res, "ERR_PLAN_NO_FORMULARY_ENTRIES", expected_status=409)
        after = get_success_data(api.get_plan(plan["id"], pbm_admin_headers))
        assert after["status"] == "DRAFT"


class TestPlanRetireCascade:
    def _retire_scenario(self, api):
        plan = make_plan(name="P-RET")
        drug = make_drug(ndc="66666-0001", name="Retirin", therapeutic_class="ANTIVIRAL",
                         unit_cost_cents=2000, max_daily_dose_units=100)
        entry = make_formulary_entry(
            plan["id"], drug["id"], tier=2, quantity_limit_per_fill=90,
            max_days_supply=90, copay_type="FLAT", copay_flat_cents=500,
            pa_required=True, rebate_eligible=False,
        )
        activate_plan(plan["id"])
        member = make_member(plan["id"], external_ref="M-RET", full_name="Pat Ret")
        pa = make_pending_pa(member["id"], drug["id"], requested_quantity=60,
                             note="new therapy")
        return plan, drug, entry, member, pa

    def test_plan_retire_terminates_members_and_entries(self, api, pbm_admin_headers):
        """PRD §3.1: "When a plan is retired, every formulary entry belonging to it
        flips from `ACTIVE` to `INACTIVE`, and every member enrolled in it flips from
        `ACTIVE` to the terminal `TERMINATED` state."

        Design: Difficulty/transitive_cascade/plan_retire_member_pa_cascade
        """
        plan, drug, entry, member, pa = self._retire_scenario(api)
        res = api.retire_plan(plan["id"], pbm_admin_headers)
        retired = validate_success(res, 200)
        assert retired["status"] == "RETIRED"

        member_after = get_success_data(api.get_member(member["id"], pbm_admin_headers))
        assert member_after["status"] == "TERMINATED", (
            f"Retire cascade link 1: member must be TERMINATED, got {member_after['status']}"
        )
        entry_after = get_success_data(
            api.get_formulary_entry(entry["id"], pbm_admin_headers)
        )
        assert entry_after["status"] == "INACTIVE", (
            f"Retire cascade link 1: entry must be INACTIVE, got {entry_after['status']}"
        )

    def test_plan_retire_cancels_pending_pa(self, api, pbm_admin_headers):
        """PRD §3.1: "Each member termination then causes its own follow-on cascade —
        not issued by the retire call directly but by the termination itself: every
        prior authorization of the terminated member that stands in `PENDING` or
        `APPROVED` is moved to `CANCELLED`."

        Design: Difficulty/transitive_cascade/plan_retire_member_pa_cascade
        """
        plan, drug, entry, member, pa = self._retire_scenario(api)
        validate_success(api.retire_plan(plan["id"], pbm_admin_headers), 200)
        pa_after = get_success_data(api.get_prior_authorization(pa["id"], pbm_admin_headers))
        assert pa_after["status"] == "CANCELLED", (
            f"Retire cascade link 2: PENDING PA must be CANCELLED, got {pa_after['status']}"
        )


class TestPharmacyLedgerAndSuspension:
    def test_pharmacy_reinstate_when_active_rejected(self, api, pbm_admin_headers):
        """PRD §2.8: "a `PbmAdmin` reinstates a pharmacy only while it is `SUSPENDED`
        (otherwise `ERR_PHARMACY_NOT_SUSPENDED`, HTTP 409) and only once its balance
        has been restored to strictly above the negative threshold (otherwise
        `ERR_PHARMACY_DEBT_OUTSTANDING`, HTTP 409)."

        Design: Corner/state_machines/pharmacy_reinstate_when_active_rejected
        """
        pharmacy = make_pharmacy(ncpdp_id="NCPDP-ACT", name="Rx Active",
                                 channel="MAIL_ORDER", auto_suspend_threshold_cents=5000)
        res = api.reinstate_pharmacy(pharmacy["id"], pbm_admin_headers)
        validate_error(res, "ERR_PHARMACY_NOT_SUSPENDED", expected_status=409)
        after = get_success_data(api.get_pharmacy(pharmacy["id"], pbm_admin_headers))
        assert after["status"] == "ACTIVE"

    def test_pharmacy_suspend_at_exact_threshold(self, api):
        """PRD §2.8: "If the mutation leaves `balance_cents` at or below the negation of
        that threshold — the boundary is inclusive, so a balance exactly equal to the
        negative threshold suspends — the pharmacy's `status` automatically transitions
        from `ACTIVE` to `SUSPENDED` without any explicit client call."

        Design: Corner/state_machines/pharmacy_suspend_at_exact_threshold
        """
        scenario = make_suspended_pharmacy_scenario(clawback_cents=15000)
        pharmacy = scenario["pharmacy"]
        assert pharmacy["balance_cents"] == -5000, (
            f"10000 plan-paid minus 15000 clawback must land at -5000, "
            f"got {pharmacy['balance_cents']}"
        )
        assert pharmacy["status"] == "SUSPENDED", (
            "Balance exactly equal to the negative threshold must suspend (inclusive <=)"
        )

    def test_reversal_restores_pharmacy_balance(self, api, pbm_admin_headers):
        """PRD §2.8: "when one of the pharmacy's claims is adjudicated `PAID`, the
        claim's `plan_paid_cents` is added to the balance; when a claim is reversed,
        that same claim's `plan_paid_cents` is subtracted"

        Design: Corner/state_machines/reversal_restores_pharmacy_balance
        """
        scenario = make_adjudication_scenario(
            drug_overrides={"ndc": "00000-9013", "unit_cost_cents": 1000,
                            "max_daily_dose_units": 100},
            entry_overrides={"copay_flat_cents": 0},
        )
        member, drug, pharmacy = (
            scenario["member"], scenario["drug"], scenario["pharmacy"],
        )
        claim = create_paid_claim(member["id"], drug["id"], pharmacy["id"])
        assert claim["plan_paid_cents"] == 10000
        mid = get_pharmacy(pharmacy["id"])
        assert mid["balance_cents"] == 10000

        validate_success(
            api.reverse_claim(
                claim["id"], {"reversal_reason": "wrong drug"},
                scenario["pharmacist_headers"],
            ),
            200,
        )
        after = get_success_data(api.get_pharmacy(pharmacy["id"], pbm_admin_headers))
        assert after["balance_cents"] == 0, (
            f"Reversal must debit exactly plan_paid_cents: balance {after['balance_cents']} != 0"
        )

    def test_reinstate_blocked_while_debt_outstanding(self, api, pbm_admin_headers):
        """PRD §2.8: "a `PbmAdmin` reinstates a pharmacy only while it is `SUSPENDED`
        (otherwise `ERR_PHARMACY_NOT_SUSPENDED`, HTTP 409) and only once its balance
        has been restored to strictly above the negative threshold (otherwise
        `ERR_PHARMACY_DEBT_OUTSTANDING`, HTTP 409)."

        Design: Corner/cross_cutting_layers/reinstate_blocked_while_debt_outstanding
        """
        scenario = make_suspended_pharmacy_scenario(clawback_cents=16000)
        pharmacy = scenario["pharmacy"]
        assert pharmacy["balance_cents"] == -6000
        assert pharmacy["status"] == "SUSPENDED"

        res = api.reinstate_pharmacy(pharmacy["id"], pbm_admin_headers)
        validate_error(res, "ERR_PHARMACY_DEBT_OUTSTANDING", expected_status=409)

        validate_success(
            api.create_balance_adjustment(
                pharmacy["id"], {"amount_cents": 20000, "reason": "settlement check"},
                pbm_admin_headers,
            ),
            200,
        )
        restored = get_pharmacy(pharmacy["id"])
        assert restored["balance_cents"] == 14000

        reinstated = validate_success(
            api.reinstate_pharmacy(pharmacy["id"], pbm_admin_headers), 200
        )
        assert reinstated["status"] == "ACTIVE"


class TestClaimGatedOnPharmacyStatus:
    def test_claim_blocked_while_pharmacy_suspended(self, api):
        """PRD §2.8: "A `SUSPENDED` pharmacy cannot perform any claim write (submission,
        resubmission, reversal, or reprocessing); such attempts are rejected with
        `ERR_PHARMACY_SUSPENDED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/claim_blocked_by_pharmacy_suspension_until_reinstated
        """
        scenario = make_suspended_pharmacy_scenario(clawback_cents=16000)
        assert scenario["pharmacy"]["status"] == "SUSPENDED"

        res = submit_claim(
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
            fill_date="2026-06-01",
        )
        validate_error(res, "ERR_PHARMACY_SUSPENDED", expected_status=409)

    def test_claim_pays_after_settlement_and_reinstate(self, api, pbm_admin_headers):
        """PRD §2.8: "Reinstatement is a deliberate administrative act: a `PbmAdmin`
        reinstates a pharmacy only while it is `SUSPENDED` (otherwise
        `ERR_PHARMACY_NOT_SUSPENDED`, HTTP 409) and only once its balance has been
        restored to strictly above the negative threshold (otherwise
        `ERR_PHARMACY_DEBT_OUTSTANDING`, HTTP 409). Reinstatement returns the pharmacy
        to `ACTIVE` and increments its `version`."

        Design: Difficulty/cross_entity_state_dependency/claim_blocked_by_pharmacy_suspension_until_reinstated
        """
        scenario = make_suspended_pharmacy_scenario(clawback_cents=16000)
        pharmacy_id = scenario["pharmacy"]["id"]

        validate_success(
            api.create_balance_adjustment(
                pharmacy_id, {"amount_cents": 20000, "reason": "clawback settlement"},
                pbm_admin_headers,
            ),
            200,
        )
        assert get_pharmacy(pharmacy_id)["balance_cents"] == 14000
        validate_success(api.reinstate_pharmacy(pharmacy_id, pbm_admin_headers), 200)
        assert get_pharmacy(pharmacy_id)["status"] == "ACTIVE"

        claim = validate_success(
            submit_claim(
                scenario["member"]["id"], scenario["drug"]["id"], pharmacy_id,
                prescription_number="RX-V2", fill_date="2026-06-01",
            ),
            201,
        )
        assert claim["status"] == "PAID"
        assert claim["plan_paid_cents"] == 10000
        assert get_pharmacy(pharmacy_id)["balance_cents"] == 24000


class TestSuspendedPharmacyPriority:
    def test_suspended_pharmacy_state_error_beats_days_supply_edit(self, api):
        """PRD §2.6: "Every request is screened against a fixed pipeline, and a request
        failing at any stage is rejected with that stage's error — later stages are
        never consulted for that request."
        PRD §2.6: "Only after all ten general stages pass do claim-adjudication requests
        enter the eleven pinned adjudication edits described in §3.4"

        Design: Difficulty/priority_pair_validation_conflict/suspended_pharmacy_vs_days_supply_conflict
        """
        scenario = make_suspended_pharmacy_scenario(clawback_cents=16000)
        assert scenario["pharmacy"]["status"] == "SUSPENDED"

        # days_supply 999 would fail adjudication edit 10 (max_days_supply 90), but the
        # stage-5 state precondition runs first and the adjudication edits never run.
        res = submit_claim(
            scenario["member"]["id"], scenario["drug"]["id"],
            scenario["pharmacy"]["id"], fill_date="2026-06-01", days_supply=999,
        )
        validate_error(res, "ERR_PHARMACY_SUSPENDED", expected_status=409)

    def test_suspended_pharmacy_rejection_persists_no_claim(self, api, pbm_admin_headers):
        """PRD §2.6: "Every request is screened against a fixed pipeline, and a request
        failing at any stage is rejected with that stage's error — later stages are
        never consulted for that request."
        PRD §3.4: "When any edit fails, the claim is still persisted — now with `status`
        `REJECTED`" (only adjudication-edit failures persist a claim).

        Design: Difficulty/priority_pair_validation_conflict/suspended_pharmacy_vs_days_supply_conflict
        """
        scenario = make_suspended_pharmacy_scenario(clawback_cents=16000)
        pharmacy_id = scenario["pharmacy"]["id"]

        res = submit_claim(
            scenario["member"]["id"], scenario["drug"]["id"], pharmacy_id,
            fill_date="2026-06-01", days_supply=999,
        )
        validate_error(res, "ERR_PHARMACY_SUSPENDED", expected_status=409)

        data, meta = validate_paginated(
            api.list_claims(
                pbm_admin_headers,
                params={"pharmacy_id": pharmacy_id, "status": "REJECTED"},
            )
        )
        assert meta["total_count"] == 0, (
            f"A stage-5 rejection never reaches adjudication, so no REJECTED claim may "
            f"be persisted; got total_count {meta['total_count']}"
        )
