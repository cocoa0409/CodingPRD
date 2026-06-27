"""Payload factories — one per create endpoint, input fields only.

Each factory provides sensible required defaults and accepts **overrides for
the values a test needs to control.
"""

# ─── Office (PRD §3.1) ─────────────────────────────────────────────────────
# Required input: name, efin, state_code. Optional: bank_product_enabled.
def create_office_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Office",
        "efin": "123456",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


# ─── ComplianceCredential (PRD §3.1) ───────────────────────────────────────
# Required input: office_id, ptin, holder_name, expires_on.
def create_credential_payload(office_id: str, **overrides) -> dict:
    defaults = {
        "office_id": office_id,
        "ptin": "P12345678",
        "holder_name": "Test Preparer",
        "expires_on": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── Preparer (PRD §3.1) ───────────────────────────────────────────────────
# Required input: credential_id, full_name. Optional: max_open_returns.
def create_preparer_payload(credential_id: str, **overrides) -> dict:
    defaults = {
        "credential_id": credential_id,
        "full_name": "Test Preparer",
    }
    defaults.update(overrides)
    return defaults


# ─── Client (PRD §3.2) ─────────────────────────────────────────────────────
# Required input: full_name, ssn_last4. Optional: risk_band, is_returning.
def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Taxpayer",
        "ssn_last4": "1234",
    }
    defaults.update(overrides)
    return defaults


# ─── Appointment (PRD §3.2) ────────────────────────────────────────────────
# Required input: client_id, preparer_id, start_utc, end_utc.
def create_appointment_payload(client_id: str, preparer_id: str,
                               start_utc: str, end_utc: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "preparer_id": preparer_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    defaults.update(overrides)
    return defaults


# ─── TaxReturn (PRD §3.3) ──────────────────────────────────────────────────
# Required input: office_id, client_id, tax_year.
# Optional: return_kind, complexity_band, schedules, state_return_count,
#           expected_refund_cents, amends_return_id.
def create_return_payload(office_id: str, client_id: str, tax_year: int = 2025,
                          **overrides) -> dict:
    defaults = {
        "office_id": office_id,
        "client_id": client_id,
        "tax_year": tax_year,
    }
    defaults.update(overrides)
    return defaults


# ─── DocumentIntake (PRD §3.3) ─────────────────────────────────────────────
# Required input: doc_type. Optional: is_required.
def create_document_payload(doc_type: str = "W2", **overrides) -> dict:
    defaults = {
        "doc_type": doc_type,
    }
    defaults.update(overrides)
    return defaults


# ─── AuditProtection (PRD §3.6) ────────────────────────────────────────────
# Required input: tax_return_id. Optional: fee_cents.
def create_audit_protection_payload(tax_return_id: str, **overrides) -> dict:
    defaults = {
        "tax_return_id": tax_return_id,
    }
    defaults.update(overrides)
    return defaults


# ─── RefundTransfer (PRD §3.7) ─────────────────────────────────────────────
# Required input: tax_return_id.
def create_refund_transfer_payload(tax_return_id: str, **overrides) -> dict:
    defaults = {
        "tax_return_id": tax_return_id,
    }
    defaults.update(overrides)
    return defaults


# ─── RefundAdvance (PRD §3.8) ──────────────────────────────────────────────
# Required input: tax_return_id, requested_cents.
def create_refund_advance_payload(tax_return_id: str, requested_cents: int,
                                  **overrides) -> dict:
    defaults = {
        "tax_return_id": tax_return_id,
        "requested_cents": requested_cents,
    }
    defaults.update(overrides)
    return defaults
