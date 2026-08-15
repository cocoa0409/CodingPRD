"""Certification queries (PRD §3.2). Constants per SCAFFOLD calculations."""
from db import store

TEST_TYPES = ["ETHICS", "INTAKE_QR", "BASIC", "ADVANCED"]
PASS_SCORE = 80
CURRENT_SEASON = 2026


def current_cert(volunteer_id, test_type, season=CURRENT_SEASON):
    """The CURRENT Certification row for (volunteer, test_type, season), or None."""
    for c in store.certifications.values():
        if (c["volunteer_id"] == volunteer_id and c["test_type"] == test_type
                and c["tax_season"] == season and c["status"] == "CURRENT"):
            return c
    return None


def has_current_passed(volunteer_id, test_type, season=CURRENT_SEASON):
    c = current_cert(volunteer_id, test_type, season)
    return c is not None and c["passed"]


def certified_test_types(volunteer_id):
    """Computed view: test types with a CURRENT passed certification for 2026."""
    return [t for t in TEST_TYPES if has_current_passed(volunteer_id, t)]


def preparer_certified(volunteer, has_advanced_scope_items):
    """Return-creation gate (tier 6b): ACTIVE + CURRENT passed ETHICS+BASIC
    (+ADVANCED when the return carries advanced-scope items), season 2026."""
    if volunteer is None or volunteer["status"] != "ACTIVE":
        return False
    if not has_current_passed(volunteer["id"], "ETHICS"):
        return False
    if not has_current_passed(volunteer["id"], "BASIC"):
        return False
    if has_advanced_scope_items and not has_current_passed(volunteer["id"], "ADVANCED"):
        return False
    return True


def reviewer_certified(volunteer):
    """Quality-review gate (tier 6c): ACTIVE + CURRENT passed INTAKE_QR+ADVANCED."""
    if volunteer is None or volunteer["status"] != "ACTIVE":
        return False
    return (has_current_passed(volunteer["id"], "INTAKE_QR")
            and has_current_passed(volunteer["id"], "ADVANCED"))
