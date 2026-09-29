"""Values sitting exactly on a rounding or counting boundary."""

from test_helpers import (
    INSPECTOR,
    ApiErrorId,
    CORN_NO_1_AT_14_04_MOISTURE,
    CORN_NO_2_AT_14_05_MOISTURE,
    SOYBEANS_NO_2_FACTORS,
    api_client,
    break_sample_seal,
    protein_analysis_payload,
    read_request,
    read_sample,
    setup_graded_request,
    setup_office,
    validate_error,
)


def test_a_corn_lot_reading_1404_moisture_is_compared_at_140():
    """Because rounding happens first, a corn lot reading 14.04 moisture is
    compared at 14.0 and can still make `US_NO_1`, while one reading 14.05 is
    compared at 14.1 and lands at `US_NO_2` with `MOISTURE` as the limiting
    factor.

    When the assigned grade is the best grade of the commodity's table,
    `limiting_factor` is `NONE`.

    Design: Difficulty/boundary_precision_check/moisture_round_half_up_at_14_045_flips_grade_and_limiting_factor
    """
    office = setup_office("DESIGNATED")
    staged = setup_graded_request(
        office,
        factors=CORN_NO_1_AT_14_04_MOISTURE,
        portions_count=2,
        lot_identifier="LOT-1404",
    )
    grading = staged["grading"]

    assert grading["rounded_factors"]["moisture_pct"] == 14.0
    assert grading["assigned_grade"] == "US_NO_1"
    assert grading["limiting_factor"] == "NONE"
    assert grading["moisture_pct"] == 14.04
    assert grading["rounded_factors"]["test_weight_lbs_per_bushel"] == 56.0
    assert grading["rounded_factors"]["heat_damaged_pct"] == 0.1
    assert read_request(staged["request"]["id"])["grading_status"] == "GRADED"


def test_the_same_lot_one_hundredth_wetter_rounds_up_and_loses_the_grade():
    """The five grading factors are each rounded to **1 decimal place, round half
    up**, before any comparison against a factor table; the rounded set is
    retained on the determination and is what every downstream consumer reads.

    Otherwise the system looks at the grade immediately better than the assigned
    one — and for `SAMPLE_GRADE`, at the worst numerical grade of that
    commodity's table — and reports the first factor, in the fixed order
    `TEST_WEIGHT`, `MOISTURE`, `DAMAGED_TOTAL`, `HEAT_DAMAGED`,
    `FOREIGN_MATERIAL`, whose rounded value violates that better grade's limit.

    Design: Difficulty/boundary_precision_check/moisture_round_half_up_at_14_045_flips_grade_and_limiting_factor
    """
    office = setup_office("DESIGNATED")
    staged = setup_graded_request(
        office,
        factors=CORN_NO_2_AT_14_05_MOISTURE,
        portions_count=2,
        lot_identifier="LOT-1405",
    )
    grading = staged["grading"]

    assert grading["rounded_factors"]["moisture_pct"] == 14.1
    assert grading["assigned_grade"] == "US_NO_2"
    assert grading["limiting_factor"] == "MOISTURE"
    assert grading["moisture_pct"] == 14.05
    assert read_request(staged["request"]["id"])["grading_status"] == "GRADED"


def test_consuming_the_last_portion_reports_exhaustion_and_not_broken_integrity():
    """When a consumption drives `portions_available` to 0 the sample moves
    `SEALED → CONSUMED`; the compensating release described in §3.3 moves it
    back `CONSUMED → SEALED`.

    Any of those three operations attempted when `portions_available` is 0 is
    refused with `ERR_SAMPLE_PORTIONS_EXHAUSTED`.

    Design: Difficulty/boundary_precision_check/last_sample_portion_exhaustion_at_exactly_zero_available
    """
    office = setup_office("DESIGNATED")
    staged = setup_graded_request(
        office,
        commodity="SOYBEANS",
        factors=SOYBEANS_NO_2_FACTORS,
        requested_services=("GRADING", "PROTEIN"),
        portions_count=1,
        lot_identifier="LOT-SOY1",
    )
    assert staged["grading"]["assigned_grade"] == "US_NO_2"
    assert staged["grading"]["limiting_factor"] == "TEST_WEIGHT"

    sample = read_sample(staged["sample"]["id"])
    assert sample["portions_consumed"] == 1
    assert sample["portions_retained"] == 0
    assert sample["portions_available"] == 0
    assert sample["integrity_status"] == "CONSUMED"

    response = api_client.create_protein_analysis(
        protein_analysis_payload(
            staged["request"]["id"],
            staged["sample"]["id"],
            office["instrument"]["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    validate_error(response, ApiErrorId.ERR_SAMPLE_PORTIONS_EXHAUSTED.value, 422)


def test_a_broken_seal_outranks_exhaustion_on_the_very_same_sample():
    """A `SupervisingInspector` may record a broken seal with an optional
    `reason`, moving the sample `SEALED → BROKEN` or `CONSUMED → BROKEN`; from
    `SEALED` this is only permitted when no non-terminal appeal currently holds
    the sample as its assigned regrade sample, and from `CONSUMED` there is no
    further precondition.

    Both `BROKEN` and `EXPIRED` are terminal, and a sample in either state that
    is offered for a grading determination, an analysis or an appeal assignment
    is refused with `ERR_SAMPLE_INTEGRITY_BROKEN`.

    Design: Difficulty/boundary_precision_check/last_sample_portion_exhaustion_at_exactly_zero_available
    """
    office = setup_office("DESIGNATED")
    staged = setup_graded_request(
        office,
        commodity="SOYBEANS",
        factors=SOYBEANS_NO_2_FACTORS,
        requested_services=("GRADING", "PROTEIN"),
        portions_count=1,
        lot_identifier="LOT-SOY1",
    )
    broken = break_sample_seal(staged["sample"]["id"])
    assert broken["integrity_status"] == "BROKEN"

    response = api_client.create_protein_analysis(
        protein_analysis_payload(
            staged["request"]["id"],
            staged["sample"]["id"],
            office["instrument"]["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    validate_error(response, ApiErrorId.ERR_SAMPLE_INTEGRITY_BROKEN.value, 409)
