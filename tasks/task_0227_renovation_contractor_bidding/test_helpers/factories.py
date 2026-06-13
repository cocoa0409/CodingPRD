"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD: Project.min_rating is optional (defaults to
0); all other source: input fields are required and are always supplied here.
"""
from .constants import (
    DEFAULT_BID_DEADLINE,
    DEFAULT_LICENSE_EXPIRY,
    TEST_DEFAULTS,
)

_email_counter = [0]


def _unique_email(prefix: str = "user") -> str:
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


# ─── Homeowner ─────────────────────────────────────────────────────────────
def create_homeowner_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Homeowner",
        "email": _unique_email("homeowner"),
    }
    defaults.update(overrides)
    return defaults


# ─── Contractor ────────────────────────────────────────────────────────────
def create_contractor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Contractor LLC",
        "trade": "GENERAL",
        "license_number": "LIC-0001",
        "license_expiry": DEFAULT_LICENSE_EXPIRY,
        "insurance_coverage_cents": TEST_DEFAULTS["INSURANCE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


# ─── Project ───────────────────────────────────────────────────────────────
def create_project_payload(homeowner_id: str, **overrides) -> dict:
    defaults = {
        "homeowner_id": homeowner_id,
        "title": "Test Project",
        "budget_cap_cents": TEST_DEFAULTS["BUDGET_CAP_CENTS"],
        "bid_deadline": DEFAULT_BID_DEADLINE,
        "required_trade": "GENERAL",
        "min_rating": 0,
    }
    defaults.update(overrides)
    return defaults


# ─── ScopeLineItem ─────────────────────────────────────────────────────────
def create_scope_line_item_payload(**overrides) -> dict:
    defaults = {
        "description": "Whole job",
        "quantity": 1,
        "unit": "LUMP",
        "estimated_unit_cost_cents": TEST_DEFAULTS["WHOLE_JOB_UNIT_COST"],
    }
    defaults.update(overrides)
    return defaults


# ─── Milestone ─────────────────────────────────────────────────────────────
def create_milestone_payload(sequence: int = 1, release_pct: float = 1.0, **overrides) -> dict:
    defaults = {
        "sequence": sequence,
        "title": f"Milestone {sequence}",
        "release_pct": release_pct,
    }
    defaults.update(overrides)
    return defaults


# ─── Bid ───────────────────────────────────────────────────────────────────
def create_bid_payload(project_id: str, contractor_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "contractor_id": contractor_id,
        "duration_days": TEST_DEFAULTS["DURATION_DAYS"],
    }
    defaults.update(overrides)
    return defaults


# ─── BidLineItem ───────────────────────────────────────────────────────────
def create_bid_line_item_payload(scope_line_item_id: str, **overrides) -> dict:
    defaults = {
        "scope_line_item_id": scope_line_item_id,
        "quantity": 1,
        "unit_price_cents": TEST_DEFAULTS["WHOLE_JOB_UNIT_COST"],
    }
    defaults.update(overrides)
    return defaults


# ─── Escrow funding ────────────────────────────────────────────────────────
def fund_escrow_payload(deposit_cents: int, **overrides) -> dict:
    defaults = {"deposit_cents": deposit_cents}
    defaults.update(overrides)
    return defaults


# ─── Draw ──────────────────────────────────────────────────────────────────
def create_draw_payload(project_id: str, milestone_id: str,
                        conditional_waiver_amount_cents: int, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "milestone_id": milestone_id,
        "conditional_waiver_amount_cents": conditional_waiver_amount_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── LienWaiver ────────────────────────────────────────────────────────────
def create_lien_waiver_payload(project_id: str, contractor_id: str, draw_id: str,
                               amount_cents: int, waiver_type: str = "UNCONDITIONAL",
                               **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "contractor_id": contractor_id,
        "draw_id": draw_id,
        "waiver_type": waiver_type,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── ChangeOrder ───────────────────────────────────────────────────────────
def create_change_order_payload(project_id: str, bid_id: str, delta_cents: int,
                                **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "bid_id": bid_id,
        "description": "Scope change",
        "delta_cents": delta_cents,
    }
    defaults.update(overrides)
    return defaults


def approve_change_order_payload(expected_bid_version: int, **overrides) -> dict:
    defaults = {"expected_bid_version": expected_bid_version}
    defaults.update(overrides)
    return defaults


# ─── Award ─────────────────────────────────────────────────────────────────
def award_project_payload(bid_id: str, expected_project_version: int, **overrides) -> dict:
    defaults = {
        "bid_id": bid_id,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Dispute ───────────────────────────────────────────────────────────────
def create_dispute_payload(project_id: str, subject_id: str, raised_by: str = "HOMEOWNER",
                           subject_type: str = "DRAW", **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "raised_by": raised_by,
        "reason": "Quality issue",
    }
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(resolution: str, **overrides) -> dict:
    defaults = {"resolution": resolution}
    defaults.update(overrides)
    return defaults


# ─── Rating ────────────────────────────────────────────────────────────────
def rate_contractor_payload(stars: int, **overrides) -> dict:
    defaults = {"stars": stars}
    defaults.update(overrides)
    return defaults


# ─── Clock ─────────────────────────────────────────────────────────────────
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
