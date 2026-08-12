"""Preference/fraudulent-transfer recovery: lookback windows, judgment,
rescission, settlement claim-swap."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_avoidance_action_payload,
    create_creditor, get_case, set_clock, create_demanded_action,
    create_judgment_action, setup_case_in_claims_administration,
    setup_case_in_liquidation, propose_plan, confirm_plan,
)

TRUSTEE = TEST_USERS["trustee_headers"]
CLERK = TEST_USERS["clerk_headers"]
COURT = TEST_USERS["court_headers"]

FILED_ON = "2026-01-15T00:00:00Z"


def _register_action(case_id, cred_id, transfer_date, transfer=100000,
                     demand=100000, action_type="PREFERENCE_547"):
    return api_client.create_avoidance_action(
        case_id,
        create_avoidance_action_payload(
            transferee_creditor_id=cred_id, transfer_date=transfer_date,
            transfer_amount_cents=transfer, action_type=action_type,
            demand_amount_cents=demand),
        TRUSTEE)


class TestLookbackWindowEdge:
    def test_transfer_exactly_at_window_edge_is_avoidable(self, api):
        """PRD §3.5: "The `avoidable` flag is true exactly when the
        `transfer_date` falls on or after the petition date minus the lookback
        window and strictly before the petition date itself: a transfer dated
        precisely at the earliest window boundary is avoidable, while a
        transfer dated precisely on `filed_on` is post-petition and not
        avoidable."

        Petition 2026-01-15, non-insider preference window 90 days: the
        earliest avoidable date is 2025-10-17.

        Design: Difficulty/boundary_precision_check/avoidance_lookback_exact_window_edge
        """
        ctx = setup_case_in_claims_administration(case_number="26-10012")
        cred = create_creditor(creditor_ref="CR-K-1", insider=False)
        resp = _register_action(ctx["case"]["id"], cred["id"], "2025-10-17T00:00:00Z")
        action = validate_success(resp, expected_status=201)
        assert action["avoidable"] is True
        assert action["lookback_window_days"] == 90
        analyzed = validate_success(api.analyze_action(action["id"], TRUSTEE))
        assert analyzed["status"] == "ANALYZED"

    def test_transfer_one_day_outside_window_rejected_at_analyze(self, api):
        """PRD §3.5: "Analysis gates the action on avoidability: moving from
        `IDENTIFIED` to `ANALYZED` requires `avoidable` to be true, and an
        action whose transfer falls outside its lookback window is rejected
        with `ERR_TRANSFER_NOT_AVOIDABLE`."

        One day before the 90-day edge (2025-10-16) is outside the window.

        Design: Difficulty/boundary_precision_check/avoidance_lookback_exact_window_edge
        """
        ctx = setup_case_in_claims_administration(case_number="26-10012")
        cred = create_creditor(creditor_ref="CR-K-1", insider=False)
        action = validate_success(
            _register_action(ctx["case"]["id"], cred["id"], "2025-10-16T00:00:00Z"),
            expected_status=201)
        assert action["avoidable"] is False
        resp = api.analyze_action(action["id"], TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_NOT_AVOIDABLE)


class TestJudgmentRescindCycle:
    def _judgment_ctx(self, case_number, demand=300000):
        ctx = setup_case_in_claims_administration(case_number=case_number)
        cred = create_creditor(creditor_ref="CR-F-1", insider=False)
        action = create_judgment_action(
            ctx["case"]["id"], cred["id"], transfer_amount_cents=demand,
            demand_amount_cents=demand)
        return ctx, cred, action

    def test_judgment_posts_recovery_and_credits_estate_cash(self, api):
        """PRD §3.5: "When the `Court` instead enters judgment on a `DEMANDED`
        action, a recovery deposit for the full `demand_amount_cents` posts
        atomically, `recovered_amount_cents` becomes the demanded amount, and
        the estate cash increases by the demanded amount."

        Design: Difficulty/non_linear_state_machine/avoidance_action_judgment_rescind_cycle_restores_cash
        """
        ctx, cred, action = self._judgment_ctx("26-10006", demand=300000)
        assert action["status"] == "JUDGMENT"
        assert action["recovered_amount_cents"] == 300000
        case = get_case(ctx["case"]["id"])
        assert case["estate_cash_on_hand_cents"] == 300000

    def test_rescind_voids_deposit_and_restores_ledger(self, api):
        """PRD §3.5: "Rescinding flips the linked recovery deposit to `VOIDED`,
        zeroes the action's `recovered_amount_cents`, and debits
        `estate_cash_on_hand_cents` by the formerly recovered
        `demand_amount_cents`, preserving the invariant that cash always equals
        receipts minus disbursements; the case `version` increments."

        Design: Difficulty/non_linear_state_machine/avoidance_action_judgment_rescind_cycle_restores_cash
        """
        ctx, cred, action = self._judgment_ctx("26-10006", demand=300000)
        case_id = ctx["case"]["id"]
        assert get_case(case_id)["estate_cash_on_hand_cents"] == 300000

        rescinded = validate_success(api.rescind_action(action["id"], COURT))
        assert rescinded["status"] == "RESCINDED"
        assert rescinded["recovered_amount_cents"] == 0
        assert get_case(case_id)["estate_cash_on_hand_cents"] == 0, \
            "the compensating entry restores the ledger exactly"

    def test_judgment_rescind_preserves_estate_cash_identity(self, api):
        """PRD §2.7: "The first, `estate_cash_on_hand_cents`, always equals the
        sum of `net_proceeds_cents` over auction sales whose `proceeds_status`
        is `POSTED`, plus the sum of `amount_cents` over recovery deposits
        whose `status` is `POSTED`, minus the sum of `amount_cents` over
        dividends whose `status` is `POSTED`, minus the sum of
        `approved_amount_cents` over fee applications whose `status` is `PAID`."

        Design: Difficulty/compensating_invariant/judgment_rescind_preserves_estate_cash_identity
        """
        ctx = setup_case_in_claims_administration(case_number="26-10017")
        cred = create_creditor(creditor_ref="CR-P-1", insider=True)
        action = create_demanded_action(
            ctx["case"]["id"], cred["id"], transfer_date="2025-08-01T00:00:00Z",
            transfer_amount_cents=250000, demand_amount_cents=250000)
        case_id = ctx["case"]["id"]
        cash_before = get_case(case_id)["estate_cash_on_hand_cents"]
        assert cash_before == 0

        validate_success(api.enter_judgment(action["id"], COURT))
        assert get_case(case_id)["estate_cash_on_hand_cents"] == 250000

        validate_success(api.rescind_action(action["id"], COURT))
        cash_after = get_case(case_id)["estate_cash_on_hand_cents"]
        assert cash_after == cash_before, \
            "forward judgment plus compensating rescind leaves zero drift"

    def test_rescind_flips_recovery_deposit_to_voided(self, api):
        """PRD §3.5: "Rescinding flips the linked recovery deposit to `VOIDED`,
        zeroes the action's `recovered_amount_cents`, and debits
        `estate_cash_on_hand_cents` by the formerly recovered
        `demand_amount_cents`, preserving the invariant that cash always equals
        receipts minus disbursements; the case `version` increments."
        PRD §3.5: "Recovery deposits themselves are simple ledger rows: each
        carries the `avoidance_action_id` it credits, an `amount_cents`, and a
        `status` of `POSTED` or `VOIDED`."

        Design: Difficulty/compensating_invariant/judgment_rescind_preserves_estate_cash_identity
        """
        ctx = setup_case_in_claims_administration(case_number="26-10017")
        cred = create_creditor(creditor_ref="CR-P-1", insider=True)
        action = create_demanded_action(
            ctx["case"]["id"], cred["id"], transfer_date="2025-08-01T00:00:00Z",
            transfer_amount_cents=250000, demand_amount_cents=250000)
        validate_success(api.enter_judgment(action["id"], COURT))

        resp = api.list_action_recovery_deposits(action["id"], TRUSTEE)
        deposits = resp.json()["data"]
        assert len(deposits) == 1
        assert deposits[0]["status"] == "POSTED"
        assert deposits[0]["amount_cents"] == 250000

        validate_success(api.rescind_action(action["id"], COURT))
        deposits = api.list_action_recovery_deposits(action["id"], TRUSTEE).json()["data"]
        assert deposits[0]["status"] == "VOIDED"


class TestDemandAmountValidation:
    def test_demand_amount_above_transfer_rejected(self, api):
        """PRD §3.5: "Demanding payment moves the action from `ANALYZED` to
        `DEMANDED` and validates the recorded `demand_amount_cents`: it must be
        strictly greater than zero and no greater than `transfer_amount_cents`
        — anything outside that band is rejected with
        `ERR_INVALID_DEMAND_AMOUNT` (HTTP 422)."

        The PRD names the band and the error; a registration carrying an
        out-of-band demand must surface `ERR_INVALID_DEMAND_AMOUNT` no later
        than the demand transition.

        Design: Corner/validations/invalid_demand_amount_rejected
        """
        ctx = setup_case_in_claims_administration(case_number="26-20025")
        cred_id = ctx["creditor"]["id"]
        resp = _register_action(ctx["case"]["id"], cred_id,
                                "2025-12-01T00:00:00Z", transfer=100000,
                                demand=100001)
        if resp.status_code >= 400:
            validate_error(resp, ApiErrorId.ERR_INVALID_DEMAND_AMOUNT)
            return
        action = validate_success(resp, expected_status=201)
        get_success_data(api.analyze_action(action["id"], TRUSTEE))
        resp_demand = api.demand_action(action["id"], TRUSTEE)
        validate_error(resp_demand, ApiErrorId.ERR_INVALID_DEMAND_AMOUNT)


class TestRescindGate:
    def test_rescind_blocked_once_plan_confirmed(self, api):
        """PRD §3.5: "The `Court` may rescind a `JUDGMENT` action only while
        the case is not in `DISTRIBUTION` and no plan of the case is
        `CONFIRMED` or `EXECUTING` — otherwise the distribution machinery is
        relying on the recovery and rescission is rejected with
        `ERR_PLAN_RELIES_ON_RECOVERY`."

        Design: Corner/errors/error_plan_relies_on_recovery_triggered
        """
        # Case with an allowed claim, a posted judgment recovery (cash
        # 100,000), the scheduled asset abandoned, then driven to DISTRIBUTION
        # with a CONFIRMED plan relying on that cash.
        ctx = setup_case_in_liquidation(case_number="26-20040",
                                        objection_window_days=1,
                                        claim_amount_cents=50000)
        case_id = ctx["case"]["id"]
        cred_id = ctx["creditor"]["id"]
        action = create_judgment_action(case_id, cred_id,
                                        transfer_amount_cents=100000,
                                        demand_amount_cents=100000)
        get_success_data(api.abandon_asset(ctx["asset"]["id"], TRUSTEE))
        get_success_data(api.begin_distribution(case_id, TRUSTEE))
        plan = propose_plan(case_id)
        confirm_plan(plan["id"], case_id)

        resp = api.rescind_action(action["id"], COURT)
        validate_error(resp, ApiErrorId.ERR_PLAN_RELIES_ON_RECOVERY)


class TestSettleAtomicity:
    def test_settle_atomicity_recovery_and_compensating_claim(self, api):
        """PRD §3.5: "When the trustee settles a `DEMANDED` action, the
        supplied `settled_amount_cents` must be no greater than the demanded
        amount; a recovery deposit of exactly `settled_amount_cents` posts in
        `POSTED` status, the action's `recovered_amount_cents` becomes the
        settled amount, and `estate_cash_on_hand_cents` increases by that
        amount."
        PRD §3.5: "Settlement also performs the claim-swap: if the transfer
        amount exceeds the settled amount, a compensating claim of
        `priority_class` `GENERAL_UNSECURED` is created for the transferee
        creditor in the positive difference, stamped with a `received_at` of
        the current logical time — recovered dollars reduce the estate's
        liability to the preference recipient."

        Design: Corner/consistency_model/settle_atomicity_recovery_and_compensating_claim
        """
        ctx = setup_case_in_claims_administration(case_number="26-20070")
        case_id = ctx["case"]["id"]
        cred_id = ctx["creditor"]["id"]
        action = create_demanded_action(case_id, cred_id,
                                        transfer_amount_cents=100000,
                                        demand_amount_cents=100000)

        settled = validate_success(api.settle_action(action["id"], 60000, TRUSTEE))
        assert settled["status"] == "SETTLED"
        assert settled["recovered_amount_cents"] == 60000

        case = get_case(case_id)
        assert case["estate_cash_on_hand_cents"] == 60000

        resp = api.list_case_claims(case_id, TRUSTEE,
                                    params={"creditor_id": cred_id})
        claims = resp.json()["data"]
        assert len(claims) == 1
        assert claims[0]["filed_amount_cents"] == 40000, \
            "compensating claim covers the shortfall, visible immediately"
        assert claims[0]["priority_class"] == "GENERAL_UNSECURED"
