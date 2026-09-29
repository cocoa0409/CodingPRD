"""State machine breadth: initial states, legal steps, refused steps.

Every entity that carries a status is born in its declared initial state; the
season walks one step at a time and refuses skips, repeats and reversals; a
cancelled leg is terminal; validation stamps its actor; a carrier suspension
reaches down into the plans below it; and the use-it-or-lose-it audit rules once
and only once.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_flight_leg,
    assert_schedule_version,
    assert_season,
    assert_slot_holding,
    assert_iso_timestamp,
    assign_aircraft,
    booking_snapshot_payload,
    cancel_leg,
    close_season,
    create_draft_season,
    create_flight_leg,
    create_schedule_version,
    create_schedule_version_payload,
    create_slot_holding,
    create_slot_holding_payload,
    read_aircraft,
    read_carrier,
    read_holding,
    read_leg,
    read_season,
    read_version,
    run_slot_audit,
    setup_domestic_rotation_base,
    setup_monday_series_schedule,
    setup_reference_data,
    setup_series_with_utilization,
    validate_error,
    validate_paginated,
    validate_success,
    validate_version,
    TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
COORDINATOR = TEST_USERS["slot_coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── Initial states ───────────────────────────────────────────────────────

class TestNewRowsStartInTheirDeclaredInitialState:
    """A season, a slot series, a schedule version and a leg, each fresh."""

    def test_a_new_season_is_draft_with_no_audit_yet(self):
        """The audit pair is null and the derived counter starts empty.

        PRD §3.2: "A season is created in `status` `DRAFT`, with
        `slot_audit_completed_at_utc` and `audit_reference` both null and
        `held_series_count` at 0"

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
        """
        season = create_draft_season()
        assert_season(season)
        assert season["status"] == "DRAFT"
        assert season["slot_audit_completed_at_utc"] is None
        assert season["audit_reference"] is None
        assert season["held_series_count"] == 0
        assert season["version"] == 1

    def test_a_new_slot_series_is_held_with_every_exit_field_null(self):
        """`HELD` with nothing attached, nothing credited and no exit recorded.

        PRD §3.5: "A new series is created in `holding_status` `HELD` with
        `planned_operations` equal to `series_weeks` multiplied by the number of
        digits in `days_of_week`, `attached_operations` at 0,
        `credited_operations` at 0, both `utilization_pct` and
        `utilization_pct_as_filed` at 0.00, `at_risk_of_loss` false,
        `pending_transaction_id` null, and `returned_reason`,
        `returned_before_deadline` and `retains_historic_precedence` all null."

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
        """
        ref = setup_reference_data(("FRA",))
        holding = create_slot_holding(
            ref["stations"]["FRA"]["id"],
            ref["season"]["id"],
            ref["carrier"]["id"],
            movement_type="DEPARTURE",
            slot_time_utc="2026-11-02T08:00:00.000Z",
            days_of_week="1",
            series_weeks=5,
        )
        assert_slot_holding(holding)
        assert holding["holding_status"] == "HELD"
        assert holding["planned_operations"] == 5
        assert holding["attached_operations"] == 0
        assert holding["credited_operations"] == 0
        assert holding["utilization_pct"] == pytest.approx(0.00, abs=0.01)
        assert holding["utilization_pct_as_filed"] == pytest.approx(0.00, abs=0.01)
        assert holding["at_risk_of_loss"] is False
        assert holding["pending_transaction_id"] is None
        assert holding["returned_reason"] is None
        assert holding["returned_before_deadline"] is None
        assert holding["retains_historic_precedence"] is None
        assert holding["version"] == 1

    def test_a_new_version_is_draft_and_clean_and_its_first_leg_is_draft(self):
        """Two independent status dimensions on the version, and a blank leg.

        PRD §3.4: "The leg is created in `status` `DRAFT` with
        `assigned_aircraft_id`, `departure_slot_holding_id` and
        `arrival_slot_holding_id` all null, all three booked-cabin counters at 0,
        `cancellation_reason` null, `open_obligation_count` at 0, and
        `block_minutes`, `is_international`, `connect_minutes` and
        `mct_shortfall_minutes` all computed."

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
        """
        ref = setup_reference_data(("MUC", "TXL"))
        version = create_schedule_version(
            ref["carrier"]["id"], ref["season"]["id"], version_label="W26-I1"
        )
        assert_schedule_version(version)
        assert version["filing_status"] == "DRAFT"
        assert version["compliance_state"] == "CLEAN"
        assert version["schedule_compliance_score"] == pytest.approx(100.00, abs=0.01)

        leg = create_flight_leg(
            ref["carrier"]["id"],
            version["id"],
            ref["stations"]["MUC"]["id"],
            ref["stations"]["TXL"]["id"],
            "2026-11-03T08:00:00.000Z",
            "2026-11-03T09:00:00.000Z",
            flight_number="HX330",
        )
        assert_flight_leg(leg)
        assert leg["status"] == "DRAFT"
        assert leg["assigned_aircraft_id"] is None
        assert leg["departure_slot_holding_id"] is None
        assert leg["arrival_slot_holding_id"] is None
        assert leg["booked_first"] == 0
        assert leg["booked_business"] == 0
        assert leg["booked_economy"] == 0
        assert leg["cancellation_reason"] is None
        assert leg["open_obligation_count"] == 0
        assert leg["block_minutes"] == 60
        assert leg["is_international"] is False
        assert leg["connect_minutes"] is None
        assert leg["mct_shortfall_minutes"] == 0


# ─── The season machine: one step at a time ───────────────────────────────

def _open(season_id: str, to_status: str = "OPEN"):
    return api_client.transition_season(season_id, {"to_status": to_status}, ADMIN)


class TestSeasonOpensAndBumpsItsVersion:
    """`DRAFT` to `OPEN` is the first legal step and it is a write."""

    def test_the_first_transition_moves_the_status_and_the_version(self):
        """200 rather than 201, because no new resource was created.

        PRD §3.2: "Each accepted transition increments the season's `version` by
        1."

        Design: Corner/state_machines/season_draft_to_open_transition_moves_the_status_and_bumps_the_version
        """
        season = create_draft_season()
        assert season["version"] == 1

        opened = validate_success(_open(season["id"]), expected_status=200)
        assert_season(opened)
        assert opened["status"] == "OPEN"
        assert opened["version"] == 2
        assert opened["slot_audit_completed_at_utc"] is None
        assert opened["audit_reference"] is None
        assert opened["held_series_count"] == 0

        assert read_season(season["id"], ADMIN)["status"] == "OPEN"

    def test_only_the_open_season_admits_a_new_slot_series(self):
        """The same allocation is refused before the step and accepted after it.

        PRD §3.2: "`OPEN` is the working state: allocating a slot series, opening
        a schedule version, adding a leg, returning a series, proposing a slot
        transaction and approving one all require the governing season to be
        `OPEN`, and are otherwise refused with `ERR_SEASON_NOT_OPEN`."

        Design: Corner/state_machines/season_draft_to_open_transition_moves_the_status_and_bumps_the_version
        """
        ref = setup_reference_data(("FRA",), open_season=False)
        payload = create_slot_holding_payload(
            ref["stations"]["FRA"]["id"],
            ref["season"]["id"],
            ref["carrier"]["id"],
            movement_type="DEPARTURE",
            slot_time_utc="2026-11-02T08:00:00.000Z",
            days_of_week="1",
            series_weeks=5,
        )

        validate_error(
            api_client.create_slot_holding(payload, COORDINATOR),
            ApiErrorId.ERR_SEASON_NOT_OPEN,
            expected_status=409,
        )

        validate_success(_open(ref["season"]["id"]))
        allocated = validate_success(
            api_client.create_slot_holding(payload, COORDINATOR), expected_status=201
        )
        assert allocated["holding_status"] == "HELD"

        season = read_season(ref["season"]["id"], ADMIN)
        assert season["status"] == "OPEN"
        # The transition itself was version 2; the allocation then rewrote the
        # season's derived `held_series_count`, which is itself a mutation of
        # the row (PRD §2.4: "`version` ... increments by exactly 1 on every
        # mutation of that row, again including derived-field-only mutations").
        assert season["version"] == 3
        assert season["held_series_count"] == 1


class TestSeasonRefusesSkipsRepeatsAndReversals:
    """The target must be the immediate successor, never anything else."""

    def test_draft_straight_to_closed_is_refused_and_writes_nothing(self):
        """One status skipped is one status too many.

        PRD §3.2: "Asking a `DRAFT` season to go straight to `CLOSED`, or asking
        a season to transition to the status it already holds, is refused with
        `ERR_SEASON_STATE_INVALID`."

        Design: Corner/state_machines/season_transition_skipping_a_status_is_rejected_as_state_invalid
        """
        season = create_draft_season()

        validate_error(
            _open(season["id"], "CLOSED"),
            ApiErrorId.ERR_SEASON_STATE_INVALID,
            expected_status=409,
        )

        unchanged = read_season(season["id"], ADMIN)
        assert unchanged["status"] == "DRAFT"
        assert unchanged["version"] == 1

    def test_transitioning_to_the_status_already_held_is_refused(self):
        """`OPEN` to `OPEN` is not a no-op, it is a rejection.

        PRD §3.2: "The only legal path is `DRAFT` to `OPEN` to `CLOSED` to
        `ARCHIVED`, and the requested target must be the **immediate** successor
        of the current status."

        Design: Corner/state_machines/season_transition_skipping_a_status_is_rejected_as_state_invalid
        """
        season = create_draft_season()
        opened = validate_success(_open(season["id"]))
        assert opened["version"] == 2

        validate_error(
            _open(season["id"], "OPEN"), ApiErrorId.ERR_SEASON_STATE_INVALID
        )

        still_open = read_season(season["id"], ADMIN)
        assert still_open["status"] == "OPEN"
        assert still_open["version"] == 2

    def test_stepping_backwards_from_open_to_draft_is_refused(self):
        """The path runs one way only.

        PRD §3.2: "Advancing a season is a one-step-at-a-time affair, driven by a
        `SystemAdmin` supplying `to_status`."

        Design: Corner/state_machines/season_transition_skipping_a_status_is_rejected_as_state_invalid
        """
        season = create_draft_season()
        validate_success(_open(season["id"]))

        validate_error(
            _open(season["id"], "DRAFT"), ApiErrorId.ERR_SEASON_STATE_INVALID
        )

        still_open = read_season(season["id"], ADMIN)
        assert still_open["status"] == "OPEN"
        assert still_open["version"] == 2
        assert still_open["slot_audit_completed_at_utc"] is None


class TestArchivingWaitsForTheAudit:
    """A `CLOSED` season with a null audit stamp is not yet archivable."""

    def test_archive_before_the_audit_reports_audit_pending(self):
        """The refusal is the audit-specific one, not the generic path error.

        PRD §3.2: "Because archival depends on the audit having produced those
        verdicts, a `CLOSED → ARCHIVED` request while
        `slot_audit_completed_at_utc` is still null is refused with
        `ERR_SEASON_AUDIT_PENDING`."

        Design: Corner/state_machines/season_archive_before_the_slot_audit_is_rejected_as_audit_pending
        """
        season = create_draft_season()
        validate_success(_open(season["id"]))
        closed = validate_success(_open(season["id"], "CLOSED"))
        assert closed["status"] == "CLOSED"
        assert closed["version"] == 3
        assert closed["slot_audit_completed_at_utc"] is None

        validate_error(
            _open(season["id"], "ARCHIVED"),
            ApiErrorId.ERR_SEASON_AUDIT_PENDING,
            expected_status=409,
        )

        unchanged = read_season(season["id"], ADMIN)
        assert unchanged["status"] == "CLOSED"
        assert unchanged["version"] == 3
        assert unchanged["slot_audit_completed_at_utc"] is None

    def test_the_identical_archive_lands_once_the_audit_has_stamped_the_season(self):
        """Only the audit stamp changed between the refusal and the success.

        PRD §3.2: "The audit stamps `slot_audit_completed_at_utc` with the
        logical clock and records the supplied `audit_reference` on the season."

        Design: Corner/state_machines/season_archive_before_the_slot_audit_is_rejected_as_audit_pending
        """
        season = create_draft_season()
        validate_success(_open(season["id"]))
        validate_success(_open(season["id"], "CLOSED"))
        validate_error(
            _open(season["id"], "ARCHIVED"), ApiErrorId.ERR_SEASON_AUDIT_PENDING
        )

        summary = run_slot_audit(season["id"], audit_reference="AUD-W26-09")
        assert summary["audited_count"] == 0
        assert summary["audit_reference"] == "AUD-W26-09"

        audited = read_season(season["id"], ADMIN)
        assert_iso_timestamp(
            audited["slot_audit_completed_at_utc"], "slot_audit_completed_at_utc"
        )
        assert audited["audit_reference"] == "AUD-W26-09"
        # Stamping the season is itself a mutation of the row, so the audit
        # carried the counter from 3 to 4 before the archival stepped it again
        # (PRD §2.4).
        assert audited["version"] == 4

        archived = validate_success(_open(season["id"], "ARCHIVED"))
        assert archived["status"] == "ARCHIVED"
        assert archived["version"] == 5


# ─── The flight leg machine: CANCELLED is terminal ────────────────────────

def _cancelled_monday_leg():
    """One slot-backed Monday leg, then cancelled, so every field walked back."""
    world = setup_monday_series_schedule(
        leg_count=1, series_weeks=5, attach_count=1, version_label="W26-K1"
    )
    world["cancelled"] = cancel_leg(
        world["carrier"]["id"], world["legs"][0]["id"], "FLEET_REALLOCATION"
    )
    return world


class TestCancelledLegRefusesEveryFurtherAction:
    """The tail, the series and the version all walked back on the cancel."""

    def test_a_cancelled_leg_cannot_take_an_aircraft_again(self):
        """Assignment demands `DRAFT`, and `CANCELLED` is not it.

        PRD §3.3: "The leg must currently be in `DRAFT`, or the action is refused
        with `ERR_FLIGHT_LEG_STATE_INVALID`."

        Design: Corner/state_machines/cancelled_leg_refuses_every_further_action_endpoint
        """
        world = _cancelled_monday_leg()
        assert world["cancelled"]["status"] == "CANCELLED"
        assert world["cancelled"]["cancellation_reason"] == "FLEET_REALLOCATION"

        validate_error(
            api_client.assign_aircraft(
                world["legs"][0]["id"],
                {"aircraft_id": world["aircraft"]["id"]},
                world["planner"],
            ),
            ApiErrorId.ERR_FLIGHT_LEG_STATE_INVALID,
            expected_status=409,
        )

        tail = read_aircraft(world["aircraft"]["id"], world["planner"])
        assert tail["assigned_leg_count"] == 0
        assert tail["rotation_feasibility_status"] == "UNCHECKED"

    def test_a_cancelled_leg_cannot_be_retimed(self):
        """The permissive action is the one that draws the sharpest line.

        PRD §3.4: "A retime is permitted from any status except `CANCELLED`; on a
        cancelled leg it is refused with `ERR_FLIGHT_LEG_STATE_INVALID`."

        Design: Corner/state_machines/cancelled_leg_refuses_every_further_action_endpoint
        """
        world = _cancelled_monday_leg()

        validate_error(
            api_client.patch_flight_leg(
                world["legs"][0]["id"],
                {
                    "dep_utc": "2026-11-02T10:00:00.000Z",
                    "arr_utc": "2026-11-02T11:00:00.000Z",
                },
                world["planner"],
            ),
            ApiErrorId.ERR_FLIGHT_LEG_STATE_INVALID,
            expected_status=409,
        )

        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert holding["attached_operations"] == 0
        assert holding["utilization_pct_as_filed"] == pytest.approx(0.00, abs=0.01)
        assert holding["at_risk_of_loss"] is False

    def test_a_cancelled_leg_cannot_take_a_booking_snapshot(self):
        """The passenger side is closed too, and the version stayed repaired.

        PRD §3.4: "A snapshot is permitted on a leg in any status except
        `CANCELLED`."

        Design: Corner/state_machines/cancelled_leg_refuses_every_further_action_endpoint
        """
        world = _cancelled_monday_leg()

        validate_error(
            api_client.booking_snapshot(
                world["legs"][0]["id"],
                booking_snapshot_payload(2, 5, 30),
                world["planner"],
            ),
            ApiErrorId.ERR_FLIGHT_LEG_STATE_INVALID,
            expected_status=409,
        )

        leg = read_leg(world["legs"][0]["id"], world["planner"])
        assert leg["booked_first"] == 0
        assert leg["booked_business"] == 0
        assert leg["booked_economy"] == 0

        version = read_version(world["version"]["id"], world["planner"])
        assert version["leg_count"] == 1
        assert version["unslotted_leg_count"] == 0
        assert version["at_risk_slot_count"] == 0
        assert version["schedule_compliance_score"] == pytest.approx(100.00, abs=0.01)
        assert version["compliance_state"] == "CLEAN"


def _domestic_draft_leg(version_label: str = "W26-D2"):
    """A plain MUC->TXL leg in a fresh version, needing no slot at either end."""
    ref = setup_reference_data(("MUC", "TXL"))
    version = create_schedule_version(
        ref["carrier"]["id"], ref["season"]["id"], version_label=version_label
    )
    ref["version"] = version
    ref["leg"] = create_flight_leg(
        ref["carrier"]["id"],
        version["id"],
        ref["stations"]["MUC"]["id"],
        ref["stations"]["TXL"]["id"],
        "2026-11-03T08:00:00.000Z",
        "2026-11-03T09:00:00.000Z",
        flight_number="HX331",
    )
    return ref


class TestSecondCancellationIsRefused:
    """The first call is the transition; the second has nowhere to go."""

    def test_the_first_cancellation_records_the_reason_and_bumps_the_version(self):
        """`CANCELLED` is reached from `DRAFT` with the reason stored verbatim.

        PRD §3.4: "`cancellation_reason` records the supplied reason, and both
        slot holdings are detached, which recomputes each series'
        `attached_operations`, `utilization_pct_as_filed` and `at_risk_of_loss`."

        Design: Corner/state_machines/cancelling_an_already_cancelled_leg_is_rejected_on_the_second_call
        """
        world = _domestic_draft_leg()
        assert world["leg"]["version"] == 1

        cancelled = cancel_leg(
            world["carrier"]["id"], world["leg"]["id"], "DEMAND_SHORTFALL"
        )
        assert_flight_leg(cancelled)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "DEMAND_SHORTFALL"
        assert cancelled["version"] == 2

    def test_the_second_cancellation_is_refused_and_moves_nothing(self):
        """The reason of the surviving cancellation is the first one supplied.

        PRD §3.4: "**Cancelling a leg** takes a `reason` and is permitted from any
        status except `CANCELLED`; a second cancellation of an already-cancelled
        leg is refused with `ERR_FLIGHT_LEG_STATE_INVALID`."

        Design: Corner/state_machines/cancelling_an_already_cancelled_leg_is_rejected_on_the_second_call
        """
        world = _domestic_draft_leg()
        first = cancel_leg(
            world["carrier"]["id"], world["leg"]["id"], "DEMAND_SHORTFALL"
        )

        validate_error(
            api_client.cancel_flight_leg(
                world["leg"]["id"], {"reason": "FLEET_REALLOCATION"}, world["planner"]
            ),
            ApiErrorId.ERR_FLIGHT_LEG_STATE_INVALID,
            expected_status=409,
        )

        leg = read_leg(world["leg"]["id"], world["planner"])
        assert leg["status"] == "CANCELLED"
        assert leg["cancellation_reason"] == "DEMAND_SHORTFALL"
        assert leg["version"] == first["version"]

        version = read_version(world["version"]["id"], world["planner"])
        assert version["leg_count"] == 1
        assert version["unslotted_leg_count"] == 0


# ─── Validation: the promotion that stamps its actor ──────────────────────

def _validatable_domestic_version():
    """One MUC->TXL leg with a tail, so the version is ready for the gate."""
    world = setup_domestic_rotation_base(
        version_label="W26-V1",
        aircraft_overrides={"registration": "D-AHXV"},
    )
    leg = create_flight_leg(
        world["carrier"]["id"],
        world["version"]["id"],
        world["stations"]["MUC"]["id"],
        world["stations"]["TXL"]["id"],
        "2026-11-03T08:00:00.000Z",
        "2026-11-03T09:00:00.000Z",
        flight_number="HX340",
    )
    world["leg"] = assign_aircraft(
        world["carrier"]["id"], leg["id"], world["aircraft"]["id"]
    )
    return world


class TestValidationStampsTheValidatingUser:
    """The promotion is only permitted once, and it records who ran it."""

    def test_validation_promotes_the_version_and_stamps_the_officer(self):
        """The acting header, not the payload, is what lands on the row.

        PRD §3.7: "On success `filing_status` moves `DRAFT → VALIDATED` and
        `validated_by_user_id` is stamped with the acting `X-User-ID`."

        Design: Corner/state_machines/validate_stamps_the_validating_user_onto_the_schedule_version
        """
        world = _validatable_domestic_version()
        # Neither MUC nor TXL is fully coordinated, so the tail alone carries the
        # leg all the way to `SLOT_BACKED`.
        assert world["leg"]["status"] == "SLOT_BACKED"

        validated = validate_success(
            api_client.validate_schedule_version(world["version"]["id"], OFFICER)
        )
        assert_schedule_version(validated)
        assert validated["filing_status"] == "VALIDATED"
        assert validated["validated_by_user_id"] == "usr-comp-1"
        assert validated["compliance_state"] == "CLEAN"
        assert validated["schedule_compliance_score"] == pytest.approx(
            100.00, abs=0.01
        )
        assert validated["leg_count"] == 1

        assert read_leg(world["leg"]["id"], world["planner"])["status"] == "SLOT_BACKED"

    def test_validating_a_second_time_is_refused_and_keeps_the_first_stamp(self):
        """`VALIDATED` is not a legal starting point for the same gate.

        PRD §3.7: "It is permitted only from `DRAFT`; from `VALIDATED`, `FILED`,
        `SUPERSEDED` or `WITHDRAWN` it is refused with
        `ERR_SCHEDULE_VERSION_STATE_INVALID`."

        Design: Corner/state_machines/validate_stamps_the_validating_user_onto_the_schedule_version
        """
        world = _validatable_domestic_version()
        validate_version(world["version"]["id"])

        validate_error(
            api_client.validate_schedule_version(world["version"]["id"], OFFICER),
            ApiErrorId.ERR_SCHEDULE_VERSION_STATE_INVALID,
            expected_status=409,
        )

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_status"] == "VALIDATED"
        assert version["validated_by_user_id"] == "usr-comp-1"
        assert version["compliance_state"] == "CLEAN"


# ─── The carrier machine: a suspension that reaches downward ──────────────

def _carrier_with_two_draft_plans():
    """One airline, one season, two untouched candidate plans."""
    ref = setup_reference_data(("FRA", "MUC"))
    ref["plans"] = [
        create_schedule_version(
            ref["carrier"]["id"], ref["season"]["id"], version_label=label
        )
        for label in ("W26-S1", "W26-S2")
    ]
    return ref


def _suspend(carrier_id: str, reason: str = "AOC_SUSPENDED_BY_REGULATOR"):
    return api_client.suspend_carrier(carrier_id, {"reason": reason}, ADMIN)


class TestCarrierSuspensionCascadesToItsDraftPlans:
    """Suspension is not a flag; it withdraws the airline's open planning."""

    def test_both_draft_versions_are_driven_to_withdrawn(self):
        """The set cascade walks every draft plan of that carrier.

        PRD §3.1: "Every schedule version belonging to that carrier whose
        `filing_status` is `DRAFT` or `VALIDATED` is driven to `WITHDRAWN`, which
        in turn cancels each of those versions' non-cancelled legs and detaches
        their slot series exactly as a voluntary withdrawal would."

        Design: Corner/state_machines/carrier_suspension_cascades_down_to_its_draft_schedule_versions
        """
        ref = _carrier_with_two_draft_plans()
        for plan in ref["plans"]:
            assert plan["filing_status"] == "DRAFT"

        validate_success(_suspend(ref["carrier"]["id"]))

        for plan in ref["plans"]:
            withdrawn = read_version(plan["id"], ref["planner"])
            assert withdrawn["filing_status"] == "WITHDRAWN"
            assert withdrawn["leg_count"] == 0

    def test_the_suspended_carrier_may_not_open_another_plan(self):
        """The guard is forward-looking as well as retrospective.

        PRD §3.1: "From then on, any attempt to open a new schedule version,
        register a tail, allocate a slot series, or propose a slot transaction
        under that carrier is refused with `ERR_CARRIER_SUSPENDED`."

        Design: Corner/state_machines/carrier_suspension_cascades_down_to_its_draft_schedule_versions
        """
        ref = _carrier_with_two_draft_plans()
        validate_success(_suspend(ref["carrier"]["id"]))

        validate_error(
            api_client.create_schedule_version(
                create_schedule_version_payload(
                    ref["carrier"]["id"], ref["season"]["id"], version_label="W26-S3"
                ),
                ref["planner"],
            ),
            ApiErrorId.ERR_CARRIER_SUSPENDED,
            expected_status=409,
        )

        rows, meta = validate_paginated(
            api_client.list_schedule_versions(
                ref["planner"], params={"carrier_id": ref["carrier"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["version_label"] for row in rows) == ["W26-S1", "W26-S2"]

    def test_the_carrier_itself_moves_active_to_suspended_and_bumps_its_version(self):
        """The airline row is written once, whatever the cascade touched.

        PRD §3.1: "Suspending a carrier's operating licence takes a `reason` and
        drives its `status` from `ACTIVE` to `SUSPENDED`; the carrier must
        currently be `ACTIVE`."

        Design: Corner/state_machines/carrier_suspension_cascades_down_to_its_draft_schedule_versions
        """
        ref = _carrier_with_two_draft_plans()
        assert ref["carrier"]["status"] == "ACTIVE"
        assert ref["carrier"]["version"] == 1

        suspended = validate_success(_suspend(ref["carrier"]["id"]))
        assert suspended["status"] == "SUSPENDED"
        assert suspended["version"] == 2

        carrier = read_carrier(ref["carrier"]["id"], ADMIN)
        assert carrier["status"] == "SUSPENDED"
        assert carrier["version"] == 2
        assert carrier["held_series_count"] == 0


# ─── The audit: one sweep, two verdicts, never twice ──────────────────────

def _two_series_at_sixty_and_eighty_percent():
    """One series credited 3 of 5, another credited 4 of 5, season closed."""
    world = setup_series_with_utilization(
        outcomes_by_holding=[
            ["OPERATED", "OPERATED", "CANCELLED_ATC", "CANCELLED_CARRIER"],
            ["OPERATED", "OPERATED", "OPERATED", "OPERATED"],
        ],
        series_weeks=5,
        slot_times=("08:00", "09:00"),
        historic_precedence=True,
    )
    world["lost_side"], world["kept_side"] = world["holdings"]
    close_season(world["season"]["id"])
    return world


class TestAuditKeepsTheEightyPercentSeriesAndTakesTheSixtyPercentOne:
    """80.00 is retained inclusively; 60.00 is taken away."""

    def test_the_sweep_partitions_the_two_series_in_its_summary(self):
        """Two examined, one retained, one lost, both identifiers listed.

        PRD §3.2: "`retained_count` and `lost_count` partition that number, and
        `audited_slot_holding_ids` lists the identifiers it examined."

        Design: Corner/state_machines/slot_audit_lets_the_eighty_percent_series_live_and_takes_the_sixty_percent_one
        """
        world = _two_series_at_sixty_and_eighty_percent()
        assert world["lost_side"]["credited_operations"] == 3
        assert world["lost_side"]["utilization_pct"] == pytest.approx(60.00, abs=0.01)
        assert world["kept_side"]["credited_operations"] == 4
        assert world["kept_side"]["utilization_pct"] == pytest.approx(80.00, abs=0.01)

        summary = run_slot_audit(world["season"]["id"], audit_reference="AUD-W26-01")
        assert summary["audited_count"] == 2
        assert summary["retained_count"] == 1
        assert summary["lost_count"] == 1
        assert summary["audit_reference"] == "AUD-W26-01"
        assert sorted(summary["audited_slot_holding_ids"]) == sorted(
            [world["lost_side"]["id"], world["kept_side"]["id"]]
        )

    def test_the_two_verdicts_land_on_the_two_series(self):
        """One keeps its grandfather claim; the other loses both flags.

        PRD §3.2: "A series whose `utilization_pct` is at least 80.00 percent is
        retained: `retains_historic_precedence` is written true and the series
        stays `HELD`. A series strictly below 80.00 percent is taken away, moving
        `HELD → LOST` with both `historic_precedence` and
        `retains_historic_precedence` set to false."

        Design: Corner/state_machines/slot_audit_lets_the_eighty_percent_series_live_and_takes_the_sixty_percent_one
        """
        world = _two_series_at_sixty_and_eighty_percent()
        run_slot_audit(world["season"]["id"], audit_reference="AUD-W26-01")

        lost = read_holding(world["lost_side"]["id"], COORDINATOR)
        assert lost["holding_status"] == "LOST"
        assert lost["historic_precedence"] is False
        assert lost["retains_historic_precedence"] is False
        # The risk was realised rather than left pending.
        assert lost["at_risk_of_loss"] is False

        kept = read_holding(world["kept_side"]["id"], COORDINATOR)
        assert kept["holding_status"] == "HELD"
        assert kept["retains_historic_precedence"] is True
        assert kept["historic_precedence"] is True

        # No leg ever referenced the taken series, so nobody had to be notified.
        rows, meta = validate_paginated(
            api_client.list_notification_obligations(OFFICER)
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_second_sweep_is_refused_because_the_audit_is_not_idempotent(self):
        """The stamp from the first run is what bars the second.

        PRD §3.2: "it requires `slot_audit_completed_at_utc` to still be null,
        because the sweep is deliberately **not** idempotent and a second run is
        refused with `ERR_SLOT_AUDIT_ALREADY_RUN`."

        Design: Corner/state_machines/slot_audit_lets_the_eighty_percent_series_live_and_takes_the_sixty_percent_one
        """
        world = _two_series_at_sixty_and_eighty_percent()
        run_slot_audit(world["season"]["id"], audit_reference="AUD-W26-01")

        validate_error(
            api_client.run_slot_audit(
                world["season"]["id"], {"audit_reference": "AUD-W26-02"}, COORDINATOR
            ),
            ApiErrorId.ERR_SLOT_AUDIT_ALREADY_RUN,
            expected_status=409,
        )

        season = read_season(world["season"]["id"], ADMIN)
        assert season["status"] == "CLOSED"
        assert season["audit_reference"] == "AUD-W26-01"
        assert_iso_timestamp(
            season["slot_audit_completed_at_utc"], "slot_audit_completed_at_utc"
        )
        assert season["held_series_count"] == 1
