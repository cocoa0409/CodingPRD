"""Corner coverage: existence/validation errors, RBAC, OCC, cross-cutting filters."""
from test_helpers import (
    get_success_data, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_benchmark_payload, create_contract_payload,
    create_contract_version_payload, create_fee_schedule_entry_payload,
    create_network, create_provider, create_draft_contract,
    create_paid_claim_payload, create_published_benchmark,
    create_simulation_batch_payload, create_simulation_claim_payload,
    create_termination_notice_payload,
    make_contract_legal_headers, make_contract_manager_headers,
    make_provider_rep_headers,
    setup_contract_active, setup_contract_in_configuration_with_mapped_version,
    setup_contract_in_testing,
    TEST_USERS,
)

ADMIN = TEST_USERS["plan_admin_headers"]
CA = TEST_USERS["configuration_analyst_headers"]
CL = TEST_USERS["contract_legal_headers"]
CM = TEST_USERS["contract_manager_headers"]
PI = TEST_USERS["payment_integrity_headers"]


class TestMissingAuthHeaders:
    def test_no_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        string the system does not declare, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_providers(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestContractManagerCannotSign:
    def test_sign_wrong_role_returns_unauthorized(self, api):
        """PRD §2.1: "A request whose authenticated role is not listed among the
        roles permitted for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST `/contracts/{id}/sign` is ContractLegal-only.

        Design: Corner/errors/contract_manager_cannot_sign_returns_unauthorized
        """
        # Priority 3 fires before existence (PRD §2.10), so an unknown id is fine.
        resp = api.sign_contract(NON_EXISTENT_UUID, CM)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestDuplicateBenchmark:
    def test_duplicate_composite_rejected(self, api):
        """PRD §3.1: "The triple of year, locality, and code is unique across the
        dataset: loading a second row for an existing triple is rejected with
        `ERR_DUPLICATE_BENCHMARK` (HTTP 409)."

        Design: Corner/errors/duplicate_benchmark_rejected
        """
        get_success_data(api.create_benchmark(create_benchmark_payload(), ADMIN))
        resp = api.create_benchmark(
            create_benchmark_payload(benchmark_amount_cents=10500), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BENCHMARK)


class TestDuplicateVersionNumber:
    def test_duplicate_version_number_rejected(self, api):
        """PRD §3.4: "finally a `version_number` already used on the contract is
        rejected with `ERR_DUPLICATE_VERSION_NUMBER` (HTTP 409)."

        Design: Corner/errors/duplicate_version_number_rejected
        """
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        contract = get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        contract = get_success_data(api.sign_contract(
            contract["id"], make_contract_legal_headers("cl-1")))
        contract = get_success_data(api.begin_configuration(contract["id"], CA))
        get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract["version"]),
            CM,
        ))
        current = get_success_data(api.get_contract(contract["id"], ADMIN))
        resp = api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-09-01",
                expected_contract_version=current["version"]),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VERSION_NUMBER)


class TestDuplicateServiceCode:
    def test_duplicate_hcpcs_on_same_version_rejected(self, api):
        """PRD §3.4: "a duplicate `hcpcs_code` on the version draws
        `ERR_DUPLICATE_SERVICE_CODE` (HTTP 409)"

        Design: Corner/errors/duplicate_service_code_rejected
        """
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        contract = get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        contract = get_success_data(api.sign_contract(
            contract["id"], make_contract_legal_headers("cl-1")))
        contract = get_success_data(api.begin_configuration(contract["id"], CA))
        version = get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract["version"]),
            CM,
        ))
        payload1 = create_fee_schedule_entry_payload(
            hcpcs_code="99213", rate_type="FLAT_RATE", flat_rate_cents=5000)
        payload1.pop("pct_of_medicare_bps", None)
        get_success_data(api.create_fee_schedule_entry(version["id"], payload1, CA))
        payload2 = create_fee_schedule_entry_payload(
            hcpcs_code="99213", service_category="ER_VISIT",
            rate_type="FLAT_RATE", flat_rate_cents=6000)
        payload2.pop("pct_of_medicare_bps", None)
        resp = api.create_fee_schedule_entry(version["id"], payload2, CA)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERVICE_CODE)


class TestDuplicateClaimNumber:
    def test_duplicate_claim_number_rejected(self, api):
        """PRD §3.8: "Each **paid claim snapshot** records an external
        `claim_number` — unique per contract, duplicates rejected with
        `ERR_DUPLICATE_CLAIM_NUMBER` (HTTP 409)"

        Design: Corner/errors/duplicate_claim_number_rejected
        """
        artefacts = setup_contract_active()
        contract_id = artefacts["contract"]["id"]
        get_success_data(api.create_paid_claim(
            contract_id, create_paid_claim_payload(claim_number="CLM-1"), PI))
        resp = api.create_paid_claim(
            contract_id,
            create_paid_claim_payload(claim_number="CLM-1", service_date="2026-08-11"),
            PI,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM_NUMBER)


class TestRetroWindowInvalid:
    def test_retro_date_not_before_effective_rejected(self, api):
        """PRD §3.4: "a `retro_effective_date`, when present, must fall on or
        after the contract's `base_effective_date` and strictly before the
        version's own `effective_date`, failing with `ERR_RETRO_WINDOW_INVALID`
        (HTTP 422)"

        Design: Corner/errors/retro_window_invalid_rejected
        """
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        contract = get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        contract = get_success_data(api.sign_contract(
            contract["id"], make_contract_legal_headers("cl-1")))
        contract = get_success_data(api.begin_configuration(contract["id"], CA))
        resp = api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-09-01",
                retro_effective_date="2026-10-01",
                expected_contract_version=contract["version"]),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_RETRO_WINDOW_INVALID)


class TestCocWindowExceeded:
    def test_treatment_end_not_after_termination_rejected(self, api):
        """PRD §3.9: "The treatment end must fall strictly after the notice's
        `termination_date`; when it does not, no post-termination obligation
        exists and registration fails with `ERR_COC_WINDOW_EXCEEDED` (HTTP 422)."

        Design: Corner/errors/coc_window_exceeded_rejected
        """
        from test_helpers import setup_issued_notice
        artefacts = setup_issued_notice()
        notice_id = artefacts["notice"]["id"]
        from test_helpers import create_continuity_case_payload
        resp = api.create_continuity_case(
            notice_id,
            create_continuity_case_payload(
                member_ref="M1", condition_category="PREGNANCY",
                treatment_end_date="2026-08-01"),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_COC_WINDOW_EXCEEDED)


class TestBatchEmptyScoreRejected:
    def test_score_empty_batch_rejected(self, api):
        """PRD §3.6: "The batch must contain at least one claim in total, failing
        with `ERR_BATCH_EMPTY` (HTTP 422) when empty."

        Design: Corner/errors/batch_empty_score_rejected
        """
        artefacts = setup_contract_in_configuration_with_mapped_version()
        batch = get_success_data(api.create_simulation_batch(
            artefacts["version"]["id"], create_simulation_batch_payload(), CA))
        get_success_data(api.price_batch(batch["id"], CA))
        resp = api.score_batch(batch["id"], CA)
        validate_error(resp, ApiErrorId.ERR_BATCH_EMPTY)


class TestNetworkInactive:
    def test_create_contract_against_retired_network_rejected(self, api):
        """PRD §3.2: "only then is the network required to still be `ACTIVE`,
        failing with `ERR_NETWORK_INACTIVE` (HTTP 422) otherwise."
        PRD §3.1: "Retirement moves a network from `ACTIVE` to `RETIRED` ... and
        forecloses new contract creation against it (§3.2)"

        Design: Corner/errors/network_inactive_rejected
        """
        net = create_network()
        get_success_data(api.retire_network(net["id"], ADMIN))
        prov = create_provider()
        resp = api.create_contract(
            prov["id"], create_contract_payload(network_id=net["id"]), CM)
        validate_error(resp, ApiErrorId.ERR_NETWORK_INACTIVE)


class TestSegregationOfDuties:
    def test_sign_by_submitter_rejected(self, api):
        """PRD §3.3: "the signing caller's `X-User-ID` must differ from the
        contract's recorded `submitted_by_user_id`, so the negotiator who
        submitted the terms can never be the counsel who signs them. A
        same-identity signature is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 409)."

        Design: Corner/errors/segregation_of_duties_rejected
        """
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        # Sign with the same X-User-ID (cm-1), even with the ContractLegal role.
        resp = api.sign_contract(
            contract["id"], make_contract_legal_headers("cm-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_success_data(api.get_contract(contract["id"], ADMIN))
        assert after["contract_status"] == "PENDING_SIGNATURE"


class TestSimulationThresholdNotMet:
    def test_mark_ready_without_passed_batch_rejected(self, api):
        """PRD §3.7: "at least one `PASSED` simulation batch must exist beneath a
        `VALIDATED` version of the contract — its absence fails with
        `ERR_SIMULATION_THRESHOLD_NOT_MET` (HTTP 422)."

        Design: Corner/errors/simulation_threshold_not_met_rejected
        """
        artefacts = setup_contract_in_testing()  # batch created but never scored
        resp = api.mark_ready(artefacts["contract"]["id"], CA)
        validate_error(resp, ApiErrorId.ERR_SIMULATION_THRESHOLD_NOT_MET)


class TestRateParityViolation:
    def _setup_two_contracts(self, api, other_pct_bps):
        """Contract A ACTIVE on PPO at 10000; contract B READY_FOR_GO_LIVE on MA
        at other_pct_bps. Parity rule (PPO, MA, 11000) ACTIVE."""
        net_ppo = create_network(name="PPO-NET", line_of_business="COMMERCIAL_PPO")
        net_ma = create_network(name="MA-NET", line_of_business="MEDICARE_ADVANTAGE")
        create_published_benchmark(hcpcs_code="99213", benchmark_year=2026,
                                   amount_cents=10000)
        from test_helpers import create_parity_rule
        create_parity_rule("COMMERCIAL_PPO", "MEDICARE_ADVANTAGE", 11000)
        prov = create_provider()

        # Contract A to ACTIVE at 10000 (vacuous parity when no other ACTIVE).
        artefacts_a = setup_contract_ready_for_go_live.__wrapped__() if False else None
        # Build A by hand against shared provider / networks.
        contract_a = create_draft_contract(network_id=net_ppo["id"], provider_id=prov["id"])
        contract_a = get_success_data(api.begin_negotiation(contract_a["id"], CM))
        contract_a = get_success_data(api.submit_for_signature(
            contract_a["id"], make_contract_manager_headers("cm-1")))
        contract_a = get_success_data(api.sign_contract(
            contract_a["id"], make_contract_legal_headers("cl-1")))
        contract_a = get_success_data(api.begin_configuration(contract_a["id"], CA))
        version_a = get_success_data(api.create_contract_version(
            contract_a["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract_a["version"]),
            CM,
        ))
        entry_a = get_success_data(api.create_fee_schedule_entry(
            version_a["id"], create_fee_schedule_entry_payload(pct_of_medicare_bps=10000), CA))
        get_success_data(api.map_benchmark(entry_a["id"], CA))
        get_success_data(api.load_version(version_a["id"], CA))
        get_success_data(api.validate_version(version_a["id"], CA))
        get_success_data(api.begin_testing(contract_a["id"], CA))
        batch_a = get_success_data(api.create_simulation_batch(
            version_a["id"], create_simulation_batch_payload(label="BA"), CA))
        get_success_data(api.create_simulation_claim(
            batch_a["id"], create_simulation_claim_payload(), CA))
        get_success_data(api.price_batch(batch_a["id"], CA))
        get_success_data(api.score_batch(batch_a["id"], CA))
        get_success_data(api.mark_ready(contract_a["id"], CA))
        get_success_data(api.approve_go_live(contract_a["id"], ADMIN))

        # Contract B to READY_FOR_GO_LIVE at other_pct_bps.
        contract_b = create_draft_contract(network_id=net_ma["id"], provider_id=prov["id"])
        contract_b = get_success_data(api.begin_negotiation(contract_b["id"], CM))
        contract_b = get_success_data(api.submit_for_signature(
            contract_b["id"], make_contract_manager_headers("cm-1")))
        contract_b = get_success_data(api.sign_contract(
            contract_b["id"], make_contract_legal_headers("cl-1")))
        contract_b = get_success_data(api.begin_configuration(contract_b["id"], CA))
        version_b = get_success_data(api.create_contract_version(
            contract_b["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract_b["version"]),
            CM,
        ))
        entry_b = get_success_data(api.create_fee_schedule_entry(
            version_b["id"],
            create_fee_schedule_entry_payload(pct_of_medicare_bps=other_pct_bps),
            CA,
        ))
        get_success_data(api.map_benchmark(entry_b["id"], CA))
        get_success_data(api.load_version(version_b["id"], CA))
        get_success_data(api.validate_version(version_b["id"], CA))
        get_success_data(api.begin_testing(contract_b["id"], CA))
        batch_b = get_success_data(api.create_simulation_batch(
            version_b["id"], create_simulation_batch_payload(label="BB"), CA))
        get_success_data(api.create_simulation_claim(
            batch_b["id"],
            create_simulation_claim_payload(expected_allowed_cents=other_pct_bps),
            CA,
        ))
        get_success_data(api.price_batch(batch_b["id"], CA))
        get_success_data(api.score_batch(batch_b["id"], CA))
        get_success_data(api.mark_ready(contract_b["id"], CA))
        return contract_b

    def test_parity_violation_rejected(self, api):
        """PRD §3.7: "A quotient strictly greater than the band rejects the entire
        go-live with `ERR_RATE_PARITY_VIOLATION` (HTTP 422)"

        Design: Corner/errors/rate_parity_violation_rejected
        """
        contract_b = self._setup_two_contracts(api, other_pct_bps=11100)
        resp = api.approve_go_live(contract_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RATE_PARITY_VIOLATION)
        after = get_success_data(api.get_contract(contract_b["id"], ADMIN))
        assert after["contract_status"] == "READY_FOR_GO_LIVE"

    def test_parity_exact_band_passes(self, api):
        """PRD §3.7: "a quotient exactly equal to the band passes."

        Design: Corner/errors/parity_exact_band_passes
        """
        contract_b = self._setup_two_contracts(api, other_pct_bps=11000)
        approved = get_success_data(api.approve_go_live(contract_b["id"], ADMIN))
        assert approved["contract_status"] == "ACTIVE"


class TestRunFinalizeBeforeComputeRejected:
    def test_finalize_created_run_rejected(self, api):
        """PRD §3.8: "Finalizing a computed run — again only from `COMPUTED`,
        else `ERR_RUN_INVALID_STATE`"

        Design: Corner/errors/run_finalize_before_compute_rejected
        """
        from test_helpers import setup_contract_with_retro_run
        artefacts = setup_contract_with_retro_run()
        run_id = artefacts["run"]["id"]
        resp = api.finalize_retro_run(run_id, PI)
        validate_error(resp, ApiErrorId.ERR_RUN_INVALID_STATE)
        run = get_success_data(api.get_retro_run(run_id, ADMIN))
        assert run["run_status"] == "CREATED"


class TestFinalizeNoticeBeforeTerminationDateRejected:
    def test_finalize_before_termination_date_rejected(self, api):
        """PRD §3.9: "the notice must be `ISSUED`, and the logical clock's
        current date must be on or after the notice's `termination_date`; an
        early finalization, like any state-mismatched notice action, fails with
        `ERR_NOTICE_INVALID_STATE`."
        PRD §2.6: "Before any clock-setting call, the logical current instant
        defaults to 2026-05-01T00:00:00Z."

        Design: Corner/errors/finalize_notice_before_termination_date_rejected
        """
        from test_helpers import setup_issued_notice
        artefacts = setup_issued_notice()
        # Clock is still the default 2026-05-01 < termination_date 2026-08-15.
        resp = api.finalize_notice(artefacts["notice"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOTICE_INVALID_STATE)
        notice = get_success_data(api.get_termination_notice(artefacts["notice"]["id"], ADMIN))
        assert notice["notice_status"] == "ISSUED"


class TestPublishTwiceRejected:
    def test_publish_published_benchmark_rejected(self, api):
        """PRD §3.1: "attempting to publish a row that is no longer `DRAFT` is
        rejected with `ERR_BENCHMARK_INVALID_STATE` (HTTP 409)"

        Design: Corner/errors/publish_twice_rejected
        """
        bench = create_published_benchmark()
        resp = api.publish_benchmark(bench["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_BENCHMARK_INVALID_STATE)


class TestNotFoundFamily:
    def test_version_get_not_found(self, api):
        """PRD §3.4: "An unresolvable version id anywhere downstream fails with
        `ERR_VERSION_NOT_FOUND`."

        Design: Corner/errors/version_get_returns_not_found
        """
        resp = api.get_contract_version(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VERSION_NOT_FOUND)

    def test_notice_get_not_found(self, api):
        """PRD §3.9: "A notice id that fails to resolve draws
        `ERR_NOTICE_NOT_FOUND`."

        Design: Corner/errors/notice_get_returns_not_found
        """
        resp = api.get_termination_notice(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_FOUND)

    def test_adjustment_get_not_found(self, api):
        """PRD §3.8: "an adjustment id draws `ERR_ADJUSTMENT_NOT_FOUND`"

        Design: Corner/errors/adjustment_get_returns_not_found
        """
        resp = api.get_adjustment(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_NOT_FOUND)


class TestExistenceLeftToRightParentFirst:
    def test_provider_error_wins_over_network(self, api):
        """PRD §2.9: "Each identifier in the path is resolved in sequence, and
        the request is rejected immediately with the not-found error belonging
        to the first identifier that fails to resolve; later segments are never
        consulted."
        PRD §3.2: "the path provider must resolve (`ERR_PROVIDER_NOT_FOUND`),
        the referenced network must resolve (`ERR_NETWORK_NOT_FOUND`)"

        Design: Corner/validations/existence_left_to_right_parent_first
        """
        # Both ids are unknown; the provider (leftmost path segment) wins.
        resp = api.create_contract(
            NON_EXISTENT_UUID,
            create_contract_payload(network_id=NON_EXISTENT_UUID),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_FOUND)


class TestEntryCreateSatisfactionPasses:
    def test_valid_entry_created_staged(self, api):
        """PRD §3.4: "Freshly created entries are `STAGED` (their
        `entry_status`)"

        Design: Corner/validations/entry_create_satisfaction_passes
        """
        net = create_network()
        create_published_benchmark()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        contract = get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        contract = get_success_data(api.sign_contract(
            contract["id"], make_contract_legal_headers("cl-1")))
        contract = get_success_data(api.begin_configuration(contract["id"], CA))
        version = get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract["version"]),
            CM,
        ))
        entry = get_success_data(api.create_fee_schedule_entry(
            version["id"], create_fee_schedule_entry_payload(), CA))
        assert entry["entry_status"] == "STAGED"


class TestProviderRepScopedRead:
    def _setup_two_providers(self, api):
        net = create_network()
        p1 = create_provider(legal_name="Prov A", tin="TIN-1", npi="NPI-1",
                             locality_code="L01")
        contract = create_draft_contract(network_id=net["id"], provider_id=p1["id"])
        p2 = create_provider(legal_name="Prov B", tin="TIN-2", npi="NPI-2",
                             locality_code="L02")
        return p1, p2, contract

    def test_own_contract_readable(self, api):
        """PRD §2.1: "When `X-User-Role` is `ProviderRep`, `X-User-ID` is the `id`
        of the acting `Provider`; ownership checks on any resource that
        references a `Provider` compare the resource's provider chain to
        `X-User-ID`."

        Design: Corner/rbac/provider_rep_scoped_read_own_ok_other_forbidden
        """
        p1, _, contract = self._setup_two_providers(api)
        headers = make_provider_rep_headers(p1["id"])
        fetched = get_success_data(api.get_contract(contract["id"], headers))
        assert fetched["id"] == contract["id"]

    def test_other_provider_contract_forbidden(self, api):
        """PRD §2.1: "On those eight, a `ProviderRep` whose `X-User-ID` does not
        match the resource's provider chain is rejected with
        `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/provider_rep_scoped_read_own_ok_other_forbidden
        """
        p1, p2, contract = self._setup_two_providers(api)
        headers = make_provider_rep_headers(p2["id"])
        resp = api.get_contract(contract["id"], headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


class TestLegalCannotCreateEntry:
    def test_contract_legal_denied_on_entry_create(self, api):
        """PRD §2.1: "A request whose authenticated role is not listed among the
        roles permitted for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST `/contract-versions/{id}/fee-schedule-entries` is
        ConfigurationAnalyst-only.

        Design: Corner/rbac/legal_cannot_create_entry_unauthorized
        """
        payload = create_fee_schedule_entry_payload(
            rate_type="FLAT_RATE", flat_rate_cents=5000)
        payload.pop("pct_of_medicare_bps", None)
        resp = api.create_fee_schedule_entry(NON_EXISTENT_UUID, payload, CL)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestAnalystCannotSettleAdjustment:
    def test_configuration_analyst_denied_on_settle(self, api):
        """PRD §2.1: "A request whose authenticated role is not listed among the
        roles permitted for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST `/retro-adjustments/{id}/settle` is
        PaymentIntegrityAnalyst-only.

        Design: Corner/rbac/analyst_cannot_settle_adjustment_unauthorized
        """
        resp = api.settle_adjustment(NON_EXISTENT_UUID, CA)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOccVersionCreateStaleRejected:
    def test_stale_version_rejected_on_second_create(self, api):
        """PRD §2.7: "If the contract's current `version` has advanced beyond the
        carried value — because any contract-mutating operation completed after
        the client's last read — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412) and nothing is created."

        Design: Corner/cross_cutting_layers/occ_version_create_stale_rejected
        """
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        contract = get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        contract = get_success_data(api.sign_contract(
            contract["id"], make_contract_legal_headers("cl-1")))
        contract = get_success_data(api.begin_configuration(contract["id"], CA))
        observed = contract["version"]
        get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=observed),
            CM,
        ))
        # Second create with the same observed version: stale.
        resp = api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=2, effective_date="2026-09-01",
                expected_contract_version=observed),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        versions = get_success_data(api.list_contract_versions(contract["id"], ADMIN))
        assert all(v["version_number"] != 2 for v in versions)


class TestOccNoticeCreateStaleRejected:
    def test_stale_version_rejected_on_second_notice_create(self, api):
        """PRD §2.7: "If the contract's current `version` has advanced beyond the
        carried value — because any contract-mutating operation completed after
        the client's last read — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412) and nothing is created."

        Design: Corner/cross_cutting_layers/occ_notice_create_stale_rejected
        """
        artefacts = setup_contract_active()
        contract = artefacts["contract"]
        observed = contract["version"]
        n1 = get_success_data(api.create_termination_notice(
            contract["id"],
            create_termination_notice_payload(
                expected_contract_version=observed),
            CM,
        ))
        # Second create with the same observed version: stale.
        resp = api.create_termination_notice(
            contract["id"],
            create_termination_notice_payload(
                termination_date="2026-09-15",
                expected_contract_version=observed),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        notices = get_success_data(api.list_termination_notices(contract["id"], ADMIN))
        assert len(notices) == 1
        assert notices[0]["id"] == n1["id"]


class TestDerivedCountersReconcileOnClaimAdd:
    def test_total_and_pending_rise_per_claim(self, api):
        """PRD §3.6: "every claim added recomputes the batch's `total_claims` and
        `pending_claims`, each rising by one."

        Design: Corner/cross_cutting_layers/derived_counters_reconcile_on_claim_add
        """
        artefacts = setup_contract_in_testing()
        batch_id = artefacts["batch"]["id"]
        get_success_data(api.create_simulation_claim(
            batch_id, create_simulation_claim_payload(service_date="2026-07-15"), CA))
        get_success_data(api.create_simulation_claim(
            batch_id, create_simulation_claim_payload(service_date="2026-07-16"), CA))
        batch = get_success_data(api.get_simulation_batch(batch_id, ADMIN))
        assert batch["total_claims"] == 2
        assert batch["pending_claims"] == 2
        assert batch["matched_claims"] == 0


class TestBenchmarkListFilterByHcpcs:
    def test_filter_returns_only_matching_rows(self, api):
        """PRD §3.1: "The benchmark list supports optional filters on
        `benchmark_year`, `hcpcs_code`, and `locality_code`."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/cross_cutting_layers/benchmark_list_filter_by_hcpcs
        """
        create_published_benchmark(hcpcs_code="99213", amount_cents=10000)
        create_published_benchmark(hcpcs_code="99214", amount_cents=12000)
        resp = api.list_benchmarks(ADMIN, params={"hcpcs_code": "99213"})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["hcpcs_code"] == "99213"


class TestImmediateConsistencyMutationVisibleInResponse:
    def test_begin_negotiation_response_shows_mutation(self, api):
        """PRD §3.3: "Negotiation opens when a `ContractManager` begins
        negotiation on a draft contract, moving `contract_status` from `DRAFT`
        to `IN_NEGOTIATION`, incrementing the contract's `version` by one"
        PRD §2.2: "operations that create or modify a resource will return the
        created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
        """
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        assert contract["version"] == 1
        after = get_success_data(api.begin_negotiation(contract["id"], CM))
        assert after["contract_status"] == "IN_NEGOTIATION"
        assert after["version"] == 2
