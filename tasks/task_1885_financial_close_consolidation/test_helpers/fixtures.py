"""Composite setup helpers for multi-step test prerequisites.

Fixtures use get_success_data() (lenient) so setup failures surface as clear
"Setup step failed" errors. Identity threading: all roles are opaque; actor ids
are threaded explicitly via make_*_headers(user_id) wherever a segregation-of-
duties or assignee gate reads the recorded actor on a sibling artifact.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_period_payload,
    create_entity_payload,
    create_task_payload,
    create_subledger_cutoff_payload,
    create_accrual_payload,
    create_journal_entry_payload,
    create_document_payload,
    create_reconciliation_payload,
    create_reconciling_item_payload,
    create_elim_pair_payload,
    create_flux_payload,
    create_fx_rate_payload,
)
from .test_users import (
    make_controller_headers,
    make_preparer_headers,
    make_approver_headers,
    make_auditor_headers,
)

CONTROLLER = make_controller_headers("controller-1")
PREPARER = make_preparer_headers("prep-1")
PREPARER2 = make_preparer_headers("prep-2")
APPROVER = make_approver_headers("approver-1")
AUDITOR = make_auditor_headers("auditor-1")


# ─── Tier 0: logical clock ────────────────────────────

def set_clock(iso: str = TEST_DEFAULTS["CLOCK_IN_PERIOD"]):
    """Drive the logical clock to a known instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, CONTROLLER))


# ─── Tier 1: Period / Entity creation ─────────────────

def create_period(**overrides) -> dict:
    """Create a close period (status SCHEDULED)."""
    return get_success_data(api_client.create_period(create_period_payload(**overrides), CONTROLLER))


def create_entity(**overrides) -> dict:
    """Register a legal entity."""
    return get_success_data(api_client.create_entity(create_entity_payload(**overrides), CONTROLLER))


def open_period(period_id: str) -> dict:
    """SCHEDULED → IN_PROGRESS; fans out EntityPeriods."""
    return get_success_data(api_client.open_period(period_id, CONTROLLER))


def get_entity_period_for(period_id: str, entity_id: str) -> dict:
    """Fetch the single EntityPeriod row for (period, entity)."""
    data = get_success_data(api_client.list_entity_periods(
        CONTROLLER, params={"close_period_id": period_id, "entity_id": entity_id}))
    assert isinstance(data, list) and len(data) == 1, f"expected exactly one EntityPeriod, got {data}"
    return data[0]


def setup_open_period_with_entity(entity_overrides=None, period_overrides=None,
                                   clock: str = TEST_DEFAULTS["CLOCK_IN_PERIOD"]):
    """Period P1 opened with one entity. Returns (period, entity, entity_period)."""
    set_clock(clock)
    period = create_period(**(period_overrides or {}))
    entity = create_entity(**(entity_overrides or {}))
    open_period(period["id"])
    ep = get_entity_period_for(period["id"], entity["id"])
    return period, entity, ep


# ─── Tier 2: JE lifecycle ─────────────────────────────

def create_balanced_je(entity_period_id: str, amount: int = 1000, *,
                       je_type: str = "RECLASS", currency: str = "USD",
                       preparer_headers=PREPARER, **overrides) -> dict:
    """Create a balanced DRAFT JE (RECLASS by default → no doc gate)."""
    payload = create_journal_entry_payload(
        je_type=je_type,
        functional_currency=currency,
        lines=[
            {"line_no": 1, "account_code": "6100", "direction": "DEBIT", "amount_minor": amount},
            {"line_no": 2, "account_code": "6150", "direction": "CREDIT", "amount_minor": amount},
        ],
        **overrides,
    )
    return get_success_data(api_client.create_journal_entry(entity_period_id, payload, preparer_headers))


def attach_verified_doc(je_id: str, *, uploader_headers=PREPARER,
                        verifier_headers=APPROVER, **doc_overrides) -> dict:
    """Attach a supporting document and have it verified.

    PRD §3.5: approval requires doc_state exactly DOC_VERIFIED, which is only
    reachable by attaching a document (DOC_ATTACHED) and having an Approver
    verify it (DOC_VERIFIED) while the entry is DRAFT or SUBMITTED.
    """
    doc = get_success_data(api_client.attach_document(
        je_id, create_document_payload(**doc_overrides), uploader_headers))
    return get_success_data(api_client.verify_document(doc["id"], verifier_headers))


def post_je(entity_period_id: str, amount: int = 1000, *, je_type: str = "RECLASS",
            currency: str = "USD", preparer_headers=PREPARER, approver_headers=APPROVER,
            **overrides) -> dict:
    """Create a balanced JE and walk DRAFT → SUBMITTED → APPROVED → POSTED.

    Attaches + verifies a supporting document before submission so the entry
    satisfies the PRD §3.5 approval gate (doc_state exactly DOC_VERIFIED) for
    every je_type, including the MANUAL/TOP_SIDE submit-time doc gate.
    """
    je = create_balanced_je(entity_period_id, amount, je_type=je_type, currency=currency,
                            preparer_headers=preparer_headers, **overrides)
    attach_verified_doc(je["id"], uploader_headers=preparer_headers,
                        verifier_headers=approver_headers)
    get_success_data(api_client.submit_journal_entry(je["id"], preparer_headers))
    get_success_data(api_client.approve_journal_entry(je["id"], approver_headers))
    return get_success_data(api_client.post_journal_entry(je["id"], preparer_headers))


# ─── Tier 3: Cutoff → SUBLEDGER_CUT ──────────────────

def drive_entity_period_to_subledger_cut(entity_period_id: str, *,
                                          subledger: str = "AR",
                                          cutoff_at: str = "2026-01-31T00:00:00Z",
                                          cutoff_rule: str = "INCLUSIVE",
                                          cutter_headers=PREPARER,
                                          confirmer_headers=APPROVER) -> dict:
    """Create + cut + confirm one cutoff; bubbles EntityPeriod PREPARING → SUBLEDGER_CUT.
    Returns the CONFIRMED cutoff."""
    cut = get_success_data(api_client.create_subledger_cutoff(
        entity_period_id,
        create_subledger_cutoff_payload(subledger=subledger, cutoff_at=cutoff_at, cutoff_rule=cutoff_rule),
        cutter_headers))
    get_success_data(api_client.cut_subledger_cutoff(cut["id"], cutter_headers))
    return get_success_data(api_client.confirm_subledger_cutoff(cut["id"], confirmer_headers))


# ─── Tier 4: RECONCILED / READY_FOR_CONSOL / SOFT_LOCKED ──

def register_identity_fx_rate(period_id: str, from_ccy: str = "USD", to_ccy: str = "USD",
                               rate_kind: str = "PERIOD_END", rate: float = 1.0,
                               effective_at: str = "2026-01-31T00:00:00Z") -> dict:
    """Register an FX rate (identity by default for same-currency pairs)."""
    return get_success_data(api_client.create_fx_rate(
        period_id,
        create_fx_rate_payload(from_currency=from_ccy, to_currency=to_ccy,
                                rate_kind=rate_kind, rate=rate, effective_at=effective_at),
        CONTROLLER))


def drive_entity_period_to_reconciled(period_id: str, entity_period_id: str, *,
                                       fx_currency: str = "USD") -> dict:
    """SUBLEDGER_CUT → (translate) → mark-reconciled. Returns RECONCILED EntityPeriod."""
    drive_entity_period_to_subledger_cut(entity_period_id)
    register_identity_fx_rate(period_id, from_ccy=fx_currency)
    get_success_data(api_client.translate_entity_period(entity_period_id, CONTROLLER))
    return get_success_data(api_client.mark_entity_period_reconciled(entity_period_id, PREPARER))


def drive_entity_period_to_ready(period_id: str, entity_period_id: str, *,
                                  fx_currency: str = "USD") -> dict:
    """Full walk: PREPARING → SUBLEDGER_CUT → RECONCILED → READY_FOR_CONSOL."""
    drive_entity_period_to_reconciled(period_id, entity_period_id, fx_currency=fx_currency)
    return get_success_data(api_client.mark_entity_period_ready(entity_period_id, PREPARER))


def get_period_version(period_id: str) -> int:
    return get_success_data(api_client.get_period(period_id, CONTROLLER))["version"]


def soft_lock_period(period_id: str) -> dict:
    """Soft-lock with the current version (OCC-fresh)."""
    v = get_period_version(period_id)
    return get_success_data(api_client.soft_lock_period(
        period_id, {"expected_close_period_version": v}, CONTROLLER))


def hard_lock_period(period_id: str) -> dict:
    """Hard-lock with the current version (OCC-fresh)."""
    v = get_period_version(period_id)
    return get_success_data(api_client.hard_lock_period(
        period_id, {"expected_close_period_version": v}, CONTROLLER))


def setup_soft_locked_period(entity_overrides=None, period_overrides=None):
    """Period + one entity driven to SOFT_LOCKED. Returns (period, entity, ep)."""
    period, entity, ep = setup_open_period_with_entity(entity_overrides, period_overrides)
    drive_entity_period_to_ready(period["id"], ep["id"],
                                  fx_currency=(entity.get("functional_currency") or "USD"))
    soft_lock_period(period["id"])
    ep = get_success_data(api_client.get_entity_period(ep["id"], PREPARER))
    return period, entity, ep


def setup_hard_locked_period(entity_overrides=None, period_overrides=None):
    """Period + one entity driven to HARD_LOCKED (posture HARD_CLOSED, status UNDER_REVIEW)."""
    period, entity, ep = setup_soft_locked_period(entity_overrides, period_overrides)
    hard_lock_period(period["id"])
    ep = get_success_data(api_client.get_entity_period(ep["id"], PREPARER))
    return period, entity, ep
