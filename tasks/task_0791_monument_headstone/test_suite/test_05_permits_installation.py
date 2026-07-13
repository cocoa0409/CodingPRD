"""Permitting and installation scheduling: validation precedence, cross-entity permit gate,
crew buffered conflicts, and permit/installation existence + state guards."""
import test_helpers as th


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / install_temporal_precedes_referential
# ---------------------------------------------------------------------------
def test_install_before_fab_ready_wins_over_pending_permit(api):
    """PRD §2.10: "then the installation temporal-readiness check (`ERR_INSTALL_BEFORE_FAB_READY`);
    then resource slot-conflict checks (`ERR_WORKSHOP_SLOT_CONFLICT` / `ERR_CREW_SLOT_CONFLICT`);
    then the cross-entity readiness gates (`ERR_PROOF_NOT_APPROVED` / `ERR_PERMIT_NOT_ISSUED`)".

    Design: Difficulty/priority_pair_validation_conflict/install_temporal_precedes_referential
    """
    ctx = th.setup_pending_permit(permit_number="P-102")
    payload = th.create_installation_payload(
        ctx["order"]["id"], ctx["crew"]["id"], "2026-03-05T09:00:00Z", "2026-03-05T11:00:00Z"
    )
    resp = api.create_installation(payload, th.TEST_USERS["field_ops_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_INSTALL_BEFORE_FAB_READY.value)


def test_install_temporal_check_precedes_permit_gate_no_install_created(api):
    """PRD §3.6: "The installation's `scheduled_start` must be at or after the order's fabrication
    `completed_at` and at or after the issued permit's `placement_date`; a start that precedes
    either readiness point is rejected with `ERR_INSTALL_BEFORE_FAB_READY`."

    Design: Difficulty/priority_pair_validation_conflict/install_temporal_precedes_referential
    """
    ctx = th.setup_pending_permit(permit_number="P-102")
    payload = th.create_installation_payload(
        ctx["order"]["id"], ctx["crew"]["id"], "2026-03-05T09:00:00Z", "2026-03-05T11:00:00Z"
    )
    resp = api.create_installation(payload, th.TEST_USERS["field_ops_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_INSTALL_BEFORE_FAB_READY.value)
    _data, meta = th.validate_paginated(
        api.list_installations(th.TEST_USERS["field_ops_headers"], params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 0, meta


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / installation_requires_issued_permit
# ---------------------------------------------------------------------------
def test_installation_with_pending_permit_returns_permit_not_issued(api):
    """PRD §3.6: "Installation requires the order to be `READY_TO_INSTALL`; when the destination
    cemetery requires a permit, an `ISSUED` permit must exist for the order (otherwise
    `ERR_PERMIT_NOT_ISSUED`)."

    Design: Difficulty/cross_entity_state_dependency/installation_requires_issued_permit
    """
    ctx = th.setup_pending_permit(permit_number="P-103")
    payload = th.create_installation_payload(
        ctx["order"]["id"], ctx["crew"]["id"], "2026-03-25T09:00:00Z", "2026-03-25T11:00:00Z"
    )
    resp = api.create_installation(payload, th.TEST_USERS["field_ops_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_PERMIT_NOT_ISSUED.value)


def test_installation_with_pending_permit_creates_no_installation(api):
    """PRD §3.6: "when the destination cemetery requires a permit, an `ISSUED` permit must exist
    for the order (otherwise `ERR_PERMIT_NOT_ISSUED`)."

    Design: Difficulty/cross_entity_state_dependency/installation_requires_issued_permit
    """
    ctx = th.setup_pending_permit(permit_number="P-103")
    payload = th.create_installation_payload(
        ctx["order"]["id"], ctx["crew"]["id"], "2026-03-25T09:00:00Z", "2026-03-25T11:00:00Z"
    )
    api.create_installation(payload, th.TEST_USERS["field_ops_headers"])
    order = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["production_status"] == "READY_TO_INSTALL", order


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / crew_buffered_slot_overlap
# ---------------------------------------------------------------------------
def test_crew_slot_within_buffer_returns_conflict(api):
    """PRD §2.7: "Two installation slots on the same crew must be separated by at least a one-hour
    turnaround — that is, sixty minutes — so a proposed slot is acceptable only if its start is at
    least sixty minutes after some existing slot's end, or its end plus sixty minutes is at or
    before some existing slot's start."

    Design: Difficulty/resource_temporal_overlap/crew_buffered_slot_overlap
    """
    ctx = th.setup_scheduled_installation(
        inst_start="2026-03-25T09:00:00Z", inst_end="2026-03-25T10:00:00Z", permit_number="P-104",
    )
    payload = th.create_installation_payload(
        ctx["order"]["id"], ctx["crew"]["id"], "2026-03-25T10:30:00Z", "2026-03-25T11:30:00Z"
    )
    resp = api.create_installation(payload, th.TEST_USERS["field_ops_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_CREW_SLOT_CONFLICT.value)


def test_crew_slot_at_exact_sixty_minute_buffer_accepted(api):
    """PRD §2.7: "a proposed slot is acceptable only if its start is at least sixty minutes after
    some existing slot's end, or its end plus sixty minutes is at or before some existing slot's
    start."

    Design: Difficulty/resource_temporal_overlap/crew_buffered_slot_overlap
    """
    ctx = th.setup_scheduled_installation(
        inst_start="2026-03-25T09:00:00Z", inst_end="2026-03-25T10:00:00Z", permit_number="P-104",
    )
    # New slot starts at 11:00 — exactly 60 minutes after the existing slot's 10:00 end.
    payload = th.create_installation_payload(
        ctx["order"]["id"], ctx["crew"]["id"], "2026-03-25T11:00:00Z", "2026-03-25T12:00:00Z"
    )
    installation = th.validate_success(
        api.create_installation(payload, th.TEST_USERS["field_ops_headers"]), 201
    )
    th.assert_installation(installation)
    assert installation["status"] == "SCHEDULED", installation


# ---------------------------------------------------------------------------
# Corner: state_machines / issue_permit_twice_returns_not_pending
# ---------------------------------------------------------------------------
def test_issue_already_issued_permit_returns_not_pending(api):
    """PRD §3.6: "Issuing a permit re-checks cemetery-spec compliance against the order's current
    marker dimensions and material per §2.6 (rejecting with `ERR_EXCEEDS_CEMETERY_SPEC` or
    `ERR_MATERIAL_NOT_ALLOWED`) and requires the permit to be `PENDING` (otherwise
    `ERR_PERMIT_NOT_PENDING`); it then moves the permit from `PENDING` to `ISSUED`".

    Design: Corner/state_machines/issue_permit_twice_returns_not_pending
    """
    ctx = th.setup_order_with_issued_permit_simple(permit_number="P-200")
    resp = api.issue_permit(ctx["permit"]["id"], th.TEST_USERS["field_ops_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_PERMIT_NOT_PENDING.value)


# ---------------------------------------------------------------------------
# Corner: validations / permit_cemetery_mismatch_returns_invalid_request
# ---------------------------------------------------------------------------
def test_permit_cemetery_mismatch_returns_invalid_request(api):
    """PRD §3.6: "The supplied `cemetery_id` must equal the order's own `cemetery_id`, or the
    request is malformed (`ERR_INVALID_REQUEST`)."

    Design: Corner/validations/permit_cemetery_mismatch_returns_invalid_request
    """
    cem_a = th.make_cemetery(name="Cemetery A", allowed_materials=["GRANITE"],
                             requires_permit=True, permit_fee_cents=12000)
    cem_b = th.make_cemetery(name="Cemetery B", allowed_materials=["GRANITE"],
                             requires_permit=True, permit_fee_cents=12000)
    cust = th.make_customer()
    order = th.make_order(cust, cem_a)
    payload = th.create_permit_payload(order["id"], cem_b["id"], permit_number="P-300")
    resp = api.create_permit(payload, th.TEST_USERS["field_ops_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner: errors / issue_unknown_permit_returns_not_found
# ---------------------------------------------------------------------------
def test_issue_unknown_permit_returns_not_found(api):
    """PRD §2.10: "existence is validated left to right, and the first identifier that does not
    resolve yields its own not-found error — `ERR_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_CEMETERY_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_FAB_JOB_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`, or
    `ERR_RESTORATION_NOT_FOUND` as appropriate."

    Design: Corner/errors/issue_unknown_permit_returns_not_found
    """
    resp = api.issue_permit(th.NON_EXISTENT_UUID, th.TEST_USERS["field_ops_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_PERMIT_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: errors / install_unknown_crew_returns_not_found
# ---------------------------------------------------------------------------
def test_install_unknown_crew_returns_not_found(api):
    """PRD §2.10: "existence is validated left to right, and the first identifier that does not
    resolve yields its own not-found error — `ERR_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_CEMETERY_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_FAB_JOB_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`, or
    `ERR_RESTORATION_NOT_FOUND` as appropriate."

    Design: Corner/errors/install_unknown_crew_returns_not_found
    """
    ctx = th.setup_drafting_order(cemetery_over={"requires_permit": False, "permit_fee_cents": 0})
    payload = th.create_installation_payload(
        ctx["order"]["id"], th.NON_EXISTENT_UUID, "2026-03-25T09:00:00Z", "2026-03-25T11:00:00Z"
    )
    resp = api.create_installation(payload, th.TEST_USERS["field_ops_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_CREW_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: errors / complete_unknown_installation_returns_not_found
# ---------------------------------------------------------------------------
def test_complete_unknown_installation_returns_not_found(api):
    """PRD §2.10: "existence is validated left to right, and the first identifier that does not
    resolve yields its own not-found error — `ERR_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_CEMETERY_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_FAB_JOB_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`, or
    `ERR_RESTORATION_NOT_FOUND` as appropriate."

    Design: Corner/errors/complete_unknown_installation_returns_not_found
    """
    resp = api.complete_installation(th.NON_EXISTENT_UUID, th.TEST_USERS["field_ops_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_INSTALLATION_NOT_FOUND.value)
