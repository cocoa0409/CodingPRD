"""
Closing a placement: the termination and return-to-district fork siblings.

Both arms release the unspent contract commitment and unwind transportation
identically; they diverge in the addenda's terminal state, the fate of the
transition reserve and the fate of disputed invoices. The termination arm also
carries the four-hop transitive chain that books money against another student's
placement.
"""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger,
    assert_route_seats,
)
from test_helpers.fixtures import (
    ATTENDANCE_FILING_INSTANT,
    FULL_MONTH_PERIOD,
    activate_plan,
    add_authorized_addendum,
    approve_payment,
    assign_transport,
    build_active_day_placement,
    build_two_addenda_billing_cycle,
    create_invoice,
    file_attendance,
    list_rows,
    make_contracted_placement,
    make_draft_plan,
    make_student,
    read_account,
    read_addendum,
    read_assignment,
    read_invoice,
    read_placement,
    read_plan,
    read_route,
    read_student,
    return_placement_to_district,
    set_clock,
    submit_accepted_report,
    terminate_placement,
    verify_attendance,
    verify_invoice,
)
from test_helpers.test_users import COORDINATOR_HEADERS

AUTHORIZED_CENTS = 100000000
CONTRACT_ENCUMBRANCE_CENTS = 5760000
SPEECH_ENCUMBRANCE_CENTS = 792000
OT_ENCUMBRANCE_CENTS = 594000
RESERVE_CENTS = 250000
CLOSURE_INSTANT = "2026-11-02T09:00:00Z"

# ─── The fork world: one addendum, an ACTIVE plan and a DISPUTED invoice ───────
FORK_Q1 = {
    "goals_total": 10,
    "goals_met": 6,
    "goals_regressed": 1,
    "benchmark_scaled_score": 60,
    "attendance_rate_pct": 90,
}
FORK_Q2 = dict(FORK_Q1, attendance_rate_pct=95)
FORK_READINESS_SCORE = 62.50
DISPUTED_SUBMITTED_CENTS = 900000
DISPUTED_VERIFIED_CENTS = 712363
FORK_RELEASE_ON_RETURN_CENTS = 6552000
FORK_RELEASE_ON_TERMINATE_CENTS = 6802000
AVAILABLE_AFTER_RETURN_CENTS = 99750000
RECEIVING_LRE_SETTING = "SEPARATE_CLASS_UNDER_40"
TRANSITION_SERVICES = ["Transition IEP meeting", "Two-week reverse mainstream trial"]


def _fork_world(api):
    """
    An ACTIVE placement carrying every component the two closure arms treat
    differently: one ACTIVE addendum, an ACTIVE transition plan holding a reserve,
    and one DISPUTED, UNPAID invoice.
    """
    world = build_active_day_placement(api)
    placement_id = world["placement"]["id"]
    world["addendum"] = add_authorized_addendum(api, placement_id)
    submit_accepted_report(api, placement_id, 1, **dict(FORK_Q1))
    submit_accepted_report(api, placement_id, 2, **dict(FORK_Q2))
    plan = make_draft_plan(api, placement_id)
    world["plan"] = activate_plan(
        api,
        plan["id"],
        transition_services=list(TRANSITION_SERVICES),
        readiness_variant="trailing_two_quarter",
    )

    set_clock(api, ATTENDANCE_FILING_INSTANT)
    record = file_attendance(
        api,
        world,
        placement_id,
        days_enrolled=20,
        days_attended=16,
        days_absent_unexcused=4,
        residential_nights=0,
        service_delivery_lines=[f.service_line(world["addendum"]["id"], 7.5)],
        **FULL_MONTH_PERIOD,
    )
    verify_attendance(api, record["id"])
    invoice = create_invoice(
        api, world, placement_id, record["id"], DISPUTED_SUBMITTED_CENTS
    )
    world["invoice"] = verify_invoice(api, invoice["id"], basis="ATTENDANCE")
    set_clock(api, CLOSURE_INSTANT)
    return world


class TestClosureFork:
    """The two closure siblings applied to identical worlds."""

    def test_return_to_district_transfers_the_addendum_and_keeps_the_reserve(
        self, api
    ):
        """
        Returning the student home hands the services on, completes the plan with
        its reserve still encumbered and leaves the disputed invoice standing.

        PRD: "The `ACTIVE` `ReturnTransitionPlan` transitions `ACTIVE → COMPLETED` rather than `ACTIVE → ABANDONED`, and its reserve is **not** released: the plan's `reserve_cents` and the placement's `transition_reserve_cents` both keep the 250 000 cents encumbered, and the fiscal account's `encumbered_cents` is not reduced by it, so the post-return transition services stay funded."

        Design: Difficulty/non_linear_state_machine/placement_return_to_district_fork_diverges_from_terminate
        """
        world = _fork_world(api)
        placement_id = world["placement"]["id"]

        assert world["plan"]["readiness_score_at_activation"] == FORK_READINESS_SCORE
        assert world["invoice"]["verification_status"] == "DISPUTED"
        assert world["invoice"]["verified_amount_cents"] == DISPUTED_VERIFIED_CENTS
        assert world["invoice"]["payment_status"] == "UNPAID"

        closed = return_placement_to_district(
            api,
            placement_id,
            reason="Student met transition criteria; receiving program has capacity.",
            receiving_lre_setting=RECEIVING_LRE_SETTING,
        )

        assert closed["status"] == "RETURNED_TO_DISTRICT"
        assert closed["transition_reserve_cents"] == RESERVE_CENTS
        assert closed["released_encumbrance_cents"] == FORK_RELEASE_ON_RETURN_CENTS
        assert closed["encumbrance_cents"] == RESERVE_CENTS

        addendum = read_addendum(api, world["addendum"]["id"])
        assert addendum["status"] == "TRANSFERRED"
        assert addendum["encumbrance_cents"] == 0

        plan = read_plan(api, world["plan"]["id"])
        assert plan["status"] == "COMPLETED"
        assert plan["reserve_cents"] == RESERVE_CENTS

        invoice = read_invoice(api, world["invoice"]["id"])
        assert invoice["verification_status"] == "DISPUTED"
        assert invoice["payment_status"] == "UNPAID"

        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=AVAILABLE_AFTER_RETURN_CENTS,
            encumbered=RESERVE_CENTS,
            disbursed=0,
        )

        student = read_student(api, world["student"]["id"])
        assert student["placement_status"] == "RETURNED"
        assert student["lre_current_setting"] == RECEIVING_LRE_SETTING

    def test_termination_terminates_the_addendum_abandons_the_plan_and_voids(
        self, api
    ):
        """
        Terminating the same world instead stops the services, abandons the plan
        and releases its reserve, and voids the disputed invoice.

        PRD: "A `ReturnTransitionPlan` on the placement whose `status` is `ACTIVE` transitions `ACTIVE → ABANDONED`, releasing its reserve: the fiscal account has `encumbered_cents` decreased and `available_cents` increased by the plan's `reserve_cents`, the placement's `transition_reserve_cents` is set to 0, the plan's `reserve_cents` is set to 0, and the plan's `version` is incremented."

        Design: Difficulty/non_linear_state_machine/placement_return_to_district_fork_diverges_from_terminate
        """
        world = _fork_world(api)
        placement_id = world["placement"]["id"]

        closed = terminate_placement(
            api, placement_id, reason="Family withdrew the student from the school."
        )

        assert closed["status"] == "TERMINATED"
        assert closed["transition_reserve_cents"] == 0
        assert closed["released_encumbrance_cents"] == FORK_RELEASE_ON_TERMINATE_CENTS
        assert closed["encumbrance_cents"] == 0

        addendum = read_addendum(api, world["addendum"]["id"])
        assert addendum["status"] == "TERMINATED"
        assert addendum["encumbrance_cents"] == 0

        plan = read_plan(api, world["plan"]["id"])
        assert plan["status"] == "ABANDONED"
        assert plan["reserve_cents"] == 0

        invoice = read_invoice(api, world["invoice"]["id"])
        assert invoice["payment_status"] == "VOIDED"
        assert invoice["verification_status"] == "DISPUTED"
        assert invoice["settled_amount_cents"] == 0

        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=AUTHORIZED_CENTS,
            encumbered=0,
            disbursed=0,
        )

        student = read_student(api, world["student"]["id"])
        assert student["placement_status"] == "TERMINATED"
        assert student["lre_current_setting"] == "RESOURCE_40_79"


# ─── The transitive chain: release, freed seat, promotion, foreign encumbrance ─
PROMOTION_INSTANT = "2026-10-01T08:00:00Z"
ROUTE_SETTINGS = {
    "seat_capacity": 1,
    "daily_rate_cents": 6200,
    "service_window_start_min": 360,
    "service_window_end_min": 600,
}
SECOND_PICKUP = {"pickup_window_start_min": 470, "pickup_window_end_min": 500}
TRANSPORT_ENCUMBRANCE_CENTS = 1152270
PLACEMENT_B_ENCUMBRANCE_CENTS = 6912270
ENCUMBERED_AFTER_PROMOTION_CENTS = 6912270
AVAILABLE_AFTER_PROMOTION_CENTS = 93087730


def _waitlisted_pair_world(api):
    """
    Two placements riding one single-seat route: the first holds the seat and is
    ACTIVE, the second is CONTRACTED and waitlisted behind it.

    The second placement stays CONTRACTED because activation of a placement that
    requires transportation needs an ACTIVE assignment, which the waitlisted rider
    does not have; a CONTRACTED parent is exactly what the promotion selector's
    candidate filter admits.
    """
    world = build_active_day_placement(
        api,
        placement_overrides={"transportation_required": True},
        route_overrides=ROUTE_SETTINGS,
    )
    route = world["route"]
    assignment_a = world["assignment"]
    student_b = make_student(api, full_name="Teodora Vasquez")
    placement_b = make_contracted_placement(
        api, world, student=student_b, transportation_required=True
    )
    assignment_b = assign_transport(
        api, placement_b["id"], route["id"], **SECOND_PICKUP
    )
    set_clock(api, PROMOTION_INSTANT)
    world.update(
        student_b=student_b,
        placement_b=placement_b,
        route=route,
        assignment_a=assignment_a,
        assignment_b=assignment_b,
    )
    return world


class TestTerminationPromotesTheWaitlist:
    """Terminating one rider promotes the next one on the same route."""

    def test_the_freed_seat_is_immediately_retaken_by_the_promoted_rider(self, api):
        """
        Releasing the ACTIVE assignment returns its seat to the route, and the
        promotion selector takes that seat again inside the same cascade.

        PRD: "Only for assignments whose status immediately before release was `ACTIVE`: the route's `seats_committed` is decreased by one and `seats_available` increased by one with the route's `version` incremented, and the fiscal account has `encumbered_cents` decreased and `available_cents` increased by that assignment's `encumbrance_cents`, while the placement's `transport_encumbrance_cents` is decreased and `released_encumbrance_cents` increased by the same figure and the assignment's `encumbrance_cents` is zeroed."

        Design: Difficulty/transitive_cascade/terminate_frees_seat_then_promotes_waitlist_onto_a_second_placement
        """
        world = _waitlisted_pair_world(api)

        assert world["assignment_a"]["status"] == "ACTIVE"
        assert world["assignment_a"]["encumbrance_cents"] == (
            TRANSPORT_ENCUMBRANCE_CENTS
        )
        assert world["assignment_b"]["status"] == "WAITLISTED"
        assert world["assignment_b"]["encumbrance_cents"] == 0
        assert_route_seats(read_route(api, world["route"]["id"]), 1, 0)

        closed = terminate_placement(api, world["placement"]["id"])

        assert closed["status"] == "TERMINATED"
        assert closed["transport_status"] == "RELEASED"
        released = read_assignment(api, world["assignment_a"]["id"])
        assert released["status"] == "RELEASED"
        assert released["encumbrance_cents"] == 0

        assert_route_seats(read_route(api, world["route"]["id"]), 1, 0)
        promoted = read_assignment(api, world["assignment_b"]["id"])
        assert promoted["status"] == "ACTIVE"
        assert_instant_equals(promoted["promoted_at"], PROMOTION_INSTANT)

        rows, _meta = list_rows(
            api.list_transportation_assignments(
                COORDINATOR_HEADERS, {"route_id": world["route"]["id"]}
            )
        )
        assert len(rows) == 2
        assert sorted(row["status"] for row in rows) == ["ACTIVE", "RELEASED"]
        assert read_student(api, world["student"]["id"])["placement_status"] == (
            "TERMINATED"
        )

    def test_the_promotion_books_its_commitment_against_the_other_placement(
        self, api
    ):
        """
        The promoted assignment's commitment is charged to its own placement, so a
        termination on one student moves money onto a different student's row.

        PRD: "The promoted assignment's `encumbrance_cents` is computed by the transportation encumbrance rule of §3.4, that amount is added to **its own** placement's `transport_encumbrance_cents`, that placement's `transport_status` becomes `ASSIGNED` and its `version` is incremented, the fiscal account has `available_cents` decreased and `encumbered_cents` increased by the same amount, and the assignment's `promoted_at` is stamped with the logical clock's current instant."

        Design: Difficulty/transitive_cascade/terminate_frees_seat_then_promotes_waitlist_onto_a_second_placement
        """
        world = _waitlisted_pair_world(api)

        closed = terminate_placement(api, world["placement"]["id"])
        assert closed["released_encumbrance_cents"] == PLACEMENT_B_ENCUMBRANCE_CENTS
        assert closed["encumbrance_cents"] == 0
        assert closed["transport_encumbrance_cents"] == 0

        promoted = read_assignment(api, world["assignment_b"]["id"])
        assert promoted["encumbrance_cents"] == TRANSPORT_ENCUMBRANCE_CENTS

        placement_b = read_placement(api, world["placement_b"]["id"])
        assert placement_b["transport_status"] == "ASSIGNED"
        assert placement_b["transport_encumbrance_cents"] == (
            TRANSPORT_ENCUMBRANCE_CENTS
        )
        assert placement_b["encumbrance_cents"] == PLACEMENT_B_ENCUMBRANCE_CENTS
        assert placement_b["status"] == "CONTRACTED"

        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=AVAILABLE_AFTER_PROMOTION_CENTS,
            encumbered=ENCUMBERED_AFTER_PROMOTION_CENTS,
            disbursed=0,
        )


# ─── The conservation identity across a partial payment and a termination ─────
SETTLED_CENTS = 799411
GROSS_BILLABLE_CENTS = 793726
VOLUME_CREDIT_CENTS = 11906
ADMIN_FEE_CENTS = 17591
ENCUMBERED_BEFORE_PAYMENT_CENTS = 7146000
AVAILABLE_BEFORE_PAYMENT_CENTS = 92854000
ENCUMBERED_AFTER_PAYMENT_CENTS = 6346589
AVAILABLE_AFTER_TERMINATION_CENTS = 99200589
CONTRACT_RELEASE_CENTS = 4960589
TOTAL_RELEASE_CENTS = 6346589
TERMINATION_INSTANT = "2026-11-10T09:00:00Z"


def _paid_cycle_world(api):
    """A two-addendum world whose first billing cycle has been settled in full."""
    world = build_two_addenda_billing_cycle(api)
    invoice = create_invoice(
        api,
        world,
        world["placement"]["id"],
        world["record"]["id"],
        SETTLED_CENTS,
    )
    world["invoice"] = verify_invoice(api, invoice["id"], basis="ENROLLMENT")
    return world


class TestConservationAcrossPaymentAndTermination:
    """The account decomposition is re-checked at every observable point."""

    def test_the_identity_holds_before_payment_after_payment_and_after_closure(
        self, api
    ):
        """
        Three checkpoints: commitments booked, part of a commitment converted into
        a disbursement, and the remainder released by termination.

        PRD: "For every account, `authorized_cents` always equals the sum of `available_cents`, `encumbered_cents` and `disbursed_cents`."

        Design: Difficulty/compensating_invariant/fiscal_account_identity_survives_partial_payment_then_termination
        """
        world = _paid_cycle_world(api)
        account_id = world["account"]["id"]

        assert_ledger(
            read_account(api, account_id),
            available=AVAILABLE_BEFORE_PAYMENT_CENTS,
            encumbered=ENCUMBERED_BEFORE_PAYMENT_CENTS,
            disbursed=0,
        )
        assert world["invoice"]["gross_billable_cents"] == GROSS_BILLABLE_CENTS
        assert world["invoice"]["volume_credit_cents"] == VOLUME_CREDIT_CENTS
        assert world["invoice"]["admin_fee_cents"] == ADMIN_FEE_CENTS
        assert world["invoice"]["verified_amount_cents"] == SETTLED_CENTS

        approve_payment(api, world["invoice"]["id"])
        assert_ledger(
            read_account(api, account_id),
            available=AVAILABLE_BEFORE_PAYMENT_CENTS,
            encumbered=ENCUMBERED_AFTER_PAYMENT_CENTS,
            disbursed=SETTLED_CENTS,
        )
        paid = read_placement(api, world["placement"]["id"])
        assert paid["paid_total_ytd_cents"] == SETTLED_CENTS

        set_clock(api, TERMINATION_INSTANT)
        terminate_placement(api, world["placement"]["id"])
        assert_ledger(
            read_account(api, account_id),
            available=AVAILABLE_AFTER_TERMINATION_CENTS,
            encumbered=0,
            disbursed=SETTLED_CENTS,
        )

    def test_termination_releases_the_contract_remainder_and_not_the_gross(
        self, api
    ):
        """
        Only the unspent part of the tuition commitment comes back, so the money
        already disbursed is never handed to the district a second time.

        PRD: "The contract release is `contract_encumbrance_cents` minus `paid_total_ytd_cents` — the part of the tuition commitment never spent."

        Design: Difficulty/compensating_invariant/fiscal_account_identity_survives_partial_payment_then_termination
        """
        world = _paid_cycle_world(api)
        approve_payment(api, world["invoice"]["id"])
        set_clock(api, TERMINATION_INSTANT)

        closed = terminate_placement(api, world["placement"]["id"])

        assert closed["released_encumbrance_cents"] == TOTAL_RELEASE_CENTS
        assert closed["contract_encumbrance_cents"] == SETTLED_CENTS
        assert closed["addendum_encumbrance_cents"] == 0
        assert closed["encumbrance_cents"] == 0

        for addendum_key in ("speech", "ot"):
            addendum = read_addendum(api, world[addendum_key]["id"])
            assert addendum["status"] == "TERMINATED"
            assert addendum["encumbrance_cents"] == 0

        account = read_account(api, world["account"]["id"])
        assert account["available_cents"] == AVAILABLE_AFTER_TERMINATION_CENTS
        assert account["available_cents"] < account["authorized_cents"]
        assert (
            TOTAL_RELEASE_CENTS
            - SPEECH_ENCUMBRANCE_CENTS
            - OT_ENCUMBRANCE_CENTS
            == CONTRACT_RELEASE_CENTS
        )
