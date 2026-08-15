"""Payload factories — one per entity, input fields only."""


def create_period_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year": 2026,
        "fiscal_period": 1,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-01-31T00:00:00Z",
        "reporting_currency": "USD",
        "materiality_threshold_minor": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_entity_payload(**overrides) -> dict:
    defaults = {
        "entity_code": "US100",
        "name": "US Parent",
        "functional_currency": "USD",
        "ownership_pct": 100,
        "translation_method": "CURRENT_RATE",
    }
    defaults.update(overrides)
    return defaults


def create_task_payload(entity_period_id=None, **overrides) -> dict:
    defaults = {
        "entity_period_id": entity_period_id,
        "task_key": "SL_CUTOFF",
        "title": "Cut subledgers",
        "assignee_user_id": "prep-1",
        "due_offset_hours": 24,
    }
    if entity_period_id is None:
        defaults.pop("entity_period_id")
    defaults.update(overrides)
    return defaults


def create_subledger_cutoff_payload(**overrides) -> dict:
    defaults = {
        "subledger": "AR",
        "cutoff_at": "2026-01-31T00:00:00Z",
        "cutoff_rule": "INCLUSIVE",
    }
    defaults.update(overrides)
    return defaults


def create_accrual_payload(subledger_cutoff_id, **overrides) -> dict:
    defaults = {
        "subledger_cutoff_id": subledger_cutoff_id,
        "account_code": "6100-SALARIES",
        "basis": "PRIOR_PERIOD",
    }
    defaults.update(overrides)
    return defaults


def create_journal_entry_payload(**overrides) -> dict:
    defaults = {
        "je_type": "RECLASS",
        "entry_date": "2026-01-20T00:00:00Z",
        "functional_currency": "USD",
        "lines": [
            {"line_no": 1, "account_code": "6100", "direction": "DEBIT", "amount_minor": 1000},
            {"line_no": 2, "account_code": "6150", "direction": "CREDIT", "amount_minor": 1000},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {
        "file_name": "invoice.pdf",
        "content_hash": "abc123",
        "doc_category": "INVOICE",
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_payload(**overrides) -> dict:
    defaults = {
        "account_code": "1010-BANK",
        "recon_type": "BANK",
        "gl_balance_minor": 100000,
        "subledger_balance_minor": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_reconciling_item_payload(**overrides) -> dict:
    defaults = {
        "description": "Deposit in transit",
        "amount_minor": 500,
        "item_date": "2026-01-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_elim_pair_payload(entity_period_id_a, entity_period_id_b, **overrides) -> dict:
    defaults = {
        "entity_period_id_a": entity_period_id_a,
        "entity_period_id_b": entity_period_id_b,
        "account_code": "1500-IC_AR",
        "amount_a_minor": 100000,
        "amount_b_minor": -100000,
    }
    defaults.update(overrides)
    return defaults


def create_flux_payload(**overrides) -> dict:
    defaults = {
        "account_code": "4000-REV",
        "prior_balance_minor": 100000,
        "current_balance_minor": 200000,
    }
    defaults.update(overrides)
    return defaults


def create_fx_rate_payload(**overrides) -> dict:
    defaults = {
        "from_currency": "EUR",
        "to_currency": "USD",
        "rate_kind": "PERIOD_END",
        "rate": 1.10,
        "effective_at": "2026-01-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
