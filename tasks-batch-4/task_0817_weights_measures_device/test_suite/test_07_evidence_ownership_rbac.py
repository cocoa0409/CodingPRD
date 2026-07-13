"""Finalize evidence guards, ownership, and role-based access control.

Covers corner validation instances finalize_accuracy_no_readings,
finalize_price_no_items, retire_with_in_progress, pay_penalty_wrong_establishment;
and rbac instances inspector_cannot_register_device,
establishment_cannot_finalize_inspection.
"""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    bootstrap_est_inspector, register_device, create_establishment,
    schedule_inspection, start_inspection, in_progress_accuracy,
    accuracy_fail_condemn, first_penalty_for_device,
    make_inspector_headers, make_establishment_headers,
    api_client,
)


# --------------------------------------------------------------------------- #
# Corner/validations/finalize_accuracy_no_readings_returns_no_readings
# --------------------------------------------------------------------------- #
def test_finalize_accuracy_with_no_readings_returns_no_readings():
    """PRD §3.7: "an `ACCURACY_TEST` or `COMPLAINT_RETEST` must have at least one
    recorded test reading, and finalizing one with none is rejected with
    `ERR_NO_READINGS`; a `PRICE_VERIFICATION` must have at least one recorded audit item,
    and finalizing one with none is rejected with `ERR_INSUFFICIENT_SAMPLE`."

    Design: Corner/validations/finalize_accuracy_no_readings_returns_no_readings
    """
    est, inspector = bootstrap_est_inspector(est_name="NoRd Store", jurisdiction="CA-37")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-NORD",
                          device_class="CLASS_III")
    ins = schedule_inspection(dev["id"], inspector["id"],
                              "2026-03-30T09:00:00Z", "2026-03-30T10:00:00Z")
    start_inspection(ins["id"], inspector["id"])
    resp = api_client.finalize_inspection(ins["id"], make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_READINGS.value)


# --------------------------------------------------------------------------- #
# Corner/validations/finalize_price_no_items_returns_insufficient_sample
# --------------------------------------------------------------------------- #
def test_finalize_price_verification_with_no_items_returns_insufficient_sample():
    """PRD §3.7: "an `ACCURACY_TEST` or `COMPLAINT_RETEST` must have at least one
    recorded test reading, and finalizing one with none is rejected with
    `ERR_NO_READINGS`; a `PRICE_VERIFICATION` must have at least one recorded audit item,
    and finalizing one with none is rejected with `ERR_INSUFFICIENT_SAMPLE`."

    Design: Corner/validations/finalize_price_no_items_returns_insufficient_sample
    """
    est, inspector = bootstrap_est_inspector(est_name="NoIt Store", jurisdiction="CA-38")
    dev = register_device(est["id"], device_type="SCANNER", serial_number="SN-NOIT")
    ins = schedule_inspection(dev["id"], inspector["id"],
                              "2026-03-31T09:00:00Z", "2026-03-31T10:00:00Z",
                              inspection_type="PRICE_VERIFICATION")
    start_inspection(ins["id"], inspector["id"])
    resp = api_client.finalize_inspection(ins["id"], make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SAMPLE.value)


# --------------------------------------------------------------------------- #
# Corner/validations/retire_with_in_progress_returns_active_inspection
# --------------------------------------------------------------------------- #
def test_retire_device_with_in_progress_inspection_returns_active_inspection():
    """PRD §3.8: "Retirement is blocked while the device has an inspection that is
    `IN_PROGRESS`: such an attempt is rejected with `ERR_DEVICE_HAS_ACTIVE_INSPECTION`."

    Design: Corner/validations/retire_with_in_progress_returns_active_inspection
    """
    est, inspector = bootstrap_est_inspector(est_name="Act Store", jurisdiction="CA-39")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-ACT",
                          device_class="CLASS_III")
    ins = schedule_inspection(dev["id"], inspector["id"],
                              "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z")
    start_inspection(ins["id"], inspector["id"])  # -> IN_PROGRESS
    # Retire is ProgramAdmin-only; the design targets the state guard, so call as ProgramAdmin.
    resp = api_client.retire_device(dev["id"], TEST_USERS["program_admin_headers"], {"reason": "premature"})
    validate_error(resp, ApiErrorId.ERR_DEVICE_HAS_ACTIVE_INSPECTION.value)


# --------------------------------------------------------------------------- #
# Corner/validations/pay_penalty_wrong_establishment_returns_ownership
# --------------------------------------------------------------------------- #
def test_paying_another_establishments_penalty_returns_ownership_violation():
    """PRD §2.1: "an establishment may pay only its own penalties and its own fee
    invoices; an attempt to pay a penalty or invoice belonging to another establishment
    is rejected with `ERR_OWNERSHIP_VIOLATION`."

    Design: Corner/validations/pay_penalty_wrong_establishment_returns_ownership
    """
    est1, inspector = bootstrap_est_inspector(est_name="Own1 Store", jurisdiction="CA-40")
    est2 = create_establishment(name="Own2 Store", jurisdiction="CA-41")
    dev = register_device(est1["id"], device_type="SCALE", serial_number="SN-OWN",
                          device_class="CLASS_III")
    accuracy_fail_condemn(inspector, dev, "2026-04-03T09:00:00Z", "2026-04-03T10:00:00Z",
                          applied_load=3000, indicated_value=3004)
    penalty = first_penalty_for_device(dev["id"])
    resp = api_client.pay_penalty(penalty["id"], make_establishment_headers(est2["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value)


# --------------------------------------------------------------------------- #
# Corner/rbac/inspector_cannot_register_device_returns_unauthorized
# --------------------------------------------------------------------------- #
def test_inspector_registering_device_returns_unauthorized():
    """PRD §2.1: "When the headers are valid but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/inspector_cannot_register_device_returns_unauthorized
    """
    est, inspector = bootstrap_est_inspector(est_name="Rbac1 Store", jurisdiction="CA-42")
    resp = api_client.create_device(
        {"establishment_id": est["id"], "device_type": "SCALE", "serial_number": "SN-RBAC1"},
        make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# --------------------------------------------------------------------------- #
# Corner/rbac/establishment_cannot_finalize_inspection_returns_unauthorized
# --------------------------------------------------------------------------- #
def test_establishment_finalizing_inspection_returns_unauthorized():
    """PRD §2.1: "When the headers are valid but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/establishment_cannot_finalize_inspection_returns_unauthorized
    """
    est, inspector = bootstrap_est_inspector(est_name="Rbac2 Store", jurisdiction="CA-43")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-RBAC2",
                          device_class="CLASS_III")
    ins = in_progress_accuracy(inspector, dev, "2026-04-04T09:00:00Z", "2026-04-04T10:00:00Z",
                               applied_load=3000, indicated_value=3000)
    resp = api_client.finalize_inspection(ins["id"], make_establishment_headers(est["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
