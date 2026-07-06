"""Hearing scheduling: interval overlap, the neutral buffer, notice windows,
and the temporal-over-constraint priority ordering."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_hearing_payload,
)
from test_helpers.fixtures import (
    ADMIN, get_case, set_clock,
    setup_hearing_case, setup_hearing_case_with_hearing,
    setup_two_hearing_cases_same_neutral,
)

ADM = ADMIN


# ---- Difficulty: half-open interval overlap on one case ------------------

def test_case_hearing_overlap_rejected(api):
    """PRD 3.6: "The hearing must not collide on the same case: if its half-open interval
    overlaps that of any other non-cancelled hearing on the same case, it is rejected with
    `ERR_HEARING_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/case_hearing_overlap_half_open
    """
    ctx = setup_hearing_case_with_hearing(api, clock="2026-06-01T00:00:00Z",
                                          start_at="2026-06-20T09:00:00Z",
                                          end_at="2026-06-20T11:00:00Z")
    resp = api.create_hearing(ctx["case"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-20T10:00:00Z",
        end_at="2026-06-20T12:00:00Z", location="Room B"), ADM)
    validate_error(resp, ApiErrorId.ERR_HEARING_OVERLAP.value)


def test_case_hearing_contained_interval_overlap_rejected(api):
    """PRD 3.6: "The hearing must not collide on the same case: if its half-open interval
    overlaps that of any other non-cancelled hearing on the same case, it is rejected with
    `ERR_HEARING_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/case_hearing_overlap_half_open
    """
    ctx = setup_hearing_case_with_hearing(api, clock="2026-06-01T00:00:00Z",
                                          start_at="2026-06-20T09:00:00Z",
                                          end_at="2026-06-20T11:00:00Z")
    resp = api.create_hearing(ctx["case"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-20T09:30:00Z",
        end_at="2026-06-20T10:30:00Z", location="Room B"), ADM)
    validate_error(resp, ApiErrorId.ERR_HEARING_OVERLAP.value)


# ---- Difficulty: neutral buffer across cases -----------------------------

def test_neutral_buffer_conflict_across_cases_rejected(api):
    """PRD 3.6: "it must respect the neutral's buffer: if the hearing falls within thirty
    minutes (`NEUTRAL_BUFFER_MINUTES`) of another hearing on any case that shares the same
    appointed neutral, it is rejected with `ERR_NEUTRAL_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/neutral_buffer_conflict_across_cases
    """
    ctx = setup_two_hearing_cases_same_neutral(api)
    resp = api.create_hearing(ctx["c2"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-20T11:15:00Z",
        end_at="2026-06-20T12:00:00Z", location="Room C"), ADM)
    validate_error(resp, ApiErrorId.ERR_NEUTRAL_UNAVAILABLE.value)


def test_neutral_buffer_well_separated_hearing_allowed(api):
    """PRD 3.6: "two hearings that share the same appointed neutral must be separated by at
    least thirty minutes of clear time (the neutral buffer is `NEUTRAL_BUFFER_MINUTES`,
    thirty minutes)."

    Design: Difficulty/resource_temporal_overlap/neutral_buffer_conflict_across_cases
    """
    ctx = setup_two_hearing_cases_same_neutral(api)
    data = validate_success(api.create_hearing(ctx["c2"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-20T13:00:00Z",
        end_at="2026-06-20T14:00:00Z", location="Room C"), ADM), 201)
    assert data["status"] == "SCHEDULED"


# ---- Difficulty: temporal notice gate pre-empts overlap gate -------------

def _double_violation_second_hearing(api):
    ctx = setup_hearing_case_with_hearing(api, clock="2026-06-01T00:00:00Z",
                                          start_at="2026-06-15T09:00:00Z",
                                          end_at="2026-06-15T11:00:00Z")
    set_clock(api, "2026-06-14T00:00:00Z")
    return api.create_hearing(ctx["case"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-15T10:00:00Z",
        end_at="2026-06-15T12:00:00Z", location="Room B"), ADM)


def test_hearing_notice_pre_empts_overlap_error(api):
    """PRD 2.8: "8. **Temporal gates** — the hearing-notice and appeal-window gates,
    reported as `ERR_HEARING_NOTICE_TOO_SHORT` or `ERR_APPEAL_WINDOW_CLOSED` (both 422)."
    PRD 2.8: "9. **Structural business gates** — ... hearing overlap ... reported as ...
    `ERR_HEARING_OVERLAP`". PRD 2.8: "An earlier check always takes precedence over a later
    one".

    Design: Difficulty/priority_pair_validation_conflict/hearing_notice_precedes_overlap
    """
    resp = _double_violation_second_hearing(api)
    validate_error(resp, ApiErrorId.ERR_HEARING_NOTICE_TOO_SHORT.value)


def test_hearing_double_violation_reports_temporal_status_422(api):
    """PRD 2.8: "8. **Temporal gates** ... (both 422). 9. **Structural business gates** ...
    (all 409)." PRD 2.8: "An earlier check always takes precedence over a later one".

    Design: Difficulty/priority_pair_validation_conflict/hearing_notice_precedes_overlap
    """
    resp = _double_violation_second_hearing(api)
    assert resp.status_code == 422, f"temporal gate should win (422), got {resp.status_code}"
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_HEARING_OVERLAP.value


# ---- Corner: end-before-start / happy path / cancel recompute ------------

def test_hearing_end_before_start_returns_end_before_start(api):
    """PRD 3.6: "The interval must be well formed: `end_at` must be strictly after
    `start_at`, otherwise `ERR_HEARING_END_BEFORE_START`."

    Design: Corner/validations/hearing_end_before_start_returns_end_before_start
    """
    ctx = setup_hearing_case(api, clock="2026-06-01T00:00:00Z")
    resp = api.create_hearing(ctx["case"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-20T12:00:00Z",
        end_at="2026-06-20T09:00:00Z", location="Room A"), ADM)
    validate_error(resp, ApiErrorId.ERR_HEARING_END_BEFORE_START.value)


def test_schedule_hearing_within_notice_and_no_overlap_passes(api):
    """PRD 3.6: "its `start_at` must be no earlier than the logical clock's current instant
    plus the seven-day notice window (`HEARING_NOTICE_DAYS`)". PRD 3.6: "A new hearing is
    `SCHEDULED`".

    Design: Corner/validations/schedule_hearing_within_notice_and_no_overlap_passes
    """
    ctx = setup_hearing_case(api, clock="2026-06-01T00:00:00Z")
    data = validate_success(api.create_hearing(ctx["case"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-20T09:00:00Z",
        end_at="2026-06-20T11:00:00Z", location="Room A"), ADM), 201)
    assert data["status"] == "SCHEDULED"


def test_cancel_hearing_recomputes_estimated_comp(api):
    """PRD 3.2: "it takes the appointed neutral's `hourly_rate_cents`, multiplies it by
    the total planned duration in hours of every hearing on the case whose status is
    `SCHEDULED` ... and rounds the product half up to whole cents." PRD 3.6: "Cancelling a
    hearing removes it from the scheduled set and therefore recomputes the case's
    `estimated_neutral_fee_cents`."

    Design: Corner/calculations/cancel_hearing_recomputes_estimated_comp
    """
    ctx = setup_hearing_case(api, clock="2026-06-01T00:00:00Z", hourly_rate_cents=50_000)
    validate_success(api.create_hearing(ctx["case"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-20T09:00:00Z",
        end_at="2026-06-20T12:00:00Z", location="Room A"), ADM), 201)
    h2 = validate_success(api.create_hearing(ctx["case"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-21T09:00:00Z",
        end_at="2026-06-21T12:00:00Z", location="Room B"), ADM), 201)
    validate_success(api.transition_hearing(h2["id"], {"to_status": "CANCELLED"}, ADM), 200)
    assert get_case(api, ctx["case"]["id"])["estimated_neutral_fee_cents"] == 150_000
