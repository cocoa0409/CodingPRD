"""Corner coverage: state machine transitions, invalid and terminal paths."""
from test_helpers import (
    get_success_data, validate_error,
    ApiErrorId,
    add_continuity_case,
    create_carve_out_payload, create_contract_version_payload,
    create_fee_schedule_entry_payload, create_simulation_batch_payload,
    create_simulation_claim_payload, create_termination_notice_payload,
    create_draft_contract, create_network, create_provider,
    create_published_benchmark,
    make_contract_legal_headers, make_contract_manager_headers,
    setup_contract_active, setup_contract_in_configuration_with_mapped_version,
    setup_contract_in_testing, setup_contract_ready_for_go_live,
    setup_contract_with_retro_run, setup_issued_notice, set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["plan_admin_headers"]
CA = TEST_USERS["configuration_analyst_headers"]
CM = TEST_USERS["contract_manager_headers"]
PI = TEST_USERS["payment_integrity_headers"]


class TestSignFromDraftRejected:
    def test_sign_on_draft_rejected(self, api):
        """PRD §3.3: "the contract must first be in `PENDING_SIGNATURE`
        (`ERR_CONTRACT_INVALID_STATE` otherwise)"

        Design: Corner/state_machines/sign_from_draft_rejected
        """
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        resp = api.sign_contract(contract["id"], make_contract_legal_headers("cl-1"))
        validate_error(resp, ApiErrorId.ERR_CONTRACT_INVALID_STATE)
        after = get_success_data(api.get_contract(contract["id"], ADMIN))
        assert after["contract_status"] == "DRAFT"


class TestTerminatedContractRejectsBeginNegotiation:
    def test_begin_negotiation_after_termination_rejected(self, api):
        """PRD §3.9: "the contract moves from `TERMINATION_NOTICE` to `TERMINATED`
        — its terminal state"
        PRD §3.3: "Every lifecycle action described in this section — and every
        later one — first requires the contract to be in the state that permits
        it; a mismatched state is rejected with `ERR_CONTRACT_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/terminated_contract_rejects_begin_negotiation
        """
        artefacts = setup_issued_notice()
        set_clock("2026-08-15T00:00:00Z")
        get_success_data(api.finalize_notice(artefacts["notice"]["id"], ADMIN))
        resp = api.begin_negotiation(artefacts["contract"]["id"], CM)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_INVALID_STATE)
        after = get_success_data(api.get_contract(artefacts["contract"]["id"], ADMIN))
        assert after["contract_status"] == "TERMINATED"


class TestSettleAfterRejectRejected:
    def test_settle_after_reject_rejected(self, api):
        """PRD §3.8: "rejecting moves it to `REJECTED`"; PRD §3.8: "Settling an
        `APPROVED` adjustment pays by direction"; PRD §3.8: "`PAID`, `RECOVERED`,
        `REJECTED`, and `VOIDED` are an adjustment's [terminal states]."

        Design: Corner/state_machines/settle_after_reject_rejected
        """
        artefacts = setup_contract_with_retro_run(
            claim_specs=[
                {"claim_number": "CLM-1", "service_date": "2026-08-10",
                 "billed_cents": 15000, "paid_cents": 10000},
                {"claim_number": "CLM-2", "service_date": "2026-08-20",
                 "billed_cents": 20000, "paid_cents": 15000},
            ],
        )
        run_id = artefacts["run"]["id"]
        get_success_data(api.compute_retro_run(run_id, PI))
        adjustments = get_success_data(api.list_run_adjustments(run_id, PI))
        adj1 = adjustments[0]
        rejected = get_success_data(api.reject_adjustment(adj1["id"], PI))
        assert rejected["adjustment_status"] == "REJECTED"
        resp = api.settle_adjustment(adj1["id"], PI)
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_INVALID_STATE)
        after = get_success_data(api.get_adjustment(adj1["id"], ADMIN))
        assert after["adjustment_status"] == "REJECTED"


class TestScoreTwiceRejected:
    def test_second_score_on_passed_batch_rejected(self, api):
        """PRD §3.6: "Scoring turns a priced batch into a verdict and is permitted
        only from `PRICED` (any other state draws `ERR_BATCH_INVALID_STATE`)."
        PRD §3.6: "A passing batch moves from `PRICED` to `PASSED`"

        Design: Corner/state_machines/score_twice_rejected
        """
        artefacts = setup_contract_in_testing()
        batch_id = artefacts["batch"]["id"]
        get_success_data(api.create_simulation_claim(
            batch_id, create_simulation_claim_payload(), CA))
        get_success_data(api.price_batch(batch_id, CA))
        scored = get_success_data(api.score_batch(batch_id, CA))
        assert scored["batch_status"] == "PASSED"
        resp = api.score_batch(batch_id, CA)
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE)


class TestMapAfterLockRejected:
    def test_map_benchmark_after_lock_rejected(self, api):
        """PRD §3.4: "A `ConfigurationAnalyst` maps an entry whose `entry_status`
        is `STAGED` — any other entry state fails with `ERR_ENTRY_INVALID_STATE`
        (HTTP 409)"
        PRD §3.4: "when at least one entry exists and every entry has reached
        `MAPPED`, the version becomes `VALIDATED`, every mapped entry cascades
        from `MAPPED` to `LOCKED`"

        Design: Corner/state_machines/map_after_lock_rejected
        """
        artefacts = setup_contract_in_configuration_with_mapped_version()
        entry = artefacts["entry"]
        # After validation, the entry is LOCKED.
        locked = get_success_data(api.get_entry(entry["id"], ADMIN))
        assert locked["entry_status"] == "LOCKED"
        resp = api.map_benchmark(entry["id"], CA)
        validate_error(resp, ApiErrorId.ERR_ENTRY_INVALID_STATE)
        after = get_success_data(api.get_entry(entry["id"], ADMIN))
        assert after["entry_status"] == "LOCKED"


class TestInitialStatesAcrossEntities:
    def test_contract_and_version_and_entry_initial_states(self, api):
        """PRD §3.2: "A new contract begins with `contract_status` set to `DRAFT`"
        PRD §3.4: "A successfully created version begins with `version_status`
        set to `DRAFT`"
        PRD §3.4: "Freshly created entries are `STAGED` (their `entry_status`)"

        Design: Corner/state_machines/initial_states_across_entities
        """
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        assert contract["contract_status"] == "DRAFT"
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
        assert version["version_status"] == "DRAFT"
        entry = get_success_data(api.create_fee_schedule_entry(
            version["id"],
            create_fee_schedule_entry_payload(
                rate_type="FLAT_RATE", flat_rate_cents=5000),
            CA,
        ))
        assert entry["entry_status"] == "STAGED"


class TestRunAutoSettlesOnLastAdjustment:
    def test_run_settles_after_last_adjustment_paid(self, api):
        """PRD §3.8: "while the run is `FINALIZED`, the moment no adjustment
        remains in `PROPOSED` or `APPROVED` — the last non-terminal adjustment
        having just settled or been rejected — the run advances itself from
        `FINALIZED` to `SETTLED` and appends `RETRO_RUN_SETTLED`."
        PRD §3.8: "an `UNDERPAID` adjustment settles to `PAID`"

        Design: Corner/state_machines/run_auto_settles_on_last_adjustment
        """
        artefacts = setup_contract_with_retro_run()  # default: one CLM-1 +2000
        run_id = artefacts["run"]["id"]
        get_success_data(api.compute_retro_run(run_id, PI))
        get_success_data(api.finalize_retro_run(run_id, PI))
        adjustments = get_success_data(api.list_run_adjustments(run_id, PI))
        adj = adjustments[0]
        get_success_data(api.approve_adjustment(adj["id"], PI))
        settled = get_success_data(api.settle_adjustment(adj["id"], PI))
        assert settled["adjustment_status"] == "PAID"
        run = get_success_data(api.get_retro_run(run_id, ADMIN))
        assert run["run_status"] == "SETTLED"


class TestRescindRestoresActiveAndClosesCases:
    def test_rescind_returns_contract_and_closes_cases(self, api):
        """PRD §3.9: "the notice becomes `RESCINDED`, appending `NOTICE_RESCINDED`,
        and the compensating cascade returns the contract from
        `TERMINATION_NOTICE` to `ACTIVE`, increments its `version`, appends
        `TERMINATION_NOTICE_RESCINDED`, and closes every continuity case of the
        notice standing `IDENTIFIED` or `NOTIFIED` by moving it to
        `CLOSED_RESCINDED`."

        Design: Corner/state_machines/rescind_restores_active_and_closes_cases
        """
        artefacts = setup_issued_notice()
        notice = artefacts["notice"]
        case = add_continuity_case(notice["id"])
        get_success_data(api.notify_case(case["id"], CM))

        rescinded = get_success_data(api.rescind_notice(notice["id"], CM))
        assert rescinded["notice_status"] == "RESCINDED"
        contract = get_success_data(api.get_contract(artefacts["contract"]["id"], ADMIN))
        assert contract["contract_status"] == "ACTIVE"
        case_after = get_success_data(api.get_continuity_case(case["id"], ADMIN))
        assert case_after["case_status"] == "CLOSED_RESCINDED"


class TestValidateRejectedThenReloadLoop:
    def test_rejected_version_can_be_reloaded_and_validated(self, api):
        """PRD §3.4: "when the version holds zero entries or any entry is still
        `STAGED`, the version becomes `REJECTED` and `VERSION_REJECTED` is
        appended. A rejected version is not dead: loading it again returns it
        from `REJECTED` to `DRAFT` for correction (appending `VERSION_RELOADED`),
        from which a further load returns it to `LOADED`."

        Design: Corner/state_machines/validate_rejected_then_reload_loop
        """
        net = create_network()
        bench = create_published_benchmark()
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
        get_success_data(api.load_version(version["id"], CA))

        rejected = get_success_data(api.validate_version(version["id"], CA))
        assert rejected["version_status"] == "REJECTED"
        back_to_draft = get_success_data(api.load_version(version["id"], CA))
        assert back_to_draft["version_status"] == "DRAFT"
        get_success_data(api.map_benchmark(entry["id"], CA))
        loaded = get_success_data(api.load_version(version["id"], CA))
        assert loaded["version_status"] == "LOADED"
        validated = get_success_data(api.validate_version(version["id"], CA))
        assert validated["version_status"] == "VALIDATED"
        locked = get_success_data(api.get_entry(entry["id"], ADMIN))
        assert locked["entry_status"] == "LOCKED"
