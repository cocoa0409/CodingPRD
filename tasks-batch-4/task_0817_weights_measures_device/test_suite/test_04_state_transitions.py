"""State-machine guards: invalid transitions, terminal lockdown, idempotency, complaints.

Covers corner state_machine instances finalize_from_scheduled,
retire_already_retired, pay_penalty_twice, resolve_uphold_requires_condemned,
complaint_dismiss_from_filed.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    bootstrap_est_inspector, register_device, create_establishment,
    create_complaint, schedule_inspection, accuracy_fail_condemn,
    first_penalty_for_device, make_inspector_headers,
    api_client,
)

ADMIN = TEST_USERS["program_admin_headers"]


# --------------------------------------------------------------------------- #
# Corner/state_machines/finalize_from_scheduled_returns_not_in_progress
# --------------------------------------------------------------------------- #
def test_finalize_scheduled_inspection_returns_not_in_progress():
    """PRD §3.7: "It may be applied only to an inspection that is `IN_PROGRESS`;
    finalizing an inspection in any other state is rejected with
    `ERR_INSPECTION_NOT_IN_PROGRESS`."

    Design: Corner/state_machines/finalize_from_scheduled_returns_not_in_progress
    """
    est, inspector = bootstrap_est_inspector(est_name="Inv T Store", jurisdiction="CA-26")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-INVT",
                          device_class="CLASS_III")
    ins = schedule_inspection(dev["id"], inspector["id"],
                              "2026-03-25T09:00:00Z", "2026-03-25T10:00:00Z")
    resp = api_client.finalize_inspection(ins["id"], make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_IN_PROGRESS.value)


# --------------------------------------------------------------------------- #
# Corner/state_machines/retire_already_retired_returns_device_retired
# --------------------------------------------------------------------------- #
def test_retire_already_retired_device_returns_device_retired():
    """PRD §3.8: "Once `RETIRED`, a device is terminal and no longer testable: any later
    action that targets an already-retired device — a second retirement, or any state
    transition on it — is rejected with `ERR_DEVICE_RETIRED`, while an attempt to
    schedule or start an inspection against it fails with `ERR_DEVICE_NOT_TESTABLE` as
    described in §3.3 and §3.4."

    Design: Corner/state_machines/retire_already_retired_returns_device_retired
    """
    est = create_establishment(name="Term Store", jurisdiction="CA-27")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-TERM")
    validate_success(api_client.retire_device(dev["id"], ADMIN, {"reason": "first"}), 200)
    resp = api_client.retire_device(dev["id"], ADMIN, {"reason": "again"})
    validate_error(resp, ApiErrorId.ERR_DEVICE_RETIRED.value)


# --------------------------------------------------------------------------- #
# Corner/state_machines/pay_penalty_twice_returns_not_payable
# --------------------------------------------------------------------------- #
def test_pay_already_paid_penalty_returns_not_payable():
    """PRD §3.9: "A penalty that is not in `ASSESSED` cannot be paid and the attempt is
    rejected with `ERR_PENALTY_NOT_PAYABLE`; an establishment paying a penalty it does
    not own is rejected with `ERR_OWNERSHIP_VIOLATION`."

    Design: Corner/state_machines/pay_penalty_twice_returns_not_payable
    """
    est, inspector = bootstrap_est_inspector(est_name="Pay2 Store", jurisdiction="CA-28")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-PAY2",
                          device_class="CLASS_III")
    accuracy_fail_condemn(inspector, dev, "2026-03-26T09:00:00Z", "2026-03-26T10:00:00Z",
                          applied_load=3000, indicated_value=3004)
    penalty = first_penalty_for_device(dev["id"])
    validate_success(api_client.pay_penalty(penalty["id"], ADMIN), 200)
    resp = api_client.pay_penalty(penalty["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PENALTY_NOT_PAYABLE.value)


# --------------------------------------------------------------------------- #
# Corner/state_machines/resolve_uphold_requires_condemned_returns_invalid_state
# --------------------------------------------------------------------------- #
def test_uphold_complaint_on_non_condemned_device_returns_invalid_state():
    """PRD §3.8: "Upholding a complaint moves it from `FILED` to `UPHELD`, but only once
    a re-test has actually confirmed the problem: the targeted device must be in `status`
    `CONDEMNED` at the time of resolution, and an attempt to uphold a complaint whose
    device is not condemned is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/resolve_uphold_requires_condemned_returns_invalid_state
    """
    est = create_establishment(name="Cmp Store", jurisdiction="CA-29")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-CMP")
    complaint = create_complaint(dev["id"], complainant_name="Ann", description="reads high")
    resp = api_client.resolve_complaint(complaint["id"], {"disposition": "UPHELD"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------- #
# Corner/state_machines/complaint_dismiss_from_filed_succeeds
# --------------------------------------------------------------------------- #
def test_dismiss_filed_complaint_moves_to_dismissed():
    """PRD §3.8: "Dismissing a complaint moves it from `FILED` to `DISMISSED` with no
    state precondition."

    Design: Corner/state_machines/complaint_dismiss_from_filed_succeeds
    """
    est = create_establishment(name="Dis Store", jurisdiction="CA-30")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-DIS")
    complaint = create_complaint(dev["id"], complainant_name="Bob", description="unfounded")
    resp = api_client.resolve_complaint(complaint["id"], {"disposition": "DISMISSED"}, ADMIN)
    data = validate_success(resp, 200)
    assert data["status"] == "DISMISSED"
