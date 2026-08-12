"""Dual-variant calculations: escalator compounding modes and benchmark lookup modes."""
import pytest

from test_helpers import (
    validate_error, validate_success, get_success_data,
    ApiErrorId,
    create_benchmark_payload, create_contract_payload,
    create_contract_version_payload, create_fee_schedule_entry_payload,
    create_network_payload, create_provider_payload, create_simulation_batch_payload,
    create_simulation_claim_payload,
    make_contract_legal_headers, make_contract_manager_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["plan_admin_headers"]
CA = TEST_USERS["configuration_analyst_headers"]
CM = TEST_USERS["contract_manager_headers"]


def _drive_to_in_configuration(api, provider_id, network_id, escalator_mode):
    """Helper: create contract, walk DRAFT -> IN_CONFIGURATION, return contract."""
    contract = get_success_data(api.create_contract(
        provider_id,
        create_contract_payload(network_id=network_id, escalator_bps=300,
                                escalator_mode=escalator_mode),
        CM,
    ))
    contract = get_success_data(api.begin_negotiation(contract["id"], CM))
    contract = get_success_data(api.submit_for_signature(
        contract["id"], make_contract_manager_headers("cm-1")))
    contract = get_success_data(api.sign_contract(
        contract["id"], make_contract_legal_headers("cl-1")))
    contract = get_success_data(api.begin_configuration(contract["id"], CA))
    return contract


def _build_version_batch_with_claim(api, contract_id, claim_id="ignored"):
    """Helper: version + entry + map + load + validate + batch + one claim priced
    at service_date 2027-06-15. Returns (batch_id, claim_id)."""
    contract = get_success_data(api.get_contract(contract_id, ADMIN))
    version = get_success_data(api.create_contract_version(
        contract_id,
        create_contract_version_payload(
            version_number=1, effective_date="2026-07-01",
            expected_contract_version=contract["version"]),
        CM,
    ))
    entry = get_success_data(api.create_fee_schedule_entry(
        version["id"],
        create_fee_schedule_entry_payload(
            hcpcs_code="99213", rate_type="PERCENT_OF_MEDICARE",
            pct_of_medicare_bps=10000),
        CA,
    ))
    get_success_data(api.map_benchmark(entry["id"], CA))
    get_success_data(api.load_version(version["id"], CA))
    get_success_data(api.validate_version(version["id"], CA))
    batch = get_success_data(api.create_simulation_batch(
        version["id"], create_simulation_batch_payload(label="B"), CA))
    claim = get_success_data(api.create_simulation_claim(
        batch["id"],
        create_simulation_claim_payload(
            service_date="2027-06-15", billed_cents=15000,
            expected_allowed_cents=0),
        CA,
    ))
    return batch["id"], claim["id"]


class TestEscalatorAnniversaryVsCalendar:
    def test_anniversary_mode_counts_zero_steps_for_pre_anniversary_date(self, api):
        """PRD §3.4: "Under `ANNIVERSARY`, the count is the number of completed
        anniversaries of the version's `effective_date` that fall on or before the
        service date."
        PRD §3.4: "for a version effective 2026-07-01 and a service date of
        2027-06-15, `ANNIVERSARY` counts zero steps (the first anniversary,
        2027-07-01, has not yet arrived)"

        Design: Difficulty/dual_variant_calc/escalator_anniversary_vs_calendar
        """
        net = get_success_data(api.create_network(create_network_payload(), ADMIN))
        bench = get_success_data(api.create_benchmark(create_benchmark_payload(), ADMIN))
        get_success_data(api.publish_benchmark(bench["id"], ADMIN))
        prov = get_success_data(api.create_provider(create_provider_payload(), ADMIN))

        contract = _drive_to_in_configuration(api, prov["id"], net["id"], "ANNIVERSARY")
        batch_id, claim_id = _build_version_batch_with_claim(api, contract["id"])

        get_success_data(api.price_batch(batch_id, CA))
        claims = get_success_data(api.list_simulation_claims(batch_id, ADMIN))
        claim = next(c for c in claims if c["id"] == claim_id)
        # escalator 300 bps but 0 steps -> base rate unchanged at 10000.
        assert claim["priced_allowed_cents"] == 10000

    def test_calendar_mode_counts_one_step_for_next_year(self, api):
        """PRD §3.4: "Under `CALENDAR`, the count is the service date's calendar
        year minus the effective date's calendar year."
        PRD §3.4: "while `CALENDAR` counts one, so identical contract data prices
        the same claim differently under the two modes."

        Design: Difficulty/dual_variant_calc/escalator_anniversary_vs_calendar
        """
        net = get_success_data(api.create_network(create_network_payload(), ADMIN))
        bench = get_success_data(api.create_benchmark(create_benchmark_payload(), ADMIN))
        get_success_data(api.publish_benchmark(bench["id"], ADMIN))
        prov = get_success_data(api.create_provider(create_provider_payload(), ADMIN))

        contract = _drive_to_in_configuration(api, prov["id"], net["id"], "CALENDAR")
        batch_id, claim_id = _build_version_batch_with_claim(api, contract["id"])

        get_success_data(api.price_batch(batch_id, CA))
        claims = get_success_data(api.list_simulation_claims(batch_id, ADMIN))
        claim = next(c for c in claims if c["id"] == claim_id)
        # 1 step of 3%: round_half_up(10000 * 1.03) = 10300.
        assert claim["priced_allowed_cents"] == 10300


class TestBenchmarkStrictVsProvisional:
    def _setup_2027_version(self, api):
        """Version effective 2027-01-01 with benchmarks PUBLISHED only for 2026.
        Returns (version_id, strict_entry_id, provisional_entry_id, benchmark_2026_id)."""
        net = get_success_data(api.create_network(create_network_payload(), ADMIN))
        b13 = get_success_data(api.create_benchmark(create_benchmark_payload(
            benchmark_year=2026, hcpcs_code="99213", benchmark_amount_cents=10000), ADMIN))
        get_success_data(api.publish_benchmark(b13["id"], ADMIN))
        b14 = get_success_data(api.create_benchmark(create_benchmark_payload(
            benchmark_year=2026, hcpcs_code="99214", benchmark_amount_cents=12000), ADMIN))
        get_success_data(api.publish_benchmark(b14["id"], ADMIN))
        prov = get_success_data(api.create_provider(create_provider_payload(), ADMIN))
        contract = _drive_to_in_configuration(api, prov["id"], net["id"], "ANNIVERSARY")
        contract = get_success_data(api.get_contract(contract["id"], ADMIN))
        version = get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2027-01-01",
                expected_contract_version=contract["version"]),
            CM,
        ))
        return version["id"], b14["id"]

    def test_strict_lookup_rejects_when_year_not_published(self, api):
        """PRD §3.4: "Under `STRICT`, only rows whose `benchmark_year` equals the
        calendar year of the version's `effective_date` survive — an unpublished
        year is an error, never a fallback."
        PRD §3.4: "An empty candidate set — under either mode — is rejected with
        `ERR_BENCHMARK_UNPUBLISHED` (HTTP 422)."

        Design: Difficulty/dual_variant_calc/benchmark_strict_vs_provisional
        """
        version_id, _ = self._setup_2027_version(api)
        strict_entry = get_success_data(api.create_fee_schedule_entry(
            version_id,
            create_fee_schedule_entry_payload(
                hcpcs_code="99213", rate_type="PERCENT_OF_MEDICARE",
                pct_of_medicare_bps=10000, benchmark_lookup_mode="STRICT"),
            CA,
        ))
        resp = api.map_benchmark(strict_entry["id"], CA)
        validate_error(resp, ApiErrorId.ERR_BENCHMARK_UNPUBLISHED)
        entry = get_success_data(api.get_entry(strict_entry["id"], ADMIN))
        assert entry["entry_status"] == "STAGED"

    def test_provisional_lookup_falls_back_to_latest_prior_year(self, api):
        """PRD §3.4: "Under `PROVISIONAL`, rows whose `benchmark_year` is no
        later than the effective year survive, ranked by year descending with
        the most recent taken; the composite uniqueness of year, locality, and
        code makes ties impossible, and no id-based tiebreak is ever used."

        Design: Difficulty/dual_variant_calc/benchmark_strict_vs_provisional
        """
        version_id, bench_2026_id = self._setup_2027_version(api)
        prov_entry = get_success_data(api.create_fee_schedule_entry(
            version_id,
            create_fee_schedule_entry_payload(
                hcpcs_code="99214", rate_type="PERCENT_OF_MEDICARE",
                pct_of_medicare_bps=10000, benchmark_lookup_mode="PROVISIONAL"),
            CA,
        ))
        mapped = get_success_data(api.map_benchmark(prov_entry["id"], CA))
        assert mapped["entry_status"] == "MAPPED"
        assert mapped["computed_rate_cents"] == 12000
        assert mapped["medicare_benchmark_id"] == bench_2026_id
