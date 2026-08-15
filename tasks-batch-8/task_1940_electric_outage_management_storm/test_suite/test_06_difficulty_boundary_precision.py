"""Difficulty tests — boundary_precision_check rule.

Covers the clustering call-count threshold and the FEMA eligibility cents
threshold, each exercised at the exact boundary and one unit off.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_accepted_assessment,
    create_and_activate_event,
    create_confirm_outage_payload,
    create_crew,
    create_feeder_record,
    create_fema_claim_payload,
    create_outage_payload,
    create_trouble_signal_payload,
    create_work_order_payload,
    get_success_data,
    make_field_crew_lead_headers,
    run_work_order_to_completed,
    set_clock,
    setup_event_with_feeder,
    validate_error,
    validate_paginated,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
TG = TEST_USERS["telemetry_gateway_headers"]
MM = TEST_USERS["materials_manager_headers"]
CO1 = TEST_USERS["claims_officer_headers"]


class TestClusteringCallThresholdExactCount:
    """Exactly threshold signals promote; threshold-1 does not."""

    def test_four_calls_do_not_promote(self, api):
        """PRD §3.2: "The group promotes to an outage when at least one
        `SCADA_TRIP` is present in it, or when the count of last-gasp signals
        reaches the feeder's `cluster_signal_threshold`, or when the count of
        customer calls reaches its `cluster_call_threshold`; a count exactly
        equal to a threshold promotes, while one short of the threshold does
        not."

        Design: Difficulty/boundary_precision_check/clustering_call_threshold_exact_count
        """
        ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T01:00:00Z")
        for minute in (1, 2, 3, 4):
            get_success_data(
                api.create_trouble_signal(
                    create_trouble_signal_payload(
                        fd["id"],
                        signal_type="CUSTOMER_CALL",
                        occurred_at=f"2026-08-10T00:0{minute}:00Z",
                    ),
                    TG,
                )
            )
        result = get_success_data(
            api.run_clustering(ev["id"], {"feeder_id": fd["id"]}, DISP)
        )
        assert result["promoted"] is False
        # The failing run leaves every signal UNCLUSTERED for accumulation.
        signals, meta = validate_paginated(
            api.list_trouble_signals(DISP, params={"feeder_id": fd["id"]})
        )
        assert meta["total_count"] == 4
        assert all(s["disposition"] == "UNCLUSTERED" for s in signals)
        # No outage was created.
        outages, meta2 = validate_paginated(
            api.list_outages(DISP, params={"feeder_id": fd["id"]})
        )
        assert meta2["total_count"] == 0

    def test_five_calls_promote_and_create_suspected_outage(self, api):
        """PRD §3.2: "a count exactly equal to a threshold promotes, while one
        short of the threshold does not. On promotion the system creates an
        outage on the event and feeder in `SUSPECTED` — its
        `customers_affected` stays null until confirmation — and moves every
        signal in the group to `CLUSTERED` with its `outage_id` pointing at
        the new outage."

        Design: Difficulty/boundary_precision_check/clustering_call_threshold_exact_count
        """
        ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T01:00:00Z")
        for minute in (1, 2, 3, 4, 5):
            get_success_data(
                api.create_trouble_signal(
                    create_trouble_signal_payload(
                        fd["id"],
                        signal_type="CUSTOMER_CALL",
                        occurred_at=f"2026-08-10T00:0{minute}:00Z",
                    ),
                    TG,
                )
            )
        result = get_success_data(
            api.run_clustering(ev["id"], {"feeder_id": fd["id"]}, DISP)
        )
        assert result["promoted"] is True
        assert result["clustered_signal_count"] == 5
        outage_id = result["outage_id"]
        outage = get_success_data(api.get_outage(outage_id, DISP))
        assert outage["outage_status"] == "SUSPECTED"
        assert outage["customers_affected"] is None
        signals, _meta = validate_paginated(
            api.list_trouble_signals(DISP, params={"feeder_id": fd["id"]})
        )
        assert all(
            s["disposition"] == "CLUSTERED" and s["outage_id"] == outage_id
            for s in signals
        )


class TestFemaThresholdEqualityQualifies:
    """eligible == threshold qualifies; one cent over the threshold rejects."""

    def _setup_event_with_100000_eligible(self, api):
        """Build an event with exactly 100000 eligible cents in county C1.

        - LABOR_INTERNAL 12000: 60 min at 12000 cents/hr, posted 01:00Z.
        - MATERIAL 88000: 8 x 11000, posted at 00:00Z (== activated_at, in
          window).
        """
        set_clock("2026-08-05T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Mu", event_type="HURRICANE")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=10, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        cr_l = create_crew(crew_type="LINE", hourly_rate_cents=12000)
        create_accepted_assessment(
            ot["id"],
            cr_a["id"],
            expected_outage_version=confirmed["version"],
            damage_class="MAJOR",
            estimated_repair_minutes=60,
            requires_switching=False,
        )
        wo = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    ot["id"], work_type="REPAIR", required_crew_type="LINE"
                ),
                DISP,
            )
        )
        get_success_data(api.ready_work_order(wo["id"], DISP))
        get_success_data(api.assign_work_order(wo["id"], {"crew_id": cr_l["id"]}, DISP))
        fcl = make_field_crew_lead_headers(cr_l["id"])
        get_success_data(api.arrive_work_order(wo["id"], fcl))
        get_success_data(api.start_work_order(wo["id"], fcl))
        # Post the 88000-cent MATERIAL entry at 00:00Z (== activated_at edge).
        from test_helpers import create_material_requisition_payload, create_material_stock_payload

        ms = get_success_data(
            api.create_material_stock(
                create_material_stock_payload(
                    warehouse_code="W1",
                    material_sku="P-9",
                    quantity_on_hand=100,
                    unit_cost_cents=11000,
                ),
                MM,
            )
        )
        mr = get_success_data(
            api.create_material_requisition(
                create_material_requisition_payload(wo["id"], ms["id"], quantity=8),
                MM,
            )
        )
        get_success_data(api.stage_material_requisition(mr["id"], MM))
        get_success_data(api.issue_material_requisition(mr["id"], MM))
        # Advance clock and complete the work order: 60 min at 12000/hr = 12000.
        set_clock("2026-08-05T01:00:00Z")
        get_success_data(api.complete_work_order(wo["id"], fcl))
        get_success_data(api.verify_work_order(wo["id"], {"outcome": "PASSED"}, DISP))
        get_success_data(api.report_restored(ot["id"], DISP))
        # Restore ping at 01:00Z so the outage can verify.
        get_success_data(
            api.create_trouble_signal(
                create_trouble_signal_payload(
                    fd["id"],
                    signal_type="METER_RESTORE_PING",
                    occurred_at="2026-08-05T01:00:00Z",
                    outage_id=ot["id"],
                ),
                TG,
            )
        )
        get_success_data(api.verify_outage(ot["id"], DISP))
        get_success_data(api.consume_material_requisition(mr["id"], MM))
        get_success_data(api.begin_demobilization(ev["id"], ED))
        return ev

    def test_equality_qualifies_for_submit(self, api):
        """PRD §3.9: "the current `eligible_cost_cents` must be at least
        `threshold_cents` — equality qualifies, and a shortfall is rejected
        with `ERR_FEMA_THRESHOLD_NOT_MET`."

        Design: Difficulty/boundary_precision_check/fema_threshold_equality_qualifies
        """
        ev = self._setup_event_with_100000_eligible(api)
        fc_a = get_success_data(
            api.create_fema_claim(
                create_fema_claim_payload(ev["id"], "C1", 100000), CO1
            )
        )
        submitted = get_success_data(api.submit_fema_claim(fc_a["id"], CO1))
        assert submitted["claim_status"] == "SUBMITTED"
        assert submitted["eligible_snapshot_cents"] == 100000, (
            f"eligible = 12000 labor + 88000 material = 100000; snapshot froze "
            f"at {submitted['eligible_snapshot_cents']}"
        )
        assert submitted["preparer_user_id"] == "co-1"

    def test_one_cent_over_threshold_rejected(self, api):
        """PRD §3.9: "the current `eligible_cost_cents` must be at least
        `threshold_cents` — equality qualifies, and a shortfall is rejected
        with `ERR_FEMA_THRESHOLD_NOT_MET`."

        Design: Difficulty/boundary_precision_check/fema_threshold_equality_qualifies
        """
        ev = self._setup_event_with_100000_eligible(api)
        fc_b = get_success_data(
            api.create_fema_claim(
                create_fema_claim_payload(ev["id"], "C1", 100001), CO1
            )
        )
        resp = api.submit_fema_claim(fc_b["id"], CO1)
        err = validate_error(resp, ApiErrorId.ERR_FEMA_THRESHOLD_NOT_MET)
        assert err["error_id"] == "ERR_FEMA_THRESHOLD_NOT_MET"
        # The rejected claim stays DRAFT with a null snapshot.
        claim = get_success_data(api.get_fema_claim(fc_b["id"], CO1))
        assert claim["claim_status"] == "DRAFT"
        assert claim["eligible_snapshot_cents"] is None
