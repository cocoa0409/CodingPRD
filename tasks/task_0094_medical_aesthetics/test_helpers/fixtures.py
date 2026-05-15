"""Composite setup helpers — multi-step preambles tests can reuse.

The medical-aesthetics pipeline is long: SKU and room registration →
project draft → submit → approve to ON_SHELF → customer profile → KYC
→ plan draft → submit → sign-consent → approve (or countersign) →
appointment create → check-in → op start → consumables → op end →
follow-up reminders → feedback → adverse-event flow → installment
create → activate → payments → refund/default. Many test claims need
the system in a late-pipeline state; these helpers reach it.

IDENTITY THREADING — PRD §2.1:

- Customer is ENTITY-BACKED. X-User-ID is the acting Customer.id. Every
  ownership-gated Customer call (POST /plans/{id}/sign-consent, POST
  /followups/{id}/feedback, POST /installments/{id}/payments, PATCH
  /customers/{id}, GET /customers/{id}, GET /plans/{id}, GET
  /appointments/{id}, GET /followups/{id}, GET /installments/{id})
  MUST mint headers via make_customer_headers(customer["id"]) —
  never via the shared CUSTOMER_FALLBACK_ID constant.

- Physician roles (AttendingPhysician, SeniorPhysician) are technically
  opaque, but PRD §2.1 makes ownership rules: AttendingPhysician must
  equal TreatmentPlan.attending_physician_id, and SeniorPhysician must
  differ from it on countersign. Fixtures therefore mint headers per
  instance via make_attending_physician_headers(doctor_id) and
  make_senior_physician_headers(doctor_id).

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing
test assertion failure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ALLOWED_TERM_MONTHS,
    GRACE_DAYS,
    NO_SHOW_GRACE_MINUTES,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    create_appointment_payload,
    create_consumable_sku_payload,
    create_contraindication_rule_payload,
    create_customer_payload,
    create_installment_payload,
    create_plan_payload,
    create_project_payload,
    create_room_payload,
    dob_for_age,
    file_adverse_event_payload,
    followup_feedback_payload,
    installment_payment_payload,
    iso_now,
    iso_offset,
    iso_utc,
    op_record_consumables_payload,
    op_record_end_payload,
    op_record_incident_payload,
    op_record_key_step_payload,
    op_record_vitals_payload,
    patch_plan_payload,
    plan_item,
    random_suffix,
    refund_medical_event_payload,
    reschedule_appointment_payload,
    submit_kyc_payload,
    utcnow,
)
from .test_users import (
    ATTENDING_PHYSICIAN_ID,
    ATTENDING_PHYSICIAN_ID_ALT,
    CONSULTANT_ID,
    NURSE_ID,
    SENIOR_PHYSICIAN_ID,
    TEST_USERS,
    make_attending_physician_headers,
    make_consultant_headers,
    make_customer_headers,
    make_finance_officer_headers,
    make_medical_director_headers,
    make_nurse_headers,
    make_senior_physician_headers,
)


# ===========================================================================
# Clock — PRD §2.10 (MedicalDirector only)
# ===========================================================================
def advance_clock(seconds: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /_clock/advance with `seconds`. PRD §2.10 reserves this
    capability to MedicalDirector and triggers three sweeps:
    Appointment→NO_SHOW, FollowUp→MISSED, InstallmentPlan→IN_DEFAULT.
    """
    headers = headers or TEST_USERS["medical_director_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(seconds=int(seconds)), headers,
    )
    return get_success_data(resp)


def server_now_iso(headers: Optional[Dict[str, str]] = None) -> str:
    """Return the server's current logical-clock time as ISO 8601.

    Uses PRD §2.2: every response meta carries
    `api_request_timestamp` set to the server's logical-clock time.
    We invoke a cheap, side-effect-free GET (list_projects) to read it
    out. Required because PRD §2.10 advances a server-side logical
    clock that begins at an implementation-chosen epoch, NOT the
    test runner's wall clock. Tests that need scheduled_end + 60min
    to be crossed by `advance_clock` must therefore peg
    `scheduled_start` to this server time, not to `utcnow()`.
    """
    headers = headers or TEST_USERS["medical_director_headers"]
    resp = api_client.list_projects(headers, params={"limit": 1})
    body = resp.json()
    return body["meta"]["api_request_timestamp"]


# ===========================================================================
# Tier 1: Atomic create-and-progress helpers
# ===========================================================================
def create_consumable_sku(
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/consumable-skus — MedicalDirector only per PRD §3.1."""
    headers = headers or TEST_USERS["medical_director_headers"]
    resp = api_client.create_consumable_sku(
        create_consumable_sku_payload(**overrides), headers,
    )
    return get_success_data(resp)


def create_room(
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/rooms — MedicalDirector only per PRD §3.1."""
    headers = headers or TEST_USERS["medical_director_headers"]
    resp = api_client.create_room(create_room_payload(**overrides), headers)
    return get_success_data(resp)


def create_project_draft(
    *,
    sku_id: str,
    sku_id_secondary: Optional[str] = None,
    qualified_doctor_ids: Optional[List[str]] = None,
    pricing_tiers: Optional[List[Dict[str, Any]]] = None,
    bom: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/projects — Consultant or MedicalDirector per PRD §3.1.

    Returns a DRAFT Project with all required fields wired.
    """
    headers = headers or TEST_USERS["consultant_headers"]
    payload = create_project_payload(
        sku_id=sku_id,
        sku_id_secondary=sku_id_secondary,
        qualified_doctor_ids=qualified_doctor_ids or [ATTENDING_PHYSICIAN_ID],
        pricing_tiers=pricing_tiers,
        bom=bom,
        **overrides,
    )
    resp = api_client.create_project(payload, headers)
    return get_success_data(resp)


def submit_project(project_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["consultant_headers"]
    return get_success_data(api_client.submit_project(project_id, headers))


def approve_project(project_id: str,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["medical_director_headers"]
    return get_success_data(api_client.approve_project(project_id, headers))


def reject_project(project_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["medical_director_headers"]
    return get_success_data(api_client.reject_project(project_id, headers))


def take_project_off_shelf(
    project_id: str, headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["medical_director_headers"]
    return get_success_data(
        api_client.take_project_off_shelf(project_id, headers)
    )


def return_project_to_shelf(
    project_id: str, headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["medical_director_headers"]
    return get_success_data(
        api_client.return_project_to_shelf(project_id, headers)
    )


def create_on_shelf_project(
    *,
    sku_id: Optional[str] = None,
    category: str = "NON_SURGICAL",
    risk_level: str = "LOW",
    duration_minutes: int = 30,
    pricing_tiers: Optional[List[Dict[str, Any]]] = None,
    qualified_doctor_ids: Optional[List[str]] = None,
    bom: Optional[List[Dict[str, Any]]] = None,
    sku_kind: str = "CONSUMABLE",
    sku_requires_lot: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Full lifecycle: create SKU + project DRAFT → submit → approve.

    Returns (project, sku) where project.status == 'ON_SHELF'.

    Provide sku_id to reuse an existing SKU; otherwise a fresh
    CONSUMABLE SKU with requires_lot_tracking=True is registered.
    """
    if sku_id is None:
        sku = create_consumable_sku(
            kind=sku_kind, requires_lot_tracking=sku_requires_lot,
        )
        sku_id_value = sku["id"]
    else:
        sku = {"id": sku_id}
        sku_id_value = sku_id

    draft = create_project_draft(
        sku_id=sku_id_value,
        category=category,
        risk_level=risk_level,
        duration_minutes=duration_minutes,
        pricing_tiers=pricing_tiers,
        qualified_doctor_ids=qualified_doctor_ids,
        bom=bom,
    )
    submit_project(draft["id"])
    on_shelf = approve_project(draft["id"])
    return on_shelf, sku


# ===========================================================================
# Tier 1: Customer helpers
# ===========================================================================
def create_customer(
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/customers — Consultant only per PRD §3.2."""
    headers = headers or TEST_USERS["consultant_headers"]
    payload = create_customer_payload(**overrides)
    resp = api_client.create_customer(payload, headers)
    return get_success_data(resp)


def verify_customer_kyc(
    customer_id: str,
    *,
    credit_score: int = 750,
    kyc_status: str = "VERIFIED",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /aesthetics/customers/{id}/kyc — FinanceOfficer only per PRD §3.2."""
    headers = headers or TEST_USERS["finance_officer_headers"]
    payload = submit_kyc_payload(
        kyc_status=kyc_status, credit_score=int(credit_score),
    )
    return get_success_data(
        api_client.submit_kyc(customer_id, payload, headers)
    )


def create_kyc_verified_customer(
    *,
    credit_score: int = 750,
    **customer_overrides: Any,
) -> Dict[str, Any]:
    """Create customer + verify KYC. Returns the verified customer."""
    customer = create_customer(**customer_overrides)
    return verify_customer_kyc(
        customer["id"], credit_score=int(credit_score),
    )


# ===========================================================================
# Tier 2: Plan setup helpers
# ===========================================================================
def create_draft_plan(
    *,
    customer_id: str,
    items: List[Dict[str, Any]],
    attending_physician_id: str = ATTENDING_PHYSICIAN_ID,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/plans — Consultant only per PRD §3.3.

    Note that the consultant_id on the response will be set to the
    X-User-ID of the headers passed here. Edit calls in this fixture
    module use the same consultant_id so consultant-edit ownership
    checks pass.
    """
    headers = headers or TEST_USERS["consultant_headers"]
    payload = create_plan_payload(
        customer_id=customer_id,
        items=items,
        attending_physician_id=attending_physician_id,
        **overrides,
    )
    resp = api_client.create_plan(payload, headers)
    return get_success_data(resp)


def submit_plan(plan_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["consultant_headers"]
    return get_success_data(api_client.submit_plan(plan_id, headers))


def sign_consent(plan_id: str, customer_id: str) -> Dict[str, Any]:
    """POST /aesthetics/plans/{id}/sign-consent — Customer only.

    Per PRD §2.1 and §3.3, X-User-ID must equal the plan's customer_id.
    """
    return get_success_data(
        api_client.sign_consent(plan_id, make_customer_headers(customer_id))
    )


def approve_plan_via_attending(
    plan_id: str,
    *,
    attending_doctor_id: str = ATTENDING_PHYSICIAN_ID,
) -> Dict[str, Any]:
    """POST /aesthetics/plans/{id}/approve — AttendingPhysician only.

    Per PRD §3.3 X-User-ID must equal TreatmentPlan.attending_physician_id.
    """
    return get_success_data(
        api_client.approve_plan(
            plan_id, make_attending_physician_headers(attending_doctor_id),
        )
    )


def countersign_plan(
    plan_id: str,
    *,
    senior_doctor_id: str = SENIOR_PHYSICIAN_ID,
) -> Dict[str, Any]:
    """POST /aesthetics/plans/{id}/countersign — SeniorPhysician only.

    Per PRD §3.3 the acting SeniorPhysician id must differ from the
    plan's attending_physician_id.
    """
    return get_success_data(
        api_client.countersign_plan(
            plan_id, make_senior_physician_headers(senior_doctor_id),
        )
    )


def reject_plan(plan_id: str,
                attending_doctor_id: str = ATTENDING_PHYSICIAN_ID,
                ) -> Dict[str, Any]:
    """POST /aesthetics/plans/{id}/reject — AttendingPhysician only."""
    return get_success_data(
        api_client.reject_plan(
            plan_id, make_attending_physician_headers(attending_doctor_id),
        )
    )


def return_plan_to_draft(
    plan_id: str, headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["consultant_headers"]
    return get_success_data(
        api_client.return_plan_to_draft(plan_id, headers)
    )


def cancel_plan(plan_id: str,
                attending_doctor_id: str = ATTENDING_PHYSICIAN_ID,
                ) -> Dict[str, Any]:
    """POST /aesthetics/plans/{id}/cancel — AttendingPhysician only."""
    return get_success_data(
        api_client.cancel_plan(
            plan_id, make_attending_physician_headers(attending_doctor_id),
        )
    )


# ===========================================================================
# Tier 3: Full plan-lifecycle setups
# ===========================================================================
def setup_approved_plan_simple(
    *,
    num_items: int = 1,
    base_price_cents: int = 100000,
    category: str = "NON_SURGICAL",
    risk_level: str = "LOW",
    duration_minutes: int = 30,
    customer_overrides: Optional[Dict[str, Any]] = None,
    attending_doctor_id: str = ATTENDING_PHYSICIAN_ID,
    sku_kind: str = "CONSUMABLE",
    sku_requires_lot: bool = True,
) -> Dict[str, Any]:
    """End-to-end: SKU → project → customer (KYC verified) → DRAFT plan
    → SUBMITTED → consent signed → APPROVED. Returns a dict with the
    keys: sku, project, customer, plan.

    For num_items >= 3 the final_total_cents reflects the 5% promo per
    PRD §3.3. For num_items < 3 no promo applies.
    """
    customer_overrides = customer_overrides or {}
    # 1) SKU + project ON_SHELF
    project, sku = create_on_shelf_project(
        category=category, risk_level=risk_level,
        duration_minutes=duration_minutes,
        pricing_tiers=[
            {"tier_code": "T0",
             "base_price_cents": int(base_price_cents),
             "min_quantity": 1},
        ],
        qualified_doctor_ids=[attending_doctor_id],
        sku_kind=sku_kind,
        sku_requires_lot=sku_requires_lot,
    )

    # 2) Customer + KYC verified (so installment activation is possible
    # downstream when tests need it).
    customer = create_kyc_verified_customer(
        age_years=customer_overrides.pop("age_years", 30),
        **customer_overrides,
    )

    # 3) DRAFT plan with `num_items` separate ON_SHELF projects.
    # When num_items > 1 we reuse the same project to keep the setup
    # cheap. PRD §3.3 items.project_id may repeat — items length 1..10
    # is the only collection-shape rule.
    items = [plan_item(project["id"], "T0", 1) for _ in range(num_items)]
    plan = create_draft_plan(
        customer_id=customer["id"], items=items,
        attending_physician_id=attending_doctor_id,
    )

    # 4) Submit (DRAFT → SUBMITTED).
    plan = submit_plan(plan["id"])

    # 5) Customer signs consent (self-loop on SUBMITTED).
    plan = sign_consent(plan["id"], customer["id"])

    # 6) Attending approves (SUBMITTED → APPROVED).
    plan = approve_plan_via_attending(
        plan["id"], attending_doctor_id=attending_doctor_id,
    )

    return {
        "sku": sku,
        "project": project,
        "customer": customer,
        "plan": plan,
        "attending_doctor_id": attending_doctor_id,
    }


def setup_approved_plan_three_items_promo(
    *, base_price_cents: int = 100000,
) -> Dict[str, Any]:
    """Three distinct ON_SHELF projects each priced base_price_cents, in
    one APPROVED plan. PRD §3.3 promo rule: items.length >= 3 triggers
    the 5% discount on final_total_cents.
    """
    sku = create_consumable_sku(
        kind="CONSUMABLE", requires_lot_tracking=True,
    )
    projects: List[Dict[str, Any]] = []
    for _ in range(3):
        p, _ = create_on_shelf_project(
            sku_id=sku["id"],
            category="NON_SURGICAL",
            risk_level="LOW",
            duration_minutes=30,
            pricing_tiers=[
                {"tier_code": "T0",
                 "base_price_cents": int(base_price_cents),
                 "min_quantity": 1},
            ],
            qualified_doctor_ids=[ATTENDING_PHYSICIAN_ID],
        )
        projects.append(p)

    customer = create_kyc_verified_customer(age_years=30)
    items = [plan_item(p["id"], "T0", 1) for p in projects]
    plan = create_draft_plan(
        customer_id=customer["id"], items=items,
        attending_physician_id=ATTENDING_PHYSICIAN_ID,
    )
    plan = submit_plan(plan["id"])
    plan = sign_consent(plan["id"], customer["id"])
    plan = approve_plan_via_attending(plan["id"])
    return {
        "sku": sku,
        "projects": projects,
        "customer": customer,
        "plan": plan,
        "attending_doctor_id": ATTENDING_PHYSICIAN_ID,
    }


def setup_draft_plan(
    *,
    num_items: int = 1,
    base_price_cents: int = 100000,
    category: str = "NON_SURGICAL",
    risk_level: str = "LOW",
    customer_overrides: Optional[Dict[str, Any]] = None,
    attending_doctor_id: str = ATTENDING_PHYSICIAN_ID,
) -> Dict[str, Any]:
    """Build a DRAFT plan (no submit). Returns dict with sku, project,
    customer, plan keys."""
    customer_overrides = customer_overrides or {}
    project, sku = create_on_shelf_project(
        category=category, risk_level=risk_level,
        pricing_tiers=[
            {"tier_code": "T0",
             "base_price_cents": int(base_price_cents),
             "min_quantity": 1},
        ],
        qualified_doctor_ids=[attending_doctor_id],
    )
    customer = create_kyc_verified_customer(
        age_years=customer_overrides.pop("age_years", 30),
        **customer_overrides,
    )
    items = [plan_item(project["id"], "T0", 1) for _ in range(num_items)]
    plan = create_draft_plan(
        customer_id=customer["id"], items=items,
        attending_physician_id=attending_doctor_id,
    )
    return {
        "sku": sku,
        "project": project,
        "customer": customer,
        "plan": plan,
        "attending_doctor_id": attending_doctor_id,
    }


def setup_submitted_plan_no_consent(**kwargs: Any) -> Dict[str, Any]:
    """DRAFT → SUBMITTED but consent NOT yet signed. Used for
    ERR_CONSENT_NOT_SIGNED tests at the approve gate."""
    ctx = setup_draft_plan(**kwargs)
    ctx["plan"] = submit_plan(ctx["plan"]["id"])
    return ctx


def setup_rejected_plan_no_consent(**kwargs: Any) -> Dict[str, Any]:
    """DRAFT → SUBMITTED → REJECTED. PRD §3.3: reject is terminal.
    Consent was never signed. Used for the priority-pair test
    (state vs consent) — calling /approve again on a REJECTED plan
    must yield ERR_INVALID_STATE (priority 5) which is the state gate,
    not ERR_CONSENT_NOT_SIGNED (priority 11).
    """
    ctx = setup_submitted_plan_no_consent(**kwargs)
    ctx["plan"] = reject_plan(
        ctx["plan"]["id"],
        attending_doctor_id=ctx["attending_doctor_id"],
    )
    return ctx


def setup_high_risk_plan_submitted(
    *, base_price_cents: int = 100000,
) -> Dict[str, Any]:
    """A SUBMITTED plan whose only project has risk_level=HIGH.
    PRD §3.3: HIGH risk_level triggers requires_senior_countersign.
    """
    return setup_submitted_plan_no_consent(
        risk_level="HIGH",
        base_price_cents=base_price_cents,
    )


# ===========================================================================
# Tier 4: Appointment helpers
# ===========================================================================
def create_appointment(
    *,
    plan_id: str,
    project_id: str,
    scheduled_start_iso: str,
    room_id: str,
    doctor_id: str = ATTENDING_PHYSICIAN_ID,
    nurse_id: str = NURSE_ID,
    equipment_ids: Optional[List[str]] = None,
    anesthesia_resource_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/appointments — Consultant only per PRD §3.4."""
    headers = headers or TEST_USERS["consultant_headers"]
    payload = create_appointment_payload(
        plan_id=plan_id,
        project_id=project_id,
        scheduled_start=scheduled_start_iso,
        doctor_id=doctor_id,
        nurse_id=nurse_id,
        room_id=room_id,
        equipment_ids=equipment_ids or [f"eq-{random_suffix(4)}"],
        anesthesia_resource_id=anesthesia_resource_id,
        **overrides,
    )
    return get_success_data(api_client.create_appointment(payload, headers))


def setup_scheduled_appointment(
    *,
    category: str = "NON_SURGICAL",
    risk_level: str = "LOW",
    duration_minutes: int = 30,
    days_ahead: int = 7,
    anesthesia: bool = False,
    base_price_cents: int = 100000,
) -> Dict[str, Any]:
    """End-to-end: approved plan → room → appointment SCHEDULED.

    Returns dict with sku, project, customer, plan, room,
    appointment, doctor_id, nurse_id.
    """
    bundle = setup_approved_plan_simple(
        category=category,
        risk_level=risk_level,
        duration_minutes=duration_minutes,
        base_price_cents=base_price_cents,
    )
    plan = bundle["plan"]
    room_kind = "SURGICAL_OR" if category == "SURGICAL" else "PROCEDURE"
    room = create_room(room_kind=room_kind)
    anesthesia_resource = None
    if category == "SURGICAL" or anesthesia:
        anesthesia_resource = f"anes-{random_suffix(4)}"

    start = utcnow() + timedelta(days=days_ahead)
    # round to a whole minute
    start = start.replace(second=0, microsecond=0)
    appt = create_appointment(
        plan_id=plan["id"],
        project_id=bundle["project"]["id"],
        scheduled_start_iso=iso_utc(start),
        room_id=room["id"],
        doctor_id=bundle["attending_doctor_id"],
        nurse_id=NURSE_ID,
        equipment_ids=[f"eq-{random_suffix(4)}"],
        anesthesia_resource_id=anesthesia_resource,
    )
    bundle.update({
        "room": room,
        "appointment": appt,
        "doctor_id": bundle["attending_doctor_id"],
        "nurse_id": NURSE_ID,
    })
    return bundle


# ===========================================================================
# Tier 5: Adverse event helpers
# ===========================================================================
def file_adverse_event(
    *,
    appointment_id: str,
    severity: str = "MINOR",
    description: str = "Test AE",
    headers: Optional[Dict[str, str]] = None,
    actor_doctor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /aesthetics/adverse-events. PRD §3.6: open to
    AttendingPhysician or Nurse."""
    if headers is None:
        if actor_doctor_id is not None:
            headers = make_attending_physician_headers(actor_doctor_id)
        else:
            headers = TEST_USERS["attending_physician_headers"]
    payload = file_adverse_event_payload(
        appointment_id=appointment_id,
        severity=severity,
        description=description,
    )
    return get_success_data(api_client.file_adverse_event(payload, headers))


def escalate_adverse_event(
    ae_id: str,
    *,
    actor_doctor_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if headers is None:
        if actor_doctor_id is not None:
            headers = make_attending_physician_headers(actor_doctor_id)
        else:
            headers = TEST_USERS["attending_physician_headers"]
    return get_success_data(api_client.escalate_adverse_event(ae_id, headers))


# ===========================================================================
# Tier 5: Installment helpers
# ===========================================================================
def create_installment_plan(
    *,
    treatment_plan_id: str,
    downpayment_cents: int = 0,
    term_months: int = 6,
    finance_partner_id: str = "FP1",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["finance_officer_headers"]
    payload = create_installment_payload(
        treatment_plan_id=treatment_plan_id,
        downpayment_cents=int(downpayment_cents),
        term_months=int(term_months),
        finance_partner_id=finance_partner_id,
    )
    return get_success_data(api_client.create_installment(payload, headers))


def activate_installment_plan(
    installment_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["finance_officer_headers"]
    return get_success_data(
        api_client.activate_installment(installment_id, headers)
    )


def pay_installment(
    installment_id: str,
    *,
    amount_cents: int,
    customer_id: Optional[str] = None,
    external_ref: str = "ref-001",
    prepay: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /aesthetics/installments/{id}/payments — Customer or
    FinanceOfficer per PRD §3.7. When `customer_id` is supplied the
    headers are minted with make_customer_headers so the ownership
    check passes.
    """
    if headers is None:
        if customer_id is not None:
            headers = make_customer_headers(customer_id)
        else:
            headers = TEST_USERS["finance_officer_headers"]
    payload = installment_payment_payload(
        amount_cents=int(amount_cents),
        external_ref=external_ref,
        prepay=prepay,
    )
    return get_success_data(
        api_client.pay_installment(installment_id, payload, headers)
    )


def setup_active_installment(
    *,
    term_months: int = 3,
    base_price_cents: int = 30000,
    downpayment_cents: int = 0,
    credit_score: int = 800,
) -> Dict[str, Any]:
    """APPROVED plan → CreateInstallmentPlan → activate (PENDING_KYC →
    ACTIVE). Returns dict with sku, project, customer, plan, installment,
    attending_doctor_id.

    The KYC step inside setup_approved_plan_simple sets credit_score=750
    by default; override via `credit_score` to test boundary cases for
    activation gating (PRD §3.7 MIN_CREDIT_SCORE table).
    """
    bundle = setup_approved_plan_simple(
        num_items=1,
        base_price_cents=int(base_price_cents),
    )
    # Override the customer's credit_score by re-running KYC.
    verify_customer_kyc(
        bundle["customer"]["id"], credit_score=int(credit_score),
    )
    inst = create_installment_plan(
        treatment_plan_id=bundle["plan"]["id"],
        downpayment_cents=int(downpayment_cents),
        term_months=int(term_months),
    )
    inst = activate_installment_plan(inst["id"])
    bundle["installment"] = inst
    return bundle


# ===========================================================================
# Catalog / customer listing helpers
# ===========================================================================
def list_projects(headers: Optional[Dict[str, str]] = None,
                  params: Optional[Dict[str, Any]] = None,
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["medical_director_headers"]
    return get_success_data(api_client.list_projects(headers, params=params))


def list_audit_entries(
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    action: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["medical_director_headers"]
    params: Dict[str, Any] = {"limit": int(limit)}
    if subject_type is not None:
        params["subject_type"] = subject_type
    if subject_id is not None:
        params["subject_id"] = subject_id
    if action is not None:
        params["action"] = action
    resp = api_client.list_audit_entries(headers, params=params)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return data if data is not None else []


def list_sync_events(
    *,
    topic: Optional[str] = None,
    kind: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["medical_director_headers"]
    params: Dict[str, Any] = {"limit": int(limit)}
    if topic is not None:
        params["topic"] = topic
    if kind is not None:
        params["kind"] = kind
    resp = api_client.list_sync_events(headers, params=params)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return data if data is not None else []


def get_plan(plan_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["consultant_headers"]
    return get_success_data(api_client.get_plan(plan_id, headers))


def get_appointment(
    appointment_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["consultant_headers"]
    return get_success_data(
        api_client.get_appointment(appointment_id, headers)
    )


def get_installment(installment_id: str,
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["finance_officer_headers"]
    return get_success_data(api_client.get_installment(installment_id, headers))


def get_customer(customer_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["consultant_headers"]
    return get_success_data(api_client.get_customer(customer_id, headers))


def list_adverse_events(
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["attending_physician_headers"]
    return get_success_data(
        api_client.list_adverse_events(headers, params=params)
    )


__all__ = [
    "advance_clock",
    "server_now_iso",
    "create_consumable_sku",
    "create_room",
    "create_project_draft",
    "submit_project",
    "approve_project",
    "reject_project",
    "take_project_off_shelf",
    "return_project_to_shelf",
    "create_on_shelf_project",
    "create_customer",
    "verify_customer_kyc",
    "create_kyc_verified_customer",
    "create_draft_plan",
    "submit_plan",
    "sign_consent",
    "approve_plan_via_attending",
    "countersign_plan",
    "reject_plan",
    "return_plan_to_draft",
    "cancel_plan",
    "setup_approved_plan_simple",
    "setup_approved_plan_three_items_promo",
    "setup_draft_plan",
    "setup_submitted_plan_no_consent",
    "setup_rejected_plan_no_consent",
    "setup_high_risk_plan_submitted",
    "create_appointment",
    "setup_scheduled_appointment",
    "file_adverse_event",
    "escalate_adverse_event",
    "create_installment_plan",
    "activate_installment_plan",
    "pay_installment",
    "setup_active_installment",
    "list_projects",
    "list_audit_entries",
    "list_sync_events",
    "get_plan",
    "get_appointment",
    "get_installment",
    "get_customer",
    "list_adverse_events",
]
