"""Payload builders: valid-by-default request bodies with keyword overrides.

Every builder returns a dict that satisfies the PRD's request-shape rules for
its endpoint. Pass keyword overrides to vary one field; pass `None` explicitly
where the PRD allows a nullable optional field.
"""

import itertools

from .constants import TEST_DEFAULTS

_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


def unique_suffix() -> str:
    """A short monotonically increasing suffix for uniqueness-constrained fields."""
    return f"{_next():04d}"


# ─── Logical clock ────────────────────────────────────

def clock_payload(to_iso8601: str = TEST_DEFAULTS["CLOCK"], **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ─── Creators ─────────────────────────────────────────

def creator_payload(**overrides) -> dict:
    payload = {
        "full_name": f"Wanda Writer {unique_suffix()}",
        "crafts": ["SCRIPT"],
        "default_page_rate_cents": 12000,
    }
    payload.update(overrides)
    return payload


# ─── Titles ───────────────────────────────────────────

def title_payload(**overrides) -> dict:
    payload = {
        "name": f"{TEST_DEFAULTS['TITLE_NAME']} {unique_suffix()}",
        "planned_issue_count": TEST_DEFAULTS["PLANNED_ISSUE_COUNT"],
        "royalty_pool_bps": TEST_DEFAULTS["ROYALTY_POOL_BPS"],
        "cover_participation_bps": TEST_DEFAULTS["COVER_PARTICIPATION_BPS"],
    }
    payload.update(overrides)
    return payload


def title_cancel_payload(**overrides) -> dict:
    payload = {"reason": "Line restructuring after the fall sales conference."}
    payload.update(overrides)
    return payload


# ─── Creative assignments ─────────────────────────────

def assignment_payload(creator_id: str, expected_title_version: int, **overrides) -> dict:
    payload = {
        "creator_id": creator_id,
        "craft": "SCRIPT",
        "page_rate_cents": 12000,
        "royalty_share_bps": 5000,
        "booking_start_date": "2026-08-01",
        "booking_end_date": "2026-09-01",
        "advance_cents": 0,
        "expected_title_version": expected_title_version,
    }
    payload.update(overrides)
    return payload


def counter_payload(**overrides) -> dict:
    payload = {
        "counter_page_rate_cents": 13600,
        "counter_royalty_share_bps": 5500,
    }
    payload.update(overrides)
    return payload


def repropose_payload(**overrides) -> dict:
    payload = {
        "page_rate_cents": 12500,
        "royalty_share_bps": 5200,
    }
    payload.update(overrides)
    return payload


def terminate_payload(**overrides) -> dict:
    payload = {"reason": "Terms could not be agreed within the negotiation rounds."}
    payload.update(overrides)
    return payload


# ─── Issues ───────────────────────────────────────────

def issue_payload(**overrides) -> dict:
    payload = {
        "issue_number": 1,
        "page_count": TEST_DEFAULTS["PAGE_COUNT"],
        "cover_price_cents": TEST_DEFAULTS["COVER_PRICE_CENTS"],
        "target_on_sale_date": TEST_DEFAULTS["TARGET_ON_SALE_DATE"],
    }
    payload.update(overrides)
    return payload


# ─── Production stages ────────────────────────────────

def stage_payload(assignment_id: str, **overrides) -> dict:
    payload = {
        "assignment_id": assignment_id,
        "craft": "SCRIPT",
        "planned_start_date": "2026-08-01",
        "planned_due_date": "2026-08-20",
    }
    payload.update(overrides)
    return payload


def deliver_payload(**overrides) -> dict:
    payload = {"delivered_pages": TEST_DEFAULTS["PAGE_COUNT"]}
    payload.update(overrides)
    return payload


def kick_back_payload(**overrides) -> dict:
    payload = {"note": "Page 14 panel flow does not read; please revise the sequence."}
    payload.update(overrides)
    return payload


# ─── Catalogs and solicitations ───────────────────────

def catalog_payload(**overrides) -> dict:
    payload = {
        "solicitation_month": TEST_DEFAULTS["SOLICITATION_MONTH"],
        "submission_deadline": TEST_DEFAULTS["SUBMISSION_DEADLINE"],
        "on_sale_month": TEST_DEFAULTS["ON_SALE_MONTH"],
        "max_slots": TEST_DEFAULTS["MAX_SLOTS"],
    }
    payload.update(overrides)
    return payload


def solicitation_payload(issue_id: str, **overrides) -> dict:
    payload = {
        "issue_id": issue_id,
        "cover_image_url": TEST_DEFAULTS["COVER_IMAGE_URL"],
        "copy_text": TEST_DEFAULTS["COPY_TEXT"],
        "variant_cover_ids": [],
    }
    payload.update(overrides)
    return payload


def withdraw_payload(**overrides) -> dict:
    payload = {"reason": "Cover art not approved in time for the catalog slate."}
    payload.update(overrides)
    return payload


# ─── Variant covers ───────────────────────────────────

def standard_cover_payload(**overrides) -> dict:
    payload = {
        "code": "A",
        "kind": "STANDARD",
        "cover_price_cents": TEST_DEFAULTS["COVER_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def ratio_cover_payload(incentive_ratio: int = 10, **overrides) -> dict:
    payload = {
        "code": f"R{incentive_ratio}",
        "kind": "RATIO_INCENTIVE",
        "incentive_ratio": incentive_ratio,
        "cover_price_cents": TEST_DEFAULTS["COVER_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def exclusive_cover_payload(**overrides) -> dict:
    payload = {
        "code": "X",
        "kind": "RETAILER_EXCLUSIVE",
        "cover_price_cents": 999,
    }
    payload.update(overrides)
    return payload


# ─── Retailers ────────────────────────────────────────

def retailer_payload(**overrides) -> dict:
    payload = {
        "account_no": f"DM-{unique_suffix()}",
        "name": f"Rocket Comics {unique_suffix()}",
        "credit_limit_cents": 1_000_000,
        "non_returnable_ack": True,
        "opening_units_ytd": 0,
    }
    payload.update(overrides)
    return payload


def suspend_payload(**overrides) -> dict:
    payload = {"reason": "Account past due on two invoicing cycles."}
    payload.update(overrides)
    return payload


# ─── Retailer orders ──────────────────────────────────

def order_payload(retailer_id: str, issue_id: str, **overrides) -> dict:
    payload = {
        "retailer_id": retailer_id,
        "issue_id": issue_id,
        "standard_qty": 100,
        "exclusive_variant_qty": 0,
    }
    payload.update(overrides)
    return payload


def adjust_payload(standard_qty: int = 120, **overrides) -> dict:
    payload = {"standard_qty": standard_qty}
    payload.update(overrides)
    return payload


def order_cancel_payload(**overrides) -> dict:
    payload = {"reason": "Store closing; the order can no longer be fulfilled."}
    payload.update(overrides)
    return payload


# ─── Print runs ───────────────────────────────────────

def print_run_payload(expected_issue_version: int, basis: str = "ORDER_DRIVEN", **overrides) -> dict:
    payload = {
        "basis": basis,
        "expected_issue_version": expected_issue_version,
    }
    payload.update(overrides)
    return payload


def print_run_cancel_payload(**overrides) -> dict:
    payload = {"reason": "Printer slot lost; the run is being rebooked."}
    payload.update(overrides)
    return payload


# ─── Release windows ──────────────────────────────────

def release_window_payload(channel: str, release_date: str, **overrides) -> dict:
    payload = {
        "channel": channel,
        "release_date": release_date,
        "expected_net_receipts_cents": 0,
    }
    payload.update(overrides)
    return payload


# ─── Revenue events ───────────────────────────────────

def revenue_event_payload(issue_id: str, **overrides) -> dict:
    payload = {
        "issue_id": issue_id,
        "channel": "PRINT_DM",
        "basis_status": "ACTUAL",
        "gross_receipts_cents": 400_000,
        "net_receipts_cents": 328_500,
        "units": 1108,
        "period": "2026-12",
    }
    payload.update(overrides)
    return payload


# ─── Royalty statements ───────────────────────────────

def statement_payload(title_id: str, creator_id: str, **overrides) -> dict:
    payload = {
        "title_id": title_id,
        "creator_id": creator_id,
        "period": "2026-12",
        "basis": "ESTIMATED",
    }
    payload.update(overrides)
    return payload


def pay_payload(**overrides) -> dict:
    payload = {"payment_reference": "ACH-2027-000144"}
    payload.update(overrides)
    return payload


def reverse_payload(**overrides) -> dict:
    payload = {"reason": "Channel receipts restated by the distributor."}
    payload.update(overrides)
    return payload
