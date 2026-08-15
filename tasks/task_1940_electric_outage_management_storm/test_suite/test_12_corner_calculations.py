"""Corner tests — calculations section.

Covers clustering promotion branches, ETR revision constraints, fatigue
boundary, labor rounding, and FEMA window filtering.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    create_accepted_assessment,
    create_and_activate_event,
    create_available_mutual_aid_crew,
    create_committed_lodging_block,
    create_confirm_outage_payload,
    create_crew,
    create_etr_revision_payload,
    create_fema_claim,
    create_fema_claim_payload,
    create_feeder_record,
    create_material_requisition_payload,
    create_material_stock_payload,
    create_mutual_aid_crew_payload,
    create_outage_payload,
    create_ready_work_order,
    create_requisition,
    create_stock,
    create_trouble_signal_payload,
    create_work_order_payload,
    get_success_data,
    make_field_crew_lead_headers,
    run_work_order_to_completed,
    set_clock,
    setup_event_with_feeder,
    setup_outage_with_accepted_assessment,
    validate_error,
    validate_paginated,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
TG = TEST_USERS["telemetry_gateway_headers"]
MAC = TEST_USERS["mutual_aid_coordinator_headers"]
MM = TEST_USERS["materials_manager_headers"]
CO1 = TEST_USERS["claims_officer_headers"]


def test_clustering_scada_trip_promotes_immediately(api):
    """PRD §3.2: "The group promotes to an outage when at least one
    `SCADA_TRIP` is present in it, or when the count of last-gasp signals
    reaches the feeder's `cluster_signal_threshold`, or when the count of
    customer calls reaches its `cluster_call_threshold`".

    Design: Corner/calculations/clustering_scada_trip_promotes_immediately
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T01:00:00Z")
    get_success_data(
        api.create_trouble_signal(
            create_trouble_signal_payload(
                fd["id"],
                signal_type="SCADA_TRIP",
                occurred_at="2026-08-10T00:01:00Z",
            ),
            TG,
        )
    )
    result = get_success_data(api.run_clustering(ev["id"], {"feeder_id": fd["id"]}, DISP))
    assert result["promoted"] is True
    assert result["clustered_signal_count"] == 1


def test_clustering_anchor_window_inclusive_end(api):
    """PRD §3.2: "The earliest candidate anchors a single group: every
    candidate whose `occurred_at` falls within sixty minutes of the anchor's,
    the end of the window included."

    Design: Corner/calculations/clustering_anchor_window_inclusive_end
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T01:02:00Z")
    # Five calls at 00:00, 00:01, 00:02, 00:03, 01:00 — the anchor is 00:00
    # and 01:00 lands exactly at anchor+60 (inclusive).
    for ts in (
        "2026-08-10T00:00:00Z",
        "2026-08-10T00:01:00Z",
        "2026-08-10T00:02:00Z",
        "2026-08-10T00:03:00Z",
        "2026-08-10T01:00:00Z",
    ):
        get_success_data(
            api.create_trouble_signal(
                create_trouble_signal_payload(
                    fd["id"], signal_type="CUSTOMER_CALL", occurred_at=ts
                ),
                TG,
            )
        )
    # A sixth call at 01:01 falls outside the anchored window.
    sixth = get_success_data(
        api.create_trouble_signal(
            create_trouble_signal_payload(
                fd["id"], signal_type="CUSTOMER_CALL", occurred_at="2026-08-10T01:01:00Z"
            ),
            TG,
        )
    )
    result = get_success_data(api.run_clustering(ev["id"], {"feeder_id": fd["id"]}, DISP))
    assert result["promoted"] is True
    assert result["clustered_signal_count"] == 5
    sixth_read = get_success_data(api.get_trouble_signal(sixth["id"], DISP))
    assert sixth_read["disposition"] == "UNCLUSTERED"


def test_etr_extension_cap_boundary_360(api):
    """PRD §2.11: "an extension may move the published time later by at most
    360 minutes (six hours) in a single revision unless the reason is
    `DAMAGE_FOUND`, which is uncapped; an extension of exactly 360 minutes is
    allowed, while one minute more is rejected with
    `ERR_ETR_EXTENSION_EXCEEDS_CAP` (422)."

    Design: Corner/calculations/etr_extension_cap_boundary_360
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    confirmed = get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(
                customers_affected=100, cause_code="TREE"
            ),
            DISP,
        )
    )
    # current_etr = 07:00Z; advance past the lock horizon setup.
    set_clock("2026-08-10T01:00:00Z")
    # Exactly +360 min (07:00 -> 13:00) is allowed.
    rev1 = get_success_data(
        api.publish_etr_revision(
            ot["id"],
            create_etr_revision_payload(
                published_etr="2026-08-10T13:00:00Z",
                revision_reason="WEATHER_DELAY",
                expected_outage_version=confirmed["version"],
            ),
            DISP,
        )
    )
    assert rev1["revision_seq"] == 2
    # One minute over the cap in a single revision from the new current ETR
    # (13:00 -> 19:01 is +361 min) fails.
    outage = get_success_data(api.get_outage(ot["id"], DISP))
    resp = api.publish_etr_revision(
        ot["id"],
        create_etr_revision_payload(
            published_etr="2026-08-10T19:01:00Z",
            revision_reason="CREW_DELAYED",
            expected_outage_version=outage["version"],
        ),
        DISP,
    )
    err = validate_error(resp, ApiErrorId.ERR_ETR_EXTENSION_EXCEEDS_CAP)
    assert err["error_id"] == "ERR_ETR_EXTENSION_EXCEEDS_CAP"
    # Failed revision does not move current_etr.
    outage_after = get_success_data(api.get_outage(ot["id"], DISP))
    assert_instant_equals(outage_after["current_etr"], "2026-08-10T13:00:00Z")


def test_etr_lock_horizon_allows_only_nested_discovery(api):
    """PRD §2.11: "a public-commit lock horizon protects imminent promises:
    when the logical now falls within the thirty minutes before the current
    ETR, inclusive of both ends of that window, every manual revision is
    rejected with `ERR_ETR_LOCKED_HORIZON` (422) unless the reason is
    `NESTED_DISCOVERED`; once the ETR has been missed, the lock no longer
    applies."

    Design: Corner/calculations/etr_lock_horizon_allows_only_nested_discovery
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    confirmed = get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(
                customers_affected=100, cause_code="TREE"
            ),
            DISP,
        )
    )
    # current_etr = 07:00Z; now = 06:45Z is inside [06:30Z, 07:00Z].
    set_clock("2026-08-10T06:45:00Z")
    resp = api.publish_etr_revision(
        ot["id"],
        create_etr_revision_payload(
            published_etr="2026-08-10T08:00:00Z",
            revision_reason="WEATHER_DELAY",
            expected_outage_version=confirmed["version"],
        ),
        DISP,
    )
    err = validate_error(resp, ApiErrorId.ERR_ETR_LOCKED_HORIZON)
    assert err["error_id"] == "ERR_ETR_LOCKED_HORIZON"
    # NESTED_DISCOVERED is exempt.
    rev = get_success_data(
        api.publish_etr_revision(
            ot["id"],
            create_etr_revision_payload(
                published_etr="2026-08-10T08:00:00Z",
                revision_reason="NESTED_DISCOVERED",
                expected_outage_version=confirmed["version"],
            ),
            DISP,
        )
    )
    assert rev["revision_seq"] == 2
    outage = get_success_data(api.get_outage(ot["id"], DISP))
    assert_instant_equals(outage["current_etr"], "2026-08-10T08:00:00Z")


def test_etr_backward_correction_only_pre_working(api):
    """PRD §2.11: "a backward revision, one earlier than the outage's current
    `current_etr`, is allowed only with reason `CORRECTION` and only while
    the outage is in `CONFIRMED` or `ASSESSED`; any other backward revision
    is rejected with `ERR_ETR_BACKWARD_FORBIDDEN` (422)".

    Design: Corner/calculations/etr_backward_correction_only_pre_working
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    confirmed = get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(
                customers_affected=100, cause_code="TREE"
            ),
            DISP,
        )
    )
    set_clock("2026-08-10T01:00:00Z")
    # CORRECTION backward move is allowed while CONFIRMED.
    rev = get_success_data(
        api.publish_etr_revision(
            ot["id"],
            create_etr_revision_payload(
                published_etr="2026-08-10T05:00:00Z",
                revision_reason="CORRECTION",
                expected_outage_version=confirmed["version"],
            ),
            DISP,
        )
    )
    assert rev["revision_seq"] == 2
    assert_instant_equals(rev["previous_etr"], "2026-08-10T07:00:00Z")
    outage = get_success_data(api.get_outage(ot["id"], DISP))
    assert_instant_equals(outage["current_etr"], "2026-08-10T05:00:00Z")
    # Same backward direction without CORRECTION is rejected.
    resp = api.publish_etr_revision(
        ot["id"],
        create_etr_revision_payload(
            published_etr="2026-08-10T04:30:00Z",
            revision_reason="WEATHER_DELAY",
            expected_outage_version=outage["version"],
        ),
        DISP,
    )
    err = validate_error(resp, ApiErrorId.ERR_ETR_BACKWARD_FORBIDDEN)
    assert err["error_id"] == "ERR_ETR_BACKWARD_FORBIDDEN"


def test_fatigue_boundary_960_allowed_961_rejected(api):
    """PRD §2.12: "The ceiling is 960 minutes: a projection of exactly 960
    minutes is allowed, while 961 minutes or more is rejected with
    `ERR_FATIGUE_LIMIT_EXCEEDED` (422)."

    Design: Corner/calculations/fatigue_boundary_960_allowed_961_rejected
    """
    set_clock("2026-08-10T00:00:00Z")
    ev = create_and_activate_event(event_name="Storm K6", event_type="ICE_STORM")
    fd = create_feeder_record(county_code="C1", customer_count=5000)
    cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
    cr9 = create_crew(crew_type="LINE", crew_code="L-9")
    cr10 = create_crew(crew_type="LINE", crew_code="L-10")

    def build_history(
        outage_customers: int,
        repair_minutes: int,
        crew_id: str,
        arrive_iso: str,
        complete_iso: str,
    ):
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=outage_customers, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        create_accepted_assessment(
            ot["id"],
            cr_a["id"],
            expected_outage_version=confirmed["version"],
            damage_class="MINOR",
            estimated_repair_minutes=repair_minutes,
            requires_switching=False,
        )
        run_work_order_to_completed(
            ot["id"],
            crew_id,
            arrive_clock_iso=arrive_iso,
            complete_clock_iso=complete_iso,
        )
        return ot

    # L-9 history: 900-minute completed work order (arrive 00:00Z, complete 15:00Z).
    h1 = build_history(5, 1, cr9["id"], "2026-08-10T00:00:00Z", "2026-08-10T15:00:00Z")
    # L-10 history: 900-minute completed work order (arrive 15:00Z, complete 06:00Z next day).
    h2 = build_history(5, 1, cr10["id"], "2026-08-10T15:00:00Z", "2026-08-11T06:00:00Z")

    # Target T1: repair 60 -> projection 900 + 60 = 960 (allowed).
    t1 = get_success_data(
        api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
    )
    conf_t1 = get_success_data(
        api.confirm_outage(
            t1["id"],
            create_confirm_outage_payload(
                customers_affected=5, cause_code="EQUIPMENT"
            ),
            DISP,
        )
    )
    create_accepted_assessment(
        t1["id"],
        cr_a["id"],
        expected_outage_version=conf_t1["version"],
        damage_class="MAJOR",
        estimated_repair_minutes=60,
        requires_switching=False,
    )
    wo_t1 = create_ready_work_order(t1["id"])

    # Target T2: repair 61 -> projection 900 + 61 = 961 (rejected).
    t2 = get_success_data(
        api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
    )
    conf_t2 = get_success_data(
        api.confirm_outage(
            t2["id"],
            create_confirm_outage_payload(
                customers_affected=5, cause_code="EQUIPMENT"
            ),
            DISP,
        )
    )
    create_accepted_assessment(
        t2["id"],
        cr_a["id"],
        expected_outage_version=conf_t2["version"],
        damage_class="MAJOR",
        estimated_repair_minutes=61,
        requires_switching=False,
    )
    wo_t2 = create_ready_work_order(t2["id"])

    # 960 exactly: allowed.
    dispatched = get_success_data(
        api.assign_work_order(wo_t1["id"], {"crew_id": cr9["id"]}, DISP)
    )
    assert dispatched["execution_status"] == "DISPATCHED"
    # 961: rejected.
    resp = api.assign_work_order(wo_t2["id"], {"crew_id": cr10["id"]}, DISP)
    err = validate_error(resp, ApiErrorId.ERR_FATIGUE_LIMIT_EXCEEDED)
    assert err["error_id"] == "ERR_FATIGUE_LIMIT_EXCEEDED"
    # The failed assignment left the work order READY and the crew AVAILABLE.
    assert get_success_data(api.get_work_order(wo_t2["id"], DISP))["execution_status"] == "READY"
    assert get_success_data(api.get_crew(cr10["id"], DISP))["crew_status"] == "AVAILABLE"


def test_labor_cost_rounding_and_capital_class_split(api):
    """PRD §3.5: "the minutes between `arrived_at` and `completed_at`,
    multiplied by the crew's `hourly_rate_cents` and divided by sixty,
    rounded half up to whole cents — thirty minutes at an hourly rate of
    10,001 cents posts 5,001 cents. The entry's type is `LABOR_INTERNAL`, its
    county is the outage's feeder's county, and its class follows §2.10."
    PRD §2.10: "An entry's `cost_class` is `CAPITAL` when it is a labor or
    material entry arising from a work order of type `REPLACE_POLE` or
    `REPLACE_TRANSFORMER`, and `O_AND_M` in every other case".

    Design: Corner/calculations/labor_cost_rounding_and_capital_class_split
    """
    set_clock("2026-08-10T00:00:00Z")
    ev = create_and_activate_event(event_name="Storm K7", event_type="HURRICANE")
    fd = create_feeder_record(county_code="C1", customer_count=2000)
    ot = get_success_data(
        api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
    )
    confirmed = get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(
                customers_affected=5, cause_code="EQUIPMENT"
            ),
            DISP,
        )
    )
    cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
    cr_l = create_crew(crew_type="LINE", hourly_rate_cents=10001)
    create_accepted_assessment(
        ot["id"],
        cr_a["id"],
        expected_outage_version=confirmed["version"],
        damage_class="MINOR",
        estimated_repair_minutes=10,
        requires_switching=False,
    )
    # REPAIR (O_AND_M) — 30 minutes at 10001/hr -> 5001.
    wo_r = run_work_order_to_completed(
        ot["id"], cr_l["id"], work_type="REPAIR",
        complete_clock_iso="2026-08-10T00:30:00Z",
    )
    # REPLACE_POLE (CAPITAL) — same crew, same 30 minutes.
    wo_p = run_work_order_to_completed(
        ot["id"], cr_l["id"], work_type="REPLACE_POLE",
        complete_clock_iso="2026-08-10T01:00:00Z",
    )
    entries, _meta = validate_paginated(
        api.list_cost_ledger_entries(
            DISP, params={"storm_event_id": ev["id"], "entry_type": "LABOR_INTERNAL"}
        )
    )
    assert len(entries) == 2
    by_class = {e["cost_class"]: e for e in entries}
    assert by_class["O_AND_M"]["amount_cents"] == 5001
    assert by_class["O_AND_M"]["county_code"] == "C1"
    assert by_class["CAPITAL"]["amount_cents"] == 5001
    assert by_class["CAPITAL"]["county_code"] == "C1"
    ev_read = get_success_data(api.get_storm_event(ev["id"], DISP))
    assert ev_read["capital_cost_cents"] == 5001
    assert ev_read["om_cost_cents"] == 5001
    assert ev_read["total_labor_cents"] == 10002


def test_fema_window_and_type_exclusions(api):
    """PRD §3.9: "it sums the `amount_cents` of the event's ledger entries
    attributed to the claim's county, counting only `LABOR_INTERNAL`,
    `LABOR_MUTUAL_AID`, and `MATERIAL` entries — `LODGING` and
    `MUTUAL_AID_PENALTY` are ineligible and excluded — and only entries whose
    `posted_at` falls no earlier than the event's `activated_at` and no later
    than ninety-six hours after it, both ends inclusive; reversal entries net
    against their originals inside the sum."

    Design: Corner/calculations/fema_window_and_type_exclusions
    """
    set_clock("2026-08-05T00:00:00Z")
    ev = create_and_activate_event(event_name="Storm K8", event_type="HURRICANE")
    fd = create_feeder_record(county_code="C1", customer_count=5000)
    cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
    cr_l = create_crew(crew_type="LINE", hourly_rate_cents=12000)

    # Outage 1: completes at 08-05T01:00Z (in window) — 60 min labor = 12000.
    o1 = get_success_data(
        api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
    )
    conf1 = get_success_data(
        api.confirm_outage(
            o1["id"],
            create_confirm_outage_payload(customers_affected=10, cause_code="EQUIPMENT"),
            DISP,
        )
    )
    create_accepted_assessment(
        o1["id"],
        cr_a["id"],
        expected_outage_version=conf1["version"],
        damage_class="MAJOR",
        estimated_repair_minutes=60,
        requires_switching=False,
    )
    wo1 = get_success_data(
        api.create_work_order(
            create_work_order_payload(o1["id"], work_type="REPAIR", required_crew_type="LINE"),
            DISP,
        )
    )
    get_success_data(api.ready_work_order(wo1["id"], DISP))
    get_success_data(api.assign_work_order(wo1["id"], {"crew_id": cr_l["id"]}, DISP))
    fcl = make_field_crew_lead_headers(cr_l["id"])
    get_success_data(api.arrive_work_order(wo1["id"], fcl))
    get_success_data(api.start_work_order(wo1["id"], fcl))
    set_clock("2026-08-05T01:00:00Z")
    get_success_data(api.complete_work_order(wo1["id"], fcl))

    # Lodging block posts a LODGING 10700 at 08-05T01:00Z (excluded by type).
    lb = create_committed_lodging_block(
        ev["id"],
        room_count=1,
        nightly_rate_cents=10000,
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
        county_code="C1",
        hotel_name="Hotel H",
    )
    ma = create_available_mutual_aid_crew(
        ev["id"],
        crew_type="TREE",
        roster_size=1,
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
    )
    get_success_data(api.assign_lodging(ma["id"], {"lodging_block_id": lb["id"]}, MAC))
    get_success_data(api.demobilize_mutual_aid_crew(ma["id"], MAC))
    get_success_data(api.release_lodging_block(lb["id"], MAC))

    # Outage 2: completes at 08-09T01:00Z — one hour AFTER window close.
    o2 = get_success_data(
        api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
    )
    conf2 = get_success_data(
        api.confirm_outage(
            o2["id"],
            create_confirm_outage_payload(customers_affected=10, cause_code="EQUIPMENT"),
            DISP,
        )
    )
    create_accepted_assessment(
        o2["id"],
        cr_a["id"],
        expected_outage_version=conf2["version"],
        damage_class="MINOR",
        estimated_repair_minutes=30,
        requires_switching=False,
    )
    wo2 = get_success_data(
        api.create_work_order(
            create_work_order_payload(o2["id"], work_type="REPAIR", required_crew_type="LINE"),
            DISP,
        )
    )
    get_success_data(api.ready_work_order(wo2["id"], DISP))
    get_success_data(api.assign_work_order(wo2["id"], {"crew_id": cr_l["id"]}, DISP))
    set_clock("2026-08-09T00:30:00Z")
    get_success_data(api.arrive_work_order(wo2["id"], fcl))
    get_success_data(api.start_work_order(wo2["id"], fcl))
    set_clock("2026-08-09T01:00:00Z")
    get_success_data(api.complete_work_order(wo2["id"], fcl))

    fc = create_fema_claim(ev["id"], county_code="C1", threshold_cents=1)
    read = get_success_data(api.get_fema_claim(fc["id"], CO1))
    # Only the in-window LABOR_INTERNAL 12000 counts.
    assert read["eligible_cost_cents"] == 12000, (
        f"eligible_cost_cents must be 12000; got {read['eligible_cost_cents']}"
    )
