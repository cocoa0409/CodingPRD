"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _common_full(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1 int"


def assert_holder(data: dict):
    _common_full(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["holder_type"] in ["BANK", "INSURER", "UTILITY", "BROKER", "OTHER"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["audit_hold"], bool)
    assert isinstance(data["assessed_penalty_cents"], int) and data["assessed_penalty_cents"] >= 0


def assert_property_type(data: dict):
    # Lightweight config record — only id + created_at (§2.4).
    _common(data)
    assert "updated_at" not in data, "PropertyType must not expose updated_at"
    assert "version" not in data, "PropertyType must not expose version"
    assert data["dormancy_basis"] in ["LAST_ACTIVITY", "ISSUANCE"]
    assert isinstance(data["dormancy_period_years"], int) and data["dormancy_period_years"] >= 1


def assert_state_account(data: dict):
    _common_full(data)
    assert isinstance(data["custody_balance_cents"], int)


def assert_owner(data: dict):
    _common_full(data)
    assert isinstance(data["id_verified"], bool)


def assert_recovery_firm(data: dict):
    _common_full(data)
    assert 0 < data["max_fee_pct"] <= 1


def assert_property(data: dict):
    _common_full(data)
    assert data["status"] in ["ACTIVE", "DORMANT", "DUE_DILIGENCE", "REPORTED", "ESCHEATED", "CLAIMED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["escheat_state"], str) and len(data["escheat_state"]) == 2
    assert isinstance(data["remitted_amount_cents"], int) and data["remitted_amount_cents"] >= 0


def assert_claim(data: dict):
    _common_full(data)
    assert data["status"] in ["FILED", "UNDER_REVIEW", "NEEDS_EVIDENCE", "APPROVED", "PAID", "DENIED", "VOIDED"]
    assert data["filed_by"] in ["OWNER", "FIRM"]


def assert_evidence_document(data: dict):
    _common_full(data)
    assert data["status"] in ["PENDING", "ACCEPTED", "REJECTED"]
    assert data["doc_type"] in ["GOV_ID", "PROOF_OF_ADDRESS", "DEATH_CERTIFICATE", "OWNERSHIP_PROOF"]


def assert_audit_case(data: dict):
    _common_full(data)
    assert data["status"] in ["OPEN", "INFO_REQUESTED", "CLOSED_NO_FINDING", "CLOSED_ASSESSED"]


def assert_ledger_entry(data: dict):
    # Immutable append-only record — only id + created_at (§2.4, §2.6).
    _common(data)
    assert "updated_at" not in data, "LedgerEntry must not expose updated_at"
    assert "version" not in data, "LedgerEntry must not expose version"
    assert data["entry_type"] in ["REMIT_IN", "PAYOUT_OUT", "FEE_OUT", "CLAWBACK_IN"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


# --- Domain invariant checkers ---
def assert_waterfall_identity(claim: dict):
    """§3.7 identity: claim_amount_cents == fee + admin_deduction + net_payout."""
    assert claim["claim_amount_cents"] == (
        claim["fee_cents"] + claim["admin_deduction_cents"] + claim["net_payout_cents"]
    ), "payout-waterfall identity violated"


def ledger_signed_sum(entries: list) -> int:
    """Signed sum over ledger rows: REMIT_IN/CLAWBACK_IN add, PAYOUT_OUT/FEE_OUT remove (§2.6)."""
    total = 0
    for e in entries:
        if e["entry_type"] in ("REMIT_IN", "CLAWBACK_IN"):
            total += e["amount_cents"]
        elif e["entry_type"] in ("PAYOUT_OUT", "FEE_OUT"):
            total -= e["amount_cents"]
    return total
