"""Dual-variant assessment: the parameter set that governs a seal classification
and the tonnage basis that governs a tax credit.

Both concerns store two figures on the same row and let a nominated variant
decide which of them drives the regulated outcome — the seal integrity indices on
a geologic model revision, and the reported and verified tonnages on a tax credit
claim.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import constants, factories, fixtures


def _two_models_differing_only_in_variant(api):
    """Register two model revisions identical in every geologic input.

    The two revisions differ only in the `assessment_variant` they nominate, so
    the classification each one lands on is attributable to the variant alone.
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    deterministic = fixtures.register_geologic_model(
        api,
        project["id"],
        project["version"],
        model_label="M1-DET",
        assessment_variant="DETERMINISTIC",
    )
    project = fixtures.refresh_project(api, project["id"])
    probabilistic = fixtures.register_geologic_model(
        api,
        project["id"],
        project["version"],
        model_label="M1-P10",
        assessment_variant="PROBABILISTIC_P10",
    )
    return deterministic, probabilistic


def test_seal_classification_deterministic_variant_bands_pass(
    api, project_developer_headers
):
    """Under the deterministic parameter set, the seal capacity is `capillary_entry_pressure_psi` multiplied by the ratio of `seal_thickness_m` to the reference seal thickness of 30.0 metres, and `seal_integrity_index` is that capacity divided by the simulated pressure buildup multiplied by the deterministic safety factor of 1.0, rounded half up to 3 decimal places.
    Both indices are always computed and both are always stored and returned, whatever the model's `assessment_variant`.
    The governing index is banded as `PASS` when it is at least 1.500, `CONDITIONAL` when it is at least 1.000 but below 1.500, and `FAIL` when it is below 1.000.
    Completing the simulation moves `plume_status` from `NOT_RUN` to `SIMULATED` and bumps the model's `version`.

    Design: Difficulty/dual_variant_calc/seal_integrity_index_variant_flips_pass_to_fail
    """
    deterministic, probabilistic = _two_models_differing_only_in_variant(api)

    simulated = validate_success(
        api.run_plume_simulation(
            deterministic["id"],
            factories.run_plume_simulation_payload(constants.DEFAULT_INJECTION_YEARS),
            project_developer_headers,
        )
    )
    validate_success(
        api.run_plume_simulation(
            probabilistic["id"],
            factories.run_plume_simulation_payload(constants.DEFAULT_INJECTION_YEARS),
            project_developer_headers,
        )
    )

    assert simulated["seal_integrity_index"] == 1.600
    assert simulated["seal_integrity_index_p10"] == 0.498
    assert simulated["seal_classification"] == "PASS"

    deterministic = fixtures.refresh_model(api, deterministic["id"])
    assert deterministic["seal_integrity_index"] == 1.600
    assert deterministic["seal_integrity_index_p10"] == 0.498
    assert deterministic["seal_classification"] == "PASS"
    assert deterministic["plume_status"] == "SIMULATED"

    probabilistic = fixtures.refresh_model(api, probabilistic["id"])
    assert probabilistic["plume_status"] == "SIMULATED"


def test_seal_classification_probabilistic_variant_bands_fail(
    api, project_developer_headers
):
    """Under the probabilistic parameter set, the conservative seal capacity is `p10_capillary_entry_pressure_psi` multiplied by the ratio of `p10_seal_thickness_m` to the same reference thickness of 30.0 metres, and `seal_integrity_index_p10` is that conservative capacity divided by the simulated pressure buildup multiplied by the probabilistic safety factor of 1.25, rounded half up to 3 decimal places.
    `seal_classification` bands whichever index the `assessment_variant` nominates — `seal_integrity_index` when the variant is `DETERMINISTIC`, `seal_integrity_index_p10` when it is `PROBABILISTIC_P10` — and never a blend of the two.
    The governing index is banded as `PASS` when it is at least 1.500, `CONDITIONAL` when it is at least 1.000 but below 1.500, and `FAIL` when it is below 1.000.
    The largest annual rate the confining zone tolerates, `max_injection_rate_tpy`, is that allowable buildup multiplied by `permeability_md`, multiplied by `porosity_fraction`, multiplied by 1000, divided by the injection buildup coefficient of 45.0, and then floored to a whole number of tonnes.
    The model's own `aor_radius_km` takes the larger of those two radii, multiplies it by 10.0, rounds that product *up* to the next whole number, and divides by 10.0 — in other words, the area-of-review radius is the greater of the free-phase plume and pressure-front radii, rounded up to the next tenth of a kilometre.

    Design: Difficulty/dual_variant_calc/seal_integrity_index_variant_flips_pass_to_fail
    """
    deterministic, probabilistic = _two_models_differing_only_in_variant(api)

    validate_success(
        api.run_plume_simulation(
            deterministic["id"],
            factories.run_plume_simulation_payload(constants.DEFAULT_INJECTION_YEARS),
            project_developer_headers,
        )
    )
    simulated = validate_success(
        api.run_plume_simulation(
            probabilistic["id"],
            factories.run_plume_simulation_payload(constants.DEFAULT_INJECTION_YEARS),
            project_developer_headers,
        )
    )

    assert simulated["seal_integrity_index"] == 1.600
    assert simulated["seal_integrity_index_p10"] == 0.498
    assert simulated["seal_classification"] == "FAIL"

    probabilistic = fixtures.refresh_model(api, probabilistic["id"])
    assert probabilistic["seal_integrity_index"] == 1.600
    assert probabilistic["seal_integrity_index_p10"] == 0.498
    assert probabilistic["seal_classification"] == "FAIL"
    assert probabilistic["max_injection_rate_tpy"] == 1200000
    assert probabilistic["aor_radius_km"] == 3.0

    deterministic = fixtures.refresh_model(api, deterministic["id"])
    assert deterministic["max_injection_rate_tpy"] == 1200000
    assert deterministic["aor_radius_km"] == 3.0


def _draft_claim_on_a_populated_ledger(api):
    """Carry a project to an active well, two reported periods and a draft claim."""
    ctx = fixtures.setup_project_with_ledger(api)
    return fixtures.setup_draft_tax_credit_claim(
        api,
        ctx,
        tax_year=constants.TAX_YEAR,
        claim_variant="REPORTED",
        lca_upstream_emissions_factor=constants.LCA_UPSTREAM_EMISSIONS_FACTOR,
    )


def test_tax_credit_reported_basis_credits_the_gross_tonnage(
    api, project_developer_headers
):
    """`reported_tonnes` is the sum of `mass_injected_tonnes` over that window, rounded half up to 3 decimal places.
    The rate is tiered on the project's ledger rather than on the claim's own tonnage, and it degrades as the project stores more: `credit_rate_usd_per_tonne` is 85.00 dollars per tonne while the project's `cumulative_stored_tonnes` is at most 500,000 tonnes, 70.00 dollars per tonne while it exceeds 500,000 but is at most 2,000,000 tonnes, and 55.00 dollars per tonne once it exceeds 2,000,000 tonnes.
    `credit_amount_usd` is the basis multiplied by `credit_rate_usd_per_tonne`, rounded half up to 2 decimal places, where the basis is `reported_tonnes` when the claim's `claim_variant` is `REPORTED` and `verified_tonnes` when it is `VERIFIED`.
    The `REPORTED` basis is the gross figure — no leakage subtraction and no lifecycle deduction — and it is the basis in force while the claim's `status` is `DRAFT` or `SUBMITTED`.
    Submission recomputes all four derived claim figures on the current ledger, records the developer's `X-User-ID` in `submitted_by_user_id`, moves the claim `DRAFT → SUBMITTED`, recomputes the project's `pending_credit_usd` as the sum of `credit_amount_usd` over the project's claims whose `status` is `SUBMITTED` or `ALLOWED`, and bumps both the claim's `version` and the project's `version`.

    Design: Difficulty/dual_variant_calc/tax_credit_reported_vs_verified_basis_divergence
    """
    ctx = _draft_claim_on_a_populated_ledger(api)

    claim = validate_success(
        api.submit_tax_credit_claim(
            ctx["claim"]["id"],
            {"submission_note": "secure geologic storage report for 2027"},
            project_developer_headers,
        )
    )

    assert claim["reported_tonnes"] == 550000.000
    assert claim["credit_rate_usd_per_tonne"] == 70.00
    assert claim["credit_amount_usd"] == 38500000.00
    assert claim["status"] == "SUBMITTED"

    project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project["cumulative_stored_tonnes"] == 549500.000


def test_tax_credit_verified_basis_nets_leakage_and_lifecycle_deduction(
    api, independent_verifier_headers
):
    """The lifecycle deduction is `reported_tonnes` multiplied by the claim's `lca_upstream_emissions_factor`, rounded half up to 3 decimal places.
    `verified_tonnes` is `reported_tonnes` less the leakage total less the lifecycle deduction, rounded half up to 3 decimal places.
    The `VERIFIED` basis nets out both the measured leakage and the lifecycle deduction, so whenever either the leakage total or the `lca_upstream_emissions_factor` is non-zero the allowed credit is strictly smaller than the credit as submitted.
    Allowing sets the claim's `claim_variant` to `VERIFIED`, recomputes `credit_amount_usd` on the verified tonnage basis, records the verifier's `X-User-ID` in `verifier_user_id`, and moves the claim `SUBMITTED → ALLOWED`.
    Both are terminal, both recompute the project's `pending_credit_usd`, and both bump the claim's `version` and the project's `version`.

    Design: Difficulty/dual_variant_calc/tax_credit_reported_vs_verified_basis_divergence
    """
    ctx = _draft_claim_on_a_populated_ledger(api)
    ctx = fixtures.setup_submitted_tax_credit_claim(api, ctx)
    credit_as_submitted = ctx["claim"]["credit_amount_usd"]
    assert credit_as_submitted == 38500000.00

    claim = validate_success(
        api.verify_tax_credit_claim(
            ctx["claim"]["id"],
            {"decision": "ALLOW", "verification_note": "lifecycle analysis accepted"},
            independent_verifier_headers,
        )
    )

    assert claim["reported_tonnes"] == 550000.000
    assert claim["verified_tonnes"] == 522000.000
    assert claim["credit_rate_usd_per_tonne"] == 70.00
    assert claim["credit_amount_usd"] == 36540000.00
    assert claim["claim_variant"] == "VERIFIED"
    assert claim["status"] == "ALLOWED"
    assert round(credit_as_submitted - claim["credit_amount_usd"], 2) == 1960000.00

    project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project["pending_credit_usd"] == 36540000.00
