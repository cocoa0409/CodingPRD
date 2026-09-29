"""A faultless prescription held up by the standing of the doctor who wrote it."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START_RENDERED
from test_helpers.test_users import MANAGER_A_HEADERS, OPTICIAN_A_HEADERS


def _unverified_prescription_of_a_suspended_prescriber(api):
    """The claimed credentials match the record exactly; only standing is wrong."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api, MANAGER_A_HEADERS)
    assert prescriber["status"] == "ACTIVE"
    patient = fixtures.create_self_pay_patient(api)
    prescription = validate_success(
        api.create_prescription(
            f.create_multifocal_prescription_payload(patient["id"], prescriber["id"]),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    assert prescription["verification_status"] == "UNVERIFIED"

    suspended = validate_success(
        api.patch_prescriber_status(
            prescriber["id"], {"status": "SUSPENDED"}, MANAGER_A_HEADERS
        )
    )
    assert suspended["status"] == "SUSPENDED"
    return {
        "prescriber_id": prescriber["id"],
        "patient_id": patient["id"],
        "prescription_id": prescription["id"],
    }


def _verify(api, scenario):
    return api.verify_prescription(
        scenario["prescription_id"], f.create_verification_payload(), OPTICIAN_A_HEADERS
    )


def test_a_suspended_prescriber_blocks_verification_of_a_valid_prescription(api):
    """Nothing about the prescription is wrong, yet the standing gate refuses it.

    PRD 3.2: "Third, and on both optician verification and self-attestation, the
    standing gate: if the referenced prescriber's `status` is anything other than
    `ACTIVE`, the request is rejected with `ERR_PRESCRIBER_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/prescription_verification_blocked_by_a_suspended_prescriber_record
    """
    scenario = _unverified_prescription_of_a_suspended_prescriber(api)

    validate_error(_verify(api, scenario), ApiErrorId.PRESCRIBER_NOT_ACTIVE.value, 422)

    prescription = fixtures.read_prescription(api, scenario["prescription_id"])
    assert prescription["verification_status"] == "UNVERIFIED"
    assert prescription["verified_at"] is None


def test_reinstating_the_prescriber_lets_the_identical_call_succeed(api):
    """Restoring standing is the only change, and verification then lands.

    PRD 3.2: "Optician verification advances `UNVERIFIED → VERIFIED`. It sets
    `verified_at` to the logical clock, sets `verification_note` to the note supplied
    in the request when one is supplied, and recomputes the prescriber's
    `verified_rx_count`."

    Design: Difficulty/cross_entity_state_dependency/prescription_verification_blocked_by_a_suspended_prescriber_record
    """
    scenario = _unverified_prescription_of_a_suspended_prescriber(api)
    validate_error(_verify(api, scenario), ApiErrorId.PRESCRIBER_NOT_ACTIVE.value, 422)

    restored = validate_success(
        api.patch_prescriber_status(
            scenario["prescriber_id"], {"status": "ACTIVE"}, MANAGER_A_HEADERS
        )
    )
    assert restored["status"] == "ACTIVE"

    prescription = validate_success(_verify(api, scenario))
    assert prescription["verification_status"] == "VERIFIED"
    assert prescription["verified_at"] == CLOCK_START_RENDERED


def test_the_prescriber_count_only_moves_on_the_successful_verification(api):
    """The rejected attempt leaves the count at zero; the accepted one raises it.

    PRD 3.2: "Optician verification advances `UNVERIFIED → VERIFIED`. It sets
    `verified_at` to the logical clock, sets `verification_note` to the note supplied
    in the request when one is supplied, and recomputes the prescriber's
    `verified_rx_count`."

    Design: Difficulty/cross_entity_state_dependency/prescription_verification_blocked_by_a_suspended_prescriber_record
    """
    scenario = _unverified_prescription_of_a_suspended_prescriber(api)
    validate_error(_verify(api, scenario), ApiErrorId.PRESCRIBER_NOT_ACTIVE.value, 422)
    assert fixtures.read_prescriber(api, scenario["prescriber_id"])["verified_rx_count"] == 0

    validate_success(
        api.patch_prescriber_status(
            scenario["prescriber_id"], {"status": "ACTIVE"}, MANAGER_A_HEADERS
        )
    )
    validate_success(_verify(api, scenario))

    assert fixtures.read_prescriber(api, scenario["prescriber_id"])["verified_rx_count"] == 1
