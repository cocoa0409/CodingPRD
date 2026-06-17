"""Composite setup helpers.

These encapsulate the multi-step API sequences needed to drive the system into
the states that test claims assert. They use get_success_data() internally so a
broken setup surfaces a clear "Setup step failed" message rather than a confusing
assertion failure.

Identity threading: a Customer/Technician acting on their own resource is
ownership-gated, so callers thread the real entity id via make_customer_headers /
make_technician_headers (never the shared TEST_USERS constants).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import (
    TEST_USERS, make_customer_headers, make_technician_headers,
)
from .factories import (
    create_customer_payload, create_technician_payload,
    create_membership_plan_payload, create_membership_payload,
    create_material_sku_payload, create_truck_stock_item_payload,
    create_service_job_payload, create_estimate_payload,
    create_dispatch_payload, create_permit_payload,
    create_material_usage_payload, create_callback_payload,
)

DISP = TEST_USERS["dispatcher_headers"]
INSP = TEST_USERS["inspector_headers"]


# ─── Tier 0: clock ────────────────────────────────────────────────────────
def set_clock(iso: str):
    """Pin the server's logical UTC clock (PRD §2.9)."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, DISP))


# ─── Tier 1: base catalog entities ────────────────────────────────────────
def make_customer(**overrides) -> dict:
    return get_success_data(api.create_customer(create_customer_payload(**overrides), DISP))


def make_technician(**overrides) -> dict:
    return get_success_data(api.create_technician(create_technician_payload(**overrides), DISP))


def make_membership_plan(**overrides) -> dict:
    return get_success_data(api.create_membership_plan(create_membership_plan_payload(**overrides), DISP))


def enroll_membership(customer_id, plan_id, **overrides) -> dict:
    return get_success_data(
        api.create_membership(create_membership_payload(customer_id, plan_id, **overrides), DISP)
    )


def make_sku(**overrides) -> dict:
    return get_success_data(api.create_material_sku(create_material_sku_payload(**overrides), DISP))


def stock_truck(technician_id, sku_id, **overrides) -> dict:
    return get_success_data(
        api.create_truck_stock_item(create_truck_stock_item_payload(technician_id, sku_id, **overrides), DISP)
    )


def make_job(customer_id, **overrides) -> dict:
    return get_success_data(api.create_service_job(create_service_job_payload(customer_id, **overrides), DISP))


def current_job_version(job_id) -> int:
    return get_success_data(api.get_service_job(job_id, DISP))["version"]


# ─── Tier 2: estimate lifecycle to QUOTED ─────────────────────────────────
def create_estimate(job_id, expected_job_version, **overrides) -> dict:
    return get_success_data(
        api.create_estimate(create_estimate_payload(job_id, expected_job_version, **overrides), DISP)
    )


def quote_and_accept(job_id, customer_id, **estimate_overrides):
    """Create an estimate on a DRAFT job, send it, and have the owning customer accept it.
    Returns (estimate, accepted_estimate). Job is left in QUOTED.
    Reads the live job version for the create (handles any prior version bumps).
    """
    v = current_job_version(job_id)
    est = create_estimate(job_id, v, **estimate_overrides)
    get_success_data(api.send_estimate(est["id"], DISP))
    accepted = get_success_data(api.accept_estimate(est["id"], make_customer_headers(customer_id)))
    return est, accepted


# ─── Tier 3: dispatch lifecycle ───────────────────────────────────────────
def dispatch_tech(job_id, technician_id, window_start, window_end, **overrides) -> dict:
    """Create a dispatch on a QUOTED job using the live job version. Returns the dispatch."""
    v = current_job_version(job_id)
    return get_success_data(
        api.create_dispatch(
            create_dispatch_payload(job_id, technician_id, v, window_start, window_end, **overrides), DISP
        )
    )


def depart_and_arrive(dispatch_id, technician_id):
    """Drive a dispatch ASSIGNED -> EN_ROUTE -> ON_SITE (job -> IN_PROGRESS)."""
    th = make_technician_headers(technician_id)
    get_success_data(api.depart_dispatch(dispatch_id, th))
    return get_success_data(api.arrive_dispatch(dispatch_id, th))


# ─── Tier 4: state-progression shortcuts ──────────────────────────────────
def setup_quoted_job(zone="100", scope="OUTLET", job_class="SERVICE",
                     priority="STANDARD", flat_rate_cents=10000,
                     customer_overrides=None, **estimate_overrides):
    """Customer + DRAFT job carried to QUOTED via an accepted FLAT_RATE estimate.
    Returns dict: {customer, job}.
    """
    cust = make_customer(**(customer_overrides or {"service_zip": zone + "01"}))
    job = make_job(cust["id"], scope=scope, job_class=job_class, priority=priority)
    if estimate_overrides.get("pricing_mode") == "TIME_MATERIALS":
        quote_and_accept(job["id"], cust["id"], **estimate_overrides)
    else:
        quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE",
                         flat_rate_cents=flat_rate_cents, **estimate_overrides)
    return {"customer": cust, "job": job}


def setup_scheduled_job(zone="100", license_class="JOURNEYMAN", on_call=False,
                        scope="OUTLET", priority="STANDARD", flat_rate_cents=10000,
                        window_start="2030-01-01T09:00:00Z",
                        window_end="2030-01-01T10:00:00Z"):
    """Quoted job + matching-zone technician dispatched (job -> SCHEDULED).
    Returns dict: {customer, technician, job, dispatch}.
    """
    cust = make_customer(service_zip=zone + "01")
    tech = make_technician(service_zone=zone, license_class=license_class, on_call=on_call)
    job = make_job(cust["id"], scope=scope, priority=priority)
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=flat_rate_cents)
    disp = dispatch_tech(job["id"], tech["id"], window_start, window_end)
    return {"customer": cust, "technician": tech, "job": job, "dispatch": disp}


def setup_in_progress_job(zone="100", license_class="JOURNEYMAN", scope="OUTLET",
                          priority="STANDARD", flat_rate_cents=10000,
                          window_start="2030-01-01T09:00:00Z",
                          window_end="2030-01-01T10:00:00Z"):
    """Scheduled job whose technician has departed and arrived (job -> IN_PROGRESS).
    Returns dict: {customer, technician, job, dispatch}.
    """
    s = setup_scheduled_job(zone=zone, license_class=license_class, scope=scope,
                            priority=priority, flat_rate_cents=flat_rate_cents,
                            window_start=window_start, window_end=window_end)
    depart_and_arrive(s["dispatch"]["id"], s["technician"]["id"])
    return s


def complete_job(job_id, technician_id, actual_labor_hours=None) -> dict:
    payload = {} if actual_labor_hours is None else {"actual_labor_hours": actual_labor_hours}
    return get_success_data(api.complete_service_job(job_id, payload, make_technician_headers(technician_id)))


def invoice_job(job_id) -> dict:
    return get_success_data(api.invoice_service_job(job_id, DISP))


def setup_completed_job(**kwargs) -> dict:
    """In-progress job driven to COMPLETED. Returns {customer, technician, job, dispatch}."""
    actual_labor_hours = kwargs.pop("actual_labor_hours", None)
    s = setup_in_progress_job(**kwargs)
    complete_job(s["job"]["id"], s["technician"]["id"], actual_labor_hours=actual_labor_hours)
    return s


def setup_invoiced_job(clock_iso="2030-06-01T08:00:00Z", **kwargs) -> dict:
    """Full lifecycle to INVOICED with a pinned clock. Returns
    {customer, technician, job, dispatch, invoiced_job}.
    """
    if clock_iso:
        set_clock(clock_iso)
    s = setup_completed_job(**kwargs)
    s["invoiced_job"] = invoice_job(s["job"]["id"])
    return s


# ─── Tier 5: permit lifecycle ─────────────────────────────────────────────
def file_permit(job_id, **overrides) -> dict:
    return get_success_data(api.create_permit(create_permit_payload(job_id, **overrides), DISP))


def issue_permit(permit_id) -> dict:
    return get_success_data(api.issue_permit(permit_id, INSP))


def schedule_inspection(permit_id, inspection_at) -> dict:
    return get_success_data(api.schedule_inspection(permit_id, {"inspection_at": inspection_at}, DISP))


def record_inspection(permit_id, result) -> dict:
    return get_success_data(api.record_inspection(permit_id, {"result": result}, INSP))


def setup_permit_passed(permit_job_id, inspection_at="2030-01-02T09:00:00Z") -> dict:
    """Drive a permit APPLIED -> ISSUED -> INSPECTION_SCHEDULED -> PASSED for a job."""
    p = file_permit(permit_job_id)
    issue_permit(p["id"])
    schedule_inspection(p["id"], inspection_at)
    record_inspection(p["id"], "PASS")
    return p


# ─── Tier 6: material usage ───────────────────────────────────────────────
def record_usage(job_id, technician_id, sku_id, quantity) -> dict:
    return get_success_data(
        api.create_material_usage(
            create_material_usage_payload(job_id, technician_id, sku_id, quantity),
            make_technician_headers(technician_id),
        )
    )


def void_usage(usage_id, technician_id) -> dict:
    return get_success_data(api.void_material_usage(usage_id, make_technician_headers(technician_id)))


# ─── Tier 7: callbacks / warranty loop ────────────────────────────────────
def file_callback(job_id, customer_id, **overrides) -> dict:
    return get_success_data(
        api.create_callback(create_callback_payload(job_id, **overrides), make_customer_headers(customer_id))
    )


def setup_warranty_open_job(clock_iso="2030-06-01T08:00:00Z", **kwargs):
    """Invoiced job + a warranty-covered callback filed (job -> WARRANTY, callback OPEN).
    Returns dict: {customer, technician, job, dispatch, invoiced_job, callback}.
    """
    s = setup_invoiced_job(clock_iso=clock_iso, **kwargs)
    s["callback"] = file_callback(s["job"]["id"], s["customer"]["id"])
    return s
