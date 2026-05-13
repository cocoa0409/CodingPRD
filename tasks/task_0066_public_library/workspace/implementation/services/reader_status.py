"""Reader posture recompute & active_loan_count maintenance."""
import db
from clock import now, parse_iso


ACTIVE_LOAN_STATUSES = {"BORROWED", "RENEWED", "RECALL_PENDING"}


def _effective_due_at(loan: dict):
    if loan.get("is_recalled") and loan.get("recall_due_at"):
        return parse_iso(loan["recall_due_at"])
    return parse_iso(loan["due_at"])


def has_overdue_loan(reader_id: str) -> bool:
    n = now()
    for l in db.loans.values():
        if l["reader_id"] != reader_id:
            continue
        if l["status"] not in ACTIVE_LOAN_STATUSES:
            continue
        if _effective_due_at(l) < n:
            return True
    return False


def reader_active_loan_count(reader_id: str) -> int:
    return sum(1 for l in db.loans.values()
               if l["reader_id"] == reader_id and l["status"] in ACTIVE_LOAN_STATUSES)


def reader_unpaid_fine_cents(reader_id: str) -> int:
    total = 0
    for f in db.fines.values():
        if f["reader_id"] == reader_id and f["settlement_status"] == "PENDING":
            total += f["outstanding_cents"]
    return total


def recompute_reader(reader_id: str):
    """Recompute active_loan_count, unpaid_fine_cents, and status for a reader."""
    r = db.readers.get(reader_id)
    if not r:
        return
    new_alc = reader_active_loan_count(reader_id)
    new_unpaid = reader_unpaid_fine_cents(reader_id)
    if r.get("status") == "BLACKLISTED":
        new_status = "BLACKLISTED"
    else:
        if has_overdue_loan(reader_id) or new_unpaid > 0:
            new_status = "OVERDUE"
        else:
            new_status = "NORMAL"

    changed = (
        r.get("active_loan_count") != new_alc
        or r.get("unpaid_fine_cents") != new_unpaid
        or r.get("status") != new_status
    )
    if changed:
        r["active_loan_count"] = new_alc
        r["unpaid_fine_cents"] = new_unpaid
        r["status"] = new_status
        from clock import iso
        r["updated_at"] = iso(now())
        r["version"] = r.get("version", 1) + 1
