"""Evaluation measurement: pinned truncated-cone rounding order, measurement
sufficiency boundaries, and the patient-version optimistic-concurrency guard.

Queue A: combinatorial_limb_volume_rounding_order, boundary_insufficient_measurement_below_two.
Queue B: error_measurement_length_mismatch, OCC instances.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    get_success_data,
    create_evaluation_payload,
    create_garment_order_payload,
    create_patient,
    create_finalized_evaluation,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]


# ---- Queue A: combinatorial_limb_volume_rounding_order (>=2 tests) ----

def test_limb_volume_uses_pinned_per_segment_rounding(api):
    """PRD §2.7: "each truncated-cone segment volume is rounded to two decimal places
    first, the rounded segments are then summed, and only that sum is rounded — to one
    decimal place — to produce the reported volume."

    Design: Difficulty/combinatorial_formula/combinatorial_limb_volume_rounding_order
    """
    patient = create_patient()
    payload = create_evaluation_payload(
        patient["id"], patient["version"],
        etiology="PRIMARY", isl_stage="STAGE_I", interval_cm=4,
        circumferences_cm=[18, 18, 20], contralateral_circumferences_cm=[18, 18, 20],
    )
    data = validate_success(api.create_evaluation(payload, CLINICIAN), expected_status=201)
    assert data["limb_volume_ml"] == 218.2, (
        f"expected pinned per-segment rounding 218.2, got {data['limb_volume_ml']}"
    )


def test_excess_volume_is_zero_for_identical_limbs(api):
    """PRD §3.2: "The excess_volume_ml is the affected volume minus the contralateral
    volume, floored at zero (never negative), rounded to one decimal place."

    Design: Difficulty/combinatorial_formula/combinatorial_limb_volume_rounding_order
    """
    patient = create_patient()
    payload = create_evaluation_payload(
        patient["id"], patient["version"],
        etiology="PRIMARY", isl_stage="STAGE_I", interval_cm=4,
        circumferences_cm=[18, 18, 20], contralateral_circumferences_cm=[18, 18, 20],
    )
    data = validate_success(api.create_evaluation(payload, CLINICIAN), expected_status=201)
    assert data["excess_volume_ml"] == 0.0


# ---- Queue A: boundary_insufficient_measurement_below_two (>=2 tests) ----

def test_single_circumference_point_rejected(api):
    """PRD §3.2: "at least two circumference points are required, and fewer than two is
    rejected with ERR_INSUFFICIENT_MEASUREMENT."

    Design: Difficulty/boundary_precision_check/boundary_insufficient_measurement_below_two
    """
    patient = create_patient()
    payload = create_evaluation_payload(
        patient["id"], patient["version"],
        etiology="PRIMARY", isl_stage="STAGE_I", interval_cm=4,
        circumferences_cm=[20], contralateral_circumferences_cm=[20],
    )
    validate_error(api.create_evaluation(payload, CLINICIAN), ApiErrorId.ERR_INSUFFICIENT_MEASUREMENT)


def test_exactly_two_circumference_points_accepted(api):
    """PRD §3.2: "at least two circumference points are required, and fewer than two is
    rejected with ERR_INSUFFICIENT_MEASUREMENT."

    Design: Difficulty/boundary_precision_check/boundary_insufficient_measurement_below_two
    """
    patient = create_patient()
    payload = create_evaluation_payload(
        patient["id"], patient["version"],
        etiology="PRIMARY", isl_stage="STAGE_I", interval_cm=4,
        circumferences_cm=[18, 20], contralateral_circumferences_cm=[18, 20],
    )
    validate_success(api.create_evaluation(payload, CLINICIAN), expected_status=201)


# ---- Queue B: measurement length mismatch ----

def test_unequal_circumference_arrays_rejected(api):
    """PRD §3.2: "The affected and contralateral arrays must be exactly the same length;
    a length difference is rejected with ERR_MEASUREMENT_LENGTH_MISMATCH."

    Design: Corner/validations/error_measurement_length_mismatch
    """
    patient = create_patient()
    payload = create_evaluation_payload(
        patient["id"], patient["version"],
        etiology="PRIMARY", isl_stage="STAGE_I", interval_cm=4,
        circumferences_cm=[18, 20, 22], contralateral_circumferences_cm=[18, 20],
    )
    validate_error(api.create_evaluation(payload, CLINICIAN), ApiErrorId.ERR_MEASUREMENT_LENGTH_MISMATCH)


# ---- Queue B: OCC ----

def test_evaluation_create_advances_patient_version(api):
    """PRD §3.2: "Every successful evaluation create also increments the patient's
    version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_evaluation_create_success_increments_patient_version
    """
    patient = create_patient()
    payload = create_evaluation_payload(patient["id"], patient["version"])
    validate_success(api.create_evaluation(payload, CLINICIAN), expected_status=201)
    refreshed = get_success_data(api.get_patient(patient["id"], CLINICIAN))
    assert refreshed["version"] == 2, f"expected version 2 after create, got {refreshed['version']}"


def test_evaluation_create_with_stale_patient_version_rejected(api):
    """PRD §2.6: "If that value does not equal the patient's current version, the create
    is rejected with ERR_STALE_PATIENT_VERSION (HTTP 412), and no evaluation or order is
    created and no supersession occurs."

    Design: Corner/cross_cutting_complexity_layers/occ_evaluation_create_stale_version_rejected
    """
    patient = create_patient()
    # First create advances Patient.version to 2.
    validate_success(
        api.create_evaluation(create_evaluation_payload(patient["id"], patient["version"]), CLINICIAN),
        expected_status=201,
    )
    # Second create still carrying the stale version 1 is rejected.
    stale = create_evaluation_payload(patient["id"], patient["version"], body_region="RIGHT_ARM")
    validate_error(api.create_evaluation(stale, CLINICIAN), ApiErrorId.ERR_STALE_PATIENT_VERSION)


def test_garment_order_create_with_stale_patient_version_rejected(api):
    """PRD §2.6: "Creating an evaluation and creating a garment order each require a
    non-optional expected_patient_version field carrying the patient version the client
    last observed. If that value does not equal the patient's current version, the create
    is rejected with ERR_STALE_PATIENT_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_garment_order_stale_version_covered
    """
    patient = create_patient()  # version 1
    evaluation = create_finalized_evaluation(patient["id"], body_region="LEFT_ARM")  # version now 2
    # Client still holds the stale version 1.
    payload = create_garment_order_payload(patient["id"], evaluation["id"], patient["version"])
    validate_error(api.create_garment_order(payload, CLINICIAN), ApiErrorId.ERR_STALE_PATIENT_VERSION)
