"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server). Setup calls use
the lenient get_success_data() validator so a setup failure surfaces as a clear
"Setup step failed" error naming the step, not a confusing assertion failure.

Scenario ctx dicts carry: customer, design, quote, job, milestones (list of
six, seq order), tool, and optionally sample / press_reservation.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    assess_engineering_change_payload,
    create_build_job_payload,
    create_customer_payload,
    create_engineering_change_payload,
    create_machine_reservation_payload,
    create_press_reservation_payload,
    create_quote_payload,
    create_shot_report_payload,
    create_spare_insert_payload,
    create_tool_design_payload,
    create_tryout_sample_payload,
    create_warranty_claim_payload,
    record_payment_payload,
    ship_tool_asset_payload,
    submit_tryout_sample_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["shop_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
ENGINEER = TEST_USERS["tooling_engineer_headers"]
PM = TEST_USERS["project_manager_headers"]
QM = TEST_USERS["quality_manager_headers"]
FIN_ISSUER = TEST_USERS["finance_issuer_headers"]
FIN_PAYER = TEST_USERS["finance_payer_headers"]

MACHINE_WINDOW = ("2026-08-03T08:00:00Z", "2026-08-03T16:00:00Z")
PRESS_WINDOW = ("2026-08-10T08:00:00Z", "2026-08-10T16:00:00Z")
INSIDE_PRESS_WINDOW = "2026-08-10T10:00:00Z"
AFTER_PRESS_WINDOW = "2026-08-25T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN))


def create_customer(company_name="Acme Plastics", credit_limit_cents=0, **overrides):
    payload = create_customer_payload(
        company_name=company_name, credit_limit_cents=credit_limit_cents, **overrides
    )
    return get_success_data(api_client.create_customer(payload, ADMIN))


def create_design(customer_id: str, **overrides):
    """New tool design in DRAFT, created by its owning customer (PRD §3.2)."""
    payload = create_tool_design_payload(customer_id, **overrides)
    return get_success_data(
        api_client.create_tool_design(payload, make_customer_headers(customer_id))
    )


def submit_design(design_id: str, customer_id: str):
    return get_success_data(
        api_client.submit_tool_design(design_id, make_customer_headers(customer_id))
    )


def review_design(design_id: str, decision: str, review_note=None):
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(api_client.review_tool_design(design_id, payload, ENGINEER))


def create_released_design(customer_id: str, **overrides):
    """DRAFT -> SUBMITTED -> RELEASED. Returns the released design dict."""
    design = create_design(customer_id, **overrides)
    submit_design(design["id"], customer_id)
    return review_design(design["id"], "RELEASED")


def get_design_version(design_id: str) -> int:
    return get_success_data(api_client.get_tool_design(design_id, ADMIN))["version"]


def get_job_version(job_id: str) -> int:
    return get_success_data(api_client.get_build_job(job_id, ADMIN))["version"]


def create_quote(customer_id: str, design_id: str, **overrides):
    """Create a DRAFT quote; reads the design's current version for the OCC
    field expected_tool_design_version (PRD §2.5)."""
    version = get_design_version(design_id)
    payload = create_quote_payload(customer_id, design_id, version, **overrides)
    return get_success_data(api_client.create_quote(payload, ESTIMATOR))


def issue_quote(quote_id: str):
    return get_success_data(api_client.issue_quote(quote_id, ESTIMATOR))


def respond_quote(quote_id: str, decision: str, customer_id: str):
    return get_success_data(
        api_client.respond_quote(quote_id, {"decision": decision}, make_customer_headers(customer_id))
    )


def create_accepted_quote(customer_id: str, design_id: str, **overrides):
    """DRAFT quote -> ISSUED -> ACCEPTED. Returns the accepted quote dict."""
    quote = create_quote(customer_id, design_id, **overrides)
    issue_quote(quote["id"])
    return respond_quote(quote["id"], "ACCEPTED", customer_id)


# ---------------------------------------------------------------------------
# Tier 2: job hierarchy (job + six milestones + one tool)
# ---------------------------------------------------------------------------
def create_build_job_for_quote(quote_id: str):
    return get_success_data(
        api_client.create_build_job(create_build_job_payload(quote_id), PM)
    )


def list_job_milestones(job_id: str):
    """The job's six milestones in seq order (list sorts by seq within a job)."""
    data = get_success_data(
        api_client.list_build_milestones(ADMIN, params={"build_job_id": job_id, "limit": 100})
    )
    if len(data) != 6:
        raise AssertionError(f"Setup step failed: expected 6 milestones, got {len(data)}")
    return data


def get_job_tool(job_id: str):
    data = get_success_data(
        api_client.list_tool_assets(ADMIN, params={"build_job_id": job_id, "limit": 100})
    )
    if len(data) != 1:
        raise AssertionError(f"Setup step failed: expected 1 tool asset, got {len(data)}")
    return data[0]


def refresh_job(ctx: dict):
    ctx["job"] = get_success_data(api_client.get_build_job(ctx["job"]["id"], ADMIN))
    return ctx["job"]


def refresh_tool(ctx: dict):
    ctx["tool"] = get_success_data(api_client.get_tool_asset(ctx["tool"]["id"], ADMIN))
    return ctx["tool"]


def refresh_milestones(ctx: dict):
    ctx["milestones"] = list_job_milestones(ctx["job"]["id"])
    return ctx["milestones"]


def setup_booked_job(company_name="Acme Plastics", part_number="PN-1001",
                     warranty_terms=None, die_class="CLASS_103", cavity_count=4,
                     design_complexity_score=10, requested_lead_weeks=12,
                     quote_kind="FIRM", expedited=False):
    """Customer + RELEASED design + ACCEPTED quote + BOOKED build job.

    Returns ctx with customer, design, quote, job, milestones, tool.
    """
    customer = create_customer(company_name=company_name)
    design = create_released_design(
        customer["id"], part_number=part_number, die_class=die_class,
        cavity_count=cavity_count, design_complexity_score=design_complexity_score,
    )
    quote_overrides = {"quote_kind": quote_kind, "requested_lead_weeks": requested_lead_weeks}
    if expedited:
        quote_overrides["expedited"] = True
    if warranty_terms is not None:
        quote_overrides["warranty_terms"] = warranty_terms
    quote = create_accepted_quote(customer["id"], design["id"], **quote_overrides)
    job = create_build_job_for_quote(quote["id"])
    milestones = list_job_milestones(job["id"])
    tool = get_job_tool(job["id"])
    return {
        "customer": customer, "design": design, "quote": quote,
        "job": job, "milestones": milestones, "tool": tool,
    }


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------
def reserve_machine_block(job_id: str, machine_id="CNC_1", start=MACHINE_WINDOW[0],
                          end=MACHINE_WINDOW[1]):
    payload = create_machine_reservation_payload(
        job_id, machine_id=machine_id, start_time=start, end_time=end
    )
    return get_success_data(api_client.create_machine_reservation(payload, PM))


def advance_job(job_id: str, target_state: str):
    return get_success_data(
        api_client.advance_build_job(job_id, {"target_state": target_state}, PM)
    )


def start_build(job_id: str, machine_id="CNC_1", machine_window=None):
    """BOOKED -> IN_BUILD with the required RESERVED machine block.
    machine_window=(start, end) overrides the default window for tests whose
    logical clock has already advanced past it (PRD §2.9 start>=now)."""
    start, end = machine_window or MACHINE_WINDOW
    reservation = reserve_machine_block(job_id, machine_id=machine_id, start=start, end=end)
    job = advance_job(job_id, "IN_BUILD")
    return job, reservation


def reserve_press_window(job_id: str, press_id="PRESS_500T", start=PRESS_WINDOW[0],
                         end=PRESS_WINDOW[1]):
    payload = create_press_reservation_payload(
        job_id, press_id=press_id, start_time=start, end_time=end
    )
    return get_success_data(api_client.create_press_reservation(payload, PM))


def schedule_tryout_round(job_id: str, press_id="PRESS_500T", press_window=None):
    """Press window + tryout sample; first sample moves the job to
    TRYOUT_PHASE (PRD §3.6). Returns (press_reservation, sample).
    press_window=(start, end) overrides the default window for tests whose
    logical clock has already advanced past it (PRD §2.9 start>=now)."""
    press = reserve_press_window(job_id, press_id=press_id,
                                 start=(press_window or PRESS_WINDOW)[0],
                                 end=(press_window or PRESS_WINDOW)[1])
    sample = get_success_data(
        api_client.create_tryout_sample(
            create_tryout_sample_payload(job_id, press["id"]), PM
        )
    )
    return press, sample


def submit_tryout_round(sample_id: str, sample_qty=30, shots_used=500,
                        measured_report_ref="LAY-1", clock_time=INSIDE_PRESS_WINDOW):
    """Move the logical clock inside the press window, then submit.
    clock_time overrides the in-window instant for tests running a second
    scenario after the clock has advanced past the default window (PRD §2.4:
    the clock never moves backward)."""
    set_clock(clock_time)
    return get_success_data(
        api_client.submit_tryout_sample(
            sample_id,
            submit_tryout_sample_payload(
                sample_qty=sample_qty, shots_used=shots_used,
                measured_report_ref=measured_report_ref,
            ),
            PM,
        )
    )


def buyoff_tryout_round(sample_id: str, decision="BOUGHT_OFF", defect_codes=None):
    payload = {"decision": decision}
    if defect_codes is not None:
        payload["defect_codes"] = defect_codes
    return get_success_data(api_client.buyoff_decision(sample_id, payload, QM))


def complete_milestones_seq(milestones, customer_id: str, seqs=(1, 2, 3, 4, 5)):
    """Complete the given seqs in order. Seq 5 is the owning customer's
    signature; all others are ProjectManager actions (PRD §3.5)."""
    completed = {}
    for seq in seqs:
        milestone = milestones[seq - 1]
        headers = make_customer_headers(customer_id) if seq == 5 else PM
        completed[seq] = get_success_data(
            api_client.complete_milestone(milestone["id"], {}, headers)
        )
    return completed


def invoice_milestones_seq(milestones, seqs=(1, 2, 3, 4), issuer_headers=None):
    """Issue progress invoices for EARNED milestones. Invoices are issued by
    the fin-a FinanceAdmin identity so payments recorded by fin-b stay
    segregation-of-duties clean."""
    issuer = issuer_headers or FIN_ISSUER
    invoices = {}
    for seq in seqs:
        invoices[seq] = get_success_data(
            api_client.invoice_milestone(milestones[seq - 1]["id"], issuer)
        )
    return invoices


def record_job_payment(job_id: str, amount_cents: int, payer_headers=None):
    """OCC-guarded payment: reads the job's current version first (PRD §2.5)."""
    payer = payer_headers or FIN_PAYER
    version = get_job_version(job_id)
    return get_success_data(
        api_client.record_payment(
            job_id, record_payment_payload(amount_cents, version), payer
        )
    )


def ship_tool(tool_id: str, carrier="OLD DOMINION", tracking_number="TRK-1"):
    return get_success_data(
        api_client.ship_tool_asset(
            tool_id,
            ship_tool_asset_payload(carrier=carrier, tracking_number=tracking_number),
            PM,
        )
    )


def deliver_tool(tool_id: str):
    return get_success_data(api_client.deliver_tool_asset(tool_id, PM))


def file_eco(job_id: str, requested_by="SHOP", affects_from_milestone_seq=4,
             description="add lifters", customer_id=None):
    """File an engineering change (SUBMITTED); reads the job version for OCC.
    SHOP filings come from a ToolingEngineer, CUSTOMER filings from the owning
    customer (PRD §3.7)."""
    version = get_job_version(job_id)
    payload = create_engineering_change_payload(
        job_id, version,
        requested_by=requested_by,
        description=description,
        affects_from_milestone_seq=affects_from_milestone_seq,
    )
    headers = ENGINEER if requested_by == "SHOP" else make_customer_headers(customer_id)
    return get_success_data(api_client.create_engineering_change(payload, headers))


def assess_eco(eco_id: str, rework_hours=4.0, scrapped_material_cost_cents=50000,
               lead_extension_weeks=1):
    return get_success_data(
        api_client.assess_engineering_change(
            eco_id,
            assess_engineering_change_payload(
                rework_hours=rework_hours,
                scrapped_material_cost_cents=scrapped_material_cost_cents,
                lead_extension_weeks=lead_extension_weeks,
            ),
            ENGINEER,
        )
    )


def approve_eco(eco_id: str, customer_id: str):
    return get_success_data(
        api_client.customer_decision_engineering_change(
            eco_id, {"decision": "APPROVED"}, make_customer_headers(customer_id)
        )
    )


def file_shot_report(tool_id: str, customer_id: str, report_period_end: str,
                     shots_in_period: int):
    return get_success_data(
        api_client.create_shot_report(
            create_shot_report_payload(
                tool_id, report_period_end=report_period_end,
                shots_in_period=shots_in_period,
            ),
            make_customer_headers(customer_id),
        )
    )


def file_warranty_claim(tool_id: str, customer_id: str, estimated_repair_cost_cents=500000,
                        defect_description="cracked cavity block"):
    return api_client.create_warranty_claim(
        create_warranty_claim_payload(
            tool_id, defect_description=defect_description,
            estimated_repair_cost_cents=estimated_repair_cost_cents,
        ),
        make_customer_headers(customer_id),
    )


def create_spare(tool_id: str, insert_code="INS-CAV-01", unit_cost_cents=45000,
                 initial_on_hand=5, reorder_point=2):
    return get_success_data(
        api_client.create_spare_insert(
            create_spare_insert_payload(
                tool_id, insert_code=insert_code, unit_cost_cents=unit_cost_cents,
                initial_on_hand=initial_on_hand, reorder_point=reorder_point,
            ),
            PM,
        )
    )


# ---------------------------------------------------------------------------
# Tier 5: full-lifecycle drives
# ---------------------------------------------------------------------------
def drive_job_to_buyoff_passed(ctx: dict, press_id="PRESS_500T", machine_id="CNC_1",
                               tryout_shots=500, machine_window=None,
                               press_window=None, submit_clock=INSIDE_PRESS_WINDOW):
    """BOOKED -> IN_BUILD -> TRYOUT_PHASE -> BUYOFF_PASSED, then milestones
    1..5 EARNED. Extends ctx with machine_reservation, press_reservation,
    sample. Tool ends AWAITING_SHIPMENT with the warranty clock started."""
    job_id = ctx["job"]["id"]
    customer_id = ctx["customer"]["id"]
    _, machine_res = start_build(job_id, machine_id=machine_id,
                                 machine_window=machine_window)
    press, sample = schedule_tryout_round(job_id, press_id=press_id,
                                          press_window=press_window)
    submit_tryout_round(sample["id"], shots_used=tryout_shots,
                        clock_time=submit_clock)
    sample = buyoff_tryout_round(sample["id"], "BOUGHT_OFF")
    complete_milestones_seq(ctx["milestones"], customer_id, seqs=(1, 2, 3, 4, 5))
    ctx.update({
        "machine_reservation": machine_res,
        "press_reservation": press,
        "sample": sample,
    })
    refresh_job(ctx)
    refresh_tool(ctx)
    refresh_milestones(ctx)
    return ctx


def drive_job_to_ready_to_ship(ctx: dict, pay_amount=8_925_000, invoice_seqs=(1, 2, 3, 4),
                               press_id="PRESS_500T", machine_id="CNC_1",
                               tryout_shots=500, machine_window=None,
                               press_window=None, submit_clock=INSIDE_PRESS_WINDOW):
    """BUYOFF_PASSED plus invoicing/payment, then advance to READY_TO_SHIP.

    Default payment covers milestones 1-4 in full (8,925,000 on the standard
    10,500,000 contract), leaving outstanding exactly at the fifteen-percent
    lien threshold so shipping is permitted. Extends ctx with invoices and
    payment."""
    drive_job_to_buyoff_passed(ctx, press_id=press_id, machine_id=machine_id,
                               tryout_shots=tryout_shots,
                               machine_window=machine_window,
                               press_window=press_window,
                               submit_clock=submit_clock)
    job_id = ctx["job"]["id"]
    invoices = invoice_milestones_seq(ctx["milestones"], seqs=invoice_seqs)
    payment = None
    if pay_amount:
        payment = record_job_payment(job_id, pay_amount)
    advance_job(job_id, "READY_TO_SHIP")
    ctx.update({"invoices": invoices, "payment": payment})
    refresh_job(ctx)
    refresh_milestones(ctx)
    return ctx


def setup_tool_in_production(company_name="Acme Plastics", part_number="PN-1001",
                             warranty_terms=None, press_id="PRESS_500T",
                             machine_id="CNC_1", tryout_shots=500,
                             tracking_number="TRK-1", machine_window=None,
                             press_window=None, submit_clock=INSIDE_PRESS_WINDOW):
    """Full drive: BOOKED job through buyoff, invoicing, payment,
    READY_TO_SHIP, ship and deliver. Tool ends IN_PRODUCTION with ownership
    still SHOP_RETAINED (only milestones 1-4 are paid)."""
    ctx = setup_booked_job(
        company_name=company_name, part_number=part_number,
        warranty_terms=warranty_terms,
    )
    drive_job_to_ready_to_ship(
        ctx, press_id=press_id, machine_id=machine_id, tryout_shots=tryout_shots,
        machine_window=machine_window, press_window=press_window,
        submit_clock=submit_clock,
    )
    ship_tool(ctx["tool"]["id"], tracking_number=tracking_number)
    deliver_tool(ctx["tool"]["id"])
    refresh_job(ctx)
    refresh_tool(ctx)
    return ctx
