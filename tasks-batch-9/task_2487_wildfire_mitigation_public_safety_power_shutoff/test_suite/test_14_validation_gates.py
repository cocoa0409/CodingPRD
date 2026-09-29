"""The business gates: the notification and field-clearance conditions that must already
hold before a shutoff is armed, executed, restored or closed, the natural keys and
intervals that may not collide, and the ceilings that cap accumulation."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_ADVANCE_NOTIFICATION_MISSING,
    ERR_CRITICAL_NOTIFICATION_INCOMPLETE,
    ERR_DUPLICATE_CODE,
    ERR_EVENT_WINDOW_INVALID,
    ERR_IGNITION_RISK_DAMAGE_UNRESOLVED,
    ERR_MITIGATION_MILES_EXCEEDED,
    ERR_NO_ELIGIBLE_RESOURCE_CENTER,
    ERR_NO_QUALIFYING_CIRCUITS,
    ERR_NOTIFICATION_WINDOW_INVALID,
    ERR_PATROL_NOT_COMPLETED,
    ERR_PATROL_WINDOW_INVALID,
    ERR_PATROL_WINDOW_OVERLAP,
    ERR_RESOURCE_CENTER_DISTRICT_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_append_only_record,
    assert_batch_outcome,
    assert_center_state,
    assert_circuit_state,
    assert_event_dimensions,
    assert_fpi,
    assert_hardening_ledger,
    assert_impact_counts,
    assert_instant,
    assert_integer,
    assert_net_benefit,
    assert_record,
    assert_scope_counts,
    assert_scope_row,
    record_for,
)
from test_helpers.fixtures import (
    ADVANCE_SEND_AT,
    DE_ENERGIZED_AT,
    IMMINENT_SEND_AT,
    ONSET_AT,
    PATROL_CLOCK_AT,
    PATROL_DONE_AT,
    PATROL_START_AT,
    RESTORE_ALPHA_AT,
    RESTORE_BRAVO_AT,
    RESTORE_CHARLIE_AT,
    arm_event,
    build_advance_dispatched_event,
    build_approved_project,
    build_armed_event,
    build_feeder_chain,
    build_imminent_dispatched_event,
    build_patrolled_event,
    build_restoring_event,
    build_scoped_event,
    complete_patrol,
    compute_index,
    dispatch_batch,
    file_finding,
    file_observation,
    list_circuits,
    move_clock,
    open_event,
    open_filing,
    plan_batch,
    re_energize,
    read_batch,
    read_center,
    read_circuit,
    read_event,
    read_filing,
    read_patrol,
    read_project,
    read_records,
    read_scope_rows,
    record_completion,
    register_center,
    register_circuit,
    register_customer,
    register_station,
    schedule_patrol,
    scope_event,
    start_patrol,
)
from test_helpers.test_users import (
    CREW_LEAD_1,
    CREW_LEAD_2,
    INSPECTOR_HEADERS,
    LIAISON_HEADERS,
    OFFICER_2_HEADERS,
    OFFICER_HEADERS,
    PLANNER_HEADERS,
    SUPERVISOR_HEADERS,
    make_duty_officer_headers,
)
from test_helpers.types import (
    AccessibilityNeed,
    BatchStatus,
    BenefitVariant,
    Channel,
    ComputationVariant,
    CustomerClass,
    DamageSeverity,
    DeliveryStatus,
    EnergizationState,
    EventScopeStatus,
    FpiTier,
    HftdTier,
    NotificationStage,
    NotificationStatus,
    NotificationTier,
    PatrolMode,
    PatrolStatus,
    ProgramType,
    ProjectStatus,
    ResourceCenterStatus,
    RiskPosture,
    ScopeRowStatus,
    TelemetryStatus,
)

#: ALPHA's patrol closes at 01:00Z, which is the shared endpoint the overlap rule reads.
ALPHA_WINDOW_END_AT = "2026-08-17T01:00:00Z"
BRAVO_WINDOW_END_AT = "2026-08-17T02:00:00Z"
ONE_SECOND_AFTER_END_AT = "2026-08-17T01:00:01Z"

#: A window well clear of EV-1's own, so only its own ordering is under test.
LATER_ONSET_AT = "2026-08-20T18:00:00Z"
BACKWARDS_ALL_CLEAR_AT = "2026-08-20T06:00:00Z"

JUST_BEFORE_ONSET_AT = "2026-08-15T17:59:00Z"
AFTER_ONSET_AT = "2026-08-15T20:00:00Z"

FIRST_COMPLETION_DATE = "2026-07-01T00:00:00Z"
SECOND_COMPLETION_DATE = "2026-07-15T00:00:00Z"
THIRD_COMPLETION_DATE = "2026-07-20T00:00:00Z"

#: EV-MIKE's eight-hour window over district D-WEST.
MIKE_FORECAST_DATE = "2026-09-10"
MIKE_OBSERVED_AT = "2026-09-09T12:00:00Z"
MIKE_ONSET_AT = "2026-09-10T00:00:00Z"
MIKE_ALL_CLEAR_AT = "2026-09-10T08:00:00Z"
MIKE_ADVANCE_SEND_AT = "2026-09-08T00:00:00Z"

#: ECHO-R3's observation sits inside the 48-hour window of 2026-08-01.
ECHO_OBSERVED_AT = "2026-07-31T12:00:00Z"
ECHO_FORECAST_DATE = "2026-08-01"
ECHO_ONSET_AT = "2026-08-01T18:00:00Z"
ECHO_ALL_CLEAR_AT = "2026-08-02T18:00:00Z"


def _chain_with_an_unreachable_medical_account():
    """The feeder chain plus ACC-A4 — a medical-baseline account whose only consented
    channel is forbidden by its own accessibility need — driven to `ARMED` with both
    notice stages dispatched."""
    ctx = build_feeder_chain()
    ctx["cust_a4"] = register_customer(
        ctx["alpha"]["id"],
        account_number="ACC-A4",
        customer_class=CustomerClass.RESIDENTIAL.value,
        medical_baseline=True,
        notification_channels=[Channel.SMS.value],
        accessibility_needs=[AccessibilityNeed.AUDIO.value],
        address_zone_code="Z2",
    )
    ctx = build_scoped_event(ctx)
    ctx = build_advance_dispatched_event(ctx)
    ctx = build_armed_event(ctx)
    return build_imminent_dispatched_event(ctx)


def _armed_mike_event():
    """EV-MIKE armed over district D-WEST: TIER_2 MIKE with 11.0 overhead miles, an R4
    index of exactly 60.00, one critical facility and four medical-baseline accounts."""
    mike = register_circuit(
        circuit_code="MIKE",
        district_code="D-WEST",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=11.0,
        equipment_condition_index=80,
    )
    station = register_station(
        mike["id"],
        station_code="WS-MIKE",
        representativeness_weight=1.00,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    file_observation(
        station["id"],
        MIKE_OBSERVED_AT,
        wind_gust_mph=40.0,
        relative_humidity_pct=35.0,
        dead_fuel_moisture_pct=7.0,
    )
    index = compute_index(mike["id"], MIKE_FORECAST_DATE)
    register_customer(
        mike["id"],
        account_number="ACC-M1",
        customer_class=CustomerClass.CRITICAL_FACILITY.value,
        notification_channels=[Channel.SMS.value],
        address_zone_code="ZM",
    )
    for ordinal in range(2, 6):
        register_customer(
            mike["id"],
            account_number=f"ACC-M{ordinal}",
            medical_baseline=True,
            notification_channels=[Channel.SMS.value],
            address_zone_code="ZM",
        )
    event = open_event(
        index["id"],
        onset_at=MIKE_ONSET_AT,
        all_clear_at=MIKE_ALL_CLEAR_AT,
        event_code="EV-MIKE",
    )
    event = scope_event(event["id"], event["version"])
    batch = plan_batch(
        event["id"], NotificationStage.ADVANCE_48H.value, MIKE_ADVANCE_SEND_AT
    )
    move_clock(MIKE_ADVANCE_SEND_AT)
    dispatch_batch(batch["id"])
    return arm_event(event["id"])


def _echo_r3_event():
    """ECHO-R3 — a TIER_2 circuit whose mild weather scores 43.75 for an R3 tier — and a
    DRAFT event whose onset falls on the index's own forecast date."""
    echo = register_circuit(
        circuit_code="ECHO-R3",
        district_code="D-EAST",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=5.0,
        equipment_condition_index=80,
    )
    station = register_station(
        echo["id"],
        station_code="WS-ECHO",
        representativeness_weight=1.00,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    file_observation(
        station["id"],
        ECHO_OBSERVED_AT,
        wind_gust_mph=30.0,
        relative_humidity_pct=50.0,
        dead_fuel_moisture_pct=9.5,
    )
    index = compute_index(
        echo["id"], ECHO_FORECAST_DATE, ComputationVariant.FORECAST.value
    )
    event = open_event(
        index["id"],
        onset_at=ECHO_ONSET_AT,
        all_clear_at=ECHO_ALL_CLEAR_AT,
        event_code="EV-R3",
    )
    return echo, index, event


# --------------------------------------------------------------------------
# Priority 11 — the notification-completeness gates
# --------------------------------------------------------------------------
def test_arming_reads_the_advance_batchs_status_and_not_merely_its_existence():
    """The same arm call is refused twice and then accepted, with nothing about the event
    changing in between except that its 48-hour notice has actually gone out — and it goes
    out with one unreachable account, which is not enough to hold the arming back.

    "There must be an `ADVANCE_48H` batch for the event whose `status` is `DISPATCHED`
    or `FAILED_PARTIAL`, or the request is refused with
    `ERR_ADVANCE_NOTIFICATION_MISSING` — a partial delivery failure does **not** block
    arming, because the 48-hour warning has demonstrably gone out."

    "The batch settles at `DISPATCHED` when `unreachable_count` is zero and at
    `FAILED_PARTIAL` when it is greater than zero."

    Design: Corner/validations/arm_requires_a_dispatched_advance_notification_batch
    """
    ctx = build_scoped_event()

    unnotified = api_client.arm_psps_event(ctx["event_id"], OFFICER_HEADERS)
    validate_error(unnotified, ERR_ADVANCE_NOTIFICATION_MISSING, 422)

    batch = plan_batch(
        ctx["event_id"], NotificationStage.ADVANCE_48H.value, ADVANCE_SEND_AT
    )
    assert batch["status"] == BatchStatus.PENDING.value

    still_pending = api_client.arm_psps_event(ctx["event_id"], OFFICER_HEADERS)
    validate_error(still_pending, ERR_ADVANCE_NOTIFICATION_MISSING, 422)
    assert_event_dimensions(
        read_event(ctx["event_id"]),
        scope_status=EventScopeStatus.SCOPED.value,
        notification_status=NotificationStatus.NOT_STARTED.value,
    )

    move_clock(ADVANCE_SEND_AT)
    dispatch_batch(batch["id"])
    armed = validate_success(
        api_client.arm_psps_event(ctx["event_id"], OFFICER_HEADERS), 200
    )
    assert_event_dimensions(
        armed,
        scope_status=EventScopeStatus.ARMED.value,
        notification_status=NotificationStatus.ADVANCE_SENT.value,
    )
    assert_net_benefit(armed, net_benefit_ratio=0.3395)
    assert_batch_outcome(
        read_batch(batch["id"]), BatchStatus.FAILED_PARTIAL.value, 5, 4, 1
    )


def test_one_unreachable_medical_account_blocks_the_shutoff_a_standard_one_does_not():
    """The baseline chain already carries an unreachable standard-tier account and still
    de-energizes; adding a medical-baseline account with no permitted channel refuses the
    order, even though the event remained armable on the same numbers.

    "A missing batch, or a single unreachable critical-facility or medical-baseline
    account, refuses the order with `ERR_CRITICAL_NOTIFICATION_INCOMPLETE`."

    "This is exactly where a `FAILED_PARTIAL` batch diverges from a `DISPATCHED` one:
    it satisfies the advance gate but fails this one whenever the unreachable account
    was a tier-A or tier-B account, while an unreachable `TIER_C_STANDARD` account
    leaves the order clear to proceed."

    "Accessibility needs remove channels before the waterfall runs: a `TTY` need
    forbids `VOICE`, and an `AUDIO` need forbids both `SMS` and `EMAIL`."

    "Arming then cascades onto every `CONFIRMED`-scoped circuit whose
    `energization_state` is `ENERGIZED`, moving each to `DE_ENERGIZATION_PENDING`,
    setting each circuit's `risk_posture` to `LOCKED`, and incrementing each circuit's
    `version` by one along with the event's own."

    Design: Corner/validations/de_energize_requires_every_tier_a_and_tier_b_customer_delivered
    """
    ctx = _chain_with_an_unreachable_medical_account()

    move_clock(DE_ENERGIZED_AT)
    refused = api_client.de_energize_psps_event(ctx["event_id"], OFFICER_HEADERS)
    validate_error(refused, ERR_CRITICAL_NOTIFICATION_INCOMPLETE, 422)

    event = read_event(ctx["event_id"])
    assert_event_dimensions(event, scope_status=EventScopeStatus.ARMED.value)
    assert_instant(event["actual_de_energized_at"], None)
    assert_impact_counts(event, 6, 2, 1)
    assert_net_benefit(event, customer_impact_score=57.60, net_benefit_ratio=0.2688)

    # The arming cascade had already staged the breaker; the refused order opened none.
    alpha = read_circuit(ctx["alpha"]["id"])
    assert_circuit_state(
        alpha,
        energization_state=EnergizationState.DE_ENERGIZATION_PENDING.value,
        risk_posture=RiskPosture.LOCKED.value,
    )

    assert_batch_outcome(
        read_batch(ctx["batch_imminent"]["id"]),
        BatchStatus.FAILED_PARTIAL.value,
        6,
        4,
        2,
    )
    assert (
        ctx["cust_a4"]["notification_tier"] == NotificationTier.TIER_B_MEDICAL.value
    ), "a medical-baseline residential account is tier B"
    records, _ = read_records(notification_batch_id=ctx["batch_imminent"]["id"])
    assert_record(
        record_for(records, ctx["cust_a4"]["id"]),
        channel_used=None,
        delivery_status=DeliveryStatus.UNREACHABLE.value,
    )


# --------------------------------------------------------------------------
# Priority 10 — the field-clearance gates
# --------------------------------------------------------------------------
def test_only_the_ignition_risk_severity_holds_a_patrolled_circuit_out_of_service():
    """Two circuits finish their patrols with one finding each. BRAVO's MAJOR finding even
    demands a repair and re-energizes anyway; ALPHA's single IGNITION_RISK finding holds it
    at the post-patrol phase with its restoration stamp still empty.

    "The latest `COMPLETED` assignment on that circuit must have an
    `ignition_risk_finding_count` of exactly zero, otherwise
    `ERR_IGNITION_RISK_DAMAGE_UNRESOLVED` — and note that the rule reads **only** the
    latest completed patrol, which is what makes the repair loop work: after the crew
    repairs the damage, a follow-up assignment is started on the `CLEARED_FOR_RESTORE`
    circuit, taking it back to `PATROL_IN_PROGRESS`, and its clean completion becomes
    the latest completed patrol and clears the gate."

    "Filing a finding increments the assignment's `damage_finding_count` and, when the
    `severity` is `IGNITION_RISK`, also its `ignition_risk_finding_count`, and
    increments the assignment's `version`."

    "Four resource types are **append-only records** and carry only `id` and
    `created_at`: both `updated_at` and `version` are absent from their
    representations entirely."

    Design: Corner/validations/re_energization_requires_a_clearing_patrol_with_no_ignition_risk_finding
    """
    ctx = build_restoring_event()
    alpha_patrol = schedule_patrol(
        ctx["event_id"],
        ctx["alpha"]["id"],
        PATROL_START_AT,
        ALPHA_WINDOW_END_AT,
        patrol_lead_user_id=CREW_LEAD_1,
    )
    bravo_patrol = schedule_patrol(
        ctx["event_id"],
        ctx["bravo"]["id"],
        PATROL_START_AT,
        BRAVO_WINDOW_END_AT,
        patrol_lead_user_id=CREW_LEAD_2,
    )

    move_clock(PATROL_CLOCK_AT)
    start_patrol(alpha_patrol["id"])
    start_patrol(bravo_patrol["id"])
    file_finding(
        alpha_patrol["id"],
        DamageSeverity.IGNITION_RISK.value,
        description="arcing scar on the tap span crossarm",
        requires_repair=False,
    )
    file_finding(
        bravo_patrol["id"],
        DamageSeverity.MAJOR.value,
        description="split crossarm at pole 22",
        requires_repair=True,
    )
    move_clock(PATROL_DONE_AT)
    complete_patrol(alpha_patrol["id"], 7.0)
    complete_patrol(bravo_patrol["id"], 6.0)

    move_clock(RESTORE_ALPHA_AT)
    blocked = api_client.re_energize_circuit(ctx["alpha"]["id"], OFFICER_HEADERS)
    validate_error(blocked, ERR_IGNITION_RISK_DAMAGE_UNRESOLVED, 422)
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state=EnergizationState.CLEARED_FOR_RESTORE.value,
    )
    assert_scope_row(
        read_scope_rows(ctx["event_id"]), ctx["alpha"]["id"], restored_at=None
    )

    validate_success(
        api_client.re_energize_circuit(ctx["bravo"]["id"], OFFICER_HEADERS), 200
    )
    assert_circuit_state(
        read_circuit(ctx["bravo"]["id"]),
        energization_state=EnergizationState.ENERGIZED.value,
    )

    alpha_done = read_patrol(alpha_patrol["id"])
    assert_integer(alpha_done["damage_finding_count"], 1)
    assert_integer(alpha_done["ignition_risk_finding_count"], 1)
    bravo_done = read_patrol(bravo_patrol["id"])
    assert_integer(bravo_done["damage_finding_count"], 1)
    assert_integer(bravo_done["ignition_risk_finding_count"], 0)

    findings, meta = validate_paginated(
        api_client.list_patrol_damage_findings(
            alpha_patrol["id"],
            SUPERVISOR_HEADERS,
            {"severity": DamageSeverity.IGNITION_RISK.value},
        )
    )
    assert_integer(meta["total_count"], 1)
    assert_append_only_record(findings[0])


def test_closing_waits_for_the_last_confirmed_circuit_to_carry_its_restoration_stamp():
    """With ALPHA and BRAVO back in service the close is still refused, because the gate is
    an aggregate over the event's confirmed scope rows; the third stamp both permits the
    close and fixes the realised restoration instant.

    "It is admitted only while the event's `scope_status` is `RESTORING`, otherwise
    `ERR_EVENT_NOT_IN_RESTORATION`, and only when every `CONFIRMED` scope row of the
    event already carries a `restored_at` — equivalently, when `actual_restored_at` is
    non-null — otherwise `ERR_PATROL_NOT_COMPLETED`."

    "Closing moves the event to the terminal `CLOSED` status, freezes its `POST_EVENT`
    scores, demobilizes any resource center still `ACTIVATED` for the event, makes the
    event eligible for plan-filing metric roll-up, and increments the event's
    `version`."

    "The circuit's scope row for the event has its `restored_at` stamped from the
    logical clock."

    Design: Corner/validations/closing_an_event_requires_every_confirmed_scope_to_carry_a_restoration_stamp
    """
    ctx = build_patrolled_event()

    move_clock(RESTORE_ALPHA_AT)
    re_energize(ctx["alpha"]["id"])
    move_clock(RESTORE_BRAVO_AT)
    re_energize(ctx["bravo"]["id"])

    early = api_client.close_psps_event(ctx["event_id"], OFFICER_HEADERS)
    validate_error(early, ERR_PATROL_NOT_COMPLETED, 422)
    pending = read_event(ctx["event_id"])
    assert_event_dimensions(pending, scope_status=EventScopeStatus.RESTORING.value)
    assert_instant(pending["actual_restored_at"], None)
    assert_net_benefit(pending, variant=BenefitVariant.PRE_EVENT.value)

    move_clock(RESTORE_CHARLIE_AT)
    re_energize(ctx["charlie"]["id"])
    closed = validate_success(
        api_client.close_psps_event(ctx["event_id"], OFFICER_HEADERS), 200
    )
    assert_event_dimensions(closed, scope_status=EventScopeStatus.CLOSED.value)
    assert_instant(closed["actual_restored_at"], RESTORE_CHARLIE_AT)
    assert_net_benefit(closed, variant=BenefitVariant.POST_EVENT.value)

    rows = read_scope_rows(ctx["event_id"])
    assert_scope_row(rows, ctx["alpha"]["id"], restored_at=RESTORE_ALPHA_AT)
    assert_scope_row(rows, ctx["charlie"]["id"], restored_at=RESTORE_CHARLIE_AT)


# --------------------------------------------------------------------------
# Priority 12 — segregation of duties
# --------------------------------------------------------------------------
def test_the_clearing_patrol_lead_may_not_restore_the_circuit_they_signed_off():
    """One endpoint, one role and one circuit: the refusal turns entirely on which
    `X-User-ID` acts, because the counterparty is the clearing patrol's own crew lead.

    "Finally, the acting `X-User-ID` must differ from that clearing assignment's
    `patrol_lead_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

    "Each is evaluated as an exact string comparison between the acting `X-User-ID`
    and a previously recorded identifier, and each failure carries
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    "That crew lead identifier is the segregation-of-duties counterparty for
    re-energization, so it is worth recording accurately."

    Design: Corner/validations/re_energization_by_the_clearing_patrol_lead_is_segregation_of_duties
    """
    ctx = build_patrolled_event()

    move_clock(RESTORE_ALPHA_AT)
    conflicted = api_client.re_energize_circuit(
        ctx["alpha"]["id"], make_duty_officer_headers(CREW_LEAD_1)
    )
    validate_error(conflicted, ERR_SEGREGATION_OF_DUTIES, 403)
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state=EnergizationState.CLEARED_FOR_RESTORE.value,
    )

    validate_success(
        api_client.re_energize_circuit(ctx["alpha"]["id"], OFFICER_2_HEADERS), 200
    )
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state=EnergizationState.ENERGIZED.value,
    )
    assert_scope_row(
        read_scope_rows(ctx["event_id"]),
        ctx["alpha"]["id"],
        restored_at=RESTORE_ALPHA_AT,
    )
    assert read_patrol(ctx["patrol_alpha"]["id"])["patrol_lead_user_id"] == CREW_LEAD_1


# --------------------------------------------------------------------------
# Priority 15 — natural-key uniqueness
# --------------------------------------------------------------------------
def test_a_taken_circuit_code_a_taken_filing_code_and_a_taken_plan_year_share_one_code():
    """A plan filing has two independent uniqueness axes, so a fresh code with a taken year
    and a taken code with a fresh year are both collisions — and three rejections leave
    neither axis poisoned for the fourth, legitimate filing.

    "**Natural-key uniqueness** — `circuit_code`, `station_code`, `event_code`,
    `account_number`, `project_code`, `resource_center_code`, `filing_code`, and a plan
    filing's `plan_year` are each unique across all rows of their own entity."

    "A `GridPlanner` opens a filing with a `filing_code` unique across all filings and
    3 to 40 characters long, and a `plan_year` from 2020 through 2100 inclusive that
    must **also** be unique across all filings — one filing per plan year, and a
    collision on either key is refused with `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/duplicate_codes_and_a_duplicate_filing_plan_year_are_rejected
    """
    alpha = register_circuit(circuit_code="ALPHA")
    cycle = open_filing(filing_code="WMP-CYCLE", plan_year=2026)

    duplicate_circuit = api_client.create_circuit(
        factories.circuit_payload(
            circuit_code="ALPHA",
            district_code="D-SOUTH",
            hftd_tier=HftdTier.TIER_1.value,
            overhead_miles=2.0,
            equipment_condition_index=90,
        ),
        PLANNER_HEADERS,
    )
    validate_error(duplicate_circuit, ERR_DUPLICATE_CODE, 409)

    duplicate_year = api_client.create_plan_filing(
        factories.plan_filing_payload(plan_year=2026, filing_code="WMP-OTHER"),
        PLANNER_HEADERS,
    )
    validate_error(duplicate_year, ERR_DUPLICATE_CODE, 409)

    duplicate_code = api_client.create_plan_filing(
        factories.plan_filing_payload(plan_year=2027, filing_code="WMP-CYCLE"),
        PLANNER_HEADERS,
    )
    validate_error(duplicate_code, ERR_DUPLICATE_CODE, 409)

    fresh = validate_success(
        api_client.create_plan_filing(
            factories.plan_filing_payload(plan_year=2027, filing_code="WMP-2027"),
            PLANNER_HEADERS,
        ),
        201,
    )
    assert fresh["filing_code"] == "WMP-2027"
    assert_integer(fresh["plan_year"], 2027)

    assert read_filing(cycle["id"])["filing_code"] == "WMP-CYCLE"
    assert_integer(read_filing(cycle["id"])["plan_year"], 2026)
    rows, meta = list_circuits()
    assert_integer(meta["total_count"], 1)
    assert rows[0]["id"] == alpha["id"]


# --------------------------------------------------------------------------
# Priority 13 — interval and lead-time well-formedness
# --------------------------------------------------------------------------
def test_a_zero_length_window_is_a_violation_for_both_events_and_patrols():
    """Both interval rules demand strict ordering, so the degenerate equal-endpoint window
    is a refusal rather than a boundary success — on an event, and on a patrol whose
    circuit and governing event are otherwise perfectly eligible.

    "**Interval and lead-time well-formedness** — `forecast_all_clear_at` is strictly
    later than `forecast_onset_at`; `window_end_at` is strictly later than
    `window_start_at`; an advance-stage or imminent-stage batch's `scheduled_send_at`
    is strictly earlier than the event's `forecast_onset_at`; and the realised dispatch
    lead time meets the stage minimum."

    "The applicable code is `ERR_EVENT_WINDOW_INVALID`, `ERR_PATROL_WINDOW_INVALID`,
    `ERR_NOTIFICATION_WINDOW_INVALID`, or `ERR_NOTIFICATION_LEAD_TIME_SHORT`, each
    HTTP 422."

    Design: Corner/validations/inverted_event_and_patrol_windows_are_rejected
    """
    ctx = build_restoring_event()

    zero_length = api_client.create_psps_event(
        factories.psps_event_payload(
            ctx["fpi_forecast"]["id"],
            LATER_ONSET_AT,
            LATER_ONSET_AT,
            event_code="EV-ZERO",
        ),
        OFFICER_HEADERS,
    )
    validate_error(zero_length, ERR_EVENT_WINDOW_INVALID, 422)

    backwards = api_client.create_psps_event(
        factories.psps_event_payload(
            ctx["fpi_forecast"]["id"],
            LATER_ONSET_AT,
            BACKWARDS_ALL_CLEAR_AT,
            event_code="EV-BACK",
        ),
        OFFICER_HEADERS,
    )
    validate_error(backwards, ERR_EVENT_WINDOW_INVALID, 422)

    zero_patrol = api_client.create_patrol_assignment(
        factories.patrol_assignment_payload(
            ctx["event_id"],
            ctx["alpha"]["id"],
            PATROL_START_AT,
            PATROL_START_AT,
            patrol_lead_user_id="crew_lead_7",
        ),
        SUPERVISOR_HEADERS,
    )
    validate_error(zero_patrol, ERR_PATROL_WINDOW_INVALID, 422)

    events, event_meta = validate_paginated(api_client.list_psps_events(OFFICER_HEADERS))
    assert_integer(event_meta["total_count"], 1)
    assert [row["event_code"] for row in events] == ["EV-1"]

    _, patrol_meta = validate_paginated(
        api_client.list_patrol_assignments(
            SUPERVISOR_HEADERS, {"psps_event_id": ctx["event_id"]}
        )
    )
    assert_integer(patrol_meta["total_count"], 0)


def test_the_pre_onset_send_window_binds_the_advance_stages_and_not_the_activation_one():
    """The very same `scheduled_send_at` field is legal or illegal depending only on which
    stage names it: an advance batch at the onset instant is refused, a minute earlier is
    accepted, and an activation batch two hours after onset is accepted too.

    "Planning is refused with `ERR_NO_CIRCUITS_IN_SCOPE` when the event's
    `confirmed_scope_count` is zero — there is nobody to notify — and, for the three
    pre-onset stages `ADVANCE_48H`, `ADVANCE_24H`, and `IMMINENT_1H`, with
    `ERR_NOTIFICATION_WINDOW_INVALID` when `scheduled_send_at` falls at or after the
    event's `forecast_onset_at`."

    "A planned batch starts with `status` at `PENDING`, `dispatched_at` and
    `lead_time_minutes` at null, and `target_count`, `delivered_count`, and
    `unreachable_count` all at zero."

    Design: Corner/validations/the_advance_window_rule_applies_only_to_advance_stages
    """
    ctx = build_scoped_event()

    at_onset = api_client.create_notification_batch(
        factories.notification_batch_payload(
            ctx["event_id"], ONSET_AT, stage=NotificationStage.ADVANCE_24H.value
        ),
        LIAISON_HEADERS,
    )
    validate_error(at_onset, ERR_NOTIFICATION_WINDOW_INVALID, 422)

    one_minute_earlier = validate_success(
        api_client.create_notification_batch(
            factories.notification_batch_payload(
                ctx["event_id"],
                JUST_BEFORE_ONSET_AT,
                stage=NotificationStage.ADVANCE_24H.value,
            ),
            LIAISON_HEADERS,
        ),
        201,
    )
    assert one_minute_earlier["status"] == BatchStatus.PENDING.value
    assert_instant(one_minute_earlier["dispatched_at"], None)
    assert one_minute_earlier["lead_time_minutes"] is None
    assert_integer(one_minute_earlier["target_count"], 0)

    after_onset = validate_success(
        api_client.create_notification_batch(
            factories.notification_batch_payload(
                ctx["event_id"],
                AFTER_ONSET_AT,
                stage=NotificationStage.ACTIVATION.value,
            ),
            LIAISON_HEADERS,
        ),
        201,
    )
    assert after_onset["stage"] == NotificationStage.ACTIVATION.value
    assert after_onset["status"] == BatchStatus.PENDING.value

    _, meta = validate_paginated(
        api_client.list_event_notification_batches(ctx["event_id"], LIAISON_HEADERS)
    )
    assert_integer(meta["total_count"], 2)


# --------------------------------------------------------------------------
# Priority 16 — interval-occupation conflicts
# --------------------------------------------------------------------------
def test_two_patrol_windows_that_share_only_an_endpoint_already_conflict():
    """Patrol windows are compared as closed intervals, so a second ALPHA patrol starting
    exactly at the first one's end is a conflict, one starting a single second later is
    not, and the same instant is free on a different circuit.

    "A reservation is admitted only when the circuit's `energization_state` is
    `DE_ENERGIZED`, `PATROL_IN_PROGRESS`, or `CLEARED_FOR_RESTORE`, otherwise
    `ERR_CIRCUIT_NOT_DE_ENERGIZED`, and it is refused with
    `ERR_PATROL_WINDOW_OVERLAP` when its closed window from `window_start_at` through
    `window_end_at` intersects the closed window of another assignment on the same
    circuit whose `status` is `SCHEDULED` or `IN_PROGRESS` — shared endpoints count as
    an intersection."

    "**Interval-occupation conflicts** — a circuit may not sit in a `CONFIRMED` scope
    of two live events whose windows overlap; a resource center may not be activated
    when the new event's onset falls strictly inside its previous service window
    extended by the reset buffer; and a circuit may not hold two `SCHEDULED` or
    `IN_PROGRESS` patrol windows whose closed intervals intersect."

    Design: Corner/validations/patrol_windows_touching_at_a_single_instant_are_rejected_as_an_overlap
    """
    ctx = build_restoring_event()
    first = schedule_patrol(
        ctx["event_id"],
        ctx["alpha"]["id"],
        PATROL_START_AT,
        ALPHA_WINDOW_END_AT,
        patrol_lead_user_id=CREW_LEAD_1,
    )
    assert first["status"] == PatrolStatus.SCHEDULED.value

    touching = api_client.create_patrol_assignment(
        factories.patrol_assignment_payload(
            ctx["event_id"],
            ctx["alpha"]["id"],
            ALPHA_WINDOW_END_AT,
            BRAVO_WINDOW_END_AT,
            patrol_lead_user_id="crew_lead_4",
            patrol_mode=PatrolMode.DRONE.value,
        ),
        SUPERVISOR_HEADERS,
    )
    validate_error(touching, ERR_PATROL_WINDOW_OVERLAP, 409)

    one_second_later = validate_success(
        api_client.create_patrol_assignment(
            factories.patrol_assignment_payload(
                ctx["event_id"],
                ctx["alpha"]["id"],
                ONE_SECOND_AFTER_END_AT,
                BRAVO_WINDOW_END_AT,
                patrol_lead_user_id="crew_lead_4",
                patrol_mode=PatrolMode.DRONE.value,
            ),
            SUPERVISOR_HEADERS,
        ),
        201,
    )
    assert one_second_later["status"] == PatrolStatus.SCHEDULED.value

    elsewhere = validate_success(
        api_client.create_patrol_assignment(
            factories.patrol_assignment_payload(
                ctx["event_id"],
                ctx["bravo"]["id"],
                ALPHA_WINDOW_END_AT,
                BRAVO_WINDOW_END_AT,
                patrol_lead_user_id="crew_lead_5",
                patrol_mode=PatrolMode.DRONE.value,
            ),
            SUPERVISOR_HEADERS,
        ),
        201,
    )
    assert elsewhere["circuit_id"] == ctx["bravo"]["id"]

    _, meta = validate_paginated(
        api_client.list_patrol_assignments(
            SUPERVISOR_HEADERS, {"circuit_id": ctx["alpha"]["id"]}
        )
    )
    assert_integer(meta["total_count"], 2)


# --------------------------------------------------------------------------
# Priority 17 — ceilings and thresholds
# --------------------------------------------------------------------------
def test_the_completion_ceiling_is_cumulative_and_its_boundary_is_inclusive():
    """Two and a half miles then two more are each comfortably under a four-mile plan, yet
    the second is refused because the ceiling reads the running total; two and a half then
    one and a half land exactly on the plan and complete the project.

    "Each record adds `completed_miles_delta` to the project's `completed_miles`; the
    call is refused with `ERR_MITIGATION_MILES_EXCEEDED` when the resulting cumulative
    total would exceed `planned_miles`, and with `ERR_PROJECT_INVALID_STATE` when the
    project's `status` is neither `APPROVED` nor `IN_EXECUTION`."

    "The first record advances the project from `APPROVED` to `IN_EXECUTION`; further
    records that leave the cumulative total strictly below `planned_miles` keep it in
    `IN_EXECUTION`; and the record whose cumulative total lands exactly on
    `planned_miles` advances it to `COMPLETED`."

    "Covered conductor earns partial credit and undergrounding earns full credit: the
    numerator is `covered_conductor_miles` multiplied by 0.6 plus `underground_miles`
    multiplied by 1.0, and the denominator is the circuit's immutable
    `overhead_miles`."

    Design: Corner/validations/cumulative_completion_deltas_may_not_exceed_planned_miles
    """
    alpha = register_circuit(circuit_code="ALPHA")
    project = build_approved_project(
        alpha["id"],
        project_code="MP-CC",
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=4.0,
        unit_cost_per_mile_cents=1250000,
    )

    started = record_completion(
        project["id"], 2.5, FIRST_COMPLETION_DATE, read_circuit(alpha["id"])["version"]
    )
    assert started["status"] == ProjectStatus.IN_EXECUTION.value
    assert_1dp(started["completed_miles"], 2.5)

    mid_version = read_circuit(alpha["id"])["version"]
    over_the_plan = api_client.record_project_completion(
        project["id"],
        factories.record_completion_payload(2.0, SECOND_COMPLETION_DATE, mid_version),
        INSPECTOR_HEADERS,
    )
    validate_error(over_the_plan, ERR_MITIGATION_MILES_EXCEEDED, 422)
    assert_1dp(read_project(project["id"])["completed_miles"], 2.5)
    held = read_circuit(alpha["id"])
    assert_integer(held["version"], mid_version)
    assert_hardening_ledger(held, 2.5, 0.0, 0.2143)

    finished = record_completion(
        project["id"], 1.5, THIRD_COMPLETION_DATE, mid_version
    )
    assert finished["status"] == ProjectStatus.COMPLETED.value
    assert_1dp(finished["completed_miles"], 4.0)
    assert_hardening_ledger(read_circuit(alpha["id"]), 4.0, 0.0, 0.3429)


def test_a_wrong_district_site_is_a_loud_refusal_and_never_a_selector_candidate():
    """The two activation modes fail differently over the same barren pool: the selector
    reports an empty pool, naming the out-of-district site reports the mismatch, and after
    either refusal the site is still on standby and the event has no coverage credit.

    "In **explicit mode**, each named site is validated in the order the request array
    lists them, and every breach is reported loudly rather than silently skipped: a
    site whose `status` is already `ACTIVATED` refuses the call with
    `ERR_RESOURCE_CENTER_ALREADY_ACTIVE`, a site whose `district_code` is not among the
    scoped districts refuses it with `ERR_RESOURCE_CENTER_DISTRICT_MISMATCH`, and a
    site with a reset-buffer collision refuses it with
    `ERR_RESOURCE_CENTER_BUFFER_CONFLICT`."

    "In **selector mode**, the server builds the candidate pool itself: sites whose
    `status` is `STANDBY` or `DEMOBILIZED`, whose `district_code` is among the scoped
    districts, and which have no reset-buffer collision."

    "If the ranked pool is empty while the required capacity is greater than zero, the
    call is refused with `ERR_NO_ELIGIBLE_RESOURCE_CENTER`."

    "`crc_capacity_served` is the sum of `site_capacity` over the resource centers
    whose `psps_event_id` is this event and whose `status` is `ACTIVATED`; sites that
    are `DEMOBILIZED` or `STANDBY` contribute nothing."

    "A new site starts with `status` at `STANDBY` and with `psps_event_id`,
    `activated_at`, `demobilized_at`, `last_served_all_clear_at`, and
    `activation_order` all null."

    Design: Corner/validations/named_resource_center_outside_the_scoped_district_is_rejected
    """
    event = _armed_mike_event()
    assert_integer(event["crc_capacity_required"], 5)

    empty_pool = api_client.activate_resource_centers(
        event["id"], factories.activation_payload(), OFFICER_HEADERS
    )
    validate_error(empty_pool, ERR_NO_ELIGIBLE_RESOURCE_CENTER, 422)

    outsider = register_center(
        resource_center_code="CRC-E9",
        district_code="D-EAST",
        site_capacity=50,
        accessibility_certified=True,
    )
    mismatch = api_client.activate_resource_centers(
        event["id"],
        factories.activation_payload([outsider["id"]]),
        OFFICER_HEADERS,
    )
    validate_error(mismatch, ERR_RESOURCE_CENTER_DISTRICT_MISMATCH, 422)

    still_empty = api_client.activate_resource_centers(
        event["id"], factories.activation_payload(), OFFICER_HEADERS
    )
    validate_error(still_empty, ERR_NO_ELIGIBLE_RESOURCE_CENTER, 422)

    standing_by = read_center(outsider["id"])
    assert_center_state(
        standing_by, ResourceCenterStatus.STANDBY.value, psps_event_id=None
    )
    assert standing_by["activation_order"] is None
    assert_instant(standing_by["activated_at"], None)

    after = read_event(event["id"])
    assert_integer(after["crc_capacity_served"], 0)
    assert_net_benefit(
        after, crc_mitigation_credit=0.00, net_benefit_ratio=0.2661
    )


# --------------------------------------------------------------------------
# Priority 14 — required related rows
# --------------------------------------------------------------------------
def test_an_r3_circuit_leaves_the_candidate_set_empty_and_the_scope_call_refused():
    """A mild forecast still produces an index, a posture and an openable event, but the
    scope walk needs an R4-or-R5 tier on the onset date, so the whole call is refused
    rather than producing an event with no scope rows at all.

    "A circuit is a primary candidate when its `energization_state` is `ENERGIZED`, a
    qualifying index exists for it, and that index's `fpi_tier` is `R4` or `R5`."

    "If no circuit qualifies, the call is refused with `ERR_NO_QUALIFYING_CIRCUITS`."

    "If the selected index's `fpi_tier` is `R4` or `R5` the posture is `EXTREME`; if
    it is `R3` the posture is `ELEVATED`; and for `R1` or `R2` the posture is
    `NORMAL`."

    Design: Corner/validations/scoping_a_circuit_below_the_de_energization_tier_set_is_rejected
    """
    echo, index, event = _echo_r3_event()
    assert_fpi(index, 43.75, FpiTier.R3.value)

    refused = api_client.scope_psps_event(
        event["id"], factories.scope_payload(event["version"]), OFFICER_HEADERS
    )
    validate_error(refused, ERR_NO_QUALIFYING_CIRCUITS, 422)

    unscoped = read_event(event["id"])
    assert_event_dimensions(unscoped, scope_status=EventScopeStatus.DRAFT.value)
    assert_scope_counts(unscoped, 0, 0)

    _, meta = validate_paginated(
        api_client.list_event_scopes(event["id"], OFFICER_HEADERS)
    )
    assert_integer(meta["total_count"], 0)

    assert_circuit_state(
        read_circuit(echo["id"]),
        energization_state=EnergizationState.ENERGIZED.value,
        risk_posture=RiskPosture.ELEVATED.value,
    )


# --------------------------------------------------------------------------
# The positive control for the whole ladder
# --------------------------------------------------------------------------
def test_with_every_gate_satisfied_arming_and_de_energizing_both_succeed():
    """The chain that clears all of it: three confirmed circuits, a dispatched advance
    notice, an imminent notice that reached every critical and medical account, and a ratio
    comfortably over the floor — two success envelopes and a shutoff on the books.

    "A `PSPSDutyOfficer` arms an event from `SCOPED` to `ARMED`, and three gates must
    clear first."

    "And the event's `net_benefit_ratio` must be at least 0.25, or the request is
    refused with `ERR_NET_BENEFIT_BELOW_THRESHOLD`; a ratio of exactly 0.2500 clears
    the gate."

    "Every `CONFIRMED`-scoped circuit moves from `DE_ENERGIZATION_PENDING` to
    `DE_ENERGIZED`, keeping its `risk_posture` at `LOCKED`."

    Design: Corner/validations/every_gate_satisfied_the_arm_and_de_energize_sequence_passes
    """
    ctx = build_advance_dispatched_event()

    armed = validate_success(
        api_client.arm_psps_event(ctx["event_id"], OFFICER_HEADERS), 200
    )
    assert_event_dimensions(
        armed,
        scope_status=EventScopeStatus.ARMED.value,
        notification_status=NotificationStatus.ADVANCE_SENT.value,
    )
    assert_scope_counts(armed, 3, 0)
    assert_impact_counts(armed, 5, 1, 1)
    assert_net_benefit(
        armed,
        customer_impact_score=45.60,
        ignition_risk_avoided_score=15.48,
        net_benefit_ratio=0.3395,
    )

    imminent = plan_batch(
        ctx["event_id"], NotificationStage.IMMINENT_1H.value, IMMINENT_SEND_AT
    )
    move_clock(IMMINENT_SEND_AT)
    dispatch_batch(imminent["id"])

    move_clock(DE_ENERGIZED_AT)
    active = validate_success(
        api_client.de_energize_psps_event(ctx["event_id"], OFFICER_HEADERS), 200
    )
    assert_event_dimensions(
        active,
        scope_status=EventScopeStatus.ACTIVE.value,
        notification_status=NotificationStatus.IMMINENT_SENT.value,
    )
    assert_instant(active["actual_de_energized_at"], DE_ENERGIZED_AT)

    for key in ("alpha", "bravo", "charlie"):
        assert_circuit_state(
            read_circuit(ctx[key]["id"]),
            energization_state=EnergizationState.DE_ENERGIZED.value,
            risk_posture=RiskPosture.LOCKED.value,
        )
    rows = read_scope_rows(ctx["event_id"])
    for key in ("alpha", "bravo", "charlie"):
        assert_scope_row(
            rows, ctx[key]["id"], scope_status=ScopeRowStatus.CONFIRMED.value
        )
