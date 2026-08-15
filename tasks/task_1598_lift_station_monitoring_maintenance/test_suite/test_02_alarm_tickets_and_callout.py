"""Alarm-ticket lifecycle, the fairness-weighted callout rotation, dispatch
OCC, and the operator active-ticket-count invariant."""
from test_helpers import (
    ApiErrorId,
    ack_ticket,
    add_operator,
    create_sso,
    create_station,
    dispatch_ticket,
    get_operator,
    get_station,
    get_ticket,
    make_operator_headers,
    raise_ticket,
    reset_clock,
    setup_dispatched_ticket,
    setup_on_scene_ticket,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestAlarmTicketLifecycle:
    def test_alarm_ticket_full_happy_path(self, api, operator_headers):
        """PRD §3.3: "The response workflow runs `OPEN → ACKED → DISPATCHED →
        ON_SCENE → CLEARED`, with cancellation shortcuts."
        PRD §3.3: "Acknowledgement by an `OnCallOperator` moves an `OPEN` ticket
        to `ACKED` and stamps `acked_at`"
        PRD §3.3: "clearing moves `ON_SCENE → CLEARED`, stamps `cleared_at`,
        computes `response_minutes` as the whole minutes between `raised_at` and
        `dispatched_at`, and decrements the operator's `active_ticket_count`."
        PRD §3.3: "Dispatch stamps `dispatched_at`, records the winner in
        `assigned_operator_id`, moves the ticket to `DISPATCHED`"

        Design: Corner/state_machines/alarm_ticket_full_happy_path
        """
        reset_clock()
        station, operator, ticket = setup_on_scene_ticket(alarm_class="MINOR")
        res = api.clear_alarm_ticket(ticket["id"], make_operator_headers(operator["id"]))
        cleared = validate_success(res, 200)
        assert cleared["status"] == "CLEARED"
        assert cleared["acked_at"] is not None
        assert cleared["dispatched_at"] is not None
        assert cleared["cleared_at"] is not None
        assert cleared["response_minutes"] == 0, (
            "raised_at and dispatched_at share the pinned clock instant"
        )

    def test_alarm_ticket_cleared_terminal_lockdown(self, api, on_call_operator_headers):
        """PRD §3.3: "`CLEARED` and `CANCELLED` are terminal."
        PRD §2.8: "then the target entity's lifecycle state
        (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/alarm_ticket_cleared_terminal_lockdown
        """
        reset_clock()
        _, operator, ticket = setup_on_scene_ticket(alarm_class="MINOR")
        api.clear_alarm_ticket(ticket["id"], make_operator_headers(operator["id"]))
        res = api.cancel_alarm_ticket(ticket["id"], on_call_operator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_alarm_ticket_dispatch_from_open_returns_invalid_state(
        self, api, on_call_operator_headers
    ):
        """PRD §3.3: "The response workflow runs `OPEN → ACKED → DISPATCHED →
        ON_SCENE → CLEARED`, with cancellation shortcuts."
        PRD §2.8: "then the target entity's lifecycle state
        (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/alarm_ticket_dispatch_from_open_returns_invalid_state
        """
        reset_clock()
        station = create_station()
        ticket = raise_ticket(station["id"])
        res = api.dispatch_alarm_ticket(ticket["id"], ticket["version"], on_call_operator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_alarm_ticket_initial_state_open(self, api, scada_webhook_headers):
        """PRD §3.3: "A new ticket sits in `OPEN`."

        Design: Corner/state_machines/alarm_ticket_initial_state_open
        """
        reset_clock()
        station = create_station()
        ticket = raise_ticket(station["id"], alarm_class="INFO", alarm_code="TEST")
        assert ticket["status"] == "OPEN"

    def test_error_stale_version_on_double_dispatch(self, api, on_call_operator_headers):
        """PRD §2.6: "Dispatching an alarm ticket requires the request to carry
        `expected_ticket_version`, the ticket `version` last observed by the
        on-call operator. A mismatch with the ticket's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412), guarding against
        double-dispatch when the ticket was already dispatched by another
        on-call operator."

        The second attempt is both stale-versioned and no longer `ACKED`; PRD
        §2.8 does not order the OCC guard against the lifecycle-state check, so
        either error identifier satisfies the contract.

        Design: Corner/errors/error_stale_version_on_double_dispatch
        """
        reset_clock()
        station, operator, ticket = setup_dispatched_ticket(alarm_class="MINOR")
        stale_version = ticket["version"] - 1
        res = api.dispatch_alarm_ticket(ticket["id"], stale_version, on_call_operator_headers)
        validate_error_is_one_of(
            res, [ApiErrorId.ERR_STALE_VERSION.value, ApiErrorId.ERR_INVALID_STATE.value],
        )


class TestCalloutSelection:
    def test_callout_score_tie_broken_by_earlier_created_at(self, api):
        """PRD §3.3: "Each eligible operator receives a `callout_score`: 100
        points if the operator's `home_zone` equals the station's
        `service_zone` (0 otherwise), minus 50 points per currently active
        ticket, minus 10 points per consecutive callout in the trailing 24
        hours. The winner is the highest score, with ties broken by the
        operator's earlier `created_at`."
        PRD §3.3: "Dispatch stamps `dispatched_at`, records the winner in
        `assigned_operator_id`, moves the ticket to `DISPATCHED`, and increments
        the winner's `active_ticket_count` and `consecutive_callouts_24h`."

        Design: Difficulty/combinatorial_formula/callout_score_tiebreak_determinism
        """
        reset_clock()
        station = create_station(service_zone="Z1")
        op_a = add_operator(full_name="Alice", home_zone="Z1")
        reset_clock("2026-08-01T00:01:00Z")
        op_b = add_operator(full_name="Bob", home_zone="Z1")
        ticket = raise_ticket(station["id"], alarm_class="MAJOR")
        ack_ticket(ticket["id"])
        dispatched = dispatch_ticket(ticket["id"])
        assert dispatched["assigned_operator_id"] == op_a["id"], (
            "tie at 100 points each resolves to the earlier-created operator"
        )
        op_a_after = get_operator(op_a["id"])
        op_b_after = get_operator(op_b["id"])
        assert op_a_after["active_ticket_count"] == 1
        assert op_a_after["consecutive_callouts_24h"] == 1
        assert op_b_after["active_ticket_count"] == 0
        assert op_b_after["consecutive_callouts_24h"] == 0

    def test_callout_zone_match_outranks_other_zone(self, api):
        """PRD §3.3: "Each eligible operator receives a `callout_score`: 100
        points if the operator's `home_zone` equals the station's
        `service_zone` (0 otherwise), minus 50 points per currently active
        ticket, minus 10 points per consecutive callout in the trailing 24
        hours. The winner is the highest score, with ties broken by the
        operator's earlier `created_at`."

        Design: Difficulty/combinatorial_formula/callout_score_tiebreak_determinism
        """
        reset_clock()
        station = create_station(service_zone="Z1")
        op_far = add_operator(full_name="Far", home_zone="Z9")
        reset_clock("2026-08-01T00:01:00Z")
        op_near = add_operator(full_name="Near", home_zone="Z1")
        ticket = raise_ticket(station["id"], alarm_class="MINOR")
        ack_ticket(ticket["id"])
        dispatched = dispatch_ticket(ticket["id"])
        assert dispatched["assigned_operator_id"] == op_near["id"], (
            "zone match scores 100 vs 0 and wins regardless of creation order"
        )
        assert get_operator(op_far["id"])["active_ticket_count"] == 0

    def test_callout_empty_pool_without_required_cert_rejected(self, api, on_call_operator_headers):
        """PRD §3.3: "if the ticket's `alarm_class` is `CRITICAL`, the pool is
        further restricted to operators holding the `COLLECTIONS_2`
        certification. If the pool is empty — or, for a `CRITICAL` ticket, no
        active under-capacity operator holds `COLLECTIONS_2` — the dispatch is
        rejected with `ERR_NO_ELIGIBLE_OPERATOR` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/callout_empty_pool_boundary
        """
        reset_clock()
        station = create_station()
        add_operator(full_name="NoCert", certifications=["CSE_1"], home_zone="Z1")
        ticket = raise_ticket(station["id"], alarm_class="CRITICAL")
        ack_ticket(ticket["id"])
        current = get_ticket(ticket["id"])
        res = api.dispatch_alarm_ticket(ticket["id"], current["version"], on_call_operator_headers)
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_OPERATOR)

    def test_callout_empty_pool_no_operators_at_all(self, api, on_call_operator_headers):
        """PRD §3.3: "The eligible pool is every `Operator` with `is_active`
        true and an `active_ticket_count` below 3"
        PRD §3.3: "If the pool is empty — or, for a `CRITICAL` ticket, no
        active under-capacity operator holds `COLLECTIONS_2` — the dispatch is
        rejected with `ERR_NO_ELIGIBLE_OPERATOR` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/callout_empty_pool_boundary
        """
        reset_clock()
        station = create_station()
        ticket = raise_ticket(station["id"], alarm_class="MINOR")
        ack_ticket(ticket["id"])
        current = get_ticket(ticket["id"])
        res = api.dispatch_alarm_ticket(ticket["id"], current["version"], on_call_operator_headers)
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_OPERATOR)


class TestActiveTicketCountInvariant:
    def test_dispatch_clear_pair_returns_count_to_zero(self, api):
        """PRD §3.3: "Dispatch stamps `dispatched_at`, records the winner in
        `assigned_operator_id`, moves the ticket to `DISPATCHED`, and increments
        the winner's `active_ticket_count` and `consecutive_callouts_24h`."
        PRD §3.3: "clearing moves `ON_SCENE → CLEARED`, stamps `cleared_at`,
        computes `response_minutes` as the whole minutes between `raised_at` and
        `dispatched_at`, and decrements the operator's `active_ticket_count`."

        Design: Difficulty/compensating_invariant/operator_active_ticket_count_invariant
        """
        reset_clock()
        station, operator, ticket = setup_on_scene_ticket(alarm_class="MINOR")
        assert get_operator(operator["id"])["active_ticket_count"] == 1
        cleared = api.clear_alarm_ticket(
            ticket["id"], make_operator_headers(operator["id"]),
        )
        validate_success(cleared, 200)
        op_after = get_operator(operator["id"])
        assert op_after["active_ticket_count"] == 0, (
            "dispatch + clear must net to zero — no drift on the conserved counter"
        )
        assert get_ticket(ticket["id"])["status"] == "CLEARED"

    def test_dispatch_then_supervisor_cancel_returns_count_to_zero(
        self, api, operations_supervisor_headers
    ):
        """PRD §3.3: "An `OperationsSupervisor` may cancel an `ON_SCENE` ticket
        when its `alarm_class` is not `CRITICAL`; cancellation clears
        `assigned_operator_id` and decrements the operator's
        `active_ticket_count`."

        Design: Difficulty/compensating_invariant/operator_active_ticket_count_invariant
        """
        reset_clock()
        station, operator, ticket = setup_on_scene_ticket(alarm_class="MINOR")
        assert get_operator(operator["id"])["active_ticket_count"] == 1
        res = api.cancel_alarm_ticket(ticket["id"], operations_supervisor_headers)
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["assigned_operator_id"] is None
        assert get_operator(operator["id"])["active_ticket_count"] == 0


class TestSsoGatedClear:
    def test_sso_related_clear_blocked_while_sso_open(self, api):
        """PRD §3.3: "Clearing an SSO-flagged ticket carries an extra condition:
        if `is_sso_related` is true, the station must have an SSO event in
        `CONTAINED`, `REPORT_DRAFT`, `REPORT_SUBMITTED`, `REPORT_ACCEPTED`, or
        `CLOSED` — attempting to clear while the station's SSO event is still
        `OPEN` is rejected with `ERR_SSO_EVENT_OPEN` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/alarm_clear_requires_sso_state
        """
        reset_clock()
        station = create_station()
        operator = add_operator()
        create_sso(station["id"])
        ticket = raise_ticket(station["id"], alarm_class="MAJOR", is_sso_related=True)
        ack_ticket(ticket["id"])
        dispatch_ticket(ticket["id"])
        api.arrive_alarm_ticket(ticket["id"], make_operator_headers(operator["id"]))
        res = api.clear_alarm_ticket(ticket["id"], make_operator_headers(operator["id"]))
        validate_error(res, ApiErrorId.ERR_SSO_EVENT_OPEN)
        assert get_ticket(ticket["id"])["status"] == "ON_SCENE", "no transition on rejection"

    def test_sso_related_clear_succeeds_once_sso_contained(self, api):
        """PRD §3.3: "Clearing an SSO-flagged ticket carries an extra condition:
        if `is_sso_related` is true, the station must have an SSO event in
        `CONTAINED`, `REPORT_DRAFT`, `REPORT_SUBMITTED`, `REPORT_ACCEPTED`, or
        `CLOSED` — attempting to clear while the station's SSO event is still
        `OPEN` is rejected with `ERR_SSO_EVENT_OPEN` (HTTP 422)."
        PRD §3.8: "Containment is an `Operator` action allowed only while the
        station's posture is `EMERGENCY`, moving the event `OPEN → CONTAINED`,
        stamping `stopped_at`, and computing the provisional
        `estimated_volume_gal`."

        Design: Difficulty/cross_entity_state_dependency/alarm_clear_requires_sso_state
        """
        reset_clock()
        station = create_station()
        operator = add_operator()
        sso = create_sso(station["id"])
        ticket = raise_ticket(station["id"], alarm_class="MAJOR", is_sso_related=True)
        ack_ticket(ticket["id"])
        dispatch_ticket(ticket["id"])
        api.arrive_alarm_ticket(ticket["id"], make_operator_headers(operator["id"]))
        res = api.contain_sso_event(sso["id"], make_operator_headers(operator["id"]))
        validate_success(res, 200)
        cleared = api.clear_alarm_ticket(ticket["id"], make_operator_headers(operator["id"]))
        cleared_data = validate_success(cleared, 200)
        assert cleared_data["status"] == "CLEARED"
        assert cleared_data["cleared_at"] is not None
