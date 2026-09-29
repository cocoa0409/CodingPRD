"""Two-variant occupancy counting, the two radius recapture bases, and the
composed rent-reduction / abatement-ledger / estoppel-fee formulas.

Every scenario is rebuilt from scratch through the API because the database
starts empty for each test.
"""
from test_helpers import (
    add_anchor_requirement,
    add_clause,
    add_condition,
    add_radius_restriction,
    approve_election,
    assert_cents,
    assert_center_quantities,
    assert_lease_dimensions,
    assert_pct,
    build_center_with_leases,
    elect_remedy,
    fetch_center,
    fetch_certificate,
    fetch_condition,
    fetch_election,
    fetch_lease,
    fetch_notice,
    go_dark,
    prepare_measurement,
    report_radius_violation,
    request_certificate,
    set_clock,
)

# --------------------------------------------------------------------------
# Shared scenario: one center, two anchor boxes and three inline suites, all
# open on the logical clock date 2026-08-01 (PRD §2.4, §2.5).
# --------------------------------------------------------------------------
CLOCK_AT_SETUP = "2026-08-01T00:00:00Z"
CENTER_TOTAL_GLA_SQFT = 300000
CENTER_GRACE_DAYS = 30

FIVE_SUITE_SPECS = (
    {
        "suite_code": "A1",
        "gla_sqft": 120000,
        "parcel_kind": "ANCHOR_BOX",
        "primary_use_code": "DISCOUNT_DEPT",
        "base_rent_monthly_cents": 6000000,
        "expiration_date": "2036-12-31",
    },
    {
        "suite_code": "A2",
        "gla_sqft": 100000,
        "parcel_kind": "ANCHOR_BOX",
        "primary_use_code": "GROCERY",
        "base_rent_monthly_cents": 4000000,
        "expiration_date": "2036-12-31",
    },
    {
        "suite_code": "I1",
        "gla_sqft": 2000,
        "parcel_kind": "INLINE",
        "primary_use_code": "COFFEE",
        "base_rent_monthly_cents": 1000000,
        "expiration_date": "2036-12-31",
    },
    {
        "suite_code": "I2",
        "gla_sqft": 3000,
        "parcel_kind": "INLINE",
        "primary_use_code": "BOOKS",
        "base_rent_monthly_cents": 1200000,
        "expiration_date": "2036-12-31",
    },
    {
        "suite_code": "I3",
        "gla_sqft": 30000,
        "parcel_kind": "INLINE",
        "primary_use_code": "FITNESS",
        "base_rent_monthly_cents": 1500000,
        "expiration_date": "2036-12-31",
    },
)


def _build_five_suite_center(api):
    """Center of 300,000 sqft with a 30-day dark-premises grace, fully open."""
    return build_center_with_leases(
        api,
        [dict(spec) for spec in FIVE_SUITE_SPECS],
        total_gla_sqft=CENTER_TOTAL_GLA_SQFT,
        occupancy_grace_days=CENTER_GRACE_DAYS,
        clock=CLOCK_AT_SETUP,
    )


# --------------------------------------------------------------------------
# Occupancy under the two counting variants (PRD §2.5, §3.4)
# --------------------------------------------------------------------------
def _prepare_both_variants(api):
    """Drive the 30,000 sqft inline suite dark, then measure it twice."""
    scenario = _build_five_suite_center(api)
    go_dark(api, scenario.lease_id("I3"))
    strict = prepare_measurement(
        api,
        scenario.center_id,
        variant="SNAPSHOT_STRICT",
        window_from_date="2026-07-01",
        window_through_date="2026-08-02",
    )
    trailing = prepare_measurement(
        api,
        scenario.center_id,
        variant="TRAILING_GRACE",
        window_from_date="2026-08-02",
        window_through_date="2026-09-02",
    )
    return scenario, strict, trailing


def test_snapshot_strict_measurement_drops_the_dark_inline_suite(api):
    """SNAPSHOT_STRICT excludes the dark suite, leaving 225,000 sqft and 75.00 pct.

    PRD: "Under the **`SNAPSHOT_STRICT`** variant, a lease counts open only when its `premises_status` is `OPEN` **and** its tenant's `status` is `ACTIVE`."

    Design: Difficulty/dual_variant_calc/occupancy_variant_divergence_dark_inline_strict_versus_trailing_grace
    """
    _scenario, strict, _trailing = _prepare_both_variants(api)

    assert strict["variant"] == "SNAPSHOT_STRICT"
    assert strict["occupied_gla_sqft"] == 225000
    assert_pct(strict["gla_occupancy_pct"], 75.00, "gla_occupancy_pct")


def test_snapshot_strict_measurement_reports_population_counts(api):
    """The strict row counts four of five population leases and excludes one.

    PRD: "From that population an engine derives: the counted gross leasable area as the sum of `gla_sqft` over counted leases; a GLA occupancy percentage equal to the counted area divided by the total area, multiplied by 100, and rounded half up to two decimal places; a non-anchor open-store count as the number of counted leases whose `is_anchor` is false; an anchor count as the number of counted leases whose `is_anchor` is true; a total counted-lease count; and an excluded count equal to the population size minus the counted size."

    Design: Difficulty/dual_variant_calc/occupancy_variant_divergence_dark_inline_strict_versus_trailing_grace
    """
    _scenario, strict, _trailing = _prepare_both_variants(api)

    assert strict["total_gla_sqft"] == CENTER_TOTAL_GLA_SQFT
    assert strict["counted_lease_count"] == 4
    assert strict["excluded_lease_count"] == 1
    assert strict["open_store_count"] == 2
    assert strict["open_anchor_count"] == 2


def test_trailing_grace_measurement_readmits_the_recently_dark_suite(api):
    """TRAILING_GRACE re-admits a suite dark 0 of 30 grace days, reaching 85.00 pct.

    PRD: "Under the **`TRAILING_GRACE`** variant, a lease whose tenant's `status` is `BANKRUPT` never counts; a lease whose `premises_status` is `OPEN` always counts, whether its tenant is `ACTIVE` or `DEFAULTED`; and a lease whose `premises_status` is `DARK` with a non-null `dark_since` still counts provided the number of whole days from `dark_since` to the measurement instant is strictly less than the center's `occupancy_grace_days`."

    Design: Difficulty/dual_variant_calc/occupancy_variant_divergence_dark_inline_strict_versus_trailing_grace
    """
    _scenario, _strict, trailing = _prepare_both_variants(api)

    assert trailing["variant"] == "TRAILING_GRACE"
    assert trailing["occupied_gla_sqft"] == 255000
    assert_pct(trailing["gla_occupancy_pct"], 85.00, "gla_occupancy_pct")
    assert trailing["counted_lease_count"] == 5
    assert trailing["excluded_lease_count"] == 0
    assert trailing["open_store_count"] == 3
    assert trailing["open_anchor_count"] == 2


def test_two_variants_diverge_by_ten_points_while_the_center_reads_strict(api):
    """The variants disagree by 10.00 points and the center keeps the strict figure.

    PRD: "The **live strict engine** recomputes the center's own derived fields — `occupied_gla_sqft`, `open_occupancy_pct`, `operating_store_count`, `open_anchor_count`, `aggregate_effective_rent_cents`, `protected_exclusive_count`, and `open_violation_count` — always under the `SNAPSHOT_STRICT` variant and always at the current logical clock."

    Design: Difficulty/dual_variant_calc/occupancy_variant_divergence_dark_inline_strict_versus_trailing_grace
    """
    scenario, strict, trailing = _prepare_both_variants(api)

    assert_pct(
        trailing["gla_occupancy_pct"] - strict["gla_occupancy_pct"],
        10.00,
        "variant divergence",
    )
    center = fetch_center(api, scenario.center_id)
    assert_center_quantities(
        center, occupied_gla_sqft=225000, open_occupancy_pct=75.00
    )


# --------------------------------------------------------------------------
# Radius recapture under the two chargeable bases (PRD §3.6)
# --------------------------------------------------------------------------
REPORTED_OFFENDING_SALES_CENTS = 4000000
PROTECTED_BASELINE_CENTS = 2500000


def _report_under_both_bases(api):
    """Two restrictions with identical numbers but opposite recapture bases."""
    scenario = _build_five_suite_center(api)
    gross = add_radius_restriction(
        api,
        scenario.lease_id("I3"),
        radius_miles=3.0,
        measured_from="CENTER_BOUNDARY",
        recapture_basis="GROSS_SALES",
        recapture_pct=8.0,
        window_from_date="2026-01-01",
        window_through_date="2026-12-31",
        protected_baseline_cents=PROTECTED_BASELINE_CENTS,
    )
    incremental = add_radius_restriction(
        api,
        scenario.lease_id("I2"),
        radius_miles=3.0,
        measured_from="CENTER_BOUNDARY",
        recapture_basis="INCREMENTAL_SALES",
        recapture_pct=8.0,
        window_from_date="2026-01-01",
        window_through_date="2026-12-31",
        protected_baseline_cents=PROTECTED_BASELINE_CENTS,
    )
    gross_notice = report_radius_violation(
        api,
        gross["id"],
        REPORTED_OFFENDING_SALES_CENTS,
        narrative="Second Pulse Fitness studio opened 1.4 miles from the center boundary.",
        cure_period_days=30,
    )
    incremental_notice = report_radius_violation(
        api,
        incremental["id"],
        REPORTED_OFFENDING_SALES_CENTS,
        narrative="Second Margin Books store opened 1.4 miles from the center boundary.",
        cure_period_days=30,
    )
    return scenario, gross_notice, incremental_notice


def test_gross_sales_basis_charges_the_whole_reported_volume(api):
    """GROSS_SALES ignores the protected baseline and assesses 320,000 cents.

    PRD: "**The recapture assessment** is computed onto `recapture_assessed_cents` at that moment: under the `GROSS_SALES` basis the chargeable base is the entire `reported_offending_sales_cents` and `protected_baseline_cents` is ignored; under the `INCREMENTAL_SALES` basis the chargeable base is `reported_offending_sales_cents` minus `protected_baseline_cents`, floored at zero."

    Design: Difficulty/dual_variant_calc/radius_recapture_basis_divergence_gross_versus_incremental
    """
    _scenario, gross_notice, _incremental_notice = _report_under_both_bases(api)

    assert gross_notice["notice_kind"] == "RADIUS"
    assert_cents(
        gross_notice["recapture_assessed_cents"], 320000, "recapture_assessed_cents"
    )


def test_incremental_sales_basis_charges_only_the_excess_over_baseline(api):
    """INCREMENTAL_SALES nets the 2,500,000-cent baseline and assesses 120,000 cents.

    PRD: "The assessment is that base multiplied by `recapture_pct`, divided by 100, and rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/radius_recapture_basis_divergence_gross_versus_incremental
    """
    _scenario, _gross_notice, incremental_notice = _report_under_both_bases(api)

    assert incremental_notice["notice_kind"] == "RADIUS"
    assert_cents(
        incremental_notice["recapture_assessed_cents"],
        120000,
        "recapture_assessed_cents",
    )


def test_recapture_bases_diverge_on_identical_reported_volumes(api):
    """Identical inputs assess 200,000 cents apart across the two bases.

    PRD: "A reported volume exactly equal to `protected_baseline_cents` therefore yields 0 under the incremental basis and a positive assessment under the gross basis."

    Design: Difficulty/dual_variant_calc/radius_recapture_basis_divergence_gross_versus_incremental
    """
    _scenario, gross_notice, incremental_notice = _report_under_both_bases(api)

    assert_cents(
        gross_notice["recapture_assessed_cents"]
        - incremental_notice["recapture_assessed_cents"],
        200000,
        "recapture divergence",
    )


def test_radius_report_mints_a_notice_with_a_thirty_day_cure_deadline(api):
    """The minted radius notice deadlines 30 days after the 2026-08-01 issue instant.

    PRD: "The report mints a notice with `notice_kind` set to `RADIUS`, `radius_restriction_id` set from the addressed restriction, `clause_id` null, `status` `ISSUED`, `issued_by_user_id` from `X-User-ID`, and `cure_deadline_at` set to `issued_at` plus `cure_period_days` days."

    Design: Difficulty/dual_variant_calc/radius_recapture_basis_divergence_gross_versus_incremental
    """
    _scenario, gross_notice, _incremental_notice = _report_under_both_bases(api)

    notice = fetch_notice(api, gross_notice["id"])
    assert notice["notice_kind"] == "RADIUS"
    assert notice["status"] == "ISSUED"
    assert notice["clause_id"] is None
    assert notice["cure_period_days"] == 30
    assert notice["cure_deadline_at"].startswith("2026-08-31T00:00:00"), (
        f"cure_deadline_at is {notice['cure_deadline_at']}, "
        "expected 30 days after the 2026-08-01T00:00:00Z issue instant"
    )


def test_both_radius_notices_move_the_center_to_watch(api):
    """Two open violations put the center on WATCH with both suites under notice.

    PRD: "The notice's other side effects mirror a directly issued notice: the lease's `use_compliance_status` moves from `CLEAR` to `UNDER_NOTICE`, the center's `open_violation_count` increments, and posture is re-derived."

    Design: Difficulty/dual_variant_calc/radius_recapture_basis_divergence_gross_versus_incremental
    """
    scenario, _gross_notice, _incremental_notice = _report_under_both_bases(api)

    center = fetch_center(api, scenario.center_id)
    assert_center_quantities(
        center, open_violation_count=2, compliance_posture="WATCH"
    )
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I3")),
        use_compliance_status="UNDER_NOTICE",
    )
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I2")),
        use_compliance_status="UNDER_NOTICE",
    )


# --------------------------------------------------------------------------
# Rent-reduction pricing: tier, anchor adder, floor and cap (PRD §3.5)
# --------------------------------------------------------------------------
def _breach_by_darkening_the_named_anchor(api):
    """Condition requiring 81.67 pct and two anchors, breached by a dark anchor."""
    scenario = _build_five_suite_center(api)
    condition = add_condition(
        api,
        scenario.lease_id("I1"),
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=90.0,
    )
    add_anchor_requirement(
        api,
        condition["id"],
        scenario.lease_id("A1"),
        substitution_allowed=False,
        min_substitute_gla_sqft=0,
    )
    go_dark(api, scenario.lease_id("A1"))
    scenario["condition"] = fetch_condition(api, condition["id"])
    return scenario


def _elect_reduction_after_anchor_went_dark(api):
    scenario = _breach_by_darkening_the_named_anchor(api)
    election = elect_remedy(
        api,
        scenario.lease_id("I1"),
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=scenario["condition"]["id"],
    )
    return scenario, election


def test_darkening_the_anchor_breaches_the_ongoing_condition(api):
    """The 120,000 sqft anchor going dark drops occupancy to 45.00 pct and breaches.

    PRD: "Hop 3, caused by hop 2 because the center's occupancy figures moved, re-evaluates every `ONGOING` condition of the center under the live strict engine; a condition that now fails flips from `SATISFIED` or `CURED` to `BREACHED` with `breach_detected_at` stamped at the current instant and `consecutive_breach_days` reset to 0."

    Design: Difficulty/combinatorial_formula/rent_reduction_tier_three_plus_anchor_bonus_then_cap
    """
    scenario = _breach_by_darkening_the_named_anchor(api)

    center = fetch_center(api, scenario.center_id)
    assert_center_quantities(center, open_occupancy_pct=45.00)
    assert scenario["condition"]["status"] == "BREACHED"


def test_shortfall_is_the_requirement_minus_the_controlling_occupancy(api):
    """81.67 required against 45.00 controlling pins a 36.67-point shortfall.

    PRD: "Otherwise, for a `GLA_PCT` condition, the shortfall is the condition's `required_occupancy_pct` minus the controlling occupancy percentage, floored at zero and rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/rent_reduction_tier_three_plus_anchor_bonus_then_cap
    """
    _scenario, election = _elect_reduction_after_anchor_went_dark(api)

    assert_pct(
        election["shortfall_pct_at_election"], 36.67, "shortfall_pct_at_election"
    )


def test_top_tier_multiplier_then_anchor_adder_yields_eighty_three_point_three_four(api):
    """36.67 x 2.0 plus the 10.00-point dark-anchor adder pins reduction_pct 83.34.

    PRD: "The shortfall is multiplied by the tier multiplier and that product is rounded half up to two decimal places; then, if any named anchor requirement of the breached condition is unsatisfied under the controlling figures — the named anchor not counted open and no qualifying substitute available — a flat 10.00 percentage points is added on top."

    Design: Difficulty/combinatorial_formula/rent_reduction_tier_three_plus_anchor_bonus_then_cap
    """
    _scenario, election = _elect_reduction_after_anchor_went_dark(api)

    assert election["anchor_bonus_applied"] is True
    assert_pct(election["reduction_pct"], 83.34, "reduction_pct")


def test_floor_then_cap_leaves_the_composed_reduction_untouched(api):
    """The 5.00 floor and the 90.0 cap both leave 83.34 exactly where it stands.

    PRD: "The result is raised to a minimum of 5.00 points, and the raised value is then lowered to a maximum of the condition's `max_reduction_pct`."

    Design: Difficulty/combinatorial_formula/rent_reduction_tier_three_plus_anchor_bonus_then_cap
    """
    scenario, election = _elect_reduction_after_anchor_went_dark(api)

    assert_pct(
        scenario["condition"]["max_reduction_pct"], 90.0, "max_reduction_pct"
    )
    assert_pct(fetch_election(api, election["id"])["reduction_pct"], 83.34, "reduction_pct")


def test_reduced_rent_snapshot_prices_the_election_alone(api):
    """1,000,000 cents at a 83.34 pct reduction snapshots 166,600 cents payable.

    PRD: "`reduced_rent_monthly_cents` is the lease's `base_rent_monthly_cents` multiplied by 100 minus `reduction_pct`, divided by 100, and rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/rent_reduction_tier_three_plus_anchor_bonus_then_cap
    """
    _scenario, election = _elect_reduction_after_anchor_went_dark(api)

    assert_cents(
        election["reduced_rent_monthly_cents"],
        166600,
        "reduced_rent_monthly_cents",
    )


def test_merely_elected_remedy_leaves_effective_rent_at_base(api):
    """An ELECTED reduction moves no rent: the lease still owes 1,000,000 cents.

    PRD: "A new election is created in `ELECTED` with `elected_at` stamped and `abated_to_date_cents` at 0, and an election in that status **does not yet change effective rent at all**."

    Design: Difficulty/combinatorial_formula/rent_reduction_tier_three_plus_anchor_bonus_then_cap
    """
    scenario, election = _elect_reduction_after_anchor_went_dark(api)

    assert election["status"] == "ELECTED"
    assert_cents(election["abated_to_date_cents"], 0, "abated_to_date_cents")
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I1")),
        effective_rent_monthly_cents=1000000,
    )


def test_one_breach_below_half_occupancy_freezes_the_center(api):
    """45.00 pct occupancy on an assessable center freezes it outright.

    PRD: "The posture is `FROZEN` when the breached-condition count is at least two, or when the center is assessable and its `open_occupancy_pct` is strictly below 50.00."

    Design: Difficulty/combinatorial_formula/rent_reduction_tier_three_plus_anchor_bonus_then_cap
    """
    scenario, _election = _elect_reduction_after_anchor_went_dark(api)

    center = fetch_center(api, scenario.center_id)
    assert_center_quantities(
        center, open_occupancy_pct=45.00, compliance_posture="FROZEN"
    )


# --------------------------------------------------------------------------
# The abatement ledger: round per election, then sum (PRD §2.7, §3.5)
# --------------------------------------------------------------------------
def _two_approved_adjacent_reductions(api):
    """Two 80-day half-open reduction windows on the same lease, both approved."""
    scenario = _build_five_suite_center(api)
    condition = add_condition(
        api,
        scenario.lease_id("I1"),
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    go_dark(api, scenario.lease_id("I3"))
    first = elect_remedy(
        api,
        scenario.lease_id("I1"),
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-10-20",
        condition_id=condition["id"],
    )
    approve_election(api, first["id"])
    second = elect_remedy(
        api,
        scenario.lease_id("I1"),
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        window_from_date="2026-10-20",
        window_through_date="2027-01-08",
        condition_id=condition["id"],
    )
    approve_election(api, second["id"])
    set_clock(api, "2027-02-01T00:00:00Z")
    scenario["condition"] = fetch_condition(api, condition["id"])
    return scenario, fetch_election(api, first["id"]), fetch_election(api, second["id"])


def test_middle_tier_multiplier_rounds_each_reduction_to_ten_point_zero_one(api):
    """A 6.67 shortfall at multiplier 1.5 rounds 10.005 half up to 10.01 per election.

    PRD: "A shortfall of at most 5.00 points takes a multiplier of 1.0; a shortfall above 5.00 but at most 15.00 takes 1.5; a shortfall above 15.00 takes 2.0."

    Design: Difficulty/combinatorial_formula/abatement_ledger_round_per_election_then_sum
    """
    _scenario, first, second = _two_approved_adjacent_reductions(api)

    assert_pct(first["shortfall_pct_at_election"], 6.67, "shortfall_pct_at_election")
    assert_pct(first["reduction_pct"], 10.01, "reduction_pct")
    assert_pct(second["reduction_pct"], 10.01, "reduction_pct")


def test_each_election_accrues_and_rounds_its_own_eighty_day_window(api):
    """80 days over 30 gives 2.6667 months, and each election rounds to 266,937 cents.

    PRD: "For one election, take the earlier of the current logical clock date and the election's `window_through_date` as the accrual end date; count the whole days from `window_from_date` to that end date, flooring the count at zero; divide that day count by 30 and round the quotient half up to four decimal places to obtain a month figure; then multiply the lease's `base_rent_monthly_cents` by the election's `reduction_pct`, divide by 100, multiply by the month figure, and **round half up to whole cents at this point, per election**."

    Design: Difficulty/combinatorial_formula/abatement_ledger_round_per_election_then_sum
    """
    _scenario, first, second = _two_approved_adjacent_reductions(api)

    assert_cents(first["abated_to_date_cents"], 266937, "abated_to_date_cents")
    assert_cents(second["abated_to_date_cents"], 266937, "abated_to_date_cents")


def test_total_abated_sums_the_already_rounded_per_election_amounts(api):
    """Round-then-sum yields 533,874 cents, one cent above the rejected sum-then-round.

    PRD: "The lease's `total_abated_cents` is then the sum of the already-rounded per-election amounts over the lease's elections whose `status` is `REDUCTION_ACTIVE` or `CONSUMMATED`."

    Design: Difficulty/combinatorial_formula/abatement_ledger_round_per_election_then_sum
    """
    scenario, _first, _second = _two_approved_adjacent_reductions(api)

    lease = fetch_lease(api, scenario.lease_id("I1"))
    assert_cents(lease["total_abated_cents"], 533874, "total_abated_cents")
    assert lease["total_abated_cents"] != 533873, (
        "total_abated_cents must not be produced by rounding once after the sum"
    )


def test_effective_rent_returns_to_base_once_no_window_covers_the_clock(api):
    """At 2027-02-01 neither half-open window covers today, so rent is 1,000,000 cents.

    PRD: "Gather the lease's elections whose `status` is `REDUCTION_ACTIVE` and whose half-open window covers the current logical clock date — the `window_from_date` on or before it and the `window_through_date` strictly after it."

    Design: Difficulty/combinatorial_formula/abatement_ledger_round_per_election_then_sum
    """
    scenario, _first, _second = _two_approved_adjacent_reductions(api)

    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I1")),
        effective_rent_monthly_cents=1000000,
    )


def test_aggregate_effective_rent_sums_the_open_and_dark_leases(api):
    """The five open-or-dark suites aggregate to 13,700,000 cents of effective rent.

    PRD: "The center's `aggregate_effective_rent_cents` is then the sum of `effective_rent_monthly_cents` over the leases of that center whose `premises_status` is `OPEN` or `DARK`."

    Design: Difficulty/combinatorial_formula/abatement_ledger_round_per_election_then_sum
    """
    scenario, _first, _second = _two_approved_adjacent_reductions(api)

    center = fetch_center(api, scenario.center_id)
    assert_center_quantities(center, aggregate_effective_rent_cents=13700000)


# --------------------------------------------------------------------------
# The estoppel fee: tier selected on the pre-surcharge subtotal (PRD §3.8)
# --------------------------------------------------------------------------
def _request_expedited_certificate_on_three_clauses(api):
    """Three active clauses benefit suite I2, then a lender requests an expedite."""
    scenario = _build_five_suite_center(api)
    add_clause(
        api,
        scenario.lease_id("I2"),
        protected_use_codes=["BOOKS"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )
    add_clause(
        api,
        scenario.lease_id("I2"),
        protected_use_codes=["STATIONERY"],
        exclusivity_scope="PAD_EXCLUDED",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=1500,
        incidental_sales_pct_cap=10.0,
    )
    add_clause(
        api,
        scenario.lease_id("I2"),
        protected_use_codes=["GREETING_CARDS"],
        exclusivity_scope="RADIUS_INCLUSIVE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=500,
        incidental_sales_pct_cap=5.0,
    )
    certificate = request_certificate(
        api, scenario.lease_id("I2"), expedite_requested=True
    )
    return scenario, certificate


def test_certificate_discloses_three_clauses_and_no_breach(api):
    """The certificate discloses three active clauses, no breach and 1,200,000 rent.

    PRD: "Three disclosures are computed at that same instant: `disclosed_cotenancy_breach` is true when at least one co-tenancy condition of the estopped lease is `BREACHED`; `disclosed_exclusive_count` is the number of `ACTIVE` exclusive-use clauses benefiting that lease; and `disclosed_effective_rent_cents` is the lease's `effective_rent_monthly_cents`."

    Design: Difficulty/combinatorial_formula/estoppel_fee_tier_keyed_on_presurcharge_subtotal
    """
    _scenario, certificate = _request_expedited_certificate_on_three_clauses(api)

    assert certificate["disclosed_exclusive_count"] == 3
    assert certificate["disclosed_cotenancy_breach"] is False
    assert_cents(
        certificate["disclosed_effective_rent_cents"],
        1200000,
        "disclosed_effective_rent_cents",
    )


def test_pre_surcharge_subtotal_is_base_plus_five_thousand_per_disclosure(api):
    """25,000 base plus three 5,000-cent disclosures makes base_fee_cents 40,000.

    PRD: "First, the pre-surcharge subtotal is 25,000 cents of base fee, plus 5,000 cents for each disclosed exclusive-use clause, plus a further 15,000 cents when `disclosed_cotenancy_breach` is true."

    Design: Difficulty/combinatorial_formula/estoppel_fee_tier_keyed_on_presurcharge_subtotal
    """
    _scenario, certificate = _request_expedited_certificate_on_three_clauses(api)

    assert_cents(certificate["base_fee_cents"], 40000, "base_fee_cents")


def test_surcharge_tier_is_keyed_on_the_subtotal_and_never_re_tiered(api):
    """A 40,000-cent subtotal takes the 10.0 pct tier, totalling 44,000 cents.

    PRD: "`total_fee_cents` is the subtotal plus the surcharge, and it is **never re-tiered** — a subtotal of exactly 40,000 cents takes the 10.0% tier even though the resulting total of 44,000 cents sits inside the next tier's range."

    Design: Difficulty/combinatorial_formula/estoppel_fee_tier_keyed_on_presurcharge_subtotal
    """
    _scenario, certificate = _request_expedited_certificate_on_three_clauses(api)

    assert certificate["expedite_requested"] is True
    assert_cents(certificate["total_fee_cents"], 44000, "total_fee_cents")
    assert certificate["total_fee_cents"] != 46000, (
        "the surcharge tier must not be re-selected on the post-surcharge total"
    )


def test_freshly_requested_certificate_has_no_lender_conditions_met(api):
    """A certificate straight out of the request is REQUESTED and not lender-ready.

    PRD: "`lender_conditions_met` is false on a freshly requested certificate."

    Design: Difficulty/combinatorial_formula/estoppel_fee_tier_keyed_on_presurcharge_subtotal
    """
    _scenario, certificate = _request_expedited_certificate_on_three_clauses(api)

    stored = fetch_certificate(api, certificate["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["lender_conditions_met"] is False
