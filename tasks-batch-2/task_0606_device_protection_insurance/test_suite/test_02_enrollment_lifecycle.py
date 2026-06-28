"""Enrollment state machine: activation, suspend/reactivate revert loop, cancel cascade,
IMEI uniqueness, premium-invoice cycle uniqueness.

Covers difficulty rules non_linear_state_machine (revert loop), resource_temporal_overlap,
compensating_invariant (cancel voids invoices), and corner state_machine instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, IMEI_A,
)
from test_helpers import fixtures as fx


# --------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / enrollment_suspend_reactivate_revert_loop
# --------------------------------------------------------------------------
def test_enrollment_suspend_then_reactivate_returns_to_active(api, admin_headers):
    """PRD 3.2: "A `PlatformAdmin` may suspend an `ACTIVE` enrollment, moving it to
    `SUSPENDED` ... the status becomes `SUSPENDED`".
    PRD 3.2: "Reinstatement is the revert loop: a `PlatformAdmin` activates a
    `SUSPENDED` enrollment back to `ACTIVE`. This is permitted only when
    `premium_paid_through_cycle` covers the current cycle ... On success the status
    returns to `ACTIVE`".

    Design: Difficulty/non_linear_state_machine/enrollment_suspend_reactivate_revert_loop
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-6")
    enr = base["enrollment"]
    fx.pay_through_current_cycle(enr)
    suspended = validate_success(api.suspend_enrollment(enr["id"], admin_headers))
    assert suspended["status"] == "SUSPENDED"
    reactivated = validate_success(api.activate_enrollment(enr["id"], admin_headers))
    assert reactivated["status"] == "ACTIVE", \
        f"expected ACTIVE after reactivate, got {reactivated['status']}"


def test_enrollment_revert_loop_versions_increment(api, admin_headers):
    """PRD 3.2: "the status becomes `SUSPENDED` and `version` increments by one."
    PRD 3.2: "On success the status returns to `ACTIVE` and `version` increments by one."

    Design: Difficulty/non_linear_state_machine/enrollment_suspend_reactivate_revert_loop
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-6B")
    enr = base["enrollment"]
    fx.pay_through_current_cycle(enr)
    before = fx.current_enrollment_version(enr["id"])
    suspended = validate_success(api.suspend_enrollment(enr["id"], admin_headers))
    assert suspended["version"] == before + 1
    reactivated = validate_success(api.activate_enrollment(enr["id"], admin_headers))
    assert reactivated["version"] == suspended["version"] + 1


# --------------------------------------------------------------------------
# Corner: state_machines
# --------------------------------------------------------------------------
def test_activate_already_active_enrollment_invalid_state(api, admin_headers):
    """PRD 3.2: "Any attempt to drive a state transition from a status where it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_enrollment_returns_invalid_state
    """
    base = fx.create_active_enrollment(carrier="CA-CN-6")
    resp = api.activate_enrollment(base["enrollment"]["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_cancel_enrollment_with_open_claim_invalid_state(api, admin_headers):
    """PRD 3.2: "Cancellation ... may be applied to an enrollment that is `ACTIVE` or
    `SUSPENDED`, and is permitted only when `open_claim_id` is null."
    PRD 3.2: "Any attempt to drive a state transition from a status where it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_enrollment_with_open_claim_returns_invalid_state
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-7")
    enr = base["enrollment"]
    fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    resp = api.cancel_enrollment(enr["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_enrollment(enr["id"], admin_headers))
    assert after["status"] == "ACTIVE", "status must stay ACTIVE after rejected cancel"


# --------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap
# --------------------------------------------------------------------------
def test_duplicate_imei_on_noncancelled_enrollment_rejected(api, admin_headers):
    """PRD 3.2: "The IMEI must also be unique across all enrollments that are not in
    `CANCELLED` status; a collision is rejected with `ERR_DUPLICATE_IMEI`."

    Design: Difficulty/resource_temporal_overlap/imei_unique_across_noncancelled_enrollments
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-15", imei=IMEI_A)
    resp = api.create_enrollment({
        "customer_id": base["customer"]["id"],
        "plan_id": base["plan"]["id"],
        "imei": IMEI_A,
        "device_model": "PhoneDup",
        "device_purchase_date": "2025-12-01T00:00:00Z",
        "replacement_sku_id": base["sku"]["id"],
    }, admin_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_IMEI.value, 409)


def test_duplicate_imei_via_corner_stub(api, admin_headers):
    """PRD 3.2: "The IMEI must also be unique across all enrollments that are not in
    `CANCELLED` status; a collision is rejected with `ERR_DUPLICATE_IMEI`."

    Design: Difficulty/resource_temporal_overlap/imei_unique_across_noncancelled_enrollments
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-15B", imei=IMEI_A)
    resp = api.create_enrollment({
        "customer_id": base["customer"]["id"],
        "plan_id": base["plan"]["id"],
        "imei": IMEI_A,
        "device_model": "PhoneDup2",
        "device_purchase_date": "2025-12-01T00:00:00Z",
        "replacement_sku_id": base["sku"]["id"],
    }, admin_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_IMEI.value, 409)


def test_distinct_cycle_invoices_coexist(api, admin_headers):
    """PRD 3.3: "A `PlatformAdmin` issues a premium invoice against an enrollment by
    supplying `enrollment_id` and a `cycle_index` (a zero-based billing-cycle index since
    activation, zero or more). At issue, the invoice's `amount_cents` is snapshotted from
    the plan's `monthly_premium_cents` ... and the invoice begins in `ISSUED` status."

    Design: Difficulty/resource_temporal_overlap/premium_invoice_cycle_uniqueness_per_enrollment
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-16B")
    enr = base["enrollment"]
    inv0 = fx.issue_invoice(enr["id"], 0)
    inv1 = validate_success(api.create_premium_invoice(
        {"enrollment_id": enr["id"], "cycle_index": 1}, admin_headers), 201)
    assert inv0["cycle_index"] == 0 and inv1["cycle_index"] == 1
    assert inv0["id"] != inv1["id"], "distinct cycles must produce distinct invoices"


# --------------------------------------------------------------------------
# Difficulty: compensating_invariant / cancel_enrollment_voids_premium_invoice_invariant
# --------------------------------------------------------------------------
def test_cancel_enrollment_voids_issued_invoices(api, admin_headers):
    """PRD 3.2: "Cancellation sets the status to `CANCELLED`, and cascades by voiding
    every premium invoice for this enrollment that is currently in `ISSUED` status
    (their status becomes `VOID`)".

    Design: Difficulty/compensating_invariant/cancel_enrollment_voids_premium_invoice_invariant
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-18")
    enr = base["enrollment"]
    inv = fx.issue_invoice(enr["id"], 0)
    assert validate_success(api.get_premium_invoice(inv["id"], admin_headers))["status"] == "ISSUED"
    cancelled = validate_success(api.cancel_enrollment(enr["id"], admin_headers))
    assert cancelled["status"] == "CANCELLED"
    after = validate_success(api.get_premium_invoice(inv["id"], admin_headers))
    assert after["status"] == "VOID", f"invoice must be VOID after cancel, got {after['status']}"


def test_cancel_enrollment_sets_cancelled_status(api, admin_headers):
    """PRD 3.2: "Cancellation sets the status to `CANCELLED`, and cascades by voiding
    every premium invoice for this enrollment that is currently in `ISSUED` status
    (their status becomes `VOID`); the enrollment's `version` increments by one."

    Design: Difficulty/compensating_invariant/cancel_enrollment_voids_premium_invoice_invariant
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-18B")
    enr = base["enrollment"]
    fx.issue_invoice(enr["id"], 0)
    before = fx.current_enrollment_version(enr["id"])
    cancelled = validate_success(api.cancel_enrollment(enr["id"], admin_headers))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["version"] == before + 1
