"""Shared workflow helpers: timestamps/version bumps, ledger appends with the
global statement-staleness cascade, fiscal-year windows, list plumbing."""

from datetime import date, timedelta

import clock
import db


def now_stamp():
    return clock.now_raw()


def new_entity():
    """Common fields for a versioned primary resource."""
    ts = now_stamp()
    return {"id": db.new_id(), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": db.next_seq()}


def new_lean_entity():
    """Common fields for CommitteeVote / LedgerEntry (no updated_at/version)."""
    return {"id": db.new_id(), "created_at": now_stamp(), "_seq": db.next_seq()}


def touch(entity):
    entity["updated_at"] = now_stamp()
    entity["version"] = entity.get("version", 0) + 1


def bump_trust(trust):
    touch(trust)


def fiscal_window(trust, fiscal_year):
    """Inclusive [start, end] date window for a fiscal year."""
    m = trust["fiscal_year_end_month"]
    if m == 12:
        return date(fiscal_year, 1, 1), date(fiscal_year, 12, 31)
    end_year = fiscal_year
    # last day of end month
    if m == 12:
        end = date(end_year, 12, 31)
    else:
        end = date(end_year, m + 1, 1) - timedelta(days=1)
    start = date(end_year - 1, m, 1) + timedelta(days=32)
    start = date(start.year, start.month, 1)  # first of month after end month
    return start, end


def fiscal_year_for_date(trust, d):
    m = trust["fiscal_year_end_month"]
    if m == 12:
        return d.year
    return d.year if d.month <= m else d.year + 1


def _parse_date(s):
    return date.fromisoformat(s)


def supersede_stale_statements(trust_id, value_date_str):
    """Global staleness rule (PRD 2.6): any ledger append supersedes the trust's
    DRAFT/FINALIZED AnnualStatements whose fiscal-year window contains value_date."""
    trust = db.trusts.get(trust_id)
    if trust is None:
        return
    vd = _parse_date(value_date_str)
    fy = fiscal_year_for_date(trust, vd)
    for s in db.statements.values():
        if (s["trust_id"] == trust_id and s["fiscal_year"] == fy
                and s["status"] in ("DRAFT", "FINALIZED")):
            s["status"] = "SUPERSEDED"
            touch(s)


def append_ledger(trust_id, entry_kind, bucket, amount_cents, value_date,
                  description=None, receipt_type=None,
                  source_entity_type="MANUAL", source_entity_id=None):
    e = new_lean_entity()
    e.update({
        "trust_id": trust_id,
        "entry_kind": entry_kind,
        "bucket": bucket,
        "amount_cents": amount_cents,
        "receipt_type": receipt_type,
        "value_date": value_date,
        "description": description,
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id,
    })
    db.ledger_entries[e["id"]] = e
    supersede_stale_statements(trust_id, value_date)
    return e


def list_page(store, filters, serializer, limit, offset):
    """filters: list of (key, value) equality checks on raw records."""
    items = [r for r in store.values()
             if all(r.get(k) == v for k, v in filters)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return [serializer(r) for r in page], total


def find_trust_path(trust_id):
    """Path trust id -> ERR_TRUST_NOT_FOUND."""
    from errors import ApiError, ERR_TRUST_NOT_FOUND
    t = db.trusts.get(trust_id)
    if t is None:
        raise ApiError(ERR_TRUST_NOT_FOUND, 404, "Trust not found: %s" % trust_id)
    return t


def find_or_404(store, rid, label="Resource"):
    from errors import ApiError, ERR_RESOURCE_NOT_FOUND
    r = store.get(rid)
    if r is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "%s not found: %s" % (label, rid))
    return r
