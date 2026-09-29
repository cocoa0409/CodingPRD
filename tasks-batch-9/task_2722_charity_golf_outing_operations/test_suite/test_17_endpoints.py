"""Collection reads, the ordered pairing sheet, and the two guarded write shapes."""

from test_helpers import (
    COURSE_HEADERS,
    DIRECTOR_HEADERS,
    TREASURER_HEADERS,
    ApiErrorId,
    assert_instant_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

SOLO_TIER = {
    "code": "SOLO",
    "kind": "INDIVIDUAL",
    "price_cents": 30000,
    "player_slots": 1,
    "gsv_cents": 0,
    "inventory_cap": 10,
}
NO_GUARANTEE = {"guaranteed_player_count": 0}

LISTING_OUTING = {"name": "Listing Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
OTHER_LISTING_OUTING = {
    "name": "Other Listing Open",
    "beneficiary_name": "Southside Literacy Trust",
    "scheduled_date": "2026-09-26T12:00:00Z",
    "wave_a_start": "2026-09-26T12:00:00Z",
    "wave_a_end": "2026-09-26T16:30:00Z",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}


class TestRegistrationListing:
    def _five_rows_on_one_outing_and_one_elsewhere(self, api):
        ctx = fx.open_outing(
            api, outing=LISTING_OUTING, contract=NO_GUARANTEE, tier=SOLO_TIER
        )
        team_tier = fx.add_tier(api, ctx)
        ctx["solo_tier_id"] = ctx["tier_id"]
        ctx["team_tier_id"] = team_tier["id"]

        solo_paid = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Solo Alpha", player_count=1
        )
        fx.pay_registration(api, solo_paid["id"], 30000)
        solo_bravo = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Solo Bravo", player_count=1
        )
        solo_charlie = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Solo Charlie", player_count=1
        )
        team_paid = fx.new_registration(
            api, ctx["outing_id"], team_tier["id"], buyer_name="Team Delta", player_count=4
        )
        fx.pay_registration(api, team_paid["id"], 120000)
        team_echo = fx.new_registration(
            api, ctx["outing_id"], team_tier["id"], buyer_name="Team Echo", player_count=4
        )

        other = fx.open_outing(
            api,
            clock=None,
            outing=OTHER_LISTING_OUTING,
            contract=NO_GUARANTEE,
            tier=SOLO_TIER,
        )
        foreign = fx.new_registration(
            api, other["outing_id"], other["tier_id"], buyer_name="Foreign Buyer",
            player_count=1,
        )

        ctx.update(
            {
                "solo_paid_id": solo_paid["id"],
                "solo_bravo_id": solo_bravo["id"],
                "solo_charlie_id": solo_charlie["id"],
                "team_paid_id": team_paid["id"],
                "team_echo_id": team_echo["id"],
                "foreign_id": foreign["id"],
            }
        )
        return ctx

    def test_the_default_window_covers_the_filtered_set_and_excludes_other_outings(self, api):
        """The window is implicit but bounded: `limit` "defaults to 10 when omitted", and
        "`total_count` is the number of rows matching the filters before the window is
        applied, and `has_more` is true exactly when rows remain beyond the returned
        window."  The outing filter is part of the contract for this collection, which is
        described as "List registrations, filterable by outing, tier and status."

        Design: Corner/endpoints/registration_listing_filters_and_paginates_over_one_outing
        """
        ctx = self._five_rows_on_one_outing_and_one_elsewhere(api)

        rows, meta = validate_paginated(
            api.list_registrations(TREASURER_HEADERS, outing_id=ctx["outing_id"])
        )
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 5
        assert meta["has_more"] is False
        assert len(rows) == 5

        ids = {row["id"] for row in rows}
        assert ctx["foreign_id"] not in ids
        assert ids == {
            ctx["solo_paid_id"],
            ctx["solo_bravo_id"],
            ctx["solo_charlie_id"],
            ctx["team_paid_id"],
            ctx["team_echo_id"],
        }
        assert all(row["outing_id"] == ctx["outing_id"] for row in rows)

    def test_the_windows_the_intersecting_filters_and_the_rejected_limit(self, api):
        """Paging never rewrites the count: "`total_count` is the number of rows matching the
        filters before the window is applied", so a two-row page still reports five and
        the trailing partial page closes the cursor.  Two filters intersect rather than
        union, and the bound on `limit` is a schema rule, not a clamp - it "may not be
        larger than 100", and "A value outside those bounds is a schema violation and is
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/registration_listing_filters_and_paginates_over_one_outing
        """
        ctx = self._five_rows_on_one_outing_and_one_elsewhere(api)

        first_rows, first_meta = validate_paginated(
            api.list_registrations(TREASURER_HEADERS, outing_id=ctx["outing_id"], limit=2,
                                   offset=0)
        )
        assert len(first_rows) == 2
        assert first_meta["total_count"] == 5
        assert first_meta["has_more"] is True

        last_rows, last_meta = validate_paginated(
            api.list_registrations(TREASURER_HEADERS, outing_id=ctx["outing_id"], limit=2,
                                   offset=4)
        )
        assert len(last_rows) == 1
        assert last_meta["total_count"] == 5
        assert last_meta["has_more"] is False

        confirmed_rows, confirmed_meta = validate_paginated(
            api.list_registrations(
                TREASURER_HEADERS, outing_id=ctx["outing_id"], status="CONFIRMED"
            )
        )
        assert confirmed_meta["total_count"] == 2
        assert {row["id"] for row in confirmed_rows} == {
            ctx["solo_paid_id"], ctx["team_paid_id"]
        }

        pending_rows, pending_meta = validate_paginated(
            api.list_registrations(
                TREASURER_HEADERS,
                outing_id=ctx["outing_id"],
                package_tier_id=ctx["solo_tier_id"],
                status="PENDING_PAYMENT",
            )
        )
        assert pending_meta["total_count"] == 2
        assert {row["id"] for row in pending_rows} == {
            ctx["solo_bravo_id"], ctx["solo_charlie_id"]
        }

        validate_error(
            api.list_registrations(TREASURER_HEADERS, outing_id=ctx["outing_id"], limit=101),
            ApiErrorId.INVALID_REQUEST,
            422,
        )


SHOTGUN_OUTING = {
    "name": "Shotgun Pairing Sheet",
    "start_format": "SHOTGUN",
    "wave_b_start": "2026-09-19T17:00:00Z",
    "wave_b_end": "2026-09-19T21:30:00Z",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}
SHEET_CONTRACT = {
    "guaranteed_player_count": 0,
    "tee_interval_minutes": 10,
    "cart_allowance_count": 40,
}
WAVE_A_SHOTGUN = "2026-09-19T12:00:00Z"
WAVE_B_SHOTGUN = "2026-09-19T17:00:00Z"
WAVE_A_OCCUPANCY_END = "2026-09-19T12:10:00Z"
WAVE_B_OCCUPANCY_END = "2026-09-19T17:10:00Z"
SHEET_BUYERS = ("Sheet Alpha", "Sheet Bravo", "Sheet Charlie", "Sheet Delta")


class TestPairingSheetOrdering:
    def _four_groups_placed_out_of_order(self, api):
        ctx = fx.open_outing(
            api, outing=SHOTGUN_OUTING, contract=SHEET_CONTRACT, tier=SOLO_TIER
        )
        team_ids = []
        for index, buyer in enumerate(SHEET_BUYERS):
            registration = fx.new_registration(
                api, ctx["outing_id"], ctx["tier_id"], buyer_name=buyer, player_count=1
            )
            player = fx.new_player(
                api, registration["id"], full_name=f"{buyer} Player", handicap_index=12.0
            )
            fx.pay_registration(api, registration["id"], 30000)
            team = fx.new_team(
                api, ctx["outing_id"], [player["id"]], team_name=f"Group {index + 1}"
            )
            team_ids.append(team["id"])

        a10, a1, b10, b1 = team_ids
        fx.assign_tee(api, a10, wave="A", starting_hole=10, tee_time=WAVE_A_SHOTGUN,
                      cart_number=2)
        fx.assign_tee(api, a1, wave="A", starting_hole=1, tee_time=WAVE_A_SHOTGUN,
                      cart_number=1)
        fx.assign_tee(api, b10, wave="B", starting_hole=10, tee_time=WAVE_B_SHOTGUN,
                      cart_number=4)
        fx.assign_tee(api, b1, wave="B", starting_hole=1, tee_time=WAVE_B_SHOTGUN,
                      cart_number=3)
        ctx.update({"a10": a10, "a1": a1, "b10": b10, "b1": b1})
        return ctx

    def test_the_sheet_falls_through_to_the_starting_hole_inside_a_wave(self, api):
        """The read is ordered, not insertion-ordered: it "returns every team of the outing
        ordered by `wave`, then by `starting_hole`, then by `tee_time`, then by
        `created_at`, each row carrying its cart number and its playing handicap."  Under
        a shotgun start every group in a wave shares one instant, so the second key is the
        only one that can decide.  Each placement also stamps the occupancy window: it
        "sets `slot_occupancy_start` equal to the `tee_time` and `slot_occupancy_end` to
        the `tee_time` advanced by `tee_interval_minutes`".

        Design: Corner/endpoints/the_pairing_sheet_orders_by_wave_then_starting_hole_then_tee_time_then_created_at
        """
        ctx = self._four_groups_placed_out_of_order(api)

        rows, meta = validate_paginated(api.get_pairing_sheet(ctx["outing_id"], COURSE_HEADERS))
        assert meta["total_count"] == 4
        assert [row["id"] for row in rows] == [ctx["a1"], ctx["a10"], ctx["b1"], ctx["b10"]]
        assert [row["wave"] for row in rows] == ["A", "A", "B", "B"]
        assert [row["starting_hole"] for row in rows] == [1, 10, 1, 10]
        assert [row["cart_number"] for row in rows] == [1, 2, 3, 4]
        assert all(row["team_playing_handicap"] is not None for row in rows)

        for row in rows[:2]:
            assert_instant_equals(row["tee_time"], WAVE_A_SHOTGUN)
            assert_instant_equals(row["slot_occupancy_start"], WAVE_A_SHOTGUN)
            assert_instant_equals(row["slot_occupancy_end"], WAVE_A_OCCUPANCY_END)
        for row in rows[2:]:
            assert_instant_equals(row["tee_time"], WAVE_B_SHOTGUN)
            assert_instant_equals(row["slot_occupancy_start"], WAVE_B_SHOTGUN)
            assert_instant_equals(row["slot_occupancy_end"], WAVE_B_OCCUPANCY_END)

    def test_the_wave_filter_and_the_window_narrow_the_same_ordering(self, api):
        """The sheet "accepts an optional `wave` filter alongside the usual `limit` and
        `offset`", and the window is applied to the sorted sheet rather than to insertion
        order, because "`total_count` is the number of rows matching the filters before
        the window is applied".

        Design: Corner/endpoints/the_pairing_sheet_orders_by_wave_then_starting_hole_then_tee_time_then_created_at
        """
        ctx = self._four_groups_placed_out_of_order(api)

        wave_b, wave_b_meta = validate_paginated(
            api.get_pairing_sheet(ctx["outing_id"], COURSE_HEADERS, wave="B")
        )
        assert wave_b_meta["total_count"] == 2
        assert [row["id"] for row in wave_b] == [ctx["b1"], ctx["b10"]]

        page, page_meta = validate_paginated(
            api.get_pairing_sheet(ctx["outing_id"], DIRECTOR_HEADERS, limit=2, offset=2)
        )
        assert page_meta["total_count"] == 4
        assert page_meta["has_more"] is False
        assert [row["id"] for row in page] == [ctx["b1"], ctx["b10"]]


CROSS_ONE = {"name": "Cross Ref One", "field_capacity_teams": 4, "prize_pool_cents": 0}
CROSS_TWO = {
    "name": "Cross Ref Two",
    "beneficiary_name": "Southside Literacy Trust",
    "scheduled_date": "2026-09-26T12:00:00Z",
    "wave_a_start": "2026-09-26T12:00:00Z",
    "wave_a_end": "2026-09-26T16:30:00Z",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}
BIRCH_HOLLOW = {"guaranteed_player_count": 0, "course_name": "Birch Hollow GC"}
FOREIGN_APPEAL = {"item_type": "DONATION", "description": "Foreign appeal", "ask_cents": 50000}


class TestCrossOutingReferences:
    def _two_peopled_outings(self, api):
        home = fx.open_outing(api, outing=CROSS_ONE, contract=NO_GUARANTEE, tier=SOLO_TIER)
        home_reg = fx.new_registration(
            api, home["outing_id"], home["tier_id"], buyer_name="Home Buyer", player_count=1
        )
        home_player = fx.new_player(api, home_reg["id"], full_name="Home Player")
        fx.pay_registration(api, home_reg["id"], 30000)

        away = fx.open_outing(
            api, clock=None, outing=CROSS_TWO, contract=BIRCH_HOLLOW, tier=SOLO_TIER
        )
        away_reg = fx.new_registration(
            api, away["outing_id"], away["tier_id"], buyer_name="Foreign Buyer",
            player_count=1,
        )
        away_player = fx.new_player(api, away_reg["id"], full_name="Foreign Player")
        fx.pay_registration(api, away_reg["id"], 30000)
        away_item = fx.new_item(api, away["outing_id"], **FOREIGN_APPEAL)

        home.update(
            {
                "home_registration_id": home_reg["id"],
                "home_player_id": home_player["id"],
                "away_tier_id": away["tier_id"],
                "away_player_id": away_player["id"],
                "away_item_id": away_item["id"],
            }
        )
        return home

    def test_a_tier_a_player_and_a_receipt_subject_from_another_outing_are_refused(self, api):
        """All three references resolve, so the 404 tier is satisfied and only the same-outing
        rule can speak: "every row named by one request belongs to the same outing,
        otherwise `ERR_CROSS_OUTING_REFERENCE` (HTTP 409). This governs a registration and
        its tier, a team and its players, an allocation's registration and its asset, a
        contest winner's player row, and a receipt's subject."  The receipt case is
        reported ahead of any complaint about the imported item's own status, because that
        tier sits above the state precondition.

        Design: Corner/endpoints/a_cross_reference_must_name_rows_that_live_in_the_same_outing
        """
        ctx = self._two_peopled_outings(api)

        validate_error(
            api.create_registration(
                f.registration_payload(
                    ctx["outing_id"], ctx["away_tier_id"], buyer_name="Wrong Tier Buyer",
                    player_count=1,
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.CROSS_OUTING_REFERENCE,
            409,
        )

        validate_error(
            api.create_team(
                f.team_payload(
                    ctx["outing_id"], [ctx["away_player_id"]], team_name="Imported Player"
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.CROSS_OUTING_REFERENCE,
            409,
        )
        assert fx.read_player(api, ctx["away_player_id"])["team_id"] is None

        validate_error(
            api.create_receipt(
                f.item_receipt_payload(ctx["outing_id"], ctx["away_item_id"]),
                TREASURER_HEADERS,
            ),
            ApiErrorId.CROSS_OUTING_REFERENCE,
            409,
        )

    def test_the_refusals_created_nothing_and_the_local_grouping_still_works(self, api):
        """A rejected write leaves no row behind, so the outing's own collection is unchanged
        while the local grouping succeeds and "derives the team's `player_count` as the
        count of players pointing at it".

        Design: Corner/endpoints/a_cross_reference_must_name_rows_that_live_in_the_same_outing
        """
        ctx = self._two_peopled_outings(api)
        validate_error(
            api.create_registration(
                f.registration_payload(
                    ctx["outing_id"], ctx["away_tier_id"], buyer_name="Wrong Tier Buyer",
                    player_count=1,
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.CROSS_OUTING_REFERENCE,
            409,
        )

        team = validate_success(
            api.create_team(
                f.team_payload(
                    ctx["outing_id"], [ctx["home_player_id"]], team_name="Home Single"
                ),
                DIRECTOR_HEADERS,
            ),
            201,
        )
        assert team["player_count"] == 1
        assert fx.read_player(api, ctx["home_player_id"])["team_id"] == team["id"]

        _, meta = validate_paginated(
            api.list_registrations(TREASURER_HEADERS, outing_id=ctx["outing_id"])
        )
        assert meta["total_count"] == 1


CLOCK_START = "2026-08-01T00:00:00Z"
CONDITIONAL_ONE = {
    "name": "Conditional Open One",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}
CONDITIONAL_TWO = {
    "name": "Conditional Open Two",
    "beneficiary_name": "Southside Literacy Trust",
    "scheduled_date": "2026-09-26T12:00:00Z",
    "wave_a_start": "2026-09-26T12:00:00Z",
    "wave_a_end": "2026-09-26T16:30:00Z",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}


class TestOpeningRegistrationIsConditional:
    def _a_draft_outing_with_a_draft_contract(self, api):
        fx.set_clock(api, CLOCK_START)
        outing = fx.new_outing(api, **CONDITIONAL_ONE)
        contract = fx.new_contract(api, outing["id"], **NO_GUARANTEE)
        return {"outing_id": outing["id"], "contract_id": contract["id"]}

    def test_the_contract_precondition_is_reported_before_the_missing_tier(self, api):
        """Two preconditions guard one edge and the PRD declares them in order: "Opening
        registration moves the outing `DRAFT → OPEN`, and it has two preconditions: the
        outing must have a contract whose status is `SIGNED` or `AMENDED`", "and the outing
        must already have at least one package tier, otherwise `ERR_NO_PACKAGE_TIER`".
        Both are violated at the start, so the contract complaint wins; signing, which
        "moves the contract from `DRAFT` to `SIGNED` and stamps `signed_at` from the
        logical clock", lets the second one surface.

        Design: Corner/endpoints/opening_registration_is_conditional_on_a_signed_contract_and_at_least_one_tier
        """
        ctx = self._a_draft_outing_with_a_draft_contract(api)

        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("OPEN_REGISTRATION"),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.CONTRACT_NOT_SIGNED,
            409,
        )

        signed = validate_success(
            api.contract_lifecycle(
                ctx["contract_id"], f.contract_lifecycle_payload("SIGN"), COURSE_HEADERS
            )
        )
        assert signed["status"] == "SIGNED"
        assert_instant_equals(signed["signed_at"], CLOCK_START)

        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("OPEN_REGISTRATION"),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.NO_PACKAGE_TIER,
            409,
        )
        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "DRAFT"

        fx.new_tier(api, ctx["outing_id"], **SOLO_TIER)
        opened = fx.open_registration(api, ctx["outing_id"])
        assert opened["play_status"] == "OPEN"
        assert opened["finance_status"] == "COLLECTING"

    def test_the_action_is_not_idempotent_and_a_missing_contract_fails_the_same_way(self, api):
        """`OPEN_REGISTRATION` is an edge out of `DRAFT` and out of `FIELD_LOCKED` only, and
        the state tier refuses anything else: "the requested action is a declared edge out
        of the target row's current state in the relevant lifecycle, including the parallel
        dimensions carried by outings and contests, otherwise
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)".  An outing with no contract row at all
        is not a 404 either, because "an outing with no contract at all fails the same
        check with `ERR_CONTRACT_NOT_SIGNED`".

        Design: Corner/endpoints/opening_registration_is_conditional_on_a_signed_contract_and_at_least_one_tier
        """
        ctx = self._a_draft_outing_with_a_draft_contract(api)
        fx.sign_contract(api, ctx["contract_id"])
        fx.new_tier(api, ctx["outing_id"], **SOLO_TIER)
        fx.open_registration(api, ctx["outing_id"])

        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("OPEN_REGISTRATION"),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )
        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "OPEN"

        bare = fx.new_outing(api, **CONDITIONAL_TWO)
        validate_error(
            api.play_transition(
                bare["id"], f.play_transition_payload("OPEN_REGISTRATION"), DIRECTOR_HEADERS
            ),
            ApiErrorId.CONTRACT_NOT_SIGNED,
            409,
        )
        assert fx.read_outing(api, bare["id"])["play_status"] == "DRAFT"
