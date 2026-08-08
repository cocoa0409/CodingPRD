"""Permit-grant gating, crew scheduling, vertical clearance, FCC shot clock,
and first-year rental proration.

Queue A — priority_pair_validation_conflict (SoD beats clearance),
resource_temporal_overlap (crew double-booking, pole clearance buffer),
boundary_precision_check (shot-clock ON_TIME at exact deadline).
Queue B — calculations (first-year proration).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_attacher_headers, make_permit_officer_headers, make_engineer_headers,
    setup_base, submit_application, submit_survey, issue_estimate, accept_estimate,
    grant_permit, set_clock, create_accepted_application, api_client,
)

COORD = TEST_USERS["coordinator_headers"]
_SIMPLE_SURVEY = {"estimated_labor_hours": 4, "make_ready_required": True,
                  "existing_attacher_count": 0, "complexity_class": "SIMPLE"}


# --- shared scenario builders ---------------------------------------------
def _pole_with_attachment_and_second_accepted(pos2, surveyor2):
    """Pole carrying an ACTIVE attachment [240,246] from a first grant, plus a
    second application ESTIMATE_ACCEPTED requesting position pos2 (span 6)."""
    ctx = setup_base(pole_overrides={"usable_communication_space_inches": 60})
    pole, crew, att = ctx["pole"], ctx["crew"], ctx["attacher"]

    app1 = submit_application(pole["id"], att["id"], requested_space_inches=6,
                              requested_position_inches=240)
    submit_survey(app1["id"], crew["id"], "eng-1",
                  window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T12:00:00Z",
                  **_SIMPLE_SURVEY)
    issue_estimate(app1["id"], "eng-1")
    accept_estimate(app1["id"], att["id"])
    grant_permit(app1["id"], "po-1", actual_labor_hours=4)

    app2 = submit_application(pole["id"], att["id"], requested_space_inches=6,
                              requested_position_inches=pos2)
    submit_survey(app2["id"], crew["id"], surveyor2,
                  window_start="2026-05-11T08:00:00Z", window_end="2026-05-11T12:00:00Z",
                  **_SIMPLE_SURVEY)
    issue_estimate(app2["id"], surveyor2)
    accept_estimate(app2["id"], att["id"])
    return ctx, app2


def _accepted_app_with_clock_schedule():
    """Estimate accepted at 2026-06-01 so permit_deadline == 2026-07-31."""
    ctx = setup_base()
    pole, crew, att = ctx["pole"], ctx["crew"], ctx["attacher"]
    set_clock("2026-05-15T00:00:00Z")
    app = submit_application(pole["id"], att["id"], requested_space_inches=6,
                             requested_position_inches=240)
    submit_survey(app["id"], crew["id"], "eng-1",
                  window_start="2026-05-16T08:00:00Z", window_end="2026-05-16T12:00:00Z",
                  **_SIMPLE_SURVEY)
    issue_estimate(app["id"], "eng-1")
    set_clock("2026-06-01T00:00:00Z")
    accept_estimate(app["id"], att["id"])
    return ctx, app


# ─── Queue A: priority_pair (SoD beats clearance) ──────────────────────────
def test_permit_grant_sod_beats_clearance_error_id(api):
    """PRD §2.10: "Then segregation of duties on permit decisions, yielding
    `ERR_SEGREGATION_OF_DUTIES` (403). Then cross-entity state guards (409). Then
    crew scheduling conflicts, yielding `ERR_CREW_DOUBLE_BOOKED` (409). Then
    vertical clearance, yielding `ERR_CLEARANCE_VIOLATION` (409)."
    PRD §2.10: "A check earlier in this ordering always masks a check later in it."

    Design: Difficulty/priority_pair_validation_conflict/permit_grant_sod_beats_clearance
    """
    ctx, app2 = _pole_with_attachment_and_second_accepted(pos2=250, surveyor2="shared-1")
    res = api.permit_application(app2["id"], {"decision": "GRANTED", "actual_labor_hours": 8},
                                 make_permit_officer_headers("shared-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


def test_permit_grant_sod_beats_clearance_status_unchanged(api):
    """PRD §2.10: "Then segregation of duties on permit decisions, yielding
    `ERR_SEGREGATION_OF_DUTIES` (403). Then cross-entity state guards (409). Then
    crew scheduling conflicts, yielding `ERR_CREW_DOUBLE_BOOKED` (409). Then
    vertical clearance, yielding `ERR_CLEARANCE_VIOLATION` (409)."
    PRD §2.10: "A check earlier in this ordering always masks a check later in it."

    Design: Difficulty/priority_pair_validation_conflict/permit_grant_sod_beats_clearance
    """
    ctx, app2 = _pole_with_attachment_and_second_accepted(pos2=250, surveyor2="shared-1")
    api.permit_application(app2["id"], {"decision": "GRANTED", "actual_labor_hours": 8},
                           make_permit_officer_headers("shared-1"))
    after = get_success_data(api_client.get_application(app2["id"], COORD))
    assert after["status"] == "ESTIMATE_ACCEPTED", "SoD rejection must leave the fork unresolved"


# ─── Queue A: resource_temporal_overlap (crew double-booking) ──────────────
def test_crew_window_overlap_rejects_double_booking(api):
    """PRD §3.2: "Crew windows are treated as half-open intervals from
    `window_start` up to but not including `window_end`, so two windows that
    merely touch at an endpoint are allowed, but any true overlap is rejected
    with `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_window_overlap_rejects_double_booking
    """
    ctx = setup_base()
    pole, crew, att = ctx["pole"], ctx["crew"], ctx["attacher"]
    app1 = submit_application(pole["id"], att["id"], requested_position_inches=240)
    submit_survey(app1["id"], crew["id"], "eng-1",
                  window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T12:00:00Z",
                  **_SIMPLE_SURVEY)
    app2 = submit_application(pole["id"], att["id"], requested_position_inches=300)
    res = api.survey_application(
        app2["id"],
        {"crew_id": crew["id"], "window_start": "2026-05-10T11:00:00Z",
         "window_end": "2026-05-10T13:00:00Z", "estimated_labor_hours": 4,
         "make_ready_required": True, "existing_attacher_count": 0,
         "complexity_class": "SIMPLE", "findings": "ok"},
        make_engineer_headers("eng-1"),
    )
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED", expected_status=409)


def test_crew_window_touching_endpoint_is_allowed(api):
    """PRD §3.2: "Crew windows are treated as half-open intervals from
    `window_start` up to but not including `window_end`, so two windows that
    merely touch at an endpoint are allowed, but any true overlap is rejected
    with `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_window_overlap_rejects_double_booking
    """
    ctx = setup_base()
    pole, crew, att = ctx["pole"], ctx["crew"], ctx["attacher"]
    app1 = submit_application(pole["id"], att["id"], requested_position_inches=240)
    submit_survey(app1["id"], crew["id"], "eng-1",
                  window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T12:00:00Z",
                  **_SIMPLE_SURVEY)
    app2 = submit_application(pole["id"], att["id"], requested_position_inches=300)
    res = api.survey_application(
        app2["id"],
        {"crew_id": crew["id"], "window_start": "2026-05-10T12:00:00Z",
         "window_end": "2026-05-10T14:00:00Z", "estimated_labor_hours": 4,
         "make_ready_required": True, "existing_attacher_count": 0,
         "complexity_class": "SIMPLE", "findings": "ok"},
        make_engineer_headers("eng-1"),
    )
    survey = validate_success(res, 201)
    assert survey["crew_id"] == crew["id"]


# ─── Queue A: resource_temporal_overlap (pole clearance buffer) ────────────
def test_pole_clearance_buffer_rejects_near_attachment(api):
    """PRD §3.4: "If any existing `ACTIVE` attachment lies within 12 inches of
    the new interval (that is, the gap is strictly less than 12 inches,
    including any overlap), the grant is rejected with `ERR_CLEARANCE_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/pole_clearance_buffer_rejects_near_attachment
    """
    ctx, app2 = _pole_with_attachment_and_second_accepted(pos2=250, surveyor2="eng-1")
    res = api.permit_application(app2["id"], {"decision": "GRANTED", "actual_labor_hours": 4},
                                 make_permit_officer_headers("po-1"))
    validate_error(res, "ERR_CLEARANCE_VIOLATION", expected_status=409)


def test_pole_clearance_sufficient_gap_grants(api):
    """PRD §3.4: "If any existing `ACTIVE` attachment lies within 12 inches of
    the new interval (that is, the gap is strictly less than 12 inches,
    including any overlap), the grant is rejected with `ERR_CLEARANCE_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/pole_clearance_buffer_rejects_near_attachment
    """
    # Existing [240,246]; new [258,264] leaves a 12-inch gap (>= 12) → clean grant.
    ctx, app2 = _pole_with_attachment_and_second_accepted(pos2=258, surveyor2="eng-1")
    res = api.permit_application(app2["id"], {"decision": "GRANTED", "actual_labor_hours": 4},
                                 make_permit_officer_headers("po-1"))
    app = validate_success(res, 200)
    assert app["status"] == "PERMIT_GRANTED"


# ─── Queue A: boundary_precision_check (shot clock ON_TIME) ─────────────────
def test_shot_clock_on_time_at_exact_deadline(api):
    """PRD §3.4: "The `shot_clock_status` is then computed: it is `ON_TIME` when
    `permit_issued_at` is on or before `permit_deadline` and `LATE` otherwise,
    with the boundary treated as on-time."

    Design: Difficulty/boundary_precision_check/shot_clock_on_time_at_exact_deadline
    """
    ctx, app = _accepted_app_with_clock_schedule()
    set_clock("2026-07-31T00:00:00Z")
    res = api.permit_application(app["id"], {"decision": "GRANTED", "actual_labor_hours": 4},
                                 make_permit_officer_headers("po-1"))
    granted = validate_success(res, 200)
    assert granted["shot_clock_status"] == "ON_TIME"
    assert granted["status"] == "PERMIT_GRANTED"


def test_shot_clock_late_one_day_past_deadline(api):
    """PRD §3.4: "The `shot_clock_status` is then computed: it is `ON_TIME` when
    `permit_issued_at` is on or before `permit_deadline` and `LATE` otherwise,
    with the boundary treated as on-time."

    Design: Difficulty/boundary_precision_check/shot_clock_on_time_at_exact_deadline
    """
    ctx, app = _accepted_app_with_clock_schedule()
    set_clock("2026-08-01T00:00:00Z")
    res = api.permit_application(app["id"], {"decision": "GRANTED", "actual_labor_hours": 4},
                                 make_permit_officer_headers("po-1"))
    granted = validate_success(res, 200)
    assert granted["shot_clock_status"] == "LATE"


# ─── Queue B: calculations (first-year proration) ──────────────────────────
def test_annual_rental_first_year_proration_correct(api):
    """PRD §3.4: "The prorated `annual_rental_fee_cents` is the full-year figure
    multiplied by those remaining days, divided by 365, and rounded half-up to
    whole cents."

    Design: Corner/calculations/annual_rental_first_year_proration_correct
    """
    ctx = create_accepted_application(
        app_overrides={"requested_space_inches": 6, "requested_position_inches": 240},
        survey_overrides=_SIMPLE_SURVEY,
    )
    set_clock("2026-07-01T00:00:00Z")
    res = api.permit_application(ctx["app"]["id"], {"decision": "GRANTED", "actual_labor_hours": 4},
                                 make_permit_officer_headers("po-1"))
    granted = validate_success(res, 200)
    # full_year = 1000*6/12 = 500; remaining_days (Jul 1..Dec 31 incl) = 184;
    # round(500*184/365) = 252
    assert granted["annual_rental_fee_cents"] == 252
