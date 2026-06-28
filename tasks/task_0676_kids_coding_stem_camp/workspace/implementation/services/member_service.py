"""Member-related computations: age, active_badge_count recompute."""
from clock import clock
from db import db


def compute_age_years(member):
    """Whole completed years from birth_date to the logical clock 'now'."""
    from validators import parse_iso
    birth = parse_iso(member["birth_date"], "birth_date")
    now = clock.now()
    years = now.year - birth.year
    # Subtract one if the birthday hasn't occurred yet this year.
    if (now.month, now.day) < (birth.month, birth.day):
        years -= 1
    return years


def recompute_active_badge_count(member):
    """Count of distinct ACTIVE BadgeAward rows for this member whose underlying
    Badge.status == ACTIVE and Badge.belt_level_id == member.current_belt_level_id.

    Returns True if the value changed.
    """
    current_belt = member["current_belt_level_id"]
    count = 0
    for award in db.badge_awards.values():
        if award["status"] != "ACTIVE":
            continue
        enrollment = db.enrollments.get(award["enrollment_id"])
        if enrollment is None or enrollment["member_id"] != member["id"]:
            continue
        badge = db.badges.get(award["badge_id"])
        if badge is None or badge["status"] != "ACTIVE":
            continue
        if badge["belt_level_id"] != current_belt:
            continue
        count += 1
    changed = member["active_badge_count"] != count
    member["active_badge_count"] = count
    return changed
