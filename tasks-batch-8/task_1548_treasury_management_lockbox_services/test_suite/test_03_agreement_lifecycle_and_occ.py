"""ServiceAgreement lifecycle: invalid transitions, validation ordering,
segregation of duties, optimistic concurrency, and terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    begin_onboarding,
    create_agreement,
    create_bank,
    create_customer,
    get_agreement,
    implement_agreement,
    list_cycles,
    make_activator_headers,
    run_close_analysis_cycle_at_month_end,
    settle_cycle,
    setup_active_agreement,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bank_admin_headers"]
ACTIVATOR = TEST_USERS["activator_headers"]


class TestAgreementActivationOrdering:
    def test_activate_draft_agreement_reports_state_error_first(self, api):
        """PRD §2.9: "Incoming requests are checked against the following rules
        in the order listed — a request that fails an earlier check is rejected
        immediately and never reaches a later one."
        PRD §2.9: "5. The target resource is in a lifecycle state from which
        the requested transition is defined (`ERR_INVALID_STATE_TRANSITION`,
        409)." (listed ahead of "6. Segregation of duties")

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_agreement_activate
        """
        bank = create_bank()
        customer = create_customer(bank["id"])
        begin_onboarding(bank["id"], customer["id"])
        agreement = create_agreement(bank["id"], customer["id"])
        # Agreement is still DRAFT: activate is defined only from IMPLEMENTED.
        resp = api.activate_agreement(
            bank["id"], customer["id"], agreement["id"],
            agreement["version"] + 1,
            make_activator_headers("act-user-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_activate_by_implementer_violates_segregation_of_duties(self, api):
        """PRD §2.8: "the TreasuryActivator who activates a ServiceAgreement
        must differ from the `implemented_by_user_id` who implemented it".
        PRD §2.8: "Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_agreement_activate
        """
        bank = create_bank()
        customer = create_customer(bank["id"])
        begin_onboarding(bank["id"], customer["id"])
        agreement = create_agreement(bank["id"], customer["id"])
        implement_agreement(bank["id"], customer["id"], agreement["id"],
                            implementer_id="impl-user-1")
        current = get_agreement(bank["id"], customer["id"], agreement["id"])
        # The activator role is correct, but X-User-ID equals the implementer's.
        resp = api.activate_agreement(
            bank["id"], customer["id"], agreement["id"], current["version"],
            make_activator_headers("impl-user-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestAgreementInvalidTransition:
    def test_invalid_from_state_returns_error(self, api):
        """PRD §2.9: "5. The target resource is in a lifecycle state from which
        the requested transition is defined (`ERR_INVALID_STATE_TRANSITION`,
        409)."
        PRD §4: agreement suspend is "ACTIVE → SUSPENDED".

        Design: Corner/state_machines/invalid_from_state_returns_error
        """
        bank = create_bank()
        customer = create_customer(bank["id"])
        agreement = create_agreement(bank["id"], customer["id"])
        # Suspend is defined only from ACTIVE; the agreement is DRAFT.
        resp = api.suspend_agreement(bank["id"], customer["id"],
                                     agreement["id"], ACTIVATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestAgreementActivationOcc:
    def test_stale_version_on_agreement_activate(self, api):
        """PRD §2.4: "Agreement activation and transmission-format activation
        each require the request to carry `expected_agreement_version` holding
        the client's last-observed `version` of the parent ServiceAgreement".
        PRD §2.4: "If the parent's version has advanced since the client last
        read it — another writer has legitimately moved the resource forward,
        for example by activating the agreement or by a confirmation cascade
        bumping a cycle — the write is rejected with `ERR_STALE_VERSION`
        (HTTP 412), so the client never overwrites state it has not observed."

        Design: Corner/errors/err_stale_version_on_agreement_activate
        """
        bank = create_bank()
        customer = create_customer(bank["id"])
        begin_onboarding(bank["id"], customer["id"])
        agreement = create_agreement(bank["id"], customer["id"])
        observed_version = agreement["version"]
        # Implementing mutates the agreement, so its version advances (PRD §2.4:
        # the version "increments by one on every mutation of the resource").
        implement_agreement(bank["id"], customer["id"], agreement["id"])
        current = get_agreement(bank["id"], customer["id"], agreement["id"])
        assert current["status"] == "IMPLEMENTED"
        assert current["version"] != observed_version
        # The client's last-observed version is stale relative to the parent.
        resp = api.activate_agreement(
            bank["id"], customer["id"], agreement["id"], observed_version,
            make_activator_headers("act-user-1"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestCustomerTerminalLockdown:
    def test_terminal_state_lockdown_on_terminated_customer(self, api):
        """PRD §3.2: "Terminating a customer requires all agreements
        `TERMINATED`, all AnalysisCycles `SETTLED` (otherwise
        `ERR_CUSTOMER_NOT_SETTLED`), and no ImageRetrievalRequest still
        `REQUESTED`."
        PRD §2.9: "5. The target resource is in a lifecycle state from which
        the requested transition is defined (`ERR_INVALID_STATE_TRANSITION`,
        409)." (resume is defined only SUSPENDED → ACTIVE, not from TERMINATED)

        Design: Corner/state_machines/terminal_state_lockdown_on_terminated_customer
        """
        ws = setup_active_agreement()
        b_id = ws["bank"]["id"]
        c_id = ws["customer"]["id"]
        a_id = ws["agreement"]["id"]
        # No sites exist, and no closed cycle references the agreement yet
        # (PRD §3.7: the cycle's agreement_id references the ACTIVE agreement
        # at close), so the agreement can terminate; the in-flight OPEN cycle
        # is then closed at its cycle_end_date (PRD §3.7) and settled.
        validate_success(api.terminate_agreement(b_id, c_id, a_id, ACTIVATOR))
        run_close_analysis_cycle_at_month_end(ws, customer_id=c_id)
        cycle = list_cycles(ws)[0]
        assert cycle["status"] == "FINALIZED"
        settle_cycle(ws, cycle["id"])
        terminated = validate_success(
            api.terminate_customer(b_id, c_id, ACTIVATOR))
        assert terminated["status"] == "TERMINATED"
        # TERMINATED is terminal: resume is not a defined transition from it.
        resp = api.resume_customer(b_id, c_id, ACTIVATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
