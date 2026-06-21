"""Payload factories — one per entity, input fields only.

Each factory returns the request body for a create/transition endpoint.
Only fields the PRD marks as caller-supplied input appear here; system-managed
and computed fields are never sent.
"""

DEFAULTS = {
    "RECEIVED_AT": "2026-01-05T00:00:00.000Z",   # Monday
    "SUBJECT": "Records sought",
}


# ─── Actor registration ───────────────────────────────
def create_officer_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Officer", "badge_id": "BADGE-1"}
    defaults.update(overrides)
    return defaults


def create_appeal_authority_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Authority", "badge_id": "AUTH-1"}
    defaults.update(overrides)
    return defaults


def create_requester_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Requester",
        "email": "requester@example.com",
        "declared_category": "OTHER",
    }
    defaults.update(overrides)
    return defaults


def create_submitter_payload(**overrides) -> dict:
    defaults = {"company_name": "Test Submitter LLC", "contact_email": "submitter@example.com"}
    defaults.update(overrides)
    return defaults


# ─── Request intake ───────────────────────────────────
def create_request_payload(requester_id, **overrides) -> dict:
    defaults = {
        "requester_id": requester_id,
        "subject_description": DEFAULTS["SUBJECT"],
        "received_at": DEFAULTS["RECEIVED_AT"],
    }
    defaults.update(overrides)
    return defaults


def perfect_request_payload(fee_category="OTHER", **overrides) -> dict:
    defaults = {"fee_category": fee_category}
    defaults.update(overrides)
    return defaults


# ─── Records & exemptions ─────────────────────────────
def create_record_payload(title="Test Record", page_count=1, **overrides) -> dict:
    defaults = {"title": title, "page_count": page_count}
    defaults.update(overrides)
    return defaults


def review_record_payload(disposition, **overrides) -> dict:
    defaults = {"disposition": disposition}
    defaults.update(overrides)
    return defaults


def create_exemption_payload(applies_to_kind, exemption_code, justification="Statutory basis", **overrides) -> dict:
    defaults = {
        "applies_to_kind": applies_to_kind,
        "exemption_code": exemption_code,
        "justification": justification,
    }
    defaults.update(overrides)
    return defaults


# ─── Fees ─────────────────────────────────────────────
def create_fee_estimate_payload(expected_request_version, search_hours=0, review_hours=0,
                                billable_pages=0, **overrides) -> dict:
    defaults = {
        "search_hours": search_hours,
        "review_hours": review_hours,
        "billable_pages": billable_pages,
        "expected_request_version": expected_request_version,
    }
    defaults.update(overrides)
    return defaults


def fee_waiver_payload(expected_request_version, f_public_understanding=False, f_not_commercial_interest=False,
                       f_meaningful_contribution=False, f_ability_to_disseminate=False, **overrides) -> dict:
    # PRD §3.4: the four findings are booleans; coerce so tuple-style callers
    # (e.g. findings=(1, 1, 1, 1)) still produce the PRD-required boolean payload.
    defaults = {
        "f_public_understanding": bool(f_public_understanding),
        "f_not_commercial_interest": bool(f_not_commercial_interest),
        "f_meaningful_contribution": bool(f_meaningful_contribution),
        "f_ability_to_disseminate": bool(f_ability_to_disseminate),
        "expected_request_version": expected_request_version,
    }
    defaults.update(overrides)
    return defaults


def payment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


# ─── Determination & Glomar ───────────────────────────
def determination_payload(expected_request_version, **overrides) -> dict:
    defaults = {"expected_request_version": expected_request_version}
    defaults.update(overrides)
    return defaults


def glomar_payload(expected_request_version, **overrides) -> dict:
    defaults = {"expected_request_version": expected_request_version}
    defaults.update(overrides)
    return defaults


# ─── Appeals ──────────────────────────────────────────
def file_appeal_payload(appellant_id, grounds="Appeal grounds", filed_at="2026-02-10T00:00:00.000Z",
                        **overrides) -> dict:
    defaults = {"appellant_id": appellant_id, "grounds": grounds, "filed_at": filed_at}
    defaults.update(overrides)
    return defaults


def decide_appeal_payload(decision, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


# ─── Reverse FOIA ─────────────────────────────────────
def create_objection_payload(submitter_id, objection_text="Confidential commercial information", **overrides) -> dict:
    defaults = {"submitter_id": submitter_id, "objection_text": objection_text}
    defaults.update(overrides)
    return defaults


def resolve_objection_payload(resolution, **overrides) -> dict:
    defaults = {"resolution": resolution}
    defaults.update(overrides)
    return defaults


# ─── Inspection facilities & bookings ─────────────────
def create_reading_room_payload(name="Reading Room", capacity=1, **overrides) -> dict:
    defaults = {"name": name, "capacity": capacity}
    defaults.update(overrides)
    return defaults


def create_review_station_payload(name="Review Station", buffer_minutes=0, **overrides) -> dict:
    defaults = {"name": name, "buffer_minutes": buffer_minutes}
    defaults.update(overrides)
    return defaults


def booking_payload(request_id, starts_at, ends_at, **overrides) -> dict:
    defaults = {"request_id": request_id, "starts_at": starts_at, "ends_at": ends_at}
    defaults.update(overrides)
    return defaults


# ─── Test-driving clock ───────────────────────────────
def clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
