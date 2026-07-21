"""Service bench: quote-vs-invoice dual variant, the QC rework cycle, and the
bench-buffer scheduling conflict."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_service_job, make_started_job, schedule_job,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


def _job(api, job_id, action, **fields):
    payload = {"action": action}
    payload.update(fields)
    return get_success_data(api.transition_service_job(job_id, payload, STAFF))


# ---------------------------------------------------------------------------
# dv_service_quote_vs_final_invoice
# ---------------------------------------------------------------------------
def test_provisional_quote_from_estimated_labor_and_parts(api):
    """PRD 3.5: "on diagnosis the system recomputes the job's
    `provisional_quote_cents` as the floor of `estimated_labor_hours`
    multiplied by the labour rate of 6,000 cents per hour, plus
    `estimated_parts_cents`."

    Design: Difficulty/dual_variant_calc/dv_service_quote_vs_final_invoice
    """
    job = make_started_job(api, job_type="REPAIR",
                           estimated_labor_hours=2, estimated_parts_cents=3000)
    # floor(2*6000) + 3000 = 15000
    assert job["provisional_quote_cents"] == 15000


def test_final_invoice_adds_actuals_and_rework_surcharge(api):
    """PRD 3.5: "on completion the system recomputes the job's
    `final_invoice_cents` as the floor of `actual_labor_hours` multiplied by the
    6,000-cents-per-hour labour rate, plus `actual_parts_cents`, plus
    `rework_count` multiplied by a rework surcharge of 2,500 cents per rework
    loop."

    Design: Difficulty/dual_variant_calc/dv_service_quote_vs_final_invoice
    """
    job = make_started_job(api, job_type="REPAIR",
                           estimated_labor_hours=2, estimated_parts_cents=3000)
    _job(api, job["id"], "QC")
    _job(api, job["id"], "REWORK")
    _job(api, job["id"], "QC")
    _job(api, job["id"], "READY")
    completed = _job(api, job["id"], "COMPLETE",
                     actual_labor_hours=3, actual_parts_cents=4000)
    # floor(3*6000) + 4000 + 1*2500 = 24500
    assert completed["final_invoice_cents"] == 24500
    assert completed["rework_count"] == 1


# ---------------------------------------------------------------------------
# nl_service_qc_rework_cycle
# ---------------------------------------------------------------------------
def test_two_rework_loops_accumulate_rework_count(api):
    """PRD 3.5: "From QC the job either fails and is sent back for rework, moving
    `QC → IN_PROGRESS` and incrementing `rework_count` by 1, or passes and is
    readied, moving `QC → READY`. The rework loop may repeat, and each pass
    through it accumulates one more unit of `rework_count`."

    Design: Difficulty/non_linear_state_machine/nl_service_qc_rework_cycle
    """
    job = make_started_job(api, job_type="BUILD",
                           estimated_labor_hours=1, estimated_parts_cents=0,
                           bench_code="B9",
                           slot_start="2026-07-03T09:00:00Z",
                           slot_end="2026-07-03T10:00:00Z")
    _job(api, job["id"], "QC")
    _job(api, job["id"], "REWORK")
    _job(api, job["id"], "QC")
    reworked = _job(api, job["id"], "REWORK")
    assert reworked["rework_count"] == 2


def test_rework_returns_job_to_in_progress(api):
    """PRD 3.5: "From QC the job either fails and is sent back for rework, moving
    `QC → IN_PROGRESS` and incrementing `rework_count` by 1".

    Design: Difficulty/non_linear_state_machine/nl_service_qc_rework_cycle
    """
    job = make_started_job(api, job_type="BUILD",
                           estimated_labor_hours=1, estimated_parts_cents=0,
                           bench_code="B9",
                           slot_start="2026-07-03T09:00:00Z",
                           slot_end="2026-07-03T10:00:00Z")
    _job(api, job["id"], "QC")
    _job(api, job["id"], "REWORK")
    _job(api, job["id"], "QC")
    reworked = _job(api, job["id"], "REWORK")
    assert reworked["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# rt_service_bench_buffer_overlap
# ---------------------------------------------------------------------------
def test_bench_slot_within_buffer_rejected(api):
    """PRD 2.8: "must sit at least `SERVICE_BUFFER_MINUTES` (30 minutes) away
    from every other slot already booked on the same `bench_code` — that is, the
    gap between the new slot and every existing neighbour on that bench must be
    30 minutes or more; a slot that is invalid or closer than 30 minutes to a
    neighbour is rejected with `ERR_BENCH_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rt_service_bench_buffer_overlap
    """
    j1 = make_service_job(api, job_type="REPAIR")
    j2 = make_service_job(api, job_type="REPAIR")
    schedule_job(api, j1["id"], "B1", "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z")
    resp = api.transition_service_job(j2["id"], {
        "action": "SCHEDULE", "bench_code": "B1",
        "slot_start": "2026-07-02T10:20:00Z", "slot_end": "2026-07-02T11:00:00Z"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_BENCH_CONFLICT.value)


def test_bench_slot_exactly_buffer_apart_allowed(api):
    """PRD 2.8: "the gap between the new slot and every existing neighbour on
    that bench must be 30 minutes or more".

    Design: Difficulty/resource_temporal_overlap/rt_service_bench_buffer_overlap
    """
    j1 = make_service_job(api, job_type="REPAIR")
    j2 = make_service_job(api, job_type="REPAIR")
    schedule_job(api, j1["id"], "B1", "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z")
    # Exactly 30-minute gap after the first slot's end -> allowed.
    scheduled = schedule_job(api, j2["id"], "B1",
                             "2026-07-02T10:30:00Z", "2026-07-02T11:00:00Z")
    assert scheduled["bench_code"] == "B1"
