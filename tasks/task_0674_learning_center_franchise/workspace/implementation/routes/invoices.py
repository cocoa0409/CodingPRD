"""Invoice endpoints and lifecycle (PRD §3.7)."""
from flask import Blueprint, request

from db import db, public
import errors
import helpers
from middleware import get_auth, require_role, get_body
from response import success
from services import calculations

bp = Blueprint("invoices", __name__)

READ_ROLES = {"FranchiseAdmin", "CenterDirector", "Parent"}


def _billable_enrollments(family_id, center_id):
    """ACTIVE enrollments whose center_id == invoice center and whose student
    belongs to the invoice family."""
    student_ids = {s["id"] for s in db.students.values() if s["family_id"] == family_id}
    return [
        e for e in db.enrollments.values()
        if e["status"] == "ACTIVE"
        and e["center_id"] == center_id
        and e["student_id"] in student_ids
    ]


@bp.route("/invoices", methods=["POST"])
def create_invoice():
    _uid, role = get_auth()
    require_role(role, {"CenterDirector"})
    body = get_body()

    family_id = helpers.require_str(body, "family_id")
    center_id = helpers.require_str(body, "center_id")
    period_month = helpers.require_str(body, "period_month")
    expected_family_version = helpers.require_int(body, "expected_family_version", minimum=0)

    family = db.families.get(family_id)
    if not family:
        raise errors.not_found()
    center = db.centers.get(center_id)
    if not center:
        raise errors.not_found()

    # OCC (priority 5): expected_family_version must match family.version.
    if expected_family_version != family["version"]:
        raise errors.stale_version()

    # Compute billable components over ACTIVE enrollments at this center for
    # this family. enrollment_fee_component: sum over students NEWLY charged on
    # this invoice of center.enrollment_fee_cents (each student at most once,
    # ever). A student's enrollment_fee_charged is set true at placement; the
    # fee is "staged for next invoice" and billed here exactly once.
    enrollments = _billable_enrollments(family_id, center_id)
    tuition_component = sum(e["monthly_rate_cents"] for e in enrollments)

    # Students newly charged: those whose fee has been staged (enrollment_fee_charged
    # True) but not yet billed on any prior invoice.
    billed_student_ids = _already_billed_student_ids(family_id)
    enrollment_fee_component = 0
    newly_charged = []
    seen = set()
    for e in enrollments:
        sid = e["student_id"]
        if sid in seen:
            continue
        seen.add(sid)
        student = db.students.get(sid)
        if student and student["enrollment_fee_charged"] and sid not in billed_student_ids:
            enrollment_fee_component += center["enrollment_fee_cents"]
            newly_charged.append(sid)

    obj = {
        "family_id": family_id,
        "center_id": center_id,
        "period_month": period_month,
        "enrollment_fee_component_cents": enrollment_fee_component,
        "tuition_component_cents": tuition_component,
        "wallet_applied_cents": 0,
        "total_due_cents": 0,
        "royalty_owed_cents": 0,
        "status": "DRAFT",
        "_fee_charged_student_ids": list(newly_charged),
    }
    db.stamp_create(obj)
    db.invoices[obj["id"]] = obj

    # Drafting advances the family's version (OCC parent).
    db.touch(family)
    return success(public(obj), status=201)


def _already_billed_student_ids(family_id):
    """Students for whom the one-time enrollment fee has already been put on a
    non-VOID invoice of this family."""
    billed = set()
    for inv in db.invoices.values():
        if inv["family_id"] != family_id:
            continue
        if inv["status"] == "VOID":
            continue
        for sid in inv.get("_fee_charged_student_ids", []):
            billed.add(sid)
    return billed


@bp.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    uid, role = get_auth()
    require_role(role, READ_ROLES)
    inv = db.invoices.get(invoice_id)
    if not inv:
        raise errors.not_found()
    if role == "Parent" and not helpers.parent_owns_family(uid, inv["family_id"]):
        raise errors.forbidden()
    return success(public(inv))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    uid, role = get_auth()
    require_role(role, READ_ROLES)
    args = request.args
    items = list(db.invoices.values())
    for key in ("family_id", "center_id", "status"):
        val = args.get(key)
        if val:
            items = [i for i in items if i.get(key) == val]
    if role == "Parent":
        items = [i for i in items if helpers.parent_owns_family(uid, i["family_id"])]
    return helpers.paginate_and_respond(items)


@bp.route("/invoices/<invoice_id>/issue", methods=["POST"])
def issue_invoice(invoice_id):
    _uid, role = get_auth()
    require_role(role, {"CenterDirector"})
    inv = db.invoices.get(invoice_id)
    if not inv:
        raise errors.not_found()
    if inv["status"] != "DRAFT":
        raise errors.invalid_state()
    gross = inv["enrollment_fee_component_cents"] + inv["tuition_component_cents"]
    if gross <= 0:
        raise errors.empty_invoice()

    # invoice_total calc: sum integer components first, then apply wallet.
    family = db.families.get(inv["family_id"])
    wallet = family["wallet_credit_cents"] if family else 0
    wallet_applied = min(wallet, gross)
    inv["wallet_applied_cents"] = wallet_applied
    inv["total_due_cents"] = gross - wallet_applied
    inv["status"] = "ISSUED"
    db.touch(inv)
    # Conserved-quantity invariant (PRD §3.7): issuing RESERVES the wallet credit
    # by deducting wallet_applied_cents from the family balance now; voiding an
    # ISSUED invoice refunds exactly this amount. (Family wallet 3000 -> 0 on
    # issue, 0 -> 3000 on void.)
    if family and wallet_applied > 0:
        family["wallet_credit_cents"] = max(0, family["wallet_credit_cents"] - wallet_applied)
        db.touch(family)
    return success(public(inv))


@bp.route("/invoices/<invoice_id>/pay", methods=["POST"])
def pay_invoice(invoice_id):
    uid, role = get_auth()
    require_role(role, {"Parent", "CenterDirector"})
    inv = db.invoices.get(invoice_id)
    if not inv:
        raise errors.not_found()
    if role == "Parent" and not helpers.parent_owns_family(uid, inv["family_id"]):
        raise errors.forbidden()
    body = get_body()
    amount = helpers.require_int(body, "amount_cents", minimum=0)

    if inv["status"] != "ISSUED":
        raise errors.invalid_state()
    if amount != inv["total_due_cents"]:
        raise errors.payment_amount_mismatch()

    inv["status"] = "PAID"
    # Wallet was already reserved (deducted) at issue time per the conserved-
    # quantity invariant; payment does not deduct again. (PRD §3.7: the wallet
    # the issue reserved is what a void would refund.)

    # royalty over tuition_component only, using the ACTIVE agreement of the center.
    agreement = _active_agreement(inv["center_id"])
    if agreement is not None:
        inv["royalty_owed_cents"] = calculations.royalty_owed(inv["tuition_component_cents"], agreement)
    db.touch(inv)
    return success(public(inv))


def _active_agreement(center_id):
    for a in db.agreements.values():
        if a["center_id"] == center_id and a["status"] == "ACTIVE":
            return a
    return None


@bp.route("/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    _uid, role = get_auth()
    require_role(role, {"CenterDirector"})
    inv = db.invoices.get(invoice_id)
    if not inv:
        raise errors.not_found()
    if inv["status"] not in ("DRAFT", "ISSUED"):
        raise errors.invalid_state()
    was_issued = inv["status"] == "ISSUED"
    inv["status"] = "VOID"
    # if previously ISSUED: refund wallet_applied back to family wallet.
    if was_issued and inv["wallet_applied_cents"] > 0:
        family = db.families.get(inv["family_id"])
        if family:
            family["wallet_credit_cents"] += inv["wallet_applied_cents"]
            db.touch(family)
    db.touch(inv)
    return success(public(inv))
