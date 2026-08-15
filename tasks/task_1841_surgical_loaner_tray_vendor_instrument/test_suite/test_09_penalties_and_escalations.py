"""Penalty assessment lifecycle (assess, waive, settle), escalation
workflows, the missing-tray backfill loop, and case-cancellation cascade."""
from test_helpers import (
    COORD_1,
    COORD_2,
    ApiErrorId,
    assert_penalty_money_conservation,
    check_in,
    coordinator,
    deliver_and_verify,
    get_success_data,
    list_escalations_of_request,
    list_penalties_of_request,
    make_scheduler_headers,
    open_turn,
    release_turn_at,
    rep_headers,
    set_clock,
    setup_approved_request,
    setup_assessed_penalty,
    start_cycle_at,
    validate_error,
    validate_success,
    verify,
)
from test_helpers.factories import (
    create_access_pass_payload,
    create_escalation_payload,
    decide_access_pass_payload,
    resolve_escalation_payload,
    settle_penalty_payload,
    start_case_payload,
    waive_penalty_payload,
)

SCHEDULER = make_scheduler_headers()


class TestPenaltySettlement:
    def test_penalty_full_waive_closes_waived_closed(self, api):
        """PRD: "A waiver adds to `waived_cents`, recomputes
        `outstanding_cents` as the assessed amount minus waived minus settled,
        and subtracts the waived amount from the vendor's
        `outstanding_penalty_cents`. When a waiver brings the outstanding
        amount to exactly zero the penalty closes as `WAIVED_CLOSED`;
        otherwise it remains `ASSESSED` and further partial waivers may follow
        under the same guards."

        Design: Corner/state_machines/penalty_full_waive_closes_waived_closed
        """
        world, penalty = setup_assessed_penalty()
        assert penalty["assessed_cents"] == 5000

        # The verifier was coord-1, so the waiver runs as coord-2 (SoD).
        waived = validate_success(
            api.waive_penalty(penalty["id"],
                              waive_penalty_payload(5000,
                                                    "vendor relationship"),
                              coordinator(COORD_2)))
        assert waived["status"] == "WAIVED_CLOSED"
        assert waived["waived_cents"] == 5000
        assert waived["outstanding_cents"] == 0
        assert_penalty_money_conservation(waived)
        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_penalty_cents"] == 0

    def test_waiver_exceeds_outstanding_rejected(self, api):
        """PRD: "the waived amount may not exceed the penalty's
        `outstanding_cents`, else `ERR_WAIVER_EXCEEDS_OUTSTANDING` (422)."

        Design: Corner/validations/waiver_exceeds_outstanding_rejected
        """
        _world, penalty = setup_assessed_penalty()
        resp = api.waive_penalty(penalty["id"],
                                 waive_penalty_payload(5001, "goodwill"),
                                 coordinator(COORD_2))
        validate_error(resp, ApiErrorId.ERR_WAIVER_EXCEEDS_OUTSTANDING)
        after = validate_success(api.get_penalty(penalty["id"], coordinator()))
        assert after["status"] == "ASSESSED"
        assert after["outstanding_cents"] == 5000
        assert after["waived_cents"] == 0

    def test_settle_amount_mismatch_rejected(self, api):
        """PRD: "Settling requires the `settle_amount_cents` to equal the
        outstanding amount exactly — anything else is
        `ERR_SETTLE_AMOUNT_MISMATCH` (422) — adds to `settled_cents`, zeroes
        `outstanding_cents`, subtracts the settled amount from the vendor
        rollup, and moves the penalty to terminal `SETTLED`."

        Design: Corner/validations/settle_amount_mismatch_rejected
        """
        _world, penalty = setup_assessed_penalty()
        resp = api.settle_penalty(penalty["id"], settle_penalty_payload(4999),
                                  coordinator(COORD_2))
        validate_error(resp, ApiErrorId.ERR_SETTLE_AMOUNT_MISMATCH)
        assert validate_success(
            api.get_penalty(penalty["id"], coordinator()))["status"] == "ASSESSED"

        settled = validate_success(
            api.settle_penalty(penalty["id"], settle_penalty_payload(5000),
                               coordinator(COORD_2)))
        assert settled["status"] == "SETTLED"
        assert settled["settled_cents"] == 5000
        assert settled["outstanding_cents"] == 0
        assert_penalty_money_conservation(settled)

    def test_sod_waive_same_user_rejected(self, api):
        """PRD: "That same identifier is thereafter barred from two settlement
        operations on the same request: reconciling any pickup of that
        request, and waiving any amount on the penalty that the check-in's
        late delivery created. Either attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD: "The rule is per-request and per-person: a different coordinator
        may reconcile and waive freely"

        Design: Corner/validations/sod_waive_same_user_rejected
        """
        # Verifier of the originating check-in: coord-1.
        _world, penalty = setup_assessed_penalty(verifier_id=COORD_1)
        resp = api.waive_penalty(penalty["id"],
                                 waive_penalty_payload(2000, "goodwill"),
                                 coordinator(COORD_1))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        waived = validate_success(
            api.waive_penalty(penalty["id"],
                              waive_penalty_payload(2000, "goodwill"),
                              coordinator(COORD_2)))
        assert waived["status"] == "ASSESSED"
        assert waived["waived_cents"] == 2000
        assert waived["outstanding_cents"] == 3000


class TestWaiveSettledPriority:
    """Difficulty instance: on a SETTLED penalty a 1-cent waiver violates
    both the state guard (tier 6) and the fiscal bound (tier 11); the first
    failing tier answers."""

    def _settled_penalty(self, api):
        world, penalty = setup_assessed_penalty(verifier_id=COORD_1)
        settled = validate_success(
            api.settle_penalty(penalty["id"], settle_penalty_payload(5000),
                               coordinator(COORD_2)))
        assert settled["status"] == "SETTLED"
        assert settled["outstanding_cents"] == 0
        return world, settled

    def test_waive_on_settled_penalty_reports_state_error(self, api):
        """PRD: "When several rules could reject the same request, the server
        evaluates them in a fixed global order, and the caller receives the
        error from the first failing tier."
        PRD: "**State guards** — the target entity is in a state that permits the
        invoked transition, else the per-entity state error (the
        `ERR_{ENTITY}_INVALID_STATE` family, `ERR_VENDOR_NOT_ACTIVE`,
        `ERR_CASE_READINESS_BLOCKED`, `ERR_VENDOR_HAS_OPEN_WORK`) at 409."
        PRD: "Assessing requires the penalty to be `ACCRUING` (else
        `ERR_PENALTY_INVALID_STATE` at 409)"

        Design: Difficulty/priority_pair_validation_conflict/waive_settled_state_error_beats_fiscal_error
        """
        _world, penalty = self._settled_penalty(api)
        # Waiving 1 cent on a SETTLED penalty also exceeds the zero
        # outstanding amount — the state guard answers first.
        resp = api.waive_penalty(penalty["id"],
                                 waive_penalty_payload(1, "goodwill"),
                                 coordinator(COORD_2))
        validate_error(resp, ApiErrorId.ERR_PENALTY_INVALID_STATE)

    def test_waive_on_settled_penalty_leaves_books_untouched(self, api):
        """PRD: "Settling requires the `settle_amount_cents` to equal the
        outstanding amount exactly — anything else is
        `ERR_SETTLE_AMOUNT_MISMATCH` (422) — adds to `settled_cents`, zeroes
        `outstanding_cents`, subtracts the settled amount from the vendor
        rollup, and moves the penalty to terminal `SETTLED`."
        PRD: "Penalties still `ACCRUING`, already `SETTLED`, closed as
        `WAIVED_CLOSED`, or annulled as `VOID` contribute nothing."

        Design: Difficulty/priority_pair_validation_conflict/waive_settled_state_error_beats_fiscal_error
        """
        world, penalty = self._settled_penalty(api)
        resp = api.waive_penalty(penalty["id"],
                                 waive_penalty_payload(1, "goodwill"),
                                 coordinator(COORD_2))
        validate_error(resp, ApiErrorId.ERR_PENALTY_INVALID_STATE)

        after = validate_success(api.get_penalty(penalty["id"], coordinator()))
        assert after["status"] == "SETTLED"
        assert after["waived_cents"] == 0
        assert after["settled_cents"] == 5000
        assert after["outstanding_cents"] == 0
        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_penalty_cents"] == 0


class TestLateDeliveryPenaltyCombination:
    """Difficulty instance: grace + ceiling hours + per-assessment cap +
    delay surcharge on one penalty."""

    def _late_world(self, api):
        """URGENT request (deadline 2026-08-02T09:00) delivered 1425 minutes
        late (2026-08-03T08:45); case started 09:50 under override; completed
        with no delay events (final vendor delay = provisional 50)."""
        world = setup_approved_request()
        deliver_and_verify(world, at="2026-08-03T08:45:00Z")
        turn = open_turn(world["trays"][0]["id"])
        start_cycle_at(world, turn["id"], "2026-08-03T09:15:00Z")
        set_clock("2026-08-03T09:50:00Z")
        get_success_data(
            api.start_case(world["case"]["id"],
                           start_case_payload(
                               override_readiness=True,
                               override_reason="surgeon proceeds without tray"),
                           SCHEDULER))
        release_turn_at(turn["id"], "2026-08-03T10:50:00Z")
        set_clock("2026-08-03T12:30:00Z")
        get_success_data(api.complete_case(world["case"]["id"], SCHEDULER))
        penalties = list_penalties_of_request(world["request"]["id"])
        assert len(penalties) == 1
        return world, penalties[0]

    def test_late_penalty_time_charge_uses_ceil_and_cap(self, api):
        """PRD: "The new penalty snapshots `late_minutes` from the check-in,
        links back through `check_in_id` and `request_id`, and computes
        `billable_minutes` as the late minutes minus the grace minutes,
        floored at zero, and `time_charge_cents` as the vendor's
        `late_rate_per_hour_cents` multiplied by the billable hours — billable
        minutes divided by sixty, rounded up to a whole hour — with the result
        capped at the vendor's `late_penalty_cap_cents`"
        PRD: "The per-assessment cap is applied after the rate multiplication,
        and it is applied separately to the time charge and to the delay
        surcharge — the two components are each capped on their own before
        they are summed."

        Design: Difficulty/combinatorial_formula/late_delivery_penalty_grace_ceil_cap_surcharge
        """
        _world, penalty = self._late_world(api)
        assert penalty["late_minutes"] == 1425
        assert penalty["billable_minutes"] == 1410, "1425 late minus 15 grace"
        # ceil(1410/60) = 24 billable hours x 5000 = 120000, capped to 20000.
        assert penalty["time_charge_cents"] == 20000
        assert penalty["delay_surcharge_cents"] == 0, "stays 0 while ACCRUING"
        assert penalty["assessed_cents"] == 20000
        assert penalty["status"] == "ACCRUING"

    def test_late_penalty_assess_adds_capped_delay_surcharge(self, api):
        """PRD: "Assessment computes `delay_surcharge_cents` as the case's
        `vendor_delay_minutes_final` multiplied by the vendor's
        `delay_surcharge_per_minute_cents`, capped at the vendor's
        `late_penalty_cap_cents`; sets `assessed_cents` to the sum of
        `time_charge_cents` and `delay_surcharge_cents`; initializes
        `outstanding_cents` to the assessed amount; recomputes the request's
        `penalty_exposure_cents`; and adds the outstanding amount onto the
        vendor's `outstanding_penalty_cents`."
        PRD: "if no events exist at all, it inherits
        `vendor_delay_minutes_provisional`."

        Design: Difficulty/combinatorial_formula/late_delivery_penalty_grace_ceil_cap_surcharge
        """
        world, penalty = self._late_world(api)
        assessed = validate_success(
            api.assess_penalty(penalty["id"], coordinator(COORD_1)))
        # Final vendor delay 50 minutes x 250/min = 12500 (under the 20000
        # cap, applied separately from the time charge).
        assert assessed["delay_surcharge_cents"] == 12500
        assert assessed["assessed_cents"] == 32500
        assert assessed["outstanding_cents"] == 32500
        assert assessed["status"] == "ASSESSED"
        assert_penalty_money_conservation(assessed)

        request = validate_success(
            api.get_request(world["request"]["id"], coordinator()))
        assert request["penalty_exposure_cents"] == 32500
        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_penalty_cents"] == 32500


class TestPenaltyMoneyInvariant:
    """Difficulty instance: assessed == waived + settled + outstanding after
    every transition, with the vendor rollup draining in lockstep."""

    def test_penalty_invariant_holds_across_waive(self, api):
        """PRD: "A waiver adds to `waived_cents`, recomputes
        `outstanding_cents` as the assessed amount minus waived minus settled,
        and subtracts the waived amount from the vendor's
        `outstanding_penalty_cents`."

        Design: Difficulty/compensating_invariant/penalty_assessed_equals_waived_plus_settled_plus_outstanding
        """
        world, penalty = setup_assessed_penalty(verifier_id=COORD_1)
        assert penalty["assessed_cents"] == 5000
        assert_penalty_money_conservation(penalty)  # 5000 == 0 + 0 + 5000
        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_penalty_cents"] == 5000

        waived = validate_success(
            api.waive_penalty(penalty["id"],
                              waive_penalty_payload(2000, "partial goodwill"),
                              coordinator(COORD_2)))
        assert waived["status"] == "ASSESSED"
        # 5000 == 2000 (waived) + 0 (settled) + 3000 (outstanding).
        assert waived["waived_cents"] == 2000
        assert waived["settled_cents"] == 0
        assert waived["outstanding_cents"] == 3000
        assert_penalty_money_conservation(waived)
        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_penalty_cents"] == 3000

    def test_penalty_invariant_holds_through_settle(self, api):
        """PRD: "Settling requires the `settle_amount_cents` to equal the
        outstanding amount exactly — anything else is
        `ERR_SETTLE_AMOUNT_MISMATCH` (422) — adds to `settled_cents`, zeroes
        `outstanding_cents`, subtracts the settled amount from the vendor
        rollup, and moves the penalty to terminal `SETTLED`."
        PRD: "Penalties still `ACCRUING`, already `SETTLED`, closed as
        `WAIVED_CLOSED`, or annulled as `VOID` contribute nothing."

        Design: Difficulty/compensating_invariant/penalty_assessed_equals_waived_plus_settled_plus_outstanding
        """
        world, penalty = setup_assessed_penalty(verifier_id=COORD_1)
        get_success_data(
            api.waive_penalty(penalty["id"],
                              waive_penalty_payload(2000, "partial goodwill"),
                              coordinator(COORD_2)))
        settled = validate_success(
            api.settle_penalty(penalty["id"], settle_penalty_payload(3000),
                               coordinator(COORD_1)))
        assert settled["status"] == "SETTLED"
        # 5000 == 2000 (waived) + 3000 (settled) + 0 (outstanding).
        assert settled["waived_cents"] == 2000
        assert settled["settled_cents"] == 3000
        assert settled["outstanding_cents"] == 0
        assert_penalty_money_conservation(settled)
        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_penalty_cents"] == 0, \
            "the rollup drained 5000 -> 3000 -> 0 in lockstep"


class TestEscalations:
    def test_tray_missing_backfill_cycle(self, api):
        """PRD: "when an expected tray simply does not arrive, marking it
        missing moves it from `EXPECTED` to `MISSING` — any other starting
        state is rejected with `ERR_TRAY_INVALID_STATE` — auto-creates an
        `OPEN` escalation of type `MISSING_TRAY` with `linked_tray_id`
        pointing at the tray, and recomputes the request's readiness."
        PRD: "must still be `EXPECTED` or `MISSING` (any other state fails
        with `ERR_TRAY_INVALID_STATE` at 409, and a `MISSING` tray covered
        here is simply a backfill delivery)"
        PRD: "One resolution guard protects the backfill story: resolving a
        `MISSING_TRAY` escalation with `BACKFILL_DELIVERY` requires the
        linked tray to have actually materialized — it must stand in
        `DELIVERY_PENDING`, `CHECKED_IN`, `PROCESSING`, `STERILE_READY`,
        `STAGED`, `IN_USE`, `USED`, `AWAITING_PICKUP`, `PICKED_UP`, or
        `RECONCILED`; a tray still `EXPECTED`, `MISSING`, or `CANCELLED`
        fails with `ERR_ESCALATION_RESOLUTION_INVALID` (409)."

        Design: Corner/state_machines/tray_missing_backfill_cycle
        """
        world = setup_approved_request()
        tray = world["trays"][0]
        set_clock("2026-08-02T10:00:00Z")
        missing = validate_success(api.mark_tray_missing(tray["id"],
                                                         coordinator()))
        assert missing["status"] == "MISSING"
        escalations = list_escalations_of_request(world["request"]["id"],
                                                  type="MISSING_TRAY")
        assert len(escalations) == 1
        escalation = escalations[0]
        assert escalation["status"] == "OPEN"
        assert escalation["linked_tray_id"] == tray["id"]

        # Backfill: the missing tray is delivered and accepted.
        ci = check_in(world)
        verify(world, ci)
        tray_after = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_after["status"] == "CHECKED_IN", \
            "MISSING -> DELIVERY_PENDING -> CHECKED_IN via backfill delivery"

        resolved = validate_success(
            api.resolve_escalation(
                escalation["id"],
                resolve_escalation_payload("BACKFILL_DELIVERY"),
                coordinator()))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_type"] == "BACKFILL_DELIVERY"

    def test_escalate_backfill_resolution_guard_rejected(self, api):
        """PRD: "resolving a `MISSING_TRAY` escalation with
        `BACKFILL_DELIVERY` requires the linked tray to have actually
        materialized — it must stand in `DELIVERY_PENDING`, `CHECKED_IN`,
        `PROCESSING`, `STERILE_READY`, `STAGED`, `IN_USE`, `USED`,
        `AWAITING_PICKUP`, `PICKED_UP`, or `RECONCILED`; a tray still
        `EXPECTED`, `MISSING`, or `CANCELLED` fails with
        `ERR_ESCALATION_RESOLUTION_INVALID` (409)."
        PRD: "Resolving moves an escalation from `OPEN` or `ACKNOWLEDGED` to
        terminal `RESOLVED` and stamps the payload's `resolution_type`, one of
        `BACKFILL_DELIVERY`, `SUBSTITUTE_APPROVED`, `CASE_RESCHEDULED`,
        `CASE_CANCELLED`, or `WAIVED`."

        Design: Corner/state_machines/escalate_backfill_resolution_guard_rejected
        """
        world = setup_approved_request(priority_class="STANDARD",
                                       case_start="2026-08-10T09:00:00Z",
                                       case_end="2026-08-10T12:00:00Z")
        tray = world["trays"][0]
        get_success_data(api.mark_tray_missing(tray["id"], coordinator()))
        escalations = list_escalations_of_request(world["request"]["id"],
                                                  type="MISSING_TRAY")
        escalation = escalations[0]

        resp = api.resolve_escalation(
            escalation["id"], resolve_escalation_payload("BACKFILL_DELIVERY"),
            coordinator())
        validate_error(resp, ApiErrorId.ERR_ESCALATION_RESOLUTION_INVALID)

        resolved = validate_success(
            api.resolve_escalation(
                escalation["id"],
                resolve_escalation_payload("SUBSTITUTE_APPROVED"),
                coordinator()))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_type"] == "SUBSTITUTE_APPROVED"

    def test_escalation_acknowledge_twice_rejected(self, api):
        """PRD: "Acknowledging moves one from `OPEN` to `ACKNOWLEDGED` —
        acknowledging anything else fails with
        `ERR_ESCALATION_INVALID_STATE` (409)."

        Design: Corner/state_machines/escalation_acknowledge_twice_rejected
        """
        world = setup_approved_request(priority_class="STANDARD",
                                       case_start="2026-08-10T09:00:00Z",
                                       case_end="2026-08-10T12:00:00Z")
        tray = world["trays"][0]
        get_success_data(api.mark_tray_missing(tray["id"], coordinator()))
        escalation = list_escalations_of_request(world["request"]["id"])[0]

        acknowledged = validate_success(
            api.acknowledge_escalation(escalation["id"], coordinator()))
        assert acknowledged["status"] == "ACKNOWLEDGED"
        resp = api.acknowledge_escalation(escalation["id"], coordinator())
        validate_error(resp, ApiErrorId.ERR_ESCALATION_INVALID_STATE)


class TestCaseCancelCascade:
    def test_case_cancel_cascades_to_request_tray_penalty_pass_escalation(self, api):
        """PRD: "Its cascade is total: linked loaner requests in `DRAFT`,
        `SUBMITTED`, or `APPROVED` move to `CANCELLED`; their non-terminal
        trays — `EXPECTED`, `DELIVERY_PENDING`, `CHECKED_IN`, `PROCESSING`,
        `QUARANTINED`, or `MISSING` — move to `CANCELLED` as well; penalty
        assessments of those requests still `ACCRUING` move to `VOID`; access
        passes of the case still `REQUESTED` are `DENIED` with
        `denial_reason` `case_cancelled`, and those `APPROVED` are `REVOKED`;
        and escalations of those requests in `OPEN` or `ACKNOWLEDGED` resolve
        with `resolution_type` `CASE_CANCELLED`."

        Design: Corner/state_machines/case_cancel_cascades_to_request_tray_penalty_pass_escalation
        """
        world = setup_approved_request()
        # Late delivery (75 minutes) so verification spawns an ACCRUING
        # penalty; tray stays CHECKED_IN.
        deliver_and_verify(world, at="2026-08-02T10:15:00Z")
        penalty = list_penalties_of_request(world["request"]["id"])[0]
        escalation = get_success_data(
            api.create_escalation(world["request"]["id"],
                                  create_escalation_payload("LATE_DELIVERY"),
                                  coordinator()), 201)
        pass_ = get_success_data(
            api.create_access_pass(
                create_access_pass_payload(world["rep"]["id"],
                                           world["case"]["id"]),
                rep_headers(world["rep"])), 201)
        get_success_data(
            api.decide_access_pass(pass_["id"],
                                   decide_access_pass_payload("APPROVE"),
                                   coordinator()))

        cancelled = validate_success(api.cancel_case(world["case"]["id"],
                                                     SCHEDULER))
        assert cancelled["status"] == "CANCELLED"

        request = validate_success(
            api.get_request(world["request"]["id"], coordinator()))
        assert request["status"] == "CANCELLED"
        assert request["penalty_exposure_cents"] == 0, \
            "the voided penalty no longer counts toward exposure"
        tray = validate_success(api.get_tray(world["trays"][0]["id"],
                                             coordinator()))
        assert tray["status"] == "CANCELLED"
        penalty_after = validate_success(api.get_penalty(penalty["id"],
                                                         coordinator()))
        assert penalty_after["status"] == "VOID"
        pass_after = validate_success(api.get_access_pass(pass_["id"],
                                                          coordinator()))
        assert pass_after["status"] == "REVOKED"
        escalation_after = validate_success(
            api.get_escalation(escalation["id"], coordinator()))
        assert escalation_after["status"] == "RESOLVED"
        assert escalation_after["resolution_type"] == "CASE_CANCELLED"
