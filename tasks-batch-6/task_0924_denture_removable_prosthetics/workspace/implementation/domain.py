"""Derived fields, lazily-evaluated clock transitions, money recomputation and
the shared cascade fragments.
"""
import calc
import nav
import pconst
from store import db, now, touch
from util import ZERO, add_days, q2


# ===========================================================================
# CaseArch derived milestone fields
# ===========================================================================
def arch_completed_milestones(arch):
    rows = [
        r
        for r in nav.tryins_of_arch(arch)
        if r["approval_status"] == "APPROVED"
    ]
    return [r["milestone_kind"] for r in rows]


def arch_next_required_milestone(arch):
    completed = list(arch_completed_milestones(arch))
    for kind in arch.get("required_milestones") or []:
        if kind in completed:
            completed.remove(kind)
            continue
        return kind
    return None


def arch_remake_count(arch):
    return len(
        [
            r
            for r in nav.remake_requests_of_arch(arch)
            if r["authorization_status"] == "APPROVED"
        ]
    )


def arch_remake_request_count(arch):
    return len(
        [
            r
            for r in nav.remake_requests_of_arch(arch)
            if r["authorization_status"]
            in ("PENDING_APPROVAL", "APPROVED", "DENIED")
        ]
    )


# ===========================================================================
# Patient derived fields
# ===========================================================================
def patient_write_gate_active(patient):
    for plan in db.plans.values():
        if plan["patient_id"] == patient["id"] and plan["plan_status"] in (
            "DELINQUENT",
            "DEFAULTED",
        ):
            return True
    return False


def patient_delivered_prosthesis_count(patient):
    return len(
        [p for p in nav.prostheses_of_patient(patient["id"]) if not p["is_remake"]]
    )


def patient_last_frequency_anchor_at(patient):
    anchors = [
        p["frequency_anchor_at"]
        for p in nav.prostheses_of_patient(patient["id"])
        if p["frequency_anchor_at"] is not None
    ]
    return max(anchors) if anchors else None


# ===========================================================================
# PaymentPlan derived money
# ===========================================================================
def plan_paid_amount(plan):
    total = ZERO
    for row in nav.installments_of_plan(plan):
        if row["installment_status"] in ("PAID", "WAIVED"):
            total = total + row["amount"]
    return q2(total)


def plan_outstanding_amount(plan):
    return q2(plan["principal_amount"] - plan_paid_amount(plan))


def plan_missed_count(plan):
    return len(
        [
            r
            for r in nav.installments_of_plan(plan)
            if r["installment_status"] == "MISSED"
        ]
    )


# ===========================================================================
# Lazily-evaluated, clock-driven transitions (PRD 2.6, 3.6, 3.8)
# ===========================================================================
def refresh_prosthesis(prosthesis):
    """Re-evaluate the two parallel clock-driven axes on this appliance.

    Each axis moves independently; both share a single version bump because a
    row a request writes twice still advances by exactly 1 (PRD 2.4)."""
    clock = now()
    if prosthesis["warranty_status"] in ("IN_WARRANTY", "WARRANTY_CONSUMED"):
        if clock > prosthesis["warranty_expires_at"]:
            prosthesis["warranty_status"] = "WARRANTY_EXPIRED"
            touch(prosthesis)
    if prosthesis["recall_status"] == "RECALL_SCHEDULED":
        if clock >= prosthesis["recall_due_at"]:
            prosthesis["recall_status"] = "RECALL_DUE"
            touch(prosthesis)
    if prosthesis["recall_status"] == "RECALL_DUE":
        # FRICTION POINT (PRD 3.6): the overdue band is implemented as
        # INCLUSIVE of recall_due_at + RECALL_OVERDUE_GRACE_DAYS, matching the
        # recall_schedule banding rule and its declared precision note.
        overdue_at = add_days(
            prosthesis["recall_due_at"], pconst.RECALL_OVERDUE_GRACE_DAYS
        )
        if clock >= overdue_at:
            prosthesis["recall_status"] = "RECALL_OVERDUE"
            touch(prosthesis)
    return prosthesis


def refresh_predetermination(row):
    if row["determination_status"] in ("APPROVED", "ALTERNATE_BENEFIT"):
        if row["expires_at"] is not None and now() > row["expires_at"]:
            row["determination_status"] = "EXPIRED"
            touch(row)
    return row


def live_predetermination(case):
    """The predetermination gate of rung 30."""
    for row in nav.predeterminations_of_case(case):
        refresh_predetermination(row)
    for row in nav.predeterminations_of_case(case):
        if row["determination_status"] in ("APPROVED", "ALTERNATE_BENEFIT"):
            if row["expires_at"] is not None and row["expires_at"] > now():
                return row
    return None


# ===========================================================================
# calculation case_total_due -- the pinned nine-step order
# ===========================================================================
def case_pre_discount_responsibility(case):
    return _case_steps(case)[2]


def _case_steps(case):
    gross = case["fee_schedule_total"]

    rush_total = ZERO
    for lc in nav.labcases_of_case(case):
        if lc["lab_status"] in pconst.RUSH_COUNTING_LAB_STATUSES:
            rush_total = rush_total + lc["rush_fee_amount"]

    service_total = ZERO
    for svc in nav.services_of_case(case):
        if svc["service_status"] == "COMPLETED":
            service_total = service_total + svc["charge_amount"]
    for wc in nav.warranty_claims_of_case(case):
        if wc["claim_status"] == "PATIENT_FAULT":
            service_total = service_total + wc["patient_charge_amount"]

    billed = q2(gross + rush_total + service_total)

    insurance_paid = ZERO
    for cl in nav.claims_of_case(case):
        if cl["adjudication_status"] in ("PRIMARY_PAID", "SECONDARY_PAID", "CLOSED"):
            insurance_paid = insurance_paid + cl["plan_paid_amount"]
    insurance_paid = q2(insurance_paid)

    pre = q2(billed - insurance_paid)
    if pre < ZERO:
        pre = ZERO
    return billed, insurance_paid, pre


def recompute_case_totals(case):
    """Runs calculation case_total_due.  This is a pure money recomputation and
    deliberately does NOT advance ProsthesisCase.version: the declared version
    accounting attributes the bump to the transition that triggered it."""
    billed, insurance_paid, pre = _case_steps(case)
    rate = calc.prompt_pay_rate(pre)
    discount = ZERO
    for plan in nav.plans_of_case(case):
        if plan["plan_status"] in ("ACTIVE", "DELINQUENT") and plan["pay_in_full"]:
            discount = q2(pre * rate)
            break
    case["billed_amount"] = billed
    case["insurance_paid_amount"] = insurance_paid
    case["prompt_pay_discount_amount"] = discount
    case["patient_responsibility_amount"] = q2(pre - discount)
    return case


# ===========================================================================
# Case closure -- performed by the system, never invoked by a caller
# ===========================================================================
def maybe_close_case(case):
    if case is None or case["case_status"] != "DELIVERED":
        return case
    claims = nav.claims_of_case(case)
    for cl in claims:
        if cl["adjudication_status"] not in ("CLOSED", "DENIED", "REVERSED"):
            return case
    plans = nav.plans_of_case(case)
    if plans:
        for plan in plans:
            if plan["plan_status"] not in ("PAID_OFF", "SUPERSEDED"):
                return case
    else:
        if case["patient_responsibility_amount"] != ZERO:
            return case
    case["case_status"] = "CLOSED"
    for arch in nav.arches_of_case(case):
        if arch["arch_status"] == "DELIVERED":
            arch["arch_status"] = "ARCH_CLOSED"
            touch(arch)
    touch(case)
    return case


# ===========================================================================
# Shared cascade fragments
# ===========================================================================
def cancel_lab_case(lab_case):
    """Moving a lab case to CANCELLED also releases whatever bench-line and
    arch occupation it held -- occupation is derived from lab_status."""
    if lab_case["lab_status"] in ("QC_PASSED", "EXPIRED", "CANCELLED"):
        return False
    lab_case["lab_status"] = "CANCELLED"
    touch(lab_case)
    return True


def void_superseded_prosthesis(prosthesis):
    """Used by the remake cascade (link 3) and by a remake delivery."""
    changed = False
    if prosthesis["warranty_status"] in ("IN_WARRANTY", "WARRANTY_CONSUMED"):
        prosthesis["warranty_status"] = "WARRANTY_VOIDED"
        changed = True
    if prosthesis["recall_status"] in (
        "RECALL_SCHEDULED",
        "RECALL_DUE",
        "RECALL_OVERDUE",
    ):
        prosthesis["recall_status"] = "RECALL_CLOSED_SUPERSEDED"
        changed = True
    if changed:
        touch(prosthesis)
    return changed


def cure_or_settle_plan(plan):
    """Applied after an installment payment: cure the delinquency cycle first,
    then settle the plan when nothing is outstanding."""
    missed = plan_missed_count(plan)
    if plan["plan_status"] in ("DELINQUENT", "DEFAULTED") and missed == 0:
        plan["plan_status"] = "ACTIVE"
        touch(plan)
    if plan_outstanding_amount(plan) == ZERO:
        if plan["plan_status"] == "ACTIVE":
            plan["plan_status"] = "PAID_OFF"
            touch(plan)
        elif plan["plan_status"] == "DELINQUENT" and missed == 0:
            plan["plan_status"] = "PAID_OFF"
            touch(plan)
    return plan


def create_remake_request(
    arch, reason_code, requested_by_user_id, warranty_claim=None
):
    """The system mints requests of this shape for itself in two places: a
    rejected try-in and a recall closed for remake evaluation."""
    attempt = arch_remake_request_count(arch) + 1
    charge_basis = "CHARGEABLE"
    if warranty_claim is not None and warranty_claim["claim_status"] in (
        "CLINIC_FAULT",
        "LAB_FAULT",
    ):
        charge_basis = "NO_CHARGE"
    return db.create(
        "remake_requests",
        {
            "case_arch_id": arch["id"],
            "warranty_claim_id": warranty_claim["id"] if warranty_claim else None,
            "reason_code": reason_code,
            "requested_by_user_id": requested_by_user_id,
            "approved_by_user_id": None,
            "authorization_status": "PENDING_APPROVAL",
            "attempt_number": attempt,
            "charge_basis": charge_basis,
            "decided_at": None,
        },
    )


def create_claim_row(case, coverage_id):
    return db.create(
        "claims",
        {
            "case_id": case["id"],
            "coverage_id": coverage_id,
            "predetermination_id": None,
            "billed_amount": ZERO,
            "allowed_amount": ZERO,
            "adjudication_status": "DRAFT",
            "submission_target": "PRIMARY",
            "primary_paid_amount": ZERO,
            "secondary_paid_amount": ZERO,
            "plan_paid_amount": ZERO,
            "patient_responsibility_amount": ZERO,
            "cob_convention_applied": None,
            "submitted_at": None,
            "adjudicated_at": None,
            "reversed_at": None,
        },
    )


def create_service_row(prosthesis, service_type, status, lab_case_id=None,
                       is_emergency_repair=False):
    return db.create(
        "services",
        {
            "prosthesis_id": prosthesis["id"],
            "lab_case_id": lab_case_id,
            "service_type": service_type,
            "is_emergency_repair": is_emergency_repair,
            "service_status": status,
            "charge_basis": None,
            "charge_amount": ZERO,
            "completed_at": None,
            "voided_at": None,
        },
    )


def apply_lab_credit_to_plan(plan, applied):
    """calculation installment_reschedule -- remake cascade link 5 and link 6."""
    plan["principal_amount"] = q2(plan["principal_amount"] - applied)
    plan["applied_lab_credit_amount"] = q2(
        plan["applied_lab_credit_amount"] + applied
    )
    remaining = applied
    open_rows = [
        r
        for r in nav.installments_of_plan(plan)
        if r["installment_status"] in ("SCHEDULED", "MISSED")
    ]
    open_rows.sort(key=lambda r: r["sequence_number"], reverse=True)
    for row in open_rows:
        if remaining <= ZERO:
            break
        take = row["amount"] if row["amount"] < remaining else remaining
        row["amount"] = q2(row["amount"] - take)
        remaining = q2(remaining - take)
        if row["amount"] == ZERO:
            row["installment_status"] = "WAIVED"
        touch(row)
    touch(plan)
    if plan_outstanding_amount(plan) == ZERO and plan["plan_status"] in (
        "ACTIVE",
        "DELINQUENT",
    ):
        plan["plan_status"] = "PAID_OFF"
        touch(plan)
    return plan
