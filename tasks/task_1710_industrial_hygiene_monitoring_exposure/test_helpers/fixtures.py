"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints: the harness restarts the server before each test, so nothing is
carried over. Setup calls use the lenient get_success_data() validator so a
broken precondition surfaces as a clear "Setup step failed" message.

Canonical operator identities (opaque per PRD §2.1):
  u_admin (FirmAdmin), u_ih_1 (plan creator / assessment preparer),
  u_cih_1 (plan approver / assessment signer), u_tech_1 (collector /
  calibrator), u_lab_1 (lab analyst), u_ssm_1 (safety manager).
Segregation of duties is honored throughout: creator != approver,
collector != analyst, preparer != signer.
"""
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BATCH_WINDOW_END, BATCH_WINDOW_START, LAB_CLOCK
from .factories import (
    create_assessment_payload,
    create_batch_payload,
    create_calibration_payload,
    create_clearance_payload,
    create_control_payload,
    create_employee_payload,
    create_fit_test_payload,
    create_limit_payload,
    create_membership_payload,
    create_plan_payload,
    create_pump_payload,
    create_sample_payload,
    create_seg_payload,
    create_site_payload,
    decide_clearance_payload,
    record_fit_result_payload,
    record_post_payload,
    revise_plan_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["firm_admin_headers"]
IH = TEST_USERS["ih_headers"]
IH2 = TEST_USERS["ih2_headers"]
CIH = TEST_USERS["cih_headers"]
CIH2 = TEST_USERS["cih2_headers"]
TECH = TEST_USERS["tech_headers"]
TECH2 = TEST_USERS["tech2_headers"]
LAB = TEST_USERS["lab_headers"]
LAB2 = TEST_USERS["lab2_headers"]
SSM = TEST_USERS["ssm_headers"]


class Ctx(dict):
    """Attribute-access dict for pipeline contexts."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


# ─── Primitive steps ─────────────────────────────────────────────────


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.5); triggers the time-based sweeps."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_site(**overrides) -> dict:
    return get_success_data(api_client.create_site(create_site_payload(**overrides), ADMIN))


def create_employee(site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_employee(create_employee_payload(site_id, **overrides), ADMIN)
    )


def create_limit(**overrides) -> dict:
    return get_success_data(
        api_client.create_exposure_limit(create_limit_payload(**overrides), ADMIN)
    )


def create_pump(site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_pump(create_pump_payload(site_id, **overrides), ADMIN)
    )


def create_seg(site_id: str, exposure_limit_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_seg(
            create_seg_payload(site_id, exposure_limit_id, **overrides), IH
        )
    )


def create_membership(seg_id: str, employee_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_membership(
            create_membership_payload(seg_id, employee_id, **overrides), IH
        )
    )


def create_plan(seg_id: str, **overrides) -> dict:
    """Create a DRAFT plan as u_ih_1 (the recorded creator, PRD §3.3)."""
    return get_success_data(
        api_client.create_sampling_plan(create_plan_payload(seg_id, **overrides), IH)
    )


def revise_plan(plan_id: str, expected_plan_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.revise_sampling_plan(
            plan_id, revise_plan_payload(expected_plan_version, **overrides), IH
        )
    )


def submit_plan(plan_id: str) -> dict:
    return get_success_data(api_client.submit_plan(plan_id, IH))


def approve_plan(plan_id: str) -> dict:
    return get_success_data(api_client.approve_plan(plan_id, CIH))


def reject_plan(plan_id: str) -> dict:
    return get_success_data(api_client.reject_plan(plan_id, CIH))


def complete_field(plan_id: str) -> dict:
    return get_success_data(api_client.complete_field(plan_id, IH))


def create_calibration(pump_id: str, pre_flow_lpm: float = 2.0) -> dict:
    return get_success_data(
        api_client.create_pump_calibration(
            create_calibration_payload(pump_id, pre_flow_lpm=pre_flow_lpm), TECH
        )
    )


def record_post(calibration_id: str, post_flow_lpm: float = 2.0) -> dict:
    return get_success_data(
        api_client.record_post_flow(
            calibration_id, record_post_payload(post_flow_lpm), TECH
        )
    )


def create_sample(
    plan_id: str,
    sample_type: str = "PERSONAL",
    employee_id: Optional[str] = None,
    pump_id: Optional[str] = None,
    pre_calibration_id: Optional[str] = None,
    collection_date: str = "2026-08-03",
    start_minute: int = 480,
    duration_minutes: int = 240,
) -> dict:
    """Log a sample as u_tech_1 (the recorded collector, PRD §3.4)."""
    return get_success_data(
        api_client.create_field_sample(
            create_sample_payload(
                plan_id,
                sample_type=sample_type,
                collection_date=collection_date,
                start_minute=start_minute,
                duration_minutes=duration_minutes,
                employee_id=employee_id,
                pump_id=pump_id,
                pre_calibration_id=pre_calibration_id,
            ),
            TECH,
        )
    )


def seal_sample(sample_id: str) -> dict:
    return get_success_data(api_client.seal_sample(sample_id, TECH))


def invalidate_sample(sample_id: str, reason: str = "dropped cassette") -> dict:
    return get_success_data(api_client.invalidate_sample(sample_id, {"reason": reason}, IH))


def create_batch(site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lab_batch(create_batch_payload(site_id, **overrides), LAB)
    )


def enter_result(sample_id: str, batch_id: str, mass_ug) -> dict:
    """Enter a lab result as u_lab_1 (never the collector, PRD §2.9)."""
    return get_success_data(
        api_client.create_lab_result(
            {
                "field_sample_id": sample_id,
                "lab_batch_id": batch_id,
                "mass_ug": mass_ug,
            },
            LAB,
        )
    )


def get_seg(seg_id: str) -> dict:
    return get_success_data(api_client.get_seg(seg_id, IH))


def get_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_sampling_plan(plan_id, IH))


def get_sample(sample_id: str) -> dict:
    return get_success_data(api_client.get_field_sample(sample_id, IH))


def get_calibration(calibration_id: str) -> dict:
    return get_success_data(api_client.get_pump_calibration(calibration_id, IH))


def get_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_lab_batch(batch_id, IH))


def get_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.get_exposure_assessment(assessment_id, IH))


def get_control(control_id: str) -> dict:
    return get_success_data(api_client.get_control(control_id, IH))


def get_notification(notification_id: str) -> dict:
    return get_success_data(api_client.get_notification(notification_id, IH))


def get_clearance(clearance_id: str) -> dict:
    return get_success_data(api_client.get_medical_clearance(clearance_id, IH))


def get_fit_test(fit_test_id: str) -> dict:
    return get_success_data(api_client.get_fit_test(fit_test_id, IH))


def list_notification_rows(**params) -> list:
    return get_success_data(api_client.list_notifications(IH, params=params or None))


def list_control_rows(**params) -> list:
    return get_success_data(api_client.list_controls(IH, params=params or None))


def list_assessment_rows(**params) -> list:
    return get_success_data(
        api_client.list_exposure_assessments(IH, params=params or None)
    )


# ─── Assessments / controls / qualification primitives ───────────────


def create_assessment(plan_id: str, seg_id: str) -> dict:
    """Create an assessment as u_ih_1, carrying the SEG's current version
    in expected_seg_version per the OCC rule (PRD §2.7)."""
    seg = get_seg(seg_id)
    return get_success_data(
        api_client.create_exposure_assessment(
            create_assessment_payload(plan_id, seg["version"]), IH
        )
    )


def submit_review(assessment_id: str) -> dict:
    return get_success_data(api_client.submit_assessment_review(assessment_id, IH))


def sign_assessment(assessment_id: str) -> dict:
    """Sign as u_cih_1 — always a different operator than the preparer (§2.9)."""
    return get_success_data(api_client.sign_assessment(assessment_id, CIH))


def reject_review(assessment_id: str) -> dict:
    return get_success_data(api_client.reject_assessment_review(assessment_id, CIH))


def set_legal_hold(assessment_id: str, hold: bool) -> dict:
    return get_success_data(
        api_client.update_assessment(assessment_id, {"legal_hold": hold}, CIH)
    )


def archive_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.archive_assessment(assessment_id, ADMIN))


def create_control(assessment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_control(create_control_payload(assessment_id, **overrides), IH)
    )


def accept_control(control_id: str) -> dict:
    return get_success_data(api_client.accept_control(control_id, SSM))


def reject_control(control_id: str) -> dict:
    return get_success_data(api_client.reject_control(control_id, SSM))


def implement_control(control_id: str) -> dict:
    return get_success_data(api_client.implement_control(control_id, SSM))


def verify_control(control_id: str) -> dict:
    return get_success_data(api_client.verify_control(control_id, CIH))


def request_clearance(employee_id: str) -> dict:
    return get_success_data(
        api_client.create_medical_clearance(create_clearance_payload(employee_id), SSM)
    )


def decide_clearance(clearance_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_clearance(clearance_id, decide_clearance_payload(decision), CIH)
    )


def schedule_fit_test(employee_id: str, clearance_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_fit_test(
            create_fit_test_payload(employee_id, clearance_id, **overrides), SSM
        )
    )


def record_fit_result(fit_test_id: str, result: str) -> dict:
    return get_success_data(
        api_client.record_fit_test_result(
            fit_test_id, record_fit_result_payload(result), TECH
        )
    )


# ─── Tier 2: entity hierarchy ────────────────────────────────────────


def setup_site_seg(
    member_count: int = 3,
    analyte_code: str = "PB",
    basis: str = "OSHA_PEL",
    limit_type: str = "TWA8",
    limit_mg_m3: float = 0.05,
    action_fraction=None,
    site_overrides=None,
) -> Ctx:
    """Site + exposure limit + SEG + member_count employees, each a member."""
    site = create_site(**(site_overrides or {}))
    limit = create_limit(
        analyte_code=analyte_code,
        basis=basis,
        limit_type=limit_type,
        limit_mg_m3=limit_mg_m3,
        **({"action_fraction": action_fraction} if action_fraction is not None else {}),
    )
    seg = create_seg(site["id"], limit["id"], analyte_code=analyte_code)
    employees = []
    memberships = []
    for _ in range(member_count):
        emp = create_employee(site["id"])
        memberships.append(create_membership(seg["id"], emp["id"]))
        employees.append(emp)
    return Ctx(
        site=site,
        limit=limit,
        seg=seg,
        employees=employees,
        memberships=memberships,
    )


def setup_approved_plan(
    ctx: Optional[Ctx] = None,
    member_count: int = 3,
    limit_kwargs: Optional[dict] = None,
    **plan_overrides,
) -> Ctx:
    """SEG context plus one plan walked DRAFT -> PENDING_APPROVAL -> APPROVED."""
    if ctx is None:
        ctx = setup_site_seg(member_count=member_count, **(limit_kwargs or {}))
    plan = create_plan(ctx.seg["id"], **plan_overrides)
    submit_plan(plan["id"])
    ctx.plan = approve_plan(plan["id"])
    return ctx


# ─── Tier 3: field-work pipeline ─────────────────────────────────────

# Non-overlapping half-open intervals on a single collection date for a
# shared pump (PRD §3.4 double-booking rule): duration 240 by default.
_DEFAULT_STARTS = (480, 720, 960, 1200)


def collect_personal_samples(
    ctx: Ctx,
    count: int,
    plan: Optional[dict] = None,
    pre_flow: float = 2.0,
    duration: int = 240,
    collection_dates: Optional[List[str]] = None,
    start_minutes: Optional[List[int]] = None,
    seal: bool = True,
    record_post_flows: bool = True,
    post_flow: float = 2.0,
) -> Ctx:
    """Collect `count` PERSONAL samples against ctx.plan (or `plan`).

    One shared pump, one fresh calibration per sample; start minutes are
    staggered so same-date intervals never overlap. Employees cycle through
    the SEG members. Samples are sealed and their calibrations record-posted
    (drift 0 -> VALID) unless disabled.
    """
    plan = plan or ctx.plan
    pump = ctx.get("pump")
    if pump is None:
        pump = create_pump(ctx.site["id"])
        ctx.pump = pump
    samples = []
    calibrations = []
    for i in range(count):
        cal = create_calibration(pump["id"], pre_flow_lpm=pre_flow)
        date = (
            collection_dates[i]
            if collection_dates
            else plan["planned_start_date"]
        )
        start = start_minutes[i] if start_minutes else _DEFAULT_STARTS[i % 4]
        sample = create_sample(
            plan["id"],
            employee_id=ctx.employees[i % len(ctx.employees)]["id"],
            pump_id=pump["id"],
            pre_calibration_id=cal["id"],
            collection_date=date,
            start_minute=start,
            duration_minutes=duration,
        )
        if seal:
            sample = seal_sample(sample["id"])
        if record_post_flows:
            record_post(cal["id"], post_flow_lpm=post_flow)
        samples.append(sample)
        calibrations.append(cal)
    ctx.samples = samples
    ctx.calibrations = calibrations
    return ctx


def setup_field_complete(
    n_samples: int = 3,
    member_count: int = 3,
    plan_overrides=None,
    limit_kwargs: Optional[dict] = None,
    **sample_kwargs,
) -> Ctx:
    """Approved plan + n_samples SEALED PERSONAL samples (calibrations VALID)
    + complete-field -> plan FIELD_COMPLETE."""
    ctx = setup_approved_plan(
        member_count=member_count,
        limit_kwargs=limit_kwargs,
        **(plan_overrides or {}),
    )
    collect_personal_samples(ctx, n_samples, **sample_kwargs)
    ctx.plan = complete_field(ctx.plan["id"])
    return ctx


def setup_lab_complete(
    masses=(12, 10, 8),
    member_count: int = 3,
    lod: float = 5,
    loq: float = 10,
    batch_window=(BATCH_WINDOW_START, BATCH_WINDOW_END),
    batch_capacity: int = 10,
    clock_at: str = LAB_CLOCK,
    plan_overrides=None,
    limit_kwargs: Optional[dict] = None,
    **sample_kwargs,
) -> Ctx:
    """Full pipeline through LAB_COMPLETE: field-complete plan, open batch,
    logical clock inside the intake window, one result per sample."""
    ctx = setup_field_complete(
        n_samples=len(masses), member_count=member_count,
        plan_overrides=plan_overrides, limit_kwargs=limit_kwargs,
        **sample_kwargs,
    )
    ctx.batch = create_batch(
        ctx.site["id"],
        analyte_code=ctx.seg["analyte_code"],
        lod_ug=lod,
        loq_ug=loq,
        window_start_date=batch_window[0],
        window_end_date=batch_window[1],
        max_capacity=batch_capacity,
    )
    set_clock(clock_at)
    ctx.results = [
        enter_result(sample["id"], ctx.batch["id"], mass)
        for sample, mass in zip(ctx.samples, masses)
    ]
    ctx.plan = get_plan(ctx.plan["id"])
    return ctx


def drive_ctx_to_lab_complete(
    ctx: Ctx,
    masses,
    lod: float = 5,
    loq: float = 10,
    batch_window=(BATCH_WINDOW_START, BATCH_WINDOW_END),
    batch_capacity: int = 10,
    clock_at: str = LAB_CLOCK,
    plan_overrides=None,
    **sample_kwargs,
) -> Ctx:
    """Drive an existing SEG context through one full campaign: create plan,
    submit, approve, collect/seal/record-post one sample per mass,
    complete-field, open a batch, set the clock, enter all results."""
    plan = create_plan(ctx.seg["id"], **(plan_overrides or {}))
    submit_plan(plan["id"])
    ctx.plan = approve_plan(plan["id"])
    collect_personal_samples(ctx, len(masses), **sample_kwargs)
    ctx.plan = complete_field(ctx.plan["id"])
    ctx.batch = create_batch(
        ctx.site["id"],
        analyte_code=ctx.seg["analyte_code"],
        lod_ug=lod,
        loq_ug=loq,
        window_start_date=batch_window[0],
        window_end_date=batch_window[1],
        max_capacity=batch_capacity,
    )
    set_clock(clock_at)
    ctx.results = [
        enter_result(sample["id"], ctx.batch["id"], mass)
        for sample, mass in zip(ctx.samples, masses)
    ]
    ctx.plan = get_plan(ctx.plan["id"])
    return ctx


def drive_plan_to_lab_complete(
    ctx: Ctx,
    plan: dict,
    masses,
    lod: float = 5,
    loq: float = 10,
    batch_window=(BATCH_WINDOW_START, BATCH_WINDOW_END),
    batch_capacity: int = 10,
    clock_at: str = LAB_CLOCK,
    **sample_kwargs,
) -> Ctx:
    """Walk an already-created DRAFT plan (e.g. a spawned verification plan)
    through submit/approve, field work, and lab entry to LAB_COMPLETE."""
    submit_plan(plan["id"])
    plan = approve_plan(plan["id"])
    collect_personal_samples(ctx, len(masses), plan=plan, **sample_kwargs)
    complete_field(plan["id"])
    ctx.batch = create_batch(
        ctx.site["id"],
        analyte_code=ctx.seg["analyte_code"],
        lod_ug=lod,
        loq_ug=loq,
        window_start_date=batch_window[0],
        window_end_date=batch_window[1],
        max_capacity=batch_capacity,
    )
    set_clock(clock_at)
    ctx.results = [
        enter_result(sample["id"], ctx.batch["id"], mass)
        for sample, mass in zip(ctx.samples, masses)
    ]
    ctx.plan = get_plan(plan["id"])
    return ctx


# ─── Tier 5: assessment lifecycle ────────────────────────────────────


def setup_draft_assessment(masses=(12, 10, 8), **kwargs) -> Ctx:
    """LAB_COMPLETE plan + a DRAFT assessment prepared by u_ih_1."""
    ctx = setup_lab_complete(masses=masses, **kwargs)
    ctx.assessment = create_assessment(ctx.plan["id"], ctx.seg["id"])
    return ctx


def setup_signed_assessment(masses=(12, 10, 8), **kwargs) -> Ctx:
    """Assessment walked DRAFT -> UNDER_REVIEW -> SIGNED (signer u_cih_1)."""
    ctx = setup_draft_assessment(masses=masses, **kwargs)
    submit_review(ctx.assessment["id"])
    ctx.assessment = sign_assessment(ctx.assessment["id"])
    ctx.seg = get_seg(ctx.seg["id"])
    return ctx


# ─── Worker qualification (PRD §3.8) ─────────────────────────────────


def qualify_member(
    employee_id: str, test_date: str = "2026-08-03", result: str = "PASS"
) -> Ctx:
    """Clearance requested + CLEARED, then a fit test recorded for it.

    Runs at the startup clock (2026-08-01), so the clearance decision date is
    2026-08-01 and its expiry lands on 2027-08-01.
    """
    clearance = request_clearance(employee_id)
    clearance = decide_clearance(clearance["id"], "CLEARED")
    fit_test = schedule_fit_test(employee_id, clearance["id"], test_date=test_date)
    fit_test = record_fit_result(fit_test["id"], result)
    return Ctx(clearance=clearance, fit_test=fit_test)
