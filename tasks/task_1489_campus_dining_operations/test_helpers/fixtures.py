"""Composite setup helpers.

Every test starts against an empty database, so these helpers build complete
precondition chains (hall -> published cycle -> period -> forecast -> service
-> reconciliation; department -> catering order lifecycle; inspection ->
corrective actions) out of PRD-declared endpoints only.

Identity threading: DepartmentUser is entity-backed by Department, so every
ownership-gated call uses make_department_user_headers(department["id"]).
Waste segregation-of-duties is exercised with explicit per-user headers.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_accommodation_payload,
    create_catering_order_payload,
    create_department_payload,
    create_dining_hall_payload,
    create_forecast_payload,
    create_inspection_report_payload,
    create_labor_shift_payload,
    create_meal_period_payload,
    create_menu_cycle_payload,
    create_recipe_payload,
    create_vendor_contract_payload,
    create_waste_log_payload,
    swipe_event_entry,
)
from .test_users import (
    TEST_USERS,
    make_department_user_headers,
    make_hall_manager_headers,
    make_health_inspector_headers,
    make_kitchen_lead_headers,
)

ADMIN = TEST_USERS["dining_admin_headers"]
HALL_MANAGER = TEST_USERS["hall_manager_headers"]
KITCHEN_LEAD = TEST_USERS["kitchen_lead_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]
INSPECTOR = TEST_USERS["health_inspector_headers"]
CONTRACT_MANAGER = TEST_USERS["contract_manager_headers"]

DEFAULT_CYCLE_START = "2026-07-01"
DEFAULT_CYCLE_END = "2026-10-01"


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators and readers
# ---------------------------------------------------------------------------

def create_hall(name="Test Hall", service_model="BOARD", dining_capacity=800,
                catering_kitchen_capacity=500):
    resp = api_client.create_dining_hall(
        create_dining_hall_payload(
            name=name, service_model=service_model, dining_capacity=dining_capacity,
            catering_kitchen_capacity=catering_kitchen_capacity), ADMIN)
    return get_success_data(resp)


def get_hall(hall_id):
    return get_success_data(api_client.get_dining_hall(hall_id, ADMIN))


def suspend_hall(hall_id):
    return get_success_data(api_client.suspend_dining_hall(hall_id, ADMIN))


def reactivate_hall(hall_id):
    return get_success_data(api_client.reactivate_dining_hall(hall_id, ADMIN))


def create_recipe(hall_id, name="Test Recipe", station="GLOBAL", allergen_tags=None,
                  dietary_flags=None, popularity_share=0.5, unit_cost_cents=500,
                  allergen_reviewed=True):
    payload = create_recipe_payload(
        hall_id, name=name, station=station,
        allergen_tags=allergen_tags if allergen_tags is not None else [],
        dietary_flags=dietary_flags if dietary_flags is not None else [],
        popularity_share=popularity_share, unit_cost_cents=unit_cost_cents,
        allergen_reviewed=allergen_reviewed)
    return get_success_data(api_client.create_recipe(payload, KITCHEN_LEAD))


def create_menu_cycle(hall_id, name="Cycle A", weeks=4,
                      start_date=DEFAULT_CYCLE_START, end_date=DEFAULT_CYCLE_END):
    resp = api_client.create_menu_cycle(
        create_menu_cycle_payload(hall_id, name=name, cycle_length_weeks=weeks,
                                  start_date=start_date, end_date=end_date), ADMIN)
    return get_success_data(resp)


def publish_cycle(cycle_id):
    return get_success_data(api_client.publish_menu_cycle(cycle_id, ADMIN))


def create_published_cycle(hall_id, name="Cycle A", weeks=4,
                           start_date=DEFAULT_CYCLE_START, end_date=DEFAULT_CYCLE_END):
    cycle = create_menu_cycle(hall_id, name=name, weeks=weeks,
                              start_date=start_date, end_date=end_date)
    return publish_cycle(cycle["id"])


def get_cycle(cycle_id):
    return get_success_data(api_client.get_menu_cycle(cycle_id, ADMIN))


def create_active_contract(hall_id, vendor_name="CampusEats LLC", board_rate=500,
                           retail_bps=1000, catering_bps=800, guarantee=0,
                           start="2026-08-01", end="2026-12-01"):
    contract = get_success_data(api_client.create_vendor_contract(
        create_vendor_contract_payload(
            hall_id, vendor_name=vendor_name, board_rate_per_cover_cents=board_rate,
            retail_commission_bps=retail_bps, catering_commission_bps=catering_bps,
            minimum_monthly_guarantee_cents=guarantee,
            effective_start_date=start, effective_end_date=end), ADMIN))
    return get_success_data(api_client.activate_vendor_contract(
        contract["id"], CONTRACT_MANAGER))


def get_contract(contract_id):
    return get_success_data(api_client.get_vendor_contract(contract_id, CONTRACT_MANAGER))


def create_department(name="Engineering", code="ENG", budget=1000000):
    resp = api_client.create_department(
        create_department_payload(name=name, department_code=code,
                                  semester_budget_cents=budget), ADMIN)
    return get_success_data(resp)


def get_department(department_id):
    return get_success_data(api_client.get_department(department_id, ADMIN))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: meal period pipeline
# ---------------------------------------------------------------------------

def create_scheduled_period(hall_id, cycle_id, service_date, meal_period="LUNCH"):
    resp = api_client.create_meal_period(
        create_meal_period_payload(hall_id, cycle_id, service_date,
                                   meal_period=meal_period), HALL_MANAGER)
    return get_success_data(resp)


def get_period(period_id):
    return get_success_data(api_client.get_meal_period(period_id, HALL_MANAGER))


def create_forecast(period_id, recipe_id, variant="BASE", expected_version=None):
    """Create a forecast, reading the period's fresh version when not supplied."""
    if expected_version is None:
        expected_version = get_period(period_id)["version"]
    resp = api_client.create_production_forecast(
        period_id,
        create_forecast_payload(recipe_id, expected_version, variant=variant),
        KITCHEN_LEAD)
    return get_success_data(resp)


def lock_forecast(forecast_id):
    return get_success_data(api_client.lock_production_forecast(forecast_id, KITCHEN_LEAD))


def drive_period_to_forecast_locked(hall_id, cycle_id, recipe_id, service_date,
                                    meal_period="LUNCH"):
    """Period in FORECAST_LOCKED with one LOCKED BASE forecast. Returns period."""
    period = create_scheduled_period(hall_id, cycle_id, service_date, meal_period)
    forecast = create_forecast(period["id"], recipe_id)
    lock_forecast(forecast["id"])
    return get_success_data(api_client.lock_meal_period_forecast(period["id"], HALL_MANAGER))


def drive_period_to_in_service(hall_id, cycle_id, recipe_id, service_date,
                               meal_period="LUNCH"):
    period = drive_period_to_forecast_locked(hall_id, cycle_id, recipe_id,
                                             service_date, meal_period)
    return get_success_data(api_client.open_meal_period_service(period["id"], HALL_MANAGER))


def ingest_swipes(period_id, events):
    """events: list of (entry_type, amount_cents, count) tuples."""
    payload = {"events": [swipe_event_entry(t, a, c) for (t, a, c) in events]}
    return get_success_data(api_client.ingest_swipes(period_id, payload, HALL_MANAGER))


def drive_period_to_reconciled(hall_id, cycle_id, recipe_id, service_date,
                               meal_period="LUNCH", events=None):
    period = drive_period_to_in_service(hall_id, cycle_id, recipe_id,
                                        service_date, meal_period)
    if events:
        ingest_swipes(period["id"], events)
    return get_success_data(api_client.reconcile_meal_period(period["id"], HALL_MANAGER))


def drive_period_to_closed(hall_id, cycle_id, recipe_id, service_date,
                           meal_period="LUNCH", events=None):
    period = drive_period_to_reconciled(hall_id, cycle_id, recipe_id, service_date,
                                        meal_period, events)
    return get_success_data(api_client.close_meal_period(period["id"], ADMIN))


def create_historical_period(hall_id, cycle_id, recipe_id, service_date,
                             meal_period="LUNCH", board_count=0,
                             retail_events=None, end_state="IN_SERVICE"):
    """A period on a prior week with a known cover count, left in end_state
    (IN_SERVICE | RECONCILED | CLOSED) so it qualifies as forecast history."""
    events = []
    if board_count:
        events.append(("BOARD_SWIPE", 0, board_count))
    for amount, count in (retail_events or []):
        events.append(("RETAIL_SALE", amount, count))
    if end_state == "IN_SERVICE":
        period = drive_period_to_in_service(hall_id, cycle_id, recipe_id,
                                            service_date, meal_period)
        if events:
            ingest_swipes(period["id"], events)
        return get_period(period["id"])
    if end_state == "RECONCILED":
        return drive_period_to_reconciled(hall_id, cycle_id, recipe_id, service_date,
                                          meal_period, events)
    if end_state == "CLOSED":
        return drive_period_to_closed(hall_id, cycle_id, recipe_id, service_date,
                                      meal_period, events)
    raise ValueError(f"unsupported end_state {end_state!r}")


def setup_hall_cycle_recipe(hall_name="Test Hall", dining_capacity=800,
                            kitchen_capacity=500, service_model="BOARD",
                            recipe_name="Grain Bowl", station="GLOBAL",
                            popularity_share=0.5, unit_cost_cents=500,
                            dietary_flags=None,
                            cycle_start=DEFAULT_CYCLE_START, cycle_end=DEFAULT_CYCLE_END):
    """Hall + allergen-reviewed ACTIVE recipe + published cycle."""
    hall = create_hall(name=hall_name, service_model=service_model,
                       dining_capacity=dining_capacity,
                       catering_kitchen_capacity=kitchen_capacity)
    recipe = create_recipe(hall["id"], name=recipe_name, station=station,
                           popularity_share=popularity_share,
                           unit_cost_cents=unit_cost_cents,
                           dietary_flags=dietary_flags or [])
    cycle = create_published_cycle(hall["id"], start_date=cycle_start,
                                   end_date=cycle_end)
    return hall, recipe, cycle


# ---------------------------------------------------------------------------
# Tier 2: waste pipeline
# ---------------------------------------------------------------------------

def record_waste_log(period_id, category="PRE_CONSUMER", disposition="LANDFILL",
                     weight_kg=1.0, recorder_id="kl-1"):
    resp = api_client.create_waste_log(
        period_id,
        create_waste_log_payload(category=category, disposition=disposition,
                                 weight_kg=weight_kg),
        make_kitchen_lead_headers(recorder_id))
    return get_success_data(resp)


def verify_waste_log(log_id, verifier_id="hm-1"):
    return get_success_data(api_client.verify_waste_log(
        log_id, make_hall_manager_headers(verifier_id)))


def post_waste_log(log_id):
    return get_success_data(api_client.post_waste_log(log_id, HALL_MANAGER))


def reject_waste_log(log_id):
    return get_success_data(api_client.reject_waste_log(log_id, HALL_MANAGER))


def get_waste_log(log_id):
    return get_success_data(api_client.get_waste_log(log_id, HALL_MANAGER))


def create_posted_waste_log(period_id, category="PRE_CONSUMER", disposition="LANDFILL",
                            weight_kg=1.0, recorder_id="kl-1", verifier_id="hm-1"):
    log = record_waste_log(period_id, category=category, disposition=disposition,
                           weight_kg=weight_kg, recorder_id=recorder_id)
    verify_waste_log(log["id"], verifier_id=verifier_id)
    return post_waste_log(log["id"])


# ---------------------------------------------------------------------------
# Tier 2: inspections and corrective actions
# ---------------------------------------------------------------------------

def file_inspection(hall_id, inspection_date, violations, inspector_id="insp-1"):
    resp = api_client.create_inspection_report(
        create_inspection_report_payload(hall_id, inspection_date, violations),
        make_health_inspector_headers(inspector_id))
    return get_success_data(resp)


def submit_inspection(report_id, inspector_id="insp-1"):
    return get_success_data(api_client.submit_inspection_report(
        report_id, make_health_inspector_headers(inspector_id)))


def acknowledge_inspection(report_id):
    return get_success_data(api_client.acknowledge_inspection_report(report_id, HALL_MANAGER))


def get_inspection(report_id):
    return get_success_data(api_client.get_inspection_report(report_id, INSPECTOR))


def list_report_corrective_actions(report_id):
    """All corrective actions bound to the report (client-side FK filter)."""
    data, _meta = validate_paginated(api_client.list_corrective_actions(INSPECTOR))
    return [row for row in data if row["inspection_report_id"] == report_id]


# ---------------------------------------------------------------------------
# Tier 2: departments and catering orders
# ---------------------------------------------------------------------------

def create_catering_order(hall_id, department_id, event_date, time_slot,
                          guaranteed_covers, menu_lines, dietary_plates=0,
                          revised_from_id=None):
    """Create an order as the owning DepartmentUser. Returns the order."""
    overrides = {}
    if revised_from_id is not None:
        overrides["revised_from_id"] = revised_from_id
    payload = create_catering_order_payload(
        hall_id, department_id, event_date, menu_lines,
        time_slot=time_slot, guaranteed_covers=guaranteed_covers,
        dietary_plates=dietary_plates, **overrides)
    resp = api_client.create_catering_order(
        payload, make_department_user_headers(department_id))
    return get_success_data(resp)


def submit_order(order_id, department_id):
    return get_success_data(api_client.submit_catering_order(
        order_id, make_department_user_headers(department_id)))


def approve_order(order_id, department_id, expected_version=None):
    """Approve with the department's fresh version when not supplied."""
    if expected_version is None:
        expected_version = get_department(department_id)["version"]
    return get_success_data(api_client.approve_catering_order(
        order_id, {"expected_department_version": expected_version}, HALL_MANAGER))


def reject_order(order_id):
    return get_success_data(api_client.reject_catering_order(order_id, HALL_MANAGER))


def schedule_order(order_id):
    return get_success_data(api_client.schedule_catering_order(order_id, HALL_MANAGER))


def fulfill_order(order_id):
    return get_success_data(api_client.fulfill_catering_order(order_id, KITCHEN_LEAD))


def invoice_order(order_id, final_total_cents):
    return get_success_data(api_client.invoice_catering_order(
        order_id, {"final_total_cents": final_total_cents}, HALL_MANAGER))


def pay_order(order_id):
    return get_success_data(api_client.pay_catering_order(order_id, ADMIN))


def cancel_order(order_id, department_id=None):
    headers = (make_department_user_headers(department_id)
               if department_id is not None else HALL_MANAGER)
    return get_success_data(api_client.cancel_catering_order(order_id, headers))


def get_order(order_id):
    return get_success_data(api_client.get_catering_order(order_id, HALL_MANAGER))


def create_submitted_order(hall_id, department_id, event_date, time_slot,
                           guaranteed_covers, menu_lines, dietary_plates=0):
    order = create_catering_order(hall_id, department_id, event_date, time_slot,
                                  guaranteed_covers, menu_lines, dietary_plates)
    return submit_order(order["id"], department_id)


def create_approved_order(hall_id, department_id, event_date, time_slot,
                          guaranteed_covers, menu_lines, dietary_plates=0):
    order = create_submitted_order(hall_id, department_id, event_date, time_slot,
                                   guaranteed_covers, menu_lines, dietary_plates)
    return approve_order(order["id"], department_id)


def walk_order_to_fulfilled(hall_id, department_id, event_date, time_slot,
                            guaranteed_covers, menu_lines, dietary_plates=0):
    order = create_approved_order(hall_id, department_id, event_date, time_slot,
                                  guaranteed_covers, menu_lines, dietary_plates)
    schedule_order(order["id"])
    return fulfill_order(order["id"])


# ---------------------------------------------------------------------------
# Tier 2: labor shifts
# ---------------------------------------------------------------------------

def create_shift(hall_id, staff_ref=None, role="COOK", shift_date="2026-08-10",
                 start_minute=480, end_minute=960, hourly_rate_cents=2000):
    overrides = {}
    if staff_ref is not None:
        overrides["staff_ref"] = staff_ref
    resp = api_client.create_labor_shift(
        create_labor_shift_payload(
            hall_id, role=role, shift_date=shift_date, start_minute=start_minute,
            end_minute=end_minute, hourly_rate_cents=hourly_rate_cents, **overrides),
        HALL_MANAGER)
    return get_success_data(resp)


def confirm_shift(shift_id):
    return get_success_data(api_client.confirm_labor_shift(shift_id, HALL_MANAGER))


def complete_shift(shift_id, worked_minutes):
    return get_success_data(api_client.complete_labor_shift(
        shift_id, {"worked_minutes": worked_minutes}, HALL_MANAGER))


def get_shift(shift_id):
    return get_success_data(api_client.get_labor_shift(shift_id, HALL_MANAGER))


def create_completed_shift(hall_id, staff_ref, shift_date, start_minute, end_minute,
                           hourly_rate_cents, worked_minutes, role="COOK"):
    """Create (ASSIGNED) -> confirm -> complete. Returns the COMPLETED shift."""
    shift = create_shift(hall_id, staff_ref=staff_ref, role=role,
                         shift_date=shift_date, start_minute=start_minute,
                         end_minute=end_minute, hourly_rate_cents=hourly_rate_cents)
    confirm_shift(shift["id"])
    return complete_shift(shift["id"], worked_minutes)


# ---------------------------------------------------------------------------
# Tier 2: accommodation requests
# ---------------------------------------------------------------------------

def create_accommodation(hall_id, student_ref="STU-1", allergen_exclusions=None,
                         dietary_requirement="VEGAN"):
    resp = api_client.create_accommodation_request(
        create_accommodation_payload(
            hall_id, student_ref=student_ref,
            allergen_exclusions=allergen_exclusions or [],
            dietary_requirement=dietary_requirement), HALL_MANAGER)
    return get_success_data(resp)


def get_accommodation(request_id):
    return get_success_data(api_client.get_accommodation_request(request_id, HALL_MANAGER))


# ---------------------------------------------------------------------------
# Tier 2: commission statements
# ---------------------------------------------------------------------------

def create_statement(contract_id, period_month="2026-08"):
    resp = api_client.create_commission_statement(
        contract_id, {"period_month": period_month}, ADMIN)
    return get_success_data(resp)


def get_statement(statement_id):
    return get_success_data(api_client.get_commission_statement(statement_id, ADMIN))
