"""Composite setup helpers — multi-step preambles tests can reuse.

PRD §2.9 test capabilities: the test driver advances the simulated
wall clock via POST /_clock/advance (with a `seconds` parameter) and
runs deferred sweeps via POST /_sweep/run. These fixtures invoke
those endpoints with the CDCSupervisor shared constant (the only
role permitted on test-driver endpoints per PRD §4).

IDENTITY THREADING — PRD §2.1: HospitalReporter, LabTechnician,
CDCDispatcher, and CDCTracer are ENTITY-BACKED — X-User-ID is the
acting ReportingInstitution.id. Ownership checks on fields like
reporting_institution_id, ordering_institution_id,
requesting_institution_id, and assigned_cdc_id compare the FK to
X-User-ID directly. Every fixture in this file that mutates such a
resource MUST mint its headers with the actual institution.id of the
institution that owns (or will own) the resource — using
make_<role>_headers(institution["id"]). Returning a shared constant
would force the implementation to drop the PRD ownership check just
to pass the test.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    allocate_batch_payload,
    approve_risk_decision_payload,
    clock_advance_payload,
    create_bulletin_payload,
    create_case_payload,
    create_contact_event_payload,
    create_facility_payload,
    create_institution_payload,
    create_isolation_payload,
    create_person_payload,
    create_region_payload,
    create_risk_decision_payload,
    create_supply_item_payload,
    create_supply_request_payload,
    create_test_order_payload,
    create_tracing_task_payload,
    daily_report_payload,
    dispatch_payload,
    iso_utc,
    iso_utc_midnight,
    random_person_hash,
    random_suffix,
    test_result_payload,
    violation_payload,
)
from .test_users import (
    TEST_USERS,
    make_cdc_dispatcher_headers,
    make_cdc_tracer_headers,
    make_hospital_reporter_headers,
    make_lab_technician_headers,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _supervisor_headers() -> Dict[str, str]:
    return TEST_USERS["cdc_supervisor_headers"]


def _press_headers() -> Dict[str, str]:
    return TEST_USERS["press_officer_headers"]


def _expert_headers() -> Dict[str, str]:
    return TEST_USERS["risk_expert_headers"]


def _supply_mgr_headers() -> Dict[str, str]:
    return TEST_USERS["supply_manager_headers"]


def _ok(resp) -> Dict[str, Any]:
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock controls (PRD §2.9)
# ---------------------------------------------------------------------------
def advance_clock(seconds: int) -> Dict[str, Any]:
    """Advance the simulated wall clock by `seconds`.

    PRD §2.9: "An admin-only clock-advance capability accepts a
    seconds body parameter and advances the simulated wall clock for
    any time-gated transition."
    """
    return _ok(api_client.clock_advance(
        clock_advance_payload(seconds), _supervisor_headers(),
    ))


def run_sweep() -> Dict[str, Any]:
    return _ok(api_client.sweep_run(_supervisor_headers()))


# ---------------------------------------------------------------------------
# Tier 1 — primitive entity creators
# ---------------------------------------------------------------------------
def create_region(district_code: Optional[str] = None,
                  population: int = 100000,
                  **overrides: Any) -> Dict[str, Any]:
    """Create a Region. PRD §3.1: CDCSupervisor-only."""
    district = district_code or f"D-{random_suffix(5)}"
    payload = create_region_payload(
        district_code=district, population=population, **overrides,
    )
    return _ok(api_client.create_region(payload, _supervisor_headers()))


def create_institution(
    institution_type: str = "HOSPITAL",
    district_code: str = "D-001",
    institution_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a ReportingInstitution. PRD §3.1: CDCSupervisor-only."""
    payload = create_institution_payload(
        institution_code=institution_code,
        institution_type=institution_type,
        district_code=district_code,
        **overrides,
    )
    return _ok(api_client.create_institution(payload, _supervisor_headers()))


def create_facility(district_code: str = "D-001",
                    capacity: int = 5,
                    facility_code: Optional[str] = None,
                    **overrides: Any) -> Dict[str, Any]:
    """Create an IsolationFacility. PRD §3.1: CDCSupervisor-only."""
    payload = create_facility_payload(
        facility_code=facility_code,
        district_code=district_code,
        capacity=capacity,
        **overrides,
    )
    return _ok(api_client.create_facility(payload, _supervisor_headers()))


def create_person(district_code: str = "D-001",
                  person_hash: Optional[str] = None,
                  **overrides: Any) -> Dict[str, Any]:
    """Create a Person. PRD §3.1 allows CDCSupervisor or HospitalReporter
    — supervisor is the safest opaque choice."""
    payload = create_person_payload(
        person_hash=person_hash, district_code=district_code, **overrides,
    )
    return _ok(api_client.create_person(payload, _supervisor_headers()))


def create_supply_item(category: str = "PPE",
                       reserve_quantity: int = 100,
                       sku: Optional[str] = None,
                       **overrides: Any) -> Dict[str, Any]:
    """Create a SupplyItem. PRD §3.7: SupplyManager-only."""
    payload = create_supply_item_payload(
        sku=sku, category=category, reserve_quantity=reserve_quantity,
        **overrides,
    )
    return _ok(api_client.create_supply_item(payload, _supply_mgr_headers()))


# ---------------------------------------------------------------------------
# Tier 2 — convenience: institution + person + region wiring
# ---------------------------------------------------------------------------
def setup_district_with_hospital(
    district_code: Optional[str] = None,
    population: int = 100000,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Region + one HOSPITAL institution in that district.

    Returns (region, hospital_institution).
    """
    district = district_code or f"D-{random_suffix(5)}"
    region = create_region(district_code=district, population=population)
    hospital = create_institution(
        institution_type="HOSPITAL", district_code=district,
    )
    return region, hospital


def setup_district_with_cdc(
    district_code: Optional[str] = None,
    population: int = 100000,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Region + one CDC institution in that district.

    Returns (region, cdc_institution).
    """
    district = district_code or f"D-{random_suffix(5)}"
    region = create_region(district_code=district, population=population)
    cdc = create_institution(
        institution_type="CDC", district_code=district,
    )
    return region, cdc


def setup_district_with_hospital_and_cdc(
    district_code: Optional[str] = None,
    population: int = 100000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Region + HOSPITAL + CDC institutions in that district.

    Returns (region, hospital, cdc).
    """
    district = district_code or f"D-{random_suffix(5)}"
    region = create_region(district_code=district, population=population)
    hospital = create_institution(
        institution_type="HOSPITAL", district_code=district,
    )
    cdc = create_institution(
        institution_type="CDC", district_code=district,
    )
    return region, hospital, cdc


def setup_full_local_chain(
    district_code: Optional[str] = None,
    population: int = 100000,
) -> Dict[str, Any]:
    """Region + HOSPITAL + LAB + CDC institutions in same district.

    Returns dict with keys: region, hospital, lab, cdc.
    """
    district = district_code or f"D-{random_suffix(5)}"
    region = create_region(district_code=district, population=population)
    hospital = create_institution(
        institution_type="HOSPITAL", district_code=district,
    )
    lab = create_institution(
        institution_type="LAB", district_code=district,
    )
    cdc = create_institution(
        institution_type="CDC", district_code=district,
    )
    return {
        "region": region,
        "hospital": hospital,
        "lab": lab,
        "cdc": cdc,
        "district_code": district,
    }


# ---------------------------------------------------------------------------
# Tier 3 — Case / TracingTask / Isolation helpers
# ---------------------------------------------------------------------------
def file_case(
    person_id: str,
    hospital_id: str,
    case_type: str = "CONFIRMED",
    onset_date: Optional[str] = None,
    symptoms: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File a Case using HospitalReporter headers bound to hospital_id.

    PRD §2.1 + §3.2: reporting_institution_id is compared to X-User-ID;
    pass the SAME hospital_id as both the FK in the body and the
    binding identity in headers.
    """
    payload = create_case_payload(
        person_id=person_id,
        reporting_institution_id=hospital_id,
        case_type=case_type,
        onset_date=onset_date,
        symptoms=symptoms,
        **overrides,
    )
    return _ok(api_client.create_case(
        payload, make_hospital_reporter_headers(hospital_id),
    ))


def dispatch_tracing_task(
    case_id: str,
    cdc_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Dispatch a TracingTask using CDCDispatcher headers bound to
    cdc_id (the CDC institution that will own the task).

    PRD §2.1 + §3.3: assigned_cdc_id is compared to X-User-ID.
    """
    payload = create_tracing_task_payload(
        case_id=case_id, assigned_cdc_id=cdc_id, **overrides,
    )
    return _ok(api_client.create_tracing_task(
        payload, make_cdc_dispatcher_headers(cdc_id),
    ))


def file_case_under_tracing(
    person_id: str,
    hospital_id: str,
    cdc_id: str,
    case_type: str = "CONFIRMED",
    **overrides: Any,
) -> Dict[str, Any]:
    """File a Case AND dispatch tracing so the case advances to
    status=UNDER_TRACING — the state PRD §3.6 counts as
    "confirmed-or-tracing-active".

    Use this when a test needs the case to be COUNTED in the
    case_density_risk_score's confirmed bucket.
    """
    case = file_case(
        person_id=person_id, hospital_id=hospital_id,
        case_type=case_type, **overrides,
    )
    dispatch_tracing_task(case_id=case["id"], cdc_id=cdc_id)
    # Re-fetch to get the post-dispatch status.
    return _ok(api_client.get_case(
        case["id"], make_hospital_reporter_headers(hospital_id),
    ))


def accept_tracing_task(task_id: str, cdc_id: str) -> Dict[str, Any]:
    return _ok(api_client.accept_tracing_task(
        task_id, make_cdc_tracer_headers(cdc_id),
    ))


def complete_tracing_task(task_id: str, cdc_id: str) -> Dict[str, Any]:
    return _ok(api_client.complete_tracing_task(
        task_id, make_cdc_tracer_headers(cdc_id),
    ))


def create_isolation_for_person(
    person_id: str,
    cdc_id: str,
    mode: str = "HOME",
    start_date: Optional[str] = None,
    facility_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open an Isolation as CDCTracer bound to cdc_id."""
    payload = create_isolation_payload(
        person_id=person_id,
        mode=mode,
        start_date=start_date,
        facility_id=facility_id,
        **overrides,
    )
    return _ok(api_client.create_isolation(
        payload, make_cdc_tracer_headers(cdc_id),
    ))


def order_pcr_test(person_id: str, hospital_id: str) -> Dict[str, Any]:
    """Order a PCR test as HospitalReporter bound to hospital_id."""
    payload = create_test_order_payload(
        person_id=person_id,
        ordering_institution_id=hospital_id,
        test_type="PCR",
    )
    return _ok(api_client.create_test_order(
        payload, make_hospital_reporter_headers(hospital_id),
    ))


def collect_test(order_id: str, hospital_id: str) -> Dict[str, Any]:
    """Record sample collection as HospitalReporter (PRD §3.5 exclusive)."""
    return _ok(api_client.collect_test_order(
        order_id, make_hospital_reporter_headers(hospital_id),
    ))


def result_test(order_id: str, lab_id: str, result: str) -> Dict[str, Any]:
    """Ingest a lab result as LabTechnician bound to lab_id (PRD §3.5)."""
    return _ok(api_client.result_test_order(
        order_id, test_result_payload(result=result),
        make_lab_technician_headers(lab_id),
    ))


# ---------------------------------------------------------------------------
# Tier 4 — composite setups for the difficulty-design recipes
# ---------------------------------------------------------------------------
def setup_resulted_negative_pcr(
    person_id: str,
    hospital_id: str,
    lab_id: str,
    cdc_id: str,
    collect_after_seconds: int = 0,
    result_after_collect_seconds: int = 1,
    result: str = "NEGATIVE",
) -> Dict[str, Any]:
    """Order a PCR, collect, advance clock, ingest result.

    Caller is responsible for setting the clock baseline before calling
    this helper. The helper advances by `collect_after_seconds` before
    collect and by `result_after_collect_seconds` between collect and
    result. Returns the resulted TestOrder."""
    if collect_after_seconds:
        advance_clock(collect_after_seconds)
    order = order_pcr_test(person_id, hospital_id)
    collected = collect_test(order["id"], hospital_id)
    if result_after_collect_seconds:
        advance_clock(result_after_collect_seconds)
    return result_test(collected["id"], lab_id, result)


def setup_two_distinct_date_negative_pcr_tests(
    person_id: str,
    hospital_id: str,
    lab_id: str,
    cdc_id: str,
    iso_start: datetime,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Produce two NEGATIVE PCR TestOrder rows for `person_id` on two
    distinct UTC collection dates. Caller has the clock parked at
    `iso_start`. Returns (test1, test2).

    Used by:
      - PRD §3.10 recovery precondition ("at least two prior TestOrder
        rows ... with chronologically distinct collection dates").
      - PRD §3.4 isolation release ("distinct UTC collection dates").
    """
    # First test: collected ~1 day in, resulted shortly after.
    # Use 86400s = 1 day to land on the next UTC calendar date.
    t1 = setup_resulted_negative_pcr(
        person_id, hospital_id, lab_id, cdc_id,
        collect_after_seconds=86400,
        result_after_collect_seconds=60,
        result="NEGATIVE",
    )
    # Second test: another full day forward, so collection dates differ.
    t2 = setup_resulted_negative_pcr(
        person_id, hospital_id, lab_id, cdc_id,
        collect_after_seconds=86400,
        result_after_collect_seconds=60,
        result="NEGATIVE",
    )
    return t1, t2


def setup_centralized_isolation(
    cdc_id: str,
    facility_capacity: int = 2,
    district_code: Optional[str] = None,
    start_date_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Person + centralized facility + active centralized Isolation.

    Returns dict with keys: person, facility, isolation, cdc_id.
    """
    district = district_code or f"D-{random_suffix(5)}"
    facility = create_facility(
        district_code=district, capacity=facility_capacity,
    )
    person = create_person(district_code=district)
    isolation = create_isolation_for_person(
        person_id=person["id"],
        cdc_id=cdc_id,
        mode="CENTRALIZED",
        facility_id=facility["id"],
        start_date=start_date_override,
    )
    return {
        "person": person,
        "facility": facility,
        "isolation": isolation,
        "cdc_id": cdc_id,
    }


def setup_provisional_risk_decision(
    region_id: str,
) -> Dict[str, Any]:
    """Create a PROVISIONAL RiskTierDecision via POST /epi/risk-decisions
    (PRD §3.6 — snapshots current provisional_risk_tier)."""
    return _ok(api_client.create_risk_decision(
        create_risk_decision_payload(region_id=region_id),
        _supervisor_headers(),
    ))


def drive_region_to_published_tier(
    region: Dict[str, Any],
    final_tier: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Walk the RiskTierDecision lifecycle to PUBLISHED with the given
    `final_tier`. Useful to force Region.current_risk_tier for downstream
    tests (supply priority cascade, no-op-publish blocking).

    PRD §3.6 requires provisional_tier != current_risk_tier at
    submit-review time. To guarantee that on a fresh region, this helper
    pre-files four ASYMPTOMATIC cases in the region (4 * W_ASYMPTOMATIC /
    population * 100k = 4.00 → still LOW alone, so we additionally file
    enough cases routed through tracing dispatch so they reach
    UNDER_TRACING status — pushing provisional to MEDIUM at minimum).

    Returns (decision, region_after_publish).
    """
    # Pre-seed cases in the region so provisional differs from current.
    # We need provisional to land somewhere != current (which is LOW on
    # a fresh region). Easiest: file 4 cases routed through tracing
    # dispatch so they reach UNDER_TRACING (counts in confirmed bucket).
    # density = 4 * W_CONFIRMED / population * 100k.
    pop = int(region.get("population") or 100000)
    target_count = max(4, (10 * pop // 100000 // 3) + 1)  # density >= 10
    # We need a HOSPITAL and a CDC in this region to file + dispatch.
    district = region["district_code"]
    seed_hospital = create_institution(
        institution_type="HOSPITAL", district_code=district,
    )
    seed_cdc = create_institution(
        institution_type="CDC", district_code=district,
    )
    for _ in range(target_count):
        p = create_person(district_code=district)
        file_case_under_tracing(
            person_id=p["id"], hospital_id=seed_hospital["id"],
            cdc_id=seed_cdc["id"], case_type="CONFIRMED",
        )
    # Step 1: recompute provisional with seeded cases in place.
    api_client.recompute_region_risk(region["id"], _supervisor_headers())
    # Step 2: create PROVISIONAL decision row.
    decision = setup_provisional_risk_decision(region["id"])
    # Step 3: submit-review (provisional now differs from current LOW).
    _ok(api_client.submit_risk_decision_review(
        decision["id"], _supervisor_headers(),
    ))
    _ok(api_client.approve_risk_decision(
        decision["id"],
        approve_risk_decision_payload(
            final_tier=final_tier,
            expert_reviewer_id=TEST_USERS["risk_expert_headers"]["X-User-ID"],
        ),
        _expert_headers(),
    ))
    published = _ok(api_client.publish_risk_decision(
        decision["id"], _press_headers(),
    ))
    region_after = _ok(api_client.get_region(
        region["id"], _supervisor_headers(),
    ))
    return published, region_after


# ---------------------------------------------------------------------------
# Tier 4b — Supply pipeline setups
# ---------------------------------------------------------------------------
def submit_supply_request(
    sku: str,
    hospital_id: str,
    requested_quantity: int,
) -> Dict[str, Any]:
    """Submit a SupplyRequest as HospitalReporter bound to hospital_id."""
    payload = create_supply_request_payload(
        sku=sku,
        requesting_institution_id=hospital_id,
        requested_quantity=requested_quantity,
    )
    return _ok(api_client.create_supply_request(
        payload, make_hospital_reporter_headers(hospital_id),
    ))


def setup_supply_for_allocate_batch(
    sku: str = "PPE_MASK",
    category: str = "PPE",
    reserve: int = 100,
    high_request_qty: int = 80,
    low_request_qty: int = 50,
) -> Dict[str, Any]:
    """Build the canonical waterfall scenario:

    - One SupplyItem with `reserve` units of `sku`.
    - Region D1 published at HIGH risk tier with HOSPITAL inst_A.
    - Region D2 at default LOW with HOSPITAL inst_B.
    - SupplyRequest A from inst_A for high_request_qty.
    - SupplyRequest B from inst_B for low_request_qty.

    Returns dict with all created entities.
    """
    item = create_supply_item(
        sku=sku, category=category, reserve_quantity=reserve,
    )
    # District D1 — high-tier.
    region_high, hospital_high = setup_district_with_hospital(population=100000)
    drive_region_to_published_tier(region_high, "HIGH")
    request_high = submit_supply_request(
        sku=item["sku"],
        hospital_id=hospital_high["id"],
        requested_quantity=high_request_qty,
    )
    # District D2 — leave at default LOW (initial Region.current_risk_tier).
    _region_low, hospital_low = setup_district_with_hospital(population=100000)
    request_low = submit_supply_request(
        sku=item["sku"],
        hospital_id=hospital_low["id"],
        requested_quantity=low_request_qty,
    )
    return {
        "item": item,
        "region_high": region_high,
        "hospital_high": hospital_high,
        "region_low": _region_low,
        "hospital_low": hospital_low,
        "request_high": request_high,
        "request_low": request_low,
    }


# ---------------------------------------------------------------------------
# Tier 5 — full-cycle setups for difficulty design instances
# ---------------------------------------------------------------------------
def setup_isolation_releasable_via_home_mode(
    days_isolated: int = 10,
    test1_day: int = 5,
    test2_day: int = 9,
) -> Dict[str, Any]:
    """Build a HOME-mode Isolation eligible for RELEASE.

    Recipe (difficulty: combinatorial_formula/isolation_release_circular_dependency):
      - Create Person P and Isolation I (mode=HOME, start_date=T0).
      - Advance clock to T0 + test1_day days; collect TestOrder1; ingest
        NEGATIVE PCR result.
      - Advance clock to T0 + test2_day days; collect TestOrder2; ingest
        NEGATIVE PCR result.
      - Advance clock to T0 + days_isolated days.

    Returns dict with keys: region, hospital, lab, cdc, person, isolation,
    test1, test2.
    """
    chain = setup_full_local_chain()
    person = create_person(district_code=chain["district_code"])

    # Use today's UTC midnight as start_date — by then the server's
    # logical clock will be close to "now" (its starting wall time);
    # the seconds-based advance_clock calls below move the clock
    # forward relative to that baseline. PRD §2.9 day-granular
    # comparisons compute elapsed_days = floor((now - start_date)/86400).
    start_iso = iso_utc_midnight(datetime.now(timezone.utc))
    isolation = create_isolation_for_person(
        person_id=person["id"],
        cdc_id=chain["cdc"]["id"],
        mode="HOME",
        start_date=start_iso,
    )

    # day-relative advances. The test driver clock starts at server's
    # "now"; advance by test1_day*86400 - some baseline (we step in
    # increments). For determinism, we just push successive deltas.
    elapsed = 0

    def _advance_to(day: int) -> None:
        nonlocal elapsed
        delta = day * 86400 - elapsed
        if delta > 0:
            advance_clock(delta)
            elapsed += delta

    _advance_to(test1_day)
    o1 = order_pcr_test(person["id"], chain["hospital"]["id"])
    c1 = collect_test(o1["id"], chain["hospital"]["id"])
    advance_clock(60)  # tiny gap before result
    elapsed += 60
    t1 = result_test(c1["id"], chain["lab"]["id"], "NEGATIVE")

    _advance_to(test2_day)
    o2 = order_pcr_test(person["id"], chain["hospital"]["id"])
    c2 = collect_test(o2["id"], chain["hospital"]["id"])
    advance_clock(60)
    elapsed += 60
    t2 = result_test(c2["id"], chain["lab"]["id"], "NEGATIVE")

    _advance_to(days_isolated)

    return {
        **chain,
        "person": person,
        "isolation": isolation,
        "test1": t1,
        "test2": t2,
    }


def setup_confirmed_case_with_isolation(
    chain: Optional[Dict[str, Any]] = None,
    onset_offset_days: int = 0,
) -> Dict[str, Any]:
    """Person + filed Case + dispatched/accepted/completed TracingTask
    chain so Case ends at CONFIRMED. Plus an Isolation in ACTIVE.

    Returns dict with: chain, person, case, task, isolation.
    """
    chain = chain or setup_full_local_chain()
    person = create_person(district_code=chain["district_code"])

    # File a CONFIRMED case directly (PRD §3.2 allows the case_type to
    # be CONFIRMED at filing).
    case = file_case(
        person_id=person["id"],
        hospital_id=chain["hospital"]["id"],
        case_type="CONFIRMED",
    )

    # Open an Isolation for the person at onset_date (HOME mode).
    isolation = create_isolation_for_person(
        person_id=person["id"],
        cdc_id=chain["cdc"]["id"],
        mode="HOME",
        start_date=case["onset_date"],
    )
    return {
        "chain": chain,
        "person": person,
        "case": case,
        "isolation": isolation,
    }


def release_isolation(isolation_id: str, cdc_id: str) -> Dict[str, Any]:
    return _ok(api_client.check_isolation_release(
        isolation_id, make_cdc_tracer_headers(cdc_id),
    ))


def violate_isolation(
    isolation_id: str,
    cdc_id: str,
    reason: str = "Geofence breach",
) -> Dict[str, Any]:
    return _ok(api_client.record_isolation_violation(
        isolation_id, violation_payload(reason=reason),
        make_cdc_tracer_headers(cdc_id),
    ))


__all__ = [
    "advance_clock",
    "run_sweep",
    "create_region",
    "create_institution",
    "create_facility",
    "create_person",
    "create_supply_item",
    "setup_district_with_hospital",
    "setup_district_with_cdc",
    "setup_district_with_hospital_and_cdc",
    "setup_full_local_chain",
    "file_case",
    "file_case_under_tracing",
    "dispatch_tracing_task",
    "accept_tracing_task",
    "complete_tracing_task",
    "create_isolation_for_person",
    "order_pcr_test",
    "collect_test",
    "result_test",
    "setup_resulted_negative_pcr",
    "setup_two_distinct_date_negative_pcr_tests",
    "setup_centralized_isolation",
    "setup_provisional_risk_decision",
    "drive_region_to_published_tier",
    "submit_supply_request",
    "setup_supply_for_allocate_batch",
    "setup_isolation_releasable_via_home_mode",
    "setup_confirmed_case_with_isolation",
    "release_isolation",
    "violate_isolation",
]
