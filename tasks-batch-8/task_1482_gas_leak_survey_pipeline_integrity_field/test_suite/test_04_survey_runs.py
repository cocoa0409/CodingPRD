"""Survey run submission, review, and rejection (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_field_technician_headers,
    make_integrity_analyst_headers,
    make_run,
    set_clock,
    setup_dispatched_route,
    setup_submitted_run,
    make_leak,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_field_technician_payload


class TestSurveyRunSubmission:
    def test_survey_run_submit_by_non_owner_rejected(self, api):
        """PRD §3.4: "the server stamps `technician_id` from `X-User-ID`" and
        "ownership first, so the caller must be the technician who recorded the
        run (`ERR_NOT_RUN_OWNER`, HTTP 403)".

        Design: Corner/state_machines/survey_run_submit_by_non_owner_rejected
        """
        ctx = setup_dispatched_route(route_code="R-OWN")
        run = make_run(ctx, ctx["route"]["id"], ctx["instrument"]["id"], submit=False)
        assert run["technician_id"] == ctx["ft"]["id"]

        other = get_success_data(api.create_field_technician(
            create_field_technician_payload(employee_code="FT-2", full_name="Tech Two"),
            ctx["ia_h"],
        ))
        resp = api.submit_run(run["id"], make_field_technician_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RUN_OWNER)

    def test_instrument_out_of_calibration_blocks_run_create(self, api):
        """PRD §3.4: "The instrument referenced must be `IN_SERVICE` at run start,
        and the same check is repeated when the run is submitted — both are
        enforced with `ERR_INSTRUMENT_OUT_OF_CALIBRATION`."

        Design: Corner/validations/instrument_out_of_calibration_blocks_run_create
        """
        ctx = setup_dispatched_route(route_code="R-IOC")
        set_clock(ctx, "2026-10-01T00:00:00Z")  # CGI calibration due was 2026-09-30
        resp = api.create_survey_run(
            {
                "route_id": ctx["route"]["id"],
                "instrument_id": ctx["instrument"]["id"],
                "distance_covered_feet": 1000.0,
            },
            ctx["ft_h"],
        )
        validate_error(resp, ApiErrorId.ERR_INSTRUMENT_OUT_OF_CALIBRATION)

    def test_state_check_on_submit_beats_instrument_safety(self, api):
        """PRD §2.5: "Only after those four classes pass are business rules
        evaluated: business-safety checks (instrument calibration status,
        segregation of duties, officer jurisdiction), then business-temporal
        checks" — the state class is evaluated before business-safety.
        PRD §3.4: "then state, so the run must be `DRAFT` (`ERR_RUN_NOT_DRAFT`),
        then instrument currency (`ERR_INSTRUMENT_OUT_OF_CALIBRATION`)" — so a
        double submit on a now-out-of-calibration instrument reports the state
        violation `ERR_RUN_NOT_DRAFT`.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_survey_run_submit
        """
        ctx = setup_submitted_run(route_code="R-PR1")
        set_clock(ctx, "2026-11-15T00:00:00Z")  # instrument now OUT_OF_CALIBRATION
        resp = api.submit_run(ctx["run"]["id"], ctx["ft_h"])
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_DRAFT)

    def test_instrument_safety_fires_when_state_is_clean(self, api):
        """PRD §3.4: "then instrument currency (`ERR_INSTRUMENT_OUT_OF_CALIBRATION`)"
        — with the run still `DRAFT` (no state violation), the safety check is the
        one that fires.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_survey_run_submit
        """
        ctx = setup_dispatched_route(route_code="R-PR1B")
        run = make_run(ctx, ctx["route"]["id"], ctx["instrument"]["id"], submit=False)
        set_clock(ctx, "2026-11-15T00:00:00Z")  # instrument now OUT_OF_CALIBRATION
        resp = api.submit_run(run["id"], ctx["ft_h"])
        validate_error(resp, ApiErrorId.ERR_INSTRUMENT_OUT_OF_CALIBRATION)


class TestSurveyRunReview:
    def test_survey_run_accept_below_coverage_rejected(self, api):
        """PRD §3.4: "the run's `coverage_pct` must be at least 95
        (`ERR_COVERAGE_BELOW_MINIMUM`), where `coverage_pct` is the sum of
        `length_feet` over the route's assignments marked `COVERED` divided by the
        total assigned length, multiplied by 100."

        Design: Corner/state_machines/survey_run_accept_below_coverage_rejected
        """
        # Single 1000-ft assignment; run covers only 400 ft -> 40%.
        ctx = setup_submitted_run(distance_covered_feet=400.0, route_code="R-COV")
        resp = api.accept_run(ctx["run"]["id"], ctx["ia_h"])
        validate_error(resp, ApiErrorId.ERR_COVERAGE_BELOW_MINIMUM)

    def test_segregation_of_duties_on_own_run_accept(self, api):
        """PRD §3.4: "segregation of duties requires the accepting analyst not be
        the technician who recorded the run (`ERR_SEGREGATION_OF_DUTIES`)"."

        Design: Corner/errors/segregation_of_duties_on_own_run_accept
        """
        ctx = setup_submitted_run(route_code="R-SOD")
        resp = api.accept_run(
            ctx["run"]["id"],
            # Role stays IntegrityAnalyst (accept is analyst-only) but X-User-ID
            # equals the technician_id recorded on the run.
            make_integrity_analyst_headers(ctx["ft"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_survey_run_reject_cascades_open_leaks_to_abandoned(self, api):
        """PRD §3.4: "Rejecting a run (`SUBMITTED → REJECTED`) requires only
        `SUBMITTED` state and abandons every `OPEN` leak that references the run —
        those leaks move to `ABANDONED_SEGMENT` — then recomputes counters and
        posture on the affected segments."

        Design: Corner/state_machines/survey_run_reject_cascades_open_leaks_to_abandoned
        """
        ctx = setup_submitted_run(route_code="R-REJ")
        segment = ctx["segments"][0]
        leak1 = make_leak(ctx, segment["id"], ctx["run"]["id"], concentration_ppm=12000.0)
        leak2 = make_leak(ctx, segment["id"], ctx["run"]["id"], concentration_ppm=13000.0)

        validate_success(api.reject_run(ctx["run"]["id"], ctx["ia_h"]))
        for leak in (leak1, leak2):
            after = get_success_data(api.get_leak(leak["id"], ctx["ia_h"]))
            assert after["status"] == "ABANDONED_SEGMENT"
        seg = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert seg["open_grade2_count"] == 0
