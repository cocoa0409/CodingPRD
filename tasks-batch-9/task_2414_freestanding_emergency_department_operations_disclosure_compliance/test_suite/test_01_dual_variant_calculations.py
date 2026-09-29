"""Two calculations that each carry two variants, driven on identical inputs.

Both the claim settlement and the physician-coverage forecast select a variant
and then compute; the point of these tests is that the *same* input produces two
different, fully pinned answers depending on which variant was selected.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_hours_equal,
    assert_money_conservation,
    assert_settlement,
)
from test_helpers.api_client import api_client
from test_helpers.factories import make_adjudicate_payload, make_claim_payload
from test_helpers.fixtures import (
    CLERK,
    OFFICER,
    PAYER,
    acknowledge_disclosure,
    add_canonical_resulted_lines,
    create_volume_forecast,
    discharge,
    open_facility,
    protected_nsa_contract,
    protected_state_contract,
    read_facility,
    register_encounter,
    screen_encounter,
)

FACILITY_OVERRIDES = {
    "observation_bed_count": 4,
    "imaging_scope": ["XRAY", "CT", "ULTRASOUND"],
    "lab_scope": ["CBC", "CHEMISTRY", "TROPONIN"],
}
HISTORY = [22, 19, 26, 31, 18, 24, 29]


def _billable_closed_encounter(facility_id, patient_reference):
    """Register, acknowledge, screen, result the canonical lines and discharge."""
    encounter = register_encounter(
        facility_id,
        CLERK,
        patient_reference=patient_reference,
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")
    add_canonical_resulted_lines(encounter["id"])
    discharge(encounter["id"])
    return encounter["id"]


def _two_claims_on_two_regimes():
    """One facility, two out-of-network contracts, two byte-identical billed bundles."""
    context = open_facility(facility_overrides=FACILITY_OVERRIDES)
    facility_id = context["facility_id"]
    nsa_contract = protected_nsa_contract(
        facility_id, OFFICER, payer_name="Lone Star Health"
    )
    state_contract = protected_state_contract(
        facility_id, OFFICER, payer_name="Bluebonnet Mutual"
    )
    nsa_encounter = _billable_closed_encounter(facility_id, "PT-1001")
    state_encounter = _billable_closed_encounter(facility_id, "PT-1002")
    nsa_claim = validate_success(
        api_client.create_claim(
            nsa_encounter, make_claim_payload(nsa_contract["id"]), OFFICER
        ),
        expected_status=201,
    )
    state_claim = validate_success(
        api_client.create_claim(
            state_encounter, make_claim_payload(state_contract["id"]), OFFICER
        ),
        expected_status=201,
    )
    return nsa_claim, state_claim


def test_state_benchmark_allowed_total_outranks_the_qualifying_payment_amount():
    """The two protected variants recognise different allowed totals on one billed bundle.

    PRD 3.9 step two: "Under `PROTECTED_STATE`, the allowed total is the larger of
    the contract's `qualifying_payment_amount_cents` and the billed total
    multiplied by the state benchmark of eighty percent, that product rounded half
    up to whole cents".  PRD 3.9 also pins the other side: "Under both
    `PROTECTED_NSA` and `UNPROTECTED`, the allowed total is the contract's
    `qualifying_payment_amount_cents` unchanged."  282500 * 0.80 = 226000 beats
    the 190000 qualifying payment amount, so the state contract allows 226000.

    Design: Difficulty/dual_variant_calc/claim_settlement_protected_state_diverges_from_protected_nsa_on_identical_lines
    """
    nsa_claim, state_claim = _two_claims_on_two_regimes()

    assert nsa_claim["billed_total_cents"] == 282500
    assert state_claim["billed_total_cents"] == 282500
    assert nsa_claim["protection_variant"] == "PROTECTED_NSA"
    assert state_claim["protection_variant"] == "PROTECTED_STATE"

    adjudicated_nsa = validate_success(
        api_client.adjudicate_claim(nsa_claim["id"], make_adjudicate_payload(), PAYER)
    )
    adjudicated_state = validate_success(
        api_client.adjudicate_claim(state_claim["id"], make_adjudicate_payload(), PAYER)
    )

    assert adjudicated_nsa["allowed_amount_cents"] == 190000
    assert adjudicated_state["allowed_amount_cents"] == 226000


def test_protected_state_and_protected_nsa_settle_identical_lines_differently():
    """Cost share, plan payment and write-off all move with the allowed total.

    PRD 3.9 step six: "Under `PROTECTED_NSA` and `PROTECTED_STATE`,
    `patient_responsibility_cents` is the cost share, `balance_bill_amount_cents`
    is 0, and `written_off_cents` is the billed total less the allowed total".  The
    higher state allowed total therefore raises the patient's cost share by 7201
    cents and shrinks the write-off, on line sets that are identical to the cent.

    Design: Difficulty/dual_variant_calc/claim_settlement_protected_state_diverges_from_protected_nsa_on_identical_lines
    """
    nsa_claim, state_claim = _two_claims_on_two_regimes()

    adjudicated_nsa = validate_success(
        api_client.adjudicate_claim(nsa_claim["id"], make_adjudicate_payload(), PAYER)
    )
    adjudicated_state = validate_success(
        api_client.adjudicate_claim(state_claim["id"], make_adjudicate_payload(), PAYER)
    )

    assert_settlement(
        adjudicated_nsa,
        allowed=190000,
        plan_paid=112001,
        patient_responsibility=77999,
        balance_bill=0,
        written_off=92500,
    )
    assert_settlement(
        adjudicated_state,
        allowed=226000,
        plan_paid=140800,
        patient_responsibility=85200,
        balance_bill=0,
        written_off=56500,
    )
    assert (
        adjudicated_state["patient_responsibility_cents"]
        - adjudicated_nsa["patient_responsibility_cents"]
        == 7201
    )
    assert_money_conservation(adjudicated_nsa)
    assert_money_conservation(adjudicated_state)


def test_peak_adjusted_forecast_volume_exceeds_the_trailing_mean_on_one_history():
    """The same seven-day history yields two different daily volumes.

    PRD 3.4: "Under the `TRAILING_MEAN` variant, `forecast_daily_volume` is that
    window mean unchanged."  And: "Under the `PEAK_ADJUSTED` variant,
    `forecast_daily_volume` is sixty percent of the window's largest element plus
    forty percent of the window mean, that sum rounded half up to two decimals".
    The mean of [22, 19, 26, 31, 18, 24, 29] is 24.14 and 0.60 * 31 + 0.40 * 24.14
    is 28.26, both under a `HISTORY` basis because the array is non-empty.

    Design: Difficulty/dual_variant_calc/physician_coverage_peak_adjusted_diverges_from_trailing_mean_on_identical_history
    """
    context = open_facility(facility_overrides=FACILITY_OVERRIDES)
    facility_id = context["facility_id"]

    trailing_mean = create_volume_forecast(
        facility_id,
        period_start_date="2026-08-01",
        period_days=7,
        historical_daily_volumes=HISTORY,
        method="TRAILING_MEAN",
    )
    peak_adjusted = create_volume_forecast(
        facility_id,
        period_start_date="2026-08-01",
        period_days=7,
        historical_daily_volumes=HISTORY,
        method="PEAK_ADJUSTED",
    )

    assert trailing_mean["forecast_basis"] == "HISTORY"
    assert peak_adjusted["forecast_basis"] == "HISTORY"
    assert_hours_equal(
        trailing_mean["forecast_daily_volume"], "24.14", "trailing mean volume"
    )
    assert_hours_equal(
        peak_adjusted["forecast_daily_volume"], "28.26", "peak adjusted volume"
    )


def test_peak_adjusted_required_hours_exceed_the_trailing_mean_requirement():
    """The volume divergence propagates into every derived hour total.

    PRD 3.4: "`required_physician_hours_total` is
    `required_physician_hours_per_day` multiplied by `period_days`, rounded half up
    to two decimals." and "`required_board_certified_hours_total` is that total
    multiplied by the board-certification minimum share of three quarters, rounded
    half up to two decimals".  PRD 3.4 also pins what the second creation does to
    the first: "every other `ACTIVE` forecast of the same facility becomes
    `SUPERSEDED` in the same operation".  With no coverage blocks on the schedule
    both forecasts see 0.00 scheduled hours, so PRD 3.4's rule that "the facility's
    `coverage_deficit_flag` is set to true when `coverage_deficit_hours` is greater
    than 0 and false otherwise" leaves the flag true.

    Design: Difficulty/dual_variant_calc/physician_coverage_peak_adjusted_diverges_from_trailing_mean_on_identical_history
    """
    context = open_facility(facility_overrides=FACILITY_OVERRIDES)
    facility_id = context["facility_id"]

    trailing_mean = create_volume_forecast(
        facility_id,
        period_start_date="2026-08-01",
        period_days=7,
        historical_daily_volumes=HISTORY,
        method="TRAILING_MEAN",
    )
    peak_adjusted = create_volume_forecast(
        facility_id,
        period_start_date="2026-08-01",
        period_days=7,
        historical_daily_volumes=HISTORY,
        method="PEAK_ADJUSTED",
    )
    refreshed_trailing_mean = validate_success(
        api_client.get_volume_forecast(trailing_mean["id"], OFFICER)
    )

    assert_hours_equal(
        trailing_mean["required_physician_hours_per_day"], "16.25", "mean per day"
    )
    assert_hours_equal(
        peak_adjusted["required_physician_hours_per_day"], "19.00", "peak per day"
    )
    assert_hours_equal(
        trailing_mean["required_physician_hours_total"], "113.75", "mean total"
    )
    assert_hours_equal(
        peak_adjusted["required_physician_hours_total"], "133.00", "peak total"
    )
    assert_hours_equal(
        trailing_mean["required_board_certified_hours_total"], "85.31", "mean board-cert"
    )
    assert_hours_equal(
        peak_adjusted["required_board_certified_hours_total"], "99.75", "peak board-cert"
    )
    assert_hours_equal(
        float(peak_adjusted["required_physician_hours_total"])
        - float(trailing_mean["required_physician_hours_total"]),
        "19.25",
        "requirement delta",
    )

    assert refreshed_trailing_mean["status"] == "SUPERSEDED"
    assert peak_adjusted["status"] == "ACTIVE"
    assert_hours_equal(
        trailing_mean["scheduled_physician_hours"], "0.00", "mean scheduled"
    )
    assert_hours_equal(
        peak_adjusted["scheduled_physician_hours"], "0.00", "peak scheduled"
    )
    assert read_facility(facility_id)["coverage_deficit_flag"] is True
