"""Resource creation, retrieval and collection behaviour.

Covers the opening shape of a draft cycle, a club registration row and a
prospect's parallel dimensions, the declared defaults of facility inventory,
the server-computed booking interval, request-shape and reference-integrity
rejections, and the two collection views that publish a filtered, paginated
page of clubs and minted draft picks.
"""

import pytest

from test_helpers import (
    ADMIN,
    CYCLE_SETUP_NOW,
    ERR_INVALID_REQUEST,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND,
    NON_EXISTENT_UUID,
    assert_chart_points,
    assert_cents_equal,
    assert_common_fields,
    assert_pagination_meta,
    assert_prospect_dimensions,
    build_combine_week,
    build_cycle_with_clubs,
    club_payload,
    combine_booking_payload,
    create_station,
    draft_cycle_payload,
    medical_station_payload,
    prospect_payload,
    read_cycle,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCycleAndClubRegistration:
    """The container cycle and the clubs that seed its draft order."""

    def test_new_cycle_opens_at_setup_with_the_full_seven_round_default(self, api):
        """A cycle created without the two optional draft inputs opens at SETUP.

        "A newly created cycle has `status` `SETUP`, `posture` `OPEN`, `club_count` zero, and `lottery_completed` false."
        "`rounds_count` declares how many rounds the cycle awards, an integer from 1 through 7 inclusive that defaults to 7."
        "`compressed_final_day` is a boolean that defaults to false and, when true, shortens the clock in the later rounds as §3.7 describes."
        "`order_finalized_at` is null until the draft order is minted; `udfa_window_close_at` is likewise null until then, and `lottery_slot_club_ids` is an empty list until the lottery runs."

        Design: Corner/entities/draft_cycle_created_with_setup_defaults
        """
        set_clock(api, CYCLE_SETUP_NOW)

        cycle = validate_success(
            api.create_draft_cycle(draft_cycle_payload(), ADMIN),
            expected_status=201,
        )

        assert_common_fields(cycle, expected_version=1)
        assert cycle["season_year"] == 2027
        assert cycle["status"] == "SETUP"
        assert cycle["posture"] == "OPEN"
        assert cycle["rounds_count"] == 7
        assert cycle["compressed_final_day"] is False
        assert cycle["club_count"] == 0
        assert cycle["lottery_completed"] is False
        assert cycle["order_finalized_at"] is None
        assert cycle["udfa_window_close_at"] is None
        assert cycle["pick_inventory_count"] == 0
        assert_chart_points(cycle["pick_inventory_chart_points"], 0.0)

    def test_registered_club_reads_back_its_seeding_inputs_and_opening_ledger(
        self, api
    ):
        """A freshly registered club echoes its inputs with two timeouts banked.

        "Registering a club recomputes the cycle's `club_count` and seeds the club's `timeouts_remaining` at two selection-clock timeouts for the whole cycle."
        "`rookie_pool_remaining_cents` is `rookie_pool_total_cents` minus the sum of `first_year_cap_charge_cents` over that club's contracts whose `status` is `SIGNED`; contracts in `OFFERED`, `VOIDED` or `LAPSED` are excluded from that sum entirely."

        Design: Corner/entities/club_retrieval_returns_stored_registration_row
        """
        state = build_cycle_with_clubs(api, club_codes=["ELM"])
        elm = state["clubs"]["ELM"]

        club = validate_success(api.get_club(elm["id"], ADMIN))

        assert_common_fields(club, expected_version=1)
        assert club["draft_cycle_id"] == state["cycle"]["id"]
        assert club["club_code"] == "ELM"
        assert club["market_name"] == "Elmwood"
        assert club["prior_season_win_pct"] == pytest.approx(0.500, abs=0.0005)
        assert club["lottery_combinations"] == 75
        assert club["registration_status"] == "REGISTERED"
        assert club["playoff_qualified"] is False
        assert club["playoff_exit_round"] == 0
        assert club["timeouts_remaining"] == 2
        assert_cents_equal(club["rookie_pool_remaining_cents"], 896721432)

        cycle = read_cycle(api, state["cycle"]["id"])
        assert cycle["club_count"] == 1

    def test_club_registration_without_a_market_name_is_rejected(self, api):
        """market_name has no default, so omitting it registers nothing.

        "A club joins a cycle when the admin registers it with a payload carrying the cycle's `draft_cycle_id`, a `club_code` of exactly three uppercase letters that must be unique among the clubs of that cycle (a repeat is refused with `ERR_CLUB_CODE_DUPLICATE`), a human-readable `market_name`, and the prior-season seeding inputs that will drive the draft order: `prior_season_win_pct` and `strength_of_schedule`, each a three-decimal share from 0.000 through 1.000 inclusive, and `head_to_head_rank`, the league-published integer rank of 1 or greater."
        "Request shape — body and query parameters parse; every required field is present; every enum value is a member of its declared set; every number lies inside its declared range; `ends_at` is strictly after `starts_at`; `limit` is between 1 and 100 inclusive; `offset` is zero or greater. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

        Design: Corner/entities/club_creation_without_market_name_is_rejected
        """
        set_clock(api, CYCLE_SETUP_NOW)
        cycle = validate_success(
            api.create_draft_cycle(draft_cycle_payload(rounds_count=2), ADMIN),
            expected_status=201,
        )

        payload = club_payload(cycle["id"], "ELM")
        payload.pop("market_name")

        validate_error(api.create_club(payload, ADMIN), ERR_INVALID_REQUEST)

        assert read_cycle(api, cycle["id"])["club_count"] == 0

    def test_club_registration_against_an_unknown_cycle_reports_a_bad_reference(
        self, api
    ):
        """A body foreign key that resolves to nothing is a referenced-entity miss.

        "Foreign keys supplied in a request body are resolved after all path parameters, in the order the endpoint declares its input fields, and an unresolvable one produces `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/club_creation_with_unknown_cycle_returns_referenced_not_found
        """
        set_clock(api, CYCLE_SETUP_NOW)
        cycle = validate_success(
            api.create_draft_cycle(draft_cycle_payload(rounds_count=2), ADMIN),
            expected_status=201,
        )

        validate_error(
            api.create_club(club_payload(NON_EXISTENT_UUID, "ELM"), ADMIN),
            ERR_REFERENCED_ENTITY_NOT_FOUND,
        )

        assert read_cycle(api, cycle["id"])["club_count"] == 0


class TestCycleClubListing:
    """The cycle's own club collection and its pagination envelope."""

    def test_first_page_of_the_club_list_reports_the_unpaginated_total(self, api):
        """Two of three registered clubs come back with the total and has_more.

        "The endpoints that declare their own order are: the cycle's club list, ordered by `draft_order_index` ascending and then `created_at` ascending; the combine-booking list, ordered by `starts_at` ascending and then `created_at` ascending; the draft-pick list, ordered by `overall_number` ascending; and the compensatory-claim list, ordered by `claim_score` descending and then `created_at` ascending."
        "`total_count` reports the number of rows matching the filters before pagination is applied, and `has_more` is true when rows remain beyond the current page."

        Design: Corner/entities/cycle_club_listing_paginates_with_total_count
        """
        state = build_cycle_with_clubs(api, club_codes=["ELM", "HAR", "BRN"])

        rows, meta = validate_paginated(
            api.list_cycle_clubs(
                state["cycle"]["id"], ADMIN, {"limit": 2, "offset": 0}
            )
        )

        assert_pagination_meta(
            meta,
            expected_total=3,
            expected_limit=2,
            expected_offset=0,
            expected_has_more=True,
        )
        assert len(rows) == 2
        assert rows[0]["id"] == state["clubs"]["ELM"]["id"]
        assert rows[1]["id"] == state["clubs"]["HAR"]["id"]
        assert rows[0]["club_code"] == "ELM"
        assert rows[1]["club_code"] == "HAR"

    def test_last_page_of_the_club_list_closes_has_more(self, api):
        """Skipping the first two clubs leaves the third and clears has_more.

        "`total_count` reports the number of rows matching the filters before pagination is applied, and `has_more` is true when rows remain beyond the current page."

        Design: Corner/entities/cycle_club_listing_paginates_with_total_count
        """
        state = build_cycle_with_clubs(api, club_codes=["ELM", "HAR", "BRN"])

        rows, meta = validate_paginated(
            api.list_cycle_clubs(
                state["cycle"]["id"], ADMIN, {"limit": 2, "offset": 2}
            )
        )

        assert_pagination_meta(
            meta,
            expected_total=3,
            expected_limit=2,
            expected_offset=2,
            expected_has_more=False,
        )
        assert len(rows) == 1
        assert rows[0]["id"] == state["clubs"]["BRN"]["id"]
        assert rows[0]["club_code"] == "BRN"


class TestProspectRegistration:
    """A prospect's opening dimensions and its input validation."""

    def test_new_prospect_opens_every_dimension_at_its_declared_initial_value(
        self, api, declaration_open
    ):
        """Registration seeds all six dimensions plus both relief flags.

        "Registration sets all five of the prospect's parallel state dimensions to their initial values — `declaration_status` `UNDECLARED`, `eligibility_status` `UNREVIEWED`, `invitation_status` `NOT_INVITED`, `consent_status` `NONE`, `signing_status` `UNSIGNED` — along with `medical_clearance_status` `PENDING`, `declared_at` null, `late_declaration_waived` false, `early_entry_waived` false, `consent_scope` null, `consent_expires_at` null and `drafted_pick_overall_number` 0."

        Design: Corner/entities/prospect_created_with_all_parallel_dimension_defaults
        """
        cycle = declaration_open["cycle"]

        prospect = validate_success(
            api.create_prospect(prospect_payload(cycle["id"]), ADMIN),
            expected_status=201,
        )

        assert_common_fields(prospect, expected_version=1)
        assert_prospect_dimensions(
            prospect,
            declaration_status="UNDECLARED",
            eligibility_status="UNREVIEWED",
            invitation_status="NOT_INVITED",
            consent_status="NONE",
            medical_clearance_status="PENDING",
            signing_status="UNSIGNED",
        )
        assert prospect["declared_at"] is None
        assert prospect["consent_scope"] is None
        assert prospect["consent_expires_at"] is None
        assert prospect["drafted_pick_overall_number"] == 0
        assert prospect["late_declaration_waived"] is False
        assert prospect["early_entry_waived"] is False

    def test_client_supplied_system_fields_are_discarded_on_registration(
        self, api, declaration_open
    ):
        """The server mints identity and audit values regardless of the body.

        "`id` — a server-minted UUID, with no type prefix and no client-supplied component."
        "`version` — an integer that starts at 1 on creation and increases by exactly one on every mutation of the row."

        Design: Corner/entities/prospect_create_with_extra_field_system_input_ignored
        """
        cycle = declaration_open["cycle"]
        submitted_id = "11111111-1111-4111-8111-111111111111"

        prospect = validate_success(
            api.create_prospect(
                prospect_payload(
                    cycle["id"],
                    full_name="Brooks Hale",
                    position_group="WR",
                    school_code="STH",
                    scouting_grade=88.00,
                    position_group_scarcity_rank=3,
                    id=submitted_id,
                    created_at="2020-01-01T00:00:00.000Z",
                    version=99,
                ),
                ADMIN,
            ),
            expected_status=201,
        )

        assert_common_fields(prospect, expected_version=1)
        assert prospect["id"] != submitted_id
        assert prospect["created_at"] == CYCLE_SETUP_NOW
        assert prospect["full_name"] == "Brooks Hale"
        assert prospect["declaration_status"] == "UNDECLARED"

    def test_position_group_outside_the_declared_enum_is_rejected(
        self, api, declaration_open
    ):
        """A position group the league does not field is a malformed request.

        "Prospects are registered by the admin too, with `draft_cycle_id`, the player's legal `full_name`, a `position_group` drawn from `QB`, `RB`, `WR`, `TE`, `OL`, `DL`, `LB`, `DB` and `ST`, an amateur institution `school_code`, `seasons_played` as an integer from 0 through 6 inclusive, a `scouting_grade` from 0.00 through 100.00 inclusive at two decimal places, and `position_group_scarcity_rank`, the league's ascending scarcity rank for that position group, an integer of 1 or greater."
        "Request shape — body and query parameters parse; every required field is present; every enum value is a member of its declared set; every number lies inside its declared range; `ends_at` is strictly after `starts_at`; `limit` is between 1 and 100 inclusive; `offset` is zero or greater. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

        Design: Corner/entities/prospect_invalid_enum_position_group_rejected
        """
        cycle = declaration_open["cycle"]

        validate_error(
            api.create_prospect(
                prospect_payload(
                    cycle["id"],
                    full_name="Cade Rios",
                    position_group="GOALIE",
                    school_code="EST",
                    seasons_played=3,
                    scouting_grade=85.00,
                    position_group_scarcity_rank=2,
                ),
                ADMIN,
            ),
            ERR_INVALID_REQUEST,
        )

        assert read_cycle(api, cycle["id"])["status"] == "DECLARATION_OPEN"

    def test_unknown_prospect_id_is_a_missing_path_resource(self, api, cycle_setup):
        """A well-formed UUID matching no prospect row is a 404, never an empty read.

        "The first identifier that does not resolve produces `ERR_RESOURCE_NOT_FOUND` (HTTP 404) immediately, and no identifier to its right is examined."

        Design: Corner/entities/prospect_fetch_with_unknown_id_returns_not_found
        """
        error = validate_error(
            api.get_prospect(NON_EXISTENT_UUID, ADMIN), ERR_RESOURCE_NOT_FOUND
        )

        assert error["message"].strip()


class TestFacilityAndBookingCreation:
    """League-wide facility inventory and the intervals booked against it."""

    def test_medical_station_takes_the_declared_buffer_and_status_defaults(
        self, api
    ):
        """A station registered with only its code and exam type buffers 15 minutes.

        "A **medical station** carries a globally unique `station_code`, an `exam_type` of `ORTHO`, `CARDIAC`, `IMAGING` or `NEURO`, a `turnaround_buffer_minutes` from 0 through 60 inclusive that defaults to 15 and represents the sanitation and turnaround time that must separate consecutive examinations, and a `status` of `AVAILABLE` or `OFFLINE` that defaults to `AVAILABLE`."

        Design: Corner/entities/medical_station_defaults_applied_when_optionals_omitted
        """
        set_clock(api, CYCLE_SETUP_NOW)

        station = validate_success(
            api.create_medical_station(
                medical_station_payload("ST-NEURO-1", "NEURO"), ADMIN
            ),
            expected_status=201,
        )

        assert_common_fields(station, expected_version=1)
        assert station["station_code"] == "ST-NEURO-1"
        assert station["exam_type"] == "NEURO"
        assert station["turnaround_buffer_minutes"] == 15
        assert station["status"] == "AVAILABLE"

    def test_booking_duration_is_derived_from_the_half_open_interval(self, api):
        """A 09:00 to 09:45 exam reports forty-five minutes and opens SCHEDULED.

        "The server computes `duration_minutes` as the whole number of minutes between `starts_at` and `ends_at`."
        "A booking is created in `SCHEDULED` and is moved by the admin with a status `action`."

        Design: Corner/entities/booking_duration_minutes_computed_from_the_interval
        """
        state = build_combine_week(api)
        station = create_station(api)

        booking = validate_success(
            api.create_combine_booking(
                combine_booking_payload(
                    state["prospect"]["id"],
                    "MEDICAL_EXAM",
                    "2027-02-23T09:00:00.000Z",
                    "2027-02-23T09:45:00.000Z",
                    medical_station_id=station["id"],
                ),
                ADMIN,
            ),
            expected_status=201,
        )

        assert_common_fields(booking, expected_version=1)
        assert booking["duration_minutes"] == 45
        assert booking["status"] == "SCHEDULED"
        assert booking["prospect_id"] == state["prospect"]["id"]
        assert booking["medical_station_id"] == station["id"]
        assert booking["interview_room_id"] is None


class TestDraftPickCollection:
    """The minted pick ledger read back through its filtered collection."""

    def test_pick_list_filtered_by_owning_club_returns_only_that_club_ledger(
        self, api, order_final
    ):
        """Filtering on the current owner returns ELM's two picks in overall order.

        "Picks are listable with optional `draft_cycle_id`, `owning_club_id`, `original_club_id`, `selected_prospect_id`, `round_number` and `status` filters, plus `limit` and `offset`."
        "Every pick carries a **chart value** minted at finalize time: `chart_value_points` is the round's chart base multiplied by a decay factor of 0.94 raised to the power of `pick_in_round` minus one, rounded half up to one decimal place."

        Design: Corner/entities/draft_pick_listing_filtered_by_owning_club_fk
        """
        cycle = order_final["cycle"]
        elm = order_final["clubs"]["ELM"]

        rows, meta = validate_paginated(
            api.list_draft_picks(
                ADMIN,
                {
                    "draft_cycle_id": cycle["id"],
                    "owning_club_id": elm["id"],
                    "limit": 10,
                },
            )
        )

        assert_pagination_meta(meta, expected_total=2, expected_has_more=False)
        assert len(rows) == 2
        assert [row["overall_number"] for row in rows] == [1, 3]
        assert all(row["owning_club_id"] == elm["id"] for row in rows)
        assert_chart_points(rows[0]["chart_value_points"], 1000.0)
        assert_chart_points(rows[1]["chart_value_points"], 420.0)
