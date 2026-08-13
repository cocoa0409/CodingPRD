"""Composite setup helpers.

These encapsulate the multi-step flows the PRD demands before interesting
behavior can be exercised: a permitted fair (sections 3.1-3.2), an open
operating day with cleared rides (section 3.4), sales and queues (3.5-3.6),
and teardown states (3.8). All helpers build state exclusively through
PRD-declared endpoints and return plain dicts of captured entities.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    INSPECTION_CLOCK_ISO,
    INSPECTION_DAY,
    OPERATING_CLOCK_ISO,
    OPERATING_DATE,
    SETUP_DAY_ISO,
    TEARDOWN_CLOCK_ISO,
    TEARDOWN_DATE,
)
from .factories import (
    create_appointment_payload,
    create_certification_payload,
    create_checklist_payload,
    create_cycle_payload,
    create_fair_payload,
    create_incident_payload,
    create_inspector_payload,
    create_observation_payload,
    create_operating_day_payload,
    create_product_payload,
    create_redemption_payload,
    create_ride_payload,
    create_sale_payload,
    create_shift_payload,
    create_staff_payload,
)
from .test_users import (
    make_admin_headers,
    make_clerk_headers,
    make_crew_headers,
    make_inspector_headers,
    make_manager_headers,
    make_operator_headers,
)

ADMIN = make_admin_headers()


def set_clock(iso: str):
    resp = api_client.set_clock({"to_iso8601": iso}, ADMIN)
    get_success_data(resp)


def create_fair(**overrides):
    resp = api_client.create_fair(create_fair_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_supervisor(fair_id: str, full_name: str = "Sup One"):
    resp = api_client.create_staff(
        create_staff_payload(fair_id, full_name=full_name, functions=["SUPERVISOR"]),
        ADMIN,
    )
    return get_success_data(resp)


def create_staff_via_manager(sup: dict, full_name: str, functions):
    """FairManager hires staff; the caller is scoped to their own fair."""
    resp = api_client.create_staff(
        create_staff_payload(sup["fair_id"], full_name=full_name, functions=functions),
        make_manager_headers(sup["id"]),
    )
    return get_success_data(resp)


def create_inspector(license_number: str, full_name: str = "Inspector", **overrides):
    resp = api_client.create_inspector(
        create_inspector_payload(full_name=full_name, license_number=license_number, **overrides),
        ADMIN,
    )
    return get_success_data(resp)


def create_ride(sup: dict, **overrides):
    resp = api_client.create_ride(create_ride_payload(sup["fair_id"], **overrides),
                                  make_manager_headers(sup["id"]))
    return get_success_data(resp)


def book_setup_shift(sup: dict, crew: dict, work_date: str = "2026-08-01",
                     start_hour: int = 6, end_hour: int = 10):
    """Create a SETUP CrewShift for the crew member at the crew's current version."""
    staff = get_success_data(api_client.get_staff(crew["id"], make_manager_headers(sup["id"])))
    resp = api_client.create_shift(
        create_shift_payload(crew["id"], staff["version"],
                             work_date=work_date, start_hour=start_hour,
                             end_hour=end_hour, shift_role="SETUP"),
        make_manager_headers(sup["id"]),
    )
    return get_success_data(resp)


def book_teardown_shift(sup: dict, crew: dict, work_date: str = TEARDOWN_DATE,
                        start_hour: int = 6, end_hour: int = 12):
    staff = get_success_data(api_client.get_staff(crew["id"], make_manager_headers(sup["id"])))
    resp = api_client.create_shift(
        create_shift_payload(crew["id"], staff["version"],
                             work_date=work_date, start_hour=start_hour,
                             end_hour=end_hour, shift_role="TEARDOWN"),
        make_manager_headers(sup["id"]),
    )
    return get_success_data(resp)


def verify_ride(crew: dict, ride_id: str):
    resp = api_client.verify_assembly(ride_id, {}, make_crew_headers(crew["id"]))
    return get_success_data(resp)


def request_permit(sup: dict):
    resp = api_client.request_permit(sup["fair_id"], {}, make_manager_headers(sup["id"]))
    return get_success_data(resp)


def schedule_fair_wide(sup: dict, scheduled_date: str = INSPECTION_DAY,
                       start_hour: int = 9, duration_hours: int = 2):
    resp = api_client.create_appointment(
        create_appointment_payload(sup["fair_id"], scheduled_date=scheduled_date,
                                   start_hour=start_hour, duration_hours=duration_hours),
        make_manager_headers(sup["id"]),
    )
    return get_success_data(resp)


def schedule_ride_audit(sup: dict, ride_id: str, scheduled_date: str = OPERATING_DATE,
                        start_hour: int = 15, duration_hours: int = 1):
    resp = api_client.create_appointment(
        create_appointment_payload(sup["fair_id"], scope="RIDE_AUDIT", ride_id=ride_id,
                                   scheduled_date=scheduled_date, start_hour=start_hour,
                                   duration_hours=duration_hours),
        make_manager_headers(sup["id"]),
    )
    return get_success_data(resp)


def complete_appointment(appointment: dict, outcome: str = "PASS", findings=None):
    payload = {"outcome": outcome}
    if findings is not None:
        payload["findings"] = findings
    resp = api_client.complete_appointment(
        appointment["id"], payload, make_inspector_headers(appointment["inspector_id"]))
    return get_success_data(resp)


def approve_permit(approver_inspector: dict, permit_id: str, fair_id: str, sup: dict):
    """Approve with a fresh fair read for the OCC handshake."""
    fair = get_success_data(api_client.get_fair(fair_id, make_manager_headers(sup["id"])))
    resp = api_client.approve_permit(
        permit_id, {"expected_fair_version": fair["version"]},
        make_inspector_headers(approver_inspector["id"]),
    )
    return get_success_data(resp)


def deny_permit(approver_inspector: dict, permit_id: str, reason: str = "failed inspection"):
    resp = api_client.deny_permit(permit_id, {"reason": reason},
                                  make_inspector_headers(approver_inspector["id"]))
    return get_success_data(resp)


def certify_operator(staff_id: str, ride_class: str = "THRILL", **overrides):
    resp = api_client.create_certification(
        create_certification_payload(staff_id, ride_class=ride_class, **overrides), ADMIN)
    return get_success_data(resp)


def setup_fair_with_staff(name: str = "Midway"):
    """Fair in SETUP + SUPERVISOR. Returns ctx dict."""
    set_clock(SETUP_DAY_ISO)
    fair = create_fair(name=name)
    sup = create_supervisor(fair["id"], full_name=f"Sup {name}")
    return {"fair": fair, "sup": sup}


def setup_verified_ride(name: str = "Midway", ride_overrides=None, num_extra_inspectors: int = 1):
    """Fair in SETUP + SUPERVISOR + CREW (with a SETUP shift today) + one
    SETUP_VERIFIED ride. Returns ctx with fair/sup/crew/ride/inspectors."""
    ctx = setup_fair_with_staff(name)
    sup = ctx["sup"]
    crew = create_staff_via_manager(sup, f"Crew {name}", ["CREW"])
    inspectors = [create_inspector(f"LIC-{name}-{i}") for i in range(num_extra_inspectors + 1)]
    ride = create_ride(sup, **(ride_overrides or {}))
    book_setup_shift(sup, crew)
    ride = verify_ride(crew, ride["id"])
    ctx.update({"crew": crew, "inspectors": inspectors, "ride": ride})
    return ctx


def setup_permit_requested(name: str = "Midway", ride_overrides=None):
    """Fair PERMIT_REQUESTED with a PENDING permit (estimated fee frozen)."""
    ctx = setup_verified_ride(name, ride_overrides=ride_overrides)
    permit = request_permit(ctx["sup"])
    ctx["permit"] = permit
    return ctx


def setup_permitted_fair(name: str = "Midway", ride_overrides=None,
                         operator_functions=("OPERATOR",), include_clerk: bool = False,
                         ride_class: str = "THRILL"):
    """Full permit lifecycle: fair PERMITTED, ride LICENSED, staff hired.

    Returns ctx with fair, sup, crew, op (optional), clerk (optional),
    inspectors (first inspector conducted the passing FAIR_WIDE, second
    approved the permit), ride, permit.
    """
    ctx = setup_permit_requested(name, ride_overrides=ride_overrides)
    sup = ctx["sup"]
    inspectors = ctx["inspectors"]
    appt = schedule_fair_wide(sup)
    set_clock(INSPECTION_CLOCK_ISO)
    appt = complete_appointment(appt, outcome="PASS")
    permit = approve_permit(inspectors[1], ctx["permit"]["id"], sup["fair_id"], sup)
    ctx["permit"] = permit
    ctx["fair"] = get_success_data(api_client.get_fair(sup["fair_id"], make_manager_headers(sup["id"])))
    ctx["ride"] = get_success_data(api_client.get_ride(ctx["ride"]["id"], make_manager_headers(sup["id"])))
    if operator_functions:
        op = create_staff_via_manager(sup, f"Op {name}", list(operator_functions))
        certify_operator(op["id"], ride_class=ride_class)
        ctx["op"] = op
    if include_clerk:
        ctx["clerk"] = create_staff_via_manager(sup, f"Clerk {name}", ["CLERK"])
    return ctx


def setup_open_day(name: str = "Midway", ride_overrides=None,
                   day_overrides=None, ride_class: str = "THRILL",
                   items_total: int = 5):
    """Permitted fair + one LICENSED ride + OperatingDay OPEN with a
    COUNTERSIGNED checklist. Returns ctx with day/chk plus base entities."""
    ctx = setup_permitted_fair(name, ride_overrides=ride_overrides,
                               include_clerk=True, ride_class=ride_class)
    sup = ctx["sup"]
    day_payload = create_operating_day_payload(sup["fair_id"], date=OPERATING_DATE,
                                               **(day_overrides or {}))
    day = get_success_data(api_client.create_operating_day(day_payload, make_manager_headers(sup["id"])))
    set_clock(OPERATING_CLOCK_ISO)
    get_success_data(api_client.begin_checklists(day["id"], {}, make_manager_headers(sup["id"])))
    chk = get_success_data(api_client.create_checklist(
        create_checklist_payload(ctx["ride"]["id"], day["id"], items_total=items_total),
        make_operator_headers(ctx["op"]["id"])))
    chk = get_success_data(api_client.submit_checklist(
        chk["id"], {"items_passed": items_total}, make_operator_headers(ctx["op"]["id"])))
    chk = get_success_data(api_client.countersign_checklist(
        chk["id"], {"expected_checklist_version": chk["version"]}, make_manager_headers(sup["id"])))
    day = get_success_data(api_client.open_gates(day["id"], {}, make_manager_headers(sup["id"])))
    ctx["day"] = day
    ctx["chk"] = chk
    return ctx


def create_product(sup: dict, **overrides):
    resp = api_client.create_product(create_product_payload(sup["fair_id"], **overrides),
                                     make_manager_headers(sup["id"]))
    return get_success_data(resp)


def sell(clerk: dict, product_id: str, day_id: str, **overrides):
    resp = api_client.create_sale(create_sale_payload(product_id, day_id, **overrides),
                                  make_clerk_headers(clerk["id"]))
    return get_success_data(resp)


def queue_redemption(op: dict, wristband_id: str, ride_id: str):
    resp = api_client.create_redemption(create_redemption_payload(wristband_id, ride_id),
                                        make_operator_headers(op["id"]))
    return get_success_data(resp)


def open_cycle(op: dict, ride_id: str, day_id: str):
    resp = api_client.create_cycle(create_cycle_payload(ride_id, day_id),
                                   make_operator_headers(op["id"]))
    return get_success_data(resp)


def cycle_action(op: dict, cycle_id: str, action: str):
    method = getattr(api_client, f"{action}_cycle")
    return get_success_data(method(cycle_id, {}, make_operator_headers(op["id"])))


def run_cycle(op: dict, ride_id: str, day_id: str):
    """Open, load, dispatch, and complete one cycle. Returns the completed cycle."""
    cyc = open_cycle(op, ride_id, day_id)
    cycle_action(op, cyc["id"], "load")
    cycle_action(op, cyc["id"], "dispatch")
    return cycle_action(op, cyc["id"], "complete")


def file_incident(caller: dict, role: str, ride_id: str, day_id: str, **overrides):
    if role == "operator":
        headers = make_operator_headers(caller["id"])
    else:
        headers = make_manager_headers(caller["id"])
    resp = api_client.create_incident(create_incident_payload(ride_id, day_id, **overrides), headers)
    return get_success_data(resp)


def record_wind(sup: dict, day_id: str, wind_speed_mph: int):
    resp = api_client.create_observation(
        create_observation_payload(day_id, wind_speed_mph=wind_speed_mph),
        make_manager_headers(sup["id"]))
    return get_success_data(resp)


def get_ride(sup: dict, ride_id: str):
    return get_success_data(api_client.get_ride(ride_id, make_manager_headers(sup["id"])))


def get_day(sup: dict, day_id: str):
    return get_success_data(api_client.get_operating_day(day_id, make_manager_headers(sup["id"])))


def get_permit(sup: dict, permit_id: str):
    return get_success_data(api_client.get_permit(permit_id, make_manager_headers(sup["id"])))


def get_sale(sup: dict, sale_id: str):
    return get_success_data(api_client.get_sale(sale_id, make_manager_headers(sup["id"])))


def get_redemption(sup: dict, redemption_id: str):
    return get_success_data(api_client.get_redemption(redemption_id, make_manager_headers(sup["id"])))


def get_cycle(sup: dict, cycle_id: str):
    return get_success_data(api_client.get_cycle(cycle_id, make_manager_headers(sup["id"])))


def get_checklist(sup: dict, checklist_id: str):
    return get_success_data(api_client.get_checklist(checklist_id, make_manager_headers(sup["id"])))


def get_staff_member(sup: dict, staff_id: str):
    return get_success_data(api_client.get_staff(staff_id, make_manager_headers(sup["id"])))


def get_shift(sup: dict, shift_id: str):
    return get_success_data(api_client.get_shift(shift_id, make_manager_headers(sup["id"])))


def create_dual_role_supervisor(fair_id: str, full_name: str = "Sup Dual"):
    """StateProgramAdmin seeds the first supervisor; this one also carries the
    OPERATOR function (used by segregation-of-duties probes)."""
    resp = api_client.create_staff(
        create_staff_payload(fair_id, full_name=full_name,
                             functions=["OPERATOR", "SUPERVISOR"]),
        ADMIN,
    )
    return get_success_data(resp)


def open_checklist(op: dict, ride_id: str, day_id: str, items_total: int = 5):
    resp = api_client.create_checklist(
        create_checklist_payload(ride_id, day_id, items_total=items_total),
        make_operator_headers(op["id"]))
    return get_success_data(resp)


def submit_checklist(op: dict, checklist_id: str, items_passed: int):
    resp = api_client.submit_checklist(
        checklist_id, {"items_passed": items_passed}, make_operator_headers(op["id"]))
    return get_success_data(resp)


def countersign_checklist(sup: dict, checklist_id: str):
    """Countersign with a fresh read of the checklist version (OCC handshake)."""
    chk = get_success_data(api_client.get_checklist(checklist_id, make_manager_headers(sup["id"])))
    resp = api_client.countersign_checklist(
        checklist_id, {"expected_checklist_version": chk["version"]},
        make_manager_headers(sup["id"]))
    return get_success_data(resp)


def reject_checklist(sup: dict, checklist_id: str, reason: str = "rework required"):
    resp = api_client.reject_checklist(
        checklist_id, {"reason": reason}, make_manager_headers(sup["id"]))
    return get_success_data(resp)


def begin_day(ctx: dict, **day_overrides):
    """Create the operating day, move the clock to its morning, and begin the
    checklist phase. Stores the resulting day in ctx["day"]."""
    sup = ctx["sup"]
    day = get_success_data(api_client.create_operating_day(
        create_operating_day_payload(sup["fair_id"], **day_overrides),
        make_manager_headers(sup["id"])))
    set_clock(OPERATING_CLOCK_ISO)
    day = get_success_data(api_client.begin_checklists(day["id"], {}, make_manager_headers(sup["id"])))
    ctx["day"] = day
    return day


def clear_ride(ctx: dict, ride_id: str, items_total: int = 3):
    """Open, submit, and countersign the checklist for (ride, ctx["day"])."""
    chk = open_checklist(ctx["op"], ride_id, ctx["day"]["id"], items_total=items_total)
    submit_checklist(ctx["op"], chk["id"], items_total)
    return countersign_checklist(ctx["sup"], chk["id"])


def open_gates(ctx: dict):
    day = get_success_data(api_client.open_gates(
        ctx["day"]["id"], {}, make_manager_headers(ctx["sup"]["id"])))
    ctx["day"] = day
    return day


def setup_two_ride_permitted_fair(name: str = "Midway", ride1_overrides=None,
                                  ride2_overrides=None):
    """Permitted fair with TWO licensed rides; the operator is certified for
    THRILL and FAMILY; clerk and crew hired; two inspectors (the first
    conducted the passing FAIR_WIDE, the second approved the permit)."""
    ctx = setup_fair_with_staff(name)
    sup = ctx["sup"]
    crew = create_staff_via_manager(sup, f"Crew {name}", ["CREW"])
    op = create_staff_via_manager(sup, f"Op {name}", ["OPERATOR"])
    clerk = create_staff_via_manager(sup, f"Clerk {name}", ["CLERK"])
    inspectors = [create_inspector(f"LIC-{name}-{i}") for i in range(2)]
    r1_over = {"name": "Coaster", "serial_number": f"SN-{name}-1"}
    r1_over.update(ride1_overrides or {})
    r2_over = {"name": "Swings", "serial_number": f"SN-{name}-2",
               "ride_class": "FAMILY", "min_rider_height_in": 40,
               "max_rider_height_in": 84, "wind_limit_mph": 25}
    r2_over.update(ride2_overrides or {})
    ride1 = create_ride(sup, **r1_over)
    ride2 = create_ride(sup, **r2_over)
    book_setup_shift(sup, crew, end_hour=12)
    ride1 = verify_ride(crew, ride1["id"])
    ride2 = verify_ride(crew, ride2["id"])
    permit = request_permit(sup)
    appt = schedule_fair_wide(sup)
    set_clock(INSPECTION_CLOCK_ISO)
    complete_appointment(appt, outcome="PASS")
    permit = approve_permit(inspectors[1], permit["id"], sup["fair_id"], sup)
    certify_operator(op["id"], ride_class="THRILL")
    certify_operator(op["id"], ride_class="FAMILY")
    ctx.update({"crew": crew, "op": op, "clerk": clerk, "inspectors": inspectors,
                "ride": ride1, "ride1": ride1, "ride2": ride2, "permit": permit})
    return ctx


def setup_two_open_fairs(name: str = "XF"):
    """Two independent fairs, each fully permitted with one licensed THRILL
    ride and an OPEN operating day on the same date. Inspector assignments are
    staggered so the shared pool serves both fairs, and each permit is approved
    by the inspector who did not conduct that fair's passing inspection."""
    set_clock(SETUP_DAY_ISO)
    fair_a = create_fair(name=f"Fair {name} A")
    fair_b = create_fair(name=f"Fair {name} B", operator_company_name="OtherCo")
    sup_a = create_supervisor(fair_a["id"], full_name=f"Sup {name} A")
    sup_b = create_supervisor(fair_b["id"], full_name=f"Sup {name} B")
    op_a = create_staff_via_manager(sup_a, f"Op {name} A", ["OPERATOR"])
    clerk_a = create_staff_via_manager(sup_a, f"Clerk {name} A", ["CLERK"])
    crew_a = create_staff_via_manager(sup_a, f"Crew {name} A", ["CREW"])
    op_b = create_staff_via_manager(sup_b, f"Op {name} B", ["OPERATOR"])
    crew_b = create_staff_via_manager(sup_b, f"Crew {name} B", ["CREW"])
    insp1 = create_inspector(f"LIC-{name}-1", full_name="Insp One")
    insp2 = create_inspector(f"LIC-{name}-2", full_name="Insp Two")
    ride_a = create_ride(sup_a, name="Coaster A", serial_number=f"SN-{name}-A")
    ride_b = create_ride(sup_b, name="Coaster B", serial_number=f"SN-{name}-B")
    book_setup_shift(sup_a, crew_a)
    book_setup_shift(sup_b, crew_b)
    verify_ride(crew_a, ride_a["id"])
    verify_ride(crew_b, ride_b["id"])
    permit_a = request_permit(sup_a)
    permit_b = request_permit(sup_b)
    appt_a = schedule_fair_wide(sup_a, start_hour=9)
    appt_b = schedule_fair_wide(sup_b, start_hour=14)
    set_clock(INSPECTION_CLOCK_ISO)
    complete_appointment(appt_a, outcome="PASS")
    complete_appointment(appt_b, outcome="PASS")
    approver_a = insp2 if appt_a["inspector_id"] == insp1["id"] else insp1
    approver_b = insp1 if appt_b["inspector_id"] == insp2["id"] else insp2
    approve_permit(approver_a, permit_a["id"], sup_a["fair_id"], sup_a)
    approve_permit(approver_b, permit_b["id"], sup_b["fair_id"], sup_b)
    certify_operator(op_a["id"], ride_class="THRILL")
    certify_operator(op_b["id"], ride_class="THRILL")
    ctx_a = {"fair": fair_a, "sup": sup_a, "op": op_a, "clerk": clerk_a,
             "crew": crew_a, "ride": ride_a}
    ctx_b = {"fair": fair_b, "sup": sup_b, "op": op_b, "crew": crew_b,
             "ride": ride_b}
    begin_day(ctx_a)
    clear_ride(ctx_a, ride_a["id"])
    open_gates(ctx_a)
    begin_day(ctx_b)
    clear_ride(ctx_b, ride_b["id"])
    open_gates(ctx_b)
    return {"a": ctx_a, "b": ctx_b, "inspectors": [insp1, insp2]}
