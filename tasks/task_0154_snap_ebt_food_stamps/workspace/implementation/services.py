"""Domain services: recompute helpers, serializers, side-effect helpers."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from common import STORE, now_iso_utc, gen_id, gen_last4, system_fields_new, touch, parse_iso8601, ApiError
from calculations import (
    calc_net_monthly_income, calc_monthly_allotment, calc_abawd_status,
    compute_household_size, compute_gross_income_cents, compute_has_elderly_or_disabled,
    gross_income_limit, net_income_limit, max_allotment_for_size,
)


# -----------------------------------------------------------------------------
# Household recompute
# -----------------------------------------------------------------------------

def recompute_household_aggregates(household: dict, bump_version: bool = True) -> None:
    """Recompute household_size, gross income, has_eod, net income, monthly allotment.
    Bumps version/updated_at only if values change."""
    clock_now = STORE.clock.now
    new_size = compute_household_size(household["id"])
    new_gross = compute_gross_income_cents(household["id"])
    new_eod = compute_has_elderly_or_disabled(household["id"], clock_now)

    # Temporarily set into household for net income computation
    household["household_size"] = new_size
    household["gross_monthly_income_cents"] = new_gross
    household["has_elderly_or_disabled"] = new_eod

    new_net = calc_net_monthly_income(household)
    household["net_monthly_income_cents"] = new_net
    new_allotment = calc_monthly_allotment(household)
    household["monthly_allotment_cents"] = new_allotment

    if bump_version:
        touch(household)


def recompute_all_abawd_statuses(household_id: str) -> None:
    """Update abawd_status for all active members of a household (after composition change).
    Does not bump version unless status changed."""
    for m in list(STORE.members.values()):
        if m["household_id"] != household_id:
            continue
        if m["status"] != "ACTIVE":
            continue
        new_status = calc_abawd_status(m)
        if m.get("abawd_status") != new_status:
            m["abawd_status"] = new_status
            touch(m)


def lazy_expire_waivers_for_member(member_id: str) -> None:
    """Lazy-expire APPROVED waivers whose effective_to <= clock.now."""
    clock_now = STORE.clock.now
    for w in STORE.waivers.values():
        if w["member_id"] != member_id:
            continue
        if w["state"] != "APPROVED":
            continue
        try:
            et = parse_iso8601(w["effective_to"])
        except Exception:
            continue
        if et <= clock_now:
            w["state"] = "EXPIRED"
            touch(w)


def lazy_refresh_member(member: dict) -> None:
    """Lazy recompute of abawd_status for a member based on current clock and waivers."""
    if member["status"] != "ACTIVE":
        return
    lazy_expire_waivers_for_member(member["id"])
    new_status = calc_abawd_status(member)
    if member.get("abawd_status") != new_status:
        member["abawd_status"] = new_status
        touch(member)


def lazy_refresh_household(household: dict) -> None:
    """Lazy recompute on read."""
    # Expire any waivers and recompute abawd
    for m in [m for m in STORE.members.values() if m["household_id"] == household["id"] and m["status"] == "ACTIVE"]:
        lazy_expire_waivers_for_member(m["id"])
    # Recompute aggregates
    recompute_household_aggregates(household, bump_version=False)
    recompute_all_abawd_statuses(household["id"])


# -----------------------------------------------------------------------------
# Card balance
# -----------------------------------------------------------------------------

def recompute_card_balance(card: dict) -> None:
    total = 0
    for e in STORE.ledger.values():
        if e["card_id"] == card["id"]:
            total += int(e["amount_cents"])
    card["balance_cents"] = total


def find_active_card_for_household(household_id: str) -> dict | None:
    for c in STORE.cards.values():
        if c["household_id"] == household_id and c["status"] in ("ISSUED", "ACTIVE", "SUSPENDED"):
            return c
    return None


# -----------------------------------------------------------------------------
# Ledger entry creation
# -----------------------------------------------------------------------------

def benefit_month_from_clock() -> str:
    n = STORE.clock.now
    return f"{n.year:04d}-{n.month:02d}"


def post_ledger_entry(household_id: str, card_id: str, entry_type: str, amount_cents: int,
                     benefit_month: str = None, reference_id: str = None) -> dict:
    if benefit_month is None:
        benefit_month = benefit_month_from_clock()
    entry_id = gen_id()
    ts = now_iso_utc(STORE.clock.now)
    entry = {
        "id": entry_id,
        "household_id": household_id,
        "card_id": card_id,
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "benefit_month": benefit_month,
        "reference_id": reference_id,
        "created_at": ts,
    }
    STORE.ledger[entry_id] = entry
    return entry


# -----------------------------------------------------------------------------
# Serializers (return shape per resource)
# -----------------------------------------------------------------------------

def serialize_household(h: dict) -> dict:
    return {
        "id": h["id"],
        "case_number": h["case_number"],
        "state_code": h["state_code"],
        "address_zip": h["address_zip"],
        "household_size": h.get("household_size", 0),
        "gross_monthly_income_cents": h.get("gross_monthly_income_cents", 0),
        "net_monthly_income_cents": h.get("net_monthly_income_cents", 0),
        "monthly_allotment_cents": h.get("monthly_allotment_cents", 0),
        "certification_status": h.get("certification_status"),
        "certification_period_end": h.get("certification_period_end"),
        "dependent_care_expense_cents": h.get("dependent_care_expense_cents", 0),
        "shelter_expense_cents": h.get("shelter_expense_cents", 0),
        "has_elderly_or_disabled": h.get("has_elderly_or_disabled", False),
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def serialize_member(m: dict) -> dict:
    return {
        "id": m["id"],
        "household_id": m["household_id"],
        "full_name": m["full_name"],
        "date_of_birth": m["date_of_birth"],
        "is_disabled": m.get("is_disabled", False),
        "is_pregnant": m.get("is_pregnant", False),
        "earned_income_cents": m.get("earned_income_cents", 0),
        "unearned_income_cents": m.get("unearned_income_cents", 0),
        "abawd_status": m.get("abawd_status", "NOT_ABAWD"),
        "abawd_countable_months_used": m.get("abawd_countable_months_used", 0),
        "status": m.get("status", "ACTIVE"),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_application(a: dict) -> dict:
    return {
        "id": a["id"],
        "household_id": a["household_id"],
        "state": a["state"],
        "submitted_at": a.get("submitted_at"),
        "interview_completed_at": a.get("interview_completed_at"),
        "decision_at": a.get("decision_at"),
        "certification_period_start_at": a.get("certification_period_start_at"),
        "certification_period_end_at": a.get("certification_period_end_at"),
        "denial_reason": a.get("denial_reason"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_card(c: dict) -> dict:
    recompute_card_balance(c)
    return {
        "id": c["id"],
        "household_id": c["household_id"],
        "card_number_last4": c["card_number_last4"],
        "status": c["status"],
        "issued_at": c.get("issued_at"),
        "activated_at": c.get("activated_at"),
        "balance_cents": c.get("balance_cents", 0),
        "replaced_by_card_id": c.get("replaced_by_card_id"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_ledger(e: dict) -> dict:
    return {
        "id": e["id"],
        "household_id": e["household_id"],
        "card_id": e["card_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "benefit_month": e["benefit_month"],
        "reference_id": e.get("reference_id"),
        "created_at": e["created_at"],
    }


def serialize_transaction(t: dict) -> dict:
    return {
        "id": t["id"],
        "card_id": t["card_id"],
        "merchant_id": t["merchant_id"],
        "requested_amount_cents": t["requested_amount_cents"],
        "eligible_amount_cents": t.get("eligible_amount_cents", 0),
        "ineligible_amount_cents": t.get("ineligible_amount_cents", 0),
        "status": t["status"],
        "decline_reason": t.get("decline_reason"),
        "line_items": t.get("line_items", []),
        "posted_at": t.get("posted_at"),
        "created_at": t["created_at"],
    }


def serialize_merchant(m: dict) -> dict:
    return {
        "id": m["id"],
        "name": m["name"],
        "snap_authorization_status": m["snap_authorization_status"],
        "authorization_expires_at": m["authorization_expires_at"],
        "hot_food_pilot": m.get("hot_food_pilot", False),
        "state_code": m.get("state_code"),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_fraud_case(c: dict) -> dict:
    return {
        "id": c["id"],
        "household_id": c["household_id"],
        "state": c["state"],
        "trigger_reason": c["trigger_reason"],
        "suspicious_score": c.get("suspicious_score", 0.0),
        "investigator_user_id": c.get("investigator_user_id"),
        "opened_at": c["opened_at"],
        "closed_at": c.get("closed_at"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_waiver(w: dict) -> dict:
    return {
        "id": w["id"],
        "member_id": w["member_id"],
        "waiver_kind": w["waiver_kind"],
        "state": w["state"],
        "effective_from": w["effective_from"],
        "effective_to": w["effective_to"],
        "decision_reason": w.get("decision_reason"),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_ea(e: dict) -> dict:
    return {
        "id": e["id"],
        "state_code": e["state_code"],
        "benefit_month": e["benefit_month"],
        "state": e["state"],
        "max_allotment_table_version": e["max_allotment_table_version"],
        "declared_at": e.get("declared_at"),
        "disbursed_at": e.get("disbursed_at"),
        "cancelled_at": e.get("cancelled_at"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_clock(c) -> dict:
    return {"id": "GLOBAL_CLOCK", "now": now_iso_utc(STORE.clock.now)}


# -----------------------------------------------------------------------------
# Helpers used by routes
# -----------------------------------------------------------------------------

def find_household_or_404(hid: str) -> dict:
    h = STORE.households.get(hid)
    if not h:
        raise ApiError("ERR_NOT_FOUND", 404, "Household not found")
    return h


def find_member_or_404(hid: str, mid: str) -> dict:
    find_household_or_404(hid)
    m = STORE.members.get(mid)
    if not m or m["household_id"] != hid:
        raise ApiError("ERR_NOT_FOUND", 404, "Member not found")
    return m


def find_application_or_404(hid: str, aid: str) -> dict:
    find_household_or_404(hid)
    a = STORE.applications.get(aid)
    if not a or a["household_id"] != hid:
        raise ApiError("ERR_NOT_FOUND", 404, "Application not found")
    return a


def find_card_or_404(hid: str, cid: str) -> dict:
    find_household_or_404(hid)
    c = STORE.cards.get(cid)
    if not c or c["household_id"] != hid:
        raise ApiError("ERR_NOT_FOUND", 404, "Card not found")
    return c


def find_waiver_or_404(hid: str, mid: str, wid: str) -> dict:
    find_member_or_404(hid, mid)
    w = STORE.waivers.get(wid)
    if not w or w["member_id"] != mid:
        raise ApiError("ERR_NOT_FOUND", 404, "Waiver not found")
    return w
