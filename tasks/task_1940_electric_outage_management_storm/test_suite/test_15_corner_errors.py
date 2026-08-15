"""Corner tests — errors section (first batch).

Each test pins one error trigger to its PRD-stated rule.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_accepted_assessment,
    create_and_activate_event,
    create_available_mutual_aid_crew,
    create_committed_lodging_block,
    create_confirm_outage_payload,
    create_crew,
    create_feeder_record,
    create_fema_claim,
    create_fema_claim_payload,
    create_lodging_block_payload,
    create_mutual_aid_crew_payload,
    create_outage_payload,
    create_priority_customer_payload,
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


def test_material_stage_insufficient_then_exact_fit(api):
    """PRD §3.8: "Staging reserves the material: it requires
    `quantity_available` to be at least the requested `quantity` — equality
    is allowed, a shortfall is rejected with `ERR_INSUFFICIENT_MATERIAL`".

    Design: Corner/errors/material_stage_insufficient_then_exact_fit
    """
    _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
    wo = create_ready_work_order(ot["id"])
    ms = create_stock(warehouse_code="W1", material_sku="SKU-1",
                      quantity_on_hand=5, unit_cost_cents=500)
    r1 = create_requisition(wo["id"], ms["id"], quantity=5)
    r2 = create_requisition(wo["id"], ms["id"], quantity=1)
    # Exact fit (5 <= 5) succeeds.
    staged = get_success_data(api.stage_material_requisition(r1["id"], MM))
    assert staged["requisition_status"] == "STAGED"
    # One more unit exceeds available (1 > 0).
    resp = api.stage_material_requisition(r2["id"], MM)
    err = validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MATERIAL)
    assert err["error_id"] == "ERR_INSUFFICIENT_MATERIAL"
    stock = get_success_data(api.get_material_stock(ms["id"], MM))
    assert stock["quantity_reserved"] == 5
    assert stock["quantity_available"] == 0


def test_signal_in_future_rejected(api):
    """PRD §3.2: "the `occurred_at` instant, which must not lie after the
    logical now — a signal from the future is rejected with
    `ERR_SIGNAL_IN_FUTURE`."

    Design: Corner/errors/signal_in_future_rejected
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    resp = api.create_trouble_signal(
        create_trouble_signal_payload(
            fd["id"],
            signal_type="CUSTOMER_CALL",
            occurred_at="2026-08-10T00:00:01Z",
        ),
        TG,
    )
    err = validate_error(resp, ApiErrorId.ERR_SIGNAL_IN_FUTURE)
    assert err["error_id"] == "ERR_SIGNAL_IN_FUTURE"


def test_certify_window_in_past_rejected(api):
    """PRD §3.1: "only when the supplied `certified_through` instant lies
    strictly after the logical now; a date already in the past is rejected
    with `ERR_CERTIFICATION_WINDOW_PAST`."

    Design: Corner/errors/certify_window_in_past_rejected
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    pc = get_success_data(
        api.create_priority_customer(
            create_priority_customer_payload(fd["id"], priority_class="CRITICAL_FACILITY"),
            DISP,
        )
    )
    resp = api.certify_priority_customer(
        pc["id"], {"certified_through": "2026-08-10T00:00:00Z"}, DISP
    )
    err = validate_error(resp, ApiErrorId.ERR_CERTIFICATION_WINDOW_PAST)
    assert err["error_id"] == "ERR_CERTIFICATION_WINDOW_PAST"
    read = get_success_data(api.get_priority_customer(pc["id"], DISP))
    assert read["certification_status"] == "REGISTERED"


def test_crew_type_mismatch_rejected(api):
    """PRD §3.5: "its `crew_type` must equal the order's
    `required_crew_type` (`ERR_CREW_TYPE_MISMATCH`)".

    Design: Corner/errors/crew_type_mismatch_rejected
    """
    _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment(cause_code="TREE")
    cr_l = create_crew(crew_type="LINE")
    wo = create_ready_work_order(ot["id"], work_type="REPAIR", required_crew_type="TREE")
    resp = api.assign_work_order(wo["id"], {"crew_id": cr_l["id"]}, DISP)
    err = validate_error(resp, ApiErrorId.ERR_CREW_TYPE_MISMATCH)
    assert err["error_id"] == "ERR_CREW_TYPE_MISMATCH"
    assert get_success_data(api.get_work_order(wo["id"], DISP))["execution_status"] == "READY"
    assert get_success_data(api.get_crew(cr_l["id"], DISP))["crew_status"] == "AVAILABLE"


def test_crew_not_available_rejected(api):
    """PRD §3.5: "An internal assignee must be `AVAILABLE`
    (`ERR_CREW_NOT_AVAILABLE`)".

    Design: Corner/errors/crew_not_available_rejected
    """
    _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
    # Crew created but never started a shift -> OFF_DUTY.
    cr_l = create_crew(crew_type="LINE", start=False)
    wo = create_ready_work_order(ot["id"])
    resp = api.assign_work_order(wo["id"], {"crew_id": cr_l["id"]}, DISP)
    err = validate_error(resp, ApiErrorId.ERR_CREW_NOT_AVAILABLE)
    assert err["error_id"] == "ERR_CREW_NOT_AVAILABLE"


def test_etr_in_past_rejected(api):
    """PRD §2.11: "First, the new `published_etr` must lie strictly after
    the logical now — a published ETR is always in the future — otherwise
    the request is rejected with `ERR_ETR_IN_PAST` (422)."

    Design: Corner/errors/etr_in_past_rejected
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
    resp = api.publish_etr_revision(
        ot["id"],
        {
            "published_etr": "2026-08-10T00:30:00Z",
            "revision_reason": "CORRECTION",
            "expected_outage_version": confirmed["version"],
        },
        DISP,
    )
    err = validate_error(resp, ApiErrorId.ERR_ETR_IN_PAST)
    assert err["error_id"] == "ERR_ETR_IN_PAST"


def test_outage_cancel_with_work_orders_rejected(api):
    """PRD §3.3: "A false-alarm cancellation — available only from
    `SUSPECTED` or `CONFIRMED`, and only while no work orders exist for the
    outage at all, otherwise `ERR_OUTAGE_WORK_OPEN`".

    Design: Corner/errors/outage_cancel_with_work_orders_rejected
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    get_success_data(
        api.create_work_order(
            create_work_order_payload(
                ot["id"], work_type="ASSESSMENT", required_crew_type="DAMAGE_ASSESSOR"
            ),
            DISP,
        )
    )
    resp = api.cancel_outage(ot["id"], DISP)
    err = validate_error(resp, ApiErrorId.ERR_OUTAGE_WORK_OPEN)
    assert err["error_id"] == "ERR_OUTAGE_WORK_OPEN"
    read = get_success_data(api.get_outage(ot["id"], DISP))
    assert read["outage_status"] == "SUSPECTED"


def test_clustering_requires_active_event(api):
    """PRD §3.2: "A `Dispatcher` runs the promotion pass against an `ACTIVE`
    event — running it against an event in any other posture is rejected
    with `ERR_EVENT_NOT_ACTIVE`".

    Design: Corner/errors/clustering_requires_active_event
    """
    set_clock("2026-08-10T00:00:00Z")
    ev = get_success_data(
        api.create_storm_event(
            {"event_name": "Storm X8", "event_type": "HURRICANE"}, ED
        )
    )
    fd = create_feeder_record(county_code="C1", customer_count=1000)
    # Event is DECLARED, never activated.
    resp = api.run_clustering(ev["id"], {"feeder_id": fd["id"]}, DISP)
    err = validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ACTIVE)
    assert err["error_id"] == "ERR_EVENT_NOT_ACTIVE"


def test_ping_on_suspected_outage_rejected(api):
    """PRD §3.2: "A restore ping is the special case: its payload must also
    carry the `outage_id` of the outage it reports restoration for, that
    outage must currently be in `WORKING` or `RESTORED` (otherwise the
    ingest is rejected with `ERR_PING_OUTAGE_STATE`)".

    Design: Corner/errors/ping_on_suspected_outage_rejected
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    resp = api.create_trouble_signal(
        create_trouble_signal_payload(
            fd["id"],
            signal_type="METER_RESTORE_PING",
            occurred_at="2026-08-10T00:00:00Z",
            outage_id=ot["id"],
        ),
        TG,
    )
    err = validate_error(resp, ApiErrorId.ERR_PING_OUTAGE_STATE)
    assert err["error_id"] == "ERR_PING_OUTAGE_STATE"


def test_report_restored_blocked_with_in_progress_work(api):
    """PRD §3.5: "When every work order on a `WORKING` outage has reached
    `COMPLETED` or `CANCELLED` and at least one has genuinely completed —
    otherwise the report is rejected with `ERR_OUTAGE_WORK_OPEN` — the
    dispatcher reports the outage restored".

    Design: Corner/errors/report_restored_blocked_with_in_progress_work
    """
    _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
    cr_l = create_crew(crew_type="LINE")
    wo = create_ready_work_order(ot["id"])
    get_success_data(api.assign_work_order(wo["id"], {"crew_id": cr_l["id"]}, DISP))
    fcl = make_field_crew_lead_headers(cr_l["id"])
    get_success_data(api.arrive_work_order(wo["id"], fcl))
    get_success_data(api.start_work_order(wo["id"], fcl))
    # Work order is IN_PROGRESS — report_restored is rejected.
    resp = api.report_restored(ot["id"], DISP)
    err = validate_error(resp, ApiErrorId.ERR_OUTAGE_WORK_OPEN)
    assert err["error_id"] == "ERR_OUTAGE_WORK_OPEN"
    read = get_success_data(api.get_outage(ot["id"], DISP))
    assert read["outage_status"] == "WORKING"


def test_verify_requires_restore_ping(api):
    """PRD §3.6: "at least one `CLUSTERED` trouble signal of type
    `METER_RESTORE_PING` pointing at this outage must have an `occurred_at`
    at or after `restoration_reported_at` (`ERR_RESTORE_PING_MISSING`)".

    Design: Corner/errors/verify_requires_restore_ping
    """
    _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
    cr_l = create_crew(crew_type="LINE")
    wo = run_work_order_to_completed(ot["id"], cr_l["id"])
    get_success_data(api.verify_work_order(wo["id"], {"outcome": "PASSED"}, DISP))
    get_success_data(api.report_restored(ot["id"], DISP))
    # No ping ingested.
    resp = api.verify_outage(ot["id"], DISP)
    err = validate_error(resp, ApiErrorId.ERR_RESTORE_PING_MISSING)
    assert err["error_id"] == "ERR_RESTORE_PING_MISSING"
    read = get_success_data(api.get_outage(ot["id"], DISP))
    assert read["outage_status"] == "RESTORED"


def test_verify_blocked_by_unverified_work(api):
    """PRD §3.6: "every non-cancelled work order on it must carry
    `VERIFY_PASSED` (`ERR_UNVERIFIED_WORK_REMAINS`)".

    Design: Corner/errors/verify_blocked_by_unverified_work
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    confirmed = get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(customers_affected=5, cause_code="EQUIPMENT"),
            DISP,
        )
    )
    cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
    create_accepted_assessment(
        ot["id"], cr_a["id"], expected_outage_version=confirmed["version"],
        damage_class="MINOR", estimated_repair_minutes=10,
    )
    cr_l = create_crew(crew_type="LINE")
    wo = run_work_order_to_completed(ot["id"], cr_l["id"])
    # Complete but do NOT verify.
    get_success_data(api.report_restored(ot["id"], DISP))
    get_success_data(
        api.create_trouble_signal(
            create_trouble_signal_payload(
                fd["id"],
                signal_type="METER_RESTORE_PING",
                occurred_at="2026-08-10T00:00:00Z",
                outage_id=ot["id"],
            ),
            TG,
        )
    )
    resp = api.verify_outage(ot["id"], DISP)
    err = validate_error(resp, ApiErrorId.ERR_UNVERIFIED_WORK_REMAINS)
    assert err["error_id"] == "ERR_UNVERIFIED_WORK_REMAINS"


def test_lodging_release_blocked_with_active_crews(api):
    """PRD §3.7: "It requires `rooms_allocated` to be zero — no crew
    currently assigned, otherwise `ERR_LODGING_HAS_ACTIVE_CREWS`".

    Design: Corner/errors/lodging_release_blocked_with_active_crews
    """
    set_clock("2026-08-10T00:00:00Z")
    ev = create_and_activate_event(event_name="Storm X13", event_type="ICE_STORM")
    lb = create_committed_lodging_block(
        ev["id"],
        room_count=2,
        nightly_rate_cents=10000,
        window_start="2026-08-10T00:00:00Z",
        window_end="2026-08-12T00:00:00Z",
        county_code="C1",
        hotel_name="Hotel H",
    )
    ma = create_available_mutual_aid_crew(
        ev["id"],
        crew_type="LINE",
        roster_size=2,
        window_start="2026-08-10T00:00:00Z",
        window_end="2026-08-12T00:00:00Z",
    )
    get_success_data(api.assign_lodging(ma["id"], {"lodging_block_id": lb["id"]}, MAC))
    resp = api.release_lodging_block(lb["id"], MAC)
    err = validate_error(resp, ApiErrorId.ERR_LODGING_HAS_ACTIVE_CREWS)
    assert err["error_id"] == "ERR_LODGING_HAS_ACTIVE_CREWS"
    # No lodging entries were posted by the rejected release.
    entries, meta = validate_paginated(
        api.list_cost_ledger_entries(
            MAC, params={"storm_event_id": ev["id"], "entry_type": "LODGING"}
        )
    )
    assert meta["total_count"] == 0


def test_assign_lodging_requires_committed_block(api):
    """PRD §3.7: "Assigning a crew to a block names the `lodging_block_id`
    and passes four checks: the block must be `COMMITTED`
    (`ERR_LODGING_NOT_COMMITTED`)".

    Design: Corner/errors/assign_lodging_requires_committed_block
    """
    set_clock("2026-08-10T00:00:00Z")
    ev = create_and_activate_event(event_name="Storm X14", event_type="ICE_STORM")
    # Block is OPEN (never committed).
    lb = get_success_data(
        api.create_lodging_block(
            create_lodging_block_payload(
                ev["id"],
                hotel_name="Hotel H",
                room_count=4,
                nightly_rate_cents=10000,
                window_start="2026-08-10T00:00:00Z",
                window_end="2026-08-12T00:00:00Z",
            ),
            MAC,
        )
    )
    ma = create_available_mutual_aid_crew(
        ev["id"],
        crew_type="LINE",
        roster_size=2,
        window_start="2026-08-10T00:00:00Z",
        window_end="2026-08-12T00:00:00Z",
    )
    resp = api.assign_lodging(ma["id"], {"lodging_block_id": lb["id"]}, MAC)
    err = validate_error(resp, ApiErrorId.ERR_LODGING_NOT_COMMITTED)
    assert err["error_id"] == "ERR_LODGING_NOT_COMMITTED"
    crew = get_success_data(api.get_mutual_aid_crew(ma["id"], MAC))
    assert crew["lodging_block_id"] is None
    block = get_success_data(api.get_lodging_block(lb["id"], MAC))
    assert block["rooms_allocated"] == 0
