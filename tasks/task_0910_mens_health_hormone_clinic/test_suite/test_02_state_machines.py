"""Invalid-transition and terminal-state lockdown probes across state machines."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_patient_payload, create_membership_plan_payload, create_membership_payload,
    setup_active_plan, setup_plan_with_prescription, get_plan,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_resume_active_plan_rejected_invalid_state(api):
    """PRD §3.5: "A `Clinician` resumes a held plan, moving it from `MONITORING_HOLD`
    back to `ACTIVE`; resumption requires the plan to be in `MONITORING_HOLD`
    (otherwise `ERR_INVALID_STATE`) and requires the patient's latest `REVIEWED` lab
    panel to have `is_unsafe` equal to false (otherwise `ERR_HEMATOCRIT_UNSAFE`)."

    Design: Corner/state_machines/resume_from_active_plan_invalid_state
    """
    ctx = setup_active_plan()
    validate_error(
        api.resume_treatment_plan(ctx["plan_id"], ctx["clinician_headers"]),
        ApiErrorId.ERR_INVALID_STATE, 409,
    )
    assert get_plan(ctx["plan_id"])["status"] == "ACTIVE", "plan must remain ACTIVE after rejected resume"


def test_revoke_already_revoked_prescription_rejected(api):
    """PRD §3.6: "A `Clinician` may revoke a prescription, and the system revokes one
    as a plan-suspension cascade; revocation is permitted from `ISSUED` or `SUSPENDED`
    (otherwise `ERR_INVALID_STATE`) and cancels every `PENDING_REVIEW` refill order
    behind that prescription (cascade link 3)."

    Design: Corner/state_machines/revoke_already_revoked_prescription_invalid_state
    """
    ctx = setup_plan_with_prescription()
    get_success_data(api.revoke_prescription(ctx["rx_id"], ctx["clinician_headers"]))
    validate_error(
        api.revoke_prescription(ctx["rx_id"], ctx["clinician_headers"]),
        ApiErrorId.ERR_INVALID_STATE, 409,
    )


def test_cancel_already_cancelled_membership_rejected(api):
    """PRD §3.2: "Cancellation moves a membership to `CANCELLED` and is permitted while
    `subscription_status` is `TRIAL` or `ACTIVE`, failing with `ERR_INVALID_STATE`
    from any other state."

    Design: Corner/state_machines/cancel_already_cancelled_membership_invalid_state
    """
    patient = validate_success(api.create_patient(create_patient_payload(), ADMIN), 201)
    plan = validate_success(
        api.create_membership_plan(create_membership_plan_payload(tier="CORE"), ADMIN), 201
    )
    membership = validate_success(
        api.create_membership(create_membership_payload(patient["id"], plan["id"]), ADMIN), 201
    )
    get_success_data(api.cancel_membership(membership["id"], ADMIN))
    validate_error(
        api.cancel_membership(membership["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE, 409,
    )
