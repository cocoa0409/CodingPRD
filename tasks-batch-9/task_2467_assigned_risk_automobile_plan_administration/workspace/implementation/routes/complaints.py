"""Complaints against a servicing carrier, their findings trail and resolution."""

from flask import Blueprint, request

import calc
import domain
import guards
from envelope import created, ok, ok_list
from errors import fail
from store import db, new_row, touch

bp = Blueprint("complaints", __name__)

READ_ROLES = ("PlanAdministrator", "ComplianceExaminer", "ServicingCarrier")
COMPLAINT_TYPES = (
    "CLAIM_HANDLING_DELAY",
    "RATING_DISPUTE",
    "CANCELLATION_DISPUTE",
    "SERVICE_STANDARD",
)
DISPOSITIONS = ("UPHELD", "NOT_UPHELD", "RETURNED_FOR_FURTHER_REVIEW")


@bp.post("/plan/complaints")
def docket_complaint():
    guards.authenticate(("PlanAdministrator", "ComplianceExaminer"))
    data = guards.body()
    policy_id = guards.req_str(data, "policy_id")
    carrier_id = guards.req_str(data, "carrier_id")
    complaint_type = guards.req_enum(data, "complaint_type", COMPLAINT_TYPES)
    narrative = guards.req_str(data, "narrative", min_len=1, max_len=2000)

    policy = guards.need_policy(policy_id)
    carrier = guards.need_carrier(carrier_id)

    if policy["carrier_id"] != carrier["id"]:
        fail("ERR_COMPLAINT_CARRIER_MISMATCH")

    row = new_row()
    row.update(
        {
            "policy_id": policy["id"],
            "carrier_id": carrier["id"],
            "complaint_type": complaint_type,
            "narrative": narrative,
            "status": "OPEN",
            "findings_recorded_by_user_id": None,
            "findings_note": None,
            "resolved_by_user_id": None,
            "disposition": None,
            "review_round": 1,
        }
    )
    db.complaints[row["id"]] = row
    # The policy's freeze is derived from its open complaints.
    touch(policy)
    return created(domain.complaint_out(row))


@bp.get("/plan/complaints")
def list_complaints():
    guards.authenticate(READ_ROLES)
    limit, offset = guards.pagination()
    policy_id = request.args.get("policy_id")
    carrier_id = request.args.get("carrier_id")
    status = request.args.get("status")

    rows = list(db.complaints.values())
    if policy_id is not None:
        rows = [r for r in rows if r["policy_id"] == policy_id]
    if carrier_id is not None:
        rows = [r for r in rows if r["carrier_id"] == carrier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    rows = domain.sort_default(rows)
    page, total = domain.paginate(rows, limit, offset)
    return ok_list([domain.complaint_out(r) for r in page], limit, offset, total)


@bp.get("/plan/complaints/<complaint_id>")
def read_complaint(complaint_id):
    guards.authenticate(READ_ROLES)
    complaint = guards.need_complaint(complaint_id)
    return ok(domain.complaint_out(complaint))


@bp.post("/plan/complaints/<complaint_id>/findings")
def record_findings(complaint_id):
    user_id, _role = guards.authenticate(("ComplianceExaminer",))
    data = guards.body()
    findings_note = guards.req_str(data, "findings_note", min_len=1, max_len=2000)
    complaint = guards.need_complaint(complaint_id)

    if complaint["status"] != "OPEN":
        fail("ERR_INVALID_COMPLAINT_STATE")

    complaint["status"] = "FINDINGS_RECORDED"
    complaint["findings_recorded_by_user_id"] = user_id
    complaint["findings_note"] = findings_note
    touch(complaint)
    return ok(domain.complaint_out(complaint))


@bp.post("/plan/complaints/<complaint_id>/resolution")
def resolve_complaint(complaint_id):
    user_id, _role = guards.authenticate(("ComplianceExaminer",))
    data = guards.body()
    disposition = guards.req_enum(data, "disposition", DISPOSITIONS)
    guards.opt_str(data, "resolution_note", max_len=2000)
    complaint = guards.need_complaint(complaint_id)

    if complaint["status"] != "FINDINGS_RECORDED":
        fail("ERR_INVALID_COMPLAINT_STATE")
    if user_id == complaint["findings_recorded_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if (
        disposition == "RETURNED_FOR_FURTHER_REVIEW"
        and complaint["review_round"] >= calc.REVIEW_ROUND_LIMIT
    ):
        fail("ERR_REVIEW_ROUND_LIMIT")

    policy = db.policies.get(complaint["policy_id"])
    complaint["resolved_by_user_id"] = user_id
    complaint["disposition"] = disposition

    if disposition == "RETURNED_FOR_FURTHER_REVIEW":
        # The freeze stays on: the complaint is still open business.
        complaint["status"] = "OPEN"
        complaint["review_round"] += 1
        complaint["findings_recorded_by_user_id"] = None
        complaint["findings_note"] = None
        touch(complaint)
        return ok(domain.complaint_out(complaint))

    if disposition == "UPHELD":
        complaint["status"] = "RESOLVED_UPHELD"
        touch(complaint)
        carrier = db.carriers.get(complaint["carrier_id"])
        if carrier is not None:
            domain.adjust_score(carrier, -calc.UPHELD_COMPLAINT_DEDUCTION)
            domain.apply_suspension_cascade(carrier)
    else:
        complaint["status"] = "RESOLVED_NOT_UPHELD"
        touch(complaint)

    # open_complaint_count fell, so the freeze is re-derived on the policy.
    touch(policy)
    return ok(domain.complaint_out(complaint))
