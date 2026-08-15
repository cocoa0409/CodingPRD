"""Domain logic: calculations, ledger recomputation, cascades."""
from decimal import Decimal
from fractions import Fraction

from core import db, create_record, touch, rhu


# --- Calculations (SCAFFOLD §1.3) ---
def season_fee_cents(contract, season):
    k = season - contract["term_first_season"]
    pct = Decimal(str(contract["escalator_pct"]))
    base = Decimal(contract["base_fee_cents"])
    if contract["escalator_mode"] == "COMPOUND":
        fee = base * ((Decimal(1) + pct) ** k)
    else:  # SIMPLE
        fee = base * (Decimal(1) + pct * k)
    return rhu(fee)


def make_good_amount(d):
    """Tiered make-good credit for a (MISSED) deliverable, capped at the season fee."""
    contract = db.contracts[d["contract_id"]]
    asset = db.assets[d["asset_id"]]
    missed_units = d["contracted_units"] - d["approved_units"]
    missed_value = missed_units * asset["rate_card_unit_cents"]
    pct = Fraction(d["approved_units"], d["contracted_units"])
    if pct >= Fraction(9, 10):
        mult = Decimal("1.00")
    elif pct >= Fraction(7, 10):
        mult = Decimal("1.25")
    else:
        mult = Decimal("1.50")
    credit = rhu(Decimal(missed_value) * mult)
    cap = season_fee_cents(contract, d["season"])
    return min(credit, cap)


def seasons_overlap(a_first, a_last, b_first, b_last):
    return a_first <= b_last and b_first <= a_last


# --- Derived ledgers (recomputed from children; bump version only on change) ---
def recompute_receivable(contract):
    total = 0
    for inv in db.invoices.values():
        if inv["contract_id"] == contract["id"] and inv["invoice_status"] in (
                "ISSUED", "PARTIALLY_PAID", "PAID", "WRITTEN_OFF"):
            total += inv["amount_cents"] - inv["paid_cents"] - inv["credits_applied_cents"]
    if contract["receivable_cents"] != total:
        contract["receivable_cents"] = total
        touch(contract)


def recompute_outstanding(contract):
    total = 0
    for cr in db.credits.values():
        if cr["contract_id"] == contract["id"] and cr["credit_status"] == "APPROVED":
            total += cr["approved_amount_cents"] or 0
    if contract["make_good_outstanding_cents"] != total:
        contract["make_good_outstanding_cents"] = total
        touch(contract)


def recompute_rights(contract):
    contested = any(g["contract_id"] == contract["id"] and g["grant_status"] == "CONFLICTED"
                    for g in db.grants.values())
    new = "CONTESTED" if contested else "CLEAR"
    if contract["rights_status"] != new:
        contract["rights_status"] = new
        touch(contract)


def rederive_invoice_status(inv):
    covered = inv["paid_cents"] + inv["credits_applied_cents"]
    if covered <= 0:
        inv["invoice_status"] = "ISSUED"
    elif covered >= inv["amount_cents"]:
        inv["invoice_status"] = "PAID"
    else:
        inv["invoice_status"] = "PARTIALLY_PAID"


# --- Cascades ---
def cancel_deliverable(d):
    d["deliverable_status"] = "CANCELLED"
    touch(d)
    for e in db.evidence.values():
        if e["deliverable_id"] == d["id"] and e["submission_status"] in ("SUBMITTED", "REJECTED"):
            e["submission_status"] = "VOIDED"
            touch(e)


def release_grant(g):
    g["grant_status"] = "RELEASED"
    touch(g)
    recompute_rights(db.contracts[g["contract_id"]])


def terminate_contract(c):
    c["contract_status"] = "TERMINATED"
    touch(c)
    for d in sorted((d for d in db.deliverables.values() if d["contract_id"] == c["id"]),
                    key=lambda r: r["_seq"]):
        if d["deliverable_status"] in ("SCHEDULED", "IN_PROGRESS"):
            cancel_deliverable(d)
    for g in db.grants.values():
        if g["contract_id"] == c["id"] and g["grant_status"] in ("PENDING", "ACTIVE", "CONFLICTED"):
            release_grant(g)
    for inv in db.invoices.values():
        if inv["contract_id"] == c["id"] and inv["invoice_status"] == "DRAFT":
            inv["invoice_status"] = "VOID"
            touch(inv)
    for cr in db.credits.values():
        if cr["contract_id"] == c["id"] and cr["credit_status"] in ("REQUESTED", "APPROVED"):
            cr["credit_status"] = "VOIDED"
            touch(cr)
    recompute_outstanding(c)
    recompute_receivable(c)


def league_contest_sweep(w):
    """LEAGUE window activated: contest overlapping ACTIVE grants in same venue+category."""
    if w["holder"] != "LEAGUE":
        return
    for g in db.grants.values():
        if g["grant_status"] != "ACTIVE":
            continue
        c = db.contracts[g["contract_id"]]
        if c["venue_id"] != w["venue_id"] or g["category"] != w["category"]:
            continue
        if not seasons_overlap(g["first_season"], g["last_season"], w["first_season"], w["last_season"]):
            continue
        g["grant_status"] = "CONFLICTED"
        touch(g)
        recompute_rights(c)


def league_release_sweep(w):
    """Window released/expired: re-activate CONFLICTED grants solely blocked by this window."""
    for g in db.grants.values():
        if g["grant_status"] != "CONFLICTED":
            continue
        c = db.contracts[g["contract_id"]]
        if c["venue_id"] != w["venue_id"] or g["category"] != w["category"]:
            continue
        if not seasons_overlap(g["first_season"], g["last_season"], w["first_season"], w["last_season"]):
            continue
        blocked_elsewhere = any(
            o["id"] != w["id"] and o["holder"] == "LEAGUE" and o["window_status"] == "ACTIVE"
            and o["venue_id"] == w["venue_id"] and o["category"] == g["category"]
            and seasons_overlap(o["first_season"], o["last_season"], g["first_season"], g["last_season"])
            for o in db.rights_windows.values())
        if not blocked_elsewhere:
            g["grant_status"] = "ACTIVE"
            touch(g)
            recompute_rights(c)


def run_countersign(c):
    total = sum(season_fee_cents(c, s)
                for s in range(c["term_first_season"], c["term_last_season"] + 1))
    c["scheduled_total_cents"] = total
    c["contract_status"] = "COUNTERSIGNED"
    a1 = rhu(Decimal(total) * Decimal("0.40"))
    a2 = rhu(Decimal(total) * Decimal("0.30"))
    a3 = total - a1 - a2
    for seq, label, amt in ((1, "SIGNING", a1), (2, "MID_SEASON", a2), (3, "POST_SEASON", a3)):
        create_record(db.invoices, {
            "contract_id": c["id"], "installment_seq": seq, "installment_label": label,
            "amount_cents": amt, "paid_cents": 0, "credits_applied_cents": 0,
            "invoice_status": "DRAFT", "payments": []})
    touch(c)


def advance_season(venue):
    new = venue["current_season"] + 1
    venue["current_season"] = new
    touch(venue)
    # 1) deliverable evaluation (created_at ASC)
    dels = sorted((d for d in db.deliverables.values()
                   if db.contracts[d["contract_id"]]["venue_id"] == venue["id"]),
                  key=lambda r: r["_seq"])
    for d in dels:
        if d["deliverable_status"] == "SCHEDULED" and d["season"] == new:
            d["deliverable_status"] = "IN_PROGRESS"
            touch(d)
        elif (d["deliverable_status"] in ("SCHEDULED", "IN_PROGRESS")
              and d["season"] < new and d["approved_units"] < d["contracted_units"]):
            d["deliverable_status"] = "MISSED"
            touch(d)
            create_record(db.credits, {
                "contract_id": d["contract_id"], "deliverable_id": d["id"],
                "requested_amount_cents": make_good_amount(d),
                "approved_amount_cents": None, "redeemed_against_invoice_id": None,
                "credit_status": "REQUESTED"})
    # 2) contract expiry
    for c in sorted((c for c in db.contracts.values() if c["venue_id"] == venue["id"]),
                    key=lambda r: r["_seq"]):
        if c["contract_status"] in ("ACTIVE", "SUSPENDED") and c["term_last_season"] < new:
            c["contract_status"] = "EXPIRED"
            touch(c)
            for g in db.grants.values():
                if g["contract_id"] == c["id"] and g["grant_status"] in ("ACTIVE", "CONFLICTED"):
                    release_grant(g)
    # 3) rights-window expiry
    for w in sorted((w for w in db.rights_windows.values() if w["venue_id"] == venue["id"]),
                    key=lambda r: r["_seq"]):
        if w["window_status"] == "ACTIVE" and w["last_season"] < new:
            w["window_status"] = "EXPIRED"
            touch(w)
            league_release_sweep(w)
