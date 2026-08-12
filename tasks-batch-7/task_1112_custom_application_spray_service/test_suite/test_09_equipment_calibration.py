"""Calibration verdicts, equipment status machine, the FAIL cascade, and
registry RBAC denials."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_customer, create_field, create_product, create_prescription,
    create_applicator, create_equipment, post_calibration, create_work_order,
    create_product_payload, schedule_work_order_payload,
    must_schedule, set_clock, base_environment,
    make_grower_headers, make_applicator_headers,
    CALIBRATION_VALID_UNTIL_DEFAULT, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
AGRONOMIST = TEST_USERS["agronomist_headers"]


def test_calibration_error_exactly_5_pct_passes(api):
    """PRD §3.3: "The `verdict` is `PASS` when `error_pct` is at most 5.0 —
    exactly 5.0 passes — and `FAIL` otherwise."
    PRD §3.3: "On a `PASS`, the equipment's `calibration_valid_until` becomes
    `performed_at` plus 180 days and the equipment is `AVAILABLE`"

    Design: Difficulty/boundary_precision_check/calibration_error_exactly_5_pct_passes
    """
    ap = create_applicator(license_categories=["HERBICIDE"])
    eq = create_equipment(unit_label="Sprayer-A")

    # |21.0 - 20.0| / 20.0 * 100 = 5.0 exactly -> PASS (boundary inclusive).
    record = post_calibration(eq["id"], ap["id"], target_gpa=20.0, measured_gpa=21.0)
    assert record["error_pct"] == 5.0
    assert record["verdict"] == "PASS"

    equipment = get_success_data(api.get_equipment(eq["id"], ADMIN))
    assert equipment["status"] == "AVAILABLE"
    # performed at the boot clock 2026-05-01T00:00:00Z + 180 days.
    assert equipment["calibration_valid_until"] == CALIBRATION_VALID_UNTIL_DEFAULT, \
        f"expected {CALIBRATION_VALID_UNTIL_DEFAULT}, got {equipment['calibration_valid_until']}"


def test_calibration_error_5_5_pct_fails(api):
    """PRD §3.3: "The `verdict` is `PASS` when `error_pct` is at most 5.0 —
    exactly 5.0 passes — and `FAIL` otherwise."
    PRD §3.3: "On a `FAIL`, the equipment drops to `CALIBRATION_DUE` and
    `calibration_valid_until` is left unchanged"

    Design: Difficulty/boundary_precision_check/calibration_error_exactly_5_pct_passes
    """
    ap = create_applicator(license_categories=["HERBICIDE"])
    eq = create_equipment(unit_label="Sprayer-B")

    # |21.1 - 20.0| / 20.0 * 100 = 5.5 -> FAIL.
    record = post_calibration(eq["id"], ap["id"], target_gpa=20.0, measured_gpa=21.1)
    assert record["error_pct"] == 5.5
    assert record["verdict"] == "FAIL"

    equipment = get_success_data(api.get_equipment(eq["id"], ADMIN))
    assert equipment["status"] == "CALIBRATION_DUE"
    assert equipment["calibration_valid_until"] is None, \
        "a FAIL never extends the (still null) validity horizon"


def test_failed_calibration_cascade_reverts_scheduled_work(api):
    """PRD §3.3: "The failure then cascades: every `SCHEDULED` work order
    naming that sprayer reverts to `DRAFT` with its assignment cleared, as §2.8
    describes."
    PRD §2.8: "reverting each of its `SCHEDULED` work orders to `DRAFT`,
    clearing `applicator_id`, `equipment_id`, `scheduled_start`, and
    `scheduled_end`, resetting `uses_adjuvant` to false, and nulling
    `estimated_total_cents`."
    PRD §3.3: "On a `FAIL`, the equipment drops to `CALIBRATION_DUE` and
    `calibration_valid_until` is left unchanged — a failure never shortens or
    extends the prior validity."

    Design: Difficulty/transitive_cascade/failed_calibration_cascade
    """
    env = base_environment()  # PASS at boot clock -> valid until 2026-10-28
    must_schedule(env["work_order"]["id"], env["applicator"]["id"],
                  env["equipment"]["id"])

    # |22.0 - 20.0| / 20.0 * 100 = 10.0 -> FAIL.
    record = post_calibration(env["equipment"]["id"], env["applicator"]["id"],
                              target_gpa=20.0, measured_gpa=22.0)
    assert record["verdict"] == "FAIL" and record["error_pct"] == 10.0

    equipment = get_success_data(api.get_equipment(env["equipment"]["id"], ADMIN))
    assert equipment["status"] == "CALIBRATION_DUE"
    assert equipment["calibration_valid_until"] == CALIBRATION_VALID_UNTIL_DEFAULT, \
        "FAIL leaves the prior PASS validity untouched"

    wo = get_success_data(api.get_work_order(env["work_order"]["id"], DISPATCHER))
    assert wo["status"] == "DRAFT"
    assert wo["applicator_id"] is None and wo["equipment_id"] is None
    assert wo["scheduled_start"] is None and wo["scheduled_end"] is None
    assert wo["estimated_total_cents"] is None


def test_fail_cascade_then_pass_restores_and_reschedule(api):
    """PRD §3.3: "A `PASS` also lifts a `CALIBRATION_DUE` unit back to
    `AVAILABLE`."
    PRD §3.4: "When the gauntlet passes, the schedule writes `applicator_id`,
    `equipment_id`, `scheduled_start`, `scheduled_end`, and `uses_adjuvant`
    onto the order"

    Design: Difficulty/transitive_cascade/failed_calibration_cascade
    """
    env = base_environment()
    must_schedule(env["work_order"]["id"], env["applicator"]["id"],
                  env["equipment"]["id"])
    post_calibration(env["equipment"]["id"], env["applicator"]["id"],
                     target_gpa=20.0, measured_gpa=22.0)  # FAIL -> cascade to DRAFT
    wo = get_success_data(api.get_work_order(env["work_order"]["id"], DISPATCHER))
    assert wo["status"] == "DRAFT"

    post_calibration(env["equipment"]["id"], env["applicator"]["id"],
                     target_gpa=20.0, measured_gpa=20.4)  # PASS -> AVAILABLE again
    equipment = get_success_data(api.get_equipment(env["equipment"]["id"], ADMIN))
    assert equipment["status"] == "AVAILABLE"

    rescheduled = must_schedule(env["work_order"]["id"], env["applicator"]["id"],
                                env["equipment"]["id"])
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["equipment_id"] == env["equipment"]["id"]


def test_pass_calibration_restores_equipment(api):
    """PRD §3.3: "A `PASS` also lifts a `CALIBRATION_DUE` unit back to
    `AVAILABLE`."
    PRD §3.3: "On a `PASS`, the equipment's `calibration_valid_until` becomes
    `performed_at` plus 180 days and the equipment is `AVAILABLE`"

    Design: Corner/state_machines/pass_calibration_restores_equipment
    """
    ap = create_applicator(license_categories=["HERBICIDE"])
    eq = create_equipment()

    post_calibration(eq["id"], ap["id"], target_gpa=20.0, measured_gpa=20.5)   # PASS
    fail = post_calibration(eq["id"], ap["id"], target_gpa=20.0, measured_gpa=22.0)
    assert fail["verdict"] == "FAIL"
    equipment = get_success_data(api.get_equipment(eq["id"], ADMIN))
    assert equipment["status"] == "CALIBRATION_DUE"

    set_clock("2026-06-01T00:00:00Z")
    # |20.4 - 20.0| / 20.0 * 100 = 2.0 -> PASS, restoring the unit.
    recovery = post_calibration(eq["id"], ap["id"], target_gpa=20.0, measured_gpa=20.4)
    assert recovery["verdict"] == "PASS" and recovery["error_pct"] == 2.0

    equipment = get_success_data(api.get_equipment(eq["id"], ADMIN))
    assert equipment["status"] == "AVAILABLE"
    # performed at 2026-06-01T00:00:00Z + 180 days.
    assert equipment["calibration_valid_until"] == "2026-11-28T00:00:00.000Z", \
        f"expected 2026-11-28T00:00:00.000Z, got {equipment['calibration_valid_until']}"


def test_grower_cannot_create_products(api):
    """PRD §2.1: "a caller whose role is not authorized for an endpoint — or
    who fails an ownership or assignment check on the target — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /api/products is authorized for CoopAdmin only.

    Design: Corner/rbac/grower_cannot_create_products
    """
    customer = create_customer(name="Solo Farm", billing_email="s@farm.test",
                               rate_per_acre_cents=900, credit_limit_cents=500000)
    res = api.create_product(
        create_product_payload(name="Bootleg", epa_registration_no="EPA-X",
                               required_buffer_ft=0, unit_cost_cents=1000),
        make_grower_headers(customer["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_grower_cannot_schedule_work_order(api):
    """PRD §2.1: "a caller whose role is not authorized for an endpoint — or
    who fails an ownership or assignment check on the target — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /api/work-orders/{id}/schedule is authorized for Dispatcher
    only.

    Design: Corner/rbac/grower_cannot_schedule_work_order
    """
    customer = create_customer(name="Solo Farm", billing_email="s@farm.test",
                               rate_per_acre_cents=900, credit_limit_cents=500000)
    field = create_field(customer["id"], label="F")
    product = create_product()
    rx = create_prescription(field["id"], [{"product_id": product["id"], "rate_per_acre": 1.5}])
    ap = create_applicator(license_categories=["HERBICIDE"])
    eq = create_equipment()
    wo = create_work_order(customer["id"], field["id"], rx["id"], acres_to_treat=100)

    # Even the owning Grower is rejected: scheduling is Dispatcher-only.
    res = api.schedule_work_order(
        wo["id"],
        schedule_work_order_payload(ap["id"], eq["id"]),
        make_grower_headers(customer["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
