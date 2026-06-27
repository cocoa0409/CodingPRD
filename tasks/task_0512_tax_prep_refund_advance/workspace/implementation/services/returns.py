"""TaxReturn state machine, prep-fee materialization, and cancellation cascade
(SCAFFOLD Table 2, PRD §3.4, §3.5)."""
import errors
from db import db
from models import (touch, make_fee_line)
from services.calculations import prep_fee_total
from services.counters import (recompute_office_open_return_count,
                               recompute_preparer_assigned_open_returns)
from timeutil import parse_iso


# Non-efile transitions handled by /returns/{id}/transition.
# Set of (from, to). EFILED_PENDING transitions are driven by efile/efile-ack.
NONEFILE_TRANSITIONS = {
    ("INTAKE", "DOCS_PENDING"),
    ("DOCS_PENDING", "IN_PREP"),
    ("IN_PREP", "PREPARED"),
    ("EFILED_REJECTED", "PREPARED"),
    ("INTAKE", "CANCELLED"),
    ("DOCS_PENDING", "CANCELLED"),
    ("IN_PREP", "CANCELLED"),
    ("PREPARED", "CANCELLED"),
}

VALID_RETURN_STATES = {
    "INTAKE", "DOCS_PENDING", "IN_PREP", "PREPARED", "EFILED_PENDING",
    "EFILED_ACCEPTED", "EFILED_REJECTED", "CANCELLED",
}


def regenerate_fee_lines(ret):
    """Recompute prep_fee_total, write prep_fee_cents, and (re)generate FeeLine
    rows for the return (PRD §3.4). Called on entry to IN_PREP."""
    # remove existing fee lines for this return (recompute each time)
    to_remove = [fid for fid, f in db.fee_lines.items()
                 if f["tax_return_id"] == ret["id"]]
    for fid in to_remove:
        del db.fee_lines[fid]

    client = db.clients.get(ret["client_id"])
    is_returning = bool(client["is_returning"]) if client else False

    prep_fee_cents, lines = prep_fee_total(
        ret["complexity_band"], ret["schedules"], ret["state_return_count"],
        is_returning,
    )
    for line_kind, label, amount_cents in lines:
        make_fee_line(ret["id"], line_kind, label, amount_cents)

    ret["prep_fee_cents"] = prep_fee_cents


def cancel_cascade(ret):
    """Cascade on TaxReturn cancellation (PRD §3.5):
      - every ACTIVE AuditProtection on the return -> VOIDED
      - any RefundAdvance REQUESTED|APPROVED -> CANCELLED, which in turn sets a
        linked PENDING_FUNDING RefundTransfer -> CANCELLED.
    Each flipped child is a mutation: refresh updated_at and bump version."""
    rid = ret["id"]

    for ap in db.audit_protections.values():
        if ap["tax_return_id"] == rid and ap["status"] == "ACTIVE":
            ap["status"] = "VOIDED"
            touch(ap)

    for adv in db.refund_advances.values():
        if adv["tax_return_id"] == rid and adv["status"] in ("REQUESTED", "APPROVED"):
            adv["status"] = "CANCELLED"
            touch(adv)
            # that cancellation sets the linked PENDING_FUNDING transfer -> CANCELLED
            for rt in db.refund_transfers.values():
                if rt["tax_return_id"] == rid and rt["status"] == "PENDING_FUNDING":
                    rt["status"] = "CANCELLED"
                    touch(rt)


def perform_cancel(ret):
    """Cancel the return: set status, recompute counters, run cascade."""
    preparer_id = ret.get("preparer_id")
    ret["status"] = "CANCELLED"
    touch(ret)
    recompute_office_open_return_count(ret["office_id"])
    recompute_preparer_assigned_open_returns(preparer_id)
    cancel_cascade(ret)


def transition_return(ret, to):
    """Apply a non-efile transition with its preconditions and side effects."""
    if to not in VALID_RETURN_STATES:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to must be a valid return state")

    current = ret["status"]
    if (current, to) not in NONEFILE_TRANSITIONS:
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Transition %s -> %s is not defined" % (current, to))

    if to == "DOCS_PENDING":
        # INTAKE -> DOCS_PENDING: at least one DocumentIntake row exists.
        has_doc = any(d["tax_return_id"] == ret["id"] for d in db.documents.values())
        if not has_doc:
            raise errors.err(errors.ERR_NO_DOCUMENTS, "Return has no documents")

    elif to == "IN_PREP":
        # DOCS_PENDING -> IN_PREP preconditions, in PRD order:
        # 1. preparer assigned
        if ret.get("preparer_id") is None:
            raise errors.err(errors.ERR_PREPARER_NOT_ASSIGNED, "No preparer assigned")
        # 2. every required document RECEIVED or WAIVED
        for d in db.documents.values():
            if d["tax_return_id"] == ret["id"] and d["is_required"] and d["status"] == "PENDING":
                raise errors.err(errors.ERR_REQUIRED_DOCS_MISSING,
                                 "A required document is still pending")
        # 3. assigned preparer's credential is ACTIVE
        prep = db.preparers.get(ret["preparer_id"])
        cred = db.credentials.get(prep["credential_id"]) if prep else None
        if cred is None or cred["status"] != "ACTIVE":
            raise errors.err(errors.ERR_CREDENTIAL_INVALID, "Preparer credential is not ACTIVE")
        # side effect: recompute prep fee + fee lines
        ret["status"] = "IN_PREP"
        regenerate_fee_lines(ret)
        touch(ret)
        return

    elif to == "PREPARED":
        if current == "IN_PREP":
            if ret["expected_refund_cents"] < 0:
                raise errors.err(errors.ERR_INVALID_REFUND_FIGURE,
                                 "expected_refund_cents must be >= 0")
        elif current == "EFILED_REJECTED":
            # correction loop precondition: reject_count <= 3
            if ret["reject_count"] > 3:
                raise errors.err(errors.ERR_REJECT_LIMIT_REACHED,
                                 "Return is locked after the reject limit")

    elif to == "CANCELLED":
        perform_cancel(ret)
        return

    # plain transition (no special side effects)
    ret["status"] = to
    touch(ret)


def efile(ret):
    """PREPARED -> EFILED_PENDING (PRD §3.5)."""
    if ret["status"] != "PREPARED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Return must be PREPARED to e-file")

    office = db.offices.get(ret["office_id"])
    # 1. EFIN must be ACTIVE
    if office["efin_status"] != "ACTIVE":
        raise errors.err(errors.ERR_EFIN_SUSPENDED, "Office EFIN is suspended")

    # 2. credential ACTIVE and not expired against the logical clock
    prep = db.preparers.get(ret.get("preparer_id")) if ret.get("preparer_id") else None
    cred = db.credentials.get(prep["credential_id"]) if prep else None
    if cred is None or cred["status"] != "ACTIVE":
        raise errors.err(errors.ERR_CREDENTIAL_INVALID, "Preparer credential is not ACTIVE")
    if parse_iso(cred["expires_on"]) <= db.clock:
        raise errors.err(errors.ERR_CREDENTIAL_INVALID, "Preparer credential is expired")

    # 3. AMENDED_1040X target must be EFILED_ACCEPTED
    if ret["return_kind"] == "AMENDED_1040X":
        target_id = ret.get("amends_return_id")
        target = db.returns.get(target_id) if target_id else None
        if target is None or target["status"] != "EFILED_ACCEPTED":
            raise errors.err(errors.ERR_AMEND_TARGET_NOT_ACCEPTED,
                             "Amend target return is not EFILED_ACCEPTED")

    # side effect: create EfileSubmission TRANSMITTED with efin/ptin snapshot
    from models import make_efile_submission
    make_efile_submission(ret["id"], office["efin"], cred["ptin"])
    ret["status"] = "EFILED_PENDING"
    touch(ret)


def _latest_transmitted_submission(return_id):
    subs = [s for s in db.efile_submissions.values()
            if s["tax_return_id"] == return_id and s["ack_status"] == "TRANSMITTED"]
    if not subs:
        return None
    return max(subs, key=lambda s: s["_seq"])


def efile_ack(ret, ack_status, reject_code):
    """EFILED_PENDING -> EFILED_ACCEPTED | EFILED_REJECTED (PRD §3.5)."""
    if ret["status"] != "EFILED_PENDING":
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Return must be EFILED_PENDING to record an ACK")

    if ack_status == "ACCEPTED":
        sub = _latest_transmitted_submission(ret["id"])
        if sub is not None:
            sub["ack_status"] = "ACCEPTED"
            touch(sub)
        ret["status"] = "EFILED_ACCEPTED"
        touch(ret)
        recompute_office_open_return_count(ret["office_id"])
        recompute_preparer_assigned_open_returns(ret.get("preparer_id"))

    elif ack_status == "REJECTED":
        if not reject_code:
            raise errors.err(errors.ERR_REJECT_CODE_REQUIRED, "reject_code is required")
        sub = _latest_transmitted_submission(ret["id"])
        if sub is not None:
            sub["ack_status"] = "REJECTED"
            sub["reject_code"] = reject_code
            touch(sub)
        ret["status"] = "EFILED_REJECTED"
        ret["reject_count"] += 1
        touch(ret)
    else:
        raise errors.err(errors.ERR_INVALID_REQUEST, "ack_status must be ACCEPTED or REJECTED")
