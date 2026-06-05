"""PurchaseAgreement service — lifecycle (DRAFT -> ACTIVE -> UNDER_CONTRACT ->
CLEARED_TO_CLOSE -> CLOSED) plus TERMINATED branches (PRD §3.1, §3.5, §3.6).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from flask import g

from calculations import (
    DISBURSEMENT_PURPOSE_ORDER,
    disbursement_sort_key,
    earnest_deposit_refund_sort_key,
)
from clock import CLOCK, parse_iso
from db import DB_INSTANCE, new_id
from errors import (
    ERR_BUYER_WIRE_NOT_LOCKED,
    ERR_CCR_NOT_ACKNOWLEDGED,
    ERR_CD_NOT_ACKNOWLEDGED,
    ERR_FK_NOT_FOUND,
    ERR_INSUFFICIENT_ESCROW_FUNDS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PRICE_OUT_OF_RANGE,
    ERR_WIRE_NOT_LOCKED,
    err,
)
from exchange_eval import evaluate_exchange_account
from lookup import (
    get_agreement_or_404,
    get_fk_exchange,
)
from validation import (
    require_bool,
    require_fields,
    require_int,
    require_str,
)


def _bump(entity: dict) -> None:
    entity["version"] += 1
    entity["updated_at"] = CLOCK.now()


def _recompute_earnest_received(agreement_id: str) -> int:
    total = 0
    for d in DB_INSTANCE.earnest_money_deposits.values():
        e = DB_INSTANCE.escrow_accounts.get(d["escrow_account_id"])
        if e is None:
            continue
        if e["agreement_id"] != agreement_id:
            continue
        if d["status"] == "CONFIRMED":
            total += d["amount_cents"]
    return total


def _recompute_balance(escrow_id: str) -> int:
    confirmed = 0
    for d in DB_INSTANCE.earnest_money_deposits.values():
        if d["escrow_account_id"] == escrow_id and d["status"] == "CONFIRMED":
            confirmed += d["amount_cents"]
    disbursed = 0
    for d in DB_INSTANCE.disbursements.values():
        if d["escrow_account_id"] == escrow_id and d["status"] == "DISBURSED":
            disbursed += d["amount_cents"]
    return confirmed - disbursed


# ---------------------------------------------------------------------------
# Create / read / list
# ---------------------------------------------------------------------------


def create_purchase_agreement(body: dict) -> dict:
    require_fields(body, [
        "buyer_name",
        "seller_name",
        "property_address",
        "purchase_price_cents",
        "earnest_money_required_cents",
        "scheduled_closing_date",
    ])
    buyer_name = require_str(body, "buyer_name")
    seller_name = require_str(body, "seller_name")
    property_address = require_str(body, "property_address")
    purchase_price_cents = require_int(body, "purchase_price_cents")
    earnest_money_required_cents = require_int(body, "earnest_money_required_cents")
    scheduled_iso = require_str(body, "scheduled_closing_date")
    try:
        scheduled = parse_iso(scheduled_iso)
    except ValueError as exc:
        raise err(ERR_INVALID_REQUEST, "scheduled_closing_date must be ISO 8601") from exc

    exchange_account_id = body.get("exchange_account_id")
    if exchange_account_id is not None:
        if not isinstance(exchange_account_id, str) or exchange_account_id == "":
            raise err(ERR_INVALID_REQUEST, "exchange_account_id must be a non-empty string")
        # FK check (priority 4).
        get_fk_exchange(exchange_account_id)

    # Business constraint (priority 19) AFTER FK & invalid-request shape checks.
    if not (100_000 <= purchase_price_cents <= 1_000_000_000_000):
        raise err(ERR_PRICE_OUT_OF_RANGE, "purchase_price_cents out of [100000, 1_000_000_000_000]")
    if earnest_money_required_cents < 0:
        raise err(ERR_INVALID_REQUEST, "earnest_money_required_cents must be >= 0")

    now = CLOCK.now()
    agreement = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "buyer_name": buyer_name,
        "seller_name": seller_name,
        "property_address": property_address,
        "purchase_price_cents": purchase_price_cents,
        "earnest_money_required_cents": earnest_money_required_cents,
        "scheduled_closing_date": scheduled,
        "exchange_account_id": exchange_account_id,
        "status": "DRAFT",
        "earnest_money_received_cents": 0,
        "terminated_reason": None,
    }
    DB_INSTANCE.purchase_agreements[agreement["id"]] = agreement
    return agreement


def list_purchase_agreements(filters: dict[str, Any]) -> list[dict]:
    items = list(DB_INSTANCE.purchase_agreements.values())
    status_q = filters.get("status")
    exchange_q = filters.get("exchange_account_id")
    if status_q:
        items = [a for a in items if a["status"] == status_q]
    if exchange_q:
        items = [a for a in items if a.get("exchange_account_id") == exchange_q]
    items.sort(key=lambda a: a["created_at"])
    return items


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


def activate(agreement_id: str) -> dict:
    a = get_agreement_or_404(agreement_id)
    if a["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "agreement is not in DRAFT")
    # Precondition: all required fields non-null. They're required at create
    # time (validated above), but enforce as documented for the transition.
    for field in (
        "buyer_name",
        "seller_name",
        "property_address",
        "purchase_price_cents",
        "earnest_money_required_cents",
        "scheduled_closing_date",
    ):
        if a.get(field) is None:
            raise err(ERR_INVALID_STATE, f"missing {field} for activation")
    now = CLOCK.now()
    escrow = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "agreement_id": a["id"],
        "escrow_officer_id": g.user_id,
        "balance_cents": 0,
        "status": "OPEN",
    }
    DB_INSTANCE.escrow_accounts[escrow["id"]] = escrow
    a["status"] = "ACTIVE"
    _bump(a)
    return a


def _ensure_close_preconditions(a: dict) -> None:
    """Run the §1.4 priority-ordered preconditions for clear-to-close and close."""
    # Computed elsewhere; nothing to do here.
    pass


def clear_to_close(agreement_id: str) -> dict:
    a = get_agreement_or_404(agreement_id)
    # Priority 5: state precondition — must be UNDER_CONTRACT.
    if a["status"] != "UNDER_CONTRACT":
        raise err(ERR_INVALID_STATE, "agreement is not in UNDER_CONTRACT")

    # Priority 11 (business_safety): every WireInstruction for this agreement must be LOCKED.
    wires = [w for w in DB_INSTANCE.wire_instructions.values() if w["agreement_id"] == agreement_id]
    if any(w["status"] != "LOCKED" for w in wires):
        raise err(ERR_WIRE_NOT_LOCKED, "all wire instructions for this agreement must be LOCKED")

    # Priority 14 (business_referential): CD must be ACKNOWLEDGED.
    cds = [cd for cd in DB_INSTANCE.closing_disclosures.values() if cd["agreement_id"] == agreement_id]
    if not any(cd["status"] == "ACKNOWLEDGED" for cd in cds):
        raise err(ERR_CD_NOT_ACKNOWLEDGED, "no ACKNOWLEDGED ClosingDisclosure")

    # Priority 15 (business_referential): a CCRReview with buyer_acknowledged=true.
    ccrs = [
        c for c in DB_INSTANCE.ccr_reviews.values()
        if c["agreement_id"] == agreement_id and c["buyer_acknowledged"] is True
    ]
    if not ccrs:
        raise err(ERR_CCR_NOT_ACKNOWLEDGED, "no CCRReview with buyer_acknowledged=true")

    # Per PRD §3.5: also need exactly one resolved-and-insurable TitleSearch and an
    # ISSUED TitleInsurancePolicy whose underlying search traces back to the
    # agreement; title gate failures surface as ERR_INVALID_STATE.
    resolved_searches = [
        t for t in DB_INSTANCE.title_searches.values()
        if t["agreement_id"] == agreement_id
        and t["status"] == "RESOLVED"
        and t["has_material_defect"] is False
    ]
    if len(resolved_searches) < 1:
        raise err(ERR_INVALID_STATE, "no RESOLVED TitleSearch with has_material_defect=false")

    issued_policies = []
    for p in DB_INSTANCE.title_insurance_policies.values():
        if p["status"] != "ISSUED":
            continue
        ts = DB_INSTANCE.title_searches.get(p["title_search_id"])
        if ts and ts["agreement_id"] == agreement_id:
            issued_policies.append(p)
    if len(issued_policies) < 1:
        raise err(ERR_INVALID_STATE, "no ISSUED TitleInsurancePolicy for this agreement")

    # current clock >= CD.earliest_consummation_at — enforced via the ACKNOWLEDGED CD's earliest_consummation_at.
    ack = next(cd for cd in cds if cd["status"] == "ACKNOWLEDGED")
    if CLOCK.now() < ack["earliest_consummation_at"]:
        # Cannot occur in practice (ACKNOWLEDGED implies we already crossed the wait), but defence-in-depth.
        raise err(ERR_INVALID_STATE, "earliest_consummation_at not yet reached")

    a["status"] = "CLEARED_TO_CLOSE"
    _bump(a)
    return a


def close_agreement(agreement_id: str) -> dict:
    a = get_agreement_or_404(agreement_id)
    if a["status"] != "CLEARED_TO_CLOSE":
        raise err(ERR_INVALID_STATE, "agreement is not in CLEARED_TO_CLOSE")

    # Locate escrow.
    escrow = next(
        (e for e in DB_INSTANCE.escrow_accounts.values() if e["agreement_id"] == agreement_id),
        None,
    )
    if escrow is None:
        # Cannot occur in practice, but defence-in-depth.
        raise err(ERR_INVALID_STATE, "no EscrowAccount for this agreement")

    # If exchange-routed, the ExchangeAccount must be OPEN/IDENTIFIED and clock <= exchange_deadline.
    if a.get("exchange_account_id") is not None:
        x = DB_INSTANCE.exchange_accounts.get(a["exchange_account_id"])
        if x is None:
            raise err(ERR_INVALID_STATE, "exchange_account missing for this agreement")
        evaluate_exchange_account(x)
        if x["status"] not in ("OPEN", "IDENTIFIED"):
            raise err(ERR_INVALID_STATE, "ExchangeAccount not in OPEN/IDENTIFIED at close")
        if CLOCK.now() > x["exchange_deadline"]:
            raise err(ERR_INVALID_STATE, "exchange_deadline has elapsed")

    # Priority 20 fiscal sufficiency: balance >= sum(QUEUED disbursements).
    queued = [
        d for d in DB_INSTANCE.disbursements.values()
        if d["escrow_account_id"] == escrow["id"] and d["status"] == "QUEUED"
    ]
    total_queued = sum(d["amount_cents"] for d in queued)
    if escrow["balance_cents"] < total_queued:
        raise err(ERR_INSUFFICIENT_ESCROW_FUNDS, "escrow balance insufficient for queued disbursements")

    # Run waterfall in created_at ASC, tie-broken by purpose lex.
    queued.sort(key=disbursement_sort_key)
    remaining = escrow["balance_cents"]
    for d in queued:
        if remaining < d["amount_cents"]:
            # Defence-in-depth (already pre-checked above).
            raise err(ERR_INSUFFICIENT_ESCROW_FUNDS, "escrow balance underflow during waterfall")
        d["status"] = "DISBURSED"
        d["updated_at"] = CLOCK.now()
        d["version"] += 1
        remaining -= d["amount_cents"]

    # EscrowAccount FUNDED -> DISBURSED -> CLOSED (two state writes, +2 version).
    escrow["status"] = "DISBURSED"
    escrow["version"] += 1
    escrow["updated_at"] = CLOCK.now()
    escrow["status"] = "CLOSED"
    escrow["version"] += 1
    escrow["updated_at"] = CLOCK.now()
    escrow["balance_cents"] = _recompute_balance(escrow["id"])

    # ExchangeAccount IDENTIFIED -> COMPLETED if applicable.
    if a.get("exchange_account_id") is not None:
        x = DB_INSTANCE.exchange_accounts[a["exchange_account_id"]]
        if x["status"] == "IDENTIFIED":
            x["status"] = "COMPLETED"
            x["version"] += 1
            x["updated_at"] = CLOCK.now()

    a["status"] = "CLOSED"
    _bump(a)
    return a


def terminate(agreement_id: str, body: dict) -> dict:
    a = get_agreement_or_404(agreement_id)
    if a["status"] not in ("ACTIVE", "UNDER_CONTRACT"):
        raise err(ERR_INVALID_STATE, "agreement cannot be terminated from this state")

    terminated_reason = body.get("terminated_reason")
    if not isinstance(terminated_reason, str) or terminated_reason == "":
        raise err(ERR_INVALID_REQUEST, "terminated_reason must be non-empty")

    escrow = next(
        (e for e in DB_INSTANCE.escrow_accounts.values() if e["agreement_id"] == agreement_id),
        None,
    )
    if escrow is None:
        raise err(ERR_INVALID_STATE, "no EscrowAccount for this agreement")

    # UNDER_CONTRACT branch requires a TitleSearch with has_material_defect=true.
    if a["status"] == "UNDER_CONTRACT":
        searches = [
            t for t in DB_INSTANCE.title_searches.values()
            if t["agreement_id"] == agreement_id and t["has_material_defect"] is True
        ]
        if not searches:
            raise err(
                ERR_INVALID_STATE,
                "UNDER_CONTRACT termination requires a TitleSearch with has_material_defect=true",
            )
        target_status = "CONFIRMED"
    else:
        # ACTIVE -> TERMINATED: refund PENDING deposits.
        target_status = "PENDING"

    # Priority 12 (business_safety): BUYER WireInstruction for this agreement must be LOCKED if any deposits will refund.
    deposits = [
        d for d in DB_INSTANCE.earnest_money_deposits.values()
        if d["escrow_account_id"] == escrow["id"] and d["status"] == target_status
    ]

    if deposits:
        buyer_locked = [
            w for w in DB_INSTANCE.wire_instructions.values()
            if w["agreement_id"] == agreement_id
            and w["party"] == "BUYER"
            and w["status"] == "LOCKED"
        ]
        if not buyer_locked:
            raise err(ERR_BUYER_WIRE_NOT_LOCKED, "BUYER WireInstruction must be LOCKED before refund")
        buyer_wire = buyer_locked[0]

        # Emit one refund Disbursement per deposit, ordered by deposit (created_at, depositor_role).
        deposits_sorted = sorted(deposits, key=earnest_deposit_refund_sort_key)
        for d in deposits_sorted:
            now = CLOCK.now()
            disb = {
                "id": new_id(),
                "created_at": now,
                "updated_at": now,
                "version": 1,
                "escrow_account_id": escrow["id"],
                "wire_instruction_id": buyer_wire["id"],
                "purpose": "EARNEST_REFUND",
                "amount_cents": d["amount_cents"],
                "status": "QUEUED",
            }
            DB_INSTANCE.disbursements[disb["id"]] = disb
            d["status"] = "REFUNDED"
            d["updated_at"] = CLOCK.now()
            d["version"] += 1

    # Escrow OPEN/FUNDED -> CLOSED, +1 version.
    escrow["status"] = "CLOSED"
    escrow["version"] += 1
    escrow["updated_at"] = CLOCK.now()
    escrow["balance_cents"] = _recompute_balance(escrow["id"])

    a["status"] = "TERMINATED"
    a["terminated_reason"] = terminated_reason
    _bump(a)
    # Recompute received cents since deposits may have flipped to REFUNDED.
    a["earnest_money_received_cents"] = _recompute_earnest_received(agreement_id)

    return a
