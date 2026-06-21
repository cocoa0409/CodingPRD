"""Material-order timing, cross-entity install gating, product discontinuation,
and warranty-claim adjudication (window + risk gates).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_estimate_payload, measure_payload, issue_payload,
    create_draft_job, create_accepted_job, create_accepted_job_material_received,
    create_scheduled_job, create_completed_job, create_filed_warranty_claim,
    register_customer, register_sales_rep, create_product, create_crew,
    schedule_slot, make_sales_rep_headers, make_customer_headers, set_clock,
    get_material_order_for_job,
    TEST_USERS,
)


# ─── Cross-entity: slot start requires material RECEIVED ──────────────

def test_slot_start_blocked_when_material_ordered(api):
    """PRD §3.9: "Starting requires the job to be `ACCEPTED`, the slot to be
    `SCHEDULED` and belong to that job, and — the cross-entity gate — the job's
    material order to be `RECEIVED`; a start while the material is not yet received
    is rejected with `ERR_MATERIAL_NOT_RECEIVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/slot_start_requires_material_order_received
    """
    (customer, sales_rep, product, job, est, order, crew, slot) = create_scheduled_job(
        declared_sqft=400, measured_sqft=400, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "LVP-M", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 7, "warranty_years": 10},
        crew_overrides={"skill_categories": ["LVP"], "daily_sqft_capacity": 2000},
        start_at="2026-06-12T09:00:00.000Z", end_at="2026-06-12T15:00:00.000Z",
        receive_material=False,
    )
    assert order["status"] == "ORDERED"
    res = api.start_install_slot(slot["id"], TEST_USERS["scheduler_headers"])
    validate_error(res, "ERR_MATERIAL_NOT_RECEIVED", expected_status=409)


def test_slot_start_succeeds_after_material_received(api):
    """PRD §3.9: "the job's material order to be `RECEIVED` ... On a successful
    start the job advances `ACCEPTED → IN_INSTALL` and its `version` is bumped."

    Design: Difficulty/cross_entity_state_dependency/slot_start_requires_material_order_received
    """
    (customer, sales_rep, product, job, est, order, crew, slot) = create_scheduled_job(
        declared_sqft=400, measured_sqft=400, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "LVP-M2", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 0, "warranty_years": 10},
        crew_overrides={"skill_categories": ["LVP"], "daily_sqft_capacity": 2000},
        start_at="2026-06-12T09:00:00.000Z", end_at="2026-06-12T15:00:00.000Z",
        receive_material=True,
    )
    assert order["status"] == "RECEIVED"
    get_success_data(api.start_install_slot(slot["id"], TEST_USERS["scheduler_headers"]))
    job_after = get_success_data(api.get_job(job["id"], TEST_USERS["admin_headers"]))
    assert job_after["status"] == "IN_INSTALL"


# ─── Cross-entity: product discontinue blocked by a live job ──────────

def test_discontinue_blocked_by_live_draft_job(api, admin_headers):
    """PRD §3.1: "That retirement is blocked while any job that references the
    product is still live — that is, while any referencing job sits in `DRAFT`,
    `MEASURED`, `RE_MEASURE`, `ESTIMATED`, `ACCEPTED`, or `IN_INSTALL` ... an
    attempt to discontinue from any state other than `ACTIVE` is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/product_discontinue_blocked_by_live_job
    """
    customer, sales_rep, product, job = create_draft_job(
        declared_sqft=200, clock=None,
        product_overrides={"sku": "TILE-D", "category": "TILE",
                           "material_cost_per_sqft_cents": 500,
                           "labor_rate_per_sqft_cents": 400,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 25})
    assert job["status"] == "DRAFT"
    res = api.discontinue_product(product["id"], admin_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_discontinue_blocked_by_live_accepted_job(api, admin_headers):
    """PRD §3.1: "That retirement is blocked while any job that references the
    product is still live — that is, while any referencing job sits in `DRAFT`,
    `MEASURED`, `RE_MEASURE`, `ESTIMATED`, `ACCEPTED`, or `IN_INSTALL`".

    Design: Difficulty/cross_entity_state_dependency/product_discontinue_blocked_by_live_job
    """
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "TILE-D2", "category": "TILE",
                           "material_cost_per_sqft_cents": 500,
                           "labor_rate_per_sqft_cents": 400,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 25})
    assert job["status"] == "ACCEPTED"
    res = api.discontinue_product(product["id"], admin_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Warranty risk scoring distinct from cost (dual-variant rule) ─────

def test_completed_carpet_job_low_warranty_risk_score(api):
    """PRD §3.9: "The category base contributes 30 for `HARDWOOD`, 15 for `LVP`,
    40 for `TILE`, and 10 for `CARPET`."
    PRD §3.9: "Completion is also the moment the job's `warranty_risk_score` is
    computed and stored — it is null until then."

    Design: Difficulty/dual_variant_calc/warranty_risk_score_on_job_domain_distinct_from_cost
    """
    # CARPET, 0 tear-out, 0 backorders, no re-measure -> base 10 only -> 10.0.
    customer, sales_rep, product, job, crew, slot = create_completed_job(
        declared_sqft=300, measured_sqft=300, tear_out_sqft=0, room_count=2,
        product_overrides={"sku": "CARP-1", "category": "CARPET",
                           "material_cost_per_sqft_cents": 200,
                           "labor_rate_per_sqft_cents": 150,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 10})
    assert job["status"] == "COMPLETED"
    assert job["warranty_risk_score"] == 10.0


def test_warranty_risk_score_null_before_completion(api):
    """PRD §3.9: "Completion is also the moment the job's `warranty_risk_score` is
    computed and stored — it is null until then."

    Design: Difficulty/dual_variant_calc/warranty_risk_score_on_job_domain_distinct_from_cost
    """
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=300, measured_sqft=300, tear_out_sqft=0, room_count=2,
        product_overrides={"sku": "CARP-1B", "category": "CARPET",
                           "material_cost_per_sqft_cents": 200,
                           "labor_rate_per_sqft_cents": 150,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 10})
    assert job["status"] == "ACCEPTED"
    assert job["warranty_risk_score"] is None


# ─── Ready date / backorder push corner instances ─────────────────────

def test_ready_date_is_order_clock_plus_lead_time(api):
    """PRD §3.6: "The order's `expected_ready_date` is computed as the current
    clock plus `lead_time_days` whole calendar days — that is, the clock instant
    plus the lead time multiplied by 86,400 seconds — expressed as an ISO 8601 UTC
    instant with three fractional digits."

    Design: Corner/calculations/ready_date_lead_time_offset
    """
    # Order placed at 2026-06-01 for a 7-day-lead product -> ready 2026-06-08.
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "RD-1", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 7, "warranty_years": 10})
    assert order["expected_ready_date"] == "2026-06-08T00:00:00.000Z"


def test_reorder_pushes_ready_date_from_reorder_clock(api):
    """PRD §3.7: "When stock returns, the scheduler reorders, moving it
    `BACKORDERED → ORDERED` and recomputing `expected_ready_date` as the current
    clock plus the snapshotted `lead_time_days` whole days — pushing the ready date
    out from the moment of reorder."

    Design: Corner/cross_cutting_complexity_layers/backorder_reorder_pushes_ready_date
    """
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "PUSH-1", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 7, "warranty_years": 10})
    sched = TEST_USERS["scheduler_headers"]
    api.backorder_material_order(order["id"], sched)
    set_clock("2026-06-10T00:00:00.000Z")
    order = get_success_data(api.reorder_material_order(order["id"], sched))
    assert order["expected_ready_date"] == "2026-06-17T00:00:00.000Z"
    assert order["status"] == "ORDERED"


def test_material_receive_before_ready_date_rejected(api):
    """PRD §3.7: "Receiving the material moves it `ORDERED → RECEIVED`, but only
    once the clock has caught up: the current clock must be at or after the order's
    `expected_ready_date`. A receipt attempted before the ready date is rejected
    with `ERR_MATERIAL_NOT_READY` (HTTP 409)."

    Design: Corner/state_machines/material_receive_before_ready_date_rejected
    """
    # lead 7d, order 2026-06-01, ready 2026-06-08; receive attempt at 2026-06-07.
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "READY-1", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 7, "warranty_years": 10})
    set_clock("2026-06-07T00:00:00.000Z")
    res = api.receive_material_order(order["id"], TEST_USERS["scheduler_headers"])
    validate_error(res, "ERR_MATERIAL_NOT_READY", expected_status=409)


def test_accept_spawns_material_order_immediately(api):
    """PRD §3.6: "Acceptance forks the workflow by spawning a `MaterialOrder`. The
    new order starts in `ORDERED` status, records its `job_id` and a `product_id`
    copied from the job".

    Design: Corner/consistency_model/accept_spawns_material_order_same_request_immediate
    """
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "IMM2-1", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 7, "warranty_years": 10})
    data, _meta = validate_paginated(
        api.list_job_material_orders(job["id"], TEST_USERS["scheduler_headers"]))
    assert len(data) == 1
    assert data[0]["status"] == "ORDERED"


# ─── Warranty adjudication corner instances ───────────────────────────

def _completed_high_risk_tile_job_with_claim(api):
    """Build a COMPLETED TILE job, re-measured once + 5 backorders + tear_out 300,
    scoring 81.0, with a FILED claim inside the warranty window."""
    customer = register_customer()
    sales_rep = register_sales_rep()
    set_clock("2026-06-01T00:00:00.000Z")
    product = create_product(sku="RISK-1", name="Risk Tile", category="TILE",
                             material_cost_per_sqft_cents=500, labor_rate_per_sqft_cents=400,
                             requires_underlayment=False, underlayment_cost_per_sqft_cents=0,
                             lead_time_days=0, warranty_years=25)
    crew = create_crew(name="Risk Crew", skill_categories=["TILE"], daily_sqft_capacity=5000)
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    cust_headers = make_customer_headers(customer["id"])
    sched = TEST_USERS["scheduler_headers"]
    estm = TEST_USERS["estimator_headers"]

    from test_helpers import create_job_payload
    job = get_success_data(api.create_job(
        create_job_payload(customer["id"], sales_rep["id"], product["id"], declared_sqft=200),
        rep_headers))
    job = get_success_data(api.measure_job(
        job["id"], measure_payload(measured_sqft=200, tear_out_sqft=300, room_count=1), estm))
    est1 = get_success_data(api.create_estimate(
        create_estimate_payload(job["id"], variant="MEASURED"), rep_headers))
    get_success_data(api.issue_estimate(est1["id"], issue_payload(job["version"]), rep_headers))
    get_success_data(api.request_remeasure(job["id"], rep_headers))
    job = get_success_data(api.measure_job(
        job["id"], measure_payload(measured_sqft=200, tear_out_sqft=300, room_count=1), estm))
    est2 = get_success_data(api.create_estimate(
        create_estimate_payload(job["id"], variant="MEASURED"), rep_headers))
    get_success_data(api.issue_estimate(est2["id"], issue_payload(job["version"]), rep_headers))
    get_success_data(api.accept_estimate(est2["id"], cust_headers))
    order = get_material_order_for_job(job["id"])
    for _ in range(5):
        api.backorder_material_order(order["id"], sched)
        order = get_success_data(api.reorder_material_order(order["id"], sched))
    get_success_data(api.receive_material_order(order["id"], sched))
    slot = schedule_slot(job["id"], crew["id"], "2026-06-02T09:00:00.000Z", "2026-06-02T15:00:00.000Z")
    api.start_install_slot(slot["id"], sched)
    api.complete_install_slot(slot["id"], sched)
    job = get_success_data(api.get_job(job["id"], TEST_USERS["admin_headers"]))
    claim = get_success_data(api.create_warranty_claim(
        {"job_id": job["id"], "defect_description": "tile cracking"}, cust_headers))
    return job, claim


def test_warranty_approve_high_risk_rejected(api, admin_headers):
    """PRD §3.11: "Second, the job's `warranty_risk_score` must be at most 70 —
    high-risk installs, those scoring strictly above 70, cannot be auto-approved
    and are referred to manual denial, with an over-threshold approval rejected by
    `ERR_RISK_TOO_HIGH` (HTTP 409)."

    Design: Corner/errors/warranty_approve_high_risk_rejected
    """
    job, claim = _completed_high_risk_tile_job_with_claim(api)
    assert job["warranty_risk_score"] == 81.0
    res = api.approve_warranty_claim(claim["id"], {"resolution_note": "attempt"}, admin_headers)
    validate_error(res, "ERR_RISK_TOO_HIGH", expected_status=409)


def test_warranty_approve_outside_window_rejected(api, admin_headers):
    """PRD §3.11: "First, the claim's `filed_at` must fall within the job's
    warranty window, whose end is the job's completion instant plus the product's
    `warranty_years` whole years; a claim filed after the window has closed is
    rejected with `ERR_WARRANTY_EXPIRED` (HTTP 409)."

    Design: Corner/errors/warranty_approve_expired_window_rejected
    """
    # warranty_years=0 -> window ends at completion; claim filed at 2026-06-03 is outside.
    customer, sales_rep, product, job, claim = create_filed_warranty_claim(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "WIN-1", "category": "CARPET",
                           "material_cost_per_sqft_cents": 100,
                           "labor_rate_per_sqft_cents": 100,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 0},
        file_at="2026-06-03T00:00:00.000Z", defect_description="post window")
    res = api.approve_warranty_claim(claim["id"], {"resolution_note": "attempt"}, admin_headers)
    validate_error(res, "ERR_WARRANTY_EXPIRED", expected_status=409)


def test_warranty_file_on_non_completed_job_rejected(api):
    """PRD §3.11: "A claim may only be filed against a job whose status is
    `COMPLETED`; filing against any other job is rejected with
    `ERR_JOB_NOT_COMPLETED` (HTTP 409)."

    Design: Corner/validations/warranty_file_on_non_completed_job_rejected
    """
    customer, sales_rep, product, job = create_draft_job(
        declared_sqft=200, clock=None,
        product_overrides={"sku": "WARN-1", "category": "LVP", "lead_time_days": 0})
    cust_headers = make_customer_headers(customer["id"])
    res = api.create_warranty_claim(
        {"job_id": job["id"], "defect_description": "early file"}, cust_headers)
    validate_error(res, "ERR_JOB_NOT_COMPLETED", expected_status=409)
