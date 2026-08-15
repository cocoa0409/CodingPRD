"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the server is restarted before each test, so no state is shared). Setup calls
use get_success_data() so failures surface as clear "Setup failed" errors.

Standard fixture legend (defaults): blanks 900x600 cin, rotation allowed,
coat finish, ink slots ["BRAND_RED"], substrate SBS18/18pt; press sheet
4800x3600 g30 e60 gr90 -> ups 25; qty 3000 -> net 120, OFFSET gross 130;
board stock 5000 sheets @300c.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    create_board_stock_payload,
    create_color_standard_payload,
    create_customer_payload,
    create_design_revision_payload,
    create_finishing_booking_payload,
    create_finishing_line_payload,
    create_imposition_plan_payload,
    create_invoice_payload,
    create_job_payload,
    create_kit_order_payload,
    create_press_approval_payload,
    create_press_booking_payload,
    create_press_payload,
    create_retail_audit_payload,
)
from .test_users import TEST_USERS, make_brand_quality_headers

ADMIN = TEST_USERS["plant_admin_headers"]
DESIGNER = TEST_USERS["structural_designer_headers"]
OPERATOR = TEST_USERS["press_operator_headers"]
FINISHER = TEST_USERS["finishing_operator_headers"]
KITTER = TEST_USERS["kitting_lead_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]

# Non-touching finishing windows per operation (closed padded semantics make
# touching endpoints conflict, so consecutive ops are separated by gaps).
FINISH_WINDOWS = {
    "COAT": ("2026-08-11T08:00:00Z", "2026-08-11T09:00:00Z"),
    "FOIL": ("2026-08-11T09:30:00Z", "2026-08-11T10:30:00Z"),
    "EMBOSS": ("2026-08-11T11:00:00Z", "2026-08-11T12:00:00Z"),
}


# ─── Tier 1: master data ──────────────────────────────

def create_customer(name="Acme", brand_code="ACM"):
    res = api_client.create_customer(
        create_customer_payload(name=name, brand_code=brand_code), ADMIN
    )
    return get_success_data(res)


def create_active_color_standard(customer_id, ink_slot=C.FIXTURE_INK_SLOT,
                                 tolerance=C.FIXTURE_TOLERANCE_DELTA_E_MILLI,
                                 **overrides):
    """Create -> submit -> brand-approve. Returns the ACTIVE standard."""
    std = get_success_data(api_client.create_color_standard(
        create_color_standard_payload(
            customer_id, ink_slot=ink_slot, tolerance_delta_e_milli=tolerance,
            **overrides),
        ADMIN,
    ))
    get_success_data(api_client.submit_color_standard(std["id"], ADMIN))
    return get_success_data(
        api_client.approve_color_standard(
            std["id"], make_brand_quality_headers(customer_id))
    )


def create_board_stock(received_sheets=C.FIXTURE_STOCK_SHEETS,
                       unit_cost_cents=C.FIXTURE_STOCK_UNIT_COST_CENTS,
                       **overrides):
    res = api_client.create_board_stock(
        create_board_stock_payload(
            received_sheets=received_sheets, unit_cost_cents=unit_cost_cents,
            **overrides),
        ADMIN,
    )
    return get_success_data(res)


def create_press(**overrides):
    return get_success_data(api_client.create_press(create_press_payload(**overrides),
                                                    ADMIN))


def create_finishing_line(**overrides):
    return get_success_data(
        api_client.create_finishing_line(create_finishing_line_payload(**overrides),
                                         ADMIN))


# ─── Tier 2: job intake and engineering ───────────────

def create_job(customer_id, **overrides):
    """Create a QUOTED job. route_type and the provisional quote are computed
    by the server at creation."""
    return get_success_data(
        api_client.create_job(create_job_payload(customer_id, **overrides), ADMIN))


def start_engineering(job_id):
    return get_success_data(api_client.start_engineering(job_id, ADMIN))


def get_job(job_id):
    return get_success_data(api_client.get_job(job_id, ADMIN))


def create_brand_approved_revision(job_id, customer_id, **overrides):
    """Create a design revision (OCC-guarded), make the sample, and obtain
    brand acceptance. Returns the BRAND_APPROVED revision."""
    job = get_job(job_id)
    rev = get_success_data(api_client.create_design_revision(
        create_design_revision_payload(job_id, job["version"], **overrides),
        DESIGNER,
    ))
    get_success_data(api_client.make_sample(rev["id"], DESIGNER))
    return get_success_data(api_client.brand_accept_revision(
        rev["id"], make_brand_quality_headers(customer_id)))


def create_draft_plan(job_id, revision_id, **overrides):
    return get_success_data(api_client.create_imposition_plan(
        create_imposition_plan_payload(job_id, revision_id, **overrides),
        DESIGNER,
    ))


def lock_plan(plan_id, job_id):
    """Lock a DRAFT plan with a fresh OCC read of the owning job's version."""
    job = get_job(job_id)
    return get_success_data(api_client.lock_imposition_plan(
        plan_id, {"expected_job_version": job["version"]}, DESIGNER
    ))


def create_locked_plan(job_id, revision_id, **overrides):
    plan = create_draft_plan(job_id, revision_id, **overrides)
    return lock_plan(plan["id"], job_id)


# ─── Tier 3: lifecycle shortcuts ──────────────────────

def setup_engineering_job(customer_name="Acme", brand_code="ACM",
                          standard=True, stock=True, **job_overrides):
    """Customer (+ ACTIVE color standard, + board stock) and a job in
    ENGINEERING. Returns a context dict."""
    ctx = {}
    ctx["customer"] = create_customer(name=customer_name, brand_code=brand_code)
    cust_id = ctx["customer"]["id"]
    if standard:
        ctx["standard"] = create_active_color_standard(cust_id)
    if stock:
        ctx["stock"] = create_board_stock()
    job = create_job(cust_id, **job_overrides)
    ctx["job"] = start_engineering(job["id"])
    return ctx


def setup_lock_ready_job(customer_name="Acme", brand_code="ACM",
                         standard=True, stock=True,
                         stock_sheets=C.FIXTURE_STOCK_SHEETS,
                         stock_unit_cost=C.FIXTURE_STOCK_UNIT_COST_CENTS,
                         **job_overrides):
    """Job in ENGINEERING with a BRAND_APPROVED revision and a LOCKED plan —
    everything mark-press-ready needs, but the transition itself not yet
    attempted. Context carries customer/standard/stock/job/revision/plan."""
    ctx = {}
    ctx["customer"] = create_customer(name=customer_name, brand_code=brand_code)
    cust_id = ctx["customer"]["id"]
    if standard:
        ctx["standard"] = create_active_color_standard(cust_id)
    if stock:
        ctx["stock"] = create_board_stock(received_sheets=stock_sheets,
                                          unit_cost_cents=stock_unit_cost)
    job = create_job(cust_id, **job_overrides)
    job = start_engineering(job["id"])
    ctx["revision"] = create_brand_approved_revision(job["id"], cust_id)
    ctx["plan"] = create_locked_plan(job["id"], ctx["revision"]["id"])
    ctx["job"] = get_job(job["id"])
    return ctx


def setup_press_ready_job(customer_name="Acme", brand_code="ACM",
                          standard=True, stock=True,
                          stock_sheets=C.FIXTURE_STOCK_SHEETS,
                          stock_unit_cost=C.FIXTURE_STOCK_UNIT_COST_CENTS,
                          **job_overrides):
    """Job driven ENGINEERING -> PRESS_READY: brand-approved revision, locked
    plan, mark-press-ready (board reservation taken). Context carries
    customer/standard/stock/job/revision/plan."""
    ctx = setup_lock_ready_job(
        customer_name=customer_name, brand_code=brand_code, standard=standard,
        stock=stock, stock_sheets=stock_sheets, stock_unit_cost=stock_unit_cost,
        **job_overrides,
    )
    ctx["job"] = get_success_data(
        api_client.mark_press_ready(ctx["job"]["id"], DESIGNER))
    return ctx


def create_approved_press_approval(ctx, measured_delta_e_milli=100):
    """Submit a press approval for the job's fixture ink slot and approve it."""
    appr = get_success_data(api_client.create_press_approval(
        create_press_approval_payload(
            ctx["job"]["id"], ctx["standard"]["id"],
            measured_delta_e_milli=measured_delta_e_milli),
        OPERATOR,
    ))
    return get_success_data(api_client.approve_press_approval(
        appr["id"], make_brand_quality_headers(ctx["customer"]["id"])))


def create_booked_press_window(ctx, **overrides):
    """Create a press and one SCHEDULED booking on it for the job."""
    ctx.setdefault("press", create_press())
    ctx["booking"] = get_success_data(api_client.create_press_booking(
        create_press_booking_payload(ctx["job"]["id"], ctx["press"]["id"],
                                     **overrides),
        OPERATOR,
    ))
    return ctx["booking"]


def setup_in_production_job(**kwargs):
    """PRESS_READY job + approved press approval + SCHEDULED booking, then
    start-production. Context adds press/booking/approval."""
    ctx = setup_press_ready_job(**kwargs)
    create_approved_press_approval(ctx)
    create_booked_press_window(ctx)
    ctx["job"] = get_success_data(api_client.start_production(ctx["job"]["id"],
                                                              OPERATOR))
    return ctx


def complete_press_booking(ctx, sheets_printed, sheets_good):
    """Complete the job's booking and finish the press stage."""
    get_success_data(api_client.complete_press_booking(
        ctx["booking"]["id"],
        {"sheets_printed": sheets_printed, "sheets_good": sheets_good},
        OPERATOR,
    ))
    ctx["job"] = get_success_data(api_client.complete_press(ctx["job"]["id"],
                                                            OPERATOR))
    return ctx["job"]


def run_finishing_stage(ctx, operations=None, buffer_minutes=0):
    """Book and complete one finishing booking per flagged operation, then
    complete the finishing stage (job -> FINISHED)."""
    if operations is None:
        operations = []
        if ctx["job"].get("finish_coat"):
            operations.append("COAT")
        if ctx["job"].get("finish_foil"):
            operations.append("FOIL")
        if ctx["job"].get("finish_emboss"):
            operations.append("EMBOSS")
    ctx["finish_bookings"] = []
    if operations:
        ctx["line"] = create_finishing_line(supported_ops=list(operations),
                                            setup_buffer_minutes=buffer_minutes)
        for op in operations:
            start, end = FINISH_WINDOWS[op]
            fb = get_success_data(api_client.create_finishing_booking(
                create_finishing_booking_payload(
                    ctx["job"]["id"], ctx["line"]["id"], op,
                    start_utc=start, end_utc=end),
                FINISHER,
            ))
            get_success_data(api_client.complete_finishing_booking(fb["id"],
                                                                   FINISHER))
            ctx["finish_bookings"].append(fb)
    ctx["job"] = get_success_data(api_client.complete_finishing(ctx["job"]["id"],
                                                                FINISHER))
    return ctx["job"]


def setup_finished_job(sheets_printed=130, sheets_good=120, **kwargs):
    """Full production path: IN_PRODUCTION -> booking completed -> FINISHING ->
    all flagged operations COMPLETED -> FINISHED. Default actuals: 130 printed
    / 120 good sheets -> 3000 good cartons at ups 25."""
    ctx = setup_in_production_job(**kwargs)
    complete_press_booking(ctx, sheets_printed, sheets_good)
    run_finishing_stage(ctx)
    ctx["job"] = get_job(ctx["job"]["id"])
    return ctx


# ─── Tier 4: kitting, audits, invoices ────────────────

def create_kit_order(job_id, **overrides):
    return get_success_data(
        api_client.create_kit_order(create_kit_order_payload(job_id, **overrides),
                                    KITTER))


def create_certified_audit(ctx, **overrides):
    """Create a COMPLIANT audit, submit it, and have the brand certify it."""
    aud = get_success_data(api_client.create_retail_audit(
        create_retail_audit_payload(ctx["job"]["id"], **overrides), KITTER))
    get_success_data(api_client.submit_retail_audit(aud["id"], KITTER))
    return get_success_data(api_client.certify_retail_audit(
        aud["id"], make_brand_quality_headers(ctx["customer"]["id"])))


def setup_complete_job(certify_audit=False, **kwargs):
    """FINISHED job -> COMPLETE (optionally with a CERTIFIED retail audit)."""
    ctx = setup_finished_job(**kwargs)
    if certify_audit:
        ctx["audit"] = create_certified_audit(ctx)
    ctx["job"] = get_success_data(api_client.complete_job(ctx["job"]["id"], ADMIN))
    return ctx


def create_draft_invoice(job_id):
    return get_success_data(
        api_client.create_invoice(create_invoice_payload(job_id), CLERK))


# ─── Tier 5: settlement-targeting fixture ─────────────

def setup_settlement_job(quantity_ordered, finishes, sheets_printed,
                         sheets_good, kit=None, stock_sheets=5000,
                         stock_unit_cost=300):
    """Drive a job all the way to COMPLETE with controlled actuals, and open a
    DRAFT invoice. `finishes` is a list of operations to flag and complete;
    `kit` is an optional dict {units_per_kit, kits_planned, kits_completed,
    labor_minutes_actual} that is started and completed before job completion.
    Returns (ctx, invoice)."""
    job_flags = {
        "finish_coat": "COAT" in finishes,
        "finish_foil": "FOIL" in finishes,
        "finish_emboss": "EMBOSS" in finishes,
    }
    ctx = setup_in_production_job(
        quantity_ordered=quantity_ordered,
        stock_sheets=stock_sheets,
        stock_unit_cost=stock_unit_cost,
        **job_flags,
    )
    return _finish_settlement(ctx, sheets_printed, sheets_good, kit)


def _finish_settlement(ctx, sheets_printed, sheets_good, kit):
    complete_press_booking(ctx, sheets_printed, sheets_good)
    run_finishing_stage(ctx)
    if kit is not None:
        k = create_kit_order(
            ctx["job"]["id"],
            components=[{"description": "carton",
                         "units_per_kit": kit["units_per_kit"]}],
            kits_planned=kit["kits_planned"],
        )
        get_success_data(api_client.start_kit_order(k["id"], KITTER))
        ctx["kit"] = get_success_data(api_client.complete_kit_order(
            k["id"],
            {"kits_completed": kit["kits_completed"],
             "labor_minutes_actual": kit["labor_minutes_actual"]},
            KITTER,
        ))
    ctx["job"] = get_success_data(api_client.complete_job(ctx["job"]["id"], ADMIN))
    invoice = create_draft_invoice(ctx["job"]["id"])
    return ctx, invoice
