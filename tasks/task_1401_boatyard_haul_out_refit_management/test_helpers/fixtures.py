"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at its startup default). Setup calls use
get_success_data so failures surface as clear "Setup failed" errors.

Identity threading: Owner-role calls (approve, request-change, owner part
creation) are ownership-gated on the vessel's `owner_user_id`, so every
helper that performs them takes the owner_user_id and builds per-instance
headers via make_owner_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_compliance_hold_payload,
    create_environmental_event_payload,
    create_insurance_certificate_payload,
    create_labor_entry_payload,
    create_ledger_entry_payload,
    create_lift_slot_payload,
    create_part_payload,
    create_refit_job_payload,
    create_stand_assignment_payload,
    create_vessel_payload,
    create_work_order_payload,
    create_yard_row_payload,
)
from .test_users import TEST_USERS, make_owner_headers

SW = TEST_USERS["service_writer_headers"]
YM = TEST_USERS["yard_manager_headers"]
EO = TEST_USERS["environmental_officer_headers"]
AC = TEST_USERS["accountant_headers"]

CLOCK_INIT = "2026-08-01T09:00:00Z"
HAUL_DATE = "2026-08-02"
SPLASH_DATE = "2026-08-20"


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected_status=None):
    if expected_status is not None and resp.status_code != expected_status:
        _fail(step, resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (PRD section 2.6)."""
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601}, YM)
    return _ok("set_current_utc", resp)


def run_daily_close():
    """Run the daily-close operations checkpoint (PRD section 3.11)."""
    resp = api_client.run_daily_close(YM)
    return _ok("run_daily_close", resp)


def create_vessel(name="MV Test", owner_user_id="owner-1", loa_ft=40,
                  beam_ft=13, hull_type="POWER", displacement_tons=20):
    resp = api_client.create_vessel(
        create_vessel_payload(
            name=name, owner_user_id=owner_user_id, loa_ft=loa_ft,
            beam_ft=beam_ft, hull_type=hull_type,
            displacement_tons=displacement_tons),
        SW,
    )
    return _ok("create_vessel", resp, expected_status=201)


def add_insurance(vessel_id, policy_no="POL-1",
                  liability_coverage_cents=200000000,
                  effective_date="2026-01-01", expiry_date="2027-06-01"):
    resp = api_client.create_insurance_certificate(
        create_insurance_certificate_payload(
            vessel_id, policy_no=policy_no,
            liability_coverage_cents=liability_coverage_cents,
            effective_date=effective_date, expiry_date=expiry_date),
        SW,
    )
    return _ok("create_insurance_certificate", resp, expected_status=201)


def create_refit_job(vessel_id, billing_mode=None, scope_notes=None):
    overrides = {}
    if billing_mode is not None:
        overrides["billing_mode"] = billing_mode
    if scope_notes is not None:
        overrides["scope_notes"] = scope_notes
    resp = api_client.create_refit_job(
        create_refit_job_payload(vessel_id, **overrides), SW)
    return _ok("create_refit_job", resp, expected_status=201)


def submit_refit_job(job_id):
    resp = api_client.submit_refit_job(job_id, SW)
    return _ok("submit_refit_job", resp)


def get_job(job_id, headers=None):
    resp = api_client.get_refit_job(job_id, headers or SW)
    return _ok("get_refit_job", resp)


def create_row(code="A", total_stands=10):
    resp = api_client.create_yard_row(
        create_yard_row_payload(code=code, total_stands=total_stands), YM)
    return _ok("create_yard_row", resp, expected_status=201)


def get_row(row_id):
    resp = api_client.get_yard_row(row_id, YM)
    return _ok("get_yard_row", resp)


def assign_stands(row_id, job_id, stands_used=4, start_date="2026-08-02",
                  end_date="2026-09-30"):
    """Create an ACTIVE stand assignment; re-reads the row first so the
    OCC expected version is always current (PRD section 2.5)."""
    row = get_row(row_id)
    resp = api_client.create_stand_assignment(
        create_stand_assignment_payload(
            row_id, job_id, row["version"], stands_used=stands_used,
            start_date=start_date, end_date=end_date),
        YM,
    )
    return _ok("create_stand_assignment", resp, expected_status=201)


def book_lift_slot(job_id, kind="HAUL_OUT",
                   scheduled_start="2026-08-02T08:00:00Z",
                   scheduled_end="2026-08-02T09:00:00Z",
                   vessel_displacement_tons=20):
    resp = api_client.create_lift_slot(
        create_lift_slot_payload(
            job_id, kind=kind, scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            vessel_displacement_tons=vessel_displacement_tons),
        YM,
    )
    return _ok("create_lift_slot", resp, expected_status=201)


def complete_slot_at(slot_id, at_iso8601):
    """Move the logical clock inside the slot window, then complete it."""
    set_clock(at_iso8601)
    resp = api_client.complete_lift_slot(slot_id, YM)
    return _ok("complete_lift_slot", resp)


def create_work_order(job_id, type="MECHANICAL", description="Engine service",
                      quoted_hours=10, quoted_rate_cents=8000,
                      quoted_parts_cents=5000):
    resp = api_client.create_work_order(
        create_work_order_payload(
            job_id, type=type, description=description,
            quoted_hours=quoted_hours, quoted_rate_cents=quoted_rate_cents,
            quoted_parts_cents=quoted_parts_cents),
        SW,
    )
    return _ok("create_work_order", resp, expected_status=201)


def get_work_order(work_order_id, headers=None):
    resp = api_client.get_work_order(work_order_id, headers or SW)
    return _ok("get_work_order", resp)


def approve_work_order(work_order_id, owner_user_id):
    """Owner approval — ownership-gated, so headers carry the vessel's
    owner_user_id (PRD section 3.5)."""
    resp = api_client.approve_work_order(
        work_order_id, make_owner_headers(owner_user_id))
    return _ok("approve_work_order", resp)


def start_work_order(work_order_id):
    resp = api_client.start_work_order(work_order_id, SW)
    return _ok("start_work_order", resp)


def complete_work_order(work_order_id):
    resp = api_client.complete_work_order(work_order_id, SW)
    return _ok("complete_work_order", resp)


def log_labor(work_order_id, worker_type="YARD_CREW", hours=5,
              rate_cents=8000, subcontractor_name=None):
    overrides = {}
    if subcontractor_name is not None:
        overrides["subcontractor_name"] = subcontractor_name
    resp = api_client.create_labor_entry(
        create_labor_entry_payload(
            work_order_id, worker_type=worker_type, hours=hours,
            rate_cents=rate_cents, **overrides),
        SW,
    )
    return _ok("create_labor_entry", resp, expected_status=201)


def post_ledger_entry(job_id, kind="DEPOSIT", amount_cents=21250, memo=None):
    overrides = {}
    if memo is not None:
        overrides["memo"] = memo
    resp = api_client.create_ledger_entry(
        create_ledger_entry_payload(job_id, kind=kind,
                                    amount_cents=amount_cents, **overrides),
        AC,
    )
    return _ok("create_ledger_entry", resp, expected_status=201)


def post_manual_hold(job_id, kind="PAYMENT", note="Hold note"):
    """Place a MANUAL hold; role is kind-segregated (PRD section 3.9)."""
    headers = AC if kind == "PAYMENT" else EO
    resp = api_client.create_compliance_hold(
        create_compliance_hold_payload(job_id, kind=kind, note=note),
        headers,
    )
    return _ok("create_compliance_hold", resp, expected_status=201)


def log_environmental_event(job_id, kind="SANDING", containment_used=True,
                            runoff_tss_ppm=150.0):
    resp = api_client.create_environmental_event(
        create_environmental_event_payload(
            job_id, kind=kind, containment_used=containment_used,
            runoff_tss_ppm=runoff_tss_ppm),
        EO,
    )
    return _ok("create_environmental_event", resp, expected_status=201)


def get_statement(job_id, headers=None):
    resp = api_client.get_statement(job_id, headers or AC)
    return _ok("get_statement", resp)


def list_ledger_entries(job_id, params=None, headers=None):
    resp = api_client.list_ledger_entries(job_id, headers or AC,
                                          params=params)
    return _ok("list_ledger_entries", resp)


def list_compliance_holds(job_id, params=None, headers=None):
    resp = api_client.list_compliance_holds(job_id, headers or EO,
                                            params=params)
    return _ok("list_compliance_holds", resp)


def list_lift_slots(job_id, params=None, headers=None):
    resp = api_client.list_lift_slots(job_id, headers or YM, params=params)
    return _ok("list_lift_slots", resp)


# ---------------------------------------------------------------------------
# Tier 1-2: vessel -> submitted job -> job ON_HARD
# ---------------------------------------------------------------------------

def create_vessel_with_insurance(name="MV Test", owner_user_id="owner-1",
                                 loa_ft=40, beam_ft=13, hull_type="POWER",
                                 displacement_tons=20,
                                 policy_no="POL-1", **cert_overrides):
    """Registered vessel plus a qualifying ACTIVE certificate."""
    vessel = create_vessel(name=name, owner_user_id=owner_user_id,
                           loa_ft=loa_ft, beam_ft=beam_ft,
                           hull_type=hull_type,
                           displacement_tons=displacement_tons)
    cert = add_insurance(vessel["id"], policy_no=policy_no, **cert_overrides)
    return vessel, cert


def create_submitted_job(vessel_id, billing_mode=None):
    """DRAFT job submitted to INTAKE."""
    job = create_refit_job(vessel_id, billing_mode=billing_mode)
    return submit_refit_job(job["id"])


def setup_job_on_hard(owner_user_id="owner-1", vessel_name="MV Hard",
                      loa_ft=40, beam_ft=13, hull_type="POWER",
                      displacement_tons=20, billing_mode=None,
                      row_code="A", total_stands=10, stands_used=4,
                      haul_date=HAUL_DATE, stand_start_date=None,
                      stand_end_date="2026-09-30",
                      clock_init=CLOCK_INIT, cert_overrides=None):
    """Full preamble through ON_HARD: clock -> vessel -> certificate ->
    job -> submit -> row -> stand assignment -> HAUL_OUT slot booked ->
    slot completed inside its window.

    Returns dict(vessel, certificate, job, row, assignment, haul_slot)
    with the job re-fetched (status ON_HARD).
    """
    set_clock(clock_init)
    vessel, cert = create_vessel_with_insurance(
        name=vessel_name, owner_user_id=owner_user_id, loa_ft=loa_ft,
        beam_ft=beam_ft, hull_type=hull_type,
        displacement_tons=displacement_tons,
        policy_no=f"POL-{row_code}", **(cert_overrides or {}))
    job = create_submitted_job(vessel["id"], billing_mode=billing_mode)
    row = create_row(code=row_code, total_stands=total_stands)
    assignment = assign_stands(
        row["id"], job["id"], stands_used=stands_used,
        start_date=stand_start_date or haul_date, end_date=stand_end_date)
    haul_slot = book_lift_slot(
        job["id"], kind="HAUL_OUT",
        scheduled_start=f"{haul_date}T08:00:00Z",
        scheduled_end=f"{haul_date}T09:00:00Z",
        vessel_displacement_tons=displacement_tons)
    complete_slot_at(haul_slot["id"], f"{haul_date}T08:30:00Z")
    return {
        "vessel": vessel,
        "certificate": cert,
        "job": get_job(job["id"]),
        "row": get_row(row["id"]),
        "assignment": assignment,
        "haul_slot": haul_slot,
    }


# ---------------------------------------------------------------------------
# Tier 3: worked job -> READY_FOR_SPLASH -> AWAITING_TRIAL
# ---------------------------------------------------------------------------

def setup_job_ready_for_splash(wo_type="MECHANICAL",
                               wo_description="Engine service",
                               quoted_hours=10, quoted_rate_cents=8000,
                               quoted_parts_cents=5000,
                               labor_lines=None,
                               deposit_cents=21250,
                               book_splash=False,
                               splash_date=SPLASH_DATE,
                               **on_hard_kwargs):
    """Job ON_HARD + one work order approved, started, optionally labored,
    completed (job auto-advances to READY_FOR_SPLASH) + optional DEPOSIT
    ledger entry + optional BOOKED splash slot.

    labor_lines: list of dicts with keys hours / rate_cents / worker_type /
    subcontractor_name, logged while the work order is IN_PROGRESS.

    Returns the setup_job_on_hard dict plus work_order, deposit_entry
    (or None) and splash_slot (or None); job re-fetched READY_FOR_SPLASH.
    """
    base = setup_job_on_hard(**on_hard_kwargs)
    job_id = base["job"]["id"]
    owner_user_id = base["vessel"]["owner_user_id"]

    work_order = create_work_order(
        job_id, type=wo_type, description=wo_description,
        quoted_hours=quoted_hours, quoted_rate_cents=quoted_rate_cents,
        quoted_parts_cents=quoted_parts_cents)
    approve_work_order(work_order["id"], owner_user_id)
    start_work_order(work_order["id"])
    for line in (labor_lines or []):
        log_labor(work_order["id"], **line)
    complete_work_order(work_order["id"])

    deposit_entry = None
    if deposit_cents is not None:
        deposit_entry = post_ledger_entry(job_id, kind="DEPOSIT",
                                          amount_cents=deposit_cents,
                                          memo="25% deposit")

    splash_slot = None
    if book_splash:
        splash_slot = book_lift_slot(
            job_id, kind="SPLASH",
            scheduled_start=f"{splash_date}T08:00:00Z",
            scheduled_end=f"{splash_date}T09:00:00Z",
            vessel_displacement_tons=base["vessel"]["displacement_tons"])

    base.update({
        "work_order": get_work_order(work_order["id"]),
        "deposit_entry": deposit_entry,
        "splash_slot": splash_slot,
        "job": get_job(job_id),
    })
    return base


def setup_job_awaiting_trial(splash_date=SPLASH_DATE, **kwargs):
    """READY_FOR_SPLASH setup plus the splash slot completed inside its
    window; job re-fetched AWAITING_TRIAL."""
    kwargs["book_splash"] = True
    base = setup_job_ready_for_splash(splash_date=splash_date, **kwargs)
    complete_slot_at(base["splash_slot"]["id"], f"{splash_date}T08:30:00Z")
    base["job"] = get_job(base["job"]["id"])
    base["assignment"] = get_success_data(
        api_client.get_stand_assignment(base["assignment"]["id"], YM))
    return base


# ---------------------------------------------------------------------------
# Tier 4: specialized composite scenarios
# ---------------------------------------------------------------------------

def setup_two_jobs_different_billing_modes():
    """Two 40 ft vessels, job A DAILY and job B MONTHLY_CONTRACT, both
    hauled 2026-08-02; clock advanced to 2026-08-11 and one daily close
    executed (10 lay days accrued on each). Returns (ctx_a, ctx_b)."""
    set_clock(CLOCK_INIT)
    ctxs = []
    for name, owner, hull, tons, mode in (
        ("MV Daily", "owner-1", "POWER", 20, "DAILY"),
        ("MV Monthly", "owner-2", "SAIL", 18, "MONTHLY_CONTRACT"),
    ):
        vessel, cert = create_vessel_with_insurance(
            name=name, owner_user_id=owner, loa_ft=40, beam_ft=13,
            hull_type=hull, displacement_tons=tons, policy_no=f"POL-{owner}")
        job = create_submitted_job(vessel["id"], billing_mode=mode)
        ctxs.append({"vessel": vessel, "certificate": cert, "job": job})

    row = create_row(code="A", total_stands=10)
    for ctx in ctxs:
        ctx["assignment"] = assign_stands(row["id"], ctx["job"]["id"],
                                          stands_used=4)
    slot_specs = (("2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z",
                   "2026-08-02T08:30:00Z"),
                  ("2026-08-02T09:30:00Z", "2026-08-02T10:30:00Z",
                   "2026-08-02T09:45:00Z"))
    for ctx, (start, end, complete_at) in zip(ctxs, slot_specs):
        ctx["haul_slot"] = book_lift_slot(
            ctx["job"]["id"], kind="HAUL_OUT", scheduled_start=start,
            scheduled_end=end,
            vessel_displacement_tons=ctx["vessel"]["displacement_tons"])
        complete_slot_at(ctx["haul_slot"]["id"], complete_at)
        ctx["job"] = get_job(ctx["job"]["id"])

    set_clock("2026-08-11T12:00:00Z")
    close = run_daily_close()
    return ctxs[0], ctxs[1], close


def setup_two_intake_jobs(prefix="MV", row_code=None):
    """Two vessels with qualifying certificates, each with a job submitted
    to INTAKE. Returns (ctx_a, ctx_b); ctx = dict(vessel, job)."""
    set_clock(CLOCK_INIT)
    ctxs = []
    for idx, owner in enumerate(("owner-1", "owner-2"), start=1):
        vessel, _cert = create_vessel_with_insurance(
            name=f"{prefix} {idx}", owner_user_id=owner, loa_ft=30,
            beam_ft=10, hull_type="POWER" if idx == 1 else "SAIL",
            displacement_tons=10, policy_no=f"POL-{prefix}-{idx}")
        job = create_submitted_job(vessel["id"])
        ctxs.append({"vessel": vessel, "job": job})
    return ctxs[0], ctxs[1]


def setup_moratorium_scenario():
    """March timeline: job A fully worked to READY_FOR_SPLASH with a BOOKED
    SPLASH slot at 2026-04-10T08:00-09:00; job B (second vessel) in INTAKE.
    Returns (ctx_a, ctx_b)."""
    base_a = setup_job_ready_for_splash(
        vessel_name="MV Early", owner_user_id="owner-1",
        row_code="M", haul_date="2026-03-02", stand_end_date="2026-04-30",
        clock_init="2026-03-01T09:00:00Z",
        cert_overrides={"expiry_date": "2027-01-01"},
        book_splash=True, splash_date="2026-04-10")
    vessel_b, _cert_b = create_vessel_with_insurance(
        name="MV Late", owner_user_id="owner-2", loa_ft=36, beam_ft=12,
        hull_type="SAIL", displacement_tons=14, policy_no="POL-LATE",
        expiry_date="2027-01-01")
    job_b = create_submitted_job(vessel_b["id"])
    ctx_b = {"vessel": vessel_b, "job": job_b}
    return base_a, ctx_b
