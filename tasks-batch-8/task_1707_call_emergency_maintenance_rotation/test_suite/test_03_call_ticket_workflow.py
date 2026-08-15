"""Call intake, triage, dispatch, escalation, and arrival rules."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    create_call_ticket_payload,
    create_dispatched_ticket,
    create_ticket,
    create_triaged_ticket,
    get_ticket,
    make_supervisor,
    make_supervisor_headers,
    make_technician,
    make_technician_headers,
    make_unit,
    publish_shift,
    set_clock,
    start_shift,
    triage_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)


def _tech_on_active_shift(start="2026-08-03T09:00:00Z", end="2026-08-03T13:00:00Z",
                          clock="2026-08-03T09:00:00Z"):
    """Technician + unit + started shift; returns (tech, unit, shift)."""
    set_clock(clock)
    tech = make_technician()
    unit = make_unit()
    shift = publish_shift(tech["id"], start, end)
    start_shift(shift["id"])
    return tech, unit, shift


class TestSlaTargetAssignment:
    def test_sla_targets_assigned_by_category_constants(self, api,
                                                        dispatcher_headers):
        """PRD §3.3: "the response target `sla_target_minutes` is assigned from
        the category — 30 minutes for `GAS_LEAK` or `FLOOD`, 60 minutes for
        `NO_HEAT` or `NO_POWER`, and 120 minutes for every other category."

        Design: Corner/calculations/sla_targets_assigned_by_category_constants
        """
        unit = make_unit(unit_number="C-1", building_code="BC")
        cases = [("GAS_LEAK", 30), ("NO_HEAT", 60), ("LOCKOUT", 120)]
        for category, expected_sla in cases:
            ticket = create_ticket(unit["id"], category)
            triaged = triage_ticket(ticket["id"], True)
            assert triaged["sla_target_minutes"] == expected_sla, (
                f"{category} must carry a {expected_sla}-minute response target"
            )


class TestDeferredTriage:
    def test_deferred_ticket_terminal_and_creates_deferred_work_order(
        self, api, dispatcher_headers
    ):
        """PRD §3.3: "A call judged non-emergency moves `RECEIVED → DEFERRED`
        instead, and the system automatically creates a follow-up work order
        with `priority` `DEFERRED` in `OPEN`, its `unit_id` copied from the
        ticket. `DEFERRED` is terminal; deferred tickets can never be
        dispatched, because dispatch's state check admits only `TRIAGED` or
        `ESCALATED` tickets."

        Design: Corner/state_machines/deferred_ticket_terminal_and_creates_deferred_work_order
        """
        unit = make_unit(unit_number="S-2", building_code="BS")
        tech = make_technician()
        ticket = create_ticket(unit["id"], "APPLIANCE",
                               description="dishwasher hums")
        triaged = validate_success(
            api.triage_call_ticket(
                ticket["id"], {"is_true_emergency": False}, dispatcher_headers
            ),
            200,
        )
        assert triaged["status"] == "DEFERRED"

        rows, meta = validate_paginated(
            api.list_work_orders(dispatcher_headers,
                                 params={"call_ticket_id": ticket["id"]})
        )
        assert meta["total_count"] == 1, "deferred triage auto-creates one order"
        assert rows[0]["priority"] == "DEFERRED"
        assert rows[0]["status"] == "OPEN"

        version = get_ticket(ticket["id"])["version"]
        resp = api.dispatch_call_ticket(
            ticket["id"],
            {"technician_id": tech["id"],
             "expected_call_ticket_version": version},
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CALL_TICKET_INVALID_STATE)


def test_ticket_close_from_received_rejected(api, dispatcher_headers):
    """PRD §3.4: "Closure moves `MITIGATED → CLOSED` and is restricted to
    `Dispatcher` and `MaintenanceSupervisor`."
    PRD §2.9: "5. **State and stale version** — the target resource must be in
    a state that permits the requested transition (the per-entity
    invalid-state errors, HTTP 409)..."

    Design: Corner/state_machines/ticket_close_from_received_rejected
    """
    unit = make_unit(unit_number="S-1", building_code="BS")
    ticket = create_ticket(unit["id"], "APPLIANCE", description="dishwasher leak")
    resp = api.close_call_ticket(ticket["id"], dispatcher_headers)
    validate_error(resp, ApiErrorId.ERR_CALL_TICKET_INVALID_STATE)
    after = get_ticket(ticket["id"])
    assert after["status"] == "RECEIVED"
    assert after.get("closed_at") is None, "failed close must not stamp closed_at"


class TestResponseSlaBoundary:
    def test_response_exactly_at_sla_target_is_not_a_breach(self, api):
        """PRD §3.3: "Arrival stamps `on_scene_at`, computes `response_minutes`
        as the whole minutes from `received_at` to `on_scene_at` (partial
        minutes truncated), and sets `response_breach` to true only when
        `response_minutes` is strictly greater than `sla_target_minutes` — a
        response landing exactly on the target is not a breach."

        Design: Difficulty/boundary_precision_check/response_sla_exact_target_boundary
        """
        tech, unit, _shift = _tech_on_active_shift()
        set_clock("2026-08-03T10:00:00Z")
        ticket = create_dispatched_ticket(unit["id"], tech["id"], "GAS_LEAK",
                                          description="Gas odor")
        set_clock("2026-08-03T10:30:00Z")
        arrived = validate_success(
            api.arrive_call_ticket(
                ticket["id"], make_technician_headers(tech["id"])
            ),
            200,
        )
        assert arrived["sla_target_minutes"] == 30
        assert arrived["response_minutes"] == 30
        assert arrived["response_breach"] is False, (
            "a response landing exactly on the target is not a breach"
        )

    def test_response_one_minute_past_sla_target_breaches(self, api):
        """PRD §3.3: "sets `response_breach` to true only when
        `response_minutes` is strictly greater than `sla_target_minutes` — a
        response landing exactly on the target is not a breach."

        Design: Difficulty/boundary_precision_check/response_sla_exact_target_boundary
        """
        tech, unit, _shift = _tech_on_active_shift()
        set_clock("2026-08-03T12:00:00Z")
        ticket = create_dispatched_ticket(unit["id"], tech["id"], "GAS_LEAK",
                                          description="Gas odor, second call")
        set_clock("2026-08-03T12:31:00Z")
        arrived = validate_success(
            api.arrive_call_ticket(
                ticket["id"], make_technician_headers(tech["id"])
            ),
            200,
        )
        assert arrived["response_minutes"] == 31
        assert arrived["response_breach"] is True, "31 > 30 must breach"


class TestDispatchGates:
    def test_dispatch_requires_active_shift(self, api, dispatcher_headers):
        """PRD §3.3: "the on-shift verification, which requires the technician
        to be `ACTIVE` and to hold a RotationShift in `ACTIVE` whose window
        covers now (else `ERR_TECHNICIAN_NOT_ON_SHIFT`)."

        Design: Corner/validations/dispatch_requires_active_shift
        """
        set_clock("2026-08-03T00:30:00Z")
        tech = make_technician(full_name="Terry Two")
        unit = make_unit(unit_number="M-6", building_code="BM")
        publish_shift(tech["id"], "2026-08-03T00:00:00Z", "2026-08-03T08:00:00Z")
        ticket = create_triaged_ticket(unit["id"], "NO_POWER",
                                       description="outage")
        version = get_ticket(ticket["id"])["version"]
        resp = api.dispatch_call_ticket(
            ticket["id"],
            {"technician_id": tech["id"],
             "expected_call_ticket_version": version},
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_ON_SHIFT)
        assert get_ticket(ticket["id"])["status"] == "TRIAGED"

    def test_deactivated_technician_not_dispatchable(self, api,
                                                     property_admin_headers,
                                                     dispatcher_headers):
        """PRD §3.1: "An inactive technician can no longer be dispatched
        (dispatch rejects them with `ERR_TECHNICIAN_NOT_ON_SHIFT`), and future
        shift publication, shift transfer, and work-order assignment to them
        are blocked..."

        Design: Corner/errors/deactivated_technician_not_dispatchable
        """
        set_clock("2026-08-03T00:00:00Z")
        tech = make_technician()
        unit = make_unit(unit_number="V-1", building_code="BV")
        shift = publish_shift(tech["id"], "2026-08-03T00:00:00Z",
                              "2026-08-03T08:00:00Z")
        start_shift(shift["id"])
        ticket = create_triaged_ticket(unit["id"], "NO_POWER",
                                       description="outage")
        deactivated = validate_success(
            api.deactivate_technician(tech["id"], property_admin_headers), 200
        )
        assert deactivated["status"] == "INACTIVE"
        version = get_ticket(ticket["id"])["version"]
        resp = api.dispatch_call_ticket(
            ticket["id"],
            {"technician_id": tech["id"],
             "expected_call_ticket_version": version},
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_ON_SHIFT)
        assert get_ticket(ticket["id"])["status"] == "TRIAGED"

    def test_arrive_by_unassigned_technician_rejected(self, api):
        """PRD §3.3: "Arrival is the assigned technician's own action, valid
        from either `DISPATCHED` or `ESCALATED` (else
        `ERR_CALL_TICKET_INVALID_STATE`), and only when `X-User-ID` matches the
        ticket's `assigned_technician_id` (else `ERR_NOT_ASSIGNED_TECHNICIAN`)."

        Design: Corner/rbac/arrive_by_unassigned_technician_rejected
        """
        set_clock("2026-08-03T00:00:00Z")
        t1 = make_technician(full_name="Pat Tech")
        t2 = make_technician(full_name="Terry Two")
        unit = make_unit(unit_number="R-6", building_code="BR")
        for tech in (t1, t2):
            shift = publish_shift(tech["id"], "2026-08-03T00:00:00Z",
                                  "2026-08-03T08:00:00Z")
            start_shift(shift["id"])
        ticket = create_dispatched_ticket(unit["id"], t1["id"], "NO_POWER",
                                          description="outage")
        resp = api.arrive_call_ticket(ticket["id"], make_technician_headers(t2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_TECHNICIAN)
        assert get_ticket(ticket["id"])["status"] == "DISPATCHED"


class TestEscalationRedispatchLoop:
    def _setup_escalated_ticket(self):
        """Two technicians on ACTIVE shifts; NO_POWER ticket dispatched to t1."""
        set_clock("2026-08-03T00:00:00Z")
        t1 = make_technician(full_name="Pat Tech")
        t2 = make_technician(full_name="Terry Two")
        sup = make_supervisor(full_name="Sam Sup")
        unit = make_unit(unit_number="U-402", building_code="B4")
        for tech in (t1, t2):
            shift = publish_shift(tech["id"], "2026-08-03T00:00:00Z",
                                  "2026-08-03T12:00:00Z")
            start_shift(shift["id"])
        ticket = create_dispatched_ticket(unit["id"], t1["id"], "NO_POWER",
                                          description="Unit dark, breaker fine")
        return t1, t2, sup, unit, ticket

    def test_manual_escalation_raises_level_then_redispatch_resets(
        self, api, dispatcher_headers
    ):
        """PRD §3.3: "A manual escalation — available to `Dispatcher`,
        `OnCallTechnician`, and `MaintenanceSupervisor` — moves `DISPATCHED →
        ESCALATED` and raises `escalation_level` by one with a floor of one, so
        a first escalation from level zero lands on level one."
        PRD §3.3: "A successful dispatch sets `assigned_technician_id`, stamps
        `dispatched_at`, resets `escalation_level` to 0, and increments the
        ticket's `version`."

        Design: Difficulty/non_linear_state_machine/call_ticket_escalation_redispatch_loop
        """
        t1, t2, sup, _unit, ticket = self._setup_escalated_ticket()
        escalated = validate_success(
            api.escalate_call_ticket(ticket["id"], dispatcher_headers), 200
        )
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalation_level"] == 1, "floor of one on first escalation"

        version = get_ticket(ticket["id"])["version"]
        redispatched = validate_success(
            api.dispatch_call_ticket(
                ticket["id"],
                {"technician_id": t2["id"],
                 "expected_call_ticket_version": version},
                make_supervisor_headers(sup["id"]),
            ),
            200,
        )
        assert redispatched["status"] == "DISPATCHED"
        assert redispatched["escalation_level"] == 0, "re-dispatch resets the level"
        assert redispatched["assigned_technician_id"] == t2["id"], (
            "assignment superseded by the re-dispatch"
        )

    def test_arrive_legal_after_redispatch_from_escalated(self, api,
                                                          dispatcher_headers):
        """PRD §3.3: "Dispatch assigns an on-call technician to a `TRIAGED`
        ticket — or re-assigns one in `ESCALATED`..."
        PRD §3.3: "Arrival is the assigned technician's own action, valid from
        either `DISPATCHED` or `ESCALATED` (else
        `ERR_CALL_TICKET_INVALID_STATE`)..."

        Design: Difficulty/non_linear_state_machine/call_ticket_escalation_redispatch_loop
        """
        t1, t2, sup, _unit, ticket = self._setup_escalated_ticket()
        validate_success(api.escalate_call_ticket(ticket["id"], dispatcher_headers),
                         200)
        version = get_ticket(ticket["id"])["version"]
        validate_success(
            api.dispatch_call_ticket(
                ticket["id"],
                {"technician_id": t2["id"],
                 "expected_call_ticket_version": version},
                make_supervisor_headers(sup["id"]),
            ),
            200,
        )
        arrived = validate_success(
            api.arrive_call_ticket(ticket["id"], make_technician_headers(t2["id"])),
            200,
        )
        assert arrived["status"] == "ON_SCENE"


def test_escalation_checkpoint_advances_levels(api, property_admin_headers,
                                               dispatcher_headers):
    """PRD §3.3: "an ops-run checkpoint — a capability restricted to
    `PropertyAdmin` and `MaintenanceSupervisor` — sweeps all `DISPATCHED` and
    `ESCALATED` tickets against the logical clock: a `DISPATCHED` ticket whose
    elapsed time since `dispatched_at` is strictly more than 15 minutes moves
    to `ESCALATED` at level 1, and an `ESCALATED` ticket still below level 2
    whose elapsed time is strictly more than 30 minutes advances to level 2.
    The checkpoint reports how many tickets were examined as `evaluated_count`
    and the tickets it moved as `escalated`."

    Design: Corner/complexity_layers/escalation_checkpoint_advances_levels
    """
    set_clock("2026-08-03T00:00:00Z")
    tech = make_technician()
    unit = make_unit(unit_number="L-2", building_code="BL")
    shift = publish_shift(tech["id"], "2026-08-03T00:00:00Z",
                          "2026-08-03T12:00:00Z")
    start_shift(shift["id"])
    ticket_a = create_dispatched_ticket(unit["id"], tech["id"], "NO_POWER",
                                        description="A")
    set_clock("2026-08-03T00:05:00Z")
    ticket_b = create_dispatched_ticket(unit["id"], tech["id"], "NO_POWER",
                                        description="B")

    set_clock("2026-08-03T00:16:00Z")
    first = validate_success(api.evaluate_escalations(property_admin_headers), 200)
    assert first["evaluated_count"] == 2, "both in-flight tickets are examined"
    after_a1 = get_ticket(ticket_a["id"])
    after_b1 = get_ticket(ticket_b["id"])
    assert after_a1["status"] == "ESCALATED" and after_a1["escalation_level"] == 1, (
        "16 min > 15 promotes A to level 1"
    )
    assert after_b1["status"] == "DISPATCHED" and after_b1["escalation_level"] == 0, (
        "11 min <= 15 leaves B untouched"
    )

    set_clock("2026-08-03T00:36:00Z")
    validate_success(api.evaluate_escalations(property_admin_headers), 200)
    after_a2 = get_ticket(ticket_a["id"])
    after_b2 = get_ticket(ticket_b["id"])
    assert after_a2["escalation_level"] == 2, "36 min > 30 raises ESCALATED A to 2"
    assert after_b2["status"] == "ESCALATED" and after_b2["escalation_level"] == 1, (
        "31 min > 15 promotes DISPATCHED B to level 1"
    )


def test_logical_clock_default_timestamp(api, dispatcher_headers):
    """PRD §2.4: "Before any operator intervention, the logical clock starts at
    exactly `2026-08-01T00:00:00Z`."
    PRD §3.3: "The ticket is stamped with `received_at` from the logical clock
    and opens in `RECEIVED`."

    Design: Corner/complexity_layers/logical_clock_default_timestamp
    """
    unit = make_unit(unit_number="L-3", building_code="BL")
    ticket = validate_success(
        api.create_call_ticket(
            create_call_ticket_payload(
                unit_id=unit["id"], category="OTHER",
                description="default clock probe"
            ),
            dispatcher_headers,
        ),
        201,
    )
    assert_same_instant(ticket["received_at"], "2026-08-01T00:00:00Z")


def test_occ_dispatch_stale_version_rejected(api, dispatcher_headers):
    """PRD §2.7: "Dispatching (or re-dispatching) a call ticket requires
    `expected_call_ticket_version` in the request body. If the value does not
    match the ticket's current `version` — for instance because another writer
    has advanced the ticket since the dispatcher last read it — the request is
    rejected with `ERR_STALE_CALL_TICKET_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_dispatch_stale_version_rejected
    """
    set_clock("2026-08-03T00:00:00Z")
    tech = make_technician()
    unit = make_unit(unit_number="L-1", building_code="BL")
    shift = publish_shift(tech["id"], "2026-08-03T00:00:00Z",
                          "2026-08-03T08:00:00Z")
    start_shift(shift["id"])
    ticket = create_triaged_ticket(unit["id"], "NO_POWER", description="outage")
    v_stale = get_ticket(ticket["id"])["version"]
    validate_success(
        api.dispatch_call_ticket(
            ticket["id"],
            {"technician_id": tech["id"],
             "expected_call_ticket_version": v_stale},
            dispatcher_headers,
        ),
        200,
    )
    validate_success(api.escalate_call_ticket(ticket["id"], dispatcher_headers), 200)
    v_fresh = get_ticket(ticket["id"])["version"]
    assert v_fresh > v_stale, "dispatch and escalate each mutate the ticket"

    stale = api.dispatch_call_ticket(
        ticket["id"],
        {"technician_id": tech["id"],
         "expected_call_ticket_version": v_stale},
        dispatcher_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_CALL_TICKET_VERSION)

    fresh = validate_success(
        api.dispatch_call_ticket(
            ticket["id"],
            {"technician_id": tech["id"],
             "expected_call_ticket_version": v_fresh},
            dispatcher_headers,
        ),
        200,
    )
    assert fresh["status"] == "DISPATCHED"
    assert fresh["version"] > v_fresh, "successful re-dispatch increments version"
