"""Corner coverage: strict head-of-line waitlist promotion, and the full
statutory turnover flow with the end of declarant authority."""
from test_helpers import (
    api_client,
    close_lots_with_owners,
    create_active_agreement,
    create_active_community,
    create_event_payload,
    create_offered_lot,
    create_open_phase,
    create_builder,
    create_notice_payload,
    create_proposed_budget,
    create_resident,
    create_residents,
    create_rsvp_payload,
    list_community_seats,
    fill_seat_by_election,
    set_clock,
    setup_active_agreement_scenario,
    get_success_data,
    validate_error,
    make_homeowner_resident_headers,
    make_owner_director_headers,
    ApiErrorId,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]


class TestRsvpStrictHeadOfLineBlocking:
    def test_freed_seat_does_not_skip_past_oversized_head(self):
        """PRD §3.8: "The RSVP lands `CONFIRMED` when the party fits the event's remaining capacity and `WAITLISTED` otherwise; the event's `confirmed_count` — the sum of `party_size` over its `CONFIRMED` RSVPs — is recomputed on each change.".
        PRD §3.8: "Cancelling a `CONFIRMED` RSVP, by the booking resident or by a `LifestyleCoordinator`, recomputes the count and runs waitlist promotion on strict head-of-line order: the earliest-created `WAITLISTED` RSVP is promoted if its `party_size` fits the freed capacity, and if the head of the line does not fit, nobody is promoted."

        Design: Corner/state_machines/rsvp_strict_head_of_line_blocking
        """
        community = create_active_community("Waitlist Woods", 10)
        event = get_success_data(
            api_client.create_event(
                create_event_payload(
                    community_id=community["id"], title="Chef Demo",
                    start_at="2026-05-20T18:00:00Z", end_at="2026-05-20T20:00:00Z",
                    capacity=3,
                ),
                LIFESTYLE,
            )
        )
        get_success_data(api_client.schedule_event(event["id"], LIFESTYLE))
        r1, r2, r3, r4 = create_residents(
            community["id"],
            [("R One", "r1@x.com"), ("R Two", "r2@x.com"),
             ("R Three", "r3@x.com"), ("R Four", "r4@x.com")],
        )

        def rsvp(resident, party_size):
            return get_success_data(
                api_client.create_rsvp(
                    create_rsvp_payload(
                        event_id=event["id"], resident_id=resident["id"], party_size=party_size
                    ),
                    make_homeowner_resident_headers(resident["id"]),
                )
            )

        rs1 = rsvp(r1, 1)
        rs2 = rsvp(r2, 2)
        rs3 = rsvp(r3, 2)
        rs4 = rsvp(r4, 1)
        assert rs1["status"] == "CONFIRMED"
        assert rs2["status"] == "CONFIRMED"
        assert rs3["status"] == "WAITLISTED"
        assert rs4["status"] == "WAITLISTED"

        cancelled = get_success_data(
            api_client.cancel_rsvp(rs1["id"], make_homeowner_resident_headers(r1["id"]))
        )
        assert cancelled["status"] == "CANCELLED"

        rs3_after = get_success_data(api_client.get_rsvp(rs3["id"], LIFESTYLE))
        assert rs3_after["status"] == "WAITLISTED", (
            "head of the line (party 2) does not fit the single freed seat"
        )
        rs4_after = get_success_data(api_client.get_rsvp(rs4["id"], LIFESTYLE))
        assert rs4_after["status"] == "WAITLISTED", (
            "strict head-of-line: no skip-ahead even though the party of 1 fits"
        )
        event_read = get_success_data(api_client.get_event(event["id"], LIFESTYLE))
        assert event_read["confirmed_count"] == 2


class TestTurnoverFullFlowAndDeclarantAuthorityEnd:
    def _setup_full_community(self):
        """5-unit community; 5 lots OFFERED; 5 prospect residents; ACTIVE
        agreement covering all 5; clock 2026-06-01 (tranche OPEN)."""
        scenario = setup_active_agreement_scenario(
            total_planned_units=5, planned_lot_count=5, total_lots_committed=5,
            tranches=[("2026-06-30T00:00:00Z", 5)], community_name="Turnover Trails",
            earnest_money_cents=1000000,
        )
        lots = [create_offered_lot(scenario["phase"]["id"], f"T{i}") for i in range(1, 6)]
        residents = create_residents(
            scenario["community"]["id"],
            [(f"T {i}", f"t{i}@x.com") for i in range(1, 6)],
        )
        set_clock("2026-06-01T00:00:00Z")
        return scenario, lots, residents

    def test_record_turnover_requires_full_closeout(self):
        """PRD §3.9: "Once `closed_unit_pct` is at least 100.00 (`ERR_TRANSITION_THRESHOLD_NOT_MET` below it) and all five seats are `OWNER_ELECTED` and `FILLED` (`ERR_TURNOVER_SEATS_NOT_FILLED` otherwise), a `DeclarantExecutive` records turnover: the community moves from `ACTIVE` to `TURNOVER_RECORDED` and `transition_stage` advances to `TURNOVER_COMPLETE`.".

        Design: Corner/state_machines/turnover_full_flow_and_declarant_authority_end
        """
        scenario, lots, residents = self._setup_full_community()
        community_id = scenario["community"]["id"]
        # 2/5 closed -> 40.00 pct.
        close_lots_with_owners(
            scenario["agreement"]["id"], [lots[0]["id"], lots[1]["id"]],
            [residents[0]["id"], residents[1]["id"]],
        )
        resp_early = api_client.record_turnover(community_id, EXEC)
        validate_error(resp_early, ApiErrorId.ERR_TRANSITION_THRESHOLD_NOT_MET)

        # Close out the remaining three -> 100.00 pct, all seats VACANT.
        close_lots_with_owners(
            scenario["agreement"]["id"],
            [lots[2]["id"], lots[3]["id"], lots[4]["id"]],
            [residents[2]["id"], residents[3]["id"], residents[4]["id"]],
        )
        resp_seats = api_client.record_turnover(community_id, EXEC)
        validate_error(resp_seats, ApiErrorId.ERR_TURNOVER_SEATS_NOT_FILLED)

    def test_turnover_then_declarant_powers_end(self):
        """PRD §3.9: "Once `closed_unit_pct` is at least 100.00 (`ERR_TRANSITION_THRESHOLD_NOT_MET` below it) and all five seats are `OWNER_ELECTED` and `FILLED` (`ERR_TURNOVER_SEATS_NOT_FILLED` otherwise), a `DeclarantExecutive` records turnover: the community moves from `ACTIVE` to `TURNOVER_RECORDED` and `transition_stage` advances to `TURNOVER_COMPLETE`. From that moment, declarant-side governance powers end — budget adoption by an `AssociationDirector`, rate arming by a `DeclarantController`, cap-override approval on the declarant side, and tranche waivers all fail with `ERR_DECLARANT_AUTHORITY_ENDED`, and the owner-side paths of §3.5 take over."
        PRD §3.5: "After turnover, adoption belongs to the owners: at `TURNOVER_COMPLETE` an `OwnerDirector` adopts directly, while an `AssociationDirector` attempting it is rejected `ERR_DECLARANT_AUTHORITY_ENDED`."

        Design: Corner/state_machines/turnover_full_flow_and_declarant_authority_end
        """
        scenario, lots, residents = self._setup_full_community()
        community_id = scenario["community"]["id"]
        close_lots_with_owners(
            scenario["agreement"]["id"],
            [lot["id"] for lot in lots],
            [r["id"] for r in residents],
        )
        seats = list_community_seats(community_id)
        assert len(seats) == 5
        # Eligible voters = 5 owners; quorum = ceil(5*20/100) = 1.
        for seat, resident in zip(seats, residents):
            assert seat["status"] == "VACANT"
            fill_seat_by_election(seat["id"], resident["id"], votes_cast=1, votes_for=1)

        recorded = get_success_data(api_client.record_turnover(community_id, EXEC))
        assert recorded["status"] == "TURNOVER_RECORDED"
        assert recorded["transition_stage"] == "TURNOVER_COMPLETE"

        # Post-turnover budget adoption: AssociationDirector is done.
        budget = create_proposed_budget(community_id, 2027, [("MANAGEMENT", 100000)])
        get_success_data(
            api_client.create_notice(
                create_notice_payload(
                    community_id=community_id, notice_type="BUDGET_ADOPTION",
                    subject="post-turnover budget", body="adopt",
                    send_at="2026-06-02T00:00:00Z", budget_id=budget["id"],
                ),
                LIFESTYLE,
            )
        )
        notices = get_success_data(
            api_client.list_notices(LIFESTYLE, params={"community_id": community_id})
        )
        budget_notice = [n for n in notices if n.get("budget_id") == budget["id"]][0]
        get_success_data(api_client.schedule_notice(budget_notice["id"], LIFESTYLE))
        set_clock("2026-06-17T00:00:00Z")

        resp_declarant = api_client.adopt_budget(budget["id"], DIRECTOR)
        validate_error(resp_declarant, ApiErrorId.ERR_DECLARANT_AUTHORITY_ENDED)

        adopted = get_success_data(
            api_client.adopt_budget(budget["id"], make_owner_director_headers(residents[0]["id"]))
        )
        assert adopted["status"] == "ADOPTED", (
            f"an OwnerDirector adopts directly post-turnover, got {adopted['status']}"
        )
