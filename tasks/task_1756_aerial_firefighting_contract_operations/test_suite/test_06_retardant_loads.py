"""Retardant reloads, the turn-time SLA, and immediate read-after-write."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_load,
    drop_load,
    request_load,
    setup_on_incident,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["carrier_ops_headers"]


class TestRetardantLoadState:
    def test_retardant_drop_from_requested_rejected(self, api):
        """PRD §3.7: "Completing the load moves it to `LOADED` with a supplied
        `loaded_at` that must not precede `requested_at`, and dropping it over
        the fire moves it `LOADED` → `DROPPED` with a supplied `dropped_at`
        that must not precede `loaded_at`; violating either ordering, or
        acting out of state, is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/retardant_drop_from_requested_rejected
        """
        ws = setup_on_incident()
        load = request_load(ws["assignment"]["id"], gallons=700,
                            requested_at="2026-08-02T10:00:00Z")
        assert load["status"] == "REQUESTED"

        resp = api.drop_retardant_load(
            load["id"], {"dropped_at": "2026-08-02T11:00:00Z"}, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_retardant_tank_capacity_exceeded(self, api):
        """PRD §3.7: "While an assignment is `ON_INCIDENT`, `CarrierOps` may
        request a retardant load of `gallons` — strictly positive and never
        more than the aircraft's `tank_capacity_gallons`, or the request is
        refused with `ERR_TANK_CAPACITY_EXCEEDED`."

        Design: Corner/validations/retardant_tank_capacity_exceeded
        """
        ws = setup_on_incident()  # tank_capacity_gallons 800

        resp = api.create_retardant_load(
            ws["assignment"]["id"],
            {"gallons": 900, "requested_at": "2026-08-02T10:00:00Z"}, OPS)
        validate_error(resp, ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED,
                       expected_status=422)

        ok = request_load(ws["assignment"]["id"], gallons=800,
                          requested_at="2026-08-02T10:05:00Z")
        assert ok["status"] == "REQUESTED", \
            "gallons equal to tank capacity is allowed (the check is strictly over)"


class TestReloadSlaBoundary:
    def _setup_three_loads(self):
        """ON_INCIDENT assignment with L1 dropped and L2/L3 loaded at
        +30-minute turns each."""
        ws = setup_on_incident()
        a_id = ws["assignment"]["id"]
        l1 = request_load(a_id, 700, "2026-08-02T10:00:00Z")
        l1 = complete_load(l1["id"], "2026-08-02T10:20:00Z")
        drop_load(l1["id"], "2026-08-02T11:00:00Z")
        l2 = request_load(a_id, 700, "2026-08-02T11:10:00Z")
        l2 = complete_load(l2["id"], "2026-08-02T11:30:00Z")
        drop_load(l2["id"], "2026-08-02T12:00:00Z")
        l3 = request_load(a_id, 700, "2026-08-02T12:10:00Z")
        l3 = complete_load(l3["id"], "2026-08-02T12:30:00Z")
        return ws, l1, l2, l3

    def test_reload_average_exactly_thirty_not_breach(self, api):
        """PRD §3.7: "The first load of an assignment has no predecessor, so
        its `reload_turn_minutes` stays null."
        PRD §3.7: "re-derives `reload_sla_breach`, which is true only when
        that average is strictly greater than 30.0 minutes; an average of
        exactly 30.0 is not a breach."

        Design: Difficulty/boundary_precision_check/reload_sla_average_exactly_thirty
        """
        ws, l1, l2, _l3 = self._setup_three_loads()
        assert l1["reload_turn_minutes"] is None, \
            "first load of the assignment has no previous drop"
        assert l2["reload_turn_minutes"] == 30, "11:30 minus 11:00"

        assignment = validate_success(
            api.get_assignment(ws["assignment"]["id"], OPS))
        assert assignment["reload_turn_avg_minutes"] == 30.0, \
            "mean of [30, 30] rounds to 30.0"
        assert assignment["reload_sla_breach"] is False, \
            "exactly 30.0 is not a breach"

    def test_reload_average_above_thirty_breaches(self, api):
        """PRD §3.7: "`reload_turn_minutes` is the whole-minute difference
        between the load's `loaded_at` and the most recent earlier drop among
        the same assignment's loads"; "the mean of its non-null turn times,
        rounded half up to one decimal place"; breach "is true only when that
        average is strictly greater than 30.0 minutes".

        Design: Difficulty/boundary_precision_check/reload_sla_average_exactly_thirty
        """
        ws, _l1, _l2, l3 = self._setup_three_loads()
        drop_load(l3["id"], "2026-08-02T13:00:00Z")
        l4 = request_load(ws["assignment"]["id"], 700, "2026-08-02T13:10:00Z")
        l4 = complete_load(l4["id"], "2026-08-02T13:31:00Z")
        assert l4["reload_turn_minutes"] == 31, "13:31 minus 13:00"

        assignment = validate_success(
            api.get_assignment(ws["assignment"]["id"], OPS))
        assert assignment["reload_turn_avg_minutes"] == 30.3, \
            "round_half_up(91 / 3, 1)"
        assert assignment["reload_sla_breach"] is True, "30.3 > 30.0 breaches"


class TestImmediateConsistency:
    def test_immediate_consistency_write_then_read(self, api):
        """PRD §2.10: "Both are maintained invariantly — the exact membership
        rules live in §3.6 and §3.8 — and every adjustment to either is a
        mutation of the contract". Derived state: "a dispatch order's fill
        band is never set by clients but is computed from the live states of
        its child assignments, bubbling up whenever an assignment is created,
        released, or demobilized."
        PRD §3.7: "Every load completion recomputes the assignment's
        `reload_turn_avg_minutes` — the mean of its non-null turn times,
        rounded half up to one decimal place, null while no turns exist — and
        re-derives `reload_sla_breach`".

        Design: Corner/consistency_model/immediate_consistency_write_then_read
        """
        from test_helpers import (create_assignment, get_order,
                                  setup_accepted_order, setup_carded_pair,
                                  launch_assignment, arrive_assignment)
        ws = setup_carded_pair()
        order = setup_accepted_order(ws, quantity=2)
        assignment = create_assignment(
            order["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
            "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z")

        # The very next read reflects the assignment creation.
        order_now = get_order(order["id"])
        assert order_now["filled_count"] == 1
        assert order_now["status"] == "PARTIALLY_FILLED"

        launch_assignment(assignment["id"], ws["pilot"]["id"])
        arrive_assignment(assignment["id"], ws["pilot"]["id"])
        l1 = request_load(assignment["id"], 700, "2026-08-02T10:00:00Z")
        complete_load(l1["id"], "2026-08-02T10:20:00Z")
        drop_load(l1["id"], "2026-08-02T11:00:00Z")
        l2 = request_load(assignment["id"], 700, "2026-08-02T11:10:00Z")
        complete_load(l2["id"], "2026-08-02T11:45:00Z")

        # The very next read reflects the load completion: turn 45 minutes.
        assignment_now = validate_success(
            api.get_assignment(assignment["id"], OPS))
        assert assignment_now["reload_turn_avg_minutes"] == 45.0
        assert assignment_now["reload_sla_breach"] is True
