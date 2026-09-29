"""Ordered cascade hops (PRD 2.9, 3.8, 3.9, 3.10, 3.12)."""
import calc
import clock
import db
import derive


# ------------------------------------------------------------------- ledger
def post_transaction(account_id, txn_type, amount_cents, source, payer_id=None,
                     remark=None, effective_at=None, reversal_of=None):
    stamp = clock.now()
    row = db.base_row(versioned=False)
    row.update({
        "account_id": account_id,
        "txn_type": txn_type,
        "amount_cents": int(amount_cents),
        "source": source,
        "payer_id": payer_id,
        "posted_at": stamp,
        "effective_at": effective_at or stamp,
        "reversal_of_transaction_id": reversal_of,
        "remark": remark,
    })
    db.account_transactions[row["id"]] = row
    if reversal_of is not None:
        db.reversed_transaction_ids.add(reversal_of)
    return row


def reverse_transaction(target, remark=None):
    """Writes a REVERSAL row carrying the exact negation of its target."""
    return post_transaction(
        account_id=target["account_id"],
        txn_type="REVERSAL",
        amount_cents=-int(target["amount_cents"]),
        source=target["source"],
        payer_id=target["payer_id"],
        remark=remark,
        reversal_of=target["id"],
    )


# -------------------------------------------------------- medicare obligation
def settle_obligations_by_refund_check(cb):
    """Hop 4 of the issue cascade (PRD 3.8)."""
    for ob in db.obligations_for_credit_balance(cb["id"]):
        if ob["state"] in ("OPEN", "REPORTED"):
            ob["state"] = "SATISFIED"
        elif ob["state"] in ("LATE", "REPORTED_LATE"):
            derive.refresh_obligation(ob)
            ob["state"] = "SATISFIED_LATE"
        else:
            continue
        ob["satisfied_at"] = clock.now()
        ob["satisfaction_mode"] = "REFUND_CHECK"
        db.touch(ob)


def reopen_obligations_after_void(cb):
    """Hop 4 of the void cascade (PRD 3.9 branch B)."""
    now = clock.now()
    for ob in db.obligations_for_credit_balance(cb["id"]):
        if ob["state"] == "SATISFIED":
            ob["state"] = "LATE" if now > ob["due_at"] else "OPEN"
        elif ob["state"] == "SATISFIED_LATE":
            ob["state"] = "LATE"
        else:
            continue
        ob["satisfied_at"] = None
        ob["satisfaction_mode"] = None
        derive.refresh_obligation(ob)
        db.touch(ob)


def settle_obligations_by_offset(cb):
    """Hop 4 of the offset cascade (PRD 3.10)."""
    for ob in db.obligations_for_credit_balance(cb["id"]):
        if ob["state"] not in ("OPEN", "LATE", "REPORTED"):
            continue
        ob["state"] = "SATISFIED_BY_OFFSET"
        ob["satisfied_at"] = clock.now()
        ob["satisfaction_mode"] = "OFFSET"
        db.touch(ob)


def reopen_obligations_after_offset_reverse(cb):
    """Hop 3 of the offset-reversal cascade (PRD 3.10)."""
    now = clock.now()
    for ob in db.obligations_for_credit_balance(cb["id"]):
        if ob["state"] != "SATISFIED_BY_OFFSET":
            continue
        ob["state"] = "LATE" if now > ob["due_at"] else "OPEN"
        ob["satisfied_at"] = None
        ob["satisfaction_mode"] = None
        derive.refresh_obligation(ob)
        db.touch(ob)


def settle_obligations_by_write_off(cb):
    """PRD 3.4 / 3.11: a write-off settles an already-reported obligation."""
    for ob in db.obligations_for_credit_balance(cb["id"]):
        if ob["state"] == "REPORTED":
            ob["state"] = "SATISFIED"
        elif ob["state"] == "REPORTED_LATE":
            ob["state"] = "SATISFIED_LATE"
        else:
            continue
        ob["satisfied_at"] = clock.now()
        ob["satisfaction_mode"] = "WRITE_OFF"
        db.touch(ob)


# ---------------------------------------------------------- credit balance
def release_credit_balance(cb, excluding_request_id):
    """REFUND_PENDING -> ATTRIBUTED when no OTHER refund request on the credit
    balance sits in SUBMITTED or APPROVED (PRD 3.7)."""
    for other in db.requests_for_credit_balance(cb["id"]):
        if other["id"] == excluding_request_id:
            continue
        if other["approval_state"] in ("SUBMITTED", "APPROVED"):
            return False
    if cb["status"] != "REFUND_PENDING":
        return False
    cb["status"] = "ATTRIBUTED"
    db.touch(cb)
    return True


# ------------------------------------------------------------ check voiding
def void_check(chk, void_reason):
    """PRD 3.9 branch B — the full four-hop compensation chain."""
    chk["state"] = "VOIDED"
    chk["void_reason"] = void_reason
    db.touch(chk)

    # hop 1 - ledger reversal of the check's REFUND_DISBURSEMENT posting
    target_id = chk.get("_disbursement_txn_id")
    target = db.account_transactions.get(target_id) if target_id else None
    if target is not None and target["id"] not in db.reversed_transaction_ids:
        reverse_transaction(target, remark="Void of check %s" % (chk["check_number"] or chk["id"]))

    # hop 2 - the refund request
    req = db.refund_requests.get(chk["refund_request_id"])
    if req is not None and req["disbursement_state"] in ("ISSUED", "CLEARED", "BATCHED"):
        req["disbursement_state"] = "REISSUE_PENDING"
        db.touch(req)

    # hop 3 - the credit balance
    cb = db.credit_balances.get(req["credit_balance_id"]) if req else None
    if cb is not None and cb["status"] == "REFUNDED":
        cb["status"] = "REFUND_PENDING"
        db.touch(cb)
        # hop 4 - the obligation
        reopen_obligations_after_void(cb)

    # an unclaimed-property record still DORMANT becomes EXEMPT
    rec = db.escheatment_for_check(chk["id"])
    if rec is not None and rec["state"] == "DORMANT":
        rec["state"] = "EXEMPT"
        db.touch(rec)


# ---------------------------------------------------------- offset reversal
def reverse_offset(offset, remark=None):
    """PRD 3.10 — line reversal and its three hops, plus the notice step-down."""
    offset["state"] = "REVERSED"
    offset["reversed_at"] = clock.now()
    db.touch(offset)

    target = db.account_transactions.get(offset["posted_transaction_id"])
    if target is not None and target["id"] not in db.reversed_transaction_ids:
        reverse_transaction(target, remark=remark)

    cb = db.credit_balances.get(offset["credit_balance_id"])
    if cb is not None and cb["status"] == "RESOLVED_BY_OFFSET" \
            and derive.cb_outstanding_cents(cb) > 0:
        cb["status"] = "ATTRIBUTED"
        db.touch(cb)
        reopen_obligations_after_offset_reverse(cb)

    notice = db.take_back_notices.get(offset["take_back_notice_id"])
    if notice is not None and notice["state"] in ("FULLY_APPLIED", "PARTIALLY_APPLIED"):
        applied = derive.notice_applied_cents(notice)
        notice["state"] = "PARTIALLY_APPLIED" if applied > 0 else "RECEIVED"
        db.touch(notice)


# ------------------------------------------------------------- batch issue
def issue_batch(batch, starting_check_number):
    """PRD 3.8 — the four-hop issue cascade."""
    batch["state"] = "ISSUED"
    db.touch(batch)

    pending = [c for c in db.checks_for_batch(batch["id"]) if c["state"] == "PENDING"]
    pending.sort(key=lambda c: (c["created_at"], c["_seq"]))
    now = clock.now()
    number = starting_check_number
    for chk in pending:
        # hop 1
        chk["state"] = "ISSUED"
        chk["check_number"] = str(number)
        chk["issued_at"] = now
        chk["stale_at"] = clock.add_days(now, calc.CHECK_STALE_DAYS)
        db.touch(chk)
        number += 1

        # hop 2
        req = db.refund_requests.get(chk["refund_request_id"])
        if req is not None and req["disbursement_state"] == "BATCHED":
            req["disbursement_state"] = "ISSUED"
            db.touch(req)

        # hop 3
        cb = db.credit_balances.get(req["credit_balance_id"]) if req else None
        if cb is not None:
            txn = post_transaction(
                account_id=cb["account_id"],
                txn_type="REFUND_DISBURSEMENT",
                amount_cents=int(chk["gross_amount_cents"]),
                source="SYSTEM",
                remark="Refund check %s" % chk["check_number"],
            )
            chk["_disbursement_txn_id"] = txn["id"]
            if cb["status"] == "REFUND_PENDING" and derive.cb_outstanding_cents(cb) == 0:
                cb["status"] = "REFUNDED"
                db.touch(cb)
                # hop 4
                settle_obligations_by_refund_check(cb)
