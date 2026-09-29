"""Derived-figure calculations: occupancy snapshots under both counting variants,
co-tenancy shortfall pricing, named-anchor substitution, the estoppel fee ladder,
the radius recapture assessment and the compliance-posture rungs.
"""
from test_helpers import (
    COMPLIANCE_OFFICER_USER_ID,
    add_anchor_requirement,
    add_clause,
    add_condition,
    add_radius_restriction,
    assert_cents,
    assert_center_quantities,
    assert_lease_dimensions,
    assert_null,
    assert_pct,
    create_center,
    create_tenant,
    draft_lease,
    elect_remedy,
    execute_lease,
    factories,
    fetch_center,
    fetch_certificate,
    fetch_condition,
    fetch_election,
    fetch_lease,
    fetch_measurement,
    fetch_notice,
    get_success_data,
    go_dark,
    make_compliance_officer_headers,
    open_lease,
    prepare_measurement,
    report_radius_violation,
    request_certificate,
    set_clock,
    terminate_lease,
)

CLOCK_START = "2026-08-01T00:00:00Z"

# suite, gla_sqft, parcel_kind, primary_use_code, base rent cents, tenant, email, chain
FIVE_LEASE_SPECS = (
    (
        "A1",
        120000,
        "ANCHOR_BOX",
        "DISCOUNT_DEPT",
        6000000,
        "Boxmart Retail Inc",
        "legal@boxmart.example",
        True,
    ),
    (
        "A2",
        100000,
        "ANCHOR_BOX",
        "GROCERY",
        4000000,
        "Grocerway Foods LLC",
        "legal@grocerway.example",
        True,
    ),
    (
        "I1",
        2000,
        "INLINE",
        "COFFEE",
        1000000,
        "Bean Theory Coffee LLC",
        "legal@beantheory.example",
        False,
    ),
    (
        "I2",
        3000,
        "INLINE",
        "BOOKS",
        1200000,
        "Margin Books LLC",
        "legal@marginbooks.example",
        False,
    ),
    (
        "I3",
        30000,
        "INLINE",
        "FITNESS",
        1500000,
        "Pulse Fitness Group",
        "legal@pulsefitness.example",
        True,
    ),
)


def _northgate_center(api):
    """A 300000 sqft center holding five open leases: 255000 sqft, 85.00 pct.

    Two anchor boxes (A1, A2) and three inline suites (I1, I2, I3) are drafted,
    executed and opened, so every lease sits in the occupancy population and is
    counted open by both variants (PRD §2.5).
    """
    set_clock(api, CLOCK_START)
    center = create_center(
        api, name="Northgate Crossing", total_gla_sqft=300000, occupancy_grace_days=30
    )
    tenants = {}
    for suite, _gla, _kind, use_code, _rent, legal_name, email, chain in FIVE_LEASE_SPECS:
        tenants[suite] = create_tenant(
            api,
            legal_name=legal_name,
            notice_email=email,
            primary_use_code=use_code,
            is_national_chain=chain,
        )
    leases = {}
    for suite, gla, kind, use_code, rent, _name, _email, _chain in FIVE_LEASE_SPECS:
        leases[suite] = draft_lease(
            api,
            center["id"],
            tenants[suite]["id"],
            suite_code=suite,
            gla_sqft=gla,
            parcel_kind=kind,
            primary_use_code=use_code,
            base_rent_monthly_cents=rent,
            commencement_date="2026-01-01",
            expiration_date="2036-12-31",
        )
    for suite in leases:
        execute_lease(api, leases[suite]["id"])
    for suite in leases:
        open_lease(api, leases[suite]["id"])
    return center, leases, tenants


def _patch_tenant_status(api, tenant_id, status):
    """Move a tenant's credit status as a ``ComplianceOfficer`` (PRD §3.3)."""
    return get_success_data(
        api.patch_tenant(
            tenant_id,
            factories.tenant_patch_payload(status),
            make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID),
        ),
        200,
    )


def _store_count_election(api):
    """One non-anchor store of three goes dark, then the tenant elects a reduction."""
    center, leases, tenants = _northgate_center(api)
    condition = add_condition(
        api,
        leases["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="STORE_COUNT",
        required_occupancy_pct=None,
        required_open_store_count=3,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_ONLY",
        max_reduction_pct=90.0,
    )
    go_dark(api, leases["I3"]["id"])
    election = elect_remedy(
        api,
        leases["I1"]["id"],
        tenants["I1"]["id"],
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=condition["id"],
    )
    return center, leases, condition, election


def test_store_count_shortfall_is_a_ratio_of_the_required_store_count(api):
    """A STORE_COUNT shortfall is the missing share of required stores, 33.33 points.

    PRD: "For a `STORE_COUNT` condition, the shortfall is the condition's `required_open_store_count` minus the controlling non-anchor open-store count, divided by `required_open_store_count`, multiplied by 100, floored at zero and rounded half up to two decimal places."

    Design: Corner/calculations/store_count_basis_shortfall_and_reduction
    """
    center, _leases, condition, election = _store_count_election(api)

    # Two of the three non-anchor stores remain open; both anchors still count.
    assert_center_quantities(
        fetch_center(api, center["id"]), operating_store_count=2, open_anchor_count=2
    )

    stored_condition = fetch_condition(api, condition["id"])
    assert stored_condition["status"] == "BREACHED"
    assert_null(stored_condition["required_occupancy_pct"], "required_occupancy_pct")

    stored_election = fetch_election(api, election["id"])
    assert_pct(
        stored_election["shortfall_pct_at_election"], 33.33, "shortfall_pct_at_election"
    )
    assert stored_election["anchor_bonus_applied"] is False


def test_store_count_reduction_prices_the_top_tier_multiplier(api):
    """A 33.33 point shortfall takes the 2.0 multiplier for 66.66 pct off the rent.

    PRD: "`reduced_rent_monthly_cents` is the lease's `base_rent_monthly_cents` multiplied by 100 minus `reduction_pct`, divided by 100, and rounded half up to whole cents."

    Design: Corner/calculations/store_count_basis_shortfall_and_reduction
    """
    _center, _leases, _condition, election = _store_count_election(api)

    stored_election = fetch_election(api, election["id"])
    # 33.33 sits above 15.00, so the multiplier is 2.0; the 90.00 cap does not bite.
    assert_pct(stored_election["reduction_pct"], 66.66, "reduction_pct")
    # 1000000 * (100 - 66.66) / 100 = 333400 whole cents.
    assert_cents(
        stored_election["reduced_rent_monthly_cents"],
        333400,
        "reduced_rent_monthly_cents",
    )
    assert stored_election["status"] == "ELECTED"


def test_measurement_population_excludes_draft_and_terminated_leases(api):
    """A terminated and a drafted lease raise neither counted nor excluded counts.

    PRD: "Leases in `DRAFT` and `TERMINATED` sit outside the population entirely and are never counted in either the numerator or in `excluded_lease_count`."

    Design: Corner/calculations/measurement_population_excludes_draft_and_terminated_leases
    """
    center, leases, _tenants = _northgate_center(api)
    terminate_lease(api, leases["I3"]["id"], termination_reason_code="SURRENDER")
    drafted_tenant = create_tenant(
        api,
        legal_name="Halcyon Optical LLC",
        notice_email="legal@halcyonoptical.example",
        primary_use_code="OPTICAL",
        is_national_chain=False,
    )
    draft_lease(
        api,
        center["id"],
        drafted_tenant["id"],
        suite_code="I8",
        gla_sqft=9000,
        parcel_kind="INLINE",
        primary_use_code="OPTICAL",
        base_rent_monthly_cents=500000,
        commencement_date="2026-10-01",
        expiration_date="2036-09-30",
    )

    measurement = prepare_measurement(
        api,
        center["id"],
        variant="SNAPSHOT_STRICT",
        window_from_date="2026-07-01",
        window_through_date="2026-08-02",
    )

    assert measurement["counted_lease_count"] == 4
    assert measurement["excluded_lease_count"] == 0
    assert measurement["occupied_gla_sqft"] == 225000
    assert measurement["total_gla_sqft"] == 300000
    assert_pct(measurement["gla_occupancy_pct"], 75.00, "gla_occupancy_pct")
    assert measurement["open_store_count"] == 2
    assert measurement["open_anchor_count"] == 2


def _variant_measurements(api):
    """Measure the center under both variants with I3's tenant DEFAULTED, then BANKRUPT."""
    center, leases, tenants = _northgate_center(api)
    _patch_tenant_status(api, tenants["I3"]["id"], "DEFAULTED")
    defaulted_strict = prepare_measurement(
        api,
        center["id"],
        variant="SNAPSHOT_STRICT",
        window_from_date="2026-06-01",
        window_through_date="2026-06-15",
    )
    defaulted_grace = prepare_measurement(
        api,
        center["id"],
        variant="TRAILING_GRACE",
        window_from_date="2026-06-15",
        window_through_date="2026-07-01",
    )
    _patch_tenant_status(api, tenants["I3"]["id"], "BANKRUPT")
    bankrupt_strict = prepare_measurement(
        api,
        center["id"],
        variant="SNAPSHOT_STRICT",
        window_from_date="2026-07-01",
        window_through_date="2026-07-15",
    )
    bankrupt_grace = prepare_measurement(
        api,
        center["id"],
        variant="TRAILING_GRACE",
        window_from_date="2026-07-15",
        window_through_date="2026-08-01",
    )
    return {
        "center": center,
        "leases": leases,
        "defaulted_strict": defaulted_strict,
        "defaulted_grace": defaulted_grace,
        "bankrupt_strict": bankrupt_strict,
        "bankrupt_grace": bankrupt_grace,
    }


def test_defaulted_tenant_diverges_between_the_two_counting_variants(api):
    """A defaulted tenant on open premises is dropped by strict but kept by grace.

    PRD: "Because a `DEFAULTED` tenant stops counting under the strict variant, a credit downgrade can breach a condition **without a single store going dark** — and because a `DEFAULTED` tenant still counts under the trailing-grace variant, a certified trailing-grace measurement can subsequently cure it."

    Design: Corner/calculations/defaulted_tenant_diverges_between_variants_bankrupt_does_not
    """
    built = _variant_measurements(api)

    # The premises never went dark; only the tenant's credit status moved.
    assert fetch_lease(api, built["leases"]["I3"]["id"])["premises_status"] == "OPEN"

    strict = fetch_measurement(api, built["defaulted_strict"]["id"])
    assert_pct(strict["gla_occupancy_pct"], 75.00, "gla_occupancy_pct")
    assert strict["counted_lease_count"] == 4

    grace = fetch_measurement(api, built["defaulted_grace"]["id"])
    assert_pct(grace["gla_occupancy_pct"], 85.00, "gla_occupancy_pct")
    assert grace["counted_lease_count"] == 5


def test_bankrupt_tenant_is_excluded_by_both_counting_variants(api):
    """A bankrupt tenant drops out of the numerator under either variant.

    PRD: "Under the **`TRAILING_GRACE`** variant, a lease whose tenant's `status` is `BANKRUPT` never counts; a lease whose `premises_status` is `OPEN` always counts, whether its tenant is `ACTIVE` or `DEFAULTED`; and a lease whose `premises_status` is `DARK` with a non-null `dark_since` still counts provided the number of whole days from `dark_since` to the measurement instant is strictly less than the center's `occupancy_grace_days`."

    Design: Corner/calculations/defaulted_tenant_diverges_between_variants_bankrupt_does_not
    """
    built = _variant_measurements(api)

    strict = fetch_measurement(api, built["bankrupt_strict"]["id"])
    assert_pct(strict["gla_occupancy_pct"], 75.00, "gla_occupancy_pct")

    grace = fetch_measurement(api, built["bankrupt_grace"]["id"])
    assert_pct(grace["gla_occupancy_pct"], 75.00, "gla_occupancy_pct")
    assert grace["counted_lease_count"] == 4
    assert grace["excluded_lease_count"] == 1

    # The live strict engine agrees with the strict measurement.
    assert_center_quantities(
        fetch_center(api, built["center"]["id"]), open_occupancy_pct=75.00
    )


def _grace_boundary_measurements(api):
    """A suite dark since 2026-08-01 measured on grace day 29 and again on day 30."""
    center, leases, _tenants = _northgate_center(api)
    go_dark(api, leases["I3"]["id"])
    set_clock(api, "2026-08-30T00:00:00Z")
    day_29 = prepare_measurement(
        api,
        center["id"],
        variant="TRAILING_GRACE",
        window_from_date="2026-08-30",
        window_through_date="2026-08-31",
    )
    set_clock(api, "2026-08-31T00:00:00Z")
    day_30 = prepare_measurement(
        api,
        center["id"],
        variant="TRAILING_GRACE",
        window_from_date="2026-08-31",
        window_through_date="2026-09-01",
    )
    return center, leases, day_29, day_30


def test_trailing_grace_still_counts_a_suite_one_day_inside_the_grace_window(api):
    """Twenty-nine whole days dark is strictly inside a 30-day grace window.

    PRD: "Under the **`TRAILING_GRACE`** variant, a lease whose tenant's `status` is `BANKRUPT` never counts; a lease whose `premises_status` is `OPEN` always counts, whether its tenant is `ACTIVE` or `DEFAULTED`; and a lease whose `premises_status` is `DARK` with a non-null `dark_since` still counts provided the number of whole days from `dark_since` to the measurement instant is strictly less than the center's `occupancy_grace_days`."

    Design: Corner/calculations/trailing_grace_boundary_at_exactly_occupancy_grace_days
    """
    _center, leases, day_29, _day_30 = _grace_boundary_measurements(api)

    dark_lease = fetch_lease(api, leases["I3"]["id"])
    assert dark_lease["dark_since"].startswith("2026-08-01")

    measurement = fetch_measurement(api, day_29["id"])
    assert measurement["measured_at"].startswith("2026-08-30")
    assert_pct(measurement["gla_occupancy_pct"], 85.00, "gla_occupancy_pct")
    assert measurement["counted_lease_count"] == 5


def test_trailing_grace_drops_a_suite_at_exactly_the_grace_day_count(api):
    """Exactly 30 whole days dark is not strictly less than 30, so the suite drops out.

    PRD: "Under the **`TRAILING_GRACE`** variant, a lease whose tenant's `status` is `BANKRUPT` never counts; a lease whose `premises_status` is `OPEN` always counts, whether its tenant is `ACTIVE` or `DEFAULTED`; and a lease whose `premises_status` is `DARK` with a non-null `dark_since` still counts provided the number of whole days from `dark_since` to the measurement instant is strictly less than the center's `occupancy_grace_days`."

    Design: Corner/calculations/trailing_grace_boundary_at_exactly_occupancy_grace_days
    """
    _center, _leases, _day_29, day_30 = _grace_boundary_measurements(api)

    measurement = fetch_measurement(api, day_30["id"])
    assert measurement["measured_at"].startswith("2026-08-31")
    assert_pct(measurement["gla_occupancy_pct"], 75.00, "gla_occupancy_pct")
    assert measurement["counted_lease_count"] == 4
    assert measurement["excluded_lease_count"] == 1


def test_anchor_substitution_satisfies_a_named_anchor_requirement(api):
    """A substitute anchor at exactly the minimum area keeps the condition satisfied.

    PRD: "If it does not count open and substitution is allowed, the system looks for a qualifying substitute: a lease of the same center whose `parcel_kind` is `ANCHOR_BOX`, which is neither the named anchor itself nor named by any other requirement of the same condition, which counts open under the controlling variant at the controlling instant, and whose `gla_sqft` is at least `min_substitute_gla_sqft`."

    Design: Corner/calculations/anchor_substitution_satisfies_a_named_anchor_requirement
    """
    center, leases, _tenants = _northgate_center(api)
    condition = add_condition(
        api,
        leases["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=40.0,
        required_anchor_count=1,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    add_anchor_requirement(
        api,
        condition["id"],
        leases["A1"]["id"],
        substitution_allowed=True,
        min_substitute_gla_sqft=100000,
    )

    go_dark(api, leases["A1"]["id"])

    assert fetch_lease(api, leases["A1"]["id"])["premises_status"] == "DARK"
    assert_center_quantities(
        fetch_center(api, center["id"]),
        occupied_gla_sqft=135000,
        open_occupancy_pct=45.00,
        open_anchor_count=1,
        # PRD §2.6: the occupancy rung freezes the center even with no breach.
        compliance_posture="FROZEN",
    )

    stored_condition = fetch_condition(api, condition["id"])
    assert stored_condition["status"] == "SATISFIED"
    assert_null(stored_condition["breach_detected_at"], "breach_detected_at")
    assert_lease_dimensions(fetch_lease(api, leases["I1"]["id"]), remedy_status="NONE")


def test_estoppel_fee_takes_the_middle_surcharge_tier_on_a_65000_subtotal(api):
    """A 65,000 cent subtotal takes the 15.0% tier for a 74,750 cent total fee.

    PRD: "Second, the surcharge tier is selected **on that subtotal, exactly once**: a subtotal of at most 40,000 cents takes a 10.0% tier, a subtotal above 40,000 but at most 75,000 cents takes 15.0%, and a subtotal above 75,000 cents takes 20.0%."

    Design: Corner/calculations/estoppel_fee_tier_b_on_a_sixty_five_thousand_subtotal
    """
    center, leases, _tenants = _northgate_center(api)
    clause_specs = (
        (["BOOKS"], "CENTER_WIDE", 0, 0.0),
        (["STATIONERY"], "PAD_EXCLUDED", 1500, 10.0),
        (["GREETING_CARDS"], "RADIUS_INCLUSIVE", 500, 5.0),
        (["MAGAZINES"], "CENTER_WIDE", 0, 0.0),
        (["PUZZLES"], "PAD_EXCLUDED", 250, 2.5),
    )
    for codes, scope, carve_out, cap in clause_specs:
        add_clause(
            api,
            leases["I2"]["id"],
            protected_use_codes=codes,
            exclusivity_scope=scope,
            gla_carve_out_sqft=carve_out,
            incidental_sales_pct_cap=cap,
            effective_from_date="2026-01-01",
            effective_through_date="2036-12-31",
        )
    add_condition(
        api,
        leases["I2"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    # Occupancy falls to 75.00 pct, breaching the 81.67 pct condition.
    go_dark(api, leases["I3"]["id"])

    certificate = request_certificate(
        api, leases["I2"]["id"], expedite_requested=True
    )

    stored = fetch_certificate(api, certificate["id"])
    assert stored["disclosed_exclusive_count"] == 5
    assert stored["disclosed_cotenancy_breach"] is True
    # 25000 base + 5 * 5000 disclosures + 15000 breach disclosure.
    assert_cents(stored["base_fee_cents"], 65000, "base_fee_cents")
    # 65000 + round_half_up(65000 * 15.0 / 100) = 65000 + 9750.
    assert_cents(stored["total_fee_cents"], 74750, "total_fee_cents")
    assert_cents(
        stored["disclosed_effective_rent_cents"],
        1200000,
        "disclosed_effective_rent_cents",
    )
    assert stored["status"] == "REQUESTED"
    assert_center_quantities(
        fetch_center(api, center["id"]), protected_exclusive_count=5
    )


def _incremental_recapture_reports(api):
    """Two incremental-basis restrictions reported at, and above, the baseline."""
    center, leases, _tenants = _northgate_center(api)
    restriction_at = add_radius_restriction(
        api,
        leases["I3"]["id"],
        radius_miles=3.0,
        measured_from="CENTER_BOUNDARY",
        recapture_basis="INCREMENTAL_SALES",
        recapture_pct=8.0,
        protected_baseline_cents=2500000,
        window_from_date="2026-01-01",
        window_through_date="2026-12-31",
    )
    restriction_above = add_radius_restriction(
        api,
        leases["I2"]["id"],
        radius_miles=3.0,
        measured_from="CENTER_BOUNDARY",
        recapture_basis="INCREMENTAL_SALES",
        recapture_pct=8.0,
        protected_baseline_cents=2500000,
        window_from_date="2026-01-01",
        window_through_date="2026-12-31",
    )
    notice_at = report_radius_violation(
        api,
        restriction_at["id"],
        reported_offending_sales_cents=2500000,
        narrative="Satellite studio sales exactly at the protected baseline.",
        cure_period_days=30,
    )
    notice_above = report_radius_violation(
        api,
        restriction_above["id"],
        reported_offending_sales_cents=2600000,
        narrative="Satellite store sales 100000 cents above the protected baseline.",
        cure_period_days=30,
    )
    return center, restriction_at, restriction_above, notice_at, notice_above


def test_incremental_recapture_at_exactly_the_protected_baseline_is_zero(api):
    """Sales exactly at the protected baseline assess nothing on the incremental basis.

    PRD: "A reported volume exactly equal to `protected_baseline_cents` therefore yields 0 under the incremental basis and a positive assessment under the gross basis."

    Design: Corner/calculations/incremental_recapture_at_exactly_the_protected_baseline_is_zero
    """
    _center, restriction_at, _restriction_above, notice_at, _notice_above = (
        _incremental_recapture_reports(api)
    )

    stored = fetch_notice(api, notice_at["id"])
    assert_cents(stored["recapture_assessed_cents"], 0, "recapture_assessed_cents")
    assert_cents(
        stored["reported_offending_sales_cents"],
        2500000,
        "reported_offending_sales_cents",
    )
    assert stored["notice_kind"] == "RADIUS"
    assert stored["radius_restriction_id"] == restriction_at["id"]
    assert_null(stored["clause_id"], "clause_id")


def test_incremental_recapture_above_the_baseline_charges_the_excess(api):
    """Only the excess over the baseline is charged, 8.0% of 100,000 cents.

    PRD: "The assessment is that base multiplied by `recapture_pct`, divided by 100, and rounded half up to whole cents."

    Design: Corner/calculations/incremental_recapture_at_exactly_the_protected_baseline_is_zero
    """
    center, _restriction_at, _restriction_above, _notice_at, notice_above = (
        _incremental_recapture_reports(api)
    )

    stored = fetch_notice(api, notice_above["id"])
    # (2600000 - 2500000) * 8.0 / 100 = 8000 whole cents.
    assert_cents(stored["recapture_assessed_cents"], 8000, "recapture_assessed_cents")

    assert_center_quantities(
        fetch_center(api, center["id"]),
        open_violation_count=2,
        compliance_posture="WATCH",
    )


def _two_centers_at_the_watch_boundary(api):
    """One center at exactly 70.00 pct occupancy and one at 69.67 pct."""
    set_clock(api, CLOCK_START)
    alpha = create_center(
        api, name="Alpha Center", total_gla_sqft=300000, occupancy_grace_days=30
    )
    beta = create_center(
        api, name="Beta Center", total_gla_sqft=300000, occupancy_grace_days=30
    )
    alpha_tenant = create_tenant(
        api,
        legal_name="Alpha Anchor Inc",
        notice_email="legal@alphaanchor.example",
        primary_use_code="DISCOUNT_DEPT",
        is_national_chain=True,
    )
    beta_tenant = create_tenant(
        api,
        legal_name="Beta Anchor Inc",
        notice_email="legal@betaanchor.example",
        primary_use_code="DISCOUNT_DEPT",
        is_national_chain=True,
    )
    alpha_lease = draft_lease(
        api,
        alpha["id"],
        alpha_tenant["id"],
        suite_code="A1",
        gla_sqft=210000,
        parcel_kind="ANCHOR_BOX",
        primary_use_code="DISCOUNT_DEPT",
        base_rent_monthly_cents=8000000,
        commencement_date="2026-01-01",
        expiration_date="2036-12-31",
    )
    beta_lease = draft_lease(
        api,
        beta["id"],
        beta_tenant["id"],
        suite_code="A1",
        gla_sqft=209000,
        parcel_kind="ANCHOR_BOX",
        primary_use_code="DISCOUNT_DEPT",
        base_rent_monthly_cents=8000000,
        commencement_date="2026-01-01",
        expiration_date="2036-12-31",
    )
    execute_lease(api, alpha_lease["id"])
    execute_lease(api, beta_lease["id"])
    open_lease(api, alpha_lease["id"])
    open_lease(api, beta_lease["id"])
    return alpha, beta


def test_posture_stays_compliant_at_exactly_seventy_percent_occupancy(api):
    """A center at exactly 70.00 pct is not on the WATCH rung.

    PRD: "Comparisons use the stored two-decimal percentage without re-rounding, and both occupancy tests are strictly-less-than: exactly 50.00 is not `FROZEN`, and exactly 70.00 is not `WATCH`."

    Design: Corner/calculations/posture_watch_rung_is_strictly_below_seventy_percent
    """
    alpha, _beta = _two_centers_at_the_watch_boundary(api)

    assert_center_quantities(
        fetch_center(api, alpha["id"]),
        occupied_gla_sqft=210000,
        open_occupancy_pct=70.00,
        compliance_posture="COMPLIANT",
        open_violation_count=0,
    )


def test_posture_reaches_watch_just_below_seventy_percent_occupancy(api):
    """A center at 69.67 pct is on the WATCH rung with no breach and no violation.

    PRD: "Otherwise the posture is `WATCH` when `open_violation_count` is at least one, or when the center is assessable and its `open_occupancy_pct` is strictly below 70.00."

    Design: Corner/calculations/posture_watch_rung_is_strictly_below_seventy_percent
    """
    _alpha, beta = _two_centers_at_the_watch_boundary(api)

    # 209000 / 300000 * 100 = 69.6666..., rounded half up to 69.67.
    assert_center_quantities(
        fetch_center(api, beta["id"]),
        occupied_gla_sqft=209000,
        open_occupancy_pct=69.67,
        compliance_posture="WATCH",
        open_violation_count=0,
    )


def test_two_breached_conditions_freeze_a_center_well_above_fifty_percent(api):
    """Two breached conditions reach the FROZEN rung even at 75.00 pct occupancy.

    PRD: "The posture is `FROZEN` when the breached-condition count is at least two, or when the center is assessable and its `open_occupancy_pct` is strictly below 50.00."

    Design: Corner/calculations/posture_freeze_rung_beats_the_breach_rung_on_two_conditions
    """
    center, leases, _tenants = _northgate_center(api)
    conditions = []
    for suite in ("I1", "I2"):
        conditions.append(
            add_condition(
                api,
                leases[suite]["id"],
                condition_kind="ONGOING",
                measurement_basis="GLA_PCT",
                required_occupancy_pct=81.67,
                required_anchor_count=2,
                grace_period_days=0,
                cure_period_days=30,
                remedy_type="RENT_REDUCTION_THEN_TERMINATION",
                max_reduction_pct=25.0,
            )
        )

    go_dark(api, leases["I3"]["id"])

    for condition in conditions:
        assert fetch_condition(api, condition["id"])["status"] == "BREACHED"
    for suite in ("I1", "I2"):
        assert_lease_dimensions(
            fetch_lease(api, leases[suite]["id"]), remedy_status="ELIGIBLE"
        )
    assert_center_quantities(
        fetch_center(api, center["id"]),
        open_occupancy_pct=75.00,
        compliance_posture="FROZEN",
        open_violation_count=0,
    )
