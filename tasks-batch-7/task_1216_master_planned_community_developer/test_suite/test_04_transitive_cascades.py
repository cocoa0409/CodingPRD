"""Transitive cascades: closing -> community stage -> board seats, and
certify-default -> agreement -> builder -> other agreements."""
from test_helpers import (
    api_client,
    close_lots_with_owners,
    create_active_agreement,
    create_active_community,
    create_and_close_lot,
    create_draft_agreement,
    create_executed_agreement,
    create_offered_lot,
    create_open_phase,
    create_builder,
    set_clock,
    setup_active_agreement_scenario,
    get_success_data,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]


class TestClosingToBoardSeatCascade:
    """Close -> closed_unit_pct -> transition_stage ratchet -> seat conversion.
    4 planned units; closes 1, 2 land at 25.00 (OWNER_REPRESENTATION, seat 5
    converted) and 50.00 (PARITY, seat 4 converted); the third close crosses
    75.00 (OWNER_MAJORITY, seat 3 converted)."""

    def _setup(self):
        scenario = setup_active_agreement_scenario(
            total_planned_units=4,
            planned_lot_count=4,
            total_lots_committed=4,
            tranches=[("2026-06-30T00:00:00Z", 4)],
            community_name="Cascade Estates",
        )
        lots = [
            create_offered_lot(scenario["phase"]["id"], f"L{i}") for i in range(1, 5)
        ]
        set_clock("2026-06-01T00:00:00Z")
        close_lots_with_owners(scenario["agreement"]["id"], [lots[0]["id"], lots[1]["id"]], [None, None])
        return scenario, lots

    def test_stage_and_percentage_after_first_two_closes(self):
        """PRD §2.7: "The stage mapping, evaluated on the rounded percentage with inclusive thresholds, is: at least 25.00 percent → `OWNER_REPRESENTATION`; at least 50.00 percent → `PARITY`; at least 75.00 percent → `OWNER_MAJORITY`; otherwise `DECLARANT_CONTROL`. Reaching 100.00 percent does not itself complete turnover — the stage remains `OWNER_MAJORITY` until statutory turnover is recorded, at which point it becomes `TURNOVER_COMPLETE`."

        Design: Difficulty/transitive_cascade/closing_to_board_seat_cascade
        """
        scenario, _ = self._setup()
        community = get_success_data(api_client.get_community(scenario["community"]["id"], EXEC))
        assert community["closed_unit_count"] == 2
        assert float(community["closed_unit_pct"]) == 50.00
        assert community["transition_stage"] == "PARITY", (
            f"2/4 units closed must be PARITY, got {community['transition_stage']}"
        )

    def test_third_close_ratchets_stage_and_converts_seat(self):
        """PRD §3.9: "On each stage advance, the deficit between the owed count and the current number of `OWNER_ELECTED` seats is made up by converting `DECLARANT_APPOINTED` `FILLED` seats — highest `seat_no` first — into `OWNER_ELECTED` `VACANT` seats: the `seat_class` flips to `OWNER_ELECTED`, the declarant appointee is removed, and `holder_name` and `holder_resident_id` are cleared.".
        PRD §3.4: "The lot moves to `CLOSED`; if its phase was `SALES_OPEN` it advances to `DELIVERING`, and the phase's `closed_lot_count` increments — that increment itself runs the amenity trigger-breach check of §3.2, which can drop a breached amenity to `DELINQUENT` and set off the event-cancellation and delinquency-notice cascade from there.".

        Design: Difficulty/transitive_cascade/closing_to_board_seat_cascade
        """
        scenario, lots = self._setup()
        tranche_id = scenario["tranches"][0]["id"]
        closed = create_and_close_lot(scenario["agreement"]["id"], lots[2]["id"])
        assert closed["status"] == "CLOSED"
        assert closed["credited_tranche_id"] == tranche_id, (
            "the waterfall must credit the OPEN tranche"
        )

        community = get_success_data(api_client.get_community(scenario["community"]["id"], EXEC))
        assert community["closed_unit_count"] == 3
        assert float(community["closed_unit_pct"]) == 75.00
        assert community["transition_stage"] == "OWNER_MAJORITY"

        tranche = get_success_data(api_client.get_tranche(tranche_id, CTRL))
        assert tranche["lots_credited"] == 3
        assert tranche["status"] == "OPEN", f"3 < 4 leaves the tranche OPEN, got {tranche['status']}"

        phase = get_success_data(api_client.get_phase(scenario["phase"]["id"], EXEC))
        assert phase["closed_lot_count"] == 3
        assert phase["status"] == "DELIVERING"

        seats_resp = api_client.list_board_seats(DIRECTOR, params={"community_id": scenario["community"]["id"]})
        seats = get_success_data(seats_resp)
        by_no = {s["seat_no"]: s for s in seats}
        assert len(seats) == 5, "the board always has exactly five seats"
        for seat_no in (3, 4, 5):
            assert by_no[seat_no]["seat_class"] == "OWNER_ELECTED"
            assert by_no[seat_no]["status"] == "VACANT"
            assert by_no[seat_no]["holder_name"] is None
            assert by_no[seat_no]["holder_resident_id"] is None
        for seat_no in (1, 2):
            assert by_no[seat_no]["seat_class"] == "DECLARANT_APPOINTED"
            assert by_no[seat_no]["status"] == "FILLED"


class TestCertifyDefaultCascade:
    """certify-default -> tranche DEFAULTED -> agreement DEFAULTED (earnest
    money forfeited) -> builder SUSPENDED -> other EXECUTED agreement
    TERMINATED -> its SCHEDULED tranche CANCELLED."""

    def _setup(self):
        community = create_active_community("Default Dunes", 20)
        phase = create_open_phase(community["id"], "P1", 1, 10)
        builder = create_builder(community["id"], "Default Bros", "C")
        a1, a1_tranches = create_active_agreement(
            community["id"], builder["id"], phase["id"], 1,
            [("2026-06-30T00:00:00Z", 1)], earnest_money_cents=10000000,
        )
        a2, a2_tranches = create_executed_agreement(
            community["id"], builder["id"], phase["id"], 1,
            [("2026-12-31T00:00:00Z", 1)], earnest_money_cents=5000000,
        )
        set_clock("2026-06-01T00:00:00Z")
        set_clock("2026-07-01T00:00:00Z")
        # Cure deadline 2026-07-14 must have passed for certify-default.
        set_clock("2026-07-16T00:00:00Z")
        return builder, a1, a1_tranches[0], a2, a2_tranches[0]

    def test_certify_default_marks_tranche_and_forfeits_earnest_money(self):
        """PRD §3.3: "Or a `DeclarantExecutive` may certify the default once the cure window has closed — the logical clock must be strictly after the `cure_deadline` (`ERR_CURE_WINDOW_OPEN` while it is still open) — moving the tranche to `DEFAULTED`. Certifying a default is the heaviest cascade in the system."
        PRD §3.3: "The tranche's agreement becomes `DEFAULTED`: its `forfeited_earnest_money_cents` is set to the full `earnest_money_cents`, and the builder's standing drops to `SUSPENDED`. That demotion itself cascades — the builder's other agreements in `DRAFT` or `EXECUTED` are `TERMINATED`, and their tranches in `SCHEDULED` or `OPEN` are `CANCELLED`."

        Design: Difficulty/transitive_cascade/certify_default_cascade
        """
        builder, a1, a1t1, _, _ = self._setup()
        defaulted = get_success_data(api_client.certify_default(a1t1["id"], EXEC))
        assert defaulted["status"] == "DEFAULTED"

        agreement = get_success_data(api_client.get_agreement(a1["id"], CTRL))
        assert agreement["status"] == "DEFAULTED"
        assert agreement["forfeited_earnest_money_cents"] == 10000000

        builder_read = get_success_data(api_client.get_builder(builder["id"], EXEC))
        assert builder_read["standing"] == "SUSPENDED"

    def test_suspension_cascades_to_other_agreements(self):
        """PRD §3.3: "That demotion itself cascades — the builder's other agreements in `DRAFT` or `EXECUTED` are `TERMINATED`, and their tranches in `SCHEDULED` or `OPEN` are `CANCELLED`. The same terminal housekeeping applies when a `DeclarantExecutive` terminates an agreement voluntarily: termination is available from `DRAFT`, `EXECUTED`, or `ACTIVE` only while no closing of the agreement is `PENDING` (`ERR_CLOSINGS_PENDING`), and it cancels the agreement's `SCHEDULED` and `OPEN` tranches."

        Design: Difficulty/transitive_cascade/certify_default_cascade
        """
        _, a1, a1t1, a2, a2t1 = self._setup()
        get_success_data(api_client.certify_default(a1t1["id"], EXEC))

        other = get_success_data(api_client.get_agreement(a2["id"], CTRL))
        assert other["status"] == "TERMINATED", (
            f"the builder-suspension cascade must terminate the other EXECUTED agreement, "
            f"got {other['status']}"
        )
        other_tranche = get_success_data(api_client.get_tranche(a2t1["id"], CTRL))
        assert other_tranche["status"] == "CANCELLED"
