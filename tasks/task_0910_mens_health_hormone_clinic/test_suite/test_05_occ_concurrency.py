"""Optimistic-concurrency stale-version guards (PRD §2.5)."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_refill_order_payload,
    setup_active_plan, setup_plan_with_prescription,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_titration_create_stale_plan_version_rejected(api):
    """PRD §2.5: "Proposing a dose titration for a treatment plan requires
    `expected_plan_version` in the request body, carrying the client's last observed
    `version` of that `TreatmentPlan`. If `expected_plan_version` does not equal the
    plan's current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/titration_create_stale_plan_version_returns_412
    """
    ctx = setup_active_plan()
    stale_version = ctx["plan_version"]
    cln = ctx["clinician_headers"]
    # First proposal consumes the observed version and advances the plan's version.
    get_success_data(
        api.create_titration(ctx["plan_id"], {"proposed_dose_mg": 120, "expected_plan_version": stale_version}, cln)
    )
    # Second proposal still carrying the pre-proposal version is stale.
    validate_error(
        api.create_titration(ctx["plan_id"], {"proposed_dose_mg": 130, "expected_plan_version": stale_version}, cln),
        ApiErrorId.ERR_STALE_VERSION, 412,
    )


def test_refill_create_stale_prescription_version_rejected(api):
    """PRD §2.5: "Creating a refill order requires `expected_prescription_version` in
    the request body, carrying the client's last observed `version` of the referenced
    `ControlledSubstancePrescription`. If it does not equal the prescription's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/refill_create_stale_prescription_version_returns_412
    """
    ctx = setup_plan_with_prescription()
    stale_version = ctx["rx_version"]
    # First refill create consumes the observed version and bumps the prescription's version.
    get_success_data(api.create_refill_order(
        create_refill_order_payload(ctx["rx_id"], ctx["membership_id"], ctx["patient_id"], stale_version), ADMIN
    ))
    # Second create still carrying the original version is stale.
    validate_error(
        api.create_refill_order(
            create_refill_order_payload(ctx["rx_id"], ctx["membership_id"], ctx["patient_id"], stale_version), ADMIN
        ),
        ApiErrorId.ERR_STALE_VERSION, 412,
    )
