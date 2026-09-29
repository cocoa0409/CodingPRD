"""Domain engine: pricing, charge breakdown, ledger, settlement, seat pools."""
from datetime import timedelta
from decimal import Decimal

from common import (DB, bp_of, clock, floor_div, new_record, parse_iso, rhu,
                    to_iso, rows)

DOW_BP = {"MON": 9500, "TUE": 9500, "WED": 9500, "THU": 10000, "FRI": 11500,
          "SAT": 12500, "SUN": 11000}
TIER_BP = {"LOW": 9000, "STANDARD": 10000, "HIGH": 12000, "PEAK": 14500}
BP_FLOOR = 8500
BP_CAP = 18000
SEVERITY_PREP_MINUTES = {"INFO": 0, "ALLERGY": 6, "ANAPHYLAXIS": 15}
FORFEITURE_LADDERS = {
    "STANDARD": [(72, 0), (24, 5000), (0, 10000)],
    "STRICT": [(168, 0), (72, 5000), (24, 8000), (0, 10000)],
}
INBOUND_KINDS = ("DEPOSIT_CHARGE", "BALANCE_CHARGE", "GOODWILL_REDEMPTION",
                 "TRANSFER_IN")
POSITIVE_KINDS = ("DEPOSIT_CHARGE", "BALANCE_CHARGE", "GOODWILL_REDEMPTION",
                  "TRANSFER_IN", "FORFEITURE_REVERSAL")
LIVE_SEATED = ("CONFIRMED", "SEATED")
COUNTED_SOLD = ("CONFIRMED", "SEATED", "COMPLETED")


# ------------------------------------------------------------------- lookups


def service_of(rec):
    return DB["services"][rec["service_id"]]


def restaurant_of_service(service):
    return DB["restaurants"][service["restaurant_id"]]


def ticket_class_of(res):
    return DB["ticket_classes"][res["ticket_class_id"]]


def package_of_class(tc):
    return DB["packages"][tc["package_id"]]


def package_of_res(res):
    return package_of_class(ticket_class_of(res))


def restaurant_of_res(res):
    return restaurant_of_service(service_of(res))


def classes_of_service(service_id):
    return [tc for tc in rows("ticket_classes") if tc["service_id"] == service_id]


def reservations_of_service(service_id):
    return [r for r in rows("reservations") if r["service_id"] == service_id]


def reservations_of_class(ticket_class_id):
    return [r for r in rows("reservations")
            if r["ticket_class_id"] == ticket_class_id]


def lines_of(reservation_id):
    return [l for l in rows("reservation_add_ons")
            if l["reservation_id"] == reservation_id]


def notes_of(reservation_id):
    return [n for n in rows("dietary_notes")
            if n["reservation_id"] == reservation_id]


def txns_of(reservation_id):
    return [t for t in rows("payment_transactions")
            if t["reservation_id"] == reservation_id]


def entries_of_service(service_id):
    return [e for e in rows("waitlist_entries") if e["service_id"] == service_id]


def entries_of_guest(guest_id):
    return [e for e in rows("waitlist_entries") if e["guest_id"] == guest_id]


def minutes(count):
    return timedelta(minutes=int(count))


# ------------------------------------------------------------------- pricing


def combined_bp(service):
    dow = DOW_BP[service["day_of_week"]]
    tier = TIER_BP[service["demand_tier"]]
    return rhu(dow * tier, 10000)


def effective_bp(service):
    value = combined_bp(service)
    if value < BP_FLOOR:
        value = BP_FLOOR
    if value > BP_CAP:
        value = BP_CAP
    return value


def scarcity_bp(sell_through):
    if sell_through >= 8000:
        return 1500
    if sell_through >= 5000:
        return 800
    return 0


def sell_through_of(tc):
    allocated = tc["seats_allocated"]
    if allocated <= 0:
        return 0
    return floor_div((tc["seats_sold"] + tc["seats_held"]) * 10000, allocated)


def price_per_cover(tc, from_release_pool):
    """Steps 1-5 of §3.2 against the class's current counters."""
    service = service_of(tc)
    package = package_of_class(tc)
    list_price = bp_of(package["base_price_cents"], effective_bp(service))
    quoted = bp_of(list_price, 10000 + scarcity_bp(sell_through_of(tc)))
    if from_release_pool:
        quoted = bp_of(quoted, 10000 - package["release_discount_bp"])
    return quoted


def derive_class_status(tc):
    """The pinned precedence ladder of §2.6."""
    if tc["status"] == "PAUSED":
        return "PAUSED"
    if tc["status"] == "CLOSED":
        return "CLOSED"
    if tc["seats_released"] > 0:
        return "RELEASED"
    if tc["seats_available"] > 0:
        return "OPEN"
    return "SOLD_OUT"


def sync_class(tc, w=None):
    """Re-derive the class's computed fields and its ladder status."""
    if w is not None:
        w.add(tc)
    tc["seats_available"] = (tc["seats_allocated"] - tc["seats_sold"]
                            - tc["seats_held"] - tc["seats_released"])
    tc["sell_through_bp"] = sell_through_of(tc)
    tc["list_price_per_cover_cents"] = price_per_cover(tc, False)
    tc["release_price_per_cover_cents"] = price_per_cover(tc, True)
    tc["status"] = derive_class_status(tc)
    return tc


# ------------------------------------------------------- charges and the ledger


def sync_lines(res):
    """Pinned per-line order: add-on name asc, then the line's created_at asc."""
    lines = lines_of(res["id"])
    charge_bp = restaurant_of_res(res)["service_charge_bp"]
    ordered = sorted(
        lines,
        key=lambda l: (DB["add_ons"][l["add_on_id"]]["name"], l["created_at"],
                       l["_seq"]))
    add_on_total = 0
    line_charges = 0
    for line in ordered:
        line["line_subtotal_cents"] = line["unit_price_cents_locked"] * line["qty"]
        line["line_service_charge_cents"] = bp_of(line["line_subtotal_cents"],
                                                 charge_bp)
        add_on_total += line["line_subtotal_cents"]
        line_charges += line["line_service_charge_cents"]
    return add_on_total, line_charges, ordered


def charge_breakdown(res):
    package = package_of_res(res)
    charge_bp = restaurant_of_res(res)["service_charge_bp"]
    res["ticket_subtotal_cents"] = (res["price_locked_per_cover_cents"]
                                    * res["party_size"])
    ticket_charge = bp_of(res["ticket_subtotal_cents"], charge_bp)
    add_on_total, line_charges, _ordered = sync_lines(res)
    res["add_on_total_cents"] = add_on_total
    res["service_charge_cents"] = ticket_charge + line_charges
    res["grand_total_cents"] = (res["ticket_subtotal_cents"]
                                + res["add_on_total_cents"]
                                + res["service_charge_cents"])
    if package["prepayment_mode"] == "FULL":
        res["deposit_due_cents"] = res["grand_total_cents"]
    elif not res["deposit_frozen"]:
        res["deposit_due_cents"] = bp_of(res["grand_total_cents"],
                                         package["deposit_bp"])
    res["balance_due_cents"] = max(
        0, res["grand_total_cents"] - res["amount_paid_cents"])


def ledger_rollup(res):
    paid = refunded = forfeited = reversed_ = goodwill = 0
    for txn in txns_of(res["id"]):
        kind = txn["kind"]
        amount = txn["amount_cents"]
        if kind in INBOUND_KINDS:
            paid += amount
        if kind == "REFUND":
            refunded += amount
        if kind == "FORFEITURE":
            forfeited += amount
        if kind == "FORFEITURE_REVERSAL":
            reversed_ += amount
        if kind == "GOODWILL_REDEMPTION":
            goodwill += amount
    res["amount_paid_cents"] = paid
    res["refunded_cents"] = refunded
    res["forfeited_cents"] = forfeited - reversed_
    res["goodwill_applied_cents"] = goodwill


def derive_payment_status(res):
    if res["fulfillment_status"] == "TRANSFERRED_OUT":
        return "TRANSFERRED"
    paid = res["amount_paid_cents"]
    if paid == 0:
        return "UNPAID"
    if res["refunded_cents"] + res["forfeited_cents"] == 0:
        if paid >= res["grand_total_cents"]:
            return "FULLY_PAID"
        if paid >= res["deposit_due_cents"]:
            return "DEPOSIT_PAID"
        return "UNPAID"
    if res["refunded_cents"] == paid:
        return "REFUNDED"
    if res["forfeited_cents"] == paid:
        return "FORFEITED"
    return "PARTIALLY_REFUNDED"


def prep_minutes_total(res):
    package = package_of_res(res)
    total = res["party_size"] * package["kitchen_prep_minutes_per_cover"]
    for note in notes_of(res["id"]):
        total += SEVERITY_PREP_MINUTES[note["severity"]]
    for line in lines_of(res["id"]):
        add_on = DB["add_ons"][line["add_on_id"]]
        total += add_on["prep_minutes_per_unit"] * line["qty"]
    return total


def sync_reservation(res, w=None):
    if w is not None:
        w.add(res)
    ledger_rollup(res)
    charge_breakdown(res)
    res["prep_minutes_total"] = prep_minutes_total(res)
    res["payment_status"] = derive_payment_status(res)
    return res


def write_txn(res, kind, amount_cents, memo_code, goodwill_credit_id=None):
    signed = amount_cents if kind in POSITIVE_KINDS else -amount_cents
    return new_record("payment_transactions", {
        "reservation_id": res["id"],
        "goodwill_credit_id": goodwill_credit_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "signed_amount_cents": signed,
        "memo_code": memo_code,
    }, versioned=False)


# ---------------------------------------------------------- parent roll-ups


def sync_service(service, w=None):
    if w is not None:
        w.add(service)
    covers = 0
    gross = refunded = forfeited = reversed_ = 0
    for res in reservations_of_service(service["id"]):
        if res["fulfillment_status"] in COUNTED_SOLD:
            covers += res["party_size"]
        for txn in txns_of(res["id"]):
            if txn["kind"] in INBOUND_KINDS:
                gross += txn["amount_cents"]
            elif txn["kind"] == "REFUND":
                refunded += txn["amount_cents"]
            elif txn["kind"] == "FORFEITURE":
                forfeited += txn["amount_cents"]
            elif txn["kind"] == "FORFEITURE_REVERSAL":
                reversed_ += txn["amount_cents"]
    service["covers_confirmed"] = covers
    service["gross_charged_cents"] = gross
    service["refunded_cents"] = refunded
    service["forfeited_cents"] = forfeited - reversed_
    service["net_settled_cents"] = gross - refunded
    return service


# ------------------------------------------------------------ guest counters


def score_of(entry, guest):
    value = (1000
             + 50 * entry["party_size"]
             + 25 * min(guest["completed_reservations_count"], 8)
             - 300 * guest["no_show_strikes"]
             - 200 * (1 if entry["priority_penalty_applied"] else 0)
             - 100 * entry["offer_round"])
    return value if value > 0 else 0


def rescore(entry, w=None):
    if w is not None:
        w.add(entry)
    entry["priority_score"] = score_of(entry, DB["guests"][entry["guest_id"]])
    return entry


def rescore_guest_entries(guest, w):
    for entry in entries_of_guest(guest["id"]):
        if entry["status"] in ("WAITING", "OFFERED"):
            rescore(entry, w)


def credit_guest_refund(res, amount_cents, w):
    """§3.7: every REFUND row moves lifetime_refunded_cents and may flag."""
    if amount_cents <= 0:
        return
    guest = DB["guests"][res["guest_id"]]
    restaurant = restaurant_of_res(res)
    w.add(guest)
    guest["lifetime_refunded_cents"] += amount_cents
    if guest["lifetime_refunded_cents"] > restaurant["refund_scrutiny_threshold_cents"]:
        guest["refund_scrutiny_flag"] = True
        for entry in entries_of_guest(guest["id"]):
            if entry["status"] == "WAITING":
                w.add(entry)
                entry["priority_penalty_applied"] = True
                rescore(entry, w)
    rescore_guest_entries(guest, w)


# ---------------------------------------------------------------- settlement


def hours_to_service(res):
    service = service_of(res)
    delta = parse_iso(service["seating_start_utc"]) - clock()
    return Decimal(int(delta.total_seconds())) / Decimal(3600)


def rebooking_fee(raw_forfeiture):
    if raw_forfeiture == 0:
        return 0
    if raw_forfeiture <= 9999:
        return 500
    if raw_forfeiture <= 39999:
        return 1500
    return 3000


def settle(res, trigger):
    """§3.7 steps 1-7. trigger: GUEST_CANCEL|NO_SHOW|SERVICE_CANCEL|HOLD_LAPSE"""
    package = package_of_res(res)
    paid = res["amount_paid_cents"]
    if trigger == "SERVICE_CANCEL":
        basis_code = "RESTAURANT_INITIATED"
    elif trigger == "NO_SHOW":
        basis_code = "NO_SHOW_FULL"
    else:
        basis_code = package["forfeiture_basis"]
    if (basis_code == "RESTAURANT_INITIATED" or trigger == "HOLD_LAPSE"
            or res["fulfillment_status"] == "PENDING"):
        refund = paid - res["refunded_cents"] if trigger == "SERVICE_CANCEL" else paid
        return {"basis_code": basis_code, "band_bp": 0, "raw": 0, "fee": 0,
                "retained": 0, "refund": max(0, refund)}
    if basis_code == "NO_SHOW_FULL":
        return {"basis_code": basis_code, "band_bp": 10000, "raw": 0, "fee": 0,
                "retained": paid, "refund": 0}
    hours = hours_to_service(res)
    band_bp = 10000
    for min_hours, band in FORFEITURE_LADDERS[package["forfeiture_schedule_code"]]:
        if hours >= Decimal(min_hours):
            band_bp = band
            break
    basis = (res["deposit_due_cents"] if basis_code == "DEPOSIT_BASIS"
             else res["grand_total_cents"])
    raw = bp_of(basis, band_bp)
    fee = rebooking_fee(raw)
    retained = min(paid, raw + fee)
    return {"basis_code": basis_code, "band_bp": band_bp, "raw": raw, "fee": fee,
            "retained": retained, "refund": paid - retained}


def apply_settlement(res, trigger, memo_code, w):
    """Runs the settlement, writes its ledger rows and re-derives the row."""
    result = settle(res, trigger)
    res["cancel_settlement_basis"] = result["basis_code"]
    if result["retained"] > 0:
        write_txn(res, "FORFEITURE", result["retained"], memo_code)
    if result["refund"] > 0:
        write_txn(res, "REFUND", result["refund"], memo_code)
    sync_reservation(res, w)
    credit_guest_refund(res, result["refund"], w)
    return result


# ------------------------------------------------------------- seat movement


def return_seats(tc, res, w):
    """Return a lapsing or cancelled hold's seats to their originating pool."""
    tc["seats_held"] -= res["party_size"]
    if res["is_release_priced"]:
        tc["seats_released"] += res["party_size"]
    else:
        tc["seats_available"] += res["party_size"]
    sync_class(tc, w)


def mint_reservation(tc, guest, party_size, primary_guest_name, from_release, w):
    """Creates a PENDING hold, drawing seats from the pinned pool."""
    service = service_of(tc)
    restaurant = restaurant_of_service(service)
    price = price_per_cover(tc, from_release)
    res = new_record("reservations", {
        "service_id": service["id"],
        "ticket_class_id": tc["id"],
        "guest_id": guest["id"],
        "assigned_table_id": None,
        "transferred_from_reservation_id": None,
        "party_size": party_size,
        "primary_guest_name": primary_guest_name,
        "fulfillment_status": "PENDING",
        "payment_status": "UNPAID",
        "is_release_priced": bool(from_release),
        "price_locked_per_cover_cents": price,
        "ticket_subtotal_cents": 0,
        "add_on_total_cents": 0,
        "service_charge_cents": 0,
        "grand_total_cents": 0,
        "deposit_due_cents": 0,
        "deposit_frozen": False,
        "balance_due_cents": 0,
        "amount_paid_cents": 0,
        "goodwill_applied_cents": 0,
        "refunded_cents": 0,
        "forfeited_cents": 0,
        "hold_expires_at_utc": to_iso(clock() + minutes(restaurant["hold_ttl_minutes"])),
        "seat_from_utc": None,
        "seat_to_utc": None,
        "prep_minutes_total": 0,
        "name_change_count": 0,
        "cancel_settlement_basis": None,
    })
    w.add(tc)
    tc["seats_held"] += party_size
    if from_release:
        tc["seats_released"] -= party_size
    else:
        tc["seats_available"] -= party_size
    sync_class(tc, w)
    sync_reservation(res)
    return res


# ------------------------------------------------------------------ waitlist


def rank_candidates(entries, service):
    def email_of(entry):
        return DB["guests"][entry["guest_id"]]["email"]

    if service["waitlist_policy"] == "YIELD_WEIGHTED":
        return sorted(entries, key=lambda e: (-e["priority_score"],
                                              e["created_at"], email_of(e),
                                              e["_seq"]))
    return sorted(entries, key=lambda e: (e["created_at"], email_of(e),
                                          e["_seq"]))


def eligible_entries(tc, pool_field, w):
    service = service_of(tc)
    restaurant = restaurant_of_service(service)
    out = []
    for entry in entries_of_service(service["id"]):
        if entry["status"] != "WAITING":
            continue
        if not (tc["min_party_size"] <= entry["party_size"] <= tc["max_party_size"]):
            continue
        if entry["requested_package_id"] not in (None, tc["package_id"]):
            continue
        if entry["offer_round"] >= restaurant["max_offer_rounds"]:
            continue
        if tc[pool_field] < entry["party_size"]:
            continue
        rescore(entry, w)
        out.append(entry)
    return rank_candidates(out, service)


def promote_one(tc, pool_field, w):
    """§3.8 promotion. Returns the promoted entry, or None when none fits."""
    if tc["status"] in ("PAUSED", "CLOSED"):
        return None
    candidates = eligible_entries(tc, pool_field, w)
    if not candidates:
        return None
    entry = candidates[0]
    service = service_of(tc)
    restaurant = restaurant_of_service(service)
    guest = DB["guests"][entry["guest_id"]]
    res = mint_reservation(tc, guest, entry["party_size"], guest["display_name"],
                           pool_field == "seats_released", w)
    w.add(entry)
    entry["status"] = "OFFERED"
    entry["offered_reservation_id"] = res["id"]
    entry["offer_expires_at_utc"] = to_iso(
        clock() + minutes(restaurant["offer_ttl_minutes"]))
    rescore(entry, w)
    return entry


def promote_after_restore(tc, previous_status, w):
    """SOL_OUT -> OPEN after a cancellation or a no-show promotes one entry."""
    if previous_status == "SOLD_OUT" and tc["status"] == "OPEN":
        promote_one(tc, "seats_available", w)
