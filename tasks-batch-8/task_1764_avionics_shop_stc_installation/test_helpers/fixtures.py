"""Composite setup helpers.

Every test starts against an empty database, so these helpers walk the full
PRD workflow chains (register -> open -> design -> quote -> approve -> induct
-> labor -> testing -> closeout) and return a bundle dict of the entities
built along the way. Setup calls use the lenient get_success_data() so a
failed precondition surfaces as a clear setup error.

Bundle keys (present once the corresponding step has run):
    customer, aircraft, work_order, design, orders (list), tasks (list),
    ground_test, flight_test, package, wb_revision
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_aircraft_payload,
    create_customer_payload,
    create_install_task_payload,
    create_panel_design_payload,
    create_regulatory_package_payload,
    create_test_event_payload,
    create_weight_balance_revision_payload,
    create_work_order_payload,
    make_equipment_line,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_inspector_headers,
    make_technician_headers,
)

MANAGER = TEST_USERS["shop_manager_headers"]

# Standard two-line equipment list reused by procurement / quote / reweigh
# scenarios (GTN750XI + GFC500).
TWO_LINE_EQUIPMENT = [
    make_equipment_line("GTN750XI", 1700000, 6.26, 14.43, 21,
                        description="GPS Nav"),
    make_equipment_line("GFC500", 900000, 3.74, 20.44, 14,
                        description="Autopilot"),
]

ONE_RADIO_EQUIPMENT = [
    make_equipment_line("GTR225", 500000, 3.0, 15.0, 14,
                        description="Comm radio"),
]

# W&B addition that keeps the default 1800.0 @ 40.0 datum on its arm.
WB_NEUTRAL_ADDITION = [{"description": "unit", "weight_lb": 10.0, "arm_in": 40.0}]


# ---------------------------------------------------------------------------
# Tier 0: atomic builders
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    return get_success_data(api_client.set_clock(to_iso8601, MANAGER))


def create_customer(name="Test Customer", contact_email="customer@example.com",
                    customer_kind="INDIVIDUAL"):
    payload = create_customer_payload(name=name, contact_email=contact_email,
                                      customer_kind=customer_kind)
    return get_success_data(api_client.create_customer(payload, MANAGER))


def create_aircraft(customer_id, **overrides):
    return get_success_data(
        api_client.create_aircraft(create_aircraft_payload(customer_id, **overrides),
                                   MANAGER))


def create_work_order(aircraft_id, **overrides):
    return get_success_data(
        api_client.create_work_order(create_work_order_payload(aircraft_id, **overrides),
                                     MANAGER))


def create_panel_design(work_order, equipment_list=None, layout_notes="panel layout"):
    """Author a revision; the OCC token is the work order's current version."""
    payload = create_panel_design_payload(
        work_order["id"],
        expected_work_order_version=work_order["version"],
        layout_notes=layout_notes,
        equipment_list=list(equipment_list) if equipment_list is not None else [],
    )
    return get_success_data(api_client.create_panel_design(payload, MANAGER))


def get_work_order(work_order_id):
    return get_success_data(api_client.get_work_order(work_order_id, MANAGER))


def get_aircraft(aircraft_id):
    return get_success_data(api_client.get_aircraft(aircraft_id, MANAGER))


def get_panel_design(panel_design_id):
    return get_success_data(api_client.get_panel_design(panel_design_id, MANAGER))


def get_install_task(task_id):
    return get_success_data(api_client.get_install_task(task_id, MANAGER))


def get_test_event(test_event_id):
    return get_success_data(api_client.get_test_event(test_event_id, MANAGER))


def get_regulatory_package(package_id):
    return get_success_data(api_client.get_regulatory_package(package_id, MANAGER))


def get_wb_revision(revision_id):
    return get_success_data(api_client.get_weight_balance_revision(revision_id, MANAGER))


def list_work_order_equipment_orders(work_order_id):
    return get_success_data(
        api_client.list_equipment_orders(MANAGER,
                                         params={"work_order_id": work_order_id}))


# ---------------------------------------------------------------------------
# Tier 1: work-order state progression
# ---------------------------------------------------------------------------

def setup_draft_work_order(equipment_list=None, customer_kind="INDIVIDUAL",
                           work_order_overrides=None, aircraft_overrides=None,
                           customer_name="Test Customer",
                           customer_email="customer@example.com",
                           layout_notes="panel layout", clock=DEFAULT_CLOCK,
                           with_design=True):
    """Customer + aircraft + DRAFT work order, plus a DRAFT design when
    with_design is true (equipment_list selects the design's lines)."""
    set_clock(clock)
    customer = create_customer(name=customer_name, contact_email=customer_email,
                               customer_kind=customer_kind)
    aircraft = create_aircraft(customer["id"], **(aircraft_overrides or {}))
    work_order = create_work_order(aircraft["id"], **(work_order_overrides or {}))
    bundle = {
        "customer": customer,
        "aircraft": aircraft,
        "work_order": work_order,
        "design": None,
        "orders": [],
        "tasks": [],
    }
    if with_design:
        bundle["design"] = create_panel_design(
            work_order, equipment_list=equipment_list, layout_notes=layout_notes)
        bundle["work_order"] = get_work_order(work_order["id"])
    return bundle


def setup_pending_approval(equipment_list=None, **kwargs):
    """DRAFT design submitted + quote submitted -> work order PENDING_APPROVAL,
    design SUBMITTED."""
    bundle = setup_draft_work_order(equipment_list=equipment_list, **kwargs)
    get_success_data(api_client.submit_panel_design(bundle["design"]["id"], MANAGER))
    bundle["design"] = get_panel_design(bundle["design"]["id"])
    bundle["work_order"] = get_success_data(
        api_client.submit_quote(bundle["work_order"]["id"], MANAGER))
    return bundle


def setup_approved_work_order(equipment_list=None, **kwargs):
    """Customer APPROVE on the submitted design. Empty equipment list leaves the
    work order APPROVED; a non-empty list cascades it to PARTS_PENDING and
    auto-creates one PLANNED DESIGN_RELEASE order per line."""
    bundle = setup_pending_approval(equipment_list=equipment_list, **kwargs)
    customer_headers = make_customer_headers(bundle["customer"]["id"])
    bundle["design"] = get_success_data(
        api_client.decide_panel_design(bundle["design"]["id"], "APPROVE",
                                       customer_headers))
    bundle["work_order"] = get_work_order(bundle["work_order"]["id"])
    bundle["orders"] = list_work_order_equipment_orders(bundle["work_order"]["id"])
    return bundle


def setup_installation_work_order(equipment_list=None, **kwargs):
    """Approved work order with every outstanding order received, inducted to
    INSTALLATION (inducted_at stamped from the logical clock)."""
    bundle = setup_approved_work_order(equipment_list=equipment_list, **kwargs)
    for order in bundle["orders"]:
        if order["status"] == "PLANNED":
            get_success_data(api_client.mark_ordered(order["id"], MANAGER))
            get_success_data(api_client.receive_equipment_order(order["id"], MANAGER))
    bundle["orders"] = list_work_order_equipment_orders(bundle["work_order"]["id"])
    bundle["work_order"] = get_success_data(
        api_client.begin_installation(bundle["work_order"]["id"], MANAGER))
    return bundle


# ---------------------------------------------------------------------------
# Tier 2: install-task lifecycle
# ---------------------------------------------------------------------------

def create_task(work_order_id, task_kind="INSTALLATION", estimated_hours=2.0,
                description="install task"):
    payload = create_install_task_payload(
        work_order_id, task_kind=task_kind, estimated_hours=estimated_hours,
        description=description)
    return get_success_data(api_client.create_install_task(payload, MANAGER))


def start_task(task_id, technician_id="tech-1"):
    return get_success_data(
        api_client.start_task(task_id, make_technician_headers(technician_id)))


def complete_task(task_id, actual_hours, technician_id="tech-1"):
    return get_success_data(
        api_client.complete_task(task_id, actual_hours,
                                 make_technician_headers(technician_id)))


def verify_task(task_id, inspector_id="insp-1"):
    return get_success_data(
        api_client.verify_task(task_id, make_inspector_headers(inspector_id)))


def work_task_to_completed(work_order_id, task_kind="INSTALLATION",
                           estimated_hours=2.0, actual_hours=2.0,
                           technician_id="tech-1"):
    task = create_task(work_order_id, task_kind=task_kind,
                       estimated_hours=estimated_hours)
    start_task(task["id"], technician_id=technician_id)
    return complete_task(task["id"], actual_hours, technician_id=technician_id)


def work_task_to_verified(work_order_id, task_kind="INSTALLATION",
                          estimated_hours=2.0, actual_hours=2.0,
                          technician_id="tech-1", inspector_id="insp-1"):
    task = work_task_to_completed(work_order_id, task_kind=task_kind,
                                  estimated_hours=estimated_hours,
                                  actual_hours=actual_hours,
                                  technician_id=technician_id)
    return verify_task(task["id"], inspector_id=inspector_id)


# ---------------------------------------------------------------------------
# Tier 3: testing stage
# ---------------------------------------------------------------------------

def setup_testing_work_order(equipment_list=None, task_kind="INSTALLATION",
                             estimated_hours=2.0, actual_hours=2.0,
                             technician_id="tech-1", inspector_id="insp-1",
                             **kwargs):
    """Inducted work order plus one VERIFIED task, moved to TESTING."""
    bundle = setup_installation_work_order(equipment_list=equipment_list, **kwargs)
    task = work_task_to_verified(
        bundle["work_order"]["id"], task_kind=task_kind,
        estimated_hours=estimated_hours, actual_hours=actual_hours,
        technician_id=technician_id, inspector_id=inspector_id)
    bundle["tasks"] = [task]
    bundle["work_order"] = get_success_data(
        api_client.begin_testing(bundle["work_order"]["id"], MANAGER))
    return bundle


def schedule_test_event(work_order_id, test_kind="GROUND",
                        scheduled_start="2026-08-05T10:00:00Z",
                        scheduled_end="2026-08-05T11:00:00Z"):
    payload = create_test_event_payload(
        work_order_id, test_kind=test_kind, scheduled_start=scheduled_start,
        scheduled_end=scheduled_end)
    return get_success_data(api_client.create_test_event(payload, MANAGER))


def record_test_result(test_event_id, result, inspector_id="insp-1"):
    return get_success_data(
        api_client.record_result(test_event_id, result,
                                 make_inspector_headers(inspector_id)))


def reschedule_event(test_event_id, scheduled_start, scheduled_end):
    return get_success_data(
        api_client.reschedule_test_event(test_event_id, scheduled_start,
                                         scheduled_end, MANAGER))


def pass_ground_and_flight(bundle, ground_start="2026-08-05T10:00:00Z",
                           ground_end="2026-08-05T11:00:00Z",
                           flight_start="2026-08-06T14:00:00Z",
                           flight_end="2026-08-06T15:30:00Z",
                           inspector_id="insp-1"):
    """One GROUND test PASSED then one FLIGHT test PASSED (ground pass is the
    flight-scheduling gate)."""
    work_order_id = bundle["work_order"]["id"]
    ground = schedule_test_event(work_order_id, test_kind="GROUND",
                                 scheduled_start=ground_start,
                                 scheduled_end=ground_end)
    bundle["ground_test"] = record_test_result(ground["id"], "PASS",
                                               inspector_id=inspector_id)
    flight = schedule_test_event(work_order_id, test_kind="FLIGHT",
                                 scheduled_start=flight_start,
                                 scheduled_end=flight_end)
    bundle["flight_test"] = record_test_result(flight["id"], "PASS",
                                               inspector_id=inspector_id)
    return bundle


# ---------------------------------------------------------------------------
# Tier 4: regulatory package and weight & balance
# ---------------------------------------------------------------------------

def create_regulatory_package(work_order_id, approval_path="STC",
                              stc_number="STC-SA1000"):
    payload = create_regulatory_package_payload(
        work_order_id, approval_path=approval_path)
    if approval_path == "STC":
        payload["stc_number"] = stc_number
    else:
        payload.pop("stc_number", None)
    return get_success_data(api_client.create_regulatory_package(payload, MANAGER))


def submit_package(package_id):
    return get_success_data(api_client.submit_regulatory_package(package_id, MANAGER))


def record_package_decision(package_id, decision, inspector_id="insp-1"):
    return get_success_data(
        api_client.record_decision(package_id, decision,
                                   make_inspector_headers(inspector_id)))


def approve_stc_package(work_order_id, stc_number="STC-SA1000",
                        inspector_id="insp-1"):
    """STC package walked DRAFT -> CONFORMITY_REVIEW -> APPROVED."""
    package = create_regulatory_package(work_order_id, approval_path="STC",
                                        stc_number=stc_number)
    submit_package(package["id"])
    return record_package_decision(package["id"], "APPROVED",
                                   inspector_id=inspector_id)


def create_wb_revision(work_order_id, method="INCREMENTAL", added_items=None,
                       removed_weight_lb=0, removed_arm_in=None):
    overrides = {"method": method}
    if added_items is not None:
        overrides["added_items"] = added_items
    if removed_weight_lb:
        overrides["removed_weight_lb"] = removed_weight_lb
        overrides["removed_arm_in"] = removed_arm_in
    payload = create_weight_balance_revision_payload(work_order_id, **overrides)
    return get_success_data(api_client.create_weight_balance_revision(payload, MANAGER))


def accept_wb_revision(revision_id, inspector_id="insp-1"):
    return get_success_data(
        api_client.accept_weight_balance_revision(
            revision_id, make_inspector_headers(inspector_id)))


def create_and_accept_wb_revision(work_order_id, method="INCREMENTAL",
                                  added_items=None, removed_weight_lb=0,
                                  removed_arm_in=None, inspector_id="insp-1"):
    revision = create_wb_revision(
        work_order_id, method=method,
        added_items=WB_NEUTRAL_ADDITION if added_items is None else added_items,
        removed_weight_lb=removed_weight_lb, removed_arm_in=removed_arm_in)
    return accept_wb_revision(revision["id"], inspector_id=inspector_id)


# ---------------------------------------------------------------------------
# Tier 5: closeout-ready terminal setup
# ---------------------------------------------------------------------------

def setup_closeout_ready_work_order(equipment_list=None, task_kind="INSTALLATION",
                                    estimated_hours=2.0, actual_hours=2.0,
                                    stc_number="STC-SA1000",
                                    wb_added_items=None, **kwargs):
    """Full chain: TESTING work order with GROUND+FLIGHT PASSED, an APPROVED
    STC package, and an ACCEPTED W&B revision — every closeout gate satisfied.
    The logical clock stays where the caller (or default setup) put it."""
    bundle = setup_testing_work_order(
        equipment_list=equipment_list, task_kind=task_kind,
        estimated_hours=estimated_hours, actual_hours=actual_hours, **kwargs)
    pass_ground_and_flight(bundle)
    bundle["package"] = approve_stc_package(bundle["work_order"]["id"],
                                            stc_number=stc_number)
    bundle["wb_revision"] = create_and_accept_wb_revision(
        bundle["work_order"]["id"], added_items=wb_added_items)
    bundle["work_order"] = get_work_order(bundle["work_order"]["id"])
    return bundle
