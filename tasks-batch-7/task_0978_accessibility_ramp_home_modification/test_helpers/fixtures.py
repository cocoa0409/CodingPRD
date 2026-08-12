"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

All helpers use get_success_data() (lenient validator) so setup failures
surface as clear "setup failed" errors rather than confusing assertions.
Every helper builds its preconditions from scratch via PRD §4 endpoints,
because each test starts against an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO
from .factories import (
    create_case_payload, create_assessment_payload, complete_assessment_payload,
    create_quote_payload, create_quote_line_item_payload,
    create_funding_source_payload, approve_funding_payload, create_funding_allocation_payload,
    create_installation_job_payload, create_rental_ramp_payload, create_inventory_unit_payload,
    create_inspection_payload, create_invoice_payload, create_invoice_line_item_payload,
    record_payment_payload, create_warranty_claim_payload,
    create_ot_consultation_payload, create_reassessment_schedule_payload,
)
from .test_users import TEST_USERS

IC = TEST_USERS["intake_coordinator_headers"]
AS = TEST_USERS["assessor_headers"]
PM = TEST_USERS["project_manager_headers"]
FC = TEST_USERS["funding_coordinator_headers"]
CL = TEST_USERS["crew_lead_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
INSP = TEST_USERS["inspector_headers"]
BC = TEST_USERS["billing_coordinator_headers"]
CLIENT = TEST_USERS["client_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
ANY = IC  # any valid user context can read (PRD §2.1 "Any" tier)


# --- Clock (PRD §2.9) ---

def set_clock(iso=CLOCK_START_ISO):
    """Set the logical clock; startup default is 2026-05-01T00:00:00Z."""
    res = api_client.set_clock({"to_iso8601": iso}, ADMIN)
    assert res.status_code == 200, f"clock setup failed: {res.text}"


def get_case(case_id) -> dict:
    return get_success_data(api_client.get_case(case_id, ANY))


def case_version(case_id) -> int:
    return get_case(case_id)["version"]


# --- Tier 1: state progression ---

def create_case(**overrides) -> dict:
    """Create a Case in INTAKE (PRD §3.1)."""
    return get_success_data(api_client.create_case(create_case_payload(**overrides), IC))


def create_case_with_scheduled_assessment(mobility_score=50, hazard_count=1, **case_overrides):
    """Case + one SCHEDULED INITIAL assessment; case is ASSESSMENT_SCHEDULED."""
    case = create_case(**case_overrides)
    asmt = get_success_data(api_client.create_assessment(
        case["id"],
        create_assessment_payload(mobility_score=mobility_score, hazard_count=hazard_count),
        IC,
    ))
    return case, asmt


def create_assessed_case(mobility_score=50, hazard_count=1, recommended=None, **case_overrides):
    """Case with one COMPLETED INITIAL assessment; case is ASSESSED (PRD §3.1)."""
    case, asmt = create_case_with_scheduled_assessment(mobility_score, hazard_count, **case_overrides)
    get_success_data(api_client.start_assessment(case["id"], asmt["id"], AS))
    asmt = get_success_data(api_client.complete_assessment(
        case["id"], asmt["id"],
        complete_assessment_payload(
            mobility_score=mobility_score, hazard_count=hazard_count,
            recommended_modifications=recommended or ["RAMP"],
        ),
        AS,
    ))
    return get_case(case["id"]), asmt


def create_draft_quote(case_id, contingency_pct=None, valid_until="2026-12-31T00:00:00Z") -> dict:
    """Create a DRAFT quote on an ASSESSED case, threading the OCC guard."""
    over = {}
    if contingency_pct is not None:
        over["contingency_pct"] = contingency_pct
    return get_success_data(api_client.create_quote(
        case_id, create_quote_payload(case_version(case_id), valid_until=valid_until, **over), PM,
    ))


def add_quote_line(case_id, quote_id, **line_overrides) -> dict:
    return get_success_data(api_client.add_quote_line_item(
        case_id, quote_id, create_quote_line_item_payload(**line_overrides), PM,
    ))


def setup_case_with_draft_quote(unit_price_cents=10000, quantity=1, line_type="MATERIAL",
                                contingency_pct=0.0, n_lines=1):
    """ASSESSED case + DRAFT quote with n simple lines. Returns (case, quote)."""
    case, _ = create_assessed_case()
    quote = create_draft_quote(case["id"], contingency_pct=contingency_pct)
    for i in range(n_lines):
        add_quote_line(case["id"], quote["id"], line_type=line_type,
                       quantity=quantity, unit_price_cents=unit_price_cents, sort_order=i + 1)
    return get_case(case["id"]), get_success_data(api_client.get_quote(case["id"], quote["id"], ANY))


def submit_quote(case_id, quote_id) -> dict:
    return get_success_data(api_client.submit_quote(case_id, quote_id, PM))


def setup_submitted_quote(unit_price_cents=10000, quantity=1, contingency_pct=0.0):
    """Case QUOTE_SUBMITTED with a SUBMITTED quote. Returns (case, quote)."""
    case, quote = setup_case_with_draft_quote(unit_price_cents, quantity, contingency_pct=contingency_pct)
    return get_case(case["id"]), submit_quote(case["id"], quote["id"])


# --- Tier 2: funding hierarchy ---

def add_funding_source(case_id, requested_cents, priority_rank=1, **overrides) -> dict:
    """Create a PENDING funding source (PRD §3.4)."""
    return get_success_data(api_client.create_funding_source(
        case_id,
        create_funding_source_payload(requested_cents=requested_cents,
                                      priority_rank=priority_rank, **overrides),
        FC,
    ))


def approve_funding(case_id, source_id, approved_cents) -> dict:
    """Approve a PENDING funding source, threading the OCC guard (PRD §3.4)."""
    return get_success_data(api_client.approve_funding_source(
        case_id, source_id,
        approve_funding_payload(approved_cents, case_version(case_id)),
        FC,
    ))


def setup_approved_funding(case_id, approved_cents, priority_rank=1, **overrides) -> dict:
    src = add_funding_source(case_id, requested_cents=approved_cents,
                             priority_rank=priority_rank, **overrides)
    return approve_funding(case_id, src["id"], approved_cents)


def add_allocation(case_id, source_id, quote_id, amount_cents, **overrides) -> dict:
    """Create a PENDING allocation (PRD §3.4)."""
    return get_success_data(api_client.create_funding_allocation(
        case_id, source_id,
        create_funding_allocation_payload(quote_id, amount_cents, **overrides),
        FC,
    ))


def setup_under_review_quote(quote_total=20000, approved_cents=None, allocate=True):
    """Quote UNDER_REVIEW with an APPROVED funding source; optionally a PENDING
    allocation covering min(quote_total, approved_cents). Returns
    (case, quote, source, allocation_or_None)."""
    case, quote = setup_case_with_draft_quote(unit_price_cents=quote_total, contingency_pct=0.0)
    src = setup_approved_funding(case["id"], approved_cents if approved_cents is not None else quote_total)
    submit_quote(case["id"], quote["id"])
    get_success_data(api_client.start_quote_review(case["id"], quote["id"], FC))
    alloc = None
    if allocate:
        alloc = add_allocation(case["id"], src["id"], quote["id"],
                               min(quote_total, src["remaining_cents"]))
    return get_case(case["id"]), get_success_data(api_client.get_quote(case["id"], quote["id"], ANY)), src, alloc


def setup_approved_quote(quote_total=20000, approved_cents=None):
    """Full chain through quote APPROVED: assessment -> quote -> funding ->
    submit -> review -> allocation -> approve (PRD §3.3/§3.4).
    Returns (case, quote, source, allocation)."""
    case, quote, src, alloc = setup_under_review_quote(quote_total, approved_cents, allocate=True)
    quote = get_success_data(api_client.approve_quote(case["id"], quote["id"], FC))
    return get_case(case["id"]), quote, src, alloc


# --- Tier 3: installation lifecycle ---

def setup_installation_job(quote_total=20000, scheduled_start="2026-05-01T00:00:00Z", **job_overrides):
    """Case FUNDING_APPROVED + InstallationJob SCHEDULED (PRD §3.5).
    Returns (case, quote, job, source, allocation)."""
    case, quote, src, alloc = setup_approved_quote(quote_total)
    job = get_success_data(api_client.create_installation_job(
        case["id"],
        create_installation_job_payload(quote["id"], scheduled_start=scheduled_start, **job_overrides),
        PM,
    ))
    return get_case(case["id"]), quote, job, src, alloc


def setup_job_in_progress(quote_total=20000, punch_list=False, **job_overrides):
    """Job walked SCHEDULED -> MATERIALS_ORDERED -> IN_PROGRESS (optionally
    -> PUNCH_LIST). Returns (case, quote, job, source, allocation)."""
    case, quote, job, src, alloc = setup_installation_job(quote_total, **job_overrides)
    get_success_data(api_client.order_materials(case["id"], job["id"], PM))
    job = get_success_data(api_client.start_installation(case["id"], job["id"], CL))
    if punch_list:
        job = get_success_data(api_client.enter_punch_list(case["id"], job["id"], CL))
    return get_case(case["id"]), quote, job, src, alloc


def setup_completed_job(quote_total=20000, **job_overrides):
    """Job COMPLETED; case INSTALLED; POST_INSTALL reassessment auto-created
    (PRD §3.5/§3.9). Returns (case, quote, job, source, allocation)."""
    case, quote, job, src, alloc = setup_job_in_progress(quote_total, punch_list=True, **job_overrides)
    job = get_success_data(api_client.complete_installation(case["id"], job["id"], CL))
    return get_case(case["id"]), quote, job, src, alloc


# --- Tier 2 (rental): inventory + rental hierarchy ---

def create_inventory_unit(**overrides) -> dict:
    """Create an AVAILABLE inventory unit (PRD §3.6)."""
    return get_success_data(api_client.create_inventory_unit(
        create_inventory_unit_payload(**overrides), LC,
    ))


def setup_rental(rental_start="2026-05-01T00:00:00Z", rental_end="2026-06-01T00:00:00Z",
                 unit_overrides=None, case=None):
    """AVAILABLE unit + INTAKE case + RESERVED rental ramp (PRD §3.6).
    Returns (case, unit, ramp)."""
    unit = create_inventory_unit(**(unit_overrides or {}))
    if case is None:
        case = create_case()
    ramp = get_success_data(api_client.create_rental_ramp(
        case["id"], create_rental_ramp_payload(unit["id"], rental_start=rental_start,
                                               rental_end=rental_end), LC,
    ))
    return get_case(case["id"]), unit, ramp


def setup_installed_rental(**kwargs):
    """Rental walked RESERVED -> DELIVERED -> INSTALLED (PRD §3.6).
    Returns (case, unit, ramp)."""
    case, unit, ramp = setup_rental(**kwargs)
    ramp = get_success_data(api_client.deliver_rental_ramp(case["id"], ramp["id"], LC))
    ramp = get_success_data(api_client.install_rental_ramp(case["id"], ramp["id"], CL))
    return case, unit, ramp


def setup_pickup_scheduled_rental(**kwargs):
    """Rental walked to PICKUP_SCHEDULED; unit DEPLOYED (PRD §3.6).
    Returns (case, unit, ramp)."""
    case, unit, ramp = setup_installed_rental(**kwargs)
    ramp = get_success_data(api_client.schedule_pickup(case["id"], ramp["id"], LC))
    return case, unit, ramp


# --- Tier 3 (billing): invoice lifecycle ---

def create_draft_invoice(case_id, invoice_type="SERVICE_CALL", due_date="2026-06-01T00:00:00Z",
                         **overrides) -> dict:
    """Create a DRAFT invoice, threading the OCC guard (PRD §3.7)."""
    return get_success_data(api_client.create_invoice(
        case_id,
        create_invoice_payload(case_version(case_id), invoice_type=invoice_type,
                               due_date=due_date, **overrides),
        BC,
    ))


def add_invoice_line(case_id, invoice_id, **line_overrides) -> dict:
    return get_success_data(api_client.add_invoice_line_item(
        case_id, invoice_id, create_invoice_line_item_payload(**line_overrides), BC,
    ))


def setup_draft_invoice(unit_price_cents=1000, quantity=1, tax_rate_pct=0.0, **invoice_overrides):
    """INTAKE case + DRAFT invoice with one line. Returns (case, invoice)."""
    case = create_case()
    inv = create_draft_invoice(case["id"], **invoice_overrides)
    add_invoice_line(case["id"], inv["id"], unit_price_cents=unit_price_cents,
                     quantity=quantity, tax_rate_pct=tax_rate_pct)
    return get_case(case["id"]), get_success_data(api_client.get_invoice(case["id"], inv["id"], ANY))


def send_invoice(case_id, invoice_id) -> dict:
    """Send a DRAFT invoice, threading the OCC guard (PRD §3.7)."""
    return get_success_data(api_client.send_invoice(
        case_id, invoice_id, {"expected_case_version": case_version(case_id)}, BC,
    ))


def setup_sent_invoice(unit_price_cents=1000, quantity=1, tax_rate_pct=0.0, **invoice_overrides):
    """Case + SENT invoice. Returns (case, invoice)."""
    case, inv = setup_draft_invoice(unit_price_cents, quantity, tax_rate_pct, **invoice_overrides)
    return get_case(case["id"]), send_invoice(case["id"], inv["id"])


def record_payment(case_id, invoice_id, amount_cents) -> dict:
    return get_success_data(api_client.record_payment(
        case_id, invoice_id, record_payment_payload(amount_cents), BC,
    ))


# --- Collaboration / follow-up helpers ---

def create_ot_consultation(case_id, **overrides) -> dict:
    return get_success_data(api_client.create_ot_consultation(
        case_id, create_ot_consultation_payload(**overrides), IC,
    ))


def create_reassessment_schedule(case_id, **overrides) -> dict:
    return get_success_data(api_client.create_reassessment_schedule(
        case_id, create_reassessment_schedule_payload(**overrides), IC,
    ))


def create_warranty_claim(case_id, installation_job_id, **overrides) -> dict:
    return get_success_data(api_client.create_warranty_claim(
        case_id, create_warranty_claim_payload(installation_job_id, **overrides), CLIENT,
    ))
