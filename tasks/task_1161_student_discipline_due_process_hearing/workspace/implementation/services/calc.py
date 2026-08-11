"""Calculation rules (SCAFFOLD.yaml §1.3 / PRD §3)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, clock, stamp
from util import academic_year_start

# Statuses whose cases count as priors for occurrence counting
PRIOR_STATUSES = {
    "CLASSIFIED",
    "SANCTION_PROPOSED",
    "NOTICE_ISSUED",
    "CONFIRMED",
    "EXPULSION_REFERRED",
    "EXPULSION_ACTIVE",
    "CLOSED",
}

OCCURRENCE_WINDOW_DAYS = 365
BAND_CAP_INDEX = 3
SUSPENSION_CAP_DAYS = 10
MDR_THRESHOLD_DAYS = 10
MDR_DUE_DAYS = 10
EXPUNGEMENT_WAIT_DAYS = 730

DEMOGRAPHIC_GROUPS = ["ASIAN", "BLACK", "HISPANIC", "WHITE", "MULTIRACIAL", "OTHER"]


def offense_category(offense_code_id):
    oc = db.offense_codes.get(offense_code_id)
    return oc["category"] if oc else None


def compute_occurrence(case, offense):
    """Returns (occurrence_index, occurrence_index_ay) — both uncapped count+1."""
    priors = [
        c
        for c in db.cases.values()
        if c["student_id"] == case["student_id"]
        and c["id"] != case["id"]
        and c["status"] in PRIOR_STATUSES
        and c.get("offense_code_id")
        and offense_category(c["offense_code_id"]) == offense["category"]
    ]
    incident = case["incident_date"]
    window_lo = incident - timedelta(days=OCCURRENCE_WINDOW_DAYS)
    rolling = sum(1 for c in priors if window_lo <= c["incident_date"] < incident)
    ay = academic_year_start(incident)
    ay_count = sum(1 for c in priors if academic_year_start(c["incident_date"]) == ay)
    return rolling + 1, ay_count + 1


def find_band(offense_code_id, occurrence_index):
    for b in db.sanction_bands.values():
        if (
            b["offense_code_id"] == offense_code_id
            and b["occurrence_index"] == occurrence_index
        ):
            return b
    return None


def recompute_ledger(student):
    """cumulative_suspension_days = SUM(sanction_days_final) over the student's
    cases with status IN {CONFIRMED, CLOSED} (PRD §2.7)."""
    student["cumulative_suspension_days"] = sum(
        (c["sanction_days_final"] or 0)
        for c in db.cases.values()
        if c["student_id"] == student["id"] and c["status"] in ("CONFIRMED", "CLOSED")
    )


def open_mdr_exists(case_id):
    return any(
        m["case_id"] == case_id and m["status"] in ("PENDING", "SCHEDULED")
        for m in db.mdrs.values()
    )


def completed_mdr_exists(case_id):
    return any(
        m["case_id"] == case_id and m["status"] == "COMPLETED"
        for m in db.mdrs.values()
    )


def create_mdr(case_id, origin):
    mdr = stamp(
        {
            "case_id": case_id,
            "origin": origin,
            "due_at": clock() + timedelta(days=MDR_DUE_DAYS),
            "meeting_at": None,
            "status": "PENDING",
            "outcome": None,
            "completed_at": None,
        }
    )
    db.mdrs[mdr["id"]] = mdr
    return mdr


def current_issued_notice(case_id):
    """The case's ISSUED notice (at most one can exist at a time)."""
    issued = [
        n
        for n in db.notices.values()
        if n["case_id"] == case_id and n["status"] == "ISSUED"
    ]
    if not issued:
        return None
    return max(issued, key=lambda n: n["_seq"])


def seats_occupied(site):
    """Placements of the site in {PLACED, ACTIVE} whose closed date interval
    [start_date, planned_end_date] covers the current clock day."""
    today = clock().date()
    return sum(
        1
        for p in db.placements.values()
        if p["site_id"] == site["id"]
        and p["status"] in ("PLACED", "ACTIVE")
        and p["start_date"].date() <= today <= p["planned_end_date"].date()
    )


def disproportionality(academic_year, reference_group):
    """PRD §3.9. Division at full precision, round half-up only for display."""
    from errors import raise_err, ERR_INVALID_REFERENCE_GROUP

    from datetime import datetime

    from util import UTC

    y1 = academic_year
    win_start = datetime(y1, 7, 1, tzinfo=UTC)
    win_end = datetime(y1 + 1, 7, 1, tzinfo=UTC)

    enrolled = {g: 0 for g in DEMOGRAPHIC_GROUPS}
    for s in db.students.values():
        enrolled[s["demographic_group"]] += 1

    disciplined = {g: set() for g in DEMOGRAPHIC_GROUPS}
    for c in db.cases.values():
        if c["status"] in ("CONFIRMED", "CLOSED") and win_start <= c["incident_date"] < win_end:
            st = db.students.get(c["student_id"])
            if st is not None:
                disciplined[st["demographic_group"]].add(st["id"])
    disc_count = {g: len(disciplined[g]) for g in DEMOGRAPHIC_GROUPS}

    total_enrolled = sum(enrolled.values())
    total_disciplined = sum(disc_count.values())

    if enrolled[reference_group] == 0 or disc_count[reference_group] == 0:
        raise_err(
            ERR_INVALID_REFERENCE_GROUP,
            "reference_group has zero enrolled or zero disciplined students",
        )

    risk_ref = Decimal(disc_count[reference_group]) / Decimal(enrolled[reference_group])
    results = []
    for g in DEMOGRAPHIC_GROUPS:
        if enrolled[g] == 0:
            continue
        risk_g = Decimal(disc_count[g]) / Decimal(enrolled[g])
        risk = float(risk_g.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        risk_ratio = float((risk_g / risk_ref).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        share = Decimal(disc_count[g]) / Decimal(total_disciplined) - Decimal(
            enrolled[g]
        ) / Decimal(total_enrolled)
        share_gap = float(share.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        results.append(
            {
                "demographic_group": g,
                "enrolled": enrolled[g],
                "disciplined": disc_count[g],
                "risk": risk,
                "risk_ratio": risk_ratio,
                "share_gap": share_gap,
            }
        )
    return {
        "academic_year": f"{y1}-{y1 + 1}",
        "reference_group": reference_group,
        "groups_evaluated": len(results),
        "results": results,
    }
