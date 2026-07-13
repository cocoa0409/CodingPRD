"""Excise tax computation across the CBMA reduced/standard tiers."""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_completed_run,
    create_tax_removal_payload,
)

_OC = TEST_USERS["compliance_headers"]


def _completed_run(api, permit):
    """A COMPLETED 10-case run with 11.9 bottled proof gallons."""
    return setup_completed_run(api, dsp_permit_number=permit, planned_cases=10, fill_proof_gallons=15)


class TestExciseReducedVsStandard:
    def test_excise_reduced_rate_regime(self, api):
        """PRD 3.6: "The `excise_tax_due_cents` is `reduced_rate_pg` multiplied by the
        reduced rate of 270 cents per proof gallon plus `standard_rate_pg` multiplied
        by the standard rate of 1,350 cents per proof gallon, rounded half-up to whole
        cents." PRD 3.6: "`removed_proof_gallons` is the run's `bottled_proof_gallons`
        multiplied by `removed_cases` divided by the run's `cases_bottled`, rounded to
        the nearest tenth using round-half-up."

        Design: Difficulty/dual_variant_calc/excise_reduced_vs_standard_rate_diverge
        """
        ctx = _completed_run(api, "DSP-EX-1")
        removal = get_success_data(
            api.create_tax_removal(
                create_tax_removal_payload(ctx["bottling_run"]["id"], removal_reason="TAXPAID", removed_cases=3),
                _OC,
            )
        )
        assert removal["removed_proof_gallons"] == 3.6
        assert removal["excise_tax_due_cents"] == 972

    def test_excise_standard_rate_regime(self, api):
        """PRD 3.6: "The portion taxed at the reduced rate, `reduced_rate_pg`, is the
        smaller of `removed_proof_gallons` and the remaining reduced-rate headroom —
        that is, 100,000 proof gallons minus the current `cbma_pg_removed_ytd` — but
        never less than zero. The remainder, `standard_rate_pg`, is
        `removed_proof_gallons` minus `reduced_rate_pg`."

        Design: Difficulty/dual_variant_calc/excise_reduced_vs_standard_rate_diverge
        """
        ctx = _completed_run(api, "DSP-EX-2")
        api.set_cbma_ytd(ctx["distillery_id"], 100000, _OC)
        removal = get_success_data(
            api.create_tax_removal(
                create_tax_removal_payload(ctx["bottling_run"]["id"], removal_reason="TAXPAID", removed_cases=3),
                _OC,
            )
        )
        assert removal["removed_proof_gallons"] == 3.6
        assert removal["excise_tax_due_cents"] == 4860


class TestExciseTierSplitAcrossLimit:
    def test_tier_split_proof_gallons(self, api):
        """PRD 3.6: "The portion taxed at the reduced rate, `reduced_rate_pg`, is the
        smaller of `removed_proof_gallons` and the remaining reduced-rate headroom —
        that is, 100,000 proof gallons minus the current `cbma_pg_removed_ytd`".

        Design: Difficulty/combinatorial_formula/excise_tiered_rate_split_across_cbma_limit
        """
        ctx = _completed_run(api, "DSP-EX-3")
        api.set_cbma_ytd(ctx["distillery_id"], 99998.0, _OC)
        removal = get_success_data(
            api.create_tax_removal(
                create_tax_removal_payload(ctx["bottling_run"]["id"], removal_reason="TAXPAID", removed_cases=5),
                _OC,
            )
        )
        assert removal["removed_proof_gallons"] == 6.0
        assert removal["reduced_rate_pg"] == 2.0
        assert removal["standard_rate_pg"] == 4.0

    def test_tier_split_excise_amount(self, api):
        """PRD 3.6: "The `excise_tax_due_cents` is `reduced_rate_pg` multiplied by the
        reduced rate of 270 cents per proof gallon plus `standard_rate_pg` multiplied
        by the standard rate of 1,350 cents per proof gallon, rounded half-up to whole
        cents."

        Design: Difficulty/combinatorial_formula/excise_tiered_rate_split_across_cbma_limit
        """
        ctx = _completed_run(api, "DSP-EX-4")
        api.set_cbma_ytd(ctx["distillery_id"], 99998.0, _OC)
        removal = get_success_data(
            api.create_tax_removal(
                create_tax_removal_payload(ctx["bottling_run"]["id"], removal_reason="TAXPAID", removed_cases=5),
                _OC,
            )
        )
        assert removal["excise_tax_due_cents"] == 5940


class TestCbmaBoundary:
    def test_boundary_100000th_pg_reduced_split(self, api):
        """PRD 2.6: "A distillery's `cbma_rate_tier` is `REDUCED` while
        `cbma_pg_removed_ytd` is below 100,000 proof gallons, and `STANDARD` once
        `cbma_pg_removed_ytd` reaches or exceeds 100,000 proof gallons." PRD 3.6:
        "`reduced_rate_pg`, is the smaller of `removed_proof_gallons` and the
        remaining reduced-rate headroom".

        Design: Difficulty/boundary_precision_check/cbma_limit_100000th_pg_is_reduced
        """
        ctx = _completed_run(api, "DSP-EX-5")
        api.set_cbma_ytd(ctx["distillery_id"], 99999.5, _OC)
        removal = get_success_data(
            api.create_tax_removal(
                create_tax_removal_payload(ctx["bottling_run"]["id"], removal_reason="TAXPAID", removed_cases=5),
                _OC,
            )
        )
        assert removal["reduced_rate_pg"] == 0.5
        assert removal["standard_rate_pg"] == 5.5
        assert removal["excise_tax_due_cents"] == 7560

    def test_boundary_crossing_flips_rate_tier(self, api):
        """PRD 3.6: "its `cbma_pg_removed_ytd` is increased by `removed_proof_gallons`,
        its `cbma_rate_tier` is recomputed against the 100,000 proof-gallon boundary".
        PRD 2.6: "`STANDARD` once `cbma_pg_removed_ytd` reaches or exceeds 100,000
        proof gallons."

        Design: Difficulty/boundary_precision_check/cbma_limit_100000th_pg_is_reduced
        """
        ctx = _completed_run(api, "DSP-EX-6")
        api.set_cbma_ytd(ctx["distillery_id"], 99999.5, _OC)
        api.create_tax_removal(
            create_tax_removal_payload(ctx["bottling_run"]["id"], removal_reason="TAXPAID", removed_cases=5),
            _OC,
        )
        d = validate_success(api.get_distillery(ctx["distillery_id"], _OC))
        assert d["cbma_rate_tier"] == "STANDARD"
