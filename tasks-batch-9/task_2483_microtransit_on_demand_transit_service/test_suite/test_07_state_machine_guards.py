"""State-machine guards across the microtransit estate.

Nine resource types in this API own a state machine, and each one declares both
where a row starts and which triggers it will answer from there. These tests pin
the declared initial states, the one transition that unlocks trip intake, the
non-idempotence of zone activation, the lockdown a terminal trip and a terminal
assignment impose while the parallel fare axis stays live, the terminal virtual
stop, the report states that refuse certification before a filing exists, and the
supersession a forecast publication performs with no client trigger of its own.

Every test builds its own state from scratch through the public endpoints, moves
the logical clock explicitly whenever a rule depends on "now", and reads the row
back after a refused trigger to prove the rejection wrote nothing.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    DISPATCHER_HEADERS,
    FINANCE_ANALYST_HEADERS,
    ZONE_ADMIN_HEADERS,
    make_driver_headers,
    make_rider_headers,
)

SERVICE_DAY_MORNING = TEST_DEFAULTS["BLOCK_START_UTC"]  # 2026-08-03T06:00:00Z


# ===========================================================================
# Instance: stop_approve_moves_proposed_to_approved_and_unlocks_trip_intake
# ===========================================================================


def test_approve_moves_a_proposed_stop_to_approved_and_bumps_its_version() -> None:
    """Approving a PROPOSED stop inside the walking standard lands it in APPROVED at version 2.

    PRD: "A successful approval sets `status` to `APPROVED` and advances the stop's `version` by 1."

    Design: Corner/state_machines/stop_approve_moves_proposed_to_approved_and_unlocks_trip_intake
    """
    fx.set_clock(SERVICE_DAY_MORNING)
    zone = fx.create_active_zone()
    stop = fx.create_stop(zone["id"], "S4", 4)
    A.assert_fields(stop, status="PROPOSED", walk_shed_meters=400)
    assert stop["version"] == 1

    approved = validate_success(
        api_client.approve_virtual_stop(stop["id"], ZONE_ADMIN_HEADERS), 200
    )

    A.assert_fields(approved, status="APPROVED")
    A.assert_version_advanced(stop, approved)
    assert approved["version"] == 2


def test_trip_intake_unlocks_only_after_the_destination_stop_is_approved() -> None:
    """The identical intake body is refused while the destination is PROPOSED and accepted once it is APPROVED.

    PRD: "Both named stops must have `status` equal to `APPROVED`; a proposed or retired stop is rejected with `ERR_STOP_NOT_APPROVED`."

    Design: Corner/state_machines/stop_approve_moves_proposed_to_approved_and_unlocks_trip_intake
    """
    fx.set_clock(SERVICE_DAY_MORNING)
    zone = fx.create_active_zone()
    origin = fx.create_approved_stop(zone["id"], "S0", 0)
    destination = fx.create_stop(zone["id"], "S4", 4)
    rider = fx.create_rider(zone["id"], "R1")
    rider_headers = make_rider_headers(rider["id"])
    intake_payload = F.trip_request_payload(
        zone["id"], rider["id"], origin["id"], destination["id"]
    )

    validate_error(
        api_client.create_trip_request(intake_payload, rider_headers),
        ApiErrorId.ERR_STOP_NOT_APPROVED.value,
    )

    # The refused intake persisted nothing.
    rows, meta = validate_paginated(
        api_client.list_trip_requests(DISPATCHER_HEADERS, params={"zone_id": zone["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    approved = fx.approve_stop(destination["id"])
    A.assert_fields(approved, status="APPROVED")

    trip = validate_success(
        api_client.create_trip_request(intake_payload, rider_headers), 201
    )
    A.assert_trip_state(trip, "RECEIVED", "UNPRICED")


# ===========================================================================
# Instance: every_state_machine_starts_in_its_declared_initial_state
# ===========================================================================


def test_new_service_zone_starts_in_draft_with_a_zeroed_scorecard() -> None:
    """A freshly defined zone is DRAFT at version 1 with every performance field zeroed.

    PRD: "A newly defined zone lands in `DRAFT` with `version` 1 and every performance field zeroed: `completed_trip_count` and `unserved_trip_count` at 0, `avg_wait_minutes`, `avg_ride_minutes`, `boardings_per_revenue_hour`, `wav_avg_wait_minutes` and `nonwav_avg_wait_minutes` at 0.00, `wav_equivalence_ratio` at 0.000, and `equivalence_verdict` at `COMPLIANT`."

    Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
    """
    fx.set_clock(SERVICE_DAY_MORNING)

    zone = validate_success(
        api_client.create_service_zone(F.service_zone_payload(), ZONE_ADMIN_HEADERS),
        201,
    )

    A.assert_versioned_entity(zone)
    A.assert_fields(
        zone,
        status="DRAFT",
        completed_trip_count=0,
        unserved_trip_count=0,
        equivalence_verdict="COMPLIANT",
    )
    assert zone["version"] == 1
    assert zone["avg_wait_minutes"] == pytest.approx(0.00, abs=0.01)
    assert zone["avg_ride_minutes"] == pytest.approx(0.00, abs=0.01)
    assert zone["boardings_per_revenue_hour"] == pytest.approx(0.00, abs=0.01)
    assert zone["wav_avg_wait_minutes"] == pytest.approx(0.00, abs=0.01)
    assert zone["nonwav_avg_wait_minutes"] == pytest.approx(0.00, abs=0.01)
    assert zone["wav_equivalence_ratio"] == pytest.approx(0.000, abs=0.01)


def test_new_virtual_stop_starts_in_proposed() -> None:
    """A stop placed on the corridor is PROPOSED at version 1, not approved on arrival.

    PRD: "New stops begin in `PROPOSED` with `version` 1."

    Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
    """
    fx.set_clock(SERVICE_DAY_MORNING)
    zone = fx.create_active_zone()

    stop = validate_success(
        api_client.create_virtual_stop(
            F.virtual_stop_payload(zone["id"], "S0", 0), ZONE_ADMIN_HEADERS
        ),
        201,
    )

    A.assert_versioned_entity(stop)
    A.assert_fields(stop, status="PROPOSED", paired_stop_id=None)
    assert stop["version"] == 1


def test_new_vehicle_starts_available() -> None:
    """A vehicle onboarded into the fleet is AVAILABLE at version 1.

    PRD: "Vehicles are created `AVAILABLE` with `version` 1."

    Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
    """
    fx.set_clock(SERVICE_DAY_MORNING)
    zone = fx.create_active_zone()

    vehicle = validate_success(
        api_client.create_vehicle(
            F.vehicle_payload(zone["id"], "V1", seat_capacity=6, wav_positions=2),
            ZONE_ADMIN_HEADERS,
        ),
        201,
    )

    A.assert_versioned_entity(vehicle)
    A.assert_fields(vehicle, status="AVAILABLE")
    assert vehicle["version"] == 1


def test_new_driver_starts_active_with_no_decline_streak() -> None:
    """A rostered driver is ACTIVE at version 1 with a decline streak of 0.

    PRD: "A driver is created `ACTIVE`, with `consecutive_decline_count` at 0 and `version` 1."

    Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
    """
    fx.set_clock(SERVICE_DAY_MORNING)
    zone = fx.create_active_zone()

    driver = validate_success(
        api_client.create_driver(
            F.driver_payload(zone["id"], "D1", wav_certified=True), ZONE_ADMIN_HEADERS
        ),
        201,
    )

    A.assert_versioned_entity(driver)
    A.assert_fields(driver, status="ACTIVE", consecutive_decline_count=0)
    assert driver["version"] == 1


def test_new_demand_forecast_starts_published() -> None:
    """A published forecast lands directly in PUBLISHED at version 1.

    PRD: "A newly published forecast lands in `PUBLISHED` with `version` 1, and every existing forecast for the *same* zone that is currently `PUBLISHED` and whose window overlaps the incoming window moves to `SUPERSEDED`, with that forecast's own `version` advancing by 1."

    Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
    """
    fx.set_clock(SERVICE_DAY_MORNING)
    zone = fx.create_active_zone()
    zone_version = fx.refresh_zone(zone["id"])["version"]

    forecast = validate_success(
        api_client.create_demand_forecast(
            F.demand_forecast_payload(
                zone["id"], zone_version, forecast_trips=40, peak_factor=1.20
            ),
            ZONE_ADMIN_HEADERS,
        ),
        201,
    )

    A.assert_versioned_entity(forecast)
    A.assert_fields(forecast, state="PUBLISHED")
    assert forecast["version"] == 1


def test_new_vehicle_block_starts_scheduled_with_nothing_committed() -> None:
    """A scheduled block is SCHEDULED at version 1 with no commitments and no stamps.

    PRD: "A scheduled block is created in `SCHEDULED` with `version` 1, with `seats_committed`, `wav_positions_committed` and `boardings_count` all at 0, with `committed_index_min` and `committed_index_max` both null, with `opened_at` and `closed_at` both null, with `actual_revenue_hours` at 0.00, and with `scheduled_revenue_hours` derived from the window: the difference between `end_utc` and `start_utc` expressed in hours, to 2 decimal places, rounded half up."

    Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
    """
    fx.set_clock(SERVICE_DAY_MORNING)
    zone = fx.create_active_zone()
    vehicle = fx.create_vehicle(zone["id"], "V1")
    driver = fx.create_driver(zone["id"], "D1")

    block = validate_success(
        api_client.create_vehicle_block(
            F.vehicle_block_payload(zone["id"], vehicle["id"], driver["id"]),
            DISPATCHER_HEADERS,
        ),
        201,
    )

    A.assert_versioned_entity(block)
    A.assert_block_state(block, "SCHEDULED")
    assert block["version"] == 1
    A.assert_block_commitments(
        block,
        seats_committed=0,
        wav_positions_committed=0,
        committed_index_min=None,
        committed_index_max=None,
    )
    A.assert_fields(block, boardings_count=0)
    A.assert_null_fields(block, "opened_at", "closed_at")
    assert block["actual_revenue_hours"] == pytest.approx(0.00, abs=0.01)
    # 06:00Z to 10:00Z is four hours of scheduled service.
    assert block["scheduled_revenue_hours"] == pytest.approx(4.00, abs=0.01)


def test_new_trip_request_starts_received_and_unpriced() -> None:
    """Intake lands a trip in RECEIVED on the fulfilment axis and UNPRICED on the fare axis.

    PRD: "A newly intaken trip sits in `status` `RECEIVED` on the fulfilment axis and `fare_status` `UNPRICED` on the fare axis, with `version` 1."

    Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
    """
    fx.set_clock(SERVICE_DAY_MORNING)
    zone = fx.create_active_zone()
    origin = fx.create_approved_stop(zone["id"], "S0", 0)
    destination = fx.create_approved_stop(zone["id"], "S4", 4)
    rider = fx.create_rider(zone["id"], "R1")

    trip = validate_success(
        api_client.create_trip_request(
            F.trip_request_payload(
                zone["id"], rider["id"], origin["id"], destination["id"]
            ),
            make_rider_headers(rider["id"]),
        ),
        201,
    )

    A.assert_versioned_entity(trip)
    A.assert_trip_state(trip, "RECEIVED", "UNPRICED")
    assert trip["version"] == 1
    assert trip["match_attempt_count"] == 0


def test_new_pool_assignment_starts_offered() -> None:
    """A manually dispatched offer arrives on the manifest in OFFERED at version 1.

    PRD: "An offer sits on a driver's manifest as a pool assignment in state `OFFERED`, and from there it forks three ways — `ACCEPTED`, `DECLINED` or `RELEASED`."

    Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
    """
    state = fx.setup_received_trip()

    assignment = validate_success(
        api_client.create_pool_assignment(
            F.pool_assignment_payload(
                state["trip"]["id"],
                state["block"]["id"],
                fx.block_version(state["block"]["id"]),
            ),
            DISPATCHER_HEADERS,
        ),
        201,
    )

    A.assert_versioned_entity(assignment)
    A.assert_assignment_state(assignment, "OFFERED")
    assert assignment["version"] == 1


def test_new_subsidy_report_starts_draft_with_no_attribution() -> None:
    """A freshly opened report is DRAFT at version 1 with no filer, no certifier and no reason.

    PRD: "A new report lands in `DRAFT` with `version` 1, `amendment_count` at 0, and `submitted_by_user_id`, `certified_by_user_id` and `rejection_reason` all null."

    Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
    """
    fx.set_clock(SERVICE_DAY_MORNING)
    zone = fx.create_active_zone()

    report = validate_success(
        api_client.create_subsidy_report(
            F.subsidy_report_payload(zone["id"]), FINANCE_ANALYST_HEADERS
        ),
        201,
    )

    A.assert_versioned_entity(report)
    A.assert_report_state(report, "DRAFT")
    assert report["version"] == 1
    A.assert_fields(report, amendment_count=0)
    A.assert_null_fields(
        report, "submitted_by_user_id", "certified_by_user_id", "rejection_reason"
    )


# ===========================================================================
# Instance: repeating_the_activate_trigger_on_an_active_zone_is_rejected
# ===========================================================================


def test_repeating_activate_on_an_active_zone_is_refused_and_writes_nothing() -> None:
    """A second activate on an ACTIVE zone answers 409 and leaves the zone's version where it was.

    PRD: "Requesting activation from a zone already `ACTIVE` is rejected with `ERR_INVALID_ZONE_STATE`, as is requesting suspension from a zone that is not `ACTIVE`."

    Design: Corner/state_machines/repeating_the_activate_trigger_on_an_active_zone_is_rejected
    """
    fx.set_clock(SERVICE_DAY_MORNING)
    zone = fx.create_zone()
    activated = fx.activate_zone(zone["id"])
    A.assert_fields(activated, status="ACTIVE")
    assert activated["version"] == 2

    validate_error(
        api_client.activate_service_zone(zone["id"], ZONE_ADMIN_HEADERS),
        ApiErrorId.ERR_INVALID_ZONE_STATE.value,
    )

    after = fx.refresh_zone(zone["id"])
    A.assert_fields(after, status="ACTIVE")
    A.assert_version_unchanged(activated, after)


# ===========================================================================
# Instance: completed_trip_and_completed_assignment_reject_all_further_triggers
# ===========================================================================


def _completed_ride() -> dict:
    """A ride manually dispatched, accepted, boarded at 07:00Z and completed at
    07:12Z, so the trip is COMPLETED / CHARGED and the assignment COMPLETED."""
    return fx.setup_completed_trip(
        board_at="2026-08-03T07:00:00Z",
        complete_at="2026-08-03T07:12:00Z",
        manual=True,
    )


def test_completed_trip_and_assignment_refuse_cancel_match_and_complete() -> None:
    """Cancel and match on the COMPLETED trip and a repeated complete on the COMPLETED assignment are all refused.

    PRD: "On every state-transition operation — that is, every action endpoint of the form collection, identifier, action — the target resource must currently be in a state from which the requested transition is declared, and on pool-assignment create the trip must be in `RECEIVED` or `MATCHING` and the block must be `OPEN`."

    Design: Corner/state_machines/completed_trip_and_completed_assignment_reject_all_further_triggers
    """
    state = _completed_ride()
    trip = state["trip"]
    assignment = state["assignment"]
    driver_headers = make_driver_headers(state["driver"]["id"])
    A.assert_trip_state(trip, "COMPLETED", "CHARGED")
    A.assert_assignment_state(assignment, "COMPLETED")

    validate_error(
        api_client.cancel_trip_request(
            trip["id"], DISPATCHER_HEADERS, {"note": "rider changed mind after the ride"}
        ),
        ApiErrorId.ERR_INVALID_TRIP_STATE.value,
    )
    validate_error(
        api_client.match_trip_request(trip["id"], DISPATCHER_HEADERS),
        ApiErrorId.ERR_INVALID_TRIP_STATE.value,
    )
    validate_error(
        api_client.complete_pool_assignment(assignment["id"], driver_headers),
        ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value,
    )

    after_trip = fx.refresh_trip(trip["id"])
    after_assignment = fx.refresh_assignment(assignment["id"])
    A.assert_trip_state(after_trip, "COMPLETED", "CHARGED")
    A.assert_assignment_state(after_assignment, "COMPLETED")
    A.assert_version_unchanged(trip, after_trip)
    A.assert_version_unchanged(assignment, after_assignment)


def test_refund_stays_legal_on_the_charged_axis_of_a_completed_trip() -> None:
    """Terminal on the fulfilment axis does not freeze the fare axis: a CHARGED trip still refunds.

    PRD: "It moves the fare axis `CHARGED → REFUNDED`, and a trip whose `fare_status` is anything other than `CHARGED` is rejected with `ERR_TRIP_NOT_CHARGED`."

    Design: Corner/state_machines/completed_trip_and_completed_assignment_reject_all_further_triggers
    """
    state = _completed_ride()
    trip = state["trip"]
    A.assert_trip_state(trip, "COMPLETED", "CHARGED")

    refunded = validate_success(
        api_client.refund_trip_request(
            trip["id"],
            {"reason": "service failure reported after completion"},
            DISPATCHER_HEADERS,
        ),
        200,
    )

    A.assert_trip_state(refunded, "COMPLETED", "REFUNDED")
    A.assert_version_advanced(trip, refunded)
    A.assert_assignment_state(
        fx.refresh_assignment(state["assignment"]["id"]), "COMPLETED"
    )


def test_refund_after_completion_appends_the_compensating_ledger_row() -> None:
    """The reversal leaves the settled CHARGE in place and adds a REFUND row that nets the trip to zero.

    PRD: "The reversal appends one ledger row of `kind` `REFUND` whose `amount_cents` is the negative of the net cents previously settled for this trip, sets `charged_fare_cents` to 0, recomputes the rider's `daily_fare_paid_cents` and `weekly_fare_paid_cents` so their cap counters return to their pre-charge values, and advances the trip's `version` by 1."

    Design: Corner/state_machines/completed_trip_and_completed_assignment_reject_all_further_triggers
    """
    state = _completed_ride()
    trip = state["trip"]
    # Base fare 250 plus the MEDIUM band surcharge of 75 for a twelve-minute
    # measured ride, at the FULL multiplier of 1.00 and under no cap.
    assert trip["charged_fare_cents"] == 325
    A.assert_fields(trip, applied_cap="NONE")
    A.assert_ledger_kinds(state["ledger"], ["CHARGE"])

    refunded = validate_success(
        api_client.refund_trip_request(
            trip["id"],
            {"reason": "service failure reported after completion"},
            DISPATCHER_HEADERS,
        ),
        200,
    )
    assert refunded["charged_fare_cents"] == 0

    rows, meta = validate_paginated(
        api_client.list_fare_transactions(
            DISPATCHER_HEADERS, params={"trip_request_id": trip["id"]}
        )
    )
    assert meta["total_count"] == 2
    A.assert_ledger_kinds(rows, ["CHARGE", "REFUND"])
    charge_row = A.ledger_rows_of_kind(rows, "CHARGE")[0]
    refund_row = A.ledger_rows_of_kind(rows, "REFUND")[0]
    assert charge_row["amount_cents"] == 325
    assert refund_row["amount_cents"] == -325
    A.assert_ledger_nets_to(rows, 0)
    A.assert_ledger_row_shape(refund_row)
    A.assert_fields(refund_row, rider_id=state["rider"]["id"], service_date="2026-08-03")

    rider = fx.refresh_rider(state["rider"]["id"])
    A.assert_fields(rider, daily_fare_paid_cents=0, weekly_fare_paid_cents=0)


# ===========================================================================
# Instance: retired_stop_rejects_approve_and_retire_triggers
# ===========================================================================


def _retired_stop() -> tuple:
    """Zone RBM ACTIVE with stop S9 retired straight out of PROPOSED."""
    fx.set_clock(SERVICE_DAY_MORNING)
    zone = fx.create_active_zone()
    stop = fx.create_stop(zone["id"], "S9", 9)
    retired = fx.retire_stop(stop["id"])
    A.assert_fields(retired, status="RETIRED")
    return zone, retired


def test_retired_stop_refuses_the_approve_trigger() -> None:
    """Approve is declared only from PROPOSED, so a RETIRED stop refuses it and stays readable.

    PRD: "A `ZoneAdmin` moves a stop `PROPOSED → APPROVED` only while the stop is still `PROPOSED`, only while its zone is in `DRAFT` or `ACTIVE`, and only when the stop's `walk_shed_meters` is less than or equal to the zone's `max_walk_meters` — the comparison is inclusive, so a stop advertising exactly the standard is approvable."

    Design: Corner/state_machines/retired_stop_rejects_approve_and_retire_triggers
    """
    _zone, retired = _retired_stop()

    validate_error(
        api_client.approve_virtual_stop(retired["id"], ZONE_ADMIN_HEADERS),
        ApiErrorId.ERR_INVALID_STOP_STATE.value,
    )

    after = validate_success(
        api_client.get_virtual_stop(retired["id"], ZONE_ADMIN_HEADERS), 200
    )
    A.assert_fields(after, status="RETIRED")
    A.assert_version_unchanged(retired, after)


def test_retired_stop_refuses_a_repeated_retire_and_remains_listed() -> None:
    """Retire is declared only from the two live states, so a second retire is refused and the row survives.

    PRD: "Retirement takes a stop out of service permanently and is available from either of the two live states, `PROPOSED → RETIRED` and `APPROVED → RETIRED`."

    Design: Corner/state_machines/retired_stop_rejects_approve_and_retire_triggers
    """
    zone, retired = _retired_stop()

    validate_error(
        api_client.retire_virtual_stop(retired["id"], ZONE_ADMIN_HEADERS),
        ApiErrorId.ERR_INVALID_STOP_STATE.value,
    )

    after = fx.refresh_stop(retired["id"])
    A.assert_fields(after, status="RETIRED")
    A.assert_version_unchanged(retired, after)

    # Retirement is not deletion: the row is still discoverable in the listing.
    rows, meta = validate_paginated(
        api_client.list_virtual_stops(ZONE_ADMIN_HEADERS, params={"zone_id": zone["id"]})
    )
    assert meta["total_count"] == 1
    A.assert_contains_ids(rows, retired["id"])


# ===========================================================================
# Instance: draft_report_rejects_certify_and_reject_before_submission
# ===========================================================================


def test_draft_report_refuses_certify_reject_and_amend_before_submission() -> None:
    """Certify, reject and amend are undeclared from DRAFT, and all three leave the report untouched.

    PRD: "Any transition requested from a state that does not declare it — certifying a `DRAFT`, amending a `SUBMITTED`, submitting a `CERTIFIED` — is rejected with `ERR_INVALID_REPORT_STATE`."

    Design: Corner/state_machines/draft_report_rejects_certify_and_reject_before_submission
    """
    fx.set_clock("2026-08-04T06:00:00Z")
    zone = fx.create_active_zone()
    report = fx.create_report(zone["id"])
    A.assert_report_state(report, "DRAFT")

    validate_error(
        api_client.certify_subsidy_report(
            report["id"], AUDITOR_HEADERS, {"note": "looks fine to me"}
        ),
        ApiErrorId.ERR_INVALID_REPORT_STATE.value,
    )
    validate_error(
        api_client.reject_subsidy_report(
            report["id"],
            {"rejection_reason": "premature rejection attempt"},
            AUDITOR_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_REPORT_STATE.value,
    )
    validate_error(
        api_client.amend_subsidy_report(report["id"], FINANCE_ANALYST_HEADERS),
        ApiErrorId.ERR_INVALID_REPORT_STATE.value,
    )

    after = fx.refresh_report(report["id"])
    A.assert_report_state(after, "DRAFT")
    A.assert_fields(after, amendment_count=0)
    A.assert_null_fields(
        after, "certified_by_user_id", "submitted_by_user_id", "rejection_reason"
    )
    A.assert_version_unchanged(report, after)


# ===========================================================================
# Instance: overlapping_forecast_supersedes_the_incumbent_by_system_trigger
# ===========================================================================


def test_overlapping_forecast_publication_supersedes_the_incumbent() -> None:
    """Publishing an overlapping window demotes the incumbent to SUPERSEDED with its own counts intact.

    PRD: "A newly published forecast lands in `PUBLISHED` with `version` 1, and every existing forecast for the *same* zone that is currently `PUBLISHED` and whose window overlaps the incoming window moves to `SUPERSEDED`, with that forecast's own `version` advancing by 1."

    Design: Corner/state_machines/overlapping_forecast_supersedes_the_incumbent_by_system_trigger
    """
    fx.set_clock("2026-08-03T05:00:00Z")
    zone = fx.create_active_zone()
    incumbent = fx.create_forecast(
        zone["id"],
        window_start_utc="2026-08-03T06:00:00Z",
        window_end_utc="2026-08-03T10:00:00Z",
        forecast_trips=40,
        peak_factor=1.20,
    )
    # Four hours at four boarded trips per block-hour is sixteen trips a block,
    # so forty forecast trips need three base blocks; a peak factor of 1.20 sits
    # at or below the 1.50 threshold, so no surge blocks are required.
    A.assert_fields(
        incumbent, state="PUBLISHED", required_base_blocks=3, required_surge_blocks=0
    )

    # [06:00,10:00) and [09:00,13:00) intersect, so publication supersedes.
    successor = fx.create_forecast(
        zone["id"],
        window_start_utc="2026-08-03T09:00:00Z",
        window_end_utc="2026-08-03T13:00:00Z",
        forecast_trips=40,
        peak_factor=1.20,
    )
    A.assert_fields(successor, state="PUBLISHED")
    assert successor["version"] == 1

    demoted = fx.refresh_forecast(incumbent["id"])
    A.assert_fields(
        demoted, state="SUPERSEDED", required_base_blocks=3, required_surge_blocks=0
    )
    A.assert_version_advanced(incumbent, demoted)


def test_touching_forecast_windows_leave_both_forecasts_published() -> None:
    """A window that begins exactly where another ends does not overlap it, so the earlier forecast survives.

    PRD: "Two windows that merely touch — where one ends at exactly the instant the other begins — do not overlap and the earlier forecast survives."

    Design: Corner/state_machines/overlapping_forecast_supersedes_the_incumbent_by_system_trigger
    """
    fx.set_clock("2026-08-03T05:00:00Z")
    zone = fx.create_active_zone()
    first = fx.create_forecast(
        zone["id"],
        window_start_utc="2026-08-03T06:00:00Z",
        window_end_utc="2026-08-03T10:00:00Z",
        forecast_trips=40,
        peak_factor=1.20,
    )
    second = fx.create_forecast(
        zone["id"],
        window_start_utc="2026-08-03T09:00:00Z",
        window_end_utc="2026-08-03T13:00:00Z",
        forecast_trips=40,
        peak_factor=1.20,
    )
    third = fx.create_forecast(
        zone["id"],
        window_start_utc="2026-08-03T13:00:00Z",
        window_end_utc="2026-08-03T17:00:00Z",
        forecast_trips=40,
        peak_factor=1.20,
    )

    # The second window ends at 13:00Z, exactly where the third begins.
    A.assert_fields(third, state="PUBLISHED")
    second_after = fx.refresh_forecast(second["id"])
    A.assert_fields(second_after, state="PUBLISHED")
    A.assert_version_unchanged(second, second_after)
    # The first window, however, did intersect the second one.
    A.assert_fields(fx.refresh_forecast(first["id"]), state="SUPERSEDED")

    rows, meta = validate_paginated(
        api_client.list_demand_forecasts(
            ZONE_ADMIN_HEADERS, params={"zone_id": zone["id"], "state": "PUBLISHED"}
        )
    )
    assert meta["total_count"] == 2
    A.assert_contains_ids(rows, second["id"], third["id"])
    A.assert_excludes_ids(rows, first["id"])
