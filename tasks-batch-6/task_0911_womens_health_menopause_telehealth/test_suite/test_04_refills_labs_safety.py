"""Refill lifecycle, lab safety gate, and validation-priority conflicts.

Difficulty: refill_request_branch_approve_vs_deny, lab_abnormal_suspends_denies_notifies,
refill_approval_requires_lab_reviewed_normal, refill_approve_state_beats_safety,
refills_remaining_zero_boundary.
Corner: refill_reverse_of_unadjudicated_charge_voids_it.
"""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, get_success_data,
    setup_active_prescription, request_refill, add_fulfilled_refill, add_lab_order,
    make_provider_headers,
)


def _message_types(api, ctx):
    data, _ = _paginate(api.list_care_plan_messages(ctx["care_plan_id"], ctx["provider_headers"]))
    return [m["message_type"] for m in data]


def _paginate(resp):
    from test_helpers import validate_paginated
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Refill request branch: approve vs deny (difficulty)
# ---------------------------------------------------------------------------
def test_refill_approve_branch_transitions_to_approved(api):
    """PRD §3.6: "A provider approves a REQUESTED refill (REQUESTED → APPROVED).
    Approval requires the refill to be REQUESTED, else ERR_REFILL_INVALID_STATE
    (409); the parent prescription to be ACTIVE, else ERR_PRESCRIPTION_NOT_ACTIVE
    (409)."

    Design: Difficulty/non_linear_state_machine/refill_request_branch_approve_vs_deny
    """
    ctx = setup_active_prescription(api, rx_overrides={"total_refills_authorized": 5})
    refill = request_refill(api, ctx)
    data = validate_success(api.approve_refill(refill["id"], ctx["provider_headers"]))
    assert data["status"] == "APPROVED", f"expected APPROVED, got {data['status']}"


def test_refill_deny_branch_sets_reason_and_appends_notice(api):
    """PRD §3.6: "A provider may instead deny a REQUESTED refill (REQUESTED →
    DENIED), permitted only from REQUESTED, else ERR_REFILL_INVALID_STATE (409);
    an optional denial_reason may be supplied and is recorded on the refill, and
    the denial appends a system-authored DENIAL_NOTICE to the prescription's care
    plan."

    Design: Difficulty/non_linear_state_machine/refill_request_branch_approve_vs_deny
    """
    ctx = setup_active_prescription(api, rx_overrides={"total_refills_authorized": 5})
    refill = request_refill(api, ctx)
    data = validate_success(
        api.deny_refill(refill["id"], ctx["provider_headers"],
                        {"denial_reason": "duplicate request"}))
    assert data["status"] == "DENIED", f"expected DENIED, got {data['status']}"
    assert data["denial_reason"] == "duplicate request"
    assert "DENIAL_NOTICE" in _message_types(api, ctx), \
        "a DENIAL_NOTICE care-plan message must be appended on denial"


# ---------------------------------------------------------------------------
# Lab abnormal -> suspend -> deny -> notify (difficulty, depth-3 cascade)
# ---------------------------------------------------------------------------
def test_lab_abnormal_reviews_and_suspends_prescription(api):
    """PRD §3.5: "If the resolved result is ABNORMAL and the parent prescription
    is ACTIVE, the system cascades the prescription into suspension (ACTIVE →
    SUSPENDED), which in turn denies that prescription's REQUESTED refills and
    appends a DENIAL_NOTICE to the care plan for each."

    Design: Difficulty/transitive_cascade/lab_abnormal_suspends_denies_notifies
    """
    ctx = setup_active_prescription(api, rx_overrides={"hrt_type": "COMBINED",
                                                       "total_refills_authorized": 3})
    lab = add_lab_order(api, ctx, panel_type="HORMONE")
    request_refill(api, ctx)
    lab_after = validate_success(
        api.resolve_lab_order(lab["id"], {"result": "ABNORMAL"}, ctx["provider_headers"]))
    assert lab_after["status"] == "REVIEWED", f"expected REVIEWED, got {lab_after['status']}"
    rx_after = get_success_data(api.get_prescription(ctx["prescription"]["id"],
                                                     ctx["provider_headers"]))
    assert rx_after["status"] == "SUSPENDED", f"expected SUSPENDED, got {rx_after['status']}"


def test_lab_abnormal_denies_refill_and_notifies(api):
    """PRD §3.5: "the system cascades the prescription into suspension (ACTIVE →
    SUSPENDED), which in turn denies that prescription's REQUESTED refills and
    appends a DENIAL_NOTICE to the care plan for each."

    Design: Difficulty/transitive_cascade/lab_abnormal_suspends_denies_notifies
    """
    ctx = setup_active_prescription(api, rx_overrides={"hrt_type": "COMBINED",
                                                       "total_refills_authorized": 3})
    lab = add_lab_order(api, ctx, panel_type="HORMONE")
    refill = request_refill(api, ctx)
    validate_success(
        api.resolve_lab_order(lab["id"], {"result": "ABNORMAL"}, ctx["provider_headers"]))
    refill_after = get_success_data(api.get_refill(refill["id"], ctx["provider_headers"]))
    assert refill_after["status"] == "DENIED", f"expected DENIED, got {refill_after['status']}"
    assert "DENIAL_NOTICE" in _message_types(api, ctx), \
        "a DENIAL_NOTICE care-plan message must be appended"


# ---------------------------------------------------------------------------
# Refill approval requires REVIEWED-NORMAL lab (difficulty, cross-entity)
# ---------------------------------------------------------------------------
def test_refill_approve_blocked_while_lab_pending(api):
    """PRD §3.6: "and, when the prescription requires labs, a REVIEWED-NORMAL lab
    to exist, else ERR_LAB_REQUIRED_BEFORE_REFILL (409)."

    Design: Difficulty/cross_entity_state_dependency/refill_approval_requires_lab_reviewed_normal
    """
    ctx = setup_active_prescription(api, rx_overrides={
        "hrt_type": "COMBINED", "total_refills_authorized": 3,
        "lab_required_before_refill": True})
    add_lab_order(api, ctx, panel_type="LIPID")
    refill = request_refill(api, ctx)
    resp = api.approve_refill(refill["id"], ctx["provider_headers"])
    validate_error(resp, ApiErrorId.ERR_LAB_REQUIRED_BEFORE_REFILL)


def test_refill_approve_succeeds_after_lab_reviewed_normal(api):
    """PRD §3.5: "a refill may not be approved and a suspended prescription may
    not be reactivated until a REVIEWED lab with a NORMAL result exists for that
    prescription; the guard is ERR_LAB_REQUIRED_BEFORE_REFILL (409) in both
    cases."

    Design: Difficulty/cross_entity_state_dependency/refill_approval_requires_lab_reviewed_normal
    """
    ctx = setup_active_prescription(api, rx_overrides={
        "hrt_type": "COMBINED", "total_refills_authorized": 3,
        "lab_required_before_refill": True})
    lab = add_lab_order(api, ctx, panel_type="LIPID")
    refill = request_refill(api, ctx)
    validate_success(api.resolve_lab_order(lab["id"], {"result": "NORMAL"},
                                           ctx["provider_headers"]))
    data = validate_success(api.approve_refill(refill["id"], ctx["provider_headers"]))
    assert data["status"] == "APPROVED", f"expected APPROVED, got {data['status']}"


# ---------------------------------------------------------------------------
# Conflict A: prescription-active state check beats lab safety check (difficulty)
# ---------------------------------------------------------------------------
def _suspended_rx_with_requested_refill(api):
    ctx = setup_active_prescription(api, rx_overrides={
        "hrt_type": "COMBINED", "total_refills_authorized": 3,
        "lab_required_before_refill": True})
    validate_success(api.suspend_prescription(ctx["prescription"]["id"], ctx["provider_headers"]))
    refill = request_refill(api, ctx)
    return ctx, refill


def test_refill_approve_returns_state_error_over_lab(api):
    """PRD §2.10: "Conflict A (refill approval). The parent-prescription-must-be-
    ACTIVE state check (yielding ERR_PRESCRIPTION_NOT_ACTIVE, 409) is evaluated
    before the lab-required safety check (yielding ERR_LAB_REQUIRED_BEFORE_REFILL,
    409). If a refill is approved against a prescription that is both non-ACTIVE
    and missing its required normal lab, the response is
    ERR_PRESCRIPTION_NOT_ACTIVE."

    Design: Difficulty/priority_pair_validation_conflict/refill_approve_state_beats_safety
    """
    ctx, refill = _suspended_rx_with_requested_refill(api)
    resp = api.approve_refill(refill["id"], ctx["provider_headers"])
    validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_ACTIVE)


def test_refill_approve_masks_lab_required_error(api):
    """PRD §2.10: "If a refill is approved against a prescription that is both
    non-ACTIVE and missing its required normal lab, the response is
    ERR_PRESCRIPTION_NOT_ACTIVE."

    Design: Difficulty/priority_pair_validation_conflict/refill_approve_state_beats_safety
    """
    ctx, refill = _suspended_rx_with_requested_refill(api)
    resp = api.approve_refill(refill["id"], ctx["provider_headers"])
    body = resp.json()["data"]
    assert body["error_id"] != "ERR_LAB_REQUIRED_BEFORE_REFILL", \
        "the lower-priority lab-safety error must be masked by the state check"
    assert body["error_id"] == "ERR_PRESCRIPTION_NOT_ACTIVE"


# ---------------------------------------------------------------------------
# Refills-remaining zero boundary (difficulty)
# ---------------------------------------------------------------------------
def test_refills_remaining_reaches_zero_after_last_fill(api):
    """PRD §2.11: "For any prescription, refills_remaining plus the count of that
    prescription's refills currently in FULFILLED status always equals
    total_refills_authorized. Fulfilling a refill decrements refills_remaining by
    1 as the refill enters FULFILLED (net change zero)."

    Design: Difficulty/boundary_precision_check/refills_remaining_zero_boundary
    """
    ctx = setup_active_prescription(api, rx_overrides={
        "hrt_type": "VAGINAL_ESTROGEN", "total_refills_authorized": 1,
        "refill_price_cents": 9000})
    add_fulfilled_refill(api, ctx)
    rx_after = get_success_data(api.get_prescription(ctx["prescription"]["id"],
                                                     ctx["provider_headers"]))
    assert rx_after["refills_remaining"] == 0, \
        f"expected refills_remaining 0, got {rx_after['refills_remaining']}"


def test_refill_request_with_zero_remaining_rejected(api):
    """PRD §3.6: "A request is refused unless the prescription has at least one
    refill remaining — that is, refills_remaining is 1 or greater — otherwise
    ERR_NO_REFILLS_REMAINING (409)."

    Design: Difficulty/boundary_precision_check/refills_remaining_zero_boundary
    """
    ctx = setup_active_prescription(api, rx_overrides={
        "hrt_type": "VAGINAL_ESTROGEN", "total_refills_authorized": 1,
        "refill_price_cents": 9000})
    add_fulfilled_refill(api, ctx)
    resp = api.request_refill(ctx["prescription"]["id"], ctx["patient_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_REFILLS_REMAINING)


# ---------------------------------------------------------------------------
# Corner: reversing a fulfilled refill whose charge is still ESTIMATED voids it
# ---------------------------------------------------------------------------
def test_refill_reverse_voids_unadjudicated_charge(api):
    """PRD §3.6: "Reversal restores the count — refills_remaining is incremented
    by 1 — and cascades to the linked charge identified by charge_id: if that
    charge is still ESTIMATED it is voided (ESTIMATED → VOID); if it has already
    been adjudicated it is reversed (ADJUDICATED → REVERSED)."

    Design: Corner/state_machines/refill_reverse_of_unadjudicated_charge_voids_it
    """
    ctx = setup_active_prescription(api, rx_overrides={
        "hrt_type": "ESTROGEN_ORAL", "refill_price_cents": 18000})
    fulfilled = add_fulfilled_refill(api, ctx)
    reversed_refill = validate_success(
        api.reverse_refill(fulfilled["id"], ctx["provider_headers"],
                           {"reason": "returned unopened"}))
    assert reversed_refill["status"] == "REVERSED", \
        f"expected REVERSED, got {reversed_refill['status']}"
    charge = get_success_data(api.get_charge(fulfilled["charge_id"], ctx["provider_headers"]))
    assert charge["status"] == "VOID", f"expected VOID charge, got {charge['status']}"
