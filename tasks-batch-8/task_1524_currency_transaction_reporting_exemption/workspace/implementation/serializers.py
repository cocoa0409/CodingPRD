"""Entity serializers — exact field sets per SCAFFOLD.yaml §1.1."""
from db import parse_date_strict, public, store, today


def serialize_branch(b):
    return public(b)


def serialize_customer(c):
    return public(c)


def serialize_cash_transaction(t):
    return public(t)


def serialize_instrument_sale(s):
    return public(s)


def serialize_aggregation(row):
    return public(row)


def serialize_ctr(c):
    out = public(c)
    # While DRAFT the snapshot live-refreshes from the current aggregation.
    if c["status"] == "DRAFT":
        row = store.aggregations.get((c["customer_id"], c["business_date"]))
        if row is not None:
            out["snapshot_cash_in_cents"] = row["total_cash_in_cents"]
            out["snapshot_cash_out_cents"] = row["total_cash_out_cents"]
        else:
            out["snapshot_cash_in_cents"] = 0
            out["snapshot_cash_out_cents"] = 0
    # Read-time lateness: DRAFT/VALIDATED and current logical date past the
    # EFILE due date (always the electronic deadline, even for paper filers).
    is_late = False
    if c["status"] in ("DRAFT", "VALIDATED"):
        due = parse_date_strict(c["due_date_efile"])
        if due is not None and today() > due:
            is_late = True
    out["is_late"] = is_late
    return out


def serialize_exemption(d):
    return public(d)


def serialize_alert(a):
    return public(a)


def serialize_case(c):
    return public(c)


def serialize_finding(f):
    return public(f)


def serialize_audit_event(ev):
    # AuditEvent carries only id + created_at from the common set.
    return {
        "id": ev["id"],
        "sequence_no": ev["sequence_no"],
        "actor_role": ev["actor_role"],
        "actor_id": ev["actor_id"],
        "action": ev["action"],
        "entity_type": ev["entity_type"],
        "entity_id": ev["entity_id"],
        "details": ev["details"],
        "prev_hash": ev["prev_hash"],
        "event_hash": ev["event_hash"],
        "created_at": ev["created_at"],
    }
