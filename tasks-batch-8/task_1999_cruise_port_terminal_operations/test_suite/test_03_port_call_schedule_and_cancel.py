"""Port call scheduling: delay/confirm-revised revision loop, the window-loss
cascade, departure gating from the wrong state, cancellation and its
compensation cascade, and the six-hour turnaround minimum."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_manifest_entry,
    assert_instant_equal,
    approve_service_order,
    confirm_revised_port_call,
    create_port_call,
    create_port_call_payload,
    create_provisional_invoice,
    create_service_order,
    create_terminal,
    create_transport_slot,
    create_vessel,
    delay_port_call,
    get_berth_assignment,
    get_invoice,
    get_manifest_entry,
    get_port_call,
    get_service_order,
    get_transport_slot,
    make_vessel_agent_headers,
    setup_base,
    setup_confirmed_call,
    setup_scheduled_call,
    validate_error,
    validate_paginated,
    validate_success,
)

HARBORMASTER = TEST_USERS["harbormaster_headers"]


class TestDelayRevisionCycle:
    def test_delay_confirm_loop_applies_latest_revision(self, api):
        """PRD §3.2: "Confirming the revision moves the call from `DELAYED`
        back to `SCHEDULED`, overwrites `scheduled_eta` and `scheduled_etd` with
        the revised values, and then fires a pinned three-hop cascade."
        PRD §3.2: "Delay and confirm-revised form a revision loop that may
        repeat as often as the schedule demands."

        Design: Difficulty/non_linear_state_machine/port_call_delay_revision_cycle
        """
        ctx = setup_base(vessel_name="MV H")
        port_call = create_port_call(ctx["terminal"]["id"], ctx["vessel"]["id"],
                                     booked_embark_pax=10, booked_debark_pax=10)
        ves = ctx["vessel"]["id"]

        delay_port_call(port_call["id"], ves,
                        revised_eta="2026-08-11T08:00:00Z",
                        revised_etd="2026-08-11T20:00:00Z", reason="weather")
        confirm_revised_port_call(port_call["id"])
        delay_port_call(port_call["id"], ves,
                        revised_eta="2026-08-12T08:00:00Z",
                        revised_etd="2026-08-12T20:00:00Z", reason="congestion")
        confirm_revised_port_call(port_call["id"])

        final = get_port_call(port_call["id"])
        assert final["status"] == "SCHEDULED"
        assert_instant_equal(final["scheduled_eta"], "2026-08-12T08:00:00Z",
                             label="scheduled_eta after the second revision")
        assert_instant_equal(final["scheduled_etd"], "2026-08-12T20:00:00Z",
                             label="scheduled_etd after the second revision")

    def test_delay_confirm_loop_increments_version_once_per_step(self, api):
        """PRD §3.2: "A recorded delay moves the call from `SCHEDULED` to
        `DELAYED`, stores the three values (with the payload's `reason`
        persisted as `delay_reason`), and increments the call's `version` by 1."
        PRD §3.2: "The call's `version` increments by 1. Delay and
        confirm-revised form a revision loop that may repeat as often as the
        schedule demands."

        Design: Difficulty/non_linear_state_machine/port_call_delay_revision_cycle
        """
        ctx = setup_base(vessel_name="MV H2")
        port_call = create_port_call(ctx["terminal"]["id"], ctx["vessel"]["id"])
        ves = ctx["vessel"]["id"]
        assert port_call["version"] == 1

        delay_port_call(port_call["id"], ves)
        mid = confirm_revised_port_call(port_call["id"])
        assert mid["version"] == 3, "create + delay + confirm"

        delay_port_call(port_call["id"], ves,
                        revised_eta="2026-08-12T08:00:00Z",
                        revised_etd="2026-08-12T20:00:00Z", reason="congestion")
        final = confirm_revised_port_call(port_call["id"])
        assert final["version"] == 5, (
            "create (1) + two delays (+2) + two confirms (+2)"
        )


class TestConfirmRevisedWindowLostCascade:
    def _setup_delayed_call_with_approved_order(self):
        """Confirmed call + APPROVED provisioning order + DRAFT provisional
        invoice, then a delay that moves the schedule to the next day (outside
        the confirmed assignment window)."""
        ctx = setup_confirmed_call(vessel_name="MV I", booked_embark_pax=100,
                                   booked_debark_pax=100)
        pc = ctx["port_call"]
        ves = ctx["vessel"]["id"]
        so = create_service_order(pc["id"], ves, kind="PROVISIONING", units=10,
                                  window_start="2026-08-10T10:00:00Z",
                                  window_end="2026-08-10T12:00:00Z")
        approve_service_order(so["id"], role="TerminalOperator", user_id="op-1")
        ctx["service_order"] = get_service_order(so["id"])
        ctx["provisional_invoice"] = create_provisional_invoice(pc["id"])
        delay_port_call(pc["id"], ves, revised_eta="2026-08-11T08:00:00Z",
                        revised_etd="2026-08-11T20:00:00Z", reason="storm front")
        return ctx

    def test_confirm_revised_supersedes_assignment_and_rejects_order(self, api):
        """PRD §3.2: "Hop 1: this call's `CONFIRMED` berth assignment whose
        window no longer contains the new schedule — that is, whose
        `window_start` falls after the new `scheduled_eta` or whose `window_end`
        falls before the new `scheduled_etd` — becomes `SUPERSEDED`, releasing
        its berth window."
        PRD §3.2: "Hop 2, caused by hop 1: this call's service orders in
        `REQUESTED` or `APPROVED` whose requested window is not contained in any
        remaining live (`TENTATIVE`, `CONFIRMED`, or `ACTIVE`) assignment window
        of the call become `REJECTED`, with `reject_reason` set to
        `WINDOW_LOST`."

        Design: Difficulty/transitive_cascade/confirm_revised_window_lost_cascade
        """
        ctx = self._setup_delayed_call_with_approved_order()
        confirm_revised_port_call(ctx["port_call"]["id"])

        assignment = get_berth_assignment(ctx["assignment"]["id"])
        assert assignment["status"] == "SUPERSEDED"

        order = get_service_order(ctx["service_order"]["id"])
        assert order["status"] == "REJECTED"
        assert order["reject_reason"] == "WINDOW_LOST"

    def test_confirm_revised_recomputes_draft_provisional_invoice(self, api):
        """PRD §3.2: "Hop 3, caused by hop 2: the call's `PROVISIONAL` invoice,
        if one exists in `DRAFT`, recomputes `service_fee_cents` — rejected
        orders now contribute zero — and with it `gross_cents` and
        `total_cents`."

        Design: Difficulty/transitive_cascade/confirm_revised_window_lost_cascade
        """
        ctx = self._setup_delayed_call_with_approved_order()
        invoice = ctx["provisional_invoice"]
        assert invoice["service_fee_cents"] == 48000
        assert invoice["gross_cents"] == 1743000, (
            "dockage 1425000 + head tax 270000 + service 48000 before the "
            "cascade"
        )

        confirm_revised_port_call(ctx["port_call"]["id"])

        recomputed = get_invoice(invoice["id"])
        assert recomputed["service_fee_cents"] == 0
        assert recomputed["gross_cents"] == 1695000
        assert recomputed["total_cents"] == 1695000
        assert recomputed["dockage_fee_cents"] == 1425000
        assert recomputed["head_tax_cents"] == 270000


class TestDepartAndCancelStateGates:
    def test_depart_from_scheduled_rejected(self, api):
        """PRD §3.3: "Departure, again the `Harbormaster`'s call, is the most
        heavily gated transition in the system. From `TURNAROUND`, four
        conditions must hold, evaluated in pipeline order: ..."
        PRD §2.9: "8. State preconditions: the target entity is in a state from
        which the requested transition exists, including parent-state gates on
        child creation — otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/port_call_depart_from_scheduled_rejected
        """
        ctx = setup_scheduled_call()
        resp = api.depart_port_call(ctx["port_call"]["id"],
                                    {"actual_etd": "2026-08-10T20:00:00Z"},
                                    HARBORMASTER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        assert get_port_call(ctx["port_call"]["id"])["status"] == "SCHEDULED"
        _, meta = validate_paginated(
            api.list_invoices(TEST_USERS["billing_headers"],
                              params={"port_call_id": ctx["port_call"]["id"]}))
        assert meta["total_count"] == 0, "no invoice may appear from a failed depart"

    def test_cancel_from_cancelled_rejected(self, api):
        """PRD §3.2: "Cancellation is the other way out of the schedule,
        available from either `SCHEDULED` or `DELAYED` to the vessel's own
        `VesselAgent` or to the `Harbormaster`, with an optional `reason`."
        PRD §3.2: "The call's terminal states are `CLOSED` and `CANCELLED`."

        Design: Corner/state_machines/port_call_cancel_from_cancelled_rejected
        """
        ctx = setup_scheduled_call()
        ves = ctx["vessel"]["id"]
        first = api.cancel_port_call(ctx["port_call"]["id"],
                                     make_vessel_agent_headers(ves))
        validate_success(first)
        assert get_port_call(ctx["port_call"]["id"])["status"] == "CANCELLED"

        second = api.cancel_port_call(ctx["port_call"]["id"], HARBORMASTER)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)
        assert get_port_call(ctx["port_call"]["id"])["status"] == "CANCELLED"

    def test_cancel_compensation_cascade_reaches_all_children(self, api):
        """PRD §3.2: "Cancelling a call fires the full compensation cascade:
        any live berth assignment of the call (`TENTATIVE` or `CONFIRMED`)
        becomes `SUPERSEDED`; service orders in `REQUESTED` or `APPROVED` become
        `CANCELLED`; the call's `QUEUED` transport slots become `EXPIRED`; a
        `DRAFT` or `ISSUED` `PROVISIONAL` invoice becomes `CANCELLED` (a `FINAL`
        invoice can never exist yet, because final billing only begins at close,
        long after cancellation is possible); every manifest entry not yet in a
        terminal state becomes `CANCELLED`; and every non-terminal baggage item
        of the call becomes `CANCELLED`."

        Design: Corner/state_machines/call_cancel_compensation_cascade
        """
        ctx = setup_confirmed_call()
        pc = ctx["port_call"]
        ves = ctx["vessel"]["id"]
        so = create_service_order(pc["id"], ves, kind="PROVISIONING", units=5)
        approve_service_order(so["id"], role="TerminalOperator", user_id="op-1")
        slot = create_transport_slot(ctx["terminal"]["id"], pc["id"],
                                     vehicle_class="TAXI", party_size=2)
        entry = add_manifest_entry(pc["id"], ves, "P1", direction="EMBARK")

        cancelled = validate_success(
            api.cancel_port_call(pc["id"], make_vessel_agent_headers(ves),
                                 payload={"reason": "itinerary change"}))
        assert cancelled["status"] == "CANCELLED"

        assert get_berth_assignment(ctx["assignment"]["id"])["status"] == "SUPERSEDED"
        assert get_service_order(so["id"])["status"] == "CANCELLED"
        assert get_transport_slot(slot["id"])["status"] == "EXPIRED"
        assert get_manifest_entry(entry["id"])["status"] == "CANCELLED"


class TestTurnaroundMinimum:
    def test_turnaround_exactly_six_hours_allowed_shorter_rejected(self, api):
        """PRD §3.2: "One feasibility rule guards the booking: the span from
        `scheduled_eta` to `scheduled_etd` must be at least six hours, and a
        span of exactly six hours is allowed; anything shorter is rejected with
        `ERR_TURNAROUND_TOO_SHORT` (HTTP 422)."

        Design: Corner/validations/turnaround_minimum_6h_boundary
        """
        terminal = create_terminal()
        vessel = create_vessel(terminal["id"])
        agent = make_vessel_agent_headers(vessel["id"])

        ok = api.create_port_call(
            create_port_call_payload(
                terminal["id"], vessel["id"], voyage_ref="V-OK",
                scheduled_eta="2026-08-10T08:00:00Z",
                scheduled_etd="2026-08-10T14:00:00Z"),
            agent)
        validate_success(ok, 201)

        short = api.create_port_call(
            create_port_call_payload(
                terminal["id"], vessel["id"], voyage_ref="V-SHORT",
                scheduled_eta="2026-08-10T08:00:00Z",
                scheduled_etd="2026-08-10T13:59:00Z"),
            agent)
        validate_error(short, ApiErrorId.ERR_TURNAROUND_TOO_SHORT)
