"""Shared domain operations: repricing, settlement, political file, LUC."""
from decimal import Decimal

from core import (add_hours, db, iso, now, touch, touch_station_once)
import pricing
from pricing import (card_unit_rate_cents, round_half_up, raw_spot_charge,
                     scaled_cap_cents, unit_equivalent, volume_discount_pct,
                     agency_commission_pct)

ACTIVE_SPOT_STATUSES = ("SCHEDULED", "AIRED")
LIVE_ORDER_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "SUSPENDED", "RUNNING", "COMPLETED")


def spots_of_order(order):
    rows = [s for s in db.tables["spot"].values() if s["order_id"] == order["id"]]
    rows.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return rows


def orders_of_station(station_id):
    rows = [o for o in db.tables["order"].values() if o["station_id"] == station_id]
    rows.sort(key=lambda o: (o["created_at"], o["_seq"]))
    return rows


# ---------------------------------------------------------------------------
# order_gross_charge + order_net_due
# ---------------------------------------------------------------------------

def reprice_order(order, skip_spot_ids=()):
    """Recompute spot_count, reprice every surviving spot at the reselected
    volume tier, then sum the already-rounded per-spot charges."""
    spots = spots_of_order(order)
    active = [s for s in spots if s["status"] in ACTIVE_SPOT_STATUSES]
    count = len(active)
    pct = volume_discount_pct(count)
    rate_class = db.get("rate_class", order["rate_class_id"])

    for spot in active:
        before = (spot["charged_rate_cents"], spot["unit_equivalent_rate_cents"])
        charged = round_half_up(raw_spot_charge(rate_class, spot["duration_seconds"], pct))
        if spot["luc_capped"] and spot["luc_cap_cents"] is not None:
            charged = min(charged, scaled_cap_cents(spot["luc_cap_cents"], spot["duration_seconds"]))
        spot["charged_rate_cents"] = charged
        spot["unit_equivalent_rate_cents"] = unit_equivalent(charged, spot["duration_seconds"])
        after = (spot["charged_rate_cents"], spot["unit_equivalent_rate_cents"])
        if after != before and spot["id"] not in skip_spot_ids:
            touch(spot)

    for spot in spots:
        if spot["status"] in ("PREEMPTED", "CANCELLED"):
            if spot["charged_rate_cents"] != 0 or spot["unit_equivalent_rate_cents"] != 0:
                spot["charged_rate_cents"] = 0
                spot["unit_equivalent_rate_cents"] = 0
                if spot["id"] not in skip_spot_ids:
                    touch(spot)

    order["spot_count"] = count
    gross = sum(s["charged_rate_cents"] for s in active)
    order["gross_charge_cents"] = gross
    if order["agency_placed"]:
        commission = round_half_up(Decimal(gross) * agency_commission_pct(gross))
    else:
        commission = 0
    order["agency_commission_cents"] = commission
    order["net_due_cents"] = gross + commission
    return order


def refund_owed_cents(order):
    return max(0, order["paid_cents"] - order["refunded_cents"] - order["net_due_cents"])


def settle_after_reprice(order, reason, luc_determination_id=None):
    """Reprice-then-settle: write only the increment not already on the ledger."""
    owed = order["paid_cents"] - order["refunded_cents"] - order["net_due_cents"]
    if owed <= order["rebate_total_cents"]:
        return None
    amount = owed - order["rebate_total_cents"]
    entry = db.insert("rebate", {
        "order_id": order["id"],
        "luc_determination_id": luc_determination_id,
        "amount_cents": amount,
        "reason": reason,
        "occurred_at": iso(now()),
    }, versioned=False)
    order["rebate_total_cents"] = owed
    if order["payment_status"] == "PAID":
        order["payment_status"] = "REFUND_DUE"
    return entry


# ---------------------------------------------------------------------------
# Event-then-file
# ---------------------------------------------------------------------------

def create_file_entry(order, event_type):
    station = db.get("station", order["station_id"])
    occurred = now()
    due = add_hours(occurred, station["political_file_posting_deadline_hours"])
    entry = db.insert("file_entry", {
        "station_id": station["id"],
        "order_id": order["id"],
        "event_type": event_type,
        "event_occurred_at": iso(occurred),
        "due_at": iso(due),
        "posted_at": None,
        "posting_status": "PENDING",
        "late_by_seconds": 0,
        "public_file_url": None,
        "disclosure_snapshot": order["sponsorship_disclosure_text"],
    })
    touch_station_once(station)
    return entry


# ---------------------------------------------------------------------------
# lowest_unit_charge
# ---------------------------------------------------------------------------

def compute_lowest_unit_charge(election, rate_class, variant, exclude_order_id=None):
    window_start = election["window_start_date"]
    window_end = election["window_end_date"]
    spot_statuses = pricing.INCLUDED_SPOT_STATUSES[variant]
    order_statuses = pricing.INCLUDED_ORDER_STATUSES[variant]

    candidates = []
    for spot in db.tables["spot"].values():
        if spot["rate_class_id"] != rate_class["id"]:
            continue
        order = db.get("order", spot["order_id"])
        if order is None:
            continue
        if order["station_id"] != election["station_id"]:
            continue
        if order["election_id"] != election["id"]:
            continue
        if not (window_start <= spot["air_date"] <= window_end):
            continue
        if spot["status"] not in spot_statuses:
            continue
        if order["status"] not in order_statuses:
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        candidates.append(spot)

    if not candidates:
        return {
            "luc_cents": card_unit_rate_cents(rate_class),
            "basis": "POSTED_RATE_FALLBACK",
            "basis_spot_id": None,
            "qualifying_spot_count": 0,
        }

    luc = min(s["unit_equivalent_rate_cents"] for s in candidates)
    winners = [s for s in candidates if s["unit_equivalent_rate_cents"] == luc]
    winners.sort(key=lambda s: (s["created_at"], s["air_date"], s["start_offset_seconds"], s["_seq"]))
    return {
        "luc_cents": luc,
        "basis": "LOWEST_QUALIFYING_SPOT",
        "basis_spot_id": winners[0]["id"],
        "qualifying_spot_count": len(candidates),
    }


def supersede_prior_determination(election_id, rate_class_id, variant):
    for det in db.tables["luc_determination"].values():
        if (det["election_id"] == election_id
                and det["rate_class_id"] == rate_class_id
                and det["variant"] == variant
                and det["status"] == "ACTIVE"):
            det["status"] = "SUPERSEDED"
            touch(det)


def create_determination(election, rate_class, variant, exclude_order_id=None):
    result = compute_lowest_unit_charge(election, rate_class, variant, exclude_order_id)
    supersede_prior_determination(election["id"], rate_class["id"], variant)
    det = db.insert("luc_determination", {
        "station_id": election["station_id"],
        "election_id": election["id"],
        "rate_class_id": rate_class["id"],
        "basis_spot_id": result["basis_spot_id"],
        "variant": variant,
        "luc_cents": result["luc_cents"],
        "basis": result["basis"],
        "qualifying_spot_count": result["qualifying_spot_count"],
        "window_start_date": election["window_start_date"],
        "window_end_date": election["window_end_date"],
        "status": "ACTIVE",
        "computed_at": iso(now()),
        "repriced_spot_count": 0,
        "rebate_total_cents": 0,
    })
    return det


# ---------------------------------------------------------------------------
# luc_final_reprice
# ---------------------------------------------------------------------------

def final_reprice(determination):
    targets = []
    for spot in db.tables["spot"].values():
        if spot["rate_class_id"] != determination["rate_class_id"]:
            continue
        order = db.get("order", spot["order_id"])
        if order is None or order["election_id"] != determination["election_id"]:
            continue
        advertiser = db.get("advertiser", order["advertiser_id"])
        if advertiser is None or advertiser["status"] != "CLASSIFIED_CANDIDATE":
            continue
        if spot["status"] not in ACTIVE_SPOT_STATUSES:
            continue
        if not (determination["window_start_date"] <= spot["air_date"]
                <= determination["window_end_date"]):
            continue
        if spot["unit_equivalent_rate_cents"] <= determination["luc_cents"]:
            continue
        targets.append(spot)

    targets.sort(key=lambda s: (s["created_at"], s["air_date"], s["start_offset_seconds"], s["_seq"]))

    rebate_total = 0
    luc = determination["luc_cents"]
    for spot in targets:
        order = db.get("order", spot["order_id"])
        # hop 1
        spot["charged_rate_cents"] = scaled_cap_cents(luc, spot["duration_seconds"])
        spot["unit_equivalent_rate_cents"] = luc
        spot["luc_cap_cents"] = luc
        spot["luc_capped"] = True
        touch(spot)
        # hop 2
        reprice_order(order, skip_spot_ids=(spot["id"],))
        # hop 3
        entry = settle_after_reprice(order, "LUC_FINAL_REPRICE", determination["id"])
        if entry is not None:
            rebate_total += entry["amount_cents"]
        touch(order)
        # hop 4
        create_file_entry(order, "RATE_ADJUSTMENT")

    determination["repriced_spot_count"] = len(targets)
    determination["rebate_total_cents"] = rebate_total
    return determination


# ---------------------------------------------------------------------------
# Equal opportunity helpers
# ---------------------------------------------------------------------------

def equal_opportunity_owed_units(station, trigger_order):
    spots = [s for s in spots_of_order(trigger_order) if s["status"] in ACTIVE_SPOT_STATUSES]
    basis = station["eo_parity_basis"]
    if basis == "SPOT_COUNT":
        return sum(s["duration_seconds"] // pricing.UNIT_SECONDS for s in spots)
    value = sum(s["charged_rate_cents"] for s in spots)
    rate_class = db.get("rate_class", trigger_order["rate_class_id"])
    reference = card_unit_rate_cents(rate_class)
    if reference <= 0:
        return 0
    return value // reference


def refresh_eo_fulfilled(order):
    for eo in db.tables["eo_request"].values():
        if eo["granted_order_id"] != order["id"] or eo["status"] != "GRANTED":
            continue
        total = 0
        for spot in spots_of_order(order):
            if spot["status"] == "AIRED":
                total += spot["duration_seconds"] // pricing.UNIT_SECONDS
        if eo["fulfilled_units"] != total:
            eo["fulfilled_units"] = total
            touch(eo)


def release_eo_grants(order):
    rows = [eo for eo in db.tables["eo_request"].values()
            if eo["granted_order_id"] == order["id"] and eo["status"] == "GRANTED"]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for eo in rows:
        eo["status"] = "RECEIVED"
        eo["granted_order_id"] = None
        eo["owed_units"] = 0
        eo["fulfilled_units"] = 0
        eo["parity_basis_applied"] = None
        eo["responded_at"] = None
        touch(eo)


# ---------------------------------------------------------------------------
# Order lifecycle helpers
# ---------------------------------------------------------------------------

def cancel_scheduled_spots(order):
    for spot in spots_of_order(order):
        if spot["status"] == "SCHEDULED":
            spot["status"] = "CANCELLED"
            spot["charged_rate_cents"] = 0
            spot["unit_equivalent_rate_cents"] = 0
            touch(spot)


def advance_after_airing(order):
    if order["first_air_at"] is None and order["status"] == "ACCEPTED":
        order["status"] = "RUNNING"
        order["first_air_at"] = iso(now())
        touch(order)
    if order["status"] == "RUNNING":
        remaining = [s for s in spots_of_order(order) if s["status"] == "SCHEDULED"]
        if not remaining:
            order["status"] = "COMPLETED"
            touch(order)


def advance_after_preemption(order):
    if order["status"] == "RUNNING":
        remaining = [s for s in spots_of_order(order) if s["status"] == "SCHEDULED"]
        if not remaining:
            order["status"] = "COMPLETED"
            touch(order)
