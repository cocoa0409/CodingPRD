"""Contract drafting/execution gates, amendments, overlap rules, and OCC on contracts."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_contract,
    create_contract,
    execute_contract,
    get_contract,
    get_engagement,
    make_answers,
    propose_amendment,
    setup_engagement_at_state,
    validate_error,
    validate_paginated,
    validate_success,
    verify_contractor,
)

_MANAGER = TEST_USERS["engagement_manager_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]
_LEGAL = TEST_USERS["legal_approver_headers"]


class TestActivationContractGate:
    def test_activate_blocked_while_contract_draft(self, api, engagement_manager_headers):
        """PRD §3.5: "Activation requires a contract in `EXECUTED` status for the
        engagement — otherwise `ERR_CONTRACT_NOT_EXECUTED` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/cesd_activate_requires_executed_contract
        """
        setup = setup_engagement_at_state("APPROVED")
        engagement = setup["engagement"]
        verify_contractor(setup["contractor"]["id"])
        contract = create_contract(engagement["id"])
        assert contract["status"] == "DRAFT"

        res = api.activate_engagement(engagement["id"], engagement_manager_headers)
        validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_EXECUTED.value)
        assert get_engagement(engagement["id"])["status"] == "APPROVED"

    def test_activate_succeeds_after_contract_executed(self, api, engagement_manager_headers):
        """PRD §3.5: "Activation requires a contract in `EXECUTED` status for the
        engagement — otherwise `ERR_CONTRACT_NOT_EXECUTED` (HTTP 409) — and applies the
        contractor standing gate of §3.2. A successful activation moves the engagement
        `APPROVED → ACTIVE` and increments its `version`."

        Design: Difficulty/cross_entity_state_dependency/cesd_activate_requires_executed_contract
        """
        setup = setup_engagement_at_state("APPROVED")
        engagement = setup["engagement"]
        verify_contractor(setup["contractor"]["id"])
        contract = create_contract(engagement["id"])
        executed = execute_contract(contract["id"])
        assert executed["status"] == "EXECUTED"

        res = api.activate_engagement(engagement["id"], engagement_manager_headers)
        activated = validate_success(res, 200)
        assert activated["status"] == "ACTIVE"


class TestContractPeriodOverlap:
    def _approved_with_contract(self):
        # The existing contract's end_date must lie strictly after the logical
        # clock's startup instant (2026-08-01, PRD §2.5); otherwise the EXECUTED
        # contract lazy-expires on the next read and is no longer an overlap peer
        # (EXPIRED is outside the DRAFT/EXECUTED/SUSPENDED overlap set, PRD §3.6).
        setup = setup_engagement_at_state("APPROVED")
        verify_contractor(setup["contractor"]["id"])
        contract = create_contract(
            setup["engagement"]["id"], start_date="2026-02-01", end_date="2026-12-01"
        )
        execute_contract(contract["id"])
        return setup, contract

    def test_overlapping_contract_rejected(self, api, engagement_manager_headers):
        """PRD §3.6: "no two contracts for the same `contractor_id` and
        `jurisdiction_id` pair in `DRAFT`, `EXECUTED`, or `SUSPENDED` status may
        overlap: a new contract whose period begins before an existing contract's
        period ends while the existing period begins before the new period ends is
        rejected with `ERR_CONTRACT_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rto_contract_half_open_adjacency
        """
        setup, _ = self._approved_with_contract()
        res = api.create_contract(
            setup["engagement"]["id"],
            {"start_date": "2026-05-01", "end_date": "2026-09-01",
             "rate_cents": 10000, "rate_unit": "HOURLY"},
            engagement_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_CONTRACT_PERIOD_OVERLAP.value)

    def test_adjacent_contract_allowed(self, api, engagement_manager_headers):
        """PRD §3.6: "Contract periods are half-open intervals — the start date is
        inclusive and the end date exclusive" and "Adjacency is allowed — a new
        contract whose `start_date` equals an existing contract's `end_date` touches
        without overlapping."

        Design: Difficulty/resource_temporal_overlap/rto_contract_half_open_adjacency
        """
        setup, _ = self._approved_with_contract()
        res = api.create_contract(
            setup["engagement"]["id"],
            {"start_date": "2026-12-01", "end_date": "2027-04-01",
             "rate_cents": 10000, "rate_unit": "HOURLY"},
            engagement_manager_headers,
        )
        contract = validate_success(res, 201)
        assert_contract(contract)
        assert contract["status"] == "DRAFT"
        assert contract["start_date"] == "2026-12-01"


class TestAmendments:
    def test_amendment_stale_contract_version_rejected(self, api, engagement_manager_headers):
        """PRD §2.6: "`POST /api/contracts/{id}/amendments` requires a non-optional
        `expected_contract_version` input carrying the client's last observed `version`
        of the parent contract. If the contract's current `version` differs — for
        example because another amendment was just proposed or applied, changing the
        contract's terms — the request is rejected with `ERR_STALE_CONTRACT_VERSION`
        (HTTP 412), and the amendment must be re-based on the current contract terms."
        PRD §3.6: "A proposal begins in `PROPOSED` and increments the parent contract's
        `version`, so each proposal invalidates any other client's captured contract
        version."

        Design: Corner/cross_cutting_layers/layer_occ_stale_contract_version_on_amendment
        """
        setup = setup_engagement_at_state("ACTIVE")
        contract = setup["contract"]
        stale_version = get_contract(contract["id"])["version"]

        first = api.create_amendment(
            contract["id"],
            {"expected_contract_version": stale_version,
             "scope_change_summary": "Amendment A", "new_rate_cents": 10500},
            engagement_manager_headers,
        )
        validate_success(first, 201)

        second = api.create_amendment(
            contract["id"],
            {"expected_contract_version": stale_version,
             "scope_change_summary": "Amendment B based on stale view",
             "new_rate_cents": 11000},
            engagement_manager_headers,
        )
        validate_error(second, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)

    def test_rejected_amendment_is_terminal(self, api, legal_approver_headers):
        """PRD §3.6: "A rejection moves the amendment `PROPOSED → REJECTED`." and
        "`APPLIED`, `REJECTED`, and `VOIDED` are the amendment's terminal states."
        PRD §2.9: state validity covers "terminal amendments".

        Design: Corner/state_machines/sm_amendment_terminal_reject_lockdown
        """
        setup = setup_engagement_at_state("ACTIVE")
        contract = setup["contract"]
        amendment = propose_amendment(contract["id"], new_rate_cents=10500)

        rejected = validate_success(
            api.approve_amendment(amendment["id"], {"decision": "REJECTED"}, legal_approver_headers),
            200,
        )
        assert rejected["status"] == "REJECTED"

        res = api.approve_amendment(amendment["id"], {"decision": "APPROVED"}, legal_approver_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
        assert get_contract(contract["id"])["rate_cents"] == 10000


class TestExecutionGatePriority:
    def _setup_expired_grant_high_engagement(self):
        """HIGH-tier engagement APPROVED behind a grant expiring 2026-08-10;
        contractor VERIFIED with insurance below the jurisdiction floor; contract
        drafted; clock advanced past the grant's expiry."""
        setup = setup_engagement_at_state(
            "APPROVED",
            jurisdiction_overrides={
                "code": "US-CA",
                "test_type": "ABC_TEST",
                "state_filing_threshold_cents": 0,
                "min_insurance_cents": 100000,
            },
            contractor_overrides={"insurance_coverage_cents": 50000},
            answers=make_answers(CONTROL_METHOD="YES"),
            with_exception=True,
            exception_overrides={"expires_at": "2026-08-10T00:00:00Z"},
        )
        verify_contractor(setup["contractor"]["id"])
        contract = create_contract(setup["engagement"]["id"], rate_cents=9000)
        # `api_client` is the same singleton the `api` fixture hands to test
        # methods; helper methods have no fixture scope, so reference it directly.
        api_client.set_clock("2026-08-20T00:00:00Z", _ADMIN)
        return setup, contract

    def test_execute_insurance_error_beats_exception_expired(self, api, engagement_manager_headers):
        """PRD §3.6: "Execution moves the contract `DRAFT → EXECUTED` under three
        gates: the contractor must be `VERIFIED` (else `ERR_CONTRACTOR_NOT_VERIFIED`),
        the contractor's `insurance_coverage_cents` must be at least the
        jurisdiction's `min_insurance_cents` (else `ERR_INSURANCE_BELOW_MINIMUM`, HTTP
        422), and when the engagement's `risk_tier` is `HIGH` an `ACTIVE`, unexpired
        ExceptionGrant must exist for the engagement — absent, the rejection is
        `ERR_EXCEPTION_REQUIRED`; expired, `ERR_EXCEPTION_EXPIRED`."
        PRD §2.9: "a request that fails an earlier rung is rejected immediately and
        never surfaces a later rung's error" — business safety gates (rung 6) precede
        referential soundness (rung 9, exception expiry).

        Design: Difficulty/priority_pair_validation_conflict/ppv_safety_vs_referential_on_contract_execute
        """
        setup, contract = self._setup_expired_grant_high_engagement()
        res = api.execute_contract(contract["id"], engagement_manager_headers)
        validate_error(res, ApiErrorId.ERR_INSURANCE_BELOW_MINIMUM.value)

    def test_expired_grant_reads_expired_after_clock_passes(self, api, engagement_manager_headers):
        """PRD §2.5: "An ExceptionGrant whose `expires_at` lies in the past — the clock
        instant is strictly later than `expires_at` — is treated as `EXPIRED`; this
        evaluation happens whenever the grant is read or used as a precondition."

        Design: Difficulty/priority_pair_validation_conflict/ppv_safety_vs_referential_on_contract_execute
        """
        setup, contract = self._setup_expired_grant_high_engagement()
        res = api.execute_contract(contract["id"], engagement_manager_headers)
        validate_error(res, ApiErrorId.ERR_INSURANCE_BELOW_MINIMUM.value)

        grants, _ = validate_paginated(
            api.list_exceptions(setup["engagement"]["id"], _ADMIN)
        )
        assert len(grants) == 1
        assert grants[0]["status"] == "EXPIRED"
        assert get_contract(contract["id"])["status"] == "DRAFT"


class TestContractExistence:
    def test_contract_get_not_found_returns_404(self, api, platform_admin_headers):
        """PRD §2.7: "any other resource identifier — whether an `{id}` path segment
        naming a jurisdiction, contract, amendment, review, audit, remediation action,
        filing, inquiry, conversion, or exception, or a resource referenced inside a
        request body — yields `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/errors/err_contract_get_not_found_returns_404
        """
        res = api.get_contract(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)
