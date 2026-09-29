"""Audit pricing helpers shared by the manual and automatic issuance paths."""
from db import db, stamp_new
from services import calc


def new_audit_row(club_id, case_id=None, sideline_evaluation_id=None,
                  opened_by_user_id=None, auto_opened=False):
    row = {
        "club_id": club_id,
        "case_id": case_id,
        "sideline_evaluation_id": sideline_evaluation_id,
        "opened_by_user_id": opened_by_user_id,
        "auto_opened": auto_opened,
        "status": "OPEN",
        "violation_codes": [],
        "exposure_days": 0,
        "escalation_tier_at_issuance": None,
        "assessed_fine_cents": 0,
        "response_round_count": 0,
        "club_response_note": None,
        "findings_issued_by_user_id": None,
        "closed_by_user_id": None,
        "closing_note": None,
        "disposition": "PENDING",
        "findings_issued_at": None,
        "closed_at": None,
    }
    stamp_new(row)
    db.protocol_audits[row["id"]] = row
    return row


def open_auto_issued_audit(club_id, violation_codes, case_id=None,
                           sideline_evaluation_id=None, exposure_days=0):
    """Open an audit on the system's own initiative and take it straight to
    FINDINGS_ISSUED (PRD §3.9 late filing, §3.11 sweep breaches)."""
    audit = new_audit_row(
        club_id,
        case_id=case_id,
        sideline_evaluation_id=sideline_evaluation_id,
        opened_by_user_id=None,
        auto_opened=True,
    )
    tier = calc.tier_for_score(calc.preliminary_score(club_id, exclude_audit_id=audit["id"]))
    audit["escalation_tier_at_issuance"] = tier
    audit["violation_codes"] = list(violation_codes)
    audit["exposure_days"] = exposure_days
    audit["assessed_fine_cents"] = calc.compute_fine_cents(audit, tier)
    audit["status"] = "FINDINGS_ISSUED"
    audit["findings_issued_at"] = db.now
    audit["findings_issued_by_user_id"] = None
    return audit
