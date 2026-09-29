"""Error breadth: distinct identifiers for distinct causes.

Twelve reads of twelve entity types against an empty database, and one endpoint
whose three tail-level preconditions are broken one at a time so that each
refusal can only be explained by the rule it names.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_aircraft,
    create_flight_leg,
    read_aircraft,
    read_leg,
    setup_reference_data,
    validate_error,
    validate_success,
    create_schedule_version,
    MISSING_UUID,
    TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── Error 1: one not-found identifier per entity type ────────────────────

_MISSING_READS = (
    ("carrier", api_client.get_carrier, ApiErrorId.ERR_CARRIER_NOT_FOUND),
    ("station", api_client.get_station, ApiErrorId.ERR_STATION_NOT_FOUND),
    ("season", api_client.get_season, ApiErrorId.ERR_SEASON_NOT_FOUND),
    ("aircraft", api_client.get_aircraft, ApiErrorId.ERR_AIRCRAFT_NOT_FOUND),
    (
        "schedule version",
        api_client.get_schedule_version,
        ApiErrorId.ERR_SCHEDULE_VERSION_NOT_FOUND,
    ),
    ("flight leg", api_client.get_flight_leg, ApiErrorId.ERR_FLIGHT_LEG_NOT_FOUND),
    (
        "slot holding",
        api_client.get_slot_holding,
        ApiErrorId.ERR_SLOT_HOLDING_NOT_FOUND,
    ),
    (
        "utilization record",
        api_client.get_slot_utilization_record,
        ApiErrorId.ERR_SLOT_UTILIZATION_RECORD_NOT_FOUND,
    ),
    (
        "slot transaction",
        api_client.get_slot_transaction,
        ApiErrorId.ERR_SLOT_TRANSACTION_NOT_FOUND,
    ),
    (
        "filing submission",
        api_client.get_filing_submission,
        ApiErrorId.ERR_FILING_SUBMISSION_NOT_FOUND,
    ),
    (
        "route authority",
        api_client.get_route_authority,
        ApiErrorId.ERR_ROUTE_AUTHORITY_NOT_FOUND,
    ),
    (
        "notification obligation",
        api_client.get_notification_obligation,
        ApiErrorId.ERR_NOTIFICATION_OBLIGATION_NOT_FOUND,
    ),
)


class TestEveryEntityTypeHasItsOwnNotFoundIdentifier:
    """Twelve unresolvable reads against a database that holds nothing."""

    def test_each_unresolvable_read_names_its_own_entity_type(self):
        """A single shared not-found identifier would collapse twelve distinct
        outcomes into one, so every read is checked against its own.

        PRD §2.9: "A carrier that does not resolve gives
        `ERR_CARRIER_NOT_FOUND`; a station, `ERR_STATION_NOT_FOUND`; a season,
        `ERR_SEASON_NOT_FOUND`; a tail, `ERR_AIRCRAFT_NOT_FOUND`; a schedule
        version, `ERR_SCHEDULE_VERSION_NOT_FOUND`"

        PRD §2.9: "a utilization record,
        `ERR_SLOT_UTILIZATION_RECORD_NOT_FOUND`; a slot transaction,
        `ERR_SLOT_TRANSACTION_NOT_FOUND`; a filing submission,
        `ERR_FILING_SUBMISSION_NOT_FOUND`; a route authority,
        `ERR_ROUTE_AUTHORITY_NOT_FOUND`; a notification obligation,
        `ERR_NOTIFICATION_OBLIGATION_NOT_FOUND`. All of these are HTTP 404."

        Design: Corner/errors/every_entity_type_has_its_own_not_found_error_id
        """
        seen = []
        for label, reader, error_id in _MISSING_READS:
            error = validate_error(
                reader(MISSING_UUID, ADMIN), error_id, expected_status=404
            )
            assert error["error_id"] == error_id.value, label
            seen.append(error["error_id"])

        assert len(set(seen)) == 12

    def test_the_refusal_carries_only_the_error_envelope(self):
        """The body of a 404 is an error envelope and nothing else - no entity
        fields ride along beside the identifier and the message.

        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/every_entity_type_has_its_own_not_found_error_id
        """
        for label, reader, error_id in _MISSING_READS:
            response = reader(MISSING_UUID, ADMIN)
            validate_error(response, error_id, expected_status=404)

            body = response.json()
            assert body["response_type"] == "error", label
            assert set(body["data"].keys()) == {"error_id", "message"}, label
            assert body["data"]["message"].strip() != "", label
            assert set(body["meta"].keys()) == {
                "api_request_id",
                "api_request_timestamp",
            }, label
            assert body["meta"]["api_request_id"].startswith("req_"), label


# ─── Error 2: three tail preconditions on one endpoint ────────────────────

def _four_tails_and_one_boeing_leg():
    """One `B738` leg and four tails, three of which break one rule each."""
    ref = setup_reference_data(("MUC", "TXL"), with_partner=True)
    carrier, partner = ref["carrier"], ref["partner"]
    muc = ref["stations"]["MUC"]["id"]

    ref["good"] = create_aircraft(
        carrier["id"], muc, registration="D-AHXA", fleet_type_code="B738"
    )
    ref["grounded"] = create_aircraft(
        carrier["id"],
        muc,
        registration="D-AHXB",
        fleet_type_code="B738",
        status="MAINTENANCE_GROUNDED",
    )
    ref["wrong_fleet"] = create_aircraft(
        carrier["id"],
        muc,
        registration="D-AHXC",
        fleet_type_code="A320",
        seats=180,
    )
    ref["other_carrier"] = create_aircraft(
        partner["id"], muc, registration="CS-XPA", fleet_type_code="B738"
    )

    ref["version"] = create_schedule_version(
        carrier["id"], ref["season"]["id"], version_label="W26-E1"
    )
    ref["leg"] = create_flight_leg(
        carrier["id"],
        ref["version"]["id"],
        muc,
        ref["stations"]["TXL"]["id"],
        "2026-11-03T08:00:00.000Z",
        "2026-11-03T09:00:00.000Z",
        flight_number="HX320",
        fleet_type_code="B738",
    )
    return ref


def _assign(world, tail_key):
    return api_client.assign_aircraft(
        world["leg"]["id"],
        {"aircraft_id": world[tail_key]["id"]},
        world["planner"],
    )


class TestAssignAircraftAnswersEachBrokenPreconditionWithItsOwnIdentifier:
    """The same call and the same leg, refused for three different reasons."""

    def test_a_grounded_tail_is_refused_on_airworthiness(self):
        """The fleet code and the ownership both match, so only the tail's own
        status can explain the refusal.

        PRD §3.3: "the tail's `status` must be `IN_SERVICE`, and a
        `MAINTENANCE_GROUNDED` or `RETIRED` tail is refused with
        `ERR_AIRCRAFT_NOT_IN_SERVICE`"

        Design: Corner/errors/assign_aircraft_answers_each_broken_precondition_with_its_own_error_id
        """
        world = _four_tails_and_one_boeing_leg()

        validate_error(
            _assign(world, "grounded"),
            ApiErrorId.ERR_AIRCRAFT_NOT_IN_SERVICE,
            expected_status=422,
        )

        leg = read_leg(world["leg"]["id"], OFFICER)
        assert leg["status"] == "DRAFT"
        assert leg["assigned_aircraft_id"] is None

    def test_an_in_service_tail_of_the_wrong_fleet_is_refused_on_equipment(self):
        """Airworthiness is satisfied, so the second check in the pinned order
        is the one that answers.

        PRD §3.3: "the tail's `fleet_type_code` must equal the leg's own
        `fleet_type_code`, else `ERR_FLEET_TYPE_MISMATCH`"

        Design: Corner/errors/assign_aircraft_answers_each_broken_precondition_with_its_own_error_id
        """
        world = _four_tails_and_one_boeing_leg()

        validate_error(
            _assign(world, "wrong_fleet"),
            ApiErrorId.ERR_FLEET_TYPE_MISMATCH,
            expected_status=422,
        )

        assert read_leg(world["leg"]["id"], OFFICER)["status"] == "DRAFT"

    def test_another_airlines_matching_tail_is_refused_on_ownership(self):
        """The partner's tail is `IN_SERVICE` and is a `B738`, so the first two
        checks pass and only the third is left to fire.

        PRD §3.3: "the tail's `carrier_id` must equal the `carrier_id` of the
        leg's schedule version, else `ERR_AIRCRAFT_CARRIER_MISMATCH`"

        Design: Corner/errors/assign_aircraft_answers_each_broken_precondition_with_its_own_error_id
        """
        world = _four_tails_and_one_boeing_leg()

        validate_error(
            _assign(world, "other_carrier"),
            ApiErrorId.ERR_AIRCRAFT_CARRIER_MISMATCH,
            expected_status=422,
        )

        assert read_leg(world["leg"]["id"], OFFICER)["status"] == "DRAFT"

    def test_the_one_conforming_tail_is_accepted_and_the_rejects_stay_untouched(self):
        """Three refusals leave nothing behind: only the accepted tail carries a
        leg, and the leg auto-advances because neither airport needs a slot.

        PRD §3.3: "After the assignment lands and the leg reaches `ASSIGNED`,
        if the leg needs no slot at all - because neither its origin nor its
        destination station is `LEVEL_3_COORDINATED` - or if every slot it does
        need is already attached, the leg immediately auto-advances `ASSIGNED →
        SLOT_BACKED` inside the very same request."

        PRD §3.3: "`rotation_feasibility_status` is `UNCHECKED` only while that
        count is 0; once the tail carries at least one leg it must hold one of
        `FEASIBLE`, `INFEASIBLE_CONTINUITY`, `INFEASIBLE_TURN` or
        `INFEASIBLE_BLOCK_CAP`."

        Design: Corner/errors/assign_aircraft_answers_each_broken_precondition_with_its_own_error_id
        """
        world = _four_tails_and_one_boeing_leg()
        for tail_key, error_id in (
            ("grounded", ApiErrorId.ERR_AIRCRAFT_NOT_IN_SERVICE),
            ("wrong_fleet", ApiErrorId.ERR_FLEET_TYPE_MISMATCH),
            ("other_carrier", ApiErrorId.ERR_AIRCRAFT_CARRIER_MISMATCH),
        ):
            validate_error(_assign(world, tail_key), error_id)

        assigned = validate_success(_assign(world, "good"))
        assert assigned["assigned_aircraft_id"] == world["good"]["id"]
        assert assigned["status"] == "SLOT_BACKED"

        flown = read_aircraft(world["good"]["id"], OFFICER)
        assert flown["assigned_leg_count"] == 1
        assert flown["rotation_feasibility_status"] == "FEASIBLE"

        for tail_key in ("grounded", "wrong_fleet"):
            idle = read_aircraft(world[tail_key]["id"], OFFICER)
            assert idle["assigned_leg_count"] == 0
            assert idle["rotation_feasibility_status"] == "UNCHECKED"
