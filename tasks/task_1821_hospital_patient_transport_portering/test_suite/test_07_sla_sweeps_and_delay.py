"""SLA posture sweeps, escalation ordering, delay attribution, offer TTL."""
from test_helpers import (
    accept_offer,
    add_equipment_asset,
    add_on_shift_transporter,
    assert_delay_record,
    create_dispatch_offer,
    create_location,
    create_transport_request,
    create_travel_edge,
    get_asset,
    get_request,
    list_delay_records,
    list_request_offers,
    run_sweep,
    set_clock,
    setup_assigned_trip,
    setup_transport_site,
    trip_event_ok,
)


class TestSweepEscalationOrder:
    def test_escalation_records_delay_against_the_new_target(self, api):
        """PRD §3.6: "Third, any `QUEUED` request whose freshly evaluated
        posture is `BREACHED` and whose priority is not yet `STAT` escalates
        one tier — `ROUTINE` to `URGENT` to `STAT` — incrementing
        `escalation_count`, and its posture is immediately recomputed against
        the new, tighter-or-looser target"
        PRD §3.6: "Fourth, for each request whose final posture is `BREACHED`
        while `QUEUED` or `ASSIGNED` and which has no `SLA_BREACH` delay record
        yet, the sweep creates one with `delay_minutes` equal to elapsed minus
        the current priority's target, `cause_code` `SYSTEM`, and
        `recorded_via` `SWEEP`."
        PRD §3.6: "The response-time service level assigns each priority a
        target: 120 minutes for `ROUTINE`, 45 for `URGENT`, and 15 for `STAT`."

        Design: Difficulty/combinatorial_formula/sla_escalation_evaluation_order
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        r1 = create_transport_request("P1", ward["id"], img["id"],
                                      priority="ROUTINE",
                                      required_equipment="PORTER_ONLY")

        # 121 minutes elapsed: strictly greater than the ROUTINE target (120).
        set_clock("2026-08-01T02:01:00Z")
        summary = run_sweep()
        assert summary["requests_escalated"] == 1
        assert summary["sla_records_created"] == 1
        assert summary["offers_expired"] == 0

        updated = get_request(r1["id"])
        assert updated["priority"] == "URGENT"
        assert updated["escalation_count"] == 1
        assert updated["sla_posture"] == "BREACHED", (
            "recomputed against the URGENT target, 121 > 45 still breaches")

        records, meta = list_delay_records(r1["id"])
        assert meta["total_count"] == 1
        assert_delay_record(records[0])
        assert records[0]["record_kind"] == "SLA_BREACH"
        assert records[0]["recorded_via"] == "SWEEP"
        assert records[0]["cause_code"] == "SYSTEM"
        assert records[0]["delay_minutes"] == 76, (
            "escalate-then-record: 121 elapsed minus the NEW URGENT target 45")

    def test_stat_request_breaches_without_escalating(self, api):
        """PRD §3.6: "Third, any `QUEUED` request whose freshly evaluated
        posture is `BREACHED` and whose priority is not yet `STAT` escalates
        one tier — `ROUTINE` to `URGENT` to `STAT` — incrementing
        `escalation_count`"
        PRD §3.6: "Fourth, for each request whose final posture is `BREACHED`
        while `QUEUED` or `ASSIGNED` and which has no `SLA_BREACH` delay record
        yet, the sweep creates one with `delay_minutes` equal to elapsed minus
        the current priority's target, `cause_code` `SYSTEM`, and
        `recorded_via` `SWEEP`."

        Design: Difficulty/combinatorial_formula/sla_escalation_evaluation_order
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        r1 = create_transport_request("P1", ward["id"], img["id"],
                                      priority="STAT",
                                      required_equipment="PORTER_ONLY")

        # 16 minutes elapsed against the STAT target of 15.
        set_clock("2026-08-01T00:16:00Z")
        summary = run_sweep()
        assert summary["requests_escalated"] == 0, (
            "STAT is the top tier and never escalates")
        assert summary["sla_records_created"] == 1

        updated = get_request(r1["id"])
        assert updated["priority"] == "STAT"
        assert updated["escalation_count"] == 0
        assert updated["sla_posture"] == "BREACHED"

        records, _meta = list_delay_records(r1["id"])
        assert len(records) == 1
        assert records[0]["record_kind"] == "SLA_BREACH"
        assert records[0]["recorded_via"] == "SWEEP"
        assert records[0]["delay_minutes"] == 1, "16 elapsed minus target 15"


class TestPostureThresholds:
    def test_at_risk_threshold_boundary_90(self, api):
        """PRD §3.6: "Elapsed time strictly greater than the target means
        `BREACHED`; elapsed time of at least three-quarters of the target,
        that fraction rounded down to a whole minute, without exceeding the
        target means `AT_RISK`; anything less is `ON_TRACK`."

        Design: Corner/calculations/at_risk_threshold_boundary_90
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        r1 = create_transport_request("P1", ward["id"], img["id"],
                                      priority="ROUTINE",
                                      required_equipment="PORTER_ONLY")

        # floor(3 x 120 / 4) == 90; at 89 minutes the request stays ON_TRACK.
        set_clock("2026-08-01T01:29:00Z")
        run_sweep()
        assert get_request(r1["id"])["sla_posture"] == "ON_TRACK"

        # At exactly 90 the inclusive lower boundary flips it to AT_RISK.
        set_clock("2026-08-01T01:30:00Z")
        run_sweep()
        assert get_request(r1["id"])["sla_posture"] == "AT_RISK"

    def test_posture_freezes_after_at_pickup(self, api):
        """PRD §3.5: "It stamps `at_pickup_at`, computes `response_minutes` as
        the whole-minute floor of the span from `created_at` to `at_pickup_at`,
        and freezes `sla_posture` one final time: `BREACHED` when
        `response_minutes` exceeds the priority's target, `AT_RISK` when it
        reaches at least three-quarters of the target rounded down to a whole
        minute, otherwise `ON_TRACK`. From this moment on, sweeps never mutate
        the posture again."
        PRD §3.6: "Second, the sweep recomputes `sla_posture` for every
        `QUEUED` or `ASSIGNED` request in `created_at` ascending order,
        incrementing `version` on each request whose posture actually changes."

        Design: Corner/state_machines/posture_freezes_after_at_pickup
        """
        world = setup_assigned_trip(equipment="PORTER_ONLY", priority="URGENT",
                                    patient_ref="P1")
        t1, r1 = world["transporter"], world["request"]
        set_clock("2026-08-01T00:10:00Z")
        arrived = trip_event_ok(r1["id"], "ARRIVE_PICKUP",
                                transporter_id=t1["id"])
        assert arrived["response_minutes"] == 10
        assert arrived["sla_posture"] == "ON_TRACK"

        # Ten hours later the frozen posture is untouched by the sweep.
        set_clock("2026-08-01T10:10:00Z")
        summary = run_sweep()
        assert summary["requests_escalated"] == 0
        assert summary["sla_records_created"] == 0
        frozen = get_request(r1["id"])
        assert frozen["sla_posture"] == "ON_TRACK"
        assert frozen["escalation_count"] == 0


class TestResponseBoundary:
    def test_response_exactly_at_target_stays_at_risk(self, api):
        """PRD §3.6: "The boundary is pinned: a request whose elapsed time
        equals its target exactly is still `AT_RISK`, because breach demands a
        strict excess."
        PRD §3.5: "and freezes `sla_posture` one final time: `BREACHED` when
        `response_minutes` exceeds the priority's target, `AT_RISK` when it
        reaches at least three-quarters of the target rounded down to a whole
        minute, otherwise `ON_TRACK`."

        Design: Difficulty/boundary_precision_check/response_boundary_exact_target
        """
        world = setup_assigned_trip(equipment="WHEELCHAIR", priority="ROUTINE",
                                    patient_ref="P1")
        t1, r1 = world["transporter"], world["request"]

        set_clock("2026-08-01T02:00:00Z")
        arrived = trip_event_ok(r1["id"], "ARRIVE_PICKUP",
                                transporter_id=t1["id"])
        assert arrived["response_minutes"] == 120, (
            "exactly the ROUTINE target")
        assert arrived["sla_posture"] == "AT_RISK", (
            "120 is not > 120; 120 >= floor(3 x 120 / 4) = 90")

        set_clock("2026-08-01T02:10:00Z")
        trip_event_ok(r1["id"], "PICKUP", transporter_id=t1["id"])
        completed = trip_event_ok(r1["id"], "COMPLETE", transporter_id=t1["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["sla_posture"] == "AT_RISK"

        records, meta = list_delay_records(r1["id"])
        assert meta["total_count"] == 0, (
            "no SLA_BREACH at the exact boundary; no appointment deadline set")
        assert records == []

    def test_response_one_minute_over_records_breach_on_completion(self, api):
        """PRD §3.5: "freezes `sla_posture` one final time: `BREACHED` when
        `response_minutes` exceeds the priority's target"
        PRD §3.5: "when `response_minutes` exceeded the priority's target and
        no `SLA_BREACH` record exists yet, one is created with `delay_minutes`
        equal to `response_minutes` minus the target, `cause_code` `SYSTEM`,
        and `recorded_via` `COMPLETION`."
        PRD §3.6: "The impact figure translates raw lateness into downstream
        schedule damage: `delay_minutes` multiplied by 2.0 when the
        destination's `location_type` is `OR`, by 1.5 for `IMAGING`, and by 1.0
        for `WARD`, `ICU`, `ED`, `DISCHARGE_LOUNGE`, and `OTHER`, with the
        product rounded half-up to whole minutes."

        Design: Difficulty/boundary_precision_check/response_boundary_exact_target
        """
        world = setup_assigned_trip(equipment="WHEELCHAIR", priority="ROUTINE",
                                    patient_ref="P1")
        t1, r1 = world["transporter"], world["request"]

        set_clock("2026-08-01T02:01:00Z")
        arrived = trip_event_ok(r1["id"], "ARRIVE_PICKUP",
                                transporter_id=t1["id"])
        assert arrived["response_minutes"] == 121
        assert arrived["sla_posture"] == "BREACHED"

        set_clock("2026-08-01T02:10:00Z")
        trip_event_ok(r1["id"], "PICKUP", transporter_id=t1["id"])
        trip_event_ok(r1["id"], "COMPLETE", transporter_id=t1["id"])

        records, meta = list_delay_records(r1["id"])
        assert meta["total_count"] == 1
        assert_delay_record(records[0])
        assert records[0]["record_kind"] == "SLA_BREACH"
        assert records[0]["recorded_via"] == "COMPLETION"
        assert records[0]["cause_code"] == "SYSTEM"
        assert records[0]["delay_minutes"] == 1, "121 response minus target 120"
        assert records[0]["impact_minutes"] == 2, (
            "round_half_up(1 x 1.5) for the IMAGING destination")


class TestDelayImpactDualVariant:
    def _late_urgent_stretcher_trip(self, destination_key, cause_code=None):
        """URGENT STRETCHER trip created at the clock start, arrived at 00:10
        (response 10, inside the URGENT target of 45) and completed at 00:50
        against an appointment deadline of 00:30."""
        site = setup_transport_site()
        dest = create_location("DST", "Destination", destination_key, "Z3")
        create_travel_edge(site["ward"]["id"], dest["id"], 10, 16)
        site["dst"] = dest
        world = setup_assigned_trip(
            equipment="STRETCHER", priority="URGENT", patient_ref="P1",
            appointment_deadline="2026-08-01T00:30:00Z", site=site,
            destination_key="dst")
        t1, r1 = world["transporter"], world["request"]
        set_clock("2026-08-01T00:10:00Z")
        trip_event_ok(r1["id"], "ARRIVE_PICKUP", transporter_id=t1["id"])
        trip_event_ok(r1["id"], "PICKUP", transporter_id=t1["id"])
        set_clock("2026-08-01T00:50:00Z")
        trip_event_ok(r1["id"], "COMPLETE", transporter_id=t1["id"],
                      cause_code=cause_code)
        return world

    def test_or_destination_doubles_impact(self, api):
        """PRD §3.5: "when an `appointment_deadline` was set and completion
        fell after it, and no `APPOINTMENT_LATE` record exists yet, one is
        created with `delay_minutes` equal to the whole-minute floor of the
        overrun, `cause_code` taken from the event payload's `cause_code` or
        `OTHER` when none was supplied, and `recorded_via` `COMPLETION`"
        PRD §3.6: "An OR-bound trip that runs 20 minutes late therefore records
        20 attributed minutes but 40 impact minutes."

        Design: Difficulty/dual_variant_calc/delay_impact_attributed_vs_cascade
        """
        world = self._late_urgent_stretcher_trip("OR",
                                                 cause_code="PATIENT_NOT_READY")
        r1 = world["request"]

        records, meta = list_delay_records(r1["id"])
        assert meta["total_count"] == 1, (
            "response was 10, inside the URGENT target of 45: no SLA_BREACH")
        record = records[0]
        assert_delay_record(record)
        assert record["record_kind"] == "APPOINTMENT_LATE"
        assert record["recorded_via"] == "COMPLETION"
        assert record["cause_code"] == "PATIENT_NOT_READY"
        assert record["delay_minutes"] == 20, "attributed variant"
        assert record["impact_minutes"] == 40, (
            "cascade variant: round_half_up(20 x 2.0) for OR")

    def test_ward_destination_keeps_impact_equal_to_delay(self, api):
        """PRD §3.6: "The impact figure translates raw lateness into downstream
        schedule damage: `delay_minutes` multiplied by 2.0 when the
        destination's `location_type` is `OR`, by 1.5 for `IMAGING`, and by 1.0
        for `WARD`, `ICU`, `ED`, `DISCHARGE_LOUNGE`, and `OTHER`, with the
        product rounded half-up to whole minutes."
        PRD §3.5: "`cause_code` taken from the event payload's `cause_code` or
        `OTHER` when none was supplied"

        Design: Difficulty/dual_variant_calc/delay_impact_attributed_vs_cascade
        """
        world = self._late_urgent_stretcher_trip("WARD", cause_code=None)
        r1 = world["request"]

        records, meta = list_delay_records(r1["id"])
        assert meta["total_count"] == 1
        record = records[0]
        assert record["record_kind"] == "APPOINTMENT_LATE"
        assert record["cause_code"] == "OTHER", (
            "no cause_code was supplied on COMPLETE")
        assert record["delay_minutes"] == 20
        assert record["impact_minutes"] == 20, (
            "cascade variant: round_half_up(20 x 1.0) for WARD")


class TestOfferExpiry:
    def test_offer_expiry_ttl_boundary(self, api):
        """PRD §3.4: "A time-driven sweep expires any `PENDING` offer that is
        strictly more than 10 minutes old, moving it to `EXPIRED` — an offer
        exactly 10 minutes old stays `PENDING`. Expiry returns its reserved
        asset to `AVAILABLE` but deliberately runs no auto-dispatch evaluation,
        and it leaves the request itself untouched: no version bump and no
        exclusion entry."

        Design: Corner/state_machines/offer_expiry_ttl_boundary
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        asset = add_equipment_asset("WC-001", "WHEELCHAIR", site["ward"]["id"])
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        create_dispatch_offer(r1, transporter_id=t1["id"])
        version_after_offer = get_request(r1["id"])["version"]

        # Exactly 10 minutes old: strictly-greater is not met, stays PENDING.
        set_clock("2026-08-01T00:10:00Z")
        summary = run_sweep()
        assert summary["offers_expired"] == 0
        offers, _meta = list_request_offers(r1["id"])
        assert offers[0]["status"] == "PENDING"

        # 11 minutes old: the sweep expires it and frees the asset.
        set_clock("2026-08-01T00:11:00Z")
        summary = run_sweep()
        assert summary["offers_expired"] == 1
        offers, _meta = list_request_offers(r1["id"])
        assert len(offers) == 1, (
            "expiry runs no auto-dispatch evaluation, so no replacement offer")
        assert offers[0]["status"] == "EXPIRED"
        assert get_asset(asset["id"])["status"] == "AVAILABLE"
        assert get_request(r1["id"])["version"] == version_after_offer, (
            "expiry leaves the request itself untouched: no version bump")
