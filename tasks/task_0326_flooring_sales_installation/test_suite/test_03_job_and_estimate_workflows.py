"""Job and estimate lifecycle: the re-measure cycle, the backorder cycle, the
job-cancel teardown cascade, estimate re-issue supersession, and the
single-ISSUED-estimate invariant. Plus state-machine corner instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_estimate_payload, measure_payload, issue_payload,
    create_draft_job, create_measured_job, create_issued_estimate,
    create_accepted_job, create_completed_job, create_scheduled_job,
    setup_backordered_n_times, register_customer, register_sales_rep,
    create_product, make_sales_rep_headers, make_customer_headers, set_clock,
    TEST_USERS,
)


# ─── Re-measure cycle: MEASURED -> RE_MEASURE -> MEASURED ─────────────

def test_remeasure_cycle_returns_job_to_measured_with_new_geometry(api):
    """PRD §3.4: "The loop closes when the estimator measures again, returning
    the job from `RE_MEASURE → MEASURED` with fresh geometry and a recomputed
    waste factor."

    Design: Difficulty/non_linear_state_machine/job_remeasure_cycle_measured_to_remeasure_to_measured
    """
    # HARDWOOD job measured 500/2 then issued; remeasure; measure again 640/3 (waste 15.0).
    customer, sales_rep, product, job, est = create_issued_estimate(
        declared_sqft=500, measured_sqft=500, tear_out_sqft=0, room_count=2,
        product_overrides={"sku": "HW-1", "category": "HARDWOOD",
                           "material_cost_per_sqft_cents": 600,
                           "labor_rate_per_sqft_cents": 350,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 5, "warranty_years": 20},
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    get_success_data(api.request_remeasure(job["id"], rep_headers))
    job = get_success_data(api.measure_job(
        job["id"], measure_payload(measured_sqft=640, tear_out_sqft=50, room_count=3),
        TEST_USERS["estimator_headers"]))
    assert job["status"] == "MEASURED"
    assert job["measured_sqft"] == 640
    assert job["waste_factor_pct"] == 15.0


def test_remeasure_voids_the_issued_estimate(api):
    """PRD §3.4: "the job moves to `RE_MEASURE`, the job's `version` is bumped,
    and as a cascade the job's currently `ISSUED` estimate, if one exists, is
    voided — moved to `VOIDED`."

    Design: Difficulty/non_linear_state_machine/job_remeasure_cycle_measured_to_remeasure_to_measured
    """
    customer, sales_rep, product, job, est = create_issued_estimate(
        declared_sqft=500, measured_sqft=500, tear_out_sqft=0, room_count=2,
        product_overrides={"sku": "HW-1B", "category": "HARDWOOD",
                           "material_cost_per_sqft_cents": 600,
                           "labor_rate_per_sqft_cents": 350,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 5, "warranty_years": 20},
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    get_success_data(api.request_remeasure(job["id"], rep_headers))
    est_after = get_success_data(api.get_estimate(est["id"], rep_headers))
    assert est_after["status"] == "VOIDED"


# ─── Backorder cycle: ORDERED -> BACKORDERED -> ORDERED ───────────────

def test_backorder_count_increments_across_two_cycles(api):
    """PRD §3.7: "When a vendor reports a stock-out, the scheduler moves an order
    `ORDERED → BACKORDERED`, which increments the order's `backorder_count` by one
    and bumps its `version`."

    Design: Difficulty/non_linear_state_machine/material_order_backorder_cycle_ordered_to_backordered_to_ordered
    """
    # One round of backorder/reorder, then a final backorder -> count 2, BACKORDERED.
    customer, sales_rep, product, job, order = setup_backordered_n_times(
        1, declared_sqft=400, measured_sqft=400, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "LVP-B", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 7, "warranty_years": 12},
    )
    order = get_success_data(api.backorder_material_order(order["id"], TEST_USERS["scheduler_headers"]))
    assert order["backorder_count"] == 2


def test_backorder_sets_status_backordered(api):
    """PRD §3.7: "A backorder is only legal from `ORDERED`, and a reorder only
    from `BACKORDERED`".

    Design: Difficulty/non_linear_state_machine/material_order_backorder_cycle_ordered_to_backordered_to_ordered
    """
    customer, sales_rep, product, job, order = setup_backordered_n_times(
        1, declared_sqft=400, measured_sqft=400, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "LVP-B2", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 7, "warranty_years": 12},
    )
    order = get_success_data(api.backorder_material_order(order["id"], TEST_USERS["scheduler_headers"]))
    assert order["status"] == "BACKORDERED"


# ─── Job-cancel depth-3 teardown cascade ──────────────────────────────

def test_job_cancel_cascades_to_material_order(api):
    """PRD §3.10: "The job's material order, if it is in `ORDERED` or
    `BACKORDERED`, is cancelled to `CANCELLED`."

    Design: Difficulty/transitive_cascade/job_cancel_depth3_teardown_estimate_order_slot
    """
    (customer, sales_rep, product, job, est, order, crew, slot) = create_scheduled_job(
        declared_sqft=400, measured_sqft=400, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "LVP-C", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 0, "warranty_years": 10},
        crew_overrides={"skill_categories": ["LVP"], "daily_sqft_capacity": 1000},
        start_at="2026-06-05T09:00:00.000Z", end_at="2026-06-05T15:00:00.000Z",
        receive_material=False,
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    job = get_success_data(api.cancel_job(job["id"], rep_headers))
    order_after = get_success_data(api.get_material_order(order["id"], TEST_USERS["scheduler_headers"]))
    assert job["status"] == "CANCELLED"
    assert order_after["status"] == "CANCELLED"


def test_job_cancel_cascades_to_scheduled_slot(api):
    """PRD §3.10: "And every `SCHEDULED` install slot of the job is cancelled,
    releasing the crew capacity each was holding."

    Design: Difficulty/transitive_cascade/job_cancel_depth3_teardown_estimate_order_slot
    """
    (customer, sales_rep, product, job, est, order, crew, slot) = create_scheduled_job(
        declared_sqft=400, measured_sqft=400, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "LVP-C2", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 0, "warranty_years": 10},
        crew_overrides={"skill_categories": ["LVP"], "daily_sqft_capacity": 1000},
        start_at="2026-06-05T09:00:00.000Z", end_at="2026-06-05T15:00:00.000Z",
        receive_material=False,
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    get_success_data(api.cancel_job(job["id"], rep_headers))
    slot_after = get_success_data(api.get_install_slot(slot["id"], TEST_USERS["scheduler_headers"]))
    assert slot_after["status"] == "CANCELLED"


# ─── Estimate re-issue supersession (depth-2) ─────────────────────────

def _issue_second_estimate(api):
    """Job MEASURED; issue est1 (job -> ESTIMATED); create + issue est2."""
    customer, sales_rep, product, job, est1 = create_issued_estimate(
        declared_sqft=300, measured_sqft=300, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "HW-S", "category": "HARDWOOD",
                           "material_cost_per_sqft_cents": 600,
                           "labor_rate_per_sqft_cents": 350,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 5, "warranty_years": 20},
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    est2 = get_success_data(api.create_estimate(
        create_estimate_payload(job["id"], variant="MEASURED"), rep_headers))
    est2 = get_success_data(api.issue_estimate(
        est2["id"], issue_payload(job["version"]), rep_headers))
    return api, rep_headers, job, est1, est2


def test_reissue_supersedes_prior_issued_estimate(api):
    """PRD §3.5: "When these hold, the estimate moves `DRAFT → ISSUED`, and any
    estimate that was previously `ISSUED` on the same job is voided to `VOIDED`,
    because a job may have only one issued estimate at any time."

    Design: Difficulty/transitive_cascade/estimate_reissue_depth2_supersede_prior_and_advance_job
    """
    api, rep_headers, job, est1, est2 = _issue_second_estimate(api)
    est1_after = get_success_data(api.get_estimate(est1["id"], rep_headers))
    assert est2["status"] == "ISSUED"
    assert est1_after["status"] == "VOIDED"


def test_reissue_keeps_job_in_estimated(api):
    """PRD §3.5: "a subsequent issue against a job already in `ESTIMATED` leaves
    the job in `ESTIMATED` while superseding the prior issued estimate."

    Design: Difficulty/transitive_cascade/estimate_reissue_depth2_supersede_prior_and_advance_job
    """
    api, rep_headers, job, est1, est2 = _issue_second_estimate(api)
    job_after = get_success_data(api.get_job(job["id"], rep_headers))
    assert job_after["status"] == "ESTIMATED"


# ─── Compensating invariant: at most one ISSUED estimate per job ──────

def _remeasure_reissue_cycle(api):
    """Issue est A; remeasure (voids A); measure again; create + issue est B."""
    customer, sales_rep, product, job, est_a = create_issued_estimate(
        declared_sqft=300, measured_sqft=300, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "HW-I", "category": "HARDWOOD",
                           "material_cost_per_sqft_cents": 600,
                           "labor_rate_per_sqft_cents": 350,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 5, "warranty_years": 20},
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    get_success_data(api.request_remeasure(job["id"], rep_headers))
    job = get_success_data(api.measure_job(
        job["id"], measure_payload(measured_sqft=320, tear_out_sqft=0, room_count=1),
        TEST_USERS["estimator_headers"]))
    est_b = get_success_data(api.create_estimate(
        create_estimate_payload(job["id"], variant="MEASURED"), rep_headers))
    est_b = get_success_data(api.issue_estimate(
        est_b["id"], issue_payload(job["version"]), rep_headers))
    return api, rep_headers, job, est_a, est_b


def test_remeasure_reissue_voids_a_and_issues_b(api):
    """PRD §3.5: "any estimate that was previously `ISSUED` on the same job is
    voided to `VOIDED`, because a job may have only one issued estimate at any
    time."

    Design: Difficulty/compensating_invariant/remeasure_void_conserves_single_issued_estimate_invariant
    """
    api, rep_headers, job, est_a, est_b = _remeasure_reissue_cycle(api)
    est_a_after = get_success_data(api.get_estimate(est_a["id"], rep_headers))
    assert est_a_after["status"] == "VOIDED"
    assert est_b["status"] == "ISSUED"


def test_remeasure_reissue_leaves_exactly_one_issued_estimate(api):
    """PRD §3.5: "a job may have only one issued estimate at any time."
    PRD §3.5: "The first issue against a `MEASURED` job bubbles the job up
    `MEASURED → ESTIMATED`".

    Design: Difficulty/compensating_invariant/remeasure_void_conserves_single_issued_estimate_invariant
    """
    api, rep_headers, job, est_a, est_b = _remeasure_reissue_cycle(api)
    job_after = get_success_data(api.get_job(job["id"], rep_headers))
    assert job_after["status"] == "ESTIMATED"
    data, _meta = validate_paginated(api.list_job_estimates(job["id"], rep_headers))
    issued = [e for e in data if e["status"] == "ISSUED"]
    assert len(issued) == 1
    assert issued[0]["id"] == est_b["id"]


# ─── State-machine corner instances ───────────────────────────────────

def test_job_initial_state_is_draft(api):
    """PRD §3.2: "A new job starts in `DRAFT` status."

    Design: Corner/state_machines/job_initial_state_is_draft
    """
    customer, sales_rep, product, job = create_draft_job(declared_sqft=200)
    assert job["status"] == "DRAFT"


def test_measure_already_measured_job_rejected(api):
    """PRD §3.3: "A measure attempted from any state other than `DRAFT` or
    `RE_MEASURE` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/measure_invalid_when_already_measured
    """
    customer, sales_rep, product, job = create_measured_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1)
    res = api.measure_job(
        job["id"], measure_payload(measured_sqft=210, tear_out_sqft=0, room_count=1),
        TEST_USERS["estimator_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_completed_job_rejected(api):
    """PRD §3.10: "A `SalesRep` may cancel a job from any non-terminal pre-install
    state — that is, while it is in `DRAFT`, `MEASURED`, `RE_MEASURE`,
    `ESTIMATED`, or `ACCEPTED` — moving it to `CANCELLED`; a cancel from any other
    status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_terminal_completed_job_returns_invalid_state
    """
    customer, sales_rep, product, job, crew, slot = create_completed_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "TERM-1", "category": "CARPET",
                           "material_cost_per_sqft_cents": 100,
                           "labor_rate_per_sqft_cents": 100,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 5})
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    res = api.cancel_job(job["id"], rep_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_accept_already_accepted_estimate_rejected(api):
    """PRD §3.6: "Acceptance requires the job to be in `ESTIMATED`; otherwise it
    is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/estimate_accept_twice_idempotency_rejected
    """
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1)
    cust_headers = make_customer_headers(customer["id"])
    res = api.accept_estimate(est["id"], cust_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_material_receive_unlocks_slot_start(api):
    """PRD §3.7: "Reaching `RECEIVED` is what unlocks the start of installation
    for the job."
    PRD §3.9: "On a successful start the job advances `ACCEPTED → IN_INSTALL` and
    its `version` is bumped."

    Design: Corner/state_machines/material_receive_unlocks_slot_start
    """
    (customer, sales_rep, product, job, est, order, crew, slot) = create_scheduled_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "SIDE-1", "category": "CARPET",
                           "material_cost_per_sqft_cents": 100,
                           "labor_rate_per_sqft_cents": 100,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 5},
        start_at="2026-06-02T09:00:00.000Z", end_at="2026-06-02T15:00:00.000Z",
        receive_material=True,
    )
    get_success_data(api.start_install_slot(slot["id"], TEST_USERS["scheduler_headers"]))
    job_after = get_success_data(api.get_job(job["id"], TEST_USERS["admin_headers"]))
    assert job_after["status"] == "IN_INSTALL"


def test_estimate_lazy_expiry_after_valid_until(api):
    """PRD §2.8: "Estimate expiry in particular is lazy — an estimate moves to
    `EXPIRED` only when an expire-check is invoked at or after `valid_until`."

    Design: Corner/state_machines/estimate_lazy_expiry_after_valid_until
    """
    customer, sales_rep, product, job, est = create_issued_estimate(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        valid_until="2026-06-15T00:00:00.000Z",
        product_overrides={"sku": "EXP-1", "category": "LVP", "lead_time_days": 0},
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    set_clock("2026-06-16T00:00:00.000Z")
    est_after = get_success_data(api.expire_check_estimate(est["id"], rep_headers))
    assert est_after["status"] == "EXPIRED"


def test_crew_deactivate_blocked_by_scheduled_slot(api):
    """PRD §3.8: "A scheduler may deactivate an `AVAILABLE` crew, moving it
    `AVAILABLE → INACTIVE`, but only when none of the crew's slots are currently
    `SCHEDULED`; deactivating a crew that still holds a scheduled slot, or one not
    in `AVAILABLE`, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/crew_deactivate_blocked_by_scheduled_slot
    """
    (customer, sales_rep, product, job, est, order, crew, slot) = create_scheduled_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "DEACT-1", "category": "CARPET",
                           "material_cost_per_sqft_cents": 100,
                           "labor_rate_per_sqft_cents": 100,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 5},
        start_at="2026-06-10T09:00:00.000Z", end_at="2026-06-10T12:00:00.000Z",
        receive_material=False,
    )
    res = api.deactivate_install_crew(crew["id"], TEST_USERS["scheduler_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
