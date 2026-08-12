"""Event posture cycle, contingency alerts, restriction cascades, and the
full event-cancellation cascade."""
from test_helpers import (
    TEST_USERS,
    api_client,
    ApiErrorId,
    ticket_line,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_EARLY_BIRD, CLOCK_MID_EVENT
from test_helpers.fixtures import (
    add_signed_agreement,
    confirm_program_slot,
    create_event,
    create_program_slot,
    create_site_area,
    create_ticket_order,
    get_event,
    issue_parking_pass,
    open_gates,
    open_registration,
    pay_ticket_order,
    publish_event,
    raise_alert,
    set_clock,
    setup_open_event,
    setup_published_event,
)
from test_helpers.test_users import make_safety_officer_headers

ORG = TEST_USERS["organizer_headers"]
SO1 = TEST_USERS["safety_officer_headers"]


class TestRestrictionCycle:
    def test_event_restriction_cycle(self, api):
        """PRD §2.6: "The loop between `EVENT_OPEN` and `RESTRICTED` is cyclic and
        may be traversed repeatedly as conditions change."
        PRD §3.9: "The same transition and the same open-flame cascade are
        available manually: the organizer or a safety officer may restrict the
        event from `EVENT_OPEN`, with an optional `reason`."

        Design: Difficulty/non_linear_state_machine/event_restriction_cycle
        """
        event = setup_open_event()
        assert event["event_posture"] == "EVENT_OPEN"

        restricted = validate_success(
            api_client.restrict_event(
                event["id"], make_safety_officer_headers("so-1"),
                {"reason": "wind-driven grass fire nearby"},
            ), 200
        )
        assert restricted["event_posture"] == "RESTRICTED"

        lifted = validate_success(
            api_client.lift_restriction(event["id"], make_safety_officer_headers("so-1")), 200
        )
        assert lifted["event_posture"] == "EVENT_OPEN", "cycle returns to EVENT_OPEN"

    def test_event_restriction_cycle_repeated(self, api):
        """PRD §2.6: "The loop between `EVENT_OPEN` and `RESTRICTED` is cyclic and
        may be traversed repeatedly as conditions change."

        Design: Difficulty/non_linear_state_machine/event_restriction_cycle
        """
        event = setup_open_event()
        for _ in range(2):
            restricted = validate_success(api_client.restrict_event(event["id"], ORG), 200)
            assert restricted["event_posture"] == "RESTRICTED"
            lifted = validate_success(api_client.lift_restriction(event["id"], ORG), 200)
            assert lifted["event_posture"] == "EVENT_OPEN"
        reread = get_event(event["id"])
        assert reread["event_posture"] == "EVENT_OPEN"


class TestRedFlagGuards:
    def test_lift_restriction_blocked_while_red_flag_open(self, api):
        """PRD §3.9: "Restriction is lifted — `RESTRICTED → EVENT_OPEN` — by the
        organizer or a safety officer only when no `OPEN` `RED_FLAG` alert remains
        on the event; otherwise the attempt fails with `ERR_RED_ALERTS_OPEN`."
        PRD §3.9: "When the recomputed level is `RED` while the event stands in
        `EVENT_OPEN`, the system itself moves the event `EVENT_OPEN → RESTRICTED`"

        Design: Corner/state_machines/lift_restriction_blocked_while_red_flag_open
        """
        event = setup_open_event()
        alert = raise_alert(event["id"], severity="RED_FLAG", alert_kind="FIRE",
                            message="red flag warning issued")
        after_raise = get_event(event["id"])
        assert after_raise["event_posture"] == "RESTRICTED", "RED alert auto-restricts"
        assert after_raise["restriction_level"] == "RED"

        blocked = api_client.lift_restriction(event["id"], SO1)
        validate_error(blocked, ApiErrorId.ERR_RED_ALERTS_OPEN, 409)

        resolved = validate_success(api_client.resolve_contingency_alert(alert["id"], SO1), 200)
        assert resolved["status"] == "RESOLVED"
        after_resolve = get_event(event["id"])
        assert after_resolve["restriction_level"] == "GREEN", (
            "level recomputes to GREEN once no OPEN alerts remain"
        )
        lifted = validate_success(api_client.lift_restriction(event["id"], SO1), 200)
        assert lifted["event_posture"] == "EVENT_OPEN"

    def test_red_flag_alert_auto_restricts_and_cancels_flame_slots(self, api):
        """PRD §3.9: "When the recomputed level is `RED` while the event stands in
        `EVENT_OPEN`, the system itself moves the event `EVENT_OPEN → RESTRICTED`,
        and every program slot of the event with `open_flame` true in `PROPOSED`
        or `CONFIRMED` is cancelled with `cancel_reason` `CONTINGENCY`."

        Design: Corner/state_machines/red_flag_alert_auto_restricts_and_cancels_flame_slots
        """
        event = setup_published_event()
        area = create_site_area(event["id"], area_kind="DEMO", capacity_units=4)
        flame = create_program_slot(
            event["id"], area["id"], title="Artillery demonstration",
            starts_at="2026-07-11T10:00:00Z", ends_at="2026-07-11T11:00:00Z",
            open_flame=True, required_combatants=0,
        )
        noflame = create_program_slot(
            event["id"], area["id"], title="Loom demonstration",
            starts_at="2026-07-11T14:00:00Z", ends_at="2026-07-11T15:00:00Z",
            open_flame=False, required_combatants=0,
        )
        confirm_program_slot(flame["id"])
        confirm_program_slot(noflame["id"])
        open_gates(event["id"])

        raise_alert(event["id"], severity="RED_FLAG", alert_kind="FIRE", message="red flag warning")

        after = get_event(event["id"])
        assert after["event_posture"] == "RESTRICTED"
        assert after["restriction_level"] == "RED"
        slots = validate_success(api_client.list_event_program_slots(event["id"], ORG), 200)
        by_id = {s["id"]: s for s in slots}
        assert by_id[flame["id"]]["status"] == "CANCELLED"
        assert by_id[flame["id"]]["cancel_reason"] == "CONTINGENCY"
        assert by_id[noflame["id"]]["status"] == "CONFIRMED", (
            "the no-flame slot is not touched by the restriction cascade"
        )

    def test_flame_slot_confirm_blocked_at_yellow_watch(self, api):
        """PRD §3.6: "when `open_flame` is true, the event's `restriction_level`
        must be `GREEN` — confirming flame under `YELLOW` or `RED` is rejected
        with `ERR_OPEN_FLAME_RESTRICTED`".
        PRD §2.6: "the level is `RED` when any open alert has severity `RED_FLAG`,
        otherwise `YELLOW` when any open alert has severity `WATCH`, otherwise
        `GREEN`."

        Design: Corner/state_machines/flame_slot_confirm_blocked_at_yellow_watch
        """
        event = setup_published_event()
        area = create_site_area(event["id"], area_kind="DEMO", capacity_units=4)
        slot = create_program_slot(
            event["id"], area["id"], open_flame=True, required_combatants=0,
        )
        open_gates(event["id"])
        raise_alert(event["id"], severity="WATCH", alert_kind="WEATHER", message="high wind watch")

        resp = api_client.confirm_program_slot(slot["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_OPEN_FLAME_RESTRICTED, 409)
        after = get_event(event["id"])
        assert after["event_posture"] == "EVENT_OPEN", "a WATCH alert never restricts posture"
        assert after["restriction_level"] == "YELLOW"

    def test_resolve_already_resolved_alert_rejected(self, api):
        """PRD §3.9: "Resolving an alert is a safety-officer action valid only from
        `OPEN` (`ERR_INVALID_ALERT_STATUS`)"

        Design: Corner/state_machines/resolve_already_resolved_alert_rejected
        """
        event = setup_published_event()
        alert = raise_alert(event["id"], severity="WATCH", alert_kind="WEATHER", message="storm watch")
        first = validate_success(api_client.resolve_contingency_alert(alert["id"], SO1), 200)
        assert first["status"] == "RESOLVED"
        resp = api_client.resolve_contingency_alert(alert["id"], SO1)
        validate_error(resp, ApiErrorId.ERR_INVALID_ALERT_STATUS, 409)
        listing = validate_success(api_client.list_contingency_alerts(event["id"], ORG), 200)
        assert listing[0]["status"] == "RESOLVED", "rejected re-resolve must not change status"


class TestEventCancellationCascade:
    def _setup_paid_order_with_pass(self):
        """Published event, PARKING lot, one PAID order holding one STANDARD pass."""
        event = create_event()
        lot = create_site_area(event["id"], area_kind="PARKING", capacity_units=10, area_name="Lot B")
        add_signed_agreement(event["id"], "LANDOWNER_USE")
        add_signed_agreement(event["id"], "INSURANCE_LIABILITY")
        open_registration(event["id"])
        publish_event(event["id"])
        set_clock(CLOCK_EARLY_BIRD)
        order = create_ticket_order(event["id"], buyer="spec-1")
        paid = pay_ticket_order(order["id"], buyer="spec-1")
        assert paid["final_total_cents"] == 8508
        parking = issue_parking_pass(
            paid["id"], buyer="spec-1", vehicle_plate="OH-1234",
            vehicle_class="STANDARD", site_area_id=lot["id"],
        )
        assert parking["status"] == "ACTIVE"
        lot_after = validate_success(api_client.get_site_area(lot["id"], ORG), 200)
        assert lot_after["allocated_units"] == 1
        return event, lot, paid, parking

    def test_event_cancel_refund_then_void_cascade(self, api):
        """PRD §3.9: "First the event's own transition lands; then every ticket
        order in `PAID` is refunded under the `EVENT_CONTINGENCY` variant —
        nothing retained, pro-rated by unused days measured to `cancelled_at` —
        while every order in `RESERVED` is simply cancelled; then every `ACTIVE`
        parking pass of a refunded order is voided, decrementing its lot's
        `allocated_units` by its `units_used`."
        PRD §3.7: "total days is the difference between the calendar dates of
        `event_ends_at` and `event_starts_at` plus one; elapsed days is the
        difference between the calendar dates of `cancelled_at` and
        `event_starts_at`, clamped so it never falls below zero and never exceeds
        total days; the refund is `final_total_cents` multiplied by the ratio of
        remaining days (total minus elapsed) to total days, rounded half-up."

        Design: Difficulty/transitive_cascade/event_cancel_refund_then_void_cascade
        """
        event, lot, paid, parking = self._setup_paid_order_with_pass()
        set_clock(CLOCK_MID_EVENT)  # 2026-07-11: one of three event days elapsed

        cancelled = validate_success(
            api_client.cancel_event(event["id"], ORG, {"reason": "wildfire evacuation order"}), 200
        )
        assert cancelled["event_posture"] == "CANCELLED"
        assert cancelled["cancelled_at"] is not None

        order = validate_success(api_client.get_ticket_order(paid["id"], ORG), 200)
        assert order["status"] == "REFUNDED", "hop 1: PAID order refunded by the cascade"
        assert order["refund_reason"] == "EVENT_CONTINGENCY"
        assert order["final_total_cents"] == 8508
        assert order["retained_fee_cents"] == 0, "nothing retained under EVENT_CONTINGENCY"
        assert order["refund_amount_cents"] == 5672, (
            "round_half_up(8508 * (3 - 1) / 3) pro-rated by unused days"
        )

        passes = validate_success(
            api_client.list_order_parking_passes(paid["id"], ORG), 200
        )
        assert passes[0]["id"] == parking["id"]
        assert passes[0]["status"] == "VOIDED", "hop 2: refunded order's pass is voided"
        lot = validate_success(api_client.get_site_area(lot["id"], ORG), 200)
        assert lot["allocated_units"] == 0, "voided pass decrements the lot"

    def test_event_cancel_cancels_reserved_order_and_slots(self, api):
        """PRD §3.9: "while every order in `RESERVED` is simply cancelled"
        PRD §3.9: "In the same sweep, every `PROPOSED` or `CONFIRMED` program slot
        is cancelled with `cancel_reason` `EVENT_CANCELLED`"

        Design: Difficulty/transitive_cascade/event_cancel_refund_then_void_cascade
        """
        event = setup_published_event()
        area = create_site_area(event["id"], area_kind="DEMO", capacity_units=4)
        slot = create_program_slot(event["id"], area["id"], open_flame=False,
                                   required_combatants=0)
        order = create_ticket_order(
            event["id"], buyer="spec-1",
            lines=[ticket_line("ADULT_DAY", 1)],
        )
        assert order["status"] == "RESERVED"

        cancelled = validate_success(api_client.cancel_event(event["id"], ORG), 200)
        assert cancelled["event_posture"] == "CANCELLED"

        reread_order = validate_success(api_client.get_ticket_order(order["id"], ORG), 200)
        assert reread_order["status"] == "CANCELLED", "RESERVED orders are cancelled, not refunded"
        assert reread_order["refund_amount_cents"] is None
        slots = validate_success(api_client.list_event_program_slots(event["id"], ORG), 200)
        assert slots[0]["status"] == "CANCELLED"
        assert slots[0]["cancel_reason"] == "EVENT_CANCELLED"
