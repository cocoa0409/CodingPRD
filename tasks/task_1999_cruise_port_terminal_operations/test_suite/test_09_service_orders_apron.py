"""Apron services: approval gates (posture, window containment, segregation of
duties, conditional role), the aggregate apron capacity rule, contamination
sequencing, and the provisional service-fee input set."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_service_order,
    arrive_port_call,
    complete_service_order,
    create_berth,
    create_confirmed_assignment,
    create_port_call,
    create_provisional_invoice,
    create_service_order,
    create_vessel,
    get_service_order,
    get_terminal,
    make_harbormaster_headers,
    make_operator_headers,
    setup_base,
    setup_confirmed_call,
    setup_turnaround_call,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["operator_headers"]
HARBORMASTER = TEST_USERS["harbormaster_headers"]


class TestStartRequiresActiveAssignment:
    def _setup_approved_order_before_arrival(self):
        """Call SCHEDULED; assignment CONFIRMED (not ACTIVE); order APPROVED."""
        ctx = setup_confirmed_call(vessel_name="MV P")
        so = create_service_order(ctx["port_call"]["id"], ctx["vessel"]["id"],
                                  kind="PROVISIONING", units=5)
        approve_service_order(so["id"], role="TerminalOperator", user_id="op-1")
        ctx["service_order"] = so
        return ctx

    def test_start_rejected_while_assignment_only_confirmed(self, api):
        """PRD §3.7: "**Starting** an `APPROVED` order moves it to
        `IN_PROGRESS` and is guarded by three checks: an `ACTIVE` berth
        assignment must exist for the call (`ERR_INVALID_STATE`); ..."

        Design: Difficulty/cross_entity_state_dependency/service_start_gated_by_active_assignment
        """
        ctx = self._setup_approved_order_before_arrival()
        resp = api.start_service_order(ctx["service_order"]["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_start_succeeds_after_arrival_flips_assignment_active(self, api):
        """PRD §3.7: "**Starting** an `APPROVED` order moves it to
        `IN_PROGRESS` and is guarded by three checks: an `ACTIVE` berth
        assignment must exist for the call (`ERR_INVALID_STATE`); ..."
        PRD §3.3: "A recorded arrival stamps `actual_eta`, flips that
        assignment from `CONFIRMED` to `ACTIVE`, recomputes the terminal's
        occupancy counters and posture, moves the call `SCHEDULED` → `ARRIVED`,
        and increments the call's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/service_start_gated_by_active_assignment
        """
        ctx = self._setup_approved_order_before_arrival()
        arrive_port_call(ctx["port_call"]["id"])
        started = validate_success(
            api.start_service_order(ctx["service_order"]["id"], OPERATOR))
        assert started["status"] == "IN_PROGRESS"


class TestApronAggregateCapacity:
    def _setup_two_calls_arrived(self):
        """Terminal max_apron_slots=2, berths B1+B2; two calls ARRIVED; three
        APPROVED orders (SO1 provisioning on call 1, SO2 provisioning on call
        2, SO3 waste offload on call 1) sharing identical windows."""
        ctx = setup_base(max_apron_slots=2, vessel_name="MV S1")
        term_id = ctx["terminal"]["id"]
        berth2 = create_berth(term_id, berth_code="B2", length_ft=1200,
                              max_draft_ft=40.0)
        vessel2 = create_vessel(term_id, name="MV S2", loa_ft=900,
                                draft_ft=28.0, pax_capacity=3000,
                                crew_count=800)

        pc1 = create_port_call(term_id, ctx["vessel"]["id"], voyage_ref="V1")
        pc2 = create_port_call(term_id, vessel2["id"], voyage_ref="V2")

        create_confirmed_assignment(pc1["id"], ctx["berth"]["id"])
        create_confirmed_assignment(pc2["id"], berth2["id"])

        so1 = create_service_order(pc1["id"], ctx["vessel"]["id"],
                                   kind="PROVISIONING", units=5)
        so2 = create_service_order(pc2["id"], vessel2["id"],
                                   kind="PROVISIONING", units=5)
        so3 = create_service_order(pc1["id"], ctx["vessel"]["id"],
                                   kind="WASTE_OFFLOAD", units=3,
                                   window_start="2026-08-10T13:00:00Z",
                                   window_end="2026-08-10T15:00:00Z")
        for so in (so1, so2, so3):
            approve_service_order(so["id"], role="TerminalOperator",
                                  user_id="op-1")

        arrive_port_call(pc1["id"])
        arrive_port_call(pc2["id"])
        ctx.update(pc1=pc1, pc2=pc2, so1=so1, so2=so2, so3=so3)
        return ctx

    def test_apron_admits_up_to_max_slots(self, api):
        """PRD §3.7: "the apron must have room, where the rule is aggregate
        concurrency with no pairwise interval arithmetic — every `IN_PROGRESS`
        order anywhere on the terminal, across all port calls, consumes one
        slot regardless of its window times, and a start is rejected with
        `ERR_APRON_CAPACITY` whenever the terminal's current `IN_PROGRESS`
        count already equals or exceeds `max_apron_slots` — a count exactly
        one below the limit passes"

        Design: Difficulty/resource_temporal_overlap/apron_aggregate_concurrency_cap
        """
        ctx = self._setup_two_calls_arrived()
        s1 = validate_success(api.start_service_order(ctx["so1"]["id"], OPERATOR))
        s2 = validate_success(api.start_service_order(ctx["so2"]["id"], OPERATOR))
        assert s1["status"] == "IN_PROGRESS"
        assert s2["status"] == "IN_PROGRESS", (
            "identical windows on different calls are admitted: capacity is "
            "aggregate, not interval-pairwise"
        )

    def test_apron_rejects_at_limit_and_recovers_after_completion(self, api):
        """PRD §3.7: "the apron must have room, where the rule is aggregate
        concurrency with no pairwise interval arithmetic — every `IN_PROGRESS`
        order anywhere on the terminal, across all port calls, consumes one
        slot regardless of its window times, and a start is rejected with
        `ERR_APRON_CAPACITY` whenever the terminal's current `IN_PROGRESS`
        count already equals or exceeds `max_apron_slots` — a count exactly
        one below the limit passes"
        PRD §3.7: "**Completing** an `IN_PROGRESS` order records the payload's
        `actual_units` — zero or more — moves the order to `COMPLETED`, and
        recomputes the `DRAFT` `PROVISIONAL` invoice."

        Design: Difficulty/resource_temporal_overlap/apron_aggregate_concurrency_cap
        """
        ctx = self._setup_two_calls_arrived()
        api.start_service_order(ctx["so1"]["id"], OPERATOR)
        api.start_service_order(ctx["so2"]["id"], OPERATOR)

        blocked = api.start_service_order(ctx["so3"]["id"], OPERATOR)
        validate_error(blocked, ApiErrorId.ERR_APRON_CAPACITY)

        complete_service_order(ctx["so1"]["id"], actual_units=5)
        freed = validate_success(api.start_service_order(ctx["so3"]["id"], OPERATOR))
        assert freed["status"] == "IN_PROGRESS"


class TestApprovalGates:
    def test_contamination_waste_before_provisioning(self, api):
        """PRD §3.7: "and the contamination rule forbids starting a
        `PROVISIONING` order while a `WASTE_OFFLOAD` of the same call is
        `IN_PROGRESS` — rejected with `ERR_WASTE_BEFORE_PROVISIONING` — though
        the reverse sequencing, starting waste offload while provisioning runs,
        is not restricted."

        Design: Corner/validations/waste_before_provisioning_contamination
        """
        # Single berth: once the call arrives, the terminal is CONSTRAINED, so
        # the Harbormaster approves.
        ctx = setup_base()
        pc = create_port_call(ctx["terminal"]["id"], ctx["vessel"]["id"],
                              voyage_ref="V1")
        ves = ctx["vessel"]["id"]
        create_confirmed_assignment(pc["id"], ctx["berth"]["id"])
        so_waste = create_service_order(
            pc["id"], ves, kind="WASTE_OFFLOAD", units=3,
            window_start="2026-08-10T09:00:00Z",
            window_end="2026-08-10T11:00:00Z")
        so_prov = create_service_order(
            pc["id"], ves, kind="PROVISIONING", units=5,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T14:00:00Z")
        arrive_port_call(pc["id"])
        approve_service_order(so_waste["id"], role="Harbormaster", user_id="hm-1")
        approve_service_order(so_prov["id"], role="Harbormaster", user_id="hm-1")
        validate_success(api.start_service_order(so_waste["id"], OPERATOR))

        blocked = api.start_service_order(so_prov["id"], OPERATOR)
        validate_error(blocked, ApiErrorId.ERR_WASTE_BEFORE_PROVISIONING)

        complete_service_order(so_waste["id"], actual_units=3)
        started = validate_success(api.start_service_order(so_prov["id"], OPERATOR))
        assert started["status"] == "IN_PROGRESS"

    def test_service_window_outside_assignment_rejected_at_approve(self, api):
        """PRD §3.7: "Second, window containment: the order's requested window
        must be contained in a live (`TENTATIVE`, `CONFIRMED`, or `ACTIVE`)
        berth-assignment window of the call, otherwise
        `ERR_SERVICE_WINDOW_OUTSIDE_BERTH` (HTTP 422)."

        Design: Corner/validations/service_window_outside_assignment_rejected
        """
        ctx = setup_confirmed_call()
        so = create_service_order(ctx["port_call"]["id"], ctx["vessel"]["id"],
                                  kind="PROVISIONING", units=5,
                                  window_start="2026-08-10T23:00:00Z",
                                  window_end="2026-08-11T01:00:00Z")
        resp = api.approve_service_order(so["id"], make_operator_headers("op-1"))
        validate_error(resp, ApiErrorId.ERR_SERVICE_WINDOW_OUTSIDE_BERTH)
        assert get_service_order(so["id"])["status"] == "REQUESTED"

    def test_segregation_of_duties_same_user_rejected(self, api):
        """PRD §3.7: "Third, segregation of duties: the approver's `X-User-ID`
        must differ from the order's `requested_by_user_id` — a requester may
        never approve its own order, and the attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
        PRD §3.7: "An approval records the approver's `X-User-ID` as
        `approved_by_user_id` (null until this moment), sets
        `surcharge_applied` to true exactly when the terminal posture at
        approval is `CONSTRAINED` — the flag that carries the ten-percent
        surcharge into §3.8, and which defaults to false — and recomputes the
        call's `DRAFT` `PROVISIONAL` invoice, if one exists, across
        `service_fee_cents`, `gross_cents`, and `total_cents`."

        Design: Corner/validations/segregation_of_duties_same_user_rejected
        """
        ctx = setup_confirmed_call()
        pc = ctx["port_call"]
        ves = ctx["vessel"]["id"]
        so = create_service_order(pc["id"], ves, kind="PROVISIONING", units=5)
        assert so["requested_by_user_id"] == ves

        # The requester's own id as approver is rejected, whatever the role.
        err = api.approve_service_order(so["id"], make_operator_headers(ves))
        validate_error(err, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(
            api.approve_service_order(so["id"], make_operator_headers("op-9")))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "op-9"
        assert approved["surcharge_applied"] is False, "posture is OPERATIONAL"

    def test_constrained_approver_role_and_surcharge(self, api):
        """PRD §3.7: "Fourth, the conditional role: under `CONSTRAINED` posture
        only a `Harbormaster` may approve, and a `TerminalOperator`'s attempt
        is rejected with `ERR_CONSTRAINED_REQUIRES_HARBORMASTER` (HTTP 403);
        under `OPERATIONAL` either role may approve."
        PRD §2.5: "While the posture is `CONSTRAINED`, service-order approval
        is reserved to the `Harbormaster` alone, and every order approved under
        `CONSTRAINED` carries a surcharge flag that raises its billed rate by
        ten percent (§3.7, §3.8)."
        PRD §3.8: "Each contributing order produces a line amount — its kind's
        rate multiplied by its units — and when the order's `surcharge_applied`
        flag is set, that line amount is increased by ten percent, rounded
        half-up to whole cents, before any summation; `service_fee_cents` is
        the sum of the line amounts, surcharge rounding applied per order line
        and only then summed."

        Design: Corner/validations/constrained_approver_role_and_surcharge
        """
        # Single-berth terminal: once the call arrives, free_berth_count hits
        # zero and the posture is CONSTRAINED.
        ctx = setup_base()
        pc = create_port_call(ctx["terminal"]["id"], ctx["vessel"]["id"],
                              voyage_ref="V1", booked_embark_pax=100,
                              booked_debark_pax=100)
        ves = ctx["vessel"]["id"]
        create_confirmed_assignment(pc["id"], ctx["berth"]["id"])
        so = create_service_order(pc["id"], ves, kind="PROVISIONING", units=7)
        arrive_port_call(pc["id"])
        assert get_terminal(ctx["terminal"]["id"])["posture"] == "CONSTRAINED"

        err = api.approve_service_order(so["id"], make_operator_headers("op-1"))
        validate_error(err, ApiErrorId.ERR_CONSTRAINED_REQUIRES_HARBORMASTER)

        approved = validate_success(
            api.approve_service_order(so["id"], make_harbormaster_headers("hm-1")))
        assert approved["status"] == "APPROVED"
        assert approved["surcharge_applied"] is True

        invoice = create_provisional_invoice(pc["id"])
        assert invoice["service_fee_cents"] == 36960, (
            "round_half_up(7 x 4800 x 1.10) with the surcharge flag set"
        )


class TestProvisionalServiceFeeInputSet:
    def test_requested_orders_contribute_zero(self, api):
        """PRD §3.8: "The PROVISIONAL variant counts orders in `APPROVED`,
        `IN_PROGRESS`, or `COMPLETED` at their planned `units`; the FINAL
        variant counts only `COMPLETED` orders at their `actual_units`; orders
        in `REQUESTED`, `REJECTED`, or `CANCELLED` contribute zero."

        Design: Corner/calculations/provisional_service_fee_excludes_requested_orders
        """
        ctx = setup_confirmed_call(booked_embark_pax=0, booked_debark_pax=0)
        pc = ctx["port_call"]
        ves = ctx["vessel"]["id"]
        so1 = create_service_order(pc["id"], ves, kind="PROVISIONING", units=10)
        create_service_order(pc["id"], ves, kind="WASTE_OFFLOAD", units=4,
                             window_start="2026-08-10T13:00:00Z",
                             window_end="2026-08-10T15:00:00Z")
        approve_service_order(so1["id"], role="TerminalOperator", user_id="op-1")

        invoice = create_provisional_invoice(pc["id"])
        assert invoice["service_fee_cents"] == 48000, (
            "only the APPROVED order counts; the REQUESTED one contributes 0"
        )
        assert invoice["gross_cents"] == 1473000, (
            "dockage 1425000 + head tax 0 + service 48000"
        )


class TestDepartOpenOrdersGate:
    def test_depart_blocked_by_open_service_orders(self, api):
        """PRD §3.3: "From `TURNAROUND`, four conditions must hold, evaluated
        in pipeline order: the terminal's posture must not be `EMERGENCY`
        (`ERR_POSTURE_EMERGENCY`); the call's customs case must be `CLEARED`
        (`ERR_CUSTOMS_NOT_CLEARED`); no baggage item of the call may remain in
        `MISTAGGED` or `RECOVERED` (`ERR_OPEN_MISTAGS`); and every service order
        of the call must be in `COMPLETED`, `REJECTED`, or `CANCELLED`
        (`ERR_OPEN_SERVICE_ORDERS`)."

        Design: Corner/errors/depart_blocked_by_open_service_orders
        """
        ctx = setup_turnaround_call(customs="cleared")
        # Single berth occupied after arrival -> CONSTRAINED, so the
        # Harbormaster approves. The order is requested while the call is
        # TURNAROUND, which the workflow permits.
        so = create_service_order(ctx["port_call"]["id"], ctx["vessel"]["id"],
                                  kind="WASTE_OFFLOAD", units=3,
                                  window_start="2026-08-10T09:00:00Z",
                                  window_end="2026-08-10T11:00:00Z")
        approve_service_order(so["id"], role="Harbormaster", user_id="hm-1")
        validate_success(api.start_service_order(so["id"], OPERATOR))

        blocked = api.depart_port_call(ctx["port_call"]["id"],
                                       {"actual_etd": "2026-08-10T20:00:00Z"},
                                       HARBORMASTER)
        validate_error(blocked, ApiErrorId.ERR_OPEN_SERVICE_ORDERS)

        complete_service_order(so["id"], actual_units=3)
        departed = validate_success(
            api.depart_port_call(ctx["port_call"]["id"],
                                 {"actual_etd": "2026-08-10T20:00:00Z"},
                                 HARBORMASTER))
        assert departed["status"] == "DEPARTED"
