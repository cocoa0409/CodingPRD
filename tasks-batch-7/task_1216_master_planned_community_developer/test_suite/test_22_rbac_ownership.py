"""Corner coverage: entity-backed ownership (BuilderRep cure, resident RSVP
cancel), budget ratify segregation of duties at PARITY, and reviewer rotation."""
from test_helpers import (
    api_client,
    close_lots_with_owners,
    create_active_agreement,
    create_active_community,
    create_and_schedule_notice,
    create_application,
    create_event_payload,
    create_offered_lot,
    create_open_phase,
    create_phase,
    create_lot,
    create_builder,
    create_proposed_budget,
    create_residents,
    create_rsvp_payload,
    deny_round,
    list_community_seats,
    fill_seat_by_election,
    resubmit_application,
    set_clock,
    setup_active_agreement_scenario,
    get_success_data,
    validate_error,
    make_association_director_headers,
    make_builder_rep_headers,
    make_design_reviewer_headers,
    make_homeowner_resident_headers,
    make_owner_director_headers,
    ApiErrorId,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]


class TestBuilderRepCannotCureOtherBuildersTranche:
    def test_foreign_builder_rep_rejected_own_rep_cures(self):
        """PRD §3.3: "The builder's own `BuilderRep` may cure it — the acting user's `X-User-ID` must equal the agreement's `builder_id` (`ERR_FORBIDDEN_ROLE` otherwise) — by paying `payment_cents` exactly equal to the current `accrued_penalty_cents` (`ERR_PENALTY_AMOUNT_MISMATCH` on any other amount) while the logical clock is on or before the `cure_deadline`; attempting to cure a tranche that is not `MISSED`, or one whose cure deadline has already passed, is rejected with `ERR_TRANCHE_NOT_CURABLE`.".
        PRD §2.1: "The same `ERR_FORBIDDEN_ROLE` rejection fires when an entity-backed actor operates on another principal's resource — for instance, a `BuilderRep` curing a tranche that belongs to a different builder's agreement."

        Design: Corner/rbac/builder_rep_cannot_cure_other_builders_tranche
        """
        community = create_active_community("Ownership Oaks", 20)
        phase = create_open_phase(community["id"], "P1", 1, 10)
        builder_a = create_builder(community["id"], "Alpha Builders", "A")
        builder_b = create_builder(community["id"], "Beta Builders", "A")
        agreement, tranches = create_active_agreement(
            community["id"], builder_a["id"], phase["id"], 1,
            [("2026-06-30T00:00:00Z", 1)], earnest_money_cents=1000000,
        )
        set_clock("2026-06-01T00:00:00Z")
        set_clock("2026-07-10T00:00:00Z")
        # Tranche MISSED (due 2026-06-30), penalty 10 days x 1 lot x 1000c.
        tranche = get_success_data(api_client.get_tranche(tranches[0]["id"], CTRL))
        assert tranche["status"] == "MISSED"
        assert tranche["accrued_penalty_cents"] == 10000

        resp = api_client.cure_tranche(
            tranches[0]["id"], {"payment_cents": 10000},
            make_builder_rep_headers(builder_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        cured = get_success_data(
            api_client.cure_tranche(
                tranches[0]["id"], {"payment_cents": 10000},
                make_builder_rep_headers(builder_a["id"]),
            )
        )
        assert cured["status"] == "CURED"


class TestRsvpCancelOwnershipEnforced:
    def test_other_resident_cannot_cancel_coordinator_can(self):
        """PRD §3.8: "Cancelling a `CONFIRMED` RSVP, by the booking resident or by a `LifestyleCoordinator`, recomputes the count and runs waitlist promotion on strict head-of-line order: the earliest-created `WAITLISTED` RSVP is promoted if its `party_size` fits the freed capacity, and if the head of the line does not fit, nobody is promoted.".
        PRD §2.1: "When `X-User-Role` is `HomeownerResident`, `X-User-ID` is the `id` of the acting `Resident`, and ownership checks likewise compare resident foreign keys (for example, an RSVP's `resident_id`) to `X-User-ID`."
        PRD §2.1: "The same `ERR_FORBIDDEN_ROLE` rejection fires when an entity-backed actor operates on another principal's resource — for instance, a `BuilderRep` curing a tranche that belongs to a different builder's agreement.".

        Design: Corner/rbac/rsvp_cancel_ownership_enforced
        """
        community = create_active_community("RSVP Ridge", 10)
        event = get_success_data(
            api_client.create_event(
                create_event_payload(
                    community_id=community["id"], title="BBQ",
                    start_at="2026-05-20T17:00:00Z", end_at="2026-05-20T20:00:00Z",
                    capacity=10,
                ),
                LIFESTYLE,
            )
        )
        get_success_data(api_client.schedule_event(event["id"], LIFESTYLE))
        r1, r2 = create_residents(
            community["id"], [("R Una", "ru@x.com"), ("R Dos", "rd@x.com")]
        )
        rsvp = get_success_data(
            api_client.create_rsvp(
                create_rsvp_payload(event_id=event["id"], resident_id=r1["id"], party_size=2),
                make_homeowner_resident_headers(r1["id"]),
            )
        )

        resp = api_client.cancel_rsvp(rsvp["id"], make_homeowner_resident_headers(r2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        cancelled = get_success_data(api_client.cancel_rsvp(rsvp["id"], LIFESTYLE))
        assert cancelled["status"] == "CANCELLED"


class TestBudgetRatifySegregationOfDuties:
    def _setup_parity_budget(self):
        """4-unit community at PARITY (2 closings, owners r1/r2, both elected
        to seats); FY2027 budget PROPOSED with BUDGET_ADOPTION notice SENT
        2026-06-02; clock 2026-06-17."""
        scenario = setup_active_agreement_scenario(
            total_planned_units=4, planned_lot_count=4, total_lots_committed=2,
            tranches=[("2026-06-30T00:00:00Z", 2)], community_name="SoD Summit",
            earnest_money_cents=1000000,
        )
        lot1 = create_offered_lot(scenario["phase"]["id"], "S1")
        lot2 = create_offered_lot(scenario["phase"]["id"], "S2")
        r1, r2 = create_residents(
            scenario["community"]["id"], [("S One", "s1@x.com"), ("S Two", "s2@x.com")]
        )
        set_clock("2026-06-01T00:00:00Z")
        close_lots_with_owners(
            scenario["agreement"]["id"], [lot1["id"], lot2["id"]], [r1["id"], r2["id"]]
        )
        seats = list_community_seats(scenario["community"]["id"])
        seat5, seat4 = seats[4], seats[3]
        assert seat5["status"] == "VACANT" and seat4["status"] == "VACANT"
        fill_seat_by_election(seat5["id"], r1["id"], votes_cast=1, votes_for=1)
        fill_seat_by_election(seat4["id"], r2["id"], votes_cast=1, votes_for=1)

        budget = create_proposed_budget(scenario["community"]["id"], 2027, [("MANAGEMENT", 100000)])
        create_and_schedule_notice(
            scenario["community"]["id"], "BUDGET_ADOPTION", "2026-06-02T00:00:00Z",
            budget_id=budget["id"], subject="sod", body="adopt",
        )
        set_clock("2026-06-02T00:00:00Z")
        set_clock("2026-06-17T00:00:00Z")
        return budget, r1, r2

    def test_adopter_cannot_ratify_different_owner_ratifies(self):
        """PRD §3.5: "Under `PARITY` or `OWNER_MAJORITY`, the same adopt action lands the budget in `PENDING_RATIFICATION`, and an `OwnerDirector` must ratify it — the ratifier's `X-User-ID` must differ from the recorded `adopted_by_user_id` (`ERR_ADOPTER_CANNOT_RATIFY`), enforcing segregation between the adopter and the ratifier."
        PRD §3.5: "Every successful adopt records `adopted_by_user_id` from the acting header."

        Design: Corner/rbac/budget_ratify_segregation_of_duties
        """
        budget, r1, r2 = self._setup_parity_budget()
        # Adopt as an AssociationDirector whose acting user id is r1's id —
        # r1 also holds an OWNER_ELECTED seat.
        adopted = get_success_data(
            api_client.adopt_budget(
                budget["id"], make_association_director_headers(r1["id"])
            )
        )
        assert adopted["status"] == "PENDING_RATIFICATION", (
            f"at PARITY the adopt lands PENDING_RATIFICATION, got {adopted['status']}"
        )
        assert adopted["adopted_by_user_id"] == r1["id"]

        # The same user, now wearing the OwnerDirector hat of their seat,
        # cannot ratify their own adoption.
        resp = api_client.ratify_budget(
            budget["id"], make_owner_director_headers(r1["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ADOPTER_CANNOT_RATIFY)

        ratified = get_success_data(
            api_client.ratify_budget(budget["id"], make_owner_director_headers(r2["id"]))
        )
        assert ratified["status"] == "ADOPTED"


class TestReviewerConflictRotation:
    def test_latest_denier_cannot_claim_resubmission(self):
        """PRD §3.7: "Two conflict rules protect impartiality: on a first submission the reviewer's `X-User-ID` must not equal the applicant's id, and on a `RESUBMITTED` application it must not equal the `denied_by_user_id` of the latest denial; both surface as `ERR_REVIEWER_CONFLICT`."
        PRD §3.7: "A `DesignReviewer` claims an application by beginning review, which stamps `reviewer_user_id` and moves it to `UNDER_REVIEW`."

        Design: Corner/rbac/reviewer_conflict_rotation
        """
        community = create_active_community("Rotation Ridge", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        lot = create_lot(phase["id"], "R1")
        builder = create_builder(community["id"], "Rotation Builders", "A")
        application = create_application(
            community["id"], lot["id"], applicant_builder_id=builder["id"],
            project_type="LANDSCAPE",
        )
        deny_round(application["id"], "rev-1", "species palette")
        resubmit_application(application["id"], applicant_builder_id=builder["id"])

        resp = api_client.begin_review(
            application["id"], make_design_reviewer_headers("rev-1")
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_CONFLICT)

        claimed = get_success_data(
            api_client.begin_review(application["id"], make_design_reviewer_headers("rev-2"))
        )
        assert claimed["status"] == "UNDER_REVIEW"
        assert claimed["reviewer_user_id"] == "rev-2"
