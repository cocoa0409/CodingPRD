"""Suspension cascade, ledger conservation, and sanction preconditions.

Covers difficulty instances suspend_out_of_service_void_seal_depth3,
balance_conserved_penalty_assess_then_waive, sealed_count_conserved_seal_then_condemn;
plus corner suspend/reinstate validation instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    bootstrap_est_inspector, register_device, create_establishment,
    accuracy_pass_seal, accuracy_fail_condemn, in_progress_accuracy,
    finalize_inspection, get_device, get_establishment,
    first_penalty_for_device, first_seal_for_device,
    api_client,
)

ADMIN = TEST_USERS["program_admin_headers"]


# --------------------------------------------------------------------------- #
# Difficulty/transitive_cascade/suspend_out_of_service_void_seal_depth3
# --------------------------------------------------------------------------- #
def test_suspend_cascades_sealed_device_to_out_of_service():
    """PRD §3.1: "Every device of that establishment whose `status` is `SEALED` is moved
    from `SEALED` to `OUT_OF_SERVICE`; for each such device its `ACTIVE` seal is moved
    from `ACTIVE` to `VOIDED`; and the establishment's `sealed_device_count` is then
    recomputed, dropping by the number of devices just taken out of service."

    Design: Difficulty/transitive_cascade/suspend_out_of_service_void_seal_depth3
    """
    est, inspector = bootstrap_est_inspector(est_name="Casc B Store", jurisdiction="CA-08")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-CB",
                          device_class="CLASS_III")
    accuracy_pass_seal(inspector, dev, "2026-03-13T09:00:00Z", "2026-03-13T10:00:00Z")
    resp = api_client.suspend_establishment(est["id"], ADMIN, {"reason": "nonpayment"})
    data = validate_success(resp, 200)
    assert data["status"] == "SUSPENDED"
    assert get_device(dev["id"])["status"] == "OUT_OF_SERVICE"


def test_suspend_voids_seal_and_zeroes_sealed_count():
    """PRD §3.1: "Every device of that establishment whose `status` is `SEALED` is moved
    from `SEALED` to `OUT_OF_SERVICE`; for each such device its `ACTIVE` seal is moved
    from `ACTIVE` to `VOIDED`; and the establishment's `sealed_device_count` is then
    recomputed, dropping by the number of devices just taken out of service."

    Design: Difficulty/transitive_cascade/suspend_out_of_service_void_seal_depth3
    """
    est, inspector = bootstrap_est_inspector(est_name="Casc B Store", jurisdiction="CA-08")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-CB",
                          device_class="CLASS_III")
    accuracy_pass_seal(inspector, dev, "2026-03-13T09:00:00Z", "2026-03-13T10:00:00Z")
    data = validate_success(api_client.suspend_establishment(est["id"], ADMIN, {}), 200)
    assert data["sealed_device_count"] == 0
    assert first_seal_for_device(dev["id"])["status"] == "VOIDED"


# --------------------------------------------------------------------------- #
# Difficulty/compensating_invariant/balance_conserved_penalty_assess_then_waive
# --------------------------------------------------------------------------- #
def test_balance_reflects_fee_plus_assessed_penalty_before_waive():
    """PRD §2.8: "The `balance_due_cents` of an establishment is the sum of the
    `amount_due_cents` of all of that establishment's fee invoices whose `status` is
    `DUE`, plus the sum of the `amount_cents` of all of that establishment's penalties
    whose `status` is `ASSESSED`."

    Design: Difficulty/compensating_invariant/balance_conserved_penalty_assess_then_waive
    """
    est, inspector = bootstrap_est_inspector(est_name="Inv1 Store", jurisdiction="CA-17")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-INV1",
                          device_class="CLASS_III")
    accuracy_fail_condemn(inspector, dev, "2026-03-21T09:00:00Z", "2026-03-21T10:00:00Z",
                          applied_load=3000, indicated_value=3004)
    assert get_establishment(est["id"])["balance_due_cents"] == 17000  # 12000 fee + 5000 penalty


def test_waiving_penalty_returns_balance_to_fee_only_total():
    """PRD §2.8: "Invoices that are `PAID` and penalties that are `PAID` or `WAIVED` do
    not contribute to the balance."
    PRD §3.9: "a waiver moves the penalty from `ASSESSED` to `WAIVED` and likewise
    recomputes `balance_due_cents`, removing the waived `amount_cents` from the total."

    Design: Difficulty/compensating_invariant/balance_conserved_penalty_assess_then_waive
    """
    est, inspector = bootstrap_est_inspector(est_name="Inv1 Store", jurisdiction="CA-17")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-INV1",
                          device_class="CLASS_III")
    accuracy_fail_condemn(inspector, dev, "2026-03-21T09:00:00Z", "2026-03-21T10:00:00Z",
                          applied_load=3000, indicated_value=3004)
    penalty = first_penalty_for_device(dev["id"])
    waived = validate_success(
        api_client.waive_penalty(penalty["id"], ADMIN, {"reason": "adjudicated"}), 200)
    assert waived["status"] == "WAIVED"
    assert get_establishment(est["id"])["balance_due_cents"] == 12000  # fee-only remainder


# --------------------------------------------------------------------------- #
# Difficulty/compensating_invariant/sealed_count_conserved_seal_then_condemn
# --------------------------------------------------------------------------- #
def test_sealed_count_is_one_after_seal():
    """PRD §2.8: "The `sealed_device_count` of an establishment is the number of that
    establishment's devices whose `status` is currently `SEALED`. It is recomputed on
    every device transition into or out of `SEALED` — whether from a passing inspection
    that seals a device, a failing re-test or retirement that voids a seal, or the
    suspension cascade described in §3.1."

    Design: Difficulty/compensating_invariant/sealed_count_conserved_seal_then_condemn
    """
    est, inspector = bootstrap_est_inspector(est_name="Inv2 Store", jurisdiction="CA-18")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-INV2",
                          device_class="CLASS_III")
    accuracy_pass_seal(inspector, dev, "2026-03-22T09:00:00Z", "2026-03-22T10:00:00Z")
    assert get_establishment(est["id"])["sealed_device_count"] == 1


def test_sealed_count_returns_to_zero_after_condemn():
    """PRD §2.8: "The `sealed_device_count` of an establishment is the number of that
    establishment's devices whose `status` is currently `SEALED`. It is recomputed on
    every device transition into or out of `SEALED` — whether from a passing inspection
    that seals a device, a failing re-test or retirement that voids a seal, or the
    suspension cascade described in §3.1."
    PRD §3.7: "If the device was `SEALED` before this fail, its `ACTIVE` seal is moved to
    `VOIDED` and the establishment's `sealed_device_count` decreases by one."

    Design: Difficulty/compensating_invariant/sealed_count_conserved_seal_then_condemn
    """
    est, inspector = bootstrap_est_inspector(est_name="Inv2 Store", jurisdiction="CA-18")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-INV2",
                          device_class="CLASS_III")
    accuracy_pass_seal(inspector, dev, "2026-03-22T09:00:00Z", "2026-03-22T10:00:00Z")
    assert get_establishment(est["id"])["sealed_device_count"] == 1
    # A failing maintenance re-test (error 8 > maintenance tol 6) condemns the sealed device.
    ins = in_progress_accuracy(inspector, dev, "2026-03-23T09:00:00Z", "2026-03-23T10:00:00Z",
                               applied_load=3000, indicated_value=3008)
    finalize_inspection(ins["id"], inspector["id"])
    assert get_device(dev["id"])["status"] == "CONDEMNED"
    assert get_establishment(est["id"])["sealed_device_count"] == 0


# --------------------------------------------------------------------------- #
# Corner/validations/suspend_zero_balance_returns_requires_balance
# --------------------------------------------------------------------------- #
def test_suspend_establishment_with_zero_balance_returns_requires_balance():
    """PRD §3.1: "suspension is permitted only when the establishment's
    `balance_due_cents` is greater than 0. An attempt to suspend an establishment that
    owes nothing is rejected with `ERR_SUSPEND_REQUIRES_BALANCE`."

    Design: Corner/validations/suspend_zero_balance_returns_requires_balance
    """
    est = create_establishment(name="ZeroBal Store", jurisdiction="CA-35")
    resp = api_client.suspend_establishment(est["id"], ADMIN, {"reason": "test"})
    validate_error(resp, ApiErrorId.ERR_SUSPEND_REQUIRES_BALANCE.value)


# --------------------------------------------------------------------------- #
# Corner/validations/reinstate_with_balance_returns_outstanding
# --------------------------------------------------------------------------- #
def test_reinstate_establishment_with_balance_returns_outstanding():
    """PRD §3.1: "reinstatement requires `balance_due_cents` to be exactly 0, and a
    reinstatement attempted while any balance remains is rejected with
    `ERR_OUTSTANDING_BALANCE`."

    Design: Corner/validations/reinstate_with_balance_returns_outstanding
    """
    est = create_establishment(name="Reinst Store", jurisdiction="CA-36")
    register_device(est["id"], device_type="SCALE", serial_number="SN-RE")  # 12000 DUE fee
    validate_success(api_client.suspend_establishment(est["id"], ADMIN, {"reason": "nonpayment"}), 200)
    resp = api_client.reinstate_establishment(est["id"], ADMIN, {})
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE.value)
