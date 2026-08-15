"""Sweep verification loop, auto-close evaluation, standby fee variants
(PRD §3.3, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_incident_payload,
    create_sweep_payload,
    get_success_data,
    make_marshal_headers,
    validate_success,
)
from test_helpers.fixtures import (
    set_clock,
    setup_event_closed,
    setup_event_show_complete,
    setup_event_standby_confirmed,
    setup_event_submitted,
)


class TestProvisionalVsFinalStandbyFee:
    def _setup_closed_with_218_minutes(self, api, engines=1):
        """Standby confirmed 19:07:00, auto-closed 22:45:00 (218 elapsed min),
        scheduled window 20:00-23:00 (planned_hours 3)."""
        ctx, sweep, closed = None, None, None
        op_headers = None
        # Build through SHOW_COMPLETE with standby confirmed at 19:07.
        from test_helpers.fixtures import (
            add_lead_crew,
            add_secured_post,
            add_site_plan,
            approve_permit,
            checkout_product,
            confirm_standby,
            create_magazine_with_batch,
            create_operator,
            post_weather,
            go_decision,
        )
        from test_helpers import create_display_payload, create_expend_payload
        op, op_headers = create_operator()
        ev = get_success_data(api.create_display(create_display_payload(), op_headers))
        sp = add_site_plan(ev, op_headers)
        app = get_success_data(api.create_permit_application(
            ev["id"], {"site_plan_id": sp["id"], "standby_engines": engines}, op_headers
        ))
        approve_permit(app, marshal_headers=make_marshal_headers("fm_1"))
        set_clock("2026-09-01T19:07:00Z")
        confirm_standby(ev, engines_on_site=engines,
                        marshal_headers=make_marshal_headers("fm_2"))
        mag, batch = create_magazine_with_batch(op_headers)
        checkout_product(batch, ev, op_headers, 20)
        crew, crew_headers = add_lead_crew(op, op_headers)
        add_secured_post(ev, op_headers)
        validate_success(api.ready_display(ev["id"], op_headers))
        post_weather(ev, crew_headers)
        go_decision(get_success_data(api.get_display(ev["id"], op_headers)),
                    op_headers, "GO")
        get_success_data(api.create_movement(
            batch["id"], create_expend_payload(ev["id"], 20), op_headers
        ))
        set_clock("2026-09-01T22:30:00Z")
        validate_success(api.complete_show(ev["id"], op_headers))
        set_clock("2026-09-01T22:35:00Z")
        sweep = get_success_data(api.create_sweep(ev["id"], create_sweep_payload(),
                                                  crew_headers))
        set_clock("2026-09-01T22:45:00Z")
        validate_success(api.verify_sweep(sweep["id"], {"verdict": "VERIFIED"},
                                          make_marshal_headers("fm_2")))
        closed = get_success_data(api.get_display(ev["id"], op_headers))
        app = get_success_data(api.get_permit_application(app["id"], op_headers))
        return app, closed

    def test_provisional_fee_is_ceil_hour_estimate(self, api):
        """PRD §3.3: "`provisional_standby_fee_cents` is then the base standby
        fee of 25000 cents, plus 14500 cents for each planned hour, plus a
        30000-cent surcharge for each requested standby engine" — 3 planned
        hours and 1 engine give 25000 + 3×14500 + 30000 = 98500.

        Design: Difficulty/dual_variant_calc/standby_fee_provisional_vs_final_permit
        """
        app, closed = self._setup_closed_with_218_minutes(api, engines=1)
        assert app["provisional_standby_fee_cents"] == 98500

    def test_final_fee_minute_prorated_differs(self, api):
        """PRD §3.8: "the hours line item is those elapsed minutes multiplied
        by the 14500-cent hourly rate and divided by 60, rounded half-up to
        whole cents; and the total is the 25000-cent base fee plus that hours
        line plus the 30000-cent surcharge per standby engine" — 218 minutes
        yields 25000 + round_half_up(218×14500/60) + 30000 = 107683, and
        "the final fee will differ from `provisional_standby_fee_cents`".

        Design: Difficulty/dual_variant_calc/standby_fee_provisional_vs_final_permit
        """
        app, closed = self._setup_closed_with_218_minutes(api, engines=1)
        assert closed["status"] == "CLOSED"
        assert closed["final_standby_fee_cents"] == 107683
        assert closed["final_standby_fee_cents"] != app["provisional_standby_fee_cents"]


class TestStandbyFeeRoundingOrder:
    def _setup_closed_two_engines(self, api):
        """Window 20:00-22:30 (planned_hours 3), 2 engines, standby 19:07,
        closed 22:45 (218 min)."""
        from test_helpers.fixtures import (
            add_lead_crew,
            add_secured_post,
            add_site_plan,
            approve_permit,
            checkout_product,
            confirm_standby,
            create_magazine_with_batch,
            create_operator,
            post_weather,
            go_decision,
        )
        from test_helpers import create_display_payload, create_expend_payload
        op, op_headers = create_operator()
        ev = get_success_data(api.create_display(
            create_display_payload(scheduled_end_at="2026-09-01T22:30:00Z"),
            op_headers,
        ))
        sp = add_site_plan(ev, op_headers)
        app = get_success_data(api.create_permit_application(
            ev["id"], {"site_plan_id": sp["id"], "standby_engines": 2}, op_headers
        ))
        approve_permit(app, marshal_headers=make_marshal_headers("fm_1"))
        set_clock("2026-09-01T19:07:00Z")
        confirm_standby(ev, engines_on_site=2,
                        marshal_headers=make_marshal_headers("fm_2"))
        mag, batch = create_magazine_with_batch(op_headers)
        checkout_product(batch, ev, op_headers, 10)
        crew, crew_headers = add_lead_crew(op, op_headers)
        add_secured_post(ev, op_headers)
        validate_success(api.ready_display(ev["id"], op_headers))
        post_weather(ev, crew_headers)
        go_decision(get_success_data(api.get_display(ev["id"], op_headers)),
                    op_headers, "GO")
        get_success_data(api.create_movement(
            batch["id"], create_expend_payload(ev["id"], 10), op_headers
        ))
        set_clock("2026-09-01T22:15:00Z")
        validate_success(api.complete_show(ev["id"], op_headers))
        sweep = get_success_data(api.create_sweep(ev["id"], create_sweep_payload(),
                                                  crew_headers))
        set_clock("2026-09-01T22:45:00Z")
        validate_success(api.verify_sweep(sweep["id"], {"verdict": "VERIFIED"},
                                          make_marshal_headers("fm_2")))
        closed = get_success_data(api.get_display(ev["id"], op_headers))
        app = get_success_data(api.get_permit_application(app["id"], op_headers))
        return app, closed

    def test_provisional_fee_with_two_engines(self, api):
        """PRD §3.3: "`provisional_standby_fee_cents` is then the base standby
        fee of 25000 cents, plus 14500 cents for each planned hour, plus a
        30000-cent surcharge for each requested standby engine" — 3 planned
        hours and 2 engines give 25000 + 3×14500 + 2×30000 = 128500.

        Design: Difficulty/combinatorial_formula/standby_fee_line_item_rounding_order
        """
        app, closed = self._setup_closed_two_engines(api)
        assert app["provisional_standby_fee_cents"] == 128500

    def test_final_fee_line_item_rounding_order(self, api):
        """PRD §3.8: "Rounding elapsed time up to whole hours before
        multiplying is expressly forbidden — it produces a different, larger
        fee." With 218 elapsed minutes the pinned per-line order gives
        25000 + round_half_up(218×14500/60) + 2×30000 = 137683, not the
        forbidden ceil-hours 25000 + 4×14500 + 60000 = 148000.

        Design: Difficulty/combinatorial_formula/standby_fee_line_item_rounding_order
        """
        app, closed = self._setup_closed_two_engines(api)
        assert closed["status"] == "CLOSED"
        assert closed["final_standby_fee_cents"] == 137683
        assert closed["final_standby_fee_cents"] != 148000


class TestSweepVerifyLoop:
    def test_sweep_rejected_allows_resweep(self, api):
        """PRD §3.8: "A rejection leaves the event in `SHOW_COMPLETE` and
        permits a fresh sweep to be recorded — the re-sweep loop." and "A
        verification against a `PENDING` sweep ... drives the event
        `SHOW_COMPLETE → SWEEP_VERIFIED` ... and triggers the auto-close
        evaluation"; with no FILED incident and net checked-out zero, "the
        `SWEEP_VERIFIED` event may move to `CLOSED`".

        Design: Corner/state_machines/sweep_rejected_allows_resweep
        """
        ctx = setup_event_show_complete()
        sw1 = get_success_data(api.create_sweep(
            ctx["ev"]["id"],
            create_sweep_payload(area_clear=False, notes="debris"),
            ctx["crew_headers"],
        ))
        rej = api.verify_sweep(sw1["id"], {"verdict": "REJECTED", "note": "re-sweep at dawn"},
                               make_marshal_headers("fm_2"))
        assert validate_success(rej)["verdict"] == "REJECTED"
        mid = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert mid["status"] == "SHOW_COMPLETE"
        sw2 = get_success_data(api.create_sweep(
            ctx["ev"]["id"], create_sweep_payload(sweep_type="DAWN_RECHECK"),
            ctx["crew_headers"],
        ))
        validate_success(api.verify_sweep(sw2["id"], {"verdict": "VERIFIED"},
                                          make_marshal_headers("fm_2")))
        end = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert end["status"] == "CLOSED"


class TestAutoCloseBlockedByIncident:
    def test_verified_sweep_with_open_incident_stays_sweep_verified(self, api):
        """PRD §3.8: "the system evaluates whether the `SWEEP_VERIFIED` event
        may move to `CLOSED`: no incident report of the event may remain
        `FILED`" — with a FILED incident the event stays SWEEP_VERIFIED.

        Design: Corner/cross_cutting_layers/auto_close_blocked_by_open_incident
        """
        ctx = setup_event_show_complete()
        inc = get_success_data(api.create_incident(
            ctx["ev"]["id"], create_incident_payload(), ctx["crew_headers"]
        ))
        sweep = get_success_data(api.create_sweep(
            ctx["ev"]["id"], create_sweep_payload(), ctx["crew_headers"]
        ))
        validate_success(api.verify_sweep(sweep["id"], {"verdict": "VERIFIED"},
                                          make_marshal_headers("fm_2")))
        ev = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert ev["status"] == "SWEEP_VERIFIED"

    def test_incident_close_triggers_auto_close_and_final_fee(self, api):
        """PRD §3.8: "After every sweep verification, every incident closure,
        and every `RETURN` movement, the system evaluates whether the
        `SWEEP_VERIFIED` event may move to `CLOSED`" and "When both hold,
        `closed_at` is stamped and the final standby fee is computed and
        stored as `final_standby_fee_cents`." Here standby was confirmed at
        19:00 and the show closed at 22:30 (210 min): 25000 +
        round_half_up(210×14500/60) + 30000 = 105750.

        Design: Corner/cross_cutting_layers/auto_close_blocked_by_open_incident
        """
        # Build SHOW_COMPLETE with standby confirmed at 19:00 exactly.
        from test_helpers.fixtures import (
            add_lead_crew,
            add_secured_post,
            add_site_plan,
            approve_permit,
            checkout_product,
            confirm_standby,
            create_magazine_with_batch,
            create_operator,
            go_decision,
            post_weather,
        )
        from test_helpers import create_display_payload, create_expend_payload
        op, op_headers = create_operator()
        ev = get_success_data(api.create_display(create_display_payload(), op_headers))
        sp = add_site_plan(ev, op_headers)
        app = get_success_data(api.create_permit_application(
            ev["id"], {"site_plan_id": sp["id"], "standby_engines": 1}, op_headers
        ))
        approve_permit(app, marshal_headers=make_marshal_headers("fm_1"))
        set_clock("2026-09-01T19:00:00Z")
        confirm_standby(ev, engines_on_site=1,
                        marshal_headers=make_marshal_headers("fm_2"))
        mag, batch = create_magazine_with_batch(op_headers)
        checkout_product(batch, ev, op_headers, 20)
        crew, crew_headers = add_lead_crew(op, op_headers)
        add_secured_post(ev, op_headers)
        validate_success(api.ready_display(ev["id"], op_headers))
        post_weather(ev, crew_headers)
        go_decision(get_success_data(api.get_display(ev["id"], op_headers)),
                    op_headers, "GO")
        get_success_data(api.create_movement(
            batch["id"], create_expend_payload(ev["id"], 20), op_headers
        ))
        inc = get_success_data(api.create_incident(
            ev["id"], create_incident_payload(), crew_headers
        ))
        set_clock("2026-09-01T22:30:00Z")
        validate_success(api.complete_show(ev["id"], op_headers))
        sweep = get_success_data(api.create_sweep(ev["id"], create_sweep_payload(),
                                                  crew_headers))
        validate_success(api.verify_sweep(sweep["id"], {"verdict": "VERIFIED"},
                                          make_marshal_headers("fm_2")))
        held = get_success_data(api.get_display(ev["id"], op_headers))
        assert held["status"] == "SWEEP_VERIFIED"
        # Incident was filed by the crew member, so fm_2 closing satisfies SoD.
        validate_success(api.close_incident(
            inc["id"], {"resolution_note": "settled"}, make_marshal_headers("fm_2")
        ))
        closed = get_success_data(api.get_display(ev["id"], op_headers))
        assert closed["status"] == "CLOSED"
        assert closed["final_standby_fee_cents"] == 105750
