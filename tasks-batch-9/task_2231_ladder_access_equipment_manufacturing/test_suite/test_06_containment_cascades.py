"""Transitive containment: the quarantine chain, the restoring chain, and the
independence of the two product dimensions."""

from test_helpers import (
    api_client,
    assert_instant_equals,
    assert_lot_units_conserved,
    create_campaign,
    get_bench_data,
    get_campaign_data,
    get_incident_data,
    get_listing_record_data,
    get_product_data,
    get_registration_data,
    get_reservation_data,
    quarantine_payload,
    reserve_bench,
    set_clock,
    setup_open_capa,
    setup_released_lot,
    setup_retail_released_product,
    setup_shipping_product_with_registered_units,
    stop_ship_payload,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
APPROVER = TEST_USERS["design_approver_headers"]


class TestLotQuarantineFiveHopCascade:
    def _shipping_model_with_planned_lab_work(self):
        """A shipping model with two registrations, plus one `PLANNED` campaign
        holding 120 further bench minutes on top of the 480 already consumed."""
        ctx = setup_shipping_product_with_registered_units(
            registration_count=2, produced_units=400
        )
        planned = create_campaign(
            ctx["product"]["id"], ctx["revision"]["id"], "INCIDENT_INVESTIGATION"
        )
        held = reserve_bench(
            ctx["bench"]["id"], planned["id"], duration_minutes=120
        )
        assert get_bench_data(ctx["bench"]["id"])["reserved_minutes_total"] == 600
        ctx.update({"planned_campaign": planned, "held_reservation": held})
        return ctx

    def test_quarantine_flags_registrations_and_stops_shipment(self):
        """PRD §3.6: "**Hop one:** every consumer registration whose
        `production_lot_id` is this lot and whose `registration_status` is
        `REGISTERED` or `NOTIFIED` has `hold_flag` set to true."
        PRD §3.6: "when that count becomes greater than 0 while the model's
        `market_status` is `RETAIL_RELEASED`, the model moves `RETAIL_RELEASED` →
        `STOP_SHIP` with `stop_ship_reason_code` set to `LOT_QUARANTINE`."

        Design: Difficulty/transitive_cascade/lot_quarantine_five_hop_cascade
        """
        ctx = self._shipping_model_with_planned_lab_work()

        quarantined = validate_success(
            api_client.quarantine_production_lot(
                ctx["lot"]["id"], quarantine_payload("JOINT_INTEGRITY"), SUPERVISOR
            )
        )

        assert quarantined["status"] == "QUARANTINED"
        assert quarantined["quarantine_reason_code"] == "JOINT_INTEGRITY"
        assert quarantined["units_quarantined"] == 400
        assert quarantined["units_released"] == 0
        assert quarantined["units_wip"] == 0
        assert quarantined["units_scrapped"] == 0
        assert_lot_units_conserved(quarantined)

        for registration in ctx["registrations"]:
            assert get_registration_data(registration["id"])["hold_flag"] is True

        product = get_product_data(ctx["product"]["id"])
        assert product["held_registration_count"] == 2
        assert product["market_status"] == "STOP_SHIP"
        assert product["stop_ship_reason_code"] == "LOT_QUARANTINE"

    def test_quarantine_suspends_the_models_listing_record(self):
        """PRD §3.6: "**Hop three,** caused by hop two: because the model entered
        `STOP_SHIP`, every listing record of the model in `LISTED` moves `LISTED`
        → `SUSPENDED` with `suspension_reason` set to `STOP_SHIP_CASCADE` and
        `audit_due_at` cleared to null."

        Design: Difficulty/transitive_cascade/lot_quarantine_five_hop_cascade
        """
        ctx = self._shipping_model_with_planned_lab_work()
        validate_success(
            api_client.quarantine_production_lot(
                ctx["lot"]["id"], quarantine_payload("JOINT_INTEGRITY"), SUPERVISOR
            )
        )

        record = get_listing_record_data(ctx["listing_record"]["id"])
        assert record["status"] == "SUSPENDED"
        assert record["suspension_reason"] == "STOP_SHIP_CASCADE"
        assert record["audit_due_at"] is None
        assert_instant_equals(
            record["suspended_at"], "2026-08-01T00:00:00Z", "suspended_at"
        )

    def test_quarantine_cancels_planned_lab_work_and_releases_its_bench_minutes(self):
        """PRD §3.6: "**Hop four,** also caused by hop two: every test campaign of
        the model still in `PLANNED` moves `PLANNED` → `CANCELLED`, whether or not
        it names a `listing_record_id`. **Hop five,** caused by hop four: each
        cancelled campaign's reservations still in `HELD` move `HELD` →
        `CANCELLED`, and each one's `duration_minutes` is subtracted from its
        bench's `reserved_minutes_total`."

        Design: Difficulty/transitive_cascade/lot_quarantine_five_hop_cascade
        """
        ctx = self._shipping_model_with_planned_lab_work()
        validate_success(
            api_client.quarantine_production_lot(
                ctx["lot"]["id"], quarantine_payload("JOINT_INTEGRITY"), SUPERVISOR
            )
        )

        assert get_campaign_data(ctx["planned_campaign"]["id"])["status"] == "CANCELLED"
        assert get_reservation_data(ctx["held_reservation"]["id"])["status"] == "CANCELLED"
        assert get_bench_data(ctx["bench"]["id"])["reserved_minutes_total"] == 480

        _, meta = validate_paginated(
            api_client.list_bench_reservations(
                TECHNICIAN,
                {"test_bench_id": ctx["bench"]["id"], "status": "CONSUMED"},
            )
        )
        assert meta["total_count"] == 2, (
            "a consumed reservation is never cancelled by the cascade"
        )


class TestCapaVerificationFourHopCascade:
    def _stopped_model_with_open_capa(self):
        """A stopped shipping model whose single hospitalisation incident is
        `CAPA_OPENED`, with the clock advanced to 2026-09-10."""
        ctx, lot = setup_released_lot(produced_units=400)
        validate_success(
            api_client.stop_ship(
                ctx["product"]["id"],
                stop_ship_payload("FIELD_INCIDENT_REVIEW"),
                OFFICER,
            )
        )
        set_clock("2026-09-10T00:00:00Z")
        incident, action = setup_open_capa(
            ctx["product"]["id"],
            incident_type="RAIL_FRACTURE",
            injury_severity="HOSPITALIZATION",
        )
        assert float(incident["incident_points"]) == 36.00
        product = get_product_data(ctx["product"]["id"])
        assert float(product["risk_score_gross"]) == 36.00
        assert float(product["risk_score_mitigated"]) == 36.00
        ctx.update({"lot": lot, "incident": incident, "action": action})
        return ctx

    def test_verification_closes_the_incident_it_covers(self):
        """PRD §3.8: "**Hop one:** the action moves `OPEN` → `VERIFIED`,
        `verified_at` is stamped with the logical clock, and `verified_by_user_id`
        records the verifier's `X-User-ID`. **Hop two,** caused by hop one:
        because the action is now verified, its field incident moves
        `CAPA_OPENED` → `CLOSED` and the incident's `closed_at` is stamped with
        the logical clock; this is the join point of the investigation fork, at
        which both branches have reached a terminal status."

        Design: Difficulty/transitive_cascade/capa_verification_four_hop_cascade
        """
        ctx = self._stopped_model_with_open_capa()

        verified = validate_success(
            api_client.verify_corrective_action(ctx["action"]["id"], APPROVER)
        )

        assert verified["status"] == "VERIFIED"
        assert_instant_equals(
            verified["verified_at"], "2026-09-10T00:00:00Z", "verified_at"
        )
        assert verified["verified_by_user_id"] == "appr-1"

        incident = get_incident_data(ctx["incident"]["id"])
        assert incident["status"] == "CLOSED"
        assert_instant_equals(
            incident["closed_at"], "2026-09-10T00:00:00Z", "closed_at"
        )

    def test_verification_discounts_the_mitigated_score_and_re_anchors_retention(self):
        """PRD §3.8: "**Hop three,** caused by hop two: because the incident
        closed, the model's `risk_score_mitigated` is recomputed with the
        one-quarter credit now applying to that incident, and
        `dhf_retention_until` with `retention_anchor_source` is re-derived from
        the new `closed_at`, taking `INCIDENT_CLOSURE` as the source when that
        instant is the latest candidate."
        PRD §2.4: "date arithmetic that adds years (design-history retention) is
        calendar-based, landing on the same month and day of the target year, with
        29 February mapping to 1 March."

        Design: Difficulty/transitive_cascade/capa_verification_four_hop_cascade
        """
        ctx = self._stopped_model_with_open_capa()
        validate_success(
            api_client.verify_corrective_action(ctx["action"]["id"], APPROVER)
        )

        product = get_product_data(ctx["product"]["id"])
        assert float(product["risk_score_gross"]) == 36.00, (
            "the gross variant never takes the corrective-action credit"
        )
        assert float(product["risk_score_mitigated"]) == 9.00
        assert_instant_equals(
            product["dhf_retention_until"],
            "2033-09-10T00:00:00Z",
            "dhf_retention_until",
        )
        assert product["retention_anchor_source"] == "INCIDENT_CLOSURE"

    def test_verification_resumes_shipment_and_restores_the_listing(self):
        """PRD §3.8: "**Hop four,** caused by hop three: if the recomputed
        `risk_score_mitigated` has dropped below 25.00 and the model is in
        `STOP_SHIP` with no lot in `QUARANTINED` and a `held_registration_count`
        of 0, the model moves `STOP_SHIP` → `RETAIL_RELEASED`, which in turn
        returns every `SUSPENDED` listing record of the model to `LISTED` with
        `audit_due_at` re-stamped as described in §3.7."

        Design: Difficulty/transitive_cascade/capa_verification_four_hop_cascade
        """
        ctx = self._stopped_model_with_open_capa()
        validate_success(
            api_client.verify_corrective_action(ctx["action"]["id"], APPROVER)
        )

        product = get_product_data(ctx["product"]["id"])
        assert product["market_status"] == "RETAIL_RELEASED"
        assert product["stop_ship_reason_code"] is None

        record = get_listing_record_data(ctx["listing_record"]["id"])
        assert record["status"] == "LISTED"
        assert record["suspension_reason"] is None
        assert record["suspended_at"] is None
        # 2026-09-10 advanced by the owning body's 180-day audit interval.
        assert_instant_equals(
            record["audit_due_at"], "2027-03-09T00:00:00Z", "audit_due_at"
        )


class TestMarketTransitionLeavesDesignUntouched:
    def _stopped_at_mid_august(self):
        ctx = setup_retail_released_product()
        set_clock("2026-08-15T00:00:00Z")
        stopped = validate_success(
            api_client.stop_ship(
                ctx["product"]["id"],
                stop_ship_payload("FIELD_INCIDENT_REVIEW"),
                OFFICER,
            )
        )
        return ctx, stopped

    def test_stop_ship_moves_only_the_market_dimension(self):
        """PRD §2.7: "The two dimensions move independently: freezing a design
        never changes `market_status`, and stopping or resuming shipment never
        changes `design_status`."
        PRD §3.7: "The transition `RETAIL_RELEASED` → `STOP_SHIP` sets
        `stop_ship_reason_code` from the supplied `reason_code`, stamps
        `market_status_changed_at` with the logical clock"

        Design: Difficulty/non_linear_state_machine/product_market_transition_leaves_design_dimension_untouched
        """
        ctx, stopped = self._stopped_at_mid_august()

        assert stopped["market_status"] == "STOP_SHIP"
        assert stopped["stop_ship_reason_code"] == "FIELD_INCIDENT_REVIEW"
        assert_instant_equals(
            stopped["market_status_changed_at"],
            "2026-08-15T00:00:00Z",
            "market_status_changed_at",
        )
        assert stopped["design_status"] == "DESIGN_FROZEN"
        assert_instant_equals(
            stopped["design_frozen_at"], "2026-08-01T00:00:00Z", "design_frozen_at"
        )
        assert stopped["frozen_revision_id"] == ctx["revision"]["id"]

    def test_stop_ship_cascades_into_the_listing_but_not_into_the_design(self):
        """PRD §3.7: "and cascades: every listing record of the model in `LISTED`
        moves `LISTED` → `SUSPENDED` with `suspension_reason` set to
        `STOP_SHIP_CASCADE` and `audit_due_at` cleared"

        Design: Difficulty/non_linear_state_machine/product_market_transition_leaves_design_dimension_untouched
        """
        ctx, _ = self._stopped_at_mid_august()

        record = get_listing_record_data(ctx["listing_record"]["id"])
        assert record["status"] == "SUSPENDED"
        assert record["suspension_reason"] == "STOP_SHIP_CASCADE"
        assert record["audit_due_at"] is None

        product = get_product_data(ctx["product"]["id"])
        assert product["design_status"] == "DESIGN_FROZEN"
        assert product["frozen_revision_id"] == ctx["revision"]["id"]
