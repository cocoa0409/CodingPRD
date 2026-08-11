"""Composite setup helpers for multi-step test prerequisites.

Fixtures use get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_crew_member_payload,
    create_damage_claim_payload,
    create_gear_inspection_payload,
    create_incident_payload,
    create_job_order_payload,
    create_pilot_booking_payload,
    create_pilot_payload,
    create_tariff_rate_payload,
    create_tug_assignment_payload,
    create_tug_payload,
    create_vessel_payload,
    create_watch_rotation_payload,
    create_weather_restriction_payload,
)
from .test_users import (
    TEST_USERS,
    make_pilot_headers,
    make_tug_captain_headers,
    make_vessel_agent_headers,
)


# ─── Tier 1: Reference data primitives ────────────────


def create_vessel(**overrides):
    res = api_client.create_vessel(
        create_vessel_payload(**overrides), TEST_USERS["port_admin_headers"]
    )
    return get_success_data(res)


def create_tug(**overrides):
    res = api_client.create_tug(
        create_tug_payload(**overrides), TEST_USERS["port_admin_headers"]
    )
    return get_success_data(res)


def create_pilot(**overrides):
    res = api_client.create_pilot(
        create_pilot_payload(**overrides), TEST_USERS["port_admin_headers"]
    )
    return get_success_data(res)


def create_crew_member(**overrides):
    res = api_client.create_crew_member(
        create_crew_member_payload(**overrides), TEST_USERS["port_admin_headers"]
    )
    return get_success_data(res)


def create_tariff_rate(**overrides):
    res = api_client.create_tariff_rate(
        create_tariff_rate_payload(**overrides), TEST_USERS["port_admin_headers"]
    )
    return get_success_data(res)


def set_clock(to_iso8601: str):
    res = api_client.set_clock(
        {"to_iso8601": to_iso8601}, TEST_USERS["port_admin_headers"]
    )
    return get_success_data(res)


def record_passed_inspection(tug_id: str, **overrides):
    res = api_client.create_gear_inspection(
        create_gear_inspection_payload(tug_id, outcome="PASSED", **overrides),
        TEST_USERS["marine_surveyor_headers"],
    )
    return get_success_data(res)


def record_failed_inspection(tug_id: str, **overrides):
    res = api_client.create_gear_inspection(
        create_gear_inspection_payload(tug_id, outcome="FAILED", **overrides),
        TEST_USERS["marine_surveyor_headers"],
    )
    return get_success_data(res)


# ─── Tier 2: Job lifecycle primitives ─────────────────


def create_job_order(vessel_id: str, tariff_rate_id: str, **overrides):
    res = api_client.create_job_order(
        create_job_order_payload(vessel_id, tariff_rate_id, **overrides),
        make_vessel_agent_headers(vessel_id),
    )
    return get_success_data(res)


def confirm_job_order(job_order_id: str):
    res = api_client.confirm_job_order(
        job_order_id, TEST_USERS["port_dispatcher_headers"]
    )
    return get_success_data(res)


def propose_assignment(job_order_id: str, tug_id: str, expected_job_order_version: int, **overrides):
    res = api_client.create_tug_assignment(
        create_tug_assignment_payload(
            job_order_id, tug_id, expected_job_order_version, **overrides
        ),
        TEST_USERS["port_dispatcher_headers"],
    )
    return get_success_data(res)


def confirm_assignment(assignment_id: str, tug_id: str):
    res = api_client.confirm_tug_assignment(
        assignment_id, make_tug_captain_headers(tug_id)
    )
    return get_success_data(res)


def propose_pilot_booking(job_order_id: str, pilot_id: str, **overrides):
    res = api_client.create_pilot_booking(
        create_pilot_booking_payload(job_order_id, pilot_id, **overrides),
        TEST_USERS["port_dispatcher_headers"],
    )
    return get_success_data(res)


def confirm_booking(booking_id: str, pilot_id: str):
    res = api_client.confirm_pilot_booking(
        booking_id, make_pilot_headers(pilot_id)
    )
    return get_success_data(res)


def dispatch_job(job_order_id: str):
    res = api_client.dispatch_job_order(
        job_order_id, TEST_USERS["port_dispatcher_headers"]
    )
    return get_success_data(res)


def start_job(job_order_id: str):
    res = api_client.start_job_order(
        job_order_id, TEST_USERS["port_dispatcher_headers"]
    )
    return get_success_data(res)


def complete_job(job_order_id: str):
    res = api_client.complete_job_order(
        job_order_id, TEST_USERS["port_dispatcher_headers"]
    )
    return get_success_data(res)


def cancel_job_order(job_order_id: str, **overrides):
    res = api_client.cancel_job_order(
        job_order_id, overrides, TEST_USERS["port_dispatcher_headers"]
    )
    return get_success_data(res)


def get_job(job_order_id: str):
    res = api_client.get_job_order(
        job_order_id, TEST_USERS["port_dispatcher_headers"]
    )
    return get_success_data(res)


def get_invoice_for_job(job_order_id: str):
    """Return the single auto-created invoice for a job."""
    res = api_client.list_invoices(
        TEST_USERS["port_dispatcher_headers"], params={"job_order_id": job_order_id}
    )
    data = get_success_data(res)
    assert isinstance(data, list) and len(data) >= 1, (
        f"Expected at least one invoice for job {job_order_id}"
    )
    return data[0]


def finalize_invoice(invoice_id: str, expected_invoice_version: int):
    res = api_client.finalize_invoice(
        invoice_id,
        {"expected_invoice_version": expected_invoice_version},
        TEST_USERS["port_dispatcher_headers"],
    )
    return get_success_data(res)


def void_invoice(invoice_id: str, **overrides):
    payload = {}
    payload.update(overrides)
    res = api_client.void_invoice(
        invoice_id, payload, TEST_USERS["port_admin_headers"]
    )
    return get_success_data(res)


# ─── Tier 3: Composite job chains ─────────────────────


def setup_reference_data(
    tug_overrides=None,
    vessel_overrides=None,
    pilot_overrides=None,
    tariff_overrides=None,
):
    """Create a tug, vessel, pilot, and tariff with the standard defaults.
    Returns (tug, vessel, pilot, tariff)."""
    tug = create_tug(**(tug_overrides or {}))
    vessel = create_vessel(**(vessel_overrides or {}))
    pilot = create_pilot(**(pilot_overrides or {}))
    tariff = create_tariff_rate(**(tariff_overrides or {}))
    return tug, vessel, pilot, tariff


def setup_confirmed_job(
    clock_iso: str = "2026-06-01T00:00:00Z",
    tug_overrides=None,
    vessel_overrides=None,
    pilot_overrides=None,
    tariff_overrides=None,
    job_overrides=None,
    assignment_overrides=None,
    booking_overrides=None,
    with_pilot_booking: bool = True,
    confirm_booking_flag: bool = True,
):
    """Standard chain to a CONFIRMED job with a CONFIRMED assignment and (optionally)
    a CONFIRMED pilot booking. Returns a dict with every entity plus the current
    job version after assignment creation."""
    tug, vessel, pilot, tariff = setup_reference_data(
        tug_overrides=tug_overrides,
        vessel_overrides=vessel_overrides,
        pilot_overrides=pilot_overrides,
        tariff_overrides=tariff_overrides,
    )
    set_clock(clock_iso)
    job = create_job_order(
        vessel["id"], tariff["id"], **(job_overrides or {})
    )
    job = confirm_job_order(job["id"])
    record_passed_inspection(tug["id"])
    asg = propose_assignment(
        job["id"],
        tug["id"],
        job["version"],
        window_start=job["scheduled_start"],
        window_end=job["scheduled_end"],
        **(assignment_overrides or {}),
    )
    asg = confirm_assignment(asg["id"], tug["id"])
    booking = None
    if with_pilot_booking:
        booking = propose_pilot_booking(
            job["id"],
            pilot["id"],
            window_start=job["scheduled_start"],
            window_end=job["scheduled_end"],
            **(booking_overrides or {}),
        )
        if confirm_booking_flag:
            booking = confirm_booking(booking["id"], pilot["id"])
    job = get_job(job["id"])
    return {
        "tug": tug,
        "vessel": vessel,
        "pilot": pilot,
        "tariff": tariff,
        "job": job,
        "assignment": asg,
        "booking": booking,
    }


def setup_dispatched_job(**kwargs):
    """setup_confirmed_job + dispatch. Returns the same dict."""
    ctx = setup_confirmed_job(**kwargs)
    dispatch_job(ctx["job"]["id"])
    ctx["job"] = get_job(ctx["job"]["id"])
    return ctx


def setup_completed_job(
    start_clock_iso: str = "2026-06-01T08:00:00Z",
    complete_clock_iso: str = "2026-06-01T10:00:00Z",
    **kwargs,
):
    """setup_dispatched_job + start + complete. Defaults give zero standby.
    Returns the ctx dict extended with the auto-created invoice."""
    ctx = setup_dispatched_job(**kwargs)
    set_clock(start_clock_iso)
    start_job(ctx["job"]["id"])
    set_clock(complete_clock_iso)
    complete_job(ctx["job"]["id"])
    ctx["job"] = get_job(ctx["job"]["id"])
    ctx["invoice"] = get_invoice_for_job(ctx["job"]["id"])
    return ctx


# ─── Tier 4: Safety / incident / claim chains ─────────


def setup_incident(
    tug_overrides=None,
    incident_overrides=None,
    passed_inspection_first: bool = False,
):
    """Create a tug (optionally with a prior PASSED inspection) and report an
    incident on it. Returns dict with tug and incident."""
    tug = create_tug(**(tug_overrides or {}))
    if passed_inspection_first:
        record_passed_inspection(tug["id"])
    incident_defaults = {}
    if incident_overrides:
        incident_defaults.update(incident_overrides)
    res = api_client.create_incident(
        create_incident_payload(tug["id"], **incident_defaults),
        make_tug_captain_headers(tug["id"]),
    )
    incident = get_success_data(res)
    return {"tug": tug, "incident": incident}


def setup_filed_claim(
    claimed_amount_cents: int = 500000,
    tug_overrides=None,
    vessel_overrides=None,
    incident_overrides=None,
):
    """Tug + vessel + incident + one filed claim. Returns dict."""
    tug = create_tug(**(tug_overrides or {}))
    vessel = create_vessel(**(vessel_overrides or {}))
    res = api_client.create_incident(
        create_incident_payload(tug["id"], **(incident_overrides or {})),
        make_tug_captain_headers(tug["id"]),
    )
    incident = get_success_data(res)
    claim_res = api_client.create_damage_claim(
        create_damage_claim_payload(incident["id"], vessel["id"], claimed_amount_cents),
        make_vessel_agent_headers(vessel["id"]),
    )
    claim = get_success_data(claim_res)
    return {"tug": tug, "vessel": vessel, "incident": incident, "claim": claim}


def review_claim(claim_id: str, action: str, **overrides):
    payload = {"action": action}
    payload.update(overrides)
    res = api_client.review_damage_claim(
        claim_id, payload, TEST_USERS["claims_adjuster_headers"]
    )
    return get_success_data(res)


def settle_claim(claim_id: str):
    res = api_client.settle_damage_claim(
        claim_id, TEST_USERS["claims_adjuster_headers"]
    )
    return get_success_data(res)


def setup_accepted_claim(**kwargs):
    ctx = setup_filed_claim(**kwargs)
    review_claim(ctx["claim"]["id"], "START_REVIEW")
    claim = review_claim(ctx["claim"]["id"], "ACCEPT")
    ctx["claim"] = claim
    return ctx


# ─── Tier 5: Weather-restriction helpers ──────────────


def create_weather_restriction(**overrides):
    res = api_client.create_weather_restriction(
        create_weather_restriction_payload(**overrides),
        TEST_USERS["port_admin_headers"],
    )
    return get_success_data(res)


def lift_weather_restriction(restriction_id: str):
    res = api_client.lift_weather_restriction(
        restriction_id, TEST_USERS["port_admin_headers"]
    )
    return get_success_data(res)
