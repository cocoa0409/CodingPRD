"""Install scheduling: crew daily-capacity boundary, buffered-crew and
single-occupancy temporal overlaps, capacity release on slot cancel, and the
slot-creation validation precedence pairs.

Billable square footage values are copied verbatim from the design indices
(CARPET 5% waste: 285.71 -> 300.0, 571.43 -> 600.0, 380 -> 399.0).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_install_slot_payload, create_install_crew_payload,
    create_accepted_job, create_accepted_job_material_received,
    add_accepted_job_for_customer, create_crew, schedule_slot,
    make_sales_rep_headers, make_customer_headers,
    TEST_USERS,
)

CARPET_CAP = {"sku": None, "category": "CARPET",
              "material_cost_per_sqft_cents": 100, "labor_rate_per_sqft_cents": 100,
              "requires_underlayment": False, "underlayment_cost_per_sqft_cents": 0,
              "lead_time_days": 0, "warranty_years": 5}


def _carpet_product(sku):
    p = dict(CARPET_CAP)
    p["sku"] = sku
    return p


# ─── Crew daily-capacity inclusive boundary ───────────────────────────

def test_capacity_boundary_exactly_at_capacity_admitted(api):
    """PRD §3.8: "the existing day load plus the candidate's `scheduled_sqft` must
    be less than or equal to the crew's `daily_sqft_capacity` — the boundary is
    inclusive, so a load exactly equal to capacity is admitted and anything beyond
    it is rejected with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/crew_capacity_inclusive_boundary_on_install_slot
    """
    # Crew cap 600; two CARPET jobs each billable 300.0; load reaches exactly 600.
    customer, sales_rep, product, job1, est1, order1 = create_accepted_job_material_received(
        declared_sqft=290, measured_sqft=285.71, tear_out_sqft=0, room_count=1,
        product_overrides=_carpet_product("CARP-CAP"))
    assert est1["billable_sqft"] == 300.0
    crew = create_crew(skill_categories=["CARPET"], daily_sqft_capacity=600)
    schedule_slot(job1["id"], crew["id"], "2026-06-10T09:00:00.000Z", "2026-06-10T11:00:00.000Z")

    job2, est2, order2 = add_accepted_job_for_customer(
        customer, sales_rep, product, declared_sqft=290,
        measured_sqft=285.71, tear_out_sqft=0, room_count=1)
    assert est2["billable_sqft"] == 300.0
    res = api.create_install_slot(
        create_install_slot_payload(job2["id"], crew["id"],
                                    start_at="2026-06-10T12:00:00.000Z",
                                    end_at="2026-06-10T16:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    slot2 = validate_success(res, 201)
    assert slot2["status"] == "SCHEDULED"


def test_capacity_boundary_one_over_capacity_rejected(api):
    """PRD §3.8: "anything beyond it is rejected with `ERR_CREW_CAPACITY_EXCEEDED`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/crew_capacity_inclusive_boundary_on_install_slot
    """
    # Crew cap 599; a single 300.0 + second 300.0 = 600 > 599 -> rejected.
    customer, sales_rep, product, job1, est1, order1 = create_accepted_job_material_received(
        declared_sqft=290, measured_sqft=285.71, tear_out_sqft=0, room_count=1,
        product_overrides=_carpet_product("CARP-OVER"))
    crew = create_crew(skill_categories=["CARPET"], daily_sqft_capacity=599)
    schedule_slot(job1["id"], crew["id"], "2026-06-10T09:00:00.000Z", "2026-06-10T11:00:00.000Z")
    job2, est2, order2 = add_accepted_job_for_customer(
        customer, sales_rep, product, declared_sqft=290,
        measured_sqft=285.71, tear_out_sqft=0, room_count=1)
    res = api.create_install_slot(
        create_install_slot_payload(job2["id"], crew["id"],
                                    start_at="2026-06-10T12:00:00.000Z",
                                    end_at="2026-06-10T16:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(res, "ERR_CREW_CAPACITY_EXCEEDED", expected_status=409)


# ─── Crew buffered-adjacency temporal overlap ─────────────────────────

def test_crew_buffer_expanded_overlap_rejected(api):
    """PRD §3.8: "the candidate's half-open interval from `start_at` up to
    `end_at` must not overlap any of the crew's `SCHEDULED` slots once each
    existing slot is expanded by the crew's `buffer_minutes` on each side, so that
    travel and cleanup time is honored; a conflict is rejected with
    `ERR_CREW_TIME_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/crew_slot_buffer_expanded_overlap_rejected
    """
    # Crew buffer 30; slot1 09:00-12:00 -> buffered [08:30,12:30); candidate 12:15-14:00 collides.
    customer, sales_rep, product, job1, est1, order1 = create_accepted_job(
        declared_sqft=300, measured_sqft=300, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "LVP-BUF", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 0, "warranty_years": 10})
    crew = create_crew(skill_categories=["LVP"], daily_sqft_capacity=5000, buffer_minutes=30)
    schedule_slot(job1["id"], crew["id"], "2026-06-10T09:00:00.000Z", "2026-06-10T12:00:00.000Z")
    job2, est2, order2 = add_accepted_job_for_customer(
        customer, sales_rep, product, declared_sqft=300,
        measured_sqft=300, tear_out_sqft=0, room_count=1)
    res = api.create_install_slot(
        create_install_slot_payload(job2["id"], crew["id"],
                                    start_at="2026-06-10T12:15:00.000Z",
                                    end_at="2026-06-10T14:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(res, "ERR_CREW_TIME_CONFLICT", expected_status=409)


def test_crew_slot_outside_buffer_window_admitted(api):
    """PRD §3.8: "the candidate's half-open interval from `start_at` up to
    `end_at` must not overlap any of the crew's `SCHEDULED` slots once each
    existing slot is expanded by the crew's `buffer_minutes` on each side".

    Design: Difficulty/resource_temporal_overlap/crew_slot_buffer_expanded_overlap_rejected
    """
    # Slot1 09:00-12:00, buffer 30 -> [08:30,12:30); candidate 12:30-14:00 is clear.
    customer, sales_rep, product, job1, est1, order1 = create_accepted_job(
        declared_sqft=300, measured_sqft=300, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "LVP-BUF2", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 0, "warranty_years": 10})
    crew = create_crew(skill_categories=["LVP"], daily_sqft_capacity=5000, buffer_minutes=30)
    schedule_slot(job1["id"], crew["id"], "2026-06-10T09:00:00.000Z", "2026-06-10T12:00:00.000Z")
    job2, est2, order2 = add_accepted_job_for_customer(
        customer, sales_rep, product, declared_sqft=300,
        measured_sqft=300, tear_out_sqft=0, room_count=1)
    res = api.create_install_slot(
        create_install_slot_payload(job2["id"], crew["id"],
                                    start_at="2026-06-10T12:30:00.000Z",
                                    end_at="2026-06-10T14:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    slot = validate_success(res, 201)
    assert slot["status"] == "SCHEDULED"


# ─── Job single-occupancy closed-interval overlap ─────────────────────

def test_job_single_occupancy_closed_interval_overlap_rejected(api):
    """PRD §3.8: "The job must not already have another `SCHEDULED` install slot
    whose closed interval shares any instant with the candidate's closed interval
    — a single job cannot be installed in two places at once, treating both
    endpoints as inclusive — and a collision here is rejected with
    `ERR_JOB_SLOT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/job_single_occupancy_closed_interval_overlap_rejected
    """
    # One job, two crews; slot1 09:00-12:00 on crew A; slot2 11:00-13:00 on crew B shares [11:00,12:00].
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=290, measured_sqft=285.71, tear_out_sqft=0, room_count=1,
        product_overrides=_carpet_product("CARP-JOB"))
    crew_a = create_crew(name="Crew A", skill_categories=["CARPET"], daily_sqft_capacity=5000)
    crew_b = create_crew(name="Crew B", skill_categories=["CARPET"], daily_sqft_capacity=5000)
    schedule_slot(job["id"], crew_a["id"], "2026-06-10T09:00:00.000Z", "2026-06-10T12:00:00.000Z")
    res = api.create_install_slot(
        create_install_slot_payload(job["id"], crew_b["id"],
                                    start_at="2026-06-10T11:00:00.000Z",
                                    end_at="2026-06-10T13:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(res, "ERR_JOB_SLOT_OVERLAP", expected_status=409)


def test_job_two_disjoint_slots_admitted(api):
    """PRD §3.8: "The job must not already have another `SCHEDULED` install slot
    whose closed interval shares any instant with the candidate's closed interval".

    Design: Difficulty/resource_temporal_overlap/job_single_occupancy_closed_interval_overlap_rejected
    """
    # Same job; slot1 09:00-11:00 on crew A; slot2 13:00-15:00 on crew B shares no instant.
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=290, measured_sqft=285.71, tear_out_sqft=0, room_count=1,
        product_overrides=_carpet_product("CARP-JOB2"))
    crew_a = create_crew(name="Crew A2", skill_categories=["CARPET"], daily_sqft_capacity=5000)
    crew_b = create_crew(name="Crew B2", skill_categories=["CARPET"], daily_sqft_capacity=5000)
    schedule_slot(job["id"], crew_a["id"], "2026-06-10T09:00:00.000Z", "2026-06-10T11:00:00.000Z")
    res = api.create_install_slot(
        create_install_slot_payload(job["id"], crew_b["id"],
                                    start_at="2026-06-10T13:00:00.000Z",
                                    end_at="2026-06-10T15:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    slot = validate_success(res, 201)
    assert slot["status"] == "SCHEDULED"


# ─── Compensating invariant: slot cancel restores crew capacity ───────

def test_slot_cancel_restores_capacity_for_next_slot(api):
    """PRD §3.8: "A scheduler may cancel a `SCHEDULED` slot, moving it
    `SCHEDULED → CANCELLED`, which releases its `scheduled_sqft` back to the
    crew's day capacity — the crew's day load is recomputed from its remaining
    `SCHEDULED` slots".

    Design: Difficulty/compensating_invariant/slot_cancel_restores_crew_day_capacity
    """
    # Crew cap 600. Job1 billable 399.0 scheduled then cancelled; job2 billable 600.0 then fits.
    customer, sales_rep, product, job1, est1, order1 = create_accepted_job_material_received(
        declared_sqft=390, measured_sqft=380, tear_out_sqft=0, room_count=1,
        product_overrides=_carpet_product("CARP-RES"))
    assert est1["billable_sqft"] == 399.0
    crew = create_crew(skill_categories=["CARPET"], daily_sqft_capacity=600)
    slot1 = schedule_slot(job1["id"], crew["id"], "2026-06-10T08:00:00.000Z", "2026-06-10T10:00:00.000Z")
    get_success_data(api.cancel_install_slot(slot1["id"], TEST_USERS["scheduler_headers"]))

    job2, est2, order2 = add_accepted_job_for_customer(
        customer, sales_rep, product, declared_sqft=580,
        measured_sqft=571.43, tear_out_sqft=0, room_count=1)
    assert est2["billable_sqft"] == 600.0
    res = api.create_install_slot(
        create_install_slot_payload(job2["id"], crew["id"],
                                    start_at="2026-06-10T12:00:00.000Z",
                                    end_at="2026-06-10T16:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    slot2 = validate_success(res, 201)
    assert slot2["status"] == "SCHEDULED"


def test_cancelled_slot_status_is_cancelled(api):
    """PRD §3.8: "A scheduler may cancel a `SCHEDULED` slot, moving it
    `SCHEDULED → CANCELLED`".

    Design: Difficulty/compensating_invariant/slot_cancel_restores_crew_day_capacity
    """
    customer, sales_rep, product, job1, est1, order1 = create_accepted_job_material_received(
        declared_sqft=390, measured_sqft=380, tear_out_sqft=0, room_count=1,
        product_overrides=_carpet_product("CARP-RES2"))
    crew = create_crew(skill_categories=["CARPET"], daily_sqft_capacity=600)
    slot1 = schedule_slot(job1["id"], crew["id"], "2026-06-10T08:00:00.000Z", "2026-06-10T10:00:00.000Z")
    cancelled = get_success_data(api.cancel_install_slot(slot1["id"], TEST_USERS["scheduler_headers"]))
    assert cancelled["status"] == "CANCELLED"


# ─── Validation precedence pair: state before capacity ────────────────

def test_unaccepted_job_over_capacity_returns_job_not_accepted(api):
    """PRD §3.12: "On slot creation the documented order is job-accepted, then
    crew-skill, then interval well-formedness, then job self-overlap, then crew
    buffered conflict, then daily capacity."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_capacity_on_install_slot
    """
    # DRAFT job + tiny-capacity crew: both job-not-accepted (12) and capacity (17) would fail.
    from test_helpers import create_draft_job
    customer, sales_rep, product, job = create_draft_job(
        declared_sqft=500, clock=None,
        product_overrides={"sku": "LVP-P", "category": "LVP",
                           "material_cost_per_sqft_cents": 300,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 30,
                           "lead_time_days": 0, "warranty_years": 10})
    crew = create_crew(skill_categories=["LVP"], daily_sqft_capacity=100)
    res = api.create_install_slot(
        create_install_slot_payload(job["id"], crew["id"],
                                    start_at="2026-06-05T09:00:00.000Z",
                                    end_at="2026-06-05T15:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(res, "ERR_JOB_NOT_ACCEPTED", expected_status=409)


def test_accepted_job_over_capacity_returns_capacity_exceeded(api):
    """PRD §3.12: "On slot creation the documented order is job-accepted, then
    crew-skill, then interval well-formedness, then job self-overlap, then crew
    buffered conflict, then daily capacity."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_capacity_on_install_slot
    """
    # Accepted job (job-accepted check passes) but billable 300 on a 100-cap crew -> capacity error.
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=290, measured_sqft=285.71, tear_out_sqft=0, room_count=1,
        product_overrides=_carpet_product("CARP-CAPCHK"))
    crew = create_crew(skill_categories=["CARPET"], daily_sqft_capacity=100)
    res = api.create_install_slot(
        create_install_slot_payload(job["id"], crew["id"],
                                    start_at="2026-06-05T09:00:00.000Z",
                                    end_at="2026-06-05T15:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(res, "ERR_CREW_CAPACITY_EXCEEDED", expected_status=409)


# ─── Validation precedence pair: skill before interval ────────────────

def test_skill_mismatch_with_degenerate_interval_returns_skill_mismatch(api):
    """PRD §3.12: "On slot creation the documented order is job-accepted, then
    crew-skill, then interval well-formedness".

    Design: Difficulty/priority_pair_validation_conflict/referential_skill_beats_temporal_interval_on_install_slot
    """
    # ACCEPTED TILE job; CARPET-only crew (skill fails) AND start_at == end_at (interval fails).
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=300, measured_sqft=300, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "TILE-S", "category": "TILE",
                           "material_cost_per_sqft_cents": 500,
                           "labor_rate_per_sqft_cents": 400,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 25})
    crew = create_crew(skill_categories=["CARPET"], daily_sqft_capacity=5000)
    res = api.create_install_slot(
        create_install_slot_payload(job["id"], crew["id"],
                                    start_at="2026-06-05T09:00:00.000Z",
                                    end_at="2026-06-05T09:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(res, "ERR_CREW_SKILL_MISMATCH", expected_status=409)


def test_skill_matched_with_degenerate_interval_returns_invalid_interval(api):
    """PRD §3.8: "Then `start_at` must be strictly before `end_at`, with both
    present; an inverted or degenerate interval is rejected with
    `ERR_INVALID_INTERVAL` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/referential_skill_beats_temporal_interval_on_install_slot
    """
    # ACCEPTED TILE job; TILE-skilled crew (skill passes) but start_at == end_at -> interval error.
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=300, measured_sqft=300, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "TILE-S2", "category": "TILE",
                           "material_cost_per_sqft_cents": 500,
                           "labor_rate_per_sqft_cents": 400,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 25})
    crew = create_crew(skill_categories=["TILE"], daily_sqft_capacity=5000)
    res = api.create_install_slot(
        create_install_slot_payload(job["id"], crew["id"],
                                    start_at="2026-06-05T09:00:00.000Z",
                                    end_at="2026-06-05T09:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=422)


# ─── Slot corner instances ────────────────────────────────────────────

def test_install_slot_inverted_interval_rejected(api):
    """PRD §3.8: "Then `start_at` must be strictly before `end_at`, with both
    present; an inverted or degenerate interval is rejected with
    `ERR_INVALID_INTERVAL` (HTTP 422)."

    Design: Corner/validations/install_slot_invalid_interval_rejected
    """
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides=_carpet_product("INTV-1"))
    crew = create_crew(skill_categories=["CARPET"], daily_sqft_capacity=5000)
    res = api.create_install_slot(
        create_install_slot_payload(job["id"], crew["id"],
                                    start_at="2026-06-10T15:00:00.000Z",
                                    end_at="2026-06-10T09:00:00.000Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=422)


def test_crew_install_slots_reverse_list(api):
    """PRD §4 (routing): the crew's install-slots list endpoint exists, and PRD
    §3.8: "Scheduling an `InstallSlot` ties a job to a crew over a time window".

    Design: Corner/endpoints/install_slots_filtered_by_crew_reverse_list
    """
    customer, sales_rep, product, job, est, order = create_accepted_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides=_carpet_product("CREW-1"))
    crew = create_crew(skill_categories=["CARPET"], daily_sqft_capacity=5000)
    slot = schedule_slot(job["id"], crew["id"], "2026-06-10T09:00:00.000Z", "2026-06-10T12:00:00.000Z")
    data, _meta = validate_paginated(
        api.list_crew_install_slots(crew["id"], TEST_USERS["scheduler_headers"]))
    assert len(data) == 1
    assert data[0]["id"] == slot["id"]
