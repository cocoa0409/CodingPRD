"""Domain helpers: record construction, mutation/versioning, and recomputes."""
from db import db, new_id, now_iso, next_seq


def base_record(common_fields=True):
    """Allocate the common system-managed fields. common_fields=False is the
    append-only KeyAuthorizationRecord (id + created_at only)."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if common_fields:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(record):
    """Apply a real mutation: refresh updated_at and bump version (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1


# ----- Money recompute (scaffold §1.3 job_net_paid_cents) -----
def recompute_net_paid(job):
    """net_paid = sum(captured for CAPTURED) - sum(refunded for REFUNDED)."""
    job_id = job["id"]
    captured = 0
    refunded = 0
    for p in db.payments.values():
        if p["service_job_id"] != job_id:
            continue
        if p["status"] == "CAPTURED":
            captured += p["captured_amount_cents"]
        elif p["status"] == "REFUNDED":
            refunded += p["refunded_amount_cents"]
    job["net_paid_cents"] = captured - refunded


# ----- Inventory recompute (scaffold §1.3 lockpart_unit_ledger) -----
def recompute_lockpart_units(part):
    """units_reserved/committed/available from this part's reservations."""
    part_id = part["id"]
    reserved = 0
    committed = 0
    for r in db.reservations.values():
        if r["lock_part_id"] != part_id:
            continue
        if r["status"] == "RESERVED":
            reserved += r["quantity"]
        elif r["status"] == "COMMITTED":
            committed += r["quantity"]
    part["units_reserved"] = reserved
    part["units_committed"] = committed
    part["units_available"] = part["units_total"] - reserved - committed
