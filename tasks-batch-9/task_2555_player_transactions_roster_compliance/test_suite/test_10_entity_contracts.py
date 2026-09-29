"""The shape of each stored record: fields, defaults and not-found answers."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_BONUS_ALLOCATION_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_INJURY_DESIGNATION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PHYSICAL_EXAM_NOT_FOUND,
    ERR_PLAYER_NOT_FOUND,
    ERR_TEAM_NOT_FOUND,
    ERR_TENDER_NOT_FOUND,
    ERR_TRADE_NOT_FOUND,
    ERR_TRANSACTION_NOT_FOUND,
    ERR_WAIVER_CLAIM_NOT_FOUND,
    ERR_WAIVER_REQUEST_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_cap_position,
    assert_designation_counts,
    assert_immutable_identity,
    assert_pagination_meta,
    assert_request_envelope,
    assert_version_is,
    assert_versioned_identity,
    find_by_id,
)
from test_helpers.fixtures import League
from test_helpers.test_users import make_cap_analyst_headers

CLOCK = "2026-08-10T14:00:00Z"
UNKNOWN_ID = "00000000-0000-0000-0000-00000000dead"


class TestClubRegistrationShape:
    """What a newly registered club looks like."""

    def test_registration_returns_zeroed_counters_and_the_whole_cap(
        self, league: League
    ) -> None:
        """A brand-new club is empty on every computed field.

        PRD 3.1: "A freshly registered club starts with every headcount and every
        money total at zero, `cap_space_cents` equal to its `salary_cap_limit_cents`,
        and a `compliance_status` of `COMPLIANT`."

        Design: Corner/entities/create_team_returns_every_declared_field_with_zeroed_counters
        """
        league.set_clock(CLOCK)

        response = league.api.create_team(
            fac.team_payload(
                name="Harbor Kings", market_code="HKG",
                salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
                active_roster_limit=26, reserve_roster_limit=4,
                injured_reserve_limit=3, practice_squad_limit=6,
            ),
            league.officer,
        )
        club = validate_success(response, 201)
        assert_request_envelope(response, "object")
        assert_versioned_identity(club, "team")

        assert club["name"] == "Harbor Kings", (
            f"the supplied name is stored, got {club['name']}"
        )
        assert club["market_code"] == "HKG", (
            f"the supplied market code is stored, got {club['market_code']}"
        )
        assert club["salary_cap_limit_cents"] == 500_000_000, (
            f"the supplied cap limit is stored, got {club['salary_cap_limit_cents']}"
        )
        assert club["waiver_priority_rank"] == 1, (
            f"the supplied priority rank is stored, got {club['waiver_priority_rank']}"
        )
        assert_designation_counts(
            club, active=0, reserve=0, injured_reserve=0, practice_squad=0
        )
        assert_cap_position(
            club, provisional=0, final=0, dead_money=0, cap_space=500_000_000,
        )
        assert club["open_medical_review_count"] == 0, (
            f"no trade is in review yet, got {club['open_medical_review_count']}"
        )
        assert club["consecutive_noncompliant_checks"] == 0, (
            "no sweep has found a violation, got "
            f"{club['consecutive_noncompliant_checks']}"
        )
        assert club["grace_expires_at"] is None, (
            f"no grace window is armed, got {club['grace_expires_at']}"
        )
        assert club["compliance_status"] == "COMPLIANT", (
            f"a new club is in order, got {club['compliance_status']}"
        )
        assert_version_is(club, 1, "team")

    def test_omitting_the_four_quotas_applies_the_league_defaults(
        self, league: League
    ) -> None:
        """The league's own default quotas fill in for anything unsupplied.

        PRD 3.1: "The four roster quotas may be supplied at registration and
        otherwise take league defaults: `active_roster_limit` defaults to 26 and must
        be at least 1; `reserve_roster_limit` defaults to 4; `injured_reserve_limit`
        defaults to 3; `practice_squad_limit` defaults to 6; and the latter three must
        each be at least 0."

        Design: Corner/entities/create_team_omitting_limits_applies_declared_defaults
        """
        league.set_clock(CLOCK)

        response = league.api.create_team(
            {
                "name": "Basin Otters", "market_code": "BSN",
                "salary_cap_limit_cents": 500_000_000, "waiver_priority_rank": 2,
            },
            league.officer,
        )
        club = validate_success(response, 201)

        assert club["active_roster_limit"] == 26, (
            f"the active quota defaults to 26, got {club['active_roster_limit']}"
        )
        assert club["reserve_roster_limit"] == 4, (
            f"the reserve quota defaults to 4, got {club['reserve_roster_limit']}"
        )
        assert club["injured_reserve_limit"] == 3, (
            "the injured-reserve quota defaults to 3, got "
            f"{club['injured_reserve_limit']}"
        )
        assert club["practice_squad_limit"] == 6, (
            "the practice-squad quota defaults to 6, got "
            f"{club['practice_squad_limit']}"
        )
        assert_version_is(club, 1, "team")

    def test_supplied_headcounts_and_cap_space_are_recomputed_not_accepted(
        self, league: League
    ) -> None:
        """A client cannot assert its own headcount or cap space into existence.

        PRD 1: "Second, **derived state is never accepted as input**: roster counts,
        cap totals, service-time totals, dead money, proration schedules, compliance
        postures and eligibility flags are all computed by the server from the records
        it holds, so a client cannot assert its way into compliance."

        Design: Corner/entities/team_active_roster_count_input_ignored_on_create
        """
        league.set_clock(CLOCK)

        response = league.api.create_team(
            {
                "name": "Coastal Rays", "market_code": "CST",
                "salary_cap_limit_cents": 500_000_000, "waiver_priority_rank": 3,
                "active_roster_count": 99, "cap_space_cents": 1,
            },
            league.officer,
        )
        club = validate_success(response, 201)

        assert club["active_roster_count"] == 0, (
            "the headcount is recomputed from the roster, so the supplied 99 is "
            f"discarded, got {club['active_roster_count']}"
        )
        assert club["cap_space_cents"] == 500_000_000, (
            "cap space is derived from the limit and the provisional total, so the "
            f"supplied 1 is discarded, got {club['cap_space_cents']}"
        )

    def test_registration_without_a_market_code_is_a_request_shape_failure(
        self, league: League
    ) -> None:
        """A missing required field is refused and nothing is stored.

        PRD 2.8: "Request shape: the body parses, every required field is present,
        enums carry known values, integers fall in their declared ranges, datetimes
        are well-formed, money amounts are non-negative, `window_end_at` is strictly
        later than `window_start_at`, and the conditional companion fields demanded by
        a polymorphic `asset_kind` are supplied — otherwise `ERR_INVALID_REQUEST`
        (400)."

        Design: Corner/entities/create_team_missing_market_code_returns_invalid_request
        """
        league.set_clock(CLOCK)

        response = league.api.create_team(
            {
                "name": "Harbor Kings", "salary_cap_limit_cents": 500_000_000,
                "waiver_priority_rank": 1,
            },
            league.officer,
        )
        validate_error(response, ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(league.api.list_teams(league.officer))
        assert meta["total_count"] == 0, (
            f"the refused registration stored no club, got {meta['total_count']}"
        )

    def test_an_unknown_enum_value_is_refused_on_both_records(
        self, league: League
    ) -> None:
        """A position outside the enum and a malformed market code both fail.

        PRD 3.2: "The league office registers each player with a `full_name` of 1 to
        80 non-blank characters and a `position` drawn from `QB`, `RB`, `WR`, `OL`,
        `DL`, `LB`, `DB` and `K`."
        PRD 3.1: "Registration carries the club's `name` — between 1 and 80
        characters, and not blank — and its `market_code`, which is exactly three
        uppercase letters A through Z and must be unique across every club in the
        league; a collision is refused with `ERR_DUPLICATE_MARKET_CODE`."

        Design: Corner/entities/create_player_with_unknown_position_returns_invalid_request
        """
        league.set_clock(CLOCK)

        player_response = league.api.create_player(
            {"full_name": "Odd Position", "position": "GOALIE"}, league.officer
        )
        validate_error(player_response, ERR_INVALID_REQUEST, 400)

        team_response = league.api.create_team(
            {
                "name": "Bad Code", "market_code": "hk",
                "salary_cap_limit_cents": 500_000_000, "waiver_priority_rank": 9,
            },
            league.officer,
        )
        validate_error(team_response, ERR_INVALID_REQUEST, 400)

        _, player_meta = validate_paginated(
            league.api.list_players(league.officer)
        )
        assert player_meta["total_count"] == 0, (
            f"no player was stored, got {player_meta['total_count']}"
        )
        _, team_meta = validate_paginated(league.api.list_teams(league.officer))
        assert team_meta["total_count"] == 0, (
            f"no club was stored either, got {team_meta['total_count']}"
        )


class TestPlayerRegistrationShape:
    """What a newly registered player looks like, and how a read echoes it."""

    def test_reading_a_player_echoes_the_stored_record_and_its_derived_flags(
        self, league: League
    ) -> None:
        """A registered player reads back with every derived field at its floor.

        PRD 3.2: "Everything else about the player is derived: a freshly registered
        player has `roster_designation` `UNROSTERED`, `medical_status` `CLEARED`, a
        `current_team_id` of null, and a `designation_effective_at` set to the logical
        clock at registration."

        Design: Corner/entities/get_player_returns_the_stored_record
        """
        league.set_clock(CLOCK)
        created = league.register_player(full_name="Ray Alder", position="QB")

        response = league.api.get_player(created["id"], league.officer)
        player = validate_success(response, 200)

        assert player["full_name"] == "Ray Alder", (
            f"the stored name is echoed, got {player['full_name']}"
        )
        assert player["position"] == "QB", (
            f"the stored position is echoed, got {player['position']}"
        )
        assert player["roster_designation"] == "UNROSTERED", (
            f"a new player is unrostered, got {player['roster_designation']}"
        )
        assert player["medical_status"] == "CLEARED", (
            f"and medically cleared, got {player['medical_status']}"
        )
        assert player["current_team_id"] is None, (
            f"and owned by nobody, got {player['current_team_id']}"
        )
        assert player["pension_credit_days"] == 0, (
            f"no day buckets were seeded, got {player['pension_credit_days']}"
        )
        assert player["roster_service_days"] == 0, (
            f"so roster service is zero too, got {player['roster_service_days']}"
        )
        assert player["service_years"] == 0, (
            f"and no service year has accrued, got {player['service_years']}"
        )
        assert player["contract_rights_class"] == "NONE", (
            "zero service years give no contract rights, got "
            f"{player['contract_rights_class']}"
        )
        assert player["practice_squad_eligible"] is True, (
            "with no roster service and no seasons used the player is practice-squad "
            "eligible"
        )
        assert player["waiver_revocability_class"] == "REVOCABLE", (
            "a placement made before 2026-08-25T16:00:00Z would be revocable, got "
            f"{player['waiver_revocability_class']}"
        )

    def test_player_identity_fields_are_minted_by_the_server(
        self, league: League
    ) -> None:
        """The id, the two timestamps and the version all come from the server.

        PRD 2.4: "`created_at` is the ISO 8601 UTC instant of creation, rendered with
        exactly three fractional-second digits."
        PRD 2.4: "`version` is an integer that starts at 1 and increases by exactly 1
        on every mutation of that resource."

        Design: Corner/entities/player_system_fields_are_server_generated_on_create
        """
        league.set_clock(CLOCK)

        response = league.api.create_player(
            fac.player_payload(full_name="Vic Lund", position="LB"),
            league.officer,
        )
        player = validate_success(response, 201)

        assert_versioned_identity(player, "player")
        assert player["created_at"] == "2026-08-10T14:00:00.000Z", (
            f"creation is stamped from the logical clock, got {player['created_at']}"
        )
        assert player["updated_at"] == player["created_at"], (
            "at creation the two timestamps agree, got "
            f"{player['updated_at']} against {player['created_at']}"
        )
        assert_version_is(player, 1, "player")
        assert player["designation_effective_at"] == "2026-08-10T14:00:00.000Z", (
            "the accrual baseline starts at the registration instant, got "
            f"{player['designation_effective_at']}"
        )
        assert player["last_physical_passed_at"] is None, (
            "the player has passed no physical yet, got "
            f"{player['last_physical_passed_at']}"
        )

    def test_the_player_list_pages_with_all_four_pagination_fields(
        self, league: League
    ) -> None:
        """Two pages over three players report the same total and disjoint rows.

        PRD 2.3: "List responses carry all four pagination fields in `meta`: `limit`
        and `offset` echo the values actually applied, `total_count` is the number of
        records matching the filter before the page window is applied, and `has_more`
        is true exactly when records remain beyond the current page."

        Design: Corner/entities/list_players_paginates_with_total_count_and_has_more
        """
        league.set_clock(CLOCK)
        league.register_player(full_name="Ray Alder", position="QB")
        league.register_player(full_name="Nate Orr", position="WR")
        league.register_player(full_name="Cy Boone", position="DB")

        first_page, first_meta = validate_paginated(
            league.api.list_players(league.officer, {"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2, (
            f"the first page holds two rows, got {len(first_page)}"
        )
        assert_pagination_meta(
            first_meta, total_count=3, has_more=True, limit=2, offset=0
        )

        second_page, second_meta = validate_paginated(
            league.api.list_players(league.officer, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1, (
            f"the second page holds the remaining row, got {len(second_page)}"
        )
        assert_pagination_meta(
            second_meta, total_count=3, has_more=False, limit=2, offset=2
        )

        first_ids = {row["id"] for row in first_page}
        second_ids = {row["id"] for row in second_page}
        assert first_ids.isdisjoint(second_ids), (
            "the two pages must not share a row, got "
            f"{first_ids & second_ids}"
        )


class TestNotFoundCatalogue:
    """Every path family answers with its own 404 code."""

    def test_an_unknown_filing_id_returns_the_filing_not_found_code(
        self, league: League
    ) -> None:
        """A read for a filing that does not exist is a typed 404, not an empty body.

        PRD 2.8: "Every identifier in the URL path exists, validated left to right —
        otherwise the matching 404 from the not-found catalogue
        (`ERR_TEAM_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_BONUS_ALLOCATION_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`,
        `ERR_WAIVER_REQUEST_NOT_FOUND`, `ERR_WAIVER_CLAIM_NOT_FOUND`,
        `ERR_TRADE_NOT_FOUND`, `ERR_TENDER_NOT_FOUND`,
        `ERR_INJURY_DESIGNATION_NOT_FOUND`, `ERR_PHYSICAL_EXAM_NOT_FOUND`)."

        Design: Corner/entities/get_transaction_with_unknown_id_returns_not_found
        """
        league.set_clock(CLOCK)

        response = league.api.get_transaction(UNKNOWN_ID, league.officer)
        validate_error(response, ERR_TRANSACTION_NOT_FOUND, 404)

        assert_request_envelope(response, "error")
        message = response.json()["data"]["message"]
        assert isinstance(message, str) and message.strip(), (
            f"the error must carry a human-readable message, got {message!r}"
        )

    def test_each_path_family_answers_with_its_own_not_found_code(
        self, league: League
    ) -> None:
        """The same unknown id draws ten different codes across ten paths.

        PRD 2.8: "Every identifier in the URL path exists, validated left to right —
        otherwise the matching 404 from the not-found catalogue
        (`ERR_TEAM_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_BONUS_ALLOCATION_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`,
        `ERR_WAIVER_REQUEST_NOT_FOUND`, `ERR_WAIVER_CLAIM_NOT_FOUND`,
        `ERR_TRADE_NOT_FOUND`, `ERR_TENDER_NOT_FOUND`,
        `ERR_INJURY_DESIGNATION_NOT_FOUND`, `ERR_PHYSICAL_EXAM_NOT_FOUND`)."

        Design: Corner/entities/path_id_family_each_returns_its_own_not_found_error
        """
        league.set_clock(CLOCK)

        validate_error(
            league.api.get_team(UNKNOWN_ID, league.officer),
            ERR_TEAM_NOT_FOUND, 404,
        )
        validate_error(
            league.api.get_player(UNKNOWN_ID, league.officer),
            ERR_PLAYER_NOT_FOUND, 404,
        )
        validate_error(
            league.api.get_contract(UNKNOWN_ID, league.officer),
            ERR_CONTRACT_NOT_FOUND, 404,
        )
        validate_error(
            league.api.earn_bonus_allocation(UNKNOWN_ID, league.officer),
            ERR_BONUS_ALLOCATION_NOT_FOUND, 404,
        )
        validate_error(
            league.api.get_waiver_request(UNKNOWN_ID, league.officer),
            ERR_WAIVER_REQUEST_NOT_FOUND, 404,
        )
        validate_error(
            league.api.get_waiver_claim(UNKNOWN_ID, league.officer),
            ERR_WAIVER_CLAIM_NOT_FOUND, 404,
        )
        validate_error(
            league.api.get_trade(UNKNOWN_ID, league.officer),
            ERR_TRADE_NOT_FOUND, 404,
        )
        validate_error(
            league.api.get_tender(UNKNOWN_ID, league.officer),
            ERR_TENDER_NOT_FOUND, 404,
        )
        validate_error(
            league.api.get_injury_designation(UNKNOWN_ID, league.officer),
            ERR_INJURY_DESIGNATION_NOT_FOUND, 404,
        )
        validate_error(
            league.api.get_physical_exam(UNKNOWN_ID, league.officer),
            ERR_PHYSICAL_EXAM_NOT_FOUND, 404,
        )

    def test_claiming_under_an_unknown_wire_reports_the_wire_before_the_version(
        self, league: League
    ) -> None:
        """The path check at rung 8 fires before the version check at rung 10.

        PRD 2.8: "`expected_team_version` equals the club's current `version` —
        otherwise `ERR_STALE_TEAM_VERSION` (412). Applies to `POST /transactions` and
        `POST /waiver-requests/{id}/claims`."

        Design: Corner/entities/waiver_claim_on_unknown_parent_wire_returns_not_found
        """
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Basin Otters", market_code="BSN",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=2,
        )

        response = league.api.submit_waiver_claim(
            UNKNOWN_ID,
            fac.waiver_claim_payload(club["id"], club["version"]),
            make_cap_analyst_headers(club["id"]),
        )
        validate_error(response, ERR_WAIVER_REQUEST_NOT_FOUND, 404)

        _, meta = validate_paginated(league.api.list_waiver_claims(league.officer))
        assert meta["total_count"] == 0, (
            f"no claim was stored, got {meta['total_count']}"
        )
        assert league.club(club["id"])["version"] == club["version"], (
            "the refused claim left the club's version alone, got "
            f"{league.club(club['id'])['version']}"
        )


class TestSweepRowIsAnImmutableAuditEvent:
    """The sweep record carries no version and no updated_at."""

    def test_a_sweep_row_exposes_only_the_immutable_identity_block(
        self, league: League
    ) -> None:
        """The audit row is append-only: no version, no updated_at, one history entry.

        PRD 2.4: "`ComplianceCheck` is the single exception. A sweep record is an
        immutable audit event, so it carries only `id` and `created_at`: it has no
        `updated_at` and no `version` field at all, and neither should appear in its
        representation."

        Design: Corner/entities/compliance_check_row_is_immutable_and_carries_no_version
        """
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )

        response = league.api.run_compliance_check(
            fac.compliance_check_payload(club["id"]), league.officer
        )
        row = validate_success(response, 201)

        assert_immutable_identity(row, "compliance check")
        assert row["checked_at"] == "2026-08-10T14:00:00.000Z", (
            f"the sweep is stamped on the logical clock, got {row['checked_at']}"
        )
        assert row["result"] == "COMPLIANT", (
            f"an empty club breaks nothing, got {row['result']}"
        )
        assert row["violation_codes"] == [], (
            f"and lists no violation, got {row['violation_codes']}"
        )
        assert row["resulting_compliance_status"] == "COMPLIANT", (
            "the posture after the sweep is still COMPLIANT, got "
            f"{row['resulting_compliance_status']}"
        )

        history, meta = validate_paginated(
            league.api.list_team_compliance_checks(club["id"], league.officer)
        )
        assert meta["total_count"] == 1, (
            f"the club has exactly one sweep on file, got {meta['total_count']}"
        )
        assert history[0]["id"] == row["id"], (
            "the history returns that same row, got "
            f"{history[0]['id']} against {row['id']}"
        )
        assert_immutable_identity(history[0], "compliance check from history")


class TestTradeAssetJunction:
    """One asset row joins a trade to a contract and is reachable from both."""

    def test_a_contract_asset_is_reachable_from_the_trade_and_the_contract(
        self, league: League
    ) -> None:
        """The junction row appears under both parents and the deltas negate.

        PRD 3.7: "Because every asset is directed at exactly one club, the two deltas
        are always exact negations of one another."

        Design: Corner/entities/trade_asset_junction_links_a_trade_to_a_contract_both_ways
        """
        league.set_clock(CLOCK)
        initiator = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        counterparty = league.register_club(
            name="Basin Otters", market_code="BSN",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=2,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        signing = league.sign_onto_roster(
            initiator["id"], player["id"],
            window_start_at="2026-08-10T13:00:00Z",
            window_end_at="2026-08-10T20:00:00Z",
            performed_at=CLOCK,
            expected_team_version=initiator["version"], years=3,
            base_salary_cents=80_000_000, signing_bonus_cents=10_000_000,
            start_season_year=2026,
        )
        trade = league.build_trade(initiator["id"], counterparty["id"], "NONE")

        response = league.api.add_trade_asset(
            trade["id"],
            fac.contract_asset_payload(
                signing["contract_id"], "TO_COUNTERPARTY", trade["version"]
            ),
            make_cap_analyst_headers(initiator["id"]),
        )
        asset = validate_success(response, 201)

        assert asset["cap_charge_snapshot_cents"] == 83_333_333, (
            "the snapshot is the contract's current-season charge, got "
            f"{asset['cap_charge_snapshot_cents']}"
        )
        assert asset["status"] == "PROPOSED", (
            f"a new asset is born PROPOSED, got {asset['status']}"
        )
        assert asset["trade_id"] == trade["id"], (
            f"the row points back at its trade, got {asset['trade_id']}"
        )
        assert asset["contract_id"] == signing["contract_id"], (
            f"and at its contract, got {asset['contract_id']}"
        )

        from_trade, trade_meta = validate_paginated(
            league.api.list_trade_assets(trade["id"], league.officer)
        )
        assert trade_meta["total_count"] == 1, (
            f"the trade holds one asset, got {trade_meta['total_count']}"
        )
        find_by_id(from_trade, asset["id"])

        from_contract, contract_meta = validate_paginated(
            league.api.list_contract_trade_assets(
                signing["contract_id"], league.officer
            )
        )
        assert contract_meta["total_count"] == 1, (
            "the same row is reachable from the contract, got "
            f"{contract_meta['total_count']}"
        )
        find_by_id(from_contract, asset["id"])

        stored = league.trade(trade["id"])
        assert stored["cap_delta_initiating_cents"] == -83_333_333, (
            "the sending club sheds the charge, got "
            f"{stored['cap_delta_initiating_cents']}"
        )
        assert stored["cap_delta_counterparty_cents"] == 83_333_333, (
            "and the receiving club takes it on, got "
            f"{stored['cap_delta_counterparty_cents']}"
        )
        assert stored["version"] == 2, (
            f"creation and one addition make two writes, got {stored['version']}"
        )
        assert league.contract(signing["contract_id"])["team_id"] == (
            initiator["id"]
        ), "nothing has moved yet, so the contract still belongs to the sender"
