"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_close_period(data: dict):
    _assert_common(data, "ClosePeriod")
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["fiscal_period"], int)
    assert 1 <= data["fiscal_period"] <= 13
    assert data["close_posture"] in ("OPEN", "SOFT_CLOSED", "HARD_CLOSED", "REOPENED")
    assert data["reporting_currency"] in ("USD", "EUR", "GBP", "JPY")
    assert isinstance(data["materiality_threshold_minor"], int)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "UNDER_REVIEW", "FINALIZED")
    assert isinstance(data["locked_entity_count"], int)
    assert isinstance(data["total_entity_count"], int)


def assert_entity(data: dict):
    _assert_common(data, "Entity")
    assert isinstance(data["entity_code"], str) and data["entity_code"]
    assert data["functional_currency"] in ("USD", "EUR", "GBP", "JPY")
    assert isinstance(data["ownership_pct"], (int, float))
    assert 0 < data["ownership_pct"] <= 100
    assert data["translation_method"] in ("CURRENT_RATE", "TEMPORAL")
    assert isinstance(data["consolidation_tier"], int)
    assert isinstance(data["is_elimination_counterparty"], bool)


def assert_entity_period(data: dict):
    _assert_common(data, "EntityPeriod")
    assert data["status"] in (
        "PREPARING", "SUBLEDGER_CUT", "RECONCILED", "READY_FOR_CONSOL",
        "SOFT_LOCKED", "HARD_LOCKED", "REOPENED",
    )
    for f in ("trial_balance_minor", "translated_balance_minor", "cta_minor",
              "nci_share_minor", "unreconciled_count", "aged_over_30_count",
              "open_task_count"):
        assert isinstance(data[f], int), f"EntityPeriod.{f} must be int"


def assert_close_task(data: dict):
    _assert_common(data, "CloseTask")
    assert data["status"] in ("BLOCKED", "READY", "IN_PROGRESS", "DONE", "WAIVED")
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["depends_on_task_ids"], list)


def assert_subledger_cutoff(data: dict):
    _assert_common(data, "SubledgerCutoff")
    assert data["subledger"] in ("AR", "AP", "INVENTORY", "FIXED_ASSETS", "PAYROLL")
    assert data["cutoff_rule"] in ("INCLUSIVE", "EXCLUSIVE_AT_END")
    assert data["status"] in ("OPEN", "CUT", "CONFIRMED")


def assert_accrual_estimate(data: dict):
    _assert_common(data, "AccrualEstimate")
    assert data["basis"] in ("PRIOR_3M_AVG", "PRIOR_PERIOD", "DAYS_OUTSTANDING")
    assert data["status"] in ("PROVISIONAL", "TRUED_UP", "POSTED")
    assert isinstance(data["provisional_amount_minor"], int)


def assert_journal_entry(data: dict):
    _assert_common(data, "JournalEntry")
    assert data["je_type"] in (
        "MANUAL", "ACCRUAL", "RECLASS", "ELIMINATION", "CONSOLIDATION_ADJ", "TOP_SIDE"
    )
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "POSTED", "REJECTED")
    assert data["doc_state"] in ("DOC_MISSING", "DOC_ATTACHED", "DOC_VERIFIED")
    assert isinstance(data["debit_total_minor"], int)
    assert isinstance(data["credit_total_minor"], int)


def assert_supporting_document(data: dict):
    _assert_common(data, "SupportingDocument")
    assert data["doc_category"] in ("INVOICE", "CONTRACT", "BANK_STATEMENT", "SCHEDULE", "OTHER")
    assert data["status"] in ("ATTACHED", "VERIFIED", "REJECTED")


def assert_reconciliation(data: dict):
    _assert_common(data, "Reconciliation")
    assert data["recon_type"] in ("BANK", "INTERCOMPANY", "SUBLEDGER_GL", "SUSPENSE")
    assert data["status"] in ("OPEN", "IN_REVIEW", "CLEARED", "STALE")
    assert isinstance(data["difference_minor"], int)
    assert isinstance(data["is_within_tolerance"], bool)


def assert_reconciling_item(data: dict):
    _assert_common(data, "ReconcilingItem")
    assert data["aging_bucket"] in ("CURRENT", "AGE_1_30", "AGE_31_60", "AGE_61_90", "AGE_OVER_90")
    assert data["status"] in ("OPEN", "RESOLVED", "WRITTEN_OFF")


def assert_elim_pair(data: dict):
    _assert_common(data, "ElimPair")
    assert data["status"] in ("PROPOSED", "MATCHED", "ELIMINATED", "DISPUTED")


def assert_flux_explanation(data: dict):
    _assert_common(data, "FluxExplanation")
    assert data["status"] in ("OPEN", "EXPLAINED", "ACCEPTED", "REJECTED")
    assert isinstance(data["requires_explanation"], bool)


def assert_fx_rate(data: dict):
    _assert_common(data, "FxRate")
    assert data["rate_kind"] in ("PERIOD_END", "AVERAGE", "HISTORICAL")
    assert data["rate"] > 0


def assert_close_event(data: dict):
    """CloseEvent is append-only: only id + created_at; no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "CloseEvent.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "CloseEvent.created_at must be ISO 8601"
    assert "updated_at" not in data, "CloseEvent must NOT carry updated_at (append-only)"
    assert "version" not in data, "CloseEvent must NOT carry version (append-only)"
    assert data["event_kind"] in (
        "PERIOD_OPENED", "SUBLEDGER_CUT", "ACCRUAL_POSTED", "JE_POSTED",
        "RECON_CLEARED", "TASK_DONE", "TRANSLATION_RUN", "ELIMINATION_RUN",
        "SOFT_LOCK", "HARD_LOCK", "REOPENED", "REVIEW_FINALIZED",
    )
