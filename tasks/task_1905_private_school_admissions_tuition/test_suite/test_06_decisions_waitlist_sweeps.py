"""Decision sweeps: round-close ranking fork, waitlist promotion join,
melt-boundary expiry, and the lapse cascade (PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_seat_ledger,
    close_round,
    get_aid,
    get_application,
    get_contract,
    get_cycle,
    get_section,
    make_aid_application,
    make_applicant,
    make_application,
    make_open_world,
    make_parent_headers,
    parse_instant,
    run_sweep,
    score_pair,
    set_clock,
    setup_decision_world,
    setup_offered_application,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    verify_aid,
    finalize_aid,
    accept_aid,
    issue_contract,
)


def _lapse_cascade_world():
    """capacity-1 EARLY world: fam-a (100.0, aid 12,000,000 hh4 verified and
    finalized pre-close, accepted post-close, contract issued due 2026-11-16)
    ahead of fam-b (84.0, no aid, waitlisted)."""
    ctx = make_open_world(capacity=1, max_aid_seat_pct=1.0)
    cyc_id, sec_id = ctx["cycle"]["id"], ctx["section"]["id"]
    apl_a = make_applicant("fam-a")
    app_a = make_application(apl_a["id"], cyc_id, sec_id, "fam-a", "EARLY")
    submit_application(app_a["id"], "fam-a")
    aid = make_aid_application(app_a["id"], "fam-a", 12_000_000, 4)
    verify_aid(aid["id"], 12_000_000, officer_id="fao-1")
    finalize_aid(aid["id"], officer_id="fao-2")
    score_pair(app_a["id"], ctx["session"]["id"], 100, 100, "int-a")
    apl_b = make_applicant("fam-b", first_name="Ben", last_name="Bell")
    app_b = make_application(apl_b["id"], cyc_id, sec_id, "fam-b", "EARLY")
    submit_application(app_b["id"], "fam-b")
    score_pair(app_b["id"], ctx["session"]["id"], 80, 90, "int-b")
    set_clock("2026-11-02T00:00:00Z")
    close_round(cyc_id, "EARLY")
    accept_aid(aid["id"], "fam-a")
    contract = issue_contract(app_a["id"])
    ctx.update({"app_a": get_application(app_a["id"]),
                "app_b": get_application(app_b["id"]),
                "aid": get_aid(aid["id"]), "contract": contract})
    return ctx


class TestRoundCloseFork:
    """Difficulty: one close-round forks EVALUATION_COMPLETE siblings into
    OFFERED / WAITLISTED / DENIED with divergent side effects, and the
    waitlisted branch later joins the offered branch via promotion."""

    def test_close_forks_pool_into_offered_waitlisted_denied(
            self, api, director_headers):
        """PRD §3.5: "Walking from the highest-ranked candidate downward: a
        candidate is admitted — moved `EVALUATION_COMPLETE` → `OFFERED` — while
        open seats remain".
        PRD §3.5: "A candidate not admitted is placed `WAITLISTED` while the
        section's waitlist band — sized equal to the section's `capacity` — is
        not yet full; anyone beyond both seats and band is `DENIED`."
        PRD §3.5: "Every newly `OFFERED` application receives an
        `offer_expires_at` twenty-one days out from the close clock, a
        `promoted_from_waitlist` of false".

        Design: Difficulty/non_linear_state_machine/round_close_fork_and_waitlist_join
        """
        ctx = setup_decision_world(
            [
                {"family": "fam-h", "test": 100, "interview": 100},
                {"family": "fam-m", "test": 80, "interview": 90},
                {"family": "fam-l", "test": 60, "interview": 60},
            ],
            capacity=1, round_name="REGULAR",
            close_clock="2027-01-16T00:00:00Z",
        )
        high, mid, low = (c["application"] for c in ctx["candidates"])
        assert high["status"] == "OFFERED"
        assert high["promoted_from_waitlist"] is False
        # REGULAR close clock 2027-01-16 + 21 days.
        assert parse_instant(high["offer_expires_at"]) == parse_instant(
            "2027-02-06T00:00:00Z"
        )
        assert mid["status"] == "WAITLISTED"   # seat gone, band of 1 not full
        assert low["status"] == "DENIED"       # past both seats and band
        # Only the OFFERED branch consumes a seat.
        section = get_section(ctx["section"]["id"])
        assert section["seats_held"] == 1
        assert_seat_ledger(section)

    def test_decline_then_sweep_promotes_waitlisted_branch(
            self, api, director_headers):
        """PRD §3.5: "the sweep takes the section's `WAITLISTED` applications
        in the same rank order — `composite_score` descending, `submitted_at`
        ascending, `created_at` ascending — and promotes the first candidate
        `WAITLISTED` → `OFFERED`, stamping `offer_expires_at` seven days from
        the promotion clock, setting `promoted_from_waitlist` to true".
        PRD §3.6: "Declining ... frees the held seat for the next sweep's
        promotion."

        Design: Difficulty/non_linear_state_machine/round_close_fork_and_waitlist_join
        """
        ctx = setup_decision_world(
            [
                {"family": "fam-h", "test": 100, "interview": 100},
                {"family": "fam-m", "test": 80, "interview": 90},
                {"family": "fam-l", "test": 60, "interview": 60},
            ],
            capacity=1, round_name="REGULAR",
            close_clock="2027-01-16T00:00:00Z",
        )
        high = ctx["candidates"][0]["application"]
        mid = ctx["candidates"][1]["application"]
        low = ctx["candidates"][2]["application"]
        validate_success(api.decline_application(
            high["id"], make_parent_headers("fam-h")))
        run_sweep(ctx["cycle"]["id"])  # clock still 2027-01-16
        promoted = get_application(mid["id"])
        assert promoted["status"] == "OFFERED"
        assert promoted["promoted_from_waitlist"] is True
        # Promotion clock 2027-01-16 + 7 days — shorter than the 21-day
        # round-close window.
        assert parse_instant(promoted["offer_expires_at"]) == parse_instant(
            "2027-01-23T00:00:00Z"
        )
        assert get_application(low["id"])["status"] == "DENIED"
        section = get_section(ctx["section"]["id"])
        assert section["seats_held"] == 1  # declined seat re-held by promotion
        assert_seat_ledger(section)


class TestContractLapseCascade:
    """Difficulty: the run-sweep lapse cascade — contract LAPSED (hop 1) ->
    application EXPIRED (hop 2) -> award RELEASED and budget uncommitted
    (hop 3) -> freed seat promotes the waitlist head (hop 4)."""

    def test_lapse_cascades_to_application_and_budget(self, api,
                                                      director_headers):
        """PRD §3.6: "When the sweep finds the logical clock past
        `response_due_at` on a contract still `ISSUED` or `SIGNED`, the
        contract moves to `LAPSED`, and the lapse cascades in one request: the
        application moves `CONTRACT_ISSUED` → `EXPIRED`, its linked aid
        application releases — uncommitting `final_award_cents` from the cycle
        when the award was `ACCEPTED` — and the section's held counters
        decrement, freeing the seat to feed that same sweep's waitlist
        promotion."

        Design: Difficulty/transitive_cascade/sweep_contract_lapse_full_cascade
        """
        ctx = _lapse_cascade_world()
        assert get_cycle(ctx["cycle"]["id"])["aid_committed_cents"] == 1_820_000
        set_clock("2026-11-17T00:00:00Z")  # past response_due_at 2026-11-16
        run_sweep(ctx["cycle"]["id"])
        assert get_contract(ctx["contract"]["id"])["status"] == "LAPSED"
        assert get_application(ctx["app_a"]["id"])["status"] == "EXPIRED"
        assert get_aid(ctx["aid"]["id"])["award_status"] == "RELEASED"
        assert get_cycle(ctx["cycle"]["id"])["aid_committed_cents"] == 0

    def test_lapse_frees_seat_and_promotes_waitlist_head(
            self, api, director_headers):
        """PRD §3.5: "Seats freed by expirations, lapses, declines, and melts
        processed earlier in the same sweep feed that same sweep's
        promotions."
        PRD §3.5: "promotes the first candidate `WAITLISTED` → `OFFERED`,
        stamping `offer_expires_at` seven days from the promotion clock,
        setting `promoted_from_waitlist` to true".

        Design: Difficulty/transitive_cascade/sweep_contract_lapse_full_cascade
        """
        ctx = _lapse_cascade_world()
        set_clock("2026-11-17T00:00:00Z")
        sweep = run_sweep(ctx["cycle"]["id"])
        assert sweep["lapsed_contract_count"] == 1
        assert ctx["app_b"]["id"] in sweep["promoted_application_ids"]
        promoted = get_application(ctx["app_b"]["id"])
        assert promoted["status"] == "OFFERED"
        assert promoted["promoted_from_waitlist"] is True
        # Sweep clock 2026-11-17 + 7 days.
        assert parse_instant(promoted["offer_expires_at"]) == parse_instant(
            "2026-11-24T00:00:00Z"
        )
        section = get_section(ctx["section"]["id"])
        assert section["seats_held"] == 1  # freed seat immediately re-held
        assert_seat_ledger(section)


class TestSeatConservation:
    """Difficulty: seats_held == count of applications in {OFFERED,
    CONTRACT_ISSUED, ENROLLED}; the offer/decline pair conserves the ledger."""

    def test_offer_then_decline_conserves_seats(self, api, director_headers):
        """PRD §2.9: "`seats_held` counts the section's applications in
        `OFFERED`, `CONTRACT_ISSUED`, or `ENROLLED` ... and `seats_available`
        is the section's `capacity` minus `seats_held`, which can never go
        negative."
        PRD §3.6: "Declining ... frees the held seat for the next sweep's
        promotion."

        Design: Difficulty/compensating_invariant/offer_decline_conserves_seats
        """
        ctx = setup_offered_application("fam-a", capacity=1)
        assert ctx["application"]["status"] == "OFFERED"
        section = get_section(ctx["section"]["id"])
        assert section["seats_held"] == 1 and section["seats_available"] == 0
        validate_success(api.decline_application(
            ctx["application"]["id"], make_parent_headers("fam-a")))
        assert get_application(ctx["application"]["id"])["status"] == "DECLINED"
        section = get_section(ctx["section"]["id"])
        assert section["seats_held"] == 0 and section["seats_available"] == 1
        assert_seat_ledger(section)

    def test_sweep_after_decline_with_empty_waitlist_promotes_nobody(
            self, api, director_headers):
        """PRD §3.5: "An empty candidate set is not an error — nothing
        happens."

        Design: Difficulty/compensating_invariant/offer_decline_conserves_seats
        """
        ctx = setup_offered_application("fam-a", capacity=1)
        validate_success(api.decline_application(
            ctx["application"]["id"], make_parent_headers("fam-a")))
        sweep = run_sweep(ctx["cycle"]["id"])
        assert sweep["promoted_application_ids"] == []
        section = get_section(ctx["section"]["id"])
        assert section["seats_held"] == 0 and section["seats_available"] == 1


class TestAidSeatCompositionCap:
    def test_aid_seat_composition_cap_skips_aid_seeker(self, api,
                                                       director_headers):
        """PRD §3.5: "The aid-seat ceiling is the greatest integer not
        exceeding the section's `capacity` multiplied by its
        `max_aid_seat_pct`, and a candidate counts as aid-seeking when a
        linked aid application exists whose `award_status` is anything other
        than `RELEASED`."
        PRD §3.5: "An aid-seeking candidate skipped because the ceiling is
        full does not consume a seat, and the pass continues to lower-ranked
        candidates."

        Design: Corner/calculations/aid_seat_composition_cap_skips_aid_seeker
        """
        ctx = setup_decision_world(
            [
                {"family": "fam-a", "test": 100, "interview": 100,
                 "aid": (9_500_000, 4)},   # 100.0
                {"family": "fam-b", "test": 100, "interview": 90,
                 "aid": (9_500_000, 4)},   # 96.0
                {"family": "fam-c", "test": 90, "interview": 100,
                 "aid": (9_500_000, 4)},   # 94.0
                {"family": "fam-d", "test": 90, "interview": 90},  # 90.0
            ],
            capacity=4, max_aid_seat_pct=0.5,  # aid cap = floor(4 * 0.5) = 2
        )
        app_a, app_b, app_c, app_d = (c["application"]
                                      for c in ctx["candidates"])
        assert app_a["status"] == "OFFERED"
        assert app_b["status"] == "OFFERED"  # aid admits reach the cap of 2
        # 94.0 aid seeker skipped by the composition cap despite outranking D.
        assert app_c["status"] == "WAITLISTED"
        assert app_d["status"] == "OFFERED"  # non-aid takes the third seat
        section = get_section(ctx["section"]["id"])
        assert section["seats_held"] == 3
        assert section["aid_seats_held"] == 2
        assert section["seats_available"] == 1


class TestDecisionReadbacks:
    def test_computed_section_counters_after_offer(self, api, director_headers):
        """PRD §2.9: "Each `GradeSection` maintains a live seat ledger:
        `seats_held` counts the section's applications in `OFFERED`,
        `CONTRACT_ISSUED`, or `ENROLLED`; `aid_seats_held` counts those among
        the held set that have a linked aid application whose `award_status`
        is anything other than `RELEASED`; and `seats_available` is the
        section's `capacity` minus `seats_held`".
        PRD §3.5: "an `estimated_deposit_cents` for the offer letter computed
        on the estimated deposit variant: the larger of 50,000 cents and ten
        percent of net tuition rounded half-up to a whole cent, where net
        tuition is the section's `tuition_cents` minus the linked aid
        application's `provisional_award_cents` — or minus zero when no aid
        application exists."

        Design: Corner/entities/computed_section_counters_after_offer
        """
        ctx = setup_submitted_application("fam-a", capacity=2,
                                          max_aid_seat_pct=1.0)
        make_aid_application(ctx["application"]["id"], "fam-a", 9_500_000, 4)
        score_pair(ctx["application"]["id"], ctx["session"]["id"], 80, 90,
                   "int-a")
        set_clock("2026-11-02T00:00:00Z")
        close_round(ctx["cycle"]["id"], "EARLY")
        section = get_section(ctx["section"]["id"])
        # A PROVISIONAL aid application counts as aid-seeking.
        assert section["seats_held"] == 1
        assert section["aid_seats_held"] == 1
        assert section["seats_available"] == 1
        application = get_application(ctx["application"]["id"])
        assert application["status"] == "OFFERED"
        # net 3,000,000 - 2,370,000 = 630,000 -> 10% is 63,000 (floor 50,000).
        assert application["estimated_deposit_cents"] == 63_000

    def test_list_applications_filter_by_status(self, api, officer_headers):
        """PRD §3.2: "The application listing accepts optional filters
        `cycle_id`, `grade_section_id`, `applicant_id`, `status`, and
        `family_id`."

        Design: Corner/endpoints/list_applications_filter_by_status
        """
        ctx = setup_decision_world(
            [
                {"family": "fam-h", "test": 100, "interview": 100},
                {"family": "fam-m", "test": 80, "interview": 90},
                {"family": "fam-l", "test": 60, "interview": 60},
            ],
            capacity=1,
        )
        mid = ctx["candidates"][1]["application"]
        low = ctx["candidates"][2]["application"]
        data, meta = validate_paginated(
            api.list_applications(officer_headers,
                                  params={"status": "WAITLISTED"})
        )
        assert [row["id"] for row in data] == [mid["id"]]
        assert meta["total_count"] == 1
        data, meta = validate_paginated(
            api.list_applications(officer_headers, params={"status": "DENIED"})
        )
        assert [row["id"] for row in data] == [low["id"]]
        assert meta["total_count"] == 1


class TestMeltBoundary:
    def test_waitlist_expires_after_melt_deadline(self, api, director_headers):
        """PRD §3.5: "if the clock has passed the cycle's `melt_deadline_at`,
        every remaining `WAITLISTED` application moves to `EXPIRED`; and only
        then does waitlist promotion run."
        PRD §3.5: "It runs only while the cycle is `EARLY_CLOSED` or `CLOSED`
        and the logical clock is at or before `melt_deadline_at`; past the
        melt deadline the waitlist expires instead, as above."

        Design: Corner/state_machines/waitlist_expires_after_melt_deadline
        """
        ctx = setup_decision_world(
            [
                {"family": "fam-h", "test": 100, "interview": 100},
                {"family": "fam-m", "test": 80, "interview": 90},
            ],
            capacity=1,
        )
        high = ctx["candidates"][0]["application"]
        mid = ctx["candidates"][1]["application"]
        assert high["status"] == "OFFERED"
        assert mid["status"] == "WAITLISTED"
        set_clock("2027-08-02T00:00:00Z")  # past melt_deadline 2027-08-01
        sweep = run_sweep(ctx["cycle"]["id"])
        assert get_application(high["id"])["status"] == "EXPIRED"
        assert get_application(mid["id"])["status"] == "EXPIRED"
        assert sweep["expired_offer_count"] == 1
        assert sweep["expired_waitlist_count"] == 1
        # The freed seat is NOT refilled past the melt deadline.
        assert sweep["promoted_application_ids"] == []
        assert get_section(ctx["section"]["id"])["seats_held"] == 0

    def test_decline_when_waitlisted_rejected(self, api):
        """PRD §3.6: "Declining, available to a `Parent` while the application
        is `OFFERED` (`ERR_APPLICATION_NOT_OFFERED` otherwise)".

        Design: Corner/validations/decline_when_waitlisted_rejected
        """
        ctx = setup_decision_world(
            [
                {"family": "fam-h", "test": 100, "interview": 100},
                {"family": "fam-m", "test": 80, "interview": 90},
            ],
            capacity=1,
        )
        mid = ctx["candidates"][1]["application"]
        assert mid["status"] == "WAITLISTED"
        resp = api.decline_application(mid["id"], make_parent_headers("fam-m"))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_OFFERED, 409)
        assert get_application(mid["id"])["status"] == "WAITLISTED"
