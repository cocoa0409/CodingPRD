"""Continuing-education bookkeeping: attribution, successive-year suppression,
restoration and the licence CE recompute (PRD 3.2)."""
from db import db, sort_key, touch
from services import calc


def attributed_year(completion_date, reporting_period_year, is_makeup):
    """reporting_period_year is ignored for attribution unless is_makeup."""
    if is_makeup:
        return reporting_period_year
    return completion_date.year


def suppressed_at_creation(originator_id, course, year, exclude_id=None):
    """A new credit is EXCLUDED_SUCCESSIVE_YEAR when its course blocks
    successive years and an APPLIED sibling sits in exactly the prior year."""
    if not course.get("successive_year_blocked"):
        return False
    for credit in db.ce_credits.values():
        if exclude_id is not None and credit["id"] == exclude_id:
            continue
        if credit["originator_id"] != originator_id:
            continue
        if credit["ce_course_id"] != course["id"]:
            continue
        if credit["credit_status"] != "APPLIED":
            continue
        if credit["attributed_year"] == year - 1:
            return True
    return False


def restore_suppressed_by(voided):
    """Every credit sitting in EXCLUDED_SUCCESSIVE_YEAR solely because of the
    row just voided returns to APPLIED."""
    restored = []
    target_year = voided["attributed_year"]
    if target_year is None:
        return restored
    candidates = [c for c in db.ce_credits.values()
                  if c["id"] != voided["id"]
                  and c["originator_id"] == voided["originator_id"]
                  and c["ce_course_id"] == voided["ce_course_id"]
                  and c["credit_status"] == "EXCLUDED_SUCCESSIVE_YEAR"
                  and c["attributed_year"] == target_year + 1]
    candidates.sort(key=sort_key)
    for candidate in candidates:
        still_suppressed = False
        for other in db.ce_credits.values():
            if other["id"] in (voided["id"], candidate["id"]):
                continue
            if (other["originator_id"] == candidate["originator_id"]
                    and other["ce_course_id"] == candidate["ce_course_id"]
                    and other["credit_status"] == "APPLIED"
                    and other["attributed_year"] == candidate["attributed_year"] - 1):
                still_suppressed = True
                break
        if not still_suppressed:
            candidate["credit_status"] = "APPLIED"
            candidate["void_reason"] = None
            touch(candidate)
            restored.append(candidate)
    return restored


def recompute_license_ce(lic, variant):
    """Rewrite ce_hours_applied / ce_satisfied on one licence."""
    total, federal, ethics, nontraditional = calc.ce_aggregate(
        lic["originator_id"], lic["ce_reporting_year"], variant)
    satisfied = calc.ce_satisfied(total, federal, ethics, nontraditional,
                                 lic["required_ce_hours"])
    if lic["ce_hours_applied"] != total or lic["ce_satisfied"] != satisfied:
        lic["ce_hours_applied"] = total
        lic["ce_satisfied"] = satisfied
        touch(lic)
    return total, satisfied


def recompute_all_licenses(originator_id, variant):
    rows = [l for l in db.license_registrations.values()
            if l["originator_id"] == originator_id]
    rows.sort(key=sort_key)
    for lic in rows:
        recompute_license_ce(lic, variant)


def voided_credit_counted_toward(lic):
    """True when some credit that would count toward the licence's reporting
    year is sitting in VOIDED."""
    for credit in db.ce_credits.values():
        if credit["originator_id"] != lic["originator_id"]:
            continue
        if credit["credit_status"] != "VOIDED":
            continue
        if credit["attributed_year"] == lic["ce_reporting_year"]:
            return True
    return False


def default_reporting_year(originator_id):
    """The ce_reporting_year of the originator's licence with the greatest
    created_at."""
    rows = [l for l in db.license_registrations.values()
            if l["originator_id"] == originator_id]
    if not rows:
        return db.clock.year
    rows.sort(key=sort_key)
    return rows[-1]["ce_reporting_year"]


def default_required_hours(originator_id):
    rows = [l for l in db.license_registrations.values()
            if l["originator_id"] == originator_id]
    if not rows:
        return calc.DEFAULT_REQUIRED_CE_HOURS
    rows.sort(key=sort_key)
    return rows[-1]["required_ce_hours"]
