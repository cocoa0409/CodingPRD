"""Refusals the workflow must produce, and what each one leaves untouched."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START_RENDERED, TEST_DEFAULTS
from test_helpers.test_users import (
    INSPECTOR_A_HEADERS,
    MANAGER_A_HEADERS,
    OPTICIAN_A_HEADERS,
    TECHNICIAN_A_HEADERS,
)

REWOUND_CLOCK = "2026-07-31T23:59:59Z"
FUTURE_STANDARD_DATE = "2026-09-01"
FUTURE_STANDARD_CLOCK = "2026-09-01T00:00:00Z"
NINE_HOUR_WINDOW = ("2026-08-01T08:00:00Z", "2026-08-01T17:00:00Z")
EIGHT_HOUR_WINDOW = ("2026-08-01T08:00:00Z", "2026-08-01T16:00:00Z")
BOOKED_WINDOW = ("2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z")
BREAKAGE_REASON = "Lens cracked in the chuck"
SELF_PAY_GROSS = 26985


def _queued_stock_job_with_a_generator(api):
    """A QUEUED stock-route job alongside a commissioned generator."""
    scenario = fixtures.stock_queued_job(api)
    machine = fixtures.create_generator(api)
    scenario["machine_id"] = machine["id"]
    scenario["job_version"] = fixtures.read_job(api, scenario["job_id"])["version"]
    return scenario


def _running_edging_operation(api):
    """A stock job whose edging window has been started but not completed."""
    scenario = fixtures.stock_queued_job(api)
    operation = fixtures.book_edging(api, scenario, *BOOKED_WINDOW)
    started = validate_success(
        api.start_lab_operation(operation["id"], TECHNICIAN_A_HEADERS)
    )
    assert started["status"] == "RUNNING"
    scenario["operation_id"] = operation["id"]
    scenario["job_version"] = fixtures.read_job(api, scenario["job_id"])["version"]
    return scenario


def _edged_job_with_only_a_future_standard(api):
    """The only single-vision standard becomes effective a month after the clock."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api)
    patient = fixtures.create_self_pay_patient(api)
    design = fixtures.create_sv_design(api)
    standard = fixtures.create_sv_standard(api, effective_from=FUTURE_STANDARD_DATE)
    bay = fixtures.create_bay(api, bay_code="BAY-S", concurrent_capacity=1)
    scenario = {
        "prescriber_id": prescriber["id"],
        "patient_id": patient["id"],
        "design_id": design["id"],
        "standard_id": standard["id"],
        "bay_id": bay["id"],
    }
    scenario = fixtures.stock_verified_prescription(api, scenario)
    scenario = fixtures.stock_draft_order(api, scenario)
    scenario = fixtures.stock_layout_ready_order(api, scenario)
    scenario = fixtures.stock_queued_job(api, scenario)
    return fixtures.stock_edged_job(api, scenario)


def _first_job_carrying_an_open_case_and_a_replacement_job(api):
    """Case 1 scrapped job 1; job 2 has returned the order to the laboratory."""
    scenario = fixtures.stock_remake_pending_order(api, defect_codes=["WRONG_FRAME"])
    assert scenario["case"]["status"] == "SUBMITTED"
    assert fixtures.read_job(api, scenario["first_job_id"])["status"] == "SCRAPPED"
    scenario = fixtures.stock_replacement_job(api, scenario)
    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "IN_LAB"
    assert order["remake_count"] == 1
    return scenario


def test_rewinding_the_logical_clock_is_refused(api):
    """One second earlier than the current instant is still backwards.

    PRD 2.4: "The clock is monotonically non-decreasing: a request whose instant is
    strictly earlier than the current logical clock is rejected with
    `ERR_CLOCK_NOT_MONOTONIC` (HTTP 409)."

    Design: Corner/errors/clock_rewind_is_refused
    """
    fixtures.set_clock(api)

    validate_error(
        api.set_clock({"current_utc": REWOUND_CLOCK}, MANAGER_A_HEADERS),
        ApiErrorId.CLOCK_NOT_MONOTONIC.value,
        409,
    )

    prescriber = fixtures.create_prescriber(api)
    assert prescriber["created_at"] == CLOCK_START_RENDERED


def test_a_second_prescriber_on_the_same_npi_is_refused(api):
    """A different name and state do not make the identifier free.

    PRD 3.1: "An `npi` may belong to only one prescriber; a second registration
    attempt with an NPI already held is rejected with `ERR_DUPLICATE_NPI`, a check that
    runs ahead of every other prescriber-specific rule."

    Design: Corner/errors/duplicate_prescriber_npi_is_refused
    """
    fixtures.set_clock(api)
    first = fixtures.create_prescriber(api)

    validate_error(
        api.create_prescriber(
            f.create_prescriber_payload(
                npi=TEST_DEFAULTS["npi_primary"],
                full_name="Dr Paul Osei",
                license_state="NV",
                max_rx_validity_months=24,
            ),
            MANAGER_A_HEADERS,
        ),
        ApiErrorId.DUPLICATE_NPI.value,
        409,
    )

    rows, meta = validate_paginated(api.list_prescribers(MANAGER_A_HEADERS))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["full_name"] == TEST_DEFAULTS["prescriber_name"]


def test_an_edging_window_carrying_a_machine_is_refused(api):
    """Edging happens in a bay, so a generator is the wrong kind of resource.

    PRD 3.6: "Then the resource-type match: a surfacing booking without a
    `machine_id`, a surfacing booking whose machine has a `machine_type` other than
    `GENERATOR`, a surfacing booking that also carries a `bay_id`, an edging booking
    without a `bay_id`, or an edging booking that also carries a `machine_id` is
    rejected with `ERR_RESOURCE_TYPE_MISMATCH` — exactly one resource, of the right
    kind, must be supplied."

    Design: Corner/errors/edging_booked_against_a_machine_is_refused
    """
    scenario = _queued_stock_job_with_a_generator(api)

    validate_error(
        api.create_lab_operation(
            f.create_lab_operation_payload(
                scenario["job_id"],
                scenario["job_version"],
                "EDGING",
                *BOOKED_WINDOW,
                machine_id=scenario["machine_id"],
            ),
            TECHNICIAN_A_HEADERS,
        ),
        ApiErrorId.RESOURCE_TYPE_MISMATCH.value,
        400,
    )

    _, meta = validate_paginated(
        api.list_lab_operations(
            TECHNICIAN_A_HEADERS, {"lab_job_id": scenario["job_id"]}
        )
    )
    assert meta["total_count"] == 0
    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "QUEUED"
    assert job["version"] == scenario["job_version"]


def test_a_nine_hour_occupation_is_refused_on_duration_alone(api):
    """The window is well ordered and the bay is empty; only its length is wrong.

    PRD 3.6: "Then the window shape: a `window_end` at or before `window_start`, or a
    window longer than eight hours, is rejected with `ERR_OPERATION_WINDOW_INVALID`."

    Design: Corner/errors/an_operation_window_longer_than_eight_hours_is_refused
    """
    scenario = fixtures.stock_queued_job(api)

    validate_error(
        api.create_lab_operation(
            f.create_edging_operation_payload(
                scenario["job_id"],
                scenario["job_version"],
                scenario["bay_id"],
                *NINE_HOUR_WINDOW,
            ),
            TECHNICIAN_A_HEADERS,
        ),
        ApiErrorId.OPERATION_WINDOW_INVALID.value,
        400,
    )

    _, meta = validate_paginated(
        api.list_lab_operations(TECHNICIAN_A_HEADERS, {"bay_id": scenario["bay_id"]})
    )
    assert meta["total_count"] == 0


def test_the_same_window_shortened_to_exactly_eight_hours_is_booked(api):
    """Eight hours is not longer than eight hours, so the identical booking stands.

    PRD 3.6: "A booked occupation is created with `status` `SCHEDULED`, a null
    `performed_by_user_id`, a null `breakage_reason` and a null `cancel_reason`."

    Design: Corner/errors/an_operation_window_longer_than_eight_hours_is_refused
    """
    scenario = fixtures.stock_queued_job(api)
    validate_error(
        api.create_lab_operation(
            f.create_edging_operation_payload(
                scenario["job_id"],
                scenario["job_version"],
                scenario["bay_id"],
                *NINE_HOUR_WINDOW,
            ),
            TECHNICIAN_A_HEADERS,
        ),
        ApiErrorId.OPERATION_WINDOW_INVALID.value,
        400,
    )

    operation = validate_success(
        api.create_lab_operation(
            f.create_edging_operation_payload(
                scenario["job_id"],
                scenario["job_version"],
                scenario["bay_id"],
                *EIGHT_HOUR_WINDOW,
            ),
            TECHNICIAN_A_HEADERS,
        ),
        expected_status=201,
    )

    assert operation["status"] == "SCHEDULED"
    assert operation["performed_by_user_id"] is None
    assert operation["breakage_reason"] is None
    assert operation["cancel_reason"] is None
    assert operation["bay_id"] == scenario["bay_id"]
    assert operation["machine_id"] is None


def test_breakage_reported_against_an_edging_occupation_is_refused(api):
    """A cracked lens in a bay is not the surfacing event this endpoint records.

    PRD 3.6: "Breakage is a surfacing-only event: reporting it against an edging
    occupation is rejected with `ERR_BREAKAGE_NOT_APPLICABLE`, and reporting it against
    an occupation that is not `RUNNING` is rejected with
    `ERR_OPERATION_STATE_INVALID`."

    Design: Corner/errors/breakage_reported_on_an_edging_operation_is_refused
    """
    scenario = _running_edging_operation(api)

    validate_error(
        api.report_breakage(
            scenario["operation_id"],
            {"breakage_reason": BREAKAGE_REASON},
            TECHNICIAN_A_HEADERS,
        ),
        ApiErrorId.BREAKAGE_NOT_APPLICABLE.value,
        422,
    )

    operation = fixtures.read_operation(api, scenario["operation_id"])
    assert operation["status"] == "RUNNING"
    assert operation["breakage_reason"] is None
    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "EDGING"
    assert job["breakage_count"] == 0


def test_the_same_eye_inspected_twice_in_one_cycle_is_refused(api):
    """The first OD reading owns cycle 0, whatever the second one measures.

    PRD 3.7: "That eye must not already have been judged in the current cycle: if an
    inspection already exists for the same `lab_job_id` and the same `eye` whose
    `cycle_index` equals the job's current `rework_cycle_count`, the response is
    `ERR_EYE_ALREADY_INSPECTED_THIS_CYCLE`."

    Design: Corner/errors/the_same_eye_inspected_twice_in_one_cycle_is_refused
    """
    scenario = fixtures.stock_edged_job(api)
    first = fixtures.inspect_eye(api, scenario["job_id"], "OD")
    assert first["cycle_index"] == 0

    validate_error(
        api.create_quality_inspection(
            f.create_quality_inspection_payload(
                scenario["job_id"], "OD", measured_sphere=-2.05
            ),
            INSPECTOR_A_HEADERS,
        ),
        ApiErrorId.EYE_ALREADY_INSPECTED_THIS_CYCLE.value,
        409,
    )

    rows, meta = validate_paginated(
        api.list_quality_inspections(
            INSPECTOR_A_HEADERS, {"lab_job_id": scenario["job_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert fixtures.read_inspection(api, first["id"])["measured_sphere"] == -2.0

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "EDGED"
    assert job["rework_cycle_count"] == 0


def test_a_defect_code_outside_the_vocabulary_is_refused(api):
    """SMUDGE is a string, so it survives to the dedicated vocabulary gate.

    PRD 3.7: "Every supplied cosmetic code must be in the vocabulary above, and an
    unrecognised member yields `ERR_UNKNOWN_DEFECT_CODE`."

    Design: Corner/errors/an_unknown_cosmetic_defect_code_is_refused
    """
    scenario = fixtures.stock_edged_job(api)

    error = validate_error(
        api.create_quality_inspection(
            f.create_quality_inspection_payload(
                scenario["job_id"], "OD", cosmetic_defect_codes=["SMUDGE"]
            ),
            INSPECTOR_A_HEADERS,
        ),
        ApiErrorId.UNKNOWN_DEFECT_CODE.value,
        400,
    )
    assert error["error_id"] != ApiErrorId.VALIDATION.value

    _, meta = validate_paginated(
        api.list_quality_inspections(
            INSPECTOR_A_HEADERS, {"lab_job_id": scenario["job_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_known_code_the_standard_disallows_is_recorded_as_a_failure(api):
    """DEEP_SCRATCH is in the vocabulary but not in this standard's allowed list.

    PRD 3.7: "`COSMETIC` fails when any code in `cosmetic_defect_codes` is not present
    in the standard's `allowed_cosmetic_defect_codes`."

    Design: Corner/errors/an_unknown_cosmetic_defect_code_is_refused
    """
    scenario = fixtures.stock_edged_job(api)
    assert scenario["standard"]["allowed_cosmetic_defect_codes"] == ["MINOR_EDGE_CHIP"]

    inspection = fixtures.inspect_eye(
        api, scenario["job_id"], "OD", cosmetic_defect_codes=["DEEP_SCRATCH"]
    )

    assert inspection["verdict"] == "FAIL"
    assert inspection["failed_metrics"] == ["COSMETIC"]
    assert inspection["cosmetic_defect_codes"] == ["DEEP_SCRATCH"]
    assert inspection["sphere_delta"] == 0.0


def test_a_second_case_on_a_job_that_already_has_one_is_refused(api):
    """The open-case answer must beat the scrapped-job answer to be reachable at all.

    PRD 3.8: "Then the open-case gate: if a remake case for that job already exists
    with `status` of `SUBMITTED` or `ADJUDICATED`, the response is
    `ERR_OPEN_REMAKE_CASE_EXISTS`."

    Design: Corner/errors/a_second_open_case_on_the_same_job_is_refused
    """
    scenario = _first_job_carrying_an_open_case_and_a_replacement_job(api)

    error = validate_error(
        api.create_remake_case(
            f.create_remake_case_payload(
                scenario["first_job_id"], defect_codes=["WRONG_FRAME"]
            ),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.OPEN_REMAKE_CASE_EXISTS.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.LAB_JOB_STATE_INVALID.value

    rows, meta = validate_paginated(
        api.list_remake_cases(
            OPTICIAN_A_HEADERS, {"lab_job_id": scenario["first_job_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario["case_id"]

    assert fixtures.read_job(api, scenario["job_id"])["status"] == "QUEUED"
    assert fixtures.read_order(api, scenario["order_id"])["remake_count"] == 1


def test_surfacing_booked_on_a_stock_route_job_is_refused(api):
    """The booking is well formed; the job simply has no surfacing step.

    PRD 3.6: "Then the route check: a surfacing booking against a job whose `route` is
    `STOCK_EDGE_ONLY` is rejected with `ERR_OPERATION_NOT_PERMITTED_FOR_ROUTE`, because
    a stock edge-only job has no surfacing step at all."

    Design: Corner/errors/surfacing_booked_on_a_stock_route_job_is_refused
    """
    scenario = _queued_stock_job_with_a_generator(api)
    job = fixtures.read_job(api, scenario["job_id"])
    assert job["route"] == "STOCK_EDGE_ONLY"
    assert job["blank_lot_id"] is None

    validate_error(
        api.create_lab_operation(
            f.create_surfacing_operation_payload(
                scenario["job_id"],
                scenario["job_version"],
                scenario["machine_id"],
                *BOOKED_WINDOW,
            ),
            TECHNICIAN_A_HEADERS,
        ),
        ApiErrorId.OPERATION_NOT_PERMITTED_FOR_ROUTE.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_lab_operations(
            TECHNICIAN_A_HEADERS, {"machine_id": scenario["machine_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_an_inspection_with_no_effective_standard_is_refused(api):
    """A standard dated a month ahead is invisible to today's measurement.

    PRD 3.7: "Fourth, a tolerance standard must resolve, and the empty result yields
    `ERR_NO_TOLERANCE_STANDARD`."

    Design: Corner/errors/an_inspection_with_no_effective_standard_is_refused_until_the_clock_advances
    """
    scenario = _edged_job_with_only_a_future_standard(api)

    validate_error(
        api.create_quality_inspection(
            f.create_quality_inspection_payload(scenario["job_id"], "OD"),
            INSPECTOR_A_HEADERS,
        ),
        ApiErrorId.NO_TOLERANCE_STANDARD.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_quality_inspections(
            INSPECTOR_A_HEADERS, {"lab_job_id": scenario["job_id"]}
        )
    )
    assert meta["total_count"] == 0
    assert fixtures.read_job(api, scenario["job_id"])["status"] == "EDGED"


def test_the_identical_inspection_binds_once_the_clock_reaches_the_standard(api):
    """The effective-from boundary is inclusive, so 1 September makes it visible.

    PRD 3.7: "An empty candidate set is the `ERR_NO_TOLERANCE_STANDARD` case above;
    because a future-dated standard is invisible, advancing the clock across its
    effective date genuinely changes the verdict of an otherwise identical
    measurement."

    Design: Corner/errors/an_inspection_with_no_effective_standard_is_refused_until_the_clock_advances
    """
    scenario = _edged_job_with_only_a_future_standard(api)
    validate_error(
        api.create_quality_inspection(
            f.create_quality_inspection_payload(scenario["job_id"], "OD"),
            INSPECTOR_A_HEADERS,
        ),
        ApiErrorId.NO_TOLERANCE_STANDARD.value,
        422,
    )

    fixtures.set_clock(api, FUTURE_STANDARD_CLOCK)
    inspection = fixtures.inspect_eye(api, scenario["job_id"], "OD")

    assert inspection["tolerance_standard_id"] == scenario["standard_id"]
    assert inspection["verdict"] == "PASS"
    assert inspection["cycle_index"] == 0

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "EDGED"
    assert job["rework_cycle_count"] == 0


def test_a_second_lab_job_on_an_order_that_already_has_one_is_refused(api):
    """The specific answer is ordered above the state answer to stay reachable.

    PRD 3.5: "First, the single-active-job gate: if the order already has a lab job
    whose `status` is neither `SCRAPPED` nor `RELEASED`, the request is rejected with
    `ERR_ACTIVE_LAB_JOB_EXISTS`."

    Design: Corner/errors/a_second_lab_job_on_an_order_that_already_has_an_active_one_is_refused
    """
    scenario = fixtures.stock_queued_job(api)

    error = validate_error(
        api.create_lab_job(
            f.create_lab_job_payload(scenario["order_id"]), TECHNICIAN_A_HEADERS
        ),
        ApiErrorId.ACTIVE_LAB_JOB_EXISTS.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ORDER_STATE_INVALID.value

    rows, meta = validate_paginated(
        api.list_lab_jobs(TECHNICIAN_A_HEADERS, {"rx_order_id": scenario["order_id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario["job_id"]
    assert fixtures.read_order(api, scenario["order_id"])["fulfillment_status"] == (
        "IN_LAB"
    )


def test_withdrawing_an_order_with_a_running_occupation_is_refused(api):
    """A lens in the chuck outranks both state gates the withdrawal would pass.

    PRD 3.9: "Three gates apply in order: a `fulfillment_status` of `DISPENSED` or
    `CANCELLED` yields `ERR_ORDER_STATE_INVALID`, so withdrawal is available from
    `DRAFT`, `LAYOUT_READY`, `IN_LAB` and `REMAKE_PENDING`; a `billing_status` other
    than `PROVISIONAL_QUOTED` yields `ERR_BILLING_ALREADY_FINALIZED`, because money
    that has been charged cannot be un-charged by withdrawal; and any occupation of the
    order's newest lab job whose `status` is `RUNNING` yields
    `ERR_OPERATION_IN_PROGRESS`, because a lens currently in a chuck cannot be
    abandoned mid-cut."

    Design: Corner/errors/cancelling_an_order_with_a_running_operation_is_refused
    """
    scenario = _running_edging_operation(api)

    validate_error(
        api.cancel_rx_order(scenario["order_id"], OPTICIAN_A_HEADERS),
        ApiErrorId.OPERATION_IN_PROGRESS.value,
        409,
    )

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "IN_LAB"
    assert order["billing_status"] == "PROVISIONAL_QUOTED"
    assert order["gross_charge_cents"] == SELF_PAY_GROSS
    assert fixtures.read_job(api, scenario["job_id"])["status"] == "EDGING"
    assert fixtures.read_operation(api, scenario["operation_id"])["status"] == "RUNNING"
