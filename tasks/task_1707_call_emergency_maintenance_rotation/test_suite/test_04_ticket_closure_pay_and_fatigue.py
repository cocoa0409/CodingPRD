"""Ticket closure gates, callback pay pricing, and the fatigue cascade."""
from test_helpers import (
    ApiErrorId,
    approve_relocation,
    arrive_ticket,
    assert_same_instant,
    close_ticket,
    create_dispatched_ticket,
    create_incident_record,
    create_triaged_ticket,
    dispatch_ticket,
    get_shift,
    get_technician,
    get_ticket,
    make_supervisor,
    make_supervisor_headers,
    make_technician,
    make_unit,
    mitigate_ticket,
    propose_relocation,
    publish_shift,
    set_clock,
    start_shift,
    submit_incident_record,
    validate_error,
    validate_success,
)


class TestCloseRequiresSubmittedIncidentRecord:
    def _setup_mitigated_with_draft_record(self):
        """APPLIANCE ticket mitigated; incident record still DRAFT."""
        set_clock("2026-08-03T00:00:00Z")
        tech = make_technician()
        unit = make_unit(unit_number="U-801", building_code="B8")
        shift = publish_shift(tech["id"], "2026-08-03T00:00:00Z",
                              "2026-08-03T08:00:00Z")
        start_shift(shift["id"])
        ticket = create_dispatched_ticket(unit["id"], tech["id"], "APPLIANCE",
                                          description="Oven sparking")
        set_clock("2026-08-03T01:00:00Z")
        arrive_ticket(ticket["id"], tech["id"])
        ticket = mitigate_ticket(ticket["id"], tech["id"],
                                 mitigation_notes="Oven disconnected")
        record = create_incident_record(
            ticket["id"], tech["id"], narrative="Element shorted",
            estimated_damage_cents=12000,
        )
        return tech, unit, ticket, record

    def test_close_blocked_while_incident_record_draft(self, api,
                                                       dispatcher_headers):
        """PRD §3.4: "Two gates guard it, after the state check itself: the
        ticket's incident record must exist and be in `SUBMITTED`,
        `UNDER_REVIEW`, or `FINALIZED` (a missing record, or one still in
        `DRAFT` or `RETURNED`, fails with
        `ERR_INCIDENT_RECORD_NOT_SUBMITTED`)..."

        Design: Difficulty/cross_entity_state_dependency/ticket_close_blocked_until_incident_record_submitted
        """
        _tech, _unit, ticket, _record = self._setup_mitigated_with_draft_record()
        resp = api.close_call_ticket(ticket["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_RECORD_NOT_SUBMITTED)
        assert get_ticket(ticket["id"])["status"] == "MITIGATED"

    def test_close_unblocked_after_incident_record_submitted(self, api,
                                                             dispatcher_headers):
        """PRD §3.4: "the ticket's incident record must exist and be in
        `SUBMITTED`, `UNDER_REVIEW`, or `FINALIZED` (a missing record, or one
        still in `DRAFT` or `RETURNED`, fails with
        `ERR_INCIDENT_RECORD_NOT_SUBMITTED`)..."
        PRD §3.4: "A successful close stamps `closed_at` and prices the
        callback."

        Design: Difficulty/cross_entity_state_dependency/ticket_close_blocked_until_incident_record_submitted
        """
        tech, _unit, ticket, record = self._setup_mitigated_with_draft_record()
        validate_error(
            api.close_call_ticket(ticket["id"], dispatcher_headers),
            ApiErrorId.ERR_INCIDENT_RECORD_NOT_SUBMITTED,
        )
        submit_incident_record(record["id"], tech["id"])
        closed = validate_success(
            api.close_call_ticket(ticket["id"], dispatcher_headers), 200
        )
        assert closed["status"] == "CLOSED"


def test_relocation_close_blocked_without_approved_case(api, dispatcher_headers):
    """PRD §3.4: "when `unit_declared_uninhabitable` is true there must exist a
    relocation case for this ticket in `APPROVED`, `ACTIVE`, or `ENDED` (else
    `ERR_RELOCATION_UNRESOLVED`)."

    Design: Corner/validations/relocation_close_blocked_without_approved_case
    """
    set_clock("2026-08-01T00:00:00Z")
    tech = make_technician()
    sup = make_supervisor()
    unit = make_unit(unit_number="M-10", building_code="BM")
    shift = publish_shift(tech["id"], "2026-08-01T00:00:00Z",
                          "2026-08-01T08:00:00Z")
    start_shift(shift["id"])
    ticket = create_dispatched_ticket(unit["id"], tech["id"], "FLOOD",
                                      description="flood")
    arrive_ticket(ticket["id"], tech["id"])
    set_clock("2026-08-01T01:00:00Z")
    mitigate_ticket(ticket["id"], tech["id"], mitigation_notes="extracted",
                    unit_uninhabitable=True)
    record = create_incident_record(ticket["id"], tech["id"], narrative="n",
                                    estimated_damage_cents=50000)
    submit_incident_record(record["id"], tech["id"])

    resp = api.close_call_ticket(ticket["id"], dispatcher_headers)
    validate_error(resp, ApiErrorId.ERR_RELOCATION_UNRESOLVED)

    case = propose_relocation(unit["id"], ticket["id"], "2026-08-02T00:00:00Z",
                              "2026-08-04T00:00:00Z", 10000, tech["id"])
    approve_relocation(case["id"], make_supervisor_headers(sup["id"]))
    closed = validate_success(
        api.close_call_ticket(ticket["id"], dispatcher_headers), 200
    )
    assert closed["status"] == "CLOSED"


class TestFatigueCrossingCascade:
    def _setup_two_closures_crossing_cap(self):
        """T1 closes 400-min then 320-min callbacks (720 total at the cap)."""
        set_clock("2026-08-01T00:00:00Z")
        tech = make_technician()
        unit = make_unit(unit_number="U-502", building_code="B5")
        shift_a = publish_shift(tech["id"], "2026-08-01T00:00:00Z",
                                "2026-08-01T12:00:00Z")
        shift_b = publish_shift(tech["id"], "2026-08-01T18:00:00Z",
                                "2026-08-02T06:00:00Z")
        start_shift(shift_a["id"])

        ticket1 = create_dispatched_ticket(
            unit["id"], tech["id"], "NO_POWER",
            at="2026-08-01T00:10:00Z",
            description="Breaker keeps tripping",
        )
        set_clock("2026-08-01T00:40:00Z")
        arrive_ticket(ticket1["id"], tech["id"])
        set_clock("2026-08-01T06:50:00Z")
        mitigate_ticket(ticket1["id"], tech["id"],
                        mitigation_notes="Faulty breaker isolated")
        record1 = create_incident_record(ticket1["id"], tech["id"],
                                         narrative="Breaker swap needed",
                                         estimated_damage_cents=0)
        submit_incident_record(record1["id"], tech["id"])
        set_clock("2026-08-01T07:00:00Z")
        close_ticket(ticket1["id"])

        ticket2 = create_dispatched_ticket(
            unit["id"], tech["id"], "NO_POWER",
            at="2026-08-01T07:30:00Z",
            description="Second outage, burning smell",
        )
        set_clock("2026-08-01T08:00:00Z")
        arrive_ticket(ticket2["id"], tech["id"])
        set_clock("2026-08-01T12:50:00Z")
        mitigate_ticket(ticket2["id"], tech["id"],
                        mitigation_notes="Panel made safe")
        record2 = create_incident_record(ticket2["id"], tech["id"],
                                         narrative="Panel scorched",
                                         estimated_damage_cents=50000)
        submit_incident_record(record2["id"], tech["id"])
        set_clock("2026-08-01T13:00:00Z")
        close_ticket(ticket2["id"])
        return tech, shift_a, shift_b, ticket2

    def test_ticket_close_crossing_fatigue_cap_sets_block_window(self, api):
        """PRD §3.4: "If the previous total was below 720 minutes (twelve
        hours) and the recomputed total is at or above 720 — the boundary is
        inclusive, so landing exactly on 720 triggers — two things happen at
        once: the technician's `fatigue_block_until` is set to the triggering
        ticket's `mitigated_at` plus ten hours, ..."
        PRD §3.4: "The technician's `callback_minutes_168h` is recomputed as
        the sum of `callback_minutes` over all of that technician's tickets in
        `MITIGATED` or `CLOSED` whose `mitigated_at` falls inside the left-open
        rolling window — after now minus 168 hours, up to and including now."

        Design: Difficulty/transitive_cascade/ticket_close_fatigue_coverage_cascade
        """
        tech, _shift_a, _shift_b, _t2 = self._setup_two_closures_crossing_cap()
        after = get_technician(tech["id"])
        assert after["callback_minutes_168h"] == 720, "400 + 320 lands on the cap"
        assert_same_instant(after["fatigue_block_until"], "2026-08-01T22:50:00Z")

    def test_fatigue_crossing_flags_overlapping_published_shift_for_coverage(
        self, api
    ):
        """PRD §3.4: "...and every `PUBLISHED` rotation shift belonging to that
        technician whose window overlaps the rest window (its `start_at` before
        the block's end and its `end_at` after the triggering `mitigated_at`)
        is flagged `needs_coverage` true."

        Design: Difficulty/transitive_cascade/ticket_close_fatigue_coverage_cascade
        """
        tech, shift_a, shift_b, _t2 = self._setup_two_closures_crossing_cap()
        assert get_shift(shift_b["id"])["needs_coverage"] is True, (
            "PUBLISHED shift overlapping the rest window must be flagged"
        )
        assert get_shift(shift_a["id"])["needs_coverage"] is False, (
            "the ACTIVE shift outside the rule's PUBLISHED scope stays clear"
        )


def test_fatigue_719_minutes_stays_unblocked(api, dispatcher_headers):
    """PRD §3.4: "If the previous total was below 720 minutes (twelve hours)
    and the recomputed total is at or above 720 — the boundary is inclusive, so
    landing exactly on 720 triggers — ..." (719 stays below it; no block forms)
    PRD §3.4: "Separately from the crossing rule, every dispatch, shift
    publication, shift transfer, and work-order assignment performs a live
    block check against `fatigue_block_until` — at transfer the reference
    instant is the shift's `start_at`, elsewhere it is now — and rejects a
    blocked technician with `ERR_FATIGUE_REST_REQUIRED`."

    Design: Corner/calculations/fatigue_719_minutes_stays_unblocked
    """

    set_clock("2026-08-01T00:00:00Z")
    tech = make_technician()
    unit = make_unit(unit_number="C-3", building_code="BC")
    shift_a = publish_shift(tech["id"], "2026-08-01T00:00:00Z",
                            "2026-08-01T12:00:00Z")
    shift_c = publish_shift(tech["id"], "2026-08-01T12:00:00Z",
                            "2026-08-01T20:00:00Z")
    start_shift(shift_a["id"])

    ticket1 = create_dispatched_ticket(unit["id"], tech["id"], "NO_POWER",
                                       at="2026-08-01T00:10:00Z",
                                       description="outage")
    arrive_ticket(ticket1["id"], tech["id"])
    set_clock("2026-08-01T06:50:00Z")
    mitigate_ticket(ticket1["id"], tech["id"], mitigation_notes="done")
    record1 = create_incident_record(ticket1["id"], tech["id"], narrative="n1",
                                     estimated_damage_cents=0)
    submit_incident_record(record1["id"], tech["id"])
    set_clock("2026-08-01T07:00:00Z")
    close_ticket(ticket1["id"])

    ticket2 = create_dispatched_ticket(unit["id"], tech["id"], "NO_POWER",
                                       at="2026-08-01T07:30:00Z",
                                       description="outage again")
    arrive_ticket(ticket2["id"], tech["id"])
    set_clock("2026-08-01T12:49:00Z")
    mitigate_ticket(ticket2["id"], tech["id"], mitigation_notes="done")
    record2 = create_incident_record(ticket2["id"], tech["id"], narrative="n2",
                                     estimated_damage_cents=0)
    submit_incident_record(record2["id"], tech["id"])
    set_clock("2026-08-01T12:55:00Z")
    close_ticket(ticket2["id"])

    start_shift(shift_c["id"])
    set_clock("2026-08-01T13:00:00Z")
    ticket3 = create_triaged_ticket(unit["id"], "LOCKOUT", description="lockout")

    after = get_technician(tech["id"])
    assert after["callback_minutes_168h"] == 719, "400 + 319 stays below 720"
    assert after["fatigue_block_until"] is None, "no crossing means no block"
    assert get_shift(shift_c["id"])["needs_coverage"] is False

    dispatched = dispatch_ticket(ticket3["id"], tech["id"], dispatcher_headers)
    assert dispatched["status"] == "DISPATCHED", (
        "an unblocked technician remains dispatchable"
    )


def test_dispatch_blocked_during_fatigue_rest_window(api, dispatcher_headers):
    """PRD §3.3: "Validation runs in the global order of §2.9: the ticket's
    state is confirmed first (`ERR_CALL_TICKET_INVALID_STATE`), then the
    version check (`ERR_STALE_CALL_TICKET_VERSION`), then the fatigue gate —
    the technician's `fatigue_block_until` must be null or already past (else
    `ERR_FATIGUE_REST_REQUIRED`) — and finally the on-shift verification, which
    requires the technician to be `ACTIVE` and to hold a RotationShift in
    `ACTIVE` whose window covers now (else `ERR_TECHNICIAN_NOT_ON_SHIFT`)."

    Design: Corner/validations/dispatch_blocked_during_fatigue_rest_window
    """

    set_clock("2026-08-01T00:00:00Z")
    tech = make_technician()
    unit = make_unit(unit_number="M-9", building_code="BM")
    shift = publish_shift(tech["id"], "2026-08-01T00:00:00Z",
                          "2026-08-01T13:00:00Z")
    start_shift(shift["id"])

    ticket1 = create_dispatched_ticket(unit["id"], tech["id"], "NO_HEAT",
                                       at="2026-08-01T00:00:00Z",
                                       description="furnace")
    set_clock("2026-08-01T00:30:00Z")
    arrive_ticket(ticket1["id"], tech["id"])
    set_clock("2026-08-01T12:00:00Z")
    mitigate_ticket(ticket1["id"], tech["id"], mitigation_notes="done")
    record = create_incident_record(ticket1["id"], tech["id"], narrative="n",
                                    estimated_damage_cents=0)
    submit_incident_record(record["id"], tech["id"])
    set_clock("2026-08-01T12:05:00Z")
    close_ticket(ticket1["id"])

    set_clock("2026-08-01T21:00:00Z")
    ticket2 = create_triaged_ticket(unit["id"], "LOCKOUT", description="lockout")
    version = get_ticket(ticket2["id"])["version"]
    resp = api.dispatch_call_ticket(
        ticket2["id"],
        {"technician_id": tech["id"], "expected_call_ticket_version": version},
        dispatcher_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FATIGUE_REST_REQUIRED)
    assert get_ticket(ticket2["id"])["status"] == "TRIAGED"


class TestCallbackPay:
    def _setup_night_weekend_hazard_closure(self):
        """GAS_LEAK ticket dispatched Saturday 23:00 UTC, 45-minute callback."""
        set_clock("2026-08-01T22:00:00Z")
        tech = make_technician(base_hourly_rate_cents=4800,
                               on_call_differential_bp=1500)
        unit = make_unit(unit_number="U-201", building_code="B2")
        shift = publish_shift(tech["id"], "2026-08-01T18:00:00Z",
                              "2026-08-02T06:00:00Z")
        start_shift(shift["id"])
        ticket = create_dispatched_ticket(
            unit["id"], tech["id"], "GAS_LEAK",
            at="2026-08-01T23:00:00Z", description="Smell of gas",
        )
        set_clock("2026-08-01T23:20:00Z")
        arrive_ticket(ticket["id"], tech["id"])
        set_clock("2026-08-01T23:45:00Z")
        mitigate_ticket(ticket["id"], tech["id"],
                        mitigation_notes="Gas shut at meter, ventilated")
        record = create_incident_record(
            ticket["id"], tech["id"],
            narrative="Gas leak at flex line; shut and vented",
            estimated_damage_cents=0,
        )
        submit_incident_record(record["id"], tech["id"])
        set_clock("2026-08-01T23:50:00Z")
        return close_ticket(ticket["id"])

    def test_callback_pay_stacks_night_weekend_hazard_multipliers(self, api):
        """PRD §3.4: "The **billed duration** is the ticket's
        `callback_minutes`, raised to a two-hour minimum when the actual
        callback ran shorter. The **effective rate** starts from the assigned
        technician's `base_hourly_rate_cents` and stacks three multiplicative
        uplifts, each read from the ticket's `dispatched_at` and `category` —
        never from arrival or close time: 1.5 when the dispatch time-of-day
        falls in the night window (at or after 22:00 UTC, strictly before
        06:00 UTC); 1.25 when the dispatch fell on a Saturday or Sunday in
        UTC; and 1.5 when the category is `GAS_LEAK` or `FLOOD`."

        Design: Difficulty/combinatorial_formula/callback_pay_night_weekend_hazard_stacking
        """
        closed = self._setup_night_weekend_hazard_closure()
        assert closed["callback_pay_cents"] == 27000, (
            "max(45, 120) = 120 min; 4800 x 1.5 x 1.25 x 1.5 = 13500 cents/h; "
            "2h x 13500 = 27000"
        )
        assert closed["status"] == "CLOSED"

    def test_callback_minutes_measured_dispatch_to_mitigation(self, api):
        """PRD §3.4: "it stamps `mitigated_at`, computes `callback_minutes` as
        the whole minutes from `dispatched_at` to `mitigated_at`..."
        PRD §3.3: "sets `response_breach` to true only when `response_minutes`
        is strictly greater than `sla_target_minutes` — a response landing
        exactly on the target is not a breach."

        Design: Difficulty/combinatorial_formula/callback_pay_night_weekend_hazard_stacking
        """
        closed = self._setup_night_weekend_hazard_closure()
        assert closed["callback_minutes"] == 45, (
            "23:00 dispatch to 23:45 mitigation"
        )
        assert closed["response_breach"] is False, (
            "20-minute response on a 30-minute hazard target does not breach"
        )

    def test_callback_pay_plain_daytime_uses_callout_floor_only(self, api):
        """PRD §3.4: "The **billed duration** is the ticket's
        `callback_minutes`, raised to a two-hour minimum when the actual
        callback ran shorter."
        PRD §3.4: "The `callback_pay_cents` stored on the ticket is the billed
        minutes divided by sixty, multiplied by the effective rate, rounded
        half-up to whole cents."

        Design: Corner/calculations/callback_pay_plain_daytime_uses_callout_floor_only
        """
        set_clock("2026-08-03T09:00:00Z")
        tech = make_technician(base_hourly_rate_cents=4800,
                               on_call_differential_bp=1500)
        unit = make_unit(unit_number="C-2", building_code="BC")
        shift = publish_shift(tech["id"], "2026-08-03T09:00:00Z",
                              "2026-08-03T18:00:00Z")
        start_shift(shift["id"])
        ticket = create_dispatched_ticket(
            unit["id"], tech["id"], "LOCKOUT",
            at="2026-08-03T10:00:00Z", description="locked out",
        )
        set_clock("2026-08-03T10:20:00Z")
        arrive_ticket(ticket["id"], tech["id"])
        set_clock("2026-08-03T10:45:00Z")
        mitigate_ticket(ticket["id"], tech["id"], mitigation_notes="Re-keyed")
        record = create_incident_record(ticket["id"], tech["id"],
                                        narrative="Lock replaced",
                                        estimated_damage_cents=8000)
        submit_incident_record(record["id"], tech["id"])
        set_clock("2026-08-03T10:50:00Z")
        closed = close_ticket(ticket["id"])
        assert closed["callback_minutes"] == 45
        assert closed["callback_pay_cents"] == 9600, (
            "Monday daytime non-hazard: 120-minute floor x 4800 cents/h, "
            "all multipliers 1.0"
        )
