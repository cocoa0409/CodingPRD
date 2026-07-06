"""Payload factories — one per entity, input fields only."""


def create_client_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Test Client LLC",
        "entity_type": "LLC",
        "accounting_basis": "ACCRUAL",
    }
    payload.update(overrides)
    return payload


def create_engagement_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "title": "Catch-up Engagement",
        "period_start": "2025-01-01",
        "period_end": "2025-06-30",
        "complexity_tier": "MEDIUM",
    }
    payload.update(overrides)
    return payload


def create_scope_estimate_payload(**overrides) -> dict:
    payload = {"monthly_txn_rate": 220}
    payload.update(overrides)
    return payload


def create_account_payload(**overrides) -> dict:
    payload = {
        "account_code": "1000",
        "name": "Cash",
        "account_type": "ASSET",
        "is_bank_account": False,
    }
    payload.update(overrides)
    return payload


def create_entry_payload(account_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "txn_date": "2025-02-01",
        "side": "DEBIT",
        "amount_cents": 1000,
    }
    payload.update(overrides)
    return payload


def create_statement_payload(account_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "statement_start": "2025-02-01",
        "statement_end": "2025-02-28",
        "ending_balance_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_reconciliation_item_payload(ledger_entry_id, statement_line_amount_cents, **overrides) -> dict:
    payload = {
        "ledger_entry_id": ledger_entry_id,
        "statement_line_amount_cents": statement_line_amount_cents,
        "match_kind": "EXACT",
    }
    payload.update(overrides)
    return payload


def create_phase_payload(phase_index, weight_bp, **overrides) -> dict:
    payload = {
        "phase_index": phase_index,
        "label": f"Phase {phase_index}",
        "weight_bp": weight_bp,
    }
    payload.update(overrides)
    return payload


def create_service_plan_payload(**overrides) -> dict:
    payload = {
        "monthly_fee_cents": 30000,
        "conversion_date": "2026-04-10",
    }
    payload.update(overrides)
    return payload


def create_exception_payload(account_id, kind, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "kind": kind,
        "severity": "NORMAL",
    }
    payload.update(overrides)
    return payload
