"""Entity assertions and domain invariant checkers for the
Marriage License & Vital Records API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version for full-quartet entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_iso8601_timestamp(data["date_of_birth"]) or "-" in data["date_of_birth"]
    assert data["prior_marriage_status"] in [
        "NEVER_MARRIED", "DIVORCED", "WIDOWED", "MARRIED",
    ]
    assert isinstance(data["has_judicial_consent"], bool)


def assert_officiant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["credential_type"] in ["CLERGY", "JUDGE", "NOTARY", "DEPUTY_COMMISSIONER"]
    assert data["status"] in ["REGISTERED", "SUSPENDED"]
    assert isinstance(data["returns_filed_count"], int)


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "UNDER_REVIEW", "APPROVED", "DENIED", "EXPIRED",
    ]
    assert isinstance(data["is_confidential"], bool)
    assert isinstance(data["total_charged_cents"], int)


def assert_license(data: dict):
    _assert_common(data)
    assert data["status"] in ["ISSUED", "USED", "EXPIRED", "VOID"]
    assert isinstance(data["is_confidential"], bool)
    assert is_iso8601_timestamp(data["issued_at"]), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data["valid_from"]), "valid_from must be ISO 8601"
    assert is_iso8601_timestamp(data["expires_at"]), "expires_at must be ISO 8601"


def assert_return(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "REJECTED"]
    assert is_iso8601_timestamp(data["ceremony_date"]), "ceremony_date must be ISO 8601"
    assert is_iso8601_timestamp(data["filing_deadline"]), "filing_deadline must be ISO 8601"


def assert_record(data: dict):
    _assert_common(data)
    assert data["status"] in ["REGISTERED", "AMENDED", "SEALED"]
    assert isinstance(data["is_confidential"], bool)
    assert isinstance(data["amendment_count"], int)
    assert isinstance(data["certified_copies_issued"], int)


def assert_certified_copy(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "ISSUED", "DENIED", "REFUNDED"]
    assert data["requester_kind"] in ["PARTY", "GOVERNMENT", "PUBLIC"]
    assert isinstance(data["copies_requested"], int)
    assert isinstance(data["fee_cents"], int)


def assert_amendment(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "RETURNED_FOR_INFO", "APPLIED", "REJECTED"]
    assert data["amendment_type"] in ["CLERICAL", "SUBSTANTIVE"]
    assert isinstance(data["resubmit_count"], int)


def assert_apostille(data: dict):
    _assert_common(data)
    assert data["status"] in ["REQUESTED", "AUTHENTICATED", "REJECTED"]
    assert isinstance(data["fee_cents"], int)


def assert_fee_waiver(data: dict):
    _assert_common(data)
    assert data["status"] in ["REQUESTED", "GRANTED", "DENIED", "CONSUMED"]
    assert isinstance(data["declared_monthly_income_cents"], int)
    assert isinstance(data["household_size"], int)
    assert isinstance(data["max_waivable_cents"], int)
    assert isinstance(data["consumed_cents"], int)


def assert_ledger_entry(data: dict):
    """FeeLedgerEntry is append-only (PRD §2.4): id + created_at only, no version."""
    assert is_valid_uuid(data.get("id", "")), "ledger id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ["CHARGE", "REFUND", "WAIVE"]
    assert isinstance(data["amount_cents"], int)
    assert data["source_entity"] in [
        "LICENSE", "CERTIFIED_COPY", "AMENDMENT", "APOSTILLE", "RETURN",
    ]


# ---------------------------------------------------------------------------
# Domain invariant helpers
# ---------------------------------------------------------------------------
def collected_balance(ledger_rows: list) -> int:
    """Office collected balance (PRD §2.9): sum(CHARGE amount_cents) - sum(REFUND
    amount_cents); WAIVE rows are excluded entirely from cash."""
    charged = sum(r["amount_cents"] for r in ledger_rows if r["kind"] == "CHARGE")
    refunded = sum(r["amount_cents"] for r in ledger_rows if r["kind"] == "REFUND")
    return charged - refunded


def find_ledger_entries(ledger_rows: list, kind=None, source_entity=None,
                        source_entity_id=None, amount_cents=None) -> list:
    """Filter ledger rows by any combination of kind / source_entity /
    source_entity_id / amount_cents."""
    out = []
    for r in ledger_rows:
        if kind is not None and r["kind"] != kind:
            continue
        if source_entity is not None and r["source_entity"] != source_entity:
            continue
        if source_entity_id is not None and r["source_entity_id"] != source_entity_id:
            continue
        if amount_cents is not None and r["amount_cents"] != amount_cents:
            continue
        out.append(r)
    return out
