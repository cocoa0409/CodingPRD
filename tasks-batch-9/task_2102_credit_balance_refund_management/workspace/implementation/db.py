"""In-memory store. Plain dicts keyed by id. NEVER seeded at startup."""
import itertools
import uuid

import clock

_seq = itertools.count(1)

payers = {}
patient_accounts = {}
account_transactions = {}
credit_balances = {}
root_cause_findings = {}
refund_requests = {}
refund_approvals = {}
refund_batches = {}
check_disbursements = {}
take_back_notices = {}
offset_applications = {}
medicare_obligations = {}
escheatment_records = {}
compliance_reports = {}

# id -> True for every transaction that some REVERSAL row names as its target.
reversed_transaction_ids = set()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def base_row(versioned=True):
    """Common fields (PRD 2.4). AccountTransaction / RefundApproval pass
    versioned=False: they carry only id and created_at."""
    stamp = clock.now()
    row = {"id": new_id(), "created_at": stamp, "_seq": next_seq()}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Bump version by exactly 1 and refresh updated_at (PRD 2.4 / 2.9)."""
    row["updated_at"] = clock.now()
    row["version"] = int(row.get("version", 0)) + 1
    return row


def ordered(rows):
    """Default list ordering: created_at ASC, insertion order as tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def txns_for_account(account_id):
    return ordered([t for t in account_transactions.values() if t["account_id"] == account_id])


def credit_balances_for_account(account_id):
    return ordered([c for c in credit_balances.values() if c["account_id"] == account_id])


def checks_for_request(refund_request_id):
    return ordered([c for c in check_disbursements.values()
                    if c["refund_request_id"] == refund_request_id])


def checks_for_batch(batch_id):
    return ordered([c for c in check_disbursements.values()
                    if c["refund_batch_id"] == batch_id])


def checks_for_credit_balance(credit_balance_id):
    out = []
    for chk in check_disbursements.values():
        req = refund_requests.get(chk["refund_request_id"])
        if req and req["credit_balance_id"] == credit_balance_id:
            out.append(chk)
    return ordered(out)


def offsets_for_notice(notice_id):
    return ordered([o for o in offset_applications.values()
                    if o["take_back_notice_id"] == notice_id])


def offsets_for_credit_balance(credit_balance_id):
    return ordered([o for o in offset_applications.values()
                    if o["credit_balance_id"] == credit_balance_id])


def approvals_for_request(refund_request_id):
    return ordered([a for a in refund_approvals.values()
                    if a["refund_request_id"] == refund_request_id])


def findings_for_credit_balance(credit_balance_id):
    return ordered([f for f in root_cause_findings.values()
                    if f["credit_balance_id"] == credit_balance_id])


def obligations_for_credit_balance(credit_balance_id):
    return ordered([o for o in medicare_obligations.values()
                    if o["credit_balance_id"] == credit_balance_id])


def escheatment_for_check(check_id):
    for rec in ordered(list(escheatment_records.values())):
        if rec["check_disbursement_id"] == check_id:
            return rec
    return None


def requests_for_credit_balance(credit_balance_id):
    return ordered([r for r in refund_requests.values()
                    if r["credit_balance_id"] == credit_balance_id])
