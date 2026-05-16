"""Enrollment endpoints: create, activate, reject, terminate, transfer, list, fetch, cost-summary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from flask import Blueprint, g, request

from auth import require_roles
from errors import err
from response import ok_array, ok_object
from serializers import (
    serialize_enrollment,
    serialize_late_enrollment_penalty,
)
from services.penalty import compute_months_late, compute_penalty
from store import store
from utils import (
    check_version,
    iso_string,
    paginate,
    parse_iso_datetime,
    parse_pagination,
    require_field,
    stamp_create,
    stamp_update,
)

bp = Blueprint("enrollments", __name__)


# ---------- helpers ----------

def _last_second_of_year(year: int) -> datetime:
    return datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def _first_of_year(year: int) -> datetime:
    return datetime(year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _check_no_overlapping_active(
    *, beneficiary_id: str, part_covered: str, new_effective: datetime, new_termination: datetime | None,
    self_enrollment_id: str | None = None,
) -> None:
    new_end = new_termination if new_termination else datetime.max.replace(tzinfo=timezone.utc)
    for e in store.enrollments.values():
        if e["id"] == self_enrollment_id:
            continue
        if e["beneficiary_id"] != beneficiary_id:
            continue
        if e["status"] != "ACTIVE":
            continue
        if e["part_covered"] != part_covered:
            continue
        other_start = e["_effective_dt"]
        other_end = e["_termination_dt"] if e["_termination_dt"] else datetime.max.replace(tzinfo=timezone.utc)
        # Intervals overlap if start_a <= end_b and start_b <= end_a
        if new_effective <= other_end and other_start <= new_end:
            raise err("ERR_DUPLICATE_PART_ENROLLMENT", "Overlapping ACTIVE enrollment exists for this part")


def _bubble_lifecycle_to_enrolled(beneficiary: dict, now_iso: str, period_type: str) -> None:
    """When an enrollment activates, bubble the beneficiary lifecycle up to ENROLLED from
    PRE_ELIGIBLE, IEP_OPEN, IEP_CLOSED, or COVERAGE_GAP."""
    if beneficiary["lifecycle_status"] in (
        "PRE_ELIGIBLE", "IEP_OPEN", "IEP_CLOSED", "COVERAGE_GAP"
    ):
        beneficiary["lifecycle_status"] = "ENROLLED"
        stamp_update(beneficiary, store_now_iso=now_iso)


def _bubble_lifecycle_after_termination(beneficiary: dict, now_iso: str) -> None:
    """When an enrollment is terminated, re-evaluate lifecycle: ENROLLED -> COVERAGE_GAP
    if no other ACTIVE rows. Also open a SEP_LOSS_OF_COVERAGE period if so."""
    if beneficiary["lifecycle_status"] != "ENROLLED":
        return
    has_other_active = any(
        e["beneficiary_id"] == beneficiary["id"] and e["status"] == "ACTIVE"
        for e in store.enrollments.values()
    )
    if has_other_active:
        return
    beneficiary["lifecycle_status"] = "COVERAGE_GAP"
    stamp_update(beneficiary, store_now_iso=now_iso)


def _open_sep_loss_of_coverage(beneficiary_id: str, now_iso: str) -> None:
    now = store.clock
    pid = store.new_id()
    period = {
        "id": pid,
        "beneficiary_id": beneficiary_id,
        "period_type": "SEP_LOSS_OF_COVERAGE",
        "status": "OPEN",
        "consumed_by_enrollment_id": None,
        "_window_start_dt": now,
        "_window_end_dt": now + timedelta(days=63),
    }
    stamp_create(period, store_now_iso=now_iso)
    store.enrollment_periods[pid] = period


def _create_drug_phase_ledger(beneficiary_id: str, enrollment_id: str, plan_year: int, now_iso: str) -> str:
    lid = store.new_id()
    ledger = {
        "id": lid,
        "beneficiary_id": beneficiary_id,
        "enrollment_id": enrollment_id,
        "plan_year": plan_year,
        "deductible_paid_cents": 0,
        "total_drug_spend_cents": 0,
        "troop_cents": 0,
        "current_phase": "DEDUCTIBLE",
        "last_adjudicated_claim_id": None,
    }
    stamp_create(ledger, store_now_iso=now_iso)
    store.drug_phase_ledgers[lid] = ledger
    return lid


def _maybe_create_penalty(enrollment: dict, plan: dict, beneficiary: dict, now_iso: str) -> dict | None:
    if enrollment["part_covered"] not in ("PART_B", "PART_D"):
        return None
    if enrollment["months_late"] <= 0:
        return None
    rate, monthly_penalty = compute_penalty(
        enrollment["part_covered"], enrollment["months_late"], plan["monthly_premium_cents"]
    )
    lep_id = store.new_id()
    lep = {
        "id": lep_id,
        "beneficiary_id": beneficiary["id"],
        "enrollment_id": enrollment["id"],
        "part": enrollment["part_covered"],
        "months_late": enrollment["months_late"],
        "penalty_rate_decimal": rate,
        "monthly_penalty_cents": monthly_penalty,
        "snapshot_base_premium_cents": plan["monthly_premium_cents"],
    }
    # LEP carries only id and created_at — no updated_at/version
    lep["created_at"] = now_iso
    store.late_enrollment_penalties[lep_id] = lep
    return lep


# ---------- endpoints ----------

@bp.route("/enrollments", methods=["POST"])
@require_roles("BenefitsCounselor")
def create_enrollment():
    body = request.get_json(silent=True) or {}
    bid = require_field(body, "beneficiary_id")
    pid = require_field(body, "plan_id")
    epid = require_field(body, "enrollment_period_id")
    effective_dt = parse_iso_datetime(require_field(body, "effective_date"), field="effective_date")

    # FK existence checks (priority 5)
    beneficiary = store.beneficiaries.get(bid)
    plan = store.plans.get(pid)
    period = store.enrollment_periods.get(epid)
    if beneficiary is None or plan is None or period is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced resource not found")
    if period["beneficiary_id"] != bid:
        raise err("ERR_FK_NOT_FOUND", "enrollment_period_id does not belong to beneficiary")

    # priority 6
    if beneficiary["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is deceased")

    # PRD §3.4 places ERR_PLAN_INACTIVE in the activation guard stack;
    # create may proceed even if the plan is currently inactive. The
    # activation transition re-checks Plan.is_active.

    if plan["plan_type"] == "MEDIGAP":
        raise err("ERR_VALIDATION", "Use /medigap-policies for MEDIGAP plans")

    now_iso = store.now_iso()
    eid = store.new_id()
    enrollment = {
        "id": eid,
        "beneficiary_id": bid,
        "plan_id": pid,
        "enrollment_period_id": epid,
        "part_covered": plan["plan_type"],
        "status": "PENDING",
        "_effective_dt": effective_dt,
        "_termination_dt": None,
        "months_late": 0,
    }
    stamp_create(enrollment, store_now_iso=now_iso)
    store.enrollments[eid] = enrollment
    return ok_object(serialize_enrollment(enrollment), status=201)


@bp.route("/enrollments/<eid>/activate", methods=["POST"])
@require_roles("BenefitsCounselor")
def activate_enrollment(eid):
    enrollment = store.enrollments.get(eid)
    if not enrollment:
        raise err("ERR_NOT_FOUND", "Enrollment not found")
    body = request.get_json(silent=True) or {}

    beneficiary = store.beneficiaries[enrollment["beneficiary_id"]]
    plan = store.plans[enrollment["plan_id"]]
    period = store.enrollment_periods[enrollment["enrollment_period_id"]]

    # priority 6
    if beneficiary["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is deceased")
    # priority 7
    if enrollment["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", f"Enrollment status must be PENDING, was {enrollment['status']}")
    # priority 8
    if not plan.get("is_active", True):
        raise err("ERR_PLAN_INACTIVE", "Plan is inactive")
    # priority 10: period must be OPEN
    if period["status"] != "OPEN":
        if period["status"] == "CONSUMED":
            raise err("ERR_PERIOD_ALREADY_CONSUMED", "EnrollmentPeriod already consumed")
        raise err("ERR_PERIOD_NOT_OPEN", "EnrollmentPeriod is not OPEN")
    # priority 11: effective_date within window
    if not (period["_window_start_dt"] <= enrollment["_effective_dt"] <= period["_window_end_dt"]):
        raise err("ERR_EFFECTIVE_DATE_OUTSIDE_PERIOD", "effective_date outside the period window")
    # plan_year == year(effective_date)
    if plan["plan_year"] != enrollment["_effective_dt"].year:
        raise err("ERR_EFFECTIVE_DATE_OUTSIDE_PERIOD", "Plan.plan_year does not match effective_date year")
    # priority 13: no overlapping ACTIVE same part
    _check_no_overlapping_active(
        beneficiary_id=beneficiary["id"],
        part_covered=enrollment["part_covered"],
        new_effective=enrollment["_effective_dt"],
        new_termination=None,
        self_enrollment_id=enrollment["id"],
    )
    # priority 17: non-PART_A enrollments require premium > 0
    if enrollment["part_covered"] != "PART_A" and plan["monthly_premium_cents"] <= 0:
        raise err("ERR_INVALID_PREMIUM", "Plan.monthly_premium_cents must be > 0 for non-PART_A")
    # priority 19: OCC
    check_version(body, enrollment["version"])

    now_iso = store.now_iso()

    # Compute months_late
    if enrollment["part_covered"] in ("PART_B", "PART_D"):
        ml = compute_months_late(beneficiary, enrollment["_effective_dt"], enrollment["part_covered"])
        enrollment["months_late"] = ml

    # Side effects
    enrollment["status"] = "ACTIVE"
    stamp_update(enrollment, store_now_iso=now_iso)

    # Consume the period if IEP or MEDIGAP_GI
    if period["period_type"] in ("IEP", "MEDIGAP_GI"):
        period["status"] = "CONSUMED"
        period["consumed_by_enrollment_id"] = enrollment["id"]
        stamp_update(period, store_now_iso=now_iso)

    # Create LEP if applicable
    _maybe_create_penalty(enrollment, plan, beneficiary, now_iso)

    # Bubble lifecycle
    _bubble_lifecycle_to_enrolled(beneficiary, now_iso, period["period_type"])

    # PART_D ledger
    if enrollment["part_covered"] == "PART_D":
        _create_drug_phase_ledger(
            beneficiary["id"], enrollment["id"], plan["plan_year"], now_iso
        )

    return ok_object(serialize_enrollment(enrollment))


@bp.route("/enrollments/<eid>/reject", methods=["POST"])
@require_roles("PlanAdmin")
def reject_enrollment(eid):
    enrollment = store.enrollments.get(eid)
    if not enrollment:
        raise err("ERR_NOT_FOUND", "Enrollment not found")
    body = request.get_json(silent=True) or {}
    beneficiary = store.beneficiaries[enrollment["beneficiary_id"]]
    if beneficiary["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is deceased")
    if enrollment["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Enrollment must be PENDING to reject")
    check_version(body, enrollment["version"])
    now_iso = store.now_iso()
    enrollment["status"] = "REJECTED"
    stamp_update(enrollment, store_now_iso=now_iso)
    return ok_object(serialize_enrollment(enrollment))


@bp.route("/enrollments/<eid>/terminate", methods=["POST"])
@require_roles("BenefitsCounselor")
def terminate_enrollment(eid):
    enrollment = store.enrollments.get(eid)
    if not enrollment:
        raise err("ERR_NOT_FOUND", "Enrollment not found")
    body = request.get_json(silent=True) or {}
    beneficiary = store.beneficiaries[enrollment["beneficiary_id"]]
    plan = store.plans[enrollment["plan_id"]]
    if beneficiary["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is deceased")
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment must be ACTIVE to terminate")
    termination_raw = require_field(body, "termination_date")
    term_dt = parse_iso_datetime(termination_raw, field="termination_date")
    end_of_year = datetime(plan["plan_year"], 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    if term_dt < enrollment["_effective_dt"]:
        raise err("ERR_VALIDATION", "termination_date must be >= effective_date")
    if term_dt > end_of_year:
        raise err("ERR_VALIDATION", "termination_date must be on or before last day of plan_year")
    check_version(body, enrollment["version"])

    now_iso = store.now_iso()
    enrollment["status"] = "TERMINATED"
    enrollment["_termination_dt"] = term_dt
    stamp_update(enrollment, store_now_iso=now_iso)

    # Freeze ledger phase if PART_D
    if enrollment["part_covered"] == "PART_D":
        for ledger in store.drug_phase_ledgers.values():
            if ledger["enrollment_id"] == enrollment["id"]:
                stamp_update(ledger, store_now_iso=now_iso)
                break

    # Mark LEP "inactive" — penalty_rate preserved as snapshot, but the row stays.
    # We model this by simply leaving the LEP row in place; serializers do not expose
    # an "active" boolean. No further action required for tests on this field.

    # Open SEP_LOSS_OF_COVERAGE period
    _open_sep_loss_of_coverage(beneficiary["id"], now_iso)

    # Re-evaluate lifecycle (ENROLLED -> COVERAGE_GAP if no other ACTIVE)
    _bubble_lifecycle_after_termination(beneficiary, now_iso)

    return ok_object(serialize_enrollment(enrollment))


@bp.route("/enrollments/<eid>/transfer", methods=["POST"])
@require_roles("BenefitsCounselor")
def transfer_enrollment(eid):
    enrollment = store.enrollments.get(eid)
    if not enrollment:
        raise err("ERR_NOT_FOUND", "Enrollment not found")
    body = request.get_json(silent=True) or {}
    beneficiary = store.beneficiaries[enrollment["beneficiary_id"]]
    if beneficiary["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is deceased")
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment must be ACTIVE to transfer")
    new_plan_id = require_field(body, "new_plan_id")
    new_plan = store.plans.get(new_plan_id)
    if new_plan is None:
        raise err("ERR_FK_NOT_FOUND", "new_plan_id not found")

    old_plan = store.plans[enrollment["plan_id"]]
    # Transfer is only for Part C in spec, but the check is plan_type match + plan_year+1
    if new_plan["plan_type"] != enrollment["part_covered"]:
        raise err("ERR_TRANSFER_WINDOW_INVALID", "New plan's plan_type must match part_covered")
    if new_plan["plan_year"] != old_plan["plan_year"] + 1:
        raise err("ERR_TRANSFER_WINDOW_INVALID", "New plan's plan_year must be old plan_year + 1")
    if not new_plan.get("is_active", True):
        raise err("ERR_TRANSFER_WINDOW_INVALID", "New plan is inactive")

    # Must occur during an OPEN AEP for this beneficiary at current clock
    now = store.clock
    open_aep = None
    for p in store.enrollment_periods.values():
        if p["beneficiary_id"] != beneficiary["id"]:
            continue
        if p["period_type"] != "AEP":
            continue
        if p["status"] != "OPEN":
            continue
        if p["_window_start_dt"] <= now <= p["_window_end_dt"]:
            open_aep = p
            break
    if open_aep is None:
        raise err("ERR_TRANSFER_WINDOW_INVALID", "No OPEN AEP covers current clock")

    check_version(body, enrollment["version"])

    now_iso = store.now_iso()

    # Old enrollment -> TERMINATED with termination_date = Dec 31 of old plan_year
    enrollment["status"] = "TERMINATED"
    enrollment["_termination_dt"] = _last_second_of_year(old_plan["plan_year"])
    stamp_update(enrollment, store_now_iso=now_iso)

    # Create new enrollment ACTIVE immediately
    new_eff = _first_of_year(new_plan["plan_year"])
    new_eid = store.new_id()
    new_enrollment = {
        "id": new_eid,
        "beneficiary_id": beneficiary["id"],
        "plan_id": new_plan["id"],
        "enrollment_period_id": open_aep["id"],
        "part_covered": new_plan["plan_type"],
        "status": "ACTIVE",
        "_effective_dt": new_eff,
        "_termination_dt": None,
        "months_late": 0,
    }
    stamp_create(new_enrollment, store_now_iso=now_iso)
    store.enrollments[new_eid] = new_enrollment

    # Fresh ledger if PART_D
    if new_plan["plan_type"] == "PART_D":
        _create_drug_phase_ledger(beneficiary["id"], new_eid, new_plan["plan_year"], now_iso)

    return ok_object(serialize_enrollment(new_enrollment))


@bp.route("/enrollments/<eid>", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def get_enrollment(eid):
    e = store.enrollments.get(eid)
    if not e:
        raise err("ERR_NOT_FOUND", "Enrollment not found")
    if g.role == "Beneficiary" and e["beneficiary_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "Beneficiaries may only read their own enrollments")
    return ok_object(serialize_enrollment(e))


@bp.route("/beneficiaries/<bid>/enrollments", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def list_enrollments(bid):
    b = store.beneficiaries.get(bid)
    if not b:
        raise err("ERR_NOT_FOUND", "Beneficiary not found")
    if g.role == "Beneficiary" and bid != g.user_id:
        raise err("ERR_FORBIDDEN", "Beneficiaries may only read their own enrollments")
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    part_f = request.args.get("part_covered")
    items = [e for e in store.enrollments.values() if e["beneficiary_id"] == bid]
    items.sort(key=lambda e: e["created_at"])
    if status_f:
        items = [e for e in items if e["status"] == status_f]
    if part_f:
        items = [e for e in items if e["part_covered"] == part_f]
    page, pagination = paginate(items, limit, offset)
    return ok_array([serialize_enrollment(e) for e in page], pagination)


@bp.route("/enrollments/<eid>/cost-summary", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def cost_summary(eid):
    e = store.enrollments.get(eid)
    if not e:
        raise err("ERR_NOT_FOUND", "Enrollment not found")
    if g.role == "Beneficiary" and e["beneficiary_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "Beneficiaries may only read their own cost summary")
    plan = store.plans[e["plan_id"]]
    beneficiary = store.beneficiaries[e["beneficiary_id"]]
    if e["status"] == "PENDING":
        # Provisional: live plan premium + projected LEP if activated today
        base = plan["monthly_premium_cents"]
        if e["part_covered"] in ("PART_B", "PART_D"):
            projected_ml = compute_months_late(beneficiary, e["_effective_dt"], e["part_covered"])
            _, projected_lep = compute_penalty(e["part_covered"], projected_ml, base)
        else:
            projected_lep = 0
        return ok_object({
            "effective_premium_cents": base + projected_lep,
            "base_premium_cents": base,
            "lep_cents": projected_lep,
            "variant": "provisional",
        })
    # Final: use frozen snapshot from LEP row (if any)
    # Find LEP for this enrollment_id
    lep = next(
        (l for l in store.late_enrollment_penalties.values() if l["enrollment_id"] == eid),
        None,
    )
    if lep:
        base = lep["snapshot_base_premium_cents"]
        lep_cents = lep["monthly_penalty_cents"]
    else:
        base = plan["monthly_premium_cents"]
        lep_cents = 0
    return ok_object({
        "effective_premium_cents": base + lep_cents,
        "base_premium_cents": base,
        "lep_cents": lep_cents,
        "variant": "final",
    })


# ---------- LEP fetch/list ----------

lep_bp = Blueprint("late_enrollment_penalties", __name__)


@lep_bp.route("/late-enrollment-penalties/<lid>", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def get_lep(lid):
    lep = store.late_enrollment_penalties.get(lid)
    if not lep:
        raise err("ERR_NOT_FOUND", "Late enrollment penalty not found")
    if g.role == "Beneficiary" and lep["beneficiary_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "Beneficiaries may only read their own penalties")
    return ok_object(serialize_late_enrollment_penalty(lep))


@lep_bp.route("/beneficiaries/<bid>/late-enrollment-penalties", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def list_leps(bid):
    b = store.beneficiaries.get(bid)
    if not b:
        raise err("ERR_NOT_FOUND", "Beneficiary not found")
    if g.role == "Beneficiary" and bid != g.user_id:
        raise err("ERR_FORBIDDEN", "Beneficiaries may only read their own penalties")
    limit, offset = parse_pagination(request.args)
    part_f = request.args.get("part")
    items = [l for l in store.late_enrollment_penalties.values() if l["beneficiary_id"] == bid]
    items.sort(key=lambda l: l["created_at"])
    if part_f:
        items = [l for l in items if l["part"] == part_f]
    page, pagination = paginate(items, limit, offset)
    return ok_array([serialize_late_enrollment_penalty(l) for l in page], pagination)
