"""Damage claims: hold cycle, appeal loop, segregation of duties, liability
assessment ladder, settlement cascade into the prepaid ledger, and terminal
lockdown (PRD §3.8, §3.6, §2.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assess_claim,
    create_assessed_claim,
    create_dried_lot,
    create_filed_claim,
    create_issued_invoice,
    deny_claim,
    get_customer,
    get_invoice,
    get_lot,
    make_adjuster_headers,
    make_grower_headers,
    make_technician_headers,
    review_claim,
    setup_base,
    setup_dried_lot_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def _dried_ctx(**kwargs):
    defaults = dict(with_schedule=True, sample_moisture_pct=22.5,
                    foreign_material_pct=2.0, meter_start=1200.0, meter_end=1265.0,
                    scale_out=9050, discharge=15.0)
    defaults.update(kwargs)
    return setup_dried_lot_scenario(**defaults)


class TestDamageHoldCycle:
    def test_filing_puts_lot_on_damage_hold(self, api, manager_headers):
        """PRD §3.8: "A successful filing records the filer in
        `filed_by_user_id` — equal to the lot's `current_owner_id` at filing —
        and moves the lot `DRIED` → `DAMAGE_HOLD`, its version incrementing."

        Design: Difficulty/non_linear_state_machine/grain_lot_damage_hold_cycle
        """
        ctx = _dried_ctx()
        claim = create_filed_claim(ctx["lot"], ctx["run"], claimed_amount_cents=20000)
        assert claim["status"] == "FILED"
        assert claim["filed_by_user_id"] == ctx["cust"]["id"]
        assert get_lot(ctx["lot"]["id"])["status"] == "DAMAGE_HOLD"

    def test_denial_releases_lot_back_to_dried(self, api, manager_headers):
        """PRD §3.8: "Three exits release the hold. Denial by an adjuster other
        than the filer moves `UNDER_REVIEW` → `DENIED` and returns the lot
        `DAMAGE_HOLD` → `DRIED`"

        Design: Difficulty/non_linear_state_machine/grain_lot_damage_hold_cycle
        """
        ctx = _dried_ctx()
        claim = create_filed_claim(ctx["lot"], ctx["run"], claimed_amount_cents=20000)
        review_claim(claim["id"], adj_id="adj-1")
        denied = deny_claim(claim["id"], adj_id="adj-1")
        assert denied["status"] == "DENIED"
        assert get_lot(ctx["lot"]["id"])["status"] == "DRIED"


class TestAppealCycle:
    def _denied_claim(self):
        ctx = _dried_ctx()
        claim = create_filed_claim(ctx["lot"], ctx["run"], claimed_amount_cents=20000,
                                   damage_type="STRESS_CRACKING")
        review_claim(claim["id"], adj_id="adj-1")
        deny_claim(claim["id"], adj_id="adj-1")
        return ctx, claim

    def test_appeal_reenters_review(self, api, manager_headers):
        """PRD §3.8: "the filer may then appeal, `DENIED` → `APPEALED`, an
        action open only to the operator in `filed_by_user_id`, and an appealed
        claim returns to `UNDER_REVIEW` through a fresh review — again by an
        adjuster other than the filer."

        Design: Difficulty/non_linear_state_machine/damage_claim_appeal_cycle
        """
        ctx, claim = self._denied_claim()
        appealed = validate_success(api.appeal_damage_claim(
            claim["id"], make_grower_headers(ctx["cust"]["id"])), 200)
        assert appealed["status"] == "APPEALED"
        back = validate_success(api.review_damage_claim(
            claim["id"], make_adjuster_headers("adj-2")), 200)
        assert back["status"] == "UNDER_REVIEW"

    def test_appeal_does_not_rehold_lot(self, api, manager_headers):
        """PRD §3.8: "Denial by an adjuster other than the filer moves
        `UNDER_REVIEW` → `DENIED` and returns the lot `DAMAGE_HOLD` → `DRIED`"
        PRD §3.8: "on the appeal path the lot was already released at denial, so
        nothing further moves."

        Design: Difficulty/non_linear_state_machine/damage_claim_appeal_cycle
        """
        ctx, claim = self._denied_claim()
        api.appeal_damage_claim(claim["id"], make_grower_headers(ctx["cust"]["id"]))
        api.review_damage_claim(claim["id"], make_adjuster_headers("adj-2"))
        # The lot stayed DRIED through appeal and re-review — no re-hold.
        assert get_lot(ctx["lot"]["id"])["status"] == "DRIED"


class TestClaimSettlementCascade:
    def _assessed_with_invoice(self):
        # fm 4.2 -> drying 7366; metered 65 therms -> energy 5575; total 12941.
        ctx = _dried_ctx(foreign_material_pct=4.2, discharge=15.9)
        invoice = create_issued_invoice(ctx["cust"]["id"], ctx["sched"])
        claim = create_assessed_claim(ctx["lot"], ctx["run"],
                                      claimed_amount_cents=20000, adj_id="adj-1")
        return ctx, invoice, claim

    def test_claim_pay_credits_prepaid_and_releases_lot(self, api, manager_headers):
        """PRD §3.8: "Payment, an `ElevatorManager` action on an `ASSESSED`
        claim, is a three-link settlement cascade. First, the customer's
        `prepaid_balance_cents` grows by `assessed_liability_cents`."
        PRD §3.8: "If the lot is still on hold, payment releases it
        `DAMAGE_HOLD` → `DRIED`; on the appeal path the lot was already released
        at denial, so nothing further moves. `PAID` is terminal for the claim."

        Design: Difficulty/transitive_cascade/claim_pay_prepaid_waterfall_cascade
        """
        ctx, invoice, claim = self._assessed_with_invoice()
        # |15.9 - 15.0| = 0.9 > 0.5 -> x1.5: min(29090, 17500*1.5) = 26250
        assert claim["assessed_liability_cents"] == 26250
        paid = validate_success(
            api.pay_damage_claim(claim["id"], manager_headers), 200)
        assert paid["status"] == "PAID"
        # 26250 credited, 12941 auto-applied to the ISSUED invoice -> 13309 left
        assert get_customer(ctx["cust"]["id"])["prepaid_balance_cents"] == 13309
        assert get_lot(ctx["lot"]["id"])["status"] == "DRIED"

    def test_claim_pay_waterfall_auto_pays_oldest_invoice(self, api, manager_headers):
        """PRD §3.8: "Second, that prepaid increase auto-applies as a waterfall
        across the customer's ISSUED invoices, oldest `issued_at` first with
        ties broken by `created_at`: each invoice in turn absorbs the lesser of
        the remaining prepaid balance and its own `amount_due_cents`, and the
        walk stops when the prepaid credit is exhausted or no ISSUED invoice
        remains. Third, every invoice whose due reaches zero in the waterfall
        moves `ISSUED` → `PAID`."

        Design: Difficulty/transitive_cascade/claim_pay_prepaid_waterfall_cascade
        """
        ctx, invoice, claim = self._assessed_with_invoice()
        api.pay_damage_claim(claim["id"], manager_headers)
        after = get_invoice(invoice["id"])
        assert after["total_cents"] == 12941
        assert after["amount_due_cents"] == 0
        assert after["status"] == "PAID"


class TestHoldAndLoadOut:
    def test_loadout_blocked_during_damage_hold(self, api, technician_headers):
        """PRD §3.6: "A lot on `DAMAGE_HOLD` is refused with
        `ERR_LOT_ON_DAMAGE_HOLD`, and other ineligible states fail the state
        gate."
        PRD §3.8: "While the hold stands, the lot cannot load out, book or
        confirm dryer time, or participate in a blend; those operations are
        rejected with `ERR_LOT_ON_DAMAGE_HOLD`."

        Design: Corner/state_machines/loadout_blocked_during_damage_hold
        """
        ctx = _dried_ctx()
        create_filed_claim(ctx["lot"], ctx["run"], claimed_amount_cents=3000,
                           damage_type="MOLD_CONTAMINATION")
        res = api.load_out_lot(ctx["lot"]["id"], technician_headers)
        validate_error(res, ApiErrorId.ERR_LOT_ON_DAMAGE_HOLD, expected_status=409)
        assert get_lot(ctx["lot"]["id"])["status"] == "DAMAGE_HOLD"

    def test_lot_loadout_then_terminal_lockdown(self, api, technician_headers):
        """PRD §3.6: "A lot may load out only from `DRIED` with no `RESERVED` or
        `ACTIVE` agreement attached; success moves it `DRIED` → `LOADED_OUT`,
        terminal, its version incrementing."
        PRD §2.5: "Once a resource reaches a terminal state, further transition
        attempts on it are rejected with `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/lot_loadout_then_terminal_lockdown
        """
        ctx = _dried_ctx()
        loaded = validate_success(
            api.load_out_lot(ctx["lot"]["id"], technician_headers), 200)
        assert loaded["status"] == "LOADED_OUT"
        res = api.load_out_lot(ctx["lot"]["id"], technician_headers)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)


class TestClaimFilingGates:
    def test_claim_after_delivery_rejected(self, api, manager_headers, technician_headers):
        """PRD §3.8: "Filing is gated by the lot's state with a deliberate split
        in the error mapping: a lot already `LOADED_OUT` or `BLENDED_OUT` is
        past the point of claims and is rejected with
        `ERR_CLAIM_AFTER_DELIVERY` (HTTP 422), while a lot on `DAMAGE_HOLD` or
        in any pre-drying state fails the ordinary state gate with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/claim_after_delivery_rejected
        """
        ctx = _dried_ctx()
        validate_success(api.load_out_lot(ctx["lot"]["id"], technician_headers), 200)
        res = api.create_damage_claim(
            {"lot_id": ctx["lot"]["id"], "dryer_run_id": ctx["run"]["id"],
             "damage_type": "EXCESS_SHRINK", "claimed_amount_cents": 3000},
            make_grower_headers(ctx["cust"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CLAIM_AFTER_DELIVERY, expected_status=422)
        assert get_lot(ctx["lot"]["id"])["status"] == "LOADED_OUT"
        claims, meta = validate_paginated(api.list_damage_claims(
            manager_headers, params={"lot_id": ctx["lot"]["id"]}))
        assert meta["total_count"] == 0

    def test_claim_run_mismatch_rejected(self, api, manager_headers):
        """PRD §3.8: "The named run must actually reference the claimed lot, or
        `ERR_CLAIM_RUN_MISMATCH` (HTTP 422)."

        Design: Corner/validations/claim_run_mismatch_rejected
        """
        ctx = setup_base()
        dried_a = create_dried_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], sample_moisture_pct=20.0,
            run_start="2026-09-05T08:00:00Z", run_end="2026-09-05T10:00:00Z",
            meter_start=100.0, meter_end=160.0)
        dried_b = create_dried_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], sample_moisture_pct=20.0,
            run_start="2026-09-05T11:00:00Z", run_end="2026-09-05T13:00:00Z",
            meter_start=100.0, meter_end=160.0)
        # Claim names lot A but lot B's run.
        res = api.create_damage_claim(
            {"lot_id": dried_a["lot"]["id"], "dryer_run_id": dried_b["run"]["id"],
             "damage_type": "HEAT_DAMAGE", "claimed_amount_cents": 3000},
            make_grower_headers(ctx["cust"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CLAIM_RUN_MISMATCH, expected_status=422)
        assert get_lot(dried_a["lot"]["id"])["status"] == "DRIED"


class TestClaimSegregation:
    def test_claim_assess_by_run_operator_sod_violation(self, api, manager_headers):
        """PRD §3.8: "Assessment, again by a `ClaimsAdjuster`, requires the
        claim `UNDER_REVIEW` and the referenced run `COMPLETED` (else
        `ERR_INVALID_STATE`), and the assessor must differ from both the filer
        and the run's `operator_user_id` — the operator who ran the dryer never
        prices their own alleged damage (`ERR_CLAIM_SO_DUTY_VIOLATION`)."

        Design: Corner/validations/claim_assess_by_run_operator_sod_violation
        """
        ctx = _dried_ctx()
        claim = create_filed_claim(ctx["lot"], ctx["run"], claimed_amount_cents=3000)
        review_claim(claim["id"], adj_id="adj-1")
        # The run's operator_user_id is op-1 — that person cannot assess.
        res = api.assess_damage_claim(claim["id"], make_adjuster_headers("op-1"))
        validate_error(res, ApiErrorId.ERR_CLAIM_SO_DUTY_VIOLATION,
                       expected_status=403)
        # An independent adjuster assesses successfully.
        assessed = validate_success(
            api.assess_damage_claim(claim["id"], make_adjuster_headers("adj-1")), 200)
        assert assessed["status"] == "ASSESSED"


class TestLiabilityAssessment:
    def test_liability_preexisting_condition_quarter_multiplier(self, api, manager_headers):
        """PRD §3.8: "Second, `fault_multiplier`, a ladder evaluated in this
        pinned order: 0.25 when the loss is attributable to a pre-existing
        condition — the lot's intake moisture above 26.0 percent or its foreign
        material above 8.0 percent; otherwise 1.5 when the run finished out of
        specification — the absolute gap between the run's
        `discharge_moisture_pct` and the lot's `target_moisture_pct` exceeding
        half a percentage point; otherwise 1.0 for an in-spec run."
        PRD §3.8: "Third, `assessed_liability_cents`: take `claimed_amount_cents`
        less a deductible of 2500 cents, floored at zero, multiply by the fault
        multiplier, and round half up to whole cents; separately compute the
        liability cap as forty percent of `lot_value_cents`, rounded half up to
        whole cents; the assessment is the lesser of the two rounded figures."

        Design: Corner/calculations/liability_preexisting_condition_quarter_multiplier
        """
        # fm 8.5 > 8.0 forces 0.25 even though the run finished in-spec (15.0).
        ctx = _dried_ctx(foreign_material_pct=8.5, discharge=15.0)
        claim = create_filed_claim(ctx["lot"], ctx["run"], claimed_amount_cents=20000,
                                   damage_type="MOLD_CONTAMINATION")
        review_claim(claim["id"], adj_id="adj-1")
        assessed = assess_claim(claim["id"], adj_id="adj-1")
        assert assessed["fault_multiplier"] == pytest.approx(0.25)
        # 161.61 bu * 450 = 72724.5 -> 72725
        assert assessed["lot_value_cents"] == 72725
        # min(cap 29090, (20000-2500)*0.25 = 4375) = 4375
        assert assessed["assessed_liability_cents"] == 4375

    def test_liability_in_spec_standard_multiplier(self, api, manager_headers):
        """PRD §3.8: "otherwise 1.5 when the run finished out of specification —
        the absolute gap between the run's `discharge_moisture_pct` and the
        lot's `target_moisture_pct` exceeding half a percentage point; otherwise
        1.0 for an in-spec run."

        Design: Corner/calculations/liability_in_spec_standard_multiplier
        """
        # |15.4 - 15.0| = 0.4 <= 0.5 -> in-spec, multiplier 1.0.
        ctx = _dried_ctx(foreign_material_pct=2.0, discharge=15.4)
        claim = create_filed_claim(ctx["lot"], ctx["run"], claimed_amount_cents=20000,
                                   damage_type="STRESS_CRACKING")
        review_claim(claim["id"], adj_id="adj-1")
        assessed = assess_claim(claim["id"], adj_id="adj-1")
        assert assessed["fault_multiplier"] == pytest.approx(1.0)
        # min(cap 29090, (20000-2500)*1.0) = 17500
        assert assessed["assessed_liability_cents"] == 17500
        assert assessed["status"] == "ASSESSED"


class TestPaidClaimTerminal:
    def test_claim_pay_twice_rejected(self, api, manager_headers):
        """PRD §3.8: "`PAID` is terminal for the claim."
        PRD §2.5: "Once a resource reaches a terminal state, further transition
        attempts on it are rejected with `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/claim_pay_twice_rejected
        """
        ctx = _dried_ctx(foreign_material_pct=2.0, discharge=15.4)
        claim = create_assessed_claim(ctx["lot"], ctx["run"],
                                      claimed_amount_cents=20000, adj_id="adj-1")
        # in-spec x1.0 -> 17500; no ISSUED invoices to absorb the credit
        paid = validate_success(api.pay_damage_claim(claim["id"], manager_headers), 200)
        assert paid["status"] == "PAID"
        assert get_customer(ctx["cust"]["id"])["prepaid_balance_cents"] == 17500

        res = api.pay_damage_claim(claim["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)
        # No double credit on the prepaid ledger.
        assert get_customer(ctx["cust"]["id"])["prepaid_balance_cents"] == 17500
