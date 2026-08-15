"""Cross-entity cascades and shared workflow helpers (PRD §3)."""
from datetime import timedelta
from decimal import Decimal

import db
from clock import now_dt, now_iso, to_iso
from services import calc


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def recompute_application_scores(application: dict):
    """Recompute rubric_complete / rubric_score / composite after a rubric
    score post or an interview scoring (§3.1)."""
    complete, rubric = calc.compute_rubric(application["review_scores"])
    application["rubric_complete"] = complete
    application["rubric_score"] = rubric
    composite, variant = calc.compute_composite(rubric, application.get("interview_score"))
    application["composite_score"] = composite
    application["composite_variant"] = variant


def scored_interview_for(application_id: str):
    for iv in db.all_records("interviews"):
        if iv["application_id"] == application_id and iv["status"] == "SCORED":
            return iv
    return None


def cancel_scheduled_interviews(application_id: str):
    """DENIED side effect: any SCHEDULED CapacityInterview -> CANCELLED."""
    for iv in db.all_records("interviews"):
        if iv["application_id"] == application_id and iv["status"] == "SCHEDULED":
            iv["status"] = "CANCELLED"
            db.touch(iv)


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------

def set_school_standings_from_report(school: dict, report: dict):
    """Monitoring accept cascade link 1 (§3.3)."""
    school["academic_standing"] = calc.standing_band(report["academic_score"])
    school["financial_standing"] = calc.standing_band(report["financial_score"])
    school["operational_standing"] = calc.standing_band(report["operational_score"])
    db.touch(school)


def auto_issue_probation_notices(school: dict, report: dict, acceptor_user_id: str):
    """Monitoring accept cascade link 2 (§3.3): for each domain newly left in
    PROBATION or CRITICAL with no open (DRAFT|ISSUED) notice for that
    (school, domain), auto-create an InterventionNotice level=PROBATION,
    status=ISSUED, issued_by_user_id=acceptor, due = clock + 30 days."""
    domains = [
        ("ACADEMIC", school["academic_standing"]),
        ("FINANCIAL", school["financial_standing"]),
        ("OPERATIONAL", school["operational_standing"]),
    ]
    for domain, band in domains:
        if band not in ("PROBATION", "CRITICAL"):
            continue
        open_existing = any(
            n["school_id"] == school["id"]
            and n["domain"] == domain
            and n["status"] in ("DRAFT", "ISSUED")
            for n in db.all_records("interventions")
        )
        if open_existing:
            continue
        notice = db.stamp_new({
            "school_id": school["id"],
            "level": "PROBATION",
            "domain": domain,
            "reason": "Auto-created from accepted monitoring report",
            "issued_by_user_id": acceptor_user_id,
            "resolved_by_user_id": None,
            "corrective_due_date": to_iso(now_dt() + timedelta(days=30)),
            "successor_notice_id": None,
            "status": "ISSUED",
        })
        db.insert("interventions", notice)


def school_to_closing(school: dict):
    """School OPEN -> CLOSING with the lottery cancellation cascade (§3.4)."""
    if school["status"] != "OPEN":
        return
    school["status"] = "CLOSING"
    db.touch(school)
    cancel_open_lotteries(school["id"])


def cancel_open_lotteries(school_id: str):
    """Every Lottery in DRAFT|OPEN|SEALED -> CANCELLED; entries VOIDED."""
    for lottery in db.all_records("lotteries"):
        if lottery["school_id"] != school_id:
            continue
        if lottery["status"] in ("DRAFT", "OPEN", "SEALED"):
            lottery["status"] = "CANCELLED"
            db.touch(lottery)
            for entry in db.all_records("lottery_entries"):
                if entry["lottery_id"] == lottery["id"] and entry["outcome"] in (
                    "ENTERED",
                    "WAITLISTED",
                    "OFFERED",
                ):
                    entry["outcome"] = "VOIDED"
                    db.touch(entry)


def school_to_closed(school: dict):
    """School CLOSING -> CLOSED side effects (§3.7): ACTIVE contract ->
    REVOKED; open notices (DRAFT|ISSUED) -> MOOT."""
    school["status"] = "CLOSED"
    db.touch(school)
    for contract in db.all_records("contracts"):
        if contract["school_id"] == school["id"] and contract["status"] == "ACTIVE":
            contract["status"] = "REVOKED"
            db.touch(contract)
    for notice in db.all_records("interventions"):
        if notice["school_id"] == school["id"] and notice["status"] in ("DRAFT", "ISSUED"):
            notice["status"] = "MOOT"
            db.touch(notice)


def upgrade_school_standing(school: dict, domain: str):
    """Notice resolve side effect (§3.5): lift the domain standing one step."""
    field = {
        "ACADEMIC": "academic_standing",
        "FINANCIAL": "financial_standing",
        "OPERATIONAL": "operational_standing",
        "COMPLIANCE": None,
    }.get(domain)
    if field is None:
        return
    school[field] = calc.upgrade_one_step(school[field])
    db.touch(school)


# ---------------------------------------------------------------------------
# Renewal eligibility (§3.6)
# ---------------------------------------------------------------------------

def compute_eligible_term_years(school: dict, contract: dict) -> int:
    term_start_year = int(str(contract["term_start"])[:4])
    term_end_year = int(str(contract["term_end"])[:4])
    indices = [
        r["compliance_index"]
        for r in db.all_records("monitoring_reports")
        if r["school_id"] == school["id"]
        and r["status"] == "ACCEPTED"
        and term_start_year <= r["fiscal_year"] <= term_end_year
    ]
    if indices:
        avg_index = calc.round1(sum(Decimal(str(v)) for v in indices) / Decimal(len(indices)))
    else:
        avg_index = 0.0

    from clock import parse as parse_iso

    term_start_dt = parse_iso(contract["term_start"])
    term_end_dt = parse_iso(contract["term_end"])
    probation_count = 0
    for n in db.all_records("interventions"):
        if n["school_id"] != school["id"]:
            continue
        if n["level"] not in ("PROBATION", "REVOCATION_REVIEW"):
            continue
        created = parse_iso(n["created_at"])
        if term_start_dt <= created <= term_end_dt:
            probation_count += 1

    standings = [school["academic_standing"], school["financial_standing"], school["operational_standing"]]

    if avg_index >= 90.0 and probation_count == 0 and all(s == "GOOD" for s in standings):
        return 10
    if avg_index >= 75.0 and all(s != "CRITICAL" for s in standings):
        return 5
    if avg_index >= 60.0:
        return 3
    return 0
