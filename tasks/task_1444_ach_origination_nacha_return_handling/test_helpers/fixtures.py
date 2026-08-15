"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the API server before every test, so every helper builds
its preconditions from scratch using only PRD-declared endpoints. All helpers
use get_success_data() so setup failures surface as clear "Setup step failed"
errors rather than confusing assertion failures.

Identity threading: after creating an Originator, every ownership-gated call
uses make_originator_headers(originator["id"]) — never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    append_entries_payload,
    create_ach_file_payload,
    create_cutoff_window_payload,
    create_originator_payload,
    create_reversal_payload,
    make_entry_batch,
    patch_originator_payload,
    register_noc_payload,
    register_return_payload,
    set_clock_payload,
)
from .test_users import (
    FINANCE_USER_ID,
    OPERATIONS_USER_ID,
    RISK_OFFICER_USER_ID,
    TEST_USERS,
    UNDERWRITER_USER_ID,
    make_finance_headers,
    make_operations_headers,
    make_originator_headers,
    make_risk_officer_headers,
    make_underwriter_headers,
)

UNDERWRITER = TEST_USERS["underwriter_headers"]
OPERATIONS = TEST_USERS["operations_headers"]
RISK_OFFICER = TEST_USERS["risk_officer_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ─── Tier 0: environment primitives ─────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD 2.4). Returns {current_utc}."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), OPERATIONS))


def define_cutoff_window(**overrides) -> dict:
    """Define one CutoffWindow (PRD 3.2). Defaults to the standard NEXT_DAY card."""
    return get_success_data(
        api_client.create_cutoff_window(create_cutoff_window_payload(**overrides),
                                        OPERATIONS))


def define_next_day_window() -> dict:
    """Define the standard NEXT_DAY 00:00-23:00 window (60/200/100 rate card)."""
    return define_cutoff_window(**TEST_DEFAULTS["NEXT_DAY_WINDOW"])


def define_same_day_1_window() -> dict:
    """Define the standard SAME_DAY_1 09:00-12:00 window (150/500/400 card)."""
    return define_cutoff_window(**TEST_DEFAULTS["SAME_DAY_1_WINDOW"])


# ─── Tier 1: originator lifecycle ───────────────────

def create_pending_originator(legal_name="Test Originator Co",
                              sec_codes=("CCD",)) -> dict:
    """Register an originator (born PENDING_UNDERWRITING, PRD 3.1)."""
    return get_success_data(api_client.create_originator(
        create_originator_payload(legal_name, sec_codes), UNDERWRITER))


def approve_originator(originator, exposure_limit_cents=None,
                       fee_discount_bps=0) -> dict:
    """PATCH decision=APPROVE from PENDING_UNDERWRITING to ACTIVE (PRD 3.1)."""
    limit = (TEST_DEFAULTS["EXPOSURE_LIMIT_CENTS"]
             if exposure_limit_cents is None else exposure_limit_cents)
    return get_success_data(api_client.patch_originator(
        originator["id"],
        patch_originator_payload(originator["version"], decision="APPROVE",
                                 exposure_limit_cents=limit,
                                 fee_discount_bps=fee_discount_bps),
        UNDERWRITER))


def create_active_originator(legal_name="Test Originator Co", sec_codes=("CCD",),
                             exposure_limit_cents=None,
                             fee_discount_bps=0) -> dict:
    """Create + approve. Returns the ACTIVE originator."""
    pending = create_pending_originator(legal_name, sec_codes)
    return approve_originator(pending, exposure_limit_cents, fee_discount_bps)


def open_manual_risk_case(originator_id: str) -> dict:
    """Manually open a RiskCase (source MANUAL) as the risk officer (PRD 3.8)."""
    return get_success_data(api_client.create_risk_case(originator_id,
                                                        RISK_OFFICER))


def resolve_case_ok(risk_case_id: str, action: str,
                    user_id: str = RISK_OFFICER_USER_ID) -> dict:
    """Resolve an OPEN risk case with the given action (PRD 3.8)."""
    return get_success_data(api_client.resolve_risk_case(
        risk_case_id, {"action": action}, make_risk_officer_headers(user_id)))


def compute_snapshot_ok(originator_id: str) -> dict:
    """Compute a return-rate snapshot at the current clock (PRD 3.8)."""
    return get_success_data(
        api_client.create_return_rate_snapshot(originator_id, RISK_OFFICER))


# ─── Tier 2: files and entries ──────────────────────

def create_warehoused_file(org, sec_code="CCD", requested_window_kind="NEXT_DAY",
                           effective_date="2026-08-03") -> dict:
    """File intake as the owning OriginatorOps caller (PRD 3.3)."""
    return get_success_data(api_client.create_ach_file(
        create_ach_file_payload(sec_code, requested_window_kind, effective_date),
        make_originator_headers(org["id"])))


def append_entries_ok(file_id: str, entries: list) -> dict:
    """Append entries to a WAREHOUSED file, threading the current file version.

    Reads the file first so the OCC guard always sees a fresh version; the
    file's owner identity is recovered from the file itself.
    """
    current = get_success_data(api_client.get_ach_file(file_id, OPERATIONS))
    return get_success_data(api_client.append_entries(
        file_id,
        append_entries_payload(current["version"], entries),
        make_originator_headers(current["originator_id"])))


def list_file_entries(file_id: str) -> list:
    """List a file's entries in creation order (PRD 2.3)."""
    return get_success_data(api_client.list_entries(file_id, OPERATIONS))


def release_file_ok(file_id: str) -> dict:
    """Release a WAREHOUSED file as OdfiOperations (PRD 3.4)."""
    return get_success_data(api_client.release_file(file_id, OPERATIONS))


def cancel_file_ok(file_id: str, originator_id: str) -> dict:
    """Cancel a WAREHOUSED file as its owning originator (PRD 3.3)."""
    return get_success_data(
        api_client.cancel_file(file_id, make_originator_headers(originator_id)))


def read_originator(originator_id: str) -> dict:
    return get_success_data(api_client.get_originator(originator_id, OPERATIONS))


def read_file(file_id: str) -> dict:
    return get_success_data(api_client.get_ach_file(file_id, OPERATIONS))


def read_entry(entry_id: str) -> dict:
    return get_success_data(api_client.get_entry(entry_id, OPERATIONS))


def read_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_batch(batch_id, OPERATIONS))


# ─── Tier 3: batch lifecycle ────────────────────────

def dispatch_batch_ok(batch_id: str, user_id: str = OPERATIONS_USER_ID) -> dict:
    """Advance a batch OPEN -> DISPATCHED (PRD 3.5)."""
    return get_success_data(api_client.advance_batch(
        batch_id, {"action": "DISPATCH"}, make_operations_headers(user_id)))


def settle_batch_ok(batch_id: str, user_id: str = OPERATIONS_USER_ID) -> dict:
    """Advance a batch DISPATCHED -> SETTLED (PRD 3.5)."""
    return get_success_data(api_client.advance_batch(
        batch_id, {"action": "SETTLE"}, make_operations_headers(user_id)))


def reconcile_batch_ok(batch_id: str, user_id: str = FINANCE_USER_ID) -> dict:
    """Reconcile a SETTLED batch as OdfiFinance (PRD 3.5)."""
    return get_success_data(
        api_client.reconcile_batch(batch_id, make_finance_headers(user_id)))


def list_gl_postings(batch_id: str) -> list:
    return get_success_data(api_client.list_gl_postings(batch_id, FINANCE))


# ─── Tier 4: entry-level lifecycle ──────────────────

def register_return_ok(entry_id: str, return_code: str) -> dict:
    """Register an inbound return against a SETTLED entry (PRD 3.6)."""
    return get_success_data(api_client.register_return(
        entry_id, register_return_payload(return_code), OPERATIONS))


def represent_ok(entry_id: str) -> dict:
    """Re-present a RETURNED entry (PRD 3.6)."""
    return get_success_data(api_client.represent_entry(entry_id, OPERATIONS))


def close_entry_ok(entry_id: str, originator_id: str) -> dict:
    """Close a SETTLED/RETURNED entry as its owning originator (PRD 3.6)."""
    return get_success_data(
        api_client.close_entry(entry_id, make_originator_headers(originator_id)))


def register_noc_ok(entry_id: str, noc_code="C01",
                    corrected_data="acct=000111222") -> dict:
    """Register an inbound NOC against an entry (PRD 3.6)."""
    return get_success_data(api_client.register_noc(
        entry_id, register_noc_payload(noc_code, corrected_data), OPERATIONS))


def apply_noc_ok(noc_id: str, originator_id: str) -> dict:
    """Apply a NOC as the owning originator (PRD 3.6)."""
    return get_success_data(
        api_client.apply_noc(noc_id, make_originator_headers(originator_id)))


def create_reversal_ok(entry_id: str, originator_id: str,
                       reason="DUPLICATE_ENTRY") -> dict:
    """Request a reversal of a SETTLED entry as its owner (PRD 3.7)."""
    return get_success_data(api_client.create_reversal(
        entry_id, create_reversal_payload(reason),
        make_originator_headers(originator_id)))


def advance_reversal_ok(reversal_id: str, action="TRANSMIT", headers=None) -> dict:
    """Advance a REQUESTED reversal (TRANSMIT by ops / CANCEL by owner)."""
    return get_success_data(api_client.advance_reversal(
        reversal_id, {"action": action}, headers or OPERATIONS))


# ─── Tier 5: full-lifecycle composites ──────────────

def setup_file_with_entries(org, entries, sec_code="CCD",
                            requested_window_kind="NEXT_DAY",
                            effective_date="2026-08-03") -> dict:
    """WAREHOUSED file with the given entries appended. Returns the file."""
    ach_file = create_warehoused_file(org, sec_code, requested_window_kind,
                                      effective_date)
    return append_entries_ok(ach_file["id"], entries)


def setup_released_file(org, entries, sec_code="CCD",
                        requested_window_kind="NEXT_DAY",
                        effective_date="2026-08-03"):
    """File with entries, released. Returns (released_file, batch_id)."""
    ach_file = setup_file_with_entries(org, entries, sec_code,
                                       requested_window_kind, effective_date)
    released = release_file_ok(ach_file["id"])
    return released, released["settlement_batch_id"]


def setup_settled_file(org, entries, sec_code="CCD",
                       requested_window_kind="NEXT_DAY",
                       effective_date="2026-08-03",
                       ops_user_id: str = OPERATIONS_USER_ID):
    """File -> entries -> release -> dispatch -> settle.

    Returns (settled_file, batch_id, settled_entries_in_creation_order).
    """
    released, batch_id = setup_released_file(
        org, entries, sec_code, requested_window_kind, effective_date)
    dispatch_batch_ok(batch_id, ops_user_id)
    settle_batch_ok(batch_id, ops_user_id)
    settled_file = read_file(released["id"])
    return settled_file, batch_id, list_file_entries(released["id"])


def setup_standard_environment(legal_name="Test Originator Co",
                               sec_codes=("CCD",), exposure_limit_cents=None,
                               fee_discount_bps=0, clock="2026-08-03T10:00:00Z"):
    """NEXT_DAY window + ACTIVE originator + clock set. Returns the originator."""
    define_next_day_window()
    org = create_active_originator(legal_name, sec_codes, exposure_limit_cents,
                                   fee_discount_bps)
    if clock is not None:
        set_clock(clock)
    return org
