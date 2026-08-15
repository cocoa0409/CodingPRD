"""Program capacity ledger, the waiting queue, promotion scans, and sweeps."""
from test_helpers import (
    TEST_USERS,
    accept_documents,
    add_customer_account,
    api_client,
    assert_capacity_ledger_invariant,
    assert_instant_equal,
    create_cost_estimate_payload,
    create_draft_application,
    create_feeder,
    create_supplemental_review_payload,
    create_transformer,
    decide_completeness,
    drive_to_pto_granted,
    get_account,
    get_application,
    get_feeder,
    get_program,
    get_success_data,
    get_transformer,
    set_clock,
    setup_program_with_grid,
    upload_required_documents,
    validate_success,
)

ADMIN = TEST_USERS["program_administrator_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


def _submit_for_capacity(sc, ctx, size, production=15_000_000,
                         technology="SOLAR_PV"):
    """Drive an application through intake without asserting where it lands
    (CAPACITY_RESERVED when it fits, WAITING_FOR_CAPACITY otherwise).

    The default production stays within the PRD 3.3 eligibility cap (110% of
    the default 20,000,000 Wh prior usage = 22,000,000 Wh) so the application
    survives the COMPLETE decision and the capacity scenario materializes."""
    app = create_draft_application(sc, ctx, size=size, production=production,
                                   technology=technology)
    accept_documents(upload_required_documents(ctx, app["id"]))
    get_success_data(
        api_client.submit_application(app["id"], ctx["applicant"]))
    return decide_completeness(app["id"], "COMPLETE")


class TestQueuePositionAssignment:
    def test_oversized_applications_queue_in_entry_order(self, api):
        """PRD §3.3: "When capacity falls short, the application instead joins
        the queue in `WAITING_FOR_CAPACITY`: it receives the next
        `queue_position` — one more than the highest position currently held in
        the program, or 1 when the queue is empty — and the program's
        `queued_count` increases by one. Positions are one-based, and
        `queue_position` is null whenever the application is not queued."

        Design: Corner/calculations/c_queue_position_assignment_on_entry
        """
        # Cap 5,000 W; each applicant is eligible yet larger than the whole
        # remaining capacity, so all three queue in entry order.
        sc = setup_program_with_grid(
            "QP", program_overrides={"aggregate_cap_watts": 5_000})
        ctx1 = add_customer_account(sc, "1")
        ctx2 = add_customer_account(sc, "2")
        ctx3 = add_customer_account(sc, "3")
        app1 = _submit_for_capacity(sc, ctx1, 6_000, production=9_000_000)
        app2 = _submit_for_capacity(sc, ctx2, 6_000, production=9_000_000)
        app3 = _submit_for_capacity(sc, ctx3, 5_500, production=9_000_000)

        assert app1["application_status"] == "WAITING_FOR_CAPACITY"
        assert app1["queue_position"] == 1
        assert app2["queue_position"] == 2
        assert app3["queue_position"] == 3

        program = get_program(sc["program"]["id"])
        assert program["queued_count"] == 3
        assert program["program_status"] == "OPEN", (
            "queued applications hold no reservation, so the posture stays "
            "OPEN while capacity is available")
        assert program["available_capacity_watts"] == 5_000


class TestExactFitCapacity:
    def test_exact_fit_reserves_and_flips_posture(self, api):
        """PRD §3.3: "When the program's `available_capacity_watts` is at least
        the requested size, the application moves to `CAPACITY_RESERVED`"
        PRD §2.7: "After any mutation that changes the reservation or
        interconnected totals, the program's posture is recomputed: if
        `available_capacity_watts` has fallen to zero or below, a program in
        `OPEN` moves to `CAP_REACHED`; if it has risen above zero, a program in
        `CAP_REACHED` returns to `OPEN`."

        Design: Difficulty/boundary_precision_check/bpc_capacity_exact_fit_cap_reached
        """
        sc = setup_program_with_grid(
            "FIT", program_overrides={"aggregate_cap_watts": 10_000})
        ctx_s = add_customer_account(sc, "S")
        ctx_t = add_customer_account(sc, "T")
        app_s = _submit_for_capacity(sc, ctx_s, 10_000, production=15_000_000)
        app_t = _submit_for_capacity(sc, ctx_t, 5_000, production=6_000_000)

        # Exact fit: 10,000 W against exactly 10,000 W of headroom (>= semantics).
        assert app_s["application_status"] == "CAPACITY_RESERVED"
        assert app_s["capacity_reserved_watts"] == 10_000

        program = get_program(sc["program"]["id"])
        assert program["available_capacity_watts"] == 0
        assert program["reserved_watts"] == 10_000
        assert program["program_status"] == "CAP_REACHED"

        # The next applicant finds no capacity and queues at position 1.
        assert app_t["application_status"] == "WAITING_FOR_CAPACITY"
        assert app_t["queue_position"] == 1

    def test_release_restores_open_and_promotes(self, api):
        """PRD §2.7: "if it has risen above zero, a program in `CAP_REACHED`
        returns to `OPEN`."
        PRD §3.6: "each whose size fits within the current
        `available_capacity_watts` is promoted to `CAPACITY_RESERVED` with
        `capacity_reserved_watts` set to its size, a fresh 180-day
        `reservation_expires_at`, and its `queue_position` cleared to null"

        Design: Difficulty/boundary_precision_check/bpc_capacity_exact_fit_cap_reached
        """
        sc = setup_program_with_grid(
            "FIT2", program_overrides={"aggregate_cap_watts": 10_000})
        ctx_s = add_customer_account(sc, "S")
        ctx_t = add_customer_account(sc, "T")
        app_s = _submit_for_capacity(sc, ctx_s, 10_000, production=15_000_000)
        app_t = _submit_for_capacity(sc, ctx_t, 5_000, production=6_000_000)
        assert app_t["application_status"] == "WAITING_FOR_CAPACITY"

        get_success_data(
            api.withdraw_application(app_s["id"], ctx_s["applicant"]))

        app_t = get_application(app_t["id"])
        assert app_t["application_status"] == "CAPACITY_RESERVED"
        assert app_t["capacity_reserved_watts"] == 5_000
        assert app_t["queue_position"] is None
        program = get_program(sc["program"]["id"])
        assert program["program_status"] == "OPEN"
        assert program["reserved_watts"] == 5_000
        assert program["available_capacity_watts"] == 5_000
        assert program["queued_count"] == 0


class TestQueuePromotionOrder:
    def test_ascending_order_promotes_smaller_fitters_first(self, api):
        """PRD §3.6: "the program's queued applications are considered in
        ascending `queue_position`; each whose size fits within the current
        `available_capacity_watts` is promoted to `CAPACITY_RESERVED` with
        `capacity_reserved_watts` set to its size, a fresh 180-day
        `reservation_expires_at`, and its `queue_position` cleared to null, its
        watts folded into `reserved_watts` and the equipment aggregates,
        `queued_count` decremented, and the available figure recomputed before
        the next candidate is considered. Applications that do not fit are
        skipped and remain queued, and the scan continues past them"

        Design: Difficulty/combinatorial_formula/cf_queue_promotion_evaluation_order
        """
        sc = setup_program_with_grid(
            "QPO", program_overrides={"aggregate_cap_watts": 50_000})
        ctxs = [add_customer_account(sc, str(i)) for i in range(1, 6)]
        app_a = _submit_for_capacity(sc, ctxs[0], 30_000)
        app_b = _submit_for_capacity(sc, ctxs[1], 20_000)
        app_c = _submit_for_capacity(sc, ctxs[2], 15_000)
        app_d = _submit_for_capacity(sc, ctxs[3], 10_000)
        app_e = _submit_for_capacity(sc, ctxs[4], 25_000)
        assert app_c["queue_position"] == 1
        assert app_d["queue_position"] == 2
        assert app_e["queue_position"] == 3
        assert get_program(sc["program"]["id"])["program_status"] == (
            "CAP_REACHED")

        # Releasing A's 30,000 W promotes C (15,000) then D (10,000); E's
        # 25,000 W no longer fits and would have won a largest-first scan.
        get_success_data(
            api.withdraw_application(app_a["id"], ctxs[0]["applicant"]))

        app_c = get_application(app_c["id"])
        assert app_c["application_status"] == "CAPACITY_RESERVED"
        assert app_c["capacity_reserved_watts"] == 15_000
        assert app_c["queue_position"] is None
        assert_instant_equal(app_c["reservation_expires_at"],
                             "2027-01-28T00:00:00Z",
                             "fresh 180-day reservation from the default clock")

        app_d = get_application(app_d["id"])
        assert app_d["application_status"] == "CAPACITY_RESERVED"
        assert app_d["capacity_reserved_watts"] == 10_000

        app_e = get_application(app_e["id"])
        assert app_e["application_status"] == "WAITING_FOR_CAPACITY"
        assert app_e["queue_position"] == 1, "renumbered down from 3"

        program = get_program(sc["program"]["id"])
        assert program["reserved_watts"] == 45_000
        assert program["available_capacity_watts"] == 5_000
        assert program["queued_count"] == 1
        assert program["program_status"] == "OPEN"

    def test_scan_recomputes_available_after_every_promotion(self, api):
        """PRD §3.6: "Applications that do not fit are skipped and remain
        queued, and the scan continues past them; evaluation order is pinned
        ascending, and the available capacity is recomputed after every
        promotion, so a different order could promote a different subset."

        Design: Difficulty/combinatorial_formula/cf_queue_promotion_evaluation_order
        """
        sc = setup_program_with_grid(
            "QPO2", program_overrides={"aggregate_cap_watts": 40_000})
        ctxs = [add_customer_account(sc, str(i)) for i in range(1, 5)]
        app_a = _submit_for_capacity(sc, ctxs[0], 25_000)
        app_b = _submit_for_capacity(sc, ctxs[1], 15_000)
        app_c = _submit_for_capacity(sc, ctxs[2], 20_000)
        app_d = _submit_for_capacity(sc, ctxs[3], 5_000)
        assert app_c["queue_position"] == 1
        assert app_d["queue_position"] == 2

        # Releasing 25,000 W: C (20,000) fits, leaving 5,000; D (5,000) then
        # exactly fits the recomputed remainder — both promote.
        get_success_data(
            api.withdraw_application(app_a["id"], ctxs[0]["applicant"]))

        for app, watts in ((app_c, 20_000), (app_d, 5_000)):
            app = get_application(app["id"])
            assert app["application_status"] == "CAPACITY_RESERVED"
            assert app["capacity_reserved_watts"] == watts
            assert app["queue_position"] is None

        program = get_program(sc["program"]["id"])
        assert program["reserved_watts"] == 40_000
        assert program["available_capacity_watts"] == 0
        assert program["queued_count"] == 0
        assert program["program_status"] == "CAP_REACHED", (
            "the promotion cascade recomputes posture and lands back on "
            "CAP_REACHED at exactly zero headroom")


class TestWithdrawalReleaseCascade:
    def test_withdrawal_promotes_queue_and_reconciles_grid(self, api):
        """PRD §3.6: "The release cascade then unwinds everything the
        application held: a queued application releases its `queue_position`,
        higher positions renumber down, and `queued_count` decreases; a
        reservation-holding application returns its watts to the program and
        equipment aggregates, zeroes `capacity_reserved_watts`, clears
        `reservation_expires_at`, and triggers the promotion scan and posture
        recompute."

        Design: Difficulty/transitive_cascade/tc_withdrawal_release_promotion_cascade
        """
        sc = setup_program_with_grid(
            "CASC", program_overrides={"aggregate_cap_watts": 60_000})
        ctxs = [add_customer_account(sc, str(i)) for i in range(1, 6)]
        app_a = _submit_for_capacity(sc, ctxs[0], 40_000)
        app_b = _submit_for_capacity(sc, ctxs[1], 20_000)
        app_c = _submit_for_capacity(sc, ctxs[2], 25_000)
        app_d = _submit_for_capacity(sc, ctxs[3], 10_000)
        app_e = _submit_for_capacity(sc, ctxs[4], 35_000)
        assert get_program(sc["program"]["id"])["program_status"] == (
            "CAP_REACHED")

        get_success_data(
            api.withdraw_application(app_a["id"], ctxs[0]["applicant"]))

        app_a = get_application(app_a["id"])
        assert app_a["application_status"] == "WITHDRAWN"
        assert app_a["withdrawal_reason"] == "APPLICANT_WITHDRAWN"

        app_c = get_application(app_c["id"])
        assert app_c["application_status"] == "CAPACITY_RESERVED"
        assert app_c["capacity_reserved_watts"] == 25_000
        assert app_c["queue_position"] is None
        assert_instant_equal(app_c["reservation_expires_at"],
                             "2027-01-28T00:00:00Z",
                             "fresh 180-day reservation at promotion")

        app_d = get_application(app_d["id"])
        assert app_d["application_status"] == "CAPACITY_RESERVED"
        assert app_d["capacity_reserved_watts"] == 10_000

        app_e = get_application(app_e["id"])
        assert app_e["application_status"] == "WAITING_FOR_CAPACITY"
        assert app_e["queue_position"] == 1

        program = get_program(sc["program"]["id"])
        assert program["reserved_watts"] == 55_000
        assert program["available_capacity_watts"] == 5_000
        assert program["interconnected_watts"] == 0
        assert program["queued_count"] == 1
        assert program["program_status"] == "OPEN"

        # Grid aggregates track the same reservation set.
        assert get_feeder(sc["feeder"]["id"])["aggregate_der_watts"] == 55_000
        assert (get_transformer(sc["transformer"]["id"])
                ["aggregate_der_watts"] == 55_000)

    def test_denial_releases_reservation_and_promotes(self, api):
        """PRD §3.4: "`DENIED` terminates the application with `denial_reason`
        `TECHNICALLY_INFEASIBLE`, releases its reservation — subtracting the
        reserved watts from the program, transformer, and feeder aggregates,
        zeroing `capacity_reserved_watts`, and clearing
        `reservation_expires_at` — and triggers the queue promotion scan and
        posture recompute."

        Design: Difficulty/transitive_cascade/tc_withdrawal_release_promotion_cascade
        """
        sc = setup_program_with_grid(
            "CASC2", program_overrides={"aggregate_cap_watts": 30_000},
            feeder_overrides={"peak_load_watts": 1_000_000,
                              "pre_existing_der_watts": 140_000})
        # Second, clean feeder/transformer pair for the queued application.
        feeder2 = create_feeder("F-CASC2B", peak_load_watts=10_000_000,
                                pre_existing_der_watts=0)
        tx2 = create_transformer(feeder2["id"], "T-CASC2B",
                                 nameplate_watts=10_000_000,
                                 pre_existing_der_watts=0)

        ctx_a = add_customer_account(sc, "A",
                                     prior_annual_usage_wh=100_000_000)
        app_a = _submit_for_capacity(sc, ctx_a, 20_000)
        assert app_a["application_status"] == "CAPACITY_RESERVED"
        report = validate_success(api.create_screening_report(
            {"application_id": app_a["id"]}, ENGINEER), 201)
        assert report["outcome"] == "FAILED"

        ctx_b = add_customer_account(sc, "B",
                                     prior_annual_usage_wh=100_000_000,
                                     transformer=tx2)
        app_b = _submit_for_capacity(sc, ctx_b, 15_000)
        assert app_b["application_status"] == "WAITING_FOR_CAPACITY"
        assert app_b["queue_position"] == 1

        review = get_success_data(api.create_supplemental_review(
            {"application_id": app_a["id"], "review_type": "FACILITIES_STUDY"},
            ENGINEER))
        review = validate_success(api.complete_supplemental_review(
            review["id"], {"outcome": "DENIED"}, ENGINEER))
        assert review["outcome"] == "DENIED"

        app_a = get_application(app_a["id"])
        assert app_a["application_status"] == "DENIED"
        assert app_a["denial_reason"] == "TECHNICALLY_INFEASIBLE"
        assert app_a["capacity_reserved_watts"] == 0
        assert app_a["reservation_expires_at"] is None

        # The release promotes the queued 15,000 W application.
        app_b = get_application(app_b["id"])
        assert app_b["application_status"] == "CAPACITY_RESERVED"
        assert app_b["capacity_reserved_watts"] == 15_000
        assert app_b["queue_position"] is None

        program = get_program(sc["program"]["id"])
        assert program["reserved_watts"] == 15_000
        assert program["available_capacity_watts"] == 15_000
        assert program["queued_count"] == 0
        assert program["program_status"] == "OPEN"
        assert (get_feeder(sc["feeder"]["id"])["aggregate_der_watts"]
                == 140_000), "only pre-existing DER remains on feeder 1"


class TestCapacityConservation:
    def test_reserve_then_withdraw_restores_capacity_exactly(self, api):
        """PRD §2.7: "The program's `available_capacity_watts` is its
        `aggregate_cap_watts` minus its `interconnected_watts` minus its
        `reserved_watts`"
        PRD §3.6: "a reservation-holding application returns its watts to the
        program and equipment aggregates, zeroes `capacity_reserved_watts`,
        clears `reservation_expires_at`, and triggers the promotion scan and
        posture recompute."

        Design: Difficulty/compensating_invariant/ci_reserve_withdraw_capacity_conservation
        """
        sc = setup_program_with_grid("INV")
        ctx = add_customer_account(sc, "1")

        program = get_program(sc["program"]["id"])
        assert program["available_capacity_watts"] == 1_000_000
        assert program["interconnected_watts"] == 0
        assert program["reserved_watts"] == 0

        app = _submit_for_capacity(sc, ctx, 10_000, production=15_000_000)
        assert app["application_status"] == "CAPACITY_RESERVED"
        program = get_program(sc["program"]["id"])
        assert program["reserved_watts"] == 10_000
        assert program["available_capacity_watts"] == 990_000
        assert_capacity_ledger_invariant(program)

        get_success_data(api.withdraw_application(app["id"], ctx["applicant"]))
        program = get_program(sc["program"]["id"])
        assert program["reserved_watts"] == 0
        assert program["available_capacity_watts"] == 1_000_000, (
            "the forward reservation and the compensating withdrawal restore "
            "available capacity exactly")
        assert_capacity_ledger_invariant(program)

        app = get_application(app["id"])
        assert app["application_status"] == "WITHDRAWN"
        assert app["withdrawal_reason"] == "APPLICANT_WITHDRAWN"
        assert app["capacity_reserved_watts"] == 0
        assert app["reservation_expires_at"] is None
        assert get_transformer(sc["transformer"]["id"])["aggregate_der_watts"] == 0
        assert get_feeder(sc["feeder"]["id"])["aggregate_der_watts"] == 0

    def test_pto_converts_reserved_to_interconnected_watt_for_watt(self, api):
        """PRD §3.8: "The grant's side effects convert the reservation into
        live capacity: `pto_granted_at` is stamped, the program's
        `reserved_watts` falls by the reserved amount while
        `interconnected_watts` rises by the same amount — leaving
        `available_capacity_watts` unchanged — `capacity_reserved_watts`
        returns to zero, `reservation_expires_at` is cleared, and the account's
        `metering_status` moves from `STANDARD` to `NET_METERING`, unlocking
        billing."

        Design: Difficulty/compensating_invariant/ci_reserve_withdraw_capacity_conservation
        """
        sc = setup_program_with_grid("INV2")
        ctx = add_customer_account(sc, "1")
        result = drive_to_pto_granted(sc, ctx, size=10_000,
                                      production=15_000_000)
        app = result["app"]

        program = get_program(sc["program"]["id"])
        assert program["reserved_watts"] == 0
        assert program["interconnected_watts"] == 10_000
        assert program["available_capacity_watts"] == 990_000, (
            "reserved converts to interconnected one-for-one; available is "
            "unchanged by the grant")
        assert_capacity_ledger_invariant(program)

        assert app["capacity_reserved_watts"] == 0
        assert app["reservation_expires_at"] is None
        assert_instant_equal(app["pto_granted_at"], "2026-08-06T00:00:00Z",
                             "pto_granted_at stamped with the logical clock")
        account = get_account(ctx["account"]["id"])
        assert account["metering_status"] == "NET_METERING"


class TestExpirySweep:
    def test_sweep_expires_estimate_then_reservation_then_promotes(self, api):
        """PRD §2.4: "The sweep is a `ProgramAdministrator`-initiated,
        per-program operation that processes expirations in a pinned order.
        First, every still-`ISSUED` upgrade cost estimate of the program whose
        `valid_until` is earlier than the current clock time is expired; each
        affected application is withdrawn with `withdrawal_reason`
        `ESTIMATE_EXPIRED`, processed in ascending order of the application's
        `created_at`. Second, every application of the program still holding a
        reservation whose `reservation_expires_at` is earlier than the current
        clock time is withdrawn with `withdrawal_reason` `RESERVATION_EXPIRED`,
        again in ascending `created_at` order. Third, the freed capacity
        triggers the queue promotion scan described in §3.3. Fourth, the
        program's capacity posture is recomputed per §2.7."

        Design: Corner/endpoints/ep_sweep_expires_estimate_and_reservation
        """
        sc = setup_program_with_grid(
            "SWP", program_overrides={"aggregate_cap_watts": 30_000},
            feeder_overrides={"peak_load_watts": 1_000_000,
                              "pre_existing_der_watts": 140_000})
        feeder2 = create_feeder("F-SWP2", peak_load_watts=10_000_000,
                                pre_existing_der_watts=0)
        tx2 = create_transformer(feeder2["id"], "T-SWP2",
                                 nameplate_watts=10_000_000,
                                 pre_existing_der_watts=0)

        # app1: fails the feeder screen, lands in CUSTOMER_DECISION_PENDING
        # with an ISSUED estimate (created at the default clock, so
        # valid_until 2026-08-31T00:00:00Z).
        ctx1 = add_customer_account(sc, "1",
                                    prior_annual_usage_wh=100_000_000)
        app1 = _submit_for_capacity(sc, ctx1, 20_000)
        report1 = validate_success(api.create_screening_report(
            {"application_id": app1["id"]}, ENGINEER), 201)
        assert report1["outcome"] == "FAILED"
        review1 = get_success_data(api.create_supplemental_review(
            create_supplemental_review_payload(app1["id"]), ENGINEER))
        review1 = get_success_data(api.complete_supplemental_review(
            review1["id"], {"outcome": "UPGRADES_REQUIRED"}, ENGINEER))
        app1 = get_application(app1["id"])
        est1 = validate_success(api.create_cost_estimate(
            create_cost_estimate_payload(
                app1["id"], review1["id"], app1["version"],
                items=[{"description": "transformer", "amount_cents": 50_000}],
                contingency_pct=10), ENGINEER), 201)

        # app2: exact-fits the remaining 10,000 W (reservation expires
        # 2027-01-28T00:00:00Z at the default clock).
        ctx2 = add_customer_account(sc, "2",
                                    prior_annual_usage_wh=100_000_000,
                                    transformer=tx2)
        app2 = _submit_for_capacity(sc, ctx2, 10_000)
        assert app2["application_status"] == "CAPACITY_RESERVED"

        # app3: queued behind the full program.
        ctx3 = add_customer_account(sc, "3",
                                    prior_annual_usage_wh=100_000_000,
                                    transformer=tx2)
        app3 = _submit_for_capacity(sc, ctx3, 8_000)
        assert app3["application_status"] == "WAITING_FOR_CAPACITY"
        assert app3["queue_position"] == 1

        set_clock("2027-02-01T00:00:00Z")
        validate_success(api.sweep_program(sc["program"]["id"], ADMIN))

        est1 = validate_success(api.get_cost_estimate(est1["id"], ADMIN))
        assert est1["estimate_status"] == "EXPIRED"
        app1 = get_application(app1["id"])
        assert app1["application_status"] == "WITHDRAWN"
        assert app1["withdrawal_reason"] == "ESTIMATE_EXPIRED"

        app2 = get_application(app2["id"])
        assert app2["application_status"] == "WITHDRAWN"
        assert app2["withdrawal_reason"] == "RESERVATION_EXPIRED"

        app3 = get_application(app3["id"])
        assert app3["application_status"] == "CAPACITY_RESERVED"
        assert app3["capacity_reserved_watts"] == 8_000
        assert app3["queue_position"] is None
        assert_instant_equal(app3["reservation_expires_at"],
                             "2027-07-31T00:00:00Z",
                             "sweep-instant 2027-02-01 plus 180 days")

        program = get_program(sc["program"]["id"])
        assert program["reserved_watts"] == 8_000
        assert program["available_capacity_watts"] == 22_000
        assert program["queued_count"] == 0
        assert program["program_status"] == "OPEN"
