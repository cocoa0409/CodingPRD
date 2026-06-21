"""Tests for boundary semantics on time-gated transitions (PRD §2.9, §3.2,
§3.5): the EnrollmentWindow's half-open [opens_at, closes_at) interval, the
strict-less-than `respond_by` deadline on Offer.accept, and the inclusive
opens_at start.
"""
from test_helpers import (
    set_clock,
    create_district,
    create_school,
    create_window,
    open_window,
    register_family,
    create_student,
    create_application,
    submit_application,
    advance_window_to_lottery_run,
    list_offers_for_application,
    get_offer,
    api_client,
    TEST_USERS,
    make_guardian_headers,
    validate_error,
    ApiErrorId,
)
from test_helpers.factories import accept_offer_payload


# =====================================================================
# Difficulty rule 8 / instance 1 — EnrollmentWindow open-window timing:
# closes_at is exclusive. Attempting open at clock == closes_at is rejected.
# =====================================================================

def test_open_window_at_closes_at_instant_rejected_with_window_timing(api):
    """PRD §3.2: "Opening the window transitions it from `DRAFT` to `OPEN`.
    The operation is rejected with `ERR_INVALID_STATE` if the window is not
    in `DRAFT`, rejected with `ERR_WINDOW_TIMING` unless the system clock
    has reached `opens_at` but is still strictly before `closes_at`,
    rejected with `ERR_DISTRICT_ARCHIVED` if the window's district is not
    `ACTIVE`, and rejected with `ERR_DISTRICT_DATA_INVALID` if the
    district's `poverty_index_pct` is outside the 0-to-100 range — a
    data-sanity gate intended to catch corrupted district configurations
    before they distort lottery weighting."

    With clock set to exactly closes_at, the precondition "clock strictly
    before closes_at" fails. ERR_WINDOW_TIMING.

    Design: Difficulty/resource_temporal_overlap/enrollment_window_inclusive_open_exclusive_close_at_closes_at_instant
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DTO1", name="Ov1", poverty_index_pct=0.00)
    window = create_window(
        district["id"], cycle_label="2026-27-TO1",
        opens_at="2026-01-02T00:00:00Z",
        closes_at="2026-02-01T00:00:00Z",
        lottery_runs_at="2026-02-02T00:00:00Z",
    )
    # Pin clock to closes_at — should violate the strict < closes_at half.
    set_clock("2026-02-01T00:00:00Z")
    res = api.open_window(window["id"], TEST_USERS["district_admin_headers"])
    err = validate_error(res, ApiErrorId.ERR_WINDOW_TIMING.value)
    assert err["error_id"] == ApiErrorId.ERR_WINDOW_TIMING.value


def test_open_window_before_opens_at_rejected_with_window_timing(api):
    """PRD §3.2: "rejected with `ERR_WINDOW_TIMING` unless the system clock
    has reached `opens_at` but is still strictly before `closes_at`."

    Companion to the closes_at-instant test. With clock pinned to a moment
    before opens_at, the same temporal precondition fails on the early
    side. ERR_WINDOW_TIMING.

    Design: Difficulty/resource_temporal_overlap/enrollment_window_inclusive_open_exclusive_close_at_closes_at_instant
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DTO1B", name="Ov1B", poverty_index_pct=0.00)
    window = create_window(
        district["id"], cycle_label="2026-27-TO1B",
        opens_at="2026-01-10T00:00:00Z",
        closes_at="2026-02-01T00:00:00Z",
        lottery_runs_at="2026-02-02T00:00:00Z",
    )
    # Clock is BEFORE opens_at.
    res = api.open_window(window["id"], TEST_USERS["district_admin_headers"])
    err = validate_error(res, ApiErrorId.ERR_WINDOW_TIMING.value)
    assert err["error_id"] == ApiErrorId.ERR_WINDOW_TIMING.value


# =====================================================================
# Difficulty rule 8 / instance 2 — Offer.accept strict-less-than respond_by.
# At clock >= respond_by, accept rejected.
# =====================================================================

def test_accept_offer_after_respond_by_returns_invalid_state(api):
    """PRD §3.5: "Acceptance moves an `OFFERED` offer to `ACCEPTED` and, in
    the same atomic mutation, advances the linked application from
    `ACCEPTED` to `ENROLLED`; the request must carry `expected_offer_version`
    matching the offer's current `version` (rejected with `ERR_STALE_VERSION`
    if not) and may not proceed once the clock has reached `respond_by`
    (rejected with `ERR_INVALID_STATE`)."

    Lottery runs at 2026-02-02; offered_at therefore = 2026-02-02;
    respond_by = 2026-02-09. With clock pinned to exactly 2026-02-09
    (strict-less-than violated), accept must fail with ERR_INVALID_STATE.

    Design: Difficulty/resource_temporal_overlap/offer_accept_after_respond_by_deadline_strict_less_than
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DTO2", name="Ov2", poverty_index_pct=0.00)
    school = create_school(district["id"], code="STO2", name="Ov2s",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=5)
    window = create_window(district["id"], cycle_label="2026-27-TO2")
    family = register_family(district["id"], guardian_email="to2@x.com",
                             residence_zone_code="ZTO2", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=5)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    advance_window_to_lottery_run(window["id"])
    off = list_offers_for_application(app["id"], family_id=family["id"])[0]
    off_now = get_offer(off["id"], family_id=family["id"])
    # Advance clock to exactly respond_by (7 days after offered_at).
    set_clock("2026-02-09T00:00:00Z")
    res = api.accept_offer(
        off["id"],
        accept_offer_payload(off_now["version"]),
        make_guardian_headers(family["id"]),
    )
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] == ApiErrorId.ERR_INVALID_STATE.value
