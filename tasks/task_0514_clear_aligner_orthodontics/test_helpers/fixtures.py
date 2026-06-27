"""Composite setup helpers.

These encapsulate the multi-step preambles that the test claims share. Every
fixture builds its preconditions from scratch (the server DB is empty before
each test) using only PRD-declared endpoints, and uses get_success_data() so a
setup failure surfaces as a clear "Setup failed" rather than a confusing
assertion failure.

Identity threading: Patient and Clinician are entity-backed roles. After a
fixture creates one, every ownership/assignment-gated call uses
make_patient_headers(patient_id) / make_clinician_headers(clinician_id) with the
real entity id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .test_users import (
    make_patient_headers, make_clinician_headers,
    make_manufacturing_headers, make_billing_headers,
)
from .factories import (
    create_patient_payload, create_clinician_payload, create_case_payload,
    create_intake_record_payload, create_plan_payload,
    create_financing_plan_payload, create_shipment_payload,
    create_checkin_payload, create_refinement_payload, create_refund_payload,
    create_retainer_payload,
)

MFG = make_manufacturing_headers()
BILLING = make_billing_headers()


# ─────────────────────────────────────────────────────────────────────────────
# Atomic creators
# ─────────────────────────────────────────────────────────────────────────────
def create_clinician(license_state_codes=None, role_type="DENTIST",
                     full_name="Dr Test", active=None):
    payload = create_clinician_payload(
        full_name=full_name,
        license_state_codes=license_state_codes or ["CA"],
        role_type=role_type,
    )
    if active is not None:
        payload["active"] = active
    return get_success_data(api_client.create_clinician(payload, BILLING))


def create_patient(state_code="CA", date_of_birth="1990-01-01",
                   email=None, full_name="Test Patient"):
    # Unique email per call to avoid the unique-across-Patient constraint.
    if email is None:
        email = f"p-{abs(hash((state_code, date_of_birth, full_name))) % 10_000_000}@x.com"
    payload = create_patient_payload(
        email=email, full_name=full_name,
        state_code=state_code, date_of_birth=date_of_birth,
    )
    return get_success_data(api_client.create_patient(payload, make_patient_headers("seed")))


def create_case(patient_id, intake_channel="IMPRESSION_KIT", list_price_cents=300000):
    payload = create_case_payload(
        patient_id, intake_channel=intake_channel, list_price_cents=list_price_cents,
    )
    return get_success_data(api_client.create_case(payload, make_patient_headers(patient_id)))


def add_usable_intake(case_id, patient_id, channel="IMPRESSION_KIT",
                      quality_score=0.9, tracking="TRK1", scan_state="CA"):
    if channel == "IMPRESSION_KIT":
        payload = create_intake_record_payload(
            channel=channel, quality_score=quality_score,
            kit_tracking_number=tracking, scan_clinic_state_code=None,
        )
        payload.pop("scan_clinic_state_code", None)
    else:
        payload = create_intake_record_payload(
            channel=channel, quality_score=quality_score,
            scan_clinic_state_code=scan_state,
        )
        payload.pop("kit_tracking_number", None)
    return get_success_data(
        api_client.create_intake_record(case_id, payload, make_patient_headers(patient_id))
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1/2: build a case up to a clinical-review posture
# ─────────────────────────────────────────────────────────────────────────────
def setup_case_under_review(state_code="CA", list_price_cents=300000,
                            intake_channel="IMPRESSION_KIT", clinician_states=None,
                            date_of_birth="1990-01-01", role_type="DENTIST"):
    """Clinician + patient + case + usable intake + submit-for-review.

    Returns dict with clinician, patient, case (after submit; UNDER_REVIEW) plus
    the threaded header builders.
    """
    clinician = create_clinician(
        license_state_codes=clinician_states or [state_code], role_type=role_type,
    )
    patient = create_patient(state_code=state_code, date_of_birth=date_of_birth)
    case = create_case(patient["id"], intake_channel, list_price_cents)
    add_usable_intake(case["id"], patient["id"], channel=intake_channel)
    get_success_data(
        api_client.submit_for_review(case["id"], make_patient_headers(patient["id"]))
    )
    case = get_success_data(api_client.get_case(case["id"], BILLING))
    return {
        "clinician": clinician,
        "patient": patient,
        "case": case,
        "clin_headers": make_clinician_headers(clinician["id"]),
        "pat_headers": make_patient_headers(patient["id"]),
    }


def setup_submitted_plan(proposed_step_count=10, weeks_per_step=2, discount_code=None,
                         state_code="CA", list_price_cents=300000,
                         intake_channel="IMPRESSION_KIT", role_type="DENTIST"):
    """Case UNDER_REVIEW + a SUBMITTED plan authored by the assigned clinician.

    Returns dict adding 'plan'.
    """
    ctx = setup_case_under_review(
        state_code=state_code, list_price_cents=list_price_cents,
        intake_channel=intake_channel, role_type=role_type,
    )
    plan_payload = create_plan_payload(
        ctx["case"]["id"], ctx["clinician"]["id"],
        proposed_step_count=proposed_step_count, weeks_per_step=weeks_per_step,
    )
    if discount_code is not None:
        plan_payload["discount_code"] = discount_code
    plan = get_success_data(api_client.create_plan(plan_payload, ctx["clin_headers"]))
    get_success_data(api_client.submit_plan(plan["id"], ctx["clin_headers"]))
    plan = get_success_data(api_client.get_plan(plan["id"], ctx["clin_headers"]))
    ctx["plan"] = plan
    return ctx


def setup_plan_approved(proposed_step_count=10, weeks_per_step=2, discount_code=None,
                        state_code="CA", list_price_cents=300000,
                        intake_channel="IMPRESSION_KIT", role_type="DENTIST"):
    """Case PLAN_APPROVED (plan APPROVED, steps generated, price computed).

    Returns dict adding 'plan' (APPROVED) and a refreshed 'case'.
    """
    ctx = setup_submitted_plan(
        proposed_step_count=proposed_step_count, weeks_per_step=weeks_per_step,
        discount_code=discount_code, state_code=state_code,
        list_price_cents=list_price_cents, intake_channel=intake_channel,
        role_type=role_type,
    )
    get_success_data(api_client.approve_plan(ctx["plan"]["id"], ctx["clin_headers"]))
    ctx["plan"] = get_success_data(api_client.get_plan(ctx["plan"]["id"], ctx["clin_headers"]))
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], BILLING))
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3/4: financing + activation
# ─────────────────────────────────────────────────────────────────────────────
def create_financing(case_id, term_months=12, down_payment_cents=0, apr_bps=0):
    """Create a PENDING_ACTIVATION financing plan. Returns the plan dict."""
    payload = create_financing_plan_payload(
        case_id, term_months=term_months,
        down_payment_cents=down_payment_cents, apr_bps=apr_bps,
    )
    return get_success_data(api_client.create_financing_plan(payload, BILLING))


def setup_financing_active(proposed_step_count=10, term_months=12,
                           down_payment_cents=0, apr_bps=0,
                           list_price_cents=300000, intake_channel="IMPRESSION_KIT",
                           discount_code=None):
    """Case PLAN_APPROVED + a financing plan activated (billing_state ACTIVE,
    installments generated). Returns dict adding 'financing' and refreshed 'case'.

    A down_payment_cents of None means "pay the full contracted total" — the
    PRD caps the down payment at total_contracted_cents, so callers that want a
    fully-settled case must not request more than the (tier-adjusted) contracted
    total. None resolves to the case's actual total_contracted_cents.
    """
    ctx = setup_plan_approved(
        proposed_step_count=proposed_step_count, list_price_cents=list_price_cents,
        intake_channel=intake_channel, discount_code=discount_code,
    )
    if down_payment_cents is None:
        down_payment_cents = ctx["case"]["total_contracted_cents"]
    fin = create_financing(
        ctx["case"]["id"], term_months=term_months,
        down_payment_cents=down_payment_cents, apr_bps=apr_bps,
    )
    get_success_data(api_client.activate_financing_plan(
        fin["id"], {"expected_financing_plan_version": fin["version"]}, BILLING,
    ))
    ctx["financing"] = get_success_data(api_client.get_financing_plan(fin["id"], BILLING))
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], BILLING))
    return ctx


def setup_case_active(proposed_step_count=10, list_price_cents=300000,
                      down_payment_cents=None, intake_channel="IMPRESSION_KIT",
                      discount_code=None):
    """Case ACTIVE: financing activated (full down payment by default) then case
    activated (step 1 -> IN_PRODUCTION). Returns dict with 'case', 'financing',
    'plan', and step list helpers via case id.

    down_payment_cents=None pays the full contracted total (which is tier- and
    discount-adjusted, not the raw list price), so the money side settles and
    the case can be activated.
    """
    ctx = setup_financing_active(
        proposed_step_count=proposed_step_count, list_price_cents=list_price_cents,
        down_payment_cents=down_payment_cents, intake_channel=intake_channel,
        discount_code=discount_code,
    )
    get_success_data(api_client.activate_case(ctx["case"]["id"], MFG))
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], BILLING))
    return ctx


def list_steps(case_id):
    """Return the case's aligner steps ordered as the API returns them
    (ascending created_at == step_index order)."""
    data, _meta = validate_paginated(api_client.list_case_aligner_steps(case_id, MFG))
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Manufacturing / shipment progression
# ─────────────────────────────────────────────────────────────────────────────
def ship_step(step_id, window_start, window_end, carrier_code="GROUND"):
    """complete-production (if needed must already be IN_PRODUCTION) is NOT done
    here; this helper books + dispatches a MANUFACTURED step. Returns shipment."""
    sh = get_success_data(api_client.create_shipment(
        create_shipment_payload(
            step_id, carrier_code=carrier_code,
            window_start=window_start, window_end=window_end,
        ), MFG,
    ))
    get_success_data(api_client.dispatch_shipment(sh["id"], MFG))
    return sh


def manufacture_and_ship_first_steps(case_id, n, start_day=2):
    """For an ACTIVE case, drive the first n first-run steps all the way to
    SHIPPED, in strict order. Step 1 is already IN_PRODUCTION after activation.

    Returns the (refreshed) list of step dicts.
    """
    steps = list_steps(case_id)
    day = start_day
    for i in range(n):
        step = steps[i]
        if i > 0:
            # predecessor already shipped below; start this one
            get_success_data(api_client.start_production(step["id"], MFG))
        get_success_data(api_client.complete_production(step["id"], MFG))
        ws = f"2026-05-{day:02d}T00:00:00Z"
        we = f"2026-05-{day + 1:02d}T00:00:00Z"
        ship_step(step["id"], ws, we, carrier_code="GROUND")
        day += 2
    return list_steps(case_id)


def setup_case_active_step1_manufactured(proposed_step_count=10, list_price_cents=300000,
                                         down_payment_cents=None):
    """Case ACTIVE with step 1 MANUFACTURED (not yet shipped); step 2 PLANNED.

    Returns dict adding 'steps' (current step list).
    down_payment_cents=None pays the full contracted total (tier-adjusted).
    """
    ctx = setup_case_active(
        proposed_step_count=proposed_step_count, list_price_cents=list_price_cents,
        down_payment_cents=down_payment_cents,
    )
    steps = list_steps(ctx["case"]["id"])
    get_success_data(api_client.complete_production(steps[0]["id"], MFG))
    ctx["steps"] = list_steps(ctx["case"]["id"])
    return ctx


def setup_case_active_step1_booked_ground(proposed_step_count=10,
                                          down_payment_cents=None,
                                          window_start="2026-05-02T00:00:00Z",
                                          window_end="2026-05-04T00:00:00Z",
                                          carrier_code="GROUND"):
    """Case ACTIVE, step 1 MANUFACTURED with one booked shipment in the given
    window (not dispatched). Returns dict adding 'steps' and 'shipment'.
    down_payment_cents=None pays the full contracted total (tier-adjusted).
    """
    ctx = setup_case_active_step1_manufactured(
        proposed_step_count=proposed_step_count, down_payment_cents=down_payment_cents,
    )
    s1 = ctx["steps"][0]
    sh = get_success_data(api_client.create_shipment(
        create_shipment_payload(
            s1["id"], carrier_code=carrier_code,
            window_start=window_start, window_end=window_end,
        ), MFG,
    ))
    ctx["shipment"] = sh
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Refinement helpers
# ─────────────────────────────────────────────────────────────────────────────
def add_assessed_checkin(case_id, patient_id, clinician_id, reported_step_index=1,
                         assessment="OFF_TRACK"):
    """Create a checkin and have the assigned clinician assess it. Returns checkin id."""
    chk = get_success_data(api_client.create_checkin(
        case_id, create_checkin_payload(reported_step_index=reported_step_index),
        make_patient_headers(patient_id),
    ))
    get_success_data(api_client.assess_checkin(
        chk["id"], {"tracking_assessment": assessment},
        make_clinician_headers(clinician_id),
    ))
    return chk["id"]


def setup_refinement_requested(assessment="OFF_TRACK", additional_step_count=2,
                               proposed_step_count=10, list_price_cents=300000):
    """Case ACTIVE with one assessed checkin and a REQUESTED refinement citing it.

    Returns dict adding 'checkin_id' and 'refinement'.
    """
    ctx = setup_case_active(
        proposed_step_count=proposed_step_count, down_payment_cents=None,
        list_price_cents=list_price_cents,
    )
    chk_id = add_assessed_checkin(
        ctx["case"]["id"], ctx["patient"]["id"], ctx["clinician"]["id"],
        assessment=assessment,
    )
    ref = get_success_data(api_client.create_refinement(
        create_refinement_payload(
            ctx["case"]["id"], chk_id, additional_step_count=additional_step_count,
        ),
        ctx["pat_headers"],
    ))
    ctx["checkin_id"] = chk_id
    ctx["refinement"] = ref
    return ctx


def setup_one_refinement_granted_resumed(proposed_step_count=10, list_price_cents=300000):
    """Case back to ACTIVE after one GRANTED+resumed refinement (refinement_count=1),
    with a second OFF_TRACK checkin and a second REQUESTED refinement.

    Returns dict adding 'second_refinement' (REQUESTED) and 'second_checkin_id'.
    """
    ctx = setup_refinement_requested(
        assessment="OFF_TRACK", additional_step_count=2,
        proposed_step_count=proposed_step_count, list_price_cents=list_price_cents,
    )
    get_success_data(api_client.grant_refinement(ctx["refinement"]["id"], ctx["clin_headers"]))
    get_success_data(api_client.resume_case(ctx["case"]["id"], MFG))
    chk2 = add_assessed_checkin(
        ctx["case"]["id"], ctx["patient"]["id"], ctx["clinician"]["id"],
        reported_step_index=2, assessment="OFF_TRACK",
    )
    ref2 = get_success_data(api_client.create_refinement(
        create_refinement_payload(ctx["case"]["id"], chk2, additional_step_count=2),
        ctx["pat_headers"],
    ))
    ctx["second_checkin_id"] = chk2
    ctx["second_refinement"] = ref2
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Completion / retainer
# ─────────────────────────────────────────────────────────────────────────────
def setup_completed_case(down_payment_cents=240000, list_price_cents=300000):
    """Single-step plan driven all the way to COMPLETED (step shipped, latest
    checkin ON_TRACK, case completed). Returns dict with COMPLETED 'case'.
    """
    ctx = setup_case_active(
        proposed_step_count=1, list_price_cents=list_price_cents,
        down_payment_cents=down_payment_cents,
    )
    steps = list_steps(ctx["case"]["id"])
    s1 = steps[0]
    get_success_data(api_client.complete_production(s1["id"], MFG))
    ship_step(s1["id"], "2026-05-02T00:00:00Z", "2026-05-03T00:00:00Z", "GROUND")
    add_assessed_checkin(
        ctx["case"]["id"], ctx["patient"]["id"], ctx["clinician"]["id"],
        assessment="ON_TRACK",
    )
    get_success_data(api_client.complete_case(ctx["case"]["id"], ctx["clin_headers"]))
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], BILLING))
    return ctx


def setup_active_retainer(cadence="QUARTERLY", per_shipment_fee_cents=5000):
    """COMPLETED case with an ACTIVE retainer. Returns dict adding 'retainer'."""
    ctx = setup_completed_case()
    ret = get_success_data(api_client.create_retainer(
        create_retainer_payload(
            ctx["case"]["id"], cadence=cadence,
            per_shipment_fee_cents=per_shipment_fee_cents,
        ),
        ctx["pat_headers"],
    ))
    ctx["retainer"] = ret
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Refund helpers
# ─────────────────────────────────────────────────────────────────────────────
def open_refund(case_id, reason="PATIENT_CANCEL", headers=None):
    """Read the case's current version, then open a refund against it. Returns
    the refund dict.
    """
    case = get_success_data(api_client.get_case(case_id, BILLING))
    payload = create_refund_payload(case_id, case["version"], reason=reason)
    return get_success_data(api_client.create_refund(payload, headers or BILLING))


def setup_refund_approved(reason="PATIENT_CANCEL", proposed_step_count=10,
                          down_payment_cents=None, list_price_cents=300000,
                          shipped_steps=0, discount_code=None):
    """Case ACTIVE (fully paid), optionally with some first-run steps shipped, and
    a refund of the given reason APPROVED. Returns dict adding 'refund' and
    refreshed 'case'.
    """
    ctx = setup_case_active(
        proposed_step_count=proposed_step_count, list_price_cents=list_price_cents,
        down_payment_cents=down_payment_cents, discount_code=discount_code,
    )
    if shipped_steps > 0:
        manufacture_and_ship_first_steps(ctx["case"]["id"], shipped_steps)
    refund = open_refund(ctx["case"]["id"], reason=reason)
    get_success_data(api_client.approve_refund(refund["id"], BILLING))
    ctx["refund"] = get_success_data(api_client.get_refund(refund["id"], BILLING))
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], BILLING))
    return ctx
