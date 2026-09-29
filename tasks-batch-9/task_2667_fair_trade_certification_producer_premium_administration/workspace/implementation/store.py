"""In-memory store. Empty at boot; every row arrives through the API."""
from flask import g

from common import next_seq, now_iso
from errors import ApiError

holders = {}
nodes = {}
committees = {}
funds = {}
entries = {}
transactions = {}
reports = {}
proposals = {}
votes = {}
audits = {}
nonconformities = {}
marks = {}

ALL = (holders, nodes, committees, funds, entries, transactions, reports,
       proposals, votes, audits, nonconformities, marks)


def reset():
    for table in ALL:
        table.clear()


def stamp_new(row):
    """Attach the four system-managed properties of PRD 2.5."""
    row["created_at"] = now_iso()
    row["updated_at"] = row["created_at"]
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def stamp_event(row):
    """Append-only events carry only id and created_at (PRD 2.5)."""
    row["created_at"] = now_iso()
    row["_seq"] = next_seq()
    return row


def touch(row):
    """A mutation: refresh updated_at and bump version by exactly 1."""
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1
    return row


def touch_once(row):
    """Bump a row at most once for the whole request.

    Cascades may reach the same row down two different paths; PRD 2.5 counts a
    request as one mutation of that row, so the bump is idempotent per request.
    """
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    if seen is None:
        seen = set()
        try:
            g._touched = seen
        except RuntimeError:
            pass
    key = id(row)
    if key in seen:
        return row
    seen.add(key)
    return touch(row)


def ordered(rows):
    """Deterministic sibling ordering: created_at ASC, insertion order to break ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def by_id(table, row_id, error_id):
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id, "%s: %s" % (error_id, row_id))
    return row


def holder_or_404(holder_id):
    return by_id(holders, holder_id, "ERR_HOLDER_NOT_FOUND")


def node_or_404(node_id):
    return by_id(nodes, node_id, "ERR_NODE_NOT_FOUND")


def committee_or_404(committee_id):
    return by_id(committees, committee_id, "ERR_COMMITTEE_NOT_FOUND")


def proposal_or_404(proposal_id):
    return by_id(proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")


def transaction_or_404(tx_id):
    return by_id(transactions, tx_id, "ERR_TRANSACTION_NOT_FOUND")


def report_or_404(report_id):
    return by_id(reports, report_id, "ERR_VOLUME_REPORT_NOT_FOUND")


def audit_or_404(audit_id):
    return by_id(audits, audit_id, "ERR_AUDIT_NOT_FOUND")


def nonconformity_or_404(nc_id):
    return by_id(nonconformities, nc_id, "ERR_NONCONFORMITY_NOT_FOUND")


def entry_or_404(entry_id):
    return by_id(entries, entry_id, "ERR_LEDGER_ENTRY_NOT_FOUND")


def mark_or_404(mark_id):
    return by_id(marks, mark_id, "ERR_MARK_REQUEST_NOT_FOUND")


def fund_of(holder_id):
    """A holder's premium fund; only PRODUCER_ORG holders ever have one."""
    matches = [f for f in funds.values() if f["holder_id"] == holder_id]
    return ordered(matches)[0] if matches else None


def live_committee_of(holder_id):
    matches = [c for c in committees.values()
               if c["holder_id"] == holder_id and c["status"] != "DISSOLVED"]
    return ordered(matches)[0] if matches else None


def nodes_of(holder_id):
    return ordered([n for n in nodes.values() if n["holder_id"] == holder_id])


def audits_of(holder_id):
    return ordered([a for a in audits.values() if a["holder_id"] == holder_id])


def findings_of_audit(audit_id):
    return ordered([n for n in nonconformities.values() if n["audit_id"] == audit_id])


def findings_of_holder(holder_id):
    out = []
    for audit in audits_of(holder_id):
        out.extend(findings_of_audit(audit["id"]))
    return ordered(out)


def txs_of_seller(node_id):
    return ordered([t for t in transactions.values() if t["seller_node_id"] == node_id])
