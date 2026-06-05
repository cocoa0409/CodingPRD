"""Record factory functions: set id, timestamps, version, defaults."""
from db import db, new_id, now_iso


def _versioned(rec):
    ts = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def _append_only(rec):
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["_seq"] = db.next_seq()
    return rec


def make_brokerage(name, total_pct, coop_pct):
    rec = _versioned({
        "name": name,
        "default_total_commission_pct": total_pct,
        "default_coop_split_pct": coop_pct,
    })
    db.brokerages[rec["id"]] = rec
    return rec


def make_agent(brokerage_id, full_name, license_no):
    rec = _versioned({
        "brokerage_id": brokerage_id,
        "full_name": full_name,
        "license_no": license_no,
        "status": "ACTIVE",
    })
    db.agents[rec["id"]] = rec
    return rec


def make_buyer(buyer_agent_id, full_name, max_budget_cents,
               prequalified_amount_cents, monthly_income_cents, monthly_debt_cents):
    rec = _append_only({
        "buyer_agent_id": buyer_agent_id,
        "full_name": full_name,
        "max_budget_cents": max_budget_cents,
        "prequalified_amount_cents": prequalified_amount_cents,
        "monthly_income_cents": monthly_income_cents,
        "monthly_debt_cents": monthly_debt_cents,
    })
    db.buyers[rec["id"]] = rec
    return rec


def make_listing(listing_agent_id, address, list_price_cents, total_pct, coop_pct):
    rec = _versioned({
        "listing_agent_id": listing_agent_id,
        "address": address,
        "list_price_cents": list_price_cents,
        "total_commission_pct": total_pct,
        "coop_split_pct": coop_pct,
        "status": "DRAFT",
        "accepted_offer_id": None,
        "final_sale_price_cents": None,
    })
    db.listings[rec["id"]] = rec
    return rec


def make_lockbox(listing_id, serial_no, access_mode, turnaround_minutes):
    rec = _versioned({
        "listing_id": listing_id,
        "serial_no": serial_no,
        "access_mode": access_mode,
        "turnaround_minutes": turnaround_minutes,
        "status": "INSTALLED",
    })
    db.lockboxes[rec["id"]] = rec
    return rec


def make_showing(lockbox_id, buyer_agent_id, buyer_id, start_at, end_at):
    rec = _versioned({
        "lockbox_id": lockbox_id,
        "buyer_agent_id": buyer_agent_id,
        "buyer_id": buyer_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "REQUESTED",
    })
    db.showings[rec["id"]] = rec
    return rec


def make_offer(listing_id, buyer_id, buyer_agent_id, initial_price_cents,
               earnest_money_cents, requested_contingencies):
    rec = _versioned({
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "buyer_agent_id": buyer_agent_id,
        "initial_price_cents": initial_price_cents,
        "earnest_money_cents": earnest_money_cents,
        "requested_contingencies": requested_contingencies,
        "status": "OPEN",
        "effective_price_cents": None,
    })
    db.offers[rec["id"]] = rec
    return rec


def make_counter(offer_id, round_index, by_party, counter_price_cents, actor_agent_id):
    rec = _append_only({
        "offer_id": offer_id,
        "round_index": round_index,
        "by_party": by_party,
        "counter_price_cents": counter_price_cents,
        "actor_agent_id": actor_agent_id,
    })
    db.counter_rounds[rec["id"]] = rec
    return rec


def make_contingency(offer_id, kind):
    rec = _versioned({
        "offer_id": offer_id,
        "kind": kind,
        "appraised_value_cents": 0,
        "status": "PENDING",
    })
    db.contingencies[rec["id"]] = rec
    return rec


def make_ledger_record(listing_id, sale_price_cents, split):
    rec = _versioned({
        "listing_id": listing_id,
        "sale_price_cents": sale_price_cents,
        "total_commission_cents": split["total_commission_cents"],
        "coop_commission_cents": split["coop_commission_cents"],
        "listing_side_commission_cents": split["listing_side_commission_cents"],
    })
    db.commission_ledgers[rec["id"]] = rec
    return rec
