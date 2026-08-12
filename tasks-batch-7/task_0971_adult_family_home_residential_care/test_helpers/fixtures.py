"""
Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against a fresh server,
using only PRD-declared endpoints. Setup calls use get_success_data() (lenient)
so failures surface as clear "Setup failed" errors rather than confusing
assertion failures deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_home_payload, create_bed_payload, create_resident_payload,
    create_assessment_payload, create_admission_payload,
    create_medication_order_payload, create_caregiver_payload,
    create_shift_payload, create_incident_payload, create_rate_schedule_payload,
    create_invoice_generate_payload, create_payment_payload,
    create_discharge_payload,
)
from .test_users import TEST_USERS, make_provider_headers

PROVIDER = TEST_USERS["provider_headers"]
PROVIDER2 = TEST_USERS["provider2_headers"]
NURSE = TEST_USERS["nurse_headers"]

SETUP_CLOCK = "2026-05-20T00:00:00Z"


# ─── Atomic helpers ───────────────────────────────────

def set_clock(to_iso8601):
    """Advance the logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, PROVIDER))


def create_home(**overrides):
    """Register a home (starts PROVISIONAL). Returns the home."""
    return get_success_data(
        api_client.create_home(create_home_payload(**overrides), PROVIDER))


def add_bed(home_id, label="1A", medicaid_certified=None):
    """Add a bed to a home. Returns the bed (AVAILABLE)."""
    payload = create_bed_payload(label=label)
    if medicaid_certified is not None:
        payload["medicaid_certified"] = medicaid_certified
    return get_success_data(api_client.create_bed(home_id, payload, PROVIDER))


def add_caregiver(home_id, awake_overnight_qualified=None, **overrides):
    """Register a caregiver. Returns the caregiver (ACTIVE)."""
    payload = create_caregiver_payload(**overrides)
    if awake_overnight_qualified is not None:
        payload["awake_overnight_qualified"] = awake_overnight_qualified
    return get_success_data(api_client.create_caregiver(home_id, payload, PROVIDER))


def license_home(home_id):
    """PROVISIONAL -> LICENSED. Returns the updated home."""
    return get_success_data(api_client.license_home(home_id, PROVIDER))


def publish_rate_schedule(home_id, **overrides):
    """Publish a rate schedule. Returns the schedule."""
    return get_success_data(
        api_client.create_rate_schedule(home_id, create_rate_schedule_payload(**overrides),
                                        PROVIDER))


def create_resident(home_id, **overrides):
    """Register a prospective resident (starts PROSPECT). Returns the resident."""
    return get_success_data(
        api_client.create_resident(home_id, create_resident_payload(**overrides), NURSE))


def create_and_finalize_assessment(resident_id, **overrides):
    """Create a DRAFT assessment and finalize it (promotes PROSPECT -> APPLICANT,
    supersedes any prior FINALIZED assessment). Returns the FINALIZED assessment."""
    asm = get_success_data(
        api_client.create_assessment(resident_id, create_assessment_payload(**overrides),
                                     NURSE))
    return get_success_data(api_client.finalize_assessment(asm["id"], NURSE))


def fresh_bed(bed_id):
    return get_success_data(api_client.get_bed(bed_id, PROVIDER))


def fresh_resident(resident_id):
    return get_success_data(api_client.get_resident(resident_id, PROVIDER))


def fresh_caregiver(caregiver_id):
    return get_success_data(api_client.get_caregiver(caregiver_id, PROVIDER))


def fresh_home(home_id):
    return get_success_data(api_client.get_home(home_id, PROVIDER))


def fresh_shift(shift_id):
    return get_success_data(api_client.get_shift(shift_id, PROVIDER))


def fresh_admission(admission_id):
    return get_success_data(api_client.get_admission(admission_id, PROVIDER))


def fresh_incident(incident_id):
    return get_success_data(api_client.get_incident(incident_id, PROVIDER))


def fresh_case(case_id):
    return get_success_data(api_client.get_compliance_case(case_id, PROVIDER))


def fresh_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, PROVIDER))


def fresh_medication_order(resident_id, order_id):
    """Medication orders are only listable per-resident; read through the list."""
    from prd_bench_local_runner.testing import validate_paginated
    data, _meta = validate_paginated(
        api_client.list_medication_orders(resident_id, NURSE))
    matches = [o for o in data if o["id"] == order_id]
    assert len(matches) == 1, f"medication order {order_id} not found for resident"
    return matches[0]


def create_pending_admission(resident_id, bed_id, assessment_id,
                             expected_admission_date="2026-05-25",
                             creator_headers=None):
    """Create a PENDING admission holding the bed. Re-reads the bed so the OCC
    expected_bed_version is current. Returns the admission."""
    bed = fresh_bed(bed_id)
    payload = create_admission_payload(
        resident_id, bed_id, assessment_id, bed["version"],
        expected_admission_date=expected_admission_date)
    return get_success_data(
        api_client.create_admission(payload, creator_headers or PROVIDER))


def approve_admission(admission_id, approver_headers=None):
    """PENDING -> APPROVED. Default approver differs from the default creator."""
    return get_success_data(
        api_client.approve_admission(admission_id, approver_headers or PROVIDER2))


def complete_admission(admission_id, completer_headers=None):
    """APPROVED -> COMPLETED (resident ADMITTED, bed OCCUPIED)."""
    return get_success_data(
        api_client.complete_admission(admission_id, completer_headers or PROVIDER2))


def generate_invoice_for(resident_id, period_start="2026-06-01",
                         period_end="2026-06-11", due_date="2026-06-20"):
    """Generate a DRAFT invoice. Re-reads the resident so the OCC
    expected_resident_version is current. Returns the invoice."""
    resident = fresh_resident(resident_id)
    payload = create_invoice_generate_payload(
        resident["version"], period_start=period_start, period_end=period_end,
        due_date=due_date)
    return get_success_data(api_client.generate_invoice(resident_id, payload, PROVIDER))


def create_shift_for(home_id, caregiver_id, start_at, end_at, overnight_mode=None):
    """Schedule a shift. Re-reads the caregiver so the OCC
    expected_caregiver_version is current. Returns the shift."""
    caregiver = fresh_caregiver(caregiver_id)
    payload = create_shift_payload(home_id, caregiver_id, start_at, end_at,
                                   caregiver["version"])
    if overnight_mode is not None:
        payload["overnight_mode"] = overnight_mode
    return get_success_data(api_client.create_shift(payload, PROVIDER))


def record_payment(resident_id, invoice_id, amount_cents, method="CASH"):
    """Record a payment against an invoice. Returns the payment response data."""
    return get_success_data(
        api_client.create_payment(
            create_payment_payload(resident_id, invoice_id, amount_cents,
                                   method=method),
            PROVIDER))


# ─── Tier 1/2: Home in a given state ──────────────────

def create_provisional_home(capacity=4, **overrides):
    """A PROVISIONAL home with nothing else. Returns the home."""
    return create_home(licensed_bed_capacity=capacity, **overrides)


def create_licensed_home(capacity=4, bed_label="1A", medicaid_certified=None,
                         caregiver_awake=True, with_bed=True, with_caregiver=True,
                         **overrides):
    """A LICENSED home (bed + ACTIVE caregiver preconditions satisfied).
    Returns dict(home, bed, caregiver)."""
    home = create_home(licensed_bed_capacity=capacity, **overrides)
    bed = add_bed(home["id"], label=bed_label, medicaid_certified=medicaid_certified) \
        if with_bed else None
    caregiver = add_caregiver(home["id"], awake_overnight_qualified=caregiver_awake) \
        if with_caregiver else None
    home = license_home(home["id"])
    return {"home": home, "bed": bed, "caregiver": caregiver}


# ─── Tier 3: Resident lifecycle shortcuts ─────────────

def create_applicant(home_id, payer_type="PRIVATE_PAY", nursing_hours_per_week=2,
                     adl_dependency_score=1, care_plan=None, **resident_overrides):
    """A resident promoted to APPLICANT by a FINALIZED assessment.
    Returns dict(resident, assessment)."""
    resident = create_resident(home_id, payer_type=payer_type, **resident_overrides)
    asm_overrides = {
        "nursing_hours_per_week": nursing_hours_per_week,
        "adl_dependency_score": adl_dependency_score,
    }
    if care_plan is not None:
        asm_overrides["care_plan"] = care_plan
    assessment = create_and_finalize_assessment(resident["id"], **asm_overrides)
    return {"resident": fresh_resident(resident["id"]), "assessment": assessment}


def create_pending_admission_scenario(home_id, bed_id, payer_type="PRIVATE_PAY",
                                      nursing_hours_per_week=2, adl_dependency_score=1,
                                      expected_admission_date="2026-05-25",
                                      **resident_overrides):
    """APPLICANT resident + FINALIZED assessment + PENDING admission holding the bed.
    Returns dict(resident, assessment, admission)."""
    ctx = create_applicant(home_id, payer_type=payer_type,
                           nursing_hours_per_week=nursing_hours_per_week,
                           adl_dependency_score=adl_dependency_score,
                           **resident_overrides)
    admission = create_pending_admission(
        ctx["resident"]["id"], bed_id, ctx["assessment"]["id"],
        expected_admission_date=expected_admission_date)
    return {**ctx, "admission": admission}


def create_approved_admission_scenario(home_id, bed_id, **kwargs):
    """PENDING admission advanced to APPROVED by a second operator.
    Returns dict(resident, assessment, admission)."""
    ctx = create_pending_admission_scenario(home_id, bed_id, **kwargs)
    admission = approve_admission(ctx["admission"]["id"])
    return {**ctx, "admission": admission}


# ─── Tier 3 (full): the admitted-resident workhorse ───

def setup_admitted_resident(
    *,
    capacity=4,
    payer_type="PRIVATE_PAY",
    nursing_hours_per_week=2,
    adl_dependency_score=1,
    medicaid_certified=None,
    caregiver_awake=True,
    rates=None,
    admission_date="2026-05-25",
    complete_clock=None,
    initial_clock=SETUP_CLOCK,
    home_overrides=None,
    resident_overrides=None,
):
    """
    Full chain: clock -> home -> bed -> caregiver -> license -> [rate schedules]
    -> resident -> FINALIZED assessment -> PENDING admission -> APPROVED ->
    [clock] -> COMPLETED (resident ADMITTED, bed OCCUPIED).

    rates: None (no schedules), or a list of rate-schedule payload overrides.
    complete_clock: logical-clock instant at which the admission completes
    (becomes the resident's admitted_at). None = complete at initial_clock.

    Returns dict(home, bed, caregiver, resident, assessment, admission).
    """
    set_clock(initial_clock)
    ctx = create_licensed_home(capacity=capacity, medicaid_certified=medicaid_certified,
                               caregiver_awake=caregiver_awake,
                               **(home_overrides or {}))
    home, bed, caregiver = ctx["home"], ctx["bed"], ctx["caregiver"]
    for rate in (rates or []):
        publish_rate_schedule(home["id"], **rate)
    adm_ctx = create_approved_admission_scenario(
        home["id"], bed["id"], payer_type=payer_type,
        nursing_hours_per_week=nursing_hours_per_week,
        adl_dependency_score=adl_dependency_score,
        expected_admission_date=admission_date, **(resident_overrides or {}))
    if complete_clock is not None:
        set_clock(complete_clock)
    admission = complete_admission(adm_ctx["admission"]["id"])
    return {
        "home": fresh_home(home["id"]),
        "bed": fresh_bed(bed["id"]),
        "caregiver": caregiver,
        "resident": fresh_resident(adm_ctx["resident"]["id"]),
        "assessment": adm_ctx["assessment"],
        "admission": admission,
    }


def discharge_resident_now(resident_id, reason="VOLUNTARY", notice_days=30,
                           clock=None):
    """Discharge an ADMITTED resident (optionally after moving the clock).
    Returns the created DischargeRecord."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(
        api_client.discharge_resident(
            resident_id, create_discharge_payload(reason=reason,
                                                  notice_days=notice_days),
            PROVIDER))


# ─── Tier 2 (care): medication logging scenario ──────

def setup_med_logging_scenario(
    *,
    schedule_times=("08:00",),
    shift_windows=(("2026-06-02T13:00:00Z", "2026-06-03T05:00:00Z"),),
    initial_clock=SETUP_CLOCK,
    **admit_kwargs,
):
    """
    Admitted resident + ACTIVE medication order + caregiver holding SCHEDULED
    shifts covering the given windows. Returns the admitted-resident context
    plus order and shifts.
    """
    ctx = setup_admitted_resident(initial_clock=initial_clock, **admit_kwargs)
    order = get_success_data(
        api_client.create_medication_order(
            ctx["resident"]["id"],
            create_medication_order_payload(schedule_times=list(schedule_times)),
            NURSE))
    shifts = [
        create_shift_for(ctx["home"]["id"], ctx["caregiver"]["id"], start, end)
        for start, end in shift_windows
    ]
    return {**ctx, "order": order, "shifts": shifts}


# ─── Tier 3 (compliance): incident/case shortcuts ────

def file_incident(resident_id, occurred_at, severity="MAJOR",
                  incident_type="FALL", description="Reportable event",
                  headers=None):
    """File an incident (reported_at stamped from the logical clock)."""
    return get_success_data(
        api_client.create_incident(
            create_incident_payload(resident_id, occurred_at, severity=severity,
                                    incident_type=incident_type,
                                    description=description),
            headers or PROVIDER))


def setup_incident_with_case(severity="MAJOR", incident_type="FALL",
                             occurred_at="2026-06-01T06:00:00Z",
                             filed_clock="2026-06-01T12:00:00Z",
                             description="Reportable event", **admit_kwargs):
    """
    Admitted resident + an incident filed at filed_clock (on time by default)
    + compliance case opened (incident UNDER_REVIEW, case OPEN).
    Returns the admitted-resident context plus incident and case.
    """
    ctx = setup_admitted_resident(**admit_kwargs)
    set_clock(filed_clock)
    incident = file_incident(ctx["resident"]["id"], occurred_at,
                             severity=severity, incident_type=incident_type,
                             description=description)
    case = get_success_data(api_client.open_incident_case(incident["id"], PROVIDER))
    return {**ctx, "incident": incident, "case": case}


# ─── Tier 4 (billing): issued/paid invoice shortcuts ─

def setup_draft_invoice(*, period_start="2026-06-01", period_end="2026-06-02",
                        due_date="2026-06-20", rates=None, **admit_kwargs):
    """Admitted resident with a rate schedule and a freshly generated DRAFT
    invoice. Returns the admitted-resident context plus invoice."""
    if rates is None:
        rates = [{}]
    ctx = setup_admitted_resident(rates=rates, **admit_kwargs)
    invoice = generate_invoice_for(ctx["resident"]["id"], period_start=period_start,
                                   period_end=period_end, due_date=due_date)
    return {**ctx, "invoice": invoice}


def setup_issued_invoice(issue_clock=None, **kwargs):
    """DRAFT invoice advanced to ISSUED (clock optionally moved first)."""
    ctx = setup_draft_invoice(**kwargs)
    if issue_clock is not None:
        set_clock(issue_clock)
    invoice = get_success_data(api_client.issue_invoice(ctx["invoice"]["id"], PROVIDER))
    return {**ctx, "invoice": invoice}
