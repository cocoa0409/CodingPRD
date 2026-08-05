"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _common_versioned(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_practice(data: dict):
    _common_versioned(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in [s.value if hasattr(s, "value") else s for s in
                              ["PROSPECT", "ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED"]]
    assert isinstance(data["ar_balance_cents"], int)
    assert isinstance(data["collected_ytd_cents"], int)


def assert_payer(data: dict):
    _common_versioned(data)
    assert data["payer_type"] in ["COMMERCIAL", "MEDICARE", "MEDICAID"]
    assert isinstance(data["timely_filing_days"], int)
    assert isinstance(data["appeal_window_days"], int)


def assert_provider(data: dict):
    _common_versioned(data)
    assert data["credentialing_status"] in ["PENDING", "SUBMITTED", "APPROVED", "REJECTED", "EXPIRED"]


def assert_enrollment(data: dict):
    _common_versioned(data)
    assert data["status"] in ["PENDING", "ACTIVE", "TERMINATED"]


def assert_fee_schedule(data: dict):
    _common_versioned(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED"]


def assert_fee_schedule_line(data: dict):
    # Append-only line item: only id + created_at, no updated_at / version.
    _common(data)
    assert "updated_at" not in data, "FeeScheduleLine must not carry updated_at"
    assert "version" not in data, "FeeScheduleLine must not carry version"
    assert isinstance(data["allowed_amount_cents"], int)


def assert_claim(data: dict):
    _common_versioned(data)
    assert data["status"] in ["DRAFT", "SCRUBBED", "SUBMITTED", "ACCEPTED", "DENIED",
                              "APPEALED", "PAID", "CLOSED", "VOID"]
    for f in ["billed_amount_cents", "allowed_amount_cents", "contractual_adjustment_cents",
              "patient_responsibility_cents", "expected_reimbursement_cents",
              "insurance_paid_cents", "write_off_cents", "outstanding_balance_cents",
              "appeal_round"]:
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_claim_line(data: dict):
    # Append-only line item: only id + created_at.
    _common(data)
    assert "updated_at" not in data, "ClaimLine must not carry updated_at"
    assert "version" not in data, "ClaimLine must not carry version"


def assert_denial(data: dict):
    _common_versioned(data)
    assert data["status"] in ["OPEN", "APPEALED", "OVERTURNED", "UPHELD", "WRITTEN_OFF"]


def assert_appeal(data: dict):
    _common_versioned(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "OVERTURNED", "UPHELD", "WITHDRAWN"]
    assert isinstance(data["recovered_amount_cents"], int)


def assert_remittance(data: dict):
    _common_versioned(data)
    assert data["status"] in ["RECEIVED", "POSTING", "POSTED", "REVERSED"]
    assert isinstance(data["allocated_amount_cents"], int)
    assert isinstance(data["unallocated_amount_cents"], int)


def assert_posting(data: dict):
    _common_versioned(data)
    assert data["status"] in ["POSTED", "REVERSED"]


def assert_statement(data: dict):
    _common_versioned(data)
    assert data["status"] in ["DRAFT", "SENT", "PARTIAL", "PAID", "COLLECTIONS", "WRITTEN_OFF"]
    assert data["aging_bucket"] in ["CURRENT", "DAYS_31_60", "DAYS_61_90", "OVER_90"]


# ---- Domain invariant checkers ----
def assert_claim_ledger_identity(claim: dict):
    """PRD §3.6: billed == contractual_adjustment + insurance_paid +
    patient_responsibility + write_off + outstanding_balance."""
    lhs = claim["billed_amount_cents"]
    rhs = (claim["contractual_adjustment_cents"] + claim["insurance_paid_cents"]
           + claim["patient_responsibility_cents"] + claim["write_off_cents"]
           + claim["outstanding_balance_cents"])
    assert lhs == rhs, (
        f"Claim ledger identity violated: billed={lhs} != "
        f"contractual+insurance+PR+writeoff+outstanding={rhs}")


def assert_remittance_conservation(remittance: dict):
    """PRD §3.6: total_amount_cents == allocated_amount_cents + unallocated_amount_cents."""
    total = remittance["total_amount_cents"]
    parts = remittance["allocated_amount_cents"] + remittance["unallocated_amount_cents"]
    assert total == parts, (
        f"Remittance conservation violated: total={total} != "
        f"allocated+unallocated={parts}")
