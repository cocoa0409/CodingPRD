"""Entity surfaces: declared defaults, echoed rows, listings and not-found codes."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CURATOR_HEADERS,
    NON_EXISTENT_UUID,
    OMIT,
    assert_pagination_meta,
    build_election_world,
    create_candidacy_payload,
    create_candidate_payload,
    create_elector_payload,
    create_induction_cycle_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    read_cycle,
    setup_eligibility_rule,
    setup_voter_bloc,
    validate_error,
    validate_paginated,
    validate_success,
)

PAGE_CANDIDATES = [
    {
        "full_name": "Page One",
        "category": "PLAYER",
        "retirement_year": 2018,
        "career_seasons": 15,
        "career_metric_value": 3000,
    },
    {
        "full_name": "Page Two",
        "category": "PLAYER",
        "retirement_year": 2017,
        "career_seasons": 14,
        "career_metric_value": 2800,
    },
    {
        "full_name": "Page Three",
        "category": "COACH",
        "retirement_year": 2016,
        "career_seasons": 20,
        "career_metric_value": 1800,
    },
]


class TestInductionCycleCreation:
    """What POST /induction-cycles writes when it is fully specified, and when it is not."""

    def test_a_fully_specified_cycle_echoes_every_declared_input(self, api):
        """An election begins with an `InductionCycle`, which an `ElectionAdministrator` opens by
        supplying the `cycle_year` the cycle elects for — a whole year no earlier than 1900 and no
        later than 2200 — together with the `sport_code` identifying the hall of fame's sport, for
        example `BASEBALL`.

        Design: Corner/entities/cycle_create_returns_declared_defaults
        """
        cycle = validate_success(
            api.create_induction_cycle(
                create_induction_cycle_payload(
                    cycle_year=2026,
                    sport_code="BASEBALL",
                    max_inductees=5,
                    travel_budget_cents=1_000_000,
                    escort_pool_size=2,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert cycle["cycle_year"] == 2026
        assert cycle["sport_code"] == "BASEBALL"
        assert cycle["max_inductees"] == 5
        assert cycle["travel_budget_cents"] == 1_000_000
        assert cycle["escort_pool_size"] == 2

    def test_a_new_cycle_starts_at_setup_with_every_counter_at_zero(self, api):
        """A newly opened cycle is in `SETUP`, with `current_round` at 0, `austerity_tier` at
        `FULL`, `ceremony_date` and `ceremony_venue` unset, and all seven of its derived counters
        at zero: `nomination_count`, `advanced_candidacy_count`, `special_election_used`,
        `credentialed_roster_count`, `travel_committed_cents`, `induction_count` and
        `ceremony_ready_count`.

        Design: Corner/entities/cycle_create_returns_declared_defaults
        """
        cycle = validate_success(
            api.create_induction_cycle(create_induction_cycle_payload(), ADMIN_HEADERS), 201
        )
        assert cycle["status"] == "SETUP"
        assert cycle["current_round"] == 0
        assert cycle["austerity_tier"] == "FULL"
        assert cycle["ceremony_date"] is None
        assert cycle["ceremony_venue"] is None
        for counter in (
            "nomination_count",
            "advanced_candidacy_count",
            "special_election_used",
            "credentialed_roster_count",
            "travel_committed_cents",
            "induction_count",
            "ceremony_ready_count",
        ):
            assert cycle[counter] == 0, f"{counter} must start at 0"
        assert cycle["version"] == 1

    def test_the_optional_figures_fall_back_to_their_declared_defaults(self, api):
        """Two optional figures may be supplied at this point and both may be revised later during
        ceremony planning: `travel_budget_cents`, which defaults to 0, and `escort_pool_size`, the
        number of ceremony escorts available concurrently for posthumous delegations, which also
        defaults to 0.

        Design: Corner/entities/cycle_create_omitting_optionals_applies_declared_defaults
        """
        cycle = validate_success(
            api.create_induction_cycle(
                create_induction_cycle_payload(
                    max_inductees=OMIT, travel_budget_cents=OMIT, escort_pool_size=OMIT
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert cycle["travel_budget_cents"] == 0
        assert cycle["escort_pool_size"] == 0
        assert cycle["austerity_tier"] == "FULL"
        assert cycle["version"] == 1

    def test_the_inductee_cap_defaults_to_five_when_omitted(self, api):
        """A third optional figure, `max_inductees`, is the hard cap on how many candidacies this
        cycle may elect; it defaults to 5 and must be at least 1.

        Design: Corner/entities/cycle_create_omitting_optionals_applies_declared_defaults
        """
        cycle = validate_success(
            api.create_induction_cycle(
                create_induction_cycle_payload(
                    max_inductees=OMIT, travel_budget_cents=OMIT, escort_pool_size=OMIT
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert cycle["max_inductees"] == 5
        assert read_cycle(api, cycle["id"])["max_inductees"] == 5


class TestCandidateRegistration:
    """Reading a registered candidate back, and the fields the server owns."""

    def test_the_stored_row_echoes_every_registered_figure(self, api):
        """Registration takes the candidate's `full_name`, their `category`, the `retirement_year`
        in which their qualifying career ended (again between 1900 and 2200), the `career_seasons`
        they completed and their `career_metric_value`.

        Design: Corner/entities/candidate_read_returns_stored_row
        """
        created = validate_success(
            api.create_candidate(
                create_candidate_payload(
                    full_name="Read Back One",
                    category="PLAYER",
                    retirement_year=2018,
                    career_seasons=15,
                    career_metric_value=3000,
                    is_deceased=False,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        fetched = validate_success(api.get_candidate(created["id"], AUDITOR_HEADERS), 200)
        assert fetched["id"] == created["id"]
        assert fetched["full_name"] == "Read Back One"
        assert fetched["category"] == "PLAYER"
        assert fetched["retirement_year"] == 2018
        assert fetched["career_seasons"] == 15
        assert fetched["career_metric_value"] == 3000
        assert fetched["is_deceased"] is False
        assert fetched["hof_status"] == "NOT_INDUCTED"

    def test_the_server_mints_the_identity_and_the_election_outcome_fields(self, api):
        """A new candidate starts with `hof_status` at `NOT_INDUCTED`, `ballot_appearances_used` at
        0, `veterans_eligible_from_year` unset and `permanently_ineligible_reason` unset.

        Design: Corner/entities/candidate_system_fields_are_server_generated
        """
        candidate = validate_success(
            api.create_candidate(
                create_candidate_payload(
                    full_name="System Fields One",
                    category="COACH",
                    retirement_year=2015,
                    career_seasons=22,
                    career_metric_value=1900,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert candidate["hof_status"] == "NOT_INDUCTED"
        assert candidate["ballot_appearances_used"] == 0
        assert candidate["veterans_eligible_from_year"] is None
        assert candidate["permanently_ineligible_reason"] is None
        assert candidate["death_year"] is None

    def test_identity_timestamps_and_version_are_server_minted(self, api):
        """Every resource also carries `created_at`, an ISO 8601 UTC timestamp with exactly three
        fractional-second digits, recording the logical-clock instant at which the row was
        written. Most resources additionally carry `updated_at` (same format, refreshed on every
        mutation of the row) and `version`, an integer that starts at 1 when the row is created
        and increments by exactly 1 on every mutation of that row.

        Design: Corner/entities/candidate_system_fields_are_server_generated
        """
        candidate = validate_success(
            api.create_candidate(
                create_candidate_payload(full_name="System Fields Two"), ADMIN_HEADERS
            ),
            201,
        )
        assert is_valid_uuid(candidate["id"])
        assert is_iso8601_timestamp(candidate["created_at"])
        assert candidate["updated_at"] == candidate["created_at"]
        assert candidate["version"] == 1


class TestCandidateListing:
    """Paging and filtering the candidate collection."""

    @pytest.fixture
    def candidates(self, api):
        """Three registered candidates: two players and one coach."""
        return [
            validate_success(
                api.create_candidate(create_candidate_payload(**spec), ADMIN_HEADERS), 201
            )
            for spec in PAGE_CANDIDATES
        ]

    def test_the_two_pages_report_the_full_total_and_the_remaining_flag(self, api, candidates):
        """The `meta` object of a list response carries `limit` (the effective page size), `offset`
        (the effective starting position), `total_count` (the number of rows matching the filters,
        before paging) and `has_more` (true when rows remain beyond the current page).

        Design: Corner/entities/candidate_list_paginates_with_total_count_and_has_more
        """
        first_rows, first_meta = validate_paginated(
            api.list_candidates(ADMIN_HEADERS, {"limit": 2, "offset": 0})
        )
        assert len(first_rows) == 2
        assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)
        second_rows, second_meta = validate_paginated(
            api.list_candidates(ADMIN_HEADERS, {"limit": 2, "offset": 2})
        )
        assert len(second_rows) == 1
        assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
        assert first_rows[0]["id"] != second_rows[0]["id"]

    def test_a_category_filter_narrows_the_collection_and_the_total(self, api, candidates):
        """Candidates may be filtered by `category`, `hof_status` and `is_deceased`.

        Design: Corner/entities/candidate_list_paginates_with_total_count_and_has_more
        """
        rows, meta = validate_paginated(api.list_candidates(ADMIN_HEADERS, {"category": "COACH"}))
        assert len(rows) == 1
        assert rows[0]["id"] == candidates[2]["id"]
        assert_pagination_meta(meta, total_count=1, has_more=False)


class TestNotFoundCodesPerResourceFamily:
    """Each family reports its own 404, in the path and in a request body alike."""

    def test_an_unknown_cycle_id_reports_the_cycle_family_code(self, api):
        """Path identifiers are resolved before any state or business rule is evaluated, and each
        resource family reports its own not-found code: a missing induction cycle yields
        `ERR_CYCLE_NOT_FOUND`, a missing candidate `ERR_CANDIDATE_NOT_FOUND`, a missing candidacy
        `ERR_CANDIDACY_NOT_FOUND`, a missing elector `ERR_ELECTOR_NOT_FOUND`, a missing ballot,
        ballot slot or vote submission `ERR_BALLOT_NOT_FOUND`, a missing induction or travel grant
        `ERR_INDUCTION_NOT_FOUND`, a missing exhibit case or exhibit installation
        `ERR_EXHIBIT_NOT_FOUND`, and a missing voter bloc `ERR_BLOC_NOT_FOUND`.

        Design: Corner/entities/cycle_not_found_on_unknown_id
        """
        validate_error(
            api.get_induction_cycle(NON_EXISTENT_UUID, ADMIN_HEADERS),
            "ERR_CYCLE_NOT_FOUND",
            404,
        )

    def test_the_error_envelope_carries_an_id_and_a_message(self, api):
        """The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`.

        Design: Corner/entities/cycle_not_found_on_unknown_id
        """
        response = api.get_induction_cycle(NON_EXISTENT_UUID, ADMIN_HEADERS)
        assert response.status_code == 404
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_CYCLE_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}

    def test_candidate_and_candidacy_report_two_distinct_codes(self, api):
        """**Existence** — in this order: cycle, candidate, candidacy, elector, ballot family,
        induction family, exhibit family, eligibility rule, voter bloc.

        Design: Corner/entities/candidate_and_candidacy_not_found_on_unknown_ids
        """
        validate_error(
            api.get_candidate(NON_EXISTENT_UUID, ADMIN_HEADERS), "ERR_CANDIDATE_NOT_FOUND", 404
        )
        validate_error(
            api.get_candidacy(NON_EXISTENT_UUID, ADMIN_HEADERS), "ERR_CANDIDACY_NOT_FOUND", 404
        )

    def test_the_whole_ballot_family_shares_one_code(self, api):
        """Path identifiers are resolved before any state or business rule is evaluated, and each
        resource family reports its own not-found code: a missing induction cycle yields
        `ERR_CYCLE_NOT_FOUND`, a missing candidate `ERR_CANDIDATE_NOT_FOUND`, a missing candidacy
        `ERR_CANDIDACY_NOT_FOUND`, a missing elector `ERR_ELECTOR_NOT_FOUND`, a missing ballot,
        ballot slot or vote submission `ERR_BALLOT_NOT_FOUND`, a missing induction or travel grant
        `ERR_INDUCTION_NOT_FOUND`, a missing exhibit case or exhibit installation
        `ERR_EXHIBIT_NOT_FOUND`, and a missing voter bloc `ERR_BLOC_NOT_FOUND`.

        Design: Corner/entities/elector_and_ballot_not_found_on_unknown_ids
        """
        validate_error(
            api.get_elector(NON_EXISTENT_UUID, ADMIN_HEADERS), "ERR_ELECTOR_NOT_FOUND", 404
        )
        validate_error(
            api.get_ballot(NON_EXISTENT_UUID, ADMIN_HEADERS), "ERR_BALLOT_NOT_FOUND", 404
        )
        validate_error(
            api.get_ballot_slot(NON_EXISTENT_UUID, ADMIN_HEADERS), "ERR_BALLOT_NOT_FOUND", 404
        )

    def test_the_induction_and_exhibit_families_share_one_code_each(self, api):
        """All eight are HTTP 404. The same codes apply to identifiers carried in a request body
        rather than in the path — `cycle_id`, `candidate_id`, `carryover_from_candidacy_id`,
        `nominated_by_elector_id`, `bloc_id`, `ballot_id`, `induction_id`, `exhibit_case_id` — and
        the existence checks are evaluated in that order, cycle first and bloc last, so that a
        payload naming two non-existent parents reports the earlier family's code.

        Design: Corner/entities/induction_and_exhibit_not_found_on_unknown_ids
        """
        validate_error(
            api.get_induction(NON_EXISTENT_UUID, CURATOR_HEADERS), "ERR_INDUCTION_NOT_FOUND", 404
        )
        validate_error(
            api.get_travel_grant(NON_EXISTENT_UUID, CURATOR_HEADERS),
            "ERR_INDUCTION_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_exhibit_case(NON_EXISTENT_UUID, CURATOR_HEADERS), "ERR_EXHIBIT_NOT_FOUND", 404
        )
        validate_error(
            api.get_exhibit_installation(NON_EXISTENT_UUID, CURATOR_HEADERS),
            "ERR_EXHIBIT_NOT_FOUND",
            404,
        )


class TestRequiredFieldsAndDeclaredTypes:
    """Payload shape is band 3: a missing field or an undeclared value never reaches storage."""

    def test_an_elector_without_a_credential_expiry_is_malformed(self, api):
        """**Payload shape** — on every POST and PATCH endpoint: every required field present,
        every enum value a declared member, integers actually integers, timestamps parseable
        ISO 8601: `ERR_INVALID_REQUEST`.

        Design: Corner/entities/elector_create_without_credential_expires_on_rejected
        """
        bloc = setup_voter_bloc(api, seat_cap=4)
        validate_error(
            api.create_elector(
                create_elector_payload(
                    bloc["id"],
                    full_name="No Credential",
                    credential_expires_on=OMIT,
                    is_screening_member=OMIT,
                ),
                ADMIN_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

    def test_the_refused_elector_never_occupies_a_seat(self, api):
        """A bloc starts with `seats_filled` at 0, and that counter tracks every elector of the
        bloc whose `status` is `CREDENTIALED` or `SUSPENDED`.

        Design: Corner/entities/elector_create_without_credential_expires_on_rejected
        """
        bloc = setup_voter_bloc(api, seat_cap=4)
        api.create_elector(
            create_elector_payload(
                bloc["id"],
                full_name="No Credential",
                credential_expires_on=OMIT,
                is_screening_member=OMIT,
            ),
            ADMIN_HEADERS,
        )
        assert validate_success(api.get_voter_bloc(bloc["id"], ADMIN_HEADERS), 200)[
            "seats_filled"
        ] == 0
        rows, meta = validate_paginated(api.list_electors(ADMIN_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_pathway_outside_the_declared_set_is_malformed(self, api):
        """The payload names the `cycle_id` the nomination competes in, the `candidate_id` of the
        person being nominated, the `nominated_by_elector_id` of the credentialed elector filing
        it, and the `pathway` being claimed, which is one of `MODERN`, `VETERANS`, `POSTHUMOUS` or
        `SPECIAL`.

        Design: Corner/entities/undeclared_enum_and_wrong_scalar_type_rejected
        """
        world = build_election_world(
            api, stage="nominations_open", elector_count=1, candidate_count=1
        )
        validate_error(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    world["electors"][0]["id"],
                    pathway="LEGACY",
                ),
                ADMIN_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 0

    def test_a_string_where_an_integer_is_declared_is_malformed(self, api):
        """**Payload shape** — on every POST and PATCH endpoint: every required field present,
        every enum value a declared member, integers actually integers, timestamps parseable
        ISO 8601: `ERR_INVALID_REQUEST`.

        Design: Corner/entities/undeclared_enum_and_wrong_scalar_type_rejected
        """
        validate_error(
            api.create_candidate(
                create_candidate_payload(
                    full_name="Bad Types", career_seasons="fifteen", is_deceased=OMIT
                ),
                ADMIN_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        rows, meta = validate_paginated(api.list_candidates(ADMIN_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0


class TestServerComputedCandidacyFields:
    """What the server derives when a nomination is filed."""

    @pytest.fixture
    def world(self, api):
        """A 2026 cycle open for nominations, one credentialed elector, one 2018 retiree."""
        return build_election_world(
            api, stage="nominations_open", elector_count=1, candidate_count=1
        )

    def test_the_eligible_year_is_computed_from_the_baseline_and_the_wait(self, api, world):
        """The candidacy's `eligible_from_year` is then the baseline year plus the effective waiting
        period, and it is stored on the row.

        Design: Corner/entities/candidacy_eligible_from_year_computed_by_server
        """
        candidacy = validate_success(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    world["electors"][0]["id"],
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert world["candidates"][0]["retirement_year"] == 2018
        assert candidacy["eligible_from_year"] == 2023

    def test_the_fresh_candidacy_carries_only_declared_zeros(self, api, world):
        """A fresh candidacy is written in `SUBMITTED` status with `appearance_number` at 0 (it is
        off-ballot), `info_request_count` at 0, `latest_round_votes` and `latest_round_pct` at 0,
        and `screened_by_elector_id` and `screening_notes` unset.

        Design: Corner/entities/candidacy_eligible_from_year_computed_by_server
        """
        candidacy = validate_success(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    world["electors"][0]["id"],
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert candidacy["status"] == "SUBMITTED"
        assert candidacy["appearance_number"] == 0
        assert candidacy["info_request_count"] == 0
        assert candidacy["latest_round_votes"] == 0
        assert candidacy["latest_round_pct"] == pytest.approx(0.0, abs=0.01)
        assert candidacy["screened_by_elector_id"] is None
        assert candidacy["carryover_from_candidacy_id"] is None

    def test_filing_moves_only_the_nomination_counter(self, api, world):
        """Its creation increments the cycle's `nomination_count` by 1 and recomputes the cycle's
        `special_election_used`, which counts the cycle's candidacies whose `pathway` is `SPECIAL`
        and whose `status` is anything other than `REJECTED`.

        Design: Corner/entities/candidacy_eligible_from_year_computed_by_server
        """
        validate_success(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    world["electors"][0]["id"],
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["nomination_count"] == 1
        assert cycle["advanced_candidacy_count"] == 0
        assert cycle["special_election_used"] == 0


class TestConfigurationResourcesAreLeaner:
    """The two versionless configuration rows."""

    def test_neither_configuration_row_carries_a_version_or_an_updated_at(self, api):
        """Two configuration resources are deliberately leaner: `EligibilityRule` and `VoterBloc`
        carry only `id` and `created_at`. Both `updated_at` and `version` are absent from those two
        resources entirely — they are declared once and never versioned, which is also why neither
        of them participates in any concurrency check.

        Design: Corner/entities/eligibility_rule_and_voter_bloc_are_immutable_and_versionless
        """
        rule = setup_eligibility_rule(api)
        bloc = setup_voter_bloc(api, seat_cap=4)
        rule_row = validate_success(api.get_eligibility_rule(rule["id"], ADMIN_HEADERS), 200)
        bloc_row = validate_success(api.get_voter_bloc(bloc["id"], ADMIN_HEADERS), 200)
        for row in (rule_row, bloc_row):
            assert "version" not in row
            assert "updated_at" not in row
            assert is_valid_uuid(row["id"])
            assert is_iso8601_timestamp(row["created_at"])

    def test_the_declared_figures_survive_the_read_unchanged(self, api):
        """One rule row has a special standing that surfaces later in tabulation: the row for
        `PLAYER` paired with `MODERN` is the **house threshold row**, and its
        `election_threshold_pct` is the fraction every ballot's election thresholds are derived
        from, whatever categories actually appear on that ballot.

        Design: Corner/entities/eligibility_rule_and_voter_bloc_are_immutable_and_versionless
        """
        rule = setup_eligibility_rule(api, election_threshold_pct=0.75)
        bloc = setup_voter_bloc(api, seat_cap=4)
        rule_row = validate_success(api.get_eligibility_rule(rule["id"], ADMIN_HEADERS), 200)
        assert rule_row["category"] == "PLAYER"
        assert rule_row["pathway"] == "MODERN"
        assert rule_row["election_threshold_pct"] == pytest.approx(0.75, abs=0.01)
        bloc_row = validate_success(api.get_voter_bloc(bloc["id"], ADMIN_HEADERS), 200)
        assert bloc_row["seat_cap"] == 4
        assert bloc_row["seats_filled"] == 0


class TestForeignKeysAreValidatedAtWriteTime:
    """Flat topology: every parent identifier in a body has its own existence rule."""

    def test_an_unknown_bloc_on_an_elector_write_is_refused(self, api):
        """The optional `is_screening_member` flag, which defaults to false, is what allows that
        person to act under the `ScreeningCommitteeMember` role later; a bloc that does not exist
        yields `ERR_BLOC_NOT_FOUND`.

        Design: Corner/entities/flat_topology_validates_bloc_and_nominator_foreign_keys
        """
        setup_voter_bloc(api, seat_cap=4)
        validate_error(
            api.create_elector(
                create_elector_payload(
                    NON_EXISTENT_UUID, full_name="Orphan Elector", is_screening_member=OMIT
                ),
                ADMIN_HEADERS,
            ),
            "ERR_BLOC_NOT_FOUND",
            404,
        )
        rows, meta = validate_paginated(api.list_electors(ADMIN_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0

    def test_an_unknown_nominator_on_a_candidacy_write_is_refused(self, api):
        """All eight are HTTP 404. The same codes apply to identifiers carried in a request body
        rather than in the path — `cycle_id`, `candidate_id`, `carryover_from_candidacy_id`,
        `nominated_by_elector_id`, `bloc_id`, `ballot_id`, `induction_id`, `exhibit_case_id` — and
        the existence checks are evaluated in that order, cycle first and bloc last, so that a
        payload naming two non-existent parents reports the earlier family's code.

        Design: Corner/entities/flat_topology_validates_bloc_and_nominator_foreign_keys
        """
        world = build_election_world(
            api, stage="nominations_open", elector_count=1, candidate_count=1
        )
        validate_error(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"], world["candidates"][0]["id"], NON_EXISTENT_UUID
                ),
                ADMIN_HEADERS,
            ),
            "ERR_ELECTOR_NOT_FOUND",
            404,
        )
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 0
