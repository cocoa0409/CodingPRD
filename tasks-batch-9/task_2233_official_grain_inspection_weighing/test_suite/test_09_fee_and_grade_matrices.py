"""Combinatorial matrices: the fee formula, the discount tiers and the grade walk."""

from test_helpers import (
    AFTER_HOURS_CLOCK,
    CORN_NO_2_FACTORS,
    SIX_CORN_DRAFTS,
    SIX_CORN_DRAFTS_DOCKAGE_PCT,
    SOYBEANS_NO_2_FACTORS,
    assert_certificate,
    assert_ledger,
    assert_rounded_factors,
    issue_certificate,
    read_applicant,
    read_sample,
    set_clock,
    setup_graded_and_weighed_request,
    setup_graded_request,
    setup_office,
)


COMBINED_SCHEDULES = (
    {
        "service_class": "GRADING",
        "base_fee_cents": 12000,
        "per_thousand_bushel_rate_cents": 3000,
        "overtime_multiplier_bp": 2500,
        "minimum_fee_cents": 15000,
    },
    {
        "service_class": "WEIGHING",
        "base_fee_cents": 9000,
        "per_thousand_bushel_rate_cents": 1500,
        "overtime_multiplier_bp": 2500,
        "minimum_fee_cents": 10000,
    },
)

TIERED_GRADING_SCHEDULE = (
    {
        "service_class": "GRADING",
        "base_fee_cents": 8000,
        "per_thousand_bushel_rate_cents": 2000,
        "minimum_fee_cents": 10000,
    },
)


def _combined_office(clock=None):
    kwargs = {
        "area_overrides": {"fee_multiplier_bp": 11500, "supervision_required": False},
        "fee_schedules": COMBINED_SCHEDULES,
    }
    if clock is not None:
        kwargs["clock"] = clock
    return setup_office("DESIGNATED", **kwargs)


def _combined_certificate(office, lot_identifier):
    staged = setup_graded_and_weighed_request(
        office,
        drafts=SIX_CORN_DRAFTS,
        dockage_pct=SIX_CORN_DRAFTS_DOCKAGE_PCT,
        declared_quantity_bushels=3500,
        lot_identifier=lot_identifier,
    )
    return issue_certificate(
        staged["request"]["id"], office["inspector"]["id"], "COMBINED"
    )


def test_combined_certificate_prices_both_classes_inside_standard_hours():
    """Divide `certified_quantity_bushels` by 1000 and round the result **up**
    to the next whole number to obtain the billed thousands. The service charge
    is the sum of `base_fee_cents` over the applicable schedules plus the
    billed thousands multiplied by the sum of `per_thousand_bushel_rate_cents`
    over the same schedules.

    The area's authority adjustment is then the discounted amount multiplied by
    the area's `fee_multiplier_bp` less 10000, divided by 10000, rounded half
    up to whole cents, and added.

    `overtime_applied` is true when `issued_at` falls outside standard hours,
    which run from 07:00:00Z inclusive to 17:00:00Z exclusive; when it is true,
    the overtime surcharge is the service charge multiplied by the **largest**
    `overtime_multiplier_bp` among the applicable schedules and divided by
    10000, rounded half up to whole cents, and when it is false the surcharge
    is 0.

    Design: Difficulty/combinatorial_formula/fee_matrix_mode_a_overtime_times_authority_multiplier
    """
    office = _combined_office()

    certificate = _combined_certificate(office, "LOT-DAY")

    assert_certificate(certificate)
    assert certificate["fee_total_cents"] == 44850
    assert certificate["fee_paid_cents"] == 0
    assert certificate["fee_settlement_status"] == "UNPAID"


def test_after_hours_issuance_adds_the_overtime_surcharge_before_the_adjustment():
    """`overtime_applied` is true when `issued_at` falls outside standard
    hours, which run from 07:00:00Z inclusive to 17:00:00Z exclusive; when it
    is true, the overtime surcharge is the service charge multiplied by the
    **largest** `overtime_multiplier_bp` among the applicable schedules and
    divided by 10000, rounded half up to whole cents, and when it is false the
    surcharge is 0.

    A volume discount tier is chosen from that subtotal: below 50000 cents the
    discount rate is 0 basis points; from 50000 cents up to but not including
    150000 cents it is 500 basis points; at 150000 cents and above it is 1000
    basis points.

    Design: Difficulty/combinatorial_formula/fee_matrix_mode_a_overtime_times_authority_multiplier
    """
    office = _combined_office(clock=AFTER_HOURS_CLOCK)

    certificate = _combined_certificate(office, "LOT-NIGHT")

    assert certificate["fee_total_cents"] == 56063


def test_two_combined_certificates_number_and_charge_per_applicant():
    """Issuance stamps `issued_at` from the logical clock, assigns a
    `sequence_no` that is monotonically increasing per applicant starting at 1,
    and freezes the state of the request into snapshots: `grade_snapshot` and
    `limiting_factor_snapshot` copy the `assigned_grade` and `limiting_factor`
    of the request's `FINAL` determination and are null on a `WEIGHT`
    certificate; `net_lbs_snapshot` and `net_bushels_snapshot` copy the
    operative weighing record's `net_lbs` and `net_bushels` and are null when
    no weighing is certified; `protein_reported_pct_snapshot` copies the
    operative analysis's `protein_reported_pct` and is null when protein was
    not ordered; and `certified_quantity_bushels` copies the request's own
    `certified_quantity_bushels`, which is what the fee is assessed on.

    The assessed fee is charged before the certificate is returned: it is added
    to the applicant's `charges_total_cents`, `open_balance_cents` is
    recomputed, and the certificate begins with `fee_paid_cents` 0 and
    `fee_settlement_status` `UNPAID`.

    Design: Difficulty/combinatorial_formula/fee_matrix_mode_a_overtime_times_authority_multiplier
    """
    office = _combined_office()

    day_certificate = _combined_certificate(office, "LOT-DAY")
    set_clock(AFTER_HOURS_CLOCK)
    night_certificate = _combined_certificate(office, "LOT-NIGHT")

    assert day_certificate["sequence_no"] == 1
    assert night_certificate["sequence_no"] == 2
    assert day_certificate["fee_total_cents"] == 44850
    assert night_certificate["fee_total_cents"] == 56063
    assert night_certificate["fee_settlement_status"] == "UNPAID"

    applicant = read_applicant(office["applicant"]["id"])
    assert_ledger(applicant, charges=100913, credits=0, open_balance=100913)


def test_grade_certificate_below_the_discount_tier_pays_the_undiscounted_fee():
    """A volume discount tier is chosen from that subtotal: below 50000 cents
    the discount rate is 0 basis points; from 50000 cents up to but not
    including 150000 cents it is 500 basis points; at 150000 cents and above it
    is 1000 basis points.

    Divide `certified_quantity_bushels` by 1000 and round the result **up** to
    the next whole number to obtain the billed thousands.

    Design: Difficulty/combinatorial_formula/fee_tier_mode_b_discount_inversion_at_50000_boundary
    """
    office = setup_office("DELEGATED", fee_schedules=TIERED_GRADING_SCHEDULE)
    staged = setup_graded_request(
        office, declared_quantity_bushels=20000, lot_identifier="LOT-20000"
    )

    certificate = issue_certificate(
        staged["request"]["id"], office["inspector"]["id"], "GRADE"
    )

    assert certificate["fee_total_cents"] == 48000


def test_a_larger_lot_crossing_the_tier_boundary_costs_less_than_a_smaller_one():
    """Because the tier is chosen from the subtotal rather than applied
    progressively, a larger lot can attract a smaller total than a slightly
    smaller one that just misses a tier boundary.

    Within fee assessment, the volume discount is truncated downward to whole
    cents (floor), while the overtime surcharge and the authority adjustment are
    rounded half up to whole cents.

    Design: Difficulty/combinatorial_formula/fee_tier_mode_b_discount_inversion_at_50000_boundary
    """
    office = setup_office("DELEGATED", fee_schedules=TIERED_GRADING_SCHEDULE)
    smaller = setup_graded_request(
        office, declared_quantity_bushels=20000, lot_identifier="LOT-20000"
    )
    smaller_certificate = issue_certificate(
        smaller["request"]["id"], office["inspector"]["id"], "GRADE"
    )
    larger = setup_graded_request(
        office,
        declared_quantity_bushels=20500,
        lot_identifier="LOT-20500",
        seal_number="SEAL-B1",
    )

    larger_certificate = issue_certificate(
        larger["request"]["id"], office["inspector"]["id"], "GRADE"
    )

    assert larger_certificate["fee_total_cents"] == 47500
    assert larger_certificate["fee_total_cents"] < smaller_certificate["fee_total_cents"]

    applicant = read_applicant(office["applicant"]["id"])
    assert_ledger(applicant, charges=95500, credits=0, open_balance=95500)


def test_corn_factor_walk_lands_on_the_first_grade_whose_limits_all_hold():
    """The official table for the request's `commodity` is then walked from the
    best grade downwards, and `assigned_grade` becomes the first grade all of
    whose limits the rounded set satisfies: the rounded test weight must be at
    least the grade's minimum test weight, and the rounded moisture, total
    damage, heat damage and foreign material must each be at most the grade's
    respective maximum.

    Otherwise the system looks at the grade immediately better than the assigned
    one — and for `SAMPLE_GRADE`, at the worst numerical grade of that
    commodity's table — and reports the first factor, in the fixed order
    `TEST_WEIGHT`, `MOISTURE`, `DAMAGED_TOTAL`, `HEAT_DAMAGED`,
    `FOREIGN_MATERIAL`, whose rounded value violates that better grade's limit.

    On success one portion is consumed and the original determination advances
    the request `SAMPLED → GRADED`.

    Design: Difficulty/combinatorial_formula/grade_matrix_mode_c_five_factor_predicate_walk
    """
    office = setup_office("DESIGNATED")
    staged = setup_graded_request(
        office, commodity="CORN", factors=CORN_NO_2_FACTORS, portions_count=2
    )
    grading = staged["grading"]

    assert grading["assigned_grade"] == "US_NO_2"
    assert grading["limiting_factor"] == "TEST_WEIGHT"
    assert_rounded_factors(grading)
    assert grading["rounded_factors"] == {
        "test_weight_lbs_per_bushel": 55.2,
        "moisture_pct": 14.0,
        "damaged_total_pct": 4.0,
        "heat_damaged_pct": 0.2,
        "foreign_material_pct": 2.5,
    }

    sample = read_sample(staged["sample"]["id"])
    assert sample["portions_consumed"] == 1
    assert sample["portions_available"] == 1


def test_soybean_factor_walk_uses_the_soybean_table_limits():
    """The five grading factors are each rounded to **1 decimal place, round half
    up**, before any comparison against a factor table; the rounded set is
    retained on the determination and is what every downstream consumer reads.

    When the assigned grade is the best grade of the commodity's table,
    `limiting_factor` is `NONE`.

    Design: Difficulty/combinatorial_formula/grade_matrix_mode_c_five_factor_predicate_walk
    """
    office = setup_office("DESIGNATED")
    staged = setup_graded_request(
        office,
        commodity="SOYBEANS",
        factors=SOYBEANS_NO_2_FACTORS,
        portions_count=2,
        lot_identifier="LOT-SOY",
    )
    grading = staged["grading"]

    assert grading["assigned_grade"] == "US_NO_2"
    assert grading["limiting_factor"] == "TEST_WEIGHT"
    assert grading["rounded_factors"]["moisture_pct"] == 13.0
    assert grading["rounded_factors"]["test_weight_lbs_per_bushel"] == 55.0
