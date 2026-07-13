"""Fabrication scheduling and completion: approved-proof gate, state guards, and
schedule-window / existence validation."""
import test_helpers as th


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / fabrication_requires_approved_proof
# ---------------------------------------------------------------------------
def test_fabrication_with_unapproved_proof_returns_proof_not_approved(api):
    """PRD §3.5: "the order's current proof must be `APPROVED` (otherwise `ERR_PROOF_NOT_APPROVED`)
    — note that approving a proof does not itself advance production, so this cross-entity gate
    is what enforces that an approved design exists before the shop begins".

    Design: Difficulty/cross_entity_state_dependency/fabrication_requires_approved_proof
    """
    ctx = th.setup_submitted_proof(
        proof_lines=[21, 31], cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    ws = th.make_workshop()
    payload = th.create_fabrication_job_payload(
        ctx["order"]["id"], ws["id"], "2026-03-05T09:00:00Z", "2026-03-05T12:00:00Z"
    )
    resp = api.create_fabrication_job(payload, th.TEST_USERS["shop_manager_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_PROOF_NOT_APPROVED.value)


def test_fabrication_with_unapproved_proof_leaves_order_drafting(api):
    """PRD §3.5: "Scheduling fabrication is the transition that carries the order from `DRAFTING`
    to `IN_FABRICATION`, and it is subject to several preconditions."

    Design: Difficulty/cross_entity_state_dependency/fabrication_requires_approved_proof
    """
    ctx = th.setup_submitted_proof(
        proof_lines=[21, 31], cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    ws = th.make_workshop()
    payload = th.create_fabrication_job_payload(
        ctx["order"]["id"], ws["id"], "2026-03-05T09:00:00Z", "2026-03-05T12:00:00Z"
    )
    api.create_fabrication_job(payload, th.TEST_USERS["shop_manager_headers"])
    order = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["production_status"] == "DRAFTING", order


# ---------------------------------------------------------------------------
# Corner: state_machines / fabricate_non_drafting_order_returns_not_drafting
# ---------------------------------------------------------------------------
def test_second_fabrication_on_in_fabrication_order_returns_not_drafting(api):
    """PRD §3.5: "The order must be in `DRAFTING` (otherwise `ERR_ORDER_NOT_DRAFTING`)".

    Design: Corner/state_machines/fabricate_non_drafting_order_returns_not_drafting
    """
    ctx = th.setup_in_fabrication(
        proof_lines=[21, 31], cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    payload = th.create_fabrication_job_payload(
        ctx["order"]["id"], ctx["workshop"]["id"], "2026-03-06T09:00:00Z", "2026-03-06T12:00:00Z"
    )
    resp = api.create_fabrication_job(payload, th.TEST_USERS["shop_manager_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_ORDER_NOT_DRAFTING.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / complete_fabrication_twice_returns_not_scheduled
# ---------------------------------------------------------------------------
def test_complete_already_completed_fabrication_returns_not_scheduled(api):
    """PRD §3.5: "the `ShopManager` completes the job, which must be in `SCHEDULED` (otherwise
    `ERR_FAB_JOB_NOT_SCHEDULED`)."

    Design: Corner/state_machines/complete_fabrication_twice_returns_not_scheduled
    """
    ctx = th.setup_ready_to_install(
        proof_lines=[21, 31], cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    resp = api.complete_fabrication_job(ctx["fabrication_job"]["id"], th.TEST_USERS["shop_manager_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_FAB_JOB_NOT_SCHEDULED.value)


# ---------------------------------------------------------------------------
# Corner: validations / fabrication_bad_schedule_window_returns_error
# ---------------------------------------------------------------------------
def test_fabrication_end_before_start_returns_invalid_schedule_window(api):
    """PRD §2.7: "every scheduled slot must be well-formed: its `scheduled_end` must be strictly
    after its `scheduled_start`, or the request is rejected with `ERR_INVALID_SCHEDULE_WINDOW`."

    Design: Corner/validations/fabrication_bad_schedule_window_returns_error
    """
    ctx = th.setup_order_and_workshop(cemetery_over={"requires_permit": False, "permit_fee_cents": 0})
    payload = th.create_fabrication_job_payload(
        ctx["order"]["id"], ctx["workshop"]["id"], "2026-03-05T12:00:00Z", "2026-03-05T09:00:00Z"
    )
    resp = api.create_fabrication_job(payload, th.TEST_USERS["shop_manager_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_SCHEDULE_WINDOW.value)


# ---------------------------------------------------------------------------
# Corner: errors / fabrication_unknown_workshop_returns_not_found
# ---------------------------------------------------------------------------
def test_fabrication_unknown_workshop_returns_not_found(api):
    """PRD §2.10: "existence is validated left to right, and the first identifier that does not
    resolve yields its own not-found error — `ERR_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_CEMETERY_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_FAB_JOB_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`, or
    `ERR_RESTORATION_NOT_FOUND` as appropriate."

    Design: Corner/errors/fabrication_unknown_workshop_returns_not_found
    """
    ctx = th.setup_drafting_order(cemetery_over={"requires_permit": False, "permit_fee_cents": 0})
    payload = th.create_fabrication_job_payload(
        ctx["order"]["id"], th.NON_EXISTENT_UUID, "2026-03-05T09:00:00Z", "2026-03-05T12:00:00Z"
    )
    resp = api.create_fabrication_job(payload, th.TEST_USERS["shop_manager_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_WORKSHOP_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: errors / complete_unknown_fabrication_returns_not_found
# ---------------------------------------------------------------------------
def test_complete_unknown_fabrication_returns_not_found(api):
    """PRD §2.10: "existence is validated left to right, and the first identifier that does not
    resolve yields its own not-found error — `ERR_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_CEMETERY_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_FAB_JOB_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`, or
    `ERR_RESTORATION_NOT_FOUND` as appropriate."

    Design: Corner/errors/complete_unknown_fabrication_returns_not_found
    """
    resp = api.complete_fabrication_job(th.NON_EXISTENT_UUID, th.TEST_USERS["shop_manager_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_FAB_JOB_NOT_FOUND.value)
