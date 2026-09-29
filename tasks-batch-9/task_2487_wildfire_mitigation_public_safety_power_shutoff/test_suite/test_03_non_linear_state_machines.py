"""State machines that are not a straight line: the circuit cycle that returns to its
starting state, the event that tracks two dimensions at once, the bounded revision
loop, and the fork-join over two review tracks."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_REVIEW_ROUND_LIMIT
from test_helpers.assertions import (
    assert_2dp,
    assert_batch_outcome,
    assert_circuit_state,
    assert_event_dimensions,
    assert_filing_metrics,
    assert_filing_tracks,
    assert_fpi,
    assert_instant,
    assert_integer,
    assert_scope_counts,
    assert_scope_row,
)
from test_helpers.fixtures import (
    ADVANCE_SEND_AT,
    IMMINENT_SEND_AT,
    arm_event,
    book_project,
    build_feeder_chain,
    close_event,
    complete_patrol,
    compute_index,
    de_energize_event,
    declare_all_clear,
    dispatch_batch,
    file_observation,
    move_clock,
    open_event,
    open_filing,
    plan_batch,
    re_energize,
    read_batch,
    read_circuit,
    read_event,
    read_filing,
    read_patrol,
    read_project,
    read_records,
    register_circuit,
    register_customer,
    register_station,
    review_filing,
    review_project,
    schedule_patrol,
    scope_event,
    start_patrol,
    submit_filing,
    submit_project,
)
from test_helpers.test_users import (
    OFFICER_HEADERS,
    REVIEWER_2_HEADERS,
    REVIEWER_3_HEADERS,
    REVIEWER_ALPHA,
    REVIEWER_BETA,
    REVIEWER_GAMMA,
    REVIEWER_HEADERS,
)
from test_helpers.types import (
    ComputationVariant,
    CustomerClass,
    FilingDecision,
    HftdTier,
    NotificationStage,
    ProgramType,
    ReviewDecision,
    ReviewTrack,
    TelemetryStatus,
)

HOTEL_FIRST_FORECAST_DATE = "2026-08-20"
HOTEL_SECOND_FORECAST_DATE = "2026-08-24"
HOTEL_ONSET_AT = "2026-08-20T06:00:00Z"
HOTEL_ALL_CLEAR_AT = "2026-08-20T18:00:00Z"
HOTEL_ADVANCE_SEND_AT = "2026-08-18T06:00:00Z"
HOTEL_IMMINENT_SEND_AT = "2026-08-20T05:00:00Z"
HOTEL_DE_ENERGIZED_AT = "2026-08-20T07:00:00Z"
HOTEL_PATROL_START_AT = "2026-08-20T17:00:00Z"
HOTEL_PATROL_DONE_AT = "2026-08-20T19:00:00Z"
HOTEL_RESTORED_AT = "2026-08-20T20:00:00Z"
HOTEL_SECOND_ONSET_AT = "2026-08-24T06:00:00Z"
HOTEL_SECOND_ALL_CLEAR_AT = "2026-08-24T18:00:00Z"


def _hotel_circuit():
    """HOTEL scores 60.00 / R4 on two separate forecast days and serves one critical
    facility plus one medical-baseline household, both reachable."""
    hotel = register_circuit(
        circuit_code="HOTEL",
        district_code="D-SOUTH",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=8.0,
        equipment_condition_index=80,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    station = register_station(
        hotel["id"],
        station_code="WS-H1",
        elevation_ft=2000,
        representativeness_weight=1.00,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    for observed_at in ("2026-08-19T12:00:00Z", "2026-08-23T12:00:00Z"):
        file_observation(
            station["id"],
            observed_at,
            wind_gust_mph=52.0,
            relative_humidity_pct=62.0,
            temperature_f=94.0,
            dead_fuel_moisture_pct=9.0,
        )
    register_customer(
        hotel["id"],
        account_number="ACC-H1",
        customer_class=CustomerClass.CRITICAL_FACILITY.value,
        notification_channels=["VOICE"],
        address_zone_code="ZH",
    )
    register_customer(
        hotel["id"],
        account_number="ACC-H2",
        medical_baseline=True,
        notification_channels=["SMS"],
        address_zone_code="ZH",
    )
    return hotel


def _hotel_first_shutoff_cycle():
    """One complete shutoff of HOTEL: scoped, armed, executed, patrolled, restored at
    20:00Z and closed."""
    hotel = _hotel_circuit()
    index = compute_index(
        hotel["id"], HOTEL_FIRST_FORECAST_DATE, ComputationVariant.FORECAST.value
    )
    event = open_event(
        index["id"],
        onset_at=HOTEL_ONSET_AT,
        all_clear_at=HOTEL_ALL_CLEAR_AT,
        event_code="EV-H1",
    )
    scope_event(event["id"], event["version"])

    advance = plan_batch(
        event["id"], NotificationStage.ADVANCE_48H.value, HOTEL_ADVANCE_SEND_AT
    )
    move_clock(HOTEL_ADVANCE_SEND_AT)
    dispatch_batch(advance["id"])
    arm_event(event["id"])

    imminent = plan_batch(
        event["id"], NotificationStage.IMMINENT_1H.value, HOTEL_IMMINENT_SEND_AT
    )
    move_clock(HOTEL_IMMINENT_SEND_AT)
    dispatch_batch(imminent["id"])

    move_clock(HOTEL_DE_ENERGIZED_AT)
    de_energize_event(event["id"])
    declare_all_clear(event["id"])

    patrol = schedule_patrol(
        event["id"],
        hotel["id"],
        "2026-08-20T16:00:00Z",
        "2026-08-20T20:00:00Z",
        patrol_lead_user_id="crew_lead_h",
    )
    move_clock(HOTEL_PATROL_START_AT)
    start_patrol(patrol["id"])
    move_clock(HOTEL_PATROL_DONE_AT)
    patrol = complete_patrol(patrol["id"], 8.0)

    move_clock(HOTEL_RESTORED_AT)
    re_energize(hotel["id"])
    event = close_event(event["id"])

    return {"hotel": hotel, "index": index, "event": event, "patrol": patrol}


def _delta_circuit():
    """DELTA sits outside any high fire threat district, so its terrain multiplier is
    the 0.5 that pins the undergrounding score at 1.50."""
    return register_circuit(
        circuit_code="DELTA",
        district_code="D-WEST",
        hftd_tier=HftdTier.NON_HFTD.value,
        overhead_miles=4.0,
        equipment_condition_index=90,
    )


def _delta_underground_project(circuit_id):
    return book_project(
        circuit_id,
        project_code="MP-UG-1",
        program_type=ProgramType.UNDERGROUNDING.value,
        plan_year=2026,
        planned_miles=3.0,
        unit_cost_per_mile_cents=9000000,
    )


# --------------------------------------------------------------------------
# The circuit cycle that ends where it began
# --------------------------------------------------------------------------
def test_full_shutoff_cycle_returns_the_circuit_to_energized():
    """HOTEL leaves ENERGIZED, walks the whole shutoff, and comes back to ENERGIZED with
    its posture read from the forecast again rather than left LOCKED.

    "The circuit moves from `CLEARED_FOR_RESTORE` to `ENERGIZED` and its `risk_posture`
    is recomputed out of `LOCKED` against its latest `FORECAST` index."

    Design: Difficulty/non_linear_state_machine/circuit_energization_full_cycle_returns_to_energized
    """
    cycle = _hotel_first_shutoff_cycle()

    assert_fpi(cycle["index"], 60.00, "R4")

    restored = read_circuit(cycle["hotel"]["id"])
    assert_circuit_state(restored, energization_state="ENERGIZED", risk_posture="EXTREME")
    assert_2dp(restored["latest_forecast_fpi_score"], 60.00)
    assert restored["latest_forecast_fpi_tier"] == "R4"

    assert cycle["event"]["scope_status"] == "CLOSED"

    patrol = read_patrol(cycle["patrol"]["id"])
    assert patrol["status"] == "COMPLETED"
    assert_instant(patrol["completed_at"], HOTEL_PATROL_DONE_AT)
    assert_integer(patrol["ignition_risk_finding_count"], 0)


def test_a_closed_shutoff_no_longer_blocks_a_second_one_on_the_same_circuit():
    """The second loop is admitted because the first event is terminal, and the circuit
    now carries one restored scope row and one still open.

    "A candidate conflicts when some other event already holds it in a `CONFIRMED` scope
    row, that other event's `scope_status` is `SCOPED`, `ARMED`, `ACTIVE`, or
    `RESTORING`, and the two events' damaging-weather windows overlap — meaning the other
    event's onset is strictly earlier than this event's all-clear **and** this event's
    onset is strictly earlier than the other event's all-clear."

    Design: Difficulty/non_linear_state_machine/circuit_energization_full_cycle_returns_to_energized
    """
    cycle = _hotel_first_shutoff_cycle()
    hotel_id = cycle["hotel"]["id"]
    first_event_id = cycle["event"]["id"]

    second_index = compute_index(
        hotel_id, HOTEL_SECOND_FORECAST_DATE, ComputationVariant.FORECAST.value
    )
    second_event = open_event(
        second_index["id"],
        onset_at=HOTEL_SECOND_ONSET_AT,
        all_clear_at=HOTEL_SECOND_ALL_CLEAR_AT,
        event_code="EV-H2",
    )

    rescoped = scope_event(second_event["id"], second_event["version"])

    assert_fpi(second_index, 60.00, "R4")
    assert_event_dimensions(rescoped, scope_status="SCOPED")
    assert_scope_counts(rescoped, confirmed=1, excluded=0)

    history, meta = validate_paginated(
        api_client.list_circuit_event_scopes(hotel_id, OFFICER_HEADERS)
    )
    assert_integer(meta["total_count"], 2)
    first_rows = [r for r in history if r["psps_event_id"] == first_event_id]
    second_rows = [r for r in history if r["psps_event_id"] == second_event["id"]]
    assert_scope_row(first_rows, hotel_id, restored_at=HOTEL_RESTORED_AT)
    assert_scope_row(
        second_rows, hotel_id, scope_status="CONFIRMED", restored_at=None
    )


# --------------------------------------------------------------------------
# Two state dimensions on one row
# --------------------------------------------------------------------------
def test_notification_dimension_advances_while_the_operational_one_stands_still():
    """Three dispatches carry the notification dimension from NOT_STARTED to
    IMMINENT_SENT while the operational dimension stays SCOPED throughout.

    "Neither dimension gates the other's edges: an event may be sitting at `SCOPED` while
    its notification dimension has already reached `ADVANCE_SENT`, and the notification
    dimension may still read `NOT_STARTED` while the operational dimension is being
    scoped and re-scoped."

    Design: Difficulty/non_linear_state_machine/psps_event_two_independent_state_dimensions
    """
    ctx = build_feeder_chain()
    event = open_event(ctx["fpi_forecast"]["id"])
    scoped = scope_event(event["id"], event["version"])
    assert_event_dimensions(
        scoped, scope_status="SCOPED", notification_status="NOT_STARTED"
    )

    advance_48 = plan_batch(
        event["id"], NotificationStage.ADVANCE_48H.value, ADVANCE_SEND_AT
    )
    imminent = plan_batch(
        event["id"], NotificationStage.IMMINENT_1H.value, IMMINENT_SEND_AT
    )

    move_clock(ADVANCE_SEND_AT)
    dispatch_batch(advance_48["id"])
    assert_event_dimensions(
        read_event(event["id"]),
        scope_status="SCOPED",
        notification_status="ADVANCE_SENT",
    )

    move_clock(IMMINENT_SEND_AT)
    dispatch_batch(imminent["id"])
    assert_event_dimensions(
        read_event(event["id"]),
        scope_status="SCOPED",
        notification_status="IMMINENT_SENT",
    )

    armed = arm_event(event["id"])
    assert_event_dimensions(
        armed, scope_status="ARMED", notification_status="IMMINENT_SENT"
    )
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state="DE_ENERGIZATION_PENDING",
        risk_posture="LOCKED",
    )


def test_the_twenty_four_hour_batch_is_a_self_loop_on_the_notification_dimension():
    """The 24-hour dispatch writes its five records and settles, and the dimension holds
    at ADVANCE_SENT rather than skipping to IMMINENT_SENT.

    "Because the 48-hour and 24-hour batches both map to `ADVANCE_SENT`, dispatching the
    second of them when the dimension already reads `ADVANCE_SENT` is a self-loop:
    records are written, the batch settles, but the dimension neither regresses nor skips
    ahead."

    Design: Difficulty/non_linear_state_machine/psps_event_two_independent_state_dimensions
    """
    ctx = build_feeder_chain()
    event = open_event(ctx["fpi_forecast"]["id"])
    scope_event(event["id"], event["version"])
    advance_48 = plan_batch(
        event["id"], NotificationStage.ADVANCE_48H.value, ADVANCE_SEND_AT
    )
    advance_24 = plan_batch(
        event["id"], NotificationStage.ADVANCE_24H.value, "2026-08-14T18:00:00Z"
    )

    move_clock(ADVANCE_SEND_AT)
    dispatched_48 = dispatch_batch(advance_48["id"])
    move_clock("2026-08-14T18:00:00Z")
    dispatched_24 = dispatch_batch(advance_24["id"])

    assert_event_dimensions(
        read_event(event["id"]),
        scope_status="SCOPED",
        notification_status="ADVANCE_SENT",
    )
    assert_integer(dispatched_48["lead_time_minutes"], 2880)
    assert_integer(dispatched_24["lead_time_minutes"], 1440)
    assert_batch_outcome(
        read_batch(advance_24["id"]),
        "FAILED_PARTIAL",
        target_count=5,
        delivered_count=4,
        unreachable_count=1,
    )
    _, meta = read_records(notification_batch_id=advance_24["id"])
    assert_integer(meta["total_count"], 5)


# --------------------------------------------------------------------------
# The revision loop and its ceiling
# --------------------------------------------------------------------------
def test_a_third_revision_request_is_refused_after_two_rounds():
    """Two revision rounds are absorbed and the third is refused, leaving the work
    package sitting at SUBMITTED with its round counter pinned at two.

    "A `REQUEST_REVISION` decision on a `SUBMITTED` project moves it to
    `REVISION_REQUESTED`, increments `review_round` by one, records the acting
    `X-User-ID` as `last_revision_reviewer_user_id`, and stores the supplied
    `review_note` as `last_review_note`; it is permitted only while `review_round` is
    still below 2, so a third revision request against a project that has already
    absorbed two is refused with `ERR_REVIEW_ROUND_LIMIT`."

    Design: Difficulty/non_linear_state_machine/mitigation_revision_cycle_bounded_at_two_rounds
    """
    delta = _delta_circuit()
    project = _delta_underground_project(delta["id"])

    submit_project(project["id"])
    review_project(
        project["id"],
        ReviewDecision.REQUEST_REVISION.value,
        "round 1 - cost basis unclear",
    )
    submit_project(project["id"])
    review_project(
        project["id"],
        ReviewDecision.REQUEST_REVISION.value,
        "round 2 - scope still unclear",
    )
    submit_project(project["id"])

    response = api_client.review_mitigation_project(
        project["id"],
        factories.project_review_payload(
            ReviewDecision.REQUEST_REVISION.value, "round 3 attempt"
        ),
        REVIEWER_HEADERS,
    )
    validate_error(response, ERR_REVIEW_ROUND_LIMIT, 422)

    unchanged = read_project(project["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert_integer(unchanged["review_round"], 2)
    assert unchanged["last_revision_reviewer_user_id"] == REVIEWER_ALPHA
    assert unchanged["last_review_note"] == "round 2 - scope still unclear"


def test_resubmission_does_not_reset_the_revision_round_counter():
    """Each resubmission returns the package to SUBMITTED while the counter climbs 0, 1,
    2 and the derived figures stay where booking put them.

    "Re-submission closes the loop and — importantly — does **not** reset `review_round`,
    so the two-round ceiling survives across the whole life of the project."

    Design: Difficulty/non_linear_state_machine/mitigation_revision_cycle_bounded_at_two_rounds
    """
    delta = _delta_circuit()
    project = _delta_underground_project(delta["id"])
    assert_2dp(project["risk_reduction_score"], 1.50)
    assert_integer(project["budget_cents"], 27000000)
    assert_integer(project["review_round"], 0)

    first_submission = submit_project(project["id"])
    assert first_submission["status"] == "SUBMITTED"

    sent_back = review_project(
        project["id"],
        ReviewDecision.REQUEST_REVISION.value,
        "round 1 - cost basis unclear",
    )
    assert sent_back["status"] == "REVISION_REQUESTED"
    assert_integer(sent_back["review_round"], 1)

    second_submission = submit_project(project["id"])
    assert second_submission["status"] == "SUBMITTED"
    assert_integer(second_submission["review_round"], 1)

    sent_back_again = review_project(
        project["id"],
        ReviewDecision.REQUEST_REVISION.value,
        "round 2 - scope still unclear",
    )
    assert_integer(sent_back_again["review_round"], 2)

    third_submission = submit_project(project["id"])
    assert third_submission["status"] == "SUBMITTED"
    assert_integer(third_submission["review_round"], 2)
    assert_2dp(third_submission["risk_reduction_score"], 1.50)
    assert_integer(third_submission["budget_cents"], 27000000)


# --------------------------------------------------------------------------
# The fork-join over two review tracks
# --------------------------------------------------------------------------
def test_the_filing_join_completes_only_on_the_second_clearance():
    """The safety clearance leaves the filing waiting at SUBMITTED; the fiscal clearance
    completes the join and approves it.

    "A `CLEAR` decision on the **second** track does the same to its own track and then
    completes the join: because both tracks now read `CLEARED`, the filing advances to
    the terminal `APPROVED` status."

    Design: Difficulty/non_linear_state_machine/plan_filing_fork_join_requires_both_tracks_cleared
    """
    delta = _delta_circuit()
    project = _delta_underground_project(delta["id"])
    submit_project(project["id"])
    review_project(project["id"], ReviewDecision.APPROVE.value, "undergrounding accepted")

    filing = open_filing(filing_code="WMP-2026", plan_year=2026)
    submit_filing(filing["id"])

    safety_cleared = review_filing(
        filing["id"],
        ReviewTrack.SAFETY.value,
        FilingDecision.CLEAR.value,
        headers=REVIEWER_2_HEADERS,
    )
    assert_filing_tracks(
        safety_cleared,
        status="SUBMITTED",
        safety_review_state="CLEARED",
        fiscal_review_state="PENDING",
        safety_reviewer_user_id=REVIEWER_BETA,
        fiscal_reviewer_user_id=None,
    )

    joined = review_filing(
        filing["id"],
        ReviewTrack.FISCAL.value,
        FilingDecision.CLEAR.value,
        headers=REVIEWER_3_HEADERS,
    )

    assert_filing_tracks(
        joined,
        status="APPROVED",
        safety_review_state="CLEARED",
        fiscal_review_state="CLEARED",
        safety_reviewer_user_id=REVIEWER_BETA,
        fiscal_reviewer_user_id=REVIEWER_GAMMA,
        deficiency_round_count=0,
    )
    assert_filing_metrics(
        joined,
        qualifying_project_count=1,
        covered_conductor_miles_reported=0.0,
        underground_miles_reported=0.0,
        psps_event_count=0,
        avg_notification_lead_minutes=0.00,
        compliance_score=0.00,
    )


def test_a_deficiency_short_circuits_the_join_and_its_count_survives_resubmission():
    """The fiscal deficiency stops the join, records its note, and the round count it
    raised is still there after the cure round is filed and both tracks clear.

    "It sets the named track's state to `DEFICIENT` and its reviewer identifier to the
    acting `X-User-ID`, it stores the supplied `deficiency_note` as
    `last_deficiency_note`, and it increments `deficiency_round_count` by one."

    Design: Difficulty/non_linear_state_machine/plan_filing_fork_join_requires_both_tracks_cleared
    """
    delta = _delta_circuit()
    project = _delta_underground_project(delta["id"])
    submit_project(project["id"])
    review_project(project["id"], ReviewDecision.APPROVE.value, "undergrounding accepted")

    filing = open_filing(filing_code="WMP-2026", plan_year=2026)
    submit_filing(filing["id"])

    deficient = review_filing(
        filing["id"],
        ReviewTrack.FISCAL.value,
        FilingDecision.DEFICIENT.value,
        deficiency_note="cost tables missing",
        headers=REVIEWER_3_HEADERS,
    )
    assert_filing_tracks(
        deficient,
        status="DEFICIENCY_ISSUED",
        safety_review_state="PENDING",
        fiscal_review_state="DEFICIENT",
        fiscal_reviewer_user_id=REVIEWER_GAMMA,
        deficiency_round_count=1,
    )
    assert deficient["last_deficiency_note"] == "cost tables missing"

    cured = submit_filing(filing["id"])
    assert_filing_tracks(
        cured,
        status="SUBMITTED",
        safety_review_state="PENDING",
        fiscal_review_state="PENDING",
        safety_reviewer_user_id=None,
        fiscal_reviewer_user_id=None,
        deficiency_round_count=1,
    )

    review_filing(
        filing["id"],
        ReviewTrack.SAFETY.value,
        FilingDecision.CLEAR.value,
        headers=REVIEWER_2_HEADERS,
    )
    review_filing(
        filing["id"],
        ReviewTrack.FISCAL.value,
        FilingDecision.CLEAR.value,
        headers=REVIEWER_3_HEADERS,
    )

    approved = read_filing(filing["id"])
    assert_filing_tracks(approved, status="APPROVED", deficiency_round_count=1)
    assert approved["last_deficiency_note"] == "cost tables missing"
    assert_filing_metrics(approved, qualifying_project_count=1, compliance_score=0.00)
