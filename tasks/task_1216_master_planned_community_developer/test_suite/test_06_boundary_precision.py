"""Boundary precision: exact-fill tranche satisfaction and election quorum /
strict-majority edges."""
from test_helpers import (
    api_client,
    close_lots_with_owners,
    create_active_agreement,
    create_active_community,
    create_and_close_lot,
    create_offered_lot,
    create_open_phase,
    create_builder,
    create_residents,
    list_community_seats,
    set_clock,
    setup_active_agreement_scenario,
    get_success_data,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]


class TestTrancheExactFillBoundary:
    """The closing that brings lots_credited exactly equal to lot_count_due
    flips the tranche to SATISFIED; one fewer leaves it OPEN."""

    def _setup(self):
        scenario = setup_active_agreement_scenario(
            total_planned_units=10,
            planned_lot_count=2,
            total_lots_committed=2,
            tranches=[("2026-06-30T00:00:00Z", 2)],
            community_name="Boundary Brook",
            earnest_money_cents=1000000,
        )
        lot1 = create_offered_lot(scenario["phase"]["id"], "L1")
        lot2 = create_offered_lot(scenario["phase"]["id"], "L2")
        set_clock("2026-06-01T00:00:00Z")
        return scenario, lot1, lot2

    def test_one_credit_short_leaves_tranche_open(self):
        """PRD §3.3: "An `OPEN` tranche becomes `SATISFIED` automatically when the closing waterfall raises its `lots_credited` to `lot_count_due`. Past the due date with the count still short, the sweep marks it `MISSED`, which demotes the builder from `GOOD_STANDING` to `PROBATION` and starts the penalty meter."

        Design: Difficulty/boundary_precision_check/tranche_exact_fill_boundary
        """
        scenario, lot1, _ = self._setup()
        tranche_id = scenario["tranches"][0]["id"]
        create_and_close_lot(scenario["agreement"]["id"], lot1["id"])
        tranche = get_success_data(api_client.get_tranche(tranche_id, CTRL))
        assert tranche["lots_credited"] == 1
        assert tranche["status"] == "OPEN", (
            f"1 < 2 must leave the tranche OPEN, got {tranche['status']}"
        )

    def test_exact_fill_satisfies_and_completes_agreement(self):
        """PRD §3.3: "An `OPEN` tranche becomes `SATISFIED` automatically when the closing waterfall raises its `lots_credited` to `lot_count_due`. Past the due date with the count still short, the sweep marks it `MISSED`, which demotes the builder from `GOOD_STANDING` to `PROBATION` and starts the penalty meter."
        PRD §3.3: "On the success path, an `ACTIVE` agreement completes automatically — `ACTIVE` → `COMPLETED` — when its `lots_closed_count` reaches `total_lots_committed` and every tranche sits in `SATISFIED`, `CURED`, or `WAIVED`. While an agreement is `EXECUTED` or `ACTIVE`, a `DeclarantController` may replace the remaining takedown schedule through the OCC-guarded amendment operation described in §2.8."

        Design: Difficulty/boundary_precision_check/tranche_exact_fill_boundary
        """
        scenario, lot1, lot2 = self._setup()
        tranche_id = scenario["tranches"][0]["id"]
        create_and_close_lot(scenario["agreement"]["id"], lot1["id"])
        create_and_close_lot(scenario["agreement"]["id"], lot2["id"])

        tranche = get_success_data(api_client.get_tranche(tranche_id, CTRL))
        assert tranche["lots_credited"] == 2
        assert tranche["status"] == "SATISFIED", (
            f"equality satisfies (inclusive boundary), got {tranche['status']}"
        )
        agreement = get_success_data(api_client.get_agreement(scenario["agreement"]["id"], CTRL))
        assert agreement["lots_closed_count"] == 2
        assert agreement["status"] == "COMPLETED", (
            f"commitment met with all tranches terminal completes the agreement, "
            f"got {agreement['status']}"
        )


class TestElectionQuorumExactBoundary:
    """8 eligible voters: quorum = ceil(8 * 20 / 100) = 2; votes_cast 1 fails,
    2 passes; strict majority rejects votes_for == votes_cast / 2."""

    def _setup_election(self):
        """8-unit community; 8 closings with owners -> pct 100.00, all 5 seats
        OWNER_ELECTED VACANT; election called on seat 1. Returns (seat_id, r1_id)."""
        scenario = setup_active_agreement_scenario(
            total_planned_units=8,
            planned_lot_count=8,
            total_lots_committed=8,
            tranches=[("2026-06-30T00:00:00Z", 8)],
            community_name="Quorum Quarter",
            earnest_money_cents=1000000,
        )
        lots = [create_offered_lot(scenario["phase"]["id"], f"Q{i}") for i in range(1, 9)]
        residents = create_residents(
            scenario["community"]["id"],
            [(f"Owner {i}", f"o{i}@x.com") for i in range(1, 9)],
        )
        set_clock("2026-06-01T00:00:00Z")
        close_lots_with_owners(
            scenario["agreement"]["id"],
            [lot["id"] for lot in lots],
            [r["id"] for r in residents],
        )
        seats = list_community_seats(scenario["community"]["id"])
        seat1 = seats[0]
        assert seat1["status"] == "VACANT", (
            f"at 100% every declarant seat converts to VACANT, got {seat1['status']}"
        )
        called = get_success_data(api_client.call_election(seat1["id"], DIRECTOR))
        assert called["eligible_voter_count"] == 8, (
            f"snapshot must be the 8 OWNER residents, got {called['eligible_voter_count']}"
        )
        return seat1["id"], residents[0]["id"]

    def test_quorum_and_strict_majority_failures(self):
        """PRD §3.9: "Certifying the result requires the payload's `votes_cast`, `votes_for`, and `holder_resident_id` to pass three tests: quorum — `votes_cast` at least the ceiling of one fifth of `eligible_voter_count` (twenty percent, with the boundary inclusive; `ERR_QUORUM_NOT_MET` below it); strict majority — `votes_for` strictly more than half of `votes_cast`, so an exact tie fails (`ERR_ELECTION_MAJORITY_NOT_REACHED`); and holder eligibility — the holder must be an `OWNER` resident of the community not already holding a `FILLED` or `ELECTION_CALLED` seat (`ERR_HOLDER_NOT_ELIGIBLE`).".

        Design: Difficulty/boundary_precision_check/election_quorum_exact_boundary
        """
        seat_id, holder_id = self._setup_election()
        resp_low = api_client.certify_election(
            seat_id, {"votes_cast": 1, "votes_for": 1, "holder_resident_id": holder_id}, DIRECTOR
        )
        validate_error(resp_low, ApiErrorId.ERR_QUORUM_NOT_MET)

        resp_tie = api_client.certify_election(
            seat_id, {"votes_cast": 2, "votes_for": 1, "holder_resident_id": holder_id}, DIRECTOR
        )
        validate_error(resp_tie, ApiErrorId.ERR_ELECTION_MAJORITY_NOT_REACHED)

    def test_exact_quorum_with_majority_certifies(self):
        """PRD §3.9: "Certification records the holder and returns the seat to `FILLED`. If the deadline passes first, the sweep moves the seat to `LAPSED`; late certification is then impossible because the from-state check rejects it with `ERR_INVALID_STATE`."

        Design: Difficulty/boundary_precision_check/election_quorum_exact_boundary
        """
        seat_id, holder_id = self._setup_election()
        # Boundary failures do not consume the election; retry succeeds.
        api_client.certify_election(
            seat_id, {"votes_cast": 1, "votes_for": 1, "holder_resident_id": holder_id}, DIRECTOR
        )
        api_client.certify_election(
            seat_id, {"votes_cast": 2, "votes_for": 1, "holder_resident_id": holder_id}, DIRECTOR
        )
        certified = get_success_data(
            api_client.certify_election(
                seat_id, {"votes_cast": 2, "votes_for": 2, "holder_resident_id": holder_id},
                DIRECTOR,
            )
        )
        assert certified["status"] == "FILLED"
        assert certified["holder_resident_id"] == holder_id
