"""Shared business logic: calculations, state recomputation, cascades."""

from decimal import Decimal, ROUND_HALF_UP

import store
from store import touch

MGMT_FEE_RATE = Decimal("0.035")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def policy_for_traveler(traveler):
    return store.policies.get(traveler["policy_id"])


def trip_traveler(trip):
    return store.travelers.get(trip["traveler_id"])


# ---------------------------------------------------------------------------
# rate_usage_consumption + ACTIVE<->EXHAUSTED (calc rate_usage_consumption)
# ---------------------------------------------------------------------------
def recompute_rate(rate):
    if rate is None or rate["status"] == "EXPIRED":
        return
    consumed = 0
    for b in store.bookings.values():
        if b.get("negotiated_rate_id") == rate["id"] and b["status"] in ("TICKETED", "EXCHANGED"):
            consumed += 1
    old_consumed = rate["consumed_count"]
    old_status = rate["status"]
    cap = rate["cap_usage_count"]
    if consumed >= cap:
        new_status = "EXHAUSTED"
    else:
        if old_status == "EXHAUSTED":
            # revive only while still within validity window
            valid_to = store.parse_dt(rate["valid_to"])
            new_status = "ACTIVE" if store.now() <= valid_to else "EXHAUSTED"
        else:
            new_status = "ACTIVE"
    if consumed != old_consumed or new_status != old_status:
        rate["consumed_count"] = consumed
        rate["status"] = new_status
        touch(rate)


# ---------------------------------------------------------------------------
# actual_cost_final (calc actual_cost_final)
# ---------------------------------------------------------------------------
def recompute_actual_cost(trip):
    total = 0
    for b in store.bookings.values():
        if b["trip_request_id"] == trip["id"] and b["status"] in ("TICKETED", "EXCHANGED"):
            total += b["fare_cents"] - b["credit_applied_cents"]
    trip["actual_cost_cents"] = total


# ---------------------------------------------------------------------------
# estimate_provisional_cost (calc estimate_provisional_cost)
# ---------------------------------------------------------------------------
def compute_estimate_and_level(trip, policy):
    now = store.now()
    candidates = []
    for r in store.rates.values():
        if r["origin"] != trip["origin"] or r["destination"] != trip["destination"]:
            continue
        if r["status"] != "ACTIVE":
            continue
        vendor = store.vendors.get(r["vendor_id"])
        if not vendor or vendor["status"] != "ACTIVE":
            continue
        vf = store.parse_dt(r["valid_from"])
        vt = store.parse_dt(r["valid_to"])
        if vf <= now <= vt:
            candidates.append(r)
    if candidates:
        candidates.sort(key=lambda r: (r["negotiated_fare_cents"], r["_seq"]))
        estimate = candidates[0]["negotiated_fare_cents"]
    else:
        estimate = trip["market_estimate_cents"]

    if estimate >= policy["requires_exec_approval_over_cents"]:
        level = "EXEC"
    elif estimate >= policy["requires_manager_approval_over_cents"]:
        level = "MANAGER"
    else:
        level = "NONE"
    return estimate, level


# ---------------------------------------------------------------------------
# Unused-ticket credits (calc credit_residual_value)
# ---------------------------------------------------------------------------
def issue_credit(traveler_id, origin_booking_id, vendor_id, value_cents, policy):
    expiry = store.add_days(store.now(), policy["credit_validity_days"])
    rec = {
        "traveler_id": traveler_id,
        "origin_booking_id": origin_booking_id,
        "vendor_id": vendor_id,
        "redeemed_by_booking_id": None,
        "face_value_cents": value_cents,
        "residual_value_cents": value_cents,
        "expiry_date": store.iso(expiry),
        "status": "AVAILABLE",
    }
    store.stamp_new(rec)
    store.credits[rec["id"]] = rec
    return rec


def apply_credit(credit, booking):
    residual_before = credit["residual_value_cents"]
    applied = min(residual_before, booking["fare_cents"])
    booking["credit_applied_cents"] = applied
    credit["residual_value_cents"] = residual_before - applied
    if credit["residual_value_cents"] == 0:
        credit["status"] = "REDEEMED"
        credit["redeemed_by_booking_id"] = booking["id"]
    else:
        credit["status"] = "PARTIALLY_USED"
    touch(credit)
    return applied


# ---------------------------------------------------------------------------
# Booking termination (cancel / refund) — shared by booking cancel and trip
# cancel cascade.
# ---------------------------------------------------------------------------
def terminate_booking(booking):
    """Cancel or refund a TICKETED booking per fare_basis, running the credit +
    rate-release side effects. Does NOT recompute the trip (caller does that once)."""
    trip = store.trips.get(booking["trip_request_id"])
    traveler = store.travelers.get(booking["traveler_id"])
    policy = policy_for_traveler(traveler) if traveler else None

    if booking["fare_basis"] == "NONREFUNDABLE":
        booking["status"] = "CANCELLED"
        touch(booking)
        if policy is not None:
            issue_credit(booking["traveler_id"], booking["id"], booking["vendor_id"],
                         booking["fare_cents"], policy)
    else:
        booking["status"] = "REFUNDED"
        touch(booking)

    # release negotiated-rate capacity (may revive EXHAUSTED -> ACTIVE)
    if booking.get("negotiated_rate_id"):
        recompute_rate(store.rates.get(booking["negotiated_rate_id"]))


# ---------------------------------------------------------------------------
# Savings report (calc realized_vs_potential_savings)
# ---------------------------------------------------------------------------
def savings_report(vendor):
    realized = 0
    potential = 0
    booked_count = 0
    for b in store.bookings.values():
        if b["status"] not in ("TICKETED", "EXCHANGED"):
            continue
        # realized: bookings that actually used a rate of this vendor
        rid = b.get("negotiated_rate_id")
        if rid:
            rate = store.rates.get(rid)
            if rate and rate["vendor_id"] == vendor["id"]:
                realized += rate["market_fare_cents"] - b["fare_cents"]
        # potential: every booking on this vendor
        if b["vendor_id"] == vendor["id"]:
            booked_count += 1
            best = _best_vendor_rate(vendor, b)
            if best is not None:
                potential += best["market_fare_cents"] - best["negotiated_fare_cents"]
    return {
        "realized_savings_cents": realized,
        "potential_savings_cents": potential,
        "booked_count": booked_count,
    }


def _best_vendor_rate(vendor, booking):
    trip = store.trips.get(booking["trip_request_id"])
    if not trip:
        return None
    matches = [
        r for r in store.rates.values()
        if r["vendor_id"] == vendor["id"]
        and r["origin"] == trip["origin"]
        and r["destination"] == trip["destination"]
    ]
    if not matches:
        return None
    matches.sort(key=lambda r: (r["negotiated_fare_cents"], r["_seq"]))
    return matches[0]


# ---------------------------------------------------------------------------
# Invoice reconciliation (calc invoice_reconciliation)
# ---------------------------------------------------------------------------
def reconcile_invoice(invoice):
    lines = [ln for ln in store.invoice_lines.values() if ln["invoice_id"] == invoice["id"]]
    lines.sort(key=lambda x: x["_seq"])
    reconciled_total = 0
    for line in lines:
        if line.get("booking_id") is None:
            line["matched_amount_cents"] = 0
            line["match_status"] = "UNMATCHED"
        else:
            booking = store.bookings.get(line["booking_id"])
            matched = booking["fare_cents"] - booking["credit_applied_cents"] if booking else 0
            line["matched_amount_cents"] = matched
            if line["billed_amount_cents"] == matched:
                line["match_status"] = "MATCHED"
            else:
                line["match_status"] = "PRICE_VARIANCE"
        touch(line)
        fee = _round_half_up_fee(line["matched_amount_cents"])
        reconciled_total += line["matched_amount_cents"] + fee
    invoice["reconciled_total_cents"] = reconciled_total
    invoice["variance_cents"] = invoice["invoiced_total_cents"] - reconciled_total


def _round_half_up_fee(matched_cents):
    fee = (Decimal(matched_cents) * MGMT_FEE_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(fee)


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------
def sorted_by_creation(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
