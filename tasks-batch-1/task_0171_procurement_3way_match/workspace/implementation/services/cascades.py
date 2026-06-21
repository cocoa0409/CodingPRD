"""Cross-entity cascade side effects shared by several workflows."""
from db import db
from services.common import touch


def cancel_open_rfqs_for_requisition(requisition_id):
    """Cascade: any OPEN RFQ for the requisition -> CANCELLED, voiding its
    SUBMITTED quotes (PRD §3.1, §3.2)."""
    for rfq in db.rfqs.values():
        if rfq["requisition_id"] == requisition_id and rfq["status"] == "OPEN":
            rfq["status"] = "CANCELLED"
            touch(rfq)
            void_submitted_quotes(rfq["id"])


def void_submitted_quotes(rfq_id):
    for q in db.quotes.values():
        if q["rfq_id"] == rfq_id and q["status"] == "SUBMITTED":
            q["status"] = "VOIDED"
            touch(q)
