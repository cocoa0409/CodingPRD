"""Entity serializers — shape entities for API output, computing derived fields on read."""

from db import db
from response import iso_ts


def client_view(c):
    return dict(c)


def agreement_view(a):
    return dict(a)


def scanner_unit_view(s):
    return dict(s)


def shelf_slot_view(s):
    return dict(s)


def batch_view(b):
    out = dict(b)
    out["projected_storage_fee_cents"] = compute_projected_storage_fee(b)
    return out


def box_view(b):
    return dict(b)


def document_view(d):
    out = dict(d)
    out.pop("qa_failed_committed_pages", None)  # internal rework bookkeeping; not part of the schema
    return out


def scan_session_view(s):
    return dict(s)


def page_log_view(p):
    out = dict(p)
    out.pop("_seq", None)  # internal ordering tiebreak; not part of the schema
    return out


def index_record_view(r):
    return dict(r)


def access_grant_view(g):
    return dict(g)


def custody_event_view(e):
    out = dict(e)
    out.pop("_seq", None)  # internal ordering tiebreak; not part of the schema
    return out


def destruction_certificate_view(c):
    return dict(c)


def shelf_assignment_view(a):
    return dict(a)


def invoice_view(inv, recompute=True):
    """DRAFT invoices recompute subtotals on read; ISSUED+ are frozen."""
    out = dict(inv)
    if recompute and inv["status"] == "DRAFT":
        from services.pricing import compute_invoice_subtotals

        page_sub, storage_sub = compute_invoice_subtotals(inv)
        out["page_subtotal_cents"] = page_sub
        out["storage_subtotal_cents"] = storage_sub
        out["total_cents"] = page_sub + storage_sub
    return out


def get_agreement_for_client(client_id):
    for a in db.service_agreements.values():
        if a["client_id"] == client_id:
            return a
    return None


def get_batch(batch_id):
    return db.batches.get(batch_id)


def get_invoice_for_batch(batch_id):
    for inv in db.invoices.values():
        if inv["batch_id"] == batch_id:
            return inv
    return None


def compute_projected_storage_fee(batch):
    """Batch read-time projection: as_of = current logical clock."""
    from services.pricing import storage_fee_total

    if not batch.get("delivered_at"):
        return 0
    agreement = get_agreement_for_client(batch["client_id"])
    if not agreement:
        return 0
    return storage_fee_total(batch, agreement, db.current_utc)


def batch_documents(batch_id):
    return [d for d in db.documents.values() if d["batch_id"] == batch_id]


def batch_boxes(batch_id):
    return [b for b in db.boxes.values() if b["batch_id"] == batch_id]


def box_custody_events(box_id):
    evts = [e for e in db.custody_events.values() if e["box_id"] == box_id]
    evts.sort(key=lambda e: e.get("_seq", 0))
    return evts
