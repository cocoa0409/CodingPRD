"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only `source: input` fields appear here; all
computed/system fields are minted server-side.
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    """Generate a unique email so independent tests never collide on uniqueness."""
    return f"{prefix}-{next(_email_counter)}@x.com"


# ─── Member ───────────────────────────────────────────────────────────────
def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "email": unique_email("member"),
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


# ─── Waiver ───────────────────────────────────────────────────────────────
def create_waiver_payload(member_id: str, **overrides) -> dict:
    # minor_guardian_name is only supplied for youth members; omit by default.
    defaults = {"member_id": member_id}
    defaults.update(overrides)
    return defaults


# ─── Membership ───────────────────────────────────────────────────────────
def create_membership_payload(member_id: str, plan_tier: str = "BASIC", **overrides) -> dict:
    defaults = {"member_id": member_id, "plan_tier": plan_tier}
    defaults.update(overrides)
    return defaults


# ─── Certification ────────────────────────────────────────────────────────
def create_certification_payload(member_id: str, discipline: str = "BELAY", **overrides) -> dict:
    defaults = {"member_id": member_id, "discipline": discipline}
    defaults.update(overrides)
    return defaults


def grade_payload(knot=90, commands=85, catch=70, lower=95, **overrides) -> dict:
    defaults = {"knot": knot, "commands": commands, "catch": catch, "lower": lower}
    defaults.update(overrides)
    return defaults


# ─── Facility ─────────────────────────────────────────────────────────────
def create_facility_payload(name="Test Wall", floor_capacity=10,
                            requires_belay_cert=False, **overrides) -> dict:
    defaults = {
        "name": name,
        "floor_capacity": floor_capacity,
        "requires_belay_cert": requires_belay_cert,
    }
    defaults.update(overrides)
    return defaults


# ─── Route ────────────────────────────────────────────────────────────────
def create_route_payload(facility_id: str, grade=5, style="OVERHANG", **overrides) -> dict:
    defaults = {"facility_id": facility_id, "grade": grade, "style": style}
    defaults.update(overrides)
    return defaults


# ─── CheckIn ──────────────────────────────────────────────────────────────
def create_checkin_payload(member_id: str, facility_id: str, expected_facility_version: int,
                           entry_kind="DAY_PASS", **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "facility_id": facility_id,
        "entry_kind": entry_kind,
        "expected_facility_version": expected_facility_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Clinic ───────────────────────────────────────────────────────────────
def create_clinic_payload(title="Test Clinic", starts_at="2026-07-01T09:00:00Z",
                          ends_at="2026-07-01T11:00:00Z", seat_capacity=5, **overrides) -> dict:
    defaults = {
        "title": title,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "seat_capacity": seat_capacity,
    }
    defaults.update(overrides)
    return defaults


# ─── Enrollment ───────────────────────────────────────────────────────────
def create_enrollment_payload(clinic_id: str, member_id: str,
                              expected_clinic_version: int, **overrides) -> dict:
    defaults = {
        "clinic_id": clinic_id,
        "member_id": member_id,
        "expected_clinic_version": expected_clinic_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Rental ───────────────────────────────────────────────────────────────
def create_rental_payload(member_id: str, item_kind="HARNESS", deposit_cents=5000, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "item_kind": item_kind,
        "deposit_cents": deposit_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── Incident ─────────────────────────────────────────────────────────────
def create_incident_payload(member_id: str, facility_id: str, severity="MINOR",
                            description="Test incident", **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "facility_id": facility_id,
        "severity": severity,
        "description": description,
    }
    defaults.update(overrides)
    return defaults
