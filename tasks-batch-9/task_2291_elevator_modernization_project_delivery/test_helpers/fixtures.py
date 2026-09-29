"""Composite setup helpers for the modernization delivery chain.

Every helper builds its state from scratch through PRD-declared endpoints only,
because each test starts against an empty database. Setup calls go through the
lenient success reader so a broken precondition surfaces as a setup failure
rather than as a confusing assertion inside the test under exercise.

The delivery chain these helpers walk is:

    clock -> jurisdiction -> project -> group -> car -> survey -> countersign
    -> scope option -> submit -> approve -> procurement order -> issue
    -> staging hold -> receive -> install -> outage window -> notice
    -> activate -> complete -> begin testing -> inspection request -> schedule
    -> ruling -> warranty transition -> maintenance contract -> enroll -> activate
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as payloads
from .api_client import api_client
from .constants import INITIAL_CLOCK_UTC
from .test_users import (
    TEST_USERS,
    make_ahj_inspector_headers,
    make_building_representative_headers,
    make_survey_technician_headers,
)

PM = TEST_USERS["project_manager_headers"]
SM = TEST_USERS["service_manager_headers"]
OPS = TEST_USERS["system_operator_headers"]
TECH = TEST_USERS["survey_technician_headers"]

DEFAULT_SURVEYOR = "tech-001"
DEFAULT_COUNTERSIGNER = "tech-002"


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock. Returns the clock read."""
    return get_success_data(
        api_client.set_clock(payloads.set_clock_payload(to_iso8601), OPS)
    )


def anchor_clock(to_iso8601: str = INITIAL_CLOCK_UTC) -> dict:
    """Pin the clock to a known instant before the scenario starts."""
    return set_clock(to_iso8601)


# --------------------------------------------------------------------------
# Single-step creators
# --------------------------------------------------------------------------

def create_jurisdiction(**overrides) -> dict:
    return get_success_data(
        api_client.create_jurisdiction(
            payloads.create_jurisdiction_payload(**overrides), OPS
        )
    )


def create_marlow_jurisdiction(**overrides) -> dict:
    """A jurisdiction whose code configuration arms code triggers."""
    defaults = {
        "name": "County of Marlow",
        "code_edition_year": 2022,
        "fire_service_required": True,
        "seismic_zone": 0,
        "door_protection_required": True,
    }
    defaults.update(overrides)
    return create_jurisdiction(**defaults)


def create_project(jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_project(
            payloads.create_project_payload(jurisdiction_id, **overrides), PM
        )
    )


def create_group(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_elevator_group(
            payloads.create_elevator_group_payload(project_id, **overrides), PM
        )
    )


def create_car(project_id: str, group_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_elevator_car(
            payloads.create_elevator_car_payload(project_id, group_id, **overrides), PM
        )
    )


def submit_survey(
    car_id: str,
    controller_condition: str = "GOOD",
    machine_condition: str = "GOOD",
    door_equipment_condition: str = "EXCELLENT",
    surveyor_user_id: str = DEFAULT_SURVEYOR,
) -> dict:
    return get_success_data(
        api_client.create_equipment_survey(
            payloads.create_equipment_survey_payload(
                car_id,
                controller_condition=controller_condition,
                machine_condition=machine_condition,
                door_equipment_condition=door_equipment_condition,
            ),
            make_survey_technician_headers(surveyor_user_id),
        )
    )


def countersign_survey(
    survey_id: str, countersigner_user_id: str = DEFAULT_COUNTERSIGNER
) -> dict:
    return get_success_data(
        api_client.countersign_equipment_survey(
            survey_id, make_survey_technician_headers(countersigner_user_id)
        )
    )


def create_scope_option(
    project_id: str,
    car_id: str,
    tier: str = "CONTROLLER_ONLY",
    base_price_cents: int = 5_000_000,
    expected_project_version: int = None,
) -> dict:
    version = (
        expected_project_version
        if expected_project_version is not None
        else project_version(project_id)
    )
    return get_success_data(
        api_client.create_scope_option(
            payloads.create_scope_option_payload(
                car_id,
                version,
                tier=tier,
                base_price_cents=base_price_cents,
            ),
            PM,
        )
    )


def price_code_trigger(code_trigger_id: str, cost_cents: int) -> dict:
    return get_success_data(
        api_client.price_code_trigger(code_trigger_id, {"cost_cents": cost_cents}, PM)
    )


def waive_code_trigger(
    jurisdiction_id: str, code_trigger_id: str, waiver_reference: str
) -> dict:
    return get_success_data(
        api_client.waive_code_trigger(
            code_trigger_id,
            {"waiver_reference": waiver_reference},
            make_ahj_inspector_headers(jurisdiction_id),
        )
    )


def price_all_code_triggers(scope_option_id: str, cost_cents: int = 0) -> list:
    """Price every trigger the option synthesized. Returns the priced triggers."""
    priced = []
    for trigger in list_code_triggers(scope_option_id):
        priced.append(price_code_trigger(trigger["id"], cost_cents))
    return priced


def submit_scope_option(scope_option_id: str) -> dict:
    return get_success_data(api_client.submit_scope_option(scope_option_id, PM))


def approve_scope_option(project_id: str, scope_option_id: str) -> dict:
    return get_success_data(
        api_client.approve_scope_option(
            scope_option_id, make_building_representative_headers(project_id)
        )
    )


def rescind_scope_option(scope_option_id: str) -> dict:
    return get_success_data(api_client.rescind_scope_option(scope_option_id, PM))


def reject_scope_option(
    project_id: str, scope_option_id: str, rejection_note: str = "price too high"
) -> dict:
    return get_success_data(
        api_client.reject_scope_option(
            scope_option_id,
            make_building_representative_headers(project_id),
            {"rejection_note": rejection_note},
        )
    )


def revise_scope_option(scope_option_id: str, base_price_cents: int) -> dict:
    return get_success_data(
        api_client.revise_scope_option(
            scope_option_id, PM, {"base_price_cents": base_price_cents}
        )
    )


def create_procurement_order(
    scope_option_id: str,
    item_type: str = "CONTROLLER",
    lead_time_days: int = 30,
    required_staging_sqft: int = 400,
) -> dict:
    return get_success_data(
        api_client.create_procurement_order(
            payloads.create_procurement_order_payload(
                scope_option_id,
                item_type=item_type,
                lead_time_days=lead_time_days,
                required_staging_sqft=required_staging_sqft,
            ),
            PM,
        )
    )


def issue_procurement_order(procurement_order_id: str) -> dict:
    return get_success_data(api_client.issue_procurement_order(procurement_order_id, PM))


def create_and_issue_order(
    scope_option_id: str,
    item_type: str = "CONTROLLER",
    lead_time_days: int = 30,
    required_staging_sqft: int = 400,
) -> dict:
    order = create_procurement_order(
        scope_option_id,
        item_type=item_type,
        lead_time_days=lead_time_days,
        required_staging_sqft=required_staging_sqft,
    )
    return issue_procurement_order(order["id"])


def hold_staging(
    project_id: str,
    procurement_order_id: str,
    sqft: int = 400,
    hold_start: str = "2026-08-05T00:00:00Z",
    hold_end: str = "2026-08-20T00:00:00Z",
    expected_project_version: int = None,
) -> dict:
    version = (
        expected_project_version
        if expected_project_version is not None
        else project_version(project_id)
    )
    return get_success_data(
        api_client.create_staging_reservation(
            payloads.create_staging_reservation_payload(
                procurement_order_id,
                version,
                sqft=sqft,
                hold_start=hold_start,
                hold_end=hold_end,
            ),
            PM,
        )
    )


def release_staging(staging_reservation_id: str) -> dict:
    return get_success_data(
        api_client.release_staging_reservation(staging_reservation_id, PM)
    )


def receive_order(procurement_order_id: str, staging_reservation_id: str) -> dict:
    return get_success_data(
        api_client.receive_procurement_order(
            procurement_order_id, {"staging_reservation_id": staging_reservation_id}, PM
        )
    )


def install_order(procurement_order_id: str) -> dict:
    return get_success_data(api_client.install_procurement_order(procurement_order_id, PM))


def plan_outage(
    car_id: str,
    start_at: str = "2026-08-10T08:00:00Z",
    end_at: str = "2026-08-12T18:00:00Z",
    temporary_service_plan: str = "ADJACENT_CAR",
    predecessor_window_id: str = None,
) -> dict:
    payload = payloads.create_outage_window_payload(
        car_id,
        start_at=start_at,
        end_at=end_at,
        temporary_service_plan=temporary_service_plan,
    )
    if predecessor_window_id is not None:
        payload["predecessor_window_id"] = predecessor_window_id
    return get_success_data(api_client.create_outage_window(payload, PM))


def send_outage_notice(outage_window_id: str) -> dict:
    return get_success_data(api_client.send_outage_notice(outage_window_id, PM))


def activate_outage(outage_window_id: str) -> dict:
    return get_success_data(api_client.activate_outage_window(outage_window_id, PM))


def complete_outage(outage_window_id: str) -> dict:
    return get_success_data(api_client.complete_outage_window(outage_window_id, PM))


def begin_testing(car_id: str) -> dict:
    return get_success_data(api_client.begin_testing_elevator_car(car_id, PM))


def request_inspection(car_id: str, requested_date: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_inspection_appointment(
            payloads.create_inspection_appointment_payload(
                car_id, requested_date=requested_date, **overrides
            ),
            PM,
        )
    )


def schedule_inspection(
    jurisdiction_id: str, inspection_appointment_id: str, scheduled_at: str
) -> dict:
    return get_success_data(
        api_client.schedule_inspection_appointment(
            inspection_appointment_id,
            {"scheduled_at": scheduled_at},
            make_ahj_inspector_headers(jurisdiction_id),
        )
    )


def reschedule_inspection(
    jurisdiction_id: str, inspection_appointment_id: str, scheduled_at: str
) -> dict:
    return get_success_data(
        api_client.reschedule_inspection_appointment(
            inspection_appointment_id,
            {"scheduled_at": scheduled_at},
            make_ahj_inspector_headers(jurisdiction_id),
        )
    )


def record_inspection_result(
    jurisdiction_id: str,
    inspection_appointment_id: str,
    result: str = "PASSED",
    punch_list_count: int = None,
) -> dict:
    payload = {"result": result}
    if punch_list_count is not None:
        payload["punch_list_count"] = punch_list_count
    return get_success_data(
        api_client.record_inspection_result(
            inspection_appointment_id, payload, make_ahj_inspector_headers(jurisdiction_id)
        )
    )


def open_warranty(car_id: str, warranty_months: int = 24) -> dict:
    return get_success_data(
        api_client.create_warranty_transition(
            payloads.create_warranty_transition_payload(
                car_id, warranty_months=warranty_months
            ),
            SM,
        )
    )


def draft_contract(
    project_id: str,
    coverage_start: str = "2027-03-15",
    monthly_base_cents: int = 45_000,
) -> dict:
    return get_success_data(
        api_client.create_maintenance_contract(
            payloads.create_maintenance_contract_payload(
                project_id,
                coverage_start=coverage_start,
                monthly_base_cents=monthly_base_cents,
            ),
            SM,
        )
    )


def enroll_warranty(warranty_transition_id: str, maintenance_contract_id: str) -> dict:
    return get_success_data(
        api_client.enroll_warranty_transition(
            warranty_transition_id,
            {"maintenance_contract_id": maintenance_contract_id},
            SM,
        )
    )


def activate_contract(maintenance_contract_id: str) -> dict:
    return get_success_data(
        api_client.activate_maintenance_contract(maintenance_contract_id, SM)
    )


# --------------------------------------------------------------------------
# Read-back helpers (side-effect verification)
# --------------------------------------------------------------------------

def read_jurisdiction(jurisdiction_id: str) -> dict:
    return get_success_data(api_client.get_jurisdiction(jurisdiction_id, PM))


def read_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, PM))


def read_posture(project_id: str) -> dict:
    return get_success_data(api_client.get_project_posture(project_id, PM))


def read_group(group_id: str) -> dict:
    return get_success_data(api_client.get_elevator_group(group_id, PM))


def read_car(car_id: str) -> dict:
    return get_success_data(api_client.get_elevator_car(car_id, PM))


def read_survey(survey_id: str) -> dict:
    return get_success_data(api_client.get_equipment_survey(survey_id, PM))


def read_scope_option(scope_option_id: str) -> dict:
    return get_success_data(api_client.get_scope_option(scope_option_id, PM))


def read_code_trigger(code_trigger_id: str) -> dict:
    return get_success_data(api_client.get_code_trigger(code_trigger_id, PM))


def read_procurement_order(procurement_order_id: str) -> dict:
    return get_success_data(api_client.get_procurement_order(procurement_order_id, PM))


def read_staging_reservation(staging_reservation_id: str) -> dict:
    return get_success_data(
        api_client.get_staging_reservation(staging_reservation_id, PM)
    )


def read_outage_window(outage_window_id: str) -> dict:
    return get_success_data(api_client.get_outage_window(outage_window_id, PM))


def read_inspection_appointment(inspection_appointment_id: str) -> dict:
    return get_success_data(
        api_client.get_inspection_appointment(inspection_appointment_id, PM)
    )


def read_warranty_transition(warranty_transition_id: str) -> dict:
    return get_success_data(
        api_client.get_warranty_transition(warranty_transition_id, PM)
    )


def read_maintenance_contract(maintenance_contract_id: str) -> dict:
    return get_success_data(
        api_client.get_maintenance_contract(maintenance_contract_id, PM)
    )


def project_version(project_id: str) -> int:
    """The project's live version, for the optimistic-concurrency writes."""
    return read_project(project_id)["version"]


def list_code_triggers(scope_option_id: str) -> list:
    body = api_client.list_code_triggers(
        PM, params={"scope_option_id": scope_option_id}
    ).json()
    return body["data"]


def list_staging_reservations(procurement_order_id: str, status: str = None) -> tuple:
    """Returns (rows, meta) for one order's staging reservations."""
    params = {"procurement_order_id": procurement_order_id}
    if status is not None:
        params["status"] = status
    body = api_client.list_staging_reservations(PM, params=params).json()
    return body["data"], body["meta"]


def list_scope_options(**params) -> tuple:
    body = api_client.list_scope_options(PM, params=params or None).json()
    return body["data"], body["meta"]


def list_outage_windows(**params) -> tuple:
    body = api_client.list_outage_windows(PM, params=params or None).json()
    return body["data"], body["meta"]


def list_equipment_surveys(**params) -> tuple:
    body = api_client.list_equipment_surveys(PM, params=params or None).json()
    return body["data"], body["meta"]


def list_procurement_orders(**params) -> tuple:
    body = api_client.list_procurement_orders(PM, params=params or None).json()
    return body["data"], body["meta"]


# --------------------------------------------------------------------------
# Tier 2 — hierarchy
# --------------------------------------------------------------------------

def setup_project(
    clock: str = INITIAL_CLOCK_UTC,
    jurisdiction_overrides: dict = None,
    marlow: bool = False,
    **project_overrides,
) -> dict:
    """Clock anchored, one jurisdiction and one project in SURVEY."""
    anchor_clock(clock)
    if marlow:
        jurisdiction = create_marlow_jurisdiction(**(jurisdiction_overrides or {}))
    else:
        jurisdiction = create_jurisdiction(**(jurisdiction_overrides or {}))
    project = create_project(jurisdiction["id"], **project_overrides)
    return {"jurisdiction": jurisdiction, "project": project}


def setup_project_with_cars(
    num_cars: int = 1,
    min_cars_in_service: int = 0,
    group_label: str = "BANK-A",
    car_overrides: list = None,
    **kwargs,
) -> dict:
    """Project + one group + `num_cars` cars registered into it.

    Cars are designated CAR-1..CAR-N with ascending duty_rank.
    """
    ctx = setup_project(**kwargs)
    group = create_group(
        ctx["project"]["id"],
        group_label=group_label,
        min_cars_in_service=min_cars_in_service,
    )
    cars = []
    for index in range(num_cars):
        overrides = dict((car_overrides or [{}] * num_cars)[index]) if car_overrides else {}
        overrides.setdefault("car_designation", f"CAR-{index + 1}")
        overrides.setdefault("duty_rank", index + 1)
        cars.append(create_car(ctx["project"]["id"], group["id"], **overrides))
    ctx["group"] = group
    ctx["groups"] = [group]
    ctx["cars"] = cars
    ctx["car"] = cars[0] if cars else None
    return ctx


def setup_project_with_two_groups(
    cars_per_group: tuple = (1, 1),
    min_cars_in_service: tuple = (0, 0),
    **kwargs,
) -> dict:
    """Project + two groups (BANK-A, BANK-B) with the requested car counts."""
    ctx = setup_project(**kwargs)
    project_id = ctx["project"]["id"]
    groups, cars = [], []
    designation = 1
    for index, label in enumerate(("BANK-A", "BANK-B")):
        group = create_group(
            project_id, group_label=label, min_cars_in_service=min_cars_in_service[index]
        )
        groups.append(group)
        for _ in range(cars_per_group[index]):
            cars.append(
                create_car(
                    project_id,
                    group["id"],
                    car_designation=f"CAR-{designation}",
                    duty_rank=designation,
                )
            )
            designation += 1
    ctx["groups"] = groups
    ctx["group"] = groups[0]
    ctx["cars"] = cars
    ctx["car"] = cars[0]
    return ctx


# --------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# --------------------------------------------------------------------------

def setup_surveyed_car(
    controller_condition: str = "GOOD",
    machine_condition: str = "GOOD",
    door_equipment_condition: str = "EXCELLENT",
    surveyor_user_id: str = DEFAULT_SURVEYOR,
    countersigner_user_id: str = DEFAULT_COUNTERSIGNER,
    **kwargs,
) -> dict:
    """Car with a countersigned survey: car SURVEYED, project SCOPING."""
    ctx = setup_project_with_cars(**kwargs)
    survey = submit_survey(
        ctx["car"]["id"],
        controller_condition=controller_condition,
        machine_condition=machine_condition,
        door_equipment_condition=door_equipment_condition,
        surveyor_user_id=surveyor_user_id,
    )
    ctx["survey"] = countersign_survey(survey["id"], countersigner_user_id)
    ctx["surveys"] = [ctx["survey"]]
    return ctx


def setup_scoped_car(
    tier: str = "CONTROLLER_ONLY",
    base_price_cents: int = 5_000_000,
    trigger_cost_cents: int = None,
    **kwargs,
) -> dict:
    """Surveyed car with one DRAFT scope option and its synthesized triggers.

    When `trigger_cost_cents` is given, every synthesized trigger is priced at
    that amount so the option can pass approval.
    """
    ctx = setup_surveyed_car(**kwargs)
    option = create_scope_option(
        ctx["project"]["id"],
        ctx["car"]["id"],
        tier=tier,
        base_price_cents=base_price_cents,
    )
    ctx["scope_option"] = option
    ctx["code_triggers"] = list_code_triggers(option["id"])
    if trigger_cost_cents is not None and ctx["code_triggers"]:
        price_all_code_triggers(option["id"], trigger_cost_cents)
        ctx["code_triggers"] = list_code_triggers(option["id"])
        ctx["scope_option"] = read_scope_option(option["id"])
    return ctx


def setup_approved_option(**kwargs) -> dict:
    """Scope option submitted and approved: car PROCURING, project EXECUTION."""
    ctx = setup_scoped_car(**kwargs)
    submit_scope_option(ctx["scope_option"]["id"])
    ctx["scope_option"] = approve_scope_option(
        ctx["project"]["id"], ctx["scope_option"]["id"]
    )
    return ctx


def setup_issued_order(
    item_type: str = "CONTROLLER",
    lead_time_days: int = 30,
    required_staging_sqft: int = 400,
    **kwargs,
) -> dict:
    """Approved option with one ORDERED procurement order."""
    ctx = setup_approved_option(**kwargs)
    ctx["procurement_order"] = create_and_issue_order(
        ctx["scope_option"]["id"],
        item_type=item_type,
        lead_time_days=lead_time_days,
        required_staging_sqft=required_staging_sqft,
    )
    ctx["procurement_orders"] = [ctx["procurement_order"]]
    return ctx


def setup_held_reservation(
    sqft: int = 400,
    hold_start: str = "2026-08-05T00:00:00Z",
    hold_end: str = "2026-08-20T00:00:00Z",
    **kwargs,
) -> dict:
    """Issued order with a HELD staging reservation against it."""
    ctx = setup_issued_order(**kwargs)
    ctx["staging_reservation"] = hold_staging(
        ctx["project"]["id"],
        ctx["procurement_order"]["id"],
        sqft=sqft,
        hold_start=hold_start,
        hold_end=hold_end,
    )
    return ctx


def setup_installed_equipment(**kwargs) -> dict:
    """Order received into staging and then installed; the hold is released."""
    ctx = setup_held_reservation(**kwargs)
    receive_order(
        ctx["procurement_order"]["id"], ctx["staging_reservation"]["id"]
    )
    ctx["procurement_order"] = install_order(ctx["procurement_order"]["id"])
    ctx["staging_reservation"] = read_staging_reservation(
        ctx["staging_reservation"]["id"]
    )
    return ctx


def setup_planned_outage(
    start_at: str = "2026-08-10T08:00:00Z",
    end_at: str = "2026-08-12T18:00:00Z",
    temporary_service_plan: str = "ADJACENT_CAR",
    with_notice: bool = True,
    **kwargs,
) -> dict:
    """Installed equipment plus one PLANNED outage window, notice optionally sent."""
    ctx = setup_installed_equipment(**kwargs)
    window = plan_outage(
        ctx["car"]["id"],
        start_at=start_at,
        end_at=end_at,
        temporary_service_plan=temporary_service_plan,
    )
    if with_notice:
        window = send_outage_notice(window["id"])
    ctx["outage_window"] = window
    ctx["outage_windows"] = [window]
    return ctx


def setup_active_outage(
    activate_at: str = "2026-08-10T09:00:00Z", **kwargs
) -> dict:
    """Outage window activated: car OUTAGE_ACTIVE, one active outage counted."""
    ctx = setup_planned_outage(**kwargs)
    set_clock(activate_at)
    ctx["outage_window"] = activate_outage(ctx["outage_window"]["id"])
    return ctx


def setup_car_in_testing(**kwargs) -> dict:
    """Outage completed and the car returned to acceptance testing."""
    ctx = setup_active_outage(**kwargs)
    ctx["outage_window"] = complete_outage(ctx["outage_window"]["id"])
    ctx["car"] = begin_testing(ctx["car"]["id"])
    return ctx


def setup_scheduled_inspection(
    requested_date: str = "2026-08-25",
    scheduled_at: str = "2026-08-25T13:00:00Z",
    **kwargs,
) -> dict:
    """Car in testing with a SCHEDULED acceptance inspection."""
    ctx = setup_car_in_testing(**kwargs)
    appointment = request_inspection(ctx["car"]["id"], requested_date)
    ctx["inspection_appointment"] = schedule_inspection(
        ctx["jurisdiction"]["id"], appointment["id"], scheduled_at
    )
    ctx["inspection_appointments"] = [ctx["inspection_appointment"]]
    return ctx


def setup_accepted_car(
    ruling_at: str = "2026-08-25T13:00:00Z",
    result: str = "PASSED",
    punch_list_count: int = None,
    **kwargs,
) -> dict:
    """Inspection ruled: on PASSED the car is ACCEPTED and CODE_ACCEPTED."""
    ctx = setup_scheduled_inspection(**kwargs)
    set_clock(ruling_at)
    ctx["inspection_appointment"] = record_inspection_result(
        ctx["jurisdiction"]["id"],
        ctx["inspection_appointment"]["id"],
        result=result,
        punch_list_count=punch_list_count,
    )
    ctx["car"] = read_car(ctx["car"]["id"])
    return ctx


def setup_warranty_transition(warranty_months: int = 24, **kwargs) -> dict:
    """Accepted, code-accepted car with a PENDING warranty transition."""
    ctx = setup_accepted_car(**kwargs)
    ctx["warranty_transition"] = open_warranty(
        ctx["car"]["id"], warranty_months=warranty_months
    )
    ctx["car"] = read_car(ctx["car"]["id"])
    return ctx


def setup_drafted_contract(
    coverage_start: str = "2027-03-15",
    monthly_base_cents: int = 45_000,
    **kwargs,
) -> dict:
    """Warranty transition plus a DRAFT maintenance contract on the same project."""
    ctx = setup_warranty_transition(**kwargs)
    ctx["maintenance_contract"] = draft_contract(
        ctx["project"]["id"],
        coverage_start=coverage_start,
        monthly_base_cents=monthly_base_cents,
    )
    return ctx


def setup_enrolled_warranty(**kwargs) -> dict:
    """Warranty transition ENROLLED on a DRAFT maintenance contract."""
    ctx = setup_drafted_contract(**kwargs)
    ctx["warranty_transition"] = enroll_warranty(
        ctx["warranty_transition"]["id"], ctx["maintenance_contract"]["id"]
    )
    ctx["maintenance_contract"] = read_maintenance_contract(
        ctx["maintenance_contract"]["id"]
    )
    return ctx


def setup_active_contract(**kwargs) -> dict:
    """Maintenance contract ACTIVE; the covered car is UNDER_CONTRACT."""
    ctx = setup_enrolled_warranty(**kwargs)
    ctx["maintenance_contract"] = activate_contract(ctx["maintenance_contract"]["id"])
    ctx["warranty_transition"] = read_warranty_transition(
        ctx["warranty_transition"]["id"]
    )
    ctx["car"] = read_car(ctx["car"]["id"])
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# --------------------------------------------------------------------------

def setup_orders_for_staging(
    order_specs: list,
    tier: str = "CONTROLLER_ONLY",
    base_price_cents: int = 5_000_000,
    **kwargs,
) -> dict:
    """Approved option carrying several ISSUED orders, one per spec.

    `order_specs` is a list of dicts accepted by the procurement order factory,
    e.g. [{"item_type": "CONTROLLER", "required_staging_sqft": 600}, ...].
    Used by the staging-yard capacity scenarios, where several holds must
    coexist against distinct orders.
    """
    ctx = setup_approved_option(tier=tier, base_price_cents=base_price_cents, **kwargs)
    orders = []
    for spec in order_specs:
        spec = dict(spec)
        orders.append(
            create_and_issue_order(
                ctx["scope_option"]["id"],
                item_type=spec.pop("item_type", "CONTROLLER"),
                lead_time_days=spec.pop("lead_time_days", 30),
                required_staging_sqft=spec.pop("required_staging_sqft", 400),
            )
        )
    ctx["procurement_orders"] = orders
    ctx["procurement_order"] = orders[0]
    return ctx


def setup_two_cars_ready_for_outage(
    min_cars_in_service: int = 0,
    max_concurrent_outages: int = 2,
    staging_area_sqft: int = 1200,
    num_cars: int = 2,
    **kwargs,
) -> dict:
    """`num_cars` cars in one group, each with its own installed equipment.

    Every car ends at work_status PROCURING with an approved option and an
    installed order, so outage windows can be planned on any of them.
    """
    ctx = setup_project_with_cars(
        num_cars=num_cars,
        min_cars_in_service=min_cars_in_service,
        max_concurrent_outages=max_concurrent_outages,
        staging_area_sqft=staging_area_sqft,
        **kwargs,
    )
    ctx["scope_options"] = []
    ctx["procurement_orders"] = []
    for index, car in enumerate(ctx["cars"]):
        survey = submit_survey(car["id"], surveyor_user_id=DEFAULT_SURVEYOR)
        countersign_survey(survey["id"], DEFAULT_COUNTERSIGNER)
        option = create_scope_option(
            ctx["project"]["id"], car["id"], base_price_cents=5_000_000
        )
        submit_scope_option(option["id"])
        option = approve_scope_option(ctx["project"]["id"], option["id"])
        ctx["scope_options"].append(option)
        order = create_and_issue_order(
            option["id"], required_staging_sqft=100 + index
        )
        reservation = hold_staging(
            ctx["project"]["id"],
            order["id"],
            sqft=100,
            hold_start="2026-08-02T00:00:00Z",
            hold_end="2026-08-03T00:00:00Z",
        )
        receive_order(order["id"], reservation["id"])
        ctx["procurement_orders"].append(install_order(order["id"]))
    ctx["scope_option"] = ctx["scope_options"][0]
    ctx["procurement_order"] = ctx["procurement_orders"][0]
    return ctx


def setup_two_groups_ready_for_outage(
    cars_per_group: tuple = (1, 1),
    min_cars_in_service: tuple = (0, 0),
    max_concurrent_outages: int = 2,
    **kwargs,
) -> dict:
    """Two groups whose cars all have installed equipment and can go on outage."""
    ctx = setup_project_with_two_groups(
        cars_per_group=cars_per_group,
        min_cars_in_service=min_cars_in_service,
        max_concurrent_outages=max_concurrent_outages,
        **kwargs,
    )
    ctx["scope_options"] = []
    ctx["procurement_orders"] = []
    for index, car in enumerate(ctx["cars"]):
        survey = submit_survey(car["id"])
        countersign_survey(survey["id"])
        option = create_scope_option(
            ctx["project"]["id"], car["id"], base_price_cents=5_000_000
        )
        submit_scope_option(option["id"])
        option = approve_scope_option(ctx["project"]["id"], option["id"])
        ctx["scope_options"].append(option)
        order = create_and_issue_order(option["id"], required_staging_sqft=100)
        reservation = hold_staging(
            ctx["project"]["id"],
            order["id"],
            sqft=100,
            hold_start="2026-08-02T00:00:00Z",
            hold_end="2026-08-03T00:00:00Z",
        )
        receive_order(order["id"], reservation["id"])
        ctx["procurement_orders"].append(install_order(order["id"]))
    return ctx


def setup_rejected_option(rejection_note: str = "price too high, cycle 1", **kwargs) -> dict:
    """Scope option submitted and then REJECTED, ready to be revised."""
    ctx = setup_scoped_car(**kwargs)
    submit_scope_option(ctx["scope_option"]["id"])
    ctx["scope_option"] = reject_scope_option(
        ctx["project"]["id"], ctx["scope_option"]["id"], rejection_note
    )
    return ctx


# --------------------------------------------------------------------------
# Tier 5 — finalization
# --------------------------------------------------------------------------

def setup_completed_project(**kwargs) -> dict:
    """The whole delivery run to the end: project COMPLETED, car UNDER_CONTRACT."""
    return setup_active_contract(**kwargs)
