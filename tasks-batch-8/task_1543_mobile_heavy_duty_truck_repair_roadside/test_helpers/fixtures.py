"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use get_success_data() so a broken
precondition surfaces as a clear setup failure rather than a confusing
assertion error deep inside a test.

Identity threading: Technician calls are entity-backed by Technician and
FleetManager calls are entity-backed by FleetAccount. Every context dict
carries per-instance headers built from the real entity ids via the make_*
builders; ownership-gated calls never fall back to the shared constants.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import S1_TOTAL_CENTS
from .factories import (
    create_dispatch_payload,
    create_estimate_payload,
    create_fleet_account_payload,
    create_inspection_defect_payload,
    create_part_usage_payload,
    create_rate_card_payload,
    create_repeat_failure_case_payload,
    create_service_call_payload,
    create_technician_payload,
    create_tow_order_payload,
    create_van_stock_payload,
    create_vehicle_payload,
    create_warranty_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_fleet_manager_headers,
    make_technician_headers,
)

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
WARRANTY_ADMIN = TEST_USERS["warranty_admin_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]

# Unique suffixes for VINs / employee codes / account numbers within a test.
_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


# ---------------------------------------------------------------------------
# Logical clock and daily ops run
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601: str):
    """Advance the logical clock (forward only)."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


def run_daily():
    """Run the daily ops checkpoint; returns the four reported counts."""
    return get_success_data(api_client.run_daily(OPS))


# ---------------------------------------------------------------------------
# Tier 1: master data
# ---------------------------------------------------------------------------

def create_standard_rate_card(**overrides):
    """Publish the canonical STD-2026 rate card. Returns the RateCard."""
    payload = create_rate_card_payload(**overrides)
    return get_success_data(api_client.create_rate_card(payload, OPS))


def create_fleet(per_call_authorization_limit_cents=100000,
                 monthly_spend_cap_cents=500000, rate_card_id=None,
                 payment_terms_days=None, account_number=None):
    """Create an ACTIVE fleet account. Returns the FleetAccount."""
    n = _next()
    payload = create_fleet_account_payload(
        account_number=account_number or f"ACCT-{1000 + n}",
        company_name=f"HaulCo-{n}",
        billing_email=f"ap-{n}@haulco.example",
        per_call_authorization_limit_cents=per_call_authorization_limit_cents,
        monthly_spend_cap_cents=monthly_spend_cap_cents,
    )
    if rate_card_id is not None:
        payload["rate_card_id"] = rate_card_id
    if payment_terms_days is not None:
        payload["payment_terms_days"] = payment_terms_days
    return get_success_data(api_client.create_fleet_account(payload, OPS))


def adjust_fleet_spend(fleet_account_id, amount_cents, reason="true-up"):
    """Post a signed spend adjustment; returns the updated FleetAccount."""
    return get_success_data(api_client.post_spend_adjustment(
        fleet_account_id, {"amount_cents": amount_cents, "reason": reason},
        BILLING))


def create_vehicle(fleet_account_id=None, odometer_miles=90000, vin=None,
                   extended_warranty=None, oem_warranty_expires_at=None,
                   oem_warranty_miles_limit=None, unit_number=None,
                   year=2020):
    """Register a vehicle (retail when fleet_account_id is None)."""
    n = _next()
    payload = create_vehicle_payload(
        vin=vin or f"1FUJHHDR1LLLW{n:04d}",
        unit_number=unit_number or f"R-{n:02d}",
        odometer_miles=odometer_miles,
        year=year,
    )
    if fleet_account_id is not None:
        payload["fleet_account_id"] = fleet_account_id
    if extended_warranty is not None:
        payload["extended_warranty"] = extended_warranty
    if oem_warranty_expires_at is not None:
        payload["oem_warranty_expires_at"] = oem_warranty_expires_at
    if oem_warranty_miles_limit is not None:
        payload["oem_warranty_miles_limit"] = oem_warranty_miles_limit
    return get_success_data(api_client.create_vehicle(payload, DISPATCHER))


def create_technician(certifications=("ENGINE",), labor_rate_class="STANDARD",
                      available=True, full_name=None, employee_code=None):
    """Onboard a technician (OFF_DUTY; AVAILABLE when available=True).

    Returns (technician_dict, technician_headers) with headers pinned to the
    real technician id for ownership-gated calls.
    """
    n = _next()
    payload = create_technician_payload(
        full_name=full_name or f"Tech {n}",
        employee_code=employee_code or f"T-{100 + n}",
        certifications=list(certifications),
        labor_rate_class=labor_rate_class,
    )
    tech = get_success_data(api_client.create_technician(payload, OPS))
    headers = make_technician_headers(tech["id"])
    if available:
        tech = get_success_data(api_client.set_technician_status(
            tech["id"], {"to_status": "AVAILABLE"}, headers))
    return tech, headers


def stock_van(technician_id, part_number="ALT-104", part_class="ENGINE",
              qty_on_hand=10, unit_cost_cents=21000, unit_retail_cents=34999,
              reorder_point=None, description=None):
    """Stock a part on a technician's van. Returns the VanStockItem."""
    payload = create_van_stock_payload(
        part_number=part_number,
        part_class=part_class,
        qty_on_hand=qty_on_hand,
        unit_cost_cents=unit_cost_cents,
        unit_retail_cents=unit_retail_cents,
    )
    if description is not None:
        payload["description"] = description
    if reorder_point is not None:
        payload["reorder_point"] = reorder_point
    return get_success_data(
        api_client.create_van_stock_item(technician_id, payload, OPS))


# ---------------------------------------------------------------------------
# Tier 2: service-call lifecycle steps
# ---------------------------------------------------------------------------

def intake_call(vehicle_id, symptom_category="ENGINE_NO_START", received_at=None,
                headers=None, **overrides):
    """Intake a service call (status RECEIVED). When received_at is given, the
    logical clock is advanced there first so the intake stamps it."""
    if received_at is not None:
        advance_clock(received_at)
    payload = create_service_call_payload(vehicle_id,
                                          symptom_category=symptom_category,
                                          **overrides)
    return get_success_data(
        api_client.create_service_call(payload, headers or DISPATCHER))


def triage_call(service_call_id, severity="DRIVABLE", headers=None,
                symptom_category=None):
    """Triage a RECEIVED call; returns the TRIAGED call."""
    payload = {"severity": severity}
    if symptom_category is not None:
        payload["symptom_category"] = symptom_category
    return get_success_data(api_client.triage_service_call(
        service_call_id, payload, headers or DISPATCHER))


def open_triaged_call(vehicle_id, symptom_category="ENGINE_NO_START",
                      severity="DRIVABLE", received_at=None, **overrides):
    """Intake + triage. Returns the TRIAGED call."""
    call = intake_call(vehicle_id, symptom_category=symptom_category,
                       received_at=received_at, **overrides)
    return triage_call(call["id"], severity=severity)


def get_call(service_call_id, headers=None):
    return get_success_data(
        api_client.get_service_call(service_call_id, headers or DISPATCHER))


def create_dispatch(service_call_id, technician_id, window_start_at,
                    window_end_at, planned_travel_miles=20, headers=None):
    """Propose a dispatch on a TRIAGED call (OCC version refetched)."""
    call = get_call(service_call_id, headers)
    payload = create_dispatch_payload(
        technician_id, call["version"],
        window_start_at=window_start_at, window_end_at=window_end_at,
        planned_travel_miles=planned_travel_miles)
    return get_success_data(
        api_client.create_dispatch(service_call_id, payload,
                                   headers or DISPATCHER))


def accept_dispatch(dispatch_id, tech_headers):
    return get_success_data(api_client.accept_dispatch(dispatch_id, tech_headers))


def depart_dispatch(dispatch_id, tech_headers, at=None):
    if at is not None:
        advance_clock(at)
    return get_success_data(api_client.depart_dispatch(dispatch_id, tech_headers))


def arrive_dispatch(dispatch_id, tech_headers, actual_travel_miles, at=None):
    if at is not None:
        advance_clock(at)
    return get_success_data(api_client.arrive_dispatch(
        dispatch_id, {"actual_travel_miles": actual_travel_miles}, tech_headers))


def complete_dispatch(dispatch_id, tech_headers):
    return get_success_data(api_client.complete_dispatch(dispatch_id,
                                                         tech_headers))


def diagnose_call(service_call_id, tech_headers,
                  diagnosis_summary="diagnosed on site",
                  resolution_path="ON_SITE_REPAIR"):
    return get_success_data(api_client.diagnose_service_call(
        service_call_id,
        {"diagnosis_summary": diagnosis_summary,
         "resolution_path": resolution_path},
        tech_headers))


def drive_call_on_site(call, technician_id, tech_headers, window_start_at,
                       window_end_at, planned_travel_miles=20,
                       accept_at=None, depart_at=None, arrive_at=None,
                       actual_travel_miles=20):
    """Dispatch -> accept -> depart -> arrive. Returns (call, dispatch).

    The optional *_at arguments advance the logical clock before the
    corresponding step so audit-trail timestamps can be spread deterministically.
    """
    dispatch = create_dispatch(call["id"], technician_id, window_start_at,
                               window_end_at,
                               planned_travel_miles=planned_travel_miles)
    if accept_at is not None:
        advance_clock(accept_at)
    accept_dispatch(dispatch["id"], tech_headers)
    depart_dispatch(dispatch["id"], tech_headers, at=depart_at)
    dispatch = arrive_dispatch(dispatch["id"], tech_headers,
                               actual_travel_miles, at=arrive_at)
    return get_call(call["id"]), dispatch


def create_estimate(service_call_id, labor_hours_est=1.0, travel_miles_est=20,
                    parts_estimate_cents=30000, includes_tow=None,
                    tow_estimate_cents=None, headers=None):
    """Create an estimate (OCC version refetched). Returns the DRAFT estimate."""
    call = get_call(service_call_id, headers)
    payload = create_estimate_payload(
        call["version"],
        labor_hours_est=labor_hours_est,
        travel_miles_est=travel_miles_est,
        parts_estimate_cents=parts_estimate_cents,
    )
    if includes_tow is not None:
        payload["includes_tow"] = includes_tow
    if tow_estimate_cents is not None:
        payload["tow_estimate_cents"] = tow_estimate_cents
    return get_success_data(api_client.create_estimate(
        service_call_id, payload, headers or DISPATCHER))


def submit_estimate(estimate_id, headers=None):
    return get_success_data(
        api_client.submit_estimate(estimate_id, headers or DISPATCHER))


def approve_estimate(estimate_id, headers, payload=None):
    return get_success_data(
        api_client.approve_estimate(estimate_id, payload or {}, headers))


def start_repair(service_call_id, tech_headers):
    return get_success_data(api_client.start_repair(service_call_id,
                                                    tech_headers))


def post_part_usage(service_call_id, tech_headers, van_stock_item_id, qty,
                    charge_type=None):
    payload = create_part_usage_payload(van_stock_item_id, qty=qty)
    if charge_type is not None:
        payload["charge_type"] = charge_type
    return get_success_data(
        api_client.create_part_usage(service_call_id, payload, tech_headers))


def complete_repair(service_call_id, tech_headers, labor_hours_actual,
                    completion_odometer_miles, at=None):
    if at is not None:
        advance_clock(at)
    return get_success_data(api_client.complete_repair(
        service_call_id,
        {"labor_hours_actual": labor_hours_actual,
         "completion_odometer_miles": completion_odometer_miles},
        tech_headers))


def order_tow(service_call_id, headers=None, **overrides):
    payload = create_tow_order_payload(**overrides)
    return get_success_data(
        api_client.create_tow_order(service_call_id, payload,
                                    headers or DISPATCHER))


# ---------------------------------------------------------------------------
# Tier 3: full on-site repair lifecycle
# ---------------------------------------------------------------------------

def run_on_site_repair(vehicle_id, technician_id, tech_headers,
                       severity="DRIVABLE",
                       symptom_category="ENGINE_NO_START",
                       received_at="2026-08-03T13:30:00Z",
                       window=("2026-08-03T13:30:00Z", "2026-08-03T18:30:00Z"),
                       depart_at="2026-08-03T14:00:00Z",
                       arrive_at="2026-08-03T15:35:00Z",
                       actual_travel_miles=40,
                       planned_travel_miles=40,
                       labor_hours_actual=2.5,
                       completion_odometer_miles=120450,
                       parts=(),
                       estimate=None,
                       diagnosis_summary="alternator failed",
                       complete_the_dispatch=True,
                       **intake_overrides):
    """Drive a call from intake all the way to REPAIR_COMPLETED.

    parts: list of dicts {item_id, qty, charge_type?} posted while the repair
    is in progress. estimate: optional dict of estimate inputs plus optional
    'approve_headers' — the estimate is created, submitted, and (when
    approve_headers is given) approved before start-repair.
    Extra keyword arguments are passed through to intake (e.g.
    symptom_description, breakdown_location_text).
    Returns a ctx dict with the final call, dispatch, usages, estimate.
    """
    call = open_triaged_call(vehicle_id, symptom_category=symptom_category,
                             severity=severity, received_at=received_at,
                             distance_miles_from_depot=planned_travel_miles,
                             **intake_overrides)
    call, dispatch = drive_call_on_site(
        call, technician_id, tech_headers, window[0], window[1],
        planned_travel_miles=planned_travel_miles, depart_at=depart_at,
        arrive_at=arrive_at, actual_travel_miles=actual_travel_miles)
    call = diagnose_call(call["id"], tech_headers,
                         diagnosis_summary=diagnosis_summary)
    estimate = None
    if estimate is not None:
        est = dict(estimate)
        approve_headers = est.pop("approve_headers", None)
        estimate = create_estimate(call["id"], headers=tech_headers, **est)
        submit_estimate(estimate["id"], headers=tech_headers)
        if approve_headers is not None:
            estimate = approve_estimate(estimate["id"], approve_headers)
    call = start_repair(call["id"], tech_headers)
    usages = []
    for part in parts:
        usages.append(post_part_usage(call["id"], tech_headers,
                                      part["item_id"], part["qty"],
                                      charge_type=part.get("charge_type")))
    call = complete_repair(call["id"], tech_headers, labor_hours_actual,
                           completion_odometer_miles)
    if complete_the_dispatch:
        complete_dispatch(dispatch["id"], tech_headers)
    return {
        "call": call,
        "dispatch": dispatch,
        "estimate": estimate,
        "usages": usages,
    }


# ---------------------------------------------------------------------------
# Tier 3b: canonical "S1" job — business-hours DRIVABLE alternator repair,
# 2.5h STANDARD labor, 40 actual one-way miles, 95 travel minutes,
# 2x ALT-104 @ 34999. Invoice total is 136698 for a STANDARD-tier customer.
# ---------------------------------------------------------------------------

def setup_s1_completed_job(fleet=None, warranty_vehicle=False,
                           odometer_miles=120000):
    """Canonical S1 job driven to REPAIR_COMPLETED. Returns ctx with rc, fa,
    veh, tech, tech_headers, stock, and the run_on_site_repair ctx."""
    rc = create_standard_rate_card()
    fa = fleet
    veh_kwargs = {}
    if warranty_vehicle:
        veh_kwargs = {"oem_warranty_expires_at": "2027-06-01T00:00:00Z",
                      "oem_warranty_miles_limit": 200000}
    veh = create_vehicle(fleet_account_id=fa["id"] if fa else None,
                         odometer_miles=odometer_miles, **veh_kwargs)
    tech, tech_headers = create_technician()
    stock = stock_van(tech["id"], qty_on_hand=10)
    ctx = run_on_site_repair(
        veh["id"], tech["id"], tech_headers,
        parts=[{"item_id": stock["id"], "qty": 2}])
    return {"rc": rc, "fa": fa, "veh": veh, "tech": tech,
            "tech_headers": tech_headers, "stock": stock, **ctx}


def create_invoice_for_call(service_call_id):
    return get_success_data(api_client.create_invoice(service_call_id, BILLING))


def issue_invoice(invoice_id, headers=None):
    return get_success_data(
        api_client.issue_invoice(invoice_id, headers or BILLING))


def setup_s1_issued_invoice(fleet=None, issue_headers=None):
    """Canonical S1 job through invoice creation and issue. Returns ctx with
    the invoice added."""
    ctx = setup_s1_completed_job(fleet=fleet)
    invoice = create_invoice_for_call(ctx["call"]["id"])
    assert invoice["total_cents"] == S1_TOTAL_CENTS, (
        f"canonical job must price at {S1_TOTAL_CENTS}, got "
        f"{invoice['total_cents']}")
    invoice = issue_invoice(invoice["id"], headers=issue_headers)
    ctx["invoice"] = invoice
    return ctx


def post_payment(invoice_id, amount_cents, method="CARD", headers=None):
    return get_success_data(api_client.post_payment(
        invoice_id, {"amount_cents": amount_cents, "method": method},
        headers or BILLING))


def void_payment(payment_id, reason="reversed", headers=None):
    return get_success_data(api_client.void_payment(
        payment_id, {"reason": reason}, headers or BILLING))


def repair_existing_call(call_id, technician_id, tech_headers,
                         window, depart_at=None, arrive_at=None,
                         actual_travel_miles=35, planned_travel_miles=35,
                         labor_hours_actual=1.5,
                         completion_odometer_miles=120760,
                         parts=(), diagnosis_summary="repaired on site"):
    """Drive an ALREADY-TRIAGED call (e.g., a confirmed comeback's new call)
    through dispatch -> on-site -> diagnose -> start-repair -> parts ->
    REPAIR_COMPLETED. Returns ctx dict."""
    call = get_call(call_id)
    call, dispatch = drive_call_on_site(
        call, technician_id, tech_headers, window[0], window[1],
        planned_travel_miles=planned_travel_miles, depart_at=depart_at,
        arrive_at=arrive_at, actual_travel_miles=actual_travel_miles)
    call = diagnose_call(call["id"], tech_headers,
                         diagnosis_summary=diagnosis_summary)
    call = start_repair(call["id"], tech_headers)
    usages = []
    for part in parts:
        usages.append(post_part_usage(call["id"], tech_headers,
                                      part["item_id"], part["qty"],
                                      charge_type=part.get("charge_type")))
    call = complete_repair(call["id"], tech_headers, labor_hours_actual,
                           completion_odometer_miles)
    return {"call": call, "dispatch": dispatch, "usages": usages}


# ---------------------------------------------------------------------------
# Tier 4: warranty claims
# ---------------------------------------------------------------------------

def file_warranty_claim(service_call_id, filer_headers, claim_type="OEM_BASE",
                        oem_labor_hours=1.8, oem_labor_rate_cents=12000,
                        parts_at_cost_cents=42000):
    payload = create_warranty_claim_payload(
        claim_type=claim_type, oem_labor_hours=oem_labor_hours,
        oem_labor_rate_cents=oem_labor_rate_cents,
        parts_at_cost_cents=parts_at_cost_cents)
    return get_success_data(
        api_client.create_warranty_claim(service_call_id, payload,
                                         filer_headers))


def submit_claim(claim_id):
    return get_success_data(api_client.submit_warranty_claim(claim_id,
                                                             WARRANTY_ADMIN))


def decide_claim(claim_id, decision, denial_reason=None):
    payload = {"decision": decision}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(
        api_client.decide_warranty_claim(claim_id, payload, WARRANTY_ADMIN))


def appeal_claim(claim_id):
    return get_success_data(
        api_client.appeal_warranty_claim(claim_id, DISPATCHER))


# ---------------------------------------------------------------------------
# Tier 4b: inspection defects
# ---------------------------------------------------------------------------

def file_defect(vehicle_id, severity="OOS", source="ROADSIDE_DOT_INSPECTION",
                defect_code="393.9", discovered_at="2026-08-05T08:00:00Z",
                citation_reference=None):
    payload = create_inspection_defect_payload(
        source=source, defect_code=defect_code, severity=severity,
        discovered_at=discovered_at)
    if citation_reference is not None:
        payload["citation_reference"] = citation_reference
    return get_success_data(
        api_client.create_inspection_defect(vehicle_id, payload, SAFETY))


def attach_defect_call(defect_id, service_call_id):
    return get_success_data(api_client.attach_defect_call(
        defect_id, {"service_call_id": service_call_id}, SAFETY))


def mark_defect_corrected(defect_id, tech_headers,
                          correction_note="repaired"):
    return get_success_data(api_client.mark_defect_corrected(
        defect_id, {"correction_note": correction_note}, tech_headers))


def verify_defect(defect_id, outcome):
    payload = {"outcome": outcome}
    return get_success_data(api_client.verify_defect(defect_id, payload, SAFETY))


# ---------------------------------------------------------------------------
# Tier 5: repeat-failure cases and the closed -> reopened -> closed cycle
# ---------------------------------------------------------------------------

def open_repeat_failure_case(vehicle_id, original_service_call_id,
                             new_service_call_id):
    payload = create_repeat_failure_case_payload(
        vehicle_id, original_service_call_id, new_service_call_id)
    return get_success_data(
        api_client.create_repeat_failure_case(payload, DISPATCHER))


def setup_closed_original_call(odometer_miles=120000):
    """Canonical S1 retail job taken through invoice issue and full payment so
    the call is CLOSED. Returns the completed-job ctx."""
    ctx = setup_s1_issued_invoice(fleet=None)
    post_payment(ctx["invoice"]["id"], ctx["invoice"]["total_cents"],
                 method="CARD")
    ctx["call"] = get_call(ctx["call"]["id"])
    assert ctx["call"]["status"] == "CLOSED", (
        "setup: full payment must close the call")
    return ctx


def setup_confirmed_comeback(original_ctx, new_received_at, vehicle_odometer,
                             new_distance_miles=35):
    """Open + review + confirm a repeat-failure case for a fresh complaint call
    on the original job's vehicle. Returns (new_call, case)."""
    veh_id = original_ctx["veh"]["id"]
    get_success_data(api_client.patch_vehicle(
        veh_id, {"odometer_miles": vehicle_odometer}, DISPATCHER))
    new_call = open_triaged_call(
        veh_id, symptom_category=original_ctx["call"]["symptom_category"],
        severity="DRIVABLE", received_at=new_received_at,
        distance_miles_from_depot=new_distance_miles,
        breakdown_location_text="I-70 mm 300",
        symptom_description="no start again")
    case = open_repeat_failure_case(veh_id, original_ctx["call"]["id"],
                                    new_call["id"])
    get_success_data(api_client.review_repeat_failure_case(case["id"],
                                                           DISPATCHER))
    case = get_success_data(api_client.decide_repeat_failure_case(
        case["id"], {"decision": "CONFIRMED_COMEBACK",
                     "decision_note": "same failure"}, OPS))
    return new_call, case


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------

def list_restock_requests_for_item(van_stock_item_id):
    data, _meta = validate_paginated(api_client.list_restock_requests(
        OPS, params={"van_stock_item_id": van_stock_item_id}))
    return data


def make_fleet_manager(fleet):
    """Per-instance FleetManager headers pinned to the fleet's real id."""
    return make_fleet_manager_headers(fleet["id"])
