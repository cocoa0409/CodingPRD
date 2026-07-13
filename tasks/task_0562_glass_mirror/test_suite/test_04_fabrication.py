"""Fabrication: tempering batches on furnaces — parallel job axes, the empty-batch and
capacity edges, furnace window/cooldown conflicts, and reservation conservation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, create_tempering_batch_payload,
)
from test_helpers import fixtures as fx


# ==========================================================================
# non_linear_state_machine / job_parallel_fabrication_and_install_axes
# ==========================================================================
def test_batch_completion_advances_fabrication_and_install_axes(api):
    """PRD §3.5: "If, after this, every line item of the job is `FABRICATED`, the job's
    `fabrication_status` bubbles from `IN_FABRICATION` to `COMPLETE`, which in turn bubbles
    the `install_status` from `NOT_READY` to `READY`."

    Design: Difficulty/non_linear_state_machine/job_parallel_fabrication_and_install_axes
    """
    ctx = fx.setup_fabricated_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    job = validate_success(api.get_job(ctx["job_id"], TEST_USERS["shop_admin_headers"]), 200)
    assert job["fabrication_status"] == "COMPLETE", job["fabrication_status"]
    assert job["install_status"] == "READY", job["install_status"]
    assert job["status"] == "ACTIVE", job["status"]


def test_install_completion_bubbles_job_to_closed(api):
    """PRD §3.6: "Completing a `SCHEDULED` appointment (permitted only from `SCHEDULED`, else
    `ERR_INVALID_STATE`) moves it to `COMPLETED`, advances each of the job's `FABRICATED`
    line items to `INSTALLED`, and moves the job's `install_status` from `SCHEDULED` to
    `INSTALLED`. If the job's `fabrication_status` is already `COMPLETE` at that moment, the
    job's lifecycle `status` bubbles from `ACTIVE` to `CLOSED`."

    Design: Difficulty/non_linear_state_machine/job_parallel_fabrication_and_install_axes
    """
    ctx = fx.setup_installed_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    job = validate_success(api.get_job(ctx["job_id"], TEST_USERS["shop_admin_headers"]), 200)
    assert job["fabrication_status"] == "COMPLETE", job["fabrication_status"]
    assert job["install_status"] == "INSTALLED", job["install_status"]
    assert job["status"] == "CLOSED", job["status"]


# ==========================================================================
# boundary_precision_check / empty_batch_zero_fabricating_lines
# ==========================================================================
def test_second_batch_with_no_fabricating_lines_rejected(api):
    """PRD §3.5: "If no line remains in `FABRICATING`, the batch would be empty and the
    request is rejected with `ERR_EMPTY_BATCH` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/empty_batch_zero_fabricating_lines
    """
    ctx = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    furnace = fx.create_furnace(api, max_batch_sqft=500)
    batch1 = fx.create_batch(api, ctx["job_id"], furnace["id"],
                             start="2026-06-10T09:00:00Z", end="2026-06-10T11:00:00Z")
    fx.complete_batch(api, batch1["id"])  # only line now FABRICATED
    resp = api.create_tempering_batch(
        create_tempering_batch_payload(ctx["job_id"], furnace["id"],
                                       "2026-06-11T09:00:00Z", "2026-06-11T11:00:00Z"),
        TEST_USERS["fabricator_headers"])
    validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH)


def test_first_batch_totals_fabricating_area(api):
    """PRD §3.5: "At creation the batch's `total_sqft` is computed as the sum, over the job's
    line items currently in `FABRICATING` status, of `billable_sqft` multiplied by
    `quantity`."

    Design: Difficulty/boundary_precision_check/empty_batch_zero_fabricating_lines
    """
    ctx = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    furnace = fx.create_furnace(api, max_batch_sqft=500)
    batch = validate_success(api.create_tempering_batch(
        create_tempering_batch_payload(ctx["job_id"], furnace["id"],
                                       "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z"),
        TEST_USERS["fabricator_headers"]), 201)
    assert batch["total_sqft"] == 15.0, batch["total_sqft"]
    assert batch["status"] == "SCHEDULED", batch["status"]


# ==========================================================================
# resource_temporal_overlap / furnace_batch_cooldown_buffer_conflict
# ==========================================================================
def test_furnace_batch_within_cooldown_buffer_rejected(api):
    """PRD §3.5: "first, the batch window must not collide with another `SCHEDULED` batch on
    the same furnace once the furnace's `cooldown_minutes` buffer is added after each batch
    window, else `ERR_FURNACE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/furnace_batch_cooldown_buffer_conflict
    """
    job1 = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    job2 = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    furnace = fx.create_furnace(api, max_batch_sqft=500, cooldown_minutes=60)
    fx.create_batch(api, job1["job_id"], furnace["id"],
                    start="2026-06-10T09:00:00Z", end="2026-06-10T11:00:00Z")
# 11:30 start is only 30 min after the 11:00 end — inside the 60-min cooldown buffer.
    resp = api.create_tempering_batch(
        create_tempering_batch_payload(job2["job_id"], furnace["id"],
                                       "2026-06-10T11:30:00Z", "2026-06-10T13:00:00Z"),
        TEST_USERS["fabricator_headers"])
    validate_error(resp, ApiErrorId.ERR_FURNACE_WINDOW_CONFLICT)


def test_furnace_batch_after_full_cooldown_allowed(api):
    """PRD §3.5: "first, the batch window must not collide with another `SCHEDULED` batch on
    the same furnace once the furnace's `cooldown_minutes` buffer is added after each batch
    window, else `ERR_FURNACE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/furnace_batch_cooldown_buffer_conflict
    """
    job1 = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    job2 = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    furnace = fx.create_furnace(api, max_batch_sqft=500, cooldown_minutes=60)
    fx.create_batch(api, job1["job_id"], furnace["id"],
                    start="2026-06-10T09:00:00Z", end="2026-06-10T11:00:00Z")
# 12:00 start is exactly 60 min after the 11:00 end — the buffer is satisfied.
    batch2 = validate_success(api.create_tempering_batch(
        create_tempering_batch_payload(job2["job_id"], furnace["id"],
                                       "2026-06-10T12:00:00Z", "2026-06-10T14:00:00Z"),
        TEST_USERS["fabricator_headers"]), 201)
    assert batch2["status"] == "SCHEDULED", batch2["status"]


# ==========================================================================
# compensating_invariant / furnace_reserved_sqft_conserved_schedule_then_cancel
# ==========================================================================
def test_furnace_reserved_released_on_batch_cancel(api):
    """PRD §3.5: "On success the batch enters `SCHEDULED` status, the furnace's
    `reserved_sqft` increases by the batch's `total_sqft`, and if this is the job's first
    batch its `fabrication_status` advances from `PENDING` to `IN_FABRICATION`."
    PRD §3.5: "Cancelling a `SCHEDULED` batch (again only from `SCHEDULED`) moves it to
    `CANCELLED` and, as compensation, releases its `total_sqft` from the furnace's
    `reserved_sqft`."

    Design: Difficulty/compensating_invariant/furnace_reserved_sqft_conserved_schedule_then_cancel
    """
    ctx = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    furnace = fx.create_furnace(api, max_batch_sqft=500)
    batch = fx.create_batch(api, ctx["job_id"], furnace["id"])
    assert batch["total_sqft"] == 15.0, batch["total_sqft"]
    reserved = validate_success(api.get_furnace(furnace["id"], TEST_USERS["fabricator_headers"]), 200)
    assert reserved["reserved_sqft"] == 15.0, reserved["reserved_sqft"]

    validate_success(api.cancel_tempering_batch(batch["id"], TEST_USERS["fabricator_headers"]), 200)
    after = validate_success(api.get_furnace(furnace["id"], TEST_USERS["fabricator_headers"]), 200)
    assert after["reserved_sqft"] == 0, after["reserved_sqft"]


def test_furnace_reserved_released_on_batch_complete(api):
    """PRD §3.5: "Completing a `SCHEDULED` batch (permitted only from `SCHEDULED`, else
    `ERR_INVALID_STATE`) moves it to `DONE`, advances each of the job's `FABRICATING` line
    items to `FABRICATED`, and releases the batch's `total_sqft` back from the furnace's
    `reserved_sqft`."

    Design: Difficulty/compensating_invariant/furnace_reserved_sqft_conserved_schedule_then_cancel
    """
    ctx = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    furnace = fx.create_furnace(api, max_batch_sqft=500)
    batch = fx.create_batch(api, ctx["job_id"], furnace["id"])
    reserved = validate_success(api.get_furnace(furnace["id"], TEST_USERS["fabricator_headers"]), 200)
    assert reserved["reserved_sqft"] == 15.0, reserved["reserved_sqft"]

    fx.complete_batch(api, batch["id"])
    after = validate_success(api.get_furnace(furnace["id"], TEST_USERS["fabricator_headers"]), 200)
    assert after["reserved_sqft"] == 0, after["reserved_sqft"]


# ==========================================================================
# state_machines / complete_batch_twice_returns_invalid_state
# ==========================================================================
def test_complete_already_done_batch_rejected(api):
    """PRD §3.5: "Completing a `SCHEDULED` batch (permitted only from `SCHEDULED`, else
    `ERR_INVALID_STATE`) moves it to `DONE`, advances each of the job's `FABRICATING` line
    items to `FABRICATED`, and releases the batch's `total_sqft` back from the furnace's
    `reserved_sqft`."

    Design: Corner/state_machines/complete_batch_twice_returns_invalid_state
    """
    ctx = fx.setup_fabricated_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    resp = api.complete_tempering_batch(ctx["batch_id"], TEST_USERS["fabricator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# validations / batch_capacity_exceeded_returns_error
# ==========================================================================
def test_batch_over_furnace_capacity_rejected(api):
    """PRD §3.5: "then the batch's `total_sqft` must not exceed the furnace's
    `max_batch_sqft`, else `ERR_BATCH_CAPACITY_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/batch_capacity_exceeded_returns_error
    """
    ctx = fx.setup_accepted_job(api, tier="SILVER", lines=[{
        "product_type": "SHOWER_ENCLOSURE", "glass_type": "TEMPERED", "thickness_mm": 10,
        "width_in": 60, "height_in": 72, "quantity": 3,  # 30 sqft/pane * 3 = 90 sqft
    }])
    furnace = fx.create_furnace(api, max_batch_sqft=50)
    resp = api.create_tempering_batch(
        create_tempering_batch_payload(ctx["job_id"], furnace["id"],
                                       "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z"),
        TEST_USERS["fabricator_headers"])
    validate_error(resp, ApiErrorId.ERR_BATCH_CAPACITY_EXCEEDED)
