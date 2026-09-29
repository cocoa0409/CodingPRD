"""Tax calculation and the stamping office dimension (PRD 3.6-3.7)."""

from flask import Blueprint

import auth
import clock
import ledger
import serialize
import validation
from calc import premium_tax
from envelope import ok
from errors import ApiError
from store import db, touch

bp = Blueprint("policy_tax", __name__)

STAMPING_DECISIONS = ("ACCEPT", "REJECT")


@bp.post("/policies/<rec_id>/calculate-tax")
def calculate_tax(rec_id):
    """No version guard: a second attempt is barred by the tax dimension itself."""
    auth.require("TaxFiler")
    policy = auth.path_entity("policies", "policy", rec_id)

    if policy.get("status") != "ISSUED":
        raise ApiError("ERR_POLICY_NOT_ISSUED",
                       "The policy's status is %s." % policy.get("status"))
    if policy.get("tax_status") != "UNCALCULATED":
        raise ApiError("ERR_INVALID_STATE",
                       "The policy's tax has already been calculated.")

    placement = db.get("placements", policy.get("placement_id"))
    if placement is None:
        raise ApiError("ERR_PLACEMENT_NOT_FOUND")

    # Rung 17: ERR_ALLOCATION_STATE_PROGRAM_MISSING surfaces from here.
    taxable, rows = premium_tax.calculate(policy, placement)

    for row in rows:
        fields = dict(row)
        fields["policy_id"] = policy["id"]
        db.insert("policy_state_allocations", fields)

    policy["taxable_premium_cents"] = taxable
    policy["total_tax_cents"] = sum(int(r["tax_cents"]) for r in rows)
    policy["total_stamping_fee_cents"] = sum(int(r["stamping_fee_cents"]) for r in rows)
    policy["tax_status"] = "CALCULATED"
    touch(policy)

    # The ledger opens here: one NEW_BUSINESS line per allocated state, in
    # ascending state_code order.
    for row in rows:
        ledger.emit_line(policy, row["_state_program_id"], "NEW_BUSINESS",
                         row["allocated_premium_cents"], row["tax_cents"],
                         row["stamping_fee_cents"])

    return ok(serialize.public(policy))


@bp.post("/policies/<rec_id>/submit-stamping")
def submit_stamping(rec_id):
    auth.require("TaxFiler")
    policy = auth.path_entity("policies", "policy", rec_id)

    if policy.get("stamping_status") != "PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "The policy's stamping status is %s."
                       % policy.get("stamping_status"))
    if policy.get("compliance_status") not in ("NOTICES_AFFIXED", "COMPLIANT"):
        raise ApiError("ERR_NOTICES_NOT_AFFIXED",
                       "The statutory notices have not been affixed.")
    if policy.get("tax_status") == "UNCALCULATED":
        raise ApiError("ERR_TAX_NOT_CALCULATED",
                       "The policy's premium tax has not been calculated.")

    policy["stamping_submitted_at"] = clock.now_raw()
    policy["stamping_status"] = "SUBMITTED"
    touch(policy)
    return ok(serialize.public(policy))


@bp.post("/policies/<rec_id>/stamping-decision")
def stamping_decision(rec_id):
    auth.require("StateRegulator")
    policy = auth.path_entity("policies", "policy", rec_id)
    data = validation.body()
    decision = validation.req_enum(data, "decision", STAMPING_DECISIONS)
    # rejection_reason is optional at rung 6; its non-emptiness is a rung-16
    # documentary check on the REJECT branch, reported as
    # ERR_REJECTION_REASON_REQUIRED rather than ERR_INVALID_REQUEST.
    reason = validation.opt_str(data, "rejection_reason", allow_blank=True)

    if policy.get("stamping_status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SUBMITTED policy may receive a stamping decision.")

    if decision == "ACCEPT":
        policy["stamping_status"] = "ACCEPTED"
    else:
        if reason is None or reason.strip() == "":
            raise ApiError("ERR_REJECTION_REASON_REQUIRED",
                           "A rejection requires a rejection_reason.")
        policy["stamping_status"] = "REJECTED"
        # One request, two independent dimensions, one version increment.
        if policy.get("compliance_status") in ("NOTICES_AFFIXED", "COMPLIANT"):
            policy["compliance_status"] = "DEFICIENT"

    touch(policy)
    return ok(serialize.public(policy))
