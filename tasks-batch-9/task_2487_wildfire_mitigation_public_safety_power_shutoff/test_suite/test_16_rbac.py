"""The authorisation matrix as a partition rather than a ladder: each of the eight roles
drives its own exclusive operations end to end, none of them inherits another's write or
another's read, and the three segregation-of-duties gates fence one identity out of a
second signature it already gave."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_FORBIDDEN_ROLE, ERR_SEGREGATION_OF_DUTIES
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_activation_summary,
    assert_center_state,
    assert_circuit_state,
    assert_event_dimensions,
    assert_fpi,
    assert_instant,
    assert_integer,
    assert_scope_counts,
    assert_scope_row,
)
from test_helpers.constants import UNKNOWN_UUID
from test_helpers.fixtures import (
    ALPHA_OBSERVATIONS,
    FORECAST_DATE,
    PATROL_DONE_AT,
    PATROL_START_AT,
    RESTORE_CHARLIE_AT,
    activate_centers,
    book_project,
    build_active_event,
    build_approved_project,
    build_armed_event,
    build_closed_event,
    build_imminent_dispatched_event,
    build_patrolled_event,
    build_restored_event,
    build_restoring_event,
    build_scoped_event,
    open_filing,
    read_center,
    read_circuit,
    read_scope_rows,
    register_center,
    register_circuit,
    review_filing,
    review_project,
    submit_filing,
    submit_project,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    ENGINEER_HEADERS,
    INSPECTOR_HEADERS,
    LIAISON_HEADERS,
    OFFICER_HEADERS,
    PLANNER_HEADERS,
    REVIEWER_2_HEADERS,
    REVIEWER_3_HEADERS,
    REVIEWER_4_HEADERS,
    REVIEWER_ALPHA,
    REVIEWER_GAMMA,
    REVIEWER_DELTA,
    REVIEWER_HEADERS,
    SUPERVISOR_HEADERS,
)
from test_helpers.types import (
    EnergizationState,
    FilingDecision,
    FilingStatus,
    HftdTier,
    NotificationTier,
    ProjectStatus,
    ResourceCenterStatus,
    ReviewDecision,
    ReviewTrack,
    ReviewTrackState,
    RiskPosture,
    ScopeRowStatus,
)

COMPLETION_DATE = "2026-07-01T00:00:00Z"
ALPHA_STATIONS = (("ws_a1", "WS-A1", 3200, 0.70), ("ws_a2", "WS-A2", 2600, 0.45))


# --------------------------------------------------------------------------
# The allow side of the matrix
# --------------------------------------------------------------------------
def test_the_planning_half_of_the_matrix_runs_under_its_own_four_owners():
    """Circuit, stations, observations, index, work package, review, executed mileage and
    filing — fifteen calls, four roles, no call reaching outside its own list, and each
    create answering 201 while each action answers 200.

    "**Role authorised** — `X-User-Role` appears in the called endpoint's
    authorised-role list in §4. Otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every
    endpoint."

    "Endpoints that create a new resource respond with **HTTP 201** on success; every
    other endpoint, including every action endpoint that drives a state transition and
    every read endpoint, responds with **HTTP 200**."

    "A `GridPlanner` opens a filing with a `filing_code` unique across all filings and 3
    to 40 characters long, and a `plan_year` from 2020 through 2100 inclusive that must
    **also** be unique across all filings — one filing per plan year, and a collision on
    either key is refused with `ERR_DUPLICATE_CODE`."

    "The qualifying projects are the mitigation projects whose `plan_year` equals the
    filing's `plan_year` and whose `status` is `APPROVED`, `IN_EXECUTION`, `SUSPENDED`,
    or `COMPLETED`; projects in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, or
    `WITHDRAWN` are excluded entirely."

    Design: Corner/rbac/planning_roles_perform_their_own_exclusive_operations
    """
    alpha = validate_success(
        api_client.create_circuit(
            factories.circuit_payload(circuit_code="ALPHA"), PLANNER_HEADERS
        ),
        201,
    )

    station_ids = {}
    for key, code, elevation_ft, weight in ALPHA_STATIONS:
        station = validate_success(
            api_client.create_weather_station(
                factories.weather_station_payload(
                    alpha["id"],
                    station_code=code,
                    elevation_ft=elevation_ft,
                    representativeness_weight=weight,
                ),
                ANALYST_HEADERS,
            ),
            201,
        )
        station_ids[key] = station["id"]

    for key, observed_at, gust, humidity, temperature, fuel_moisture in ALPHA_OBSERVATIONS:
        validate_success(
            api_client.create_weather_observation(
                factories.observation_payload(
                    station_ids[key],
                    observed_at,
                    wind_gust_mph=gust,
                    relative_humidity_pct=humidity,
                    temperature_f=temperature,
                    dead_fuel_moisture_pct=fuel_moisture,
                ),
                ANALYST_HEADERS,
            ),
            201,
        )

    index = validate_success(
        api_client.create_fire_potential_index(
            factories.fpi_payload(alpha["id"], FORECAST_DATE), ANALYST_HEADERS
        ),
        201,
    )
    assert_fpi(index, 85.93, "R5")

    project = validate_success(
        api_client.create_mitigation_project(
            factories.mitigation_project_payload(alpha["id"], project_code="MP-CC"),
            PLANNER_HEADERS,
        ),
        201,
    )
    submitted = validate_success(
        api_client.submit_mitigation_project(project["id"], PLANNER_HEADERS), 200
    )
    assert submitted["status"] == ProjectStatus.SUBMITTED.value

    approved = validate_success(
        api_client.review_mitigation_project(
            project["id"],
            factories.project_review_payload(
                ReviewDecision.APPROVE.value, "hardening plan accepted"
            ),
            REVIEWER_HEADERS,
        ),
        200,
    )
    assert approved["status"] == ProjectStatus.APPROVED.value

    # The inspector's only exclusive write is the mileage, and it reads the circuit first.
    seen = validate_success(api_client.get_circuit(alpha["id"], INSPECTOR_HEADERS), 200)
    completed = validate_success(
        api_client.record_project_completion(
            project["id"],
            factories.record_completion_payload(4.0, COMPLETION_DATE, seen["version"]),
            INSPECTOR_HEADERS,
        ),
        200,
    )
    assert completed["status"] == ProjectStatus.COMPLETED.value
    assert_1dp(completed["completed_miles"], 4.0)

    filing = validate_success(
        api_client.create_plan_filing(
            factories.plan_filing_payload(2026, "WMP-CYCLE"), PLANNER_HEADERS
        ),
        201,
    )
    filed = validate_success(
        api_client.submit_plan_filing(filing["id"], PLANNER_HEADERS), 200
    )
    assert filed["status"] == FilingStatus.SUBMITTED.value
    assert_integer(filed["qualifying_project_count"], 1)
    assert_1dp(filed["covered_conductor_miles_reported"], 4.0)


def test_the_event_lifecycle_is_split_across_four_operational_owners():
    """The duty officer arms, activates, de-energizes, restores and closes; the liaison plans
    and dispatches and registers the site; the meteorologist alone calls the all-clear; the
    supervisor owns the patrols — and the site stands down on the cascade, not by request.

    "The weather judgement is deliberately separated from the switching authority: only
    a `MeteorologyAnalyst` may declare the damaging-weather window over, advancing the
    event from `ACTIVE` to `RESTORING` and incrementing its `version`."

    "The safety gate lives on re-energization, which belongs to the
    `PSPSDutyOfficer`."

    "Demobilization is always a cascade, never a direct operator action. A site whose
    `status` is `ACTIVATED` moves to `DEMOBILIZED`, with `demobilized_at` stamped from the
    logical clock, when the event it served reaches a non-null `actual_restored_at`, or is
    closed, or is cancelled."

    "Closing moves the event to the terminal `CLOSED` status, freezes its `POST_EVENT`
    scores, demobilizes any resource center still `ACTIVATED` for the event, makes the
    event eligible for plan-filing metric roll-up, and increments the event's
    `version`."

    Design: Corner/rbac/operational_roles_perform_their_own_exclusive_operations
    """
    ctx = build_armed_event()
    center = register_center(
        headers=LIAISON_HEADERS,
        resource_center_code="CRC-N1",
        district_code="D-NORTH",
        site_capacity=2,
        accessibility_certified=True,
    )
    summary = activate_centers(ctx["event_id"], headers=OFFICER_HEADERS)
    assert_activation_summary(
        summary,
        activated_count=1,
        activated_capacity=2,
        unmet_capacity=0,
        activated_ids=[center["id"]],
    )
    assert_center_state(
        read_center(center["id"]),
        ResourceCenterStatus.ACTIVATED.value,
        activation_order=1,
        psps_event_id=ctx["event_id"],
    )

    ctx = build_imminent_dispatched_event(ctx)
    ctx = build_active_event(ctx)
    ctx = build_restoring_event(ctx)
    assert_event_dimensions(ctx["event"], scope_status="RESTORING")

    ctx = build_patrolled_event(ctx)
    ctx = build_restored_event(ctx)
    assert_center_state(
        read_center(center["id"]), ResourceCenterStatus.DEMOBILIZED.value
    )

    ctx = build_closed_event(ctx)
    assert_event_dimensions(ctx["event"], scope_status="CLOSED")
    assert_instant(ctx["event"]["actual_restored_at"], RESTORE_CHARLIE_AT)

    # ALPHA still carries its own R5 forecast, so its posture leaves `LOCKED` for
    # `EXTREME`; the two dependants never had an index of their own.
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state=EnergizationState.ENERGIZED.value,
        risk_posture=RiskPosture.EXTREME.value,
    )
    for key in ("bravo", "charlie"):
        assert_circuit_state(
            read_circuit(ctx[key]["id"]),
            energization_state=EnergizationState.ENERGIZED.value,
            risk_posture=RiskPosture.NORMAL.value,
        )


# --------------------------------------------------------------------------
# The deny side of the matrix
# --------------------------------------------------------------------------
def test_only_the_transmission_engineer_may_hold_a_circuit_out_of_the_shutoff():
    """The planner who owns the circuit and the officer who scoped the event are both
    refused, and the one role the contract names carries the exclusion — after which the
    held-out row's term is pinned rather than dropped.

    "A `TransmissionEngineer` reviews determined scope and is the only role that may
    hold a circuit out of a scoped or armed event."

    "A `TransmissionEngineer` — and only a `TransmissionEngineer` — may hold a confirmed
    circuit out of the event by supplying a written `exclusion_justification`, which
    overwrites whatever the determination had placed there."

    "Every `EXCLUDED` row carries `ignition_risk_term` pinned at 0.00 rather than being
    omitted from the set, which keeps the sum stable as circuits are held out."

    Design: Corner/rbac/only_the_transmission_engineer_may_exclude_a_scope_row
    """
    ctx = build_scoped_event()
    alpha_id = ctx["alpha"]["id"]
    rows = read_scope_rows(ctx["event_id"])
    alpha_row = next(row for row in rows if row["circuit_id"] == alpha_id)

    validate_error(
        api_client.exclude_event_scope(
            alpha_row["id"], factories.exclude_payload("planner override"), PLANNER_HEADERS
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.exclude_event_scope(
            alpha_row["id"],
            factories.exclude_payload("operator override"),
            OFFICER_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    assert_scope_row(
        read_scope_rows(ctx["event_id"]),
        alpha_id,
        scope_status=ScopeRowStatus.CONFIRMED.value,
        ignition_risk_term=6.02,
    )

    excluded = validate_success(
        api_client.exclude_event_scope(
            alpha_row["id"],
            factories.exclude_payload("conductor already covered on this span"),
            ENGINEER_HEADERS,
        ),
        200,
    )
    assert excluded["scope_status"] == ScopeRowStatus.EXCLUDED.value
    assert_2dp(excluded["ignition_risk_term"], 0.00)

    event = validate_success(
        api_client.get_psps_event(ctx["event_id"], OFFICER_HEADERS), 200
    )
    assert_scope_counts(event, confirmed=2, excluded=1)
    assert_2dp(event["ignition_risk_avoided_score"], 9.46)


def test_no_role_inherits_another_roles_exclusive_write():
    """Nine cross-role attempts, every role an offender at least once: each is refused at the
    authorisation step, so none of them reaches the identifier that does not exist and none
    of them leaves a row behind.

    "If the role is recognised but is not listed among the authorised roles for the
    endpoint being called (see the table in §4), the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    "**Role authorised** — `X-User-Role` appears in the called endpoint's
    authorised-role list in §4. Otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every
    endpoint."

    "**Path identifiers resolve** — every id embedded in the request path resolves to
    an existing row, validated left to right, so that the leftmost unresolvable segment
    determines the error."

    Design: Corner/rbac/no_role_may_perform_another_roles_exclusive_operation
    """
    survivor = register_circuit(headers=PLANNER_HEADERS, circuit_code="DENIAL-1")

    attempts = [
        api_client.arm_psps_event(UNKNOWN_UUID, PLANNER_HEADERS),
        api_client.create_circuit(
            factories.circuit_payload(
                circuit_code="DO-1",
                hftd_tier=HftdTier.TIER_1.value,
                overhead_miles=3.0,
                equipment_condition_index=90,
            ),
            OFFICER_HEADERS,
        ),
        api_client.review_mitigation_project(
            UNKNOWN_UUID,
            factories.project_review_payload(ReviewDecision.APPROVE.value),
            LIAISON_HEADERS,
        ),
        api_client.record_project_completion(
            UNKNOWN_UUID,
            factories.record_completion_payload(
                1.0, COMPLETION_DATE, survivor["version"]
            ),
            REVIEWER_HEADERS,
        ),
        api_client.create_patrol_assignment(
            factories.patrol_assignment_payload(
                UNKNOWN_UUID,
                UNKNOWN_UUID,
                PATROL_START_AT,
                PATROL_DONE_AT,
                patrol_lead_user_id="crew_lead_9",
            ),
            INSPECTOR_HEADERS,
        ),
        api_client.dispatch_notification_batch(UNKNOWN_UUID, SUPERVISOR_HEADERS),
        api_client.create_plan_filing(
            factories.plan_filing_payload(2026, "MET-FILING"), ANALYST_HEADERS
        ),
        api_client.create_customer(
            factories.customer_payload(UNKNOWN_UUID, account_number="TE-1"),
            ENGINEER_HEADERS,
        ),
        # The rule cuts both ways: the duty officer cannot issue the meteorologist's
        # all-clear either.
        api_client.all_clear_psps_event(UNKNOWN_UUID, OFFICER_HEADERS),
    ]

    for attempt in attempts:
        validate_error(attempt, ERR_FORBIDDEN_ROLE, 403)
        assert attempt.status_code == 403, (
            "the authorisation step decides before any path identifier is resolved"
        )

    circuits, circuit_meta = validate_paginated(api_client.list_circuits(PLANNER_HEADERS))
    assert_integer(circuit_meta["total_count"], 1)
    assert [row["circuit_code"] for row in circuits] == ["DENIAL-1"]


def test_read_authorisation_is_partitioned_endpoint_by_endpoint():
    """No role is a superset of another on the read surface either: the supervisor and the
    meteorologist are shut out of account data, the liaison is shut out of telemetry, and the
    inspector who can read neither is welcome on the scope listing.

    "If the role is recognised but is not listed among the authorised roles for the
    endpoint being called (see the table in §4), the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    "Registration computes one derived field, the account's `notification_tier`, from a
    strict precedence: an account whose `customer_class` is `CRITICAL_FACILITY` is
    `TIER_A_CRITICAL`; otherwise an account whose `medical_baseline` is true is
    `TIER_B_MEDICAL`; otherwise the account is `TIER_C_STANDARD`."

    "Scope rows for an event, or every scope row that has ever named a given circuit,
    can be listed filtered by `scope_status`; an unresolvable scope row identifier yields
    `ERR_EVENT_SCOPE_NOT_FOUND`."

    Design: Corner/rbac/read_authorisation_is_per_endpoint_not_a_global_rank
    """
    ctx = build_scoped_event()

    validate_error(
        api_client.get_customer(ctx["cust_a1"]["id"], SUPERVISOR_HEADERS),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.list_circuit_customers(ctx["alpha"]["id"], ANALYST_HEADERS),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.list_circuit_weather_stations(ctx["alpha"]["id"], LIAISON_HEADERS),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    _, scope_meta = validate_paginated(
        api_client.list_event_scopes(ctx["event_id"], INSPECTOR_HEADERS)
    )
    assert_integer(scope_meta["total_count"], 3)

    account = validate_success(
        api_client.get_customer(ctx["cust_a1"]["id"], ENGINEER_HEADERS), 200
    )
    assert account["notification_tier"] == NotificationTier.TIER_B_MEDICAL.value


# --------------------------------------------------------------------------
# Segregation of duties
# --------------------------------------------------------------------------
def test_the_reviewer_who_demanded_the_change_may_not_certify_it():
    """The gate is keyed on the operator identifier and survives the revision loop: the
    reviewer who sent the package back is refused the approval, the refusal leaves the
    recorded identifier and the round counter untouched, and a second reviewer signs.

    "Three gates enforce that no single operator can both create and bless the same
    risk. Each is evaluated as an exact string comparison between the acting `X-User-ID`
    and a previously recorded identifier, and each failure carries
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    "The **project-approval gate** compares the acting `X-User-ID` against the project's
    `last_revision_reviewer_user_id`. If they match, the approval is refused; the reviewer
    who demanded the change may not certify that the change is adequate."

    "Re-submission closes the loop and — importantly — does **not** reset `review_round`,
    so the two-round ceiling survives across the whole life of the project."

    Design: Corner/rbac/the_same_user_cannot_request_and_then_approve_a_mitigation_project
    """
    alpha = register_circuit(circuit_code="ALPHA")
    project = book_project(alpha["id"], project_code="MP-CC")
    submit_project(project["id"])
    sent_back = review_project(
        project["id"],
        ReviewDecision.REQUEST_REVISION.value,
        "widen the covered span",
        headers=REVIEWER_HEADERS,
    )
    assert sent_back["status"] == ProjectStatus.REVISION_REQUESTED.value
    assert sent_back["last_revision_reviewer_user_id"] == REVIEWER_ALPHA
    resubmitted = submit_project(project["id"])
    assert_integer(resubmitted["review_round"], 1)

    validate_error(
        api_client.review_mitigation_project(
            project["id"],
            factories.project_review_payload(
                ReviewDecision.APPROVE.value, "looks fine now"
            ),
            REVIEWER_HEADERS,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    refused = validate_success(
        api_client.get_mitigation_project(project["id"], PLANNER_HEADERS), 200
    )
    assert refused["status"] == ProjectStatus.SUBMITTED.value
    assert_integer(refused["review_round"], 1)
    assert refused["last_revision_reviewer_user_id"] == REVIEWER_ALPHA

    independent = validate_success(
        api_client.review_mitigation_project(
            project["id"],
            factories.project_review_payload(
                ReviewDecision.APPROVE.value, "independent approval"
            ),
            REVIEWER_2_HEADERS,
        ),
        200,
    )
    assert independent["status"] == ProjectStatus.APPROVED.value


def test_one_reviewer_may_not_clear_both_tracks_of_the_same_filing_round():
    """The filing's fork demands two signatures: the reviewer who cleared safety is refused
    the fiscal track, the refusal leaves that track `PENDING` and the filing `SUBMITTED`, and
    a different reviewer completes the join.

    "The **filing-review gate** compares the acting `X-User-ID` against the other
    track's recorded reviewer identifier. If the other track has already been decided in
    this round and its `safety_reviewer_user_id` or `fiscal_reviewer_user_id` equals the
    acting identifier, the second decision is refused."

    "A `CLEAR` decision on the **first** of the two tracks sets that track's state to
    `CLEARED` and its reviewer identifier to the acting `X-User-ID`, and leaves the filing
    at `SUBMITTED` waiting for its sibling — one leg of the join has landed."

    "That second clearance is where the filing-review segregation-of-duties gate bites —
    the other track's recorded reviewer identifier must differ from the acting
    `X-User-ID`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_two_filing_review_tracks_must_be_decided_by_different_users
    """
    alpha = register_circuit(circuit_code="ALPHA")
    build_approved_project(alpha["id"], project_code="MP-CC")
    filing = open_filing(filing_code="WMP-CYCLE", plan_year=2026)
    submit_filing(filing["id"])

    first_leg = review_filing(
        filing["id"],
        ReviewTrack.SAFETY.value,
        FilingDecision.CLEAR.value,
        headers=REVIEWER_3_HEADERS,
    )
    assert first_leg["safety_review_state"] == ReviewTrackState.CLEARED.value
    assert first_leg["status"] == FilingStatus.SUBMITTED.value

    validate_error(
        api_client.review_plan_filing(
            filing["id"],
            factories.filing_review_payload(
                ReviewTrack.FISCAL.value, FilingDecision.CLEAR.value
            ),
            REVIEWER_3_HEADERS,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    refused = validate_success(
        api_client.get_plan_filing(filing["id"], PLANNER_HEADERS), 200
    )
    assert refused["fiscal_review_state"] == ReviewTrackState.PENDING.value
    assert refused["status"] == FilingStatus.SUBMITTED.value
    assert refused["fiscal_reviewer_user_id"] is None

    joined = validate_success(
        api_client.review_plan_filing(
            filing["id"],
            factories.filing_review_payload(
                ReviewTrack.FISCAL.value, FilingDecision.CLEAR.value
            ),
            REVIEWER_4_HEADERS,
        ),
        200,
    )
    assert joined["fiscal_review_state"] == ReviewTrackState.CLEARED.value
    assert joined["status"] == FilingStatus.APPROVED.value
    assert joined["safety_reviewer_user_id"] == REVIEWER_GAMMA
    assert joined["fiscal_reviewer_user_id"] == REVIEWER_DELTA
    assert_integer(joined["deficiency_round_count"], 0)
