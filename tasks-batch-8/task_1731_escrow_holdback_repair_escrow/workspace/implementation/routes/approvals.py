"""Approval decision endpoint."""

from db import store, now
from errors import ApiError
from helpers import (
    get_body, check_allowed_fields, req_enum, opt_string,
    get_approval_or_404, get_holdback_or_404, file_of_holdback, touch,
    ser_approval,
)
from middleware import authenticate, authorize
from response import success

from . import bp

DECISIONS = {"APPROVED", "REJECTED"}


@bp.post("/escrow/approvals/<aid>/decide")
def decide_approval(aid):
    uid, role = authenticate()
    authorize(role, ["Lender", "Insurer"])
    a = get_approval_or_404(aid)
    data = get_body()
    check_allowed_fields(data, {"decision", "rejection_reason"})
    decision = req_enum(data, "decision", DECISIONS)
    rejection_reason = opt_string(data, "rejection_reason")

    hb = get_holdback_or_404(a["holdback_id"])
    f = file_of_holdback(hb)

    # Rung 5: caller role matches approver_role and caller id matches the
    # file's lender/insurer id.
    if a["approver_role"] == "LENDER":
        party_ok = role == "Lender" and f is not None and uid == f["lender_user_id"]
    else:
        party_ok = role == "Insurer" and f is not None and uid == f["insurer_user_id"]
    if not party_ok:
        raise ApiError("ERR_NOT_FILE_PARTY", "Caller is not the approver of record")

    # Rung 8: only a REQUESTED approval can be decided.
    if a["status"] != "REQUESTED":
        raise ApiError("ERR_APPROVAL_NOT_PENDING", "Approval is not in REQUESTED state")

    a["approver_user_id"] = uid
    a["decided_at"] = now()
    a["holdback_version_at_decision"] = hb["version"]
    if decision == "APPROVED":
        a["status"] = "APPROVED"
    else:
        a["status"] = "REJECTED"
        a["rejection_reason"] = rejection_reason
    touch(a)

    if decision == "APPROVED":
        # Auto-activate when no REQUESTED approvals remain.
        remaining = any(
            x["status"] == "REQUESTED"
            for x in store.approvals.values() if x["holdback_id"] == hb["id"]
        )
        if not remaining and hb["status"] == "PENDING_APPROVALS":
            hb["status"] = "ACTIVE"
            touch(hb)
    else:
        # Rejection loop: holdback back to DRAFT, siblings CANCELLED.
        for x in store.approvals.values():
            if x["holdback_id"] == hb["id"] and x["id"] != a["id"] and x["status"] == "REQUESTED":
                x["status"] = "CANCELLED"
                touch(x)
        if hb["status"] == "PENDING_APPROVALS":
            hb["status"] = "DRAFT"
            touch(hb)

    return success(ser_approval(a), response_type="object", status=200)
