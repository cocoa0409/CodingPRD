"""An order raised against a prescription that is both unverified and expired."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import MANAGER_A_HEADERS, OPTICIAN_A_HEADERS


def _expired_unverified_prescription(api):
    """A twelve-month prescription issued in June 2025, left unverified."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api, MANAGER_A_HEADERS)
    plan = fixtures.create_plan(api)
    patient = fixtures.create_insured_patient(api, plan["id"])
    design = fixtures.create_progressive_design(api)
    prescription = validate_success(
        api.create_prescription(
            f.create_multifocal_prescription_payload(
                patient["id"], prescriber["id"], issued_on="2025-06-01"
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    assert prescription["verification_status"] == "UNVERIFIED"
    assert prescription["expires_at"] == "2026-06-01T00:00:00.000Z"
    return {
        "patient_id": patient["id"],
        "prescription_id": prescription["id"],
        "design_id": design["id"],
        "prescription": prescription,
    }


def _order_attempt(api, scenario):
    return api.create_rx_order(
        f.create_progressive_rx_order_payload(
            scenario["patient_id"], scenario["prescription_id"], scenario["design_id"]
        ),
        OPTICIAN_A_HEADERS,
    )


def test_verification_failure_is_reported_before_expiry(api):
    """Both rules are broken by one request; only the verification answer surfaces.

    PRD 3.3: "Only then is expiry considered: if the logical clock is at or after the
    prescription's `expires_at`, the response is `ERR_RX_EXPIRED`. Because
    verification is checked first, an unverified *and* expired prescription reports
    the verification failure; expiry is only ever reported on a prescription that is
    genuinely verified."

    Design: Difficulty/priority_pair_validation_conflict/unverified_and_expired_prescription_reports_not_verified_before_expired
    """
    scenario = _expired_unverified_prescription(api)

    error = validate_error(
        _order_attempt(api, scenario), ApiErrorId.RX_NOT_VERIFIED.value, 409
    )

    assert error["error_id"] != ApiErrorId.RX_EXPIRED.value

    _, meta = validate_paginated(api.list_rx_orders(OPTICIAN_A_HEADERS))
    assert meta["total_count"] == 0


def test_expiry_does_not_block_verification_itself(api):
    """A stale prescription may still be verified; only ordering is barred.

    PRD 3.2: "Four gates guard the verification actions, evaluated in this order.
    First, the state gate: if the prescription's `verification_status` admits no
    transition for the requested action, the request is rejected with
    `ERR_RX_STATE_INVALID`."

    PRD 3.2: "Optician verification advances `UNVERIFIED → VERIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/unverified_and_expired_prescription_reports_not_verified_before_expired
    """
    scenario = _expired_unverified_prescription(api)
    validate_error(_order_attempt(api, scenario), ApiErrorId.RX_NOT_VERIFIED.value, 409)

    verified = validate_success(
        api.verify_prescription(
            scenario["prescription_id"],
            f.create_verification_payload(),
            OPTICIAN_A_HEADERS,
        )
    )

    assert verified["verification_status"] == "VERIFIED"


def test_expiry_surfaces_once_the_verification_gate_is_satisfied(api):
    """The temporal rule was live all along and answers as soon as it is reachable.

    PRD 3.2: "A prescription is usable while the logical clock is **strictly before**
    `expires_at`; a clock exactly equal to `expires_at` is already too late."

    Design: Difficulty/priority_pair_validation_conflict/unverified_and_expired_prescription_reports_not_verified_before_expired
    """
    scenario = _expired_unverified_prescription(api)
    validate_error(_order_attempt(api, scenario), ApiErrorId.RX_NOT_VERIFIED.value, 409)
    validate_success(
        api.verify_prescription(
            scenario["prescription_id"],
            f.create_verification_payload(),
            OPTICIAN_A_HEADERS,
        )
    )

    validate_error(_order_attempt(api, scenario), ApiErrorId.RX_EXPIRED.value, 422)

    _, meta = validate_paginated(api.list_rx_orders(OPTICIAN_A_HEADERS))
    assert meta["total_count"] == 0
