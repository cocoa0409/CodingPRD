"""Business logic: batch seal/settle, reversal, waiver allocation, auto offers,
charge-off cascade, report metrics. Implements SCAFFOLD §1.3 calculations."""
from datetime import date, timedelta

import db
from serializers import offer_effective_status

TELLER_CAP_CENTS = 5000
SUPERVISOR_CAP_CENTS = 20000
MANAGER_CAP_CENTS = 100000

SCRUTINY_WAIVER_RATIO_BPS = 1500
SCRUTINY_AVG_FEES_CENTI = 1200


def parse_d(s):
    return date.fromisoformat(s)


def get_election(account_id):
    for e in db.store["elections"].values():
        if e["account_id"] == account_id:
            return e
    return None


def is_opted_in(account_id):
    e = get_election(account_id)
    return e is not None and e["status"] == "OPTED_IN"


def create_fee(account_id, batch_id, transaction_id, fee_type, amount_cents,
               status, posted_date):
    f = db.new_entity({
        "account_id": account_id,
        "batch_id": batch_id,
        "transaction_id": transaction_id,
        "fee_type": fee_type,
        "amount_cents": amount_cents,
        "waived_cents": 0,
        "status": status,
        "posted_date": posted_date,
    })
    db.store["fees"][f["id"]] = f
    return f


# ---------------------------------------------------------------------------
# Seal (SCAFFOLD §1.3 posting_order_and_fee_assessment + working_vs_ledger)
# ---------------------------------------------------------------------------

def seal_batch(batch):
    program = db.store["programs"][batch["program_id"]]
    bd = parse_d(batch["business_date"])
    accounts = db.store["accounts"]
    candidates = [
        t for t in db.store["transactions"].values()
        if t["status"] == "AUTHORIZED"
        and parse_d(t["authorized_date"]) <= bd
        and accounts[t["account_id"]]["program_id"] == batch["program_id"]
    ]
    by_acct = {}
    for t in candidates:
        by_acct.setdefault(t["account_id"], []).append(t)
    acct_list = sorted(
        (accounts[aid] for aid in by_acct),
        key=lambda a: (a["created_at"], a["seq"]),
    )
    posted = returned = fee_n = fee_c = 0
    for acct in acct_list:
        items = by_acct[acct["id"]]
        credits = sorted(
            (i for i in items if i["type"] == "CREDIT_DEPOSIT"),
            key=lambda t: (t["authorized_date"], t["created_at"], t["seq"]),
        )
        debits_all = [i for i in items if i["type"] != "CREDIT_DEPOSIT"]
        if program["posting_order_policy"] == "HIGH_TO_LOW":
            debits = sorted(
                debits_all,
                key=lambda t: (-t["amount_cents"], t["authorized_date"], t["created_at"], t["seq"]),
            )
        else:  # CHRONOLOGICAL
            debits = sorted(
                debits_all,
                key=lambda t: (t["authorized_date"], t["created_at"], t["seq"]),
            )
        working = acct["ledger_balance_cents"]
        fc = 0
        fs = 0
        seqn = 0
        for item in credits + debits:
            seqn += 1
            item["batch_id"] = batch["id"]
            item["posting_sequence"] = seqn
            item["posted_date"] = batch["business_date"]
            if item["type"] == "CREDIT_DEPOSIT":
                working += item["amount_cents"]
                item["status"] = "POSTED"
                posted += 1
            else:
                projected = working - item["amount_cents"]
                if projected >= 0:
                    working = projected
                    item["status"] = "POSTED"
                    posted += 1
                else:
                    payable = item["type"] != "DEBIT_ONE_TIME" or is_opted_in(acct["id"])
                    if not payable:
                        item["status"] = "RETURNED_NSF"
                        returned += 1
                    else:
                        working = projected
                        item["status"] = "POSTED"
                        posted += 1
                        if (
                            program["status"] == "ACTIVE"
                            and (-working) > program["de_minimis_threshold_cents"]
                            and fc < program["max_daily_fees_count"]
                            and fs + program["fee_amount_cents"] <= program["daily_fee_cap_cents"]
                        ):
                            create_fee(acct["id"], batch["id"], item["id"],
                                       "OVERDRAFT", program["fee_amount_cents"],
                                       "ASSESSED", None)
                            fc += 1
                            fs += program["fee_amount_cents"]
                            acct["lifetime_fees_assessed_cents"] += program["fee_amount_cents"]
                            fee_n += 1
                            fee_c += program["fee_amount_cents"]
            db.touch(item)
        acct["ledger_balance_cents"] = working
        db.touch(acct)
    batch["items_posted_count"] = posted
    batch["items_returned_count"] = returned
    batch["fees_assessed_count"] = fee_n
    batch["fees_assessed_cents"] = fee_c
    batch["status"] = "SEALED"
    db.touch(batch)


# ---------------------------------------------------------------------------
# Settle (SCAFFOLD §1.3 sustained_overdraft_day_count + steering_fee_trigger)
# ---------------------------------------------------------------------------

def auto_offer_allowed(acct, window_start, window_end):
    for o in db.store["offers"].values():
        if o["account_id"] != acct["id"]:
            continue
        if offer_effective_status(o) == "OFFERED":
            return False
        od = db.parse_ts(o["created_at"]).date()
        if window_start <= od <= window_end:
            return False
    return True


def create_auto_offer(acct, program, trigger_reason):
    expires = db.clock_dt() + timedelta(days=program["offer_expiry_days"])
    o = db.new_entity({
        "account_id": acct["id"],
        "offer_type": "OVERDRAFT_LINE_OF_CREDIT",
        "trigger_reason": trigger_reason,
        "status": "OFFERED",
        "expires_at": db.fmt_ts(expires),
    })
    db.store["offers"][o["id"]] = o
    return o


def charge_off(acct):
    co = -acct["ledger_balance_cents"]
    acct["charged_off_cents"] = co
    acct["charge_off_original_cents"] = co
    acct["recovered_cents"] = 0
    acct["ledger_balance_cents"] = 0
    acct["status"] = "CLOSED_CHARGEOFF"
    for w in db.store["waiver_requests"].values():
        if w["account_id"] == acct["id"] and w["status"] in (
                "PENDING_SUPERVISOR", "PENDING_MANAGER", "PENDING_COMPLIANCE"):
            w["status"] = "DENIED_FINAL"
            db.touch(w)
    for o in db.store["offers"].values():
        if o["account_id"] == acct["id"] and o["status"] == "OFFERED":
            o["status"] = "EXPIRED"
            db.touch(o)


def settle_batch(batch):
    program = db.store["programs"][batch["program_id"]]
    bd = parse_d(batch["business_date"])
    accounts = db.store["accounts"]

    # 1. ASSESSED fees of this batch -> POSTED; amounts debit the ledger.
    affected = set()
    batch_fees = sorted(
        (f for f in db.store["fees"].values()
         if f["batch_id"] == batch["id"] and f["status"] == "ASSESSED"),
        key=lambda f: (f["created_at"], f["seq"]),
    )
    for f in batch_fees:
        f["status"] = "POSTED"
        f["posted_date"] = batch["business_date"]
        db.touch(f)
        acct = accounts[f["account_id"]]
        acct["ledger_balance_cents"] -= f["amount_cents"]
        affected.add(acct["id"])

    # 2. Sustained-overdraft day counting over all ACTIVE/RESTRICTED accounts
    #    of the program (even accounts with no activity this batch).
    window_start = bd - timedelta(days=program["steering_window_days"] - 1)
    accts = sorted(
        (a for a in accounts.values()
         if a["program_id"] == batch["program_id"] and a["status"] in ("ACTIVE", "RESTRICTED")),
        key=lambda a: (a["created_at"], a["seq"]),
    )
    for acct in accts:
        changed = acct["id"] in affected
        if acct["ledger_balance_cents"] < 0:
            acct["consecutive_negative_business_days"] += 1
            changed = True
            if (acct["status"] == "ACTIVE"
                    and acct["consecutive_negative_business_days"]
                    >= program["sustained_overdraft_days_threshold"]):
                acct["status"] = "RESTRICTED"
                acct["restricted_business_days"] = 0
                if program["status"] != "SUSPENDED":
                    create_fee(acct["id"], batch["id"], None, "SUSTAINED",
                               program["sustained_overdraft_fee_cents"],
                               "POSTED", batch["business_date"])
                    acct["ledger_balance_cents"] -= program["sustained_overdraft_fee_cents"]
                    acct["lifetime_fees_assessed_cents"] += program["sustained_overdraft_fee_cents"]
                if auto_offer_allowed(acct, window_start, bd):
                    create_auto_offer(acct, program, "SUSTAINED_OD")
            elif acct["status"] == "RESTRICTED":
                acct["restricted_business_days"] += 1
                if acct["restricted_business_days"] >= program["charge_off_grace_business_days"]:
                    charge_off(acct)
        else:
            if acct["consecutive_negative_business_days"] != 0:
                acct["consecutive_negative_business_days"] = 0
                changed = True
            if acct["status"] == "RESTRICTED":
                acct["status"] = "ACTIVE"
                acct["restricted_business_days"] = 0
                changed = True
        if changed:
            db.touch(acct)

    # 3. Steering sweep (after day counting; statuses re-evaluated).
    steer_accts = sorted(
        (a for a in accounts.values()
         if a["program_id"] == batch["program_id"] and a["status"] in ("ACTIVE", "RESTRICTED")),
        key=lambda a: (a["created_at"], a["seq"]),
    )
    for acct in steer_accts:
        n = 0
        for f in db.store["fees"].values():
            if (f["account_id"] == acct["id"] and f["posted_date"]
                    and window_start <= parse_d(f["posted_date"]) <= bd
                    and f["status"] in ("POSTED", "WAIVED")):
                n += 1
        if n >= program["steering_fee_count_threshold"] and auto_offer_allowed(acct, window_start, bd):
            create_auto_offer(acct, program, "FEE_THRESHOLD")

    batch["status"] = "SETTLED"
    db.touch(batch)


# ---------------------------------------------------------------------------
# Reversal (POSTED -> REVERSED while batch is SEALED)
# ---------------------------------------------------------------------------

def reverse_transaction(txn):
    acct = db.store["accounts"][txn["account_id"]]
    if txn["type"] == "CREDIT_DEPOSIT":
        acct["ledger_balance_cents"] -= txn["amount_cents"]
    else:
        acct["ledger_balance_cents"] += txn["amount_cents"]
    for f in db.store["fees"].values():
        if f["transaction_id"] == txn["id"] and f["status"] == "ASSESSED":
            outstanding = f["amount_cents"] - f["waived_cents"]
            f["status"] = "VOIDED"
            db.touch(f)
            acct["lifetime_fees_waived_cents"] += outstanding
    txn["status"] = "REVERSED"
    db.touch(txn)
    db.touch(acct)


# ---------------------------------------------------------------------------
# Waiver allocation (SCAFFOLD §1.3 waiver_allocation)
# ---------------------------------------------------------------------------

def compute_allocation(kind, amount_cents, percent_bps, fees):
    """Pinned order: created_at ASC, tie amount_cents ASC (never id).
    PERCENT_BPS rounds half-up PER ITEM, then sums."""
    ordered = sorted(fees, key=lambda f: (f["created_at"], f["amount_cents"], f["seq"]))
    allocs = {}
    if kind == "FULL":
        for f in ordered:
            allocs[f["id"]] = f["amount_cents"] - f["waived_cents"]
    elif kind == "FIXED_AMOUNT":
        remaining = amount_cents
        for f in ordered:
            out = f["amount_cents"] - f["waived_cents"]
            a = min(remaining, out)
            allocs[f["id"]] = a
            remaining -= a
    else:  # PERCENT_BPS
        for f in ordered:
            out = f["amount_cents"] - f["waived_cents"]
            allocs[f["id"]] = (out * percent_bps + 5000) // 10000
    return allocs, sum(allocs.values())


def routing_band(total):
    if total <= TELLER_CAP_CENTS:
        return "TELLER"
    if total <= SUPERVISOR_CAP_CENTS:
        return "SUPERVISOR"
    if total <= MANAGER_CAP_CENTS:
        return "MANAGER"
    return "COMPLIANCE"


def apply_waiver(wr, decided_by):
    """Apply allocations against CURRENT outstanding amounts (recomputed)."""
    fees = [db.store["fees"][fid] for fid in wr["fee_ids"]]
    allocs, total = compute_allocation(wr["kind"], wr["amount_cents"], wr["percent_bps"], fees)
    acct = db.store["accounts"][wr["account_id"]]
    for item in db.store["waiver_items"].values():
        if item["waiver_request_id"] == wr["id"]:
            item["waived_cents"] = allocs.get(item["fee_id"], 0)
    seen = set()
    for fid in wr["fee_ids"]:
        if fid in seen:
            continue
        seen.add(fid)
        f = db.store["fees"][fid]
        a = allocs.get(fid, 0)
        if a:
            f["waived_cents"] += a
            if f["amount_cents"] - f["waived_cents"] <= 0:
                f["status"] = "WAIVED"
            db.touch(f)
    if total:
        acct["ledger_balance_cents"] += total
        acct["lifetime_fees_waived_cents"] += total
        db.touch(acct)
    if decided_by is not None:
        wr["decided_by_user_id"] = decided_by


# ---------------------------------------------------------------------------
# Report metrics (SCAFFOLD §1.3 report_revenue_metrics)
# ---------------------------------------------------------------------------

def compute_report_metrics(report):
    start = parse_d(report["period_start"])
    end = parse_d(report["period_end"])
    batches = db.store["batches"]
    prov = 0
    final = 0
    waived_sum = 0
    amount_sum = 0
    pw_count = 0
    overdrafters = set()
    for f in db.store["fees"].values():
        if f["status"] == "VOIDED":
            continue
        b = batches.get(f["batch_id"])
        if b is None or b["program_id"] != report["program_id"]:
            continue
        if f["fee_type"] == "SUSTAINED":
            d = parse_d(f["posted_date"]) if f["posted_date"] else None
        else:
            d = parse_d(b["business_date"])
        if d is None or not (start <= d <= end):
            continue
        net = f["amount_cents"] - f["waived_cents"]
        if f["status"] in ("ASSESSED", "POSTED", "WAIVED"):
            prov += net
        if f["status"] in ("POSTED", "WAIVED"):
            final += net
            waived_sum += f["waived_cents"]
            amount_sum += f["amount_cents"]
            pw_count += 1
            overdrafters.add(f["account_id"])
    ratio = (waived_sum * 10000) // amount_sum if amount_sum else 0
    avg = (pw_count * 100) // len(overdrafters) if overdrafters else 0
    report["revenue_provisional_cents"] = prov
    report["revenue_final_cents"] = final
    report["waiver_ratio_bps"] = ratio
    report["avg_fees_per_overdrafter_centi"] = avg
    report["scrutiny_flag"] = bool(ratio > SCRUTINY_WAIVER_RATIO_BPS or avg >= SCRUTINY_AVG_FEES_CENTI)
