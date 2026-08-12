"""Shared-cost pool, refundable deposit, cleanup reporting, completion, and the
cancel/deny/expire unwind chains (PRD §3.7, §3.8, §3.9)."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_contribution,
    assert_cost_share_pool,
    contribute_record,
    create_deposit_record,
    create_pool_record,
    create_report_record,
    create_reservation_record,
    create_stock_record,
    dispatch_then_return,
    inspect_report_payload,
    make_organizer_headers,
    set_logical_clock,
    setup_issued_application,
    setup_under_review_application,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["permit_officer_headers"]


def _under_review_with_pool(api, *, target=30000, contributions=(12000, 18000),
                            with_reservation=True, with_deposit=True):
    ctx = setup_under_review_application(segment_overrides={"length_m": 12})
    app, organizer = ctx["application"], ctx["organizer"]
    if with_reservation:
        stock = create_stock_record(equipment_kind="BARRICADE", total_units=5)
        reservation = create_reservation_record(app, organizer, "BARRICADE", 1)
        ctx.update(stock=stock, reservation=reservation)
    if with_deposit:
        ctx["deposit"] = create_deposit_record(app, organizer)
    pool = create_pool_record(app, organizer, target)
    ctx["pool"] = pool
    ctx["contributions"] = [
        contribute_record(pool["id"], household_address=f"{i + 1} Birch Rd", amount_cents=amt)
        for i, amt in enumerate(contributions)
    ]
    return ctx


class TestCancelPoolRefundChain:
    def test_pool_funded_at_exact_target(self, api):
        """PRD §3.7: "the moment the running total reaches or exceeds `target_cents` —
        equality funds — the pool flips to `FUNDED`."

        Design: Difficulty/transitive_cascade/cancel_triggers_pool_refund_chain
        """
        ctx = _under_review_with_pool(api)
        headers = make_organizer_headers(ctx["organizer"]["id"])
        pool = validate_success(api.get_cost_share_pool(ctx["pool"]["id"], headers), 200)
        assert pool["status"] == "FUNDED"
        assert pool["collected_cents"] == 30000, "12000 + 18000 reaches the target exactly"
        assert pool["refunded_cents"] == 0

    def test_cancel_runs_refund_chain_and_unwinds(self, api):
        """PRD §3.7: "On the application becoming `CANCELLED`, `REVOKED`, `DENIED`, or
        `EXPIRED`, a pool in `OPEN` or `FUNDED` enters `REFUNDING`; every `PAID` contribution
        flips to `REFUNDED` with `refunded_at` stamped from the logical clock, the pool's
        `refunded_cents` accumulating each amount while `collected_cents` shrinks by the
        same; and once no `PAID` contributions remain the pool settles into terminal
        `REFUNDED` — all within the same request that triggered the chain."
        PRD §3.9: "From `UNDER_REVIEW`, `SUSPENDED`, or `APPROVED`, cancellation additionally
        unwinds the application's commitments: each `HELD` reservation becomes `CANCELLED`
        and releases its stock reservation; a `HELD` deposit auto-settles to `SETTLED` with
        `refund_cents` equal to `held_cents` minus `charges_cents`; and an `OPEN` or `FUNDED`
        pool runs the refund chain to `REFUNDED`."

        Design: Difficulty/transitive_cascade/cancel_triggers_pool_refund_chain
        """
        ctx = _under_review_with_pool(api)
        organizer = ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        cancelled = validate_success(
            api.cancel_permit_application(
                ctx["application"]["id"], {"reason": "organizer moved away"}, headers
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"

        pool = validate_success(api.get_cost_share_pool(ctx["pool"]["id"], headers), 200)
        assert pool["status"] == "REFUNDED"
        assert pool["collected_cents"] == 0
        assert pool["refunded_cents"] == 30000
        contributions = validate_success(api.list_contributions(ctx["pool"]["id"], headers), 200)
        assert len(contributions) == 2
        for contribution in contributions:
            assert_contribution(contribution)
            assert contribution["status"] == "REFUNDED"
            assert contribution["refunded_at"] is not None

        reservation = validate_success(
            api.get_equipment_reservation(ctx["reservation"]["id"], headers), 200
        )
        assert reservation["reservation_status"] == "CANCELLED"
        deposit = validate_success(api.get_deposit(ctx["deposit"]["id"], headers), 200)
        assert deposit["status"] == "SETTLED"
        assert deposit["refund_cents"] == 10000

        # The released reservation no longer tallies inside the event's buffered window.
        set_logical_clock("2026-06-20T15:00:00Z")
        stock = validate_success(api.get_equipment_stock(ctx["stock"]["id"], OFFICER), 200)
        assert stock["reserved_units"] == 0
        assert stock["available_units"] == 5


class TestContributionCentConservation:
    def test_forward_contributions_accumulate_collected(self, api):
        """PRD §3.7: "Each contribution is stamped `PAID` with `refunded_at` empty, its
        `pool_id` tying it to the pool, and the pool's `collected_cents` grows by the
        amount".

        Design: Difficulty/compensating_invariant/contribution_cent_conservation_invariant
        """
        ctx = _under_review_with_pool(api, with_reservation=False, with_deposit=False)
        headers = make_organizer_headers(ctx["organizer"]["id"])
        pool = validate_success(api.get_cost_share_pool(ctx["pool"]["id"], headers), 200)
        assert pool["status"] == "FUNDED"
        assert pool["collected_cents"] == 30000 == 12000 + 18000
        assert pool["refunded_cents"] == 0
        # Conservation: collected + refunded equals lifetime contributed at every step.
        assert pool["collected_cents"] + pool["refunded_cents"] == 30000

    def test_compensating_refunds_conserve_cents(self, api):
        """PRD §3.7: "every `PAID` contribution flips to `REFUNDED` with `refunded_at`
        stamped from the logical clock, the pool's `refunded_cents` accumulating each amount
        while `collected_cents` shrinks by the same; and once no `PAID` contributions remain
        the pool settles into terminal `REFUNDED`".

        Design: Difficulty/compensating_invariant/contribution_cent_conservation_invariant
        """
        ctx = _under_review_with_pool(api, with_reservation=False, with_deposit=False)
        organizer = ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        validate_success(
            api.cancel_permit_application(ctx["application"]["id"], {}, headers), 200
        )
        pool = validate_success(api.get_cost_share_pool(ctx["pool"]["id"], headers), 200)
        assert pool["status"] == "REFUNDED"
        assert pool["collected_cents"] == 0
        assert pool["refunded_cents"] == 30000
        assert pool["collected_cents"] + pool["refunded_cents"] == 30000


class TestFailedInspectionCascade:
    def _issued_late_returned(self, api):
        ctx = setup_issued_application(
            application_overrides={"expected_attendance": 100},
            segment_overrides={"length_m": 48},
            tcp_overrides={"barricade_count": 4},
            stocks=[{"equipment_kind": "BARRICADE", "total_units": 10}],
            reservations=[{"equipment_kind": "BARRICADE", "units": 4}],
        )
        # Dispatch inside the window; return 12h past the 06-22T22:00 deadline.
        dispatch_then_return(
            ctx, dispatch_at="2026-06-19T15:00:00Z", return_at="2026-06-23T10:00:00Z",
            returned_units=4,
        )
        return ctx

    def test_late_return_posts_charge_without_forfeiting(self, api):
        """PRD §3.6: "A late return posts a `LATE_EQUIPMENT` ChargeEntry of `returned_units`
        times the kind's unit rate times two, times `late_days`, written only when positive."
        PRD §3.6: "Charges then post, but only while the application's deposit is still
        `HELD`."

        Design: Difficulty/transitive_cascade/failed_inspection_forfeits_deposit_and_flags_organizer
        """
        ctx = self._issued_late_returned(api)
        reservation = ctx["reservations"][0]
        assert reservation["late_days"] == 1
        headers = make_organizer_headers(ctx["organizer"]["id"])
        charges = validate_success(api.list_deposit_charges(ctx["deposit"]["id"], headers), 200)
        assert len(charges) == 1
        assert charges[0]["kind"] == "LATE_EQUIPMENT"
        assert charges[0]["amount_cents"] == 2000, "4 * 250 * 2 * 1 late day"
        deposit = validate_success(api.get_deposit(ctx["deposit"]["id"], headers), 200)
        assert deposit["charges_cents"] == 2000
        assert deposit["status"] == "HELD", "2000 < held 10000 -> no forfeiture yet"

    def test_cleaning_charge_forfeits_deposit_and_flags_organizer(self, api):
        """PRD §3.8: "A `FAILED` result records `inspected_by`, stores the supplied
        `cleaning_charge_cents`, and — when that figure is positive and the application's
        deposit is still `HELD` — posts a `CLEANING` ChargeEntry against the deposit."
        PRD §3.6: "Should posted charges push the deposit's `charges_cents` to meet or exceed
        its `held_cents`, the deposit forfeits on the spot: `HELD` becomes `FORFEITED` with
        `refund_cents` zeroed, and the organizer's standing takes the demotion described in
        §3.1."

        Design: Difficulty/transitive_cascade/failed_inspection_forfeits_deposit_and_flags_organizer
        """
        ctx = self._issued_late_returned(api)
        organizer = ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        report = create_report_record(
            ctx["application"], organizer,
            cleanup_completed=False, cleanup_notes="debris left on curb",
        )
        inspected = validate_success(
            api.inspect_post_event_report(
                report["id"], inspect_report_payload("FAILED", cleaning_charge_cents=9000), OFFICER
            ),
            200,
        )
        assert inspected["inspection_result"] == "FAILED"
        assert inspected["cleaning_charge_cents"] == 9000

        charges = validate_success(api.list_deposit_charges(ctx["deposit"]["id"], headers), 200)
        assert sorted(c["amount_cents"] for c in charges) == [2000, 9000]
        assert {c["kind"] for c in charges} == {"LATE_EQUIPMENT", "CLEANING"}
        deposit = validate_success(api.get_deposit(ctx["deposit"]["id"], headers), 200)
        assert deposit["charges_cents"] == 11000
        assert deposit["status"] == "FORFEITED", "11000 >= held 10000"
        assert deposit["refund_cents"] == 0

        organizer_now = validate_success(api.get_organizer(organizer["id"], OFFICER), 200)
        assert organizer_now["standing"] == "FLAGGED"
        assert organizer_now["forfeiture_count"] == 1


class TestPoolBoundaries:
    def test_contribution_min_and_pool_funding_boundary(self, api):
        """PRD §3.7: "Neighbors contribute by naming their `household_address` and an
        `amount_cents` of at least 100 cents — smaller offerings are refused with
        `ERR_CONTRIBUTION_BELOW_MIN` — and only into an `OPEN` pool, contributions against
        any other state failing with `ERR_POOL_NOT_OPEN`."
        PRD §3.7: "the moment the running total reaches or exceeds `target_cents` — equality
        funds — the pool flips to `FUNDED`."

        Design: Corner/errors/contribution_min_and_pool_funding_boundary
        """
        ctx = _under_review_with_pool(api, target=500, contributions=(),
                                      with_reservation=False, with_deposit=False)
        pool = ctx["pool"]
        headers = make_organizer_headers(ctx["organizer"]["id"])
        res = api.create_contribution(
            pool["id"], {"household_address": "1 Birch Rd", "amount_cents": 99},
            TEST_USERS["neighbor_headers"],
        )
        validate_error(res, "ERR_CONTRIBUTION_BELOW_MIN")
        contribute_record(pool["id"], household_address="1 Birch Rd", amount_cents=100)
        contribute_record(pool["id"], household_address="2 Birch Rd", amount_cents=400)
        pool_now = validate_success(api.get_cost_share_pool(pool["id"], headers), 200)
        assert pool_now["status"] == "FUNDED"
        assert pool_now["collected_cents"] == 500, "100 + 400 reaches the target exactly"
        res = api.create_contribution(
            pool["id"], {"household_address": "3 Birch Rd", "amount_cents": 100},
            TEST_USERS["neighbor_headers"],
        )
        validate_error(res, "ERR_POOL_NOT_OPEN")


class TestTerminalAndLazyTransitions:
    def test_denied_application_terminal_lockdown(self, api):
        """PRD §3.5: "Denial moves the application from `UNDER_REVIEW` to terminal `DENIED`
        with `decision_reason` set".
        PRD §2.6: "**State gates** — the target resource is in a state that permits the
        transition".

        Design: Corner/state_machines/denied_application_terminal_lockdown
        """
        ctx = setup_under_review_application()
        app, organizer = ctx["application"], ctx["organizer"]
        denied = validate_success(
            api.deny_permit_application(app["id"], {"reason": "street work scheduled"}, OFFICER),
            200,
        )
        assert denied["status"] == "DENIED"
        assert denied["decision_reason"] == "street work scheduled"
        res = api.approve_permit_application(app["id"], OFFICER)
        validate_error(res, "ERR_INVALID_STATE")

    def test_lazy_expiry_unwinds_past_event_application(self, api):
        """PRD §3.9: "On any access to an application whose `event_end_at` has passed on the
        logical clock, a status of `DRAFT`, `UNDER_REVIEW`, `SUSPENDED`, or `APPROVED`
        lazily collapses to terminal `EXPIRED`, with the same unwind as a pre-issuance
        cancellation — held reservations cancelled and released, the deposit auto-settled,
        the pool refunded."

        Design: Corner/state_machines/lazy_expiry_of_past_event_application
        """
        ctx = _under_review_with_pool(api, target=500, contributions=(500,),
                                      with_reservation=True, with_deposit=False)
        organizer = ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        set_logical_clock("2026-06-21T00:00:00Z")  # past event_end 06-20T22:00
        application = validate_success(
            api.get_permit_application(ctx["application"]["id"], headers), 200
        )
        assert application["status"] == "EXPIRED"
        reservation = validate_success(
            api.get_equipment_reservation(ctx["reservation"]["id"], headers), 200
        )
        assert reservation["reservation_status"] == "CANCELLED"
        pool = validate_success(api.get_cost_share_pool(ctx["pool"]["id"], headers), 200)
        assert pool["status"] == "REFUNDED"
        assert pool["refunded_cents"] == 500


class TestReportWindowAndCompletion:
    def test_report_window_inclusive_end_exclusive_start(self, api):
        """PRD §3.8: "the filing must land after `event_end_at` and no later than 72 hours
        after it — the window is open at the start (a report exactly at `event_end_at` is
        too early) and closed at the end (a report exactly 72 hours after is still inside) —
        with violations rejected as `ERR_REPORT_WINDOW_CLOSED`."

        Design: Corner/errors/report_window_boundary_and_closed
        """
        ctx = setup_issued_application(
            segment_overrides={"length_m": 12},
            tcp_overrides={"barricade_count": 1},
            stocks=[{"equipment_kind": "BARRICADE", "total_units": 5}],
            reservations=[{"equipment_kind": "BARRICADE", "units": 1}],
        )
        app, organizer = ctx["application"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        # Deadline is event_end 06-20T22:00 + 72h = 06-23T22:00; one second later is closed.
        set_logical_clock("2026-06-23T22:00:01Z")
        res = api.create_post_event_report(
            app["id"], {"cleanup_completed": True, "cleanup_notes": "done"}, headers
        )
        validate_error(res, "ERR_REPORT_WINDOW_CLOSED")
        # Exactly at the deadline is still inside the window.
        set_logical_clock("2026-06-23T22:00:00Z")
        report = validate_success(
            api.create_post_event_report(
                app["id"], {"cleanup_completed": True, "cleanup_notes": "done"}, headers
            ),
            201,
        )
        assert report["inspection_result"] == "PENDING"

    def test_completion_blocked_without_passed_report(self, api):
        """PRD §3.8: "Completion is the permit office's final gate on an `ISSUED`
        application, and every condition must hold: the logical clock has passed
        `event_end_at`; the latest post-event report's `inspection_result` is `PASSED`; every
        equipment reservation stands in a terminal state — `CLOSED`, `CANCELLED`, or
        `RECALLED`; the deposit, if one exists, is `SETTLED` or `FORFEITED`; and the
        cost-share pool, if one exists, is `CLOSED` or `REFUNDED`. Any shortfall rejects the
        completion with `ERR_COMPLETION_PRECONDITIONS`".

        Design: Corner/errors/completion_gate_blocked_returns_409
        """
        ctx = setup_issued_application(
            segment_overrides={"length_m": 12},
            tcp_overrides={"barricade_count": 1},
            stocks=[{"equipment_kind": "BARRICADE", "total_units": 5}],
            reservations=[{"equipment_kind": "BARRICADE", "units": 1}],
        )
        set_logical_clock("2026-06-21T10:00:00Z")  # past event_end, no report filed
        res = api.complete_permit_application(ctx["application"]["id"], OFFICER)
        validate_error(res, "ERR_COMPLETION_PRECONDITIONS")
        application = validate_success(
            api.get_permit_application(
                ctx["application"]["id"], make_organizer_headers(ctx["organizer"]["id"])), 200
        )
        assert application["status"] == "ISSUED"
