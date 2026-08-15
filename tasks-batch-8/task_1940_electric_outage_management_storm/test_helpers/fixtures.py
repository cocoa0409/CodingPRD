"""Composite setup helpers for the outage-management test suite.

Every fixture builds its preconditions from scratch using only endpoints the
PRD declares. Fixtures return response-data dicts so tests can read fields
directly; setup uses `get_success_data` (lenient) so failures surface as
clear "Setup failed" assertion errors instead of cascading through
validators.
"""
from typing import Any, Dict, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_confirm_outage_payload,
    create_crew_payload,
    create_damage_assessment_payload,
    create_fema_claim_payload,
    create_feeder_payload,
    create_lodging_block_payload,
    create_material_requisition_payload,
    create_material_stock_payload,
    create_mutual_aid_crew_payload,
    create_outage_payload,
    create_priority_customer_payload,
    create_storm_event_payload,
    create_switching_order_payload,
    create_trouble_signal_payload,
    create_work_order_payload,
)
from .test_users import TEST_USERS, make_field_crew_lead_headers

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
TG = TEST_USERS["telemetry_gateway_headers"]
SYSOP1 = TEST_USERS["system_operator_headers"]
SYSOP2 = TEST_USERS["system_operator_2_headers"]
MAC = TEST_USERS["mutual_aid_coordinator_headers"]
MM = TEST_USERS["materials_manager_headers"]
CO1 = TEST_USERS["claims_officer_headers"]
CO2 = TEST_USERS["claims_officer_2_headers"]
REG = TEST_USERS["regulator_headers"]


# --- Tier 1: clock + base grid -------------------------------------------------


def set_clock(iso: str) -> Dict[str, Any]:
    resp = api_client.set_clock({"to_iso8601": iso}, ED)
    return get_success_data(resp)


def create_event(event_name: Optional[str] = None, event_type: str = "HURRICANE") -> Dict[str, Any]:
    resp = api_client.create_storm_event(
        create_storm_event_payload(event_name=event_name, event_type=event_type)
        if event_name
        else create_storm_event_payload(event_type=event_type),
        ED,
    )
    return get_success_data(resp)


def create_and_activate_event(
    event_name: Optional[str] = None, event_type: str = "HURRICANE"
) -> Dict[str, Any]:
    ev = create_event(event_name=event_name, event_type=event_type)
    return get_success_data(api_client.activate_storm_event(ev["id"], ED))


def create_feeder_record(
    county_code: str = "C1",
    customer_count: int = 2000,
    signal_threshold: Optional[int] = None,
    call_threshold: Optional[int] = None,
) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    if signal_threshold is not None:
        overrides["cluster_signal_threshold"] = signal_threshold
    if call_threshold is not None:
        overrides["cluster_call_threshold"] = call_threshold
    resp = api_client.create_feeder(
        create_feeder_payload(
            county_code=county_code,
            service_customer_count=customer_count,
            **overrides,
        ),
        ED,
    )
    return get_success_data(resp)


# --- Tier 2: event + feeder scaffold -------------------------------------------


def setup_event_with_feeder(
    clock_iso: str = "2026-08-10T00:00:00Z",
    county_code: str = "C1",
    customer_count: int = 2000,
    signal_threshold: Optional[int] = None,
    call_threshold: Optional[int] = None,
    event_type: str = "HURRICANE",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """ACTIVE event + one feeder. Returns (event, feeder)."""
    set_clock(clock_iso)
    ev = create_and_activate_event(event_type=event_type)
    fd = create_feeder_record(
        county_code=county_code,
        customer_count=customer_count,
        signal_threshold=signal_threshold,
        call_threshold=call_threshold,
    )
    return ev, fd


# --- Tier 3: outage lifecycle ---------------------------------------------------


def create_outage_on_event(
    event_id: str, feeder_id: str, parent_outage_id: Optional[str] = None
) -> Dict[str, Any]:
    payload = create_outage_payload(event_id, feeder_id)
    if parent_outage_id is not None:
        payload["parent_outage_id"] = parent_outage_id
    resp = api_client.create_outage(payload, DISP)
    return get_success_data(resp)


def create_confirmed_outage(
    event_id: str,
    feeder_id: str,
    customers_affected: int = 5,
    cause_code: str = "EQUIPMENT",
    parent_outage_id: Optional[str] = None,
) -> Dict[str, Any]:
    """SUSPECTED -> CONFIRMED. Returns the post-confirm outage (version 2)."""
    ot = create_outage_on_event(event_id, feeder_id, parent_outage_id=parent_outage_id)
    resp = api_client.confirm_outage(
        ot["id"],
        create_confirm_outage_payload(
            customers_affected=customers_affected, cause_code=cause_code
        ),
        DISP,
    )
    return get_success_data(resp)


def create_crew(
    crew_type: str = "LINE",
    hourly_rate_cents: int = 9000,
    crew_code: Optional[str] = None,
    start: bool = True,
) -> Dict[str, Any]:
    payload = create_crew_payload(
        crew_type=crew_type, hourly_rate_cents=hourly_rate_cents
    )
    if crew_code is not None:
        payload["crew_code"] = crew_code
    crew = get_success_data(api_client.create_crew(payload, DISP))
    if start:
        crew = get_success_data(api_client.start_shift(crew["id"], DISP))
    return crew


def create_submitted_assessment(
    outage_id: str,
    assessor_crew_id: str,
    damage_class: str = "MINOR",
    estimated_repair_minutes: int = 30,
    requires_switching: bool = False,
) -> Dict[str, Any]:
    fcl = make_field_crew_lead_headers(assessor_crew_id)
    da = get_success_data(
        api_client.create_damage_assessment(
            create_damage_assessment_payload(
                outage_id,
                damage_class=damage_class,
                estimated_repair_minutes=estimated_repair_minutes,
                requires_switching=requires_switching,
            ),
            fcl,
        )
    )
    return get_success_data(api_client.submit_damage_assessment(da["id"], fcl))


def create_accepted_assessment(
    outage_id: str,
    assessor_crew_id: str,
    expected_outage_version: int,
    damage_class: str = "MINOR",
    estimated_repair_minutes: int = 30,
    requires_switching: bool = False,
) -> Dict[str, Any]:
    da = create_submitted_assessment(
        outage_id,
        assessor_crew_id,
        damage_class=damage_class,
        estimated_repair_minutes=estimated_repair_minutes,
        requires_switching=requires_switching,
    )
    return get_success_data(
        api_client.accept_damage_assessment(
            da["id"], {"expected_outage_version": expected_outage_version}, DISP
        )
    )


def create_ready_work_order(
    outage_id: str,
    work_type: str = "REPAIR",
    required_crew_type: str = "LINE",
    requires_switching_order: bool = False,
) -> Dict[str, Any]:
    wo = get_success_data(
        api_client.create_work_order(
            create_work_order_payload(
                outage_id,
                work_type=work_type,
                required_crew_type=required_crew_type,
                requires_switching_order=requires_switching_order,
            ),
            DISP,
        )
    )
    return get_success_data(api_client.ready_work_order(wo["id"], DISP))


def setup_outage_with_accepted_assessment(
    customers_affected: int = 5,
    cause_code: str = "EQUIPMENT",
    estimated_repair_minutes: int = 30,
    requires_switching: bool = False,
    clock_iso: str = "2026-08-10T00:00:00Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """ACTIVE event + feeder + confirmed outage + ACCEPTED damage assessment.

    Returns (event, feeder, outage, assessor_crew, assessment).
    """
    ev, fd = setup_event_with_feeder(clock_iso=clock_iso)
    ot = create_confirmed_outage(
        ev["id"], fd["id"], customers_affected=customers_affected, cause_code=cause_code
    )
    cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
    da = create_accepted_assessment(
        ot["id"],
        cr_a["id"],
        expected_outage_version=ot["version"],
        estimated_repair_minutes=estimated_repair_minutes,
        requires_switching=requires_switching,
    )
    ot = get_success_data(api_client.get_outage(ot["id"], DISP))
    return ev, fd, ot, cr_a, da


# --- Tier 4: full work-order lifecycle -----------------------------------------


def run_work_order_to_completed(
    outage_id: str,
    crew_id: str,
    work_type: str = "REPAIR",
    required_crew_type: str = "LINE",
    requires_switching_order: bool = False,
    arrive_clock_iso: Optional[str] = None,
    complete_clock_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """READY -> DISPATCHED -> arrived -> started -> completed.

    Returns the post-completion work order. If `complete_clock_iso` is given,
    the logical clock is advanced before completion (drives worked-minutes
    accrual and labor posting).
    """
    wo = create_ready_work_order(
        outage_id,
        work_type=work_type,
        required_crew_type=required_crew_type,
        requires_switching_order=requires_switching_order,
    )
    wo = get_success_data(
        api_client.assign_work_order(wo["id"], {"crew_id": crew_id}, DISP)
    )
    if arrive_clock_iso is not None:
        set_clock(arrive_clock_iso)
    fcl = make_field_crew_lead_headers(crew_id)
    wo = get_success_data(api_client.arrive_work_order(wo["id"], fcl))
    wo = get_success_data(api_client.start_work_order(wo["id"], fcl))
    if complete_clock_iso is not None:
        set_clock(complete_clock_iso)
    return get_success_data(api_client.complete_work_order(wo["id"], fcl))


def setup_completed_work_order_scenario(
    customers_affected: int = 5,
    cause_code: str = "EQUIPMENT",
    estimated_repair_minutes: int = 30,
    crew_hourly_rate_cents: int = 9000,
    clock_iso: str = "2026-08-10T00:00:00Z",
    complete_clock_iso: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Full path: event+feeder+outage+accepted assessment+completed work order.

    Returns (event, feeder, outage, line_crew, work_order).
    """
    ev, fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment(
        customers_affected=customers_affected,
        cause_code=cause_code,
        estimated_repair_minutes=estimated_repair_minutes,
        clock_iso=clock_iso,
    )
    cr_l = create_crew(crew_type="LINE", hourly_rate_cents=crew_hourly_rate_cents)
    wo = run_work_order_to_completed(
        ot["id"], cr_l["id"], complete_clock_iso=complete_clock_iso
    )
    ot = get_success_data(api_client.get_outage(ot["id"], DISP))
    return ev, fd, ot, cr_l, wo


def create_stock(
    warehouse_code: Optional[str] = None,
    material_sku: str = "SKU-1",
    quantity_on_hand: int = 100,
    unit_cost_cents: int = 500,
) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {
        "material_sku": material_sku,
        "quantity_on_hand": quantity_on_hand,
        "unit_cost_cents": unit_cost_cents,
    }
    if warehouse_code is not None:
        overrides["warehouse_code"] = warehouse_code
    return get_success_data(
        api_client.create_material_stock(create_material_stock_payload(**overrides), MM)
    )


def create_requisition(
    work_order_id: str, material_stock_id: str, quantity: int = 10
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_material_requisition(
            create_material_requisition_payload(
                work_order_id, material_stock_id, quantity=quantity
            ),
            MM,
        )
    )


def create_staged_requisition(
    work_order_id: str, material_stock_id: str, quantity: int = 10
) -> Dict[str, Any]:
    mr = create_requisition(work_order_id, material_stock_id, quantity=quantity)
    return get_success_data(api_client.stage_material_requisition(mr["id"], MM))


def create_issued_requisition(
    work_order_id: str, material_stock_id: str, quantity: int = 10
) -> Dict[str, Any]:
    mr = create_staged_requisition(work_order_id, material_stock_id, quantity=quantity)
    return get_success_data(api_client.issue_material_requisition(mr["id"], MM))


# --- Tier 5: mutual aid + lodging -------------------------------------------------


def create_available_mutual_aid_crew(
    event_id: str,
    crew_type: str = "LINE",
    roster_size: int = 2,
    daily_rate_cents: int = 40000,
    per_diem_cents: int = 5000,
    window_start: str = "2026-08-10T00:00:00Z",
    window_end: str = "2026-08-12T00:00:00Z",
    county_code: str = "C1",
) -> Dict[str, Any]:
    ma = get_success_data(
        api_client.create_mutual_aid_crew(
            create_mutual_aid_crew_payload(
                event_id,
                committed_window_start=window_start,
                committed_window_end=window_end,
                crew_type=crew_type,
                roster_size=roster_size,
                daily_rate_cents=daily_rate_cents,
                per_diem_cents=per_diem_cents,
                service_county_code=county_code,
            ),
            MAC,
        )
    )
    return get_success_data(api_client.mark_arrived(ma["id"], MAC))


def create_committed_lodging_block(
    event_id: str,
    room_count: int = 4,
    nightly_rate_cents: int = 10000,
    window_start: str = "2026-08-10T00:00:00Z",
    window_end: str = "2026-08-12T00:00:00Z",
    county_code: str = "C1",
    hotel_name: Optional[str] = None,
) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    if hotel_name is not None:
        overrides["hotel_name"] = hotel_name
    lb = get_success_data(
        api_client.create_lodging_block(
            create_lodging_block_payload(
                event_id,
                window_start=window_start,
                window_end=window_end,
                room_count=room_count,
                nightly_rate_cents=nightly_rate_cents,
                county_code=county_code,
                **overrides,
            ),
            MAC,
        )
    )
    return get_success_data(api_client.commit_lodging_block(lb["id"], MAC))


# --- Tier 6: switching-order ladder ---------------------------------------------


def create_switching_order_for_work_order(
    work_order_id: str,
    issuer_user_id: str = "op-1",
    steps: Optional[list] = None,
) -> Dict[str, Any]:
    from .test_users import make_system_operator_headers

    return get_success_data(
        api_client.create_switching_order(
            create_switching_order_payload(
                work_order_id, switching_steps=steps or ["Open breaker 7"]
            ),
            make_system_operator_headers(issuer_user_id),
        )
    )


def create_issued_switching_order(
    work_order_id: str, issuer_user_id: str = "op-1"
) -> Dict[str, Any]:
    from .test_users import make_system_operator_headers

    so = create_switching_order_for_work_order(
        work_order_id, issuer_user_id=issuer_user_id
    )
    return get_success_data(
        api_client.issue_switching_order(
            so["id"], make_system_operator_headers(issuer_user_id)
        )
    )


def create_executed_switching_order(
    work_order_id: str,
    issuer_user_id: str = "op-1",
    approver_user_id: str = "op-2",
) -> Dict[str, Any]:
    from .test_users import make_system_operator_headers

    so = create_issued_switching_order(work_order_id, issuer_user_id=issuer_user_id)
    so = get_success_data(
        api_client.approve_switching_order(
            so["id"], make_system_operator_headers(approver_user_id)
        )
    )
    return get_success_data(
        api_client.execute_switching_order(
            so["id"], make_system_operator_headers(approver_user_id)
        )
    )


# --- Tier 7: FEMA lifecycle ------------------------------------------------------


def create_fema_claim(
    event_id: str, county_code: str = "C1", threshold_cents: int = 0
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_fema_claim(
            create_fema_claim_payload(event_id, county_code, threshold_cents), CO1
        )
    )


def setup_demobilized_event_with_claim(
    clock_iso: str = "2026-08-10T00:00:00Z", threshold_cents: int = 0
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Event carried DECLARED -> ACTIVE -> DEMOBILIZING with zero outages
    (vacuous preconditions); a DRAFT claim on it."""
    set_clock(clock_iso)
    ev = create_and_activate_event()
    ev = get_success_data(api_client.begin_demobilization(ev["id"], ED))
    claim = create_fema_claim(ev["id"], county_code="C1", threshold_cents=threshold_cents)
    return ev, claim


# --- Tier 8: outage verified (full restore pipeline) ----------------------------


def setup_verified_outage(
    customers_affected: int = 5,
    cause_code: str = "EQUIPMENT",
    estimated_repair_minutes: int = 10,
    clock_iso: str = "2026-08-10T00:00:00Z",
    restore_ping_occurred_at: str = "2026-08-10T00:00:00Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Carry an outage all the way to VERIFIED.

    Returns (event, feeder, outage, line_crew, work_order).
    """
    ev, fd, ot, cr_l, wo = setup_completed_work_order_scenario(
        customers_affected=customers_affected,
        cause_code=cause_code,
        estimated_repair_minutes=estimated_repair_minutes,
        clock_iso=clock_iso,
    )
    wo = get_success_data(
        api_client.verify_work_order(wo["id"], {"outcome": "PASSED"}, DISP)
    )
    ot = get_success_data(api_client.report_restored(ot["id"], DISP))
    # restore ping must be at/after restoration_reported_at
    get_success_data(
        api_client.create_trouble_signal(
            create_trouble_signal_payload(
                fd["id"],
                signal_type="METER_RESTORE_PING",
                occurred_at=restore_ping_occurred_at,
                outage_id=ot["id"],
            ),
            TG,
        )
    )
    ot = get_success_data(api_client.verify_outage(ot["id"], DISP))
    return ev, fd, ot, cr_l, wo
