"""Record factories and mutation helpers (PRD §2.4, §2.5).

Common fields: id (UUID, no prefix), created_at, updated_at (ISO 8601 UTC, 3
fractional digits), version (int starting at 1, +1 on every mutation). Payment is
the exception — id + created_at only.

bump(record) refreshes updated_at and increments version. It is invoked
independently on EVERY mutated resource (cascades bump each child resource).
"""

from db import db, new_id, now_ts


def _base():
    ts = now_ts()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def bump(record):
    """Refresh updated_at and increment version on a mutated resource."""
    record["updated_at"] = now_ts()
    record["version"] = record["version"] + 1


# ----------------------------------------------------------------------------
# Factories
# ----------------------------------------------------------------------------

def make_account(account_type, legal_name, state_code, credit_terms,
                 credit_limit_cents):
    rec = _base()
    rec.update({
        "account_type": account_type,
        "legal_name": legal_name,
        "state_code": state_code,
        "credit_terms": credit_terms,
        "credit_limit_cents": credit_limit_cents,
        "ytd_completed_count": 0,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    })
    db.accounts[rec["id"]] = rec
    return rec


def make_fee_schedule(state_code, title_fee_cents, registration_fee_cents,
                      transfer_fee_cents, lien_recording_fee_cents,
                      use_tax_rate_bps, trade_in_credit_allowed):
    rec = _base()
    rec.update({
        "state_code": state_code,
        "title_fee_cents": title_fee_cents,
        "registration_fee_cents": registration_fee_cents,
        "transfer_fee_cents": transfer_fee_cents,
        "lien_recording_fee_cents": lien_recording_fee_cents,
        "use_tax_rate_bps": use_tax_rate_bps,
        "trade_in_credit_allowed": trade_in_credit_allowed,
        "status": "ACTIVE",
    })
    db.fee_schedules[rec["id"]] = rec
    return rec


def make_transaction(account_id, transaction_type, vin, declared_price_cents,
                     trade_in_allowance_cents, expedite):
    rec = _base()
    rec.update({
        "account_id": account_id,
        "transaction_type": transaction_type,
        "vin": vin,
        "declared_price_cents": declared_price_cents,
        "trade_in_allowance_cents": trade_in_allowance_cents,
        "expedite": expedite,
        "lifecycle_status": "DRAFT",
        "document_status": "COLLECTING",
        "rejection_round": 0,
        "active_quote_id": None,
        "submitted_by_user_id": None,
    })
    db.transactions[rec["id"]] = rec
    return rec


def make_document_item(transaction_id, checklist_code, file_ref):
    rec = _base()
    rec.update({
        "transaction_id": transaction_id,
        "checklist_code": checklist_code,
        "doc_status": "PENDING",
        "file_ref": file_ref,
    })
    db.document_items[rec["id"]] = rec
    return rec


def make_fee_quote(transaction_id, variant, schedule_id, components, status):
    rec = _base()
    rec.update({
        "transaction_id": transaction_id,
        "variant": variant,
        "schedule_id": schedule_id,
        "tax_cents": components["tax_cents"],
        "state_fees_cents": components["state_fees_cents"],
        "service_fee_cents": components["service_fee_cents"],
        "total_cents": components["total_cents"],
        "status": status,
    })
    db.fee_quotes[rec["id"]] = rec
    return rec


def make_submission(transaction_id, priority_class, sla_deadline_at):
    rec = _base()
    rec.update({
        "transaction_id": transaction_id,
        "submission_status": "QUEUED",
        "priority_class": priority_class,
        "sla_deadline_at": sla_deadline_at,
        "leg_id": None,
        "rejection_reason": None,
    })
    db.submissions[rec["id"]] = rec
    return rec


def make_runner_trip(dmv_office_code, capacity, window_start_at, window_end_at):
    rec = _base()
    rec.update({
        "dmv_office_code": dmv_office_code,
        "trip_status": "PLANNED",
        "capacity": capacity,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "assigned_leg_count": 0,
    })
    db.runner_trips[rec["id"]] = rec
    return rec


def make_runner_leg(trip_id, submission_id, sequence_index):
    rec = _base()
    rec.update({
        "trip_id": trip_id,
        "submission_id": submission_id,
        "leg_status": "ATTACHED",
        "sequence_index": sequence_index,
    })
    db.runner_legs[rec["id"]] = rec
    return rec


def make_lien_packet(transaction_id, lender_name, lien_amount_cents):
    rec = _base()
    rec.update({
        "transaction_id": transaction_id,
        "lender_name": lender_name,
        "lien_amount_cents": lien_amount_cents,
        "packet_status": "DRAFT",
        "perfected_by_user_id": None,
    })
    db.lien_packets[rec["id"]] = rec
    return rec


def make_payment(account_id, transaction_id, amount_cents, kind):
    # Payment has NO updated_at/version (PRD §2.4). Keep _seq for stable sort.
    rec = {
        "id": new_id(),
        "created_at": now_ts(),
        "_seq": db.next_seq(),
        "account_id": account_id,
        "transaction_id": transaction_id,
        "amount_cents": amount_cents,
        "kind": kind,
    }
    db.payments[rec["id"]] = rec
    return rec
