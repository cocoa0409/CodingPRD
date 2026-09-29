"""Three requests that violate two rules at once.

Each pair is proved twice over: first the lower-priority rule is shown to be
genuinely live on the very same request, then the higher-priority violation is
added and the reported error changes.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_carrier,
    create_flight_leg_payload,
    create_open_season,
    create_schedule_version,
    create_slot_holding,
    create_station,
    make_network_planner_headers,
    read_holding,
    read_season,
    read_submission,
    read_version,
    retime_leg,
    set_clock,
    setup_monday_series_schedule,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
AGENT = TEST_USERS["filing_agent_headers"]


def _held_series_past_the_return_deadline():
    """A held series whose season's return deadline is already in the past."""
    carrier = create_carrier()
    fra = create_station("FRA")
    season = create_open_season()
    holding = create_slot_holding(
        fra["id"], season["id"], carrier["id"], historic_precedence=False
    )
    set_clock("2026-09-20T00:00:00.000Z")
    return {
        "carrier": carrier,
        "planner": make_network_planner_headers(carrier["id"]),
        "season": season,
        "holding": holding,
    }


def _return_request(world):
    return api_client.return_slot_holding(
        world["holding"]["id"], {"reason": "NETWORK_RESTRUCTURE"}, world["planner"]
    )


class TestSeasonStateOutranksReturnDeadline:
    """The identical return request answers 422 while open and 409 once
    closed."""

    def test_the_passed_deadline_is_reported_while_the_season_is_open(self):
        """The lower-priority temporal rule is genuinely violated by this
        request.

        PRD §3.5: "the logical clock must not have passed the season's
        `slot_return_deadline_utc` (`ERR_SLOT_RETURN_DEADLINE_PASSED`)"

        Design: Difficulty/priority_pair_validation_conflict/season_not_open_outranks_slot_return_deadline_passed_on_the_same_return
        """
        world = _held_series_past_the_return_deadline()

        validate_error(
            _return_request(world),
            ApiErrorId.ERR_SLOT_RETURN_DEADLINE_PASSED,
            expected_status=422,
        )

    def test_closing_the_season_replaces_the_deadline_error(self):
        """Same payload, same clock, different error: the season objection
        wins.

        PRD §2.9: "A slot return attempted against a season that is no longer
        `OPEN` **and** whose slot return deadline has already passed must report
        `ERR_SEASON_NOT_OPEN`, not `ERR_SLOT_RETURN_DEADLINE_PASSED`"

        Design: Difficulty/priority_pair_validation_conflict/season_not_open_outranks_slot_return_deadline_passed_on_the_same_return
        """
        world = _held_series_past_the_return_deadline()
        validate_error(
            _return_request(world), ApiErrorId.ERR_SLOT_RETURN_DEADLINE_PASSED
        )

        validate_success(
            api_client.transition_season(
                world["season"]["id"], {"to_status": "CLOSED"}, ADMIN
            )
        )

        validate_error(
            _return_request(world), ApiErrorId.ERR_SEASON_NOT_OPEN, expected_status=409
        )

    def test_neither_rejection_touched_the_series(self):
        """Two failed returns leave the holding exactly as it was.

        PRD §3.5: "On success `holding_status` moves `HELD → RETURNED`,
        `returned_reason` records the supplied reason, `returned_before_deadline`
        is set to true and `retains_historic_precedence` is set to true."

        Design: Difficulty/priority_pair_validation_conflict/season_not_open_outranks_slot_return_deadline_passed_on_the_same_return
        """
        world = _held_series_past_the_return_deadline()
        validate_error(
            _return_request(world), ApiErrorId.ERR_SLOT_RETURN_DEADLINE_PASSED
        )
        validate_success(
            api_client.transition_season(
                world["season"]["id"], {"to_status": "CLOSED"}, ADMIN
            )
        )
        validate_error(_return_request(world), ApiErrorId.ERR_SEASON_NOT_OPEN)

        holding = read_holding(world["holding"]["id"], world["planner"])
        assert holding["holding_status"] == "HELD"
        assert holding["returned_before_deadline"] is None
        assert holding["retains_historic_precedence"] is None
        assert holding["returned_reason"] is None

        season = read_season(world["season"]["id"], ADMIN)
        assert season["status"] == "CLOSED"
        assert season["held_series_count"] == 1


def _international_night_arrival_without_a_traffic_right():
    """A draft version and a MUC->LIS pair with no DE/PT authority granted."""
    carrier = create_carrier()
    muc = create_station("MUC")
    lis = create_station("LIS", gate_count=2, maintenance_capable=False)
    season = create_open_season()
    version = create_schedule_version(
        carrier["id"], season["id"], version_label="W26-P2"
    )
    return {
        "carrier": carrier,
        "planner": make_network_planner_headers(carrier["id"]),
        "version": version,
        "leg_payload": create_flight_leg_payload(
            version["id"],
            muc["id"],
            lis["id"],
            "2026-11-03T21:00:00.000Z",
            "2026-11-03T23:30:00.000Z",
            flight_number="HX880",
        ),
    }


class TestCurfewOutranksRouteAuthority:
    """Two 422s on the same creation: only the error_id separates them."""

    def test_the_missing_traffic_right_surfaces_once_the_curfew_is_waived(self):
        """The lower-priority referential rule is genuinely violated by this
        leg.

        PRD §3.4: "A leg whose origin and destination countries differ is
        international, and it must have a matching route authority granted to the
        acting carrier on that country pair, matched as an **unordered** pair so
        that one authority covers both directions; with no such authority the leg
        is refused with `ERR_ROUTE_AUTHORITY_MISSING`."

        Design: Difficulty/priority_pair_validation_conflict/curfew_violation_outranks_route_authority_missing_on_the_same_leg_creation
        """
        world = _international_night_arrival_without_a_traffic_right()
        payload = dict(world["leg_payload"])
        payload["curfew_waiver_reference"] = "NIGHT-01"

        validate_error(
            api_client.create_flight_leg(payload, world["planner"]),
            ApiErrorId.ERR_ROUTE_AUTHORITY_MISSING,
            expected_status=422,
        )

    def test_the_unwaived_curfew_replaces_the_route_authority_error(self):
        """Dropping the waiver flips the error_id while the status stays 422.

        PRD §2.9: "And a leg that both lands inside a night curfew **and** has no
        traffic right at all must report `ERR_CURFEW_VIOLATION`, not
        `ERR_ROUTE_AUTHORITY_MISSING`"

        Design: Difficulty/priority_pair_validation_conflict/curfew_violation_outranks_route_authority_missing_on_the_same_leg_creation
        """
        world = _international_night_arrival_without_a_traffic_right()

        waived = dict(world["leg_payload"])
        waived["curfew_waiver_reference"] = "NIGHT-01"
        first = api_client.create_flight_leg(waived, world["planner"])
        first_error = validate_error(first, ApiErrorId.ERR_ROUTE_AUTHORITY_MISSING)

        second = api_client.create_flight_leg(world["leg_payload"], world["planner"])
        second_error = validate_error(
            second, ApiErrorId.ERR_CURFEW_VIOLATION, expected_status=422
        )

        # Both objections carry 422, so error_id is the only discriminator.
        assert first.status_code == 422
        assert second.status_code == 422
        assert first_error["error_id"] != second_error["error_id"]

    def test_neither_rejected_creation_left_a_partial_leg(self):
        """The version is still empty and still scoring a clean 100.00.

        PRD §3.4: "The check is skipped, the leg is accepted, and the leg counts
        toward the version's `curfew_violation_count` for the entire time it
        remains non-cancelled."

        Design: Difficulty/priority_pair_validation_conflict/curfew_violation_outranks_route_authority_missing_on_the_same_leg_creation
        """
        world = _international_night_arrival_without_a_traffic_right()
        waived = dict(world["leg_payload"])
        waived["curfew_waiver_reference"] = "NIGHT-01"
        validate_error(
            api_client.create_flight_leg(waived, world["planner"]),
            ApiErrorId.ERR_ROUTE_AUTHORITY_MISSING,
        )
        validate_error(
            api_client.create_flight_leg(world["leg_payload"], world["planner"]),
            ApiErrorId.ERR_CURFEW_VIOLATION,
        )

        version = read_version(world["version"]["id"], world["planner"])
        assert version["leg_count"] == 0
        assert version["curfew_violation_count"] == 0
        assert version["schedule_compliance_score"] == pytest.approx(100.00, abs=0.01)
        assert version["compliance_state"] == "CLEAN"

        rows, meta = validate_paginated(
            api_client.list_flight_legs(
                world["planner"], params={"schedule_version_id": world["version"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []


def _queued_submission_over_a_tiny_budget():
    """Four legs filed STANDARD for 16900 cents against a budget of 1000."""
    return setup_monday_series_schedule(
        leg_count=4,
        series_weeks=5,
        version_label="W26-B1",
        budget_cents=1000,
        validate=True,
        submission={"change_window": "STANDARD"},
    )


class TestScheduleBlockedOutranksBudget:
    """The same transmit answers 402 when clean and 409 once blocked."""

    def test_the_budget_is_reported_while_the_version_is_clean(self):
        """The lower-priority fiscal rule is genuinely violated by this
        transmit.

        PRD §3.8: "the version's `filing_charge_accrued_cents` plus this
        submission's `total_charge_cents` must be no greater than its
        `filing_charge_budget_cents`, or it fails with
        `ERR_FILING_CHARGE_BUDGET_EXCEEDED`, which is the one payment-related
        status in the catalogue."

        Design: Difficulty/priority_pair_validation_conflict/schedule_blocked_outranks_filing_charge_budget_exceeded_on_the_same_transmit
        """
        world = _queued_submission_over_a_tiny_budget()
        submission_id = world["submission"]["id"]
        assert world["submission"]["total_charge_cents"] == 16900

        validate_error(
            api_client.transmit_filing_submission(submission_id, AGENT),
            ApiErrorId.ERR_FILING_CHARGE_BUDGET_EXCEEDED,
            expected_status=402,
        )

        submission = read_submission(submission_id, AGENT)
        assert submission["status"] == "QUEUED"
        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_charge_accrued_cents"] == 0

    def test_blocking_the_version_replaces_the_budget_error(self):
        """The identical transmit now answers 409 on compliance instead.

        PRD §2.9: "A transmission that is both blocked on compliance **and** over
        the version's filing charge budget must report `ERR_SCHEDULE_BLOCKED`,
        not `ERR_FILING_CHARGE_BUDGET_EXCEEDED`"

        Design: Difficulty/priority_pair_validation_conflict/schedule_blocked_outranks_filing_charge_budget_exceeded_on_the_same_transmit
        """
        world = _queued_submission_over_a_tiny_budget()
        submission_id = world["submission"]["id"]
        validate_error(
            api_client.transmit_filing_submission(submission_id, AGENT),
            ApiErrorId.ERR_FILING_CHARGE_BUDGET_EXCEEDED,
        )

        retime_leg(
            world["carrier"]["id"],
            world["legs"][3]["id"],
            "2026-11-23T10:00:00.000Z",
            "2026-11-23T11:00:00.000Z",
        )
        version = read_version(world["version"]["id"], world["planner"])
        assert version["at_risk_slot_count"] == 1
        assert version["unslotted_leg_count"] == 1
        assert version["schedule_compliance_score"] == pytest.approx(77.00, abs=0.01)
        assert version["compliance_state"] == "BLOCKED"

        validate_error(
            api_client.transmit_filing_submission(submission_id, AGENT),
            ApiErrorId.ERR_SCHEDULE_BLOCKED,
            expected_status=409,
        )

    def test_the_block_cascade_leaves_a_queued_submission_and_its_price_alone(self):
        """A QUEUED submission is untouched by the rejection cascade.

        PRD §3.7: "A submission still sitting in `QUEUED` is deliberately left
        alone by that cascade - it never reached a distribution system and never
        accrued a charge, so there is nothing to reverse; instead its later
        transmit attempt is what fails, with `ERR_SCHEDULE_BLOCKED`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_blocked_outranks_filing_charge_budget_exceeded_on_the_same_transmit
        """
        world = _queued_submission_over_a_tiny_budget()
        submission_id = world["submission"]["id"]
        validate_error(
            api_client.transmit_filing_submission(submission_id, AGENT),
            ApiErrorId.ERR_FILING_CHARGE_BUDGET_EXCEEDED,
        )
        retime_leg(
            world["carrier"]["id"],
            world["legs"][3]["id"],
            "2026-11-23T10:00:00.000Z",
            "2026-11-23T11:00:00.000Z",
        )
        validate_error(
            api_client.transmit_filing_submission(submission_id, AGENT),
            ApiErrorId.ERR_SCHEDULE_BLOCKED,
        )

        submission = read_submission(submission_id, AGENT)
        assert submission["status"] == "QUEUED"
        assert submission["total_charge_cents"] == 16900
        assert submission["expedite_fee_cents"] == 0
        assert submission["rejection_reason"] is None

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_status"] == "VALIDATED"
        assert version["filing_charge_accrued_cents"] == 0
