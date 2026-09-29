"""Payload builders.

Each builder returns a plain dict satisfying the PRD's required fields for one
create or transition call, with optional fields stated explicitly wherever an
expected value would otherwise lean on a fallback.  Monetary amounts are always
Python integers of cents and rates always integers of basis points, never
strings.  The brokered pair `broker_name` / `recordkeeping_status` is emitted
only when the ownership category is `BROKERED_PASS_THROUGH`, because the PRD
requires it to be absent otherwise.
"""
import itertools

from . import constants as C

_institution_certs = itertools.count(60001)
_bidder_certs = itertools.count(70001)
_seq = itertools.count(1)
_data_room_days = itertools.count(2)


def _n():
    return next(_seq)


# ---------------------------------------------------------------------------
# Institutions (PRD 3.1)
# ---------------------------------------------------------------------------
def institution_payload(
    cert_number=None,
    legal_name=None,
    charter_state="WA",
    book_asset_value_cents=25000000,
    estimated_liquidation_recovery_cents=18000000,
    **overrides,
):
    i = _n()
    payload = {
        "cert_number": cert_number if cert_number is not None else str(next(_institution_certs)),
        "legal_name": legal_name if legal_name is not None else f"Cascade Trust Bank {i}",
        "charter_state": charter_state,
        "book_asset_value_cents": book_asset_value_cents,
        "estimated_liquidation_recovery_cents": estimated_liquidation_recovery_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Readiness submissions (PRD 3.1)
# ---------------------------------------------------------------------------
def readiness_submission_payload(
    file_format="FDIC_STANDARD_V2",
    record_count=C.CLEAN_RECORD_COUNT,
    malformed_record_count=C.CLEAN_MALFORMED_COUNT,
    reported_deposit_total_cents=0,
    **overrides,
):
    """A package scoring exactly 9800 bps by default, which clears the score floor."""
    payload = {
        "file_format": file_format,
        "record_count": record_count,
        "malformed_record_count": malformed_record_count,
        "reported_deposit_total_cents": reported_deposit_total_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Depositor records (PRD 3.2)
# ---------------------------------------------------------------------------
def depositor_record_payload(
    tin_hash=None,
    legal_name=None,
    depositor_type="NATURAL_PERSON",
    contact_email=None,
    **overrides,
):
    i = _n()
    payload = {
        "tin_hash": tin_hash if tin_hash is not None else f"TIN-HASH-{i:05d}",
        "legal_name": legal_name if legal_name is not None else f"Depositor {i}",
        "depositor_type": depositor_type,
        "contact_email": (
            contact_email if contact_email is not None else f"depositor{i}@example.com"
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Deposit accounts and ownership interests (PRD 3.2)
# ---------------------------------------------------------------------------
def deposit_account_payload(
    institution_id,
    primary_depositor_id,
    account_number=None,
    ownership_category="SINGLE",
    balance_cents=C.ACCOUNT_A_BALANCE_CENTS,
    accrued_interest_cents=0,
    opened_at="2024-03-01T00:00:00Z",
    broker_name=None,
    recordkeeping_status=None,
    **overrides,
):
    i = _n()
    payload = {
        "institution_id": institution_id,
        "primary_depositor_id": primary_depositor_id,
        "account_number": (
            account_number if account_number is not None else f"ACCT-{i:05d}"
        ),
        "ownership_category": ownership_category,
        "balance_cents": balance_cents,
        "accrued_interest_cents": accrued_interest_cents,
        "opened_at": opened_at,
    }
    if ownership_category == "BROKERED_PASS_THROUGH":
        payload["broker_name"] = (
            broker_name if broker_name is not None else f"Broker House {i}"
        )
        payload["recordkeeping_status"] = (
            recordkeeping_status if recordkeeping_status is not None else "COMPLETE"
        )
    else:
        if broker_name is not None:
            payload["broker_name"] = broker_name
        if recordkeeping_status is not None:
            payload["recordkeeping_status"] = recordkeeping_status
    payload.update(overrides)
    return payload


def ownership_interest_payload(
    depositor_record_id, interest_role, designated_share_bps, **overrides
):
    payload = {
        "depositor_record_id": depositor_record_id,
        "interest_role": interest_role,
        "designated_share_bps": designated_share_bps,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Determinations (PRD 3.4)
# ---------------------------------------------------------------------------
def determination_payload(
    depositor_record_id, expected_depositor_record_version, revision_reason=None, **overrides
):
    payload = {
        "depositor_record_id": depositor_record_id,
        "expected_depositor_record_version": expected_depositor_record_version,
    }
    if revision_reason is not None:
        payload["revision_reason"] = revision_reason
    payload.update(overrides)
    return payload


def prepare_payload(method_variant="AGGREGATE_BY_CATEGORY", **overrides):
    payload = {"method_variant": method_variant}
    payload.update(overrides)
    return payload


def request_revision_payload(revision_reason="Beneficiary documentation incomplete", **overrides):
    payload = {"revision_reason": revision_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Marketing, bidders and bids (PRD 3.7)
# ---------------------------------------------------------------------------
def marketing_payload(marketing_action="OPEN", bid_deadline_at="2026-09-30T00:00:00Z", **overrides):
    payload = {"marketing_action": marketing_action}
    if marketing_action == "OPEN" and bid_deadline_at is not None:
        payload["bid_deadline_at"] = bid_deadline_at
    payload.update(overrides)
    return payload


def bidder_payload(
    legal_name=None,
    cert_number=None,
    tier1_capital_ratio_bps=1500,
    camels_composite=2,
    **overrides,
):
    i = _n()
    payload = {
        "legal_name": legal_name if legal_name is not None else f"Acquiring Bank {i}",
        "cert_number": cert_number if cert_number is not None else str(next(_bidder_certs)),
        "tier1_capital_ratio_bps": tier1_capital_ratio_bps,
        "camels_composite": camels_composite,
    }
    payload.update(overrides)
    return payload


def qualification_payload(decision="QUALIFY", disqualification_reason=None, **overrides):
    payload = {"decision": decision}
    if disqualification_reason is not None:
        payload["disqualification_reason"] = disqualification_reason
    payload.update(overrides)
    return payload


def next_data_room_window():
    """A fresh data-room interval, spaced a whole day from every earlier one."""
    day = next(_data_room_days)
    return (f"2026-09-{day:02d}T09:00:00Z", f"2026-09-{day:02d}T12:00:00Z")


def bid_payload(
    institution_id,
    bidder_id,
    structure="WHOLE_BANK_PA",
    deposit_premium_bps=300,
    asset_discount_bps=1000,
    loss_share_pct_bps=0,
    asset_retention_pool_cents=0,
    data_room_window_start=None,
    data_room_window_end=None,
    **overrides,
):
    if data_room_window_start is None or data_room_window_end is None:
        start, end = next_data_room_window()
        data_room_window_start = data_room_window_start or start
        data_room_window_end = data_room_window_end or end
    payload = {
        "institution_id": institution_id,
        "bidder_id": bidder_id,
        "structure": structure,
        "deposit_premium_bps": deposit_premium_bps,
        "asset_discount_bps": asset_discount_bps,
        "loss_share_pct_bps": loss_share_pct_bps,
        "asset_retention_pool_cents": asset_retention_pool_cents,
        "data_room_window_start": data_room_window_start,
        "data_room_window_end": data_room_window_end,
    }
    payload.update(overrides)
    return payload


def evaluate_payload(test_variant="EXPECTED_LOSS_SHARE", **overrides):
    payload = {"test_variant": test_variant}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Branch reopenings (PRD 3.8)
# ---------------------------------------------------------------------------
def branch_reopening_payload(
    branch_code=None,
    reopen_window_start="2026-08-10T09:00:00Z",
    reopen_window_end="2026-08-10T17:00:00Z",
    staffing_headcount=10,
    **overrides,
):
    i = _n()
    payload = {
        "branch_code": branch_code if branch_code is not None else f"BR-{i:03d}",
        "reopen_window_start": reopen_window_start,
        "reopen_window_end": reopen_window_end,
        "staffing_headcount": staffing_headcount,
    }
    payload.update(overrides)
    return payload


def reschedule_payload(reopen_window_start, reopen_window_end, **overrides):
    payload = {
        "reopen_window_start": reopen_window_start,
        "reopen_window_end": reopen_window_end,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Receivership disposition and dividends (PRD 3.9)
# ---------------------------------------------------------------------------
def proceeds_payload(
    asset_pool_code=None, gross_proceeds_cents=5000000, disposition_expense_cents=1000000, **overrides
):
    i = _n()
    payload = {
        "asset_pool_code": asset_pool_code if asset_pool_code is not None else f"POOL-{i:03d}",
        "gross_proceeds_cents": gross_proceeds_cents,
        "disposition_expense_cents": disposition_expense_cents,
    }
    payload.update(overrides)
    return payload


def dividend_payload(
    priority_class, declared_rate_bps, expected_institution_version, **overrides
):
    payload = {
        "priority_class": priority_class,
        "declared_rate_bps": declared_rate_bps,
        "expected_institution_version": expected_institution_version,
    }
    payload.update(overrides)
    return payload
