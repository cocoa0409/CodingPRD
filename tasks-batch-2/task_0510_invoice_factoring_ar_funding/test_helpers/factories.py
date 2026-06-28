"""Payload factories — one per entity, input fields only.

Each factory provides PRD-faithful defaults for required input fields and
accepts **overrides for the values tests need to control.
"""
from .constants import TEST_DEFAULTS


# ─── FactoringProgram (POST /factoring/programs) ─────────────────────────────
# Required: name. Optional: currency, default_fee_rate_per_day, tier2_multiplier,
# tier3_multiplier, recourse_grace_days (all have server defaults).
def create_program_payload(**overrides) -> dict:
    defaults = {"name": "Test Factor Program"}
    defaults.update(overrides)
    return defaults


# ─── Client (POST /factoring/clients) ────────────────────────────────────────
# Required: program_id, legal_name, requested_advance_rate_pct.
def create_client_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "legal_name": "Test Client LLC",
        "requested_advance_rate_pct": TEST_DEFAULTS["ADVANCE_RATE_PCT"],
    }
    defaults.update(overrides)
    return defaults


# ─── Client credit-decision (POST .../credit-decision) ───────────────────────
# decision=APPROVE additionally carries approved_advance_rate_pct,
# credit_limit_cents, default_concentration_limit_pct.
def approve_client_payload(**overrides) -> dict:
    defaults = {
        "decision": "APPROVE",
        "approved_advance_rate_pct": TEST_DEFAULTS["ADVANCE_RATE_PCT"],
        "credit_limit_cents": TEST_DEFAULTS["BIG_CREDIT_LIMIT_CENTS"],
        "default_concentration_limit_pct": TEST_DEFAULTS["BIG_CONCENTRATION_PCT"],
    }
    defaults.update(overrides)
    return defaults


def reject_client_payload(**overrides) -> dict:
    defaults = {"decision": "REJECT"}
    defaults.update(overrides)
    return defaults


# ─── Debtor (POST /factoring/debtors) ────────────────────────────────────────
# Required: program_id, legal_name, credit_rating.
def create_debtor_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "legal_name": "Test Debtor Inc",
        "credit_rating": "A",
    }
    defaults.update(overrides)
    return defaults


# ─── Debtor credit-decision ──────────────────────────────────────────────────
# decision=APPROVE additionally carries approved_credit_ceiling_cents,
# verification_required.
def approve_debtor_payload(**overrides) -> dict:
    defaults = {
        "decision": "APPROVE",
        "approved_credit_ceiling_cents": TEST_DEFAULTS["BIG_CEILING_CENTS"],
        "verification_required": False,
    }
    defaults.update(overrides)
    return defaults


def reject_debtor_payload(**overrides) -> dict:
    defaults = {"decision": "REJECT"}
    defaults.update(overrides)
    return defaults


# ─── ClientDebtorRelationship (POST /factoring/relationships) ────────────────
# Required: client_id, debtor_id, recourse_type. Optional: concentration_limit_pct.
def create_relationship_payload(client_id: str, debtor_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "debtor_id": debtor_id,
        "recourse_type": "RECOURSE",
    }
    defaults.update(overrides)
    return defaults


# ─── Invoice (POST /factoring/invoices) ──────────────────────────────────────
# Required: client_id, debtor_id, invoice_number, face_amount_cents,
# issue_date, due_date.
def create_invoice_payload(client_id: str, debtor_id: str, invoice_number: str,
                           **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "debtor_id": debtor_id,
        "invoice_number": invoice_number,
        "face_amount_cents": 100000,
        "issue_date": "2026-05-01T00:00:00Z",
        "due_date": "2026-05-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── Verification (POST .../verify) ──────────────────────────────────────────
# Required: method, confirmed_amount_cents.
def verify_payload(method: str = "WAIVED", confirmed_amount_cents: int = 100000,
                   **overrides) -> dict:
    defaults = {"method": method, "confirmed_amount_cents": confirmed_amount_cents}
    defaults.update(overrides)
    return defaults


# ─── PurchaseBatch (POST /factoring/purchase-batches) ────────────────────────
# Required: client_id, batch_reference, invoice_ids.
def create_batch_payload(client_id: str, invoice_ids, batch_reference: str = "B-1",
                         **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "batch_reference": batch_reference,
        "invoice_ids": list(invoice_ids),
    }
    defaults.update(overrides)
    return defaults


def fund_batch_payload(expected_client_version: int, **overrides) -> dict:
    defaults = {"expected_client_version": expected_client_version}
    defaults.update(overrides)
    return defaults


# ─── CollectionPosting (POST .../postings) ───────────────────────────────────
# Required: amount_cents, received_at, expected_client_version. Optional: payer.
def create_posting_payload(amount_cents: int, received_at: str,
                           expected_client_version: int, payer: str = "DEBTOR",
                           **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "received_at": received_at,
        "payer": payer,
        "expected_client_version": expected_client_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Adjustment (POST .../adjustments) ───────────────────────────────────────
# Required: type, amount_cents, reason.
def create_adjustment_payload(type: str, amount_cents: int,
                              reason: str = "test adjustment", **overrides) -> dict:
    defaults = {"type": type, "amount_cents": amount_cents, "reason": reason}
    defaults.update(overrides)
    return defaults


# ─── Buyback (POST .../buyback) ──────────────────────────────────────────────
# Required: trigger_reason.
def buyback_payload(trigger_reason: str = "CLIENT_REQUEST", **overrides) -> dict:
    defaults = {"trigger_reason": trigger_reason}
    defaults.update(overrides)
    return defaults
