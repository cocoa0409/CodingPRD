"""Initial states, legal edges, refused edges and the cascades they trigger."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START_RENDERED, TEST_DEFAULTS
from test_helpers.test_users import (
    BENEFITS_A_HEADERS,
    INSPECTOR_A_HEADERS,
    MANAGER_A_HEADERS,
    OPTICIAN_A,
    OPTICIAN_A_HEADERS,
    TECHNICIAN_A,
    TECHNICIAN_A_HEADERS,
)

SELF_PAY_GROSS = 26985
FIRST_REJECTION_NOTE = "First rejection: NPI unreadable"
CORRECTED_ISSUED_ON = "2026-05-01"
SECOND_WINDOW = ("2026-08-01T12:00:00Z", "2026-08-01T13:00:00Z")


def _rejected_prescription(api):
    """A self-pay prescription taken to REJECTED by its first rejection."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api)
    patient = fixtures.create_self_pay_patient(api)
    prescription = validate_success(
        api.create_prescription(
            f.create_prescription_payload(patient["id"], prescriber["id"]),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    rejected = validate_success(
        api.reject_prescription(
            prescription["id"],
            {"verification_note": FIRST_REJECTION_NOTE},
            OPTICIAN_A_HEADERS,
        )
    )
    assert rejected["verification_status"] == "REJECTED"
    return {
        "prescriber_id": prescriber["id"],
        "patient_id": patient["id"],
        "prescription_id": prescription["id"],
    }


def _insured_stock_queued_job(api):
    """A basic-plan insured patient's stock order, committed so the route is known."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api)
    plan = fixtures.create_basic_plan(api)
    patient = fixtures.create_insured_patient(api, plan["id"])
    design = fixtures.create_sv_design(api)
    standard = fixtures.create_sv_standard(api)
    bay = fixtures.create_bay(api, bay_code="BAY-S", concurrent_capacity=1)
    scenario = {
        "prescriber_id": prescriber["id"],
        "plan_id": plan["id"],
        "patient_id": patient["id"],
        "design_id": design["id"],
        "standard_id": standard["id"],
        "bay_id": bay["id"],
    }
    scenario = fixtures.stock_verified_prescription(api, scenario)
    scenario = fixtures.stock_draft_order(api, scenario)
    scenario = fixtures.stock_layout_ready_order(api, scenario)
    return fixtures.stock_queued_job(api, scenario)


def test_a_new_order_sits_at_the_initial_state_of_both_dimensions(api):
    """One create stamps every server-owned default on the fresh order.

    PRD 3.3: "An accepted order is created with `fulfillment_status` `DRAFT` and
    `billing_status` `PROVISIONAL_QUOTED`, with `quote_variant` `PROVISIONAL`,
    `tat_commitment_status` `ON_TRACK`, `remake_count` 0, `insurance_benefit_cents` 0,
    `lab_writeoff_cents` 0, `patient_paid_cents` 0, `expedite_fee_cents` 0 and a null
    `benefit_applied_at`."

    Design: Corner/state_machines/new_rx_order_starts_in_draft_and_provisional_quoted
    """
    scenario = fixtures.stock_verified_prescription(api)

    order = validate_success(
        api.create_rx_order(
            f.create_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )

    assert order["fulfillment_status"] == "DRAFT"
    assert order["billing_status"] == "PROVISIONAL_QUOTED"
    assert order["quote_variant"] == "PROVISIONAL"
    assert order["tat_commitment_status"] == "ON_TRACK"
    assert order["remake_count"] == 0
    assert order["insurance_benefit_cents"] == 0
    assert order["lab_writeoff_cents"] == 0
    assert order["patient_paid_cents"] == 0
    assert order["expedite_fee_cents"] == 0
    assert order["benefit_applied_at"] is None
    assert order["version"] == 1
    assert order["created_by_optician_id"] == OPTICIAN_A
    assertions.assert_rx_order(order)


def test_the_self_pay_projection_leaves_the_whole_gross_with_the_patient(api):
    """Frame 8995 plus lens 11995 plus AR_STANDARD 5995, none of it covered.

    PRD 3.3: "A self-pay patient runs the identical arithmetic with every allowance
    and the coinsurance share treated as zero, so the projected benefit is 0 and the
    patient portion equals the gross charge."

    Design: Corner/state_machines/new_rx_order_starts_in_draft_and_provisional_quoted
    """
    scenario = fixtures.stock_draft_order(api)

    order = fixtures.read_order(api, scenario["order_id"])

    assert order["gross_charge_cents"] == SELF_PAY_GROSS
    assert order["estimated_benefit_cents"] == 0
    assert order["patient_portion_cents"] == SELF_PAY_GROSS
    assert order["patient_balance_due_cents"] == SELF_PAY_GROSS
    assertions.assert_money_identity(order)
    assertions.assert_balance_definition(order)


def test_the_standard_tier_promise_is_seventy_two_hours_from_creation(api):
    """No expedite and no surfacing yet, so the promise is the bare tier base.

    PRD 3.3: "`promised_due_at` is the order's `created_at` advanced by
    `promised_tat_hours` hours, plus a further 48 hours for every backorder event the
    order has suffered."

    Design: Corner/state_machines/new_rx_order_starts_in_draft_and_provisional_quoted
    """
    scenario = fixtures.stock_draft_order(api)

    order = fixtures.read_order(api, scenario["order_id"])

    assert order["created_at"] == CLOCK_START_RENDERED
    assert order["promised_tat_hours"] == 72
    assert order["promised_due_at"] == "2026-08-04T00:00:00.000Z"
    assert order["product_tier"] == "STANDARD"


def test_resubmission_walks_the_only_backwards_edge_and_recomputes_expiry(api):
    """REJECTED returns to UNVERIFIED and the corrected issue date moves expiry.

    PRD 3.2: "Resubmission runs the other way, `REJECTED → UNVERIFIED`: it increments
    `resubmit_count` by exactly 1, clears `verification_note`, and applies any
    correction the optician supplies."

    Design: Corner/state_machines/resubmit_returns_a_rejected_prescription_to_unverified_and_recomputes_expiry
    """
    scenario = _rejected_prescription(api)

    prescription = validate_success(
        api.resubmit_prescription(
            scenario["prescription_id"],
            {"corrected_issued_on": CORRECTED_ISSUED_ON},
            OPTICIAN_A_HEADERS,
        )
    )

    assert prescription["verification_status"] == "UNVERIFIED"
    assert prescription["resubmit_count"] == 1
    assert prescription["verification_note"] is None
    assert prescription["verified_at"] is None
    assert prescription["issued_on"] == CORRECTED_ISSUED_ON
    assert prescription["expires_at"] == "2027-05-01T00:00:00.000Z"
    prescriber = fixtures.read_prescriber(api, scenario["prescriber_id"])
    assert prescriber["verified_rx_count"] == 0


def test_releasing_a_job_that_only_reached_edged_is_refused(api):
    """The edging is done but nobody has measured the lenses yet.

    PRD 3.7: "A `LabTechnician` releases a job to the store, and the job's `status`
    must be `PASSED`; anything else yields `ERR_LAB_JOB_STATE_INVALID`."

    Design: Corner/state_machines/release_of_a_job_that_only_reached_edged_is_refused
    """
    scenario = fixtures.stock_edged_job(api)
    assert fixtures.read_operation(api, scenario["operation_id"])["status"] == "COMPLETED"

    validate_error(
        api.release_lab_job(scenario["job_id"], TECHNICIAN_A_HEADERS),
        ApiErrorId.LAB_JOB_STATE_INVALID.value,
        409,
    )

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "EDGED"
    assert job["released_at"] is None
    assert fixtures.read_order(api, scenario["order_id"])["fulfillment_status"] == "IN_LAB"


def test_release_stamps_the_job_and_completes_the_order(api):
    """Both eyes passed, so the job leaves the shop and the order is complete.

    PRD 3.7: "Release moves the job `PASSED → RELEASED` and stamps `released_at` with
    the logical clock."

    Design: Corner/state_machines/release_stamps_released_at_and_completes_the_order_on_time
    """
    scenario = fixtures.stock_passed_job(api)
    assert scenario["inspection_od"]["verdict"] == "PASS"
    assert scenario["inspection_os"]["verdict"] == "PASS"
    assert fixtures.read_job(api, scenario["job_id"])["status"] == "PASSED"

    job = validate_success(
        api.release_lab_job(scenario["job_id"], TECHNICIAN_A_HEADERS)
    )

    assert job["status"] == "RELEASED"
    assert job["released_at"] == CLOCK_START_RENDERED
    assert fixtures.read_order(api, scenario["order_id"])["fulfillment_status"] == (
        "LAB_COMPLETE"
    )


def test_release_leaves_the_promise_on_track_and_the_billing_untouched(api):
    """The clock never moved past the promise, and release is a fulfillment act.

    PRD 3.7: "And the promise is judged: if the logical clock is strictly past the
    order's `promised_due_at`, `tat_commitment_status` becomes `BREACHED`; otherwise it
    is left exactly as it was, which means a job that spent time in backorder is
    released still reading `AT_RISK` rather than being quietly restored to `ON_TRACK`."

    Design: Corner/state_machines/release_stamps_released_at_and_completes_the_order_on_time
    """
    scenario = fixtures.stock_passed_job(api)

    validate_success(api.release_lab_job(scenario["job_id"], TECHNICIAN_A_HEADERS))

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["promised_due_at"] == "2026-08-04T00:00:00.000Z"
    assert order["tat_commitment_status"] == "ON_TRACK"
    assert order["billing_status"] == "PROVISIONAL_QUOTED"
    assert order["quote_variant"] == "PROVISIONAL"

    _, meta = validate_paginated(api.list_lens_blank_lots(MANAGER_A_HEADERS))
    assert meta["total_count"] == 0


def test_a_second_verification_of_a_verified_prescription_is_refused(api):
    """VERIFIED has no outgoing verify edge, so the count is not doubled.

    PRD 3.2: "First, the state gate: if the prescription's `verification_status`
    admits no transition for the requested action, the request is rejected with
    `ERR_RX_STATE_INVALID`."

    Design: Corner/state_machines/verify_on_an_already_verified_prescription_has_no_transition
    """
    scenario = fixtures.stock_verified_prescription(api)
    first = fixtures.read_prescription(api, scenario["prescription_id"])
    assert first["verification_status"] == "VERIFIED"
    assert first["verified_at"] == CLOCK_START_RENDERED
    assert fixtures.read_prescriber(api, scenario["prescriber_id"])["verified_rx_count"] == 1

    validate_error(
        api.verify_prescription(
            scenario["prescription_id"],
            {"verification_note": "second look"},
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.RX_STATE_INVALID.value,
        409,
    )

    prescription = fixtures.read_prescription(api, scenario["prescription_id"])
    assert prescription["verification_status"] == "VERIFIED"
    assert prescription["verified_at"] == first["verified_at"]
    assert prescription["verification_note"] == TEST_DEFAULTS["verification_note"]
    assert fixtures.read_prescriber(api, scenario["prescriber_id"])["verified_rx_count"] == 1


def test_starting_a_cancelled_occupation_is_refused(api):
    """A dropped window is terminal, so it can never be picked back up.

    PRD 3.6: "Two gates apply: if the occupation's own `status` admits no start —
    because it is already `RUNNING`, or `COMPLETED`, `BROKEN` or `CANCELLED` — the
    response is `ERR_OPERATION_STATE_INVALID`; and if the job's `status` does not admit
    an occupation of this `operation_type`, the response is
    `ERR_LAB_JOB_STATE_INVALID`."

    Design: Corner/state_machines/start_of_a_cancelled_operation_is_refused_from_a_terminal_state
    """
    scenario = fixtures.stock_queued_job(api)
    operation = fixtures.book_edging(api, scenario)
    cancelled = validate_success(
        api.cancel_lab_operation(
            operation["id"], {"cancel_reason": "SHIFT_CHANGE"}, TECHNICIAN_A_HEADERS
        )
    )
    assert cancelled["status"] == "CANCELLED"

    validate_error(
        api.start_lab_operation(operation["id"], TECHNICIAN_A_HEADERS),
        ApiErrorId.OPERATION_STATE_INVALID.value,
        409,
    )

    reread = fixtures.read_operation(api, operation["id"])
    assert reread["status"] == "CANCELLED"
    assert reread["performed_by_user_id"] is None
    assert fixtures.read_job(api, scenario["job_id"])["status"] == "QUEUED"


def test_a_second_rejection_is_not_silently_absorbed(api):
    """Replaying the same reject fails and the first note survives.

    PRD 3.2: "Rejection by an optician requires a `verification_note` explaining the
    decision, and reaches `REJECTED` from either of two states."

    Design: Corner/state_machines/second_reject_on_a_rejected_prescription_is_refused
    """
    scenario = _rejected_prescription(api)

    validate_error(
        api.reject_prescription(
            scenario["prescription_id"],
            {"verification_note": "Second rejection attempt"},
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.RX_STATE_INVALID.value,
        409,
    )

    prescription = fixtures.read_prescription(api, scenario["prescription_id"])
    assert prescription["verification_status"] == "REJECTED"
    assert prescription["verification_note"] == FIRST_REJECTION_NOTE
    assert prescription["resubmit_count"] == 0


def test_the_third_failing_cycle_scraps_the_job_instead_of_looping_again(api):
    """Two cycles of rework are budgeted; the third failure ends the job.

    PRD 3.7: "A `FAIL` recorded when `rework_cycle_count` has already reached 2
    exhausts the budget: the inspection is still written with its `verdict` of `FAIL`,
    and the job moves `EDGED → SCRAPPED` with `scrap_reason` `REWORK_LIMIT`."

    Design: Corner/state_machines/rework_loop_scraps_the_job_on_the_third_failing_cycle
    """
    scenario = fixtures.stock_edged_job(api)
    scenario = fixtures.failing_inspection_rework_cycle(api, scenario)
    assert scenario["failing_inspection"]["verdict"] == "FAIL"
    assert scenario["failing_inspection"]["cycle_index"] == 0
    assert fixtures.read_job(api, scenario["job_id"])["rework_cycle_count"] == 1

    scenario = fixtures.failing_inspection_rework_cycle(
        api, scenario, window_start=SECOND_WINDOW[0], window_end=SECOND_WINDOW[1]
    )
    assert scenario["failing_inspection"]["cycle_index"] == 1
    assert fixtures.read_job(api, scenario["job_id"])["rework_cycle_count"] == 2

    third = fixtures.inspect_eye(api, scenario["job_id"], "OD", measured_sphere=-2.3)

    assert third["sphere_delta"] == 0.30
    assert third["failed_metrics"] == ["SPHERE"]
    assert third["verdict"] == "FAIL"
    assert third["cycle_index"] == 2
    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "SCRAPPED"
    assert job["scrap_reason"] == "REWORK_LIMIT"
    assert job["rework_cycle_count"] == 2
    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "IN_LAB"
    assert order["billing_status"] == "PROVISIONAL_QUOTED"
    assert order["remake_count"] == 0
    inspections, meta = validate_paginated(
        api.list_quality_inspections(
            INSPECTOR_A_HEADERS, {"lab_job_id": scenario["job_id"]}
        )
    )
    assert meta["total_count"] == 3
    assert sorted(row["cycle_index"] for row in inspections) == [0, 1, 2]


def test_suspending_a_prescriber_rejects_the_rx_and_withdraws_its_draft_order(api):
    """One PATCH on the parent walks three hops down to the order's money block.

    PRD 3.2: "The second hop takes every prescription of that prescriber whose
    `verification_status` is `VERIFIED` and drives it `VERIFIED → REJECTED`, setting
    `verification_note` to the literal string `PRESCRIBER_STANDING_LOST` and clearing
    `verified_at`."

    Design: Corner/state_machines/suspending_a_prescriber_rejects_the_rx_and_cancels_its_draft_order
    """
    scenario = fixtures.stock_draft_order(api)
    assert fixtures.read_prescriber(api, scenario["prescriber_id"])["verified_rx_count"] == 1
    assert (
        fixtures.read_order(api, scenario["order_id"])["gross_charge_cents"]
        == SELF_PAY_GROSS
    )

    prescriber = validate_success(
        api.patch_prescriber_status(
            scenario["prescriber_id"], {"status": "SUSPENDED"}, MANAGER_A_HEADERS
        )
    )

    assert prescriber["status"] == "SUSPENDED"
    assert prescriber["verified_rx_count"] == 0

    prescription = fixtures.read_prescription(api, scenario["prescription_id"])
    assert prescription["verification_status"] == "REJECTED"
    assert prescription["verification_note"] == "PRESCRIBER_STANDING_LOST"
    assert prescription["verified_at"] is None

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "CANCELLED"
    assert order["billing_status"] == "CANCELLED_NO_CHARGE"
    assert order["gross_charge_cents"] == 0
    assert order["estimated_benefit_cents"] == 0
    assert order["patient_portion_cents"] == 0
    assert order["patient_balance_due_cents"] == 0
    assert order["expedite_fee_cents"] == 0
    assert fixtures.read_patient(api, scenario["patient_id"])["benefit_used_cents"] == 0


def test_the_job_passes_only_when_the_second_eye_completes_the_pair(api):
    """One PASS is a record, not a join; the pair is what moves the job.

    PRD 3.7: "A `PASS` that is the first of its cycle leaves the job at `EDGED →
    EDGED`: the record exists but the pair is incomplete."

    Design: Corner/state_machines/job_reaches_passed_only_when_both_eyes_pass_the_current_cycle
    """
    scenario = fixtures.stock_edged_job(api)
    od = fixtures.inspect_eye(api, scenario["job_id"], "OD")
    assert od["verdict"] == "PASS"
    assert od["cycle_index"] == 0
    assert fixtures.read_job(api, scenario["job_id"])["status"] == "EDGED"

    os_ = fixtures.inspect_eye(api, scenario["job_id"], "OS")

    assert os_["verdict"] == "PASS"
    assert od["eye"] == "OD"
    assert os_["eye"] == "OS"
    assert os_["cycle_index"] == 0
    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "PASSED"
    assert job["rework_cycle_count"] == 0
    assert job["released_at"] is None
    assert fixtures.read_order(api, scenario["order_id"])["fulfillment_status"] == "IN_LAB"


def test_applying_the_benefit_raises_the_patient_rolling_consumption(api):
    """The derived ancestor field is 0 before the application and 19995 after.

    PRD 3.9: "It is the sum of `insurance_benefit_cents` across the patient's orders
    whose `billing_status` is `BENEFIT_APPLIED`, `PATIENT_SETTLED` or `REFUND_DUE` and
    whose `benefit_applied_at` is at or after the window's opening instant and
    **strictly before** its closing instant — inclusive start, exclusive end."

    Design: Corner/state_machines/benefit_application_raises_the_patient_rolling_benefit_used
    """
    scenario = _insured_stock_queued_job(api)
    assert (
        fixtures.read_order(api, scenario["order_id"])["estimated_benefit_cents"] == 19995
    )
    assert fixtures.read_patient(api, scenario["patient_id"])["benefit_used_cents"] == 0

    order = validate_success(
        api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS)
    )

    assert order["billing_status"] == "BENEFIT_APPLIED"
    assert order["quote_variant"] == "FINAL"
    assert order["gross_charge_cents"] == SELF_PAY_GROSS
    assert order["insurance_benefit_cents"] == 19995
    assert order["patient_portion_cents"] == 6990
    assert order["benefit_applied_at"] == CLOCK_START_RENDERED
    assertions.assert_money_identity(order)
    assert fixtures.read_patient(api, scenario["patient_id"])["benefit_used_cents"] == 19995

    entries, meta = validate_paginated(
        api.list_order_settlement_entries(scenario["order_id"], BENEFITS_A_HEADERS)
    )
    assert meta["total_count"] == 2
    assertions.assert_ledger_types_in_order(
        entries, ["ORDER_CHARGE", "INSURANCE_BENEFIT"]
    )
    assert [entry["amount_cents"] for entry in entries] == [SELF_PAY_GROSS, -19995]


def test_withdrawal_spares_the_completed_window_and_drops_the_scheduled_one(api):
    """The unwind is state-filtered: finished work is history, not a booking.

    PRD 3.9: "Every `SCHEDULED` occupation of the order's newest job moves `SCHEDULED
    → CANCELLED` with `cancel_reason` set to the literal string `ORDER_CANCELLED`,
    freeing the machine and bay windows they held."

    Design: Corner/state_machines/order_cancel_spares_the_completed_operation_and_drops_only_the_scheduled_one
    """
    scenario = fixtures.stock_edged_job(api)
    completed_id = scenario["operation_id"]
    second = fixtures.book_edging(api, scenario, *SECOND_WINDOW)
    assert second["status"] == "SCHEDULED"

    validate_success(api.cancel_rx_order(scenario["order_id"], OPTICIAN_A_HEADERS))

    completed = fixtures.read_operation(api, completed_id)
    assert completed["status"] == "COMPLETED"
    assert completed["performed_by_user_id"] == TECHNICIAN_A
    assert fixtures.read_operation(api, second["id"])["status"] == "CANCELLED"

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "SCRAPPED"
    assert job["scrap_reason"] == "ORDER_CANCELLED"

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "CANCELLED"
    assert order["billing_status"] == "CANCELLED_NO_CHARGE"
    assert order["gross_charge_cents"] == 0
    assert order["patient_portion_cents"] == 0
    assert order["patient_balance_due_cents"] == 0
