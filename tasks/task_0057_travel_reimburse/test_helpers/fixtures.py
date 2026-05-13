"""Composite setup helpers for the Travel Reimburse API test suite.

Most testable claims require the system to be in a specific state that
takes 5–15 API calls to reach (admin bootstrap → ExpenseStandard publish
→ employee + supervisor + dept-head + finance + GM creation → travel
application create → submit → approval chain → bookings → invoice
upload + OCR + tax-verify → form create → item attach → form submit →
form approval chain → payment batch → execute → result). These fixtures
encapsulate those preambles so test bodies focus on assertions.

Identity threading (PRD §2.1, MANDATORY):
- Applicant, Supervisor, DeptHead, Finance, GeneralManager are
  ENTITY-BACKED by Employee. The X-User-ID for these roles MUST equal
  the Employee.id of the acting principal. Every helper that needs to
  act under an entity-backed role calls the per-instance builder
  (make_applicant_headers(emp_id), etc.) with the actual Employee.id
  returned by POST /employees. Falling back to the shared TEST_USERS
  constant would cause every ownership/chain-step check to fail because
  the placeholder strings ('applicant-fallback', etc.) are never equal
  to any real Employee.id.

- Admin is OPAQUE; the shared TEST_USERS['admin_headers'] is canonical
  for all admin operations.

Setup helpers use get_success_data() (lenient validator) so broken
preconditions surface as clear 'Setup failed' errors, not confusing
assertion failures inside test bodies.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    add_item_payload,
    approval_payload,
    book_segment_payload,
    booking_options_payload,
    clock_payload,
    create_employee_payload,
    create_expense_standard_payload,
    create_form_payload,
    create_travel_application_payload,
    payment_batch_payload,
    payment_result_payload,
    reject_form_payload,
    reject_payload,
    tax_verify_pin_payload,
    unique_invoice_code,
    unique_invoice_number,
    unique_option_code,
    upload_invoice_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_applicant_headers,
    make_dept_head_headers,
    make_finance_headers,
    make_general_manager_headers,
    make_supervisor_headers,
)


# ===========================================================================
# Shared constants
# ===========================================================================
ADMIN = TEST_USERS["admin_headers"]

# Standard test windows (PRD-faithful ISO 8601 UTC with millisecond precision)
DEFAULT_PLANNED_START = "2025-06-01T09:00:00.000Z"
DEFAULT_PLANNED_END = "2025-06-04T18:00:00.000Z"

# A wide ExpenseStandard window covering all test scenarios that don't
# specifically exercise the auto-close / version-rollover path.
WIDE_EFFECTIVE_FROM = "2024-01-01T00:00:00.000Z"


def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision, Z-suffixed (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Per PRD §3.1: when publishing into a bucket that already has a row, the
# new row's effective_from MUST be strictly later than every prior row's
# effective_from for that bucket. The implementation under test enforces
# this rule. Because the test process shares a single in-memory store
# across all tests in the suite, fixtures that default to the same
# (city_tier, employee_level) bucket would collide after the first
# publish. We track a per-bucket "high-water-mark" of the largest
# millisecond offset already consumed in each bucket so each fixture-
# driven publish is strictly later than the previous one in that bucket
# while still falling inside the wide [2024-01-01, ...) window the
# default-driven tests need.
_BUCKET_PUBLISH_WATERMARK: Dict[Tuple[str, str], int] = {}
_BUCKET_BASE = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _next_effective_from_for_bucket(city_tier: str, employee_level: str) -> str:
    """Return a unique effective_from for the (city_tier, employee_level)
    bucket, strictly later than every previous fixture-driven publish in
    the same bucket within this test session. Advances the per-bucket
    watermark by one millisecond per call.
    """
    key = (city_tier, employee_level)
    seq = _BUCKET_PUBLISH_WATERMARK.get(key, -1) + 1
    _BUCKET_PUBLISH_WATERMARK[key] = seq
    return iso_z(_BUCKET_BASE + timedelta(milliseconds=seq))


def _bump_effective_from_past_bucket(
    city_tier: str, employee_level: str, requested: str,
) -> str:
    """When a test supplies an explicit `effective_from` for a bucket
    that may already contain prior publishes in this test session, ensure
    the returned value is strictly later than every prior publish in the
    same bucket. The returned value is the later of (the requested
    timestamp) and (the next watermark slot). This preserves the
    semantics tests usually want — "a wide window covering my test" —
    while complying with PRD §3.1's strict ordering rule under a shared
    in-memory store.
    """
    key = (city_tier, employee_level)
    requested_dt = datetime.fromisoformat(requested.replace("Z", "+00:00"))
    requested_offset_ms = int(
        (requested_dt - _BUCKET_BASE).total_seconds() * 1000,
    )
    current = _BUCKET_PUBLISH_WATERMARK.get(key, -1)
    next_offset = max(requested_offset_ms, current + 1)
    _BUCKET_PUBLISH_WATERMARK[key] = next_offset
    return iso_z(_BUCKET_BASE + timedelta(milliseconds=next_offset))


# ===========================================================================
# Tier 0 — Bootstrap helpers (employees, standards, eligible options)
# ===========================================================================
def create_employee(
    full_name: Optional[str] = None,
    employee_level: str = "STAFF",
    supervisor_id: Optional[str] = None,
    department_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Admin creates an Employee. Returns the persisted Employee dict.

    PRD §3.1: only Admin may POST /employees. Newly created employees
    default to status=ACTIVE.
    """
    payload = create_employee_payload(
        full_name=full_name or f"Employee-{uuid.uuid4().hex[:6]}",
        employee_level=employee_level,
        supervisor_id=supervisor_id,
        department_id=department_id,
    )
    return get_success_data(
        api_client.create_employee(payload, ADMIN)
    )


def publish_expense_standard(
    version: int = 1,
    city_tier: str = "TIER_2",
    employee_level: str = "STAFF",
    effective_from: Optional[str] = None,
    effective_to: Optional[str] = None,
    lodging_daily_cap: float = 400.00,
    per_diem_amount: float = 80.00,
    transportation_daily_cap: float = 120.00,
    holiday_multiplier: float = 1.00,
) -> Dict[str, Any]:
    """Admin publishes one ExpenseStandard row. PRD §3.1.

    When `effective_from` is not supplied, the helper allocates a
    bucket-monotonic timestamp so that successive default-driven publishes
    in the same (city_tier, employee_level) bucket satisfy PRD §3.1's
    strictly-later-than-prior-effective_from rule. Tests that need a
    specific `effective_from` (e.g., the dual-version pinning scenarios in
    Tier 9) continue to pass an explicit value.
    """
    if effective_from is None:
        effective_from = _next_effective_from_for_bucket(
            city_tier, employee_level,
        )
    else:
        effective_from = _bump_effective_from_past_bucket(
            city_tier, employee_level, effective_from,
        )
    payload = create_expense_standard_payload(
        version=version,
        effective_from=effective_from,
        effective_to=effective_to,
        city_tier=city_tier,
        employee_level=employee_level,
        lodging_daily_cap=lodging_daily_cap,
        per_diem_amount=per_diem_amount,
        transportation_daily_cap=transportation_daily_cap,
        holiday_multiplier=holiday_multiplier,
    )
    return get_success_data(
        api_client.create_expense_standard(payload, ADMIN)
    )


def seed_eligible_option(
    segment_type: str,
    employee_level: str,
    option_codes: List[str],
) -> None:
    """Test-harness seed of the policy-eligible option set. PRD §3.10."""
    get_success_data(
        api_client.seed_booking_options(
            booking_options_payload(segment_type, employee_level, option_codes),
            ADMIN,
        )
    )


# ===========================================================================
# Tier 1 — Cast assembly (a complete approval-chain population)
# ===========================================================================
class ApprovalCast:
    """Holds Employee rows + identity-threaded headers for a fully wired
    approval chain.

    Every header below is built with make_*_headers(employee['id']) so
    ownership and chain-step checks resolve correctly.
    """

    def __init__(
        self,
        applicant: Dict[str, Any],
        supervisor: Dict[str, Any],
        dept_head: Dict[str, Any],
        finance: Dict[str, Any],
        gm: Dict[str, Any],
    ) -> None:
        self.applicant = applicant
        self.supervisor = supervisor
        self.dept_head = dept_head
        self.finance = finance
        self.gm = gm

        # Identity-threaded headers — these are the ONLY safe headers to
        # pass on any ownership/chain-step gated call.
        self.applicant_headers = make_applicant_headers(applicant["id"])
        self.supervisor_headers = make_supervisor_headers(supervisor["id"])
        self.dept_head_headers = make_dept_head_headers(dept_head["id"])
        self.finance_headers = make_finance_headers(finance["id"])
        self.gm_headers = make_general_manager_headers(gm["id"])


def create_approval_cast(
    applicant_level: str = "STAFF",
    department_id: Optional[str] = None,
) -> ApprovalCast:
    """Stand up one supervisor + dept-head + finance + GM + applicant.

    Returns an ApprovalCast object whose `*_headers` properties carry
    the correct X-User-ID per PRD §2.1 — supervisor.id matches the
    applicant's supervisor_id, etc.
    """
    department_id = department_id or f"dept-{uuid.uuid4().hex[:8]}"
    supervisor = create_employee(
        full_name=f"Supervisor-{uuid.uuid4().hex[:6]}",
        employee_level="MANAGER",
        department_id=department_id,
    )
    dept_head = create_employee(
        full_name=f"DeptHead-{uuid.uuid4().hex[:6]}",
        employee_level="DIRECTOR",
        department_id=department_id,
    )
    finance = create_employee(
        full_name=f"Finance-{uuid.uuid4().hex[:6]}",
        employee_level="MANAGER",
        department_id=f"finance-{uuid.uuid4().hex[:8]}",
    )
    gm = create_employee(
        full_name=f"GM-{uuid.uuid4().hex[:6]}",
        employee_level="EXECUTIVE",
        department_id=f"exec-{uuid.uuid4().hex[:8]}",
    )
    applicant = create_employee(
        full_name=f"Applicant-{uuid.uuid4().hex[:6]}",
        employee_level=applicant_level,
        supervisor_id=supervisor["id"],
        department_id=department_id,
    )
    return ApprovalCast(
        applicant=applicant,
        supervisor=supervisor,
        dept_head=dept_head,
        finance=finance,
        gm=gm,
    )


# ===========================================================================
# Tier 2 — Baseline reference data + a complete cast
# ===========================================================================
def standard_test_environment(
    applicant_level: str = "STAFF",
    destination_tier: str = "TIER_2",
    lodging_daily_cap: float = 400.00,
    per_diem_amount: float = 80.00,
    transportation_daily_cap: float = 120.00,
    holiday_multiplier: float = 1.00,
    standard_version: int = 1,
    standard_effective_from: Optional[str] = None,
    standard_effective_to: Optional[str] = None,
    seed_options_for: Optional[List[Tuple[str, str]]] = None,
    extra_option_codes: Optional[Dict[Tuple[str, str], List[str]]] = None,
) -> Tuple[ApprovalCast, Dict[str, Any]]:
    """Bootstrap: publish an ExpenseStandard, seed eligible options,
    create a complete approval cast.

    `seed_options_for` is a list of (segment_type, employee_level) pairs
    for which to seed a default eligible option code. Tests then book
    segments using the returned cast and option codes.

    Returns (cast, standard_row).
    """
    standard = publish_expense_standard(
        version=standard_version,
        city_tier=destination_tier,
        employee_level=applicant_level,
        effective_from=standard_effective_from,
        effective_to=standard_effective_to,
        lodging_daily_cap=lodging_daily_cap,
        per_diem_amount=per_diem_amount,
        transportation_daily_cap=transportation_daily_cap,
        holiday_multiplier=holiday_multiplier,
    )
    cast = create_approval_cast(applicant_level=applicant_level)

    # Default: seed FLIGHT, TRAIN, HOTEL, CAR for the applicant's level.
    pairs = seed_options_for or [
        ("FLIGHT", applicant_level),
        ("TRAIN", applicant_level),
        ("HOTEL", applicant_level),
        ("CAR", applicant_level),
    ]
    for seg_type, level in pairs:
        codes = (extra_option_codes or {}).get(
            (seg_type, level), [f"OPT-{seg_type}-001", f"OPT-{seg_type}-002"]
        )
        seed_eligible_option(seg_type, level, codes)
    return cast, standard


# ===========================================================================
# Tier 3 — TravelApplication lifecycle shortcuts
# ===========================================================================
def draft_application(
    cast: ApprovalCast,
    *,
    destination_city: str = "Shanghai",
    destination_tier: str = "TIER_2",
    travel_scope: str = "DOMESTIC",
    purpose: str = "Customer onboarding visit",
    planned_start: str = DEFAULT_PLANNED_START,
    planned_end: str = DEFAULT_PLANNED_END,
    estimated_budget: float = 2_000.00,
    urgent: Optional[bool] = None,
) -> Dict[str, Any]:
    """Create a DRAFT TravelApplication owned by cast.applicant."""
    payload = create_travel_application_payload(
        destination_city=destination_city,
        destination_tier=destination_tier,
        travel_scope=travel_scope,
        purpose=purpose,
        planned_start=planned_start,
        planned_end=planned_end,
        estimated_budget=estimated_budget,
        urgent=urgent,
    )
    return get_success_data(
        api_client.create_travel_application(payload, cast.applicant_headers)
    )


def submit_application(
    cast: ApprovalCast,
    application: Dict[str, Any],
) -> Dict[str, Any]:
    """DRAFT → SUBMITTED via POST /submit."""
    return get_success_data(
        api_client.submit_travel_application(
            application["id"], cast.applicant_headers,
        )
    )


def walk_approval_chain(
    cast: ApprovalCast,
    application: Dict[str, Any],
) -> Dict[str, Any]:
    """Walk the full required_chain to APPROVED.

    Re-reads the application after submit to discover the pinned
    required_chain, then issues one approve call per chain step using
    the correctly-threaded role headers from the cast.
    """
    app_id = application["id"]
    submitted = submit_application(cast, application)
    chain: List[str] = submitted["required_chain"]

    role_to_headers = {
        "SUPERVISOR": cast.supervisor_headers,
        "DEPT_HEAD": cast.dept_head_headers,
        "FINANCE": cast.finance_headers,
        "GM": cast.gm_headers,
    }
    latest = submitted
    for step in chain:
        latest = get_success_data(
            api_client.approve_travel_application(
                app_id, role_to_headers[step], approval_payload(),
            )
        )
    return latest


def approved_application(
    cast: Optional[ApprovalCast] = None,
    *,
    destination_city: str = "Shanghai",
    destination_tier: str = "TIER_2",
    travel_scope: str = "DOMESTIC",
    estimated_budget: float = 2_000.00,
    urgent: Optional[bool] = None,
    planned_start: str = DEFAULT_PLANNED_START,
    planned_end: str = DEFAULT_PLANNED_END,
    purpose: str = "Customer onboarding visit",
    env_kwargs: Optional[Dict[str, Any]] = None,
) -> Tuple[ApprovalCast, Dict[str, Any]]:
    """End-to-end: bootstrap env + cast (if not supplied) + draft +
    submit + walk approval chain. Returns (cast, APPROVED application)."""
    if cast is None:
        cast, _standard = standard_test_environment(
            destination_tier=destination_tier,
            **(env_kwargs or {}),
        )
    app = draft_application(
        cast,
        destination_city=destination_city,
        destination_tier=destination_tier,
        travel_scope=travel_scope,
        purpose=purpose,
        planned_start=planned_start,
        planned_end=planned_end,
        estimated_budget=estimated_budget,
        urgent=urgent,
    )
    approved = walk_approval_chain(cast, app)
    return cast, approved


# ===========================================================================
# Tier 4 — Itinerary helpers
# ===========================================================================
def book_segment(
    cast: ApprovalCast,
    app_id: str,
    *,
    segment_type: str = "FLIGHT",
    option_code: Optional[str] = None,
    start_at: str = "2025-06-01T10:00:00.000Z",
    end_at: str = "2025-06-01T13:00:00.000Z",
    cost: float = 500.00,
    extra_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Book one ItinerarySegment under an APPROVED / BOOKING_LOCKED app.

    Defaults the option_code to OPT-{TYPE}-001 which standard_test_environment
    seeds by default.
    """
    overrides = dict(extra_overrides or {})
    payload = book_segment_payload(
        segment_type=segment_type,
        option_code=option_code or f"OPT-{segment_type}-001",
        start_at=start_at,
        end_at=end_at,
        cost=cost,
        **overrides,
    )
    return get_success_data(
        api_client.book_itinerary(app_id, payload, cast.applicant_headers)
    )


def approved_application_with_segment(
    *,
    segment_type: str = "HOTEL",
    cost: float = 1350.00,
    seg_start: str = "2025-06-01T15:00:00.000Z",
    seg_end: str = "2025-06-04T11:00:00.000Z",
    destination_tier: str = "TIER_2",
    estimated_budget: float = 2_000.00,
    standard_kwargs: Optional[Dict[str, Any]] = None,
    travel_scope: str = "DOMESTIC",
) -> Tuple[ApprovalCast, Dict[str, Any], Dict[str, Any]]:
    """Approved application + one booked segment. Returns
    (cast, application, segment). After this call the application is
    in BOOKING_LOCKED."""
    cast, app = approved_application(
        destination_tier=destination_tier,
        travel_scope=travel_scope,
        estimated_budget=estimated_budget,
        env_kwargs=standard_kwargs,
    )
    segment = book_segment(
        cast, app["id"],
        segment_type=segment_type,
        start_at=seg_start,
        end_at=seg_end,
        cost=cost,
    )
    return cast, app, segment


# ===========================================================================
# Tier 5 — Invoice lifecycle (upload → OCR → tax-verify → ATTACH-ready)
# ===========================================================================
def upload_and_verify_invoice(
    cast: ApprovalCast,
    *,
    category: str = "LODGING",
    amount: float = 1350.00,
    invoice_date: str = "2025-06-02T12:00:00.000Z",
    verdict: str = "VALID",
    invoice_number: Optional[str] = None,
    invoice_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Upload → OCR → pin VALID/INVALID outcome → verify-tax.

    Returns the invoice in TAX_VERIFIED (when verdict=VALID) or REJECTED
    (when verdict=INVALID). The applicant_id is the cast.applicant
    (identity-threaded).
    """
    payload = upload_invoice_payload(
        applicant_id=cast.applicant["id"],
        invoice_number=invoice_number,
        invoice_code=invoice_code,
        category=category,
        amount=amount,
        invoice_date=invoice_date,
    )
    invoice = get_success_data(
        api_client.upload_invoice(payload, cast.applicant_headers)
    )

    # OCR step (no idempotency key — fresh call).
    get_success_data(
        api_client.ocr_invoice(invoice["id"], cast.applicant_headers)
    )

    # Pin verdict for the next verify-tax call (admin test-harness).
    get_success_data(
        api_client.pin_invoice_verify_result(
            tax_verify_pin_payload(invoice["id"], verdict),
            ADMIN,
        )
    )

    # Run tax verification.
    verified = get_success_data(
        api_client.verify_tax_invoice(invoice["id"], cast.applicant_headers)
    )
    return verified


# ===========================================================================
# Tier 6 — ReimbursementForm lifecycle
# ===========================================================================
def create_form(cast: ApprovalCast, app_id: str) -> Dict[str, Any]:
    """Create a DRAFT ReimbursementForm bound to an application."""
    return get_success_data(
        api_client.create_reimbursement_form(
            create_form_payload(application_id=app_id),
            cast.applicant_headers,
        )
    )


def attach_item(
    cast: ApprovalCast,
    form_id: str,
    *,
    invoice_id: str,
    category: str = "LODGING",
    covered_days: int = 3,
    claimed_amount: float = 1350.00,
    matched_segment_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach a ReimbursementItem to a DRAFT form."""
    payload = add_item_payload(
        invoice_id=invoice_id,
        category=category,
        covered_days=covered_days,
        claimed_amount=claimed_amount,
        matched_segment_id=matched_segment_id,
    )
    return get_success_data(
        api_client.add_reimbursement_item(
            form_id, payload, cast.applicant_headers,
        )
    )


def submit_form(cast: ApprovalCast, form_id: str) -> Dict[str, Any]:
    """DRAFT → SUBMITTED (runs final-settlement recompute)."""
    return get_success_data(
        api_client.submit_reimbursement_form(form_id, cast.applicant_headers)
    )


def walk_form_approval_chain(
    cast: ApprovalCast,
    form: Dict[str, Any],
    *,
    stop_at_state: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk a ReimbursementForm through the SUPERVISOR → DEPT_HEAD →
    FINANCE [→ GM] sequence, stopping at the named state if supplied.

    PRD §3.7: the form chain is always four roles deep (SUPERVISOR,
    DEPT_HEAD, FINANCE), with an optional GM step driven by
    requires_special_approval.
    """
    form_id = form["id"]
    sequence = [
        ("SUPERVISOR", cast.supervisor_headers, "SUPERVISOR_APPROVED"),
        ("DEPT_HEAD", cast.dept_head_headers, "DEPT_APPROVED"),
        ("FINANCE", cast.finance_headers, "FINANCE_APPROVED"),
    ]
    latest = form
    for _, hdrs, after_state in sequence:
        latest = get_success_data(
            api_client.approve_reimbursement_form(
                form_id, hdrs, approval_payload(),
            )
        )
        if stop_at_state == after_state:
            return latest

    # If still at FINANCE_APPROVED and special approval required → GM.
    if latest.get("status") == "FINANCE_APPROVED":
        if latest.get("requires_special_approval"):
            latest = get_success_data(
                api_client.approve_reimbursement_form(
                    form_id, cast.gm_headers, approval_payload(),
                )
            )
        else:
            # FINANCE issues the terminal approval (FINANCE_APPROVED → APPROVED).
            latest = get_success_data(
                api_client.approve_reimbursement_form(
                    form_id, cast.finance_headers, approval_payload(),
                )
            )
    return latest


# ===========================================================================
# Tier 7 — End-to-end "form ready for payment" composites
# ===========================================================================
def approved_form_with_one_lodging_item(
    *,
    lodging_daily_cap: float = 400.00,
    holiday_multiplier: float = 1.00,
    destination_tier: str = "TIER_2",
    applicant_level: str = "STAFF",
    travel_scope: str = "DOMESTIC",
    estimated_budget: float = 2_000.00,
    hotel_cost: float = 1350.00,
    covered_days: int = 3,
    claimed_amount: float = 1350.00,
    invoice_amount: Optional[float] = None,
) -> Tuple[
    ApprovalCast, Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """One HOTEL segment + one LODGING item; walk form to APPROVED.

    With default caps lodging=400, covered_days=3, claimed=1350:
    - standard_cap_applied = 400 * 3 = 1200.00
    - reimbursable_amount = min(1350, 1200) = 1200.00
    - self_paid_amount = 150.00
    - requires_special_approval = true (total_self_paid > 0)
    - Form walks through SUPERVISOR → DEPT_HEAD → FINANCE → GM → APPROVED.

    Returns (cast, application, segment, invoice, approved_form).
    """
    seg_start = "2025-06-01T15:00:00.000Z"
    seg_end = "2025-06-04T11:00:00.000Z"

    cast, _std = standard_test_environment(
        applicant_level=applicant_level,
        destination_tier=destination_tier,
        lodging_daily_cap=lodging_daily_cap,
        holiday_multiplier=holiday_multiplier,
    )
    # Stand up an APPROVED application via that cast.
    app = draft_application(
        cast,
        destination_tier=destination_tier,
        travel_scope=travel_scope,
        planned_start="2025-06-01T09:00:00.000Z",
        planned_end="2025-06-04T18:00:00.000Z",
        estimated_budget=estimated_budget,
    )
    walk_approval_chain(cast, app)

    segment = book_segment(
        cast, app["id"],
        segment_type="HOTEL",
        start_at=seg_start,
        end_at=seg_end,
        cost=hotel_cost,
    )
    invoice = upload_and_verify_invoice(
        cast,
        category="LODGING",
        amount=invoice_amount if invoice_amount is not None else claimed_amount,
        invoice_date="2025-06-02T12:00:00.000Z",
    )
    form = create_form(cast, app["id"])
    attach_item(
        cast, form["id"],
        invoice_id=invoice["id"],
        category="LODGING",
        covered_days=covered_days,
        claimed_amount=claimed_amount,
        matched_segment_id=segment["id"],
    )
    submitted = submit_form(cast, form["id"])
    approved = walk_form_approval_chain(cast, submitted)
    return cast, app, segment, invoice, approved


def approved_form_no_self_paid(
    *,
    applicant_level: str = "STAFF",
    destination_tier: str = "TIER_2",
    travel_scope: str = "DOMESTIC",
) -> Tuple[
    ApprovalCast, Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """Same as approved_form_with_one_lodging_item but claimed_amount is
    UNDER the cap so total_self_paid == 0 and the form does NOT require
    GM approval. FINANCE issues the terminal APPROVED transition."""
    cast, _std = standard_test_environment(
        applicant_level=applicant_level,
        destination_tier=destination_tier,
        lodging_daily_cap=400.00,
    )
    app = draft_application(
        cast,
        destination_tier=destination_tier,
        travel_scope=travel_scope,
        estimated_budget=2_000.00,
    )
    walk_approval_chain(cast, app)
    seg = book_segment(
        cast, app["id"],
        segment_type="HOTEL",
        start_at="2025-06-01T15:00:00.000Z",
        end_at="2025-06-04T11:00:00.000Z",
        cost=600.00,
    )
    invoice = upload_and_verify_invoice(
        cast, category="LODGING", amount=600.00,
        invoice_date="2025-06-02T12:00:00.000Z",
    )
    form = create_form(cast, app["id"])
    attach_item(
        cast, form["id"],
        invoice_id=invoice["id"],
        category="LODGING",
        covered_days=3,
        claimed_amount=600.00,    # < 400 * 3 = 1200 cap
        matched_segment_id=seg["id"],
    )
    submit_form(cast, form["id"])
    # Read the form after submit to confirm requires_special_approval.
    submitted = get_success_data(
        api_client.get_reimbursement_form(form["id"], cast.applicant_headers)
    )
    approved = walk_form_approval_chain(cast, submitted)
    return cast, app, seg, invoice, approved


# ===========================================================================
# Tier 8 — Payment lifecycle
# ===========================================================================
def create_payment_batch(
    cast: ApprovalCast,
    form_ids: List[str],
    channel: str = "BANK_TRANSFER",
) -> Dict[str, Any]:
    """Finance creates a batch payment. Returns the batch envelope."""
    return get_success_data(
        api_client.create_payment_batch(
            payment_batch_payload(form_ids=form_ids, channel=channel),
            cast.finance_headers,
        )
    )


def execute_payment(cast: ApprovalCast, payment_id: str) -> Dict[str, Any]:
    """Finance issues POST /payments/{id}/execute."""
    return get_success_data(
        api_client.execute_payment(payment_id, cast.finance_headers)
    )


def post_payment_outcome(
    cast: ApprovalCast,
    payment_id: str,
    outcome: str = "SUCCESS",
    external_ref: Optional[str] = None,
    failure_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Finance posts the banking-callback simulation outcome."""
    payload = payment_result_payload(
        outcome=outcome,
        external_ref=external_ref,
        failure_reason=failure_reason,
    )
    return get_success_data(
        api_client.post_payment_result(
            payment_id, payload, cast.finance_headers,
        )
    )


def payment_pending(
    *,
    fixture_factory=approved_form_with_one_lodging_item,
    channel: str = "BANK_TRANSFER",
    **factory_kwargs: Any,
) -> Tuple[ApprovalCast, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Approved form + payment batch in PENDING. Returns
    (cast, approved_form, batch_envelope, payment).

    The 'payment' element is the single Payment created for the form.
    """
    cast, _app, _seg, _invoice, approved = fixture_factory(**factory_kwargs)
    batch = create_payment_batch(cast, [approved["id"]], channel=channel)
    # The batch envelope may either be the list directly or contain a
    # list of payments under a known key; both shapes are admitted by
    # PRD §3.9 which only guarantees one Payment per form with a shared
    # batch_id. We discover the payment via /payments?form_id=.
    listing = get_success_data(
        api_client.list_payments(
            cast.finance_headers, params={"form_id": approved["id"]},
        )
    )
    payments = listing if isinstance(listing, list) else listing.get("data", [])
    if not payments:
        # Fall back to validate_paginated, which handles the standard
        # envelope shape directly.
        data, _meta = validate_paginated(
            api_client.list_payments(
                cast.finance_headers, params={"form_id": approved["id"]},
            )
        )
        payments = data
    assert payments, "Setup failed: no Payment created for approved form"
    return cast, approved, batch, payments[0]


def payment_succeeded(
    **kwargs: Any,
) -> Tuple[
    ApprovalCast, Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Walk PENDING → EXECUTING → SUCCESS. Returns
    (cast, form, batch, payment_before_callback, payment_after_success)."""
    cast, form, batch, pending = payment_pending(**kwargs)
    executed = execute_payment(cast, pending["id"])
    success = post_payment_outcome(cast, pending["id"], outcome="SUCCESS")
    return cast, form, batch, executed, success


# ===========================================================================
# Tier 9 — Difficulty-design-driven composites
#
# Each helper below targets the exact prerequisite state described by a
# SCAFFOLD_DIFFICULTY_DESIGN.yaml instance, so the corresponding Stage 2
# test can call ONE helper instead of replaying the recipe inline.
# ===========================================================================

def setup_two_standard_versions_with_dataset_for_dual_variant(
    *,
    tier: str = "TIER_2",
    employee_level: str = "STAFF",
    v1_lodging_cap: float = 400.00,
    v2_lodging_cap: float = 500.00,
    v1_effective_from: str = "2024-12-01T00:00:00.000Z",
    v2_effective_from: str = "2025-06-15T00:00:00.000Z",
) -> Tuple[
    ApprovalCast, Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Difficulty rule 1 / dual_variant_calc instance 1.

    Setup: publish v1 standard → cast → applicant → APPROVED app pinned
    to v1 → book HOTEL → publish v2 standard (auto-closes v1) → upload
    + verify invoice → create form + attach LODGING item.

    Returns (cast, approved_app, segment, invoice, form_draft_with_item)
    so the test can call /budget-projection (uses currently-active v2)
    and then /submit (uses pinned v1) and assert the divergence.
    """
    # Publish v1 (active for application submit)
    publish_expense_standard(
        version=1, city_tier=tier, employee_level=employee_level,
        effective_from=v1_effective_from,
        lodging_daily_cap=v1_lodging_cap,
        per_diem_amount=80.00, transportation_daily_cap=120.00,
    )
    # Build cast + seed eligible options (the env helper would publish a
    # standard again — we publish manually so we own the version
    # numbers, so just create cast and seed options directly here).
    cast = create_approval_cast(applicant_level=employee_level)
    for seg_type in ("FLIGHT", "TRAIN", "HOTEL", "CAR"):
        seed_eligible_option(
            seg_type, employee_level,
            [f"OPT-{seg_type}-001", f"OPT-{seg_type}-002"],
        )

    # APPROVED application — pin v1.
    app = draft_application(
        cast,
        destination_tier=tier,
        travel_scope="DOMESTIC",
        planned_start="2025-06-01T09:00:00.000Z",
        planned_end="2025-06-04T18:00:00.000Z",
        estimated_budget=3_000.00,
    )
    walk_approval_chain(cast, app)

    # Book a HOTEL segment within the planned window (3 nights).
    segment = book_segment(
        cast, app["id"],
        segment_type="HOTEL",
        start_at="2025-06-01T15:00:00.000Z",
        end_at="2025-06-04T11:00:00.000Z",
        cost=1350.00,
    )

    # Publish v2 (auto-closes v1 for this bucket).
    publish_expense_standard(
        version=2, city_tier=tier, employee_level=employee_level,
        effective_from=v2_effective_from,
        lodging_daily_cap=v2_lodging_cap,
        per_diem_amount=80.00, transportation_daily_cap=120.00,
    )

    # Move clock past planned_end so /complete is admissible (covers the
    # complete-before-form-submit path).
    get_success_data(api_client.advance_clock(clock_payload(60 * 60 * 24 * 30), ADMIN))
    get_success_data(
        api_client.complete_travel_application(app["id"], cast.applicant_headers)
    )

    # Upload + verify invoice for the LODGING claim.
    invoice = upload_and_verify_invoice(
        cast, category="LODGING", amount=1350.00,
        invoice_date="2025-06-02T12:00:00.000Z",
    )
    form = create_form(cast, app["id"])
    attach_item(
        cast, form["id"],
        invoice_id=invoice["id"],
        category="LODGING",
        covered_days=3,
        claimed_amount=1350.00,
        matched_segment_id=segment["id"],
    )
    return cast, app, segment, invoice, form


def setup_app_with_first_active_segment(
    *,
    segment_type: str = "FLIGHT",
    cost: float = 500.00,
    estimated_budget: float = 2_000.00,
    seg_start: str = "2025-06-01T10:00:00.000Z",
    seg_end: str = "2025-06-01T13:00:00.000Z",
) -> Tuple[ApprovalCast, Dict[str, Any], Dict[str, Any]]:
    """Difficulty rule 1 / instance 2: APPROVED app + first ACTIVE
    segment so the test can /change the segment and observe
    total_booked_cost recomputation."""
    cast, app = approved_application(estimated_budget=estimated_budget)
    seg = book_segment(
        cast, app["id"], segment_type=segment_type,
        start_at=seg_start, end_at=seg_end, cost=cost,
    )
    return cast, app, seg


# ===========================================================================
# Tier 10 — Concurrency-friendly helpers
# ===========================================================================
def alt_supervisor_for(cast: ApprovalCast) -> Dict[str, Any]:
    """Mint a second Employee row whose role is Supervisor but who is
    NOT the cast.applicant's supervisor. Useful for testing chain-step
    misroute (ERR_NOT_CURRENT_APPROVER)."""
    return create_employee(
        full_name=f"WrongSup-{uuid.uuid4().hex[:6]}",
        employee_level="MANAGER",
    )


def alt_applicant(applicant_level: str = "STAFF") -> Dict[str, Any]:
    """Mint a second applicant Employee row (with a fresh supervisor)
    for ownership-violation tests."""
    sup = create_employee(
        full_name=f"OtherSup-{uuid.uuid4().hex[:6]}",
        employee_level="MANAGER",
    )
    return create_employee(
        full_name=f"OtherApp-{uuid.uuid4().hex[:6]}",
        employee_level=applicant_level,
        supervisor_id=sup["id"],
    )


__all__ = [
    "ADMIN",
    "DEFAULT_PLANNED_START",
    "DEFAULT_PLANNED_END",
    "WIDE_EFFECTIVE_FROM",
    "iso_z",
    "ApprovalCast",
    "create_employee",
    "publish_expense_standard",
    "seed_eligible_option",
    "create_approval_cast",
    "standard_test_environment",
    "draft_application",
    "submit_application",
    "walk_approval_chain",
    "approved_application",
    "book_segment",
    "approved_application_with_segment",
    "upload_and_verify_invoice",
    "create_form",
    "attach_item",
    "submit_form",
    "walk_form_approval_chain",
    "approved_form_with_one_lodging_item",
    "approved_form_no_self_paid",
    "create_payment_batch",
    "execute_payment",
    "post_payment_outcome",
    "payment_pending",
    "payment_succeeded",
    "setup_two_standard_versions_with_dataset_for_dual_variant",
    "setup_app_with_first_active_segment",
    "alt_supervisor_for",
    "alt_applicant",
]
