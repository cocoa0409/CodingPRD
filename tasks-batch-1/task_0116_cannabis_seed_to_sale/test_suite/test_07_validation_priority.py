"""Validation-priority conflicts: when two checks could both fire, the PRD's
fixed evaluation order determines the single returned error."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_cultivation_license, create_testing_license,
    create_active_package, create_flowering_batch, create_batch,
    create_cured_harvest, create_package, record_lab_result,
    cult_h, cm_h,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Rule 5: state (priority 4) beats license-active (priority 5) on advance
# ---------------------------------------------------------------------------
def test_advance_harvested_batch_under_suspended_license_reports_invalid_state(api):
    """PRD §2.11: "State checks come next: the target resource must be in a legal
    state for the requested transition (`ERR_INVALID_STATE`)"
    PRD §2.11: "After state come the business-safety checks, in this order:
    license-active (`ERR_LICENSE_NOT_ACTIVE`), license-type"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_license_active_on_advance
    """
    cul = create_cultivation_license()
    batch = create_flowering_batch(cul["id"])
    # Harvest flips the batch to HARVESTED (no outgoing advance transition).
    api.create_harvest({
        "plant_batch_id": batch["id"], "harvest_name": "H-I", "wet_weight_grams": 1000,
    }, cult_h())
    # Suspend the owning license so BOTH the state and license checks would fail.
    from test_helpers import reg_h
    validate_success(api.suspend_license(cul["id"], reg_h()))
    resp = api.advance_plant_batch(batch["id"], cult_h())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_advance_harvested_batch_under_suspended_license_not_license_error(api):
    """PRD §2.11: "The guiding intent is that a higher-tier violation surfaces
    its own error rather than being masked by a lower-tier check."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_license_active_on_advance
    """
    cul = create_cultivation_license()
    batch = create_flowering_batch(cul["id"])
    api.create_harvest({
        "plant_batch_id": batch["id"], "harvest_name": "H-I2", "wet_weight_grams": 1000,
    }, cult_h())
    from test_helpers import reg_h
    validate_success(api.suspend_license(cul["id"], reg_h()))
    resp = api.advance_plant_batch(batch["id"], cult_h())
    # Must be the state error, NOT the license-active error.
    body = resp.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value, (
        f"state (priority 4) must beat license-active (priority 5); "
        f"got {body['data'].get('error_id')!r}"
    )


# ---------------------------------------------------------------------------
# Rule 5: state (priority 4) beats segregation-of-duties (priority 7) on clear-hold
# ---------------------------------------------------------------------------
def test_clear_hold_on_active_package_reports_invalid_state(api):
    """PRD §2.11: "State checks come next: the target resource must be in a legal
    state for the requested transition (`ERR_INVALID_STATE`)"
    PRD §2.11: "After state come the business-safety checks, in this order:
    license-active (`ERR_LICENSE_NOT_ACTIVE`), license-type
    (`ERR_LICENSE_TYPE_MISMATCH`), segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`)"

    Design: Difficulty/priority_pair_validation_conflict/sod_vs_state_on_clear_hold
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    # ACTIVE package that was never put ON_HOLD => clear-hold is an illegal state.
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=100)
    resp = api.clear_hold(pkg["id"], cm_h("cm-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_clear_hold_on_active_package_not_sod_error(api):
    """PRD §2.11: "The guiding intent is that a higher-tier violation surfaces
    its own error rather than being masked by a lower-tier check."

    Design: Difficulty/priority_pair_validation_conflict/sod_vs_state_on_clear_hold
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=100)
    resp = api.clear_hold(pkg["id"], cm_h("cm-1"))
    body = resp.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value, (
        f"state (priority 4) must beat SoD (priority 7); "
        f"got {body['data'].get('error_id')!r}"
    )


# ---------------------------------------------------------------------------
# Rule 7 (cross_entity_state_dependency): advance requires owning license ACTIVE
# ---------------------------------------------------------------------------
def test_advance_immature_batch_under_suspended_license_rejected(api):
    """PRD §2.7: "The operating or owning license must be in `ACTIVE` status for
    the following operations: advancing a plant batch's growth stage"
    PRD §2.7: "If the governing license is `SUSPENDED` or `REVOKED` when one of
    these operations is attempted, it is rejected with `ERR_LICENSE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/plant_batch_advance_requires_license_active
    """
    from test_helpers import reg_h
    cul = create_cultivation_license()
    batch = create_batch(cul["id"], plant_count=10)  # IMMATURE — a valid advance state
    validate_success(api.suspend_license(cul["id"], reg_h()))
    resp = api.advance_plant_batch(batch["id"], cult_h())
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value)


def test_advance_under_suspended_license_keeps_batch_immature(api):
    """PRD §3.2: "Each advance is permitted only when the batch is currently in
    the originating stage, the owning license is `ACTIVE`, and the batch still
    has at least one live plant (`live_plant_count` of 1 or more)"

    Design: Difficulty/cross_entity_state_dependency/plant_batch_advance_requires_license_active
    """
    from test_helpers import reg_h
    cul = create_cultivation_license()
    batch = create_batch(cul["id"], plant_count=10)
    validate_success(api.suspend_license(cul["id"], reg_h()))
    api.advance_plant_batch(batch["id"], cult_h())
    after = validate_success(api.get_plant_batch(batch["id"], cult_h()))
    assert after["status"] == "IMMATURE", "batch must remain IMMATURE after rejected advance"


# ---------------------------------------------------------------------------
# Corner: partial FAILED_TEST destroy is not terminal
# ---------------------------------------------------------------------------
def test_partial_failed_test_destroy_rejected(api):
    """PRD §3.5: "A partial destroy on a `FAILED` package does not terminalize it
    and is rejected with `ERR_PARTIAL_DESTROY_NOT_TERMINAL`."

    Design: Corner/validations/partial_failed_test_destroy_not_terminal
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    harvest = create_cured_harvest(cul["id"], wet_weight_grams=1500, dry_weight_grams=1000)
    pkg = create_package(harvest["id"], quantity_grams=600)
    record_lab_result(pkg["id"], lab["id"], pesticide_pass=False)
    resp = api.create_waste_event({
        "source_type": "PACKAGE", "package_id": pkg["id"], "reason": "FAILED_TEST",
        "destroyed_grams": 300, "destroyed_at": "2026-06-17T00:00:00Z",
    }, cm_h("cm-1"))
    validate_error(resp, ApiErrorId.ERR_PARTIAL_DESTROY_NOT_TERMINAL.value)
    after = validate_success(api.get_package(pkg["id"], cult_h()))
    assert after["status"] == "FAILED", "package must stay FAILED after a partial destroy"
