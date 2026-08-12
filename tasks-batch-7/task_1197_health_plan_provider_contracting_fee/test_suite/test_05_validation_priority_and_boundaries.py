"""Validation priority pairs and boundary precision checks."""
from test_helpers import (
    get_success_data, validate_error,
    ApiErrorId,
    create_contract_version_payload, create_fee_schedule_entry_payload,
    create_paid_claim_payload, create_parity_rule, create_simulation_batch_payload,
    create_simulation_claim_payload, create_termination_notice_payload,
    create_published_benchmark, create_network, create_provider,
    setup_contract_active, setup_contract_in_testing,
    setup_contract_ready_for_go_live,
    TEST_USERS,
    make_contract_legal_headers, make_contract_manager_headers,
)

ADMIN = TEST_USERS["plan_admin_headers"]
CA = TEST_USERS["configuration_analyst_headers"]
CM = TEST_USERS["contract_manager_headers"]
PI = TEST_USERS["payment_integrity_headers"]


def _drive_contract_to_in_testing_with_rate(api, provider_id, network_id,
                                            pct_of_medicare_bps, expected_priced):
    """Walk a contract to IN_TESTING with a VALIDATED version at the given pct."""
    from test_helpers import create_draft_contract
    contract = create_draft_contract(network_id=network_id, provider_id=provider_id)
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
        version["id"],
        create_fee_schedule_entry_payload(
            hcpcs_code="99213", rate_type="PERCENT_OF_MEDICARE",
            pct_of_medicare_bps=pct_of_medicare_bps),
        CA,
    ))
    get_success_data(api.map_benchmark(entry["id"], CA))
    get_success_data(api.load_version(version["id"], CA))
    get_success_data(api.validate_version(version["id"], CA))
    get_success_data(api.begin_testing(contract["id"], CA))
    return contract, version


class TestStateOverFiscalOnGoLive:
    def _setup(self, api):
        """Contract A ACTIVE on PPO at 10000; contract B in IN_TESTING on MA at
        11100; ACTIVE parity rule (PPO, MA, band 11000)."""
        net_ppo = create_network(name="PPO-NET", line_of_business="COMMERCIAL_PPO")
        net_ma = create_network(name="MA-NET", line_of_business="MEDICARE_ADVANTAGE")
        create_published_benchmark(hcpcs_code="99213", benchmark_year=2026,
                                   amount_cents=10000)
        create_parity_rule("COMMERCIAL_PPO", "MEDICARE_ADVANTAGE", 11000)
        prov = create_provider()

        # Contract A to ACTIVE at 10000.
        contract_a, version_a = _drive_contract_to_in_testing_with_rate(
            api, prov["id"], net_ppo["id"], 10000, 10000)
        batch_a = get_success_data(api.create_simulation_batch(
            version_a["id"], create_simulation_batch_payload(label="BA"), CA))
        get_success_data(api.create_simulation_claim(
            batch_a["id"],
            create_simulation_claim_payload(
                service_date="2026-07-15", expected_allowed_cents=10000), CA))
        get_success_data(api.price_batch(batch_a["id"], CA))
        get_success_data(api.score_batch(batch_a["id"], CA))
        get_success_data(api.mark_ready(contract_a["id"], CA))
        get_success_data(api.approve_go_live(contract_a["id"], ADMIN))

        # Contract B in IN_TESTING at 11100 (would fail parity; state also wrong).
        contract_b, _ = _drive_contract_to_in_testing_with_rate(
            api, prov["id"], net_ma["id"], 11100, 11100)
        return contract_b

    def test_state_error_wins_over_parity_when_both_fail(self, api):
        """PRD §2.10: "6. **State preconditions and optimistic concurrency** ... 11.
        **Fiscal gates** — rate parity at go-live (`ERR_RATE_PARITY_VIOLATION`)"
        PRD §3.7: "The contract must stand `READY_FOR_GO_LIVE`
        (`ERR_CONTRACT_INVALID_STATE` otherwise), after which rate parity
        evaluation runs to completion before any activation occurs."

        Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_on_go_live
        """
        contract_b = self._setup(api)
        resp = api.approve_go_live(contract_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_INVALID_STATE)
        after = get_success_data(api.get_contract(contract_b["id"], ADMIN))
        assert after["contract_status"] == "IN_TESTING"

    def test_state_precondition_evaluated_before_parity_check(self, api):
        """PRD §3.7: "The contract must stand `READY_FOR_GO_LIVE`
        (`ERR_CONTRACT_INVALID_STATE` otherwise), after which rate parity
        evaluation runs to completion before any activation occurs."

        Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_on_go_live
        """
        contract_b = self._setup(api)
        # Repeated: the same request repeatedly returns the state error.
        resp = api.approve_go_live(contract_b["id"], ADMIN)
        data = validate_error(resp, ApiErrorId.ERR_CONTRACT_INVALID_STATE)
        assert data["error_id"] == "ERR_CONTRACT_INVALID_STATE"


class TestSafetyOverReferentialOnEntryCreate:
    def _setup_in_configuration(self, api):
        from test_helpers import create_draft_contract
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
        return version["id"]

    def test_rate_floor_fires_when_benchmark_also_unresolvable(self, api):
        """PRD §2.10: "7. **Business safety** — the regulatory rate floor
        (`ERR_RATE_BELOW_FLOOR`) ... 10. **Referential business rules** —
        benchmark resolvable at entry creation (`ERR_BENCHMARK_UNRESOLVABLE`)"
        PRD §3.4: "the regulatory floor then requires a percent-of-Medicare
        entry's `pct_of_medicare_bps` to be at least 8,000 basis points — 80.00%
        of the Medicare benchmark — with violations rejected as
        `ERR_RATE_BELOW_FLOOR` (HTTP 422), a duplicate `hcpcs_code` on the
        version draws `ERR_DUPLICATE_SERVICE_CODE` (HTTP 409), and last, for
        percent-of-Medicare entries only, at least one Medicare benchmark row of
        any status must exist for the entry's code and the provider's locality,
        failing with `ERR_BENCHMARK_UNRESOLVABLE` (HTTP 422) when none does."

        Design: Difficulty/priority_pair_validation_conflict/safety_over_referential_on_entry_create
        """
        version_id = self._setup_in_configuration(api)
        resp = api.create_fee_schedule_entry(
            version_id,
            create_fee_schedule_entry_payload(
                hcpcs_code="ZZZZZ", rate_type="PERCENT_OF_MEDICARE",
                pct_of_medicare_bps=7000),
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_BELOW_FLOOR)

    def test_rate_floor_error_is_422(self, api):
        """PRD §3.4: "with violations rejected as `ERR_RATE_BELOW_FLOOR`
        (HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/safety_over_referential_on_entry_create
        """
        version_id = self._setup_in_configuration(api)
        resp = api.create_fee_schedule_entry(
            version_id,
            create_fee_schedule_entry_payload(
                hcpcs_code="ZZZZZ", rate_type="PERCENT_OF_MEDICARE",
                pct_of_medicare_bps=7000),
            CA,
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["data"]["error_id"] == "ERR_RATE_BELOW_FLOOR"


class TestPassRateExactlyAtThreshold:
    def _setup_batch(self, api, match_count, mismatch_count):
        """Batch with the given number of MATCH/MISMATCH claims, priced."""
        artefacts = setup_contract_in_testing()
        batch_id = artefacts["batch"]["id"]
        for i in range(match_count):
            get_success_data(api.create_simulation_claim(
                batch_id, create_simulation_claim_payload(
                    service_date=f"2026-07-{10 + i:02d}", expected_allowed_cents=10000), CA))
        for i in range(mismatch_count):
            get_success_data(api.create_simulation_claim(
                batch_id, create_simulation_claim_payload(
                    service_date=f"2026-08-{10 + i:02d}", expected_allowed_cents=9999), CA))
        get_success_data(api.price_batch(batch_id, CA))
        return batch_id

    def test_exactly_at_threshold_passes(self, api):
        """PRD §3.6: "The batch passes when `matched_claims` multiplied by ten
        thousand is at least the priced population multiplied by 7,500 basis
        points (75.00%): an exact integer comparison with no division and no
        rounding, under which a match share exactly equal to the threshold passes."

        Design: Difficulty/boundary_precision_check/pass_rate_exactly_at_threshold
        """
        batch_id = self._setup_batch(api, match_count=3, mismatch_count=1)
        scored = get_success_data(api.score_batch(batch_id, CA))
        # 3*10000 >= 4*7500 -> 30000 >= 30000 -> PASSED
        assert scored["batch_status"] == "PASSED"

    def test_one_below_threshold_fails(self, api):
        """PRD §3.6: "The batch passes when `matched_claims` multiplied by ten
        thousand is at least the priced population multiplied by 7,500 basis
        points (75.00%)"

        Design: Difficulty/boundary_precision_check/pass_rate_exactly_at_threshold
        """
        batch_id = self._setup_batch(api, match_count=2, mismatch_count=2)
        scored = get_success_data(api.score_batch(batch_id, CA))
        # 2*10000 < 4*7500 -> 20000 < 30000 -> FAILED
        assert scored["batch_status"] == "FAILED"


class TestNoticePeriodExactly90Days:
    def test_exactly_90_days_accepted(self, api):
        """PRD §3.9: "the notice period is measured in whole days from
        `notice_date` to `termination_date` and must be at least ninety — exactly
        ninety days is accepted, eighty-nine is rejected with
        `ERR_NOTICE_PERIOD_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/notice_period_exactly_90_days
        """
        artefacts = setup_contract_active()
        contract = artefacts["contract"]
        # 2026-05-01 to 2026-07-30 == 90 days.
        notice = get_success_data(api.create_termination_notice(
            contract["id"],
            create_termination_notice_payload(
                notice_date="2026-05-01", termination_date="2026-07-30",
                expected_contract_version=contract["version"]),
            CM,
        ))
        assert notice["notice_status"] == "DRAFT"

    def test_89_days_rejected(self, api):
        """PRD §3.9: "the notice period is measured in whole days from
        `notice_date` to `termination_date` and must be at least ninety — exactly
        ninety days is accepted, eighty-nine is rejected with
        `ERR_NOTICE_PERIOD_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/notice_period_exactly_90_days
        """
        artefacts = setup_contract_active()
        contract = artefacts["contract"]
        # 2026-05-01 to 2026-07-29 == 89 days.
        resp = api.create_termination_notice(
            contract["id"],
            create_termination_notice_payload(
                notice_date="2026-05-01", termination_date="2026-07-29",
                expected_contract_version=contract["version"]),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_NOTICE_PERIOD_INSUFFICIENT)
