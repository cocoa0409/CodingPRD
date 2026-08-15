"""Clock sweep steps, alerts, and the depth-3 reprice cascades (PRD §3.9, §3.3, §3.2)."""
from test_helpers import (
    add_contract_term,
    approve_amendment,
    create_amendment,
    create_draft_contract,
    create_escalator,
    create_test_claim,
    create_test_payer,
    add_claim_line,
    activate_contract,
    get_case,
    get_claim,
    get_contract,
    get_single_case_for_claim,
    list_alerts,
    list_cases_for_claim,
    post_remittance,
    price_claim,
    set_clock,
    setup_case_with_filed_appeal,
    setup_priced_claim,
    validate_success,
)
from test_helpers.fixtures import CM


class TestAmendmentEffectiveCascade:
    """Sweep applies a retroactive amendment -> reprice -> variance -> case."""

    def _setup_retroactive_amendment(self, api):
        """Claim priced 200000 with a 150000 remittance (case QUEUED 50000),
        plus an APPROVED retroactive amendment to 120000/day."""
        ctx = setup_priced_claim(claim_overrides={"claim_number": "CL-TC1"})
        post_remittance(ctx["claim"]["id"], 150000)
        ctx["case"] = get_single_case_for_claim(ctx["claim"]["id"])
        assert ctx["case"]["original_variance_cents"] == 50000
        amendment = create_amendment(
            ctx["contract"]["id"],
            ctx["contract_version"],
            creator_user_id="ca-1",
            effective_date="2026-06-01",
            retroactive_to_date="2026-06-01",
            term_overrides=[
                {"service_category": "INPATIENT_MEDICAL", "base_rate_cents": 120000}
            ],
        )
        approve_amendment(amendment["id"], approver_user_id="cm-2")
        ctx["amendment"] = amendment
        return ctx

    def test_amendment_sweep_reprices_claim_and_recomputes_variance(self, api):
        """PRD §3.3: "when `retroactive_to_date` is set it fires the
        three-link reprice cascade: first, every claim priced under this
        contract in `PRICED` or `REPRICED` status with a discharge date on or
        after `retroactive_to_date` is repriced retrospectively; second, each
        repriced claim recomputes its variance and remittance standing".

        Design: Difficulty/transitive_cascade/amendment_effective_reprice_case_restate_cascade
        """
        ctx = self._setup_retroactive_amendment(api)
        summary = set_clock("2026-08-02T00:00:00Z")
        assert summary["amendments_applied"] == 1
        claim = get_claim(ctx["claim"]["id"])
        # Link 1: repriced RETROSPECTIVE at 2 nights x 120000.
        assert claim["pricing_status"] == "REPRICED"
        assert claim["expected_reimbursement_cents"] == 240000
        # Link 2: variance recomputed 240000 - 150000 = 90000.
        assert claim["variance_cents"] == 90000
        amendment = validate_success(api.get_rate_amendment(ctx["amendment"]["id"], CM))
        assert amendment["status"] == "EFFECTIVE"

    def test_amendment_sweep_restates_active_case(self, api):
        """PRD §3.3: "third, every variance flip either creates a fresh
        `QUEUED` underpayment case or restates the active case's original and
        current outstanding amounts." PRD §3.6: "Landing on `RECONCILED`
        restates the active case, if any, but never auto-closes it."

        Design: Difficulty/transitive_cascade/amendment_effective_reprice_case_restate_cascade
        """
        ctx = self._setup_retroactive_amendment(api)
        set_clock("2026-08-02T00:00:00Z")
        # Link 3: the same case (id stable) is restated to the new variance.
        case = get_case(ctx["case"]["id"])
        assert case["original_variance_cents"] == 90000
        assert case["current_outstanding_cents"] == 90000
        assert case["status"] == "QUEUED"
        assert len(list_cases_for_claim(ctx["claim"]["id"])) == 1


class TestEscalatorVoidCascade:
    """Voiding an APPLIED escalator reprices, recomputes variance, restates."""

    def _setup_applied_escalator_case(self, api):
        payer = create_test_payer(name="Payer EV")
        contract = create_draft_contract(payer["id"], contract_code="EV-2026")
        add_contract_term(contract["id"])
        escalator = create_escalator(
            contract["id"], effective_date="2026-06-01", escalator_bp=2000,
            compounding=True,
        )
        activate_contract(contract["id"])
        set_clock("2026-08-01T00:00:00Z")  # applies the escalator
        claim = create_test_claim(payer["id"], claim_number="CL-EV1")
        add_claim_line(claim["id"])
        priced = price_claim(claim["id"])
        # Sanity: 2 days x round_half_up(100000 x 1.2) = 240000.
        assert priced["expected_reimbursement_cents"] == 240000
        post_remittance(claim["id"], 200000)
        case = get_single_case_for_claim(claim["id"])
        assert case["original_variance_cents"] == 40000
        return {
            "payer": payer, "contract": contract, "escalator": escalator,
            "claim": priced, "case": case,
        }

    def test_escalator_void_reprices_claim_and_reconciles(self, api):
        """PRD §3.2: "voiding an `APPLIED` one reprices the past: every claim
        priced under that contract, in `PRICED` or `REPRICED` pricing status,
        whose discharge date falls on or after the escalator's
        `effective_date` is repriced retrospectively, each repriced claim
        recomputes its variance and remittance standing".

        Design: Difficulty/transitive_cascade/escalator_void_reprice_case_restate_cascade
        """
        ctx = self._setup_applied_escalator_case(api)
        validate_success(api.void_rate_escalator(ctx["escalator"]["id"], CM))
        claim = get_claim(ctx["claim"]["id"])
        # Link 1: repriced without the escalator -> 200000.
        assert claim["expected_reimbursement_cents"] == 200000
        # Link 2: variance 200000 - 200000 = 0 -> RECONCILED.
        assert claim["variance_cents"] == 0
        assert claim["remittance_status"] == "RECONCILED"
        escalator = validate_success(api.get_rate_escalator(ctx["escalator"]["id"], CM))
        assert escalator["status"] == "VOIDED"

    def test_escalator_void_restates_case_without_closing_it(self, api):
        """PRD §3.2: "the underpayment queue absorbs the difference — active
        cases are restated and fresh cases are queued wherever variance
        crosses the threshold." PRD §3.6: "Landing on `RECONCILED` restates
        the active case, if any, but never auto-closes it."

        Design: Difficulty/transitive_cascade/escalator_void_reprice_case_restate_cascade
        """
        ctx = self._setup_applied_escalator_case(api)
        validate_success(api.void_rate_escalator(ctx["escalator"]["id"], CM))
        case = get_case(ctx["case"]["id"])
        # Link 3: restated to the new (zero) variance, left QUEUED.
        assert case["original_variance_cents"] == 0
        assert case["current_outstanding_cents"] == 0
        assert case["status"] == "QUEUED"


class TestClockSweepAlerts:
    def test_term_expiring_alerts_deduped(self, api):
        """PRD §3.9: "`TERM_EXPIRING_90` fires for a contract in `ACTIVE` or
        `SUSPENDED` whose `expiration_date` lies between 0 and 90 days after
        today inclusive, keyed on the contract and alert type.
        `TERM_EXPIRING_30` fires on the same condition with a 30-day window,
        keyed identically — so a contract inside thirty days carries both
        alerts." and the sweep is "deduplicated so the sweep never creates a
        second alert with the same key".

        Design: Corner/endpoints/ep_clock_sweep_term_expiring_alerts_deduped
        """
        payer = create_test_payer(name="Payer AL")
        contract = create_draft_contract(
            payer["id"], contract_code="AL-2026", expiration_date="2026-10-30"
        )
        add_contract_term(contract["id"])
        activate_contract(contract["id"])

        # Exactly 90 days out (inclusive boundary): TERM_EXPIRING_90 only.
        summary = set_clock("2026-08-01T00:00:00Z")
        assert summary["alerts_generated"] == 1
        alerts_90 = list_alerts(
            contract_id=contract["id"], alert_type="TERM_EXPIRING_90"
        )
        alerts_30 = list_alerts(
            contract_id=contract["id"], alert_type="TERM_EXPIRING_30"
        )
        assert len(alerts_90) == 1
        assert alerts_30 == []

        # 30 days out: TERM_EXPIRING_30 joins; the 90-day alert is not remade.
        set_clock("2026-09-30T00:00:00Z")
        all_alerts = list_alerts(contract_id=contract["id"])
        assert len(all_alerts) == 2
        by_type = {a["alert_type"] for a in all_alerts}
        assert by_type == {"TERM_EXPIRING_90", "TERM_EXPIRING_30"}
        for alert in all_alerts:
            assert alert["status"] == "TRIGGERED"
        assert get_contract(contract["id"])["status"] == "ACTIVE"

    def test_clock_sweep_expires_contract_with_alert(self, api):
        """PRD §3.9: "Step four expires contracts: every `ACTIVE` contract
        whose `expiration_date` has passed moves to `EXPIRED` and raises a
        `TERM_EXPIRED` alert."

        Design: Corner/endpoints/ep_clock_sweep_expires_contract_with_alert
        """
        payer = create_test_payer(name="Payer EX")
        contract = create_draft_contract(
            payer["id"], contract_code="EX-2026", expiration_date="2026-08-15"
        )
        add_contract_term(contract["id"])
        activate_contract(contract["id"])
        summary = set_clock("2026-08-16T00:00:00Z")
        assert summary["contracts_expired"] == 1
        assert get_contract(contract["id"])["status"] == "EXPIRED"
        alerts = list_alerts(contract_id=contract["id"], alert_type="TERM_EXPIRED")
        assert len(alerts) == 1

    def test_clock_sweep_expires_filed_appeal(self, api):
        """PRD §3.7: "If today passes `response_due_date` with no outcome
        recorded — the due date itself is still timely — the clock sweep
        expires the appeal: it moves to terminal `EXPIRED`, its `outcome`
        becomes `EXPIRED`, `outcome_recorded_date` is stamped, and a level-4
        expiry additionally drives its case to `DENIED_FINAL`."

        Design: Corner/endpoints/ep_clock_sweep_expires_filed_appeal
        """
        ctx = setup_case_with_filed_appeal(
            level=1, paid_amount_cents=100000,
            claim_overrides={"claim_number": "CL-AX1"},
        )
        appeal = ctx["appeal"]
        assert appeal["response_due_date"] == "2026-08-31"
        summary = set_clock("2026-09-01T00:00:00Z")
        assert summary["appeals_expired"] == 1
        appeal_after = validate_success(api.get_appeal(appeal["id"], CM))
        assert appeal_after["status"] == "EXPIRED"
        assert appeal_after["outcome"] == "EXPIRED"
        assert appeal_after["outcome_recorded_date"] == "2026-09-01"
        # Non-level-4 expiry does not end the case.
        assert get_case(ctx["case"]["id"])["status"] == "APPEAL_L1"

    def test_clock_sweep_escalator_upcoming_alert(self, api):
        """PRD §3.9: "`ESCALATOR_UPCOMING` fires for a `SCHEDULED` escalator
        whose `effective_date` lies between 0 and 30 days after today
        inclusive, keyed on contract, alert type, and escalator." and "Step
        one applies escalators: every `SCHEDULED` escalator whose
        `effective_date` is on or before today moves to `APPLIED`".

        Design: Corner/endpoints/ep_clock_sweep_escalator_upcoming_alert
        """
        payer = create_test_payer(name="Payer EU")
        contract = create_draft_contract(payer["id"], contract_code="EU-2026")
        add_contract_term(contract["id"])
        escalator = create_escalator(
            contract["id"], effective_date="2026-08-20", escalator_bp=1000
        )
        activate_contract(contract["id"])
        set_clock("2026-08-01T00:00:00Z")  # 19 days out -> alert, not applied
        alerts = list_alerts(escalator_id=escalator["id"])
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "ESCALATOR_UPCOMING"
        escalator_after = validate_success(api.get_rate_escalator(escalator["id"], CM))
        assert escalator_after["status"] == "SCHEDULED"
