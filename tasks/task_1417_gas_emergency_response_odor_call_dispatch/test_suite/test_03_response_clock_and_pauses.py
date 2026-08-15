"""Response-clock arithmetic, dual raw/adjusted variants, and pause rules
(PRD §2.7, §3.4, §3.8)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    setup_territory, setup_territory_technician, intake_call, triage, dispatch,
    arrive, set_clock, get_incident, create_report, get_report,
    create_pause_payload,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def _fixture_p2_incident_with_pause(do_arrive: bool = True):
    """P2 incident (60-min threshold) created at 00:00, triaged 00:01,
    dispatched 00:02; pause [00:10, 00:30) = 1200s; clock advanced to 01:20.
    When do_arrive=True the technician then arrives at 01:20.
    raw = 4800s; adjusted = 4800 - 1200 = 3600s."""
    terr, tech = setup_territory_technician()
    call = intake_call(terr["id"], address_line="10 Main St", caller_name="Ann",
                       caller_phone="555-0100")
    inc_id = call["incident_id"]
    set_clock("2026-08-01T00:01:00Z")
    triage(inc_id, "P2")
    set_clock("2026-08-01T00:02:00Z")
    disp = dispatch(inc_id, tech["id"])
    set_clock("2026-08-01T00:10:00Z")
    pause = validate_success(api_client.create_pause(
        inc_id, {"reason": "CUSTOMER_NOT_HOME"}, DISPATCHER), expected_status=201)
    set_clock("2026-08-01T00:30:00Z")
    validate_success(api_client.end_pause(pause["id"], DISPATCHER))
    set_clock("2026-08-01T01:20:00Z")
    if do_arrive:
        arrive(disp["id"], tech["id"])
    return terr, tech, call, disp, pause


class TestResponseElapsedRawVsAdjustedVariants:
    def test_raw_and_adjusted_diverge_on_same_segment(self, api):
        """PRD §2.7: "The `raw_elapsed_seconds` is the number of seconds from
        `response_clock_started_at` to the segment end, ignoring pauses
        entirely. The `pause_total_seconds` is the sum of the durations of the
        incident's response-clock pauses belonging to the current segment...
        The `adjusted_elapsed_seconds` is the raw elapsed minus the pause
        total, floored at zero so it can never go negative."

        Design: Difficulty/dual_variant_calc/response_elapsed_raw_vs_adjusted_variants
        """
        terr, tech, call, disp, pause = _fixture_p2_incident_with_pause(do_arrive=True)
        incident = get_incident(call["incident_id"])
        assert incident["raw_elapsed_seconds"] == 4800
        assert incident["adjusted_elapsed_seconds"] == 3600
        assert incident["pause_total_seconds"] == 1200
        assert incident["threshold_minutes"] == 60

    def test_adjusted_variant_drives_breach_while_raw_would_breach(self, api):
        """PRD §2.7: "the incident is in breach only when the elapsed figure
        exceeds the threshold in seconds, and an elapsed figure exactly equal
        to the threshold is compliant" and "Breach verdicts, and the
        incident's `adjusted_elapsed_seconds` field, always use the
        pause-subtracted variant; the raw variant, which ignores pauses,
        exists for the incident's `raw_elapsed_seconds` field and for the raw
        compliance counts in regulatory reports."

        Design: Difficulty/dual_variant_calc/response_elapsed_raw_vs_adjusted_variants
        """
        terr, tech, call, disp, pause = _fixture_p2_incident_with_pause(do_arrive=True)
        incident = get_incident(call["incident_id"])
        # adjusted 3600 == 60*60: equality is compliant under the adjusted
        # variant even though raw 4800 > 3600 would breach.
        assert incident["breach_class"] == "NONE"
        assert incident["first_arrival_at"].startswith("2026-08-01T01:20:00")
        assert incident["lifecycle_status"] == "ON_SCENE"


class TestAdjustedElapsedExactlyAtThreshold:
    def test_incident_at_exact_threshold_is_compliant(self, api):
        """PRD §2.7: "the incident is in breach only when the elapsed figure
        exceeds the threshold in seconds, and an elapsed figure exactly equal
        to the threshold is compliant."

        Design: Difficulty/boundary_precision_check/adjusted_elapsed_exactly_at_threshold_is_compliant
        """
        terr, tech, call, disp, pause = _fixture_p2_incident_with_pause(do_arrive=True)
        incident = get_incident(call["incident_id"])
        assert incident["adjusted_elapsed_seconds"] == 3600
        assert incident["threshold_minutes"] * 60 == 3600
        assert incident["breach_class"] == "NONE"

    def test_report_counts_raw_and_adjusted_variants_separately(self, api):
        """PRD §3.8: "`compliant_count_adjusted` counts determined incidents
        whose adjusted elapsed is at most the threshold in seconds, while
        `compliant_count_raw` counts those whose raw elapsed — pauses ignored
        — is at most the threshold."

        Design: Difficulty/boundary_precision_check/adjusted_elapsed_exactly_at_threshold_is_compliant
        """
        terr, tech, call, disp, pause = _fixture_p2_incident_with_pause(do_arrive=True)
        report = create_report(terr["id"])
        assert report["incident_count"] == 1
        assert report["determined_count"] == 1
        assert report["pending_count"] == 0
        assert report["compliant_count_adjusted"] == 1
        assert report["compliance_rate_adjusted"] == 1.0
        # raw 4800 > 3600: the two variants disagree on the same incident.
        assert report["compliant_count_raw"] == 0
        assert report["compliance_rate_raw"] == 0.0


class TestPauseEndRecomputesAdjustedElapsed:
    def test_open_pause_accrues_until_ended(self, api):
        """PRD §2.7: "a pause that is still open contributes from its
        `started_at` to the current logical time, evaluated at read time."

        Design: Corner/calculations/pause_end_recomputes_adjusted_elapsed
        """
        terr, tech = setup_territory_technician()
        call = intake_call(terr["id"], address_line="27 Pause St",
                           caller_name="W", caller_phone="555-0222")
        inc_id = call["incident_id"]
        triage(inc_id, "P2")
        dispatch(inc_id, tech["id"])
        set_clock("2026-08-01T00:10:00Z")
        pause = validate_success(api_client.create_pause(
            inc_id, {"reason": "CUSTOMER_NOT_HOME"}, DISPATCHER),
            expected_status=201)

        set_clock("2026-08-01T00:25:00Z")
        incident = get_incident(inc_id)
        assert incident["raw_elapsed_seconds"] == 1500
        assert incident["adjusted_elapsed_seconds"] == 600, (
            "open pause counts up to now: 1500 - 900")

        set_clock("2026-08-01T00:30:00Z")
        ended = validate_success(api_client.end_pause(pause["id"], DISPATCHER))
        assert ended["status"] == "CLOSED"

        set_clock("2026-08-01T00:40:00Z")
        incident = get_incident(inc_id)
        assert incident["raw_elapsed_seconds"] == 2400
        assert incident["pause_total_seconds"] == 1200
        assert incident["adjusted_elapsed_seconds"] == 1200

    def test_closed_pause_duration_is_ended_minus_started(self, api):
        """PRD §3.4: "A pause's `duration_seconds` reads as `ended_at` minus
        `started_at` once closed, and as the current logical time minus
        `started_at` while still open." and "Ending the pause — legal only
        while it is `OPEN`, otherwise `ERR_INVALID_STATE` — stamps `ended_at`
        from the logical clock, flips it to `CLOSED`, and recomputes the
        incident's `pause_total_seconds` and `breach_class`."

        Design: Corner/calculations/pause_end_recomputes_adjusted_elapsed
        """
        terr, tech = setup_territory_technician()
        call = intake_call(terr["id"], address_line="27 Pause St",
                           caller_name="W", caller_phone="555-0222")
        inc_id = call["incident_id"]
        triage(inc_id, "P2")
        dispatch(inc_id, tech["id"])
        set_clock("2026-08-01T00:10:00Z")
        pause = validate_success(api_client.create_pause(
            inc_id, {"reason": "CUSTOMER_NOT_HOME"}, DISPATCHER),
            expected_status=201)
        assert pause["status"] == "OPEN"
        # Open at read time (clock still 00:10): now - started_at.
        assert pause["duration_seconds"] == 0

        set_clock("2026-08-01T00:30:00Z")
        ended = validate_success(api_client.end_pause(pause["id"], DISPATCHER))
        assert ended["status"] == "CLOSED"
        assert ended["duration_seconds"] == 1200
        assert ended["ended_at"].startswith("2026-08-01T00:30:00")


class TestSecondOpenPauseRejected:
    def test_second_pause_while_one_open_rejected(self, api):
        """PRD §3.4: "Opening a pause requires the incident's lifecycle to be
        `TRIAGED` or `DISPATCHED`, requires that no arrival has been recorded
        yet, and requires that no other pause is currently open; violation of
        any of these yields `ERR_OPEN_PAUSE_EXISTS` (HTTP 409)."

        Design: Corner/validations/second_open_pause_rejected
        """
        terr = setup_territory()
        call = intake_call(terr["id"], address_line="29 Pause Ave",
                           caller_name="X", caller_phone="555-0223")
        inc_id = call["incident_id"]
        triage(inc_id, "P2")
        pause = validate_success(api_client.create_pause(
            inc_id, {"reason": "CUSTOMER_NOT_HOME"}, DISPATCHER),
            expected_status=201)

        resp = api_client.create_pause(inc_id, {"reason": "ACCESS_BLOCKED"},
                                       DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_OPEN_PAUSE_EXISTS)

        validate_success(api_client.end_pause(pause["id"], DISPATCHER))
        resp = api_client.create_pause(inc_id, {"reason": "ACCESS_BLOCKED"},
                                       DISPATCHER)
        pause2 = validate_success(resp, expected_status=201)
        assert pause2["status"] == "OPEN"


class TestEndAlreadyClosedPause:
    def test_end_closed_pause_returns_invalid_state(self, api):
        """PRD §3.4: "Ending the pause — legal only while it is `OPEN`,
        otherwise `ERR_INVALID_STATE` — stamps `ended_at` from the logical
        clock, flips it to `CLOSED`, and recomputes the incident's
        `pause_total_seconds` and `breach_class`."

        Design: Corner/validations/end_already_closed_pause_returns_invalid_state
        """
        terr = setup_territory()
        call = intake_call(terr["id"], address_line="31 Pause Blvd",
                           caller_name="Y", caller_phone="555-0224")
        inc_id = call["incident_id"]
        triage(inc_id, "P2")
        pause = validate_success(api_client.create_pause(
            inc_id, {"reason": "ACCESS_BLOCKED"}, DISPATCHER), expected_status=201)
        ended = validate_success(api_client.end_pause(pause["id"], DISPATCHER))
        assert ended["duration_seconds"] == 0

        resp = api_client.end_pause(pause["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        data = validate_success(api_client.get_incident(inc_id, SUPERVISOR))
        assert data["pause_total_seconds"] == 0, "rejected end must not mutate"
