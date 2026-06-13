"""Photo validation boundaries and the two appointment interval geometries
(facility half-open vs counter buffer-extended).

Difficulty queue: boundary_precision_check, resource_temporal_overlap. Corner queue:
calculations (photo multi-failure / ratio boundary / revalidate).
"""
from test_helpers import (
    api_client,
    make_applicant_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


# ════════════════════════════════════════════════════════════════════════
# Difficulty/boundary_precision_check/photo_head_fraction_upper_boundary_069_pass_070_fail
# ════════════════════════════════════════════════════════════════════════
def test_head_fraction_069_passes(api):
    """PRD §3.3: "The head_height_fraction must be at least 0.50 and at most 0.69;
    outside that inclusive band the code HEAD_OUT_OF_RANGE is added — so a fraction
    of exactly 0.69 passes this rule while exactly 0.70 fails it."

    Design: Difficulty/boundary_precision_check/photo_head_fraction_upper_boundary_069_pass_070_fail
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    photo = validate_success(api.create_photo(application["id"], {
        "width_px": 600, "height_px": 600, "head_height_fraction": 0.69,
        "background_is_white": True}, make_applicant_headers(applicant["id"])), 201)
    assert photo["validation_result"] == "PASS"


def test_head_fraction_070_fails_with_head_out_of_range(api):
    """PRD §3.3: "outside that inclusive band the code HEAD_OUT_OF_RANGE is added —
    so a fraction of exactly 0.69 passes this rule while exactly 0.70 fails it." PRD
    §3.3: "The validation result is PASS when no codes were added and FAIL
    otherwise".

    Design: Difficulty/boundary_precision_check/photo_head_fraction_upper_boundary_069_pass_070_fail
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    photo = validate_success(api.create_photo(application["id"], {
        "width_px": 600, "height_px": 600, "head_height_fraction": 0.70,
        "background_is_white": True}, make_applicant_headers(applicant["id"])), 201)
    assert photo["validation_result"] == "FAIL"
    assert "HEAD_OUT_OF_RANGE" in photo["failure_reasons"]


# ════════════════════════════════════════════════════════════════════════
# Difficulty/boundary_precision_check/counter_buffer_boundary_start_equals_end_plus_buffer_allowed
# ════════════════════════════════════════════════════════════════════════
def test_counter_booking_at_end_plus_buffer_edge_allowed(api):
    """PRD §3.7: "a new booking whose start_utc is exactly equal to an existing
    booking's end_utc plus the buffer is allowed, since the window is closed at its
    start and open at its extended end."

    Design: Difficulty/boundary_precision_check/counter_buffer_boundary_start_equals_end_plus_buffer_allowed
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    counter = fx.create_counter(cleanup_buffer_minutes=15)

    ctx1 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    fx.book_counter_appointment(ctx1["application"]["id"], ctx1["applicant"]["id"], counter["id"],
                                "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                ctx1["application"]["version"])

    ctx2 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl2 = ctx2["applicant"]["id"]
    app2 = ctx2["application"]["id"]
    # 09:45 == 09:30 + 15-minute buffer → allowed.
    appt2 = validate_success(api.create_appointment({
        "application_id": app2, "resource_kind": "URGENT_TRAVEL_COUNTER",
        "counter_id": counter["id"], "start_utc": "2026-06-09T09:45:00Z",
        "end_utc": "2026-06-09T10:15:00Z",
        "expected_application_version": ctx2["application"]["version"],
    }, make_applicant_headers(appl2)), 201)
    assert appt2["status"] == "BOOKED"


def test_counter_booking_one_minute_inside_buffer_rejected(api):
    """PRD §3.7: "a new booking that falls anywhere inside that buffer-extended
    window is rejected with ERR_COUNTER_SLOT_CONFLICT". The buffer-extended window of
    a 09:00-09:30 booking on a 15-minute-buffer counter runs to 09:45, so 09:44 is
    inside it.

    Design: Difficulty/boundary_precision_check/counter_buffer_boundary_start_equals_end_plus_buffer_allowed
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    counter = fx.create_counter(cleanup_buffer_minutes=15)

    ctx1 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    fx.book_counter_appointment(ctx1["application"]["id"], ctx1["applicant"]["id"], counter["id"],
                                "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                ctx1["application"]["version"])

    ctx2 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl2 = ctx2["applicant"]["id"]
    app2 = ctx2["application"]["id"]
    res = api.create_appointment({
        "application_id": app2, "resource_kind": "URGENT_TRAVEL_COUNTER",
        "counter_id": counter["id"], "start_utc": "2026-06-09T09:44:00Z",
        "end_utc": "2026-06-09T10:14:00Z",
        "expected_application_version": ctx2["application"]["version"],
    }, make_applicant_headers(appl2))
    validate_error(res, "ERR_COUNTER_SLOT_CONFLICT")


# ════════════════════════════════════════════════════════════════════════
# Difficulty/resource_temporal_overlap/facility_half_open_adjacency_allowed_overlap_rejected
# ════════════════════════════════════════════════════════════════════════
def test_facility_overlapping_appointment_rejected(api):
    """PRD §3.7: "A facility appointment must not overlap any existing BOOKED facility
    appointment on the same facility, where overlap is judged on a half-open interval
    basis ... but any actual overlap is rejected with ERR_FACILITY_SLOT_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/facility_half_open_adjacency_allowed_overlap_rejected
    """
    facility = fx.create_facility()
    ctx1 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    fx.book_facility_appointment(ctx1["application"]["id"], ctx1["applicant"]["id"], facility["id"],
                                 "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                 ctx1["application"]["version"])

    ctx2 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl2 = ctx2["applicant"]["id"]
    app2 = ctx2["application"]["id"]
    # 09:15-09:45 overlaps 09:00-09:30.
    res = api.create_appointment({
        "application_id": app2, "resource_kind": "ACCEPTANCE_FACILITY",
        "facility_id": facility["id"], "start_utc": "2026-06-09T09:15:00Z",
        "end_utc": "2026-06-09T09:45:00Z",
        "expected_application_version": ctx2["application"]["version"],
    }, make_applicant_headers(appl2))
    validate_error(res, "ERR_FACILITY_SLOT_CONFLICT")


def test_facility_adjacent_appointment_allowed(api):
    """PRD §3.7: "each booking occupies the time from its start_utc up to but not
    including its end_utc, so two bookings that merely touch end-to-start (one ending
    exactly when the next begins) do not conflict".

    Design: Difficulty/resource_temporal_overlap/facility_half_open_adjacency_allowed_overlap_rejected
    """
    facility = fx.create_facility()
    ctx1 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    fx.book_facility_appointment(ctx1["application"]["id"], ctx1["applicant"]["id"], facility["id"],
                                 "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                 ctx1["application"]["version"])

    ctx2 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl2 = ctx2["applicant"]["id"]
    app2 = ctx2["application"]["id"]
    # 09:30-10:00 starts exactly when the prior ends → allowed.
    appt2 = validate_success(api.create_appointment({
        "application_id": app2, "resource_kind": "ACCEPTANCE_FACILITY",
        "facility_id": facility["id"], "start_utc": "2026-06-09T09:30:00Z",
        "end_utc": "2026-06-09T10:00:00Z",
        "expected_application_version": ctx2["application"]["version"],
    }, make_applicant_headers(appl2)), 201)
    assert appt2["status"] == "BOOKED"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/resource_temporal_overlap/counter_buffered_window_rejects_inside_buffer
# ════════════════════════════════════════════════════════════════════════
def test_counter_booking_inside_buffer_window_rejected(api):
    """PRD §3.7: "each existing BOOKED counter appointment occupies the time from its
    start_utc up to but not including its end_utc plus that counter's
    cleanup_buffer_minutes, and a new booking that falls anywhere inside that
    buffer-extended window is rejected with ERR_COUNTER_SLOT_CONFLICT".

    Design: Difficulty/resource_temporal_overlap/counter_buffered_window_rejects_inside_buffer
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    counter = fx.create_counter(cleanup_buffer_minutes=15)
    ctx1 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    fx.book_counter_appointment(ctx1["application"]["id"], ctx1["applicant"]["id"], counter["id"],
                                "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                ctx1["application"]["version"])

    ctx2 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl2 = ctx2["applicant"]["id"]
    app2 = ctx2["application"]["id"]
    # 09:40 is inside the 09:30+15=09:45 buffer window even though it does not
    # overlap the raw 09:00-09:30 interval.
    res = api.create_appointment({
        "application_id": app2, "resource_kind": "URGENT_TRAVEL_COUNTER",
        "counter_id": counter["id"], "start_utc": "2026-06-09T09:40:00Z",
        "end_utc": "2026-06-09T10:10:00Z",
        "expected_application_version": ctx2["application"]["version"],
    }, make_applicant_headers(appl2))
    validate_error(res, "ERR_COUNTER_SLOT_CONFLICT")


def test_counter_outside_buffer_window_allowed(api):
    """PRD §3.7: "a new booking whose start_utc is exactly equal to an existing
    booking's end_utc plus the buffer is allowed, since the window is closed at its
    start and open at its extended end." A start well past the buffered end is
    likewise allowed.

    Design: Difficulty/resource_temporal_overlap/counter_buffered_window_rejects_inside_buffer
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    counter = fx.create_counter(cleanup_buffer_minutes=15)
    ctx1 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    fx.book_counter_appointment(ctx1["application"]["id"], ctx1["applicant"]["id"], counter["id"],
                                "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                ctx1["application"]["version"])

    ctx2 = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl2 = ctx2["applicant"]["id"]
    app2 = ctx2["application"]["id"]
    appt2 = validate_success(api.create_appointment({
        "application_id": app2, "resource_kind": "URGENT_TRAVEL_COUNTER",
        "counter_id": counter["id"], "start_utc": "2026-06-09T10:00:00Z",
        "end_utc": "2026-06-09T10:30:00Z",
        "expected_application_version": ctx2["application"]["version"],
    }, make_applicant_headers(appl2)), 201)
    assert appt2["status"] == "BOOKED"


# ════════════════════════════════════════════════════════════════════════
# Corner/calculations/photo_validation_multiple_failure_reasons
# ════════════════════════════════════════════════════════════════════════
def test_photo_multiple_failure_reasons(api):
    """PRD §3.3: "Both width_px and height_px must be at least 600 pixels; if either
    is below 600, the code DIMENSION_TOO_SMALL is added." "The head_height_fraction
    must be at least 0.50 and at most 0.69; outside that inclusive band the code
    HEAD_OUT_OF_RANGE is added". "The background_is_white flag must be true; if it is
    false, the code BACKGROUND_NOT_WHITE is added."

    Design: Corner/calculations/photo_validation_multiple_failure_reasons
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    photo = validate_success(api.create_photo(application["id"], {
        "width_px": 500, "height_px": 500, "head_height_fraction": 0.40,
        "background_is_white": False}, make_applicant_headers(applicant["id"])), 201)
    assert photo["validation_result"] == "FAIL"
    assert "DIMENSION_TOO_SMALL" in photo["failure_reasons"]
    assert "HEAD_OUT_OF_RANGE" in photo["failure_reasons"]
    assert "BACKGROUND_NOT_WHITE" in photo["failure_reasons"]
    assert "NOT_SQUARE" not in photo["failure_reasons"]


# ════════════════════════════════════════════════════════════════════════
# Corner/calculations/photo_validation_not_square_ratio_boundary_fail
# ════════════════════════════════════════════════════════════════════════
def test_photo_not_square_ratio_fail(api):
    """PRD §3.3: "The aspect ratio, computed as width_px divided by height_px, must
    be at least 0.98 and at most 1.02; outside that inclusive band the code
    NOT_SQUARE is added." 600/630 = 0.952 is below 0.98.

    Design: Corner/calculations/photo_validation_not_square_ratio_boundary_fail
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    photo = validate_success(api.create_photo(application["id"], {
        "width_px": 600, "height_px": 630, "head_height_fraction": 0.60,
        "background_is_white": True}, make_applicant_headers(applicant["id"])), 201)
    assert photo["validation_result"] == "FAIL"
    assert "NOT_SQUARE" in photo["failure_reasons"]


# ════════════════════════════════════════════════════════════════════════
# Corner/calculations/revalidate_photo_flips_fail_to_pass
# ════════════════════════════════════════════════════════════════════════
def test_revalidate_photo_flips_fail_to_pass(api):
    """PRD §3.3: "Photo validation runs immediately on attachment and again on demand
    through a re-validation capability that may override any of the four inputs; the
    outcome is written to validation_result ... and the list of failed-rule codes is
    written to failure_reasons (empty on a pass)."

    Design: Corner/calculations/revalidate_photo_flips_fail_to_pass
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    appl_id = applicant["id"]
    photo = validate_success(api.create_photo(application["id"], {
        "width_px": 600, "height_px": 600, "head_height_fraction": 0.60,
        "background_is_white": False}, make_applicant_headers(appl_id)), 201)
    assert photo["validation_result"] == "FAIL"

    revalidated = validate_success(api.revalidate_photo(photo["id"], {"background_is_white": True},
                                                        make_applicant_headers(appl_id)), 200)
    assert revalidated["validation_result"] == "PASS"
    assert revalidated["failure_reasons"] == []
