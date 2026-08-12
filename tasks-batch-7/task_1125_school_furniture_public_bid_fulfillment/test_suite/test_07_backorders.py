"""Backorder declaration, district ETA communication, posture gating, and the
OCC-guarded supersede-create flow (PRD §2.7, §3.5, §3.8)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, TWO_TIER_TABLE, make_district_buyer_headers,
    validate_error, validate_paginated, validate_success, add_accepted_po,
    add_po_line, build_accepted_award_context, create_po, create_shipment,
    declare_backorder, deliver_shipment, get_po, get_po_line, set_clock,
)

FC = TEST_USERS["fulfillment_coordinator_headers"]


def _coop_ctx(api, clock="2026-05-10T00:00:00Z"):
    return build_accepted_award_context(
        pricing_mode="COOP_TIERED", tier_table=TWO_TIER_TABLE, clock=clock)


def _notice_for_line(api, po_line_id):
    data, _meta = validate_paginated(
        api.list_backorder_notices(FC, params={"po_line_id": po_line_id}))
    return data[0]


class TestBackorderCascade:
    def test_backorder_declaration_cascades_notice_count_posture_gate(self, api):
        """PRD §3.8: "it is the head of a three-link cascade: a backorder notice is
        created in `OPEN` status with `revision_count` 0 and `current_eta_date` set
        to the declared `initial_eta_date`; the purchase order's
        `open_backorder_count` is incremented by one; and the order's `posture` is
        recomputed — when the count reaches two or more, the order flips `ON_TRACK`
        → `AT_RISK`"
        PRD §3.5: "while the order's `posture` is `AT_RISK`, shipment creation is
        rejected with `ERR_PO_AT_RISK_BLOCKS_SCHEDULING` unless the shipment's
        `kind` is `REPLACEMENT` or at least one of its lines is currently
        `BACKORDERED`"

        Design: Difficulty/transitive_cascade/backorder_declaration_cascades_notice_count_posture_gate
        """
        ctx = _coop_ctx(api)
        po, lines = add_accepted_po(ctx, line_qtys=(10, 8, 5))
        l1, l2, l3 = [l["id"] for l in lines]

        line1 = declare_backorder(l1, "2026-07-20")
        assert line1["status"] == "BACKORDERED"

        po_mid = get_po(po["id"])
        assert po_mid["open_backorder_count"] == 1
        assert po_mid["posture"] == "ON_TRACK"

        declare_backorder(l2, "2026-07-22")
        po_end = get_po(po["id"])
        assert po_end["open_backorder_count"] == 2
        assert po_end["posture"] == "AT_RISK"

        notice = _notice_for_line(api, l1)
        assert notice["status"] == "OPEN"
        assert notice["current_eta_date"] == "2026-07-20"
        assert notice["revision_count"] == 0

        blocked = api.create_shipment(
            {"purchase_order_id": po["id"], "school_site_id": ctx["site"]["id"],
             "scheduled_date": "2026-07-01", "lines": [{"po_line_id": l3, "qty": 5}]}, FC)
        validate_error(blocked, ApiErrorId.ERR_PO_AT_RISK_BLOCKS_SCHEDULING)

    def test_single_backorder_keeps_posture_on_track(self, api):
        """PRD §3.8: "when the count reaches two or more, the order flips
        `ON_TRACK` → `AT_RISK`"
        PRD §3.8: "a backorder notice is created in `OPEN` status with
        `revision_count` 0 and `current_eta_date` set to the declared
        `initial_eta_date`"

        Design: Difficulty/transitive_cascade/backorder_declaration_cascades_notice_count_posture_gate
        """
        ctx = _coop_ctx(api)
        po, lines = add_accepted_po(ctx, line_qtys=(10, 8))
        l1, l2 = [l["id"] for l in lines]

        declare_backorder(l1, "2026-07-20")
        po_now = get_po(po["id"])
        assert po_now["open_backorder_count"] == 1
        assert po_now["posture"] == "ON_TRACK"

        notice = _notice_for_line(api, l1)
        assert notice["status"] == "OPEN" and notice["revision_count"] == 0
        assert notice["current_eta_date"] == "2026-07-20"

        # Below threshold the posture gate does not engage: scheduling proceeds.
        shipment = validate_success(api.create_shipment(
            {"purchase_order_id": po["id"], "school_site_id": ctx["site"]["id"],
             "scheduled_date": "2026-07-01", "lines": [{"po_line_id": l2, "qty": 8}]}, FC), 201)
        assert shipment["status"] == "SCHEDULED"


class TestNoticeLifecycle:
    def test_backorder_update_eta_on_resolved_notice_rejected(self, api):
        """PRD §3.8: "Updating a notice that is already `SUPERSEDED` or `RESOLVED`
        is rejected with `ERR_BACKORDER_NOT_OPEN`."
        PRD §3.8: "when the linked line is fully delivered or is cancelled, its open
        notice — whether `OPEN` or `ETA_UPDATED` — moves to `RESOLVED`"

        Design: Corner/state_machines/backorder_update_eta_on_resolved_notice_rejected
        """
        ctx = _coop_ctx(api)
        po, lines = add_accepted_po(ctx, line_qtys=(10,))
        l1 = lines[0]["id"]
        declare_backorder(l1, "2026-07-20")
        notice = _notice_for_line(api, l1)

        shipment = create_shipment(po["id"], ctx["site"]["id"],
                                   [{"po_line_id": l1, "qty": 10}], scheduled_date="2026-07-01")
        deliver_shipment(shipment["id"], [{
            "po_line_id": l1, "delivered_qty": 10,
            "manufacturer": "Acme", "model": "Desk-100",
        }])
        resolved = validate_success(api.get_backorder_notice(notice["id"], FC))
        assert resolved["status"] == "RESOLVED"

        resp = api.update_eta(notice["id"], {"new_eta_date": "2026-08-01"}, FC)
        validate_error(resp, ApiErrorId.ERR_BACKORDER_NOT_OPEN)

    def test_declare_backorder_on_fully_delivered_line_rejected(self, api):
        """PRD §3.8: "An undelivered remainder must exist — `ordered_qty` exceeding
        `delivered_qty` — otherwise the declaration is `ERR_INVALID_STATE`"

        Design: Corner/endpoints/declare_backorder_on_fully_delivered_line_rejected
        """
        ctx = build_accepted_award_context()
        po, lines = add_accepted_po(ctx, line_qtys=(10,))
        l1 = lines[0]["id"]
        shipment = create_shipment(po["id"], ctx["site"]["id"],
                                   [{"po_line_id": l1, "qty": 10}], scheduled_date="2026-07-01")
        deliver_shipment(shipment["id"], [{
            "po_line_id": l1, "delivered_qty": 10,
            "manufacturer": "Acme", "model": "Desk-100",
        }])

        resp = api.declare_backorder(l1, {"initial_eta_date": "2026-07-20"}, FC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_eta_update_not_forward_returns_eta_not_forward(self, api):
        """PRD §3.8: "the revision is accepted only if it is strictly later than
        the notice's `current_eta_date` and strictly later than the clock's current
        date — anything else is `ERR_ETA_NOT_FORWARD`."
        PRD §3.8: "Each accepted update sets `current_eta_date` to the new date,
        increments `revision_count` by one, re-stamps `communicated_at` from the
        clock, and leaves the notice in `ETA_UPDATED`"

        Design: Corner/errors/eta_update_not_forward_returns_eta_not_forward
        """
        ctx = _coop_ctx(api)
        po, lines = add_accepted_po(ctx, line_qtys=(10,))
        l1 = lines[0]["id"]
        declare_backorder(l1, "2026-07-20")
        notice = _notice_for_line(api, l1)

        backwards = api.update_eta(notice["id"], {"new_eta_date": "2026-07-19"}, FC)
        validate_error(backwards, ApiErrorId.ERR_ETA_NOT_FORWARD)

        forward = validate_success(api.update_eta(
            notice["id"], {"new_eta_date": "2026-07-25"}, FC))
        assert forward["status"] == "ETA_UPDATED"
        assert forward["current_eta_date"] == "2026-07-25"
        assert forward["revision_count"] == 1


class TestPostureRecovery:
    def test_posture_recovers_when_backorders_resolved(self, api):
        """PRD §3.5: "Whenever a delivery completes a line that had an open
        backorder notice, the notice transitions to `RESOLVED`, the order's
        `open_backorder_count` is decremented, and `posture` is recomputed —
        dropping back to `ON_TRACK` once the count falls below two."
        PRD §3.5: "remediation shipments are exempt because they are how the order
        recovers."

        Design: Corner/calculations/posture_recovers_when_backorders_resolved
        """
        ctx = _coop_ctx(api)
        po, lines = add_accepted_po(ctx, line_qtys=(10, 8))
        l1, l2 = [l["id"] for l in lines]
        declare_backorder(l1, "2026-07-20")
        declare_backorder(l2, "2026-07-22")

        po_mid = get_po(po["id"])
        assert po_mid["open_backorder_count"] == 2
        assert po_mid["posture"] == "AT_RISK"

        # Remediation: the shipment carries BACKORDERED lines, so the gate exempts it.
        shipment = validate_success(api.create_shipment(
            {"purchase_order_id": po["id"], "school_site_id": ctx["site"]["id"],
             "scheduled_date": "2026-07-25",
             "lines": [{"po_line_id": l1, "qty": 10}, {"po_line_id": l2, "qty": 8}]}, FC), 201)
        deliver_shipment(shipment["id"], [
            {"po_line_id": l1, "delivered_qty": 10, "manufacturer": "Acme", "model": "Desk-100"},
            {"po_line_id": l2, "delivered_qty": 8, "manufacturer": "Acme", "model": "Desk-100"},
        ])

        po_end = get_po(po["id"])
        assert po_end["open_backorder_count"] == 0
        assert po_end["posture"] == "ON_TRACK"
        assert _notice_for_line(api, l1)["status"] == "RESOLVED"
        assert _notice_for_line(api, l2)["status"] == "RESOLVED"


class TestSupersedeCreateOCC:
    def test_occ_stale_version_on_backorder_supersede_returns_412(self, api):
        """PRD §2.7: "A revised backorder notice created against a PO line must
        carry `expected_po_line_version` holding the value of that line's `version`
        the client last observed. ... if the line's `version` no longer matches, the
        client would be superseding a notice it never saw; the create is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.8: "On success the prior `OPEN` or `ETA_UPDATED` notice becomes
        `SUPERSEDED`, a fresh notice opens with `revision_count` 0 and
        `current_eta_date` taken from the request, and the line's `version`
        increments."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_backorder_supersede_returns_412
        """
        ctx = _coop_ctx(api)
        po = create_po(ctx["award"]["id"], ctx["district"]["id"], po_number="PO-1")
        line = add_po_line(po["id"], ctx["spec_line"]["id"], ctx["district"]["id"], 10)
        stale_version = line["version"]
        accept_resp = api.accept_purchase_order(po["id"], FC)
        validate_success(accept_resp)
        declared = declare_backorder(line["id"], "2026-07-20")
        fresh_version = declared["version"]
        assert fresh_version != stale_version

        stale = api.create_backorder_notice(
            line["id"],
            {"initial_eta_date": "2026-07-25", "expected_po_line_version": stale_version},
            FC)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        created = validate_success(api.create_backorder_notice(
            line["id"],
            {"initial_eta_date": "2026-07-25", "expected_po_line_version": fresh_version},
            FC), 201)
        assert created["status"] == "OPEN"
        assert created["revision_count"] == 0
        assert created["current_eta_date"] == "2026-07-25"

        notices, _meta = validate_paginated(
            api.list_backorder_notices(FC, params={"po_line_id": line["id"]}))
        assert notices[0]["status"] == "SUPERSEDED"  # the original notice, created first
