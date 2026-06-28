"""Payload factories — one per entity, input fields only (Country Club Membership API)."""


def create_club_payload(**overrides) -> dict:
    """POST /clubs. Only `name` is required; the three policy knobs are optional
    (PRD §3.1: fb_minimum_carryover_allowed, resignation_refund_pct,
    guest_visits_cap_per_period, which carry server-side defaults)."""
    payload = {"name": "Test Club"}
    payload.update(overrides)
    return payload


def create_category_payload(**overrides) -> dict:
    """POST /membership-categories (PRD §3.1). allows_golf is optional (defaults
    false); every other field below is required."""
    payload = {
        "club_id": None,
        "code": "SOCIAL",
        "initiation_fee_cents": 0,
        "refundable_equity_cents": 0,
        "monthly_dues_cents": 15000,
        "fb_minimum_cents": 0,
        "capacity": 50,
        "guest_fee_cents": 5000,
    }
    payload.update(overrides)
    return payload


def create_membership_payload(**overrides) -> dict:
    """POST /memberships (PRD §3.2). primary_member_id optional self-reference."""
    payload = {
        "club_id": None,
        "category_id": None,
        "holder_name": "Test Holder",
    }
    payload.update(overrides)
    return payload


def create_resource_payload(**overrides) -> dict:
    """POST /resources (PRD §3.1). turnaround_minutes and seat_capacity optional."""
    payload = {
        "club_id": None,
        "kind": "COURT",
        "label": "Test Resource",
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(**overrides) -> dict:
    """POST /reservations (PRD §3.4). party_size optional (defaults 1);
    expected_resource_version is non-optional (PRD §2.8)."""
    payload = {
        "club_id": None,
        "resource_id": None,
        "membership_id": None,
        "starts_at": "2026-02-01T10:00:00Z",
        "ends_at": "2026-02-01T11:00:00Z",
        "expected_resource_version": None,
    }
    payload.update(overrides)
    return payload


def propose_amend_payload(**overrides) -> dict:
    """POST /reservations/{id}/propose-amend (PRD §3.4)."""
    payload = {
        "proposed_starts_at": "2026-02-01T12:00:00Z",
        "proposed_ends_at": "2026-02-01T13:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_chit_payload(**overrides) -> dict:
    """POST /chits (PRD §3.5)."""
    payload = {
        "club_id": None,
        "membership_id": None,
        "amount_cents": 5000,
        "kind": "DINING",
    }
    payload.update(overrides)
    return payload


def create_guest_pass_payload(**overrides) -> dict:
    """POST /guest-passes (PRD §3.5)."""
    payload = {
        "club_id": None,
        "sponsor_membership_id": None,
        "guest_name": "Test Guest",
        "visit_date": "2026-01-05T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(**overrides) -> dict:
    """POST /capital-assessments (PRD §3.5)."""
    payload = {
        "club_id": None,
        "description": "Test Assessment",
        "total_target_cents": 100000,
        "allocation_basis": "EQUAL",
    }
    payload.update(overrides)
    return payload


def create_waitlist_entry_payload(**overrides) -> dict:
    """POST /waitlist-entries (PRD §3.2)."""
    payload = {
        "club_id": None,
        "category_id": None,
        "applicant_name": "Test Applicant",
    }
    payload.update(overrides)
    return payload


def payment_payload(**overrides) -> dict:
    """POST /memberships/{id}/payments (PRD §3.6)."""
    payload = {"amount_cents": 1000}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc (PRD §3.8)."""
    return {"to_iso8601": to_iso8601}
