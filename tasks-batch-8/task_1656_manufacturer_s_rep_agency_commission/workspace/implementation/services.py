"""Business logic: attribution waterfall, rating, allocation, chargebacks,
depreciation, ledger posting, rep posture, re-attribution cascades, sweep."""
from datetime import timedelta

import db
from db import now, touch

# ---------------------------------------------------------------------------
# Global constants (SCAFFOLD constants block + calculation constants)
# ---------------------------------------------------------------------------
PROTECTION_DAYS = 180
RENEWAL_DAYS = 90
RENEWAL_WINDOW_DAYS = 30
RENEWAL_LIMIT = 1
CHECKOUT_DAYS = 30
CHECKOUT_BUFFER_DAYS = 1
RMA_RECEIPT_WINDOW_DAYS = 45
REP_HOLD_FLOOR_CENTS = -50000
LINE_TOLERANCE_CENTS = 25
DRAW_RECOVERY_BP = 5000
DEPRECIATION_STEP_BP = 1500
RESIDUAL_FLOOR_BP = 2000
DAMAGED_RETURN_BP = 5000


# ---------------------------------------------------------------------------
# Integer money math
# ---------------------------------------------------------------------------
def rhu_div(numer, denom):
    """round-half-up of numer/denom to a whole integer (ties away from zero)."""
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def active_agreement(principal_id):
    for ag in sorted(db.agreements.values(), key=lambda a: a["_seq"]):
        if ag["principal_id"] == principal_id and ag["status"] == "ACTIVE":
            return ag
    return None


def latest_agreement(principal_id):
    """The principal's ACTIVE agreement, else its most recent agreement in any
    status. Re-attribution (PRD §3.3/§3.9) still needs the agreement's share
    terms after a termination or expiry cascade has left no ACTIVE agreement."""
    active = active_agreement(principal_id)
    if active is not None:
        return active
    candidates = [a for a in db.agreements.values()
                  if a["principal_id"] == principal_id]
    if not candidates:
        return None
    return sorted(candidates, key=lambda a: a["_seq"])[-1]


def active_schedule(principal_id):
    for rs in sorted(db.rate_schedules.values(), key=lambda r: r["_seq"]):
        if rs["principal_id"] == principal_id and rs["status"] == "ACTIVE":
            return rs
    return None


def active_rep_for_territory(code):
    for rep in sorted(db.reps.values(), key=lambda r: r["_seq"]):
        if rep["status"] == "ACTIVE" and code in (rep["territory_codes"] or []):
            return rep
    return None


def find_protection(principal_id, customer_id, family_code, placed_at):
    """APPROVED registration matching (principal, customer, family) whose
    half-open window [protection_start, protection_end) contains placed_at."""
    for reg in sorted(db.registrations.values(), key=lambda r: r["_seq"]):
        if (reg["status"] == "APPROVED"
                and reg["principal_id"] == principal_id
                and reg["customer_id"] == customer_id
                and reg["family_code"] == family_code
                and reg["protection_start"] is not None
                and reg["protection_start"] <= placed_at < reg["protection_end"]):
            return reg
    return None


def get_principal(pid):
    return db.principals.get(pid)


# ---------------------------------------------------------------------------
# Ledger + rep posture
# ---------------------------------------------------------------------------
def post_entry(rep_id, principal_id, order_id, statement_id, etype,
               amount_cents, ref_line_id=None, business_date=None, note=None):
    entry = {
        "id": db.new_id(),
        "rep_id": rep_id,
        "principal_id": principal_id,
        "order_id": order_id,
        "statement_id": statement_id,
        "type": etype,
        "amount_cents": amount_cents,
        "ref_line_id": ref_line_id,
        "business_date": business_date if business_date is not None else now(),
        "note": note,
        "created_at": now(),
        "_seq": db.next_seq(),
    }
    db.entries[entry["id"]] = entry
    return entry


def recompute_rep(rep_id):
    """Recompute a rep's balance from the ledger and re-evaluate hold posture."""
    rep = db.reps.get(rep_id)
    if rep is None:
        return
    balance = sum(e["amount_cents"] for e in db.entries.values()
                  if e["rep_id"] == rep_id)
    changed = False
    if balance != rep["commission_balance_cents"]:
        rep["commission_balance_cents"] = balance
        changed = True
    if rep["status"] == "ACTIVE" and balance < REP_HOLD_FLOOR_CENTS:
        rep["status"] = "COMMISSION_HOLD"
        changed = True
    elif rep["status"] == "COMMISSION_HOLD" and balance >= 0:
        rep["status"] = "ACTIVE"
        changed = True
    if changed:
        touch(rep)


# ---------------------------------------------------------------------------
# Split row helpers
# ---------------------------------------------------------------------------
def split_rows_for(order_id, line_id=None):
    rows = [s for s in db.splits.values() if s["order_id"] == order_id]
    if line_id is not None:
        rows = [s for s in rows if s["line_id"] == line_id]
    return sorted(rows, key=lambda s: s["_seq"])


def _make_split(order_id, line_id, rep_id, role, share_bp, is_override):
    row = {
        "order_id": order_id,
        "line_id": line_id,
        "rep_id": rep_id,
        "role": role,
        "share_bp": share_bp,
        "is_override": is_override,
    }
    db.stamp_new(row)
    db.splits[row["id"]] = row
    return row


def attribute_line(order, line, agreement):
    """Attribution waterfall for one order line. Creates OrderSplit rows and
    sets line['protected_registration_id']. Precedence REGISTERED > SPECIFY >
    SHIP_TO > HOUSE."""
    reg = find_protection(order["principal_id"], order["customer_id"],
                          line["family_code"], order["placed_at"])
    if reg is not None:
        line["protected_registration_id"] = reg["id"]
        share = agreement["registered_protection_share_bp"]
        if share > 0:
            _make_split(order["id"], line["line_id"], reg["rep_id"],
                        "REGISTERED", share, False)
        residual = 10000 - share
        if residual > 0:
            _make_split(order["id"], line["line_id"], None,
                        "HOUSE", residual, False)
        return
    line["protected_registration_id"] = None
    spec = active_rep_for_territory(line["spec_territory_code"])
    ship = active_rep_for_territory(line["ship_to_territory_code"])
    if spec is not None and ship is not None and spec["id"] == ship["id"]:
        _make_split(order["id"], line["line_id"], spec["id"], "SPECIFY", 10000, False)
    elif spec is not None and ship is not None:
        ssb = agreement["specify_share_bp"]
        if ssb > 0:
            _make_split(order["id"], line["line_id"], spec["id"], "SPECIFY", ssb, False)
        if 10000 - ssb > 0:
            _make_split(order["id"], line["line_id"], ship["id"], "SHIP_TO",
                        10000 - ssb, False)
    elif spec is not None:
        _make_split(order["id"], line["line_id"], spec["id"], "SPECIFY", 10000, False)
    elif ship is not None:
        _make_split(order["id"], line["line_id"], ship["id"], "SHIP_TO", 10000, False)
    else:
        _make_split(order["id"], line["line_id"], None, "HOUSE", 10000, False)


def _alloc_sort_key(row):
    rep = db.reps.get(row["rep_id"]) if row["rep_id"] else None
    rep_created = rep["created_at"] if rep else None
    # share_bp DESC, then rep created_at ASC (house rows last), then row seq
    return (-row["share_bp"],
            0 if rep is not None else 1,
            rep_created if rep_created is not None else db.now(),
            rep["_seq"] if rep is not None else 0,
            row["_seq"])


def allocate(total_cents, rows, total_weight=10000):
    """Largest-remainder allocation of total_cents across split rows.
    raw = floor(total * share_bp / total_weight); residual cents dealt one by
    one to rows ordered share_bp DESC, tie-break Rep.created_at ASC.
    Returns {split_row_id: cents}."""
    alloc = {}
    for r in rows:
        alloc[r["id"]] = (total_cents * r["share_bp"]) // total_weight
    residual = total_cents - sum(alloc.values())
    ordered = sorted(rows, key=_alloc_sort_key)
    i = 0
    while residual > 0 and ordered:
        alloc[ordered[i % len(ordered)]["id"]] += 1
        residual -= 1
        i += 1
    return alloc


# ---------------------------------------------------------------------------
# Quota attainment + rating
# ---------------------------------------------------------------------------
def select_tier(schedule, attainment_bp):
    """Largest min_attainment_bp such that attainment_bp >= min (inclusive)."""
    best = None
    for t in schedule["attainment_tiers"]:
        if attainment_bp >= t["min_attainment_bp"]:
            if best is None or t["min_attainment_bp"] > best["min_attainment_bp"]:
                best = t
    return best


def attainment_bp(principal):
    quota = principal["annual_quota_cents"]
    if not quota:
        return 0
    return (principal["credited_ytd_sales_cents"] * 10000) // quota


def current_multiplier(principal, schedule):
    tier = select_tier(schedule, attainment_bp(principal))
    return tier["multiplier_bp"] if tier else 10000


def family_base_rate(schedule, family_code):
    for fr in schedule["family_rates"]:
        if fr["family_code"] == family_code:
            return fr["base_rate_bp"]
    return None


# ---------------------------------------------------------------------------
# Re-attribution cascade (registration expired/withdrawn, line terminated)
# ---------------------------------------------------------------------------
def reattribute_for_registration(reg):
    """Drop REGISTERED attribution on uninvoiced orders (PLACED/SHIPPED) whose
    lines referenced this registration; re-resolve precedence. Override rows
    are never touched."""
    for order in sorted(db.orders.values(), key=lambda o: o["_seq"]):
        if order["principal_id"] != reg["principal_id"]:
            continue
        if order["fulfillment_status"] not in ("PLACED", "SHIPPED"):
            continue
        order_rows = split_rows_for(order["id"])
        if any(r["is_override"] for r in order_rows):
            continue  # manual override survives everything
        agreement = latest_agreement(order["principal_id"])
        touched_order = False
        for line in order["lines"]:
            if line.get("protected_registration_id") != reg["id"]:
                continue
            for row in split_rows_for(order["id"], line["line_id"]):
                del db.splits[row["id"]]
            line["protected_registration_id"] = None
            if agreement is not None:
                attribute_line(order, line, agreement)
            touched_order = True
        if touched_order:
            touch(order)


def expire_registration(reg, counts=None):
    if reg["status"] != "APPROVED":
        return
    reg["status"] = "EXPIRED"
    touch(reg)
    if counts is not None:
        counts["registrations_expired"] += 1
    reattribute_for_registration(reg)


# ---------------------------------------------------------------------------
# Sample depreciation
# ---------------------------------------------------------------------------
def depreciated_value(value_cents, checked_out_at, event_at):
    days = (event_at - checked_out_at).total_seconds() // 86400
    months_started = int(days // 30)
    factor_bp = max(RESIDUAL_FLOOR_BP, 10000 - DEPRECIATION_STEP_BP * months_started)
    return rhu_div(value_cents * factor_bp, 10000)


# ---------------------------------------------------------------------------
# Epoch sweep — runs synchronously on every clock advance
# ---------------------------------------------------------------------------
def run_sweep():
    ts = now()
    counts = {
        "principals_terminated": 0,
        "agreements_terminated": 0,
        "agreements_expired": 0,
        "registrations_expired": 0,
        "rmas_expired": 0,
        "sample_checkouts_charged": 0,
        "ytd_rollovers": 0,
        "holds_released": 0,
    }

    # 1. Principal terminations (NOTICE_PENDING -> TERMINATED) + cascades
    for p in sorted(db.principals.values(), key=lambda x: x["_seq"]):
        if p["status"] == "NOTICE_PENDING" and p["termination_effective_at"] <= ts:
            p["status"] = "TERMINATED"
            touch(p)
            counts["principals_terminated"] += 1
            for ag in sorted(db.agreements.values(), key=lambda a: a["_seq"]):
                if (ag["principal_id"] == p["id"]
                        and ag["status"] in ("ACTIVE", "SUSPENDED")):
                    ag["status"] = "TERMINATED"
                    touch(ag)
                    counts["agreements_terminated"] += 1
            for reg in sorted(db.registrations.values(), key=lambda r: r["_seq"]):
                if reg["principal_id"] == p["id"] and reg["status"] == "APPROVED":
                    expire_registration(reg, counts)

    # 2. Agreement expiry at effective_end
    for ag in sorted(db.agreements.values(), key=lambda a: a["_seq"]):
        if (ag["status"] == "ACTIVE" and ag["effective_end"] is not None
                and ag["effective_end"] <= ts):
            ag["status"] = "EXPIRED"
            touch(ag)
            counts["agreements_expired"] += 1
            for reg in sorted(db.registrations.values(), key=lambda r: r["_seq"]):
                if reg["principal_id"] == ag["principal_id"] and reg["status"] == "APPROVED":
                    expire_registration(reg, counts)

    # 3. Registration natural expiry at protection_end
    for reg in sorted(db.registrations.values(), key=lambda r: r["_seq"]):
        if (reg["status"] == "APPROVED" and reg["protection_end"] is not None
                and reg["protection_end"] <= ts):
            expire_registration(reg, counts)

    # 4. RMA expiry past receipt window
    for rma in sorted(db.rmas.values(), key=lambda r: r["_seq"]):
        if (rma["status"] == "APPROVED"
                and rma["approved_at"] + timedelta(days=RMA_RECEIPT_WINDOW_DAYS) <= ts):
            rma["status"] = "EXPIRED"
            rma["provisional_chargeback_cents"] = None
            touch(rma)
            counts["rmas_expired"] += 1

    # 5. Overdue sample checkouts
    for co in sorted(db.checkouts.values(), key=lambda c: c["_seq"]):
        if co["status"] == "OPEN" and ts > co["due_at"]:
            unit = db.sample_units.get(co["sample_unit_id"])
            charge = depreciated_value(unit["value_cents"], co["checked_out_at"], ts)
            co["charge_cents"] = charge
            co["status"] = "CHARGED"
            touch(co)
            post_entry(rep_id=co["rep_id"], principal_id=unit["principal_id"],
                       order_id=None, statement_id=None, etype="SAMPLE_CHARGE",
                       amount_cents=-charge, business_date=ts)
            unit["status"] = "WRITTEN_OFF"
            touch(unit)
            recompute_rep(co["rep_id"])
            counts["sample_checkouts_charged"] += 1

    # 6. Calendar-year rollover of credited YTD pools
    for p in sorted(db.principals.values(), key=lambda x: x["_seq"]):
        if ts.year > p["ytd_year"]:
            p["credited_ytd_sales_cents"] = 0
            p["ytd_year"] = ts.year
            touch(p)
            counts["ytd_rollovers"] += 1

    # 7. COMMISSION_HOLD release on recovered balances
    for rep in sorted(db.reps.values(), key=lambda r: r["_seq"]):
        if rep["status"] == "COMMISSION_HOLD":
            balance = sum(e["amount_cents"] for e in db.entries.values()
                          if e["rep_id"] == rep["id"])
            if balance != rep["commission_balance_cents"]:
                rep["commission_balance_cents"] = balance
            if balance >= 0:
                rep["status"] = "ACTIVE"
                touch(rep)
                counts["holds_released"] += 1

    return counts
