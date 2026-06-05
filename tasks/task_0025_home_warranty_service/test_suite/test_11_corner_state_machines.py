"""Corner (state machines) — invalid transitions, initial state, terminal lockdown,
direct side effects."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    set_clock,
    tick_clock,
    setup_active_contract_with_item,
    setup_expired_contract,
    file_claim,
    assess_claim,
    dispatch_claim,
    get_dispatch_for_claim,
    start_dispatch,
    make_customer_headers,
    make_admin_headers,
    make_technician_headers,
    renew_contract_payload,
)


_ADMIN = make_admin_headers()
_TECHNICIAN = make_technician_headers()


class TestContractCancelFromTerminalExpired:

    def test_cancel_expired_contract_returns_invalid_state(self, api):
        """PRD §3.2: "A `Customer` may cancel their own contract while it is still
        in `PENDING_PAYMENT` with no further conditions; this transitions the
        contract to `CANCELLED`. Cancellation from `ACTIVE` is also permitted, but
        only when no `ClaimTicket` on the contract is in `SUBMITTED`, `ASSESSED`,
        or `DISPATCHED` — that is, no open claim is in flight."
        PRD §3.2: "Both `CANCELLED` and `EXPIRED` and `RENEWED` are terminal contract states;
        no further transition leaves them."

        Design: Corner/state_machines/contract_cancel_from_terminal_expired_invalid_state
        """
        package, customer, expired = setup_expired_contract(
            activate_at="2026-01-01T00:00:00Z",
            tick_at="2027-02-01T00:00:00Z",
        )
        assert expired["status"] == "EXPIRED"
        cust_h = make_customer_headers(customer["id"])
        res = api.cancel_contract(expired["id"], cust_h)
        validate_error(res, "ERR_INVALID_STATE")


class TestClaimInitialState:

    def test_newly_filed_claim_is_submitted(self, api):
        """PRD §3.4: "The new claim is written in `SUBMITTED` with all computed
        fields cleared: `repair_cost_cents` zero, `provisional_copay_cents` zero,
        `final_copay_cents` zero, `service_fee_charged_cents` zero, `is_return_visit`
        false, `prior_dispatch_id` null, and `rejection_reason` null."

        Design: Corner/state_machines/claim_initial_state_submitted_on_create
        """
        package, customer, contract, item = setup_active_contract_with_item()
        claim = file_claim(contract, customer, item, issue="Just filed")
        assert claim["status"] == "SUBMITTED"
        assert claim["repair_cost_cents"] == 0
        assert claim["provisional_copay_cents"] == 0
        assert claim["final_copay_cents"] == 0
        assert claim["service_fee_charged_cents"] == 0
        assert claim["is_return_visit"] is False
        assert claim.get("rejection_reason") is None


class TestContractTerminalRenewedLockdown:

    def test_cancel_renewed_contract_returns_invalid_state(self, api):
        """PRD §3.8: "The original contract's `status` is set to `RENEWED` and its
        `version` is incremented by one. `RENEWED` is terminal on the original;
        the successor begins the cycle anew and must itself be activated"

        Design: Corner/state_machines/contract_terminal_renewed_lockdown_no_further_transitions
        """
        from test_helpers import setup_expiring_soon_contract
        package, customer, expiring = setup_expiring_soon_contract(
            activate_at="2026-01-01T00:00:00Z",
            tick_at="2026-12-12T00:00:00Z",
        )
        cust_h = make_customer_headers(customer["id"])
        # Renew → original becomes RENEWED (terminal).
        get_success_data(api.renew_contract(
            expiring["id"], renew_contract_payload(expiring["version"]), cust_h
        ))
        # Now try to cancel the original → blocked by terminal state.
        res = api.cancel_contract(expiring["id"], cust_h)
        validate_error(res, "ERR_INVALID_STATE")


class TestDispatchCompleteStampsCompletedUtc:

    def test_complete_stamps_completed_utc_with_clock_value(self, api):
        """PRD §3.5: "A successful repair completes the dispatch (`IN_PROGRESS →
        COMPLETED`), which stamps `completed_utc` on the dispatch to the current clock"

        Design: Corner/state_machines/dispatch_complete_stamps_completed_utc_side_effect
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        claim = file_claim(contract, customer, item)
        assess_claim(claim, 10_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(claim, "tech-S", "2026-02-01T10:00:00Z")
        d = get_dispatch_for_claim(claim["id"])
        set_clock("2026-02-01T10:30:00Z")
        start_dispatch(d)
        set_clock("2026-02-01T11:00:00Z")
        res = api.complete_dispatch(d["id"], _TECHNICIAN)
        body = validate_success(res, 200)
        assert body["status"] == "COMPLETED"
        # completed_utc reflects the current clock at the moment of /complete.
        # The PRD permits any ISO-8601 spelling; we check the implementation's stamp
        # round-trips to the same instant we set.
        assert body["completed_utc"] is not None
        assert body["completed_utc"].startswith("2026-02-01T11:00:00")


class TestDispatchStartBeforeScheduled:

    def test_start_before_scheduled_utc_returns_invalid_state(self, api):
        """PRD §3.5: "The start endpoint is only legal once the server clock has
        reached `scheduled_utc` — earlier starts are blocked by the state-machine
        eligibility check."

        Design: Corner/state_machines/dispatch_start_before_scheduled_invalid_state
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        claim = file_claim(contract, customer, item, issue="Soon")
        assess_claim(claim, 10_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(claim, "tech-Q", "2026-02-01T10:00:00Z")
        d = get_dispatch_for_claim(claim["id"])
        # Clock still at 2026-02-01T08:00 < scheduled_utc 2026-02-01T10:00.
        res = api.start_dispatch(d["id"], _TECHNICIAN)
        validate_error(res, "ERR_INVALID_STATE")
