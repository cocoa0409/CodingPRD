"""Electrician dispatch booking: daily capacity boundary, window overlap vs adjacency,
out-of-territory vs overlap priority, and suspended-electrician rejection.

Translates difficulty rules boundary_precision_check (capacity branch),
resource_temporal_overlap, priority_pair_validation_conflict (instance 2), plus the
suspended-booking and window-validation corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_quoted_job,
    setup_compliance_cleared,
    create_electrician,
    create_dispatch_assignment_payload,
    create_interconnection_request_payload,
    make_homeowner_headers,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
UTILITY = TEST_USERS["utility_reviewer_headers"]


def _quoted_job_for_property(ctx, prop_id, charger_sku):
    """Create a second QUOTED job on an existing property (reuses homeowner)."""
    job = get_success_data(api_client.create_install_job(
        {"property_id": prop_id, "charger_product_sku": charger_sku}, COORDINATOR))
    sa = get_success_data(api_client.create_site_assessment(
        {"property_id": prop_id, "install_job_id": job["id"],
         "assessment_method": "LOAD_STUDY_220_87", "declared_fixed_appliance_va": 0,
         "max_measured_demand_va": 7200}, COORDINATOR))
    get_success_data(api_client.accept_site_assessment(sa["id"], COORDINATOR))
    quote = get_success_data(api_client.create_quote(
        {"install_job_id": job["id"], "labor_cents": 120000, "parts_line_cents": [60000, 5000]},
        COORDINATOR))
    get_success_data(api_client.send_quote(quote["id"], COORDINATOR))
    cur = get_success_data(api_client.get_install_job(job["id"], COORDINATOR))
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.accept_quote(
        quote["id"], {"expected_install_job_version": cur["version"]}, ho_headers))
    return job


# ─── Daily capacity strict-< boundary ────────────────────────────────────

def test_third_booking_at_capacity_rejected():
    """PRD §3.6: "counting that electrician's assignments on the same `window_date` whose
    status is `BOOKED` or `EN_ROUTE`, the booking is allowed only when that count is
    strictly fewer than the electrician's `max_daily_jobs`. A count equal to the cap is at
    capacity and is rejected with `ERR_DAILY_CAPACITY_EXCEEDED` (HTTP 409)"

    Design: Difficulty/boundary_precision_check/electrician_third_booking_at_capacity_rejected
    """
    ctx = setup_quoted_job()
    el = create_electrician(max_daily_jobs=2)
    date = "2026-05-05T00:00:00Z"
    # First booking on ctx's quoted job
    get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"], window_date=date,
                                            window_start_minute=480, window_end_minute=600),
        COORDINATOR))
    # Second booking on a fresh quoted job (same electrician, same date)
    job_b = _quoted_job_for_property(ctx, ctx["property"]["id"], ctx["charger"]["sku"])
    get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(job_b["id"], el["id"], window_date=date,
                                            window_start_minute=660, window_end_minute=780),
        COORDINATOR))
    # Third booking -> at capacity (count==2) -> rejected
    job_c = _quoted_job_for_property(ctx, ctx["property"]["id"], ctx["charger"]["sku"])
    res = api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(job_c["id"], el["id"], window_date=date,
                                            window_start_minute=840, window_end_minute=960),
        COORDINATOR)
    validate_error(res, "ERR_DAILY_CAPACITY_EXCEEDED")


def test_second_booking_below_capacity_allowed():
    """PRD §3.6: "a count one below the cap is still allowed."

    Design: Difficulty/boundary_precision_check/electrician_third_booking_at_capacity_rejected
    """
    ctx = setup_quoted_job()
    el = create_electrician(max_daily_jobs=2)
    date = "2026-05-05T00:00:00Z"
    get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"], window_date=date,
                                            window_start_minute=480, window_end_minute=600),
        COORDINATOR))
    job_b = _quoted_job_for_property(ctx, ctx["property"]["id"], ctx["charger"]["sku"])
    # count==1 (< 2) -> allowed
    res = validate_success(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(job_b["id"], el["id"], window_date=date,
                                            window_start_minute=660, window_end_minute=780),
        COORDINATOR), 201)
    assert res["status"] == "BOOKED"


# ─── Window overlap (half-open, strict) ──────────────────────────────────

def test_overlapping_windows_rejected():
    """PRD §3.6: "The new window must not overlap any non-cancelled assignment already held
    by the same electrician on the same `window_date`; overlap is evaluated on the half-open
    interval (two windows overlap when one starts before the other ends and vice versa, with
    a shared endpoint not counting as overlap), and a conflict is rejected with
    `ERR_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/electrician_overlapping_windows_rejected
    """
    ctx = setup_quoted_job()
    el = create_electrician()
    date = "2026-05-07T00:00:00Z"
    get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"], window_date=date,
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR))
    job_b = _quoted_job_for_property(ctx, ctx["property"]["id"], ctx["charger"]["sku"])
    # [600,780) overlaps [540,720) since 600 < 720
    res = api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(job_b["id"], el["id"], window_date=date,
                                            window_start_minute=600, window_end_minute=780),
        COORDINATOR)
    validate_error(res, "ERR_WINDOW_OVERLAP")


def test_enclosing_window_rejected():
    """PRD §3.6: "The new window must not overlap any non-cancelled assignment already held
    by the same electrician on the same `window_date`; overlap is evaluated on the half-open
    interval (two windows overlap when one starts before the other ends and vice versa, with
    a shared endpoint not counting as overlap), and a conflict is rejected with
    `ERR_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/electrician_overlapping_windows_rejected
    """
    ctx = setup_quoted_job()
    el = create_electrician(max_daily_jobs=5)
    date = "2026-05-07T00:00:00Z"
    get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"], window_date=date,
                                            window_start_minute=600, window_end_minute=660),
        COORDINATOR))
    job_b = _quoted_job_for_property(ctx, ctx["property"]["id"], ctx["charger"]["sku"])
    # [540,720) strictly encloses the existing [600,660): 540 < 660 and 600 < 720 -> overlap
    res = api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(job_b["id"], el["id"], window_date=date,
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR)
    validate_error(res, "ERR_WINDOW_OVERLAP")


def test_adjacent_touching_windows_allowed():
    """PRD §3.6: "overlap is evaluated on the half-open interval (two windows overlap when
    one starts before the other ends and vice versa, with a shared endpoint not counting as
    overlap)"
    PRD §3.6: "A successful booking creates the assignment in `BOOKED` status and advances
    the job's `workflow_status` from `QUOTED` to `SCHEDULED`"

    Design: Difficulty/resource_temporal_overlap/electrician_adjacent_windows_touching_allowed
    """
    ctx = setup_quoted_job()
    el = create_electrician(max_daily_jobs=5)
    date = "2026-05-08T00:00:00Z"
    get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"], window_date=date,
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR))
    job_b = _quoted_job_for_property(ctx, ctx["property"]["id"], ctx["charger"]["sku"])
    # [720,900) touches the prior window's end at 720 (excluded) -> no overlap -> allowed
    res = validate_success(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(job_b["id"], el["id"], window_date=date,
                                            window_start_minute=720, window_end_minute=900),
        COORDINATOR), 201)
    assert res["status"] == "BOOKED"
    job_after = validate_success(api_client.get_install_job(job_b["id"], COORDINATOR), 200)
    assert job_after["workflow_status"] == "SCHEDULED"


def test_adjacent_window_before_existing_allowed():
    """PRD §3.6: "the half-open interval ... with a shared endpoint not counting as
    overlap)"
    PRD §3.6: "A successful booking creates the assignment in `BOOKED` status and advances
    the job's `workflow_status` from `QUOTED` to `SCHEDULED`"

    Design: Difficulty/resource_temporal_overlap/electrician_adjacent_windows_touching_allowed
    """
    ctx = setup_quoted_job()
    el = create_electrician(max_daily_jobs=5)
    date = "2026-05-08T00:00:00Z"
    get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"], window_date=date,
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR))
    job_b = _quoted_job_for_property(ctx, ctx["property"]["id"], ctx["charger"]["sku"])
    # [360,540) ends exactly at the existing window's start 540 (excluded) -> no overlap
    res = validate_success(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(job_b["id"], el["id"], window_date=date,
                                            window_start_minute=360, window_end_minute=540),
        COORDINATOR), 201)
    assert res["status"] == "BOOKED"


# ─── Out-of-territory beats window overlap (priority 10 < 12) ─────────────

def test_out_of_territory_beats_window_overlap():
    """PRD §3.10: "then the electrician-territory check on booking, failing with
    `ERR_ELECTRICIAN_OUT_OF_TERRITORY`; ... then the dispatch window-overlap check, failing
    with `ERR_WINDOW_OVERLAP`"
    PRD §3.6: "The electrician's `license_state_code` must equal the property's
    `state_code`, since only properties in the licensed state are serviceable by them; a
    mismatch is rejected with `ERR_ELECTRICIAN_OUT_OF_TERRITORY` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/out_of_territory_beats_window_overlap
    """
    el = create_electrician(license_state_code="NV")
    date = "2026-05-04T00:00:00Z"
    # The window-overlap check (§3.6) is per-electrician across the day regardless of
    # property, while the territory check compares the booked job's property state_code.
    # To make BOTH checks applicable on a single booking we first establish an existing
    # window for the NV electrician on an in-territory (NV) property (so that booking
    # succeeds and seeds an overlapping window), then book the same electrician on a
    # CA property (out-of-territory) with an overlapping window on the same date.
    nv_ctx = setup_quoted_job(property_overrides={"state_code": "NV",
                                                  "utility_territory_code": "NVE"})
    get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(nv_ctx["job"]["id"], el["id"], window_date=date,
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR))
    ca_ctx = setup_quoted_job()  # CA property
    # Same window (overlap) AND out-of-territory -> territory (P10) wins over overlap (P12)
    res = api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ca_ctx["job"]["id"], el["id"], window_date=date,
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR)
    validate_error(res, "ERR_ELECTRICIAN_OUT_OF_TERRITORY")


def test_out_of_territory_rejected_isolated():
    """PRD §3.6: "The electrician's `license_state_code` must equal the property's
    `state_code`, since only properties in the licensed state are serviceable by them; a
    mismatch is rejected with `ERR_ELECTRICIAN_OUT_OF_TERRITORY` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/out_of_territory_beats_window_overlap
    """
    ctx = setup_quoted_job()  # CA property
    el = create_electrician(license_state_code="NV")
    res = api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"],
                                            window_date="2026-05-04T00:00:00Z",
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR)
    validate_error(res, "ERR_ELECTRICIAN_OUT_OF_TERRITORY")


# ─── Suspended electrician booking rejected (corner error instance) ──────

def test_suspended_electrician_booking_rejected():
    """PRD §3.6: "The electrician must be `ACTIVE`; booking a `SUSPENDED` electrician is
    rejected with `ERR_ELECTRICIAN_SUSPENDED` (HTTP 409)."

    Design: Corner/errors/electrician_suspended_booking_rejected
    """
    ctx = setup_quoted_job()
    el = create_electrician()
    get_success_data(api_client.set_electrician_status(el["id"], {"status": "SUSPENDED"}, COORDINATOR))
    res = api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"],
                                            window_date="2026-05-18T00:00:00Z",
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR)
    validate_error(res, "ERR_ELECTRICIAN_SUSPENDED")


# ─── Window end <= start rejected (corner type-constraint instance) ──────

def test_window_end_before_start_invalid():
    """PRD §3.6: "A `window_end_minute` that is not strictly greater than
    `window_start_minute` is rejected with `ERR_INVALID_REQUEST`"

    Design: Corner/validations/window_end_before_start_invalid
    """
    ctx = setup_quoted_job()
    el = create_electrician()
    res = api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"],
                                            window_date="2026-05-14T00:00:00Z",
                                            window_start_minute=720, window_end_minute=540),
        COORDINATOR)
    validate_error(res, "ERR_INVALID_REQUEST")
