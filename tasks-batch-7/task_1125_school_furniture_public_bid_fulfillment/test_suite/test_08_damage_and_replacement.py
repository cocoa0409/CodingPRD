"""Damage reporting, replacement deadlines, and the approve-replacement cascade
(PRD §3.7)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, assert_crew_booking_invariant, validate_error,
    validate_paginated, validate_success, add_accepted_po,
    build_accepted_award_context, create_shipment, deliver_shipment,
    file_damage_report, get_crew, set_clock,
)

FC = TEST_USERS["fulfillment_coordinator_headers"]
CM = TEST_USERS["contract_manager_headers"]


def _delivered_ctx(api, ordered_qty=10, clock_after="2026-07-20T09:00:00Z"):
    """Accepted award + PO line fully delivered 2026-07-01; clock advanced."""
    ctx = build_accepted_award_context()
    po, lines = add_accepted_po(ctx, line_qtys=(ordered_qty,))
    shipment = create_shipment(
        po["id"], ctx["site"]["id"],
        [{"po_line_id": lines[0]["id"], "qty": ordered_qty}],
        scheduled_date="2026-07-01")
    deliver_shipment(shipment["id"], [{
        "po_line_id": lines[0]["id"], "delivered_qty": ordered_qty,
        "manufacturer": "Acme", "model": "Desk-100",
    }])
    if clock_after is not None:
        set_clock(clock_after)
    return ctx, po, lines, shipment


class TestReplacementCascade:
    def test_damage_approval_cascades_shipment_installtask_crew_ledger(self, api):
        """PRD §3.7: "its `replacement_deadline` is computed as the earlier of two
        candidate dates — the bid specification's `delivery_window_end` plus
        fourteen days, and the `reported_date` plus twenty-one days."
        PRD §3.7: "Approval cascades through three linked creations. First, a
        replacement shipment is created with `kind` `REPLACEMENT` ... Second, that
        shipment creation itself spawns a `SCHEDULED` install task ... Third, the
        new task debits that crew's `booked_days` by its computed `crew_days`,
        keeping the ledger synchronized."

        Design: Difficulty/transitive_cascade/damage_approval_cascades_shipment_installtask_crew_ledger
        """
        ctx, _po, lines, shipment = _delivered_ctx(api)
        crew_id = ctx["crew"]["id"]
        report = file_damage_report(lines[0]["id"], 2, crew_id, shipment_id=shipment["id"])
        assert report["reported_date"] == "2026-07-20"
        assert report["replacement_deadline"] == "2026-08-10"  # min(08-15+14d, 07-20+21d)
        assert get_crew(crew_id)["booked_days"] == 0

        approved = validate_success(api.approve_replacement(report["id"], {
            "scheduled_date": "2026-08-01", "crew_id": crew_id,
            "start_date": "2026-08-03", "end_date": "2026-08-05",
            "crew_count": 2, "room_label": "W-12",
        }, CM))
        assert approved["status"] == "REPLACEMENT_ORDERED"

        shipments, _m = validate_paginated(
            api.list_shipments(CM, params={"damage_report_id": report["id"]}))
        repl = shipments[0]
        assert repl["kind"] == "REPLACEMENT" and repl["status"] == "SCHEDULED"

        tasks, _m2 = validate_paginated(
            api.list_install_tasks(CM, params={"shipment_id": repl["id"]}))
        assert tasks[0]["status"] == "SCHEDULED"
        assert tasks[0]["crew_days"] == 4  # 2 crew x 2 dates in [2026-08-03, 2026-08-05)

        assert_crew_booking_invariant(get_crew(crew_id), 4)

    def test_replacement_shipment_links_report_and_qty(self, api):
        """PRD §3.7: "a replacement shipment is created with `kind` `REPLACEMENT`,
        its `damage_report_id` pointing back to the report, status `SCHEDULED`, the
        approved `scheduled_date`, a destination site taken from the report's
        shipment or from the shipment behind the report's install task, and a
        single shipment line pairing the report's `po_line_id` with a quantity
        equal to `damaged_qty`."

        Design: Difficulty/transitive_cascade/damage_approval_cascades_shipment_installtask_crew_ledger
        """
        ctx, _po, lines, shipment = _delivered_ctx(api)
        crew_id = ctx["crew"]["id"]
        report = file_damage_report(lines[0]["id"], 2, crew_id, shipment_id=shipment["id"])

        approved = validate_success(api.approve_replacement(report["id"], {
            "scheduled_date": "2026-08-01", "crew_id": crew_id,
            "start_date": "2026-08-03", "end_date": "2026-08-05",
            "crew_count": 2, "room_label": "W-12",
        }, CM))
        assert approved["status"] == "REPLACEMENT_ORDERED"

        shipments, _m = validate_paginated(
            api.list_shipments(CM, params={"damage_report_id": report["id"]}))
        repl = shipments[0]
        assert repl["damage_report_id"] == report["id"]
        assert repl["scheduled_date"] == "2026-08-01"
        assert repl["school_site_id"] == ctx["site"]["id"]
        assert len(repl["lines"]) == 1
        assert repl["lines"][0]["po_line_id"] == lines[0]["id"]
        assert repl["lines"][0]["qty"] == 2


class TestDamageGuards:
    def test_damage_over_delivered_returns_damage_exceeds_delivered(self, api):
        """PRD §3.7: "the `damaged_qty` — at least 1 and no more than the line's
        `delivered_qty`, with excess rejected as `ERR_DAMAGE_EXCEEDS_DELIVERED`"

        Design: Corner/errors/damage_over_delivered_returns_damage_exceeds_delivered
        """
        from test_helpers import make_crew_lead_headers
        ctx, _po, lines, shipment = _delivered_ctx(api)
        resp = api.create_damage_report(
            {"po_line_id": lines[0]["id"], "damaged_qty": 11,
             "discovered_during": "DELIVERY", "fault_type": "TRANSIT",
             "shipment_id": shipment["id"]},
            make_crew_lead_headers(ctx["crew"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DAMAGE_EXCEEDS_DELIVERED)

    def test_replacement_scheduled_past_deadline_returns_window_missed(self, api):
        """PRD §3.7: "the manager approves a replacement, moving the report to
        `REPLACEMENT_ORDERED` — but only if the proposed `scheduled_date` falls on
        or before the report's `replacement_deadline`, inclusive; a later date is
        rejected with `ERR_REPLACEMENT_WINDOW_MISSED`."

        Design: Corner/errors/replacement_scheduled_past_deadline_returns_window_missed
        """
        ctx, _po, lines, shipment = _delivered_ctx(api)
        crew_id = ctx["crew"]["id"]
        report = file_damage_report(lines[0]["id"], 2, crew_id, shipment_id=shipment["id"])
        assert report["replacement_deadline"] == "2026-08-10"

        resp = api.approve_replacement(report["id"], {
            "scheduled_date": "2026-08-12", "crew_id": crew_id,
            "start_date": "2026-08-13", "end_date": "2026-08-14",
            "crew_count": 1, "room_label": "W-12",
        }, CM)
        validate_error(resp, ApiErrorId.ERR_REPLACEMENT_WINDOW_MISSED)


class TestReplacementDeadlineBranches:
    def test_replacement_deadline_min_selects_window_buffer_branch(self, api):
        """PRD §3.7: "its `replacement_deadline` is computed as the earlier of two
        candidate dates — the bid specification's `delivery_window_end` plus
        fourteen days, and the `reported_date` plus twenty-one days."
        PRD §2.5: "Filing dates such as a damage report's `reported_date` ... are
        stamped from this clock's calendar date"

        Design: Corner/calculations/replacement_deadline_min_selects_window_buffer_branch
        """
        # Filed 2026-08-10: candidates 2026-08-29 (window+buffer) vs 2026-08-31
        # (reported+21d); the window+buffer branch binds.
        ctx, _po, lines, shipment = _delivered_ctx(api, clock_after="2026-08-10T09:00:00Z")
        report = file_damage_report(lines[0]["id"], 2, ctx["crew"]["id"],
                                    shipment_id=shipment["id"])
        assert report["reported_date"] == "2026-08-10"
        assert report["replacement_deadline"] == "2026-08-29"
