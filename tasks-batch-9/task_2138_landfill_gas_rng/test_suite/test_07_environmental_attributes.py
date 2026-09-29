"""Environmental attributes: D3 RIN and LCFS generation, the basis that decides
which energy figure is used, stewardship, and the conserved RIN ledger."""

from test_helpers import (
    OFFICER_ALICE,
    ApiErrorId,
    approx_2dp,
    approx_3dp,
    approx_4dp,
    assert_attribute_batch,
    assert_energy_balance_read,
    create_attribute_batch_payload,
    fixtures,
    make_compliance_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = make_compliance_officer_headers(OFFICER_ALICE)


class TestAttributeBasis:
    def test_provisional_and_settled_metered_bases_yield_different_rin_counts(
        self, api, scheduler_headers
    ):
        """PRD §3.8: "`energy_basis_mmbtu` is the MMBtu quantity the attributes are
        actually computed from: it is the source batch's `gross_mmbtu` when the `basis`
        is `PROVISIONAL_NOMINATED`, and the source batch's `metered_mmbtu` when the
        `basis` is `SETTLED_METERED`. Because the pipeline's meter and the plant's own
        calculation disagree in practice, the same injection batch yields materially
        different attribute quantities under the two bases, which is exactly why the
        basis is recorded on the row."
        PRD §3.8: "For the `RIN_D3` program, `rin_count` is the energy basis multiplied
        by 11.727 RINs per MMBtu and then multiplied by the eligibility factor, with the
        result **truncated toward zero** to a whole number — partial RINs do not exist and
        are never rounded up."
        PRD §3.5: "A plant with no closed downtime records in the month-to-date window
        therefore reports 100.00."

        Design: Difficulty/dual_variant_calc/rin_provisional_nominated_vs_settled_metered_basis
        """
        context = fixtures.setup_injected_batch()
        batch_id = context["batch"]["id"]

        provisional = validate_success(
            api.create_attribute_batch(
                create_attribute_batch_payload(batch_id, program="RIN_D3"), OFFICER
            ),
            201,
        )
        assert_attribute_batch(provisional)
        assert provisional["basis"] == "PROVISIONAL_NOMINATED"
        assert provisional["energy_basis_mmbtu"] == approx_2dp(340.14)
        assert provisional["eligibility_factor"] == approx_4dp(1.0)
        assert provisional["rin_count"] == 3988

        validate_success(
            api.meter_trueup(batch_id, {"metered_mmbtu": 352.40}, scheduler_headers)
        )
        source = fixtures.read_injection_batch(batch_id)
        assert source["gross_mmbtu"] == approx_2dp(340.14)
        assert source["metered_mmbtu"] == approx_2dp(352.40)

        validate_success(
            api.set_attribute_batch_status(
                provisional["id"],
                {"to_status": "REVERSED", "reason": "BASIS_RESTATEMENT"},
                OFFICER,
            )
        )

        settled = validate_success(
            api.create_attribute_batch(
                create_attribute_batch_payload(
                    batch_id, program="RIN_D3", basis="SETTLED_METERED"
                ),
                OFFICER,
            ),
            201,
        )
        assert settled["basis"] == "SETTLED_METERED"
        assert settled["energy_basis_mmbtu"] == approx_2dp(352.40)
        assert settled["rin_count"] == 4132
        assert settled["rin_count"] != provisional["rin_count"], (
            "the same injected volume mints a different number of RINs on each basis"
        )

    def test_settled_metered_regeneration_leaves_the_site_rin_ledger_consistent(
        self, api, scheduler_headers
    ):
        """PRD §3.8: "Generating D3 RINs raises the site's `rin_generated_total` and its
        `rin_available_count`, each by the batch's `rin_count`."
        PRD §3.8: "What reversal never does is reduce `rin_generated_total` — that
        counter is monotonic by design, which is what keeps the identity of §2.8 true
        across generate, retire and reverse in any order."

        Design: Difficulty/dual_variant_calc/rin_provisional_nominated_vs_settled_metered_basis
        """
        context = fixtures.setup_injected_batch()
        batch_id = context["batch"]["id"]
        site_id = context["site"]["id"]

        provisional = fixtures.generate_attribute_batch(batch_id, program="RIN_D3")
        validate_success(
            api.meter_trueup(batch_id, {"metered_mmbtu": 352.40}, scheduler_headers)
        )
        validate_success(
            api.set_attribute_batch_status(
                provisional["id"],
                {"to_status": "REVERSED", "reason": "BASIS_RESTATEMENT"},
                OFFICER,
            )
        )
        settled = fixtures.generate_attribute_batch(
            batch_id, program="RIN_D3", basis="SETTLED_METERED"
        )
        assert settled["rin_count"] == 4132

        site = fixtures.read_site(site_id)
        assert site["rin_generated_total"] == 3988 + 4132
        assert site["rin_available_count"] == 4132
        assert site["rin_reversed_count"] == 3988
        assert site["rin_retired_count"] == 0


class TestLcfsWaterfall:
    def test_avoided_methane_tier_is_selected_from_the_pre_credit_intensity(self, api):
        """PRD §3.8: "Step two selects the avoided-methane credit **from the pre-credit
        intensity, not from the final one**: a pre-credit intensity below 20.000 earns a
        credit of 22.500, one below 40.000 earns 15.000, and anything at or above 40.000
        earns 7.500."
        PRD §3.8: "To make the pinning unambiguous: a site with a clean ledger and no
        flaring has a pre-credit intensity of 44.000, which lands in the highest tier and
        earns a credit of 7.500, giving a project intensity of 36.500. Re-selecting the
        tier from 36.500 would earn 15.000 and yield 29.000 — a materially larger credit —
        and that is **not** what this system computes."
        PRD §3.8: "Step four converts energy and produces the credits: the energy in
        megajoules is the energy basis multiplied by 1055.06 and rounded half up to two
        decimal places, and `lcfs_credits` is the benchmark carbon intensity of 91.980
        less the project intensity, multiplied by the compressed-natural-gas energy
        economy ratio of 0.90, multiplied by the energy in megajoules, divided by one
        million, and rounded half up to four decimal places."

        Design: Difficulty/combinatorial_formula/lcfs_avoided_methane_tier_selected_from_ci_pre_mode_c
        """
        context = fixtures.setup_injected_batch()

        credits = validate_success(
            api.create_attribute_batch(
                create_attribute_batch_payload(
                    context["batch"]["id"], program="LCFS"
                ),
                OFFICER,
            ),
            201,
        )
        assert credits["energy_basis_mmbtu"] == approx_2dp(340.14)
        assert credits["ci_project_gco2e_per_mj"] == approx_3dp(36.500)
        assert credits["ci_project_gco2e_per_mj"] != approx_3dp(29.000), (
            "re-selecting the tier from the post-credit intensity is not the rule"
        )
        assert credits["lcfs_credits"] == approx_4dp(17.9190)
        assert credits["status"] == "GENERATED"

    def test_lcfs_generation_moves_no_rin_counter(self, api):
        """PRD §3.8: "For this program `rin_count` is 0. LCFS generation moves no RIN
        counter on the site."
        PRD §3.8: "The row is created in `status` `PENDING` and auto-advances to
        `GENERATED` inside the same request, with every computed figure populated on the
        way through."

        Design: Difficulty/combinatorial_formula/lcfs_avoided_methane_tier_selected_from_ci_pre_mode_c
        """
        context = fixtures.setup_injected_batch()

        credits = validate_success(
            api.create_attribute_batch(
                create_attribute_batch_payload(
                    context["batch"]["id"], program="LCFS"
                ),
                OFFICER,
            ),
            201,
        )
        assert credits["status"] == "GENERATED"
        assert credits["rin_count"] == 0

        site = fixtures.read_site(context["site"]["id"])
        assert site["rin_generated_total"] == 0
        assert site["rin_available_count"] == 0

    def test_flare_penalty_raises_the_project_carbon_intensity(self, api):
        """PRD §3.8: "Step one derives a flare penalty from the site's **current** energy
        ledger: the denominator is the site's `energy_injected_mmbtu` plus its
        `energy_flared_mmbtu`; the flare fraction is 0.0000 when that denominator is zero
        and otherwise the site's `energy_flared_mmbtu` divided by that denominator,
        rounded half up to four decimal places; the flare penalty is that fraction
        multiplied by 60.000, rounded half up to three decimal places; and the pre-credit
        carbon intensity is the baseline landfill-gas RNG figure of 44.000 grams of
        carbon dioxide equivalent per megajoule plus that penalty, rounded half up to
        three decimal places."

        Design: Corner/calculations/lcfs_flare_penalty_raises_project_ci_when_half_the_gas_is_flared
        """
        context = fixtures.setup_injected_batch()
        plant_id = context["plant"]["id"]

        flared = fixtures.create_batch(
            plant_id,
            interval_start="2026-08-10T06:00:00Z",
            interval_end="2026-08-10T09:00:00Z",
        )
        fixtures.analyse_batch(flared["id"])
        fixtures.divert_batch(flared["id"])

        site = fixtures.read_site(context["site"]["id"])
        assert site["energy_injected_mmbtu"] == approx_2dp(340.14)
        assert site["energy_flared_mmbtu"] == approx_2dp(340.14)
        assert site["energy_produced_mmbtu"] == approx_2dp(680.28)

        credits = validate_success(
            api.create_attribute_batch(
                create_attribute_batch_payload(
                    context["batch"]["id"], program="LCFS"
                ),
                OFFICER,
            ),
            201,
        )
        # flare fraction 0.5000 -> penalty 30.000 -> ci_pre 74.000 -> ci_project 66.500
        assert credits["ci_project_gco2e_per_mj"] == approx_3dp(66.500)
        assert credits["lcfs_credits"] == approx_4dp(8.2296)
        assert credits["rin_count"] == 0
        assert credits["status"] == "GENERATED"


class TestEligibilityFactor:
    def test_eligibility_factor_tracks_the_plants_availability_factor(self, api):
        """PRD §3.8: "`eligibility_factor` is the producing plant's
        `availability_factor_pct` divided by 100 and rounded half up to four decimal
        places, captured at the instant of generation and never restated afterwards — a
        plant that later suffers an outage does not retroactively devalue attributes
        already generated."
        PRD §3.8: "For the `RIN_D3` program, `rin_count` is the energy basis multiplied
        by 11.727 RINs per MMBtu and then multiplied by the eligibility factor, with the
        result **truncated toward zero** to a whole number — partial RINs do not exist and
        are never rounded up."

        Design: Corner/calculations/rin_eligibility_factor_tracks_plant_availability_factor
        """
        context = fixtures.setup_injected_batch(clock="2026-08-11T00:00:00Z")
        plant_id = context["plant"]["id"]

        # 780 minutes of closed downtime in a 14400-minute month-to-date window.
        fixtures.create_closed_downtime(
            plant_id,
            "2026-08-02T00:00:00Z",
            "2026-08-02T13:00:00Z",
            cause="COMPRESSOR_TRIP",
            disposition="FLARED",
        )
        plant = fixtures.read_plant(plant_id)
        assert plant["availability_factor_pct"] == approx_2dp(94.58)

        attributes = validate_success(
            api.create_attribute_batch(
                create_attribute_batch_payload(
                    context["batch"]["id"], program="RIN_D3"
                ),
                OFFICER,
            ),
            201,
        )
        assert attributes["eligibility_factor"] == approx_4dp(0.9458)
        assert attributes["energy_basis_mmbtu"] == approx_2dp(340.14)
        assert attributes["rin_count"] == 3772, (
            "a fully available plant would have earned 3988"
        )

        site = fixtures.read_site(context["site"]["id"])
        assert site["rin_generated_total"] == 3772
        assert site["rin_available_count"] == 3772


class TestRinLedgerConservation:
    def test_generation_credits_the_generated_total_and_the_available_bucket(self, api):
        """PRD §3.8: "Generating D3 RINs raises the site's `rin_generated_total` and its
        `rin_available_count`, each by the batch's `rin_count`."
        PRD §2.8: "The three destination counters — `rin_available_count` for attributes
        currently held, `rin_retired_count` for attributes retired, and
        `rin_reversed_count` for attributes reversed — must always sum to exactly
        `rin_generated_total`."

        Design: Difficulty/compensating_invariant/rin_count_ledger_conserved_across_generation_and_reversal
        """
        context = fixtures.setup_injected_batch()
        site_id = context["site"]["id"]

        attributes = fixtures.generate_attribute_batch(
            context["batch"]["id"], program="RIN_D3"
        )
        assert attributes["rin_count"] == 3988

        balance = fixtures.read_energy_balance(site_id)
        assert_energy_balance_read(balance)
        assert balance["rin_available_count"] == 3988
        assert balance["rin_ledger_ok"] is True

        site = fixtures.read_site(site_id)
        assert site["rin_generated_total"] == 3988
        assert site["rin_available_count"] == 3988
        assert site["rin_retired_count"] == 0
        assert site["rin_reversed_count"] == 0

    def test_reversal_moves_available_into_reversed_and_leaves_the_total_alone(
        self, api
    ):
        """PRD §3.8: "For the `RIN_D3` program, reversal moves the batch's `rin_count`
        out of `rin_available_count` and into `rin_reversed_count`. What reversal never
        does is reduce `rin_generated_total` — that counter is monotonic by design, which
        is what keeps the identity of §2.8 true across generate, retire and reverse in
        any order."
        PRD §3.8: "The supplied reason is stored as `reversal_reason`, drawn from
        `UPSTREAM_BATCH_DIVERTED`, `BASIS_RESTATEMENT`, `QA_FAILURE` or
        `REPORT_REJECTED`."

        Design: Difficulty/compensating_invariant/rin_count_ledger_conserved_across_generation_and_reversal
        """
        context = fixtures.setup_injected_batch()
        site_id = context["site"]["id"]
        attributes = fixtures.generate_attribute_batch(
            context["batch"]["id"], program="RIN_D3"
        )

        reversed_batch = validate_success(
            api.set_attribute_batch_status(
                attributes["id"], {"to_status": "REVERSED", "reason": "QA_FAILURE"}, OFFICER
            )
        )
        assert reversed_batch["status"] == "REVERSED"
        assert reversed_batch["reversal_reason"] == "QA_FAILURE"

        balance = fixtures.read_energy_balance(site_id)
        assert_energy_balance_read(balance)
        assert balance["rin_reversed_count"] == 3988
        assert balance["rin_ledger_ok"] is True

        site = fixtures.read_site(site_id)
        assert site["rin_generated_total"] == 3988, "the total is monotonic"
        assert site["rin_available_count"] == 0
        assert site["rin_retired_count"] == 0
        assert site["rin_reversed_count"] == 3988


class TestSeparationGating:
    def test_separation_is_refused_while_the_covering_filing_is_only_under_review(
        self, api
    ):
        """PRD §3.8: "A generated batch may be `SEPARATED`, but only once the paperwork
        supports it: there must exist an accepted compliance filing for the site behind
        this attribute batch whose `period` covers the batch's `generation_period` and
        whose `report_type` is `QUARTERLY_RIN_QAP` when the program is `RIN_D3` or
        `LCFS_QUARTERLY` when the program is `LCFS`. Without such a filing the separation
        is refused with `ERR_REPORT_NOT_ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/attribute_separation_gated_on_accepted_compliance_report
        """
        context = fixtures.setup_injected_batch()
        attributes = fixtures.generate_attribute_batch(
            context["batch"]["id"], program="RIN_D3"
        )
        report = fixtures.setup_report_under_review(
            context["site"]["id"], report_type="QUARTERLY_RIN_QAP", period="2026-Q3"
        )
        assert report["status"] == "UNDER_REVIEW"

        validate_error(
            api.set_attribute_batch_status(
                attributes["id"], {"to_status": "SEPARATED"}, OFFICER
            ),
            ApiErrorId.ERR_REPORT_NOT_ACCEPTED.value,
        )
        assert fixtures.read_attribute_batch(attributes["id"])["status"] == "GENERATED"

    def test_separation_succeeds_once_the_covering_filing_is_accepted(self, api):
        """PRD §3.8: "Separation itself moves no ledger; separated attributes remain in
        `rin_available_count`."
        PRD §3.9: "Acceptance is terminal, and it is what unlocks separation for the
        site's attribute batches of that period."

        Design: Difficulty/cross_entity_state_dependency/attribute_separation_gated_on_accepted_compliance_report
        """
        context = fixtures.setup_injected_batch()
        site_id = context["site"]["id"]
        attributes = fixtures.generate_attribute_batch(
            context["batch"]["id"], program="RIN_D3"
        )
        report = fixtures.setup_accepted_report(
            site_id, report_type="QUARTERLY_RIN_QAP", period="2026-Q3"
        )
        assert report["status"] == "ACCEPTED"

        separated = validate_success(
            api.set_attribute_batch_status(
                attributes["id"], {"to_status": "SEPARATED"}, OFFICER
            )
        )
        assert separated["status"] == "SEPARATED", (
            "nothing about the attribute batch changed — only the filing did"
        )

        site = fixtures.read_site(site_id)
        assert site["rin_available_count"] == 3988
        assert site["rin_retired_count"] == 0


class TestGenerationRejections:
    def test_generation_from_a_batch_that_never_reached_injected_is_refused(self, api):
        """PRD §3.8: "The source injection batch must have reached `INJECTED`; anything
        earlier is refused with `ERR_BATCH_NOT_INJECTED`."

        Design: Corner/errors/attribute_generation_from_a_non_injected_batch_is_rejected
        """
        context = fixtures.setup_on_spec_batch()
        batch_id = context["batch"]["id"]
        assert context["batch"]["status"] == "ON_SPEC"

        validate_error(
            api.create_attribute_batch(
                create_attribute_batch_payload(batch_id, program="RIN_D3"), OFFICER
            ),
            ApiErrorId.ERR_BATCH_NOT_INJECTED.value,
        )

        assert fixtures.read_injection_batch(batch_id)["status"] == "ON_SPEC"
        assert fixtures.read_site(context["site"]["id"])["rin_generated_total"] == 0

        _, meta = validate_paginated(
            api.list_attribute_batches(
                OFFICER,
                params={"injection_batch_id": batch_id, "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0

    def test_settled_basis_before_the_trueup_and_a_second_batch_of_the_same_program(
        self, api
    ):
        """PRD §3.8: "When the `basis` is `SETTLED_METERED`, the source batch's
        `metered_mmbtu` must already be non-null, and a request that asks for the settled
        basis before the pipeline meter true-up has landed is refused with
        `ERR_METERED_VOLUME_REQUIRED`. At most one non-reversed attribute batch may exist
        for any given injection batch and program pairing; a second is refused with
        `ERR_ATTRIBUTE_DUPLICATE_PROGRAM`."
        PRD §2.3: "Attribute batches filter on `injection_batch_id`, `program`, `status`
        and `generation_period`."

        Design: Corner/errors/settled_metered_basis_before_trueup_is_rejected_and_duplicate_program_is_rejected
        """
        context = fixtures.setup_injected_batch()
        batch_id = context["batch"]["id"]
        assert fixtures.read_injection_batch(batch_id)["metered_mmbtu"] is None

        validate_error(
            api.create_attribute_batch(
                create_attribute_batch_payload(
                    batch_id, program="RIN_D3", basis="SETTLED_METERED"
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_METERED_VOLUME_REQUIRED.value,
        )

        first = validate_success(
            api.create_attribute_batch(
                create_attribute_batch_payload(batch_id, program="RIN_D3"), OFFICER
            ),
            201,
        )
        assert first["rin_count"] == 3988

        validate_error(
            api.create_attribute_batch(
                create_attribute_batch_payload(batch_id, program="RIN_D3"), OFFICER
            ),
            ApiErrorId.ERR_ATTRIBUTE_DUPLICATE_PROGRAM.value,
        )

        assert fixtures.read_site(context["site"]["id"])["rin_generated_total"] == 3988

        _, meta = validate_paginated(
            api.list_attribute_batches(
                OFFICER,
                params={
                    "injection_batch_id": batch_id,
                    "program": "RIN_D3",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
