"""Entity construction + common-field management.

Common fields (PRD §2.4):
  Physician, StateLicense, Patient, Visit, Prescription, Claim, FollowUp carry
  id, created_at, updated_at, version (version starts at 1 on creation? -> see note).
  Payer, ComplianceCheck, ClockState carry only id + created_at (no updated_at/version).

Version note (PRD §2.4): "version — an integer that begins at creation and
increments by one with every mutation." Creation is version 1; each subsequent
mutation +1. created_at/updated_at use the LOGICAL clock (db.clock_now) so that
time-sensitive ordering and follow-up/recency math read a consistent now.
"""
import db


def _stamp(record):
    """Set created_at/updated_at/version for a full (common_fields) entity."""
    now = db.iso_millis(db.clock_now())
    record["id"] = db.new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    # Internal append-order tie-break (never serialized); see db.next_seq.
    record["_seq"] = db.next_seq()
    return record


def _stamp_lean(record):
    """Set id/created_at only (Payer, ComplianceCheck)."""
    now = db.iso_millis(db.clock_now())
    record["id"] = db.new_id()
    record["created_at"] = now
    # Internal append-order tie-break (never serialized); see db.next_seq.
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mutation bump: refresh updated_at, increment version. Logical clock."""
    record["updated_at"] = db.iso_millis(db.clock_now())
    record["version"] = record.get("version", 1) + 1


def create_full(fields):
    record = dict(fields)
    return _stamp(record)


def create_lean(fields):
    record = dict(fields)
    return _stamp_lean(record)
