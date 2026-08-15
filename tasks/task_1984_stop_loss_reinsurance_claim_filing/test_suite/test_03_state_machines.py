"""State-machine basics: invalid transitions, terminal lockdown, initial states."""
from test_helpers import (
    ADMIN,
    EXAMINER,
    ApiErrorId,
    create_claim,
    create_contract,
    create_filing,
    create_member,
    create_plan,
    get_claim,
    get_contract,
    renew_contract,
    set_clock,
    setup_paid_claim_scenario,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api_client


class TestClaimTransitions:
    def test_pay_submitted_claim_rejected(self, api):
        """PRD §3.4: "Payment then moves the claim from `ADJUDICATED` to
        `PAID`, recording `paid_amount_cents` — which may not exceed
        `allowed_amount_cents` — together with the `paid_date`."
        PRD §2.9: "State eligibility comes fourth: the target entity's
        current state must permit the requested transition, failing with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/claim_invalid_transition_submitted_to_paid
        """
        plan = create_plan(plan_name="P", sponsor_tax_id="55-5555555")
        member = create_member(plan["id"], "M")
        claim = create_claim(plan["id"], member["id"],
                             billed_amount_cents=1_000_000)
        resp = api.pay_claim(
            claim["id"], {"paid_amount_cents": 1_000_000,
                          "paid_date": "2026-02-02T00:00:00Z"}, EXAMINER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_claim(claim["id"])["status"] == "SUBMITTED"


class TestContractRenewal:
    def test_renewed_contract_cannot_be_activated(self, api):
        """PRD §3.2: "A contract in `EXPIRED` — and only in `EXPIRED` — may
        be renewed by a `PlanAdministrator`, moving it to the terminal
        `RENEWED` state while the system creates a successor contract in
        `DRAFT` carrying the renewed terms."
        PRD §3.2: "A request that fails any activation precondition — like
        any transition attempted from a state that does not permit it — is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/contract_terminal_renewed_lockdown
        """
        set_clock("2026-01-01T00:00:00Z")
        plan = create_plan(plan_name="P", sponsor_tax_id="66-6666666")
        contract = create_contract(
            plan["id"], policy_year_start="2026-01-01T00:00:00Z",
            policy_year_end="2026-06-01T00:00:00Z", filing_deadline_days=30)
        resp = _api_client.activate_contract(contract["id"], ADMIN)
        contract = validate_success(resp, 200)
        assert contract["status"] == "IN_FORCE"

        # Cross policy_year_end: the IN_FORCE -> EXPIRED transition fires.
        set_clock("2026-07-01T00:00:00Z")
        assert get_contract(contract["id"])["status"] == "EXPIRED"

        successor = renew_contract(contract["id"], "2026-06-01T00:00:00Z",
                                   "2027-06-01T00:00:00Z",
                                   filing_deadline_days=30)
        assert successor["status"] == "DRAFT"
        assert get_contract(contract["id"])["status"] == "RENEWED"

        # RENEWED is terminal: activation from it is not permitted.
        resp = _api_client.activate_contract(contract["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestFilingInitialState:
    def test_new_filing_is_draft_with_null_submitted_at(self, api):
        """PRD §3.5: "The new filing starts in `DRAFT`."
        PRD §3.5: "Two filing fields stay null until their moment:
        `submitted_at` while the filing is in `DRAFT`, and
        `approved_amount_cents` until the filing reaches `APPROVED` or
        `PAID`."

        Design: Corner/state_machines/filing_initial_state_is_draft
        """
        ctx = setup_paid_claim_scenario(plan_name="P", claim_cents=15_000_000)
        filing = create_filing(ctx["contract"]["id"], [ctx["claim"]["id"]],
                               filing_scope="SPECIFIC",
                               member_id=ctx["member"]["id"])
        assert filing["status"] == "DRAFT", (
            f"New filing must be DRAFT, got {filing['status']}")
        assert filing["submitted_at"] is None, (
            f"submitted_at must be null while DRAFT, got {filing['submitted_at']!r}")
        assert filing["approved_amount_cents"] is None, (
            "approved_amount_cents must be null until APPROVED or PAID")
