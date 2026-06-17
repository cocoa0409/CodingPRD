"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims in this domain require the system to be driven through a
long chain — create config, create a customer/technician, open a job, dispatch +
confirm + depart + arrive to ON_SITE, build/present/approve an estimate, start
work, complete — before the behavior under test can even be exercised. These
helpers encapsulate those chains so tests focus on assertions.

Uses get_success_data() (lenient validator) internally so a broken setup surfaces
as a clear "Setup failed" error rather than a confusing assertion failure.

Identity threading: any Technician-owned or Customer-owned call uses the
per-instance header builder seeded with the real entity id (PRD §2.1 ownership).
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    membership_plan_payload, flat_rate_item_payload, part_payload,
    customer_payload, technician_payload, inspector_payload,
    truck_stock_payload, service_job_payload, dispatch_assignment_payload,
    estimate_payload, flat_rate_line_payload, part_line_payload,
    inspection_payload, callback_payload,
)
from .test_users import (
    TEST_USERS, make_technician_headers, make_customer_headers,
)

OM = TEST_USERS["office_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]

# Monotonic suffix source so composite fixtures that mint reference data
# (e.g. a flat-rate item) can be invoked more than once in a single test
# without colliding on the PRD §3.1 "code is unique across the book" rule.
_unique_seq = itertools.count(1)


# ─── Clock control ────────────────────────────────────────────────────
def set_clock(to_iso8601):
    """Pin the server clock to a fixed UTC instant (PRD §3.10)."""
    return get_success_data(api_client.set_clock(to_iso8601, OM))


# ─── Tier 0: Config & people primitives ───────────────────────────────
def create_membership_plan(**overrides):
    return get_success_data(api_client.create_membership_plan(
        membership_plan_payload(**overrides), OM))


def create_flat_rate_item(**overrides):
    return get_success_data(api_client.create_flat_rate_item(
        flat_rate_item_payload(**overrides), OM))


def create_part(**overrides):
    return get_success_data(api_client.create_part(part_payload(**overrides), OM))


def create_customer(**overrides):
    return get_success_data(api_client.create_customer(customer_payload(**overrides), OM))


def create_technician(**overrides):
    return get_success_data(api_client.create_technician(technician_payload(**overrides), OM))


def create_inspector(**overrides):
    return get_success_data(api_client.create_inspector(inspector_payload(**overrides), OM))


def create_truck_stock(technician_id, part_id, **overrides):
    return get_success_data(api_client.create_truck_stock(
        truck_stock_payload(technician_id, part_id, **overrides), OM))


def create_service_job(customer_id, **overrides):
    return get_success_data(api_client.create_service_job(
        service_job_payload(customer_id, **overrides), DISP))


# ─── Tier 1: Dispatch progression ──────────────────────────────────────
def propose_assignment(job_id, technician_id, expected_job_version,
                       window_start, window_end, eta):
    return get_success_data(api_client.create_dispatch_assignment(
        dispatch_assignment_payload(job_id, technician_id, expected_job_version,
                                    window_start, window_end, eta), DISP))


def drive_job_to_on_site(job, technician_id, window_start, window_end, eta):
    """Propose -> confirm -> depart -> arrive. Returns (assignment, job-after-arrive).

    Confirm cascades the job RECEIVED -> DISPATCHED (freezing after_hours); depart and
    arrive walk it to ON_SITE. Technician-owned calls thread the real technician id.
    """
    tech_h = make_technician_headers(technician_id)
    asg = propose_assignment(job["id"], technician_id, job["version"],
                             window_start, window_end, eta)
    get_success_data(api_client.confirm_assignment(asg["id"], DISP))
    get_success_data(api_client.depart_assignment(asg["id"], tech_h))
    get_success_data(api_client.arrive_assignment(asg["id"], tech_h))
    job_after = get_success_data(api_client.get_service_job(job["id"], tech_h))
    return asg, job_after


# ─── Tier 2: Estimate construction ─────────────────────────────────────
def create_estimate_on_job(job_id, expected_job_version, technician_id):
    tech_h = make_technician_headers(technician_id)
    return get_success_data(api_client.create_estimate(
        job_id, estimate_payload(expected_job_version), tech_h))


def add_flat_rate_line(est_id, flat_rate_item_id, technician_id, quantity=1):
    tech_h = make_technician_headers(technician_id)
    return get_success_data(api_client.add_estimate_line(
        est_id, flat_rate_line_payload(flat_rate_item_id, quantity), tech_h))


def add_part_line(est_id, part_id, technician_id, quantity=1):
    tech_h = make_technician_headers(technician_id)
    return get_success_data(api_client.add_estimate_line(
        est_id, part_line_payload(part_id, quantity), tech_h))


def present_estimate(est_id, technician_id):
    tech_h = make_technician_headers(technician_id)
    return get_success_data(api_client.present_estimate(est_id, tech_h))


def approve_estimate(est_id, customer_id):
    cust_h = make_customer_headers(customer_id)
    return get_success_data(api_client.approve_estimate(est_id, cust_h))


# ─── Tier 3: Full job lifecycle composites ─────────────────────────────
def setup_on_site_job(*, customer_overrides=None, technician_overrides=None,
                      job_overrides=None, window_start, window_end, eta):
    """Open a job and drive it to ON_SITE with a confirmed/arrived assignment.

    Returns a dict with customer, technician, job (ON_SITE), assignment.
    """
    customer = create_customer(**(customer_overrides or {}))
    technician = create_technician(**(technician_overrides or {}))
    job = create_service_job(customer["id"], **(job_overrides or {}))
    asg, job_on_site = drive_job_to_on_site(
        job, technician["id"], window_start, window_end, eta)
    return {
        "customer": customer,
        "technician": technician,
        "job": job_on_site,
        "assignment": asg,
    }


def setup_presented_estimate(*, flat_rate_lines, part_lines=None,
                             customer_overrides=None, technician_overrides=None,
                             job_overrides=None, window_start, window_end, eta):
    """Drive a job to ON_SITE, build an estimate with the given lines, present it.

    flat_rate_lines: list of dicts {item: <flat_rate_item dict>, quantity: int}.
    part_lines: list of dicts {part: <part dict>, quantity: int}.
    Returns dict with customer, technician, job, assignment, estimate (PRESENTED).
    """
    scenario = setup_on_site_job(
        customer_overrides=customer_overrides,
        technician_overrides=technician_overrides,
        job_overrides=job_overrides,
        window_start=window_start, window_end=window_end, eta=eta)
    tech_id = scenario["technician"]["id"]
    job = scenario["job"]
    estimate = create_estimate_on_job(job["id"], job["version"], tech_id)
    for fl in flat_rate_lines:
        add_flat_rate_line(estimate["id"], fl["item"]["id"], tech_id,
                           fl.get("quantity", 1))
    for pl in (part_lines or []):
        add_part_line(estimate["id"], pl["part"]["id"], tech_id, pl.get("quantity", 1))
    estimate = present_estimate(estimate["id"], tech_id)
    scenario["estimate"] = estimate
    return scenario


def setup_authorized_job(*, flat_rate_lines, part_lines=None,
                         customer_overrides=None, technician_overrides=None,
                         job_overrides=None, window_start, window_end, eta):
    """Through to AUTHORIZED: present estimate then customer approves it.

    Returns dict with customer, technician, job (AUTHORIZED), assignment, estimate (APPROVED).
    """
    scenario = setup_presented_estimate(
        flat_rate_lines=flat_rate_lines, part_lines=part_lines,
        customer_overrides=customer_overrides,
        technician_overrides=technician_overrides,
        job_overrides=job_overrides,
        window_start=window_start, window_end=window_end, eta=eta)
    estimate = approve_estimate(scenario["estimate"]["id"], scenario["customer"]["id"])
    scenario["estimate"] = estimate
    scenario["job"] = get_success_data(
        api_client.get_service_job(scenario["job"]["id"], DISP))
    return scenario


def start_work(job_id, technician_id):
    tech_h = make_technician_headers(technician_id)
    return get_success_data(api_client.start_work(job_id, tech_h))


def complete_job(job_id, technician_id, consumed_parts=None):
    tech_h = make_technician_headers(technician_id)
    payload = {"consumed_parts": consumed_parts or []}
    return get_success_data(api_client.complete_job(job_id, payload, tech_h))


def setup_completed_job(*, flat_rate_lines, part_lines=None, consumed_parts=None,
                        customer_overrides=None, technician_overrides=None,
                        job_overrides=None, window_start, window_end, eta):
    """Full lifecycle through COMPLETED (no permit on the job).

    Returns dict with customer, technician, job (COMPLETED), assignment, estimate.
    """
    scenario = setup_authorized_job(
        flat_rate_lines=flat_rate_lines, part_lines=part_lines,
        customer_overrides=customer_overrides,
        technician_overrides=technician_overrides,
        job_overrides=job_overrides,
        window_start=window_start, window_end=window_end, eta=eta)
    tech_id = scenario["technician"]["id"]
    # Completion consumes parts out of the technician's truck stock (PRD §3.7):
    # every consumed part must have a truck-stock row whose quantity covers the
    # units claimed, else completion is correctly rejected ERR_INSUFFICIENT_STOCK.
    # Provision one truck-stock row per distinct consumed part before completing.
    truck_stocks = {}
    for cp in (consumed_parts or []):
        pid = cp["part_id"]
        units = cp.get("units", 0)
        if pid not in truck_stocks:
            truck_stocks[pid] = create_truck_stock(
                tech_id, pid, quantity=units, reorder_point=0)
        else:
            truck_stocks[pid] = create_truck_stock(
                tech_id, pid,
                quantity=truck_stocks[pid]["quantity"] + units,
                reorder_point=0)
    start_work(scenario["job"]["id"], tech_id)
    job_completed = complete_job(scenario["job"]["id"], tech_id, consumed_parts)
    scenario["job"] = job_completed
    scenario["truck_stocks"] = truck_stocks
    return scenario


# ─── Tier 4: Permit lifecycle composites ───────────────────────────────
def get_job_permit(job_id):
    """Return the (single) permit auto-created for a job, or None."""
    data, _meta = _list(api_client.list_job_permits(job_id, OM))
    return data[0] if data else None


def issue_permit(permit_id):
    return get_success_data(api_client.issue_permit(permit_id, OM))


def schedule_inspection(permit_id, inspector_id, scheduled_date):
    return get_success_data(api_client.schedule_inspection(
        permit_id, inspection_payload(inspector_id, scheduled_date), OM))


def record_inspection(inspection_id, result):
    return get_success_data(api_client.record_inspection(
        inspection_id, {"result": result}, OM))


def setup_permit_job_issued(*, jurisdiction, scheduled_date=None,
                            window_start, window_end, eta, clock=None):
    """Permit-requiring job authorized and started; permit auto-created and ISSUED.

    The customer's service_address is set to the jurisdiction code so the
    auto-created permit's derived jurisdiction matches the inspector.  Returns dict with
    customer, technician (licensed), job (IN_PROGRESS), estimate, permit (ISSUED),
    flat_rate_item.
    """
    if clock:
        set_clock(clock)
    fr_item = create_flat_rate_item(
        code="PMT-FR-%d" % next(_unique_seq), category="WATER_HEATER",
        base_price_cents=40000, skill_required=2, requires_permit=True)
    scenario = setup_authorized_job(
        flat_rate_lines=[{"item": fr_item, "quantity": 1}],
        customer_overrides={"service_address": jurisdiction,
                            "credit_limit_cents": 1000000},
        technician_overrides={"skill_level": 3, "licensed_for_permits": True},
        job_overrides={"category": "WATER_HEATER"},
        window_start=window_start, window_end=window_end, eta=eta)
    permit = get_job_permit(scenario["job"]["id"])
    permit = issue_permit(permit["id"])
    scenario["permit"] = permit
    scenario["flat_rate_item"] = fr_item
    return scenario


def schedule_inspection_on_issued_permit(permit, inspector_id, scheduled_date):
    """ISSUED -> INSPECTION_SCHEDULED; returns the created InspectionVisit."""
    return schedule_inspection(permit["id"], inspector_id, scheduled_date)


def setup_permit_job_in_progress_scheduled(*, jurisdiction, inspector_id,
                                           scheduled_date, window_start,
                                           window_end, eta, clock=None):
    """Permit-requiring job authorized, permit issued + inspection scheduled
    (permit INSPECTION_SCHEDULED, not PASSED), then job started (IN_PROGRESS).

    Returns dict with customer, technician, job (IN_PROGRESS), estimate, permit
    (INSPECTION_SCHEDULED), inspection_visit, flat_rate_item.
    """
    scenario = setup_permit_job_issued(
        jurisdiction=jurisdiction, window_start=window_start,
        window_end=window_end, eta=eta, clock=clock)
    visit = schedule_inspection(scenario["permit"]["id"], inspector_id, scheduled_date)
    start_work(scenario["job"]["id"], scenario["technician"]["id"])
    scenario["inspection_visit"] = visit
    scenario["permit"] = get_success_data(
        api_client.get_permit(scenario["permit"]["id"], OM))
    scenario["job"] = get_success_data(
        api_client.get_service_job(scenario["job"]["id"], DISP))
    return scenario


def setup_completed_permit_job(*, jurisdiction, inspector_id, scheduled_date,
                               window_start, window_end, eta, clock=None,
                               consumed_parts=None):
    """Full lifecycle for a permit-requiring job through COMPLETED: permit issued,
    inspection scheduled and recorded PASSED, then job started and completed.

    Returns dict with customer, technician, job (COMPLETED), estimate, permit
    (PASSED), inspection_visit, flat_rate_item.
    """
    scenario = setup_permit_job_issued(
        jurisdiction=jurisdiction, window_start=window_start,
        window_end=window_end, eta=eta, clock=clock)
    visit = schedule_inspection(scenario["permit"]["id"], inspector_id, scheduled_date)
    record_inspection(visit["id"], "PASSED")
    tech_id = scenario["technician"]["id"]
    start_work(scenario["job"]["id"], tech_id)
    job_completed = complete_job(scenario["job"]["id"], tech_id, consumed_parts)
    scenario["job"] = job_completed
    scenario["permit"] = get_success_data(
        api_client.get_permit(scenario["permit"]["id"], OM))
    scenario["inspection_visit"] = visit
    return scenario


# ─── Tier 5: Callback composites ───────────────────────────────────────
def file_callback(original_job_id, customer_id, reason="Test callback"):
    cust_h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_callback(
        callback_payload(original_job_id, reason), cust_h))


def accept_callback(callback_id):
    return get_success_data(api_client.accept_callback(callback_id, OM))


def setup_reopened_job(*, flat_rate_lines, part_lines=None, consumed_parts=None,
                       customer_overrides=None, technician_overrides=None,
                       job_overrides=None, window_start, window_end, eta, clock=None):
    """Drive a job through COMPLETED, file an in-warranty callback, accept it so the
    job moves COMPLETED -> REOPENED.

    Returns dict with customer, technician, job (REOPENED), estimate, callback (ACCEPTED).
    """
    if clock:
        set_clock(clock)
    scenario = setup_completed_job(
        flat_rate_lines=flat_rate_lines, part_lines=part_lines,
        consumed_parts=consumed_parts,
        customer_overrides=customer_overrides,
        technician_overrides=technician_overrides,
        job_overrides=job_overrides,
        window_start=window_start, window_end=window_end, eta=eta)
    callback = file_callback(scenario["job"]["id"], scenario["customer"]["id"],
                             "Defect reported")
    accept_callback(callback["id"])
    scenario["callback"] = get_success_data(
        api_client.get_callback(callback["id"], OM))
    scenario["job"] = get_success_data(
        api_client.get_service_job(scenario["job"]["id"], DISP))
    return scenario


# ─── Tier 6: Callback-rate accumulation (six completed jobs) ────────────
def run_one_completed_job(customer_id, technician_id, flat_rate_item_id,
                          window_start, window_end, eta):
    """Open + dispatch + arrive + estimate (one FLAT_RATE line) + approve + start +
    complete a single job for the given customer/technician. Returns the COMPLETED job."""
    job = create_service_job(customer_id, category="DRAIN")
    asg, job_on_site = drive_job_to_on_site(
        job, technician_id, window_start, window_end, eta)
    estimate = create_estimate_on_job(job["id"], job_on_site["version"], technician_id)
    add_flat_rate_line(estimate["id"], flat_rate_item_id, technician_id, 1)
    present_estimate(estimate["id"], technician_id)
    approve_estimate(estimate["id"], customer_id)
    start_work(job["id"], technician_id)
    return complete_job(job["id"], technician_id, [])


# ─── Internal helper ────────────────────────────────────────────────────
def _list(response):
    """Return (data_list, meta) from a list response, lenient on envelope shape."""
    body = response.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    return data, meta
