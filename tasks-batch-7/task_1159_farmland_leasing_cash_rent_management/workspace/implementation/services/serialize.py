"""Serialize stored records (datetimes internally) to JSON-safe dicts (ISO strings)."""
from db import to_iso

# Fields that are datetimes (or null datetimes) per entity
DATETIME_FIELDS = {
    "landlord": [],
    "tenant": [],
    "field": [],
    "offering": ["term_start_date", "bid_deadline"],
    "bid": ["accepted_at"],
    "lease": ["term_start_date", "term_end_date", "current_notice_deadline"],
    "installment": ["due_date", "last_payment_at"],
    "settlement": [],
    "expense": ["incurred_date", "approved_at"],
    "compliance": ["due_date", "cure_deadline", "noncompliant_at"],
    "improvement": ["completed_at"],
    "notice": ["served_date", "statutory_deadline", "effective_date"],
    "report": ["period_start", "period_end", "sent_at", "ack_due_date", "acknowledged_at"],
}


def serialize(kind, rec):
    out = {}
    dt_fields = set(DATETIME_FIELDS.get(kind, []))
    for k, v in rec.items():
        if k in dt_fields:
            out[k] = to_iso(v) if v is not None else None
        elif k == "conservation_practices" and v is not None:
            out[k] = [
                {
                    "practice_type": p.get("practice_type"),
                    "due_date": to_iso(p["due_date"]) if p.get("due_date") is not None else None,
                }
                for p in v
            ]
        else:
            out[k] = v
    return out
