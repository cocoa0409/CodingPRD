"""Helpers shared across routes that touch Participant state: LOC certification
gating with expiry, and the derived ledger recompute."""
import db
from services.common import parse_iso


def loc_certified_and_valid(participant, gate_dt):
    """PRD §3.2 / §3.4 / §3.7: the participant's active_loc_assessment_id must
    point at a CERTIFIED assessment whose expires_on is on/after gate_dt
    (date comparison). Returns True/False.

    gate_dt is a timezone-aware datetime; comparison is by calendar date.
      - enroll: gating date is the current clock date; CERTIFIED treated EXPIRED
        when clock date > expires_on.
      - capitation finalize: gating date is first day of service_month; CERTIFIED
        valid when first day of service_month <= expires_on.
    """
    aid = participant.get("active_loc_assessment_id")
    if not aid:
        return False
    assessment = db.loc_assessments.get(aid)
    if assessment is None:
        return False
    if assessment["status"] != "CERTIFIED":
        return False
    expires_on = assessment.get("expires_on")
    if not expires_on:
        return False
    exp_dt = parse_iso(expires_on)
    return gate_dt.date() <= exp_dt.date()


def recompute_ledger(participant):
    """Recompute Participant derived fields from child rows (PRD §2.6).
    ledger_billed_cents      = sum(total_billed_cents) over FINALIZED payments
    ledger_reconciled_cents  = sum(reconciled_cents)    over RECONCILED payments
    lifetime_attendance_days = count of COMPLETED attendance days
    """
    pid = participant["id"]
    billed = 0
    reconciled = 0
    for pay in db.capitation_payments.values():
        if pay["participant_id"] != pid:
            continue
        if pay["status"] == "FINALIZED":
            billed += pay["total_billed_cents"]
        elif pay["status"] == "RECONCILED":
            reconciled += pay["reconciled_cents"]
    completed = sum(
        1 for d in db.attendance_days.values()
        if d["participant_id"] == pid and d["status"] == "COMPLETED"
    )
    participant["ledger_billed_cents"] = billed
    participant["ledger_reconciled_cents"] = reconciled
    participant["lifetime_attendance_days"] = completed


def recompute_enrolled_count(program):
    """Program.enrolled_count = count of that program's ENROLLED participants
    (PRD §2.6)."""
    pid = program["id"]
    program["enrolled_count"] = sum(
        1 for p in db.participants.values()
        if p["program_id"] == pid and p["status"] == "ENROLLED"
    )
