"""Composite setup helpers for multi-step test prerequisites.

Identity threading rule (PRD §2.1):
- Tester / Reviewer / Signatory are entity_backed roles. Every
  ownership-gated call MUST use make_<role>_headers(entity['id']);
  never the shared TEST_USERS["*_headers"] fallback constants.
- LabClerk / LabManager are opaque, so the shared TEST_USERS constants
  are canonical.

All helpers use get_success_data() (lenient validator) internally so
setup failures surface as plain "Setup failed" errors rather than
confusing assertion stacks.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_MAX_CONCURRENT_TASKS,
    METHOD_TO_CATEGORY,
)
from .factories import (
    clock_advance_payload,
    create_booking_payload,
    create_client_payload,
    create_instrument_payload,
    create_invoice_payload,
    create_record_payload,
    create_reviewer_payload,
    create_sample_payload,
    create_signatory_payload,
    create_test_task_payload,
    create_tester_payload,
    emit_event_payload,
    method_for_category,
    qualification,
    update_client_payload,
    update_tester_payload,
)
from .test_users import (
    TEST_USERS,
    make_reviewer_headers,
    make_signatory_headers,
    make_tester_headers,
)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


# Canonical anchor instant used by tests for clock-relative offsets. Set
# far enough in the future that booking slots at anchor_plus(...) remain
# "future" relative to the server's wall-clock startup time. The PRD's
# /_clock/advance can only move forward, so picking an anchor in the
# far future means tests can always advance forward toward it.
CLOCK_ANCHOR = datetime(2099, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# Qualification dates used by default fixtures. Chosen to remain valid
# both at real wall-clock startup AND at the future CLOCK_ANCHOR so the
# same Tester remains QUALIFIED across the test suite.
DEFAULT_QUAL_VALID_FROM = "2024-01-01"
DEFAULT_QUAL_VALID_TO = "2200-12-31"


def anchor_plus(*, days: int = 0, hours: int = 0,
                minutes: int = 0, seconds: int = 0) -> str:
    """Return an ISO 8601 timestamp at CLOCK_ANCHOR + offset."""
    return iso(CLOCK_ANCHOR + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


# ---------------------------------------------------------------------------
# Tier 0: minimal "bootstrap" actors used by most tests
# ---------------------------------------------------------------------------
def create_client(*, contract_id: Optional[str] = None,
                  **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'a LabManager registers a Client by providing a name and
    a contact_email.'"""
    payload = create_client_payload(**overrides)
    if contract_id is not None:
        payload["contract_id"] = contract_id
    res = api_client.create_client(payload, TEST_USERS["lab_manager_headers"])
    return get_success_data(res)


def create_tester(
    *,
    qualifications: Optional[List[Dict[str, Any]]] = None,
    max_concurrent_tasks: int = DEFAULT_MAX_CONCURRENT_TASKS,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a Tester with the supplied qualifications (default:
    CONCRETE valid 2024..2030)."""
    payload = create_tester_payload(
        qualifications=qualifications,
        max_concurrent_tasks=max_concurrent_tasks,
        **overrides,
    )
    res = api_client.create_tester(payload, TEST_USERS["lab_manager_headers"])
    return get_success_data(res)


def create_reviewer(*, scope_categories: Optional[List[str]] = None,
                    **overrides: Any) -> Dict[str, Any]:
    payload = create_reviewer_payload(
        scope_categories=scope_categories, **overrides,
    )
    res = api_client.create_reviewer(payload, TEST_USERS["lab_manager_headers"])
    return get_success_data(res)


def create_signatory(*, scope_categories: Optional[List[str]] = None,
                     **overrides: Any) -> Dict[str, Any]:
    payload = create_signatory_payload(
        scope_categories=scope_categories, **overrides,
    )
    res = api_client.create_signatory(payload, TEST_USERS["lab_manager_headers"])
    return get_success_data(res)


def create_instrument(
    *,
    capabilities: Optional[List[str]] = None,
    calibration_valid_from: Optional[str] = None,
    calibration_valid_to: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_instrument_payload(
        capabilities=capabilities,
        calibration_valid_from=(
            calibration_valid_from or anchor_plus(days=-30)
        ),
        calibration_valid_to=(
            calibration_valid_to or anchor_plus(days=730)
        ),
        **overrides,
    )
    res = api_client.create_instrument(
        payload, TEST_USERS["lab_manager_headers"],
    )
    return get_success_data(res)


def create_sample(
    *,
    client_id: str,
    material_category: str = "CONCRETE",
    specification: Optional[str] = None,
    witness_sampled: bool = False,
    witness_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_sample_payload(
        client_id=client_id,
        material_category=material_category,
        specification=specification,
        witness_sampled=witness_sampled,
        witness_name=witness_name,
        **overrides,
    )
    res = api_client.create_sample(payload, TEST_USERS["lab_clerk_headers"])
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1: state-progression walks
# ---------------------------------------------------------------------------
def create_task(
    *,
    sample_id: str,
    test_method: str = "COMPRESSION_STRENGTH",
    urgent: bool = False,
) -> Dict[str, Any]:
    """PRD §3.3: 'A LabClerk creates a TestTask under a registered sample
    by supplying the test_method enumeration value and the optional
    urgent boolean.'"""
    payload = create_test_task_payload(test_method=test_method, urgent=urgent)
    res = api_client.create_test_task(
        sample_id, payload, TEST_USERS["lab_clerk_headers"],
    )
    return get_success_data(res)


def book_instrument_for_task(
    *,
    instrument_id: str,
    task_id: str,
    slot_start: str,
    slot_end: str,
) -> Dict[str, Any]:
    payload = create_booking_payload(
        task_id=task_id, slot_start=slot_start, slot_end=slot_end,
    )
    res = api_client.create_instrument_booking(
        instrument_id, payload, TEST_USERS["lab_clerk_headers"],
    )
    return get_success_data(res)


def start_task(*, task_id: str, tester_id: str) -> Dict[str, Any]:
    """PRD §3.6: 'the assigned Tester advances it to IN_PROGRESS by
    starting work.'"""
    res = api_client.start_task(task_id, make_tester_headers(tester_id))
    return get_success_data(res)


def in_band_raw_data_for_method(test_method: str) -> Dict[str, Any]:
    """Build an in-band default raw_data blob for a given test_method so
    record submission produces a non-abnormal calculated_result.

    PRD §3.6 declares per-method calculation shapes and per-method
    expected-band bounds. Default values chosen to fall inside band.
    """
    if test_method == "COMPRESSION_STRENGTH":
        # Default spec is "C30 cube 150mm" (22500 mm^2). 600 kN → 26.7 MPa.
        return {"peak_load_kn": 600.0}
    if test_method == "TENSILE_STRENGTH":
        # Default spec rebar D16: area ≈ 201 mm². 100 kN → ≈497 MPa (in band).
        return {"peak_load_kn": 100.0}
    if test_method == "COMPACTION_DENSITY":
        # Band 1.9..2.6 g/cm³
        return {"density_g_cm3": 2.1}
    if test_method == "MARSHALL_STABILITY":
        # Band 7.5..18.0 kN
        return {"stability_kn": 12.0}
    if test_method == "SETTING_TIME":
        # Band 45..600 minutes
        return {"setting_time_minutes": 120.0}
    return {"peak_load_kn": 600.0}


def submit_record(
    *,
    task_id: str,
    tester_id: str,
    peak_load_kn: float = 600.0,
    supersedes_record_id: Optional[str] = None,
    raw_data: Optional[Dict[str, Any]] = None,
    test_method: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.6: 'During testing the tester submits one or more
    TestRecord rows.'

    If raw_data is not supplied and test_method is given, an in-band
    default raw_data blob shaped for that method is sent. Otherwise the
    raw_data defaults to {peak_load_kn: peak_load_kn} (COMPRESSION_STRENGTH
    shape) per the original factory contract.
    """
    if raw_data is None and test_method is not None:
        raw_data = in_band_raw_data_for_method(test_method)
    payload = create_record_payload(
        peak_load_kn=peak_load_kn,
        supersedes_record_id=supersedes_record_id,
        raw_data=raw_data,
    )
    res = api_client.create_record(
        task_id, payload, make_tester_headers(tester_id),
    )
    return get_success_data(res)


def complete_task(*, task_id: str, tester_id: str) -> Dict[str, Any]:
    res = api_client.complete_task(task_id, make_tester_headers(tester_id))
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2: composite entity-hierarchy fixtures
# ---------------------------------------------------------------------------
def setup_concrete_test_environment(
    *,
    tester_qualifications: Optional[List[Dict[str, Any]]] = None,
    tester_max_tasks: int = DEFAULT_MAX_CONCURRENT_TASKS,
    instrument_capabilities: Optional[List[str]] = None,
    contract_id: Optional[str] = None,
) -> Dict[str, Any]:
    """One-shot environment with a CONCRETE-ready client, tester,
    reviewer, signatory, and an instrument calibrated broadly enough to
    cover any test booking. Returns a dict with all created entities.

    No Sample is created here — callers do that themselves so they
    control material_category, witness_sampled, etc.
    """
    if tester_qualifications is None:
        tester_qualifications = [
            qualification("CONCRETE", DEFAULT_QUAL_VALID_FROM, DEFAULT_QUAL_VALID_TO),
        ]
    if instrument_capabilities is None:
        instrument_capabilities = ["COMPRESSION_STRENGTH"]

    client = create_client(contract_id=contract_id)
    tester = create_tester(
        qualifications=tester_qualifications,
        max_concurrent_tasks=tester_max_tasks,
    )
    reviewer = create_reviewer(scope_categories=["CONCRETE"])
    signatory = create_signatory(scope_categories=["CONCRETE"])
    instrument = create_instrument(
        capabilities=instrument_capabilities,
        calibration_valid_from=anchor_plus(days=-365),
        calibration_valid_to=anchor_plus(days=365),
    )
    return {
        "client": client,
        "tester": tester,
        "reviewer": reviewer,
        "signatory": signatory,
        "instrument": instrument,
    }


def setup_assigned_task(
    *,
    material_category: str = "CONCRETE",
    test_method: Optional[str] = None,
    urgent: bool = False,
    contract_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Reach the ASSIGNED state for a single task: client → tester →
    instrument → sample → task (auto-assignment fires synchronously).

    Returns dict with the standard env plus `sample` and `task`. The
    task is guaranteed to be ASSIGNED with assigned_tester_id == tester.id.
    """
    if test_method is None:
        test_method = method_for_category(material_category)
    env = setup_concrete_test_environment(
        tester_qualifications=[
            qualification(material_category, DEFAULT_QUAL_VALID_FROM, DEFAULT_QUAL_VALID_TO),
        ],
        instrument_capabilities=[test_method],
        contract_id=contract_id,
    )
    sample = create_sample(
        client_id=env["client"]["id"],
        material_category=material_category,
    )
    task = create_task(
        sample_id=sample["id"], test_method=test_method, urgent=urgent,
    )
    return {**env, "sample": sample, "task": task}


def setup_in_progress_task(
    *,
    material_category: str = "CONCRETE",
    test_method: Optional[str] = None,
    booking_minutes: int = 60,
    contract_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Reach the IN_PROGRESS state. Walks the task to ASSIGNED via
    auto-assignment, books an instrument, then starts the task with the
    actual tester's identity (entity_backed Tester ownership rule)."""
    base = setup_assigned_task(
        material_category=material_category,
        test_method=test_method,
        contract_id=contract_id,
    )
    slot_start = anchor_plus(hours=1)
    slot_end = anchor_plus(hours=1, minutes=booking_minutes)
    booking = book_instrument_for_task(
        instrument_id=base["instrument"]["id"],
        task_id=base["task"]["id"],
        slot_start=slot_start,
        slot_end=slot_end,
    )
    started = start_task(
        task_id=base["task"]["id"],
        tester_id=base["tester"]["id"],
    )
    return {
        **base,
        "booking": booking,
        "task": started,
        "booking_slot_start": slot_start,
        "booking_slot_end": slot_end,
    }


def setup_completed_task(
    *,
    material_category: str = "CONCRETE",
    test_method: Optional[str] = None,
    booking_minutes: int = 60,
    peak_load_kn: float = 600.0,
    contract_id: Optional[str] = None,
    urgent: bool = False,
) -> Dict[str, Any]:
    """Reach the COMPLETED state with a single non-abnormal record. The
    default peak_load_kn=600 with a 150mm cube → 26.7 MPa (in-band)."""
    base = setup_in_progress_task(
        material_category=material_category,
        test_method=test_method,
        booking_minutes=booking_minutes,
        contract_id=contract_id,
    )
    # If urgent is requested, the task created in setup_assigned_task
    # already used urgent=False; recreate by toggling here is unnecessary —
    # urgency only affects priority_seq, not the lifecycle. For tests
    # that need an urgent task, use a dedicated builder below.
    rec = submit_record(
        task_id=base["task"]["id"],
        tester_id=base["tester"]["id"],
        peak_load_kn=peak_load_kn,
    )
    completed = complete_task(
        task_id=base["task"]["id"], tester_id=base["tester"]["id"],
    )
    return {**base, "record": rec, "task": completed}


def setup_completed_urgent_task(
    *,
    material_category: str = "CONCRETE",
    test_method: Optional[str] = None,
    booking_minutes: int = 60,
    peak_load_kn: float = 600.0,
    contract_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Same as setup_completed_task but the underlying task is urgent so
    the resulting invoice can exercise the urgent surcharge."""
    if test_method is None:
        test_method = method_for_category(material_category)
    env = setup_concrete_test_environment(
        tester_qualifications=[
            qualification(material_category, DEFAULT_QUAL_VALID_FROM, DEFAULT_QUAL_VALID_TO),
        ],
        instrument_capabilities=[test_method],
        contract_id=contract_id,
    )
    sample = create_sample(
        client_id=env["client"]["id"],
        material_category=material_category,
    )
    task = create_task(
        sample_id=sample["id"], test_method=test_method, urgent=True,
    )
    slot_start = anchor_plus(hours=1)
    slot_end = anchor_plus(hours=1, minutes=booking_minutes)
    booking = book_instrument_for_task(
        instrument_id=env["instrument"]["id"],
        task_id=task["id"],
        slot_start=slot_start, slot_end=slot_end,
    )
    start_task(task_id=task["id"], tester_id=env["tester"]["id"])
    rec = submit_record(
        task_id=task["id"], tester_id=env["tester"]["id"],
        peak_load_kn=peak_load_kn,
    )
    completed = complete_task(
        task_id=task["id"], tester_id=env["tester"]["id"],
    )
    return {
        **env, "sample": sample, "task": completed, "booking": booking,
        "record": rec,
    }


# ---------------------------------------------------------------------------
# Tier 3: report lifecycle helpers
# ---------------------------------------------------------------------------
def mint_report(*, task_id: str, tester_id: str) -> Dict[str, Any]:
    """PRD §3.9: 'When a TestTask reaches COMPLETED, the assigned Tester
    mints a Report for it.'"""
    res = api_client.create_report(task_id, make_tester_headers(tester_id))
    return get_success_data(res)


def submit_for_review(*, report_id: str, tester_id: str) -> Dict[str, Any]:
    res = api_client.submit_report_for_review(
        report_id, make_tester_headers(tester_id),
    )
    return get_success_data(res)


def approve_review(*, report_id: str, reviewer_id: str) -> Dict[str, Any]:
    res = api_client.approve_review(
        report_id, make_reviewer_headers(reviewer_id),
    )
    return get_success_data(res)


def sign_report(*, report_id: str, signatory_id: str) -> Dict[str, Any]:
    res = api_client.sign_report(
        report_id, make_signatory_headers(signatory_id),
    )
    return get_success_data(res)


def issue_report(*, report_id: str, signatory_id: str) -> Dict[str, Any]:
    res = api_client.issue_report(
        report_id, make_signatory_headers(signatory_id),
    )
    return get_success_data(res)


def setup_signed_report(
    *,
    material_category: str = "CONCRETE",
    test_method: Optional[str] = None,
    booking_minutes: int = 60,
    peak_load_kn: float = 600.0,
) -> Dict[str, Any]:
    """Drive a single task all the way to a SIGNED Report (review approved,
    signatory signed, not yet issued)."""
    base = setup_completed_task(
        material_category=material_category,
        test_method=test_method,
        booking_minutes=booking_minutes,
        peak_load_kn=peak_load_kn,
    )
    report = mint_report(
        task_id=base["task"]["id"], tester_id=base["tester"]["id"],
    )
    submit_for_review(
        report_id=report["id"], tester_id=base["tester"]["id"],
    )
    approve_review(
        report_id=report["id"], reviewer_id=base["reviewer"]["id"],
    )
    signed = sign_report(
        report_id=report["id"], signatory_id=base["signatory"]["id"],
    )
    return {**base, "report": signed}


def setup_issued_report(
    *,
    material_category: str = "CONCRETE",
    test_method: Optional[str] = None,
    booking_minutes: int = 60,
    peak_load_kn: float = 600.0,
) -> Dict[str, Any]:
    """Drive a single task to a fully ISSUED Report. The required Invoice
    is created automatically (issuance precondition per PRD §3.9)."""
    base = setup_signed_report(
        material_category=material_category,
        test_method=test_method,
        booking_minutes=booking_minutes,
        peak_load_kn=peak_load_kn,
    )
    invoice = create_invoice_for_tasks(
        client_id=base["client"]["id"],
        task_ids=[base["task"]["id"]],
    )
    issued = issue_report(
        report_id=base["report"]["id"],
        signatory_id=base["signatory"]["id"],
    )
    return {**base, "invoice": invoice, "report": issued}


# ---------------------------------------------------------------------------
# Tier 4: invoice / financial fixtures
# ---------------------------------------------------------------------------
def create_invoice_for_tasks(*, client_id: str,
                             task_ids: List[str]) -> Dict[str, Any]:
    payload = create_invoice_payload(task_ids=task_ids)
    res = api_client.create_invoice(
        client_id, payload, TEST_USERS["lab_manager_headers"],
    )
    return get_success_data(res)


def credit_deposit(*, client_id: str, amount_cents: int) -> Dict[str, Any]:
    """PRD §3.1: 'The deposit balance is credited when the laboratory
    receives a PaymentReceived external event whose payload omits an
    invoice reference.'"""
    body = emit_event_payload(
        event_type="PaymentReceived",
        payload={"client_id": client_id, "amount_cents": amount_cents},
    )
    res = api_client.emit_event(body, TEST_USERS["lab_manager_headers"])
    return get_success_data(res)


def setup_n_completed_tasks_for_client(
    *,
    n: int,
    urgent: bool = False,
    material_category: str = "CONCRETE",
    test_method: Optional[str] = None,
    deposit_cents: int = 0,
    contract_id: Optional[str] = None,
    booking_minutes: int = 60,
    peak_load_kn: float = 600.0,
) -> Dict[str, Any]:
    """Build a single Client with N COMPLETED tasks ready to invoice.

    Each task uses its own Sample and its own short booking slot to avoid
    instrument overlap. A single Tester with max_concurrent_tasks=n+5 is
    used so workload caps never trip during setup. Tasks are walked to
    COMPLETED one at a time so the tester's active_task_count releases
    back before the next assignment.
    """
    if test_method is None:
        test_method = method_for_category(material_category)
    env = setup_concrete_test_environment(
        tester_qualifications=[
            qualification(material_category, DEFAULT_QUAL_VALID_FROM, DEFAULT_QUAL_VALID_TO),
        ],
        tester_max_tasks=max(DEFAULT_MAX_CONCURRENT_TASKS, n + 5),
        instrument_capabilities=[test_method],
        contract_id=contract_id,
    )
    if deposit_cents:
        credit_deposit(
            client_id=env["client"]["id"], amount_cents=deposit_cents,
        )
        env["client"] = get_success_data(
            api_client.get_client(
                env["client"]["id"], TEST_USERS["lab_manager_headers"],
            ),
        )

    samples: List[Dict[str, Any]] = []
    tasks: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    for i in range(n):
        sample = create_sample(
            client_id=env["client"]["id"],
            material_category=material_category,
        )
        task = create_task(
            sample_id=sample["id"], test_method=test_method, urgent=urgent,
        )
        slot_start = anchor_plus(
            hours=2 + i * 2,  # 2-hour stride per task
        )
        slot_end = anchor_plus(
            hours=2 + i * 2, minutes=booking_minutes,
        )
        booking = book_instrument_for_task(
            instrument_id=env["instrument"]["id"],
            task_id=task["id"],
            slot_start=slot_start, slot_end=slot_end,
        )
        start_task(task_id=task["id"], tester_id=env["tester"]["id"])
        rec = submit_record(
            task_id=task["id"], tester_id=env["tester"]["id"],
            peak_load_kn=peak_load_kn,
            test_method=test_method,
        )
        task = complete_task(
            task_id=task["id"], tester_id=env["tester"]["id"],
        )
        samples.append(sample)
        tasks.append(task)
        records.append(rec)
        # bookings are append-only and we don't need them after completion
    return {**env, "samples": samples, "tasks": tasks, "records": records}


# ---------------------------------------------------------------------------
# Tier 5: retest / abnormal fixtures
# ---------------------------------------------------------------------------
def setup_task_with_abnormal_first_record(
    *,
    material_category: str = "CONCRETE",
) -> Dict[str, Any]:
    """Drive a task to AWAITING_RETEST by submitting an initial abnormal
    record (peak_load_kn=400 → 17.8 MPa on a 150mm cube, below LOWER=20).
    """
    base = setup_in_progress_task(material_category=material_category)
    first = submit_record(
        task_id=base["task"]["id"],
        tester_id=base["tester"]["id"],
        peak_load_kn=400.0,
    )
    return {**base, "first_record": first}


def setup_task_with_retest_abnormal_final(
    *,
    material_category: str = "CONCRETE",
) -> Dict[str, Any]:
    """Drive a task through one retest where the retest record is ALSO
    abnormal (peak_load_kn=400 → 17.8 MPa, still below LOWER=20). This is
    the condition under which an invoice would apply the 30% refund."""
    base = setup_task_with_abnormal_first_record(
        material_category=material_category,
    )
    retest = submit_record(
        task_id=base["task"]["id"],
        tester_id=base["tester"]["id"],
        peak_load_kn=400.0,
        supersedes_record_id=base["first_record"]["id"],
    )
    return {**base, "retest_record": retest}


# ---------------------------------------------------------------------------
# Tier 6: clock-advance helpers
# ---------------------------------------------------------------------------
def advance_clock_to(*, to: str) -> Dict[str, Any]:
    body = clock_advance_payload(to=to)
    res = api_client.advance_clock(body, TEST_USERS["lab_manager_headers"])
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 7: per-difficulty-design composite fixtures
# ---------------------------------------------------------------------------
def setup_workload_cap_environment(
    *,
    max_concurrent_tasks: int = 2,
) -> Dict[str, Any]:
    """For tester workload tests (difficulty-design instance
    workload_cap_exact_equality_boundary). Creates a single tester at
    max_concurrent_tasks=2 with two existing tasks already ASSIGNED
    (active_task_count == 2)."""
    env = setup_concrete_test_environment(
        tester_qualifications=[
            qualification("CONCRETE", DEFAULT_QUAL_VALID_FROM, DEFAULT_QUAL_VALID_TO),
        ],
        tester_max_tasks=max_concurrent_tasks,
    )
    samples: List[Dict[str, Any]] = []
    tasks: List[Dict[str, Any]] = []
    for _ in range(max_concurrent_tasks):
        sample = create_sample(
            client_id=env["client"]["id"], material_category="CONCRETE",
        )
        task = create_task(
            sample_id=sample["id"], test_method="COMPRESSION_STRENGTH",
        )
        samples.append(sample)
        tasks.append(task)
    return {**env, "occupying_samples": samples, "occupying_tasks": tasks}


def setup_two_qualified_testers_with_capacity(
    *,
    other_active_count: int = 2,
) -> Dict[str, Any]:
    """Difficulty-design tester_workload_conservation_under_reassign.
    Two testers qualified for CONCRETE: T1 already has `other_active_count`
    ASSIGNED tasks, T2 has zero. A third sample is then created and a new
    task auto-assigns to T2 (workload-balancing tie-break)."""
    client = create_client()
    tester_t1 = create_tester(
        qualifications=[
            qualification("CONCRETE", DEFAULT_QUAL_VALID_FROM, DEFAULT_QUAL_VALID_TO),
        ],
        max_concurrent_tasks=DEFAULT_MAX_CONCURRENT_TASKS,
    )
    # Pre-load T1 with active tasks (uses a second tester only briefly).
    occupying_samples: List[Dict[str, Any]] = []
    occupying_tasks: List[Dict[str, Any]] = []
    for _ in range(other_active_count):
        sample = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        # By creating these tasks before T2 exists, the only candidate is
        # T1 → auto-assigns to T1.
        task = create_task(
            sample_id=sample["id"], test_method="COMPRESSION_STRENGTH",
        )
        occupying_samples.append(sample)
        occupying_tasks.append(task)

    tester_t2 = create_tester(
        qualifications=[
            qualification("CONCRETE", DEFAULT_QUAL_VALID_FROM, DEFAULT_QUAL_VALID_TO),
        ],
        max_concurrent_tasks=DEFAULT_MAX_CONCURRENT_TASKS,
    )

    # Refresh T1 to capture its active_task_count after the pre-load.
    tester_t1 = get_success_data(
        api_client.get_tester(
            tester_t1["id"], TEST_USERS["lab_manager_headers"],
        ),
    )
    return {
        "client": client,
        "tester_t1": tester_t1,
        "tester_t2": tester_t2,
        "occupying_samples": occupying_samples,
        "occupying_tasks": occupying_tasks,
    }


def setup_no_qualified_tester_environment() -> Dict[str, Any]:
    """Difficulty-design empty_eligible_tester_pool_at_assignment. Only
    STEEL_REBAR testers exist; sample is CONCRETE."""
    client = create_client()
    create_tester(
        qualifications=[
            qualification("STEEL_REBAR", DEFAULT_QUAL_VALID_FROM, DEFAULT_QUAL_VALID_TO),
        ],
    )
    sample = create_sample(
        client_id=client["id"], material_category="CONCRETE",
    )
    return {"client": client, "sample": sample}


def setup_steel_only_testers_concrete_sample() -> Dict[str, Any]:
    """Difficulty-design instance
    business_referential_vs_business_constraint_on_task_creation.
    All testers are STEEL_REBAR-only; sample is CONCRETE.  Used to assert
    that even when both ERR_TEST_METHOD_NOT_SUPPORTED *and*
    ERR_NO_QUALIFIED_TESTER could fire, the referential check (priority 11)
    wins."""
    client = create_client()
    create_tester(
        qualifications=[
            qualification("STEEL_REBAR", DEFAULT_QUAL_VALID_FROM, DEFAULT_QUAL_VALID_TO),
        ],
    )
    sample = create_sample(
        client_id=client["id"], material_category="CONCRETE",
    )
    return {"client": client, "sample": sample}


def setup_instrument_with_short_calibration(
    *,
    calibration_end: str,
) -> Dict[str, Any]:
    """Create an instrument that is currently AVAILABLE but whose
    calibration_valid_to is `calibration_end` — used by clock-advance
    cascade tests for calibration lapses."""
    return create_instrument(
        capabilities=["COMPRESSION_STRENGTH"],
        calibration_valid_from=anchor_plus(days=-30),
        calibration_valid_to=calibration_end,
    )


def setup_assigned_task_with_short_calibration(
    *,
    calibration_end: str,
    booking_start_offset_minutes: int = 1440,  # default: booking 1 day later
) -> Dict[str, Any]:
    """Build a fully ASSIGNED task with a RESERVED future booking, where
    the instrument's calibration ends at `calibration_end`. Used by the
    instrument_calibration_lapse_cascade difficulty-design instance.

    The caller is responsible for choosing a `calibration_end` that is
    strictly after the server's logical clock (the clock can only
    advance forward). The cascade test then calls advance_clock_to(...)
    to push the clock past calibration_end."""
    client = create_client()
    tester = create_tester(
        qualifications=[
            qualification("CONCRETE", DEFAULT_QUAL_VALID_FROM, DEFAULT_QUAL_VALID_TO),
        ],
    )
    instrument = create_instrument(
        capabilities=["COMPRESSION_STRENGTH"],
        calibration_valid_from=anchor_plus(days=-30),
        calibration_valid_to=calibration_end,
    )
    sample = create_sample(
        client_id=client["id"], material_category="CONCRETE",
    )
    task = create_task(
        sample_id=sample["id"], test_method="COMPRESSION_STRENGTH",
    )
    slot_start = anchor_plus(minutes=booking_start_offset_minutes)
    slot_end = anchor_plus(minutes=booking_start_offset_minutes + 60)
    booking = book_instrument_for_task(
        instrument_id=instrument["id"], task_id=task["id"],
        slot_start=slot_start, slot_end=slot_end,
    )
    return {
        "client": client,
        "tester": tester,
        "instrument": instrument,
        "sample": sample,
        "task": task,
        "booking": booking,
        "slot_start": slot_start,
        "slot_end": slot_end,
    }


def get_task(task_id: str) -> Dict[str, Any]:
    res = api_client.get_task(task_id, TEST_USERS["lab_manager_headers"])
    return get_success_data(res)


def get_tester(tester_id: str) -> Dict[str, Any]:
    res = api_client.get_tester(
        tester_id, TEST_USERS["lab_manager_headers"],
    )
    return get_success_data(res)


def get_instrument(instrument_id: str) -> Dict[str, Any]:
    res = api_client.get_instrument(
        instrument_id, TEST_USERS["lab_manager_headers"],
    )
    return get_success_data(res)


def get_sample(sample_id: str) -> Dict[str, Any]:
    res = api_client.get_sample(sample_id, TEST_USERS["lab_clerk_headers"])
    return get_success_data(res)


def get_report(report_id: str) -> Dict[str, Any]:
    res = api_client.get_report(
        report_id, TEST_USERS["lab_manager_headers"],
    )
    return get_success_data(res)


def get_invoice(invoice_id: str) -> Dict[str, Any]:
    res = api_client.get_invoice(
        invoice_id, TEST_USERS["lab_manager_headers"],
    )
    return get_success_data(res)


def get_client(client_id: str) -> Dict[str, Any]:
    res = api_client.get_client(
        client_id, TEST_USERS["lab_manager_headers"],
    )
    return get_success_data(res)


def get_first_booking_for_instrument(instrument_id: str) -> Optional[Dict[str, Any]]:
    """Helper: fetch the first booking for an instrument (used by cascade
    tests that want to read the booking's updated status)."""
    res = api_client.list_instrument_bookings(
        instrument_id, TEST_USERS["lab_manager_headers"],
        params={"limit": 100},
    )
    data = get_success_data(res)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    if isinstance(data, list) and data:
        return data[0]
    return None


__all__ = [
    "iso",
    "parse_iso",
    "CLOCK_ANCHOR",
    "anchor_plus",
    "create_client",
    "create_tester",
    "create_reviewer",
    "create_signatory",
    "create_instrument",
    "create_sample",
    "create_task",
    "book_instrument_for_task",
    "start_task",
    "submit_record",
    "complete_task",
    "setup_concrete_test_environment",
    "setup_assigned_task",
    "setup_in_progress_task",
    "setup_completed_task",
    "setup_completed_urgent_task",
    "mint_report",
    "submit_for_review",
    "approve_review",
    "sign_report",
    "issue_report",
    "setup_signed_report",
    "setup_issued_report",
    "create_invoice_for_tasks",
    "credit_deposit",
    "setup_n_completed_tasks_for_client",
    "setup_task_with_abnormal_first_record",
    "setup_task_with_retest_abnormal_final",
    "advance_clock_to",
    "setup_workload_cap_environment",
    "setup_two_qualified_testers_with_capacity",
    "setup_no_qualified_tester_environment",
    "setup_steel_only_testers_concrete_sample",
    "setup_instrument_with_short_calibration",
    "setup_assigned_task_with_short_calibration",
    "get_task",
    "get_tester",
    "get_instrument",
    "get_sample",
    "get_report",
    "get_invoice",
    "get_client",
    "get_first_booking_for_instrument",
]
