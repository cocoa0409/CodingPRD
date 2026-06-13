"""Payload factories — one per write endpoint, input fields only.

Only fields the client supplies (PRD §3) appear here. Computed and
system-managed fields (status, version, ledger totals, dates derived at
election) are never sent by the client.
"""
from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Plan (PRD §3.1) — only name + applicable_premium_cents are required; the
# timing/pricing knobs each carry a server default and may be omitted.
# ---------------------------------------------------------------------------
def create_plan_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Plan A",
        "applicable_premium_cents": TEST_DEFAULTS["APPLICABLE_PREMIUM_CENTS"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Beneficiary (PRD §3.1) — plan_id, full_name, relationship,
# original_coverage_start all required.
# ---------------------------------------------------------------------------
def create_beneficiary_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "full_name": "Test Beneficiary",
        "relationship": "EMPLOYEE",
        "original_coverage_start": "2024-01-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Qualifying event (PRD §3.2) — all five fields required.
# ---------------------------------------------------------------------------
def create_event_payload(plan_id, beneficiary_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "beneficiary_id": beneficiary_id,
        "event_type": "TERMINATION",
        "event_date": "2026-03-31T00:00:00.000Z",
        "coverage_loss_date": "2026-04-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Invoice (PRD §3.5) — coverage_month required; proration_mode optional
# (defaults to FULL_MONTH server-side).
# ---------------------------------------------------------------------------
def create_invoice_payload(coverage_month, **overrides) -> dict:
    defaults = {"coverage_month": coverage_month}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Payment (PRD §3.6) — amount_cents + target_coverage_month required.
# ---------------------------------------------------------------------------
def create_payment_payload(amount_cents, target_coverage_month, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "target_coverage_month": target_coverage_month,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Subsidy grant (PRD §3.7) — subsidy_pct, start_month, end_month required.
# ---------------------------------------------------------------------------
def create_subsidy_payload(subsidy_pct, start_month, end_month, **overrides) -> dict:
    defaults = {
        "subsidy_pct": subsidy_pct,
        "start_month": start_month,
        "end_month": end_month,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Disability extension (PRD §3.8) — determination_date required.
# ---------------------------------------------------------------------------
def apply_disability_extension_payload(determination_date, **overrides) -> dict:
    defaults = {"determination_date": determination_date}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Early termination (PRD §3.9) — reason required.
# ---------------------------------------------------------------------------
def terminate_early_payload(reason, **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Refund (PRD §3.11 / §2.8) — refund_amount_cents + expected_account_version
# both required.
# ---------------------------------------------------------------------------
def refund_payload(refund_amount_cents, expected_account_version, **overrides) -> dict:
    defaults = {
        "refund_amount_cents": refund_amount_cents,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Clock control (PRD §2.5).
# ---------------------------------------------------------------------------
def set_clock_payload(now_iso8601) -> dict:
    return {"now_iso8601": now_iso8601}
