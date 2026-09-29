"""Computed geometry, quote arithmetic, allowance pooling and blank ranking."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions, factories as f, fixtures
from test_helpers.constants import CLOCK_START_RENDERED, TEST_DEFAULTS
from test_helpers.test_users import (
    BENEFITS_A_HEADERS,
    OPTICIAN_A_HEADERS,
    TECHNICIAN_A_HEADERS,
)

SECOND_PERIOD_CLOCK = "2027-02-01T00:00:00Z"
POOLED_GROSS = 29480
POOLED_BENEFIT = 22000
SIX_MONTH_ISSUE_DATE = "2025-08-31"


def _insured_basic_registry(api):
    """A zero-coinsurance plan, an insured patient and the single-vision design."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api)
    plan = fixtures.create_basic_plan(api)
    patient = fixtures.create_insured_patient(api, plan["id"])
    design = fixtures.create_sv_design(api)
    return {
        "prescriber_id": prescriber["id"],
        "plan_id": plan["id"],
        "patient_id": patient["id"],
        "design_id": design["id"],
    }


def _self_pay_progressive_order(api):
    """A self-pay premium progressive order on a one-blank 80.0 mm lot."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api)
    patient = fixtures.create_self_pay_patient(api)
    design = fixtures.create_progressive_design(api)
    lot = fixtures.create_blank_lot(api, design["id"], received_qty=1)
    scenario = {
        "prescriber_id": prescriber["id"],
        "patient_id": patient["id"],
        "design_id": design["id"],
        "lot_id": lot["id"],
    }
    scenario = fixtures.surfaced_verified_prescription(api, scenario)
    order = validate_success(
        api.create_rx_order(
            f.create_progressive_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
                frame_retail_cents=15000,
                requested_coatings=["AR_PREMIUM"],
                expedite_requested=False,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    scenario["order"] = order
    scenario["order_id"] = order["id"]
    scenario["order_version"] = order["version"]
    return fixtures.surfaced_layout_ready_order(api, scenario)


def test_a_single_vision_layout_consumes_the_horizontal_decentration_alone(api):
    """The vertical figure is recorded at 2.0 mm yet contributes nothing.

    PRD 3.4: "For a `SINGLE_VISION` design the total decentration for an eye is its
    horizontal decentration alone — which is why a single-vision layout is completely
    insensitive to fitting height."

    Design: Corner/calculations/single_vision_layout_ignores_fitting_height_and_returns_fifty_eight_millimetres
    """
    scenario = fixtures.stock_layout_ready_order(api)

    layout = fixtures.read_layout(api, scenario["layout_id"])

    assert layout["decentration_h_od_mm"] == 2.0
    assert layout["decentration_h_os_mm"] == 2.0
    assert layout["decentration_v_mm"] == 2.0
    assert layout["required_blank_diameter_mm"] == 58.0
    assert layout["layout_status"] == "COMPUTED"
    assert layout["effective_fitting_height_mm"] == 16.0
    assert layout["fitting_height_override_mm"] is None
    assertions.assert_frame_layout(layout)

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "LAYOUT_READY"
    assert order["version"] == 2


def test_rolling_consumption_ignores_an_application_outside_the_period(api):
    """Two applied orders of 19995 each, but only one sits inside the window.

    PRD 3.9: "It is the sum of `insurance_benefit_cents` across the patient's orders
    whose `billing_status` is `BENEFIT_APPLIED`, `PATIENT_SETTLED` or `REFUND_DUE` and
    whose `benefit_applied_at` is at or after the window's opening instant and
    **strictly before** its closing instant — inclusive start, exclusive end."

    Design: Corner/calculations/benefit_used_counts_only_orders_whose_application_falls_inside_the_declared_window
    """
    scenario = _insured_basic_registry(api)
    scenario = fixtures.stock_verified_prescription(api, scenario)
    scenario = fixtures.stock_draft_order(api, scenario)
    scenario = fixtures.stock_layout_ready_order(api, scenario)
    scenario = fixtures.stock_queued_job(api, scenario)
    first = validate_success(api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS))
    assert first["insurance_benefit_cents"] == 19995
    assert first["benefit_applied_at"] == CLOCK_START_RENDERED
    assert fixtures.read_patient(api, scenario["patient_id"])["benefit_used_cents"] == (
        19995
    )

    fixtures.set_clock(api, SECOND_PERIOD_CLOCK)
    scenario = fixtures.second_order_on_same_prescription(api, scenario)

    second = validate_success(
        api.apply_benefit(scenario["second_order_id"], BENEFITS_A_HEADERS)
    )

    assert second["insurance_benefit_cents"] == 19995
    assert second["benefit_applied_at"] == "2027-02-01T00:00:00.000Z"
    assert second["patient_portion_cents"] == 6990
    assert second["billing_status"] == "BENEFIT_APPLIED"
    assert (
        fixtures.read_order(api, scenario["order_id"])["billing_status"]
        == "BENEFIT_APPLIED"
    )
    assert fixtures.read_patient(api, scenario["patient_id"])["benefit_used_cents"] == (
        19995
    )


def test_a_thirty_six_hour_promise_is_billed_at_the_twenty_percent_band(api):
    """Halving the 72-hour base lands in the 48-hour band, not the 24-hour one.

    PRD 3.3: "The expedite rate is then read from the first matching band of the
    promised hours: 30 percent of the lens subtotal when the promise is 24 hours or
    fewer, 20 percent when it is 48 hours or fewer, 12 percent when it is 72 hours or
    fewer, and nothing at all beyond that."

    Design: Corner/calculations/standard_tier_expedite_uses_the_twenty_percent_band_at_thirty_six_hours
    """
    scenario = fixtures.stock_verified_prescription(api)

    order = validate_success(
        api.create_rx_order(
            f.create_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
                expedite_requested=True,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )

    assert order["promised_tat_hours"] == 36
    assert order["promised_due_at"] == "2026-08-02T12:00:00.000Z"
    assert order["expedite_fee_cents"] == 3598
    assert order["gross_charge_cents"] == 30583
    assert order["patient_portion_cents"] == 30583
    assert order["estimated_benefit_cents"] == 0
    assert order["tat_commitment_status"] == "ON_TRACK"
    assert order["quote_variant"] == "PROVISIONAL"


def test_a_sphere_gap_of_one_eighth_rounds_onto_the_tolerance_and_passes(api):
    """0.125 becomes 0.13 before the comparison, which ties rather than exceeds.

    PRD 2.6: "Every diopter difference used in an inspection is rounded half up to two
    decimal places **before** it is compared to a tolerance, so that a measurement
    which rounds onto the tolerance passes."

    Design: Corner/calculations/sphere_delta_rounds_half_up_at_the_third_decimal_and_lands_exactly_on_tolerance
    """
    scenario = fixtures.stock_edged_job(api)

    inspection = fixtures.inspect_eye(
        api, scenario["job_id"], "OD", measured_sphere=-2.125
    )

    assert inspection["sphere_delta"] == 0.13
    assert inspection["cylinder_delta"] == 0.0
    assert inspection["axis_delta"] == 0
    assert inspection["prism_delta"] == 0.0
    assert inspection["failed_metrics"] == []
    assert inspection["verdict"] == "PASS"
    assert inspection["tolerance_standard_id"] == scenario["standard_id"]
    assert inspection["cycle_index"] == 0

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "EDGED"
    assert job["rework_cycle_count"] == 0


def test_a_six_month_window_from_the_last_of_august_clamps_to_february(api):
    """There is no 31 February, so the expiry lands on the 28th.

    PRD 3.2: "When the target month has fewer days than the day-of-month of
    `issued_on`, the day is clamped to the last day of the target month: a prescription
    issued on 31 January 2026 with a twelve-month validity expires on 31 January 2027,
    one issued on 29 February 2026 with a twelve-month validity expires on 28 February
    2027, and one issued on 31 August 2025 with a six-month validity expires on 28
    February 2026."

    Design: Corner/calculations/expiry_clamps_to_the_last_day_of_a_shorter_target_month
    """
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(
        api,
        npi=TEST_DEFAULTS["npi_alternate"],
        license_state="OR",
        max_rx_validity_months=6,
    )
    patient = fixtures.create_self_pay_patient(api)

    prescription = validate_success(
        api.create_prescription(
            f.create_prescription_payload(
                patient["id"],
                prescriber["id"],
                prescriber_npi_claimed=TEST_DEFAULTS["npi_alternate"],
                prescriber_license_state_claimed="OR",
                issued_on=SIX_MONTH_ISSUE_DATE,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )

    assert prescription["expires_at"] == "2026-02-28T00:00:00.000Z"
    assert prescription["issued_on"] == SIX_MONTH_ISSUE_DATE
    assert prescription["verification_status"] == "UNVERIFIED"
    assert prescription["resubmit_count"] == 0
    assert prescription["requires_multifocal"] is False
    assertions.assert_prescription(prescription)


def test_the_smallest_sufficient_lot_wins_and_the_oldest_receipt_breaks_the_tie(api):
    """Three eligible lots: 80.0 loses on diameter, then the older 77.0 wins.

    PRD 3.5: "Candidates are ranked by `diameter_mm` ascending, so the smallest
    sufficient blank is taken first and large blanks are preserved for the frames that
    need them; ties on diameter are broken by `received_on` ascending, so the oldest
    stock rotates out first; and remaining ties are broken by `created_at` ascending."

    Design: Corner/calculations/blank_selection_takes_the_smallest_sufficient_diameter_then_the_oldest_receipt
    """
    scenario = fixtures.surfaced_registry(api)
    newer_77 = fixtures.create_blank_lot(
        api,
        scenario["design_id"],
        blank_sku="BLK-167-77N",
        diameter_mm=77.0,
        received_qty=2,
        received_on="2026-06-20",
    )
    older_77 = fixtures.create_blank_lot(
        api,
        scenario["design_id"],
        blank_sku="BLK-167-77O",
        diameter_mm=77.0,
        received_qty=2,
        received_on="2026-05-01",
    )
    scenario = fixtures.surfaced_verified_prescription(api, scenario)
    scenario = fixtures.surfaced_draft_order(api, scenario)
    scenario = fixtures.surfaced_layout_ready_order(api, scenario)
    assert (
        fixtures.read_layout(api, scenario["layout_id"])["required_blank_diameter_mm"]
        == 77.0
    )

    job = validate_success(
        api.create_lab_job(
            f.create_lab_job_payload(scenario["order_id"]), TECHNICIAN_A_HEADERS
        ),
        expected_status=201,
    )

    assert job["route"] == "SURFACE_AND_EDGE"
    assert job["status"] == "QUEUED"
    assert job["frame_layout_id"] == scenario["layout_id"]
    assert job["blank_lot_id"] == older_77["id"]

    assertions.assert_lot_quantities(
        fixtures.read_lot(api, older_77["id"]),
        on_hand=1,
        allocated=1,
        consumed=0,
        scrapped=0,
        status="AVAILABLE",
    )
    assertions.assert_lot_quantities(
        fixtures.read_lot(api, newer_77["id"]),
        on_hand=2,
        allocated=0,
        consumed=0,
        scrapped=0,
        status="AVAILABLE",
    )
    assertions.assert_lot_quantities(
        fixtures.read_lot(api, scenario["lot_id"]),
        on_hand=2,
        allocated=0,
        consumed=0,
        scrapped=0,
        status="AVAILABLE",
    )


def test_the_coating_pool_is_spent_dearest_first(api):
    """AR_STANDARD takes its whole 5995 and HARDCOAT gets only the 2005 left.

    PRD 3.9: "The coatings share a **single pool** initialised to
    `coating_allowance_cents`: taking each coating in component order, its allowance is
    the lesser of the pool's current balance and that coating's charge, and the pool is
    then reduced by the allowance just granted."

    Design: Corner/calculations/coating_pool_is_spent_dearest_first_and_leaves_the_cheaper_coating_partly_uncovered
    """
    scenario = _insured_basic_registry(api)
    scenario = fixtures.stock_verified_prescription(api, scenario)

    order = validate_success(
        api.create_rx_order(
            f.create_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
                requested_coatings=["HARDCOAT", "AR_STANDARD"],
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )

    assert order["gross_charge_cents"] == POOLED_GROSS
    assert order["estimated_benefit_cents"] == POOLED_BENEFIT
    assert order["patient_portion_cents"] == POOLED_GROSS - POOLED_BENEFIT
    assert order["insurance_benefit_cents"] == 0
    assert order["quote_variant"] == "PROVISIONAL"
    assert fixtures.read_patient(api, scenario["patient_id"])["benefit_used_cents"] == 0


def test_committing_the_order_repromises_the_turnaround_and_nothing_else(api):
    """The surfacing route lengthens the promise while the money block stands still.

    PRD 3.5: "Finally the turnaround is re-promised with the route now actually known,
    rewriting `promised_tat_hours` and `promised_due_at` — and *only* those two
    fields."

    Design: Corner/calculations/job_creation_repromises_the_turnaround_without_touching_the_money_block
    """
    scenario = _self_pay_progressive_order(api)
    before = fixtures.read_order(api, scenario["order_id"])
    assert before["promised_tat_hours"] == 48
    assert before["promised_due_at"] == "2026-08-03T00:00:00.000Z"
    assert before["gross_charge_cents"] == 57990

    job = validate_success(
        api.create_lab_job(
            f.create_lab_job_payload(scenario["order_id"]), TECHNICIAN_A_HEADERS
        ),
        expected_status=201,
    )
    assert job["route"] == "SURFACE_AND_EDGE"

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["promised_tat_hours"] == 72
    assert order["promised_due_at"] == "2026-08-04T00:00:00.000Z"
    assert order["gross_charge_cents"] == 57990
    assert order["expedite_fee_cents"] == 0
    assert order["patient_portion_cents"] == 57990
    assert order["quote_variant"] == "PROVISIONAL"
    assert order["billing_status"] == "PROVISIONAL_QUOTED"
    assert order["fulfillment_status"] == "IN_LAB"
    assert order["tat_commitment_status"] == "ON_TRACK"
    assert fixtures.read_lot(api, scenario["lot_id"])["status"] == "DEPLETED"
