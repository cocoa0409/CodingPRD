"""Payment plan endpoints (PRD 3.8): OCC-guarded create-with-supersede
drafting with the pinned setup-fee evaluation order and floor-then-remainder
installment split, and the segregated-duty APPROVE with the SERVED-notice
gate."""

from flask import Blueprint

import db
import errors
import middleware
import response
import serializers
import validators as V
from services import calc

bp = Blueprint("plans", __name__)

DRAFT_ROLES = {"Tenant", "LeasingAgent", "PropertyManager"}
MIN_INSTALLMENTS = 2
MAX_INSTALLMENTS = 12


def get_plan_or_404(plan_id):
    plan = db.plans.get(plan_id)
    if plan is None:
        errors.fail(errors.ERR_NOT_FOUND, "Payment plan %s does not exist." % plan_id)
    return plan


@bp.post("/payment-plans")
def create_plan():
    uid, role = middleware.current_user()
    middleware.require_role(role, DRAFT_ROLES)
    data = V.json_body()
    V.check_unknown(data, {
        "lease_id", "charge_ids", "installment_count",
        "first_installment_date", "expected_lease_version",
    })
    lease_id = V.req_str(data, "lease_id")
    charge_ids = V.req_id_array(data, "charge_ids")
    installment_count = V.req_int(data, "installment_count")
    first_installment_date = V.req_date(data, "first_installment_date")
    # Tier 4: body FK references must exist.
    lease = db.leases.get(lease_id)
    if lease is None:
        errors.fail(errors.ERR_NOT_FOUND, "Lease %s does not exist." % lease_id)
    covered = []
    for cid in charge_ids:
        charge = db.charges.get(cid)
        if charge is None:
            errors.fail(errors.ERR_NOT_FOUND, "Charge %s does not exist." % cid)
        covered.append(charge)
    # Tier 2 ownership: a Tenant drafts only on their own lease.
    if role == "Tenant" and lease["primary_tenant_id"] != uid:
        errors.fail(
            errors.ERR_UNAUTHORIZED,
            "A Tenant may draft payment plans only on their own lease.",
        )
    # Tier 5: OCC — the client must hold the lease's current version.
    expected = V.req_version(data, "expected_lease_version")
    if expected != lease["version"]:
        errors.fail(
            errors.ERR_STALE_VERSION,
            "expected_lease_version %s does not match the lease's current version %d."
            % (expected, lease["version"]),
        )
    # Tier 6: plan creation requires an ACTIVE lease.
    if lease["status"] == "DRAFT":
        errors.fail(errors.ERR_LEASE_NOT_ACTIVE, "Payment plans require an ACTIVE lease.")
    if lease["status"] == "ENDED":
        errors.fail(
            errors.ERR_LEASE_ALREADY_ENDED,
            "Payment plans cannot be created on an ENDED lease.",
        )
    # Tier 9: every covered charge must belong to the named lease and be open.
    for charge in covered:
        if charge["lease_id"] != lease["id"]:
            errors.fail(
                errors.ERR_CHARGE_NOT_ON_LEASE,
                "Charge %s does not belong to lease %s." % (charge["id"], lease["id"]),
            )
        if charge["status"] not in ("OPEN", "PARTIALLY_PAID"):
            errors.fail(
                errors.ERR_INVALID_REQUEST,
                "Covered charges must be in OPEN or PARTIALLY_PAID status.",
            )
    # Tier 12: the schedule must be sensible (dedicated error code).
    today = db.clock_date()
    if not MIN_INSTALLMENTS <= installment_count <= MAX_INSTALLMENTS:
        errors.fail(
            errors.ERR_INVALID_INSTALLMENT_SCHEDULE,
            "installment_count must be between 2 and 12 inclusive.",
        )
    if first_installment_date <= today:
        errors.fail(
            errors.ERR_INVALID_INSTALLMENT_SCHEDULE,
            "first_installment_date must be strictly after today.",
        )
    # Tier 13: at most one ACTIVE plan per lease; the cooling-off window after
    # a default must have elapsed (strict less-than on whole days).
    for other in db.plans.values():
        if other["lease_id"] != lease["id"]:
            continue
        if other["status"] == "ACTIVE":
            errors.fail(
                errors.ERR_PLAN_EXISTS,
                "An ACTIVE payment plan already exists on this lease.",
            )
        if other["status"] == "DEFAULTED" and other["defaulted_date"] is not None:
            prop = calc.property_of(lease)
            days_since = (today - calc.parse_d(other["defaulted_date"])).days
            if days_since < prop["plan_cooling_off_days"]:
                errors.fail(
                    errors.ERR_PLAN_COOLING_OFF,
                    "The plan cooling-off window has not elapsed on this lease.",
                )
    prop = calc.property_of(lease)
    # Create-with-supersede: any existing DRAFT plan on the lease is cancelled;
    # the lease version advances (the OCC-observable mutation).
    for other in db.plans.values():
        if other["lease_id"] == lease["id"] and other["status"] == "DRAFT":
            other["status"] = "CANCELLED"
            other["cancel_reason"] = "SUPERSEDED"
            db.touch(other)
    # plan_setup_fee_evaluation (pinned order): the fee is fixed on the
    # pre-fee covered balance; a balance exactly at the threshold qualifies.
    base_balance = sum(c["outstanding_cents"] for c in covered)
    setup_fee = (
        prop["plan_setup_fee_cents"]
        if base_balance >= prop["plan_setup_fee_threshold_cents"]
        else 0
    )
    first_str = first_installment_date.isoformat()
    if setup_fee > 0:
        # The PLAN_SETUP_FEE charge is due on the first installment date,
        # source PLAN, created by 'system'.
        calc_charge = db.init_common({
            "lease_id": lease["id"],
            "kind": "PLAN_SETUP_FEE",
            "source": "PLAN",
            "period_start_date": first_str,
            "period_end_date": first_str,
            "due_date": first_str,
            "amount_cents": setup_fee,
            "waived_cents": 0,
            "outstanding_cents": setup_fee,
            "status": "OPEN",
            "created_by_user_id": "system",
        })
        db.charges[calc_charge["id"]] = calc_charge
    scheduled_total = base_balance + setup_fee
    plan = db.init_common({
        "lease_id": lease["id"],
        "charge_ids": charge_ids,
        "drafted_by_user_id": uid,
        "approved_by_user_id": None,
        "status": "DRAFT",
        "setup_fee_cents": setup_fee,
        "scheduled_total_cents": scheduled_total,
        "installment_count": installment_count,
        "first_installment_date": first_str,
        "installments": calc.installment_schedule(
            scheduled_total, installment_count, first_str
        ),
        "missed_installment_count": 0,
        "defaulted_date": None,
        "cancel_reason": None,
        "_activated_date": None,
    })
    db.plans[plan["id"]] = plan
    db.touch(lease)
    return response.success_object(serializers.plan_view(plan), 201)


@bp.get("/leases/<lease_id>/payment-plans")
def list_plans(lease_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    lease = db.leases.get(lease_id)
    if lease is None:
        errors.fail(errors.ERR_NOT_FOUND, "Lease %s does not exist." % lease_id)
    if role == "Tenant":
        middleware.require_owns_lease(uid, lease)
    rows = [p for p in db.plans.values() if p["lease_id"] == lease["id"]]
    page, limit, offset, total = V.sorted_page(rows, [
        ("status", V.query_filter("status")),
    ])
    return response.success_list(
        [serializers.plan_view(p) for p in page], limit, offset, total
    )


@bp.get("/payment-plans/<plan_id>")
def get_plan(plan_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    plan = get_plan_or_404(plan_id)
    if role == "Tenant":
        middleware.require_owns_lease(uid, db.leases[plan["lease_id"]])
    return response.success_object(serializers.plan_view(plan))


@bp.post("/payment-plans/<plan_id>/transition")
def transition_plan(plan_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.PM)
    plan = get_plan_or_404(plan_id)
    data = V.json_body()
    V.check_unknown(data, {"action"})
    V.req_enum(data, "action", {"APPROVE"})
    # Tier 7: approval is legal only from DRAFT.
    if plan["status"] != "DRAFT":
        errors.fail(
            errors.ERR_PLAN_INVALID_TRANSITION,
            "APPROVE requires a plan in DRAFT status.",
        )
    # Tier 8: segregation of duties — approver must differ from the drafter.
    if uid == plan["drafted_by_user_id"]:
        errors.fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "The plan approver must differ from the plan's drafter.",
        )
    # Tier 14: approval is blocked while any notice on the lease is SERVED.
    for n in db.notices.values():
        if n["lease_id"] == plan["lease_id"] and n["status"] == "SERVED":
            errors.fail(
                errors.ERR_ACTIVE_NOTICE_BLOCKS_PLAN,
                "A SERVED notice on this lease blocks plan approval.",
            )
    plan["status"] = "ACTIVE"
    plan["approved_by_user_id"] = uid
    plan["_activated_date"] = db.today_str()
    db.touch(plan)
    return response.success_object(serializers.plan_view(plan))
