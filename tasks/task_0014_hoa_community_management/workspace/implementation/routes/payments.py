"""Payment endpoints (apply, reverse, list, fetch)."""
from __future__ import annotations

from flask import Blueprint, request

import db
import recompute
from errors import (
    ERR_INVALID_STATE,
    ERR_OVERPAYMENT,
    ERR_STALE_VERSION,
    raise_err,
)
from middleware import auth_required
from response import list_success, success
from .helpers import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_str,
)


bp = Blueprint("payments", __name__)


def _serialize(p: dict) -> dict:
    return {
        "id": p["id"],
        "assessment_id": p["assessment_id"],
        "amount_cents": int(p["amount_cents"]),
        "state": p["state"],
        "applied_at": p["applied_at"],
        "created_at": p["created_at"],
    }


@bp.route("/hoa/payments", methods=["POST"])
@auth_required({"Treasurer", "HomeOwner"})
def create_payment():
    body = get_json_body()
    assessment_id = require_str(body, "assessment_id")
    amount_cents = require_int(body, "amount_cents", min_value=1)
    expected_version = require_int(body, "expected_assessment_version",
                                   min_value=0)

    a = fetch_or_404(db.assessments, assessment_id, "Assessment")

    # Validation priority: state check before fiscal before OCC
    # (per PRD §2.11 within business tier: safety > temporal > referential
    # > fiscal > constraint). State machine eligibility is even higher.
    if a["status"] not in {"DUE", "OVERDUE"}:
        raise_err(ERR_INVALID_STATE,
                  f"Assessment must be DUE or OVERDUE (currently {a['status']})")

    # Business-fiscal: overpayment check first (priority 13)
    remaining = int(a["principal_cents"]) + int(a["late_fee_cents"]) - int(a["paid_cents"])
    if amount_cents > remaining:
        raise_err(ERR_OVERPAYMENT,
                  f"Amount {amount_cents} exceeds remaining {remaining}")

    # Business-constraint: OCC check (priority 16)
    if int(a["version"]) != int(expected_version):
        raise_err(ERR_STALE_VERSION,
                  f"Assessment version is {a['version']}, "
                  f"expected {expected_version}")

    # Apply the payment
    now_s = db.iso_now()
    payment = {
        "id": db.new_id(),
        "assessment_id": assessment_id,
        "amount_cents": amount_cents,
        "state": "APPLIED",
        "applied_at": now_s,
        "created_at": now_s,
    }
    db.payment_applications[payment["id"]] = payment

    # Recompute paid_cents and outstanding on the assessment
    recompute.recompute_assessment_paid_outstanding(a)
    recompute.maybe_transition_to_paid(a)
    db.bump(a)

    # Recompute property balance
    prop = db.properties.get(a["property_id"])
    if prop is not None:
        recompute.recompute_property_account_balance(prop)
        # Payment never creates a lien (balance only goes down), so no cascade

    return success(_serialize(payment), status=201)


@bp.route("/hoa/payments/<pid>", methods=["GET"])
@auth_required({"PlatformAdmin", "Treasurer", "BoardPresident",
                "BoardSecretary", "HomeOwner"})
def fetch_payment(pid):
    p = fetch_or_404(db.payment_applications, pid, "PaymentApplication")
    return success(_serialize(p))


@bp.route("/hoa/payments", methods=["GET"])
@auth_required({"PlatformAdmin", "Treasurer", "BoardPresident",
                "BoardSecretary", "HomeOwner"})
def list_payments():
    limit, offset = parse_pagination()
    assessment_id = request.args.get("assessment_id")
    rows = list(db.payment_applications.values())
    if assessment_id is not None:
        rows = [r for r in rows if r["assessment_id"] == assessment_id]
    page, total = paginate(rows, limit, offset)
    return list_success([_serialize(r) for r in page], total, limit, offset)


@bp.route("/hoa/payments/<pid>/reverse", methods=["POST"])
@auth_required({"Treasurer"})
def reverse_payment(pid):
    p = fetch_or_404(db.payment_applications, pid, "PaymentApplication")
    if p["state"] != "APPLIED":
        raise_err(ERR_INVALID_STATE,
                  f"PaymentApplication must be APPLIED to reverse "
                  f"(currently {p['state']})")
    p["state"] = "REVERSED"
    a = db.assessments.get(p["assessment_id"])
    if a is not None:
        recompute.recompute_assessment_paid_outstanding(a)
        # If the reversal pushed outstanding back above 0 and the assessment
        # was PAID, drop it back to DUE/OVERDUE per the clock.
        recompute.maybe_revert_from_paid(a)
        db.bump(a)
        prop = db.properties.get(a["property_id"])
        if prop is not None:
            recompute.recompute_property_account_balance(prop)
            recompute.maybe_file_lien_cascade(prop)

    return success(_serialize(p))
