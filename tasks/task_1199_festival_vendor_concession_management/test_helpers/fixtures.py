"""Composite setup helpers.

Each fixture builds a multi-step scenario (festival + zone + vendors +
applications + booths + assignments + sales + settlements, etc.) so tests can
focus on the trigger and the assertion. Internally they use
``get_success_data`` so a setup failure raises a clear "Setup failed" error
rather than a confusing downstream assertion.

Identity threading: the Vendor role is entity-backed, so every ownership-gated
call is made with ``make_vendor_headers(vendor["id"])`` — never with the shared
fallback constant.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AFTER_EVENT_END_ISO,
    DEFAULT_CLOCK_ISO,
    EVENT_END_ISO,
    EVENT_START_ISO,
    IN_WINDOW_SALE_ISO,
)
from .factories import (
    create_application_payload,
    create_assignment_payload,
    create_booth_payload,
    create_festival_payload,
    create_fine_payload,
    create_inspection_payload,
    create_reservation_payload,
    create_settlement_payload,
    create_slot_payload,
    create_transaction_payload,
    create_vendor_payload,
    create_zone_payload,
    curated_terms_payload,
    decide_payload,
)
from .test_users import TEST_USERS, make_vendor_headers

DIRECTOR = TEST_USERS["director_headers"]
DIRECTOR2 = TEST_USERS["director2_headers"]
VM = TEST_USERS["vendor_manager_headers"]
OPS = TEST_USERS["ops_headers"]
HI = TEST_USERS["health_inspector_headers"]
SUS = TEST_USERS["sustainability_headers"]
FIN1 = TEST_USERS["finance_headers"]      # fin-1 — default reconciler / fine collector
FIN2 = TEST_USERS["finance2_headers"]     # fin-2 — default finalizer (SoD-safe)


def _expect_ok(resp, label: str) -> Dict[str, Any]:
    """Lenient validator for setup calls — surfaces a clear message on failure."""
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {label}: {exc}") from exc


# ---------------------------------------------------------------------------
# Tier 0 — clock and atomic creators
# ---------------------------------------------------------------------------

def reset_clock() -> None:
    """Pin the logical clock to the documented server-startup default."""
    _expect_ok(api_client.set_clock({"to_iso8601": DEFAULT_CLOCK_ISO}, DIRECTOR), "reset_clock")


def set_clock(iso: str) -> Dict[str, Any]:
    return _expect_ok(api_client.set_clock({"to_iso8601": iso}, DIRECTOR), f"set_clock({iso})")


def create_festival(**overrides) -> Dict[str, Any]:
    resp = api_client.create_festival(create_festival_payload(**overrides), DIRECTOR)
    return _expect_ok(resp, "create_festival")


def create_zone(festival_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_zone(create_zone_payload(festival_id, **overrides), OPS)
    return _expect_ok(resp, "create_zone")


def create_booth(zone_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_booth(create_booth_payload(zone_id, **overrides), OPS)
    return _expect_ok(resp, "create_booth")


def create_vendor(**overrides) -> Dict[str, Any]:
    resp = api_client.create_vendor(create_vendor_payload(**overrides), VM)
    return _expect_ok(resp, "create_vendor")


def advance_festival(festival_id: str, to_status: str) -> Dict[str, Any]:
    resp = api_client.advance_festival_status(festival_id, {"to_status": to_status}, DIRECTOR)
    return _expect_ok(resp, f"advance_festival({to_status})")


def submit_application(vendor: Dict[str, Any], festival_id: str, **overrides) -> Dict[str, Any]:
    """Submit as the owning vendor (entity-backed identity threading)."""
    payload = create_application_payload(vendor["id"], festival_id, **overrides)
    resp = api_client.create_application(payload, make_vendor_headers(vendor["id"]))
    return _expect_ok(resp, "submit_application")


def start_review(application_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.start_review(application_id, VM), "start_review")


def request_changes(application_id: str, notes: Optional[str] = None) -> Dict[str, Any]:
    payload = {} if notes is None else {"notes": notes}
    return _expect_ok(api_client.request_changes(application_id, payload, VM), "request_changes")


def decide_application(application_id: str, decision: str = "ACCEPTED", **curated) -> Dict[str, Any]:
    resp = api_client.decide_application(application_id, decide_payload(decision, **curated), VM)
    return _expect_ok(resp, f"decide_application({decision})")


def accept_application(application_id: str, fee_model: str = "FLAT_FEE", **terms) -> Dict[str, Any]:
    """Decide ACCEPTED with a complete curated term set for the fee model."""
    curated = curated_terms_payload(fee_model, **terms)
    return decide_application(application_id, "ACCEPTED", **curated)


def withdraw_application(application_id: str, vendor: Dict[str, Any]) -> Dict[str, Any]:
    resp = api_client.withdraw_application(application_id, make_vendor_headers(vendor["id"]))
    return _expect_ok(resp, "withdraw_application")


def create_assignment(application_id: str, booth_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_assignment(create_assignment_payload(application_id, booth_id, **overrides), OPS)
    return _expect_ok(resp, "create_assignment")


def confirm_assignment(assignment_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.confirm_assignment(assignment_id, OPS), "confirm_assignment")


def provision_assignment(assignment_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.provision_utilities(assignment_id, OPS), "provision_assignment")


def record_inspection(assignment_id: str, type: str = "HEALTH_PREOPEN",
                      result: str = "PASS", notes: Optional[str] = None) -> Dict[str, Any]:
    payload = create_inspection_payload(assignment_id, type=type, result=result)
    if notes is not None:
        payload["notes"] = notes
    return _expect_ok(api_client.create_inspection(payload, HI), "record_inspection")


def activate_assignment(assignment_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.activate_assignment(assignment_id, OPS), "activate_assignment")


def release_assignment(assignment_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.release_assignment(assignment_id, OPS), "release_assignment")


def report_sale(assignment_id: str, vendor: Dict[str, Any], amount_cents: int,
                idempotency_key: str, occurred_at: str = IN_WINDOW_SALE_ISO) -> Dict[str, Any]:
    """Report a sale as the owning vendor (ownership-gated)."""
    payload = create_transaction_payload(
        assignment_id, amount_cents=amount_cents, occurred_at=occurred_at,
        idempotency_key=idempotency_key,
    )
    resp = api_client.create_transaction(payload, make_vendor_headers(vendor["id"]))
    return _expect_ok(resp, f"report_sale({amount_cents})")


def create_settlement(assignment_id: str, headers=None) -> Dict[str, Any]:
    resp = api_client.create_settlement(create_settlement_payload(assignment_id), headers or FIN1)
    return _expect_ok(resp, "create_settlement")


def reconcile_settlement(settlement_id: str, headers=None) -> Dict[str, Any]:
    resp = api_client.reconcile_settlement(settlement_id, headers or FIN1)
    return _expect_ok(resp, "reconcile_settlement")


def dispute_settlement(settlement_id: str, vendor: Dict[str, Any], reason: str) -> Dict[str, Any]:
    resp = api_client.dispute_settlement(settlement_id, {"reason": reason}, make_vendor_headers(vendor["id"]))
    return _expect_ok(resp, "dispute_settlement")


def finalize_settlement(settlement_id: str, headers=None) -> Dict[str, Any]:
    resp = api_client.finalize_settlement(settlement_id, headers or FIN2)
    return _expect_ok(resp, "finalize_settlement")


def mark_paid_settlement(settlement_id: str, headers=None) -> Dict[str, Any]:
    resp = api_client.mark_paid_settlement(settlement_id, headers or FIN1)
    return _expect_ok(resp, "mark_paid_settlement")


def issue_fine(assignment_id: str, type: str = "WASTE_SORTING", amount_cents: int = 10000,
               headers=None, description: Optional[str] = None) -> Dict[str, Any]:
    payload = create_fine_payload(assignment_id, type=type, amount_cents=amount_cents)
    if description is not None:
        payload["description"] = description
    resp = api_client.create_fine(payload, headers or SUS)
    return _expect_ok(resp, "issue_fine")


def respond_fine(fine_id: str, vendor: Dict[str, Any], response: str) -> Dict[str, Any]:
    resp = api_client.respond_fine(fine_id, {"response": response}, make_vendor_headers(vendor["id"]))
    return _expect_ok(resp, f"respond_fine({response})")


def pay_fine(fine_id: str, headers=None) -> Dict[str, Any]:
    resp = api_client.mark_paid_fine(fine_id, headers or FIN1)
    return _expect_ok(resp, "pay_fine")


def waive_fine(fine_id: str, headers=None) -> Dict[str, Any]:
    resp = api_client.waive_fine(fine_id, headers or DIRECTOR)
    return _expect_ok(resp, "waive_fine")


def create_slot(festival_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_slot(create_slot_payload(festival_id, **overrides), OPS)
    return _expect_ok(resp, "create_slot")


def book_reservation(assignment_id: str, slot_id: str, vehicle_count: int = 1, headers=None) -> Dict[str, Any]:
    payload = create_reservation_payload(assignment_id, slot_id, vehicle_count=vehicle_count)
    resp = api_client.create_reservation(payload, headers or OPS)
    return _expect_ok(resp, "book_reservation")


def sweep_festival(festival_id: str, headers=None) -> Dict[str, Any]:
    resp = api_client.sweep_operations(festival_id, headers or OPS)
    return _expect_ok(resp, "sweep_festival")


def get_assignment(assignment_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.get_assignment(assignment_id, OPS), "get_assignment")


def get_zone(zone_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.get_zone(zone_id, OPS), "get_zone")


def get_booth(booth_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.get_booth(booth_id, OPS), "get_booth")


def get_slot(slot_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.get_slot(slot_id, OPS), "get_slot")


def get_reservation(reservation_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.get_reservation(reservation_id, OPS), "get_reservation")


def get_application(application_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.get_application(application_id, VM), "get_application")


def get_vendor(vendor_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.get_vendor(vendor_id, VM), "get_vendor")


def get_transaction(transaction_id: str) -> Dict[str, Any]:
    return _expect_ok(api_client.get_transaction(transaction_id, FIN1), "get_transaction")


def get_review_for_assignment(assignment_id: str) -> Dict[str, Any]:
    """Return the single auto-created performance review for an assignment."""
    body = _expect_ok(
        api_client.list_reviews(VM, params={"assignment_id": assignment_id}),
        "list_reviews",
    )
    data = body if isinstance(body, list) else body.get("data", [])
    assert len(data) == 1, f"expected exactly 1 review for {assignment_id}, got {len(data)}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 1 — festival progression composites
# ---------------------------------------------------------------------------

def setup_open_festival(name: str = "Fest", cap: int = 2, zone_power: int = 100,
                        zone_water: int = 1, event_start: str = EVENT_START_ISO,
                        event_end: str = EVENT_END_ISO) -> Dict[str, Any]:
    """Clock reset -> festival -> zone -> APPLICATIONS_OPEN."""
    reset_clock()
    festival = create_festival(name=name, event_start=event_start, event_end=event_end,
                               category_cap_per_category=cap)
    zone = create_zone(festival["id"], power_capacity_amps=zone_power, water_hookup_total=zone_water)
    advance_festival(festival["id"], "APPLICATIONS_OPEN")
    return {"festival": festival, "zone": zone}


def setup_submitted_application(name: str = "Fest", category: str = "FOOD_HOT",
                                fee_model: str = "FLAT_FEE", **app_overrides) -> Dict[str, Any]:
    """Open festival + vendor + one SUBMITTED application."""
    base = setup_open_festival(name=name)
    vendor = create_vendor(legal_name=f"{name} Vendor LLC")
    app = submit_application(vendor, base["festival"]["id"], category=category,
                             fee_model=fee_model, **app_overrides)
    return {**base, "vendor": vendor, "app": app}


def setup_accepted_application(name: str = "Fest", category: str = "FOOD_HOT",
                               fee_model: str = "FLAT_FEE", terms: Optional[dict] = None,
                               **app_overrides) -> Dict[str, Any]:
    """Open festival + vendor + application driven SUBMITTED -> UNDER_REVIEW -> ACCEPTED.
    The festival remains APPLICATIONS_OPEN."""
    scen = setup_submitted_application(name=name, category=category, fee_model=fee_model, **app_overrides)
    start_review(scen["app"]["id"])
    app = accept_application(scen["app"]["id"], fee_model, **(terms or {}))
    scen["app"] = app
    return scen


def setup_curated_with_booth(name: str = "Fest", category: str = "FOOD_HOT",
                             fee_model: str = "FLAT_FEE", terms: Optional[dict] = None,
                             booth_overrides: Optional[dict] = None,
                             **app_overrides) -> Dict[str, Any]:
    """Accepted application + festival CURATED + one booth."""
    scen = setup_accepted_application(name=name, category=category, fee_model=fee_model,
                                      terms=terms, **app_overrides)
    advance_festival(scen["festival"]["id"], "CURATED")
    booth = create_booth(scen["zone"]["id"], **(booth_overrides or {}))
    scen["booth"] = booth
    return scen


def setup_reserved_assignment(name: str = "Fest", draw: int = 20, water: bool = False,
                              **kwargs) -> Dict[str, Any]:
    """CURATED festival + RESERVED assignment."""
    scen = setup_curated_with_booth(name=name, **kwargs)
    asg = create_assignment(scen["app"]["id"], scen["booth"]["id"],
                            power_draw_amps=draw, requires_water=water)
    scen["assignment"] = asg
    return scen


def setup_confirmed_assignment(name: str = "Fest", draw: int = 20, water: bool = False,
                               **kwargs) -> Dict[str, Any]:
    """CURATED festival + CONFIRMED assignment (fee snapshot pinned)."""
    scen = setup_reserved_assignment(name=name, draw=draw, water=water, **kwargs)
    scen["assignment"] = confirm_assignment(scen["assignment"]["id"])
    return scen


def setup_active_assignment(name: str = "Fest", draw: int = 20, water: bool = False,
                            **kwargs) -> Dict[str, Any]:
    """Full chain: CONFIRMED + PROVISIONED + HEALTH_PREOPEN PASS + festival LIVE + ACTIVE."""
    scen = setup_confirmed_assignment(name=name, draw=draw, water=water, **kwargs)
    asg_id = scen["assignment"]["id"]
    provision_assignment(asg_id)
    record_inspection(asg_id, "HEALTH_PREOPEN", "PASS")
    set_clock(scen["festival"]["event_start"])
    advance_festival(scen["festival"]["id"], "LIVE")
    scen["assignment"] = activate_assignment(asg_id)
    return scen


# ---------------------------------------------------------------------------
# Tier 2 — multi-vendor festival driver (shared by settlement / review tests)
# ---------------------------------------------------------------------------

def make_vendor_spec(legal_name: str, category: str, fee_model: str = "FLAT_FEE",
                     flat_fee_cents: int = 50000, revenue_share_pct_bp: int = 1000,
                     tier_mode: str = "MARGINAL", minimum_guarantee_cents: int = 100000,
                     free_allowance_cents: int = 150000, power_needed_amps: int = 20,
                     requires_water: bool = False, power_draw_amps: int = 20,
                     booth_label: Optional[str] = None, booth_outlet_amps: int = 60,
                     booth_water: bool = False, decision: str = "ACCEPTED") -> Dict[str, Any]:
    """Declarative per-vendor spec consumed by the multi-vendor drivers."""
    return {
        "legal_name": legal_name, "category": category, "fee_model": fee_model,
        "flat_fee_cents": flat_fee_cents, "revenue_share_pct_bp": revenue_share_pct_bp,
        "tier_mode": tier_mode, "minimum_guarantee_cents": minimum_guarantee_cents,
        "free_allowance_cents": free_allowance_cents, "power_needed_amps": power_needed_amps,
        "requires_water": requires_water, "power_draw_amps": power_draw_amps,
        "booth_label": booth_label, "booth_outlet_amps": booth_outlet_amps,
        "booth_water": booth_water, "decision": decision,
    }


def setup_curated_multi(vendor_specs: List[Dict[str, Any]], name: str = "Multi Fest",
                        cap: int = 2, zone_power: int = 300, zone_water: int = 4) -> Dict[str, Any]:
    """Festival -> zone -> APPLICATIONS_OPEN -> vendors+applications decided per spec
    -> CURATED -> one booth per ACCEPTED application -> one RESERVED assignment each
    -> confirm all. Returns aligned lists."""
    base = setup_open_festival(name=name, cap=cap, zone_power=zone_power, zone_water=zone_water)
    vendors, apps = [], []
    for i, spec in enumerate(vendor_specs):
        vendor = create_vendor(legal_name=spec["legal_name"],
                               contact_email=f"v{i}@{spec['legal_name'].replace(' ', '').lower()}.com")
        app = submit_application(
            vendor, base["festival"]["id"], category=spec["category"],
            fee_model=spec["fee_model"], power_needed_amps=spec["power_needed_amps"],
            requires_water=spec["requires_water"],
            proposed_flat_fee_cents=spec["flat_fee_cents"],
            proposed_revenue_share_pct_bp=spec["revenue_share_pct_bp"],
        )
        start_review(app["id"])
        if spec["decision"] == "ACCEPTED":
            app = accept_application(
                app["id"], spec["fee_model"], flat_fee_cents=spec["flat_fee_cents"],
                revenue_share_pct_bp=spec["revenue_share_pct_bp"], tier_mode=spec["tier_mode"],
                minimum_guarantee_cents=spec["minimum_guarantee_cents"],
                free_allowance_cents=spec["free_allowance_cents"],
            )
        else:
            app = decide_application(app["id"], spec["decision"])
        vendors.append(vendor)
        apps.append(app)
    advance_festival(base["festival"]["id"], "CURATED")
    booths, assignments = [], []
    for i, (spec, app) in enumerate(zip(vendor_specs, apps)):
        if spec["decision"] != "ACCEPTED":
            booths.append(None)
            assignments.append(None)
            continue
        booth = create_booth(base["zone"]["id"], label=spec["booth_label"] or f"N-{i + 1:02d}",
                             power_outlet_max_amps=spec["booth_outlet_amps"],
                             has_water_hookup=spec["booth_water"])
        asg = create_assignment(app["id"], booth["id"], power_draw_amps=spec["power_draw_amps"],
                                requires_water=spec["requires_water"])
        asg = confirm_assignment(asg["id"])
        booths.append(booth)
        assignments.append(asg)
    return {**base, "vendors": vendors, "apps": apps, "booths": booths, "assignments": assignments}


def setup_live_multi(vendor_specs: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
    """setup_curated_multi + provision + PASS inspection + clock to event_start + LIVE + activate."""
    scen = setup_curated_multi(vendor_specs, **kwargs)
    for asg in scen["assignments"]:
        if asg is None:
            continue
        provision_assignment(asg["id"])
        record_inspection(asg["id"], "HEALTH_PREOPEN", "PASS")
    set_clock(scen["festival"]["event_start"])
    advance_festival(scen["festival"]["id"], "LIVE")
    for i, asg in enumerate(scen["assignments"]):
        if asg is not None:
            scen["assignments"][i] = activate_assignment(asg["id"])
    return scen


def report_sales(scen: Dict[str, Any], sales: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
    """Report sales per assignment index. Each entry is a list of
    {amount_cents, occurred_at?, key} dicts reported as the owning vendor."""
    all_txns: List[List[Dict[str, Any]]] = []
    for i, sale_list in enumerate(sales):
        txns = []
        for sale in sale_list:
            txns.append(report_sale(
                scen["assignments"][i]["id"], scen["vendors"][i],
                sale["amount_cents"], sale.get("key", f"sale-{i}-{len(txns)}"),
                sale.get("occurred_at", IN_WINDOW_SALE_ISO),
            ))
        all_txns.append(txns)
    return all_txns


def open_settlements(scen: Dict[str, Any], indices: Optional[List[int]] = None) -> List[Optional[Dict[str, Any]]]:
    """Create (OPEN) one settlement per requested assignment index (default: all ACTIVE)."""
    settlements: List[Optional[Dict[str, Any]]] = [None] * len(scen["assignments"])
    for i, asg in enumerate(scen["assignments"]):
        if asg is None or (indices is not None and i not in indices):
            continue
        settlements[i] = create_settlement(asg["id"])
    scen["settlements"] = settlements
    return settlements


def reconcile_all(scen: Dict[str, Any], headers=None) -> None:
    for stl in scen.get("settlements", []):
        if stl is not None:
            reconcile_settlement(stl["id"], headers=headers)


def move_to_settlement_phase(scen: Dict[str, Any]) -> None:
    """Clock strictly past event_end, then advance LIVE -> SETTLEMENT
    (ACTIVE assignments complete; zone reservations drain)."""
    set_clock(AFTER_EVENT_END_ISO)
    advance_festival(scen["festival"]["id"], "SETTLEMENT")


def finalize_all(scen: Dict[str, Any], headers=None) -> None:
    for i, stl in enumerate(scen.get("settlements", [])):
        if stl is not None:
            scen["settlements"][i] = finalize_settlement(stl["id"], headers=headers)


def setup_finalized_multi(vendor_specs: List[Dict[str, Any]],
                          sales: List[List[Dict[str, Any]]], **kwargs) -> Dict[str, Any]:
    """Full lifecycle: LIVE + ACTIVE assignments + sales + settlements reconciled
    (fin-1) -> SETTLEMENT phase -> all finalized (fin-2). Reviews auto-created."""
    scen = setup_live_multi(vendor_specs, **kwargs)
    scen["transactions"] = report_sales(scen, sales)
    open_settlements(scen)
    reconcile_all(scen)
    move_to_settlement_phase(scen)
    finalize_all(scen)
    return scen


# ---------------------------------------------------------------------------
# Tier 3 — single-assignment settlement shortcut
# ---------------------------------------------------------------------------

def setup_reconciled_settlement(sale_amounts: Optional[List[int]] = None,
                                fee_model: str = "FLAT_FEE", terms: Optional[dict] = None,
                                name: str = "Settle Fest") -> Dict[str, Any]:
    """ACTIVE assignment + REPORTED sales + settlement created (fin-1) and
    reconciled (fin-1). Festival is LIVE."""
    scen = setup_active_assignment(name=name, fee_model=fee_model, terms=terms)
    asg_id = scen["assignment"]["id"]
    txns = [report_sale(asg_id, scen["vendor"], amount, f"{name}-sale-{i}")
            for i, amount in enumerate(sale_amounts or [100000])]
    settlement = create_settlement(asg_id)
    settlement = reconcile_settlement(settlement["id"])
    scen.update({"transactions": txns, "settlement": settlement})
    return scen


def setup_finalized_settlement(sale_amounts: Optional[List[int]] = None,
                               fee_model: str = "FLAT_FEE", terms: Optional[dict] = None,
                               name: str = "Final Fest") -> Dict[str, Any]:
    """Reconciled settlement + festival SETTLEMENT phase + finalize (fin-2)."""
    scen = setup_reconciled_settlement(sale_amounts=sale_amounts, fee_model=fee_model,
                                       terms=terms, name=name)
    move_to_settlement_phase(scen)
    scen["settlement"] = finalize_settlement(scen["settlement"]["id"])
    return scen
