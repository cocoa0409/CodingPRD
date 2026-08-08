"""Cross-entity gates on EM activation and release ordering, the state-before-fiscal
precedence, device-unit conservation, and the pure no-device path.

Translates SCAFFOLD_DIFFICULTY_DESIGN.yaml rules cross_entity_state_dependency.*,
priority_pair_validation_conflict.em_activate_state_beats_fiscal, and
compensating_invariant.device_assign_return_conserves_units; and
SCAFFOLD_CORNER_DESIGN.yaml endpoints.em_activate_no_device_returns_no_device_available.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_defendant, create_device, create_pending_enrollment,
    create_submitted_assessment, create_release_order_payload, activate_defendant,
)

SUPERVISING = TEST_USERS["supervising_headers"]
JUDICIAL = TEST_USERS["judicial_headers"]


# ─── cross_entity_state_dependency / em_activate_requires_defendant_active ──

def test_activate_enrollment_pretrial_defendant_rejected(api):
    """PRD §3.5: "the enrollment's defendant must be in `supervision_status` `ACTIVE`
    (otherwise `ERR_DEFENDANT_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/em_activate_requires_defendant_active
    """
    d = create_defendant()  # PRETRIAL_PENDING
    dev = create_device(total_units=1)
    enr = create_pending_enrollment(d["id"], dev["id"])
    resp = api.transition_em_enrollment(enr["id"], "ACTIVE", SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_DEFENDANT_NOT_ACTIVE, 409)


def test_activate_rejected_leaves_enrollment_pending(api):
    """PRD §3.5: "the enrollment's defendant must be in `supervision_status` `ACTIVE`
    (otherwise `ERR_DEFENDANT_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/em_activate_requires_defendant_active
    """
    d = create_defendant()
    dev = create_device(total_units=1)
    enr = create_pending_enrollment(d["id"], dev["id"])
    api.transition_em_enrollment(enr["id"], "ACTIVE", SUPERVISING)
    fresh = validate_success(api.get_em_enrollment(enr["id"], SUPERVISING), 200)
    assert fresh["status"] == "PENDING", "rejected activation must not change status"


# ─── cross_entity_state_dependency / release_order_requires_assessment_approved ──

def test_order_release_with_submitted_assessment_rejected(api):
    """PRD §3.3: "**Ordering** (`PROPOSED → ORDERED`) requires the order to be in `PROPOSED`
    and requires the linked risk assessment to be in `APPROVED` status; if the linked
    assessment is not approved, the transition is rejected with `ERR_ASSESSMENT_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/release_order_requires_assessment_approved
    """
    d = create_defendant()
    a = create_submitted_assessment(d["id"])
    order = validate_success(api.create_release_order(
        create_release_order_payload(d["id"], a["id"], decision="RELEASE",
                                     ordered_conditions=["CHECK_IN"]), JUDICIAL), 201)
    resp = api.transition_release_order(order["id"], "ORDERED", JUDICIAL)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED, 409)


def test_order_rejected_leaves_order_proposed_and_defendant_pending(api):
    """PRD §3.3: "if the linked assessment is not approved, the transition is rejected with
    `ERR_ASSESSMENT_NOT_APPROVED`." (a rejected ordering activates nothing).

    Design: Difficulty/cross_entity_state_dependency/release_order_requires_assessment_approved
    """
    d = create_defendant()
    a = create_submitted_assessment(d["id"])
    order = validate_success(api.create_release_order(
        create_release_order_payload(d["id"], a["id"], decision="RELEASE",
                                     ordered_conditions=["CHECK_IN"]), JUDICIAL), 201)
    api.transition_release_order(order["id"], "ORDERED", JUDICIAL)
    fresh_def = validate_success(api.get_defendant(d["id"], JUDICIAL), 200)
    assert fresh_def["supervision_status"] == "PRETRIAL_PENDING"


# ─── priority_pair_validation_conflict / em_activate_state_beats_fiscal ────

def test_state_error_beats_fiscal_error_on_activation(api):
    """PRD §2.10: validation priority "5. Defendant-active gate (EM activation only) ...
    `ERR_DEFENDANT_NOT_ACTIVE` (409)." precedes "12. Device availability (EM activation) ...
    `ERR_NO_DEVICE_AVAILABLE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/em_activate_state_beats_fiscal
    """
    d = create_defendant()  # PRETRIAL_PENDING
    dev = create_device(total_units=0)  # exhausted pool
    enr = create_pending_enrollment(d["id"], dev["id"])
    resp = api.transition_em_enrollment(enr["id"], "ACTIVE", SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_DEFENDANT_NOT_ACTIVE, 409)


def test_state_error_not_masked_by_fiscal_error(api):
    """PRD §2.10: "the first failing check determines the error returned" — with the
    defendant-active gate (priority 5) before device availability (priority 12), the state
    error is returned, not `ERR_NO_DEVICE_AVAILABLE`.

    Design: Difficulty/priority_pair_validation_conflict/em_activate_state_beats_fiscal
    """
    d = create_defendant()
    dev = create_device(total_units=0)
    enr = create_pending_enrollment(d["id"], dev["id"])
    err = api.transition_em_enrollment(enr["id"], "ACTIVE", SUPERVISING).json()["data"]["error_id"]
    assert err == "ERR_DEFENDANT_NOT_ACTIVE"
    assert err != "ERR_NO_DEVICE_AVAILABLE"


# ─── compensating_invariant / device_assign_return_conserves_units ─────────

def test_activation_consumes_one_unit(api):
    """PRD §2.11: "Activating an enrollment consumes one unit ... An activate paired with its
    later terminate therefore leaves `available_units` unchanged."

    Design: Difficulty/compensating_invariant/device_assign_return_conserves_units
    """
    ctx = activate_defendant(ordered_conditions=["GPS_MONITORING"])
    dev = create_device(total_units=1)
    enr = create_pending_enrollment(ctx["defendant"]["id"], dev["id"])
    validate_success(api.transition_em_enrollment(enr["id"], "ACTIVE", SUPERVISING), 200)
    fresh_dev = validate_success(api.get_em_device(dev["id"], SUPERVISING), 200)
    assert fresh_dev["available_units"] == 0


def test_termination_returns_the_unit(api):
    """PRD §2.11: "terminating an active or suspended enrollment returns one unit ... An
    activate paired with its later terminate therefore leaves `available_units` unchanged."

    Design: Difficulty/compensating_invariant/device_assign_return_conserves_units
    """
    ctx = activate_defendant(ordered_conditions=["GPS_MONITORING"])
    dev = create_device(total_units=1)
    enr = create_pending_enrollment(ctx["defendant"]["id"], dev["id"])
    validate_success(api.transition_em_enrollment(enr["id"], "ACTIVE", SUPERVISING), 200)
    validate_success(api.transition_em_enrollment(enr["id"], "TERMINATED", SUPERVISING), 200)
    fresh_dev = validate_success(api.get_em_device(dev["id"], SUPERVISING), 200)
    assert fresh_dev["available_units"] == 1, "terminate returns the unit to total_units"


# ─── Corner: endpoints.em_activate_no_device_returns_no_device_available ───

def test_activate_on_exhausted_pool_returns_no_device_available(api):
    """PRD §3.5: "the referenced device pool must have at least one free unit, meaning
    `available_units` of 1 or more (otherwise `ERR_NO_DEVICE_AVAILABLE`)."

    Design: Corner/endpoints/em_activate_no_device_returns_no_device_available
    """
    ctx = activate_defendant(ordered_conditions=["GPS_MONITORING"])
    dev = create_device(total_units=0)
    enr = create_pending_enrollment(ctx["defendant"]["id"], dev["id"])
    resp = api.transition_em_enrollment(enr["id"], "ACTIVE", SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_NO_DEVICE_AVAILABLE, 409)
