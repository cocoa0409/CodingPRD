"""Combinatorial claim-pricing formulas: case-rate outlier branch and per-line rounding."""
from test_helpers import (
    get_success_data,
    create_contract_version_payload, create_fee_schedule_entry_payload,
    create_simulation_batch_payload, create_simulation_claim_payload,
    create_published_benchmark, create_network, create_provider,
    TEST_USERS,
)

ADMIN = TEST_USERS["plan_admin_headers"]
CA = TEST_USERS["configuration_analyst_headers"]
CM = TEST_USERS["contract_manager_headers"]


def _version_with_case_rate_entry(api):
    """Contract in IN_CONFIGURATION with version 1 DRAFT carrying one CASE_RATE
    entry at flat 200000 (mapped)."""
    net = create_network()
    prov = create_provider()
    # PRD 3.4: mapping resolves a PUBLISHED benchmark for the entry's code and
    # the provider's locality under every rate type, so J9999 needs one.
    create_published_benchmark(hcpcs_code="J9999", benchmark_year=2026)
    # Use fixture-less path (helpers above only cover PERCENT_OF_MEDICARE).
    from test_helpers import create_draft_contract  # local import keeps top tidy
    contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
    contract = get_success_data(api.begin_negotiation(contract["id"], CM))
    from test_helpers import make_contract_manager_headers, make_contract_legal_headers
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
            hcpcs_code="J9999", service_category="INPATIENT_SURGERY",
            rate_type="CASE_RATE", flat_rate_cents=200000),
        CA,
    ))
    get_success_data(api.map_benchmark(entry["id"], CA))
    get_success_data(api.load_version(version["id"], CA))
    get_success_data(api.validate_version(version["id"], CA))
    return version["id"]


class TestCaseRateOutlierBranch:
    def _price_four_claims(self, api):
        version_id = _version_with_case_rate_entry(api)
        batch = get_success_data(api.create_simulation_batch(
            version_id, create_simulation_batch_payload(label="BC"), CA))
        claims = {}
        for name, billed in (
            ("below", 500000), ("at", 600000), ("above", 900000), ("cap", 150000),
        ):
            c = get_success_data(api.create_simulation_claim(
                batch["id"],
                create_simulation_claim_payload(
                    hcpcs_code="J9999", service_category="INPATIENT_SURGERY",
                    service_date="2026-08-01", billed_cents=billed,
                    expected_allowed_cents=0),
                CA,
            ))
            claims[name] = c["id"]
        get_success_data(api.price_batch(batch["id"], CA))
        priced = {c["id"]: c for c in get_success_data(api.list_simulation_claims(batch["id"], ADMIN))}
        return claims, priced

    def test_below_threshold_and_at_threshold_take_base(self, api):
        """PRD §3.6: "when the billed charge multiplied by ten thousand strictly
        exceeds thirty thousand times the base — an exact integer comparison in
        which a billed charge of exactly three times the base does not qualify —
        ... when the threshold is not crossed, the base stands"

        Design: Difficulty/combinatorial_formula/case_rate_outlier_branch
        """
        claims, priced = self._price_four_claims(api)
        # below: 500000*10000 = 5e9 not > 30000*200000 = 6e9 -> base 200000.
        assert priced[claims["below"]]["priced_allowed_cents"] == 200000
        # at: 600000*10000 == 6e9, strictly-greater false -> base 200000.
        assert priced[claims["at"]]["priced_allowed_cents"] == 200000

    def test_above_threshold_and_cap_binds(self, api):
        """PRD §3.6: "the excess is the billed charge minus the threshold amount
        (the threshold being thirty thousand basis points of the base, rounded
        half up to whole cents), and the line amount becomes the base plus 80.00%
        of that excess, the share itself rounded half up to whole cents"
        PRD §3.6: "in both sub-cases the result is capped at the billed charge,
        the lesser of the two amounts prevailing."

        Design: Difficulty/combinatorial_formula/case_rate_outlier_branch
        """
        claims, priced = self._price_four_claims(api)
        # above: 200000 + round_half_up((900000-600000) * 8000 / 10000) = 440000.
        assert priced[claims["above"]]["priced_allowed_cents"] == 440000
        # cap binds: min(200000, 150000) = 150000.
        assert priced[claims["cap"]]["priced_allowed_cents"] == 150000


class TestPerLineThenSumRounding:
    def _setup_batch_with_three_rounding_claims(self, api):
        net = create_network()
        bench = create_published_benchmark(
            hcpcs_code="X0001", benchmark_year=2026, amount_cents=10001)
        prov = create_provider()
        from test_helpers import create_draft_contract, make_contract_manager_headers, make_contract_legal_headers
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
            version["id"],
            create_fee_schedule_entry_payload(
                hcpcs_code="X0001", service_category="LAB",
                rate_type="PERCENT_OF_MEDICARE", pct_of_medicare_bps=8000),
            CA,
        ))
        get_success_data(api.map_benchmark(entry["id"], CA))
        get_success_data(api.load_version(version["id"], CA))
        get_success_data(api.validate_version(version["id"], CA))
        batch = get_success_data(api.create_simulation_batch(
            version["id"], create_simulation_batch_payload(label="BR"), CA))
        claim_ids = []
        for d in ("2026-08-01", "2026-08-02", "2026-08-03"):
            c = get_success_data(api.create_simulation_claim(
                batch["id"],
                create_simulation_claim_payload(
                    hcpcs_code="X0001", service_category="LAB",
                    service_date=d, billed_cents=999999,
                    expected_allowed_cents=8001),
                CA,
            ))
            claim_ids.append(c["id"])
        return batch["id"], claim_ids

    def test_per_line_rounding_produces_8001_each(self, api):
        """PRD §2.5: "every claim line is rounded to whole cents on its own, and
        batch totals are produced by summing the already-rounded line values;
        summing unrounded values and rounding the total is never used."

        Design: Difficulty/combinatorial_formula/per_line_then_sum_rounding
        """
        batch_id, claim_ids = self._setup_batch_with_three_rounding_claims(api)
        get_success_data(api.price_batch(batch_id, CA))
        priced = {c["id"]: c for c in get_success_data(api.list_simulation_claims(batch_id, ADMIN))}
        for cid in claim_ids:
            assert priced[cid]["priced_allowed_cents"] == 8001
            assert priced[cid]["claim_outcome"] == "MATCH"

    def test_batch_total_sums_already_rounded_lines(self, api):
        """PRD §2.5: "every claim line is rounded to whole cents on its own, and
        batch totals are produced by summing the already-rounded line values;
        summing unrounded values and rounding the total is never used."
        PRD §3.6: "the batch's `total_priced_cents` is the sum of the
        already-rounded `priced_allowed_cents` values over claims whose outcome
        is `MATCH` or `MISMATCH`"

        Design: Difficulty/combinatorial_formula/per_line_then_sum_rounding
        """
        batch_id, _ = self._setup_batch_with_three_rounding_claims(api)
        priced_batch = get_success_data(api.price_batch(batch_id, CA))
        # 3 * round_half_up(10001*8000/10000) = 3 * 8001 = 24003; sum-then-round
        # would give 24002 and is explicitly not used.
        assert priced_batch["total_priced_cents"] == 24003
