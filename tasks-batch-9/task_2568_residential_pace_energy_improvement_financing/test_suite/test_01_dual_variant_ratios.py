"""The three calculations the PRD applies twice under different aggregations.

Each of these tests drives one figure through both of its declared variants in a
single scenario, so that the two answers can be compared against each other on
identical stored data rather than merely checked one at a time.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import ERR_WORKMANSHIP_GATE_NOT_MET
from test_helpers.test_users import COMPLIANCE_OFFICER, PROGRAM_ADMIN, UNDERWRITING_ANALYST


def _mixed_strength_portfolio(client):
    """A strong 25-year solar array plus a 20-year window package below the floor."""
    world = fixtures.seed_program(client)
    windows = A.expect_created(
        client.create_product(
            factories.product_payload("WINDOWS_DUALPANE", "WINDOWS", 20, 60000),
            PROGRAM_ADMIN,
        )
    )
    world["windows_product_id"] = windows["id"]
    fixtures.open_draft_application(client, world, 20)
    solar = A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["solar_product_id"],
                fixtures.current_version(client, world),
                3000000,
                250000,
            ),
            world["owner_headers"],
        )
    )
    world["solar_measure_id"] = solar["id"]
    weak = A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["windows_product_id"],
                fixtures.current_version(client, world),
                1000000,
                40000,
            ),
            world["owner_headers"],
        )
    )
    world["weak_measure_id"] = weak["id"]
    return world


def test_per_measure_gate_and_portfolio_blend_disagree_on_one_measure_set(client):
    """Per-measure and blended savings ratios diverge over the same PROPOSED set.

    The two figures genuinely disagree on identical data: a strong measure carries
    a weak one in the blend, while the per-measure figure judges each measure alone
    against the 10000-basis-point floor.

    Design: Difficulty/dual_variant_calc/sir_per_measure_gate_vs_portfolio_blend_divergence_on_measures
    """
    world = _mixed_strength_portfolio(client)

    app = A.expect_ok(
        client.submit_application(world["application_id"], world["owner_headers"])
    )
    A.assert_fields(
        app,
        status="UNDER_REVIEW",
        requested_principal_cents=4000000,
        weighted_useful_life_years=23,
        min_measure_sir_bps=5951,
        portfolio_sir_bps=12371,
    )

    strong = A.expect_ok(client.get_measure(world["solar_measure_id"], PROGRAM_ADMIN))
    weak = A.expect_ok(client.get_measure(world["weak_measure_id"], PROGRAM_ADMIN))
    A.assert_fields(strong, pv_savings_cents=4353287, sir_bps=14511, status="PROPOSED")
    A.assert_fields(weak, pv_savings_cents=595099, sir_bps=5951, status="PROPOSED")

    # The gate variant condemns the weak measure even though the blend cleared 10000.
    A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        A.expect_ok(client.get_measure(world["solar_measure_id"], PROGRAM_ADMIN)),
        status="APPROVED",
        sir_bps=14511,
    )
    A.assert_fields(
        A.expect_ok(client.get_measure(world["weak_measure_id"], PROGRAM_ADMIN)),
        status="INELIGIBLE",
        sir_bps=5951,
    )


def test_blended_variant_is_re_evaluated_over_the_approved_subset_alone(client):
    """Underwriting re-blends the portfolio ratio over the surviving measures only.

    At submit and cure both variants are evaluated over the whole `PROPOSED` set;
    the blended figure is later re-evaluated over the approved subset alone during
    underwriting.

    Design: Difficulty/dual_variant_calc/sir_per_measure_gate_vs_portfolio_blend_divergence_on_measures
    """
    world = _mixed_strength_portfolio(client)
    submitted = A.expect_ok(
        client.submit_application(world["application_id"], world["owner_headers"])
    )
    assert submitted["portfolio_sir_bps"] == 12371

    underwritten = A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    # Dropping the weak measure both shrank the exposure and lifted the blend.
    A.assert_fields(
        underwritten,
        status="CONSENT_PENDING",
        requested_principal_cents=3000000,
        portfolio_sir_bps=14511,
        min_measure_sir_bps=5951,
        underwriting_cltv_bps=7000,
        valuation_basis="ASSESSED",
    )


def _severe_then_major_history(client):
    """A SEVERE defect old enough to age out, plus a fresh MAJOR one."""
    world = fixtures.funded_project(client)
    fixtures.move_clock(client, "2026-08-20T00:00:00Z")
    fixtures.upheld_complaint(client, world, "2026-09-30", severity="SEVERE")
    first_complaint_id = world["complaint_id"]
    A.assert_fields(
        fixtures.read_contractor(client, world),
        workmanship_score=8000,
        lifetime_workmanship_score=8000,
        enrollment_status="PROBATION",
        suspension_reason="WORKMANSHIP_SCORE_BELOW_9000",
        upheld_open_remedy_count=1,
    )
    fixtures.move_clock(client, "2026-09-15T00:00:00Z")
    A.expect_ok(
        client.adjudicate_complaint(
            first_complaint_id,
            factories.adjudicate_payload("REMEDY_VERIFIED"),
            COMPLIANCE_OFFICER,
        )
    )
    A.assert_fields(
        fixtures.read_contractor(client, world),
        workmanship_score=8000,
        lifetime_workmanship_score=8000,
        enrollment_status="PROBATION",
        upheld_open_remedy_count=0,
    )
    # 742 days after the severe complaint was filed: outside the 730-day window.
    fixtures.move_clock(client, "2028-09-01T00:00:00Z")
    fixtures.upheld_complaint(client, world, "2028-09-20", severity="MAJOR")
    world["first_complaint_id"] = first_complaint_id
    return world


def test_trailing_variant_ages_the_old_defect_out_while_lifetime_keeps_it(client):
    """The 730-day window drops the severe defect the lifetime figure still counts.

    The **trailing** variant, stored in `workmanship_score`, counts only upheld
    complaints whose `created_at` falls within 730 days of the current logical date,
    so old defects age out and a contractor can climb back to 10000 simply by
    working cleanly for two years.

    Design: Difficulty/dual_variant_calc/workmanship_trailing_24m_vs_lifetime_blocks_reinstatement
    """
    world = _severe_then_major_history(client)

    contractor = fixtures.read_contractor(client, world)
    # Trailing sees the 800 bps MAJOR only; lifetime still carries the 2000 bps SEVERE.
    A.assert_fields(
        contractor,
        workmanship_score=9200,
        lifetime_workmanship_score=7200,
        upheld_open_remedy_count=1,
    )
    # Trailing is at or above 9000, so this uphold left the enrollment status alone.
    A.assert_fields(contractor, enrollment_status="PROBATION")


def test_lifetime_variant_blocks_reinstatement_the_trailing_variant_would_allow(client):
    """Reinstatement is refused on the lifetime gate while the trailing gate passes.

    Both score windows matter independently — a contractor whose defects have aged
    out of the trailing window can still be barred by the lifetime figure, and
    licence currency is re-checked here and not only at first enrollment.

    Design: Difficulty/dual_variant_calc/workmanship_trailing_24m_vs_lifetime_blocks_reinstatement
    """
    world = _severe_then_major_history(client)
    fixtures.move_clock(client, "2028-09-10T00:00:00Z")
    A.expect_ok(
        client.adjudicate_complaint(
            world["complaint_id"],
            factories.adjudicate_payload("REMEDY_VERIFIED"),
            COMPLIANCE_OFFICER,
        )
    )
    A.assert_fields(
        fixtures.read_contractor(client, world),
        workmanship_score=9200,
        lifetime_workmanship_score=7200,
        upheld_open_remedy_count=0,
        enrollment_status="PROBATION",
    )

    # Trailing 9200 >= 9000 and no open remedy, but lifetime 7200 < 8000.
    A.expect_error(
        client.reinstate_contractor(
            world["contractor_id"],
            PROGRAM_ADMIN,
            factories.reinstate_payload("trailing window cleared"),
        ),
        ERR_WORKMANSHIP_GATE_NOT_MET,
    )
    A.assert_fields(
        fixtures.read_contractor(client, world),
        enrollment_status="PROBATION",
        suspension_reason="WORKMANSHIP_SCORE_BELOW_9000",
    )


def _thin_equity_parcel(client):
    """A parcel whose assessed basis sits exactly at the cap and whose appraisal is fresh."""
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    world = {"clock": fixtures.SIGNING_CLOCK}
    world.update(fixtures.seed_catalog(client))
    world.update(fixtures.seed_enrolled_contractor(client))
    world.update(
        fixtures.seed_parcel(
            client,
            payload=factories.property_payload(
                market_value_cents=46000000, appraisal_effective_on="2026-07-01"
            ),
            lien_overrides={"current_balance_cents": 34000000},
        )
    )
    fixtures.open_draft_application(client, world, 20)
    A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["solar_product_id"],
                fixtures.current_version(client, world),
                3600000,
                280000,
            ),
            world["owner_headers"],
        )
    )
    A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["hvac_product_id"],
                fixtures.current_version(client, world),
                1200000,
                100000,
            ),
            world["owner_headers"],
        )
    )
    return world


def test_assessed_basis_variant_is_the_conservative_one_and_locks_the_screen(client):
    """The advisory screen and an ASSESSED underwrite both divide by the assessed value.

    Because assessed values lag the market, the assessed basis produces the higher —
    and therefore more conservative — ratio for the same debt, which is why it is the
    only basis permitted for the advisory screen at submit.

    Design: Difficulty/dual_variant_calc/cltv_assessed_vs_market_basis_divergence_on_property
    """
    world = _thin_equity_parcel(client)

    submitted = A.expect_ok(
        client.submit_application(world["application_id"], world["owner_headers"])
    )
    A.assert_fields(
        submitted,
        requested_principal_cents=4800000,
        weighted_useful_life_years=23,
        portfolio_sir_bps=13023,
        min_measure_sir_bps=11461,
        screening_cltv_bps=9700,
        valuation_basis=None,
        underwriting_cltv_bps=None,
    )

    underwritten = A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        underwritten,
        status="CONSENT_PENDING",
        valuation_basis="ASSESSED",
        underwriting_cltv_bps=9700,
        screening_cltv_bps=9700,
    )


def test_market_basis_variant_diverges_from_the_assessed_screen_on_one_parcel(client):
    """Electing MARKET moves only the underwriting ratio; the screen stays assessed.

    Under the **assessed basis** the denominator is `assessed_value_cents`. Under the
    **market basis** it is `market_value_cents`, but only while the appraisal behind
    it is fresh: the current logical date minus `appraisal_effective_on` must be at
    most 180 days.

    Design: Difficulty/dual_variant_calc/cltv_assessed_vs_market_basis_divergence_on_property
    """
    world = _thin_equity_parcel(client)
    A.expect_ok(client.submit_application(world["application_id"], world["owner_headers"]))

    underwritten = A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_proceed_payload("MARKET"),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        underwritten,
        status="CONSENT_PENDING",
        valuation_basis="MARKET",
        underwriting_cltv_bps=8435,
        screening_cltv_bps=9700,
    )

    # Both denominators are reported side by side on the same parcel and debt.
    report = A.expect_ok(
        client.get_eligibility_report(world["application_id"], UNDERWRITING_ANALYST)
    )
    A.assert_fields(
        report,
        valuation_basis_applied="MARKET",
        appraisal_stale=False,
        cltv_bps_assessed=9700,
        cltv_bps_market=8435,
        ptv_bps=1200,
        equity_bps=1500,
        approved_principal_cents=4800000,
        blocking_error_id=None,
    )
