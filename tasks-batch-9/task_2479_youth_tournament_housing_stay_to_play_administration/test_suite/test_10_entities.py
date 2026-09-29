"""What each record looks like the moment the server hands it back.

Creations that must already carry their derived arithmetic, reads and filtered
lists that must echo what was stored, rejections of malformed or dangling input,
and the two record shapes that carry no version at all.
"""

from test_helpers import (
    CLOCK_STARTUP_UTC,
    HOUSING_MANAGER_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    ComplaintCategory,
    RebateModel,
    assertions,
    factories as f,
    fixtures as fx,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS

# The logical clock's startup instant, rendered the way a stamped field carries it.
CLOCK_START_STAMP = "2026-08-01T00:00:00.000Z"


def _two_contracts_one_negotiating_env(api):
    """One event holding two host-hotel contracts: the first has been submitted
    and sits at `NEGOTIATING`, the second is still a draft. Returns the
    environment carrying the negotiating contract plus the draft contract."""
    env = fx.negotiating_contract_env(api)
    second_hotel = fx.create_hotel(
        api, name="Riverfront Suites", total_rooms=80, distance_miles_from_venue=6.0
    )
    draft_contract = validate_success(
        api.create_hotel_contract(
            f.hotel_contract_payload(
                env.tournament_id,
                second_hotel["id"],
                negotiated_nightly_rate_cents=15900,
                rebate_flat_cents_per_room_night=800,
                attrition_penalty_rate_cents_per_room_night=800,
            ),
            HM,
        ),
        201,
    )
    return env, draft_contract


def _complaint_subjects_env(api) -> fx.Env:
    """A registration that owns both a draft booking and a live exemption
    request, so one complaint can name a registration, an exemption decision and
    a booking at once."""
    env = fx.draft_booking_env(api)
    fx.add_exception_request(env)
    return env


class TestTournamentCreation:
    """The event record every other resource hangs off."""

    def test_creating_an_event_returns_its_inputs_and_its_derived_openings(self, api):
        """A four-day window from the 10th to the 13th is stamped as three
        nights, and the new event opens with nothing contracted and no pressure.

        PRD §3.1: "When both hold, the server computes `night_count` as the
        number of whole days from `start_date` up to but not including
        `end_date` — the event window is half-open, so the night that begins on
        `end_date` is not part of the event."

        PRD §3.1: "A new tournament begins with `posture` at `OPEN`,
        `housing_pressure` at `NORMAL`, and both derived contract counters —
        `executed_contract_count` and `sold_out_contract_count` — at 0."

        PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601
        UTC timestamp in the same format, and `version`, an integer that starts
        at 1 when the row is created and is incremented by exactly 1 on every
        mutation of that row."

        PRD §4: "Status codes follow one uniform rule: an endpoint that creates a
        new resource responds with `201 Created` and returns the created resource
        in `data`, while an endpoint that reads a resource, lists resources, or
        modifies or transitions an existing resource responds with `200 OK` and
        returns the read or updated resource in `data`."

        Design: Corner/entities/tournament_creation_returns_all_declared_fields
        """
        tournament = validate_success(
            api.create_tournament(f.tournament_payload(), HM), 201
        )

        assert tournament["name"] == "Fall Classic 2026"
        assert tournament["rights_holder_org"] == "USYS"
        assert tournament["destination_org"] == "Metro CVB"
        assert tournament["start_date"] == "2026-09-10"
        assert tournament["end_date"] == "2026-09-13"
        assert tournament["booking_deadline"] == "2026-09-01T00:00:00Z"
        assert tournament["share_pct_organizer"] == 0.5
        assert tournament["share_pct_rights_holder"] == 0.3
        assert tournament["share_pct_destination"] == 0.2
        assert tournament["stay_to_play_required"] is True
        assert tournament["night_count"] == 3
        assert tournament["posture"] == "OPEN"
        assert tournament["housing_pressure"] == "NORMAL"
        assert tournament["executed_contract_count"] == 0
        assert tournament["sold_out_contract_count"] == 0
        assertions.assert_versioned_record(tournament, 1)


class TestStayToPlayDefault:
    """The one input field the event record fills in for itself."""

    def test_omitting_the_stay_to_play_flag_stores_it_as_required(self, api):
        """An event created without the flag comes back with the policy in
        force rather than switched off or left empty.

        PRD §3.1: "An optional `stay_to_play_required` boolean may be supplied;
        when it is omitted it defaults to `true`, meaning every registered team
        must end up either housing-compliant or exception-granted."

        Design: Corner/entities/tournament_stay_to_play_default_applied_when_omitted
        """
        tournament = validate_success(
            api.create_tournament(
                f.tournament_payload(
                    name="Default Probe Cup", stay_to_play_required=None
                ),
                HM,
            ),
            201,
        )

        assert tournament["stay_to_play_required"] is True

    def test_a_team_on_a_defaulted_event_is_not_waved_through_as_compliant(self, api):
        """Because the policy defaults to in force, a freshly registered team
        still owes its four pooled rooms and waits at pending rather than being
        excused outright.

        PRD §3.3: "If the tournament's `stay_to_play_required` is `false`, the
        registration is `HOUSING_COMPLIANT` outright — the policy is not in
        force."

        PRD §3.3: "Otherwise, if the tournament's `posture` is still `OPEN`, the
        registration is `PENDING_HOUSING` — it has time left to book."

        Design: Corner/entities/tournament_stay_to_play_default_applied_when_omitted
        """
        tournament = validate_success(
            api.create_tournament(
                f.tournament_payload(
                    name="Default Probe Cup", stay_to_play_required=None
                ),
                HM,
            ),
            201,
        )
        team = fx.create_team(api)

        registration = validate_success(
            api.create_team_registration(
                f.team_registration_payload(tournament["id"], team["id"]), HM
            ),
            201,
        )

        assert registration["committed_rooms"] == 0
        assert registration["effective_required_rooms"] == 4
        assert registration["status"] == "PENDING_HOUSING"


class TestHotelContractReads:
    """Reading one contract, and reading a filtered page of them."""

    def test_reading_a_contract_echoes_its_terms_and_its_contracted_volume(self, api):
        """The stored draft reads back with its negotiated rate and flat rebate
        intact, the unused percent parameter defaulted to zero, and sixty
        contracted room nights from its single twenty-room three-night block.

        PRD §3.2: "A freshly drafted contract sits at `status` `DRAFT` with
        `block_posture` `AVAILABLE`, `revision_round` at 0,
        `contracted_room_nights` at 0 and `countersigned_by_hotel_id` null."

        PRD §3.2: "Whichever fields are omitted default to 0 on the stored
        record."

        PRD §3.2: "Finally, the block's contracted volume — `block_size_rooms`
        multiplied by its night count — is added into the contract's
        `contracted_room_nights`, which stands as the sum of that product over
        every block of the contract whose `status` is `OPEN`, `RESTRICTED`,
        `RELEASED` or `SETTLED`."

        PRD §3.2: "Otherwise it is `AVAILABLE`."

        Design: Corner/entities/hotel_contract_retrieval_returns_stored_data
        """
        env = fx.draft_contract_env(api)
        fx.add_block(env)

        contract = validate_success(api.get_hotel_contract(env.contract_id, HM))

        assert contract["id"] == env.contract_id
        assert contract["tournament_id"] == env.tournament_id
        assert contract["hotel_id"] == env.hotel_id
        assert contract["status"] == "DRAFT"
        assert contract["negotiated_nightly_rate_cents"] == 14900
        assert contract["rebate_model"] == RebateModel.PER_ROOM_NIGHT_FLAT.value
        assert contract["rebate_flat_cents_per_room_night"] == 900
        assert contract["rebate_percent"] == 0
        assert contract["attrition_threshold_pct"] == 0.1
        assert contract["attrition_penalty_rate_cents_per_room_night"] == 900
        assert contract["cutoff_date"] == "2026-08-20"
        assert contract["contracted_room_nights"] == 60
        assert contract["block_posture"] == "AVAILABLE"
        assert contract["revision_round"] == 0
        assert contract["countersigned_by_hotel_id"] is None

    def test_a_status_filtered_page_counts_only_the_matching_contracts(self, api):
        """With two contracts on the event and only one in negotiation, asking
        for the negotiating ones a page at a time returns that single row and
        counts the filtered population rather than the whole table.

        PRD §2.3: "For every list response, the `meta` block carries `limit`,
        `offset`, `total_count` and `has_more`, where `total_count` is the number
        of rows matching the filters before pagination and `has_more` indicates
        whether rows remain beyond the current page."

        PRD §2.3: "List endpoints additionally accept the domain filters named in
        their §4 descriptions; a filter that is supplied narrows the result set
        by exact match on the named field, and filters combine conjunctively."

        Design: Corner/entities/hotel_contract_listing_paginates_and_filters
        """
        env, draft_contract = _two_contracts_one_negotiating_env(api)

        rows, meta = validate_paginated(
            api.list_hotel_contracts(
                HM,
                params={
                    "tournament_id": env.tournament_id,
                    "status": "NEGOTIATING",
                    "limit": 1,
                    "offset": 0,
                },
            )
        )

        assert meta["total_count"] == 1
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["id"] == env.contract_id
        assert rows[0]["status"] == "NEGOTIATING"
        assert draft_contract["status"] == "DRAFT"


class TestTeamRegistrationFields:
    """The registration record and the two room requirements it derives."""

    def test_a_registration_missing_its_staff_count_is_refused_and_not_stored(
        self, api
    ):
        """The staff head count is part of the declared input, so leaving it out
        is a schema failure rather than a silent zero, and no registration
        appears on the event afterwards.

        PRD §3.3: "Either a `HousingManager` or the team's own `TeamManager`
        submits `tournament_id`, `team_id`, `roster_player_count` (at least 1)
        and `roster_staff_count` (at least 0), and the tournament must be
        `OPEN`."

        PRD §2.6: "Requests are also checked against the endpoint's input schema:
        required fields must be present, unknown fields are refused, enum-typed
        fields must carry a declared member, integer counts must respect their
        declared non-negativity, dates and datetimes must be well-formed ISO 8601
        values, and pagination parameters must fall in range."

        PRD §2.6: "Any of these failures produces `ERR_INVALID_REQUEST` with HTTP
        400."

        Design: Corner/entities/team_registration_missing_required_field_is_rejected
        """
        tournament = fx.create_tournament(api)
        team = fx.create_team(api)

        response = api.create_team_registration(
            f.team_registration_payload(
                tournament["id"], team["id"], roster_staff_count=None
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )
        rows, meta = validate_paginated(
            api.list_team_registrations(HM, params={"tournament_id": tournament["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_registering_derives_both_room_requirements_from_the_roster_alone(
        self, api
    ):
        """Thirteen players and three staff buy six rooms at most under the
        segregated split and owe four at least under the pooled one, the event's
        three nights turn six rooms into eighteen room nights, and the team's own
        distance rather than anything on the registration settles its locality.

        PRD §3.3: "At creation the server derives `local_team_flag` by reading
        the referenced team's `distance_miles_from_venue` and testing it against
        a local radius of thirty miles: the flag is `true` when the team's home
        city lies at or within thirty miles of the venue, and `false` otherwise."

        PRD §3.3: "Take `roster_player_count`, divide by four and round **up** to
        a whole number of player rooms; take `roster_staff_count`, divide by two
        and round **up** to a whole number of staff rooms; add the two counts."

        PRD §3.3: "The registration also stores `required_room_nights`, which is
        `required_rooms_registered` multiplied by the tournament's `night_count`."

        PRD §3.3: "Here players and staff share rooms at the four-per-room
        capacity: add `roster_player_count` and `roster_staff_count`, divide the
        single pooled total by four, and round **up** once."

        PRD §3.3: "The rest of the registration record is initialised to
        `exempt_rooms_granted` of 0, `effective_required_rooms` equal to
        `minimum_rooms_for_compliance`, `committed_rooms` of 0 and `status`
        `PENDING_HOUSING`."

        PRD §2.5: "Every timestamp the server stamps onto a resource —
        `created_at`, `updated_at`, `cancelled_at`, `compliance_evaluated_at` —
        reads the logical clock, so a test-driven sequence of operations produces
        deterministic timestamps."

        Design: Corner/entities/registration_computed_room_requirements_are_server_derived
        """
        fx.set_clock(api, CLOCK_STARTUP_UTC)
        tournament = fx.create_tournament(api)
        team = fx.create_team(api)

        registration = validate_success(
            api.create_team_registration(
                f.team_registration_payload(tournament["id"], team["id"]), HM
            ),
            201,
        )

        assert registration["tournament_id"] == tournament["id"]
        assert registration["team_id"] == team["id"]
        assert registration["roster_player_count"] == 13
        assert registration["roster_staff_count"] == 3
        assert registration["local_team_flag"] is False
        assert registration["required_rooms_registered"] == 6
        assert registration["required_room_nights"] == 18
        assert registration["minimum_rooms_for_compliance"] == 4
        assert registration["exempt_rooms_granted"] == 0
        assert registration["effective_required_rooms"] == 4
        assert registration["committed_rooms"] == 0
        assert registration["status"] == "PENDING_HOUSING"
        assert is_iso8601_timestamp(registration["compliance_evaluated_at"])
        assert registration["compliance_evaluated_at"].startswith("2026-08-01T00:00:00")
        assertions.assert_versioned_record(registration, 1)


class TestBookingSystemFields:
    """Which of a booking's fields the server mints for itself."""

    def test_a_new_booking_is_stamped_from_the_clock_with_nothing_cancelled_yet(
        self, api
    ):
        """Four rooms over three nights come back as twelve projected room
        nights on a first-version record timestamped at the logical instant,
        with every penalty figure at zero and no cancellation recorded.

        PRD §2.4: "Every persisted resource carries a server-minted `id`, which
        is a UUID string with no type prefix and no client-supplied component."

        PRD §2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`."

        PRD §3.4: "A booking that clears all of that is created with
        `booking_status` `DRAFT` and `rebate_status` `NOT_DUE`."

        PRD §3.4: "The server computes `nights` as the whole days from
        `check_in_date` up to but not including `check_out_date`, and
        `projected_room_nights` as `rooms_requested` multiplied by `nights` — the
        pre-stay estimate that cancellation penalties are assessed against."

        PRD §3.4: "It initialises `actualized_room_nights`,
        `rebate_accrued_cents`, `penalty_cents`, `penalty_room_nights` and
        `penalty_credit_cents` all to 0, leaves `cancellation_reason` and
        `cancelled_at` null, and increments the parent registration's `version`
        by 1."

        Design: Corner/entities/booking_system_fields_minted_by_server
        """
        fx.set_clock(api, CLOCK_STARTUP_UTC)
        env = fx.registered_team_env(api)
        registration = env.refresh_registration()

        booking = validate_success(
            api.create_booking(
                f.booking_payload(
                    registration["id"], env.block_id, registration["version"]
                ),
                HM,
            ),
            201,
        )

        assert is_valid_uuid(booking["id"])
        assert booking["created_at"] == CLOCK_START_STAMP
        assert booking["updated_at"] == CLOCK_START_STAMP
        assert booking["version"] == 1
        assert booking["registration_id"] == registration["id"]
        assert booking["room_block_id"] == env.block_id
        assert booking["rooms_requested"] == 4
        assert booking["nights"] == 3
        assert booking["projected_room_nights"] == 12
        assert booking["booking_status"] == "DRAFT"
        assert booking["rebate_status"] == "NOT_DUE"
        assert booking["actualized_room_nights"] == 0
        assert booking["rebate_accrued_cents"] == 0
        assert booking["penalty_cents"] == 0
        assert booking["penalty_room_nights"] == 0
        assert booking["penalty_credit_cents"] == 0
        assert booking["cancellation_reason"] is None
        assert booking["cancelled_at"] is None


class TestRebateModelVocabulary:
    """A contract's rebate structure is drawn from a closed vocabulary."""

    def test_an_undeclared_rebate_model_is_a_schema_failure(self, api):
        """A rebate model outside the three declared structures is refused as
        malformed input, ahead of the later rule that checks the rebate
        parameters against the model.

        PRD §3.2: "The `rebate_model` selects one of three rebate structures, and
        the parameter fields must match the choice exactly."

        PRD §2.6: "Requests are also checked against the endpoint's input schema:
        required fields must be present, unknown fields are refused, enum-typed
        fields must carry a declared member, integer counts must respect their
        declared non-negativity, dates and datetimes must be well-formed ISO 8601
        values, and pagination parameters must fall in range."

        PRD §2.11: "Checks are evaluated in the fixed order below, and the first
        failing check produces the response; later checks are not evaluated and
        cannot mask an earlier one."

        Design: Corner/entities/hotel_contract_invalid_rebate_model_enum_rejected
        """
        tournament = fx.create_tournament(api)
        hotel = fx.create_hotel(api)

        response = api.create_hotel_contract(
            f.hotel_contract_payload(
                tournament["id"],
                hotel["id"],
                rebate_model="MYSTERY_MODEL",
                rebate_flat_cents_per_room_night=None,
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )


class TestRoomingListEntryShape:
    """Manifest rows are replaced wholesale and carry no version."""

    def test_resubmitting_a_manifest_replaces_every_row_rather_than_editing_it(
        self, api
    ):
        """A second manifest of four rooms at three occupants each leaves exactly
        four rows behind, carrying the new counts, with the booking still at
        rooming-list-submitted.

        PRD §3.4: "A further submission while the booking is already
        `ROOMING_LIST_SUBMITTED` is a self-loop: the booking stays in
        `ROOMING_LIST_SUBMITTED`, every existing entry for that booking is
        deleted, and a fresh row is created for each submitted element."

        PRD §3.4: "Rooming lists may be re-collected any number of times before
        confirmation."

        PRD §3.4: "Each stored `RoomingListEntry` records the `booking_id` it
        belongs to."

        Design: Corner/entities/rooming_list_entries_are_immutable_and_versionless
        """
        env = fx.rooming_list_env(api)

        booking = validate_success(
            api.submit_rooming_list(
                env.booking_id,
                f.rooming_list_payload(
                    entries=[
                        f.rooming_list_entry(index + 1, occupant_count=3)
                        for index in range(4)
                    ]
                ),
                HM,
            )
        )

        assert booking["booking_status"] == "ROOMING_LIST_SUBMITTED"
        rows, meta = validate_paginated(api.list_rooming_list(env.booking_id, HM))
        assert meta["total_count"] == 4
        by_index = sorted(rows, key=lambda row: row["room_index"])
        assert [row["room_index"] for row in by_index] == [1, 2, 3, 4]
        assert [row["occupant_count"] for row in by_index] == [3, 3, 3, 3]
        assert [row["minor_occupant_count"] for row in by_index] == [0, 0, 0, 0]
        assert all(row["booking_id"] == env.booking_id for row in by_index)

    def test_manifest_rows_carry_no_version_and_no_update_timestamp(self, api):
        """Each stored manifest row is a record of a moment: an identifier and a
        creation instant, and nothing to version.

        PRD §2.4: "Two resources are append-only records of a moment rather than
        mutable rows, and they carry only `id` and `created_at`."

        PRD §2.4: "Neither `updated_at` nor `version` exists on a
        `RoomingListEntry`, and neither exists on an `ActualizationReport`."

        PRD §2.4: "A rooming list is revised by replacing its entries wholesale
        rather than by editing them, and an actualization figure is restated by
        filing a further report rather than by editing the prior one, so there is
        nothing on either record to version."

        Design: Corner/entities/rooming_list_entries_are_immutable_and_versionless
        """
        env = fx.rooming_list_env(api)

        rows, meta = validate_paginated(api.list_rooming_list(env.booking_id, HM))

        assert meta["total_count"] == 4
        for row in rows:
            assertions.assert_append_only_record(row)


class TestActualizationLedger:
    """Hotel reports accumulate; the booking reads only the latest one."""

    def test_both_reports_survive_and_number_themselves_in_filing_order(self, api):
        """A corrected folio does not overwrite the first one: two rows remain,
        numbered one and two, each an append-only record of its moment.

        PRD §3.7: "Each accepted report is an immutable record carrying the
        `booking_id` it describes, its `reported_room_nights`, its optional
        `report_note`, and a server-assigned `sequence_no` equal to one more than
        the number of reports already filed against that booking — so the first
        report is number 1 and numbering rises monotonically per booking."

        PRD §2.3: "The one documented exception is the list of actualization
        reports for a booking, which is ordered by `sequence_no` ascending;
        because sequence numbers are assigned in creation order, the two
        orderings coincide."

        PRD §2.4: "Two resources are append-only records of a moment rather than
        mutable rows, and they carry only `id` and `created_at`."

        Design: Corner/entities/actualization_reports_form_append_only_ledger
        """
        env = fx.checked_out_booking_env(api, reported_room_nights=12)

        report = validate_success(
            api.create_actualization(
                env.booking_id,
                f.actualization_payload(15, report_note="corrected folio"),
                env.hotel_headers,
            ),
            201,
        )

        assert report["sequence_no"] == 2
        assert report["reported_room_nights"] == 15
        assert report["booking_id"] == env.booking_id
        assertions.assert_append_only_record(report)
        rows, meta = validate_paginated(
            api.list_actualization_reports(env.booking_id, HM)
        )
        assert meta["total_count"] == 2
        assert [row["sequence_no"] for row in rows] == [1, 2]
        assert [row["reported_room_nights"] for row in rows] == [12, 15]
        for row in rows:
            assertions.assert_append_only_record(row)

    def test_the_later_report_restates_the_room_nights_rather_than_adding_to_them(
        self, api
    ):
        """Fifteen reported nights replace the twelve first filed — not
        twenty-seven — and the flat rebate and the block's own consumption both
        follow the restated figure.

        PRD §3.7: "The booking's `actualized_room_nights` is always taken from
        the report with the **greatest** `sequence_no`, and is 0 while no report
        exists."

        PRD §3.7: "A later report therefore *restates* the figure rather than
        adding to it."

        PRD §3.7: "Under `PER_ROOM_NIGHT_FLAT`, the line is
        `actualized_room_nights` multiplied by the contract's
        `rebate_flat_cents_per_room_night`."

        PRD §3.7: "The block's own `actualized_room_nights` is then re-derived as
        the sum of `actualized_room_nights` over the bookings on that block whose
        `booking_status` is `CHECKED_OUT`."

        Design: Corner/entities/actualization_reports_form_append_only_ledger
        """
        env = fx.checked_out_booking_env(api, reported_room_nights=12)
        assert env.booking["actualized_room_nights"] == 12

        validate_success(
            api.create_actualization(
                env.booking_id,
                f.actualization_payload(15, report_note="corrected folio"),
                env.hotel_headers,
            ),
            201,
        )

        booking = env.refresh_booking()
        assert booking["actualized_room_nights"] == 15
        assert booking["rebate_accrued_cents"] == 13500
        assert booking["booking_status"] == "CHECKED_OUT"
        assert env.refresh_block()["actualized_room_nights"] == 15


class TestReferenceResolution:
    """Identifiers that resolve to nothing, in the path and in the body."""

    def test_reading_a_booking_that_does_not_exist_is_a_booking_not_found(self, api):
        """A well-formed identifier matching no booking is answered with the
        not-found identifier for bookings, not with an empty success envelope.

        PRD §2.6: "The 404 error identifier is chosen by the type of resource
        that was not found: `ERR_TOURNAMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_ROOM_BLOCK_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
        `ERR_BOOKING_NOT_FOUND`, `ERR_EXCEPTION_REQUEST_NOT_FOUND`,
        `ERR_COMPLAINT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` or
        `ERR_DISTRIBUTION_NOT_FOUND`."

        PRD §2.11: "Every path-templated resource exists, resolved left to right
        — otherwise the not-found identifier for that resource type."

        Design: Corner/entities/booking_get_with_unknown_id_returns_not_found
        """
        response = api.get_booking(NON_EXISTENT_UUID, HM)

        validate_error(
            response, ApiErrorId.ERR_BOOKING_NOT_FOUND.value, expected_status=404
        )

    def test_holding_a_block_under_a_contract_that_does_not_exist_is_refused(
        self, api
    ):
        """A block whose only parent reference dangles is refused on the missing
        contract, before any window or capacity rule gets a say.

        PRD §2.6: "Each reference must resolve to an existing row, and the 404
        identifier is again chosen by referenced type, drawn from
        `ERR_TOURNAMENT_NOT_FOUND`, `ERR_HOTEL_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_ROOM_BLOCK_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
        `ERR_EXCEPTION_REQUEST_NOT_FOUND` and `ERR_INVOICE_NOT_FOUND`."

        PRD §2.6: "Body-reference resolution is performed on `POST
        /housing/hotel-contracts`, `POST /housing/room-blocks`, `POST
        /housing/team-registrations`, `POST /housing/bookings`, `POST
        /housing/exception-requests`, `POST /housing/complaints`, `POST
        /housing/rebate-invoices` and `POST /housing/revenue-distributions`."

        PRD §2.11: "Checks are evaluated in the fixed order below, and the first
        failing check produces the response; later checks are not evaluated and
        cannot mask an earlier one."

        Design: Corner/entities/room_block_create_with_unknown_contract_returns_not_found
        """
        response = api.create_room_block(
            f.room_block_payload(NON_EXISTENT_UUID), HM
        )

        validate_error(
            response, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, expected_status=404
        )


class TestComplaintCrossAggregateLinks:
    """One complaint row joining an event, a team, an exemption and a stay."""

    def test_a_complaint_can_name_a_registration_an_exemption_and_a_booking_at_once(
        self, api
    ):
        """All three optional subjects resolve on the same filing, and the new
        complaint opens untriaged with no remedy and no adjudication trail.

        PRD §3.9: "Up to three optional subject references may accompany it: a
        `registration_id` naming the complaining registration (null for
        hotel-side complaints), a `cited_exception_request_id` naming the
        exemption decision the complaint disputes, and an `affected_booking_id`
        naming the booking whose penalty a granted remedy would credit."

        PRD §3.9: "A new complaint opens at `status` `FILED` with `route` null,
        `remedy_type` `NONE`, `remedy_amount_cents` 0, `remedy_credit_cents` 0
        and both `triaged_by_user_id` and `adjudicated_by_user_id` null."

        Design: Corner/entities/graph_topology_complaint_resolves_three_cross_aggregate_links
        """
        env = _complaint_subjects_env(api)

        complaint = validate_success(
            api.create_complaint(
                f.complaint_payload(
                    env.tournament_id,
                    category=ComplaintCategory.POLICY_FAIRNESS.value,
                    narrative="the housing policy is applied unevenly across visiting teams",
                    registration_id=env.registration_id,
                    cited_exception_request_id=env.exception_request["id"],
                    affected_booking_id=env.booking_id,
                ),
                HM,
            ),
            201,
        )

        assert complaint["tournament_id"] == env.tournament_id
        assert complaint["registration_id"] == env.registration_id
        assert complaint["cited_exception_request_id"] == env.exception_request["id"]
        assert complaint["affected_booking_id"] == env.booking_id
        assert complaint["category"] == "POLICY_FAIRNESS"
        assert complaint["status"] == "FILED"
        assert complaint["route"] is None
        assert complaint["remedy_type"] == "NONE"
        assert complaint["remedy_amount_cents"] == 0
        assert complaint["remedy_credit_cents"] == 0
        assert complaint["triaged_by_user_id"] is None
        assert complaint["adjudicated_by_user_id"] is None
        assertions.assert_versioned_record(complaint, 1)

    def test_filtering_complaints_by_the_affected_booking_alone_finds_the_row(
        self, api
    ):
        """Each optional subject is queryable in its own right: naming only the
        affected booking returns the complaint that cites it.

        PRD §2.3: "List endpoints additionally accept the domain filters named in
        their §4 descriptions; a filter that is supplied narrows the result set
        by exact match on the named field, and filters combine conjunctively."

        PRD §2.3: "For every list response, the `meta` block carries `limit`,
        `offset`, `total_count` and `has_more`, where `total_count` is the number
        of rows matching the filters before pagination and `has_more` indicates
        whether rows remain beyond the current page."

        Design: Corner/entities/graph_topology_complaint_resolves_three_cross_aggregate_links
        """
        env = _complaint_subjects_env(api)
        complaint = fx.add_complaint(
            env,
            category=ComplaintCategory.POLICY_FAIRNESS.value,
            narrative="the housing policy is applied unevenly across visiting teams",
            registration_id=env.registration_id,
            cited_exception_request_id=env.exception_request["id"],
            affected_booking_id=env.booking_id,
        )

        rows, meta = validate_paginated(
            api.list_complaints(HM, params={"affected_booking_id": env.booking_id})
        )

        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == complaint["id"]
        assert rows[0]["affected_booking_id"] == env.booking_id
