"""Repair-order workflow: the block/resume cycle, the safety gate on start,
committed-cost recomputation and conservation, priority-conflict precedence, and
breadth checks over the repair lifecycle."""
from test_helpers import (
    api_client, TEST_USERS, make_technician_headers, ApiErrorId,
    validate_success, validate_error, validate_paginated,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------- nlsm block/resume
def test_block_moves_in_progress_repair_to_blocked():
    """PRD §3.5: "Real jobs stall, so the order is cyclic: a `Technician` can block
    an `IN_PROGRESS` order (`IN_PROGRESS → BLOCKED`) and later resume it (`BLOCKED
    → IN_PROGRESS`); this block/resume pair may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/nlsm_repairorder_block_resume_cycle
    """
    setup = fx.setup_safe_draft_job(job_overrides={"repair_authorization_cents": 50000})
    tech = setup["technician"]
    ro = fx.propose_repair(setup["job"]["id"], technician=tech, repair_type="LINER", part_sku="LNR-AL",
                           quoted_cost_cents=20000)
    fx.approve_repair(ro["id"])
    fx.start_repair(ro["id"], tech)
    resp = api_client.transition_repair_order(ro["id"], {"action": "BLOCK"}, make_technician_headers(tech["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "BLOCKED"


def test_resume_returns_blocked_repair_to_in_progress():
    """PRD §3.5: "Real jobs stall, so the order is cyclic: a `Technician` can block
    an `IN_PROGRESS` order (`IN_PROGRESS → BLOCKED`) and later resume it (`BLOCKED
    → IN_PROGRESS`); this block/resume pair may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/nlsm_repairorder_block_resume_cycle
    """
    setup = fx.setup_safe_draft_job(job_overrides={"repair_authorization_cents": 50000})
    tech = setup["technician"]
    ro = fx.propose_repair(setup["job"]["id"], technician=tech, repair_type="LINER", part_sku="LNR-AL",
                           quoted_cost_cents=20000)
    fx.approve_repair(ro["id"])
    fx.start_repair(ro["id"], tech)
    api_client.transition_repair_order(ro["id"], {"action": "BLOCK"}, make_technician_headers(tech["id"]))
    resp = api_client.transition_repair_order(ro["id"], {"action": "RESUME"}, make_technician_headers(tech["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------- cesd repair start safety gate
def test_repair_start_rejected_when_job_unsafe():
    """PRD §3.5: "Both starting and resuming are safety-gated — the parent job's
    `safety_posture` must be `SAFE` or `CONDITIONS`, else `ERR_JOB_UNSAFE` — while
    blocking carries no such gate."

    Design: Difficulty/cross_entity_state_dependency/cesd_repair_start_requires_job_posture_safe
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 2, "repair_authorization_cents": 50000})
    tech = setup["technician"]
    ro = fx.propose_repair(setup["job"]["id"], technician=tech, repair_type="CAP", part_sku="CAP-STD",
                           quoted_cost_cents=9000)
    fx.approve_repair(ro["id"])
    fx.record_safety_check(setup["job"]["id"], tech, co_ppm=15, draft_ok=False, spillage_detected=True)  # -> UNSAFE
    resp = api_client.transition_repair_order(ro["id"], {"action": "START"}, make_technician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_JOB_UNSAFE)
    assert fx.get_repair_order(ro["id"])["status"] == "APPROVED"


def test_repair_start_rejected_when_posture_pending():
    """PRD §2.7: "Several operations are gated on posture: a repair may only be
    started or resumed, a job may only be completed, and a warranty may only be
    issued when the job's `safety_posture` is either `SAFE` or `CONDITIONS`. If any
    of these is attempted while the posture is `PENDING`, `UNSAFE`, or `CONDEMNED`,
    the request is rejected with `ERR_JOB_UNSAFE`."

    Design: Difficulty/cross_entity_state_dependency/cesd_repair_start_requires_job_posture_safe
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 2, "repair_authorization_cents": 50000})
    tech = setup["technician"]
    ro = fx.propose_repair(setup["job"]["id"], technician=tech, repair_type="CAP", part_sku="CAP-STD",
                           quoted_cost_cents=9000)
    fx.approve_repair(ro["id"])
    # Posture is still PENDING (no safety check recorded).
    resp = api_client.transition_repair_order(ro["id"], {"action": "START"}, make_technician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_JOB_UNSAFE)
    assert fx.get_repair_order(ro["id"])["status"] == "APPROVED"


# ---------------------------------------------------------------- tc repair cancel -> committed
def test_repair_cancel_recomputes_committed_cost():
    """PRD §3.5: "Cancellation removes the order from the committed sum, so the
    job's `committed_cost_cents` is recomputed to its `sweep_provisional_cost_cents`
    plus the `provisional_cost_cents` of the surviving orders that are neither
    rejected nor cancelled."

    Design: Difficulty/transitive_cascade/tc_repaircancel_committed_cost_depth2
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "trip_zone": "A", "repair_authorization_cents": 100000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    ro1 = fx.propose_repair(job_id, technician=tech, repair_type="CAP", part_sku="CAP-SS", quoted_cost_cents=12000)
    fx.propose_repair(job_id, technician=tech, repair_type="DAMPER", part_sku="DMP-THR", quoted_cost_cents=8000)
    api_client.transition_repair_order(ro1["id"], {"action": "CANCEL"}, DISPATCHER)
    # 15000 sweep_provisional + 8000 surviving = 23000
    assert fx.get_job(job_id)["committed_cost_cents"] == 23000
    assert fx.get_repair_order(ro1["id"])["status"] == "CANCELLED"


def test_committed_cost_before_and_after_repair_cancel():
    """PRD §2.8: "A `ServiceJob`'s `committed_cost_cents` is always its
    `sweep_provisional_cost_cents` plus the sum of `provisional_cost_cents` over its
    repair orders whose status is neither `REJECTED` nor `CANCELLED`."

    Design: Difficulty/transitive_cascade/tc_repaircancel_committed_cost_depth2
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "trip_zone": "A", "repair_authorization_cents": 100000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    ro1 = fx.propose_repair(job_id, technician=tech, repair_type="CAP", part_sku="CAP-SS", quoted_cost_cents=12000)
    fx.propose_repair(job_id, technician=tech, repair_type="DAMPER", part_sku="DMP-THR", quoted_cost_cents=8000)
    assert fx.get_job(job_id)["committed_cost_cents"] == 35000  # 15000 + 12000 + 8000
    api_client.transition_repair_order(ro1["id"], {"action": "CANCEL"}, DISPATCHER)
    assert fx.get_job(job_id)["committed_cost_cents"] == 23000


# ---------------------------------------------------------------- ci committed conservation
def test_committed_cost_conserved_through_propose_and_cancel():
    """PRD §2.8: "Both are invariants: booking an appointment and then cancelling
    it restores `booked_minutes` exactly, and proposing a repair and then
    cancelling or rejecting it returns `committed_cost_cents` to exactly the value
    implied by the surviving orders."

    Design: Difficulty/compensating_invariant/ci_committed_cost_repair_cancel_money
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "trip_zone": "A", "repair_authorization_cents": 100000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    fx.propose_repair(job_id, technician=tech, repair_type="DAMPER", part_sku="DMP-THR", quoted_cost_cents=8000)
    ro_cancel = fx.propose_repair(job_id, technician=tech, repair_type="CAP", part_sku="CAP-STD", quoted_cost_cents=12000)
    api_client.transition_repair_order(ro_cancel["id"], {"action": "CANCEL"}, DISPATCHER)
    # Back to sweep_provisional 15000 + surviving 8000 = 23000
    assert fx.get_job(job_id)["committed_cost_cents"] == 23000


def test_committed_cost_returns_to_baseline_after_compensating_cancel():
    """PRD §2.8: "A `ServiceJob`'s `committed_cost_cents` is always its
    `sweep_provisional_cost_cents` plus the sum of `provisional_cost_cents` over its
    repair orders whose status is neither `REJECTED` nor `CANCELLED`."

    Design: Difficulty/compensating_invariant/ci_committed_cost_repair_cancel_money
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "trip_zone": "A", "repair_authorization_cents": 100000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    assert setup["job"]["committed_cost_cents"] == 15000  # baseline: sweep_provisional only
    fx.propose_repair(job_id, technician=tech, repair_type="DAMPER", part_sku="DMP-THR", quoted_cost_cents=8000)
    ro_cancel = fx.propose_repair(job_id, technician=tech, repair_type="CAP", part_sku="CAP-STD", quoted_cost_cents=12000)
    assert fx.get_job(job_id)["committed_cost_cents"] == 35000
    api_client.transition_repair_order(ro_cancel["id"], {"action": "CANCEL"}, DISPATCHER)
    assert fx.get_job(job_id)["committed_cost_cents"] == 23000


# ---------------------------------------------------------------- ppvc referential beats fiscal
def test_unknown_part_beats_over_authorization_cost():
    """PRD §2.11: "10. **Part referential integrity** — repair part rules, else
    `ERR_PART_REQUIRED` or `ERR_UNKNOWN_PART` (422)."
    PRD §2.11: "12. **Fiscal limits** — repair authorization ceiling and route
    capacity, else `ERR_REPAIR_COST_EXCEEDS_AUTH` or `ERR_ROUTE_CAPACITY_EXCEEDED`
    (402)."
    PRD §2.11: "A check earlier in this list always takes precedence over one later
    in the list when both would fail."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_referential_beats_fiscal_on_repair_create
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 1000})
    tech = setup["technician"]
    resp = api_client.create_repair_order(
        F.create_repair_order_payload(service_job_id=setup["job"]["id"], repair_type="CAP",
                                      part_sku="BOGUS-999", quoted_cost_cents=50000),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_PART)


def test_missing_part_beats_over_authorization_cost():
    """PRD §2.11: "10. **Part referential integrity** — repair part rules, else
    `ERR_PART_REQUIRED` or `ERR_UNKNOWN_PART` (422)."
    PRD §2.11: "12. **Fiscal limits** — repair authorization ceiling and route
    capacity, else `ERR_REPAIR_COST_EXCEEDS_AUTH` or `ERR_ROUTE_CAPACITY_EXCEEDED`
    (402)."
    PRD §2.11: "A check earlier in this list always takes precedence over one later
    in the list when both would fail."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_referential_beats_fiscal_on_repair_create
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 1000})
    tech = setup["technician"]
    resp = api_client.create_repair_order(
        F.create_repair_order_payload(service_job_id=setup["job"]["id"], repair_type="CAP",
                                      quoted_cost_cents=50000),  # no part_sku on a CAP
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PART_REQUIRED)


# ---------------------------------------------------------------- corner: reject recomputes
def test_committed_cost_after_repair_reject():
    """PRD §3.5: "Rejecting an order drops it out of the committed-cost sum, so the
    job's `committed_cost_cents` is recomputed."

    Design: Corner/calculations/committed_cost_after_repair_reject
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "trip_zone": "A", "repair_authorization_cents": 100000})
    job_id = setup["job"]["id"]
    fx.propose_repair(job_id, headers=DISPATCHER, repair_type="DAMPER", part_sku="DMP-THR", quoted_cost_cents=8000)
    ro_reject = fx.propose_repair(job_id, headers=DISPATCHER, repair_type="CAP", part_sku="CAP-STD", quoted_cost_cents=12000)
    api_client.transition_repair_order(ro_reject["id"], {"action": "REJECT"}, DISPATCHER)
    assert fx.get_job(job_id)["committed_cost_cents"] == 23000
    assert fx.get_repair_order(ro_reject["id"])["status"] == "REJECTED"


# ---------------------------------------------------------------- corner: invalid transition
def test_complete_repair_from_proposed_rejected():
    """PRD §3.5: "A `Technician` completes an `IN_PROGRESS` order by supplying
    `final_cost_cents` and `labor_cents`; the labor portion may not exceed the
    final cost, else `ERR_VALIDATION`. Completion sets `final_cost_cents` and
    `labor_cents` and derives `parts_cents` as the final cost minus the labor. Each
    of these transitions is legal only from the state named as its source; any
    other origin is `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/invalid_transition_complete_repair_from_proposed
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 50000})
    tech = setup["technician"]
    ro = fx.propose_repair(setup["job"]["id"], headers=DISPATCHER, repair_type="CAP", part_sku="CAP-STD",
                           quoted_cost_cents=9000)
    resp = api_client.transition_repair_order(
        ro["id"], {"action": "COMPLETE", "final_cost_cents": 9000, "labor_cents": 5000},
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert fx.get_repair_order(ro["id"])["status"] == "PROPOSED"


# ---------------------------------------------------------------- corner: idempotency
def test_double_approve_repair_rejected():
    """PRD §3.5: "A `Dispatcher` approves a `PROPOSED` order (`PROPOSED →
    APPROVED`) or rejects it (`PROPOSED → REJECTED`); either is legal only from
    `PROPOSED`, else `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/idempotency_double_approve_repair
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 50000})
    ro = fx.propose_repair(setup["job"]["id"], headers=DISPATCHER, repair_type="DAMPER", part_sku="DMP-TOP",
                           quoted_cost_cents=7000)
    fx.approve_repair(ro["id"])
    resp = api_client.transition_repair_order(ro["id"], {"action": "APPROVE"}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert fx.get_repair_order(ro["id"])["status"] == "APPROVED"


# ---------------------------------------------------------------- corner: part required
def test_cap_repair_without_part_rejected():
    """PRD §3.5: "A part is required for a `CAP`, `LINER`, or `DAMPER` repair and
    must be omitted for a `GAS_LOG_CONVERSION`; a missing part where one is required
    raises `ERR_PART_REQUIRED`."

    Design: Corner/validations/error_part_required_missing_on_cap_repair
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 50000})
    tech = setup["technician"]
    resp = api_client.create_repair_order(
        F.create_repair_order_payload(service_job_id=setup["job"]["id"], repair_type="CAP", quoted_cost_cents=9000),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PART_REQUIRED)


# ---------------------------------------------------------------- corner: cost exceeds auth
def test_repair_cost_exceeds_authorization():
    """PRD §3.5: "Fiscally, the `quoted_cost_cents` may not exceed the parent job's
    `repair_authorization_cents`, else `ERR_REPAIR_COST_EXCEEDS_AUTH`."

    Design: Corner/validations/error_repair_cost_exceeds_authorization
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 5000})
    tech = setup["technician"]
    resp = api_client.create_repair_order(
        F.create_repair_order_payload(service_job_id=setup["job"]["id"], repair_type="LINER",
                                      part_sku="LNR-SS6", quoted_cost_cents=30000),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REPAIR_COST_EXCEEDS_AUTH)


# ---------------------------------------------------------------- corner: RBAC denial
def test_billing_clerk_cannot_propose_repair():
    """PRD §2.1: "A `BillingClerk` handles money: completing jobs (which finalizes
    the invoice), issuing warranties, and processing warranty claims."
    PRD §2.1: "When a role is not permitted to perform the requested operation, the
    request is rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/validations/error_unauthorized_billingclerk_proposes_repair
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 50000})
    resp = api_client.create_repair_order(
        F.create_repair_order_payload(service_job_id=setup["job"]["id"], repair_type="CAP",
                                      part_sku="CAP-STD", quoted_cost_cents=9000),
        BILLING,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


# ---------------------------------------------------------------- corner: FK reverse lookup
def test_list_repair_orders_by_service_job():
    """PRD §3.5: "Repair orders may be fetched or listed with optional
    `service_job_id` and `status` filters."

    Design: Corner/endpoints/fk_reverse_repair_orders_by_service_job
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 50000})
    ro = fx.propose_repair(setup["job"]["id"], headers=DISPATCHER, repair_type="CAP", part_sku="CAP-STD",
                           quoted_cost_cents=9000)
    resp = api_client.list_repair_orders(DISPATCHER, params={"service_job_id": setup["job"]["id"]})
    data, _meta = validate_paginated(resp)
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["id"] == ro["id"]
