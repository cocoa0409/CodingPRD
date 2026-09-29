"""Three arithmetic surfaces: which lines count, what a line costs, when to round.

None of the three needs a long chain to expose — a cancelled study, a price list and
two fifty-minute shifts are enough to separate an implementation that reads the
declared inputs from one that reads the convenient ones.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_hours_equal,
    assert_line_total,
    assert_total_count,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    OFFICER,
    PHYSICIAN,
    acknowledge_disclosure,
    create_claim,
    create_payer_contract,
    create_physician_shift,
    create_volume_forecast,
    coverage_summary,
    discharge,
    open_facility,
    order_ancillary,
    read_facility,
    register_encounter,
    resolve_ancillary,
    screen_encounter,
)

WORKING_INSTANT = "2026-08-01T08:00:00Z"
NARROW_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}
FACILITY_FEE_CENTS = 145000
RESULTED_CT_PAIR_CENTS = 98000
CANCELLED_CBC_CENTS = 4500
BILLED_TOTAL_WITHOUT_THE_CANCELLED_LINE = 243000
FIFTY_MINUTE_SHIFT_HOURS = "0.83"
TWO_FIFTY_MINUTE_SHIFTS_HOURS = "1.66"
FLOOR_TOTAL_HOURS = "12.00"
FLOOR_BOARD_CERTIFIED_HOURS = "9.00"
DEFICIT_AGAINST_THE_FLOOR_HOURS = "10.34"


def test_a_cancelled_study_is_never_billed_even_though_it_was_priced():
    """Both lines carry a line total; only the resulted one reaches the claim.

    PRD 3.9: "`billed_ancillary_cents` is the sum of `line_total_cents` over the
    encounter's ancillary orders whose `status` is `RESULTED`; `ORDERED` and `CANCELLED`
    lines contribute nothing." and "`billed_facility_fee_cents` is copied from the
    `facility_fee_cents` of the template the encounter pinned at registration — not from
    whatever template happens to be published today." with "`billed_total_cents` is the sum
    of those two figures."  The cancelled line keeps its price, because PRD 3.7 says
    "`line_total_cents` is `unit_charge_cents` multiplied by `quantity` — an exact integer
    product with no rounding — and that relationship holds for every order in every status,
    for the life of the row."  The claim's own opening posture is PRD 3.9's: "The claim is
    created with `status` `DRAFT`, with `negotiation_rounds_used` 0" and with
    "`allowed_amount_cents`, `plan_paid_cents`, `patient_responsibility_cents`,
    `balance_bill_amount_cents` and `written_off_cents` all unset until adjudication."

    Design: Corner/calculations/billed_ancillary_cents_counts_only_resulted_orders
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    contract = create_payer_contract(
        context["facility_id"],
        OFFICER,
        payer_name="Lone Star Health",
        network_status="OUT_OF_NETWORK",
        state_protection_regime="FEDERAL_NSA_ONLY",
    )
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-1301",
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")

    kept = order_ancillary(encounter["id"], "IMAGING", "CT", 2)
    dropped = order_ancillary(encounter["id"], "LABORATORY", "CBC", 1)
    resulted = resolve_ancillary(kept["id"], "RESULTED")
    cancelled = resolve_ancillary(dropped["id"], "CANCELLED")
    discharge(encounter["id"])

    assert resulted["status"] == "RESULTED"
    assert resulted["line_total_cents"] == RESULTED_CT_PAIR_CENTS
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["line_total_cents"] == CANCELLED_CBC_CENTS

    claim = create_claim(encounter["id"], contract["id"], OFFICER)

    assert claim["billed_facility_fee_cents"] == FACILITY_FEE_CENTS
    assert claim["billed_ancillary_cents"] == RESULTED_CT_PAIR_CENTS
    assert claim["billed_total_cents"] == BILLED_TOTAL_WITHOUT_THE_CANCELLED_LINE
    assert claim["status"] == "DRAFT"
    assert claim["protection_variant"] == "PROTECTED_NSA"
    assert claim.get("allowed_amount_cents") is None


def test_each_ancillary_line_is_priced_from_the_schedule_and_multiplied_by_quantity():
    """Three codes from three categories, each taking its own constant.

    PRD 3.7: "`unit_charge_cents` is looked up by `code`: 12000 for `XRAY`, 49000 for `CT`,
    24000 for `ULTRASOUND`, 145000 for `MRI`, 4500 for `CBC`, 6200 for `CHEMISTRY`, 15500
    for `TROPONIN`, 11500 for `BLOOD_CULTURE`, 8500 for `ANALGESIC`, 7400 for `ANTIBIOTIC`,
    and 210000 for `THROMBOLYTIC`. `line_total_cents` is `unit_charge_cents` multiplied by
    `quantity` — an exact integer product with no rounding — and that relationship holds for
    every order in every status, for the life of the row. The order is created with `status`
    `ORDERED`, and creation has no billing effect yet."

    Design: Corner/calculations/ancillary_unit_charge_constants_are_applied_per_code_and_multiplied_by_quantity
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-1401",
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")

    films = order_ancillary(encounter["id"], "IMAGING", "XRAY", 3)
    troponins = order_ancillary(encounter["id"], "LABORATORY", "TROPONIN", 2)
    analgesic = order_ancillary(encounter["id"], "PHARMACY", "ANALGESIC", 1)

    assert films["unit_charge_cents"] == 12000
    assert films["line_total_cents"] == 36000
    assert troponins["unit_charge_cents"] == 15500
    assert troponins["line_total_cents"] == 31000
    assert analgesic["unit_charge_cents"] == 8500
    assert analgesic["line_total_cents"] == 8500

    for order in (films, troponins, analgesic):
        assert order["status"] == "ORDERED"
        assert_line_total(order)

    _, meta = validate_paginated(
        api_client.list_ancillary_orders(encounter["id"], PHYSICIAN)
    )
    assert_total_count(meta, 3)


def test_coverage_hours_are_rounded_per_shift_before_they_are_summed():
    """Two fifty-minute shifts total 1.66 hours, not the 1.67 the raw minutes give.

    PRD 3.4: "For each candidate, the clipped span runs from the later of the block's
    `start_utc` and the period start to the earlier of the block's `end_utc` and the period
    end; that span in minutes is divided by 60 and rounded half up to two decimals to give
    the block's contribution. `scheduled_physician_hours` is the sum of those per-block
    contributions, rounded half up to two decimals again."  Each block's own figure follows
    the same convention: "Its `duration_hours` is the elapsed time from `start_utc` to
    `end_utc` expressed in hours and rounded half up to two decimals."  The requirement it
    is measured against is the empty-history floor — "`required_physician_hours_per_day` is
    set to the coverage floor of 12 hours per day" — three quarters of which must be board
    certified, and PRD 3.4 pins both the shortfall and the verdict: "`coverage_deficit_hours`
    is the shortfall of `required_physician_hours_total` against `scheduled_physician_hours`,
    rounded half up to two decimals, and floored at 0 so that over-coverage never produces a
    negative deficit. A facility is `coverage_compliant` only when `coverage_deficit_hours`
    is exactly 0 **and** `board_certified_hours` is at least
    `required_board_certified_hours_total`".

    Design: Corner/calculations/scheduled_coverage_hours_round_per_shift_before_summing
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]

    forecast = create_volume_forecast(
        facility_id,
        period_start_date="2026-08-03",
        period_days=1,
        historical_daily_volumes=[],
        method="TRAILING_MEAN",
    )
    first_shift = create_physician_shift(
        facility_id,
        ADMIN,
        clinician_user_id="doc-a",
        role_type="PHYSICIAN",
        board_certified=True,
        start_utc="2026-08-03T08:00:00Z",
        end_utc="2026-08-03T08:50:00Z",
    )
    second_shift = create_physician_shift(
        facility_id,
        ADMIN,
        clinician_user_id="doc-a",
        role_type="PHYSICIAN",
        board_certified=True,
        start_utc="2026-08-03T09:00:00Z",
        end_utc="2026-08-03T09:50:00Z",
    )

    assert_hours_equal(
        first_shift["duration_hours"], FIFTY_MINUTE_SHIFT_HOURS, "first duration_hours"
    )
    assert_hours_equal(
        second_shift["duration_hours"], FIFTY_MINUTE_SHIFT_HOURS, "second duration_hours"
    )

    summary = coverage_summary(
        facility_id, OFFICER, params={"volume_forecast_id": forecast["id"]}
    )

    assert summary["forecast_basis"] == "FLOOR_ONLY"
    assert_hours_equal(
        summary["required_physician_hours_per_day"], FLOOR_TOTAL_HOURS, "required per day"
    )
    assert_hours_equal(
        summary["required_physician_hours_total"], FLOOR_TOTAL_HOURS, "required total"
    )
    assert_hours_equal(
        summary["required_board_certified_hours_total"],
        FLOOR_BOARD_CERTIFIED_HOURS,
        "required board-certified",
    )
    assert_hours_equal(
        summary["scheduled_physician_hours"], TWO_FIFTY_MINUTE_SHIFTS_HOURS, "scheduled"
    )
    assert_hours_equal(
        summary["board_certified_hours"], TWO_FIFTY_MINUTE_SHIFTS_HOURS, "board certified"
    )
    assert_hours_equal(
        summary["coverage_deficit_hours"], DEFICIT_AGAINST_THE_FLOOR_HOURS, "deficit"
    )
    assert summary["coverage_compliant"] is False

    stored = validate_success(
        api_client.get_volume_forecast(forecast["id"], ADMIN)
    )
    assert_hours_equal(
        stored["scheduled_physician_hours"],
        TWO_FIFTY_MINUTE_SHIFTS_HOURS,
        "stored scheduled",
    )
    assert_hours_equal(
        stored["coverage_deficit_hours"],
        DEFICIT_AGAINST_THE_FLOOR_HOURS,
        "stored deficit",
    )
    assert read_facility(facility_id)["coverage_deficit_flag"] is True
