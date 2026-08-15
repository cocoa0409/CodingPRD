"""Linehaul legs: relay connect buffering, provisional vs planned ETA variants,
relay sequencing on departure, leg window validity, and the arrival cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    arrive_leg,
    create_linehaul_leg_payload,
    depart_leg,
    get_success_data,
    get_trailer,
    make_relay_chain,
    make_sealed_trailer,
    make_terminal,
    make_terminal_pair,
    make_trailer,
    plan_leg,
    validate_error,
)

DISP = TEST_USERS["dispatcher_headers"]
DOCK = TEST_USERS["dock_supervisor_headers"]


class TestProvisionalEta:
    def test_leg1_provisional_eta_includes_accrued_delay(self, api):
        """PRD §3.6: "The accrued departure delay is the difference between the
        actual and planned departure instants, expressed in whole minutes and
        floored at zero — an early departure accrues no negative delay. The
        leg's `provisional_eta_utc` is its `planned_arrival_utc` plus those
        accrued delay minutes."
        PRD §3.6: "Before any leg of the chain has departed, projections use
        planned times only, with no accrued delay."

        Design: Difficulty/dual_variant_calc/relay_eta_planned_vs_provisional_divergence
        """
        chain = make_relay_chain()
        # PLANNED_ETA variant: nothing departed yet, projections are planned-only.
        leg1_before = get_success_data(api.get_linehaul_leg(chain["leg1"]["id"],
                                                            headers=DISP))
        leg2_before = get_success_data(api.get_linehaul_leg(chain["leg2"]["id"],
                                                            headers=DISP))
        assert leg1_before["provisional_eta_utc"] == "2026-08-02T14:00:00Z"
        assert leg2_before["provisional_eta_utc"] == "2026-08-02T19:00:00Z"

        # Leg 1 departs 30 minutes late (planned 10:00, actual 10:30).
        leg1 = depart_leg(chain["leg1"]["id"], at_utc="2026-08-02T10:30:00Z")
        assert leg1["status"] == "EN_ROUTE"
        assert leg1["actual_departure_utc"] == "2026-08-02T10:30:00Z"
        assert leg1["provisional_eta_utc"] == "2026-08-02T14:30:00Z", (
            "planned arrival 14:00 + 30 accrued delay minutes"
        )

    def test_leg2_provisional_eta_pushed_by_connect_shortfall(self, api):
        """PRD §3.6: "if the current leg's provisional ETA leaves at least the
        45-minute connect buffer before the next leg's planned departure, the
        next leg's projected arrival stays its own `planned_arrival_utc`;
        otherwise the next leg's projected arrival is pushed out by exactly the
        connect shortfall — that is, by the amount by which the current leg's
        provisional ETA plus 45 minutes exceeds the next leg's planned
        departure."

        Design: Difficulty/dual_variant_calc/relay_eta_planned_vs_provisional_divergence
        """
        chain = make_relay_chain()
        depart_leg(chain["leg1"]["id"], at_utc="2026-08-02T10:30:00Z")
        leg2 = get_success_data(api.get_linehaul_leg(chain["leg2"]["id"],
                                                     headers=DISP))
        # provisional ETA of leg 1 = 14:30; 14:30 + 45 min = 15:15 exceeds the
        # 15:00 planned departure by 15 minutes -> projection 19:00 + 15 min.
        assert leg2["provisional_eta_utc"] == "2026-08-02T19:15:00Z"
        assert leg2["planned_arrival_utc"] == "2026-08-02T19:00:00Z", (
            "the planned value is never rewritten by projection"
        )


class TestRelayConnectBuffer:
    def _sealed_trailer_with_leg1(self):
        t_origin = make_terminal(code="CHI", name="Chicago", dock_doors=12)
        t_relay = make_terminal(code="KCY", name="Kansas City", dock_doors=8)
        t_dest = make_terminal(code="DEN", name="Denver", dock_doors=8)
        ctx = make_sealed_trailer(
            t_origin["id"], t_dest["id"],
            shipment_overrides={"actual_weight_lbs": 26000, "length_in": 96,
                                "width_in": 96, "height_in": 96},
            door_number=33)
        leg1 = plan_leg(t_origin["id"], t_relay["id"], ctx["trailer"]["id"],
                        "2026-08-02T10:00:00Z", "2026-08-02T14:00:00Z",
                        relay_sequence=1)
        return t_relay, t_dest, ctx["trailer"], leg1

    def test_relay_connect_44_minutes_rejected(self, api):
        """PRD §3.6: "And for any leg with `relay_sequence` greater than 1, the
        planned departure must be no earlier than the previous leg's planned
        arrival plus a 45-minute connect buffer — the minimum connect time at a
        relay point. A tighter connection is rejected with
        `ERR_RELAY_CONNECT_INFEASIBLE` (HTTP 422); a departure exactly 45 minutes
        after the prior arrival is feasible."

        Design: Difficulty/resource_temporal_overlap/relay_connect_buffer_window_semantics
        """
        t_relay, t_dest, trailer, _ = self._sealed_trailer_with_leg1()
        resp = api.create_linehaul_leg(
            create_linehaul_leg_payload(
                t_relay["id"], t_dest["id"], trailer["id"],
                "2026-08-02T14:44:00Z", "2026-08-02T18:00:00Z",
                relay_sequence=2),
            headers=DISP,
        )
        validate_error(resp, ApiErrorId.ERR_RELAY_CONNECT_INFEASIBLE)

    def test_relay_connect_exactly_45_minutes_accepted(self, api):
        """PRD §3.6: "A tighter connection is rejected with
        `ERR_RELAY_CONNECT_INFEASIBLE` (HTTP 422); a departure exactly 45 minutes
        after the prior arrival is feasible."

        Design: Difficulty/resource_temporal_overlap/relay_connect_buffer_window_semantics
        """
        t_relay, t_dest, trailer, _ = self._sealed_trailer_with_leg1()
        leg2 = plan_leg(t_relay["id"], t_dest["id"], trailer["id"],
                        "2026-08-02T14:45:00Z", "2026-08-02T18:00:00Z",
                        relay_sequence=2)
        assert leg2["status"] == "PLANNED", (
            "a departure exactly 45 minutes after the prior arrival is feasible"
        )


class TestRelayDepartureSequencing:
    def test_leg2_depart_blocked_until_leg1_arrives(self, api):
        """PRD §3.6: "for a later leg, the previous leg for the same trailer (the
        one whose `relay_sequence` is one less) must already be `ARRIVED` —
        departing leg N while leg N−1 is anything other than `ARRIVED` is
        rejected with `ERR_RELAY_SEQUENCE_VIOLATION` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/leg_depart_gated_by_prior_relay_leg
        """
        chain = make_relay_chain()
        depart_leg(chain["leg1"]["id"], at_utc="2026-08-02T10:00:00Z")
        resp = api.depart_leg(chain["leg2"]["id"], headers=DISP)
        validate_error(resp, ApiErrorId.ERR_RELAY_SEQUENCE_VIOLATION)
        leg2 = get_success_data(api.get_linehaul_leg(chain["leg2"]["id"],
                                                     headers=DISP))
        assert leg2["status"] == "PLANNED"
        assert leg2.get("actual_departure_utc") is None

    def test_leg2_depart_succeeds_after_leg1_arrival(self, api):
        """PRD §3.6: "Departing a leg stamps `actual_departure_utc` from the
        logical clock and moves the leg `PLANNED` → `EN_ROUTE`."
        PRD §3.6: "for a later leg, the previous leg for the same trailer (the
        one whose `relay_sequence` is one less) must already be `ARRIVED`"

        Design: Difficulty/cross_entity_state_dependency/leg_depart_gated_by_prior_relay_leg
        """
        chain = make_relay_chain()
        depart_leg(chain["leg1"]["id"], at_utc="2026-08-02T10:00:00Z")
        arrive_leg(chain["leg1"]["id"], at_utc="2026-08-02T14:00:00Z")
        leg2 = depart_leg(chain["leg2"]["id"], at_utc="2026-08-02T15:00:00Z")
        assert leg2["status"] == "EN_ROUTE"
        assert leg2["actual_departure_utc"] == "2026-08-02T15:00:00Z"


class TestArrivalCascade:
    def test_final_leg_arrival_cascades_delivery(self, api):
        """PRD §3.6: "When the arriving leg's `destination_terminal_id` equals
        the trailer's `destination_terminal_id` — that is, it is the final leg
        of the relay chain — the arrival cascades: the trailer's posture moves
        `DISPATCHED` → `ARRIVED` (terminal), and every shipment with an `ACTIVE`
        manifest entry aboard moves `IN_LINEHAUL` → `DELIVERED`, each stamped
        with `delivered_at_utc` at the same instant."
        PRD §2.9: "Every timestamp the server stamps — tender instants,
        departures, arrivals, deliveries — is read from this logical clock."

        Design: Difficulty/transitive_cascade/leg_arrival_delivery_cascade_depth3
        """
        origin, dest = make_terminal_pair()
        ctx = make_sealed_trailer(origin["id"], dest["id"], door_number=25)
        leg = plan_leg(origin["id"], dest["id"], ctx["trailer"]["id"],
                       "2026-08-01T20:00:00Z", "2026-08-02T08:00:00Z",
                       relay_sequence=1)
        depart_leg(leg["id"], at_utc="2026-08-01T20:00:00Z")
        arrived = arrive_leg(leg["id"], at_utc="2026-08-02T08:00:00Z")

        assert arrived["status"] == "ARRIVED"
        assert arrived["actual_arrival_utc"] == "2026-08-02T08:00:00Z"
        trailer = get_trailer(ctx["trailer"]["id"])
        assert trailer["posture"] == "ARRIVED", (
            "the trailer flip is caused by the leg arrival"
        )
        shipment = get_success_data(api.get_shipment(ctx["shipment"]["id"],
                                                     headers=DISP))
        assert shipment["handling_status"] == "DELIVERED"
        assert shipment["delivered_at_utc"] == "2026-08-02T08:00:00Z", (
            "delivery is stamped at the same instant as the final arrival"
        )

    def test_intermediate_leg_arrival_does_not_deliver(self, api):
        """PRD §3.6: "An intermediate relay leg's arrival merely completes that
        leg, leaving the trailer `DISPATCHED` and the shipments `IN_LINEHAUL`
        for the next leg."

        Design: Difficulty/transitive_cascade/leg_arrival_delivery_cascade_depth3
        """
        chain = make_relay_chain()
        depart_leg(chain["leg1"]["id"], at_utc="2026-08-02T10:00:00Z")
        arrived = arrive_leg(chain["leg1"]["id"], at_utc="2026-08-02T14:00:00Z")
        assert arrived["status"] == "ARRIVED"
        # Leg 1 ends at the relay point, not the trailer's destination.
        trailer = get_trailer(chain["trailer"]["id"])
        assert trailer["posture"] == "DISPATCHED"
        shipment = get_success_data(api.get_shipment(chain["shipment"]["id"],
                                                     headers=DISP))
        assert shipment["handling_status"] == "IN_LINEHAUL"
        assert shipment.get("delivered_at_utc") is None


class TestLegWindow:
    def test_leg_window_must_be_strictly_after(self, api):
        """PRD §3.6: "The planned arrival must be strictly after the planned
        departure; equality is not enough, and a violation is
        `ERR_LEG_WINDOW_INVALID` (HTTP 422)."

        Design: Corner/validations/error_leg_window_invalid
        """
        origin, dest = make_terminal_pair()
        trailer = make_trailer(origin["id"], dest["id"], door_number=40)
        resp = api.create_linehaul_leg(
            create_linehaul_leg_payload(
                origin["id"], dest["id"], trailer["id"],
                "2026-08-02T10:00:00Z", "2026-08-02T10:00:00Z",
                relay_sequence=1),
            headers=DISP,
        )
        validate_error(resp, ApiErrorId.ERR_LEG_WINDOW_INVALID)
