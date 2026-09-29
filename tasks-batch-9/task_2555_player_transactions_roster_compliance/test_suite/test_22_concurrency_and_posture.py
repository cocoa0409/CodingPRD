"""Stale parents and the posture ladder: the guards time and versions impose."""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_STALE_CONTRACT_VERSION,
    ERR_STALE_TEAM_VERSION,
    ERR_STALE_TRADE_VERSION,
)
from test_helpers.fixtures import League
from test_helpers.test_users import make_cap_analyst_headers

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"

TERMS = {
    "years": 3,
    "base_salary_cents": 80_000_000,
    "signing_bonus_cents": 10_000_000,
    "start_season_year": 2026,
}
SMALL_TERMS = {
    "years": 1,
    "base_salary_cents": 12_000_000,
    "signing_bonus_cents": 0,
    "start_season_year": 2026,
}


def _club(league: League, **overrides: Any) -> Dict[str, Any]:
    """One club with room to spare."""
    defaults = {
        "name": "Harbor Kings", "market_code": "HKG",
        "salary_cap_limit_cents": 500_000_000, "waiver_priority_rank": 1,
    }
    return league.register_club(**{**defaults, **overrides})


class TestAStaleClubVersionOnFilingCreation:
    """Two drafts are legal; a writer who has not re-read the club is not.

    PRD 2.6: "A club may legitimately hold several `DRAFT` filings for the same
    player and the same designation at once — the second create observes no state
    field that the first create changed, so no state-machine or business rule would
    refuse it."
    """

    @staticmethod
    def _one_draft_already_filed_against_version_one(
        league: League
    ) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = _club(league)
        first_player = league.register_player(full_name="Ray Alder", position="QB")
        second_player = league.register_player(full_name="Milo Sarr", position="WR")
        first = league.open_signing(
            club["id"], first_player["id"],
            expected_team_version=club["version"], **TERMS
        )
        return {
            "club": club,
            "stale_version": club["version"],
            "second_player": second_player,
            "first_filing_id": first["id"],
        }

    def test_a_second_create_carrying_the_superseded_version_is_refused(
        self, league: League
    ) -> None:
        """The first create moved the club's version and its provisional total.

        PRD 2.6: "If `expected_team_version` does not equal the club's current
        `version`, the request is rejected with `ERR_STALE_TEAM_VERSION` (HTTP 412)."

        PRD 3.3: "Creating any filing increments the club's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/filing_creation_rejects_a_stale_club_version_and_admits_the_refreshed_one
        """
        world = self._one_draft_already_filed_against_version_one(league)

        club = league.club(world["club"]["id"])
        assert club["version"] == 2, (
            f"the first filing advanced the club to version 2, got {club['version']}"
        )
        assert club["provisional_cap_committed_cents"] == 83_333_333, (
            "and its pending contract to the provisional total, got "
            f"{club['provisional_cap_committed_cents']}"
        )

        response = league.api.create_transaction(
            fac.signing_payload(
                world["club"]["id"], world["second_player"]["id"],
                world["stale_version"], **SMALL_TERMS
            ),
            make_cap_analyst_headers(world["club"]["id"]),
        )
        validate_error(response, ERR_STALE_TEAM_VERSION, 412)

        filings, meta = validate_paginated(
            league.api.list_transactions(league.officer)
        )
        assert meta["total_count"] == 1, (
            f"only the first filing should exist, got {meta['total_count']}"
        )
        assert filings[0]["id"] == world["first_filing_id"], (
            f"and it should be that first one, got {filings[0]['id']}"
        )

    def test_the_identical_create_succeeds_on_the_refreshed_version(
        self, league: League
    ) -> None:
        """Re-reading the club is the whole remedy; the body never changes.

        PRD 3.3: "That is the moment a not-yet-approved contract begins consuming
        provisional cap space, which is why a `SIGNING` create is itself subject to the
        provisional cap ceiling and can be refused with `ERR_CAP_LIMIT_EXCEEDED`."

        Design: Corner/cross_cutting_complexity_layers/filing_creation_rejects_a_stale_club_version_and_admits_the_refreshed_one
        """
        world = self._one_draft_already_filed_against_version_one(league)
        league.api.create_transaction(
            fac.signing_payload(
                world["club"]["id"], world["second_player"]["id"],
                world["stale_version"], **SMALL_TERMS
            ),
            make_cap_analyst_headers(world["club"]["id"]),
        )

        refreshed = league.version_of(world["club"]["id"])
        second = get_success_data(
            league.api.create_transaction(
                fac.signing_payload(
                    world["club"]["id"], world["second_player"]["id"],
                    refreshed, **SMALL_TERMS
                ),
                make_cap_analyst_headers(world["club"]["id"]),
            ),
            201,
        )
        assert second["status"] == "DRAFT", (
            f"the retry is admitted as a draft, got {second['status']}"
        )

        club = league.club(world["club"]["id"])
        assert club["version"] == 3, (
            f"the accepted create advanced the club again, got {club['version']}"
        )
        assert club["provisional_cap_committed_cents"] == 95_333_333, (
            "83,333,333 plus the second draft's 12,000,000 charge, got "
            f"{club['provisional_cap_committed_cents']}"
        )


class TestAStaleClaimingClubVersion:
    """The wire never moved; the claiming club's own books did.

    PRD 2.6: "The claim captures a snapshot of that club's waiver priority rank and
    cap space, and a club may legitimately hold claims on several wires
    simultaneously, so a repeated submit sees identical waiver-request state and
    would otherwise succeed."
    """

    @staticmethod
    def _wire_and_a_claimant_whose_version_moved(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        releasing = _club(league)
        claiming = _club(
            league, name="Basin Otters", market_code="BSN", waiver_priority_rank=2,
        )
        wired = league.register_player(full_name="Ray Alder", position="QB")
        own_target = league.register_player(full_name="Milo Sarr", position="WR")
        league.sign_onto_roster(
            releasing["id"], wired["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=releasing["version"], **TERMS,
        )
        released = league.release_onto_wire(releasing["id"], wired["id"])
        league.open_signing(
            claiming["id"], own_target["id"],
            expected_team_version=claiming["version"], **SMALL_TERMS
        )
        return {
            "releasing": releasing,
            "claiming": claiming,
            "stale_version": claiming["version"],
            "wire_id": released["waiver_request_id"],
        }

    def test_a_claim_carrying_the_superseded_club_version_is_refused(
        self, league: League
    ) -> None:
        """An unrelated filing of the claimant's own is what made it stale.

        PRD 2.6: "Rejecting on a stale team version is what prevents a claim from being
        ranked and cap-tested against a club snapshot that has since been superseded."

        PRD 2.6: "The rejection is `ERR_STALE_TEAM_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/claim_submission_rejects_a_stale_claiming_club_version
        """
        world = self._wire_and_a_claimant_whose_version_moved(league)

        wire_before = league.wire(world["wire_id"])
        assert wire_before["status"] == "PENDING", (
            f"the wire is claimable throughout, got {wire_before['status']}"
        )
        assert league.version_of(world["claiming"]["id"]) == 2, (
            "the claimant's own draft filing moved its version, got "
            f"{league.version_of(world['claiming']['id'])}"
        )

        response = league.api.submit_waiver_claim(
            world["wire_id"],
            fac.waiver_claim_payload(
                world["claiming"]["id"], world["stale_version"]
            ),
            make_cap_analyst_headers(world["claiming"]["id"]),
        )
        validate_error(response, ERR_STALE_TEAM_VERSION, 412)

        claims, meta = validate_paginated(
            league.api.list_waiver_claims(league.officer)
        )
        assert meta["total_count"] == 0, (
            f"no claim should have been recorded, got {meta['total_count']}"
        )
        assert claims == [], f"the claim list should be empty, got {claims}"

        wire = league.wire(world["wire_id"])
        assert wire["claim_count"] == 0, (
            f"and the wire counts none, got {wire['claim_count']}"
        )

    def test_the_retry_snapshots_the_refreshed_club(self, league: League) -> None:
        """The accepted claim captures the rank and charge the league will use.

        PRD 3.6: "`priority_rank_snapshot` copies the claiming club's
        `waiver_priority_rank` and is the ranking key the award pipeline uses."

        PRD 3.6: "`required_cap_charge_cents` is the `base_salary_cents` of the wired
        contract, that is, the charge the claiming club would assume."

        PRD 3.6: "Submitting a claim increments the wire's `claim_count` and the
        claiming club's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/claim_submission_rejects_a_stale_claiming_club_version
        """
        world = self._wire_and_a_claimant_whose_version_moved(league)
        league.api.submit_waiver_claim(
            world["wire_id"],
            fac.waiver_claim_payload(
                world["claiming"]["id"], world["stale_version"]
            ),
            make_cap_analyst_headers(world["claiming"]["id"]),
        )

        refreshed = league.version_of(world["claiming"]["id"])
        claim = league.submit_claim(
            world["wire_id"], world["claiming"]["id"],
            expected_team_version=refreshed,
        )
        assert claim["status"] == "SUBMITTED", (
            f"the retry is admitted, got {claim['status']}"
        )
        assert claim["priority_rank_snapshot"] == 2, (
            f"carrying the claimant's rank, got {claim['priority_rank_snapshot']}"
        )
        assert claim["required_cap_charge_cents"] == 80_000_000, (
            "and the wired contract's base salary as the charge it would assume, got "
            f"{claim['required_cap_charge_cents']}"
        )

        claiming = league.club(world["claiming"]["id"])
        assert claiming["version"] == refreshed + 1, (
            f"the accepted claim bumped the club again, got {claiming['version']}"
        )


class TestAStaleTradeVersion:
    """A second asset on the same side is legal; not having seen the deltas is not.

    PRD 2.6: "A trade accepts any number of assets on either side, so a second add
    observes the same trade status and would legitimately succeed; the stale version is
    the only signal that the writer has not seen the cap deltas recomputed by the
    previously added asset, or the counter that flipped which club is now allowed to
    add."
    """

    @staticmethod
    def _a_trade_whose_deltas_have_already_moved(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        initiating = _club(league)
        counterparty = _club(
            league, name="Basin Otters", market_code="BSN", waiver_priority_rank=2,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        signing = league.sign_onto_roster(
            initiating["id"], player["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=initiating["version"], **TERMS,
        )
        trade = league.build_trade(initiating["id"], counterparty["id"])
        stale_version = trade["version"]
        league.offer_contract(
            trade["id"], initiating["id"], signing["contract_id"],
            "TO_COUNTERPARTY", expected_trade_version=stale_version,
        )
        return {
            "initiating": initiating,
            "trade_id": trade["id"],
            "stale_version": stale_version,
        }

    def test_a_pick_added_on_the_superseded_version_is_refused(
        self, league: League
    ) -> None:
        """The contract asset that moved the deltas also moved the trade.

        PRD 3.7: "The asset is born `PROPOSED` and every addition re-derives both clubs'
        cap deltas and increments the trade's `version`."

        PRD 2.6: "The rejection is `ERR_STALE_TRADE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/asset_admission_rejects_a_stale_trade_version
        """
        world = self._a_trade_whose_deltas_have_already_moved(league)

        trade = league.trade(world["trade_id"])
        assert trade["version"] == world["stale_version"] + 1, (
            f"the contract asset advanced the trade, got {trade['version']}"
        )
        assert trade["cap_delta_initiating_cents"] == -83_333_333, (
            "and sent the sender's own charge away, got "
            f"{trade['cap_delta_initiating_cents']}"
        )

        response = league.api.add_trade_asset(
            world["trade_id"],
            fac.draft_pick_asset_payload(
                "TO_COUNTERPARTY", world["stale_version"]
            ),
            make_cap_analyst_headers(world["initiating"]["id"]),
        )
        validate_error(response, ERR_STALE_TRADE_VERSION, 412)

        assets, meta = validate_paginated(
            league.api.list_trade_assets(world["trade_id"], league.officer)
        )
        assert meta["total_count"] == 1, (
            f"only the contract asset should be on the table, got "
            f"{meta['total_count']}"
        )
        assert assets[0]["asset_kind"] == "CONTRACT", (
            f"and it should be that contract, got {assets[0]['asset_kind']}"
        )

    def test_the_pick_lands_on_the_refreshed_version_and_moves_nothing(
        self, league: League
    ) -> None:
        """A pick is worth nothing to either cap, but it still bumps the trade.

        PRD 3.7: "and for a `DRAFT_PICK` asset it is 0."

        PRD 3.7: "Because every asset is directed at exactly one club, the two deltas
        are always exact negations of one another."

        Design: Corner/cross_cutting_complexity_layers/asset_admission_rejects_a_stale_trade_version
        """
        world = self._a_trade_whose_deltas_have_already_moved(league)
        league.api.add_trade_asset(
            world["trade_id"],
            fac.draft_pick_asset_payload(
                "TO_COUNTERPARTY", world["stale_version"]
            ),
            make_cap_analyst_headers(world["initiating"]["id"]),
        )

        refreshed = league.trade(world["trade_id"])["version"]
        pick = league.offer_draft_pick(
            world["trade_id"], world["initiating"]["id"], "TO_COUNTERPARTY",
            expected_trade_version=refreshed,
        )
        assert pick["cap_charge_snapshot_cents"] == 0, (
            f"a pick snapshots nothing, got {pick['cap_charge_snapshot_cents']}"
        )
        assert pick["status"] == "PROPOSED", (
            f"and is born proposed, got {pick['status']}"
        )

        trade = league.trade(world["trade_id"])
        assert trade["version"] == refreshed + 1, (
            f"the accepted add advanced the trade again, got {trade['version']}"
        )
        assert trade["status"] == "PROPOSED", (
            f"which is still the club's own turn to be answered, got "
            f"{trade['status']}"
        )
        assert trade["cap_delta_initiating_cents"] == -83_333_333, (
            "the pick left the initiator's delta alone, got "
            f"{trade['cap_delta_initiating_cents']}"
        )
        assert trade["cap_delta_counterparty_cents"] == 83_333_333, (
            "and the counterparty's is its exact negation, got "
            f"{trade['cap_delta_counterparty_cents']}"
        )

        _, meta = validate_paginated(
            league.api.list_trade_assets(world["trade_id"], league.officer)
        )
        assert meta["total_count"] == 2, (
            f"both assets are on the table, got {meta['total_count']}"
        )


class TestAStaleContractVersion:
    """The option decision is guarded by the contract the client last read.

    PRD 2.6: "A `POST /contracts/{id}/option-decision` request must carry
    `expected_contract_version` matching the contract's current `Contract.version`; a
    mismatch is `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."
    """

    @staticmethod
    def _an_option_read_before_the_contract_activated(
        league: League
    ) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        filing = league.open_signing(
            club["id"], player["id"],
            expected_team_version=club["version"],
            option_type="TEAM_OPTION",
            option_deadline_at="2026-12-01T14:00:00Z",
            option_salary_cents=40_000_000,
            **TERMS,
        )
        offered = league.contract(filing["contract_id"])
        league.pass_entry_physical(
            club["id"], player["id"], filing["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END,
            performed_at=CLOCK,
        )
        league.submit_filing(filing["id"], club["id"])
        league.approve_filing(filing["id"])
        return {
            "club": club,
            "player": player,
            "contract_id": filing["contract_id"],
            "stale_version": offered["version"],
        }

    def test_the_version_read_before_approval_no_longer_decides(
        self, league: League
    ) -> None:
        """Activation is what armed the option and what invalidated the read.

        PRD 3.3: "A `SIGNING` create additionally builds the offered contract
        immediately — a `PENDING_APPROVAL` contract linked back through
        `signed_via_transaction_id`, with the filing's own `contract_id` pointing forward
        at it — computes that contract's proration schedule and current-season charge as
        §3.4 describes, and re-derives the club's provisional commitment and cap space."

        PRD 3.4: "It begins `NOT_APPLICABLE`, and moves to `PENDING` at the moment the
        contract activates *if* the contract carries an option — that is, if
        `option_type` is `TEAM_OPTION` or `PLAYER_OPTION`, in which case both
        `option_deadline_at` and `option_salary_cents` are required and the latter may
        not be negative."

        Design: Corner/cross_cutting_complexity_layers/option_decision_rejects_a_stale_contract_version
        """
        world = self._an_option_read_before_the_contract_activated(league)

        contract = league.contract(world["contract_id"])
        assert contract["status"] == "ACTIVE", (
            f"the approval activated the contract, got {contract['status']}"
        )
        assert contract["option_status"] == "PENDING", (
            f"and armed its option dimension, got {contract['option_status']}"
        )
        assert contract["version"] > world["stale_version"], (
            "leaving the pre-approval read behind, got "
            f"{contract['version']} against {world['stale_version']}"
        )

        response = league.api.decide_option(
            world["contract_id"],
            fac.option_decision_payload("EXERCISE", world["stale_version"]),
            make_cap_analyst_headers(world["club"]["id"]),
        )
        validate_error(response, ERR_STALE_CONTRACT_VERSION, 412)

        untouched = league.contract(world["contract_id"])
        assert untouched["option_status"] == "PENDING", (
            f"the option is still undecided, got {untouched['option_status']}"
        )
        assert untouched["base_salary_cents"] == 80_000_000, (
            "and the original base salary stands, got "
            f"{untouched['base_salary_cents']}"
        )

    def test_the_refreshed_version_exercises_the_option(
        self, league: League
    ) -> None:
        """One re-read is all the retry needs; the decision itself is unchanged.

        PRD 3.4: "An `EXERCISE` decision moves `option_status` `PENDING → EXERCISED`,
        replaces `base_salary_cents` with `option_salary_cents`, adds one to `years`,
        then recomputes the contract's current-season charge and the owning club's cap
        fields."

        PRD 3.4: "Either branch increments the contract's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/option_decision_rejects_a_stale_contract_version
        """
        world = self._an_option_read_before_the_contract_activated(league)
        league.api.decide_option(
            world["contract_id"],
            fac.option_decision_payload("EXERCISE", world["stale_version"]),
            make_cap_analyst_headers(world["club"]["id"]),
        )

        refreshed = league.contract(world["contract_id"])["version"]
        decided = league.decide_option(
            world["contract_id"], "EXERCISE",
            make_cap_analyst_headers(world["club"]["id"]),
            expected_contract_version=refreshed,
        )
        assert decided["option_status"] == "EXERCISED", (
            f"the retry resolves the option, got {decided['option_status']}"
        )
        assert decided["base_salary_cents"] == 40_000_000, (
            f"the option salary takes over, got {decided['base_salary_cents']}"
        )
        assert decided["years"] == 4, (
            f"and the deal runs one season longer, got {decided['years']}"
        )
        assert decided["status"] == "ACTIVE", (
            f"an exercise keeps the contract alive, got {decided['status']}"
        )
        assert decided["version"] == refreshed + 1, (
            f"and bumps the contract once, got {decided['version']}"
        )

        assert league.player(world["player"]["id"])["roster_designation"] == "ACTIVE", (
            "the player stays on the active roster, got "
            f"{league.player(world['player']['id'])['roster_designation']}"
        )


class TestThePostureLadderClimbsAtItsDeclaredBoundaries:
    """One unfiled form, five sweeps, and every rung the league declares.

    PRD 3.9: "`UNFILED_INJURY_PAPERWORK`, when any injury designation of this club is
    still in `PENDING_PAPERWORK` and the logical clock has reached or passed that
    designation's `created_at` plus a 24-hour paperwork grace period."
    """

    @staticmethod
    def _one_designation_nobody_files(league: League) -> Dict[str, Any]:
        league.set_clock(CLOCK)
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        league.sign_onto_roster(
            club["id"], player["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=club["version"], **TERMS,
        )
        designation = league.open_injury_designation(club["id"], player["id"])
        return {"club": club, "player": player, "designation": designation}

    @staticmethod
    def _sweep_at(league: League, team_id: str, moment: str) -> Dict[str, Any]:
        league.set_clock(moment)
        return league.run_sweep(team_id)

    def test_the_first_two_sweeps_straddle_the_paperwork_grace_boundary(
        self, league: League
    ) -> None:
        """One second before the day is up the club is clean; on the instant it is not.

        PRD 3.9: "An empty list means the club is compliant."

        PRD 3.9: "From `COMPLIANT`, a non-empty violation list moves the club to `GRACE`,
        arming `grace_expires_at` at the evaluation instant plus a 24-hour grace period
        and setting `consecutive_noncompliant_checks` to 1."

        Design: Corner/cross_cutting_complexity_layers/the_compliance_posture_ladder_climbs_only_at_its_declared_boundaries
        """
        world = self._one_designation_nobody_files(league)
        assert world["designation"]["status"] == "PENDING_PAPERWORK", (
            "the designation is born awaiting its form, got "
            f"{world['designation']['status']}"
        )
        assert world["designation"]["minimum_stay_days"] == 21, (
            "an injured-reserve designation stays 21 days, got "
            f"{world['designation']['minimum_stay_days']}"
        )

        early = self._sweep_at(
            league, world["club"]["id"], "2026-08-11T13:59:59Z"
        )
        assert early["violation_codes"] == [], (
            f"a second short of the day, nothing is wrong, got "
            f"{early['violation_codes']}"
        )
        assert early["result"] == "COMPLIANT", (
            f"so the sweep reports a clean club, got {early['result']}"
        )
        assert early["resulting_compliance_status"] == "COMPLIANT", (
            "and leaves the posture where it was, got "
            f"{early['resulting_compliance_status']}"
        )
        assert early["grace_expires_at"] is None, (
            f"with no grace armed, got {early['grace_expires_at']}"
        )

        armed = self._sweep_at(
            league, world["club"]["id"], "2026-08-11T14:00:00Z"
        )
        assert armed["violation_codes"] == ["UNFILED_INJURY_PAPERWORK"], (
            "on the instant the day is up the gap is a violation, got "
            f"{armed['violation_codes']}"
        )
        assert armed["result"] == "GRACE", (
            f"the club's first violation only arms grace, got {armed['result']}"
        )
        assert armed["grace_expires_at"] == "2026-08-12T14:00:00.000Z", (
            "a further 24 hours from the evaluation instant, got "
            f"{armed['grace_expires_at']}"
        )

        club = league.club(world["club"]["id"])
        assert club["compliance_status"] == "GRACE", (
            f"the club now holds that posture, got {club['compliance_status']}"
        )
        assert club["consecutive_noncompliant_checks"] == 1, (
            f"counted as the first failing check, got "
            f"{club['consecutive_noncompliant_checks']}"
        )

    def test_the_ladder_stalls_inside_grace_then_climbs_to_frozen(
        self, league: League
    ) -> None:
        """Grace holds until its own expiry instant, then two rungs in two sweeps.

        PRD 3.9: "A sweep that finds violations while the club is in `GRACE` and the
        logical clock is still strictly before `grace_expires_at` leaves the club in
        `GRACE`, with `grace_expires_at` and `consecutive_noncompliant_checks` both
        unchanged."

        PRD 3.9: "A sweep that finds violations while the club is in `GRACE` and the
        logical clock has reached or passed `grace_expires_at` moves the club `GRACE →
        NON_COMPLIANT` — the boundary instant already counts as expired — clears
        `grace_expires_at` to null, and sets `consecutive_noncompliant_checks` to 2; from
        this point every team-scoped write is refused."

        PRD 3.9: "A sweep that finds violations while the club is `NON_COMPLIANT` moves
        it `NON_COMPLIANT → TRANSACTION_FROZEN` when the counter incremented by one
        reaches or exceeds the freeze threshold of 3, and it increments
        `consecutive_noncompliant_checks`."

        Design: Corner/cross_cutting_complexity_layers/the_compliance_posture_ladder_climbs_only_at_its_declared_boundaries
        """
        world = self._one_designation_nobody_files(league)
        club_id = world["club"]["id"]
        self._sweep_at(league, club_id, "2026-08-11T13:59:59Z")
        self._sweep_at(league, club_id, "2026-08-11T14:00:00Z")

        held = self._sweep_at(league, club_id, "2026-08-12T13:59:59Z")
        assert held["resulting_compliance_status"] == "GRACE", (
            "strictly before its expiry, grace holds, got "
            f"{held['resulting_compliance_status']}"
        )
        in_grace = league.club(club_id)
        assert in_grace["grace_expires_at"] == "2026-08-12T14:00:00.000Z", (
            f"the armed expiry is not re-armed, got {in_grace['grace_expires_at']}"
        )
        assert in_grace["consecutive_noncompliant_checks"] == 1, (
            "and the counter does not move either, got "
            f"{in_grace['consecutive_noncompliant_checks']}"
        )

        expired = self._sweep_at(league, club_id, "2026-08-12T14:00:00Z")
        assert expired["result"] == "NON_COMPLIANT", (
            f"the boundary instant already counts as expired, got "
            f"{expired['result']}"
        )
        assert expired["grace_expires_at"] is None, (
            f"and the sweep armed no new grace, got {expired['grace_expires_at']}"
        )
        fallen = league.club(club_id)
        assert fallen["compliance_status"] == "NON_COMPLIANT", (
            f"the club has fallen a rung, got {fallen['compliance_status']}"
        )
        assert fallen["grace_expires_at"] is None, (
            f"its grace is cleared, got {fallen['grace_expires_at']}"
        )
        assert fallen["consecutive_noncompliant_checks"] == 2, (
            f"and the counter is set to two, got "
            f"{fallen['consecutive_noncompliant_checks']}"
        )

        frozen_row = self._sweep_at(league, club_id, "2026-08-12T14:00:00Z")
        assert frozen_row["resulting_compliance_status"] == "TRANSACTION_FROZEN", (
            "the third failing check reaches the freeze threshold, got "
            f"{frozen_row['resulting_compliance_status']}"
        )
        frozen = league.club(club_id)
        assert frozen["compliance_status"] == "TRANSACTION_FROZEN", (
            f"so the club is frozen, got {frozen['compliance_status']}"
        )
        assert frozen["consecutive_noncompliant_checks"] == 3, (
            f"on its third consecutive failure, got "
            f"{frozen['consecutive_noncompliant_checks']}"
        )

        history = league.sweep_history(club_id)
        assert len(history) == 5, (
            f"every sweep left an audit row, got {len(history)}"
        )
        for row in history:
            assert row["active_roster_count"] == 1, (
                "no sweep moved the roster it observed, got "
                f"{row['active_roster_count']}"
            )
            assert row["final_cap_committed_cents"] == 83_333_333, (
                "nor the settled money, got "
                f"{row['final_cap_committed_cents']}"
            )
            assert row["cap_space_cents"] == 416_666_667, (
                "and the audit view measures space against that settled total, got "
                f"{row['cap_space_cents']}"
            )

        stale = league.designation(world["designation"]["id"])
        assert stale["status"] == "PENDING_PAPERWORK", (
            f"the sweep reports the gap rather than closing it, got "
            f"{stale['status']}"
        )
        assert league.player(world["player"]["id"])["roster_designation"] == "ACTIVE", (
            "and the player is untouched by the club's posture, got "
            f"{league.player(world['player']['id'])['roster_designation']}"
        )


class TestClosingThePaperworkGapResetsThePostureAndTheCounter:
    """The single violation-free edge, taken from GRACE.

    PRD 3.9: "There is exactly **one** way out, and it is the same edge from all three
    violation postures: a sweep that finds an empty violation list returns the club to
    `COMPLIANT`, clears `grace_expires_at` to null and resets
    `consecutive_noncompliant_checks` to 0."
    """

    def test_filing_the_form_returns_the_club_to_compliant(
        self, league: League
    ) -> None:
        """Nothing about the club's roster or money changed — only the form did.

        PRD 3.5: "The designation advances `PENDING_PAPERWORK → PAPERWORK_FILED` when
        the club's medical officer files the league paperwork, supplying a
        `paperwork_reference` that is present and non-blank."

        PRD 3.5: "The server stamps `paperwork_filed_at` with the logical clock and, in
        the same write, moves the player's `medical_status` `CLEARED → REHAB`."

        Design: Corner/cross_cutting_complexity_layers/closing_the_paperwork_gap_resets_the_posture_and_the_counter
        """
        league.set_clock(CLOCK)
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        league.sign_onto_roster(
            club["id"], player["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            expected_team_version=club["version"], **TERMS,
        )
        designation = league.open_injury_designation(club["id"], player["id"])

        league.set_clock("2026-08-11T14:00:00Z")
        armed = league.run_sweep(club["id"])
        assert armed["resulting_compliance_status"] == "GRACE", (
            f"the club starts this test in grace, got "
            f"{armed['resulting_compliance_status']}"
        )

        filed = league.file_paperwork(designation["id"], club["id"])
        assert filed["status"] == "PAPERWORK_FILED", (
            f"the form is now on file, got {filed['status']}"
        )
        assert filed["paperwork_filed_at"] == "2026-08-11T14:00:00.000Z", (
            f"stamped on the logical clock, got {filed['paperwork_filed_at']}"
        )

        cleared = league.run_sweep(club["id"])
        assert cleared["violation_codes"] == [], (
            f"the club has nothing left in violation, got "
            f"{cleared['violation_codes']}"
        )
        assert cleared["result"] == "COMPLIANT", (
            f"so the sweep reports it clean, got {cleared['result']}"
        )
        assert cleared["resulting_compliance_status"] == "COMPLIANT", (
            f"and restores the posture, got "
            f"{cleared['resulting_compliance_status']}"
        )

        club_now = league.club(club["id"])
        assert club_now["compliance_status"] == "COMPLIANT", (
            f"the club is out, got {club_now['compliance_status']}"
        )
        assert club_now["grace_expires_at"] is None, (
            f"its armed grace is cleared, got {club_now['grace_expires_at']}"
        )
        assert club_now["consecutive_noncompliant_checks"] == 0, (
            f"and the counter is reset to zero, got "
            f"{club_now['consecutive_noncompliant_checks']}"
        )

        assert len(league.sweep_history(club["id"])) == 2, (
            f"both sweeps are on the record, got "
            f"{len(league.sweep_history(club['id']))}"
        )
        subject = league.player(player["id"])
        assert subject["medical_status"] == "REHAB", (
            f"the filing moved the player into rehab, got "
            f"{subject['medical_status']}"
        )
        assert subject["roster_designation"] == "ACTIVE", (
            "while his designation waits on a placement filing, got "
            f"{subject['roster_designation']}"
        )
