"""Restitution payments: the conserved back-wage ledger of PRD 2.10 and 3.11.

Scheduling is a promise that moves nothing; disbursement is the forward
movement; reversal and voiding are the two compensating branches of the very
same endpoint, selected by the payment's from-state.
"""

from flask import Blueprint, request

import db
import derive
import serializers as s
import validators as v
from auth import ALL_ROLES, acting_staff, authenticate, require_ownership
from errors import ApiError
from response import created, ok, paginated, pagination

bp = Blueprint("restitution", __name__)

COMMITTED_STATUSES = ("PENDING", "DISBURSED")
DISBURSABLE_FINDING_STATUSES = ("OPEN", "RESPONSE_SUBMITTED", "RESPONSE_REJECTED")


def get_finding(finding_id):
    return v.lookup(db.findings, finding_id, "ERR_FINDING_NOT_FOUND")


def get_payment(payment_id):
    return v.lookup(db.restitution_payments, payment_id, "ERR_RESTITUTION_NOT_FOUND")


def _invalid_payment_state(message):
    raise ApiError("ERR_INVALID_PAYMENT_STATE", message)


def committed_cents(finding_id):
    """Sum of amount_cents over the PENDING and DISBURSED payments on a finding."""
    return sum(
        p["amount_cents"]
        for p in db.restitution_payments.values()
        if p["finding_id"] == finding_id and p["status"] in COMMITTED_STATUSES
    )


def _owning_assignment(finding):
    """The contract assignment that owns the finding's cited payroll submission."""
    return derive.finding_assignment(finding)


def _require_finding_ownership(actor, finding):
    """Ladder rung 5 for the two contractor-side restitution operations."""
    assignment = _owning_assignment(finding)
    staff = acting_staff(actor)
    require_ownership(staff, assignment["contractor_id"] if assignment else None)
    return assignment


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
@bp.route("/findings/<finding_id>/restitution-payments", methods=["POST"])
def schedule_payment(finding_id):
    actor = authenticate(["PayrollPreparer"])
    finding = get_finding(finding_id)
    payload = v.body()
    worker = v.resolve_fk(payload, "worker_id", db.workers, "ERR_WORKER_NOT_FOUND")

    _require_finding_ownership(actor, finding)

    if worker is None:
        v.bad("worker_id is required.")
    amount_cents = v.req_int(payload, "amount_cents", minimum=1)

    if committed_cents(finding["id"]) + amount_cents > finding["restitution_required_cents"]:
        raise ApiError(
            "ERR_RESTITUTION_EXCEEDS_OBLIGATION",
            "The committed restitution total would exceed the finding's obligation.",
        )

    row = db.base_row()
    row.update(
        {
            "finding_id": finding["id"],
            "worker_id": worker["id"],
            "amount_cents": amount_cents,
            "status": "PENDING",
            "disbursed_at": None,
            "reversal_reason": None,
        }
    )
    db.restitution_payments[row["id"]] = row
    return created(s.payment(row))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.route("/restitution-payments", methods=["GET"])
def list_payments():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    finding_id = request.args.get("finding_id")
    worker_id = request.args.get("worker_id")
    status = request.args.get("status")

    def keep(row):
        if finding_id is not None and row["finding_id"] != finding_id:
            return False
        if worker_id is not None and row["worker_id"] != worker_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(db.ordered(db.restitution_payments, keep), s.payment, limit, offset)


@bp.route("/restitution-payments/<payment_id>", methods=["GET"])
def read_payment(payment_id):
    authenticate(ALL_ROLES)
    return ok(s.payment(get_payment(payment_id)))


# ---------------------------------------------------------------------------
# PENDING -> DISBURSED, the forward ledger movement
# ---------------------------------------------------------------------------
@bp.route("/restitution-payments/<payment_id>/disburse", methods=["POST"])
def disburse_payment(payment_id):
    actor = authenticate(["PayrollPreparer"])
    payment = get_payment(payment_id)
    finding = db.findings.get(payment["finding_id"])
    assignment = _require_finding_ownership(actor, finding)

    if payment["status"] != "PENDING":
        _invalid_payment_state("Only a PENDING restitution payment may be disbursed.")
    if finding["status"] not in DISBURSABLE_FINDING_STATUSES:
        raise ApiError(
            "ERR_INVALID_FINDING_STATE",
            "Only an OPEN, RESPONSE_SUBMITTED or RESPONSE_REJECTED finding accepts a disbursement.",
        )
    if payment["amount_cents"] > finding["restitution_outstanding_cents"]:
        raise ApiError(
            "ERR_RESTITUTION_EXCEEDS_OBLIGATION",
            "amount_cents exceeds the finding's current restitution_outstanding_cents.",
        )

    payment["status"] = "DISBURSED"
    payment["disbursed_at"] = db.now()
    db.touch(payment)

    amount = payment["amount_cents"]
    finding["restitution_outstanding_cents"] = finding["restitution_outstanding_cents"] - amount
    db.touch(finding)
    if assignment is not None:
        assignment["cumulative_restitution_cents"] = (
            assignment["cumulative_restitution_cents"] + amount
        )
        db.touch(assignment)

    submission = derive.finding_submission(finding)
    auto_accepted = False
    if (
        finding["restitution_outstanding_cents"] == 0
        and finding["finding_type"] == "UNDERPAYMENT"
        and finding["status"] == "RESPONSE_SUBMITTED"
    ):
        finding["status"] = "RESPONSE_ACCEPTED"
        finding["_auto_accepted"] = True
        db.touch(finding)
        auto_accepted = True

    derive.cascade_finding_change(finding)
    if auto_accepted:
        derive.compliance_maybe_remedied(submission)
    elif finding["restitution_outstanding_cents"] > 0:
        derive.compliance_on_partial_disbursement(submission)
    return ok(s.payment(payment))


# ---------------------------------------------------------------------------
# DISBURSED -> REVERSED and PENDING -> VOIDED, the two compensating branches
# ---------------------------------------------------------------------------
@bp.route("/restitution-payments/<payment_id>/reverse", methods=["POST"])
def reverse_payment(payment_id):
    authenticate(["AgencyComplianceOfficer"])
    payment = get_payment(payment_id)
    payload = v.body()
    reversal_reason = v.req_nonempty_string(payload, "reversal_reason")
    finding = db.findings.get(payment["finding_id"])

    if payment["status"] == "PENDING":
        # No funds had moved, so neither side of the conserved identity shifts.
        payment["status"] = "VOIDED"
        payment["reversal_reason"] = reversal_reason
        db.touch(payment)
        return ok(s.payment(payment))

    if payment["status"] != "DISBURSED":
        _invalid_payment_state(
            "A restitution payment already REVERSED or VOIDED may not be reversed again."
        )
    if finding["status"] == "WITHDRAWN":
        raise ApiError(
            "ERR_INVALID_FINDING_STATE",
            "A payment on a WITHDRAWN finding may not be reversed.",
        )

    payment["status"] = "REVERSED"
    payment["reversal_reason"] = reversal_reason
    db.touch(payment)

    amount = payment["amount_cents"]
    finding["restitution_outstanding_cents"] = finding["restitution_outstanding_cents"] + amount
    db.touch(finding)
    assignment = _owning_assignment(finding)
    if assignment is not None:
        assignment["cumulative_restitution_cents"] = (
            assignment["cumulative_restitution_cents"] - amount
        )
        db.touch(assignment)

    if finding["status"] == "RESPONSE_ACCEPTED" and finding.get("_auto_accepted"):
        finding["status"] = "RESPONSE_SUBMITTED"
        finding["_auto_accepted"] = False
        db.touch(finding)

    derive.compliance_after_reversal(derive.finding_submission(finding))
    derive.cascade_finding_change(finding)
    return ok(s.payment(payment))
