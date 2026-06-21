"""Entity assertions and domain invariant checkers for the Coding Bootcamp ISA API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable(data: dict):
    """Mutable resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at >=1, got {data.get('version')}"


def assert_cohort(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in {"PLANNING", "OPEN", "RUNNING", "GRADUATED", "ARCHIVED"}
    assert isinstance(data["capacity"], int)
    assert isinstance(data["seats_committed"], int)
    assert isinstance(data["seats_available"], int)
    assert_cohort_seat_invariant(data)


def assert_cohort_seat_invariant(data: dict):
    """PRD §2.5: seats_committed + seats_available always equals capacity."""
    assert data["seats_committed"] + data["seats_available"] == data["capacity"], (
        f"seat conservation violated: {data['seats_committed']} + {data['seats_available']} "
        f"!= {data['capacity']}"
    )
    assert data["seats_committed"] >= 0
    assert data["seats_available"] >= 0


def assert_applicant(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in {"APPLIED", "ADMITTED", "REJECTED", "ENROLLED", "WITHDRAWN_APP"}
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0


def assert_enrollment(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in {"ENROLLED", "ACTIVE", "GRADUATED", "DISMISSED", "WITHDRAWN"}
    assert data["financing_choice"] in {"ISA", "UPFRONT"}


def assert_isa_contract(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in {
        "PENDING", "ACTIVE", "DEFERRED", "COMPLETED", "SETTLED_TERM", "VOIDED",
    }
    assert isinstance(data["cap_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["remaining_cap_cents"], int)
    assert isinstance(data["payments_made_count"], int)
    assert_isa_ledger_invariant(data)


def assert_isa_ledger_invariant(data: dict):
    """PRD §2.5: amount_paid_cents + remaining_cap_cents always equals cap_cents."""
    assert data["amount_paid_cents"] + data["remaining_cap_cents"] == data["cap_cents"], (
        f"ISA ledger invariant violated: {data['amount_paid_cents']} + "
        f"{data['remaining_cap_cents']} != {data['cap_cents']}"
    )
    assert data["amount_paid_cents"] >= 0
    assert data["amount_paid_cents"] <= data["cap_cents"], "amount_paid must never overshoot cap"


def assert_scholarship(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in {"APPLIED", "SUPERSEDED"}
    assert data["kind"] in {"DEI", "MERIT", "NEED"}


def assert_deposit(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in {"HELD", "REFUNDED", "FORFEITED"}
    assert isinstance(data["amount_cents"], int)


def assert_income_report(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["obligation_cents"], int)
    assert data["employment_status"] in {"EMPLOYED", "UNEMPLOYED", "UNDEREMPLOYED"}


def assert_payment(data: dict):
    _assert_common_mutable(data)
    assert data["collection_status"] in {"PENDING", "SETTLED", "FAILED"}
    assert data["refund_status"] in {"NONE", "REFUNDED"}
    assert data["status"] in {"PENDING", "FAILED", "SETTLED", "REVERSED"}
    assert isinstance(data["amount_cents"], int)


def assert_deferment_request(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in {"REQUESTED", "APPROVED", "DENIED", "ENDED"}
    assert data["reason"] in {"UNEMPLOYMENT", "INCOME_FLOOR"}


def assert_refund_request(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in {"PENDING", "APPROVED", "REJECTED"}
    assert data["reason"] in {"COOLING_OFF", "WITHDRAWAL", "DISMISSAL_APPEAL"}


def assert_placement_outcome(data: dict):
    _assert_common_mutable(data)
    assert data["category"] in {
        "EMPLOYED_IN_FIELD", "EMPLOYED_OUT_OF_FIELD", "SELF_EMPLOYED",
        "CONTINUED_EDUCATION", "STILL_SEEKING", "OUT_OF_PROGRAM",
    }
    assert isinstance(data["cirr_eligible"], bool)


def assert_cirr_report(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in {"DRAFT", "PUBLISHED"}
    assert data["denominator_basis"] in {"GRADUATES_ONLY", "ALL_ENROLLED"}
    assert isinstance(data["placed_count"], int)


def assert_attendance_record(data: dict):
    """Append-only event log (PRD §2.4): ONLY id + created_at, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "attendance record id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "AttendanceRecord must not carry a version field"
    assert "updated_at" not in data, "AttendanceRecord must not carry an updated_at field"
