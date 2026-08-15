"""Entity assertions and domain invariant checkers (PRD §2.5, §2.10)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(str(data.get("id", ""))), "id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), "created_at must be ISO 8601"
    assert "updated_at" in data, "updated_at must be present on a mutable resource"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["preferred_language"], str) and data["preferred_language"]
    assert data["status"] in ("REGISTERED", "ACTIVE", "EXITED")
    assert isinstance(data["reportable"], bool)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1


def assert_staff_member(data: dict):
    _assert_common_fields(data)
    assert data["role_level"] in ("ADMIN", "CASE_MANAGER", "INTAKE")
    assert data["clearance_level"] in (1, 2, 3)
    assert data["status"] == "ACTIVE"


def assert_organization(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["referral_capacity"], int)
    assert isinstance(data["referral_slots_used"], int)
    assert isinstance(data["referral_slots_open"], int)


def assert_room(data: dict):
    # PRD §2.5: rooms carry id and created_at only; updated_at/version absent.
    assert is_valid_uuid(str(data.get("id", ""))), "id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), "created_at must be ISO 8601"
    assert "updated_at" not in data, "rooms never expose updated_at"
    assert "version" not in data, "rooms never expose version"
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_case(data: dict):
    _assert_common_fields(data)
    assert data["service_status"] in (
        "INTAKE", "ASSESSED", "PLANNING", "ACTIVE", "SUSPENDED", "OUTCOME_REVIEW", "CLOSED",
    )
    assert data["privacy_posture"] in ("STANDARD", "RESTRICTED", "SEALED")


def assert_assessment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "VERIFIED", "SUPERSEDED")
    for field in ("housing_score", "employment_score", "education_score", "language_score", "health_score"):
        assert isinstance(data[field], int) and 0 <= data[field] <= 4


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "COMPLETED", "SUPERSEDED")
    assert isinstance(data["plan_revision"], int) and data["plan_revision"] >= 1


def assert_case_note(data: dict):
    _assert_common_fields(data)
    assert data["sensitivity"] in ("STANDARD", "CONFIDENTIAL", "SEALED")
    assert data["redaction_status"] in ("VISIBLE", "REDACTED")


def assert_consent(data: dict):
    _assert_common_fields(data)
    assert data["scope"] in ("REFERRAL_SHARE", "ACCOMPANIMENT", "DATA_REPORTING")
    assert data["status"] in ("GRANTED", "REVOKED", "EXPIRED")


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "SENT", "ACCEPTED", "DECLINED", "EXPIRED", "SUSPENDED", "COMPLETED", "WITHDRAWN",
    )
    assert data["service_category"] in ("HOUSING", "EMPLOYMENT", "EDUCATION", "LEGAL", "HEALTH")
    assert isinstance(data["ttl_days"], int) and data["ttl_days"] >= 1


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert data["kind"] in ("DOCUMENT_ID", "ACCOMPANIMENT", "ORIENTATION", "BENEFITS")


def assert_program(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "FULL", "CLOSED")
    assert data["kind"] in ("ESOL", "WORKFORCE")
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0


def assert_program_enrollment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("APPLIED", "ELIGIBLE", "ENROLLED", "COMPLETED", "WITHDRAWN", "DENIED")
    assert data["fee_status"] in ("PENDING", "ARRANGED", "WAIVED")


def assert_workshop_session(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "HELD", "CANCELLED", "RECONCILED")
    assert isinstance(data["enrolled_count"], int)
    assert isinstance(data["waitlist_count"], int)
    assert isinstance(data["open_seats"], int)


def assert_workshop_enrollment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ENROLLED", "WAITLISTED", "CANCELLED", "ATTENDED", "NO_SHOW")


def assert_benefit_screening(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SCREENED", "EXPLAINED")
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1


def assert_funder_report(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")
    assert isinstance(data["lines"], list)
    assert isinstance(data["stream_totals"], list)
    assert isinstance(data["total_cost_cents"], int)


# --- Domain invariants (PRD §2.10 capacity ledgers) ---

def assert_org_slot_invariant(org: dict):
    """referral_slots_used + referral_slots_open == referral_capacity at all times."""
    assert org["referral_slots_used"] + org["referral_slots_open"] == org["referral_capacity"], (
        f"slot ledger drift: used={org['referral_slots_used']} open={org['referral_slots_open']} "
        f"capacity={org['referral_capacity']}"
    )
    assert org["referral_slots_used"] >= 0


def assert_workshop_seat_invariant(session: dict):
    """enrolled_count + open_seats == capacity at all times."""
    assert session["enrolled_count"] + session["open_seats"] == session["capacity"], (
        f"seat ledger drift: enrolled={session['enrolled_count']} open={session['open_seats']} "
        f"capacity={session['capacity']}"
    )
    assert session["waitlist_count"] >= 0
