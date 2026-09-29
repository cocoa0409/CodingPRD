"""Per diem claim pricing: the two bases and the per-day rounding of the half rate.

One month of census rows can be priced two ways, and the audited basis both caps
bed-hold days and halves their rate. These tests hold the census fixed and vary
only the basis, and separately pin the point at which the halved rate is rounded.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx


def _twelve_bed_hold_day_month(api):
    """A full August with nineteen resident days and twelve bed-hold days.

    The resident is admitted on the first, leaves for hospital on the tenth and
    returns on the twenty-second, and the checkpoint materialises the month once
    the month has closed.
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    fx.hospitalize(api, scenario.resident_id, "2026-08-10", clock="2026-08-10T00:00:00Z")
    fx.readmit(api, scenario.resident_id, "2026-08-22", clock="2026-08-22T00:00:00Z")
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.census_run(api, "2026-08-31", scenario.home_id)
    return scenario


def test_audited_basis_caps_payable_bed_hold_days_at_ten(api):
    """The audited basis pays only ten bed-hold days and pays them at half the daily rate.

    Per the PRD: "Payable bed-hold days are `bed_hold_day_count` capped at ten
    per claim month. `billable_day_count` is `resident_day_count` plus those
    payable bed-hold days — so bed-hold days beyond the cap are excluded from the
    billable count entirely". Twelve hold days are counted but only ten reach the
    billable total.

    Design: Difficulty/dual_variant_calc/per_diem_claim_census_vs_audited_basis_divergence
    """
    scenario = _twelve_bed_hold_day_month(api)

    claim = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )

    assert claim["basis"] == "AUDITED_BASIS"
    assert claim["resident_day_count"] == 19
    assert claim["bed_hold_day_count"] == 12
    assert claim["billable_day_count"] == 29
    assert claim["claim_amount_cents"] == 284573
    assert claim["census_reported_resident_count"] == 1


def test_rejection_releases_the_month_and_zeroes_the_paid_amount(api):
    """A rejected claim keeps its computed amount but is paid nothing.

    Per the PRD: "On an outcome of `REJECTED`, a `rejection_code` of
    `CENSUS_MISMATCH`, `RECOGNITION_LAPSE` or `DUPLICATE_PERIOD` is required;
    `status` becomes `REJECTED`, `adjudicated_at` is stamped, `paid_amount_cents`
    is set to 0, the code is stored, and every attributed census day is released
    with `per_diem_claim_id` set back to null and `claimed` back to false, which
    returns those days to the pool."

    Design: Difficulty/dual_variant_calc/per_diem_claim_census_vs_audited_basis_divergence
    """
    scenario = _twelve_bed_hold_day_month(api)
    claim = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )
    validate_success(fx.submit_claim(api, claim["id"]), 200)

    adjudicated = validate_success(
        fx.adjudicate_claim(
            api,
            claim["id"],
            outcome="REJECTED",
            rejection_code="CENSUS_MISMATCH",
            note="resubmit on census basis",
        ),
        200,
    )

    assert adjudicated["status"] == "REJECTED"
    assert adjudicated["paid_amount_cents"] == 0
    assert adjudicated["claim_amount_cents"] == 284573


def test_census_basis_correction_reprices_the_same_month_upwards(api):
    """Repricing the identical census on the census basis drops the cap and the half rate.

    Per the PRD: "Under `CENSUS_BASIS`, there is no cap and no half rate:
    `billable_day_count` is `resident_day_count` plus the whole
    `bed_hold_day_count`, and `claim_amount_cents` is the full rate times
    `billable_day_count`." The correcting claim inherits the month and the unit,
    names its target and carries the next correction generation.

    Design: Difficulty/dual_variant_calc/per_diem_claim_census_vs_audited_basis_divergence
    """
    scenario = _twelve_bed_hold_day_month(api)
    first = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )
    validate_success(fx.submit_claim(api, first["id"]), 200)
    validate_success(
        fx.adjudicate_claim(
            api,
            first["id"],
            outcome="REJECTED",
            rejection_code="CENSUS_MISMATCH",
            note="resubmit on census basis",
        ),
        200,
    )

    second = validate_success(
        fx.correct_claim(
            api,
            first["id"],
            correction_note="recomputed on census basis",
            basis="CENSUS_BASIS",
        ),
        201,
    )

    assert second["basis"] == "CENSUS_BASIS"
    assert second["corrects_claim_id"] == first["id"]
    assert second["correction_generation"] == 1
    assert second["resident_day_count"] == 19
    assert second["bed_hold_day_count"] == 12
    assert second["billable_day_count"] == 31
    assert second["claim_amount_cents"] == 367567
    assert second["status"] == "DRAFT"
    assert second["claim_amount_cents"] - first["claim_amount_cents"] == 82994


def _three_bed_hold_day_month(api):
    """A full August with twenty-eight resident days and exactly three bed-hold days."""
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    fx.hospitalize(api, scenario.resident_id, "2026-08-10", clock="2026-08-10T00:00:00Z")
    fx.readmit(api, scenario.resident_id, "2026-08-13", clock="2026-08-13T00:00:00Z")
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.census_run(api, "2026-08-31", scenario.home_id)
    return scenario


def test_bed_hold_half_rate_is_rounded_once_per_day_before_multiplication(api):
    """The halved nursing rate is rounded per day, so three hold days price at 17,787 cents.

    Per the PRD: "At the `NURSING` rate of 11,857 cents over three bed-hold days,
    the correct order rounds 5,928.5 up to 5,929 and multiplies to 17,787 cents;
    rounding the monthly total instead would give 17,786 cents." The one-cent
    difference lands on the claim total.

    Design: Difficulty/combinatorial_formula/per_diem_bed_hold_per_day_rounding_order_pinned
    """
    scenario = _three_bed_hold_day_month(api)

    claim = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )

    assert claim["claim_amount_cents"] == 349783
    assert claim["claim_amount_cents"] != 349782


def test_three_day_hold_is_counted_on_both_the_claim_and_the_resident(api):
    """A three-day hospitalisation yields three bed-hold days and twenty-eight resident days.

    Per the PRD: "The consequences are worth stating plainly: the
    `hospitalization_start_date` is itself a `BED_HOLD_DAY`, and the
    `readmission_date` is itself a `RESIDENT_DAY`." All thirty-one August dates
    are therefore billable, and none of the hold days exceeds the ten-day cap.

    Design: Difficulty/combinatorial_formula/per_diem_bed_hold_per_day_rounding_order_pinned
    """
    scenario = _three_bed_hold_day_month(api)

    claim = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )

    assert claim["resident_day_count"] == 28
    assert claim["bed_hold_day_count"] == 3
    assert claim["billable_day_count"] == 31
    assert fx.read_resident(api, scenario.resident_id)["bed_hold_days_used"] == 3
