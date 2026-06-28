"""Composite setup helpers for multi-step test prerequisites.

The dental-lab pipeline drives a case from INTAKE all the way to DELIVERED
through ~15 API calls (submit -> schedule mill job -> start/complete -> ready
-> route stop -> accept verdict -> complete stop -> confirm delivery). These
helpers encapsulate the chain so test bodies focus on their single assertion.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "setup failed" errors rather than confusing assertion failures.

Identity threading: a Doctor is entity_backed, so ownership-gated Doctor calls
(cancel, tryin-verdict, remake-requests) use make_doctor_headers(doctor_id),
never the shared TEST_USERS["doctor_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_doctor_payload, create_material_payload, create_mill_machine_payload,
    create_courier_route_payload, create_case_payload, create_restoration_payload,
    create_mill_job_payload, create_route_stop_payload, tryin_verdict_payload,
    create_remake_request_payload,
)
from .test_users import TEST_USERS, make_doctor_headers
from .constants import CLOCK_DEFAULT

ADMIN = TEST_USERS["labadmin_headers"]
TECH = TEST_USERS["labtech_headers"]
SCHED = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_headers"]


# ─── Primitive create helpers ─────────────────────────────────────────
def set_clock(iso=CLOCK_DEFAULT):
    """Pin the server logical clock to a known instant (PRD §3.10)."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


def create_doctor(**overrides):
    return get_success_data(api_client.create_doctor(create_doctor_payload(**overrides), ADMIN))


def create_material(**overrides):
    return get_success_data(api_client.create_material(create_material_payload(**overrides), ADMIN))


def create_machine(**overrides):
    return get_success_data(api_client.create_mill_machine(
        create_mill_machine_payload(**overrides), ADMIN))


def create_route(**overrides):
    return get_success_data(api_client.create_courier_route(
        create_courier_route_payload(**overrides), SCHED))


def create_case(doctor_id, **overrides):
    return get_success_data(api_client.create_case(
        create_case_payload(doctor_id, **overrides), TECH))


def create_restoration(case_id, material_id, **overrides):
    return get_success_data(api_client.create_restoration(
        case_id, create_restoration_payload(material_id, **overrides), TECH))


def list_units(restoration_id):
    return get_success_data(api_client.list_restoration_units(restoration_id, TECH))


def get_case(case_id):
    return get_success_data(api_client.get_case(case_id, ADMIN))


def get_invoice_for_case(case_id):
    """Return the single invoice attached to a case (PRD: one PROVISIONAL per case)."""
    data = get_success_data(api_client.get_case_invoice(case_id, BILLING))
    return data[0] if isinstance(data, list) else data


# ─── Tier 1: standing configuration ──────────────────────────────────
def setup_base_config(material_overrides=None, machine_overrides=None,
                      with_route=False, route_overrides=None, with_clock=True):
    """Doctor + material + machine (+ optional route), clock pinned.

    Returns a dict of the created entities for the caller to thread through.
    """
    if with_clock:
        set_clock()
    doctor = create_doctor()
    material = create_material(**(material_overrides or {}))
    machine = create_machine(**(machine_overrides or {}))
    out = {"doctor": doctor, "material": material, "machine": machine}
    if with_route:
        out["route"] = create_route(**(route_overrides or {}))
    return out


# ─── Tier 2: case in DESIGN (submitted, units materialized & priced) ──
def setup_submitted_case(restoration_specs=None, case_overrides=None,
                         material_overrides=None, doctor=None, with_clock=True):
    """Build a case, attach restorations, and submit it to DESIGN.

    restoration_specs: list of dicts forwarded to create_restoration overrides
        (each names restoration_type / unit_count / etc). Defaults to one crown.
    Returns dict: doctor, material, case (post-submit), restorations, units.
    """
    if with_clock:
        set_clock()
    if doctor is None:
        doctor = create_doctor()
    material = create_material(**(material_overrides or {}))
    case = create_case(doctor["id"], **(case_overrides or {}))

    specs = restoration_specs if restoration_specs is not None else [
        {"restoration_type": "CROWN", "unit_count": 1}
    ]
    restorations = []
    for spec in specs:
        mat_id = spec.pop("material_id", material["id"])
        restorations.append(create_restoration(case["id"], mat_id, **spec))

    submitted = get_success_data(api_client.submit_case(case["id"], TECH))

    units = []
    for rest in restorations:
        units.extend(list_units(rest["id"]))

    return {
        "doctor": doctor,
        "material": material,
        "case": submitted,
        "restorations": restorations,
        "units": units,
    }


# ─── Tier 3: schedule + mill a single-unit case up to a target state ──
def _schedule_and_mill_units(case_id, units, machine, mill_each=True,
                             job_overrides_by_index=None, base_day="2026-01-01",
                             start_fab_times=1):
    """Schedule a mill job for each unit, start fabrication, then optionally
    run+complete each job so the units reach MILLED.

    `base_day` selects the ISO calendar day for the staggered start_at windows.
    When the SAME machine is reused across revision cycles, completed (DONE) jobs
    remain non-CANCELLED and therefore still occupy their half-open intervals
    (PRD §3.4: a new job must not intersect any non-cancelled job on the machine).
    Re-milling on the same machine must therefore land on a distinct day so it
    cannot collide with the prior cycle's DONE jobs; callers pass an advancing
    base_day per cycle.

    `start_fab_times` controls how many start-fabrication advancements to issue
    before milling. A case entering from DESIGN needs one (DESIGN -> FABRICATION),
    but a case entering from REVISION needs two, because the first advancement
    lands it back in DESIGN and only the second reaches FABRICATION (PRD §3.5:
    "the same advancement, applied to a case sitting in REVISION, lands it back
    in DESIGN so the design-then-fabrication walk repeats"). Both advancements run
    while the jobs are still SCHEDULED, so each requeued unit holds a fresh
    SCHEDULED job for both legs.

    Returns list of created mill-job dicts (in unit order).
    """
    jobs = []
    # Stagger job start_at by 2h per unit on the shared machine to avoid overlap.
    hours = [1, 3, 5, 7, 9, 11, 13, 15]
    for i, unit in enumerate(units):
        ov = {"start_at": f"{base_day}T{hours[i]:02d}:00:00Z", "duration_minutes": 60}
        if job_overrides_by_index and i in job_overrides_by_index:
            ov.update(job_overrides_by_index[i])
        job = get_success_data(api_client.create_mill_job(
            create_mill_job_payload(unit["id"], machine["id"], **ov), SCHED))
        jobs.append(job)

    # Advance toward FABRICATION (each leg requires every queued unit to have a
    # SCHEDULED job, which holds because the jobs are not yet started).
    for _ in range(start_fab_times):
        get_success_data(api_client.start_fabrication(case_id, TECH))

    if mill_each:
        for job in jobs:
            machine_now = get_success_data(api_client.get_mill_machine(machine["id"], SCHED))
            get_success_data(api_client.start_mill_job(
                job["id"], {"expected_machine_version": machine_now["version"]}, SCHED))
            get_success_data(api_client.complete_mill_job(job["id"], SCHED))
    return jobs


def setup_case_at_tryin(restoration_specs=None, case_overrides=None,
                        material_overrides=None, machine_overrides=None,
                        doctor=None, with_clock=True):
    """Drive a case all the way to TRY_IN with every billable unit MILLED.

    Returns dict: doctor, material, machine, case (at TRY_IN, latest version),
    restorations, units (post-mill), jobs.
    """
    built = setup_submitted_case(
        restoration_specs=restoration_specs, case_overrides=case_overrides,
        material_overrides=material_overrides, doctor=doctor, with_clock=with_clock)
    machine = create_machine(**(machine_overrides or {}))

    jobs = _schedule_and_mill_units(built["case"]["id"], built["units"], machine)

    # FABRICATION -> TRY_IN (every billable unit MILLED).
    case = get_success_data(api_client.ready_tryin(built["case"]["id"], TECH))

    return {
        "doctor": built["doctor"],
        "material": built["material"],
        "machine": machine,
        "case": case,
        "restorations": built["restorations"],
        "units": built["units"],
        "jobs": jobs,
    }


def setup_case_at_tryin_with_route(restoration_specs=None, case_overrides=None,
                                   material_overrides=None, route_overrides=None,
                                   stop_overrides=None, with_clock=True):
    """Case at TRY_IN plus a PLANNED RouteStop attached (ACCEPT precondition met).

    Returns the setup_case_at_tryin dict plus route and route_stop keys.
    """
    built = setup_case_at_tryin(
        restoration_specs=restoration_specs, case_overrides=case_overrides,
        material_overrides=material_overrides, with_clock=with_clock)
    route = create_route(**(route_overrides or {}))
    stop = get_success_data(api_client.create_route_stop(
        create_route_stop_payload(route["id"], built["case"]["id"],
                                  **(stop_overrides or {})), SCHED))
    built["route"] = route
    built["route_stop"] = stop
    return built


def accept_case(case_dict_or_id, doctor_id, expected_version=None):
    """Record an ACCEPT verdict (ships the case). Returns the updated case.

    Reads the live case version when expected_version is not supplied so the
    OCC check passes.
    """
    case_id = case_dict_or_id["id"] if isinstance(case_dict_or_id, dict) else case_dict_or_id
    if expected_version is None:
        expected_version = get_case(case_id)["version"]
    return get_success_data(api_client.tryin_verdict(
        case_id, tryin_verdict_payload("ACCEPT", expected_version),
        make_doctor_headers(doctor_id)))


def setup_shipped_case(restoration_specs=None, case_overrides=None,
                       material_overrides=None, clock_at_ship=None,
                       route_overrides=None, stop_overrides=None):
    """Case driven through ACCEPT to SHIPPED. Optionally advance the clock to
    `clock_at_ship` just before the verdict so SLA breach can be controlled.

    Returns dict: doctor, machine, case (SHIPPED), restorations, units, route,
    route_stop, invoice.
    """
    built = setup_case_at_tryin_with_route(
        restoration_specs=restoration_specs, case_overrides=case_overrides,
        material_overrides=material_overrides, route_overrides=route_overrides,
        stop_overrides=stop_overrides)
    if clock_at_ship is not None:
        set_clock(clock_at_ship)
    case = accept_case(built["case"], built["doctor"]["id"])
    built["case"] = case
    built["invoice"] = get_invoice_for_case(case["id"])
    return built


def setup_delivered_case(restoration_specs=None, case_overrides=None,
                         material_overrides=None, clock_at_ship=None,
                         route_overrides=None, stop_overrides=None):
    """Case driven all the way to DELIVERED (route stop completed, delivery
    confirmed). Returns the setup_shipped_case dict with case at DELIVERED and
    the unit(s) PASSED.
    """
    built = setup_shipped_case(
        restoration_specs=restoration_specs, case_overrides=case_overrides,
        material_overrides=material_overrides, clock_at_ship=clock_at_ship,
        route_overrides=route_overrides, stop_overrides=stop_overrides)
    get_success_data(api_client.complete_route_stop(built["route_stop"]["id"], SCHED))
    case = get_success_data(api_client.confirm_delivery(built["case"]["id"], SCHED))
    built["case"] = case
    # Refresh units to PASSED.
    units = []
    for rest in built["restorations"]:
        units.extend(list_units(rest["id"]))
    built["units"] = units
    return built


# ─── Tier 4: doctor volume-tier targeting via warm DELIVERED cases ────
def deliver_n_cases_for_doctor(doctor_id, n, material):
    """Drive `n` independent crown cases for `doctor_id` to DELIVERED so the
    doctor's completed_case_count reaches n. Reuses one machine + one route.

    Each warm case ships within SLA (clock left at the 2026-01-01 default), so
    no credit memo is issued, keeping the doctor's account_credit ledger at 0.
    """
    for _ in range(n):
        case = create_case(doctor_id)
        rest = create_restoration(case["id"], material["id"],
                                  restoration_type="CROWN", unit_count=1)
        get_success_data(api_client.submit_case(case["id"], TECH))
        units = list_units(rest["id"])
        machine = create_machine()
        _schedule_and_mill_units(case["id"], units, machine)
        get_success_data(api_client.ready_tryin(case["id"], TECH))
        route = create_route()
        stop = get_success_data(api_client.create_route_stop(
            create_route_stop_payload(route["id"], case["id"]), SCHED))
        accept_case(case, doctor_id)
        get_success_data(api_client.complete_route_stop(stop["id"], SCHED))
        get_success_data(api_client.confirm_delivery(case["id"], SCHED))


# ─── Tier 5: revision-cycle targeting ────────────────────────────────
def advance_revision_once(case_id, doctor_id, restoration_id, machine, cycle=0):
    """From a case at TRY_IN, record a REVISE verdict and walk the requeued unit
    back through DESIGN -> FABRICATION -> TRY_IN once. Returns the case at TRY_IN.

    Used to push revision_count toward MAX_REVISIONS. `cycle` selects a distinct
    re-mill calendar day so this cycle's new jobs cannot intersect the prior
    cycle's still-non-CANCELLED DONE jobs on the same machine (PRD §3.4).
    """
    case = get_case(case_id)
    get_success_data(api_client.tryin_verdict(
        case_id,
        tryin_verdict_payload("REVISE", case["version"],
                              revise_restoration_ids=[restoration_id]),
        make_doctor_headers(doctor_id)))
    # REVISION: re-mill the requeued unit(s) on a fresh day to avoid colliding
    # with prior DONE jobs occupying the same machine intervals. From REVISION the
    # walk is REVISION -> DESIGN -> FABRICATION, so two start-fabrication legs are
    # needed before milling (PRD §3.5).
    units = list_units(restoration_id)
    base_day = f"2026-02-{(cycle % 27) + 1:02d}"
    _schedule_and_mill_units(case_id, units, machine, base_day=base_day,
                             start_fab_times=2)
    return get_success_data(api_client.ready_tryin(case_id, TECH))


def setup_case_at_tryin_with_revisions(num_revisions, material_overrides=None):
    """Case at TRY_IN whose revision_count == num_revisions, with one crown unit
    MILLED and a PLANNED route stop is NOT attached (caller adds if needed).

    Returns dict: doctor, machine, case (TRY_IN), restoration, units.
    """
    built = setup_case_at_tryin(material_overrides=material_overrides)
    rest = built["restorations"][0]
    machine = built["machine"]
    for cycle in range(num_revisions):
        advance_revision_once(built["case"]["id"], built["doctor"]["id"],
                              rest["id"], machine, cycle=cycle)
    built["case"] = get_case(built["case"]["id"])
    built["restoration"] = rest
    return built
