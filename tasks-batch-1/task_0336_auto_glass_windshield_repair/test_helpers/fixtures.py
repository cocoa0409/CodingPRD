"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared endpoints,
because the harness resets the database before every test. Fixtures use
get_success_data() (lenient) so setup failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Identity threading: Technician is entity_backed, so any call the technician
performs (check-in, start-service, finish-install, recalibration actions) uses
make_technician_headers(technician_id). Customer is entity_backed too; ownership
gated calls use make_customer_headers(customer_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_technician_headers,
    make_customer_headers,
)
from . import factories as f

ADVISOR = TEST_USERS["service_advisor_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Pin the server clock (ShopManager-only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, MANAGER))


# ---------------------------------------------------------------------------
# Tier 0: primitive creators (single POST + capture)
# ---------------------------------------------------------------------------
def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(f.create_customer_payload(**overrides), ADVISOR))


def create_vehicle(customer_id, **overrides) -> dict:
    return get_success_data(api_client.create_vehicle(f.create_vehicle_payload(customer_id, **overrides), ADVISOR))


def create_glass_part(**overrides) -> dict:
    return get_success_data(api_client.create_glass_part(f.create_glass_part_payload(**overrides), MANAGER))


def create_technician(**overrides) -> dict:
    return get_success_data(api_client.create_technician(f.create_technician_payload(**overrides), MANAGER))


def create_service_bay(**overrides) -> dict:
    return get_success_data(api_client.create_service_bay(f.create_service_bay_payload(**overrides), MANAGER))


def create_work_order(customer_id, vehicle_id, **overrides) -> dict:
    return get_success_data(api_client.create_work_order(
        f.create_work_order_payload(customer_id, vehicle_id, **overrides), ADVISOR))


def create_assessment(work_order_id, **overrides) -> dict:
    return get_success_data(api_client.create_damage_assessment(
        work_order_id, f.create_damage_assessment_payload(**overrides), ADVISOR))


# ---------------------------------------------------------------------------
# Tier 1: customer+vehicle bootstrap
# ---------------------------------------------------------------------------
def setup_customer_and_vehicle(state="CA", adas_equipped=False, oem="FW0TEST"):
    """A customer and a vehicle. Returns (customer, vehicle)."""
    cust = create_customer(service_address_state=state)
    veh = create_vehicle(cust["id"], adas_equipped=adas_equipped, glass_part_number=oem)
    return cust, veh


# ---------------------------------------------------------------------------
# Tier 2: work order through ASSESSED (decision frozen, quote computed)
# ---------------------------------------------------------------------------
def setup_assessed_work_order(decision="REPAIR", adas_equipped=False, state="CA", oem="FW0TEST"):
    """Open a work order, record an assessment producing the requested decision,
    and accept it. Returns (customer, vehicle, work_order_after_accept, assessment_id).

    decision must be REPAIR or REPLACE; REPLACE on adas_equipped vehicle yields
    recalibration later. The assessment payload is chosen to force the recommendation.
    """
    cust, veh = setup_customer_and_vehicle(state=state, adas_equipped=adas_equipped, oem=oem)
    wo = create_work_order(cust["id"], veh["id"])
    if decision == "REPLACE":
        asmt_payload = f.replace_assessment_payload()
    else:
        asmt_payload = f.create_damage_assessment_payload()
    asmt = get_success_data(api_client.create_damage_assessment(wo["id"], asmt_payload, ADVISOR))
    wo2 = get_success_data(api_client.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR))
    return cust, veh, wo2, asmt["id"]


# ---------------------------------------------------------------------------
# Tier 2b: reserve a part for a REPLACE work order
# ---------------------------------------------------------------------------
def reserve_part(work_order_id, work_order_version, oem="FW0TEST", adas_compatible=False, on_hand_qty=5):
    """Create a glass part with stock and reserve it for the work order.
    Returns (glass_part, part_order). Caller supplies the current WO version."""
    part = create_glass_part(oem_part_number=oem, adas_compatible=adas_compatible, on_hand_qty=on_hand_qty)
    po = get_success_data(api_client.create_part_order(
        f.create_part_order_payload(work_order_id, part["id"], work_order_version), ADVISOR))
    return part, po


# ---------------------------------------------------------------------------
# Tier 3: book + schedule (ASSESSED -> SCHEDULED)
# ---------------------------------------------------------------------------
def book_appointment(work_order_id, technician_id, service_location, start_at, end_at, service_bay_id=None):
    payload = f.create_service_appointment_payload(
        work_order_id, technician_id, service_location, start_at, end_at)
    if service_bay_id is not None:
        payload["service_bay_id"] = service_bay_id
    return get_success_data(api_client.create_service_appointment(payload, ADVISOR))


def schedule(work_order_id, appointment_id):
    return get_success_data(api_client.schedule_work_order(
        work_order_id, {"appointment_id": appointment_id}, ADVISOR))


# ---------------------------------------------------------------------------
# Tier 3b: full lifecycle to IN_SERVICE
# ---------------------------------------------------------------------------
def setup_in_service(decision="REPAIR", adas_equipped=False, state="CA",
                     start_at="2026-06-13T08:00:00Z", end_at="2026-06-13T08:59:00Z",
                     on_hand_qty=5, clock="2026-06-13T09:00:00Z"):
    """Drive a work order to IN_SERVICE.

    For REPLACE, a part is reserved first (adas_compatible matches the vehicle).
    Returns a dict with: customer, vehicle, work_order (IN_SERVICE), technician,
    bay, appointment, glass_part (or None), part_order (or None).
    """
    if clock is not None:
        set_clock(clock)
    oem = "FW0SVC"
    cust, veh, wo, asmt_id = setup_assessed_work_order(
        decision=decision, adas_equipped=adas_equipped, state=state, oem=oem)
    tech = create_technician(can_mobile=False, adas_certified=adas_equipped, home_state="CA")
    bay = create_service_bay(name="Svc Install Bay", bay_type="INSTALL")
    glass_part = None
    part_order = None
    if decision == "REPLACE":
        glass_part, part_order = reserve_part(
            wo["id"], wo["version"], oem=oem,
            adas_compatible=adas_equipped, on_hand_qty=on_hand_qty)
    appt = book_appointment(wo["id"], tech["id"], "IN_SHOP", start_at, end_at, service_bay_id=bay["id"])
    schedule(wo["id"], appt["id"])
    tech_headers = make_technician_headers(tech["id"])
    get_success_data(api_client.check_in_appointment(appt["id"], tech_headers))
    wo_is = get_success_data(api_client.start_service(wo["id"], tech_headers))
    return {
        "customer": cust, "vehicle": veh, "work_order": wo_is,
        "technician": tech, "bay": bay, "appointment": appt,
        "glass_part": glass_part, "part_order": part_order,
        "tech_headers": tech_headers,
    }


# ---------------------------------------------------------------------------
# Tier 4: REPLACE through finish-install (-> CURING or AWAITING_RECALIBRATION)
# ---------------------------------------------------------------------------
def setup_after_finish_install(adas_equipped=False, temp_c=25, humidity_pct=40,
                               state="CA", clock="2026-06-13T09:00:00Z", on_hand_qty=5):
    """Drive a REPLACE work order through finish-install.

    adas_equipped=True -> AWAITING_RECALIBRATION; False -> CURING.
    Returns the dict from setup_in_service plus work_order (post finish-install).
    """
    ctx = setup_in_service(decision="REPLACE", adas_equipped=adas_equipped,
                           state=state, clock=clock, on_hand_qty=on_hand_qty)
    wo = get_success_data(api_client.finish_install(
        ctx["work_order"]["id"], {"temp_c": temp_c, "humidity_pct": humidity_pct},
        ctx["tech_headers"]))
    ctx["work_order"] = wo
    return ctx


# ---------------------------------------------------------------------------
# Tier 4b: REPLACE+ADAS through to a SCHEDULED RecalibrationJob
# ---------------------------------------------------------------------------
def setup_awaiting_recalibration_with_job(
        temp_c=25, humidity_pct=40, clock="2026-06-13T09:00:00Z",
        rc_start="2026-06-13T09:10:00Z", rc_end="2026-06-13T09:40:00Z"):
    """REPLACE+ADAS work order in AWAITING_RECALIBRATION with a SCHEDULED STATIC
    RecalibrationJob (certified tech, CALIBRATION bay).

    Returns the finish-install ctx plus calibration_bay and recalibration_job.
    """
    ctx = setup_after_finish_install(adas_equipped=True, temp_c=temp_c,
                                     humidity_pct=humidity_pct, clock=clock)
    cbay = create_service_bay(name="Recal Calib Bay", bay_type="CALIBRATION")
    tech_id = ctx["technician"]["id"]
    wo = ctx["work_order"]
    rc = get_success_data(api_client.create_recalibration_job(
        f.create_recalibration_job_payload(
            wo["id"], tech_id, "STATIC", rc_start, rc_end, wo["version"],
            service_bay_id=cbay["id"]),
        ctx["tech_headers"]))
    ctx["calibration_bay"] = cbay
    ctx["recalibration_job"] = rc
    return ctx


# ---------------------------------------------------------------------------
# Tier 4c: drive an existing vehicle to AWAITING_RECALIBRATION reusing a shared
# technician and install bay (used for shared-CALIBRATION-bay overlap tests).
# ---------------------------------------------------------------------------
def drive_adas_vehicle_to_awaiting_recalibration(
        customer_id, vehicle_id, technician_id, install_bay_id, tech_headers,
        oem, appt_start, appt_end, temp_c=25, humidity_pct=40):
    """Open + assess(REPLACE) + reserve part + book in-shop appt + schedule +
    check-in + start-service + finish-install for an ADAS vehicle. Returns the
    work order (AWAITING_RECALIBRATION). Caller supplies a non-overlapping appt
    window for the shared technician."""
    wo = create_work_order(customer_id, vehicle_id)
    asmt = get_success_data(api_client.create_damage_assessment(
        wo["id"], f.replace_assessment_payload(), ADVISOR))
    wo2 = get_success_data(api_client.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR))
    part = create_glass_part(oem_part_number=oem, adas_compatible=True, on_hand_qty=5)
    get_success_data(api_client.create_part_order(
        f.create_part_order_payload(wo["id"], part["id"], wo2["version"]), ADVISOR))
    appt = book_appointment(wo["id"], technician_id, "IN_SHOP", appt_start, appt_end, service_bay_id=install_bay_id)
    schedule(wo["id"], appt["id"])
    get_success_data(api_client.check_in_appointment(appt["id"], tech_headers))
    get_success_data(api_client.start_service(wo["id"], tech_headers))
    wo_fin = get_success_data(api_client.finish_install(
        wo["id"], {"temp_c": temp_c, "humidity_pct": humidity_pct}, tech_headers))
    return wo_fin


# ---------------------------------------------------------------------------
# Tier 5: pay a work order in full
# ---------------------------------------------------------------------------
def pay_in_full(work_order_id, amount_cents, method="CARD"):
    return get_success_data(api_client.create_payment(
        f.create_payment_payload(work_order_id, amount_cents, method), ADVISOR))


# ---------------------------------------------------------------------------
# Tier 5b: REPAIR work order completed (warranty issued)
# ---------------------------------------------------------------------------
def setup_completed_repair(clock="2026-06-13T09:00:00Z"):
    """A REPAIR work order driven to COMPLETED (warranty ACTIVE issued).
    Returns (work_order_completed, warranty)."""
    ctx = setup_in_service(decision="REPAIR", adas_equipped=False, clock=clock)
    wo = ctx["work_order"]
    pay_in_full(wo["id"], 9657, "CASH")
    wo_done = get_success_data(api_client.complete_work_order(wo["id"], ADVISOR))
    wlist = get_success_data(api_client.list_work_order_warranties(wo["id"], ADVISOR))
    warranty = wlist[0] if isinstance(wlist, list) and wlist else None
    return wo_done, warranty
