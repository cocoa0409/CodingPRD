"""Entity assertions and domain invariant checkers (PRD-derived)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id (UUID), created_at/updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_tax_roll(data: dict):
    _assert_common(data)
    assert isinstance(data["tax_year"], int)
    assert data["status"] in {"DRAFT", "OPEN", "CERTIFIED", "CLOSED"}


def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["is_veteran"], bool)
    assert isinstance(data["disability_pct"], int)


def assert_parcel(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["owner_id"]), "owner_id must be a UUID"
    assert data["status"] in {"ACTIVE", "SOLD"}
    assert isinstance(data["is_primary_residence"], bool)


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["parcel_id"]), "parcel_id must be a UUID"
    assert is_valid_uuid(data["tax_roll_id"]), "tax_roll_id must be a UUID"
    assert data["status"] in {"DRAFT", "NOTICED", "UNDER_APPEAL", "FINAL"}
    assert data["reassessment_event"] in {"NONE", "SALE", "NEW_CONSTRUCTION"}


def assert_exemption(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["assessment_id"]), "assessment_id must be a UUID"
    assert data["exemption_type"] in {"HOMESTEAD", "SENIOR", "VETERAN", "DISABILITY"}
    assert data["status"] in {"CLAIMED", "APPROVED", "DENIED"}


def assert_appeal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["assessment_id"]), "assessment_id must be a UUID"
    assert is_valid_uuid(data["filed_by_owner_id"]), "filed_by_owner_id must be a UUID"
    assert data["status"] in {
        "FILED", "UNDER_REVIEW", "EVIDENCE_REQUESTED",
        "SETTLED", "GRANTED", "DENIED", "WITHDRAWN",
    }


def assert_board_panel(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]


def assert_hearing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["appeal_id"]), "appeal_id must be a UUID"
    assert is_valid_uuid(data["board_panel_id"]), "board_panel_id must be a UUID"
    assert data["status"] in {"SCHEDULED", "HELD", "CANCELLED"}


def assert_deferral_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["parcel_id"]), "parcel_id must be a UUID"
    assert is_valid_uuid(data["owner_id"]), "owner_id must be a UUID"
    assert data["status"] in {"ACTIVE", "SATISFIED", "DEFAULTED"}


def assert_tax_bill(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["assessment_id"]), "assessment_id must be a UUID"
    assert data["status"] in {"ISSUED", "PAID", "DEFERRED"}
    assert isinstance(data["is_deferred"], bool)


def assert_deferral_payment(data: dict):
    """Append-only event: id + created_at only, no version / updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "DeferralPayment is immutable: must NOT carry a version field"
    assert "updated_at" not in data, "DeferralPayment is immutable: must NOT carry updated_at"


def assert_deferral_balance_identity(data: dict):
    """PRD §3.9: outstanding == principal + accrued interest - total_paid."""
    expected = (
        data["deferred_principal_cents"]
        + data["accrued_interest_cents"]
        - data["total_paid_cents"]
    )
    assert data["outstanding_balance_cents"] == expected, (
        f"balance identity violated: outstanding={data['outstanding_balance_cents']} "
        f"!= {expected}"
    )
