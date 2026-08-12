"""Corner coverage: calculations (mapping, floor, carve-out overrides, per-diem, EXCLUDE)."""
from test_helpers import (
    get_success_data, validate_error,
    ApiErrorId,
    create_carve_out_payload, create_fee_schedule_entry_payload,
    create_simulation_batch_payload, create_simulation_claim_payload,
    create_published_benchmark, create_network, create_provider,
    create_draft_contract,
    make_contract_legal_headers, make_contract_manager_headers,
    setup_contract_in_configuration_with_mapped_version,
    TEST_USERS,
)

ADMIN = TEST_USERS["plan_admin_headers"]
CA = TEST_USERS["configuration_analyst_headers"]
CL = TEST_USERS["contract_legal_headers"]
CM = TEST_USERS["contract_manager_headers"]


def _draft_version(api, with_benchmark=True):
    """(version_id, benchmark_id) — contract in IN_CONFIGURATION, version 1 DRAFT."""
    net = create_network()
    bench = create_published_benchmark() if with_benchmark else None
    prov = create_provider()
    contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
    contract = get_success_data(api.begin_negotiation(contract["id"], CM))
    contract = get_success_data(api.submit_for_signature(
        contract["id"], make_contract_manager_headers("cm-1")))
    contract = get_success_data(api.sign_contract(
        contract["id"], make_contract_legal_headers("cl-1")))
    contract = get_success_data(api.begin_configuration(contract["id"], CA))
    from test_helpers import create_contract_version_payload
    version = get_success_data(api.create_contract_version(
        contract["id"],
        create_contract_version_payload(
            version_number=1, effective_date="2026-07-01",
            expected_contract_version=contract["version"]),
        CM,
    ))
    return version["id"], (bench["id"] if bench else None)


class TestPercentMappingExactLiteral:
    def test_pct_mapping_computes_rate(self, api):
        """PRD §3.4: "for percent-of-Medicare entries, the resolved benchmark
        cents multiplied by `pct_of_medicare_bps` and divided by ten thousand,
        rounded half up to whole cents"
        PRD §3.4: "The entry advances from `STAGED` to `MAPPED`."

        Design: Corner/calculations/percent_mapping_exact_literal
        """
        version_id, _ = _draft_version(api)
        entry = get_success_data(api.create_fee_schedule_entry(
            version_id, create_fee_schedule_entry_payload(), CA))
        mapped = get_success_data(api.map_benchmark(entry["id"], CA))
        assert mapped["computed_rate_cents"] == 10000
        assert mapped["entry_status"] == "MAPPED"


class TestRateFloorBoundary:
    def test_pct_7999_rejected(self, api):
        """PRD §3.4: "the regulatory floor then requires a percent-of-Medicare
        entry's `pct_of_medicare_bps` to be at least 8,000 basis points — 80.00%
        of the Medicare benchmark — with violations rejected as
        `ERR_RATE_BELOW_FLOOR` (HTTP 422)"

        Design: Corner/calculations/rate_floor_boundary_7999_rejected_8000_accepted
        """
        version_id, _ = _draft_version(api)
        resp = api.create_fee_schedule_entry(
            version_id,
            create_fee_schedule_entry_payload(hcpcs_code="99213", pct_of_medicare_bps=7999),
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_BELOW_FLOOR)

    def test_pct_8000_accepted(self, api):
        """PRD §3.4: "the regulatory floor then requires a percent-of-Medicare
        entry's `pct_of_medicare_bps` to be at least 8,000 basis points — 80.00%
        of the Medicare benchmark"
        PRD §2.5: "the regulatory floor of 8,000 basis points is 80.00% of the
        Medicare benchmark."

        Design: Corner/calculations/rate_floor_boundary_7999_rejected_8000_accepted
        """
        version_id, _ = _draft_version(api, with_benchmark=False)
        # Publish a benchmark for a different code so resolvability is satisfiable
        create_published_benchmark(hcpcs_code="99214", benchmark_year=2026,
                                   amount_cents=12000)
        entry = get_success_data(api.create_fee_schedule_entry(
            version_id,
            create_fee_schedule_entry_payload(hcpcs_code="99214", pct_of_medicare_bps=8000),
            CA,
        ))
        assert entry["entry_status"] == "STAGED"


class TestCarveOutOverrideFlatReplacesEntryRate:
    def test_flat_carve_out_overrides_entry_rate(self, api):
        """PRD §3.6: "A `FLAT_RATE` selection sets the line's allowed amount to
        `override_flat_cents` and proceeds to rounding."

        Design: Corner/calculations/carve_out_override_flat_replaces_entry_rate
        """
        artefacts = setup_contract_in_configuration_with_mapped_version(
            carve_outs=[dict(
                service_category="OFFICE_VISIT", override_type="FLAT_RATE",
                override_flat_cents=7777, start_date="2026-07-01",
                end_date="2026-12-31", priority_rank=1)],
        )
        version_id = artefacts["version"]["id"]
        batch = get_success_data(api.create_simulation_batch(
            version_id, create_simulation_batch_payload(label="B1"), CA))
        get_success_data(api.create_simulation_claim(
            batch["id"],
            create_simulation_claim_payload(
                service_date="2026-08-01", expected_allowed_cents=7777),
            CA,
        ))
        priced = get_success_data(api.price_batch(batch["id"], CA))
        assert priced["matched_claims"] == 1


class TestCarveOutWildcardPriorityRankWins:
    def test_lower_priority_rank_wins_over_specific(self, api):
        """PRD §3.5: "a `priority_rank` under which a lower number wins when
        several carve-outs match the same claim, with ties broken by earlier
        `created_at`"
        PRD §3.5: "the literal value `"*"` acts as a wildcard matching any
        claim's category at pricing time"

        Design: Corner/calculations/carve_out_wildcard_priority_rank_wins
        """
        artefacts = setup_contract_in_configuration_with_mapped_version(
            carve_outs=[
                dict(service_category="OFFICE_VISIT", override_type="FLAT_RATE",
                     override_flat_cents=7777, start_date="2026-07-01",
                     end_date="2026-12-31", priority_rank=2),
                dict(service_category="*", override_type="FLAT_RATE",
                     override_flat_cents=5555, start_date="2026-07-01",
                     end_date="2026-12-31", priority_rank=1),
            ],
        )
        version_id = artefacts["version"]["id"]
        batch = get_success_data(api.create_simulation_batch(
            version_id, create_simulation_batch_payload(label="B1"), CA))
        claim = get_success_data(api.create_simulation_claim(
            batch["id"],
            create_simulation_claim_payload(
                service_date="2026-08-01", expected_allowed_cents=0),
            CA,
        ))
        get_success_data(api.price_batch(batch["id"], CA))
        claims = get_success_data(api.list_simulation_claims(batch["id"], ADMIN))
        priced = next(c for c in claims if c["id"] == claim["id"])
        assert priced["priced_allowed_cents"] == 5555


class TestPerDiemMultipliesLos:
    def test_per_diem_multiplies_los_days(self, api):
        """PRD §3.6: "per-diem entries multiply the projected base by the claim's
        `los_days`"

        Design: Corner/calculations/per_diem_multiplies_los
        """
        version_id, _ = _draft_version(api, with_benchmark=False)
        # PRD 3.4: mapping resolves a PUBLISHED benchmark for the entry's code
        # and the provider's locality under every rate type, so DRG1 needs one.
        create_published_benchmark(hcpcs_code="DRG1", benchmark_year=2026)
        entry = get_success_data(api.create_fee_schedule_entry(
            version_id,
            create_fee_schedule_entry_payload(
                hcpcs_code="DRG1", service_category="INPATIENT_MEDICAL",
                rate_type="PER_DIEM", flat_rate_cents=30000),
            CA,
        ))
        get_success_data(api.map_benchmark(entry["id"], CA))
        get_success_data(api.load_version(version_id, CA))
        get_success_data(api.validate_version(version_id, CA))
        batch = get_success_data(api.create_simulation_batch(
            version_id, create_simulation_batch_payload(label="B1"), CA))
        get_success_data(api.create_simulation_claim(
            batch["id"],
            create_simulation_claim_payload(
                hcpcs_code="DRG1", service_category="INPATIENT_MEDICAL",
                service_date="2026-08-01", billed_cents=200000,
                expected_allowed_cents=120000, los_days=4),
            CA,
        ))
        priced = get_success_data(api.price_batch(batch["id"], CA))
        assert priced["matched_claims"] == 1
        assert priced["mismatched_claims"] == 0


class TestExcludeCarveOutMarksClaimExcluded:
    def test_exclude_carve_out_excluded_and_not_counted(self, api):
        """PRD §3.6: "An `EXCLUDE` selection ends the line immediately: the claim
        becomes `EXCLUDED` and its `priced_allowed_cents` stays null."
        PRD §3.6: "The priced population counts matched plus mismatched claims
        only — excluded and pending claims never enter either side of the
        comparison."

        Design: Corner/calculations/exclude_carve_out_marks_claim_excluded
        """
        artefacts = setup_contract_in_configuration_with_mapped_version(
            carve_outs=[dict(
                service_category="OFFICE_VISIT", override_type="EXCLUDE",
                start_date="2026-07-01", end_date="2026-12-31", priority_rank=1)],
        )
        version_id = artefacts["version"]["id"]
        batch = get_success_data(api.create_simulation_batch(
            version_id, create_simulation_batch_payload(label="B1"), CA))
        # In-window claim -> EXCLUDED.
        excluded_claim = get_success_data(api.create_simulation_claim(
            batch["id"],
            create_simulation_claim_payload(
                service_date="2026-08-01", expected_allowed_cents=0),
            CA,
        ))
        # Out-of-window claim -> MATCH (2027-02-01 outside carve-out window).
        get_success_data(api.create_simulation_claim(
            batch["id"],
            create_simulation_claim_payload(
                service_date="2027-02-01", expected_allowed_cents=10000),
            CA,
        ))
        priced = get_success_data(api.price_batch(batch["id"], CA))
        assert priced["excluded_claims"] == 1
        assert priced["matched_claims"] == 1
        claims = get_success_data(api.list_simulation_claims(batch["id"], ADMIN))
        ex = next(c for c in claims if c["id"] == excluded_claim["id"])
        assert ex["claim_outcome"] == "EXCLUDED"
        assert ex["priced_allowed_cents"] is None
        # Scoring: 1 MATCH, 0 MISMATCH -> 1*10000 >= 1*7500 -> PASSED.
        scored = get_success_data(api.score_batch(batch["id"], CA))
        assert scored["batch_status"] == "PASSED"
