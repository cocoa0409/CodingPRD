"""Ops-run cascades: season settlement and event completion/cancellation."""
from datetime import timedelta
from decimal import Decimal

import db
import domain
from domain import now
from db import touch


def settle_season(season):
    """Season PUBLISHED -> SETTLED five-part ops cascade (PRD 3.5)."""
    clock = now()
    season_id = season["id"]

    covering = [a for a in db.all_of("agreements")
                if a["status"] in ("ACTIVE", "SUSPENDED", "EXPIRING")
                and domain.agreement_covers_season(a, season_id)]

    # Link 1+2: F&B minimum accrual (net variant) and shortfall invoices
    billed_account_ids = []
    for agr in covering:
        accrued = 0
        for o in db.all_of("catering_orders"):
            if o.get("agreement_id") != agr["id"]:
                continue
            ev = db.get("events", o["event_id"])
            if ev is None or ev["season_id"] != season_id:
                continue
            if o["status"] in ("CONFIRMED", "FULFILLED"):
                accrued += o["subtotal_cents"]
            elif o["status"] == "CANCELLED_LATE":
                accrued += o["cancel_fee_cents"]
        executed_on = agr.get("executed_on")
        if executed_on is None or executed_on <= season["starts_on"]:
            minimum = agr["f_b_minimum_cents"]
        else:
            ratio = domain.proration_ratio(season_id, executed_on)
            minimum = agr["f_b_minimum_cents"] if ratio is None \
                else domain_rhu(Decimal(agr["f_b_minimum_cents"]) * ratio)
        shortfall = max(0, minimum - accrued)
        if shortfall > 0:
            domain.create_auto_invoice(
                account_id=agr["account_id"],
                invoice_type="F_B_SHORTFALL",
                amount_cents=shortfall,
                description="F&B minimum shortfall",
                due_on=clock + timedelta(days=30),
                agreement_id=agr["id"],
                season_id=season_id,
            )
            if agr["account_id"] not in billed_account_ids:
                billed_account_ids.append(agr["account_id"])

    # Link 3: credit cascade on billed accounts
    just_suspended = set()
    for acc_id in billed_account_ids:
        acc = db.get("accounts", acc_id)
        if acc is not None and acc["status"] == "ACTIVE" \
                and domain.account_credit_standing(acc_id) == "HOLD":
            just_suspended.update(domain.suspend_account(acc, "ACCOUNT_DEFAULT"))

    # Link 4: term bookkeeping (after the credit cascade; skip just-suspended agreements)
    for agr in covering:
        if agr["id"] in just_suspended:
            continue
        covered = domain.covered_seasons(agr)
        if not covered:
            continue
        if covered[-1]["id"] == season_id:
            # last covered season settled -> RENEWED or EXPIRED; suite released either way
            agr["status"] = "RENEWED" if agr.get("renewal_agreement_id") else "EXPIRED"
            touch(agr)
            domain.release_suite(agr)
        elif len(covered) >= 2 and covered[-2]["id"] == season_id and agr["status"] == "ACTIVE":
            # next covered season is the last -> EXPIRING
            agr["status"] = "EXPIRING"
            touch(agr)

    # Link 5: sweep stale renewal offers and waitlist entries
    covering_ids = {a["id"] for a in covering}
    for offer in db.all_of("renewal_offers"):
        if offer["agreement_id"] in covering_ids and offer["status"] in ("OFFERED", "REVISED", "COUNTERED") \
                and offer["response_due_on"] < clock:
            offer["status"] = "EXPIRED"
            touch(offer)
    for entry in db.all_of("waitlist_entries"):
        if entry["status"] == "WAITING" and entry.get("target_season_id") == season_id:
            entry["status"] = "EXPIRED"
            touch(entry)

    season["status"] = "SETTLED"
    touch(season)


def domain_rhu(x):
    from util import rhu
    return rhu(x)


def event_cancelled(event):
    """Cascade for Event SCHEDULED -> CANCELLED (PRD 3.1)."""
    for o in db.all_of("catering_orders"):
        if o["event_id"] == event["id"] and o["status"] in ("DRAFT", "PLACED", "CONFIRMED"):
            was_confirmed = o["status"] == "CONFIRMED"
            o["status"] = "CANCELLED"
            o["cancel_fee_cents"] = 0
            o["accrual_cents"] = 0
            touch(o)
            if was_confirmed and o.get("agreement_id"):
                agr = db.get("agreements", o["agreement_id"])
                if agr is not None:
                    touch(agr)  # accrual recomputes down (derived)
    for c in db.all_of("credentials"):
        if c["event_id"] == event["id"] and c["status"] in ("ISSUED", "ACTIVATED"):
            c["status"] = "EXPIRED"
            touch(c)
    for r in db.all_of("rentals"):
        if r["event_id"] == event["id"] and r["status"] in ("QUOTED", "HELD", "CONFIRMED"):
            r["status"] = "CANCELLED"
            r["cancel_fee_cents"] = 0
            touch(r)
            inv_id = r.get("_rental_invoice_id")
            if inv_id:
                inv = db.get("invoices", inv_id)
                if inv is not None and inv["status"] == "ISSUED":
                    inv["status"] = "VOID"
                    touch(inv)
                    acc = db.get("accounts", inv["account_id"])
                    if acc is not None:
                        touch(acc)


def event_completed(event):
    """Cascade for Event SCHEDULED -> COMPLETED (PRD 3.1)."""
    for c in db.all_of("credentials"):
        if c["event_id"] == event["id"] and c["status"] == "ISSUED":
            c["status"] = "EXPIRED"
            touch(c)
    for r in db.all_of("rentals"):
        if r["event_id"] == event["id"] and r["status"] == "CONFIRMED":
            r["status"] = "SETTLED"
            touch(r)
