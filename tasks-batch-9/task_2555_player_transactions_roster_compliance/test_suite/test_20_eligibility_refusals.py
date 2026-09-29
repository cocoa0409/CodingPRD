"""Who and what may take part: the two-party rule and the rights class."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_RESTRICTED_RIGHTS_REQUIRED,
    ERR_TRADE_SAME_TEAM,
)
from test_helpers.fixtures import League
from test_helpers.test_users import make_cap_analyst_headers

CLOCK = "2026-08-10T14:00:00Z"


class TestATradeAClubOffersItself:
    """The actor represents the club named on both sides, and that is the problem."""

    def test_naming_one_club_twice_on_a_trade_is_refused(
        self, league: League
    ) -> None:
        """Existence and authorisation both pass; only the two-party rule fails.

        PRD 3.7: "The acting identifier must equal `initiating_team_id`, both clubs must
        exist, both must have a posture that is neither `NON_COMPLIANT` nor
        `TRANSACTION_FROZEN`, and the two must be distinct — naming the same club twice
        is `ERR_TRADE_SAME_TEAM`."

        PRD 3.7: "A trade is a negotiation between exactly two clubs, and it is the only
        place in this system where two clubs act on the same record in alternation."

        Design: Corner/errors/a_trade_between_a_club_and_itself_is_refused
        """
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        assert club["compliance_status"] == "COMPLIANT", (
            "the club's posture is no obstacle to opening a trade, got "
            f"{club['compliance_status']}"
        )

        response = league.api.create_trade(
            fac.trade_payload(club["id"], club["id"], "NONE"),
            make_cap_analyst_headers(club["id"]),
        )
        validate_error(response, ERR_TRADE_SAME_TEAM, 422)

        trades, meta = validate_paginated(league.api.list_trades(league.officer))
        assert meta["total_count"] == 0, (
            f"no trade should have been opened, got {meta['total_count']}"
        )
        assert trades == [], f"the trade list should be empty, got {trades}"

    def test_the_refused_trade_leaves_the_club_untouched(
        self, league: League
    ) -> None:
        """A freshly registered club is still at version 1 and still compliant.

        PRD 2.9: "If any precondition fails, nothing is written at all."

        PRD 3.1: "A freshly registered club starts with every headcount and every money
        total at zero, `cap_space_cents` equal to its `salary_cap_limit_cents`, and a
        `compliance_status` of `COMPLIANT`."

        Design: Corner/errors/a_trade_between_a_club_and_itself_is_refused
        """
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )

        league.api.create_trade(
            fac.trade_payload(club["id"], club["id"], "NONE"),
            make_cap_analyst_headers(club["id"]),
        )

        after = league.club(club["id"])
        assert after["version"] == 1, (
            f"the refused trade bumped no version, got {after['version']}"
        )
        assert after["compliance_status"] == "COMPLIANT", (
            f"and cost the club no standing, got {after['compliance_status']}"
        )
        assert after["cap_space_cents"] == 500_000_000, (
            f"its whole cap is still free, got {after['cap_space_cents']}"
        )


class TestATenderForAPlayerWithoutRestrictedRights:
    """Zero accrued days means no rights to keep, so there is nothing to tender."""

    def test_tendering_an_unproven_player_is_refused(self, league: League) -> None:
        """The pair is free of other offers, so the rights class is what answers.

        PRD 3.2: "`service_years` is the floor of `pension_credit_days` divided by 170
        days per season, and it selects the player's `contract_rights_class`:
        `UNRESTRICTED` at 4 or more service years, `ARBITRATION_ELIGIBLE` at exactly 3,
        `RESTRICTED` at 1 or 2, and `NONE` at 0."

        PRD 3.8: "The club must not be `NON_COMPLIANT` or `TRANSACTION_FROZEN`; the
        player must currently be `UNROSTERED`; the player's `medical_status` must not be
        `FAILED_PHYSICAL`; the player's `contract_rights_class` must be `RESTRICTED` or
        `ARBITRATION_ELIGIBLE`, and an `ARBITRATION_TENDER` specifically requires
        `ARBITRATION_ELIGIBLE`, with any other rights class refused as
        `ERR_RESTRICTED_RIGHTS_REQUIRED`; and the same club-and-player pair may not
        already hold an `ISSUED` tender, which would be `ERR_TENDER_ALREADY_ISSUED`."

        Design: Corner/errors/tendering_a_player_who_holds_no_restricted_rights_is_refused
        """
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        player = league.register_player(full_name="Noel Prine", position="WR")

        assert player["service_years"] == 0, (
            f"an unproven player has served no seasons, got {player['service_years']}"
        )
        assert player["contract_rights_class"] == "NONE", (
            "and therefore holds no rights the club could keep, got "
            f"{player['contract_rights_class']}"
        )
        assert player["roster_designation"] == "UNROSTERED", (
            "he is nevertheless unrostered, which the eligibility rule requires, got "
            f"{player['roster_designation']}"
        )

        response = league.api.create_tender(
            fac.tender_payload(
                player["id"], club["id"], "RESTRICTED_TENDER", "FIRST_ROUND",
                50_000_000,
            ),
            make_cap_analyst_headers(club["id"]),
        )
        validate_error(response, ERR_RESTRICTED_RIGHTS_REQUIRED, 422)

    def test_the_refused_tender_costs_the_club_no_cap_room(
        self, league: League
    ) -> None:
        """The rights test sits above the cap test, so no money was ever committed.

        PRD 2.8: "A tender targets a player whose `contract_rights_class` is
        `RESTRICTED` or `ARBITRATION_ELIGIBLE`, and an `ARBITRATION_TENDER` targets only
        a player who is `ARBITRATION_ELIGIBLE` — otherwise
        `ERR_RESTRICTED_RIGHTS_REQUIRED` (422)."

        PRD 3.8: "Issuing a tender is also subject to the provisional cap ceiling and
        can be refused with `ERR_CAP_LIMIT_EXCEEDED`."

        Design: Corner/errors/tendering_a_player_who_holds_no_restricted_rights_is_refused
        """
        league.set_clock(CLOCK)
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        player = league.register_player(full_name="Noel Prine", position="WR")

        league.api.create_tender(
            fac.tender_payload(
                player["id"], club["id"], "RESTRICTED_TENDER", "FIRST_ROUND",
                50_000_000,
            ),
            make_cap_analyst_headers(club["id"]),
        )

        tenders, meta = validate_paginated(league.api.list_tenders(league.officer))
        assert meta["total_count"] == 0, (
            f"no tender should have been issued, got {meta['total_count']}"
        )
        assert tenders == [], f"the tender list should be empty, got {tenders}"

        after = league.club(club["id"])
        assert after["provisional_cap_committed_cents"] == 0, (
            "the club committed nothing, got "
            f"{after['provisional_cap_committed_cents']}"
        )
        assert after["cap_space_cents"] == 500_000_000, (
            f"so its whole cap is still free, got {after['cap_space_cents']}"
        )
