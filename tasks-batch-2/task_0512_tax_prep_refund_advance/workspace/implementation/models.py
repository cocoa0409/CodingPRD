"""Entity construction and serialization (SCAFFOLD Table 1, PRD §2.4).

Records are plain dicts stored in db. Common system fields:
  id, created_at, updated_at, version  (all entities with common_fields: true)

`_seq` is an internal monotonic ordering key (NOT serialized) used to break
created_at ties for default ascending-by-creation sort.

Computed fields (open_return_count, assigned_open_returns, prep_fee_cents,
approved_cents, repaid_cents, net_to_taxpayer_cents, fee_shortfall_cents) are
stored on the record and kept current by their owning services."""
from db import db, new_id, created_ts


def _base_full():
    ts = created_ts()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(record):
    """Mutation bookkeeping: refresh updated_at and bump version (PRD §2.4)."""
    record["updated_at"] = created_ts()
    record["version"] = record.get("version", 1) + 1


def _clean(record):
    """Serialize a record, dropping internal keys (those starting with '_')."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def office_dict(o):
    return _clean(o)


def credential_dict(c):
    return _clean(c)


def preparer_dict(p):
    return _clean(p)


def client_dict(c):
    return _clean(c)


def appointment_dict(a):
    return _clean(a)


def return_dict(r):
    return _clean(r)


def document_dict(d):
    return _clean(d)


def fee_line_dict(f):
    return _clean(f)


def audit_protection_dict(a):
    return _clean(a)


def efile_submission_dict(e):
    return _clean(e)


def refund_transfer_dict(t):
    return _clean(t)


def refund_advance_dict(a):
    return _clean(a)


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------
def make_office(name, efin, state_code, bank_product_enabled):
    rec = _base_full()
    rec.update({
        "name": name,
        "efin": efin,
        "state_code": state_code,
        "efin_status": "ACTIVE",
        "bank_product_enabled": bool(bank_product_enabled),
        "open_return_count": 0,
    })
    db.offices[rec["id"]] = rec
    return rec


def make_credential(office_id, ptin, holder_name, expires_on):
    rec = _base_full()
    rec.update({
        "office_id": office_id,
        "ptin": ptin,
        "holder_name": holder_name,
        "status": "ACTIVE",
        "expires_on": expires_on,
    })
    db.credentials[rec["id"]] = rec
    return rec


def make_preparer(office_id, credential_id, full_name, max_open_returns):
    rec = _base_full()
    rec.update({
        "office_id": office_id,
        "credential_id": credential_id,
        "full_name": full_name,
        "assigned_open_returns": 0,
        "max_open_returns": max_open_returns,
    })
    db.preparers[rec["id"]] = rec
    return rec


def make_client(office_id, full_name, ssn_last4, risk_band, is_returning):
    rec = _base_full()
    rec.update({
        "office_id": office_id,
        "full_name": full_name,
        "ssn_last4": ssn_last4,
        "risk_band": risk_band,
        "is_returning": bool(is_returning),
    })
    db.clients[rec["id"]] = rec
    return rec


def make_appointment(office_id, client_id, preparer_id, start_utc, end_utc):
    rec = _base_full()
    rec.update({
        "office_id": office_id,
        "client_id": client_id,
        "preparer_id": preparer_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "status": "SCHEDULED",
    })
    db.appointments[rec["id"]] = rec
    return rec


def make_return(office_id, client_id, tax_year, return_kind, complexity_band,
                schedules, state_return_count, expected_refund_cents,
                amends_return_id):
    rec = _base_full()
    rec.update({
        "office_id": office_id,
        "client_id": client_id,
        "preparer_id": None,
        "amends_return_id": amends_return_id,
        "tax_year": tax_year,
        "return_kind": return_kind,
        "complexity_band": complexity_band,
        "schedules": schedules,
        "state_return_count": state_return_count,
        "expected_refund_cents": expected_refund_cents,
        "prep_fee_cents": None,
        "status": "INTAKE",
        "reject_count": 0,
    })
    db.returns[rec["id"]] = rec
    return rec


def make_document(tax_return_id, doc_type, is_required):
    rec = _base_full()
    rec.update({
        "tax_return_id": tax_return_id,
        "doc_type": doc_type,
        "is_required": bool(is_required),
        "status": "PENDING",
    })
    db.documents[rec["id"]] = rec
    return rec


def make_fee_line(tax_return_id, line_kind, label, amount_cents):
    rec = _base_full()
    rec.update({
        "tax_return_id": tax_return_id,
        "line_kind": line_kind,
        "label": label,
        "amount_cents": amount_cents,
    })
    db.fee_lines[rec["id"]] = rec
    return rec


def make_audit_protection(tax_return_id, fee_cents):
    rec = _base_full()
    rec.update({
        "tax_return_id": tax_return_id,
        "fee_cents": fee_cents,
        "status": "ACTIVE",
    })
    db.audit_protections[rec["id"]] = rec
    return rec


def make_efile_submission(tax_return_id, efin_used, ptin_used):
    rec = _base_full()
    rec.update({
        "tax_return_id": tax_return_id,
        "efin_used": efin_used,
        "ptin_used": ptin_used,
        "ack_status": "TRANSMITTED",
        "reject_code": None,
    })
    db.efile_submissions[rec["id"]] = rec
    return rec


def make_refund_transfer(tax_return_id, estimated_refund_cents):
    rec = _base_full()
    rec.update({
        "tax_return_id": tax_return_id,
        "bank_product_fee_cents": 3995,
        "estimated_refund_cents": estimated_refund_cents,
        "disbursed_refund_cents": None,
        "net_to_taxpayer_cents": None,
        "fee_shortfall_cents": None,
        "status": "PENDING_FUNDING",
    })
    db.refund_transfers[rec["id"]] = rec
    return rec


def make_refund_advance(tax_return_id, requested_cents):
    rec = _base_full()
    rec.update({
        "tax_return_id": tax_return_id,
        "requested_cents": requested_cents,
        "approved_cents": None,
        "repaid_cents": 0,
        "status": "REQUESTED",
    })
    db.refund_advances[rec["id"]] = rec
    return rec
